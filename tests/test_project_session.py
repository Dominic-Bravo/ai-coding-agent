from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import project_session


class TestProjectSession(unittest.TestCase):
    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project_session.save_session(
                root,
                user_request="build api",
                plan="# plan",
                dom_summary="ok",
                tasks=["a", "b"],
                artifacts=[{"task": "a", "code": "x", "review": "y"}],
                status="in_progress",
            )
            data = project_session.load_session(root)
            self.assertIsNotNone(data)
            assert data is not None
            self.assertEqual(data["user_request"], "build api")
            self.assertEqual(data["tasks"], ["a", "b"])
            self.assertEqual(len(data["artifacts"]), 1)

    def test_wrong_root_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "proj"
            root.mkdir()
            other = Path(d) / "other"
            other.mkdir()
            wrong = root / ".micro-agent" / "session.json"
            wrong.parent.mkdir(parents=True)
            wrong.write_text(
                json.dumps(
                    {
                        "version": project_session.SESSION_VERSION,
                        "project_root": str(other.resolve()),
                        "updated_at": "x",
                        "status": "in_progress",
                        "user_request": "x",
                        "plan": "p",
                        "dom_summary": "d",
                        "tasks": [],
                        "artifacts": [],
                    }
                ),
                encoding="utf-8",
            )
            self.assertIsNone(project_session.load_session(root))

    def test_clear_session(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project_session.save_session(
                root,
                user_request="x",
                plan="p",
                dom_summary="d",
                tasks=[],
                artifacts=[],
                status="completed",
            )
            project_session.clear_session(root)
            self.assertIsNone(project_session.load_session(root))


if __name__ == "__main__":
    unittest.main()
