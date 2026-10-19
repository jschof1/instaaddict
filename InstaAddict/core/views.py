import datetime
import logging
import re
import platform
import xml.etree.ElementTree as ET
from enum import Enum, auto
from random import randint, uniform
from time import sleep
from typing import Optional, Tuple

import emoji
from colorama import Fore, Style

from InstaAddict.core.device_facade import (
    DeviceFacade,
    Direction,
    Location,
    Mode,
    SleepTime,
    Timeout,
)
from InstaAddict.core.resources import ClassName
from InstaAddict.core.resources import ResourceID as resources
from InstaAddict.core.resources import TabBarText
from InstaAddict.core.utils import (
    ActionBlockedError,
    EmptyList,
    get_value,
    inspect_current_view,
    random_sleep,
    save_crash,
)

logger = logging.getLogger(__name__)

# Module-level globals initialized to prevent NameError prior to load_config
args = None
configs = None
ResourceID = resources("com.instagram.android")


def load_config(config):
    global args
    global configs
    global ResourceID
    args = config.args
    configs = config
    ResourceID = resources(config.args.app_id)


def case_insensitive_re(str_list):
    strings = str_list if isinstance(str_list, str) else "|".join(str_list)
    return f"(?i)({strings})"


class TabBarTabs(Enum):
    HOME = auto()
    SEARCH = auto()
    REELS = auto()
    ORDERS = auto()
    ACTIVITY = auto()
    PROFILE = auto()


class SearchTabs(Enum):
    TOP = auto()
    ACCOUNTS = auto()
    TAGS = auto()
    PLACES = auto()


class FollowStatus(Enum):
    FOLLOW = auto()
    FOLLOWING = auto()
    FOLLOW_BACK = auto()
    REQUESTED = auto()
    NONE = auto()


class SwipeTo(Enum):
    HALF_PHOTO = auto()
    NEXT_POST = auto()


class LikeMode(Enum):
    SINGLE_CLICK = auto()
    DOUBLE_CLICK = auto()


class MediaType(Enum):
    PHOTO = auto()
    VIDEO = auto()
    REEL = auto()
    IGTV = auto()
    CAROUSEL = auto()
    UNKNOWN = auto()


class Owner(Enum):
    OPEN = auto()
    GET_NAME = auto()
    GET_POSITION = auto()


class TabBarView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def _getTabBar(self):
        return self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.TAB_BAR),
            className=ClassName.LINEAR_LAYOUT,
        )

    def is_tab_bar_visible(self) -> bool:
        """The tab bar is only present on the main screens (home, search, profile, ...)."""
        try:
            if hasattr(self.device, "_ig_is_opened") and not self.device._ig_is_opened():
                return False
            return self._getTabBar().exists(Timeout.SHORT)
        except DeviceFacade.AppHasCrashed:
            return False
        except Exception as e:
            logger.debug(f"is_tab_bar_visible error: {e}")
            return False

    def _escape_subscreens(self, max_attempts: int = 3) -> bool:
        """If the tab bar is not visible because we are stuck in a subscreen,
        attempt to back out to the main screen using back button or device back.
        """
        if self.is_tab_bar_visible():
            return True

        if hasattr(self.device, "_ig_is_opened") and not self.device._ig_is_opened():
            logger.warning(
                "Instagram is not in the foreground during subscreen escape. Restoring via open_instagram()..."
            )
            try:
                from InstaAddict.core.utils import open_instagram

                if open_instagram(self.device):
                    random_sleep(1.0, 2.0, modulable=False)
                    if self.is_tab_bar_visible():
                        logger.info("Tab bar restored after relaunching Instagram.")
                        return True
            except Exception as e:
                logger.debug(f"open_instagram error in _escape_subscreens: {e}")

        logger.info("Tab bar not visible (screen in subscreen). Attempting auto-escape...")
        for attempt in range(1, max_attempts + 1):
            try:
                # Dismiss any blocking modal dialog first
                if UniversalActions.dismiss_dialog(self.device):
                    logger.info(
                        f"Dismissed dialog during subscreen escape (attempt {attempt}/{max_attempts})."
                    )
                    if self.is_tab_bar_visible():
                        logger.info("Tab bar restored after dialog dismissal.")
                        return True

                # Try action bar back button first (least disruptive)
                back_btn = self.device.find(
                    resourceIdMatches=case_insensitive_re(ResourceID.ACTION_BAR_BUTTON_BACK)
                )
                if back_btn.exists(Timeout.SHORT):
                    logger.debug(
                        f"Clicking action bar back button (attempt {attempt}/{max_attempts})..."
                    )
                    back_btn.click()
                else:
                    logger.debug(
                        f"Pressing device back key (attempt {attempt}/{max_attempts})..."
                    )
                    self.device.back()

                random_sleep(0.8, 1.4, modulable=False)
                # Safeguard: if back dropped app into background launcher, restore immediately
                if hasattr(self.device, "_ig_is_opened") and not self.device._ig_is_opened():
                    logger.warning("Instagram dropped to background after back key. Restoring via open_instagram()...")
                    try:
                        from InstaAddict.core.utils import open_instagram

                        open_instagram(self.device)
                        random_sleep(1.0, 2.0, modulable=False)
                    except Exception as e:
                        logger.debug(f"open_instagram recovery failed: {e}")

                if self.is_tab_bar_visible():
                    logger.info(
                        f"Tab bar successfully restored after {attempt} back step(s)."
                    )
                    try:
                        from InstaAddict.core.session_state import SessionState

                        active_session = SessionState.get_active()
                        if active_session:
                            active_session.increment_subscreen_escapes()
                    except Exception:
                        pass
                    return True
            except DeviceFacade.AppHasCrashed:
                logger.warning(
                    f"AppHasCrashed encountered during subscreen escape attempt {attempt}/{max_attempts}. Restoring Instagram..."
                )
                try:
                    from InstaAddict.core.utils import open_instagram

                    open_instagram(self.device)
                    random_sleep(1.5, 2.5, modulable=False)
                    if self.is_tab_bar_visible():
                        return True
                except Exception as e:
                    logger.debug(f"AppHasCrashed relaunch error in _escape_subscreens: {e}")

        logger.warning(
            f"Could not restore tab bar after {max_attempts} escape attempt(s)."
        )
        return False

    def navigateToHome(self):
        self._navigateTo(TabBarTabs.HOME)
        return HomeView(self.device)

    def navigateToSearch(self):
        self._navigateTo(TabBarTabs.SEARCH)
        return SearchView(self.device)

    def navigateToReels(self):
        self._navigateTo(TabBarTabs.REELS)

    def navigateToOrders(self):
        self._navigateTo(TabBarTabs.ORDERS)

    def navigateToActivity(self):
        self._navigateTo(TabBarTabs.ACTIVITY)

    def navigateToProfile(self):
        from InstaAddict.core.telemetry import PerformanceTracker

        with PerformanceTracker.get_instance().measure("view", "profile_load"):
            self._navigateTo(TabBarTabs.PROFILE)
            return ProfileView(self.device, is_own_profile=True)

    def _get_new_profile_position(self) -> Optional[DeviceFacade.View]:
        obj = self.device.find(
            classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
            descriptionMatches=case_insensitive_re(TabBarText.PROFILE_CONTENT_DESC),
        )
        if obj.exists(Timeout.SHORT):
            return obj
        obj = self.device.find(
            descriptionMatches=case_insensitive_re(TabBarText.PROFILE_CONTENT_DESC)
        )
        if obj.exists(Timeout.SHORT):
            return obj
        return None

    def _navigateTo(self, tab: TabBarTabs):
        tab_name = tab.name
        logger.debug(f"Navigate to {tab_name}")
        try:
            from InstaAddict.core.watchdog import record_heartbeat

            record_heartbeat("navigation", f"Navigating to {tab_name}")
        except Exception:
            pass
        button = None
        UniversalActions.close_keyboard(self.device)

        # Ensure tab bar is visible before attempting tab lookup
        try:
            if not self.is_tab_bar_visible():
                self._escape_subscreens()
        except DeviceFacade.AppHasCrashed:
            from InstaAddict.core.utils import open_instagram

            logger.warning(
                f"AppHasCrashed during navigateTo({tab_name}). Relaunching Instagram..."
            )
            open_instagram(self.device)
            random_sleep(1.5, 2.5, modulable=False)
            self._escape_subscreens()

        if tab == TabBarTabs.HOME:
            button = self.device.find(resourceIdMatches=ResourceID.FEED_TAB)
            if not button.exists():
                button = self.device.find(
                    classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                    descriptionMatches=case_insensitive_re(TabBarText.HOME_CONTENT_DESC),
                )

        elif tab == TabBarTabs.SEARCH:
            button = self.device.find(resourceIdMatches=ResourceID.SEARCH_TAB)
            if not button.exists():
                button = self.device.find(
                    classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                    descriptionMatches=case_insensitive_re(TabBarText.SEARCH_CONTENT_DESC),
                )

            if not button.exists():
                # If still not found, check if we are stuck on a subscreen and attempt escape
                if not self.is_tab_bar_visible():
                    self._escape_subscreens()
                    button = self.device.find(resourceIdMatches=ResourceID.SEARCH_TAB)
                    if not button.exists():
                        button = self.device.find(
                            classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                            descriptionMatches=case_insensitive_re(TabBarText.SEARCH_CONTENT_DESC),
                        )

            if not button.exists():
                # Some accounts display the search btn only in Home -> action bar
                logger.debug("Didn't find search in the tab bar...")
                home_view = self.navigateToHome()
                search_view = home_view.navigateToSearch()
                if search_view is not None:
                    return

        elif tab == TabBarTabs.REELS:
            button = self.device.find(resourceIdMatches=ResourceID.CLIPS_TAB)
            if not button.exists():
                button = self.device.find(
                    classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                    descriptionMatches=case_insensitive_re(TabBarText.REELS_CONTENT_DESC),
                )

        elif tab == TabBarTabs.ORDERS:
            button = self.device.find(
                classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                descriptionMatches=case_insensitive_re(TabBarText.ORDERS_CONTENT_DESC),
            )

        elif tab == TabBarTabs.ACTIVITY:
            button = self.device.find(
                classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                descriptionMatches=case_insensitive_re(
                    TabBarText.ACTIVITY_CONTENT_DESC
                ),
            )

        elif tab == TabBarTabs.PROFILE:
            button = self.device.find(resourceIdMatches=ResourceID.PROFILE_TAB)
            if not button.exists():
                button = self.device.find(
                    classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                    descriptionMatches=case_insensitive_re(TabBarText.PROFILE_CONTENT_DESC),
                )
            if not button.exists():
                button = self._get_new_profile_position()

        if button is None or not button.exists(Timeout.MEDIUM):
            # Attempt popup dismissal and retry before failing (CO-032 / F-05)
            if UniversalActions.dismiss_dialog(self.device):
                logger.info(f"Dismissed popup during navigation to {tab_name}. Retrying tab lookup...")
            if not self.is_tab_bar_visible():
                self._escape_subscreens()
            if tab == TabBarTabs.PROFILE:
                button = self.device.find(resourceIdMatches=ResourceID.PROFILE_TAB)
                if not button.exists():
                    button = self.device.find(
                        classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                        descriptionMatches=case_insensitive_re(TabBarText.PROFILE_CONTENT_DESC),
                    )
                if not button.exists():
                    button = self._get_new_profile_position()
            elif tab == TabBarTabs.HOME:
                button = self.device.find(resourceIdMatches=ResourceID.FEED_TAB)
                if not button.exists():
                    button = self.device.find(
                        classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                        descriptionMatches=case_insensitive_re(TabBarText.HOME_CONTENT_DESC),
                    )
            elif tab == TabBarTabs.SEARCH:
                button = self.device.find(resourceIdMatches=ResourceID.SEARCH_TAB)
                if not button.exists():
                    button = self.device.find(
                        classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                        descriptionMatches=case_insensitive_re(TabBarText.SEARCH_CONTENT_DESC),
                    )
            elif tab == TabBarTabs.REELS:
                button = self.device.find(resourceIdMatches=ResourceID.CLIPS_TAB)
                if not button.exists():
                    button = self.device.find(
                        classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                        descriptionMatches=case_insensitive_re(TabBarText.REELS_CONTENT_DESC),
                    )
            elif tab == TabBarTabs.ORDERS:
                button = self.device.find(
                    classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                    descriptionMatches=case_insensitive_re(TabBarText.ORDERS_CONTENT_DESC),
                )
            elif tab == TabBarTabs.ACTIVITY:
                button = self.device.find(
                    classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
                    descriptionMatches=case_insensitive_re(
                        TabBarText.ACTIVITY_CONTENT_DESC
                    ),
                )

        if button is not None and button.exists(Timeout.MEDIUM):
            # Two clicks to reset tab content
            button.click(sleep=SleepTime.SHORT)
            if tab is not TabBarTabs.PROFILE:
                button.click(sleep=SleepTime.SHORT)
            return

        logger.error(f"Didn't find tab {tab_name} in the tab bar...")


class ActionBarView:
    def __init__(self, device: DeviceFacade):
        self.device = device
        try:
            self.action_bar = self._getActionBar()
        except DeviceFacade.AppHasCrashed:
            self.action_bar = None

    def _getActionBar(self):
        try:
            return self.device.find(
                resourceIdMatches=case_insensitive_re(ResourceID.ACTION_BAR_CONTAINER),
                className=ClassName.FRAME_LAYOUT,
            )
        except DeviceFacade.AppHasCrashed:
            return None


class HomeView(ActionBarView):
    def __init__(self, device: DeviceFacade):
        super().__init__(device)
        self.device = device

    def navigateToSearch(self):
        logger.debug("Navigate to Search")
        if self.action_bar is None:
            self.action_bar = self._getActionBar()
        if self.action_bar is None:
            logger.warning("Search icon not found in Home action bar.")
            return None
        search_btn = self.action_bar.child(
            descriptionMatches=case_insensitive_re(TabBarText.SEARCH_CONTENT_DESC)
        )
        if not search_btn.exists(Timeout.SHORT):
            logger.warning("Search icon not found in Home action bar.")
            return None
        try:
            search_btn.click()
        except (DeviceFacade.JsonRpcError, Exception) as e:
            logger.warning(
                f"Failed clicking search icon in Home action bar: {e}. Falling back to TabBar search."
            )
            return None

        return SearchView(self.device)


class HashTagView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def _getRecyclerView(self):
        obj = self.device.find(resourceIdMatches=ResourceID.RECYCLER_VIEW)
        if obj.exists(Timeout.LONG):
            logger.debug("RecyclerView exists.")
        else:
            logger.debug("RecyclerView doesn't exists.")
        return obj

    def _getFirstImageView(self, recycler):
        obj = recycler.child(
            resourceIdMatches=ResourceID.IMAGE_BUTTON,
        )
        if not obj.exists():
            obj = recycler.child(
                className=ClassName.IMAGE_VIEW,
            )
        if obj.exists(Timeout.LONG):
            logger.debug("First image in view exists.")
        else:
            logger.debug("First image in view doesn't exists.")
        return obj

    _getFistImageView = _getFirstImageView

    def _getRecentTab(self):
        obj = self.device.find(
            classNameMatches=ClassName.BUTTON_OR_TEXTVIEW_REGEX,
            textMatches=case_insensitive_re(r"^(Recent|Recent top posts)$"),
        )
        if not obj.exists(Timeout.SHORT):
            obj = self.device.find(
                descriptionMatches=case_insensitive_re(r"^(Recent|Recent top posts)$"),
            )
        if not obj.exists(Timeout.SHORT):
            obj = self.device.find(
                className=ClassName.TEXT_VIEW,
                textMatches=case_insensitive_re(TabBarText.RECENT_CONTENT_DESC),
            )
        if obj.exists(Timeout.SHORT):
            logger.debug("Recent Tab exists.")
        else:
            logger.debug("Recent Tab doesn't exist.")
        return obj


# The place view for the moment It's only a copy/paste of HashTagView
# Maybe we can add the com.instagram.android:id/category_name == "Country/Region" (or other obv)


class PlacesView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def _getRecyclerView(self):
        obj = self.device.find(resourceIdMatches=ResourceID.RECYCLER_VIEW)
        if obj.exists(Timeout.LONG):
            logger.debug("RecyclerView exists.")
        else:
            logger.debug("RecyclerView doesn't exists.")
        return obj

    def _getFirstImageView(self, recycler):
        obj = recycler.child(
            resourceIdMatches=ResourceID.IMAGE_BUTTON,
        )
        if not obj.exists():
            obj = recycler.child(
                className=ClassName.IMAGE_VIEW,
            )
        if obj.exists(Timeout.LONG):
            logger.debug("First image in view exists.")
        else:
            logger.debug("First image in view doesn't exists.")
        return obj

    _getFistImageView = _getFirstImageView

    def _getRecentTab(self):
        obj = self.device.find(
            classNameMatches=ClassName.BUTTON_OR_TEXTVIEW_REGEX,
            textMatches=case_insensitive_re(r"^(Recent|Recent top posts)$"),
        )
        if not obj.exists(Timeout.SHORT):
            obj = self.device.find(
                descriptionMatches=case_insensitive_re(r"^(Recent|Recent top posts)$"),
            )
        if not obj.exists(Timeout.SHORT):
            obj = self.device.find(
                className=ClassName.TEXT_VIEW,
                textMatches=case_insensitive_re(TabBarText.RECENT_CONTENT_DESC),
            )
        return obj

    def _getInformBody(self):
        return self.device.find(
            className=ClassName.TEXT_VIEW,
            resourceId=ResourceID.INFORM_BODY,
        )


