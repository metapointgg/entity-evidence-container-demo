from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from eec.container_reader import inspect_container, read_entity, read_manifest, validate_container
from eec.corruption import corrupt_container
from eec.exporter import export_evidence_pack
from eec.indexer import rebuild_index
from eec.search import search_index
from eec.ui_data import (
    format_bytes,
    get_archive_summary,
    get_entity_by_id,
    list_entities,
    list_objects_for_entity,
    read_payload,
    resolve_archive_paths,
    validate_all_containers,
)

st.set_page_config(
    page_title="Entity Evidence Container Demo",
    page_icon="🗃️",
    layout="wide",
)


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
def cached_search(index_path: str, query: str, limit: int) -> List[Dict[str, Any]]:
    return search_index(Path(index_path), query, limit=limit)


@st.cache_data(show_spinner=False)
def cached_inspect(container_path: str) -> Dict[str, Any]:
    return inspect_container(Path(container_path))


@st.cache_data(show_spinner=False)
def cached_validate(container_path: str) -> Dict[str, Any]:
    return validate_container(Path(container_path)).to_dict()


def clear_caches() -> None:
    cached_summary.clear()
    cached_entities.clear()
    cached_objects.clear()
    cached_search.clear()
    cached_inspect.clear()
    cached_validate.clear()


def run_generator(customers: int, target_mb: int, seed: int, root: Path) -> None:
    command = [
        sys.executable,
        "scripts/generate_sample_data.py",
        "--customers",
        str(customers),
        "--output",
        str(root / "source"),
        "--target-mb-per-customer",
        str(target_mb),
        "--seed",
        str(seed),
    ]
    subprocess.run(command, check=True)


