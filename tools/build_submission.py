#!/usr/bin/env python3
"""Bundle the submission tarball. Runs on the GitHub Actions runner.

Kaggriculture expects `main.py` at the *archive root* -- not nested in a folder.
Anything else produces an `Error` submission, so the layout is asserted here.
"""

from __future__ import annotations

import argparse
import os
import tarfile

PAYLOAD = ["main.py"]


def build(root, out):
    root = os.path.abspath(root)
    missing = [f for f in PAYLOAD if not os.path.isfile(os.path.join(root, f))]
    if missing:
        raise SystemExit("::error::missing payload files: {}".format(missing))

    if os.path.exists(out):
        os.remove(out)
    with tarfile.open(out, "w:gz") as tar:
        for name in PAYLOAD:
            tar.add(os.path.join(root, name), arcname=name)

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    if "main.py" not in names:
        raise SystemExit("::error::main.py is not at the archive root: {}".format(names))
    size = os.path.getsize(out)
    print("built {} ({} bytes) containing {}".format(out, size, names))
    if size > 100 * 1024 * 1024:
        raise SystemExit("::error::archive exceeds the 100 MiB submission ceiling")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="submission.tar.gz")
    args = ap.parse_args()
    build(args.root, args.out)
