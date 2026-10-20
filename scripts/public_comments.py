#!/usr/bin/env python3
"""Finite prepared public comments for uk.tradeleads; no discovery or retries.

Every UI attempt is durably reserved first. Only a full single-node author/text
receipt can finish it; every other outcome stays charged and requires review.
"""
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
from urllib.parse import urlsplit
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
ACCOUNT = "uk.tradeleads"
APP = "com.instagram.android"
RID = APP + ":id/"
HANDLE = re.compile(r"[a-z0-9_](?:[a-z0-9_.]{0,28}[a-z0-9_])?\Z")
POST = re.compile(r"/(?:(?P<handle>[a-z0-9_.]+)/)?p/(?P<code>[A-Za-z0-9_-]{1,64})/\Z")
STATES = {"reserved", "uncertain", "posted", "alreadyPosted"}
FIELDS = {"id", "handle", "postUrl", "captionSnippet", "text", "sourceUrl", "expiresAt"}
RESTRICTED = re.compile(
    r"action blocked|try again later|we restrict|challenge|captcha|confirm you.re human|"
    r"account has been compromised|suspicious|feedback_required|couldn.t post|"
    r"couldn.t refresh|comments (?:are|have been) (?:limited|disabled|turned off)|"
    r"check your internet|no internet|log in|session expired", re.I)
PROMOTION = re.compile(
    r"https?://|www\.|\b[\w-]+\.(?:[\w-]+\.)*[a-z]{2,}(?:\b|/)|"
    r"\b(?:dm|buy|discount|enquire|inquire)\b|"
    r"\b(?:message|contact|call|follow) (?:me|us)\b|"
    r"\b(?:get in touch|we can help|our services|free quote|book (?:a|now)|"
    r"generate leads|more leads|check (?:out )?our|visit our)\b", re.I)


def now():
    return datetime.now(UK)


def normalize(text):
    return " ".join(text.split())


def aware(value):
    if not isinstance(value, str):
        raise ValueError("Expected an ISO timestamp")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return result


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


def write_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    with temp.open("w") as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_entry(entry):
    if not isinstance(entry, dict) or not FIELDS <= entry.keys():
        raise ValueError("Incomplete comment entry")
    if any(not isinstance(entry[key], str) or not entry[key].strip() for key in FIELDS):
        raise ValueError("Comment fields must be nonempty strings")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", entry["id"]):
        raise ValueError("Invalid comment id")
    handle = entry["handle"]
    if not HANDLE.fullmatch(handle) or ".." in handle or handle == ACCOUNT:
        raise ValueError("Invalid comment target handle")
    url = urlsplit(entry["postUrl"])
    match = POST.fullmatch(url.path)
    if (url.scheme != "https" or url.netloc not in {"www.instagram.com", "instagram.com"}
            or url.query or url.fragment or not match
            or entry["postUrl"] != "https://" + url.netloc + url.path
            or match["handle"] not in (None, handle)):
        raise ValueError("Expected an exact Instagram post URL matching handle")
    if entry["sourceUrl"] not in {f"https://www.instagram.com/{handle}/", f"https://instagram.com/{handle}/"}:
        raise ValueError("Comment requires matching profile proof sourceUrl")
    if any(len(entry[field]) > 220 for field in ("captionSnippet", "text")):
        raise ValueError("Caption snippet and comment must be at most 220 characters")
    if entry["text"] != entry["text"].strip() or PROMOTION.search(entry["text"]):
        raise ValueError("Comment contains a link or sales pitch")
    aware(entry["expiresAt"])
    return match["code"], normalize(entry["text"]).casefold()


