"""Bounded read commands for the existing T-FLEX Chat Bridge v2."""
import base64
from datetime import datetime, timezone
import os
from pathlib import Path, PureWindowsPath
import re
import time
from uuid import UUID, uuid4

PROTOCOL = "tflex-bridge-v2"
MAX_RESPONSE = 1024 * 1024


def decode(path):
    with path.open("rb") as f:
        raw = f.read(MAX_RESPONSE + 1)
    if not raw or len(raw) > MAX_RESPONSE:
        raise ValueError("Invalid bridge record size")
    fields = {}
    for line in raw.decode("utf-8").splitlines():
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Za-z0-9_.]+", key) or key in fields:
            raise ValueError("Invalid bridge field")
        fields[key] = base64.b64decode(value, validate=True).decode("utf-8")
    return fields


def encode(fields):
    return "".join(
        f"{key}={base64.b64encode(value.encode('utf-8')).decode('ascii')}\n"
        for key, value in sorted(fields.items())
    )


def canonical_id(value):
    return isinstance(value, str) and str(UUID(value)) == value


def windows_process_start(pid):
    """Return TFlexCad's creation time; no process is started or modified."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes as w

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.CloseHandle.restype = w.BOOL
    k.QueryFullProcessImageNameW.argtypes = [
        w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)
    ]
    k.QueryFullProcessImageNameW.restype = w.BOOL
    ft = ctypes.POINTER(w.FILETIME)
    k.GetProcessTimes.argtypes = [w.HANDLE, ft, ft, ft, ft]
    k.GetProcessTimes.restype = w.BOOL
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        image = ctypes.create_unicode_buffer(32768)
        length = w.DWORD(len(image))
        if not k.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
            return None
        if PureWindowsPath(image.value).name.casefold() != "tflexcad.exe":
            return None
        created, exited, kernel, user = (w.FILETIME() for _ in range(4))
        if not k.GetProcessTimes(handle, *(ctypes.byref(t) for t in (created, exited, kernel, user))):
            return None
        if exited.dwLowDateTime or exited.dwHighDateTime:
            return None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return (ticks - 116444736000000000) / 10_000_000
    finally:
        k.CloseHandle(handle)


def _error(status, **details):
    return {"ok": False, "status": status, **details}


class BridgeReader:
    def __init__(self, root=None, process_start=windows_process_start):
        local = os.environ.get("LOCALAPPDATA")
        self.root = root if root is not None else (
            Path(local) / "TFlexGuiBridge" / "v2" if local else None
        )
        self.process_start = process_start

    def _sessions(self):
        sessions = []
        if self.root is None:
            return sessions
        starts = {}
        for path in sorted(self.root.glob("*/*/ready.txt")):
            pid, sid = path.parent.parent.name, path.parent.name
            try:
                if not re.fullmatch(r"[1-9][0-9]{0,9}", pid) or int(pid) > 0xFFFFFFFF:
                    continue
                if not canonical_id(sid):
                    continue
                d = decode(path)
                if (d.get("protocol"), d.get("status"), d.get("pid"), d.get("session_id")) != (
                    PROTOCOL, "ready", pid, sid
                ):
                    continue
                started = datetime.fromisoformat(d["process_started_utc"])
                if started.tzinfo is None:
                    continue
                if pid not in starts:
                    starts[pid] = self.process_start(int(pid))
                live = starts[pid]
                if live is None or abs(started.timestamp() - live) > 0.1:
                    continue
                sessions.append((path.parent, {"pid": pid, "session_id": sid,
                                              "process_started_utc": d["process_started_utc"]}))
            except (OSError, ValueError, KeyError, OverflowError):
                continue
        return sessions

    def status(self):
        sessions = [identity for _, identity in self._sessions()]
        return {"ok": True, "status": "discovered" if sessions else "no_live_session",
                "sessions": sessions}

    def _query(self, directory, session, command, deadline, **arguments):
        argument_sets = {
            "list_documents": set(),
            "variables": {"doc_id", "offset", "limit"},
            "operations": {"doc_id", "offset", "limit"},
            "selection": {"doc_id", "offset", "limit"},
            "inspect": {"doc_id"},
            "object_info": {"doc_id", "object_id"},
            "measure_property": {"doc_id", "object_id", "property"},
        }
        if command not in argument_sets or set(arguments) != argument_sets[command]:
            raise ValueError("Unsupported bridge read")
        rid = str(uuid4())
        self._submit(directory, session, rid, command, arguments)
        return self._await_result(directory, session, rid, deadline, "ok")

    def _submit(self, directory, session, rid, command, arguments):
        fields = {k: str(v) for k, v in arguments.items()}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0+00:00"
        fields.update(protocol=PROTOCOL, pid=session["pid"], session_id=session["session_id"],
                      request_id=rid, created_utc=now, command=command)
        temporary = directory / "inbox" / (rid + ".tmp")
        stream = temporary.open("x", encoding="utf-8", newline="\n")
        try:
            with stream as f:
                f.write(encode(fields))
            temporary.rename(temporary.with_suffix(".req"))
        finally:
            temporary.unlink(missing_ok=True)

    def _result(self, directory, session, rid):
        result = decode(directory / "results" / (rid + ".txt"))
        target = {"protocol": PROTOCOL, "pid": session["pid"],
                  "session_id": session["session_id"], "request_id": rid}
        if any(result.get(k) != v for k, v in target.items()):
            return _error("response_target_mismatch", request_id=rid)
        return result

    def _await_result(self, directory, session, rid, deadline, expected):
        while True:
            try:
                result = self._result(directory, session, rid)
                if result.get("ok") is False:
                    return result
                if result.get("status") != expected:
                    return _error("cad_read_failed", request_id=rid, error_type=result.get("error_type"))
                return result
            except FileNotFoundError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return _error("read_timeout", request_id=rid)
                time.sleep(min(remaining, 0.04))

    def snapshot(self, session_id="", doc_id="", include="summary", offset=0, limit=40):
        """One fresh read: document summaries, or a page of variables/operations."""
        session_id = session_id or ""
        try:
            if ((session_id and not canonical_id(session_id)) or
                    (doc_id and not canonical_id(doc_id)) or
                    include not in ("summary", "variables", "operations", "selection", "inspect") or
                    type(offset) is not int or not 0 <= offset <= 1_000_000 or
                    type(limit) is not int or not 1 <= limit <= 100 or
                    (include != "summary" and not (session_id and doc_id))):
                return _error("invalid_arguments")
            found = [(p, s) for p, s in self._sessions()
                     if not session_id or s["session_id"] == session_id]
            if len(found) != 1:
                return _error("ambiguous_session" if found else "no_live_session",
                              sessions=[s for _, s in found])
            directory, session = found[0]
            if include == "summary":
                result = self._query(directory, session, "list_documents", time.monotonic() + 4)
            elif include == "inspect":
                result = self._query(directory, session, include, time.monotonic() + 4, doc_id=doc_id)
            else:
                result = self._query(directory, session, include, time.monotonic() + 4,
                                     doc_id=doc_id, offset=offset, limit=limit)
            if result.get("status") != "ok":
                return result
            if include != "summary" and result.get("doc_id") != doc_id:
                return _error("document_target_mismatch", request_id=result["request_id"])
            if include == "inspect":
                return {"ok": True, "status": "ok", **session, "doc_id": doc_id,
                        "captured_utc": result["utc"], "request_id": result["request_id"],
                        **{key: result[key] for key in ("operations", "variables", "snapshot",
                           "snapshot_scope", "changed", "read_only", "command_running")}}
            items, document = {}, {}
            for key, value in result.items():
                m = re.fullmatch(r"items\.([0-9]+)\.(\w+)", key)
                if m:
                    key = m[2]
                    if key == "path":
                        items.setdefault(int(m[1]), {})["file_name"] = PureWindowsPath(value).name
                    else:
                        items.setdefault(int(m[1]), {})[key] = value
                elif key in ("doc_id", "changed", "read_only", "active", "command_running"):
                    document[key] = value
            page = [items[i] for i in sorted(items)]
            if include == "summary" and doc_id:
                page = [item for item in page if item.get("doc_id") == doc_id]
                if not page:
                    return _error("document_not_found", request_id=result["request_id"])
            return {"ok": True, "status": "ok", **session, "request_id": result["request_id"],
                    "captured_utc": result["utc"], "kind": include, "document": document,
                    "items": page, "returned": len(page),
                    "total": len(page) if include == "summary" else int(result["total"])}
        except (OSError, ValueError, KeyError, OverflowError):
            return _error("invalid_or_unavailable_bridge_record")

    def object_details(self, session_id, doc_id, object_id, property_name=""):
        try:
            if (not canonical_id(session_id) or not canonical_id(doc_id) or
                    not re.fullmatch(r"[0-9]{1,10}", object_id) or
                    int(object_id) > 0xffffffff or
                    (property_name and not re.fullmatch(r"[^\W\d]\w{0,95}", property_name))):
                return _error("invalid_arguments")
            found = [(p, s) for p, s in self._sessions() if s["session_id"] == session_id]
            if len(found) != 1:
                return _error("session_unavailable")
            path, identity = found[0]
            args = {"doc_id": doc_id, "object_id": object_id}
            if property_name:
                args["property"] = property_name
            result = self._query(path, identity, "measure_property" if property_name else
                                 "object_info", time.monotonic() + 4, **args)
            if result.get("status") != "ok":
                return result
            if result.get("doc_id") != doc_id:
                return _error("document_target_mismatch", request_id=result["request_id"])
            fields = {k: v for k, v in result.items() if k.startswith("value.") or k in
                      ("object_type", "object_name", "property_schema", "raw_value",
                       "measurement_kind", "request_id", "utc")}
            return {"ok": True, "status": "ok", "doc_id": doc_id, "object_id": object_id,
                    "property_name": property_name, "geometry_verified": False, **fields}
        except (OSError, ValueError, KeyError):
            return _error("invalid_or_unavailable_bridge_record")
