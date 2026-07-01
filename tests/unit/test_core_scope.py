from pathlib import Path

from aeqcs.core.config import load_settings


def test_core_package_does_not_include_llm_or_cognitive_agent_modules():
    assert not Path("aeqcs/llm").exists()
    assert not Path("aeqcs/agents/market_observer.py").exists()
    assert not Path("aeqcs/factor/qlib_expression_handler.py").exists()


def test_role_prompts_are_limited_to_deterministic_core_roles():
    role_files = {path.stem for path in Path("aeqcs/config/roles").glob("*.txt")}

    assert role_files == {
        "data_steward",
        "factor_researcher",
        "strategy_engineer",
        "risk_officer",
    }


def test_core_settings_exclude_llm_and_cognitive_database():
    settings = load_settings(".")

    assert "llm" not in settings
    assert "cognitive" not in settings["database"]


def test_embedding_settings_are_cpu_bge_with_resource_budget():
    embedding = load_settings(".")["embedding"]

    assert embedding["provider"] == "sentence-transformers"
    assert embedding["model"] == "BAAI/bge-base-zh-v1.5"
    assert embedding["device"] == "cpu"
    assert embedding["max_resident_mb"] <= 1024


def test_core_sources_do_not_reference_llm_or_market_observer():
    scanned_paths = [
        *Path("aeqcs").rglob("*.py"),
        *Path("aeqcs/config").rglob("*.yaml"),
        Path("deploy/init_db.py"),
    ]

    offenders = []
    for path in scanned_paths:
        text = path.read_text(encoding="utf-8")
        if "llm" in text.lower() or "market_observer" in text or "cognitive" in text.lower():
            offenders.append(str(path))

    assert offenders == []
