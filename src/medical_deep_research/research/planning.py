from __future__ import annotations

import re
from typing import Any

from .models import QueryPlan


HEALTHCARE_RESEARCH_KEYWORDS = {
    "policy",
    "ethics",
    "informatics",
    "digital health",
    "social care",
    "burnout",
    "implementation",
    "workflow",
    "public health",
    "health literacy",
}

CLINICAL_KEYWORDS = {
    "trial",
    "meta-analysis",
    "systematic review",
    "placebo",
    "mortality",
    "diagnosis",
    "treatment",
    "randomized",
    "randomised",
    "cohort",
    "intervention",
}

STOP_WORDS = {
    "about",
    "adult",
    "adults",
    "among",
    "and",
    "are",
    "between",
    "effects",
    "for",
    "from",
    "into",
    "that",
    "the",
    "their",
    "these",
    "this",
    "with",
}

AI_EDUCATION_TERMS = (
    "AI",
    "artificial intelligence",
    "generative AI",
    "generative artificial intelligence",
    "large language model",
    "large language models",
    "LLM",
    "LLMs",
    "ChatGPT",
    "GPT",
    "chatbot",
    "chatbots",
    "conversational agent",
    "conversational agents",
    "virtual patient",
    "virtual patients",
    "simulated patient",
    "simulated patients",
)

AI_EDUCATION_ACTIVITY_TERMS = (
    "education",
    "medical education",
    "health professions education",
    "training",
    "simulation",
    "coaching",
    "assessment",
    "feedback",
)

COMMUNICATION_SDM_TERMS = (
    "shared decision making",
    "shared decision-making",
    "SDM",
    "communication skills",
    "communication training",
    "medical interview",
    "history taking",
    "breaking bad news",
    "empathy",
    "empathetic communication",
    "patient-centered",
    "patient-centred",
    "patient centered",
    "patient centred",
    "doctor-patient communication",
    "physician-patient communication",
)
FRAMEWORK_LABELS = {
    "population",
    "intervention",
    "comparison",
    "outcome",
    "concept",
    "context",
}
_STRUCTURED_FIELD_ORDER = (
    "population",
    "intervention",
    "comparison",
    "outcome",
    "concept",
    "context",
)
_STRUCTURED_FIELD_RE = re.compile(
    r"\b(population|intervention|comparison|outcome|concept|context)\s*:\s*"
    r"(.*?)(?=\s*;\s*(?:population|intervention|comparison|outcome|concept|context)\s*:|$)",
    re.I | re.S,
)


def normalize_query(query: str) -> str:
    return " ".join(query.strip().split())


def _clean_structured_value(value: Any) -> str:
    text = normalize_query(str(value or ""))
    return "" if text.lower() in {"none", "null", "n/a"} else text


def _structured_fields_from_payload(query_payload: dict[str, Any] | None) -> dict[str, str]:
    if not query_payload:
        return {}
    normalized: dict[str, str] = {}
    aliases = {
        "p": "population",
        "i": "intervention",
        "c": "comparison",
        "o": "outcome",
        "pico_p": "population",
        "pico_i": "intervention",
        "pico_c": "comparison",
        "pico_o": "outcome",
        "pcc_p": "population",
        "pcc_concept": "concept",
        "pcc_context": "context",
    }
    for key, value in query_payload.items():
        target = aliases.get(str(key).lower(), str(key).lower())
        if target not in FRAMEWORK_LABELS:
            continue
        cleaned = _clean_structured_value(value)
        if cleaned:
            normalized[target] = cleaned
    return normalized


