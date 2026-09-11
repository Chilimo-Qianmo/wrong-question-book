#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
错题集自动生成脚本
==================
将「试卷.pdf」「答题情况.xlsx」「各题目图片文件夹」作为输入，
自动为每位学生生成『错题集_学生姓名.docx』。

特性
----
* 从扫描版试卷自动识别选择题题干与选项（OCR，需 RapidOCR）。
* 按学生错题（答题表中得分 0 的题）汇总。
* 每题在「题干」与「答案」之间插入该题号文件夹内的全部图片（按文件名排序）；
  若文件夹为空或不存在，则省略（不标注“无图片”）。
* 支持可选“标准答案”文件。

用法
----
  python 生成错题集.py --pdf 试卷.pdf --excel 答题情况.xlsx --images 图片 --out 错题集输出

可选参数
--------
  --answers 标准答案.json       题号 -> 正确选项，如 {"1":"A","2":"B",...}，用于附注“标准答案”
  --title  试卷标题             用于文档副标题，默认可自动从试卷首页识别
  --cache  ocr缓存.json         缓存 OCR 结果以便重复运行提速

依赖
----
  pip install pypdfium2 rapidocr_onnxruntime openpyxl python-docx
"""

import argparse
import glob
import json
import os
import re

from openpyxl import load_workbook
from PIL import Image

import pypdfium2 as pdfium
from rapidocr_onnxruntime import RapidOCR

from docx import Document
from docx.shared import Pt, Inches, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# --------------------------------------------------------------------------- #
# 以下两个字典用于“修正”自动 OCR 识别，可按自己试卷增删改。
#  - QUESTION_STEMS：题干文本。自动识别对扫描件（尤其含示意图的题）可能不完整，
#    这里给出准确题干；若某题不在其中，则回退到 OCR 自动拼接的题干。
#  - TABLE_SPEC：把“表格型”题目（题干/选项以表格呈现）还原成 Word 表格。
#    格式：{题号: {"columns": [...], "rows": [[...], ...], "as_answer": bool}}
#    as_answer=True 时表格放在“答案”处；否则放在题干之后、选项之前。
# --------------------------------------------------------------------------- #
QUESTION_STEMS = {
    1: "刺梨富含抗氧化物超氧化物歧化酶（SOD），SOD由Cu²⁺、Zn²⁺等金属离子与蛋白质共同构成，含有两条肽链。下列叙述错误的是",
    2: "GLUT4是脂肪细胞和骨骼肌细胞最主要的葡萄糖转运蛋白，当血糖浓度升高时，细胞膜上受体识别胰岛素后会引起细胞膜上GLUT4含量增加，GLUT4与葡萄糖结合并发生自身构象变化，将葡萄糖顺浓度梯度转运至组织细胞内。下列叙述错误的是",
    3: "我国科考队在太平洋马里亚纳海沟采集到一种蓝细菌，其细胞内存在由两层膜组成的片层结构，此结构可进行光合作用与呼吸作用。对该结构的推测错误的是",
    4: "线虫是生物学研究中常用的模式生物。科学家在研究细胞凋亡时对线虫进行诱变处理，发现C3基因功能缺失突变体中本应该凋亡的细胞存活。下列叙述正确的是",
    5: "衣藻（n=17）是一种单细胞的真核生物，在环境适宜时，通过孢子连续进行无性生殖；环境条件恶劣时进行有性生殖。其生活史如图所示，下列叙述错误的是",
    6: "经许多科学家及团队不断努力，人们逐渐了解了遗传物质的本质。下列叙述错误的是",
    7: "野生香蕉（2n=22）是一种二倍体植物。如图为无子香蕉的培育过程，植株甲由野生香蕉染色体加倍后获得的四倍体与野生香蕉杂交而来。下列叙述正确的是",
    8: "炎症反应主要由组织释放炎症介质（如：组织胺等）引发，使血管壁通透性增强、局部血液循环和淋巴循环受阻，对细胞呼吸造成影响，严重时可导致患者出现组织坏死等症状。下列叙述错误的是",
    9: "促甲状腺激素（TSH）可调节甲状腺激素的分泌。为研究甲状腺激素分泌的调控，某研究小组用若干生理状况相同的健康家兔进行了下列相关实验。给甲、乙、丙三组家兔分别静脉注射一定量的生理盐水、促甲状腺激素溶液、促甲状腺激素抑制剂。一段时间后分别测定三组家兔血液中甲状腺激素的含量并进行分析。下列叙述正确的是",
    10: "破伤风外毒素是破伤风杆菌分泌的一种强毒性物质，可导致小鼠死亡。研究人员利用生理状态相同的小鼠进行破伤风类毒素（抗原）和破伤风抗毒素（抗体）预防破伤风的免疫学研究，实验处理及结果如下表所示。下列分析错误的是",
    11: "莴苣种子萌发受多种内外因素的调节。下列叙述正确的是",
    12: "松材线虫是一种对松树具有极大危害的外来入侵物种，成虫虫体长约1毫米，主要从松树的木质部汲取养分导致松树枯死。可引入能侵染松材线虫的白僵菌孢子对其进行防治。下列叙述正确的是",
    13: "夏季高山峡谷常在暴雨后发生山体滑坡形成滑坡体，滑坡体的恢复治理主要有自然修复和人工修复两种方式。经过一段时间的演替，滑坡体的动植物多样性会逐渐恢复到原有水平。下列叙述正确的是",
    14: "下列对有关实验操作的叙述，正确的是",
    15: "某种臭豆腐制作时需要将豆腐浸入含有乳酸菌、芽孢杆菌等微生物的卤汁中发酵。随着市场发展，人们逐渐开始尝试运用发酵罐生产臭豆腐。下列叙述错误的是",
    16: "猪的器官是人体异种器官移植的最佳来源。研究发现，移植来自转入人hCD39基因的基因编辑猪的器官，能有效降低免疫排斥反应。图为获得基因编辑猪的示意图，下列叙述错误的是",
}

TABLE_SPEC = {
    # 注意：第 10 题的表格是“题目配图”，应作为图片插入（由用户截图放入 图片/10/），
    # 因此不在这里生成 Word 表格。第 14 题的表格是“答案”，用 as_answer=True 放在答案处。
    14: {
        "columns": ["选项", "实验名称", "相关操作"],
        "rows": [
            ["A", "探究淀粉酶对淀粉和蔗糖的水解作用", "保温相同时间后，用碘液进行检测"],
            ["B", "探索生长素类调节剂促进插条生根的最适浓度", "进行预实验时无需设置空白对照"],
            ["C", "研究土壤中小动物类群的丰富度", "打开诱虫器顶端的电灯可驱使小动物向下移动"],
            ["D", "DNA的粗提取与鉴定", "向溶解DNA的NaCl溶液中加入二苯胺后立即观察实验现象"],
        ],
        "as_answer": True,    # 表格即本题的四个选项（答案），放在“答案”处
    },
}

MARGIN_CHARS = {"号", "证", "考", "准", "名", "姓"}   # 试卷左侧“准考证号/姓名”竖排文字，需过滤


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def set_font(run, size=None, bold=None, color=None, name="宋体"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def render_pages(pdf_path, out_dir, scale=3.0):
    """把 PDF 每页渲染成 PNG，返回 {页码(index 1): 图片路径}"""
    os.makedirs(out_dir, exist_ok=True)
    pdf = pdfium.PdfDocument(pdf_path)
    paths = {}
    for i, page in enumerate(pdf):
        img = page.render(scale=scale).to_pil()
        fp = os.path.join(out_dir, "page_%02d.png" % (i + 1))
        img.save(fp)
        paths[i + 1] = fp
    pdf.close()
    return paths


def ocr_pages(page_paths, cache=None):
    """对每页 OCR，返回 {页码: [bbox框,...]}。cache 为 json 路径时读取/保存结果。"""
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    engine = RapidOCR()
    result = {}
    for page, fp in page_paths.items():
        res, _ = engine(fp)
        boxes = []
        if res is not None:
            for item in res:
                p = item[0]
                xs = [pt[0] for pt in p]
                ys = [pt[1] for pt in p]
                boxes.append({
                    "bbox": [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))],
                    "text": item[1],
                    "score": float(item[2]),
                })
        result[page] = boxes
    if cache:
        try:
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except OSError:
            pass  # 缓存目录不可写时忽略，不影响生成
    return result


# 常见卷面小节关键字（可按试卷调整）
SECTION_START = ["选择题", "单选题", "单项选择", "选择题部分"]
SECTION_END = ["非选择题", "解答题", "非选择", "第II卷", "第二部分", "主观题", "计算题", "简答题"]


def _qno_of(text):
    """识别题号：支持 1． / 1. / 1、 / 1： / 1) / (1) 等形式。"""
    s = text.strip()
    m = re.match(r"^\(?(\d{1,3})\)?\s*[．.、:：]\s*", s)
    if m:
        return int(m.group(1))
    m2 = re.match(r"^\(?(\d{1,3})\)?\s+\S", s)
    if m2:
        return int(m2.group(1))
    return None


def _is_question_box(ocr_box, sec_end):
    t = ocr_box["text"]
    if any(k in t for k in sec_end):
        return False
    if "试卷第" in t and "页" in t:
        return False
    return True


def _is_page_header_footer(text, bbox, page_h):
    """判断是否为页眉/页脚：位于页面顶部/底部边缘、且为“非内容”的短文本
    （页眉、页码、第X页等）。题干/选项/较长文本（如选项正文）不会被误删。"""
    y0, y1 = bbox[1], bbox[3]
    if not (page_h and (y0 < page_h * 0.06 or y1 > page_h * 0.94)):
        return False
    s = text.strip()
    if not s:
        return True
    # 明显是内容：以选项字母开头 / 以题号开头 / 较长（选项正文等）
    if re.match(r"^[A-Da-d]\s*[．.、:：)]", s):
        return False
    if _qno_of(s) is not None:
        return False
    if "试卷第" in s or ("页" in s and len(s) <= 3):
        return True
    if len(s) > 8:
        return False
    # 其余短文本（页眉“选择题训练一1”、页码等）作为页眉页脚
    return True


def _is_option_junk(s):
    """不应并入选项的杂项：页码、页脚、题号、小节标题等。"""
    if re.match(r"^\d{1,3}$", s):              # 纯数字（页码）
        return True
    if "试卷第" in s or ("页" in s and len(s) <= 3):  # 页脚
        return True
    if _qno_of(s) is not None:                  # 题号
        return True
    if any(k in s for k in ("非选择题", "解答题", "第II卷", "主观题", "计算题", "简答题")):
        return True
    return False


def _is_section_title(t, sec_start=None, strict=False):
    """是否为“选择题”小节标题。

    strict=True ：正式小节标题（含“小题/本题共/部分”或以中文数字开头），
                  避免把“注意事项”里“回答选择题…”等说明当成标题。
    strict=False：宽松匹配短标题/卷名（如“选择题训练-2”“选择题”）。
    """
    sec_start = sec_start or SECTION_START
    if not any(k in t for k in sec_start):
        return False
    if "非选择题" in t:                       # 结束标题，或“选择题和非选择题…”说明句
        return False
    if any(k in t for k in ("回答", "选出", "填涂", "作答", "请将", "考生", "铅笔")):
        return False
    if ("小题" in t or "本题共" in t or "部分" in t
            or re.match(r"^[一二三四五六]\s*[、．.]", t)):
        return True
    return (not strict) and len(t) <= 20


def group_questions(ocr, sec_start=None, sec_end=None):
    """按题号把 OCR 框分组为“选择题”。

    通用策略：
      1) 先按“选择题”小节标题定位起点（正式标题优先，其次兼容“选择题训练-2”这类卷名/页眉短标题）；
      2) 从起点后第一个题号开始按连续题号收集；读到结束关键字、跳号或达到声明题数（共N小题）则停；
      3) 若全卷没有小节标题，则从卷面第一个题号开始（不再要求必须是 1）；
      4) 若首个识别到的题号是 2（首题题号被 OCR 漏识别），把“起点→首个题号”之间的内容补回为第 1 题。
    """
    sec_start = sec_start or SECTION_START
    sec_end = sec_end or SECTION_END

    # 1) 原始框（含页眉页脚），用于识别可能写在页眉上的“选择题…”卷名
    raw_boxes = []
    for page in sorted(ocr, key=int):
        for b in sorted(ocr[page], key=lambda x: (x["bbox"][1], x["bbox"][0])):
            t = b["text"].strip()
            if t:
                raw_boxes.append({"page": int(page), "box": b, "text": t})

    # 2) 过滤页眉/页脚/边栏，得到内容框
    all_boxes = []
    for page in sorted(ocr, key=int):
        page_boxes = sorted(ocr[page], key=lambda x: (x["bbox"][1], x["bbox"][0]))
        # 用本页最靠下的框近似页面高度，用于识别顶部/底部页眉页脚
        page_h = max((b["bbox"][3] for b in page_boxes), default=0)
        for b in page_boxes:
            t = b["text"].strip()
            if not t:
                continue
            if len(t) == 1 and t in MARGIN_CHARS and b["bbox"][0] < 180:
                continue
            if "试卷第" in t and "页" in t:
                continue
            if _is_page_header_footer(t, b["bbox"], page_h):
                continue   # 过滤页眉/页脚（如“选择题训练一1”、页码等）
            all_boxes.append({"page": int(page), "box": b, "text": t})

    # 3) 定位“选择题”小节起点：正式标题优先，其次宽松匹配短标题/卷名（含写在页眉上的卷名）
    anchor = None
    for strict in (True, False):
        for b in raw_boxes:
            if _is_section_title(b["text"], sec_start, strict=strict):
                anchor = (b["page"], b["box"]["bbox"][1])
                break
        if anchor is not None:
            break

    start_idx = None
    if anchor is not None:
        ap, ay = anchor
        start_idx = next((i for i, b in enumerate(all_boxes)
                          if b["page"] > ap or (b["page"] == ap and b["box"]["bbox"][1] >= ay - 1)), None)

    declare_count = None
    if start_idx is not None:
        q0 = next((i for i in range(start_idx, len(all_boxes))
                   if _qno_of(all_boxes[i]["text"]) is not None), None)
        if q0 is None:
            return {}
        for b in all_boxes[start_idx:q0 + 3]:
            m = re.search(r"共\s*(\d+)\s*小题", b["text"])
            if m:
                declare_count = int(m.group(1))
                break
    else:
        # 无小节标题：从卷面第一个题号开始（兼容首题题号缺失、起点不是 1 的情况）
        q0 = next((i for i, b in enumerate(all_boxes) if _qno_of(b["text"]) is not None), None)
        if q0 is None:
            return {}

    questions = {}
    # 首题题号被 OCR 漏识别：把“起点 → 第一个题号”之间的内容补为第 1 题
    if start_idx is not None and _qno_of(all_boxes[q0]["text"]) == 2:
        pre = [b for b in all_boxes[start_idx:q0] if not _is_section_title(b["text"], sec_start)]
        if any(len(b["text"]) >= 6 for b in pre):
            questions[1] = {"page": pre[0]["page"],
                            "boxes": [dict(b["box"], page=b["page"]) for b in pre]}

    expected = _qno_of(all_boxes[q0]["text"])
    i = q0
    while i < len(all_boxes):
        b = all_boxes[i]
        t = b["text"]
        if any(k in t for k in sec_end):
            break
        qn = _qno_of(t)
        if qn == expected:
            questions.setdefault(qn, {"page": b["page"], "boxes": []})
            questions[qn]["boxes"].append(dict(b["box"], page=b["page"]))
            j = i + 1
            while j < len(all_boxes):
                bt = all_boxes[j]["text"]
                bqn = _qno_of(bt)
                if bqn is not None and bqn == expected + 1:
                    break
                if any(k in bt for k in sec_end) or ("试卷第" in bt and "页" in bt):
                    break
                questions[qn]["boxes"].append(dict(all_boxes[j]["box"], page=all_boxes[j]["page"]))
                j += 1
            i = j
            expected += 1
            if declare_count is not None and expected > declare_count:
                break
        else:
            if qn is not None and qn > expected:
                break
            i += 1
    return questions


def split_stem_options(boxes):
    """从题目文本框拆出题干与选项。

    boxes: [{text, bbox}]（题内文本框）。使用“几何就近”把【选项字母】与其【文本
    （可能被 OCR 拆成单独框）】关联起来，兼容：
      * 选项字母与正文被拆成两行/两列（如 “C.” 与正文分开）；
      * 纯英文(如基因型 HhMM)选项；
      同时排除页码/页脚/题号等杂项。
    """
    opt_re = re.compile(r"^[（(]?\s*([A-Da-d])\s*[)）]?\s*[．.、:：\s]\s*(.*)$")

    def center(b):
        return ((b["bbox"][0] + b["bbox"][2]) / 2.0, (b["bbox"][1] + b["bbox"][3]) / 2.0)

    # 排序：先按页(page)再按行(y)、列(x)（跨页题目必须按页排，否则页序会错乱）
    boxes = sorted(boxes, key=lambda b: (b.get("page", 0), round(b["bbox"][1] / 10), b["bbox"][0]))

    # 找出所有“选项字母框”
    letter_boxes = []   # {'letter','idx','text','box'}
    for i, b in enumerate(boxes):
        s = b["text"].strip()
        m = opt_re.match(s)
        if m:
            letter_boxes.append({"letter": m.group(1).upper(), "idx": i,
                                 "text": m.group(2).strip(), "box": b})

    if not letter_boxes:
        return [b["text"] for b in boxes], {}

    first = letter_boxes[0]["idx"]
    stem_lines = [b["text"] for b in boxes[:first]]

    # 各选项的初始文本 = 选项字母框自身的尾部文字（有的框“字母+正文”同一框）
    options = {lb["letter"]: lb["text"] for lb in letter_boxes}
    letter_idx = {lb["idx"] for lb in letter_boxes}

    # 续行：选项区内、非选项字母、非杂项 的框
    continuations = []
    for i, b in enumerate(boxes):
        if i < first or i in letter_idx:
            continue
        s = b["text"].strip()
        if not s or _is_option_junk(s):
            continue
        continuations.append(b)

    # 把每个续行并入“同一行、左侧最近的选项字母”（若在字母下一行则并入上一行字母）
    def row(cy):
        return round(cy / 35.0)

    for b in continuations:
        cx, cy = center(b)
        cr = row(cy)
        pg = b.get("page", 0)
        # 优先：同一页、同一行、位于其左侧的选项字母
        cands = [lb for lb in letter_boxes
                 if lb["box"].get("page", 0) == pg
                 and row(center(lb["box"])[1]) == cr and center(lb["box"])[0] < cx]
        if not cands:
            # 其次：同一页、上一行的选项字母（选项正文换行到下一行）
            cands = [lb for lb in letter_boxes
                     if lb["box"].get("page", 0) == pg
                     and row(center(lb["box"])[1]) == cr - 1 and abs(center(lb["box"])[0] - cx) < 220]
        if cands:
            best = min(cands, key=lambda lb: abs(center(lb["box"])[0] - cx))
            options[best["letter"]] = (options.get(best["letter"]) or "") + b["text"].strip()

    return stem_lines, options


OPTION_RE = re.compile(r"^[（(]?\s*([A-Da-d])\s*[)）]?\s*[．.、:：\s]\s*(.*)$")


def _find_table_regions(boxes):
    """识别一道题里的“表格/插图”区域。

    返回 (regions, protected_ids)：
      regions      —— 表格/插图的外框 bbox 列表 [x0,y0,x1,y1]；
      protected_ids—— 需保留（不算表格）的框 id，即本题题干首行。

    思路：题干是长句、选项是“A./B./C./D.”打头的框，其余短框若呈网格状
    （≥3 个列、每列 ≥2 个框、整体横向跨度大）则判为表格/插图。
    """
    def _is_opt(b):
        return OPTION_RE.match(b["text"].strip()) is not None

    def _prose_len(b):
        # 去掉开头的题号（如“14．”）后再看是不是一句完整表述
        t = re.sub(r"^\s*\(?\d{1,3}\)?\s*[．.、:：]\s*", "", b["text"].strip())
        return len(t)

    # 保护题首的题干（最靠上的一句完整表述），避免被当成表格一起吞掉
    ordered = sorted(boxes, key=lambda b: (b.get("page", 0), b["bbox"][1], b["bbox"][0]))
    first_prose = next((b for b in ordered if _prose_len(b) >= 6 and not _is_opt(b)), None)
    protected = set()
    if first_prose is not None:
        fpg = first_prose.get("page", 0)
        py0, py1 = first_prose["bbox"][1], first_prose["bbox"][3]
        for b in boxes:                                   # 同一页、与题干首行同行的框一并保护
            if b.get("page", 0) == fpg and b["bbox"][1] < py1 and b["bbox"][3] > py0:
                protected.add(id(b))

    regions = []
    # 跨页题目按页分别判断，避免把不同页的坐标混在一起
    for pg in sorted(set(b.get("page", 0) for b in boxes)):
        cand = [b for b in boxes
                if b.get("page", 0) == pg and not _is_opt(b) and id(b) not in protected]
        if len(cand) < 6:
            continue
        # 按左边缘聚类成“列”（每列至少 3 个框，避免把普通排版误判成表格）
        cols = []
        for b in sorted(cand, key=lambda x: x["bbox"][0]):
            x0 = b["bbox"][0]
            for c in cols:
                if abs(c["x"] - x0) <= 30:
                    c["boxes"].append(b)
                    c["x"] = sum(y["bbox"][0] for y in c["boxes"]) / len(c["boxes"])
                    break
            else:
                cols.append({"x": x0, "boxes": [b]})
        cols = [c for c in cols if len(c["boxes"]) >= 3]
        if len(cols) < 3:
            continue
        cols.sort(key=lambda c: c["x"])
        if cols[-1]["x"] - cols[0]["x"] < 300:      # 列之间要足够分散
            continue
        sel = [b for c in cols for b in c["boxes"]]
        if len(sel) < 6:
            continue
        # 纵向切成连通块，避免把相隔很远的两处内容并成一大块
        sel.sort(key=lambda b: b["bbox"][1])
        groups, cur = [], [sel[0]]
        for b in sel[1:]:
            if b["bbox"][1] - max(x["bbox"][3] for x in cur) <= 100:
                cur.append(b)
            else:
                groups.append(cur)
                cur = [b]
        groups.append(cur)
        for grp in groups:
            if len(grp) < 4:
                continue
            regions.append([pg, min(b["bbox"][0] for b in grp), min(b["bbox"][1] for b in grp),
                            max(b["bbox"][2] for b in grp), max(b["bbox"][3] for b in grp)])
    if not regions:
        return [], protected
    # 安全网：剥掉表格/插图后仍须留有题干，否则视为误判、整体放弃
    keep = set()
    for (pg, x0, y0, x1, y1) in regions:
        for b in boxes:
            if b.get("page", 0) != pg:
                continue
            cx = (b["bbox"][0] + b["bbox"][2]) / 2.0
            cy = (b["bbox"][1] + b["bbox"][3]) / 2.0
            if x0 - 3 <= cx <= x1 + 3 and y0 - 3 <= cy <= y1 + 3:
                keep.add(id(b))
    rest = [b for b in boxes if id(b) not in keep]
    if not any(_prose_len(b) >= 6 and not _is_opt(b) for b in rest):
        return [], protected
    return regions, protected


def build_question_map(questions, stems_override=None, options_override=None):
    """题号 -> {题号, 题干, 选项, 表格区域}。题干/选项 优先用配置覆盖，否则自动识别。

    表格/插图区域内的文字不并入题干与选项（避免题干被表格内容污染）；
    这些区域仅记入“表格区域”备查，不再自动转成附图。"""
    stems_override = stems_override or {}
    options_override = options_override or {}
    qmap = {}
    for qn, q in questions.items():
        # 传入带坐标的文本框，供“几何就近”拆选项
        # 先按页、再按行/列排序（跨页题目必须按页排，否则页序会错乱导致题干为空）
        boxes = sorted(q["boxes"],
                       key=lambda b: (b.get("page", 0), round(b["bbox"][1] / 18), b["bbox"][0]))
        regions, protected = _find_table_regions(boxes)
        if regions:
            # 落在表格/插图区域内的框不再并入题干/选项（题号与题干首行除外）
            def _inside(b):
                cx = (b["bbox"][0] + b["bbox"][2]) / 2.0
                cy = (b["bbox"][1] + b["bbox"][3]) / 2.0
                return any(pg == b.get("page", 0) and x0 - 3 <= cx <= x1 + 3 and y0 - 3 <= cy <= y1 + 3
                           for (pg, x0, y0, x1, y1) in regions)
            boxes = [b for b in boxes
                     if id(b) in protected or _qno_of(b["text"]) is not None or not _inside(b)]
        auto_lines, auto_options = split_stem_options(boxes)
        # 选项：优先用配置修正（key 兼容 int/str 题号）
        options = options_override.get(str(qn)) or options_override.get(qn) or auto_options
        stem = stems_override.get(str(qn)) or stems_override.get(qn)
        if not stem:
            # 自动题干：拼接“像句子”的行（>=6字），并保留以标点结尾的短续行
            # （如“正确的是：”只有 5 字，但属于题干的一部分，不能丢）
            prose = [l for l in auto_lines
                     if len(l) >= 6 or re.search(r"[：:。．.？?！!，,、；;]$", l)]
            stem = "".join(prose) if prose else "".join(auto_lines)
            # 去掉开头的题号（如“1．”“2.”），题干不再重复题号
            stem = re.sub(r"^\s*\(?\d{1,3}\)?\s*[．.、:：]\s*", "", stem).strip()
        qmap[qn] = {"题号": qn, "题干": stem, "选项": options, "page": q["page"],
                    "表格区域": regions}
    return qmap


def load_config(config_path):
    """读取可选配置（题目修正）JSON：{"match": "试卷关键字", "stems": {...}, "tables": {...}}"""
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    return None


# --------------------------------------------------------------------------- #
# 读答题情况
# --------------------------------------------------------------------------- #
def load_wrong_answers(excel_path, qnos):
    """返回 {学生姓名: [错误题号,...]}。单元格为 0 视为答错。"""
    wb = load_workbook(excel_path, data_only=True, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return {}
    # 建立“题号 -> 列索引”映射（列名可以是 1 / "1" / 1.0 / "1.0"）
    qidx = {}
    for i, h in enumerate(rows[0]):
        s = str(h).strip()
        m = re.match(r"^(\d+)(\.0)?$", s)
        if m:
            qidx[int(m.group(1))] = i
    wrong = {}
    for r in rows[1:]:
        if not r or r[0] is None:
            continue
        name = str(r[0]).strip()
        bad = []
        for qn in qnos:
            idx = qidx.get(qn)
            if idx is None or idx >= len(r):
                continue
            val = r[idx]
            if val is not None and isinstance(val, (int, float)) and float(val) == 0.0:
                bad.append(int(qn))
        wrong[name] = sorted(bad)
    return wrong


# --------------------------------------------------------------------------- #
# 读取题目图片
# --------------------------------------------------------------------------- #
def find_question_images(images_root, qno):
    """返回 <images_root>/<qno>/ 下所有图片，按文件名排序；无则空列表"""
    qdir = os.path.join(images_root, str(qno))
    if not os.path.isdir(qdir):
        return []
    return [f for f in sorted(glob.glob(os.path.join(qdir, "*")))
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"))]


# --------------------------------------------------------------------------- #
# 生成 Word 文档
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# docx 版式常量（要改格式就在这改）：
#   FONT_NAME ：正文字体（宋体）
#   BODY_SIZE ：正文字号（5号 = 10.5pt）
#   LINE_SPACING ：行距（1.1）
#   P0 ：段前段后间距（0）
#   PAGE_MARGIN ：页边距（上下左右 1.27cm）
#   HDR_FTR_DIST ：页眉上边距 / 页脚下边距（0.8cm）
# --------------------------------------------------------------------------- #
FONT_NAME = "宋体"
BODY_SIZE = 10.5        # 五号
TITLE_SIZE = 16         # 标题字号
HEADING_SIZE = 12       # “第X题”字号
LINE_SPACING = 1.1
PAGE_MARGIN = Cm(1.27)
HDR_FTR_DIST = Cm(0.8)


def _set_first_line_chars(paragraph, chars):
    """按“字符”设置首行缩进（Word 的 firstLineChars=chars*100）。"""
    pPr = paragraph._p.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)
    ind.set(qn("w:firstLineChars"), str(int(chars * 100)))


def _fmt_para(paragraph, align=None, first_line_chars=0):
    """段落基础格式：行距 LINE_SPACING、段前段后 0、可选对齐与首行缩进(字符)。"""
    pf = paragraph.paragraph_format
    pf.line_spacing = LINE_SPACING
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    if align is not None:
        paragraph.alignment = align
    if first_line_chars:
        _set_first_line_chars(paragraph, first_line_chars)
    return paragraph


def add_title(doc, text):
    return _add_text(doc, text, size=TITLE_SIZE, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)


def add_subtitle(doc, text):
    return _add_text(doc, text, size=9, color="595959", align=WD_ALIGN_PARAGRAPH.CENTER)


def add_heading(doc, text):
    return _add_text(doc, text, size=HEADING_SIZE, bold=True)


def add_body(doc, text, prefix=None, size=BODY_SIZE, first_line_chars=0):
    p = doc.add_paragraph()
    if prefix:
        set_font(p.add_run(prefix), size=size, bold=True, name=FONT_NAME)
    set_font(p.add_run(text), size=size, name=FONT_NAME)
    return _fmt_para(p, first_line_chars=first_line_chars)


def _add_text(doc, text, size=BODY_SIZE, bold=False, color=None, align=None, first_line_chars=0):
    p = doc.add_paragraph()
    set_font(p.add_run(text), size=size, bold=bold, color=color, name=FONT_NAME)
    return _fmt_para(p, align=align, first_line_chars=first_line_chars)


def add_option(doc, text):
    """选项：缩进 2 字符，宋体五号。"""
    return _add_text(doc, text, size=BODY_SIZE, first_line_chars=2)


def add_table(doc, spec):
    tbl = doc.add_table(rows=1, cols=len(spec["columns"]))
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(spec["columns"]):
        c = tbl.rows[0].cells[i]
        c.text = ""
        set_font(c.paragraphs[0].add_run(h), size=9, bold=True, name=FONT_NAME)
    for row in spec["rows"]:
        cells = tbl.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            set_font(cells[i].paragraphs[0].add_run(str(val)), size=9, name=FONT_NAME)


def insert_images(doc, img_paths, width_in=6.0):
    for path in img_paths:
        try:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.add_run().add_picture(path, width=Inches(width_in))
        except Exception as e:  # noqa: BLE001
            add_body(doc, "[图片插入失败:%s: %s]" % (os.path.basename(path), e), size=9)


def _add_page_number(run):
    """在 run 里插入 PAGE 域，显示为 1、2、3 的页码。"""
    fld1 = OxmlElement("w:fldChar"); fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = " PAGE "
    fld2 = OxmlElement("w:fldChar"); fld2.set(qn("w:fldCharType"), "end")
    run._r.append(fld1); run._r.append(instr); run._r.append(fld2)


def _setup_section(doc, student_name):
    """页边距 1.27、页眉=姓名、页眉上边距/页脚下边距 0.8、页脚=居中页码。"""
    sec = doc.sections[0]
    sec.top_margin = PAGE_MARGIN
    sec.bottom_margin = PAGE_MARGIN
    sec.left_margin = PAGE_MARGIN
    sec.right_margin = PAGE_MARGIN
    sec.header_distance = HDR_FTR_DIST
    sec.footer_distance = HDR_FTR_DIST

    # 页眉：学生姓名（居中）
    hp = sec.header.paragraphs[0]
    hp.text = ""
    set_font(hp.add_run(student_name), size=9, name=FONT_NAME)
    _fmt_para(hp, align=WD_ALIGN_PARAGRAPH.CENTER)

    # 页脚：页码（居中，1、2、3）
    fp = sec.footer.paragraphs[0]
    fp.text = ""
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = fp.add_run()
    set_font(run, size=9, name=FONT_NAME)
    _add_page_number(run)
    _fmt_para(fp, align=WD_ALIGN_PARAGRAPH.CENTER)


# --------------------------------------------------------------------------- #
# 一道错题的版式（改一道题的样式就在这里）：
#   题号标题 / 题干 / 选项(缩进2字符) / 答案表格 / 图片宽度
# --------------------------------------------------------------------------- #
def add_question_section(doc, qno, q, images_root, tspec, answers):
    """在文档中添加一道错题。顺序：题号 -> 题干 -> (图片/表格) -> 选项(答案)。"""
    add_heading(doc, "第 %d 题" % qno)

    # 题干（不加缩进）
    add_body(doc, q["题干"].strip())

    # 非“答案型”表格（题目配置.json 的 tables 中 as_answer:false 的题）放在题干之后、选项之前
    tspec = tspec or {}
    table = tspec.get(qno) or tspec.get(str(qno))
    if table and not table.get("as_answer"):
        add_table(doc, table)

    # 题目图片：插入在题干与答案之间；无图则省略（不标注“无图片”）
    imgs = find_question_images(images_root, qno)
    if imgs:
        insert_images(doc, imgs)

    # 答案（选项，缩进 2 字符；或“选项以表格呈现”的表格）
    options = q.get("选项") or {}
    if options:
        for letter in ["A", "B", "C", "D"]:
            if letter in options and options[letter]:
                add_option(doc, "%s. %s" % (letter, options[letter]))
    elif table and table.get("as_answer"):
        add_table(doc, table)

    if answers and str(qno) in answers:
        add_body(doc, "标准答案：%s" % str(answers[str(qno)]))
    _fmt_para(doc.add_paragraph())   # 题与题之间的分隔段（0 间距）


def generate_student_docx(name, wrongs, qmap, images_root, tspec, answers, exam_title, out_dir):
    doc = Document()
    # 页面设置：页边距 1.27、页眉姓名、页眉/页脚边距 0.8、页脚页码
    _setup_section(doc, name)

    # 默认字体：宋体 五号
    st = doc.styles["Normal"]
    st.font.name = FONT_NAME
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_NAME)
    st.font.size = Pt(BODY_SIZE)

    add_title(doc, "%s 错题集" % name)
    add_subtitle(doc, exam_title + " · 选择题错题整理")
    wrong_str = "、".join(str(w) for w in wrongs) if wrongs else "无"
    add_body(doc, "错题题号：%s（共 %d 道）" % (wrong_str, len(wrongs)))
    _fmt_para(doc.add_paragraph())

    if wrongs:
        for qno in wrongs:
            add_question_section(doc, qno, qmap[qno], images_root, tspec, answers)
    else:
        p = _add_text(doc, "恭喜！本次考试选择题全部正确，无错题。", size=14, bold=True,
                      color="2E7D32", align=WD_ALIGN_PARAGRAPH.CENTER)

    import time
    import tempfile
    fn = os.path.join(out_dir, "错题集_%s.docx" % name)
    for attempt in range(10):
        try:
            if attempt == 0:
                doc.save(fn)
            else:
                tmp = os.path.join(out_dir, ".tmp_%s_%d.docx" % (name, attempt))
                doc.save(tmp)
                os.replace(tmp, fn)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.4)
    return fn


# --------------------------------------------------------------------------- #
# 生成后的文件管理：归档 + 清理
# --------------------------------------------------------------------------- #
def _exam_name(exam_path, config=None):
    """确定用于归档/命名文件夹的试卷名。

    优先用试卷文件名；若未提供试卷，则从「题目配置」文件所在的
    [日期]-[试卷名]-题目配置 文件夹名推导；再回退用配置的 match 关键字；
    最后回到“配置生成”。"""
    if exam_path and os.path.exists(exam_path):
        return os.path.splitext(os.path.basename(exam_path))[0]
    # 配置来自归档文件夹：...[日期]-[试卷名]-题目配置/题目配置.json
    if isinstance(config, str) and os.path.exists(config):
        parent = os.path.basename(os.path.dirname(config))
        if "-题目配置" in parent:
            p = re.sub(r"-题目配置$", "", parent)
            p = re.sub(r"^\d{8}-", "", p)   # 去掉 [日期]- 前缀
            if p.strip("-_ "):
                return p.strip("-_ ")
    # 回退：用配置的 match 关键字
    cfg = load_config(config) if isinstance(config, str) else config
    if isinstance(cfg, dict) and (cfg.get("match") or "").strip():
        return cfg["match"].strip()
    return "配置生成"


def class_from_excel(excel_path):
    """从答题情况表文件名推断班级名：去掉常见后缀（考试/选择/答题情况/成绩 等）。"""
    name = os.path.splitext(os.path.basename(excel_path or ""))[0]
    for tok in ("答题情况", "选择题", "考试", "成绩", "表格", "得分", "答题"):
        name = name.replace(tok, "")
    name = re.sub(r"[_\-—\s]+$", "", name).strip()
    name = re.sub(r"^[_\-—\s]+", "", name).strip()
    return name or "未分班"


def class_of_folder(path):
    """从错题集文件夹路径推断班级名（用于合并时按班级分类）。

    规则：
    1) 末层是 [YYYYMMDD]-[试卷名] → 取其上一级目录名作为班级；
    2) 否则取路径中含“班/级”的片段；
    3) 再回退到文件夹名。"""
    path = (path or "").rstrip("/\\")
    base = os.path.basename(path)
    if re.match(r"^\d{8}-", base):
        parent = os.path.basename(os.path.dirname(path))
        if parent and parent != "错题集" and not re.match(r"^\d{8}-", parent):
            return parent
    for seg in reversed(path.replace("\\", "/").split("/")):
        if ("班" in seg) or ("级" in seg):
            return seg
    return base or "未分班"


def archive_config(exam_path, out_dir, cfg):
    """把题目配置保存到「与错题集(out_dir) 并列的 题目配置/[日期]-[试卷名]-题目配置」文件夹。

    cfg 可为 dict（直接写入 json）或 文件路径（复制该文件）。同名文件夹存在则复用并覆盖。
    返回保存的文件夹路径；cfg 为空时返回 None。"""
    import datetime
    import shutil
    if cfg is None:
        return None
    date = datetime.date.today().strftime("%Y%m%d")
    # 文件夹名称与试卷(试卷名)绑定
    name = os.path.splitext(os.path.basename(exam_path))[0]
    for ch in ('/', ':', '*', '?', '"', '<', '>', '|', ' '):
        name = name.replace(ch, '_')
    name = name.strip('_') or "试卷"
    folder = "%s-%s-题目配置" % (date, name)
    cfg_root = os.path.join(os.path.dirname(out_dir), "题目配置")
    target = os.path.join(cfg_root, folder)
    os.makedirs(target, exist_ok=True)
    dest = os.path.join(target, "题目配置.json")
    if isinstance(cfg, str) and os.path.exists(cfg):
        shutil.copy2(cfg, dest)
    elif isinstance(cfg, dict):
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    return target


def archive_and_cleanup(out_dir, excel_path, images_root, config=None, render_dir=None, ocr_cache=None, exam_path=None, clean_images=True, cls=None):
    """生成成功后调用：
    1) 在 out_dir 下把本批所有“错题集_*.docx”移入 [班级]/[YYYYMMDD]-[试卷名] 子文件夹；
       无班级则直接放 [YYYYMMDD]-[试卷名]；同名则追加 _1/_2。
    2) 清空图片根目录内所有文件/子文件夹，仅保留空的图片文件夹。
    返回 dict：{folder, moved, leftover}，folder 为相对 out_dir 的路径。"""
    import datetime
    import shutil
    date = datetime.date.today().strftime("%Y%m%d")
    # 归档文件夹名与试卷(试卷名)绑定，特殊字符替换为下划线
    table = os.path.splitext(os.path.basename(exam_path or excel_path))[0]
    table = re.sub(r'[\\/:*?"<>|\s]+', "_", table).strip("_") or "试卷"
    base = "%s-%s" % (date, table)
    # 目标目录：无班级直接放 out_dir；有班级则先建 [班级] 层
    if cls:
        cls = (cls or "").strip("\\/") or "未分班"
        target_dir = os.path.join(out_dir, cls)
        os.makedirs(target_dir, exist_ok=True)
    else:
        target_dir = out_dir
    sub, n = base, 0
    while os.path.exists(os.path.join(target_dir, sub)):
        n += 1
        sub = "%s_%d" % (base, n)
    target = os.path.join(target_dir, sub)
    os.makedirs(target, exist_ok=True)
    folder = os.path.join(cls, sub) if cls else sub   # 相对 out_dir，供界面显示
    # 移动本批生成的文档
    moved = 0
    for f in glob.glob(os.path.join(out_dir, "错题集_*.docx")):
        try:
            shutil.move(f, os.path.join(target, os.path.basename(f)))
            moved += 1
        except OSError:
            pass
    leftover = glob.glob(os.path.join(out_dir, "错题集_*.docx"))

    # 4) 清空图片文件夹（保留空文件夹）；clean_images=False 时保留（分析多个班级同一试卷）
    if clean_images and os.path.isdir(images_root):
        for entry in os.listdir(images_root):
            ep = os.path.join(images_root, entry)
            if os.path.isdir(ep):
                shutil.rmtree(ep, ignore_errors=True)
            else:
                try:
                    os.remove(ep)
                except OSError:
                    pass

    # 2) 归档题目配置到 与错题集并列的「题目配置/[日期]-[试卷名]-题目配置」文件夹
    cfg_folder = archive_config(exam_path or excel_path, out_dir, config)

    # 3) 删除 .render 临时渲染文件夹与 OCR 缓存文件
    if render_dir and os.path.isdir(render_dir):
        shutil.rmtree(render_dir, ignore_errors=True)
    if ocr_cache and os.path.exists(ocr_cache):
        try:
            os.remove(ocr_cache)
        except OSError:
            pass

    return {"folder": folder, "cfg_folder": cfg_folder, "moved": moved, "leftover": len(leftover)}


# --------------------------------------------------------------------------- #
# 复用已保存的题目配置（跳过 OCR 的快路径）
# --------------------------------------------------------------------------- #
def find_config_for_exam(exam_path, out_dir):
    """在「题目配置」文件夹中按试卷名查找已保存的题目配置，返回 dict 或 None。

    保存的配置文件夹名含试卷名（形如 [日期]-[试卷名]-题目配置），
    因此只要文件夹名包含当前试卷名即可命中，便于同一试卷跨批次复用。"""
    if not exam_path:
        return None
    name = os.path.splitext(os.path.basename(exam_path))[0]
    cfg_root = os.path.join(os.path.dirname(out_dir), "题目配置")
    if not os.path.isdir(cfg_root):
        return None
    for d in sorted(os.listdir(cfg_root)):
        if name not in d:
            continue
        cfg_file = os.path.join(cfg_root, d, "题目配置.json")
        if os.path.exists(cfg_file):
            cfg = load_config(cfg_file)
            if cfg and cfg.get("stems"):
                return cfg
    return None


def _build_qmap_from_config(cfg):
    """用已保存的题目配置直接构建 qmap（无需 OCR）。"""
    qmap = {}
    for s, stem in (cfg.get("stems") or {}).items():
        try:
            qn = int(s)
        except (TypeError, ValueError):
            continue
        qmap[qn] = {"题号": qn, "题干": stem,
                    "选项": (cfg.get("options") or {}).get(s) or {},
                    "page": 0}
    return dict(sorted(qmap.items()))


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def generate_all(pdf, excel, images_root, out_dir, title=None, answers=None, cache=None, progress=None, config=None, cleanup=True, keep_images=False, cls=None):
    """完整流水线：渲染+OCR→识别题目→读答题情况→逐学生生成。

    config：可为 配置json路径 或 已解析的 dict（用于按试卷修正题干/表格）。
            配置含 "match"（试卷应包含的关键字）时，只有当试卷 OCR 文本包含该关键字才应用，
            这样同一配置不会污染不同卷子。
    """
    def _report(msg):
        if progress:
            progress(msg)
        else:
            print(msg)

    os.makedirs(out_dir, exist_ok=True)
    render_dir = None   # 快路径（复用配置）不渲染页面，故先置空，供后续清理使用

    # 载入配置：优先用户显式传入；否则尝试从「题目配置」文件夹按试卷名复用（跳过 OCR）
    _report("正在准备题目配置 ...")
    cfg = load_config(config) if isinstance(config, str) else (config or None)
    if cfg is None:
        cfg = find_config_for_exam(pdf, out_dir)
        if cfg:
            _report("已复用「题目配置」文件夹中该试卷的配置（跳过 OCR，可复用）。")

    if cfg and cfg.get("stems"):
        # 快路径：直接用配置构建题目，不 OCR（同一试卷跨批次复用）
        qmap = _build_qmap_from_config(cfg)
        tables = (cfg or {}).get("tables") or {}
        ocr = {}
    else:
        if not pdf or not os.path.exists(pdf):
            raise ValueError("未提供有效的试卷 PDF，且所选题目配置不含题干/选项，无法自动识别。\n请选择试卷，或使用包含题干与选项的题目配置。")
        _report("正在渲染试卷页面 ...")
        render_dir = os.path.join(out_dir, ".render")
        page_paths = render_pages(pdf, render_dir)
        _report("正在识别题目文字（OCR，可能需要 1-2 分钟）...")
        ocr = ocr_pages(page_paths, cache=cache)
        # 校验配置（match 不匹配则忽略，改用自动识别）
        if cfg:
            ocr_text = " ".join(b["text"] for page in ocr.values() for b in page)
            if cfg.get("match") and cfg["match"] not in ocr_text:
                cfg = None
                _report("未匹配到该试卷的题目修正配置，已改用自动识别。")
        stems_override = (cfg or {}).get("stems") or {}
        options_override = (cfg or {}).get("options") or {}
        tables = (cfg or {}).get("tables") or {}
        _report("正在整理题目 ...")
        questions = group_questions(ocr)
        qmap = build_question_map(questions, stems_override=stems_override,
                                 options_override=options_override)

    qnos = sorted(qmap.keys())
    _report("识别到选择题：%s" % qnos)

    _report("正在读取答题情况 ...")
    wrong_by_student = load_wrong_answers(excel, qnos)
    _report("学生人数：%d，有错题：%d" % (len(wrong_by_student), sum(1 for w in wrong_by_student.values() if w)))

    ans = {}
    if answers and os.path.exists(answers):
        with open(answers, encoding="utf-8") as f:
            ans = json.load(f)

    exam_title = title or "模拟测试"
    count = 0
    for name in sorted(wrong_by_student):
        fn = generate_student_docx(name, wrong_by_student[name], qmap, images_root,
                                   tables, ans, exam_title, out_dir)
        count += 1
        _report("生成：%s（错题 %d 道）" % (os.path.basename(fn), len(wrong_by_student[name])))

    _report("完成，共 %d 份文档，输出目录：%s" % (count, os.path.abspath(out_dir)))
    archive = None
    if cleanup:
        _report("正在整理：归档错题集/题目配置，并清理临时文件与图片 ...")
        exam_name = _exam_name(pdf, config)   # 无试卷时用题目配置名命名归档文件夹
        # 构建“本次实际使用”的题目配置用于归档（含自动识别的题干/选项）
        kw = (cfg.get("match") if cfg else "") or _exam_keyword(ocr)
        eff_cfg = {"match": kw,
                   "stems": {str(qn): qmap[qn]["题干"] for qn in qmap},
                   "options": {str(qn): qmap[qn]["选项"] for qn in qmap if qmap[qn]["选项"]},
                   "tables": tables}
        archive = archive_and_cleanup(out_dir, excel, images_root,
                                      config=eff_cfg, render_dir=render_dir, ocr_cache=cache,
                                      exam_path=exam_name, clean_images=not keep_images, cls=cls)
        if archive["leftover"] == 0:
            _report("已归档错题集到：%s（%d 份）；已删除 .render 与 OCR 缓存；临时图片已清空。"
                    % (os.path.join(out_dir, archive["folder"]), archive["moved"]))
        else:
            _report("注意：仍有 %d 份文件未移动，请检查。" % archive["leftover"])
    return {"qnos": qnos, "students": len(wrong_by_student), "docs": count,
            "out": os.path.abspath(out_dir), "archive": archive}


def _exam_keyword(ocr):
    """从 OCR 提取试卷标题并生成较短关键字（用于配置的 match 字段）。"""
    title = None
    for page in sorted(ocr, key=int):
        for b in sorted(ocr[page], key=lambda x: (x["bbox"][1], x["bbox"][0])):
            t = b["text"].strip()
            if ("考试" in t or "试卷" in t) and len(t) >= 5:
                title = t
                break
        if title:
            break
    return _make_keyword(title)


def _make_keyword(title):
    """从试卷标题生成较短的“试卷关键字”，用于配置的 match 字段（如‘铜仁市’）。"""
    if not title:
        return ""
    s = title.strip()
    m = re.search(r"\d{4}", s)          # 年份之前通常是地区名
    if m:
        s = s[:m.start()]
    s = re.sub(r"[、，。．\s]*$", "", s)
    return s if s else title.strip()


def detect_questions(pdf, cache=None, config=None, progress=None, out_dir=None):
    """识别题目文本，返回 (qmap, 试卷关键字)。供 GUI 的“编辑题干/答案”使用。

    - qmap：{题号: {题干, 选项, page}}，配置命中时用配置修正版。
    - 试卷关键字：自动生成（用于“题目配置.json”的 match 字段）。
    - out_dir：输出目录，用于在“题目配置”文件夹中复用已保存的配置（跳过 OCR）。
    """
    def _report(m):
        if progress:
            progress(m)
        else:
            print(m)

    # 优先复用已保存的题目配置：显式传入或用“题目配置”文件夹中的同名配置（跳过 OCR）
    cfg = load_config(config) if isinstance(config, str) else (config or None)
    if cfg is None and out_dir:
        cfg = find_config_for_exam(pdf, out_dir)
    if cfg and cfg.get("stems"):
        _report("已复用「题目配置」文件夹中该试卷的配置（跳过 OCR）。")
        return _build_qmap_from_config(cfg), (cfg.get("match") or "")

    if not pdf or not os.path.exists(pdf):
        raise ValueError("未提供有效的试卷 PDF，无法识别题目。请选择试卷 PDF，或使用包含题干/选项的题目配置。")
    _report("正在识别题目文字（OCR，可能需要 1-2 分钟）...")
    import shutil as _shutil
    render_dir = os.path.join(os.path.dirname(os.path.abspath(pdf)) or ".", ".render")
    try:
        page_paths = render_pages(pdf, render_dir)
        ocr = ocr_pages(page_paths, cache=cache)
    finally:
        _shutil.rmtree(render_dir, ignore_errors=True)   # 识别用的临时渲染图，用完即删

    cfg = load_config(config) if isinstance(config, str) else (config or None)
    if cfg:
        ocr_text = " ".join(b["text"] for page in ocr.values() for b in page)
        if cfg.get("match") and cfg["match"] not in ocr_text:
            cfg = None
    stems_override = (cfg or {}).get("stems") or {}
    options_override = (cfg or {}).get("options") or {}

    questions = group_questions(ocr)
    qmap = build_question_map(questions, stems_override=stems_override, options_override=options_override)

    # 试卷标题（用于生成 match 关键字）
    title = None
    for page in sorted(ocr, key=int):
        for b in sorted(ocr[page], key=lambda x: (x["bbox"][1], x["bbox"][0])):
            t = b["text"].strip()
            if ("考试" in t or "试卷" in t) and len(t) >= 5:
                title = t
                break
        if title:
            break
    return qmap, _make_keyword(title)


# --------------------------------------------------------------------------- #
# 合并两个错题集文件夹（同名学生两份文档合并）
# --------------------------------------------------------------------------- #
def _docx_name(filename):
    """从文件名提取学生姓名（去掉 .docx 与 ‘错题集_’ 前缀）。"""
    name = os.path.splitext(os.path.basename(filename))[0]
    if name.startswith("错题集_"):
        name = name[len("错题集_"):]
    return name.strip()


def _remap_image_rels(dest_part, src_part, element):
    """把 element 中的图片关系重映射到目标文档，保证图片不丢失。"""
    import io as _io
    for blip in element.iter(qn("a:blip")):
        rId = blip.get(qn("r:embed"))
        if rId and rId in src_part.rels:
            img_part = src_part.related_parts[rId]
            new_rId, _ = dest_part.get_or_add_image(_io.BytesIO(img_part.blob))
            blip.set(qn("r:embed"), new_rId)


def _collect_numbers(doc):
    """收集文档中所有‘第 N 题’的题号。"""
    numbers = set()
    for p in doc.paragraphs:
        m = re.match(r"^第\s*(\d+)\s*题", p.text.strip())
        if m:
            numbers.add(int(m.group(1)))
    return numbers


def _copy_body_elements(dest_doc, src_doc, skip_numbers=None, part_offset=0):
    """把 src_doc 的段落/表格复制到 dest_doc（保留图片与文本）。

    skip_numbers：若非 None，则跳过其中题号已出现的题（用于去重）。
    part_offset：若 >0，则重排该文档内部‘第 N 部分’编号（使合并结果结构有序）。"""
    import copy as _copy
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
            m = re.match(r"^第\s*(\d+)\s*题", text.strip())
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


CN_DIGITS = "零一二三四五六七八九"


def _num_to_cn(n):
    if n <= 0:
        return str(n)
    if n < 10:
        return CN_DIGITS[n]
    if n < 20:
        return "十" + (CN_DIGITS[n - 10] if n % 10 else "")
    h, t = divmod(n, 10)
    return CN_DIGITS[h] + "十" + (CN_DIGITS[t] if t else "")


def _cn_to_num(s):
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


def _count_parts(doc):
    """统计文档中“第 N 部分”的最大编号（用于复用合并时递增分隔编号）。"""
    maxp = 1
    for p in doc.paragraphs:
        m = re.match(r".*第\s*([一二三四五六七八九十百\d]+)\s*部分", p.text.strip())
        if m:
            maxp = max(maxp, _cn_to_num(m.group(1)))
    return maxp


def _shift_part_numbers(element, diff):
    """把元素中“第 N 部分”的编号整体增加 diff（保持内部结构有序）。"""
    for p in element.iter(qn("w:p")):
        for r in p.iter(qn("w:r")):
            t = r.find(qn("w:t"))
            if t is not None and t.text:
                m = re.search(r"(第\s*)([一二三四五六七八九十百\d]+)(\s*部分)", t.text)
                if m:
                    t.text = t.text[:m.start(2)] + _num_to_cn(_cn_to_num(m.group(2)) + diff) + t.text[m.end(2):]


def merge_wrong_folders(folders, out_dir, deduplicate=False, copy_single=True, progress=None):
    """多重合并：任选多个错题集文件夹，同名学生的多份文档按顺序合并。

    - folders：文件夹路径列表（>=1），顺序即合并顺序。
    - 同名学生出现在多个文件夹则合并（内容顺序 + 自动递增“第 N 部分”分隔）。
    - 仅一个文件夹出现则复制到输出目录（copy_single=True）。
    - 合并结果可再次作为输入与其他文档合并，分隔编号会自动续接。
    - deduplicate：按‘第 N 题’跨文件夹去重（需文档已标记题号）。
    返回 {merged, copied, logs}。"""
    import shutil
    def _report(msg):
        if progress:
            progress(msg)
        else:
            print(msg)

    os.makedirs(out_dir, exist_ok=True)
    logs = []
    per_folder = [{_docx_name(f): f for f in glob.glob(os.path.join(fd, "*.docx"))} for fd in folders]
    all_names = sorted(set().union(*[set(d) for d in per_folder]))

    merged = 0
    copied = 0
    for name in all_names:
        present = [(i, per_folder[i][name]) for i in range(len(per_folder)) if name in per_folder[i]]
        try:
            if len(present) == 1:
                if copy_single:
                    src = present[0][1]
                    shutil.copy2(src, os.path.join(out_dir, os.path.basename(src)))
                    copied += 1
                    _report("复制（仅单侧）：%s" % name)
                else:
                    _report("跳过（仅在单侧）：%s" % name)
                continue
            base_path = present[0][1]
            dest = Document(base_path)   # 以第一个文件夹为主（保留其样式/版式）
            seen = _collect_numbers(dest) if deduplicate else None
            next_part = _count_parts(dest)   # 基准文档已有的最大部分编号（复用合并时自动续接）
            for (idx, path) in present[1:]:
                doc_i = Document(path)
                next_part += 1
                brk_p = dest.add_paragraph()
                brk_p.add_run().add_break(WD_BREAK.PAGE)
                sep = dest.add_paragraph()
                sep.alignment = WD_ALIGN_PARAGRAPH.CENTER
                sep_r = sep.add_run("———— 第 %s 部分 ————" % _num_to_cn(next_part))
                sep_r.bold = True
                sep_r.font.size = Pt(16)
                # 追加 doc_i；若其本身是合并结果，重排内部“部分”编号以保持有序
                _copy_body_elements(dest, doc_i, skip_numbers=seen, part_offset=next_part - 1)
            prefix = "错题集_" if any(os.path.basename(p[1]).startswith("错题集_") for p in present) else "合并错题集_"
            out = os.path.join(out_dir, "%s%s.docx" % (prefix, name))
            dest.save(out)
            merged += 1
            logs.append("成功：%s" % name)
            _report("已合并：%s -> %s" % (name, out))
        except Exception as e:  # noqa: BLE001
            logs.append("失败：%s（%s）" % (name, e))
            _report("失败：%s：%s" % (name, e))

    logs.append("合并 %d 份，复制 %d 份。" % (merged, copied))
    return {"merged": merged, "copied": copied, "logs": logs}


def main():
    ap = argparse.ArgumentParser(description="自动生成每位学生的错题集 Word 文档")
    ap.add_argument("--pdf", required=True, help="试卷 PDF 路径")
    ap.add_argument("--excel", required=True, help="答题情况 xlsx 路径")
    ap.add_argument("--images", default="图片", help="各题目图片根目录（其下按题号分文件夹）")
    ap.add_argument("--out", default="错题集输出", help="输出目录")
    ap.add_argument("--answers", default=None, help="可选：标准答案 json 文件路径")
    ap.add_argument("--title", default=None, help="可选：试卷标题（用于文档副标题）")
    ap.add_argument("--cache", default=None, help="OCR 缓存 json 路径（可加速重复运行）")
    ap.add_argument("--config", default=None, help="可选：题目修正配置 json 路径（含题干/表格修正）")
    args = ap.parse_args()
    generate_all(args.pdf, args.excel, args.images, args.out, title=args.title,
                 answers=args.answers, cache=args.cache, config=args.config, progress=print)


if __name__ == "__main__":
    main()
