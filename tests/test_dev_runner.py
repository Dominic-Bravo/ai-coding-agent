from __future__ import annotations

import unittest

from dev_runner import validate_dev_command


class TestValidateDevCommand(unittest.TestCase):
    def test_python_m_pytest_ok(self):
        ok, msg = validate_dev_command(["python", "-m", "pytest", "-q"])
        self.assertTrue(ok, msg)

    def test_pytest_direct_ok(self):
        ok, msg = validate_dev_command(["pytest", "tests"])
        self.assertTrue(ok, msg)

    def test_python_c_rejected(self):
        ok, msg = validate_dev_command(["python", "-c", "print(1)"])
        self.assertFalse(ok)
        self.assertIn("-c", msg)

    def test_forbidden_shell_rejected(self):
        ok, msg = validate_dev_command(["powershell", "-Command", "Get-ChildItem"])
        self.assertFalse(ok)

    def test_pipe_rejected(self):
        ok, msg = validate_dev_command(["python", "-m", "pytest", "|", "more"])
        self.assertFalse(ok)

    def test_npm_install_rejected(self):
        ok, msg = validate_dev_command(["npm", "install"])
        self.assertFalse(ok)

    def test_npm_test_ok(self):
        ok, msg = validate_dev_command(["npm", "test"])
        self.assertTrue(ok, msg)

    def test_pip_install_rejected(self):
        ok, msg = validate_dev_command(["pip", "install", "requests"])
        self.assertFalse(ok)

    def test_pip_list_ok(self):
        ok, msg = validate_dev_command(["pip", "list"])
        self.assertTrue(ok, msg)

    def test_poetry_run_nested_ok(self):
        ok, msg = validate_dev_command(["poetry", "run", "pytest", "-q"])
        self.assertTrue(ok, msg)

    def test_make_arbitrary_target_rejected(self):
        ok, msg = validate_dev_command(["make", "clean"])
        self.assertFalse(ok)

    def test_make_test_ok(self):
        ok, msg = validate_dev_command(["make", "test"])
        self.assertTrue(ok, msg)


if __name__ == "__main__":
    unittest.main()
