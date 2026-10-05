"""Source-derived map grids: walkability and exits from real content JSON.

Walkability convention (from the pret tile-data pipeline as encoded in the
extracted maps): a cell is walkable iff its ``collision`` field is ``0``.
The real content schema (verified against content/maps/PalletTown.json at
source_revision 037335f) has root ``width``/``height``/``map_name`` and an
``events`` DICT containing ``connections`` (list of {direction, map,
map_name, offset} edge links) and ``warp_events`` (list of {x, y, dest_map,
...} door warps). Exits are: warp cells, plus walkable boundary cells in a
direction that has a connection (walking off that edge transfers).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class MapLoadError(ValueError):
    """Raised when a content map file is missing or structurally unusable."""


class GameMap:
    """Immutable walkability grid plus derived exits for one map."""

    def __init__(
        self,
        map_id: str,
        width: int,
        height: int,
        walkable_rows: list[str],
        exits: dict[tuple[int, int], str],
        *,
        display_name: str = "",
        source_path: str = "",
        source_sha256: str = "",
        events: dict | None = None,
        reference_id: str = "",
    ) -> None:
        self.map_id = map_id
        self.width = width
        self.height = height
        self.display_name = display_name
        self.source_path = source_path
        self.source_sha256 = source_sha256
        self._walk = [[ch == "1" for ch in row] for row in walkable_rows]  # [y][x]
        self.exits = dict(exits)
        self.events = events or {}
        self.reference_id = reference_id
        self.source_revision = ""
        self.cells = {}

    @classmethod
    def from_content(cls, map_id: str, path: str | Path) -> "GameMap":
        path = Path(path)
        if not path.is_file():
            raise MapLoadError(f"map file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MapLoadError(f"unreadable map file {path}: {exc}") from exc
        cells = data.get("cells")
        if not isinstance(cells, list) or not cells:
            raise MapLoadError(f"map {map_id}: missing or empty cells")
        width = int(data.get("width", 0) or 0)
        height = int(data.get("height", 0) or 0)
        if width <= 0 or height <= 0:
            width = max(int(c.get("x", -1)) for c in cells) + 1
            height = max(int(c.get("y", -1)) for c in cells) + 1
        if width <= 0 or height <= 0 or len(cells) != width * height:
            raise MapLoadError(
                f"map {map_id}: grid mismatch (cells={len(cells)} vs {width}x{height})")
        grid = [["0"] * width for _ in range(height)]
        for cell in cells:
            x, y = int(cell.get("x", -1)), int(cell.get("y", -1))
            if 0 <= x < width and 0 <= y < height:
                grid[y][x] = "1" if str(cell.get("collision")) == "0" else "0"
        exits: dict[tuple[int, int], str] = {}
        events = data.get("events")
        if isinstance(events, dict):
            for warp in events.get("warp_events") or []:
                if not isinstance(warp, dict):
                    continue
                target = warp.get("dest_map")
                try:
                    x, y = int(warp.get("x")), int(warp.get("y"))
                except (TypeError, ValueError):
                    continue
                if target and 0 <= x < width and 0 <= y < height:
                    exits[(x, y)] = str(target)
                    grid[y][x] = "1"  # a warp cell must be standable
            edge_dirs = {
                "up": "north", "down": "south", "left": "west", "right": "east",
            }
            for conn in events.get("connections") or []:
                if not isinstance(conn, dict):
                    continue
                target = conn.get("map")
                d = edge_dirs.get(str(conn.get("direction")))
                if not target or d is None:
                    continue
                for y in range(height):
                    for x in range(width):
                        on_edge = (
                            (d == "north" and y == 0) or (d == "south" and y == height - 1)
                            or (d == "west" and x == 0) or (d == "east" and x == width - 1)
                        )
                        if on_edge and grid[y][x] == "1":
                            exits.setdefault((x, y), str(target))
        result = cls(
            map_id,
            width,
            height,
            ["".join(row) for row in grid],
            exits,
            display_name=str(data.get("map_name") or map_id),
            source_path=str(path),
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            events=events if isinstance(events, dict) else {},
            reference_id=str(data.get("map_id", "")),
        )

        result.source_revision = str(data.get("source_revision", ""))
        result.cells = {(int(c["x"]),int(c["y"])):dict(c) for c in cells}
        return result

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self._walk[y][x]

    def _step_basic(self, start, direction, surfing=False):
        """Source movement constraints: directional walls, elevations and ledges.

        Ground collision alone is insufficient. Water requires explicit surfing.
        References: metatile_behavior.c sBehaviorSurfable; object movement
        directional function tables and IsElevationMismatchAt; player ledges.
        """
        vectors={"north":(0,-1),"south":(0,1),"east":(1,0),"west":(-1,0)}
        if direction not in vectors:return None
        x,y=start;dx,dy=vectors[direction];n=(x+dx,y+dy)
        if not self.cells:return n if self.is_walkable(*n) else None
        old=self.cells.get((x,y),{});target=self.cells.get(n,{})
        behavior=int(target.get("behavior",0));current=int(old.get("behavior",0))
        blocks={"east":{0x30,0x34,0x36},"west":{0x31,0x35,0x37},"north":{0x32,0x34,0x35},"south":{0x33,0x36,0x37}}
        opposite={"east":"west","west":"east","north":"south","south":"north"}
        if current in blocks[direction] or behavior in blocks[opposite[direction]]:return None
        jumps={"east":0x38,"west":0x39,"north":0x3A,"south":0x3B}
        if behavior in jumps.values():
            if jumps[direction]!=behavior:return None
            n=(x+dx*2,y+dy*2);target=self.cells.get(n,{})
        if not self.is_walkable(*n):return None
        water={0x10,0x11,0x12,0x13,0x15,0x1A,0x1B,0x50,0x51,0x52,0x53}
        if int(target.get("behavior",0)) in water and not surfing:return None
        elevation=int(old.get("elevation",0));landing=int(target.get("elevation",0))
        if elevation!=0 and landing not in (0,15,elevation) and not surfing:return None
        return n

    def step_path(self,start,direction,surfing=False):
        """One input plus source forced spin tiles; returns every traversed tile.

        MB_SPIN_RIGHT/LEFT/UP/DOWN 0x54..57 select momentum direction; 0x58
        stops. Bounded cycles/collisions reject rather than teleporting.
        """
        if self.source_revision and int(self.cells.get(tuple(start),{}).get("behavior",0))==0x66:return None
        first=self._step_basic(start,direction,surfing=surfing)
        if first is None:return None
        path=[first];spin={0x54:'east',0x55:'west',0x56:'north',0x57:'south'}
        behavior=int(self.cells.get(first,{}).get('behavior',0))
        currents={0x50:'east',0x51:'west',0x52:'north',0x53:'south'}
        if surfing and behavior in currents:
            seen=set()
            for _ in range(self.width*self.height*4):
                point=path[-1];behavior=int(self.cells.get(point,{}).get('behavior',0))
                if behavior not in currents:return path
                direction=currents[behavior];key=(point,direction)
                if key in seen:return None
                seen.add(key);nxt=self._step_basic(point,direction,surfing=True)
                if nxt is None:return None
                path.append(nxt)
            return None
        if behavior not in spin:return path
        momentum=spin[behavior];seen=set()
        for _ in range(self.width*self.height*4):
            point=path[-1];behavior=int(self.cells.get(point,{}).get('behavior',0))
            if behavior==0x58:return path
            momentum=spin.get(behavior,momentum);key=(point,momentum)
            if key in seen:return None
            seen.add(key);nxt=self._step_basic(point,momentum,surfing=surfing)
            if nxt is None:return None
            path.append(nxt)
        return None

    def step_destination(self,start,direction,surfing=False):
        path=self.step_path(start,direction,surfing=surfing)
        return path[-1] if path else None

    def exit_target(self, x: int, y: int) -> str | None:
        return self.exits.get((x, y))

    def exit_target_cells(self) -> dict[tuple[int, int], str]:
        return dict(self.exits)

    def first_open_cell(self, near: tuple[int, int] = (0, 0)) -> tuple[int, int]:
        """Deterministically pick a walkable cell with four walkable neighbours."""
        best: tuple[int, int] | None = None
        best_d = -1
        for y in range(self.height):
            for x in range(self.width):
                if not self.is_walkable(x, y):
                    continue
                if all(self.is_walkable(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    d = abs(x - near[0]) + abs(y - near[1])
                    if best is None or d < best_d:
                        best, best_d = (x, y), d
        if best is None:
            raise MapLoadError(f"map {self.map_id}: no open cell available")
        return best

    def content_summary(self) -> dict[str, Any]:
        return {
            "map_id": self.map_id,
            "display_name": self.display_name,
            "width": self.width,
            "height": self.height,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "exit_count": len(self.exits),
        }


def resolve_transfer(maps, current, x: int, y: int, target: str, surfing=False) -> tuple[str, int, int]:
    """Resolve actual source warp landing or offset-aligned adjacent edge.

    Connection offset locates the destination origin relative to the source:
    north/south arrival x = source x - offset; east/west arrival y likewise.
    No nearest-open-cell substitution is allowed.
    """
    origin = maps[current] if isinstance(current, str) else current
    def find(name):
        for key, m in maps.items():
            if name in (key, m.map_id, m.display_name, m.reference_id): return key, m
        raise MapLoadError(f"destination map unavailable: {name}")
    target_key, dest = find(target)
    def matches(name):
        try: return find(name)[0] == target_key
        except MapLoadError: return False
    landing = None
    for w in origin.events.get("warp_events", []):
        if (w.get("x"), w.get("y")) != (x,y): continue
        if not matches(w.get("destination_map_name") or w.get("dest_map")): continue
        try: index=int(w["dest_warp_id"])
        except (KeyError,TypeError,ValueError): raise MapLoadError("dynamic warp destination is unresolved")
        warps=dest.events.get("warp_events", [])
        if not 0 <= index < len(warps): raise MapLoadError("destination warp index unavailable")
        landing=(int(warps[index]["x"]), int(warps[index]["y"])); break
    if landing is None:
        for c in origin.events.get("connections", []):
            if not matches(c.get("map_name") or c.get("map")): continue
            d=c.get("direction");offset=int(c.get("offset",0))
            if d=="up" and y==0: landing=(x-offset,dest.height-1)
            elif d=="down" and y==origin.height-1: landing=(x-offset,0)
            elif d=="left" and x==0: landing=(dest.width-1,y-offset)
            elif d=="right" and x==origin.width-1: landing=(0,y-offset)
            if landing is not None: break
    if landing is None: raise MapLoadError("no source exit to requested destination at this tile")
    if not surfing and int(dest.cells.get(landing,{}).get("behavior",0)) in {0x10,0x11,0x12,0x13,0x15,0x1A,0x1B,0x50,0x51,0x52,0x53}:
        raise MapLoadError("destination requires explicit surfing; on-foot transfer unavailable")
    if not origin.is_walkable(x,y) or not dest.is_walkable(*landing):
        raise MapLoadError("source exit or exact destination tile is blocked")
    return target_key,*landing
