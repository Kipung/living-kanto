"""M0 engine slice: private observations, legal-action construction, atomic commits.

Architecture invariant: the model only CHOOSES among engine-built legal actions;
the engine owns collision, legality, staleness rejection, and canonical
event/state construction. All persistence goes through RunStore.append_event,
which re-applies the event's StateUpdate against the stored snapshot and
recomputes hashes — the engine never trusts its own precomputed result alone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..contracts.base import ContractError, content_hash
from ..contracts.events import CanonicalEvent
from ..contracts.human import HumanObservation, LegalAction
from ..contracts.run import RunMetadata
from ..contracts.state import StateUpdate, WorldState
from .maps import GameMap, resolve_transfer, MapLoadError
from .pathfinding import shortest_path, PathNotFound
from .access import transfer_gate, AccessDenied
from .field_scripts import transition_effects, safe_travel_slice
from .routeplanner import plan_journey, public_destinations, JourneyUnavailable
from .field import permission, actor_map, actions as field_actions, DIRECTIONS as FIELD_DIRECTIONS, WATER, elevator_options, pressed_switches, fallen_boulder

ENGINE_VERSION = "m0-0.1"
GENESIS_HEAD = "0" * 64
VISION_RADIUS = 6
ACTION_SECONDS = 1
DIR_STEPS = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
_CONTENT_MAPS = {
    "pallet-town": "PalletTown.json",
}


class EngineError(Exception):
    """Engine rejected a request (illegal, stale, or malformed)."""


class StaleActionError(EngineError):
    """Action was built from an observation the world has already moved past."""


def first_starter_eligible(state, human):
    """A recorded starter remains claimed after storage, trade, or release."""
    return not human.get("party") and f"pokemon-{human['human_id']}-starter" not in state.pokemon


def default_map_paths(content_root: str | Path) -> dict[str, Path]:
    root = Path(content_root)
    return {mid: root / "maps" / fn for mid, fn in _CONTENT_MAPS.items()}


class SimulationEngine:
    """Deterministic, store-backed M0 engine (movement/wait/goal/memory/entry)."""

    def __init__(self, maps: Mapping[str, GameMap],
                 wall_time_fn=None) -> None:
        if not maps:
            raise EngineError("SimulationEngine requires at least one map")
        self.maps = dict(maps)
        self._wall_time = wall_time_fn or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

    @classmethod
    def from_content(cls, content_root: str | Path,
                     wall_time_fn=None) -> "SimulationEngine":
        maps = {
            mid: GameMap.from_content(mid, p)
            for mid, p in sorted(default_map_paths(content_root).items())
        }
        return cls(maps, wall_time_fn=wall_time_fn)

    # ------------------------------------------------------------- genesis

    def create_run(
        self,
        store,
        *,
        run_id: str,
        mode: str = "survival",
        humans: Sequence[tuple[str, str]] = (),
        notes: str = "engine-genesis",
    ) -> WorldState:
        """Create run at state v0 and persist it atomically via the store."""
        if not humans:
            raise EngineError("create_run requires an explicit human roster")
        home = self.maps["pallet-town"]
        human_states: dict[str, dict[str, Any]] = {}
        for idx, (hid, name) in enumerate(humans):
            x, y = home.first_open_cell((4 + idx % 4, 5 + (idx // 4) % 3))
            human_states[hid] = {
                "human_id": hid, "name": name, "map_id": "pallet-town",
                "x": x, "y": y, "facing": "south", "money": 3000,
                "badges": [], "party": [], "inventory": {}, "box": [],
                "goal": {}, "memories": {}, "last_entry": {}, "status": {},
            }
        state = WorldState(
            run_id=run_id, state_version=0, state_hash=GENESIS_HEAD,
            tick=0, simulated_time=0, mode=mode, phase="running",
            clock={"seconds": 0}, humans=human_states,
            maps={mid: m.content_summary() for mid, m in self.maps.items()},
        )
        state.state_hash = state.compute_state_hash()
        state.verify()
        meta = RunMetadata(
            run_id=run_id, world_id="kanto-m0", world_revision="pret-pinned",
            engine_version=ENGINE_VERSION, code_revision=ENGINE_VERSION, mode=mode,
            created_at="engine-genesis", population_target=len(humans),
            population_actual=len(humans),
            data_directory=str(getattr(store, "path", "")),
            content_manifest_hash=content_hash(
                {mid: m.content_summary() for mid, m in self.maps.items()}
            ),
            notes=notes,
        )
        store.create_run(meta, state)
        return state

    # -------------------------------------------------------- observations

    def get_observation(self, store, run_id: str, human_id: str) -> HumanObservation:
        _, state, _head = store.load_run(run_id)
        return self.observation_for(state, human_id)

    def observation_for(self, state: WorldState, human_id: str) -> HumanObservation:
        h = self._require_human(state, human_id)
        vis = []
        observed_map=self._require_map(state,str(h["map_id"]))
        vision_radius=1 if observed_map.events.get("requires_flash") and not h.get("field",{}).get("flash_active") else VISION_RADIUS
        for other_id, o in sorted(state.humans.items()):
            if other_id == human_id or o.get("map_id") != h["map_id"]:
                continue
            if abs(int(o["x"]) - int(h["x"])) <= vision_radius and \
               abs(int(o["y"]) - int(h["y"])) <= vision_radius:
                vis.append({
                    "human_id": other_id, "name": o["name"],
                    "x": int(o["x"]), "y": int(o["y"]), "facing": o["facing"],
                })
        game_map = self._require_map(state, str(h["map_id"]))
        exits = [
            {"x": x, "y": y, "target": t}
            for (x, y), t in sorted(game_map.exit_target_cells().items())
            if abs(x - int(h["x"])) <= vision_radius
            and abs(y - int(h["y"])) <= vision_radius
        ]
        return HumanObservation(
            run_id=state.run_id, human_id=human_id,
            state_version=state.state_version,
            observation_version=state.state_version,
            simulated_time=state.simulated_time,
            self_state={
                "name": h["name"], "x": int(h["x"]), "y": int(h["y"]),
                "facing": h["facing"], "goal": dict(h["goal"]),
            },
            party=tuple(h["party"]), inventory=tuple(dict(h["inventory"]).values()),
            memories=tuple(v for _k, v in sorted(
                dict(h["memories"]).items(),
                key=lambda kv: (0, int(kv[0])) if kv[0].isdigit() else (1, kv[0]))),
            money=int(h["money"]), badges=tuple(h["badges"]),
            legal_actions=self.legal_actions(state, human_id),
            visible_actors=tuple(vis[:64]),
            location={
                "map_id": h["map_id"], "x": int(h["x"]), "y": int(h["y"]),
                "width": game_map.width, "height": game_map.height, "exits": exits,
                "requires_flash":bool(game_map.events.get("requires_flash")),"flash_active":bool(h.get("field",{}).get("flash_active")),"flash_level":4 if game_map.events.get("requires_flash") and not h.get("field",{}).get("flash_active") else 0,"flash_radius_pixels":24 if game_map.events.get("requires_flash") and not h.get("field",{}).get("flash_active") else 200,
            },
            revealed_battle_info={},
        )

    def legal_actions(self, state: WorldState, human_id: str, *, include_routes: bool = True) -> tuple[LegalAction, ...]:
        h = self._require_human(state, human_id)
        game_map = self._require_map(state, str(h["map_id"]))
        original_map = game_map
        game_map = actor_map(game_map,h,state)
        surfing = bool(h.get("status",{}).get("surfing")) and (permission(state,h,"SURF") or bool(h.get("status",{}).get("source_forced_surfing")))
        x, y = int(h["x"]), int(h["y"])
        acts: list[LegalAction] = []
        for d, (dx, dy) in sorted(DIR_STEPS.items()):
            walking_path = game_map.step_path((x,y),d,surfing=surfing)
            destination = walking_path[-1] if walking_path else None
            if destination is not None:
                nx,ny=destination
                acts.append(LegalAction(
                    action="walk_to", arguments={"direction": d},
                    known_consequences={"arrives_at": [nx, ny],
                                        "map_id": h["map_id"],"changes_map":False,
                                        "duration_seconds": len(walking_path)*ACTION_SECONDS},
                ))
        if game_map.source_revision:
            acts.extend(LegalAction(action="turn_to",arguments={"direction":direction},known_consequences={"facing":direction,"duration_seconds":ACTION_SECONDS}) for direction in sorted(DIR_STEPS) if direction!=h.get("facing"))
        target = game_map.exit_target(x, y)
        transferable = target is not None and target in self.maps
        if transferable and game_map.source_revision:
            try: resolve_transfer(self.maps, game_map, x, y, target,surfing=surfing or int(game_map.cells.get((x,y),{}).get("behavior",0))==0x66,actor=h,state=state)
            except MapLoadError: transferable = False
        if transferable:
            try: transfer_gate(h,target,state)
            except AccessDenied: transferable=False
        if transferable:
            acts.append(LegalAction(
                action="enter_map", arguments={"map_id": target},
                known_consequences={"duration_seconds": ACTION_SECONDS,"destination_map":target,"changes_map":True},
            ))
        if game_map.source_revision and include_routes:
            candidates = sorted(game_map.exits, key=lambda p:(abs(p[0]-x)+abs(p[1]-y),p))[:16]
            radius=1 if original_map.events.get('requires_flash') and not h.get('field',{}).get('flash_active') else VISION_RADIUS
            candidates += [(int(o["x"])+dx,int(o["y"])+dy) for hid,o in sorted(state.humans.items()) if hid != human_id and o.get("map_id")==h["map_id"] and abs(int(o['x'])-x)<=radius and abs(int(o['y'])-y)<=radius for dx,dy in DIR_STEPS.values()][:32]
            candidates += [(int(bg["x"]),int(bg["y"])+1) for bg in original_map.events.get("mansion_switch",{}).get("statues",[])]
            candidates += [(x+dx*5,y+dy*5) for dx,dy in DIR_STEPS.values()]
            for dest in dict.fromkeys(candidates):
                if dest == (x,y): continue
                try: route = shortest_path(game_map,(x,y),dest,surfing=surfing)
                except PathNotFound: continue
                acts.append(LegalAction(action="travel_to",arguments={"x":dest[0],"y":dest[1]},known_consequences={"map_id":h["map_id"],"arrives_at":list(dest),"changes_map":False,"duration_seconds":len(route)*ACTION_SECONDS,"route_length":len(route),"destination_kind":"exit" if dest in game_map.exits else "local",**({"exit_target":game_map.exits[dest],"next_action":"enter_map"} if dest in game_map.exits else {})}))
        if game_map.source_revision and include_routes:
            destinations=public_destinations(self.maps,h["map_id"])
            starter_lab="PalletTown_ProfessorOaksLab"
            starter_eligible=first_starter_eligible(state,h)
            if starter_eligible and h["map_id"]!=starter_lab and starter_lab in self.maps and starter_lab not in destinations:
                destinations.insert(0,starter_lab)
            active=h.get("active_plan") or {}
            if active.get("kind")=="journey" and active.get("destination_map") not in destinations:destinations.append(active["destination_map"])
            path_cache={}
            for destination in destinations:
                try: journey=plan_journey(self.maps,h,destination,state=state,max_nodes=256 if destination==starter_lab and not h.get("party") else 48,max_tiles=1000,path_cache=path_cache)
                except JourneyUnavailable: continue
                acts.append(LegalAction(action="journey_to",arguments={"map_id":destination},known_consequences={"engine_owned_route":True,"destination_map":destination,"changes_map":True,"arrives_at":journey[-1]["destination"],"duration_seconds":sum(len(s["steps"])+1 for s in journey),"maps_crossed":len(journey),"may_interrupt":True,**({"destination_kind":"starter","purpose":"Visit Professor Oak for a first starter; choosing a starter is a separate legal action on arrival."} if destination==starter_lab and starter_eligible else {})}))
        from .field_travel import actions as travel_actions
        acts.extend(travel_actions(state,h,self.maps))
        acts.extend(field_actions(state,h,original_map))
        for floor in elevator_options(self.maps,h):
            acts.append(LegalAction(action="ride_elevator",arguments={"map_id":floor["map_id"]},known_consequences={"arrives_at":[floor["x"],floor["y"]],"source":floor["source"],"per_trainer":True}))
        acts.append(LegalAction(action="wait", arguments={},
                                known_consequences={"duration_seconds": ACTION_SECONDS}))
        acts.append(LegalAction(
            action="set_goal", arguments={"text": "<non-empty text, <=200 chars>"},
            known_consequences={"duration_seconds": ACTION_SECONDS}))
        acts.append(LegalAction(
            action="remember", arguments={"text": "<non-empty text, <=200 chars>"},
            known_consequences={"duration_seconds": ACTION_SECONDS}))
        from .individual_life import LIFE_ACTIONS
        active=(h.get('individual_life') or {}).get('commitment') or {}
        for life_action in sorted(LIFE_ACTIONS):
            if life_action=='set_commitment' and active.get('status')=='active':continue
            if life_action in {'complete_commitment','abandon_commitment'} and active.get('status')!='active':continue
            acts.append(LegalAction(action=life_action,arguments={'text':'<non-empty text, <=200 chars>'},known_consequences={'private_reflection':True,'does_not_grant_rewards':True}))
        return tuple(acts)

    def legal_actions_for_validation(self, state, human_id, action):
        from inspect import signature
        if 'include_routes' not in signature(self.legal_actions).parameters:
            return self.legal_actions(state,human_id)
        return self.legal_actions(state, human_id, include_routes=action in {'travel_to','journey_to'})

    # ------------------------------------------------------------- actions

    def build_action_event(
        self, store, run_id: str, human_id: str, *,
        action: str,
        arguments: Mapping[str, Any],
        observation_version: int,
        expected_state_version: int,
        decision_explanation: str,
        decision_provenance: Mapping[str, Any],
        scripted_test_mind: bool = False,
        defer_time: bool = False,
    ) -> tuple[CanonicalEvent, WorldState]:
        """Validate a choice against CURRENT state; return (event, new_state).

        Raises EngineError/StaleActionError before anything is persisted.
        """
        if scripted_test_mind:
            raise EngineError("scripted_test_mind is not permitted in production runs")
        prov = dict(decision_provenance)
        if prov.get("kind") not in {"model", "user"} or (prov.get("kind") == "model" and not str(prov.get("model_id", "")).strip()):
            raise EngineError("decisions must carry model provenance (kind='model', model_id)")
        if not str(decision_explanation).strip():
            raise EngineError("decisions require a non-empty decision_explanation")
        _meta, state, head = store.load_run(run_id)
        if observation_version != state.state_version:
            raise StaleActionError(
                f"observation_version {observation_version} is stale "
                f"(state is at {state.state_version})")
        if expected_state_version != state.state_version:
            raise StaleActionError(
                f"expected_state_version {expected_state_version} != current "
                f"{state.state_version}")
        h = self._require_human(state, human_id)
        args = dict(arguments)
        legal = {la.action: la for la in self.legal_actions_for_validation(state, human_id, action)}
        if action not in legal:
            raise EngineError(f"action {action!r} is not legal for {human_id} right now")
        game_map = self._require_map(state, str(h["map_id"]))
        original_map = game_map
        game_map = actor_map(game_map,h,state)
        surfing = bool(h.get("status",{}).get("surfing")) and (permission(state,h,"SURF") or bool(h.get("status",{}).get("source_forced_surfing")))
        x, y = int(h["x"]), int(h["y"])
        changes: list[dict[str, Any]] = []
        duration = ACTION_SECONDS
        route_evidence = None
        activity_completions=[]
        if action == "walk_to":
            d = args.get("direction")
            if d not in DIR_STEPS or {"direction": d} != args:
                raise EngineError("walk_to takes exactly {'direction': one of north/south/east/west}")
            dx, dy = DIR_STEPS[d]
            walking_path = game_map.step_path((x,y),d,surfing=surfing)
            destination = walking_path[-1] if walking_path else None
            if destination is None:
                raise EngineError(f"walk_to {d} collides with terrain/bounds")
            nx,ny=destination
            duration=len(walking_path)*ACTION_SECONDS
            route_evidence={"map_id":h["map_id"],"start":[x,y],"steps":[list(p) for p in walking_path],"duration_seconds":duration}
            changes += [
                {"op": "set", "path": f"humans.{human_id}.x", "value": nx},
                {"op": "set", "path": f"humans.{human_id}.y", "value": ny},
                {"op": "set", "path": f"humans.{human_id}.facing", "value": d},
            ]
            if surfing and int(game_map.cells.get((nx,ny),{}).get("behavior",0)) not in WATER:
                changes.append({"op":"set","path":f"humans.{human_id}.status.surfing","value":False})
            kind = "human.moved"
        elif action == "travel_to":
            if set(args) != {"x","y"} or type(args["x"]) is not int or type(args["y"]) is not int:
                raise EngineError("travel_to takes integer x and y in the current map")
            try: route = shortest_path(game_map,(x,y),(args["x"],args["y"]),surfing=surfing)
            except PathNotFound as exc: raise EngineError(str(exc)) from exc
            if not route: raise EngineError("already at destination")
            duration = len(route)*ACTION_SECONDS
            route_evidence = {"map_id":h["map_id"],"start":[x,y],"steps":[list(p) for p in route],"duration_seconds":duration}
            nx,ny = route[-1]
            changes += [{"op":"set","path":f"humans.{human_id}.x","value":nx},{"op":"set","path":f"humans.{human_id}.y","value":ny}]
            if surfing and int(game_map.cells.get((nx,ny),{}).get("behavior",0)) not in WATER:
                changes.append({"op":"set","path":f"humans.{human_id}.status.surfing","value":False})
            kind = "human.moved"
        elif action == "turn_to":
            if set(args)!={"direction"} or args["direction"] not in DIR_STEPS or not game_map.source_revision:raise EngineError("turn_to requires source map and cardinal direction")
            changes.append({"op":"set","path":f"humans.{human_id}.facing","value":args["direction"]})
            kind="human.moved"
        elif action == "enter_map":
            tgt = args.get("map_id")
            if set(args) != {"map_id"} or tgt != game_map.exit_target(x, y) or tgt not in self.maps:
                raise EngineError("enter_map target is not the exit under this human")
            if game_map.source_revision:
                try: tgt,nx,ny = resolve_transfer(self.maps,game_map,x,y,tgt,surfing=surfing or int(game_map.cells.get((x,y),{}).get("behavior",0))==0x66,actor=h,state=state)
                except MapLoadError as exc: raise EngineError(str(exc)) from exc
            else:
                nx, ny = self.maps[tgt].first_open_cell((x, y))
            try: changes.extend(transfer_gate(h,tgt,state))
            except AccessDenied as exc: raise EngineError(str(exc)) from exc
            changes += [
                {"op": "set", "path": f"humans.{human_id}.map_id", "value": tgt},
                {"op": "set", "path": f"humans.{human_id}.last_entry.from_map",
                 "value": h["map_id"]},
                {"op": "set", "path": f"humans.{human_id}.x", "value": nx},
                {"op": "set", "path": f"humans.{human_id}.y", "value": ny},
            ]
            if game_map.source_revision:
                actor,script_steps=transition_effects(self.maps,h,game_map,(x,y),tgt,(nx,ny))
                for key in ("map_id","x","y","field","status","facing"):
                    if key in actor:changes.append({"op":"set","path":f"humans.{human_id}.{key}","value":actor[key]})
                if script_steps:
                    duration+=sum(len(s.get("steps",[])) for s in script_steps)
                    route_evidence={"source_scripts":script_steps,"duration_seconds":duration}
            kind = "human.entered_map"
        elif action == "journey_to":
            if set(args)!={"map_id"} or not isinstance(args["map_id"],str):raise EngineError("journey_to requires destination map_id")
            try: journey=plan_journey(self.maps,h,args["map_id"],state=state)
            except JourneyUnavailable as exc:raise EngineError(str(exc)) from exc
            completed=[];duration=0;position=(h["map_id"],x,y);surfing_after=surfing;interrupted=False
            # A bounded travel slice is a deterministic activity boundary, not
            # another model action. Preserve the destination as an active plan.
            remaining=128
            from .scheduling import next_due
            due=next_due(state)
            if due is not None and due>state.simulated_time:remaining=min(remaining,due-state.simulated_time)
            source_actor=dict(h)
            for segment in journey:
                steps=segment["steps"]
                if len(steps)>=remaining:
                    safe_count=safe_travel_slice(actor_map(self.maps[segment["map_id"]],source_actor),steps,remaining)
                    actual=steps[:safe_count];position=(segment["map_id"],*actual[-1]);duration+=len(actual)
                    if surfing_after and any(int(self.maps[segment["map_id"]].cells.get(tuple(p),{}).get("behavior",0)) not in WATER for p in actual):surfing_after=False
                    completed.append({**segment,"steps":actual,"transfer_completed":False});interrupted=True;break
                duration+=len(steps);remaining-=len(steps)
                changes.extend(segment["checkpoint_changes"])
                for key in ("field","status"):
                    changes.append({"op":"set","path":f"humans.{human_id}.{key}","value":segment[key+"_after"]})
                duration+=sum(len(s.get("steps",[])) for s in segment.get("script_steps",[]))
                duration+=1;remaining-=1;position=(segment["destination_map"],*segment["destination"]);surfing_after=segment["surfing_after"];completed.append({**segment,"transfer_completed":True});source_actor["field"]=segment["field_after"]
                if remaining<=0 and segment is not journey[-1]:interrupted=True;break
            mid,nx,ny=position;prefix=f"humans.{human_id}"
            changes += [{"op":"set","path":prefix+".map_id","value":mid},{"op":"set","path":prefix+".x","value":nx},{"op":"set","path":prefix+".y","value":ny},{"op":"set","path":prefix+".status.surfing","value":surfing_after},{"op":"set","path":prefix+".active_plan","value":{"kind":"journey","destination_map":args["map_id"],"accepted_state_version":(h.get("active_plan") or {}).get("accepted_state_version",state.state_version) if prov.get("continuation_of_state_version") is not None else state.state_version,"explanation":decision_explanation,"provenance":prov} if interrupted else None}]
            route_evidence={"journey":completed,"destination_map":args["map_id"],"duration_seconds":duration,"interrupted":interrupted,"interruption_reason":"deterministic travel activity boundary (128 tiles or next due activity, preserving forced movement)" if interrupted else None}
            kind="human.moved"
        elif action in ("fly_to","flash","ride_bicycle","dismount_bicycle"):
            from .field_travel import changes_for
            try: changes,travel_evidence=changes_for(state,h,self.maps,action,args)
            except ValueError as exc:raise EngineError(str(exc)) from exc
            route_evidence={"field_travel":travel_evidence,"duration_seconds":duration}
            kind="human.field_move"
        elif action == "ride_elevator":
            floor=next((f for f in elevator_options(self.maps,h) if args=={"map_id":f["map_id"]}),None)
            if floor is None:raise EngineError("elevator floor is unavailable or lift key missing")
            try: changes.extend(transfer_gate(h,floor["map_id"],state))
            except AccessDenied as exc: raise EngineError(str(exc)) from exc
            prefix=f"humans.{human_id}"
            choices=dict(h.get("field",{}).get("elevator_choices",{}));choices[h["map_id"]]=floor["map_id"]
            changes += [{"op":"set","path":prefix+".field.elevator_choices","value":choices},{"op":"set","path":prefix+".last_entry.from_map","value":h["map_id"]},{"op":"set","path":prefix+".map_id","value":floor["map_id"]},{"op":"set","path":prefix+".x","value":floor["x"]},{"op":"set","path":prefix+".y","value":floor["y"]}]
            kind="human.entered_map"
        elif action in {"surf","stop_surf","cut","push_boulder","open_card_door","toggle_mansion_switch"}:
            options=field_actions(state,h,original_map)
            if not any(a.action==action and a.arguments==args for a in options):raise EngineError("field move permissions or source object unavailable")
            prefix=f"humans.{human_id}"
            if action=="surf":
                dx,dy=FIELD_DIRECTIONS[h.get("facing","south")]
                changes += [{"op":"set","path":prefix+".status.surfing","value":True},{"op":"set","path":prefix+".x","value":x+dx},{"op":"set","path":prefix+".y","value":y+dy}]
            elif action=="stop_surf":changes.append({"op":"set","path":prefix+".status.surfing","value":False})
            elif action=="toggle_mansion_switch":changes.append({"op":"set","path":prefix+".field.mansion_switch","value":not h.get("field",{}).get("mansion_switch",False)})
            elif action=="open_card_door":changes.append({"op":"set","path":prefix+".field.doors","value":list(h.get("field",{}).get("doors",[]))+[args["door_id"]]})
            elif action=="cut":changes.append({"op":"set","path":prefix+".field.cut","value":list(h.get("field",{}).get("cut",[]))+[args["object_id"]]})
            else:
                dx,dy=FIELD_DIRECTIONS[args["direction"]]
                positions=dict(h.get("field",{}).get("boulders",{}));positions[args["object_id"]]=[x+2*dx,y+2*dy]
                fall=fallen_boulder(original_map,h,args["object_id"],positions[args["object_id"]])
                if fall:
                    for key,value in fall.items():changes.append({"op":"set","path":prefix+".field."+key,"value":value})
                switches=pressed_switches(original_map,args["object_id"],positions[args["object_id"]],h.get("field",{}).get("switches",[]))
                changes.append({"op":"set","path":prefix+".field.switches","value":switches})
                changes += [{"op":"set","path":prefix+".field.boulders","value":positions},{"op":"set","path":prefix+".x","value":x+dx},{"op":"set","path":prefix+".y","value":y+dy}]
            kind="human.field_move"
        elif action == "wait":
            if args:
                raise EngineError("wait takes no arguments")
            kind = "time.advanced"
        elif action in {'set_aspiration','set_commitment','complete_commitment','abandon_commitment'}:
            from .individual_life import life_action_changes
            changes += life_action_changes(h,human_id,action,args,decision_explanation,state.simulated_time,prov)
            kind = 'human.goal_set'
        elif action == "set_goal":
            text = str(args.get("text", "")).strip()
            if set(args) != {"text"} or not text or len(text) > 200:
                raise EngineError("set_goal takes {'text': non-empty, <=200 chars}")
            changes += [
                {"op": "set", "path": f"humans.{human_id}.goal.text", "value": text},
            ]
            kind = "human.goal_set"
        elif action == "remember":
            text = str(args.get("text", "")).strip()
            if set(args) != {"text"} or not text or len(text) > 200:
                raise EngineError("remember takes {'text': non-empty, <=200 chars}")
            from .conversation import next_memory_slot
            slot = next_memory_slot(h.get("memories", {}))
            changes += [
                {"op": "set", "path": f"humans.{human_id}.memories.{slot}.text",
                 "value": text},
            ]
            kind = "human.memory_written"
        else:  # pragma: no cover — legal_actions never emits it
            raise EngineError(f"action {action!r} not implemented by this engine slice")
        if action!="journey_to" and h.get("active_plan"):
            changes.append({"op":"set","path":f"humans.{human_id}.active_plan","value":None})
        from .movement_encounters import intercept
        changes,duration,route_evidence,encounter_kind=intercept(self,state,human_id,action,args,prov,decision_explanation,route_evidence,changes,duration)
        if encounter_kind:kind=encounter_kind
        if action in ("walk_to","travel_to") and not encounter_kind and route_evidence.get("steps"):
            fx,fy=route_evidence["steps"][-1]
            if int(game_map.cells.get((fx,fy),{}).get("behavior",0))==0x66:
                target=game_map.exit_target(fx,fy)
                try:
                    target,tx,ty=resolve_transfer(self.maps,game_map,fx,fy,target,surfing=True,actor=h,state=state)
                    actor,script_steps=transition_effects(self.maps,h,game_map,(fx,fy),target,(tx,ty))
                except MapLoadError as exc:raise EngineError("source fall warp unresolved") from exc
                for key in ("map_id","x","y","field","status","facing"):
                    if key in actor:changes.append({"op":"set","path":f"humans.{human_id}.{key}","value":actor[key]})
                duration+=1+sum(len(s.get("steps",[])) for s in script_steps)
                route_evidence.update(source_scripts=script_steps,fall_warp={"source":[fx,fy],"destination_map":target,"landing":[tx,ty]},duration_seconds=duration)
        if action in ("walk_to","travel_to","enter_map","journey_to","ride_elevator","fly_to"):
            final_map=h["map_id"]
            for change in changes:
                if change.get("path")==f"humans.{human_id}.map_id":final_map=change["value"]
            visited=list(dict.fromkeys(h.get("field",{}).get("visited_maps",[])+[h["map_id"]]))
            if route_evidence and route_evidence.get("journey"):
                for segment in route_evidence["journey"]:
                    if segment.get("transfer_completed") and segment["destination_map"] not in visited:visited.append(segment["destination_map"])
            from ..mechanics.acquisition import LAB, transition_acquisition
            departed_lab=h["map_id"]==LAB and final_map=="CinnabarIsland_PokemonLab_Entrance"
            if route_evidence and route_evidence.get("journey"):
                departed_lab=departed_lab or any(segment.get("transfer_completed") and segment.get("map_id")==LAB and segment.get("destination_map")=="CinnabarIsland_PokemonLab_Entrance" for segment in route_evidence["journey"])
            if departed_lab and h.get("acquisition",{}).get("reviving"):
                changes.append({"op":"set","path":f"humans.{human_id}.acquisition","value":transition_acquisition(h,LAB,"CinnabarIsland_PokemonLab_Entrance")})
            if final_map not in visited:visited.append(final_map)
            changes.append({"op":"set","path":f"humans.{human_id}.field.visited_maps","value":visited})
            if self.maps[final_map].events.get("map_type") in {"MAP_TYPE_ROUTE","MAP_TYPE_TOWN","MAP_TYPE_OCEAN_ROUTE","MAP_TYPE_CITY"}:changes.append({"op":"set","path":f"humans.{human_id}.field.flash_active","value":False})
            if not self.maps[final_map].events.get("allow_cycling",False):changes.append({"op":"set","path":f"humans.{human_id}.status.bicycle","value":False})
        time_hook=getattr(self,"resolve_time_effects",None)
        if time_hook and not defer_time:changes,activity_completions=time_hook(state,changes,duration)
        final_map=h['map_id'];final_x=x;final_y=y
        for delta in changes:
            if delta.get('path')==f'humans.{human_id}.map_id':final_map=delta['value']
            elif delta.get('path')==f'humans.{human_id}.x':final_x=delta['value']
            elif delta.get('path')==f'humans.{human_id}.y':final_y=delta['value']
        from .collision import actor_elevation
        level=int(self.maps[final_map].cells.get((final_x,final_y),{}).get('elevation',0))
        if level==15:level=actor_elevation(original_map,h)
        changes.append({'op':'set','path':f'humans.{human_id}.status.collision_elevation','value':level})
        changes.append({"op": "advance_clock", "seconds": 0 if defer_time else duration})
        changes.append({"op": "set", "path": f"humans.{human_id}.last_decision", "value": {"action": action, "arguments": args, "explanation": decision_explanation, "provenance": prov, "observation_version": observation_version}})
        from .entity_systems import map_visit_changes
        changes.extend(map_visit_changes(state,changes))
        if not defer_time:
            from .individual_life import record_decision
            record_decision(h,human_id,action,args,decision_explanation,state.simulated_time,changes,source_state_version=state.state_version)
            from .task_continuity import settle_changes
            changes += settle_changes(state,changes)
        new_state = state.with_advanced_version(changes)

        action_hash = content_hash({
            "run_id": run_id, "human_id": human_id, "action": action,
            "arguments": args, "observation_version": observation_version,
            "expected_state_version": expected_state_version,
        })
        event_index = state.state_version
        event_id = f"evt-{event_index}-{action_hash[:24]}"
        update = StateUpdate(
            run_id=run_id, event_id=event_id, event_index=event_index,
            prior_state_version=state.state_version,
            prior_state_hash=state.state_hash, previous_head=head,
            state_version=new_state.state_version, state_hash=new_state.state_hash,
            changes=changes,
        )
        update.validate()
        # Engine-side dry run: prove the update applies to THIS state exactly.
        dry = update.apply_to(state)
        assert dry.state_hash == new_state.state_hash
        event = CanonicalEvent(
            run_id=run_id, event_id=event_id, event_index=event_index,
            state_version=new_state.state_version, previous_head=head,
            event_kind=kind, tick=new_state.tick,
            simulated_time=new_state.simulated_time,
            real_wall_time=self._wall_time(),
            causation={"human_id": human_id, "action": action,
                       "action_hash": action_hash,
                       "action_arguments": args,
                       "decision_explanation": decision_explanation,
                       "observation_version": observation_version,
                       "provenance": prov},
            affected=[{"human_id": hid} for hid in dict.fromkeys([human_id]+[r["human_id"] for r in activity_completions])],
            before={"position": {"map_id": h["map_id"], "x": x, "y": y}},
            after={"position": {"map_id": new_state.humans[human_id]["map_id"],
                                "x": int(new_state.humans[human_id]["x"]),
                                "y": int(new_state.humans[human_id]["y"])}},
            deterministic_inputs={"duration_seconds": duration, "action_hash": action_hash, **({"route": route_evidence} if route_evidence is not None else {}),**({"activity_completions":activity_completions} if activity_completions else {})},
            transaction={"kind": "state_update", **update.to_dict()},
            visibility={"private_to": [human_id]},
        )
        event.validate()
        return event, new_state

    def commit(self, store, event: CanonicalEvent) -> str:
        """Persist atomically through the store; returns the new chain head."""
        return store.append_event(event, event.transaction["state_hash"])

    # -------------------------------------------------------------- internals

    @staticmethod
    def _require_human(state: WorldState, human_id: str) -> dict[str, Any]:
        h = state.humans.get(human_id)
        if h is None:
            raise EngineError(f"unknown human {human_id!r}")
        return h

    def _require_map(self, state: WorldState, map_id: str) -> GameMap:
        gm = self.maps.get(map_id)
        if gm is None:
            raise EngineError(f"map {map_id!r} not loaded by this engine")
        return gm
