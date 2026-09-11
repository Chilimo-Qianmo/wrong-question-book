#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
学生错题集生成器（图形界面版）
================================
面向普通用户：选择「试卷.pdf」「答题情况.xlsx」「导入某题图片」，
点一下即可自动为每位学生生成『错题集_学生姓名.docx』。

模块结构（便于后期维护）：
    App            —— 主窗体：文件选择 / 题目图片 / 生成 / 日志
    _merge_*       —— 多重合并子窗口：多文件夹选择 + 自动建输出目录
    ＊统一走 _log() 写日志，日志带时间戳；操作结果全部落到下方“运行日志”。
用法：双击本文件（或 一键启动.bat）即可。需已安装依赖：
    pip install customtkinter pypdfium2 rapidocr_onnxruntime openpyxl python-docx
"""
import os
import sys
import threading
import queue
import shutil
from datetime import datetime

# 让同一目录下的「生成错题集.py」可被导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import customtkinter as ctk
from tkinter import filedialog, messagebox

import 生成错题集 as engine

# ---------------------------------------------------------------------- #
# 常量：主题与文案
# ---------------------------------------------------------------------- #
APP_TITLE = "学生错题集生成器"
APP_SUB = "生物学试卷 · 选择题错题自动整理"
IMAGE_TYPES = [("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("所有文件", "*.*")]

# 界面配色（统一在此定义，方便后期微调美观性）
ACCENT = "#2F6F8F"          # 主色
ACCENT_HOVER = "#3B85A8"
MUTED = "#66707A"           # 次要文字灰
SUCCESS = "#2E7D32"         # 成功绿
ERROR = "#C62828"           # 错误红
PANEL = "#EFF3F6"           # 头部/区块底色
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")
# 全局默认字体改为支持中文的“微软雅黑”，避免界面文字（尤其日志/题目配置）显示异常
try:
    ctk.ThemeManager.theme["CTkFont"]["family"] = "微软雅黑"
except Exception:  # pragma: no cover
    pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        # 窗口：宽度收窄、高度加大（尽量占满纵向空间，1920x1080 也适配）
        _sw, _sh = self.winfo_screenwidth(), self.winfo_screenheight()
        _w = min(960, max(720, int(_sw * 0.46)))
        _h = min(1040, max(600, _sh - 80))
        self.geometry("%dx%d" % (_w, _h))
        self.minsize(680, 600)
        self._ensure_folders()            # 自动建立 错题集/题目配置/图片 文件夹（可复用）

        # ---- 表单数据（StringVar 承载，便于复用与读取） ----
        self.pdf_path = ctk.StringVar()
        self.excel_path = ctk.StringVar()
        self.out_dir = ctk.StringVar(value=os.path.join(self._app_dir(), "错题集"))
        self.images_root = ctk.StringVar(value=os.path.join(self._app_dir(), "图片"))
        self.config_path = ctk.StringVar()     # 用户显式导入的题目配置（可选）
        self.qno_var = ctk.StringVar(value="1")
        self.title_var = ctk.StringVar()
        self.cls_var = ctk.StringVar(value="未分班")               # 班级名（生成时建立 [班级] 文件夹）
        self.source_var = ctk.StringVar(value="尚未选择生成来源")   # 显示当前生效的生成来源

        self._queue = queue.Queue()            # 主窗口后台线程 -> UI 的事件队列
        self._running = False                   # 是否正在后台处理
        self._last_img_sig = None
        self._flow_mode = "edit"                # 当前是“生成前核对”还是“编辑题干”

        self._build_ui()
        self._refresh_image_list()
        self._watch_images()                   # 定时刷新“某题有无图片”的提示
        self._update_source()                  # 初始化“当前生成来源”提示

    # ------------------------------------------------------------------ #
    # 目录与基础工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def _app_dir():
        # PyInstaller 打包后 __file__ 指向临时目录，需用 exe 所在目录
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))
        return os.path.dirname(os.path.abspath(__file__))

    def _ensure_folders(self):
        """启动时确保 错题集 / 题目配置 / 图片 子文件夹存在（可在后续批次复用）。"""
        for name in ("错题集", "题目配置", "图片"):
            try:
                os.makedirs(os.path.join(self._app_dir(), name), exist_ok=True)
            except OSError:      # pragma: no cover
                pass

    @staticmethod
    def _now():
        """当前时间的 HH:MM:SS，用于日志前缀。"""
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _font(size=12, weight="normal", family="微软雅黑"):
        """懒创建字体（须在 Tk 根窗口存在后调用，故放到方法里）；默认微软雅黑保证中文清晰。"""
        return ctk.CTkFont(family=family, size=size, weight=weight)

    @staticmethod
    def _has_docx(d):
        """目录是否含 .docx（用于判断是否为可合并的错题集文件夹）。"""
        return any(f.lower().endswith(".docx")
                   for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))

    # ------------------------------------------------------------------ #
    # 日志（统一入口，所有操作结果都写到这里）
    # ------------------------------------------------------------------ #
    def _append_log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log(self, msg, ok=True):
        """写一条带时间戳的日志（仅主线程调用，如按钮/完成回调）。"""
        self._append_log("[%s] %s" % (self._now(), msg))

    def _log_ok(self, msg):
        self._log("✔ " + msg)

    # ------------------------------------------------------------------ #
    # 图片目录签名与轮询
    # ------------------------------------------------------------------ #
    def _img_signature(self):
        qdir = self._qdir()
        if not os.path.isdir(qdir):
            return None
        files = sorted(os.listdir(qdir))
        return (len(files), tuple(files))

    def _watch_images(self):
        """定时检测题目图片文件夹是否变化，及时刷新“本题有无图片”提示。"""
        try:
            sig = self._img_signature()
            if sig != self._last_img_sig:
                self._last_img_sig = sig
                self._refresh_image_list()
        except Exception:  # noqa: BLE001
            pass
        self.after(1500, self._watch_images)

    # ------------------------------------------------------------------ #
    # 界面搭建
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        # ---- 顶部横幅 ----
        banner = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        banner.pack(fill="x")
        ctk.CTkLabel(banner, text=APP_TITLE, font=ctk.CTkFont(size=26, weight="bold")).pack(pady=(16, 0))
        ctk.CTkLabel(banner, text=APP_SUB, text_color=MUTED, font=ctk.CTkFont(size=13)).pack(pady=(0, 14))

        # ---- 主容器 ----
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=18, pady=14)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(4, weight=1)

        # ---------- 区块1：文件 ----------
        f1 = ctk.CTkFrame(main)
        f1.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        f1.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f1, text="① 选择文件（生成来源：试卷 PDF 或 题目配置，任选其一）",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=3, padx=14, pady=(12, 4), sticky="w")

        # 试卷 PDF 与 题目配置 是“并列”的生成来源：可任选其一（也可同时选，则优先用题目配置）
        self._file_row(f1, 1, "试卷 PDF（自动识别）", self.pdf_path, "选择试卷…", self._pick_pdf,
                       extra="编辑题干…", extra_cmd=self._edit_stems, extra_attr="edit_btn")
        self._file_row(f1, 2, "题目配置 JSON（优先）", self.config_path, "导入题目配置…", self._pick_config)
        self._file_row(f1, 3, "答题情况 (Excel)", self.excel_path, "选择表格…", self._pick_excel)
        self._file_row(f1, 4, "输出文件夹", self.out_dir, "选择文件夹…", self._pick_out)
        # 班级：用于在“错题集”下按班级归档为 [班级]/[日期]-[试卷](可从答题表推断)
        self._file_row(f1, 5, "班级", self.cls_var, "从表格推断", self._auto_class)

        row4 = ctk.CTkFrame(f1, fg_color="transparent")
        row4.grid(row=6, column=0, columnspan=3, sticky="ew", padx=14, pady=(8, 12))
        row4.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row4, text="考试标题").grid(row=0, column=0, padx=(0, 10), sticky="w")
        ctk.CTkEntry(row4, textvariable=self.title_var, placeholder_text="留空则用‘模拟测试’").grid(
            row=0, column=1, sticky="ew")

        # 生成来源提示（试卷 / 题目配置 二选一，显示当前生效项）
        ctk.CTkLabel(f1, textvariable=self.source_var, text_color=ACCENT, anchor="w").grid(
            row=7, column=0, columnspan=3, padx=14, pady=(0, 10), sticky="w")

        # ---------- 区块2：题目图片 ----------
        f2 = ctk.CTkFrame(main)
        f2.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        f2.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f2, text="② 导入题目的配图（可选）", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=4, padx=14, pady=(12, 2), sticky="w")
        ctk.CTkLabel(f2, text="图片会保存到「图片/<题号>/」文件夹，生成文档时插入到该题题干与答案之间。",
                     text_color=MUTED).grid(row=1, column=0, columnspan=4, padx=14, sticky="w")

        r2 = ctk.CTkFrame(f2, fg_color="transparent")
        r2.grid(row=2, column=0, columnspan=4, sticky="ew", padx=14, pady=(8, 4))
        r2.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(r2, text="题号").grid(row=0, column=0, padx=(0, 8), sticky="w")
        ctk.CTkComboBox(r2, values=self._qno_values(), command=lambda v: self._refresh_image_list(),
                        variable=self.qno_var, width=70).grid(row=0, column=1, padx=(0, 10))
        ctk.CTkButton(r2, text="添加图片…", width=110, command=self._add_images).grid(row=0, column=2, sticky="w", padx=(0, 8))
        ctk.CTkButton(r2, text="打开本题文件夹", width=120, fg_color="gray", command=self._open_image_folder).grid(row=0, column=3, padx=(0, 8))
        ctk.CTkButton(r2, text="清空本题", width=90, fg_color="transparent", border_width=1,
                      text_color=MUTED, command=self._clear_question).grid(row=0, column=4)

        imglist = ctk.CTkTextbox(f2, height=70, font=self._font(12))
        imglist.grid(row=3, column=0, columnspan=4, sticky="ew", padx=14, pady=(4, 4))
        imglist.configure(state="disabled")
        imglist.tag_config("hl", foreground=SUCCESS)
        self.imglist = imglist

        r2b = ctk.CTkFrame(f2, fg_color="transparent")
        r2b.grid(row=4, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 12))
        r2b.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(r2b, text="图片根目录").grid(row=0, column=0, padx=(0, 10), sticky="w")
        ctk.CTkEntry(r2b, textvariable=self.images_root).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(r2b, text="更改…", width=70, fg_color="gray", command=self._pick_images_root).grid(row=0, column=2, padx=(0, 8))
        self.keep_images_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(r2b, text="不删除图片缓存", variable=self.keep_images_var).grid(row=0, column=3, padx=(0, 4))
        ctk.CTkLabel(r2b, text="（分析多个班级同一试卷时请勾选）", text_color=MUTED).grid(row=0, column=4, sticky="w")

        # ---------- 区块3：生成 ----------
        f3 = ctk.CTkFrame(main)
        f3.grid(row=2, column=0, sticky="ew")
        f3.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(f3, height=16)
        self.progress.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        self.progress.set(0)
        self.status = ctk.CTkLabel(f3, text="请选择（试卷 PDF 或 题目配置）与答题情况表，然后点击生成。", anchor="w", text_color=MUTED)
        self.status.grid(row=1, column=0, padx=14, sticky="ew")
        self.gen_btn = ctk.CTkButton(f3, text="生成错题集", height=44,
                                     font=ctk.CTkFont(size=16, weight="bold"),
                                     fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                     command=self._start_generate)
        self.gen_btn.grid(row=2, column=0, padx=14, pady=(10, 8), sticky="ew")
        self.merge_btn = ctk.CTkButton(f3, text="合并错题集文件夹…", height=40,
                                       fg_color="gray", font=ctk.CTkFont(size=14),
                                       command=self._open_merge)
        self.merge_btn.grid(row=3, column=0, padx=14, pady=(0, 10), sticky="ew")

        # ---------- 日志区 ----------
        ctk.CTkLabel(main, text="运行日志", text_color=MUTED).grid(row=3, column=0, sticky="w", pady=(10, 2))
        self.log = ctk.CTkTextbox(main, font=self._font(12), fg_color="#FBFCFD")
        self.log.grid(row=4, column=0, sticky="nsew")
        self.log.configure(state="disabled")
        self._log_ok("界面已就绪，请选择试卷与答题表。")

    @staticmethod
    def _qno_values():
        return [str(i) for i in range(1, 31)]

    def _file_row(self, parent, row, label, var, btn_text, cmd, extra=None, extra_cmd=None, extra_attr=None):
        """搭建一行“标签 + 输入框 + 按钮(+附加按钮)”的复用布局。"""
        rowf = ctk.CTkFrame(parent, fg_color="transparent")
        rowf.grid(row=row, column=0, columnspan=3, sticky="ew", padx=14, pady=(4, 2))
        rowf.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(rowf, text=label).grid(row=0, column=0, padx=(0, 10), sticky="w")
        ctk.CTkEntry(rowf, textvariable=var).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(rowf, text=btn_text, width=86, command=cmd).grid(row=0, column=2)
        if extra:
            btn = ctk.CTkButton(rowf, text=extra, width=100, fg_color="gray", command=extra_cmd)
            btn.grid(row=0, column=3, padx=(8, 0))
            if extra_attr:
                setattr(self, extra_attr, btn)

    # ------------------------------------------------------------------ #
    # 文件选择（每次选择都写入运行日志）
    # ------------------------------------------------------------------ #
    def _update_source(self):
        """刷新“当前生成来源”提示：有配置显示为配置，否则为试卷/未选择。"""
        if self.config_path.get().strip():
            self.source_var.set("当前生成来源：题目配置（优先，无需试卷 PDF）")
        elif self.pdf_path.get().strip():
            self.source_var.set("当前生成来源：试卷 PDF（自动识别 / 复用同卷配置）")
        else:
            self.source_var.set("当前生成来源：尚未选择（请选试卷 PDF 或导入题目配置）")

    def _pick_pdf(self):
        f = filedialog.askopenfilename(title="选择试卷 PDF", filetypes=[("PDF 文件", "*.pdf")])
        if f:
            self.pdf_path.set(f)
            self.config_path.set("")          # 试卷与题目配置二选一：选试卷即清空配置，以试卷为来源
            self._update_source()
            self._log_ok("导入试卷成功：%s（已切换为“试卷 PDF”生成来源）" % os.path.basename(f))

    def _pick_excel(self):
        f = filedialog.askopenfilename(title="选择答题情况表", filetypes=[("Excel", "*.xlsx *.xls")])
        if f:
            self.excel_path.set(f)
            self.cls_var.set(engine.class_from_excel(f))    # 从表格文件名自动推断班级
            self._log_ok("导入答题情况表格成功：%s（已推断班级：%s）" % (os.path.basename(f), self.cls_var.get()))

    def _pick_out(self):
        d = filedialog.askdirectory(title="选择输出文件夹")
        if d:
            self.out_dir.set(d)
            self._log_ok("输出文件夹：%s" % d)

    def _pick_images_root(self):
        d = filedialog.askdirectory(title="选择题目图片根目录")
        if d:
            self.images_root.set(d)
            self._log_ok("图片根目录：%s" % d)

    def _pick_config(self):
        f = filedialog.askopenfilename(title="导入题目配置", filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")])
        if f:
            self.config_path.set(f)
            self.pdf_path.set("")           # 二选一：导入配置即清空试卷，以配置为来源（无需试卷 PDF）
            self._update_source()
            self._log_ok("导入题目配置成功：%s（已切换为“题目配置”生成来源）" % os.path.basename(f))

    def _auto_class(self):
        """从已选答题情况表文件名推断班级名并填入“班级”栏。"""
        excel = self.excel_path.get().strip()
        if not excel:
            messagebox.showinfo("提示", "请先选择答题情况表。")
            return
        self.cls_var.set(engine.class_from_excel(excel))
        self._log_ok("已从答题情况表推断班级：%s" % self.cls_var.get())

    # ------------------------------------------------------------------ #
    # 题目图片管理
    # ------------------------------------------------------------------ #
    def _qno(self):
        try:
            return int(self.qno_var.get())
        except ValueError:
            return 1

    def _qdir(self):
        return os.path.join(self.images_root.get(), str(self._qno()))

    def _refresh_image_list(self):
        files = engine.find_question_images(self.images_root.get(), self._qno())
        self.imglist.configure(state="normal")
        self.imglist.delete("1.0", "end")
        if files:
            self.imglist.insert("end", "本题图片（%d 张）：\n" % len(files))
            for f in files:
                self.imglist.insert("end", "  •  " + os.path.basename(f) + "\n")
        else:
            self.imglist.insert("end", "（本题暂无图片）")
        self.imglist.configure(state="disabled")

    def _add_images(self):
        qno = self._qno()
        root = self.images_root.get()
        if not root:
            messagebox.showwarning("提示", "请先选择（或填写）题目图片根目录。")
            return
        files = filedialog.askopenfilenames(title="选择本题图片（可多选）", filetypes=IMAGE_TYPES)
        if not files:
            return
        qdir = os.path.join(root, str(qno))
        os.makedirs(qdir, exist_ok=True)
        n = 0
        for f in files:
            base = os.path.basename(f)
            dst = os.path.join(qdir, base)
            try:
                shutil.copy(f, dst)
                n += 1
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("复制失败", "%s\n%s" % (base, e))
        self._refresh_image_list()
        self._log_ok("已导入 %d 张图片到「第 %d 题」。" % (n, qno))

    def _open_image_folder(self):
        qdir = self._qdir()
        os.makedirs(qdir, exist_ok=True)
        os.startfile(qdir)

    def _clear_question(self):
        qdir = self._qdir()
        if os.path.isdir(qdir):
            for f in os.listdir(qdir):
                try:
                    os.remove(os.path.join(qdir, f))
                except OSError:  # noqa: BLE001
                    pass
        self._refresh_image_list()
        self._log_ok("已清空「第 %d 题」图片。" % self._qno())

    # ------------------------------------------------------------------ #
    # 生 成
    # ------------------------------------------------------------------ #
    def _start_generate(self):
        """「生成错题集」：先识别题目并进入核对窗口，核对通过后自动开始生成。"""
        self._begin_flow("generate")

    def _begin_flow(self, mode):
        """两个入口的公共逻辑：校验 → 识别题目 → 打开“题目核对与编辑”窗口。

        mode='generate'：核对通过后继续生成；mode='edit'：核对通过后仅保存题目配置。"""
        if self._running:
            return
        pdf = self.pdf_path.get().strip()
        cfg = self.config_path.get().strip()
        excel = self.excel_path.get().strip()
        if mode == "generate" and (not excel or not os.path.exists(excel)):
            messagebox.showwarning("缺少文件", "请先选择有效的答题情况表。")
            return
        if (not pdf or not os.path.exists(pdf)) and not cfg:
            messagebox.showwarning("缺少生成来源", "请选择「试卷 PDF」或「导入题目配置」作为来源（任选其一）。")
            return
        self._flow_mode = mode
        self._running = True
        self.gen_btn.configure(state="disabled", text="正在识别…")
        self.edit_btn.configure(state="disabled", text="正在识别…")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.status.configure(text="正在识别题目，请稍候（首次识别约需 1-2 分钟）……")
        self._log("开始识别题目（%s）…" % ("生成前核对" if mode == "generate" else "编辑题干"))
        cache = os.path.join(self._app_dir(), "_ocr_cache.json")
        threading.Thread(target=self._worker_detect,
                         args=(pdf or None, cache, cfg or None, self.out_dir.get().strip()),
                         daemon=True).start()
        self.after(60, self._poll_detect)

    def _do_generate(self):
        """核对通过后真正开始生成（此时已有保存好的题目配置）。"""
        pdf = self.pdf_path.get().strip()
        excel = self.excel_path.get().strip()
        out = self.out_dir.get().strip() or os.path.join(self._app_dir(), "错题集")
        self.out_dir.set(out)
        self._running = True
        self.gen_btn.configure(state="disabled", text="正在生成…")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.status.configure(text="正在生成错题集，请稍候……")
        self._log("开始生成错题集…")
        args = (pdf, excel, self.images_root.get(), out,
                self.title_var.get().strip() or None, self.config_path.get().strip() or None,
                self.keep_images_var.get(), self.cls_var.get().strip() or "未分班")
        threading.Thread(target=self._worker, args=args, daemon=True).start()
        self.after(60, self._poll_queue)

    def _worker(self, pdf, excel, images, out, title, cfg, keep_images, cls):
        cache = os.path.join(self._app_dir(), "_ocr_cache.json")
        # 用户显式导入的配置（已在主线程读取）-> 传入；否则交给 engine 自动优先复用“题目配置”文件夹中的配置
        config = cfg or None
        try:
            def cb(msg):
                self._queue.put(("log", "[%s] %s" % (self._now(), msg)))
                self._queue.put(("status", msg))
            result = engine.generate_all(pdf or None, excel, images, out, title=title,
                                         progress=cb, cache=cache, config=config,
                                         keep_images=keep_images, cls=cls)
            self._queue.put(("done", result))
        except Exception as e:  # noqa: BLE001
            self._queue.put(("error", str(e)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "status":
                    self.status.configure(text=payload)
                elif kind == "done":
                    self._finish(payload)
                    return
                elif kind == "error":
                    self._finish_error(payload)
                    return
        except queue.Empty:
            pass
        if self._running:
            self.after(60, self._poll_queue)

    def _finish(self, result):
        self._running = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1)
        self.gen_btn.configure(state="normal", text="生成错题集")
        archive = result.get("archive")
        if archive:
            target = os.path.join(result["out"], archive["folder"])
            cfg_msg = ""
            if archive.get("cfg_folder"):
                cfg_msg = "；题目配置已归档到：%s" % archive["cfg_folder"]
            self.status.configure(text="完成！已归档 %d 份到：%s，临时文件与图片已清理。" % (result["docs"], target))
            self._log("✅ 全部完成：学生 %d 人，文档 %d 份，已归档到：%s%s" % (result["students"], result["docs"], target, cfg_msg))
            messagebox.showinfo("完成", "已生成并归档 %d 位学生的错题集到：%s%s（临时文件与图片已清理）" % (result["docs"], target, cfg_msg))
        else:
            self.status.configure(text="完成！已生成 %d 份文档。输出目录：%s" % (result["docs"], result["out"]))
            self._log("✅ 全部完成：学生 %d 人，文档 %d 份。" % (result["students"], result["docs"]))
            messagebox.showinfo("完成", "已生成 %d 位学生的错题集，保存在：%s" % (result["docs"], result["out"]))

    def _finish_error(self, msg):
        self._running = False
        self.progress.stop()
        self.gen_btn.configure(state="normal", text="生成错题集")
        self.status.configure(text="生成失败。")
        self._log("❌ 生成失败：%s" % msg)
        messagebox.showerror("生成失败", "发生错误：\n%s" % msg)

    # ------------------------------------------------------------------ #
    # 「编辑题干」：识别题目后弹编辑窗口，保存到 题目配置.json（生成时优先使用）
    # ------------------------------------------------------------------ #
    def _edit_stems(self):
        """「编辑题干」：同样先识别题目并进入核对窗口，核对通过后保存题目配置。"""
        self._begin_flow("edit")

    def _worker_detect(self, pdf, cache, config_path, out_dir):
        try:
            qmap, keyword = engine.detect_questions(pdf, cache=cache, config=config_path, out_dir=out_dir,
                                                    progress=lambda m: self._queue.put(("log", "[%s] %s" % (self._now(), m))))
            self._queue.put(("detect_done", (qmap, keyword)))
        except Exception as e:  # noqa: BLE001
            self._queue.put(("error", str(e)))

    def _poll_detect(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "detect_done":
                    self._running = False
                    self.progress.stop()
                    self.gen_btn.configure(state="normal", text="生成错题集")
                    self.edit_btn.configure(state="normal", text="编辑题干…")
                    self.status.configure(text="识别完成，请逐题核对并勾选“已核对”。")
                    self._open_editor(payload[0], payload[1], getattr(self, "_flow_mode", "edit"))
                    return
                elif kind == "error":
                    self._running = False
                    self.progress.stop()
                    self.gen_btn.configure(state="normal", text="生成错题集")
                    self.edit_btn.configure(state="normal", text="编辑题干…")
                    self._finish_error(payload)
                    return
        except queue.Empty:
            pass
        if self._running:
            self.after(60, self._poll_detect)

    def _open_editor(self, qmap, keyword, mode="edit"):
        """题目核对与编辑窗口。

        - 可修改每题 题干 与 选项(A/B/C/D)，并提示该题是否有附图；
        - 每题右下角须手工勾选「已核对」（也可用左上「一键全部核验」）；
          点「确认核验」时若有未勾选，自动把该题滚动到窗口中间并灰亮闪烁提示；
        - 全部勾选后才保存题目配置：mode='generate' 继续生成，mode='edit' 仅保存。"""
        if not qmap:
            messagebox.showwarning("没有题目", "未识别到选择题。请检查试卷或改用题目配置。")
            return
        win = ctk.CTkToplevel(self)
        win.title("题目核对与编辑（须逐题勾选确认）")
        win.geometry("880x780")
        win.minsize(780, 640)
        win.transient(self)
        win.grab_set()

        cfg_path = self.config_path.get().strip() or os.path.join(self._app_dir(), "题目配置.json")
        existing = engine.load_config(cfg_path) or {}

        tail = "并开始生成" if mode == "generate" else "并保存配置"
        ctk.CTkLabel(win, text="请逐题核对题干与选项；每题右下角勾选「已核对」后，点下方按钮%s" % tail,
                     font=self._font(13, "bold")).pack(pady=(12, 0))
        self._confirm_note = ctk.CTkLabel(win, text="", text_color=MUTED)
        self._confirm_note.pack(pady=(0, 4))

        kwf = ctk.CTkFrame(win, fg_color="transparent")
        kwf.pack(fill="x", padx=16)
        ctk.CTkLabel(kwf, text="本卷关键字").pack(side="left", padx=(0, 8))
        self._kw_var = ctk.StringVar(value=keyword or existing.get("match") or "")
        ctk.CTkEntry(kwf, textvariable=self._kw_var).pack(side="left", fill="x", expand=True)

        scroll = ctk.CTkScrollableFrame(win)
        scroll.pack(fill="both", expand=True, padx=16, pady=10)
        self._editor_scroll = scroll
        self._editor_qmap = qmap
        self._stem_widgets = {}
        self._opt_widgets = {}
        self._confirm = {}          # 题号 -> 是否已核对（BooleanVar）
        self._qcards = {}           # 题号 -> 该题卡片（滚动定位 + 闪烁）
        self._card_bg = None
        order = sorted(qmap)

        for qn in order:
            frame = ctk.CTkFrame(scroll)
            frame.pack(fill="x", pady=4)
            if self._card_bg is None:
                try:
                    self._card_bg = frame.cget("fg_color")
                except Exception:  # noqa: BLE001
                    self._card_bg = "transparent"
            head = ctk.CTkFrame(frame, fg_color="transparent")
            head.pack(fill="x", padx=8, pady=(4, 0))
            ctk.CTkLabel(head, text="第 %d 题" % qn, font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(head, text="题图：%s" % ("有" if engine.find_question_images(self.images_root.get(), qn) else "无"),
                         text_color=MUTED).pack(side="right", padx=(0, 12))
            var = ctk.BooleanVar(value=False)
            self._confirm[qn] = var
            self._qcards[qn] = frame

            ctk.CTkLabel(frame, text="题干", text_color=MUTED).pack(anchor="w", padx=8)
            box = ctk.CTkTextbox(frame, height=48, font=self._font(12))
            box.pack(fill="x", padx=8, pady=(0, 4))
            box.insert("1.0", qmap[qn]["题干"])
            self._stem_widgets[qn] = box

            ctk.CTkLabel(frame, text="答案选项", text_color=MUTED).pack(anchor="w", padx=8)
            opt_frame = ctk.CTkFrame(frame, fg_color="transparent")
            opt_frame.pack(fill="x", padx=8, pady=(0, 6))
            opt_frame.grid_columnconfigure(1, weight=1)
            opt_frame.grid_columnconfigure(3, weight=1)
            self._opt_widgets[qn] = {}
            for i, letter in enumerate(["A", "B", "C", "D"]):
                r, col = (0, 0) if i == 0 else ((0, 2) if i == 1 else ((1, 0) if i == 2 else (1, 2)))
                ctk.CTkLabel(opt_frame, text=letter).grid(row=r, column=col, padx=(0, 2), sticky="w")
                ent = ctk.CTkEntry(opt_frame, font=self._font(12))
                ent.grid(row=r, column=col + 1, sticky="ew", padx=(0, 10))
                ent.insert(0, (qmap[qn]["选项"] or {}).get(letter, ""))
                self._opt_widgets[qn][letter] = ent

            # 核验勾选框放在本题卡片的右下角
            foot = ctk.CTkFrame(frame, fg_color="transparent")
            foot.pack(fill="x", padx=8, pady=(0, 6))
            ctk.CTkCheckBox(foot, text="已核对", variable=var, width=92,
                            command=self._update_confirm_note).pack(side="right")

        def do_confirm():
            missing = [q for q in order if not self._confirm[q].get()]
            if missing:
                self._flash_question(missing[0], len(missing))   # 定位并闪烁提示
                return
            self._save_and_continue(win, order, qmap, existing, mode)

        def check_all():
            """一键把每题都标为已核对。"""
            for v in self._confirm.values():
                v.set(True)
            self._update_confirm_note()

        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(bar, text="一键全部核验", width=140, height=44,
                      fg_color="gray", hover_color="#5A6570",
                      command=check_all).pack(side="left")
        ctk.CTkButton(bar, text="确认核验%s" % tail, height=44, width=250, fg_color=SUCCESS,
                      hover_color="#1B5E20", font=ctk.CTkFont(size=15, weight="bold"),
                      command=do_confirm).pack(side="right")
        self._update_confirm_note()

    # ------------------------------------------------------------------ #
    # 题目核对：进度、定位闪烁、保存并继续
    # ------------------------------------------------------------------ #
    def _update_confirm_note(self):
        """刷新“已核对 x / y 题”提示。"""
        lbl = getattr(self, "_confirm_note", None)
        vars_ = getattr(self, "_confirm", {})
        if lbl is None or not vars_:
            return
        done = sum(1 for v in vars_.values() if v.get())
        try:
            lbl.configure(text="已核对 %d / %d 题" % (done, len(vars_)))
        except Exception:  # noqa: BLE001
            pass

    def _flash_question(self, qn, remaining=1):
        """把未勾选的题目滚动到窗口中间，并灰亮闪烁提示其“已核对”区域。"""
        card = getattr(self, "_qcards", {}).get(qn)
        scroll = getattr(self, "_editor_scroll", None)
        if card is None or scroll is None:
            return
        try:
            self.update_idletasks()
            canvas = scroll._parent_canvas
            bbox = canvas.bbox("all")
            total = max(1, (bbox[3] - bbox[1]) if bbox else card.winfo_height())
            vh = canvas.winfo_height() or total
            cy = card.winfo_y() + card.winfo_height() / 2.0
            canvas.yview_moveto(max(0.0, min(1.0, (cy - vh / 2.0) / total)))
        except Exception:  # noqa: BLE001
            pass
        self._log("还有 %d 题未勾选「已核对」，已定位到第 %d 题。" % (remaining, qn))
        self._flash_widget(card, 2)

    def _flash_widget(self, w, n=7):
        """灰亮闪烁：交替切换卡片底色，若干次后恢复原底色。"""
        try:
            w.configure(fg_color=("#A9B2BB" if n % 2 else self._card_bg))
        except Exception:  # noqa: BLE001
            return
        if n > 0:
            self.after(260, lambda: self._flash_widget(w, n - 1))

    def _save_and_continue(self, win, order, qmap, existing, mode):
        """逐题核对通过：保存题目配置（含表格附图区域），再继续生成或结束。"""
        stems, options = {}, {}
        for qn in order:
            s = self._stem_widgets[qn].get("1.0", "end").strip()
            if s:
                stems[str(qn)] = s
            od = {l: self._opt_widgets[qn][l].get().strip() for l in ["A", "B", "C", "D"]}
            od = {l: v for l, v in od.items() if v}
            if od:
                options[str(qn)] = od
        cfg = {"match": self._kw_var.get().strip(), "stems": stems, "options": options}
        cfg["tables"] = existing.get("tables", {})
        try:
            # 归档到「与错题集并列的 题目配置/[日期]-[试卷名]-题目配置」文件夹
            _out = self.out_dir.get().strip() or os.path.join(self._app_dir(), "错题集")
            _exam = self.pdf_path.get().strip() or "试卷"
            _arc = engine.archive_config(_exam, _out, cfg)
            self.config_path.set(os.path.join(_arc, "题目配置.json"))   # 生成时使用该配置
            self._update_source()          # 提示已切换为“题目配置”来源
            self._log_ok("逐题核对通过，题干配置已保存：%s" % _arc)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存失败", str(e))
            return
        win.destroy()
        if mode == "generate":
            self.status.configure(text="核对完成，开始生成……")
            self.after(80, self._do_generate)
        else:
            self.status.configure(text="核对完成，题干配置已保存。")
            self._log_ok("核对完成（未生成）。如需生成请点「生成错题集」。")

    # ------------------------------------------------------------------ #
    # 多重合并错题集文件夹
    # ------------------------------------------------------------------ #
    @staticmethod
    def _append_logbox(box, msg):
        box.configure(state="normal")
        box.insert("end", msg + "\n")
        box.see("end")
        box.configure(state="disabled")

    def _open_merge(self):
        win = ctk.CTkToplevel(self)
        win.title("多重合并错题集文件夹")
        win.geometry("780x680")
        win.minsize(700, 600)
        win.transient(self)

        # 合并窗口共享的数据（供各按钮回调读写）
        self._merge_fo = ctk.StringVar()                 # 输出文件夹（可由“添加完成”自动生成，也可手填）
        self._merge_cls = ctk.StringVar()                # 班级（可多个，用顿号隔开）
        self._merge_dedup = ctk.BooleanVar(value=False)
        self._merge_copy_single = ctk.BooleanVar(value=True)
        self._merge_folders = []                          # 选中的错题集文件夹列表
        self._merge_win = win

        # ---- 标题与说明 ----
        ctk.CTkLabel(win, text="多重合并错题集文件夹",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(12, 2))
        ctk.CTkLabel(win, text="选择多个错题集文件夹（按顺序合并）；同名学生文档会合并，编号自动续接。",
                     text_color=MUTED).pack()
        ctk.CTkLabel(win, text="提示：可从文件夹路径自动推断班级；含多个班级时会按班级分类，分别合并到各自的输出文件夹。",
                     text_color=MUTED).pack()

        # ---- 班级输入 ----
        crow = ctk.CTkFrame(win, fg_color="transparent")
        crow.pack(fill="x", padx=14, pady=(10, 4))
        crow.grid_columnconfigure(1, weight=1)
        crow.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(crow, text="班级（自动识别）").grid(row=0, column=0, padx=(0, 8), sticky="w")
        ctk.CTkEntry(crow, textvariable=self._merge_cls).grid(row=0, column=1, sticky="ew", padx=(0, 20))
        ctk.CTkLabel(crow, text="输出文件夹").grid(row=0, column=2, padx=(0, 8), sticky="w")
        ctk.CTkEntry(crow, textvariable=self._merge_fo).grid(row=0, column=3, sticky="ew", padx=(0, 8))
        ctk.CTkButton(crow, text="浏览…", width=70, fg_color="gray",
                      command=lambda: self._merge_fo.set(
                          filedialog.askdirectory(title="选择输出文件夹"))).grid(row=0, column=4)

        # ---- 文件夹列表 ----
        self._merge_list = ctk.CTkTextbox(win, height=160, font=self._font(12))
        self._merge_list.pack(fill="x", padx=14, pady=6)
        self._merge_list.configure(state="disabled")

        # ---- 按钮行：添加文件夹(可多选) / 移除 / 清空 | 添加完成(自动建输出目录) ----
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=14)
        ctk.CTkButton(btns, text="添加文件夹…", width=130, command=self._merge_add).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="移除最后一个", width=110, fg_color="gray", command=self._merge_pop).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="清空", width=70, fg_color="transparent", border_width=1,
                      text_color=MUTED, command=self._merge_clear).pack(side="left")
        ctk.CTkButton(btns, text="添加完成（生成输出文件夹）", width=220, fg_color=SUCCESS,
                      command=self._merge_finish).pack(side="right")

        # ---- 选项 ----
        opt = ctk.CTkFrame(win, fg_color="transparent")
        opt.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkCheckBox(opt, text="复制仅单侧学生文档", variable=self._merge_copy_single).pack(side="left", padx=(0, 20))
        ctk.CTkCheckBox(opt, text="按题号去重", variable=self._merge_dedup).pack(side="left")

        ctk.CTkButton(win, text="开始多重合并", height=40,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=lambda: self._start_merge(self._merge_fo.get().strip(),
                                                        self._merge_dedup.get(),
                                                        self._merge_copy_single.get())
                      ).pack(fill="x", padx=14, pady=(6, 8))

        logbox = ctk.CTkTextbox(win, font=self._font(12), fg_color="#FBFCFD")
        logbox.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        logbox.configure(state="disabled")
        self._merge_log = logbox

    # ---------------------------------------------------------------- #
    # 合并窗口：文件夹选择
    # ---------------------------------------------------------------- #
    def _merge_add(self):
        """一次选择多个文件夹：选父目录会自动加入其内含 .docx 的子文件夹（即多个班级）。
        若所选目录本身就是错题集文件夹，则直接加入。"""
        d = filedialog.askdirectory(title="选择错题集文件夹（选父目录可一次加入多个班级子文件夹）")
        if not d:
            return
        # 找出父目录下所有含 .docx 的子文件夹
        try:
            subs = [os.path.join(d, s) for s in os.listdir(d)
                    if os.path.isdir(os.path.join(d, s)) and self._has_docx(os.path.join(d, s))]
        except OSError:  # noqa: BLE001
            subs = []
        paths = subs if subs else [d]   # 有子文件夹则加入全部子文件夹；否则加入目录本身
        added = [p for p in paths if p not in self._merge_folders]

        self._merge_folders.extend(added)
        self._merge_refresh()   # 刷新列表，并自动按路径推断班级、补全“班级”栏
        self._append_logbox(self._merge_log, "已加入 %d 个文件夹。" % len(added))

    def _merge_pop(self):
        if self._merge_folders:
            self._merge_folders.pop()
            self._merge_refresh()

    def _merge_clear(self):
        self._merge_folders = []
        self._merge_refresh()

    def _merge_groups(self):
        """按班级分组：始终从文件夹路径推断班级并分组（多班级则每班一组，分别合并）。
        返回 {班级: [文件夹, ...]}。"""
        folders = list(self._merge_folders)
        if not folders:
            return {}
        groups = {}
        for d in folders:
            c = engine.class_of_folder(d)
            groups.setdefault(c, []).append(d)
        return groups

    def _merge_refresh(self):
        self._merge_list.configure(state="normal")
        self._merge_list.delete("1.0", "end")
        for i, d in enumerate(self._merge_folders, 1):
            c = engine.class_of_folder(d)
            self._merge_list.insert("end", "%d. [%s] %s\n" % (i, c, d))
        self._merge_list.configure(state="disabled")
        # 自动补全“班级”栏（若用户尚未填写）
        if not self._merge_cls.get().strip():
            cm = self._merge_groups()
            if cm:
                self._merge_cls.set("、".join(cm.keys()))

    def _merge_class_outdir(self, stamp, cls):
        """在“合并输出”下新建 [日期时间]-[班级]-合并文档，返回其路径。"""
        base = os.path.join(self._app_dir(), "合并输出")
        os.makedirs(base, exist_ok=True)
        cls = cls or "未填班级"
        out = os.path.join(base, "%s-%s-合并文档" % (stamp, cls))
        try:
            os.makedirs(out, exist_ok=True)
        except OSError:  # noqa: BLE001
            pass
        return out

    def _merge_finish(self):
        """“添加完成”：按班级自动生成对应的输出文件夹并设为输出（可多班级，逐班一个）。"""
        groups = self._merge_groups()
        if not groups:
            messagebox.showinfo("提示", "请先添加至少一个错题集文件夹。")
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        outs = [self._merge_class_outdir(stamp, c) for c in groups]
        self._merge_fo.set(outs[0])   # 默认取第一个作为输出显示
        self._append_logbox(self._merge_log, "✔ 已创建输出文件夹：\n  " + "\n  ".join(outs))

    # ---------------------------------------------------------------- #
    # 合并窗口：执行合并
    # ---------------------------------------------------------------- #
    def _start_merge(self, fo, dedup, copy_single):
        groups = self._merge_groups()
        if not groups:
            messagebox.showwarning("提示", "请先添加至少一个错题集文件夹。")
            return
        box = self._merge_log
        q = queue.Queue()
        # 单班级且用户指定了输出目录时，用指定目录；否则每个班级单独建输出
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        use_plain = (len(groups) == 1 and bool(fo))
        self._append_logbox(box, "开始多重合并…")

        def worker():
            try:
                tot_m = tot_c = 0
                outs = []
                for cls, glds in groups.items():
                    out = fo if (use_plain and cls == next(iter(groups))) else self._merge_class_outdir(stamp, cls)
                    outs.append(out)
                    res = engine.merge_wrong_folders(glds, out, deduplicate=dedup,
                                                     copy_single=copy_single,
                                                     progress=lambda m, c=cls: q.put(("log", "[%s] %s" % (c, m))))
                    tot_m += res["merged"]
                    tot_c += res["copied"]
                q.put(("done", {"merged": tot_m, "copied": tot_c, "outs": outs}))
            except Exception as e:  # noqa: BLE001
                q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_merge(box, q, lambda res: messagebox.showinfo(
            "完成", "多重合并完成：合并 %d 份，复制 %d 份。\n输出目录：\n  %s" % (res["merged"], res["copied"], "\n  ".join(res["outs"]))))

    def _poll_merge(self, box, q, done_cb):
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "log":
                    self._append_logbox(box, payload)
                elif kind == "done":
                    done_cb(payload)
                    return
                elif kind == "error":
                    self._append_logbox(box, "❌ " + payload)
                    messagebox.showerror("合并失败", payload)
                    return
        except queue.Empty:
            pass
        self.after(80, lambda: self._poll_merge(box, q, done_cb))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
