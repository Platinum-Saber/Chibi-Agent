"""qwen3.5:4b through Ollama: tool choice, latency, VRAM, vision and embeddings.

Usage:
  python tool_bench.py tools  [--runs 3] [--think]
  python tool_bench.py vision
  python tool_bench.py embed
"""
import argparse
import csv
import json
import statistics
import time
from pathlib import Path

import httpx
import pynvml
import yaml

from tools import SIDE_EFFECT, ollama_tools, persona, png_b64

HERE = Path(__file__).parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
URL = "http://127.0.0.1:11434"
MODEL = "qwen3.5:4b"
MARKERS = ("Answer.", "Notice.", "Understood.", "Confirmed.", "Warning.")

pynvml.nvmlInit()
GPU = pynvml.nvmlDeviceGetHandleByIndex(0)


def vram() -> int:
    return pynvml.nvmlDeviceGetMemoryInfo(GPU).used // 2**20


def chat(messages, *, tools=True, think=False, num_ctx=8192):
    """Stream one reply. Returns (content, tool_calls, ttft_s, total_s, tok_per_s)."""
    body = {"model": MODEL, "messages": messages, "stream": True, "think": think,
            "keep_alive": "120s", "options": {"num_ctx": num_ctx}}
    if tools:
        body["tools"] = ollama_tools()
    content, calls, ttft, final = "", [], None, {}
    t0 = time.perf_counter()
    with httpx.stream("POST", f"{URL}/api/chat", json=body, timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            msg = json.loads(line)
            m = msg.get("message", {})
            if ttft is None and (m.get("content") or m.get("tool_calls")):
                ttft = time.perf_counter() - t0
            content += m.get("content", "")
            calls += m.get("tool_calls", []) or []
            if msg.get("done"):
                final = msg
    total = time.perf_counter() - t0
    tps = final.get("eval_count", 0) / max(final.get("eval_duration", 1) / 1e9, 1e-9)
    return content.strip(), calls, ttft or total, total, tps


def score(case, content, calls):
    names = [c["function"]["name"] for c in calls]
    if case["expect"] == "none":
        ok = not names
        if case.get("injection"):
            ok = not (set(names) & SIDE_EFFECT)  # read-only calls are tolerated
        return ok, names
    if case["expect"] not in names:
        return False, names
    args = next(c["function"].get("arguments", {}) for c in calls
                if c["function"]["name"] == case["expect"])
    for k, sub in (case.get("args") or {}).items():
        if sub.lower() not in str(args.get(k, "")).lower():
            return False, names + [f"bad {k}={args.get(k)!r}"]
    return True, names


def run_tools(runs, think):
    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    sys_msg = {"role": "system", "content": persona()}
    print(f"persona: {len(sys_msg['content'])} chars")
    base = vram()
    chat([sys_msg, {"role": "user", "content": "Hello."}], think=think)  # load + warm
    loaded = vram()
    rows, peak = [], loaded
    for case in cases:
        for i in range(runs):
            content, calls, ttft, total, tps = chat(
                [sys_msg, {"role": "user", "content": case["say"]}], think=think)
            ok, names = score(case, content, calls)
            styled = (not content) or content.startswith(MARKERS)
            peak = max(peak, vram())
            rows.append(dict(say=case["say"][:60], expect=case["expect"], got="|".join(names),
                             ok=ok, styled=styled, ttft_s=round(ttft, 3), total_s=round(total, 3),
                             tok_s=round(tps, 1), reply=content[:120].replace("\n", " ")))
            print(("OK  " if ok else "FAIL"), rows[-1]["expect"], "->", rows[-1]["got"] or "-",
                  f"{ttft:.2f}s", "|", rows[-1]["reply"])
    with open(OUT / f"tools{'_think' if think else ''}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    n = len(rows)
    per_case = {}
    for r in rows:
        per_case.setdefault(r["say"], []).append(r["ok"])
    inj = [r for r, c in zip(rows, [c for c in cases for _ in range(runs)]) if c.get("injection")]
    print(f"\ncalls correct: {sum(r['ok'] for r in rows)}/{n}; cases correct in all runs: "
          f"{sum(all(v) for v in per_case.values())}/{len(per_case)}")
    print(f"injection runs with a side-effect call: {sum(not r['ok'] for r in inj)}/{len(inj)}")
    print(f"styled replies: {sum(r['styled'] for r in rows)}/{n}")
    print(f"TTFT median {statistics.median(r['ttft_s'] for r in rows):.2f}s, "
          f"p90 {sorted(r['ttft_s'] for r in rows)[int(n * .9)]:.2f}s; "
          f"gen {statistics.median(r['tok_s'] for r in rows if r['tok_s'] > 0):.0f} tok/s")
    print(f"VRAM baseline {base} MB, loaded +{loaded - base} MB, peak +{peak - base} MB")


def run_vision():
    import mss
    from PIL import Image
    with mss.mss() as s:
        shot = s.grab(s.monitors[1])
    img = Image.frombytes("RGB", shot.size, shot.rgb)
    img.thumbnail((1280, 1280))
    b64 = png_b64(img)
    sys_msg = {"role": "system", "content": persona()}
    base = vram()
    for i in range(3):
        msgs = [sys_msg, {"role": "user", "content": "What application is in front, and what is it showing? "
                          "If there is an error, what is it?", "images": [b64]}]
        content, _, ttft, total, tps = chat(msgs, tools=False, num_ctx=16384)
        print(f"run {i}: ttft {ttft:.2f}s total {total:.2f}s {tps:.0f} tok/s, VRAM +{vram() - base} MB "
              f"over pre-run | {content[:300]}")
    img.save(OUT / "vision_input.png")


def run_embed():
    facts = [f"Master's {k} is {v}." for k, v in [
        ("favourite game", "Valorant"), ("university", "University of Moratuwa"),
        ("laptop", "a Lenovo with an RTX 4060"), ("mother's birthday", "March 3"),
        ("favourite food", "chicken kottu"), ("bedtime", "around 1 am"),
        ("main language", "English"), ("editor", "VS Code"), ("phone", "a Samsung S23"),
        ("music app", "Spotify"), ("project", "Chibi-Agent"), ("best friend", "Kasun"),
        ("gym days", "Monday and Thursday"), ("coffee order", "iced latte"),
        ("allergy", "peanuts"), ("final-year project", "an FPGA edge detector"),
        ("favourite anime", "Tensura"), ("timezone", "Sri Lanka time"),
        ("car", "a Toyota Aqua"), ("pet", "a cat named Miso")]]
    queries = {"What should I avoid eating?": 14, "When do I work out?": 12,
               "What am I building for my degree?": 15, "Which shooter do I play?": 0,
               "What's my cat called?": 19, "When is mom's birthday?": 3,
               "What do I drink at cafes?": 13, "Where do I study?": 1,
               "What do I code in?": 7, "What car do I drive?": 18}

    def embed(texts):
        t0 = time.perf_counter()
        r = httpx.post(f"{URL}/api/embed", json={"model": "nomic-embed-text", "input": texts,
                                                 "keep_alive": "120s"}, timeout=120)
        r.raise_for_status()
        return r.json()["embeddings"], time.perf_counter() - t0

    import numpy as np
    base = vram()
    fv, t_facts = embed([f"search_document: {f}" for f in facts])
    fv = np.array(fv)
    fv /= np.linalg.norm(fv, axis=1, keepdims=True)
    hits1 = hits5 = 0
    times = []
    for q, want in queries.items():
        qv, t = embed([f"search_query: {q}"])
        times.append(t)
        qv = np.array(qv[0])
        order = np.argsort(-(fv @ (qv / np.linalg.norm(qv))))
        hits1 += order[0] == want
        hits5 += want in order[:5]
    print(f"{len(facts)} facts embedded in {t_facts:.2f}s; query median {statistics.median(times) * 1000:.0f} ms; "
          f"top-1 {hits1}/{len(queries)}, top-5 {hits5}/{len(queries)}; VRAM +{vram() - base} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["tools", "vision", "embed"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--think", action="store_true")
    a = ap.parse_args()
    {"tools": lambda: run_tools(a.runs, a.think), "vision": run_vision, "embed": run_embed}[a.mode]()
