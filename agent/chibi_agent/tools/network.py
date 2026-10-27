"""Read-only network checks: open connections, traffic, ping, Wi-Fi (psutil, ping, netsh)."""
from __future__ import annotations

import re
import socket
import subprocess
import time
from collections import Counter

import psutil

from . import Result, tool

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _rate(n: float) -> str:
    for unit in ("B/s", "KB/s", "MB/s"):
        if n < 1024 or unit == "MB/s":
            return f"{n:.0f} {unit}" if unit == "B/s" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} MB/s"


def _total(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _names() -> dict[int, str]:
    out = {}
    for p in psutil.process_iter(["pid", "name"]):
        out[p.info["pid"]] = p.info["name"] or "?"
    return out


def connections(process: str = "", conns=None, names=None) -> str:
    conns = psutil.net_connections(kind="tcp") if conns is None else conns
    names = _names() if names is None else names
    process = process.lower()
    est, listen = [], []
    for c in conns:
        name = names.get(c.pid or 0, "?")
        if process and process not in name.lower():
            continue
        if c.status == psutil.CONN_LISTEN:
            listen.append(f"{name} listening on port {c.laddr.port}")
        elif c.status == psutil.CONN_ESTABLISHED and c.raddr:
            est.append(f"{name} -> {c.raddr.ip}:{c.raddr.port}")
    by_proc = Counter(line.split(" -> ")[0] for line in est)
    head = (f"{len(est)} open connections"
            + (" (" + ", ".join(f"{n} {k}" for k, n in by_proc.most_common(6)) + ")" if est else ""))
    body = est[:25] + (["..."] if len(est) > 25 else [])
    tail = sorted(set(listen))[:15]
    return "\n".join([head, *body] + (["Listening:", *tail] if tail else []))


def traffic(sample_s: float = 2.0, counters=None, sleep=time.sleep) -> str:
    take = counters or (lambda: psutil.net_io_counters(pernic=True))
    a = take()
    sleep(sample_s)
    b = take()
    lines = []
    for nic, s in b.items():
        if nic not in a or ("loopback" in nic.lower()):
            continue
        up = (s.bytes_sent - a[nic].bytes_sent) / sample_s
        down = (s.bytes_recv - a[nic].bytes_recv) / sample_s
        if up or down or s.bytes_recv:
            lines.append((down + up, f"{nic}: down {_rate(down)}, up {_rate(up)}  "
                                     f"(since boot: {_total(s.bytes_recv)} down, {_total(s.bytes_sent)} up)"))
    lines.sort(reverse=True)
    out = [ln for _, ln in lines[:6]] or ["No network traffic."]
    return "\n".join(out)


def ping(host: str = "1.1.1.1", run=subprocess.run) -> str:
    host = (host or "1.1.1.1").strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-:]+", host):
        return f"'{host}' is not a host name or address."
    try:
        ip = socket.gethostbyname(host)
        dns = f"{host} is {ip}" if ip != host else ""
    except OSError:
        return f"{host} doesn't resolve: no DNS answer (check the name or the connection)."
    p = run(["ping", "-n", "4", "-w", "1500", host], capture_output=True, text=True, timeout=15,
            creationflags=NO_WINDOW)
    out = p.stdout or ""
    loss = re.search(r"\((\d+)% loss\)", out)
    avg = re.search(r"Average = (\d+)ms", out)
    if avg:
        res = f"{host} answers: average {avg.group(1)} ms, {loss.group(1) if loss else '?'}% lost."
    else:
        res = f"{host} doesn't answer ping ({loss.group(1) if loss else '100'}% lost)."
    return " ".join(x for x in (dns + "." if dns else "", res) if x)


def wifi(run=subprocess.run) -> str:
    p = run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=10,
            creationflags=NO_WINDOW)
    out = p.stdout or ""
    want = ("SSID", "State", "Signal", "Band", "Radio type", "Receive rate (Mbps)", "Transmit rate (Mbps)")
    vals = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = (x.strip() for x in line.split(":", 1))
            if k in want and k not in vals:
                vals[k] = v
    if not vals:
        return "No Wi-Fi adapter (or it's off)."
    return ", ".join(f"{k}: {v}" for k, v in vals.items())


@tool("network", "Network connections, traffic, ping or Wi-Fi.",
      {"action": ("connections, traffic, ping or wifi", True),
       "target": ("Host to ping, or app name to filter connections", False)}, timeout_s=25)
def network(action: str, target: str = "") -> Result:
    action = (action or "").lower()
    try:
        if action == "connections":
            return Result(connections(target), untrusted=True)
        if action == "traffic":
            return Result(traffic())
        if action == "ping":
            return Result(ping(target))
        if action == "wifi":
            return Result(wifi(), untrusted=True)
    except (OSError, subprocess.SubprocessError, psutil.Error) as e:
        return Result(f"The network check failed: {e}", failed=True)
    return Result("Use action connections, traffic, ping or wifi.")