def parse_structured_query(query: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _STRUCTURED_FIELD_RE.finditer(query):
        key = match.group(1).lower()
        value = _clean_structured_value(match.group(2))
        if value:
            fields[key] = value
    return fields


def structured_query_text(query: str, query_payload: dict[str, Any] | None = None) -> str:
    fields = _structured_fields_from_payload(query_payload) or parse_structured_query(query)
    values = [fields[key] for key in _STRUCTURED_FIELD_ORDER if fields.get(key)]
    return normalize_query(" ".join(values)) if values else normalize_query(query)


def extract_keywords(query: str, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for token in re.split(r"\s+", normalize_query(query).replace(",", " ")):
        lowered = token.strip().lower().strip("()[]{}.:;!?")
        if len(lowered) < 4 or lowered in STOP_WORDS or lowered in FRAMEWORK_LABELS or lowered in seen:
            continue
        seen.add(lowered)
        keywords.append(lowered)
        if len(keywords) >= limit:
            break
    return keywords or ["medical", "research"]


def classify_domain(query: str) -> str:
    lowered = query.lower()
    healthcare_hits = sum(1 for term in HEALTHCARE_RESEARCH_KEYWORDS if term in lowered)
    clinical_hits = sum(1 for term in CLINICAL_KEYWORDS if term in lowered)
    if healthcare_hits >= 2 and healthcare_hits > clinical_hits:
        return "healthcare_research"
    return "clinical"


def suggest_databases(query: str, provider: str) -> list[str]:
    if classify_domain(query) == "clinical":
        databases = [
            "PubMed",
            "Cochrane",
            "PMC",
            "Europe PMC",
            "OpenAlex",
            "Crossref",
            "Semantic Scholar",
        ]
    else:
        databases = [
            "OpenAlex",
            "Crossref",
            "Semantic Scholar",
            "PubMed",
            "Europe PMC",
            "PMC",
        ]
    if provider != "google":
        databases.append("Scopus")
    return databases


def build_todos(query_type: str, provider: str) -> list[str]:
    framework = "PICO" if query_type == "pico" else "PCC" if query_type == "pcc" else "free-form"
    return [
        f"Interpret the {framework} request and identify the core medical scope",
        "Build constrained queries for each literature source",
        "Search the selected literature databases in a fixed order",
        "Score and deduplicate evidence candidates",
        "Verify identifiers before final synthesis",
        f"Produce the final report through the {provider} runtime adapter",
    ]


def sanitize_pubmed_query(query: str) -> str:
    sanitized = query
    sanitized = sanitized.replace(">=", " ").replace("<=", " ").replace(">", " ").replace("<", " ")
    sanitized = re.sub(r"\be\.g\.\s*", "", sanitized, flags=re.I)
    sanitized = re.sub(r"\bi\.e\.\s*", "", sanitized, flags=re.I)
    sanitized = re.sub(r"%", "", sanitized)
    sanitized = re.sub(r"\bPatients?\s+with\b", "", sanitized, flags=re.I)
    sanitized = re.sub(r"\bSubjects?\s+with\b", "", sanitized, flags=re.I)
    sanitized = re.sub(r"\bIndividuals?\s+with\b", "", sanitized, flags=re.I)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


def quote_term(term: str) -> str:
    return f'"{term}"' if " " in term else term


def _split_structured_terms(value: str, *, limit: int = 8) -> list[str]:
    normalized = sanitize_pubmed_query(value)
    normalized = re.sub(r"\b(or|and)\b", ",", normalized, flags=re.I)
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[,;/]", normalized):
        term = raw.strip(" .")
        if not term:
            continue
        lowered = term.lower()
        if lowered in STOP_WORDS or lowered in seen:
            continue
        seen.add(lowered)
        terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def _expanded_pubmed_terms(term: str) -> list[str]:
    lowered = term.lower().strip()
    expansions = {
        "ai": ["AI", "artificial intelligence"],
        "ai-supported": ["AI", "artificial intelligence"],
        "ai supported": ["AI", "artificial intelligence"],
        "machine learning": ["machine learning"],
        "patient-centered": ["patient-centered", "patient-centred"],
        "patient centered": ["patient-centered", "patient-centred"],
    }
    return expansions.get(lowered, [term])


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _pubmed_group(terms: list[str]) -> str:
    tagged_terms: list[str] = []
    seen: set[str] = set()
    for term in terms:
        for expanded in _expanded_pubmed_terms(term):
            lowered = expanded.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            tagged_terms.append(f"{quote_term(expanded)}[tiab]")
    if not tagged_terms:
        return ""
    if len(tagged_terms) == 1:
        return tagged_terms[0]
    return "(" + " OR ".join(tagged_terms) + ")"


def is_ai_communication_education_query(
    query: str,
    query_type: str | None = None,
    structured_fields: dict[str, str] | None = None,
) -> bool:
    fields = structured_fields or parse_structured_query(query)
    text = " ".join(
        part
        for part in (
            query,
            fields.get("concept", ""),
            fields.get("intervention", ""),
            fields.get("context", ""),
            fields.get("outcome", ""),
        )
        if part
    )
    if query_type and query_type.lower() == "pcc":
        return _contains_any(text, AI_EDUCATION_TERMS) and _contains_any(text, COMMUNICATION_SDM_TERMS)
    return (
        _contains_any(text, AI_EDUCATION_TERMS)
        and _contains_any(text, AI_EDUCATION_ACTIVITY_TERMS)
        and _contains_any(text, COMMUNICATION_SDM_TERMS)
    )


def _ai_communication_pubmed_query() -> str:
    groups = [
        _pubmed_group(list(AI_EDUCATION_TERMS)),
        _pubmed_group(list(AI_EDUCATION_ACTIVITY_TERMS)),
        _pubmed_group(list(COMMUNICATION_SDM_TERMS)),
    ]
    return " AND ".join(group for group in groups if group)


def _ai_communication_general_query() -> str:
    terms = (
        "artificial intelligence",
        "generative AI",
        "large language model",
        "ChatGPT",
        "chatbot",
        "virtual patient",
        "simulated patient",
        "medical education",
        "health professions education",
        "training",
        "simulation",
        "communication skills",
        "communication training",
        "medical interview",
        "shared decision making",
        "empathy",
        "breaking bad news",
        "patient-centered",
    )
    return " ".join(terms)


def _structured_pubmed_query(structured_fields: dict[str, str]) -> str:
    groups: list[str] = []
    concept_text = structured_fields.get("concept") or structured_fields.get("intervention") or ""
    context_text = " ".join(
        value
        for value in (
            structured_fields.get("comparison"),
            structured_fields.get("context"),
            structured_fields.get("outcome"),
        )
        if value
    )
    population_text = structured_fields.get("population", "")

    concept_terms = _split_structured_terms(concept_text, limit=8)
    context_terms = _split_structured_terms(context_text, limit=6)
    population_terms = _split_structured_terms(population_text, limit=3)

    if concept_terms:
        groups.append(_pubmed_group(concept_terms))
    if context_terms:
        groups.append(_pubmed_group(context_terms))
    if not groups and population_terms:
        groups.append(_pubmed_group(population_terms))
    return " AND ".join(group for group in groups if group)


def build_pubmed_query(
    query: str,
    keywords: list[str],
    structured_fields: dict[str, str] | None = None,
    query_type: str | None = None,
) -> str:
    if is_ai_communication_education_query(query, query_type, structured_fields):
        return _ai_communication_pubmed_query()

    if structured_fields:
        structured = _structured_pubmed_query(structured_fields)
        if structured:
            return structured

    # Use a small OR bundle rather than requiring every extracted word to appear.
    specificity_keywords = [
        kw
        for kw in keywords
        if kw not in {"what", "current", "evidence", "using", "role", "best", "recent", "effect", "impact"}
    ]
    terms = specificity_keywords[:6] or keywords[:6]
    group = _pubmed_group(terms)
    if group:
        return group
    return sanitize_pubmed_query(query)


def convert_to_scopus_query(pubmed_query: str) -> str:
    query = re.sub(r"\[(tiab|mh|pt|tw|majr|mesh|all)\]", "", pubmed_query, flags=re.I)
    query = re.sub(r"\s+", " ", query).strip()
    if not query:
        return ""
    return f"TITLE-ABS-KEY({query})"


def build_query_plan(
    query: str,
    query_type: str,
    provider: str,
    query_payload: dict[str, Any] | None = None,
) -> QueryPlan:
    structured_fields = _structured_fields_from_payload(query_payload) or parse_structured_query(query)
    normalized_query = structured_query_text(query, structured_fields)
    keywords = extract_keywords(normalized_query, limit=10)
    classification_query = normalize_query(f"{query} {normalized_query}")
    domain = classify_domain(classification_query)
    databases = suggest_databases(classification_query, provider)
    pubmed_query = build_pubmed_query(normalized_query, keywords, structured_fields, query_type)
    general_query = (
        _ai_communication_general_query()
        if is_ai_communication_education_query(query, query_type, structured_fields)
        else normalized_query
    )

    source_queries = {
        "PubMed": pubmed_query,
        "PMC": pubmed_query,
        "Europe PMC": general_query,
        "OpenAlex": general_query,
        "Crossref": general_query,
        "Semantic Scholar": general_query,
        "Cochrane": pubmed_query,
    }
    scopus_query = convert_to_scopus_query(pubmed_query)
    if scopus_query:
        source_queries["Scopus"] = scopus_query

    notes = [
        f"Domain classified as `{domain}`.",
        "PubMed query uses title/abstract term groups and avoids requiring every PCC/PICO term simultaneously.",
    ]
    if structured_fields:
        notes.append("Structured query fields were used to remove PICO/PCC labels from source searches.")
    if "Scopus" in databases and not scopus_query:
        notes.append("Scopus was requested but no valid Scopus query could be derived.")

    return QueryPlan(
        query=query,
        query_type=query_type,
        provider=provider,
        domain=domain,
        normalized_query=normalized_query,
        keywords=keywords,
        databases=databases,
        todos=build_todos(query_type, provider),
        source_queries=source_queries,
        notes=notes,
    )
