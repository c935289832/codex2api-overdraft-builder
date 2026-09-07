import json
import os
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi


SPACE = "axm0121/SelfCodex2api"
EXPECTED_PARENT = "0c047bdc556405df53d2fc8131ae7ffbdc0b0ebf"
FILES = (".gitattributes", "Dockerfile", "README.md", "entrypoint.sh")
REMOVE = ("codex2api", "BUILD_INFO.json", "UPSTREAM_VERSION")


def restore(api, source):
    info = api.repo_info(repo_id=SPACE, repo_type="space")
    if info.sha != EXPECTED_PARENT:
        raise RuntimeError(f"Space changed since backup: {info.sha}")
    operations = [
        CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(source / name))
        for name in FILES
    ]
    present = {item.rfilename for item in info.siblings}
    operations.extend(
        CommitOperationDelete(path_in_repo=name) for name in REMOVE if name in present
    )
    # One normal commit retains history and touches no database, variable, or secret.
    commit = api.create_commit(
        repo_id=SPACE,
        repo_type="space",
        parent_commit=EXPECTED_PARENT,
        operations=operations,
        commit_message="Restore original upstream-image runtime from 6080143",
    )
    print(f"RESTORED_COMMIT: {commit.oid}", flush=True)
    runtime = api.restart_space(repo_id=SPACE)
    print(f"RESUME: {runtime.stage}", flush=True)
    return commit.oid


def read_health():
    with urlopen("https://axm0121-selfcodex2api.hf.space/health", timeout=20) as response:
        return json.load(response)


def wait_ready(api, expected_sha, timeout=900):
    deadline = time.monotonic() + timeout
    last = "unknown"
    while time.monotonic() < deadline:
        info = api.repo_info(repo_id=SPACE, repo_type="space")
        if info.sha != expected_sha:
            raise RuntimeError(f"Space changed during verification: {info.sha}")
        runtime = api.get_space_runtime(SPACE)
        last = str(runtime.stage)
        if runtime.stage in {"RUNNING", "SLEEPING"}:
            try:
                health = read_health()
            except (URLError, TimeoutError, ValueError):
                last += " health pending"
            else:
                version = health.get("build_version", "")
                # Upstream /health does not expose build_version. The patched
                # deployment adds it; never require that customization here.
                if (runtime.stage == "RUNNING" and health.get("status") == "ok"
                        and "overdraft" not in version):
                    print("HF_ORIGINAL_READY: RUNNING health=ok original_files=verified", flush=True)
                    print("HEALTH: " + json.dumps(health, sort_keys=True), flush=True)
                    return
                last += f" health={health.get('status')} version={version}"
        print(f"HF_WAIT: {last}", flush=True)
        time.sleep(10)
    raise TimeoutError(f"Original runtime not ready: {last}")


def main():
    api = HfApi(token=os.environ["HF_TOKEN"])
    sha = restore(api, Path(__file__).parent / "hf-original")
    wait_ready(api, sha)


if __name__ == "__main__":
    main()
