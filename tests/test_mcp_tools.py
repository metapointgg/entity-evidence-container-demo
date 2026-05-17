from __future__ import annotations

from eec import mcp_tools


def test_archive_status_uses_environment_paths(monkeypatch, tmp_path):
    root = tmp_path / "trustvault"
    monkeypatch.setenv("TRUSTVAULT_ROOT", str(root))
    monkeypatch.setenv("TRUSTVAULT_SOURCE_DIR", str(root / "source"))
    monkeypatch.setenv("TRUSTVAULT_CONTAINERS_DIR", str(root / "containers"))
    monkeypatch.setenv("TRUSTVAULT_INDEX_PATH", str(root / "index" / "evidence_index.db"))
    monkeypatch.setenv("TRUSTVAULT_VECTOR_PATH", str(root / "index" / "evidence_vector.pkl"))
    monkeypatch.setenv("TRUSTVAULT_LMSTUDIO_VECTOR_PATH", str(root / "index" / "evidence_lmstudio_vector.pkl"))
    monkeypatch.setenv("TRUSTVAULT_EXPORTS_DIR", str(root / "exports"))

    status = mcp_tools.archive_status()

    assert status["product"] == "TrustVault"
    assert status["paths"]["source_folder"] == str(root / "source")
    assert status["paths"]["containers_folder"] == str(root / "containers")
    assert status["paths"]["index_path"] == str(root / "index" / "evidence_index.db")
    assert status["configuration"]["read_only"] is True
    assert status["configuration"]["export_enabled"] is False


def test_interpret_query_normalises_onboarding_without_ai(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUSTVAULT_ROOT", str(tmp_path))

    result = mcp_tools.interpret_query(
        "Show me all onboarding documentation for high risk clients in Guernsey",
        use_local_ai=False,
    )
    structured = result["structured_query"]

    assert structured["snapshot_id"] == "ONBOARDING"
    assert structured["document_type"] is None
    assert structured["risk_rating"] == "High"
    assert structured["jurisdiction"] == "Guernsey"


def test_export_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUSTVAULT_ROOT", str(tmp_path))
    monkeypatch.delenv("TRUSTVAULT_MCP_ENABLE_EXPORT", raising=False)
    monkeypatch.delenv("TRUSTVAULT_MCP_READ_ONLY", raising=False)

    result = mcp_tools.export_evidence_pack(object_ids=["OBJ-001"])

    assert result["enabled"] is False
    assert result["status"] == "disabled"


def test_list_entities_without_index_returns_empty_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUSTVAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("TRUSTVAULT_CONTAINERS_DIR", str(tmp_path / "containers"))

    result = mcp_tools.list_entities(limit=5)

    assert result["source"] == "fits"
    assert result["rows"] == []
