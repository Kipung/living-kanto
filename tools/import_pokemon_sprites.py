#!/usr/bin/env python3
"""Apply original normal palette to original first-151 front/back PNGs."""
import hashlib,json,re
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];REF=ROOT/'reference/pokefirered';out=ROOT/'content/pokemon';out.mkdir(exist_ok=True)
names={n.lower() for n,v in re.findall(r'#define SPECIES_(\w+)\s+(\d+)',(REF/'include/constants/species.h').read_text()) if 1<=int(v)<=151};assets=[]
for name in sorted(names):
 folder=REF/'graphics/pokemon'/name;palette_path=folder/'normal.pal'
 palette=[tuple(map(int,x.split())) for x in palette_path.read_text().splitlines()[3:19]]
 for facing in ('front','back'):
  source=folder/(facing+'.png');image=Image.open(source);rgba=Image.new('RGBA',image.size);rgba.putdata([(*palette[i],0 if i==0 else 255) for i in image.get_flattened_data()]);dest=out/(name+'_'+facing+'.png');rgba.save(dest)
  assets.append({'path':str(dest.relative_to(ROOT)),'source':str(source.relative_to(ROOT)),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'palette':str(palette_path.relative_to(ROOT))})
(ROOT/'content/pokemon_asset_manifest.json').write_text(json.dumps({'source_revision':'037335f4c725d7c9aecdac87066f2002b4bd7e14','usage':'Original Nintendo/Game Freak pixels; no open license claimed. Palette application only; no generated artwork.','assets':assets},indent=2)+'\n')