class SearchView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def _getSearchEditText(self):
        for _ in range(2):
            obj = self.device.find(
                resourceIdMatches=case_insensitive_re(
                    ResourceID.ACTION_BAR_SEARCH_EDIT_TEXT
                ),
            )
            if obj.exists(Timeout.LONG):
                return obj
            logger.error(
                "Can't find the search bar! Refreshing it by pressing Home and Search again.."
            )
            UniversalActions.close_keyboard(self.device)
            TabBarView(self.device).navigateToHome()
            TabBarView(self.device).navigateToSearch()
        logger.error("Can't find the search bar!")
        return None

    def _getUsernameRow(self, username):
        return self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.ROW_SEARCH_USER_USERNAME),
            className=ClassName.TEXT_VIEW,
            textMatches=case_insensitive_re(username),
        )

    def _getHashtagRow(self, hashtag):
        return self.device.find(
            resourceIdMatches=case_insensitive_re(
                ResourceID.ROW_HASHTAG_TEXTVIEW_TAG_NAME
            ),
            className=ClassName.TEXT_VIEW,
            text=f"#{hashtag}",
        )

    def _getPlaceRow(self):
        obj = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.ROW_PLACE_TITLE),
        )
        obj.wait(Timeout.MEDIUM)
        return obj

    def _getTabTextView(self, tab: SearchTabs):
        tab_layout = self.device.find(
            resourceIdMatches=case_insensitive_re(
                ResourceID.FIXED_TABBAR_TABS_CONTAINER
            ),
        )
        if tab_layout.exists():
            logger.debug("Tabs container exists!")
            tab_text_view = tab_layout.child(
                resourceIdMatches=case_insensitive_re(ResourceID.TAB_BUTTON_NAME_TEXT),
                textMatches=case_insensitive_re(tab.name),
            )
            if not tab_text_view.exists():
                logger.debug("Tabs container hasn't text! Let's try with description.")
                for obj in tab_layout.child():
                    if obj.ui_info()["contentDescription"].upper() == tab.name.upper():
                        tab_text_view = obj
                        break
            return tab_text_view
        return None

    def _searchTabWithTextPlaceholder(self, tab: SearchTabs):
        tab_layout = self.device.find(
            resourceIdMatches=case_insensitive_re(
                ResourceID.FIXED_TABBAR_TABS_CONTAINER
            ),
        )
        search_edit_text = self._getSearchEditText()

        fixed_text = "Search {}".format(tab.name if tab.name != "TAGS" else "hashtags")
        logger.debug(
            "Going to check if the search bar have as placeholder: {}".format(
                fixed_text
            )
        )

        for item in tab_layout.child(
            resourceId=ResourceID.TAB_BUTTON_FALLBACK_ICON,
            className=ClassName.IMAGE_VIEW,
        ):
            item.click()

            # Little trick for force-update the ui and placeholder text
            if search_edit_text is not None:
                search_edit_text.click()

            if self.device.find(
                className=ClassName.TEXT_VIEW,
                textMatches=case_insensitive_re(fixed_text),
            ).exists():
                return item
        return None

    def navigate_to_target(self, target: str, job: str) -> bool:
        from InstaAddict.core.telemetry import PerformanceTracker

        with PerformanceTracker.get_instance().measure("view", "search_query"):
            target = emoji.emojize(target, use_aliases=True)
            logger.info(f"Navigate to {target}")
            try:
                from InstaAddict.core.watchdog import record_heartbeat

                record_heartbeat("search_navigation", f"Searching for {target}")
            except Exception:
                pass
            search_edit_text = self._getSearchEditText()
            if search_edit_text is not None:
                logger.debug("Pressing on searchbar.")
                try:
                    search_edit_text.click(sleep=SleepTime.SHORT)
                except (DeviceFacade.JsonRpcError, Exception) as e:
                    logger.warning(
                        f"Transient error pressing searchbar: {e}. Retrying after searchbar refresh..."
                    )
                    search_edit_text = self._getSearchEditText()
                    if search_edit_text is not None:
                        try:
                            search_edit_text.click(sleep=SleepTime.SHORT)
                        except Exception as e2:
                            logger.error(f"Cannot click searchbar on retry: {e2}")
                            return False
                    else:
                        return False
            else:
                logger.debug("There is no searchbar!")
                return False
            if self._check_current_view(target, job):
                logger.info(f"{target} is in recent history.")
                return True
            try:
                search_edit_text.set_text(
                    target,
                    Mode.PASTE,
                )
            except (DeviceFacade.JsonRpcError, Exception) as e:
                logger.warning(f"Error pasting search text for {target}: {e}")
                return False
            if self._check_current_view(target, job):
                logger.info(f"{target} is in top view.")
                return True
            echo_text = self.device.find(resourceId=ResourceID.ECHO_TEXT)
            if echo_text.exists(Timeout.SHORT):
                logger.debug("Pressing on see all results.")
                echo_text.click()
            # at this point we have the tabs available
            self._switch_to_target_tag(job)
            if self._check_current_view(target, job, in_place_tab=True):
                return True
            return False

    def _switch_to_target_tag(self, job: str):
        if "place" in job:
            tab = SearchTabs.PLACES
        elif "hashtag" in job:
            tab = SearchTabs.TAGS
        else:
            tab = SearchTabs.ACCOUNTS

        obj = self._getTabTextView(tab)
        if obj is not None:
            logger.info(f"Switching to {tab.name}")
            obj.click()

    def _check_current_view(
        self, target: str, job: str, in_place_tab: bool = False
    ) -> bool:
        if "place" in job:
            if not in_place_tab:
                return False
            else:
                obj = self._getPlaceRow()
        else:
            obj = self.device.find(
                text=target,
                resourceIdMatches=ResourceID.SEARCH_ROW_ITEM,
            )
            if not obj.exists():
                obj = self.device.find(
                    text=target,
                    className=ClassName.TEXT_VIEW,
                )
            if not obj.exists():
                obj = self.device.find(
                    description=target,
                )
            if not obj.exists() and target.startswith("#"):
                clean_tag = target[1:]
                tag_obj = self.device.find(
                    text=clean_tag,
                    className=ClassName.TEXT_VIEW,
                )
                if tag_obj.exists():
                    obj = tag_obj
        if obj.exists():
            obj.click()
            return True
        return False


