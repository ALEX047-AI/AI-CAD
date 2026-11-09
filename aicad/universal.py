"""Проверяемый граф CAD-операций с возможностью повторного построения. Содержимое проекта не выполняется как код."""
from __future__ import annotations
import ast
from copy import deepcopy
from dataclasses import dataclass, field
import json, math, os, tempfile, uuid
from pathlib import Path
import cadquery as cq
from .core import from_dict as old_spec_from_dict, build as build_legacy
from .importing import encode_step, decode_brep

MAX_NODES = 200
MAX_COORD = 10000
KINDS = {'sketch','extrude','revolve','loft','sweep','box','cylinder','sphere','legacy_part',
         'union','cut','intersect','transform','hole','linear_pattern','polar_pattern','mirror','shell','fillet','chamfer','edge_fillet','edge_chamfer','face_shell','face_hole','component','assembly','import_brep'}
SOLID_KINDS = KINDS-{'sketch'}


def _number(value, parameters, resolving=frozenset()):
    if isinstance(value, bool): raise ValueError('Логическое значение вместо размера')
    if isinstance(value, (int,float)): answer=float(value)
    elif isinstance(value,str):
        if len(value)>120: raise ValueError('Слишком длинное выражение')
        try: tree=ast.parse(value,mode='eval')
        except SyntaxError as exc: raise ValueError('Неверное выражение параметра') from exc
        def walk(node):
            if isinstance(node,ast.Expression):return walk(node.body)
            if isinstance(node,ast.Constant) and type(node.value) in (int,float):return float(node.value)
            if isinstance(node,ast.Name) and node.id in parameters:
                if node.id in resolving:raise ValueError('Циклическая зависимость параметров')
                return _number(parameters[node.id],parameters,resolving|{node.id})
            if isinstance(node,ast.BinOp) and type(node.op) in (ast.Add,ast.Sub,ast.Mult,ast.Div):
                a,b=walk(node.left),walk(node.right)
                return {ast.Add:lambda:a+b,ast.Sub:lambda:a-b,ast.Mult:lambda:a*b,ast.Div:lambda:a/b}[type(node.op)]()
            if isinstance(node,ast.UnaryOp) and type(node.op) in (ast.UAdd,ast.USub):
                return walk(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
            raise ValueError('Недопустимое выражение параметра')
        try:answer=walk(tree)
        except ZeroDivisionError as exc:raise ValueError('Деление на ноль') from exc
    else:raise ValueError('Ожидается числовой параметр')
    if not math.isfinite(answer) or abs(answer)>MAX_COORD:raise ValueError('Размер вне допустимого диапазона')
    return answer


def _vec(value,parameters,length=3):
    if not isinstance(value,(list,tuple)) or len(value)!=length:raise ValueError(f'Ожидается вектор из {length} чисел')
    return tuple(_number(v,parameters) for v in value)


def _positive(value,parameters):
    n=_number(value,parameters)
    if n<=0:raise ValueError('Размер должен быть положительным')
    return n


def _shape(value):
    if not isinstance(value,cq.Shape) or not value.isValid() or not value.Solids() or value.Volume()<=0:
        raise ValueError('Операция создала некорректное тело')
    return value.Solids()[0] if len(value.Solids())==1 else value


def _work(shape):return cq.Workplane('XY').newObject([shape])


@dataclass
class Feature:
    id: str
    kind: str
    name: str
    params: dict
    refs: list[str] = field(default_factory=list)
    visible: bool = True
    source: str = 'manual'

    def validate(self):
        if not isinstance(self.id,str) or not self.id or len(self.id)>64:raise ValueError('Некорректный ID')
        if self.kind not in KINDS:raise ValueError('Неизвестная CAD-операция')
        if not isinstance(self.name,str) or len(self.name)>120:raise ValueError('Некорректное имя')
        if not isinstance(self.params,dict) or len(self.params)>30:raise ValueError('Некорректные параметры')
        if not isinstance(self.refs,list) or len(self.refs)>8 or any(not isinstance(r,str) for r in self.refs):raise ValueError('Некорректные ссылки')
        if type(self.visible) is not bool or self.source not in ('manual','ai','import'):raise ValueError('Некорректные метаданные')
        return self

    def to_dict(self):return dict(id=self.id,kind=self.kind,name=self.name,params=deepcopy(self.params),refs=list(self.refs),visible=self.visible,source=self.source)

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict) or set(data)!={'id','kind','name','params','refs','visible','source'}:raise ValueError('Некорректный узел')
        return cls(**data).validate()


