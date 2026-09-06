from __future__ import annotations

import unittest
from lifehub import bot


class BotTests(unittest.TestCase):
    def test_dedup_message(self):
        msg_id = "test_msg_unique_123"
        self.assertFalse(bot._is_duplicate_message(msg_id))
        # Second call with same message id should report duplicate
        self.assertTrue(bot._is_duplicate_message(msg_id))

    def test_empty_message_id(self):
        self.assertFalse(bot._is_duplicate_message(""))

    def test_menu_phrase_matches(self):
        self.assertEqual(bot._match_board("功能"), "menu")
        self.assertEqual(bot._match_board("汇报功能"), "menu")
        self.assertEqual(bot._match_board("调出说明"), "menu")
        self.assertEqual(bot._match_board("你会做什么"), "menu")


if __name__ == "__main__":
    unittest.main()
