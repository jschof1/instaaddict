import atexit
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BotWatchdog:
    """
    Autonomous out-of-band watchdog monitoring the bot execution health.

    Runs on an isolated daemon background thread. Detects if main thread or
    ADB connection becomes hung/stuck, and executes escalating actions:
      - Tier 1 (Soft Recovery): KEYCODE_WAKEUP + KEYCODE_BACK
      - Tier 2 (Task Skip): Requests task skip via DashboardManager & IPC
      - Tier 3 (Nuclear Restart): Force-stop Instagram app and monkey relaunch
    """

    _instance: Optional["BotWatchdog"] = None
    _lock: threading.RLock = threading.RLock()

    @classmethod
    def get_instance(
        cls,
        device_id: Optional[str] = None,
        app_id: str = "com.instagram.android",
        soft_timeout: float = 90.0,
        skip_timeout: float = 105.0,
        hard_timeout: float = 120.0,
        check_interval: float = 5.0,
    ) -> "BotWatchdog":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(
                    device_id=device_id,
                    app_id=app_id,
                    soft_timeout=soft_timeout,
                    skip_timeout=skip_timeout,
                    hard_timeout=hard_timeout,
                    check_interval=check_interval,
                )
            else:
                if device_id is not None:
                    cls._instance.device_id = device_id
                if app_id:
                    cls._instance.app_id = app_id
                if soft_timeout != 90.0:
                    cls._instance.soft_timeout = max(soft_timeout, 5.0)
                if skip_timeout != 105.0:
                    cls._instance.skip_timeout = max(
                        skip_timeout, cls._instance.soft_timeout
                    )
                if hard_timeout != 120.0:
                    cls._instance.hard_timeout = max(
                        hard_timeout, cls._instance.skip_timeout
                    )
                if check_interval != 5.0:
                    cls._instance.check_interval = max(check_interval, 0.5)
            return cls._instance

    def __init__(
        self,
        device_id: Optional[str] = None,
        app_id: str = "com.instagram.android",
        soft_timeout: float = 90.0,
        skip_timeout: float = 105.0,
        hard_timeout: float = 120.0,
        check_interval: float = 5.0,
    ):
        self.device_id: Optional[str] = device_id
        self.app_id: str = app_id
        self.soft_timeout: float = max(soft_timeout, 5.0)
        self.skip_timeout: float = max(skip_timeout, self.soft_timeout)
        self.hard_timeout: float = max(hard_timeout, self.skip_timeout)
        self.check_interval: float = max(check_interval, 0.5)

        self.last_heartbeat: float = time.time()
        self.current_tier: int = 0
        self.last_recovery_time: float = 0.0
        self.current_stage: str = "init"
        self.current_action: str = "starting"
        self.is_paused: bool = False
        self.is_running: bool = False
        self.recovering: bool = False
        self.recovery_attempts: int = 0
        self.recovery_history: List[Dict[str, Any]] = []

        self._stop_event: threading.Event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        atexit.register(self.stop)

    def heartbeat(
        self,
        stage: Optional[str] = None,
        action: Optional[str] = None,
    ):
        """Record a heartbeat from active flow to keep watchdog alive."""
        with self._lock:
            self.last_heartbeat = time.time()
            if stage is not None:
                self.current_stage = stage
            if action is not None:
                self.current_action = action
            self.current_tier = 0
            self.recovering = False

    def pause(self):
        """Pause watchdog monitoring during sleep/cooldown intervals."""
        with self._lock:
            self.is_paused = True
            self.last_heartbeat = time.time()
            self.current_tier = 0
            self.recovering = False

    def resume(self):
        """Resume watchdog monitoring upon entering active execution work."""
        with self._lock:
            self.is_paused = False
            self.last_heartbeat = time.time()
            self.current_tier = 0
            self.recovering = False

    def start(self):
        """Start the background watchdog monitoring thread."""
        with self._lock:
            if self.is_running and self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self.is_running = True
            self.last_heartbeat = time.time()
            self.current_tier = 0
            self.recovering = False
            self._thread = threading.Thread(
                target=self._run_loop,
                name="BotWatchdogThread",
                daemon=True,
            )
            self._thread.start()

    def stop(self):
        """Stop the background watchdog monitoring thread."""
        with self._lock:
            self.is_running = False
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                try:
                    self._thread.join(timeout=2.0)
                except Exception:
                    pass
                self._thread = None

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status snapshot for dashboard and telemetry."""
        with self._lock:
            now = time.time()
            elapsed = max(0.0, now - self.last_heartbeat)
            if not self.is_running:
                state = "STOPPED"
            elif self.is_paused:
                state = "PAUSED"
            elif self.recovering or self.current_tier > 0 or elapsed >= self.soft_timeout:
                state = "RECOVERING"
            elif elapsed >= 30.0:
                state = "STALLED"
            else:
                state = "HEALTHY"

            return {
                "state": state,
                "elapsed": elapsed,
                "attempts": self.recovery_attempts,
                "current_tier": self.current_tier,
                "stage": self.current_stage,
                "action": self.current_action,
                "is_paused": self.is_paused,
                "is_running": self.is_running,
                "recovering": self.recovering,
            }

    def is_healthy(self) -> bool:
        return self.get_status()["state"] == "HEALTHY"

    def is_stalled(self) -> bool:
        return self.get_status()["state"] == "STALLED"

    def is_recovering(self) -> bool:
        return self.get_status()["state"] == "RECOVERING"

    def _run_loop(self):
        """Continuous background loop inspecting bot heartbeat freshness."""
        while not self._stop_event.wait(timeout=self.check_interval):
            with self._lock:
                if not self.is_running or self.is_paused:
                    continue
                now = time.time()
                elapsed = now - self.last_heartbeat
                tier = self.current_tier
                last_rec = self.last_recovery_time

            if elapsed >= self.hard_timeout:
                if tier < 3 or (now - last_rec >= self.hard_timeout):
                    self._execute_hard_recovery(elapsed)
            elif elapsed >= self.skip_timeout:
                if tier < 2:
                    self._execute_skip_recovery(elapsed)
            elif elapsed >= self.soft_timeout:
                if tier < 1:
                    self._execute_soft_recovery(elapsed)

    def _run_adb_cmd(
        self,
        args: List[str],
        timeout: float = 5.0,
    ) -> Optional[subprocess.CompletedProcess]:
        cmd = ["adb"]
        if self.device_id:
            cmd.extend(["-s", str(self.device_id)])
        cmd.extend(args)
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.debug(f"[WATCHDOG] ADB command {cmd} error: {e}")
            return None

    def _record_recovery_kpi(self):
        try:
            from InstaAddict.core.session_state import SessionState

            active_ss = SessionState.get_active()
            if active_ss and hasattr(
                active_ss, "increment_watchdog_recoveries"
            ):
                active_ss.increment_watchdog_recoveries()
        except Exception:
            pass

    def _execute_soft_recovery(self, elapsed: float):
        """Tier 1: Send KEYCODE_WAKEUP and KEYCODE_BACK."""
        with self._lock:
            self.recovering = True
            self.current_tier = 1
            self.last_recovery_time = time.time()
            self.recovery_attempts += 1
            self.recovery_history.append(
                {
                    "tier": 1,
                    "action": "soft_keyevent_back",
                    "timestamp": datetime.now().isoformat(),
                    "elapsed": elapsed,
                }
            )

        logger.warning(
            f"[WATCHDOG] Tier 1 Triggered: Inactivity ({elapsed:.1f}s >= "
            f"{self.soft_timeout}s). Dispatching WAKEUP and KEYCODE_BACK..."
        )
        self._record_recovery_kpi()
        try:
            self._run_adb_cmd(["shell", "input", "keyevent", "224"])
            self._run_adb_cmd(["shell", "input", "keyevent", "4"])
            self._run_adb_cmd(["shell", "input", "keyevent", "4"])
        except Exception as e:
            logger.error(f"[WATCHDOG] Soft recovery execution error: {e}")

    def _execute_skip_recovery(self, elapsed: float):
        """Tier 2: Request task skip to advance to next scheduled work item."""
        with self._lock:
            self.recovering = True
            self.current_tier = 2
            self.last_recovery_time = time.time()
            self.recovery_attempts += 1
            self.recovery_history.append(
                {
                    "tier": 2,
                    "action": "skip_task",
                    "timestamp": datetime.now().isoformat(),
                    "elapsed": elapsed,
                }
            )

        logger.warning(
            f"[WATCHDOG] Tier 2 Triggered: Bot frozen ({elapsed:.1f}s >= "
            f"{self.skip_timeout}s). Flagging task skip to advance..."
        )
        self._record_recovery_kpi()
        try:
            from InstaAddict.core.tui import DashboardManager

            if DashboardManager.is_active():
                DashboardManager.get_instance().trigger_skip_task()

            from InstaAddict.core.session_state import SessionState

            active_ss = SessionState.get_active()
            if active_ss and active_ss.my_username:
                account_dir = os.path.join("accounts", active_ss.my_username)
                if os.path.isdir(account_dir):
                    sig_path = os.path.join(account_dir, ".skip_task")
                    with open(sig_path, "w") as f:
                        f.write(str(time.time()))
        except Exception as e:
            logger.error(f"[WATCHDOG] Skip recovery execution error: {e}")

    def _execute_hard_recovery(self, elapsed: float):
        """Tier 3: Nuclear recovery: force-stop app and relaunch via monkey."""
        with self._lock:
            self.recovering = True
            self.current_tier = 3
            self.last_recovery_time = time.time()
            self.recovery_attempts += 1
            self.recovery_history.append(
                {
                    "tier": 3,
                    "action": "force_stop_relaunch",
                    "timestamp": datetime.now().isoformat(),
                    "elapsed": elapsed,
                }
            )

        logger.error(
            f"[WATCHDOG] Tier 3 Triggered: Hang ({elapsed:.1f}s >= "
            f"{self.hard_timeout}s). Force-stopping {self.app_id}..."
        )
        self._record_recovery_kpi()
        try:
            self._run_adb_cmd(["shell", "am", "force-stop", self.app_id])
            time.sleep(1.0)
            self._run_adb_cmd(
                [
                    "shell",
                    "monkey",
                    "-p",
                    self.app_id,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ]
            )
        except Exception as e:
            logger.error(f"[WATCHDOG] Hard recovery execution error: {e}")


def record_heartbeat(stage: Optional[str] = None, action: Optional[str] = None) -> None:
    """Safe module-level utility to record a heartbeat without throwing exceptions."""
    try:
        if BotWatchdog._instance is not None:
            BotWatchdog.get_instance().heartbeat(stage=stage, action=action)
    except Exception:
        pass


class StartupGrace:
    """Keep the heartbeat fresh while a blocking app launch is in progress.

    Instagram's cold start on an emulator can block a single uiautomator call
    for more than the 90s soft timeout. The grace is bounded, so a launch that
    is still stuck after ``limit`` seconds lets the watchdog fire as normal.
    """

    def __init__(self, action: str, limit: float = 240.0, interval: float = 10.0):
        self.action = action
        self.limit = limit
        self.interval = interval
        self._done = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _beat(self) -> None:
        deadline = time.monotonic() + self.limit
        while time.monotonic() < deadline and not self._done.wait(self.interval):
            if time.monotonic() < deadline:
                record_heartbeat("startup", self.action)

    def __enter__(self) -> "StartupGrace":
        record_heartbeat("startup", self.action)
        self._thread = threading.Thread(target=self._beat, name="StartupGrace", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
