"""配置默认值与示例配置脱敏测试。"""
import unittest
from pathlib import Path

from lifehub.config import Config, ROOT, load


class ConfigSanityTests(unittest.TestCase):

    def test_defaults_are_clean(self):
        cfg = Config()
        self.assertEqual(cfg.bitable.app_token, "")
        self.assertEqual(cfg.bitable.table_id, "")
        self.assertEqual(cfg.transfer.search_dirs, [])
        self.assertEqual(cfg.codex.sandbox, "read-only")
        self.assertFalse(cfg.codex.enabled)
        self.assertIsInstance(cfg.transfer.inbox_dir, Path)

    def test_example_config_loads_without_private_values(self):
        cfg = load(ROOT / "config.example.toml")
        self.assertEqual(cfg.bitable.app_token, "")
        self.assertEqual(cfg.bitable.table_id, "")
        self.assertEqual(cfg.transfer.search_dirs, [])
        self.assertEqual(cfg.codex.sandbox, "read-only")
        self.assertFalse(cfg.codex.enabled)
        # 示例中只允许占位符形式的会话 ID
        self.assertTrue(
            all(cid.startswith("oc_xxxxxxxx") for cid in cfg.codex.allowed_chats)
        )


if __name__ == "__main__":
    unittest.main()
