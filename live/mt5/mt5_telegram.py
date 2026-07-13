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
                timeframe=None, notional_usd=None, balance=None,
                profit_at_tp=None, loss_at_sl=None):
    """Post a clean new-entry signal. profit_at_tp / loss_at_sl are the REAL
    dollar amounts (computed from actual lots x tick value in the orchestrator)
    — not derived, so they're accurate even on min-lot-forced trades."""
    emoji = "🟢" if side == "buy" else "🔴"
    arrow = "BUY (long)" if side == "buy" else "SELL (short)"
    d = _decimals(price)
    risk_dist = abs(price - sl)
    rew_dist = abs(tp - price)
    rr = (rew_dist / risk_dist) if risk_dist > 0 else 0
    sl_pct = risk_dist / price * 100
    tp_pct = rew_dist / price * 100
    # Fallback if the caller didn't pass real $ amounts.
    if profit_at_tp is None and risk_usd is not None:
        profit_at_tp = abs(risk_usd) * rr
    if loss_at_sl is None and risk_usd is not None:
        loss_at_sl = abs(risk_usd)

    lines = [f"{emoji} *{symbol}*  —  {arrow}",
             f"📊 Strategy: {strategy}"]
    if confidence is not None:
        lines.append(f"🎯 Confidence: {label or ''} ({confidence}/100)")
    lines.append("")
    lines.append(f"Entry:  `{price:.{d}f}`")
    lines.append(f"Stop:   `{sl:.{d}f}`   (−{sl_pct:.1f}%)")
    lines.append(f"Target: `{tp:.{d}f}`   (+{tp_pct:.1f}%)")
    lines.append(f"R:R  {rr:.1f} : 1")
    if lots is not None:
        lines.append(f"Size:  {lots} lots")
    # The money math — REAL amounts, clearly framed.
    if profit_at_tp is not None and loss_at_sl is not None:
        lines.append("")
        wtxt = f"✅ If target hit:  *+${profit_at_tp:,.2f}*"
        if balance is not None:
            wtxt += f"  → ${balance + profit_at_tp:,.2f}"
        ltxt = f"⛔ If stop hit:    *−${loss_at_sl:,.2f}*"
        if balance is not None:
            ltxt += f"  → ${balance - loss_at_sl:,.2f}"
        lines.append(wtxt)
        lines.append(ltxt)
    if timeframe:
        lines.append(f"\n⏱️ Est. hold: {_HOLD_ESTIMATE.get(timeframe, 'varies')}")
    if reason:
        lines.append(f"_{reason}_")
    lines.append(DISCLAIMER)
    return _send("\n".join(lines))


def post_close(symbol, strategy, profit, reason="", balance=None):
    """Post a closed trade (honest — wins AND losses) with the new balance."""
    emoji = "✅" if profit >= 0 else "❌"
    bal = f"\n*New balance:* ${balance:,.2f}" if balance is not None else ""
    txt = (f"{emoji} *CLOSED — {symbol}*  ({strategy})\n"
           f"*Result:* {'+' if profit>=0 else ''}{round(profit,2)} USD{bal}\n"
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
