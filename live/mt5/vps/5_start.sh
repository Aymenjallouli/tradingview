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

# Load secrets (MT5 login/password/server + Telegram) from the gitignored .env
# so the terminal can auto-log-in headlessly after a reboot.
if [ -f "$APP_DIR/.env" ]; then set -a; . "$APP_DIR/.env"; set +a; fi

# 1) fake screen
pgrep -x Xvfb >/dev/null || (Xvfb "$DISPLAY" -screen 0 1024x768x16 &>/dev/null &)
sleep 3

# 2) MT5 terminal (relaunched if not already up)
if ! pgrep -f terminal64.exe >/dev/null; then
  echo "[start] launching MT5 terminal"
  wr "$TERM_EXE" &>/dev/null &
  sleep 30
fi

# 3) log the terminal into the account (credentials from .env). Idempotent:
#    if it's already logged in this just re-confirms.
if [ -n "${MT5_LOGIN:-}" ]; then
  echo "[start] logging in account $MT5_LOGIN"
  wpy "$(dirname "$0")/login.py" || echo "[start] login step returned non-zero"
  sleep 3
fi

# 4) the supervised books (this call blocks and self-heals its children)
echo "[start] launching the 6 books"
cd "$APP_DIR"
exec wpy run_all.py
