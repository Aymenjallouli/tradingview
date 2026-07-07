# Deploy Tonight — quick guide for your pm2 VPS

You already have a VPS running `pm2` (with `site-bot`) and `claude` logged in.
That's the easiest setup — we'll add this trader as a second pm2 process. No
Docker needed. It'll run overnight, survive reboots, and the Claude live
commentary will work (because `claude` is authenticated on your box).

## Steps (run on the VPS as the `ubuntu` user)

```bash
# 1. Get the code onto the VPS. Easiest: copy the whole `live/` folder up.
#    From your LOCAL machine:
scp -r "c:/Users/AymenJallouli/Desktop/tradingview/live" ubuntu@YOUR_VPS_IP:~/rt-trader
#    (or use git if the project is in a repo)

# 2. On the VPS: set up a Python environment.
cd ~/rt-trader
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Start it under pm2 (alongside site-bot).
pm2 start ecosystem.config.js
pm2 save                    # so it comes back after a reboot

# 4. Watch it.
pm2 list                    # should show rt-trader "online"
pm2 logs rt-trader          # live log — you'll see candle checks + trades
```

## See the dashboard

The dashboard runs on port **8010**. Two ways to view it:

**Option A — SSH tunnel (safest, nothing exposed):**
```bash
# From your LOCAL machine:
ssh -L 8010:localhost:8010 ubuntu@YOUR_VPS_IP
# then open http://localhost:8010 in your browser
```

**Option B — open the port** (only if you add a firewall + password/proxy):
```bash
sudo ufw allow 8010     # then visit http://YOUR_VPS_IP:8010
```
⚠️ Don't expose it raw long-term — it's a dashboard, not hardened for the
public internet.

## Tomorrow — check the progress

```bash
pm2 logs rt-trader --lines 100     # what happened overnight
```
Or just open the dashboard. Look at each strategy's **equity vs $50** and
**number of trades**. Bring the numbers back and we'll judge honestly:
- Which strategy made/lost money?
- Did the scalper bleed from costs (as the backtest predicted)?
- Is anything worth keeping / dropping?

## Handy pm2 commands

```bash
pm2 restart rt-trader     # restart after a config change
pm2 stop rt-trader        # pause it
pm2 delete rt-trader      # remove it from pm2
pm2 monit                 # live CPU/memory for all processes
```

## Reset the experiment (fresh $50 for each strategy)

```bash
cd ~/rt-trader
rm -f live_trades.db      # deletes all trades; a fresh DB is made on restart
pm2 restart rt-trader
```

## Notes

- **It's all paper money.** No broker, no keys, no real funds. Safe to run.
- **The scalper trades often; trend/forex trade rarely.** All normal.
- **Claude commentary** updates every ~3 minutes (uses your logged-in `claude`).
- If you change `ecosystem.config.js`, run `pm2 restart rt-trader` to apply it.
