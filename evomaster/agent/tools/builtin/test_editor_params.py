import json
import unittest

from .editor import EditorToolParams


class EditorToolParamsTests(unittest.TestCase):
    def test_view_accepts_provider_emitted_null_optional_fields(self) -> None:
        params = EditorToolParams.model_validate_json(
            json.dumps(
                {
                    "command": "view",
                    "path": "C:/workspace/file.txt",
                    "file_text": None,
                    "old_str": None,
                    "new_str": None,
                    "insert_line": None,
                    "view_range": None,
                }
            )
        )
        self.assertEqual(params.command, "view")
        self.assertIsNone(params.view_range)


if __name__ == "__main__":
    unittest.main()
