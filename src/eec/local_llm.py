from __future__ import annotations

import os
import re
from typing import Any, Iterable, Sequence

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "lm-studio"
DEFAULT_CHAT_MODEL = "google/gemma-4-e4b"
DEFAULT_QUERY_MODEL = "google/gemma-4-e4b"
DEFAULT_EMBEDDING_MODEL = "text-embedding-nomic-embed-text-v1.5"


class LocalLLMError(RuntimeError):
    """Raised when the local LM Studio endpoint is unavailable or misconfigured."""


def get_lm_studio_client():
    """Return an OpenAI-compatible client pointed at LM Studio."""
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        raise LocalLLMError("Local LLM support requires openai. Install with: python -m pip install openai") from exc

    return OpenAI(
        base_url=os.getenv("EEC_LM_STUDIO_BASE_URL", DEFAULT_BASE_URL),
        api_key=os.getenv("EEC_LM_STUDIO_API_KEY", DEFAULT_API_KEY),
    )


# Backwards-compatible alias used by older modules.
def _openai_client():
    return get_lm_studio_client()


def get_chat_model() -> str:
    return os.getenv("EEC_LM_STUDIO_MODEL", DEFAULT_CHAT_MODEL)


def get_query_model() -> str:
    return os.getenv("EEC_LM_STUDIO_QUERY_MODEL", os.getenv("EEC_LM_STUDIO_MODEL", DEFAULT_QUERY_MODEL))


def get_embedding_model() -> str:
    return os.getenv("EEC_LM_STUDIO_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


# Backwards-compatible aliases.
def chat_model() -> str:
    return get_chat_model()


def query_model() -> str:
    return get_query_model()


def embedding_model() -> str:
    return get_embedding_model()


def list_models() -> list[str]:
    client = get_lm_studio_client()
    models = client.models.list()
    return [model.id for model in models.data]


def lm_studio_status() -> dict[str, Any]:
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
    content = getattr(message, "content", None) or ""
    if content:
        return content
    # Some local reasoning models expose reasoning_content rather than final content.
    return getattr(message, "reasoning_content", None) or ""


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
    blocked_fragments = [
        "thinking process", "analyze the request", "determine the search terms",
        "determine the intent", "brainstorm", "constraint", "final selection",
        "revised list", "check constraints", "let's", "the user", "the prompt",
        "task:", "format:", "topic:", "json", "allowed intents",
    ]
    if any(fragment in lower for fragment in blocked_fragments):
        return None
    if len(cleaned) < 3 or len(cleaned) > 90:
        return None
    return cleaned


def expand_search_query(query: str, model: str | None = None, max_terms: int = 20) -> list[str]:
    """Use a local model to expand a plain-English search query into archive search terms."""
    if not query.strip():
        return []
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
    text = _extract_text_from_message(response.choices[0].message)
    terms: list[str] = []
    for line in text.splitlines():
        term = _clean_search_term(line)
        if term:
            if ":" in term and len(term.split(":", 1)[0]) < 30:
                term = term.split(":", 1)[1].strip()
            if term and term.lower() not in {t.lower() for t in terms}:
                terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms[:max_terms]


def summarise_search_results(query: str, result_rows: Iterable[dict[str, Any]], model: str | None = None, max_rows: int = 10) -> str:
    rows = list(result_rows)[:max_rows]
    if not rows:
        return "No retrieved evidence was provided for summarisation."
    evidence_blocks: list[str] = []
    for idx, row in enumerate(rows, start=1):
        evidence_blocks.append(
            f"""
Result {idx}
Entity: {row.get('entity_id', '')}
Customer: {row.get('display_name', '')}
Object: {row.get('object_id', '')}
Snapshot: {row.get('snapshot_id', '')}
Category: {row.get('category', '')}
Document type: {row.get('document_type', '')}
Source system: {row.get('source_system', '')}
Filename: {row.get('filename', '')}
Retention: {row.get('retention_class', '')} / {row.get('retention_until', '')}
Legal hold: {row.get('legal_hold_status', '')}
Evidence text: {(row.get('search_text') or row.get('snippet') or '')[:1600]}
""".strip()
        )
    client = get_lm_studio_client()
    response = client.chat.completions.create(
        model=model or get_chat_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    "You summarise retrieved financial services evidence for compliance and operations users. "
                    "Use only the supplied evidence. Do not invent facts. "
                    "If evidence is insufficient, say so. Keep the summary concise and grounded."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User query:\n{query}\n\nRetrieved evidence:\n"
                    + "\n\n".join(evidence_blocks)
                    + "\n\nProvide a concise summary with key evidence types and any limitations."
                ),
            },
        ],
        temperature=0.1,
        max_tokens=1200,
    )
    return _extract_text_from_message(response.choices[0].message)


