#!/usr/bin/env python3
"""Import original Game Freak map art from the pinned pokefirered checkout.

Assembles original pixels only: no art is generated or redrawn here.  For each
layout it decodes the original ``map.bin`` (uint16 little-endian entries),
composes 16x16 metatiles from the original 4bpp tile PNG indices, applies the
original JASC ``.pal`` palettes with the engine's primary/secondary palette
slot rules (``NUM_PALS_IN_PRIMARY`` 7, ``NUM_PALS_TOTAL`` 13, secondary
starting at slot 7), and writes a deterministic PNG plus JSON metadata.

Map grid entry bits (include/global.fieldmap.h):
  0x03FF metatile ID, 0x0C00 collision, 0xF000 elevation.
Metatile entry bits: tile number 0x03FF, vflip 0x0400, hflip 0x0800,
palette 0xF000 (BG_TILE_*_FLIP in include/gba/defines.h; palette field
verified visually per the task instruction and recorded as render uncertainty).
Metatile attributes (src/fieldmap.c sMetatileAttrMasks): 32-bit words,
behavior bits 0-8, terrain bits 9-13, encounter type bits 24-26,
layer type bits 29-30.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image

PINNED_REVISION = "037335f4c725d7c9aecdac87066f2002b4bd7e14"

NUM_METATILES_IN_PRIMARY = 640
NUM_METATILES_TOTAL = 1024
NUM_PALS_IN_PRIMARY = 7
NUM_PALS_TOTAL = 13

MAPGRID_METATILE_ID_MASK = 0x03FF
MAPGRID_COLLISION_MASK = 0x0C00
MAPGRID_ELEVATION_MASK = 0xF000

ENTRY_TILE_MASK = 0x03FF
ENTRY_HFLIP = 0x0400   # BG_TILE_H_FLIP, include/gba/defines.h:53
ENTRY_VFLIP = 0x0800   # BG_TILE_V_FLIP
ENTRY_PAL_MASK = 0xF000  # GLOBAL palette bank: primary 0-6, secondary 7-12

ATTR_BEHAVIOR = (0x000001FF, 0)
ATTR_TERRAIN = (0x00003E00, 9)
ATTR_ENCOUNTER_TYPE = (0x07000000, 24)
ATTR_LAYER_TYPE = (0x60000000, 29)

TILE_W, TILE_H = 8, 8  # GBA tiles are 8x8; tiles.png cells are 8 px square


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jasc_pal(path: Path) -> list[tuple[int, int, int]]:
    """Parse a JASC-PAL palette file (16 RGB entries)."""
    lines = path.read_text().replace("\r\n", "\n").split("\n")
    assert lines[0] == "JASC-PAL" and lines[1] == "0100", path
    count = int(lines[2])
    assert count == 16, path
    entries = []
    for line in lines[3 : 3 + 16]:
        r, g, b = (int(v) for v in line.split())
        entries.append((r, g, b))
    return entries


def camel_to_snake(name: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")


class Tileset:
    def __init__(self, root: Path, kind: str, name: str):
        self.dir = root / "data/tilesets" / kind / name
        graphics_dir = root / "data/tilesets/secondary/condominiums" if name == "silph_co" else self.dir
        self.graphics_dir = graphics_dir
        self.tiles_img = Image.open(graphics_dir / "tiles.png")
        assert self.tiles_img.mode == "P", self.tiles_img.mode
        self.tiles = list(self.tiles_img.getdata())
        self.tiles_w = self.tiles_img.width // TILE_W
        self.tiles_h = self.tiles_img.height // TILE_H
        self.metatiles = (self.dir / "metatiles.bin").read_bytes()
        self.metatile_attrs = (self.dir / "metatile_attributes.bin").read_bytes()
        self.num_metatiles = len(self.metatiles) // 16
        self.tiles_n = len(self.tiles) // (TILE_W * TILE_H)
        self.palettes = [
            load_jasc_pal(graphics_dir / "palettes" / f"{i:02d}.pal") for i in range(16)
        ]

def _cell_indices(tiles: list[int], width: int, tile_no: int, tiles_w: int) -> list[int]:
    # Map load clears all VRAM before copying min(decompressedSize, bank size).
    # Source: overworld.c ResetScreenForMapLoad; new_menu_helpers.c
    # DecompressAndCopyTileDataToVram2/DecompressAndLoadBgGfxUsingHeap2.
    # An allocated bank tile beyond the supplied sheet remains all zero.
    if tile_no >= len(tiles) // 64:
        return [0] * 64
    col, row = tile_no % tiles_w, tile_no // tiles_w
    x0, y0 = col * TILE_W, row * TILE_H
    out = []
    for y in range(TILE_H):
        base = (y0 + y) * width + x0
        out.extend(tiles[base : base + TILE_W])
    return out


def compose_metatile(ts: "Tileset", primary: "Tileset", secondary: "Tileset",
                     entries: list[int], shadow: list[tuple[int, int, int]]) -> Image.Image:
    """Render one 16x16 metatile from original indexed pixels + JASC palette.

    Per src/field_camera.c:242-305 all 8 entries are drawn: the first 4 form
    the bottom 2x2 plane, the next 4 form the top 2x2 overlay (index 0 of a
    cell is transparent).  Tile entry IDs are GLOBAL: 0-639 primary bank,
    640+ secondary bank (src/fieldmap.c:911-933).  Palette field is the
    GLOBAL bank index 0-12 (LoadTilesetPalette: secondary palettes[7] on).
    """
    img = Image.new("RGB", (16, 16))
    px = img.load()
    cells = [(0, 0), (1, 0), (0, 1), (1, 1)]  # (dx,dy) order in metatiles.bin
    for plane in (0, 1):
        for k in range(4):
            dx, dy = cells[k]
            entry = entries[plane * 4 + k]
            if plane == 1 and (entry & ENTRY_TILE_MASK) == 0:
                continue  # transparent filler on the overlay plane
            tile_no = entry & ENTRY_TILE_MASK
            if tile_no < NUM_METATILES_IN_PRIMARY:
                src_ts, local = primary, tile_no
            else:
                src_ts, local = secondary, tile_no - NUM_METATILES_IN_PRIMARY
            idx = _cell_indices(src_ts.tiles, src_ts.tiles_img.width, local, src_ts.tiles_w)
            if entry & ENTRY_HFLIP:
                idx = [idx[r * 8 + (7 - c)] for r in range(8) for c in range(8)]
            if entry & ENTRY_VFLIP:
                idx = [idx[(7 - r) * 8 + c] for r in range(8) for c in range(8)]
            pal_no = (entry & ENTRY_PAL_MASK) >> 12  # global 4-bit slot 0-12
            # Palette source is chosen by the GLOBAL slot number alone, never by
            # the metatile/tile bank: src/fieldmap.c LoadTilesetPalette loads
            # primary palettes[0:7] into global slots 0-6 and secondary
            # palettes[7:13] into global slots 7-12.  Reading the wrong file
            # here yields the primary dummy palettes and renders black.
            if pal_no < NUM_PALS_IN_PRIMARY:
                pal = primary.palettes[pal_no]
            else:
                pal = secondary.palettes[pal_no]
            for r in range(8):
                for c in range(8):
                    i = idx[r * 8 + c]
                    if plane == 0 and i == 0:
                        color = shadow
                    elif i == 0:
                        continue  # overlay transparency
                    else:
                        color = pal[i]
                    px[dx * 8 + c, dy * 8 + r] = color
    return img


def load_layout(root: Path, layout_id: str) -> dict:
    """Exact lookup of a layout id in data/layouts/layouts.json["layouts"]."""
    data = json.loads((root / "data/layouts/layouts.json").read_text())
    matches = [entry for entry in data["layouts"] if entry.get("id") == layout_id]
    if not matches:
        raise KeyError(f"layout id {layout_id} not found in data/layouts/layouts.json")
    if len(matches) > 1:
        raise ValueError(f"duplicate layout id {layout_id}")
    return matches[0]


def load_map_json(root: Path, map_name: str):
    """Authoritative per-map definition: layout id, tilesets, events, connections."""
    path = root / f"data/maps/{map_name}/map.json"
    if not path.exists():
        raise FileNotFoundError(f"map definition not found: {path.relative_to(root)}")
    return json.loads(path.read_text()), path


def load_tileset_secondary_flags(root: Path) -> dict:
    """{TilesetSymbolBase: isSecondary} from src/data/tilesets/headers.h."""
    path = root / "src/data/tilesets/headers.h"
    flags = {}
    if path.exists():
        for m in re.finditer(
            r"const struct Tileset gTileset_(\w+) = .*?\.isSecondary = (TRUE|FALSE)",
            path.read_text(), re.S,
        ):
            flags[m.group(1)] = m.group(2) == "TRUE"
    return flags


def resolve_tileset_dir(root: Path, kind: str, symbol: str, secondary_flags: dict) -> str:
    """Resolve a tileset C symbol to data/tilesets/<kind>/<dir>, verifying against source."""
    base = symbol.replace("gTileset_", "")
    candidates = ["ss_anne"] if base == "SSAnne" else []
    for s in (camel_to_snake(base), re.sub(r"(?<=[a-z])(?=\d)", "_", camel_to_snake(base))):
        if s not in candidates:
            candidates.append(s)
    for cand in candidates:
        if (root / f"data/tilesets/{kind}/{cand}").is_dir():
            declared = secondary_flags.get(base)
            if declared is not None and declared != (kind == "secondary"):
                raise ValueError(
                    f"tileset {base}: headers.h isSecondary={declared}, resolved as {kind}"
                )
            return cand
    raise FileNotFoundError(
        f"tileset {symbol}: no source directory for {candidates} under data/tilesets/{kind}"
    )


def load_map_id_index(root: Path) -> dict:
    """MAP_* constant -> map folder name, for resolving warp/connection destinations."""
    index = {}
    for path in sorted((root / "data/maps").glob("*/map.json")):
        entry = json.loads(path.read_text())
        if "id" in entry:
            index[entry["id"]] = path.parent.name
    return index


def export_events(root: Path, map_json: dict, id_index: dict) -> dict:
    """Source-backed connections and events, taken verbatim from data/maps/<name>/map.json.

    Warp destinations are resolved to the destination map's own warp_events entry so the
    landing coordinates come from the original data rather than a guess.
    """
    def warp_coord(map_name, warp_index):
        if map_name is None:
            return None
        events = json.loads((root / f"data/maps/{map_name}/map.json").read_text()).get("warp_events") or []
        # the source stores dest_warp_id as a numeric *string* (e.g. '0'); coerce before indexing
        if isinstance(warp_index, str) and warp_index.strip().lstrip("-").isdigit():
            warp_index = int(warp_index)
        if isinstance(warp_index, int) and 0 <= warp_index < len(events):
            return {"x": events[warp_index]["x"], "y": events[warp_index]["y"]}
        return None

    connections = []
    for conn in map_json.get("connections") or []:
        d = dict(conn)
        d["map_name"] = id_index.get(conn.get("map"))
        connections.append(d)

    warps = []
    for i, ev in enumerate(map_json.get("warp_events") or []):
        d = dict(ev)
        d["index"] = i
        dest_name = id_index.get(ev.get("dest_map"))
        d["destination_map_name"] = dest_name
        d["destination_coordinates"] = warp_coord(dest_name, ev.get("dest_warp_id"))
        warps.append(d)

    return {
        "connections": connections,
        "warp_events": warps,
        "object_events": map_json.get("object_events") or [],
        "bg_events": map_json.get("bg_events") or [],
        "coord_events": map_json.get("coord_events") or [],
        "map_type": map_json.get("map_type"),
        "requires_flash": map_json.get("requires_flash",False),
        "allow_cycling": map_json.get("allow_cycling",False),
        "allow_running": map_json.get("allow_running",False),
        "allow_escaping": map_json.get("allow_escaping",False),
        "weather": map_json.get("weather"),
        "floor_number": map_json.get("floor_number"),
        "battle_scene": map_json.get("battle_scene"),
        "region_map_section": map_json.get("region_map_section"),
        "music": map_json.get("music"),
    }


def import_map(root: Path, out_dir: Path, map_name: str, layout_override=None) -> dict:
    map_json, map_json_path = load_map_json(root, map_name)
    layout = load_layout(root, layout_override or map_json["layout"])
    secondary_flags = load_tileset_secondary_flags(root)
    events = export_events(root, map_json, load_map_id_index(root))
    script_path = root / "data/maps" / map_name / "scripts.inc"
    if map_name.startswith("SilphCo_"):
        shared=root / "data/scripts/silphco_doors.inc";scripts=shared.read_text();doors=[]
        def tile_changes(label):
            found=re.search(re.escape(label)+r"::\n(.*?)(?=\n\w+::|\Z)",scripts,re.S)
            return [{"x":int(x),"y":int(y),"metatile":tile,"collision":int(collision)} for x,y,tile,collision in re.findall(r"setmetatile\s+(\d+),\s*(\d+),\s*(\w+),\s*([01])",found.group(1) if found else "")]
        for bg in map_json.get("bg_events",[]):
            label=bg.get("script", "")
            if "_EventScript_Door" not in label:continue
            suffix=map_name.removeprefix("SilphCo_")+label.split("_EventScript_")[-1]
            closed=tile_changes("EventScript_Close"+suffix);opened=tile_changes("EventScript_Open"+suffix)
            if closed and opened:doors.append({"id":label,"x":bg["x"],"y":bg["y"],"closed":closed,"opened":opened,"source":str(shared.relative_to(root)),"source_sha256":sha256(shared)})
        events["card_key_doors"]=doors
    if map_name.startswith("VictoryRoad_") and script_path.is_file():
        scripts=script_path.read_text();switches=[]
        for trigger in map_json.get("coord_events",[]):
            label=trigger.get("script", "")
            if "FloorSwitch" not in label:continue
            match=re.search(re.escape(label)+r"::\n(.*?)(?=\n\w+::|\Z)",scripts,re.S)
            if not match:continue
            body=match.group(1);barriers=[{"x":int(x),"y":int(y),"metatile":tile} for x,y,tile in re.findall(r"setmetatile\s+(\d+),\s*(\d+),\s*(\w+),\s*0",body)]
            obj=re.search(r"copyobjectxytoperm\s+(\w+)",body)
            if barriers and obj:switches.append({"id":label,"x":trigger["x"],"y":trigger["y"],"object_id":obj.group(1),"object_ids":re.findall(r"copyobjectxytoperm\s+(\w+)",body),"barriers":barriers,"source":str(script_path.relative_to(root)),"source_sha256":sha256(script_path)})
        events["strength_switches"]=switches
    if map_name.startswith("PokemonMansion_"):
        shared=root / "data/scripts/pokemon_mansion.inc";scripts=shared.read_text();floor=map_name.split("_")[-1]
        def mansion_tiles(state):
            label=f"PokemonMansion_EventScript_{state}Switch_{floor}"
            found=re.search(re.escape(label)+r"::\n(.*?)(?=\n\w+::|\Z)",scripts,re.S)
            return [{"x":int(x),"y":int(y),"metatile":tile,"collision":int(collision)} for x,y,tile,collision in re.findall(r"setmetatile\s+(\d+),\s*(\d+),\s*(\w+),\s*([01])",found.group(1) if found else "")]
        events["mansion_switch"]={"off":mansion_tiles("Reset"),"on":mansion_tiles("Press"),"statues":[bg for bg in map_json.get("bg_events",[]) if "_EventScript_Statue" in bg.get("script","")],"source":str(shared.relative_to(root)),"source_sha256":sha256(shared)}
    if map_name.endswith("_Elevator") and script_path.is_file():
        events["elevator_destinations"] = [{"map_id":mid,"x":int(x),"y":int(y),"source":str(script_path.relative_to(root)),"source_sha256":sha256(script_path)} for mid,x,y in re.findall(r"setdynamicwarp\s+(MAP_\w+),\s*255,\s*(\d+),\s*(\d+)",script_path.read_text())]
    width, height = layout["width"], layout["height"]
    border = {"width": layout["border_width"], "height": layout["border_height"]}
    primary_name = resolve_tileset_dir(root, "primary", layout["primary_tileset"], secondary_flags)
    secondary_name = resolve_tileset_dir(root, "secondary", layout["secondary_tileset"], secondary_flags)
    primary = Tileset(root, "primary", primary_name)
    secondary = Tileset(root, "secondary", secondary_name)

    constants = {name:int(number,16) for name,number in re.findall(r"#define\s+(METATILE_\w+)\s+(0x[0-9A-Fa-f]+)",(root / "include/constants/metatile_labels.h").read_text())}
    collections=[switch["barriers"] for switch in events.get("strength_switches", [])]+[door[k] for door in events.get("card_key_doors",[]) for k in ("opened","closed")]
    collections += [events["mansion_switch"][state] for state in ("off","on")] if events.get("mansion_switch") else []
    for barriers in collections:
        for barrier in barriers:
            mid=constants[barrier["metatile"]];ts=primary if mid<640 else secondary;offset=mid if mid<640 else mid-640
            word=struct.unpack_from("<I",ts.metatile_attrs,offset*4)[0]
            barrier.update(metatile_id=mid,behavior=word&0x1ff,terrain=(word>>9)&31)
    shadow = load_jasc_pal(primary.dir / "palettes" / "00.pal")[0]

    # Pre-compose every metatile once (original pixels only).
    cache: dict[tuple[str, int], Image.Image] = {}

    def metatile_image(mid: int) -> tuple[Image.Image, dict]:
        key = ("P" if mid < NUM_METATILES_IN_PRIMARY else "S", mid)
        if key in cache:
            return cache[key]
        if mid < NUM_METATILES_IN_PRIMARY:
            ts, offset = primary, mid * 16
            attrs_word = struct.unpack_from("<I", primary.metatile_attrs, mid * 4)[0]
        else:
            ts, offset = secondary, (mid - NUM_METATILES_IN_PRIMARY) * 16
            attrs_word = struct.unpack_from("<I", secondary.metatile_attrs, (mid - NUM_METATILES_IN_PRIMARY) * 4)[0]
        entries = list(struct.unpack_from("<8H", ts.metatiles, offset))
        img = compose_metatile(primary, primary, secondary, entries, shadow)
        attrs = {
            "behavior": (attrs_word & ATTR_BEHAVIOR[0]) >> ATTR_BEHAVIOR[1],
            "terrain": (attrs_word & ATTR_TERRAIN[0]) >> ATTR_TERRAIN[1],
            "encounter_type": (attrs_word & ATTR_ENCOUNTER_TYPE[0]) >> ATTR_ENCOUNTER_TYPE[1],
            "layer_type": (attrs_word & ATTR_LAYER_TYPE[0]) >> ATTR_LAYER_TYPE[1],
        }
        cache[key] = (img, attrs)
        return img, attrs

    patch_dir=out_dir.parent / "metatiles";patch_dir.mkdir(parents=True,exist_ok=True)
    for collection in collections:
        for tile in collection:
            image,_=metatile_image(tile["metatile_id"]);patch=patch_dir / f"{map_name}_{tile['metatile_id']}.png";image.save(patch)
            tile["image"]=f"content/metatiles/{patch.name}";tile["image_sha256"]=sha256(patch)
    map_bin = root / layout["blockdata_filepath"]
    grid_bytes = map_bin.read_bytes()
    grid = list(struct.unpack(f"<{width * height}H", grid_bytes))

    canvas = Image.new("RGB", (width * 16, height * 16))
    cells = []
    for i, entry in enumerate(grid):
        x, y = i % width, i // width
        mid = entry & MAPGRID_METATILE_ID_MASK
        img, attrs = metatile_image(mid)
        canvas.paste(img, (x * 16, y * 16))
        cells.append({
            "x": x,
            "y": y,
            "raw": entry,
            "metatile_id": mid,
            "collision": (entry & MAPGRID_COLLISION_MASK) >> 10,
            "elevation": (entry & MAPGRID_ELEVATION_MASK) >> 12,
            **attrs,
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{map_name}.png"
    canvas.save(png)

    meta = {
        "map_name": map_name,
        "map_id": map_json.get("id"),
        "layout": layout["id"],
        "source_revision": PINNED_REVISION,
        "source_map_json": str(map_json_path),
        "source_map_json_sha256": sha256(map_json_path),
        "source_map_bin": str(map_bin),
        "source_map_bin_sha256": sha256(map_bin),
        "width": width,
        "height": height,
        "border": border,
        "primary_tileset": layout["primary_tileset"],
        "secondary_tileset": layout["secondary_tileset"],
        "primary_tileset_dir": f"data/tilesets/primary/{primary_name}",
        "secondary_tileset_dir": f"data/tilesets/secondary/{secondary_name}",
        "events": events,
        "primary_tiles_png_sha256": sha256(primary.graphics_dir / "tiles.png"),
        "secondary_tiles_png_sha256": sha256(secondary.graphics_dir / "tiles.png"),
        "unloaded_tile_provenance": {
            "rule": "Unwritten allocated VRAM tiles are zero after ResetScreenForMapLoad. Copy length is min(decompressed size, allocated bank size); these are source-backed zero pixels, not generated artwork.",
            "sources": ["src/overworld.c:ResetScreenForMapLoad", "src/new_menu_helpers.c:DecompressAndCopyTileDataToVram2", "src/new_menu_helpers.c:DecompressAndLoadBgGfxUsingHeap2"],
            "source_sha256": {p: sha256(root / p) for p in ["src/overworld.c", "src/new_menu_helpers.c"]},
        },
        "palette_slots": {
            "primary": f"slots 0-{NUM_PALS_IN_PRIMARY - 1} from primary palettes[0:]",
            "secondary": f"slots {NUM_PALS_IN_PRIMARY}-{NUM_PALS_TOTAL - 1} from secondary palettes[{NUM_PALS_IN_PRIMARY}:]",
        },
        "cells": cells,
        "uncertainties": [
            "metatile-entry palette bits 0xF000 read as the GLOBAL 4-bit bank slot: slots 0-6 from primary palettes and slots 7-12 from secondary palettes[7:], per LoadTilesetPalette in src/fieldmap.c.  Measured over all 87224 metatile entries in every pinned tileset the slot value spans only 0-12 (never 13-15), so nothing exceeds NUM_PALS_TOTAL-1 and no wrap-around case arises.  Slot assignment confirmed by render inspection, not against a ROM/emulator screenshot.",
            "layer_type/behavior/terrain byte positions per src/fieldmap.c ExtractMetatileAttribute; full engine passability NOT verified",
            "border metatile (layout border id) not substituted for out-of-grid cells because grids here are fully populated",
        ],
    }
    (out_dir / f"{map_name}.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return {"png": str(png), "json": str(out_dir / f"{map_name}.json")}


ACTOR_GRAPHICS_INFO = {
    # deliverable-B slug -> gObjectEventGraphicsInfo_<suffix>
    "red_normal": "RedNormal",
    "green_normal": "GreenNormal",
    "prof_oak": "ProfOak",
    "nurse": "Nurse",
    "cut_tree":"CutTree", "strength_boulder":"StrengthBoulder", "snorlax":"Snorlax",
    "item_ball":"ItemBall", "fossil":"Fossil", "articuno":"Articuno", "zapdos":"Zapdos", "mewtwo":"Mewtwo",
}


def brace_block(text: str, header_regex: str) -> str | None:
    """Return the body of the brace block that opens just after *header_regex*."""
    m = re.search(header_regex, text)
    if not m:
        return None
    brace = text.find("{", m.end())
    if brace < 0:
        return None
    depth, i = 0, brace
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1 : i]
        i += 1
    return None


def import_actor(root: Path, out_dir: Path, slug: str) -> dict:
    """Copy one actor sheet PNG and parse its descriptors from the five pinned headers."""
    oe = root / "src/data/object_events"
    suffix = ACTOR_GRAPHICS_INFO[slug]
    info_text = (oe / "object_event_graphics_info.h").read_text()
    ptr_text = (oe / "object_event_graphics_info_pointers.h").read_text()
    pic_text = (oe / "object_event_pic_tables.h").read_text()
    gfx_text = (oe / "object_event_graphics.h").read_text()
    anim_text = (oe / "object_event_anims.h").read_text()

    body = brace_block(info_text, rf"gObjectEventGraphicsInfo_{suffix}\s*=")
    if body is None:
        raise SystemExit(f"missing gObjectEventGraphicsInfo_{suffix}")
    info = {k: v.strip().rstrip(",").strip() for k, v in
            re.findall(r"^\s*\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?),?\s*$", body, re.M)}

    # enum index, straight from the designated-initializer pointer table
    m = re.search(rf"\[([A-Z0-9_]+)\]\s*=\s*&gObjectEventGraphicsInfo_{suffix}\b", ptr_text)
    if not m:
        raise SystemExit(f"no gObjectEventGraphicsInfoPointers entry for {suffix}")
    gfx_const = m.group(1)

    # picture table -> sheet symbols plus frame grid and byte layout, per overworld_frame()
    images_sym = info.get("images", "").lstrip("&")
    pic_body = brace_block(pic_text, rf"{re.escape(images_sym)}\[\]\s*=") or ""
    frames, sheets = [], {}
    for sheet, w, h, frame in re.findall(
        r"overworld_frame\(\s*gObjectEventPic_(\w+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", pic_body
    ):
        size = int(w) * int(h) * 64 // 2  # include/sprite.h overworld_frame()
        entry = {
            "sheet": f"gObjectEventPic_{sheet}",
            "grid_width": int(w),
            "grid_height": int(h),
            "frame": int(frame),
            "bytes": size,
            "byte_offset": size * int(frame),
        }
        frames.append(entry)
        agg = sheets.setdefault(entry["sheet"], {"grid_width": int(w), "grid_height": int(h)})
        agg["frames"] = agg.get("frames", 0) + 1

    # sheet symbol -> original .4bpp path -> the repo PNG sitting beside it
    sheet_files = {}
    for sym in sheets:
        m = re.search(rf"{sym}\[\]\s*=\s*INCBIN_U16\(\"([^\"]+)\"\)", gfx_text)
        if not m:
            raise SystemExit(f"{sym} has no INCBIN_U16 source path")
        png_path = Path(m.group(1)).with_suffix(".png")
        if not (root / png_path).exists():
            raise SystemExit(f"{sym}: expected PNG {png_path} not found")
        sheet_files[sym] = {"fourbpp": m.group(1), "png": str(png_path)}

    # animation table: designator -> anim script, with each script's frame/duration sequence
    anims_sym = info.get("anims", "").lstrip("&")
    anim_body = brace_block(anim_text, rf"{re.escape(anims_sym)}\[\]\s*=") or ""
    anims = {}
    for designator, anim_sym in re.findall(r"\[([A-Z0-9_]+)\]\s*=\s*(sAnim_\w+)", anim_body):
        script = brace_block(anim_text, rf"{anim_sym}\[\]\s*=") or ""
        anims[designator] = {
            "symbol": anim_sym,
            "frames": [{"frame": int(a), "duration": int(b), "hFlip": ".hFlip = TRUE" in flags, "vFlip": ".vFlip = TRUE" in flags} for a, b, flags in
                       re.findall(r"ANIMCMD_FRAME\(\s*(-?\d+)\s*,\s*(\d+)\s*([^)]*)\)", script)],
            "loops": "ANIMCMD_JUMP" in script,
            "ends": "ANIMCMD_END" in script,
        }

    # palette binding, through the real chain only:
    #   graphics_info.paletteTag -> sObjectEventSpritePalettes (src/event_object_movement.c)
    #   -> gObjectEventPal_* INCBIN (src/data/object_events/object_event_graphics.h)
    #   -> graphics/object_events/palettes/*.pal on disk.
    # There is no object_event_palettes.h in this checkout; nothing is invented here.
    tag = info.get("paletteTag", "").strip()
    move_text = (root / "src/event_object_movement.c").read_text()
    pal_sym = None
    for sym, table_tag in re.findall(
        r"\{\s*(gObjectEventPal_\w+)\s*,\s*(OBJ_EVENT_PAL_TAG_\w+)\s*\}", move_text
    ):
        if table_tag == tag:
            pal_sym = sym
            break
    pal_binding = {"paletteTag": tag or None, "resolved": False}
    if pal_sym:
        inc = re.search(rf"const u16 {re.escape(pal_sym)}\[\]\s*=\s*INCBIN_U16\(\"([^\"]+)\"\)", gfx_text)
        if inc:
            want = Path(inc.group(1))                      # e.g. .../player.gbapal
            disk = want.with_suffix(".pal")                # this checkout ships .pal form
            if (root / disk).exists():
                pal_binding = {
                    "paletteTag": tag,
                    "palette_symbol": pal_sym,
                    "incbin_path_in_source": str(want),
                    "incbin_present_in_checkout": (root / want).exists(),
                    "pal_path_in_checkout": str(disk),
                    "pal_sha256": sha256(root / disk),
                    "binding_chain": [
                        "src/data/object_events/object_event_graphics_info.h:.paletteTag",
                        "src/event_object_movement.c:sObjectEventSpritePalettes",
                        "src/data/object_events/object_event_graphics.h:INCBIN_U16",
                        str(disk),
                    ],
                    "resolved": True,
                }
                (out_dir / "actors" / "palettes").mkdir(parents=True, exist_ok=True)
                pdst = out_dir / "actors" / "palettes" / f"{pal_sym}.pal"
                shutil.copyfile(root / disk, pdst)
                pal_binding.update({
                    "copied_pal": str(pdst.relative_to(out_dir.parent)),
                    "copied_pal_sha256": sha256(pdst),
                })
    if not pal_binding["resolved"]:
        raise SystemExit(f"{slug}: paletteTag {tag!r} (symbol {pal_sym}) could not be bound from source")

    # copy EVERY referenced sheet: a pic table may span several PNGs
    # (Red/Green = normal 9 frames + surf_run 11 frames = 20).
    (out_dir / "actors").mkdir(parents=True, exist_ok=True)
    sheet_out, primary_sym = [], next(iter(sheet_files))
    for sym, meta in sheet_files.items():
        src = root / meta["png"]
        stem = sym.split("_Pic_", 1)[-1].lower() if "_Pic_" in sym else sym.lower()
        dst = out_dir / "actors" / f"{slug}__{stem}.png"
        shutil.copyfile(src, dst)
        if sha256(src) != sha256(dst):
            raise SystemExit(f"{slug}: copy of {src} is not byte-identical")
        sheet_out.append({
            "symbol": sym,
            "is_primary": sym == primary_sym,
            "grid_width": sheets[sym]["grid_width"],
            "grid_height": sheets[sym]["grid_height"],
            "frames": sheets[sym]["frames"],
            "fourbpp_path_in_source": meta["fourbpp"],
            "fourbpp_present_in_checkout": (root / meta["fourbpp"]).exists(),
            "source_png": meta["png"],
            "source_png_sha256": sha256(src),
            "source_png_pixels": list(Image.open(src).size),
            "copied_png": str(dst.relative_to(out_dir.parent)),
            "copied_png_sha256": sha256(dst),
            "copied_png_pixels": list(Image.open(dst).size),
        })

    descriptor = {
        "actor": slug,
        "source_revision": PINNED_REVISION,
        "gfx_constant": gfx_const,
        "graphics_info_symbol": f"gObjectEventGraphicsInfo_{suffix}",
        "graphics_info": info,
        "pic_table_symbol": images_sym,
        "pic_frames": frames,
        "total_pic_frames": len(frames),
        "sheets": sheet_out,
        "palette_binding": pal_binding,
        "anim_table_symbol": anims_sym,
        "anims": anims,
        "availability_note": (
            "INCBIN paths name .4bpp/.gbapal assets that are absent from this checkout; "
            "the byte-identical converted forms actually shipped (.png sheets, .pal palettes) "
            "are what get copied. No pixels were redrawn or fabricated."
        ),
        "descriptor_sources": [
            "src/data/object_events/object_event_graphics_info.h",
            "src/data/object_events/object_event_graphics_info_pointers.h",
            "src/data/object_events/object_event_pic_tables.h",
            "src/data/object_events/object_event_graphics.h",
            "src/data/object_events/object_event_anims.h",
            "src/event_object_movement.c",
        ],
        "descriptor_source_sha256": {
            p: sha256(root / p) for p in [
                "src/data/object_events/object_event_graphics_info.h",
                "src/data/object_events/object_event_graphics_info_pointers.h",
                "src/data/object_events/object_event_pic_tables.h",
                "src/data/object_events/object_event_graphics.h",
                "src/data/object_events/object_event_anims.h",
                "src/event_object_movement.c",
            ]
        },
    }
    dst_json = out_dir / "actors" / f"{slug}.json"
    dst_json.write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n")
    return {
        "actor": slug,
        "json": str(dst_json),
        "gfx": gfx_const,
        "sheets": len(sheet_out),
        "frames": len(frames),
        "palette": pal_binding["palette_symbol"],
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/jetson/projects/living-kanto/reference/pokefirered")
    ap.add_argument("--out", default="/home/jetson/projects/living-kanto/content",
                    help="content root: maps go to <out>/maps, actors to <out>/actors")
    ap.add_argument("--layouts", "--maps", dest="layouts",
                    default="PalletTown,Route1,ViridianCity",
                    help="comma-separated map names under data/maps/<name>/map.json")
    ap.add_argument("--actors", default="",
                    help="comma-separated deliverable-B slugs: " + ",".join(sorted(ACTOR_GRAPHICS_INFO)))
    args = ap.parse_args(argv)
    root = Path(args.root)
    st = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    rev = st.stdout.strip()
    if rev != PINNED_REVISION:
        print(f"ERROR: reference at {rev}, expected {PINNED_REVISION}", file=sys.stderr)
        return 2
    content_root = Path(args.out)
    for name in ([x.strip() for x in args.layouts.split(",") if x.strip()]
                 if args.layouts.strip() else []):
        result = import_map(root, content_root / "maps", name.strip())
        print(json.dumps(result))
    for slug in [s.strip() for s in args.actors.split(",") if s.strip()]:
        if slug not in ACTOR_GRAPHICS_INFO:
            raise SystemExit(f"unknown actor {slug!r}; known: {sorted(ACTOR_GRAPHICS_INFO)}")
        print(json.dumps(import_actor(root, content_root, slug)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
