#!/usr/bin/env python3
"""Memory System Dashboard — 터미널 스냅샷 + 수집 라이브러리.

세 저장소(Hindsight/agentmemory/네이티브)의 헬스·현황·활동·성능을 한 화면에.
실행할 때마다 ~/.claude/memdash_history.jsonl 에 스냅샷을 누적해 추이를 표시.
memdash_web.py 가 collect()를 재사용해 웹 대시보드를 제공한다.

Usage: ./memdash.py [--no-bench] [--no-history]
"""

import argparse
import glob
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime

HS = "http://127.0.0.1:9077"
AM = "http://localhost:3111"
OL = "http://localhost:11434"
STATE = os.path.expanduser("~/.claude/plugins/data/hindsight-memory-dev/state")
HISTORY = os.path.expanduser("~/.claude/memdash_history.jsonl")
ABLOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_comparison_log.md")
MAIN_BANK = "claude-code::Claude_MemorySystem"

G, R, Y, B, X = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"


def get(url, timeout=5, body=None):
    """(elapsed_ms, json|None)"""
    try:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"} if body else {})
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (time.monotonic() - t0) * 1000, json.loads(r.read())
    except Exception:
        return None, None


def _bank_url(bank_id, path=""):
    return f"{HS}/v1/default/banks/{urllib.parse.quote(bank_id, safe='')}{path}"


