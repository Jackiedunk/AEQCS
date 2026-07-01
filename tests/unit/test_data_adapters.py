from datetime import date, datetime
import threading
import time

import pandas as pd
import pytest

from aeqcs.core.exceptions import DataSourceError
from aeqcs.data.adapters.akshare_adapter import AkshareAdapter
from aeqcs.data.adapters.baostock_adapter import BaostockAdapter
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
                    "grossprofit_margin": 0.31,
                    "netprofit_margin": 0.17,
                    "quick_ratio": 1.08,
                }
            ]
        )


class MalformedTushareRowsClient:
    def daily(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": " ",
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
                    "ann_date": "not-a-date",
                    "roe_dt": 0.12,
                }
            ]
        )


class DuplicateTushareFinancialColumnsClient:
    def daily(self, **kwargs):
        raise AssertionError("daily should not be called")

    def fina_indicator(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001",
                    "end_date": "20251231",
                    "ann_date": "20260115",
                    "roe": 0.99,
                    "roe_dt": 0.12,
                    "gross_margin": 0.88,
                    "grossprofit_margin": 0.31,
                    "netprofit_margin": 0.17,
                }
            ]
        )


class FakeAkshareClient:
    def stock_board_concept_cons_ths(self, symbol: str):
        return pd.DataFrame([{"代码": "1", "名称": "平安银行"}])

    def stock_news_em(self, symbol: str):
        return pd.DataFrame([{"发布时间": "2026-01-02 09:30:00", "新闻标题": "测试新闻"}])


class FailIfCalledAkshareClient:
    def stock_board_concept_cons_ths(self, symbol: str):
        raise AssertionError("Akshare concept constituents should not be called")

    def stock_news_em(self, symbol: str):
        raise AssertionError("Akshare stock news should not be called")


class InvalidAkshareRowsClient:
    def stock_board_concept_cons_ths(self, symbol: str):
        return pd.DataFrame([{"代码": " ", "名称": "平安银行"}])

    def stock_news_em(self, symbol: str):
        return pd.DataFrame([{"发布时间": "2026-01-02 09:30:00", "新闻标题": " "}])


class MalformedAkshareRowsClient:
    def stock_board_concept_cons_ths(self, symbol: str):
        return pd.DataFrame([{"代码": "abc", "名称": "平安银行"}])

    def stock_news_em(self, symbol: str):
        return pd.DataFrame([{"发布时间": "not-a-time", "新闻标题": "测试新闻"}])


class FakeFinancialRevisionAdapter:
    def __init__(self, frames):
        self.frames = list(frames)

    def fina_indicator(self, symbol: str):
        return self.frames.pop(0)


class FailIfCalledTushareClient:
    def daily(self, **kwargs):
        raise AssertionError("Tushare daily should not be called")

    def fina_indicator(self, **kwargs):
        raise AssertionError("Tushare fina_indicator should not be called")


class FailIfCalledImportAdapter:
    def daily(self, symbol: str, start: date, end: date):
        raise AssertionError("import_daily_to_local should not call adapter")

    def fina_indicator(self, symbol: str):
        raise AssertionError("import_financials_to_local should not call adapter")


class MalformedImportAdapter:
    def daily(self, symbol: str, start: date, end: date):
        return pd.DataFrame(
            [
                {
                    "symbol": " ",
                    "date": "20260102",
                    "open": 11,
                    "high": 12,
                    "low": 10,
                    "close": 11.5,
                    "volume": 100,
                    "amount": 1100,
                }
            ]
        )

    def fina_indicator(self, symbol: str):
        return pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "not-a-date",
                    "roe": 0.12,
                }
            ]
        )


class InvalidDailyBarImportAdapter:
    def daily(self, symbol: str, start: date, end: date):
        return pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "date": "20260102",
                    "open": 11,
                    "high": 10,
                    "low": 9,
                    "close": 11.5,
                    "volume": 100,
                    "amount": 1100,
                }
            ]
        )

    def fina_indicator(self, symbol: str):
        raise AssertionError("financials should not be called")


class FakeBaostockLoginResult:
    error_code = "0"
    error_msg = "success"


class FakeBaostockQueryResult:
    def __init__(self, frame):
        self.error_code = "0"
        self.error_msg = "success"
        self._frame = frame

    def get_data(self):
        return self._frame


