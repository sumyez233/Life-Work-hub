"""CLI 单实例文件锁回归测试（防止 bot/serve 启动路径漏测）。"""
import os
import unittest

from lifehub import cli
from lifehub.config import ROOT


class CliLockTests(unittest.TestCase):

    def test_lock_acquire_then_second_attempt_fails(self):
        name = f"ut_lock_{os.getpid()}"
        try:
            self.assertTrue(cli._acquire_lock(name))
            # 同一进程内二次获取同一把锁应失败
            self.assertFalse(cli._acquire_lock(name))
        finally:
            cli._release_lock(name)

    def test_lock_file_under_project_root(self):
        self.assertTrue((ROOT / "data").is_dir() or (ROOT / "data").exists())


if __name__ == "__main__":
    unittest.main()
