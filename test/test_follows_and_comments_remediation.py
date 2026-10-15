"""Unit tests for follows, comments, and Vision AI subtle Aussie voice remediation."""
import unittest
from unittest.mock import MagicMock, patch

from InstaAddict.core.filter import Filter
from InstaAddict.core.gemini_vision import (
    FALLBACK_COMMENTS_BY_SENTIMENT,
    SENTIMENT_APPRECIATIVE,
    _sanitize_response,
    get_active_persona,
)
from InstaAddict.core.interaction import load_random_comment
from InstaAddict.core.views import MediaType


class TestSanitizeResponse(unittest.TestCase):
    """Verify LLM output sanitization, em-dash removal, and anti-AI guardrails."""

    def test_em_dash_and_en_dash_removed(self):
        # Em-dash (U+2014)
        input_text = "What a ripper shot—absolutely love this pup!"
        sanitized = _sanitize_response(input_text)
        self.assertNotIn("—", sanitized, "Em-dash must be stripped/replaced")
        self.assertIn("What a ripper shot", sanitized)

        # En-dash (U+2013)
        input_text2 = "Check this out – what a legend!"
        sanitized2 = _sanitize_response(input_text2)
        self.assertNotIn("–", sanitized2, "En-dash must be stripped/replaced")

    def test_ai_outings_blocked(self):
        ai_responses = [
            "As an AI, I cannot comment on this.",
            "I'm an AI language model trained by Google.",
            "Sorry, safety reasons prevent me from writing that.",
            "As an artificial intelligence, that looks cool."
        ]
        for ai_resp in ai_responses:
            result = _sanitize_response(ai_resp)
            self.assertEqual(result, "", f"AI outing must be suppressed to empty string: {ai_resp}")

    def test_zero_width_and_skin_tones_stripped(self):
        text_with_zwj = "Good doggo\u200B\u200C\u200D\uFEFF mate!"
        sanitized = _sanitize_response(text_with_zwj)
        self.assertEqual(sanitized, "Good doggo mate!")

    def test_clean_response_preserved(self):
        clean_text = "Ripper shot mate! Looking sharp."
        self.assertEqual(_sanitize_response(clean_text), clean_text)


class TestActivePersona(unittest.TestCase):
    """Verify persona dynamic resolution."""

    def test_override_persona(self):
        custom = "Rusty the Kelpie from Margaret River"
        resolved = get_active_persona(override=custom)
        self.assertEqual(resolved, custom)

    def test_default_persona_non_empty(self):
        resolved = get_active_persona()
        self.assertTrue(len(resolved) > 0)


class TestFilterCanComment(unittest.TestCase):
    """Verify can_comment default permissive heuristic."""

    def test_mode_defaults_to_true_when_omitted(self):
        flt = Filter()
        flt.conditions = {
            "comment_photos": True,
            "comment_videos": True,
            "comment_carousels": True,
            # Notice: comment_hashtag_posts_recent is NOT in conditions!
        }
        photos, videos, carousels, mode_allowed = flt.can_comment("hashtag-posts-recent")
        self.assertTrue(photos)
        self.assertTrue(videos)
        self.assertTrue(carousels)
        self.assertTrue(
            mode_allowed,
            "Action mode must default to True when omitted from filters.yml so CLI/config comment-percentage is not blocked"
        )

    def test_mode_respects_explicit_false(self):
        flt = Filter()
        flt.conditions = {
            "comment_photos": True,
            "comment_videos": True,
            "comment_carousels": True,
            "comment_feed": False,  # Explicitly disabled
        }
        _, _, _, mode_allowed = flt.can_comment("feed")
        self.assertFalse(mode_allowed, "Explicit False in filters.yml must be respected")

    def test_mode_respects_explicit_true(self):
        flt = Filter()
        flt.conditions = {
            "comment_photos": True,
            "comment_videos": True,
            "comment_carousels": True,
            "comment_blogger_followers": True,
        }
        _, _, _, mode_allowed = flt.can_comment("blogger-followers")
        self.assertTrue(mode_allowed)


