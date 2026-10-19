import re
from unittest.mock import MagicMock, patch

from InstaAddict.core.views import MediaType


class TestReelsAdAndFollowFix:
    """Tests for Route-056: Reels false-positive ad classification, inline follow button, and comment lifecycle."""

    def test_ad_cta_regex_excludes_subscribe(self):
        """Verify that 'Subscribe' (creator subscription) is not classified as an ad CTA."""
        ad_cta_regex = (
            r"(?i)^(Learn More|Install Now|Install|Shop Now|Download|"
            r"Sign Up|Watch More|Apply Now|Get Offer|Book Now|"
            r"Contact Us|Play Game|Open app)$"
        )
        assert re.match(ad_cta_regex, "Subscribe") is None
        assert re.match(ad_cta_regex, "subscribe") is None

    def test_ad_cta_regex_matches_standard_ad_ctas(self):
        """Verify that genuine ad CTAs match ad_cta_regex."""
        ad_cta_regex = (
            r"(?i)^(Learn More|Install Now|Install|Shop Now|Download|"
            r"Sign Up|Watch More|Apply Now|Get Offer|Book Now|"
            r"Contact Us|Play Game|Open app)$"
        )
        for cta in [
            "Learn More", "learn more", "Install Now", "Install",
            "Shop Now", "Download", "Sign Up", "Watch More", "Apply Now",
            "Get Offer", "Book Now", "Contact Us", "Play Game", "Open app"
        ]:
            assert re.match(ad_cta_regex, cta) is not None, f"Expected {cta} to match ad_cta_regex"

    def test_reels_ad_bounds_validation(self):
        """Verify that elements with non-CTA coordinates (top header, tiny width) are rejected."""
        w, h = 1080, 2400

        # Top-docked recycled view (top=142, width=240) - should be REJECTED as ad
        top_bounds = {"top": 142, "bottom": 198, "left": 0, "right": 240}
        top_y = top_bounds.get("top", 0)
        top_w = top_bounds.get("right", 0) - top_bounds.get("left", 0)
        is_ad_top = (top_y > h * 0.4) and (top_w > w * 0.25)
        assert is_ad_top is False

        # Legitimate bottom ad CTA banner (top=2000, bottom=2150, left=50, right=1030) - should be ACCEPTED
        bottom_cta_bounds = {"top": 2000, "bottom": 2150, "left": 50, "right": 1030}
        bottom_y = bottom_cta_bounds.get("top", 0)
        bottom_w = bottom_cta_bounds.get("right", 0) - bottom_cta_bounds.get("left", 0)
        is_ad_bottom = (bottom_y > h * 0.4) and (bottom_w > w * 0.25)
        assert is_ad_bottom is True

        # Narrow button in bottom half (top=1500, width=50) - should be REJECTED as ad CTA
        narrow_bounds = {"top": 1500, "bottom": 1600, "left": 50, "right": 100}
        narrow_y = narrow_bounds.get("top", 0)
        narrow_w = narrow_bounds.get("right", 0) - narrow_bounds.get("left", 0)
        is_ad_narrow = (narrow_y > h * 0.4) and (narrow_w > w * 0.25)
        assert is_ad_narrow is False

    def test_reels_follow_button_regex_matches_inline_follow_button(self):
        """Verify that the follow button pattern matches modern Instagram inline_follow_button."""
        pattern = r".*inline_follow_button.*|.*clips_follow_button.*|.*follow_button.*"
        modern_id = "com.instagram.android:id/inline_follow_button"
        clips_id = "com.instagram.android:id/clips_follow_button"
        legacy_id = "com.instagram.android:id/follow_button"

        assert re.match(pattern, modern_id) is not None
        assert re.match(pattern, clips_id) is not None
        assert re.match(pattern, legacy_id) is not None

    @patch("InstaAddict.plugins.interact_reels.random_sleep")
    @patch("InstaAddict.plugins.interact_reels.evaluate_and_comment_reel", return_value="Ripper pup mate!")
    @patch("InstaAddict.plugins.interact_reels._comment")
    @patch("InstaAddict.plugins.interact_reels.TabBarView")
    @patch("InstaAddict.plugins.interact_reels.UniversalActions")
    def test_interact_reels_follows_with_inline_follow_button(
        self, mock_ua, mock_tab_bar, mock_comment, mock_evaluate, mock_sleep
    ):
        """Verify interact_reels finds and clicks inline_follow_button when follow_percentage is active."""
        from InstaAddict.plugins.interact_reels import InteractReelsPlugin

        mock_device = MagicMock()
        mock_d = MagicMock()
        mock_device.deviceV2 = mock_d
        mock_d.info = {"displayWidth": 1080, "displayHeight": 2400}
        mock_d.screenshot.return_value = b"dummy_png"

        # Mock escape_in_app_browser
        mock_ua.escape_in_app_browser.return_value = False

        # Mock ad_button and sponsored: not ads
        mock_ad_btn = MagicMock()
        mock_ad_btn.exists.return_value = False
        mock_sponsored = MagicMock()
        mock_sponsored.exists.return_value = False

        # Mock follow_btn with inline_follow_button
        mock_follow_btn = MagicMock()
        mock_follow_btn.exists.return_value = True

        def find_side_effect(**kwargs):
            if "textMatches" in kwargs and "Sponsored" in str(kwargs.get("textMatches")):
                return mock_sponsored
            elif "textMatches" in kwargs and "Learn More" in str(kwargs.get("textMatches")):
                return mock_ad_btn
            elif "resourceIdMatches" in kwargs and "inline_follow_button" in str(kwargs.get("resourceIdMatches")):
                return mock_follow_btn
            m = MagicMock()
            m.exists.return_value = False
            return m

        mock_device.find.side_effect = find_side_effect

        mock_configs = MagicMock()
        mock_configs.args.interact_reels = "1"
        mock_configs.args.evaluate_percentage = 100
        mock_configs.args.follow_percentage = 100
        mock_configs.args.reels_topic = "dogs"

        mock_session = MagicMock()
        mock_session.totalWatched = 0
        mock_session.totalLikes = 0
        mock_session.totalFollowed = 0
        mock_session.check_limit.return_value = False
        sessions = [mock_session]

        plugin = InteractReelsPlugin()
        plugin.run(mock_device, mock_configs, MagicMock(), sessions, MagicMock(), "interact-reels")

        # Verify follow button was clicked
        mock_follow_btn.click.assert_called_once()
        assert mock_session.totalFollowed == 1

    @patch("InstaAddict.core.interaction.random_sleep")
    @patch("InstaAddict.core.interaction.UniversalActions.detect_block")
    @patch("InstaAddict.core.interaction._comment", return_value=True)
    @patch("InstaAddict.core.interaction.PostsGridView")
    @patch("InstaAddict.core.interaction.ProfileView")
    @patch("InstaAddict.core.interaction._watch_stories", return_value=0)
    def test_post_lifecycle_comment_runs_while_post_is_open(
        self, mock_stories, mock_profile_view, mock_grid_view, mock_comment, mock_detect_block, mock_sleep
    ):
        """Verify that _comment() is called while the post is open, before device.back() returns to profile."""
        from InstaAddict.core.interaction import interact_with_user
        from InstaAddict.core.views import PostsGridView

        mock_device = MagicMock()
        mock_device._ig_is_opened.return_value = True
        mock_session = MagicMock()
        mock_session.check_limit.return_value = False
        mock_session.Limit.LIKES = "likes"
        mock_session.Limit.COMMENTS = "comments"
        mock_session.Limit.FOLLOWS = "follows"
        mock_session.Limit.PM = "pm"
        mock_session.Limit.TOTAL = "total"

        mock_filter = MagicMock()
        profile_data = MagicMock()
        profile_data.is_private = False
        profile_data.posts_count = 5
        mock_filter.check_profile.return_value = (profile_data, False)
        mock_filter.can_comment.return_value = (True, True, True, True)

        post_view_inst = MagicMock()
        post_view_inst.is_peek = False
        post_view_inst.is_peek_preview_opened.return_value = False
        post_view_inst.detect_opened_media_type.return_value = MediaType.PHOTO
        post_view_inst._is_post_liked.return_value = (False, None)
        post_view_inst.like_post.return_value = True

        grid_inst = PostsGridView(mock_device)
        grid_inst.navigateToPost = MagicMock(return_value=(post_view_inst, MediaType.PHOTO, 1))
        # Exercise bounded recovery: post is open, then the first Back restores the grid.
        grid_inst._is_still_on_profile = MagicMock(side_effect=[False, True])
        grid_inst.return_to_profile = MagicMock(wraps=grid_inst.return_to_profile)
        mock_grid_view.return_value = grid_inst

        prof_view_inst = MagicMock()
        prof_view_inst.count_photo_in_view.return_value = (1, 1)
        prof_inst_swipe = MagicMock()
        prof_inst_swipe.return_value = 100
        prof_view_inst.swipe_to_fit_posts = prof_inst_swipe
        mock_profile_view.return_value = prof_view_inst

        mock_args = MagicMock()
        mock_args.max_comments_pro_user = "1"
        mock_args.dont_type = True

        call_order = []
        post_view_inst.like_post.side_effect = lambda: (call_order.append("like_post"), True)[1]
        mock_comment.side_effect = lambda *args, **kwargs: (call_order.append("_comment"), True)[1]
        mock_device.back.side_effect = lambda *args, **kwargs: call_order.append("device.back")

        with patch("InstaAddict.core.interaction.can_like", return_value=True), \
             patch("InstaAddict.core.interaction.can_comment", return_value=True), \
             patch("InstaAddict.core.views.OpenedPostView.is_peek_preview_opened", return_value=False), \
             patch("InstaAddict.core.views.random_sleep"):
            result = interact_with_user(
                device=mock_device,
                username="test_user",
                my_username="bot_user",
                likes_count="1",
                likes_percentage="100",
                stories_percentage=0,
                can_follow=False,
                follow_percentage=0,
                comment_percentage=100,
                pm_percentage=0,
                profile_filter=mock_filter,
                args=mock_args,
                session_state=mock_session,
                scraping_file=None,
                current_mode="hashtag-posts-recent",
            )

        assert call_order == ["like_post", "_comment", "device.back"]
        grid_inst.return_to_profile.assert_called_once_with()
        assert grid_inst._is_still_on_profile.call_count == 2
        mock_device.back.assert_called_once_with()
        assert (result[5], result[7]) == (1, 1)
