#!/usr/bin/env python3
"""Deliverable C: deterministic asset manifest with SHA-256 provenance.

Walks content/maps and content/actors, hashing every produced artifact and
carrying the source-revision provenance recorded by import_original_assets.py.
Deterministic: sorted keys, sorted paths, no timestamps.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONTENT = REPO / "content"
PINNED_REVISION = "037335f4c725d7c9aecdac87066f2002b4bd7e14"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(path: Path) -> dict:
    e = {
        "path": str(path.relative_to(REPO)),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }
    if path.suffix == ".json":
        try:
            e["keys"] = sorted(json.loads(path.read_text()))
        except Exception:
            pass
    return e


def main() -> int:
    if not CONTENT.is_dir():
        print(f"ERROR: {CONTENT} missing; run import_original_assets.py first", file=sys.stderr)
        return 2

    maps, actors = [], []
    for p in sorted((CONTENT / "maps").glob("*")) if (CONTENT / "maps").is_dir() else []:
        if p.suffix.lower() in (".png", ".json"):
            maps.append(entry(p))
    actor_dir = CONTENT / "actors"
    if actor_dir.is_dir():
        for p in sorted(actor_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".png", ".json", ".pal"):
                actors.append(entry(p))

    # Pull provenance that the importer already embedded in each map meta file.
    provenance = {}
    for m in maps:
        if not m["path"].endswith(".json"):
            continue
        meta = json.loads((REPO / m["path"]).read_text())
        name = Path(m["path"]).stem
        provenance[name] = {
            "source_revision": meta.get("source_revision"),
            "source_map_json": meta.get("source_map_json"),
            "source_map_json_sha256": meta.get("source_map_json_sha256"),
            "source_map_bin": meta.get("source_map_bin"),
            "source_map_bin_sha256": meta.get("source_map_bin_sha256"),
            "primary_tileset": meta.get("primary_tileset"),
            "secondary_tileset": meta.get("secondary_tileset"),
            "primary_tiles_png_sha256": meta.get("primary_tiles_png_sha256"),
            "secondary_tiles_png_sha256": meta.get("secondary_tiles_png_sha256"),
            "uncertainties": meta.get("uncertainties", []),
        }

    actor_prov = {}
    source_files = {}
    for a in actors:
        if not a["path"].endswith(".json") or "/palettes/" in a["path"]:
            continue
        d = json.loads((REPO / a["path"]).read_text())
        pal = d.get("palette_binding", {})
        actor_prov[d["actor"]] = {
            "source_revision": d.get("source_revision"),
            "gfx_constant": d.get("gfx_constant"),
            "graphics_info_symbol": d.get("graphics_info_symbol"),
            "pic_table_symbol": d.get("pic_table_symbol"),
            "anim_table_symbol": d.get("anim_table_symbol"),
            "total_pic_frames": d.get("total_pic_frames"),
            "sheets": [
                {
                    "symbol": s.get("symbol"),
                    "is_primary": s.get("is_primary"),
                    "frames": s.get("frames"),
                    "source_png": s.get("source_png"),
                    "source_png_sha256": s.get("source_png_sha256"),
                    "fourbpp_path_in_source": s.get("fourbpp_path_in_source"),
                    "fourbpp_present_in_checkout": s.get("fourbpp_present_in_checkout"),
                    "copied_png": s.get("copied_png"),
                    "copied_png_sha256": s.get("copied_png_sha256"),
                }
                for s in d.get("sheets", [])
            ],
            "palette": {
                "paletteTag": pal.get("paletteTag"),
                "palette_symbol": pal.get("palette_symbol"),
                "binding_chain": pal.get("binding_chain"),
                "incbin_path_in_source": pal.get("incbin_path_in_source"),
                "incbin_present_in_checkout": pal.get("incbin_present_in_checkout"),
                "pal_path_in_checkout": pal.get("pal_path_in_checkout"),
                "pal_sha256": pal.get("pal_sha256"),
                "copied_pal": pal.get("copied_pal"),
                "copied_pal_sha256": pal.get("copied_pal_sha256"),
            },
            "anims": d.get("anims"),
            "availability_note": d.get("availability_note"),
        }
        for src, digest in sorted(d.get("descriptor_source_sha256", {}).items()):
            source_files.setdefault(src, {"sha256": digest, "used_by": []})["used_by"].append(d["actor"])
        for s in d.get("sheets", []):
            source_files.setdefault(s["source_png"], {
                "sha256": s["source_png_sha256"], "used_by": []})["used_by"].append(d["actor"])
        if pal.get("pal_path_in_checkout"):
            source_files.setdefault(pal["pal_path_in_checkout"], {
                "sha256": pal["pal_sha256"], "used_by": []})["used_by"].append(d["actor"])

    all_unc = sorted({u for v in provenance.values() for u in v["uncertainties"]})
    all_unc.append(
        "prof_oak: sAnimTable_Standard includes ANIM_RAISE_HAND -> sAnim_RaiseHand, "
        "which selects pic frame 9, but sPicTable_ProfOak defines only frames 0-8. "
        "This is faithful to the pinned source (object_event_anims.h:306, "
        "object_event_pic_tables.h:794); the engine must not assume every anim in an "
        "actor's table is drawable from its pic table."
    )

    manifest = {
        "generator": "tools/build_asset_manifest.py",
        "source_repo": "pret/pokefirered",
        "source_revision": PINNED_REVISION,
        "note": ("Original Game Boy Advance FireRed assets converted to PNG plus "
                 "source-derived metadata. Artwork is copyrighted Nintendo/Game Freak "
                 "property obtained from the pinned private checkout; it is NOT open "
                 "licensed. No artwork was generated or redrawn."),
        "maps": maps,
        "actors": actors,
        "terrain_patches": [entry(p) for p in sorted((CONTENT/"metatiles").glob("*.png"))],
        "alternate_layouts": [entry(p) for p in sorted((CONTENT/"layouts").glob("*")) if p.suffix in {".png",".json"}],
        "map_provenance": provenance,
        "actor_provenance": actor_prov,
        "actor_source_files": {k: source_files[k] for k in sorted(source_files)},
        "uncertainties": sorted(all_unc),
        "scope_limits": [
            "Static source terrain renders plus original actor animation descriptors; client composes source human and environmental sprite frames.",
            "Actors are raw source PNG sheets plus metadata; source PNG palette "
            "colors are retained; exhaustive cartridge raster equivalence is not claimed.",
            "Anim scripts are reproduced as source data and standard facing/walking playback is "
            "implemented; exhaustive animation verification remains open. Where a source anim selects a pic frame the actor's "
            "pic table does not define, the gap is recorded rather than filled with a "
            "fabricated frame.",
            "Binary .4bpp/.gbapal forms named by the source INCBIN directives are absent "
            "from this checkout; the shipped .png/.pal equivalents are used and hashed, "
            "and each descriptor records fourbpp_present_in_checkout=false.",
            "Mainland inventory has 256 maps and static renders are imported. School tile704 uses source-proven zero-filled VRAM after map reset; this rationale is preserved in both affected metadata files.",
        ],
    }

    out = CONTENT / "asset_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out.relative_to(REPO)}: {len(maps)} map files, {len(actors)} actor files")
    for m in maps:
        if m["path"].endswith(".png"):
            print(f"  {m['path']} {m['sha256'][:16]} {m['bytes']}B")
    for a in actors:
        if a["path"].endswith(".png"):
            print(f"  {a['path']} {a['sha256'][:16]} {a['bytes']}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
