# -*- coding: utf-8 -*-
"""归档 / 清理 / 配置复用查找 / 合并文件夹展开（移植自旧版 生成错题集.py）。

本次移植按要求修复的两个旧 bug：
  1. find_config_for_exam：旧实现用「试卷名是文件夹名子串」匹配，且 sorted() 升序，
     永远命中最早那份配置（错卷风险）。现改为：把 [YYYYMMDD]-[试卷名]-题目配置
     文件夹名按 ^[0-9]{8}-(.+)-题目配置$ 解析出试卷名，**精确相等**才命中；
     多份命中时按日期倒序取最新。
  2. expand_merge_folders：旧实现只看一层，选错题集父目录时合并 0 份。现改为
     递归向下找出所有「直接包含 .docx」的文件夹并返回。
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import re
import shutil
from typing import Any, Iterable, Mapping, Optional

__all__ = [
    "load_config", "exam_name_of", "class_from_excel", "class_of_folder",
    "find_config_for_exam", "archive_config", "archive_and_cleanup",
    "expand_merge_folders",
]

CONFIG_DIR_NAME = "题目配置"
CONFIG_FILE_NAME = "题目配置.json"
CONFIG_FOLDER_RE = re.compile(r"^(\d{8})-(.+)-题目配置$")
DOCX_PREFIX = "错题集_"

_ILLEGAL = re.compile(r'[\\/:*?"<>|\s]+')


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def load_config(config):
    """读取题目配置：支持 dict（原样返回）、json 路径（读取）、其它（None）。"""
    if isinstance(config, Mapping):
        return dict(config)
    if isinstance(config, str) and config and os.path.exists(config):
        try:
            with open(config, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None
    return None


def _safe_name(name: str) -> str:
    """把试卷名/文件夹名里的 Windows 非法字符与空白替换成下划线。"""
    return _ILLEGAL.sub("_", str(name or "")).strip("_")


def _plain_name(value) -> str:
    """把可能是路径的入参变成「不带扩展名的文件名」（纯名字原样返回）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.splitext(os.path.basename(text))[0].strip()


def exam_name_of(exam_name="", config=None) -> str:
    """确定用于归档/命名的试卷名（已做非法字符替换）。

    优先用显式传入的试卷名（可为 PDF 路径）；其次从配置文件夹名推导；
    再用配置里的 match 关键字；最后回退「试卷」。
    """
    name = _plain_name(exam_name)
    if not name and isinstance(config, str) and os.path.exists(config):
        parent = os.path.basename(os.path.dirname(config))
        m = CONFIG_FOLDER_RE.match(parent)
        if m:
            name = m.group(2).strip("-_ ")
    if not name:
        cfg = load_config(config)
        if isinstance(cfg, Mapping) and str(cfg.get("match") or "").strip():
            name = str(cfg["match"]).strip()
    return _safe_name(name) or "试卷"


# --------------------------------------------------------------------------- #
# 班级名推断
# --------------------------------------------------------------------------- #
def class_from_excel(excel_path) -> str:
    """从答题情况表文件名推断班级名：去掉常见后缀（考试/选择/答题情况/成绩 等）。"""
    name = os.path.splitext(os.path.basename(str(excel_path or "")))[0]
    for tok in ("答题情况", "选择题", "考试", "成绩", "表格", "得分", "答题"):
        name = name.replace(tok, "")
    name = re.sub(r"[_\-—\s]+$", "", name).strip()
    name = re.sub(r"^[_\-—\s]+", "", name).strip()
    return name or "未分班"


def class_of_folder(path) -> str:
    """从错题集文件夹路径推断班级名（合并时按班级分类）。

    规则：
    1) 末层是 [YYYYMMDD]-[试卷名] → 取其上一级目录名作为班级；
    2) 否则取路径中含「班/级」的片段；
    3) 再回退到文件夹名。
    """
    path = str(path or "").rstrip("/\\")
    base = os.path.basename(path)
    if re.match(r"^\d{8}-", base):
        parent = os.path.basename(os.path.dirname(path))
        if parent and parent != "错题集" and not re.match(r"^\d{8}-", parent):
            return parent
    for seg in reversed(path.replace("\\", "/").split("/")):
        if ("班" in seg) or ("级" in seg):
            return seg
    return base or "未分班"