class PostsViewList:
    def __init__(self, device: DeviceFacade):
        self.device = device
        self.has_tags = False

    def swipe_to_fit_posts(self, swipe: SwipeTo):
        """calculate the right swipe amount necessary to swipe to next post in hashtag post view
        in order to make it available to other plug-ins I cut it in two moves"""
        displayWidth = self.device.get_info()["displayWidth"]
        displayHeight = self.device.get_info()["displayHeight"]
        containers_content = ResourceID.MEDIA_CONTAINER
        containers_gap = ResourceID.GAP_VIEW_AND_FOOTER_SPACE

        # move type: half photo
        if swipe == SwipeTo.HALF_PHOTO:
            media_bounds = self._get_current_media_bounds(containers_content)
            if media_bounds is None:
                logger.debug("Can't find media bounds, using screen fallback.")
                media_bounds = {
                    "top": displayHeight * 0.25,
                    "bottom": displayHeight * 0.75,
                }
            zoomable_view_container = media_bounds["bottom"]
            ac_exists, _, ac_bottom = PostsViewList(
                self.device
            )._get_action_bar_position()
            if ac_exists and zoomable_view_container < ac_bottom:
                zoomable_view_container += ac_bottom
            self.device.swipe_points(
                displayWidth / 2,
                zoomable_view_container - 5,
                displayWidth / 2,
                zoomable_view_container * 0.5,
            )
        elif swipe == SwipeTo.NEXT_POST:
            logger.info(
                "Scroll down to see next post.", extra={"color": f"{Fore.GREEN}"}
            )
            # Check if currently inside the Reels / Clips viewer
            is_clips = False
            try:
                clips_viewer = self.device.find(
                    resourceIdMatches=case_insensitive_re(
                        f"{ResourceID.ROOT_CLIPS_LAYOUT}|{ResourceID.CLIPS_VIEWER_CONTAINER}|{ResourceID.CLIPS_VIEWER_VIEW_PAGER}|{ResourceID.CLIPS_VIDEO_CONTAINER}"
                    )
                )
                if clips_viewer.exists():
                    is_clips = True
            except Exception:
                is_clips = False

            if is_clips:
                logger.debug("Reels viewer detected: executing fluid full-page vertical swipe.")
                start_y = int(displayHeight * 0.80)
                end_y = int(displayHeight * 0.20)
                self.device.swipe_points(
                    displayWidth / 2,
                    start_y,
                    displayWidth / 2,
                    end_y,
                )
                return True

            gap_view_obj = self.device.find(index=-1, resourceIdMatches=containers_gap)
            obj1 = None
            if gap_view_obj.exists():
                obj1 = gap_view_obj.get_bounds()["bottom"]
            else:
                fallback_media_bounds = self._get_current_media_bounds(
                    containers_content
                )
                obj1 = (
                    fallback_media_bounds["bottom"]
                    if fallback_media_bounds
                    else displayHeight * 0.75
                )

            media_bounds = self._get_current_media_bounds(containers_content)
            if media_bounds is None:
                logger.debug("Can't find media bounds, using screen fallback.")
                media_bounds = {
                    "top": displayHeight * 0.25,
                    "bottom": displayHeight * 0.75,
                }

            ac_exists, _, ac_bottom = PostsViewList(
                self.device
            )._get_action_bar_position()
            if ac_exists:
                obj2 = ac_bottom + 20
            else:
                obj2 = media_bounds["top"] if media_bounds else displayHeight * 0.25

            if (obj1 - obj2) < (displayHeight * 0.4):
                logger.debug(
                    f"Calculated swipe distance {obj1 - obj2} is too small. Overriding to prevent snap-back."
                )
                obj1 = displayHeight * 0.8
                obj2 = displayHeight * 0.2

            self.device.swipe_points(
                displayWidth / 2,
                obj1 - 5,
                displayWidth / 2,
                obj2 + 5,
            )
            return True

    def _get_current_media_bounds(self, legacy_media_selector) -> Optional[dict]:
        try:
            media = self.device.find(resourceIdMatches=legacy_media_selector)
            if media.exists() or media.count_items() >= 1:
                return media.get_bounds()
        except Exception as e:
            logger.debug(f"Legacy media bounds lookup failed: {e}")

        try:
            root = ET.fromstring(self.device.deviceV2.dump_hierarchy())
        except Exception as e:
            logger.debug(f"Can't parse UI hierarchy while looking for media: {e}")
            return None

        media_ids = set(ResourceID.MEDIA_CONTAINER.split("|"))
        media_ids.update(ResourceID.CAROUSEL_AND_MEDIA_GROUP.split("|"))
        media_ids.update(
            {
                ResourceID.MEDIA_GROUP,
                ResourceID.VIDEO_CONTAINER,
                f"{configs.args.app_id}:id/row_feed_photo_imageview",
                ResourceID.REEL_VIEWER_MEDIA_CONTAINER,
            }
        )
        display_height = self.device.get_info()["displayHeight"]
        display_width = self.device.get_info()["displayWidth"]

        nodes = []
        for node in root.iter("node"):
            if node.attrib.get("package") != configs.args.app_id:
                continue
            if node.attrib.get("visible-to-user") != "true":
                continue
            bounds = PostsViewList._bounds_from_xml_node(node)
            if bounds is None:
                continue
            nodes.append(
                {
                    "bounds": bounds,
                    "resource_id": node.attrib.get("resource-id", ""),
                    "desc": PostsViewList._normalize_ig_text(
                        node.attrib.get("content-desc")
                    ),
                }
            )

        button_rows = sorted(
            (
                item
                for item in nodes
                if item["resource_id"] == ResourceID.ROW_FEED_VIEW_GROUP_BUTTONS
            ),
            key=lambda item: item["bounds"]["top"],
        )
        media_candidates = []
        for item in nodes:
            bounds = item["bounds"]
            width = bounds["right"] - bounds["left"]
            height = bounds["bottom"] - bounds["top"]
            if width < display_width * 0.5 or height < display_height * 0.08:
                continue
            desc = item["desc"].casefold()
            looks_like_media = (
                item["resource_id"] in media_ids
                or " likes" in desc
                or " comments" in desc
                or desc.startswith(("photo ", "reel by", "video by"))
            )
            if looks_like_media:
                media_candidates.append(item)

        if not media_candidates:
            return None

        for button_row in button_rows:
            row_top = button_row["bounds"]["top"]
            candidates_above_buttons = [
                item
                for item in media_candidates
                if item["bounds"]["top"] < row_top
                and item["bounds"]["bottom"] <= row_top + 4
            ]
            if candidates_above_buttons:
                return max(
                    candidates_above_buttons,
                    key=lambda item: (
                        item["bounds"]["bottom"] - item["bounds"]["top"],
                        item["bounds"]["right"] - item["bounds"]["left"],
                    ),
                )["bounds"]

        visible_candidates = [
            item
            for item in media_candidates
            if 0
            <= (item["bounds"]["top"] + item["bounds"]["bottom"]) / 2
            <= display_height
        ]
        if not visible_candidates:
            visible_candidates = media_candidates
        return max(
            visible_candidates,
            key=lambda item: (
                item["bounds"]["bottom"] - item["bounds"]["top"],
                -(item["bounds"]["top"]),
            ),
        )["bounds"]

    def _find_likers_container(self):
        # In full-screen Reels viewer, bypass feed likers search and downward swipes
        is_reel = self.device.find(
            resourceIdMatches=f"{ResourceID.CLIPS_VIEWER_CONTAINER}|{ResourceID.ROOT_CLIPS_LAYOUT}|{ResourceID.CLIPS_AUTHOR_USERNAME}"
        ).exists()
        if is_reel:
            logger.debug("In Reels viewer: bypassing feed likers container search.")
            return False, -1

        universal_actions = UniversalActions(self.device)
        containers_gap = ResourceID.GAP_VIEW_AND_FOOTER_SPACE
        media_container = ResourceID.MEDIA_CONTAINER
        likes = 0
        for _ in range(4):
            gap_view_obj = self.device.find(resourceIdMatches=containers_gap)
            likes_view = self.device.find(
                index=-1,
                resourceId=ResourceID.ROW_FEED_TEXTVIEW_LIKES,
                className=ClassName.TEXT_VIEW,
            )
            description_view = self.device.find(
                resourceIdMatches=ResourceID.ROW_FEED_COMMENT_TEXTVIEW_LAYOUT
            )
            media = self.device.find(
                resourceIdMatches=media_container,
            )
            try:
                media_count = media.count_items()
            except Exception:
                media_count = 0
            logger.debug(f"I can see {media_count} media(s) in this view..")
            try:
                media_bounds = media.get_bounds() if media_count > 0 else None
            except Exception as e:
                logger.debug(f"Legacy media bounds lookup failed: {e}")
                media_bounds = None
            if media_bounds is None:
                media_bounds = self._get_current_media_bounds(media_container)
                if media_bounds is not None:
                    logger.debug("Using compatibility media bounds.")

            if (
                media_count > 1
                and media_bounds
                and (
                    media_bounds["bottom"] < self.device.get_info()["displayHeight"] / 3
                )
            ):
                universal_actions._swipe_points(Direction.DOWN, delta_y=100)
                continue
            if not likes_view.exists():
                likes_fallback = self._get_current_likers_info()
                if likes_fallback is not None:
                    logger.debug("Likers container found in compatibility hierarchy.")
                    return True, self._get_number_of_likers_from_text(
                        likes_fallback["text"]
                    )
                if description_view.exists() or gap_view_obj.exists():
                    return False, likes
                else:
                    universal_actions._swipe_points(Direction.DOWN, delta_y=100)
                    continue
            elif (
                media_bounds
                and media_bounds["bottom"] > likes_view.get_bounds()["bottom"]
            ):
                universal_actions._swipe_points(Direction.DOWN, delta_y=100)
                continue
            logger.debug("Likers container exists!")
            likes = self._get_number_of_likers(likes_view)
            return likes_view.exists(), likes
        return False, 0

    def _get_current_likers_info(self) -> Optional[dict]:
        try:
            root = ET.fromstring(self.device.deviceV2.dump_hierarchy())
        except Exception as e:
            logger.debug(f"Can't parse UI hierarchy while looking for likers: {e}")
            return None

        nodes = []
        for node in root.iter("node"):
            if node.attrib.get("package") != configs.args.app_id:
                continue
            if node.attrib.get("visible-to-user") != "true":
                continue
            bounds = PostsViewList._bounds_from_xml_node(node)
            if bounds is None:
                continue
            nodes.append(
                {
                    "bounds": bounds,
                    "resource_id": node.attrib.get("resource-id", ""),
                    "text": PostsViewList._normalize_ig_text(node.attrib.get("text")),
                }
            )

        button_rows = sorted(
            (
                item
                for item in nodes
                if item["resource_id"] == ResourceID.ROW_FEED_VIEW_GROUP_BUTTONS
            ),
            key=lambda item: item["bounds"]["top"],
        )
        if not button_rows:
            return None

        likers = []
        for item in nodes:
            text = item["text"]
            if not text:
                continue
            text_lower = text.casefold()
            if (
                text_lower.startswith("liked by ")
                or re.search(r"\b\d[\d,.kmb]*\s+likes?\b", text_lower)
                or text_lower.endswith(" others")
            ):
                likers.append(item)

        for button_row in button_rows:
            row_bottom = button_row["bounds"]["bottom"]
            candidates = [
                item
                for item in likers
                if row_bottom <= item["bounds"]["top"] <= row_bottom + 120
            ]
            if candidates:
                return min(candidates, key=lambda item: item["bounds"]["top"])
        return None

    def _get_number_of_likers_from_text(self, likes_view_text):
        likes = 0
        likes_view_text = PostsViewList._normalize_ig_text(likes_view_text).replace(
            ",", ""
        )
        matches_likes = re.search(
            r"(?P<likes>\d+) (?:others|likes)", likes_view_text, re.IGNORECASE
        )
        matches_view = re.search(
            r"(?P<views>\d+) views", likes_view_text, re.IGNORECASE
        )
        if hasattr(matches_likes, "group"):
            likes = int(matches_likes.group("likes"))
            logger.info(
                f"This post has {likes if 'likes' in likes_view_text else likes + 1} like(s)."
            )
            return likes
        if hasattr(matches_view, "group"):
            views = int(matches_view.group("views"))
            logger.info(
                f"I can see only that this post has {views} views(s). It may contain likes.."
            )
            return -1
        if likes_view_text.endswith("others"):
            logger.info("This post has more than 1 like.")
            return -1
        logger.info("This post has only 1 like.")
        return 1

    def _get_number_of_likers(self, likes_view):
        likes = 0
        if likes_view.exists():
            return self._get_number_of_likers_from_text(likes_view.get_text())
        else:
            logger.info("This post has no likes, skip.")
            return likes

    def open_likers_container(self):
        """Open likes container"""
        post_liked_by_a_following = False
        logger.info("Opening post likers.")
        facepil_stub = self.device.find(
            index=-1, resourceId=ResourceID.ROW_FEED_LIKE_COUNT_FACEPILE_STUB
        )

        if facepil_stub.exists():
            logger.debug("Facepile present, pressing on it!")
            facepil_stub.click()
        else:
            random_sleep(1, 2, modulable=False)
            likes_view = self.device.find(
                index=-1,
                resourceId=ResourceID.ROW_FEED_TEXTVIEW_LIKES,
                className=ClassName.TEXT_VIEW,
            )
            if not likes_view.exists():
                likes_fallback = self._get_current_likers_info()
                if likes_fallback is not None:
                    bounds = likes_fallback["bounds"]
                    logger.debug(f"[DEBUG likers click - compat path] bounds={bounds}")
                    right_edge_point = (
                        bounds["right"] - 15,
                        int((bounds["top"] + bounds["bottom"]) / 2),
                    )
                    self.device.deviceV2.click(*right_edge_point)
                    DeviceFacade.sleep_mode(SleepTime.DEFAULT)
                    return
            if " Liked by" in likes_view.get_text():
                post_liked_by_a_following = True
            elif likes_view.child().count_items() < 2:
                likes_view.click()
                return
            if likes_view.child().exists():
                foil = likes_view.get_bounds()
                # The avatar ("child") sits near the start of the text, and the
                # username right after it is its own clickable span whose exact
                # bounds we can't see via accessibility. Avoiding just the avatar
                # isn't enough -- clicking near the right edge lands past both the
                # avatar and the username link, on "...and X others" instead.
                hole = likes_view.child().get_bounds()
                text = likes_view.get_text()
                logger.debug(
                    f"[DEBUG likers click] text='{text}' | foil={foil} | hole={hole}"
                )
                right_edge_point = (
                    foil["right"] - 15,
                    int((foil["top"] + foil["bottom"]) / 2),
                )
                likes_view.click(Location.CUSTOM, coord=right_edge_point)
                return
            elif not post_liked_by_a_following:
                likes_view.click(Location.RIGHT)
            else:
                likes_view.click(Location.LEFT)

    def _has_tags(self) -> bool:
        tags_icon = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.INDICATOR_ICON_VIEW)
        )
        self.has_tags = tags_icon.exists()
        return self.has_tags

    @staticmethod
    def _bounds_from_xml_node(node):
        bounds = node.attrib.get("bounds", "")
        matches = re.findall(r"\d+", bounds)
        if len(matches) != 4:
            return None
        left, top, right, bottom = map(int, matches)
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
        }

    @staticmethod
    def _normalize_ig_text(text):
        return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()

    @staticmethod
    def _node_has_owner_child(node, username):
        username = PostsViewList._normalize_ig_text(username)
        for child in node.iter("node"):
            if child is node:
                continue
            if (
                PostsViewList._normalize_ig_text(child.attrib.get("content-desc"))
                == username
            ):
                return True
        return False

    @staticmethod
    def _is_caption_text_node(node, username):
        username = PostsViewList._normalize_ig_text(username)
        text = PostsViewList._normalize_ig_text(node.attrib.get("text"))
        if not text.startswith(f"{username} "):
            return False
        resource_id = node.attrib.get("resource-id", "")
        if resource_id in (
            ResourceID.ROW_FEED_PHOTO_PROFILE_NAME,
            ResourceID.ROW_FEED_PROFILE_HEADER,
        ):
            return False
        if node.attrib.get("class", "") == ClassName.BUTTON:
            return False
        return PostsViewList._node_has_owner_child(node, username)

    def _find_caption_text_in_current_post(self, username) -> Optional[str]:
        username = PostsViewList._normalize_ig_text(username)
        media_ids = set(ResourceID.MEDIA_CONTAINER.split("|"))
        try:
            root = ET.fromstring(self.device.deviceV2.dump_hierarchy())
        except Exception as e:
            logger.debug(f"Can't parse UI hierarchy while looking for caption: {e}")
            return None

        nodes = []
        for node in root.iter("node"):
            bounds = PostsViewList._bounds_from_xml_node(node)
            if bounds is None or node.attrib.get("visible-to-user") != "true":
                continue
            nodes.append(
                {
                    "node": node,
                    "bounds": bounds,
                    "resource_id": node.attrib.get("resource-id", ""),
                    "text": PostsViewList._normalize_ig_text(node.attrib.get("text")),
                    "desc": PostsViewList._normalize_ig_text(
                        node.attrib.get("content-desc")
                    ),
                }
            )

        headers = sorted(
            (
                item
                for item in nodes
                if item["resource_id"] == ResourceID.ROW_FEED_PROFILE_HEADER
            ),
            key=lambda item: item["bounds"]["top"],
        )
        button_rows = sorted(
            (
                item
                for item in nodes
                if item["resource_id"] == ResourceID.ROW_FEED_VIEW_GROUP_BUTTONS
            ),
            key=lambda item: item["bounds"]["top"],
        )
        captions = sorted(
            (
                item
                for item in nodes
                if PostsViewList._is_caption_text_node(item["node"], username)
            ),
            key=lambda item: item["bounds"]["top"],
        )

        for button_row in reversed(button_rows):
            next_header_top = min(
                (
                    header["bounds"]["top"]
                    for header in headers
                    if header["bounds"]["top"] > button_row["bounds"]["bottom"]
                ),
                default=self.device.get_info()["displayHeight"] + 1,
            )
            for caption in captions:
                caption_top = caption["bounds"]["top"]
                if button_row["bounds"]["bottom"] <= caption_top < next_header_top:
                    logger.debug("Description found in resource-id-less caption node.")
                    return caption["text"]

        current_headers = [
            header
            for header in headers
            if username in header["desc"] or username in header["text"]
        ]
        for header in reversed(current_headers):
            next_header_top = min(
                (
                    other["bounds"]["top"]
                    for other in headers
                    if other["bounds"]["top"] > header["bounds"]["top"]
                ),
                default=self.device.get_info()["displayHeight"] + 1,
            )
            has_media = any(
                item["resource_id"] in media_ids
                and header["bounds"]["top"] <= item["bounds"]["top"] < next_header_top
                for item in nodes
            )
            if not has_media:
                continue
            for caption in captions:
                if (
                    header["bounds"]["top"]
                    <= caption["bounds"]["top"]
                    < next_header_top
                ):
                    logger.debug("Description found in current post hierarchy.")
                    return caption["text"]
        return None

    @staticmethod
    def _clean_trailing_more(text: str) -> str:
        if not text:
            return ""
        s = text.strip()
        return re.sub(r"(\s*\.{2,}\s*more|\s+more)$", "", s, flags=re.IGNORECASE).strip()

    def _find_reels_caption_from_hierarchy(self, username: Optional[str] = None) -> Optional[str]:
        """Inspects UI XML hierarchy to extract Reels caption text when direct element lookups fail."""
        try:
            root = ET.fromstring(self.device.deviceV2.dump_hierarchy())
        except Exception as e:
            logger.debug(f"Can't parse UI hierarchy for Reels caption: {e}")
            return None

        clean_user = (PostsViewList._normalize_ig_text(username) or "").lstrip("@").lower()
        caption_candidates = []

        for node in root.iter("node"):
            bounds = PostsViewList._bounds_from_xml_node(node)
            if bounds is None or node.attrib.get("visible-to-user") != "true":
                continue

            res_id = (node.attrib.get("resource-id", "") or "").lower()
            cls_name = (node.attrib.get("class", "") or "").lower()
            text = PostsViewList._normalize_ig_text(node.attrib.get("text"))
            desc = PostsViewList._normalize_ig_text(node.attrib.get("content-desc"))
            content = text or desc
            if not content:
                continue

            # Skip button widgets, numbers, timestamps, system UI, or author username itself
            if "button" in cls_name and "textview" not in cls_name:
                continue
            if clean_user and content.lower() == clean_user:
                continue
            if re.match(r"^\d+([.,]\d+)?[kmb]?$", content, flags=re.IGNORECASE):
                continue
            if re.match(r"^\d+\s*(s|m|h|d|w)$", content, flags=re.IGNORECASE):
                continue

            # Prioritize nodes matching known Reels caption resource IDs
            is_caption_id = any(
                term in res_id
                for term in [
                    "clips_caption",
                    "clips_viewer_caption",
                    "video_caption",
                    "reel_viewer_title",
                    "expandable_text",
                ]
            )

            # Check if within bottom-left viewport typical of Reels caption area
            try:
                disp_h = self.device.get_info()["displayHeight"]
                disp_w = self.device.get_info()["displayWidth"]
            except Exception:
                disp_h = 2400
                disp_w = 1080

            in_reels_area = (
                bounds["top"] >= disp_h * 0.4
                and bounds["bottom"] <= disp_h * 0.98
                and bounds["left"] <= disp_w * 0.85
            )

            if is_caption_id or in_reels_area:
                cleaned = PostsViewList._clean_trailing_more(content)
                if cleaned and len(cleaned) > 2:
                    caption_candidates.append({
                        "text": cleaned,
                        "is_id_match": is_caption_id,
                        "top": bounds["top"],
                        "len": len(cleaned),
                    })

        if not caption_candidates:
            return None

        # Sort: priority to explicit ID match, then by text length (captions are longer than metadata)
        caption_candidates.sort(key=lambda c: (not c["is_id_match"], -c["len"]))
        return caption_candidates[0]["text"]

    def _check_if_last_post(
        self, last_description, current_job
    ) -> Tuple[bool, str, str, bool, bool, bool]:
        """check if that post has been just interacted"""
        universal_actions = UniversalActions(self.device)
        username, is_ad, is_hashtag = self._post_owner(
            current_job, Owner.GET_NAME
        )
        username = PostsViewList._normalize_ig_text(username)
        has_tags = self._has_tags()
        if is_ad:
            logger.info("Advertisement detected in current post.")
            return False, "", "", True, is_hashtag, has_tags
        if not username or username == "False" or len(username.strip()) == 0:
            logger.info("No valid post author found. Skipping as unsupported.")
            return False, "", "", False, is_hashtag, has_tags

        # Check Reels caption component if on a Reel
        clips_caption = self.device.find(
            resourceIdMatches=ResourceID.CLIPS_CAPTION_COMPONENT
        )
        is_on_reel = (
            (isinstance(current_job, str) and "reels" in current_job.lower())
            or clips_caption.exists()
        )
        if not is_on_reel:
            reels_marker = self.device.find(
                resourceIdMatches=case_insensitive_re([
                    ResourceID.CLIPS_VIDEO_CONTAINER,
                    ResourceID.CLIPS_AUTHOR_USERNAME,
                    ResourceID.ROOT_CLIPS_LAYOUT,
                ])
            )
            is_on_reel = reels_marker.exists()

        if is_on_reel:
            desc_txt = None

            # Tier 1: Direct attributes on clips_caption container
            if clips_caption.exists():
                desc_txt = clips_caption.get_desc() or clips_caption.get_text()

            # Tier 2: Child TextView elements inside clips_caption container
            if not desc_txt and clips_caption.exists():
                try:
                    child_tv = clips_caption.child(className=ClassName.TEXT_VIEW)
                    if child_tv.exists():
                        num_children = child_tv.count_items()
                        if num_children > 1:
                            segments = []
                            clean_uname = (username or "").lstrip("@").lower()
                            for idx in range(num_children):
                                segment = child_tv.get_text(error=False, index=idx)
                                if not segment:
                                    try:
                                        segment = child_tv.child(index=idx).get_desc()
                                    except Exception:
                                        segment = None
                                if segment and segment.strip():
                                    seg_clean = PostsViewList._normalize_ig_text(segment)
                                    if seg_clean.lstrip("@").lower() != clean_uname:
                                        segments.append(seg_clean)
                            if segments:
                                desc_txt = " ".join(segments)
                        else:
                            desc_txt = child_tv.get_text(error=False) or child_tv.get_desc()
                except Exception as ex:
                    logger.debug(f"Error querying clips_caption child TextViews: {ex}")

            # Tier 3: Alternative known Reels caption resource IDs
            if not desc_txt:
                alt_caption_regex = (
                    r".*clips.*caption.*|.*clips.*viewer.*caption.*|.*video_caption.*|"
                    r".*reel.*viewer.*title.*|.*expandable_text.*"
                )
                alt_caption = self.device.find(resourceIdMatches=alt_caption_regex)
                if alt_caption.exists():
                    desc_txt = alt_caption.get_desc() or alt_caption.get_text()
                    if not desc_txt:
                        try:
                            alt_child = alt_caption.child(className=ClassName.TEXT_VIEW)
                            if alt_child.exists():
                                desc_txt = alt_child.get_text(error=False) or alt_child.get_desc()
                        except Exception:
                            pass

            # Tier 4: XML hierarchy dump traversal
            if not desc_txt:
                desc_txt = self._find_reels_caption_from_hierarchy(username)

            if desc_txt:
                desc_txt = PostsViewList._clean_trailing_more(desc_txt)
                new_description = PostsViewList._normalize_ig_text(desc_txt).upper()
                if new_description != last_description:
                    return False, new_description, username, is_ad, is_hashtag, has_tags
                logger.info(
                    "This post has the same description and author as the last one."
                )
                return True, new_description, username, is_ad, is_hashtag, has_tags

            logger.info("This Reel post hasn't a caption description...")
            return False, "", username, is_ad, is_hashtag, has_tags
        for _ in range(8):
            post_description = self.device.find(
                index=-1,
                resourceIdMatches=ResourceID.ROW_FEED_TEXT,
                textStartsWith=username,
            )
            if not post_description.exists() and post_description.count_items() >= 1:
                text = post_description.get_text()
                post_description = self.device.find(
                    index=-1,
                    resourceIdMatches=ResourceID.ROW_FEED_TEXT,
                    text=text,
                )
            if post_description.exists():
                logger.debug("Description found!")
                new_description = post_description.get_text().upper()
                if new_description != last_description:
                    return False, new_description, username, is_ad, is_hashtag, has_tags
                logger.info(
                    "This post has the same description and author as the last one."
                )
                return True, new_description, username, is_ad, is_hashtag, has_tags
            caption_text = self._find_caption_text_in_current_post(username)
            if caption_text:
                new_description = caption_text.upper()
                if new_description != last_description:
                    return False, new_description, username, is_ad, is_hashtag, has_tags
                logger.info(
                    "This post has the same description and author as the last one."
                )
                return True, new_description, username, is_ad, is_hashtag, has_tags
            else:
                gap_view_obj = self.device.find(resourceId=ResourceID.GAP_VIEW)
                feed_composer = self.device.find(
                    resourceId=ResourceID.FEED_INLINE_COMPOSER_BUTTON_TEXTVIEW
                )
                if gap_view_obj.exists() and gap_view_obj.get_bounds()["bottom"] < (
                    self.device.get_info()["displayHeight"] / 3
                ):
                    universal_actions._swipe_points(
                        direction=Direction.DOWN, delta_y=200
                    )
                    continue
                row_feed_profile_header = self.device.find(
                    resourceId=ResourceID.ROW_FEED_PROFILE_HEADER
                )
                if row_feed_profile_header.count_items() > 1:
                    logger.info("This post hasn't the description...")
                    return False, "", username, is_ad, is_hashtag, has_tags
                profile_header_is_above = row_feed_profile_header.is_above_this(
                    gap_view_obj if gap_view_obj.exists() else feed_composer
                )
                if profile_header_is_above is not None:
                    if not profile_header_is_above:
                        logger.info("This post hasn't the description...")
                        return False, "", username, is_ad, is_hashtag, has_tags

                logger.debug(self.device.dump_hierarchy("window.xml"))
                logger.debug(
                    f"Can't find the description of {username}'s post, try to swipe a little bit down."
                )
                universal_actions._swipe_points(direction=Direction.DOWN, delta_y=200)
        logger.info("This post hasn't the description...")
        return False, "", username, is_ad, is_hashtag, has_tags

    def _if_action_bar_is_over_obj_swipe(self, obj):
        """do a swipe of the amount of the action bar"""
        action_bar_exists, _, action_bar_bottom = PostsViewList(
            self.device
        )._get_action_bar_position()
        if action_bar_exists:
            obj_top = obj.get_bounds()["top"]
            if action_bar_bottom > obj_top:
                UniversalActions(self.device)._swipe_points(
                    direction=Direction.UP, delta_y=action_bar_bottom
                )

    def _get_action_bar_position(self) -> Tuple[bool, int, int]:
        """action bar is overlay, if you press on it, you go back to the first post
        knowing his position is important to avoid it: exists, top, bottom"""
        action_bar = self.device.find(resourceIdMatches=ResourceID.ACTION_BAR_CONTAINER)
        if action_bar.exists():
            return (
                True,
                action_bar.get_bounds()["top"],
                action_bar.get_bounds()["bottom"],
            )
        else:
            return False, 0, 0

    def _refresh_feed(self):
        logger.info("Refresh feed..")
        refresh_pill = self.device.find(resourceId=ResourceID.NEW_FEED_PILL)
        if refresh_pill.exists(Timeout.SHORT):
            refresh_pill.click()
            random_sleep(inf=5, sup=8, modulable=False)
        else:
            UniversalActions(self.device)._reload_page()

    def _post_owner(self, current_job, mode: Owner, username=None):
        """returns a tuple[var, bool, bool]"""
        is_ad = False
        is_hashtag = False
        if mode == Owner.OPEN:
            owner_locators = (
                f"{ResourceID.ROW_FEED_PHOTO_PROFILE_NAME}|"
                f"{ResourceID.CLIPS_AUTHOR_USERNAME}|"
                f"{ResourceID.ROW_FEED_PROFILE_HEADER}|"
                f"{ResourceID.CLIPS_AUTHOR_INFO_COMPONENT}"
            )
        else:
            owner_locators = (
                f"{ResourceID.ROW_FEED_PHOTO_PROFILE_NAME}|"
                f"{ResourceID.CLIPS_AUTHOR_USERNAME}|"
                f"{ResourceID.CLIPS_AUTHOR_PROFILE_PIC}|"
                f"{ResourceID.ROW_FEED_PROFILE_HEADER}|"
                f"{ResourceID.CLIPS_AUTHOR_INFO_COMPONENT}"
            )
        if username is None:
            post_owner_obj = self.device.find(
                resourceIdMatches=ResourceID.ROW_FEED_PHOTO_PROFILE_NAME
            )
            if not post_owner_obj.exists():
                post_owner_obj = self.device.find(
                    resourceIdMatches=ResourceID.CLIPS_AUTHOR_USERNAME
                )
            if not post_owner_obj.exists() and mode != Owner.OPEN:
                post_owner_obj = self.device.find(
                    resourceIdMatches=ResourceID.CLIPS_AUTHOR_PROFILE_PIC
                )
            if not post_owner_obj.exists():
                post_owner_obj = self.device.find(
                    resourceIdMatches=ResourceID.ROW_FEED_PROFILE_HEADER
                )
            if not post_owner_obj.exists():
                post_owner_obj = self.device.find(
                    resourceIdMatches=owner_locators
                )
        else:
            clean_username = username.lstrip("@").strip() if username else ""
            for _ in range(2):
                post_owner_obj = self.device.find(
                    resourceIdMatches=ResourceID.ROW_FEED_PHOTO_PROFILE_NAME,
                    textStartsWith=clean_username,
                )
                if not post_owner_obj.exists():
                    post_owner_obj = self.device.find(
                        resourceIdMatches=ResourceID.CLIPS_AUTHOR_USERNAME,
                        textStartsWith=clean_username,
                    )
                # Never click profile pic in Reels when opening owner, as it opens the Story!
                if not post_owner_obj.exists() and mode != Owner.OPEN:
                    post_owner_obj = self.device.find(
                        resourceIdMatches=ResourceID.CLIPS_AUTHOR_PROFILE_PIC,
                        descriptionMatches=f"(?i)Profile picture of {re.escape(clean_username)}",
                    )
                if not post_owner_obj.exists() and mode == Owner.OPEN:
                    # In Reels full-screen viewer, fallback directly to the author username widget
                    clips_user = self.device.find(
                        resourceIdMatches=ResourceID.CLIPS_AUTHOR_USERNAME
                    )
                    if clips_user.exists():
                        post_owner_obj = clips_user
                if not post_owner_obj.exists():
                    post_owner_obj = self.device.find(
                        resourceIdMatches=owner_locators
                    )
                notification = self.device.find(
                    resourceIdMatches=ResourceID.NOTIFICATION_MESSAGE
                )
                if not post_owner_obj.exists() and notification.exists():
                    logger.warning(
                        "There is a notification there! Please disable them in settings.. We will wait 10 seconds before continue.."
                    )
                    sleep(10)
        post_owner_clickable = False

        for _ in range(3):
            if not post_owner_obj.exists():
                post_owner_obj = self.device.find(resourceIdMatches=owner_locators)
                if post_owner_obj.exists():
                    post_owner_clickable = True
                    break

                if mode == Owner.OPEN:
                    if (
                        not username
                        or username == "False"
                        or len(username.strip()) == 0
                    ):
                        logger.info(
                            "Cannot open post owner: invalid or empty username."
                        )
                        return False, False, is_hashtag
                    comment_description = self.device.find(
                        resourceIdMatches=ResourceID.ROW_FEED_COMMENT_TEXTVIEW_LAYOUT,
                        textStartsWith=username,
                    )
                    count_items = 0
                    try:
                        count_items = int(comment_description.count_items())
                    except Exception:
                        count_items = 0
                    if not comment_description.exists() and count_items >= 1:
                        comment_description = self.device.find(
                            resourceIdMatches=ResourceID.ROW_FEED_COMMENT_TEXTVIEW_LAYOUT,
                            text=comment_description.get_text(),
                        )

                    if comment_description.exists():
                        logger.info("Open post owner from description.")
                        comment_description.child().click()
                        return True, is_ad, is_hashtag
                UniversalActions(self.device)._swipe_points(direction=Direction.UP)
                post_owner_obj = self.device.find(
                    resourceIdMatches=owner_locators,
                )
            else:
                post_owner_clickable = True
                break

        if not post_owner_clickable:
            logger.info("Can't find the owner name, skip.")
            return False, False, is_hashtag
        if mode == Owner.OPEN:
            is_ad, is_hashtag, _ = self._check_if_ad_or_hashtag(post_owner_obj)
            if is_ad:
                logger.info("Post owner is an ad; refusing to click open post owner.")
                return False, True, is_hashtag
            logger.info("Open post owner.")
            self._if_action_bar_is_over_obj_swipe(post_owner_obj)
            post_owner_obj.click()
            return True, is_ad, is_hashtag
        elif mode == Owner.GET_NAME:
            is_ad, is_hashtag, raw_name = self._check_if_ad_or_hashtag(post_owner_obj)
            if not raw_name:
                raw_name = post_owner_obj.get_text() or post_owner_obj.get_desc() or ""

            logger.debug(f"[DEBUG owner name] raw_name='{raw_name}'")
            m_pic = re.search(
                r"Profile picture of\s+([a-zA-Z0-9._]+)",
                raw_name,
                re.IGNORECASE,
            )
            if m_pic:
                username = m_pic.group(1)
            else:
                cleaned = raw_name.replace("•", " ").replace("\xa0", " ").strip()
                m_user = re.match(r"^([a-zA-Z0-9._]+)", cleaned)
                if m_user:
                    username = m_user.group(1)
                else:
                    username = cleaned.split(" ", 1)[0] if cleaned else ""
            return username, is_ad, is_hashtag

        elif mode == Owner.GET_POSITION:
            return post_owner_obj.get_bounds(), is_ad
        else:
            return None, is_ad, is_hashtag

    def _get_post_owner_name(self):
        return self.device.find(
            resourceIdMatches=ResourceID.ROW_FEED_PHOTO_PROFILE_NAME
        ).get_text()

    def _describes_a_post(self, media) -> Optional[str]:
        """IG 447+ moved the description from the media_group wrapper to its inner
        image view (ROW_FEED_PHOTO_IMAGEVIEW / CAROUSEL_IMAGE). Check the outer node
        first; fall back to the inner child if the outer is empty.

        Always returns a non-empty string or None so callers can use a simple
        truthiness check: ``if content_desc:``
        """
        content_desc = media.get_desc()
        if content_desc:
            return content_desc
        inner = media.child(
            resourceIdMatches=(
                f"{ResourceID.ROW_FEED_PHOTO_IMAGEVIEW}|{ResourceID.CAROUSEL_IMAGE}"
            )
        )
        if inner.exists():
            inner_desc = inner.get_desc()
            return inner_desc if inner_desc else None
        return None

    def _get_media_container(self):
        media = self.device.find(resourceIdMatches=ResourceID.CAROUSEL_AND_MEDIA_GROUP)
        if not media.exists():
            return media, None
        # The feed RecyclerView keeps thin 54px slivers of already-scrolled posts at
        # the top of the list. They share the same resource IDs but carry no
        # description. The old code returned the first one it found, which sent
        # double-taps into the wrong post or the header row.
        # Take the first candidate that actually describes a real post.
        # (upstream fix: commits 01891fa and 74c8dc4 from PR #28)
        for index in range(media.count_items()):
            candidate = self.device.find(
                resourceIdMatches=ResourceID.CAROUSEL_AND_MEDIA_GROUP, index=index
            )
            content_desc = self._describes_a_post(candidate)
            if content_desc:
                return candidate, content_desc
        return media, None

    def _get_like_button_of(self, media) -> Optional[object]:
        """Pair the like (heart) button with the post that *media* belongs to.

        In a flat feed RecyclerView the media view and the action-bar row that
        contains the heart are siblings, not parent/child. Calling
        find(ROW_FEED_BUTTON_LIKE) without further filtering returns the first
        button in the DOM tree, which is typically the heart of the post that
        was scrolled past (above the current post). We fix this by iterating
        all ROW_FEED_BUTTON_LIKE nodes and returning the one whose top edge
        starts at or below the media's bottom edge — the closest such button
        belongs to the current post.

        Returns None when no geometrically-paired button can be found so callers
        can fall back gracefully (e.g. double-tap).
        (upstream fix: commits 74c8dc4 and f2146a3 from PR #28)
        """
        buttons = self.device.find(resourceIdMatches=ResourceID.ROW_FEED_BUTTON_LIKE)
        if not buttons.exists():
            return None
        try:
            media_bottom = media.get_bounds()["bottom"] if media is not None else 0
        except DeviceFacade.JsonRpcError:
            media_bottom = 0
        best = None
        for index in range(buttons.count_items()):
            candidate = self.device.find(
                resourceIdMatches=ResourceID.ROW_FEED_BUTTON_LIKE, index=index
            )
            try:
                top = candidate.get_bounds()["top"]
            except DeviceFacade.JsonRpcError:
                continue
            if top >= media_bottom and (best is None or top < best[0]):
                best = (top, candidate)
        return best[1] if best else None

    @staticmethod
    def detect_media_type(content_desc) -> Tuple[Optional[MediaType], Optional[int]]:
        """
        Detect the nature and amount of a media
        :return: MediaType and count
        :rtype: MediaType, int
        """
        obj_count = 1
        if content_desc is None:
            return None, None
        if re.match(r"^,|^\s*$", content_desc, re.IGNORECASE):
            logger.info(
                "That media is missing content description, so I don't know which kind of video it is."
            )
            media_type = MediaType.UNKNOWN
        elif carousel_match := re.match(
            r"^(?:Photo|Video)\s+\d+\s+of\s+(\d+)", content_desc, re.IGNORECASE
        ):
            # IG 447+: carousels are labeled "Photo 1 of 4 by Username, 2280 likes".
            # This branch MUST appear before ^Photo/^Video or the carousel match
            # is swallowed by the single-item branches.
            # (upstream fix: commit f32620c from PR #28)
            obj_count = int(carousel_match.group(1))
            logger.info(f"It's a carousel with {obj_count} element(s).")
            media_type = MediaType.CAROUSEL
        elif re.match(r"^Photo|^Hidden Photo", content_desc, re.IGNORECASE):
            logger.info("It's a photo.")
            media_type = MediaType.PHOTO
        elif re.match(r"^Video|^Hidden Video", content_desc, re.IGNORECASE):
            logger.info("It's a video.")
            media_type = MediaType.VIDEO
        elif re.match(r"^IGTV", content_desc, re.IGNORECASE):
            logger.info("It's a IGTV.")
            media_type = MediaType.IGTV
        elif re.match(r"^Reel", content_desc, re.IGNORECASE):
            logger.info("It's a Reel.")
            media_type = MediaType.REEL
        else:
            # Legacy carousel format: "2 photos, 1 video" — retained for backward
            # compatibility with older IG versions that don't use "Photo N of M".
            carousel_obj = re.finditer(
                r"((?P<photo>\d+) photo)|((?P<video>\d+) video)",
                content_desc,
                re.IGNORECASE,
            )
            n_photos = 0
            n_videos = 0
            for match in carousel_obj:
                if match.group("photo"):
                    n_photos = int(match.group("photo"))
                if match.group("video"):
                    n_videos = int(match.group("video"))
            logger.info(
                f"It's a carousel with {n_photos} photo(s) and {n_videos} video(s)."
            )
            obj_count = n_photos + n_videos
            media_type = MediaType.CAROUSEL
        return media_type, obj_count

    def _like_in_post_view(
        self,
        mode: LikeMode,
        skip_media_check: bool = False,
        already_watched: bool = False,
    ):
        post_view_list = PostsViewList(self.device)
        opened_post_view = OpenedPostView(self.device)
        if skip_media_check:
            return

        # ── Reels viewer: dedicated Reel like path ────────────────────────────
        # This block is intentionally kept verbatim from our fork; upstream PR #28
        # removed it which would break Reels liking. Do NOT merge upstream here.
        is_reel = self.device.find(
            resourceIdMatches=f"{ResourceID.CLIPS_VIEWER_CONTAINER}|{ResourceID.ROOT_CLIPS_LAYOUT}|{ResourceID.CLIPS_AUTHOR_USERNAME}"
        ).exists()
        if is_reel:
            logger.info("In Reels viewer: liking via dedicated Reel like button.")
            like_btn = self.device.find(
                resourceIdMatches=f"{ResourceID.LIKE_BUTTON}|{ResourceID.ROW_FEED_BUTTON_LIKE}|{ResourceID.TOOLBAR_LIKE_BUTTON}"
            )
            if like_btn.exists():
                logger.info("Clicking on the little heart ❤️.")
                like_btn.click()
            return
        # ─────────────────────────────────────────────────────────────────────

        media, content_desc = self._get_media_container()
        media_type = None  # initialise so it is always bound before use

        if content_desc is None:
            if mode == LikeMode.DOUBLE_CLICK:
                # Can't determine media type without a description; and without a
                # geometry anchor we can't pair the heart reliably either.
                logger.debug("Media container has no description, skip like.")
                return
            # For SINGLE_CLICK we attempt a geometry-paired heart press anyway.
            # By the time the retry runs the feed has usually scrolled into place.
            logger.debug(
                "Media container has no description, pressing the heart anyway."
            )
        elif not already_watched:
            media_type, _ = post_view_list.detect_media_type(content_desc)
            opened_post_view.watch_media(media_type)

        if mode == LikeMode.DOUBLE_CLICK:
            if media_type in (MediaType.CAROUSEL, MediaType.PHOTO):
                # Pressing the heart is the reliable path on IG 447: in one run
                # double-tapping the media registered 1 like out of 9 attempts,
                # while the button toggles content-desc Like <-> Liked every time.
                # Fall back to double-tap only when no heart can be paired.
                # (upstream fix: commits 74c8dc4 and f2146a3 from PR #28)
                like_button = self._get_like_button_of(media)
                if like_button is not None:
                    logger.info("Clicking on the little heart ❤️.")
                    like_button.click()
                else:
                    logger.info("Double click on post.")
                    _, _, action_bar_bottom = PostsViewList(
                        self.device
                    )._get_action_bar_position()
                    media.double_click(obj_over=action_bar_bottom)
            else:
                # Reels, videos, and IGTV in feed (not in dedicated viewer).
                # The previous recursive SINGLE_CLICK(skip_media_check=True) call
                # returned immediately without pressing anything — these were
                # never liked. Use geometric pairing instead.
                like_button = self._get_like_button_of(media)
                if like_button is not None:
                    logger.info("Clicking on the little heart ❤️.")
                    like_button.click()
                else:
                    logger.debug("Like button not found on this screen, skip like.")
        elif mode == LikeMode.SINGLE_CLICK:
            like_button = self._get_like_button_of(media)
            if like_button is None:
                # The heart may still be below the fold; scroll it into view.
                self._find_likers_container()
                like_button = self._get_like_button_of(media)
            if like_button is not None:
                logger.info("Clicking on the little heart ❤️.")
                like_button.click()
            else:
                logger.debug("Like button not found on this screen, skip like.")

    def _follow_in_post_view(self):
        logger.info("Follow blogger in place.")
        self.device.find(resourceIdMatches=ResourceID.BUTTON).click()

    def _comment_in_post_view(self):
        logger.info("Open comments of post.")
        self.device.find(resourceIdMatches=ResourceID.ROW_FEED_BUTTON_COMMENT).click()

    def _check_if_liked(self, retries=3):
        logger.debug("Check if like succeeded in post view.")
        is_reel = self.device.find(
            resourceIdMatches=f"{ResourceID.CLIPS_VIEWER_CONTAINER}|{ResourceID.ROOT_CLIPS_LAYOUT}|{ResourceID.CLIPS_AUTHOR_USERNAME}"
        ).exists()
        if is_reel:
            bnt_like_obj = self.device.find(
                resourceIdMatches=f"{ResourceID.LIKE_BUTTON}|{ResourceID.ROW_FEED_BUTTON_LIKE}|{ResourceID.TOOLBAR_LIKE_BUTTON}"
            )
            if bnt_like_obj.exists():
                try:
                    if bnt_like_obj.get_selected():
                        logger.debug("Reel like button is selected.")
                        return True
                except Exception:
                    pass
                desc = bnt_like_obj.get_desc() or ""
                text = bnt_like_obj.get_text() or ""
                if re.search(r"(?i)(liked|unlike)", desc) or re.search(
                    r"(?i)(liked|unlike)", text
                ):
                    logger.debug("Like is present on Reel.")
                    return True
            logger.debug("Reel like handled.")
            return True

        bnt_like_obj = self.device.find(
            resourceIdMatches=ResourceID.ROW_FEED_BUTTON_LIKE
        )
        if bnt_like_obj.exists():
            STR = "Liked"
            if self.device.find(descriptionMatches=case_insensitive_re(STR)).exists():
                logger.debug("Like is present.")
                return True
            else:
                logger.debug("Like is not present.")
                return False
        else:
            if retries <= 0:
                logger.debug(
                    "Could not verify like via standard button ID. Assuming already handled."
                )
                return True
            UniversalActions(self.device)._swipe_points(
                direction=Direction.DOWN, delta_y=100
            )
            return PostsViewList(self.device)._check_if_liked(retries=retries - 1)

    def _check_if_ad_or_hashtag(
        self, post_owner_obj
    ) -> Tuple[bool, bool, Optional[str]]:
        is_hashtag = False
        is_ad = False
        logger.debug("Checking if it's an AD or an hashtag..")
        ad_like_obj = post_owner_obj.sibling(
            resourceId=ResourceID.SECONDARY_LABEL,
        )

        owner_name = ""
        try:
            if post_owner_obj.exists():
                owner_name = post_owner_obj.get_text() or post_owner_obj.get_desc() or ""
        except Exception as e:
            logger.debug(f"Could not extract owner_name directly: {e}")

        if not isinstance(owner_name, str):
            owner_name = str(owner_name) if owner_name else ""

        if not owner_name:
            logger.info("Can't find the owner name, need to use OCR.")
            try:
                import pytesseract as pt

                try:
                    owner_name = self.get_text_from_screen(pt, post_owner_obj)
                    if not isinstance(owner_name, str):
                        owner_name = str(owner_name) if owner_name else ""
                except pt.TesseractNotFoundError:
                    logger.error(
                        "You need to install Tesseract engine in order to use OCR feature."
                    )
                except Exception as e:
                    logger.debug(f"OCR execution failed: {e}")
            except ImportError:
                logger.debug(
                    "Pytesseract not installed; skipping OCR owner name extraction."
                )
        if owner_name and owner_name.startswith("#"):
            is_hashtag = True
            logger.debug("Looks like an hashtag, skip.")

        # Check secondary label / subtitle for sponsored indicators
        ad_regex = r"\b(sponsored|ad|promoted|advertisement|paid partnership)\b"
        ad_like_txt = ""
        try:
            if ad_like_obj.exists():
                ad_like_txt = ad_like_obj.get_text() or ad_like_obj.get_desc() or ""
        except Exception as e:
            logger.debug(f"Could not extract secondary label: {e}")

        if not isinstance(ad_like_txt, str):
            ad_like_txt = str(ad_like_txt) if ad_like_txt else ""
        if re.search(ad_regex, ad_like_txt, re.IGNORECASE):
            logger.debug(f"Looks like an AD (label: '{ad_like_txt}'), skip.")
            is_ad = True
        elif is_hashtag and owner_name:
            owner_name = owner_name.split("•")[0].strip()

        # Check if owner name itself indicates sponsored content
        if owner_name and re.search(ad_regex, owner_name, re.IGNORECASE):
            logger.debug(
                f"Looks like an AD (owner contains sponsored: '{owner_name}'), skip."
            )
            is_ad = True

        # Check Call-To-Action (CTA) ad buttons in visible post area
        if not is_ad:
            owner_bounds = None
            if post_owner_obj.exists():
                try:
                    b = post_owner_obj.get_bounds()
                    if isinstance(b, dict) and isinstance(
                        b.get("top"), (int, float)
                    ):
                        owner_bounds = b
                except Exception:
                    pass
            post_owner_top = owner_bounds["top"] if owner_bounds else 0

            cta_ad_button = self.device.find(
                resourceIdMatches=f"{ResourceID.AD_ACTION_BUTTON}|{ResourceID.AD_CALL_TO_ACTION}|{ResourceID.POST_AD_CTA_BUTTON}"
            )
            if cta_ad_button.exists():
                cta_bounds = None
                try:
                    cb = cta_ad_button.get_bounds()
                    if isinstance(cb, dict) and isinstance(
                        cb.get("bottom"), (int, float)
                    ):
                        cta_bounds = cb
                except Exception:
                    pass
                if (
                    cta_bounds is None
                    or cta_bounds.get("bottom", 0) >= post_owner_top
                ):
                    logger.debug(
                        "Looks like an AD (CTA button resource detected), skip."
                    )
                    is_ad = True
            if not is_ad:
                ad_button_text = self.device.find(
                    textMatches="(?i)^(Learn More|Install Now|Install|Shop Now|Download|Sign Up|Watch More|Apply Now|Get Offer|Book Now|Contact Us|Play Game|Subscribe|Open app)$"
                )
                if ad_button_text.exists():
                    cta_text_bounds = None
                    try:
                        tb = ad_button_text.get_bounds()
                        if isinstance(tb, dict) and isinstance(
                            tb.get("bottom"), (int, float)
                        ):
                            cta_text_bounds = tb
                    except Exception:
                        pass
                    if (
                        cta_text_bounds is None
                        or cta_text_bounds.get("bottom", 0) >= post_owner_top
                    ):
                        logger.debug(
                            f"Looks like an AD (CTA button text '{ad_button_text.get_text()}'), skip."
                        )
                        is_ad = True

        return is_ad, is_hashtag, owner_name

    def get_text_from_screen(self, pt, obj) -> Optional[str]:

        if platform.system() == "Windows":
            pt.pytesseract.tesseract_cmd = (
                r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            )

        screenshot = self.device.screenshot()
        bounds = obj.ui_info().get("visibleBounds", None)
        if bounds is None:
            logger.info("Can't find the bounds of the object.")
            return None
        screenshot_cropped = screenshot.crop(
            [
                bounds.get("left"),
                bounds.get("top"),
                bounds.get("right"),
                bounds.get("bottom"),
            ]
        )
        return pt.image_to_string(screenshot_cropped).split(" ")[0].rstrip()


