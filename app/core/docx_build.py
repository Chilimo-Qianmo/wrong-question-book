# -*- coding: utf-8 -*-
"""Word 错题集生成（移植自旧版 生成错题集.py，版式逐项保持不变）。

版式契约（与旧版一致，全部集中在 LAYOUT 里，可通过 layout 参数逐次覆盖）：
  * 正文 宋体 10.5pt（五号）；行距 1.1；段前段后 0
  * 标题「<姓名> 错题集」16pt 粗体居中；副标题 9pt 灰(595959) 居中
  * 题号标题「第 N 题」12pt 粗体
  * 选项缩进 2 字符；图片居中、宽 6 英寸
  * 页边距上下左右 1.27cm；页眉/页脚距边界 0.8cm
  * 页眉＝学生姓名 9pt 居中；页脚＝居中页码（PAGE 域，9pt）

与旧版的差异（本次移植按要求修复）：
  1. 选项输出顺序改为 for letter in sorted(options)（支持 E 选项，旧代码硬编码 A-D）；
  2. 图片优先取 qmap[qno]["figures"] 中的绝对路径，为空才回退 images_root/题号/ 扫描；
  3. 题目数据键同时兼容新版英文键（stem/options/tables/figures）与旧版中文键
     （题干/选项/表格区域），便于新旧引擎混用。
"""
from __future__ import annotations

import glob
import os
import re
import time
from typing import Any, Iterable, Mapping, Optional, Sequence

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

__all__ = [
    "LAYOUT", "resolve_layout",
    "set_font", "add_title", "add_subtitle", "add_heading", "add_body",
    "add_option", "add_table", "insert_images", "find_question_images",
    "add_question_section", "build_student_docx",
]

# --------------------------------------------------------------------------- #
# 版式常量（要改格式就在这改；build_student_docx(layout=...) 可逐次覆盖）
# --------------------------------------------------------------------------- #
LAYOUT = {
    "font_name": "宋体",
    "body_size": 10.5,        # 五号
    "heading_size": 12,       # 「第 N 题」字号
    "title_size": 16,         # 标题字号
    "line_spacing": 1.1,
    "page_margin_cm": 1.27,
    "hdr_ftr_dist_cm": 0.8,
    # --- 图片 ---
    # natural=True 时按图片自身的物理尺寸（像素 ÷ DPI）插入，尽量与原图一致；
    # image_width_in / image_max_height_in 只作为上限，超出才等比缩小，不放大。
    "image_natural": True,
    "image_width_in": 6.0,          # 宽度上限（英寸，绝对上限）
    "image_width_ratio": 0.6,       # 宽度上限 = 正文宽度 × 该比例（默认 60%）
    "image_max_height_in": 9.2,     # 高度上限（英寸），防止单图超出一页
    "image_dpi_fallback": 144.0,    # 图片未带 DPI 信息时的兜底 DPI（截图通常 1.5~2 倍）
    "text_width_in": 7.27,          # 正文可用宽度（A4 - 左右各 1.27cm）
}

SUBTITLE_SIZE = 9
SUBTITLE_COLOR = "595959"
TABLE_SIZE = 9
PAGE_NUM_SIZE = 9
HAPPY_SIZE = 14
HAPPY_COLOR = "2E7D32"

SUPPORTED_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
_ILLEGAL_FN = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def resolve_layout(layout: Optional[Mapping[str, Any]] = None) -> dict:
    """把调用方传入的 layout 与默认 LAYOUT 合并（None 值忽略，未知键忽略）。"""
    merged = dict(LAYOUT)
    if layout:
        for key, value in dict(layout).items():
            if key in merged and value is not None:
                merged[key] = value
    return merged


# --------------------------------------------------------------------------- #
# 低层工具
# --------------------------------------------------------------------------- #
def set_font(run, size=None, bold=None, color=None, name="宋体"):
    """设置 run 的中英文字体/字号/加粗/颜色（中文必须同时写 eastAsia）。"""
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    return run


