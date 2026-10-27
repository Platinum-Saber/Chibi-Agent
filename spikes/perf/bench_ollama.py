"""Ollama benchmark with her real prompt and tools.  python bench_ollama.py <out.json> [label]"""
import json
import subprocess
import sys
import time

import httpx

from chibi_agent import persona, tools
from chibi_shared import config

out = sys.argv[1]
label = sys.argv[2] if len(sys.argv) > 2 else "alone"
oc = config.load()["ollama"]
URL, MODEL = oc["url"], oc["model"]
OPTS = {"num_ctx": int(oc.get("num_ctx", 8192)), "temperature": float(oc.get("temperature", 0.4))}
tools.load_all()
ALL = tools.schemas()
SUBSET = tools.schemas(["get_time", "system_info", "look_at_screen", "remember", "open_app"]) or ALL[:5]
SYSTEM = persona.system_prompt(tools.listing())
c = httpx.Client(timeout=300)


def vram() -> dict:
    ps = {m["name"]: {"vram_mb": round(m["size_vram"] / 2**20), "size_mb": round(m["size"] / 2**20),
                      "ctx": m.get("context_length")} for m in c.get(f"{URL}/api/ps").json()["models"]}
    smi = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip().split(", ")
    return {"ollama": ps, "gpu_used_mb": int(smi[0]), "gpu_util_pct": int(smi[1])}


def chat(user: str, tool_list) -> dict:
    body = {"model": MODEL, "stream": True, "think": False, "keep_alive": "10m", "options": OPTS,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
    if tool_list:
        body["tools"] = tool_list
    t0 = time.perf_counter()
    first = None
    final = {}
    text, calls = "", []
    with c.stream("POST", f"{URL}/api/chat", json=body) as r:
        for line in r.iter_lines():
            if not line:
                continue
            j = json.loads(line)
            m = j.get("message", {})
            if first is None and (m.get("content") or m.get("tool_calls")):
                first = time.perf_counter() - t0
            text += m.get("content", "")
            calls += [tc["function"]["name"] for tc in m.get("tool_calls", [])]
            if j.get("done"):
                final = j
    total = time.perf_counter() - t0
    ns = 1e9
    return {"user": user, "tools_sent": len(tool_list or []), "ttft_s": round(first or total, 3), "total_s": round(total, 3),
            "prompt_tokens": final.get("prompt_eval_count"), "prompt_tok_s": round(final.get("prompt_eval_count", 0) / (final.get("prompt_eval_duration", 1) / ns), 1),
            "gen_tokens": final.get("eval_count"), "gen_tok_s": round(final.get("eval_count", 0) / (final.get("eval_duration", 1) / ns), 1),
            "load_s": round(final.get("load_duration", 0) / ns, 2), "tool_calls": calls, "reply": text[:80]}


R = {"label": label, "model": MODEL, "options": OPTS, "system_chars": len(SYSTEM), "tools_all": len(ALL)}
R["before"] = vram()
t0 = time.perf_counter()
c.post(f"{URL}/api/generate", json={"model": MODEL, "keep_alive": "10m", "options": OPTS}).raise_for_status()
R["cold_load_s"] = round(time.perf_counter() - t0, 2)
R["loaded"] = vram()
runs = []
for user, tl in [("What time is it?", SUBSET), ("What time is it?", SUBSET), ("What time is it?", ALL),
                 ("Tell me in two sentences what you can help me with.", SUBSET),
                 ("Tell me in two sentences what you can help me with.", SUBSET),
                 ("Open Spotify.", ALL), ("Open Spotify.", ALL)]:
    runs.append(chat(user, tl))
    print(runs[-1], flush=True)
R["runs"] = runs
R["after"] = vram()
json.dump(R, open(out, "w", encoding="utf-8"), indent=1)
