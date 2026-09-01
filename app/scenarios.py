"""Frozen demo scenarios. PLAN.MD sections 33 and 38.

PLAN.MD section 35 has ChatGPT invent the itinerary while section 38 demands stable
rehearsed values. Those conflict. Resolution: the engine accepts whatever items
ChatGPT sends, but a named scenario_id resolves to this frozen itinerary so the
rehearsed run is reproducible.
"""

from __future__ import annotations

from functools import lru_cache

import yaml
from pydantic import TypeAdapter

from app import config
from app.models.planning import Itinerary

_ITINERARY = TypeAdapter(Itinerary)


@lru_cache(maxsize=8)
def load_scenario(scenario_id: str) -> Itinerary:
    path = config.DATA / "itineraries" / f"{scenario_id}.yaml"
    if not path.exists():
        raise KeyError(f"Unknown scenario {scenario_id!r}")
    return _ITINERARY.validate_python(yaml.safe_load(path.read_text()))
