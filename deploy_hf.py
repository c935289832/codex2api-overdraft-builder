import json
import os
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi


def main() -> None:
    repo_id = os.environ["HF_SPACE_ID"]
    source_dir = Path(os.environ.get("DEPLOY_DIR", "dist"))
    paths = {
        "codex2api": source_dir / "codex2api",
        "UPSTREAM_VERSION": source_dir / "UPSTREAM_VERSION",
        "BUILD_INFO.json": source_dir / "BUILD_INFO.json",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise SystemExit(f"missing deployment files: {', '.join(missing)}")

    build_info = json.loads(paths["BUILD_INFO.json"].read_text(encoding="utf-8"))
    commit_message = f"Deploy patched upstream {build_info['upstream_short_sha']}"
    operations = [
        CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(path))
        for name, path in paths.items()
    ]
    api = HfApi()
    api.super_squash_history(
        repo_id=repo_id,
        repo_type="space",
        branch="main",
        commit_message=f"Compact deployment history before {build_info['upstream_short_sha']}",
    )
    print("Compacted Space deployment history")
    result = api.create_commit(
        repo_id=repo_id,
        repo_type="space",
        operations=operations,
        commit_message=commit_message,
    )
    print(result.oid)


if __name__ == "__main__":
    main()
