from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import mcp_tools

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - exercised only when optional dependency is absent.
    FastMCP = None  # type: ignore[assignment]


_MCP_INSTALL_HELP = """
The optional MCP Python SDK is not installed.

Install it with one of:

    python -m pip install "mcp[cli]"
    python -m pip install -e ".[mcp]"

Then run:

    python scripts/run_mcp_server.py
    trustvault-mcp
""".strip()

_JURISDICTION_MAP = {
    "guernsey": "Guernsey",
    "jersey": "Jersey",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "isle of man": "Isle of Man",
}

_RISK_RATING_MAP = {
    "high": "High",
    "high risk": "High",
    "high-risk": "High",
    "medium": "Medium",
    "medium risk": "Medium",
    "medium-risk": "Medium",
    "low": "Low",
    "low risk": "Low",
    "low-risk": "Low",
}

_SNAPSHOT_MAP = {
    "onboarding": "ONBOARDING",
    "account opening": "ONBOARDING",
    "cdd review 2026": "CDD_REVIEW_2026",
    "statements 2026 q1": "STATEMENTS_2026_Q1",
    "correspondence 2026": "CORRESPONDENCE_2026",
    "transactions 2026 q1": "TRANSACTIONS_2026_Q1",
    "legal disclosure": "LEGAL_DISCLOSURE",
}


def _json_resource(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str)