def load_ledger(growth, required=False):
    path = growth / "comment-ledger.json"
    if not path.exists() and not required:
        return {"version": 1, "intents": []}
    ledger = read_json(path) if path.exists() else None
    if not isinstance(ledger, dict) or type(ledger.get("version")) is not int or ledger["version"] != 1 or not isinstance(ledger.get("intents"), list):
        raise ValueError("Invalid or missing comment ledger")
    ids = set()
    for intent in ledger["intents"]:
        validate_entry(intent)
        if intent["id"] in ids or intent.get("state") not in STATES:
            raise ValueError("Duplicate intent id or invalid intent state")
        ids.add(intent["id"])
        stamp = aware(intent.get("reservedAt"))
        if intent.get("day") != stamp.astimezone(UK).date().isoformat():
            raise ValueError("Intent day must match its UK reservation timestamp")
        if "finishedAt" in intent:
            if aware(intent["finishedAt"]) < stamp:
                raise ValueError("Intent finish precedes reservation")
        for field in ("evidence", "receiptSessionId"):
            if field in intent and (not isinstance(intent[field], str) or not intent[field]):
                raise ValueError("Invalid receipt metadata")
        if "receiptSessionId" in intent and intent["state"] not in {"posted", "alreadyPosted"}:
            raise ValueError("Only confirmed receipts may refer to bot sessions")
    return ledger


def recover_reservations(growth):
    """Call only while the helper is stopped or under its exclusive lock."""
    ledger = load_ledger(growth)
    changed = False
    for intent in ledger["intents"]:
        if intent["state"] == "reserved":
            intent["state"] = "uncertain"
            changed = True
    if changed:
        write_json(growth / "comment-ledger.json", ledger)
    return changed


def bot_comments(growth, day):
    path = growth.parent / "sessions.json"
    sessions = read_json(path) if path.exists() else []
    if not isinstance(sessions, list):
        raise ValueError("Invalid bot session history")
    counts, seen = {}, set()
    for session in sessions:
        sid = session["id"]
        if not isinstance(sid, str) or sid in seen:
            raise ValueError("Invalid or duplicate bot session id")
        seen.add(sid)
        start = datetime.fromisoformat(session["start_time"])
        finish = datetime.fromisoformat(session["finish_time"])
        start = start.replace(tzinfo=UK) if start.tzinfo is None else start.astimezone(UK)
        finish = finish.replace(tzinfo=UK) if finish.tzinfo is None else finish.astimezone(UK)
        count = session.get("total_comments", 0)
        if type(count) is not int or count < 0 or finish < start:
            raise ValueError("Invalid bot comment history")
        if start.date().isoformat() <= day <= finish.date().isoformat():
            counts[sid] = count
    return counts


def plan(growth, day=None, at=None):
    at = at or now()
    day = day or at.astimezone(UK).date().isoformat()
    policy_path = growth / "comment-policy.json"
    policy = read_json(policy_path) if policy_path.exists() else {"enabled": False, "dailyLimit": 2, "timezone": "Europe/London"}
    if (not isinstance(policy, dict) or type(policy.get("enabled")) is not bool
            or type(policy.get("dailyLimit")) is not int or policy["dailyLimit"] != 2
            or policy.get("timezone") != "Europe/London"):
        raise ValueError("Invalid comment policy")
    ledger = load_ledger(growth, required=policy["enabled"])
    queue_path = growth / "comment-queue.json"
    manifest = read_json(queue_path) if queue_path.exists() else ({"comments": []} if not policy["enabled"] else None)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("comments"), list):
        raise ValueError("Invalid or missing prepared comment queue")
    codes, texts, ids = set(), set(), set()
    for intent in ledger["intents"]:
        code, text = validate_entry(intent)
        codes.add(code)
        texts.add(text)
    pending = []
    for entry in manifest["comments"]:
        code, text = validate_entry(entry)
        if set(entry) != FIELDS or entry["id"] in ids:
            raise ValueError("Invalid queue fields or duplicate comment id")
        ids.add(entry["id"])
        if (aware(entry["expiresAt"]) <= at or code in codes or text in texts
                or any(i["id"] == entry["id"] for i in ledger["intents"])):
            continue
        pending.append(entry)
        codes.add(code)
        texts.add(text)
    charged = [i for i in ledger["intents"] if i["day"] == day]
    counts = bot_comments(growth, day)
    daily_charged = len(charged) + sum(max(0, count - sum(i.get("receiptSessionId") == sid for i in charged)) for sid, count in counts.items())
    status = {"enabled": policy["enabled"], "dailyCharged": daily_charged,
              "remaining": max(0, 2 - daily_charged), "pending": len(pending),
              "reviewRequired": any(i["state"] in {"reserved", "uncertain"} for i in ledger["intents"])}
    return status, pending, ledger