def answer_question_from_evidence(question: str, result_rows: Iterable[dict[str, Any]], model: str | None = None, max_rows: int = 8) -> str:
    rows = list(result_rows)[:max_rows]
    if not rows:
        return "No evidence rows were provided."
    evidence: list[str] = []
    for idx, row in enumerate(rows, start=1):
        evidence.append(
            f"""
Evidence {idx}
Entity: {row.get('entity_id', '')}
Customer: {row.get('display_name', '')}
Object: {row.get('object_id', '')}
Snapshot: {row.get('snapshot_id', '')}
Category: {row.get('category', '')}
Document type: {row.get('document_type', '')}
Source system: {row.get('source_system', '')}
Filename: {row.get('filename', '')}
Text: {(row.get('search_text') or row.get('snippet') or '')[:1800]}
""".strip()
        )
    client = get_lm_studio_client()
    response = client.chat.completions.create(
        model=model or get_chat_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer questions using only the retrieved evidence. Do not speculate. "
                    "If the answer is not supported by the evidence, say that the evidence is insufficient. "
                    "Cite object IDs in the answer where useful."
                ),
            },
            {"role": "user", "content": f"Question:\n{question}\n\nRetrieved evidence:\n" + "\n\n".join(evidence)},
        ],
        temperature=0.1,
        max_tokens=1200,
    )
    return _extract_text_from_message(response.choices[0].message)


# Backwards-compatible alias used by some earlier UI versions.
def ask_over_evidence(question: str, result_rows: Iterable[dict[str, Any]], model: str | None = None, max_rows: int = 10) -> str:
    return answer_question_from_evidence(question, result_rows, model=model, max_rows=max_rows)


def embed_texts(texts: Sequence[str], model: str | None = None) -> list[list[float]]:
    client = get_lm_studio_client()
    clean = [text if text and text.strip() else " " for text in texts]
    response = client.embeddings.create(model=model or get_embedding_model(), input=clean)
    return [item.embedding for item in response.data]


def summarise_completeness_report(report: dict[str, Any], model: str | None = None, max_customers: int = 12) -> str:
    """Summarise an evidence-completeness report using the local model.

    The summary is advisory only. The checklist/report remains the source of truth.
    """
    summary = report.get("summary", {}) or {}
    rows = list(report.get("rows", []) or [])[:max_customers]

    if not rows:
        return "No completeness rows were provided for summarisation."

    customer_blocks: list[str] = []
    for idx, row in enumerate(rows, start=1):
        missing = ", ".join(row.get("missing_evidence") or []) or "None"
        present = ", ".join(row.get("present_evidence") or []) or "None"
        customer_blocks.append(
            f"""
Customer {idx}
Entity: {row.get('entity_id', '')}
Name: {row.get('display_name', '')}
Risk rating: {row.get('risk_rating', '')}
Jurisdiction: {row.get('jurisdiction', '')}
Profile: {row.get('profile', '')}
Complete: {row.get('complete', False)}
Present evidence: {present}
Missing evidence: {missing}
Evidence count: {row.get('evidence_count', 0)}
""".strip()
        )

    client = get_lm_studio_client()
    response = client.chat.completions.create(
        model=model or get_chat_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    "You summarise evidence-completeness control results for financial services compliance users. "
                    "Use only the supplied completeness report. Do not invent facts. "
                    "Be concise, identify key gaps, highlight highest-priority remediation, and note if the sample is filtered."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Completeness report summary:\n"
                    f"Ruleset: {summary.get('ruleset_name', '')}\n"
                    f"Customers evaluated: {summary.get('customers_evaluated', 0)}\n"
                    f"Complete customers: {summary.get('complete_customers', 0)}\n"
                    f"Incomplete customers: {summary.get('incomplete_customers', 0)}\n"
                    f"Total missing items: {summary.get('total_missing_items', 0)}\n\n"
                    "Customer rows:\n"
                    + "\n\n".join(customer_blocks)
                    + "\n\nProvide:\n"
                    "1. A short overall finding.\n"
                    "2. Key missing evidence themes.\n"
                    "3. Recommended remediation actions.\n"
                    "4. Any important limitation."
                ),
            },
        ],
        temperature=0.1,
        max_tokens=1200,
    )
    return _extract_text_from_message(response.choices[0].message)
