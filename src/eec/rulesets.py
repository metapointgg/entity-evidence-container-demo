from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_RULESET_ID = "retail_cdd_v1"

DEFAULT_REQUIRED_EVIDENCE: dict[str, list[str]] = {
    "Low-risk individual": ["Application", "Passport / ID", "Proof of Address", "CDD Review"],
    "Medium-risk individual": ["Application", "Passport / ID", "Proof of Address", "CDD Review", "Source of Funds"],
    "High-risk individual": ["Application", "Passport / ID", "Proof of Address", "CDD Review", "Source of Wealth", "Source of Funds", "Screening", "EDD Approval"],
    "Corporate customer": ["Application", "Company Registry Extract", "Beneficial Owner Evidence", "Authorised Signatory ID", "Proof of Address", "CDD Review", "Source of Funds"],
}

EVIDENCE_ALIASES: dict[str, list[str]] = {
    "Application": ["application", "customer application", "account opening", "signed application"],
    "Passport / ID": ["passport", "identity", "id verification", "identity evidence"],
    "Proof of Address": ["proof of address", "utility bill", "address evidence"],
    "CDD Review": ["cdd", "due diligence", "kyc", "risk review", "cdd review"],
    "Source of Wealth": ["source of wealth", "wealth evidence", "property sale", "investment income"],
    "Source of Funds": ["source of funds", "funding", "funds origin", "initial deposit", "bank statements for funding"],
    "Screening": ["screening", "sanctions", "pep", "adverse media"],
    "EDD Approval": ["edd", "enhanced due diligence", "manual approval", "compliance approval"],
    "Company Registry Extract": ["company registry", "registry extract", "incorporation", "company extract"],
    "Beneficial Owner Evidence": ["beneficial owner", "ubo", "ownership", "control evidence"],
    "Authorised Signatory ID": ["authorised signatory", "authorized signatory", "signatory id", "signatory identity"],
}


@dataclass
class EvidenceRuleProfile:
    profile: str
    customer_type: str = "Individual"
    risk_rating: str | None = None
    jurisdiction: str | None = None
    required_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceRuleset:
    ruleset_id: str = DEFAULT_RULESET_ID
    name: str = "Retail Individual CDD v1"
    description: str = "Default CDD evidence completeness rules for financial-services customer files."
    profiles: list[EvidenceRuleProfile] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ruleset_id": self.ruleset_id,
            "name": self.name,
            "description": self.description,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }



def default_ruleset() -> EvidenceRuleset:
    profiles = [
        EvidenceRuleProfile("Low-risk individual", risk_rating="Low", required_evidence=DEFAULT_REQUIRED_EVIDENCE["Low-risk individual"]),
        EvidenceRuleProfile("Medium-risk individual", risk_rating="Medium", required_evidence=DEFAULT_REQUIRED_EVIDENCE["Medium-risk individual"]),
        EvidenceRuleProfile("High-risk individual", risk_rating="High", required_evidence=DEFAULT_REQUIRED_EVIDENCE["High-risk individual"]),
        EvidenceRuleProfile("Corporate customer", customer_type="Corporate", required_evidence=DEFAULT_REQUIRED_EVIDENCE["Corporate customer"]),
    ]
    return EvidenceRuleset(profiles=profiles)



def ruleset_path(root: Path) -> Path:
    return root / "config" / "evidence_rulesets.json"



def load_rulesets(root: Path) -> list[EvidenceRuleset]:
    path = ruleset_path(root)
    if not path.exists():
        return [default_ruleset()]
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_rulesets = data.get("rulesets", data if isinstance(data, list) else [])
    rulesets: list[EvidenceRuleset] = []
    for raw in raw_rulesets:
        profiles = [
            EvidenceRuleProfile(
                profile=str(profile.get("profile") or profile.get("name") or "Profile"),
                customer_type=str(profile.get("customer_type") or "Individual"),
                risk_rating=profile.get("risk_rating") or None,
                jurisdiction=profile.get("jurisdiction") or None,
                required_evidence=list(profile.get("required_evidence") or []),
            )
            for profile in raw.get("profiles", [])
        ]
        rulesets.append(
            EvidenceRuleset(
                ruleset_id=str(raw.get("ruleset_id") or DEFAULT_RULESET_ID),
                name=str(raw.get("name") or "Evidence Ruleset"),
                description=str(raw.get("description") or ""),
                profiles=profiles,
            )
        )
    return rulesets or [default_ruleset()]



def save_rulesets(root: Path, rulesets: list[EvidenceRuleset]) -> Path:
    path = ruleset_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rulesets": [ruleset.to_dict() for ruleset in rulesets]}, indent=2), encoding="utf-8")
    return path



def ensure_rulesets(root: Path) -> Path:
    path = ruleset_path(root)
    if not path.exists():
        save_rulesets(root, [default_ruleset()])
    return path



def _normalise(text: str | None) -> str:
    return (text or "").lower().replace("_", " ").replace("-", " ")



def _evidence_terms(item: str) -> list[str]:
    terms = [item]
    terms.extend(EVIDENCE_ALIASES.get(item, []))
    return [_normalise(term) for term in terms if term]



def _object_matches_required(row: dict[str, Any], required_item: str) -> bool:
    # For control evidence presence, use identity and controlled extracted text, but avoid broad entity/customer fields.
    haystack = _normalise(" ".join(str(row.get(key, "")) for key in ["category", "document_type", "filename", "relative_path", "search_text"]))
    return any(term and term in haystack for term in _evidence_terms(required_item))



