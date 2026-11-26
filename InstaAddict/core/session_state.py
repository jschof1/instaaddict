import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum, auto
from json import JSONEncoder
from typing import Optional

from InstaAddict.core.utils import get_value

logger = logging.getLogger(__name__)


class SessionState:
    _active_session = None
    id = None
    args = {}
    my_username = None
    my_posts_count = None
    my_followers_count = None
    my_following_count = None
    totalInteractions = {}
    successfulInteractions = {}
    totalFollowed = {}
    totalLikes = 0
    totalComments = 0
    totalPm = 0
    totalWatched = 0
    totalVideoWatchWindows = 0
    totalVideoWatchSeconds = 0.0
    totalUnfollowed = 0
    removedMassFollowers = []
    totalScraped = 0
    totalCrashes = 0
    totalWatchdogRecoveries = 0
    totalPostsChecked = 0
    totalProfilesChecked = 0
    totalProfilesSkipped = 0
    totalAdsBypassed = 0
    totalDialogsDismissed = 0
    totalReelsEvaluated = 0
    totalSubscreenEscapes = 0
    totalSwipes = 0
    zeroDisplacementSwipes = 0
    snapbackEvents = 0
    totalMicroStallEscapes = 0
    durationsP50 = {}
    durationsP95 = {}
    skip_reasons = {}
    job_metrics = {}
    crash_history = []
    current_job = None
    startTime = None
    finishTime = None

    @classmethod
    def get_active(cls) -> Optional["SessionState"]:
        return cls._active_session

    @classmethod
    def set_active(cls, session: Optional["SessionState"]):
        cls._active_session = session

    def __init__(self, configs=None):
        self.id = str(uuid.uuid4())
        self.args = configs.args if configs and hasattr(configs, "args") else {}
        if hasattr(self.args, "username"):
            self.my_username = getattr(self.args, "username", None)
        elif isinstance(self.args, dict):
            self.my_username = self.args.get("username")
        else:
            self.my_username = None
        self.my_posts_count = None
        self.my_followers_count = None
        self.my_following_count = None
        self.totalInteractions = {}
        self.successfulInteractions = {}
        self.totalFollowed = {}
        self.totalLikes = 0
        self.totalComments = 0
        self.totalPm = 0
        self.totalWatched = 0
        self.totalVideoWatchWindows = 0
        self.totalVideoWatchSeconds = 0.0
        self.totalUnfollowed = 0
        self.removedMassFollowers = []
        self.totalScraped = {}
        self.totalCrashes = 0
        self.totalWatchdogRecoveries = 0
        self.totalPostsChecked = 0
        self.totalProfilesChecked = 0
        self.totalProfilesSkipped = 0
        self.totalAdsBypassed = 0
        self.totalDialogsDismissed = 0
        self.totalReelsEvaluated = 0
        self.totalSubscreenEscapes = 0
        self.totalSwipes = 0
        self.zeroDisplacementSwipes = 0
        self.snapbackEvents = 0
        self.totalMicroStallEscapes = 0
        self.durationsP50 = {}
        self.durationsP95 = {}
        self.skip_reasons = {}
        self.job_metrics = {}
        self.crash_history = []
        self.current_job = None
        self.totalUploadsSuccess = 0
        self.totalUploadsFailed = 0
        self.uploadHistory = []
        self.startTime = datetime.now()
        self.finishTime = None

    def _sync_tui(self):
        try:
            from InstaAddict.core.tui import DashboardManager

            if DashboardManager.is_active():
                DashboardManager.get_instance().state.update_from_session_state(self)
        except Exception:
            pass

    def increment_watchdog_recoveries(self, count: int = 1):
        self.totalWatchdogRecoveries = (
            getattr(self, "totalWatchdogRecoveries", 0) + count
        )
        self._sync_tui()

    def increment_posts_checked(self, count: int = 1):
        self.totalPostsChecked = getattr(self, "totalPostsChecked", 0) + count
        self._sync_tui()

    def increment_profiles_checked(self, count: int = 1):
        self.totalProfilesChecked = getattr(self, "totalProfilesChecked", 0) + count
        self._sync_tui()

    def increment_profiles_skipped(self, count: int = 1):
        self.totalProfilesSkipped = getattr(self, "totalProfilesSkipped", 0) + count
        self._sync_tui()

    def increment_ads_bypassed(self, count: int = 1):
        self.totalAdsBypassed = getattr(self, "totalAdsBypassed", 0) + count
        self._sync_tui()

    def increment_dialogs_dismissed(self, count: int = 1):
        self.totalDialogsDismissed = getattr(self, "totalDialogsDismissed", 0) + count
        self._sync_tui()

    def increment_reels_evaluated(self, count: int = 1):
        self.totalReelsEvaluated = getattr(self, "totalReelsEvaluated", 0) + count
        self._sync_tui()

    def increment_subscreen_escapes(self, count: int = 1):
        self.totalSubscreenEscapes = (
            getattr(self, "totalSubscreenEscapes", 0) + count
        )
        self._sync_tui()

    def increment_swipes(self, count: int = 1):
        self.totalSwipes = getattr(self, "totalSwipes", 0) + count
        self._sync_tui()

    def increment_zero_displacement(self, count: int = 1):
        self.zeroDisplacementSwipes = (
            getattr(self, "zeroDisplacementSwipes", 0) + count
        )
        self._sync_tui()

    def increment_snapback_events(self, count: int = 1):
        self.snapbackEvents = getattr(self, "snapbackEvents", 0) + count
        self._sync_tui()

    def increment_micro_stall_escapes(self, count: int = 1):
        self.totalMicroStallEscapes = (
            getattr(self, "totalMicroStallEscapes", 0) + count
        )
        self._sync_tui()

    def update_durations(self, p50_dict: dict, p95_dict: dict):
        self.durationsP50 = dict(p50_dict)
        self.durationsP95 = dict(p95_dict)
        self._sync_tui()

    def record_skip_reason(self, reason: str, count: int = 1):
        if not hasattr(self, "skip_reasons") or self.skip_reasons is None:
            self.skip_reasons = {}
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + count
        self._sync_tui()

    def record_crash(self, crash_info: dict):
        if not hasattr(self, "crash_history") or self.crash_history is None:
            self.crash_history = []
        self.crash_history.append(crash_info)
        self.totalCrashes = getattr(self, "totalCrashes", 0) + 1
        self._sync_tui()

    def start_job(self, job_name: str):
        self.current_job = job_name
        if not hasattr(self, "job_metrics") or self.job_metrics is None:
            self.job_metrics = {}
        if job_name not in self.job_metrics:
            self.job_metrics[job_name] = {
                "started_at": datetime.now().isoformat(),
                "finished_at": None,
                "duration_seconds": 0.0,
                "status": "in_progress",
                "interactions_attempted": 0,
                "interactions_successful": 0,
                "followed": 0,
                "scraped": 0,
            }
        else:
            self.job_metrics[job_name]["status"] = "in_progress"

    def end_job(self, job_name: str, status: str = "completed"):
        if getattr(self, "current_job", None) == job_name:
            self.current_job = None
        if not hasattr(self, "job_metrics") or self.job_metrics is None:
            self.job_metrics = {}
        if job_name in self.job_metrics:
            metrics = self.job_metrics[job_name]
            metrics["finished_at"] = datetime.now().isoformat()
            metrics["status"] = status
            try:
                start_dt = datetime.fromisoformat(metrics["started_at"])
                metrics["duration_seconds"] = round(
                    (datetime.now() - start_dt).total_seconds(), 1
                )
            except Exception:
                pass

    def finalize_jobs(self, default_status: str = "interrupted"):
        """Ensure no jobs remain 'in_progress' when a session finishes or is aborted."""
        if not hasattr(self, "job_metrics") or self.job_metrics is None:
            self.job_metrics = {}
            return
        now_iso = datetime.now().isoformat()
        for job_name, metrics in self.job_metrics.items():
            if metrics.get("status") == "in_progress":
                metrics["status"] = default_status
                metrics["finished_at"] = now_iso
                try:
                    start_dt = datetime.fromisoformat(metrics["started_at"])
                    metrics["duration_seconds"] = round(
                        (datetime.now() - start_dt).total_seconds(), 1
                    )
                except Exception:
                    pass
        self.current_job = None

    def record_job_interaction(
        self,
        job_name: str,
        success: bool = True,
        followed: bool = False,
        scraped: bool = False,
    ):
        if not hasattr(self, "job_metrics") or self.job_metrics is None:
            self.job_metrics = {}
        if job_name in self.job_metrics:
            self.job_metrics[job_name]["interactions_attempted"] += 1
            if success or scraped:
                self.job_metrics[job_name]["interactions_successful"] += 1
            if followed:
                self.job_metrics[job_name]["followed"] += 1
            if scraped:
                self.job_metrics[job_name]["scraped"] += 1

    def add_interaction(self, source, succeed, followed, scraped):
        if self.totalInteractions.get(source) is None:
            self.totalInteractions[source] = 1
        else:
            self.totalInteractions[source] += 1

        is_success = bool(succeed or scraped)
        if self.successfulInteractions.get(source) is None:
            self.successfulInteractions[source] = 1 if is_success else 0
        else:
            if is_success:
                self.successfulInteractions[source] += 1

        if self.totalFollowed.get(source) is None:
            self.totalFollowed[source] = 1 if followed else 0
        else:
            if followed:
                self.totalFollowed[source] += 1

        if self.totalScraped.get(source) is None:
            self.totalScraped[source] = 1 if scraped else 0
        else:
            if scraped:
                self.totalScraped[source] += 1

        if getattr(self, "current_job", None):
            self.record_job_interaction(self.current_job, is_success, followed, scraped)

        self._sync_tui()

    def set_limits_session(
        self,
    ):
        """set the limits for current session"""
        self.args.current_likes_limit = get_value(
            self.args.total_likes_limit, None, 300
        )
        self.args.current_follow_limit = get_value(
            self.args.total_follows_limit, None, 50
        )
        self.args.current_unfollow_limit = get_value(
            self.args.total_unfollows_limit, None, 50
        )
        self.args.current_comments_limit = get_value(
            self.args.total_comments_limit, None, 10
        )
        self.args.current_pm_limit = get_value(self.args.total_pm_limit, None, 10)
        self.args.current_watch_limit = get_value(
            self.args.total_watches_limit, None, 50
        )
        self.args.current_success_limit = get_value(
            self.args.total_successful_interactions_limit, None, 100
        )
        self.args.current_total_limit = get_value(
            self.args.total_interactions_limit, None, 1000
        )
        self.args.current_scraped_limit = get_value(
            self.args.total_scraped_limit, None, 200
        )
        self.args.current_crashes_limit = get_value(
            self.args.total_crashes_limit, None, 5
        )

    def check_limit(self, limit_type=None, output=False):
        """Returns True if limit reached - else False"""
        limit_type = SessionState.Limit.ALL if limit_type is None else limit_type
        # check limits
        total_likes = self.totalLikes >= int(self.args.current_likes_limit)
        total_followed = sum(self.totalFollowed.values()) >= int(
            self.args.current_follow_limit
        )
        total_unfollowed = self.totalUnfollowed >= int(self.args.current_unfollow_limit)
        total_comments = self.totalComments >= int(self.args.current_comments_limit)
        total_pm = self.totalPm >= int(self.args.current_pm_limit)
        total_watched = self.totalWatched >= int(self.args.current_watch_limit)
        total_successful = sum(self.successfulInteractions.values()) >= int(
            self.args.current_success_limit
        )
        total_interactions = sum(self.totalInteractions.values()) >= int(
            self.args.current_total_limit
        )

        total_scraped = sum(self.totalScraped.values()) >= int(
            self.args.current_scraped_limit
        )

        total_crashes = self.totalCrashes >= int(self.args.current_crashes_limit)

        session_info = [
            "Checking session limits:",
            f"- Total Likes:\t\t\t\t{'Limit Reached' if total_likes else 'OK'} ({self.totalLikes}/{self.args.current_likes_limit})",
            f"- Total Comments:\t\t\t\t{'Limit Reached' if total_comments else 'OK'} ({self.totalComments}/{self.args.current_comments_limit})",
            f"- Total PM:\t\t\t\t\t{'Limit Reached' if total_pm else 'OK'} ({self.totalPm}/{self.args.current_pm_limit})",
            f"- Total Followed:\t\t\t\t{'Limit Reached' if total_followed else 'OK'} ({sum(self.totalFollowed.values())}/{self.args.current_follow_limit})",
            f"- Total Unfollowed:\t\t\t\t{'Limit Reached' if total_unfollowed else 'OK'} ({self.totalUnfollowed}/{self.args.current_unfollow_limit})",
            f"- Total Watched:\t\t\t\t{'Limit Reached' if total_watched else 'OK'} ({self.totalWatched}/{self.args.current_watch_limit})",
            f"- Total Successful Interactions:\t\t{'Limit Reached' if total_successful else 'OK'} ({sum(self.successfulInteractions.values())}/{self.args.current_success_limit})",
            f"- Total Interactions:\t\t\t{'Limit Reached' if total_interactions else 'OK'} ({sum(self.totalInteractions.values())}/{self.args.current_total_limit})",
            f"- Total Crashes:\t\t\t\t{'Limit Reached' if total_crashes else 'OK'} ({self.totalCrashes}/{self.args.current_crashes_limit})",
            f"- Total Successful Scraped Users:\t\t{'Limit Reached' if total_scraped else 'OK'} ({sum(self.totalScraped.values())}/{self.args.current_scraped_limit})",
        ]

        if limit_type == SessionState.Limit.ALL:
            if output is not None:
                if output:
                    for line in session_info:
                        logger.info(line)
                else:
                    for line in session_info:
                        logger.debug(line)

            return (
                total_likes
                and self.args.end_if_likes_limit_reached
                or total_followed
                and self.args.end_if_follows_limit_reached
                or total_watched
                and self.args.end_if_watches_limit_reached
                or total_comments
                and self.args.end_if_comments_limit_reached
                or total_pm
                and self.args.end_if_pm_limit_reached,
                total_unfollowed,
                total_interactions or total_successful or total_scraped,
            )

        elif limit_type == SessionState.Limit.LIKES:
            if output:
                logger.info(session_info[1])
            else:
                logger.debug(session_info[1])
            return total_likes

        elif limit_type == SessionState.Limit.COMMENTS:
            if output:
                logger.info(session_info[2])
            else:
                logger.debug(session_info[2])
            return total_comments

        elif limit_type == SessionState.Limit.PM:
            if output:
                logger.info(session_info[3])
            else:
                logger.debug(session_info[3])
            return total_pm

        elif limit_type == SessionState.Limit.FOLLOWS:
            if output:
                logger.info(session_info[4])
            else:
                logger.debug(session_info[4])
            return total_followed

        elif limit_type == SessionState.Limit.UNFOLLOWS:
            if output:
                logger.info(session_info[5])
            else:
                logger.debug(session_info[5])
            return total_unfollowed

        elif limit_type == SessionState.Limit.WATCHES:
            if output:
                logger.info(session_info[6])
            else:
                logger.debug(session_info[6])
            return total_watched

        elif limit_type == SessionState.Limit.SUCCESS:
            if output:
                logger.info(session_info[7])
            else:
                logger.debug(session_info[7])
            return total_successful

        elif limit_type == SessionState.Limit.TOTAL:
            if output:
                logger.info(session_info[8])
            else:
                logger.debug(session_info[8])
            return total_interactions

        elif limit_type == SessionState.Limit.CRASHES:
            if output:
                logger.info(session_info[9])
            else:
                logger.debug(session_info[9])
            return total_crashes

        elif limit_type == SessionState.Limit.SCRAPED:
            if output:
                logger.info(session_info[10])
            else:
                logger.debug(session_info[10])
            return total_scraped

    @staticmethod
    def inside_working_hours(working_hours, delta_sec):
        def time_in_range(start, end, x):
            if start <= end:
                return start <= x <= end
            else:
                return start <= x or x <= end

        in_range = False
        time_left_list = []
        current_time = datetime.now()
        delta = timedelta(seconds=delta_sec)
        if isinstance(working_hours, str):
            working_hours = [working_hours]
        for n in working_hours:
            today = current_time.strftime("%Y-%m-%d")
            inf_value = f"{n.split('-')[0]} {today}"
            inf = datetime.strptime(inf_value, "%H.%M %Y-%m-%d") + delta
            sup_value = f"{n.split('-')[1]} {today}"
            sup = datetime.strptime(sup_value, "%H.%M %Y-%m-%d") + delta
            if sup - inf + timedelta(minutes=1) == timedelta(
                days=1
            ) or sup - inf + timedelta(minutes=1) == timedelta(days=0):
                logger.debug("Whole day mode.")
                return True, 0
            if time_in_range(inf.time(), sup.time(), current_time.time()):
                in_range = True
                return in_range, 0
            else:
                time_left = inf - current_time
                if time_left >= timedelta(0):
                    time_left_list.append(time_left)
                else:
                    time_left_list.append(time_left + timedelta(days=1))

        return (
            in_range,
            min(time_left_list) if len(time_left_list) > 1 else time_left_list[0],
        )

    def is_finished(self):
        return self.finishTime is not None

    class Limit(Enum):
        ALL = auto()
        LIKES = auto()
        COMMENTS = auto()
        PM = auto()
        FOLLOWS = auto()
        UNFOLLOWS = auto()
        WATCHES = auto()
        SUCCESS = auto()
        TOTAL = auto()
        SCRAPED = auto()
        CRASHES = auto()


