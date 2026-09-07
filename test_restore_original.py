import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import restore_original as restore


class RestoreTests(unittest.TestCase):
    def test_restore_is_atomic_preserves_history_and_resumes(self):
        api = Mock()
        api.repo_info.return_value = SimpleNamespace(
            sha=restore.EXPECTED_PARENT,
            siblings=[SimpleNamespace(rfilename=name) for name in (*restore.FILES, *restore.REMOVE)],
        )
        api.create_commit.return_value.oid = "restored-sha"
        api.restart_space.return_value.stage = "BUILDING"
        with tempfile.TemporaryDirectory() as tmp:
            for name in restore.FILES:
                (Path(tmp) / name).write_text("fixture", encoding="utf-8")
            self.assertEqual(restore.restore(api, Path(tmp)), "restored-sha")
        args = api.create_commit.call_args.kwargs
        self.assertEqual(args["parent_commit"], restore.EXPECTED_PARENT)
        self.assertEqual(len(args["operations"]), 7)
        self.assertEqual([op.path_in_repo for op in args["operations"][4:]], list(restore.REMOVE))
        self.assertEqual([call[0] for call in api.method_calls], ["repo_info", "create_commit", "restart_space"])

    def test_changed_remote_is_not_overwritten(self):
        api = Mock()
        api.repo_info.return_value.sha = "new-user-edit"
        with self.assertRaisesRegex(RuntimeError, "changed since backup"):
            restore.restore(api, Path("unused"))
        api.create_commit.assert_not_called()
        api.restart_space.assert_not_called()

    def test_live_health_requires_running_original(self):
        api = Mock()
        api.repo_info.return_value.sha = "restored-sha"
        api.get_space_runtime.return_value.stage = "RUNNING"
        with patch.object(restore, "read_health", return_value={"status": "ok", "available": 1, "total": 1}):
            restore.wait_ready(api, "restored-sha", timeout=1)

    def test_patched_health_is_rejected(self):
        api = Mock()
        api.repo_info.return_value.sha = "restored-sha"
        api.get_space_runtime.return_value.stage = "RUNNING"
        with patch.object(restore, "read_health", return_value={"status": "ok", "build_version": "v2.9.3+overdraft.x"}), patch.object(restore.time, "monotonic", side_effect=[0, 0, 2]), patch.object(restore.time, "sleep"):
            with self.assertRaises(TimeoutError):
                restore.wait_ready(api, "restored-sha", timeout=1)


if __name__ == "__main__":
    unittest.main()
