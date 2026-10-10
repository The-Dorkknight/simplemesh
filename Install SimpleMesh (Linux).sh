#!/bin/sh
# Double-click me (choose "Run"), or run:  sh "Install SimpleMesh (Linux).sh"
# Opens the SimpleMesh installer window. Needs Python 3 (already on Linux Mint / Ubuntu).
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
    exec python3 install.py "$@"
fi
echo "Python 3 was not found. Install it with:  sudo apt install python3 python3-tk"
read -r _
