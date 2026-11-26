"""Offline checks for opened-post hearts whose selected flag is unreliable."""
import unittest
from unittest.mock import MagicMock, patch

from InstaAddict.core.views import OpenedPostView


class OpenedPostLikeStateTests(unittest.TestCase):
    def setUp(self):
        self.view = object.__new__(OpenedPostView)
        self.view.device = MagicMock()
        self.button = MagicMock()
        self.button.exists.return_value = True
        # Observed accessibility shape: content-desc="Liked", selected="false".
        self.button.get_selected.return_value = False

    def test_post_and_video_read_exact_labels_without_selected_flag(self):
        for label, expected in [("Liked", True), ("Unlike", True), ("Like", False),
                                ("", None), ("Like this post", None), ("12 likes", None)]:
            with self.subTest(label=label):
                self.button.get_desc.return_value = label
                with patch.object(self.view, "_get_post_like_button", return_value=self.button):
                    self.assertIs(self.view._is_post_liked()[0], expected)
                self.view.device.find.return_value = self.button
                self.assertIs(self.view._is_video_liked()[0], expected)
        self.button.get_selected.assert_not_called()

    def test_missing_post_and_video_buttons_are_unknown(self):
        with patch.object(self.view, "_get_post_like_button", return_value=None):
            self.assertEqual(self.view._is_post_liked(), (None, None))
        self.button.exists.return_value = False
        self.view.device.find.return_value = self.button
        self.assertEqual(self.view._is_video_liked(), (None, None))

    def test_disappearing_button_cannot_confirm_a_like(self):
        self.button.exists.return_value = False
        with patch.object(self.view, "_get_post_like_button", return_value=self.button):
            self.assertIsNone(self.view._is_post_liked()[0])

    def test_button_disappearing_during_label_read_is_unknown(self):
        self.button.exists.side_effect = [True, False]
        self.button.get_desc.return_value = "Liked"
        with patch.object(self.view, "_get_post_like_button", return_value=self.button):
            self.assertIsNone(self.view._is_post_liked()[0])

    def test_unknown_label_never_uses_optimistic_selected_flag(self):
        self.button.get_selected.return_value = True
        self.button.get_desc.return_value = ""
        with patch.object(self.view, "_get_post_like_button", return_value=self.button):
            self.assertIsNone(self.view._is_post_liked()[0])
        self.button.get_selected.assert_not_called()

    def test_liked_and_unknown_posts_are_never_toggled(self):
        for state, result in [(True, True), (None, False)]:
            with self.subTest(state=state), patch.object(self.view, "_is_post_liked", return_value=(state, self.button)):
                self.assertIs(self.view.like_post(), result)
        self.view.device.find.assert_not_called()
        self.button.click.assert_not_called()

    def test_post_double_tap_confirmation_never_retries_unknown_or_liked(self):
        for state, result in [(True, True), (None, False)]:
            self.button.reset_mock()
            media = MagicMock()
            media.exists.return_value = True
            self.view.device.find.return_value = media
            self.view.has_tags = False
            with self.subTest(state=state), patch.object(self.view, "_is_post_liked", side_effect=[(False, self.button), (state, self.button)]):
                self.assertIs(self.view.like_post(), result)
            media.double_click.assert_called_once()
            self.button.click.assert_not_called()

    def test_direct_heart_uses_label_confirmation(self):
        media = MagicMock()
        media.exists.return_value = False
        self.view.device.find.side_effect = [media, self.button]
        self.button.get_desc.return_value = "Liked"
        with patch.object(self.view, "_is_post_liked", return_value=(False, self.button)), patch("InstaAddict.core.views.UniversalActions.detect_block"):
            self.assertIs(self.view.like_post(), True)
        self.button.click.assert_called_once()
        self.button.get_selected.assert_not_called()

    def test_video_liked_and_unknown_initial_states_are_never_toggled(self):
        for state, result in [(True, True), (None, False)]:
            with self.subTest(state=state), patch.object(self.view, "_is_video_liked", return_value=(state, self.button)):
                self.assertIs(self.view.like_video(), result)
        self.view.device.find.assert_not_called()

    def test_video_after_double_tap_never_retries_unknown_or_liked(self):
        for state, result in [(True, True), (None, False)]:
            self.button.reset_mock()
            media = MagicMock()
            with self.subTest(state=state), patch.object(self.view, "_is_video_liked", side_effect=[(False, self.button), (state, self.button)]), patch.object(self.view, "_is_video_in_fullscreen", return_value=(True, media)), patch("InstaAddict.core.views.UniversalActions.detect_block"):
                self.assertIs(self.view.like_video(), result)
            media.double_click.assert_called_once()
            self.button.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
