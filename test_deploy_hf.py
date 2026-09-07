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
            calls.attach_mock(api.pause_space, "pause")
            calls.attach_mock(api.super_squash_history, "squash")
            calls.attach_mock(api.permanently_delete_lfs_files, "delete")
            calls.attach_mock(api.create_commit, "commit")
            calls.attach_mock(api.restart_space, "restart")

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
            self.assertEqual([call[0] for call in calls.mock_calls], ["pause", "squash", "delete", "commit", "restart"])
            api.pause_space.assert_called_once_with(repo_id="owner/space")
            api.restart_space.assert_called_once_with(repo_id="owner/space", factory_reboot=True)

    def test_resumes_space_after_upload_or_cleanup_error(self) -> None:
        for failed_step in ("cleanup", "upload"):
            with self.subTest(failed_step=failed_step), tempfile.TemporaryDirectory() as temp_dir:
                source = Path(temp_dir)
                (source / "codex2api").write_bytes(b"binary")
                (source / "UPSTREAM_VERSION").write_text("upstream-sha")
                (source / "BUILD_INFO.json").write_text(json.dumps({"upstream_short_sha": "test"}))
                api = Mock()
                if failed_step == "upload":
                    api.create_commit.side_effect = RuntimeError("upload failed")
                with (
                    patch.object(deploy_hf, "HfApi", return_value=api),
                    patch.object(deploy_hf, "compact_and_prune_history") as compact,
                    patch.dict(os.environ, {"HF_SPACE_ID": "owner/space", "DEPLOY_DIR": str(source)}, clear=True),
                ):
                    if failed_step == "cleanup":
                        compact.side_effect = RuntimeError("cleanup failed")
                    with self.assertRaisesRegex(RuntimeError, "failed"):
                        deploy_hf.main()
                api.restart_space.assert_called_once_with(repo_id="owner/space", factory_reboot=True)
                if failed_step == "cleanup":
                    api.create_commit.assert_not_called()

    def test_does_not_mutate_history_if_pause_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            for name in ("codex2api", "UPSTREAM_VERSION"):
                (source / name).write_text("fixture")
            (source / "BUILD_INFO.json").write_text(json.dumps({"upstream_short_sha": "test"}))
            api = Mock()
            api.pause_space.side_effect = RuntimeError("pause failed")
            with (
                patch.object(deploy_hf, "HfApi", return_value=api),
                patch.dict(os.environ, {"HF_SPACE_ID": "owner/space", "DEPLOY_DIR": str(source)}, clear=True),
            ):
                with self.assertRaisesRegex(RuntimeError, "pause failed"):
                    deploy_hf.main()
            api.super_squash_history.assert_not_called()
            api.create_commit.assert_not_called()
            api.restart_space.assert_not_called()


if __name__ == "__main__":
    unittest.main()
