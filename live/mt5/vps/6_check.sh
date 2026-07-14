#!/usr/bin/env bash
# STAGE 6 — confirm it is actually trading. Runs the honest audit against the
# broker's own records (the only source of truth) from inside Wine-Python.
set -uo pipefail
cd "$(dirname "$0")"
source ./env.sh

echo "== service state =="
systemctl --no-pager status mt5bots.service | head -6 || true
echo ""
echo "== books answering on their ports? =="
for p in 8801 8802 8803 8804 8805 8806; do
  if curl -fsS "http://127.0.0.1:$p/api/state" >/dev/null 2>&1; then
    echo "  :$p up"
  else
    echo "  :$p DOWN"
  fi
done
echo ""
echo "== broker audit (are we making money?) =="
cd "$APP_DIR"
wpy mt5_audit.py || echo "audit needs the terminal logged in — check 4b_login.sh"
echo ""
echo "To view a dashboard from your computer, tunnel it:"
echo "    ssh -L 8800:localhost:8800 $USER@\$(hostname -I | awk '{print \$1}')"
echo "    then run on the VPS:  cd $APP_DIR && wine python mt5_hub.py"
echo "    and open http://localhost:8800 in your browser."
