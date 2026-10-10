#!/bin/sh
# Double-click me in Finder. Opens the SimpleMesh installer window.
# The first time, macOS may ask you to right-click > Open instead of double-clicking.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
    exec python3 install.py "$@"
fi
echo "Python 3 was not found. Install it from https://www.python.org/downloads/ and try again."
read -r _
