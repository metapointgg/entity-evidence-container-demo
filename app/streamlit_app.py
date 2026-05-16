from __future__ import annotations

import base64
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pandas as pd
import streamlit as st

from eec.archive_health import indexed_health, integrity_health
from eec.container_reader import inspect_container, validate_container
from eec.corruption import corrupt_container
from eec.exporter import export_evidence_pack
from eec.indexer import rebuild_index
from eec.presets import REGULATORY_PRESETS
from eec.retention import retention_report
from eec.search import advanced_search_index
from eec.search_result_exporter import export_search_results
from eec.local_llm import answer_question_from_evidence, expand_search_query, lm_studio_status, summarise_search_results
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
def cached_validate(container_path: str) -> Dict[str, Any]:
    return validate_container(Path(container_path)).to_dict()


def clear_caches() -> None:
    cached_summary.clear(); cached_entities.clear(); cached_objects.clear(); cached_facets.clear(); cached_search.clear(); cached_vector_search.clear(); cached_lmstudio_vector_search.clear(); cached_validate.clear()


def run_generator(customers: int, target_mb: int, seed: int, root: Path) -> None:
    command = [sys.executable, "scripts/generate_sample_data.py", "--customers", str(customers), "--output", str(root / "source"), "--target-mb-per-customer", str(target_mb), "--seed", str(seed)]
    subprocess.run(command, check=True)


def run_build_containers(root: Path, snapshot_model: bool) -> None:
    command = [sys.executable, "scripts/build_containers.py", "--source", str(root / "source"), "--output", str(root / "containers")]
    if snapshot_model:
        command.append("--snapshot-model")
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
    paths = resolve_archive_paths(root)
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
    snapshot_model = col_d.checkbox("Snapshot model", value=True, help="Build immutable event/snapshot containers instead of one large file per entity.")
    a1, a2, a3, a4 = st.columns(4)
    if a1.button("Generate sample evidence"):
        with st.spinner("Generating sample evidence..."):
            run_generator(int(customers), int(target_mb), int(seed), root)
        clear_caches(); st.success("Generated.")
    if a2.button("Build FITS containers"):
        with st.spinner("Building FITS containers..."):
            run_build_containers(root, snapshot_model)
        clear_caches(); st.success("Containers built.")
    if a3.button("Rebuild SQLite/FTS index", type="primary"):
        with st.spinner("Rebuilding index from FITS containers..."):
            count = rebuild_index(paths.containers, paths.index)
        clear_caches(); st.success(f"Indexed {count} objects.")
    if a4.button("Build local vector index"):
        with st.spinner("Building local offline vector index..."):
            count = build_vector_index(paths.index, paths.root / "index" / "evidence_vector.pkl")
        cached_vector_search.clear(); st.success(f"Vector indexed {count} objects.")
    st.divider()
    st.subheader("Local LM Studio AI")
    status = lm_studio_status()
    if status.get("available"):
        st.success(f"LM Studio available at {status.get('base_url')}")
        st.caption("Models: " + ", ".join(status.get("models", [])))
        if st.button("Build LM Studio embedding index"):
            with st.spinner("Calling LM Studio embeddings endpoint and building local vector index..."):
                count = build_lmstudio_vector_index(paths.index, paths.root / "index" / "evidence_lmstudio_vector.pkl")
            cached_lmstudio_vector_search.clear(); st.success(f"LM Studio embedding indexed {count} objects.")
    else:
        st.warning("LM Studio is not available. Start LM Studio server on http://127.0.0.1:1234 and refresh.")
        st.caption(status.get("error", ""))
    st.info("Set EEC_OCR_PROVIDER=auto, sidecar, tesseract or none before building containers to control OCR/index extraction. Tesseract requires the native Tesseract executable plus pytesseract.")


def health_tab(root: Path) -> None:
    paths = resolve_archive_paths(root)
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
    paths = resolve_archive_paths(root)
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


