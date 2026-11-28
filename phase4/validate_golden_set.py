"""Validate the golden-set schema and evidence provenance."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VALID_MODALITIES = {"text", "table", "image"}
VALID_CATEGORIES = {"normal", "edge", "adversarial"}
VALID_EDGE_TYPES = {
    "out-of-scope",
    "prompt-injection",
    "no-evidence",
    "ambiguous",
    "multi-doc",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def get_doc_name(case: dict[str, Any]) -> str:
    return str(case.get("doc_name") or case.get("source_doc") or "")


def get_answer(case: dict[str, Any]) -> str:
    return str(case.get("expected_answer") or case.get("ground_truth_answer") or "")


def validate_golden_set(golden_path: Path, parsed_path: Path) -> dict[str, Any]:
    """Return validity summary, invalid cases, and coverage breakdowns."""
    cases = load_json(golden_path)
    parsed = load_json(parsed_path)

    if not isinstance(cases, list):
        return {"valid": False, "invalid_cases": [{"id": "<root>", "errors": ["golden set must be a JSON list"]}]}

    source_pages: defaultdict[str, set[int]] = defaultdict(set)
    modalities: Counter[str] = Counter()
    for element in parsed:
        if not isinstance(element, dict):
            continue
        doc_name = str(element.get("doc_name") or "")
        page = element.get("page_or_slide")
        if doc_name and page is not None:
            try:
                source_pages[doc_name].add(int(page))
            except (TypeError, ValueError):
                pass

    invalid_cases: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    modality_counts: Counter[str] = Counter()

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            invalid_cases.append({"id": f"case_{index}", "errors": ["case must be an object"]})
            continue

        case_id = str(case.get("id") or f"case_{index}")
        errors: list[str] = []
        question = str(case.get("question") or "").strip()
        answer = get_answer(case).strip()
        modality = str(case.get("modality") or "").strip().lower()
        doc_name = get_doc_name(case)
        page = case.get("page_or_slide")

        if not question:
            errors.append("missing question")
        if not answer:
            errors.append("missing expected answer (expected_answer or ground_truth_answer)")
        if modality not in VALID_MODALITIES:
            errors.append(f"invalid modality: {modality or '<missing>'}")
        if not doc_name:
            errors.append("missing doc_name/source_doc")

        try:
            page_int = int(page)
        except (TypeError, ValueError):
            page_int = -1
            errors.append("missing or invalid page_or_slide")

        if doc_name and doc_name not in source_pages:
            errors.append("source document not found in parsed_elements.json")
        elif doc_name and page_int not in source_pages[doc_name]:
            errors.append("source page_or_slide not found in parsed_elements.json")

        category = str(case.get("category") or "normal").strip().lower()
        if category not in VALID_CATEGORIES:
            errors.append(f"invalid category: {category}")

        if case.get("category") is not None:
            category_counts[category] += 1
        else:
            category_counts["normal"] += 1

        modality_counts[modality if modality in VALID_MODALITIES else "invalid"] += 1

        if category in {"edge", "adversarial"}:
            edge_type = str(case.get("edge_type") or "").strip().lower()
            if edge_type not in VALID_EDGE_TYPES:
                errors.append(f"missing or invalid edge_type: {edge_type or '<missing>'}")
            if not case.get("provenance"):
                errors.append("edge/adversarial case missing provenance")
        elif "provenance" not in case:
            # Provenance is optional for legacy normal cases; report warning later.
            pass

        if errors:
            invalid_cases.append({"id": case_id, "errors": errors})

    return {
        "valid": not invalid_cases,
        "total_cases": len(cases),
        "valid_cases": len(cases) - len(invalid_cases),
        "invalid_cases": invalid_cases,
        "modality_breakdown": dict(sorted(modality_counts.items())),
        "category_breakdown": dict(sorted(category_counts.items())),
        "provenance_missing": [
            str(case.get("id") or f"case_{index}")
            for index, case in enumerate(cases)
            if isinstance(case, dict) and not case.get("provenance")
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 4 golden-set evidence")
    parser.add_argument("--golden", type=Path, default=Path("data/golden_set.json"))
    parser.add_argument("--parsed", type=Path, default=Path("data/parsed_elements.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = validate_golden_set(args.golden, args.parsed)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
