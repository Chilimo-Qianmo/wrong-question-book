# -*- coding: utf-8 -*-
"""表格检测与结构化。

* 电子版：直接用 pdfplumber 的结构化结果（digital.py 负责）。
* 扫描版：OpenCV 形态学线检测找出表格外框（实测可命中题10/题14），
  再按检测到的横竖线切分单元格，并把 OCR 文本按中心点填进格子。
"""
from __future__ import annotations
import cv2
import numpy as np
from app.core.layout import TableRegion


def detect_ruled_regions(img, min_w_ratio: float = 0.12, min_h: int = 40,
                         min_area: int = 20000) -> list:
    """返回线框表格区域 bbox 列表（像素坐标）。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    inv = 255 - gray
    bw = cv2.adaptiveThreshold(inv, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    h, w = bw.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, w // 25), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, h // 25)))
    horiz = cv2.dilate(cv2.erode(bw, hk), hk)
    vert = cv2.dilate(cv2.erode(bw, vk), vk)
    grid = cv2.bitwise_or(horiz, vert)
    cnts, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, ww, hh = cv2.boundingRect(c)
        if ww >= w * min_w_ratio and hh >= min_h and ww * hh >= min_area:
            out.append([x, y, x + ww, y + hh])
    out.sort(key=lambda b: (b[1], b[0]))
    return _merge_overlapping(out)


def _merge_overlapping(boxes, tol: int = 12) -> list:
    merged = []
    for b in boxes:
        for m in merged:
            if not (b[0] > m[2] + tol or b[2] < m[0] - tol or b[1] > m[3] + tol or b[3] < m[1] - tol):
                m[0], m[1] = min(m[0], b[0]), min(m[1], b[1])
                m[2], m[3] = max(m[2], b[2]), max(m[3], b[3])
                break
        else:
            merged.append(list(b))
    return merged


def _line_positions(binary, horizontal: bool, lo: int, hi: int) -> list:
    """在给定带宽内找出横线（或竖线）的坐标。"""
    if horizontal:
        proj = binary[lo:hi, :].sum(axis=1)
    else:
        proj = binary[:, lo:hi].sum(axis=0)
    thr = proj.max() * 0.5 if proj.max() > 0 else 0
    pos, run = [], []
    for i, v in enumerate(proj):
        if v >= thr and thr > 0:
            run.append(i)
        else:
            if len(run) >= 2:
                pos.append(int(sum(run) / len(run)))
            run = []
    if len(run) >= 2:
        pos.append(int(sum(run) / len(run)))
    return [p + (lo if horizontal else lo) for p in pos]


def cells_from_lines(img, bbox, boxes) -> list | None:
    """按线框切分单元格，并把文本块按中心点填格。boxes 为本页文本块（像素坐标）。"""
    x0, y0, x1, y1 = [int(v) for v in bbox]
    x0, y0 = max(0, x0), max(0, y0)
    if x1 - x0 < 40 or y1 - y0 < 30:
        return None
    gray = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    inv = 255 - gray
    bw = cv2.adaptiveThreshold(inv, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    h, w = bw.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 3), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 3)))
    horiz = cv2.dilate(cv2.erode(bw, hk), hk)
    vert = cv2.dilate(cv2.erode(bw, vk), vk)
    rows = _line_positions(horiz, True, 0, h)
    cols = _line_positions(vert, False, 0, w)
    if len(rows) < 2 or len(cols) < 2:
        return None
    rows = [0] + rows + [h]
    cols = [0] + cols + [w]
    grid = [[[] for _ in range(len(cols) - 1)] for _ in range(len(rows) - 1)]
    for b in boxes:
        cx, cy = (b.x0 + b.x1) / 2 - x0, (b.y0 + b.y1) / 2 - y0
        if not (0 <= cx <= w and 0 <= cy <= h):
            continue
        ri = next((i for i in range(len(rows) - 1) if rows[i] <= cy < rows[i + 1]), None)
        ci = next((i for i in range(len(cols) - 1) if cols[i] <= cx < cols[i + 1]), None)
        if ri is None or ci is None:
            continue
        grid[ri][ci].append((b.y0, b.x0, b.text.strip()))
    out = []
    for r in grid:
        row = []
        for cell in r:
            cell.sort()
            row.append(" ".join(t for _, _, t in cell).strip())
        out.append(row)
    if sum(1 for r in out for c in r if c) < 4:
        return None
    return out
