"""SQLite 数据层测试（使用临时数据库，不影响真实数据）。"""
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from lifehub import db


class DbTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lifehub_test_")
        self._orig_db = db.CFG.hub.db
        self._orig_initialized = db._initialized
        db.CFG.hub.db = Path(self._tmp) / "test.db"
        db._initialized = False
        db.init_db()

    def tearDown(self):
        db.CFG.hub.db = self._orig_db
        db._initialized = self._orig_initialized
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_add_list_complete_todo(self):
        tid = db.add_todo("买牛奶")
        self.assertEqual([r["title"] for r in db.list_todos()], ["买牛奶"])
        self.assertTrue(db.complete_todo(tid))
        self.assertEqual(db.list_todos(), [])
        self.assertEqual(len(db.list_todos(status="done")), 1)
        self.assertFalse(db.complete_todo(tid))

    def test_complete_todo_smart_fuzzy(self):
        db.add_todo("买速溶咖啡")
        res = db.complete_todo_smart("咖啡")
        self.assertIsNotNone(res)
        self.assertIn("咖啡", res[1])
        self.assertIsNone(db.complete_todo_smart("咖啡"))

    def test_delete_smart_priority_todo(self):
        db.add_todo("买牛奶")
        label, title = db.delete_smart("牛奶")
        self.assertEqual(label, "待办")
        self.assertIn("牛奶", title)
        self.assertEqual(db.list_todos(), [])

    def test_delete_smart_event_and_ledger(self):
        db.add_event("产品评审", "2026-09-07 15:00")
        self.assertEqual(db.delete_smart("产品评审")[0], "日程")

        db.add_ledger(35.0, "餐饮", "午饭", occurred_on=date.today().isoformat())
        label, title = db.delete_smart("午饭")
        self.assertEqual(label, "账目")
        self.assertIn("午饭", title)

    def test_ledger_summary(self):
        day = "2026-09-06"
        db.add_ledger(35.0, "餐饮", "午饭", occurred_on=day)
        db.add_ledger(9.9, "餐饮", "美式", occurred_on=day)
        db.add_ledger(8000.0, "收入", "工资", occurred_on=day, kind="income")
        self.assertAlmostEqual(db.spend_between(day, day), 44.9)
        self.assertAlmostEqual(db.income_between(day, day), 8000.0)

    def test_usage_bump(self):
        db.usage_bump("done")
        db.usage_bump("done")
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT done FROM usage WHERE day = date('now','localtime')"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["done"], 2)


if __name__ == "__main__":
    unittest.main()
