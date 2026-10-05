"""Observer and player HTTP commands over the shared authoritative simulation."""
from __future__ import annotations
import json,threading,copy,tempfile,os
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel, Field
from ..contracts import ContractError, StateUpdate, RunMetadata, WorldState, CanonicalEvent
from ..simulation.world import WorldEngine
from ..simulation.engine import EngineError,StaleActionError
from ..runtime import RuntimeController,LocalModelConfig,LocalModelProvider,ProviderError
from ..store import RunStore,StoreError

class WorldRequest(BaseModel):
    run_id:str
    seed:int=1
    mode:str='observer'
class Command(BaseModel):
    human_id:str='player'
    expected_state_version:int
    action:str
    arguments:dict=Field(default_factory=dict)
class Intervention(BaseModel):
    expected_state_version:int
    author:str='user'
    kind:str
    human_id:str
    arguments:dict=Field(default_factory=dict)
class Endpoint(BaseModel):
    base_url:str
    model_id:str
    kind:str='openai'
    timeout_seconds:float=60
    concurrency:int=Field(default=1,ge=1,le=8,strict=True)
class Step(BaseModel):
    human_id:str|None=None
class PlayerRequest(BaseModel):
    expected_state_version:int
class ModeRequest(PlayerRequest):
    mode:str

def interaction_mode(state):
    return state.world_facts.get('interaction_mode',state.mode)


