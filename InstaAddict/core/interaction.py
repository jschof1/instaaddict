import logging
import os
import re
import subprocess
from argparse import Namespace
from datetime import datetime
from os import path
from random import choice, randint, shuffle, uniform
from time import sleep, time
from typing import Optional, Tuple, List

import emoji
import spintax
from colorama import Fore, Style

from InstaAddict.core import storage
from InstaAddict.core.device_facade import (
    DeviceFacade,
    Location,
    Mode,
    SleepTime,
    Timeout,
)
from InstaAddict.core.report import print_scrape_report, print_short_report
from InstaAddict.core.resources import ClassName
from InstaAddict.core.resources import ResourceID as resources
from InstaAddict.core.session_state import SessionState
from InstaAddict.core.gemini_vision import (
    get_vision_comment,
    classify_sentiment,
    generate_sentiment_fallback,
)
from InstaAddict.core.storage import CommentMemory
from InstaAddict.core.utils import (
    append_to_file,
    get_value,
    random_choice,
    random_sleep,
    save_crash,
)
from InstaAddict.core.views import (
    CurrentStoryView,
    Direction,
    MediaType,
    PostsGridView,
    ProfileView,
    UniversalActions,
    case_insensitive_re,
)

logger = logging.getLogger(__name__)

# Module-level globals initialized to prevent NameError prior to load_config
args = None
configs = None
ResourceID = None


def load_config(config):
    global args
    global configs
    global ResourceID
    args = config.args
    configs = config
    ResourceID = resources(config.args.app_id)


