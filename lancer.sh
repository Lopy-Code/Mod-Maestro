#!/usr/bin/env sh
# Lance ModMaestro (interface web). Linux / macOS.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then exec python3 main.py "$@"; fi
echo "Python 3.11+ est requis : https://www.python.org/downloads/" >&2
exit 1
