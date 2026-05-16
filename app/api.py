from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from eec.archive_health import indexed_health, integrity_health
from eec.container_reader import inspect_container, validate_container
from eec.indexer import rebuild_index
from eec.search import advanced_search_index
from eec.ui_data import list_entities, list_objects_for_entity, read_payload, resolve_archive_paths
from eec.vector_search import vector_search
from eec.local_llm import answer_question_from_evidence, expand_search_query, lm_studio_status, summarise_search_results
from eec.lmstudio_vector_search import build_lmstudio_vector_index, lmstudio_vector_search

app = FastAPI(title="Entity Evidence Container API", version="0.1.0")


def _paths(root: str):
    return resolve_archive_paths(Path(root))


@app.get("/health")
def health(root: str = "samples"):
    paths = _paths(root)
    return {"indexed": indexed_health(paths.index), "integrity": integrity_health(paths.containers)}


@app.post("/index/rebuild")
def rebuild(root: str = "samples"):
    paths = _paths(root)
    count = rebuild_index(paths.containers, paths.index)
    return {"indexed_objects": count, "index": str(paths.index)}


@app.get("/entities")
def entities(root: str = "samples"):
    return list_entities(_paths(root).index)


@app.get("/entities/{entity_id}/objects")
def entity_objects(entity_id: str, root: str = "samples"):
    return list_objects_for_entity(_paths(root).index, entity_id)


@app.get("/search")
def search(root: str = "samples", q: str = "", mode: str = Query("keyword", pattern="^(keyword|semantic|vector|lmstudio-vector)$"), limit: int = 50):
    paths = _paths(root)
    if mode == "vector":
        return vector_search(paths.root / "index" / "evidence_vector.pkl", q, limit)
    if mode == "lmstudio-vector":
        return lmstudio_vector_search(paths.root / "index" / "evidence_lmstudio_vector.pkl", q, limit)
    return advanced_search_index(paths.index, query=q, limit=limit, mode=mode)


@app.get("/containers/{container_name}/inspect")
def inspect(container_name: str, root: str = "samples"):
    container = _paths(root).containers / container_name
    if not container.exists():
        raise HTTPException(status_code=404, detail="Container not found")
    return inspect_container(container)


@app.get("/containers/{container_name}/validate")
def validate(container_name: str, root: str = "samples"):
    container = _paths(root).containers / container_name
    if not container.exists():
        raise HTTPException(status_code=404, detail="Container not found")
    return validate_container(container).to_dict()


@app.get("/objects/{object_id}/download")
def download_object(object_id: str, container_path: str):
    container = Path(container_path)
    if not container.exists():
        raise HTTPException(status_code=404, detail="Container not found")
    item, data = read_payload(container, object_id)
    tmp_dir = Path(".tmp_api_payloads")
    tmp_dir.mkdir(exist_ok=True)
    out = tmp_dir / item.get("filename", f"{object_id}.bin")
    out.write_bytes(data)
    return FileResponse(out, media_type=item.get("mime_type", "application/octet-stream"), filename=item.get("filename", out.name))


@app.get("/llm/status")
def llm_status():
    return lm_studio_status()


@app.get("/llm/expand-query")
def llm_expand_query(q: str):
    return {"query": q, "expanded_terms": expand_search_query(q)}


@app.post("/llm/vector-index/rebuild")
def rebuild_lmstudio_vector_index(root: str = "samples"):
    paths = _paths(root)
    output = paths.root / "index" / "evidence_lmstudio_vector.pkl"
    count = build_lmstudio_vector_index(paths.index, output)
    return {"indexed_objects": count, "index": str(output)}


@app.get("/llm/summarise-search")
def llm_summarise_search(root: str = "samples", q: str = "", mode: str = "keyword", limit: int = 10):
    paths = _paths(root)
    if mode == "lmstudio-vector":
        rows = lmstudio_vector_search(paths.root / "index" / "evidence_lmstudio_vector.pkl", q, limit)
    elif mode == "vector":
        rows = vector_search(paths.root / "index" / "evidence_vector.pkl", q, limit)
    else:
        rows = advanced_search_index(paths.index, query=q, limit=limit, mode=mode)
    return {"query": q, "summary": summarise_search_results(q, rows), "result_count": len(rows)}


@app.get("/llm/ask")
def llm_ask(root: str = "samples", q: str = "", question: str = "", mode: str = "keyword", limit: int = 8):
    paths = _paths(root)
    if mode == "lmstudio-vector":
        rows = lmstudio_vector_search(paths.root / "index" / "evidence_lmstudio_vector.pkl", q, limit)
    elif mode == "vector":
        rows = vector_search(paths.root / "index" / "evidence_vector.pkl", q, limit)
    else:
        rows = advanced_search_index(paths.index, query=q, limit=limit, mode=mode)
    return {"query": q, "question": question, "answer": answer_question_from_evidence(question, rows), "result_count": len(rows)}
