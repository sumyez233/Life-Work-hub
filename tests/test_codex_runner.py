"""Codex 直通执行器配置与路径测试（不实际调用 codex CLI）。"""
import unittest

from lifehub import codex_runner
from lifehub.config import ROOT


class CodexRunnerPathTests(unittest.TestCase):

    def test_sessions_file_is_under_project_root(self):
        self.assertEqual(codex_runner._SESSIONS_FILE, ROOT / "data" / "codex_sessions.json")
        self.assertTrue(codex_runner._SESSIONS_FILE.is_absolute())
        self.assertEqual(codex_runner._SESSIONS_FILE.parent.name, "data")


if __name__ == "__main__":
    unittest.main()
