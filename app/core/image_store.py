# -*- coding: utf-8 -*-
"""配图仓库：图片**平铺**放在「图片」目录里，用一份分配清单记录「哪张图属于哪道题」。

旧版按 图片/<题号>/ 分子目录存放；首次使用时会自动迁移到平铺结构，
因此老师不需要（也不应该）再手工新建 1、2、3 这类文件夹。
"""
from __future__ import annotations
import json
import os
import re
import shutil
import time

MANIFEST = "配图分配.json"
SUPPORTED = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
_LEGACY_MARK = "_已迁移到平铺目录"

# 「从 PDF 自动抽取配图」产物的保留前缀与来源记录。
# 这些文件是程序自己的产物：换一份试卷重新抽取时，必须先按前缀清掉，
# 否则上一份试卷的图会继续挂在题号上（用户反馈：换 PDF 后配图页还是旧试卷的图）。
AUTO_PREFIX = "自动抽取_"
AUTO_RECORD = "自动抽取来源.json"


def _is_image(name: str) -> bool:
    return name.lower().endswith(SUPPORTED)


def is_auto(name: str) -> bool:
    """是否是「自动抽取」生成的图片。"""
    return os.path.basename(str(name)).startswith(AUTO_PREFIX)


def manifest_path(root: str) -> str:
    return os.path.join(root, MANIFEST)


def load_assign(root: str) -> dict:
    """读取分配清单：{题号(str): [文件名, ...]}"""
    fp = manifest_path(root)
    if not os.path.exists(fp):
        return {}
    try:
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in (data or {}).items():
        if isinstance(v, list):
            out[str(k)] = [str(x) for x in v]
    return out