class FakeBaostockClient:
    def __init__(self, *, sleep_seconds: float = 0.0):
        self.login_count = 0
        self.requests = []
        self.sleep_seconds = sleep_seconds
        self.in_flight = 0
        self.max_in_flight = 0

    def login(self):
        self.login_count += 1
        return FakeBaostockLoginResult()

    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.sleep_seconds:
                time.sleep(self.sleep_seconds)
            self.requests.append(
                {
                    "code": code,
                    "fields": fields,
                    "start_date": start_date,
                    "end_date": end_date,
                    "frequency": frequency,
                    "adjustflag": adjustflag,
                }
            )
            return FakeBaostockQueryResult(
                pd.DataFrame(
                    [
                        {
                            "date": "2026-01-02",
                            "code": code,
                            "open": "11",
                            "high": "12",
                            "low": "10",
                            "close": "11.5",
                            "volume": "100",
                            "amount": "1100",
                            "pctChg": "1.23",
                            "peTTM": "9.8",
                        }
                    ]
                )
            )
        finally:
            self.in_flight -= 1


class FakeBaostockMinuteClient(FakeBaostockClient):
    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        self.requests.append(
            {
                "code": code,
                "fields": fields,
                "start_date": start_date,
                "end_date": end_date,
                "frequency": frequency,
                "adjustflag": adjustflag,
            }
        )
        return FakeBaostockQueryResult(
            pd.DataFrame(
                [
                    {
                        "date": "2024-01-02",
                        "time": "20240102093500000",
                        "code": code,
                        "open": "9.39",
                        "high": "9.42",
                        "low": "9.34",
                        "close": "9.34",
                        "volume": "9018600",
                        "amount": "84582080",
                    }
                ]
            )
        )


class ExpiringBaostockClient(FakeBaostockClient):
    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        if len(self.requests) == 0 and self.login_count == 1:
            self.requests.append({"expired": True})
            result = FakeBaostockQueryResult(pd.DataFrame())
            result.error_code = "10002007"
            result.error_msg = "not login"
            return result
        return super().query_history_k_data_plus(code, fields, start_date, end_date, frequency, adjustflag)


def test_tushare_daily_normalizes_columns():
    adapter = TushareAdapter(client=FakeTushareClient())

    frame = adapter.daily("000001", date(2026, 1, 1), date(2026, 1, 2))

    assert frame.iloc[0]["symbol"] == "000001"
    assert frame.iloc[0]["date"] == date(2026, 1, 2)
    assert frame.iloc[0]["volume"] == 100


def test_baostock_daily_uses_raw_adjustflag_and_maps_to_canonical_daily_columns():
    client = FakeBaostockClient()
    now = datetime(2026, 1, 2, 16, 1)
    adapter = BaostockAdapter(client=client, clock=lambda: now)

    frame = adapter.daily("sh.000001", date(2026, 1, 1), date(2026, 1, 2))

    assert client.requests[0]["adjustflag"] == "3"
    assert client.requests[0]["frequency"] == "d"
    assert frame.iloc[0]["symbol"] == "sh.000001"
    assert frame.iloc[0]["date"] == date(2026, 1, 2)
    assert frame.iloc[0]["volume"] == 100
    assert frame.iloc[0]["pct_chg"] == 1.23
    assert frame.iloc[0]["pe_ttm"] == 9.8
    assert frame.iloc[0]["timestamp"] == pd.Timestamp("2026-01-02")
    assert frame.iloc[0]["knowledge_ts"] == now


def test_baostock_reconnects_transparently_when_session_expires():
    client = ExpiringBaostockClient()
    adapter = BaostockAdapter(client=client)

    frame = adapter.daily("sh.000001", date(2026, 1, 1), date(2026, 1, 2))

    assert not frame.empty
    assert client.login_count == 2


