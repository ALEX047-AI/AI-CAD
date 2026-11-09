"""Структурированные планы ИИ для универсального графа CAD-операций."""
from __future__ import annotations
import json,os,re
try:
    import requests
except ImportError:
    requests=None
from .commands import execute
from .universal import Model
from .inspection import shape_report

SYSTEM='''You are an engineering CAD planner. Decompose the Russian request into real, editable feature-graph operations. You operate a parametric CAD feature graph. Return ONLY JSON:
{"commands":[{"action":"add","kind":"sketch|extrude|revolve|loft|sweep|box|cylinder|sphere|union|cut|intersect|transform|hole|linear_pattern|polar_pattern|mirror|shell|fillet|chamfer|edge_fillet|edge_chamfer|face_shell|face_hole|component|assembly","params":{},"refs":[],"alias":"optional"}, {"action":"update","id":"existing feature id","params":{}}, {"action":"set_parameter","name":"width","value":80}],"explanation":"Short Russian summary of construction and assumptions"}.
Sketch params: {"plane":"XY","origin":[0,0,0],"entities":[{"type":"rectangle","center":[0,0],"width":80,"height":40},{"type":"circle","center":[0,0],"radius":5},{"type":"polygon","points":[[0,0],[20,0],[10,10]]}]}.
For an oblique sketch, plane may be {"normal":[0,1,1],"x_dir":[1,0,0]} with perpendicular vectors, plus an origin. Hole axis may be X/Y/Z or a nonzero 3D vector.
Mixed line/arc profile entity: {"type":"profile","start":[0,0],"segments":[{"type":"line","to":[20,0]},{"type":"arc","mid":[25,10],"to":[20,20]},{"type":"line","to":[0,20]}],"closed":true}. Extrude: {"distance":5}, refs sketch. Revolve: {"angle":360,"axis_start":[0,0,0],"axis_end":[0,1,0]}, refs sketch. Loft: {"ruled":false}, refs 2–8 sketches with one closed contour each. Sweep: {"is_frenet":false}, refs profile sketch and path sketch. Boolean: params {}, refs two solids. Hole: {"center":[0,0,0],"radius":3,"depth":10,"axis":"Z"}, refs solid. Transform: {"translation":[0,0,0],"rotation":[0,0,0]}, refs solid. Linear pattern: {"count":4,"step":[20,0,0]}, refs solid. Polar pattern: {"count":4,"angle":90,"center":[0,0,0],"axis":"Z"}, refs solid. Mirror: {"plane":"YZ","origin":[0,0,0]}, refs solid. Shell: {"thickness":3,"face":">Z"}, refs solid. Fillet/chamfer: {"radius":2,"selector":"|Z"}, refs solid.
Edge fillet/chamfer: {"radius":2,"edge_indices":[0]}, refs solid. Face shell: {"thickness":3,"face_index":0}, refs solid. Face hole: {"face_index":0,"radius":3,"depth":10,"u":0,"v":0}, refs solid. Topology indices refer to the referenced solid's current evaluated edges/faces and may change when upstream geometry changes. Component: {"translation":[0,0,0],"rotation":[0,0,0]}, refs one solid. Assembly: params {}, refs 2–8 components. For edit commands, params must contain the complete new parameter object. References may use prior feature IDs or aliases created earlier in this response. Global parameter names may be used in numeric expressions and may reference other global parameters without cycles. On an edit, preserve existing feature IDs and update earlier parameters or add dependent features; do not replace the project with unrelated primitives. For enclosures, use box + shell or cut, then cylinders/transforms/unions and holes as needed. Explain only actions actually present in the plan. Return at most 30 commands. If critical dimensions or placement are missing, return {"error":"specific clarification question in Russian"}. Never return code or paths.'''


class ClarificationNeeded(ValueError):
    pass

