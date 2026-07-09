"""
mt5_telegram.py — push the bot's signals to a Telegram channel.

Build a track record IN PUBLIC (free) before ever charging anyone. Every time a
strategy fires a real entry, this posts a clean, formatted signal to your
channel. It ALSO posts closes (so wins/losses are public and honest — that
honesty is exactly what makes a track record worth trusting later).

Setup (3 minutes):
  1. Telegram -> @BotFather -> /newbot -> copy the BOT TOKEN
  2. Create a channel, add your bot as an ADMIN
  3. Set env vars (or put them in live/mt5/.env):
        MT5_TG_TOKEN=123456:ABC...
        MT5_TG_CHAT=@your_channel_username    (or the numeric -100... id)

If the env vars are missing, this stays silent (no-op) — the bot runs fine
without Telegram.

IMPORTANT (read the chat): selling paid signals is regulated financial advice
in most countries and can be illegal without a license, ESPECIALLY on unproven
signals. Run the channel FREE to build a public, honest track record first.
Every message carries a "not financial advice / demo" disclaimer.
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

TOKEN = os.getenv("MT5_TG_TOKEN", "").strip()
CHAT = os.getenv("MT5_TG_CHAT", "").strip()
DISCLAIMER = ("\n\n_Demo track record. Not financial advice. Trading is high"
              " risk; most retail traders lose money._")

_ENABLED = bool(TOKEN and CHAT)


def enabled():
    return _ENABLED


def _send(text):
    """Fire-and-forget Telegram message (never raises into the trading loop)."""
    if not _ENABLED:
        return False
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": CHAT, "text": text, "parse_mode": "Markdown",
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def post_signal(symbol, strategy, side, price, sl, tp, confidence=None,
                label=None, reason=""):
    """Post a new-entry signal."""
    emoji = "🟢" if side == "buy" else "🔴"
    arrow = "LONG ▲" if side == "buy" else "SHORT ▼"
    conf = ""
    if confidence is not None:
        conf = f"\n*Confidence:* {label or ''} ({confidence})"
    txt = (f"{emoji} *SIGNAL — {symbol}*  {arrow}\n"
           f"*Strategy:* {strategy}{conf}\n"
           f"*Entry:* `{price}`\n"
           f"*Stop:* `{round(sl,5)}`   *Target:* `{round(tp,5)}`\n"
           f"_{reason}_"
           f"{DISCLAIMER}")
    return _send(txt)


def post_close(symbol, strategy, profit, reason=""):
    """Post a closed trade (honest — wins AND losses)."""
    emoji = "✅" if profit >= 0 else "❌"
    txt = (f"{emoji} *CLOSED — {symbol}*  ({strategy})\n"
           f"*Result:* {'+' if profit>=0 else ''}{round(profit,2)} USD\n"
           f"_{reason}_"
           f"{DISCLAIMER}")
    return _send(txt)


def post_text(text):
    return _send(text)


def daily_summary(equity, start_equity, wins, losses, open_count):
    """Optional end-of-day recap for the channel."""
    pnl = equity - start_equity
    emoji = "📈" if pnl >= 0 else "📉"
    txt = (f"{emoji} *Daily Recap*\n"
           f"Equity: ${round(equity,2)}  ({'+' if pnl>=0 else ''}{round(pnl,2)})\n"
           f"Closed: {wins}W / {losses}L   Open: {open_count}"
           f"{DISCLAIMER}")
    return _send(txt)