def interact_with_user(
    device,
    username,
    my_username,
    likes_count,
    likes_percentage,
    stories_percentage,
    can_follow,
    follow_percentage,
    comment_percentage,
    pm_percentage,
    profile_filter,
    args,
    session_state,
    scraping_file,
    current_mode,
) -> Tuple[bool, bool, bool, bool, bool, int, int, int]:
    """
    :return: (whether interaction succeed, whether @username was followed during the interaction, if you scraped that account, if you sent a PM, number of liked, number of watched, number of commented)
    """
    number_of_liked = 0
    number_of_watched = 0
    number_of_commented = 0
    comment_done = interacted = followed = scraped = sent_pm = False
    logger.debug("Checking profile..")
    start_time = time()
    profile_data, skipped = profile_filter.check_profile(device, username)
    if username == my_username:
        logger.info("It's you, skip.")
        return (
            interacted,
            followed,
            profile_data.is_private,
            scraped,
            sent_pm,
            number_of_liked,
            number_of_watched,
            number_of_commented,
        )

    if skipped:
        delta = format(time() - start_time, ".2f")
        logger.debug(f"Profile checked in {delta}s")
        return (
            interacted,
            followed,
            profile_data.is_private,
            scraped,
            sent_pm,
            number_of_liked,
            number_of_watched,
            number_of_commented,
        )

    profile_view = ProfileView(device)
    delta = format(time() - start_time, ".2f")
    logger.debug(f"Profile checked in {delta}s")
    if profile_data.is_private or (profile_data.posts_count == 0):
        private_empty = "Private" if profile_data.is_private else "Empty"
        logger.info(f"{private_empty} account.")
        if (
            pm_percentage != 0
            and can_send_PM(session_state, pm_percentage)
            and profile_filter.can_pm_to_private_or_empty
        ):
            sent_pm = _send_PM(
                device, session_state, my_username, 0, profile_data.is_private
            )
            if sent_pm:
                interacted = True
        can_follow_private_or_empty = profile_filter.can_follow_private_or_empty()
        if can_follow and can_follow_private_or_empty:
            if scraping_file is None:
                followed = _follow(
                    device, username, follow_percentage, args, session_state, 0
                )
                if followed:
                    interacted = True
                return (
                    interacted,
                    followed,
                    profile_data.is_private,
                    scraped,
                    sent_pm,
                    number_of_liked,
                    number_of_watched,
                    number_of_commented,
                )
        else:
            if not can_follow_private_or_empty:
                logger.info(
                    "follow_private_or_empty is disabled in filters. Skip.",
                    extra={"color": f"{Fore.GREEN}"},
                )
            else:
                logger.info(
                    "Your follow-percentage is not 100%, not following this time. Skip.",
                    extra={"color": f"{Fore.GREEN}"},
                )
            return (
                interacted,
                followed,
                profile_data.is_private,
                scraped,
                sent_pm,
                number_of_liked,
                number_of_watched,
                number_of_commented,
            )

    # handle the scraping mode
    if scraping_file is not None:
        append_to_file(scraping_file, username)
        logger.info(
            f"Added @{username} at {scraping_file}",
            extra={"color": f"{Style.BRIGHT}{Fore.GREEN}"},
        )
        scraped = True
        return (
            interacted,
            followed,
            profile_data.is_private,
            scraped,
            sent_pm,
            number_of_liked,
            number_of_watched,
            number_of_commented,
        )

    # if not in scarping mode, we will interact
    number_of_watched = _watch_stories(
        device,
        profile_view,
        username,
        stories_percentage,
        args,
        session_state,
    )
    swipe_amount = 0

    if number_of_watched >= 1:
        interacted = True
    if can_like(session_state, likes_percentage):
        if profile_data.posts_count > 3:
            swipe_amount = ProfileView(device).swipe_to_fit_posts()
        else:
            logger.debug(
                f"We don't need to scroll, there is/are only {profile_data.posts_count} post(s)."
            )
        if swipe_amount == -1:
            return (
                interacted,
                followed,
                profile_data.is_private,
                scraped,
                sent_pm,
                number_of_liked,
                number_of_watched,
                number_of_commented,
            )

        likes_value = get_value(likes_count, "Likes count: {}", 2)
        can_comment_job = True
        if profile_filter is not None and hasattr(profile_filter, "can_comment"):
            try:
                (
                    _,
                    _,
                    _,
                    can_comment_job,
                ) = profile_filter.can_comment(current_mode)
            except (ValueError, TypeError):
                can_comment_job = True
        if can_comment_job and comment_percentage != 0:
            max_comments_pro_user = get_value(
                args.max_comments_pro_user, "Max comment count: {}", 1
            )
        if likes_value > 12:
            logger.error("Max number of likes per user is 12.")
            likes_value = 12

        start_time = time()
        full_rows, columns_last_row = profile_view.count_photo_in_view()
        end_time = format(time() - start_time, ".2f")
        photos_indices = list(range(full_rows * 3 + columns_last_row))

        if 0 < profile_data.posts_count < len(photos_indices):
            logger.debug(
                f"The grid shows {len(photos_indices)} slots but the profile has {profile_data.posts_count} posts. Trimming empty slots."
            )
            photos_indices = photos_indices[: profile_data.posts_count]

        if len(photos_indices) == profile_data.posts_count and len(photos_indices) > 1:
            del photos_indices[-1]
            logger.debug(
                "This is a temporary fix, for avoid bot to crash we have removed the last picture form the list."
            )

        logger.info(
            f"There {f'is {len(photos_indices)} post' if len(photos_indices)<=1 else f'are {len(photos_indices)} posts'} fully visible. Calculated in {end_time}s"
        )
        if current_mode in [
            "hashtag-posts-recent",
            "hashtag-posts-top",
            "place-posts-recent",
            "place-posts-top",
            "feed",
        ]:
            # in these jobs we did a like already at the post
            photos_indices = photos_indices[1:]
            # sometimes we liked not the last picture, have to introduce the already liked thing..

        if likes_value > len(photos_indices):
            logger.info(
                f"Only {len(photos_indices)} {'photo' if len(photos_indices)<=1 else 'photos'} available."
            )
        else:
            shuffle(photos_indices)
            photos_indices = photos_indices[:likes_value]
            photos_indices = sorted(photos_indices)
        post_grid_view = PostsGridView(device)
        consecutive_open_failures = 0
        for i in range(len(photos_indices)):
            try:
                from InstaAddict.core.tui import DashboardManager

                if DashboardManager.is_active():
                    dm = DashboardManager.get_instance()
                    if dm.state.is_skip_task_requested():
                        logger.warning(
                            "[TUI] Task skip requested by user ([CTRL+S]). Breaking out of profile post interactions...",
                            extra={"color": f"{Fore.YELLOW}"},
                        )
                        break
                    if dm.state.is_upload_requested():
                        logger.info(
                            "[TUI] Immediate upload requested by user ([CTRL+U]). Exiting profile post interactions to execute upload...",
                            extra={"color": f"{Fore.MAGENTA}"},
                        )
                        break
            except Exception:
                pass

            photo_index = photos_indices[i]
            row = photo_index // 3
            column = photo_index - row * 3
            logger.info(f"Open post #{i + 1} ({row + 1} row, {column + 1} column).")
            opened_post_view, media_type, obj_count = post_grid_view.navigateToPost(
                row, column
            )

            like_succeed = False
            if opened_post_view is None:
                save_crash(device)
                consecutive_open_failures += 1
                UniversalActions.dismiss_peek_if_open(device)
                for _ in range(3):
                    if post_grid_view._is_still_on_profile():
                        break
                    logger.debug("Ensuring return to profile grid after failed open...")
                    device.back()
                    random_sleep(0.5, 1.0, modulable=False)
                if consecutive_open_failures >= 2:
                    logger.warning(
                        f"Multiple consecutive post open failures for @{username}. Moving to next profile."
                    )
                    break
                continue

            consecutive_open_failures = 0

            # Dynamic check: If is_peek is not yet set on opened_post_view, but Peek Preview is actually open
            if (
                not getattr(opened_post_view, "is_peek", False)
                and hasattr(opened_post_view, "is_peek_preview_opened")
                and opened_post_view.is_peek_preview_opened() is True
            ):
                logger.info("Peek Preview detected during post inspection.")
                opened_post_view.is_peek = True

            # Handle Peek Preview if triggered
            if getattr(opened_post_view, "is_peek", False):
                logger.info("Handling post interaction via Peek Preview.")
                already_liked = opened_post_view.is_peek_already_liked()
                if already_liked:
                    logger.info("Post already liked (detected in Peek Preview)!")
                else:
                    like_succeed = opened_post_view.like_in_peek()
                    if like_succeed:
                        register_like(device, session_state)
                        number_of_liked += 1
                        interacted = True
                    else:
                        logger.warning("Fail to like post via Peek Preview.")
                opened_post_view.dismiss_peek()
                random_sleep(0.5, 1.0, modulable=False)
                continue
            if media_type in (None, MediaType.UNKNOWN):
                media_type = opened_post_view.detect_opened_media_type()
            if media_type in (MediaType.REEL, MediaType.IGTV, MediaType.VIDEO):
                already_liked, _ = opened_post_view._is_video_liked()
            else:
                already_liked, _ = opened_post_view._is_post_liked()
            if already_liked:
                logger.info("Post already liked!")
            elif opened_post_view and already_liked is not None:
                if media_type in (MediaType.REEL, MediaType.IGTV, MediaType.VIDEO):
                    opened_post_view.start_video()
                    video_opened = opened_post_view.open_video()
                    if video_opened:
                        opened_post_view.watch_media(media_type)
                        like_succeed = opened_post_view.like_video()
                elif media_type in (
                    MediaType.CAROUSEL,
                    MediaType.PHOTO,
                    MediaType.UNKNOWN,
                ):
                    if media_type == MediaType.CAROUSEL:
                        _browse_carousel(device, obj_count)
                    opened_post_view.watch_media(media_type)
                    like_succeed = opened_post_view.like_post()
                if like_succeed:
                    register_like(device, session_state)
                    number_of_liked += 1
                else:
                    logger.warning("Fail to like post. Let's continue...")
            else:
                logger.warning("Can't find the post element!")
                save_crash(device)

            if opened_post_view and already_liked is not None:
                if comment_percentage != 0 and can_comment(
                    media_type, profile_filter, current_mode
                ):
                    if number_of_commented < max_comments_pro_user:
                        comment_done = _comment(
                            device,
                            my_username,
                            comment_percentage,
                            args,
                            session_state,
                            media_type,
                        )
                        if comment_done:
                            number_of_commented += 1
                    else:
                        logger.info(
                            f"You've already did {max_comments_pro_user} {'comment' if max_comments_pro_user<=1 else 'comments'} for this user!"
                        )
            if like_succeed or comment_done:
                interacted = True

            if not opened_post_view or (not like_succeed and not already_liked):
                reason = "open" if not opened_post_view else "like"
                logger.info(
                    f"Could not {reason} media. Posts count: {profile_data.posts_count}."
                )
            logger.info("Back to profile.")
            for _ in range(3):
                if post_grid_view._is_still_on_profile():
                    break
                UniversalActions.dismiss_peek_if_open(device)
                logger.debug("Exiting post view to profile grid...")
                device.back()
                random_sleep(0.5, 1.0, modulable=False)
            else:
                logger.warning("Can't go back to the profile!")
            # Allow RecyclerView grid to re-lay out before next child(index=N) lookup
            random_sleep(0.5, 1.0, modulable=False)

    if pm_percentage != 0 and can_send_PM(session_state, pm_percentage):
        sent_pm = _send_PM(device, session_state, my_username, swipe_amount)
        swipe_amount = 0
        if sent_pm:
            interacted = True
    if can_follow:
        followed = _follow(
            device,
            username,
            follow_percentage,
            args,
            session_state,
            swipe_amount,
        )
        if followed:
            interacted = True

    return (
        interacted,
        followed,
        profile_data.is_private,
        scraped,
        sent_pm,
        number_of_liked,
        number_of_watched,
        number_of_commented,
    )


