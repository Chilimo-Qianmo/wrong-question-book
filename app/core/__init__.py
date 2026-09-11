# -*- coding: utf-8 -*-
"""app.core —— v2 引擎层（从旧版 生成错题集.py / 错题集生成器.py 移植并修复）。

子模块职责：
  * docx_build   —— Word 错题集生成（版式沿用旧版，逐项不变）
  * archive      —— 归档 / 清理 / 配置复用查找 / 合并文件夹展开
  * merge_docx   —— 多个错题集文件夹合并（同名文档合并、图片关系重映射、部分编号续接）
  * excel        —— 答题表解析（表头多形态、判定放宽、姓名列可指定）

本包不做 import 期副作用：子模块按需导入，只有真正用到时才需要 python-docx / openpyxl。
"""
from __future__ import annotations

__all__ = ["archive", "docx_build", "excel", "merge_docx"]

__version__ = "2.0.0"
