"""Source map classification for consensual personal battles.

Personal duels are a shared-world adaptation: permit them outdoors, in caves,
and in interiors that the extracted FireRed events identify as trainer venues.
Source scripted/official battles have separate authorization and do not use
this gate (Oak's introductory rival battle does not authorize casual lab duels).
Unknown content fails closed. This policy only gates new duels, never turns in
an already accepted battle.
"""

OUTDOOR_OR_CAVE_TYPES = frozenset({
    "MAP_TYPE_ROUTE", "MAP_TYPE_TOWN", "MAP_TYPE_CITY",
    "MAP_TYPE_OCEAN_ROUTE", "MAP_TYPE_UNDERGROUND",
})
LEAGUE_ROOMS = frozenset({
    "PokemonLeague_LoreleisRoom", "PokemonLeague_BrunosRoom",
    "PokemonLeague_AgathasRoom", "PokemonLeague_LancesRoom",
    "PokemonLeague_ChampionsRoom",
})


def personal_duel_allowed(game_map):
    if game_map is None:
        return False
    events = game_map.events
    if events.get("map_type") in OUTDOOR_OR_CAVE_TYPES:
        return True
    if events.get("map_type") != "MAP_TYPE_INDOOR":
        return False
    # Civic services and homes stay peaceful even if future content adds a
    # battle-capable resident. Special scripted battles still use their own path.
    name = game_map.map_id
    if any(part in name for part in ("House", "Lab", "Mart", "PokemonCenter", "DepartmentStore")):
        return False
    if name in LEAGUE_ROOMS:
        return True
    return any(obj.get("trainer_type") == "TRAINER_TYPE_NORMAL"
               for obj in events.get("object_events", []))
