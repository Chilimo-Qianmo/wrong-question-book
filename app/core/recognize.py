# -*- coding: utf-8 -*-
"""题号 / 题干 / 选项切分与质量评估。这是整个引擎的核心。

相对旧实现的关键改变：
1. 以「行」为单位归题（行聚类见 lines.py），题号与题干同行时不再错位；
2. 题号必须带分隔符（1. / 1．/ 1、/ 1：），不再把「2 条肽链」当题号；
3. 跳号不再吞并/截断：按检测到的题号开新题，并产出 gaps 告警；
4. 选项识别兼容「字母与正文同块」和「字母/分隔符/正文被切成多块」两种排版；
5. 被剔除的文本全部进 dropped[]，绝不静默丢弃。
"""
from __future__ import annotations
import re
from app.core.figures import assign_to_questions

QNO_RE = re.compile(r"^\(?(\d{1,3})\)?\s*[．.、:：]\s*")
OPT_RE = re.compile(r"^[（(]?\s*([A-Da-d])\s*[)）]?\s*[．.、:：]\s*(.*)$")
LETTERS = "ABCDEFGH"
SECTION_HINT = ("选择题", "单选题", "单项选择")
END_RE = re.compile(r"非选择题|主观题|解答题|简答题|计算题")
INSTRUCTION_RE = re.compile(r"注意事项|须知|填涂|铅笔|签字笔|答题卡|本试卷|满分|考试用时|闭卷|评分标准")
DECLARE_RE = re.compile(r"共\s*([0-9０-９]{1,2})\s*[小道]题")


def _norm_digits(s: str) -> str:
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def parse_qno(text: str):
    m = QNO_RE.match(text.strip())
    return int(m.group(1)) if m else None


def line_qno(ln):
    """识别该行是否以题号开头。

    兼容两种排版：题号与分隔符同块（"13．塞罕坝…"），或被切成两块（"13" + "．塞罕坝…"）。
    """
    boxes = ln.boxes
    if not boxes:
        return None
    n = parse_qno(boxes[0].text)
    if n is not None:
        return n
    s = boxes[0].text.strip()
    if re.fullmatch(r"\d{1,3}", s) and len(boxes) > 1:
        nb = boxes[1]
        if nb.x0 - boxes[0].x1 <= 4.0 and re.match(r"^\s*[．.、:：]", nb.text):
            return int(s)
    return None


def is_instruction(text: str) -> bool:
    return bool(INSTRUCTION_RE.search(text))


def is_section_title(text: str, strict: bool = True) -> bool:
    t = text.strip()
    if not any(k in t for k in SECTION_HINT):
        return False
    if "非选择题" in t:
        return False
    if is_instruction(t):
        return False
    if strict:
        return bool(re.search(r"小题|本题共|部分", t)
                    or re.match(r"^[一二三四五六七八九十]\s*[、．.]", t))
    return len(t) <= 20


def find_anchor(lines):
    for strict in (True, False):
        for i, ln in enumerate(lines):
            if is_section_title(ln.text, strict):
                return i, strict
    return None, None


def group_questions(lines, notes: list):
    """返回 (questions: dict[qno, list[Line]], gaps: list[(expected, found)], declared)"""
    anchor, _strict = find_anchor(lines)
    start = anchor + 1 if anchor is not None else 0
    declared = None
    for ln in lines[start:start + 8]:
        m = DECLARE_RE.search(_norm_digits(ln.text))
        if m:
            declared = int(m.group(1))
            break
    if anchor is None:
        notes.append("未找到「选择题」小节标题，已从卷面第一个题号开始识别（置信度下调）")

    questions, gaps = {}, []
    expected, cur = None, None
    first_idx = None
    for i in range(start, len(lines)):
        if line_qno(lines[i]) is not None and not is_instruction(lines[i].text):
            first_idx = i
            break
    if first_idx is None:
        return {}, [], declared

    # 首题题号被漏识别（首个题号是 2）：把 anchor→首个题号 之间的内容补成第 1 题
    if line_qno(lines[first_idx]) == 2:
        pre = [ln for ln in lines[start:first_idx] if not is_section_title(ln.text, False)]
        if any(len(ln.text.strip()) >= 6 for ln in pre):
            questions[1] = pre
            notes.append("第 1 题题号未被识别，已按顺序把其内容归入第 1 题")
            expected = 2

    for ln in lines[first_idx:]:
        qn = line_qno(ln)
        if qn is not None and is_instruction(ln.text):
            qn = None                                  # 「2.回答选择题时…」这类说明不是题号
        if qn is not None and (expected is None or qn >= expected):
            if expected is not None and qn > expected:
                gaps.append((expected, qn))
            cur, expected = qn, qn + 1
            questions.setdefault(qn, [])
            questions[qn].append(ln)
            if declared is not None and qn >= declared:
                break
            continue
        if qn is None and END_RE.search(ln.text):
            break
        if cur is not None:
            questions[cur].append(ln)
    return questions, gaps, declared


