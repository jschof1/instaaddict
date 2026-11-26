import re
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from InstaAddict.core.device_facade import DeviceFacade, Mode
from InstaAddict.core.utils import EmptyList
from InstaAddict.plugins.action_unfollow_followers import ActionUnfollowFollowers


def test_device_facade_view_exists_timeout_kwarg():
    """Verify that DeviceFacade.View.exists accepts both timeout= and ui_timeout= without TypeError."""
    mock_u2_obj = MagicMock()
    mock_u2_obj.exists.return_value = True

    view = DeviceFacade.View(mock_u2_obj, MagicMock())

    # Call with timeout keyword argument
    result1 = view.exists(timeout=2)
    assert result1 is True
    mock_u2_obj.exists.assert_called_with(2)

    # Call with ui_timeout keyword argument
    result2 = view.exists(ui_timeout=5)
    assert result2 is True
    mock_u2_obj.exists.assert_called_with(5)

    # Call with positional argument
    result3 = view.exists(3)
    assert result3 is True
    mock_u2_obj.exists.assert_called_with(3)


def test_device_facade_view_set_text_uses_self_get_text():
    """Verify typing simulation calls self.get_text(error=False) safely."""
    mock_u2_obj = MagicMock()
    mock_device_v2 = MagicMock()

    view = DeviceFacade.View(mock_u2_obj, mock_device_v2)
    # Mock view.get_text
    view.get_text = MagicMock(return_value="hello")

    # Should not raise TypeError: UiObject.get_text() got an unexpected keyword argument 'error'
    view.set_text("hello", mode=Mode.TYPE)
    view.get_text.assert_called_with(error=False)


def test_gemini_vision_false_401_circuit_breaker_avoidance():
    """Verify that 429 quota exhaustion strings with retry floats containing '401' do not trip the 401 circuit breaker."""
    import InstaAddict.core.gemini_vision as gv

    # Reset circuit breaker
    gv.VISION_API_DEAD = False

    quota_error_msg = (
        "429 You exceeded your current quota, please check your plan and billing details. "
        "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests. "
        "Please retry in 7.924074016s. [links: https://ai.google.dev/gemini-api/docs/rate-limits]"
    )

    mock_device = MagicMock()
    mock_device.deviceV2.screenshot.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake_key_for_test"}), \
         patch("InstaAddict.core.gemini_vision.genai.GenerativeModel") as mock_model_cls, \
         patch("InstaAddict.core.gemini_vision._safe_rate_limit_sleep") as mock_sleep, \
         patch("InstaAddict.core.gemini_vision.Image.open") as mock_img_open:
        
        mock_img = MagicMock()
        mock_img.convert.return_value = mock_img
        mock_img_open.return_value = mock_img

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception(quota_error_msg)
        mock_model_cls.return_value = mock_model

        res = gv.get_vision_comment(mock_device)
        
        # Verify result is empty string (retries exhausted)
        assert res == ""
        # Crucially, VISION_API_DEAD must NOT have been tripped to True by '7.924074016s'!
        assert gv.VISION_API_DEAD is False
        assert mock_sleep.called


def test_action_unfollow_handles_empty_list_gracefully():
    """Verify that ActionUnfollowFollowers catches EmptyList when inspecting user_list and exits gracefully."""
    plugin = ActionUnfollowFollowers()
    mock_device = MagicMock()
    mock_device.get_info.return_value = {"displayWidth": 1080, "displayHeight": 1920}

    # Mock device.find to return a list container mock
    mock_user_list = MagicMock()
    mock_device.find.return_value = mock_user_list

    # When inspect_current_view is called, raise EmptyList
    with patch("InstaAddict.plugins.action_unfollow_followers.inspect_current_view", side_effect=EmptyList):
        with patch("InstaAddict.plugins.action_unfollow_followers.logger") as mock_logger:
            # Setup session state and storage mocks
            mock_storage = MagicMock()
            mock_storage.get_following_status.return_value = None
            mock_storage.non_bot_followings = set()
            mock_storage.whitelist = []

            # Set args
            plugin.args = MagicMock()
            plugin.args.unfollow_delay = "3"
            plugin.args.unfollow_non_followers = 10
            plugin.args.unfollow_any_non_followers = None
            plugin.args.unfollow_followed_by_anyone = None
            plugin.args.unfollow_restriction = "followed-by-script-non-followers"
            plugin.args.ignore_followers_cache = False
            plugin.args.sort_followers_newest_to_oldest = False
            plugin.ResourceID = MagicMock()

            # Mock sort_button and top_tab
            mock_sort_btn = MagicMock()
            mock_sort_btn.exists.return_value = False
            mock_device.find.return_value = mock_sort_btn

            # Run iterate_over_followings
            plugin.iterate_over_followings(
                device=mock_device,
                count=5,
                on_unfollow=MagicMock(),
                storage=mock_storage,
                unfollow_restriction=MagicMock(),
                my_username="lolatheozjack",
                posts_end_detector=MagicMock(),
                job_name="unfollow-followers",
            )

            # Must have logged that list is empty and broken out without raising unhandled EmptyList
            assert any("empty or reached the end" in str(call) for call in mock_logger.info.call_args_list)


def test_profile_view_harvest_followers_handles_empty_list():
    """Verify that ProfileView.harvest_visible_followers catches EmptyList and returns cleanly."""
    from InstaAddict.core.views import ProfileView

    mock_device = MagicMock()
    mock_device.find.return_value = MagicMock()

    pv = ProfileView(mock_device)
    with patch("InstaAddict.core.views.inspect_current_view", side_effect=EmptyList):
        with patch("InstaAddict.core.views.logger") as mock_logger:
            result = pv.harvest_visible_followers(max_scrolls=2)
            assert result == []
            assert any("empty or reached end of list" in str(call) for call in mock_logger.info.call_args_list)


