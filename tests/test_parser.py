"""parser 规则引擎测试。"""
import unittest
from datetime import date, timedelta

from lifehub import parser


class ParseSingleLineTests(unittest.TestCase):

    def test_plain_todo(self):
        p = parser.parse("买牛奶")
        self.assertEqual(p.kind, "todo")
        self.assertEqual(p.title, "买牛奶")
        self.assertEqual(p.priority, 0)

    def test_todo_cleans_fillers_and_priority_markers(self):
        p = parser.parse("周五 !! 体检")
        self.assertEqual(p.kind, "todo")
        self.assertIn("体检", p.title)
        self.assertNotIn("!!", p.title)
        self.assertEqual(p.priority, 1)

    def test_event_with_relative_time(self):
        p = parser.parse("明天下午3点开会")
        self.assertEqual(p.kind, "event")
        self.assertEqual(p.title, "开会")
        self.assertIsNotNone(p.when)
        self.assertEqual(p.when.date(), date.today() + timedelta(days=1))
        self.assertEqual((p.when.hour, p.when.minute), (15, 0))

    def test_todo_with_due_date_but_no_time(self):
        p = parser.parse("明天交方案")
        self.assertEqual(p.kind, "todo")
        self.assertIsNotNone(p.when)
        self.assertEqual(p.when.date(), date.today() + timedelta(days=1))
        self.assertEqual(p.when.hour, 9)

    def test_ledger_expense_with_space(self):
        p = parser.parse("午饭 35")
        self.assertEqual(p.kind, "ledger")
        self.assertAlmostEqual(p.amount, 35.0)
        self.assertEqual(p.category, "餐饮")
        self.assertEqual(p.note, "午饭")
        self.assertEqual(p.direction, "expense")

    def test_ledger_expense_no_unit_with_space(self):
        p = parser.parse("美式 9.9")
        self.assertEqual(p.kind, "ledger")
        self.assertAlmostEqual(p.amount, 9.9)
        self.assertEqual(p.category, "餐饮")

    def test_ledger_income(self):
        p = parser.parse("工资 8000")
        self.assertEqual(p.kind, "ledger")
        self.assertAlmostEqual(p.amount, 8000.0)
        self.assertEqual(p.direction, "income")
        self.assertEqual(p.category, "收入")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            parser.parse("   ")


class ParseMultiLineTests(unittest.TestCase):

    def test_sections_split_into_todos_and_ledger(self):
        text = (
            "学习\n"
            "1. 完成开题报告\n"
            "2. 给导师发邮件\n"
            "今日消费\n"
            "1. 美式9.9\n"
            "2. 打车 23.5"
        )
        out = parser.parse_multi(text)
        self.assertEqual([p.kind for p in out], ["todo", "todo", "ledger", "ledger"])
        self.assertEqual(out[2].category, "餐饮")
        self.assertEqual(out[3].category, "交通")
        self.assertAlmostEqual(out[2].amount, 9.9)
        self.assertAlmostEqual(out[3].amount, 23.5)

    def test_custom_section_header_ending_with_work(self):
        text = "文献阅读工作\n1. 下载论文\n2. 写笔记"
        out = parser.parse_multi(text)
        self.assertEqual([p.kind for p in out], ["todo", "todo"])

    def test_mention_placeholder_removed(self):
        text = "@_user_1 学习\n1. 复习"
        out = parser.parse_multi(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].kind, "todo")


if __name__ == "__main__":
    unittest.main()