def can_send_PM(session_state: SessionState, pm_percentage: int) -> bool:
    pm_chance = randint(1, 100)
    return not session_state.check_limit(
        limit_type=session_state.Limit.PM, output=True
    ) and (pm_chance <= pm_percentage)


def can_like(session_state: SessionState, likes_percentage: int) -> bool:
    likes_chance = randint(1, 100)
    return not session_state.check_limit(
        limit_type=session_state.Limit.LIKES, output=True
    ) and (likes_chance <= likes_percentage)


def can_comment(media_type: MediaType, profile_filter, current_mode) -> bool:
    if profile_filter is None:
        return True
    (
        can_comment_photos,
        can_comment_videos,
        can_comment_carousels,
        can_comment_job,
    ) = profile_filter.can_comment(current_mode)
    if can_comment_job:
        if media_type == MediaType.PHOTO and can_comment_photos:
            return True
        elif (
            media_type in (MediaType.VIDEO, MediaType.IGTV, MediaType.REEL)
            and can_comment_videos
        ):
            return True
        elif media_type == MediaType.CAROUSEL and can_comment_carousels:
            return True
    logger.warning(
        f"Can't comment this {media_type} because filters are: can_comment_photos = {can_comment_photos}, can_comment_videos = {can_comment_videos}, can_comment_carousels = {can_comment_carousels}, can_comment_{current_mode} = {can_comment_job}. Check your filters.yml."
    )
    return False


def register_like(device, session_state):
    UniversalActions.detect_block(device)
    logger.debug("Like succeed.")
    session_state.totalLikes += 1


def is_follow_limit_reached_for_source(session_state, follow_limit, source):
    if follow_limit is None:
        return False

    followed_count = session_state.totalFollowed.get(source)
    return followed_count is not None and followed_count >= follow_limit