def test_handle_likers_handles_empty_list():
    """Verify that handle_likers catches EmptyList when inspect_current_view raises it."""
    from InstaAddict.core.handle_sources import handle_likers

    mock_device = MagicMock()
    mock_device.get_info.return_value = {"displayWidth": 1080, "displayHeight": 1920}
    mock_container = MagicMock()

    with patch("InstaAddict.core.handle_sources.OpenedPostView") as mock_opened_view_cls, \
         patch("InstaAddict.core.handle_sources.inspect_current_view", side_effect=EmptyList), \
         patch("InstaAddict.core.handle_sources.UniversalActions.escape_in_app_browser", return_value=False), \
         patch("InstaAddict.core.handle_sources.logger") as mock_logger:

        mock_opv = MagicMock()
        mock_opv._getUserContainer.return_value = mock_container
        mock_opened_view_cls.return_value = mock_opv

        mock_filter = MagicMock()
        mock_filter.is_num_likers_in_range.return_value = True

        with patch("InstaAddict.core.handle_sources.nav_to_hashtag_or_place", return_value=True), \
             patch("InstaAddict.core.handle_sources.PostsViewList") as mock_pvl_cls:
            
            mock_pvl = MagicMock()
            mock_pvl._check_if_last_post.return_value = (True, "desc", "user", False, False, False)
            mock_pvl._find_likers_container.return_value = (True, 10)
            mock_pvl.swipe_to_fit_posts.return_value = True
            mock_pvl_cls.return_value = mock_pvl

            mock_session = MagicMock()
            mock_session.totalPostsChecked = 1

            # Should not raise EmptyList
            handle_likers(
                self=MagicMock(),
                device=mock_device,
                session_state=mock_session,
                target="#dog",
                current_job="hashtag-likers-recent",
                storage=MagicMock(),
                profile_filter=mock_filter,
                posts_end_detector=MagicMock(),
                on_interaction=MagicMock(),
                interaction=MagicMock(),
                is_follow_limit_reached=MagicMock(),
            )

        assert any("Likers list is empty or reached the end" in str(call) for call in mock_logger.info.call_args_list)


@pytest.mark.parametrize("resource_name", ["ROW_FEED_BUTTON_LIKE", "LIKE_BUTTON"])
@pytest.mark.parametrize("has_context", [False, True])
def test_peek_preview_no_false_positive_on_reels_and_feed_posts(resource_name, has_context):
    """Ordinary post actions veto Peek even when matching menu text is present."""
    from InstaAddict.core.views import ClassName, OpenedPostView, ResourceID

    mock_device = MagicMock()
    mock_device._ig_is_opened.return_value = True

    opv = OpenedPostView(mock_device)

    def mock_find(**kwargs):
        elem = MagicMock()
        resource_pattern = kwargs.get("resourceIdMatches", "")
        text_pattern = kwargs.get("textMatches", "")
        if resource_pattern and re.fullmatch(resource_pattern, getattr(ResourceID, resource_name)):
            elem.exists.return_value = True
        elif kwargs.get("className") == ClassName.TEXT_VIEW and re.fullmatch(text_pattern, "Like"):
            elem.exists.return_value = True
            elem.get_bounds.return_value = {"left": 100, "top": 600, "right": 300, "bottom": 640}
        elif kwargs.get("className") == ClassName.TEXT_VIEW and re.fullmatch(text_pattern, "Report"):
            elem.exists.return_value = has_context
            elem.get_bounds.return_value = {"left": 100, "top": 680, "right": 300, "bottom": 720}
        else:
            elem.exists.return_value = False
        return elem

    mock_device.find.side_effect = mock_find

    # Crucial assertion: Must evaluate to False!
    assert opv.is_peek_preview_opened() is False


@pytest.mark.parametrize("like_label", ["Like", "Unlike"])
@pytest.mark.parametrize("context_label", ["Repost", "Report"])
def test_peek_preview_detects_real_peek_preview(like_label, context_label):
    """Require both vertical TextView options with real bounds for a Peek menu."""
    from InstaAddict.core.views import ClassName, OpenedPostView

    mock_device = MagicMock()
    mock_device._ig_is_opened.return_value = True

    opv = OpenedPostView(mock_device)
    like_option = MagicMock()
    like_option.exists.return_value = True
    like_option.get_bounds.return_value = {"left": 100, "top": 600, "right": 300, "bottom": 640}
    context_option = MagicMock()
    context_option.exists.return_value = True
    context_option.get_bounds.return_value = {"left": 100, "top": 680, "right": 300, "bottom": 720}

    def mock_find(**kwargs):
        text_pattern = kwargs.get("textMatches", "")
        if kwargs.get("className") == ClassName.TEXT_VIEW:
            if re.fullmatch(text_pattern, like_label):
                return like_option
            if re.fullmatch(text_pattern, context_label):
                return context_option
        elem = MagicMock()
        elem.exists.return_value = False
        return elem

    mock_device.find.side_effect = mock_find

    assert opv.is_peek_preview_opened() is True

    like_option.exists.return_value = False
    assert opv.is_peek_preview_opened() is False


def test_is_tab_bar_visible_catches_app_has_crashed():
    """Verify that is_tab_bar_visible catches AppHasCrashed and returns False without raising fatal exception."""
    from InstaAddict.core.views import TabBarView

    mock_device = MagicMock()
    mock_device._ig_is_opened.return_value = True
    mock_device.find.side_effect = DeviceFacade.AppHasCrashed("App has crashed / has been closed!")

    tbv = TabBarView(mock_device)
    assert tbv.is_tab_bar_visible() is False


def test_is_tab_bar_visible_returns_false_when_ig_not_opened():
    """Verify that is_tab_bar_visible returns False immediately when Instagram is not in foreground."""
    from InstaAddict.core.views import TabBarView

    mock_device = MagicMock()
    mock_device._ig_is_opened.return_value = False

    tbv = TabBarView(mock_device)
    assert tbv.is_tab_bar_visible() is False
    # device.find should not even have been called
    assert mock_device.find.call_count == 0


def test_escape_subscreens_relaunches_when_ig_not_opened():
    """Verify that _escape_subscreens relaunches Instagram via open_instagram if app is in background."""
    from InstaAddict.core.views import TabBarView

    mock_device = MagicMock()
    mock_device._ig_is_opened.side_effect = [False, True, True]

    tbv = TabBarView(mock_device)
    with patch("InstaAddict.core.utils.open_instagram", return_value=True) as mock_open:
        with patch.object(tbv, "is_tab_bar_visible", side_effect=[False, True]):
            res = tbv._escape_subscreens()
            assert res is True
            assert mock_open.called


def test_gemini_vision_daily_quota_circuit_breaker():
    """Verify that daily quota limit exhaustion (GenerateRequestsPerDay) immediately trips VISION_API_DEAD without sleeping."""
    import InstaAddict.core.gemini_vision as gv

    gv.VISION_API_DEAD = False

    daily_quota_error = (
        "429 You exceeded your current quota, please check your plan and billing details. "
        "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
        "limit: 20, model: gemini-3.6-flash. "
        "quota_id: 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'"
    )

    mock_device = MagicMock()
    mock_device.deviceV2.screenshot.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake_key_for_test"}), \
         patch("InstaAddict.core.gemini_vision.genai.GenerativeModel") as mock_model_cls, \
         patch("InstaAddict.core.gemini_vision._safe_rate_limit_sleep") as mock_sleep, \
         patch("InstaAddict.core.gemini_vision.Image.open") as mock_img_open:

        mock_img = MagicMock()
        mock_img.convert.return_value = mock_img
        mock_img_open.return_value = mock_img

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception(daily_quota_error)
        mock_model_cls.return_value = mock_model

        res = gv.get_vision_comment(mock_device)
        assert res == ""
        # Crucial assertion: Must trip circuit breaker instantly
        assert gv.VISION_API_DEAD is True
        # Must NOT have slept because daily quota cannot recover in 60s
        assert mock_sleep.called is False


