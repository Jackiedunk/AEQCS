from scripts.verify_mcp_permissions import (
    FORBIDDEN_TABLE_PRIVILEGES,
    REQUIRED_TABLE_PRIVILEGES,
    audit_table_privileges,
)


def grant_rows(grants):
    return [
        {"table_name": table_name, "privilege_type": privilege}
        for table_name, privileges in grants.items()
        for privilege in privileges
    ]


def test_mcp_permission_audit_accepts_expected_restricted_grants():
    report = audit_table_privileges(grant_rows(REQUIRED_TABLE_PRIVILEGES))

    assert report["status"] == "ok"
    assert report["missing_required"] == []
    assert report["forbidden_present"] == []


def test_mcp_permission_audit_rejects_authoritative_table_write_grants():
    grants = {table: set(privileges) for table, privileges in REQUIRED_TABLE_PRIVILEGES.items()}
    grants["stock_daily_origin"] = {*grants["stock_daily_origin"], "UPDATE"}
    grants["event_log"] = {*grants["event_log"], "DELETE"}

    report = audit_table_privileges(grant_rows(grants))

    assert report["status"] == "failed"
    assert {
        "table": "stock_daily_origin",
        "privilege": "UPDATE",
    } in report["forbidden_present"]
    assert {"table": "event_log", "privilege": "DELETE"} in report["forbidden_present"]


def test_mcp_permission_audit_tracks_forbidden_tables_explicitly():
    assert FORBIDDEN_TABLE_PRIVILEGES["stock_daily_origin"] == {"INSERT", "UPDATE", "DELETE"}
    assert FORBIDDEN_TABLE_PRIVILEGES["financial_indicators"] == {"INSERT", "UPDATE", "DELETE"}
    assert FORBIDDEN_TABLE_PRIVILEGES["index_constituents"] == {"INSERT", "UPDATE", "DELETE"}
    assert FORBIDDEN_TABLE_PRIVILEGES["event_log"] == {"UPDATE", "DELETE"}
    assert FORBIDDEN_TABLE_PRIVILEGES["event_consumptions"] == {"UPDATE", "DELETE"}
