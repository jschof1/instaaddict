import logging
import re
import string
import warnings
from datetime import datetime
from enum import Enum, auto
from inspect import stack
from os import getcwd, listdir
from random import randint, uniform
from re import search
from subprocess import PIPE, run
from time import sleep
from typing import Optional

import uiautomator2

from InstaAddict.core.utils import random_sleep

# Silence noisy third-party deprecation warnings
warnings.filterwarnings("ignore", message=".*forward_list is deprecated.*")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

logger = logging.getLogger(__name__)

_GRAPHEME_CLUSTER_RE = re.compile(
    r"(?:"
    r"[\U00010000-\U0010FFFF](?:[\u200D\uFE0E\uFE0F]|[\U00010000-\U0010FFFF])*"
    r"|[\u2600-\u27BF](?:[\u200D\uFE0E\uFE0F]|[\u2600-\u27BF])*"
    r"|.[\u0300-\u036F\uFE00-\uFE0F\u200D]*"
    r")",
    re.UNICODE,
)


def _split_into_grapheme_clusters(s: str) -> list:
    """Splits string into atomic visual/grapheme units so emojis and modifiers are not severed."""
    clusters = _GRAPHEME_CLUSTER_RE.findall(s)
    return clusters if clusters else list(s)


def _apply_uiautomator2_compatibility_patches():
    """Patch uiautomator2 for Android 14+ / AndroidX / modern packaging compatibility."""
    if getattr(uiautomator2.Device, "_acp_compatibility_patched", False):
        return
    uiautomator2.Device._acp_compatibility_patched = True

    # 1. Patch current_ime regex for Android 14+ / modern IME compatibility
    def patched_current_ime(dev_self):
        _INPUT_METHOD_RE = re.compile(
            r"(?:mCurMethodId|mCurImeId|mSelectedImeId)=([-_./\w]+)"
        )
        dim, _ = dev_self.shell(["dumpsys", "input_method"])
        m = _INPUT_METHOD_RE.search(dim)
        method_id = None if not m else m.group(1)
        shown = "mInputShown=true" in dim
        return (method_id, shown)

    uiautomator2.Device.current_ime = patched_current_ime

    # 2. Patch _package_version to safely handle versionName=null / missing version without crashing
    # with packaging.version.InvalidVersion: Invalid version: ''
    def patched_package_version(dev_self, package_name: str):
        import packaging.version

        if dev_self.shell(["pm", "path", package_name]).exit_code != 0:
            return None
        try:
            dump_output = dev_self.shell(["dumpsys", "package", package_name]).output
            m = re.compile(r"versionName=(?P<name>[\d.]+)").search(dump_output)
            if m and m.group("name"):
                return packaging.version.parse(m.group("name"))
        except Exception:
            pass
        # Fallback version for test packages or packages where versionName is null
        return packaging.version.parse("2.3.3")

    uiautomator2.Device._package_version = patched_package_version

    # 3. Patch _test_run_instrument to detect androidx.test.runner.AndroidJUnitRunner
    def patched_test_run_instrument(dev_self):
        runner = "androidx.test.runner.AndroidJUnitRunner"
        try:
            res = dev_self.shell(["pm", "list", "instrumentation"]).output
            if "androidx.test.runner.AndroidJUnitRunner" not in res:
                runner = "android.support.test.runner.AndroidJUnitRunner"
        except Exception:
            pass
        return dev_self.shell(
            [
                "am",
                "instrument",
                "-w",
                "-r",
                "-e",
                "debug",
                "false",
                "-e",
                "class",
                "com.github.uiautomator.stub.Stub",
                f"com.github.uiautomator.test/{runner}",
            ]
        ).output

    uiautomator2.Device._test_run_instrument = patched_test_run_instrument

    # 4. Patch _Service.start to launch androidx.test.runner.AndroidJUnitRunner properly
    # Because atx-agent on device hardcodes android.support.test.runner.AndroidJUnitRunner which fails on modern Android
    try:
        from uiautomator2 import _Service
        _orig_service_start = _Service.start

        def patched_service_start(srv_self):
            try:
                _orig_service_start(srv_self)
            except Exception:
                pass
            runner = "androidx.test.runner.AndroidJUnitRunner"
            try:
                res = srv_self.u2obj.shell(["pm", "list", "instrumentation"]).output
                if "androidx.test.runner.AndroidJUnitRunner" not in res and "android.support.test.runner.AndroidJUnitRunner" in res:
                    runner = "android.support.test.runner.AndroidJUnitRunner"
            except Exception:
                pass
            srv_self.u2obj.shell(
                f"nohup am instrument -w -r -e debug false -e class com.github.uiautomator.stub.Stub com.github.uiautomator.test/{runner} > /dev/null 2>&1 &"
            )

        _Service.start = patched_service_start
    except Exception as e:
        logger.debug(f"Failed to patch _Service.start: {e}")

    # 5. Patch reset_uiautomator to recover gracefully on modern AndroidX devices without raising EnvironmentError
    try:
        _orig_reset_uiautomator = uiautomator2.Device.reset_uiautomator

        def patched_reset_uiautomator(dev_self, reason="unknown", depth=0):
            try:
                if dev_self._is_alive():
                    return True
            except Exception:
                pass
            try:
                return _orig_reset_uiautomator(dev_self, reason=reason, depth=depth)
            except Exception as reset_err:
                try:
                    if dev_self._is_alive():
                        return True
                except Exception:
                    pass
                logger.warning(
                    f"uiautomator2 reset_uiautomator failed ({reset_err}). Triggering AndroidX resurrection fallback..."
                )
                runner = "androidx.test.runner.AndroidJUnitRunner"
                try:
                    res = dev_self.shell(["pm", "list", "instrumentation"]).output
                    if "androidx.test.runner.AndroidJUnitRunner" not in res and "android.support.test.runner.AndroidJUnitRunner" in res:
                        runner = "android.support.test.runner.AndroidJUnitRunner"
                except Exception:
                    pass
                try:
                    dev_self.shell(["/data/local/tmp/atx-agent", "server", "--stop"])
                    dev_self.shell(["/data/local/tmp/atx-agent", "server", "--nouia", "-d", "--addr", "127.0.0.1:7912"])
                except Exception:
                    pass
                try:
                    dev_self.shell(["pkill", "-f", "com.github.uiautomator"])
                except Exception:
                    pass
                try:
                    dev_self.shell(
                        f"nohup am instrument -w -r -e debug false -e class com.github.uiautomator.stub.Stub com.github.uiautomator.test/{runner} > /dev/null 2>&1 &"
                    )
                except Exception:
                    pass
                sleep(2)
                try:
                    if dev_self._is_alive():
                        logger.info("Resurrection fallback succeeded; uiautomator is alive.")
                        return True
                except Exception:
                    pass
                if depth >= 2:
                    raise
                return False

        uiautomator2.Device.reset_uiautomator = patched_reset_uiautomator
    except Exception as e:
        logger.debug(f"Failed to patch reset_uiautomator: {e}")