def test_open_instagram_records_heartbeats():
    """Verify that open_instagram emits watchdog heartbeats to prevent premature inactivity timeouts."""
    from InstaAddict.core.utils import open_instagram

    mock_device = MagicMock()
    mock_device.deviceV2.app_current.return_value = {"package": "com.instagram.android"}

    with patch("InstaAddict.core.watchdog.record_heartbeat") as mock_hb, \
         patch("InstaAddict.core.utils.random_sleep"), \
         patch("InstaAddict.core.utils.check_if_crash_popup_is_there", return_value=False), \
         patch("InstaAddict.core.views.TabBarView.is_tab_bar_visible", return_value=True), \
         patch("InstaAddict.core.views.UniversalActions.dismiss_dialog", return_value=False), \
         patch("subprocess.run"):
        mock_device.app_id = "com.instagram.android"
        res = open_instagram(mock_device)
        assert res is True
        assert mock_hb.called
        # Verify it was called with startup stage
        stages = [call.args[0] for call in mock_hb.call_args_list if call.args]
        assert "startup" in stages


def test_profile_startup_recovery_on_none_fields():
    """Verify that when profile fields return None initially, self-healing recovery triggers re-navigation."""
    from InstaAddict.core.views import ProfileView, TabBarView

    mock_device = MagicMock()
    tbv = TabBarView(mock_device)
    pv = ProfileView(mock_device)

    # Simulate getProfileInfo returning None on 1st call, valid on 2nd
    pv.getProfileInfo = MagicMock(side_effect=[
        (None, None, None, None),
        ("lolatheozjack", 10, 100, 200)
    ])
    tbv.navigateToProfile = MagicMock()

    # Simulate the recovery block logic
    session_state = MagicMock()
    (
        session_state.my_username,
        session_state.my_posts_count,
        session_state.my_followers_count,
        session_state.my_following_count,
    ) = pv.getProfileInfo()

    if (
        session_state.my_username is None
        or session_state.my_posts_count is None
        or session_state.my_followers_count is None
        or session_state.my_following_count is None
    ):
        tbv.navigateToProfile()
        (
            session_state.my_username,
            session_state.my_posts_count,
            session_state.my_followers_count,
            session_state.my_following_count,
        ) = pv.getProfileInfo()

    assert tbv.navigateToProfile.called
    assert session_state.my_username == "lolatheozjack"
    assert session_state.my_followers_count == 100


def test_action_bar_view_app_has_crashed_resilience():
    """Verify that ActionBarView and ProfileView handle AppHasCrashed during __init__ without failing."""
    from InstaAddict.core.views import ActionBarView, ProfileView

    mock_device = MagicMock()
    mock_device.find.side_effect = DeviceFacade.AppHasCrashed("App closed")

    # Creating ActionBarView must not raise AppHasCrashed
    abv = ActionBarView(mock_device)
    assert abv.action_bar is None

    # Creating ProfileView must also not raise AppHasCrashed
    pv = ProfileView(mock_device)
    assert pv.action_bar is None


def test_profile_view_get_username_app_has_crashed_returns_none():
    """Verify that ProfileView.getUsername returns None on AppHasCrashed rather than raising."""
    from InstaAddict.core.views import ProfileView

    mock_device = MagicMock()
    mock_device.find.side_effect = DeviceFacade.AppHasCrashed("App closed")

    pv = ProfileView(mock_device)
    assert pv.getUsername(error=False) is None
    assert pv.getUsername(error=True) is None


def test_open_instagram_checks_foreground_before_success():
    """Verify that open_instagram returns False if Instagram fails to stay in the foreground."""
    from InstaAddict.core.utils import open_instagram

    mock_device = MagicMock()
    mock_device.deviceV2.app_current.return_value = {"package": "com.android.launcher"}
    mock_device._ig_is_opened.return_value = False

    mock_device.app_id = "com.instagram.android"

    with patch("InstaAddict.core.utils.random_sleep"), \
         patch("InstaAddict.core.utils.check_if_crash_popup_is_there", return_value=False), \
         patch("time.sleep"):
        res = open_instagram(mock_device)
        assert res is False


def test_startup_retry_recovers_from_app_has_crashed():
    """Verify that startup retry catches AppHasCrashed and relaunches via open_instagram."""
    mock_device = MagicMock()
    mock_session_state = MagicMock()
    mock_session_state.totalCrashes = 0

    open_ig_calls = []

    def mock_open_ig(dev):
        open_ig_calls.append(dev)
        return True

    # Simulate 3 attempts: attempt 0 raises AppHasCrashed, attempt 1 succeeds
    calls = [0]

    def mock_profile_init(dev):
        calls[0] += 1
        if calls[0] == 1:
            raise DeviceFacade.AppHasCrashed("Instagram closed during startup")
        mock_pv = MagicMock()
        mock_pv.getProfileInfo.return_value = ("lolatheozjack", 10, 100, 50)
        return mock_pv

    startup_ok = False
    for startup_attempt in range(3):
        try:
            pv = mock_profile_init(mock_device)
            username, posts, followers, following = pv.getProfileInfo()
            startup_ok = True
            break
        except DeviceFacade.AppHasCrashed:
            mock_session_state.totalCrashes += 1
            mock_open_ig(mock_device)

    assert startup_ok is True
    assert mock_session_state.totalCrashes == 1
    assert len(open_ig_calls) == 1
    assert username == "lolatheozjack"


def test_session_state_skip_reasons_and_job_metrics():
    """Verify that SessionState records skip reasons, job metrics, and crash history, and encodes them to JSON."""
    import json
    from InstaAddict.core.session_state import SessionState, SessionStateEncoder

    ss = SessionState()
    ss.record_skip_reason("LT_FOLLOWERS")
    ss.record_skip_reason("LT_FOLLOWERS")
    ss.record_skip_reason("POTENCY_RATIO")

    assert ss.skip_reasons["LT_FOLLOWERS"] == 2
    assert ss.skip_reasons["POTENCY_RATIO"] == 1

    ss.start_job("interact_hashtag")
    ss.record_job_interaction("interact_hashtag", success=True, followed=True)
    ss.record_job_interaction("interact_hashtag", success=False)
    ss.end_job("interact_hashtag", "completed")

    assert "interact_hashtag" in ss.job_metrics
    jm = ss.job_metrics["interact_hashtag"]
    assert jm["status"] == "completed"
    assert jm["interactions_attempted"] == 2
    assert jm["interactions_successful"] == 1
    assert jm["followed"] == 1

    ss.record_crash({"timestamp": "2026-09-22T00:00:00", "error_reason": "test_crash"})
    assert len(ss.crash_history) == 1
    assert ss.totalCrashes == 1

    encoded = json.loads(json.dumps(ss, cls=SessionStateEncoder))
    assert encoded["skip_reasons"]["LT_FOLLOWERS"] == 2
    assert encoded["job_metrics"]["interact_hashtag"]["interactions_attempted"] == 2
    assert len(encoded["crash_history"]) == 1


