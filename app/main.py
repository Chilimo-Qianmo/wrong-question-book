# -*- coding: utf-8 -*-
"""FastAPI 应用：把引擎能力暴露为本地 HTTP 接口，并托管 Vue3 前端。"""
from __future__ import annotations
import asyncio
import json
import os
import queue
import sys
import tempfile
import re
import threading
import time
import webbrowser
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import models as M
from app.jobs import JOBS, start, sweep
from app.core import engine, archive, excel as xl, docx_build, merge_docx, cache as cache_mod
from app.core import image_store as store, regions
from app import paths
from app.core.figures import assign_to_questions, crop_from_page, crop_from_image

VERSION = "2.3.5"


def _bundle_dir() -> str:
    """打包资源所在目录（PyInstaller 解包目录 / 源码目录）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    """用户数据目录（见 app/paths.py）。

    不能直接用 __file__，否则打包后配置与输出会落到临时解包目录里。
    """
    return paths.data_dir()


WEB_DIST = os.path.join(_bundle_dir(), "web", "dist")
SETTINGS_PATH = paths.settings_path()
_DEFAULT_SETTINGS = M.Settings(
    out_dir=os.path.join(data_dir(), "错题集"),
    images_root=os.path.join(data_dir(), "图片"),
)
_settings = _DEFAULT_SETTINGS.model_copy()


def _is_temp_path(p: str) -> bool:
    """判断路径是否落在系统临时目录里（自动化测试留下的脏路径）。"""
    try:
        t = os.path.abspath(tempfile.gettempdir()).lower().rstrip("\\")
        return os.path.abspath(p).lower().startswith(t)
    except Exception:                                   # noqa: BLE001
        return False


def _sanitize_settings(s: M.Settings) -> tuple:
    """把失效的目录拉回「exe 所在的目录」。

    只要有失效路径（不存在，或指向系统临时目录），就改回默认的
    错题集 / 图片（都在程序自己所在目录下），并顺手把目录建出来。
    这样换台电脑、或 settings.json 里残留了别的机器的路径时，
    不会出现「输出目录指向一个不存在的临时文件夹」这种莫名其妙的状况。
    """
    base = paths.data_dir()
    changed = []
    for key, folder in (("out_dir", "错题集"), ("images_root", "图片")):
        cur = (getattr(s, key) or "").strip()
        drop = False
        if not cur or _is_temp_path(cur):
            drop = True                                  # 空值 / 自动化测试留下的临时路径
        elif not os.path.isdir(cur):
            parent = os.path.dirname(os.path.abspath(cur))
            if os.path.isdir(parent):
                # 父目录还在（用户新建的目录或还没建）→ 直接建出来，不动设置
                try:
                    os.makedirs(cur, exist_ok=True)
                except OSError:
                    drop = True
            else:
                drop = True                              # 换机/盘符不存在 → 拉回默认
        if drop:
            setattr(s, key, os.path.join(base, folder))
            changed.append(key)
    for key in ("out_dir", "images_root"):
        p = getattr(s, key)
        if p:
            try:
                os.makedirs(p, exist_ok=True)            # 首次启动就把目录建好
            except OSError:
                pass
    return s, changed


def load_settings() -> M.Settings:
    global _settings
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                _settings = M.Settings(**json.load(f))
        except (OSError, ValueError):
            pass
    _settings, changed = _sanitize_settings(_settings)
    if changed:
        save_settings(_settings)                        # 自愈：把修正后的路径写回配置
    return _settings


def save_settings(s: M.Settings) -> None:
    global _settings
    _settings = s
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s.model_dump(), f, ensure_ascii=False, indent=2)
    except OSError:
        pass


app = FastAPI(title="错题集生成器 v2", version=VERSION)


class NoCacheStatic(StaticFiles):
    """给 index.html 加 no-cache，避免升级后浏览器缓存旧入口引用已删除的 chunk。"""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if path in ("", "/", "index.html"):
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    def has(mod):
        try:
            __import__(mod)
            return True
        except Exception:
            return False
    try:
        from app import dpi as _dpi
        dpi_info = {"awareness": _dpi.enable_dpi_awareness(),
                    "primary_dpi": _dpi.primary_dpi(),
                    "tk_scaling": round(_dpi.tk_scaling(), 3)}
    except Exception:                                   # noqa: BLE001
        dpi_info = {}
    return {"ok": True, "version": VERSION,
            "engine": {"pdfplumber": has("pdfplumber"), "rapidocr": has("rapidocr_onnxruntime"),
                       "opencv": has("cv2"), "docx": has("docx")},
            "dpi": dpi_info}


@app.get("/api/diagnose")
def diagnose(pdf: str = Query("")):
    """系统自检：路径、可写性、PDF 可用性，并做一次真实的区域裁切。

    出问题时把这页的内容发出来即可定位，不用再猜。
    """
    import time as _t
    s = load_settings()
    cache = regions.default_cache_dir()
    info: dict = {"version": VERSION, "data_dir": paths.data_dir(),
                  "settings": {"out_dir": s.out_dir, "images_root": s.images_root},
                  "cache_dir": {"path": cache, "exists": os.path.isdir(cache),
                                "writable": False},
                  "folders": {}, "tests": []}
    for name in paths.APP_FOLDERS:
        p = os.path.join(paths.data_dir(), name)
        info["folders"][name] = {"path": p, "exists": os.path.isdir(p)}
    try:
        os.makedirs(cache, exist_ok=True)
        probe = os.path.join(cache, ".write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        info["cache_dir"]["writable"] = True
    except OSError as e:
        info["cache_dir"]["error"] = str(e)

    target = pdf or ""
    if target:
        ap = os.path.abspath(target)
        info["pdf"] = {"path": ap, "exists": os.path.exists(ap),
                       "size": os.path.getsize(ap) if os.path.exists(ap) else 0}
        if os.path.exists(ap):
            try:
                src = engine.pdf_router.inspect_pdf(ap)
                info["pdf"].update({"kind": src.kind.value, "pages": src.pages,
                                    "text_chars": src.total_chars})
            except Exception as e:                      # noqa: BLE001
                info["pdf"]["inspect_error"] = str(e)
            for label, space, scale, box in (
                ("区域裁切(按PDF点)", "pdf", 1.0, None),
            ):
                t0 = _t.time()
                try:
                    with __import__("pdfplumber").open(ap) as doc:
                        pg = doc.pages[0]
                        b = box or [20, 60, float(pg.width) - 20, 200]
                    fp = regions.crop_region(ap, 1, b, space, scale, 150)
                    info["tests"].append({"name": label, "ok": True,
                                          "ms": int((_t.time() - t0) * 1000),
                                          "bytes": os.path.getsize(fp)})
                except Exception as e:                  # noqa: BLE001
                    info["tests"].append({"name": label, "ok": False,
                                          "ms": int((_t.time() - t0) * 1000), "error": str(e)})
    return info


@app.get("/api/settings", response_model=M.Settings)
def get_settings():
    return load_settings()


@app.put("/api/settings", response_model=M.Settings)
def put_settings(s: M.Settings):
    save_settings(s)
    return _settings


_DPI_READY = False


@app.post("/api/dialog/pick")
def dialog_pick(req: M.PickRequest):
    """弹出系统文件对话框（无 GUI 环境返回空数组）。

    高 DPI 适配：先声明进程 DPI 感知，再按主屏 DPI 设置 Tk 缩放，
    否则在 4K/高缩放屏上对话框会被系统拉伸得又小又糊。
    """
    global _DPI_READY
    try:
        import tkinter as tk
        from tkinter import filedialog
        if not _DPI_READY:
            from app import dpi as _dpi
            _dpi.enable_dpi_awareness()
            _DPI_READY = True
        root = tk.Tk()
        # 让 Tk 按真实 DPI 缩放（默认 72dpi 基准）
        try:
            scale = _dpi.tk_scaling()
            root.tk.call("tk", "scaling", scale)
        except Exception:                               # noqa: BLE001
            pass
        try:
            root.tk.call("wm", "attributes", ".", "-alpha", 0.0)   # 隐藏闪一下的空窗
        except Exception:                               # noqa: BLE001
            pass
        root.withdraw()
        root.attributes("-topmost", True)
        init = req.initialdir or ""
        if req.kind == "dir":
            p = filedialog.askdirectory(title=req.title or "选择文件夹", initialdir=init or None)
            paths = [p] if p else []
        else:
            ftypes = {"pdf": [("PDF", "*.pdf")], "excel": [("Excel", "*.xlsx *.xls")],
                      "config": [("JSON", "*.json")],
                      "images": [("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.webp")]}.get(
                          req.kind, [("所有文件", "*.*")])
            if req.multi:
                ps = filedialog.askopenfilenames(title=req.title or "选择文件", filetypes=ftypes,
                                                 initialdir=init or None)
                paths = list(ps)
            else:
                p = filedialog.askopenfilename(title=req.title or "选择文件", filetypes=ftypes,
                                               initialdir=init or None)
                paths = [p] if p else []
        root.destroy()
        return {"paths": paths}
    except Exception:
        return {"paths": []}


@app.post("/api/fs/open")
def fs_open(payload: dict):
    path = (payload or {}).get("path", "")
    if not path or not os.path.exists(path):
        raise HTTPException(404, "路径不存在")
    try:
        if os.path.isdir(path):
            os.startfile(path)                       # noqa: S606
        else:
            os.startfile(os.path.dirname(path))
        return {"ok": True}
    except Exception as e:                            # noqa: BLE001
        raise HTTPException(500, str(e))


def _allowed_roots() -> list:
    s = load_settings()
    roots = [s.images_root, s.out_dir, os.path.dirname(os.path.abspath(s.out_dir or "."))]
    roots += [os.path.join(os.path.dirname(os.path.abspath(s.out_dir or ".")), d)
              for d in (".cache", "题目配置", "图片")]
    return [os.path.abspath(r) for r in roots if r]


@app.get("/api/media")
def media(path: str = Query(...)):
    ap = os.path.abspath(path)
    if not os.path.exists(ap):
        raise HTTPException(404, "文件不存在")
    ok = any(ap.lower().startswith(r.lower()) for r in _allowed_roots())
    if not ok:
        raise HTTPException(403, "路径不在允许范围内")
    return FileResponse(ap)


# --------------------------------------------------------------------------- #
# 试卷来源
# --------------------------------------------------------------------------- #
@app.post("/api/source/inspect", response_model=M.SourceInfo)
def source_inspect(payload: dict):
    pdf = (payload or {}).get("pdf") or ""
    if not pdf or not os.path.exists(pdf):
        raise HTTPException(400, "PDF 不存在")
    return engine.pdf_router.inspect_pdf(pdf)


@app.get("/api/media/region")
def media_region(pdf: str = Query(...), page: int = Query(1),
                 x0: float = Query(0), y0: float = Query(0),
                 x1: float = Query(0), y1: float = Query(0),
                 space: str = Query("pdf"), scale: float = Query(1.0),
                 dpi: int = Query(150)):
    """按题目区域从原卷裁切出图片（核对页右侧的「原题区域」）。

    space='render' 时坐标是渲染图像素，按 scale 换算回 PDF 点再裁切。
    结果落盘缓存，同一区域只渲染一次。
    """
    try:
        fp = regions.crop_region(pdf, page, [x0, y0, x1, y1], space, scale, dpi,
                                 regions.default_cache_dir())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:                              # noqa: BLE001
        raise HTTPException(500, "裁切失败：%s" % e)
    return FileResponse(fp, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
@app.post("/api/config/find")
def config_find(payload: dict):
    pdf = (payload or {}).get("pdf") or None
    out_dir = (payload or {}).get("out_dir") or load_settings().out_dir
    p = archive.find_config_for_exam(pdf, out_dir)
    if not p:
        return {"found": False, "path": "", "config": None}
    cfg = archive.load_config(p) or {}
    return {"found": True, "path": p, "config": M.QuestionConfig(**cfg).model_dump()}


@app.post("/api/config/load", response_model=M.QuestionConfig)
def config_load(payload: dict):
    p = (payload or {}).get("path") or ""
    cfg = archive.load_config(p)
    if not cfg:
        raise HTTPException(404, "配置不存在或无法解析")
    return M.QuestionConfig(**cfg)


@app.post("/api/config/save")
def config_save(payload: dict):
    cfg = M.QuestionConfig(**(payload or {}).get("config") or {})
    exam = (payload or {}).get("exam") or "试卷"
    out_dir = (payload or {}).get("out_dir") or load_settings().out_dir
    folder = archive.archive_config(exam, out_dir, cfg.model_dump())
    if not folder:
        raise HTTPException(500, "保存失败")
    return {"path": os.path.join(folder, "题目配置.json"), "folder": folder}


# --------------------------------------------------------------------------- #
# 图片
# --------------------------------------------------------------------------- #
def _images_list(images_root: str, qno: int) -> list:
    """某题已分配的图片（平铺结构，取自分配清单）。"""
    return store.assigned_info(images_root, qno)


@app.post("/api/images/library")
def images_library(payload: dict):
    """图片库全貌：平铺目录里的所有图片 + 每题分配情况。"""
    root = (payload or {}).get("images_root") or load_settings().images_root
    notes = store.migrate_legacy(root)            # 旧的 图片/<题号>/ 自动迁移
    assign = store.load_assign(root)
    counts = {k: len([n for n in v if os.path.isfile(os.path.join(root, n))])
              for k, v in assign.items()}
    auto = store.load_auto_record(root)           # 自动抽取的来源试卷（供界面提示）
    return {"root": root, "files": store.library(root), "assign": assign,
            "counts": counts, "notes": notes,
            "auto_source": {"pdf": auto.get("pdf") or "", "name": auto.get("name") or "",
                            "at": auto.get("at") or "",
                            "count": sum(len(v) for v in (auto.get("files") or {}).values())}}


@app.post("/api/images/list")
def images_list(payload: dict):
    root = (payload or {}).get("images_root") or load_settings().images_root
    qno = int((payload or {}).get("qno") or 1)
    store.migrate_legacy(root)
    return {"files": store.assigned_info(root, qno)}


@app.post("/api/images/assign")
def images_assign(payload: dict):
    """把图片分配给某题：可传图片库里的文件名，也可传外部绝对路径（会复制进来）。"""
    root = (payload or {}).get("images_root") or load_settings().images_root
    qno = int((payload or {}).get("qno") or 1)
    items = (payload or {}).get("paths") or (payload or {}).get("names") or []
    return {"files": store.assign(root, qno, items)}


@app.post("/api/images/unassign")
def images_unassign(payload: dict):
    """只把图片从该题移出，不删除文件。"""
    root = (payload or {}).get("images_root") or load_settings().images_root
    qno = int((payload or {}).get("qno") or 1)
    return {"files": store.unassign(root, qno, (payload or {}).get("names") or [])}


@app.post("/api/images/delete")
def images_delete(payload: dict):
    """彻底删除图片文件（并从所有题目移除）。"""
    root = (payload or {}).get("images_root") or load_settings().images_root
    store.delete_files(root, (payload or {}).get("names") or [])
    return {"files": store.library(root)}


@app.post("/api/images/clear")
def images_clear(payload: dict):
    """清空图片库：删除目录下所有图片并清空分配表（不影响题目配置）。"""
    root = (payload or {}).get("images_root") or load_settings().images_root
    removed = 0
    if root and os.path.isdir(root):
        for f in store.library(root):
            try:
                os.remove(f["path"])
                removed += 1
            except OSError:
                pass
    store.save_assign(root, {})
    return {"removed": removed, "files": store.library(root)}


@app.post("/api/images/autofill")
def images_autofill(payload: dict):
    """从 PDF 自动抽取配图，平铺写入图片库并自动分配到对应题号。

    抽取前一定先清掉上一轮「自动抽取_*」产物（含分配关系）：
    换一份试卷后，旧试卷的配图不能继续挂在题号上。
    用户自己导入的图片不受影响。
    """
    pdf = (payload or {}).get("pdf") or ""
    root = (payload or {}).get("images_root") or load_settings().images_root
    if not pdf or not os.path.exists(pdf):
        raise HTTPException(400, "PDF 不存在")
    os.makedirs(root, exist_ok=True)
    store.migrate_legacy(root)
    prev = store.load_auto_record(root)
    purged = store.purge_auto(root)                     # 先清旧产物，再抽新的
    found = engine.export_figures(pdf, root, load_settings().out_dir)
    for qno, names in found.items():
        store.assign(root, qno, names)
    assign = store.load_assign(root)
    try:
        fp = cache_mod.fingerprint(pdf)
    except OSError:
        fp = ""
    rec = store.save_auto_record(root, pdf, fp, found)
    changed = bool(prev.get("fingerprint")) and prev.get("fingerprint") != rec["fingerprint"]
    return {"assigned": found,
            "purged": len(purged),
            "previous_pdf": prev.get("name") or "",
            "source_pdf": rec["name"],
            "changed_source": changed,
            "counts": {str(k): len(v) for k, v in found.items()},
            "library_count": len(store.library(root)),
            "assign_counts": {k: len(v) for k, v in assign.items()}}


# --------------------------------------------------------------------------- #
# 答题表
# --------------------------------------------------------------------------- #
@app.post("/api/excel/peek", response_model=M.ExcelPeek)
def excel_peek(payload: dict):
    p = (payload or {}).get("path") or ""
    if not p or not os.path.exists(p):
        raise HTTPException(400, "表格不存在")
    return M.ExcelPeek(**xl.peek_excel(p))


# --------------------------------------------------------------------------- #
# 任务
# --------------------------------------------------------------------------- #
@app.post("/api/jobs/detect")
def jobs_detect(req: M.DetectRequest):
    def work(job):
        job.log("开始识别题目 ...")
        cfg = None
        if req.config_path:
            cfg = archive.load_config(req.config_path)
        if cfg is None:
            p = archive.find_config_for_exam(req.pdf, req.out_dir or load_settings().out_dir)
            if p:
                cfg = archive.load_config(p)
                job.log("已找到同卷题目配置：%s" % os.path.basename(os.path.dirname(p)))
        payload = engine.detect(req.pdf, config=cfg, out_dir=req.out_dir or load_settings().out_dir,
                                use_cache=req.use_cache, prefer_text_layer=req.prefer_text_layer,
                                scale=req.scale, progress=lambda m, d=0, t=1: job.progress(m, d, t))
        job.log("识别完成：%d 题，用时 %.1fs" % (len(payload.questions), payload.elapsed_ms / 1000.0))
        for g in payload.gaps:
            job.log(g.message, "warn")
        out = payload.model_dump()
        # 后台预热「原题区域」图片：核对页打开即可显示，不用一张张等渲染
        try:
            import threading as _th
            _th.Thread(target=regions.warm,
                       args=(req.pdf, out.get("questions"), req.out_dir or load_settings().out_dir),
                       daemon=True).start()
        except Exception:                               # noqa: BLE001
            pass
        return out
    job = start("detect", work)
    return {"job_id": job.id}


def _qmap_from_questions(questions, images_root: str) -> dict:
    qmap = {}
    for q in questions:
        qn = int(q["qno"])
        figs = [f.get("path") for f in (q.get("figures") or []) if f.get("path")]
        for fp in store.assigned_files(images_root, qn):     # 平铺图片库里分配给本题的图
            if fp not in figs:
                figs.append(fp)
        qmap[qn] = {
            "stem": q.get("stem") or "",
            "options": {k: v for k, v in (q.get("options") or {}).items() if v},
            "tables": [t["spec"] for t in (q.get("tables") or []) if t.get("spec")],
            "figures": figs,
        }
    return qmap


@app.post("/api/jobs/generate")
def jobs_generate(req: M.GenerateRequest):
    s = load_settings()
    out_dir = req.out_dir or s.out_dir
    images_root = req.images_root or s.images_root

    def work(job):
        job.log("开始生成错题集 ...")
        job.progress("准备题目", 0, 4)
        questions = [q.model_dump() if hasattr(q, "model_dump") else q for q in (req.questions or [])]
        pdf = req.pdf or None
        if not questions:
            cfg = req.config.model_dump() if req.config else None
            if cfg is None and req.config_path:
                cfg = archive.load_config(req.config_path)
            if cfg is None and pdf:
                p = archive.find_config_for_exam(pdf, out_dir)
                cfg = archive.load_config(p) if p else None
            payload = engine.detect(pdf, config=cfg, out_dir=out_dir,
                                    progress=lambda m, d=0, t=1: job.progress(m, d, t))
            questions = [q.model_dump() for q in payload.questions]
        if not questions:
            raise ValueError("没有可生成的题目：请先识别试卷或导入题目配置。")
        qmap = _qmap_from_questions(questions, images_root)

        # 落盘题目配置（schema 2，含 figures）
        eff = M.QuestionConfig(
            match=(req.config.match if req.config else "") or "",
            source_exam=os.path.basename(pdf or "") or (req.title or ""),
            stems={str(q["qno"]): q.get("stem") or "" for q in questions},
            options={str(q["qno"]): {k: v for k, v in (q.get("options") or {}).items() if v}
                     for q in questions},
            tables={str(q["qno"]): t["spec"] for q in questions for t in (q.get("tables") or [])
                    if t.get("spec")},
            # 只把「用户自己的配图」写进配置：自动检测到的每次都会重新检测，
            # 存进去会导致下一轮识别时同一张图被重复累加。
            figures={str(q["qno"]): [
                f for f in (q.get("figures") or [])
                if not (f.get("auto") and not f.get("path"))
            ] for q in questions if q.get("figures")},
        )
        job.progress("读取答题情况", 1, 4)
        wrongs, diag = xl.load_wrong_answers(req.excel, sorted(qmap))
        job.log("学生 %d 人，题号列 %s" % (diag.get("students"), diag.get("question_columns")))
        for note in diag.get("notes") or []:
            job.log(note, "warn")

        job.progress("生成 Word 文档", 2, 4)
        title = req.title or (eff.source_exam or "模拟测试")
        # 把「⑥ 设置」里的版式与配图尺寸（含最大宽度比例）传给文档生成
        layout = {
            "font_name": s.font_name,
            "body_size": s.body_size,
            "line_spacing": s.line_spacing,
            "page_margin_cm": s.page_margin_cm,
            "image_width_ratio": s.image_width_ratio,
            "image_dpi_fallback": s.image_dpi_fallback,
        }
        count = 0
        for name in sorted(wrongs):
            docx_build.build_student_docx(name, wrongs[name], qmap, images_root, title, out_dir,
                                          layout=layout)
            count += 1
            job.log("生成：错题集_%s.docx（错题 %d 道）" % (name, len(wrongs[name])))
        job.progress("归档与清理", 3, 4)

        exam_name = os.path.splitext(os.path.basename(pdf))[0] if pdf else (eff.match or "配置生成")
        info = archive.archive_and_cleanup(out_dir, images_root, config=eff.model_dump(),
                                           exam_name=exam_name, clean_images=not req.keep_images,
                                           cls=req.cls or None)
        job.progress("完成", 4, 4)
        job.log("已归档到：%s" % info.get("target"))
        return M.GenerateResult(students=len(wrongs), docs=count, out=os.path.abspath(out_dir),
                                archive_folder=info.get("target") or "",
                                config_folder=info.get("cfg_folder") or "",
                                moved=info.get("moved") or 0,
                                leftover=info.get("leftover") or 0).model_dump()
    job = start("generate", work)
    return {"job_id": job.id}


MERGE_ROOT_NAME = "错题集合并"


def _merge_root(out_dir: str = "") -> str:
    """合并输出的根目录：没指定就用程序目录下的「错题集合并」。"""
    return (out_dir or "").strip() or os.path.join(paths.data_dir(), MERGE_ROOT_NAME)


def _collect_merge_folders(folders) -> list:
    got = []
    for f in (folders or []):
        found = archive.expand_merge_folders(f) or ([f] if os.path.isdir(f) else [])
        got.extend(found)
    return sorted(set(got))


def _group_by_class(folders) -> dict:
    groups: dict = {}
    for d in folders:
        groups.setdefault(archive.class_of_folder(d), []).append(d)
    return dict(sorted(groups.items()))


@app.post("/api/merge/preview")
def merge_preview(payload: dict):
    """合并前预览：按班级分组、每组有多少文件夹与文档，以及输出根目录。"""
    folders = _collect_merge_folders((payload or {}).get("folders"))
    groups = _group_by_class(folders)
    root = _merge_root((payload or {}).get("out_dir") or "")
    out = []
    total = 0
    for cls, glds in groups.items():
        n = 0
        for g in glds:
            if os.path.isdir(g):
                n += len([f for f in os.listdir(g)
                          if f.lower().endswith(".docx") and not f.startswith("~$")])
        total += n
        out.append({"cls": cls, "folders": glds, "docs": n,
                    "out_dir": os.path.join(root, cls)})
    return {"root": root, "groups": out, "total_docs": total,
            "folder_count": len(folders), "root_name": MERGE_ROOT_NAME}


@app.post("/api/jobs/merge")
def jobs_merge(req: M.MergeRequest):
    """合并错题集：按班级分组，分别输出到 <根目录>/<班级>/。"""
    def work(job):
        root = _merge_root(req.out_dir)
        os.makedirs(root, exist_ok=True)          # 先把「错题集合并」建出来
        folders = _collect_merge_folders(req.folders)
        if not folders:
            raise ValueError("没有找到包含错题集文档的文件夹，请先添加要合并的错题集文件夹"
                             "（已为你创建输出目录：%s）" % root)
        groups = _group_by_class(folders)
        job.log("待合并文件夹 %d 个，按班级分成 %d 组" % (len(folders), len(groups)))
        job.log("输出根目录：%s" % root)
        tot_m = tot_c = 0
        outs, logs = [], []
        for cls, glds in groups.items():
            out = os.path.join(root, cls)
            # 上次合并的产物先清掉，避免旧文件留在目录里造成「越合并越多」的错觉
            stale = 0
            if os.path.isdir(out):
                for f in os.listdir(out):
                    if (f.startswith("错题集_") or f.startswith("合并错题集_")) \
                            and f.lower().endswith(".docx"):
                        try:
                            os.remove(os.path.join(out, f))
                            stale += 1
                        except OSError:
                            pass
            if stale:
                job.log("【%s】清理上次合并产物 %d 份" % (cls, stale))
            job.log("【%s】%d 个文件夹 → %s" % (cls, len(glds), out))
            res = merge_docx.merge_wrong_folders(
                glds, out, deduplicate=req.deduplicate, copy_single=req.copy_single,
                progress=lambda m, c=cls: job.log("[%s] %s" % (c, m)))
            tot_m += res.get("merged", 0)
            tot_c += res.get("copied", 0)
            outs.append(out)
            logs.extend(res.get("logs") or [])
        job.log("全部完成：合并 %d 份，复制 %d 份，输出 %d 个班级文件夹" % (tot_m, tot_c, len(outs)))
        return M.MergeResult(merged=tot_m, copied=tot_c, outs=outs, logs=logs,
                             root=root).model_dump()
    job = start("merge", work)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}", response_model=M.JobStatus)
def job_status(job_id: str):
    sweep()
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在或已过期")
    return M.JobStatus(**job.to_status())


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    job.cancel_flag.set()
    job.log("已请求取消（当前步骤结束后停止）", "warn")
    return {"ok": True}


def _sse(event: str, data) -> str:
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在或已过期")

    async def gen():
        yield _sse("state", job.to_status())
        idle = 0
        while True:
            got = None
            try:
                got = job.q.get_nowait()
            except queue.Empty:
                got = None
            if got is None:
                if job.state != "running":
                    yield _sse("done", {"state": job.state})
                    return
                idle += 1
                if idle % 200 == 0:                       # 心跳，防代理断流
                    yield ": ping\n\n"
                await asyncio.sleep(0.05)
                continue
            kind, payload = got
            yield _sse(kind, payload)
            if kind in ("result", "error"):
                yield _sse("done", {"state": job.state})
                return

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# 前端静态资源（必须最后挂载）
# --------------------------------------------------------------------------- #
if os.path.isdir(WEB_DIST):
    app.mount("/", NoCacheStatic(directory=WEB_DIST, html=True), name="web")
else:
    @app.get("/")
    def no_web():
        return JSONResponse({"error": "前端未构建：请先在 web/ 下执行 npm install && npm run build"},
                            status_code=503)


# 启动即确保三个工作目录存在（新环境第一次运行时目录还不存在）
try:
    paths.ensure_dirs()
except Exception:                                       # noqa: BLE001
    pass

load_settings()
