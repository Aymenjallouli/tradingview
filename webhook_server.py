"""
webhook_server.py — Module 2: TradingView webhook receiver (OPTIONAL mode).

This is an alternative to the free signal engine (Module 1). Instead of polling
yfinance yourself, TradingView sends an alert to this server when your strategy
fires on their side. The server validates a shared secret, then routes the
signal to the SAME paper broker (paper_broker.py) that Module 1 uses.

IMPORTANT: TradingView webhooks require a PAID TradingView plan (Essential or
higher). On the free plan you cannot send webhook alerts — use Module 1 instead.

Run it:
    uvicorn webhook_server:app --host 0.0.0.0 --port 8000
  (or)
    python webhook_server.py

Then expose it to the internet (TradingView must be able to reach it). The
simplest way for testing is a tunnel like ngrok:
    ngrok http 8000
and use the https URL ngrok gives you as the webhook URL in TradingView.

---------------------------------------------------------------------------
The EXACT alert message JSON to paste into your TradingView alert's "Message"
box (replace the secret with the one from config.py — WEBHOOK_SECRET):

    {
      "secret": "change-me-to-a-long-random-string",
      "symbol": "{{ticker}}",
      "action": "{{strategy.order.action}}",
      "price": {{close}}
    }

  * {{ticker}}, {{strategy.order.action}} and {{close}} are TradingView
    placeholders it fills in automatically.
  * "action" will be "buy" or "sell".
  * Set the webhook URL (Alert dialog -> Notifications -> Webhook URL) to:
        https://YOUR-NGROK-OR-SERVER/webhook
---------------------------------------------------------------------------
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import config
from paper_broker import PaperBroker

app = FastAPI(title="Paper Trading Webhook Receiver")


# ---------------------------------------------------------------------------
# The shape of the JSON TradingView will POST to us.
# ---------------------------------------------------------------------------
class Alert(BaseModel):
    secret: str            # shared secret — must match config.WEBHOOK_SECRET
    symbol: str            # e.g. "BTC-USD" or "AAPL"
    action: str            # "buy" or "sell"
    price: float           # the price to fill at (usually the candle close)


# Map TradingView tickers to our yfinance symbols if they differ.
# TradingView often sends things like "BTCUSD" or "BINANCE:BTCUSDT"; add
# entries here as needed so the broker uses OUR canonical symbol names.
SYMBOL_ALIASES = {
    "BTCUSD": "BTC-USD",
    "BTCUSDT": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "ETHUSDT": "ETH-USD",
}


def normalize_symbol(raw: str) -> str:
    """Turn a TradingView ticker into one of our config.SYMBOLS names."""
    # Strip an exchange prefix like "BINANCE:BTCUSDT" -> "BTCUSDT".
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    return SYMBOL_ALIASES.get(raw.upper(), raw)


@app.get("/")
def health():
    """Simple health check so you can confirm the server is up in a browser."""
    return {"status": "ok", "service": "paper-trading-webhook"}


@app.post("/webhook")
def webhook(alert: Alert):
    """Receive a TradingView alert, validate it, and route it to the broker."""
    # 1. Security: reject anything without the correct shared secret.
    if alert.secret != config.WEBHOOK_SECRET:
        # 403 Forbidden — don't reveal why.
        raise HTTPException(status_code=403, detail="Invalid secret")

    # 2. Validate the action.
    action = alert.action.lower().strip()
    if action not in ("buy", "sell"):
        raise HTTPException(status_code=400,
                            detail=f"Unknown action: {alert.action}")

    symbol = normalize_symbol(alert.symbol)

    # 3. Only trade symbols we actually track.
    if symbol not in config.SYMBOLS:
        raise HTTPException(status_code=400,
                            detail=f"Symbol not tracked: {symbol}")

    # 4. Route to the paper broker (each request opens its own connection so
    #    it's safe under concurrent requests).
    broker = PaperBroker()
    try:
        if action == "buy":
            ok = broker.buy(symbol, alert.price)
            result = "opened" if ok else "skipped (already in position)"
        else:  # sell
            ok = broker.sell(symbol, alert.price, reason="webhook")
            result = "closed" if ok else "skipped (no open position)"
    finally:
        broker.close()

    return {"status": "accepted", "symbol": symbol,
            "action": action, "result": result}


if __name__ == "__main__":
    import uvicorn
    # host 0.0.0.0 so a tunnel/other machines can reach it.
    uvicorn.run(app, host="0.0.0.0", port=8000)
