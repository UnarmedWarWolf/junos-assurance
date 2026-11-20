#!/bin/bash
# Double-click to launch on macOS. First run creates a virtual environment and installs dependencies.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv || { echo "Python 3 is required (https://www.python.org/downloads/)"; read; exit 1; }
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt || { echo "Dependency install failed"; read; exit 1; }
fi
./.venv/bin/python main.py
