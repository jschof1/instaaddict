"""Offline regressions for descriptionless grids and Instagram 451 navigation."""

import re
import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from InstaAddict.core.device_facade import DeviceFacade
from InstaAddict.core.interaction import interact_with_user
from InstaAddict.core.utils import ActionBlockedError
from InstaAddict.core.views import (
    ClassName, MediaType, OpenedPostView, PostsGridView, ProfileView,
    ResourceID, TabBarTabs, TabBarView,
)


def grid_xml(headers=1, top=400, columns=(3, 2), cell_height=300, bottom=1500):
    root = ET.Element("hierarchy")
    ET.SubElement(root, "node", {
        "resource-id": ResourceID.PROFILE_TABS_CONTAINER,
        "bounds": "[0,300][900,360]",
    })
    grid = ET.SubElement(root, "node", {
        "resource-id": ResourceID.LIST, "bounds": f"[0,0][900,{bottom}]",
    })
    for _ in range(headers):
        header = ET.SubElement(grid, "node", {"bounds": "[0,0][900,300]"})
        ET.SubElement(header, "node", {"bounds": "[0,100][300,150]", "text": "Following"})
    for row, count in enumerate(columns):
        wrapper = ET.SubElement(grid, "node")
        y = top + row * cell_height
        for col in range(count):
            bounds = f"[{col * 300},{y}][{(col + 1) * 300},{min(y + cell_height, bottom)}]"
            cell = ET.SubElement(wrapper, "node", {"bounds": bounds, "content-desc": ""})
            ET.SubElement(cell, "node", {"bounds": bounds})
    return ET.tostring(root, encoding="unicode")


def options_device(*options):
    """Match selectors, including text versus accessibility descriptions."""
    device = MagicMock()
    device._ig_is_opened.return_value = True

    def find(**selector):
        for properties in options:
            if all(
                re.fullmatch(value, properties.get(key[:-7], ""))
                if key.endswith("Matches") else properties.get(key) == value
                for key, value in selector.items()
            ):
                node = MagicMock()
                node.exists.return_value = True
                node.get_bounds.return_value = properties["bounds"]
                return node
        return SimpleNamespace(exists=lambda *args: False)

    device.find.side_effect = find
    return device


def option(text="", description="", x=100, y=600):
    return dict(text=text, description=description, className=ClassName.TEXT_VIEW,
                bounds=dict(left=x, top=y, right=x + 120, bottom=y + 40))


class TestPeekIdentification(unittest.TestCase):
    def test_normal_post_icons_and_report_only_are_not_peek(self):
        for nodes in (
            [option(description="Like"), option(description="Repost"), option(description="Report")],
            [option("Report")],
            [option("Like"), option(description="Repost")],
            [option("Like"), option("Repost", x=300)],  # horizontal toolbar
            [option("Like"), option("Report", y=1200)],  # unrelated distant text
        ):
            with self.subTest(nodes=nodes):
                self.assertFalse(OpenedPostView(options_device(*nodes)).is_peek_preview_opened())

    def test_vertical_text_menu_requires_both_like_and_context_options(self):
        for label in ("Like", "Unlike"):
            with self.subTest(label=label):
                device = options_device(option(label), option("Repost", y=680))
                self.assertTrue(OpenedPostView(device).is_peek_preview_opened())

    def test_regular_post_controls_override_menu_like_text(self):
        like = option("Like")
        like["resourceId"] = ResourceID.ROW_FEED_BUTTON_LIKE
        device = options_device(like, option("Report", y=680))
        self.assertFalse(OpenedPostView(device).is_peek_preview_opened())
        self.assertFalse(OpenedPostView(device).like_in_peek())

    @patch("InstaAddict.core.views.random_sleep")
    def test_dismissal_checks_first_and_sends_at_most_one_back(self, sleep):
        for states, result, backs in (([False], True, 0), ([True, False], True, 1),
                                      ([True, True], False, 1)):
            with self.subTest(states=states):
                device = MagicMock()
                view = OpenedPostView(device)
                with patch.object(view, "is_peek_preview_opened", side_effect=states):
                    self.assertEqual(view.dismiss_peek(), result)
                self.assertEqual(device.back.call_count, backs)
                device.deviceV2.click.assert_not_called()

    def test_peek_like_propagates_action_block(self):
        device = options_device(option("Like"), option("Repost", y=680))
        with patch("InstaAddict.core.views.UniversalActions.detect_block",
                   side_effect=ActionBlockedError("blocked")) as detect:
            with self.assertRaises(ActionBlockedError):
                OpenedPostView(device).like_in_peek()
        detect.assert_called_once_with(device)


