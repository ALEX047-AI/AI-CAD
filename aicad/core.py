"""Проверяемая и воспроизводимая CAD-модель. Ответы ИИ и файлы проекта не выполняются как программный код."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json, math, os, re, tempfile
from pathlib import Path
import cadquery as cq

KINDS = {'plate','bracket','enclosure','box','cylinder','sphere'}
FIELDS = {
 'plate': ('length','width','thickness','hole_diameter','hole_count','edge_offset'),
 'bracket': ('horizontal_length','vertical_height','width','thickness'),
 'enclosure': ('length','width','height','wall_thickness','floor_thickness'),
 'box': ('length','width','height'),
 'cylinder': ('diameter','height'),
 'sphere': ('diameter',),
}
DEFAULTS = {
 'plate': dict(length=100,width=60,thickness=5,hole_diameter=0,hole_count=0,edge_offset=10),
 'bracket': dict(horizontal_length=80,vertical_height=50,width=30,thickness=5),
 'enclosure': dict(length=120,width=80,height=40,wall_thickness=3,floor_thickness=3),
 'box': dict(length=50,width=40,height=30),
 'cylinder': dict(diameter=20,height=40),
 'sphere': dict(diameter=30),
}

@dataclass
class PartSpec:
 kind: str
 parameters: dict
 units: str = 'mm'

 def validate(self):
  if self.kind not in KINDS or self.units != 'mm': raise ValueError('Неизвестный тип детали или единицы измерения')
  if not isinstance(self.parameters,dict) or set(self.parameters)!=set(FIELDS[self.kind]): raise ValueError('Неполные или неизвестные параметры')
  p=self.parameters
  for k,v in p.items():
   if not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v): raise ValueError(f'Недопустимое число: {k}')
   if k=='hole_count':
    if v not in (0,4): raise ValueError('Поддерживается 0 или 4 отверстия')
   elif k=='hole_diameter':
    if not 0<=v<=1000: raise ValueError('Недопустимый диаметр отверстий')
   elif not 0<v<=1000: raise ValueError(f'{k}: допустимый диапазон (0, 1000] мм')
  if self.kind=='plate':
   if p['hole_count']:
    d=p['hole_diameter']; o=p['edge_offset']
    if d<=0 or o<=d/2 or 2*o>=min(p['length'],p['width']): raise ValueError('Отверстия не помещаются или касаются края')
    if p['length']-2*o<=d or p['width']-2*o<=d: raise ValueError('Отверстия пересекаются')
  elif self.kind=='bracket':
   if p['thickness']>=min(p['horizontal_length'],p['vertical_height']): raise ValueError('Толщина кронштейна слишком велика')
  elif self.kind=='enclosure':
   if 2*p['wall_thickness']>=min(p['length'],p['width']) or p['floor_thickness']>=p['height']:
    raise ValueError('Стенки или дно корпуса не помещаются')
  return self

 def to_dict(self): return {'schema_version':1,'kind':self.kind,'units':self.units,'parameters':dict(self.parameters)}


def new_spec(kind, **changes):
 if kind not in KINDS: raise ValueError('Неизвестный тип детали')
 p=dict(DEFAULTS[kind]); p.update(changes)
 return PartSpec(kind,p).validate()


def from_dict(data):
 if not isinstance(data,dict) or data.get('schema_version')!=1 or set(data)-{'schema_version','kind','units','parameters'}:
  raise ValueError('Неизвестный формат проекта')
 return PartSpec(data['kind'],data['parameters'],data.get('units','mm')).validate()


def build(spec):
 spec.validate(); p=spec.parameters
 if spec.kind=='plate':
  obj=cq.Workplane('XY').box(p['length'],p['width'],p['thickness'],centered=(True,True,False))
  if p['hole_count']:
   x=p['length']/2-p['edge_offset']; y=p['width']/2-p['edge_offset']
   pts=[(-x,-y),(-x,y),(x,-y),(x,y)]
   obj=obj.faces('>Z').workplane().pushPoints(pts).hole(p['hole_diameter'])
 elif spec.kind=='bracket':
  # Ось X направлена горизонтально, Y задаёт ширину, Z — высоту. Обе части пересекаются и объединяются.
  foot=cq.Workplane('XY').box(p['horizontal_length'],p['width'],p['thickness'],centered=(False,True,False))
  upright=cq.Workplane('XY').box(p['thickness'],p['width'],p['vertical_height'],centered=(False,True,False))
  obj=foot.union(upright)
 elif spec.kind=='box':
  obj=cq.Workplane('XY').box(p['length'],p['width'],p['height'],centered=(True,True,False))
 elif spec.kind=='cylinder':
  obj=cq.Workplane('XY').circle(p['diameter']/2).extrude(p['height'])
 elif spec.kind=='sphere':
  obj=cq.Workplane('XY').sphere(p['diameter']/2)
 else:
  shell=cq.Workplane('XY').box(p['length'],p['width'],p['height'],centered=(True,True,False))
  cavity=cq.Workplane('XY').box(p['length']-2*p['wall_thickness'],p['width']-2*p['wall_thickness'],p['height']-p['floor_thickness']+1,centered=(True,True,False)).translate((0,0,p['floor_thickness']))
  obj=shell.cut(cavity)
 solid=obj.val()
 if not solid.isValid() or solid.Volume()<=0 or len(solid.Solids())!=1: raise ValueError('CAD-геометрия некорректна')
 return solid


def save_project(path,spec):
 spec.validate(); path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.aicad-',suffix='.tmp',dir=str(path.parent))
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(spec.to_dict(),f,ensure_ascii=False,indent=2)
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp): os.unlink(tmp)


def load_project(path):
 path=Path(path)
 if path.stat().st_size>65536: raise ValueError('Файл проекта слишком большой')
 return from_dict(json.loads(path.read_text(encoding='utf-8')))


def export_model(solid,path):
 path=Path(path); ext=path.suffix.lower()
 if ext not in ('.step','.stp','.stl'): raise ValueError('Поддерживаются STEP и STL')
 cq.exporters.export(solid,str(path),exportType='STL' if ext=='.stl' else 'STEP')
 if not path.exists() or path.stat().st_size<100: raise RuntimeError('Не удалось создать файл CAD')
 return path

_NUM=r'(\d+(?:[.,]\d+)?)'
def _num(x): return float(x.replace(',','.'))
def _find_named(text,names):
 for name in names:
  m=re.search(r'\b'+name+r'\s*(?:=|:|на|в)?\s*'+_NUM,text,re.I)
  if m:return _num(m.group(1))
 return None

def parse_offline(text,current=None):
 t=text.lower().replace('х','×').replace('x','×').replace('*','×')
 if len(t)>2000: raise ValueError('Слишком длинный запрос')
 if re.search(r'\b(измени|поменяй|установи|увеличь)\b',t):
  if current is None: raise ValueError('Сначала создайте деталь')
  mappings={'толщину':'thickness','толщина':'thickness','длину':'length','ширину':'width','высоту':'height','стенки':'wall_thickness','дно':'floor_thickness'}
  for word,key in mappings.items():
   m=re.search(word+r'\s*(?:на|до|=)?\s*'+_NUM,t)
   if m:
    if key not in current.parameters: raise ValueError('Параметр не подходит для этой детали')
    p=dict(current.parameters);p[key]=_num(m.group(1));return PartSpec(current.kind,p).validate()
  raise ValueError('Не удалось распознать изменение параметра')
 if 'пластин' in t: kind='plate'
 elif 'цилиндр' in t: kind='cylinder'
 elif 'сфер' in t: kind='sphere'
 elif 'параллелепипед' in t or 'брусок' in t: kind='box'
 elif 'кронштейн' in t: kind='bracket'
 elif 'корпус' in t: kind='enclosure'
 else: raise ValueError('Поддерживаются запросы: пластина, кронштейн, корпус')
 p=dict(DEFAULTS[kind]);m=re.search(_NUM+r'\s*×\s*'+_NUM+r'\s*×\s*'+_NUM,t)
 if kind=='plate':
  if m:p.update(zip(('length','width','thickness'),map(_num,m.groups())))
  else: raise ValueError('Укажите размеры пластины Д×Ш×Т, например 100×60×5 мм')
  if 'отверст' in t:
   if not re.search(r'четыр|4\s*отверст',t):raise ValueError('Пока поддерживаются только четыре отверстия')
   d=re.search(r'диаметр\w*\s*(?:=|:)?\s*'+_NUM,t)
   if not d:raise ValueError('Укажите диаметр отверстий')
   p['hole_count']=4;p['hole_diameter']=_num(d.group(1))
   # Явное начальное значение для демонстрации; его можно изменить позднее.
   p['edge_offset']=10
 elif kind=='cylinder':
  d=_find_named(t,['диаметром','диаметр']);h=_find_named(t,['высотой','высота'])
  if d is None or h is None: raise ValueError('Укажите диаметр и высоту цилиндра')
  p.update(diameter=d,height=h)
 elif kind=='sphere':
  d=_find_named(t,['диаметром','диаметр'])
  if d is None: raise ValueError('Укажите диаметр сферы')
  p['diameter']=d
 elif kind=='box':
  if not m: raise ValueError('Укажите размеры параллелепипеда Д×Ш×В')
  p.update(zip(('length','width','height'),map(_num,m.groups())))
 elif kind=='bracket':
  for key,names in [('horizontal_length',['длиной','длина']),('vertical_height',['высотой','высота']),('width',['шириной','ширина']),('thickness',['толщиной','толщина'])]:
   v=_find_named(t,names)
   if v is None: raise ValueError('Для кронштейна укажите длину, высоту, ширину и толщину')
   p[key]=v
 else:
  if not m:raise ValueError('Укажите размеры корпуса Д×Ш×В')
  p.update(zip(('length','width','height'),map(_num,m.groups())))
  for key,pattern in [('wall_thickness','стенк\\w*'),('floor_thickness','дн\\w*')]:
   found=re.search(pattern+r'\s*(?:=|:)?\s*'+_NUM,t)
   if found:p[key]=_num(found.group(1))
 return PartSpec(kind,p).validate()
