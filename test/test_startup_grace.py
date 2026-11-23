import time

from InstaAddict.core import watchdog


def test_startup_grace_keeps_heartbeat_fresh_then_stops(monkeypatch):
    beats = []
    monkeypatch.setattr(watchdog, "record_heartbeat", lambda stage=None, action=None: beats.append(time.monotonic()))
    with watchdog.StartupGrace("launch", limit=0.35, interval=0.05):
        time.sleep(0.6)
        count_at_end = len(beats)
    assert 4 <= count_at_end <= 9  # initial beat plus beats only inside the limit
    time.sleep(0.15)
    assert len(beats) == count_at_end


def test_startup_grace_stops_on_exit(monkeypatch):
    beats = []
    monkeypatch.setattr(watchdog, "record_heartbeat", lambda stage=None, action=None: beats.append(1))
    with watchdog.StartupGrace("launch", limit=10, interval=0.05):
        time.sleep(0.12)
    after = len(beats)
    time.sleep(0.2)
    assert len(beats) == after


def test_watchdog_soft_timeout_not_hit_during_grace():
    wd = watchdog.BotWatchdog.get_instance()
    wd.last_heartbeat = time.time() - 1000
    with watchdog.StartupGrace("launch", limit=1, interval=0.05):
        time.sleep(0.1)
        assert time.time() - wd.last_heartbeat < wd.soft_timeout
