import tempfile, unittest
from pathlib import Path
import cadquery as cq
from aicad.universal import Model, save_model, load_model
from aicad.commands import execute
from aicad.universal_ai import decode, request_commands
from aicad.core import new_spec


def bracket():
 m=Model();m.set_parameter('length',80);m.set_parameter('width',30)
 sk=m.add('sketch',{'plane':'XZ','entities':[{'type':'polygon','points':[[0,0],['length',0],['length',8],[8,8],[8,60],[0,60]]}]})
 body=m.add('extrude',{'distance':'width'},[sk])
 for center in ([20,-31,0],[60,-31,0],[0,-31,40]):
  body=m.add('hole',{'center':center,'radius':3,'depth':32,'axis':'Y'},[body])
 notch=m.add('box',{'length':15,'width':12,'height':20})
 placed=m.add('transform',{'translation':[40,-15,0],'rotation':[0,0,0]},[notch])
 m.add('cut',{},[body,placed]);return m


def enclosure():
 m=Model();m.set_parameter('length',120)
 outer=m.add('box',{'length':'length','width':80,'height':40})
 cavity=m.add('box',{'length':'length-6','width':74,'height':40})
 shifted=m.add('transform',{'translation':[0,0,3],'rotation':[0,0,0]},[cavity])
 body=m.add('cut',{},[outer,shifted])
 post=m.add('cylinder',{'radius':5,'height':15})
 for x,y in [(-45,-25),(45,-25),(-45,25),(45,25)]:
  placed=m.add('transform',{'translation':[x,y,3],'rotation':[0,0,0]},[post])
  body=m.add('union',{},[body,placed])
 for x,y in [(-45,-25),(45,-25),(-45,25),(45,25)]:
  body=m.add('hole',{'center':[x,y,3],'radius':2,'depth':16,'axis':'Z'},[body])
 side=m.add('hole',{'center':[-61,0,20],'radius':4,'depth':10,'axis':'X'},[body])
 return m


def lofted_part():
 m=Model();m.set_parameter('base_width',60)
 a=m.add('sketch',{'plane':'XY','entities':[{'type':'rectangle','center':[0,0],'width':'base_width','height':40}]})
 b=m.add('sketch',{'plane':'XY','origin':[0,0,30],'entities':[{'type':'rectangle','center':[0,0],'width':30,'height':20}]})
 body=m.add('loft',{'ruled':False},[a,b])
 tab=m.add('sketch',{'plane':'XY','entities':[{'type':'polygon','points':[[30,-8],[48,-8],[48,8],[30,8]]}]})
 tab_body=m.add('extrude',{'distance':5},[tab])
 combined=m.add('union',{},[body,tab_body])
 m.add('hole',{'center':[40,0,0],'radius':3,'depth':5,'axis':'Z'},[combined])
 return m

class UniversalTests(unittest.TestCase):
 def test_three_models(self):
  for builder in (bracket,enclosure,lofted_part):
   with self.subTest(builder=builder.__name__):
    m=builder();solid=m.solid();self.assertTrue(solid.isValid());self.assertGreater(solid.Volume(),100)
    with tempfile.TemporaryDirectory() as directory:
     path=Path(directory);save_model(path/'model.aicad.json',m)
     loaded=load_model(path/'model.aicad.json');self.assertAlmostEqual(loaded.solid().Volume(),solid.Volume(),places=4)
     cq.exporters.export(loaded.solid(),str(path/'model.step'))
     self.assertTrue(cq.importers.importStep(str(path/'model.step')).val().isValid())
 def test_hybrid_rebuild_and_atomic_ai(self):
  m=Model();m.set_parameter('length',80)
  base=m.add('sketch',{'plane':'XY','entities':[{'type':'rectangle','center':[0,0],'width':'length','height':40}]})
  commands=[{'action':'add','kind':'extrude','params':{'distance':8},'refs':[base],'alias':'body'},
            {'action':'add','kind':'hole','params':{'center':[20,0,0],'radius':4,'depth':8,'axis':'Z'},'refs':['body']}]
  execute(m,commands);before=m.solid().Volume()
  m.set_parameter('length',100);self.assertGreater(m.solid().Volume(),before)
  last=m.features[-1];m.update(last.id,params={'center':[25,0,0],'radius':5,'depth':8,'axis':'Z'})
  with tempfile.TemporaryDirectory() as directory:
   save_model(Path(directory)/'hybrid.json',m);self.assertAlmostEqual(load_model(Path(directory)/'hybrid.json').solid().Volume(),m.solid().Volume())
  snapshot=m.to_dict()
  with self.assertRaises(ValueError):execute(m,[{'action':'add','kind':'box','params':{'length':10,'width':10,'height':10}}, {'action':'add','kind':'box','params':{'length':0,'width':10,'height':10}}])
  self.assertEqual(m.to_dict(),snapshot)
 def test_ai_schema_and_legacy(self):
  m=Model();cmds,mode=request_commands('Добавь цилиндр диаметром 20 мм и высотой 40 мм','Offline',m,{})
  execute(m,cmds);self.assertGreater(m.solid().Volume(),0)
  with self.assertRaises(ValueError):decode('{"commands":[],"code":"print(1)"}')
  old=Model.from_dict(new_spec('plate').to_dict());self.assertGreater(old.solid().Volume(),0)
 def test_invalid_reference_and_expression(self):
  m=Model()
  with self.assertRaises(ValueError):m.add('extrude',{'distance':3},['missing'])
  with self.assertRaises(ValueError):m.add('box',{'length':'__import__("os")','width':3,'height':4})
  self.assertEqual(len(m.features),0)

