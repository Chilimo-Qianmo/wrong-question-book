# -*- coding: utf-8 -*-
"""指纹化缓存：缓存键绑定 PDF 内容+页数+渲染参数+引擎版本，杜绝跨试卷串用。"""
from __future__ import annotations
import hashlib
import json
import os
import sys

from app import __version__ as APP_VERSION
from app.core.layout import Layout, TableRegion, FigureRegion
from app.core.lines import Box

SCHEMA = 2
ENGINE_TAG = "v2-layout"


def code_signature() -> str:
    """缓存用的「代码版本」签名。

    - 源码运行：对 app/core/*.py 的 大小+修改时间 求签名，改了识别代码旧缓存立即失效
      （曾经踩过：修好行聚类后仍命中旧缓存，误以为修复无效）。
    - 打包运行（PyInstaller）：源码已编译进 PYZ，磁盘上没有 app/core 目录，
      此时不能用 listdir，改用应用版本号。
    本函数保证不抛异常——缓存永远不能影响识别。
    """
    if getattr(sys, "frozen", False):
        return "frozen-" + str(APP_VERSION)
    try:
        d = os.path.dirname(os.path.abspath(__file__))
        names = [n for n in sorted(os.listdir(d)) if n.endswith(".py")]
    except (OSError, NameError, ValueError):
        return "src-unknown"
    if not names:
        return "src-empty"
    try:
        h = hashlib.sha1()
        for name in names:
            fp = os.path.join(d, name)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            h.update(name.encode("utf-8"))
            h.update(str(st.st_size).encode())
            h.update(str(int(st.st_mtime)).encode())
        return h.hexdigest()[:10]
    except Exception:                                   # noqa: BLE001
        return "src-error"


def fingerprint(path: str) -> str:
    st = os.stat(path)
    h = hashlib.sha1()
    h.update(os.path.abspath(path).lower().encode("utf-8"))
    h.update(str(st.st_size).encode())
    h.update(str(int(st.st_mtime)).encode())
    try:
        with open(path, "rb") as f:
            h.update(f.read(512 * 1024))
    except OSError:
        pass
    return h.hexdigest()[:16]


def cache_file(cache_dir: str, path: str, scale: float) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "%s_%s_%s_%s.json" % (
        fingerprint(path), str(scale).replace(".", ""), ENGINE_TAG, code_signature()))


def _box_dump(b):
    return {"t": b.text, "x0": b.x0, "y0": b.y0, "x1": b.x1, "y1": b.y1,
            "p": b.page, "s": b.source, "c": b.conf, "a": b.absent}


def _box_load(d):
    return Box(text=d["t"], x0=d["x0"], y0=d["y0"], x1=d["x1"], y1=d["y1"],
               page=d["p"], source=d["s"], conf=d["c"], absent=d.get("a", ""))


def dump(lay: Layout) -> dict:
    return {
        "schema": SCHEMA, "engine": ENGINE_TAG, "code_sig": code_signature(),
        "path": lay.path, "kind": lay.kind,
        "scale": lay.scale,
        "boxes": [_box_dump(b) for b in lay.boxes],
        "dropped": [_box_dump(b) for b in lay.dropped],
        "tables": [{"page": t.page, "bbox": list(t.bbox), "cells": t.cells,
                    "source": t.source, "image_path": t.image_path} for t in lay.tables],
        "figures": [{"page": f.page, "bbox": list(f.bbox), "path": f.path,
                     "width": f.width, "height": f.height} for f in lay.figures],
        "page_sizes": {str(k): list(v) for k, v in lay.page_sizes.items()},
        "page_kind": {str(k): v for k, v in lay.page_kind.items()},
        "render_paths": {str(k): v for k, v in lay.render_paths.items()},
        "notes": lay.notes,
    }


def load_dict(d: dict) -> Layout:
    lay = Layout(path=d.get("path", ""), kind=d.get("kind", "scanned"), scale=d.get("scale", 3.0))
    lay.boxes = [_box_load(x) for x in d.get("boxes", [])]
    lay.dropped = [_box_load(x) for x in d.get("dropped", [])]
    lay.tables = [TableRegion(page=t["page"], bbox=tuple(t["bbox"]), cells=t.get("cells"),
                              source=t.get("source", "ruled"), image_path=t.get("image_path"))
                  for t in d.get("tables", [])]
    lay.figures = [FigureRegion(page=f["page"], bbox=tuple(f["bbox"]), path=f.get("path"),
                                width=f.get("width", 0), height=f.get("height", 0))
                   for f in d.get("figures", [])]
    lay.page_sizes = {int(k): tuple(v) for k, v in (d.get("page_sizes") or {}).items()}
    lay.page_kind = {int(k): v for k, v in (d.get("page_kind") or {}).items()}
    lay.render_paths = {int(k): v for k, v in (d.get("render_paths") or {}).items()}
    lay.notes = list(d.get("notes") or [])
    return lay


def save(cache_dir: str, path: str, scale: float, lay: Layout) -> str | None:
    try:
        fp = cache_file(cache_dir, path, scale)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(dump(lay), f, ensure_ascii=False)
        return fp
    except Exception:                                   # noqa: BLE001
        return None


def try_load(cache_dir: str, path: str, scale: float) -> Layout | None:
    try:
        fp = cache_file(cache_dir, path, scale)
        if not os.path.exists(fp):
            return None
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("schema") != SCHEMA or d.get("engine") != ENGINE_TAG \
                or d.get("code_sig") != code_signature():
            return None
        lay = load_dict(d)
        if not lay.boxes and not lay.tables:
            return None
        return lay
    except Exception:                                   # noqa: BLE001
        return None