class LanguageView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def setLanguage(self, language: str):
        logger.debug(f"Set language to {language}.")
        search_edit_text = self.device.find(
            resourceId=ResourceID.SEARCH,
            className=ClassName.EDIT_TEXT,
        )
        dont_type = getattr(args, "dont_type", False) if args is not None else False
        search_edit_text.set_text(language, Mode.PASTE if dont_type else Mode.TYPE)

        list_view = self.device.find(
            resourceId=ResourceID.LANGUAGE_LIST_LOCALE,
            className=ClassName.LIST_VIEW,
        )
        first_item = list_view.child(index=0)
        first_item.click()
        random_sleep()


class AccountView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def navigateToLanguage(self):
        logger.debug("Navigate to Language")
        button = self.device.find(
            className=ClassName.BUTTON,
            index=6,
        )
        if button.exists():
            button.click()
            return LanguageView(self.device)
        else:
            logger.error("Not able to set your app in English! Do it by yourself!")
            exit(0)

    def navigate_to_main_account(self):
        logger.info("Navigating to profile / main account...")
        profile_view = ProfileView(self.device)
        profile_view.click_on_avatar()
        if profile_view.getFollowingCount() is None:
            profile_view.click_on_avatar()

    def changeToUsername(self, username: str):
        action_bar = ProfileView._getActionBarTitleBtn(self)

        # If action_bar exists, we compare it
        if action_bar is not None:
            current_profile_name = action_bar.get_text()
            if (
                current_profile_name
                and current_profile_name.strip().upper() == username.upper()
            ):
                logger.info(
                    f"You are already logged as {username}!",
                    extra={"color": f"{Style.BRIGHT}{Fore.BLUE}"},
                )
                return True
            if current_profile_name:
                logger.debug(f"You're logged as {current_profile_name.strip()}")

        # If no action bar was found OR names didn't match, look for dropdown selector
        selector = self.device.find(resourceId=ResourceID.ACTION_BAR_TITLE_CHEVRON)
        if not selector.exists(Timeout.SHORT):
            # Try tapping the action_bar directly as the account switcher dropdown triggers there
            if action_bar:
                selector = action_bar

        if selector and selector.exists():
            selector.click()
            if self._find_username(username):
                # Verify change without hard sleep - let the _getActionBarTitleBtn UIAutomator internal wait handle it
                action_bar = ProfileView._getActionBarTitleBtn(self)
                if action_bar is not None:
                    current_profile_name = action_bar.get_text()
                    if (
                        current_profile_name
                        and current_profile_name.strip().upper() == username.upper()
                    ):
                        return True

                # Fallback verify: search exact username on screen if action bar still failing
                direct_name = self.device.find(textMatches=f"(?i)^{username}$")
                if direct_name.exists(Timeout.SHORT):
                    return True
        else:
            # Maybe already single account and it matches?
            # We must be on the profile already if we couldn't click a dropdown.
            direct_name = self.device.find(textMatches=f"(?i)^{username}$")
            if direct_name.exists(Timeout.SHORT):
                logger.info(
                    f"Confirmed already logged as {username} via screen text fallback."
                )
                return True

        logger.error("Failed to switch to or verify account {username}.")
        return False

    def _find_username(self, username, has_scrolled=False):
        list_view = self.device.find(resourceId=ResourceID.LIST)
        username_obj = self.device.find(
            resourceIdMatches=f"{ResourceID.ROW_USER_TEXTVIEW}|{ResourceID.USERNAME_TEXTVIEW}",
            textMatches=case_insensitive_re(username),
        )
        if username_obj.exists(Timeout.SHORT):
            logger.info(
                f"Switching to {username}...",
                extra={"color": f"{Style.BRIGHT}{Fore.BLUE}"},
            )
            username_obj.click()
            return True

        # Fallback for IG 438+: account switcher uses content-desc on ViewGroup rows
        account_row = self.device.find(
            classNameMatches="android.view.ViewGroup",
            descriptionMatches=case_insensitive_re(f"^{username}.*"),
        )
        if account_row.exists(Timeout.SHORT):
            logger.info(
                f"Switching to {username}...",
                extra={"color": f"{Style.BRIGHT}{Fore.BLUE}"},
            )
            account_row.click()
            return True

        if list_view.exists() and list_view.is_scrollable() and not has_scrolled:
            logger.debug("User list is scrollable.")
            list_view.scroll(Direction.DOWN)
            return self._find_username(username, has_scrolled=True)
        return False

    def refresh_account(self):
        try:
            from InstaAddict.core.watchdog import record_heartbeat
            record_heartbeat("profile", "Refreshing account profile")
        except Exception:
            pass
        textview = self.device.find(
            resourceIdMatches=ResourceID.ROW_PROFILE_HEADER_TEXTVIEW_POST_CONTAINER
        )
        universal_actions = UniversalActions(self.device)
        if textview.exists(Timeout.SHORT):
            logger.info("Refresh account...")
            universal_actions._swipe_points(
                direction=Direction.UP,
                start_point_y=textview.get_bounds()["bottom"],
                delta_y=280,
            )
            random_sleep(modulable=False)
        obj = self.device.find(
            resourceIdMatches=ResourceID.ROW_PROFILE_HEADER_TEXTVIEW_POST_CONTAINER
        )
        if not obj.exists(Timeout.MEDIUM):
            logger.debug(
                "Can't see Posts, Followers and Following after the refresh, maybe we moved a little bit bottom.. Swipe down."
            )
            universal_actions._swipe_points(Direction.UP)


