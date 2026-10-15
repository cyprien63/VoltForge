#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
VENV_DIR="${VENV_DIR:-.venv}"
if [ ! -x "$VENV_DIR/bin/python" ]; then
    "${PYTHON:-python3}" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
exec "$VENV_DIR/bin/python" -m PyInstaller --noconfirm --clean --windowed --name VoltForge --add-data "assets/icons:assets/icons" main.py
