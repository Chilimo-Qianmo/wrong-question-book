# -*- coding: utf-8 -*-
"""FastAPI 应用：把引擎能力暴露为本地 HTTP 接口，并托管 Vue3 前端。"""
from __future__ import annotations
import asyncio
import json
import os
import queue
import sys
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
from app.core.figures import assign_to_questions, crop_from_page, crop_from_image

VERSION = "2.0.1"


def _bundle_dir() -> str:
    """打包资源所在目录（PyInstaller 解包目录 / 源码目录）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    """用户数据目录：打包后是 exe 所在目录，源码运行是项目根目录。

    （不能直接用 __file__，否则打包后配置与输出会落到临时解包目录里。）
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return _bundle_dir()


WEB_DIST = os.path.join(_bundle_dir(), "web", "dist")
SETTINGS_PATH = os.path.join(data_dir(), "settings.json")
_DEFAULT_SETTINGS = M.Settings(
    out_dir=os.path.join(data_dir(), "错题集"),
    images_root=os.path.join(data_dir(), "图片"),
)
_settings = _DEFAULT_SETTINGS.model_copy()


def load_settings() -> M.Settings:
    global _settings
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                _settings = M.Settings(**json.load(f))
        except (OSError, ValueError):
            pass
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
    return {"ok": True, "version": VERSION,
            "engine": {"pdfplumber": has("pdfplumber"), "rapidocr": has("rapidocr_onnxruntime"),
                       "opencv": has("cv2"), "docx": has("docx")}}


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
    import hashlib
    import pdfplumber

    ap = os.path.abspath(pdf)
    if not os.path.exists(ap) or not ap.lower().endswith(".pdf"):
        raise HTTPException(400, "不是有效的 PDF 路径")
    s = float(scale or 1.0)
    if space == "render" and s > 0.01:
        x0, y0, x1, y1 = x0 / s, y0 / s, x1 / s, y1 / s
    if x1 <= x0 or y1 <= y0:
        raise HTTPException(400, "区域无效")
    dpi = max(72, min(400, int(dpi or 150)))

    cache_dir, _render = engine.work_dirs(load_settings().out_dir)
    key = "%s|%d|%.1f|%.1f|%.1f|%.1f|%d" % (
        cache_mod.fingerprint(ap), page, x0, y0, x1, y1, dpi)
    fp = os.path.join(cache_dir, "crop", hashlib.sha1(key.encode()).hexdigest()[:20] + ".png")
    if not os.path.exists(fp):
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        try:
            with pdfplumber.open(ap) as doc:
                if page < 1 or page > len(doc.pages):
                    raise HTTPException(400, "页码超出范围")
                pg = doc.pages[page - 1]
                bbox = (max(0.0, x0), max(0.0, y0),
                        min(float(pg.width), x1), min(float(pg.height), y1))
                img = pg.crop(bbox).to_image(resolution=dpi)
                img.save(fp)                        # PageImage.save() 已按 resolution 写入 DPI
        except HTTPException:
            raise
        except Exception as e:                          # noqa: BLE001
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
    d = os.path.join(images_root, str(qno))
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
            continue
        fp = os.path.join(d, name)
        out.append({"name": name, "path": fp, "size": os.path.getsize(fp),
                    "url": "/api/media?path=" + fp.replace("\\", "/")})
    return out


@app.post("/api/images/list")
def images_list(payload: dict):
    root = (payload or {}).get("images_root") or load_settings().images_root
    return {"files": _images_list(root, int((payload or {}).get("qno") or 1))}


@app.post("/api/images/assign")
def images_assign(payload: dict):
    import shutil
    root = (payload or {}).get("images_root") or load_settings().images_root
    qno = int((payload or {}).get("qno") or 1)
    d = os.path.join(root, str(qno))
    os.makedirs(d, exist_ok=True)
    for p in (payload or {}).get("paths") or []:
        if os.path.exists(p):
            try:
                shutil.copy2(p, os.path.join(d, os.path.basename(p)))
            except OSError:
                pass
    return {"files": _images_list(root, qno)}


@app.post("/api/images/delete")
def images_delete(payload: dict):
    root = (payload or {}).get("images_root") or load_settings().images_root
    qno = int((payload or {}).get("qno") or 1)
    d = os.path.join(root, str(qno))
    for name in (payload or {}).get("names") or []:
        fp = os.path.join(d, os.path.basename(name))
        try:
            if os.path.isfile(fp):
                os.remove(fp)
        except OSError:
            pass
    return {"files": _images_list(root, qno)}


@app.post("/api/images/autofill")
def images_autofill(payload: dict):
    pdf = (payload or {}).get("pdf") or ""
    root = (payload or {}).get("images_root") or load_settings().images_root
    if not pdf or not os.path.exists(pdf):
        raise HTTPException(400, "PDF 不存在")
    os.makedirs(root, exist_ok=True)
    assigned = engine.export_figures(pdf, root, load_settings().out_dir)
    return {"assigned": assigned,
            "counts": {str(k): len(v) for k, v in assigned.items()}}


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
        return payload.model_dump()
    job = start("detect", work)
    return {"job_id": job.id}


def _qmap_from_questions(questions, images_root: str) -> dict:
    qmap = {}
    for q in questions:
        qn = int(q["qno"])
        figs = [f.get("path") for f in (q.get("figures") or []) if f.get("path")]
        for f in _images_list(images_root, qn):
            if f["path"] not in figs:
                figs.append(f["path"])
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
            figures={str(q["qno"]): (q.get("figures") or []) for q in questions if q.get("figures")},
        )
        job.progress("读取答题情况", 1, 4)
        wrongs, diag = xl.load_wrong_answers(req.excel, sorted(qmap))
        job.log("学生 %d 人，题号列 %s" % (diag.get("students"), diag.get("question_columns")))
        for note in diag.get("notes") or []:
            job.log(note, "warn")

        job.progress("生成 Word 文档", 2, 4)
        title = req.title or (eff.source_exam or "模拟测试")
        count = 0
        for name in sorted(wrongs):
            docx_build.build_student_docx(name, wrongs[name], qmap, images_root, title, out_dir)
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


@app.post("/api/jobs/merge")
def jobs_merge(req: M.MergeRequest):
    def work(job):
        folders = []
        for f in req.folders:
            got = archive.expand_merge_folders(f) or ([f] if os.path.isdir(f) else [])
            folders.extend(got)
        folders = sorted(set(folders))
        if not folders:
            raise ValueError("没有找到包含错题集文档的文件夹")
        job.log("待合并文件夹 %d 个" % len(folders))
        out = req.out_dir or os.path.join(os.path.dirname(folders[0]), "合并输出")
        res = merge_docx.merge_wrong_folders(folders, out, deduplicate=req.deduplicate,
                                             copy_single=req.copy_single,
                                             progress=lambda m: job.log(m))
        return M.MergeResult(merged=res.get("merged", 0), copied=res.get("copied", 0),
                             outs=res.get("outs") or [out], logs=res.get("logs") or []).model_dump()
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


load_settings()
