#!/usr/bin/env python3
"""Create/update the local virtualenv and run the Django checks and tests."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV_DIR / f".freecad-plm-requirements-{os.name}.sha256"


def venv_python():
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(command):
    print("+", " ".join(str(value) for value in command), flush=True)
    subprocess.run([str(value) for value in command], cwd=ROOT, check=True)


def requirements_digest():
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ensure_environment():
    python = venv_python()
    if not python.is_file():
        print(f"Erzeuge virtuelle Umgebung: {VENV_DIR}", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)

    digest = requirements_digest()
    installed_digest = STAMP.read_text(encoding="ascii").strip() if STAMP.is_file() else ""
    if installed_digest != digest:
        run((python, "-m", "pip", "install", "--disable-pip-version-check", "-r", REQUIREMENTS))
        STAMP.write_text(digest + "\n", encoding="ascii")
    return python


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 oder neuer ist erforderlich.")
    python = ensure_environment()
    (ROOT / "staticfiles").mkdir(exist_ok=True)
    run((python, "manage.py", "check"))
    parallel = "1" if os.name == "nt" else "auto"
    run((python, "manage.py", "test", "--parallel", parallel))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