def test_baostock_adapter_serializes_process_local_requests():
    client = FakeBaostockClient(sleep_seconds=0.05)
    adapter = BaostockAdapter(client=client)
    threads = [
        threading.Thread(target=adapter.daily, args=("sh.000001", date(2026, 1, 1), date(2026, 1, 2)))
        for _ in range(3)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert client.max_in_flight == 1
    assert len(client.requests) == 3


def test_baostock_minute_parses_provider_datetime_format():
    client = FakeBaostockMinuteClient()
    adapter = BaostockAdapter(client=client)

    frame = adapter.minute("sz.000001", date(2024, 1, 2), date(2024, 1, 2), frequency="5")

    assert client.requests[0]["adjustflag"] == "3"
    assert client.requests[0]["frequency"] == "5"
    assert frame.iloc[0]["timestamp"] == pd.Timestamp("2024-01-02 09:35:00")


def test_baostock_adapter_has_no_financial_fundamental_entrypoint():
    adapter = BaostockAdapter(client=FakeBaostockClient())

    assert not hasattr(adapter, "fina_indicator")


def test_tushare_daily_rejects_invalid_request_before_provider_call():
    adapter = TushareAdapter(client=FailIfCalledTushareClient())

    with pytest.raises(ValueError, match="symbol is required"):
        adapter.daily(" ", date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(ValueError, match="start must be on or before end"):
        adapter.daily("000001.SZ", date(2026, 1, 3), date(2026, 1, 2))


def test_tushare_financials_rejects_empty_symbol_before_provider_call():
    adapter = TushareAdapter(client=FailIfCalledTushareClient())

    with pytest.raises(ValueError, match="symbol is required"):
        adapter.fina_indicator(" ")


def test_tushare_financials_normalize_pit_fields():
    adapter = TushareAdapter(client=FakeTushareClient())

    frame = adapter.fina_indicator("000001")

    assert frame.iloc[0]["period"] == "20251231"
    assert frame.iloc[0]["ann_date"] == date(2026, 1, 15)
    assert frame.iloc[0]["roe"] == 0.12
    assert frame.iloc[0]["gross_margin"] == 0.31
    assert frame.iloc[0]["net_margin"] == 0.17
    assert frame.iloc[0]["quick_ratio"] == 1.08


def test_tushare_financials_prefer_mapped_provider_fields_without_duplicate_columns():
    adapter = TushareAdapter(client=DuplicateTushareFinancialColumnsClient())

    frame = adapter.fina_indicator("000001")

    assert frame.columns.is_unique
    assert frame.iloc[0]["roe"] == 0.12
    assert frame.iloc[0]["gross_margin"] == 0.31


def test_tushare_rejects_invalid_provider_rows_as_data_source_errors():
    adapter = TushareAdapter(client=MalformedTushareRowsClient())

    with pytest.raises(DataSourceError, match="Tushare daily invalid row"):
        adapter.daily("000001.SZ", date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(DataSourceError, match="Tushare fina_indicator invalid row"):
        adapter.fina_indicator("000001.SZ")


def test_akshare_concept_padding_and_news_entities():
    adapter = AkshareAdapter(client=FakeAkshareClient())

    concept = adapter.concept_constituents("银行")
    news = adapter.stock_news("000001")

    assert concept.iloc[0]["symbol"] == "000001"
    assert news.iloc[0]["entities"] == ["000001"]


def test_akshare_rejects_invalid_inputs_before_provider_call():
    adapter = AkshareAdapter(client=FailIfCalledAkshareClient())

    with pytest.raises(ValueError, match="concept is required"):
        adapter.concept_constituents(" ")
    with pytest.raises(ValueError, match="symbol is required"):
        adapter.stock_news(" ")


def test_akshare_rejects_invalid_provider_rows():
    adapter = AkshareAdapter(client=InvalidAkshareRowsClient())

    with pytest.raises(DataSourceError, match="symbol is required"):
        adapter.concept_constituents("银行")
    with pytest.raises(DataSourceError, match="title is required"):
        adapter.stock_news("000001")


def test_akshare_rejects_malformed_provider_formats():
    adapter = AkshareAdapter(client=MalformedAkshareRowsClient())

    with pytest.raises(DataSourceError, match="symbol must contain only digits"):
        adapter.concept_constituents("银行")
    with pytest.raises(DataSourceError, match="timestamp must be a valid datetime"):
        adapter.stock_news("000001")


def test_importers_upsert_into_local_store(tmp_path):
    store = LocalStore(tmp_path)
    adapter = TushareAdapter(client=FakeTushareClient())

    assert import_daily_to_local(adapter, store, "000001", date(2026, 1, 1), date(2026, 1, 2)) == 1
    assert import_daily_to_local(adapter, store, "000001", date(2026, 1, 1), date(2026, 1, 2)) == 1
    assert import_financials_to_local(adapter, store, "000001") == 1

    assert len(store.load_daily()) == 1
    assert len(store.load_financials()) == 1


def test_importers_reject_invalid_requests_before_adapter_call(tmp_path):
    store = LocalStore(tmp_path)
    adapter = FailIfCalledImportAdapter()

    with pytest.raises(ValueError, match="symbol is required"):
        import_daily_to_local(adapter, store, " ", date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(ValueError, match="start must be on or before end"):
        import_daily_to_local(adapter, store, "000001.SZ", date(2026, 1, 3), date(2026, 1, 2))
    with pytest.raises(ValueError, match="symbol is required"):
        import_financials_to_local(adapter, store, " ")


def test_importers_wrap_malformed_adapter_outputs_as_data_source_errors(tmp_path):
    store = LocalStore(tmp_path)
    adapter = MalformedImportAdapter()

    with pytest.raises(DataSourceError, match="daily import invalid row"):
        import_daily_to_local(adapter, store, "000001", date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(DataSourceError, match="financial import invalid row"):
        import_financials_to_local(adapter, store, "000001")


def test_import_daily_wraps_invalid_bar_quality_as_data_source_error(tmp_path):
    store = LocalStore(tmp_path)
    adapter = InvalidDailyBarImportAdapter()

    with pytest.raises(DataSourceError, match="daily import invalid bar"):
        import_daily_to_local(adapter, store, "000001", date(2026, 1, 1), date(2026, 1, 2))


def test_import_financials_assigns_vintage_for_revisions_and_new_periods(tmp_path):
    store = LocalStore(tmp_path)
    adapter = FakeFinancialRevisionAdapter(
        [
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "period": "2025Q4",
                        "ann_date": date(2026, 1, 15),
                        "roe": 0.10,
                    }
                ]
            ),
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "period": "2025Q4",
                        "ann_date": date(2026, 1, 20),
                        "roe": 0.12,
                    }
                ]
            ),
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "period": "2026Q1",
                        "ann_date": date(2026, 4, 20),
                        "roe": 0.08,
                    }
                ]
            ),
        ]
    )

    import_financials_to_local(adapter, store, "000001")
    import_financials_to_local(adapter, store, "000001")
    import_financials_to_local(adapter, store, "000001")

    rows = store.load_financials().sort_values(["period", "ann_date"]).to_dict("records")
    assert [(row["period"], row["ann_date"], row["vintage"], row["roe"]) for row in rows] == [
        ("2025Q4", date(2026, 1, 15), 0, 0.10),
        ("2025Q4", date(2026, 1, 20), 1, 0.12),
        ("2026Q1", date(2026, 4, 20), 0, 0.08),
    ]


