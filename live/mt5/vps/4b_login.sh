#!/usr/bin/env bash
# STAGE 4b — the ONE time you need to see the screen: log MT5 into your demo
# and enable algorithmic trading. After this, everything runs headless forever.
#
# It opens the terminal on the fake screen and shares that screen over VNC so
# you can view it from your own computer. You do the login by hand (your
# password is typed by YOU, into the terminal — it is never stored in the code).
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

TERM_EXE="$(cat "$HOME/.mt5_terminal_path" 2>/dev/null || true)"
[ -z "$TERM_EXE" ] && { echo "run ./4_mt5_install.sh first"; exit 1; }

pgrep -x Xvfb >/dev/null || (Xvfb "$DISPLAY" -screen 0 1280x800x16 &>/dev/null &) && sleep 3

echo "== launching the MT5 terminal on the fake screen =="
wr "$TERM_EXE" &>/dev/null &
sleep 15

echo "== sharing the screen over VNC (localhost only, for safety) =="
pkill x11vnc 2>/dev/null || true
x11vnc -display "$DISPLAY" -localhost -nopw -forever -quiet &>/dev/null &
sleep 2

MYIP="$(hostname -I | awk '{print $1}')"
cat <<EOF

===============================================================
  MT5 IS OPEN ON THE VPS. To see it and log in:

  1. On YOUR computer, open a terminal and run (keep it open):
         ssh -L 5900:localhost:5900 $USER@$MYIP
  2. Open any VNC viewer and connect to:
         localhost:5900
  3. In the MT5 window that appears:
       - File > Login to Trade Account
       - Login:  61557431
       - Server: Pepperstone-Demo  (pick the demo one from the list)
       - Password: <type it yourself>
       - Tick "Save password"
       - Then: Tools > Options > Expert Advisors >
               [x] Allow algorithmic trading      <-- REQUIRED for the bot
       - Click the "Algo Trading" toolbar button so it is GREEN.
  4. Confirm the balance shows, then close the VNC viewer.

  When done, run:  ./5_install_service.sh
===============================================================
EOF
