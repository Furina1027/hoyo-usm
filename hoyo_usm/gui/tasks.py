"""导出任务管理：单工作线程串行执行，进度事件流、逐文件结果、取消、任务历史。

GUI 同屏只跑一个导出任务（磁盘/ffmpeg 密集），后续任务排队。
每个任务维护事件列表，前端通过 GET /api/tasks/{id}/events?after=N 增量拉取。
已结束的任务摘要 + 逐文件结果持久化到 <应用数据>/tasks.json，重启后仍可查看。
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .. import export as export_mod
from ..export import Options, Result, Target

#: 持久化保留的历史任务数
HISTORY_LIMIT = 50


@dataclass
class Task:
    id: str
    game: str
    options: dict
    out_dir: str
    ffmpeg: str
    targets: list[Target]
    status: str = "queued"            # queued / running / done / failed / cancelled
    total: int = 0
    done: int = 0
    ok: int = 0
    skip: int = 0
    fail: int = 0
    cancelled: int = 0
    error: str = ""
    report_path: str = ""
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    current: list[str] = field(default_factory=list)   # 正在处理的文件
    results: list[dict] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)
    events: list[dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    ev_base: int = 0                  # 已裁掉的事件数（保持 index 单调）

    def emit(self, ev: dict) -> None:
        ev["t"] = time.time()
        with self.lock:
            self.events.append(ev)
            # 事件列表设上限，防止超长任务内存膨胀
            if len(self.events) > 5000:
                del self.events[:1000]
                self.ev_base += 1000

    def events_after(self, after: int) -> tuple[list[dict], int]:
        with self.lock:
            start = max(0, after - self.ev_base)
            return self.events[start:], self.ev_base + len(self.events)

    def summary(self) -> dict:
        return {
            "id": self.id, "game": self.game, "status": self.status,
            "total": self.total, "done": self.done,
            "ok": self.ok, "skip": self.skip, "fail": self.fail,
            "cancelled": self.cancelled,
            "error": self.error, "report_path": self.report_path,
            "out_dir": self.out_dir, "created": self.created,
            "started": self.started, "finished": self.finished,
            "options": self.options, "current": list(self.current),
        }

    def to_record(self) -> dict:
        return self.summary() | {"results": self.results}


class TaskManager:
    """单工作线程的导出任务队列。"""

    def __init__(self, history_path: Path | None = None) -> None:
        self.tasks: dict[str, Task] = {}
        self.order: list[str] = []
        self.queue: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self.history_path = history_path
        self._load_history()
        self._worker = threading.Thread(target=self._run, daemon=True, name="hoyo-usm-task")
        self._worker.start()

    # ---- 历史持久化 ----
    def _load_history(self) -> None:
        if not self.history_path or not self.history_path.is_file():
            return
        try:
            records = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for r in reversed(records if isinstance(records, list) else []):
            try:
                task = Task(id=r["id"], game=r["game"], options=r.get("options") or {},
                            out_dir=r.get("out_dir", ""), ffmpeg="", targets=[])
            except (KeyError, TypeError):
                continue
            for k in ("status", "total", "done", "ok", "skip", "fail", "cancelled", "error",
                      "report_path", "created", "started", "finished"):
                if k in r:
                    setattr(task, k, r[k])
            if task.status in ("queued", "running"):    # 上次异常退出
                task.status = "cancelled"
            task.results = r.get("results") or []
            self.tasks[task.id] = task
            self.order.append(task.id)

    def _save_history(self) -> None:
        if not self.history_path:
            return
        with self.lock:
            done = [self.tasks[i] for i in reversed(self.order)
                    if self.tasks[i].status not in ("queued", "running")]
        records = [t.to_record() for t in done[:HISTORY_LIMIT]]
        try:
            tmp = self.history_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.history_path)
        except OSError:
            pass

    # ---- 队列操作 ----
    def submit(self, game: str, targets: list[Target], options: Options,
               out_dir, ffmpeg: str) -> Task:
        task = Task(
            id=uuid.uuid4().hex[:12],
            game=game,
            options={
                "audio": options.audio, "audio_format": options.audio_format,
                "container": options.container, "verify": options.verify,
                "jobs": options.jobs,
            },
            out_dir=str(out_dir),
            ffmpeg=ffmpeg,
            targets=targets,
        )
        task.total = len(targets)
        with self.lock:
            self.tasks[task.id] = task
            self.order.append(task.id)
        self.queue.put(task.id)
        return task

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def list(self) -> list[Task]:
        with self.lock:
            return [self.tasks[i] for i in reversed(self.order)]

    def cancel(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task is None:
            return False
        task.cancel.set()
        if task.status == "queued":
            task.status = "cancelled"
            task.finished = time.time()
            task.emit({"type": "end", "status": "cancelled"})
            self._save_history()
        return True

    def delete(self, task_id: str) -> bool:
        """删除一条已结束的历史记录（不动磁盘上的导出产物）。"""
        task = self.tasks.get(task_id)
        if task is None or task.status in ("queued", "running"):
            return False
        with self.lock:
            self.tasks.pop(task_id, None)
            self.order = [i for i in self.order if i != task_id]
        self._save_history()
        return True

    def clear_finished(self) -> int:
        with self.lock:
            gone = [i for i in self.order if self.tasks[i].status not in ("queued", "running")]
            for i in gone:
                self.tasks.pop(i, None)
            self.order = [i for i in self.order if i in self.tasks]
        self._save_history()
        return len(gone)

    def _run(self) -> None:
        while True:
            tid = self.queue.get()
            task = self.tasks.get(tid)
            if task is None or task.status == "cancelled":
                continue
            task.status = "running"
            task.started = time.time()
            task.emit({"type": "start", "total": task.total})
            try:
                self._execute(task)
                task.status = "cancelled" if task.cancel.is_set() else "done"
            except Exception as exc:                  # run_batch 不应抛异常，这里兜底
                task.status = "failed"
                task.error = str(exc)
            task.current = []
            task.finished = time.time()
            task.emit({"type": "end", "status": task.status, "error": task.error,
                       "report_path": task.report_path})
            task.targets = []                          # 释放内存
            self._save_history()

    def _execute(self, task: Task) -> None:
        opts = Options(audio=task.options["audio"],
                       audio_format=task.options["audio_format"],
                       container=task.options["container"],
                       verify=task.options["verify"],
                       jobs=task.options["jobs"])
        sizes = {t.rel_video: t.size for t in task.targets}
        pending = [t.rel_video for t in task.targets]
        task.current = pending[:opts.jobs]

        def on_result(r: Result) -> None:
            task.results.append({
                "rel": r.rel_video, "status": r.status, "msg": r.msg,
                "output": r.output, "seconds": round(r.seconds, 2),
                "method": r.method, "notes": list(r.notes),
                "size": sizes.get(r.rel_video, 0),
            })

        def progress(rel: str, status: str) -> None:
            task.done += 1
            if status in ("ok", "skip", "fail", "cancelled"):
                setattr(task, status, getattr(task, status) + 1)
            try:
                pending.remove(rel)
            except ValueError:
                pass
            task.current = pending[:opts.jobs]
            task.emit({"type": "progress", "rel": rel, "status": status,
                       "done": task.done, "total": task.total})

        report = export_mod.run_batch(task.targets, opts, Path(task.out_dir),
                                      task.ffmpeg, progress=progress, cancel=task.cancel,
                                      on_result=on_result)
        task.report_path = str(report["report_path"])
        task.emit({"type": "report", "path": task.report_path})
