import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from math import nan
from os import getcwd, rename, walk
from pathlib import Path
from random import randint, shuffle, uniform
from subprocess import PIPE
from time import sleep
from typing import Optional, Tuple, Union
from urllib.parse import urlparse

import emoji
import requests
import urllib3
from colorama import Fore, Style
from packaging.version import parse as parse_version

from InstaAddict import __file__, __version__
from InstaAddict.core.config import Config
from InstaAddict.core.log import get_log_file_config
from InstaAddict.core.report import print_full_report
from InstaAddict.core.resources import ResourceID as resources
from InstaAddict.core.storage import ACCOUNTS

http = urllib3.PoolManager()
logger = logging.getLogger(__name__)

args = None
configs = None
app_id = None
ResourceID = None


def load_config(config: Config):
    global app_id
    global args
    global configs
    global ResourceID
    app_id = config.args.app_id
    args = config.args
    configs = config
    ResourceID = resources(app_id)


def update_available():
    try:
        response = requests.get(
            "https://pypi.python.org/pypi/InstaAddict-AI/json", timeout=5
        )
        if response.status_code == 404:
            logger.debug("Package 'InstaAddict-AI' not yet indexed on PyPI (running from source).")
            return False, "source"
        if response.ok:
            data = response.json()
            latest_version = data.get("info", {}).get("version")
            if latest_version:
                current_version = parse_version(__version__)
                latest_version_parsed = parse_version(latest_version)
                return current_version < latest_version_parsed, latest_version
    except Exception as e:
        logger.debug(f"Update check failed or timed out: {e}")
    return False, None


def check_if_updated(crash=False):
    if not crash:
        logger.info("Checking for updates...")
    new_update, latest_version = update_available()
    if new_update:
        logger.warning("NEW VERSION FOUND!")
        logger.warning(
            f"Version {latest_version} has been released! Please update so that you can get all the latest features and bugfixes. Changelog here -> https://github.com/ssucipto/instaaddict/blob/master/CHANGELOG.md"
        )
        logger.warning("HOW TO UPDATE:")
        logger.warning("If you installed with pip: pip3 install InstaAddict-AI -U")
        logger.warning("If you installed with git: git pull")
        sleep(5)
    elif latest_version == "source":
        if not crash:
            logger.debug("Running development build from source repository.")
    elif latest_version is None:
        if not crash:
            logger.debug("Update check skipped (unable to reach PyPI).")
    elif not crash:
        logger.info("Bot is updated.", extra={"color": f"{Style.BRIGHT}"})

    if not crash:
        logger.info(
            f"InstaAddict-AI v.{__version__}",
            extra={"color": f"{Style.BRIGHT}{Fore.MAGENTA}"},
        )
        logger.info(
            "Follow & Support: GitHub: https://github.com/ssucipto/instaaddict | Open an issue for bugs or feature requests",
            extra={"color": f"{Style.BRIGHT}{Fore.CYAN}"},
        )


def ask_for_a_donation():
    logger.info(
        "InstaAddict-AI is free and open source. If you find it useful, consider starring the repo: https://github.com/ssucipto/instaaddict",
        extra={"color": f"{Style.BRIGHT}{Fore.MAGENTA}"},
    )


def move_usernames_to_accounts():
    Path(ACCOUNTS).mkdir(parents=True, exist_ok=True)
    ls = next(walk("."))[1]
    ignored_dir = [
        "__pycache__",
        "build",
        "accounts",
        "InstaAddict",
        "InstaAddict-AI",
        "config-examples",
        ".git",
        ".venv",
        "dist",
        ".vscode",
        ".github",
        "crashes",
        "gramaddict.egg-info",
        "logs",
        "res",
        "test",
        "dump",
    ]
    for n in ignored_dir:
        try:
            ls.remove(n)
        except ValueError:
            pass

    for dir in ls:
        try:
            if dir != dir.strip():
                rename(f"{dir}", dir.strip())
            shutil.move(dir.strip(), ACCOUNTS)
        except Exception as e:
            logger.error(
                f"Folder {dir.strip()} already exists! Won't overwrite it, please check which is the correct one and delete the other! Exception: {e}"
            )
            sleep(3)
    if len(ls) > 0:
        logger.warning(
            f"Username folders {', '.join(ls)} have been moved to main folder 'accounts'. Remember that your config file must point there! Example: '--config accounts/yourusername/config.yml'"
        )


def config_examples():
    if getcwd() == __file__[:-23]:
        logger.debug("Installed via git, config-examples is in the local folder.")
    else:
        logger.debug("Installed via pip.")
        logger.info(
            "Do you want to update/create your config-examples folder in local? Do the following: \n\t\t\t\tpip3 install --user gitdir (only the first time)\n\t\t\t\tpython3 -m gitdir https://github.com/ssucipto/instaaddict/tree/master/config-examples (python on Windows)",
            extra={"color": Fore.GREEN},
        )
        sleep(3)


