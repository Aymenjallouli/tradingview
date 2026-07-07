"""
engine.py — Real-time, multi-strategy, multi-feed engine.

Runs up to three strategies at once, each with its own paper account:

  CRYPTO strategies (trend 4h, scalp 1m) run off Binance's live WebSocket.
    - One WS subscribes to every needed (symbol, timeframe) kline stream.
    - The engine acts when a candle CLOSES (event-driven, no polling).

  FOREX strategy (swing 5m) runs off yfinance in a ~60s refresh loop, because
    forex has no free public tick WebSocket. It builds candles from yfinance
    and acts on the latest closed one. (This is the one non-realtime feed;
    everything crypto is true real-time.)

Each strategy trades ONE market's symbols into its OWN account. All shared state
is guarded by a lock so the dashboard can read while the engine writes.
"""

import json
import threading
import time
from collections import deque
from datetime import datetime, timezone

import pandas as pd
import requests
import websocket
import yfinance as yf

import config
import strategy as strat
from broker import MultiBroker


def _log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Cost functions (passed to the broker so it applies realistic fills).
# ---------------------------------------------------------------------------
def crypto_cost(mid, side):
    return mid * (1 + config.SLIPPAGE_PCT) if side == "buy" \
        else mid * (1 - config.SLIPPAGE_PCT)


def forex_cost_fn(symbol):
    info = config.FOREX_SPREADS.get(symbol, {"pip": 0.0001, "spread": 0.5})
    adj = (info["spread"] / 2 + config.FOREX_SLIPPAGE_PIPS) * info["pip"]
    def fn(mid, side):
        return mid + adj if side == "buy" else mid - adj
    return fn


