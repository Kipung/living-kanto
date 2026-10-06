#!/usr/bin/env python3
"""Import pinned source people and mainland spawn metadata without story flags."""
import json,re,sys,subprocess,hashlib
from pathlib import Path
from import_original_assets import import_actor,ACTOR_GRAPHICS_INFO,PINNED_REVISION,brace_block
ROOT=Path(__file__).resolve().parents[1]
def build():
 reference=ROOT/'reference/pokefirered'; oe=reference/'src/data/object_events'
 git_root=Path(subprocess.check_output(['git','-C',str(reference),'rev-parse','--show-toplevel'],text=True).strip())
 if git_root.resolve()==reference.resolve():
  revision=subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip()
  if revision!=PINNED_REVISION:raise SystemExit('Source revision differs from pinned FireRed reference')
 else:
  # Local reference is a copied tree inside the app checkout, not its own Git repo.
  pinned=json.loads((ROOT/'content/actors/prof_oak.json').read_text())
  if pinned['source_revision']!=PINNED_REVISION:raise SystemExit('Missing pinned source provenance')
  for path,digest in pinned['descriptor_source_sha256'].items():
   if hashlib.sha256((reference/path).read_bytes()).hexdigest()!=digest:raise SystemExit(f'Source descriptor differs from pinned reference: {path}')
 ptr=(oe/'object_event_graphics_info_pointers.h').read_text(); info=(oe/'object_event_graphics_info.h').read_text(); pics=(oe/'object_event_pic_tables.h').read_text(); gfx=(oe/'object_event_graphics.h').read_text()
 bindings=dict(re.findall(r'\[(OBJ_EVENT_GFX_\w+)\]\s*=\s*&gObjectEventGraphicsInfo_(\w+)',ptr))
 humans={}
 for constant,suffix in bindings.items():
  body=brace_block(info,rf'gObjectEventGraphicsInfo_{suffix}\s*=') or ''
  image=re.search(r'\.images\s*=\s*(\w+)',body)
  if not image:continue
  table=brace_block(pics,rf'{image[1]}\[\]\s*=') or ''
  sheets=re.findall(r'overworld_frame\(\s*(gObjectEventPic_\w+)',table)
  if not any(re.search(rf'{sheet}\[\].*?pics/people/',gfx) for sheet in sheets):continue
  slug=re.sub(r'(?<!^)(?=[A-Z][a-z])','_',suffix).lower()
  # Existing special aliases have stable names.
  slug=next((k for k,v in ACTOR_GRAPHICS_INFO.items() if v==suffix),slug)
  humans[constant]=(slug,suffix)
 maps=json.loads((ROOT/'content/region.json').read_text())['maps']; actors=[]
 for mid in sorted(m['id'] for m in maps):
  data=json.loads((ROOT/f'content/maps/{mid}.json').read_text())
  for index,obj in enumerate(data.get('events',{}).get('object_events',[])):
   if obj['graphics_id'] not in humans or str(obj.get('flag','0'))!='0':continue
   movement=obj.get('movement_type',''); facing={'UP':'north','DOWN':'south','LEFT':'west','RIGHT':'east'}
   direction=next((v for k,v in facing.items() if movement.endswith('_'+k)),'south')
   actors.append(dict(key=f"{mid}:{obj.get('local_id',index)}",map_id=mid,sprite=humans[obj['graphics_id']][0],x=obj['x'],y=obj['y'],elevation=obj.get('elevation',0),facing=direction,moving=False,graphics_id=obj['graphics_id'],source_script=obj.get('script'),source_movement=movement,source_local_id=obj.get('local_id',index),trainer_type=obj.get('trainer_type'),source_kind='source_npc',source_map_json=data.get('source_map_json'),source_map_json_sha256=data.get('source_map_json_sha256')))
 # Preserve only an unconditional direct msgbox from the actor's own script.
 for actor in actors:
  directory=reference/'data/maps'/actor['map_id']; script=directory/'scripts.inc'; texts=directory/'text.inc'
  if not script.exists() or not texts.exists():continue
  label=actor.get('source_script') or ''
  match=re.search(rf'^{re.escape(label)}::?\n(.*?)(?=^\w+::?|\Z)',script.read_text(),re.M|re.S)
  if not match or re.search(r'\b(?:goto_if\w*|call_if\w*|switch|compare|checkflag|trainerbattle\w*)\b',match[1]):continue
  msg=re.search(r'\bmsgbox\s+(\w+)',match[1])
  if not msg:continue
  body=re.search(rf'^{re.escape(msg[1])}::?\n(.*?)(?=^\w+::?|\Z)',texts.read_text(),re.M|re.S)
  if not body:continue
  pieces=re.findall(r'\.string\s+"(.*?)"',body[1]); raw=''.join(pieces)
  # Dynamic player/story substitution is not presented as generic conversation.
  if '{' in raw:continue
  text=raw.replace('\\n',' ').replace('\\l',' ').replace('\\p','\n\n').replace('$','').strip()
  if text:actor['dialogue']={'text':text,'source_script':label,'source_text':msg[1],'source_path':str(texts.relative_to(reference)),'source_text_sha256':hashlib.sha256(texts.read_bytes()).hexdigest(),'source_script_sha256':hashlib.sha256(script.read_bytes()).hexdigest()}
 used={a['graphics_id'] for a in actors}
 for constant in sorted(used):
  slug,suffix=humans[constant]; ACTOR_GRAPHICS_INFO[slug]=suffix
  import_actor(reference,ROOT/'content',slug)
 out=dict(schema_version=1,source_revision=PINNED_REVISION,mainland_maps=len(maps),actor_count=len(actors),visibility_policy='Only unconditional flag 0 source people; story contingent actors omitted.',movement_policy='Source starting positions and fixed source facing; random-facing/wandering actors hold south at their source origin until authoritative movement is implemented.',actors=actors)
 (ROOT/'content/source_npcs.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'actors':len(actors),'sprites':len(used)}))
if __name__=='__main__':build()
