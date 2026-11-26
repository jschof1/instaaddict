"""The visible Instagram 451 carousel fills the screen before its like button."""
import re
import unittest

from InstaAddict.core.resources import ResourceID


class CarouselResourceTests(unittest.TestCase):
    def test_both_carousel_containers_confirm_media_and_carousel_type(self):
        ids = ResourceID("com.instagram.android")
        for name in ("carousel_media_group", "carousel_image_media_group"):
            value = "com.instagram.android:id/" + name
            self.assertIsNotNone(re.fullmatch(ids.CAROUSEL_MEDIA_GROUP, value))
            self.assertIsNotNone(re.fullmatch(ids.MEDIA_CONTAINER, value))
        self.assertIsNone(re.fullmatch(ids.MEDIA_CONTAINER, "com.instagram.android:id/image_button"))


if __name__ == "__main__":
    unittest.main()
