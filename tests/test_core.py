import json
import pytest
import cadquery as cq
from aicad.core import *
from aicad.ai import interpret,_extract

@pytest.mark.parametrize('kind,dim', [('plate',(100,60,5)),('bracket',(80,30,50)),('enclosure',(120,80,40))])
def test_solids(kind,dim):
 solid=build(new_spec(kind));bb=solid.BoundingBox()
 assert solid.isValid() and len(solid.Solids())==1
 assert (round(bb.xlen),round(bb.ylen),round(bb.zlen))==dim

def test_holes():
 a=build(new_spec('plate',hole_count=4,hole_diameter=6));b=build(new_spec('plate'))
 assert b.Volume()-a.Volume()==pytest.approx(4*3.141592653589793*3**2*5,rel=1e-4)

def test_parse_and_edit():
 spec=parse_offline('Создай пластину 100×60×5 мм с четырьмя отверстиями диаметром 6 мм')
 assert spec.parameters['hole_count']==4
 changed=parse_offline('Измени толщину на 8 мм',spec)
 assert build(changed).BoundingBox().zlen==8
 assert changed.parameters['hole_count']==4

@pytest.mark.parametrize('text',['Сделай ракету','Создай пластину 100×60×5 с пятью отверстиями','Создай корпус 20×20×10 мм стенки 11 мм'])
def test_bad_parse(text):
 with pytest.raises(ValueError):parse_offline(text)

def test_bracket_parse():
 s=parse_offline('Создай кронштейн длиной 80 мм высотой 50 мм шириной 30 мм толщиной 5 мм')
 assert s.kind=='bracket' and s.parameters['vertical_height']==50

def test_enclosure_parse():
 s=parse_offline('Создай корпус 120×80×40 мм, стенки 3 мм, дно 3 мм')
 assert s.parameters['floor_thickness']==3

def test_save_load(tmp_path):
 s=new_spec('plate',hole_count=4,hole_diameter=6)
 f=tmp_path/'project.json';save_project(f,s)
 assert load_project(f).to_dict()==s.to_dict()

def test_export(tmp_path):
 solid=build(new_spec('plate',hole_count=4,hole_diameter=6))
 for ext in ['step','stl']:
  f=export_model(solid,tmp_path/('plate.'+ext));assert f.stat().st_size>100
  if ext=='step':
   imported=cq.importers.importStep(str(f)).val();assert imported.isValid()
   assert imported.Volume()==pytest.approx(solid.Volume(),rel=1e-5)

def test_schema_rejects_extra():
 d=new_spec('plate').to_dict();d['python']='print(1)'
 with pytest.raises(ValueError):from_dict(d)

def test_llm_invalid():
 with pytest.raises(ValueError):_extract('not json')
 with pytest.raises(ValueError):_extract('{"schema_version":1,"kind":"plate","units":"mm","parameters":{"length":0}}')

def test_fallback():
 spec,mode=interpret('Создай пластину 100×60×5 мм',mode='Auto',config={'consent':False,'ollama_model':''})
 assert spec.kind=='plate' and mode.startswith('Offline')
