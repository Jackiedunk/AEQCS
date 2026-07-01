from scripts.verify_risk_alert_delivery import (
    build_alert_report,
    evaluate_delivery,
    expected_alert_event_id,
)


def test_build_alert_report_uses_risk_officer_action():
    report = build_alert_report()

    assert report == {
        "alerts": [
            {
                "severity": "red",
                "action": "risk_officer.reduce_exposure",
                "metric": "gross_exposure",
                "value": "1.2",
                "threshold": "1",
            }
        ]
    }


def test_expected_alert_event_id_matches_strategy_risk_publisher():
    event_id = expected_alert_event_id("delivery-test")

    assert event_id == "risk_alert:delivery-test:risk_officer.reduce_exposure:gross_exposure"


def test_evaluate_delivery_accepts_published_and_consumed_alert():
    event_id = expected_alert_event_id("delivery-test")
    report = evaluate_delivery(
        event_id=event_id,
        notification_payload={"event_id": event_id, "channel": "risk_alerts"},
        stored_payload={
            "event_id": event_id,
            "type": "risk_officer.reduce_exposure",
            "severity": "red",
            "message": "delivery-test: risk_officer.reduce_exposure metric=gross_exposure value=1.2 threshold=1",
        },
        handled_payloads=[
            {
                "event_id": event_id,
                "type": "risk_officer.reduce_exposure",
                "severity": "red",
            }
        ],
    )

    assert report == {
        "status": "ok",
        "event_id": event_id,
        "channel": "risk_alerts",
        "handled_count": 1,
    }


def test_evaluate_delivery_rejects_missing_handler_consumption():
    event_id = expected_alert_event_id("delivery-test")
    report = evaluate_delivery(
        event_id=event_id,
        notification_payload={"event_id": event_id, "channel": "risk_alerts"},
        stored_payload={
            "event_id": event_id,
            "type": "risk_officer.reduce_exposure",
            "severity": "red",
        },
        handled_payloads=[],
    )

    assert report["status"] == "failed"
    assert report["handled_count"] == 0