class TestVisibleGrid(unittest.TestCase):
    def setUp(self):
        self.device = MagicMock()
        self.device.deviceV2.dump_hierarchy.return_value = grid_xml()
        self.grid = PostsGridView(self.device)
        for mocked in (
            patch("InstaAddict.core.telemetry.PerformanceTracker.get_instance"),
            patch.object(OpenedPostView, "is_peek_preview_opened", return_value=False),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_header_count_and_nested_descriptionless_cells_do_not_shift_indices(self):
        for headers in (0, 1, 3):
            with self.subTest(headers=headers):
                self.device.deviceV2.dump_hierarchy.return_value = grid_xml(headers=headers)
                with patch.object(OpenedPostView, "is_post_opened", return_value=True):
                    opened, media, _ = self.grid.navigateToPost(1, 1)
                self.assertIsInstance(opened, OpenedPostView)
                self.assertEqual(media, MediaType.UNKNOWN)
                self.device.deviceV2.click.assert_called_with(450, 850)
                profile = SimpleNamespace(device=self.device)
                self.assertEqual(ProfileView.count_photo_in_view(profile), (1, 2))

    def test_square_and_portrait_bottom_rows_are_excluded_even_when_bounds_fit(self):
        for height in (300, 400):
            for headers in (0, 1, 3):
                with self.subTest(height=height, headers=headers):
                    self.device.deviceV2.dump_hierarchy.return_value = grid_xml(
                        headers=headers, columns=(3, 3), cell_height=height,
                        bottom=400 + height + 250,
                    )
                    self.assertEqual(len(self.grid._get_visible_post_rows()), 1)
                    self.assertEqual(ProfileView.count_photo_in_view(
                        SimpleNamespace(device=self.device)), (1, 0))
                    self.assertEqual(self.grid.navigateToPost(1, 0), (None, None, None))
        self.device.deviceV2.click.assert_not_called()

    def test_captured_451_portrait_grid_geometry_counts_three_not_six(self):
        # Actual crash hierarchy: 238x317 thumbnails, bottom row clipped to 241px.
        root = ET.Element("hierarchy")
        ET.SubElement(root, "node", {"resource-id": ResourceID.PROFILE_TABS_CONTAINER,
                                   "bounds": "[0,574][720,671]"})
        grid = ET.SubElement(root, "node", {"resource-id": ResourceID.LIST,
                                          "bounds": "[0,671][720,1232]"})
        for top, bottom in ((671, 988), (991, 1232)):
            for left in (0, 241, 482):
                ET.SubElement(grid, "node", {
                    "bounds": f"[{left},{top}][{left + 238},{bottom}]"})
        self.device.deviceV2.dump_hierarchy.return_value = ET.tostring(root, encoding="unicode")
        self.assertEqual(ProfileView.count_photo_in_view(SimpleNamespace(device=self.device)), (1, 0))

    def test_navigation_heartbeats_confirm_progress_without_refreshing_retries(self):
        for opened in (False, True):
            with self.subTest(opened=opened), \
                 patch("InstaAddict.core.views.record_heartbeat") as beat, \
                 patch.object(OpenedPostView, "is_post_opened", return_value=opened), \
                 patch.object(self.grid, "_is_still_on_profile", return_value=True):
                self.grid.navigateToPost(0, 0)
                self.assertEqual(beat.call_count, 2 if opened else 1)
                if opened:
                    self.assertIn("confirmed", beat.call_args.args[1])

    def test_retry_refreshes_bounds_and_stops_after_two_taps(self):
        self.device.deviceV2.dump_hierarchy.side_effect = [grid_xml(), grid_xml(top=420)]
        with patch.object(OpenedPostView, "is_post_opened", return_value=False), \
             patch.object(self.grid, "_is_still_on_profile", return_value=True):
            self.assertEqual(self.grid.navigateToPost(0, 0), (None, None, None))
        self.assertEqual(self.device.deviceV2.click.call_args_list, [call(150, 550), call(150, 570)])

    def test_disappearing_profile_is_not_post_confirmation_or_permission_to_retap(self):
        with patch.object(OpenedPostView, "is_post_opened", return_value=False), \
             patch.object(self.grid, "_is_still_on_profile", return_value=False):
            self.assertEqual(self.grid.navigateToPost(0, 0), (None, None, None))
        self.device.deviceV2.click.assert_called_once_with(150, 550)

    def test_confirmed_peek_is_returned_for_bounded_handling(self):
        with patch.object(OpenedPostView, "is_peek_preview_opened", return_value=True):
            opened, _, _ = self.grid.navigateToPost(0, 0)
        self.assertTrue(opened.is_peek)
        self.device.deviceV2.click.assert_called_once_with(150, 550)

    def test_photo_image_marker_confirms_a_regular_post(self):
        photo = dict(resourceId=ResourceID.ROW_FEED_PHOTO_IMAGEVIEW,
                     bounds=dict(left=0, top=0, right=900, bottom=900))
        self.assertTrue(OpenedPostView(options_device(photo)).is_post_opened())

    def test_invalid_grid_and_slots_never_tap(self):
        for xml, row, col in (("<broken", 0, 0), ("<hierarchy/>", 0, 0),
                              (grid_xml(), 1, 2), (grid_xml(), -1, 0),
                              (grid_xml(), 0, 3)):
            with self.subTest(xml=xml, row=row, col=col):
                self.device.deviceV2.dump_hierarchy.return_value = xml
                self.assertEqual(self.grid.navigateToPost(row, col), (None, None, None))
        self.device.deviceV2.click.assert_not_called()

    def test_headers_and_cells_clipped_above_profile_tabs_are_excluded(self):
        self.device.deviceV2.dump_hierarchy.return_value = grid_xml(top=100)
        self.assertEqual(len(self.grid._get_visible_post_rows()), 1)
        self.assertEqual(ProfileView.count_photo_in_view(SimpleNamespace(device=self.device)), (0, 2))

    def test_negative_and_out_of_grid_bounds_are_not_tappable(self):
        for xml in (grid_xml(top=-400, columns=(3,)),
                    grid_xml(columns=(3,)).replace("[900,700]", "[920,700]")):
            with self.subTest(xml=xml):
                self.device.deviceV2.dump_hierarchy.return_value = xml
                self.assertEqual(self.grid.navigateToPost(0, 2), (None, None, None))
        self.device.deviceV2.click.assert_not_called()


class TestBoundedNavigation(unittest.TestCase):
    @patch("InstaAddict.core.views.UniversalActions.close_keyboard")
    def test_tab_replacement_after_first_click_does_not_receive_a_second_click(self, close):
        device = MagicMock()
        button = device.find.return_value
        button.exists.return_value = True

        def click(**kwargs):
            button.exists.return_value = False

        button.click.side_effect = click
        tabs = TabBarView(device)
        with patch.object(tabs, "is_tab_bar_visible", return_value=True):
            tabs._navigateTo(TabBarTabs.SEARCH)
        button.click.assert_called_once()

    @patch("InstaAddict.core.views.UniversalActions.close_keyboard")
    def test_failed_tabbar_recovery_stops_before_lookup_or_recursive_navigation(self, close):
        device = MagicMock()
        tabs = TabBarView(device)
        with patch.object(tabs, "is_tab_bar_visible", return_value=False), \
             patch.object(tabs, "_escape_subscreens", return_value=False) as escape:
            with self.assertRaises(DeviceFacade.JsonRpcError):
                tabs.navigateToSearch()
        escape.assert_called_once_with()
        device.find.assert_not_called()

    @patch("InstaAddict.core.views.UniversalActions.close_keyboard")
    @patch("InstaAddict.core.views.UniversalActions.dismiss_dialog", return_value=False)
    def test_missing_tab_is_an_explicit_failure(self, dismiss, close):
        device = MagicMock()
        device.find.return_value.exists.return_value = False
        tabs = TabBarView(device)
        with patch.object(tabs, "is_tab_bar_visible", return_value=True):
            with self.assertRaises(DeviceFacade.JsonRpcError):
                tabs.navigateToHome()

    @patch("InstaAddict.core.views.random_sleep")
    def test_return_to_profile_rechecks_after_last_back_and_never_overshoots(self, sleep):
        for checks, expected, backs in (([True], True, 0), ([False, True], True, 1),
                                         ([False, False, False, True], True, 3),
                                         ([False] * 4, False, 3)):
            with self.subTest(checks=checks):
                device = MagicMock()
                grid = PostsGridView(device)
                with patch.object(grid, "_is_still_on_profile", side_effect=checks), \
                     patch.object(OpenedPostView, "is_peek_preview_opened", return_value=False), \
                     patch("InstaAddict.core.views.record_heartbeat") as beat:
                    self.assertEqual(grid.return_to_profile(), expected)
                    self.assertEqual(beat.call_count, 2 if expected else 1)
                self.assertEqual(device.back.call_count, backs)

    @patch("InstaAddict.core.views.random_sleep")
    def test_peek_dismissal_does_not_add_an_extra_back(self, sleep):
        device = MagicMock()
        grid = PostsGridView(device)
        with patch.object(grid, "_is_still_on_profile", return_value=True), \
             patch.object(OpenedPostView, "is_peek_preview_opened", side_effect=[True, False]), \
             patch.object(OpenedPostView, "dismiss_peek", return_value=True) as dismiss:
            self.assertTrue(grid.return_to_profile())
        dismiss.assert_called_once_with()
        device.back.assert_not_called()

    def test_return_does_not_back_out_of_the_launcher(self):
        device = MagicMock()
        device._ig_is_opened.return_value = False
        self.assertFalse(PostsGridView(device).return_to_profile())
        device.back.assert_not_called()

    def test_failed_peek_dismissal_stops_without_an_additional_back(self):
        device = MagicMock()
        grid = PostsGridView(device)
        with patch.object(grid, "_is_still_on_profile", return_value=True), \
             patch.object(OpenedPostView, "is_peek_preview_opened", return_value=True), \
             patch.object(OpenedPostView, "dismiss_peek", return_value=False) as dismiss:
            self.assertFalse(grid.return_to_profile())
        dismiss.assert_called_once_with()
        device.back.assert_not_called()


class TestInteractionRecovery(unittest.TestCase):
    def test_reel_watch_like_and_follow_refresh_only_at_action_boundaries(self):
        device, profile, grid, post = (MagicMock() for _ in range(4))
        profile.count_photo_in_view.return_value = (1, 0)
        grid.return_to_profile.return_value = True
        grid.navigateToPost.return_value = (post, MediaType.REEL, 1)
        post.is_peek = False
        post.is_peek_preview_opened.return_value = False
        post._is_video_liked.return_value = (False, MagicMock())
        post.open_video.return_value = True
        post.like_video.return_value = True
        filters = MagicMock()
        filters.check_profile.return_value = (SimpleNamespace(is_private=False, posts_count=3), False)
        filters.can_comment.return_value = (False, False, False, False)
        events = []
        post.watch_media.side_effect = lambda *_: events.append("watch")
        post.like_video.side_effect = lambda: events.append("like") or True
        with patch("InstaAddict.core.interaction.ProfileView", return_value=profile), \
             patch("InstaAddict.core.interaction.PostsGridView", return_value=grid), \
             patch("InstaAddict.core.interaction._watch_stories", return_value=0), \
             patch("InstaAddict.core.interaction.can_like", return_value=True), \
             patch("InstaAddict.core.interaction.get_value", return_value=1), \
             patch("InstaAddict.core.interaction.shuffle"), \
             patch("InstaAddict.core.interaction.random_sleep"), \
             patch("InstaAddict.core.interaction.register_like"), \
             patch("InstaAddict.core.interaction._follow", side_effect=lambda *_: events.append("follow") or True), \
             patch("InstaAddict.core.interaction.record_heartbeat", side_effect=lambda stage, action: events.append((stage, action))):
            result = interact_with_user(
                device, "target", "bot", "1", 100, 0, True, 100,
                0, 0, filters, SimpleNamespace(max_comments_pro_user="0"), MagicMock(), None, "profile",
            )
        self.assertEqual([e if isinstance(e, str) else e[0] for e in events], [
            "post_watch", "watch", "post_like", "like", "post_like",
            "profile_follow", "follow", "profile_follow",
        ])
        self.assertEqual(result[5], 1)
        self.assertTrue(result[1])

    def test_daily_app_crash_limit_stops_before_restart_or_target_retry(self):
        from InstaAddict.core.decorators import run_safely
        device = MagicMock()
        state = MagicMock(totalCrashes=0)
        state.check_limit.return_value = True
        config = SimpleNamespace(args=SimpleNamespace(count_app_crashes=True))
        action = MagicMock(side_effect=DeviceFacade.AppHasCrashed())
        with patch("InstaAddict.core.decorators.stop_bot", side_effect=SystemExit(2)) as stop, \
             patch("InstaAddict.core.decorators.open_instagram") as reopen:
            wrapped = run_safely(device, "emulator-5554", [state], state, False, config)(action)
            with self.assertRaises(SystemExit):
                wrapped()
        self.assertEqual(state.totalCrashes, 1)
        action.assert_called_once()
        stop.assert_called_once()
        reopen.assert_not_called()

    def test_lost_profile_stops_posts_follow_and_dm_without_losing_confirmed_likes(self):
        for outcome in ("failed_open", "post", "peek"):
            with self.subTest(outcome=outcome):
                device, profile, grid, post = (MagicMock() for _ in range(4))
                profile.count_photo_in_view.return_value = (1, 0)
                grid.return_to_profile.return_value = False
                post.is_peek = outcome == "peek"
                post.is_peek_preview_opened.return_value = outcome == "peek"
                post.is_peek_already_liked.return_value = False
                post.like_in_peek.return_value = True
                post.dismiss_peek.return_value = False
                post._is_post_liked.return_value = (False, MagicMock())
                post.like_post.return_value = True
                grid.navigateToPost.return_value = (
                    (None, None, None) if outcome == "failed_open"
                    else (post, MediaType.PHOTO, 1)
                )
                filters = MagicMock()
                filters.check_profile.return_value = (SimpleNamespace(is_private=False, posts_count=3), False)
                filters.can_comment.return_value = (False, False, False, False)
                args = SimpleNamespace(max_comments_pro_user="0")
                with patch("InstaAddict.core.interaction.ProfileView", return_value=profile), \
                     patch("InstaAddict.core.interaction.PostsGridView", return_value=grid), \
                     patch("InstaAddict.core.interaction._watch_stories", return_value=0), \
                     patch("InstaAddict.core.interaction.can_like", return_value=True), \
                     patch("InstaAddict.core.interaction.get_value", return_value=2), \
                     patch("InstaAddict.core.interaction.shuffle"), \
                     patch("InstaAddict.core.interaction.save_crash"), \
                     patch("InstaAddict.core.interaction.random_sleep"), \
                     patch("InstaAddict.core.interaction.register_like") as register, \
                     patch("InstaAddict.core.interaction._follow") as follow, \
                     patch("InstaAddict.core.interaction._send_PM") as dm:
                    result = interact_with_user(
                        device, "target", "bot", "2", 100, 0, True, 100,
                        0, 100, filters, args, MagicMock(), None, "profile",
                    )
                grid.navigateToPost.assert_called_once()
                follow.assert_not_called()
                dm.assert_not_called()
                self.assertEqual(result[5], 0 if outcome == "failed_open" else 1)
                self.assertEqual(register.call_count, result[5])
                device.back.assert_not_called()


if __name__ == "__main__":
    unittest.main()
