import json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cadquery as cq
import aicad.universal_ai as ai
from aicad.universal import Model,save_model,load_model
from aicad.commands import execute
from aicad.core import export_model

CONFIG={'consent':True,'cloud_url':'https://api.mistral.ai/v1','cloud_model':'mistral-large-latest','api_key':'IGNORED_UI_FIELD','fallback':False}

_mock_environment=None
def setUpModule():
 global _mock_environment
 _mock_environment=patch.dict(os.environ,{'MISTRAL_API_KEY':'TEST_ONLY_TOKEN'});_mock_environment.start()
def tearDownModule():
 _mock_environment.stop()

class Response:
 def __init__(self,content=None,status=200,models=None):self.content=content;self.status_code=status;self.models=models
 def raise_for_status(self):
  if self.status_code>=400:raise OSError('HTTP error')
 def json(self):
  if self.models is not None:return {'data':[{'id':name} for name in self.models]}
  return {'choices':[{'message':{'content':self.content}}]}

class FakeAPI:
 def __init__(self,responses,status=200):self.responses=list(responses);self.status=status;self.calls=[]
 def post(self,url,headers=None,json=None,timeout=None):
  self.calls.append((url,headers,json,timeout))
  content=self.responses.pop(0)
  return Response(content,self.status)
 def get(self,url,headers=None,timeout=None):
  self.calls.append((url,headers,None,timeout))
  return Response(status=self.status,models=['mistral-large-latest'])
 @property
 def namespace(self):return SimpleNamespace(post=self.post,get=self.get,RequestException=OSError,Timeout=TimeoutError,ConnectionError=ConnectionError)


def plan(commands):return json.dumps({'commands':commands},ensure_ascii=False)

def enclosure_plan():
 commands=[{'action':'add','kind':'box','params':{'length':140,'width':90,'height':45},'alias':'outer'},
           {'action':'add','kind':'shell','params':{'thickness':3,'face':'>Z'},'refs':['outer'],'alias':'shell'},
           {'action':'add','kind':'cylinder','params':{'radius':5,'height':13},'alias':'post'}]
 body='shell'
 for index,(x,y) in enumerate([(-50,-30),(50,-30),(-50,30),(50,30)]):
  placed='p'+str(index);newbody='b'+str(index)
  commands.append({'action':'add','kind':'transform','params':{'translation':[x,y,2],'rotation':[0,0,0]},'refs':['post'],'alias':placed})
  commands.append({'action':'add','kind':'union','params':{},'refs':[body,placed],'alias':newbody})
  body=newbody
 for index,(x,y) in enumerate([(-50,-30),(50,-30),(-50,30),(50,30)]):
  drilled='h'+str(index)
  commands.append({'action':'add','kind':'hole','params':{'center':[x,y,2],'radius':2,'depth':13,'axis':'Z'},'refs':[body],'alias':drilled})
  body=drilled
 return commands

class MistralIntegrationTests(unittest.TestCase):
 def test_health_and_correct_engineering_plan(self):
  fake=FakeAPI([plan(enclosure_plan())]);m=Model()
  with patch.object(ai,'requests',fake.namespace):
   self.assertIn('подключён',ai.check_connection('Mistral',CONFIG))
   commands,mode=ai.request_commands('Создай корпус устройства 140×90×45 мм со стенками 3 мм и четырьмя стойками','Mistral',m,CONFIG)
  self.assertEqual(mode,'Mistral');self.assertEqual(len(commands),15)
  self.assertEqual(len(m.features),0) # Построение плана не должно изменять рабочую модель.
  execute(m,commands);self.assertTrue(m.solid().isValid());self.assertEqual(len(m.features),15)
  self.assertEqual(fake.calls[1][0],'https://api.mistral.ai/v1/chat/completions')
  self.assertEqual(fake.calls[1][2]['response_format'],{'type':'json_object'})
  self.assertEqual(fake.calls[1][1]['Authorization'],'Bearer TEST_ONLY_TOKEN')
  self.assertTrue(all(f.source=='ai' for f in m.features))
  with tempfile.TemporaryDirectory() as directory:
   out=Path(directory);save_model(out/'case.aicad.json',m);loaded=load_model(out/'case.aicad.json')
   self.assertAlmostEqual(loaded.solid().Volume(),m.solid().Volume(),places=4)
   step=export_model(loaded.solid(),out/'case.step');stl=export_model(loaded.solid(),out/'case.stl')
   self.assertGreater(step.stat().st_size,100);self.assertGreater(stl.stat().st_size,100)
   self.assertTrue(cq.importers.importStep(str(step)).val().isValid())
 def test_invalid_json_unknown_op_and_geometry_repaired(self):
  corrected=plan([{'action':'add','kind':'box','params':{'length':20,'width':10,'height':5}}])
  invalid=['not json',plan([{'action':'add','kind':'teleport','params':{}}]),plan([{'action':'add','kind':'box','params':{'length':0,'width':10,'height':5}}])]
  for first in invalid:
   with self.subTest(first=first):
    fake=FakeAPI([first,corrected]);m=Model()
    with patch.object(ai,'requests',fake.namespace):commands,_=ai.request_commands('Создай деталь 20×10×5 мм','Mistral',m,CONFIG)
    self.assertEqual(len(fake.calls),2)
    self.assertIn('не удалось исполнить',fake.calls[1][2]['messages'][-1]['content'])
    execute(m,commands);self.assertAlmostEqual(m.solid().Volume(),1000)
 def test_double_failure_rollback_and_http_errors(self):
  m=Model();m.add('box',{'length':10,'width':10,'height':10});before=m.to_dict()
  fake=FakeAPI(['invalid','still invalid'])
  with patch.object(ai,'requests',fake.namespace):
   with self.assertRaises(ValueError):ai.request_commands('Сделай изменение','Mistral',m,CONFIG)
  self.assertEqual(m.to_dict(),before)
  for status,label in ((401,'авторизации'),(429,'Лимит')):
   fake=FakeAPI([],status)
   with patch.object(ai,'requests',fake.namespace):
    with self.assertRaisesRegex(ValueError,label):ai.check_connection('Mistral',CONFIG)
 def test_continue_manual_model_and_repair_edit(self):
  m=Model();base=m.add('box',{'length':80,'width':50,'height':30},name='ручная заготовка')
  first=plan([{'action':'add','kind':'hole','params':{'center':[20,0,0],'radius':3,'depth':30,'axis':'Z'},'refs':[base]}])
  fake=FakeAPI([first]);old=m.solid().Volume()
  with patch.object(ai,'requests',fake.namespace):commands,_=ai.request_commands('Добавь отверстие в существующей заготовке','Mistral',m,CONFIG)
  execute(m,commands);self.assertLess(m.solid().Volume(),old)
  hole=m.features[-1]
  second=plan([{'action':'update','id':hole.id,'params':{'center':[25,0,0],'radius':4,'depth':30,'axis':'Z'}}])
  fake=FakeAPI([second]);old=m.solid().Volume()
  with patch.object(ai,'requests',fake.namespace):commands,_=ai.request_commands('Увеличь отверстие и перемести ближе к краю','Mistral',m,CONFIG)
  execute(m,commands);self.assertLess(m.solid().Volume(),old)
  self.assertEqual(m.features[0].id,base)
  self.assertEqual(m.features[-1].id,hole.id)