def _on_interaction(
    source,
    succeed,
    followed,
    scraped,
    interactions_limit,
    likes_limit,
    sessions,
    session_state,
    args,
):
    session_state = sessions[-1]
    session_state.add_interaction(source, succeed, followed, scraped)

    can_continue = True

    inside_working_hours, _ = SessionState.inside_working_hours(
        args.working_hours, args.time_delta_session
    )
    if not inside_working_hours:
        can_continue = False
    else:
        successful_interactions_count = session_state.successfulInteractions.get(source)
        if (
            successful_interactions_count
            and successful_interactions_count >= interactions_limit
        ):
            logger.info(
                "Reached interaction limit for that source, going to the next one..",
                extra={"color": f"{Fore.CYAN}"},
            )
            can_continue = False

        if args.scrape_to_file is not None:
            if session_state.check_limit(
                limit_type=session_state.Limit.SCRAPED, output=True
            ):
                logger.info(
                    "Reached scraped limit, finish.", extra={"color": f"{Fore.CYAN}"}
                )
                can_continue = False
        else:
            if (
                session_state.check_limit(
                    limit_type=session_state.Limit.LIKES, output=False
                )
                and args.end_if_likes_limit_reached
            ):
                logger.info(
                    "Reached liked limit, finish.", extra={"color": f"{Fore.CYAN}"}
                )
                can_continue = False

            if (
                session_state.check_limit(
                    limit_type=session_state.Limit.FOLLOWS, output=False
                )
                and args.end_if_follows_limit_reached
            ):
                logger.info(
                    "Reached followed limit, finish.", extra={"color": f"{Fore.CYAN}"}
                )
                can_continue = False

            if (
                session_state.check_limit(
                    limit_type=session_state.Limit.WATCHES, output=False
                )
                and args.end_if_watches_limit_reached
            ):
                logger.info(
                    "Reached watched limit, finish.", extra={"color": f"{Fore.CYAN}"}
                )
                can_continue = False

            if (
                session_state.check_limit(
                    limit_type=session_state.Limit.PM, output=False
                )
                and args.end_if_pm_limit_reached
            ):
                logger.info(
                    "Reached pm limit, finish.", extra={"color": f"{Fore.CYAN}"}
                )
                can_continue = False

            if (
                session_state.check_limit(
                    limit_type=session_state.Limit.COMMENTS, output=False
                )
                and args.end_if_comments_limit_reached
            ):
                logger.info(
                    "Reached comments limit, finish.", extra={"color": f"{Fore.CYAN}"}
                )
                can_continue = False

            if session_state.check_limit(
                limit_type=session_state.Limit.TOTAL, output=False
            ):
                logger.info(
                    "Reached total interaction limit, finish.",
                    extra={"color": f"{Fore.CYAN}"},
                )
                can_continue = False
            if session_state.check_limit(
                limit_type=session_state.Limit.SUCCESS, output=False
            ):
                logger.info(
                    "Reached total successfully interaction limit, finish.",
                    extra={"color": f"{Fore.CYAN}"},
                )
                can_continue = False

    if (can_continue and succeed) or scraped:
        if scraped:
            print_scrape_report(source, session_state)
        else:
            print_short_report(source, session_state)

    return can_continue


def _browse_carousel(device: DeviceFacade, obj_count: int) -> None:
    carousel_percentage = get_value(configs.args.carousel_percentage, None, 0)
    carousel_count = get_value(configs.args.carousel_count, None, 1)
    if carousel_percentage > randint(0, 100) and carousel_count > 1:
        media_obj = device.find(resourceIdMatches=ResourceID.CAROUSEL_MEDIA_GROUP)
        logger.info("Watching photos/videos in carousel.")
        if obj_count < carousel_count:
            logger.info(f"There are only {obj_count} media(s) in this carousel!")
            carousel_count = obj_count
        if media_obj.exists():
            media_obj_bounds = media_obj.get_bounds()
            n = 1
            while n < carousel_count:
                if media_obj.child(
                    resourceIdMatches=ResourceID.CAROUSEL_IMAGE_MEDIA_GROUP
                ).exists():
                    watch_photo_time = get_value(
                        configs.args.watch_photo_time,
                        "Watching photo for {}s.",
                        0,
                        its_time=True,
                    )
                    sleep(watch_photo_time)
                elif media_obj.child(
                    resourceIdMatches=ResourceID.CAROUSEL_VIDEO_MEDIA_GROUP
                ).exists():
                    watch_video_time = get_value(
                        configs.args.watch_video_time,
                        "Watching video for {}s.",
                        0,
                        its_time=True,
                    )
                    sleep(watch_video_time)
                start_point_y = (
                    (media_obj_bounds["bottom"] + media_obj_bounds["top"])
                    / 2
                    * uniform(0.85, 1.15)
                )
                start_point_x = uniform(0.85, 1.10) * (
                    media_obj_bounds["right"] * 5 / 6
                )
                delta_x = media_obj_bounds["right"] * uniform(0.5, 0.7)
                UniversalActions(device)._swipe_points(
                    start_point_y=start_point_y,
                    start_point_x=start_point_x,
                    delta_x=delta_x,
                    direction=Direction.LEFT,
                )
                n += 1


