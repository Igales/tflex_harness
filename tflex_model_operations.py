"""Bounded model-operation contract for the GUI bridge."""
from pathlib import Path
import re
import time
from uuid import uuid4
from hashlib import sha256

from tflex_bridge_read import _error, canonical_id, decode, encode

_NAME = r"[^\W\d]\w{0,63}"
_LITERAL = r"[+-]?[0-9]+(?:\.[0-9]+)?"
_FILE_STEM = r"[\w -]{1,100}"
_DEVICE = re.compile(r"(?i:con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])")
_PATHS = {"open_grb": (".grb", True), "save_copy": (".grb", False),
          "export_step": (".step", False)}
_NO_ARGS = frozenset(("activate", "show_3d", "regenerate", "close"))
_EDITS = frozenset(("set_variable", "bind_parameter", "regenerate"))
GUI_ACTIONS = sorted(_NO_ARGS | _PATHS.keys() | _EDITS)


def checked_model_path(root, file_name, suffix, existing):
    stem, ext = file_name[:-len(suffix)], file_name[-len(suffix):]
    if (ext.lower() != suffix or not re.fullmatch(_FILE_STEM, stem) or
            stem != stem.strip() or _DEVICE.fullmatch(stem)):
        raise ValueError("Invalid model file name")
    directory = Path(root).resolve(strict=True)
    requested = directory / file_name
    target = requested.resolve()
    if requested != target or target.parent != directory:
        raise ValueError("Model path cannot be redirected")
    if existing and not target.is_file():
        raise ValueError("Input model not found in workspace")
    if not existing and target.exists():
        raise ValueError("Output already exists; choose a new name")
    return str(target)


class ModelOperations:
    def __init__(self, bridge, workspace):
        self.bridge = bridge
        self.workspace = workspace

    def _identity(self, session_id):
        choices = [(p, s) for p, s in self.bridge._sessions() if s["session_id"] == session_id]
        return choices[0] if len(choices) == 1 else (None, None)

    def _arguments(self, action, doc_id, args, resolve_paths):
        if type(args) is not dict or any(type(v) is not str for v in args.values()):
            raise ValueError("Expected a dictionary of strings")
        out = {"action": action}
        if action == "open_grb":
            if doc_id:
                raise ValueError("Opening a file does not take a target document")
        elif canonical_id(doc_id):
            out["doc_id"] = doc_id
        else:
            raise ValueError("Document identity required")
        if action in _PATHS and set(args) == {"file_name"}:
            if resolve_paths:
                out["arg.path"] = checked_model_path(self.workspace, args["file_name"],
                                                     *_PATHS[action])
        elif action in _NO_ARGS and not args:
            pass
        elif (action == "set_variable" and set(args) == {"name", "numeric_literal"} and
              re.fullmatch(_NAME, args["name"]) and len(args["numeric_literal"]) <= 64 and
              re.fullmatch(_LITERAL, args["numeric_literal"])):
            out.update({"arg.name": args["name"], "arg.expression": args["numeric_literal"]})
        elif (action == "bind_parameter" and set(args) == {"object_id", "property", "variable"} and
              re.fullmatch(r"[0-9]{1,10}", args["object_id"]) and
              int(args["object_id"]) <= 0xFFFFFFFF and re.fullmatch(_NAME, args["property"]) and
              re.fullmatch(_NAME, args["variable"])):
            out.update({"arg." + k: v for k, v in args.items()})
        else:
            raise ValueError("Operation not allowed or invalid arguments")
        return out

    def submit(self, session_id, doc_id, job_id, action, arguments):
        try:
            if not canonical_id(session_id) or not canonical_id(job_id):
                return _error("invalid_session_or_job_id")
            directory, identity = self._identity(session_id)
            if directory is None:
                return _error("session_unavailable")
            self._arguments(action, doc_id, arguments, False)
            metadata = {"doc_id": doc_id, "job_id": job_id, "session_id": session_id,
                        "action": action, **{"input." + k: v for k, v in arguments.items()}}
            record = directory / "states" / ("mcp-model-" + job_id + ".txt")
            if record.exists():
                return (self.status(session_id, job_id) if decode(record) == metadata
                        else _error("job_id_conflict", job_id=job_id))
            params = self._arguments(action, doc_id, arguments, True)
            try:
                with record.open("x", encoding="utf-8", newline="\n") as f:
                    f.write(encode(metadata))
            except FileExistsError:
                return (self.status(session_id, job_id) if decode(record) == metadata
                        else _error("job_id_conflict", job_id=job_id))
            prepare_id = str(uuid4())
            self.bridge._submit(directory, identity, prepare_id, "prepare", params)
            plan = self.bridge._await_result(directory, identity, prepare_id,
                                             time.monotonic() + 4, "prepared")
            if plan.get("status") != "prepared":
                return _error("prepare_failed_no_edit_submitted", job_id=job_id,
                              detail=plan.get("status"), error_type=plan.get("error_type"))
            digest = sha256(encode(params).encode("utf-8")).hexdigest()
            if not canonical_id(plan["plan_id"]) or plan.get("plan_sha256") != digest:
                return _error("invalid_plan_no_edit_submitted", job_id=job_id)
            self.bridge._submit(directory, identity, job_id, "commit",
                                {"plan_id": plan["plan_id"], "plan_sha256": digest})
            return {"ok": True, "status": "submitted_review_required", "job_id": job_id,
                    "session_id": session_id, "action": action}
        except ValueError as exc:
            return _error("invalid_operation_or_job_record", job_id=job_id, detail=str(exc))
        except (OSError, KeyError, TypeError, OverflowError):
            return _error("check_job_do_not_repeat", job_id=job_id)

    def status(self, session_id, job_id):
        try:
            if not canonical_id(session_id) or not canonical_id(job_id):
                return _error("invalid_session_or_job_id")
            directory, identity = self._identity(session_id)
            if directory is None:
                return _error("session_unavailable_outcome_unknown", job_id=job_id)
            record = directory / "states" / ("mcp-model-" + job_id + ".txt")
            if not record.is_file():
                return _error("unknown_job", job_id=job_id)
            metadata = decode(record)
            action = metadata["action"]
            try:
                response = self.bridge._result(directory, identity, job_id)
            except FileNotFoundError:
                return {"ok": True, "status": "no_final_result_do_not_repeat",
                        "action": action, "job_id": job_id}
            passed = (response.get("status") == "ok" and response.get("action") == action and
                      (action not in _EDITS or response.get("model_edit_completed") == "true") and
                      (action != "close" or response.get("closed") == "True"))
            if not passed:
                return _error("operation_not_confirmed_check_document", action=action,
                              job_id=job_id, error_type=response.get("error_type"))
            return {"ok": True, "status": "completed", "action": action, "job_id": job_id,
                    "document_id": response.get("doc_id") or metadata.get("doc_id"),
                    "rebuilt": action in _EDITS,
                    "output_file": metadata.get("input.file_name") if action in
                    ("save_copy", "export_step") else None, "original_saved": False,
                    "geometry_verified": False}
        except (OSError, ValueError, KeyError):
            return _error("invalid_or_unavailable_job_record", job_id=job_id)
