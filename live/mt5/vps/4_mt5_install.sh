#!/usr/bin/env bash
# STAGE 4 — install the MetaTrader 5 terminal under Wine.
# Uses the Pepperstone-branded installer so their DEMO server is pre-loaded in
# the login list. Override the URL if Pepperstone changes it:
#     MT5_URL="https://.../pepperstone5setup.exe" ./4_mt5_install.sh
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

MT5_URL="${MT5_URL:-https://download.mql5.com/cdn/web/pepperstone.group.limited/mt5/pepperstone5setup.exe}"
INST=mt5setup.exe
echo "== downloading MT5 installer =="
wget -qO "$INST" "$MT5_URL"

pgrep -x Xvfb >/dev/null || (Xvfb "$DISPLAY" -screen 0 1024x768x16 &>/dev/null &) && sleep 3

echo "== installing MT5 (silent /auto) — takes a couple of minutes =="
wr "$INST" /auto || true          # installer may exit non-zero yet still install
sleep 20
wineserver -w || true

echo "== locating terminal64.exe =="
TERM_EXE="$(find "$WINEPREFIX/drive_c" -name terminal64.exe 2>/dev/null | head -1 || true)"
if [ -z "$TERM_EXE" ]; then
  echo "!! terminal64.exe not found. The install may have failed — paste output to Claude."
  exit 1
fi
echo "found: $TERM_EXE"
# Save the path for the launcher + the bot (initialize() uses it under Wine).
echo "$TERM_EXE" > "$HOME/.mt5_terminal_path"
echo ""
echo "STAGE 4 DONE. The terminal is installed but NOT yet logged in."
echo "Next: log in once (you need to SEE the screen) — run:  ./4b_login.sh"