def test_import_financials_assigns_vintage_within_same_batch_revisions(tmp_path):
    store = LocalStore(tmp_path)
    adapter = FakeFinancialRevisionAdapter(
        [
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "period": "2025Q4",
                        "ann_date": date(2026, 1, 15),
                        "roe": 0.10,
                    },
                    {
                        "symbol": "000001",
                        "period": "2025Q4",
                        "ann_date": date(2026, 1, 20),
                        "roe": 0.12,
                    },
                ]
            )
        ]
    )

    import_financials_to_local(adapter, store, "000001")

    rows = store.load_financials().sort_values("ann_date").to_dict("records")
    assert [(row["ann_date"], row["vintage"], row["roe"]) for row in rows] == [
        (date(2026, 1, 15), 0, 0.10),
        (date(2026, 1, 20), 1, 0.12),
    ]


def test_import_financials_keeps_reimported_same_version_idempotent(tmp_path):
    store = LocalStore(tmp_path)
    frame = pd.DataFrame(
        [
            {
                "symbol": "000001",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 15),
                "roe": 0.10,
            }
        ]
    )
    adapter = FakeFinancialRevisionAdapter([frame, frame.copy()])

    import_financials_to_local(adapter, store, "000001")
    import_financials_to_local(adapter, store, "000001")

    rows = store.load_financials().to_dict("records")
    assert len(rows) == 1
    assert rows[0]["vintage"] == 0
