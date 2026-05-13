from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import workspace


class TestDescribeProjectTree(unittest.TestCase):
    def test_lists_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.txt").write_text("x", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.py").write_text("y", encoding="utf-8")
            text = workspace.describe_project_tree(root, max_files=50, max_depth=5)
            self.assertIn("a.txt", text)
            self.assertIn("sub/", text)
            self.assertIn("b.py", text)


class TestWriteFilesFromAgentOutput(unittest.TestCase):
    def test_python_path_fence(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            md = "```python src/hello.py\nprint('hi')\n```"
            written, errs = workspace.write_files_from_agent_output(root, md)
            self.assertFalse(errs)
            self.assertEqual(written, ["src/hello.py"])
            p = root / "src" / "hello.py"
            self.assertTrue(p.is_file())
            self.assertIn("print", p.read_text(encoding="utf-8"))

    def test_file_marker(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            md = "```python\n# file: lib/x.py\nx = 1\n```"
            written, errs = workspace.write_files_from_agent_output(root, md)
            self.assertFalse(errs)
            self.assertEqual(written, ["lib/x.py"])
            self.assertEqual((root / "lib" / "x.py").read_text(encoding="utf-8").strip(), "x = 1")

    def test_resolve_safe_rejects_dotdot(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(ValueError):
                workspace.resolve_safe_path(root, "x/../../outside")

    def test_skips_unsafe_marker_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            md = "```python\n# file: ../evil.txt\noops\n```"
            written, errs = workspace.write_files_from_agent_output(root, md)
            self.assertEqual(written, [])
            self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
