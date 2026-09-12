# -*- coding: utf-8 -*-
"""启动器：起本地服务并打开界面（优先原生窗口，回退系统浏览器）。"""
from __future__ import annotations
import argparse
import os
import socket
import sys
import threading
import time
import webbrowser

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


def app_dir() -> str:
    """打包成 exe 后，配置/图片/输出目录应落在 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return APP_DIR


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_ready(port: int, timeout: float = 30.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main() -> int:
    # 必须在创建任何窗口之前声明 DPI 感知：
    # 否则在 4K/高缩放屏上，系统「选择文件」对话框会被位图拉伸得又小又糊。
    from app import dpi
    dpi_tag = dpi.enable_dpi_awareness()

    ap = argparse.ArgumentParser(description="错题集生成器 v2 启动器")
    ap.add_argument("--port", type=int, default=0, help="固定端口（默认随机空闲端口）")
    ap.add_argument("--no-window", action="store_true", help="只起服务，不开界面")
    args = ap.parse_args()

    try:
        os.chdir(app_dir())
    except OSError:
        pass

    # 新环境第一次启动：先把 错题集/图片/题目配置 建好，用户打开即是可用状态
    from app import paths
    created = paths.ensure_dirs(app_dir())
    if created and not args.no_window:
        print("已创建目录：%s" % "、".join(os.path.basename(p) for p in created))
    # 读一次设置：会顺带把失效的目录（例如指向已不存在的临时目录）改回程序所在目录
    try:
        from app.main import load_settings
        _s = load_settings()
        if not args.no_window:
            print("输出目录：%s" % _s.out_dir)
            print("图片目录：%s" % _s.images_root)
            print("缓存目录：%s" % os.path.join(app_dir(), ".cache"))
    except Exception:                                   # noqa: BLE001
        pass

    import uvicorn
    port = args.port or free_port()
    url = "http://127.0.0.1:%d/" % port
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    if args.no_window:
        print("服务已启动：%s" % url)
        server.run()
        return 0

    use_webview = False
    try:
        import webview  # noqa: F401
        use_webview = True
    except Exception:
        use_webview = False

    if use_webview:
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        if not wait_ready(port):
            print("服务启动超时")
            return 1
        import webview
        webview.create_window("学生错题集生成器", url, width=1180, height=820, min_size=(940, 660))
        webview.start()
        return 0

    print("=" * 56)
    print(" 学生错题集生成器 v2")
    print(" DPI 感知：%s" % dpi.describe())
    print(" 界面地址：%s" % url)
    print(" 关闭本窗口即结束程序。")
    print("=" * 56)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
