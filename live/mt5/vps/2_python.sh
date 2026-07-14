#!/usr/bin/env bash
# STAGE 2 — install a real Windows Python 3.11 INSIDE Wine. This is the trick
# that lets "import MetaTrader5" work on Linux: the package is Windows-only, so
# we run our bot under a Windows Python that lives in the Wine world.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

PYINST=python-3.11.9-amd64.exe
echo "== downloading $PYINST =="
[ -f "$PYINST" ] || wget -q "https://www.python.org/ftp/python/3.11.9/$PYINST"

pgrep -x Xvfb >/dev/null || (Xvfb "$DISPLAY" -screen 0 1024x768x16 &>/dev/null &) && sleep 3

echo "== installing Windows Python into Wine (silent) =="
# InstallAllUsers + PrependPath so "wine python" just works afterwards.
wr "$PYINST" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1
wineserver -w

echo ""
echo "STAGE 2 DONE. Verify:"
wpy --version
echo "If that printed 'Python 3.11.9', run:  ./3_smoke.sh"
