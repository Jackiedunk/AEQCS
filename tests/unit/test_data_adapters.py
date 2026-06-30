from datetime import date

import pandas as pd

from aeqcs.data.adapters.akshare_adapter import AkshareAdapter
from aeqcs.data.adapters.tushare_adapter import TushareAdapter
from aeqcs.data.etl.importers import import_daily_to_local, import_financials_to_local
from aeqcs.store.local import LocalStore


class FakeTushareClient:
    def daily(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001",
                    "trade_date": "20260102",
                    "open": 11,
                    "high": 12,
                    "low": 10,
                    "close": 11.5,
                    "vol": 100,
                    "amount": 1100,
                }
            ]
        )

    def fina_indicator(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001",
                    "end_date": "20251231",
                    "ann_date": "20260115",
                    "roe_dt": 0.12,
                    "basic_eps": 0.8,
                }
            ]
        )


class FakeAkshareClient:
    def stock_board_concept_cons_ths(self, symbol: str):
        return pd.DataFrame([{"代码": "1", "名称": "平安银行"}])

    def stock_news_em(self, symbol: str):
        return pd.DataFrame([{"发布时间": "2026-01-02 09:30:00", "新闻标题": "测试新闻"}])


def test_tushare_daily_normalizes_columns():
    adapter = TushareAdapter(client=FakeTushareClient())

    frame = adapter.daily("000001", date(2026, 1, 1), date(2026, 1, 2))

    assert frame.iloc[0]["symbol"] == "000001"
    assert frame.iloc[0]["date"] == date(2026, 1, 2)
    assert frame.iloc[0]["volume"] == 100


def test_tushare_financials_normalize_pit_fields():
    adapter = TushareAdapter(client=FakeTushareClient())

    frame = adapter.fina_indicator("000001")

    assert frame.iloc[0]["period"] == "20251231"
    assert frame.iloc[0]["ann_date"] == date(2026, 1, 15)
    assert frame.iloc[0]["roe"] == 0.12


def test_akshare_concept_padding_and_news_entities():
    adapter = AkshareAdapter(client=FakeAkshareClient())

    concept = adapter.concept_constituents("银行")
    news = adapter.stock_news("000001")

    assert concept.iloc[0]["symbol"] == "000001"
    assert news.iloc[0]["entities"] == ["000001"]


def test_importers_upsert_into_local_store(tmp_path):
    store = LocalStore(tmp_path)
    adapter = TushareAdapter(client=FakeTushareClient())

    assert import_daily_to_local(adapter, store, "000001", date(2026, 1, 1), date(2026, 1, 2)) == 1
    assert import_daily_to_local(adapter, store, "000001", date(2026, 1, 1), date(2026, 1, 2)) == 1
    assert import_financials_to_local(adapter, store, "000001") == 1

    assert len(store.load_daily()) == 1
    assert len(store.load_financials()) == 1
