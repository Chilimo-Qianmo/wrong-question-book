# -*- coding: utf-8 -*-
"""前后端数据契约（Pydantic v2）。所有 API 的出参/入参都来自这里。"""
from __future__ import annotations
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class LayoutKind(str, Enum):
    digital = "digital"     # 有文字层
    scanned = "scanned"     # 整页图片
    mixed = "mixed"         # 混合（按页分流）


class PageInfo(BaseModel):
    page: int
    width: float = 0
    height: float = 0
    text_chars: int = 0
    kind: Literal["digital", "scanned"] = "scanned"
    tables: int = 0
    images: int = 0


class SourceInfo(BaseModel):
    path: str = ""
    name: str = ""
    pages: int = 0
    kind: LayoutKind = LayoutKind.scanned
    page_infos: list[PageInfo] = Field(default_factory=list)
    total_chars: int = 0
    has_text_layer: bool = False
    notes: list[str] = Field(default_factory=list)


class DroppedText(BaseModel):
    """被规则剔除、未能进入题干/选项的文本（绝不静默丢弃）。"""
    text: str
    page: int = 0
    bbox: list[float] = Field(default_factory=list)
    reason: str = ""


class FigureRef(BaseModel):
    id: str = ""
    page: int = 0
    bbox: list[float] = Field(default_factory=list)
    path: Optional[str] = None      # 绝对路径
    url: Optional[str] = None       # /api/media/... 供前端显示
    auto: bool = True               # True=自动抽取, False=人工添加
    width: int = 0
    height: int = 0


class TableSpec(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    as_answer: bool = False


class TableRef(BaseModel):
    id: str = ""
    page: int = 0
    bbox: list[float] = Field(default_factory=list)
    cells: Optional[list[list[str]]] = None   # 结构化单元格（电子版/线框）
    source: Literal["structured", "ruled", "manual"] = "ruled"
    as_answer: bool = False
    spec: Optional[TableSpec] = None          # 人工/结构化后转成的写入规格
    image_url: Optional[str] = None           # 扫描版裁图预览


class RegionOut(BaseModel):
    """题目在原始试卷上的区域（用于核对页右侧显示「原题区域」）。

    space='pdf'    坐标是 PDF 点（电子版文字层所在坐标系）
    space='render' 坐标是渲染图像素（扫描版 OCR 所在坐标系），scale 为渲染倍率
    """
    page: int = 1
    bbox: list[float] = Field(default_factory=list)
    space: Literal["pdf", "render"] = "pdf"
    scale: float = 1.0


class QuestionOut(BaseModel):
    qno: int
    page: int = 0
    stem: str = ""
    regions: list[RegionOut] = Field(default_factory=list)
    options: dict[str, str] = Field(default_factory=dict)
    source: Literal["text", "ocr", "config", "mixed"] = "ocr"
    conf: float = 1.0
    warnings: list[str] = Field(default_factory=list)
    dropped: list[DroppedText] = Field(default_factory=list)
    figures: list[FigureRef] = Field(default_factory=list)
    tables: list[TableRef] = Field(default_factory=list)
    verified: bool = False


class Gap(BaseModel):
    expected: int
    found: int
    message: str = ""


class DetectPayload(BaseModel):
    source: Optional[SourceInfo] = None
    questions: list[QuestionOut] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    declared_count: Optional[int] = None
    keyword: str = ""
    elapsed_ms: int = 0


class QuestionConfig(BaseModel):
    """题目配置（磁盘结构 / 生成时覆盖）"""
    schema_version: int = 2
    match: str = ""
    source_exam: str = ""
    stems: dict[str, str] = Field(default_factory=dict)
    options: dict[str, dict[str, str]] = Field(default_factory=dict)
    tables: dict[str, TableSpec] = Field(default_factory=dict)
    figures: dict[str, list[FigureRef]] = Field(default_factory=dict)


class DetectRequest(BaseModel):
    pdf: Optional[str] = None
    config_path: Optional[str] = None
    out_dir: str = ""
    use_cache: bool = True
    prefer_text_layer: bool = True
    scale: float = 3.0


class Settings(BaseModel):
    out_dir: str = ""
    images_root: str = ""
    class_name: str = ""
    exam_title: str = ""
    keep_images: bool = False
    auto_open_after_generate: bool = True
    font_name: str = "宋体"
    body_size: float = 10.5
    line_spacing: float = 1.1
    page_margin_cm: float = 1.27
    image_width_ratio: float = 0.6      # 配图最大宽度 = 正文宽度 × 该比例
    image_dpi_fallback: float = 144.0   # 图片无 DPI 信息时按此 DPI 估算原图尺寸


class GenerateRequest(BaseModel):
    pdf: Optional[str] = None
    excel: str = ""
    images_root: str = ""
    out_dir: str = ""
    title: Optional[str] = None
    cls: str = ""
    config_path: Optional[str] = None
    config: Optional[QuestionConfig] = None
    questions: Optional[list[QuestionOut]] = None   # 核对页确认后的题目（优先）
    keep_images: bool = False
    cleanup: bool = True


class GenerateResult(BaseModel):
    students: int = 0
    docs: int = 0
    out: str = ""
    archive_folder: str = ""
    config_folder: str = ""
    moved: int = 0
    leftover: int = 0


class MergeRequest(BaseModel):
    folders: list[str] = Field(default_factory=list)
    out_dir: str = ""
    deduplicate: bool = False
    copy_single: bool = True


class MergeResult(BaseModel):
    merged: int = 0
    copied: int = 0
    outs: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)


class JobStatus(BaseModel):
    id: str
    kind: str
    state: Literal["running", "done", "error", "cancelled"] = "running"
    percent: float = 0
    message: str = ""
    result: Optional[dict[str, Any]] = None
    error: str = ""
    started_at: float = 0
    finished_at: float = 0


class PickRequest(BaseModel):
    kind: Literal["pdf", "excel", "dir", "images", "config", "any"] = "any"
    title: str = ""
    multi: bool = False
    initialdir: str = ""


class ExcelPeek(BaseModel):
    path: str = ""
    sheet: str = ""
    students: int = 0
    question_columns: list[int] = Field(default_factory=list)
    missing_columns: list[int] = Field(default_factory=list)
    class_name: str = ""
    name_column: int = 0
    notes: list[str] = Field(default_factory=list)
