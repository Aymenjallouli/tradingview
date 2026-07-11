"""
mt5_regime.py — the regime brain (higher-timeframe trend filter).

Backtested finding: strategies lose when they fight the bigger trend. Adding a
DAILY-regime filter turned losers into winners in testing:
  * BTC donchian: PF 0.68 (losing) -> 1.15 (winning) with the filter
  * ETH donchian: PF 1.03 -> 1.74
  * Gold donchian: 3.05 -> 3.32 (and 4.00 with trailing too)

The rule: only take LONGs when the daily trend is UP (price above its daily
200-EMA), and only take SHORTs when the daily trend is DOWN. This stops the
"buying a dip in a downtrend" and "shorting a market that drifts up" losers.

Used by the orchestrator to gate entries. Cached per symbol (recomputed at most
once per 10 min) so it doesn't hammer the daily-candle pull every poll.
"""

from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


class RegimeBrain:
    def __init__(self, bridge):
        self.bridge = bridge
        self._cache = {}     # our_symbol -> (bull_bool, timestamp)

    def _daily_bull(self, our_symbol):
        """True if price is above its DAILY 200-EMA (long-term uptrend)."""
        now = datetime.now(timezone.utc)
        cached = self._cache.get(our_symbol)
        if cached and (now - cached[1]).total_seconds() < 600:
            return cached[0]
        df = self.bridge.candles(our_symbol, "1d", 260)
        if df.empty or len(df) < 200:
            # unknown regime -> don't block (fail open)
            self._cache[our_symbol] = (None, now)
            return None
        ema200 = df["close"].ewm(span=200, adjust=False).mean().iloc[-1]
        bull = bool(df["close"].iloc[-1] > ema200)
        self._cache[our_symbol] = (bull, now)
        return bull

    def allows(self, our_symbol, side):
        """Return (allowed, reason). Longs need daily-bull, shorts need
        daily-bear. Unknown regime = allowed (fail open)."""
        bull = self._daily_bull(our_symbol)
        if bull is None:
            return True, "regime unknown"
        if side == "buy" and not bull:
            return False, "regime: daily downtrend (no longs)"
        if side == "sell" and bull:
            return False, "regime: daily uptrend (no shorts)"
        return True, "regime ok"
