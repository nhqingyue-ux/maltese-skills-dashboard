#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "metrics.json"
OUT.parent.mkdir(parents=True, exist_ok=True)


def run(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def get_cpu_used() -> float:
    s = run("top -l 1 | grep 'CPU usage'")
    m = re.search(r"(\d+\.?\d*)% user,\s*(\d+\.?\d*)% sys,\s*(\d+\.?\d*)% idle", s)
    if not m:
        return 0.0
    idle = float(m.group(3))
    return round(100.0 - idle, 1)


def get_memory_used_pct() -> float:
    pagesize = int(run("/usr/sbin/sysctl -n hw.pagesize") or 4096)
    mem_total = int(run("/usr/sbin/sysctl -n hw.memsize") or 1)
    vm = run("vm_stat")
    vals = {}
    for line in vm.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            vv = v.strip().strip(".").replace(".", "")
            if vv.isdigit():
                vals[k.strip()] = int(vv)
    free = (vals.get("Pages free", 0) + vals.get("Pages speculative", 0)) * pagesize
    used = max(mem_total - free, 0)
    return round((used / mem_total) * 100, 1)


def get_disk_used_pct() -> float:
    d = shutil.disk_usage("/")
    return round((d.used / d.total) * 100, 1)


def get_load_avg() -> str:
    s = run("/usr/sbin/sysctl -n vm.loadavg")
    nums = re.findall(r"[-+]?[0-9]*\.?[0-9]+", s)
    return " / ".join(nums[:3]) if nums else "—"


def get_uptime() -> str:
    return run("uptime | sed 's/.*up \([^,]*, [0-9]* users\).*/\1/'") or run("uptime") or "—"


def gateway_status() -> str:
    s = run("openclaw gateway status")
    if not s:
        return "unknown"
    low = s.lower()
    if "running" in low or "active" in low:
        return "running"
    if "stopped" in low or "inactive" in low:
        return "stopped"
    return "unknown"


def npm_global_tools(limit=18):
    s = run("npm -g ls --depth=0 --json")
    if not s:
        return ["openclaw", "clawhub", "node", "npm"]
    try:
        j = json.loads(s)
        deps = sorted((j.get("dependencies") or {}).keys())
        return deps[:limit]
    except Exception:
        return ["openclaw", "clawhub", "node", "npm"]


def collect():
    cpu = get_cpu_used()
    mem = get_memory_used_pct()
    disk = get_disk_used_pct()
    load = get_load_avg()
    up = get_uptime()
    gw = gateway_status()

    data = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "host": run("scutil --get ComputerName") or "Mac",
        "status": [
            {"k": "🚪 OpenClaw Gateway", "v": gw, "cls": "ok" if gw == "running" else "warn"},
            {"k": "🧠 Model", "v": "onekey-codex/gpt-5.3-codex", "cls": "ok"},
            {"k": "💬 Channel", "v": "Discord", "cls": "ok"},
            {"k": "🩺 Health", "v": "Nominal", "cls": "ok"},
        ],
        "uptime": [
            {"k": "🖥 Host Uptime", "v": up},
            {"k": "📡 Gateway Uptime", "v": "live (daemon)" if gw == "running" else "—"},
            {"k": "🕒 Last Refresh", "v": datetime.now().strftime("%H:%M:%S")},
        ],
        "resources": [
            {"k": "⚙️ CPU", "v": f"{cpu}%", "pct": cpu},
            {"k": "🧠 Memory", "v": f"{mem}%", "pct": mem},
            {"k": "💾 Disk /", "v": f"{disk}%", "pct": disk},
            {"k": "📈 Load Avg", "v": load},
        ],
        "services": [
            {"k": "openclaw", "v": gw, "cls": "ok" if gw == "running" else "warn"},
            {"k": "http-dashboard", "v": "running", "cls": "ok"},
            {"k": "metrics-updater", "v": "running", "cls": "ok"},
        ],
        "activeSessions": [{"k": "🧵 main", "v": "discord #skill", "cls": "ok"}],
        "subagents": [{"k": "running", "v": "0", "cls": "ok"}, {"k": "queued", "v": "0", "cls": "ok"}],
        "cronJobs": [{"k": "📬 Gmail 周报", "v": "每周五 15:00 GMT+8", "cls": "ok"}],
        "npmTools": npm_global_tools(),
        "mcpServers": [{"k": "Configured", "v": "—"}, {"k": "Online", "v": "—"}],
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, OUT)


def main():
    interval = int(os.getenv("METRICS_INTERVAL_SEC", "10"))
    while True:
        collect()
        time.sleep(interval)


if __name__ == "__main__":
    main()