def search_tab(root: Path) -> None:
    paths = resolve_archive_paths(root)
    st.subheader("Search rebuilt index")
    schema_status = get_index_schema_status(paths.index)
    if not schema_status["is_current"]:
        st.error(schema_status["message"]); st.json(schema_status); return
    facets = cached_facets(str(paths.index))
    preset_names = ["Custom search"] + list(REGULATORY_PRESETS.keys())
    preset_name = st.selectbox("Regulatory evidence search preset", preset_names)
    preset = REGULATORY_PRESETS.get(preset_name, {})
    if preset_name != "Custom search": st.caption(preset.get("description", ""))
    query = st.text_input("Search query", value=preset.get("query", "source of wealth"))
    mode = st.radio(
        "Search mode",
        ["keyword", "semantic", "vector", "lmstudio-vector"],
        horizontal=True,
        help="Vector mode uses the local TF-IDF index. LM Studio vector mode uses the local embeddings endpoint and evidence_lmstudio_vector.pkl.",
    )
    limit = st.slider("Limit", min_value=5, max_value=250, value=50, step=5)
    filters = _filter_multiselects(facets, defaults=preset.get("filters", {}))

    with st.expander("Local LM Studio assistance", expanded=False):
        status = lm_studio_status()
        if status.get("available"):
            st.success(f"LM Studio available: {status.get('base_url')}")
            st.caption(f"Query model: {status.get('query_model')} · Chat model: {status.get('chat_model')} · Embedding model: {status.get('embedding_model')}")
        else:
            st.warning("LM Studio is not currently available.")
            st.caption(status.get("error", ""))
        use_llm_expansion = st.checkbox("Use local LLM query expansion", value=False, disabled=not status.get("available"))
        show_summary = st.checkbox("Enable local LLM result summary", value=False, disabled=not status.get("available"))
        expanded_terms: list[str] = []
        if use_llm_expansion and query.strip():
            try:
                with st.spinner("Expanding search query with local LLM..."):
                    expanded_terms = expand_search_query(query)
                st.caption("Expanded terms: " + ", ".join(expanded_terms))
            except Exception as exc:
                st.error(f"Local LLM query expansion failed: {exc}")

    if mode == "vector":
        results = cached_vector_search(str(paths.root / "index" / "evidence_vector.pkl"), query + " " + " ".join(expanded_terms), limit)
        st.caption("Vector mode uses the local offline TF-IDF vector index and does not currently apply structured facets.")
    elif mode == "lmstudio-vector":
        results = cached_lmstudio_vector_search(str(paths.root / "index" / "evidence_lmstudio_vector.pkl"), query + " " + " ".join(expanded_terms), limit)
        st.caption("LM Studio vector mode uses local embeddings from LM Studio. Build this index from the Dashboard tab first.")
    else:
        results = cached_search(str(paths.index), query, limit, mode, _filters_key(filters))
        if expanded_terms:
            extra = []
            for term in expanded_terms[:8]:
                try:
                    extra.append(cached_search(str(paths.index), term, limit, mode, _filters_key(filters)))
                except Exception:
                    pass
            results = _merge_results(results, extra, limit)
    st.caption(f"{len(results)} result(s)")
    if not results:
        st.info("No results found."); return
    df = pd.DataFrame(results)
    cols = ["object_id", "entity_id", "display_name", "snapshot_id", "risk_rating", "category", "document_type", "filename", "source_system", "retention_class", "legal_hold_status", "sensitivity", "ocr_source", "size_bytes"]
    if "semantic_score" in df.columns: cols.insert(3, "semantic_score")
    if "vector_score" in df.columns: cols.insert(3, "vector_score")
    if "lmstudio_vector_score" in df.columns: cols.insert(3, "lmstudio_vector_score")
    out = df[[c for c in cols if c in df.columns]].copy()
    if "size_bytes" in out.columns:
        out["size"] = out["size_bytes"].apply(format_bytes); out = out.drop(columns=["size_bytes"])
    event, supported = _selectable_dataframe(out, key="search-results-table", height=420)
    idx = _selected_row_index(event) if supported else None
    st.markdown("### Result actions")
    c_export, c_preview, c_validate, c_msg = st.columns([1.4, 1.4, 1.2, 3])
    if c_export.button("Export all results as evidence pack", type="primary"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = paths.exports / f"search_results_{timestamp}"
        export_search_results(results, out_dir, pack_name=f"{preset_name} / {query}")
        st.success(f"Exported {len(results)} result(s) to {out_dir}")
    if idx is not None:
        row = results[idx]
        _open_preview_once(row, f"search:{mode}:{query}:{row['object_id']}", session_key="last_search_result_preview")
        if c_preview.button("Open selected preview again"):
            render_object_preview_modal(row)
        if c_validate.button("Validate container"):
            validation = cached_validate(row["container_path"]); render_validation_badge(validation["status"])
        c_msg.caption(f"Selected: {row.get('display_name')} / {row.get('filename')}")
        if row.get("snippet"):
            st.markdown("### Selected result snippet"); st.markdown(str(row["snippet"]))
        ask = st.text_input("Ask a question about the current results or selected evidence", value="")
        if ask and st.button("Ask local LLM"):
            try:
                evidence_rows = [row] + [r for i, r in enumerate(results) if i != idx][:7]
                with st.spinner("Asking local LLM over retrieved evidence..."):
                    st.markdown(answer_question_from_evidence(ask, evidence_rows))
            except Exception as exc:
                st.error(f"Local LLM question failed: {exc}")
    else:
        c_msg.caption("Select a row to preview it.")

    if show_summary and st.button("Summarise current results with local LLM"):
        try:
            with st.spinner("Summarising retrieved evidence with local LLM..."):
                st.markdown(summarise_search_results(query, results))
        except Exception as exc:
            st.error(f"Local LLM summary failed: {exc}")

def retention_tab(root: Path) -> None:
    paths = resolve_archive_paths(root)
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
    paths = resolve_archive_paths(root)
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
    paths = resolve_archive_paths(root)
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
    st.caption("FITS-based portable evidence objects with snapshot containers, integrity validation, retention/legal hold, OCR indexing, local vector search, evidence export and API access.")
    root = Path(st.sidebar.text_input("Demo root folder", value=str(DEFAULT_ROOT)))
    paths = resolve_archive_paths(root)
    schema_status = get_index_schema_status(paths.index)
    if paths.index.exists() and not schema_status["is_current"]:
        st.warning("The SQLite search index was built with an older schema. Use Dashboard → Rebuild SQLite/FTS index.")
    st.sidebar.markdown("### Paths")
    st.sidebar.caption(f"Source: `{paths.source}`"); st.sidebar.caption(f"Containers: `{paths.containers}`"); st.sidebar.caption(f"Index: `{paths.index}`")
    st.sidebar.caption(f"Vector: `{paths.root / 'index' / 'evidence_vector.pkl'}`")
    st.sidebar.caption(f"LM vector: `{paths.root / 'index' / 'evidence_lmstudio_vector.pkl'}`")
    if st.sidebar.button("Refresh UI caches"):
        clear_caches(); st.rerun()
    tabs = st.tabs(["Dashboard", "Health", "Comparison", "Customers", "Search", "Retention", "Integrity", "Export", "API"])
    with tabs[0]: dashboard_tab(root)
    with tabs[1]: health_tab(root)
    with tabs[2]: comparison_tab(root)
    with tabs[3]: customers_tab(root)
    with tabs[4]: search_tab(root)
    with tabs[5]: retention_tab(root)
    with tabs[6]: integrity_tab(root)
    with tabs[7]: export_tab(root)
    with tabs[8]: api_tab(root)


if __name__ == "__main__":
    main()