if __name__=='__main__':unittest.main()

class EnclosureFollowupTests(unittest.TestCase):
 def test_second_turn_updates_existing_enclosure(self):
  model=Model();execute(model,enclosure_plan())
  original_ids=[feature.id for feature in model.features]
  shell=next(feature for feature in model.features if feature.kind=='shell')
  transforms=[feature for feature in model.features if feature.kind=='transform']
  holes=[feature for feature in model.features if feature.kind=='hole']
  changes=[{'action':'update','id':shell.id,'params':{'thickness':4,'face':'>Z'}}]
  for feature,(x,y) in zip(transforms,[(-55,-35),(55,-35),(-55,35),(55,35)]):
   changes.append({'action':'update','id':feature.id,'params':{'translation':[x,y,2],'rotation':[0,0,0]}})
  for feature,(x,y) in zip(holes,[(-55,-35),(55,-35),(-55,35),(55,35)]):
   changes.append({'action':'update','id':feature.id,'params':{'center':[x,y,2],'radius':2,'depth':13,'axis':'Z'}})
  changes.append({'action':'add','kind':'fillet','params':{'radius':1,'selector':'|Z'},'refs':[model.features[-1].id]})
  fake=FakeAPI([plan(changes)])
  with patch.object(ai,'requests',fake.namespace):
   commands,_=ai.request_commands('Увеличь стенки до 4 мм, перемести крепёжные отверстия ближе к углам и добавь скругления','Mistral',model,CONFIG)
  self.assertEqual([feature.id for feature in model.features],original_ids)
  execute(model,commands)
  self.assertEqual([feature.id for feature in model.features[:-1]],original_ids)
  self.assertEqual(model.features[-1].kind,'fillet')
  self.assertEqual(model.features[1].params['thickness'],4)
  self.assertTrue(model.solid().isValid())
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'edited.aicad.json';save_model(path,model)
   self.assertAlmostEqual(load_model(path).solid().Volume(),model.solid().Volume(),places=4)

class NetworkErrorTests(unittest.TestCase):
 def test_timeout_and_no_consent(self):
  def timeout(*args,**kwargs):raise TimeoutError('socket timeout')
  fake=SimpleNamespace(post=timeout,get=timeout,RequestException=OSError,Timeout=TimeoutError,ConnectionError=ConnectionError)
  with patch.object(ai,'requests',fake):
   with self.assertRaisesRegex(ValueError,'Истекло время ожидания'):
    ai.request_commands('Создай объект','Mistral',Model(),CONFIG)
   with self.assertRaisesRegex(ValueError,'не разрешена'):
    ai.request_commands('Создай объект','Mistral',Model(),dict(CONFIG,consent=False))
 def test_mistral_ignores_cloud_key_field(self):
  fake=FakeAPI([])
  with patch.dict(os.environ,{'MISTRAL_API_KEY':''}),patch.object(ai,'requests',fake.namespace):
   with self.assertRaisesRegex(ValueError,'ключ отсутствует'):
    ai.check_connection('Mistral',CONFIG)