def _sketch_wires(feature,parameters):
    p=feature.params
    if set(p)-{'plane','origin','entities','constraints'}:raise ValueError('Неизвестный параметр эскиза')
    plane=p.get('plane','XY')
    origin=_vec(p.get('origin',[0,0,0]),parameters)
    if isinstance(plane,dict):
        if set(plane)!={'normal','x_dir'}:raise ValueError('Плоскость эскиза: normal и x_dir')
        normal=cq.Vector(*_vec(plane['normal'],parameters));x_dir=cq.Vector(*_vec(plane['x_dir'],parameters))
        if normal.Length<1e-9 or x_dir.Length<1e-9 or abs(normal.normalized().dot(x_dir.normalized()))>1e-7:
            raise ValueError('Нормаль и ось X плоскости должны быть ненулевыми и перпендикулярными')
        plane=cq.Plane(origin=origin,xDir=x_dir,normal=normal)
    elif plane not in ('XY','XZ','YZ'):raise ValueError('Плоскость: XY, XZ, YZ или normal/x_dir')
    wp=cq.Workplane(plane,origin=origin)
    entities=p.get('entities',[])
    if not isinstance(entities,list) or len(entities)>100:raise ValueError('Слишком много элементов эскиза')
    wires=[];paths=[];open_count=0
    for ent in entities:
        if not isinstance(ent,dict):raise ValueError('Некорректный элемент эскиза')
        kind=ent.get('type')
        if kind=='rectangle' and set(ent)=={'type','center','width','height'}:
            x,y=_vec(ent['center'],parameters,2);w=_positive(ent['width'],parameters);h=_positive(ent['height'],parameters)
            wire=wp.center(x,y).rect(w,h).val()
        elif kind=='circle' and set(ent)=={'type','center','radius'}:
            x,y=_vec(ent['center'],parameters,2);r=_positive(ent['radius'],parameters)
            wire=wp.center(x,y).circle(r).val()
        elif kind=='polygon' and set(ent)=={'type','points'}:
            pts=ent['points']
            if not isinstance(pts,list) or not 3<=len(pts)<=100:raise ValueError('Полигон: 3–100 точек')
            xy=[_vec(v,parameters,2) for v in pts]
            if len(set(xy))!=len(xy):raise ValueError('Повтор точки в полигоне')
            wire=wp.polyline(xy).close().val()
        elif kind=='profile' and set(ent)=={'type','start','segments','closed'}:
            start=_vec(ent['start'],parameters,2);segments=ent['segments'];closed=ent['closed']
            if type(closed) is not bool or not isinstance(segments,list) or not 1<=len(segments)<=100:raise ValueError('Некорректный составной профиль')
            current=start;builder=wp.moveTo(*start)
            for seg in segments:
                if not isinstance(seg,dict):raise ValueError('Некорректный сегмент профиля')
                if seg.get('type')=='line' and set(seg)=={'type','to'}:
                    end=_vec(seg['to'],parameters,2)
                    if end==current:raise ValueError('Сегмент нулевой длины')
                    builder=builder.lineTo(*end)
                elif seg.get('type')=='arc' and set(seg)=={'type','mid','to'}:
                    mid=_vec(seg['mid'],parameters,2);end=_vec(seg['to'],parameters,2)
                    if len({current,mid,end})<3:raise ValueError('Вырожденная дуга')
                    builder=builder.threePointArc(mid,end)
                else:raise ValueError('Неизвестный сегмент профиля')
                current=end
            if closed:wire=builder.close().val()
            else:paths.append(builder.val());open_count+=1;continue
        elif kind=='line' and set(ent)=={'type','start','end'}:
            start,end=_vec(ent['start'],parameters,2),_vec(ent['end'],parameters,2)
            if start==end:raise ValueError('Линия нулевой длины')
            paths.append(wp.moveTo(*start).lineTo(*end).val());open_count+=1;continue
        elif kind=='path' and set(ent)=={'type','points'}:
            pts=ent['points']
            if not isinstance(pts,list) or not 2<=len(pts)<=100:raise ValueError('Траектория: 2–100 точек')
            xy=[_vec(v,parameters,2) for v in pts]
            if any(a==b for a,b in zip(xy,xy[1:])):raise ValueError('Повтор точки траектории')
            paths.append(wp.polyline(xy).val());open_count+=1;continue
        else:raise ValueError('Неизвестный элемент эскиза или его параметры')
        if not wire.isValid():raise ValueError('Некорректный контур')
        wires.append(wire)
    constraints=p.get('constraints',[])
    if not isinstance(constraints,list) or len(constraints)>100:raise ValueError('Некорректные ограничения')
    for constraint in constraints:
        if not isinstance(constraint,dict):raise ValueError('Некорректное ограничение')
        typ=constraint.get('type');index=constraint.get('entity')
        if type(index) is not int or not 0<=index<len(entities):raise ValueError('Ограничение ссылается на неизвестный элемент')
        ent=entities[index]
        if typ in ('horizontal','vertical','length') and ent.get('type')=='line':
            a=_vec(ent['start'],parameters,2);b=_vec(ent['end'],parameters,2)
            if typ=='horizontal' and (set(constraint)!={'type','entity'} or abs(a[1]-b[1])>1e-7):raise ValueError('Линия не горизонтальна')
            if typ=='vertical' and (set(constraint)!={'type','entity'} or abs(a[0]-b[0])>1e-7):raise ValueError('Линия не вертикальна')
            if typ=='length' and (set(constraint)!={'type','entity','value'} or abs(math.dist(a,b)-_positive(constraint['value'],parameters))>1e-7):raise ValueError('Длина линии не соответствует размеру')
        else:raise ValueError('Неподдерживаемое ограничение эскиза')
    return wires,open_count,plane,origin,paths