def _normalise_lookup(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def _normalise_jurisdiction(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    return _JURISDICTION_MAP.get(_normalise_lookup(text), text)


def _normalise_risk_rating(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    return _RISK_RATING_MAP.get(_normalise_lookup(text), text[:1].upper() + text[1:].lower())


def _normalise_snapshot_id(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    mapped = _SNAPSHOT_MAP.get(_normalise_lookup(text))
    return mapped or text.upper()


def build_server() -> "FastMCP":
    """Build the TrustVault MCP server.

    The server exposes controlled TrustVault tools and resources only. It does
    not expose arbitrary filesystem reads, arbitrary SQL execution, or payload
    binary download tools.
    """

    if FastMCP is None:
        raise RuntimeError(_MCP_INSTALL_HELP)

    mcp = FastMCP("TrustVault MCP")

    @mcp.tool()
    def trustvault_archive_status() -> dict[str, Any]:
        """Return configured TrustVault archive paths and high-level status."""
        return mcp_tools.archive_status()

    @mcp.tool()
    def trustvault_list_entities(
        jurisdiction: str | None = None,
        risk_rating: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """List TrustVault customer/entity records with optional cohort filters."""
        return mcp_tools.list_entities(
            jurisdiction=_normalise_jurisdiction(jurisdiction),
            risk_rating=_normalise_risk_rating(risk_rating),
            limit=limit,
        )

    @mcp.tool()
    def trustvault_get_entity_summary(entity_id: str) -> dict[str, Any]:
        """Return TrustVault metadata, evidence counts and completeness status for one entity."""
        return mcp_tools.get_entity_summary(entity_id=entity_id)

    @mcp.tool()
    def trustvault_search_entity_fits(
        entity_id: str,
        query: str,
        limit: int | None = None,
        document_type: str | None = None,
        category: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        """Search a selected entity's FITS container(s) directly."""
        return mcp_tools.search_entity_fits(
            entity_id=entity_id,
            query=query,
            limit=limit,
            document_type=document_type,
            category=category,
            snapshot_id=_normalise_snapshot_id(snapshot_id),
        )

    @mcp.tool()
    def trustvault_search_archive(
        query: str,
        jurisdiction: str | None = None,
        risk_rating: str | None = None,
        document_type: str | None = None,
        category: str | None = None,
        snapshot_id: str | None = None,
        source_system: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Search across the TrustVault archive using the rebuilt index."""
        return mcp_tools.search_archive(
            query=query,
            jurisdiction=_normalise_jurisdiction(jurisdiction),
            risk_rating=_normalise_risk_rating(risk_rating),
            document_type=document_type,
            category=category,
            snapshot_id=_normalise_snapshot_id(snapshot_id),
            source_system=source_system,
            limit=limit,
        )

    @mcp.tool()
    def trustvault_interpret_query(
        query: str,
        selected_entity_id: str | None = None,
        use_local_ai: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Convert a natural-language archive request into StructuredArchiveQuery JSON."""
        return mcp_tools.interpret_query(
            query=query,
            selected_entity_id=selected_entity_id,
            use_local_ai=use_local_ai,
            limit=limit,
        )

    @mcp.tool()
    def trustvault_execute_query(
        query: str,
        selected_entity_id: str | None = None,
        use_local_ai: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Interpret and execute a natural-language TrustVault archive query."""
        return mcp_tools.execute_query(
            query=query,
            selected_entity_id=selected_entity_id,
            use_local_ai=use_local_ai,
            limit=limit,
        )

    @mcp.tool()
    def trustvault_check_completeness(
        entity_id: str | None = None,
        jurisdiction: str | None = None,
        risk_rating: str | None = None,
        missing_only: bool | None = None,
        ruleset_id: str | None = None,
    ) -> dict[str, Any]:
        """Check evidence completeness for one or more TrustVault customers."""
        return mcp_tools.check_completeness(
            entity_id=entity_id,
            jurisdiction=_normalise_jurisdiction(jurisdiction),
            risk_rating=_normalise_risk_rating(risk_rating),
            missing_only=missing_only,
            ruleset_id=ruleset_id,
        )

    @mcp.tool()
    def trustvault_get_evidence_payload_metadata(entity_id: str, object_id: str) -> dict[str, Any]:
        """Return metadata and safe preview text for an evidence object, not the binary payload."""
        return mcp_tools.get_evidence_payload_metadata(entity_id=entity_id, object_id=object_id)

    @mcp.tool()
    def trustvault_export_evidence_pack(
        query: str | None = None,
        entity_id: str | None = None,
        object_ids: list[str] | None = None,
        output_name: str | None = None,
    ) -> dict[str, Any]:
        """Export an evidence pack when explicitly enabled by MCP configuration."""
        return mcp_tools.export_evidence_pack(
            query=query,
            entity_id=entity_id,
            object_ids=object_ids,
            output_name=output_name,
        )

    @mcp.resource("trustvault://archive/status")
    def resource_archive_status() -> str:
        """TrustVault archive status and configured paths."""
        return _json_resource(mcp_tools.archive_status())

    @mcp.resource("trustvault://entities")
    def resource_entities() -> str:
        """TrustVault entity list."""
        return _json_resource(mcp_tools.list_entities())

    @mcp.resource("trustvault://entities/{entity_id}")
    def resource_entity(entity_id: str) -> str:
        """TrustVault entity summary."""
        return _json_resource(mcp_tools.get_entity_summary(entity_id=entity_id))

    @mcp.resource("trustvault://entities/{entity_id}/evidence")
    def resource_entity_evidence(entity_id: str) -> str:
        """TrustVault evidence metadata for one entity."""
        summary = mcp_tools.get_entity_summary(entity_id=entity_id)
        # Resource responses should stay concise. Use the search tools for targeted snippets.
        return _json_resource(summary)

    @mcp.resource("trustvault://containers/{entity_id}")
    def resource_entity_containers(entity_id: str) -> str:
        """TrustVault FITS container summary for one entity."""
        summary = mcp_tools.get_entity_summary(entity_id=entity_id)
        return _json_resource(
            {
                "source_of_truth_note": summary.get("source_of_truth_note"),
                "entity_id": entity_id,
                "fits_containers": summary.get("fits_containers", []),
            }
        )

    @mcp.resource("trustvault://rulesets")
    def resource_rulesets() -> str:
        """TrustVault completeness rulesets."""
        return _json_resource(mcp_tools.list_rulesets())

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the TrustVault MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="MCP transport to use. LM Studio local MCP configurations normally use stdio.",
    )
    args = parser.parse_args(argv)

    try:
        server = build_server()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
