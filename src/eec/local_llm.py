from __future__ import annotations

import os
import re
from typing import Iterable, Any

from openai import OpenAI


DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "lm-studio"
DEFAULT_CHAT_MODEL = "google/gemma-4-e4b"
DEFAULT_QUERY_MODEL = "google/gemma-4-e4b"
DEFAULT_EMBEDDING_MODEL = "text-embedding-nomic-embed-text-v1.5"


def get_lm_studio_client() -> OpenAI:
    """Return an OpenAI-compatible client pointed at LM Studio."""
    base_url = os.getenv("EEC_LM_STUDIO_BASE_URL", DEFAULT_BASE_URL)
    api_key = os.getenv("EEC_LM_STUDIO_API_KEY", DEFAULT_API_KEY)
    return OpenAI(base_url=base_url, api_key=api_key)


def get_chat_model() -> str:
    return os.getenv("EEC_LM_STUDIO_MODEL", DEFAULT_CHAT_MODEL)


def get_query_model() -> str:
    return os.getenv("EEC_LM_STUDIO_QUERY_MODEL", get_chat_model())


def get_embedding_model() -> str:
    return os.getenv("EEC_LM_STUDIO_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def list_models() -> list[str]:
    """List models currently exposed by LM Studio."""
    client = get_lm_studio_client()
    models = client.models.list()
    return [model.id for model in models.data]


def lm_studio_status() -> dict[str, Any]:
    """Return a lightweight LM Studio availability/status payload."""
    try:
        models = list_models()
        return {
            "available": True,
            "base_url": os.getenv("EEC_LM_STUDIO_BASE_URL", DEFAULT_BASE_URL),
            "chat_model": get_chat_model(),
            "query_model": get_query_model(),
            "embedding_model": get_embedding_model(),
            "models": models,
            "error": None,
        }
    except Exception as exc:
        return {
            "available": False,
            "base_url": os.getenv("EEC_LM_STUDIO_BASE_URL", DEFAULT_BASE_URL),
            "chat_model": get_chat_model(),
            "query_model": get_query_model(),
            "embedding_model": get_embedding_model(),
            "models": [],
            "error": str(exc),
        }


def _extract_text_from_message(message: Any) -> str:
    """Extract response text from normal content or local-model reasoning content."""
    content = getattr(message, "content", None) or ""

    if content:
        return content

    # Some local reasoning models expose reasoning_content rather than final content.
    reasoning_content = getattr(message, "reasoning_content", None) or ""

    return reasoning_content


def _clean_search_term(line: str) -> str | None:
    cleaned = line.strip()

    if not cleaned:
        return None

    cleaned = re.sub(r"^[\-\*\u2022\s]*", "", cleaned)
    cleaned = re.sub(r"^\d+[\.\)]\s*", "", cleaned)
    cleaned = cleaned.strip().strip('"').strip("'").strip()

    if not cleaned:
        return None

    lower = cleaned.lower()

    # Drop common reasoning/prose leakage from reasoning models.
    blocked_fragments = [
        "thinking process",
        "analyze the request",
        "determine the search terms",
        "determine the intent",
        "brainstorm",
        "constraint",
        "final selection",
        "revised list",
        "check constraints",
        "let's",
        "the user",
        "the prompt",
        "task:",
        "format:",
        "topic:",
    ]

    if any(fragment in lower for fragment in blocked_fragments):
        return None

    if len(cleaned) < 3 or len(cleaned) > 90:
        return None

    return cleaned


def expand_search_query(query: str, model: str | None = None) -> list[str]:
    """Use a local model to expand a plain-English search query into archive search terms."""
    client = get_lm_studio_client()
    model_name = model or get_query_model()

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate search terms for a regulated financial services evidence archive. "
                    "Return only concise search terms. One term per line. Do not explain."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Return exactly 10 search terms or short phrases, one per line, for this query:\n\n"
                    f"{query}\n\n"
                    "Use terms suitable for customer due diligence, source of wealth, source of funds, "
                    "banking records, customer statements, transaction evidence and compliance review."
                ),
            },
        ],
        temperature=0.1,
        max_tokens=800,
    )

    message = response.choices[0].message
    text = _extract_text_from_message(message)

    terms: list[str] = []

    for line in text.splitlines():
        term = _clean_search_term(line)
        if term:
            terms.append(term)

    # If a reasoning model leaked a long reasoning block, try to recover quoted/final terms.
    recovered_terms: list[str] = []
    for term in terms:
        if ":" in term and len(term.split(":", 1)[0]) < 30:
            possible = term.split(":", 1)[1].strip()
            cleaned = _clean_search_term(possible)
            if cleaned:
                recovered_terms.append(cleaned)
        else:
            recovered_terms.append(term)

    # Deduplicate while preserving order.
    unique_terms: list[str] = []
    seen: set[str] = set()

    for term in recovered_terms:
        key = term.lower()
        if key not in seen:
            unique_terms.append(term)
            seen.add(key)

    return unique_terms[:20]


