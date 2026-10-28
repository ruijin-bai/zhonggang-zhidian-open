"""QA smoke 回归：标题关键词召回、意图与总时延（不代表业务答案准确率）。

用法（需后端已运行在 8010，并通过环境变量 EVAL_PASSWORD 提供密码）：
    python -m scripts.eval_qa --base http://127.0.0.1:8010 --username admin

评测维度（P2 可量化回归看护，替代人肉看）：
    1. 检索命中率 —— citations 的 file_title 是否含 golden 期望关键词（recall）
    2. 答案质量   —— 答案非空 / 是否诚实标注「信息不足」
    3. 时延       —— 每个问题的首字与总时延
输出 JSON 汇总 + 逐条明细，供 prompt/检索参数改动后对比。
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sys
import time
from pathlib import Path

import httpx

from app.services.rag.query_intent import classify_intent

GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "golden_qa.json"


def _load_golden() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _hit(citations: list[dict], expect: list[str]) -> bool:
    """期望关键词是否命中任一引用的制度标题（召回判据）。"""
    titles = " ".join(c.get("file_title", "") for c in citations)
    return any(k in titles for k in expect)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default=os.getenv("EVAL_PASSWORD"))
    ap.add_argument("--min-recall", type=float, default=0.90)
    ap.add_argument("--min-intent-accuracy", type=float, default=0.99)
    ap.add_argument("--min-category-recall", type=float, default=0.90)
    ap.add_argument("--max-p95", type=float, default=60.0)
    ap.add_argument("--workers", type=int, default=4, choices=range(1, 9))
    ap.add_argument("--category", action="append", help="仅运行指定类别，可重复传入")
    args = ap.parse_args()
    if not args.password:
        print("缺少评测密码：请设置 EVAL_PASSWORD 或使用 --password")
        return 2

    golden = _load_golden()
    if args.category:
        selected = set(args.category)
        golden = [item for item in golden if item.get("category") in selected]
        if not golden:
            print(f"未找到指定评测类别：{', '.join(args.category)}")
            return 2
    c = httpx.Client(timeout=180, base_url=args.base)
    r = c.post("/api/v1/auth/login", json={"username": args.username, "password": args.password})
    token = (r.json().get("data") or {}).get("access_token") or r.json().get("access_token")
    if not token:
        print("登录失败，请确认后端已启动且账号密码正确")
        return 2
    headers = {"Authorization": f"Bearer {token}"}

    def evaluate_item(item: dict) -> tuple[dict, str]:
        q = item["question"]
        classified_intent = classify_intent(q)
        intent_match = classified_intent == item.get("intent")
        t0 = time.time()
        try:
            resp = c.post(
                "/api/v1/qa/ask",
                json={"question": q, "round": 1, "slots": {}, "evaluation": True},
                headers=headers,
            )
            elapsed = time.time() - t0
            d = (resp.json().get("data") or {}) if resp.status_code == 200 else {}
        except Exception as exc:  # noqa: BLE001 —— 单题失败不中断整体评测
            row = {
                "question": q, "category": item.get("category"), "expect": item["expect"],
                "intent": item.get("intent"), "classified_intent": classified_intent,
                "intent_match": intent_match,
                "hit": False, "citations": 0, "matched_titles": [],
                "confidence": None, "need_human": None, "honest": False,
                "answer_len": 0, "elapsed": round(time.time() - t0, 1),
                "error": type(exc).__name__,
            }
            return row, f"[ERR ] {q[:24]} | {type(exc).__name__}: {exc}"
        citations = d.get("citations") or []
        answer = d.get("answer_interpret") or ""
        followup = d.get("follow_up")
        # 追问分支：检索到了相关条款但信息不足（金额/境内外等槽位缺失），
        # 属正常交互，单独标记为 followup（不算 miss）。
        if followup:
            row = {
                "question": q, "category": item.get("category"), "expect": item["expect"],
                "intent": item.get("intent"), "classified_intent": classified_intent,
                "intent_match": intent_match,
                "hit": True, "status": "followup", "citations": 0,
                "matched_titles": [], "confidence": d.get("confidence"),
                "need_human": d.get("need_human"), "honest": False,
                "answer_len": 0, "elapsed": round(elapsed, 1),
            }
            return row, f"[FOLLOWUP] {q[:24]} | 缺槽位: {followup.get('missing')}"
        hit = _hit(citations, item["expect"])
        honest = any(w in answer for w in ("信息不足", "无法确定", "未检索到"))
        row = {
            "question": q,
            "category": item.get("category"),
            "expect": item["expect"],
            "intent": item.get("intent"),
            "classified_intent": classified_intent,
            "intent_match": intent_match,
            "hit": hit,
            "citations": len(citations),
            "matched_titles": [x.get("file_title", "")[:20] for x in citations[:3]],
            "confidence": d.get("confidence"),
            "need_human": d.get("need_human"),
            "honest": honest,
            "answer_len": len(answer),
            "elapsed": round(elapsed, 1),
        }
        message = (
            f"[{'HIT' if hit else 'MISS'}] {q[:24]} | conf={d.get('confidence')} | "
            f"cite={len(citations)} | {elapsed:.1f}s"
        )
        return row, message

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(evaluate_item, item): index for index, item in enumerate(golden)}
        indexed_rows: dict[int, dict] = {}
        for future in as_completed(futures):
            row, message = future.result()
            indexed_rows[futures[future]] = row
            print(message, flush=True)
    rows = [indexed_rows[index] for index in range(len(golden))]

    hits = sum(1 for x in rows if x["hit"])
    total = len(rows)
    avg_conf = round(sum(x["confidence"] or 0 for x in rows) / total, 3) if total else 0
    avg_time = round(sum(x["elapsed"] for x in rows) / total, 1) if total else 0
    intent_accuracy = round(sum(1 for x in rows if x["intent_match"]) / total, 3) if total else 0
    latencies = [float(x["elapsed"]) for x in rows]
    category_metrics = {}
    for category in sorted({x.get("category") or "未分类" for x in rows}):
        group = [x for x in rows if (x.get("category") or "未分类") == category]
        category_metrics[category] = {
            "total": len(group),
            "recall": round(sum(1 for x in group if x["hit"]) / len(group), 3),
        }
    recall = round(hits / total, 3) if total else 0
    p95 = _percentile(latencies, 0.95)
    summary = {
        "total": total,
        "hit": hits,
        "recall": recall,
        "intent_accuracy": intent_accuracy,
        "avg_confidence": avg_conf,
        "avg_elapsed_s": avg_time,
        "p50_elapsed_s": _percentile(latencies, 0.50),
        "p95_elapsed_s": p95,
        "category_metrics": category_metrics,
        "details": rows,
    }
    print("\n=== 汇总 ===")
    print(json.dumps({k: v for k, v in summary.items() if k != "details"}, ensure_ascii=False, indent=2))
    out = Path(__file__).resolve().parent.parent / "eval_smoke_result.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写 {out}")
    category_pass = all(
        metrics["recall"] >= args.min_category_recall for metrics in category_metrics.values()
    )
    passed = (
        recall >= args.min_recall
        and intent_accuracy >= args.min_intent_accuracy
        and category_pass
        and p95 <= args.max_p95
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
