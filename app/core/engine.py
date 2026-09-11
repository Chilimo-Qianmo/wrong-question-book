# -*- coding: utf-8 -*-
"""引擎编排：探测渠道 → 解析版面 → 识别题目 → （可选）导出配图。"""
from __future__ import annotations
import os
import re
import tempfile
import time
from app.models import DetectPayload, QuestionOut, Gap, SourceInfo, LayoutKind
from app.core import pdf_router, recognize, cache as cache_mod
from app.core.layout import Layout
from app.core.figures import assign_to_questions, crop_from_page, crop_from_image, safe_name


def _base_dir(out_dir: str | None) -> str:
    if out_dir:
        d = os.path.abspath(out_dir)
        return os.path.dirname(d) if os.path.isdir(d) or d.endswith(("\\", "/")) else os.path.dirname(d)
    return tempfile.gettempdir()


def work_dirs(out_dir: str | None):
    base = _base_dir(out_dir)
    cache_dir = os.path.join(base, ".cache")
    return cache_dir, os.path.join(cache_dir, "render")


def build_layout(pdf: str, info: SourceInfo, out_dir: str | None = None, scale: float = 3.0,
                 use_cache: bool = True, prefer_text_layer: bool = True, progress=None) -> Layout:
    from app.core import digital, scanned
    cache_dir, render_root = work_dirs(out_dir)
    if use_cache:
        try:
            lay = cache_mod.try_load(cache_dir, pdf, scale)
        except Exception:                               # noqa: BLE001
            lay = None                                  # 缓存永远不能影响识别
        if lay is not None:
            if progress:
                progress("命中版面缓存（%s 通道），跳过解析" % lay.kind, 1, 1)
            return lay

    dig_pages = pdf_router.digital_pages(info) if prefer_text_layer else []
    sca_pages = pdf_router.scanned_pages(info)

    lay = Layout(path=os.path.abspath(pdf), scale=scale)
    if dig_pages:
        if progress:
            progress("电子版通道：解析 PDF 文字层（%d 页）..." % len(dig_pages), 0, 1)
        d = digital.extract_digital(pdf, pages=dig_pages, progress=progress)
        _merge_into(lay, d)
    if sca_pages:
        if progress:
            progress("扫描版通道：渲染 + OCR（%d 页）..." % len(sca_pages), 0, 1)
        render_dir = os.path.join(render_root, cache_mod.fingerprint(pdf))
        s = scanned.extract_scanned(pdf, sca_pages, render_dir, scale=scale, progress=progress)
        _merge_into(lay, s)
        lay.render_paths.update(s.render_paths)
    lay.kind = info.kind.value
    lay.page_kind = {p.page: p.kind for p in info.page_infos}
    if use_cache:
        try:
            cache_mod.save(cache_dir, pdf, scale, lay)
        except Exception:                               # noqa: BLE001
            pass
    return lay


def _merge_into(dst: Layout, src: Layout) -> None:
    dst.boxes.extend(src.boxes)
    dst.dropped.extend(src.dropped)
    dst.tables.extend(src.tables)
    dst.figures.extend(src.figures)
    dst.page_sizes.update(src.page_sizes)
    dst.page_kind.update(src.page_kind)
    for n in src.notes:
        if n not in dst.notes:
            dst.notes.append(n)
    dst.boxes.sort(key=lambda b: (b.page, b.y0, b.x0))
    dst.dropped.sort(key=lambda b: (b.page, b.y0, b.x0))


def make_keyword(text: str) -> str:
    if not text:
        return ""
    s = text.strip()
    m = re.search(r"\d{4}", s)
    if m:
        s = s[:m.start()]
    s = re.sub(r"[、，。．\s]*$", "", s)
    return s or text.strip()


def keyword_from_layout(lay: Layout) -> str:
    from app.core.lines import build_lines
    for ln in build_lines(lay.boxes)[:20]:
        t = ln.text.strip()
        if ("考试" in t or "试卷" in t) and len(t) >= 5:
            return make_keyword(t)
    return ""


def detect(pdf: str, config: dict | None = None, out_dir: str | None = None,
           use_cache: bool = True, prefer_text_layer: bool = True, scale: float = 3.0,
           progress=None) -> DetectPayload:
    t0 = time.time()
    info = pdf_router.inspect_pdf(pdf)
    if progress:
        progress("来源判定：%s（%d 页）" % (info.kind.value, info.pages), 0, 1)
    lay = build_layout(pdf, info, out_dir, scale, use_cache, prefer_text_layer, progress)
    if progress:
        progress("识别题目结构 ...", 1, 1)
    res = recognize.detect_questions(lay, config=config, progress=progress)
    payload = DetectPayload(
        source=info,
        questions=[QuestionOut(**q) for q in res["questions"]],
        gaps=[Gap(**g) for g in res["gaps"]],
        declared_count=res["declared_count"],
        keyword=keyword_from_layout(lay),
        elapsed_ms=int((time.time() - t0) * 1000),
    )
    if res["notes"]:
        payload.source.notes.extend([n for n in res["notes"] if n not in payload.source.notes])
    return payload


def layout_for(pdf: str, out_dir: str | None = None, scale: float = 3.0, use_cache: bool = True,
               progress=None) -> tuple:
    info = pdf_router.inspect_pdf(pdf)
    lay = build_layout(pdf, info, out_dir, scale, use_cache, True, progress)
    return info, lay


def export_figures(pdf: str, images_root: str, out_dir: str | None = None,
                   scale: float = 3.0, questions=None, progress=None) -> dict:
    """把版面里的插图归属到题并导出到 图片/<题号>/。返回 {qno: [文件名...]}"""
    from app.core.lines import build_lines
    info, lay = layout_for(pdf, out_dir, scale, True, progress)
    lines = build_lines(lay.boxes)
    notes = []
    qs, gaps, declared = recognize.group_questions(lines, notes)
    spans = recognize.question_spans(qs, lay)
    assign = assign_to_questions(lay.figures, spans)
    result = {}
    for qno, figs in sorted(assign.items()):
        qdir = os.path.join(images_root, str(qno))
        os.makedirs(qdir, exist_ok=True)
        names = []
        for k, f in enumerate(figs, 1):
            name = "auto_p%d_%d.png" % (f.page, k)
            dst = os.path.join(qdir, name)
            ok = None
            if f.page in lay.render_paths:
                # 渲染图是 scale 倍 72dpi，写入 DPI 后 Word 里即可按原图尺寸插入
                ok = crop_from_image(lay.render_paths[f.page], f.bbox, dst, dpi=72.0 * scale)
            if not ok:
                ok = crop_from_page(pdf, f.page, f.bbox, dst,
                                    resolution=int(72 * max(1.5, scale)))
            if ok:
                names.append(name)
        if names:
            result[qno] = names
    return result