def test_filter_records_skip_reason_name_in_active_session_state():
    """Verify Filter.return_check_profile records SkipReason into active SessionState."""
    from InstaAddict.core.filter import Filter, Profile, SkipReason
    from InstaAddict.core.session_state import SessionState

    mock_storage = MagicMock()
    f = Filter(mock_storage)

    ss = SessionState()
    SessionState.set_active(ss)
    try:
        mock_profile = Profile(0, "Follow", False, True, 10, 100, 5, 0, False)
        skipped = f.return_check_profile("testuser", mock_profile, SkipReason.LT_FOLLOWERS)
        assert skipped is True
        assert ss.totalProfilesSkipped == 1
        assert ss.skip_reasons.get("LT_FOLLOWERS") == 1

        skipped2 = f.return_check_profile("testuser2", mock_profile, SkipReason.POTENCY_RATIO)
        assert skipped2 is True
        assert ss.totalProfilesSkipped == 2
        assert ss.skip_reasons.get("POTENCY_RATIO") == 1
    finally:
        SessionState.set_active(None)


def test_save_crash_generates_context_json_and_records_to_session(tmp_path, monkeypatch):
    """Verify save_crash writes crash_context.json and records crash in active SessionState."""
    import os
    import zipfile
    import json
    from InstaAddict.core.session_state import SessionState
    from InstaAddict.core.utils import save_crash

    monkeypatch.chdir(tmp_path)
    mock_device = MagicMock()
    mock_device.get_current_package.return_value = "com.instagram.android"
    mock_device.is_screen_on.return_value = True

    ss = SessionState()
    ss.my_username = "testuser"
    SessionState.set_active(ss)
    try:
        save_crash(mock_device, error_reason="Testing crash telemetry")

        assert len(ss.crash_history) == 1
        assert ss.crash_history[0]["error_reason"] == "Testing crash telemetry"
        assert ss.crash_history[0]["foreground_package"] == "com.instagram.android"

        # Check zip archive
        zip_path = ss.crash_history[0]["crash_archive"]
        assert os.path.exists(zip_path)
        with zipfile.ZipFile(zip_path, "r") as z:
            assert "crash_context.json" in z.namelist()
            with z.open("crash_context.json") as jf:
                data = json.load(jf)
                assert data["username"] == "testuser"
                assert data["error_reason"] == "Testing crash telemetry"
                assert data["foreground_package"] == "com.instagram.android"
    finally:
        SessionState.set_active(None)


def test_dogfood_optimizer_analyzes_skip_reasons_and_recommends_filter_tuning(tmp_path, monkeypatch):
    """Verify DogfoodOptimizer detects filter starvation and produces actionable filter recommendations."""
    import json
    from InstaAddict.core.dogfood import DogfoodOptimizer

    monkeypatch.chdir(tmp_path)
    acc_dir = tmp_path / "accounts" / "testuser"
    acc_dir.mkdir(parents=True)

    sessions_data = [
        {
            "id": "s1",
            "total_interactions": 10,
            "successful_interactions": 2,
            "total_likes": 2,
            "total_followed": 0,
            "total_crashes": 0,
            "skip_reasons": {
                "LT_FOLLOWERS": 60,
                "POTENCY_RATIO": 10,
            },
        }
    ]
    with open(acc_dir / "sessions.json", "w") as f:
        json.dump(sessions_data, f)

    with open(acc_dir / "filters.yml", "w") as f:
        f.write("min_followers: 50\nmin_potency_ratio: 0.5\n")

    optimizer = DogfoodOptimizer("testuser")
    analysis = optimizer.analyze()

    assert analysis["metrics"]["total_skips"] == 70
    assert analysis["skip_reasons"]["LT_FOLLOWERS"] == 60

    # Verify recommendation
    rec_cats = [r["category"] for r in analysis["recommendations"]]
    assert "Filter Starvation" in rec_cats

    # Verify auto-tuning applies to filters.yml
    tune_res = optimizer.apply_tuning(dry_run=False, backup=True)
    assert any(a.get("parameter") == "min_followers" for a in tune_res["applied"])

    with open(acc_dir / "filters.yml", "r") as f:
        content = f.read()
    assert "min_followers: 35" in content  # 50 * 0.7 = 35


def test_dogfood_optimizer_analyzes_job_performance_standards(tmp_path, monkeypatch):
    """Verify DogfoodOptimizer identifies jobs failing standards (100% conversion failure)."""
    import json
    from InstaAddict.core.dogfood import DogfoodOptimizer

    monkeypatch.chdir(tmp_path)
    acc_dir = tmp_path / "accounts" / "testuser"
    acc_dir.mkdir(parents=True)

    sessions_data = [
        {
            "id": "s1",
            "total_interactions": 10,
            "successful_interactions": 5,
            "total_likes": 5,
            "total_followed": 1,
            "total_crashes": 0,
            "job_metrics": {
                "interact_hashtag": {
                    "runs": 1,
                    "duration_seconds": 120.0,
                    "interactions_attempted": 8,
                    "interactions_successful": 0,
                }
            },
        }
    ]
    with open(acc_dir / "sessions.json", "w") as f:
        json.dump(sessions_data, f)

    optimizer = DogfoodOptimizer("testuser")
    analysis = optimizer.analyze()

    assert "interact_hashtag" in analysis["job_performance"]
    recs = [r for r in analysis["recommendations"] if r["category"] == "Task Performance Standards"]
    assert len(recs) >= 1
    assert "interact_hashtag" in recs[0]["issue"]


def test_home_view_navigate_to_search_handles_json_rpc_error():
    """Verify HomeView.navigateToSearch gracefully handles JsonRpcError and returns None (CO-067)."""
    from InstaAddict.core.views import HomeView

    mock_device = MagicMock()
    home_view = HomeView(mock_device)

    mock_action_bar = MagicMock()
    mock_search_btn = MagicMock()
    mock_search_btn.exists.return_value = True
    mock_search_btn.click.side_effect = DeviceFacade.JsonRpcError("-32002: UiObjectNotFound")
    mock_action_bar.child.return_value = mock_search_btn
    home_view.action_bar = mock_action_bar

    # Should not raise JsonRpcError, but return None gracefully
    result = home_view.navigateToSearch()
    assert result is None


