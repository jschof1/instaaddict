#!/usr/bin/env python3
"""Explicit offline review of one provable pre-typing failure; never send or retry.

The original day remains charged and the post/text remain permanently consumed.
This command never archives the separate safety fault or changes day journals.
"""
import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

import public_comments as comments

FAILURE = "Existing draft or unknown composer hint"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_file(path, folder, expected):
    path = path.resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError("Evidence must be an existing file in its account evidence folder")
    data = path.read_bytes()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha(data) != expected:
        raise ValueError("Evidence hash mismatch")
    return path, data


def check_source(source, composer_hint="Start the conversation…"):
    """Re-derive the failure-before-typing control flow from the deployed source."""
    tree = ast.parse(source)
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CommentUI"), None)
    if cls is None:
        raise ValueError("Missing original comment UI source")
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    if not {"submit", "open_and_validate"} <= methods.keys():
        raise ValueError("Missing original validation/submission source")
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)
              and isinstance(n.exc, ast.Call) and isinstance(n.exc.func, ast.Name)
              and n.exc.func.id == "RuntimeError" and n.exc.args
              and isinstance(n.exc.args[0], ast.Constant) and n.exc.args[0].value == FAILURE]
    if len(raises) != 1 or raises[0] not in list(ast.walk(methods["open_and_validate"])):
        raise ValueError("Failure does not uniquely originate in read-only validation")
    validation = methods["open_and_validate"]
    for name, method in methods.items():
        if name != "submit" and any(
                (isinstance(n, ast.Attribute) and n.attr == "set_text")
                or (isinstance(n, ast.Constant) and n.value == "layout_comment_thread_post_button_icon")
                for n in ast.walk(method)):
            raise ValueError("Typing or send control exists outside submission")
    first = methods["submit"].body[0]
    if not (isinstance(first, ast.Assign) and isinstance(first.value, ast.Call)
            and isinstance(first.value.func, ast.Attribute)
            and first.value.func.attr == "open_and_validate"):
        raise ValueError("Submission must validate before any typing or send")
    hints = [n.value for n in ast.walk(validation) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "hints" for t in n.targets)]
    if len(hints) != 1 or not isinstance(hints[0], ast.Set):
        raise ValueError("Cannot derive the original composer hints")
    accepted = {n.value for n in hints[0].elts if isinstance(n, ast.Constant)}
    if composer_hint in accepted:
        raise ValueError("Source already accepts this prompt; failure provenance does not match")


