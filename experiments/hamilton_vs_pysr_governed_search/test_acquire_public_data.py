import unittest

from .acquire_public_data import source_url


class AcquirePublicDataTests(unittest.TestCase):
    def test_uses_pinned_revision_and_dataset_name(self) -> None:
        url = source_url(
            {"source_dataset": "feynman_I_14_4", "source_revision": "abc123"}
        )
        self.assertEqual(
            url,
            "https://media.githubusercontent.com/media/EpistasisLab/pmlb/abc123/"
            "datasets/feynman_I_14_4/feynman_I_14_4.tsv.gz",
        )
        self.assertNotIn("latest", url)


if __name__ == "__main__":
    unittest.main()
