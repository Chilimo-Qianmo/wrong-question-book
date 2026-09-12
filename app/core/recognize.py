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
# 扫描件左侧竖排的「准考证号/姓名」等边栏字，可能被 OCR 并进正文行
MARGIN_CHARS = set("号证考准名姓")
DECLARE_RE = re.compile(r"共\s*([0-9０-９]{1,2})\s*[小道]题")


def _norm_digits(s: str) -> str:
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def parse_qno(text: str):
    m = QNO_RE.match(text.strip())
    return int(m.group(1)) if m else None


def line_qno(ln):
    """识别该行是否以题号开头。

    兼容三类排版：
      1) 题号与题干同块：        "13．塞罕坝…"
      2) 题号与分隔符被切成两块： "13" + "．塞罕坝…"
      3) 行首混进了竖排边栏字：   ["姓", "3.我国科考队…"]
         —— 扫描件左侧的「准考证号/姓名」竖排字常被 OCR 聚到与题干同一行，
            而它们按 x 排序时排在题号前面，旧实现只看第一个块就会漏判这道题。
    """
    boxes = ln.boxes
    if not boxes:
        return None

    def _one(i: int):
        if i >= len(boxes):
            return None
        n = parse_qno(boxes[i].text)
        if n is not None:
            return n
        s = boxes[i].text.strip()
        if re.fullmatch(r"\d{1,3}", s) and i + 1 < len(boxes):
            nb = boxes[i + 1]
            if nb.x0 - boxes[i].x1 <= 4.0 and re.match(r"^\s*[．.、:：]", nb.text):
                return int(s)
        return None

    n = _one(0)
    if n is not None:
        return n
    # 跳过行首的边栏杂字（单字：姓名准考证号等），再看下一个块
    idx = 0
    while idx < len(boxes) and idx < 3:
        s = boxes[idx].text.strip()
        if len(s) == 1 and (s in MARGIN_CHARS or not s.isalnum()):
            idx += 1
            continue
        break
    if idx:
        return _one(idx)
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
        # 兜底：期望的题号可能被 OCR 并进了别的文本框中间（扫描件竖排边栏字导致），
        # 这时把该行切开，前半段归上一题，后半段作为这一题的开头，避免整题丢失。
        if qn is None and expected is not None and cur is not None:
            sp = split_line_at_qno(ln, expected)
            if sp is not None:
                head, tail = sp
                if head is not None and head.boxes:
                    questions[cur].append(head)
                notes.append("第 %d 题的题号被并入了上一行的文本框，已自动切分恢复" % expected)
                ln = tail
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


# 被并进正文的题号：前面必须是边栏字或空白，避免把「如图3.所示」这类正文误切成题号
_MERGED_QNO_TPL = r"(?:[%s]|\s)(%d)\s*[．.、:：]\s*" % ("".join(sorted(MARGIN_CHARS)), 0)


def split_line_at_qno(ln, target: int):
    """把「题号被并进某一个文本框中间」的行切成两行。

    例如扫描件里 OCR 输出："…下降名D姓3.我国科考队在太平洋…"
    切分后：前半段仍属于上一题，后半段就是第 3 题的开头。
    返回 (head_line|None, tail_line) 或 None。
    """
    pat = re.compile(r"(?:[%s]|\s)%d\s*[．.、:：]\s*" % ("".join(sorted(MARGIN_CHARS)), target))
    for bi, b in enumerate(ln.boxes):
        m = pat.search(b.text)
        if not m:
            continue
        off = m.start()
        # 题号本身从 m.end(0) 前回溯到数字处，这里直接用匹配结束位置作为切点
        head_txt = b.text[:off].strip()
        tail_txt = b.text[m.end(0):].strip()
        if len(tail_txt) < 2:
            continue
        head_txt = head_txt + b.text[off:m.end(0)][:0]      # 保持简单：题号归到后半段
        from app.core.lines import Box, Line
        head = None
        if head_txt:
            hb = Box(text=head_txt, x0=b.x0, y0=b.y0, x1=b.x1, y1=b.y1,
                     page=b.page, source=b.source, conf=b.conf)
            head = Line(page=b.page)
            head.add(hb)
            for b2 in ln.boxes[:bi]:
                head.add(b2)
            head.sort_boxes()
        tb = Box(text="%d．%s" % (target, tail_txt), x0=b.x0, y0=b.y0, x1=b.x1, y1=b.y1,
                 page=b.page, source=b.source, conf=b.conf)
        tail = Line(page=b.page)
        tail.add(tb)
        for b2 in ln.boxes[bi + 1:]:
            tail.add(b2)
        tail.sort_boxes()
        return head, tail
    return None


