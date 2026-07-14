#!/usr/bin/env bash
# The headless launcher the systemd service runs on boot and keeps alive.
# Brings up the fake screen, starts the (already-logged-in) MT5 terminal, waits
# for it to connect, then launches the supervised books. run_all.py's own
# watchdog restarts any book that dies; systemd restarts this whole script if
# the terminal or Wine itself falls over.
set -uo pipefail
cd "$(dirname "$0")"
source ./env.sh

TERM_EXE="$(cat "$HOME/.mt5_terminal_path" 2>/dev/null || true)"
export MT5_TERMINAL_PATH="$TERM_EXE"     # the bridge's initialize() uses this

# 1) fake screen
pgrep -x Xvfb >/dev/null || (Xvfb "$DISPLAY" -screen 0 1024x768x16 &>/dev/null &)
sleep 3

# 2) MT5 terminal (remembers the last login from stage 4b)
if ! pgrep -f terminal64.exe >/dev/null; then
  echo "[start] launching MT5 terminal"
  wr "$TERM_EXE" &>/dev/null &
  sleep 30
fi

# 3) the supervised books (this call blocks and self-heals its children)
echo "[start] launching the 6 books"
cd "$APP_DIR"
exec wpy run_all.py
