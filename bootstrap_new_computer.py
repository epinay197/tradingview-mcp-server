"""
bootstrap_new_computer.py
Run once on any new computer. Requires Python 3.10+ only — no other dependencies.

Usage (BEFORE Railway is deployed — uses local browser fallback):
  python bootstrap_new_computer.py

Usage (AFTER Railway is deployed):
  python bootstrap_new_computer.py https://your-app.up.railway.app/sse
"""
import json
import os
import subprocess
import sys
import urllib.request
import shutil

REPO_URL   = "https://github.com/epinay197/tradingview-mcp-server"
MCP_JSON   = os.path.expanduser(r"~/.claude/.mcp.json")
LOCAL_DIR  = os.path.expanduser(r"~/tradingview-mcp")
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

def run(cmd, **kw):
    print(f"  > {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    return subprocess.run(cmd, check=True, **kw)

def update_mcp_json(entry: dict):
    os.makedirs(os.path.dirname(MCP_JSON), exist_ok=True)
    cfg = {}
    if os.path.exists(MCP_JSON):
        with open(MCP_JSON) as f:
            cfg = json.load(f)
    cfg.setdefault("mcpServers", {})["tradingview"] = entry
    with open(MCP_JSON, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"  [OK] .mcp.json written: {MCP_JSON}")

def test_remote(url: str) -> bool:
    health = url.replace("/sse", "/health")
    try:
        with urllib.request.urlopen(health, timeout=8) as r:
            data = json.loads(r.read())
            print(f"  [OK] Remote server healthy: {data}")
            return True
    except Exception as e:
        print(f"  [WARN] Remote health check failed: {e}")
        return False

def clone_repo():
    if os.path.exists(LOCAL_DIR):
        print(f"  Repo already cloned at {LOCAL_DIR}")
        return
    run(["git", "clone", REPO_URL, LOCAL_DIR])

def install_deps():
    req = os.path.join(LOCAL_DIR, "requirements.txt")
    # Only mcp, httpx, websockets needed for local CDP mode
    run([sys.executable, "-m", "pip", "install", "mcp", "httpx", "websockets", "--quiet"])

def brave_exists() -> bool:
    return os.path.exists(BRAVE_PATH)

# ── Main ──────────────────────────────────────────────────────────────────────
remote_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else ""
if remote_url and not remote_url.endswith("/sse"):
    remote_url += "/sse"

print("=== TradingView MCP Bootstrap ===\n")

if remote_url:
    print(f"[1/2] Testing remote server at {remote_url} …")
    ok = test_remote(remote_url)
    if ok:
        print("[2/2] Configuring .mcp.json to use remote server …")
        update_mcp_json({"url": remote_url})
        print("\nDone! Restart Claude Code. No local browser needed.")
        sys.exit(0)
    else:
        print("Remote not ready. Falling back to local setup.\n")

# Local setup — clone repo + local launcher
print("[1/3] Cloning repo …")
clone_repo()

print("[2/3] Installing Python deps …")
install_deps()

print("[3/3] Configuring .mcp.json (local Brave browser) …")
launcher = os.path.join(LOCAL_DIR, "launch_with_browser.py")
if not os.path.exists(launcher):
    # Older clone — fall back to server.py
    launcher = os.path.join(LOCAL_DIR, "server.py")

update_mcp_json({
    "command": sys.executable,
    "args": [launcher]
})

print()
if brave_exists():
    print("Brave found at default path — auto-launch is enabled.")
else:
    print("[WARN] Brave not found. Install Brave or update BRAVE_PATH in launch_with_browser.py.")

print("\nDone! Restart Claude Code to activate the TradingView MCP.")
print("Once Railway is deployed, run:")
print("  python bootstrap_new_computer.py https://your-app.up.railway.app/sse")