def test_search_view_navigate_to_target_handles_search_bar_click_error():
    """Verify SearchView.navigate_to_target handles transient click errors defensively (CO-067)."""
    from InstaAddict.core.views import SearchView

    mock_device = MagicMock()
    search_view = SearchView(mock_device)

    mock_search_edit = MagicMock()
    mock_search_edit.click.side_effect = DeviceFacade.JsonRpcError("-32002: Client error")
    search_view._getSearchEditText = MagicMock(return_value=mock_search_edit)

    result = search_view.navigate_to_target("test_target", "hashtag")
    assert result is False


def test_run_safely_handles_empty_list_without_crash_or_restart():
    """Verify @run_safely treats EmptyList as non-fatal without calling restart() or incrementing crashes (CO-068)."""
    from InstaAddict.core.decorators import run_safely

    mock_device = MagicMock()
    mock_session_state = MagicMock()
    mock_session_state.totalCrashes = 0
    mock_sessions = [mock_session_state]
    mock_configs = MagicMock()

    @run_safely(
        device=mock_device,
        device_id="dummy_id",
        sessions=mock_sessions,
        session_state=mock_session_state,
        screen_record=None,
        configs=mock_configs,
    )
    def dummy_task():
        raise EmptyList()

    with patch("InstaAddict.core.decorators.restart") as mock_restart:
        # Calling dummy_task should catch EmptyList, not call restart, and not increment totalCrashes
        dummy_task()
        mock_restart.assert_not_called()
        assert mock_session_state.totalCrashes == 0


def test_dogfood_optimizer_sliding_window_separates_active_and_lifetime(tmp_path, monkeypatch):
    """Verify DogfoodOptimizer evaluates sliding window while maintaining lifetime metrics (CO-069)."""
    import json
    from InstaAddict.core.dogfood import DogfoodOptimizer

    monkeypatch.chdir(tmp_path)
    acc_dir = tmp_path / "accounts" / "testuser"
    acc_dir.mkdir(parents=True)

    # Create 8 sessions: first 3 have crashes, last 5 have 0 crashes
    sessions = []
    for i in range(8):
        crashes = 2 if i < 3 else 0
        sessions.append(
            {
                "id": f"s{i}",
                "total_interactions": 20,
                "successful_interactions": 15,
                "total_likes": 10,
                "total_followed": 2,
                "total_crashes": crashes,
                "total_subscreen_escapes": 0,
                "total_uploads_success": 0,
                "total_uploads_failed": 0,
            }
        )

    with open(acc_dir / "sessions.json", "w") as f:
        json.dump(sessions, f)

    optimizer = DogfoodOptimizer("testuser", window_sessions=5)
    report = optimizer.analyze()

    # Active window metrics (last 5 sessions)
    assert report["metrics"]["total_sessions"] == 5
    assert report["metrics"]["total_crashes"] == 0

    # Lifetime metrics (all 8 sessions)
    assert report["lifetime_metrics"]["total_sessions"] == 8
    assert report["lifetime_metrics"]["total_crashes"] == 6


def test_dogfood_optimizer_error_log_accurate_fatal_crash_counting(tmp_path, monkeypatch):
    """Verify DogfoodOptimizer accurately counts uncaught fatal crashes and ignores handled error traces (CO-069)."""
    from InstaAddict.core.dogfood import DogfoodOptimizer

    monkeypatch.chdir(tmp_path)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)

    log_content = (
        "[09/13 10:00:00] ERROR | Handled network error (views.py:100)\n"
        "Traceback (most recent call last):\n"
        "  File 'views.py', line 100, in foo\n"
        "    bar()\n"
        "[09/13 10:05:00] CRITICAL | Uncaught fatal exception: (log.py:158)\n"
        "Traceback (most recent call last):\n"
        "  File 'run.py', line 20, in <module>\n"
        "    crash()\n"
    )
    with open(logs_dir / "testuser_error_trace.log", "w", encoding="utf-8") as f:
        f.write(log_content)

    optimizer = DogfoodOptimizer("testuser")
    diag = optimizer._analyze_error_log()

    assert diag["total_errors"] == 1
    assert diag["total_criticals"] == 1
    # Only the uncaught fatal exception should be counted as fatal crash
    assert diag["fatal_crashes"] == 1


def test_dogfood_optimizer_recommendation_stability_root_cause_not_placebo_delay(tmp_path, monkeypatch):
    """Verify crash recommendation provides root-cause investigation parameter instead of placebo delay-mean (CO-069)."""
    import json
    from InstaAddict.core.dogfood import DogfoodOptimizer

    monkeypatch.chdir(tmp_path)
    acc_dir = tmp_path / "accounts" / "testuser"
    acc_dir.mkdir(parents=True)

    with open(acc_dir / "sessions.json", "w") as f:
        json.dump([{"total_interactions": 10, "successful_interactions": 8, "total_crashes": 2}], f)

    optimizer = DogfoodOptimizer("testuser")
    report = optimizer.analyze()

    stab_recs = [r for r in report["recommendations"] if r["category"] == "Stability & Timing"]
    assert len(stab_recs) == 1
    rec = stab_recs[0]
    # Parameter should NOT be delay-mean for crash issues
    assert rec["parameter"] == "stability_investigation"
    assert "crash traces" in rec["action"]


def test_session_state_finalize_jobs():
    """Verify finalize_jobs marks all in-progress jobs as interrupted and calculates duration (CO-072)."""
    from InstaAddict.core.session_state import SessionState

    ss = SessionState()
    ss.start_job("hashtag-posts-recent")
    ss.start_job("blogger-followers")
    # Simulate blogger-followers completed normally
    ss.end_job("blogger-followers", "completed")

    assert ss.job_metrics["hashtag-posts-recent"]["status"] == "in_progress"
    assert ss.job_metrics["hashtag-posts-recent"]["finished_at"] is None
    assert ss.job_metrics["blogger-followers"]["status"] == "completed"

    ss.finalize_jobs("interrupted")

    assert ss.job_metrics["hashtag-posts-recent"]["status"] == "interrupted"
    assert ss.job_metrics["hashtag-posts-recent"]["finished_at"] is not None
    assert isinstance(ss.job_metrics["hashtag-posts-recent"]["duration_seconds"], float)
    # blogger-followers should remain completed
    assert ss.job_metrics["blogger-followers"]["status"] == "completed"
    assert ss.current_job is None


def test_session_state_encoder_auto_finalizes_jobs():
    """Verify SessionStateEncoder automatically finalizes dangling in-progress jobs during serialization."""
    from InstaAddict.core.session_state import SessionState, SessionStateEncoder

    ss = SessionState()
    ss.start_job("upload-posts")
    encoder = SessionStateEncoder()
    encoded = encoder.default(ss)

    assert encoded["job_metrics"]["upload-posts"]["status"] == "interrupted"
    assert encoded["job_metrics"]["upload-posts"]["finished_at"] is not None


