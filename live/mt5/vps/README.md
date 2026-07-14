# Run the bot 24/7 on an Ubuntu VPS

The MT5 Python API is Windows-only, so we run the Windows MT5 terminal **and** a
Windows Python **inside Wine** on your Ubuntu box. The trading code is unchanged
— `import MetaTrader5` works because it runs under Wine's Python.

**Account stays DEMO.** The bot refuses to start on a real account, here as on
the laptop. This is paper trading for evidence, not real money.

---

## One-time setup — run the stages in order

Each script verifies itself and tells you the next one. If a stage fails, stop
and paste the output back — don't push past a red gate (especially stage 3).

```bash
# get the code
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/Aymenjallouli/tradingview.git
cd tradingview/live/mt5/vps
chmod +x *.sh

./1_system.sh          # Wine + fake screen (Xvfb) + VNC helper
./2_python.sh          # Windows Python 3.11 inside Wine
./3_smoke.sh           # THE GATE: numpy/pandas/MetaTrader5 import under Wine?
./4_mt5_install.sh     # install the MT5 terminal
./4b_login.sh          # ONE-time: log in over VNC + enable Algo Trading
./5_install_service.sh # run on boot, restart on crash (systemd)
./6_check.sh           # confirm it's trading
```

The only stage where you need to *see* a screen is **4b** — you VNC in once to
log MT5 into the demo and tick "Allow algorithmic trading". Everything after is
headless and automatic, including across reboots.

---

## After it's running

```bash
journalctl -u mt5bots.service -f      # live log of the books
./6_check.sh                          # broker audit: are we making money?
sudo systemctl restart mt5bots        # restart everything
sudo systemctl stop mt5bots           # stop trading
```

**View a dashboard** from your own computer (nothing is exposed to the internet):
```bash
# on your computer:
ssh -L 8800:localhost:8800 ubuntu@<vps-ip>
# on the VPS:
cd ~/tradingview/live/mt5 && wine python mt5_hub.py
# then open http://localhost:8800 in your browser
```

---

## Secrets (optional — Telegram signals)

Never committed. Create `~/tradingview/live/mt5/.env` on the VPS only:
```
MT5_TG_TOKEN=123456:ABC...
MT5_TG_CHAT=@your_channel
```
`.env` is gitignored. Your MT5 password is typed into the terminal at stage 4b
and lives only in the terminal's own saved profile — never in the code.

---

## Updating the code later

```bash
cd ~/tradingview && git pull
sudo systemctl restart mt5bots
```

## If something breaks
- **Stage 3 numpy/pandas error** → the one real risk. Stop; we switch to the
  native-Linux + bridge approach. Don't work around it.
- **Stage 4 "terminal64.exe not found"** → the installer URL changed; pass a
  fresh one: `MT5_URL="https://..." ./4_mt5_install.sh`.
- **Books up but no trades** → markets may be closed, or MT5 isn't logged in.
  Re-run `./4b_login.sh` and confirm the balance shows.