# Apply compatibility patches at module load
_apply_uiautomator2_compatibility_patches()


def create_device(device_id, app_id):
    try:
        return DeviceFacade(device_id, app_id)
    except ImportError as e:
        logger.error(str(e))
        return None


def get_device_info(device):
    try:
        info = device.get_info() if hasattr(device, "get_info") else {}
    except Exception as e:
        logger.warning(f"Could not retrieve device info via RPC ({e}), using fallback defaults.")
        info = getattr(device, "_get_info_via_adb", lambda: {})()

    product_name = info.get("productName", "Android Device")
    sdk_int = info.get("sdkInt", 0)
    display_w = info.get("displayWidth", 0)
    display_h = info.get("displayHeight", 0)
    dp_x = info.get("displaySizeDpX", 0)
    dp_y = info.get("displaySizeDpY", 0)

    logger.debug(f"Phone Name: {product_name}, SDK Version: {sdk_int}")
    try:
        if int(sdk_int) < 19:
            logger.warning("Only Android 4.4+ (SDK 19+) devices are supported!")
    except (ValueError, TypeError):
        pass

    logger.debug(f"Screen dimension: {display_w}x{display_h}")
    logger.debug(f"Screen resolution: {dp_x}x{dp_y}")
    try:
        serial = (
            device.deviceV2.serial
            if hasattr(device, "deviceV2") and device.deviceV2
            else getattr(device, "device_id", "unknown")
        )
        logger.debug(f"Device ID: {serial}")
    except Exception:
        logger.debug(f"Device ID: {getattr(device, 'device_id', 'unknown')}")


class Timeout(Enum):
    ZERO = auto()
    TINY = auto()
    SHORT = auto()
    MEDIUM = auto()
    LONG = auto()


class SleepTime(Enum):
    ZERO = auto()
    TINY = auto()
    SHORT = auto()
    DEFAULT = auto()


class Location(Enum):
    CUSTOM = auto()
    WHOLE = auto()
    CENTER = auto()
    BOTTOM = auto()
    RIGHT = auto()
    LEFT = auto()
    BOTTOMRIGHT = auto()
    LEFTEDGE = auto()
    RIGHTEDGE = auto()
    TOPLEFT = auto()


class Direction(Enum):
    UP = auto()
    DOWN = auto()
    RIGHT = auto()
    LEFT = auto()


class Mode(Enum):
    TYPE = auto()
    PASTE = auto()


