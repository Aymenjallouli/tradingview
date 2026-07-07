# Real-time paper trading engine — container image.
# Small, single-process: runs the engine + dashboard together.

FROM python:3.12-slim

# Don't buffer stdout so logs stream to `docker logs` in real time.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first (layer caching: deps rarely change).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app.
COPY . .

# The database lives in /data (mounted as a volume) so trades SURVIVE
# container restarts / redeploys.
ENV DATABASE_PATH=/data/live_trades.db
VOLUME ["/data"]

# Bind the dashboard to all interfaces inside the container; you map the port
# out with -p. (Put it behind a firewall / reverse proxy on a real VPS.)
ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8000
EXPOSE 8000

# Simple healthcheck so Docker/monitors know it's alive.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
  CMD python -c "import urllib.request,sys; \
  sys.exit(0 if __import__('json').load(urllib.request.urlopen('http://127.0.0.1:8000/healthz'))['ok'] else 1)"

CMD ["python", "app.py"]
