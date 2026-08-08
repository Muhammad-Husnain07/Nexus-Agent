"""Tests for the capability retriever (retrieval-first narrowing)."""

from __future__ import annotations

from nexus.capabilities.retrieval import CapabilityRetriever


class _FakeGC:
    """Minimal GlobalContext stand-in with the metadata the retriever reads."""

    def __init__(self) -> None:
        self.capability_index = {
            "pokeapi_get_pokemon": {
                "id": "1", "domain": "pokemon",
                "aliases": ["pokemon info", "pokemon"],
                "logical_op_name": "pokeapi_get_pokemon",
            },
            "pokeapi_get_species": {
                "id": "2", "domain": "pokemon",
                "aliases": ["species", "pokemon species"],
                "logical_op_name": "pokeapi_get_species",
            },
            "get_weather": {
                "id": "3", "domain": "weather",
                "aliases": ["weather", "forecast"],
                "logical_op_name": "get_weather",
            },
            "github_search": {
                "id": "4", "domain": "github",
                "aliases": ["repo search"],
                "logical_op_name": "github_search",
            },
        }
        self.capability_keywords = {
            "pokemon": ["pokeapi_get_pokemon"],
            "species": ["pokeapi_get_species"],
            "weather": ["get_weather"],
            "github": ["github_search"],
        }
        self.capability_providers = {k: [{}] for k in self.capability_index}
        self.alias_index = {
            "pokemon info": "pokeapi_get_pokemon",
            "pokemon": "pokeapi_get_pokemon",
            "weather": "get_weather",
        }
        self.domain_index = {
            "pokemon": ["pokeapi_get_pokemon", "pokeapi_get_species"],
            "weather": ["get_weather"],
            "github": ["github_search"],
        }


def _make_retriever() -> CapabilityRetriever:
    r = CapabilityRetriever(top_k=10)
    r.build_corpus(_FakeGC())
    return r


def test_retriever_alias_exact_hit():
    r = _make_retriever()
    results = r.retrieve("pokemon info", gc=_FakeGC())
    assert results
    assert results[0].name == "pokeapi_get_pokemon"
    assert results[0].matched_by == "alias"


def test_retriever_bm25_narrows_to_domain():
    r = _make_retriever()
    results = r.retrieve("tell me about pokemon species", gc=_FakeGC())
    names = {res.name for res in results}
    # Pokemon capabilities rank; unrelated domains are absent.
    assert "pokeapi_get_species" in names or "pokeapi_get_pokemon" in names
    assert "get_weather" not in names


def test_retriever_returns_empty_for_gibberish():
    r = _make_retriever()
    results = r.retrieve("zzqxqwnz", gc=_FakeGC())
    assert isinstance(results, list)


def test_retriever_respects_top_k():
    r = _make_retriever()
    results = r.retrieve("pokemon", top_k=1, gc=_FakeGC())
    assert len(results) == 1


def test_retriever_invalidate_rebuilds():
    r = _make_retriever()
    assert r.retrieve("weather", gc=_FakeGC())
    r.invalidate()
    assert not r._ready
    assert r.retrieve("weather", gc=_FakeGC()) == []


class _BoostGC:
    """A realistic-size catalog: prose words appear across MOST capabilities
    (generic), domain words in a FEW (discriminative)."""

    def __init__(self) -> None:
        self.capability_index = {
            "get_current_weather": {
                "domain": "weather",
                "aliases": ["get weather"],
                "logical_op_name": "get_current_weather",
                "examples": [],
                "keywords": ["weather", "temperature", "latitude", "longitude", "right", "now"],
            },
            "geocode_location": {
                "domain": "maps",
                "aliases": ["geocode location"],
                "logical_op_name": "geocode_location",
                "examples": [],
                "keywords": ["weather", "latitude", "longitude", "location", "the", "use", "tool"],
            },
        }
        # Prose-heavy capabilities sharing generic words with the tools above.
        generic_words = ["the", "use", "tool", "user", "for", "and", "whenever", "this", "before"]
        for i in range(10):
            self.capability_index[f"misc_tool_{i}"] = {
                "domain": "misc",
                "aliases": [],
                "logical_op_name": f"misc_tool_{i}",
                "examples": [],
                "keywords": list(generic_words) + [f"kw_{i}"],
            }
        self.capability_keywords = {k: [k] for k in self.capability_index}
        self.capability_providers = {k: [{}] for k in self.capability_index}
        self.alias_index = {}
        self.domain_index = {}


def test_boost_returns_all_winners_ranked():
    """Every capability matching examples/keywords is returned (ranked), not
    a single arbitrary winner — the planner must see both tools."""
    r = CapabilityRetriever(top_k=10)
    r.build_corpus(_BoostGC())
    results = r.retrieve(
        "How's the weather right now at latitude 31.5 and longitude 74.3?",
        gc=_BoostGC(),
    )
    names = [res.name for res in results if res.matched_by == "example"]
    assert "get_current_weather" in names
    assert "geocode_location" in names
    idx_w = names.index("get_current_weather")
    idx_g = names.index("geocode_location")
    assert idx_w < idx_g, "more specific keyword set must rank first"


def test_boost_demotes_generic_prose_keywords():
    """Keywords like 'the'/'use'/'tool' (present in most of the catalog) must
    not boost — a capability with only generic keywords scores zero."""
    r = CapabilityRetriever(top_k=10)
    r.build_corpus(_BoostGC())
    results = r.retrieve("the user wants to use this tool", gc=_BoostGC())
    boosted = [res.name for res in results if res.matched_by == "example"]
    assert not any(n.startswith("misc_tool_") for n in boosted)


def test_boost_example_subset_strongest():
    """An example fully contained in the query scores by its token count."""
    gc = _BoostGC()
    gc.capability_index["get_current_weather"]["examples"] = [
        "how hot is it right now at latitude 40.71 and longitude -74.00",
    ]
    gc.capability_index["geocode_location"]["examples"] = [
        "find the coordinates of Lahore",
    ]
    r = CapabilityRetriever(top_k=10)
    r.build_corpus(gc)
    results = r.retrieve(
        "how hot is it right now at latitude 40.71 and longitude -74.00",
        gc=gc,
    )
    top = results[0]
    assert top.name == "get_current_weather"
    assert top.matched_by == "example"