def _set_first_line_chars(paragraph, chars):
    """按「字符」设置首行缩进（Word 的 firstLineChars = chars*100）。"""
    pPr = paragraph._p.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)
    ind.set(qn("w:firstLineChars"), str(int(chars * 100)))


def _fmt_para(paragraph, align=None, first_line_chars=0, layout=None):
    """段落基础格式：行距、段前段后 0、可选对齐与首行缩进（字符数）。"""
    L = resolve_layout(layout)
    pf = paragraph.paragraph_format
    pf.line_spacing = L["line_spacing"]
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    if align is not None:
        paragraph.alignment = align
    if first_line_chars:
        _set_first_line_chars(paragraph, first_line_chars)
    return paragraph


def _add_text(doc, text, size=None, bold=False, color=None, align=None,
              first_line_chars=0, layout=None):
    L = resolve_layout(layout)
    p = doc.add_paragraph()
    set_font(p.add_run(text), size=(size or L["body_size"]), bold=bold,
             color=color, name=L["font_name"])
    return _fmt_para(p, align=align, first_line_chars=first_line_chars, layout=layout)


def add_title(doc, text, layout=None):
    L = resolve_layout(layout)
    return _add_text(doc, text, size=L["title_size"], bold=True,
                     align=WD_ALIGN_PARAGRAPH.CENTER, layout=layout)


def add_subtitle(doc, text, layout=None):
    return _add_text(doc, text, size=SUBTITLE_SIZE, color=SUBTITLE_COLOR,
                     align=WD_ALIGN_PARAGRAPH.CENTER, layout=layout)


def add_heading(doc, text, layout=None):
    L = resolve_layout(layout)
    return _add_text(doc, text, size=L["heading_size"], bold=True, layout=layout)


def add_body(doc, text, prefix=None, size=None, first_line_chars=0, layout=None):
    L = resolve_layout(layout)
    size = size or L["body_size"]
    p = doc.add_paragraph()
    if prefix:
        set_font(p.add_run(prefix), size=size, bold=True, name=L["font_name"])
    set_font(p.add_run(text), size=size, name=L["font_name"])
    return _fmt_para(p, first_line_chars=first_line_chars, layout=layout)


def add_option(doc, text, layout=None):
    """选项：缩进 2 字符，宋体五号。"""
    L = resolve_layout(layout)
    return _add_text(doc, text, size=L["body_size"], first_line_chars=2, layout=layout)


def _norm_table(spec) -> Optional[dict]:
    """表格规格归一化：{"columns": [...], "rows": [[...]], "as_answer": bool}。"""
    if not isinstance(spec, Mapping):
        return None
    columns = [("" if c is None else str(c)) for c in (spec.get("columns") or [])]
    rows = []
    for row in (spec.get("rows") or []):
        if row is None:
            continue
        if isinstance(row, (str, bytes)):
            rows.append([row])
        else:
            rows.append([("" if v is None else str(v)) for v in row])
    if not columns and not rows:
        return None
    return {"columns": columns, "rows": rows, "as_answer": bool(spec.get("as_answer"))}


def add_table(doc, spec, layout=None):
    """插入表格（Table Grid，居中，表头加粗 9pt）。"""
    L = resolve_layout(layout)
    norm = _norm_table(spec)
    if not norm:
        return None
    columns, rows = norm["columns"], norm["rows"]
    ncols = len(columns) or (max(len(r) for r in rows) if rows else 0)
    if ncols <= 0:
        return None
    tbl = doc.add_table(rows=1, cols=ncols)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, head in enumerate(columns[:ncols]):
        cell = tbl.rows[0].cells[i]
        cell.text = ""
        set_font(cell.paragraphs[0].add_run(head), size=TABLE_SIZE, bold=True,
                 name=L["font_name"])
    for row in rows:
        cells = tbl.add_row().cells
        for i, val in enumerate(row[:ncols]):
            cells[i].text = ""
            set_font(cells[i].paragraphs[0].add_run(val), size=TABLE_SIZE,
                     name=L["font_name"])
    return tbl


