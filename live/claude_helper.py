"""
claude_helper.py — Claude Code as a near-real-time HELPER (not the trigger).

Why a helper, not the brain: Claude (even via the Claude Code CLI, which uses
your subscription — NOT the paid API) takes a few SECONDS per answer. That's far
too slow to pull the trigger on a scalp that needs millisecond reactions. So the
fast MATH rules do the trading; Claude WATCHES and EXPLAINS in near-real-time.

Every INTERVAL seconds this:
  1. Builds a short snapshot of what just happened (equity, recent trades,
     what each strategy is currently looking at).
  2. Calls the `claude` CLI (claude -p "...") to get a 2-3 sentence read on
     what's going on and whether anything looks off.
  3. Stores the reply so the dashboard can show it.

It runs in its own thread and never blocks the trading engine. If the `claude`
command isn't available, it degrades gracefully (the dashboard just shows a
note that the helper is offline).
"""

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

# Resolve the full path to the `claude` CLI once. On Windows this finds
# claude.CMD; subprocess can't run a bare "claude" for a .CMD file, so we need
# the resolved path (and to run it via the shell on Windows).
CLAUDE_BIN = shutil.which("claude")
IS_WINDOWS = os.name == "nt"


class ClaudeHelper:
    def __init__(self, engine, interval_seconds=180):
        self.engine = engine
        self.interval = interval_seconds
        self.latest = {
            "text": "Claude helper starting… (first read within a few minutes)",
            "at": None,
            "available": True,
        }
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------
    def _build_prompt(self, snap):
        """Turn the engine snapshot into a compact prompt for Claude."""
        lines = ["You are watching a PAPER (fake-money) trading system in real "
                 "time. Give a SHORT read: 2-3 sentences max, plain language, "
                 "for a beginner. Say what's happening and flag anything notable "
                 "(a strategy bleeding from costs, a good/bad streak, choppy "
                 "market). Do NOT give financial advice. Be concise.\n"]
        for s in snap["strategies"]:
            d = s["equity"] - s["start_capital"]
            lines.append(
                f"- {s['label']}: equity ${s['equity']:.2f} "
                f"({'+' if d>=0 else ''}{d:.2f}), {s['stats']['trades']} trades, "
                f"win rate {s['stats']['win_rate']}%, "
                f"PF {s['stats']['profit_factor']}, "
                f"cost paid ${s['stats']['cost_paid']:.2f}, "
                f"{len(s['positions'])} open.")
            for sym, b in (s.get("brain") or {}).items():
                lines.append(f"    {sym}: {b.get('waiting_for','')}")
        recent = []
        for s in snap["strategies"]:
            for t in s["recent_trades"][:3]:
                recent.append(f"{s['key']} {t['symbol']} {t['reason']} "
                              f"${t['pnl']:+.3f}")
        if recent:
            lines.append("Recent trades: " + "; ".join(recent[:8]))
        return "\n".join(lines)

    def _call_claude(self, prompt):
        """Run `claude -p` and return its text, or an error string.

        Windows note: `claude` is a .CMD, which subprocess can't launch as a
        bare name. We use the resolved full path and run via the shell on
        Windows so the .CMD is executed correctly.
        """
        if not CLAUDE_BIN:
            return None   # CLI genuinely not installed
        try:
            if IS_WINDOWS:
                # Quote the path and pass the prompt as a single argument.
                r = subprocess.run(
                    f'"{CLAUDE_BIN}" -p {json.dumps(prompt)}',
                    capture_output=True, text=True, timeout=120, shell=True)
            else:
                r = subprocess.run(
                    [CLAUDE_BIN, "-p", prompt],
                    capture_output=True, text=True, timeout=120, shell=False)
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            return "(Claude took too long this round; will try again.)"
        if r.returncode != 0:
            return f"(Claude error: {(r.stderr or '').strip()[:150]})"
        return r.stdout.strip()

    def _loop(self):
        # Small initial delay so the engine has some data first.
        time.sleep(20)
        while self._running:
            try:
                snap = self.engine.snapshot()
                prompt = self._build_prompt(snap)
                text = self._call_claude(prompt)
                if text is None:
                    self.latest = {
                        "text": "Claude helper is offline — the `claude` command "
                                "wasn't found. Install Claude Code + sign in to "
                                "enable live commentary.",
                        "at": datetime.now(timezone.utc).isoformat(),
                        "available": False,
                    }
                    # No point retrying fast if the CLI is missing.
                    time.sleep(max(self.interval, 300))
                    continue
                self.latest = {
                    "text": text,
                    "at": datetime.now(timezone.utc).isoformat(),
                    "available": True,
                }
            except Exception as exc:  # noqa: BLE001 - never kill the thread
                self.latest = {"text": f"(helper hiccup: {exc})",
                               "at": None, "available": True}
            # Wait for the next round.
            for _ in range(self.interval):
                if not self._running:
                    return
                time.sleep(1)

    def snapshot(self):
        return self.latest
