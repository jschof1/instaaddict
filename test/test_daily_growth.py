"""Critical daily-budget and replay protection, without a device or dependencies."""
from datetime import datetime
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
