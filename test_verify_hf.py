import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import verify_hf


class VerifySpaceTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.version = "v2.9.3+overdraft.test"
        self.running = {"stage": "RUNNING", "domains": [{"domain": "owner-space.hf.space"}]}
        self.healthy = {"status": "ok", "build_version": self.version}
        self.get = self.enterContext(patch.object(verify_hf, "get_json"))
        self.enterContext(patch.object(verify_hf.time, "monotonic", side_effect=lambda: self.now))
        self.enterContext(patch.object(verify_hf.time, "sleep", side_effect=self.advance))
        self.enterContext(patch.dict("os.environ", {"HF_TOKEN": "test-token"}))

    def advance(self, seconds):
        self.now += seconds

    def wait(self):
        verify_hf.wait_for_space("owner/space", self.version, timeout=4, interval=1, grace=1)

    def test_building_then_running_requires_matching_health(self):
        self.get.side_effect = [{"stage": "BUILDING"}, self.running, self.healthy]
        self.wait()
        self.assertEqual(self.now, 1)
        self.get.assert_any_call("https://huggingface.co/api/spaces/owner/space/runtime", "test-token")
        self.get.assert_any_call("https://owner-space.hf.space/health")

    def test_does_not_accept_previous_build(self):
        self.get.side_effect = [self.running, {"status": "ok", "build_version": "old"}, self.running, self.healthy]
        self.wait()
        self.assertEqual(self.now, 1)

    def test_terminal_build_error_fails(self):
        self.get.return_value = {"stage": "BUILD_ERROR", "errorMessage": "exit 128"}
        with self.assertRaisesRegex(RuntimeError, "BUILD_ERROR: exit 128"):
            self.wait()

    def test_previous_terminal_state_can_transition_during_grace(self):
        self.get.side_effect = [{"stage": "BUILD_ERROR"}, self.running, self.healthy]
        self.wait()

    def test_runtime_error_fails(self):
        self.get.return_value = {"stage": "RUNTIME_ERROR"}
        with self.assertRaisesRegex(RuntimeError, "RUNTIME_ERROR"):
            self.wait()

    def test_build_queue_has_bounded_timeout(self):
        self.get.return_value = {"stage": "BUILDING"}
        with self.assertRaisesRegex(TimeoutError, "not ready after 4s"):
            self.wait()
        self.assertEqual(self.now, 4)

    def test_retry_unhealthy_http_and_json(self):
        self.get.side_effect = [
            self.running, HTTPError("health", 503, "unavailable", {}, None),
            self.running, ValueError("not json"),
            self.running, self.healthy,
        ]
        self.wait()

    def test_http_200_unhealthy_is_not_success(self):
        self.get.side_effect = [self.running, {"status": "unavailable", "build_version": self.version}] * 4
        with self.assertRaises(TimeoutError):
            self.wait()

    def test_auth_failure_does_not_retry(self):
        self.get.side_effect = HTTPError("runtime", 401, "unauthorized", {}, None)
        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            self.wait()
        self.assertEqual(self.get.call_count, 1)

    def test_exit_128_rebuild_is_bounded_and_health_still_required(self):
        failure = {"stage": "BUILD_ERROR", "errorMessage": "Job failed with exit code: 128. Reason: Error"}
        self.get.side_effect = [failure, self.running, self.healthy]
        with patch.object(verify_hf, "rebuild_space") as restart:
            verify_hf.wait_for_space("owner/space", self.version, grace=0, rebuild_on_exit_128=True)
            restart.assert_called_once_with("owner/space")

    def test_repeated_exit_128_fails_after_one_rebuild(self):
        self.get.return_value = {"stage": "BUILD_ERROR", "errorMessage": "Job failed with exit code: 128. Reason: Error"}
        with patch.object(verify_hf, "rebuild_space") as restart:
            with self.assertRaisesRegex(RuntimeError, "exit code: 128"):
                verify_hf.wait_for_space("owner/space", self.version, grace=0, rebuild_on_exit_128=True)
            restart.assert_called_once()

    def test_other_build_error_is_not_rebuilt(self):
        self.get.return_value = {"stage": "BUILD_ERROR", "errorMessage": "Dockerfile syntax error"}
        with patch.object(verify_hf, "rebuild_space") as restart:
            with self.assertRaisesRegex(RuntimeError, "Dockerfile syntax error"):
                verify_hf.wait_for_space("owner/space", self.version, grace=0, rebuild_on_exit_128=True)
            restart.assert_not_called()

    def test_network_failure_retries(self):
        self.get.side_effect = [URLError("offline"), self.running, self.healthy]
        self.wait()

    def test_does_not_probe_untrusted_domain(self):
        self.get.return_value = {"stage": "RUNNING", "domains": [{"domain": "evil.example"}]}
        with self.assertRaises(TimeoutError):
            self.wait()
        self.assertTrue(all("huggingface.co/api/" in c.args[0] for c in self.get.call_args_list))


if __name__ == "__main__":
    unittest.main()