def install_world_routes(app,open_store,safe_run_id,creation_lock):
    controllers={};registry_lock=threading.RLock();engine_box={}
    app.state.runtime_controllers=controllers
    def engine():
        with registry_lock:
            if not engine_box:engine_box['world']=WorldEngine(app.state.content_dir)
            return engine_box['world']
    def controller(run_id):
        with registry_lock:
            if run_id not in controllers:
                store=open_store(run_id)
                _,s,_=store.load_run(run_id)
                provider=None;concurrency=1
                settings_path=Path(store.path).with_suffix('.runtime-settings.json')
                try:
                    if settings_path.exists():
                        settings=Endpoint.model_validate_json(settings_path.read_text());concurrency=settings.concurrency
                        provider=LocalModelProvider(LocalModelConfig(settings.base_url,settings.model_id,settings.kind,settings.timeout_seconds))
                    else:provider=LocalModelProvider(LocalModelConfig.from_env())
                except (ProviderError,ValueError):pass
                controllers[run_id]=RuntimeController(engine(),store,run_id,provider,actor_ids=[h for h in s.humans if h!='player'],concurrency=concurrency)
            return controllers[run_id]
    app.state.get_runtime_controller=controller
    def fail(exc):
        code=409 if isinstance(exc,(StaleActionError,RuntimeError)) else 400
        raise HTTPException(code,detail=str(exc))


    @app.get('/runs')
    def runs():
        result=[]
        for p in sorted(app.state.base_dir.glob('*.db')):
            try:
                store=open_store(p.stem);meta,s,head=store.load_run(p.stem)
                result.append({'run_id':s.run_id,'status':store.get_status(s.run_id),'state_version':s.state_version,'simulated_time':s.simulated_time,'population':len([h for h in s.humans if h!='player']),'mode':interaction_mode(s),'creative_modified':s.world_facts.get('creative_modified',False)})
            except (StoreError,ContractError,HTTPException):continue
        return result

    @app.post('/worlds',status_code=201)
    def new_world(req:WorldRequest):
        if not safe_run_id(req.run_id) or req.mode not in {'observer','survival','creative'}:raise HTTPException(400,detail='invalid run identifier or mode')
        path=app.state.base_dir/f'{req.run_id}.db'
        with registry_lock,creation_lock(path):
            if path.exists():raise HTTPException(409,detail='run already exists')
            store=RunStore(path)
            try:s=engine().initialize(store,req.run_id,req.seed,req.mode)
            except Exception as exc:
                store.close();path.unlink(missing_ok=True);fail(exc)
            app.state.stores[req.run_id]=store
            return {'run_id':req.run_id,'status':'paused','state_version':s.state_version,'population':100}

    @app.get('/runs/{run_id}/runtime')
    def runtime_status(run_id:str):return controller(run_id).status()

    @app.post('/runs/{run_id}/mode')
    def change_mode(run_id:str,req:ModeRequest):
        if req.mode not in {'observer','survival','creative'}:raise HTTPException(400,detail='unknown interaction mode')
        c=controller(run_id)
        with c.shared_lock:
            store=open_store(run_id);_,state,_=store.load_run(run_id)
            if req.expected_state_version!=state.state_version:raise HTTPException(409,detail='state changed; refresh before switching modes')
            c.pause();before=interaction_mode(state)
            if before==req.mode:return {'mode':before,'state_version':state.state_version,'creative_modified':state.world_facts.get('creative_modified',False)}
            event,new=engine().commit_changes(store,run_id,[{'op':'set','path':'world_facts.interaction_mode','value':req.mode}],kind='run.mode_changed',actor='user',explanation='Explicit user mode change',provenance={'kind':'user','author':'user'},expected_version=req.expected_state_version,details={'before':{'mode':before},'after':{'mode':req.mode}})
        return {'mode':req.mode,'state_version':new.state_version,'event_id':event.event_id,'creative_modified':new.world_facts.get('creative_modified',False)}

    @app.post('/runs/{run_id}/runtime')
    def configure(run_id:str,req:Endpoint):
        try:provider=LocalModelProvider(LocalModelConfig(req.base_url,req.model_id,req.kind,req.timeout_seconds))
        except (ValueError,ProviderError) as exc:fail(exc)
        c=controller(run_id);c.pause()
        with c.shared_lock:
            settings_path=Path(c.store.path).with_suffix('.runtime-settings.json')
            temporary=settings_path.with_suffix('.tmp');temporary.write_text(req.model_dump_json());temporary.replace(settings_path)
            c.provider=provider;c.concurrency=req.concurrency
        return c.status()

    @app.post('/runs/{run_id}/step')
    def step(run_id:str,req:Step):
        try:return controller(run_id).step(req.human_id)
        except (ValueError,EngineError,ProviderError,RuntimeError) as exc:fail(exc)

    @app.get('/runs/{run_id}/observations/{human_id}')
    def observation(run_id:str,human_id:str):
        try:return engine().get_observation(open_store(run_id),run_id,human_id).to_dict()
        except (EngineError,ContractError) as exc:fail(exc)

    @app.get('/runs/{run_id}/observer/humans')
    def humans(run_id:str):
        _,s,_=open_store(run_id).load_run(run_id)
        # Observer inspection is deliberately separate from human private observations.
        return {'humans':[copy.deepcopy(h) for h in s.humans.values()],'state_version':s.state_version,'pokemon':s.pokemon}

    @app.post('/runs/{run_id}/player/create')
    def create_player(run_id:str,req:PlayerRequest):
        c=controller(run_id)
        with c.shared_lock:
            store=open_store(run_id);_,s,_=store.load_run(run_id)
            if interaction_mode(s)=='observer':raise HTTPException(403,detail='Observer worlds do not accept player mutations')
            try:s=engine().add_player(store,run_id,req.expected_state_version)
            except (EngineError,ContractError) as exc:fail(exc)
        return {'human_id':'player','state_version':s.state_version}

    @app.post('/runs/{run_id}/player')
    def player_action(run_id:str,req:Command):
        if req.human_id!='player':raise HTTPException(403,detail='Survival input controls only your trainer')
        c=controller(run_id)
        with c.shared_lock:
            store=open_store(run_id);_,s,_=store.load_run(run_id)
            if interaction_mode(s)=='observer':raise HTTPException(403,detail='Observer worlds do not accept player mutations')
            try:
                event,new=engine().build_action_event(store,run_id,'player',action=req.action,arguments=req.arguments,observation_version=req.expected_state_version,expected_state_version=req.expected_state_version,decision_explanation='User-controlled trainer action',decision_provenance={'kind':'user','author':'user'})
                head=engine().commit(store,event)
            except (EngineError,ContractError,ValueError) as exc:fail(exc)
        return {'state_version':new.state_version,'event_head_hash':head}

    @app.post('/runs/{run_id}/interventions')
    def intervention(run_id:str,req:Intervention):
        c=controller(run_id)
        with c.shared_lock:
            store=open_store(run_id);_,s,_=store.load_run(run_id)
            if interaction_mode(s)!='creative':raise HTTPException(403,detail='Creative actions require a Creative world')
            if req.author!='user':raise HTTPException(400,detail='intervention author must be user')
            h=s.humans.get(req.human_id)
            if h is None:raise HTTPException(404,detail='unknown human')
            args=req.arguments;prefix=f'humans.{req.human_id}';changes=[];before={};after={}
            if req.kind=='teleport':
                mid=args.get('map_id');gm=engine().maps.get(mid)
                if gm is None:raise HTTPException(400,detail='map unavailable')
                x,y=args.get('x'),args.get('y')
                if type(x) is not int or type(y) is not int or not gm.is_walkable(x,y):raise HTTPException(400,detail='destination must be an open tile')
                before={k:h[k] for k in ['map_id','x','y']};after={'map_id':mid,'x':x,'y':y}
            elif req.kind=='money':
                v=args.get('value')
                if type(v) is not int or not 0<=v<=999999:raise HTTPException(400,detail='invalid money')
                before={'money':h['money']};after={'money':v}
            elif req.kind=='goal':
                text=args.get('text')
                if not isinstance(text,str) or not 0<len(text)<=200:raise HTTPException(400,detail='invalid goal')
                before={'goal':h['goal']};after={'goal':{'text':text}}
            elif req.kind=='heal':
                before={'party':[copy.deepcopy(s.pokemon[pid]) for pid in h['party']]}
                from ..mechanics import heal
                for pid in h['party']:
                    mon=copy.deepcopy(s.pokemon[pid]);heal(mon)
                    for k,v in mon.items():changes.append({'op':'set','path':f'pokemon.{pid}.{k}','value':v})
                after={'healed_party':list(h['party'])}
            elif req.kind=='pokemon':
                from ..mechanics import create_pokemon
                import random
                level=args.get('level');species=args.get('species')
                if len(h.get('party',[]))>=6 and len(h.get('box',[]))>=420:raise HTTPException(400,detail='party and storage are full')
                if type(level) is not int or not 1<=level<=100:raise HTTPException(400,detail='level must be 1..100')
                pid=f'creative-pokemon-{s.state_version}'
                try:mon=create_pokemon(species,level,req.human_id,random.Random(s.world_facts['seed']+s.state_version),identifier=pid)
                except (ValueError,KeyError,AttributeError):raise HTTPException(400,detail='unknown Kanto species')
                for k,v in mon.items():changes.append({'op':'set','path':f'pokemon.{pid}.{k}','value':v})
                before={'party':h['party'],'box':h['box']};party=list(h['party']);box=list(h['box']);(party if len(party)<6 else box).append(pid);after={'party':party,'box':box}
            elif req.kind=='item':
                from ..mechanics.item_rules import item_catalog
                raw=args.get('item');item=raw.upper().removeprefix('ITEM_') if isinstance(raw,str) else '';n=args.get('quantity')
                if item not in item_catalog() or item=='NONE' or type(n)is not int or not 0<=n<=999:raise HTTPException(400,detail='invalid item')
                item=item.lower()
                before={'inventory':h['inventory']};inv={k:copy.deepcopy(v) for k,v in h['inventory'].items() if k.upper().removeprefix('ITEM_')!=item.upper()};inv[item]={'item_id':item,'quantity':n};after={'inventory':inv}
            elif req.kind=='badges':
                from ..mechanics.progression import GYMS
                badges=args.get('badges')
                if not isinstance(badges,list) or len(badges)>8 or any(not isinstance(b,str) or b not in GYMS.values() for b in badges) or len(set(badges))!=len(badges):raise HTTPException(400,detail='invalid badge list')
                before={'badges':h['badges'],'achievement_provenance':h.get('achievement_provenance',{})}
                records=copy.deepcopy(h.get('achievement_provenance',{}))
                for badge in badges:
                    if badge not in h['badges']:records[badge]={'kind':'creative','author':req.author,'state_version':s.state_version+1}
                after={'badges':badges,'achievement_provenance':records}
            else:raise HTTPException(400,detail='unsupported intervention')
            for k,v in after.items():
                if k=='healed_party':continue
                changes.append({'op':'set','path':prefix+'.'+k,'value':v})
            changes.extend([{'op':'set','path':'world_facts.creative_modified','value':True},{'op':'set','path':'world_facts.last_intervention','value':{'author':req.author,'human_id':req.human_id,'kind':req.kind,'before':before,'after':after}}])
            try:event,new=engine().commit_changes(store,run_id,changes,kind='intervention.applied',actor=req.author,explanation='Explicit Creative intervention',provenance={'kind':'creative','author':req.author},expected_version=req.expected_state_version,details={'intervention':req.kind,'before':before,'after':after})
            except (EngineError,ContractError) as exc:fail(exc)
        return {'state_version':new.state_version,'event_id':event.event_id,'creative_modified':True}

    @app.get('/runs/{run_id}/battles')
    def battles(run_id:str):
        _,s,_=open_store(run_id).load_run(run_id)
        return {'battles':[{'battle_id':bid,'challenger':b['challenger'],'opponent':b['opponent'],'turn':b['turn'],'ended':b.get('ended',False),'outcome':b.get('outcome'),'log':b['session']['result']['log']} for bid,b in s.world_facts.get('battles',{}).items()]}

    @app.get('/runs/{run_id}/replay')
    def replay(run_id:str,cursor:int|None=None):
        store=open_store(run_id)
        try:
            with store._read_snapshot():
                verified=store.replay(run_id);state=store.load_genesis(run_id)
                events=store.iter_events(run_id)
            if cursor is None:state=verified
            else:
                if cursor < -1 or cursor >=len(events):raise HTTPException(400,detail='cursor outside committed history')
                for event in events[:cursor+1]:state=StateUpdate.from_dict(event.transaction).apply_to(state)
        except (StoreError,ContractError) as exc:fail(exc)
        return {'state':state.to_dict(),'event_count':len(events),'cursor':len(events)-1 if cursor is None else cursor,'verified':True,'inference_calls':0}

    @app.get('/runs/{run_id}/export')
    def export(run_id:str):
        store=open_store(run_id)
        try:
            with store._read_snapshot():
                meta,exported_state,exported_head=store.load_run(run_id);metadata=meta.to_dict();metadata['data_directory']=''
                bundle={'format':'living-kanto-run-v1','metadata':metadata,'genesis':store.load_genesis(run_id).to_dict(),'events':[e.to_dict() for e in store.iter_events(run_id)],'inference_settings_included':False,'state_hash':exported_state.state_hash,'head_hash':exported_head}
        except (StoreError,ContractError) as exc:fail(exc)
        # Model receipts contain model IDs and metrics, never endpoint credentials.
        from fastapi.responses import JSONResponse
        return JSONResponse(bundle,headers={'Content-Disposition':f'attachment; filename="{run_id}.json"'})


    @app.post('/runs/import',status_code=201)
    def import_run(bundle:dict):
        """Restore a hash-verified bundle under its original, unused run ID.

        Keeping identity preserves every canonical state/event hash. Import
        never rewrites historical events or accepts local inference settings.
        """
        if set(bundle)!={'format','metadata','genesis','events','inference_settings_included','state_hash','head_hash'} or bundle.get('format')!='living-kanto-run-v1' or bundle.get('inference_settings_included') is not False:
            raise HTTPException(400,detail='Unsupported portable run bundle')
        forbidden={'api_key','authorization','password','credentials','base_url','endpoint','endpoint_url','model_endpoint'}
        def reject_settings(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if str(key).lower() in forbidden:raise HTTPException(400,detail='Portable bundles cannot contain endpoint settings or credentials')
                    reject_settings(item)
            elif isinstance(value,list):
                for item in value:reject_settings(item)
        reject_settings(bundle)
        try:
            metadata=dict(bundle['metadata']);metadata['data_directory']='.'
            meta=RunMetadata.from_dict(metadata);genesis=WorldState.from_dict(bundle['genesis'])
            if not safe_run_id(meta.run_id):raise ValueError('Unsafe run identity')
            if not isinstance(bundle['events'],list) or len(bundle['events'])>100000:raise ValueError('Invalid or excessive event history')
            events=[CanonicalEvent.from_dict(event) for event in bundle['events']]
        except (ValueError,TypeError,KeyError,ContractError) as exc:fail(exc)
        path=app.state.base_dir/f'{meta.run_id}.db'
        with registry_lock, app.state.creation_lock(path):
            if path.exists() or meta.run_id in app.state.stores:raise HTTPException(409,detail='Imported run identity already exists; import into a separate save directory')
            handle=tempfile.NamedTemporaryFile(prefix='.import-',suffix='.sqlite',dir=app.state.base_dir,delete=False)
            staged=Path(handle.name);handle.close();store=None
            try:
                store=RunStore(staged);store.create_run(meta,genesis)
                for event in events:store.append_event(event,event.transaction['state_hash'])
                verified=store.replay(meta.run_id)
                if verified.state_hash!=bundle['state_hash'] or store.load_head(meta.run_id)!=bundle['head_hash']:raise ValueError('Portable state or event-chain head hash does not match')
                store.set_status(meta.run_id,'paused')
                store.close();store=None
                os.replace(staged,path)
                app.state.stores[meta.run_id]=RunStore(path)
            except (ValueError,KeyError,StoreError,ContractError,OSError) as exc:
                if store is not None:store.close()
                raise HTTPException(400,detail=str(exc))
            finally:
                staged.unlink(missing_ok=True)
                for suffix in ['-wal','-shm']:Path(str(staged)+suffix).unlink(missing_ok=True)
        return {'run_id':meta.run_id,'status':'paused','state_version':verified.state_version,'state_hash':verified.state_hash,'event_count':len(events),'inference_settings_imported':False}
