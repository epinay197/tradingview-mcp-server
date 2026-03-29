"""
TradingView Remote MCP Server
FastAPI + Server-Sent Events transport — runs in cloud, both computers connect via URL.
Uses Playwright headless Chromium so no local browser is needed.
"""
import asyncio
import base64
import json
import logging
import os
from typing import Any

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent, ImageContent
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tv-remote-mcp")

# ── Config ────────────────────────────────────────────────────────────────────
PORT     = int(os.getenv("PORT", "8000"))
TV_URL   = os.getenv("TV_URL", "https://www.tradingview.com/chart/")
TV_USER  = os.getenv("TV_USERNAME", "")
TV_PASS  = os.getenv("TV_PASSWORD", "")
API_KEY  = os.getenv("MCP_API_KEY", "")          # optional auth for the MCP endpoint

# ── Browser singleton ─────────────────────────────────────────────────────────
_pw       = None
_browser: Browser | None  = None
_context: BrowserContext | None = None
_page:    Page | None     = None
_lock     = asyncio.Lock()
_ready    = False


async def _launch_browser():
    global _pw, _browser, _context, _page, _ready
    logger.info("Launching headless Chromium …")
    _pw      = await async_playwright().start()
    _browser = await _pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-setuid-sandbox",
            "--window-size=1920,1080",
        ],
    )
    _context = await _browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    _page = await _context.new_page()
    await _goto_tradingview()
    _ready = True
    logger.info("Browser ready.")


async def _goto_tradingview():
    """Navigate to TradingView and wait for the chart to be interactive."""
    logger.info("Navigating to TradingView …")
    await _page.goto(TV_URL, wait_until="domcontentloaded", timeout=60_000)

    # Dismiss any cookie/GDPR banner
    try:
        btn = _page.locator("button:has-text('Accept'), button:has-text('I agree'), button:has-text('Got it')")
        await btn.first.click(timeout=5_000)
    except Exception:
        pass

    # Wait for chart canvas to appear
    try:
        await _page.wait_for_selector("canvas", timeout=20_000)
        await _page.wait_for_timeout(3_000)   # let indicators render
    except Exception:
        logger.warning("Chart canvas not detected — continuing anyway")


async def get_page() -> Page:
    """Return a live TradingView page, re-launching if needed."""
    global _ready
    async with _lock:
        if not _ready or _page is None or _page.is_closed():
            await _launch_browser()
        # If page navigated away from TV, bring it back
        current_url = _page.url
        if "tradingview.com" not in current_url:
            logger.warning("Page drifted to %s — re-navigating", current_url)
            await _goto_tradingview()
        return _page


# ── MCP Server ────────────────────────────────────────────────────────────────
mcp = Server("tradingview-remote")


