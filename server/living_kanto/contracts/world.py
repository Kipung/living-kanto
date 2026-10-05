"""WorldDefinition: maps, rules, content versions, seed, population.

Immutable at run creation. A run's WorldDefinition digest is stored in run
metadata so two runs claiming the same world can be proven identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import (
    CONTRACTS_VERSION,
    Contract,
    ContractError,
    as_versioned_dict,
    content_hash,
    require_bool,
    require_id,
    require_int,
    require_list,
    require_mapping,
    require_string,
)

MAX_POPULATION = 256


@dataclass(slots=True)
class ContentSource:
    """One pinned upstream source. Usage terms are recorded, never inferred."""

    source_id: str
    repository: str
    revision: str
    paths: tuple[str, ...] = ()
    usage_terms: str = ""
    note: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContentSource":
        payload = as_versioned_dict(data, kind="content_source")
        return cls(
            source_id=require_id(payload.get("source_id"), "content_source.source_id"),
            repository=require_string(payload.get("repository"), "content_source.repository", max_len=500),
            revision=require_string(payload.get("revision"), "content_source.revision", max_len=200),
            paths=tuple(
                require_string(p, "content_source.paths[]", max_len=500)
                for p in require_list(payload.get("paths"), "content_source.paths", max_items=4096)
            ),
            usage_terms=require_string(payload.get("usage_terms") or "unspecified", "content_source.usage_terms", max_len=4000),
            note=str(payload.get("note") or "")[:2000],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "content_source",
            "source_id": self.source_id,
            "repository": self.repository,
            "revision": self.revision,
            "paths": list(self.paths),
            "usage_terms": self.usage_terms,
            "note": self.note,
        }


@dataclass(slots=True)
class MapRef:
    """A map the world declares available. Geometry arrives with the content pack."""

    map_id: str
    name: str
    region: str = "kanto"
    indoor: bool = False
    connections: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MapRef":
        payload = as_versioned_dict(data, kind="map_ref")
        return cls(
            map_id=require_id(payload.get("map_id"), "map_ref.map_id"),
            name=require_string(payload.get("name"), "map_ref.name", max_len=200),
            region=require_string(payload.get("region") or "kanto", "map_ref.region", max_len=100),
            indoor=require_bool(payload.get("indoor", False), "map_ref.indoor"),
            connections=tuple(
                require_mapping(c, "map_ref.connections[]")
                for c in require_list(payload.get("connections"), "map_ref.connections", max_items=64)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "map_ref",
            "map_id": self.map_id,
            "name": self.name,
            "region": self.region,
            "indoor": self.indoor,
            "connections": [dict(c) for c in self.connections],
        }


@dataclass(slots=True)
class WorldDefinition(Contract):
    """The full, immutable specification of a run's world."""

    world_id: str = ""
    name: str = ""
    seed: int = 0
    schema_version: int = CONTRACTS_VERSION
    rules_version: int = 1
    content_versions: dict[str, int] = field(default_factory=dict)
    maps: tuple[MapRef, ...] = ()
    population_size: int = 0
    species_roster: tuple[str, ...] = ()
    sources: tuple[ContentSource, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "WorldDefinition":
        self.world_id = require_id(self.world_id, "world_definition.world_id")
        self.name = require_string(self.name, "world_definition.name", max_len=200)
        self.seed = require_int(self.seed, "world_definition.seed", minimum=0, maximum=2**63 - 1)
        self.check_version()
        self.rules_version = require_int(
            self.rules_version, "world_definition.rules_version", minimum=1, maximum=1_000_000
        )
        if not isinstance(self.content_versions, Mapping):
            raise ContractError("world_definition.content_versions must be an object")
        self.content_versions = {
            require_id(k, "world_definition.content_versions key"): require_int(
                v, f"world_definition.content_versions[{k}]", minimum=1, maximum=1_000_000
            )
            for k, v in self.content_versions.items()
        }
        self.maps = tuple(MapRef.from_dict(m) if not isinstance(m, MapRef) else m for m in self.maps)
        self.population_size = require_int(
            self.population_size, "world_definition.population_size", minimum=0, maximum=MAX_POPULATION
        )
        self.species_roster = tuple(
            require_id(s, "world_definition.species_roster[]") for s in self.species_roster
        )
        if len(set(self.species_roster)) != len(self.species_roster):
            raise ContractError("world_definition.species_roster contains duplicates")
        self.sources = tuple(
            ContentSource.from_dict(s) if not isinstance(s, ContentSource) else s for s in self.sources
        )
        seen = {s.source_id for s in self.sources}
        if len(seen) != len(self.sources):
            raise ContractError("world_definition.sources contains duplicate source_id values")
        self.extra = require_mapping(self.extra, "world_definition.extra")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorldDefinition":
        payload = as_versioned_dict(data, kind="world_definition")
        return cls(
            world_id=str(payload.get("world_id") or ""),
            name=str(payload.get("name") or ""),
            seed=payload.get("seed", 0),
            schema_version=require_int(
                payload.get("schema_version", CONTRACTS_VERSION),
                "world_definition.schema_version",
                minimum=1,
                maximum=CONTRACTS_VERSION,
            ),
            rules_version=payload.get("rules_version", 1),
            content_versions=require_mapping(payload.get("content_versions"), "world_definition.content_versions"),
            maps=tuple(
                MapRef.from_dict(m) for m in require_list(payload.get("maps"), "world_definition.maps", max_items=2048)
            ),
            population_size=payload.get("population_size", 0),
            species_roster=tuple(
                require_list(payload.get("species_roster"), "world_definition.species_roster", max_items=1024)
            ),
            sources=tuple(
                ContentSource.from_dict(s)
                for s in require_list(payload.get("sources"), "world_definition.sources", max_items=256)
            ),
            extra=require_mapping(payload.get("extra"), "world_definition.extra"),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "world_definition",
            "schema_version": self.schema_version,
            "world_id": self.world_id,
            "name": self.name,
            "seed": self.seed,
            "rules_version": self.rules_version,
            "content_versions": dict(self.content_versions),
            "maps": [m.to_dict() for m in self.maps],
            "population_size": self.population_size,
            "species_roster": list(self.species_roster),
            "sources": [s.to_dict() for s in self.sources],
            "extra": dict(self.extra),
        }

    @property
    def definition_hash(self) -> str:
        return content_hash(self.to_dict())