def _option_at(ln, i):
    """识别第 i 个块是否为「选项字母」。

    兼容两种排版：
      * 字母与正文在同一个块（OCR 常见）："A．与休眠种子相比…"
      * 字母、分隔符、正文被 pdfplumber 切成多块："A" + "．" + "a点…"
    返回 (字母, 字母后的正文, 消耗的块数) 或 None。
    """
    boxes = ln.boxes
    s = boxes[i].text.strip()
    m = OPT_RE.match(s)
    if m:
        return m.group(1).upper(), m.group(2).strip(), 1
    if re.fullmatch(r"[A-Da-d]", s) and i + 1 < len(boxes):
        nb = boxes[i + 1]
        if nb.x0 - boxes[i].x1 <= 4.0:
            m2 = re.match(r"^\s*[．.、:：)）]\s*(.*)$", nb.text)
            if m2:
                return s.upper(), m2.group(1).strip(), 2
    return None


def _line_atoms(ln):
    """把一行规范化为 [["opt", 字母, 正文], ["txt", 文本], ...]。"""
    atoms, i, boxes = [], 0, ln.boxes
    while i < len(boxes):
        got = _option_at(ln, i)
        if got:
            letter, text, consumed = got
            atoms.append(["opt", letter, text])
            i += consumed
        else:
            t = boxes[i].text.strip()
            if atoms and atoms[-1][0] == "txt":
                atoms[-1][1] += t
            else:
                atoms.append(["txt", t])
            i += 1
    return atoms


def split_question(lines):
    """切分题干与选项，返回 (题干, 选项dict, 已采纳的选项字母列表)。

    选项字母必须：① 是行内首个原子，或同行前面已出现选项字母原子（支持两列选项排版）；
    ② 从 A 开始按序递增（避免正文里的「B 细胞」被当成选项）。
    """
    all_atoms = [_line_atoms(ln) for ln in lines]

    cand = []                       # [(行号, 原子号, 字母)] 合格的字母候选
    for li, atoms in enumerate(all_atoms):
        seen_opt = False
        for ai, a in enumerate(atoms):
            if a[0] != "opt":
                continue
            if ai == 0 or seen_opt:
                cand.append((li, ai, a[1]))
                seen_opt = True

    letters, accepted, first = [], set(), None
    for (li, ai, L) in cand:
        if not letters:
            if L != "A":
                continue
            letters.append(L)
            accepted.add((li, ai))
            first = (li, ai)
        elif L == LETTERS[len(letters)]:
            letters.append(L)
            accepted.add((li, ai))

    if len(letters) < 2 or first is None:
        stem = QNO_RE.sub("", "".join(ln.text for ln in lines).strip(), count=1).strip()
        return stem, {}, []

    stem_parts, options, cur = [], {}, None
    for li, atoms in enumerate(all_atoms):
        for ai, a in enumerate(atoms):
            if (li, ai) < first:
                if a[0] == "txt":
                    stem_parts.append(a[1])
                continue
            if a[0] == "opt" and (li, ai) in accepted:
                cur = a[1]
                options[cur] = a[2]
            elif cur is not None:
                options[cur] += a[1]

    stem = QNO_RE.sub("", "".join(stem_parts).strip(), count=1).strip()
    return stem, options, letters


def question_spans(questions, layout):
    """{qno: [(page, y0, y1), ...]}，用于把图/表/被剔除文本归属到题。"""
    spans = {}
    ordered = sorted(questions)
    for qi, qno in enumerate(ordered):
        per_page = {}
        for ln in questions[qno]:
            p = ln.page
            if p not in per_page:
                per_page[p] = [ln.y0, ln.y1]
            per_page[p][0] = min(per_page[p][0], ln.y0)
            per_page[p][1] = max(per_page[p][1], ln.y1)
        out = []
        for p, (y0, y1) in per_page.items():
            next_y = None
            for q2 in ordered[qi + 1:]:
                cand = [ln.y0 for ln in questions[q2] if ln.page == p]
                if cand:
                    next_y = min(cand)
                    break
            bottom = next_y - 1 if next_y is not None else layout.page_height(p)
            out.append((p, y0 - 4, bottom))
        spans[qno] = out
    return spans


