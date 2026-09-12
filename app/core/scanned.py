# -*- coding: utf-8 -*-
"""扫描版 PDF 解析：pypdfium2 渲染 + RapidOCR + OpenCV 线框表格。

与电子版产出同一种 Layout，后续识别逻辑完全复用。
"""
from __future__ import annotations
import os
import pypdfium2 as pdfium
from app.core.layout import Layout, TableRegion, FigureRegion
from app.core.lines import Box, is_page_furniture

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def render_pages(path: str, out_dir: str, pages: list | None = None, scale: float = 3.0) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    pdf = pdfium.PdfDocument(path)
    out = {}
    try:
        for i, page in enumerate(pdf, 1):
            if pages and i not in pages:
                continue
            img = page.render(scale=scale).to_pil()
            fp = os.path.join(out_dir, "page_%03d.png" % i)
            img.save(fp)
            out[i] = fp
    finally:
        pdf.close()
    return out


def ocr_image(fp: str) -> list:
    """返回 Box 列表（像素坐标）。"""
    res, _ = _engine()(fp)
    boxes = []
    if not res:
        return boxes
    for item in res:
        poly, text, score = item[0], item[1], item[2]
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        if not str(text).strip():
            continue
        boxes.append(Box(text=str(text).strip(), x0=float(min(xs)), y0=float(min(ys)),
                         x1=float(max(xs)), y1=float(max(ys)), source="ocr",
                         conf=float(score)))
    return boxes


def detect_table_regions(img_path: str, boxes: list) -> list:
    """OpenCV 线框检测 + 单元格填格。"""
    try:
        import cv2
        from app.core import tables as tbl
    except Exception:
        return []
    img = cv2.imread(img_path)
    if img is None:
        return []
    out = []
    for bbox in tbl.detect_ruled_regions(img):
        cells = None
        try:
            cells = tbl.cells_from_lines(img, bbox, boxes)
        except Exception:
            cells = None
        out.append(TableRegion(page=0, bbox=tuple(float(v) for v in bbox), cells=cells, source="ruled"))
    return out


def extract_scanned(path: str, pages: list, work_dir: str, scale: float = 3.0,
                    progress=None, use_cache: bool = True) -> Layout:
    lay = Layout(path=path, kind="scanned", scale=scale)
    render_dir = work_dir          # 目录由调用方给出，不再多套一层 .render
    if use_cache and os.path.isdir(render_dir):
        paths = {p: os.path.join(render_dir, "page_%03d.png" % p) for p in pages}
        if not all(os.path.exists(v) for v in paths.values()):
            paths = render_pages(path, render_dir, pages, scale)
    else:
        paths = render_pages(path, render_dir, pages, scale)
    lay.render_paths = paths

    from PIL import Image
    total = len(paths)
    for n, (pg, fp) in enumerate(sorted(paths.items()), 1):
        if progress:
            progress("OCR 第 %d/%d 页" % (n, total), n, total)
        lay.page_kind[pg] = "scanned"
        with Image.open(fp) as im:
            lay.page_sizes[pg] = (float(im.width), float(im.height))
        boxes = ocr_image(fp)
        for b in boxes:                       # OCR 结果必须带上页码，否则跨页会被当成同一页
            b.page = pg
        tregs = detect_table_regions(fp, boxes)
        for t in tregs:
            t.page = pg
            lay.tables.append(t)
        tbboxes = [t.bbox for t in tregs]
        ph = lay.page_sizes[pg][1]
        for b in boxes:
            if any(tb[0] - 2 <= b.cx <= tb[2] + 2 and tb[1] - 2 <= b.cy <= tb[3] + 2 for tb in tbboxes):
                b.absent = "表格区域内的文字"
            else:
                reason = is_page_furniture(b, ph)
                if reason:
                    b.absent = reason
            if b.absent:
                lay.dropped.append(b)
            else:
                lay.boxes.append(b)
    return lay
