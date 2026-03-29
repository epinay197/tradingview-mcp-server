# TradingView MCP Server (Remote / Cloud)

Runs headless Chromium in the cloud. Both computers connect via a single HTTPS URL — no local browser needed.

## Deploy to Railway (one-time, ~2 minutes)

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/epinay197/tradingview-mcp-server)

1. Sign in at [railway.app](https://railway.app) with your GitHub account
2. Click the button above → Railway auto-builds and deploys the Docker image
3. Copy your deployment URL (e.g. `https://tradingview-mcp-server.up.railway.app`)

### Optional env vars (set in Railway dashboard → Variables)
| Variable | Purpose | Default |
|---|---|---|
| `TV_URL` | Starting TradingView chart URL | `https://www.tradingview.com/chart/` |
| `MCP_API_KEY` | Protect the endpoint (both computers must set it) | *(none)* |
| `PORT` | HTTP port | `8000` |

## Configure Claude Code on each computer

```bash
python setup_computer.py https://YOUR-APP.up.railway.app/sse
```

Restart Claude Code. The `tradingview` MCP tools are now available from any computer.

## Auto-deploy on push

Add `RAILWAY_TOKEN` as a GitHub Actions secret (Railway dashboard → Account → Tokens) and every push to `main` redeploys automatically.

## Available MCP tools

| Tool | Description |
|---|---|
| `tv_screenshot` | Chart screenshot (PNG) |
| `tv_get_symbol` | Current symbol + price from title |
| `tv_read_indicators` | All visible indicator values |
| `tv_read_price_data` | OHLCV data |
| `tv_navigate` | Change symbol or URL |
| `tv_execute_js` | Run custom JavaScript |
| `tv_read_watchlist` | Watchlist symbols & prices |
| `tv_read_strategy_results` | Pine Script backtest results |
| `tv_status` | Server + browser health |