def decode_plan(content):
    if not isinstance(content,str) or len(content)>30000:raise ValueError('Некорректный ответ ИИ')
    content=content.strip();content=re.sub(r'^```(?:json)?\s*|\s*```$','',content)
    data=json.loads(content)
    if not isinstance(data,dict) or set(data) not in ({'commands'},{'commands','explanation'},{'error'}):raise ValueError('ИИ вернул неверную схему')
    if 'error' in data:raise ClarificationNeeded(str(data['error'])[:300])
    explanation=data.get('explanation','')
    if not isinstance(explanation,str) or len(explanation)>1000:raise ValueError('Некорректное пояснение ИИ')
    return data['commands'],explanation


def decode(content):return decode_plan(content)[0]


def offline(text,model):
    """Ограниченная обработка естественного языка. Полный проверяемый протокол CAD-команд доступен локально через JSON."""
    text=text.strip()
    if len(text)>5000:raise ValueError('Слишком длинный запрос')
    if text.startswith('{'):return decode(text)
    if text.lower() in ('удали последнее изменение','отмени последнее изменение'):
        return 'undo'
    normalized=text.lower().replace('х','×')
    number=r'(\d+(?:[.,]\d+)?)'
    def n(value):return float(value.replace(',','.'))
    m=re.search(r'(?:создай|добавь)\s+эскиз\s+прямоугольник\s+'+number+r'\s*[×x]\s*'+number,normalized)
    if m:return [{'action':'add','kind':'sketch','params':{'plane':'XY','entities':[{'type':'rectangle','center':[0,0],'width':n(m.group(1)),'height':n(m.group(2))}]},'name':'Прямоугольный эскиз'}]
    m=re.search(r'выдави(?:\s+последний\s+эскиз)?\s+на\s*'+number,normalized)
    if m:
        sketch=next((f for f in reversed(model.features) if f.kind=='sketch'),None)
        if sketch is None:raise ValueError('Сначала создайте эскиз')
        return [{'action':'add','kind':'extrude','params':{'distance':n(m.group(1))},'refs':[sketch.id],'name':'Выдавливание'}]
    m=re.search(r'(?:добавь|просверли)\s+отверстие\s+диаметром\s*'+number+r'\s*мм?\s+глубиной\s*'+number+r'.*?x\s*=\s*'+number+r'\s*y\s*=\s*'+number+r'\s*z\s*=\s*'+number,normalized)
    if m:
        body=next((f for f in reversed(model.features) if f.kind not in ('sketch',)),None)
        if body is None:raise ValueError('Сначала создайте тело')
        d,depth,x,y,z=map(n,m.groups())
        return [{'action':'add','kind':'hole','params':{'center':[x,y,z],'radius':d/2,'depth':depth,'axis':'Z'},'refs':[body.id],'name':'Отверстие'}]
    m=re.search(r'(?:измени|установи)\s+параметр\s+([a-zA-Z_][a-zA-Z_0-9]*)\s*(?:на|=)\s*'+number,normalized)
    if m:
        if m.group(1) not in model.parameters:raise ValueError('Глобальный параметр не найден')
        return [{'action':'set_parameter','name':m.group(1),'value':n(m.group(2))}]
    from .core import parse_offline
    current=None
    last=next((f for f in reversed(model.features) if f.kind=='legacy_part'),None)
    if last:
        from .core import from_dict
        current=from_dict(last.params['spec'])
    spec=parse_offline(text,current)
    if re.match(r'(?i)^\s*(измени|увеличь|поменяй|установи)',text) and last:
        return [{'action':'update','id':last.id,'params':{'spec':spec.to_dict()}}]
    return [{'action':'add','kind':'legacy_part','params':{'spec':spec.to_dict()},'name':spec.kind}]


MISTRAL_URL='https://api.mistral.ai/v1'
MISTRAL_MODEL='mistral-large-latest'


def _credentials(provider,config):
    if provider=='Mistral':
        return (config.get('cloud_url') or MISTRAL_URL).rstrip('/'),config.get('cloud_model') or MISTRAL_MODEL,os.environ.get('MISTRAL_API_KEY','')
    return (config.get('cloud_url') or '').rstrip('/'),config.get('cloud_model') or '',config.get('api_key') or ''


