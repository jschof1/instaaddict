import re
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import configargparse

from InstaAddict.core.views import FollowStatus, ProfileView
from InstaAddict.core.interaction import _follow
from InstaAddict.plugins.core_arguments import CoreArguments


class Node:
    def __init__(self, text="", resource="", clickable=False, description=""):
        self.properties = dict(
            text=text, resourceId=resource, clickable=clickable,
            contentDescription=description, className="android.widget.TextView",
        )

    def exists(self, *args):
        return True

    def get_text(self):
        return self.properties["text"]

    def get_property(self, key):
        return self.properties.get(key)

    def click(self):
        self.properties["text"] = "Following"


class Device:
    def __init__(self, *nodes):
        self.nodes = nodes

    def find(self, **selector):
        names = {"description": "contentDescription"}
        for node in self.nodes:
            matches = True
            for key, value in selector.items():
                regex = key.endswith("Matches")
                name = key[:-7] if regex else key
                actual = node.properties.get(names.get(name, name))
                if not (re.fullmatch(value, actual or "") if regex else actual == value):
                    matches = False
                    break
            if matches:
                return node
        return SimpleNamespace(exists=lambda *args: False)


class TestProfileFollowButton(unittest.TestCase):
    def lookup(self, *nodes):
        return ProfileView.getFollowButton(SimpleNamespace(device=Device(*nodes)))

    def test_instagram_451_count_label_is_not_the_follow_action(self):
        count = Node("following", "com.instagram.android:id/profile_header_familiar_following_label")
        action = Node("Follow", "com.instagram.android:id/profile_header_follow_button", True,
                      "Follow London Roofing Ltd")
        button, status = self.lookup(count, action)
        self.assertIs(button, action)
        self.assertEqual(status, FollowStatus.FOLLOW)

    def test_all_action_states_and_clickable_fallback(self):
        for label, expected in (("Follow", FollowStatus.FOLLOW),
                                ("Follow back", FollowStatus.FOLLOW_BACK),
                                ("Following", FollowStatus.FOLLOWING),
                                ("Requested", FollowStatus.FOLLOWING)):
            with self.subTest(label=label):
                action = Node(label, clickable=True)
                self.assertEqual(self.lookup(Node("following"), action), (action, expected))

    def test_description_only_and_business_name_containing_following(self):
        action = Node(clickable=True, description="Follow Following Seas Plumbing")
        self.assertEqual(self.lookup(action), (action, FollowStatus.FOLLOW))

    def test_count_labels_and_ambiguous_containers_are_not_actions(self):
        for node in (Node("following"), Node("followers", clickable=True),
                     Node("", "com.instagram.android:id/profile_header_actions_top_row", True),
                     Node("Message", "com.instagram.android:id/profile_header_follow_button", True)):
            with self.subTest(properties=node.properties):
                self.assertEqual(self.lookup(node), (None, FollowStatus.NONE))


class TestBlockDetectionOption(unittest.TestCase):
    def parser(self):
        parser = configargparse.ArgumentParser()
        argument = next(a for a in CoreArguments().arguments
                        if a["arg"] == "--disable-block-detection")
        parser.add_argument(argument["arg"], action=argument["action"])
        return parser

    def test_detection_enabled_by_default_and_false_in_config(self):
        self.assertFalse(self.parser().parse_args([]).disable_block_detection)
        self.assertFalse(self.parser().parse_args([], config_file_contents=
                         "disable-block-detection: false").disable_block_detection)

    def test_explicit_disable_flag_and_true_config(self):
        self.assertTrue(self.parser().parse_args(["--disable-block-detection"]).disable_block_detection)
        self.assertTrue(self.parser().parse_args([], config_file_contents=
                        "disable-block-detection: true").disable_block_detection)


class TestFollowAction(unittest.TestCase):
    @patch("InstaAddict.core.interaction.UniversalActions")
    @patch("InstaAddict.core.interaction.ResourceID", SimpleNamespace(COORDINATOR_ROOT_LAYOUT="coordinator"))
    def test_follow_ignores_count_and_verifies_real_button_change(self, actions):
        action = Node("Follow", "com.instagram.android:id/profile_header_follow_button", True)
        device = Device(Node("following"), action)
        session = MagicMock()
        session.check_limit.return_value = False
        self.assertTrue(_follow(device, "trade_business", 100, None, session, 0))
        self.assertEqual(action.get_text(), "Following")
        actions.return_value.detect_block.assert_called_once_with(device)

    @patch("InstaAddict.core.interaction.UniversalActions")
    @patch("InstaAddict.core.interaction.ResourceID", SimpleNamespace(COORDINATOR_ROOT_LAYOUT="coordinator"))
    def test_unchanged_button_and_following_count_do_not_prove_success(self, actions):
        action = Node("Follow", clickable=True)
        action.click = MagicMock()
        device = Device(Node("following"), action)
        session = MagicMock()
        session.check_limit.return_value = False
        self.assertFalse(_follow(device, "trade_business", 100, None, session, 0))
        self.assertEqual(action.click.call_count, 3)


if __name__ == "__main__":
    unittest.main()
