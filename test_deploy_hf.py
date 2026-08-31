import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import deploy_hf


class DeployHfTests(unittest.TestCase):
    def test_compacts_history_before_uploading_new_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            (source_dir / "codex2api").write_bytes(b"linux-binary")
            (source_dir / "UPSTREAM_VERSION").write_text("upstream-sha\n", encoding="utf-8")
            (source_dir / "BUILD_INFO.json").write_text(
                json.dumps({"upstream_short_sha": "aac568fb7bb0"}), encoding="utf-8"
            )

            api = Mock()
            api.create_commit.return_value.oid = "new-commit"
            calls = Mock()
            calls.attach_mock(api.super_squash_history, "squash")
            calls.attach_mock(api.create_commit, "commit")

            with (
                patch.object(deploy_hf, "HfApi", return_value=api),
                patch.dict(
                    os.environ,
                    {"HF_SPACE_ID": "owner/space", "DEPLOY_DIR": str(source_dir)},
                    clear=True,
                ),
            ):
                deploy_hf.main()

            api.super_squash_history.assert_called_once_with(
                repo_id="owner/space",
                repo_type="space",
                branch="main",
                commit_message="Compact deployment history before aac568fb7bb0",
            )
            self.assertEqual(calls.mock_calls[0][0], "squash")
            self.assertEqual(calls.mock_calls[1][0], "commit")


if __name__ == "__main__":
    unittest.main()