def evaluate(feature, values, parameters):
    p=feature.params; kind=feature.kind
    def exact(*keys):
        if set(p)!=set(keys):raise ValueError(f'{kind}: требуются параметры {keys}')
    def refs(n):
        if len(feature.refs)!=n:raise ValueError(f'{kind}: требуется {n} ссылок')
        return [values[r] for r in feature.refs]
    if kind=='sketch':return _sketch_wires(feature,parameters)
    if kind=='legacy_part':
        exact('spec');refs(0);return _shape(build_legacy(old_spec_from_dict(p['spec'])))
    if kind=='import_brep':
        exact('data');refs(0);return _shape(decode_brep(p['data']))
    if kind=='box':
        exact('length','width','height');refs(0)
        return _shape(cq.Workplane('XY').box(*(_positive(p[k],parameters) for k in ('length','width','height')),centered=(True,True,False)).val())
    if kind=='cylinder':
        exact('radius','height');refs(0)
        return _shape(cq.Workplane('XY').circle(_positive(p['radius'],parameters)).extrude(_positive(p['height'],parameters)).val())
    if kind=='sphere':
        exact('radius');refs(0);return _shape(cq.Workplane('XY').sphere(_positive(p['radius'],parameters)).val())
    if kind=='loft':
        exact('ruled')
        if not 2<=len(feature.refs)<=8:raise ValueError('Loft: нужны 2–8 эскизов')
        if type(p['ruled']) is not bool:raise ValueError('ruled должен быть логическим')
        work=cq.Workplane('XY')
        for sketch in refs(len(feature.refs)):
            wires,open_count,_,_,_=sketch
            if len(wires)!=1 or open_count:raise ValueError('Loft: каждый эскиз должен содержать один замкнутый контур')
            work=work.add(wires[0])
        return _shape(work.toPending().loft(ruled=p['ruled'],combine=False).val())
    if kind=='sweep':
        exact('is_frenet')
        if type(p['is_frenet']) is not bool:raise ValueError('is_frenet должен быть логическим')
        profile,path=refs(2)
        pw,pc,plane,origin,_=profile;_,_,_,_,paths=path
        if len(pw)!=1 or pc or len(paths)!=1:raise ValueError('Sweep: один замкнутый профиль и одна открытая траектория')
        return _shape(cq.Workplane(plane,origin=origin).add(pw[0]).toPending().sweep(paths[0],isFrenet=p['is_frenet'],combine=False).val())
    if kind in ('extrude','revolve'):
        refs(1);wires,open_count,plane,origin,_=values[feature.refs[0]]
        if not wires or open_count:raise ValueError('Для объёмной операции нужен замкнутый эскиз')
        wp=cq.Workplane(plane,origin=origin)
        for wire in wires:wp=wp.add(wire)
        wp=wp.toPending()
        if kind=='extrude':
            exact('distance');result=wp.extrude(_number(p['distance'],parameters))
        else:
            exact('angle','axis_start','axis_end')
            result=wp.revolve(_number(p['angle'],parameters),_vec(p['axis_start'],parameters),_vec(p['axis_end'],parameters))
        return _shape(result.val())
    if kind in ('union','cut','intersect'):
        a,b=refs(2);exact()
        return _shape({'union':lambda:a.fuse(b),'cut':lambda:a.cut(b),'intersect':lambda:a.intersect(b)}[kind]())
    if kind=='transform':
        a,=refs(1);exact('translation','rotation')
        result=a
        for axis,angle in zip(((1,0,0),(0,1,0),(0,0,1)),_vec(p['rotation'],parameters)):
            if angle:result=result.rotate((0,0,0),axis,angle)
        return _shape(result.translate(_vec(p['translation'],parameters)))
    if kind=='hole':
        a,=refs(1);exact('center','radius','depth','axis')
        center=_vec(p['center'],parameters);radius=_positive(p['radius'],parameters);depth=_positive(p['depth'],parameters)
        axis=p['axis']
        if isinstance(axis,str):
            if axis not in ('X','Y','Z'):raise ValueError('Ось отверстия: X, Y, Z или вектор')
            direction={'X':(1,0,0),'Y':(0,1,0),'Z':(0,0,1)}[axis]
        else:direction=_vec(axis,parameters)
        if cq.Vector(*direction).Length<1e-9:raise ValueError('Нулевой вектор оси отверстия')
        cutter=cq.Solid.makeCylinder(radius,depth,cq.Vector(*center),cq.Vector(*direction))
        return _shape(a.cut(cutter))
    if kind=='linear_pattern':
        a,=refs(1);exact('count','step')
        count=_number(p['count'],parameters)
        if int(count)!=count or not 2<=count<=20:raise ValueError('Массив: 2–20 копий')
        step=_vec(p['step'],parameters)
        if step==(0,0,0):raise ValueError('Шаг массива равен нулю')
        return _shape(cq.Compound.makeCompound([a.translate(tuple(i*x for x in step)) for i in range(int(count))]))
    if kind=='polar_pattern':
        a,=refs(1);exact('count','angle','center','axis')
        count=_number(p['count'],parameters);angle=_number(p['angle'],parameters)
        if int(count)!=count or not 2<=count<=20:raise ValueError('Круговой массив: 2–20 копий')
        center=_vec(p['center'],parameters);axis=p['axis']
        if axis not in ('X','Y','Z'):raise ValueError('Ось массива: X, Y или Z')
        direction={'X':(1,0,0),'Y':(0,1,0),'Z':(0,0,1)}[axis]
        end=tuple(x+y for x,y in zip(center,direction))
        return _shape(cq.Compound.makeCompound([a.rotate(center,end,i*angle) for i in range(int(count))]))
    if kind=='mirror':
        a,=refs(1);exact('plane','origin')
        if p['plane'] not in ('XY','XZ','YZ'):raise ValueError('Плоскость зеркала: XY, XZ или YZ')
        return _shape(a.mirror(p['plane'],_vec(p['origin'],parameters)))
    if kind=='shell':
        a,=refs(1);exact('thickness','face')
        if p['face'] not in ('>X','<X','>Y','<Y','>Z','<Z'):raise ValueError('Неподдерживаемая открытая грань')
        return _shape(_work(a).faces(p['face']).shell(-_positive(p['thickness'],parameters)).val())
    if kind=='component':
        a,=refs(1);exact('translation','rotation')
        result=a
        for axis,angle in zip(((1,0,0),(0,1,0),(0,0,1)),_vec(p['rotation'],parameters)):
            if angle:result=result.rotate((0,0,0),axis,angle)
        return _shape(result.translate(_vec(p['translation'],parameters)))
    if kind=='assembly':
        exact()
        if not 2<=len(feature.refs)<=8:raise ValueError('Сборка: нужны 2–8 компонентов')
        return _shape(cq.Compound.makeCompound(refs(len(feature.refs))))
    if kind in ('edge_fillet','edge_chamfer'):
        a,=refs(1);exact('radius','edge_indices')
        radius=_positive(p['radius'],parameters);indices=p['edge_indices'];edges=a.Edges()
        if not isinstance(indices,list) or not 1<=len(indices)<=20 or len(set(indices))!=len(indices) or any(type(i) is not int or i<0 or i>=len(edges) for i in indices):raise ValueError('Неверные индексы рёбер')
        selected=_work(a).newObject([edges[i] for i in indices])
        return _shape((selected.fillet(radius) if kind=='edge_fillet' else selected.chamfer(radius)).val())
    if kind=='face_shell':
        a,=refs(1);exact('thickness','face_index')
        index=p['face_index'];faces=a.Faces()
        if type(index) is not int or not 0<=index<len(faces):raise ValueError('Неверный индекс грани')
        return _shape(_work(a).newObject([faces[index]]).shell(-_positive(p['thickness'],parameters)).val())
    if kind=='face_hole':
        a,=refs(1);exact('face_index','radius','depth','u','v')
        index=p['face_index'];faces=a.Faces()
        if type(index) is not int or not 0<=index<len(faces):raise ValueError('Неверный индекс грани')
        face=faces[index]
        if face.geomType()!='PLANE':raise ValueError('Отверстие по грани поддерживает плоские грани')
        normal=face.normalAt().normalized();reference=cq.Vector(0,0,1) if abs(normal.z)<0.9 else cq.Vector(1,0,0)
        u_axis=normal.cross(reference).normalized();v_axis=normal.cross(u_axis).normalized()
        center=face.Center()+u_axis*_number(p['u'],parameters)+v_axis*_number(p['v'],parameters)
        radius=_positive(p['radius'],parameters);depth=_positive(p['depth'],parameters)
        cutter=cq.Solid.makeCylinder(radius,depth+1,cq.Vector(center.x+normal.x*.5,center.y+normal.y*.5,center.z+normal.z*.5),-normal)
        result=a.cut(cutter)
        if a.Volume()-result.Volume()<1e-7:raise ValueError('Отверстие не пересекает тело')
        return _shape(result)
    if kind in ('fillet','chamfer'):
        a,=refs(1);exact('radius','selector')
        radius=_positive(p['radius'],parameters);selector=p['selector']
        if selector not in ('|X','|Y','|Z','>X','<X','>Y','<Y','>Z','<Z','%CIRCLE'):
            raise ValueError('Неподдерживаемый селектор рёбер')
        edges=_work(a).edges(selector)
        if not edges.size():raise ValueError('Рёбра не найдены')
        return _shape((edges.fillet(radius) if kind=='fillet' else edges.chamfer(radius)).val())
    raise ValueError('Неизвестная операция')


