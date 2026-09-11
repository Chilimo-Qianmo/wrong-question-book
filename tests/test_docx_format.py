# -*- coding: utf-8 -*-
"""Word 版式符合性测试（任务1）。

逐条校验生成文档是否满足约定的版式要求：
  1) 页边距 上下左右 = 1.27cm
  2) 页眉 = 学生姓名（居中）
  3) 页眉上边距 / 页脚下边距 = 0.8cm
  4) 页脚 = 居中页码（PAGE 域，显示 1、2、3）
  5) 选项缩进 2 个字符；题目（题干）不缩进
  6) 字体宋体、正文 5 号（10.5pt）
  7) 行距 1.1
  8) 段前段后间距 0

用法：python tests/test_docx_format.py
"""
from __future__ import annotations
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from docx import Document                                   # noqa: E402
from docx.oxml.ns import qn                                 # noqa: E402
from app.core import docx_build                             # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((bool(cond), name, detail))


def indent_chars(paragraph):
    """读取段落的「首行缩进字符数」（w:firstLineChars 的百分之一百倍）。"""
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        return None
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        return None
    v = ind.get(qn("w:firstLineChars"))
    return int(v) / 100.0 if v is not None else None


def build_sample(dirpath):
    qmap = {
        1: {"stem": "刺梨富含抗氧化物超氧化物歧化酶（SOD），含有两条肽链。下列叙述错误的是",
            "options": {"A": "构成SOD的基本单位是氨基酸", "B": "在核糖体上合成SOD需要酶和能量",
                        "C": "Cu、Zn等微量元素可参与大分子合成", "D": "高温会使SOD中肽键断裂"},
            "tables": [], "figures": []},
        2: {"stem": "破伤风外毒素可导致小鼠死亡。下列分析错误的是",
            "options": {}, "tables": [{"columns": ["选项", "实验名称"], "rows": [["A", "甲"]],
                                      "as_answer": True}], "figures": []},
    }
    return docx_build.build_student_docx("张三", [1, 2], qmap, os.path.join(dirpath, "img"),
                                         "测试卷", dirpath)


def main() -> int:
    d = tempfile.mkdtemp(prefix="docx_fmt_")
    path = build_sample(d)
    doc = Document(path)
    sec = doc.sections[0]

    # 1) 页边距
    for label, val in (("上", sec.top_margin.cm), ("下", sec.bottom_margin.cm),
                       ("左", sec.left_margin.cm), ("右", sec.right_margin.cm)):
        check("页边距%s = 1.27cm" % label, abs(val - 1.27) < 0.01, "实测 %.3fcm" % val)
    # 2) 页眉
    hp = sec.header.paragraphs[0]
    check("页眉为学生姓名", hp.text.strip() == "张三", "实测 %r" % hp.text)
    check("页眉居中", hp.alignment == 1 or (hp.alignment is not None and int(hp.alignment) == 1),
          "实测 %s" % hp.alignment)
    # 3) 页眉/页脚距离
    check("页眉上边距 = 0.8cm", abs(sec.header_distance.cm - 0.8) < 0.01,
          "实测 %.3fcm" % sec.header_distance.cm)
    check("页脚下边距 = 0.8cm", abs(sec.footer_distance.cm - 0.8) < 0.01,
          "实测 %.3fcm" % sec.footer_distance.cm)
    # 4) 页脚页码
    fp = sec.footer.paragraphs[0]
    check("页脚含 PAGE 域（1、2、3 页码）", "PAGE" in fp._p.xml)
    check("页脚居中", fp.alignment == 1 or (fp.alignment is not None and int(fp.alignment) == 1),
          "实测 %s" % fp.alignment)

    # 5/6/7/8) 正文段落
    body = [p for p in doc.paragraphs if p.text.strip()]
    stems, options = [], []
    for p in body:
        t = p.text.strip()
        if t.startswith("第 ") and t.endswith("题"):
            continue
        if t[:2] in ("A.", "B.", "C.", "D.", "E."):
            options.append(p)
        elif not t.endswith("错题集") and "错题题号" not in t and "·" not in t:
            stems.append(p)

    check("题干段落不缩进", all((indent_chars(p) in (None, 0)) for p in stems),
          "实测 %s" % [indent_chars(p) for p in stems])
    check("选项缩进 2 个字符", options and all(indent_chars(p) == 2.0 for p in options),
          "实测 %s" % [indent_chars(p) for p in options])
    bad_size = [p.runs[0].font.size.pt for p in stems + options
                if p.runs and p.runs[0].font.size and abs(p.runs[0].font.size.pt - 10.5) > 0.01]
    check("正文/选项字号 10.5pt（五号）", not bad_size, "异常字号 %s" % bad_size)
    bad_font = [p.runs[0].font.name for p in stems + options
                if p.runs and p.runs[0].font.name not in (None, "宋体")]
    check("正文字体宋体", not bad_font, "异常字体 %s" % bad_font)
    bad_ls = [p.paragraph_format.line_spacing for p in stems + options
              if p.paragraph_format.line_spacing not in (None, 1.1)]
    check("行距 1.1", not bad_ls, "异常行距 %s" % bad_ls)
    bad_sp = []
    for p in doc.paragraphs:
        pf = p.paragraph_format
        sb = pf.space_before.pt if pf.space_before is not None else 0
        sa = pf.space_after.pt if pf.space_after is not None else 0
        if sb != 0 or sa != 0:
            bad_sp.append((p.text[:14], sb, sa))
    check("段前段后间距 0", not bad_sp, "异常 %s" % bad_sp)

    ok = sum(1 for r in RESULTS if r[0])
    print("=" * 68)
    print("Word 版式符合性测试（任务1）—— 生成样本：%s" % os.path.basename(path))
    print("=" * 68)
    for good, name, detail in RESULTS:
        print("  %s %s%s" % ("[OK]" if good else "[!!]", name, ("  " + detail) if detail and not good else ""))
    print("-" * 68)
    print("通过 %d / %d 项" % (ok, len(RESULTS)))
    print("结论：%s" % ("全部符合" if ok == len(RESULTS) else "存在不符合项"))
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
