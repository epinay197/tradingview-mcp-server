"""
setup_computer.py — Run on ANY computer to configure the TradingView MCP.
Usage:  python setup_computer.py <remote_mcp_url>
Example: python setup_computer.py https://tradingview-mcp-server.up.railway.app/sse

What it does:
  1. Writes / updates ~/.claude/.mcp.json to point at the remote server
  2. Tests connectivity to the remote MCP endpoint
  3. Prints confirmation
"""
import json
import os
import sys
import urllib.request

MCP_JSON_PATH = os.path.expanduser(r"~/.claude/.mcp.json")

def update_mcp_config(sse_url: str):
    config = {}
    if os.path.exists(MCP_JSON_PATH):
        with open(MCP_JSON_PATH) as f:
            config = json.load(f)

    config.setdefault("mcpServers", {})
    config["mcpServers"]["tradingview"] = {"url": sse_url}

    os.makedirs(os.path.dirname(MCP_JSON_PATH), exist_ok=True)
    with open(MCP_JSON_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print(f"[OK] .mcp.json updated → tradingview MCP points to {sse_url}")


def test_health(sse_url: str):
    health_url = sse_url.replace("/sse", "/health")
    try:
        with urllib.request.urlopen(health_url, timeout=10) as r:
            data = json.loads(r.read())
            print(f"[OK] Server health: {data}")
    except Exception as e:
        print(f"[WARN] Health check failed: {e}")
        print("      Server may still be starting up. Try again in 60s.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python setup_computer.py <remote_sse_url>")
        print("  e.g. python setup_computer.py https://your-app.up.railway.app/sse")
        sys.exit(1)

    url = sys.argv[1].rstrip("/")
    if not url.endswith("/sse"):
        url = url + "/sse"

    update_mcp_config(url)
    test_health(url)
    print("\nDone! Restart Claude Code to load the remote MCP.")
