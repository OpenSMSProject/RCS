import json
import os
import threading
import time
from typing import Optional


INFLIGHT_STATES = {"accepted", "sending"}
VALID_STATES = {"accepted", "sending", "sent", "failed", "ambiguous"}


class JobLedger:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._records = self._load()
        changed = False
        for record in self._records.values():
            if record.get("state") in INFLIGHT_STATES:
                record["state"] = "ambiguous"
                record["updated_ns"] = time.time_ns()
                changed = True
        if changed:
            self._save()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(self._records, fh, separators=(",", ":"), sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, self.path)

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            record = self._records.get(job_id)
            return dict(record) if isinstance(record, dict) else None

    def records(self) -> dict:
        with self._lock:
            return {key: dict(value) for key, value in self._records.items()}

    def mark(self, job_id: str, state: str, result: Optional[dict] = None) -> None:
        if not job_id:
            raise ValueError("job_id is required")
        if state not in VALID_STATES:
            raise ValueError("invalid job state")
        with self._lock:
            previous = self._records.get(job_id, {})
            record = {
                "state": state,
                "updated_ns": time.time_ns(),
            }
            if result is not None:
                record["result"] = dict(result)
            elif "result" in previous:
                record["result"] = previous["result"]
            self._records[job_id] = record
            self._save()

    def prune(self, max_entries: int = 500) -> None:
        if max_entries < 0:
            raise ValueError("max_entries must be non-negative")
        with self._lock:
            if len(self._records) <= max_entries:
                return
            newest = sorted(
                self._records.items(),
                key=lambda item: int(item[1].get("updated_ns", 0)),
                reverse=True,
            )[:max_entries]
            self._records = dict(newest)
            self._save()