def _clean_stem_start(text: str) -> str:
    """去掉题干开头的边栏杂字与题号（如 "姓3.我国科考队…" → "我国科考队…"）。"""
    t = text.strip()
    t = re.sub(r"^[%s\s]+(?=\d{1,3}\s*[．.、:：])" % "".join(sorted(MARGIN_CHARS)), "", t)
    return QNO_RE.sub("", t, count=1).strip()


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
            # 扫描件左侧的竖排边栏字（姓名/准考证号）会混进正文行，
            # 单独一个字且属于边栏字集合时直接丢弃，避免污染题干与选项。
            if len(t) == 1 and t in MARGIN_CHARS:
                i += 1
                continue
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
        # 允许选项字母前面有极短的前导文本（如残留的边栏字），仍视为「行首选项」
        start = 0
        while start < len(atoms) and atoms[start][0] == "txt" and len(atoms[start][1].strip()) <= 1:
            start += 1
        seen_opt = False
        for ai, a in enumerate(atoms):
            if a[0] != "opt":
                continue
            if ai == start or seen_opt:
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
        return _clean_stem_start("".join(ln.text for ln in lines)), {}, []

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

    return _clean_stem_start("".join(stem_parts)), options, letters


def _crop_url(layout, page: int, bbox, dpi: int = 150) -> str:
    """把「版面坐标」转成前端的区域裁剪地址（与右侧原题区域同一套坐标系）。"""
    try:
        from urllib.parse import urlencode
        is_pdf = layout.page_kind.get(page, "scanned") == "digital"
        q = {
            "pdf": layout.path, "page": page,
            "x0": round(bbox[0], 1), "y0": round(bbox[1], 1),
            "x1": round(bbox[2], 1), "y1": round(bbox[3], 1),
            "space": "pdf" if is_pdf else "render",
            "scale": 1.0 if is_pdf else float(layout.scale or 1.0),
            "dpi": dpi,
        }
        return "/api/media/region?" + urlencode(q)
    except Exception:                                   # noqa: BLE001
        return None


class _FakeBox:
    """把一个「被否决的表格」伪装成文本块，复用 dropped 展示通道。"""

    def __init__(self, text, page, y0, y1, x0, x1, reason):
        self.text = text
        self.page = page
        self.y0, self.y1, self.x0, self.x1 = y0, y1, x0, x1
        self.absent = reason

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2.0

    def bbox(self):
        return [self.x0, self.y0, self.x1, self.y1]


