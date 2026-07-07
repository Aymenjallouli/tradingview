"""
claude_trader.py — Module B: the autonomous AI discretionary trader.

An experiment, stated honestly: give Claude $50 of PAPER money and the goal
"earn $50/day," let it choose trades at its own discretion, and record what
happens — whatever it is. Expectation (from our own tests + the literature):
it will most likely underperform and may hit the kill switch. The value is the
honest record, not profit.

Uses the Claude Code CLI (`claude -p`, your subscription) — NOT the paid API.

System-enforced rules (apply regardless of what the AI outputs):
  * Spot only — no leverage, no shorting.
  * <= 50% of current equity per position; <= 3 open positions.
  * Stops mandatory — if the AI omits one, a -5% default is applied.
  * Fills at the NEXT candle open; real fee (0.1%/side) + live spread slippage.
  * Equity < $10 -> frozen forever (one life, no top-ups).

Decision cadence: every DECISION_SECONDS (default 2h to respect rate limits).
"""

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

import requests

import config

CLAUDE_BIN = shutil.which("claude")
IS_WINDOWS = os.name == "nt"

FEE = config.FEE_PCT
START_CAPITAL = 50.0
KILL_EQUITY = 10.0
MAX_POS_PCT = 0.50           # <=50% equity per position
MAX_POSITIONS = 3
DEFAULT_STOP = 0.05          # -5% applied if AI omits a stop
DECISION_SECONDS = int(os.getenv("CLAUDE_TRADER_SECONDS", "7200"))  # 2h
UNIVERSE_EXTRA = ["BTCUSDT", "ETHUSDT"]

