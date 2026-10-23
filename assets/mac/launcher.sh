#!/bin/bash
# Launcher for Infinia Spend Analyzer. First run creates a private Python environment.
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
SUPPORT="$HOME/Library/Application Support/CCSorter"
VENV="$SUPPORT/venv"
LOG="$SUPPORT/install.log"
mkdir -p "$SUPPORT"

alert() { osascript -e "display alert \"Infinia Spend Analyzer\" message \"$1\"" >/dev/null 2>&1; }

if [ ! -x "$VENV/bin/python" ]; then
  # Find a real Python 3 (Finder-launched apps don't see Homebrew on PATH).
  PY=""
  for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
    [ -x "$c" ] && PY="$c" && break
  done
  # /usr/bin/python3 is only a placeholder until Apple's developer tools are installed.
  if [ -z "$PY" ] && xcode-select -p >/dev/null 2>&1 && [ -x /usr/bin/python3 ]; then
    PY=/usr/bin/python3
  fi
  if [ -z "$PY" ]; then
    alert "Python 3 is not installed. Open Terminal, run: xcode-select --install   (or install Python from python.org), wait for it to finish, then open this app again."
    exit 1
  fi

  osascript -e 'display notification "First run: installing components. This takes 1-2 minutes." with title "Infinia Spend Analyzer"' >/dev/null 2>&1
  : > "$LOG"
  if ! "$PY" -m venv "$VENV" >> "$LOG" 2>&1 || \
     ! "$VENV/bin/pip" install -q flask pdfplumber pandas openpyxl >> "$LOG" 2>&1; then
    rm -rf "$VENV"
    alert "Setup failed. Details are in: ~/Library/Application Support/CCSorter/install.log"
    exit 1
  fi
fi

exec "$VENV/bin/python" "$RES/app.py"
