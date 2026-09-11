# -*- coding: utf-8 -*-
"""PDF 路由：探测文字层，决定每页走「电子版解析」还是「OCR」。"""
from __future__ import annotations
import os
import re
import pdfplumber
from app.models import SourceInfo, PageInfo, LayoutKind

WATERMARK_RE = re.compile(r"\{#\{?\s*QQ.*?#\}\}?", re.S)
MIN_TEXT_CHARS = 120          # 去掉水印后，一页正文文字层字符数低于此值判为扫描页


def _clean_text(t: str) -> str:
    if not t:
        return ""
    t = WATERMARK_RE.sub("", t)
    t = re.sub(r"^\s*\{?#\{?.*?\}?#?\}\s*$", "", t, flags=re.S)
    return t.strip()


def inspect_pdf(path: str, max_pages: int | None = None) -> SourceInfo:
    """探测 PDF：逐页文字层字符数 → digital / scanned / mixed，并给出诊断信息。"""
    info = SourceInfo(path=os.path.abspath(path), name=os.path.basename(path))
    if not path or not os.path.exists(path):
        info.notes.append("文件不存在")
        return info

    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        pages = pdf.pages[:max_pages] if max_pages else pdf.pages
        for i, page in enumerate(pages, 1):
            raw = page.extract_text() or ""
            chars = len(_clean_text(raw))
            n_tables = 0
            try:
                n_tables = len(page.find_tables())
            except Exception:
                pass
            n_images = len(page.images)
            kind = "digital" if chars >= MIN_TEXT_CHARS else "scanned"
            info.page_infos.append(PageInfo(
                page=i, width=float(page.width), height=float(page.height),
                text_chars=chars, kind=kind, tables=n_tables, images=n_images))
        info.pages = total

    info.total_chars = sum(p.text_chars for p in info.page_infos)
    kinds = {p.kind for p in info.page_infos}
    if kinds == {"digital"}:
        info.kind = LayoutKind.digital
    elif kinds == {"scanned"}:
        info.kind = LayoutKind.scanned
    else:
        info.kind = LayoutKind.mixed
    info.has_text_layer = info.kind != LayoutKind.scanned

    if info.kind == LayoutKind.digital:
        info.notes.append("全页存在文字层：将直接解析 PDF 文本（跳过 OCR）")
    elif info.kind == LayoutKind.scanned:
        info.notes.append("全页无文字层（纯扫描件）：将渲染后 OCR 识别")
    else:
        d = sum(1 for p in info.page_infos if p.kind == "digital")
        info.notes.append("混合卷：%d 页走文字层、%d 页走 OCR" % (d, len(info.page_infos) - d))
    return info


def digital_pages(info: SourceInfo) -> list:
    return [p.page for p in info.page_infos if p.kind == "digital"]


def scanned_pages(info: SourceInfo) -> list:
    return [p.page for p in info.page_infos if p.kind == "scanned"]
