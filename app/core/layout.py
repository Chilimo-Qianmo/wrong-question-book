# -*- coding: utf-8 -*-
"""统一的版面中间结构：无论电子版还是扫描版，后续识别只认这个结构。"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class TableRegion:
    page: int
    bbox: tuple                      # (x0, y0, x1, y1) 页面坐标
    cells: list | None = None        # [["可选","经典实验","实验设计"], ...]
    source: str = "ruled"            # structured=PDF自带表格; ruled=线框检测
    image_path: str | None = None    # 裁图预览（可选）

    def as_spec(self, as_answer: bool = False) -> dict:
        """转成写 Word 用的表格规格。"""
        if not self.cells:
            return {}
        cols = [str(c).replace("\n", "") for c in self.cells[0]]
        rows = [[str(c).replace("\n", "") for c in r] for r in self.cells[1:]]
        return {"columns": cols, "rows": rows, "as_answer": as_answer}


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
