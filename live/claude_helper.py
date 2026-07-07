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
        self._enabled = True     # use the .enabled property below
        self._running = False
        self._thread = None
        self.latest = {
            "text": "Claude helper starting… (first read within a few minutes)",
            "at": None,
            "available": True,
        }

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, val):
        self._enabled = val
        if not val:
            # Show the off-state immediately so the panel isn't confusing.
            self.latest = {
                "text": "Live commentary is off — all Claude budget goes to the "
                        "🤖 Claude Trader (below), which decides on real trades "
                        "every 2 hours.",
                "at": None, "available": True}

    def start(self):
        if not self.enabled:
            self.latest = {"text": "Live commentary is off (saving Claude "
                           "rate limit). The Claude Trader still runs.",
                           "at": None, "available": True}
            return
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

        # Arb-monitor funnel (if running) so Claude can reference it.
        arb = snap.get("arb")
        if arb:
            f = arb["funnel"]
            lines.append(
                f"Arb monitor funnel: {f['raw_gaps']} raw gaps seen -> "
                f"{f['net_positive']} net-positive after costs -> "
                f"{f['survived']} survived 2.5s latency "
                f"(hypothetical P&L ${arb['hypo_pnl']:.2f}).")
        return "\n".join(lines)

    def _call_claude(self, prompt):
        """Run `claude -p` and return its text, or an error string.

        Env note: under pm2 the process may not inherit your interactive shell's
        environment, so `claude` can't find its auth (~/.claude) or PATH. We
        pass a full environment with HOME set so the CLI locates its credentials
        the same way it does in your terminal. You can also set CLAUDE_BIN or
        extra vars in ecosystem.config.js if your setup needs it.

        Windows note: `claude` is a .CMD, which subprocess can't launch as a
        bare name, so we run it via the shell there.
        """
        claude_bin = os.getenv("CLAUDE_BIN") or CLAUDE_BIN
        if not claude_bin:
            return None   # CLI genuinely not installed / not on PATH

        # Build an environment the CLI can authenticate in. Supported ways:
        #   1) CLAUDE_CODE_OAUTH_TOKEN in .env  <-- what your site-bot uses
        #      (Claude Code subscription token, not the paid API). Passed through.
        #   2) Your logged-in session: claude reads ~/.claude, found via HOME.
        #   3) ANTHROPIC_API_KEY / CLAUDE_API_KEY token, if you use those.
        # config.py already loaded .env, so os.environ has whatever you set.
        env = dict(os.environ)
        if "HOME" not in env and "USERPROFILE" in env:
            env["HOME"] = env["USERPROFILE"]
        if "ANTHROPIC_API_KEY" not in env and env.get("CLAUDE_API_KEY"):
            env["ANTHROPIC_API_KEY"] = env["CLAUDE_API_KEY"]
        # CLAUDE_CODE_OAUTH_TOKEN is already in env if set in .env — the claude
        # CLI reads it directly. Nothing extra to do; it's passed through here.

        try:
            if IS_WINDOWS:
                r = subprocess.run(
                    f'"{claude_bin}" -p {json.dumps(prompt)}',
                    capture_output=True, text=True, timeout=120,
                    shell=True, env=env, stdin=subprocess.DEVNULL)
            else:
                r = subprocess.run(
                    [claude_bin, "-p", prompt],
                    capture_output=True, text=True, timeout=120,
                    shell=False, env=env, stdin=subprocess.DEVNULL)
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            return "(Claude took too long this round; will try again.)"
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()[:200]
            return f"(Claude error: {err})"
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
