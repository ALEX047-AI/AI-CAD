"""Версионируемый проект с несколькими объектами. Ручные и ИИ-изменения используют общую историю команд."""
from __future__ import annotations
from dataclasses import dataclass, field
from copy import deepcopy
from pathlib import Path
import json, math, os, tempfile, uuid
import cadquery as cq
from .core import PartSpec, from_dict, build

@dataclass
class Item:
    id: str
    name: str
    spec: PartSpec
    position: tuple = (0.0, 0.0, 0.0)
    rotation: tuple = (0.0, 0.0, 0.0)

    def validate(self):
        self.spec.validate()
        if not isinstance(self.id, str) or len(self.id) > 64 or not self.id:
            raise ValueError('Некорректный ID объекта')
        if not isinstance(self.name, str) or len(self.name) > 100:
            raise ValueError('Некорректное имя')
        for values in (self.position, self.rotation):
            if len(values) != 3 or any(not isinstance(v, (float, int)) or not math.isfinite(v) or abs(v)>10000 for v in values):
                raise ValueError('Некорректное положение или ориентация')
        return self

    def solid(self):
        self.validate()
        solid = build(self.spec)
        for axis, angle in zip(((1,0,0),(0,1,0),(0,0,1)), self.rotation):
            if angle: solid = solid.rotate((0,0,0), axis, angle)
        return solid.translate(self.position)

    def to_dict(self):
        return dict(id=self.id,name=self.name,spec=self.spec.to_dict(),position=list(self.position),rotation=list(self.rotation))

    @classmethod
    def from_dict(cls, data):
        if set(data) != {'id','name','spec','position','rotation'}: raise ValueError('Некорректный объект проекта')
        return cls(data['id'],data['name'],from_dict(data['spec']),tuple(data['position']),tuple(data['rotation'])).validate()

@dataclass
class Project:
    items: list[Item] = field(default_factory=list)
    selected_id: str | None = None
    operations: list[dict] = field(default_factory=list)
    _undo: list = field(default_factory=list, repr=False)
    _redo: list = field(default_factory=list, repr=False)

    def _snapshot(self): return deepcopy((self.items,self.selected_id,self.operations))
    def _commit(self, op):
        self._undo.append(self._snapshot());self._redo.clear()
        try:
            op();self.validate()
        except Exception:
            self.items,self.selected_id,self.operations=self._undo.pop()
            raise

    def validate(self):
        if len(self.items)>50 or len(self.operations)>1000: raise ValueError('Превышен лимит проекта')
        ids=[item.validate().id for item in self.items]
        if len(ids)!=len(set(ids)):raise ValueError('Повторяющийся ID')
        if self.selected_id is not None and self.selected_id not in ids:raise ValueError('Выбранный объект отсутствует')
        return self

    def selected(self): return next((x for x in self.items if x.id==self.selected_id),None)
    def select(self, item_id):
        if item_id is not None and item_id not in {x.id for x in self.items}:raise ValueError('Объект не найден')
        self.selected_id=item_id

    def add(self,spec,name=None,source='Ручное'):
        spec.validate();build(spec)
        item=Item(uuid.uuid4().hex,name or f'{spec.kind} {len(self.items)+1}',deepcopy(spec))
        def action():
            self.items.append(item);self.selected_id=item.id
            self.operations.append(dict(action='add',id=item.id,source=source))
        self._commit(action);return item

    def update(self,item_id,spec=None,position=None,rotation=None,source='Ручное'):
        item=next((x for x in self.items if x.id==item_id),None)
        if item is None:raise ValueError('Объект не найден')
        candidate=deepcopy(item)
        if spec is not None:candidate.spec=deepcopy(spec)
        if position is not None:candidate.position=tuple(position)
        if rotation is not None:candidate.rotation=tuple(rotation)
        candidate.validate();candidate.solid()
        def action():
            index=self.items.index(item);self.items[index]=candidate
            self.operations.append(dict(action='update',id=item_id,source=source))
        self._commit(action)

    def remove(self,item_id):
        if item_id not in {x.id for x in self.items}:raise ValueError('Объект не найден')
        def action():
            self.items=[x for x in self.items if x.id!=item_id]
            self.selected_id=self.items[-1].id if self.items else None
            self.operations.append(dict(action='remove',id=item_id,source='Ручное'))
        self._commit(action)

    def undo(self):
        if not self._undo:return False
        self._redo.append(self._snapshot());self.items,self.selected_id,self.operations=self._undo.pop();return True

    def redo(self):
        if not self._redo:return False
        self._undo.append(self._snapshot());self.items,self.selected_id,self.operations=self._redo.pop();return True

    def combined_solid(self):
        if not self.items:raise ValueError('Проект пуст')
        solids=[item.solid() for item in self.items]
        return cq.Compound.makeCompound(solids)

    def to_dict(self):
        self.validate()
        return dict(schema_version=2,items=[x.to_dict() for x in self.items],selected_id=self.selected_id,operations=deepcopy(self.operations))

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict):raise ValueError('Некорректный формат проекта')
        if data.get('schema_version')==1:
            result=cls();result.add(from_dict(data),source='Импорт MVP 0.1');result._undo.clear();return result
        if set(data)!={'schema_version','items','selected_id','operations'} or data['schema_version']!=2:raise ValueError('Неизвестная версия проекта')
        if not isinstance(data['items'],list) or not isinstance(data['operations'],list):raise ValueError('Некорректный формат проекта')
        result=cls([Item.from_dict(x) for x in data['items']],data['selected_id'],data['operations'])
        return result.validate()

def save(path,project):
    path=Path(path);payload=json.dumps(project.to_dict(),ensure_ascii=False,indent=2)
    if len(payload)>1000000:raise ValueError('Проект слишком велик')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.aicad-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as stream:stream.write(payload)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def load(path):
    path=Path(path)
    if path.stat().st_size>1000000:raise ValueError('Проект слишком велик')
    return Project.from_dict(json.loads(path.read_text(encoding='utf8')))
