#!/usr/bin/env bash
# Startet memecoin-radar. Unter macOS/Linux ausfuehrbar machen:
#   chmod +x start.sh
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    exec python3 run.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python run.py "$@"
fi

echo
echo "  Python wurde nicht gefunden."
echo "  Installation: https://www.python.org/downloads/"
echo
exit 1
