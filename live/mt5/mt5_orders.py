"""
mt5_orders.py — Order execution with MANDATORY broker-side SL/TP.

Every market order sent here carries a stop-loss AND take-profit attached at the
broker, so your protection survives even if this script crashes. Full logging of
every request and response (including rejections). Includes position sizing from
a risk % of account, position close, and stop-modify (for trailing stops).

DEMO ONLY — this module assumes the bridge already verified a demo account.
"""

import time
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


def _log(m):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [order] {m}", flush=True)


# Retcodes that mean "requote/price moved" — worth a retry.
_RETRY_CODES = set()
if mt5 is not None:
    _RETRY_CODES = {mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_CHANGED,
                    mt5.TRADE_RETCODE_PRICE_OFF, mt5.TRADE_RETCODE_TIMEOUT}


def _round_to_step(volume, step, vmin, vmax):
    """Clamp/round a lot size to the symbol's allowed step/min/max."""
    if step > 0:
        volume = round(round(volume / step) * step, 8)
    return max(vmin, min(vmax, volume))


def lots_for_risk(broker_symbol, account_equity, risk_pct, entry, stop):
    """Compute a lot size so that hitting `stop` loses ~risk_pct of equity.

    Uses the symbol's tick value/size so it works across forex, metals, stocks.
    Returns a broker-valid lot size (clamped to step/min/max), or 0 if invalid.
    """
    info = mt5.symbol_info(broker_symbol)
    if info is None or entry <= 0 or stop <= 0:
        return 0.0
    risk_money = account_equity * (risk_pct / 100.0)
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return 0.0
    # Value of a 1.0-lot move of `stop_dist` price units:
    #   (stop_dist / tick_size) * tick_value  == loss per 1 lot
    tick_size = info.trade_tick_size or info.point
    tick_value = info.trade_tick_value
    if not tick_size or not tick_value:
        return 0.0
    loss_per_lot = (stop_dist / tick_size) * tick_value
    if loss_per_lot <= 0:
        return 0.0
    raw_lots = risk_money / loss_per_lot
    return _round_to_step(raw_lots, info.volume_step,
                          info.volume_min, info.volume_max)


def market_order(broker_symbol, side, lots, sl_price, tp_price,
                 comment="", deviation=20, retries=3):
    """Send a market BUY/SELL with SL + TP attached. side in {'buy','sell'}.

    Returns a dict with the outcome (ok, retcode, order, price, ...). Fully
    logs the request and the broker's response, including rejections.
    """
    if mt5 is None:
        return {"ok": False, "error": "MetaTrader5 not installed"}
    info = mt5.symbol_info(broker_symbol)
    if info is None:
        return {"ok": False, "error": f"unknown symbol {broker_symbol}"}
    if lots <= 0:
        return {"ok": False, "error": "lots <= 0 (risk too small / bad stop)"}

    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL

    for attempt in range(1, retries + 1):
        tick = mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            return {"ok": False, "error": "no tick"}
        price = tick.ask if side == "buy" else tick.bid
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": float(lots),
            "type": order_type,
            "price": price,
            "sl": float(sl_price),
            "tp": float(tp_price),
            "deviation": deviation,
            "magic": 770001,           # tags our orders
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _filling_mode(broker_symbol),
        }
        _log(f"REQUEST buy/sell={side} {broker_symbol} lots={lots} @~{price} "
             f"SL={sl_price} TP={tp_price} (attempt {attempt})")
        res = mt5.order_send(req)
        if res is None:
            _log(f"order_send returned None: {mt5.last_error()}")
            time.sleep(0.5)
            continue
        _log(f"RESPONSE retcode={res.retcode} comment='{res.comment}' "
             f"order={res.order} deal={res.deal} price={res.price}")
        if res.retcode == mt5.TRADE_RETCODE_DONE:
            return {"ok": True, "retcode": res.retcode, "order": res.order,
                    "deal": res.deal, "price": res.price, "lots": lots,
                    "sl": sl_price, "tp": tp_price}
        if res.retcode in _RETRY_CODES and attempt < retries:
            time.sleep(0.4)
            continue
        return {"ok": False, "retcode": res.retcode, "comment": res.comment}
    return {"ok": False, "error": "exhausted retries"}


def _filling_mode(broker_symbol):
    """Pick a filling mode the symbol supports (brokers differ)."""
    info = mt5.symbol_info(broker_symbol)
    if info is None:
        return mt5.ORDER_FILLING_IOC
    mode = info.filling_mode
    # filling_mode is a bitmask of supported modes.
    if mode & 1:      # SYMBOL_FILLING_FOK
        return mt5.ORDER_FILLING_FOK
    if mode & 2:      # SYMBOL_FILLING_IOC
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def close_position(position, deviation=20):
    """Close an open position (a MT5 position object) at market."""
    side = "sell" if position.type == mt5.ORDER_TYPE_BUY else "buy"
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY \
        else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(position.symbol)
    price = tick.bid if side == "sell" else tick.ask
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": position.symbol,
        "volume": position.volume, "type": order_type,
        "position": position.ticket, "price": price, "deviation": deviation,
        "magic": 770001, "comment": "close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _filling_mode(position.symbol),
    }
    _log(f"CLOSE {position.symbol} ticket={position.ticket} vol={position.volume}")
    res = mt5.order_send(req)
    ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
    _log(f"close result: retcode={res.retcode if res else None}")
    return {"ok": ok, "retcode": res.retcode if res else None}


def modify_stop(position, new_sl, new_tp=None):
    """Move a position's SL (and optionally TP) — used for trailing stops."""
    req = {
        "action": mt5.TRADE_ACTION_SLTP, "symbol": position.symbol,
        "position": position.ticket, "sl": float(new_sl),
        "tp": float(new_tp if new_tp is not None else position.tp),
    }
    res = mt5.order_send(req)
    ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
    _log(f"modify SL {position.symbol} -> {new_sl} : "
         f"retcode={res.retcode if res else None}")
    return {"ok": ok}


def open_positions(magic=770001):
    """Our open positions (filtered by magic number)."""
    poss = mt5.positions_get()
    if poss is None:
        return []
    return [p for p in poss if p.magic == magic]