class SettingsView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def navigateToAccount(self):
        logger.debug("Navigate to Account")
        button = self.device.find(
            className=ClassName.BUTTON,
            index=5,
        )
        if button.exists():
            button.click()
            return AccountView(self.device)
        else:
            logger.error("Not able to set your app in English! Do it by yourself!")
            exit(2)


class OptionsView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def navigateToSettings(self):
        logger.debug("Navigate to Settings")
        button = self.device.find(
            resourceId=ResourceID.MENU_OPTION_TEXT,
            className=ClassName.TEXT_VIEW,
        )
        if button.exists():
            button.click()
            return SettingsView(self.device)
        else:
            logger.error("Not able to set your app in English! Do it by yourself!")
            exit(0)


class OpenedPostView:
    def __init__(self, device: DeviceFacade):
        self.device = device
        self.has_tags = False
        self.is_peek = False

    def is_post_opened(self) -> bool:
        """Confirm a post detail or the reels viewer is actually showing."""
        post_media = self.device.find(
            resourceIdMatches=case_insensitive_re(
                "|".join(
                    [
                        ResourceID.MEDIA_CONTAINER,
                        ResourceID.VIDEO_CONTAINER_AND_CLIPS_VIDEO_CONTAINER,
                        ResourceID.ROW_FEED_BUTTON_LIKE,
                        ResourceID.LIKE_BUTTON,
                        ResourceID.ROOT_CLIPS_LAYOUT,
                        ResourceID.CLIPS_VIEWER_CONTAINER,
                        ResourceID.CLIPS_VIEWER_VIEW_PAGER,
                        ResourceID.CLIPS_VIDEO_CONTAINER,
                    ]
                )
            )
        )
        return post_media.exists(Timeout.MEDIUM)

    def is_peek_preview_opened(self) -> bool:
        """Confirm if Instagram's 3D Touch / long-press Peek Preview popup is open.
        This popup displays a floating preview card with a context menu containing
        options like Repost, Report, Like/Unlike.
        Note: Standard Reels and Feed posts also contain Like, Comment, and Share.
        To completely prevent false-positive detection on normal content, (Repost|Report)
        is strictly required as the identifying context marker."""
        try:
            if hasattr(self.device, "_ig_is_opened") and not self.device._ig_is_opened():
                return False

            # 1. Distinctive Peek Preview options (Repost and Report in popup context menus)
            distinct_opt = self.device.find(
                textMatches=case_insensitive_re(r"^\s*(Repost|Report)\s*$"),
            )
            if not distinct_opt.exists(Timeout.ZERO):
                distinct_opt = self.device.find(
                    descriptionMatches=case_insensitive_re(r"^\s*(Repost|Report)\s*$"),
                )
            if distinct_opt.exists(Timeout.ZERO):
                return True

            # 2. Context options: Like/Unlike alongside Repost/Report
            like_btn = self.device.find(
                textMatches=case_insensitive_re(r"^\s*(Like|Unlike)\s*$"),
            )
            if not like_btn.exists(Timeout.ZERO):
                like_btn = self.device.find(
                    descriptionMatches=case_insensitive_re(r"^\s*(Like|Unlike)\s*$"),
                )

            context_opt = self.device.find(
                textMatches=case_insensitive_re(r"^\s*(Repost|Report)\s*$"),
            )
            if not context_opt.exists(Timeout.ZERO):
                context_opt = self.device.find(
                    descriptionMatches=case_insensitive_re(r"^\s*(Repost|Report)\s*$"),
                )

            if like_btn.exists(Timeout.ZERO) and context_opt.exists(Timeout.ZERO):
                return True
            return False
        except DeviceFacade.AppHasCrashed:
            return False
        except Exception as e:
            logger.debug(f"is_peek_preview_opened error: {e}")
            return False

    def is_peek_already_liked(self) -> bool:
        """Check if the post in the Peek Preview is already liked (shows 'Unlike')."""
        try:
            unlike_btn = self.device.find(
                textMatches=case_insensitive_re(r"^\s*Unlike\s*$"),
            )
            if not unlike_btn.exists(Timeout.ZERO):
                unlike_btn = self.device.find(
                    descriptionMatches=case_insensitive_re(r"^\s*Unlike\s*$"),
                )
            return unlike_btn.exists(Timeout.TINY)
        except DeviceFacade.AppHasCrashed:
            return False
        except Exception:
            return False

    def like_in_peek(self) -> bool:
        """Perform a like directly from the Peek Preview context menu."""
        try:
            if self.is_peek_already_liked():
                logger.info("Post already liked (detected via Peek Preview menu)!")
                return True
            like_btn = self.device.find(
                textMatches=case_insensitive_re(r"^\s*Like\s*$"),
            )
            if not like_btn.exists(Timeout.ZERO):
                like_btn = self.device.find(
                    descriptionMatches=case_insensitive_re(r"^\s*Like\s*$"),
                )
            if like_btn.exists(Timeout.TINY):
                logger.info("Liking post directly from Peek Preview menu ❤️.")
                like_btn.click()
                UniversalActions.detect_block(self.device)
                random_sleep(0.5, 1.0, modulable=False)
                return True
            logger.warning("Like button not found in Peek Preview menu!")
            return False
        except DeviceFacade.AppHasCrashed:
            return False
        except Exception as e:
            logger.debug(f"like_in_peek error: {e}")
            return False

    def dismiss_peek(self) -> bool:
        """Cleanly and immediately dismiss the Peek Preview and return to profile grid."""
        try:
            logger.debug("Dismissing Peek Preview...")
            for _ in range(2):
                self.device.back()
                random_sleep(0.5, 1.0, modulable=False)
                if not self.is_peek_preview_opened():
                    return True
            # If back key did not clear the overlay, tap outside the modal card (top margin)
            try:
                info = self.device.get_info()
                w, h = info["displayWidth"], info["displayHeight"]
                self.device.deviceV2.click(w // 2, int(h * 0.05))
                random_sleep(0.5, 1.0, modulable=False)
            except Exception:
                pass
            return not self.is_peek_preview_opened()
        except DeviceFacade.AppHasCrashed:
            return False
        except Exception as e:
            logger.debug(f"dismiss_peek error: {e}")
            return False

    def detect_opened_media_type(self) -> MediaType:
        """Detect the media type from the opened post itself.
        Used when the grid cell had no content description."""
        clips_container = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.CLIPS_VIDEO_CONTAINER)
        )
        if clips_container.exists():
            logger.info("It's a Reel (detected after opening).")
            return MediaType.REEL

        carousel_indicator = self.device.find(
            resourceIdMatches=case_insensitive_re(
                f"{ResourceID.CAROUSEL_MEDIA_GROUP}|{ResourceID.CAROUSEL_INDEX_INDICATOR_TEXT_VIEW}"
            )
        )
        if carousel_indicator.exists():
            logger.info("It's a carousel (detected after opening).")
            return MediaType.CAROUSEL

        photo_indicator = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.ROW_FEED_PHOTO_IMAGEVIEW)
        )
        if photo_indicator.exists():
            logger.info("It's a photo (detected after opening).")
            return MediaType.PHOTO

        video_container = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.VIDEO_CONTAINER)
        )
        if video_container.exists():
            logger.info("It's a video (detected after opening).")
            return MediaType.VIDEO

        logger.warning(
            "Could not identify media type from any known marker — defaulting to photo."
        )
        return MediaType.PHOTO

    def _get_post_like_button(self) -> Optional[DeviceFacade.View]:
        post_media_view = self.device.find(resourceIdMatches=ResourceID.MEDIA_CONTAINER)
        if post_media_view.exists(Timeout.MEDIUM):
            attempt = 0
            while True:
                like_button = post_media_view.down(
                    resourceIdMatches=case_insensitive_re(
                        f"{ResourceID.ROW_FEED_BUTTON_LIKE}|{ResourceID.LIKE_BUTTON}"
                    )
                )
                if like_button.viewV2 is not None or attempt == 3:
                    return like_button if like_button.exists() else None
                UniversalActions(self.device)._swipe_points(
                    direction=Direction.DOWN, delta_y=100
                )
                attempt += 1
        like_btn = self.device.find(
            resourceIdMatches=case_insensitive_re(
                f"{ResourceID.ROW_FEED_BUTTON_LIKE}|{ResourceID.LIKE_BUTTON}"
            )
        )
        if like_btn.exists(Timeout.SHORT):
            return like_btn
        return None

    def _is_post_liked(self) -> Tuple[Optional[bool], Optional[DeviceFacade.View]]:
        """
        Check if post is liked
        :return: post is liked or not
        :rtype: bool
        """
        like_btn_view = self._get_post_like_button()
        if not like_btn_view:
            return False, None

        return like_btn_view.get_selected(), like_btn_view

    def like_post(self) -> bool:
        """
        Like the post with a double click and check if it's liked
        :return: post has been liked
        :rtype: bool
        """
        post_media_view = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.MEDIA_CONTAINER)
        )
        liked = False
        if not post_media_view.exists():
            like_button = self.device.find(
                resourceIdMatches=case_insensitive_re(
                    f"{ResourceID.ROW_FEED_BUTTON_LIKE}|{ResourceID.LIKE_BUTTON}"
                )
            )
            if like_button.exists(Timeout.SHORT):
                logger.info("Liking post via the little heart ❤️.")
                like_button.click()
                UniversalActions.detect_block(self.device)
                liked = like_button.get_selected()
            else:
                logger.error("Can't find the media container nor the like button!")
        elif post_media_view.exists():
            logger.info("Liking post.")
            if self.has_tags:
                logger.info(
                    "Post has tags, better going with a single click on the little heart ❤️."
                )
                like_button = self._get_post_like_button()
                if like_button is not None:
                    like_button.click()
                    liked, _ = self._is_post_liked()
                else:
                    logger.warning("Can't find the like button object!")
            else:
                post_media_view.double_click()
                liked, like_button = self._is_post_liked()
                if not liked and like_button is not None:
                    logger.info("Double click failed, clicking on the little heart ❤️.")
                    like_button.click()
                    liked, _ = self._is_post_liked()
        return liked

    def start_video(self) -> bool:
        """
        Press on play button if present
        :return: has play button been pressed
        :rtype: bool
        """
        play_button = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.VIEW_PLAY_BUTTON)
        )
        if play_button.exists(Timeout.TINY):
            logger.debug("Pressing on play button.")
            play_button.click()
            return True
        return False

    def open_video(self) -> bool:
        """
        Open video in full-screen mode
        :return: video in full-screen mode
        :rtype: bool
        """
        in_fullscreen, _ = self._is_video_in_fullscreen()
        if in_fullscreen:
            logger.debug("Video is already in full screen.")
            return True
        post_media_view = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.MEDIA_CONTAINER)
        )
        if post_media_view.exists():
            logger.info("Going in full screen.")
            post_media_view.click()
            in_fullscreen, _ = self._is_video_in_fullscreen()
        return in_fullscreen

    def watch_media(self, media_type: MediaType) -> None:
        """
        Watch media for the amount of time specified in config
        :return: None
        :rtype: None
        """
        if (
            media_type
            in (MediaType.IGTV, MediaType.REEL, MediaType.VIDEO, MediaType.UNKNOWN)
            and args.watch_video_time != "0"
        ):
            in_fullscreen, _ = self._is_video_in_fullscreen()
            time_left = self._get_video_time_left()
            watching_time = get_value(
                args.watch_video_time, name=None, default=0, its_time=True
            )
            if time_left > 0 and media_type != MediaType.REEL and in_fullscreen:
                logger.info(f"This video is about {time_left}s long.")
                # hardcoded 5 seconds, so we have the time to doing everything without going to the next video, hopefully
                watching_time = min(
                    watching_time,
                    time_left - 5,
                )
            logger.info(
                f"Watching video for {watching_time if watching_time > 0 else 'few '}s."
            )

        elif (
            media_type in (MediaType.CAROUSEL, MediaType.PHOTO)
            and args.watch_photo_time != "0"
        ):
            self._has_tags()
            watching_time = get_value(
                args.watch_photo_time, "Watching photo for {}s.", 0, its_time=True
            )
        else:
            return None
        if watching_time > 0:
            sleep(watching_time)

    def _get_video_time_left(self) -> int:
        timer = self.device.find(resourceId=ResourceID.TIMER)
        if timer.exists():
            raw_time = timer.get_text().split(":")
            try:
                return int(raw_time[0]) * 60 + int(raw_time[1])
            except (IndexError, ValueError):
                return 0
        return 0

    def _is_video_in_fullscreen(self) -> Tuple[bool, DeviceFacade.View]:
        """
        Check if video is in full-screen mode
        """
        video_container = self.device.find(
            resourceIdMatches=case_insensitive_re(
                ResourceID.VIDEO_CONTAINER_AND_CLIPS_VIDEO_CONTAINER
            )
        )
        return video_container.exists(), video_container

    def _is_video_liked(self) -> Tuple[Optional[bool], Optional[DeviceFacade.View]]:
        """
        Check if video has been liked
        """
        like_button = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.LIKE_BUTTON)
        )
        if like_button.exists():
            return like_button.get_selected(), like_button
        return False, None

    def _has_tags(self) -> bool:
        tags_icon = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.INDICATOR_ICON_VIEW)
        )
        self.has_tags = tags_icon.exists()
        return self.has_tags

    def like_video(self) -> bool:
        """
        Like the video with a double click and check if it's liked
        :return: video has been liked
        :rtype: bool
        """
        sidebar = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.UFI_STACK)
        )
        liked = False
        full_screen, obj = self._is_video_in_fullscreen()
        if full_screen:
            logger.info("Liking video.")
            obj.double_click()
            UniversalActions.detect_block(self.device)
            if not sidebar.exists():
                logger.debug("Showing sidebar...")
                obj.click()
            liked, like_button = self._is_video_liked()
            if not liked:
                logger.info("Double click failed, clicking on the little heart ❤️.")
                if like_button is not None:
                    like_button.click()
                    UniversalActions.detect_block(self.device)
                else:
                    logger.error("We are seeing another video.")
                liked, _ = self._is_video_liked()
        return liked

    def _getListViewLikers(self):
        for _ in range(2):
            obj = self.device.find(resourceId=ResourceID.LIST)
            if obj.exists(Timeout.LONG):
                return obj
            logger.debug("Can't find likers list, try again..")
        logger.error("Can't load likers list..")
        return None

    def _getUserContainer(self):
        obj = self.device.find(
            resourceIdMatches=ResourceID.USER_LIST_CONTAINER,
        )
        return obj if obj.exists(Timeout.LONG) else None

    def _getUserName(self, container):
        return container.child(
            resourceId=ResourceID.ROW_USER_PRIMARY_NAME,
        )

    def _isFollowing(self, container):
        text = container.child(
            resourceId=ResourceID.BUTTON,
            classNameMatches=ClassName.BUTTON_OR_TEXTVIEW_REGEX,
        )
        if not isinstance(text, str):
            text = text.get_text() if text.exists() else ""
        return text in ["Following", "Requested"]