def image_display_size(path, layout=None):
    """计算图片应以多大尺寸插入。

    默认按「原图尺寸」：像素数 ÷ 图片自带 DPI（自动抽取的配图会写入渲染 DPI），
    这样插入后的高度/宽度与试卷上的原图一致，不会被放大得又大又糊。
    仅当超过上限（宽 image_width_in / 高 image_max_height_in）时才等比缩小；
    永远不会放大超过原图尺寸。返回 (宽英寸, 高英寸)。
    """
    L = resolve_layout(layout)
    w_px = h_px = 0
    dpi_x = dpi_y = 0.0
    try:
        from PIL import Image
        with Image.open(path) as im:
            w_px, h_px = im.size
            dpi = im.info.get("dpi") or (0, 0)
            dpi_x = float(dpi[0] or 0)
            dpi_y = float(dpi[1] or 0)
    except Exception:                                   # noqa: BLE001
        pass

    fallback = float(L.get("image_dpi_fallback") or 144.0)
    text_w = float(L.get("text_width_in") or 7.27)
    ratio = float(L.get("image_width_ratio") or 0)
    max_w = float(L.get("image_width_in") or 6.0)
    if ratio > 0:
        max_w = min(max_w, text_w * ratio)      # 图片最多占正文宽度的 ratio
    max_h = float(L.get("image_max_height_in") or 9.2)

    if not L.get("image_natural", True) or not w_px or not h_px:
        return max_w, None                              # 旧行为：给定宽度，高度按比例
    if dpi_x <= 1 or dpi_y <= 1:                        # 没有 DPI 信息时取兜底值
        dpi_x = dpi_y = fallback
    natural_w = w_px / dpi_x
    natural_h = h_px / dpi_y
    scale = 1.0
    if natural_w > max_w:
        scale = max_w / natural_w
    if natural_h * scale > max_h:                       # 超高时优先保证不出页
        scale = max_h / natural_h
    return natural_w * scale, natural_h * scale


def insert_images(doc, img_paths, width_in=None, layout=None):
    """逐张居中插图：默认按原图尺寸（高度与原图一致），超限才等比缩小。

    插入失败的图片在正文留一行提示（不静默丢弃）。
    """
    L = resolve_layout(layout)
    for path in img_paths:
        try:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run()
            if width_in is not None:                    # 显式指定宽度时沿用旧行为
                run.add_picture(path, width=Inches(width_in))
            else:
                w, h = image_display_size(path, layout)
                if h:
                    run.add_picture(path, width=Inches(w), height=Inches(h))
                else:
                    run.add_picture(path, width=Inches(w))
        except Exception as exc:  # noqa: BLE001  —— 与旧版一致：失败要看得见
            add_body(doc, "[图片插入失败:%s: %s]" % (os.path.basename(str(path)), exc),
                     size=9, layout=layout)


def find_question_images(images_root, qno):
    """旧版回退路径：<images_root>/<题号>/ 下的图片，按文件名排序；无则空列表。"""
    if not images_root:
        return []
    qdir = os.path.join(str(images_root), str(qno))
    if not os.path.isdir(qdir):
        return []
    return [f for f in sorted(glob.glob(os.path.join(qdir, "*")))
            if f.lower().endswith(SUPPORTED_EXTS)]


# --------------------------------------------------------------------------- #
# 页面与页眉页脚
# --------------------------------------------------------------------------- #
def _add_page_number(run):
    """在 run 里插入 PAGE 域，显示为 1、2、3 的页码。"""
    fld1 = OxmlElement("w:fldChar")
    fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld2 = OxmlElement("w:fldChar")
    fld2.set(qn("w:fldCharType"), "end")
    run._r.append(fld1)
    run._r.append(instr)
    run._r.append(fld2)