def atomic_bytes(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("wb") as stream:
        os.chmod(temp, 0o600)
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def review_not_sent(growth, intent_id, xml, log, xml_sha, log_sha, source_ref,
                    reviewer, reason, source_reader=None, dry_run=False):
    if not reviewer.strip() or len(reason.strip()) < 10:
        raise ValueError("A named reviewer and concrete reason are required")
    if not re.fullmatch(r"[0-9a-f]{40}", source_ref):
        raise ValueError("An exact deployed source commit is required")
    with (growth / "worker.lock").open("a") as worker, (growth / "comment.lock").open("a") as lock:
        fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Review is offline; a manual pause stays untouched and can remain in place.
        ledger = comments.load_ledger(growth, required=True)
        matching = [i for i in ledger["intents"] if i["id"] == intent_id]
        if len(matching) != 1 or matching[0]["state"] != "uncertain":
            raise ValueError("Only one existing uncertain intent may be reviewed")
        intent = matching[0]
        if any(k in intent for k in ("evidence", "receiptSessionId", "commentUrl")):
            raise ValueError("A receipt-bearing intent cannot be declared not sent")
        fault = comments.read_json(growth / "fault.json")
        start, end = comments.aware(intent["reservedAt"]), comments.aware(fault["at"])
        if (fault.get("reason") != "Comment helper exited unsuccessfully"
                or fault.get("day") != intent["day"] or not 0 <= (end-start).total_seconds() <= 180):
            raise ValueError("Fault is not the matching bounded comment-helper failure")
        xml, xml_data = checked_file(xml, growth / "comments-log", xml_sha)
        log, log_data = checked_file(log, growth / "logs", log_sha)
        stops = [(n, line) for n, line in enumerate(log_data.decode().splitlines(), 1)
                 if line.startswith("Comments stopped for review:")]
        if (len(stops) != 1 or stops[0][1] != "Comments stopped for review: " + FAILURE
                or not log.name.startswith(intent["day"])
                or not start.timestamp() <= log.stat().st_mtime <= end.timestamp()+30):
            raise ValueError("Log must contain the one exact pre-typing failure for this day")
        snapshots = []
        for p in (growth / "comments-log").glob("*.xml"):
            if start.timestamp() <= p.stat().st_mtime <= end.timestamp():
                snapshots.append(p)
                if any(p.name.endswith("-" + phase + ".xml") for phase in ("prepared", "receipt", "fresh-receipt")):
                    raise ValueError("Possible typing or submission evidence exists; keep uncertain")
                for n in ET.fromstring(p.read_bytes()).iter("node"):
                    if (n.get("resource-id") == comments.RID + "layout_comment_thread_edittext_multiline"
                            and n.get("text") != "Start the conversation…"):
                        raise ValueError("Another snapshot contains a possible draft")
        if not (start.timestamp() <= xml.stat().st_mtime <= end.timestamp()) or not xml.name.endswith("-composer.xml"):
            raise ValueError("Composer snapshot is outside this attempt window")
        if not snapshots or xml.stat().st_mtime != max(p.stat().st_mtime for p in snapshots):
            raise ValueError("Evidence must be the final snapshot of this attempt")
        root = ET.fromstring(xml_data)
        nodes = list(root.iter("node"))
        composers = [n for n in nodes if n.get("resource-id") == comments.RID + "layout_comment_thread_edittext_multiline"]
        owners = [n for n in nodes if n.get("resource-id") == comments.RID + "row_feed_photo_profile_name"]
        if (len(composers) != 1 or composers[0].get("text") != "Start the conversation…"
                or composers[0].get("focused") != "false"
                or len(owners) != 1 or owners[0].get("text") != intent["handle"]):
            raise ValueError("Expected exact empty unfocused composer and matching post owner")
        visible = [n.get(k, "") for n in nodes for k in ("text", "content-desc")]
        if (not any(comments.normalize(intent["captionSnippet"]) in comments.normalize(t) for t in visible)
                or any(t.startswith(comments.ACCOUNT + " said ") for t in visible)
                or any(comments.RESTRICTED.search(t) for t in visible)
                or any("challenge" in n.get("resource-id", "").lower() for n in nodes)):
            raise ValueError("Caption, existing own comment or restriction requires continued hold")
        if source_reader is None:
            repo = growth.parents[2]
            subprocess.run(["git", "merge-base", "--is-ancestor", source_ref, "HEAD"], cwd=repo, check=True)
            actual = subprocess.check_output(["git", "log", "-1", "--format=%H",
                "--before="+intent["reservedAt"], "HEAD", "--", "scripts/public_comments.py"], cwd=repo).decode().strip()
            if actual != source_ref:
                raise ValueError("Source must be the last helper change before this reservation")
        source_reader = source_reader or (lambda ref: subprocess.check_output(
            ["git", "show", ref + ":scripts/public_comments.py"], cwd=growth.parents[2]).decode())
        source = source_reader(source_ref)
        check_source(source)
        prior_hash = sha(json.dumps(intent, sort_keys=True, separators=(",", ":")).encode())
        stamp = comments.now().isoformat()
        if comments.aware(stamp) < end:
            raise ValueError("Review cannot precede the recorded failure")
        intent.update(state="reviewedNotSent", finishedAt=stamp, notSentReview={
            "reviewer": reviewer.strip(), "reason": reason.strip(), "reviewedAt": stamp,
            "failureStage": "before_typing", "xml": str(xml), "log": str(log),
            "xmlSha256": xml_sha, "logSha256": log_sha, "logLine": stops[0][0],
            "sourceRef": source_ref, "sourceSha256": sha(source.encode()), "priorIntentSha256": prior_hash})
        before_data = (growth / "comment-ledger.json").read_bytes()
        before = sha(before_data)
        comments.validate_ledger(ledger)
        if dry_run:
            return {"id": intent_id, "verifiedPreTyping": True, "dryRun": True,
                    "beforeSha256": before, "faultCleared": False}
        backup = growth/"reviews/not-sent-reviews"/("comment-ledger.pre-review-"+before+".json")
        if backup.exists() and backup.read_bytes() != before_data:
            raise ValueError("Conflicting pre-review backup")
        atomic_bytes(backup, before_data)
        try:
            comments.write_json(growth / "comment-ledger.json", ledger)
            comments.load_ledger(growth, required=True)
        except BaseException:
            if (growth / "comment-ledger.json").read_bytes() != before_data:
                atomic_bytes(growth / "comment-ledger.json", before_data)
            raise
        return {"id": intent_id, "state": "reviewedNotSent", "beforeSha256": before,
                "afterSha256": sha((growth / "comment-ledger.json").read_bytes()),
                "permanentlyConsumed": True, "budgetRefunded": False, "faultCleared": False,
                "backup": str(backup)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--account", choices=[comments.ACCOUNT], required=True)
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--dry-run", action="store_true")
    for name in ("intent", "xml", "log", "xml-sha256", "log-sha256", "source-ref", "reviewer", "reason"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    result = review_not_sent(a.repo.resolve()/"accounts"/a.account/"growth", a.intent,
        Path(a.xml), Path(a.log), a.xml_sha256, a.log_sha256, a.source_ref, a.reviewer, a.reason,
        dry_run=a.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
