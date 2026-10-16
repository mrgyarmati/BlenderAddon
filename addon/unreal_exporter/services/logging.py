"""Structured export log (pure, no bpy).

Records go to a human-readable text log and a JSON-lines log beside the
manifest. Absolute paths are redacted to export-root-relative form unless debug
mode is on, so logs can be shared without leaking local directory layouts.
"""

from __future__ import annotations

import json
import os
import re
import time

from ..domain import naming

_ABS_WINDOWS = re.compile(r"[A-Za-z]:[\\/][^\s'\"]*")
_ABS_POSIX = re.compile(r"(?<![\w.])/(?:[^\s'\"/]+/)+[^\s'\"]*")


class ExportLog:
    def __init__(self, root: str, debug: bool = False, clock=time.time):
        self.root = root
        self.debug = debug
        self._clock = clock
        self._start = clock()
        self.records = []

    def _redact(self, text: str) -> str:
        if self.debug or not isinstance(text, str):
            return text

        def sub(match):
            return naming.redact_path(match.group(0), self.root, debug=False)

        text = _ABS_WINDOWS.sub(sub, text)
        return _ABS_POSIX.sub(sub, text)

    def add(self, level: str, event: str, message: str = "", **fields) -> dict:
        record = {
            "t": round(self._clock() - self._start, 4),
            "level": level,
            "event": event,
            "message": self._redact(message),
        }
        for key, value in sorted(fields.items()):
            record[key] = self._redact(value) if isinstance(value, str) else value
        self.records.append(record)
        return record

    def info(self, event, message="", **fields):
        return self.add("INFO", event, message, **fields)

    def warning(self, event, message="", **fields):
        return self.add("WARNING", event, message, **fields)

    def error(self, event, message="", **fields):
        return self.add("ERROR", event, message, **fields)

    def text(self) -> str:
        lines = []
        for rec in self.records:
            extra = " ".join("%s=%s" % (k, rec[k]) for k in rec if k not in ("t", "level", "event", "message"))
            lines.append("[%8.3fs] %-7s %-22s %s%s" % (rec["t"], rec["level"], rec["event"], rec["message"],
                                                         (" | " + extra) if extra else ""))
        return "\n".join(lines) + "\n"

    def write(self, text_path: str, json_path: str) -> None:
        os.makedirs(os.path.dirname(text_path) or ".", exist_ok=True)
        with open(text_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(self.text())
        with open(json_path, "w", encoding="utf-8", newline="\n") as handle:
            for rec in self.records:
                handle.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
