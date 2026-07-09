"""
mt5_orchestrator.py — runs strategies, gates every order through a risk
governor, and executes on the DEMO account.

Risk governor (HARD limits, enforced regardless of what a strategy asks):
  * max 1.5% account risk per position
  * max 5 open positions total, max 3 per strategy
  * daily circuit breaker: if equity drops 5% intraday, BLOCK new entries until
    the next day (existing positions keep their broker SL/TP)
  * every order carries broker-side SL + TP

Modes:
  * dry_run=True  -> compute intents + what WOULD happen, send NOTHING
  * dry_run=False -> actually place demo orders

The orchestrator polls candles per strategy timeframe, asks each strategy for
intents on its allowed symbols, and routes them through the governor.
"""

import time
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None

import mt5_orders as orders
from mt5_strategies import build_strategies


import mt5_log


def _log(m):
    mt5_log.emit("orch", m)


import os
MAX_RISK_PCT = float(os.getenv("MT5_RISK_PCT", "1.5"))
# Size trades as if the account were this big, not the demo's $100k. Set to 1000
# so the P&L mirrors what a real $1000 account would do. 0 = use real equity.
VIRTUAL_EQUITY = float(os.getenv("MT5_VIRTUAL_EQUITY", "1000"))
# Raised so the system grabs MORE opportunities when signals cluster in one
# sweep. Still risk-governed: 10 x 1.5% = up to 15% account risk deployed.
MAX_POSITIONS_TOTAL = int(os.getenv("MT5_MAX_POS", "10"))
MAX_POSITIONS_PER_STRATEGY = int(os.getenv("MT5_MAX_POS_STRAT", "5"))
DAILY_DRAWDOWN_STOP = float(os.getenv("MT5_DAILY_STOP", "0.05"))   # 5%


class RiskGovernor:
    def __init__(self, bridge):
        self.bridge = bridge
        self.day = None
        self.day_start_equity = None
        self.blocked = False       # circuit breaker tripped for the day

    def _roll_day(self, equity):
        today = datetime.now(timezone.utc).date()
        if self.day != today:
            self.day = today
            self.day_start_equity = equity
            self.blocked = False
            _log(f"new day {today}: start equity ${equity:.2f}")

    def check_breaker(self):
        snap = self.bridge.account_snapshot()
        if not snap:
            return
        eq = snap["equity"]
        self._roll_day(eq)
        if self.day_start_equity and not self.blocked:
            dd = (self.day_start_equity - eq) / self.day_start_equity
            if dd >= DAILY_DRAWDOWN_STOP:
                self.blocked = True
                _log(f"!!! CIRCUIT BREAKER: equity -{dd*100:.1f}% today. "
                     f"Blocking new entries until tomorrow.")

    def can_open(self, strategy_key):
        """Return (allowed, reason)."""
        if self.blocked:
            return False, "circuit breaker (daily -5%)"
        ours = orders.open_positions()
        if len(ours) >= MAX_POSITIONS_TOTAL:
            return False, f"max {MAX_POSITIONS_TOTAL} total positions"
        per = sum(1 for p in ours
                  if p.comment.startswith(strategy_key))
        if per >= MAX_POSITIONS_PER_STRATEGY:
            return False, f"max {MAX_POSITIONS_PER_STRATEGY} for {strategy_key}"
        return True, "ok"


