import threading
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Job:
    """One long-running task at a time. This is a single-user local tool."""

    name: str = ""
    running: bool = False
    done: int = 0
    total: int = 0
    failed: int = 0
    seq: int = 0
    log: deque[str] = field(default_factory=lambda: deque(maxlen=400))
    summary: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, name: str) -> bool:
        with self.lock:
            if self.running:
                return False
            self.name = name
            self.running = True
            self.done = self.total = self.failed = self.seq = 0
            self.summary = ""
            self.log.clear()
            return True

    def emit(self, line: str) -> None:
        with self.lock:
            self.log.append(line)
            self.seq += 1

    def progress(self, done: int, total: int) -> None:
        with self.lock:
            self.done, self.total = done, total

    def set_failed(self, count: int) -> None:
        with self.lock:
            self.failed = count

    def finish(self, summary: str) -> None:
        with self.lock:
            self.running = False
            self.summary = summary

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "name": self.name,
                "running": self.running,
                "done": self.done,
                "total": self.total,
                "failed": self.failed,
                "summary": self.summary,
                "log": list(self.log),
                "seq": self.seq,
            }


JOB = Job()
