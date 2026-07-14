#!/usr/bin/env bash
# STAGE 1 — system packages: Wine (to run Windows programs), Xvfb (a fake
# screen so the GUI terminal can run headless), and x11vnc (so you can SEE that
# screen once, to log MT5 in the first time). Ubuntu 22.04 (jammy).
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

echo "== enabling 32-bit packages (Wine needs them) =="
sudo dpkg --add-architecture i386

echo "== adding the official WineHQ repo (newer & more reliable than Ubuntu's) =="
sudo mkdir -pm755 /etc/apt/keyrings
sudo wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key
sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources
sudo apt-get update

echo "== installing Wine + helpers =="
sudo apt-get install -y --install-recommends winehq-stable || sudo apt-get install -y --install-recommends wine-stable
sudo apt-get install -y xvfb x11vnc winbind cabextract unzip wget xdotool

echo "== initialising the Wine world at $WINEPREFIX (this takes a minute) =="
# Start the fake screen if it isn't up, so wineboot has a display.
pgrep -x Xvfb >/dev/null || (Xvfb "$DISPLAY" -screen 0 1024x768x16 &>/dev/null &) && sleep 3
WINEDLLOVERRIDES="mscoree=d;mshtml=d" wineboot --init
wineserver -w

echo ""
echo "STAGE 1 DONE. Verify:"
wine --version
echo "If that printed a version (e.g. wine-9.x), run:  ./2_python.sh"
