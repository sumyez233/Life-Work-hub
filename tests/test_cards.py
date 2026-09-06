"""Schema 2.0 卡片结构测试。"""
import shutil
import tempfile
import unittest
from pathlib import Path

from lifehub import cards, db


class CardStructureTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lifehub_cards_")
        self._orig_db = db.CFG.hub.db
        self._orig_initialized = db._initialized
        db.CFG.hub.db = Path(self._tmp) / "cards.db"
        db._initialized = False
        db.init_db()

    def tearDown(self):
        db.CFG.hub.db = self._orig_db
        db._initialized = self._orig_initialized
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_menu_card_is_schema_v2(self):
        card = cards.build("menu")
        self.assertEqual(card["schema"], "2.0")
        self.assertIn("title", card["header"])
        self.assertIn("elements", card["body"])

    def test_todos_card_contains_open_todo(self):
        db.add_todo("买牛奶")
        card = cards.build("todos")
        self.assertEqual(card["schema"], "2.0")
        dumped = str(card)
        self.assertIn("买牛奶", dumped)


if __name__ == "__main__":
    unittest.main()