@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="tv_screenshot",
            description="Screenshot of the current TradingView chart (base64 PNG).",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="tv_get_symbol",
            description="Current symbol, timeframe, and price from the chart title.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="tv_read_indicators",
            description="All visible indicator values from the chart legend / status bar.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="tv_read_price_data",
            description="Current OHLCV data from the chart.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="tv_navigate",
            description="Navigate the chart to a different symbol or URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "TradingView symbol e.g. 'BINANCE:BTCUSDT' or 'MYM1!'",
                    },
                    "url": {
                        "type": "string",
                        "description": "Full TradingView chart URL (overrides symbol)",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="tv_execute_js",
            description="Execute JavaScript in the TradingView page context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "JavaScript to execute"}
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="tv_read_watchlist",
            description="Symbols and prices from the TradingView watchlist panel.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="tv_read_strategy_results",
            description="Pine Script strategy tester results if a strategy is loaded.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="tv_status",
            description="Server status: uptime, current page URL, browser health.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


async def _eval(page: Page, expr: str) -> Any:
    result = await page.evaluate(expr)
    return result


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
    try:
        page = await get_page()

        if name == "tv_screenshot":
            png = await page.screenshot(full_page=False)
            return [ImageContent(type="image", data=base64.b64encode(png).decode(), mimeType="image/png")]

        if name == "tv_get_symbol":
            result = await _eval(page, """
            (() => {
                const title = document.title;
                const toolbar = (document.querySelector(
                    '[class*="chart-controls"], [class*="header-toolbar"]'
                ) || {innerText:''}).innerText.substring(0, 300);
                return JSON.stringify({ title, toolbar });
            })()
            """)
            return [TextContent(type="text", text=str(result))]

        if name == "tv_read_indicators":
            result = await _eval(page, """
            (() => {
                const seen = new Set();
                const out = [];
                document.querySelectorAll(
                    '[class*="legend"],[class*="statusLine"],[class*="valuesWrapper"]'
                ).forEach(el => {
                    const t = el.innerText.trim();
                    if (t && t.length > 2 && t.length < 500 && !seen.has(t)) {
                        seen.add(t); out.push(t);
                    }
                });
                return JSON.stringify(out.slice(0, 15));
            })()
            """)
            return [TextContent(type="text", text=str(result))]

        if name == "tv_read_price_data":
            result = await _eval(page, """
            (() => {
                const vals = [];
                document.querySelectorAll(
                    '[class*="valuesWrapper"] [class*="value"],[class*="legendValue"],[class*="ohlcValue"]'
                ).forEach(el => vals.push(el.innerText.trim()));
                const dw = [];
                document.querySelectorAll('[class*="dataWindow"] [class*="row"],[class*="item"]')
                    .forEach(el => { const t = el.innerText.trim(); if (t) dw.push(t); });
                return JSON.stringify({ legend_values: vals.slice(0,20), data_window: dw.slice(0,20) });
            })()
            """)
            return [TextContent(type="text", text=str(result))]

        if name == "tv_navigate":
            url  = arguments.get("url", "")
            sym  = arguments.get("symbol", "")
            if url:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            elif sym:
                encoded = sym.replace(":", "%3A")
                await page.goto(
                    f"https://www.tradingview.com/chart/?symbol={encoded}",
                    wait_until="domcontentloaded", timeout=30_000,
                )
            await page.wait_for_timeout(3_000)
            title = await page.title()
            return [TextContent(type="text", text=f"Navigated to: {title}")]

        if name == "tv_execute_js":
            code   = arguments.get("code", "")
            result = await page.evaluate(code)
            return [TextContent(type="text", text=str(result))]

        if name == "tv_read_watchlist":
            result = await _eval(page, """
            (() => {
                const items = [];
                document.querySelectorAll('[class*="watchlist"] [class*="row"],[class*="symbolRow"]')
                    .forEach(el => { const t = el.innerText.trim(); if (t) items.push(t); });
                return items.length ? JSON.stringify(items.slice(0,30)) : 'Watchlist not visible';
            })()
            """)
            return [TextContent(type="text", text=str(result))]

        if name == "tv_read_strategy_results":
            result = await _eval(page, """
            (() => {
                const tester = document.querySelector('[class*="strategyReport"],[data-name="backtesting"]');
                if (!tester) return JSON.stringify({status:'Strategy tester not visible'});
                const rows = [];
                tester.querySelectorAll('tr,[class*="row"]').forEach(el => rows.push(el.innerText.trim()));
                return JSON.stringify({strategy_results: rows.slice(0,50)});
            })()
            """)
            return [TextContent(type="text", text=str(result))]

        if name == "tv_status":
            url    = page.url
            title  = await page.title()
            closed = page.is_closed()
            return [TextContent(type="text", text=json.dumps({
                "server": "tradingview-remote-mcp",
                "browser_connected": _browser is not None and _browser.is_connected(),
                "page_closed": closed,
                "current_url": url,
                "page_title": title,
                "ready": _ready,
            }, indent=2))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error("Tool %s failed: %s", name, e, exc_info=True)
        return [TextContent(type="text", text=f"ERROR: {e}")]


# ── Starlette App ─────────────────────────────────────────────────────────────
sse = SseServerTransport("/messages/")


async def handle_sse(request: Request) -> Response:
    # Optional API key check
    if API_KEY:
        key = request.headers.get("x-api-key", request.query_params.get("api_key", ""))
        if key != API_KEY:
            return Response("Unauthorized", status_code=401)
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp.run(streams[0], streams[1], mcp.create_initialization_options())
    return Response()


async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "ready": _ready,
        "page_url": _page.url if _page else None,
    })


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/sse", handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ]
)


async def startup():
    asyncio.create_task(_launch_browser())

app.add_event_handler("startup", startup)


if __name__ == "__main__":
    uvicorn.run("server_remote:app", host="0.0.0.0", port=PORT, log_level="info")