class DeviceFacade:
    def __init__(self, device_id, app_id):
        self.device_id = device_id
        self.app_id = app_id
        _apply_uiautomator2_compatibility_patches()
        self._ensure_adb_healthy(device_id)
        try:
            if device_id is None or "." not in device_id:
                self.deviceV2 = uiautomator2.connect(
                    "" if device_id is None else device_id
                )
            else:
                self.deviceV2 = uiautomator2.connect_adb_wifi(f"{device_id}")
        except ImportError:
            raise ImportError("Please install uiautomator2: pip3 install uiautomator2")
        except Exception as e:
            logger.warning(
                f"Initial connection to device {device_id} failed ({e}). Attempting ADB recovery..."
            )
            self._recover_adb()
            if device_id is None or "." not in device_id:
                self.deviceV2 = uiautomator2.connect(
                    "" if device_id is None else device_id
                )
            else:
                self.deviceV2 = uiautomator2.connect_adb_wifi(f"{device_id}")
        self.ensure_uiautomator_alive()

    @staticmethod
    def _recover_adb(device_id: Optional[str] = None):
        """Recovers stale or offline ADB transport connections by restarting the ADB server daemon, or reconnecting specific device in multi-account mode."""
        import subprocess

        try:
            if os.environ.get("INSTAADDICT_MULTI_ACCOUNT") == "1":
                if device_id:
                    logger.info(
                        f"Multi-account mode active: executing targeted 'adb -s {device_id} reconnect' without killing shared ADB server (GAP-08)..."
                    )
                    subprocess.run(["adb", "-s", device_id, "reconnect"], capture_output=True, timeout=10)
                    sleep(1)
                    subprocess.run(["adb", "-s", device_id, "reconnect", "device"], capture_output=True, timeout=10)
                    sleep(2)
                else:
                    logger.warning("Multi-account mode active: suppressing global adb kill-server to protect sibling bots.")
                return

            logger.info("Executing 'adb kill-server && adb start-server' to refresh transport...")
            subprocess.run(["adb", "kill-server"], capture_output=True, timeout=10)
            sleep(1)
            subprocess.run(["adb", "start-server"], capture_output=True, timeout=15)
            sleep(2)
        except Exception as err:
            logger.warning(f"ADB server recovery encountered an error: {err}")

    def _ensure_adb_healthy(self, device_id: Optional[str]):
        """Checks if ADB reports the target device as offline, and auto-recovers if so."""
        if not device_id or "." in device_id:
            return
        import subprocess

        try:
            res = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, timeout=10
            )
            for line in res.stdout.splitlines():
                if device_id in line and "offline" in line:
                    logger.warning(
                        f"Device {device_id} detected as 'offline' in ADB. Automatically refreshing ADB transport..."
                    )
                    self._recover_adb(device_id)
                    break
        except Exception:
            pass

    def ensure_uiautomator_alive(self) -> bool:
        """Verify that uiautomator2's accessibility service / UiAutomation is connected and responsive."""
        try:
            self.deviceV2.dump_hierarchy(compressed=False)
            return True
        except Exception as e:
            logger.warning(
                f"Detected disconnected/crashed UiAutomation service ({e}). Performing automated resurrection..."
            )
            runner = "androidx.test.runner.AndroidJUnitRunner"
            try:
                res = self.deviceV2.shell(["pm", "list", "instrumentation"]).output
                if "androidx.test.runner.AndroidJUnitRunner" not in res and "android.support.test.runner.AndroidJUnitRunner" in res:
                    runner = "android.support.test.runner.AndroidJUnitRunner"
            except Exception:
                pass
            try:
                self.deviceV2.shell(["/data/local/tmp/atx-agent", "server", "--stop"])
                self.deviceV2.shell(["/data/local/tmp/atx-agent", "server", "--nouia", "-d", "--addr", "127.0.0.1:7912"])
            except Exception:
                pass
            try:
                self.deviceV2.shell(["pkill", "-f", "com.github.uiautomator"])
            except Exception:
                pass
            try:
                self.deviceV2.shell(
                    f"nohup am instrument -w -r -e debug false -e class com.github.uiautomator.stub.Stub com.github.uiautomator.test/{runner} > /dev/null 2>&1 &"
                )
            except Exception as launch_err:
                logger.debug(f"Failed to launch instrumentation: {launch_err}")
            sleep(2)
            try:
                self.deviceV2.dump_hierarchy(compressed=False)
                logger.info("UiAutomation service successfully resurrected.")
                return True
            except Exception as r_err:
                logger.warning(f"Secondary UiAutomation resurrection attempt failed: {r_err}")
            return False

    def _get_current_app(self):
        try:
            return self.deviceV2.app_current()["package"]
        except Exception as e:
            raise DeviceFacade.JsonRpcError(e)

    def _ig_is_opened(self) -> bool:
        return self._get_current_app() == self.app_id

    def check_if_ig_is_opened(func):
        def wrapper(self, **kwargs):
            avoid_lst = ["choose_cloned_app", "check_if_crash_popup_is_there"]
            caller = stack()[1].function
            current_app = self._get_current_app()
            if current_app != self.app_id and caller not in avoid_lst:
                raise DeviceFacade.AppHasCrashed(
                    f"App has crashed / has been closed! foreground_package={current_app!r} expected_package={self.app_id!r}"
                )
            return func(self, **kwargs)

        return wrapper

    @check_if_ig_is_opened
    def find(
        self,
        index=None,
        **kwargs,
    ):
        try:
            view = self.deviceV2(**kwargs)
            if index is not None and view.count > 1:
                view = self.deviceV2(**kwargs)[index]
        except Exception as e:
            raise DeviceFacade.JsonRpcError(e)
        return DeviceFacade.View(view=view, device=self.deviceV2)

    def back(self, modulable: bool = True):
        logger.debug("Press back button.")
        self.deviceV2.press("back")
        random_sleep(modulable=modulable)

    def start_screenrecord(self, output="debug_0000.mp4", fps=20):
        import imageio

        def _run_MOD(self):
            from collections import deque
            from time import sleep

            import numpy as np

            try:
                frames = deque(maxlen=self._fps * 30)
                if hasattr(self._d, "path2url"):
                    pipelines = [self._pipe_limit, self._pipe_convert, self._pipe_resize]
                    _iter = self._iter_minicap()
                    for p in pipelines:
                        _iter = p(_iter)
                    for im in _iter:
                        frames.append(im)
                else:
                    interval = 1 / max(self._fps, 1)
                    while not self._stop_event.is_set():
                        frames.append(np.asarray(self._d.screenshot()))
                        sleep(interval)

                if self.crash:
                    with imageio.get_writer(self._filename, fps=self._fps) as wr:
                        for frame in frames:
                            wr.append_data(frame)
            except Exception as e:
                logger.warning(f"Screen recording failed: {e}")
            finally:
                self._done_event.set()

        def stop_MOD(self, crash=True):
            """
            stop record and finish write video
            Returns:
                bool: whether video is recorded.
            """
            if self._running:
                self.crash = crash
                self._stop_event.set()
                ret = self._done_event.wait(30.0)

                # reset
                self._stop_event.clear()
                self._done_event.clear()
                self._running = False
                return ret

        from uiautomator2 import screenrecord as _sr

        _sr.Screenrecord._run = _run_MOD
        _sr.Screenrecord.stop = stop_MOD
        mp4_files = [f for f in listdir(getcwd()) if f.endswith(".mp4")]
        if mp4_files:
            last_mp4 = mp4_files[-1]
            debug_number = "{0:0=4d}".format(int(last_mp4[-8:-4]) + 1)
            output = f"debug_{debug_number}.mp4"
        self.deviceV2.screenrecord(output, fps)
        logger.warning("Screen recording has been started.")

    def stop_screenrecord(self, crash=True):
        if self.deviceV2.screenrecord.stop(crash=crash):
            logger.warning("Screen recorder has been stopped successfully!")

    def take_screenshot(self, format: str = "pillow", path: Optional[str] = None):
        """Dual-engine screenshot capture pipeline.
        1. Attempts uiautomator2 screenshot (pillow or raw format).
        2. Validates image buffer (>= 500 bytes with PNG/JPEG magic headers).
        3. If uiautomator2 screencap is corrupted or returns error output (such as
           b'screencap: exit status 1\\n' on Android 15/16 emulators), transparently
           falls back to high-speed `adb exec-out screencap -p`.
        """
        import io
        from PIL import Image

        raw_bytes = None
        pillow_img = None

        # Try uiautomator2 first
        try:
            if format == "raw":
                res = self.deviceV2.screenshot(format="raw")
                if isinstance(res, (bytes, bytearray)) and (res.startswith(b"\x89PNG") or res.startswith(b"\xff\xd8\xff")):
                    raw_bytes = bytes(res)
                else:
                    logger.debug(f"u2 raw screencap invalid ({len(res) if res else 0} bytes). Falling back to ADB exec-out...")
            else:
                img = self.deviceV2.screenshot()
                if img is not None and hasattr(img, "size") and img.size[0] > 0 and img.size[1] > 0:
                    pillow_img = img
                else:
                    logger.debug("u2 pillow screencap returned None or 0-size image. Falling back to ADB exec-out...")
        except Exception as e:
            logger.debug(f"u2 screenshot attempt raised: {e}. Falling back to ADB exec-out...")

        # If u2 failed, fallback to direct ADB exec-out screencap -p
        if raw_bytes is None and pillow_img is None:
            try:
                cmd = ["adb"]
                serial = getattr(self, "device_id", None)
                if not serial and hasattr(self.deviceV2, "serial") and self.deviceV2.serial:
                    serial = str(self.deviceV2.serial)
                if serial:
                    cmd.extend(["-s", str(serial)])
                cmd.extend(["exec-out", "screencap", "-p"])
                proc = run(cmd, stdout=PIPE, stderr=PIPE, shell=False, timeout=10)
                if proc.stdout and (proc.stdout.startswith(b"\x89PNG") or proc.stdout.startswith(b"\xff\xd8\xff")):
                    raw_bytes = proc.stdout
                    logger.debug(f"ADB exec-out screencap fallback succeeded ({len(raw_bytes)} bytes).")
                else:
                    logger.error(f"ADB exec-out screencap produced invalid payload ({len(proc.stdout) if proc.stdout else 0} bytes). Stderr: {proc.stderr}")
            except Exception as adb_err:
                logger.error(f"ADB exec-out screencap fallback failed: {adb_err}")

        # Materialize requested output format
        if format == "raw":
            if raw_bytes is None:
                if pillow_img is not None:
                    buf = io.BytesIO()
                    pillow_img.save(buf, format="PNG")
                    raw_bytes = buf.getvalue()
                else:
                    return b""
            if path:
                with open(path, "wb") as f:
                    f.write(raw_bytes)
            return raw_bytes
        else:
            if pillow_img is None:
                if raw_bytes is not None:
                    try:
                        pillow_img = Image.open(io.BytesIO(raw_bytes))
                    except Exception as pil_err:
                        logger.error(f"Failed decoding screenshot raw bytes to Pillow Image: {pil_err}")
                        return None
                else:
                    return None
            if path:
                pillow_img.save(path)
            return pillow_img

    def screenshot(self, path=None):
        return self.take_screenshot(format="pillow", path=path)

    def dump_hierarchy(self, path):
        xml_dump = self.deviceV2.dump_hierarchy()
        with open(path, "w", encoding="utf-8") as outfile:
            outfile.write(xml_dump)

    def press_power(self):
        self.deviceV2.press("power")
        sleep(2)

    def is_screen_locked(self):
        try:
            cmd = ["adb"]
            if hasattr(self.deviceV2, "serial") and self.deviceV2.serial:
                cmd.extend(["-s", str(self.deviceV2.serial)])
            cmd.extend(["shell", "dumpsys", "window"])
            data = run(
                cmd,
                encoding="utf-8",
                stdout=PIPE,
                stderr=PIPE,
                shell=False,
                timeout=10,
            )
            if data and data.stdout:
                # Modern Android (SDK 28+ / Android 9-15+): isKeyguardShowing=(true|false)
                keyguard_match = search(r"isKeyguardShowing=(true|false)", data.stdout)
                if keyguard_match:
                    return keyguard_match.group(1).lower() == "true"
                # Legacy Android: mDreamingLockscreen=(true|false)
                flag = search(r"mDreamingLockscreen=(true|false)", data.stdout)
                if flag:
                    return flag.group(1).lower() == "true"
                # Fallback check for active dream lockscreen
                showing_dream = search(r"mShowingDream=(true|false)", data.stdout)
                if showing_dream and showing_dream.group(1).lower() == "true":
                    return True
                return False
            else:
                logger.debug("dumpsys window returned nothing.")
                return None
        except Exception as ex:
            logger.debug(f"is_screen_locked error: {ex}")
            return None

    def _is_keyboard_show(self):
        try:
            cmd = ["adb"]
            if hasattr(self.deviceV2, "serial") and self.deviceV2.serial:
                cmd.extend(["-s", str(self.deviceV2.serial)])
            cmd.extend(["shell", "dumpsys", "input_method"])
            data = run(
                cmd,
                encoding="utf-8",
                stdout=PIPE,
                stderr=PIPE,
                shell=False,
                timeout=10,
            )
            if data and data.stdout:
                flag = search("mInputShown=(true|false)", data.stdout)
                return flag is not None and flag.group(1) == "true"
            else:
                logger.debug("dumpsys input_method returned nothing.")
                return None
        except Exception as ex:
            logger.debug(f"_is_keyboard_show error: {ex}")
            return None

    def is_alive(self):
        try:
            self.deviceV2.info
            return True
        except Exception:
            return False

    def wake_up(self):
        """Make sure agent is alive or bring it back up before starting."""
        if self.deviceV2 is not None:
            attempts = 0
            while not self.is_alive() and attempts < 5:
                self.get_info()
                attempts += 1

    def unlock(self):
        """Dismiss keyguard and unlock screen using native ADB keyguard dismissal, keyevents, and fallback swipes."""
        serial = getattr(self.deviceV2, "serial", None)
        adb_prefix = ["adb"]
        if serial:
            adb_prefix.extend(["-s", str(serial)])

        # Step 1: Direct native ADB wm dismiss-keyguard (instant and works across Android 8-15+)
        try:
            run(adb_prefix + ["shell", "wm", "dismiss-keyguard"], shell=False, timeout=5, stdout=PIPE, stderr=PIPE)
            sleep(0.5)
        except Exception as e:
            logger.debug(f"wm dismiss-keyguard error: {e}")

        # Step 2: Wakeup + Keycode MENU (82) / WAKEUP (224)
        try:
            run(adb_prefix + ["shell", "input", "keyevent", "224"], shell=False, timeout=3, stdout=PIPE, stderr=PIPE)
            run(adb_prefix + ["shell", "input", "keyevent", "82"], shell=False, timeout=3, stdout=PIPE, stderr=PIPE)
            sleep(0.5)
        except Exception as e:
            logger.debug(f"keyevent unlock error: {e}")

        locked = self.is_screen_locked()
        logger.debug(f"Screen locked after native unlock: {locked}")
        if locked is False:
            return

        # Step 3: Swipe UP gesture fallback
        self.swipe(Direction.UP, 0.8)
        sleep(1)
        locked = self.is_screen_locked()
        logger.debug(f"Screen locked after swipe UP: {locked}")
        if locked is False:
            return

        # Step 4: Swipe RIGHT gesture fallback
        self.swipe(Direction.RIGHT, 0.8)
        sleep(1)
        logger.debug(f"Screen locked after swipe RIGHT: {self.is_screen_locked()}")

    def screen_off(self):
        self.deviceV2.screen_off()

    def get_orientation(self):
        try:
            return self.deviceV2._get_orientation()
        except Exception as e:
            raise DeviceFacade.JsonRpcError(e)

    def window_size(self):
        """return (width, height)"""
        try:
            self.deviceV2.window_size()
        except Exception as e:
            raise DeviceFacade.JsonRpcError(e)

    def swipe(self, direction: Direction, scale=0.5):
        """Swipe finger in the `direction`.
        Scale is the sliding distance. Default to 50% of the screen width
        """
        from InstaAddict.core.session_state import SessionState
        from InstaAddict.core.telemetry import PerformanceTracker

        tracker = PerformanceTracker.get_instance()
        session = SessionState.get_active()
        effective_scale = min(scale * tracker.adaptive_scale_factor, 0.85)

        logger.debug(f"Swipe {direction.name}, scale={scale} (effective={effective_scale:.2f})")

        try:
            with tracker.measure("motion", "swipe"):
                info = self.get_info()
                w, h = info["displayWidth"], info["displayHeight"]
                cx, cy = w / 2, h / 2

                sx, sy, ex, ey = cx, cy, cx, cy
                if direction == Direction.UP:
                    sy = min(h * 0.9, cy + (h * effective_scale / 2))
                    ey = max(h * 0.1, cy - (h * effective_scale / 2))
                elif direction == Direction.DOWN:
                    sy = max(h * 0.1, cy - (h * effective_scale / 2))
                    ey = min(h * 0.9, cy + (h * effective_scale / 2))
                elif direction == Direction.LEFT:
                    sx = min(w * 0.9, cx + (w * effective_scale / 2))
                    ex = max(w * 0.1, cx - (w * effective_scale / 2))
                elif direction == Direction.RIGHT:
                    sx = max(w * 0.1, cx - (w * effective_scale / 2))
                    ex = min(w * 0.9, cx + (w * effective_scale / 2))

                logger.debug(f"UIA2 Swipe from ({sx},{sy}) to ({ex},{ey}) over 200ms.")
                self.deviceV2.swipe(sx, sy, ex, ey, 0.20)
                DeviceFacade.sleep_mode(SleepTime.TINY)

            tracker.record_swipe_motion(displaced=True)
            if session:
                session.increment_swipes()
        except Exception as e:
            tracker.record_swipe_motion(displaced=False)
            if session:
                session.increment_swipes()
                session.increment_zero_displacement()
            raise DeviceFacade.JsonRpcError(e) from e

    def swipe_points(self, sx, sy, ex, ey, random_x=True, random_y=True):
        from InstaAddict.core.session_state import SessionState
        from InstaAddict.core.telemetry import PerformanceTracker

        tracker = PerformanceTracker.get_instance()
        session = SessionState.get_active()

        if random_x:
            sx = int(sx * uniform(0.85, 1.15))
            ex = int(ex * uniform(0.85, 1.15))
        if random_y:
            ey = int(ey * uniform(0.98, 1.02))
        sy = int(sy)
        try:
            with tracker.measure("motion", "swipe"):
                logger.debug(f"UIA2 Swipe from ({sx},{sy}) to ({ex},{ey}) over 200ms.")
                self.deviceV2.swipe(sx, sy, ex, ey, 0.20)
                DeviceFacade.sleep_mode(SleepTime.TINY)

            tracker.record_swipe_motion(displaced=True)
            if session:
                session.increment_swipes()
        except Exception as e:
            tracker.record_swipe_motion(displaced=False)
            if session:
                session.increment_swipes()
                session.increment_zero_displacement()
            raise DeviceFacade.JsonRpcError(e) from e

    def _get_info_via_adb(self) -> dict:
        """Fast direct ADB fallback to query device metrics when UiAutomator RPC service is disconnected or slow."""
        import subprocess

        info = {
            "currentPackageName": "com.instagram.android",
            "displayHeight": 1920,
            "displayRotation": 0,
            "displaySizeDpX": 411,
            "displaySizeDpY": 731,
            "displayWidth": 1080,
            "productName": "Android Device",
            "screenOn": True,
            "sdkInt": 28,
            "naturalOrientation": True,
        }
        cmd_prefix = ["adb"]
        device_id = getattr(self, "device_id", None)
        if device_id:
            cmd_prefix.extend(["-s", str(device_id)])

        try:
            # 1. Product Name & SDK
            res_prod = subprocess.run(
                cmd_prefix + ["shell", "getprop", "ro.product.model"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res_prod.returncode == 0 and res_prod.stdout.strip():
                info["productName"] = res_prod.stdout.strip()
            else:
                res_name = subprocess.run(
                    cmd_prefix + ["shell", "getprop", "ro.product.name"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if res_name.returncode == 0 and res_name.stdout.strip():
                    info["productName"] = res_name.stdout.strip()

            res_sdk = subprocess.run(
                cmd_prefix + ["shell", "getprop", "ro.build.version.sdk"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res_sdk.returncode == 0 and res_sdk.stdout.strip().isdigit():
                info["sdkInt"] = int(res_sdk.stdout.strip())

            # 2. Display Width & Height via wm size
            res_wm = subprocess.run(
                cmd_prefix + ["shell", "wm", "size"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res_wm.returncode == 0 and res_wm.stdout:
                m_size = re.findall(r"(\d+)x(\d+)", res_wm.stdout)
                if m_size:
                    info["displayWidth"] = int(m_size[-1][0])
                    info["displayHeight"] = int(m_size[-1][1])

            # 3. Density for DP calculation
            res_density = subprocess.run(
                cmd_prefix + ["shell", "wm", "density"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            density = 420
            if res_density.returncode == 0 and res_density.stdout:
                m_den = re.findall(r"\d+", res_density.stdout)
                if m_den:
                    density = int(m_den[-1])
            info["displaySizeDpX"] = int(info["displayWidth"] * 160 / max(density, 1))
            info["displaySizeDpY"] = int(info["displayHeight"] * 160 / max(density, 1))

            # 4. Screen On via dumpsys power
            res_power = subprocess.run(
                cmd_prefix + ["shell", "dumpsys", "power"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res_power.returncode == 0 and res_power.stdout:
                p_out = res_power.stdout
                info["screenOn"] = (
                    "mWakefulness=Awake" in p_out or "Display Power: state=ON" in p_out
                )
        except Exception as e:
            logger.debug(f"_get_info_via_adb fallback error: {e}")

        return info

    def is_screen_on(self) -> bool:
        """Check if device screen is on with fast ADB fallback."""
        try:
            return bool(self.deviceV2.info.get("screenOn", True))
        except Exception:
            return bool(self._get_info_via_adb().get("screenOn", True))

    def get_info(self, fallback_to_adb: bool = False):
        import time
        from InstaAddict.core.telemetry import PerformanceTracker

        tracker = PerformanceTracker.get_instance()
        last_exc = None
        for attempt in range(5):
            try:
                with tracker.measure("rpc", "get_info"):
                    return self.deviceV2.info
            except Exception as e:
                last_exc = e
                logger.debug(
                    f"deviceV2.info attempt {attempt + 1}/5 failed: {e}. Attempting uiautomator recovery..."
                )
                try:
                    self.deviceV2.reset_uiautomator(str(e))
                except Exception as r_err:
                    logger.debug(
                        f"reset_uiautomator attempt {attempt + 1} raised: {r_err}"
                    )
                time.sleep(1)

        if fallback_to_adb:
            logger.warning(
                f"RPC get_info failed ({last_exc}). Falling back to fast direct ADB device inspection..."
            )
            tracker.record_metric("rpc", "get_info_fallback", 1.0, error=True)
            return self._get_info_via_adb()

        raise DeviceFacade.JsonRpcError(last_exc) from last_exc

    @staticmethod
    def sleep_mode(mode):
        mode = SleepTime.DEFAULT if mode is None else mode
        if mode == SleepTime.DEFAULT:
            random_sleep()
        elif mode == SleepTime.TINY:
            random_sleep(0, 1)
        elif mode == SleepTime.SHORT:
            random_sleep(1, 2)
        elif mode == SleepTime.ZERO:
            pass

    class View:
        deviceV2 = None  # uiautomator2
        viewV2 = None  # uiautomator2

        def __init__(self, view, device):
            self.viewV2 = view
            self.deviceV2 = device

        def __iter__(self):
            children = []
            try:
                iterator = self.viewV2.__iter__()
                while True:
                    try:
                        item = next(iterator)
                    except StopIteration:
                        break
                    children.append(DeviceFacade.View(view=item, device=self.deviceV2))
                return iter(children)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e) from e

        def ui_info(self):
            try:
                return self.viewV2.info
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e) from e

        def get_desc(self):
            try:
                return self.viewV2.info["contentDescription"]
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def child(self, *args, **kwargs):
            try:
                view = self.viewV2.child(*args, **kwargs)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)
            return DeviceFacade.View(view=view, device=self.deviceV2)

        def sibling(self, *args, **kwargs):
            try:
                view = self.viewV2.sibling(*args, **kwargs)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)
            return DeviceFacade.View(view=view, device=self.deviceV2)

        def left(self, *args, **kwargs):
            try:
                view = self.viewV2.left(*args, **kwargs)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)
            return DeviceFacade.View(view=view, device=self.deviceV2)

        def right(self, *args, **kwargs):
            try:
                view = self.viewV2.right(*args, **kwargs)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)
            return DeviceFacade.View(view=view, device=self.deviceV2)

        def up(self, *args, **kwargs):
            try:
                view = self.viewV2.up(*args, **kwargs)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)
            return DeviceFacade.View(view=view, device=self.deviceV2)

        def down(self, *args, **kwargs):
            try:
                view = self.viewV2.down(*args, **kwargs)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)
            return DeviceFacade.View(view=view, device=self.deviceV2)

        def click_gone(self, maxretry=3, interval=1.0):
            try:
                self.viewV2.click_gone(maxretry, interval)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def click(self, mode=None, sleep=None, coord=None, crash_report_if_fails=True):
            if coord is None:
                coord = []
            mode = Location.WHOLE if mode is None else mode
            if mode == Location.WHOLE:
                x_offset = uniform(0.15, 0.85)
                y_offset = uniform(0.15, 0.85)

            elif mode == Location.LEFT:
                x_offset = uniform(0.15, 0.4)
                y_offset = uniform(0.15, 0.85)

            elif mode == Location.LEFTEDGE:
                x_offset = uniform(0.1, 0.2)
                y_offset = uniform(0.40, 0.60)

            elif mode == Location.CENTER:
                x_offset = uniform(0.4, 0.6)
                y_offset = uniform(0.15, 0.85)

            elif mode == Location.RIGHT:
                x_offset = uniform(0.6, 0.85)
                y_offset = uniform(0.15, 0.85)

            elif mode == Location.RIGHTEDGE:
                x_offset = uniform(0.8, 0.9)
                y_offset = uniform(0.40, 0.60)

            elif mode == Location.BOTTOMRIGHT:
                x_offset = uniform(0.8, 0.9)
                y_offset = uniform(0.8, 0.9)

            elif mode == Location.TOPLEFT:
                x_offset = uniform(0.12, 0.18)
                y_offset = uniform(0.05, 0.25)
            elif mode == Location.CUSTOM:
                try:
                    logger.debug(f"Single click ({coord[0]},{coord[1]})")
                    self.deviceV2.click(coord[0], coord[1])
                    DeviceFacade.sleep_mode(sleep)
                    return
                except Exception as e:
                    if crash_report_if_fails:
                        raise DeviceFacade.JsonRpcError(e)
                    else:
                        logger.debug("Trying to press on a obj which is gone.")

            else:
                x_offset = 0.5
                y_offset = 0.5

            try:
                visible_bounds = self.get_bounds()
                x_abs = int(
                    visible_bounds["left"]
                    + (visible_bounds["right"] - visible_bounds["left"]) * x_offset
                )
                y_abs = int(
                    visible_bounds["top"]
                    + (visible_bounds["bottom"] - visible_bounds["top"]) * y_offset
                )

                logger.debug(
                    f"Single click in ({x_abs},{y_abs}). Surface: ({visible_bounds['left']}-{visible_bounds['right']},{visible_bounds['top']}-{visible_bounds['bottom']})"
                )
                self.viewV2.click(
                    self.get_ui_timeout(Timeout.LONG),
                    offset=(x_offset, y_offset),
                )
                DeviceFacade.sleep_mode(sleep)

            except Exception as e:
                if crash_report_if_fails:
                    raise DeviceFacade.JsonRpcError(e)
                else:
                    logger.debug("Trying to press on a obj which is gone.")

        def click_retry(self, mode=None, sleep=None, coord=None, maxretry=2):
            """return True if successfully open the element, else False"""
            if coord is None:
                coord = []
            self.click(mode, sleep, coord)

            while maxretry > 0:
                # we wait a little more before try again
                random_sleep(2, 4, modulable=False)
                if not self.exists():
                    return True
                logger.debug("UI element didn't open! Try again..")
                self.click(mode, sleep, coord)
                maxretry -= 1
            if not self.exists():
                return True
            logger.warning("Failed to open the UI element!")
            return False

        def double_click(self, padding=0.3, obj_over=0):
            """Double click randomly in the selected view using padding
            padding: % of how far from the borders we want the double
                    click to happen.
            """
            visible_bounds = self.get_bounds()
            horizontal_len = visible_bounds["right"] - visible_bounds["left"]
            vertical_len = visible_bounds["bottom"] - max(
                visible_bounds["top"], obj_over
            )
            horizontal_padding = int(padding * horizontal_len)
            vertical_padding = int(padding * vertical_len)
            random_x = int(
                uniform(
                    visible_bounds["left"] + horizontal_padding,
                    visible_bounds["right"] - horizontal_padding,
                )
            )
            random_y = int(
                uniform(
                    visible_bounds["top"] + vertical_padding,
                    visible_bounds["bottom"] - vertical_padding,
                )
            )

            time_between_clicks = uniform(0.050, 0.140)

            try:
                logger.debug(
                    f"Double click in ({random_x},{random_y}) with t={int(time_between_clicks*1000)}ms. Surface: ({visible_bounds['left']}-{visible_bounds['right']},{visible_bounds['top']}-{visible_bounds['bottom']})."
                )
                self.deviceV2.double_click(
                    random_x, random_y, duration=time_between_clicks
                )
                DeviceFacade.sleep_mode(SleepTime.DEFAULT)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def scroll(self, direction):
            try:
                if direction == Direction.UP:
                    self.viewV2.scroll.toBeginning(max_swipes=1)
                else:
                    self.viewV2.scroll.toEnd(max_swipes=1)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def fling(self, direction):
            try:
                if direction == Direction.UP:
                    self.viewV2.fling.toBeginning(max_swipes=5)
                else:
                    self.viewV2.fling.toEnd(max_swipes=5)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def exists(
            self,
            ui_timeout=None,
            ignore_bug: bool = False,
            timeout=None,
            **kwargs,
        ) -> bool:
            try:
                if ui_timeout is None and timeout is not None:
                    ui_timeout = timeout
                # Currently, the methods left, right, up and down from
                # uiautomator2 return None when a Selector does not exist.
                # All other selectors return an UiObject with exists() == False.
                # We will open a ticket to uiautomator2 to fix this inconsistency.
                if self.viewV2 is None:
                    return False
                exists: bool = self.viewV2.exists(self.get_ui_timeout(ui_timeout))
                if ignore_bug and not exists:
                    try:
                        if hasattr(self.viewV2, "count") and self.viewV2.count >= 1:
                            logger.debug(
                                f"UIA2 BUG: exists return False, but there is/are {self.viewV2.count} element(s)!"
                            )
                            return "BUG!"
                    except Exception:
                        pass
                return exists
            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ("gateway", "jsonrpc", "closed", "connection", "instrument", "deadobject", "nullpointer", "time used")):
                    logger.warning(
                        f"exists() encountered RPC/daemon error ({e}). Attempting self-healing resurrection..."
                    )
                    try:
                        if hasattr(self.deviceV2, "shell"):
                            runner = "androidx.test.runner.AndroidJUnitRunner"
                            try:
                                res = self.deviceV2.shell(["pm", "list", "instrumentation"]).output
                                if "androidx.test.runner.AndroidJUnitRunner" not in res and "android.support.test.runner.AndroidJUnitRunner" in res:
                                    runner = "android.support.test.runner.AndroidJUnitRunner"
                            except Exception:
                                pass
                            try:
                                self.deviceV2.shell(["/data/local/tmp/atx-agent", "server", "--stop"])
                                self.deviceV2.shell(["/data/local/tmp/atx-agent", "server", "--nouia", "-d", "--addr", "127.0.0.1:7912"])
                            except Exception:
                                pass
                            self.deviceV2.shell(["pkill", "-f", "com.github.uiautomator"])
                            self.deviceV2.shell(
                                f"nohup am instrument -w -r -e debug false -e class com.github.uiautomator.stub.Stub com.github.uiautomator.test/{runner} > /dev/null 2>&1 &"
                            )
                            sleep(2)
                            return bool(self.viewV2.exists(self.get_ui_timeout(ui_timeout)))
                    except Exception as retry_err:
                        logger.debug(f"Self-healing resurrection retry in exists() failed: {retry_err}")
                raise DeviceFacade.JsonRpcError(e)

        def count_items(self) -> int:
            try:
                return self.viewV2.count
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def wait(self, ui_timeout=Timeout.MEDIUM):
            try:
                return self.viewV2.wait(timeout=self.get_ui_timeout(ui_timeout))
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def wait_gone(self, ui_timeout=None):
            try:
                return self.viewV2.wait_gone(timeout=self.get_ui_timeout(ui_timeout))
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def is_above_this(self, obj2) -> Optional[bool]:
            obj1 = self.viewV2
            obj2 = obj2.viewV2
            try:
                if obj1.exists() and obj2.exists():
                    return obj1.info["bounds"]["top"] < obj2.info["bounds"]["top"]
                else:
                    return None
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def get_bounds(self) -> dict:
            try:
                return self.viewV2.info["bounds"]
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def get_height(self) -> int:
            bounds = self.get_bounds()
            return bounds["bottom"] - bounds["top"]

        def get_width(self):
            bounds = self.get_bounds()
            return bounds["right"] - bounds["left"]

        def get_property(self, prop: str):
            try:
                return self.viewV2.info[prop]
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def is_scrollable(self):
            try:
                if self.viewV2.exists():
                    return self.viewV2.info["scrollable"]
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        @staticmethod
        def get_ui_timeout(ui_timeout: Timeout) -> int:
            ui_timeout = Timeout.ZERO if ui_timeout is None else ui_timeout
            if ui_timeout == Timeout.ZERO:
                ui_timeout = 0
            elif ui_timeout == Timeout.TINY:
                ui_timeout = 1
            elif ui_timeout == Timeout.SHORT:
                ui_timeout = 3
            elif ui_timeout == Timeout.MEDIUM:
                ui_timeout = 5
            elif ui_timeout == Timeout.LONG:
                ui_timeout = 8
            return ui_timeout

        def get_text(self, error=True, index=None):
            try:
                text = (
                    self.viewV2.info["text"]
                    if index is None
                    else self.viewV2[index].info["text"]
                )
                if text is not None:
                    return text
            except Exception as e:
                if error:
                    raise DeviceFacade.JsonRpcError(e)
                else:
                    return ""
            logger.debug("Object exists but doesn't contain any text.")
            return ""

        def get_selected(self) -> bool:
            try:
                if self.viewV2.exists():
                    info = self.viewV2.info
                    logger.debug(f"DEBUG like button info {info}")
                    return info["selected"]
                logger.debug(
                    "Object has disappeared! Probably too short video which has been liked!"
                )
                return True
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

        def set_text(self, text: str, mode: Mode = Mode.TYPE) -> None:
            punct_list = string.punctuation
            try:
                if mode == Mode.PASTE:
                    self.viewV2.set_text(text)
                else:
                    try:
                        self.click(sleep=SleepTime.SHORT)
                        self.deviceV2.clear_text()
                        random_sleep(0.3, 1, modulable=False)
                        start = datetime.now()
                        sentences = text.splitlines()
                        for j, sentence in enumerate(sentences, start=1):
                            word_list = sentence.split()
                            n_words = len(word_list)
                            for n, word in enumerate(word_list, start=1):
                                i = 0
                                n_single_letters = randint(1, 3)
                                clusters = _split_into_grapheme_clusters(word)
                                n_clusters = len(clusters)
                                for idx, cluster in enumerate(clusters):
                                    if i < n_single_letters:
                                        self.deviceV2.send_keys(cluster, clear=False)
                                        i += 1
                                    else:
                                        if clusters[-1] in punct_list and idx < n_clusters - 1:
                                            self.deviceV2.send_keys("".join(clusters[i:-1]), clear=False)
                                            self.deviceV2.send_keys(clusters[-1], clear=False)
                                        else:
                                            self.deviceV2.send_keys("".join(clusters[i:]), clear=False)
                                        break
                                if n < n_words:
                                    self.deviceV2.send_keys(" ", clear=False)
                            if j < len(sentences):
                                self.deviceV2.send_keys("\n")

                        typed_text = self.get_text(error=False)
                        # Instagram strips spaces out of hashtag searches, so we don't need to throw an error if the stripped version matches
                        if typed_text.replace(" ", "") != text.replace(" ", ""):
                            logger.debug(
                                f"Typed text '{typed_text}' does not match expected '{text}', falling back to direct set_text."
                            )
                            self.viewV2.set_text(text)
                        else:
                            logger.debug(
                                f"Text typed in: {(datetime.now()-start).total_seconds():.2f}s"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Typing simulation failed ({e}), falling back to direct set_text."
                        )
                        self.viewV2.set_text(text)
                DeviceFacade.sleep_mode(SleepTime.SHORT)
            except Exception as e:
                raise DeviceFacade.JsonRpcError(e)

    class JsonRpcError(Exception):
        pass

    class AppHasCrashed(Exception):
        pass
