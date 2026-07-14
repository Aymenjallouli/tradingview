#!/usr/bin/env bash
# STAGE 3 — install the Python deps into Wine-Python and SMOKE-TEST them.
# This is the make-or-break gate: if numpy/pandas import cleanly under Wine,
# the whole approach works and everything after is straightforward. If numpy
# fails here, STOP and tell Claude — we pivot to the bridge approach instead of
# discovering the problem three stages later.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

echo "== upgrading pip =="
wpy -m pip install --upgrade pip

echo "== installing requirements into Wine-Python (numpy/pandas take a while) =="
wpy -m pip install -r "$APP_DIR/requirements.txt"

echo ""
echo "== THE GATE: import the risky libraries under Wine =="
wpy -c "import numpy, pandas, MetaTrader5, fastapi, uvicorn; \
print('SMOKE OK  numpy', numpy.__version__, ' pandas', pandas.__version__, \
' MT5', MetaTrader5.__version__)"

echo ""
echo "If you saw 'SMOKE OK ...', the hard part is proven. Next: ./4_mt5_install.sh"
echo "If numpy/pandas threw an error, STOP and paste it to Claude."
