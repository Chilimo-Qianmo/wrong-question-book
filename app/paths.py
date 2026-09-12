# -*- coding: utf-8 -*-
"""运行期目录约定：打包后一切数据都落在 exe 所在目录，源码运行落在项目根目录。"""
from __future__ import annotations
import os
import sys

# 首次启动时自动创建的三个目录（与 v1 行为一致，用户无需手动建）
APP_FOLDERS = ("错题集", "图片", "题目配置")


def data_dir() -> str:
    """用户数据目录：打包后 = exe 所在目录；源码运行 = 项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_dirs(base: str | None = None) -> list:
    """确保三个工作目录存在，返回成功创建的路径列表。

    新环境第一次启动时目录还不存在，这里一次性建好，
    用户在界面里选目录时就能直接看到，不会以为是空的。
    """
    base = base or data_dir()
    created = []
    for name in APP_FOLDERS:
        p = os.path.join(base, name)
        if not os.path.isdir(p):
            try:
                os.makedirs(p, exist_ok=True)
                created.append(p)
            except OSError:
                pass
    return created


def settings_path() -> str:
    return os.path.join(data_dir(), "settings.json")
