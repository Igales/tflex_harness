from datetime import datetime
from pathlib import Path
import tempfile
import threading
import time
import unittest
from uuid import uuid4

from tflex_bridge_read import BridgeReader, PROTOCOL, decode, encode


class BridgeReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stamp = "2026-11-22T10:00:00.1234567Z"
        self.live = datetime.fromisoformat(self.stamp).timestamp()
        self.starts = {123: self.live}
        self.reader = BridgeReader(self.root, self.starts.get)
        self.sid, self.dir = self.session(123)

    def session(self, pid):
        sid = str(uuid4())
        directory = self.root / str(pid) / sid
        (directory / "inbox").mkdir(parents=True)
        (directory / "results").mkdir()
        (directory / "ready.txt").write_text(encode({
            "protocol": PROTOCOL, "status": "ready", "pid": str(pid),
            "session_id": sid, "process_started_utc": self.stamp,
        }), encoding="utf-8")
        return sid, directory

    def reply(self, data):
        def run():
            end = time.monotonic() + 1
            while time.monotonic() < end:
                files = list((self.dir / "inbox").glob("*.req"))
                if files:
                    req = decode(files[0])
                    self.request = req
                    response = {k: req[k] for k in ("protocol", "pid", "session_id", "request_id")}
                    response.update(status="ok", utc=self.stamp, **data)
                    target = self.dir / "results" / (req["request_id"] + ".txt")
                    pending = target.with_suffix(".tmp")
                    pending.write_text(encode(response), encoding="utf-8")
                    pending.rename(target)
                    return
                time.sleep(.005)
        thread = threading.Thread(target=run)
        thread.start()
        self.addCleanup(thread.join)

    def test_discovery_rejects_dead_and_reused_pid_without_writing_files(self):
        self.session(124)
        self.session(125)
        self.starts[125] = self.live + 100
        self.assertEqual([s["session_id"] for s in self.reader.status()["sessions"]], [self.sid])
        self.assertEqual(list(self.root.glob("*/*/inbox/*")), [])

    def test_ambiguous_session_never_sends_request(self):
        self.session(124)
        self.starts[124] = self.live
        self.assertEqual(self.reader.snapshot()["status"], "ambiguous_session")
        self.assertEqual(list(self.root.glob("*/*/inbox/*")), [])

    def test_summary_names_without_full_paths(self):
        doc = str(uuid4())
        second = str(uuid4())
        self.reply({"items.0.doc_id": doc, "items.0.path": r"C:\Private\Деталь.grb",
                    "items.1.doc_id": second, "items.1.path": ""})
        result = self.reader.snapshot()
        self.assertTrue(result["ok"])
        self.assertEqual(result["items"][0], {"doc_id": doc, "file_name": "Деталь.grb"})
        self.assertEqual(result["items"][1]["doc_id"], second)
        self.assertEqual(self.request["command"], "list_documents")
        self.assertRegex(self.request["created_utc"], r"\.\d{7}\+00:00$")

    def test_variables_target_and_pagination(self):
        doc = str(uuid4())
        self.reply({"doc_id": doc, "items.0.name": "h", "items.0.expression": "20",
                    "total": "40"})
        result = self.reader.snapshot(self.sid, doc, "variables", offset=2, limit=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["items"], [{"name": "h", "expression": "20"}])
        self.assertEqual(result["total"], 40)
        self.assertEqual(self.request["offset"], "2")
        self.assertEqual(self.request["doc_id"], doc)

    def test_wrong_document_is_rejected(self):
        self.reply({"doc_id": str(uuid4()), "total": "0"})
        self.assertEqual(self.reader.snapshot(self.sid, str(uuid4()), "operations")["status"],
                         "document_target_mismatch")

    def test_unsupported_commands_and_unaddressed_detail_rejected(self):
        for mode in ("commit", "variables", "../operations"):
            self.assertEqual(self.reader.snapshot(include=mode)["status"], "invalid_arguments")
        self.assertEqual(list(self.dir.glob("inbox/*")), [])

    def test_timeout_correlates_existing_request_without_retry(self):
        directory, identity = self.reader._sessions()[0]
        result = self.reader._query(directory, identity, "list_documents", time.monotonic())
        self.assertEqual(result["status"], "read_timeout")
        self.assertEqual(len(list(self.dir.glob("inbox/*.req"))), 1)
        self.assertTrue((self.dir / "inbox" / (result["request_id"] + ".req")).is_file())