def _comment(
    device: DeviceFacade,
    my_username: str,
    comment_percentage: int,
    args,
    session_state: SessionState,
    media_type: MediaType,
    explicit_comment: str = None,
    caption: str = "",
    author: str = "",
) -> bool:
    global ResourceID
    if ResourceID is None:
        app_id = getattr(args, "app_id", "com.instagram.android") if args else "com.instagram.android"
        ResourceID = resources(app_id)

    if not session_state.check_limit(
        limit_type=session_state.Limit.COMMENTS, output=False
    ):
        if not random_choice(comment_percentage):
            return False

        if explicit_comment:
            smart_ai_comment = explicit_comment
            logger.info(
                "Using pre-generated explicit comment. Skipping duplicate Vision-AI check."
            )
        else:
            # VISION AI: Take snapshot of view BEFORE opening comment box (obfuscation guard)
            logger.info("Executing Vision-AI Context Assessment...")
            smart_ai_comment = get_vision_comment(
                device,
                "current_post_target",
                caption=caption,
                author=author,
                media_type=str(media_type),
                account_name=my_username,
            )

        universal_actions = UniversalActions(device)
        # we have to do a little swipe for preventing get the previous post comments button (which is covered by top bar, but present in hierarchy!!)
        if media_type != MediaType.REEL:
            universal_actions._swipe_points(
                direction=Direction.DOWN, delta_y=randint(150, 250)
            )
            tab_bar = device.find(
                resourceId=ResourceID.TAB_BAR,
            )
            media = device.find(
                resourceIdMatches=ResourceID.MEDIA_CONTAINER,
            )
            if tab_bar.exists() and media.exists():
                if (
                    int(tab_bar.get_bounds()["top"]) - int(media.get_bounds()["bottom"])
                    < 150
                ):
                    universal_actions._swipe_points(
                        direction=Direction.DOWN, delta_y=randint(150, 250)
                    )
            else:
                logger.debug(
                    "Tab bar or media container not found — skipping extra swipe check."
                )
        # look at hashtag of comment
        for _ in range(2):
            comment_button = device.find(
                resourceIdMatches=f"{ResourceID.ROW_FEED_BUTTON_COMMENT}|.*comment_button.*|.*clips_comment_button.*"
            )
            if not comment_button.exists():
                comment_button = device.find(
                    descriptionMatches="(?i)^Comments?$"
                )
            if comment_button.exists():
                logger.info("Open comments of post.")
                comment_button.click()

                # CO-115: Read top community comments to ensure tone and originality
                community_comments = []
                try:
                    for c_elem in device.find_all(
                        resourceId=ResourceID.ROW_COMMENT_TEXTVIEW_COMMENT
                    ):
                        c_text = c_elem.get_text()
                        if c_text and c_text.strip():
                            community_comments.append(c_text.strip())
                            if len(community_comments) >= 3:
                                break
                except Exception as ce:
                    logger.debug(f"Could not read community comments: {ce}")

                comment_box = device.find(
                    resourceId=ResourceID.LAYOUT_COMMENT_THREAD_EDITTEXT,
                    enabled="true",
                )
                if not comment_box.exists():
                    comment_box = device.find(
                        resourceId=ResourceID.LAYOUT_COMMENT_THREAD_EDITTEXT_MULTILINE,
                        enabled="true",
                    )
                if not comment_box.exists():
                    comment_box = device.find(
                        resourceIdMatches=f"{ResourceID.LAYOUT_COMMENT_THREAD_EDITTEXT}|{ResourceID.LAYOUT_COMMENT_THREAD_EDITTEXT_MULTILINE}|.*layout_comment_thread_edittext.*"
                    )
                if not comment_box.exists():
                    any_edittext = device.find(
                        classNameMatches=".*EditText.*|.*AutoCompleteTextView.*"
                    )
                    if any_edittext.exists():
                        comment_box = any_edittext
                        logger.debug(
                            f"[DEBUG comment box] found an EditText-like widget. Bounds: {any_edittext.get_bounds()}"
                        )
                    else:
                        logger.debug(
                            "[DEBUG comment box] no EditText-like widget found on screen at all."
                        )

                if comment_box.exists():
                    # CO-113: Ensure IME focus before typing to prevent Compose -32002 errors
                    try:
                        comment_box.click()
                        random_sleep(0.3, 0.6, modulable=False)
                    except Exception as ce:
                        logger.debug(f"Pre-type focus click encountered: {ce}")

                    if not smart_ai_comment:
                        try:
                            mem = CommentMemory.get_instance(my_username)
                            post_sentiment = classify_sentiment(caption)
                            smart_ai_comment = generate_sentiment_fallback(
                                sentiment=post_sentiment, author=author, memory=mem
                            )
                        except Exception as fe:
                            logger.debug(f"Sentiment fallback generation failed: {fe}")

                    comment = (
                        smart_ai_comment
                        if smart_ai_comment
                        else load_random_comment(my_username, media_type, caption=caption, author=author)
                    )
                    if not comment:
                        UniversalActions.close_keyboard(device)
                        device.back()
                        return False

                    import time

                    # Biometric Telemetry Typing Delay Guard (150ms per character)
                    sleep_duration = len(comment) * 0.15
                    logger.info(
                        f"Write comment: {comment} (Simulating native typing delay for {sleep_duration:.2f}s)",
                        extra={"color": f"{Fore.CYAN}"},
                    )

                    try:
                        comment_box.set_text(
                            comment, Mode.PASTE if args.dont_type else Mode.TYPE
                        )
                    except Exception as te:
                        logger.warning(
                            f"Initial set_text failed ({te}), retrying after focus tap..."
                        )
                        try:
                            comment_box.click()
                            random_sleep(0.5, 0.8, modulable=False)
                            comment_box.set_text(comment, Mode.TYPE)
                        except Exception as te2:
                            logger.error(f"Failed to enter text into comment box: {te2}")
                            UniversalActions.close_keyboard(device)
                            device.back()
                            return False

                    time.sleep(sleep_duration)

                    # Ghost Typing DOM Wake-up Hack
                    # Fire physical spacebar to wake React Native event listener natively
                    try:
                        subprocess.run(
                            [
                                "adb",
                                "-s",
                                str(device.deviceV2.serial),
                                "shell",
                                "input",
                                "keyevent",
                                "62",
                            ],
                            shell=False,
                            timeout=5,
                        )
                    except (subprocess.SubprocessError, OSError, Exception):
                        pass

                    # Wait for post button to appear (it only shows after typing)
                    random_sleep(0.5, 1, modulable=False)

                    post_button = device.find(
                        resourceId=ResourceID.LAYOUT_COMMENT_THREAD_POST_BUTTON_ICON
                    )
                    if not post_button.exists():
                        post_button = device.find(
                            resourceId=ResourceID.LAYOUT_COMMENT_THREAD_POST_BUTTON_CLICK_AREA
                        )
                    if not post_button.exists():
                        # Fallback: try to find button by content-desc "Post" or "Send"
                        post_button = device.find(
                            descriptionMatches="(?i)^(Post|Send)$"
                        )
                    if post_button.exists():
                        post_button.click()
                        time.sleep(2)

                        # Graceful Degradation: Soft-Ban Action Blocked Sniffer
                        blocked = device.find(
                            textMatches="(?i)Blocked|(?i)Restricted|(?i)Try Again Later"
                        )
                        if blocked.exists(timeout=2):
                            logger.error(
                                "Ig Action Blocked overlay detected! Aborting to prevent ban cascade."
                            )
                            # session_state natively records blocks and we should raise it
                            ok_btn = device.find(textMatches="(?i)Tell us|(?i)OK")
                            if ok_btn.exists():
                                ok_btn.click()
                            from InstaAddict.core.exceptions import ActionBlockedError

                            raise ActionBlockedError(
                                "Action Blocked during comment injection."
                            )
                    else:
                        logger.warning(
                            "Post button not found, skipping comment submission"
                        )
                        universal_actions.close_keyboard(device)
                        device.back()
                        return False
                else:
                    logger.info("Comments on this post have been limited.")
                    universal_actions.close_keyboard(device)
                    device.back()
                    return False

                universal_actions.detect_block(device)
                universal_actions.close_keyboard(device)
                # Verify comment was posted using multi-tier signals:
                # Tier 1: Check for comment text in content-description
                comment_sub = comment.strip()[:20] if comment else ""
                posted_text = device.find(
                    descriptionMatches=f"(?i).*{re.escape(comment_sub)}.*"
                )
                comment_confirmed = False
                if posted_text.exists(Timeout.SHORT):
                    logger.info("Comment succeed (confirmed via accessibility description).", extra={"color": f"{Fore.GREEN}"})
                    comment_confirmed = True
                else:
                    # Tier 2: Check if comment_box was cleared or dismissed
                    box_check = device.find(
                        resourceIdMatches=f"{ResourceID.LAYOUT_COMMENT_THREAD_EDITTEXT}|{ResourceID.LAYOUT_COMMENT_THREAD_EDITTEXT_MULTILINE}"
                    )
                    post_btn_check = device.find(
                        resourceIdMatches=f"{ResourceID.LAYOUT_COMMENT_THREAD_POST_BUTTON_ICON}|{ResourceID.LAYOUT_COMMENT_THREAD_POST_BUTTON_CLICK_AREA}"
                    )
                    if not box_check.exists() or (box_check.get_text() or "").strip() == "" or not post_btn_check.exists():
                        logger.info("Comment succeed (confirmed via input submission transition).", extra={"color": f"{Fore.GREEN}"})
                        comment_confirmed = True
                    else:
                        logger.warning("Failed to check if comment succeed.")
                        comment_confirmed = False

                if comment_confirmed:
                    session_state.totalComments += 1
                    try:
                        CommentMemory.get_instance(my_username).add_comment(
                            comment,
                            target_username=author,
                            post_type=str(media_type),
                        )
                    except Exception as me:
                        logger.debug(f"Failed to record comment to CommentMemory: {me}")

                logger.info("Go back to post view.")
                device.back()
                return comment_confirmed
            else:
                like_button = device.find(
                    resourceIdMatches=f"{ResourceID.ROW_FEED_BUTTON_LIKE}|.*like_button.*",
                )
                if like_button.exists() and media_type != MediaType.REEL:
                    logger.info("This post has comments disabled.")
                    return False
                if media_type != MediaType.REEL:
                    universal_actions._swipe_points(
                        direction=Direction.DOWN, delta_y=randint(150, 250)
                    )
    return False


