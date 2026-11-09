"""Обработка структурированных запросов через облачный сервис или Ollama с явным согласием пользователя и резервным локальным режимом."""
import json, os, re
import requests
from .core import from_dict, PartSpec, parse_offline

SYSTEM = '''You are a mechanical CAD command parser. Return ONLY JSON, no prose or code.
Schema: {"schema_version":1,"kind":"plate|bracket|enclosure|box|cylinder|sphere","units":"mm","parameters":{...}}.
Plate fields length,width,thickness,hole_diameter,hole_count,edge_offset. hole_count 0 or 4.
Bracket fields horizontal_length,vertical_height,width,thickness.
Enclosure fields length,width,height,wall_thickness,floor_thickness. Box fields length,width,height. Cylinder fields diameter,height. Sphere field diameter. For an edit, return a full updated spec based on the supplied current spec.
All numeric, units mm. Ask for missing information by returning {"error":"..."}.
Never return source code, paths, markdown or extra keys.'''

def _extract(content):
 content=content.strip();content=re.sub(r'^```(?:json)?\s*|\s*```$','',content)
 data=json.loads(content)
 if not isinstance(data,dict):raise ValueError('ИИ вернул неверный JSON')
 if 'error' in data:raise ValueError(str(data['error'])[:300])
 return from_dict(data)

def cloud(prompt,base_url,model,key,consent,timeout=15,current=None):
 if not consent:raise PermissionError('Отправка в облако запрещена. Разрешите её в настройках.')
 if not key or not model:raise ValueError('Укажите API-ключ и модель')
 base_url=base_url.rstrip('/')
 if not base_url.startswith('https://'):raise ValueError('Облачный API должен использовать HTTPS')
 r=requests.post(base_url+'/chat/completions',headers={'Authorization':'Bearer '+key},json={'model':model,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':prompt + ('\nCurrent spec: '+json.dumps(current.to_dict()) if current else '')}],'temperature':0},timeout=timeout)
 r.raise_for_status();return _extract(r.json()['choices'][0]['message']['content'])

def ollama(prompt,base_url,model,timeout=20,current=None):
 if not model:raise ValueError('Укажите модель Ollama')
 base_url=base_url.rstrip('/')
 if not re.fullmatch(r'http://(localhost|127\.0\.0\.1)(:\d+)?',base_url):
  raise ValueError('Для MVP Ollama доступна только локально')
 r=requests.post(base_url+'/api/chat',json={'model':model,'stream':False,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':prompt + ('\nCurrent spec: '+json.dumps(current.to_dict()) if current else '')}],'format':'json'},timeout=timeout)
 r.raise_for_status();return _extract(r.json()['message']['content'])

def interpret(prompt,mode='Offline',current=None,config=None):
 config=config or {};errors=[]
 modes={'Offline':[], 'Cloud':['Cloud'], 'Ollama':['Ollama'], 'Auto':['Cloud','Ollama']}
 if mode not in modes:raise ValueError('Неизвестный режим ИИ')
 for provider in modes[mode]:
  try:
   if provider=='Cloud':
    if not config.get('consent'):continue
    return cloud(prompt,config.get('cloud_url',''),config.get('cloud_model',''),config.get('api_key',''),True,current=current),provider
   return ollama(prompt,config.get('ollama_url','http://localhost:11434'),config.get('ollama_model',''),current=current),provider
  except (ValueError,requests.RequestException,PermissionError,KeyError,TypeError) as exc:
   errors.append(f'{provider}: {exc}')
 if mode!='Offline' and not config.get('fallback',True):raise ValueError('; '.join(errors) or 'ИИ недоступен')
 try:return parse_offline(prompt,current),'Offline'+(' (резерв)' if mode!='Offline' else '')
 except ValueError as exc:raise ValueError(str(exc)+(' | '+ '; '.join(errors) if errors else '')) from exc