def summarise_search_results(
    query: str,
    result_rows: Iterable[dict],
    model: str | None = None,
    max_rows: int = 10,
) -> str:
    """Summarise retrieved evidence using the local model."""
    client = get_lm_studio_client()
    model_name = model or get_chat_model()

    evidence_blocks: list[str] = []

    for idx, row in enumerate(result_rows, start=1):
        if idx > max_rows:
            break

        search_text = row.get("search_text") or row.get("ocr_text") or row.get("content") or ""

        evidence_blocks.append(
            f"""
Result {idx}
Entity: {row.get("entity_id", "")}
Container: {row.get("container_id", "")}
Object: {row.get("object_id", "")}
Category: {row.get("category", "")}
Document type: {row.get("document_type", "")}
Source system: {row.get("source_system", "")}
Filename: {row.get("filename", "")}
Text:
{search_text[:1500]}
"""
        )

    if not evidence_blocks:
        return "No retrieved evidence was provided for summarisation."

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "You summarise retrieved financial services evidence. "
                    "Use only the evidence provided. Do not invent facts. "
                    "If the evidence is insufficient, say so clearly."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User query:\n{query}\n\n"
                    "Retrieved evidence:\n"
                    f"{chr(10).join(evidence_blocks)}\n\n"
                    "Provide a concise compliance-style summary."
                ),
            },
        ],
        temperature=0.1,
        max_tokens=1200,
    )

    message = response.choices[0].message
    return _extract_text_from_message(message)


def ask_over_evidence(
    question: str,
    result_rows: Iterable[dict],
    model: str | None = None,
    max_rows: int = 10,
) -> str:
    """Answer a question using only supplied retrieved evidence rows."""
    client = get_lm_studio_client()
    model_name = model or get_chat_model()

    evidence_blocks: list[str] = []

    for idx, row in enumerate(result_rows, start=1):
        if idx > max_rows:
            break

        search_text = row.get("search_text") or row.get("ocr_text") or row.get("content") or ""

        evidence_blocks.append(
            f"""
Evidence {idx}
Entity: {row.get("entity_id", "")}
Object: {row.get("object_id", "")}
Document type: {row.get("document_type", "")}
Source system: {row.get("source_system", "")}
Filename: {row.get("filename", "")}
Text:
{search_text[:1500]}
"""
        )

    if not evidence_blocks:
        return "No retrieved evidence was provided."

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "You answer questions using only the evidence provided. "
                    "Do not infer beyond the evidence. "
                    "If the answer is not supported, say that the evidence is insufficient."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    "Evidence:\n"
                    f"{chr(10).join(evidence_blocks)}"
                ),
            },
        ],
        temperature=0.1,
        max_tokens=1200,
    )

    message = response.choices[0].message
    return _extract_text_from_message(message)

def embedding_model() -> str:
    """Backward-compatible alias used by lmstudio_vector_search.py."""
    return get_embedding_model()


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Generate local embeddings using LM Studio's OpenAI-compatible embeddings API."""
    client = get_lm_studio_client()
    model_name = model or get_embedding_model()

    cleaned_texts = [
        text if text and text.strip() else " "
        for text in texts
    ]

    response = client.embeddings.create(
        model=model_name,
        input=cleaned_texts,
    )

    # Preserve the response order.
    return [item.embedding for item in response.data]

def answer_question_from_evidence(
    question: str,
    result_rows: Iterable[dict],
    model: str | None = None,
    max_rows: int = 10,
) -> str:
    """Backward-compatible wrapper used by the Streamlit UI."""
    return ask_over_evidence(
        question=question,
        result_rows=result_rows,
        model=model,
        max_rows=max_rows,
    )