def _send_PM(
    device,
    session_state: SessionState,
    my_username: str,
    swipe_amount: int,
    private: bool = False,
) -> bool:
    universal_actions = UniversalActions(device)
    if private:
        options = device.find(
            classNameMatches=ClassName.FRAME_LAYOUT,
            descriptionMatches=case_insensitive_re("^Options$"),
        )
        if options.exists(Timeout.SHORT):
            options.click()
        else:
            return False
        send_pm = device.find(
            classNameMatches=ClassName.BUTTON,
            textMatches=case_insensitive_re("^Send Message$"),
        )
        if send_pm.exists(Timeout.SHORT):
            send_pm.click()
        else:
            return False
    else:
        coordinator_layout = device.find(resourceId=ResourceID.COORDINATOR_ROOT_LAYOUT)
        if coordinator_layout.exists() and swipe_amount != 0:
            universal_actions._swipe_points(
                direction=Direction.UP, delta_y=swipe_amount
            )
        message_button = device.find(
            classNameMatches=ClassName.BUTTON_OR_TEXTVIEW_REGEX,
            enabled=True,
            textMatches="Message",
        )
        if message_button.exists(Timeout.SHORT):
            message_button.click()
        else:
            logger.warning("Cannot find the button for sending PMs!")
            return False
    message_box = device.find(
        resourceId=ResourceID.ROW_THREAD_COMPOSER_EDITTEXT,
        className=ClassName.EDIT_TEXT,
        enabled="true",
    )

    if message_box.exists():
        message = load_random_message(my_username)
        if message is None:
            logger.warning(
                "If you don't want to comment set 'pm-percentage: 0' in your config.yml."
            )
            device.back()
            return False
        nl = "\n"
        nlv = "\\n"
        logger.info(
            f"Write private message: {message.replace(nl, nlv)}",
            extra={"color": f"{Fore.CYAN}"},
        )
        message_box.set_text(message, Mode.PASTE if args.dont_type else Mode.TYPE)
        send_button = device.find(
            resourceId=ResourceID.ROW_THREAD_COMPOSER_BUTTON_SEND,
        )
        if send_button.exists():
            send_button.click()
            universal_actions.detect_block(device)
            universal_actions.close_keyboard(device)
            posted_text = device.find(text=f"{message}")
            message_sending_icon = device.find(
                resourceId=ResourceID.ACTION_ICON, className=ClassName.IMAGE_VIEW
            )
            if message_sending_icon.exists():
                random_sleep()
            if posted_text.exists(Timeout.MEDIUM) and not message_sending_icon.exists():
                logger.info("PM send succeed.", extra={"color": f"{Fore.GREEN}"})
                session_state.totalPm += 1
                pm_confirmed = True
            else:
                logger.warning("Failed to check if PM send succeed.")
                pm_confirmed = False
            logger.info("Go back to profile view.")
            device.back()
            return pm_confirmed
        else:
            logger.warning("Can't find SEND button!")
            universal_actions.close_keyboard(device)
            device.back()
            return False
    else:
        logger.info("PM to this user have been limited.")
        universal_actions.close_keyboard(device)
        device.back()
        return False