def _setup_section(doc, student_name, layout=None):
    """页边距 1.27cm、页眉＝姓名、页眉上边距/页脚下边距 0.8cm、页脚＝居中页码。"""
    L = resolve_layout(layout)
    margin = Cm(L["page_margin_cm"])
    dist = Cm(L["hdr_ftr_dist_cm"])
    sec = doc.sections[0]
    sec.top_margin = margin
    sec.bottom_margin = margin
    sec.left_margin = margin
    sec.right_margin = margin
    sec.header_distance = dist
    sec.footer_distance = dist

    # 页眉：学生姓名（居中 9pt）
    hp = sec.header.paragraphs[0]
    hp.text = ""
    set_font(hp.add_run(student_name), size=PAGE_NUM_SIZE, name=L["font_name"])
    _fmt_para(hp, align=WD_ALIGN_PARAGRAPH.CENTER, layout=layout)

    # 页脚：居中页码
    fp = sec.footer.paragraphs[0]
    fp.text = ""
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = fp.add_run()
    set_font(run, size=PAGE_NUM_SIZE, name=L["font_name"])
    _add_page_number(run)
    _fmt_para(fp, align=WD_ALIGN_PARAGRAPH.CENTER, layout=layout)


# --------------------------------------------------------------------------- #
# 题目数据结构归一化（兼容新英文键 / 旧中文键）
# --------------------------------------------------------------------------- #
def _norm_options(options) -> dict:
    """选项字典归一化：字母统一大写、值转字符串；同字母重复时保留首个非空值。"""
    out: dict = {}
    for letter, text in (options or {}).items():
        key = str(letter).strip().upper()
        if not key:
            continue
        val = "" if text is None else str(text)
        if out.get(key):
            continue
        out[key] = val
    return out


def _norm_tables(tables) -> list:
    if not tables:
        return []
    if isinstance(tables, Mapping):
        tables = [tables]
    out = []
    for spec in tables:
        norm = _norm_table(spec)
        if norm:
            out.append(norm)
    return out


def _norm_figures(figures) -> list:
    """图片列表归一化：支持 "路径" 或 {"path": ...} / FigureRef 风格 dict。"""
    paths = []
    for item in (figures or []):
        path = ""
        if isinstance(item, str):
            path = item
        elif isinstance(item, Mapping):
            path = item.get("path") or item.get("文件") or ""
        if path:
            paths.append(str(path))
    return paths


def _get_q(qmap, qno):
    """按 int / str 键取题（新旧引擎的 qmap 键类型都可能不同）。"""
    if isinstance(qmap, Mapping):
        if qno in qmap:
            return qmap[qno]
        if str(qno) in qmap:
            return qmap[str(qno)]
        try:
            key = int(qno)
        except (TypeError, ValueError):
            key = None
        if key is not None and key in qmap:
            return qmap[key]
    raise KeyError("qmap 中找不到第 %s 题" % qno)


def question_parts(q, tables=None, qno=None):
    """把题目 dict 拆成 (stem, options, tables, figures)，兼容新旧键名。

    tables 参数为旧版 tspec（{题号: spec}）时按题号取；为 list 时直接使用。
    """
    q = q or {}
    stem = q.get("stem") or q.get("题干") or ""
    options = _norm_options(q.get("options") or q.get("选项"))
    raw_tables = q.get("tables")
    if raw_tables is None:
        raw_tables = q.get("表格") or q.get("table")
    tlist = _norm_tables(raw_tables)
    if tables is not None:
        if isinstance(tables, Mapping):
            spec = tables.get(qno) or tables.get(str(qno))
            extra = _norm_tables(spec)
            if extra:
                tlist = extra
        else:
            extra = _norm_tables(tables)
            if extra:
                tlist = extra
    figures = _norm_figures(q.get("figures") or q.get("图片"))
    return stem, options, tlist, figures


