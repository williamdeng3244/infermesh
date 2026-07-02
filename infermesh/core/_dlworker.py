# SPDX-License-Identifier: Apache-2.0
"""Subprocess download worker — one repo per process so the parent can pause or
cancel a download by killing the process (a daemon thread running
``snapshot_download`` can't be stopped). ``snapshot_download`` resumes partial
files automatically, so a killed-then-restarted download continues where it left
off.

Run as:  python -m infermesh.core._dlworker <repo_id> <dest> <source> [endpoint]
"""

import sys


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: _dlworker <repo_id> <dest> <source> [endpoint]", file=sys.stderr)
        return 2
    repo_id, dest, source = sys.argv[1], sys.argv[2], sys.argv[3]
    endpoint = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None
    if source == "modelscope":
        import modelscope
        modelscope.snapshot_download(repo_id, local_dir=dest)
    else:
        import huggingface_hub
        kw = {"endpoint": endpoint} if endpoint else {}
        huggingface_hub.snapshot_download(repo_id, local_dir=dest, **kw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
