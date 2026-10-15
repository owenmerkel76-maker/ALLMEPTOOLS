"""Offline structure / source-copy integrity checks for consolidated pyRevit ribbon."""
from pathlib import Path
import ast
import hashlib
import json
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
TAB=ROOT/'ROBMEPTOOLS.extension'/'ROBMEPTOOLS.tab'
EXPECTED = {
 'AutoDim.panel':('AutoDim Smart',),
 'AutoTag.panel':('AutoTag Smart',),
 'Annotation.panel':('Tag Dim Organizer',),
 'Fab Hover.panel':('FabHover',),
 'Fabrication.panel':('Fab Ref Probe','Fab Ref Classifier'),
 'Hangers.panel':('Auto Hanger','Repair Draft Rods','Review Extra Hangers'),
 'Hanger Steel.panel':('Joist Groups','Reconstruct Steel','Import Navis BOS','Probe NWD'),
 'Roof Deck.panel':('Roof Deck From IFC','Roof Deck From DXF'),
 'Schedules.panel':('ROBMEPTOOLS Schedule Number',),
 'Updates.panel':('Update Tool',),
}

def validate():
 errors=[]
 actual_panels = {p.name for p in TAB.glob('*.panel')}
 if actual_panels != set(EXPECTED): errors.append('Panels mismatch: %r'%(actual_panels^set(EXPECTED),))
 for panel,commands in EXPECTED.items():
  pd=TAB/panel
  observed={p.name.removesuffix('.pushbutton') for p in pd.glob('*.pushbutton')}
  if observed!=set(commands): errors.append('Button mismatch in '+panel+': '+str(observed^set(commands)))
  for name in commands:
   d=pd/(name+'.pushbutton')
   for f in ('bundle.yaml','script.py','icon.png'):
    if not (d/f).is_file():errors.append('Missing '+str(d/f))
 main=(TAB/'bundle.yaml').read_text()
 for name in EXPECTED:
  if '  - '+name.removesuffix('.panel') not in main:errors.append('Panel missing in tab layout: '+name)
 src=(ROOT/'ROBMEPTOOLS.extension'/'startup.py').read_text()
 if 'update_installed(' in src:errors.append('Old remote startup updater is enabled!')
 update_script=(TAB/'Updates.panel'/'Update Tool.pushbutton'/'script.py').read_text()
 if 'update_installed(' in update_script:errors.append('Old update tool is enabled!')
 if (ROOT/'ROBMEPTOOLS.extension'/'update-manifest.json').exists():errors.append('Old hash manifest must not ship in merged extension')
 for p in (ROOT/'ROBMEPTOOLS.extension').rglob('*.xaml'):
  try:ET.parse(p)
  except ET.ParseError as e:errors.append('Bad XML '+str(p)+': '+str(e))
 for p in (ROOT/'ROBMEPTOOLS.extension').rglob('*.py'):
  try:ast.parse(p.read_bytes(),str(p))
  except SyntaxError as e:errors.append('Bad Python syntax '+str(p)+': '+str(e))
 return errors

if __name__=='__main__':
 errors=validate()
 print('Found',sum(len(v) for v in EXPECTED.values()),'commands in',len(EXPECTED),'panels.')
 for e in errors:print('FAIL:',e)
 print('FAIL' if errors else 'PASS — unified ribbon structural checks')
 if not errors:print('Runtime behavior needs Revit testing; missing AutoSleeve not represented as an installed command.')
 sys.exit(bool(errors))