def check_adb_connection():
    is_device_id_provided = configs.device_id is not None
    # sometimes it needs two requests to wake up...
    stream = os.popen("adb devices")
    stream.close()
    stream = os.popen("adb devices")
    output = stream.read()
    devices_count = len(re.findall("device\n", output))
    stream.close()

    is_ok = True
    message = "That's ok."
    if devices_count == 0:
        is_ok = False
        message = "Cannot proceed."
    elif devices_count > 1 and not is_device_id_provided:
        is_ok = False
        message = "Set a device name in your config.yml"

    if is_ok:
        logger.debug(f"Connected devices via adb: {devices_count}. {message}")
    else:
        logger.error(f"Connected devices via adb: {devices_count}. {message}")

    return is_ok


def get_instagram_version():
    stream = os.popen(
        f"adb{'' if configs.device_id is None else ' -s ' + configs.device_id} shell dumpsys package {app_id}"
    )
    output = stream.read()
    version_match = re.findall("versionName=(\\S+)", output)
    version = version_match[0] if len(version_match) == 1 else "not found"
    stream.close()
    return version


def open_instagram_with_url(url) -> bool:
    logger.info(f"Open Instagram app with url: {url}")
    cmd = ["adb"]
    if configs.device_id is not None:
        cmd.extend(["-s", str(configs.device_id)])
    cmd.extend(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", str(url)])
    try:
        cmd_res = subprocess.run(
            cmd, stdout=PIPE, stderr=PIPE, shell=False, encoding="utf8", timeout=15
        )
        err = cmd_res.stderr.strip()
    except Exception as ex:
        logger.warning(f"Error executing am start: {ex}")
        return False
    random_sleep()
    if err:
        logger.debug(err)
        return False
    return True


def kill_app(device, app_id):
    device.deviceV2.app_stop(app_id)


def head_up_notifications(enabled: bool = False):
    """
    Enable or disable head-up-notifications
    """
    cmd = ["adb"]
    if configs is not None and getattr(configs, "device_id", None) is not None:
        cmd.extend(["-s", str(configs.device_id)])
    cmd.extend(["shell", "settings", "put", "global", "heads_up_notifications_enabled", "1" if enabled else "0"])
    try:
        return subprocess.run(cmd, stdout=PIPE, stderr=PIPE, shell=False, encoding="utf8", timeout=10)
    except Exception as ex:
        logger.debug(f"Failed to update heads_up_notifications: {ex}")
        return None


def check_screen_timeout():
    MIN_TIMEOUT = 5 * 6_000
    cmd = ["adb"]
    if configs is not None and getattr(configs, "device_id", None) is not None:
        cmd.extend(["-s", str(configs.device_id)])
    cmd.extend(["shell", "settings", "get", "system", "screen_off_timeout"])
    try:
        resp = subprocess.run(cmd, stdout=PIPE, stderr=PIPE, shell=False, encoding="utf8", timeout=10)
    except Exception as ex:
        logger.debug(f"Failed to get screen timeout: {ex}")
        return

    try:
        if int(resp.stdout.strip()) < MIN_TIMEOUT:
            logger.info(
                f"Setting timeout of the screen to {MIN_TIMEOUT/6_000:.0f} minutes."
            )
            set_cmd = ["adb"]
            if configs.device_id is not None:
                set_cmd.extend(["-s", str(configs.device_id)])
            set_cmd.extend(["shell", "settings", "put", "system", "screen_off_timeout", str(MIN_TIMEOUT)])
            subprocess.run(set_cmd, stdout=PIPE, stderr=PIPE, shell=False, encoding="utf8", timeout=10)
        else:
            logger.info("Screen timeout is fine!")
    except (ValueError, AttributeError):
        logger.info("Unable to get screen timeout!")
        logger.debug(resp.stdout if resp else "")


def open_instagram(device):
    nl = "\n"
    FastInputIME = "com.github.uiautomator/.FastInputIME"
    target_app = app_id
    if not target_app and configs and hasattr(configs, "app_id") and isinstance(configs.app_id, str):
        target_app = configs.app_id
    if not target_app and isinstance(getattr(device, "app_id", None), str):
        target_app = getattr(device, "app_id")
    if not target_app:
        target_app = "com.instagram.android"
    logger.info(f"Open Instagram app ({target_app}).")

    from InstaAddict.core.watchdog import StartupGrace

    with StartupGrace(f"Launching Instagram ({target_app})"):
        def call_ig():
            try:
                device.deviceV2.app_start(target_app, use_monkey=True)
                return None
            except Exception as exc:
                return exc

        try:
            from InstaAddict.core.watchdog import record_heartbeat
            record_heartbeat("startup", f"Calling Instagram app ({target_app})")
        except Exception:
            pass

        err = call_ig()
        if err:
            logger.error(f"Failed to call Instagram ({target_app}): {err}")
            return False
        else:
            logger.debug("Instagram called successfully.")

        max_tries = 6
        n = 0
        while True:
            try:
                from InstaAddict.core.watchdog import record_heartbeat
                record_heartbeat("startup", f"Waiting for Instagram to open ({n}/{max_tries})")
            except Exception:
                pass
            curr = {}
            if hasattr(device, "deviceV2") and hasattr(device.deviceV2, "app_current"):
                try:
                    raw_curr = device.deviceV2.app_current()
                    if isinstance(raw_curr, dict):
                        curr = raw_curr
                except Exception:
                    pass
            curr_pkg = curr.get("package", "")
            if curr_pkg == target_app:
                break

            # Check for interfering overlay apps (e.g. Google Play Store com.android.vending, browser, dialogs)
            system_pkgs = (
                "android",
                "com.android.systemui",
                "com.google.android.apps.nexuslauncher",
                "com.android.launcher3",
                "com.google.android.inputmethod.latin",
            )
            if curr_pkg and curr_pkg != target_app and curr_pkg not in system_pkgs:
                logger.warning(
                    f"Detected interfering non-target foreground package '{curr_pkg}'. Force-stopping package to clear overlay/dialog..."
                )
                try:
                    if hasattr(device, "shell"):
                        device.shell(f"am force-stop {curr_pkg}")
                    elif hasattr(device, "deviceV2") and hasattr(device.deviceV2, "app_stop"):
                        device.deviceV2.app_stop(curr_pkg)
                except Exception as stop_err:
                    logger.debug(f"Failed to force-stop interfering package {curr_pkg}: {stop_err}")
                try:
                    if hasattr(device, "back"):
                        device.back()
                except Exception:
                    pass
                try:
                    from InstaAddict.core.views import UniversalActions
                    UniversalActions.dismiss_dialog(device)
                except Exception:
                    pass

            if n >= max_tries:
                logger.critical(
                    f"Unable to open Instagram. Bot will stop. Current package name: {curr_pkg or 'unknown'} (Looking for {target_app})"
                )
                return False
            n += 1
            logger.info(f"Waiting for Instagram to open... 😴 ({n}/{max_tries})")
            if check_if_crash_popup_is_there(device):
                logger.info("Ig crashed, try to open it again...")
            call_ig()
            choose_cloned_app(device)
            random_sleep(3, 3, modulable=False)

        # Wait up to 8s for Instagram main UI to settle
        try:
            from InstaAddict.core.views import TabBarView, UniversalActions
            tab_bar = TabBarView(device)
            settle_timeout = 8
            start_settle = time.time()
            logger.debug("Waiting for Instagram main UI to settle...")
            while time.time() - start_settle < settle_timeout:
                try:
                    from InstaAddict.core.watchdog import record_heartbeat
                    record_heartbeat("startup", "Waiting for Instagram main UI to settle")
                except Exception:
                    pass
                if check_if_crash_popup_is_there(device):
                    logger.info("Instagram crashed during startup, trying to open again...")
                    call_ig()
                UniversalActions.dismiss_dialog(device)
                if tab_bar.is_tab_bar_visible():
                    logger.debug("Instagram main UI detected (tab bar visible).")
                    break
                random_sleep(0.8, 1.4, modulable=False)
        except Exception as e:
            logger.debug(f"UI settle check encountered: {e}")

        try:
            from InstaAddict.core.watchdog import record_heartbeat
            record_heartbeat("startup", "Instagram main UI ready")
        except Exception:
            pass

    logger.info("Ready for botting!🤫", extra={"color": f"{Style.BRIGHT}{Fore.GREEN}"})

    random_sleep()
    if configs and hasattr(configs, "args") and getattr(configs.args, "close_apps", False):
        logger.info("Close all the other apps, to avoid interferences...")
        device.deviceV2.app_stop_all(excludes=[app_id])
        random_sleep()
    logger.debug("Setting FastInputIME as default keyboard.")
    try:
        from InstaAddict.core.watchdog import record_heartbeat
        record_heartbeat("startup", "Setting FastInputIME keyboard")
    except Exception:
        pass
    device.deviceV2.set_fastinput_ime(True)
    cmd = ["adb"]
    dev_id = getattr(configs, "device_id", None) if configs else getattr(device, "device_id", None)
    if dev_id is not None:
        cmd.extend(["-s", str(dev_id)])
    cmd.extend(["shell", "settings", "get", "secure", "default_input_method"])
    try:
        cmd_res = subprocess.run(cmd, stdout=PIPE, stderr=PIPE, shell=False, encoding="utf8", timeout=10)
    except Exception as ex:
        logger.debug(f"Failed to check default IME: {ex}")
        cmd_res = None

    if cmd_res and cmd_res.stdout.replace(nl, "") != FastInputIME:
        logger.warning(
            f"FastInputIME is not the default keyboard! Default is: {cmd_res.stdout.replace(nl, '')}. Changing it via adb.."
        )
        set_cmd = ["adb"]
        if dev_id is not None:
            set_cmd.extend(["-s", str(dev_id)])
        set_cmd.extend(["shell", "ime", "set", FastInputIME])
        try:
            cmd_res = subprocess.run(
                set_cmd, stdout=PIPE, stderr=PIPE, shell=False, encoding="utf8", timeout=10
            )
        except Exception as ex:
            logger.debug(f"Failed to set default IME: {ex}")
            cmd_res = None

        if cmd_res and cmd_res.stdout.startswith("Error:"):
            logger.warning(
                f"{cmd_res.stdout.replace(nl, '')}. It looks like you don't have FastInputIME installed :S"
            )
        else:
            logger.info("FastInputIME is the default keyboard.")
    else:
        logger.info("FastInputIME is the default keyboard.")
    if configs and hasattr(configs, "args") and getattr(configs.args, "screen_record", False):
        try:
            device.start_screenrecord()
        except Exception as e:
            logger.error(
                f"You can't use this feature without installing dependencies. Type that in console: 'pip3 install -U \"uiautomator2[image]\" -i https://pypi.doubanio.com/simple'. Exception: {e}"
            )
    if hasattr(device, "_ig_is_opened") and not device._ig_is_opened():
        logger.warning(
            "Instagram is not in the foreground at conclusion of open_instagram(). Attempting final foreground bring-up..."
        )
        call_ig()
        time.sleep(2)
        if not device._ig_is_opened():
            logger.error("Instagram failed to stay in foreground after open_instagram().")
            return False
    return True


def close_instagram(device):
    logger.info("Close Instagram app.")
    device.deviceV2.app_stop(app_id)
    random_sleep(5, 5, modulable=False)
    if configs and hasattr(configs, "args") and getattr(configs.args, "screen_record", False):
        try:
            device.stop_screenrecord(crash=False)
        except Exception as e:
            logger.error(
                f"You can't use this feature without installing dependencies. Type that in console: 'pip3 install -U \"uiautomator2[image]\" -i https://pypi.doubanio.com/simple'. Exception: {e}"
            )


def check_if_crash_popup_is_there(device) -> bool:
    obj = device.find(resourceId=ResourceID.CRASH_POPUP)
    if obj.exists():
        obj.click()
        return True
    return False


def show_ending_conditions():
    end_likes = configs.args.end_if_likes_limit_reached
    end_follows = configs.args.end_if_follows_limit_reached
    end_watches = configs.args.end_if_watches_limit_reached
    end_comments = configs.args.end_if_comments_limit_reached
    end_pm = configs.args.end_if_pm_limit_reached
    logger.info(
        "-" * 70,
        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
    )
    logger.info(
        f"{'Session ending conditions:':<35} Value",
        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
    )
    logger.info(
        "-" * 70,
        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
    )
    logger.info(
        f"{'Likes:':<35} {end_likes}",
        extra={"color": f"{Style.BRIGHT}{Fore.GREEN if end_likes else Fore.RED}"},
    )
    logger.info(
        f"{'Follows:':<35} {end_follows}",
        extra={"color": f"{Style.BRIGHT}{Fore.GREEN if end_follows else Fore.RED}"},
    )
    logger.info(
        f"{'Watches:':<35} {end_watches}",
        extra={"color": f"{Style.BRIGHT}{Fore.GREEN if end_watches else Fore.RED}"},
    )
    logger.info(
        f"{'Comments:':<35} {end_comments}",
        extra={"color": f"{Style.BRIGHT}{Fore.GREEN if end_comments else Fore.RED}"},
    )
    logger.info(
        f"{'PM:':<35} {end_pm}",
        extra={"color": f"{Style.BRIGHT}{Fore.GREEN if end_pm else Fore.RED}"},
    )
    logger.info(
        f"{'Total actions:':<35} True (not mutable)",
        extra={"color": f"{Style.BRIGHT}{Fore.GREEN}"},
    )
    logger.info(
        f"{'Total successfull actions:':<35} True (not mutable)",
        extra={"color": f"{Style.BRIGHT}{Fore.GREEN}"},
    )
    logger.info(
        "For more info -> https://github.com/ssucipto/instaaddict/blob/master/README.md#ending-session-conditions",
        extra={"color": f"{Style.BRIGHT}{Fore.BLUE}"},
    )
    logger.info(
        "-" * 70,
        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
    )


def countdown(seconds: int = 10, waiting_message: str = "") -> None:
    from InstaAddict.core.tui import DashboardManager
    from InstaAddict.core.watchdog import record_heartbeat

    if DashboardManager.is_active():
        mgr = DashboardManager.get_instance()
        try:
            while seconds:
                record_heartbeat(
                    "countdown",
                    f"{waiting_message} {seconds}s" if waiting_message else f"Sleeping {seconds}s",
                )
                if mgr.state.consume_skip_task_request():
                    logger.info("[TUI] Countdown skipped by user shortcut ([S]/[N]).")
                    break
                mgr.state.update_countdown(seconds, waiting_message)
                mgr.update_render()
                time.sleep(1)
                seconds -= 1
        finally:
            mgr.state.update_countdown(None, "")
            mgr.update_render()
        return

    while seconds:
        record_heartbeat(
            "countdown",
            f"{waiting_message} {seconds}s" if waiting_message else f"Sleeping {seconds}s",
        )
        print(waiting_message, f"{seconds:02d}", end="\r")
        time.sleep(1)
        seconds -= 1


def choose_cloned_app(device) -> None:
    """if dialog box is displayed choose for original or cloned app"""
    use_cloned = False
    if configs and hasattr(configs, "args") and configs.args:
        use_cloned = getattr(configs.args, "use_cloned_app", False)
    app_number = "2" if use_cloned else "1"
    miui_res = getattr(ResourceID, "MIUI_APP", "android:id/text") if ResourceID else "android:id/text"
    obj = device.find(resourceId=f"{miui_res}{app_number}")
    if obj.exists(3):
        logger.debug(f"Cloned app menu exists. Pressing on app number {app_number}.")
        obj.click()


def pre_post_script(path: str, pre: bool = True):
    if path is not None:
        if os.path.isfile(path):
            logger.info(f"Running '{path}' as {'pre' if pre else 'post'} script.")
            try:
                p1 = subprocess.Popen(path)
                p1.wait(timeout=300)
            except subprocess.TimeoutExpired:
                logger.error(
                    f"{'Pre' if pre else 'Post'} script '{path}' timed out after 300s. Terminating process..."
                )
                p1.kill()
                p1.wait()
            except Exception as ex:
                logger.error(f"This exception has occurred: {ex}")
        else:
            logger.error(
                f"File '{path}' not found. Check your spelling. (The start point for relative paths is this: '{os.getcwd()}')."
            )


def print_telegram_reports(
    conf, telegram_reports_at_end, followers_now, following_now, time_left=None
):
    if followers_now is not None and telegram_reports_at_end:
        conf.actions["telegram-reports"].run(
            conf, "telegram-reports", followers_now, following_now, time_left
        )


def kill_atx_agent(device):
    _restore_keyboard(device)
    logger.info("Kill atx agent.")
    cmd = ["adb"]
    if configs.device_id is not None:
        cmd.extend(["-s", str(configs.device_id)])
    cmd.extend(["shell", "pkill", "atx-agent"])
    try:
        subprocess.run(cmd, stdout=PIPE, stderr=PIPE, shell=False, encoding="utf8", timeout=10)
    except Exception as ex:
        logger.debug(f"Failed to kill atx-agent: {ex}")


def restart_atx_agent(device):
    kill_atx_agent(device)
    logger.info("Restarting atx agent.")
    cmd = ["adb"]
    if configs.device_id is not None:
        cmd.extend(["-s", str(configs.device_id)])
    cmd.extend(["shell", "/data/local/tmp/atx-agent", "server", "-d"])

    try:
        result = subprocess.run(
            cmd, stdout=PIPE, stderr=PIPE, shell=False, encoding="utf8", check=True, timeout=15
        )
        if result.returncode != 0:
            logger.error(f"Failed to restart atx-agent: {result.stderr}")
        else:
            logger.info("atx-agent restarted successfully.")
    except Exception as e:
        logger.error(f"Error occurred while restarting atx-agent: {e}")


def _restore_keyboard(device):
    logger.debug("Back to default keyboard!")
    device.deviceV2.set_fastinput_ime(False)


def random_sleep(inf=0.5, sup=3.0, modulable=True, log=True):
    MIN_INF = 0.3
    multiplier = 1.0
    try:
        if args is not None and hasattr(args, "speed_multiplier"):
            multiplier = float(args.speed_multiplier)
    except Exception:
        multiplier = 1.0
    delay = uniform(inf, sup) / (multiplier if modulable else 1.0)
    delay = max(delay, MIN_INF)
    if log:
        logger.debug(f"{str(delay)[:4]}s sleep")

    try:
        from InstaAddict.core.tui import DashboardManager

        if DashboardManager.is_active():
            dm = DashboardManager.get_instance()
            if dm.state.is_skip_task_requested():
                return

            slice_sec = 0.1
            remaining = delay
            while remaining > 0:
                if dm.state.is_skip_task_requested():
                    break
                step = min(remaining, slice_sec)
                sleep(step)
                remaining -= step
        else:
            sleep(delay)
    except Exception:
        sleep(delay)


def save_crash(device, error_reason=None, exception=None):
    directory_name = f"{__version__}_" + datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    crash_path = os.path.join("crashes", directory_name)
    try:
        os.makedirs(crash_path, exist_ok=True)
    except OSError as e:
        logger.error(f"Cannot create directory {directory_name}: {e}")
        return
    screenshot_format = ".png"
    try:
        device.screenshot(os.path.join(crash_path, "screenshot" + screenshot_format))
    except Exception as e:
        logger.error(f"Cannot save 'screenshot.{screenshot_format}': {e}")

    hierarchy_format = ".xml"
    try:
        device.dump_hierarchy(os.path.join(crash_path, "hierarchy" + hierarchy_format))
    except Exception as e:
        logger.error(f"Cannot save 'hierarchy.{hierarchy_format}': {e}")

    # Build machine-readable crash context JSON
    context_data = {
        "timestamp": datetime.now().isoformat(),
        "bot_version": __version__,
        "error_reason": str(error_reason) if error_reason else None,
        "exception_type": type(exception).__name__ if exception else None,
        "exception_message": str(exception) if exception else None,
    }
    try:
        from InstaAddict.core.session_state import SessionState

        active_ss = SessionState.get_active()
        if active_ss:
            context_data["session_id"] = getattr(active_ss, "id", None)
            context_data["username"] = getattr(active_ss, "my_username", None)
            if getattr(active_ss, "startTime", None):
                context_data["uptime_seconds"] = round(
                    (datetime.now() - active_ss.startTime).total_seconds(), 1
                )
            context_data["total_crashes"] = getattr(active_ss, "totalCrashes", 0)
    except Exception:
        pass

    try:
        from InstaAddict.core.tui import DashboardManager

        if DashboardManager.is_active():
            dm_state = DashboardManager.get_instance().state
            context_data["active_job"] = getattr(dm_state, "current_job", None)
            context_data["active_target"] = getattr(dm_state, "current_target", None)
            context_data["current_action"] = getattr(dm_state, "current_action", None)
    except Exception:
        pass

    try:
        if device:
            if hasattr(device, "get_current_package"):
                context_data["foreground_package"] = device.get_current_package()
            elif hasattr(device, "deviceV2") and hasattr(device.deviceV2, "app_current"):
                app_curr = device.deviceV2.app_current()
                if isinstance(app_curr, dict):
                    context_data["foreground_package"] = app_curr.get("package")
                    context_data["foreground_activity"] = app_curr.get("activity")
            if hasattr(device, "is_screen_on"):
                context_data["screen_on"] = device.is_screen_on()
    except Exception:
        pass

    try:
        from InstaAddict.core.watchdog import BotWatchdog

        wd = BotWatchdog.get_instance()
        if wd:
            context_data["watchdog_checkpoint"] = getattr(wd, "last_checkpoint", None)
            context_data["watchdog_status"] = getattr(wd, "last_status", None)
    except Exception:
        pass

    try:
        with open(
            os.path.join(crash_path, "crash_context.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(context_data, f, indent=2)
    except Exception as e:
        logger.error(f"Cannot save 'crash_context.json': {e}")

    if args is not None and getattr(args, "screen_record", False):
        try:
            device.stop_screenrecord(crash=True)
        except Exception as e:
            logger.error(
                f"You can't use this feature without installing dependencies. Type that in console: 'pip3 install -U \"uiautomator2[image]\" -i https://pypi.doubanio.com/simple'. Exception: {e}"
            )
        files = [f for f in os.listdir("./") if f.endswith(".mp4")]
        try:
            source = files[-1]
            target = os.path.join(crash_path, "video.mp4")
            for attempt in range(10):
                try:
                    os.replace(source, target)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    sleep(1)
        except (FileNotFoundError, IndexError):
            logger.error("File *.mp4 not found!")
        except PermissionError as e:
            logger.error(f"Cannot save crash video because it is still in use: {e}")
    g_log_file_name, g_logs_dir, _, _ = get_log_file_config()
    if g_log_file_name and g_logs_dir:
        src_file = os.path.join(g_logs_dir, g_log_file_name)
        target_file = os.path.join(crash_path, "logs.txt")
        if os.path.exists(src_file):
            trim_txt(source=src_file, target=target_file)  # copy logs trimmed
    shutil.make_archive(crash_path, "zip", crash_path)
    shutil.rmtree(crash_path)
    logger.info(
        f"Crash saved as {crash_path}.zip",
        extra={"color": Fore.GREEN},
    )

    try:
        from InstaAddict.core.session_state import SessionState

        active_ss = SessionState.get_active()
        if active_ss:
            active_ss.record_crash(
                {
                    "timestamp": context_data["timestamp"],
                    "crash_archive": f"{crash_path}.zip",
                    "foreground_package": context_data.get("foreground_package"),
                    "foreground_activity": context_data.get("foreground_activity"),
                    "active_job": context_data.get("active_job"),
                    "active_target": context_data.get("active_target"),
                    "error_reason": error_reason,
                    "exception": str(exception) if exception else None,
                }
            )
    except Exception:
        pass
    logger.info(
        "If you want to report this crash, please upload the dump file via a ticket in the #lobby channel on discord ",
        extra={"color": Fore.GREEN},
    )
    logger.info("https://discord.gg/ySMaySMCD\n", extra={"color": Fore.GREEN})
    try:
        check_if_updated(crash=True)
    except Exception:
        pass
    if args is not None and getattr(args, "screen_record", False):
        try:
            device.start_screenrecord()
        except Exception as e:
            logger.error(
                f"You can't use this feature without installing dependencies. Type that in console: 'pip3 install -U \"uiautomator2[image]\" -i https://pypi.doubanio.com/simple'. Exception: {e}"
            )


def trim_txt(source: str, target: str) -> None:
    with open(source, "r", encoding="utf-8") as f:
        lines = f.readlines()
    tail = next(
        (
            index
            for index, line in enumerate(lines[::-1])
            if line.find("Arguments used:") != -1
        ),
        250,
    )
    rem = lines[-tail:]
    with open(target, "w", encoding="utf-8") as f:
        f.writelines(rem)


def stop_bot(device, sessions, session_state, was_sleeping=False):
    try:
        from InstaAddict.core.beacon import get_active_beacon_writer, set_active_beacon_writer

        active_writer = get_active_beacon_writer()
        if active_writer is not None:
            active_writer.set_status("stopped")
            active_writer.stop()
            set_active_beacon_writer(None)
    except Exception:
        pass
    try:
        from InstaAddict.core.watchdog import BotWatchdog

        BotWatchdog.get_instance().stop()
    except Exception:
        pass
    try:
        from InstaAddict.core.session_state import SessionState

        SessionState.set_active(None)
    except Exception:
        pass

    from InstaAddict.core.log import disable_tui_logging
    from InstaAddict.core.tui import DashboardManager

    if DashboardManager.is_active():
        DashboardManager.get_instance().stop()
        disable_tui_logging()

    close_instagram(device)
    if args is not None and getattr(args, "kill_atx_agent", False):
        kill_atx_agent(device)
    head_up_notifications(enabled=True)
    logger.info(
        f"-------- FINISH: {datetime.now().strftime('%H:%M:%S')} --------",
        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
    )
    if session_state is not None:
        if hasattr(session_state, "finalize_jobs"):
            session_state.finalize_jobs("interrupted")
        if getattr(session_state, "finishTime", None) is None:
            session_state.finishTime = datetime.now()
        scrape_to_file = getattr(getattr(configs, "args", None), "scrape_to_file", None)
        print_full_report(sessions, scrape_to_file)
        if not was_sleeping:
            sessions.persist(directory=session_state.my_username)
    ask_for_a_donation()
    sys.exit(2)


def can_repeat(current_session, max_sessions: int) -> bool:
    if max_sessions == -1:
        return True
    logger.info(
        f"You completed {current_session} session(s). {max_sessions-current_session} session(s) left.",
        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
    )
    if current_session < max_sessions:
        return True
    logger.info(
        "You reached the total-sessions limit! Finish.",
        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
    )
    return False


def get_value(
    count: str,
    name: Optional[str],
    default: Optional[Union[int, float]] = 0,
    its_time: bool = False,
) -> Optional[Union[int, float]]:
    def print_error() -> None:
        logger.error(
            f'Using default value instead of "{count}", because it must be '
            "either a number (e.g. 2) or a range (e.g. 2-4)."
        )

    if count is None:
        return None
    try:
        if "." in count:
            value = float(count)
        else:
            value = int(count)
    except ValueError:
        parts = count.split("-")
        if len(parts) == 2:
            if not its_time:
                value = randint(int(parts[0]), int(parts[1]))
            else:
                value = round(uniform(int(parts[0]), int(parts[1])), 2)
        else:
            value = default
            print_error()
    if name is not None:
        logger.info(name.format(value), extra={"color": Style.BRIGHT})
    return value


def validate_url(x) -> bool:
    try:
        result = urlparse(x)
        return all([result.scheme, result.netloc, result.path])
    except Exception as e:
        logger.error(f"Error validating URL {x}. Error: {e}")
        return False


def append_to_file(filename: str, username: str) -> None:
    try:
        if not filename.lower().endswith(".txt"):
            filename += ".txt"
        with open(filename, "a+", encoding="utf-8") as file:
            file.write(username + "\n")
    except Exception as e:
        logger.error(f"Failed to append {username} to: {filename}. Exception: {e}")


def sample_sources(sources, n_sources):
    from random import sample

    sources_limit_input = n_sources.split("-")
    if len(sources_limit_input) > 1:
        sources_limit = randint(
            int(sources_limit_input[0]), int(sources_limit_input[1])
        )
    else:
        sources_limit = int(sources_limit_input[0])
    if len(sources) < sources_limit:
        sources_limit = len(sources)
    if sources_limit == 0:
        truncaded = sources
        shuffle(truncaded)
    else:
        truncaded = sample(sources, sources_limit)
        logger.info(
            f"Source list truncated at {len(truncaded)} {'item' if len(truncaded)<=1 else 'items'}."
        )
    logger.info(
        f"In this session, {'that source' if len(truncaded)<=1 else 'these sources'} will be handled: {', '.join(emoji.emojize(str(x), use_aliases=True) for x in truncaded)}"
    )
    return truncaded


def random_choice(number: int) -> bool:
    """
    Generate a random int and compare with the argument passed
    :param int number: number passed
    :return: is argument greater or equal then a random generated number
    :rtype: bool
    """
    return number >= randint(1, 100)


def init_on_things(source, args, sessions, session_state):
    from functools import partial

    from InstaAddict.core.interaction import _on_interaction

    on_interaction = partial(
        _on_interaction,
        likes_limit=args.current_likes_limit,
        source=source,
        interactions_limit=get_value(
            args.interactions_count, "Interactions count: {}", 70
        ),
        sessions=sessions,
        session_state=session_state,
        args=args,
    )

    if args.stories_count != "0":
        stories_percentage = get_value(
            args.stories_percentage, "Chance of watching stories: {}%", 40
        )
    else:
        stories_percentage = 0

    likes_percentage = get_value(args.likes_percentage, "Chance of liking: {}%", 100)
    follow_percentage = get_value(
        args.follow_percentage, "Chance of following: {}%", 40
    )
    comment_percentage = get_value(
        args.comment_percentage, "Chance of commenting: {}%", 0
    )
    interact_percentage = get_value(
        args.interact_percentage, "Chance of interacting: {}%", 40
    )
    pm_percentage = get_value(args.pm_percentage, "Chance of send PM: {}%", 0)

    return (
        on_interaction,
        stories_percentage,
        likes_percentage,
        follow_percentage,
        comment_percentage,
        pm_percentage,
        interact_percentage,
    )


def set_time_delta(args):
    args.time_delta_session = (
        get_value(args.time_delta, None, 0) * (1 if random.random() < 0.5 else -1) * 60
    ) + random.randint(0, 59)
    m, s = divmod(abs(args.time_delta_session), 60)
    h, m = divmod(m, 60)
    logger.info(
        f"Time delta has set to {'' if args.time_delta_session >0 else '-'}{h:02d}:{m:02d}:{s:02d}."
    )


def wait_for_next_session(time_left, session_state, sessions, device):
    try:
        from InstaAddict.core.watchdog import BotWatchdog

        BotWatchdog.get_instance().pause()
    except Exception:
        pass
    hours, remainder = divmod(time_left.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if args is not None and getattr(args, "kill_atx_agent", False):
        kill_atx_agent(device)
    logger.info(
        f'Next session will start at: {(datetime.now()+ time_left).strftime("%H:%M:%S (%Y/%m/%d)")}.',
        extra={"color": f"{Fore.GREEN}"},
    )
    logger.info(
        f"Time left: {hours:02d}:{minutes:02d}:{seconds:02d}.",
        extra={"color": f"{Fore.GREEN}"},
    )
    try:
        from InstaAddict.core.tui import DashboardManager

        if DashboardManager.is_active():
            wh_str = (
                getattr(args, "working_hours", "configured hours")
                if args
                else "configured hours"
            )
            dm = DashboardManager.get_instance()
            next_start_time = (datetime.now() + time_left).strftime("%H:%M")
            dm.state.update_activity(
                job="Scheduled Sleep",
                action=f"Sleeping until {next_start_time} (Working hours: {wh_str})",
                source="working-hours",
            )
            dm.update_render()
    except Exception:
        pass
    try:
        total_seconds = time_left.total_seconds()
        while total_seconds > 0:
            slice_sleep = min(5.0, total_seconds)
            sleep(slice_sleep)
            total_seconds -= slice_sleep

            try:
                from InstaAddict.core.tui import DashboardManager

                if (
                    DashboardManager.is_active()
                    and DashboardManager.get_instance().state.is_upload_requested()
                ):
                    logger.info(
                        "[TUI] On-demand upload requested via [CTRL+U] during sleep. Waking up immediately to process upload...",
                        extra={"color": f"{Fore.MAGENTA}"},
                    )
                    break
            except Exception:
                pass

            if getattr(args, "telegram_inbox", False) or getattr(
                args, "telegram_reports", False
            ):
                try:
                    from InstaAddict.plugins.telegram import check_telegram_inbox

                    check_telegram_inbox(args.username)
                except Exception as e:
                    logger.debug(
                        f"check_telegram_inbox during sleep error: {e}"
                    )
    except KeyboardInterrupt:
        stop_bot(device, sessions, session_state, was_sleeping=True)
    finally:
        try:
            from InstaAddict.core.watchdog import BotWatchdog

            BotWatchdog.get_instance().resume()
        except Exception:
            pass


def inspect_current_view(user_list, _retries=2) -> Tuple[int, int]:
    """
    return the number of users and each row height in the current view
    """
    from InstaAddict.core.device_facade import DeviceFacade

    user_list.wait()
    lst = []
    for item in user_list:
        if not item.wait():
            continue
        try:
            lst.append(item.get_height())
        except DeviceFacade.JsonRpcError:
            logger.debug(
                "Skip row while inspecting current view because bounds are unavailable."
            )
            continue
    if not lst:
        if _retries > 0:
            logger.debug(
                f"Empty list detected, waiting 3s and retrying ({_retries} retries left)."
            )
            sleep(3)
            return inspect_current_view(user_list, _retries=_retries - 1)
        raise EmptyList
    row_height, n_users = Counter(lst).most_common(1)[0]
    logger.debug(f"There are {n_users} users fully visible in that view.")
    return row_height, n_users


class ActionBlockedError(Exception):
    pass


class EmptyList(Exception):
    pass


class Square:
    def __init__(self, x0, y0, x1, y1):
        self.delta = 7
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1

    def point(self):
        """return safe point to click"""
        if (self.x1 - self.x0) <= (2 * self.delta) or (self.y1 - self.y0) <= (
            2 * self.delta
        ):
            return nan
        else:
            return [
                randint(self.x0 + self.delta, self.x1 - self.delta),
                randint(self.y0 + self.delta, self.y1 - self.delta),
            ]
