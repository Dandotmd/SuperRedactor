#!/bin/bash
# Double-click this file to start SuperRedactor.
# It sets itself up the first time, then opens your browser.

cd "$(dirname "$0")" || exit 1

echo "Starting SuperRedactor…"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed on this Mac."
  echo "Install it from https://www.python.org/downloads/ and run this again."
  echo
  read -r -p "Press Return to close."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "First run — setting up. This takes a minute and only happens once."
  python3 -m venv .venv || {
    echo "Could not create the setup folder."
    read -r -p "Press Return to close."
    exit 1
  }
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -e . || {
    echo
    echo "Setup could not download what it needs."
    echo "If you are on a work network, ask IT for your organisation's"
    echo "certificate file and see the README section on locked-down computers."
    read -r -p "Press Return to close."
    exit 1
  }
  echo "Setup finished."
  echo
fi

echo "SuperRedactor is running at http://127.0.0.1:8321"
echo "Leave this window open while you use it."
echo "Close it, or press Control-C, when you are done."
echo

.venv/bin/superredactor