@dataclass
class Model:
    parameters: dict = field(default_factory=dict)
    features: list[Feature] = field(default_factory=list)
    _undo: list = field(default_factory=list,repr=False)
    _redo: list = field(default_factory=list,repr=False)

    def _snapshot(self):return deepcopy((self.parameters,self.features))
    def _edit(self,action):
        before=self._snapshot()
        try:
            action();self.rebuild()
        except Exception:
            self.parameters,self.features=before
            raise
        self._undo.append(before);self._redo.clear()

    def add(self,kind,params,refs=None,name=None,source='manual',visible=True):
        node=Feature(uuid.uuid4().hex,kind,name or kind,deepcopy(params),list(refs or []),visible,source).validate()
        self._edit(lambda:self.features.append(node))
        return node.id

    def import_step(self,path):
        name=Path(path).stem[:120]
        return self.add('import_brep',{'data':encode_step(path)},name=name,source='import')

    def update(self,node_id,*,params=None,refs=None,name=None,visible=None):
        index=self._index(node_id)
        def action():
            node=self.features[index]
            if params is not None:node.params=deepcopy(params)
            if refs is not None:node.refs=list(refs)
            if name is not None:node.name=name
            if visible is not None:node.visible=visible
            node.validate()
        self._edit(action)

    def remove(self,node_id):
        index=self._index(node_id)
        if any(node_id in f.refs for f in self.features[index+1:]):raise ValueError('Узел используется следующими операциями')
        self._edit(lambda:self.features.pop(index))

    def set_parameter(self,name,value):
        if not isinstance(name,str) or not name.isidentifier() or len(name)>64:raise ValueError('Некорректное имя параметра')
        def action():self.parameters[name]=value
        self._edit(action)

    def _index(self,node_id):
        for i,node in enumerate(self.features):
            if node.id==node_id:return i
        raise ValueError('Узел не найден')

    def undo(self):
        if not self._undo:return False
        current=self._snapshot();self.parameters,self.features=self._undo.pop();self._redo.append(current);return True

    def redo(self):
        if not self._redo:return False
        current=self._snapshot();self.parameters,self.features=self._redo.pop();self._undo.append(current);return True

    def rebuild(self):
        if len(self.features)>MAX_NODES or len(self.parameters)>100:raise ValueError('Превышен лимит модели')
        for name,value in self.parameters.items():
            if not isinstance(name,str) or not name.isidentifier():raise ValueError('Некорректное имя параметра')
            _number(value,self.parameters,frozenset({name}))
        values={}
        for node in self.features:
            node.validate()
            if node.id in values:raise ValueError('Повтор ID операции')
            if any(ref not in values for ref in node.refs):raise ValueError('Ссылка должна указывать на предыдущую операцию')
            values[node.id]=evaluate(node,values,self.parameters)
        return values

    def visible_solids(self):
        values=self.rebuild()
        # Промежуточные результаты, использованные последующими операциями, скрываются во избежание дублирования геометрии.
        consumed={r for f in self.features if f.visible for r in f.refs}
        return [(f,values[f.id]) for f in self.features if f.kind in SOLID_KINDS and f.visible and f.id not in consumed]

    def solid(self):
        solids=[s for _,s in self.visible_solids()]
        if not solids:raise ValueError('Нет видимых тел для экспорта')
        return cq.Compound.makeCompound(solids)

    def to_dict(self):
        self.rebuild()
        return dict(schema_version=3,units='mm',parameters=deepcopy(self.parameters),features=[f.to_dict() for f in self.features])

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict):raise ValueError('Некорректный проект')
        version=data.get('schema_version')
        if version in (1,2):
            from .project import Project
            old=Project.from_dict(data);model=cls()
            for item in old.items:
                ref=model.add('legacy_part',{'spec':item.spec.to_dict()},name=item.name,source='import')
                if item.position!=(0,0,0) or item.rotation!=(0,0,0):
                    model.add('transform',{'translation':list(item.position),'rotation':list(item.rotation)},[ref],name=item.name+' transform',source='import')
            model._undo.clear();return model
        if set(data)!={'schema_version','units','parameters','features'} or version!=3 or data['units']!='mm':raise ValueError('Неизвестная версия проекта')
        if not isinstance(data['features'],list) or not isinstance(data['parameters'],dict):raise ValueError('Некорректный проект')
        model=cls(deepcopy(data['parameters']),[Feature.from_dict(x) for x in data['features']]);model.rebuild();return model


def save_model(path,model):
    payload=json.dumps(model.to_dict(),ensure_ascii=False,indent=2)
    if len(payload)>1000000:raise ValueError('Проект слишком велик')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.aicad-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as out:out.write(payload)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def load_model(path):
    path=Path(path)
    if path.stat().st_size>1000000:raise ValueError('Проект слишком велик')
    return Model.from_dict(json.loads(path.read_text(encoding='utf8')))
