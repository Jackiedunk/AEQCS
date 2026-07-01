from scripts.verify_table_bloat import evaluate_table_bloat


def test_table_bloat_report_passes_after_four_hour_observation():
    report = evaluate_table_bloat(
        [
            {"relname": "signal_log", "n_live_tup": 10_000, "n_dead_tup": 100},
            {"relname": "proposals", "n_live_tup": 1_000, "n_dead_tup": 20},
            {"relname": "cooccurrence_cache", "n_live_tup": 5_000, "n_dead_tup": 200},
            {"relname": "minute_bar_hot", "n_live_tup": 1_000_000, "n_dead_tup": 10_000},
        ],
        observed_hours=4.25,
        max_dead_tuple_ratio=0.10,
    )

    assert report["status"] == "ok"
    assert report["observed_hours"] == 4.25
    assert report["max_dead_tuple_ratio"] == 0.10
    assert report["failures"] == []
    assert report["tables"]["signal_log"]["dead_tuple_ratio"] == 0.009901


def test_table_bloat_report_fails_when_dead_tuple_ratio_exceeds_threshold():
    report = evaluate_table_bloat(
        [
            {"relname": "signal_log", "n_live_tup": 1_000, "n_dead_tup": 400},
            {"relname": "proposals", "n_live_tup": 1_000, "n_dead_tup": 20},
        ],
        observed_hours=4,
        max_dead_tuple_ratio=0.10,
    )

    assert report["status"] == "failed"
    assert report["failures"] == [
        {
            "table": "signal_log",
            "reason": "dead_tuple_ratio_exceeded",
            "dead_tuple_ratio": 0.285714,
            "max_dead_tuple_ratio": 0.10,
        }
    ]


def test_table_bloat_report_requires_four_hour_intraday_observation():
    report = evaluate_table_bloat(
        [{"relname": "signal_log", "n_live_tup": 1_000, "n_dead_tup": 10}],
        observed_hours=3.5,
        min_observed_hours=4,
    )

    assert report["status"] == "failed"
    assert report["failures"] == [
        {
            "reason": "insufficient_observation_window",
            "observed_hours": 3.5,
            "min_observed_hours": 4,
        }
    ]
