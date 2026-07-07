"""
scanner.py — Market radar (SUPPORT role, no trading).

RETIRED as a trader (PF 0.14 — it was noise, not a strategy). Repurposed as a
RADAR: every scan classifies each liquid market as TRENDING, RANGING, or
NEITHER, and produces two ranked watchlists:
    * "Grid candidates"  — ranging + liquid + tight spread (feeds the grid v2)
    * "Trend candidates" — trending up + liquid (informational for now)

It never trades and has no equity. The grid module reads the ranging list
during its rotation. Trend stays on fixed symbols (a future trend-v3 could use
the trend list — not built yet).
"""

import time
from datetime import datetime, timezone

import pandas as pd
import requests

import config


def _log(m):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [radar] {m}", flush=True)


_SKIP = {"USDCUSDT", "USD1USDT", "RLUSDUSDT", "TUSDUSDT", "FDUSDUSDT",
         "BUSDUSDT", "DAIUSDT", "USDPUSDT", "EURUSDT", "AEURUSDT", "XUSDUSDT"}

# Min 24h volume to be "liquid enough" to grid. $10M keeps ~45 coins in play
# (vs only ~10 at $50M) while still avoiding illiquid junk. Env-overridable.
import os as _os
MIN_VOLUME = float(_os.getenv("GRID_MIN_VOLUME", "10000000"))


def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()


def _rsi(s, p):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / p, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / p, adjust=False).mean()
    return (100 - 100 / (1 + g / loss)).fillna(100)


def _choppiness(closes):
    if len(closes) < 10 or closes[0] == 0:
        return 0.0
    net = abs(closes[-1] - closes[0]) / closes[0]
    total = sum(abs(closes[i] - closes[i - 1])
                for i in range(1, len(closes))) / closes[0]
    return (1 - net / total) if total > 0 else 0.0


class Scanner:
    """Radar only — classifies markets, no trading, no account."""

    def __init__(self, top_n=50, timeframe="1h", scan_seconds=300, **_ignore):
        # **_ignore keeps old constructor call sites working (broker etc.).
        self.top_n = top_n
        self.timeframe = timeframe
        self.scan_seconds = scan_seconds
        self.grid_candidates = []    # ranging + liquid + tight spread
        self.trend_candidates = []   # trending up + liquid
        self.last_scan = None
        self._running = False

    def _liquid_markets(self):
        try:
            info = requests.get(f"{config.BINANCE_REST}/api/v3/exchangeInfo",
                                timeout=20).json()
            spot = {s["symbol"] for s in info["symbols"]
                    if s["symbol"].endswith("USDT")
                    and s["status"] == "TRADING"
                    and s.get("isSpotTradingAllowed")}
            tk = requests.get(f"{config.BINANCE_REST}/api/v3/ticker/24hr",
                              timeout=25).json()
            rows = []
            for t in tk:
                if t["symbol"] in spot and t["symbol"] not in _SKIP \
                        and t["symbol"].isascii() \
                        and t["symbol"].replace("USDT", "").isalnum():
                    vol = float(t["quoteVolume"])
                    if vol >= MIN_VOLUME:      # liquid enough to grid safely
                        rows.append((t["symbol"], vol))
            rows.sort(key=lambda x: x[1], reverse=True)
            return rows[:self.top_n]           # [(symbol, volume), ...]
        except Exception as exc:  # noqa: BLE001
            _log(f"liquid list failed: {exc}")
            return []

    def _spread_pct(self, sym):
        """Half the bid-ask spread as a % (per-side slippage estimate)."""
        try:
            d = requests.get(f"{config.BINANCE_REST}/api/v3/ticker/bookTicker",
                            params={"symbol": sym}, timeout=8).json()
            bid, ask = float(d["bidPrice"]), float(d["askPrice"])
            if bid <= 0:
                return None
            return (ask - bid) / bid / 2 * 100
        except Exception:  # noqa: BLE001
            return None

    def _classify(self, sym, vol):
        try:
            rows = requests.get(
                f"{config.BINANCE_REST}/api/v3/klines",
                params={"symbol": sym, "interval": self.timeframe,
                        "limit": 250}, timeout=12).json()
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(rows, list) or len(rows) < 210:
            return None
        closes = [float(r[4]) for r in rows]
        close = pd.Series(closes)
        ef = float(_ema(close, 20).iloc[-1])
        es = float(_ema(close, 50).iloc[-1])
        et = float(_ema(close, 200).iloc[-1])
        r = float(_rsi(close, 14).iloc[-1])
        price = closes[-1]
        chop = _choppiness(closes[-200:])
        spread = self._spread_pct(sym)

        uptrend = ef > es and price > et
        # RANGING: choppy AND not strongly trending. Loosened (chop>0.85, band
        # within 8% of the 50-EMA) so many more coins qualify — $50M/chop>0.9
        # left only ~2 coins on a quiet day. Grid's range-break exit handles any
        # that turn out to trend.
        ranging = chop > 0.85 and abs(price - es) / es < 0.08
        regime = "TRENDING" if uptrend and not ranging \
            else ("RANGING" if ranging else "NEITHER")
        return {"symbol": sym, "price": price, "rsi": round(r, 1),
                "chop": round(chop, 3), "vol_m": round(vol / 1e6, 0),
                "spread_pct": round(spread, 4) if spread is not None else None,
                "regime": regime, "uptrend": uptrend}

    def scan_once(self):
        markets = self._liquid_markets()
        if not markets:
            return
        grid_c, trend_c = [], []
        for sym, vol in markets:
            info = self._classify(sym, vol)
            if not info:
                continue
            if info["regime"] == "RANGING":
                # Grid needs a tight spread (spread <= 0.15% per full round trip
                # ≈ 0.075% per side). Eligible flag for the grid to consume.
                sp = info["spread_pct"]
                info["grid_eligible"] = (sp is not None and sp <= 0.075)
                grid_c.append(info)
            elif info["regime"] == "TRENDING":
                trend_c.append(info)
            time.sleep(0.02)
        grid_c.sort(key=lambda x: x["chop"], reverse=True)
        trend_c.sort(key=lambda x: x["vol_m"], reverse=True)
        self.grid_candidates = grid_c[:15]
        self.trend_candidates = trend_c[:15]
        self.last_scan = datetime.now(timezone.utc).isoformat()
        _log(f"scan done: {len(grid_c)} ranging, {len(trend_c)} trending")

    def ranging_symbols(self, eligible_only=True):
        """Symbols the grid module should consider (ranging + tradeable)."""
        return [c["symbol"] for c in self.grid_candidates
                if (c.get("grid_eligible") or not eligible_only)]

    def run(self):
        self._running = True
        _log(f"Radar started (support role, no trading): top {self.top_n} "
             f"liquid coins, every {self.scan_seconds}s")
        while self._running:
            try:
                self.scan_once()
            except Exception as exc:  # noqa: BLE001
                _log(f"scan error: {exc}")
            for _ in range(self.scan_seconds):
                if not self._running:
                    return
                time.sleep(1)

    def stop(self):
        self._running = False

    def snapshot(self):
        return {
            "role": "radar (support, no trading)",
            "last_scan": self.last_scan,
            "grid_candidates": self.grid_candidates,
            "trend_candidates": self.trend_candidates,
        }