if __name__=='__main__':unittest.main()

class ProviderTests(unittest.TestCase):
 def test_cloud_consent_and_fallback(self):
  m=Model()
  commands,mode=request_commands('Создай пластину 100×60×5 мм','Auto',m,{'consent':False,'ollama_model':'','fallback':True})
  self.assertEqual(mode,'Offline (резерв)');self.assertEqual(commands[0]['kind'],'legacy_part')
  with self.assertRaises(ValueError):request_commands('Создай пластину 100×60×5 мм','Cloud',m,{'consent':False,'fallback':False})
 def test_invalid_ai_batch_cannot_damage_model(self):
  m=Model();m.add('box',{'length':10,'width':10,'height':10});before=m.to_dict()
  with self.assertRaises(ValueError):execute(m,[{'action':'add','kind':'box','params':{'length':-1,'width':10,'height':10}}])
  self.assertEqual(before,m.to_dict())

class OfflineWorkflowTests(unittest.TestCase):
 def test_shared_operations_from_text(self):
  m=Model()
  for text in ('Создай эскиз прямоугольник 80×50 мм','Выдави последний эскиз на 8 мм','Добавь отверстие диаметром 6 мм глубиной 8 мм в точке x=20 y=0 z=0'):
   commands,mode=request_commands(text,'Offline',m,{});self.assertEqual(mode,'Offline');execute(m,commands)
  self.assertEqual([f.kind for f in m.features],['sketch','extrude','hole'])
  self.assertAlmostEqual(m.solid().Volume(),80*50*8-3.141592653589793*3**2*8,places=4)

class AdditionalOperationTests(unittest.TestCase):
 def test_sweep_shell_patterns_and_constraints(self):
  m=Model();profile=m.add('sketch',{'plane':'YZ','entities':[{'type':'circle','center':[0,0],'radius':3}]})
  path=m.add('sketch',{'plane':'XZ','entities':[{'type':'path','points':[[0,0],[20,0],[20,30]]}]})
  m.add('sweep',{'is_frenet':False},[profile,path]);self.assertTrue(m.solid().isValid())
  box=Model();base=box.add('box',{'length':80,'width':50,'height':40})
  shell=box.add('shell',{'thickness':3,'face':'>Z'},[base]);self.assertTrue(box.solid().isValid())
  box.add('mirror',{'plane':'YZ','origin':[0,0,0]},[shell]);self.assertTrue(box.solid().isValid())
  p=Model();a=p.add('box',{'length':10,'width':5,'height':5});p.add('linear_pattern',{'count':3,'step':[15,0,0]},[a]);self.assertEqual(len(p.solid().Solids()),3)
  good={'plane':'XY','entities':[{'type':'line','start':[0,0],'end':[10,0]}],'constraints':[{'type':'horizontal','entity':0},{'type':'length','entity':0,'value':10}]}
  Model().add('sketch',good)
  bad=dict(good);bad['constraints']=[{'type':'vertical','entity':0}]
  with self.assertRaises(ValueError):Model().add('sketch',bad)