# --------------------------------------------------------------------------- #
# 配置复用（修复：精确匹配 + 取最新）
# --------------------------------------------------------------------------- #
def _config_root(out_dir) -> str:
    """题目配置根目录：与错题集输出目录(out_dir) 同级。"""
    out_dir = os.path.abspath(str(out_dir or "."))
    return os.path.join(os.path.dirname(out_dir), CONFIG_DIR_NAME)


def find_config_for_exam(pdf, out_dir) -> Optional[str]:
    """按试卷名精确查找已保存的题目配置，返回配置文件（题目配置.json）绝对路径。

    修复点：
      * 只认 [YYYYMMDD]-[试卷名]-题目配置 这种规范文件夹名，且解析出的试卷名必须与
        试卷文件名（去扩展名）**完全相等**——不再用「子串包含」；
      * 多份命中（同名试卷不同日期）时按日期倒序取最新那份；
      * 找不到 / 目录不存在 / 无配置文件时返回 None。
    额外兜底：若精确匹配无果，再尝试「去掉非法字符后相等」（归档时文件名会被消毒）。
    """
    if not pdf:
        return None
    name = _plain_name(pdf)
    if not name:
        return None
    cfg_root = _config_root(out_dir)
    if not os.path.isdir(cfg_root):
        return None

    exact, relaxed = [], []
    for folder in os.listdir(cfg_root):
        m = CONFIG_FOLDER_RE.match(folder)
        if not m:
            continue
        cfg_file = os.path.join(cfg_root, folder, CONFIG_FILE_NAME)
        if not os.path.exists(cfg_file):
            continue
        date, folder_exam = m.group(1), m.group(2)
        if folder_exam == name:
            exact.append((date, folder, cfg_file))
        elif _safe_name(folder_exam) == _safe_name(name):
            relaxed.append((date, folder, cfg_file))

    hits = exact or relaxed
    if not hits:
        return None
    # 日期倒序（同日期再按文件夹名倒序），取最新一份
    hits.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return os.path.abspath(hits[0][2])


def archive_config(exam_name, out_dir, cfg) -> Optional[str]:
    """把题目配置保存到「与错题集(out_dir) 并列的 题目配置/[日期]-[试卷名]-题目配置」。

    cfg 可为 dict（写成 json）或文件路径（复制）。同名文件夹已存在则复用并覆盖。
    返回保存的文件夹路径；cfg 为空时返回 None。
    """
    if cfg is None:
        return None
    date = datetime.date.today().strftime("%Y%m%d")
    name = exam_name_of(exam_name) or "试卷"
    folder = "%s-%s-题目配置" % (date, name)
    cfg_root = _config_root(out_dir)
    target = os.path.join(cfg_root, folder)
    os.makedirs(target, exist_ok=True)
    dest = os.path.join(target, CONFIG_FILE_NAME)
    if isinstance(cfg, str) and os.path.exists(cfg):
        shutil.copy2(cfg, dest)
    elif isinstance(cfg, Mapping):
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(dict(cfg), f, ensure_ascii=False, indent=2)
    else:
        return None
    return os.path.abspath(target)


# --------------------------------------------------------------------------- #
# 归档 + 清理
# --------------------------------------------------------------------------- #
def _unique_dir(parent, base):
    sub, n = base, 0
    while os.path.exists(os.path.join(parent, sub)):
        n += 1
        sub = "%s_%d" % (base, n)
    return sub


