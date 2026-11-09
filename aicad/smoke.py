"""Самопроверка собранного приложения с созданием выходных файлов и машиночитаемого отчёта."""
from __future__ import annotations
import json
from pathlib import Path
import cadquery as cq
from .universal import Model,save_model,load_model
from .core import export_model
from .drawing import export_universal_pdf
from .inspection import shape_report,pick_topology

def run(outdir):
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    model=Model();sketch=model.add('sketch',{'plane':'XY','entities':[{'type':'rectangle','center':[0,0],'width':80,'height':50}]})
    body=model.add('extrude',{'distance':8},[sketch]);model.add('hole',{'center':[20,0,0],'radius':3,'depth':8,'axis':'Z'},[body])
    save_model(out/'smoke.aicad.json',model);loaded=load_model(out/'smoke.aicad.json')
    solid=loaded.solid()
    step=export_model(solid,out/'smoke.step');stl=export_model(solid,out/'smoke.stl');pdf=export_universal_pdf(loaded,out/'smoke.pdf')
    imported=cq.importers.importStep(str(step)).val()
    if not imported.isValid() or abs(imported.Volume()-solid.Volume())>1e-3:raise RuntimeError('STEP roundtrip failed')
    for path in (step,stl,pdf):
        if path.stat().st_size<500:raise RuntimeError('Export too small: '+str(path))
    assembly=Model();plate=assembly.import_step(step)
    part=assembly.add('component',{'translation':[0,0,0],'rotation':[0,0,0]},[plate])
    second=assembly.add('component',{'translation':[100,0,0],'rotation':[0,0,0]},[plate])
    assembly.add('assembly',{},[part,second]);save_model(out/'assembly.aicad.json',assembly)
    if len(load_model(out/'assembly.aicad.json').solid().Solids())!=2:raise RuntimeError('Assembly import/reload failed')
    if pick_topology(solid,lambda p:(p[0],p[1],-p[2]),0,0,'face') is None:
        raise RuntimeError('Topology picking failed')
    # Проверка ресурсов и модулей Qt: скрытое окно просмотра должно построить сетку CAD-модели.
    from PySide6.QtWidgets import QApplication
    from .ui import Viewport
    app=QApplication.instance() or QApplication([])
    view=Viewport();view.resize(640,480);view.set_solid(solid)
    image=view.grab().toImage()
    if image.isNull() or image.width()<100:raise RuntimeError('Qt viewport render failed')
    image.save(str(out/'viewport.png'))
    from .universal_ui import UniversalWindow
    window=UniversalWindow();window.show();app.processEvents()
    if not window.isVisible() or window.centralWidget() is None:raise RuntimeError('Main GUI failed to open')
    gui_image=window.grab().toImage()
    if gui_image.isNull() or gui_image.width()<500:raise RuntimeError('Main GUI render failed')
    gui_image.save(str(out/'main_window.png'));window.close()
    report={'status':'ok','volume_mm3':solid.Volume(),'feature_count':len(model.features),'assembly_solids':2,'topology':shape_report(solid),'files':{p.name:p.stat().st_size for p in out.iterdir() if p.is_file()}}
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return report
