"""
mt5_correlation.py — the missing risk rail.

The problem the backtest CANNOT see: our 38 index strategies (US500, US100,
US30, GER40, UK100, JPN225, AUS200, HK50, FRA40, NAS100) are NOT 38 independent
edges. Indices crash together. On a bad day they ALL lose at once — so the
"diversified" portfolio takes one giant correlated hit that no single-strategy
backtest ever shows.

The cap: limit how much risk may sit in any one CORRELATED GROUP at once.
Groups are computed from real price correlation (rolling, cached) and fall back
to a static asset-class map if data is thin.

Enforced in the orchestrator before every entry:
  * max MAX_GROUP_RISK_PCT of the account at risk within one correlated group
  * max MAX_GROUP_POSITIONS open positions within one group

So even if 10 index strategies all fire on the same crash-day bounce, only a
couple get in — the rest are skipped. This is the rail that guards the drawdown
your backtest can't see.
"""

import os
from datetime import datetime, timezone

import numpy as np

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None

import mt5_log

MAX_GROUP_RISK_PCT = float(os.getenv("MT5_MAX_GROUP_RISK", "4.0"))
MAX_GROUP_POSITIONS = int(os.getenv("MT5_MAX_GROUP_POS", "2"))
CORR_THRESHOLD = float(os.getenv("MT5_CORR_THRESHOLD", "0.6"))

# Static fallback groups (used when correlation data is unavailable).
STATIC_GROUPS = {
    "equity_indices": {"US500", "US100", "US30", "GER40", "UK100", "JPN225",
                       "AUS200", "HK50", "FRA40", "NAS100"},
    "precious_metals": {"XAUUSD", "XAGUSD", "XPTUSD"},
    "energy": {"CRUDE", "BRENT", "NATGAS", "GASOLINE"},
    "crypto": {"BTCUSD", "ETHUSD", "BNBUSD"},
    "usd_majors": {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF",
                   "USDJPY"},
    "jpy_crosses": {"EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY"},
    "eur_crosses": {"EURGBP", "EURAUD", "EURCAD", "EURCHF"},
    "softs": {"COFFEE", "COCOA", "SUGAR", "WHEAT", "CORN", "SOYBEANS"},
    "industrial": {"COPPER"},
}


def _log(m):
    mt5_log.emit("corr", m)


class CorrelationGuard:
    """Caps risk within correlated groups — the rail the backtest can't see."""

    def __init__(self, bridge):
        self.bridge = bridge
        self._group_of = {}          # our_symbol -> group name
        self._built = None           # timestamp of last build

    # ---------- grouping ----------
    def _static_group(self, sym):
        for g, members in STATIC_GROUPS.items():
            if sym in members:
                return g
        return f"solo:{sym}"

    def _build_groups(self, symbols):
        """Group symbols by REAL rolling correlation of daily returns; fall back
        to the static map when data is thin. Rebuilt at most once an hour."""
        now = datetime.now(timezone.utc)
        if self._built and (now - self._built).total_seconds() < 3600:
            return
        rets = {}
        for s in symbols:
            try:
                df = self.bridge.candles(s, "1d", 120)
                if df.empty or len(df) < 60:
                    continue
                r = df["close"].pct_change().dropna().values[-60:]
                if len(r) >= 50:
                    rets[s] = r
            except Exception:  # noqa: BLE001
                continue
        groups = {}
        assigned = {}
        syms = list(rets.keys())
        for i, a in enumerate(syms):
            if a in assigned:
                continue
            gname = f"grp{len(groups)}"
            members = {a}
            for b in syms[i + 1:]:
                if b in assigned:
                    continue
                n = min(len(rets[a]), len(rets[b]))
                if n < 40:
                    continue
                c = np.corrcoef(rets[a][-n:], rets[b][-n:])[0, 1]
                if not np.isnan(c) and abs(c) >= CORR_THRESHOLD:
                    members.add(b)
            for m in members:
                assigned[m] = gname
            groups[gname] = members
        # any symbol without correlation data -> static group
        for s in symbols:
            if s not in assigned:
                assigned[s] = self._static_group(s)
        self._group_of = assigned
        self._built = now
        big = {g: len(m) for g, m in groups.items() if len(m) > 1}
        if big:
            _log(f"correlation groups rebuilt: {len(groups)} groups, "
                 f"clusters={big}")

    def group_of(self, sym):
        return self._group_of.get(sym) or self._static_group(sym)

    # ---------- the cap ----------
    def allows(self, our_symbol, new_risk_usd, balance, symbols_universe):
        """(allowed, reason). Blocks if this trade would push the correlated
        group over its risk or position cap."""
        if mt5 is None or not balance:
            return True, "no data"
        self._build_groups(symbols_universe)
        g = self.group_of(our_symbol)

        # sum existing risk + positions in the SAME group (all books, all magics)
        group_risk = 0.0
        group_pos = 0
        for p in (mt5.positions_get() or []):
            # map broker symbol back to our name
            our = None
            for k, v in self.bridge.symbols.items():
                if v == p.symbol:
                    our = k
                    break
            if our is None or self.group_of(our) != g:
                continue
            group_pos += 1
            info = mt5.symbol_info(p.symbol)
            if info and p.sl and info.trade_tick_size:
                group_risk += (abs(p.price_open - p.sl) / info.trade_tick_size
                               * info.trade_tick_value * p.volume)

        if group_pos >= MAX_GROUP_POSITIONS:
            return False, (f"correlation cap: {group_pos} positions already in "
                           f"group '{g}' (max {MAX_GROUP_POSITIONS})")
        total_pct = (group_risk + new_risk_usd) / balance * 100
        if total_pct > MAX_GROUP_RISK_PCT:
            return False, (f"correlation cap: group '{g}' risk would be "
                           f"{total_pct:.1f}% (max {MAX_GROUP_RISK_PCT:.0f}%)")
        return True, "ok"
