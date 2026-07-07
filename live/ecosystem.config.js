// pm2 config for the real-time paper trader.
//
// You already run pm2 (site-bot). This adds the trader as a second pm2 process,
// kept alive + auto-restarted the same way. Because `claude` is authenticated
// on your VPS, the Claude live-commentary helper will work here too.
//
// Deploy (from inside the `live/` folder on the VPS):
//   python3 -m venv .venv
//   .venv/bin/pip install -r requirements.txt
//   pm2 start ecosystem.config.js
//   pm2 save                      # remember it across reboots
//   pm2 logs rt-trader            # watch it
//
// The dashboard will be at http://<vps-ip>:8010 (open the port / use an SSH
// tunnel — see README). Data persists in live_trades.db in this folder.

module.exports = {
  apps: [
    {
      name: "rt-trader",
      // Use the venv's python so dependencies resolve.
      script: "./.venv/bin/python",
      args: "app.py",
      cwd: __dirname,
      interpreter: "none",          // run the script directly, not via node
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      env: {
        STARTING_CAPITAL: "50",
        ENABLED: "trend,scalp,forex",
        CRYPTO_SYMBOLS: "BTCUSDT,ETHUSDT",
        FOREX_SYMBOLS: "USDJPY=X,EURUSD=X",
        DASHBOARD_HOST: "0.0.0.0",  // reachable on the VPS (firewall it!)
        DASHBOARD_PORT: "8010",
        DATABASE_PATH: "live_trades.db",
        // Claude live-commentary helper needs HOME so the `claude` CLI can find
        // its saved login at ~/.claude (same as your site-bot setup). Set these
        // to match YOUR VPS user. On your box HOME is /home/ubuntu.
        HOME: "/home/ubuntu",
        // If `claude` isn't on pm2's PATH, set the full path here. Find it on
        // the VPS with:  which claude
        // CLAUDE_BIN: "/home/ubuntu/.npm-global/bin/claude",
      },
    },
  ],
};
