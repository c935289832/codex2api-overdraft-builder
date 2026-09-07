import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from huggingface_hub.hf_api import LFSFileInfo

import deploy_hf


class DeployHfTests(unittest.TestCase):
    @staticmethod
    def lfs_file(file_oid, oid, size):
        return LFSFileInfo(fileOid=file_oid, oid=oid, filename="codex2api", size=size,
                           pushedAt="2026-09-07T00:00:00Z", ref="refs/heads/main")

    def test_compacts_history_before_uploading_new_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            (source_dir / "codex2api").write_bytes(b"linux-binary")
            (source_dir / "UPSTREAM_VERSION").write_text("upstream-sha\n", encoding="utf-8")
            (source_dir / "BUILD_INFO.json").write_text(
                json.dumps({"upstream_short_sha": "aac568fb7bb0"}), encoding="utf-8"
            )

            api = Mock()
            api.pause_space.return_value.stage = "PAUSED"
            api.create_commit.return_value.oid = "new-commit"
            api.repo_info.return_value = SimpleNamespace(
                siblings=[SimpleNamespace(lfs=SimpleNamespace(sha256="current-oid"))]
            )
            # HF's oid is a different identifier; only file_oid is the SHA-256.
            current = self.lfs_file("current-oid", "internal-current", 12)
            orphan1 = self.lfs_file("old-oid-1", "internal-old-1", 100)
            orphan2 = self.lfs_file("old-oid-2", "internal-old-2", 200)
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
                api.pause_space.return_value.stage = "PAUSED"
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

    def test_current_lfs_blob_is_never_pruned(self) -> None:
        api = Mock()
        api.repo_info.return_value = SimpleNamespace(siblings=[SimpleNamespace(lfs=SimpleNamespace(sha256="active-sha"))])
        api.list_lfs_files.return_value = [self.lfs_file("active-sha", "different-internal-id", 100)]
        deploy_hf.compact_and_prune_history(api, "owner/space", "next")
        api.permanently_delete_lfs_files.assert_not_called()

    def test_waits_for_async_pause(self) -> None:
        api = Mock()
        api.get_space_runtime.return_value.stage = "PAUSED"
        with patch.object(deploy_hf.time, "sleep") as sleep:
            deploy_hf.wait_until_paused(api, "owner/space", SimpleNamespace(stage="RUNNING"))
        api.get_space_runtime.assert_called_once_with(repo_id="owner/space")
        sleep.assert_called_once_with(2)

    def test_pause_timeout_is_bounded(self) -> None:
        with patch.object(deploy_hf.time, "monotonic", side_effect=[0, 91]):
            with self.assertRaises(TimeoutError):
                deploy_hf.wait_until_paused(Mock(), "owner/space", SimpleNamespace(stage="RUNNING"))


if __name__ == "__main__":
    unittest.main()