def _load_and_clean_txt_file(
    my_username: str, txt_filename: str
) -> Optional[List[str]]:
    def nonblank_lines(f):
        for ln in f:
            line = ln.rstrip()
            if line:
                yield line

    lines = []
    file_name = os.path.join(storage.ACCOUNTS, my_username, txt_filename)
    if path.isfile(file_name):
        try:
            with open(file_name, "r", encoding="utf-8") as f:
                for line in nonblank_lines(f):
                    lines.append(line)
                if lines:
                    return lines
                logger.warning(f"{file_name} is empty! Check your account folder.")
                return None
        except Exception as e:
            logger.error(f"Error: {e}.")
            return None
    logger.warning(f"{file_name} not found! Check your account folder.")
    return None


def load_random_message(my_username: str) -> Optional[str]:
    lines = _load_and_clean_txt_file(my_username, storage.FILENAME_MESSAGES)
    if lines is not None:
        random_message = choice(lines)
        return emoji.emojize(
            spintax.spin(random_message.replace("\\n", "\n")),
            use_aliases=True,
        )
    return None


def load_random_comment(
    my_username: str,
    media_type: MediaType,
    caption: str = "",
    author: str = "",
) -> Optional[str]:
    mem = None
    try:
        mem = CommentMemory.get_instance(my_username)
    except Exception:
        pass

    lines = _load_and_clean_txt_file(my_username, storage.FILENAME_COMMENTS)
    candidates = []
    if lines and len(lines) > 0:
        try:
            photo_header = lines.index("%PHOTO")
            video_header = lines.index("%VIDEO")
            carousel_header = lines.index("%CAROUSEL")
            photo_comments = lines[photo_header + 1 : video_header]
            video_comments = lines[video_header + 1 : carousel_header]
            carousel_comments = lines[carousel_header + 1 :]
            if media_type == MediaType.PHOTO and photo_comments:
                candidates = photo_comments
            elif media_type in (MediaType.VIDEO, MediaType.IGTV, MediaType.REEL) and video_comments:
                candidates = video_comments
            elif media_type == MediaType.CAROUSEL and carousel_comments:
                candidates = carousel_comments
        except ValueError:
            non_header_lines = [l for l in lines if not l.startswith("%")]
            if non_header_lines:
                candidates = non_header_lines

    # Filter candidates with CommentMemory to avoid repetition
    if candidates:
        shuffled = list(candidates)
        shuffle(shuffled)
        for cand in shuffled:
            spun = emoji.emojize(spintax.spin(cand), use_aliases=True)
            if mem is not None and mem.is_similar_to_recent(spun):
                continue
            return spun

    # If no lines or all candidates repetitive, use sentiment fallback generator!
    try:
        sentiment = classify_sentiment(caption)
        fallback = generate_sentiment_fallback(sentiment=sentiment, author=author, memory=mem)
        if fallback:
            return fallback
    except Exception:
        pass

    DEFAULT_COMMENTS = [
        "Ripper shot mate! :paw_prints:",
        "Heaps good! :dog:",
        "Reckon this is gold! :raised_hands:",
        "What a champion! :heart:",
        "Proper legend! :sparkles:",
        "Looking sharp mate! :fire:",
        "Love this heaps! :clap:",
    ]
    chosen = choice(DEFAULT_COMMENTS)
    return emoji.emojize(spintax.spin(chosen), use_aliases=True)