class SessionStateEncoder(JSONEncoder):
    def default(self, session_state: SessionState):
        if hasattr(session_state, "finalize_jobs"):
            session_state.finalize_jobs()
        return {
            "id": session_state.id,
            "total_interactions": sum(session_state.totalInteractions.values()),
            "successful_interactions": sum(
                session_state.successfulInteractions.values()
            ),
            "total_followed": sum(session_state.totalFollowed.values()),
            "total_likes": session_state.totalLikes,
            "total_comments": session_state.totalComments,
            "total_pm": session_state.totalPm,
            "total_watched": session_state.totalWatched,
            "video_watch_windows": getattr(session_state, "totalVideoWatchWindows", 0),
            "video_watch_seconds": round(getattr(session_state, "totalVideoWatchSeconds", 0.0), 2),
            "total_unfollowed": session_state.totalUnfollowed,
            "total_scraped": session_state.totalScraped,
            "total_crashes": getattr(session_state, "totalCrashes", 0),
            "total_watchdog_recoveries": getattr(
                session_state, "totalWatchdogRecoveries", 0
            ),
            "total_posts_checked": getattr(session_state, "totalPostsChecked", 0),
            "total_profiles_checked": getattr(session_state, "totalProfilesChecked", 0),
            "total_profiles_skipped": getattr(session_state, "totalProfilesSkipped", 0),
            "total_ads_bypassed": getattr(session_state, "totalAdsBypassed", 0),
            "total_dialogs_dismissed": getattr(session_state, "totalDialogsDismissed", 0),
            "total_reels_evaluated": getattr(session_state, "totalReelsEvaluated", 0),
            "total_subscreen_escapes": getattr(
                session_state, "totalSubscreenEscapes", 0
            ),
            "total_swipes": getattr(session_state, "totalSwipes", 0),
            "zero_displacement_swipes": getattr(
                session_state, "zeroDisplacementSwipes", 0
            ),
            "snapback_events": getattr(session_state, "snapbackEvents", 0),
            "total_micro_stall_escapes": getattr(
                session_state, "totalMicroStallEscapes", 0
            ),
            "durations_p50": getattr(session_state, "durationsP50", {}),
            "durations_p95": getattr(session_state, "durationsP95", {}),
            "skip_reasons": getattr(session_state, "skip_reasons", {}),
            "job_metrics": getattr(session_state, "job_metrics", {}),
            "crash_history": getattr(session_state, "crash_history", []),
            "total_uploads_success": getattr(session_state, "totalUploadsSuccess", 0),
            "total_uploads_failed": getattr(session_state, "totalUploadsFailed", 0),
            "upload_history": getattr(session_state, "uploadHistory", []),
            "start_time": str(session_state.startTime),
            "finish_time": (
                str(session_state.finishTime)
                if getattr(session_state, "finishTime", None) is not None
                else "None"
            ),
            "args": (
                session_state.args.__dict__
                if hasattr(session_state.args, "__dict__")
                else (session_state.args or {})
            ),
            "profile": {
                "posts": session_state.my_posts_count,
                "followers": session_state.my_followers_count,
                "following": session_state.my_following_count,
            },
        }
