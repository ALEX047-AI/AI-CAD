"""Повторное создание переносимых демонстрационных моделей только средствами универсальных CAD-операций."""
from pathlib import Path
import cadquery as cq
from aicad.universal import Model,save_model,load_model
from aicad.core import export_model
from aicad.drawing import export_universal_pdf
from aicad.inspection import component_interferences


def assembly():
    m=Model();m.set_parameter('plate_length',100);m.set_parameter('bolt_offset',36)
    plate=m.add('box',{'length':'plate_length','width':60,'height':8},name='Плита')
    for x,y in [(-36,-20),(36,-20),(-36,20),(36,20)]:
        plate=m.add('hole',{'center':[x,y,0],'radius':3,'depth':8,'axis':'Z'},[plate],name='Монтажное отверстие')
    shaft=m.add('cylinder',{'radius':9,'height':30},name='Вал')
    shaft=m.add('fillet',{'radius':1.5,'selector':'>Z'},[shaft],name='Скругление вала')
    base_part=m.add('component',{'translation':[0,0,0],'rotation':[0,0,0]},[plate],name='Плита · компонент')
    shaft_part=m.add('component',{'translation':[0,0,8],'rotation':[0,0,0]},[shaft],name='Вал · компонент')
    m.add('assembly',{},[base_part,shaft_part],name='Сборка крепления')
    return m


def oblique_loft():
    m=Model();m.set_parameter('base_width',65)
    bottom=m.add('sketch',{'plane':'XY','origin':[0,0,0],'entities':[{'type':'rectangle','center':[0,0],'width':'base_width','height':40}]},name='Основание')
    upper=m.add('sketch',{'plane':'XY','origin':[0,0,25],'entities':[{'type':'rectangle','center':[0,0],'width':35,'height':22}]},name='Верхний профиль')
    tapered=m.add('loft',{'ruled':False},[bottom,upper],name='Переход')
    oblique=m.add('sketch',{'plane':{'normal':[0,1,1],'x_dir':[1,0,0]},'origin':[20,0,8],
                    'entities':[{'type':'rectangle','center':[0,0],'width':25,'height':12}]},name='Наклонный эскиз')
    wing=m.add('extrude',{'distance':14},[oblique],name='Наклонное ребро')
    body=m.add('union',{},[tapered,wing],name='Единая деталь')
    m.add('hole',{'center':[0,0,0],'radius':3,'depth':25,'axis':[0,0,1]},[body],name='Осевая обработка')
    return m


def imported_edit(source):
    m=Model();base=m.import_step(source)
    m.add('transform',{'translation':[0,0,5],'rotation':[0,0,15]},[base],name='Положение импортированной детали')
    return m


def write(name,model,out):
    project=out/(name+'.aicad.json');save_model(project,model)
    loaded=load_model(project);shape=loaded.solid()
    if not shape.isValid() or shape.Volume()<=0:raise RuntimeError(name+' has invalid CAD geometry')
    for extension in ('step','stl'):export_model(shape,out/(name+'.'+extension))
    export_universal_pdf(loaded,out/(name+'.pdf'))
    imported=cq.importers.importStep(str(out/(name+'.step'))).val()
    if not imported.isValid() or abs(imported.Volume()-shape.Volume())>1e-3:raise RuntimeError(name+' STEP roundtrip failed')
    print(name,'features',len(model.features),'solids',len(shape.Solids()),'volume_mm3',round(shape.Volume(),3))


def main():
    out=Path(__file__).resolve().parents[1]/'demo_output'/'universal';out.mkdir(parents=True,exist_ok=True)
    first=assembly();write('H_component_assembly',first,out)
    print('H component interferences',component_interferences(first))
    write('I_oblique_loft',oblique_loft(),out)
    write('J_imported_step_edit',imported_edit(out/'I_oblique_loft.step'),out)


if __name__=='__main__':main()