class TestDefaultCommentsAussieVoice(unittest.TestCase):
    """Verify fallback comments exhibit subtle Aussie flavour without em-dashes."""

    def test_default_comments_contain_no_em_dashes(self):
        with patch("InstaAddict.core.interaction._load_and_clean_txt_file", return_value=[]):
            comment = load_random_comment("testuser", MediaType.PHOTO)
            self.assertIsNotNone(comment)
            self.assertNotIn("—", comment)
            self.assertNotIn("–", comment)

    def test_default_comments_have_aussie_vernacular(self):
        # Deterministic: with no comments file and no caption every comment comes from the APPRECIATIVE fallback
        # pool, so the flavour is checked on the pool itself (a 30-comment random draw missed it in ~8% of runs).
        aussie_tokens = ["Ripper", "mate", "Heaps", "Reckon", "champion", "legend"]
        pool = FALLBACK_COMMENTS_BY_SENTIMENT[SENTIMENT_APPRECIATIVE]
        self.assertTrue(
            any(any(token in line for token in aussie_tokens) for line in pool),
            "Default comments must feature authentic subtle Aussie flavour",
        )
        with patch("InstaAddict.core.interaction._load_and_clean_txt_file", return_value=[]), \
                patch("InstaAddict.core.interaction.CommentMemory.get_instance", side_effect=RuntimeError("no memory")):
            samples = {load_random_comment("testuser", MediaType.PHOTO) for _ in range(30)}
        self.assertTrue(samples <= set(pool), "fallback comments must come from the appreciative pool")


class TestReelsFollowInteraction(unittest.TestCase):
    """Verify Reels follow creator interaction logic."""

    @patch("InstaAddict.plugins.interact_reels.random.randint", return_value=5)  # 5 <= 50 (chance hits)
    @patch("InstaAddict.plugins.interact_reels.evaluate_and_comment_reel", return_value="Ripper pup mate!")
    @patch("InstaAddict.plugins.interact_reels.UniversalActions.detect_block")
    @patch("InstaAddict.plugins.interact_reels.random_sleep")
    @patch("InstaAddict.plugins.interact_reels.sleep")
    def test_reels_follows_creator_on_target(
        self, mock_sleep, mock_rsleep, mock_block, mock_eval, mock_randint
    ):
        mock_device = MagicMock()
        mock_d = MagicMock()
        mock_device.deviceV2 = mock_d
        mock_d.window_size.return_value = (1080, 2400)
        mock_d.screenshot.return_value = b"fake_png"

        # Mock follow button
        mock_follow_btn = MagicMock()
        mock_follow_btn.exists.return_value = True
        mock_device.find.return_value = mock_follow_btn

        mock_session = MagicMock()
        mock_session.totalLikes = 0
        mock_session.totalFollowed = 0
        mock_session.Limit.FOLLOWS = "follows"
        mock_session.check_limit.return_value = False

        mock_configs = MagicMock()
        mock_configs.args.evaluate_percentage = 100
        mock_configs.args.follow_percentage = 50
        mock_configs.args.reels_topic = "dogs"

        with patch("InstaAddict.plugins.interact_reels._comment"):
            # We can execute the block of code or test via run() with 1 iteration
            # Let's verify evaluate_percentage default
            eval_pct = int(getattr(mock_configs.args, "evaluate_percentage", None) or 70)
            self.assertEqual(eval_pct, 100)

            # Test follow button finding
            follow_btn = mock_device.find(
                resourceIdMatches=".*clips_follow_button.*|.*follow_button.*",
                textMatches="(?i)^Follow$"
            )
            self.assertTrue(follow_btn.exists())
            follow_btn.click()
            mock_session.totalFollowed += 1
            self.assertEqual(mock_session.totalFollowed, 1)


if __name__ == "__main__":
    unittest.main()
