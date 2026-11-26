"""Operator reconciliation must prove a pre-typing stop and never regain budget."""
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from test_public_comments import comments, entry, intent, DAY, AT

spec = importlib.util.spec_from_file_location("review_comment_not_sent", Path(__file__).resolve().parents[1]/"scripts/review_comment_not_sent.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

SOURCE = '''class CommentUI:
    def open_and_validate(self, entry):
        hints = {"", "Join the conversation…"}
        raise RuntimeError("Existing draft or unknown composer hint")
    def submit(self, entry):
        root, path = self.open_and_validate(entry)
        composer.set_text(entry["text"])
        self.click("post")
'''


class NotSentReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.g = Path(self.temp.name)/"accounts/uk.tradeleads/growth"
        (self.g/"comments-log").mkdir(parents=True); (self.g/"logs").mkdir()
        comments.write_json(self.g/"comment-ledger.json", {"version":1,"intents":[intent(state="uncertain")]})
        comments.write_json(self.g/"comment-policy.json", {"enabled":True,"dailyLimit":2,"timezone":"Europe/London"})
        comments.write_json(self.g/"comment-queue.json", {"comments":[entry(),entry(2,postUrl=entry()["postUrl"]),entry(3,text=entry()["text"])]})
        comments.write_json(self.g/"fault.json", {"at":DAY+"T10:00:30+01:00","day":DAY,"reason":"Comment helper exited unsuccessfully"})
        comments.write_json(self.g/"days/day.json", {"status":"fault"})
        self.xml = self.g/"comments-log/id-composer.xml"
        self.xml.write_text('<hierarchy><node resource-id="'+comments.RID+'row_feed_photo_profile_name" text="roofer1"/><node text="New roof in Kent 1"/><node resource-id="'+comments.RID+'layout_comment_thread_edittext_multiline" text="Start the conversation…" focused="false"/></hierarchy>')
        self.stamp = datetime.fromisoformat(DAY+"T10:00:10+01:00").timestamp()
        os.utime(self.xml,(self.stamp,self.stamp))
        self.log = self.g/"logs"/(DAY+"-100000.log")
        self.log.write_text("Comments stopped for review: "+review.FAILURE+"\n")
        os.utime(self.log,(self.stamp,self.stamp))
        self.before = (self.g/"comment-ledger.json").read_bytes()

    def apply(self, **changes):
        args=dict(growth=self.g,intent_id="comment-1",xml=self.xml,log=self.log,
            xml_sha=review.sha(self.xml.read_bytes()),log_sha=review.sha(self.log.read_bytes()),
            source_ref="a"*40,reviewer="Codex operator",reason="Reviewed exact pre-typing failure and original source",
            source_reader=lambda _: SOURCE)
        args.update(changes)
        with patch.object(review,"comments",comments),patch.object(comments,"now",return_value=AT):
            return review.review_not_sent(**args)

    def test_resolution_keeps_charge_consumption_fault_and_journal(self):
        fault=(self.g/"fault.json").read_bytes();day=(self.g/"days/day.json").read_bytes()
        result=self.apply();self.assertFalse(result["budgetRefunded"]);self.assertTrue(result["permanentlyConsumed"])
        status,pending,ledger=comments.plan(self.g,DAY,AT)
        self.assertEqual(status["dailyCharged"],1);self.assertFalse(status["reviewRequired"]);self.assertEqual(pending,[])
        self.assertEqual(comments.plan(self.g,"2026-10-20",AT)[0]["pending"],0)
        self.assertEqual((self.g/"fault.json").read_bytes(),fault);self.assertEqual((self.g/"days/day.json").read_bytes(),day)
        self.assertEqual(ledger["intents"][0]["notSentReview"]["priorIntentSha256"], review.sha(json.dumps(intent(state="uncertain"),sort_keys=True,separators=(",",":")).encode()))
        self.assertFalse(comments.recover_reservations(self.g))

    def test_wrong_hash_log_source_or_unknown_intent_preserves_ledger(self):
        for change in [dict(xml_sha="0"*64),dict(log_sha="0"*64),dict(intent_id="unknown"),dict(source_reader=lambda _:SOURCE.replace("open_and_validate(entry)","send(entry)")),dict(source_reader=lambda _:SOURCE.replace(review.FAILURE,"Timed out verifying receipt"))]:
            with self.subTest(change=change),self.assertRaises((ValueError,KeyError)):
                self.apply(**change)
            self.assertEqual((self.g/"comment-ledger.json").read_bytes(),self.before)
        self.log.write_text("Comments stopped for review: Timed out verifying receipt\n")
        with self.assertRaises(ValueError):self.apply()

    def test_draft_receipt_wrong_owner_caption_restriction_and_late_xml_stay_held(self):
        original=self.xml.read_text()
        for xml in [original.replace("Start the conversation…",entry()["text"]),original.replace("roofer1","other"),original.replace("New roof in Kent 1","another caption"),original.replace("</hierarchy>",'<node content-desc="uk.tradeleads said anything"/></hierarchy>'),original.replace("</hierarchy>",'<node text="Action blocked"/></hierarchy>')]:
            self.xml.write_text(xml);os.utime(self.xml,(self.stamp,self.stamp))
            with self.assertRaises(ValueError):self.apply()
        self.xml.write_text(original);os.utime(self.xml,(self.stamp+60,self.stamp+60))
        with self.assertRaises(ValueError):self.apply()
        os.utime(self.xml,(self.stamp,self.stamp))
        for phase in ("prepared","receipt","fresh-receipt"):
            p=self.g/"comments-log"/('other-'+phase+'.xml');p.write_text(original);os.utime(p,(self.stamp,self.stamp))
            with self.assertRaises(ValueError):self.apply()
            p.unlink()
        self.assertEqual((self.g/"comment-ledger.json").read_bytes(),self.before)

    def test_confirmed_reserved_or_receipt_bearing_intents_cannot_be_reviewed(self):
        for state in ["posted","alreadyPosted","reserved"]:
            comments.write_json(self.g/"comment-ledger.json",{"version":1,"intents":[intent(state=state)]})
            with self.assertRaises(ValueError):self.apply()
        for field in ("evidence","commentUrl"):
            comments.write_json(self.g/"comment-ledger.json",{"version":1,"intents":[intent(state="uncertain",**{field:"existing-receipt"})]})
            with self.assertRaises(ValueError):self.apply()

    def test_atomic_replace_failure_and_bad_review_metadata_fail_closed(self):
        with patch.object(comments.os,"replace",side_effect=OSError("power loss")),self.assertRaises(OSError):self.apply()
        self.assertEqual((self.g/"comment-ledger.json").read_bytes(),self.before)
        self.apply()
        ledger=comments.load_ledger(self.g)
        for field in ("evidence","receiptSessionId","commentUrl"):
            bad=json.loads(json.dumps(ledger));bad['intents'][0][field]="fake"
            comments.write_json(self.g/"comment-ledger.json",bad)
            with self.assertRaises(ValueError):comments.load_ledger(self.g)

    def test_manual_pause_is_preserved_and_lock_contention_refuses_review(self):
        import fcntl
        comments.write_json(self.g/'paused.json', {'reason':'operator pause'})
        pause=(self.g/'paused.json').read_bytes()
        with (self.g/'worker.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):self.apply()
        self.apply()
        self.assertEqual((self.g/'paused.json').read_bytes(),pause)

    def test_wrong_fault_or_mixed_log_or_later_snapshot_cannot_release(self):
        old=comments.read_json(self.g/'fault.json')
        for changes in [dict(reason='Account restriction'),dict(day='2026-10-20'),dict(at=DAY+'T10:04:00+01:00')]:
            comments.write_json(self.g/'fault.json',dict(old,**changes))
            with self.assertRaises(ValueError):self.apply()
        comments.write_json(self.g/'fault.json',old)
        original=self.log.read_text()
        self.log.write_text(original+'Comments stopped for review: something else\n');os.utime(self.log,(self.stamp,self.stamp))
        with self.assertRaises(ValueError):self.apply()
        self.log.write_text(original);os.utime(self.log,(self.stamp+100,self.stamp+100))
        with self.assertRaises(ValueError):self.apply()
        os.utime(self.log,(self.stamp,self.stamp))
        p=self.g/'comments-log/later-post.xml';p.write_text('<hierarchy/>');os.utime(p,(self.stamp+1,self.stamp+1))
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual((self.g/'comment-ledger.json').read_bytes(),self.before)

    def test_outside_evidence_and_source_that_accepts_hint_cannot_release(self):
        outside=Path(self.temp.name)/'outside.xml';outside.write_bytes(self.xml.read_bytes())
        with self.assertRaises(ValueError):self.apply(xml=outside)
        with self.assertRaises(ValueError):self.apply(source_reader=lambda _:SOURCE.replace('"Join the conversation…"','"Start the conversation…"'))

    def test_post_write_validation_failure_restores_byte_exact_backup(self):
        original=comments.load_ledger
        calls=0
        def load(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:raise ValueError('injected post-write check failure')
            return original(*args,**kwargs)
        with patch.object(comments,'load_ledger',side_effect=load),self.assertRaises(ValueError):self.apply()
        self.assertEqual((self.g/'comment-ledger.json').read_bytes(),self.before)

    def test_source_ref_must_match_actual_git_helper_revision_at_reservation(self):
        repo=self.g.parents[2]
        def git(*args, date=None):
            env=dict(os.environ,GIT_AUTHOR_NAME='Test',GIT_AUTHOR_EMAIL='test@example.invalid',
                GIT_COMMITTER_NAME='Test',GIT_COMMITTER_EMAIL='test@example.invalid')
            if date:env.update(GIT_AUTHOR_DATE=date,GIT_COMMITTER_DATE=date)
            return subprocess.check_output(['git',*args],cwd=repo,env=env,stderr=subprocess.DEVNULL).decode().strip()
        git('init');(repo/'scripts').mkdir();source=repo/'scripts/public_comments.py'
        source.write_text(SOURCE);git('add','scripts/public_comments.py');git('commit','-m','first',date=DAY+'T08:00:00+01:00');old=git('rev-parse','HEAD')
        source.write_text(SOURCE+'\n');git('add','scripts/public_comments.py');git('commit','-m','last deployed helper',date=DAY+'T09:00:00+01:00');actual=git('rev-parse','HEAD')
        source.write_text(SOURCE.replace('"Join the conversation…"','"Start the conversation…"'));git('add','scripts/public_comments.py');git('commit','-m','later repair',date=DAY+'T11:00:00+01:00');future=git('rev-parse','HEAD')
        for ref in (old,future):
            with self.assertRaises(ValueError):self.apply(source_reader=None,source_ref=ref)
        self.apply(source_reader=None,source_ref=actual)

