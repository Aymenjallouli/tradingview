#!/usr/bin/env bash
# Shared configuration for every VPS stage. Sourced by the other scripts.
# Edit this ONE file if a path is wrong; the rest follow.

export WINEPREFIX="$HOME/.mt5wine"     # isolated Wine world just for MT5
export WINEARCH=win64                   # MT5 terminal is 64-bit
export WINEDEBUG=-all                   # quiet Wine's chatter
export DISPLAY="${DISPLAY:-:99}"        # the headless (fake) screen

# Windows-Python inside the Wine prefix. Installed with PrependPath, so "wine
# python" resolves via PATH; this explicit path is the fallback.
export WINPY_DIR="$WINEPREFIX/drive_c/Program Files/Python311"

# Where the trading code lives once cloned on the VPS.
export APP_DIR="$HOME/tradingview/live/mt5"

# Run a Windows program under Wine on the fake screen.
wr() { DISPLAY="$DISPLAY" wine "$@"; }

# Run Windows-Python: try PATH first, fall back to the explicit exe.
wpy() {
  if DISPLAY="$DISPLAY" wine python --version >/dev/null 2>&1; then
    DISPLAY="$DISPLAY" wine python "$@"
  else
    DISPLAY="$DISPLAY" wine "$WINPY_DIR/python.exe" "$@"
  fi
}
