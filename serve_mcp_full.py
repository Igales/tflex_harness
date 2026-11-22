from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
REFERENCES = ["TFlexAPI", "TFlexAPI3D", "TFlexAPIData", "TFlexCommandAPI"]
LOCK = threading.Lock()


def child_environment():
    env = {
        k: v for k, v in os.environ.items()
        if not any(word in k.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        and not k.upper().startswith("PYTHON")
    }
    env["PYTHONPATH"] = str(SRC)
    return env


def read_live_versions(program_dir):
    script = ROOT / "Read-TFlexVersions.ps1"
    shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    try:
        if not script.is_file():
            raise FileNotFoundError("Read-TFlexVersions.ps1 is missing beside the server")
        proc = subprocess.run(
            [str(shell), "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-ProgramDir", str(program_dir)],
            env=child_environment(), capture_output=True, text=True,
            encoding="utf-8-sig", errors="replace", timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError("Version probe failed: " + proc.stderr[-4000:])
        result = json.loads(proc.stdout)
        if not isinstance(result, dict) or not isinstance(result.get("files"), list):
            raise ValueError("Invalid version probe response")
        return result
    except Exception as exc:
        return {"ok": False, "files": [], "error": str(exc)}


def worker():
    request = json.load(sys.stdin)
    from tflex_harness.config import load_config
    from tflex_harness.runner import run_csharp_snippet
    cfg = load_config(ROOT)
    missing = [name + ".dll" for name in REFERENCES
               if not (cfg.tflex_program_dir / (name + ".dll")).is_file()]
    if missing:
        result = {"ok": False, "stage": "environment", "missing_references": missing}
    else:
        result = run_csharp_snippet(
            code=request["code"], mode=request["mode"],
            timeout_sec=request["timeout_sec"], references=REFERENCES,
            helpers=None, environment=None,
            artifact_prefix="mcp_" + request["mode"], config=cfg,
        )
    result["geometry_verified"] = False
    result["cad_session_verified"] = False
    result["execution_kind"] = "standalone_exe"
    json.dump(result, sys.stdout, ensure_ascii=True)


def execute(code, mode, timeout_sec):
    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "stage": "input", "error": "Empty C# source"}
    if len(code.encode("utf-8")) > 131072:
        return {"ok": False, "stage": "input", "error": "Source exceeds 128 KiB"}
    if type(timeout_sec) is not int or not 1 <= timeout_sec <= 120:
        return {"ok": False, "stage": "input", "error": "timeout_sec must be 1..120"}
    if mode not in ("compile_only", "run"):
        return {"ok": False, "stage": "input", "error": "Invalid mode"}
    if mode == "run" and os.environ.get("TFLEX_MCP_ALLOW_RUN") != "1":
        return {"ok": False, "stage": "permission", "error": "Run disabled locally"}
    if not LOCK.acquire(blocking=False):
        return {"ok": False, "stage": "busy", "error": "Another request is active"}
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            cwd=ROOT, env=child_environment(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        payload = json.dumps({"code": code, "mode": mode, "timeout_sec": timeout_sec})
        try:
            stdout, stderr = proc.communicate(payload, timeout=2 * timeout_sec + 20)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, timeout=15,
                )
            if proc.poll() is None:
                proc.kill()
            return {"ok": False, "stage": "worker_timeout",
                    "geometry_verified": False,
                    "error": "Worker timed out; CAD state must be inspected"}
        if proc.returncode != 0:
            return {"ok": False, "stage": "worker", "exit_code": proc.returncode,
                    "stderr": stderr[-12000:]}
        result = json.loads(stdout)
        if not isinstance(result, dict):
            raise ValueError("Worker returned a non-object response")
        return result
    except Exception as exc:
        return {"ok": False, "stage": "server", "error": str(exc)}
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
        LOCK.release()


def main():
    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from tflex_harness.config import load_config
    from tflex_harness.docs_search import DocsSearch
    import serve_mcp_readonly as legacy
    from tflex_bridge_read import BridgeReader

    key = os.environ.get("TFLEX_MCP_API_KEY", "")
    if len(key) < 32 or not key.isascii() or any(c.isspace() for c in key):
        raise SystemExit("Missing or invalid TFLEX_MCP_API_KEY")
    if not (SRC / "tflex_harness" / "runner.py").is_file():
        raise SystemExit("Local harness source is missing")

    server = FastMCP("tflex-full")
    docs = DocsSearch()
    cfg = load_config(ROOT)
    bridge = BridgeReader()
    bridge_reads_enabled = os.environ.get("TFLEX_MCP_ALLOW_BRIDGE_READ") == "1"

    @server.tool()
    def get_bridge_status() -> dict:
        """Discover local T-FLEX GUI sessions by process identity. No CAD command or file write."""
        if not bridge_reads_enabled:
            return {"ok": False, "status": "bridge_reads_disabled"}
        return bridge.status()

    @server.tool()
    def get_document_snapshot(session_id: str = "", doc_id: str = "", include: str = "summary",
                              offset: int = 0, limit: int = 40) -> dict:
        """Inspect T-FLEX GUI documents. Summary lists documents; variables and operations require
        session_id and doc_id from summary. Writes bridge request/audit files; never edits the
        CAD document, saves GRB, compiles C#, or starts an external CAD process.
        Pages are independent, not a single atomic geometry snapshot.
        """
        if not bridge_reads_enabled:
            return {"ok": False, "status": "bridge_reads_disabled"}
        return bridge.snapshot(session_id, doc_id, include, offset, limit)
        
    @server.tool()
    def search_tflex_docs(query: str, scope: str = "all", limit: int = 5) -> dict:
        """Search API reference (includes 17.1.30.0). User installed CAD 17.1.50.0;
        compatibility still requires compilation and live checks. Does not run CAD.
        """
        if scope not in ("symbols", "types", "chm", "all"):
            return {"ok": False, "error": "Invalid scope"}
        return docs.search(query=query, scope=scope, limit=max(1, min(limit, 20)))

    @server.tool()
    def read_verified_macro(macro_id: str) -> dict:
        """Read saved example and README. Does not compile or execute it."""
        try:
            folder = legacy.get_macro_dir(macro_id)
            return {"ok": True, "macro_id": macro_id, "language": "csharp",
                    "code": legacy.read_allowed_file(folder, "macro.cs", legacy.MAX_CODE_BYTES),
                    "readme": legacy.read_allowed_file(folder, "README.md", legacy.MAX_README_BYTES, optional=True)}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    @server.tool()
    def list_verified_macros() -> dict:
        """List saved examples. Names do not imply independent live verification."""
        items = []
        if legacy.MACROS_DIR.is_dir():
            for entry in sorted(legacy.MACROS_DIR.iterdir(), key=lambda p: p.name.lower()):
                if not legacy.MACRO_ID_PATTERN.fullmatch(entry.name):
                    continue
                item = read_verified_macro(entry.name)
                if item.get("ok"):
                    items.append({"macro_id": entry.name,
                                  "description": item["readme"][:2000],
                                  "has_readme": bool(item["readme"]),
                                  "code_lines": len(item["code"].splitlines())})
                else:
                    items.append({"macro_id": entry.name, "error": item.get("error")})
        return {"ok": True, "macros": items, "count": len(items)}

    @server.tool()
    def get_tflex_environment() -> dict:
        """Read live EXE/DLL versions, hashes, paths and module provenance.
        Reads metadata using PowerShell; never builds or starts CAD.
        Reports on-disk files, not DLLs loaded into an existing CAD process.
        """
        import tflex_harness.config as config_module
        import tflex_harness.runner as runner_module
        versions = read_live_versions(cfg.tflex_program_dir)
        by_name = {item["name"]: item for item in versions.get("files", [])}
        return {"repo_dir": str(ROOT), "python": sys.executable,
                "config_module": config_module.__file__,
                "runner_module": runner_module.__file__,
                "program_dir": str(cfg.tflex_program_dir),
                "docs_dir": str(cfg.docs_dir),
                "live_versions": versions,
                "dlls": [by_name.get(name + ".dll", {
                    "name": name + ".dll",
                    "path": str(cfg.tflex_program_dir / (name + ".dll")),
                    "exists": (cfg.tflex_program_dir / (name + ".dll")).is_file(),
                    "read_ok": False, "error": "Live version probe unavailable"})
                    for name in REFERENCES],
                "run_enabled": os.environ.get("TFLEX_MCP_ALLOW_RUN") == "1",
                "geometry_verified": False}

    @server.tool()
    def compile_csharp_tflex(code: str, timeout_sec: int = 30) -> dict:
        """Compile a complete x64 C# program with Main against installed API DLLs.
        Writes build artifacts. Does not execute the compiled program or CAD.
        """
        return execute(code, "compile_only", timeout_sec)

    @server.tool()
    def run_csharp_tflex(code: str, timeout_sec: int = 30) -> dict:
        """Compile and execute arbitrary C# as this Windows user. NOT sandboxed.
        May modify files or CAD documents. Requires explicit user approval.
        Requires local TFLEX_MCP_ALLOW_RUN=1. Exit zero does not verify geometry.
        """
        return execute(code, "run", timeout_sec)

    uvicorn.run(legacy.RequireApiKey(server.streamable_http_app(), key),
                host="127.0.0.1", port=8000, access_log=False)


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        worker()
    else:
        main()
