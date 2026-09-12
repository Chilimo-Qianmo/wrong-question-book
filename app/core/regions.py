# -*- coding: utf-8 -*-
"""原卷区域裁剪：核对页右侧「原题区域」与配图预览共用。

同一区域只渲染一次（按 PDF 指纹 + 区域 + DPI 落盘缓存），
识别完成后会调用 warm() 在后台预热，保证核对页打开即显示。
"""
from __future__ import annotations
import hashlib
import os

import pdfplumber

from app.core import cache as cache_mod
from app import paths


def default_cache_dir() -> str:
    """区域裁剪缓存的固定位置。

    必须与 out_dir 无关：识别任务的预热用的是请求里的 out_dir，
    而 /api/media/region 用的是设置里的 out_dir，两者可能不同（来源页的输出目录
    并不一定写进设置），用同一定位才能让预热真正命中。
    """
    return os.path.join(paths.data_dir(), ".cache")


def region_cache_path(cache_dir: str, pdf: str, page: int, bbox, dpi: int) -> str:
    key = "%s|%d|%.1f|%.1f|%.1f|%.1f|%d" % (
        cache_mod.fingerprint(pdf), page, bbox[0], bbox[1], bbox[2], bbox[3], dpi)
    return os.path.join(cache_dir, "crop",
                        hashlib.sha1(key.encode()).hexdigest()[:20] + ".png")


def crop_region(pdf: str, page: int, bbox, space: str = "pdf", scale: float = 1.0,
                dpi: int = 150, cache_dir: str = "") -> str:
    """按区域裁切原卷，返回 PNG 路径（带缓存）。失败抛异常。"""
    ap = os.path.abspath(pdf)
    if not os.path.exists(ap) or not ap.lower().endswith(".pdf"):
        raise ValueError("不是有效的 PDF 路径")
    s = float(scale or 1.0)
    x0, y0, x1, y1 = [float(v) for v in bbox]
    if space == "render" and s > 0.01:            # 渲染图像素 → PDF 点
        x0, y0, x1, y1 = x0 / s, y0 / s, x1 / s, y1 / s
    if x1 <= x0 or y1 <= y0:
        raise ValueError("区域无效")
    dpi = max(72, min(400, int(dpi or 150)))
    if not cache_dir:
        cache_dir = default_cache_dir()
    fp = region_cache_path(cache_dir, ap, page, (x0, y0, x1, y1), dpi)
    if os.path.exists(fp):
        return fp
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with pdfplumber.open(ap) as doc:
        if page < 1 or page > len(doc.pages):
            raise ValueError("页码超出范围")
        pg = doc.pages[page - 1]
        box = (max(0.0, x0), max(0.0, y0),
               min(float(pg.width), x1), min(float(pg.height), y1))
        img = pg.crop(box).to_image(resolution=dpi)
        img.save(fp)          # PageImage.save 会按 resolution 自动写入 DPI
    return fp


def warm(pdf: str, questions, out_dir: str = "", dpi: int = 150) -> int:
    """后台预热：把每道题的原题区域先渲染好，核对页就不用等。

    questions 里每项需带 regions: [{page, bbox, space, scale}, ...]
    返回成功预热的区域个数（失败静默跳过，不影响识别结果）。
    """
    cache_dir = default_cache_dir()          # 与接口读取的位置保持一致
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


def _work_dirs(out_dir: str):
    from app.core.engine import work_dirs
    return work_dirs(out_dir or None)
