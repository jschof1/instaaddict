from unittest.mock import MagicMock, patch

from InstaAddict.core.session_state import SessionState
from InstaAddict.core.utils import get_value
from InstaAddict.core.views import MediaType
from InstaAddict.core.interaction import can_comment, load_random_comment


class TestFollowsAndCommentsRobustness:
    """Tests for Route-057: Follow dict preservation, range percentage parsing, and already-liked commenting."""

    def test_interact_reels_range_percentage_parsing(self):
        """Verify that range expressions ('30-40', '60-80') parse without ValueError."""
        range_val = "30-40"
        val = get_value(str(range_val), None, 0)
        assert isinstance(val, int)
        assert 30 <= val <= 40

        single_val = "35"
        val2 = get_value(str(single_val), None, 0)
        assert val2 == 35

    def test_session_state_total_followed_is_dict_and_check_limit_works(self):
        """Verify that SessionState.totalFollowed is a dict and add_interaction preserves it."""
        configs = MagicMock()
        configs.args.total_likes_limit = "100"
        configs.args.total_follows_limit = "50"
        configs.args.total_unfollows_limit = "50"
        configs.args.total_comments_limit = "10"
        configs.args.total_pm_limit = "10"
        configs.args.total_watches_limit = "50"
        configs.args.total_successful_interactions_limit = "100"
        configs.args.total_total_limit = "200"
        configs.args.total_scraped_limit = "50"
        configs.args.total_crashes_limit = "5"

        session = SessionState(configs)
        session.set_limits_session()

        assert isinstance(session.totalFollowed, dict)
        session.add_interaction("interact-reels", succeed=True, followed=True, scraped=False)

        assert isinstance(session.totalFollowed, dict)
        assert session.totalFollowed.get("interact-reels") == 1
        assert sum(session.totalFollowed.values()) == 1

        # check_limit must not raise AttributeError or TypeError
        limit_reached = session.check_limit(limit_type=SessionState.Limit.FOLLOWS, output=False)
        assert limit_reached is False

    def test_can_comment_handles_none_filter(self):
        """Verify that can_comment returns True when profile_filter is None."""
        res = can_comment(MediaType.PHOTO, None, "feed")
        assert res is True

    def test_load_random_comment_guarantees_non_empty_fallback(self):
        """Verify that load_random_comment always returns a non-empty string."""
        with patch("InstaAddict.core.interaction._load_and_clean_txt_file", return_value=[]):
            comment = load_random_comment("test_user", MediaType.PHOTO)
            assert comment is not None
            assert len(comment.strip()) > 0

    @patch("InstaAddict.core.interaction.random_sleep")
    @patch("InstaAddict.core.interaction._comment")
    @patch("InstaAddict.core.interaction.can_comment", return_value=True)
    @patch("InstaAddict.core.interaction.PostsGridView")
    @patch("InstaAddict.core.interaction.ProfileView")
    def test_interact_with_user_comments_when_already_liked(
        self, mock_pv_cls, mock_pgv_cls, mock_can_comment, mock_comment, mock_sleep
    ):
        """Verify that interact_with_user evaluates _comment even when the post is already liked."""
        from InstaAddict.core.interaction import interact_with_user

        device = MagicMock()
        mock_pv = MagicMock()
        mock_pv.count_photo_in_view.return_value = (1, 1)
        mock_pv.swipe_to_fit_posts.return_value = 0
        mock_pv_cls.return_value = mock_pv

        mock_post_view = MagicMock()
        mock_post_view.is_peek = False
        mock_post_view.is_peek_preview_opened.return_value = False
        mock_post_view.detect_opened_media_type.return_value = MediaType.PHOTO
        mock_post_view._is_post_liked.return_value = (True, True)  # ALREADY LIKED!

        mock_pgv = MagicMock()
        mock_pgv.navigateToPost.return_value = (mock_post_view, MediaType.PHOTO, 1)
        mock_pgv.return_to_profile.return_value = True
        mock_pgv_cls.return_value = mock_pgv

        profile_filter = MagicMock()
        profile_data = MagicMock()
        profile_data.is_private = False
        profile_data.posts_count = 1
        profile_filter.check_profile.return_value = (profile_data, False)
        profile_filter.can_comment.return_value = (True, True, True, True)

        configs = MagicMock()
        configs.args.likes_count = "1"
        configs.args.max_comments_pro_user = "1"
        configs.args.app_id = "com.instagram.android"
        configs.args.scrape_to_file = None

        session = MagicMock()
        session.check_limit.return_value = False
        session.totalComments = 0
        session.totalLikes = 0

        mock_comment.return_value = True

        res = interact_with_user(
            device=device,
            username="target_user",
            my_username="bot_user",
            likes_count="1",
            likes_percentage=100,
            stories_percentage=0,
            can_follow=False,
            follow_percentage=0,
            comment_percentage=100,
            pm_percentage=0,
            profile_filter=profile_filter,
            args=configs.args,
            session_state=session,
            scraping_file=None,
            current_mode="profile",
        )

        # _comment must have been called even though already_liked was True
        mock_comment.assert_called_once()
        mock_post_view.like_post.assert_not_called()
        mock_pgv.return_to_profile.assert_called_once_with()
        device.back.assert_not_called()
        # interacted returned True because comment was executed
        assert res[0] is True
        assert (res[5], res[7]) == (0, 1)