def test_record_source_skip_increments_profile_counters_and_skip_reasons():
    """Verify _record_source_skip increments skip_reasons, totalProfilesChecked, and totalProfilesSkipped."""
    from InstaAddict.core.handle_sources import _record_source_skip
    from InstaAddict.core.session_state import SessionState

    ss = SessionState()
    SessionState.set_active(ss)
    try:
        assert ss.totalProfilesChecked == 0
        assert ss.totalProfilesSkipped == 0
        assert ss.skip_reasons == {}

        _record_source_skip(ss, "COOLDOWN")
        assert ss.totalProfilesChecked == 1
        assert ss.totalProfilesSkipped == 1
        assert ss.skip_reasons.get("COOLDOWN") == 1

        _record_source_skip(ss, "BLACKLIST")
        assert ss.totalProfilesChecked == 2
        assert ss.totalProfilesSkipped == 2
        assert ss.skip_reasons.get("BLACKLIST") == 1
        assert ss.skip_reasons.get("COOLDOWN") == 1
    finally:
        SessionState.set_active(None)


def test_hashtag_and_places_view_get_first_image_view_alias():
    """Verify HashTagView and PlacesView expose _getFirstImageView and legacy _getFistImageView alias (CO-073)."""
    from InstaAddict.core.views import HashTagView, PlacesView
    from unittest.mock import MagicMock

    mock_device = MagicMock()
    ht = HashTagView(mock_device)
    assert hasattr(ht, "_getFirstImageView")
    assert hasattr(ht, "_getFistImageView")
    assert ht._getFistImageView == ht._getFirstImageView

    pv = PlacesView(mock_device)
    assert hasattr(pv, "_getFirstImageView")
    assert hasattr(pv, "_getFistImageView")
    assert pv._getFistImageView == pv._getFirstImageView


@pytest.mark.parametrize("resource_name", [
    "ZOOMABLE_VIEW_CONTAINER", "ROW_FEED_PHOTO_IMAGEVIEW", "CLIPS_VIDEO_CONTAINER",
    "ROOT_CLIPS_LAYOUT", "CLIPS_VIEWER_CONTAINER", "CLIPS_VIEWER_VIEW_PAGER",
])
def test_opened_post_view_is_post_opened_includes_reels_and_clips(resource_name):
    """Confirm posts only from an explicit media/viewer resource ID (CO-073)."""
    from InstaAddict.core.views import OpenedPostView, ResourceID
    from unittest.mock import MagicMock

    mock_device = MagicMock()
    visible_resource = getattr(ResourceID, resource_name)

    def mock_find(**kwargs):
        element = MagicMock()
        pattern = kwargs.get("resourceIdMatches", "")
        element.exists.return_value = bool(pattern and re.fullmatch(pattern, visible_resource))
        return element

    mock_device.find.side_effect = mock_find

    opened_view = OpenedPostView(mock_device)
    result = opened_view.is_post_opened()

    assert result is True
    # Verify find was called with resourceIdMatches checking clips containers
    call_kwargs = mock_device.find.call_args[1]
    pattern = call_kwargs["resourceIdMatches"]
    for expected_sub in ["zoomable_view_container", "row_feed_photo_imageview", "clips_video_container", "root_clips_layout", "clips_viewer_container"]:
        assert expected_sub in pattern.lower()

    visible_resource = ResourceID.PROFILE_TABS_CONTAINER
    assert opened_view.is_post_opened() is False


def test_nav_to_hashtag_or_place_tap_and_open_verification(monkeypatch):
    """Verify nav_to_hashtag_or_place taps center bounds, verifies is_post_opened, and returns True (CO-073)."""
    from InstaAddict.core.navigation import nav_to_hashtag_or_place
    from unittest.mock import MagicMock

    mock_device = MagicMock()
    mock_device.find.return_value.exists.return_value = False
    mock_device.deviceV2.click = MagicMock()

    mock_recycler = MagicMock()
    mock_image = MagicMock()
    mock_image.exists.return_value = True
    mock_image.get_bounds.return_value = {"left": 10, "top": 100, "right": 110, "bottom": 200}

    # Mock TargetView
    mock_target_view_instance = MagicMock()
    mock_target_view_instance._getRecentTab.return_value.exists.return_value = False
    mock_target_view_instance._getRecyclerView.return_value = mock_recycler
    mock_target_view_instance._getFirstImageView.return_value = mock_image

    mock_search_view = MagicMock()
    mock_search_view.navigate_to_target.return_value = True
    monkeypatch.setattr("InstaAddict.core.navigation.TabBarView.navigateToSearch", lambda self: mock_search_view)
    monkeypatch.setattr("InstaAddict.core.navigation.HashTagView", lambda dev: mock_target_view_instance)
    monkeypatch.setattr("InstaAddict.core.views.OpenedPostView.is_peek_preview_opened", lambda self: False)
    monkeypatch.setattr("InstaAddict.core.views.OpenedPostView.is_post_opened", lambda self: True)
    monkeypatch.setattr("InstaAddict.core.views.UniversalActions._check_if_no_posts", lambda self: False)

    res = nav_to_hashtag_or_place(mock_device, "cats", "hashtag-posts-recent")
    assert res is True
    # Verify click was called at center point: x=(10+110)//2 = 60, y=(100+200)//2 = 150
    mock_device.deviceV2.click.assert_called_with(60, 150)


def test_nav_to_hashtag_or_place_retries_and_returns_false_on_failure(monkeypatch):
    """Verify nav_to_hashtag_or_place retries once and returns False if post fails to open (CO-073)."""
    from InstaAddict.core.navigation import nav_to_hashtag_or_place
    from unittest.mock import MagicMock

    mock_device = MagicMock()
    mock_device.find.return_value.exists.return_value = False
    mock_device.deviceV2.click = MagicMock()

    mock_recycler = MagicMock()
    mock_image = MagicMock()
    mock_image.exists.return_value = True
    mock_image.get_bounds.return_value = {"left": 0, "top": 0, "right": 100, "bottom": 100}

    mock_target_view_instance = MagicMock()
    mock_target_view_instance._getRecentTab.return_value.exists.return_value = False
    mock_target_view_instance._getRecyclerView.return_value = mock_recycler
    mock_target_view_instance._getFirstImageView.return_value = mock_image

    mock_search_view = MagicMock()
    mock_search_view.navigate_to_target.return_value = True
    monkeypatch.setattr("InstaAddict.core.navigation.TabBarView.navigateToSearch", lambda self: mock_search_view)
    monkeypatch.setattr("InstaAddict.core.navigation.HashTagView", lambda dev: mock_target_view_instance)
    monkeypatch.setattr("InstaAddict.core.views.OpenedPostView.is_peek_preview_opened", lambda self: False)
    # is_post_opened returns False both times
    monkeypatch.setattr("InstaAddict.core.views.OpenedPostView.is_post_opened", lambda self: False)
    monkeypatch.setattr("InstaAddict.core.views.UniversalActions._check_if_no_posts", lambda self: False)

    res = nav_to_hashtag_or_place(mock_device, "dogs", "hashtag-posts-recent")
    assert res is False
    assert mock_device.deviceV2.click.call_count == 2