def question_regions(questions, layout) -> dict:
    """计算每道题在原始试卷上的区域（供核对页右侧显示「原题区域」）。

    区域 = 该页正文横向范围 ×（本题首行 y → 下一题首行 y），
    这样右侧显示的就是「这道题在卷子上的原始样子」，便于逐字比对。
    """
    page_x: dict = {}
    for b in layout.boxes:
        cur = page_x.get(b.page)
        page_x[b.page] = (min(cur[0], b.x0), max(cur[1], b.x1)) if cur else (b.x0, b.x1)
    ordered = sorted(questions)
    out: dict = {}
    for qi, qno in enumerate(ordered):
        per_page: dict = {}
        for ln in questions[qno]:
            v = per_page.get(ln.page)
            per_page[ln.page] = [min(v[0], ln.y0), max(v[1], ln.y1)] if v else [ln.y0, ln.y1]
        regs = []
        for p in sorted(per_page):
            y0, y1 = per_page[p]
            next_y = None
            for q2 in ordered[qi + 1:]:
                cand = [ln.y0 for ln in questions[q2] if ln.page == p]
                if cand:
                    next_y = min(cand)
                    break
            bottom = (next_y - 2.0) if next_y is not None else layout.page_height(p)
            if bottom <= y0:
                bottom = y1 + 4
            x0, x1 = page_x.get(p, (0.0, layout.page_sizes.get(p, (0.0, 0.0))[0]))
            is_pdf = layout.page_kind.get(p, "scanned") == "digital"
            regs.append({
                "page": p,
                "bbox": [round(x0 - 4, 1), round(max(0.0, y0 - 4), 1),
                         round(x1 + 4, 1), round(bottom, 1)],
                "space": "pdf" if is_pdf else "render",
                "scale": 1.0 if is_pdf else float(layout.scale or 1.0),
            })
        out[qno] = regs
    return out


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
    regions = question_regions(questions, layout)

    # 先筛掉误检表格（答题卡编号条、空表等），再与配图去重：
    # 同一块内容如果既是「表格」又被当成「配图」，只保留表格，避免题里插两遍。
    good_tables, bad_tables = [], []
    for t in layout.tables:
        reason = t.invalid_reason()
        if reason:
            bad_tables.append((t, reason))
        else:
            good_tables.append(t)

    figures = []
    for f in layout.figures:
        dup = None
        fa = max(1.0, (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        for t in good_tables:
            if t.page != f.page:
                continue
            ox = min(f.bbox[2], t.bbox[2]) - max(f.bbox[0], t.bbox[0])
            oy = min(f.bbox[3], t.bbox[3]) - max(f.bbox[1], t.bbox[1])
            if ox > 0 and oy > 0 and (ox * oy) / fa > 0.6:
                dup = t
                break
        if dup is None:
            figures.append(f)

    fig_assign = assign_to_questions(figures, spans) if figures else {}
    tbl_assign, drop_assign = {}, {}
    for t in good_tables:
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
    for t, reason in bad_tables:                       # 误检表格：不进题目，但要看得见
        cy = (t.bbox[1] + t.bbox[3]) / 2.0
        for qno, sp in spans.items():
            if any(p == t.page and y0 - 6 <= cy <= y1 + 6 for (p, y0, y1) in sp):
                drop_assign.setdefault(qno, []).append(_FakeBox(
                    text="[疑似误检的表格] %s" % (t.cells[0] if t.cells else ""),
                    page=t.page, y0=t.bbox[1], y1=t.bbox[3],
                    x0=t.bbox[0], x1=t.bbox[2], reason=reason))
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
            # 检测到的配图还没有落到磁盘，直接用 /api/media/region 按区域裁给前端显示，
            # 否则前端拿到 url/path 都是空，配图位置会显示成破图。
            figures.append({"id": "f%d_%s" % (f.page, int(f.bbox[1])), "page": f.page,
                            "bbox": list(f.bbox), "path": f.path,
                            "url": _crop_url(layout, f.page, f.bbox), "auto": True,
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
            item = dict(f)
            item["auto"] = False
            # 配置里的配图如果与本次自动检测到的是同一张（同页同坐标），跳过，
            # 否则每次「识别→生成」都会把同一张图重复累加进题目。
            bb = item.get("bbox") or []
            if len(bb) >= 4 and any(
                x.page == (item.get("page") or 0)
                and abs(x.bbox[0] - bb[0]) < 4 and abs(x.bbox[1] - bb[1]) < 4
                for x in figures
            ):
                continue
            if not item.get("url") and not item.get("path"):
                bb = item.get("bbox") or []
                if len(bb) >= 4 and layout.path:
                    # 旧版本配置里只存了坐标，这里补上按区域裁剪的地址，
                    # 否则前端拿不到图片会显示「配图暂不可预览」。
                    item["url"] = _crop_url(layout, int(item.get("page") or 1), bb)
            if item.get("url") or item.get("path"):
                figures.append(item)
            else:
                dropped.append({
                    "text": "[配图] 第 %s 页 %s" % (item.get("page"), item.get("bbox")),
                    "page": int(item.get("page") or 0),
                    "bbox": list(item.get("bbox") or []),
                    "reason": "配置里的配图缺少可显示的原图地址，已跳过",
                })

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
            "regions": regions.get(qno, []),
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
