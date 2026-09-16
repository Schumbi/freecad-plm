#!/usr/bin/env python3
"""Run addon/server HTTP contracts on Windows and Linux in the server venv."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from run_tests import ROOT, ensure_environment, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addon", type=Path, default=Path(os.environ.get(
        "PLM_ADDON_SOURCE", ROOT.parent / "freecad-plm-addon")))
    args = parser.parse_args()
    addon = args.addon.resolve()
    if not (addon / "freecad_plm_addon" / "api_client.py").is_file():
        parser.error(f"Addon checkout missing: {addon}; use --addon PATH")
    if sys.version_info < (3, 10):
        parser.error("Python 3.10 or newer is required")
    os.environ["PLM_ADDON_SOURCE"] = str(addon)
    python = ensure_environment()
    (ROOT / "staticfiles").mkdir(exist_ok=True)
    run((python, "manage.py", "test", "contracts.addon_server", "--parallel", "1", "--noinput"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
