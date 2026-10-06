"""Every displayed native-effect pixel uses its original index and bound palette."""
import hashlib,json
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
def test_original_effect_pixels_and_palette_bindings():
 manifest=json.loads((ROOT/'content/field_effects/manifest.json').read_text())
 for descriptor in manifest['effects'].values():
  original=ROOT/'reference/pokefirered'/descriptor['source_png'];palette=ROOT/'reference/pokefirered'/descriptor['palette']
  assert hashlib.sha256(original.read_bytes()).hexdigest()==descriptor['source_png_sha256']
  assert hashlib.sha256(palette.read_bytes()).hexdigest()==descriptor['palette_sha256']
  colors=[tuple(map(int,line.split())) for line in palette.read_text().splitlines()[3:] if line.strip()]
  indexed=Image.open(original);output=Image.open(ROOT/descriptor['image'].lstrip('/'))
  assert indexed.size==output.size
  for index,rgba in zip(indexed.get_flattened_data(),output.get_flattened_data()):
   assert rgba==(*colors[index],0 if index==0 else 255)