def run_build_containers(root: Path) -> int:
    command = [
        sys.executable,
        "scripts/build_containers.py",
        "--source",
        str(root / "source"),
        "--output",
        str(root / "containers"),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    st.code(completed.stdout or completed.stderr or "Containers built.")
    return 0


def render_validation_badge(status: str) -> None:
    if status == "PASS":
        st.success("Integrity: PASS")
    else:
        st.error("Integrity: FAIL")


def render_object_preview(row: Dict[str, Any]) -> None:
    container_path = Path(row["container_path"])
    object_id = row["object_id"]
    item, data = read_payload(container_path, object_id)
    mime_type = item.get("mime_type", "application/octet-stream")
    filename = item.get("filename", f"{object_id}.bin")

    st.download_button(
        "Download original payload",
        data=data,
        file_name=filename,
        mime=mime_type,
        key=f"download-{object_id}",
    )

    if mime_type.startswith("text/") or filename.endswith((".txt", ".json", ".csv", ".eml")):
        st.text_area("Payload preview", data.decode("utf-8", errors="replace")[:12000], height=320)
    elif mime_type.startswith("image/"):
        st.image(data, caption=filename, use_container_width=True)
    elif mime_type == "application/pdf":
        st.info("PDF payload is preserved byte-for-byte. Use the download button to open it locally.")
    else:
        st.info("Binary payload preview is intentionally limited. Use the download button to inspect the original payload.")
        st.code(data[:256].hex(" "))


def dashboard_tab(root: Path) -> None:
    paths = resolve_archive_paths(root)
    summary = cached_summary(str(root))

    st.subheader("Archive overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Containers", summary["container_count"])
    c2.metric("Entities", summary["entity_count"])
    c3.metric("Preserved objects", summary["object_count"])
    c4.metric("Container storage", format_bytes(summary["total_container_bytes"]))

    st.caption(f"Index: `{summary['index_path']}`")

    st.divider()
    st.subheader("Demo data and index actions")
    st.write("Use these actions to create or refresh the demonstrator data set from the UI.")

    col_a, col_b, col_c = st.columns(3)
    customers = col_a.number_input("Customers", min_value=1, max_value=500, value=3, step=1)
    target_mb = col_b.number_input("Approx. MB per customer", min_value=1, max_value=1024, value=2, step=1)
    seed = col_c.number_input("Seed", min_value=1, max_value=999999, value=42, step=1)

    action_cols = st.columns(3)
    with action_cols[0]:
        if st.button("Generate sample evidence", type="secondary"):
            with st.spinner("Generating sample customer evidence..."):
                run_generator(int(customers), int(target_mb), int(seed), root)
            clear_caches()
            st.success("Sample evidence generated.")
    with action_cols[1]:
        if st.button("Build FITS containers", type="secondary"):
            with st.spinner("Building FITS preservation containers..."):
                run_build_containers(root)
            clear_caches()
            st.success("Containers built.")
    with action_cols[2]:
        if st.button("Rebuild search index", type="primary"):
            with st.spinner("Rebuilding SQLite/FTS index from containers..."):
                count = rebuild_index(paths.containers, paths.index)
            clear_caches()
            st.success(f"Indexed {count} preserved objects.")

    st.divider()
    st.subheader("Architecture thesis")
    st.markdown(
        """
        This demonstrator treats the FITS file as a **portable entity evidence object**. The database/search layer is useful for discovery, but it is deliberately rebuildable from the preservation containers.

        **Source systems → Entity Evidence Builder → FITS preservation containers → Rebuildable index → Search / export / validation / UI**
        """
    )


def customers_tab(root: Path) -> None:
    paths = resolve_archive_paths(root)
    entities = cached_entities(str(paths.index))
    if not entities:
        st.warning("No entities found. Rebuild the search index from the Dashboard tab first.")
        return

    st.subheader("Customers / entities")
    entity_df = pd.DataFrame(entities)
    entity_df["payload_size"] = entity_df["payload_bytes"].apply(format_bytes)
    st.dataframe(
        entity_df[["entity_id", "display_name", "jurisdiction", "risk_rating", "occupation", "object_count", "payload_size"]],
        use_container_width=True,
        hide_index=True,
    )

    selected = st.selectbox(
        "Select an entity",
        options=[row["entity_id"] for row in entities],
        format_func=lambda entity_id: f"{entity_id} — {next(row['display_name'] for row in entities if row['entity_id'] == entity_id)}",
    )

    entity = get_entity_by_id(paths.index, selected)
    if not entity:
        return
    objects = cached_objects(str(paths.index), selected)
    st.divider()
    st.subheader(f"{entity['display_name']} / {selected}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Risk rating", entity.get("risk_rating") or "—")
    m2.metric("Jurisdiction", entity.get("jurisdiction") or "—")
    m3.metric("Objects", len(objects))
    m4.metric("Payload size", format_bytes(sum(o.get("size_bytes") or 0 for o in objects)))

    container_path = Path(entity["container_path"])
    inspect_data = cached_inspect(str(container_path))
    with st.expander("Container metadata"):
        st.json(inspect_data)

    if st.button("Validate this container"):
        result = cached_validate(str(container_path))
        render_validation_badge(result["status"])
        if result["failures"]:
            st.json(result["failures"])

    st.markdown("### Preserved objects")
    objects_df = pd.DataFrame(objects)
    objects_df["size"] = objects_df["size_bytes"].apply(format_bytes)
    st.dataframe(
        objects_df[["object_id", "category", "document_type", "filename", "source_system", "retention_class", "sensitivity", "size"]],
        use_container_width=True,
        hide_index=True,
    )

    selected_object = st.selectbox(
        "Preview / download preserved object",
        options=[row["object_id"] for row in objects],
        format_func=lambda oid: f"{oid} — {next(row['filename'] for row in objects if row['object_id'] == oid)}",
    )
    selected_row = next(row for row in objects if row["object_id"] == selected_object)
    render_object_preview(selected_row)


def search_tab(root: Path) -> None:
    paths = resolve_archive_paths(root)
    st.subheader("Search rebuilt index")
    query = st.text_input("Search query", value="source of wealth")
    limit = st.slider("Limit", min_value=5, max_value=100, value=25, step=5)
    if not query.strip():
        st.info("Enter a search term to query the SQLite/FTS index.")
        return
    if not paths.index.exists():
        st.warning("Index not found. Rebuild the search index from the Dashboard tab first.")
        return

    results = cached_search(str(paths.index), query, limit)
    st.caption(f"{len(results)} result(s)")
    if not results:
        st.info("No results found.")
        return

    for row in results:
        with st.container(border=True):
            title = f"{row['display_name']} / {row['entity_id']} — {row['filename']}"
            st.markdown(f"**{title}**")
            st.caption(f"{row['category']} · {row['document_type']} · {row['source_system']} · {format_bytes(row['size_bytes'])}")
            if row.get("snippet"):
                st.markdown(row["snippet"])
            cols = st.columns([1, 1, 4])
            if cols[0].button("Preview", key=f"preview-{row['object_id']}"):
                st.session_state["preview_object"] = row
            if cols[1].button("Validate", key=f"validate-{row['object_id']}"):
                validation = cached_validate(row["container_path"])
                render_validation_badge(validation["status"])

    preview = st.session_state.get("preview_object")
    if preview:
        st.divider()
        st.subheader("Selected payload")
        render_object_preview(preview)


def integrity_tab(root: Path) -> None:
    paths = resolve_archive_paths(root)
    st.subheader("Integrity and corruption detection")
    containers = sorted(paths.containers.glob("*.fits"))
    if not containers:
        st.warning("No containers found. Build containers first.")
        return

    selected_container = st.selectbox("Container", options=containers, format_func=lambda p: p.name)
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Validate selected container", type="primary"):
            result = validate_container(selected_container).to_dict()
            render_validation_badge(result["status"])
            st.json(result)

    with col2:
        object_index = st.number_input("Object index to corrupt", min_value=0, max_value=9999, value=3, step=1)
        if st.button("Create corrupted copy"):
            output = selected_container.with_name(selected_container.stem + "-ui-corrupt.fits")
            corrupt_container(selected_container, output, int(object_index))
            clear_caches()
            st.warning(f"Created corrupted copy: {output.name}")

    st.divider()
    if st.button("Validate all containers"):
        with st.spinner("Validating all FITS containers..."):
            rows = validate_all_containers(paths.containers)
        df = pd.DataFrame(rows)
        if not df.empty:
            st.dataframe(df[["container_name", "entity_id", "status", "checked_payloads", "failed_payloads"]], use_container_width=True, hide_index=True)
            failures = [failure for row in rows for failure in row.get("failures", [])]
            if failures:
                st.error(f"Detected {len(failures)} failed payload(s).")
                st.json(failures)
            else:
                st.success("All containers passed integrity validation.")


def export_tab(root: Path) -> None:
    paths = resolve_archive_paths(root)
    st.subheader("Export regulator-ready evidence pack")
    containers = sorted(paths.containers.glob("*.fits"))
    if not containers:
        st.warning("No containers found. Build containers first.")
        return
    selected_container = st.selectbox("Container to export", options=containers, format_func=lambda p: p.name, key="export-container")
    default_output = paths.exports / selected_container.stem
    output_text = st.text_input("Output folder", value=str(default_output))

    if st.button("Export evidence pack", type="primary"):
        out = export_evidence_pack(selected_container, Path(output_text))
        st.success(f"Exported evidence pack to {out}")
        summary = out / "EVIDENCE_PACK_SUMMARY.md"
        if summary.exists():
            st.markdown(summary.read_text(encoding="utf-8"))


def main() -> None:
    st.title("Entity Evidence Container Demo")
    st.caption("FITS-based portable evidence objects for regulated records, search, export and integrity validation.")

    root_value = st.sidebar.text_input("Demo root folder", value=str(DEFAULT_ROOT))
    root = Path(root_value)
    paths = resolve_archive_paths(root)
    st.sidebar.markdown("### Paths")
    st.sidebar.caption(f"Source: `{paths.source}`")
    st.sidebar.caption(f"Containers: `{paths.containers}`")
    st.sidebar.caption(f"Index: `{paths.index}`")

    if st.sidebar.button("Refresh UI caches"):
        clear_caches()
        st.rerun()

    tab_dashboard, tab_customers, tab_search, tab_integrity, tab_export = st.tabs(
        ["Dashboard", "Customers", "Search", "Integrity", "Export"]
    )
    with tab_dashboard:
        dashboard_tab(root)
    with tab_customers:
        customers_tab(root)
    with tab_search:
        search_tab(root)
    with tab_integrity:
        integrity_tab(root)
    with tab_export:
        export_tab(root)


if __name__ == "__main__":
    main()