def _http_error(response):
    status=getattr(response,'status_code',200)
    if status in (401,403):raise ValueError('Ошибка авторизации API: проверьте ключ и доступ к модели')
    if status==429:raise ValueError('Лимит API исчерпан; повторите позже')
    if status>=500:raise ValueError(f'Сервер API временно недоступен (HTTP {status})')
    if status>=400:raise ValueError(f'API отклонил запрос (HTTP {status})')
    response.raise_for_status()


def check_connection(provider,config):
    """Проверка доступности провайдера по запросу пользователя; текст запроса и проект не передаются."""
    if provider not in ('Mistral','Cloud','Ollama'):raise ValueError('Выберите сетевого провайдера')
    if requests is None:raise ValueError('Установите requests')
    try:
        if provider=='Ollama':
            base=config.get('ollama_url','http://localhost:11434').rstrip('/')
            if not re.fullmatch(r'http://(localhost|127\.0\.0\.1)(:\d+)?',base):raise ValueError('Ollama должна быть локальной')
            response=requests.get(base+'/api/tags',timeout=6);_http_error(response)
            models=[item.get('name','') for item in response.json().get('models',[])]
            selected=config.get('ollama_model','')
            return 'Ollama подключена; моделей: '+str(len(models))+('; '+selected+' найдена' if selected in models else '; выберите установленную модель')
        base,model,key=_credentials(provider,config)
        if not base.startswith('https://'):raise ValueError('Облачный URL должен использовать HTTPS')
        if not key:raise ValueError('API-ключ отсутствует в окружении или поле настроек')
        response=requests.get(base+'/models',headers={'Authorization':'Bearer '+key},timeout=8)
        _http_error(response)
        data=response.json();models=data.get('data',[]) if isinstance(data,dict) else []
        names={entry.get('id') for entry in models if isinstance(entry,dict)}
        if model and names and model not in names:return 'API подключён; заданная модель отсутствует в списке доступных'
        return 'API подключён; модель '+model
    except Exception as exc:
        key=_credentials(provider,config)[2] if provider!='Ollama' else ''
        raise ValueError(_safe_error(exc,key)) from None


def _safe_error(exc,key=''):
    if requests is not None and isinstance(exc,getattr(requests,'Timeout',())):
        message='Истекло время ожидания API'
    elif requests is not None and isinstance(exc,getattr(requests,'ConnectionError',())):
        message='Нет соединения с API'
    else:message=str(exc)[:500]
    return message.replace(key,'[СКРЫТО]') if key else message


def _chat(provider,messages,config):
    if requests is None:raise ValueError('Установите requests для сетевых провайдеров')
    if provider in ('Mistral','Cloud'):
        if not config.get('consent'):raise PermissionError('Отправка задания и структуры проекта в облако не разрешена')
        base,model,key=_credentials(provider,config)
        if not base.startswith('https://'):raise ValueError('Облачный URL должен использовать HTTPS')
        if not model or not key:raise ValueError('Укажите модель и API-ключ')
        payload={'model':model,'messages':messages,'temperature':0,'max_tokens':8192}
        if provider=='Mistral':payload['response_format']={'type':'json_object'}
        response=requests.post(base+'/chat/completions',headers={'Authorization':'Bearer '+key},json=payload,timeout=45)
        _http_error(response)
        return response.json()['choices'][0]['message']['content']
    base=config.get('ollama_url','http://localhost:11434').rstrip('/')
    if not re.fullmatch(r'http://(localhost|127\.0\.0\.1)(:\d+)?',base):raise ValueError('Ollama должна быть локальной')
    model=config.get('ollama_model','')
    if not model:raise ValueError('Укажите модель Ollama')
    response=requests.post(base+'/api/chat',json={'model':model,'stream':False,'format':'json','messages':messages},timeout=60)
    _http_error(response)
    return response.json()['message']['content']