def test_handle_posts_consecutive_unidentifiable_circuit_breaker(monkeypatch):
    """Verify handle_posts breaks out after max consecutive unidentifiable posts and records dead hashtag (CO-074, CO-075)."""
    from InstaAddict.core.handle_sources import handle_posts
    from InstaAddict.core.session_state import SessionState
    from unittest.mock import MagicMock

    mock_device = MagicMock()
    mock_storage = MagicMock()
    mock_profile_filter = MagicMock()
    mock_on_interaction = MagicMock()
    mock_interaction = MagicMock()

    mock_args = MagicMock()
    mock_args.feed = None
    mock_args.likes_count = "1-2"
    mock_args.follow_percentage = 0
    mock_args.comment_percentage = 0
    mock_args.interact_percentage = 100
    mock_args.skipped_posts_limit = "10"

    class DummyCaller:
        def __init__(self, args):
            self.args = args

    caller = DummyCaller(mock_args)
    ss = SessionState()
    SessionState.set_active(ss)

    recorded_dead_tag = []

    # Mock HashtagManager
    class MockHashtagManager:
        @classmethod
        def get_instance(cls, username=None):
            return cls()

        def record_hashtag_result(self, tag, posts_found=True, already_liked_exhausted=False):
            if not posts_found:
                recorded_dead_tag.append(tag)

    monkeypatch.setattr("InstaAddict.core.hashtag_manager.HashtagManager", MockHashtagManager)
    monkeypatch.setattr("InstaAddict.core.handle_sources.nav_to_hashtag_or_place", lambda *args, **kwargs: True)
    monkeypatch.setattr("InstaAddict.core.views.UniversalActions.escape_in_app_browser", lambda dev: False)
    monkeypatch.setattr("InstaAddict.core.views.UniversalActions.dismiss_peek_if_open", lambda dev: False)
    monkeypatch.setattr("InstaAddict.core.views.OpenedPostView.is_post_opened", lambda self: True)
    monkeypatch.setattr("InstaAddict.core.views.OpenedPostView._is_post_liked", lambda self: (False, None))
    monkeypatch.setattr("InstaAddict.core.views.PostsViewList._find_likers_container", lambda self: (False, 0))
    monkeypatch.setattr("InstaAddict.core.views.PostsViewList.swipe_to_fit_posts", lambda self, swipe: None)
    monkeypatch.setattr("InstaAddict.core.views.TabBarView.navigateToProfile", lambda self: None)

    # Return unidentifiable post (username = "")
    monkeypatch.setattr(
        "InstaAddict.core.views.PostsViewList._check_if_last_post",
        lambda self, desc, job: (False, "", "", False, False, False),
    )

    micro_stall_calls = []
    monkeypatch.setattr(
        "InstaAddict.core.views.UniversalActions.check_micro_stall",
        lambda dev, context="": micro_stall_calls.append(context),
    )

    try:
        handle_posts(
            caller,
            device=mock_device,
            session_state=ss,
            target="jrtpost",
            current_job="hashtag-posts-recent",
            storage=mock_storage,
            profile_filter=mock_profile_filter,
            on_interaction=mock_on_interaction,
            interaction=mock_interaction,
            is_follow_limit_reached=lambda: False,
            interact_percentage=100,
            scraping_file=None,
        )

        # Circuit breaker should have fired at 5 unidentifiable posts
        assert ss.skip_reasons.get("UNIDENTIFIABLE") == 5
        assert "jrtpost" in recorded_dead_tag
        assert len(micro_stall_calls) == 1
        assert "consecutive_unidentifiable" in micro_stall_calls[0]
    finally:
        SessionState.set_active(None)


def test_handle_posts_grid_exit_detection_breaks_out(monkeypatch):
    """Verify handle_posts detects when screen drops out to thumbnail grid and exits immediately (CO-074)."""
    from InstaAddict.core.handle_sources import handle_posts
    from InstaAddict.core.session_state import SessionState
    from unittest.mock import MagicMock

    mock_device = MagicMock()
    mock_storage = MagicMock()
    mock_profile_filter = MagicMock()
    mock_on_interaction = MagicMock()
    mock_interaction = MagicMock()
    mock_args = MagicMock()
    mock_args.feed = None
    mock_args.skipped_posts_limit = "5"

    class DummyCaller:
        def __init__(self, args):
            self.args = args

    caller = DummyCaller(mock_args)
    ss = SessionState()
    SessionState.set_active(ss)

    monkeypatch.setattr("InstaAddict.core.handle_sources.nav_to_hashtag_or_place", lambda *args, **kwargs: True)
    monkeypatch.setattr("InstaAddict.core.views.UniversalActions.escape_in_app_browser", lambda dev: False)
    monkeypatch.setattr("InstaAddict.core.views.UniversalActions.dismiss_peek_if_open", lambda dev: False)
    monkeypatch.setattr("InstaAddict.core.views.TabBarView.navigateToProfile", lambda self: None)

    # Once entered handle_posts, is_post_opened returns False (simulating grid drop)
    monkeypatch.setattr("InstaAddict.core.views.OpenedPostView.is_post_opened", lambda self: False)

    micro_stall_calls = []
    monkeypatch.setattr(
        "InstaAddict.core.views.UniversalActions.check_micro_stall",
        lambda dev, context="": micro_stall_calls.append(context),
    )

    try:
        handle_posts(
            caller,
            device=mock_device,
            session_state=ss,
            target="jrtpost",
            current_job="hashtag-posts-recent",
            storage=mock_storage,
            profile_filter=mock_profile_filter,
            on_interaction=mock_on_interaction,
            interaction=mock_interaction,
            is_follow_limit_reached=lambda: False,
            interact_percentage=100,
            scraping_file=None,
        )

        assert len(micro_stall_calls) == 1
        assert "grid_trap_exit" in micro_stall_calls[0]
    finally:
        SessionState.set_active(None)


def test_device_facade_get_info_adb_fallback(monkeypatch):
    """Verify that DeviceFacade.get_info() recovers via fast ADB inspection on RPC failure."""
    from InstaAddict.core.device_facade import DeviceFacade

    # Create dummy DeviceFacade instance bypassing __init__
    dev = DeviceFacade.__new__(DeviceFacade)
    dev.device_id = "emulator-5554"
    dev.deviceV2 = MagicMock()
    # Simulate RPC failure on deviceV2.info
    type(dev.deviceV2).info = PropertyMock(side_effect=Exception("GatewayError: gateway error"))
    dev.deviceV2.reset_uiautomator = MagicMock()

    fallback_info = {
        "productName": "Pixel_10_Pro",
        "sdkInt": 37,
        "displayWidth": 1080,
        "displayHeight": 2424,
        "displaySizeDpX": 411,
        "displaySizeDpY": 923,
        "screenOn": True,
    }
    monkeypatch.setattr(dev, "_get_info_via_adb", lambda: fallback_info)

    res = dev.get_info(fallback_to_adb=True)
    assert res["productName"] == "Pixel_10_Pro"
    assert res["sdkInt"] == 37
    assert res["displayWidth"] == 1080
    assert res["screenOn"] is True


