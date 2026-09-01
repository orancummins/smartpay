"""The record of what SmartPay has been asked.

The dashboard and the MCP server are separate processes, so this is a file rather
than memory. These tests cover the parts that bit during development: distinct
questions must stay distinct, and rendering a page must not look like a question.
"""

import json

import pytest

from app import history
from app.services.smartpay import SmartPayService


@pytest.fixture
def store(tmp_path):
    """The autouse fixture in conftest already redirects the store; this just names
    the path so a test can inspect the file itself."""
    return tmp_path / "queries.json"


def test_most_recent_first(store):
    history.record({"key": "a", "title": "First"})
    history.record({"key": "b", "title": "Second"})
    assert [e["title"] for e in history.load()] == ["Second", "First"]


def test_reasking_moves_an_entry_up_without_duplicating(store):
    history.record({"key": "a", "title": "Ireland"})
    history.record({"key": "b", "title": "New York"})
    history.record({"key": "a", "title": "Ireland"})
    entries = history.load()
    assert [e["key"] for e in entries] == ["a", "b"]
    assert len(entries) == 2


def test_history_is_capped(store):
    for i in range(history.MAX_ENTRIES + 6):
        history.record({"key": f"k{i}", "title": f"Trip {i}"})
    assert len(history.load()) == history.MAX_ENTRIES


def test_missing_or_corrupt_file_reads_as_empty(store):
    assert history.load() == []
    store.write_text("{ not json")
    assert history.load() == []
    store.write_text('{"not": "a list"}')
    assert history.load() == []


def test_entries_are_stamped(store):
    history.record({"key": "a", "title": "Trip"})
    assert history.load()[0]["asked_at"]


def test_writes_are_atomic_and_leave_no_partial_file(store):
    history.record({"key": "a", "title": "Trip"})
    assert json.loads(store.read_text())
    assert not list(store.parent.glob("tmp*")), "temp file left behind"


# --- integration with the service -------------------------------------------


def test_distinct_itineraries_are_remembered_separately(store):
    """Every ChatGPT itinerary was filed under "custom", so asking about Ireland and
    then New York left only one of them: the second silently replaced the first."""
    service = SmartPayService()
    for title in ("Five nights in Ireland", "Weekend in New York"):
        service.optimise_itinerary(
            "alex",
            {"title": title, "start_date": "2026-11-02",
             "items": [{"label": "Hotel", "merchant": "Hilton", "amount": "900"}]},
        )
    keys = [e["key"] for e in history.load()]
    assert len(keys) == len(set(keys)) == 2
    assert "custom" not in keys


def test_rendering_the_dashboard_is_not_recorded_as_a_question(store):
    """Loading a page is not asking something.

    Recording here would put a phantom entry at the top of the user's own history
    every time the dashboard refreshed -- and it polls.
    """
    from app.dashboard import render_alex_dashboard
    from app.providers.open_finance import SyntheticAlexProvider

    render_alex_dashboard(SyntheticAlexProvider().get_profile("alex"))
    assert history.load() == []


def test_the_dashboard_leads_with_the_most_recent_question(store):
    from app.dashboard import render_alex_dashboard
    from app.providers.open_finance import SyntheticAlexProvider

    service = SmartPayService()
    service.optimise_itinerary()
    service.optimise_itinerary(
        "alex",
        {"title": "Five nights in Ireland", "start_date": "2026-11-02",
         "items": [{"label": "Hotel in Dublin", "merchant": "Hilton", "amount": "1150"}]},
    )

    html = render_alex_dashboard(SyntheticAlexProvider().get_profile("alex"))
    assert "Five nights in Ireland" in html
    assert "Hotel in Dublin" in html, "the most recent enquiry's own detail must be present"
    # The earlier question is still listed, just further down.
    assert "Every distinct enquiry counted toward this total" in html
    assert "Walt Disney World" in html
    assert '<span class="q-tag">Latest</span>' in html
    assert html.index("Five nights in Ireland") < html.index("Walt Disney World"), (
        "the most recent enquiry must lead the list"
    )


def test_an_international_trip_loses_the_domestic_baggage_benefit(store):
    """Ireland is the reason this matters: the same cards, a different answer."""
    service = SmartPayService()
    result = service.optimise_itinerary(
        "alex",
        {"title": "Ireland", "start_date": "2026-11-02",
         "items": [{"label": "Flights", "merchant": "American Airlines", "amount": "2100",
                    "metadata": {"origin": "BOS", "destination": "DUB", "travellers": 2,
                                 "checked_bags": 2, "segments": 2}}]},
    )
    flights = result["data"]["recommendations"][0]
    assert "First checked bag free on American Airlines" not in flights["benefits"]
    assert flights["guaranteed_savings"] == "0.00"