class Orchestrator:
    def __init__(self, bridge, dry_run=True):
        self.bridge = bridge
        self.dry_run = dry_run
        self.governor = RiskGovernor(bridge)
        self.strategies = build_strategies()
        # remember last candle time processed per (strategy, symbol) to act
        # once per closed candle.
        self._last_bar = {}
        self.log = []              # recent human-readable events for the UI
        # Full per-poll scan report so the dashboard can show the bot's live
        # "thinking": every strategy x symbol, its status, and how close it is
        # to a signal. Keyed by "strategy|symbol".
        self.scan = {}
        self.last_scan_time = None
        self.poll_count = 0

    def _record(self, msg):
        _log(msg)
        self.log.append({"time": datetime.now(timezone.utc).isoformat(),
                         "msg": msg})
        self.log = self.log[-100:]

    def _has_position(self, strategy_key, our_symbol):
        broker = self.bridge.symbols.get(our_symbol)
        for p in orders.open_positions():
            if p.symbol == broker and p.comment.startswith(strategy_key):
                return p
        return None

    def _execute_open(self, strat, our_symbol, intent, equity):
        broker = self.bridge.symbols.get(our_symbol)
        tick = self.bridge.tick(our_symbol)
        if not broker or not tick:
            return
        price = tick["ask"] if intent["side"] == "buy" else tick["bid"]
        # SL/TP prices from the strategy's percentages (direction-aware).
        if intent["side"] == "buy":
            sl = price * (1 - intent["stop_pct"])
            tp = price * (1 + intent["target_pct"])
        else:
            sl = price * (1 + intent["stop_pct"])
            tp = price * (1 - intent["target_pct"])
        lots = orders.lots_for_risk(broker, equity, MAX_RISK_PCT, price, sl)
        if lots <= 0:
            self._record(f"[{strat.key}] {our_symbol}: skip — lot size 0 "
                         f"(risk/stop invalid)")
            return
        allowed, reason = self.governor.can_open(strat.key)
        if not allowed:
            self._record(f"[{strat.key}] {our_symbol}: BLOCKED — {reason}")
            return
        if self.dry_run:
            self._record(f"[DRY-RUN] [{strat.key}] WOULD {intent['side'].upper()} "
                         f"{our_symbol} {lots} lots @ {price:.5f} "
                         f"SL={sl:.5f} TP={tp:.5f} ({intent['reason']})")
            return
        res = orders.market_order(broker, intent["side"], lots, sl, tp,
                                  comment=f"{strat.key}")
        if res.get("ok"):
            self._record(f"[{strat.key}] OPENED {our_symbol} {lots} lots "
                         f"@ {res['price']} SL={sl:.5f} TP={tp:.5f}")
        else:
            self._record(f"[{strat.key}] OPEN FAILED {our_symbol}: "
                         f"{res.get('comment') or res.get('error')}")

    def _execute_close(self, strat, our_symbol, intent):
        pos = self._has_position(strat.key, our_symbol)
        if not pos:
            return
        if self.dry_run:
            self._record(f"[DRY-RUN] [{strat.key}] WOULD CLOSE {our_symbol} "
                         f"({intent['reason']})")
            return
        res = orders.close_position(pos)
        self._record(f"[{strat.key}] CLOSED {our_symbol} "
                     f"({intent['reason']}) ok={res['ok']}")

    def _scan_set(self, strat_key, our_symbol, status, detail="", extra=None):
        """Record what one strategy saw on one symbol this poll (for the UI)."""
        entry = {"strategy": strat_key, "symbol": our_symbol,
                 "status": status, "detail": detail,
                 "time": datetime.now(timezone.utc).isoformat()}
        if extra:
            entry.update(extra)
        self.scan[f"{strat_key}|{our_symbol}"] = entry

    def poll_once(self, symbols=None):
        """One pass: check breaker, run each strategy on its allowed symbols."""
        self.governor.check_breaker()
        self.poll_count += 1
        self.last_scan_time = datetime.now(timezone.utc).isoformat()
        # Size positions as if the account were VIRTUAL_EQUITY (e.g. $1000), so
        # the risk/P&L mirror a realistic small account instead of the demo's
        # $100k. The circuit breaker still watches the REAL demo equity.
        equity = VIRTUAL_EQUITY if VIRTUAL_EQUITY > 0 else (
            (self.bridge.account_snapshot() or {}).get("equity", 100000))
        universe = symbols or list(self.bridge.symbols.keys())

        for strat in self.strategies:
            # Respect a strategy's symbol whitelist (e.g. breakout = stocks+gold).
            allowed = getattr(strat, "allowed_symbols", None)
            for our_symbol in universe:
                if allowed is not None and our_symbol not in allowed:
                    continue
                df = self.bridge.candles(our_symbol, strat.timeframe, 300)
                if df.empty:
                    self._scan_set(strat.key, our_symbol, "no-data",
                                   "no candles from broker")
                    continue
                # Act once per newly CLOSED candle.
                bar_key = (strat.key, our_symbol)
                # (the last row can be the forming candle; use the prior closed
                #  one for signals, matching the paper engines)
                closed = df.iloc[:-1]
                if closed.empty:
                    continue
                closed_time = closed["time"].iloc[-1]
                pos = self._has_position(strat.key, our_symbol)
                intents = strat.on_candle(our_symbol, closed,
                                          has_position=pos is not None)
                # --- Record the scan status for the dashboard ---
                dist = self._breakout_distance(strat, closed)
                if pos is not None:
                    close_intent = next(
                        (i for i in intents if i["type"] == "close"), None)
                    self._scan_set(
                        strat.key, our_symbol, "holding",
                        "exit signal!" if close_intent else "in position",
                        extra={"distance": dist})
                elif any(i["type"] == "open" for i in intents):
                    self._scan_set(strat.key, our_symbol, "SIGNAL",
                                   "entry conditions met",
                                   extra={"distance": dist})
                else:
                    self._scan_set(strat.key, our_symbol, "waiting",
                                   "no signal", extra={"distance": dist})
                # Only act on OPEN intents once per new closed candle; CLOSE
                # intents can fire any poll (protective).
                for it in intents:
                    if it["type"] == "open":
                        if self._last_bar.get(bar_key) == closed_time:
                            self._scan_set(strat.key, our_symbol, "SIGNAL",
                                           "signal (already acted this candle)",
                                           extra={"distance": dist})
                            continue
                        self._last_bar[bar_key] = closed_time
                        self._execute_open(strat, our_symbol, it, equity)
                    elif it["type"] == "close":
                        self._execute_close(strat, our_symbol, it)

    def _breakout_distance(self, strat, closed):
        """For breakout-style strategies, how far (%) price is from firing.
        Returns None for strategies where 'distance' isn't meaningful."""
        try:
            key = strat.key
            cl = closed["close"].values
            hi = closed["high"].values
            price = cl[-1]
            if key in ("donchian", "donch1h") and len(hi) >= 21:
                band = hi[-21:-1].max()
                return round((band - price) / price * 100, 2)
            if key == "breakout" and len(hi) >= 21:
                band = hi[-21:-1].max()
                return round((band - price) / price * 100, 2)
        except Exception:  # noqa: BLE001
            return None
        return None

    def status(self):
        snap = self.bridge.account_snapshot()
        ours = orders.open_positions()
        # Sort the scan so signals + near-misses float to the top.
        def _rank(s):
            order = {"SIGNAL": 0, "holding": 1, "waiting": 2,
                     "no-data": 3}.get(s.get("status"), 4)
            d = s.get("distance")
            return (order, d if d is not None else 999)
        scan = sorted(self.scan.values(), key=_rank)
        return {
            "dry_run": self.dry_run,
            "account": snap,
            "breaker_blocked": self.governor.blocked,
            "poll_count": self.poll_count,
            "last_scan_time": self.last_scan_time,
            "open_positions": [{
                "symbol": p.symbol, "type": "buy" if p.type == 0 else "sell",
                "volume": p.volume, "price_open": p.price_open,
                "sl": p.sl, "tp": p.tp, "profit": p.profit,
                "strategy": p.comment} for p in ours],
            "strategies": [s.key for s in self.strategies],
            "scan": scan,
            "log": self.log[-60:][::-1],
        }
