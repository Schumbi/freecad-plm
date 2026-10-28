#!/usr/bin/env python3
"""Push the current release and deploy its images to the PLM server."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REMOTE_SCRIPT = Path(__file__).with_name("deploy-remote.sh")


def git(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        text=True, stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="FreeCAD-PLM pushen und deployen")
    parser.add_argument("--build-timeout-minutes", type=int, default=60,
                        help="Wartezeit auf die Images (Standard: 60 Minuten)")
    args = parser.parse_args()
    if args.build_timeout_minutes < 1:
        parser.error("--build-timeout-minutes muss mindestens 1 sein")
    try:
        branch = git("branch", "--show-current", capture=True)
        if branch not in ("main", "master"):
            raise ValueError("Bitte main oder master auschecken.")
        if git("status", "--porcelain", capture=True):
            raise ValueError("Arbeitsverzeichnis ist nicht sauber; Änderungen zuerst committen.")
        sha = git("rev-parse", "HEAD", capture=True)
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Commit konnte nicht ermittelt werden.")
        remote_script = REMOTE_SCRIPT.read_bytes().replace(b"\r\n", b"\n")
        print(f"Push von {branch} ({sha}) nach origin", flush=True)
        git("push", "origin", f"{branch}:{branch}")
        print("Warte auf Images und starte das Deployment.", flush=True)
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "jellyfin.schumbi.de",
             f"bash -s -- {sha} {args.build_timeout_minutes}"],
            input=remote_script, check=True,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Deployment abgebrochen: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
