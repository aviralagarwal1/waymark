from types import SimpleNamespace
import json

import pytest

from evaluations.run_discovery import BASE_TARGET, provenance_fixture
from waymark.discovery import DiscoveryError, research_target
from waymark.discovery.research import Proposal, _page_record, validate_proposal
from waymark.discovery.safety import Document


def test_unsupported_summary_is_not_shown_as_fact():
    target, proposal, records = provenance_fixture("invented_day")
    proposal["summary"] = "CONFIRMED opened on September 1, 2025."
    result = validate_proposal(target, proposal, records)
    assert "CONFIRMED" not in result["summary"]
    assert result["historical_date"] is None


def test_fabricated_employment_type_is_not_exact():
    target, proposal, records = provenance_fixture("exact_day")
    records[0]["text"] = records[0]["text"].replace("FullTime. ", "")
    proposal["claims"][0]["excerpt"] = records[0]["text"]
    result = validate_proposal(target, proposal, records)
    assert result["historical_date"] is None
    assert result["match_status"] != "exact_program"


def test_malformed_proposal_is_reviewable():
    result = validate_proposal(BASE_TARGET, {"claims": "invalid"}, [])
    assert result["status"] == "needs_review"


def test_extraction_uses_fetched_metadata_not_search_page_age():
    payload = {"@type": "JobPosting", "title": "Associate Product Manager", "datePosted": "2025-09-12", "hiringOrganization": {"name": "Example Labs"}, "url": "https://careers.example.org/1"}
    doc = Document("https://careers.example.org/1", '<script type="application/ld+json">' + json.dumps(payload) + '</script>', "text/html")
    record = _page_record(doc, 1)
    assert record["date_facts"][0]["date_meaning"] == "original_posted"
    assert "JobPosting structured data" in record["text"]


def test_complete_research_uses_separate_search_and_extraction(monkeypatch):
    import anthropic
    _, proposal, records = provenance_fixture("exact_day")
    calls = []
    class Messages:
        def create(self, **kwargs):
            calls.append(("search", kwargs))
            return {"content": [{"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": records[0]["url"], "page_age": "2025-01-01"}]}], "usage": {"input_tokens": 1000, "output_tokens": 200, "server_tool_use": {"web_search_requests": 1}}}
        def parse(self, **kwargs):
            calls.append(("extract", kwargs))
            return SimpleNamespace(parsed_output=Proposal.model_validate(proposal), model_dump=lambda: {"usage": {"input_tokens": 2000, "output_tokens": 400}, "stop_reason": "end_turn"})
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            self.messages = Messages()
        def close(self):
            pass
    monkeypatch.setattr(anthropic, "Anthropic", Client)
    monkeypatch.setattr("waymark.discovery.research.safe_fetch", lambda url: Document(url, records[0]["text"], "text/html"))
    result = research_target(BASE_TARGET, api_key="synthetic-test-key")
    assert result["historical_date"] == "2025-09-12"
    assert [kind for kind, _ in calls] == ["search", "extract"]
    assert calls[0][1]["tools"][0]["type"] == "web_search_20250305"
    assert calls[0][1]["tools"][0]["allowed_callers"] == ["direct"]
    assert calls[0][1]["tools"][0]["max_uses"] <= 6
    assert "tools" not in calls[1][1]
    assert result["usage"]["searches"] == 1 and result["usage"]["input_tokens"] == 3000
    assert result["usage"]["estimated_cost_usd"] > 0


def test_budget_blocks_before_any_provider_call(monkeypatch):
    result = research_target(BASE_TARGET, api_key="synthetic-test-key", budget_usd=0.01)
    assert result["usage"]["estimated_cost_usd"] == 0
    assert "budget" in result["summary"].lower()


def test_unknown_model_price_blocks_ai():
    result = research_target(BASE_TARGET, api_key="synthetic-test-key", model="unknown-model")
    assert "price estimate" in result["summary"]


def test_oversized_input_rejected_before_provider():
    with pytest.raises(DiscoveryError):
        research_target({**BASE_TARGET, "notes": "x" * 20_000}, api_key="synthetic-test-key")


def test_job_date_fact_cannot_be_reused_for_different_title():
    target, proposal, records = provenance_fixture("jsonld")
    records[0]["date_facts"][0]["title"] = "Senior Software Engineer"
    assert validate_proposal(target, proposal, records)["historical_date"] is None


def test_conflicting_dates_preserve_both_evidence_records():
    target, proposal, records = provenance_fixture("conflict")
    result = validate_proposal(target, proposal, records)
    assert result["historical_date"] is None
    assert [row["date_value"] for row in result["evidence"]] == ["2025-09-12", "2025-09-13"]


def test_date_in_unrelated_sentence_cannot_be_opening_date():
    target, proposal, records = provenance_fixture("exact_day")
    text = records[0]["text"].replace("Applications opened September 12, 2025.", "Applications opened recently. This article was updated September 12, 2025.")
    records[0]["text"] = text
    proposal["claims"][0]["excerpt"] = text
    assert validate_proposal(target, proposal, records)["historical_date"] is None