class MockProviderTests(unittest.TestCase):
 def test_cloud_structured_response_and_invalid_fallback(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  import aicad.universal_ai as ai
  m=Model()
  payload='{"commands":[{"action":"add","kind":"box","params":{"length":10,"width":20,"height":30}}]}'
  class Response:
   def __init__(self,content):self.content=content
   def raise_for_status(self):pass
   def json(self):return {'choices':[{'message':{'content':self.content}}]}
  calls=[]
  def post(url,headers=None,json=None,timeout=None):
   calls.append((url,headers,json));return Response(payload)
  fake=SimpleNamespace(post=post,RequestException=OSError)
  config={'consent':True,'cloud_url':'https://example.test/v1','cloud_model':'mock','api_key':'SECRET','fallback':False}
  with patch.object(ai,'requests',fake):
   commands,mode=ai.request_commands('create','Cloud',m,config)
  self.assertEqual(mode,'Cloud');self.assertEqual(commands[0]['kind'],'box')
  self.assertEqual(calls[0][1]['Authorization'],'Bearer SECRET')
  self.assertEqual(len(m.features),0)
  def bad(*args,**kwargs):return Response('not json')
  fake.post=bad
  with patch.object(ai,'requests',fake):
   with self.assertRaises(ValueError):ai.request_commands('create','Cloud',m,config)
  self.assertEqual(len(m.features),0)

class CompatibilityAndEdgeTests(unittest.TestCase):
 def test_v2_import_and_revolve_edge_features(self):
  from aicad.project import Project
  p=Project();item=p.add(new_spec('plate'));p.update(item.id,position=(10,0,0))
  m=Model.from_dict(p.to_dict());self.assertEqual(m.solid().BoundingBox().xmin,-40)
  m=Model();s=m.add('sketch',{'plane':'XY','entities':[{'type':'polygon','points':[[5,0],[15,0],[15,20],[5,20]]}]})
  body=m.add('revolve',{'angle':360,'axis_start':[0,0,0],'axis_end':[0,1,0]},[s]);self.assertTrue(m.solid().isValid())
  f=Model();base=f.add('box',{'length':80,'width':50,'height':20});f.add('fillet',{'radius':2,'selector':'|Z'},[base]);self.assertTrue(f.solid().isValid())
  c=Model();base=c.add('box',{'length':80,'width':50,'height':20});c.add('chamfer',{'radius':2,'selector':'|Z'},[base]);self.assertTrue(c.solid().isValid())

class ProfileTests(unittest.TestCase):
 def test_mixed_arc_profile(self):
  m=Model();s=m.add('sketch',{'plane':'XY','entities':[{'type':'profile','start':[0,0],'segments':[{'type':'line','to':[20,0]},{'type':'arc','mid':[25,10],'to':[20,20]},{'type':'line','to':[0,20]}],'closed':True}]})
  m.add('extrude',{'distance':5},[s]);self.assertTrue(m.solid().isValid());self.assertGreater(m.solid().Volume(),2000)
  with self.assertRaises(ValueError):Model().add('sketch',{'plane':'XY','entities':[{'type':'profile','start':[0,0],'segments':[{'type':'arc','mid':[0,0],'to':[1,1]}],'closed':True}]})


class BatchAliasRegressionTests(unittest.TestCase):
 def test_update_can_reference_alias_created_in_same_batch(self):
  m=Model()
  execute(m,[{'action':'add','kind':'box','params':{'length':10,'width':10,'height':10},'alias':'first'},
             {'action':'add','kind':'box','params':{'length':5,'width':5,'height':5},'alias':'second'},
             {'action':'add','kind':'cut','params':{},'refs':['first','second'],'alias':'result'},
             {'action':'update','id':'result','refs':['first','second']}])
  self.assertEqual(m.features[2].refs,[m.features[0].id,m.features[1].id])

 def test_bad_alias_does_not_change_project(self):
  m=Model();before=m.to_dict()
  with self.assertRaises(ValueError):
   execute(m,[{'action':'add','kind':'box','params':{'length':10,'width':10,'height':10},'alias':'not-valid!'}])
  self.assertEqual(m.to_dict(),before)
