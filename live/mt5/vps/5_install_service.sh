#!/usr/bin/env bash
# STAGE 5 — make it survive reboots. Installs a systemd service that runs the
# headless launcher on boot and restarts it if it ever exits. This is what a
# VPS buys you over a laptop: it is ALWAYS on, and Ubuntu babysits the process.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

SVC=/etc/systemd/system/mt5bots.service
echo "== writing $SVC =="
sudo tee "$SVC" >/dev/null <<EOF
[Unit]
Description=MT5 trading books (Wine, headless)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Environment=HOME=$HOME
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/env bash $(pwd)/5_start.sh
Restart=always
RestartSec=20
# give Wine + the terminal time to come up before systemd judges it failed
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
EOF

echo "== enabling on boot + starting now =="
sudo systemctl daemon-reload
sudo systemctl enable mt5bots.service
sudo systemctl restart mt5bots.service
sleep 45

echo ""
echo "STAGE 5 DONE. Status:"
systemctl --no-pager status mt5bots.service | head -12
echo ""
echo "Watch it live:   journalctl -u mt5bots.service -f"
echo "Is it trading?:  see 6_check.sh"