def collect(bench_n: int = 10) -> dict:
    """모든 지표를 수집해 dict로 반환. bench_n=0이면 라이브 지연 측정 생략."""
    d: dict = {"ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}

    # A. 헬스
    hs_ms, hs = get(f"{HS}/health")
    am_ms, am = get(f"{AM}/agentmemory/livez")
    ol_ms, ol = get(f"{OL}/api/tags")
    hooks_wired, am_plug_disabled = 0, False
    try:
        cfg = json.load(open(os.path.expanduser("~/.claude/settings.json")))
        hooks_wired = sum(1 for ev in cfg.get("hooks", {}).values() for e in ev
                          for h in e.get("hooks", [])
                          if "hindsight-integrations/claude-code" in h.get("command", ""))
        am_plug_disabled = cfg.get("enabledPlugins", {}).get("agentmemory@agentmemory") is False
    except Exception:
        pass
    d["health"] = {
        "hindsight": {"ok": bool(hs), "ms": hs_ms},
        "agentmemory": {"ok": bool(am), "ms": am_ms},
        "ollama": {"ok": bool(ol), "ms": ol_ms, "models": len(ol.get("models", [])) if ol else 0},
        "hooks_wired": hooks_wired, "am_plugin_disabled": am_plug_disabled,
    }

    # B. 저장소
    _, banks_resp = get(f"{HS}/v1/default/banks")
    banks = []
    for b in (banks_resp or {}).get("banks", []):
        _, st = get(_bank_url(b["bank_id"], "/stats"))
        if st:
            nt = st.get("nodes_by_fact_type", {})
            banks.append({"id": b["bank_id"], "nodes": st.get("total_nodes", 0),
                          "world": nt.get("world", 0), "obs": nt.get("observation", 0),
                          "exp": nt.get("experience", 0), "docs": st.get("total_documents", 0),
                          "links": st.get("total_links", 0)})
    d["banks"] = banks
    d["hs_nodes"] = sum(b["nodes"] for b in banks)
    _, amc = get(f"{AM}/agentmemory/memories?count=true")
    d["am_count"] = (amc or {}).get("latestCount")
    mem_dirs = glob.glob(os.path.expanduser("~/.claude/projects/*/memory"))
    counts = sorted(((len(glob.glob(os.path.join(md, "*.md"))),
                      os.path.basename(os.path.dirname(md)).replace("-home-jkyoo-", ""))
                     for md in mem_dirs), reverse=True)
    d["native"] = {"projects": len(counts), "files": sum(c for c, _ in counts),
                   "top": [{"name": n, "files": c} for c, n in counts[:3]]}

    # C. 활동
    act: dict = {"last_recall": None, "sessions": [], "recent_ops": [], "failed": 0}
    try:
        act["last_recall"] = {k: v for k, v in
                              json.load(open(os.path.join(STATE, "last_recall.json"))).items()
                              if k != "context"}
    except Exception:
        pass
    try:
        turns = json.load(open(os.path.join(STATE, "turns.json")))
        rt = json.load(open(os.path.join(STATE, "retention_tracking.json")))
        for sid, n in list(turns.items())[-3:]:
            prog = rt.get(sid, {})
            act["sessions"].append({"sid": sid[:8], "turns": n,
                                    "left": 10 - (n % 10) if n % 10 else 0,
                                    "msg": prog.get("message_count", 0),
                                    "chunk": prog.get("chunk", "-")})
    except Exception:
        pass
    for b in banks:
        _, ops = get(_bank_url(b["id"], "/operations?limit=10"))
        act["failed"] += sum(1 for op in (ops or {}).get("operations", [])
                             if op["status"] == "failed")
    _, ops = get(_bank_url(MAIN_BANK, "/operations?limit=4"))
    act["recent_ops"] = [f"{op['task_type']}:{op['status']}@{op['created_at'][11:16]}"
                         for op in (ops or {}).get("operations", [])]
    d["activity"] = act

    # D. 성능
    perf: dict = {"p50": None, "p95": None, "n": 0, "ab_count": 0, "ab_last": ""}
    if bench_n and hs:
        lats = []
        qs = ["프로젝트 설정", "버그 수정 이력", "최근 결정사항", "테스트"]
        for i in range(bench_n):
            ms, _ = get(_bank_url(MAIN_BANK, "/memories/recall"),
                        body={"query": qs[i % len(qs)], "max_tokens": 512, "budget": "low"},
                        timeout=15)
            if ms:
                lats.append(ms)
        if lats:
            lats.sort()
            perf["n"] = len(lats)
            perf["p50"] = round(lats[len(lats) // 2])
            perf["p95"] = round(lats[min(len(lats) - 1, int(len(lats) * 0.95))])
    try:
        heads = [line.strip("# \n") for line in open(ABLOG) if line.startswith("## ")]
        perf["ab_count"], perf["ab_last"] = len(heads), heads[-1][:60] if heads else ""
    except Exception:
        pass
    d["perf"] = perf
    return d


def load_history():
    try:
        return [json.loads(line) for line in open(HISTORY)]
    except Exception:
        return []


def render(d: dict, hist: list):
    def dot(ok):
        return f"{G}●{X}" if ok else f"{R}●{X}"

    def sec(t):
        print(f"\n{B}[{t}]{X}")

    print(f"{B}Memory System Dashboard{X} — {d['ts'][:16].replace('T', ' ')}")
    print("=" * 64)
    h = d["health"]
    sec("시스템 헬스")
    for name, port, extra in (("hindsight ", 9077, ""), ("agentmemory", 3111, "  (아카이브 전용, 훅 비활성)"),
                              ("ollama    ", 11434, f"  models={h['ollama']['models']}")):
        s = h[name.strip()]
        ms = f"{s['ms']:.0f}ms" if s.get("ms") else ""
        print(f"  {dot(s['ok'])} {name}:{port}  {'ok' if s['ok'] else 'DOWN':6s} {ms}{extra}")
    print(f"  {dot(h['hooks_wired'] == 4)} 글로벌 훅 {h['hooks_wired']}/4 연결"
          f"   {dot(h['am_plugin_disabled'])} agentmemory 플러그인 disabled={h['am_plugin_disabled']}")

    sec("저장소 현황")
    for b in d["banks"]:
        print(f"  hindsight {b['id']}")
        print(f"    nodes={b['nodes']} (world {b['world']} / obs {b['obs']} / exp {b['exp']})"
              f"  docs={b['docs']}  links={b['links']}")
    print(f"  agentmemory 아카이브: {d['am_count']}건")
    nt = d["native"]
    top = ", ".join(f"{t['name']} {t['files']}" for t in nt["top"])
    print(f"  네이티브: {nt['projects']}개 프로젝트, {nt['files']}개 파일 (top: {top})")

    sec("파이프라인 활동")
    a = d["activity"]
    if a["last_recall"]:
        lr = a["last_recall"]
        print(f"  마지막 recall: {lr.get('saved_at')}  {lr.get('result_count')}건  bank={lr.get('bank_id')}")
    for s in a["sessions"]:
        print(f"  세션 {s['sid']}…: 턴 {s['turns']}, 다음 retain까지 {s['left']}턴"
              f"  (retained {s['msg']}msg/chunk {s['chunk']})")
    print(f"  최근 작업: {' | '.join(a['recent_ops']) if a['recent_ops'] else '-'}")
    print(f"  실패 작업: {G if a['failed'] == 0 else R}{a['failed']}건{X}")

    sec("성능")
    p = d["perf"]
    if p["p50"] is not None:
        print(f"  hindsight recall (live n={p['n']}): p50={p['p50']}ms  p95={p['p95']}ms")
    print(f"  A/B 로그: {p['ab_count']}건 누적" + (f" (최근: {p['ab_last']})" if p["ab_last"] else ""))

    sec("추이")
    if len(hist) >= 2:
        tail = hist[-8:]
        print(f"  hindsight nodes: {' → '.join(str(x.get('hs_nodes', '?')) for x in tail)}")
        print(f"  archive:         {' → '.join(str(x.get('am_count', '?')) for x in tail)}")
        p50s = [x.get("p50") for x in tail if x.get("p50")]
        if p50s:
            print(f"  recall p50(ms):  {' → '.join(str(v) for v in p50s)}")
        print(f"  (스냅샷 {len(hist)}회 누적: {HISTORY})")
    else:
        print(f"  첫 스냅샷 기록됨 — 다음 실행부터 추이 표시 ({HISTORY})")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-bench", action="store_true", help="라이브 지연 측정 생략")
    ap.add_argument("--no-history", action="store_true", help="추이 기록 생략")
    args = ap.parse_args()

    d = collect(bench_n=0 if args.no_bench else 10)
    hist = load_history()
    snapshot = {"ts": d["ts"][:16], "hs_nodes": d["hs_nodes"], "am_count": d["am_count"]}
    if d["perf"]["p50"] is not None:
        snapshot["p50"] = d["perf"]["p50"]
    if not args.no_history:
        with open(HISTORY, "a") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
        hist.append(snapshot)
    render(d, hist)


if __name__ == "__main__":
    main()
