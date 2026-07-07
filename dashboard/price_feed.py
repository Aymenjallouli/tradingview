"""
price_feed.py — Live real-time price feed via Binance's public WebSocket.

Streams REAL market ticks (no API key, no cost) for the crypto symbols and
keeps the latest price for each in memory. The dashboard reads these prices to
mark open paper positions to market in real time — so your equity moves with the
actual market, tick by tick, even though the money is still simulated.

This is the "real data, fake money" phase: real prices in, paper trades only.

Design:
  * One background thread runs the WebSocket and updates a shared dict.
  * The dict is protected by a lock; readers get a cheap snapshot.
  * Auto-reconnects if the socket drops.

Symbols: Binance uses lowercase concatenated tickers (btcusdt). We map our
canonical names to those, and expose prices back under BOTH the Binance form
and the project's forms (BTC-USD, BTCUSDT) so any system can look them up.
"""

import json
import threading
import time

import websocket  # from the websocket-client package


# Canonical symbol -> Binance stream ticker.
STREAM_SYMBOLS = {
    "BTCUSDT": "btcusdt",
    "ETHUSDT": "ethusdt",
    "SOLUSDT": "solusdt",
}

# When we get a price for e.g. BTCUSDT, also publish it under these aliases so
# the trend system (BTC-USD) and others can find it.
ALIASES = {
    "BTCUSDT": ["BTC-USD"],
    "ETHUSDT": ["ETH-USD"],
    "SOLUSDT": ["SOL-USD"],
}


class PriceFeed:
    def __init__(self):
        self._prices = {}          # symbol -> {"price": float, "ts": epoch_ms}
        self._lock = threading.Lock()
        self._ws = None
        self._thread = None
        self._running = False
        self._connected = False

    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    def _stream_url(self):
        streams = "/".join(f"{t}@trade" for t in STREAM_SYMBOLS.values())
        return f"wss://stream.binance.com:9443/stream?streams={streams}"

    def _on_message(self, ws, message):
        try:
            payload = json.loads(message)
            data = payload.get("data", {})
            sym = data.get("s")        # e.g. "BTCUSDT"
            price = data.get("p")      # trade price (string)
            ts = data.get("T")         # trade time (ms)
            if sym and price is not None:
                self._set_price(sym, float(price), ts)
        except Exception:  # noqa: BLE001 - never let a bad frame kill the feed
            pass

    def _on_open(self, ws):
        self._connected = True

    def _on_close(self, ws, *args):
        self._connected = False

    def _on_error(self, ws, err):
        self._connected = False

    def _run(self):
        """Run the socket, reconnecting with backoff while _running is True."""
        backoff = 1
        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    self._stream_url(),
                    on_message=self._on_message,
                    on_open=self._on_open,
                    on_close=self._on_close,
                    on_error=self._on_error,
                )
                # run_forever blocks until the socket closes.
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:  # noqa: BLE001
                self._connected = False
            if not self._running:
                break
            # Reconnect with capped exponential backoff.
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

    # ------------------------------------------------------------------
    def _set_price(self, sym, price, ts):
        with self._lock:
            entry = {"price": price, "ts": ts}
            self._prices[sym] = entry
            for alias in ALIASES.get(sym, []):
                self._prices[alias] = entry

    def get_prices(self):
        """Return a snapshot {symbol: price} of the latest real prices."""
        with self._lock:
            return {k: v["price"] for k, v in self._prices.items()}

    def is_connected(self):
        return self._connected


# A single shared feed the dashboard imports and starts.
FEED = PriceFeed()
