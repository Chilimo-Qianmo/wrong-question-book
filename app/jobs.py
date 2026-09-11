# -*- coding: utf-8 -*-
"""后台任务与进度事件（线程 + 队列 → SSE）。"""
from __future__ import annotations
import queue
import threading
import time
import traceback
import uuid

JOBS: dict = {}


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.state = "running"          # running | done | error | cancelled
        self.percent = 0.0
        self.message = ""
        self.result = None
        self.error = ""
        self.tb = ""
        self.started_at = time.time()
        self.finished_at = 0.0
        self.q: queue.Queue = queue.Queue()
        self.cancel_flag = threading.Event()

    # --- 事件 ---
    def log(self, msg, level="info"):
        self.q.put(("log", {"ts": time.strftime("%H:%M:%S"), "level": level, "msg": str(msg)}))

    def progress(self, msg, done=0, total=1, stage=""):
        pct = (done / total * 100.0) if total else 0.0
        self.percent = max(self.percent, min(100.0, pct))
        self.message = str(msg)
        self.q.put(("progress", {"stage": stage, "done": done, "total": total,
                                 "percent": round(self.percent, 1), "msg": str(msg)}))

    def finish(self, result):
        self.state = "done"
        self.percent = 100.0
        self.result = result
        self.finished_at = time.time()
        self.q.put(("result", result))

    def fail(self, exc):
        self.state = "error"
        self.error = str(exc)
        self.tb = traceback.format_exc()
        self.finished_at = time.time()
        self.q.put(("error", {"message": str(exc), "traceback": self.tb}))

    def to_status(self) -> dict:
        return {"id": self.id, "kind": self.kind, "state": self.state,
                "percent": round(self.percent, 1), "message": self.message,
                "result": self.result, "error": self.error,
                "started_at": self.started_at, "finished_at": self.finished_at}


def start(kind: str, fn) -> Job:
    """把 fn(job) 放到后台线程执行。fn 内部用 job.log/progress 上报。"""
    job = Job(kind)
    JOBS[job.id] = job

    def runner():
        try:
            result = fn(job)
            if job.cancel_flag.is_set():
                job.state = "cancelled"
                job.q.put(("error", {"message": "任务已取消", "traceback": ""}))
                return
            job.finish(result)
        except Exception as e:                      # noqa: BLE001
            job.fail(e)
            try:
                import traceback as _tb
                syserr = _tb.format_exc()
                job.tb = syserr
            except Exception:
                pass

    t = threading.Thread(target=runner, daemon=True, name="job-" + job.id)
    t.start()
    return job


def sweep(max_age: float = 3600.0) -> None:
    """清理过期任务，避免长时间运行内存增长。"""
    now = time.time()
    for jid in [k for k, j in JOBS.items()
                if j.state != "running" and now - j.finished_at > max_age]:
        JOBS.pop(jid, None)
