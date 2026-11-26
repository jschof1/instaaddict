import logging
import sys
import traceback
from datetime import datetime
from http.client import HTTPException
from socket import timeout

from colorama import Fore, Style
from adbutils.errors import AdbError
from requests.exceptions import ConnectionError as RequestsConnectionError
from uiautomator2.exceptions import UiObjectNotFoundError

from InstaAddict.core.device_facade import DeviceFacade
from InstaAddict.core.report import print_full_report
from InstaAddict.core.utils import (
    EmptyList,
    check_if_crash_popup_is_there,
    close_instagram,
    open_instagram,
    random_sleep,
    save_crash,
    stop_bot,
)
from InstaAddict.core.views import TabBarView

logger = logging.getLogger(__name__)


def run_safely(device, device_id, sessions, session_state, screen_record, configs):
    def actual_decorator(func):
        def wrapper(*args, **kwargs):
            session_state = sessions[-1]
            try:
                func(*args, **kwargs)
            except KeyboardInterrupt:
                try:
                    # Catch Ctrl-C and ask if user wants to pause execution
                    logger.info(
                        "CTRL-C detected . . .",
                        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
                    )
                    logger.info(
                        f"-------- PAUSED: {datetime.now().strftime('%H:%M:%S')} --------",
                        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
                    )
                    logger.info(
                        "NOTE: This is a rudimentary pause. It will restart the action, while retaining session data.",
                        extra={"color": Style.BRIGHT},
                    )
                    logger.info(
                        "Press RETURN to resume or CTRL-C again to Quit: ",
                        extra={"color": Style.BRIGHT},
                    )

                    try:
                        input("")
                    except (KeyboardInterrupt, EOFError):
                        stop_bot(device, sessions, session_state)
                        return

                    logger.info(
                        f"-------- RESUMING: {datetime.now().strftime('%H:%M:%S')} --------",
                        extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
                    )
                    TabBarView(device).navigateToProfile()
                except (KeyboardInterrupt, EOFError):
                    stop_bot(device, sessions, session_state)
                    return

            except DeviceFacade.AppHasCrashed as exc:
                logger.warning("%s", exc)
                restart(
                    device,
                    sessions,
                    session_state,
                    configs,
                    normal_crash=False,
                    print_traceback=False,
                )

            except EmptyList:
                logger.info(
                    "Empty list encountered (empty/restricted source or list end) - advancing task without crash restart."
                )
                return

            except (
                DeviceFacade.JsonRpcError,
                IndexError,
                HTTPException,
                timeout,
                UiObjectNotFoundError,
                AdbError,
                RequestsConnectionError,
            ):
                restart(
                    device,
                    sessions,
                    session_state,
                    configs,
                )

            except Exception as e:
                logger.error(traceback.format_exc())
                for exception_line in traceback.format_exception_only(type(e), e):
                    logger.critical(
                        f"'{exception_line}' -> This kind of exception will stop the bot (no restart)."
                    )
                logger.info(
                    f"List of running apps: {', '.join(device.deviceV2.app_list_running())}"
                )
                save_crash(device)
                close_instagram(device)
                print_full_report(sessions, configs.args.scrape_to_file)
                sessions.persist(directory=session_state.my_username)
                raise e from e

        return wrapper

    return actual_decorator


def restart(
    device: DeviceFacade,
    sessions,
    session_state,
    configs,
    normal_crash: bool = True,
    print_traceback: bool = True,
):
    if print_traceback:
        logger.error(traceback.format_exc())
        save_crash(device)
    logger.info(
        f"List of running apps: {', '.join(device.deviceV2.app_list_running())}."
    )
    if configs.args.count_app_crashes or normal_crash:
        session_state.totalCrashes += 1
        if session_state.check_limit(
            limit_type=session_state.Limit.CRASHES, output=True
        ):
            logger.error(
                "Reached crashes limit. Bot has crashed too much! Please check what's going on."
            )
            stop_bot(device, sessions, session_state)
        logger.info("Something unexpected happened. Let's try again.")
    close_instagram(device)
    check_if_crash_popup_is_there(device)
    random_sleep()
    if hasattr(device, "ensure_uiautomator_alive"):
        try:
            device.ensure_uiautomator_alive()
        except Exception as e:
            logger.debug(
                f"UiAutomator resurrection check during restart encountered: {e}"
            )
    if not open_instagram(device):
        import time

        logger.error(
            "open_instagram() failed during restart recovery. Initiating autonomous backoff recovery..."
        )
        print_full_report(
            sessions,
            configs.args.scrape_to_file if configs and hasattr(configs, "args") else False,
        )
        if session_state and hasattr(session_state, "my_username") and session_state.my_username:
            sessions.persist(directory=session_state.my_username)
        revived = False
        for recovery_attempt in range(1, 4):
            backoff_secs = 60 * recovery_attempt
            logger.warning(
                f"[AUTONOMOUS RECOVERY] Waiting {backoff_secs}s before re-attempting Instagram restart ({recovery_attempt}/3)..."
            )
            time.sleep(backoff_secs)
            if hasattr(device, "_recover_adb"):
                try:
                    device._recover_adb()
                except Exception:
                    pass
            if hasattr(device, "ensure_uiautomator_alive"):
                try:
                    device.ensure_uiautomator_alive()
                except Exception:
                    pass
            if open_instagram(device):
                logger.info("[AUTONOMOUS RECOVERY] Instagram successfully revived after backoff!")
                revived = True
                break
        if not revived:
            logger.critical(
                "[AUTONOMOUS RECOVERY] Instagram could not be revived after 3 backoff cycles. Yielding control to session supervisor loop."
            )
            return False
    try:
        TabBarView(device).navigateToProfile()
    except Exception as e:
        logger.warning(
            f"Unable to navigate to profile immediately after restart ({e}). Retrying after brief settle..."
        )
        random_sleep(2, 4, modulable=False)
        try:
            TabBarView(device).navigateToProfile()
        except Exception as e2:
            logger.error(
                f"Failed to navigate to profile after restart: {e2}. Proceeding with recovery."
            )
