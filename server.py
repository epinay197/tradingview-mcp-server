"""
TradingView MCP Server - Connects to Chrome via CDP to read TradingView charts.
Provides screenshot, DOM reading, and JavaScript execution capabilities.
"""

import asyncio
import base64
import json
import logging
import sys
from io import BytesIO
from typing import Any

import websockets
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("tradingview-mcp")

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222

server = Server("tradingview-mcp")


async def get_ws_endpoint(target_url_fragment: str = "tradingview.com") -> str | None:
    """Find the WebSocket debugger URL for a TradingView tab."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://{CDP_HOST}:{CDP_PORT}/json")
        tabs = resp.json()
        for tab in tabs:
            if target_url_fragment in tab.get("url", ""):
                return tab.get("webSocketDebuggerUrl")
        # Return first page tab if no TV tab found
        for tab in tabs:
            if tab.get("type") == "page":
                return tab.get("webSocketDebuggerUrl")
    return None


async def cdp_command(ws_url: str, method: str, params: dict = None) -> dict:
    """Send a CDP command and return the result."""
    async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
        msg = {"id": 1, "method": method, "params": params or {}}
        await ws.send(json.dumps(msg))
        while True:
            response = json.loads(await ws.recv())
            if response.get("id") == 1:
                return response.get("result", {})


async def cdp_evaluate(ws_url: str, expression: str) -> Any:
    """Evaluate JavaScript in the page context."""
    result = await cdp_command(ws_url, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True
    })
    remote = result.get("result", {})
    if remote.get("type") == "undefined":
        return None
    return remote.get("value", remote.get("description", str(remote)))


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="tv_screenshot",
            description="Take a screenshot of the current TradingView chart. Returns a base64 PNG image.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="tv_get_symbol",
            description="Get the current symbol, timeframe, and basic chart info from TradingView.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="tv_read_indicators",
            description="Read all visible indicator values and overlays from the TradingView chart legend/status area.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="tv_read_price_data",
            description="Read current price, OHLC of last N candles, and volume data from the chart.",
            inputSchema={
                "type": "object",
                "properties": {
                    "num_candles": {
                        "type": "integer",
                        "description": "Number of recent candles to read (default 20)",
                        "default": 20
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="tv_execute_js",
            description="Execute arbitrary JavaScript on the TradingView page. Use for custom data extraction.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "JavaScript code to execute in the page context"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="tv_read_orderbook",
            description="Read the DOM/order flow panel if visible on the TradingView chart.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="tv_read_strategy_results",
            description="Read Pine Script strategy tester results (performance, trades list) if a strategy is loaded.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="tv_list_tabs",
            description="List all open Chrome tabs (useful to find TradingView tabs).",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="tv_read_alerts",
            description="Read any alert popups or notification messages on the TradingView page.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="tv_read_watchlist",
            description="Read symbols and prices from the TradingView watchlist panel.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
    try:
        if name == "tv_list_tabs":
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://{CDP_HOST}:{CDP_PORT}/json")
                tabs = resp.json()
                info = [{"title": t.get("title", ""), "url": t.get("url", ""), "id": t.get("id", "")} for t in tabs]
                return [TextContent(type="text", text=json.dumps(info, indent=2))]

        ws_url = await get_ws_endpoint()
        if not ws_url:
            return [TextContent(type="text", text="ERROR: No TradingView tab found. Make sure Chrome is running with --remote-debugging-port=9222 and TradingView is open.")]

        if name == "tv_screenshot":
            result = await cdp_command(ws_url, "Page.captureScreenshot", {"format": "png", "quality": 90})
            img_data = result.get("data", "")
            return [ImageContent(type="image", data=img_data, mimeType="image/png")]

        elif name == "tv_get_symbol":
            js = """
            (function() {
                const symbolEl = document.querySelector('[data-symbol-short]') ||
                                 document.querySelector('.chart-controls-bar .apply-common-tooltip') ||
                                 document.querySelector('[class*="titleWrapper"] button');
                const intervalEl = document.querySelector('[data-value][data-role="button"]') ||
                                   document.querySelector('[id*="header-toolbar-interval"]');
                const priceEl = document.querySelector('.chart-markup-table .pane .price-axis .last-price-line') ||
                                document.querySelector('[class*="lastContainer"]') ||
                                document.querySelector('[class*="currentPriceValue"]');

                // Try to get info from page title
                const title = document.title;

                // Get all text from the top toolbar area
                const toolbar = document.querySelector('[class*="chart-controls"]') ||
                                document.querySelector('[class*="header-toolbar"]');
                const toolbarText = toolbar ? toolbar.innerText : '';

                return JSON.stringify({
                    title: title,
                    symbol: symbolEl ? symbolEl.innerText : 'N/A',
                    interval: intervalEl ? intervalEl.innerText : 'N/A',
                    toolbar_info: toolbarText.substring(0, 500)
                });
            })()
            """
            result = await cdp_evaluate(ws_url, js)
            return [TextContent(type="text", text=str(result))]

        elif name == "tv_read_indicators":
            js = """
            (function() {
                // Read indicator legends (values shown on chart)
                const legends = document.querySelectorAll('[class*="legend"], [class*="study"], [class*="indicator"]');
                const results = [];
                legends.forEach(el => {
                    const text = el.innerText.trim();
                    if (text && text.length > 2 && text.length < 500) {
                        results.push(text);
                    }
                });

                // Also try the source pane legends
                const panes = document.querySelectorAll('[class*="pane"] [class*="legend"], [data-name="legend"]');
                panes.forEach(el => {
                    const text = el.innerText.trim();
                    if (text && text.length > 2) results.push(text);
                });

                // Read from the status line area
                const statusLines = document.querySelectorAll('[class*="valuesWrapper"], [class*="statusLine"]');
                statusLines.forEach(el => {
                    const text = el.innerText.trim();
                    if (text) results.push("STATUS: " + text);
                });

                return JSON.stringify([...new Set(results)]);
            })()
            """
            result = await cdp_evaluate(ws_url, js)
            return [TextContent(type="text", text=str(result))]

        elif name == "tv_read_price_data":
            js = """
            (function() {
                // Read OHLCV from the legend/data window
                const dataWindow = document.querySelectorAll('[class*="valuesWrapper"] [class*="value"], [class*="legendValue"]');
                const values = [];
                dataWindow.forEach(el => values.push(el.innerText.trim()));

                // Get the OHLCV from header
                const ohlcLabels = ['O', 'H', 'L', 'C', 'V'];
                const ohlcData = {};
                const allSpans = document.querySelectorAll('[class*="headerItem"], [class*="ohlcValue"], [class*="valueItem"]');
                allSpans.forEach(el => {
                    const text = el.innerText.trim();
                    ohlcData[text] = true;
                });

                // Try reading from the data window panel
                const dwItems = document.querySelectorAll('[class*="dataWindow"] [class*="row"], [class*="item"]');
                const dwData = [];
                dwItems.forEach(el => {
                    const text = el.innerText.trim();
                    if (text) dwData.push(text);
                });

                // Current price from axis
                const priceAxis = document.querySelectorAll('[class*="price-axis"] text, [class*="lastPrice"], [class*="currentPrice"]');
                const prices = [];
                priceAxis.forEach(el => prices.push(el.innerText || el.textContent));

                return JSON.stringify({
                    legend_values: values,
                    ohlc_area: Object.keys(ohlcData).slice(0, 20),
                    data_window: dwData.slice(0, 30),
                    price_axis: prices.slice(0, 5)
                });
            })()
            """
            result = await cdp_evaluate(ws_url, js)
            return [TextContent(type="text", text=str(result))]

        elif name == "tv_execute_js":
            code = arguments.get("code", "")
            result = await cdp_evaluate(ws_url, code)
            return [TextContent(type="text", text=str(result))]

        elif name == "tv_read_orderbook":
            js = """
            (function() {
                const dom = document.querySelectorAll('[class*="orderBook"], [class*="dom-"], [class*="depth"]');
                const data = [];
                dom.forEach(el => {
                    const text = el.innerText.trim();
                    if (text) data.push(text.substring(0, 300));
                });
                return data.length ? JSON.stringify(data) : 'Order book/DOM panel not visible';
            })()
            """
            result = await cdp_evaluate(ws_url, js)
            return [TextContent(type="text", text=str(result))]

        elif name == "tv_read_strategy_results":
            js = """
            (function() {
                // Read strategy tester panel
                const tester = document.querySelector('[class*="strategyReport"], [data-name="backtesting"]');
                if (!tester) {
                    // Try the bottom panel tabs
                    const panels = document.querySelectorAll('[class*="bottomPanel"] [class*="tab"], [class*="tabs"] button');
                    const panelTexts = [];
                    panels.forEach(el => panelTexts.push(el.innerText));
                    return JSON.stringify({status: 'Strategy tester panel not visible', available_panels: panelTexts});
                }

                // Read performance summary
                const rows = tester.querySelectorAll('tr, [class*="row"]');
                const data = [];
                rows.forEach(el => data.push(el.innerText.trim()));

                return JSON.stringify({strategy_results: data.slice(0, 50)});
            })()
            """
            result = await cdp_evaluate(ws_url, js)
            return [TextContent(type="text", text=str(result))]

        elif name == "tv_read_alerts":
            js = """
            (function() {
                const alerts = document.querySelectorAll('[class*="alert"], [class*="notification"], [class*="toast"]');
                const data = [];
                alerts.forEach(el => {
                    const text = el.innerText.trim();
                    if (text && text.length > 3) data.push(text);
                });
                return data.length ? JSON.stringify(data) : 'No alerts visible';
            })()
            """
            result = await cdp_evaluate(ws_url, js)
            return [TextContent(type="text", text=str(result))]

        elif name == "tv_read_watchlist":
            js = """
            (function() {
                const items = document.querySelectorAll('[class*="watchlist"] [class*="row"], [class*="symbolRow"]');
                const data = [];
                items.forEach(el => {
                    const text = el.innerText.trim();
                    if (text) data.push(text);
                });
                return data.length ? JSON.stringify(data.slice(0, 30)) : 'Watchlist not visible';
            })()
            """
            result = await cdp_evaluate(ws_url, js)
            return [TextContent(type="text", text=str(result))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        return [TextContent(type="text", text=f"ERROR: {str(e)}. Make sure Chrome is running with --remote-debugging-port=9222")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
