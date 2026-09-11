# -*- coding: utf-8 -*-
"""Windows 高 DPI 适配。

不声明 DPI 感知的进程在 4K/高缩放屏幕上会被系统“位图拉伸”，
导致系统文件对话框又小又模糊。本模块在进程启动最早期声明 DPI 感知，
并把主屏 DPI 提供给 Tk，让文件选择对话框在各种分辨率/缩放下都清晰、大小合适。
"""
from __future__ import annotations
import sys

_APPLIED = None


def enable_dpi_awareness() -> str:
    """声明本进程的 DPI 感知级别（必须在创建任何窗口之前调用）。

    依次尝试：Per-Monitor V2（Win10 1703+）→ Per-Monitor（Win8.1+）→ System（Vista+）。
    返回实际生效的级别，便于日志记录与排查。
    """
    global _APPLIED
    if _APPLIED is not None:
        return _APPLIED
    if sys.platform != "win32":
        _APPLIED = "n/a"
        return _APPLIED
    try:
        import ctypes
    except Exception:                                   # noqa: BLE001
        _APPLIED = "no-ctypes"
        return _APPLIED

    # 1) DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4
    try:
        fn = ctypes.windll.user32.SetProcessDpiAwarenessContext
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_bool
        if fn(ctypes.c_void_p(-4)):
            _APPLIED = "per-monitor-v2"
            return _APPLIED
    except Exception:                                   # noqa: BLE001
        pass
    # 2) PROCESS_PER_MONITOR_DPI_AWARE == 2
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            _APPLIED = "per-monitor"
            return _APPLIED
    except Exception:                                   # noqa: BLE001
        pass
    # 3) 退回系统级 DPI 感知
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            _APPLIED = "system"
            return _APPLIED
    except Exception:                                   # noqa: BLE001
        pass
    _APPLIED = "failed"
    return _APPLIED


def primary_dpi() -> int:
    """主屏 DPI（96 为 100% 缩放）。"""
    if sys.platform != "win32":
        return 96
    try:
        import ctypes
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = int(ctypes.windll.gdi32.GetDeviceCaps(hdc, 88))   # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi if dpi > 0 else 96
    except Exception:                                   # noqa: BLE001
        return 96


def tk_scaling() -> float:
    """Tk 的 scaling 值：screen DPI / 72。"""
    return primary_dpi() / 72.0


def describe() -> str:
    """当前 DPI 情况的一句话描述，用于日志。"""
    dpi = primary_dpi()
    return "%s | 主屏 DPI=%d（缩放 %d%%）" % (enable_dpi_awareness(), dpi, round(dpi / 96 * 100))
