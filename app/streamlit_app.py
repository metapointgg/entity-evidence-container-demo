from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from eec.archive_health import indexed_health, integrity_health
from eec.container_reader import inspect_container, validate_container
from eec.corruption import corrupt_container
from eec.exporter import export_evidence_pack
from eec.extraction_report import extraction_dashboard, extracted_fields_for_entity, extraction_report_for_container
from eec.fits_direct_search import direct_search_entity
from eec.indexer import rebuild_index
from eec.ingestion import bulk_ingest, process_event_queue, write_ingestion_report
from eec.presets import REGULATORY_PRESETS
from eec.retention import retention_report
from eec.rulesets import (
    DEFAULT_REQUIRED_EVIDENCE,
    default_ruleset,
    ensure_rulesets,
    evaluate_completeness,
    export_completeness_report,
    load_rulesets,
    save_rulesets,
    EvidenceRuleProfile,
    EvidenceRuleset,
)
from eec.search import advanced_search_index
from eec.query_interpreter import execute_structured_query, interpret_archive_query, query_capability_matrix
from eec.search_result_exporter import export_search_results
from eec.local_llm import answer_question_from_evidence, expand_search_query, lm_studio_status, summarise_completeness_report, summarise_search_results
from eec.lmstudio_vector_search import build_lmstudio_vector_index, lmstudio_vector_search
from eec.ui_data import (
    format_bytes,
    get_archive_summary,
    get_index_schema_status,
    list_entities,
    list_facets,
    list_objects_for_entity,
    read_payload,
    resolve_archive_paths,
)
from eec.vector_search import build_vector_index, vector_search

st.set_page_config(page_title="Entity Evidence Container Demo", page_icon="🗃️", layout="wide")
DEFAULT_ROOT = Path("samples")


PATH_SESSION_KEYS = {
    "source": "archive_source_path",
    "containers": "archive_containers_path",
    "index": "archive_index_path",
    "vector": "archive_vector_path",
    "lm_vector": "archive_lm_vector_path",
    "exports": "archive_exports_path",
}


def _default_archive_path_values(root: Path) -> dict[str, Path]:
    """Return the default derived archive paths for a root folder."""
    defaults = resolve_archive_paths(root)
    return {
        "source": defaults.source,
        "containers": defaults.containers,
        "index": defaults.index,
        "vector": defaults.root / "index" / "evidence_vector.pkl",
        "lm_vector": defaults.root / "index" / "evidence_lmstudio_vector.pkl",
        "exports": defaults.exports,
    }


def configure_archive_paths(root: Path):
    """Configure archive paths from the sidebar and store them in session state.

    The root folder remains a convenience default, but the source, containers,
    index and vector locations can be explicitly overridden. This prevents
    ingestion/rebuild actions accidentally targeting the sample container path.
    """
    root = Path(root)
    defaults = _default_archive_path_values(root)
    root_key = str(root)

    if st.session_state.get("archive_paths_root_key") != root_key:
        st.session_state["archive_paths_root_key"] = root_key
        for name, session_key in PATH_SESSION_KEYS.items():
            st.session_state[session_key] = str(defaults[name])

    with st.sidebar.expander("Archive paths", expanded=not is_basic_mode()):
        st.caption("Set these explicitly when using imported client data rather than the sample dataset.")
        source = Path(st.text_input("Source folder", key=PATH_SESSION_KEYS["source"]))
        containers = Path(st.text_input("Containers folder", key=PATH_SESSION_KEYS["containers"]))
        index = Path(st.text_input("SQLite index", key=PATH_SESSION_KEYS["index"]))
        vector = Path(st.text_input("Local vector index", key=PATH_SESSION_KEYS["vector"]))
        lm_vector = Path(st.text_input("LM Studio vector index", key=PATH_SESSION_KEYS["lm_vector"]))
        exports = Path(st.text_input("Exports folder", key=PATH_SESSION_KEYS["exports"]))

        if st.button("Reset paths from root", key="archive-paths-reset"):
            for name, session_key in PATH_SESSION_KEYS.items():
                st.session_state[session_key] = str(defaults[name])
            st.rerun()

    return SimpleNamespace(
        root=root,
        source=source,
        containers=containers,
        index=index,
        vector=vector,
        lm_vector=lm_vector,
        exports=exports,
    )


def get_ui_archive_paths(root: Path):
    """Return path settings chosen in the sidebar, falling back to root defaults."""
    root = Path(root)
    defaults = _default_archive_path_values(root)
    return SimpleNamespace(
        root=root,
        source=Path(st.session_state.get(PATH_SESSION_KEYS["source"], str(defaults["source"]))),
        containers=Path(st.session_state.get(PATH_SESSION_KEYS["containers"], str(defaults["containers"]))),
        index=Path(st.session_state.get(PATH_SESSION_KEYS["index"], str(defaults["index"]))),
        vector=Path(st.session_state.get(PATH_SESSION_KEYS["vector"], str(defaults["vector"]))),
        lm_vector=Path(st.session_state.get(PATH_SESSION_KEYS["lm_vector"], str(defaults["lm_vector"]))),
        exports=Path(st.session_state.get(PATH_SESSION_KEYS["exports"], str(defaults["exports"]))),
    )


def is_basic_mode() -> bool:
    return st.session_state.get("ui_mode", "Basic") == "Basic"


def basic_defaults_for_search() -> dict[str, Any]:
    status = lm_studio_status()
    return {
        "use_local_ai": bool(status.get("available", False)),
        "include_summary": bool(status.get("available", False)),
        "use_direct_fits": True,
        "show_interpreted": False,
        "limit": 50,
        "status": status,
    }


@st.cache_data(show_spinner=False)
def cached_summary(root: str) -> Dict[str, Any]:
    return get_archive_summary(resolve_archive_paths(Path(root)))


@st.cache_data(show_spinner=False)
def cached_entities(index_path: str) -> List[Dict[str, Any]]:
    return list_entities(Path(index_path))


@st.cache_data(show_spinner=False)
def cached_objects(index_path: str, entity_id: str) -> List[Dict[str, Any]]:
    return list_objects_for_entity(Path(index_path), entity_id)


@st.cache_data(show_spinner=False)
def cached_facets(index_path: str) -> Dict[str, List[str]]:
    return list_facets(Path(index_path))


@st.cache_data(show_spinner=False)
def cached_search(index_path: str, query: str, limit: int, mode: str, filters_key: tuple) -> List[Dict[str, Any]]:
    filters = {name: list(values) for name, values in filters_key if values}
    return advanced_search_index(Path(index_path), query=query, filters=filters, limit=limit, mode=mode)


@st.cache_data(show_spinner=False)
def cached_vector_search(vector_path: str, query: str, limit: int) -> List[Dict[str, Any]]:
    return vector_search(Path(vector_path), query, limit)




@st.cache_data(show_spinner=False)
def cached_lmstudio_vector_search(vector_path: str, query: str, limit: int) -> List[Dict[str, Any]]:
    return lmstudio_vector_search(Path(vector_path), query, limit)


