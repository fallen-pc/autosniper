import unittest
from copy import deepcopy
from datetime import datetime, timedelta

import pandas as pd

from shared.comps_engine import CompsEngine, CompsEngineConfig, parse_currency


def _base_row(**overrides):
    row = {
        "make": "TOYOTA",
        "model": "Corolla",
        "year": 2018,
        "odometer_reading": 80000,
        "repair_severity": 0,
        "sale_price": 15000,
        "date_sold": "2023-06-01",
        "location_state": "NSW",
        "url": "http://example.com/listing/1",
    }
    row.update(overrides)
    return row


def _make_df(rows):
    return pd.DataFrame(rows)


def _sold_date(offset_days=0):
    return (datetime(2023, 6, 1) - timedelta(days=offset_days)).strftime("%Y-%m-%d")


class TestParseCurrency(unittest.TestCase):
    def test_parse_currency_formatted(self):
        self.assertEqual(parse_currency("$14,500"), 14500.0)

    def test_parse_currency_none(self):
        self.assertIsNone(parse_currency(None))

    def test_parse_currency_empty(self):
        self.assertIsNone(parse_currency(""))

    def test_parse_currency_plain_float(self):
        self.assertEqual(parse_currency(12000.0), 12000.0)


class TestCompsEngineHappyPath(unittest.TestCase):
    def setUp(self):
        rows = [
            _base_row(url=f"http://example.com/listing/{i}", date_sold=_sold_date(i + 1))
            for i in range(1, 7)
        ]
        self.engine = CompsEngine(_make_df(rows))
        self.subject = pd.Series(_base_row(date_sold="2023-06-01"))
        self.subject["make"] = "TOYOTA"
        self.subject["model"] = "Corolla"
        self.subject["year_numeric"] = 2018.0
        self.subject["odometer_numeric"] = 80000.0
        self.subject["repair_severity"] = 0.0
        self.subject["location_state"] = "NSW"
        self.subject["date_sold"] = pd.Timestamp("2023-06-01")

    def test_predict_row_happy_path(self):
        p50, p90, count, confidence = self.engine.predict_row(self.subject)
        self.assertIsNotNone(p50)
        self.assertIsNotNone(p90)
        self.assertGreaterEqual(count, 1)
        self.assertGreater(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)


class TestCompsEngineAdjustments(unittest.TestCase):
    def _engine_with_one_comp(self, **comp_overrides):
        comp = _base_row(url="http://example.com/comp/1", date_sold=_sold_date(1))
        comp.update(comp_overrides)
        cfg = CompsEngineConfig(min_comps=1, preferred_comps=1)
        return CompsEngine(_make_df([comp]), config=cfg)

    def _subject(self, **overrides):
        s = {
            "make": "TOYOTA",
            "model": "Corolla",
            "year_numeric": 2018.0,
            "odometer_numeric": 80000.0,
            "repair_severity": 0.0,
            "location_state": "NSW",
            "date_sold": pd.Timestamp("2023-06-01"),
            "url": "http://example.com/subject",
        }
        s.update(overrides)
        return pd.Series(s)

    def test_year_adjustment(self):
        engine = self._engine_with_one_comp(year=2017, sale_price=15000)
        subject = self._subject(year_numeric=2018.0)
        p50, _p90, count, _conf = engine.predict_row(subject)
        self.assertIsNotNone(p50)
        self.assertAlmostEqual(p50, 15000.0 + 700.0, places=1)

    def test_odometer_adjustment(self):
        engine = self._engine_with_one_comp(odometer_reading=90000, sale_price=15000)
        subject = self._subject(odometer_numeric=80000.0)
        p50, _p90, _count, _conf = engine.predict_row(subject)
        self.assertIsNotNone(p50)
        self.assertAlmostEqual(p50, 15000.0 + 280.0, places=1)

    def test_state_penalty(self):
        engine = self._engine_with_one_comp(location_state="VIC", sale_price=15000)
        subject = self._subject(location_state="NSW")
        p50, _p90, _count, _conf = engine.predict_row(subject)
        self.assertIsNotNone(p50)
        self.assertAlmostEqual(p50, 15000.0 - 200.0, places=1)


class TestCompsEngineFallback(unittest.TestCase):
    def test_fallback_widening(self):
        rows = [
            _base_row(url=f"http://example.com/listing/{i}", date_sold=_sold_date(i + 1))
            for i in range(1, 3)
        ]
        cfg = CompsEngineConfig(min_comps=5)
        engine = CompsEngine(_make_df(rows), config=cfg)
        subject = pd.Series({
            "make": "TOYOTA",
            "model": "Corolla",
            "year_numeric": 2018.0,
            "odometer_numeric": 80000.0,
            "repair_severity": 0.0,
            "location_state": "NSW",
            "date_sold": pd.Timestamp("2023-06-01"),
            "url": "http://example.com/subject",
        })
        p50, _p90, count, _conf = engine.predict_row(subject)
        self.assertIsNotNone(p50)
        self.assertGreaterEqual(count, 1)


class TestCompsEngineEdgeCases(unittest.TestCase):
    def test_empty_pool_no_match(self):
        rows = [_base_row(make="HONDA", model="Civic", url="http://example.com/1", date_sold=_sold_date(1))]
        engine = CompsEngine(_make_df(rows))
        subject = pd.Series({
            "make": "TOYOTA",
            "model": "Corolla",
            "year_numeric": 2018.0,
            "odometer_numeric": 80000.0,
            "repair_severity": 0.0,
            "location_state": "NSW",
            "date_sold": pd.Timestamp("2023-06-01"),
            "url": "http://example.com/subject",
        })
        result = engine.predict_row(subject)
        self.assertEqual(result, (None, None, 0, 0.0))

    def test_url_self_exclusion(self):
        shared_url = "http://example.com/listing/self"
        rows = [
            _base_row(url=shared_url, date_sold=_sold_date(1)),
            _base_row(url="http://example.com/listing/other1", date_sold=_sold_date(2)),
            _base_row(url="http://example.com/listing/other2", date_sold=_sold_date(3)),
        ]
        cfg = CompsEngineConfig(min_comps=1)
        engine = CompsEngine(_make_df(rows), config=cfg)
        subject = pd.Series({
            "make": "TOYOTA",
            "model": "Corolla",
            "year_numeric": 2018.0,
            "odometer_numeric": 80000.0,
            "repair_severity": 0.0,
            "location_state": "NSW",
            "date_sold": pd.Timestamp("2023-06-01"),
            "url": shared_url,
        })
        _p50, _p90, count, _conf = engine.predict_row(subject)
        self.assertLessEqual(count, 2)


class TestCompsEngineRun(unittest.TestCase):
    def test_run_returns_dataframe(self):
        rows = [
            _base_row(url=f"http://example.com/listing/{i}", date_sold=_sold_date(i))
            for i in range(1, 4)
        ]
        cfg = CompsEngineConfig(min_comps=1)
        engine = CompsEngine(_make_df(rows), config=cfg)
        result = engine.run()
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 3)
        for col in ("comps_p50", "comps_p90", "comps_count", "comps_confidence"):
            self.assertIn(col, result.columns)


if __name__ == "__main__":
    unittest.main()