def archive_and_cleanup(out_dir, images_root, config=None, render_dir=None,
                        ocr_cache=None, exam_name="", clean_images=True,
                        cls=None) -> dict:
    """生成成功后调用：

    1) 在 out_dir 下把本批所有「错题集_*.docx」移入 [班级]/[YYYYMMDD]-[试卷名]
       子文件夹（无班级则直接放 [YYYYMMDD]-[试卷名]，同名追加 _1/_2）；
    2) 把题目配置归档到与 out_dir 并列的 题目配置/[日期]-[试卷名]-题目配置；
    3) 删除 .render 临时渲染目录与 OCR 缓存文件；
    4) clean_images=True 时清空图片根目录内容（保留空文件夹）。

    返回 dict：
      folder     —— 归档文件夹相对 out_dir 的路径（供界面显示）
      target     —— 归档文件夹绝对路径
      cfg_folder —— 题目配置归档文件夹（可能为 None）
      moved      —— 成功移动的文档数
      leftover   —— 仍留在 out_dir 根目录的文档数
      images_cleared —— 是否执行了图片清理
    """
    out_dir = os.path.abspath(str(out_dir))
    os.makedirs(out_dir, exist_ok=True)
    date = datetime.date.today().strftime("%Y%m%d")
    name = exam_name_of(exam_name, config)
    base = "%s-%s" % (date, name)

    # 目标目录：无班级直接放 out_dir；有班级先建 [班级] 层
    if cls:
        cls = str(cls).strip("\\/ ") or "未分班"
        target_dir = os.path.join(out_dir, cls)
        os.makedirs(target_dir, exist_ok=True)
    else:
        cls = ""
        target_dir = out_dir

    sub = _unique_dir(target_dir, base)
    target = os.path.join(target_dir, sub)
    os.makedirs(target, exist_ok=True)
    folder = os.path.join(cls, sub) if cls else sub

    # 移动本批生成的文档
    moved = 0
    for f in glob.glob(os.path.join(out_dir, DOCX_PREFIX + "*.docx")):
        if os.path.basename(f).startswith("~$"):
            continue
        try:
            shutil.move(f, os.path.join(target, os.path.basename(f)))
            moved += 1
        except OSError:
            pass
    leftover = [f for f in glob.glob(os.path.join(out_dir, DOCX_PREFIX + "*.docx"))
                if not os.path.basename(f).startswith("~$")]

    # 图片清理（按题号分文件夹；只清内容，保留空目录方便下一位老师直接拖图）
    if clean_images and images_root and os.path.isdir(str(images_root)):
        for entry in os.listdir(str(images_root)):
            ep = os.path.join(str(images_root), entry)
            if os.path.isdir(ep):
                shutil.rmtree(ep, ignore_errors=True)
            else:
                try:
                    os.remove(ep)
                except OSError:
                    pass

    # 题目配置归档
    cfg_folder = archive_config(name, out_dir, config)

    # 删除 .render 临时目录与 OCR 缓存
    if render_dir and os.path.isdir(str(render_dir)):
        shutil.rmtree(str(render_dir), ignore_errors=True)
    if ocr_cache and os.path.exists(str(ocr_cache)):
        try:
            os.remove(str(ocr_cache))
        except OSError:
            pass

    return {
        "folder": folder,
        "target": target,
        "cfg_folder": cfg_folder,
        "moved": moved,
        "leftover": len(leftover),
        "images_cleared": bool(clean_images and images_root
                               and os.path.isdir(str(images_root))),
    }


# --------------------------------------------------------------------------- #
# 合并输入展开（修复：递归向下）
# --------------------------------------------------------------------------- #
def _is_docx(filename: str) -> bool:
    """是否为可用的 docx（排除 Word 打开文档时生成的 ~$ 临时锁文件）。"""
    low = filename.lower()
    return low.endswith(".docx") and not filename.startswith("~$")


def has_docx(folder) -> bool:
    """该文件夹下是否直接存在 docx（不递归）。"""
    try:
        with os.scandir(str(folder)) as it:
            for entry in it:
                if entry.is_file() and _is_docx(entry.name):
                    return True
    except OSError:
        return False
    return False


def expand_merge_folders(root) -> list:
    """递归向下展开：返回所有「直接包含 .docx」的文件夹（绝对路径，已排序）。

    旧实现只看一层（os.listdir(root) 里的一级子目录），用户选择「错题集」父目录
    时（docx 实际在 错题集/<班级>/<日期-试卷>/ 下）会得到 0 份，合并静默失败。
    现已递归展开；隐藏目录（.render/.git 等）跳过；结果按路径排序保证合并顺序稳定。
    """
    root = os.path.abspath(str(root or ""))
    if not root or not os.path.isdir(root):
        return []
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if any(_is_docx(f) for f in filenames):
            found.append(os.path.abspath(dirpath))
    return sorted(set(found))
