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

# Load live/mt5/.env so MT5_TG_TOKEN / MT5_TG_CHAT (and other config) are
# available without exporting them by hand. Safe no-op if dotenv is missing.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:  # noqa: BLE001
    pass

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


# Rough "how long this trade tends to last" by the strategy's timeframe — an
# ESTIMATE (trades exit on stop/target/signal, not a timer). Helps the reader
# know the horizon: a 15m scalp is minutes-to-hours; a daily trade is days.
_HOLD_ESTIMATE = {
    "15m": "~1-6 hours", "30m": "~2-12 hours", "1h": "~4-24 hours",
    "4h": "~1-4 days", "1d": "~1-3 weeks",
}


def _decimals(price):
    return 5 if price < 10 else (3 if price < 1000 else 2)


def post_signal(symbol, strategy, side, price, sl, tp, confidence=None,
                label=None, reason="", lots=None, risk_usd=None,
                timeframe=None):
    """Post a full new-entry signal: exact entry/SL/TP, position size (lots +
    $ risk), reward:risk, confidence, and an estimated hold time."""
    emoji = "🟢" if side == "buy" else "🔴"
    arrow = "LONG ▲ (buy)" if side == "buy" else "SHORT ▼ (sell)"
    d = _decimals(price)
    # reward:risk from the SL/TP distances
    risk_dist = abs(price - sl)
    rew_dist = abs(tp - price)
    rr = (rew_dist / risk_dist) if risk_dist > 0 else 0
    sl_pct = risk_dist / price * 100
    tp_pct = rew_dist / price * 100

    lines = [f"{emoji} *SIGNAL — {symbol}*  {arrow}",
             f"*Strategy:* {strategy}"]
    if confidence is not None:
        lines.append(f"*Confidence:* {label or ''} ({confidence}/100)")
    lines.append("")
    lines.append(f"📍 *Entry:* `{price:.{d}f}`")
    lines.append(f"🛑 *Stop-loss:* `{sl:.{d}f}`  (−{sl_pct:.2f}%)")
    lines.append(f"🎯 *Take-profit:* `{tp:.{d}f}`  (+{tp_pct:.2f}%)")
    lines.append(f"⚖️ *Reward:Risk:* {rr:.1f} : 1")
    if lots is not None:
        size = f"💰 *Size:* {lots} lots"
        if risk_usd is not None:
            size += f"  (risking ~${abs(risk_usd):.0f} if stop hit)"
        lines.append(size)
    if timeframe:
        est = _HOLD_ESTIMATE.get(timeframe, "varies")
        lines.append(f"⏱️ *Est. hold:* {est}  ({timeframe} strategy)")
    lines.append(f"\n_Why:_ {reason}")
    lines.append(DISCLAIMER)
    return _send("\n".join(lines))


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
