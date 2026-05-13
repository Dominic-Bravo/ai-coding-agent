import unittest

import manager


class TestParsePlanTasks(unittest.TestCase):
    def test_bullets_and_numbered(self):
        plan = """
# Plan
- First file: app.py
* Second: utils/helpers.py
1. Add tests
"""
        tasks = manager.parse_plan_tasks(plan)
        self.assertEqual(
            tasks,
            [
                "First file: app.py",
                "Second: utils/helpers.py",
                "Add tests",
            ],
        )

    def test_checkboxes(self):
        plan = "- [ ] Do A\n- [x] Do B"
        tasks = manager.parse_plan_tasks(plan)
        self.assertEqual(tasks, ["Do A", "Do B"])

    def test_respects_max_tasks(self):
        plan = "\n".join(f"- Task {i}" for i in range(20))
        tasks = manager.parse_plan_tasks(plan, max_tasks=3)
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0], "Task 0")

    def test_empty_when_no_list_items(self):
        self.assertEqual(manager.parse_plan_tasks("Just prose\nno bullets."), [])


class TestNeedsAutoFix(unittest.TestCase):
    def test_fix_required(self):
        self.assertTrue(manager.needs_auto_fix("STATUS: FIX REQUIRED"))

    def test_bug_keyword(self):
        self.assertTrue(manager.needs_auto_fix("No critical BUG"))

    def test_clean(self):
        self.assertFalse(manager.needs_auto_fix("Looks good to ship."))


if __name__ == "__main__":
    unittest.main()