@st.cache_data(show_spinner=False)
def cached_direct_fits_search(containers_dir: str, entity_id: str, query: str, structured_payload: dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    # Recreate a lightweight object with attribute access for direct_search_entity.
    class _Structured:
        def __init__(self, payload: dict[str, Any]):
            self.__dict__.update(payload)

    return direct_search_entity(Path(containers_dir), entity_id, query, structured=_Structured(structured_payload), limit=limit)

@st.cache_data(show_spinner=False)
def cached_validate(container_path: str) -> Dict[str, Any]:
    return validate_container(Path(container_path)).to_dict()


def clear_caches() -> None:
    cached_summary.clear(); cached_entities.clear(); cached_objects.clear(); cached_facets.clear(); cached_search.clear(); cached_vector_search.clear(); cached_lmstudio_vector_search.clear(); cached_direct_fits_search.clear(); cached_validate.clear()


def run_generator(customers: int, target_mb: int, seed: int, root: Path) -> None:
    command = [sys.executable, "scripts/generate_sample_data.py", "--customers", str(customers), "--output", str(root / "source"), "--target-mb-per-customer", str(target_mb), "--seed", str(seed)]
    subprocess.run(command, check=True)


def run_build_containers(root: Path, split_snapshots: bool) -> None:
    paths = get_ui_archive_paths(root)
    command = [
        sys.executable,
        "scripts/build_containers.py",
        "--source",
        str(paths.source),
        "--output",
        str(paths.containers),
    ]
    if split_snapshots:
        command.append("--split-snapshots")
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    st.code(completed.stdout or completed.stderr or "Containers built.")


def render_validation_badge(status: str) -> None:
    if status == "PASS":
        st.success("Integrity: PASS")
    else:
        st.error("Integrity: FAIL")


def _safe_preview_text(data: bytes, limit: int = 20000) -> str:
    return data[:limit].decode("utf-8", errors="replace")


def _pdf_iframe(data: bytes, height: int = 720) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f'<iframe src="data:application/pdf;base64,{encoded}" width="100%" height="{height}" type="application/pdf"></iframe>'


def _render_payload_content(row: Dict[str, Any], *, modal: bool = False) -> None:
    item, data = read_payload(Path(row["container_path"]), row["object_id"])
    mime_type = item.get("mime_type", "application/octet-stream")
    filename = item.get("filename", f"{row['object_id']}.bin")
    st.caption(f"{item.get('snapshot_type', row.get('snapshot_type', 'Snapshot'))} · {item.get('category')} · {item.get('document_type')} · {filename} · {format_bytes(len(data))} · {mime_type}")
    st.caption(f"Retention: {item.get('retention_class')} until {item.get('retention_until', 'n/a')} · Legal hold: {item.get('legal_hold_status', 'None')} · OCR/index: {item.get('ocr_source', 'none')}")
    st.download_button("Download original payload", data=data, file_name=filename, mime=mime_type, key=f"download-{row['object_id']}-{'modal' if modal else 'inline'}")
    if mime_type.startswith("text/") or filename.lower().endswith((".txt", ".json", ".csv", ".eml")):
        st.text_area("Payload preview", _safe_preview_text(data), height=420, key=f"text-preview-{row['object_id']}"); return
    if mime_type.startswith("image/"):
        st.image(data, caption=filename, use_container_width=True); return
    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        if len(data) <= 30 * 1024 * 1024:
            st.markdown(_pdf_iframe(data), unsafe_allow_html=True)
        else:
            st.warning("This PDF is larger than 30 MB, so browser preview is disabled. Use download to inspect locally.")
        return
    st.info("Binary payload preview is intentionally limited. Use download to inspect the original payload.")
    st.code(data[:512].hex(" "))


def _dialog_decorator(title: str):
    if hasattr(st, "dialog"):
        return st.dialog(title, width="large")
    if hasattr(st, "experimental_dialog"):
        return st.experimental_dialog(title)
    return None


_dialog = _dialog_decorator("Preserved payload preview")
if _dialog is not None:
    @_dialog
    def render_object_preview_modal(row: Dict[str, Any]) -> None:
        _render_payload_content(row, modal=True)
else:
    def render_object_preview_modal(row: Dict[str, Any]) -> None:
        st.warning("This Streamlit version does not support dialogs, so the preview is shown inline.")
        _render_payload_content(row, modal=False)


def _filters_key(filters: Dict[str, Sequence[str]]) -> tuple:
    return tuple(sorted((name, tuple(values)) for name, values in filters.items() if values))


def _filter_multiselects(facets: Dict[str, List[str]], defaults: Dict[str, List[str]] | None = None) -> Dict[str, List[str]]:
    defaults = defaults or {}
    with st.expander("Structured filters / facets", expanded=True):
        c1, c2, c3 = st.columns(3)
        filters = {
            "entity_id": c1.multiselect("Entity", facets.get("entity_id", []), default=defaults.get("entity_id", [])),
            "snapshot_id": c2.multiselect("Snapshot", facets.get("snapshot_id", []), default=defaults.get("snapshot_id", [])),
            "risk_rating": c3.multiselect("Risk rating", facets.get("risk_rating", []), default=defaults.get("risk_rating", [])),
            "jurisdiction": c1.multiselect("Jurisdiction", facets.get("jurisdiction", []), default=defaults.get("jurisdiction", [])),
            "category": c2.multiselect("Evidence category", facets.get("category", []), default=defaults.get("category", [])),
            "document_type": c3.multiselect("Document type", facets.get("document_type", []), default=defaults.get("document_type", [])),
            "source_system": c1.multiselect("Source system", facets.get("source_system", []), default=defaults.get("source_system", [])),
            "retention_class": c2.multiselect("Retention class", facets.get("retention_class", []), default=defaults.get("retention_class", [])),
            "legal_hold_status": c3.multiselect("Legal hold", facets.get("legal_hold_status", []), default=defaults.get("legal_hold_status", [])),
            "sensitivity": c1.multiselect("Sensitivity", facets.get("sensitivity", []), default=defaults.get("sensitivity", [])),
            "ocr_source": c2.multiselect("OCR / index source", facets.get("ocr_source", []), default=defaults.get("ocr_source", [])),
            "deletion_eligible": c3.multiselect("Deletion eligible", facets.get("deletion_eligible", []), default=defaults.get("deletion_eligible", [])),
        }
    return filters


def _selectable_dataframe(df: pd.DataFrame, *, key: str, height: int | None = None):
    kwargs: Dict[str, Any] = {"use_container_width": True, "hide_index": True, "key": key}
    if height is not None:
        kwargs["height"] = height
    try:
        return st.dataframe(df, on_select="rerun", selection_mode="single-row", **kwargs), True
    except TypeError:
        kwargs.pop("key", None); st.dataframe(df, **kwargs); return None, False


def _selected_row_index(event: Any) -> int | None:
    try:
        rows = event.selection.rows
    except AttributeError:
        try: rows = event["selection"]["rows"]
        except Exception: rows = []
    return int(rows[0]) if rows else None


def _open_preview_once(row: Dict[str, Any], unique_key: str, *, session_key: str) -> None:
    if st.session_state.get(session_key) != unique_key:
        st.session_state[session_key] = unique_key
        render_object_preview_modal(row)


def dashboard_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    summary = cached_summary(str(root))
    st.subheader("Archive overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Containers", summary["container_count"]); c2.metric("Entities", summary["entity_count"])
    c3.metric("Preserved objects", summary["object_count"]); c4.metric("Container storage", format_bytes(summary["total_container_bytes"]))
    st.caption(f"Index: `{summary['index_path']}`")
    st.divider()
    st.subheader("Demo data, container and index actions")
    col_a, col_b, col_c, col_d = st.columns(4)
    customers = col_a.number_input("Customers", min_value=1, max_value=500, value=3, step=1)
    target_mb = col_b.number_input("Approx. MB per customer", min_value=1, max_value=1024, value=2, step=1)
    seed = col_c.number_input("Seed", min_value=1, max_value=999999, value=42, step=1)
    split_snapshots = col_d.checkbox("Legacy split-snapshot mode", value=False, help="Default is one active FITS file per entity with internal logical snapshots. Enable only to build separate FITS files per snapshot.")
    a1, a2, a3, a4 = st.columns(4)
    if a1.button("Generate sample evidence"):
        with st.spinner("Generating sample evidence..."):
            run_generator(int(customers), int(target_mb), int(seed), root)
        clear_caches(); st.success("Generated.")
    if a2.button("Build FITS containers"):
        with st.spinner("Building FITS containers..."):
            run_build_containers(root, split_snapshots)
        clear_caches(); st.success("Containers built.")
    if a3.button("Rebuild SQLite/FTS index", type="primary"):
        with st.spinner("Rebuilding index from FITS containers..."):
            count = rebuild_index(paths.containers, paths.index)
        clear_caches(); st.success(f"Indexed {count} objects.")
    if a4.button("Build local vector index"):
        with st.spinner("Building local offline vector index..."):
            count = build_vector_index(paths.index, paths.vector)
        cached_vector_search.clear(); st.success(f"Vector indexed {count} objects.")
    st.divider()
    st.subheader("Local LM Studio AI")
    status = lm_studio_status()
    if status.get("available"):
        st.success(f"LM Studio available at {status.get('base_url')}")
        st.caption("Models: " + ", ".join(status.get("models", [])))
        if st.button("Build LM Studio embedding index"):
            with st.spinner("Calling LM Studio embeddings endpoint and building local vector index..."):
                count = build_lmstudio_vector_index(paths.index, paths.lm_vector)
            cached_lmstudio_vector_search.clear(); st.success(f"LM Studio embedding indexed {count} objects.")
    else:
        st.warning("LM Studio is not available. Start LM Studio server on http://127.0.0.1:1234 and refresh.")
        st.caption(status.get("error", ""))
    st.info("Set EEC_OCR_PROVIDER=auto, sidecar, tesseract or none before building containers to control OCR/index extraction. Tesseract requires the native Tesseract executable plus pytesseract.")


def health_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    st.subheader("Archive health and integrity dashboard")
    indexed = indexed_health(paths.index)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Indexed entities", indexed.get("entities", 0)); c2.metric("Indexed containers", indexed.get("containers", 0))
    c3.metric("Indexed objects", indexed.get("objects", 0)); c4.metric("Legal hold objects", indexed.get("legal_hold_objects", 0))
    if st.button("Run full integrity validation", type="primary"):
        with st.spinner("Validating every payload in every FITS container..."):
            health = integrity_health(paths.containers)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Containers", health["container_count"]); c2.metric("Passed", health["passed_containers"]); c3.metric("Failed", health["failed_containers"]); c4.metric("Failed payloads", health["failed_payloads"])
        rows = pd.DataFrame(health["rows"])
        if not rows.empty:
            st.dataframe(rows[["container_name", "entity_id", "status", "checked_payloads", "failed_payloads", "container_size_bytes"]], use_container_width=True, hide_index=True)
        if health["failures"]:
            st.error("Corruption / integrity failures detected")
            st.json(health["failures"])
        else:
            st.success("All containers passed integrity validation.")


def comparison_tab(root: Path) -> None:
    st.subheader("Traditional DMS versus preservation object")
    st.markdown("""
| Area | Traditional DMS | Entity Evidence Container |
|---|---|---|
| Primary source of meaning | Application database, indexes and file links | Self-describing FITS container with embedded manifest and provenance |
| Failure domain | Central database/index corruption can affect many records | Corruption can be detected and isolated at container/payload level |
| Portability | Often vendor/application dependent | Original payloads, metadata and hashes travel together |
| Search | Native DMS database/index | Rebuildable SQLite/FTS and local vector index from containers |
| Long-term preservation | Usually added as a policy/process | Core design principle: manifest, provenance, retention and fixity |
| Best role | Live workflow and collaboration | Durable evidence, regulatory archive, legacy decommissioning, evidence-pack export |

The key architectural proposition is that the database is **an access/index layer**, not the only place where meaning lives. If the index is lost, it can be rebuilt from the preserved containers.
""")
    st.code("Source systems → Entity Evidence Builder → FITS snapshots → Rebuildable indexes → Search / API / evidence packs")


def customers_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    schema_status = get_index_schema_status(paths.index)
    if not schema_status["is_current"]:
        st.error(schema_status["message"]); st.json(schema_status); return
    entities = cached_entities(str(paths.index))
    if not entities:
        st.warning("No entities found. Rebuild the search index first."); return
    st.subheader("Customers / entities")
    entity_df = pd.DataFrame(entities)
    entity_df["payload_size"] = entity_df["payload_bytes"].apply(format_bytes)
    display = entity_df[["entity_id", "display_name", "jurisdiction", "risk_rating", "occupation", "object_count", "payload_size"]]
    event, supported = _selectable_dataframe(display, key="entity-table", height=260)
    idx = _selected_row_index(event) if supported else 0
    if idx is None:
        idx = 0
    selected = entities[idx]["entity_id"]
    st.markdown(f"### Evidence for {selected} — {entities[idx]['display_name']}")
    objects = cached_objects(str(paths.index), selected)
    if not objects:
        st.info("No objects for selected entity."); return
    df = pd.DataFrame(objects)
    cols = ["object_id", "snapshot_id", "category", "document_type", "filename", "retention_class", "retention_until", "legal_hold_status", "sensitivity", "ocr_source", "size_bytes"]
    out = df[[c for c in cols if c in df.columns]].copy(); out["size"] = out["size_bytes"].apply(format_bytes); out = out.drop(columns=["size_bytes"])
    event, supported = _selectable_dataframe(out, key=f"objects-{selected}", height=420)
    object_idx = _selected_row_index(event) if supported else None
    if object_idx is not None:
        row = objects[object_idx]
        _open_preview_once(row, f"customer:{selected}:{row['object_id']}", session_key="last_customer_object_preview")
        if st.button("Open selected preview again"):
            render_object_preview_modal(row)


def _merge_results(primary: list[dict[str, Any]], extra_batches: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for row in primary:
        key = str(row.get("object_id"))
        if key not in seen:
            seen.add(key); merged.append(row)
    for batch in extra_batches:
        for row in batch:
            key = str(row.get("object_id"))
            if key not in seen:
                row = dict(row)
                row["snippet"] = row.get("snippet", "")
                seen.add(key); merged.append(row)
            if len(merged) >= limit:
                return merged
    return merged[:limit]


def _customer_label(entity: Dict[str, Any]) -> str:
    return f"{entity.get('entity_id')} — {entity.get('display_name', '')} · {entity.get('jurisdiction', '')} · {entity.get('risk_rating', '')}"


def _evidence_table(rows: list[dict[str, Any]], *, key: str, height: int = 420):
    df = pd.DataFrame(rows)
    cols = [
        "object_id", "entity_id", "display_name", "snapshot_id", "risk_rating", "jurisdiction",
        "category", "document_type", "filename", "source_system", "retention_class",
        "retention_until", "legal_hold_status", "sensitivity", "ocr_source", "size_bytes",
    ]
    for score_col in ["direct_fits_score", "lmstudio_vector_score", "vector_score", "semantic_score"]:
        if score_col in df.columns:
            cols.insert(3, score_col)
    out = df[[c for c in cols if c in df.columns]].copy()
    if "size_bytes" in out.columns:
        out["size"] = out["size_bytes"].apply(format_bytes)
        out = out.drop(columns=["size_bytes"])
    return _selectable_dataframe(out, key=key, height=height)



def _rows_summary_cache_key(query: str, rows: list[dict[str, Any]]) -> str:
    """Create a stable key for an AI summary over a result set."""
    identity = {
        "query": query,
        "rows": [
            {
                "container_id": row.get("container_id"),
                "snapshot_id": row.get("snapshot_id"),
                "entity_id": row.get("entity_id"),
                "object_id": row.get("object_id"),
                "filename": row.get("filename"),
                "document_type": row.get("document_type"),
                "sha256": row.get("sha256"),
            }
            for row in rows[:25]
        ],
    }
    payload = json.dumps(identity, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render_ai_summary_once(query: str, rows: list[dict[str, Any]], *, state_key: str) -> None:
    """Render an AI summary without recomputing it on dataframe row-selection reruns."""
    if not rows:
        return

    cache_key = _rows_summary_cache_key(query, rows)
    summary_store_key = f"ai_summary::{state_key}"
    summary_store = st.session_state.setdefault(summary_store_key, {})

    st.markdown("### AI evidence summary")

    if cache_key not in summary_store:
        with st.spinner("Summarising retrieved evidence with the local LLM..."):
            summary_store[cache_key] = summarise_search_results(query, rows)

    st.markdown(summary_store[cache_key])

    c1, c2 = st.columns([1, 5])
    if c1.button("Refresh summary", key=f"{summary_store_key}:refresh"):
        summary_store.pop(cache_key, None)
        st.rerun()



def _completeness_summary_cache_key(report: dict[str, Any], rows: list[dict[str, Any]], filters: dict[str, Any]) -> str:
    """Create a stable key for an AI summary over a completeness result set."""
    identity = {
        "summary": report.get("summary", {}),
        "filters": filters,
        "rows": [
            {
                "entity_id": row.get("entity_id"),
                "risk_rating": row.get("risk_rating"),
                "jurisdiction": row.get("jurisdiction"),
                "profile": row.get("profile"),
                "complete": row.get("complete"),
                "missing_evidence": row.get("missing_evidence"),
                "present_evidence": row.get("present_evidence"),
            }
            for row in rows[:50]
        ],
    }
    payload = json.dumps(identity, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render_completeness_ai_summary(report: dict[str, Any], rows: list[dict[str, Any]], filters: dict[str, Any], *, state_key: str) -> None:
    """Render an AI completeness summary without recomputing on dataframe-selection reruns."""
    if not rows:
        return

    st.markdown("### AI completeness summary")
    st.caption("Generated locally from the completeness result set. The checklist and ruleset remain the source of truth.")

    cache_key = _completeness_summary_cache_key(report, rows, filters)
    store_key = f"completeness_ai_summary::{state_key}"
    store = st.session_state.setdefault(store_key, {})

    if cache_key not in store:
        with st.spinner("Summarising completeness findings with the local LLM..."):
            summary_report = {**report, "rows": rows}
            store[cache_key] = summarise_completeness_report(summary_report)

    st.markdown(store[cache_key])

    c1, c2 = st.columns([1, 5])
    if c1.button("Refresh summary", key=f"{store_key}:refresh"):
        store.pop(cache_key, None)
        st.rerun()

def _cached_ai_summary_for_export(query: str, rows: list[dict[str, Any]], state_key: str | None) -> str | None:
    """Return a previously generated AI summary for this result set, if one exists."""
    if not state_key:
        return None
    cache_key = _rows_summary_cache_key(query, rows)
    summary_store = st.session_state.get(f"ai_summary::{state_key}", {})
    if isinstance(summary_store, dict):
        value = summary_store.get(cache_key)
        return str(value) if value else None
    return None


def _render_evidence_actions(
    rows: list[dict[str, Any]],
    *,
    paths,
    query: str,
    key_prefix: str,
    selected_idx: int | None = None,
    structured_query: dict[str, Any] | None = None,
    result_context: dict[str, Any] | None = None,
    ai_summary_state_key: str | None = None,
) -> None:
    st.markdown("### Evidence actions")
    c_export, c_preview, c_validate, c_msg = st.columns([1.5, 1.4, 1.2, 3])
    if c_export.button("Export current evidence pack", type="primary", key=f"{key_prefix}-export"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = paths.exports / f"evidence_results_{timestamp}"
        ai_summary = _cached_ai_summary_for_export(query, rows, ai_summary_state_key)
        export_search_results(
            rows,
            out_dir,
            pack_name=query,
            query=query,
            structured_query=structured_query,
            completeness_report=result_context if (result_context or {}).get("type") == "completeness_report" else None,
            ai_summary=ai_summary,
        )
        st.success(f"Exported {len(rows)} evidence item(s) to {out_dir}")
        st.caption("Pack includes README, query JSON, structured query JSON, manifest, hash report, source-system report, retention/legal-hold report and AI summary where available.")
    if selected_idx is None:
        c_msg.caption("Select an evidence row to preview or ask about it.")
        return
    row = rows[selected_idx]
    _open_preview_once(row, f"{key_prefix}:{row.get('object_id')}", session_key=f"{key_prefix}_last_preview")
    if c_preview.button("Open selected preview again", key=f"{key_prefix}-preview"):
        render_object_preview_modal(row)
    if c_validate.button("Validate container", key=f"{key_prefix}-validate"):
        validation = cached_validate(row["container_path"])
        render_validation_badge(validation["status"])
    c_msg.caption(f"Selected: {row.get('display_name')} / {row.get('filename')}")
    ask = st.text_input("Ask about selected / retrieved evidence", value="", key=f"{key_prefix}-ask")
    if ask and st.button("Ask local LLM", key=f"{key_prefix}-ask-button"):
        try:
            evidence_rows = [row] + [r for i, r in enumerate(rows) if i != selected_idx][:7]
            with st.spinner("Asking the local LLM over retrieved evidence..."):
                st.markdown(answer_question_from_evidence(ask, evidence_rows))
        except Exception as exc:
            st.error(f"Local LLM question failed: {exc}")


def _restore_structured_flags(structured_dict: dict[str, Any]) -> dict[str, Any]:
    """Small helper for rendering persisted structured search state after Streamlit reruns."""
    return {
        "intent": structured_dict.get("intent"),
        "result_type": structured_dict.get("result_type"),
        "requires_summary": bool(structured_dict.get("requires_summary")),
        "requires_evidence": bool(structured_dict.get("requires_evidence", True)),
    }


def _show_customer_evidence_from_search(paths, selected_customer: dict[str, Any], *, query: str) -> None:
    entity_id = selected_customer.get("entity_id")
    if not entity_id:
        return
    st.markdown("### Selected customer evidence")
    st.caption(
        f"{entity_id} — {selected_customer.get('display_name', '')} · "
        f"{selected_customer.get('jurisdiction', '')} · {selected_customer.get('risk_rating', '')}"
    )
    try:
        customer_rows = list_objects_for_entity(paths.index, entity_id)
    except Exception as exc:
        st.warning(f"Could not load customer evidence: {exc}")
        return
    if not customer_rows:
        st.info("No indexed evidence was found for the selected customer.")
        return
    event, supported = _evidence_table(customer_rows, key=f"search-customer-evidence-{entity_id}", height=360)
    evidence_idx = _selected_row_index(event) if supported else None
    _render_evidence_actions(
        customer_rows,
        paths=paths,
        query=query or f"Evidence for {entity_id}",
        key_prefix=f"search-customer-evidence-{entity_id}",
        selected_idx=evidence_idx,
    )


def search_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    st.subheader("Search the Evidence Archive")
    schema_status = get_index_schema_status(paths.index)
    if not schema_status["is_current"]:
        st.error(schema_status["message"])
        st.json(schema_status)
        return

    state_key = f"intent_search_state::{paths.root.resolve()}"

    entities = cached_entities(str(paths.index))
    entity_options = {"": "No selected customer"}
    entity_options.update({entity["entity_id"]: _customer_label(entity) for entity in entities})

    basic_mode = is_basic_mode()
    if basic_mode:
        st.markdown(
            "Ask a business question, select a customer when needed, and the archive will return "
            "the relevant evidence, checklist or customer list."
        )
    else:
        st.markdown(
            "Ask in natural language. The app interprets the request into a controlled structured query, "
            "executes deterministic filters/search, and only then uses the local LLM to summarise retrieved evidence."
        )

    # Keep selected customer stable across reruns and row clicks.
    if "search_scope" not in st.session_state:
        st.session_state["search_scope"] = "All customers"
    if "search_selected_entity_id" not in st.session_state:
        st.session_state["search_selected_entity_id"] = ""

    c_scope, c_customer = st.columns([1, 2])
    scope = c_scope.radio(
        "Scope",
        ["All customers", "Selected customer"],
        horizontal=True,
        key="search_scope",
    )

    selected_entity_id: str | None = None
    entity_ids = list(entity_options.keys())[1:]
    if scope == "Selected customer":
        current_entity = st.session_state.get("search_selected_entity_id") or (entity_ids[0] if entity_ids else "")
        if current_entity not in entity_ids and entity_ids:
            current_entity = entity_ids[0]
        selected_entity_id = c_customer.selectbox(
            "Customer",
            options=entity_ids,
            format_func=lambda value: entity_options.get(value, value),
            index=entity_ids.index(current_entity) if current_entity in entity_ids else 0,
            key="search_selected_entity_id",
        )
    else:
        c_customer.caption("Searching across all indexed customer evidence.")
        st.session_state["search_selected_entity_id"] = st.session_state.get("search_selected_entity_id", "")

    if basic_mode:
        if scope == "Selected customer":
            st.caption("Use this for questions about one customer, such as source of wealth, onboarding completeness, or held evidence.")
        else:
            st.caption("Use this for portfolio questions, such as high-risk customers, missing evidence, or cohort evidence requests.")

    examples = {
        "Customer source of wealth": "What is the customer's source of wealth?",
        "High-risk customers": "Show me customers who are high risk",
        "High-risk Guernsey customers": "Show me customers in Guernsey who are high risk",
        "CDD for high-risk Guernsey customers": "Show me the CDD for customers in Guernsey who are high risk",
        "Legal hold review": "Show me documents past retention date but blocked by legal hold",
        "Regulatory pack": "Prepare evidence for high-risk Guernsey customers showing CDD, source of wealth and screening evidence",
    }
    if basic_mode:
        quick_examples = {
            "Ask about selected customer source of wealth": "What is the customer's source of wealth?",
            "Check selected customer onboarding completeness": "Is this customer's onboarding file complete?",
            "Find high-risk customers": "Show me customers who are high risk",
            "Find high-risk Guernsey customers": "Show me customers in Guernsey who are high risk",
            "Find missing proof of address": "Show me customers who are high risk and do not have proof of address",
            "Retrieve cohort onboarding evidence": "Show me all onboarding documentation for high risk clients in Guernsey",
        }
        example_name = st.selectbox("Quick examples", ["Custom"] + list(quick_examples.keys()), key="search_example")
        default_query = quick_examples.get(
            example_name,
            "What is the customer's source of wealth?" if scope == "Selected customer" else "Show me customers who are high risk",
        )
    else:
        example_name = st.selectbox("Example requests", ["Custom"] + list(examples.keys()), key="search_example")
        default_query = examples.get(
            example_name,
            "What is the customer's source of wealth?" if scope == "Selected customer" else "Show me customers who are high risk",
        )

    # Do not overwrite the user's text on every rerun caused by table selection.
    if "search_query_text" not in st.session_state or example_name != st.session_state.get("search_last_example"):
        st.session_state["search_query_text"] = default_query
        st.session_state["search_last_example"] = example_name

    query = st.text_area(
        "What would you like to find?" if basic_mode else "Ask a question or request evidence",
        height=72 if basic_mode else 88,
        key="search_query_text",
        placeholder="For example: What is the customer's source of wealth?",
    )

    if basic_mode:
        defaults = basic_defaults_for_search()
        use_local_ai = defaults["use_local_ai"]
        include_summary = defaults["include_summary"]
        use_direct_fits = defaults["use_direct_fits"]
        show_interpreted = defaults["show_interpreted"]
        limit = defaults["limit"]
        status = defaults["status"]
        with st.expander("How this search will run", expanded=False):
            st.write("The app will interpret the question, apply controlled filters, search the relevant FITS containers/indexes, and summarise evidence where useful.")
            st.caption("Selected-customer evidence searches use the customer FITS file directly. Portfolio searches use the rebuildable index for speed.")
            if status.get("available"):
                st.success("Local AI is available for interpretation and summaries.")
            else:
                st.info("Local AI is unavailable, so deterministic query interpretation will be used.")
    else:
        with st.expander("Advanced options", expanded=False):
            status = lm_studio_status()
            if status.get("available"):
                st.success(f"LM Studio available: {status.get('base_url')}")
                st.caption(f"Query model: {status.get('query_model')} · Chat model: {status.get('chat_model')} · Embedding model: {status.get('embedding_model')}")
            else:
                st.warning("LM Studio is not currently available. The app will use deterministic rule-based interpretation.")
                st.caption(status.get("error", ""))
            use_local_ai = st.checkbox("Interpret natural language locally", value=status.get("available", False), disabled=not status.get("available"), key="search_use_local_ai")
            include_summary = st.checkbox("Generate AI evidence summary when relevant", value=status.get("available", False), disabled=not status.get("available"), key="search_include_summary")
            use_direct_fits = st.checkbox("Use direct FITS search for selected-customer evidence queries", value=True, key="search_use_direct_fits")
            st.caption("Direct FITS search opens the selected customer/entity FITS file and searches its manifest/OCR/metadata tables without using SQLite. Cross-customer searches still use the rebuildable index.")
            show_interpreted = st.checkbox("Show interpreted structured query", value=True, key="search_show_interpreted")
            limit = st.slider("Result limit", min_value=5, max_value=250, value=50, step=5, key="search_limit")
            with st.expander("Supported query capabilities", expanded=False):
                matrix = query_capability_matrix()
                st.dataframe(
                    pd.DataFrame([
                        {
                            "capability": key,
                            "intent": value.get("intent"),
                            "result_type": value.get("result_type"),
                            "requires_selected_customer": value.get("requires_selected_entity"),
                            "filters": ", ".join(value.get("supports_filters", [])),
                            "description": value.get("description"),
                        }
                        for key, value in matrix.items()
                    ]),
                    use_container_width=True,
                    hide_index=True,
                    height=280,
                )
            if st.button("Clear last search result", key="search_clear_state"):
                st.session_state.pop(state_key, None)
                for key in list(st.session_state.keys()):
                    if key.startswith(f"ai_summary::{state_key}"):
                        st.session_state.pop(key, None)
                st.rerun()

    c_search, c_clear = st.columns([1, 1])
    search_clicked = c_search.button("Search", type="primary", key="intent_search_button")
    if basic_mode and c_clear.button("Clear", key="intent_search_clear_basic"):
        st.session_state.pop(state_key, None)
        for key in list(st.session_state.keys()):
            if key.startswith(f"ai_summary::{state_key}"):
                st.session_state.pop(key, None)
        st.rerun()

    if search_clicked:
        structured = interpret_archive_query(
            query,
            selected_entity_id=selected_entity_id,
            use_local_ai=use_local_ai,
            limit=limit,
        )
        if include_summary and (
            structured.result_type in {"evidence", "evidence_grouped_by_customer", "completeness_report"}
            or structured.intent == "evidence_completeness_review"
        ):
            structured.requires_summary = True

        result = execute_structured_query(paths.index, structured)

        # For selected-customer evidence questions/retrieval, prefer direct FITS search.
        # This proves that the customer archive object is self-describing and searchable
        # without relying on the rebuildable SQLite/FTS index.
        if (
            use_direct_fits
            and selected_entity_id
            and structured.result_type == "evidence"
            and structured.intent in {"customer_evidence_question", "customer_evidence_retrieval", "general_archive_search"}
        ):
            try:
                direct_rows = cached_direct_fits_search(
                    str(paths.containers),
                    selected_entity_id,
                    structured.semantic_query or structured.raw_query or query,
                    structured.to_dict(),
                    structured.limit,
                )
                result = {
                    "type": "evidence",
                    "rows": direct_rows,
                    "grouped": None,
                    "search_source": "direct_fits",
                    "source_note": f"Searched {selected_entity_id}.fits directly. SQLite/vector indexes were not used for this result set.",
                }
            except Exception as exc:
                result["source_note"] = f"Direct FITS search failed, falling back to rebuilt index: {exc}"

        for key in list(st.session_state.keys()):
            if key.startswith(f"ai_summary::{state_key}"):
                st.session_state.pop(key, None)
        st.session_state[state_key] = {
            "query": query,
            "structured": structured.to_dict(),
            "result": result,
            "selected_entity_id": selected_entity_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    elif state_key not in st.session_state:
        st.info("Choose a scope, enter a request, then click Search." if basic_mode else "Choose a scope, enter a request, then click Search evidence archive.")
        return

    search_state = st.session_state.get(state_key)
    if not search_state:
        return

    query = search_state.get("query", query)
    structured_dict = search_state.get("structured", {})
    structured_flags = _restore_structured_flags(structured_dict)
    result = search_state.get("result", {})

    if not basic_mode:
        st.caption(f"Showing last search result from {search_state.get('created_at', 'this session')}. Row selections will not reset this result.")

    if show_interpreted:
        with st.expander("Interpreted request", expanded=True):
            capability_id = structured_dict.get("capability") or structured_dict.get("intent")
            capability = query_capability_matrix().get(capability_id or "", {})
            if capability:
                st.info(f"Capability: {capability_id} — {capability.get('description', '')}")
            st.json(structured_dict)

    result_type = result.get("type")
    if result.get("source_note"):
        if basic_mode:
            st.caption(result.get("source_note"))
        else:
            st.info(result.get("source_note"))
    rows: list[dict[str, Any]] = result.get("rows") or []

    if result_type == "customers":
        st.markdown(f"### Customers found: {len(rows)}")
        if not rows:
            st.info("No customers matched the request.")
            return
        df = pd.DataFrame(rows)
        display_cols = ["entity_id", "display_name", "jurisdiction", "risk_rating", "occupation", "evidence_count", "last_evidence_date", "payload_bytes"]
        out = df[[c for c in display_cols if c in df.columns]].copy()
        if "payload_bytes" in out.columns:
            out["payload_size"] = out["payload_bytes"].apply(format_bytes)
            out = out.drop(columns=["payload_bytes"])
        event, supported = _selectable_dataframe(out, key="structured-customers", height=420)
        selected_idx = _selected_row_index(event) if supported else None
        if selected_idx is not None:
            selected_customer = rows[selected_idx]
            selected_customer_id = selected_customer.get("entity_id")
            st.session_state["search_selected_entity_id"] = selected_customer_id or ""
            st.success(f"Selected {selected_customer_id} — evidence is shown below. You can also switch scope to Selected customer and ask a follow-up question.")
            _show_customer_evidence_from_search(paths, selected_customer, query=query)
        else:
            st.caption("Select a customer row to view its indexed evidence without leaving the Search tab.")
        return

    if result_type == "completeness_report":
        summary = result.get("summary", {})
        st.markdown(f"### Evidence completeness results: {len(rows)} customer(s)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Evaluated", summary.get("customers_evaluated", len(rows)))
        c2.metric("Complete", summary.get("complete_customers", 0))
        c3.metric("Incomplete", summary.get("incomplete_customers", 0))
        c4.metric("Missing items", summary.get("total_missing_items", 0))

        if rows and structured_flags["requires_summary"]:
            try:
                _render_completeness_ai_summary(
                    {
                        "summary": summary,
                        "ruleset": result.get("ruleset", {}),
                        "rows": rows,
                        "source": "search",
                        "query": query,
                    },
                    rows,
                    filters={
                        "query": query,
                        "entity_id": structured_dict.get("entity_id"),
                        "risk_rating": structured_dict.get("risk_rating"),
                        "jurisdiction": structured_dict.get("jurisdiction"),
                        "document_type": structured_dict.get("document_type"),
                        "capability": structured_dict.get("capability"),
                    },
                    state_key=f"{state_key}:search-completeness",
                )
            except Exception as exc:
                st.warning(f"Local AI completeness summary unavailable: {exc}")

        if not rows:
            st.info("No customer completeness findings matched the request.")
            return
        display_rows = [{
            "entity_id": row.get("entity_id"),
            "display_name": row.get("display_name"),
            "risk_rating": row.get("risk_rating"),
            "jurisdiction": row.get("jurisdiction"),
            "profile": row.get("profile"),
            "complete": "Yes" if row.get("complete") else "No",
            "present": f"{row.get('present_count', 0)}/{row.get('required_count', 0)}",
            "missing_count": row.get("missing_count", 0),
            "missing_evidence": ", ".join(row.get("missing_evidence") or []),
        } for row in rows]
        event, supported = _selectable_dataframe(pd.DataFrame(display_rows), key="structured-completeness", height=420)
        idx = _selected_row_index(event) if supported else None
        if idx is not None:
            selected = rows[idx]
            st.markdown(f"### Checklist for {selected.get('entity_id')} — {selected.get('display_name')}")
            _render_checklist(selected)
        return

    if result_type == "retention_report":
        st.markdown(f"### Retention / legal hold findings: {len(rows)}")
        if not rows:
            st.info("No retention or legal-hold records matched the request.")
            return
        event, supported = _evidence_table(rows, key="structured-retention", height=420)
        idx = _selected_row_index(event) if supported else None
        _render_evidence_actions(
            rows,
            paths=paths,
            query=query,
            key_prefix="structured-retention",
            selected_idx=idx,
            structured_query=structured_dict,
            result_context=result,
        )
        return

    if result_type == "evidence_grouped_by_customer":
        grouped = result.get("grouped") or {}
        st.markdown(f"### Evidence grouped by customer: {len(rows)} item(s) across {len(grouped)} customer(s)")
        if not rows:
            st.info("No evidence matched the request.")
            return
        if structured_flags["requires_summary"]:
            try:
                _render_ai_summary_once(query, rows, state_key=f"{state_key}:grouped")
            except Exception as exc:
                st.warning(f"AI summary failed: {exc}")
        all_table_event, supported = _evidence_table(rows, key="structured-grouped-all", height=320)
        idx = _selected_row_index(all_table_event) if supported else None
        _render_evidence_actions(
            rows,
            paths=paths,
            query=query,
            key_prefix="structured-grouped",
            selected_idx=idx,
            structured_query=structured_dict,
            result_context=result,
            ai_summary_state_key=f"{state_key}:grouped",
        )
        st.markdown("### Customer groups")
        for entity_id, group_rows in grouped.items():
            first = group_rows[0]
            with st.expander(f"{entity_id} — {first.get('display_name', '')} · {first.get('jurisdiction', '')} · {first.get('risk_rating', '')} · {len(group_rows)} evidence item(s)"):
                group_df = pd.DataFrame(group_rows)
                cols = ["snapshot_id", "category", "document_type", "filename", "source_system", "retention_class", "legal_hold_status", "sensitivity"]
                group_event, group_supported = _selectable_dataframe(
                    group_df[[c for c in cols if c in group_df.columns]],
                    key=f"structured-group-{entity_id}",
                    height=220,
                )
                group_idx = _selected_row_index(group_event) if group_supported else None
                if group_idx is not None:
                    row = group_rows[group_idx]
                    render_object_preview_modal(row)
        return

    # Default: evidence result, generally customer-specific Q&A or general evidence retrieval.
    st.markdown(f"### Evidence found: {len(rows)} item(s)")
    if not rows:
        st.info("No evidence matched the request.")
        return

    if structured_flags["requires_summary"]:
        try:
            _render_ai_summary_once(query, rows, state_key=f"{state_key}:evidence")
        except Exception as exc:
            st.warning(f"AI summary failed: {exc}")

    event, supported = _evidence_table(rows, key="structured-evidence", height=420)
    idx = _selected_row_index(event) if supported else None
    _render_evidence_actions(
        rows,
        paths=paths,
        query=query,
        key_prefix="structured-evidence",
        selected_idx=idx,
        structured_query=structured_dict,
        result_context=result,
        ai_summary_state_key=f"{state_key}:evidence",
    )


def _selected_ruleset(root: Path, key: str = "ruleset-select") -> EvidenceRuleset:
    ensure_rulesets(root)
    rulesets = load_rulesets(root)
    selected_id = st.selectbox(
        "Ruleset",
        options=[ruleset.ruleset_id for ruleset in rulesets],
        format_func=lambda ruleset_id: next((ruleset.name for ruleset in rulesets if ruleset.ruleset_id == ruleset_id), ruleset_id),
        key=key,
    )
    return next((ruleset for ruleset in rulesets if ruleset.ruleset_id == selected_id), rulesets[0])


def _render_checklist(row: dict[str, Any]) -> None:
    checklist = row.get("checklist") or []
    if not checklist:
        st.info("No checklist details are available for this row.")
        return
    check_df = pd.DataFrame([
        {
            "status": "✅ Present" if item.get("present") else "❌ Missing",
            "required_evidence": item.get("required_evidence"),
            "matches": item.get("match_count", 0),
            "matching_files": ", ".join(item.get("matching_filenames") or []),
        }
        for item in checklist
    ])
    st.dataframe(check_df, use_container_width=True, hide_index=True, height=280)


def evidence_completeness_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    st.subheader("Evidence completeness")
    schema_status = get_index_schema_status(paths.index)
    if not schema_status["is_current"]:
        st.error(schema_status["message"])
        return

    ruleset = _selected_ruleset(root, key="completeness-ruleset")
    facets = cached_facets(str(paths.index))
    entities = cached_entities(str(paths.index))
    entity_options = [""] + [entity["entity_id"] for entity in entities]

    c1, c2, c3, c4 = st.columns(4)
    risk = c1.selectbox("Risk rating", options=[""] + facets.get("risk_rating", []), key="completeness-risk") or None
    jurisdiction = c2.selectbox("Jurisdiction", options=[""] + facets.get("jurisdiction", []), key="completeness-jurisdiction") or None
    entity_id = c3.selectbox("Customer", options=entity_options, format_func=lambda value: value or "All customers", key="completeness-entity") or None
    missing_only = c4.checkbox("Only incomplete", value=True, key="completeness-missing-only")

    with st.expander("AI summary options", expanded=False):
        enable_ai_summary = st.checkbox("Generate local AI completeness summary", value=True, key="completeness-ai-summary-enabled")
        st.caption("The summary is generated from the completeness report only. It does not replace the checklist or ruleset output.")

    report = evaluate_completeness(
        paths.index,
        root=root,
        ruleset_id=ruleset.ruleset_id,
        entity_id=entity_id,
        risk_rating=risk,
        jurisdiction=jurisdiction,
    )
    rows = report.get("rows", [])
    if missing_only:
        rows = [row for row in rows if not row.get("complete")]

    summary = report.get("summary", {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Customers evaluated", summary.get("customers_evaluated", 0))
    m2.metric("Complete", summary.get("complete_customers", 0))
    m3.metric("Incomplete", summary.get("incomplete_customers", 0))
    m4.metric("Missing evidence items", summary.get("total_missing_items", 0))

    st.caption("Completeness is calculated from the preserved evidence index. The database/search layer can be rebuilt from the FITS containers.")

    if enable_ai_summary and rows:
        try:
            _render_completeness_ai_summary(
                {**report, "rows": rows},
                rows,
                filters={
                    "ruleset_id": ruleset.ruleset_id,
                    "risk_rating": risk,
                    "jurisdiction": jurisdiction,
                    "entity_id": entity_id,
                    "missing_only": missing_only,
                },
                state_key="completeness-tab",
            )
        except Exception as exc:
            st.warning(f"Local AI completeness summary unavailable: {exc}")

    if not rows:
        st.success("No incomplete customer files matched the current filters." if missing_only else "No customers matched the current filters.")
        return

    display_rows = []
    for row in rows:
        display_rows.append({
            "entity_id": row.get("entity_id"),
            "display_name": row.get("display_name"),
            "risk_rating": row.get("risk_rating"),
            "jurisdiction": row.get("jurisdiction"),
            "profile": row.get("profile"),
            "complete": "Yes" if row.get("complete") else "No",
            "present": f"{row.get('present_count', 0)}/{row.get('required_count', 0)}",
            "missing_count": row.get("missing_count", 0),
            "missing_evidence": ", ".join(row.get("missing_evidence") or []),
        })
    event, supported = _selectable_dataframe(pd.DataFrame(display_rows), key="completeness-table", height=420)
    selected_idx = _selected_row_index(event) if supported else None

    c_export, c_note = st.columns([1, 3])
    if c_export.button("Export completeness report", key="completeness-export"):
        export_report = {**report, "rows": rows}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = export_completeness_report(export_report, paths.exports / f"completeness_report_{timestamp}")
        st.success(f"Exported completeness report to {out}")
    c_note.caption("Select a row to view the detailed required-evidence checklist.")

    if selected_idx is not None:
        selected = rows[selected_idx]
        st.markdown(f"### Checklist for {selected.get('entity_id')} — {selected.get('display_name')}")
        st.caption(f"Profile: {selected.get('profile')} · Ruleset: {selected.get('ruleset_name')} · Risk: {selected.get('risk_rating')} · Jurisdiction: {selected.get('jurisdiction')}")
        _render_checklist(selected)
        try:
            customer_rows = list_objects_for_entity(paths.index, selected.get("entity_id"))
            with st.expander("Show available customer evidence", expanded=False):
                event2, supported2 = _evidence_table(customer_rows, key=f"completeness-evidence-{selected.get('entity_id')}", height=320)
                evidence_idx = _selected_row_index(event2) if supported2 else None
                _render_evidence_actions(
                    customer_rows,
                    paths=paths,
                    query=f"Evidence completeness for {selected.get('entity_id')}",
                    key_prefix=f"completeness-evidence-{selected.get('entity_id')}",
                    selected_idx=evidence_idx,
                )
        except Exception as exc:
            st.warning(f"Could not load customer evidence: {exc}")


def ruleset_builder_tab(root: Path) -> None:
    st.subheader("Ruleset builder")
    st.markdown("Define the evidence expected for each customer profile. The completeness engine uses these rules to identify missing mandatory evidence.")
    ensure_rulesets(root)
    rulesets = load_rulesets(root)

    selected_id = st.selectbox(
        "Ruleset to edit",
        options=[ruleset.ruleset_id for ruleset in rulesets],
        format_func=lambda ruleset_id: next((ruleset.name for ruleset in rulesets if ruleset.ruleset_id == ruleset_id), ruleset_id),
        key="ruleset-builder-selected",
    )
    ruleset = next((item for item in rulesets if item.ruleset_id == selected_id), rulesets[0])

    c1, c2 = st.columns([1, 2])
    new_id = c1.text_input("Ruleset ID", value=ruleset.ruleset_id, key="ruleset-id")
    new_name = c2.text_input("Ruleset name", value=ruleset.name, key="ruleset-name")
    new_description = st.text_area("Description", value=ruleset.description, height=80, key="ruleset-description")

    st.markdown("### Customer profiles and required evidence")
    profile_rows = []
    for profile in ruleset.profiles:
        profile_rows.append({
            "profile": profile.profile,
            "customer_type": profile.customer_type,
            "risk_rating": profile.risk_rating or "",
            "jurisdiction": profile.jurisdiction or "",
            "required_evidence": ", ".join(profile.required_evidence),
        })
    edited = st.data_editor(
        pd.DataFrame(profile_rows),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="ruleset-editor",
        column_config={
            "required_evidence": st.column_config.TextColumn(
                "required_evidence",
                help="Comma-separated list of required evidence items, for example: Application, Passport / ID, Proof of Address",
                width="large",
            )
        },
    )

    with st.expander("Default profile template", expanded=False):
        st.table(pd.DataFrame([
            {"Customer profile": profile, "Required evidence": ", ".join(required)}
            for profile, required in DEFAULT_REQUIRED_EVIDENCE.items()
        ]))

    c_save, c_reset, c_path = st.columns([1, 1, 3])
    if c_save.button("Save ruleset", type="primary", key="ruleset-save"):
        profiles = []
        for _, row in edited.fillna("").iterrows():
            required = [item.strip() for item in str(row.get("required_evidence", "")).split(",") if item.strip()]
            if not str(row.get("profile", "")).strip():
                continue
            profiles.append(EvidenceRuleProfile(
                profile=str(row.get("profile", "")).strip(),
                customer_type=str(row.get("customer_type", "Individual")).strip() or "Individual",
                risk_rating=str(row.get("risk_rating", "")).strip() or None,
                jurisdiction=str(row.get("jurisdiction", "")).strip() or None,
                required_evidence=required,
            ))
        updated = EvidenceRuleset(
            ruleset_id=new_id.strip() or ruleset.ruleset_id,
            name=new_name.strip() or ruleset.name,
            description=new_description.strip(),
            profiles=profiles,
        )
        other_rulesets = [item for item in rulesets if item.ruleset_id != selected_id]
        path = save_rulesets(root, [*other_rulesets, updated])
        st.success(f"Saved ruleset to {path}")
        st.rerun()

    if c_reset.button("Reset to default", key="ruleset-reset"):
        path = save_rulesets(root, [default_ruleset()])
        st.success(f"Reset rulesets to default at {path}")
        st.rerun()

    c_path.caption(f"Rulesets file: `{root / 'config' / 'evidence_rulesets.json'}`")


def ingestion_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    st.subheader("Ingestion")
    st.caption("Import historical evidence in bulk, or process continuous update events from source systems. Imported files are normalised into the source archive structure with metadata sidecars, then built into FITS containers and indexed.")
    st.info(
        "Current archive target: "
        f"source `{paths.source}` · containers `{paths.containers}` · index `{paths.index}`"
    )

    reports_dir = paths.root / "ingestion" / "reports"
    queue_dir_default = paths.root / "ingestion" / "queue"

    with st.expander("Bulk ingestion — historical customer folders / legacy exports", expanded=True):
        input_path = st.text_input("Bulk input folder", value=str(paths.root / "ingestion_demo" / "legacy_export"), key="bulk-ingest-input")
        manifest_path = st.text_input("Optional CSV/JSON manifest", value=str(paths.root / "ingestion_demo" / "legacy_export" / "bulk_manifest.csv"), key="bulk-ingest-manifest")
        c1, c2, c3 = st.columns(3)
        default_jurisdiction = c1.text_input("Default jurisdiction", value="Guernsey", key="bulk-default-jurisdiction")
        default_risk = c2.selectbox("Default risk rating", options=["Low", "Medium", "High"], index=1, key="bulk-default-risk")
        overwrite = c3.checkbox("Overwrite existing files", value=True, key="bulk-overwrite")
        st.caption("Without a manifest, the importer treats each top-level folder as a customer and infers evidence metadata from folder/file names.")
        if st.button("Run bulk ingestion", type="primary", key="bulk-ingest-run"):
            try:
                manifest = Path(manifest_path) if manifest_path.strip() and Path(manifest_path).exists() else None
                report = bulk_ingest(
                    Path(input_path),
                    paths.source,
                    manifest=manifest,
                    defaults={"jurisdiction": default_jurisdiction, "risk_rating": default_risk},
                    overwrite=overwrite,
                )
                report_path = reports_dir / f"{report.run_id}.json"
                write_ingestion_report(report, report_path)
                clear_caches()
                st.success(f"Bulk ingestion complete: {report.ingested_items} ingested, {report.skipped_items} skipped, {report.failed_items} failed")
                st.caption(f"Report: `{report_path}`")
                st.json(report.to_dict())
            except Exception as exc:
                st.error(f"Bulk ingestion failed: {exc}")

    with st.expander("Continuous ingestion — event queue", expanded=True):
        queue_path = st.text_input("Event queue folder", value=str(queue_dir_default), key="continuous-queue")
        st.caption("Each JSON event should identify an entity and a file_path to ingest, together with source_system, category/document_type and optional retention metadata.")
        if st.button("Process event queue", type="primary", key="process-event-queue"):
            try:
                report = process_event_queue(Path(queue_path), paths.source)
                report_path = reports_dir / f"{report.run_id}.json"
                write_ingestion_report(report, report_path)
                clear_caches()
                st.success(f"Queue processed: {report.ingested_items} ingested, {report.skipped_items} skipped, {report.failed_items} failed")
                st.caption(f"Report: `{report_path}`")
                st.json(report.to_dict())
            except Exception as exc:
                st.error(f"Event queue processing failed: {exc}")

    with st.expander("Post-ingestion rebuild", expanded=True):
        st.caption("After ingestion, rebuild FITS containers and indexes so the new evidence becomes searchable.")
        st.caption(f"Rebuild source: `{paths.source}`")
        st.caption(f"Rebuild containers: `{paths.containers}`")
        st.caption(f"Rebuild index: `{paths.index}`")
        split_snapshots = st.checkbox("Legacy split-snapshot mode", value=False, key="ingest-snapshot-build", help="Default rebuilds one active FITS file per entity with internal snapshots.")
        build_lmstudio = st.checkbox("Also rebuild LM Studio embedding index", value=False, key="ingest-lmstudio-build")
        if st.button("Rebuild containers and indexes", type="primary", key="ingest-rebuild"):
            try:
                paths.containers.mkdir(parents=True, exist_ok=True)
                paths.index.parent.mkdir(parents=True, exist_ok=True)
                run_build_containers(root, split_snapshots=split_snapshots)
                count = rebuild_index(paths.containers, paths.index)
                st.success(f"Rebuilt SQLite index with {count} objects")
                try:
                    vector_count = build_vector_index(paths.index, paths.vector)
                    st.success(f"Rebuilt local vector index with {vector_count} objects")
                except Exception as exc:
                    st.warning(f"Local vector index rebuild skipped/failed: {exc}")
                if build_lmstudio:
                    lm_count = build_lmstudio_vector_index(paths.index, paths.lm_vector)
                    st.success(f"Rebuilt LM Studio vector index with {lm_count} objects")
                clear_caches()
            except Exception as exc:
                st.error(f"Rebuild failed: {exc}")

    with st.expander("Recent ingestion reports", expanded=False):
        if not reports_dir.exists():
            st.info("No ingestion reports yet.")
        else:
            reports = sorted(reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
            if not reports:
                st.info("No ingestion reports yet.")
            for report in reports:
                with st.expander(report.name):
                    try:
                        st.json(json.loads(report.read_text(encoding="utf-8")))
                    except Exception:
                        st.text(report.read_text(encoding="utf-8", errors="replace"))



def extraction_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    st.subheader("OCR and structured extraction")
    st.markdown(
        "The FITS containers preserve original payloads plus OCR/search text, extracted fields and extraction events. "
        "The rebuilt indexes accelerate discovery, but the extraction artefacts are also embedded in the FITS files."
    )

    report = extraction_dashboard(paths.index)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Indexed objects", report.get("object_count", 0))
    c2.metric("With searchable text", report.get("with_search_text", 0))
    c3.metric("With extracted fields", report.get("with_extracted_fields", 0))
    c4.metric("Low confidence", report.get("low_confidence_objects", 0))

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### OCR / extraction sources")
        sources = pd.DataFrame(report.get("ocr_sources", []))
        if sources.empty:
            st.info("No OCR/index source data found. Rebuild containers and index.")
        else:
            st.dataframe(sources, use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("#### Extracted field counts")
        field_counts = report.get("field_counts", {}) or {}
        if not field_counts:
            st.info("No extracted fields found yet.")
        else:
            fields_df = pd.DataFrame([{"field_name": k, "count": v} for k, v in sorted(field_counts.items(), key=lambda kv: (-kv[1], kv[0]))])
            st.dataframe(fields_df, use_container_width=True, hide_index=True, height=280)

    low_rows = report.get("low_confidence_rows", [])
    with st.expander("Low-confidence extraction rows", expanded=bool(low_rows)):
        if low_rows:
            st.dataframe(pd.DataFrame(low_rows), use_container_width=True, hide_index=True, height=320)
        else:
            st.success("No low-confidence extraction rows in the current index.")

    st.divider()
    st.markdown("### Per-customer extracted fields")
    entities = cached_entities(str(paths.index)) if paths.index.exists() else []
    if not entities:
        st.info("No indexed entities found. Rebuild the index first.")
    else:
        selected_entity = st.selectbox(
            "Customer / entity",
            options=[e["entity_id"] for e in entities],
            format_func=lambda entity_id: next((f"{e['entity_id']} — {e.get('display_name', '')}" for e in entities if e["entity_id"] == entity_id), entity_id),
            key="extraction-entity-select",
        )
        field_rows = extracted_fields_for_entity(paths.index, selected_entity)
        if not field_rows:
            st.info("No extracted fields for this entity.")
        else:
            field_df = pd.DataFrame(field_rows)
            visible_cols = [
                "object_id", "snapshot_id", "category", "document_type", "filename", "ocr_source",
                "extraction_confidence", "field_name", "field_value", "field_type", "field_confidence", "source_system",
            ]
            st.dataframe(field_df[[c for c in visible_cols if c in field_df.columns]], use_container_width=True, hide_index=True, height=420)

    st.divider()
    st.markdown("### FITS-level extraction inspection")
    containers = sorted(paths.containers.glob("*.fits"))
    if not containers:
        st.info("No FITS containers found.")
        return
    selected_container = st.selectbox("Container", options=containers, format_func=lambda p: p.name, key="extraction-container-select")
    if st.button("Inspect extraction HDUs", key="inspect-extraction-hdus"):
        container_report = extraction_report_for_container(selected_container)
        st.json({k: v for k, v in container_report.items() if k not in {"fields", "events"}})
        with st.expander("Extracted fields embedded in FITS", expanded=True):
            fields = container_report.get("fields", [])
            st.dataframe(pd.DataFrame(fields), use_container_width=True, hide_index=True) if fields else st.info("No extracted fields HDU rows.")
        with st.expander("Extraction events embedded in FITS", expanded=False):
            events = container_report.get("events", [])
            st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True) if events else st.info("No extraction event HDU rows.")

def retention_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    st.subheader("Retention and legal hold")
    report = retention_report(paths.index)
    summary = report.get("summary", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Objects", summary.get("total_objects", 0)); c2.metric("Expired retention", summary.get("expired_retention", 0))
    c3.metric("Legal hold", summary.get("legal_hold", 0)); c4.metric("Deletion eligible", summary.get("deletion_eligible", 0))
    rows = report.get("rows", [])
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df[["entity_id", "display_name", "risk_rating", "snapshot_id", "filename", "retention_class", "retention_until", "legal_hold_status", "deletion_eligible", "sensitivity"]], use_container_width=True, hide_index=True, height=420)
    with st.expander("Legal hold objects"):
        st.dataframe(pd.DataFrame(report.get("legal_hold", [])), use_container_width=True, hide_index=True)


def integrity_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    st.subheader("Integrity and corruption detection")
    containers = sorted(paths.containers.glob("*.fits"))
    if not containers:
        st.warning("No containers found. Build containers first."); return
    selected_container = st.selectbox("Container", options=containers, format_func=lambda p: p.name)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Validate selected container", type="primary"):
            result = validate_container(selected_container).to_dict(); render_validation_badge(result["status"]); st.json(result)
    with col2:
        object_index = st.number_input("Object index to corrupt", min_value=1, max_value=9999, value=3, step=1)
        if st.button("Create corrupted copy"):
            output = selected_container.with_name(selected_container.stem + "-ui-corrupt.fits")
            corrupt_container(selected_container, output, int(object_index)); clear_caches(); st.warning(f"Created corrupted copy: {output.name}")


def export_tab(root: Path) -> None:
    paths = get_ui_archive_paths(root)
    st.subheader("Export evidence pack")
    containers = sorted(paths.containers.glob("*.fits"))
    if not containers:
        st.warning("No containers found. Build containers first."); return
    selected_container = st.selectbox("Container to export", options=containers, format_func=lambda p: p.name, key="export-container")
    output_text = st.text_input("Output folder", value=str(paths.exports / selected_container.stem))
    if st.button("Export evidence pack", type="primary"):
        out = export_evidence_pack(selected_container, Path(output_text)); st.success(f"Exported evidence pack to {out}")
        summary = out / "EVIDENCE_PACK_SUMMARY.md"
        if summary.exists(): st.markdown(summary.read_text(encoding="utf-8"))


def api_tab(root: Path) -> None:
    st.subheader("API layer")
    st.markdown("Run the FastAPI service from the repository root:")
    st.code("uvicorn app.api:app --reload --host 127.0.0.1 --port 8000", language="powershell")
    st.markdown("Example endpoints:")
    st.code("""GET  /health?root=samples
POST /index/rebuild?root=samples
POST /ingestion/bulk?root=samples&input_path=data/ingestion_demo/legacy_export
POST /ingestion/queue/process?root=samples&queue_path=data/ingestion_demo/queue
GET  /entities?root=samples
GET  /entities/{entity_id}/objects?root=samples
GET  /search?root=samples&q=source%20of%20wealth&mode=keyword
GET  /search?root=samples&q=where%20did%20money%20come%20from&mode=vector
GET  /search?root=samples&q=where%20did%20money%20come%20from&mode=lmstudio-vector
GET  /llm/status
GET  /llm/expand-query?q=where%20did%20the%20customer%20money%20come%20from
POST /llm/vector-index/rebuild?root=samples
GET  /llm/summarise-search?root=samples&q=source%20of%20wealth
GET  /containers/{container_name}/inspect?root=samples
GET  /containers/{container_name}/validate?root=samples""")


def main() -> None:
    st.title("Entity Evidence Container Demo")
    st.caption("FITS-based portable evidence objects with embedded OCR, extracted fields, internal snapshots, integrity validation, retention/legal hold, direct FITS search, local vector search, evidence export and API access.")
    st.sidebar.markdown("### Mode")
    st.sidebar.radio(
        "Interface mode",
        ["Basic", "Advanced"],
        index=0,
        key="ui_mode",
        help="Basic shows the normal user workflow. Advanced exposes diagnostics, build tools and implementation controls.",
    )
    root = Path(st.sidebar.text_input("Demo root folder", value=str(DEFAULT_ROOT)))
    paths = configure_archive_paths(root)
    schema_status = get_index_schema_status(paths.index)
    if paths.index.exists() and not schema_status["is_current"]:
        st.warning("The SQLite search index was built with an older schema. Use Dashboard → Rebuild SQLite/FTS index.")
    if is_basic_mode():
        st.sidebar.markdown("### Archive")
        st.sidebar.caption(f"Root: `{paths.root}`")
        st.sidebar.caption(f"Containers: `{paths.containers}`")
        st.sidebar.caption(f"Index: `{paths.index}`")
        if st.sidebar.button("Refresh UI caches"):
            clear_caches(); st.rerun()
        tabs = st.tabs(["Search", "Customers", "Completeness", "Evidence Packs"])
        with tabs[0]: search_tab(root)
        with tabs[1]: customers_tab(root)
        with tabs[2]: evidence_completeness_tab(root)
        with tabs[3]: export_tab(root)
    else:
        st.sidebar.markdown("### Paths")
        st.sidebar.caption(f"Source: `{paths.source}`"); st.sidebar.caption(f"Containers: `{paths.containers}`"); st.sidebar.caption(f"Index: `{paths.index}`")
        st.sidebar.caption(f"Vector: `{paths.root / 'index' / 'evidence_vector.pkl'}`")
        st.sidebar.caption(f"LM vector: `{paths.root / 'index' / 'evidence_lmstudio_vector.pkl'}`")
        if st.sidebar.button("Refresh UI caches"):
            clear_caches(); st.rerun()
        tabs = st.tabs(["Dashboard", "Health", "Comparison", "Customers", "Search", "Completeness", "Rulesets", "Ingestion", "Extraction", "Retention", "Integrity", "Export", "API"])
        with tabs[0]: dashboard_tab(root)
        with tabs[1]: health_tab(root)
        with tabs[2]: comparison_tab(root)
        with tabs[3]: customers_tab(root)
        with tabs[4]: search_tab(root)
        with tabs[5]: evidence_completeness_tab(root)
        with tabs[6]: ruleset_builder_tab(root)
        with tabs[7]: ingestion_tab(root)
        with tabs[8]: extraction_tab(root)
        with tabs[9]: retention_tab(root)
        with tabs[10]: integrity_tab(root)
        with tabs[11]: export_tab(root)
        with tabs[12]: api_tab(root)


if __name__ == "__main__":
    main()