class CommentUI:
    """Importable read-only validation path: open_and_validate never types/posts."""
    def __init__(self, device, growth, account=ACCOUNT, guard=lambda: None):
        if account != ACCOUNT:
            raise ValueError("Prepared public comments are scoped to uk.tradeleads")
        self.d, self.growth, self.account, self.guard = device, Path(growth), account, guard

    def snapshot(self, phase):
        self.guard()
        xml = self.d.dump_hierarchy()
        root = ET.fromstring(xml)
        folder = self.growth / "comments-log"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        path = folder / (uuid.uuid4().hex + "-" + phase + ".xml")
        with path.open("w") as stream:
            os.chmod(path, 0o600)
            stream.write(xml)
            stream.flush()
            os.fsync(stream.fileno())
        visible = " ".join(n.get(k, "") for n in root.iter() for k in ("text", "content-desc"))
        if RESTRICTED.search(visible) or any("challenge" in n.get("resource-id", "").lower() for n in root.iter()):
            raise RuntimeError("Instagram restriction, challenge or error requires review")
        return root, str(path)

    def nodes(self, root, name):
        return [n for n in root.iter("node") if n.get("resource-id") == RID + name]

    def wait_for(self, phase, predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while True:
            root, path = self.snapshot(phase)
            if predicate(root):
                return root, path
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out verifying " + phase)
            time.sleep(0.5)

    def click(self, name, root, description=None):
        nodes = self.nodes(root, name)
        if len(nodes) != 1 or nodes[0].get("enabled", "true") != "true":
            raise RuntimeError("Missing or ambiguous control: " + name)
        if description is not None and nodes[0].get("content-desc") != description:
            raise RuntimeError("Unexpected send control description")
        self.guard()
        selector = {"resourceId": RID + name}
        if description is not None:
            selector["description"] = description
        self.d(**selector).click()

    def receipt(self, root, entry):
        return any(n.get("content-desc") == self.account + " said " + entry["text"] for n in root.iter("node"))

    def open_post(self, entry):
        self.guard()
        self.d.shell(["am", "start", "-a", "android.intent.action.VIEW", "-d", entry["postUrl"], "-p", APP])
        root, path = self.wait_for("post", lambda r: bool(self.nodes(r, "row_feed_photo_profile_name")))
        owners = self.nodes(root, "row_feed_photo_profile_name")
        if len(owners) != 1 or owners[0].get("text") != entry["handle"]:
            raise RuntimeError("Post owner does not match the prepared handle")
        caption = normalize(entry["captionSnippet"])
        if not any(caption in normalize(n.get(k, "")) for n in root.iter("node") for k in ("text", "content-desc")):
            raise RuntimeError("Post caption does not match the prepared excerpt")
        self.click("row_feed_button_comment", root)
        return self.wait_for("composer", lambda r: bool(self.nodes(r, "layout_comment_thread_edittext_multiline")))

    def open_and_validate(self, entry):
        validate_entry(entry)
        self.guard()
        self.d.shell(["monkey", "-p", APP, "-c", "android.intent.category.LAUNCHER", "1"])
        root, _ = self.snapshot("launch")
        for _ in range(3):
            if not self.nodes(root, "layout_comment_thread_edittext_multiline"):
                break
            self.guard()
            self.d.press("back")
            root, _ = self.snapshot("dismiss-comments")
        if self.nodes(root, "layout_comment_thread_edittext_multiline"):
            raise RuntimeError("Comment sheet did not close after bounded Back presses")
        if not self.nodes(root, "profile_tab") and self.nodes(root, "row_feed_photo_profile_name"):
            self.guard()
            self.d.press("back")
        root, _ = self.wait_for("profile-tab", lambda r: bool(self.nodes(r, "profile_tab")))
        self.click("profile_tab", root)
        root, _ = self.wait_for("account", lambda r: bool(self.nodes(r, "action_bar_title")))
        titles = self.nodes(root, "action_bar_title")
        if len(titles) != 1 or titles[0].get("text") != self.account:
            raise RuntimeError("Logged-in account does not match uk.tradeleads")
        root, path = self.open_post(entry)
        composers = self.nodes(root, "layout_comment_thread_edittext_multiline")
        if len(composers) != 1:
            raise RuntimeError("Ambiguous comment composer")
        hints = {"", "Join the conversation…", "Join the conversation...", "What do you think of this?", "Add a comment for " + entry["handle"]}
        visible = [n.get(k, "") for n in root.iter("node") for k in ("text", "content-desc")]
        if any(re.search(r"\breply(?:ing)? (?:to|as)\b", text, re.I) for text in visible):
            raise RuntimeError("Reply context is not permitted")
        composer = self.d(resourceId=RID + "layout_comment_thread_edittext_multiline")
        if composers[0].get("text", "") not in hints or composer.get_text() not in hints:
            raise RuntimeError("Existing draft or unknown composer hint")
        return root, path

    def submit(self, entry):
        root, path = self.open_and_validate(entry)
        if self.receipt(root, entry):
            return "alreadyPosted", path
        composer = self.d(resourceId=RID + "layout_comment_thread_edittext_multiline")
        self.guard()
        composer.set_text(entry["text"])
        if composer.get_text() != entry["text"]:
            raise RuntimeError("Composer text differs from the prepared comment")
        root, _ = self.snapshot("prepared")
        nodes = self.nodes(root, "layout_comment_thread_edittext_multiline")
        if len(nodes) != 1 or nodes[0].get("text") != entry["text"]:
            raise RuntimeError("Prepared composer is not present")
        self.click("layout_comment_thread_post_button_icon", root, "Post")
        root, _ = self.wait_for("receipt", lambda r: self.receipt(r, entry))
        if self.nodes(root, "layout_comment_thread_edittext_multiline"):
            self.guard()
            self.d.press("back")
        root, path = self.open_post(entry)
        if not self.receipt(root, entry):
            _, path = self.wait_for("fresh-receipt", lambda r: self.receipt(r, entry))
        return "posted", path


def connect_device():
    os.environ["ADB_USB"] = "0"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from InstaAddict.core import device_facade  # patches Android 14 BEFORE connect
    import uiautomator2
    return uiautomator2.connect("emulator-5554")


def run_comments(growth, account, day, device_factory=connect_device):
    if account != ACCOUNT:
        raise ValueError("Prepared comments support only uk.tradeleads")
    with (growth / "comment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recover_reservations(growth)
        status, pending, ledger = plan(growth, day)
        if status["reviewRequired"]:
            raise RuntimeError("Uncertain comment intent requires review; never retry")
        if not status["enabled"] or not pending or not status["remaining"]:
            return status
        started = time.monotonic()

        def guard():
            if (growth / "paused.json").exists():
                raise RuntimeError("Paused by operator")
            if (growth / "fault.json").exists():
                raise RuntimeError("Safety fault requires review")
            if now().date().isoformat() != day:
                raise RuntimeError("Comment phase reached the next UK day")
            if time.monotonic() - started >= 180:
                raise RuntimeError("Comment phase time limit")

        guard()
        ui = CommentUI(device_factory(), growth, account, guard)
        for entry in pending[:status["remaining"]]:
            guard()
            current, eligible, _ = plan(growth, day)
            if not current["enabled"] or not current["remaining"]:
                break
            if entry not in eligible:
                continue
            intent = dict(entry, day=day, reservedAt=now().isoformat(), state="reserved")
            ledger["intents"].append(intent)
            try:
                write_json(growth / "comment-ledger.json", ledger)
                state, evidence = ui.submit(entry)
                intent.update(state=state, finishedAt=now().isoformat(), evidence=evidence)
                write_json(growth / "comment-ledger.json", ledger)
            except BaseException:
                intent["state"] = "uncertain"
                write_json(growth / "comment-ledger.json", ledger)
                raise
        return plan(growth, day)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True, choices=[ACCOUNT])
    parser.add_argument("--day", required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    growth = args.repo.resolve() / "accounts" / args.account / "growth"
    os.umask(0o077)

    def interrupted(sig, frame):
        raise RuntimeError("Comment helper interrupted by signal " + str(sig))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        print(json.dumps(run_comments(growth, args.account, args.day)))
        return 0
    except BaseException as exc:
        write_json(growth / "fault.json", {"at": now().isoformat(), "reason": str(exc), "reviewRequired": True})
        print("Comments stopped for review:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