def _validate_plan(commands,model,text):
    if not isinstance(commands,list):raise ValueError('Ответ должен содержать массив commands')
    existing={feature.id for feature in model.features}
    edit_intent=bool(existing and re.search(r'(?i)\b(измен|увелич|уменьш|перемест|скругл|передвин)',text))
    if edit_intent:
        connected=any(isinstance(cmd,dict) and (cmd.get('action')=='set_parameter' or cmd.get('id') in existing or any(ref in existing for ref in cmd.get('refs',[]) if isinstance(ref,str))) for cmd in commands)
        if not connected:raise ValueError('План редактирования не связан с текущими построениями')
    trial=Model.from_dict(model.to_dict())
    normalized=[]
    for cmd in commands:
        if not isinstance(cmd,dict):raise ValueError('Некорректная CAD-команда')
        cmd=dict(cmd)
        if cmd.get('action')=='add' and cmd.get('kind')=='import_brep':raise ValueError('ИИ не может создавать бинарные импортированные тела')
        if cmd.get('action')=='update' and any(f.id==cmd.get('id') and f.kind=='import_brep' for f in model.features) and 'params' in cmd:
            raise ValueError('ИИ не может менять бинарные данные импорта; используйте зависимую операцию')
        if cmd.get('action')=='add':cmd['source']='ai'
        normalized.append(cmd)
    execute(trial,normalized)
    return normalized


def request_commands(text,mode,model,config,progress=None):
    if mode not in ('Offline','Cloud','Mistral','Ollama','Auto'):raise ValueError('Неизвестный режим')
    if not isinstance(text,str) or not text.strip() or len(text)>5000:raise ValueError('Введите запрос длиной до 5000 символов')
    config=config or {};errors=[]
    providers={'Offline':[],'Mistral':['Mistral'],'Cloud':['Cloud'],'Ollama':['Ollama'],'Auto':['Mistral','Ollama']}[mode]
    for provider in providers:
        try:
            if progress:progress('Проверка плана через '+provider)
            graph=model.to_dict()
            if any(feature['kind']=='import_brep' for feature in graph['features']):
                values=model.rebuild()
                for feature in graph['features']:
                    if feature['kind']=='import_brep':
                        feature['params']={'embedded_geometry':'omitted','geometry':shape_report(values[feature['id']])}
            context=json.dumps(graph,ensure_ascii=False)
            try:metrics=shape_report(model.solid())
            except ValueError:metrics={}
            selected=config.get('selected_id')
            if selected not in {feature.id for feature in model.features}:selected=None
            topology=config.get('selected_topology') if selected else None
            extra=json.dumps({'metrics':metrics,'selected_feature_id':selected,'selected_topology':topology},ensure_ascii=False)
            messages=[{'role':'system','content':SYSTEM},{'role':'user','content':text+'\nCurrent CAD graph JSON (preserve IDs when editing): '+context+'\nInspection context: '+extra}]
            for attempt in range(2):
                content=_chat(provider,messages,config)
                try:
                    commands,explanation=decode_plan(content)
                    normalized=_validate_plan(commands,model,text)
                    if explanation and progress:progress('План: '+explanation)
                    return normalized,provider
                except ClarificationNeeded:raise
                except Exception as plan_error:
                    if attempt:raise ValueError('CAD-план отклонён после повторной попытки: '+str(plan_error)) from plan_error
                    if progress:progress('Исправление CAD-плана: '+str(plan_error)[:160])
                    messages.extend([{'role':'assistant','content':str(content)[:30000]},
                                     {'role':'user','content':'Этот план не удалось исполнить: '+str(plan_error)[:1000]+'. Верни полностью исправленный JSON commands для исходного задания. Сохрани существующие узлы и их ID.'}])
        except ClarificationNeeded:raise
        except Exception as exc:
            key=_credentials(provider,config)[2] if provider in ('Mistral','Cloud') else ''
            errors.append(provider+': '+_safe_error(exc,key))
    if mode!='Offline' and not config.get('fallback',True):raise ValueError('; '.join(errors) or 'Провайдер недоступен')
    try:
        if progress:progress('Локальный парсер')
        commands=offline(text,model)
        if commands!='undo':commands=_validate_plan(commands,model,text)
        return commands,'Offline' if mode=='Offline' else 'Offline (резерв)'
    except ValueError as exc:raise ValueError(str(exc)+(' | '+'; '.join(errors) if errors else '')) from exc