def _infer_customer_type(entity: dict[str, Any]) -> str:
    text = _normalise(" ".join(str(entity.get(key, "")) for key in ["display_name", "occupation", "entity_type"]))
    corporate_markers = [" ltd", " limited", " llc", " plc", " holdings", " company", " corporate"]
    return "Corporate" if any(marker in text for marker in corporate_markers) else "Individual"



def choose_profile(entity: dict[str, Any], ruleset: EvidenceRuleset) -> EvidenceRuleProfile:
    customer_type = _infer_customer_type(entity)
    risk_rating = entity.get("risk_rating")
    jurisdiction = entity.get("jurisdiction")

    best: EvidenceRuleProfile | None = None
    best_score = -1
    for profile in ruleset.profiles:
        score = 0
        if profile.customer_type and profile.customer_type != customer_type:
            continue
        score += 1
        if profile.risk_rating:
            if profile.risk_rating != risk_rating:
                continue
            score += 4
        if profile.jurisdiction:
            if profile.jurisdiction != jurisdiction:
                continue
            score += 2
        if score > best_score:
            best = profile
            best_score = score
    if best:
        return best
    # Fallback: map risk rating onto default individual profile.
    defaults = {profile.risk_rating: profile for profile in default_ruleset().profiles if profile.risk_rating}
    return defaults.get(risk_rating) or default_ruleset().profiles[0]



def _load_entities_and_objects(sqlite_path: Path) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        entities = [dict(row) for row in conn.execute("SELECT * FROM entities ORDER BY entity_id").fetchall()]
        objects_by_entity: dict[str, list[dict[str, Any]]] = {entity["entity_id"]: [] for entity in entities}
        for row in conn.execute("SELECT * FROM objects ORDER BY entity_id, snapshot_id, document_type, filename").fetchall():
            item = dict(row)
            objects_by_entity.setdefault(item["entity_id"], []).append(item)
        return entities, objects_by_entity
    finally:
        conn.close()



def evaluate_entity_completeness(entity: dict[str, Any], objects: list[dict[str, Any]], ruleset: EvidenceRuleset) -> dict[str, Any]:
    profile = choose_profile(entity, ruleset)
    checklist: list[dict[str, Any]] = []
    for required in profile.required_evidence:
        matches = [row for row in objects if _object_matches_required(row, required)]
        checklist.append({
            "required_evidence": required,
            "present": bool(matches),
            "match_count": len(matches),
            "matching_object_ids": [row.get("object_id") for row in matches[:10]],
            "matching_filenames": sorted({str(row.get("filename")) for row in matches if row.get("filename")})[:10],
        })
    missing = [item["required_evidence"] for item in checklist if not item["present"]]
    present = [item["required_evidence"] for item in checklist if item["present"]]
    return {
        "entity_id": entity.get("entity_id"),
        "display_name": entity.get("display_name"),
        "jurisdiction": entity.get("jurisdiction"),
        "risk_rating": entity.get("risk_rating"),
        "occupation": entity.get("occupation"),
        "customer_type": _infer_customer_type(entity),
        "ruleset_id": ruleset.ruleset_id,
        "ruleset_name": ruleset.name,
        "profile": profile.profile,
        "required_count": len(profile.required_evidence),
        "present_count": len(present),
        "missing_count": len(missing),
        "complete": not missing,
        "present_evidence": present,
        "missing_evidence": missing,
        "checklist": checklist,
        "evidence_count": len(objects),
    }



def evaluate_completeness(
    sqlite_path: Path,
    root: Path | None = None,
    ruleset_id: str | None = None,
    entity_id: str | None = None,
    risk_rating: str | None = None,
    jurisdiction: str | None = None,
    missing_item: str | None = None,
) -> dict[str, Any]:
    root = root or sqlite_path.parent.parent
    rulesets = load_rulesets(root)
    ruleset = next((item for item in rulesets if item.ruleset_id == ruleset_id), rulesets[0])
    entities, objects_by_entity = _load_entities_and_objects(sqlite_path)
    rows = []
    for entity in entities:
        if entity_id and entity.get("entity_id") != entity_id:
            continue
        if risk_rating and entity.get("risk_rating") != risk_rating:
            continue
        if jurisdiction and entity.get("jurisdiction") != jurisdiction:
            continue
        result = evaluate_entity_completeness(entity, objects_by_entity.get(entity["entity_id"], []), ruleset)
        if missing_item and missing_item not in result["missing_evidence"]:
            continue
        rows.append(result)
    summary = {
        "ruleset_id": ruleset.ruleset_id,
        "ruleset_name": ruleset.name,
        "customers_evaluated": len(rows),
        "complete_customers": sum(1 for row in rows if row["complete"]),
        "incomplete_customers": sum(1 for row in rows if not row["complete"]),
        "total_missing_items": sum(row["missing_count"] for row in rows),
    }
    return {"summary": summary, "rows": rows, "ruleset": ruleset.to_dict()}



def export_completeness_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "completeness_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Evidence Completeness Report",
        "",
        f"Ruleset: {report.get('summary', {}).get('ruleset_name', '')}",
        f"Customers evaluated: {report.get('summary', {}).get('customers_evaluated', 0)}",
        f"Incomplete customers: {report.get('summary', {}).get('incomplete_customers', 0)}",
        "",
        "| Customer | Risk | Jurisdiction | Complete | Missing evidence |",
        "|---|---|---|---|---|",
    ]
    for row in report.get("rows", []):
        lines.append(
            f"| {row.get('entity_id')} {row.get('display_name', '')} | {row.get('risk_rating', '')} | "
            f"{row.get('jurisdiction', '')} | {'Yes' if row.get('complete') else 'No'} | "
            f"{', '.join(row.get('missing_evidence', [])) or '-'} |"
        )
    (output_dir / "COMPLETENESS_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return output_dir
