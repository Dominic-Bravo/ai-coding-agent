from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import workspace


class TestCollectProjectMarkdownDocs(unittest.TestCase):
    def test_reads_and_orders_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "z_note.md").write_text("# Z\n- [ ] last\n", encoding="utf-8")
            (root / "README.md").write_text("# Read\n- [ ] first task\n", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "bad.md").write_text("x", encoding="utf-8")
            text, n = workspace.collect_project_markdown_docs(
                root, max_files=10, max_total_chars=50_000
            )
            self.assertEqual(n, 2)
            self.assertIn("README.md", text)
            self.assertIn("z_note.md", text)
            self.assertNotIn("node_modules", text)
            self.assertLess(text.index("README.md"), text.index("z_note.md"))


class TestExtractTodoLinesFromMarkdown(unittest.TestCase):
    def test_pulls_list_items(self):
        bundle = "# TODO\n\n- [ ] One thing\n* Two thing\n3. Three thing\n"
        lines = workspace.extract_todo_lines_from_markdown(bundle, max_lines=10)
        self.assertEqual(lines, ["One thing", "Two thing", "Three thing"])


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
