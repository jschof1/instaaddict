"""Completed viewing windows are measured separately from story and like totals."""
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from InstaAddict.core import views
from InstaAddict.core.session_state import SessionState, SessionStateEncoder


class VideoWatchAccountingTests(unittest.TestCase):
    def test_completed_video_wait_records_elapsed_time_and_serializes_separately(self):
        view=object.__new__(views.OpenedPostView)
        session=SessionState()
        with patch.object(views,"args",SimpleNamespace(watch_video_time="15-30",watch_photo_time="2-3")),patch.object(view,"_is_video_in_fullscreen",return_value=(False,None)),patch.object(view,"_get_video_time_left",return_value=0),patch.object(views,"get_value",return_value=20),patch.object(views,"sleep") as sleep,patch.object(views,"monotonic",side_effect=[100,120.25]),patch.object(SessionState,"_active_session",session):
            view.watch_media(views.MediaType.REEL)
        sleep.assert_called_once_with(20)
        saved=SessionStateEncoder().default(session)
        self.assertEqual(saved['video_watch_windows'],1);self.assertEqual(saved['video_watch_seconds'],20.25)
        self.assertEqual(saved['total_watched'],0);self.assertEqual(saved['total_likes'],0)
        self.assertEqual(SessionState().totalVideoWatchWindows,0)

    def test_interrupted_wait_does_not_claim_completed_window(self):
        view=object.__new__(views.OpenedPostView);session=SessionState()
        with patch.object(views,"args",SimpleNamespace(watch_video_time="15-30")),patch.object(view,"_is_video_in_fullscreen",return_value=(False,None)),patch.object(view,"_get_video_time_left",return_value=0),patch.object(views,"get_value",return_value=20),patch.object(views,"sleep",side_effect=RuntimeError('interrupted')),patch.object(SessionState,"_active_session",session),self.assertRaises(RuntimeError):
            view.watch_media(views.MediaType.VIDEO)
        self.assertEqual(session.totalVideoWatchWindows,0)
