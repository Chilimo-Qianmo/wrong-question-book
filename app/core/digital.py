# -*- coding: utf-8 -*-
"""电子版 PDF 解析：pdfplumber 文字层 + 结构化表格 + 内嵌图像。

实测（选择题训练-2.pdf）：文字行/表格/图片均一次到位，无需 OCR，无坐标抖动。
"""
from __future__ import annotations
import pdfplumber
from app.core.layout import Layout, TableRegion, FigureRegion
from app.core.lines import Box, is_page_furniture
from app.core.pdf_router import WATERMARK_RE


def _inside(px: float, py: float, bbox, pad: float = 2.0) -> bool:
    x0, y0, x1, y1 = bbox
    return x0 - pad <= px <= x1 + pad and y0 - pad <= py <= y1 + pad


def _vector_figure_regions(page, boxes, table_bboxes) -> list:
    """矢量插图区域（图是画出来的电子卷）。保守判定：区域内需有 ≥4 个短文本标签。"""
    cands = []
    for attr in ("rects", "curves", "lines"):
        for d in getattr(page, attr, []) or []:
            w = abs(d.get("x1", 0) - d.get("x0", 0))
            h = abs(d.get("bottom", 0) - d.get("top", 0))
            if w * h >= 1500:
                x0, x1 = sorted((d["x0"], d["x1"]))
                y0, y1 = sorted((d["top"], d["bottom"]))
                cands.append([x0, y0, x1, y1])
    if not cands:
        return []
    # 合并重叠候选
    merged = []
    for b in cands:
        for m in merged:
            if not (b[0] > m[2] + 5 or b[2] < m[0] - 5 or b[1] > m[3] + 5 or b[3] < m[1] - 5):
                m[0], m[1] = min(m[0], b[0]), min(m[1], b[1])
                m[2], m[3] = max(m[2], b[2]), max(m[3], b[3])
                break
        else:
            merged.append(list(b))
    out = []
    for m in merged:
        w, h = m[2] - m[0], m[3] - m[1]
        if w < 100 or h < 60:
            continue
        # 与已知表格重叠过大则跳过
        ov = 0.0
        for tb in table_bboxes:
            ix = min(m[2], tb[2]) - max(m[0], tb[0])
            iy = min(m[3], tb[3]) - max(m[1], tb[1])
            if ix > 0 and iy > 0:
                ov = max(ov, (ix * iy) / max(1.0, w * h))
        if ov > 0.4:
            continue
        labels = [b for b in boxes
                  if _inside(b.cx, b.cy, m) and len(b.text.strip()) <= 12]
        if len(labels) >= 4:
            out.append((m[0], m[1], m[2], m[3]))
    return out


def extract_digital(path: str, pages: list | None = None, progress=None,
                    detect_vector: bool = True) -> Layout:
    lay = Layout(path=path, kind="digital")
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages, 1):
            if pages and i not in pages:
                continue
            if progress:
                progress("解析文字层 第 %d/%d 页" % (i, total), i, total)
            lay.page_kind[i] = "digital"
            lay.page_sizes[i] = (float(page.width), float(page.height))

            # --- 表格（结构化） ---
            tbboxes = []
            try:
                for t in page.find_tables():
                    bbox = tuple(float(v) for v in t.bbox)
                    cells = None
                    try:
                        cells = t.extract()
                    except Exception:
                        cells = None
                    lay.tables.append(TableRegion(page=i, bbox=bbox, cells=cells, source="structured"))
                    tbboxes.append(bbox)
            except Exception as e:
                lay.notes.append("第 %d 页表格解析失败：%s" % (i, e))

            # --- 内嵌图像 ---
            fbboxes = []
            for im in page.images:
                w = im["x1"] - im["x0"]
                h = im["bottom"] - im["top"]
                if w < 40 or h < 30:
                    continue
                bbox = (float(im["x0"]), float(im["top"]), float(im["x1"]), float(im["bottom"]))
                lay.figures.append(FigureRegion(page=i, bbox=bbox,
                                                width=int(im.get("srcsize", (0, 0))[0]),
                                                height=int(im.get("srcsize", (0, 0))[1])))
                fbboxes.append(bbox)

            # --- 文本块 ---
            words = page.extract_words(extra_attrs=["size"], keep_blank_chars=False,
                                       use_text_flow=False) or []
            boxes = []
            for w in words:
                t = (w.get("text") or "").strip()
                if not t:
                    continue
                boxes.append(Box(text=t, x0=float(w["x0"]), y0=float(w["top"]),
                                 x1=float(w["x1"]), y1=float(w["bottom"]),
                                 page=i, source="text", conf=1.0))

            # --- 矢量插图区域（保守） ---
            vregions = []
            if detect_vector:
                try:
                    vregions = _vector_figure_regions(page, boxes, tbboxes)
                    for v in vregions:
                        lay.figures.append(FigureRegion(page=i, bbox=v))
                        fbboxes.append(v)
                except Exception:
                    vregions = []

            ph = float(page.height)
            for b in boxes:
                if WATERMARK_RE.search(b.text):
                    b.absent = "水印"
                elif any(_inside(b.cx, b.cy, tb) for tb in tbboxes):
                    b.absent = "表格区域内的文字（已结构化提取）"
                elif any(_inside(b.cx, b.cy, fb) for fb in fbboxes):
                    b.absent = "插图区域内的文字（图注）"
                else:
                    reason = is_page_furniture(b, ph)
                    if reason:
                        b.absent = reason
                if b.absent:
                    lay.dropped.append(b)
                else:
                    lay.boxes.append(b)
    return lay
