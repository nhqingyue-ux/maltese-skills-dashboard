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


def bytes_to_gib(v: int) -> float:
    return round(v / (1024 ** 3), 1)


def get_memory_stats():
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
    pct = round((used / mem_total) * 100, 1)
    return {
        "pct": pct,
        "used_gib": bytes_to_gib(used),
        "total_gib": bytes_to_gib(mem_total),
    }


def get_disk_stats():
    d = shutil.disk_usage("/")
    return {
        "pct": round((d.used / d.total) * 100, 1),
        "used_gib": bytes_to_gib(d.used),
        "total_gib": bytes_to_gib(d.total),
    }


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


def parse_token_str_to_int(s: str) -> int:
    s = s.strip().lower()
    m = re.match(r"(\d+(?:\.\d+)?)([kmb]?)", s)
    if not m:
        return 0
    n = float(m.group(1))
    unit = m.group(2)
    if unit == "k":
        n *= 1000
    elif unit == "m":
        n *= 1_000_000
    elif unit == "b":
        n *= 1_000_000_000
    return int(n)


def get_token_usage_estimate():
    text = run("openclaw status")
    total = 0
    rows = 0
    by_model = {}
    for line in text.splitlines():
        if "│" not in line or "/200k" not in line:
            continue
        parts = [p.strip() for p in line.split("│") if p.strip()]
        if len(parts) < 5:
            continue
        model = parts[3]
        tokens_cell = parts[4]
        m = re.search(r"([0-9]+(?:\.[0-9]+)?[kmb]?)\s*/", tokens_cell.lower())
        if not m:
            continue
        v = parse_token_str_to_int(m.group(1))
        total += v
        rows += 1
        by_model[model] = by_model.get(model, 0) + v

    top_model = "—"
    top_tokens = 0
    if by_model:
        top_model, top_tokens = sorted(by_model.items(), key=lambda x: x[1], reverse=True)[0]

    return {
        "total": total,
        "sessions": rows,
        "top_model": top_model,
        "top_tokens": top_tokens,
    }


def collect():
    cpu = get_cpu_used()
    mem = get_memory_stats()
    disk = get_disk_stats()
    load = get_load_avg()
    up = get_uptime()
    gw = gateway_status()
    tu = get_token_usage_estimate()

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
            {"k": "⚙️ CPU", "v": f"{cpu}%", "pct": cpu, "detail": "负载占比"},
            {"k": "🧠 Memory", "v": f"{mem['pct']}%", "pct": mem['pct'], "detail": f"{mem['used_gib']} / {mem['total_gib']} GiB"},
            {"k": "💾 Disk /", "v": f"{disk['pct']}%", "pct": disk['pct'], "detail": f"{disk['used_gib']} / {disk['total_gib']} GiB"},
            {"k": "📈 Load Avg", "v": load, "detail": "1m / 5m / 15m"},
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
        "tokenUsage": [
            {"k": "🧮 今日估算总 Tokens", "v": f"{tu['total']:,}", "cls": "ok"},
            {"k": "🧵 统计会话数", "v": str(tu['sessions'])},
            {"k": "🤖 主力模型", "v": tu['top_model']},
            {"k": "📊 主力模型 Tokens", "v": f"{tu['top_tokens']:,}"},
        ],
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
