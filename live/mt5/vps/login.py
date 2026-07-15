"""
Headless MT5 login for the VPS. Logs the running terminal into the account using
credentials from the environment (loaded from live/mt5/.env by the launcher), so
the service comes up logged-in after every reboot with no GUI needed.

Reads: MT5_TERMINAL_PATH, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER.
Exits 0 if the account is connected, 1 otherwise (so the launcher can log it).
No secrets live in this file — they come from the gitignored .env.
"""
import os
import sys

import MetaTrader5 as mt5

kw = {}
path = os.environ.get("MT5_TERMINAL_PATH")
if path:
    kw["path"] = path
if os.environ.get("MT5_LOGIN"):
    kw["login"] = int(os.environ["MT5_LOGIN"])
    kw["password"] = os.environ.get("MT5_PASSWORD", "")
    kw["server"] = os.environ.get("MT5_SERVER", "")

ok = mt5.initialize(**kw)
info = mt5.account_info()
print(f"[login] initialize={ok} error={mt5.last_error()} "
      f"account={(info.login, info.balance, info.server) if info else None}")
mt5.shutdown()
sys.exit(0 if info else 1)
