# -*- coding: utf-8 -*-
"""多个错题集文件夹合并（移植自旧版 生成错题集.py，逻辑保持不变）。

能力：
  * 同名学生出现在多个文件夹 → 合并为一份（以第一个文件夹的文档为主，保留其版式）；
  * 图片关系（a:blip / r:embed）重映射到目标文档，保证图片不丢；
  * 「第 N 部分」分隔编号自动续接（合并结果可再次作为输入继续合并）；
  * deduplicate=True 时按「第 N 题」跨文件夹去重；
  * 只在单侧出现的姓名：copy_single=True 直接复制，否则跳过。
"""
from __future__ import annotations

import copy as _copy
import glob
import io as _io
import os
import re
import shutil
from typing import Any, Callable, Iterable, Optional, Sequence

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Pt

__all__ = ["merge_wrong_folders", "docx_name", "collect_numbers", "count_parts"]

CN_DIGITS = "零一二三四五六七八九"
_SEP_SIZE = 16
_PART_RE = re.compile(r"(第\s*)([一二三四五六七八九十百\d]+)(\s*部分)")
_QNO_RE = re.compile(r"^第\s*(\d+)\s*题")


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
# 合并产物会带「合并错题集_」前缀，再次参与合并时必须能认回同一个学生
_NAME_PREFIXES = ("合并错题集_", "错题集_")


def docx_name(filename) -> str:
    """从文件名提取学生姓名（去掉 .docx 与「错题集_」/「合并错题集_」前缀）。"""
    name = os.path.splitext(os.path.basename(str(filename)))[0]
    for pre in _NAME_PREFIXES:
        if name.startswith(pre):
            name = name[len(pre):]
            break
    return name.strip()


def _list_docx(folder) -> list:
    """文件夹内的 docx（排除 ~$ 锁文件），按文件名排序。"""
    files = [f for f in glob.glob(os.path.join(str(folder), "*.docx"))
             if not os.path.basename(f).startswith("~$")]
    return sorted(files)


def _num_to_cn(n: int) -> str:
    if n <= 0:
        return str(n)
    if n < 10:
        return CN_DIGITS[n]
    if n < 20:
        return "十" + (CN_DIGITS[n - 10] if n % 10 else "")
    h, t = divmod(n, 10)
    return CN_DIGITS[h] + "十" + (CN_DIGITS[t] if t else "")


def _cn_to_num(s: str) -> int:
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        h, _, t = s.partition("十")
        return (CN_DIGITS.index(h) if h else 1) * 10 + (CN_DIGITS.index(t) if t else 0)
    if s in CN_DIGITS:
        return CN_DIGITS.index(s)
    return 1


def collect_numbers(doc) -> set:
    """收集文档中所有「第 N 题」的题号。"""
    numbers = set()
    for p in doc.paragraphs:
        m = _QNO_RE.match(p.text.strip())
        if m:
            numbers.add(int(m.group(1)))
    return numbers


def count_parts(doc) -> int:
    """统计文档中「第 N 部分」的最大编号（合并时用于续接分隔编号）。"""
    maxp = 1
    for p in doc.paragraphs:
        m = re.match(r".*第\s*([一二三四五六七八九十百\d]+)\s*部分", p.text.strip())
        if m:
            maxp = max(maxp, _cn_to_num(m.group(1)))
    return maxp


def _shift_part_numbers(element, diff: int):
    """把元素中「第 N 部分」的编号整体增加 diff（保持内部结构有序）。"""
    for p in element.iter(qn("w:p")):
        for r in p.iter(qn("w:r")):
            t = r.find(qn("w:t"))
            if t is not None and t.text:
                m = _PART_RE.search(t.text)
                if m:
                    t.text = (t.text[:m.start(2)]
                              + _num_to_cn(_cn_to_num(m.group(2)) + diff)
                              + t.text[m.end(2):])


def _remap_image_rels(dest_part, src_part, element):
    """把 element 中的图片关系重映射到目标文档，保证图片不丢失。"""
    for blip in element.iter(qn("a:blip")):
        rId = blip.get(qn("r:embed"))
        if rId and rId in src_part.rels:
            img_part = src_part.related_parts[rId]
            new_rId, _ = dest_part.get_or_add_image(_io.BytesIO(img_part.blob))
            blip.set(qn("r:embed"), new_rId)