def save_assign(root: str, data: dict) -> None:
    os.makedirs(root, exist_ok=True)
    with open(manifest_path(root), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def migrate_legacy(root: str) -> list:
    """把旧的 图片/<题号>/* 迁移成平铺 + 清单，返回迁移说明（无变化则空）。"""
    if not root or not os.path.isdir(root):
        return []
    notes = []
    assign = load_assign(root)
    for entry in sorted(os.listdir(root)):
        sub = os.path.join(root, entry)
        if not os.path.isdir(sub) or entry.startswith("."):
            continue
        if not re.fullmatch(r"\d{1,3}", entry):        # 只迁移形如 1、2、3 的题号目录
            continue
        moved = []
        for name in sorted(os.listdir(sub)):
            src = os.path.join(sub, name)
            if not os.path.isfile(src) or not _is_image(name):
                continue
            dst_name = name
            if os.path.exists(os.path.join(root, dst_name)):
                stem, ext = os.path.splitext(name)
                dst_name = "%s_题%s%s" % (stem, entry, ext)
            try:
                shutil.move(src, os.path.join(root, dst_name))
                moved.append(dst_name)
            except OSError:
                continue
        if moved:
            cur = [n for n in assign.get(entry, []) if isinstance(n, str)]
            for n in moved:
                if n not in cur:
                    cur.append(n)
            assign[entry] = cur
            notes.append("已把「%s」目录下的 %d 张图片迁移到平铺目录" % (entry, len(moved)))
        try:
            if not os.listdir(sub):
                os.rmdir(sub)
        except OSError:
            pass
    if notes:
        save_assign(root, assign)
        notes.append(_LEGACY_MARK)
    return notes


def library(root: str) -> list:
    """图片库里所有可用的图片（平铺目录下的图片文件）。"""
    if not root or not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        fp = os.path.join(root, name)
        if not os.path.isfile(fp) or not _is_image(name):
            continue
        try:
            size = os.path.getsize(fp)
        except OSError:
            size = 0
        out.append({"name": name, "path": fp, "size": size, "auto": is_auto(name),
                    "url": "/api/media?path=" + fp.replace("\\", "/")})
    return out


def _file_info(root: str, name: str) -> dict:
    fp = os.path.join(root, name)
    try:
        size = os.path.getsize(fp)
    except OSError:
        size = 0
    return {"name": name, "path": fp, "size": size, "auto": is_auto(name),
            "url": "/api/media?path=" + fp.replace("\\", "/")}


def assigned_names(root: str, qno) -> list:
    return list(load_assign(root).get(str(qno), []))


def assigned_files(root: str, qno) -> list:
    """返回该题已分配图片的绝对路径（过滤掉磁盘上已不存在的）。"""
    names = assigned_names(root, qno)
    out = []
    for n in names:
        fp = os.path.join(root, n)
        if os.path.isfile(fp):
            out.append(fp)
    return out


def assigned_info(root: str, qno) -> list:
    return [_file_info(root, n) for n in assigned_names(root, qno)
            if os.path.isfile(os.path.join(root, n))]


def assign(root: str, qno, paths_or_names: list, copy_outside: bool = True) -> list:
    """把图片分配给某题。

    参数既可以是图片库里的文件名，也可以是外部绝对路径（会先复制进图片库）。
    返回该题最终的图片信息列表。
    """
    os.makedirs(root, exist_ok=True)
    assign_map = load_assign(root)
    key = str(int(qno))
    cur = assign_map.setdefault(key, [])
    for item in paths_or_names or []:
        item = str(item)
        name = os.path.basename(item.replace("/", os.sep))
        if os.path.isabs(item) and os.path.isfile(item):
            dst = os.path.join(root, name)
            if os.path.abspath(item) != os.path.abspath(dst):
                i = 1
                while os.path.exists(dst):
                    if copy_outside:
                        stem, ext = os.path.splitext(name)
                        dst = os.path.join(root, "%s_%d%s" % (stem, i, ext))
                        i += 1
                    else:
                        break
                try:
                    shutil.copy2(item, dst)
                except OSError:
                    continue
                name = os.path.basename(dst)
        if os.path.isfile(os.path.join(root, name)) and name not in cur:
            cur.append(name)
    save_assign(root, assign_map)
    return assigned_info(root, qno)


def unassign(root: str, qno, names: list) -> list:
    assign_map = load_assign(root)
    key = str(int(qno))
    cur = assign_map.get(key, [])
    assign_map[key] = [n for n in cur if n not in set(names or [])]
    save_assign(root, assign_map)
    return assigned_info(root, qno)


def delete_files(root: str, names: list) -> list:
    """删除图片文件本身，并从所有题目的分配里移除。"""
    assign_map = load_assign(root)
    dead = set(names or [])
    for name in dead:
        fp = os.path.join(root, os.path.basename(name))
        try:
            if os.path.isfile(fp):
                os.remove(fp)
        except OSError:
            pass
    for k in list(assign_map):
        assign_map[k] = [n for n in assign_map[k] if n not in dead]
    save_assign(root, assign_map)
    return library(root)


def cover_for(root: str, qno) -> str:
    """该题的首图 URL（用于缩略图墙），没有则空串。"""
    items = assigned_info(root, qno)
    return items[0]["url"] if items else ""


# --------------------------------------------------------------------------- #
# 自动抽取的产物管理
# --------------------------------------------------------------------------- #
def auto_record_path(root: str) -> str:
    return os.path.join(root, AUTO_RECORD)


def load_auto_record(root: str) -> dict:
    """上次自动抽取的来源信息：{pdf, name, fingerprint, files, at}。"""
    fp = auto_record_path(root)
    if not os.path.isfile(fp):
        return {}
    try:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_auto_record(root: str, pdf: str, fingerprint: str, files: dict) -> dict:
    rec = {"pdf": os.path.abspath(pdf or ""), "name": os.path.basename(pdf or ""),
           "fingerprint": fingerprint or "",
           "files": {str(k): list(v) for k, v in (files or {}).items()},
           "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        os.makedirs(root, exist_ok=True)
        with open(auto_record_path(root), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return rec


def purge_auto(root: str) -> list:
    """删除上一次自动抽取留下的图片，并把它们从所有题目的分配里移除。

    换试卷后必须重新抽取：这些文件带固定前缀，属于程序自己的产物，
    不能和用户自己导入的图片混在一起留在库里。
    返回被删掉的文件名。
    """
    if not root or not os.path.isdir(root):
        return []
    removed = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for name in names:
        if not is_auto(name):
            continue
        fp = os.path.join(root, name)
        if not os.path.isfile(fp):
            continue
        try:
            os.remove(fp)
            removed.append(name)
        except OSError:
            continue
    # 分配表里可能还留着名字（文件被手工删过），一并清掉
    assign_map = load_assign(root)
    stale = 0
    for k in list(assign_map):
        keep = [n for n in assign_map[k] if not is_auto(n)]
        stale += len(assign_map[k]) - len(keep)
        assign_map[k] = keep
    if stale:
        save_assign(root, assign_map)
    try:
        os.remove(auto_record_path(root))           # 来源记录随之失效
    except OSError:
        pass
    return removed