def _follow(device, username, follow_percentage, args, session_state, swipe_amount):
    if not session_state.check_limit(
        limit_type=session_state.Limit.FOLLOWS, output=False
    ):
        follow_chance = randint(1, 100)
        if follow_chance > follow_percentage:
            return False
        universal_actions = UniversalActions(device)
        coordinator_layout = device.find(resourceId=ResourceID.COORDINATOR_ROOT_LAYOUT)
        if coordinator_layout.exists(Timeout.MEDIUM) and swipe_amount != 0:
            universal_actions._swipe_points(
                direction=Direction.UP, delta_y=swipe_amount
            )

        FOLLOW_REGEX = "^Follow$"
        follow_button = device.find(
            clickable=True,
            textMatches=case_insensitive_re(FOLLOW_REGEX),
        )
        if not follow_button.exists():
            follow_button = device.find(
                clickable=True,
                descriptionMatches=case_insensitive_re(FOLLOW_REGEX),
            )
        UNFOLLOW_REGEX = "^Following|^Requested"
        unfollow_button = device.find(
            clickable=True,
            textMatches=case_insensitive_re(UNFOLLOW_REGEX),
        )
        if not unfollow_button.exists():
            unfollow_button = device.find(
                clickable=True,
                descriptionMatches=case_insensitive_re(UNFOLLOW_REGEX),
            )
        FOLLOWBACK_REGEX = "^Follow Back$"
        followback_button = device.find(
            clickable=True,
            textMatches=case_insensitive_re(FOLLOWBACK_REGEX),
        )
        if not followback_button.exists():
            followback_button = device.find(
                clickable=True,
                descriptionMatches=case_insensitive_re(FOLLOWBACK_REGEX),
            )

        if followback_button.exists():
            logger.info(
                f"@{username} already follows you.",
                extra={"color": f"{Fore.GREEN}"},
            )
            return False
        elif unfollow_button.exists():
            logger.info(
                f"You already follow @{username}.", extra={"color": f"{Fore.GREEN}"}
            )
            return False
        elif follow_button.exists():
            max_tries = 3
            for n in range(max_tries):
                follow_button.click()
                if (
                    device.find(
                        clickable=True,
                        textMatches=case_insensitive_re(UNFOLLOW_REGEX),
                    ).exists(Timeout.SHORT)
                    or device.find(
                        clickable=True,
                        descriptionMatches=case_insensitive_re(UNFOLLOW_REGEX),
                    ).exists(Timeout.SHORT)
                ):
                    logger.info(f"Followed @{username}", extra={"color": Fore.GREEN})
                    universal_actions.detect_block(device)
                    return True
                else:
                    if n < max_tries - 1:
                        logger.debug(
                            "Looks like the click on the button didn't work, try again."
                        )
            logger.warning(
                f"Looks like I was not able to follow @{username}, maybe you got soft-banned for this action!",
                extra={"color": Fore.RED},
            )
            universal_actions.detect_block(device)
        else:
            logger.error(
                "Cannot find neither Follow button, Follow Back button, nor Unfollow button."
            )
            save_crash(device)

    else:
        logger.info("Reached total follows limit, not following.")
    return False


def _watch_stories(
    device: DeviceFacade,
    profile_view: ProfileView,
    username: str,
    stories_percentage: int,
    args: Namespace,
    session_state: SessionState,
) -> int:
    if not random_choice(stories_percentage):
        return 0
    if not session_state.check_limit(
        limit_type=session_state.Limit.WATCHES, output=True
    ):

        def watch_story() -> bool:
            if session_state.check_limit(
                limit_type=session_state.Limit.WATCHES, output=False
            ):
                return False
            logger.debug("Watching stories...")
            session_state.totalWatched += 1
            nonlocal stories_counter
            stories_counter += 1
            for _ in range(7):
                random_sleep(0.5, 1, modulable=False, log=False)
                if story_view.getUsername().strip().casefold() != username.casefold():
                    return False
            like_story()
            return True

        def like_story():
            obj = device.find(resourceIdMatches=ResourceID.TOOLBAR_LIKE_BUTTON)
            if obj.exists():
                if not obj.get_selected():
                    obj.click()
                    logger.info("Story has been liked!")
                else:
                    logger.info("Story is already liked!")
            else:
                logger.info("There is no like button!")

        stories_ring = profile_view.StoryRing()
        live_marker = profile_view.live_marker()
        if live_marker.exists():
            logger.info(f"{username} is making a live.")
            return 0
        if stories_ring.exists():
            stories_to_watch: int = get_value(
                args.stories_count, "Stories count: {}.", 1
            )
            stories_counter = 0
            logger.debug("Open the story container.")
            stories_ring.click(sleep=SleepTime.DEFAULT)
            # Check if expanded profile picture preview opened instead of story
            expanded_profile_pic = device.find(
                resourceId=ResourceID.TOUCH_INTERCEPTOR_EXPANDED_PROFILE_PIC
            )
            if expanded_profile_pic.exists():
                logger.debug(
                    "Profile picture preview opened instead of story. Dismissing."
                )
                device.back()
                return 0
            story_view = CurrentStoryView(device)
            story_frame = story_view.getStoryFrame()
            story_frame.wait(Timeout.MEDIUM)
            story_username = story_view.getUsername()
            if (
                story_username == "BUG!"
                or story_username.strip().casefold() == username.casefold()
            ):
                start = datetime.now()
                try:
                    if not watch_story():
                        return stories_counter
                except Exception as e:
                    logger.debug(f"Exception: {e}")
                    logger.debug(
                        "Ignore this error! Stories ended while we were interacting with it."
                    )
                for _ in range(stories_to_watch - 1):
                    try:
                        logger.debug("Going to the next story...")
                        story_frame.click(
                            mode=Location.RIGHTEDGE,
                            sleep=SleepTime.ZERO,
                            crash_report_if_fails=False,
                        )
                        if not watch_story():
                            break
                    except Exception as e:
                        logger.debug(f"Exception: {e}")
                        logger.debug(
                            "Ignore this error! Stories ended while we were interacting with it."
                        )
                        break
                for _ in range(4):
                    if UniversalActions.escape_in_app_browser(device):
                        break
                    if (
                        story_view.getUsername().strip().casefold()
                        == username.casefold()
                    ):
                        device.back()
                    else:
                        break
                session_state.check_limit(
                    limit_type=session_state.Limit.WATCHES, output=True
                )
                logger.info(
                    f"Watched stories for {(datetime.now()-start).total_seconds():.2f}s."
                )
                return stories_counter
            else:
                logger.warning("Failed to open the story container.")
                logger.debug(f"Story username: {story_username}")
                save_crash(device)
                if story_frame.exists():
                    device.back()
                return 0
        return 0
    else:
        logger.info("Reached total watch limit, not watching stories.")
        return 0
