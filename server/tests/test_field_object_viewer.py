"""Environmental renderer mirrors private source overlays without extra minds."""
import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def test_source_objects_private_overlay_and_no_campaign_people():
    source=(ROOT/'client/js/field-objects.js').read_text().replace("import {loadActorFrames,drawActorFrame} from './actor-frames.js';",'const loadActorFrames=()=>{throw Error("not used")};')
    fixtures={name:json.loads((ROOT/f'content/maps/{name}.json').read_text()) for name in ['SeafoamIslands_B4F','Route12','CeladonCity_Condominiums_RoofRoom','PowerPlant']}
    code=source+'\nconst maps='+json.dumps(fixtures)+''';
const assert=(value,message)=>{if(!value)throw Error(message)};
const sea=maps.SeafoamIslands_B4F;
assert(!environmentalObjects(sea,{worldFacts:{static_encounters:{}}}).some(o=>o.sprite==='strength_boulder'),'initial hidden boulders');
const human={field:{revealed_boulders:['FLAG_HIDE_SEAFOAM_B4F_BOULDER_1'],boulders:{'SeafoamIslands_B4F:0':[12,18]}}};
const moved=environmentalObjects(sea,{human,worldFacts:{static_encounters:{articuno:{status:'caught'}}}});
assert(moved.some(o=>o.sprite==='strength_boulder'&&o.x===12),'personal position');
assert(!moved.some(o=>o.sprite==='articuno'),'global caught legendary');
assert(environmentalObjects(sea,{worldFacts:{static_encounters:{}}}).some(o=>o.sprite==='articuno'),'source available legendary');
const plant=maps.PowerPlant;
const fake=environmentalObjects(plant,{human:{field:{electrode_cleared:['electrode1']}}});
assert(!fake.some(o=>o.source.script==='PowerPlant_EventScript_Electrode1'),'fake ball claim');
const roof=maps.CeladonCity_Condominiums_RoofRoom,ball=roof.events.object_events.find(o=>o.graphics_id==='OBJ_EVENT_GFX_ITEM_BALL');
assert(!environmentalObjects(roof,{human:{collected_source_items:[`${roof.map_name}:${ball.local_id}:${ball.script}`]}}).some(o=>o.sprite==='item_ball'),'exact claimed item key');
const route=maps.Route12;
const initial=environmentalObjects(route);assert(initial.some(o=>o.sprite==='snorlax'),'source blocker visible');
const key=initial.find(o=>o.sprite==='snorlax').key;
assert(!environmentalObjects(route,{human:{field:{snorlax_cleared:[key]}}}).some(o=>o.sprite==='snorlax'),'private clear');
assert(!initial.some(o=>o.sprite==='fisher'),'campaign NPC is not AI resident');
assert(!environmentalObjects(maps.CeladonCity_Condominiums_RoofRoom,{human:{source_gifts:['eevee']}}).some(o=>o.sprite==='item_ball'),'gift claim hidden');
'''
    subprocess.run(['node','--input-type=module','-'],input=code,text=True,check=True,capture_output=True)

def test_source_terrain_patches_and_current_layout_selection():
    import hashlib
    maps={name:json.loads((ROOT/f'content/maps/{name}.json').read_text()) for name in ['PokemonMansion_1F','SilphCo_3F','VictoryRoad_1F','SeafoamIslands_B4F']}
    for map in maps.values():
        groups=[]
        groups.extend(door[status] for door in map['events'].get('card_key_doors',[]) for status in ['opened','closed'])
        groups.extend(switch['barriers'] for switch in map['events'].get('strength_switches',[]))
        if map['events'].get('mansion_switch'):groups.extend(map['events']['mansion_switch'][state] for state in ['on','off'])
        for tiles in groups:
            for tile in tiles:assert hashlib.sha256((ROOT/tile['image']).read_bytes()).hexdigest()==tile['image_sha256']
    code=(ROOT/'client/js/terrain-overlays.js').read_text()+'\nconst maps='+json.dumps(maps)+''';
const assert=(value)=>{if(!value)throw Error('Source terrain selection failed')};
const mansion=maps.PokemonMansion_1F;
assert(JSON.stringify(terrainPatches(mansion,{field:{mansion_switch:true}}))===JSON.stringify(mansion.events.mansion_switch.on));
const silph=maps.SilphCo_3F,door=silph.events.card_key_doors[0];
assert(terrainPatches(silph,{field:{doors:[door.id]}}).some(p=>door.opened.includes(p)));
const victory=maps.VictoryRoad_1F,plate=victory.events.strength_switches[0];
assert(terrainPatches(victory,{field:{switches:[plate.id]}}).length===plate.barriers.length);
assert(seafoamLayout(maps.SeafoamIslands_B4F,{field:{revealed_boulders:['FLAG_HIDE_SEAFOAM_B4F_BOULDER_1','FLAG_HIDE_SEAFOAM_B4F_BOULDER_2']}})==='/content/layouts/SeafoamIslands_B4F.png');
assert(seafoamLayout(maps.SeafoamIslands_B4F,{field:{}})===null);
'''
    subprocess.run(['node','--input-type=module','-'],input=code,text=True,check=True,capture_output=True)
