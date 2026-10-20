"""Prepared queue, durable uncertainty and exact UI receipts, with no device/network."""
from datetime import datetime
import importlib.util
import itertools
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("public_comments", Path(__file__).resolve().parents[1] / "scripts/public_comments.py")
comments = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comments)
DAY = "2026-10-19"
AT = datetime.fromisoformat("2026-10-19T12:00:00+01:00")


def entry(number=1, **changes):
    result = dict(id=f"comment-{number}", handle=f"roofer{number}", postUrl=f"https://www.instagram.com/p/CODE{number}/",
                  captionSnippet=f"New roof in Kent {number}", text=f"Really neat finish on this roof {number}.",
                  sourceUrl=f"https://www.instagram.com/roofer{number}/", expiresAt="2026-10-26T12:00:00+00:00")
    result.update(changes)
    return result


def intent(number=1, state="posted", day=DAY, **changes):
    result = dict(entry(number), day=day, reservedAt=day + "T10:00:00+01:00", state=state)
    result.update(changes)
    return result


class FakeDevice:
    def __init__(self, growth, entries, receipt="exact", failure=None):
        self.growth, self.entries, self.receipt_kind, self.failure = growth, entries, receipt, failure
        self.current, self.screen, self.draft = entries[0], "home", ""
        self.account, self.owner, self.caption = comments.ACCOUNT, None, None
        self.hint = "Join the conversation…"
        self.posted, self.clicks, self.typed, self.backs = set(), 0, 0, 0
        self.restriction, self.reply = "", False

    def shell(self, args):
        if args[0] == "am":
            url = args[args.index("-d") + 1]
            self.current = next(e for e in self.entries if e["postUrl"] == url)
            self.screen = "post"

    def press(self, key):
        assert key == "back"
        self.backs += 1
        self.screen = "post" if self.screen == "comments" else "home"

    def dump_hierarchy(self):
        root = ET.Element("hierarchy")

        def node(resource="", text="", desc=""):
            ET.SubElement(root, "node", {"resource-id": comments.RID + resource, "text": text, "content-desc": desc, "enabled": "true"})

        if self.screen in {"home", "profile"}:
            node("profile_tab")
            if self.screen == "profile":
                node("action_bar_title", self.account)
        if self.screen == "post":
            node("row_feed_photo_profile_name", self.owner or self.current["handle"])
            node("caption", self.caption or self.current["captionSnippet"])
            node("row_feed_button_comment")
        if self.screen == "comments":
            node("layout_comment_thread_edittext_multiline", self.draft or self.hint)
            node("layout_comment_thread_post_button_icon", desc="Post")
            if self.current["id"] in self.posted:
                author, text = comments.ACCOUNT, self.current["text"]
                if self.receipt_kind == "wrong-author":
                    author = "someone.else"
                if self.receipt_kind == "prefix":
                    text = text[:20]
                if self.receipt_kind == "split":
                    node(desc=author + " said another comment")
                    node(desc="someone.else said " + text)
                else:
                    node("comment-row", desc=author + " said " + text)
            if self.reply:
                node(text="Replying to someone")
        if self.restriction:
            node(text=self.restriction)
        return ET.tostring(root, encoding="unicode")

    def __call__(self, resourceId, **kwargs):
        device = self
        name = resourceId.removeprefix(comments.RID)

        class Selector:
            def click(self):
                if name == "profile_tab":
                    device.screen = "profile"
                elif name == "row_feed_button_comment":
                    device.screen = "comments"
                elif name == "layout_comment_thread_post_button_icon":
                    ledger = comments.load_ledger(device.growth)
                    assert ledger["intents"][-1]["state"] == "reserved", "send before durable reservation"
                    device.clicks += 1
                    device.posted.add(device.current["id"])
                    device.draft = ""
                    if device.failure:
                        raise device.failure
                else:
                    raise AssertionError(name)

            def get_text(self):
                return device.draft or device.hint

            def set_text(self, text):
                device.typed += 1
                device.draft = text

        return Selector()


class PublicCommentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.growth = Path(self.temp.name) / "accounts/uk.tradeleads/growth"
        self.growth.mkdir(parents=True)
        self.seed([entry(1), entry(2), entry(3)])
        self.now = patch.object(comments, "now", return_value=AT)
        self.now.start()
        self.addCleanup(self.now.stop)
        self.sleep = patch.object(comments.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)
        self.clock = patch.object(comments.time, "monotonic", side_effect=itertools.count())
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def seed(self, entries, intents=None):
        comments.write_json(self.growth / "comment-policy.json", {"enabled": True, "dailyLimit": 2, "timezone": "Europe/London"})
        comments.write_json(self.growth / "comment-queue.json", {"comments": entries})
        comments.write_json(self.growth / "comment-ledger.json", {"version": 1, "intents": intents or []})

    def run_helper(self, device):
        return comments.run_comments(self.growth, comments.ACCOUNT, DAY, lambda: device)

    def test_policy_absent_is_off_and_enabled_missing_ledger_fails_closed(self):
        (self.growth / "comment-policy.json").unlink()
        self.assertFalse(comments.plan(self.growth)[0]["enabled"])
        self.seed([entry()])
        (self.growth / "comment-ledger.json").unlink()
        with self.assertRaises(ValueError):
            comments.plan(self.growth)

    def test_seeded_manual_receipts_use_today_budget_without_connecting(self):
        self.seed([entry(3)], [intent(1), intent(2)])
        connect = Mock(side_effect=AssertionError("must not connect"))
        status = comments.run_comments(self.growth, comments.ACCOUNT, DAY, connect)
        self.assertEqual((status["dailyCharged"], status["remaining"], status["pending"]), (2, 0, 1))
        connect.assert_not_called()

    def test_all_states_charge_budget_and_uncertainty_requires_review(self):
        for state in comments.STATES:
            with self.subTest(state=state):
                self.seed([entry(3)], [intent(1, state=state)])
                status = comments.plan(self.growth)[0]
                self.assertEqual(status["dailyCharged"], 1)
                self.assertEqual(status["reviewRequired"], state in {"reserved", "uncertain"})

    def test_shortcode_or_full_normalized_text_dedupes_across_days(self):
        old = intent(day="2026-10-18")
        self.seed([entry(2, postUrl="https://instagram.com/roofer2/p/CODE1/"),
                   entry(3, text=old["text"].upper().replace(" ", "  ")), entry(4)], [old])
        status, pending, _ = comments.plan(self.growth)
        self.assertEqual(status["dailyCharged"], 0)
        self.assertEqual([e["id"] for e in pending], ["comment-4"])

    def test_expired_entries_skip_but_malformed_even_expired_entries_fail_closed(self):
        self.seed([entry(expiresAt=AT.isoformat()), entry(2)])
        self.assertEqual(comments.plan(self.growth)[0]["pending"], 1)
        invalid = [dict(postUrl=url) for url in ["http://www.instagram.com/p/CODE1/", "https://www.instagram.com.evil/p/CODE1/", "https://www.instagram.com:443/p/CODE1/", "https://www.instagram.com/p/CODE1/?x=1", "https://www.instagram.com/p/CODE1/?", "https://www.instagram.com/p/CODE1/#", "https://www.instagram.com/other/p/CODE1/", "https://www.instagram.com/reel/CODE1/"]]
        invalid += [dict(handle="BadName"), dict(text=""), dict(text="x" * 221), dict(captionSnippet=" "), dict(captionSnippet="x" * 221),
                    dict(text="Visit our website"), dict(text="Nice work https://example.com"), dict(text="DM us"),
                    dict(sourceUrl="https://www.instagram.com/other/"), dict(expiresAt="2026-10-18T12:00:00")]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.seed([entry(**dict(dict(expiresAt="2026-10-18T12:00:00+01:00"), **changes))])
                comments.plan(self.growth)

    def test_duplicate_ids_json_keys_and_invalid_ledger_fail_closed(self):
        for manifest in [{"comments": [entry(), entry()]}, {"comments": None}]:
            comments.write_json(self.growth / "comment-queue.json", manifest)
            with self.assertRaises(ValueError):
                comments.plan(self.growth)
        self.seed([entry()])
        (self.growth / "comment-policy.json").write_text('{"enabled":true,"enabled":false,"dailyLimit":2,"timezone":"Europe/London"}')
        with self.assertRaises(ValueError):
            comments.plan(self.growth)
        self.seed([entry()], [intent(day="2026-10-18", reservedAt=AT.isoformat())])
        with self.assertRaises(ValueError):
            comments.plan(self.growth)

    def test_bot_comment_history_and_optional_receipt_session_dedupe(self):
        session = dict(id="bot-1", start_time="2026-10-18T23:30:00+00:00", finish_time="2026-10-18T23:40:00+00:00", total_comments=2)
        comments.write_json(self.growth.parent / "sessions.json", [session])
        self.seed([entry(3)], [intent(1, receiptSessionId="bot-1")])
        self.assertEqual(comments.plan(self.growth)[0]["dailyCharged"], 2)
        self.seed([entry(3)], [intent(1)])
        self.assertEqual(comments.plan(self.growth)[0]["dailyCharged"], 3)

    def test_restart_converts_durable_reservation_to_uncertain_without_device(self):
        self.seed([entry(2)], [intent(1, state="reserved", day="2026-10-18")])
        connect = Mock()
        with self.assertRaisesRegex(RuntimeError, "Uncertain"):
            comments.run_comments(self.growth, comments.ACCOUNT, DAY, connect)
        self.assertEqual(comments.load_ledger(self.growth)["intents"][0]["state"], "uncertain")
        connect.assert_not_called()

    def test_pause_before_attempt_does_not_connect_or_reserve(self):
        (self.growth / "paused.json").touch()
        connect = Mock()
        with self.assertRaisesRegex(RuntimeError, "Paused"):
            comments.run_comments(self.growth, comments.ACCOUNT, DAY, connect)
        connect.assert_not_called()
        self.assertEqual(comments.load_ledger(self.growth)["intents"], [])

    def test_two_consecutive_posts_are_reserved_once_and_have_fresh_private_receipts(self):
        device = FakeDevice(self.growth, [entry(1), entry(2), entry(3)])
        with patch.object(comments.os, "fsync", wraps=comments.os.fsync) as sync:
            status = self.run_helper(device)
        self.assertEqual((status["dailyCharged"], status["remaining"], device.clicks, device.typed), (2, 0, 2, 2))
        self.assertEqual(device.backs, 4)
        self.assertGreater(sync.call_count, 4)
        for record in comments.load_ledger(self.growth)["intents"]:
            self.assertEqual(record["state"], "posted")
            path = Path(record["evidence"])
            self.assertIn("uk.tradeleads said " + record["text"], path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.growth / "comment-ledger.json").stat().st_mode & 0o777, 0o600)
        self.run_helper(device)
        self.assertEqual(device.clicks, 2)

    def test_read_only_validation_twice_dismisses_sheet_never_types_or_sends(self):
        device = FakeDevice(self.growth, [entry(1), entry(2)])
        ui = comments.CommentUI(device, self.growth)
        ui.open_and_validate(entry(1))
        ui.open_and_validate(entry(2))
        self.assertEqual((device.backs, device.typed, device.clicks), (2, 0, 0))

    def test_keyboard_back_does_not_leave_comment_sheet_blocking_next_post(self):
        device = FakeDevice(self.growth, [entry(1), entry(2)])
        ui = comments.CommentUI(device, self.growth)
        ui.open_and_validate(entry(1))
        original_press = device.press

        def press(key):
            if device.backs == 0:
                device.backs += 1
            else:
                original_press(key)

        device.press = press
        ui.open_and_validate(entry(2))
        self.assertEqual((device.backs, device.typed, device.clicks), (3, 0, 0))

    def test_observed_question_hint_is_accepted_without_typing(self):
        device = FakeDevice(self.growth, [entry()])
        device.hint = "What do you think of this?"
        comments.CommentUI(device, self.growth).open_and_validate(entry())
        self.assertEqual((device.typed, device.clicks), (0, 0))

    def test_comment_sheet_that_will_not_close_stops_before_typing(self):
        device = FakeDevice(self.growth, [entry()])
        device.screen = "comments"
        device.press = Mock()
        with self.assertRaisesRegex(RuntimeError, "bounded Back"):
            comments.CommentUI(device, self.growth).open_and_validate(entry())
        self.assertEqual(device.press.call_count, 3)
        self.assertEqual((device.typed, device.clicks), (0, 0))

    def test_already_visible_exact_comment_is_charged_without_typing(self):
        self.seed([entry()])
        device = FakeDevice(self.growth, [entry()])
        device.posted.add(entry()["id"])
        status = self.run_helper(device)
        self.assertEqual((status["dailyCharged"], device.clicks, device.typed), (1, 0, 0))
        self.assertEqual(comments.load_ledger(self.growth)["intents"][0]["state"], "alreadyPosted")

    def test_send_interruption_never_clicks_again_on_restart(self):
        for failure in (RuntimeError("lost response"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                self.seed([entry()])
                device = FakeDevice(self.growth, [entry()], failure=failure)
                with self.assertRaises(type(failure)):
                    self.run_helper(device)
                self.assertEqual(comments.load_ledger(self.growth)["intents"][0]["state"], "uncertain")
                with self.assertRaisesRegex(RuntimeError, "Uncertain"):
                    self.run_helper(device)
                self.assertEqual(device.clicks, 1)

    def test_wrong_author_prefix_or_split_receipt_never_confirms_or_retries(self):
        for kind in ("wrong-author", "prefix", "split"):
            with self.subTest(kind=kind):
                self.seed([entry()])
                device = FakeDevice(self.growth, [entry()], receipt=kind)
                with self.assertRaisesRegex(RuntimeError, "Timed out"):
                    self.run_helper(device)
                self.assertEqual(device.clicks, 1)
                self.assertEqual(comments.load_ledger(self.growth)["intents"][0]["state"], "uncertain")

    def test_account_caption_owner_draft_reply_or_restriction_aborts_before_send(self):
        for field, value in [("account", "someone.else"), ("owner", "other.roofer"), ("caption", "Unrelated caption"),
                             ("draft", "An existing draft"), ("reply", True), ("restriction", "Try again later")]:
            with self.subTest(field=field):
                self.seed([entry()])
                device = FakeDevice(self.growth, [entry()])
                setattr(device, field, value)
                with self.assertRaises(RuntimeError):
                    self.run_helper(device)
                self.assertEqual((device.clicks, device.typed), (0, 0))
                self.assertEqual(comments.load_ledger(self.growth)["intents"][0]["state"], "uncertain")


if __name__ == "__main__":
    unittest.main()
