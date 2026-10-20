#!/usr/bin/env python3
"""One bounded Instagram session per UK day, with an owned macOS emulator.

Private settings, queue, journals and logs live in accounts/<username>/growth.
This runner never retries a started day, clears a fault, or discovers new targets.
"""
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import public_comments

UK = ZoneInfo("Europe/London")
HANDLE = re.compile(r"[a-z0-9_][a-z0-9_.]{0,29}\Z")
STOP = re.compile(
    r"serius block detected|probably block dialog|seems that action is blocked|"
    r"action blocked overlay detected|challenge_required|captcha required|"
    r"we restrict certain activity|confirm you.re human|account has been compromised|"
    r"watchdog.*tier[\s-]*[123]|Traceback \(most recent call last\)|"
    r"App has crashed / has been closed|"
    r"Profile grid unavailable after failed post open|"
    r"Could not return from Peek Preview|Can't go back to the profile|"
    r"Multiple consecutive post open failures|Can't find the post element|Crash saved as", re.I
)
GIB = 1024 ** 3


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as out:
        os.chmod(temp, 0o600)
        json.dump(value, out, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def now():
    return datetime.now(UK).isoformat()


def daily_totals(sessions, day):
    """Include manual sessions and sessions spanning midnight. Fail closed on bad data."""
    totals = {"follows": 0, "likes": 0}
    ids = set()
    for session in sessions:
        sid = session["id"]
        if sid in ids:
            raise ValueError("Duplicate session IDs require review")
        ids.add(sid)
        start = datetime.fromisoformat(session["start_time"])
        start = start.replace(tzinfo=UK) if start.tzinfo is None else start.astimezone(UK)
        finish_text = session.get("finish_time")
        if finish_text in (None, "None"):
            raise ValueError("Unfinished bot session requires review")
        finish = datetime.fromisoformat(finish_text)
        finish = finish.replace(tzinfo=UK) if finish.tzinfo is None else finish.astimezone(UK)
        if start.date().isoformat() <= day <= finish.date().isoformat():
            for name, field in (("follows", "total_followed"), ("likes", "total_likes")):
                count = session[field]
                if type(count) is not int or count < 0:
                    raise ValueError("Invalid session action counter")
                totals[name] += count
    return totals


def accounting_totals(sessions, day, journals):
    totals = daily_totals(sessions, day)
    by_id = {s["id"]: s for s in sessions}
    charged = set()
    configs, runs = set(), set()
    for journal in journals:
        if journal.get("day") != day:
            continue
        for key, seen in (("config", configs), ("startedAt", runs)):
            identity = journal.get(key)
            if identity is not None:
                if identity in seen:
                    raise ValueError("Duplicate daily journal run")
                seen.add(identity)
        ids = journal.get("sessionIds", [])
        if len(ids) != len(set(ids)) or any(sid in charged for sid in ids):
            raise ValueError("Duplicate daily journal session IDs")
        charged.update(ids)
        saved = [by_id[sid] for sid in ids if sid in by_id]
        for session in saved:
            stamps = [datetime.fromisoformat(session[key]) for key in ("start_time", "finish_time")]
            start, finish = [stamp.replace(tzinfo=UK) if stamp.tzinfo is None else stamp.astimezone(UK) for stamp in stamps]
            if not start.date().isoformat() <= day <= finish.date().isoformat():
                raise ValueError("Linked saved session does not belong to the journal day")
        observed = len(set(journal.get("observedFollowHandles", [])))
        recorded = sum(s["total_followed"] for s in saved)
        totals["follows"] += max(0, observed - recorded)
        reservation = journal.get("reservedLikeBudget", None if journal.get("config") else 0)
        if type(reservation) is not int or reservation < 0:
            raise ValueError("Missing or invalid like reservation requires review")
        if reservation and any(s.get("args", {}).get("config") != journal.get("config") for s in saved):
            raise ValueError("Like reservation requires matching saved sessions")
        totals["likes"] += max(0, reservation - sum(s["total_likes"] for s in saved))
    return totals


def select_targets(manifest, interacted, journals, username, count):
    consumed = {h for j in journals for h in j.get("targets", [])}
    selected = []
    for entry in manifest["targets"]:
        handle = entry["handle"]
        if not HANDLE.fullmatch(handle) or handle == username:
            raise ValueError("Invalid target handle")
        for field in ("sourceUrl", "instagramUrl", "trade", "serviceArea", "evidence"):
            if not entry.get(field):
                raise ValueError("Every target needs source evidence")
        if not entry["sourceUrl"].startswith("https://"):
            raise ValueError("Target source must use HTTPS")
        if entry["instagramUrl"].rstrip("/") != "https://www.instagram.com/" + handle:
            raise ValueError("Target URL does not match handle")
        # Never revisit a processed or previously interacted profile automatically.
        if handle not in consumed and handle not in interacted and handle not in selected:
            selected.append(handle)
    return selected[:count]


def bot_config(username, targets, follows, likes):
    if not targets or not 1 <= follows <= 5 or not 1 <= likes <= 10:
        raise ValueError("No action budget")
    likes_each = min(2, likes // len(targets))
    if likes_each < 1 or len(targets) > follows:
        raise ValueError("Target batch exceeds action budget")
    return {
        "username": username, "device": "emulator-5554", "app-id": "com.instagram.android",
        "screen-sleep": False, "speed-multiplier": 1, "no-tui": True,
        "allow-untested-ig-version": True, "disable-block-detection": False,
        "close-apps": False, "screen-record": False, "total-sessions": 1,
        "total-crashes-limit": 1, "count-app-crashes": True,
        "blogger": targets, "truncate-sources": len(targets),
        "interactions-count": 1, "total-interactions-limit": len(targets),
        "total-successful-interactions-limit": len(targets),
        "likes-count": likes_each, "likes-percentage": 100, "follow-percentage": 100,
        "stories-count": 0, "stories-percentage": 0, "comment-percentage": 0,
        "pm-percentage": 0, "total-likes-limit": likes, "total-follows-limit": follows,
        "total-unfollows-limit": 0, "total-comments-limit": 0, "total-pm-limit": 0,
        "total-watches-limit": 0, "end-if-likes-limit-reached": True,
        "end-if-follows-limit-reached": True, "can-reinteract-after": 168,
        "watch-video-time": "3-5", "watch-photo-time": "2-3", "no-harvest-hashtags": True,
    }


def preflight(repo, config_path):
    sys.path.insert(0, str(repo))
    from InstaAddict.core.config import Config
    previous = sys.argv
    try:
        sys.argv = ["run.py", "--config", str(config_path)]
        c = Config(first_run=False)
        a = c.args
        if c.enabled != ["blogger"] or c.unknown_args or a.disable_block_detection:
            raise ValueError("Unexpected job or disabled restriction detection")
        if a.repeat or int(a.total_sessions) != 1 or a.telegram_inbox or a.telegram_reports:
            raise ValueError("Unexpected repeat or messaging integration")
        if not a.count_app_crashes or int(a.total_crashes_limit) != 1:
            raise ValueError("App crashes must stop the session")
        for key in ("comment_percentage", "pm_percentage", "total_comments_limit", "total_pm_limit", "total_unfollows_limit"):
            if int(getattr(a, key)) != 0:
                raise ValueError("Messaging/unfollowing must remain disabled")
    finally:
        sys.argv = previous


def stop_process(proc):
    if proc is None or proc.poll() is not None:
        return
    for sig, timeout in ((signal.SIGINT, 20), (signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            continue
        except ProcessLookupError:
            return


def saved_bot_job(account, growth, config_path, day):
    sessions = read_json(account / "sessions.json", [])
    daily_totals(sessions, day)
    previous = {s["id"] for s in read_json(growth / "sessions-before.json", [])}
    relevant = [s for s in sessions if s["id"] not in previous and s.get("args", {}).get("config") == str(config_path)]
    if len(relevant) != 1:
        raise ValueError("Expected one new matching saved bot job")
    for session in relevant:
        start = datetime.fromisoformat(session["start_time"])
        finish = datetime.fromisoformat(session["finish_time"])
        start = start.replace(tzinfo=UK) if start.tzinfo is None else start.astimezone(UK)
        finish = finish.replace(tzinfo=UK) if finish.tzinfo is None else finish.astimezone(UK)
        if start.date().isoformat() != day or finish < start:
            raise ValueError("Saved bot job does not belong to this UK day")
        if (session.get("total_crashes", 0) or session.get("total_watchdog_recoveries", 0)
                or session.get("job_metrics", {}).get("blogger", {}).get("status") != "completed"):
            raise ValueError("Bot job did not complete without recovery")
        if any(session.get(field, 0) for field in ("total_comments", "total_pm", "total_unfollowed", "total_uploads_success")):
            raise ValueError("Unexpected messaging, unfollow or publishing action")
    return relevant


def run_comment_phase(repo, account, growth, day, env, vm, started, log):
    status, pending, _ = public_comments.plan(growth, day)
    if status["reviewRequired"]:
        raise ValueError("Uncertain comment intent requires review")
    if not status["enabled"] or not status["remaining"] or not pending:
        return status
    if account.name != public_comments.ACCOUNT:
        raise ValueError("Prepared comments support only uk.tradeleads")
    phase_started = time.monotonic()

    def check():
        if (growth / "paused.json").exists():
            raise RuntimeError("Paused by operator")
        if datetime.now(UK).date().isoformat() != day:
            raise RuntimeError("Comment phase reached the next UK day")
        if vm.poll() is not None:
            raise RuntimeError("Emulator exited during comments")
        if time.monotonic() - phase_started >= 180 or time.monotonic() - started >= 1440:
            raise RuntimeError("Comment phase time limit")
        if shutil.disk_usage(repo).free < 3 * GIB:
            raise RuntimeError("Disk reserve reached during comments")
        if log.tell() > 10 * 1024 * 1024:
            raise RuntimeError("Log size limit")

    check()
    helper = subprocess.Popen([str(repo / ".venv/bin/python"), "-u", str(repo / "scripts/public_comments.py"),
                               "--account", account.name, "--day", day, "--repo", str(repo)],
                              cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=log,
                              stderr=subprocess.STDOUT, start_new_session=True)
    try:
        while True:
            check()
            if helper.poll() is not None:
                break
            time.sleep(1)
        if helper.returncode != 0:
            raise RuntimeError("Comment helper exited unsuccessfully")
    finally:
        stop_process(helper)
        public_comments.recover_reservations(growth)
    status = public_comments.plan(growth, day)[0]
    if status["reviewRequired"]:
        raise ValueError("Uncertain comment intent requires review")
    return status


def run_session(repo, account, growth):
    import yaml
    day = datetime.now(UK).date().isoformat()
    journal_path = growth / "days" / (day + ".json")
    state_path = growth / "state.json"
    if (growth / "paused.json").exists() or (growth / "fault.json").exists():
        print("Paused. Read status before resuming.")
        return 0
    journals = [read_json(p) for p in sorted((growth / "days").glob("*.json"))]
    if any(j.get("status") == "running" for j in journals):
        raise ValueError("An unfinished daily run requires review")
    if journal_path.exists():
        print("Today's session already started; no automatic retry.")
        return 0
    settings = read_json(growth / "settings.json")
    if settings != {"dailyFollows": 5, "dailyLikes": 10, "timezone": "Europe/London"}:
        raise ValueError("Unexpected daily settings")
    totals = accounting_totals(read_json(account / "sessions.json", []), day, journals)
    if totals["follows"] > 5 or totals["likes"] > 10:
        raise ValueError("Daily action limit already exceeded")
    follows, likes = max(0, 5 - totals["follows"]), max(0, 10 - totals["likes"])
    targets = select_targets(read_json(growth / "queue.json", {"targets": []}), read_json(account / "interacted_users.json", {}), journals, account.name, min(follows, likes))
    public_comments.recover_reservations(growth)
    comments, pending_comments, _ = public_comments.plan(growth, day)
    if comments["reviewRequired"]:
        raise ValueError("Uncertain comment intent requires review")
    if comments["enabled"] and account.name != public_comments.ACCOUNT:
        raise ValueError("Prepared comments support only uk.tradeleads")
    if not targets and not (comments["enabled"] and comments["remaining"] and pending_comments):
        write_json(state_path, {"status": "queue_empty_or_budget_used", "checkedAt": now(), "totals": totals, "comments": comments})
        print("No fresh targets or daily budget remains. Refill the reviewed queue when empty.")
        return 0
    free = shutil.disk_usage(repo).free
    if free < 8 * GIB:
        write_json(state_path, {"status": "low_disk_skipped", "checkedAt": now(), "freeGiB": round(free / GIB, 2)})
        print("Skipped: need 8 GiB free before starting Android.")
        return 0
    sdk = Path.home() / "Library/Android/sdk"
    env = dict(os.environ, ADB_USB="0", ANDROID_HOME=str(sdk), INSTAADDICT_NO_TELEGRAM_INBOX="1", PYTHONUNBUFFERED="1")
    env["PATH"] = str(sdk / "platform-tools") + ":" + str(sdk / "emulator") + ":/opt/homebrew/bin:" + env.get("PATH", "/usr/bin:/bin")
    adb = str(sdk / "platform-tools/adb")
    def adb_call(*args, timeout=10):
        return subprocess.run([adb, *args], env=env, capture_output=True, text=True, timeout=timeout, check=True).stdout
    adb_call("start-server", timeout=20)
    if "emulator-5554" in adb_call("devices"):
        write_json(state_path, {"status": "emulator_busy_skipped", "checkedAt": now()})
        print("Skipped: emulator is already in use.")
        return 0
    processes = subprocess.check_output(["/bin/ps", "-axo", "command="], text=True)
    if any("run.py" in line and "--config" in line for line in processes.splitlines()):
        raise ValueError("Another bot process is running")
    filters = yaml.safe_load((account / "filters.yml").read_text())
    if any(value for key, value in filters.items() if key.startswith("comment_") or key == "pm_to_private_or_empty"):
        raise ValueError("Account filters allow comments or private messages")
    if any(filters.get(key) is not True for key in ("skip_if_private", "skip_following", "skip_follower")) or filters.get("follow_private_or_empty") is not False:
        raise ValueError("Account filters must skip private and existing connections")
    config_path = None
    if targets:
        conf = bot_config(account.name, targets, follows, likes)
        config_path = growth / (datetime.now(UK).strftime("%Y-%m-%d-%H%M%S") + ".yml")
        # JSON arrays are also YAML flow arrays accepted by ConfigArgParse.
        config_path.write_text("\n".join(key + ": " + json.dumps(value) for key, value in conf.items()) + "\n")
        os.chmod(config_path, 0o600)
        preflight(repo, config_path)
    journal = {"day": day, "startedAt": now(), "status": "running", "targets": targets, "config": str(config_path) if config_path else None, "budgetBefore": totals, "limits": {"follows": follows, "likes": likes}, "comments": comments, "reservedLikeBudget": 0}
    write_json(journal_path, journal)
    write_json(state_path, journal)
    vm = bot = caffeinate = None
    problem = None
    started = time.monotonic()
    log_path = growth / "logs" / (datetime.now(UK).strftime("%Y-%m-%d-%H%M%S") + ".log")
    log_path.parent.mkdir(mode=0o700, exist_ok=True)
    previous_handlers = {}
    def interrupted(sig, frame):
        raise RuntimeError("Worker interrupted by signal " + str(sig))
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, interrupted)
    try:
        with log_path.open("w", buffering=1) as log:
            os.chmod(log_path, 0o600)
            caffeinate = subprocess.Popen(["/usr/bin/caffeinate", "-is", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            vm = subprocess.Popen([str(Path.home() / "Applications/InstaAddict/Start Android.command")], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while True:
                if (growth / "paused.json").exists():
                    raise RuntimeError("Paused by operator during boot")
                if datetime.now(UK).date().isoformat() != day:
                    raise RuntimeError("Boot reached the next UK day")
                if vm.poll() is not None:
                    raise RuntimeError("Emulator exited during boot")
                if time.monotonic() - started > 240:
                    raise RuntimeError("Emulator boot timeout")
                if shutil.disk_usage(repo).free < 3 * GIB:
                    raise RuntimeError("Disk reserve reached during boot")
                try:
                    if adb_call("-s", "emulator-5554", "shell", "getprop", "sys.boot_completed").strip() == "1":
                        break
                except (subprocess.SubprocessError, OSError):
                    pass
                time.sleep(3)
            if targets:
                journal["reservedLikeBudget"] = len(targets) * conf["likes-count"]
                write_json(journal_path, journal)
                write_json(state_path, journal)
                bot = subprocess.Popen([str(repo / ".venv/bin/python"), "-u", "run.py", "--config", str(config_path)], cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)
                lines = queue.Queue()
                def drain():
                    for line in bot.stdout:
                        lines.put(line)
                    lines.put(None)
                threading.Thread(target=drain, daemon=True).start()
                bot_started = time.monotonic()
                ended = False
                while not ended:
                    try:
                        line = lines.get(timeout=2)
                        if line is None:
                            ended = True
                        else:
                            log.write(line)
                            print(line, end="", flush=True)
                            followed = re.search(r"\bFollowed @([a-z0-9_.]+)\b", line)
                            if followed:
                                observed = journal.setdefault("observedFollowHandles", [])
                                if followed.group(1) not in observed:
                                    observed.append(followed.group(1))
                                    write_json(journal_path, journal)
                            if STOP.search(line):
                                raise RuntimeError("Bot stop condition: " + line.strip()[-300:])
                    except queue.Empty:
                        pass
                    if (growth / "paused.json").exists():
                        raise RuntimeError("Paused by operator")
                    if vm.poll() is not None:
                        raise RuntimeError("Emulator exited during the bot session")
                    if datetime.now(UK).date().isoformat() != day:
                        raise RuntimeError("Session reached the next UK day")
                    if time.monotonic() - bot_started > 1200 or time.monotonic() - started > 1440:
                        raise RuntimeError("Session time limit")
                    if shutil.disk_usage(repo).free < 3 * GIB:
                        raise RuntimeError("Disk reserve reached")
                    if log.tell() > 10 * 1024 * 1024:
                        raise RuntimeError("Log size limit")
                if bot.wait(timeout=10) != 0:
                    raise RuntimeError("Bot exited unsuccessfully: " + str(bot.returncode))
                relevant = saved_bot_job(account, growth, config_path, day)
                journal["sessionIds"] = [s["id"] for s in relevant]
                write_json(journal_path, journal)
                after = accounting_totals(read_json(account / "sessions.json", []), day, journals + [journal])
                if after["follows"] > 5 or after["likes"] > 10:
                    raise ValueError("Daily action limit exceeded")
            journal["comments"] = run_comment_phase(repo, account, growth, day, env, vm, started, log)
    except BaseException as exc:
        problem = str(exc) or type(exc).__name__
    finally:
        # Do not let a second interrupt skip cleanup.
        for sig in previous_handlers:
            signal.signal(sig, signal.SIG_IGN)
        stop_process(bot)
        if vm is not None:
            try:
                adb_call("-s", "emulator-5554", "emu", "kill")
            except (subprocess.SubprocessError, OSError):
                pass
            try:
                vm.wait(timeout=20)
            except subprocess.TimeoutExpired:
                stop_process(vm)
        stop_process(caffeinate)
        manual_pause = bool(problem and problem.startswith("Paused by operator"))
        journal.update(finishedAt=now(), status="paused" if manual_pause else ("fault" if problem else "completed"), problem=problem, elapsedSeconds=round(time.monotonic() - started), emulatorStopped=vm is not None and vm.poll() is not None, log=str(log_path))
        try:
            new_sessions = [s for s in read_json(account / "sessions.json", []) if s["id"] not in {old["id"] for old in read_json(growth / "sessions-before.json", [])}]
            # A clean process exit alone is insufficient evidence of a completed job.
            relevant = [s for s in new_sessions if config_path and s.get("args", {}).get("config") == str(config_path)]
            journal["sessionIds"] = [s["id"] for s in relevant]
            sessions = read_json(account / "sessions.json", [])
            after = accounting_totals(sessions, day, journals + [journal])
            journal["totalsAfter"] = after
            journal["botRecordedActions"] = {"follows": sum(s["total_followed"] for s in relevant), "likes": sum(s["total_likes"] for s in relevant)}
            if after["follows"] > 5 or after["likes"] > 10:
                raise ValueError("Daily action limit exceeded")
            if config_path and not manual_pause:
                saved_bot_job(account, growth, config_path, day)
            if any(s.get(field, 0) for s in relevant for field in ("total_comments", "total_pm", "total_unfollowed", "total_uploads_success")):
                raise ValueError("Unexpected messaging, unfollow or publishing action")
            public_comments.recover_reservations(growth)
            journal["comments"] = public_comments.plan(growth, day)[0]
            if journal["comments"]["reviewRequired"]:
                raise ValueError("Uncertain comment intent requires review")
        except Exception as exc:
            journal["status"] = "fault"
            journal["problem"] = journal["problem"] or str(exc)
        write_json(journal_path, journal)
        write_json(state_path, journal)
        if journal["status"] == "fault":
            write_json(growth / "fault.json", {"at": now(), "reason": journal["problem"], "day": day, "reviewRequired": True})
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    print(json.dumps(journal, indent=2))
    return 1 if journal["status"] == "fault" else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status", "pause", "resume"))
    parser.add_argument("--account", required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if not HANDLE.fullmatch(args.account):
        parser.error("Invalid account")
    repo = args.repo.resolve()
    account = repo / "accounts" / args.account
    if not account.is_dir():
        parser.error("Account directory does not exist")
    os.chdir(repo)
    os.umask(0o077)
    growth = account / "growth"
    growth.mkdir(mode=0o700, exist_ok=True)
    if args.command == "status":
        journals = [read_json(p) for p in (growth / "days").glob("*.json")]
        pending = select_targets(read_json(growth / "queue.json", {"targets": []}), read_json(account / "interacted_users.json", {}), journals, args.account, 10000)
        print(json.dumps({"paused": (growth / "paused.json").exists(), "fault": read_json(growth / "fault.json"), "latest": read_json(growth / "state.json"), "pendingProfiles": len(pending), "comments": public_comments.plan(growth)[0]}, indent=2))
        return 0
    if args.command == "pause":
        write_json(growth / "paused.json", {"at": now()})
        print("Paused. An active session will stop and shut down its emulator.")
        return 0
    if args.command == "resume":
        (growth / "paused.json").unlink(missing_ok=True)
        print("Manual pause removed. Safety faults still require review; status shows any fault.")
        return 0
    with (growth / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another daily worker holds the lock.")
            return 0
        try:
            write_json(growth / "sessions-before.json", read_json(account / "sessions.json", []))
            return run_session(repo, account, growth)
        except Exception as exc:
            write_json(growth / "fault.json", {"at": now(), "reason": str(exc), "reviewRequired": True})
            print("Stopped for review:", exc)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