# --------------------------------------------------------------------------- #
# 一道错题的版式：题号 -> 题干 -> 非答案表格 -> 图片 -> 选项/答案表格 -> 标准答案
# --------------------------------------------------------------------------- #
def add_question_section(doc, qno, q, images_root=None, answers=None, layout=None,
                         tables=None):
    stem, options, tlist, figures = question_parts(q, tables=tables, qno=qno)

    add_heading(doc, "第 %s 题" % qno, layout=layout)

    # 题干：首行缩进 2 字符（与选项的悬挂缩进一致）
    add_body(doc, str(stem).strip(), first_line_chars=2, layout=layout)

    # as_answer=False 的表格：题干之后、选项之前
    for spec in [t for t in tlist if not t["as_answer"]]:
        add_table(doc, spec, layout=layout)

    # 图片：优先 qmap[qno]["figures"] 的绝对路径；为空回退 images_root/题号/
    imgs = figures or find_question_images(images_root, qno)
    if imgs:
        insert_images(doc, imgs, layout=layout)

    # 答案位：有选项则输出选项（缩进 2 字符，按字母排序），否则输出 as_answer 表格
    if options:
        for letter in sorted(options):
            text = options[letter]
            if text:
                add_option(doc, "%s. %s" % (letter, text), layout=layout)
    else:
        for spec in [t for t in tlist if t["as_answer"]]:
            add_table(doc, spec, layout=layout)

    if answers:
        ans = answers.get(str(qno))
        if ans is None:
            ans = answers.get(qno)
        if ans:
            add_body(doc, "标准答案：%s" % str(ans), layout=layout)

    _fmt_para(doc.add_paragraph(), layout=layout)   # 题与题之间的分隔段


# --------------------------------------------------------------------------- #
# 生成一份学生文档
# --------------------------------------------------------------------------- #
def _save_with_retry(doc, path, attempts=10, wait=0.4):
    """保存 docx：被 Word 占用时重试（旧版行为），最后一次失败直接抛出。"""
    for attempt in range(attempts):
        try:
            if attempt == 0:
                doc.save(path)
            else:
                tmp = os.path.join(os.path.dirname(path),
                                   ".tmp_%d_%s" % (attempt, os.path.basename(path)))
                doc.save(tmp)
                os.replace(tmp, path)
            return path
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(wait)
    return path


def build_student_docx(name, wrong_qnos, qmap, images_root, exam_title, out_dir,
                       answers=None, layout=None, tables=None) -> str:
    """生成一位学生的错题集 Word，返回生成文件的绝对路径。

    参数
    ----
    name        : 学生姓名（同时用于标题与页眉）
    wrong_qnos  : 错题题号序列（按给定顺序输出）
    qmap        : {题号: {"stem"/"题干", "options"/"选项", "tables", "figures"}}
    images_root : 图片根目录（figures 为空时的回退扫描位置）
    exam_title  : 试卷标题（副标题）
    out_dir     : 输出目录
    answers     : 可选 {题号: 标准答案}
    layout      : 可选版式覆盖（见 LAYOUT）
    tables      : 可选旧版 tspec（{题号: 表格规格}），一般不需要传
    """
    L = resolve_layout(layout)
    wrong = list(wrong_qnos or [])

    doc = Document()
    _setup_section(doc, name, layout=layout)

    # 默认字体：宋体 五号
    st = doc.styles["Normal"]
    st.font.name = L["font_name"]
    st.element.rPr.rFonts.set(qn("w:eastAsia"), L["font_name"])
    st.font.size = Pt(L["body_size"])

    # 标题只要「错题集」三个字；学生姓名放在页眉，不重复出现在正文标题里
    add_title(doc, "错题集", layout=layout)
    wrong_str = "、".join(str(w) for w in wrong) if wrong else "无"
    add_body(doc, "错题题号：%s（共 %d 道）" % (wrong_str, len(wrong)), layout=layout)
    _fmt_para(doc.add_paragraph(), layout=layout)

    if wrong:
        for qno in wrong:
            add_question_section(doc, qno, _get_q(qmap, qno), images_root,
                                 answers=answers, layout=layout, tables=tables)
    else:
        _add_text(doc, "恭喜！本次考试选择题全部正确，无错题。", size=HAPPY_SIZE,
                  bold=True, color=HAPPY_COLOR, align=WD_ALIGN_PARAGRAPH.CENTER,
                  layout=layout)

    os.makedirs(out_dir, exist_ok=True)
    safe = _ILLEGAL_FN.sub("_", str(name)).strip() or "学生"
    fn = os.path.join(out_dir, "错题集_%s.docx" % safe)
    _save_with_retry(doc, fn)
    return os.path.abspath(fn)
