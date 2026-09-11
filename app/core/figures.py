# -*- coding: utf-8 -*-
"""配图处理：电子版按图片 bbox 抽取并自动归属题目；扫描版按候选区域裁剪。"""
from __future__ import annotations
import os
import re
import pdfplumber
from app.core.layout import FigureRegion

SAFE_RE = re.compile(r'[\\/:*?"<>|]+')


def safe_name(s: str) -> str:
    return SAFE_RE.sub("_", str(s)).strip("_") or "x"


def export_digital_figures(path: str, pages: list | None = None,
                           min_w: float = 40, min_h: float = 30) -> list:
    """导出电子版 PDF 的内嵌图像（返回 FigureRegion 列表，path 为文件路径）。"""
    out = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            if pages and i not in pages:
                continue
            for k, im in enumerate(page.images, 1):
                w = im["x1"] - im["x0"]
                h = im["bottom"] - im["top"]
                if w < min_w or h < min_h:
                    continue
                out.append(FigureRegion(page=i, bbox=(im["x0"], im["top"], im["x1"], im["bottom"]),
                                        width=int(im.get("srcsize", (0, 0))[0]),
                                        height=int(im.get("srcsize", (0, 0))[1])))
    return out


def crop_from_page(path: str, page_no: int, bbox, out_path: str, resolution: int = 200) -> str | None:
    """把页面某区域渲染裁切保存（电子版矢量图 / 扫描版都可）。"""
    try:
        with pdfplumber.open(path) as pdf:
            page = pdf.pages[page_no - 1]
            crop = page.crop(tuple(bbox))
            img = crop.to_image(resolution=resolution)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            # 注意：pdfplumber 的 PageImage.save() 内部已按 resolution 写入 DPI，
            # 再传 dpi= 会报 "multiple values for keyword argument 'dpi'"。
            img.save(out_path)
            return out_path
    except Exception:
        return None


def crop_from_image(img_path: str, bbox, out_path: str, pad: int = 6, dpi: float = 0) -> str | None:
    """从已渲染的页面图裁切（扫描版）。dpi>0 时写入图片元数据，便于按原图尺寸插入。"""
    try:
        from PIL import Image
        im = Image.open(img_path)
        x0, y0, x1, y1 = [int(v) for v in bbox]
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
        x1, y1 = min(im.width, x1 + pad), min(im.height, y1 + pad)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        out = im.crop((x0, y0, x1, y1))
        if dpi and dpi > 1:
            out.save(out_path, dpi=(dpi, dpi))
        else:
            out.save(out_path)
        return out_path
    except Exception:
        return None


def assign_to_questions(figures: list, question_spans: dict) -> dict:
    """按「题目在页面上的 y 区间」把图归属到题号。

    question_spans: {qno: [(page, y0, y1), ...]}，按题号升序给出该题在页面占用的纵向区间。
    返回 {qno: [FigureRegion, ...]}
    """
    result: dict = {}
    flat = []
    for qno in sorted(question_spans):
        for (pg, y0, y1) in question_spans[qno]:
            flat.append((pg, y0, y1, qno))
    flat.sort(key=lambda t: (t[0], t[1]))
    for fig in figures:
        pg = fig.page
        cy = (fig.bbox[1] + fig.bbox[3]) / 2.0
        best = None
        for (p, y0, y1, qno) in flat:
            if p != pg:
                continue
            if y0 - 8 <= cy <= y1 + 8:
                if best is None or (y1 - y0) < (best[2] - best[1]):
                    best = (p, y0, y1, qno)
        if best is not None:
            result.setdefault(best[3], []).append(fig)
    return result
