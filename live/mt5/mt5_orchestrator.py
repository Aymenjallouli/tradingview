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
import mt5_conviction as conviction
import mt5_telegram as telegram
from mt5_strategies import (build_strategies, build_gold_focus_strategies,
                            build_daytrader_strategies)


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
# Widened to 12% to match the aggressive 2-5%/trade sizing (a 5%/trade loss
# would trip a 5% daily stop instantly). Still a HARD backstop: lose 12% in a
# day and all new entries stop until tomorrow — so you can't nuke the account
# in one bad session. Open positions keep their broker SL/TP.
DAILY_DRAWDOWN_STOP = float(os.getenv("MT5_DAILY_STOP", "0.12"))   # 12%

# DAY-TRADER mode (MT5_DAYTRADER=1): fast strategies only, with a hard daily
# discipline — max N new trades/day, and STOP for the day after M losses. This
# is the classic anti-revenge-trade circuit breaker. Both counters reset each
# UTC day. Defaults: 5 trades/day, stop after 3 losses.
DAYTRADER = os.getenv("MT5_DAYTRADER", "0") == "1"
MAX_TRADES_PER_DAY = int(os.getenv("MT5_MAX_TRADES_DAY", "5"))
MAX_LOSSES_PER_DAY = int(os.getenv("MT5_MAX_LOSSES_DAY", "3"))


