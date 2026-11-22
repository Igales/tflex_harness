from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from uuid import uuid4

from tflex_bridge_read import encode
from tflex_model_operations import ModelOperations, checked_model_path


class ModelOperationsTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "states").mkdir()
        self.sid, self.doc, self.job, self.plan = (str(uuid4()) for _ in range(4))
        self.bridge = Mock()
        self.bridge._sessions.return_value = [(self.root, {"session_id": self.sid, "pid": "123"})]
        self.ops = ModelOperations(self.bridge, self.root)
        self.bridge._await_result.side_effect = lambda *_: {
            "status": "prepared", "plan_id": self.plan,
            "plan_sha256": sha256(encode(self.bridge._submit.call_args.args[4]).encode()).hexdigest(),
        }

    def submit(self, action, args, doc_id=None):
        return self.ops.submit(self.sid, self.doc if doc_id is None else doc_id,
                               self.job, action, args)

    def test_edit_and_bind_pass_exact_contract(self):
        self.assertEqual(self.submit("set_variable", {"name": "h", "numeric_literal": "20"})["status"],
                         "submitted_review_required")
        calls = self.bridge._submit.call_args_list
        self.assertEqual([v.args[3] for v in calls], ["prepare", "commit"])
        self.assertEqual(calls[0].args[4], {"action": "set_variable", "doc_id": self.doc,
                                          "arg.name": "h", "arg.expression": "20"})
        self.assertEqual(calls[1].args[2], self.job)
        self.job = str(uuid4())
        self.assertTrue(self.submit("bind_parameter", {"object_id": "3", "property": "Length",
                                                       "variable": "h"})["ok"])

    def test_open_save_and_export_use_workspace_without_overwrite(self):
        (self.root / "part.grb").touch()
        self.assertTrue(self.submit("open_grb", {"file_name": "part.grb"}, doc_id="")["ok"])
        self.assertNotIn("doc_id", self.bridge._submit.call_args_list[0].args[4])
        self.job = str(uuid4())
        self.assertTrue(self.submit("save_copy", {"file_name": "Новое имя.grb"})["ok"])
        self.job = str(uuid4())
        self.assertTrue(self.submit("export_step", {"file_name": "Новое имя.step"})["ok"])
        self.job = str(uuid4())
        self.assertFalse(self.submit("save_copy", {"file_name": "part.grb"})["ok"])

    def test_paths_and_unrestricted_commands_denied(self):
        for name in ("../part.grb", "C:\\part.grb", "x:secret.grb", "NUL.grb", "COM¹.grb",
                     ".grb", "space .grb", "foo.exe"):
            with self.assertRaises(ValueError):
                checked_model_path(self.root, name, ".grb", False)
        for action, args in (("run_code", {"source": "code"}), ("save", {}),
                             ("set_variable", {"name": "h", "numeric_literal": "20 mm"}),
                             ("regenerate", {"unexpected": "true"})):
            self.assertFalse(self.submit(action, args)["ok"])
        self.bridge._submit.assert_not_called()

    def test_job_id_retry_does_not_send_another_mutation(self):
        self.assertTrue(self.submit("regenerate", {})["ok"])
        self.bridge._result.side_effect = FileNotFoundError
        self.assertEqual(self.submit("regenerate", {})["status"], "no_final_result_do_not_repeat")
        self.assertEqual(self.submit("activate", {})["status"], "job_id_conflict")
        self.assertEqual(self.bridge._submit.call_count, 2)

    def test_altered_digest_and_timeout_never_commit(self):
        self.bridge._await_result.side_effect = None
        self.bridge._await_result.return_value = {
            "status": "prepared", "plan_id": self.plan, "plan_sha256": "0" * 64}
        self.assertEqual(self.submit("regenerate", {})["status"], "invalid_plan_no_edit_submitted")
        self.job = str(uuid4())
        self.bridge._await_result.return_value = {"status": "read_timeout"}
        self.assertEqual(self.submit("regenerate", {})["status"], "prepare_failed_no_edit_submitted")
        self.assertEqual([v.args[3] for v in self.bridge._submit.call_args_list], ["prepare", "prepare"])

    def test_finished_job_requires_observed_rebuild_and_never_claims_geometry(self):
        self.submit("regenerate", {})
        self.bridge._result.return_value = {"status": "ok", "action": "regenerate"}
        self.assertFalse(self.ops.status(self.sid, self.job)["ok"])
        self.bridge._result.return_value["model_edit_completed"] = "true"
        result = self.ops.status(self.sid, self.job)
        self.assertTrue(result["rebuilt"])
        self.assertFalse(result["geometry_verified"])
        self.assertFalse(result["original_saved"])
