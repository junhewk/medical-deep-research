from __future__ import annotations

from dataclasses import dataclass

from .models import EvidenceStudy, SourceCatalogEntry


@dataclass(frozen=True)
class SourceDefinition:
    id: str
    name: str
    domain: str
    description: str
    source_type: str = "literature"
    api_key_names: tuple[str, ...] = ()
    requires_api_key: bool = False
    included_by_default: bool = True
    ranked_evidence: bool = True
    peer_reviewed: bool = True
    notes: tuple[str, ...] = ()


LITERATURE_SOURCE_DEFINITIONS: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        id="pubmed",
        name="PubMed",
        domain="biomedical",
        description="MEDLINE/PubMed indexed biomedical literature.",
        api_key_names=("ncbi",),
        notes=("NCBI API key is optional but improves rate limits.",),
    ),
    SourceDefinition(
        id="cochrane",
        name="Cochrane",
        domain="evidence_synthesis",
        description="Cochrane Database of Systematic Reviews surfaced through PubMed.",
        api_key_names=("ncbi",),
        notes=("Restricted to published Cochrane systematic reviews.",),
    ),
    SourceDefinition(
        id="pmc",
        name="PMC",
        domain="biomedical_open_access",
        description="PubMed Central open-access biomedical articles.",
        api_key_names=("ncbi",),
        notes=("NCBI API key is optional but improves rate limits.",),
    ),
    SourceDefinition(
        id="europe_pmc",
        name="Europe PMC",
        domain="biomedical",
        description="Published biomedical literature indexed by Europe PMC.",
    ),
    SourceDefinition(
        id="openalex",
        name="OpenAlex",
        domain="scholarly",
        description="Open scholarly works filtered to articles.",
    ),
    SourceDefinition(
        id="crossref",
        name="Crossref",
        domain="scholarly_metadata",
        description="Published journal-article metadata from Crossref.",
    ),
    SourceDefinition(
        id="semantic_scholar",
        name="Semantic Scholar",
        domain="scholarly",
        description="Academic papers from Semantic Scholar, Medicine-filtered for clinical queries.",
        api_key_names=("semantic_scholar", "semanticscholar"),
        requires_api_key=True,
    ),
    SourceDefinition(
        id="scopus",
        name="Scopus",
        domain="scholarly",
        description="Elsevier Scopus citation database.",
        api_key_names=("scopus",),
        requires_api_key=True,
    ),
    SourceDefinition(
        id="preprints",
        name="Preprints",
        domain="biomedical_preprint",
        description="Preprint literature from Europe PMC preprint records.",
        included_by_default=False,
        peer_reviewed=False,
        notes=(
            "Not peer reviewed; use only as explicitly labelled low-certainty context.",
        ),
    ),
)

AUXILIARY_SOURCE_DEFINITIONS: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        id="clinicaltrials",
        name="ClinicalTrials.gov",
        domain="trial_registry",
        description="Trial registry records, not literature evidence.",
        source_type="registry",
        included_by_default=False,
        ranked_evidence=False,
        peer_reviewed=False,
        notes=(
            "Excluded from EBM evidence ranking; use only for publication-bias context.",
        ),
    ),
)

ALL_SOURCE_DEFINITIONS: tuple[SourceDefinition, ...] = (
    *LITERATURE_SOURCE_DEFINITIONS,
    *AUXILIARY_SOURCE_DEFINITIONS,
)

_SOURCE_BY_NAME: dict[str, SourceDefinition] = {}
for _definition in ALL_SOURCE_DEFINITIONS:
    for _alias in {
        _definition.id,
        _definition.name,
        _definition.name.replace(".", ""),
        _definition.name.replace(" ", "_"),
        _definition.name.replace(" ", "").replace(".", ""),
    }:
        _SOURCE_BY_NAME[_alias.casefold()] = _definition


def source_definition(
    source: str, *, include_auxiliary: bool = True
) -> SourceDefinition | None:
    key = (source or "").strip().casefold()
    if key.startswith("europe_pmc_"):
        key = "europe_pmc"
    elif key.startswith("openalex_"):
        key = "openalex"
    definition = _SOURCE_BY_NAME.get(key)
    if definition is None:
        return None
    if definition.source_type != "literature" and not include_auxiliary:
        return None
    return definition


def canonical_source_name(source: str) -> str | None:
    definition = source_definition(source)
    return definition.name if definition else None


def is_rankable_source_name(source: str) -> bool:
    definition = source_definition(source)
    return bool(definition and definition.ranked_evidence)


def is_rankable_evidence_study(study: EvidenceStudy) -> bool:
    candidates = [study.source, *study.sources]
    return any(is_rankable_source_name(source) for source in candidates if source)


def _clean_key(value: str | None) -> str:
    return (value or "").strip().strip("\"'").strip()


def _credential_status(
    definition: SourceDefinition,
    api_keys: dict[str, str],
    *,
    offline_mode: bool,
) -> str:
    if offline_mode:
        return "offline"
    if not definition.api_key_names:
        return "not_required"
    has_key = any(_clean_key(api_keys.get(name)) for name in definition.api_key_names)
    if definition.requires_api_key:
        return "present" if has_key else "missing"
    return "present_optional" if has_key else "optional_missing"


def source_catalog(
    api_keys: dict[str, str] | None = None,
    *,
    offline_mode: bool = False,
    include_auxiliary: bool = False,
) -> list[SourceCatalogEntry]:
    key_map = api_keys or {}
    definitions = (
        ALL_SOURCE_DEFINITIONS if include_auxiliary else LITERATURE_SOURCE_DEFINITIONS
    )
    entries: list[SourceCatalogEntry] = []
    for definition in definitions:
        credential_status = _credential_status(
            definition,
            key_map,
            offline_mode=offline_mode,
        )
        usable = credential_status not in {"offline", "missing"}
        entries.append(
            SourceCatalogEntry(
                id=definition.id,
                name=definition.name,
                domain=definition.domain,
                description=definition.description,
                source_type=definition.source_type,
                requires_api_key=definition.requires_api_key,
                api_key_names=list(definition.api_key_names),
                credential_status=credential_status,
                enabled=definition.included_by_default and usable,
                included_by_default=definition.included_by_default,
                ranked_evidence=definition.ranked_evidence,
                peer_reviewed=definition.peer_reviewed,
                notes=list(definition.notes),
            )
        )
    return entries