class Engine:
    def __init__(self):
        self.broker = MultiBroker()
        self.lock = threading.Lock()
        self.strategies = strat.build(config.ENABLED)
        for s in self.strategies:
            self.broker.ensure_account(s.key)

        # Live "brain state": latest indicator values per (strategy, symbol),
        # so the dashboard can show WHAT the strategy is looking at right now.
        self.brain = {}

        # Split strategies by market.
        self.crypto_strats = [s for s in self.strategies if s.market == "crypto"]
        self.forex_strats = [s for s in self.strategies if s.market == "forex"]

        # Candle history per (strategy_key, symbol).
        self.candles = {}
        self.last_price = {}          # symbol -> latest price (any market)
        self.connected = {"crypto": False, "forex": False}
        self.events = deque(maxlen=200)
        self._ws = None
        self._running = False

    def _key(self, skey, symbol):
        return f"{skey}:{symbol}"

    def _record(self, msg):
        _log(msg)
        self.events.append(msg)

    # ==================================================================
    # CRYPTO: warmup + WebSocket
    # ==================================================================
    def _warmup_crypto(self):
        for s in self.crypto_strats:
            for sym in config.CRYPTO_SYMBOLS:
                url = f"{config.BINANCE_REST}/api/v3/klines"
                params = {"symbol": sym, "interval": s.timeframe,
                          "limit": min(s.warmup + 20, 1000)}
                try:
                    rows = requests.get(url, params=params, timeout=20).json()
                except Exception as exc:  # noqa: BLE001
                    _log(f"warmup {s.key}/{sym} failed: {exc}")
                    continue
                dq = deque(maxlen=s.warmup + 500)
                for r in rows[:-1]:      # drop the open candle
                    dq.append({"open_time": r[0], "open": float(r[1]),
                               "high": float(r[2]), "low": float(r[3]),
                               "close": float(r[4])})
                self.candles[self._key(s.key, sym)] = dq
                if rows:
                    self.last_price[sym] = float(rows[-1][4])
        self._record("Crypto strategies warmed up.")

    def _crypto_streams(self):
        # Unique (symbol, timeframe) pairs across crypto strategies.
        pairs = set()
        for s in self.crypto_strats:
            for sym in config.CRYPTO_SYMBOLS:
                pairs.add((sym.lower(), s.timeframe))
        return "/".join(f"{sym}@kline_{tf}" for sym, tf in pairs)

    def _on_crypto_msg(self, ws, message):
        try:
            k = json.loads(message)["data"]["k"]
            sym = k["s"]
            tf = k["i"]
            price = float(k["c"])   # current price (updates many times/second)
            with self.lock:
                self.last_price[sym] = price

            # TICK-LEVEL EXITS: on EVERY update (not just candle close), check
            # whether any open scalp position should exit on its stop/target.
            # This is the real-time speed that matters for scalping — we don't
            # wait a full minute to cut a loss or take a profit.
            self._tick_exits(sym, price)

            if k["x"]:   # candle closed -> run full entry/exit logic
                candle = {"open_time": k["t"], "open": float(k["o"]),
                          "high": float(k["h"]), "low": float(k["l"]),
                          "close": float(k["c"])}
                for s in self.crypto_strats:
                    if s.timeframe == tf:
                        self._on_close(s, sym, candle, crypto_cost)
        except Exception as exc:  # noqa: BLE001
            _log(f"crypto msg error: {exc}")

    def _tick_exits(self, sym, price):
        """Check stop-loss / take-profit for open crypto positions on EVERY
        tick. Only price-based exits run here (stop, target) — indicator-based
        exits (EMA cross, Bollinger mid, time stop) still run on candle close.
        This gives scalp exits real-time (sub-second) reaction.
        """
        with self.lock:
            for s in self.crypto_strats:
                pos = self.broker.position(s.key, sym)
                if pos is None:
                    continue
                entry = pos["entry_price"]
                reason = None
                # Stop / target thresholds per strategy.
                if s.key == "scalp":
                    if price <= entry * (1 - config.SCALP_STOP):
                        reason = "stop_loss"
                    else:
                        # Take-profit: price reaches the middle Bollinger band.
                        # Use the latest computed mid band (updates per candle);
                        # checking it on every tick makes the TP fire the instant
                        # price touches it, not a minute later.
                        b = self.brain.get(self._key(s.key, sym)) or {}
                        mid = b.get("bb_mid")
                        if mid and price >= mid:
                            reason = "take_profit"
                else:  # trend
                    if price <= entry * (1 - config.TREND_STOP):
                        reason = "stop_loss"
                    elif price >= entry * (1 + config.TREND_TARGET):
                        reason = "take_profit"
                # Scalp take-profit is the Bollinger mid (indicator) — handled
                # on candle close; but a fixed target check keeps it snappy if
                # you ever add one. Stops are the critical tick-level exit.
                if reason:
                    r = self.broker.sell(s.key, sym, price, reason, crypto_cost)
                    if r:
                        self._record(
                            f"[{s.key}] TICK-EXIT {sym} @ {price:.2f} {reason} "
                            f"P&L ${r['pnl']:+.4f} ({r['return_pct']*100:+.2f}%)")

    def _run_crypto(self):
        backoff = 1
        while self._running:
            try:
                url = f"{config.BINANCE_WS}/stream?streams={self._crypto_streams()}"
                self._ws = websocket.WebSocketApp(
                    url, on_message=self._on_crypto_msg,
                    on_open=lambda w: self._set_conn("crypto", True),
                    on_close=lambda w, *a: self._set_conn("crypto", False),
                    on_error=lambda w, e: self._set_conn("crypto", False))
                self._ws.run_forever(ping_interval=180, ping_timeout=10)
            except Exception as exc:  # noqa: BLE001
                _log(f"crypto WS crash: {exc}")
            if not self._running:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            self._warmup_crypto()

    def _set_conn(self, market, val):
        self.connected[market] = val
        if val:
            self._record(f"{market} feed connected.")

    # ==================================================================
    # FOREX: yfinance ~60s refresh loop
    # ==================================================================
    def _fetch_forex(self, sym, tf):
        try:
            df = yf.download(sym, interval=tf, period="10d",
                             auto_adjust=True, progress=False)
        except Exception as exc:  # noqa: BLE001
            _log(f"forex fetch {sym} failed: {exc}")
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={c: c.lower() for c in df.columns})
        return df[["open", "high", "low", "close"]] if "close" in df else pd.DataFrame()

    def _run_forex(self):
        while self._running:
            any_ok = False
            for s in self.forex_strats:
                for sym in config.FOREX_SYMBOLS:
                    df = self._fetch_forex(sym, s.timeframe)
                    if df.empty or len(df) < s.warmup:
                        continue
                    any_ok = True
                    price = float(df["close"].iloc[-1])
                    with self.lock:
                        self.last_price[sym] = price
                    # Act on the latest CLOSED candle (drop the forming one).
                    closed = df.iloc[:-1]
                    self._forex_decide(s, sym, closed)
            self._set_conn("forex", any_ok)
            # Sleep between refreshes (this feed is not tick-level).
            for _ in range(config.FOREX_POLL_SECONDS):
                if not self._running:
                    return
                time.sleep(1)

    def _forex_decide(self, s, sym, df):
        with self.lock:
            df = df.copy()
            df.columns = [c.lower() for c in df.columns]
            di = s.add_indicators(df).reset_index(drop=True)
            if len(di) < s.warmup:
                return
            i = len(di) - 1
            price = float(di.iloc[i]["close"])
            cost_fn = forex_cost_fn(sym)
            self.brain[self._key(s.key, sym)] = self._brain_state(s, sym, di, i)
            if self.broker.has_position(s.key, sym):
                pos = self.broker.position(s.key, sym)
                reason = s.check_exit(pos["entry_price"], price, di, i, 0)
                if reason:
                    r = self.broker.sell(s.key, sym, price, reason, cost_fn)
                    self._record(f"[{s.key}] SELL {sym} {reason} "
                                 f"P&L ${r['pnl']:+.4f}")
            elif s.entry_signal(di, i):
                r = self.broker.buy(s.key, sym, price, s.size_pct, cost_fn)
                if r:
                    self._record(f"[{s.key}] BUY {sym} @ {price:.5f}")

    # ==================================================================
    # Describe what a strategy "sees" right now (for the brain view + log).
    # ==================================================================
    def _brain_state(self, s, sym, di, i):
        """Return a human-readable dict of the indicator values the strategy
        is looking at, so the dashboard can show the 'brain' and explain why it
        did or didn't trade.
        """
        row = di.iloc[i]
        price = float(row["close"])
        if s.key == "scalp":
            lower = float(row["bb_lower"]) if not pd.isna(row["bb_lower"]) else None
            mid = float(row["bb_mid"]) if not pd.isna(row["bb_mid"]) else None
            rsi = float(row["rsi"]) if not pd.isna(row["rsi"]) else None
            # Why no entry? (only relevant when flat)
            why = []
            band_line = lower * (1 + config.SCALP_BAND_TOL) if lower else None
            if band_line is not None and not (price < band_line):
                why.append("price not near lower band")
            if rsi is not None and not (rsi < config.SCALP_RSI_ENTRY):
                why.append(f"RSI {rsi:.0f} not < {config.SCALP_RSI_ENTRY}")
            return {"price": round(price, 2),
                    "rsi": round(rsi, 1) if rsi is not None else None,
                    "lower_band": round(lower, 2) if lower is not None else None,
                    "bb_mid": mid,  # used by tick-level take-profit exit
                    "waiting_for": "; ".join(why) if why else "entry conditions MET"}
        else:  # trend / forex (EMA based)
            ef = float(row["ema_fast"]) if not pd.isna(row["ema_fast"]) else None
            es = float(row["ema_slow"]) if not pd.isna(row["ema_slow"]) else None
            rsi = float(row["rsi"]) if not pd.isna(row["rsi"]) else None
            trend = "up" if (ef and es and ef > es) else "down"
            return {"price": round(price, 2),
                    "ema_fast": round(ef, 2) if ef else None,
                    "ema_slow": round(es, 2) if es else None,
                    "rsi": round(rsi, 1) if rsi is not None else None,
                    "waiting_for": f"trend is {trend}; waiting for a fresh cross-up + pullback"}

    # ==================================================================
    # Shared candle-close handler (crypto).
    # ==================================================================
    def _on_close(self, s, sym, candle, cost_fn):
        with self.lock:
            key = self._key(s.key, sym)
            if key not in self.candles:
                self.candles[key] = deque(maxlen=s.warmup + 500)
            self.candles[key].append(candle)
            df = pd.DataFrame(list(self.candles[key]))
            if len(df) < s.warmup:
                return
            di = s.add_indicators(df)
            i = len(di) - 1
            price = float(di.iloc[i]["close"])

            # Update live brain state so the dashboard can show it.
            bstate = self._brain_state(s, sym, di, i)
            self.brain[key] = bstate

            if self.broker.has_position(s.key, sym):
                pos = self.broker.position(s.key, sym)
                entry_ms = pos["entry_bar_ms"] or candle["open_time"]
                mins = int((candle["open_time"] - entry_ms) / 60000)
                reason = s.check_exit(pos["entry_price"], price, di, i, mins)
                if reason:
                    r = self.broker.sell(s.key, sym, price, reason, cost_fn)
                    self._record(f"[{s.key}] SELL {sym} @ {price:.2f} {reason} "
                                 f"P&L ${r['pnl']:+.4f} ({r['return_pct']*100:+.2f}%)")
                else:
                    self._record(f"[{s.key}] {sym} candle closed @ {price:.2f} "
                                 f"— holding position")
            elif s.entry_signal(di, i):
                r = self.broker.buy(s.key, sym, price, s.size_pct, cost_fn,
                                    entry_bar_ms=candle["open_time"])
                if r:
                    self._record(f"[{s.key}] BUY {sym} @ {price:.2f} "
                                 f"(committed ${r['committed']:.2f})")
            else:
                # The "thinking out loud" line: candle closed, no trade, WHY.
                self._record(f"[{s.key}] {sym} candle closed @ {price:.2f} — "
                             f"no trade ({bstate.get('waiting_for', 'no signal')})")

    # ==================================================================
    # Lifecycle
    # ==================================================================
    def run(self):
        self._running = True
        threads = []
        if self.crypto_strats:
            self._warmup_crypto()
            t = threading.Thread(target=self._run_crypto, daemon=True)
            t.start(); threads.append(t)
        if self.forex_strats:
            t = threading.Thread(target=self._run_forex, daemon=True)
            t.start(); threads.append(t)
        self._record(f"Engine running: {', '.join(s.key for s in self.strategies)}")
        # Keep the main run() alive.
        while self._running:
            time.sleep(1)

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.close()

    # ==================================================================
    # Dashboard snapshot.
    # ==================================================================
    def snapshot(self):
        with self.lock:
            prices = dict(self.last_price)
            out_strats = []
            for s in self.strategies:
                positions = []
                for p in self.broker.open_positions(s.key):
                    mark = prices.get(p["symbol"], p["fill_price"])
                    positions.append({
                        "symbol": p["symbol"],
                        "entry": round(p["entry_price"], 5),
                        "price": round(mark, 5),
                        "unrealized": round((mark - p["fill_price"]) * p["qty"], 4),
                    })
                stats = self.broker.stats(s.key)
                equity = self.broker.equity(s.key, prices)
                recent = [{
                    "symbol": t["symbol"], "pnl": round(t["pnl"], 4),
                    "return_pct": round(t["return_pct"] * 100, 2),
                    "reason": t["exit_reason"], "exit_time": t["exit_time"],
                } for t in self.broker.trades(s.key)[-15:][::-1]]
                # Attach the live "brain" (indicator state) per symbol.
                brain = {}
                for sym in (config.CRYPTO_SYMBOLS if s.market == "crypto"
                            else config.FOREX_SYMBOLS):
                    b = self.brain.get(self._key(s.key, sym))
                    if b:
                        brain[sym] = b
                out_strats.append({
                    "key": s.key, "label": s.label, "market": s.market,
                    "timeframe": s.timeframe,
                    "cash": round(self.broker.cash(s.key), 2),
                    "equity": round(equity, 2),
                    "start_capital": config.STARTING_CAPITAL,
                    "positions": positions, "stats": stats,
                    "recent_trades": recent, "brain": brain,
                })
            return {
                "connected": self.connected,
                "prices": {k: round(v, 5) for k, v in prices.items()},
                "strategies": out_strats,
                "events": list(self.events)[-30:][::-1],
            }


ENGINE = Engine()


if __name__ == "__main__":
    _log("Starting multi-strategy engine (standalone). Ctrl+C to stop.")
    try:
        ENGINE.run()
    except KeyboardInterrupt:
        ENGINE.stop()
