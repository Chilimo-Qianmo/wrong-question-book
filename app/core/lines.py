# -*- coding: utf-8 -*-
"""文本块 → 行 的聚类（电子版文字层与 OCR 结果共用）。

设计要点：
* 用「纵向重叠 > 50% 较小高度」判定同一行，对 OCR 的 y 抖动（实测可达 4px）免疫；
* 行内按 x0 排序，行间按 (page, y0) 排序，全流程只有这一套顺序规则；
* 行的 x0 取最左块的 x0，供「正文栏 / 选项栏」判定使用。
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Box:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int = 1
    source: str = "ocr"          # text=文字层, ocr=识别
    conf: float = 1.0            # OCR 置信度；文字层恒为 1.0
    absent: str = ""             # 排除原因（非空则不进正文流）

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return max(0.1, self.y1 - self.y0)

    def bbox(self) -> list:
        return [self.x0, self.y0, self.x1, self.y1]


@dataclass
class Line:
    page: int
    boxes: list = field(default_factory=list)
    y0: float = 0.0
    y1: float = 0.0

    @property
    def x0(self) -> float:
        return self.boxes[0].x0 if self.boxes else 0.0

    @property
    def x1(self) -> float:
        return max((b.x1 for b in self.boxes), default=0.0)

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.boxes)

    @property
    def conf(self) -> float:
        if not self.boxes:
            return 1.0
        return sum(b.conf for b in self.boxes) / len(self.boxes)

    def add(self, b: Box) -> None:
        if not self.boxes:            # 首个块直接决定行的 y 范围（旧实现 min(0, y) 恒为 0，导致排序全部失效）
            self.y0, self.y1 = b.y0, b.y1
        else:
            self.y0 = min(self.y0, b.y0)
            self.y1 = max(self.y1, b.y1)
        self.boxes.append(b)

    def sort_boxes(self) -> None:
        self.boxes.sort(key=lambda b: (b.x0, b.y0))


def build_lines(boxes, overlap: float = 0.5) -> list:
    """把文本块聚成行。boxes 需带 page/x0/y0/x1/y1。

    按页分组后逐页聚类，避免跨页误合并；行内按 x0 排序，行间按 (y0, x0) 排序。
    """
    by_page: dict = {}
    for b in boxes:
        if b.text.strip():
            by_page.setdefault(b.page, []).append(b)
    lines: list = []
    for page in sorted(by_page):
        pg_lines: list = []
        for b in sorted(by_page[page], key=lambda x: (x.cy, x.x0)):
            target = None
            for ln in reversed(pg_lines):
                ov = min(ln.y1, b.y1) - max(ln.y0, b.y0)
                if ov > overlap * min(ln.y1 - ln.y0, b.h):
                    target = ln
                    break
                if b.y0 - ln.y1 > 200:      # 再往上找也不可能重叠了
                    break
            if target is None:
                target = Line(page=page)
                pg_lines.append(target)
            target.add(b)
        for ln in pg_lines:
            ln.sort_boxes()
        pg_lines.sort(key=lambda l: (l.y0, l.x0))
        lines.extend(pg_lines)
    return lines


def is_page_furniture(b, page_height: float, top_ratio: float = 0.06, bottom_ratio: float = 0.94) -> str:
    """返回排除原因（空串表示保留）。用于统一电子版/扫描版的页眉页脚判定。"""
    if not page_height:
        return ""
    in_band = b.y0 < page_height * top_ratio or b.y1 > page_height * bottom_ratio
    if not in_band:
        return ""
    t = b.text.strip()
    if not t:
        return "空文本"
    if t.isdigit() and len(t) <= 4:
        return "页码"
    if t.startswith("试卷第") or ("共" in t and "页" in t):
        return "页脚"
    if len(t) <= 12 and not t[:1].isdigit():
        return "页眉/页脚"
    return ""
