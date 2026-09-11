# -*- coding: utf-8 -*-
"""回归测试：把两份真实试卷的识别结果与快照对比。

用法：
    python tests/regression.py                # 对比（缺快照则生成）
    python tests/regression.py --update       # 用当前结果重写快照

说明：扫描卷依赖 OCR，结果可能有轻微波动，因此用相似度阈值（默认 0.95）判定，
      并在报告里给出具体差异，而不是简单 pass/fail。
"""
from __future__ import annotations
import argparse
import difflib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:                                    # Windows 控制台默认 GBK，避免打印时崩
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from app.core import engine                                     # noqa: E402

SNAP_DIR = os.path.join(ROOT, "tests", "snapshots")
CASES = [
    ("digital_选择题训练-2", os.path.join(ROOT, "选择题训练-2.pdf"), 16, 0.999),
    ("scanned_贵阳市生物", os.path.join(ROOT, "贵阳市2026届高三年级摸底考试试卷+生物.pdf"), 15, 0.95),
    ("digital_选择题训练-1", os.path.join(ROOT, "选择题训练-1.pdf"), 16, 0.999),
]


def snapshot_path(name: str) -> str:
    return os.path.join(SNAP_DIR, name + ".json")


def collect(pdf: str) -> dict:
    payload = engine.detect(pdf, out_dir=os.path.join(ROOT, "错题集"), use_cache=True)
    return {
        "qnos": [q.qno for q in payload.questions],
        "declared_count": payload.declared_count,
        "gaps": [[g.expected, g.found] for g in payload.gaps],
        "elapsed_ms": payload.elapsed_ms,
        "questions": {str(q.qno): {"stem": (q.stem or "").strip(),
                                   "options": {k: v.strip() for k, v in q.options.items()},
                                   "source": q.source,
                                   "tables": len(q.tables),
                                   "figures": len(q.figures)}
                      for q in payload.questions},
    }


def compare(name: str, cur: dict, ref: dict, threshold: float) -> tuple:
    problems = []
    if cur["qnos"] != ref["qnos"]:
        problems.append("题号集合不同：当前 %s / 快照 %s" % (cur["qnos"], ref["qnos"]))
    for qno, rq in ref["questions"].items():
        cq = cur["questions"].get(qno)
        if cq is None:
            problems.append("第 %s 题缺失" % qno)
            continue
        r = difflib.SequenceMatcher(None, rq["stem"], cq["stem"]).ratio()
        if r < threshold:
            problems.append("第 %s 题题干相似度 %.3f\n        快照: %s\n        当前: %s"
                            % (qno, r, rq["stem"][:90], cq["stem"][:90]))
        ro, co = rq["options"], cq["options"]
        if set(ro) != set(co):
            problems.append("第 %s 题选项集合不同：%s -> %s" % (qno, sorted(ro), sorted(co)))
        else:
            for k in ro:
                rr = difflib.SequenceMatcher(None, ro[k], co[k]).ratio()
                if rr < threshold:
                    problems.append("第 %s 题选项 %s 相似度 %.3f\n        快照: %s\n        当前: %s"
                                    % (qno, k, rr, ro[k][:70], co[k][:70]))
    return problems, len(ref["questions"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="用当前结果重写快照")
    ap.add_argument("--threshold", type=float, default=None)
    args = ap.parse_args()
    os.makedirs(SNAP_DIR, exist_ok=True)
    failed = 0
    for name, pdf, expect_n, default_thr in CASES:
        if not os.path.exists(pdf):
            print("[跳过] %s（文件不存在）" % name)
            continue
        thr = args.threshold if args.threshold is not None else default_thr
        t0 = time.time()
        cur = collect(pdf)
        print("=" * 74)
        print("### %s：%d 题，用时 %.1fs（阈值 %.2f）" % (name, len(cur["qnos"]), time.time() - t0, thr))
        sp = snapshot_path(name)
        if args.update or not os.path.exists(sp):
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
            print("    已写入快照：%s" % sp)
            continue
        ref = json.load(open(sp, encoding="utf-8"))
        problems, n = compare(name, cur, ref, thr)
        print("    题数 %d（快照 %d）| 缺口 %s" % (len(cur["qnos"]), n, cur["gaps"]))
        if len(cur["qnos"]) < expect_n:
            problems.insert(0, "识别题数 %d 少于预期下限 %d" % (len(cur["qnos"]), expect_n))
        if problems:
            failed += 1
            print("    [差异] 发现 %d 处：" % len(problems))
            for p in problems[:12]:
                print("      - %s" % p)
            if len(problems) > 12:
                print("      ... 其余 %d 处省略" % (len(problems) - 12))
        else:
            print("    [通过]")
    print("=" * 74)
    print("回归结果：%s" % ("全部通过" if failed == 0 else "%d 个用例存在差异" % failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
