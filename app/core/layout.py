# -*- coding: utf-8 -*-
"""统一的版面中间结构：无论电子版还是扫描版，后续识别只认这个结构。"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

_PURE_NUM = re.compile(r"^\d{1,3}$")


@dataclass
class TableRegion:
    page: int
    bbox: tuple                      # (x0, y0, x1, y1) 页面坐标
    cells: list | None = None        # [["可选","经典实验","实验设计"], ...]
    source: str = "ruled"            # structured=PDF自带表格; ruled=线框检测
    image_path: str | None = None    # 裁图预览（可选）

    def normalize(self) -> list | None:
        """清洗单元格：去换行、去掉全空的行与列。返回二维列表或 None。"""
        if not self.cells or len(self.cells) < 2:
            return None
        grid = [[str(c).replace("\n", "").replace("\r", "").strip() for c in row]
                for row in self.cells]
        grid = [row for row in grid if any(row)]                 # 去掉全空行
        if len(grid) < 2:
            return None
        width = max(len(r) for r in grid)
        keep = [i for i in range(width)
                if any((r[i] if i < len(r) else "") for r in grid)]   # 去掉全空列
        if len(keep) < 2:
            return None
        return [[(r[i] if i < len(r) else "") for i in keep] for r in grid]

    def invalid_reason(self) -> str:
        """判断这是不是一次误检（返回原因，空串表示是有效表格）。

        典型误检：PDF 里的「答题卡编号条」——一排 1 2 3 4 5 …，会被
        pdfplumber.find_tables() 当成 8 列表格；插进题目里就是多余内容。
        """
        grid = self.normalize()
        if not grid:
            return "表格内容为空或不足两行两列"
        total = sum(len(r) for r in grid)
        filled = sum(1 for r in grid for c in r if c)
        if total and filled / total < 0.3:
            return "表格大部分单元格为空，疑似误检"
        head = [c for c in grid[0] if c]
        if len(head) >= 4 and all(_PURE_NUM.match(c) for c in head):
            return "表头是一排连续数字（疑似答题卡编号条或页码条）"
        if len(grid) >= 2 and all(_PURE_NUM.match(c) for r in grid for c in r if c) \
                and sum(1 for r in grid for c in r if c) >= 6:
            return "整表都是数字编号，疑似答题卡编号条"
        return ""

    def as_spec(self, as_answer: bool = False) -> dict:
        """转成写 Word 用的表格规格（自动去掉空行空列）。"""
        grid = self.normalize()
        if not grid:
            return {}
        return {"columns": grid[0], "rows": grid[1:], "as_answer": as_answer}


@dataclass
class FigureRegion:
    page: int
    bbox: tuple
    path: str | None = None
    width: int = 0
    height: int = 0


@dataclass
class Layout:
    path: str = ""
    kind: str = "scanned"
    boxes: list = field(default_factory=list)        # 正文文本块（已剔除页眉页脚/图表区）
    tables: list = field(default_factory=list)       # TableRegion
    figures: list = field(default_factory=list)      # FigureRegion
    dropped: list = field(default_factory=list)      # 被剔除的 Box（带 absent 原因）
    page_sizes: dict = field(default_factory=dict)   # page -> (宽, 高)
    page_kind: dict = field(default_factory=dict)    # page -> digital|scanned
    render_paths: dict = field(default_factory=dict) # page -> 渲染图路径（扫描页）
    scale: float = 3.0
    notes: list = field(default_factory=list)

    def page_height(self, page: int) -> float:
        return self.page_sizes.get(page, (0.0, 0.0))[1]

    def tables_on(self, page: int) -> list:
        return [t for t in self.tables if t.page == page]

    def figures_on(self, page: int) -> list:
        return [f for f in self.figures if f.page == page]
