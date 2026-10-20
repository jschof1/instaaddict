"""Critical daily-budget and replay protection, without a device or dependencies."""
from datetime import datetime
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import io

spec = importlib.util.spec_from_file_location("daily_growth", Path(__file__).resolve().parents[1] / "scripts/daily_growth.py")
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


class DailyGrowthTests(unittest.TestCase):
    def session(self, sid="manual", start="2026-10-19 14:51:00", finish="2026-10-19 14:57:53", follows=2, likes=1):
        return dict(id=sid, start_time=start, finish_time=finish, total_followed=follows, total_likes=likes)

    def test_manual_and_midnight_sessions_share_day_budget(self):
        sessions = [self.session(), self.session("overnight", "2026-10-18 23:59:00", "2026-10-19 00:02:00", 1, 2), self.session("old", "2026-10-18 10:00:00", "2026-10-18 11:00:00", 5, 10)]
        self.assertEqual(daily.daily_totals(sessions, "2026-10-19"), {"follows": 3, "likes": 3})

    def test_aware_times_convert_to_uk_calendar_day(self):
        self.assertEqual(daily.daily_totals([self.session(start="2026-10-18T23:30:00+00:00", finish="2026-10-18T23:35:00+00:00")], "2026-10-19")["follows"], 2)

    def test_interrupted_follow_log_is_charged_without_double_counting(self):
        journal = {"day": "2026-10-19", "sessionIds": ["manual"], "observedFollowHandles": ["prospect"]}
        self.assertEqual(daily.accounting_totals([self.session(follows=0)], "2026-10-19", [journal])["follows"], 1)
        self.assertEqual(daily.accounting_totals([self.session(follows=1)], "2026-10-19", [journal])["follows"], 1)
        with self.assertRaises(ValueError):
            daily.accounting_totals([self.session()], "2026-10-19", [journal, journal])

    def test_uncertain_sessions_stop_instead_of_freeing_budget(self):
        for sessions in ([self.session(finish="None")], [self.session(), self.session()], [self.session(likes=-1)]):
            with self.subTest(sessions=sessions), self.assertRaises(ValueError):
                daily.daily_totals(sessions, "2026-10-19")

    def test_interrupted_batch_keeps_reserved_likes_charged(self):
        journal = {"day": "2026-10-19", "config": "batch.yml", "sessionIds": [],
                   "reservedLikeBudget": 10, "observedFollowHandles": ["one", "two", "three"]}
        self.assertEqual(daily.accounting_totals([], "2026-10-19", [journal]), {"follows": 3, "likes": 10})
        for saved in (0, 4, 10, 11):
            session = dict(self.session("batch", follows=3, likes=saved), args={"config": "batch.yml"})
            journal["sessionIds"] = ["batch"]
            sessions = [session, self.session(likes=1)]
            expected = {"follows": 5, "likes": max(10, saved) + 1}
            self.assertEqual(daily.accounting_totals(sessions, "2026-10-19", [journal]), expected)
            self.assertEqual(daily.accounting_totals(sessions, "2026-10-19", [journal]), expected)

    def test_duplicate_empty_session_journals_require_review(self):
        journal = {"day": "2026-10-19", "config": "batch.yml", "reservedLikeBudget": 10}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            daily.accounting_totals([], "2026-10-19", [journal, journal])

    def test_duplicate_ids_within_one_journal_cannot_release_reservation(self):
        journal = {"day": "2026-10-19", "config": "batch.yml", "reservedLikeBudget": 10,
                   "sessionIds": ["batch", "batch"]}
        saved = dict(self.session("batch", likes=5), args={"config": "batch.yml"})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            daily.accounting_totals([saved], "2026-10-19", [journal])

    def test_linked_session_outside_journal_day_requires_review(self):
        journal = {"day": "2026-10-19", "config": "batch.yml", "reservedLikeBudget": 10,
                   "sessionIds": ["batch"]}
        for likes in (4, -1):
            saved = dict(self.session("batch", start="2026-10-18 12:00:00", finish="2026-10-18 12:30:00", likes=likes),
                         args={"config": "batch.yml"})
            with self.subTest(likes=likes), self.assertRaisesRegex(ValueError, "journal day"):
                daily.accounting_totals([saved], "2026-10-19", [journal])

    def test_missing_or_invalid_like_reservation_requires_review(self):
        for reservation in (None, -1, True, "10"):
            journal = {"day": "2026-10-19", "config": "batch.yml"}
            if reservation is not None:
                journal["reservedLikeBudget"] = reservation
            with self.subTest(reservation=reservation), self.assertRaises(ValueError):
                daily.accounting_totals([], "2026-10-19", [journal])

    def test_unrelated_saved_session_cannot_release_like_reservation(self):
        journal = {"day": "2026-10-19", "config": "batch.yml", "reservedLikeBudget": 10,
                   "sessionIds": ["manual"]}
        with self.assertRaisesRegex(ValueError, "matching"):
            daily.accounting_totals([self.session(likes=4)], "2026-10-19", [journal])

    def target(self, handle):
        return dict(handle=handle, sourceUrl="https://business.example/", instagramUrl="https://www.instagram.com/" + handle + "/", trade="Roofing", serviceArea="Kent", evidence="Business links this account")

    def test_faulted_and_interacted_targets_are_not_replayed(self):
        manifest = {"targets": [self.target(h) for h in ["old", "partial", "fresh", "fresh", "next"]]}
        self.assertEqual(daily.select_targets(manifest, {"old": {}}, [{"status": "fault", "targets": ["partial"]}], "owner", 2), ["fresh", "next"])

    def test_invalid_or_unsupported_target_fails_closed(self):
        for handle in ["owner", "NotLowercase", "unsafe/path"]:
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                daily.select_targets({"targets": [self.target(handle)]}, {}, [], "owner", 5)
        entry = self.target("real")
        entry["instagramUrl"] = "https://www.instagram.com/someone_else/"
        with self.assertRaises(ValueError):
            daily.select_targets({"targets": [entry]}, {}, [], "owner", 5)

    def test_odd_remaining_like_budget_cannot_overshoot(self):
        for follows in range(1, 6):
            for likes in range(1, 11):
                handles = ["target" + str(i) for i in range(min(follows, likes))]
                c = daily.bot_config("owner", handles, follows, likes)
                self.assertLessEqual(len(handles), follows)
                self.assertLessEqual(len(handles) * c["likes-count"], likes)
                self.assertEqual(c["total-sessions"], 1)
                self.assertFalse(c["disable-block-detection"])
                self.assertTrue(c["count-app-crashes"])
                self.assertEqual(c["total-crashes-limit"], 1)
                for key in ("pm-percentage", "comment-percentage", "total-pm-limit", "total-comments-limit", "total-unfollows-limit"):
                    self.assertEqual(c[key], 0)
                self.assertNotIn("repeat", c)

    def test_restriction_and_hang_lines_stop_run(self):
        for line in ["A serius block detected", "Watchdog Tier 1 recovery", "Watchdog Tier 2 recovery", "Traceback (most recent call last)", "challenge_required", "App has crashed / has been closed!", "Can't go back to the profile; ending interaction.", "Could not return from Peek Preview; ending interaction.", "Profile grid unavailable after failed post open; ending interaction."]:
            self.assertIsNotNone(daily.STOP.search(line))
        self.assertIsNone(daily.STOP.search("Block detection is enabled"))

    def test_atomic_private_journal_survives_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "days/day.json"
            daily.write_json(path, {"status": "running"})
            daily.write_json(path, {"status": "completed"})
            self.assertEqual(daily.read_json(path)["status"], "completed")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def lifecycle_fixture(self, directory):
        repo = Path(directory)
        account = repo / "accounts/owner"
        growth = account / "growth"
        growth.mkdir(parents=True)
        daily.write_json(account / "sessions.json", [])
        daily.write_json(growth / "sessions-before.json", [])
        daily.write_json(growth / "settings.json", {"dailyFollows": 5, "dailyLikes": 10, "timezone": "Europe/London"})
        daily.write_json(growth / "queue.json", {"targets": [self.target("prospect")]})
        (account / "filters.yml").write_text("fixture")
        return repo, account, growth

    def test_occupied_emulator_is_not_stopped_or_consumed(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            repo, account, growth = self.lifecycle_fixture(directory)
            stack.enter_context(patch.dict("sys.modules", {"yaml": SimpleNamespace()}))
            stack.enter_context(patch.object(daily.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * daily.GIB)))
            adb = stack.enter_context(patch.object(daily.subprocess, "run", side_effect=[SimpleNamespace(stdout=""), SimpleNamespace(stdout="emulator-5554\tdevice\n")]))
            spawn = stack.enter_context(patch.object(daily.subprocess, "Popen"))
            self.assertEqual(daily.run_session(repo, account, growth), 0)
            spawn.assert_not_called()
            self.assertEqual(adb.call_count, 2)
            self.assertEqual(list((growth / "days").glob("*.json")), [])
            self.assertFalse((growth / "fault.json").exists())

    def test_owned_emulator_boot_failure_cleans_up_and_blocks_future_runs(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            repo, account, growth = self.lifecycle_fixture(directory)
            filters = {"skip_if_private": True, "skip_following": True, "skip_follower": True, "follow_private_or_empty": False}
            stack.enter_context(patch.dict("sys.modules", {"yaml": SimpleNamespace(safe_load=lambda _: filters)}))
            stack.enter_context(patch.object(daily.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * daily.GIB)))
            adb = stack.enter_context(patch.object(daily.subprocess, "run", return_value=SimpleNamespace(stdout="")))
            stack.enter_context(patch.object(daily.subprocess, "check_output", return_value=""))
            stack.enter_context(patch.object(daily, "preflight"))
            caffeinate, emulator = MagicMock(), MagicMock()
            emulator.poll.return_value = 1
            spawn = stack.enter_context(patch.object(daily.subprocess, "Popen", side_effect=[caffeinate, emulator]))
            stop = stack.enter_context(patch.object(daily, "stop_process"))
            self.assertEqual(daily.run_session(repo, account, growth), 1)
            self.assertTrue(any(call.args[0][-2:] == ["emu", "kill"] for call in adb.call_args_list))
            stop.assert_any_call(caffeinate)
            self.assertEqual(daily.read_json(growth / "state.json")["status"], "fault")
            self.assertEqual(daily.read_json(growth / "state.json")["reservedLikeBudget"], 0)
            self.assertTrue((growth / "fault.json").exists())
            self.assertEqual(daily.run_session(repo, account, growth), 0)
            self.assertEqual(spawn.call_count, 2)  # no bot or retry after failed boot

    def test_manual_pause_during_boot_stops_owned_vm_without_safety_fault(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            repo, account, growth = self.lifecycle_fixture(directory)
            filters = {"skip_if_private": True, "skip_following": True, "skip_follower": True, "follow_private_or_empty": False}
            stack.enter_context(patch.dict("sys.modules", {"yaml": SimpleNamespace(safe_load=lambda _: filters)}))
            stack.enter_context(patch.object(daily.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * daily.GIB)))
            adb = stack.enter_context(patch.object(daily.subprocess, "run", return_value=SimpleNamespace(stdout="")))
            stack.enter_context(patch.object(daily.subprocess, "check_output", return_value=""))
            stack.enter_context(patch.object(daily, "preflight"))
            caffeinate, emulator = MagicMock(), MagicMock()
            emulator.poll.return_value = 0

            def spawn(command, **kwargs):
                if command[0] == "/usr/bin/caffeinate":
                    return caffeinate
                daily.write_json(growth / "paused.json", {"at": daily.now()})
                return emulator

            stack.enter_context(patch.object(daily.subprocess, "Popen", side_effect=spawn))
            stop = stack.enter_context(patch.object(daily, "stop_process"))
            self.assertEqual(daily.run_session(repo, account, growth), 0)
            state = daily.read_json(growth / "state.json")
            self.assertEqual(state["status"], "paused")
            self.assertTrue(state["emulatorStopped"])
            self.assertFalse((growth / "fault.json").exists())
            self.assertTrue(any(call.args[0][-2:] == ["emu", "kill"] for call in adb.call_args_list))
            stop.assert_any_call(caffeinate)

    def comment_setup(self, repo, account, growth):
        from test_public_comments import entry
        prepared = entry()
        daily.write_json(growth / "comment-policy.json", {"enabled": True, "dailyLimit": 2, "timezone": "Europe/London"})
        daily.write_json(growth / "comment-queue.json", {"comments": [prepared]})
        daily.write_json(growth / "comment-ledger.json", {"version": 1, "intents": []})
        return prepared

    def completed_job(self, config_path, day=None):
        day = day or datetime.now(daily.UK).date().isoformat()
        return dict(self.session("new-job", day + "T10:00:00+01:00", day + "T10:01:00+01:00"),
                    args={"config": str(config_path)}, job_metrics={"blogger": {"status": "completed"}},
                    total_crashes=0, total_watchdog_recoveries=0)

    def test_saved_job_requires_new_matching_completed_record_without_recoveries(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, account, growth = self.lifecycle_fixture(directory)
            config = growth / "job.yml"
            good = self.completed_job(config, "2026-10-19")
            daily.write_json(account / "sessions.json", [good])
            self.assertEqual(daily.saved_bot_job(account, growth, config, "2026-10-19"), [good])
            for changes in ({"total_crashes": 1}, {"total_watchdog_recoveries": 1}, {"total_comments": 1},
                            {"total_pm": 1}, {"finish_time": "None"}, {"args": {"config": "other.yml"}},
                            {"job_metrics": {"blogger": {"status": "running"}}}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    daily.write_json(account / "sessions.json", [dict(good, **changes)])
                    daily.saved_bot_job(account, growth, config, "2026-10-19")
            daily.write_json(account / "sessions.json", [good])
            daily.write_json(growth / "sessions-before.json", [good])
            with self.assertRaisesRegex(ValueError, "new matching"):
                daily.saved_bot_job(account, growth, config, "2026-10-19")

    def exercise_comment_worker(self, directory, *, comment_only=False, job_completed=True, reservation_fails=False):
        repo, original, growth = self.lifecycle_fixture(directory)
        account = original.with_name("uk.tradeleads")
        original.rename(account)
        growth = account / "growth"
        self.comment_setup(repo, account, growth)
        if comment_only:
            daily.write_json(growth / "queue.json", {"targets": []})
        filters = {"skip_if_private": True, "skip_following": True, "skip_follower": True, "follow_private_or_empty": False}
        with ExitStack() as stack:
            if reservation_fails:
                original_write = daily.write_json

                def write(path, value):
                    nonlocal reservation_fails
                    if path.parent.name == "days" and value.get("reservedLikeBudget", 0) > 0 and reservation_fails:
                        reservation_fails = False
                        raise OSError("reservation disk failure")
                    original_write(path, value)

                stack.enter_context(patch.object(daily, "write_json", side_effect=write))
            stack.enter_context(patch.dict("sys.modules", {"yaml": SimpleNamespace(safe_load=lambda _: filters)}))
            stack.enter_context(patch.object(daily.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * daily.GIB)))
            stack.enter_context(patch.object(daily.subprocess, "check_output", return_value=""))
            stack.enter_context(patch.object(daily, "preflight"))
            stack.enter_context(patch.object(daily, "stop_process"))
            caffeinate, emulator, bot, helper = MagicMock(), MagicMock(), MagicMock(), MagicMock()
            emulator.poll.return_value = None
            helper.poll.return_value, helper.returncode = 0, 0
            bot.stdout, bot.wait.return_value, bot.returncode = iter([]), 0, 0

            def adb_call(command, **kwargs):
                if command[-2:] == ["emu", "kill"]:
                    emulator.poll.return_value = 0
                return SimpleNamespace(stdout="1" if command[-1] == "sys.boot_completed" else "")

            stack.enter_context(patch.object(daily.subprocess, "run", side_effect=adb_call))
            commands = []

            def spawn(command, **kwargs):
                commands.append(command)
                if command[0] == "/usr/bin/caffeinate":
                    return caffeinate
                if command[0].endswith("Start Android.command"):
                    return emulator
                if "run.py" in command:
                    config = command[command.index("--config") + 1]
                    journal = daily.read_json(next((growth / "days").glob("*.json")))
                    self.assertEqual(journal["reservedLikeBudget"], 2)
                    record = self.completed_job(config)
                    if not job_completed:
                        record["job_metrics"]["blogger"]["status"] = "running"
                    daily.write_json(account / "sessions.json", [record])
                    return bot
                self.assertTrue(command[0].endswith(".venv/bin/python"))
                self.assertTrue(command[2].endswith("scripts/public_comments.py"))
                self.assertIsNone(emulator.poll())  # same owned VM, before cleanup
                self.assertEqual(kwargs["env"]["ADB_USB"], "0")
                journal = daily.read_json(next((growth / "days").glob("*.json")))
                self.assertEqual(journal.get("sessionIds", []), [] if comment_only else ["new-job"])
                return helper

            stack.enter_context(patch.object(daily.subprocess, "Popen", side_effect=spawn))
            result = daily.run_session(repo, account, growth)
            state = daily.read_json(growth / "state.json")
            count_before = len(commands)
            self.assertEqual(daily.run_session(repo, account, growth), 0)
            self.assertEqual(len(commands), count_before)  # today's journal prevents replay
            return result, state, commands

    def test_comment_only_run_uses_same_owned_vm_and_never_launches_bot(self):
        with tempfile.TemporaryDirectory() as directory:
            result, state, commands = self.exercise_comment_worker(directory, comment_only=True)
            self.assertEqual((result, state["status"], state["config"]), (0, "completed", None))
            self.assertEqual(state["reservedLikeBudget"], 0)
            self.assertEqual(len(commands), 3)
            self.assertFalse(any("run.py" in command for command in commands))

    def test_failed_reservation_write_prevents_bot_and_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            result, state, commands = self.exercise_comment_worker(directory, reservation_fails=True)
            self.assertEqual((result, state["status"]), (1, "fault"))
            self.assertEqual(state["problem"], "reservation disk failure")
            self.assertEqual(len(commands), 2)
            self.assertFalse(any("run.py" in command for command in commands))

    def test_existing_follow_or_like_overshoot_prevents_comment_only_vm(self):
        for follows, likes in [(6, 10), (5, 11)]:
            with self.subTest(follows=follows, likes=likes), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                repo, original, growth = self.lifecycle_fixture(directory)
                account = original.with_name("uk.tradeleads")
                original.rename(account)
                growth = account / "growth"
                self.comment_setup(repo, account, growth)
                daily.write_json(growth / "queue.json", {"targets": []})
                day = datetime.now(daily.UK).date().isoformat()
                daily.write_json(account / "sessions.json", [self.session(start=day + " 10:00:00", finish=day + " 10:01:00", follows=follows, likes=likes)])
                stack.enter_context(patch.dict("sys.modules", {"yaml": SimpleNamespace()}))
                spawn = stack.enter_context(patch.object(daily.subprocess, "Popen"))
                with self.assertRaisesRegex(ValueError, "already exceeded"):
                    daily.run_session(repo, account, growth)
                spawn.assert_not_called()

    def test_comment_phase_follows_saved_job_validation_before_vm_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            result, state, commands = self.exercise_comment_worker(directory)
            self.assertEqual((result, state["status"], state["sessionIds"]), (0, "completed", ["new-job"]))
            self.assertEqual(len(commands), 4)
        with tempfile.TemporaryDirectory() as directory:
            result, state, commands = self.exercise_comment_worker(directory, job_completed=False)
            self.assertEqual((result, state["status"]), (1, "fault"))
            self.assertEqual(len(commands), 3)  # invalid saved job cannot start helper

    def test_comment_phase_pause_rollover_disk_and_shared_deadline_prevent_launch(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            repo, account, growth = self.lifecycle_fixture(directory)
            account = account.with_name("uk.tradeleads")
            self.comment_setup(repo, account, growth)
            vm = MagicMock()
            vm.poll.return_value = None
            spawn = stack.enter_context(patch.object(daily.subprocess, "Popen"))
            stack.enter_context(patch.object(daily.time, "monotonic", return_value=1500))
            disk = stack.enter_context(patch.object(daily.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * daily.GIB)))
            day = datetime.now(daily.UK).date().isoformat()
            with self.assertRaisesRegex(RuntimeError, "time limit"):
                daily.run_comment_phase(repo, account, growth, day, {}, vm, 0, io.StringIO())
            (growth / "paused.json").touch()
            with self.assertRaisesRegex(RuntimeError, "Paused"):
                daily.run_comment_phase(repo, account, growth, day, {}, vm, 1500, io.StringIO())
            (growth / "paused.json").unlink()
            with self.assertRaisesRegex(RuntimeError, "next UK day"):
                daily.run_comment_phase(repo, account, growth, "2026-10-18", {}, vm, 1500, io.StringIO())
            disk.return_value.free = 2 * daily.GIB
            with self.assertRaisesRegex(RuntimeError, "Disk"):
                daily.run_comment_phase(repo, account, growth, day, {}, vm, 1500, io.StringIO())
            spawn.assert_not_called()

    def test_interrupted_helper_is_stopped_and_reservation_becomes_uncertain(self):
        from test_public_comments import intent
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            repo, original, growth = self.lifecycle_fixture(directory)
            account = original.with_name("uk.tradeleads")
            self.comment_setup(repo, account, growth)
            helper, vm = MagicMock(), MagicMock()
            helper.poll.return_value = vm.poll.return_value = None
            stack.enter_context(patch.object(daily.time, "monotonic", return_value=0))
            stack.enter_context(patch.object(daily.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * daily.GIB)))
            stack.enter_context(patch.object(daily.time, "sleep", side_effect=lambda _: (growth / "paused.json").touch()))
            stop = stack.enter_context(patch.object(daily, "stop_process"))
            day = datetime.now(daily.UK).date().isoformat()

            def reserve(*args, **kwargs):
                daily.write_json(growth / "comment-ledger.json", {"version": 1, "intents": [intent(state="reserved", day=day)]})
                return helper

            stack.enter_context(patch.object(daily.subprocess, "Popen", side_effect=reserve))
            with self.assertRaisesRegex(RuntimeError, "Paused"):
                daily.run_comment_phase(repo, account, growth, day, {}, vm, 0, io.StringIO())
            stop.assert_called_once_with(helper)
            self.assertEqual(daily.public_comments.load_ledger(growth)["intents"][0]["state"], "uncertain")

    def test_comment_helper_is_stopped_at_180_seconds(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            repo, original, growth = self.lifecycle_fixture(directory)
            account = original.with_name("uk.tradeleads")
            self.comment_setup(repo, account, growth)
            helper, vm = MagicMock(), MagicMock()
            helper.poll.return_value = vm.poll.return_value = None
            stack.enter_context(patch.object(daily.time, "monotonic", side_effect=[0, 0, 0, 180]))
            stack.enter_context(patch.object(daily.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * daily.GIB)))
            stack.enter_context(patch.object(daily.subprocess, "Popen", return_value=helper))
            stop = stack.enter_context(patch.object(daily, "stop_process"))
            with self.assertRaisesRegex(RuntimeError, "time limit"):
                daily.run_comment_phase(repo, account, growth, datetime.now(daily.UK).date().isoformat(), {}, vm, 0, io.StringIO())
            stop.assert_called_once_with(helper)


if __name__ == "__main__":
    unittest.main()