def _copy_body_elements(dest_doc, src_doc, skip_numbers=None, part_offset=0):
    """把 src_doc 的段落/表格复制到 dest_doc（保留图片与文本）。

    skip_numbers：若非 None，则跳过其中题号已出现的题（去重）；
    part_offset：若 >0，则重排该文档内部「第 N 部分」编号。
    """
    dest_body = dest_doc.element.body
    sectPr = dest_body.find(qn("w:sectPr"))
    if sectPr is not None:
        dest_body.remove(sectPr)
    src_part = src_doc.part
    dest_part = dest_doc.part
    in_skipped = False
    for element in list(src_doc.element.body):
        if element.tag not in (qn("w:p"), qn("w:tbl")):
            continue
        if skip_numbers is not None:
            text = "".join(t.text or "" for t in element.iter(qn("w:t")))
            m = _QNO_RE.match(text.strip())
            if m:
                n = int(m.group(1))
                if n in skip_numbers:
                    in_skipped = True
                else:
                    in_skipped = False
                    skip_numbers.add(n)
            if in_skipped:
                continue
        new_el = _copy.deepcopy(element)
        if part_offset:
            _shift_part_numbers(new_el, part_offset)
        _remap_image_rels(dest_part, src_part, new_el)
        dest_body.append(new_el)
    if sectPr is not None:
        dest_body.append(sectPr)


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def merge_wrong_folders(folders, out_dir, deduplicate=False, copy_single=True,
                        progress: Optional[Callable[[str], None]] = None) -> dict:
    """多重合并：任选多个错题集文件夹，同名学生的多份文档按顺序合并。

    - folders：文件夹路径列表（>=1），顺序即合并顺序；
    - 同名学生出现在多个文件夹则合并（内容顺序 + 自动递增「第 N 部分」分隔）；
    - 仅在一个文件夹出现则复制到输出目录（copy_single=True）；
    - 合并结果可再次作为输入与其他文档合并，分隔编号会自动续接；
    - deduplicate：按「第 N 题」跨文件夹去重。

    返回 {"merged": int, "copied": int, "logs": [str], "outs": [str]}。
    """
    def _report(msg):
        if progress:
            progress(msg)
        else:
            print(msg)

    out_dir = os.path.abspath(str(out_dir))
    os.makedirs(out_dir, exist_ok=True)
    logs: list = []
    outs: list = []

    folder_list = []
    for fd in (folders or []):
        fd = os.path.abspath(str(fd))
        if os.path.isdir(fd):
            folder_list.append(fd)
        else:
            logs.append("跳过：目录不存在 %s" % fd)
    if not folder_list:
        logs.append("没有可合并的文件夹。")
        return {"merged": 0, "copied": 0, "logs": logs, "outs": outs}

    # 同一文件夹内若出现重名学生（例如既是错题集又是合并结果），全部保留，
    # 合并时按顺序依次追加，不再互相覆盖。
    per_folder: list = []
    for fd in folder_list:
        d: dict = {}
        for f in _list_docx(fd):
            d.setdefault(docx_name(f), []).append(f)
        per_folder.append(d)
    all_names = sorted(set().union(*[set(d) for d in per_folder]))

    merged = 0
    copied = 0
    for name in all_names:
        present = [(i, per_folder[i][name]) for i in range(len(per_folder))
                   if name in per_folder[i]]
        try:
            if len(present) == 1 and len(present[0][1]) == 1:
                src = present[0][1][0]
                dest = os.path.join(out_dir, os.path.basename(src))
                if not copy_single:
                    _report("跳过（仅在单侧）：%s" % name)
                elif os.path.abspath(src) == os.path.abspath(dest):
                    _report("跳过（源与目标相同）：%s" % name)
                else:
                    shutil.copy2(src, dest)
                    copied += 1
                    outs.append(dest)
                    _report("复制（仅单侧）：%s" % name)
                continue
            # 展平成「按文件夹顺序、文件夹内按文件名顺序」的文档列表
            sources = [p for (_idx, paths) in present for p in paths]
            base_path = sources[0]
            dest_doc = Document(base_path)   # 以第一个文档为主（保留其样式/版式）
            seen = collect_numbers(dest_doc) if deduplicate else None
            next_part = count_parts(dest_doc)   # 基准文档已有的最大部分编号
            for path in sources[1:]:
                doc_i = Document(path)
                next_part += 1
                brk_p = dest_doc.add_paragraph()
                brk_p.add_run().add_break(WD_BREAK.PAGE)
                sep = dest_doc.add_paragraph()
                sep.alignment = WD_ALIGN_PARAGRAPH.CENTER
                sep_r = sep.add_run("———— 第 %s 部分 ————" % _num_to_cn(next_part))
                sep_r.bold = True
                sep_r.font.size = Pt(_SEP_SIZE)
                # 追加 doc_i；若其本身是合并结果，重排内部「部分」编号以保持有序
                _copy_body_elements(dest_doc, doc_i, skip_numbers=seen,
                                    part_offset=next_part - 1)
            prefix = ("错题集_" if any(os.path.basename(p).startswith("错题集_")
                                     for p in sources) else "合并错题集_")
            out = os.path.join(out_dir, "%s%s.docx" % (prefix, name))
            dest_doc.save(out)
            merged += 1
            outs.append(out)
            logs.append("成功：%s" % name)
            _report("已合并：%s -> %s" % (name, out))
        except Exception as e:  # noqa: BLE001  —— 单个学生失败不影响其它学生
            logs.append("失败：%s（%s）" % (name, e))
            _report("失败：%s：%s" % (name, e))

    logs.append("合并 %d 份，复制 %d 份。" % (merged, copied))
    return {"merged": merged, "copied": copied, "logs": logs, "outs": outs}
