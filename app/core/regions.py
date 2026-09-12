# -*- coding: utf-8 -*-
"""原卷区域裁剪：核对页右侧「原题区域」、配图预览、放大镜共用。

加固要点（v2.3.1）：
* 扫描页直接从「已渲染的页面图」裁切（毫秒级），不再每次让 pdfplumber 重新栅格化；
* 所有 PDFium 渲染串行化（PDFium 非线程安全，并发渲染可能卡住或崩溃）；
* 两条路径互为兜底：任一方式失败自动换另一种，并把原因写进异常信息；
* 同一区域只渲染一次（按 PDF 指纹 + 区域 + DPI 落盘缓存）。
"""
from __future__ import annotations
import hashlib
import os
import threading

_LOCK = threading.RLock()          # PDFium 串行化

from app.core import cache as cache_mod
from app import paths


def default_cache_dir() -> str:
    """区域裁剪缓存的固定位置。

    必须与 out_dir 无关：识别预热用的是请求里的 out_dir，而 /api/media/region
    用的是设置里的 out_dir，来源页的输出目录并不一定写进设置，
    用同一定位才能让预热真正命中。
    """
    return os.path.join(paths.data_dir(), ".cache")


def render_page_path(pdf: str, page: int, scale: float = 3.0) -> str:
    """识别时渲染的页面图路径（与 scanned.extract_scanned 保持一致）。"""
    return os.path.join(default_cache_dir(), "render", cache_mod.fingerprint(pdf),
                        "page_%03d.png" % page)


def region_cache_path(cache_dir: str, pdf: str, page: int, bbox, dpi: int, tag: str = "") -> str:
    key = "%s|%d|%.1f|%.1f|%.1f|%.1f|%d|%s" % (
        cache_mod.fingerprint(pdf), page, bbox[0], bbox[1], bbox[2], bbox[3], dpi, tag)
    return os.path.join(cache_dir, "crop",
                        hashlib.sha1(key.encode()).hexdigest()[:20] + ".png")


def _crop_from_pdf(pdf: str, page: int, box, fp: str, dpi: int) -> str:
    """电子页：pdfplumber 按 PDF 点坐标裁切并渲染。"""
    import pdfplumber
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with _LOCK:
        with pdfplumber.open(pdf) as doc:
            if page < 1 or page > len(doc.pages):
                raise ValueError("页码超出范围")
            pg = doc.pages[page - 1]
            b = (max(0.0, box[0]), max(0.0, box[1]),
                 min(float(pg.width), box[2]), min(float(pg.height), box[3]))
            if b[2] <= b[0] or b[3] <= b[1]:
                raise ValueError("区域超出页面范围")
            tmp = fp + ".tmp"
            pg.crop(b).to_image(resolution=dpi).save(tmp)   # save 会按 resolution 写入 DPI
            os.replace(tmp, fp)
    return fp


def _ensure_render_page(pdf: str, page: int, scale: float) -> str:
    """确保页面渲染图存在（识别时已渲染过则直接复用）。"""
    fp = render_page_path(pdf, page, scale)
    if os.path.exists(fp):
        return fp
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    import pypdfium2 as pdfium
    with _LOCK:
        if os.path.exists(fp):
            return fp
        doc = pdfium.PdfDocument(pdf)
        try:
            if page < 1 or page > len(doc):
                raise ValueError("页码超出范围")
            tmp = fp + ".tmp"
            doc[page - 1].render(scale=float(scale or 3.0)).to_pil().save(tmp)
            os.replace(tmp, fp)
        finally:
            doc.close()
    return fp


def _crop_from_render(pdf: str, page: int, box, fp: str, scale: float) -> str:
    """扫描页：从页面渲染图直接裁切（坐标已是渲染像素）。"""
    from PIL import Image
    rp = _ensure_render_page(pdf, page, scale)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with Image.open(rp) as im:
        x0 = max(0, int(box[0])); y0 = max(0, int(box[1]))
        x1 = min(im.width, int(box[2])); y1 = min(im.height, int(box[3]))
        if x1 - x0 < 4 or y1 - y0 < 4:
            raise ValueError("区域无效（渲染图 %dx%d）" % (im.width, im.height))
        out = im.crop((x0, y0, x1, y1))
        d = max(36.0, 72.0 * float(scale or 3.0))
        tmp = fp + ".tmp"
        out.save(tmp, dpi=(d, d))
        os.replace(tmp, fp)
    return fp


def crop_region(pdf: str, page: int, bbox, space: str = "pdf", scale: float = 1.0,
                dpi: int = 150, cache_dir: str = "") -> str:
    """按区域裁切原卷，返回 PNG 路径（带缓存）。失败抛异常（含具体原因）。"""
    ap = os.path.abspath(pdf or "")
    if not os.path.exists(ap) or not ap.lower().endswith(".pdf"):
        raise ValueError("不是有效的 PDF 路径：%s" % (pdf or "(空)"))
    s = float(scale or 1.0)
    x0, y0, x1, y1 = [float(v) for v in bbox]
    if space == "render" and s > 0.01:                 # 渲染像素 → PDF 点
        pdf_box = (x0 / s, y0 / s, x1 / s, y1 / s)
        render_box = (x0, y0, x1, y1)
    else:
        pdf_box = (x0, y0, x1, y1)
        render_box = (x0 * s, y0 * s, x1 * s, y1 * s) if s > 0.01 else (x0, y0, x1, y1)
    if pdf_box[2] <= pdf_box[0] or pdf_box[3] <= pdf_box[1]:
        raise ValueError("区域无效：%s" % (list(bbox),))
    dpi = max(72, min(400, int(dpi or 150)))
    if not cache_dir:
        cache_dir = default_cache_dir()
    tag = "render" if space == "render" else "pdf"
    fp = region_cache_path(cache_dir, ap, page, pdf_box, dpi, tag)
    if os.path.exists(fp):
        return fp

    errors = []
    if space == "render":
        order = ("render", "pdf")
    else:
        order = ("pdf", "render")
    for kind in order:
        try:
            if kind == "render":
                return _crop_from_render(ap, page, render_box, fp, s)
            return _crop_from_pdf(ap, page, pdf_box, fp, dpi)
        except Exception as e:                          # noqa: BLE001
            errors.append("%s: %s" % (kind, e))
    raise RuntimeError("区域裁切失败（%s）" % "；".join(errors))


def warm(pdf: str, questions, out_dir: str = "", dpi: int = 150) -> int:
    """后台预热：把每道题的原题区域先渲染好，核对页打开即显示。"""
    cache_dir = default_cache_dir()
    done = 0
    for q in questions or []:
        for r in (q.get("regions") or []):
            try:
                crop_region(pdf, int(r.get("page") or 1), r.get("bbox") or [],
                            r.get("space") or "pdf", float(r.get("scale") or 1.0),
                            dpi, cache_dir)
                done += 1
            except Exception:                           # noqa: BLE001
                continue
    return done
