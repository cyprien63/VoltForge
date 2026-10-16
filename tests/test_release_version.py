import unittest
from unittest.mock import patch

from scripts.release_version import release_version


class ReleaseVersionTests(unittest.TestCase):
    @patch("scripts.release_version.git", side_effect=["v0.9.9\nv1.2.9\n", ""])
    def test_increments_patch_of_latest_semver_tag(self, _git):
        self.assertEqual(release_version(), ("v1.2.10", "v1.2.9"))

    @patch("scripts.release_version.git", side_effect=["", ""])
    def test_starts_at_one_zero_zero_without_tags(self, _git):
        self.assertEqual(release_version(), ("v1.0.0", None))

    @patch("scripts.release_version.git", side_effect=["v1.2.3\n", "v1.2.3\n"])
    def test_reuses_release_tag_pointing_at_head(self, _git):
        self.assertEqual(release_version(), ("v1.2.3", "v1.2.3"))


if __name__ == "__main__":
    unittest.main()