def detect_questions(layout, config: dict | None = None, progress=None):
    """核心识别入口。返回 dict（与 app.models.DetectPayload 对齐）。"""
    from app.core.lines import build_lines
    notes = list(layout.notes)
    lines = build_lines(layout.boxes)
    if progress:
        progress("整理题目结构", 1, 1)
    questions, gaps, declared = group_questions(lines, notes)
    spans = question_spans(questions, layout)

    fig_assign = assign_to_questions(layout.figures, spans) if layout.figures else {}
    tbl_assign, drop_assign = {}, {}
    for t in layout.tables:
        cy = (t.bbox[1] + t.bbox[3]) / 2.0
        for qno, sp in spans.items():
            if any(p == t.page and y0 - 6 <= cy <= y1 + 6 for (p, y0, y1) in sp):
                tbl_assign.setdefault(qno, []).append(t)
                break
    for b in layout.dropped:
        for qno, sp in spans.items():
            if any(p == b.page and y0 - 6 <= b.cy <= y1 + 6 for (p, y0, y1) in sp):
                drop_assign.setdefault(qno, []).append(b)
                break

    cfg = config or {}
    cfg_stems = {str(k): v for k, v in (cfg.get("stems") or {}).items()}
    cfg_opts = {str(k): v for k, v in (cfg.get("options") or {}).items()}
    cfg_tables = {str(k): v for k, v in (cfg.get("tables") or {}).items()}
    cfg_figs = {str(k): v for k, v in (cfg.get("figures") or {}).items()}
    gap_after = {e for (e, _f) in gaps}

    out = []
    for qno in sorted(questions):
        lines_q = questions[qno]
        stem, options, letters = split_question(lines_q)
        src = "text" if all(b.source == "text" for ln in lines_q for b in ln.boxes) else "ocr"
        conf = sum(ln.conf for ln in lines_q) / max(1, len(lines_q))
        warns, dropped = [], []
        for b in drop_assign.get(qno, []):
            dropped.append({"text": b.text, "page": b.page, "bbox": b.bbox(), "reason": b.absent})

        tables, figures = [], []
        for t in tbl_assign.get(qno, []):
            spec = t.as_spec(as_answer=(not options))
            tables.append({"id": "t%d_%s" % (t.page, int(t.bbox[1])), "page": t.page,
                           "bbox": list(t.bbox), "cells": t.cells, "source": t.source,
                           "as_answer": (not options) and bool(spec), "spec": spec or None})
        for f in fig_assign.get(qno, []):
            figures.append({"id": "f%d_%s" % (f.page, int(f.bbox[1])), "page": f.page,
                            "bbox": list(f.bbox), "path": f.path, "url": None, "auto": True,
                            "width": f.width, "height": f.height})

        if cfg_stems.get(str(qno)):
            stem = cfg_stems[str(qno)]
            src = "config" if src == "text" else "mixed"
        if cfg_opts.get(str(qno)):
            options = dict(cfg_opts[str(qno)])
            src = "config" if src == "text" else "mixed"
        if cfg_tables.get(str(qno)):
            tables = [{"id": "cfg_%s" % qno, "page": 0, "bbox": [], "cells": None,
                       "source": "manual",
                       "as_answer": bool(cfg_tables[str(qno)].get("as_answer")),
                       "spec": cfg_tables[str(qno)]}]
        for f in cfg_figs.get(str(qno), []):
            figures.append(dict(f, auto=False))

        if not stem:
            warns.append("题干为空")
            conf *= 0.5
        elif len(stem) < 6:
            warns.append("题干过短，可能被截断")
            conf *= 0.8
        if not options:
            warns.append("未识别到选项")
            conf *= 0.6
        elif len(options) < 4:
            warns.append("仅识别到 %d 个选项（%s）" % (len(options), "".join(sorted(options))))
            conf *= 0.85
        if dropped:
            warns.append("有 %d 处文字被判定为图/表/页眉页脚并忽略，请核对" % len(dropped))
            conf *= max(0.75, 1.0 - 0.02 * len(dropped))
        if tables and any(t.get("as_answer") for t in tables):
            warns.append("本题表格已按「答案表格」处理")
        if qno in gap_after:
            warns.append("下一题号缺号，本题内容可能被并入了后续题目")
            conf *= 0.9
        if anchor_note(notes):
            conf *= 0.9

        out.append({
            "qno": int(qno), "page": lines_q[0].page, "stem": stem, "options": options,
            "source": src, "conf": round(max(0.05, min(1.0, conf)), 3),
            "warnings": warns, "dropped": dropped, "figures": figures, "tables": tables,
            "verified": False,
        })

    gap_models = [{"expected": e, "found": f,
                   "message": "第 %d 题未识别到（下一题直接是第 %d 题）" % (e, f)}
                  for (e, f) in gaps]
    if declared is not None and len(out) != declared:
        notes.append("声明共 %d 小题，实际识别 %d 题" % (declared, len(out)))
    return {"questions": out, "gaps": gap_models, "declared_count": declared, "notes": notes}


def anchor_note(notes) -> bool:
    """是否走了「无小节标题」的兜底路径（用于下调置信度）。"""
    return any("未找到「选择题」小节标题" in n for n in notes)