class PostsGridView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def scrollDown(self):
        coordinator_layout = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.COORDINATOR_ROOT_LAYOUT)
        )
        if coordinator_layout.exists():
            coordinator_layout.scroll(Direction.DOWN)
            return True

        return False

    def _get_post_view(self):
        return self.device.find(resourceIdMatches=case_insensitive_re(ResourceID.LIST))

    def _is_still_on_profile(self) -> bool:
        """The profile tab bar is only visible while no post is opened."""
        profile_tabs = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.PROFILE_TABS_CONTAINER)
        )
        return profile_tabs.exists(Timeout.SHORT)

    def navigateToPost(self, row, col):
        from InstaAddict.core.telemetry import PerformanceTracker

        with PerformanceTracker.get_instance().measure("view", "post_open"):
            post_list_view = self._get_post_view()
            post_list_view.wait(Timeout.MEDIUM)
            OFFSET = 1  # row with post starts from index 1
            row_view = post_list_view.child(index=row + OFFSET)
            if not row_view.exists():
                return None, None, None
            post_view = row_view.child(index=col)
            if not post_view.exists():
                return None, None, None
            content_desc = post_view.ui_info()["contentDescription"]
            media_type, obj_count = PostsViewList.detect_media_type(content_desc)
            opened_post_view = OpenedPostView(self.device)
            for attempt in range(2):
                # Fast, crisp tap: calculate center coordinates to avoid lingering touches triggering Peek Preview
                try:
                    bounds = post_view.get_bounds()
                    x_center = (bounds["left"] + bounds["right"]) // 2
                    y_center = (bounds["top"] + bounds["bottom"]) // 2
                    self.device.deviceV2.click(x_center, y_center)
                except Exception:
                    post_view.click()

                if opened_post_view.is_peek_preview_opened():
                    logger.info("Peek Preview detected on post thumbnail.")
                    opened_post_view.is_peek = True
                    return opened_post_view, media_type, obj_count
                if opened_post_view.is_post_opened() or not self._is_still_on_profile():
                    return opened_post_view, media_type, obj_count
                if attempt == 0:
                    logger.debug("Post didn't open, trying one more click...")
                    # Re-resolve both row_view and post_view — the recycler may have
                    # re-bound the previous child reference after a layout pass.
                    row_view = post_list_view.child(index=row + OFFSET)
                    if not row_view.exists():
                        break
                    post_view = row_view.child(index=col)
                    if not post_view.exists():
                        break
            logger.debug(
                f"Click on row {row}, column {col} didn't open any post (empty grid slot?)."
            )
            return None, None, None