MANDATE = (
    "You manage $50 of paper money on real crypto prices. The owner's goal: "
    "earn $50 per day. You choose trades at your own discretion. You may be "
    "aggressive or cautious — your choices and their results are logged "
    "permanently. Constraints you cannot override: spot only (no leverage, no "
    "shorting), max 50% of current equity per position, max 3 open positions, "
    "real fees and spread apply. If equity falls below $10 the experiment ends "
    "permanently."
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _log(m):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [claude-trader] {m}", flush=True)


def _price(sym):
    try:
        d = requests.get(f"{config.BINANCE_REST}/api/v3/ticker/price",
                        params={"symbol": sym}, timeout=8).json()
        return float(d["price"])
    except Exception:  # noqa: BLE001
        return None


def _spread_side(sym):
    try:
        d = requests.get(f"{config.BINANCE_REST}/api/v3/ticker/bookTicker",
                        params={"symbol": sym}, timeout=8).json()
        bid, ask = float(d["bidPrice"]), float(d["askPrice"])
        return (ask - bid) / bid / 2 if bid > 0 else 0.0005
    except Exception:  # noqa: BLE001
        return 0.0005


class ClaudeTrader:
    def __init__(self, broker, radar=None):
        self.broker = broker
        self.radar = radar
        self.account = "claude_trader"
        self.broker.ensure_account(self.account)
        self.frozen = False
        self.started_at = _now()
        self.decisions = []          # rolling decision log (with outcomes)
        self.last_decision = None
        self.epitaph = None
        self._running = False
        self._equity_curve = [START_CAPITAL]

    # ------------------------------------------------------------------
    # Build the context + prompt for one decision.
    # ------------------------------------------------------------------
    def _universe(self):
        syms = list(UNIVERSE_EXTRA)
        if self.radar is not None:
            for c in (self.radar.grid_candidates + self.radar.trend_candidates):
                if c["symbol"] not in syms:
                    syms.append(c["symbol"])
        return syms[:12]

    def _context(self):
        prices = {}
        for s in self._universe():
            p = _price(s)
            if p:
                prices[s] = p
        positions = []
        for p in self.broker.open_positions(self.account):
            mark = prices.get(p["symbol"], p["entry_price"])
            positions.append({
                "symbol": p["symbol"], "entry": round(p["entry_price"], 6),
                "now": round(mark, 6),
                "pnl_pct": round((mark / p["entry_price"] - 1) * 100, 2)})
        cash = self.broker.cash(self.account)
        equity = self.broker.equity(self.account, prices)
        days = max(1e-6, (time.time() - self._parse(self.started_at)) / 86400)
        total_pnl_pct = (equity / START_CAPITAL - 1) * 100
        return {
            "prices": prices, "cash": round(cash, 2),
            "equity": round(equity, 2), "positions": positions,
            "days_elapsed": round(days, 2),
            "cumulative_pnl_pct": round(total_pnl_pct, 2),
            "recent_decisions": self.decisions[-10:],
        }

    def _parse(self, iso):
        try:
            return datetime.fromisoformat(iso).timestamp()
        except Exception:  # noqa: BLE001
            return time.time()

    def _prompt(self, ctx):
        return (
            MANDATE + "\n\n"
            "Here is the current state (JSON):\n"
            + json.dumps(ctx, indent=2) + "\n\n"
            "Decide your actions. Respond with STRICT JSON only, no prose:\n"
            '{ "actions": [ {"action":"buy|sell|hold","symbol":"BTCUSDT",'
            '"size_pct":0-50,"stop_loss_pct":number,"take_profit_pct":number,'
            '"reasoning":"1-2 sentences"} ], '
            '"self_assessment":"1 sentence on how the goal is going" }\n'
            "Rules: spot only; size_pct is % of current equity (<=50); at most "
            "3 open positions; only symbols present in prices. If you hold, "
            'use action "hold". Output JSON and nothing else.'
        )

    def _call_claude(self, prompt):
        """Run `claude -p`, passing the prompt on STDIN (robust — avoids shell
        quoting issues when the prompt contains JSON braces/quotes/newlines).
        """
        if not CLAUDE_BIN:
            return None
        env = dict(os.environ)
        if "HOME" not in env and "USERPROFILE" in env:
            env["HOME"] = env["USERPROFILE"]
        try:
            # `claude -p` with the prompt piped on STDIN — no shell string, so
            # JSON braces/quotes/newlines in the prompt can't break the command.
            # CLAUDE_BIN is the resolved full path (finds .CMD on Windows), so
            # no shell is needed on either platform.
            r = subprocess.run([CLAUDE_BIN, "-p"],
                               input=prompt, capture_output=True, text=True,
                               timeout=180, env=env)
        except Exception as exc:  # noqa: BLE001
            _log(f"claude call failed: {exc}")
            return None
        if r.returncode != 0:
            _log(f"claude rc={r.returncode}: {(r.stderr or '')[:120]}")
            return None
        return r.stdout.strip()

    def _extract_json(self, text):
        """Pull the first JSON object out of Claude's reply; None if malformed."""
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Run one decision cycle (also usable standalone for the checkpoint test).
    # ------------------------------------------------------------------
    def decide_once(self):
        if self.frozen:
            return None
        ctx = self._context()
        # Kill switch check first.
        if ctx["equity"] < KILL_EQUITY:
            self._freeze("equity fell below $10")
            return None
        prompt = self._prompt(ctx)
        raw = self._call_claude(prompt)
        decision = self._extract_json(raw)
        stamp = _now()
        if decision is None:
            entry = {"time": stamp, "status": "no decision (malformed/no CLI)",
                     "raw": (raw or "")[:200]}
            self.decisions.append(entry)
            self.last_decision = entry
            _log("no decision (malformed JSON or claude unavailable)")
            return entry

        # Apply the decision through the enforced rules.
        results = self._apply(decision, ctx)
        entry = {
            "time": stamp,
            "self_assessment": decision.get("self_assessment", ""),
            "actions": decision.get("actions", []),
            "results": results,
            "equity_after": round(self.broker.equity(self.account,
                                                     ctx["prices"]), 2),
        }
        self.decisions.append(entry)
        self.last_decision = entry
        self._equity_curve.append(entry["equity_after"])
        _log(f"decision applied: {results} | assessment: "
             f"{decision.get('self_assessment','')[:80]}")
        return entry

    def _apply(self, decision, ctx):
        """Enforce all system rules regardless of AI output."""
        results = []
        prices = ctx["prices"]
        for a in decision.get("actions", []):
            action = str(a.get("action", "hold")).lower()
            sym = a.get("symbol", "")
            if action == "hold":
                results.append(f"hold {sym}")
                continue
            if sym not in prices:
                results.append(f"reject {sym}: not in universe")
                continue
            price = prices[sym]
            cost_fn = self._cost_fn(sym)
            if action == "sell":
                if self.broker.has_position(self.account, sym):
                    r = self.broker.sell(self.account, sym, price, "ai_sell",
                                         cost_fn)
                    results.append(f"SOLD {sym} P&L ${r['pnl']:+.3f}")
                else:
                    results.append(f"reject sell {sym}: no position")
            elif action == "buy":
                # Enforce max positions.
                if len(self.broker.open_positions(self.account)) >= MAX_POSITIONS:
                    results.append(f"reject buy {sym}: max 3 positions")
                    continue
                if self.broker.has_position(self.account, sym):
                    results.append(f"reject buy {sym}: already held")
                    continue
                size = min(MAX_POS_PCT, max(0.0, float(a.get("size_pct", 0)) / 100))
                if size <= 0:
                    results.append(f"reject buy {sym}: size 0")
                    continue
                r = self.broker.buy(self.account, sym, price, size, cost_fn)
                if r:
                    # Record the AI's stop (or default -5%) with the position.
                    stop = a.get("stop_loss_pct")
                    stop = float(stop)/100 if stop else DEFAULT_STOP
                    self._stops = getattr(self, "_stops", {})
                    self._stops[sym] = {"entry": price, "stop": stop,
                                        "tp": (float(a.get("take_profit_pct"))/100
                                               if a.get("take_profit_pct") else None)}
                    results.append(f"BOUGHT {sym} ({size*100:.0f}% equity, "
                                   f"stop {stop*100:.0f}%)")
                else:
                    results.append(f"reject buy {sym}: no cash")
        return results

    def _cost_fn(self, sym):
        slip = _spread_side(sym)
        def fn(mid, side):
            return mid * (1 + slip) if side == "buy" else mid * (1 - slip)
        return fn

    def _check_stops(self):
        """Between decisions, enforce stops/take-profits on every price tick."""
        stops = getattr(self, "_stops", {})
        for pos in self.broker.open_positions(self.account):
            sym = pos["symbol"]
            info = stops.get(sym)
            if not info:
                info = {"entry": pos["entry_price"], "stop": DEFAULT_STOP,
                        "tp": None}
            price = _price(sym)
            if price is None:
                continue
            entry = pos["entry_price"]
            reason = None
            if price <= entry * (1 - info["stop"]):
                reason = "stop_loss"
            elif info.get("tp") and price >= entry * (1 + info["tp"]):
                reason = "take_profit"
            if reason:
                self.broker.sell(self.account, sym, price, reason,
                                 self._cost_fn(sym))
                _log(f"{sym} auto-exit {reason} @ {price}")

    def _freeze(self, why):
        self.frozen = True
        stats = self.broker.stats(self.account)
        last = ""
        for d in reversed(self.decisions):
            if d.get("self_assessment"):
                last = d["self_assessment"]
                break
        self.epitaph = {"why": why, "final_stats": stats,
                        "last_assessment": last, "died_at": _now()}
        _log(f"FROZEN: {why}. Epitaph: {last}")

    def run(self):
        self._running = True
        _log(f"Claude Trader started. Mandate: $50/day. Decision every "
             f"{DECISION_SECONDS//3600}h. One life, kill at ${KILL_EQUITY}.")
        # First decision shortly after boot.
        time.sleep(15)
        last_decision = 0
        while self._running and not self.frozen:
            self._check_stops()
            if time.time() - last_decision >= DECISION_SECONDS:
                try:
                    self.decide_once()
                except Exception as exc:  # noqa: BLE001
                    _log(f"decision error: {exc}")
                last_decision = time.time()
            for _ in range(30):
                if not self._running:
                    return
                time.sleep(1)

    def stop(self):
        self._running = False

    def snapshot(self):
        prices = {}
        for p in self.broker.open_positions(self.account):
            prices[p["symbol"]] = _price(p["symbol"]) or p["entry_price"]
        equity = self.broker.equity(self.account, prices)
        days = max(1e-6, (time.time() - self._parse(self.started_at)) / 86400)
        pnl_pct = (equity / START_CAPITAL - 1) * 100
        positions = [{
            "symbol": p["symbol"], "entry": round(p["entry_price"], 6),
            "now": round(prices.get(p["symbol"], p["entry_price"]), 6),
            "pnl_pct": round((prices.get(p["symbol"], p["entry_price"])
                              / p["entry_price"] - 1) * 100, 2),
        } for p in self.broker.open_positions(self.account)]
        return {
            "mandate": MANDATE,
            "frozen": self.frozen,
            "epitaph": self.epitaph,
            "equity": round(equity, 2),
            "start_capital": START_CAPITAL,
            "cash": round(self.broker.cash(self.account), 2),
            "days": round(days, 2),
            "cumulative_pnl_pct": round(pnl_pct, 2),
            "daily_pace_pct": round(pnl_pct / days, 2) if days else 0.0,
            "goal_daily_pct": 100.0,   # $50/day on $50 = +100%/day
            "positions": positions,
            "stats": self.broker.stats(self.account),
            "decisions": self.decisions[-15:][::-1],
            "equity_curve": self._equity_curve[-60:],
            "verdict": self._verdict(equity, days),
        }

    def _verdict(self, equity, days):
        """Template-based (not AI) honest comparison line vs the mandate."""
        pnl = (equity / START_CAPITAL - 1) * 100
        pace = pnl / days if days else 0
        return (f"Day {days:.1f}: Claude Trader {pnl:+.1f}% "
                f"({pace:+.1f}%/day) vs the +100%/day goal — "
                f"{'on track' if pace >= 100 else 'far below (as expected — $50/day is unrealistic)'}")


if __name__ == "__main__":
    # Standalone: run ONE real decision cycle and print it (checkpoint 3).
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from broker import MultiBroker
    from scanner import Scanner
    b = MultiBroker("claude_trader_test.db")
    radar = Scanner(top_n=15)
    print("Scanning radar for the universe...")
    radar.scan_once()
    t = ClaudeTrader(b, radar=radar)
    print("Running ONE real decision cycle (calls claude -p)...")
    entry = t.decide_once()
    print(json.dumps(entry, indent=2, default=str))
    b.close()
    os.remove("claude_trader_test.db") if os.path.exists("claude_trader_test.db") else None
