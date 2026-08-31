import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
            api.repo_info.return_value = SimpleNamespace(
                siblings=[SimpleNamespace(lfs=SimpleNamespace(sha256="current-oid"))]
            )
            current = SimpleNamespace(oid="current-oid", size=12)
            orphan1 = SimpleNamespace(oid="old-oid-1", size=100)
            orphan2 = SimpleNamespace(oid="old-oid-2", size=200)
            api.list_lfs_files.return_value = [current, orphan1, orphan2]
            calls = Mock()
            calls.attach_mock(api.super_squash_history, "squash")
            calls.attach_mock(api.permanently_delete_lfs_files, "delete")
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
            api.permanently_delete_lfs_files.assert_called_once_with(
                repo_id="owner/space",
                repo_type="space",
                lfs_files=[orphan1, orphan2],
                rewrite_history=False,
            )
            self.assertEqual(calls.mock_calls[0][0], "squash")
            self.assertEqual(calls.mock_calls[1][0], "delete")
            self.assertEqual(calls.mock_calls[2][0], "commit")


if __name__ == "__main__":
    unittest.main()