class ProfileView(ActionBarView):
    def __init__(self, device: DeviceFacade, is_own_profile=False):
        super().__init__(device)
        self.device = device
        self.is_own_profile = is_own_profile

    def _is_still_on_profile(self) -> bool:
        """The profile tab bar or header is only visible while on a profile."""
        profile_tabs = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.PROFILE_TABS_CONTAINER)
        )
        return profile_tabs.exists(Timeout.SHORT)

    def navigateToOptions(self):
        logger.debug("Navigate to Options")
        if self.action_bar is None:
            self.action_bar = self._getActionBar()
        if self.action_bar is None:
            logger.warning("Action bar not found in ProfileView.")
            return None
        button = self.action_bar.child(index=2)
        button.click()

        return OptionsView(self.device)

    def _getActionBarTitleBtn(self, watching_stories=False, error=True):
        try:
            bar = case_insensitive_re(
                [
                    ResourceID.TITLE_VIEW,
                    ResourceID.ACTION_BAR_TITLE,
                    ResourceID.ACTION_BAR_LARGE_TITLE,
                    ResourceID.ACTION_BAR_TEXTVIEW_TITLE,
                    ResourceID.ACTION_BAR_TITLE_AUTO_SIZE,
                    ResourceID.ACTION_BAR_LARGE_TITLE_AUTO_SIZE,
                ]
            )
            action_bar = self.device.find(
                resourceIdMatches=bar,
            )
            timeout = Timeout.LONG if error else Timeout.SHORT
            if not watching_stories and action_bar.exists(timeout) or watching_stories:
                return action_bar

            # IG v446 fallback: The dedicated action bar resource IDs were removed.
            # The title is now simply a TextView at the top of the screen containing the username.
            logger.debug("Action bar IDs not found. Falling back to layout inspection.")
            top_text = self.device.find(
                classNameMatches="(?i)TextView|Button", textMatches="(?i)^[-a-z0-9_.]+$"
            )
            if top_text.exists(Timeout.SHORT):
                return top_text

            if error:
                logger.error(
                    "Unable to find action bar! (The element with the username at top)"
                )
            return None
        except DeviceFacade.AppHasCrashed:
            return None

    def _getSomeText(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Get some text from the profile to check the language"""
        try:
            post = (
                self.device.find(
                    resourceIdMatches=ResourceID.ROW_PROFILE_HEADER_TEXTVIEW_POST_CONTAINER
                )
                .child(index=1)
                .get_text()
            )
            followers = (
                self.device.find(
                    resourceIdMatches=ResourceID.ROW_PROFILE_HEADER_FOLLOWERS_CONTAINER
                )
                .child(index=1)
                .get_text()
            )
            following = (
                self.device.find(
                    resourceIdMatches=ResourceID.ROW_PROFILE_HEADER_FOLLOWING_CONTAINER
                )
                .child(index=1)
                .get_text()
            )
            if post and followers and following:
                return post.casefold(), followers.casefold(), following.casefold()
        except Exception as e:
            logger.debug(f"Exception reading profile header children: {e}")

        # Modern Instagram v446 fallback
        try:
            post_lbl = self.device.find(
                resourceIdMatches=r".*profile_header_familiar_post_count_label|.*profile_header.*post.*label"
            )
            fol_lbl = self.device.find(
                resourceIdMatches=r".*profile_header_familiar_followers_label|.*profile_header.*followers.*label"
            )
            ing_lbl = self.device.find(
                resourceIdMatches=r".*profile_header_familiar_following_label|.*profile_header.*following.*label"
            )
            if post_lbl.exists(Timeout.SHORT) and fol_lbl.exists(Timeout.SHORT) and ing_lbl.exists(Timeout.SHORT):
                p = post_lbl.get_text()
                f = fol_lbl.get_text()
                i = ing_lbl.get_text()
                if p and f and i:
                    return p.casefold(), f.casefold(), i.casefold()
        except Exception as e:
            logger.debug(f"Exception in modern profile label fallback: {e}")

        logger.warning(
            "Can't get post/followers/following text for check the language! Save a crash to understand the reason."
        )
        save_crash(self.device)
        return None, None, None

    def _profile_tab_button(self) -> bool:
        if ResourceID is not None and hasattr(ResourceID, "PROFILE_TAB"):
            obj = self.device.find(resourceIdMatches=ResourceID.PROFILE_TAB)
            if obj.exists(Timeout.SHORT):
                obj.click()
                return True
        return False

    def _new_ui_profile_button(self) -> bool:
        obj = self.device.find(
            classNameMatches=ClassName.BUTTON_OR_FRAME_LAYOUT_REGEX,
            descriptionMatches=case_insensitive_re(TabBarText.PROFILE_CONTENT_DESC),
        )
        if obj.exists(Timeout.SHORT):
            obj.click()
            return True
        obj = self.device.find(
            descriptionMatches=case_insensitive_re(TabBarText.PROFILE_CONTENT_DESC)
        )
        if obj.exists(Timeout.SHORT):
            obj.click()
            return True
        return False

    def _old_ui_profile_button(self) -> bool:
        obj = self.device.find(resourceIdMatches=ResourceID.TAB_AVATAR)
        if obj.exists(Timeout.SHORT):
            obj.click()
            return True
        return False

    def click_on_avatar(self):
        max_attempts = 4
        for attempt in range(max_attempts):
            if self._profile_tab_button():
                return
            if self._new_ui_profile_button():
                return
            if self._old_ui_profile_button():
                return
            logger.debug(
                f"Profile button not visible yet (attempt {attempt+1}/{max_attempts}), pressing back..."
            )
            self.device.back()

    def getFollowButton(self):
        button_regex = f"{ClassName.BUTTON}|{ClassName.TEXT_VIEW}"
        labels = "following|requested|follow back|follow"
        # The non-clickable profile count label also says "following". Prefer
        # the action's resource ID; text-only fallbacks must be clickable.
        selectors = (
            {"resourceIdMatches": r".*:id/(profile_header_follow_button|button_profile_header_follow)"},
            {
                "classNameMatches": button_regex,
                "textMatches": case_insensitive_re(f"^({labels})$"),
                "clickable": True,
            },
            {
                "descriptionMatches": case_insensitive_re(f"^({labels})(\\s.*)?$"),
                "clickable": True,
            },
        )
        statuses = {
            "following": FollowStatus.FOLLOWING,
            # Pending requests must remain ineligible for another follow.
            "requested": FollowStatus.FOLLOWING,
            "follow back": FollowStatus.FOLLOW_BACK,
            "follow": FollowStatus.FOLLOW,
        }
        for selector in selectors:
            button = self.device.find(**selector)
            if not button.exists(Timeout.SHORT):
                continue
            text = (button.get_text() or "").strip().casefold()
            if text in statuses:
                return button, statuses[text]
            description = (button.get_property("contentDescription") or "").strip()
            match = re.match(rf"^({labels})(?:\s|$)", description, re.IGNORECASE)
            if match:
                return button, statuses[match.group(1).casefold()]
        logger.warning("The follow button doesn't exist! Maybe the profile is not loaded!")
        return None, FollowStatus.NONE

    def has_follows_you_badge(self) -> bool:
        """
        Check if profile header displays 'Follows you' badge or context label.
        Used to verify whether the candidate follows you without navigating into
        their following list.
        """
        # Tier 1: Dedicated subtitle TextView with exact text 'Follows you'
        badge = self.device.find(
            className=ClassName.TEXT_VIEW,
            textMatches="(?i)^Follows you$",
        )
        if badge.exists(Timeout.SHORT):
            return True

        # Tier 2: Accessibility contentDescription on any view
        badge_desc = self.device.find(
            descriptionMatches="(?i)^Follows you$",
        )
        if badge_desc.exists(Timeout.SHORT):
            return True

        # Tier 3: Follow context text / mutual label containing 'follows you'
        context_id = getattr(ResourceID, "PROFILE_HEADER_FOLLOW_CONTEXT_TEXT", ".*follow_context.*")
        context = self.device.find(
            resourceIdMatches=f"{context_id}|.*follow_context.*"
        )
        if context.exists(Timeout.SHORT):
            txt = (context.get_text() or "").strip()
            if "follows you" in txt.casefold():
                return True

        # Tier 4: Check if follow button says 'Follow Back' (when user not following them)
        follow_btn = self.device.find(
            classNameMatches=ClassName.BUTTON_OR_TEXTVIEW_REGEX,
            textMatches="(?i)^Follow back$",
        )
        if follow_btn.exists(Timeout.SHORT):
            return True

        return False

    def getUsername(self, watching_stories=False, error=True):
        try:
            action_bar = self._getActionBarTitleBtn(watching_stories, error=error)
            if action_bar is not None:
                return action_bar.get_text(error=not watching_stories and error).strip()
        except DeviceFacade.AppHasCrashed:
            return None
        except Exception as e:
            logger.debug(f"getUsername exception: {e}")
            return None
        if not watching_stories and error:
            logger.error("Cannot get username.")
        return None

    def getLinkInBio(self):
        obj = self.device.find(resourceIdMatches=ResourceID.PROFILE_HEADER_WEBSITE)
        if obj.exists():
            website = obj.get_text()
            return website if website != "" else None
        return None

    def getMutualFriends(self) -> int:
        logger.debug("Looking for mutual friends tab.")
        follow_context = self.device.find(
            resourceIdMatches=ResourceID.PROFILE_HEADER_FOLLOW_CONTEXT_TEXT
        )
        if follow_context.exists():
            text = follow_context.get_text()
            mutual_friends = re.finditer(
                r"((?P<others>\s\d+\s)|(?P<extra>,))",
                text,
                re.IGNORECASE,
            )
            n_others = 0
            n_extra = 0
            for match in mutual_friends:
                if match.group("others"):
                    n_others = int(match.group("others"))
                if match.group("extra"):
                    n_extra = 2
            if n_others != 0:
                mutual_friends = n_others + n_extra if n_extra != 0 else n_others + 1
            else:
                mutual_friends = n_extra if n_extra != 0 else 1
        else:
            mutual_friends = 0
        return mutual_friends

    def _parseCounter(self, raw_text: str) -> Optional[int]:
        multiplier = 1
        regex = r"(?!(K|M|\.))\D+"
        subst = "."
        text = re.sub(regex, subst, raw_text)
        if "K" in text:
            value = float(text.replace("K", ""))
            multiplier = 1_000
        elif "M" in text:
            value = float(text.replace("M", ""))
            multiplier = 1_000_000
        else:
            try:
                value = int(text.replace(".", ""))
            except ValueError:
                logger.error(f"Cannot parse {repr(raw_text)}.")
                return None
        return int(value * multiplier)

    def _getFollowersTextView(self):
        followers_text_view = self.device.find(
            resourceIdMatches=case_insensitive_re(
                ResourceID.ROW_PROFILE_HEADER_TEXTVIEW_FOLLOWERS_COUNT
            ),
            className=ClassName.TEXT_VIEW,
        )
        followers_text_view.wait(Timeout.MEDIUM)
        return followers_text_view

    def getFollowersCount(self) -> Optional[int]:
        followers = None
        followers_text_view = self._getFollowersTextView()
        if followers_text_view.exists():
            followers_text = followers_text_view.get_text()
            if followers_text:
                followers = self._parseCounter(followers_text)
            else:
                logger.error("Cannot get followers count text.")
        else:
            logger.error("Cannot find followers count view.")

        return followers

    def _getFollowingTextView(self):
        following_text_view = self.device.find(
            resourceIdMatches=case_insensitive_re(
                ResourceID.ROW_PROFILE_HEADER_TEXTVIEW_FOLLOWING_COUNT
            ),
            className=ClassName.TEXT_VIEW,
        )
        following_text_view.wait(Timeout.MEDIUM)
        return following_text_view

    def getFollowingCount(self) -> Optional[int]:
        following = None
        following_text_view = self._getFollowingTextView()
        if following_text_view.exists(Timeout.MEDIUM):
            following_text = following_text_view.get_text()
            if following_text:
                following = self._parseCounter(following_text)
            else:
                logger.error("Cannot get following count text.")
        else:
            logger.error("Cannot find following count view.")

        return following

    def getPostsCount(self) -> int:
        post_count_view = self.device.find(
            resourceIdMatches=case_insensitive_re(
                ResourceID.ROW_PROFILE_HEADER_TEXTVIEW_POST_COUNT
            )
        )
        if post_count_view.exists(Timeout.MEDIUM):
            count = post_count_view.get_text()
            if count is not None:
                return self._parseCounter(count)
        logger.error("Cannot get posts count text.")
        return 0

    def count_photo_in_view(self) -> Tuple[int, int]:
        """return rows filled and the number of post in the last row"""
        views = f"({ClassName.RECYCLER_VIEW}|{ClassName.VIEW})"
        grid_post = self.device.find(
            classNameMatches=views, resourceIdMatches=ResourceID.LIST
        )
        if not grid_post.exists(Timeout.MEDIUM):
            return 0, 0
        for i in range(2, 6):
            lin_layout = grid_post.child(index=i, className=ClassName.LINEAR_LAYOUT)
            if i == 5 or not lin_layout.exists():
                last_index = i - 1
                last_lin_layout = grid_post.child(index=last_index)
                for n in range(1, 4):
                    if n == 3 or not last_lin_layout.child(index=n).exists():
                        if n == 3:
                            return last_index, 0
                        else:
                            return last_index - 1, n

    def getProfileInfo(self):
        try:
            from InstaAddict.core.watchdog import record_heartbeat
            record_heartbeat("profile", "Reading profile counters")
        except Exception:
            pass
        username = self.getUsername()
        posts = self.getPostsCount()
        followers = self.getFollowersCount()
        following = self.getFollowingCount()

        return username, posts, followers, following

    def getProfileBiography(self) -> str:
        biography = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.PROFILE_HEADER_BIO_TEXT),
            className=ClassName.TEXT_VIEW,
        )
        if biography.exists():
            biography_text = biography.get_text()
            # If the biography is very long, blabla text and end with "...more" click the bottom of the text and get the new text
            is_long_bio = re.compile(
                r"{0}$".format("… more"), flags=re.IGNORECASE
            ).search(biography_text)
            if is_long_bio is not None:
                logger.debug('Found "… more" in bio - trying to expand')
                username = self.getUsername()
                biography.click(Location.BOTTOMRIGHT)
                if username != self.getUsername():
                    logger.debug(
                        "We're not in the same page - did we click a hashtag or a tag? Go back."
                    )
                    self.device.back()
                    logger.info("Failed to expand biography - checking short view.")
                return biography.get_text()
            return biography_text
        return ""

    def getFullName(self):
        full_name_view = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.PROFILE_HEADER_FULL_NAME),
            className=ClassName.TEXT_VIEW,
        )
        if full_name_view.exists(Timeout.SHORT):
            fullname_text = full_name_view.get_text()
            if fullname_text is not None:
                return fullname_text
        return ""

    def isPrivateAccount(self):
        private_profile_view = self.device.find(
            resourceIdMatches=case_insensitive_re(
                [
                    ResourceID.PRIVATE_PROFILE_EMPTY_STATE,
                    ResourceID.ROW_PROFILE_HEADER_EMPTY_PROFILE_NOTICE_TITLE,
                    ResourceID.ROW_PROFILE_HEADER_EMPTY_PROFILE_NOTICE_CONTAINER,
                ]
            )
        )
        return private_profile_view.exists()

    def StoryRing(self) -> DeviceFacade.View:
        return self.device.find(
            resourceId=ResourceID.REEL_RING,
        )

    def live_marker(self) -> DeviceFacade.View:
        return self.device.find(resourceId=ResourceID.LIVE_BADGE_VIEW)

    def profileImage(self):
        return self.device.find(
            resourceId=ResourceID.ROW_PROFILE_HEADER_IMAGEVIEW,
        )

    def navigateToFollowers(self):
        logger.info("Navigate to followers.")
        followers_button = None
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                from InstaAddict.core.watchdog import record_heartbeat

                record_heartbeat("profile_view", f"polling followers container attempt {attempt + 1}")
            except Exception:
                pass
            btn = self.device.find(
                resourceIdMatches=ResourceID.ROW_PROFILE_HEADER_FOLLOWERS_CONTAINER
            )
            if not btn.exists(Timeout.SHORT):
                btn = self.device.find(
                    descriptionMatches=case_insensitive_re(r".*follower.*")
                )
            if not btn.exists(Timeout.SHORT):
                btn = self.device.find(
                    textMatches=case_insensitive_re(r".*[0-9]+(\.[0-9]+)?[kmb]?\s*followers.*")
                )
            if btn.exists(Timeout.SHORT):
                followers_button = btn
                break
            if attempt < max_attempts - 1:
                logger.debug(
                    f"Waiting for profile followers container to render (attempt {attempt + 1}/{max_attempts})..."
                )
                random_sleep(1.0, 2.0, modulable=False)

        if followers_button and followers_button.exists(Timeout.SHORT):
            followers_button.click()
            followers_tab = self.device.find(
                resourceIdMatches=ResourceID.UNIFIED_FOLLOW_LIST_TAB_LAYOUT
            ).child(textContains="Followers")
            if followers_tab.exists(Timeout.LONG):
                if not followers_tab.get_property("selected"):
                    followers_tab.click()
                return True
            # Fallback: Instagram often navigates directly into the Followers list
            following_list = self.device.find(
                resourceIdMatches=f"{ResourceID.FOLLOW_LIST_CONTAINER}|.*follow_list.*|.*recycler.*"
            )
            if following_list.exists(Timeout.SHORT):
                logger.debug("Followers list container detected directly.")
                return True
            tab_layout = self.device.find(
                resourceIdMatches=ResourceID.UNIFIED_FOLLOW_LIST_TAB_LAYOUT
            )
            if tab_layout.exists(Timeout.SHORT):
                return True
            return True
        else:
            logger.error("Can't find followers tab!")
            return False

    def harvest_visible_followers(self, max_scrolls: int = 2) -> list:
        """
        Harvest visible follower usernames from the Followers list container.
        Bounded by max_scrolls to minimize action footprint.
        """
        harvested = []
        seen = set()
        user_list_id = getattr(ResourceID, "USER_LIST_CONTAINER", ".*user_list.*")
        primary_name_id = getattr(ResourceID, "ROW_USER_PRIMARY_NAME", ".*row_user_primary_name.*")
        list_id = getattr(ResourceID, "LIST", ".*list.*")
        for scroll_i in range(max_scrolls + 1):
            user_list = self.device.find(
                resourceIdMatches=user_list_id,
            )
            try:
                row_height, n_users = inspect_current_view(user_list)
            except EmptyList:
                logger.info("Followers list is empty or reached end of list.")
                break
            for item in user_list:
                cur_row_height = item.get_height()
                if cur_row_height < row_height:
                    continue
                user_name_view = item.child(
                    resourceIdMatches=f"{primary_name_id}|.*follow_list_username.*|.*row_profile_header_username.*"
                )
                if not user_name_view.exists():
                    user_info_view = item.child(index=1)
                    if user_info_view.exists():
                        candidate = user_info_view.child(index=0).child()
                        if candidate.exists():
                            user_name_view = candidate
                if not user_name_view.exists():
                    text_views = item.child(className=ClassName.TEXT_VIEW)
                    for tv in text_views:
                        txt = (tv.get_text() or "").strip()
                        if txt and not any(kw in txt.casefold() for kw in ["following", "follow", "remove", "message", "requested"]):
                            user_name_view = tv
                            break
                if user_name_view.exists():
                    uname = (user_name_view.get_text() or "").strip()
                    if uname and uname.casefold() not in seen:
                        seen.add(uname.casefold())
                        harvested.append(uname)

            if scroll_i < max_scrolls:
                list_view = self.device.find(resourceId=list_id)
                if list_view.exists(Timeout.SHORT):
                    list_view.scroll(Direction.DOWN)
                else:
                    break
        return harvested

    def navigateToFollowing(self):
        logger.info("Navigate to following.")
        following_button = self.device.find(
            resourceIdMatches=ResourceID.ROW_PROFILE_HEADER_FOLLOWING_CONTAINER
        )
        if following_button.exists(Timeout.LONG):
            following_button.click_retry()
            following_tab = self.device.find(
                resourceIdMatches=ResourceID.UNIFIED_FOLLOW_LIST_TAB_LAYOUT
            ).child(textContains="Following")
            if following_tab.exists(Timeout.LONG):
                if not following_tab.get_property("selected"):
                    following_tab.click()
                return True
            # Fallback: Instagram often navigates directly into the Following list
            following_list = self.device.find(
                resourceIdMatches=f"{ResourceID.FOLLOW_LIST_CONTAINER}|.*follow_list.*|.*recycler.*"
            )
            if following_list.exists(Timeout.SHORT):
                logger.debug("Following list container detected directly.")
                return True
            tab_layout = self.device.find(
                resourceIdMatches=ResourceID.UNIFIED_FOLLOW_LIST_TAB_LAYOUT
            )
            if tab_layout.exists(Timeout.SHORT):
                return True
            return True
        else:
            logger.error("Can't find following tab!")
            return False

    def navigateToMutual(self):
        logger.info("Navigate to mutual friends.")
        has_mutual = False
        follow_context = self.device.find(
            resourceIdMatches=ResourceID.PROFILE_HEADER_FOLLOW_CONTEXT_TEXT
        )
        if follow_context.exists():
            follow_context.click()
            has_mutual = True
        return has_mutual

    def swipe_to_fit_posts(self):
        """calculate the right swipe amount necessary to see 12 photos"""
        displayWidth = self.device.get_info()["displayWidth"]
        element_to_swipe_over_obj = self.device.find(
            resourceIdMatches=ResourceID.PROFILE_TABS_CONTAINER
        )
        for _ in range(2):
            if not element_to_swipe_over_obj.exists():
                UniversalActions(self.device)._swipe_points(
                    direction=Direction.DOWN, delta_y=randint(300, 350)
                )
                element_to_swipe_over_obj = self.device.find(
                    resourceIdMatches=ResourceID.PROFILE_TABS_CONTAINER
                )
                continue

            element_to_swipe_over = element_to_swipe_over_obj.get_bounds()["top"]
            try:
                bar_container = self.device.find(
                    resourceIdMatches=ResourceID.ACTION_BAR_CONTAINER
                ).get_bounds()["bottom"]

                logger.info("Scrolled down to see more posts.")
                self.device.swipe_points(
                    displayWidth / 2,
                    element_to_swipe_over,
                    displayWidth / 2,
                    bar_container,
                )
                return element_to_swipe_over - bar_container
            except Exception as e:
                logger.debug(f"Exception: {e}")
                logger.info("I'm not able to scroll down.")
                return 0
        logger.warning(
            "Maybe a private/empty profile in which check failed or after whatching stories the view moves down :S.. Skip"
        )
        return -1

    def navigateToPostsTab(self):
        self._navigateToTab(TabBarText.POSTS_CONTENT_DESC)
        return PostsGridView(self.device)

    def navigateToIgtvTab(self):
        self._navigateToTab(TabBarText.IGTV_CONTENT_DESC)
        raise Exception("Not implemented")

    def navigateToReelsTab(self):
        self._navigateToTab(TabBarText.REELS_CONTENT_DESC)
        raise Exception("Not implemented")

    def navigateToEffectsTab(self):
        self._navigateToTab(TabBarText.EFFECTS_CONTENT_DESC)
        raise Exception("Not implemented")

    def navigateToPhotosOfYouTab(self):
        self._navigateToTab(TabBarText.PHOTOS_OF_YOU_CONTENT_DESC)
        raise Exception("Not implemented")

    def _navigateToTab(self, tab: TabBarText):
        tabs_view = self.device.find(
            resourceIdMatches=case_insensitive_re(ResourceID.PROFILE_TAB_LAYOUT),
            className=ClassName.HORIZONTAL_SCROLL_VIEW,
        )
        button = tabs_view.child(
            descriptionMatches=case_insensitive_re(tab),
            resourceIdMatches=case_insensitive_re(ResourceID.PROFILE_TAB_ICON_VIEW),
            className=ClassName.IMAGE_VIEW,
        )

        attempts = 0
        while not button.exists():
            attempts += 1
            self.device.swipe(Direction.UP, scale=0.1)
            if attempts > 2:
                logger.error(f"Cannot navigate to tab '{tab}'")
                save_crash(self.device)
                return

        button.click()

    def _getRecyclerView(self):
        views = f"({ClassName.RECYCLER_VIEW}|{ClassName.VIEW})"

        return self.device.find(classNameMatches=views)


class FollowingView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def do_unfollow_from_list(self, username, user_row=None) -> Optional[bool]:
        """
        :return: True if unfollowed, False on failure,
                 None if the account has no Unfollow option at all
        """
        exists = False
        username_row = ""
        if user_row is None:
            user_row = self.device.find(
                resourceId=ResourceID.FOLLOW_LIST_CONTAINER,
                className=ClassName.LINEAR_LAYOUT,
            )
        if user_row.exists(Timeout.MEDIUM):
            exists = True
            username_row = user_row.child(index=1).child().child().get_text()
        if not exists or username_row != username:
            logger.error(f"Cannot find {username} in following list.")
            return False

        UNFOLLOW_REGEX = "^Unfollow$"

        # Fast path: some rows show a direct "Following" button we can tap
        # straight away, instead of going through the three-dots menu.
        following_button = user_row.child(textMatches="(?i)^Following$")
        if not following_button.exists(Timeout.SHORT):
            following_button = user_row.child(index=2, textMatches="(?i)^Following$")
        if following_button.exists(Timeout.SHORT):
            logger.debug("Direct 'Following' button found, using it.")
            following_button.click()
            random_sleep(0, 1, modulable=False)
        else:
            # new layout: unfollow is behind the three-dots menu on each row
            options_button = user_row.child(
                descriptionMatches=case_insensitive_re("options|more")
            )
            if not options_button.exists(Timeout.SHORT):
                # fallback: it's the last item on the row, after the Message/Following button
                options_button = user_row.child(index=3)
            if not options_button.exists():
                logger.error(f"Cannot find the options button for {username}.")
                save_crash(self.device)
                return False
            logger.debug("Opening the three-dots menu.")
            options_button.click()

            unfollow_row = self.device.find(
                classNameMatches=ClassName.BUTTON_OR_TEXTVIEW_REGEX,
                textMatches=UNFOLLOW_REGEX,
            )
            if not unfollow_row.exists(Timeout.SHORT):
                logger.info(
                    f"@{username} has no Unfollow option. Can't unfollow from the list."
                )
                self.device.back()
                return None
            logger.debug("Pressing on Unfollow.")
            unfollow_row.click()
            random_sleep(0, 1, modulable=False)

        # private accounts ask for an extra confirmation
        confirm_unfollow_button = self.device.find(
            classNameMatches=ClassName.BUTTON_OR_TEXTVIEW_REGEX,
            textMatches=UNFOLLOW_REGEX,
        )
        if confirm_unfollow_button.exists(Timeout.SHORT):
            logger.debug("Confirm unfollow private account.")
            confirm_unfollow_button.click()
            random_sleep(0, 1, modulable=False)

        UniversalActions.detect_block(self.device)
        # "Follow back" shows up for accounts that follow you: the unfollow worked
        FOLLOW_REGEX = "^Follow$|^Follow back$"
        follow_button = user_row.child(textMatches=case_insensitive_re(FOLLOW_REGEX))
        if not follow_button.exists(Timeout.SHORT):
            follow_button = user_row.child(index=2, textMatches=case_insensitive_re(FOLLOW_REGEX))
        if follow_button.exists(Timeout.SHORT):
            logger.info(
                f"{username} unfollowed.",
                extra={"color": f"{Style.BRIGHT}{Fore.GREEN}"},
            )
            return True
        logger.error(f"Cannot confirm unfollow for {username}.")
        save_crash(self.device)
        return False


class FollowersView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def _find_user_to_remove(self, username):
        row = self.device.find(resourceId=ResourceID.FOLLOW_LIST_CONTAINER)
        return row if row.child(textMatches=username).exists() else None

    def _get_remove_button(self, row_obj):
        REMOVE_TEXT = "^Remove$"
        return row_obj.child(
            resourceId=ResourceID.BUTTON, textMatches=case_insensitive_re(REMOVE_TEXT)
        )

    def _click_button(self, obj, obj_name):
        if obj.exists(Timeout.SHORT):
            logger.info(f"Pressing on {obj_name} button.")
            obj.click()
            return True
        logger.info(f"Object {obj_name} doesn't exists. Can't press on it!")
        return False

    def _confirm_remove_follower(self):
        obj = self.device.find(resourceId=ResourceID.ACTION_SHEET_ROW_TEXT_VIEW)
        return self._click_button(obj, "remove confirmation")

    def remove_follower(self, username):
        user_row = self._find_user_to_remove(username)
        if user_row is not None and user_row.exists():
            if self._click_button(self._get_remove_button(user_row), "remove"):
                return self._confirm_remove_follower()
        return False


class CurrentStoryView:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def getStoryFrame(self) -> DeviceFacade.View:
        return self.device.find(
            resourceId=ResourceID.REEL_VIEWER_MEDIA_CONTAINER,
        )

    def getUsername(self) -> str:
        reel_viewer_title = self.device.find(
            resourceId=ResourceID.REEL_VIEWER_TITLE,
        )
        reel_exists = reel_viewer_title.exists(ignore_bug=True)
        if reel_exists == "BUG!":
            return reel_exists
        return (
            ""
            if not reel_exists
            else reel_viewer_title.get_text(error=False).replace(" ", "")
        )

    def getTimestamp(self) -> Optional[datetime.datetime]:
        reel_viewer_timestamp = self.device.find(
            resourceId=ResourceID.REEL_VIEWER_TIMESTAMP,
        )
        if reel_viewer_timestamp.exists():
            timestamp = reel_viewer_timestamp.get_text().strip()
            value = int(re.sub("[^0-9]", "", timestamp))
            if timestamp[-1] == "s":
                return datetime.timestamp(
                    datetime.datetime.now() - datetime.timedelta(seconds=value)
                )
            elif timestamp[-1] == "m":
                return datetime.timestamp(
                    datetime.datetime.now() - datetime.timedelta(minutes=value)
                )
            elif timestamp[-1] == "h":
                return datetime.timestamp(
                    datetime.datetime.now() - datetime.timedelta(hours=value)
                )
            else:
                return datetime.timestamp(
                    datetime.datetime.now() - datetime.timedelta(days=value)
                )
        return None


class UniversalActions:
    def __init__(self, device: DeviceFacade):
        self.device = device

    def _swipe_points(
        self,
        direction: Direction,
        start_point_x=-1,
        start_point_y=-1,
        delta_x=-1,
        delta_y=450,
    ) -> None:
        displayWidth = self.device.get_info()["displayWidth"]
        displayHeight = self.device.get_info()["displayHeight"]
        middle_point_x = displayWidth / 2
        if start_point_y == -1:
            start_point_y = displayHeight / 2
        if direction == Direction.UP:
            if start_point_y + delta_y > displayHeight:
                delta = start_point_y + delta_y - displayHeight
                start_point_y = start_point_y - delta
            self.device.swipe_points(
                middle_point_x,
                start_point_y,
                middle_point_x,
                start_point_y + delta_y,
            )
        elif direction == Direction.DOWN:
            if start_point_y - delta_y < 0:
                delta = abs(start_point_y - delta_y)
                start_point_y = start_point_y + delta
            self.device.swipe_points(
                middle_point_x,
                start_point_y,
                middle_point_x,
                start_point_y - delta_y,
            )
        elif direction == Direction.LEFT:
            if start_point_x == -1:
                start_point_x = displayWidth * 2 / 3
            if delta_x == -1:
                delta_x = uniform(0.95, 1.25) * (displayWidth / 2)
            self.device.swipe_points(
                start_point_x,
                start_point_y,
                start_point_x - delta_x,
                start_point_y,
            )

    def press_button_back(self) -> None:
        back_button = self.device.find(
            resourceIdMatches=ResourceID.ACTION_BAR_BUTTON_BACK
        )
        if back_button.exists():
            logger.info("Pressing on back button.")
            back_button.click()

    def _reload_page(self) -> None:
        logger.debug("Reload page.")
        self._swipe_points(direction=Direction.UP)
        random_sleep(inf=5, sup=8, modulable=False)

    _micro_stall_sentinel = None

    @classmethod
    def get_micro_stall_sentinel(cls):
        if cls._micro_stall_sentinel is None:
            from InstaAddict.core.telemetry import MicroStallSentinel

            cls._micro_stall_sentinel = MicroStallSentinel(
                timeout_threshold=3, stagnation_seconds=20.0
            )
        return cls._micro_stall_sentinel

    @classmethod
    def check_micro_stall(cls, device, context: str = "") -> bool:
        """Check if micro-stall has occurred. If so, execute proactive soft recovery and increment telemetry."""
        sentinel = cls.get_micro_stall_sentinel()
        if sentinel.record_timeout(context):
            cls.dismiss_peek_if_open(device)
            cls.dismiss_dialog(device)
            device.back()
            random_sleep(1.0, 2.0, modulable=False)
            try:
                from InstaAddict.core.session_state import SessionState

                session = SessionState.get_active()
                if session:
                    session.increment_micro_stall_escapes()
            except Exception:
                pass
            return True
        return False

    @staticmethod
    def escape_in_app_browser(device) -> bool:
        """
        Detects if the bot has accidentally navigated into an in-app browser
        (such as BrowserLiteInMainProcessIGActivity) or an external browser/app,
        and safely dismisses it to restore the main Instagram UI.
        """
        escaped = False
        try:
            current_app = {}
            if hasattr(device, "deviceV2") and hasattr(device.deviceV2, "app_current"):
                raw_app = device.deviceV2.app_current()
                if isinstance(raw_app, dict):
                    current_app = raw_app

            pkg = current_app.get("package", "")
            act = current_app.get("activity", "")
            app_id = getattr(device, "app_id", "com.instagram.android")

            is_browser_activity = bool(
                act
                and any(
                    b in act.lower()
                    for b in ["browserlite", "inappbrowser", "browseractivity"]
                )
            )
            system_packages = {
                "com.android.systemui",
                "android",
                "com.google.android.inputmethod.latin",
            }
            is_foreign_package = bool(
                pkg and pkg != app_id and pkg not in system_packages
            )

            close_btn = device.find(
                resourceIdMatches=ResourceID.IG_BROWSER_CLOSE_BUTTON
            )
            browser_root = device.find(
                resourceIdMatches=ResourceID.BROWSER_LITE_ROOT_CONTAINER
            )
            browser_chrome = device.find(
                resourceIdMatches=ResourceID.BROWSER_CHROME_CONTAINER
            )
            webview_cont = device.find(resourceIdMatches=ResourceID.WEBVIEW_CONTAINER)
            webview_cls = device.find(className="android.webkit.WebView")
            close_desc = device.find(
                descriptionMatches=case_insensitive_re(
                    ["Close browser", "Close", "Done"]
                )
            )

            is_browser_ui = (
                close_btn.exists()
                or browser_root.exists()
                or browser_chrome.exists()
                or webview_cont.exists()
                or webview_cls.exists()
                or close_desc.exists()
            )

            if is_browser_activity or is_foreign_package or is_browser_ui:
                logger.warning(
                    f"In-app browser or advertisement overlay detected! (activity={act}, package={pkg}) Escaping..."
                )
                escaped = True

                if close_btn.exists():
                    logger.info(
                        "Clicking in-app browser close button (ig_browser_close_button)..."
                    )
                    close_btn.click()
                    random_sleep(inf=1, sup=2)
                elif close_desc.exists():
                    logger.info("Clicking browser close action by description...")
                    close_desc.click()
                    random_sleep(inf=1, sup=2)
                else:
                    logger.info("Pressing back to escape browser/external ad...")
                    device.back()
                    random_sleep(inf=1, sup=2)

                if hasattr(device, "deviceV2") and hasattr(
                    device.deviceV2, "app_current"
                ):
                    raw_new_app = device.deviceV2.app_current()
                    new_app = raw_new_app if isinstance(raw_new_app, dict) else {}
                    new_pkg = new_app.get("package", "")
                    new_act = new_app.get("activity", "")
                    if new_pkg != app_id or any(
                        b in new_act.lower() for b in ["browserlite", "inappbrowser"]
                    ):
                        logger.warning(
                            "Still inside browser after first dismissal attempt. Pressing back again..."
                        )
                        device.back()
                        random_sleep(inf=1, sup=2)

                    if new_pkg and new_pkg != app_id and new_pkg not in system_packages:
                        logger.warning(
                            f"Still in external app {new_pkg}. Relaunching {app_id}..."
                        )
                        device.deviceV2.app_start(app_id)
                        random_sleep(inf=2, sup=3)

        except Exception as e:
            logger.debug(f"escape_in_app_browser check encountered error: {e}")

        if escaped:
            try:
                from InstaAddict.core.session_state import SessionState

                active_ss = SessionState.get_active()
                if active_ss and hasattr(active_ss, "increment_ads_bypassed"):
                    active_ss.increment_ads_bypassed()
                else:
                    from InstaAddict.core.tui import DashboardManager

                    if DashboardManager.is_active():
                        dm = DashboardManager.get_instance()
                        if dm.bound_session_state and hasattr(
                            dm.bound_session_state, "increment_ads_bypassed"
                        ):
                            dm.bound_session_state.increment_ads_bypassed()
                        else:
                            dm.state.ads_bypassed += 1
                        dm.update_render()
            except Exception:
                pass

        return escaped

    @classmethod
    def dismiss_peek_if_open(cls, device) -> bool:
        """
        Detects if a lingering Peek Preview / long-press modal is obscuring the screen
        and dismisses it immediately.
        """
        try:
            d = getattr(device, "deviceV2", None)
            target_app = "com.instagram.android"
            if isinstance(getattr(device, "app_id", None), str):
                target_app = getattr(device, "app_id")
            if d is not None and hasattr(d, "app_current"):
                curr = d.app_current()
                if isinstance(curr, dict) and curr.get("package") != target_app:
                    return False

            if hasattr(device, "_ig_is_opened") and not device._ig_is_opened():
                return False

            opened_view = OpenedPostView(device)
            if opened_view.is_peek_preview_opened():
                logger.warning("Lingering Peek Preview detected on screen! Dismissing...")
                return opened_view.dismiss_peek()
        except DeviceFacade.AppHasCrashed:
            return False
        except Exception as e:
            logger.debug(f"dismiss_peek_if_open error: {e}")
        return False

    @classmethod
    def dismiss_dialog(cls, device, max_sweeps: int = 3) -> bool:
        """
        Detects and dismisses modal dialogs, popups, and intrusive system/app overlays
        such as 'Rate Instagram', notification requests, Google autofill, sync prompts, etc.
        Sweeps up to max_sweeps times to handle stacked dialogs.
        Returns True if any dialog was dismissed, False otherwise.
        """
        dismissed_any = False
        d = getattr(device, "deviceV2", None)
        app_id = getattr(device, "app_id", "com.instagram.android")

        def _find_elem(text_regex, fallback_list=None):
            if d is not None:
                try:
                    btn = d(textMatches=text_regex)
                    if btn.exists(timeout=1):
                        return btn
                except Exception:
                    pass
            elif hasattr(device, "find"):
                try:
                    query = case_insensitive_re(fallback_list or text_regex)
                    view = device.find(textMatches=query)
                    if view.exists():
                        return view
                except Exception:
                    pass
            return None

        for sweep in range(max_sweeps):
            dismissed_this_pass = False
            try:
                # 0. Check and dismiss lingering Peek Preview popup
                if cls.dismiss_peek_if_open(device):
                    dismissed_this_pass = True
                    dismissed_any = True
                    random_sleep(0.5, 1.0, modulable=False)
                    continue

                # 1. High-Priority Special Case: "Rate Instagram" / "Enjoying Instagram?"
                # Specifically click "No, thanks" or "Remind me later". STRICTLY avoid "Rate Instagram".
                rate_no_thanks = _find_elem(r"(?i)^(No,\s*thanks|No\s+thanks)$", ["No, thanks", "No thanks"])
                if rate_no_thanks is not None:
                    logger.info("Dismissing 'Rate Instagram' dialog by clicking 'No, thanks'...")
                    rate_no_thanks.click()
                    dismissed_this_pass = True
                    dismissed_any = True
                    random_sleep(1, 2, modulable=False)
                    continue

                rate_remind_later = _find_elem(r"(?i)^Remind\s+me\s+later$", "Remind me later")
                if rate_remind_later is not None:
                    logger.info("Dismissing 'Rate Instagram' dialog by clicking 'Remind me later'...")
                    rate_remind_later.click()
                    dismissed_this_pass = True
                    dismissed_any = True
                    random_sleep(1, 2, modulable=False)
                    continue

                # 2. Standard Negative/Dismiss Options (Notifications, Sync, FB Link, Promo, etc.)
                neg_options = [
                    "Not now",
                    "Cancel",
                    "Skip",
                    "Maybe later",
                    "Don't allow",
                    "Never",
                    "No",
                    "Close",
                ]
                neg_regex = r"(?i)^(Not now|Cancel|Skip|Maybe later|Don't allow|Never|No|Close)$"
                neg_btn = _find_elem(neg_regex, neg_options)
                if neg_btn is not None:
                    txt = None
                    if hasattr(neg_btn, "get_text"):
                        txt = neg_btn.get_text()
                    elif hasattr(neg_btn, "info") and isinstance(neg_btn.info, dict):
                        txt = neg_btn.info.get("text", "")
                    logger.info(f"Dismissing modal popup with negative action: '{txt or 'dismiss'}'...")
                    neg_btn.click()
                    dismissed_this_pass = True
                    dismissed_any = True
                    random_sleep(1, 2, modulable=False)
                    continue

                # 3. Informational/Consent OK Options
                info_options = ["OK", "Got it", "Continue", "I agree", "Dismiss", "Done"]
                info_regex = r"(?i)^(OK|Got it|Continue|I agree|Dismiss|Done)$"
                info_btn = _find_elem(info_regex, info_options)
                if info_btn is not None:
                    txt = None
                    if hasattr(info_btn, "get_text"):
                        txt = info_btn.get_text()
                    elif hasattr(info_btn, "info") and isinstance(info_btn.info, dict):
                        txt = info_btn.info.get("text", "")
                    logger.info(f"Dismissing informational modal dialog with action: '{txt or 'OK'}'...")
                    info_btn.click()
                    dismissed_this_pass = True
                    dismissed_any = True
                    random_sleep(1, 2, modulable=False)
                    continue

                # 4. Resource ID fallbacks (NEGATIVE_BUTTON, FIND_PEOPLE_DISMISS_BUTTON, etc.)
                res_attr = getattr(device, "ResourceID", None)
                if res_attr is not None and not isinstance(res_attr, type):
                    res_neg = getattr(res_attr, "NEGATIVE_BUTTON", f"{app_id}:id/negative_button")
                else:
                    res_neg = f"{app_id}:id/negative_button"

                try:
                    neg_res_btn = None
                    if d is not None:
                        btn = d(resourceIdMatches=res_neg)
                        if btn.exists(timeout=1):
                            neg_res_btn = btn
                    elif hasattr(device, "find"):
                        btn = device.find(resourceIdMatches=res_neg)
                        if btn.exists():
                            neg_res_btn = btn

                    if neg_res_btn is not None:
                        logger.info("Dismissing modal dialog via ResourceID.NEGATIVE_BUTTON...")
                        neg_res_btn.click()
                        dismissed_this_pass = True
                        dismissed_any = True
                        random_sleep(1, 2, modulable=False)
                        continue
                except Exception:
                    pass

                # System ANR Dialog ("Instagram isn't responding" -> "Wait")
                anr_btn = _find_elem(r"(?i)^Wait$", "Wait")
                if anr_btn is not None:
                    logger.warning("System ANR detected ('Wait'). Tapping Wait...")
                    try:
                        from InstaAddict.core.watchdog import record_heartbeat

                        record_heartbeat("anr_recovery", "Tapping Wait on system ANR dialog")
                    except Exception:
                        pass
                    anr_btn.click()
                    dismissed_this_pass = True
                    dismissed_any = True
                    random_sleep(1, 2, modulable=False)
                    continue

            except Exception as ex:
                logger.debug(f"dismiss_dialog check encountered error on pass {sweep + 1}: {ex}")

            if not dismissed_this_pass:
                break

        if dismissed_any:
            try:
                from InstaAddict.core.session_state import SessionState

                active_ss = SessionState.get_active()
                if active_ss and hasattr(active_ss, "increment_dialogs_dismissed"):
                    active_ss.increment_dialogs_dismissed()
                else:
                    from InstaAddict.core.tui import DashboardManager

                    if DashboardManager.is_active():
                        dm = DashboardManager.get_instance()
                        if dm.bound_session_state and hasattr(
                            dm.bound_session_state, "increment_dialogs_dismissed"
                        ):
                            dm.bound_session_state.increment_dialogs_dismissed()
                        else:
                            dm.state.dialogs_dismissed += 1
                        dm.update_render()
            except Exception:
                pass

        return dismissed_any

    @staticmethod
    def recover_stuck_screen(device, app_id: Optional[str] = None) -> bool:
        """
        Escalated self-healing recovery when the bot is stuck or unable to navigate.
        Stage 1: Dismiss any dialogs
        Stage 2: Press back up to 2 times
        Stage 3: Attempt Home tab tap
        Stage 4: Clean app relaunch (app_stop -> app_start) to reset app state
        """
        target_app = app_id or getattr(device, "app_id", "com.instagram.android")
        logger.warning(
            "Executing escalated stuck-screen recovery protocol...",
            extra={"color": f"{Style.BRIGHT}{Fore.YELLOW}"},
        )
        # Stage 1: Dialog dismissal
        if UniversalActions.dismiss_dialog(device):
            logger.info("Stuck screen recovery: dialog dismissed.")
            random_sleep(1, 2, modulable=False)

        # Stage 2: Back keys
        logger.info("Stuck screen recovery: issuing back keys...")
        device.back()
        random_sleep(1, 2, modulable=False)
        UniversalActions.dismiss_dialog(device)

        # Stage 3: Check if tab bar or home is available now
        d = getattr(device, "deviceV2", None)
        if d is not None:
            try:
                home_desc = d(descriptionMatches=r"(?i).*Home.*")
                if home_desc.exists(timeout=2):
                    logger.info("Stuck screen recovery: Home tab reached.")
                    return True
            except Exception:
                pass

        # Stage 4: Nuclear / Clean App Relaunch
        logger.warning(
            f"Stuck screen recovery escalating to Stage 4: Clean restart of {target_app}...",
            extra={"color": f"{Style.BRIGHT}{Fore.RED}"},
        )
        try:
            if d is not None:
                d.app_stop(target_app)
                random_sleep(2, 3, modulable=False)
                d.app_start(target_app)
                random_sleep(5, 7, modulable=False)
                UniversalActions.dismiss_dialog(device)
                return True
        except Exception as restart_err:
            logger.error(f"Failed to relaunch app during stuck-screen recovery: {restart_err}")

        return False

    @staticmethod
    def detect_block(device) -> bool:
        UniversalActions.escape_in_app_browser(device)
        if getattr(args, "disable_block_detection", False):
            return False
        logger.debug("Checking for block...")
        if hasattr(device, "deviceV2") and hasattr(device.deviceV2, "toast"):
            try:
                toast_msg = device.deviceV2.toast.get_message(1.0, 2.0, default="")
                if isinstance(toast_msg, str) and "blocked" in toast_msg.lower():
                    logger.warning("Toast detected!")
            except Exception:
                pass
        serius_block = device.find(
            className=ClassName.IMAGE,
            textMatches=case_insensitive_re("Force reset password icon"),
        )
        if serius_block.exists():
            raise ActionBlockedError("Serius block detected :(")
        block_dialog = device.find(
            resourceIdMatches=ResourceID.BLOCK_POPUP if ResourceID else None,
        )
        popup_body = device.find(
            resourceIdMatches=ResourceID.IGDS_HEADLINE_BODY if ResourceID else None,
        )
        popup_appears = block_dialog.exists() if block_dialog else False
        if popup_appears:
            if popup_body and popup_body.exists():
                regex = r".+deleted"
                is_post_deleted = re.match(regex, popup_body.get_text(), re.IGNORECASE)
                if is_post_deleted:
                    logger.info(f"{is_post_deleted.group()}")
                    logger.debug("Click on OK button.")
                    neg_btn = device.find(
                        resourceIdMatches=ResourceID.NEGATIVE_BUTTON if ResourceID else None,
                    )
                    if neg_btn:
                        neg_btn.click()
                    is_blocked = False
                else:
                    is_blocked = True
            else:
                is_blocked = True
        else:
            is_blocked = False

        if is_blocked:
            logger.error("Probably block dialog is shown.")
            raise ActionBlockedError(
                "Seems that action is blocked. Consider reinstalling Instagram app and be more careful with limits!"
            )

    def _check_if_no_posts(self) -> bool:
        obj = self.device.find(resourceId=ResourceID.IGDS_HEADLINE_EMPHASIZED_HEADLINE)
        return obj.exists(Timeout.MEDIUM)

    def search_text(self, username):
        search_row = self.device.find(resourceId=ResourceID.ROW_SEARCH_EDIT_TEXT)
        if search_row.exists(Timeout.MEDIUM):
            search_row.set_text(username, Mode.PASTE if args.dont_type else Mode.TYPE)
            return True
        else:
            return False

    @staticmethod
    def close_keyboard(device):
        flag = DeviceFacade(device.device_id, device.app_id)._is_keyboard_show()
        if flag:
            logger.debug("The keyboard is currently open. Press back to close.")
            device.back()
        elif flag is None:
            tabbar_container = device.find(
                resourceId=ResourceID.FIXED_TABBAR_TABS_CONTAINER
            )
            if tabbar_container.exists():
                delta = tabbar_container.get_bounds()["bottom"]
            else:
                delta = 375
            logger.debug(
                "Failed to check if keyboard is open! Will do a little swipe up to prevent errors."
            )
            UniversalActions(device)._swipe_points(
                direction=Direction.UP,
                start_point_y=randint(delta + 10, delta + 150),
                delta_y=randint(50, 100),
            )
