# Codex2API Overdraft Builder

This repository keeps the quota-overdraft change as a patch instead of a
locally produced application snapshot.

The scheduled workflow:

1. resolves `james-6-23/codex2api` `main` to an immutable commit;
2. checks out that commit and applies `codex-overdraft.patch` with three-way
   fallback;
3. builds the current upstream frontend, runs the focused Go tests, and builds
   the Linux amd64 service;
4. uploads the binary together with `UPSTREAM_VERSION` and `BUILD_INFO.json` to
   the Hugging Face Space.

If an upstream change conflicts with the patch, the workflow stops before
publishing. The Space therefore keeps the last tested version.

Required repository secret:

- `HF_TOKEN`: write access to the target Space.

The workflow can be run manually and also checks upstream every six hours.