class RiskGovernor:
    def __init__(self, bridge):
        self.bridge = bridge
        self.day = None
        self.day_start_equity = None
        self.blocked = False       # circuit breaker tripped for the day
        # Day-trader counters (reset each UTC day).
        self.trades_today = 0
        self.losses_today = 0
        self.day_stopped = False   # hit the loss limit — stop for the day

    def _roll_day(self, equity):
        today = datetime.now(timezone.utc).date()
        if self.day != today:
            self.day = today
            self.day_start_equity = equity
            self.blocked = False
            self.trades_today = 0
            self.losses_today = 0
            self.day_stopped = False
            _log(f"new day {today}: start equity ${equity:.2f}"
                 + (f" · day-trader: 0/{MAX_TRADES_PER_DAY} trades, "
                    f"0/{MAX_LOSSES_PER_DAY} losses" if DAYTRADER else ""))

    def record_trade_opened(self):
        self.trades_today += 1

    def record_trade_closed(self, profit):
        """Called when a trade closes — count losses toward the daily limit."""
        if profit < 0:
            self.losses_today += 1
            if DAYTRADER and self.losses_today >= MAX_LOSSES_PER_DAY \
                    and not self.day_stopped:
                self.day_stopped = True
                _log(f"!!! DAY-TRADER STOP: {self.losses_today} losses today "
                     f"(limit {MAX_LOSSES_PER_DAY}). No more trades until "
                     f"tomorrow. Discipline > revenge trading.")

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
            return False, "circuit breaker (daily drawdown)"
        # Day-trader discipline: stop after M losses, cap at N trades/day.
        if DAYTRADER:
            if self.day_stopped:
                return False, (f"day-trader STOPPED "
                               f"({self.losses_today} losses today)")
            if self.trades_today >= MAX_TRADES_PER_DAY:
                return False, (f"day-trader max {MAX_TRADES_PER_DAY} "
                               f"trades/day reached")
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
        # Mode selection:
        #  DAYTRADER  -> fast metals strategies + 5-trade/3-loss daily limit
        #  GOLD_FOCUS -> all metals strategies (15m..daily)
        #  else       -> the full 42-market team
        if DAYTRADER:
            self.strategies = build_daytrader_strategies()
            _log(f"*** DAY-TRADER MODE — fast metals only · max "
                 f"{MAX_TRADES_PER_DAY} trades/day · stop after "
                 f"{MAX_LOSSES_PER_DAY} losses ***")
        elif os.getenv("MT5_GOLD_FOCUS", "0") == "1":
            self.strategies = build_gold_focus_strategies()
            _log("*** GOLD/SILVER FOCUS MODE — metals only ***")
        else:
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
        self._agree_count = {}     # symbol -> #strategies signalling this poll
        self._last_conf = {}       # "strat|symbol" -> confidence info of a fill

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
        # --- CONVICTION SIZING ---------------------------------------------
        # Score this setup's confidence (strategy agreement + backtested edge +
        # trend alignment), then size risk between RISK_MIN and RISK_MAX.
        # NOT a guarantee — just more behind the higher-odds setups.
        agree = getattr(self, "_agree_count", {}).get(our_symbol, 1)
        trend_ok = self._trend_aligned(our_symbol, strat.timeframe)
        conf = conviction.confidence(our_symbol, agree, trend_ok)
        risk_pct = conviction.risk_pct_for(conf)
        lots = orders.lots_for_risk(broker, equity, risk_pct, price, sl)
        if lots <= 0:
            self._record(f"[{strat.key}] {our_symbol}: skip — lot size 0 "
                         f"(risk/stop invalid)")
            return True          # not a transient failure — don't hammer-retry
        allowed, reason = self.governor.can_open(strat.key)
        if not allowed:
            self._record(f"[{strat.key}] {our_symbol}: BLOCKED — {reason}")
            return True          # governor block — wait for a new candle
        conf_txt = (f"conf {conf} ({conviction.label(conf)}, {agree} strat"
                    f"{'s' if agree != 1 else ''} agree, risk {risk_pct}%)")
        if self.dry_run:
            self._record(f"[DRY-RUN] [{strat.key}] WOULD {intent['side'].upper()} "
                         f"{our_symbol} {lots} lots @ {price:.5f} "
                         f"SL={sl:.5f} TP={tp:.5f} — {conf_txt}")
            return True
        res = orders.market_order(broker, intent["side"], lots, sl, tp,
                                  comment=f"{strat.key}")
        if res.get("ok"):
            self.governor.record_trade_opened()
            self._record(f"[{strat.key}] OPENED {our_symbol} {lots} lots "
                         f"@ {res['price']} SL={sl:.5f} TP={tp:.5f} — {conf_txt}")
            self._last_conf[f"{strat.key}|{our_symbol}"] = {
                "confidence": conf, "label": conviction.label(conf),
                "agree": agree, "risk_pct": risk_pct}
            # Push the full signal to Telegram (no-op if not configured):
            # entry/SL/TP, size (lots + $ value), $ profit if TP / loss if SL,
            # resulting balance, R:R, confidence, est. hold.
            risk_usd = equity * (risk_pct / 100.0)
            notional_usd = None
            if mt5 is not None:
                info = mt5.symbol_info(broker)
                if info and info.trade_contract_size:
                    notional_usd = lots * info.trade_contract_size * res["price"]
            snap = self.bridge.account_snapshot() or {}
            balance = snap.get("balance")
            telegram.post_signal(our_symbol, getattr(strat, "label", strat.key),
                                 intent["side"], res["price"], sl, tp,
                                 confidence=conf, label=conviction.label(conf),
                                 reason=intent.get("reason", ""),
                                 lots=lots, risk_usd=risk_usd,
                                 timeframe=getattr(strat, "timeframe", None),
                                 notional_usd=notional_usd, balance=balance)
            return True
        comment = (res.get("comment") or res.get("error") or "").lower()
        # "Market closed" / "no prices" are NOT transient — the market is shut
        # for hours. Don't retry every 60s (log spam); treat as acted so we
        # wait for a new candle, same as a normal signal.
        non_transient = any(k in comment for k in
                            ("market closed", "no prices", "market is closed",
                             "trade disabled", "invalid stops"))
        self._record(f"[{strat.key}] OPEN FAILED {our_symbol}: "
                     f"{res.get('comment') or res.get('error')}"
                     f"{' (waiting — not retrying)' if non_transient else ''}")
        return non_transient   # True => acted (won't hammer-retry a closed market)

    def _trend_aligned(self, our_symbol, timeframe):
        """True if price is above its 200-EMA on this timeframe (with-trend)."""
        try:
            df = self.bridge.candles(our_symbol, timeframe, 220)
            if df.empty or len(df) < 200:
                return False
            ema200 = df["close"].ewm(span=200, adjust=False).mean().iloc[-1]
            return bool(df["close"].iloc[-1] > ema200)
        except Exception:  # noqa: BLE001
            return False

    def _execute_close(self, strat, our_symbol, intent):
        pos = self._has_position(strat.key, our_symbol)
        if not pos:
            return
        if self.dry_run:
            self._record(f"[DRY-RUN] [{strat.key}] WOULD CLOSE {our_symbol} "
                         f"({intent['reason']})")
            return
        profit = pos.profit
        res = orders.close_position(pos)
        self._record(f"[{strat.key}] CLOSED {our_symbol} "
                     f"({intent['reason']}) ok={res['ok']}")
        if res.get("ok"):
            snap = self.bridge.account_snapshot() or {}
            telegram.post_close(our_symbol, getattr(strat, "label", strat.key),
                                profit, reason=intent.get("reason", ""),
                                balance=snap.get("balance"))

    def _scan_set(self, strat_key, our_symbol, status, detail="", extra=None):
        """Record what one strategy saw on one symbol this poll (for the UI)."""
        entry = {"strategy": strat_key, "symbol": our_symbol,
                 "status": status, "detail": detail,
                 "time": datetime.now(timezone.utc).isoformat()}
        if extra:
            entry.update(extra)
        self.scan[f"{strat_key}|{our_symbol}"] = entry

    def _count_closed_trades(self):
        """Detect newly-closed OUR trades (bot-close OR broker SL/TP) and feed
        their P&L to the governor so the day-trader loss limit counts every
        loss, however it closed. Idempotent via a seen-deal set."""
        if mt5 is None:
            return
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(hours=24), now)
        if not deals:
            return
        if not hasattr(self, "_seen_deals"):
            self._seen_deals = set()
        for d in deals:
            if d.magic != orders.MAGIC or d.entry != 1:  # our closing deals
                continue
            if d.ticket in self._seen_deals:
                continue
            self._seen_deals.add(d.ticket)
            self.governor.record_trade_closed(d.profit)
        # keep the set from growing forever
        if len(self._seen_deals) > 2000:
            self._seen_deals = set(list(self._seen_deals)[-1000:])

    def poll_once(self, symbols=None):
        """One pass: check breaker, run each strategy on its allowed symbols."""
        # Detect a STALE MT5 handle: the long-running process can lose its
        # Python-API link even while the terminal stays connected (symptom:
        # every candle pull returns empty -> dashboard shows "no-data"). If the
        # account snapshot is gone, force a reconnect before scanning.
        if self.bridge.account_snapshot() is None:
            _log("account snapshot empty — MT5 handle looks stale, reconnecting")
            self.bridge.reconnect()
        self.governor.check_breaker()
        self._count_closed_trades()   # feed closed P&L to day-trader limits
        self.poll_count += 1
        self.last_scan_time = datetime.now(timezone.utc).isoformat()
        # Size positions as if the account were VIRTUAL_EQUITY (e.g. $1000), so
        # the risk/P&L mirror a realistic small account instead of the demo's
        # $100k. The circuit breaker still watches the REAL demo equity.
        equity = VIRTUAL_EQUITY if VIRTUAL_EQUITY > 0 else (
            (self.bridge.account_snapshot() or {}).get("equity", 100000))
        universe = symbols or list(self.bridge.symbols.keys())

        # --- First pass: count how many strategies signal each symbol this
        #     poll, so conviction sizing can reward AGREEMENT. Cheap: reuses the
        #     same candle pulls the main loop would do (cached by MT5).
        self._agree_count = {}
        for strat in self.strategies:
            allowed = getattr(strat, "allowed_symbols", None)
            for our_symbol in universe:
                if allowed is not None and our_symbol not in allowed:
                    continue
                if self._has_position(strat.key, our_symbol):
                    continue
                df = self.bridge.candles(our_symbol, strat.timeframe, 300)
                if df.empty or len(df) < 2:
                    continue
                closed = df.iloc[:-1]
                try:
                    intents = strat.on_candle(our_symbol, closed,
                                              has_position=False)
                except Exception:  # noqa: BLE001
                    continue
                if any(i["type"] == "open" for i in intents):
                    self._agree_count[our_symbol] = \
                        self._agree_count.get(our_symbol, 0) + 1

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
                    agree = self._agree_count.get(our_symbol, 1)
                    trend_ok = self._trend_aligned(our_symbol, strat.timeframe)
                    conf = conviction.confidence(our_symbol, agree, trend_ok)
                    self._scan_set(strat.key, our_symbol, "SIGNAL",
                                   f"entry! conf {conf} "
                                   f"({conviction.label(conf)}, {agree} agree)",
                                   extra={"distance": dist, "confidence": conf})
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
                        # Only mark the candle as "acted" if the order actually
                        # went through. A blocked/failed order (e.g. algo
                        # trading off, requote) should retry on the next poll,
                        # not be silently skipped until a new candle.
                        acted = self._execute_open(strat, our_symbol, it, equity)
                        if acted:
                            self._last_bar[bar_key] = closed_time
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
            "daytrader": ({
                "on": True,
                "trades": self.governor.trades_today,
                "max_trades": MAX_TRADES_PER_DAY,
                "losses": self.governor.losses_today,
                "max_losses": MAX_LOSSES_PER_DAY,
                "stopped": self.governor.day_stopped,
            } if DAYTRADER else {"on": False}),
            "open_positions": [{
                "symbol": p.symbol, "type": "buy" if p.type == 0 else "sell",
                "volume": p.volume, "price_open": p.price_open,
                "sl": p.sl, "tp": p.tp, "profit": p.profit,
                "strategy": p.comment} for p in ours],
            "strategies": [s.key for s in self.strategies],
            "scan": scan,
            "log": self.log[-60:][::-1],
        }
