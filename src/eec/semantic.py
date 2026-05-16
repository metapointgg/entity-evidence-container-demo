from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Tuple

TOKEN_RE = re.compile(r"[a-zA-Z0-9_'-]+")

DOMAIN_SYNONYMS: Dict[str, List[str]] = {
    "wealth": ["source", "funds", "inheritance", "dividend", "sale", "proceeds", "net worth", "asset"],
    "source": ["wealth", "funds", "proceeds", "origin", "evidence"],
    "kyc": ["cdd", "due diligence", "onboarding", "identity", "verification", "risk"],
    "cdd": ["kyc", "due diligence", "screening", "periodic review", "compliance"],
    "identity": ["passport", "id", "verification", "certified", "document"],
    "address": ["utility", "bill", "residence", "proof"],
    "complaint": ["dispute", "final response", "investigation", "redress", "issue"],
    "statement": ["account", "balance", "monthly", "transaction", "notice"],
    "payment": ["transaction", "transfer", "standing order", "card", "settlement"],
    "high": ["enhanced", "edd", "risk", "review", "compliance"],
    "risk": ["rating", "assessment", "compliance", "screening", "pep", "sanctions"],
    "pep": ["politically exposed", "screening", "risk", "sanctions"],
    "sanctions": ["screening", "aml", "financial crime", "risk"],
    "audit": ["evidence", "provenance", "integrity", "validation", "review"],
    "legal": ["hold", "litigation", "retention", "evidence", "disclosure"],
}


def tokenise(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


def expand_query(query: str) -> str:
    tokens = tokenise(query)
    expanded: List[str] = list(tokens)
    lower = query.lower()
    for key, values in DOMAIN_SYNONYMS.items():
        if key in tokens or key in lower:
            for value in values:
                expanded.extend(tokenise(value))
    # Keep stable order while deduplicating.
    seen = set()
    out = []
    for token in expanded:
        if token not in seen:
            seen.add(token)
            out.append(token)
    return " ".join(out)


def cosine_score(query: str, document: str) -> float:
    """Small dependency-free cosine similarity over expanded domain tokens.

    This is intentionally lightweight for the POC. It gives the demo a semantic-style mode
    without requiring an embeddings service. It can later be replaced with OpenAI embeddings,
    SentenceTransformers, FAISS, OpenSearch k-NN, etc.
    """
    q_tokens = tokenise(expand_query(query))
    d_tokens = tokenise(document)
    if not q_tokens or not d_tokens:
        return 0.0
    q = Counter(q_tokens)
    d = Counter(d_tokens)
    common = set(q) & set(d)
    numerator = sum(q[t] * d[t] for t in common)
    q_norm = math.sqrt(sum(v * v for v in q.values()))
    d_norm = math.sqrt(sum(v * v for v in d.values()))
    if q_norm == 0 or d_norm == 0:
        return 0.0
    return numerator / (q_norm * d_norm)
