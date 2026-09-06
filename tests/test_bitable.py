"""多维表格通用摘要逻辑测试（不访问网络）。"""
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from lifehub import bitable


class SummarizeTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lifehub_bitable_")
        self._orig = (
            bitable.CFG.bitable.app_token,
            bitable.CFG.bitable.table_id,
            bitable.CFG.bitable.updated_field,
            bitable.CFG.bitable.cache_file,
        )
        bitable.CFG.bitable.cache_file = Path(self._tmp) / "cache.json"

    def tearDown(self):
        (bitable.CFG.bitable.app_token,
         bitable.CFG.bitable.table_id,
         bitable.CFG.bitable.updated_field,
         bitable.CFG.bitable.cache_file) = self._orig

    def test_summarize_counts_and_latest(self):
        bitable.CFG.bitable.updated_field = "更新时间"
        records = [
            {"更新时间": "2026-09-01 10:00"},
            {"更新时间": "2026-09-05 09:00"},
        ]
        stats = bitable.summarize(records)
        self.assertEqual(stats["total_records"], 2)
        self.assertEqual(stats["latest_updated"], "2026-09-05 09:00")
        self.assertTrue(stats["fetched_at"])

    def test_latest_supports_dict_value(self):
        bitable.CFG.bitable.updated_field = "更新时间"
        records = [{"更新时间": {"text": "2026-09-03"}}]
        stats = bitable.summarize(records)
        self.assertEqual(stats["latest_updated"], "2026-09-03")

    def test_no_updated_field_returns_empty(self):
        bitable.CFG.bitable.updated_field = ""
        stats = bitable.summarize([{"其他字段": "x"}])
        self.assertEqual(stats["latest_updated"], "")
        self.assertEqual(stats["total_records"], 1)

    def test_unconfigured_state(self):
        bitable.CFG.bitable.app_token = ""
        bitable.CFG.bitable.table_id = ""
        self.assertFalse(bitable.configured())
        stats = bitable.get_cached_or_fresh()
        self.assertFalse(stats["configured"])
        self.assertEqual(stats["total_records"], 0)

    def test_fetch_and_analyze_caches_full_records(self):
        bitable.CFG.bitable.app_token = "fake_app_token"
        bitable.CFG.bitable.table_id = "fake_table_id"
        bitable.CFG.bitable.updated_field = "更新时间"
        records = [
            {"更新时间": "2026-09-05 09:00", "标题": "示例"},
            {"更新时间": "2026-09-01 10:00", "标题": "另一条"},
        ]
        with mock.patch.object(bitable, "fetch_records", return_value=records):
            stats = bitable.fetch_and_analyze()
        self.assertIsNotNone(stats)
        self.assertEqual(stats["records"], records)
        self.assertEqual(stats["total_records"], 2)
        cached = json.loads(bitable.CFG.bitable.cache_file.read_text(encoding="utf-8"))
        self.assertEqual(cached["records"], records)


if __name__ == "__main__":
    unittest.main()
