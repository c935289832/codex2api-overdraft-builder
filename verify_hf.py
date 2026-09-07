import argparse
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_json(url, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urlopen(Request(url, headers=headers), timeout=15) as response:
        return json.load(response)


def wait_for_space(repo_id, build_version, *, timeout=600, interval=10, grace=30):
    started = time.monotonic()
    deadline = started + timeout
    last = "not checked"
    while time.monotonic() < deadline:
        try:
            runtime = get_json(
                f"https://huggingface.co/api/spaces/{repo_id}/runtime",
                os.environ.get("HF_TOKEN"),
            )
        except HTTPError as exc:
            if exc.code in (401, 403, 404):
                raise RuntimeError(f"Space runtime returned HTTP {exc.code}") from None
            last = f"runtime HTTP {exc.code}"
        except (URLError, TimeoutError, ValueError):
            last = "runtime temporarily unavailable"
        else:
            stage = runtime.get("stage", "UNKNOWN")
            last = stage
            if stage in {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"}:
                # HF may briefly report the previous build's state after a commit/restart.
                if time.monotonic() - started >= grace:
                    raise RuntimeError(f"Space {stage}: {runtime.get('errorMessage', '')}")
            elif stage == "RUNNING":
                for domain in runtime.get("domains", []):
                    host = domain.get("domain", "")
                    if not host.endswith(".hf.space") or any(c in host for c in "/:@"):
                        continue
                    try:
                        health = get_json(f"https://{host}/health")
                    except (URLError, TimeoutError, ValueError):
                        last = "RUNNING, health temporarily unavailable"
                        continue
                    if health.get("status") == "ok" and health.get("build_version") == build_version:
                        print(f"HF_READY: RUNNING health=ok build_version={build_version}", flush=True)
                        return
                    last = "RUNNING, health status or build version does not match"
            print(f"HF_WAIT: {last}", flush=True)
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    raise TimeoutError(f"Space not ready after {timeout}s: {last}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-info", default="dist/BUILD_INFO.json")
    args = parser.parse_args()
    info = json.loads(Path(args.build_info).read_text(encoding="utf-8"))
    wait_for_space(os.environ["HF_SPACE_ID"], info["build_version"])


if __name__ == "__main__":
    main()
