"""Evidence item construction and validation boundaries."""

from bidded.evidence.company_profile import (
    CompanyProfileEvidenceUpsertResult,
    build_company_profile_evidence_items,
    upsert_company_profile_evidence,
)
from bidded.evidence.contract_clause_tags import (
    CONTRACT_CLAUSE_TAGS,
    ContractClauseTag,
    ContractClauseTagMatch,
    match_contract_clause_tags,
)
from bidded.evidence.regulatory_glossary import (
    REGULATORY_GLOSSARY,
    RegulatoryGlossaryEntry,
    RegulatoryGlossaryMatch,
    match_regulatory_glossary,
)
from bidded.evidence.tender_document import (
    TenderClauseSegment,
    TenderEvidenceCandidate,
    TenderEvidenceUpsertResult,
    build_tender_clause_segments,
    build_tender_evidence_candidates,
    build_tender_evidence_items,
    get_tender_evidence_item_by_key,
    upsert_tender_evidence_items,
)

__all__ = [
    "CompanyProfileEvidenceUpsertResult",
    "CONTRACT_CLAUSE_TAGS",
    "REGULATORY_GLOSSARY",
    "ContractClauseTag",
    "ContractClauseTagMatch",
    "RegulatoryGlossaryEntry",
    "RegulatoryGlossaryMatch",
    "TenderClauseSegment",
    "TenderEvidenceCandidate",
    "TenderEvidenceUpsertResult",
    "build_company_profile_evidence_items",
    "build_tender_clause_segments",
    "build_tender_evidence_candidates",
    "build_tender_evidence_items",
    "get_tender_evidence_item_by_key",
    "match_contract_clause_tags",
    "match_regulatory_glossary",
    "upsert_company_profile_evidence",
    "upsert_tender_evidence_items",
]
