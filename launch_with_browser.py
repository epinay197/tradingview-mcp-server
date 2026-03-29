"""
Wrapper that ensures Brave/Chrome is running with CDP before starting the MCP server.
Run this instead of server.py in .mcp.json.
"""
import subprocess
import sys
import os
import time
import asyncio
import httpx

CDP_PORT = 9222
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
BRAVE_USER_DATA = r"C:\Users\Anwender\AppData\Local\BraveSoftware\Brave-Browser\User Data"
TV_URL = "https://www.tradingview.com/chart/"


async def is_cdp_ready():
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=2)
            return True
    except Exception:
        return False


async def ensure_browser():
    if await is_cdp_ready():
        return  # Already running

    # Launch Brave with CDP
    subprocess.Popen(
        [BRAVE_PATH, f"--remote-debugging-port={CDP_PORT}",
         f"--user-data-dir={BRAVE_USER_DATA}", TV_URL],
        creationflags=8,  # DETACHED_PROCESS
    )

    # Wait up to 15s for CDP to be ready
    for _ in range(15):
        await asyncio.sleep(1)
        if await is_cdp_ready():
            await asyncio.sleep(3)  # Extra wait for page load
            return

    # Non-fatal: server will report errors per-call if browser not ready


asyncio.run(ensure_browser())

# Hand off to the real MCP server
server_path = os.path.join(os.path.dirname(__file__), "server.py")
os.execv(sys.executable, [sys.executable, server_path])