def test_get_device_info_single_call_and_safe_defaults():
    """Verify get_device_info queries get_info() exactly once and tolerates partial/null fields."""
    from InstaAddict.core.device_facade import get_device_info

    mock_dev = MagicMock()
    mock_dev.get_info.return_value = {
        "productName": "sdk_gphone",
        "sdkInt": 37,
        "displayWidth": 1080,
        "displayHeight": 1920,
        "displaySizeDpX": 411,
        "displaySizeDpY": 731,
    }
    mock_dev.deviceV2.serial = "emulator-5554"

    get_device_info(mock_dev)
    assert mock_dev.get_info.call_count == 1


def test_device_facade_is_screen_on_fallback(monkeypatch):
    """Verify is_screen_on checks RPC first, falling back to ADB power check."""
    from InstaAddict.core.device_facade import DeviceFacade

    dev = DeviceFacade.__new__(DeviceFacade)
    dev.device_id = "emulator-5554"
    dev.deviceV2 = MagicMock()

    # RPC succeeds
    type(dev.deviceV2).info = PropertyMock(return_value={"screenOn": True})
    assert dev.is_screen_on() is True

    # RPC raises exception, falls back to _get_info_via_adb
    type(dev.deviceV2).info = PropertyMock(side_effect=Exception("RPC timeout"))
    monkeypatch.setattr(dev, "_get_info_via_adb", lambda: {"screenOn": False})
    assert dev.is_screen_on() is False


def test_update_available_tolerates_404_and_offline(monkeypatch):
    """Verify update_available gracefully returns (False, 'source') on 404 without error logging."""
    from InstaAddict.core.utils import update_available, check_if_updated

    # 1. Test 404 response
    mock_resp_404 = MagicMock()
    mock_resp_404.status_code = 404
    mock_resp_404.ok = False
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp_404)

    is_update, ver = update_available()
    assert is_update is False
    assert ver == "source"

    # 2. Test check_if_updated with logger spy
    with patch("InstaAddict.core.utils.logger.error") as mock_err:
        check_if_updated(crash=False)
        # Must NOT log ERROR for 404/source installation
        assert mock_err.called is False


def test_dogfood_optimizer_analyzes_rpc_adb_and_watchdog_errors(tmp_path):
    """Verify DogfoodOptimizer._analyze_error_log parses RPC disconnects, ADB timeouts, and Watchdog tiers."""
    from InstaAddict.core.dogfood import DogfoodOptimizer

    log_file = tmp_path / "test_user_error_trace.log"
    log_content = """
[09/25 00:00:01]  WARNING | Detected disconnected/crashed UiAutomation service (Read timed out.)
[09/25 00:00:02]    DEBUG | [WATCHDOG] ADB command ['adb', 'shell', 'input', 'keyevent', '4'] error: Command timed out after 5.0 seconds
[09/25 00:00:03]  WARNING | [WATCHDOG] Tier 1 Triggered: Inactivity (90.2s >= 90.0s). Dispatching WAKEUP
[09/25 00:00:04]  WARNING | [WATCHDOG] Tier 2 Triggered: Bot frozen (105.5s >= 105.0s). Flagging task skip
[09/25 00:00:05]    ERROR | [WATCHDOG] Tier 3 Triggered: Hang (150.0s >= 150.0s). Force-stopping
[09/25 00:00:06]  WARNING | Zero-displacement hashtag grid trap detected on target #dogs
"""
    log_file.write_text(log_content.strip(), encoding="utf-8")

    opt = DogfoodOptimizer("test_user")
    opt.error_log_path = str(log_file)

    diag = opt._analyze_error_log()
    assert diag["rpc_disconnects"] == 1
    assert diag["adb_timeouts"] == 1
    assert diag["watchdog_tier1_triggers"] == 1
    assert diag["watchdog_tier2_triggers"] == 1
    assert diag["watchdog_tier3_triggers"] == 1
    assert diag["grid_traps"] == 1


def test_dogfood_optimizer_recommendations_for_transport_and_watchdog(tmp_path):
    """Verify DogfoodOptimizer.analyze() synthesizes Device Transport and Watchdog Stability recommendations."""
    from InstaAddict.core.dogfood import DogfoodOptimizer

    opt = DogfoodOptimizer("test_user")
    opt.sessions_path = str(tmp_path / "sessions.json")
    opt.error_log_path = str(tmp_path / "error.log")
    opt.suggestions_json_path = str(tmp_path / "sugg.json")
    opt.suggestions_md_path = str(tmp_path / "sugg.md")

    # Inject error diagnostics directly
    mock_diag = {
        "total_warnings": 5,
        "total_errors": 1,
        "total_criticals": 0,
        "quota_429_errors": 0,
        "ui_not_found_errors": 0,
        "fatal_crashes": 0,
        "subscreen_escapes": 0,
        "subscreen_escape_failures": 0,
        "restart_profile_failures": 0,
        "rpc_disconnects": 2,
        "adb_timeouts": 1,
        "watchdog_tier1_triggers": 3,
        "watchdog_tier2_triggers": 1,
        "watchdog_tier3_triggers": 0,
        "grid_traps": 1,
    }
    opt._analyze_error_log = lambda: mock_diag
    opt._load_sessions = lambda: [{"total_interactions": 20, "successful_interactions": 15, "total_likes": 10, "total_followed": 5}]

    report = opt.analyze()
    categories = [r["category"] for r in report["recommendations"]]
    assert "Device & Transport Health" in categories
    assert "Bot Watchdog Stability" in categories
    assert "Source & Grid Traps" in categories


def test_performance_tracker_device_health():
    """Verify PerformanceTracker records and computes device RPC health metrics."""
    from InstaAddict.core.telemetry import PerformanceTracker

    PerformanceTracker.reset_instance()
    tracker = PerformanceTracker.get_instance()

    tracker.record_device_health(connected=True, latency_ms=12.5)
    tracker.record_device_health(connected=True, latency_ms=17.5)
    tracker.record_device_health(connected=False, latency_ms=0.0)

    health = tracker.get_device_health()
    assert health["total_samples"] == 3
    assert health["connected_pct"] == 66.7
    assert health["avg_latency_ms"] == 15.0
    assert health["is_healthy"] is False  # < 90%

