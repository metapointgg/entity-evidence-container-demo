from __future__ import annotations

REGULATORY_PRESETS = {
    "AML / CDD evidence": {
        "query": "customer due diligence source of wealth source of funds sanctions pep risk assessment",
        "filters": {"retention_class": ["CDD"], "category": ["Due Diligence"]},
        "description": "CDD, source-of-wealth, identity, screening and risk-review evidence.",
    },
    "Source of wealth / funds": {
        "query": "source of wealth source of funds inheritance property sale dividends proceeds evidence",
        "filters": {"category": ["Due Diligence"]},
        "description": "Evidence supporting how the customer generated or obtained funds.",
    },
    "High-risk customer reviews": {
        "query": "high risk enhanced due diligence compliance review adverse media pep sanctions",
        "filters": {"risk_rating": ["High"]},
        "description": "High-risk customer files and enhanced due-diligence material.",
    },
    "Statements and transaction evidence": {
        "query": "statement monthly balance transaction account payment transfer",
        "filters": {"category": ["Statement", "Transaction Extract"]},
        "description": "Statements and transaction extracts useful for complaints and audit retrieval.",
    },
    "Customer communications": {
        "query": "email correspondence follow up welcome review documentation customer communication",
        "filters": {"category": ["Correspondence"]},
        "description": "Preserved customer emails and correspondence records.",
    },
    "Complaints / dispute evidence": {
        "query": "complaint dispute final response investigation redress statement discrepancy payment delay",
        "filters": {},
        "description": "Complaint, dispute and investigation material across customer files.",
    },
    "Legal hold / disclosure pack": {
        "query": "legal hold disclosure evidence audit provenance statements correspondence due diligence",
        "filters": {"legal_hold_status": ["Active"], "sensitivity": ["Restricted", "Confidential"]},
        "description": "Broad evidence retrieval for disclosure, regulator requests or litigation support.",
    },
    "Expired retention review": {
        "query": "retention disposal deletion eligible legal hold",
        "filters": {},
        "description": "Records-management review for retention, disposal and legal-hold analysis.",
    },
}
