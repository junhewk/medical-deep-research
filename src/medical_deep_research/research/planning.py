from __future__ import annotations

import re

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


def normalize_query(query: str) -> str:
    return " ".join(query.strip().split())


def extract_keywords(query: str, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for token in re.split(r"\s+", normalize_query(query).replace(",", " ")):
        lowered = token.strip().lower().strip("()[]{}.:;!?")
        if len(lowered) < 4 or lowered in STOP_WORDS or lowered in seen:
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
    databases = ["PubMed", "OpenAlex", "Semantic Scholar"]
    if classify_domain(query) == "clinical":
        databases.insert(1, "Cochrane")
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


def build_pubmed_query(query: str, keywords: list[str]) -> str:
    # Use the most specific keywords (skip generic ones) for title/abstract search
    specificity_keywords = [kw for kw in keywords if kw not in {"what", "current", "evidence", "using", "role", "best", "recent", "effect", "impact"}]
    terms = specificity_keywords[:6] or keywords[:6]
    tagged_terms = [f"{quote_term(term)}[tiab]" for term in terms]
    if tagged_terms:
        return " AND ".join(tagged_terms)
    return sanitize_pubmed_query(query)


def convert_to_scopus_query(pubmed_query: str) -> str:
    query = re.sub(r"\[(tiab|mh|pt|tw|majr|mesh|all)\]", "", pubmed_query, flags=re.I)
    query = re.sub(r"\s+", " ", query).strip()
    terms = [token.strip('" ') for token in re.split(r"\bAND\b|\bOR\b|\bNOT\b|[()]", query) if token.strip('" ')]
    unique_terms: list[str] = []
    seen: set[str] = set()
    for term in terms:
        lowered = term.lower()
        if lowered in STOP_WORDS or lowered in seen:
            continue
        seen.add(lowered)
        unique_terms.append(quote_term(term))
    if not unique_terms:
        return ""
    return f"TITLE-ABS-KEY({' AND '.join(unique_terms)})"


def build_query_plan(query: str, query_type: str, provider: str) -> QueryPlan:
    normalized_query = normalize_query(query)
    keywords = extract_keywords(normalized_query, limit=10)
    domain = classify_domain(normalized_query)
    databases = suggest_databases(normalized_query, provider)
    pubmed_query = build_pubmed_query(normalized_query, keywords)

    source_queries = {
        "PubMed": pubmed_query,
        "OpenAlex": normalized_query,
        "Semantic Scholar": normalized_query,
        "Cochrane": f"{normalized_query} AND systematic review",
    }
    scopus_query = convert_to_scopus_query(pubmed_query)
    if scopus_query:
        source_queries["Scopus"] = scopus_query

    notes = [
        f"Domain classified as `{domain}`.",
        "PubMed query uses title/abstract terms only in the deterministic pipeline.",
    ]
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

