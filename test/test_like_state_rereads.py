from unittest.mock import MagicMock, patch

from InstaAddict.core.views import MediaType
from InstaAddict.core import interaction


def run_reel(states):
    from InstaAddict.core.interaction import interact_with_user

    pv = MagicMock()
    pv.count_photo_in_view.return_value = (1, 1)
    pv.swipe_to_fit_posts.return_value = 0
    post = MagicMock(is_peek=False)
    post.is_peek_preview_opened.return_value = False
    post._is_video_liked.side_effect = states
    post.open_video.return_value = True
    post.like_video.return_value = True
    grid = MagicMock()
    grid.navigateToPost.return_value = (post, MediaType.REEL, 1)
    grid.return_to_profile.return_value = True
    profile_data = MagicMock(is_private=False, posts_count=1)
    profile_filter = MagicMock()
    profile_filter.check_profile.return_value = (profile_data, False)
    args = MagicMock(likes_count="1", max_comments_pro_user="1", app_id="com.instagram.android", scrape_to_file=None)
    session = MagicMock(totalComments=0, totalLikes=0)
    session.check_limit.return_value = False
    with patch.object(interaction, "ProfileView", return_value=pv), \
            patch.object(interaction, "PostsGridView", return_value=grid), \
            patch.object(interaction, "random_sleep"), \
            patch.object(interaction, "register_like"), \
            patch.object(interaction, "save_crash") as crash:
        result = interact_with_user(
            device=MagicMock(), username="target", my_username="owner", likes_count="1",
            likes_percentage=100, stories_percentage=0, can_follow=False, follow_percentage=0,
            comment_percentage=0, pm_percentage=0, profile_filter=profile_filter, args=args,
            session_state=session, scraping_file=None, current_mode="profile")
    return result, post, grid, crash


def test_late_reel_like_control_is_reread_then_liked():
    result, post, grid, crash = run_reel([(None, None), (None, None), (False, MagicMock())])
    assert post._is_video_liked.call_count == 3
    post.like_video.assert_called_once_with()
    assert result[5] == 1
    crash.assert_not_called()
    grid.return_to_profile.assert_called_once_with()


def test_unreadable_reel_is_skipped_without_tapping_or_crash_dump():
    result, post, grid, crash = run_reel([(None, None)] * interaction.LIKE_STATE_READS)
    assert post._is_video_liked.call_count == interaction.LIKE_STATE_READS
    post.like_video.assert_not_called()
    post.open_video.assert_not_called()
    assert result[5] == 0
    crash.assert_not_called()
    grid.return_to_profile.assert_called_once_with()
