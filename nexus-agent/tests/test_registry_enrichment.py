"""Tests for registry enrichment: capabilities/produces/consumes/related/cacheable
+ prebuilt search documents."""

from __future__ import annotations

from nexus.capabilities.retrieval import CapabilityRetriever


class _FakeGC:
    def __init__(self) -> None:
        self.capability_index = {
            "pokeapi_get_pokemon": {
                "id": "1",
                "domain": "pokemon",
                "aliases": ["pokemon info"],
                "capabilities": ["retrieve", "pokemon", "game_data"],
                "produces": ["pokemon_data"],
                "consumes": ["pokemon_name"],
                "related": ["pokeapi_get_species"],
                "cacheable": True,
                "description": "Retrieve detailed Pokemon information including stats, abilities, types.",
                "purpose": "Fetch Pokemon data by name.",
                "search_doc": (
                    "pokeapi_get_pokemon pokemon info retrieve pokemon game_data "
                    "pokemon_data pokemon_name pokeapi_get_species "
                    "Retrieve detailed Pokemon information including stats, abilities, types. "
                    "Fetch Pokemon data by name. Tell me about Pikachu"
                ),
                "logical_op_name": "pokeapi_get_pokemon",
            },
            "get_weather": {
                "id": "2",
                "domain": "weather",
                "aliases": ["weather"],
                "capabilities": ["retrieve", "weather"],
                "produces": ["forecast"],
                "consumes": ["city"],
                "related": [],
                "cacheable": False,
                "description": "Get current weather for a city.",
                "purpose": "",
                "search_doc": "get_weather weather retrieve weather forecast city Get current weather for a city.",
                "logical_op_name": "get_weather",
            },
        }
        self.capability_keywords = {}
        self.capability_providers = {k: [{}] for k in self.capability_index}
        self.alias_index = {"pokemon info": "pokeapi_get_pokemon"}
        self.domain_index = {
            "pokemon": ["pokeapi_get_pokemon"],
            "weather": ["get_weather"],
        }


def _make_retriever() -> CapabilityRetriever:
    r = CapabilityRetriever(top_k=10)
    r.build_corpus(_FakeGC())
    return r


def test_search_doc_used_for_bm25():
    """Retrieval should rank by the prebuilt search doc (examples included)."""
    r = _make_retriever()
    res = r.retrieve("Tell me about Pikachu", gc=_FakeGC())
    names = [x.name for x in res]
    assert "pokeapi_get_pokemon" in names[:3]


def test_non_cacheable_flag_surfaces():
    """cacheable=False is part of the capability metadata."""
    gc = _FakeGC()
    assert gc.capability_index["get_weather"]["cacheable"] is False
    assert gc.capability_index["pokeapi_get_pokemon"]["cacheable"] is True


def test_related_and_produces_in_meta():
    gc = _FakeGC()
    meta = gc.capability_index["pokeapi_get_pokemon"]
    assert "pokeapi_get_species" in meta["related"]
    assert "pokemon_data" in meta["produces"]
    assert "pokemon_name" in meta["consumes"]


def test_update_coerce_examples_handles_dicts():
    """ToolUpdate.model_dump already serializes ToolExample to dicts — the
    update path must accept raw dicts without calling .model_dump() on them
    (this was a 500: 'dict' object has no attribute 'model_dump')."""
    from nexus.tools.registry import _coerce_examples
    from nexus.tools.schemas import ToolExample, ToolUpdate

    examples = [
        {
            "user_prompt": "How's the weather?",
            "expected_tool": "get_current_weather",
            "sample_input": {"latitude": 31.5},
        }
    ]
    dumped = ToolUpdate(examples=examples).model_dump(exclude_unset=True)
    assert all(isinstance(e, dict) for e in dumped["examples"])
    coerced = _coerce_examples(dumped["examples"])
    assert coerced == dumped["examples"]

    model_entries = [ToolExample.model_validate(examples[0])]
    coerced_models = _coerce_examples(model_entries)
    assert coerced_models == [
        {
            "user_prompt": "How's the weather?",
            "expected_tool": "get_current_weather",
            "sample_input": {"latitude": 31.5},
            "sample_output": {},
        }
    ]


def test_update_schema_keeps_form_fields():
    """ToolUpdate must carry every field the edit form sends — otherwise
    frontend edits silently drop compensating_operation/idempotent."""
    from nexus.tools.schemas import ToolUpdate

    upd = ToolUpdate(
        compensating_operation="rollback_op",
        idempotent=True,
    ).model_dump(exclude_unset=True)
    assert upd == {
        "compensating_operation": "rollback_op",
        "idempotent": True,
    }


def test_update_schema_drops_tenant_public():
    """tenant_public is dead metadata — it must not be settable via the API."""
    from nexus.tools.schemas import ToolUpdate

    upd = ToolUpdate(tenant_public=True)  # type: ignore[call-arg]
    assert "tenant_public" not in upd.model_dump(exclude_unset=True)


def test_contract_includes_business_rules():
    """Validation rules declared on the tool must surface as business_rules
    in the capability contract — that is what ValidatorNode Tier-3 enforces."""
    from nexus.tools.registry import _build_tool_contract

    class _FakeTool:
        idempotent = False
        risk_level = "high"
        requires_approval = True
        cacheable = False
        capabilities = ["retrieve", "billing"]
        related = ["get_invoice"]
        validation_rules = {"all_of": ["$.amount >= 0", "$.id != null"]}

    contract = _build_tool_contract(_FakeTool())
    assert contract["business_rules"] == {"all_of": ["$.amount >= 0", "$.id != null"]}
    assert contract["risk_level"] == "high"
    assert contract["requires_approval"] is True
    assert contract["cacheable"] is False
    assert contract["capabilities"] == ["retrieve", "billing"]


def test_contract_defaults_when_metadata_missing():
    """Missing metadata degrades to safe defaults — never guesses."""
    from nexus.tools.registry import _build_tool_contract

    class _Minimal:
        idempotent = False
        risk_level = None
        requires_approval = False
        validation_rules = None

    contract = _build_tool_contract(_Minimal())
    assert contract["risk_level"] == "low"
    assert contract["cacheable"] is True
    assert contract["business_rules"] == {}
    assert contract["capabilities"] == []
    assert contract["related"] == []
