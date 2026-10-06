#!/usr/bin/env python3
"""Import pinned FireRed field sprites and source animation commands, with palettes."""
from pathlib import Path
import hashlib,json,re,sys
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];REF=ROOT/'reference/pokefirered'
sys.path.insert(0,str(ROOT/'tools'))
from import_original_assets import load_jasc_pal
OUT=ROOT/'content/field_effects';OUT.mkdir(exist_ok=True)
text=(REF/'src/data/field_effects/field_effect_objects.h').read_text()
gfx=(REF/'src/data/object_events/object_event_graphics.h').read_text()
revision='037335f4c725d7c9aecdac87066f2002b4bd7e14'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def anim(name):
 m=re.search(r'\b'+re.escape(name)+r'\[\]\s*=\s*\{(.*?)\};',text,re.S);assert m,name
 frames=[{'frame':int(a),'duration':int(b),'hFlip':'.hFlip = TRUE' in flags,'vFlip':'.vFlip = TRUE' in flags} for a,b,flags in re.findall(r'ANIMCMD_FRAME\(\s*(\d+)\s*,\s*(\d+)\s*([^)]*)\)',m[1])]
 return {'symbol':name,'frames':frames,'loops':'ANIMCMD_JUMP' in m[1],'ends':'ANIMCMD_END' in m[1]}
def add(name,source,palette,w,h,anims,source_definition):
 image=Image.open(REF/source);assert image.mode=='P',source
 colors=load_jasc_pal(REF/palette);image.putpalette([c for rgb in colors for c in rgb]+[0]*(768-len(colors)*3));image.info['transparency']=0;rgba=image.convert('RGBA');dest=OUT/(name+'.png');rgba.save(dest)
 rows=[];cols=rgba.width//w
 for i in range((rgba.width//w)*(rgba.height//h)):rows.append({'frame':i,'sx':i%cols*w,'sy':i//cols*h,'width':w,'height':h})
 for a in anims.values():assert all(0<=f['frame']<len(rows) for f in a['frames'])
 manifest['effects'][name]={'image':'/content/field_effects/'+dest.name,'frames':rows,'anims':anims,'source_png':source,'source_png_sha256':sha(REF/source),'palette':palette,'palette_sha256':sha(REF/palette),'output_sha256':sha(dest),'source_definition':source_definition}
manifest={'source_revision':revision,'fps':60,'effects':{},'adaptations':['Surf blob and Fly bird use the original player palette for shared trainers. Flash uses the source circular visibility window, not a made-up particle sprite.']}
base='graphics/field_effects/pics/'
for name,stem,w,h,pal,animations in [
 ('ripple','ripple',16,16,'general_1',['sAnim_Ripple']),('splash','jump_big_splash',16,16,'general_0',['sAnim_JumpBigSplash']),('dust','ground_impact_dust',16,8,'general_0',['sAnim_GroundImpactDust']),('grass','tall_grass',16,16,'general_1',['sAnim_TallGrass'])]:
 add(name,base+stem+'.png','graphics/field_effects/palettes/'+pal+'.pal',w,h,{'default':anim(a) for a in animations},'src/data/field_effects/field_effect_objects.h')
add('surf','graphics/object_events/pics/misc/surf_blob.png','graphics/object_events/palettes/player.pal',32,32,{d:anim('sSurfBlobAnim_Face'+d.title()) for d in ['south','north','west','east']},'src/data/field_effects/field_effect_objects.h:sAnimTable_SurfBlob')
add('fly',base+'bird.png','graphics/object_events/palettes/player.pal',64,64,{'default':anim('sAnim_Bird_WithoutPlayer')},'src/data/field_effects/field_effect_objects.h:sAnimTable_Bird')
for name in ['cut_tree','strength_boulder']:
 descriptor=json.loads((ROOT/'content/actors'/f'{name}.json').read_text());sheet=descriptor['sheets'][0];source=sheet['source_png'];palette=descriptor['palette_binding']['pal_path_in_checkout'];a=descriptor['anims']['ANIM_REMOVE_OBSTACLE' if name=='cut_tree' else 'ANIM_STAY_STILL']
 add(name,source,palette,16,16,{'default':a},'src/data/object_events/object_event_anims.h:'+descriptor['anim_table_symbol'])
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Imported',len(manifest['effects']),'original field sprites with source palettes and60Hz animation timing')
