"""Универсальный редактор операций. Ручной интерфейс и ИИ используют общие механизмы модели и команд."""
from __future__ import annotations
import json
from copy import deepcopy
import cadquery as cq
from PySide6.QtCore import Qt,QThread,Signal
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
 QSplitter,QTreeWidget,QTreeWidgetItem,QPlainTextEdit,QPushButton,QComboBox,QLineEdit,QCheckBox,
 QLabel,QDialog,QListWidget,QListWidgetItem,QFileDialog,QMessageBox,QInputDialog,QAbstractItemView)
from .ui import Viewport
from .sketch_ui import SketchDialog
from .universal import Model,save_model,load_model,SOLID_KINDS
from .commands import execute
from .universal_ai import request_commands,check_connection
from .core import export_model
from .drawing import export_universal_pdf
from .inspection import element_report,shape_report,component_interferences

DEFAULT_PARAMS={
 'box':{'length':60,'width':40,'height':20},'cylinder':{'radius':10,'height':30},'sphere':{'radius':15},
 'extrude':{'distance':10},'revolve':{'angle':360,'axis_start':[0,0,0],'axis_end':[0,1,0]},
 'loft':{'ruled':False},'sweep':{'is_frenet':False},'union':{},'cut':{},'intersect':{},
 'transform':{'translation':[0,0,0],'rotation':[0,0,0]},
 'hole':{'center':[0,0,0],'radius':3,'depth':10,'axis':'Z'},
 'linear_pattern':{'count':3,'step':[20,0,0]},
 'polar_pattern':{'count':4,'angle':90,'center':[0,0,0],'axis':'Z'},
 'mirror':{'plane':'YZ','origin':[0,0,0]},'shell':{'thickness':3,'face':'>Z'},
 'fillet':{'radius':2,'selector':'|Z'},'chamfer':{'radius':2,'selector':'|Z'},
 'edge_fillet':{'radius':2,'edge_indices':[0]},'edge_chamfer':{'radius':2,'edge_indices':[0]},
 'face_shell':{'thickness':3,'face_index':0},'face_hole':{'face_index':0,'radius':3,'depth':10,'u':0,'v':0},
 'component':{'translation':[0,0,0],'rotation':[0,0,0]},'assembly':{}
}

class FeatureDialog(QDialog):
 def __init__(self,parent,model,kind,node=None,selected_id=None):
  super().__init__(parent);self.setWindowTitle('Операция: '+kind);self.resize(560,520)
  self.model=model;self.node=node;self.kind=kind
  layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
  self.name=QLineEdit(node.name if node else kind);form.addRow('Имя',self.name)
  layout.addWidget(QLabel('Параметры JSON. Числа могут ссылаться на глобальные параметры по имени.'))
  self.params=QPlainTextEdit(json.dumps(node.params if node else DEFAULT_PARAMS[kind],ensure_ascii=False,indent=2));layout.addWidget(self.params,1)
  layout.addWidget(QLabel('Входные построения (порядок выбора важен для вычитания и loft):'))
  self.refs=QListWidget();self.refs.setSelectionMode(QListWidget.MultiSelection)
  candidates=model.features if node is None else model.features[:model._index(node.id)]
  for feature in candidates:
   item=QListWidgetItem(feature.name+' · '+feature.kind+' · '+feature.id[:8]);item.setData(Qt.UserRole,feature.id);self.refs.addItem(item)
   if (node and feature.id in node.refs) or (node is None and kind in ('extrude','revolve','transform','hole','linear_pattern','polar_pattern','mirror','shell','fillet','chamfer','edge_fillet','edge_chamfer','face_shell','face_hole','component') and feature.id==selected_id):item.setSelected(True)
  layout.addWidget(self.refs,1)
  row=QHBoxLayout();layout.addLayout(row)
  for title,fn in [('Отмена',self.reject),('Проверить и применить',self.accept)]:
   button=QPushButton(title);button.clicked.connect(fn);row.addWidget(button)
 def accept(self):
  try:
   self.result_params=json.loads(self.params.toPlainText())
   if not isinstance(self.result_params,dict):raise ValueError('Параметры должны быть JSON-объектом')
   self.result_refs=[item.data(Qt.UserRole) for item in self.refs.selectedItems()]
   if self.kind=='loft':self.result_refs=[self.refs.item(i).data(Qt.UserRole) for i in range(self.refs.count()) if self.refs.item(i).isSelected()]
  except Exception as exc:QMessageBox.warning(self,'Ошибка операции',str(exc));return
  super().accept()

def mesh_for(model):
 try:
  verts,faces=model.solid().tessellate(1.2)
  return ([(v.x,v.y,v.z) for v in verts],[tuple(face) for face in faces])
 except ValueError:return None

class CADWorker(QThread):
 completed=Signal(object,object,object);failed=Signal(str)
 def __init__(self,model,method,args,kwargs):
  super().__init__();self.model=model;self.method=method;self.args=args;self.kwargs=kwargs
 def run(self):
  try:
   result=getattr(self.model,self.method)(*self.args,**self.kwargs)
   self.completed.emit(self.model,result,mesh_for(self.model))
  except Exception as exc:self.failed.emit(str(exc))

class ExportWorker(QThread):
 completed=Signal(str);failed=Signal(str)
 def __init__(self,model,path,kind):
  super().__init__();self.model=model;self.path=path;self.kind=kind
 def run(self):
  try:
   if self.kind=='pdf':export_universal_pdf(self.model,self.path)
   else:export_model(self.model.solid(),self.path)
   self.completed.emit(self.path)
  except Exception as exc:self.failed.emit(str(exc))

class AnalysisWorker(QThread):
 completed=Signal(object);failed=Signal(str)
 def __init__(self,model):super().__init__();self.model=model
 def run(self):
  try:
   report=shape_report(self.model.solid());report['component_interferences']=component_interferences(self.model)
   self.completed.emit(report)
  except Exception as exc:self.failed.emit(str(exc))

class AIWorker(QThread):
 completed=Signal(object,str,object,object);failed=Signal(str);progress=Signal(str)
 def __init__(self,text,mode,model,config):
  super().__init__();self.text=text;self.mode=mode;self.model=model;self.config=config
 def run(self):
  try:
   commands,mode=request_commands(self.text,self.mode,self.model,self.config,progress=self.progress.emit)
   if commands=='undo':self.model.undo()
   else:execute(self.model,commands)
   mesh=mesh_for(self.model)
   self.completed.emit(self.model,mode,commands,mesh)
  except Exception as exc:self.failed.emit(str(exc))

class ConnectionWorker(QThread):
 completed=Signal(str);failed=Signal(str)
 def __init__(self,mode,config):
  super().__init__();self.mode=mode;self.config=config
 def run(self):
  try:self.completed.emit(check_connection(self.mode,self.config))
  except Exception as exc:self.failed.emit(str(exc))

class UniversalWindow(QMainWindow):
 def __init__(self):
  super().__init__();self.setWindowTitle('AI-CAD Desktop · Universal Engine');self.resize(1400,840)
  self.model=Model();self.path=None;self.selected_id=None;self.worker=None;self.connection_worker=None;self.cad_worker=None;self.export_worker=None;self.request_history=[];self.model_origin=None;self.analysis_worker=None;self.selected_topology=None;self.picked_point=None;self.measure_start=None;self.measure_mode=False
  splitter=QSplitter(Qt.Horizontal);self.setCentralWidget(splitter)
  left=QWidget();ll=QVBoxLayout(left);ll.addWidget(QLabel('Дерево построения'))
  self.tree=QTreeWidget();self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection);self.tree.setHeaderLabels(['Операции и видимость']);self.tree.currentItemChanged.connect(self.select_feature);self.tree.itemChanged.connect(self.visibility_changed);ll.addWidget(self.tree,1)
  self.properties=QPlainTextEdit();self.properties.setReadOnly(True);self.properties.setMaximumHeight(130);ll.addWidget(QLabel('Свойства выбранной операции'));ll.addWidget(self.properties)
  for text,fn in [('Новый эскиз',self.add_sketch),('Добавить операцию',self.choose_feature),('Редактировать выбранную',self.edit_selected),('Удалить выбранную',self.delete_selected)]:
   b=QPushButton(text);b.clicked.connect(fn);ll.addWidget(b)
  row=QHBoxLayout();ll.addLayout(row)
  for text,fn in [('Undo',self.undo),('Redo',self.redo),('Параметр',self.parameter_dialog)]:
   b=QPushButton(text);b.clicked.connect(fn);row.addWidget(b)
  self.parameters=QPlainTextEdit();self.parameters.setReadOnly(True);self.parameters.setMaximumHeight(100);ll.addWidget(QLabel('Глобальные параметры'));ll.addWidget(self.parameters)
  splitter.addWidget(left)
  center=QWidget();cl=QVBoxLayout(center);self.viewer=Viewport();cl.addWidget(self.viewer,1)
  viewrow=QHBoxLayout();cl.addLayout(viewrow)
  for title,ax,az in [('Изометрия',.45,-.6),('Сверху',1.57,0),('Спереди',0,0),('Справа',0,1.57)]:
   b=QPushButton(title);b.clicked.connect(lambda checked=False,x=ax,y=az:self.set_view(x,y));viewrow.addWidget(b)
  pickrow=QHBoxLayout();cl.addLayout(pickrow)
  pickrow.addWidget(QLabel('Выбор:'))
  self.pick_mode=QComboBox();self.pick_mode.addItems(['camera','body','face','edge','vertex']);self.pick_mode.currentTextChanged.connect(self.set_pick_mode);pickrow.addWidget(self.pick_mode)
  self.viewer.picked.connect(self.on_pick)
  self.viewer.dragged.connect(self.on_viewport_drag)
  for title,fn in [('Отверстие в грани',self.hole_on_face),('Оболочка',self.shell_on_face),('Скруглить ребро',self.fillet_edge),('Фаска ребра',self.chamfer_edge)]:
   button=QPushButton(title);button.clicked.connect(fn);pickrow.addWidget(button)
  assemblyrow=QHBoxLayout();cl.addLayout(assemblyrow)
  for title,fn in [('Компонент из выбранного',self.add_component),('Сборка из выделенных',self.add_assembly),('Измерить 2 вершины',self.measure),('Анализ',self.analyze)]:
   button=QPushButton(title);button.clicked.connect(fn);assemblyrow.addWidget(button)
  splitter.addWidget(center)
  right=QWidget();rl=QVBoxLayout(right);rl.addWidget(QLabel('ИИ-оператор CAD'))
  self.mode=QComboBox();self.mode.addItems(['Mistral','Auto','Cloud','Ollama','Offline']);rl.addWidget(self.mode)
  self.prompt=QPlainTextEdit();self.prompt.setPlaceholderText('Создай пластину 100×60×5 мм с четырьмя отверстиями диаметром 6 мм\nили вставьте JSON-команды');self.prompt.setMaximumHeight(120);rl.addWidget(self.prompt)
  self.go=QPushButton('Применить AI-команды');self.go.clicked.connect(self.ai_run);rl.addWidget(self.go)
  self.history=QListWidget();self.history.setMaximumHeight(105);self.history.itemClicked.connect(lambda item:self.prompt.setPlainText(item.data(Qt.UserRole)));rl.addWidget(QLabel('История запросов (сеанс)'));rl.addWidget(self.history)
  self.ai_status=QLabel('Ожидание запроса');rl.addWidget(self.ai_status)
  rl.addWidget(QLabel('Облачный API (Mistral: ключ из MISTRAL_API_KEY)'))
  self.cloud_url=QLineEdit('https://api.mistral.ai/v1');rl.addWidget(self.cloud_url)
  self.cloud_model=QLineEdit('mistral-large-latest');self.cloud_model.setPlaceholderText('Модель');rl.addWidget(self.cloud_model)
  self.api_key=QLineEdit();self.api_key.setEchoMode(QLineEdit.Password);self.api_key.setPlaceholderText('Ключ для Cloud API, только в памяти');rl.addWidget(self.api_key)
  self.consent=QCheckBox('Разрешить отправку текста и структуры проекта');rl.addWidget(self.consent)
  self.check_button=QPushButton('Проверить подключение');self.check_button.clicked.connect(self.check_provider);rl.addWidget(self.check_button)
  self.connection_status=QLabel('Подключение не проверено');rl.addWidget(self.connection_status)
  rl.addWidget(QLabel('Ollama'));self.ollama_url=QLineEdit('http://localhost:11434');rl.addWidget(self.ollama_url)
  self.ollama_model=QLineEdit('llama3.2');rl.addWidget(self.ollama_model)
  self.fallback=QCheckBox('Резервный офлайн-парсер');self.fallback.setChecked(True);rl.addWidget(self.fallback)
  self.log=QPlainTextEdit();self.log.setReadOnly(True);rl.addWidget(self.log,1)
  splitter.addWidget(right);splitter.setSizes([310,760,330])
  self._menus();self.refresh('Готово. Создайте эскиз или выберите операцию.')
 def closeEvent(self,event):
  active=any(worker and worker.isRunning() for worker in (self.worker,self.cad_worker,self.connection_worker,self.export_worker,self.analysis_worker))
  if active:
   event.ignore();self.note('Дождитесь завершения фоновой операции перед закрытием')
  else:super().closeEvent(event)
 def _menus(self):
  file=self.menuBar().addMenu('Файл')
  for text,fn in [('Новый проект',self.new_project),('Открыть',self.open),('Сохранить',self.save),('Сохранить как',self.save_as),('Импорт STEP',self.import_step),('Экспорт STEP',lambda:self.export('.step')),('Экспорт STL',lambda:self.export('.stl')),('Чертёж PDF',self.pdf)]:file.addAction(text,fn)
  edit=self.menuBar().addMenu('Правка');edit.addAction('Отменить',self.undo);edit.addAction('Повторить',self.redo)
  tools=self.menuBar().addMenu('Моделирование');tools.addAction('Эскиз',self.add_sketch)
  for kind in DEFAULT_PARAMS:tools.addAction(kind,lambda checked=False,k=kind:self.add_feature(k))
 def note(self,message):self.log.appendPlainText(message);self.statusBar().showMessage(message[:200])
 def refresh(self,message='Модель перестроена',mesh=None):
  self.selected_topology=None
  self.tree.blockSignals(True);self.tree.clear()
  for node in self.model.features:
   item=QTreeWidgetItem([node.name+' · '+node.kind+(' · AI' if node.source=='ai' else '')]);item.setData(0,Qt.UserRole,node.id)
   item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(0,Qt.Checked if node.visible else Qt.Unchecked);self.tree.addTopLevelItem(item)
   if node.id==self.selected_id:self.tree.setCurrentItem(item)
  self.tree.blockSignals(False)
  self.parameters.setPlainText(json.dumps(self.model.parameters,ensure_ascii=False,indent=2))
  if self.selected_id:
   selected=next((f for f in self.model.features if f.id==self.selected_id),None)
   if selected:self.properties.setPlainText(json.dumps({'id':selected.id,'kind':selected.kind,'params':selected.params,'refs':selected.refs,'visible':selected.visible},ensure_ascii=False,indent=2))
   else:self.properties.clear()
  else:self.properties.clear()
  if mesh is not None:self.viewer.set_mesh(*mesh);self.viewer.set_highlight(None)
  else:
   try:self.viewer.set_solid(self.model.solid());self.viewer.set_highlight(None)
   except ValueError:self.viewer.vertices=[];self.viewer.faces=[];self.viewer.set_highlight(None);self.viewer.update()
  if mesh is None:self.update_pick_context()
  else:self.viewer.set_pick_context(None,[])
  self.note(message)
 def select_feature(self,current,previous):
  self.selected_topology=None
  self.selected_id=current.data(0,Qt.UserRole) if current else None
  if self.selected_id:
   try:
    value=self.model.rebuild()[self.selected_id]
    self.viewer.set_highlight(value if isinstance(value,cq.Shape) else None)
   except Exception:self.viewer.set_highlight(None)
   node=next(f for f in self.model.features if f.id==self.selected_id)
   self.update_pick_context(value if isinstance(value,cq.Shape) else None)
   self.properties.setPlainText(json.dumps({'id':node.id,'kind':node.kind,'params':node.params,'refs':node.refs,'visible':node.visible},ensure_ascii=False,indent=2))
   self.statusBar().showMessage(node.name+' · '+node.kind+' · '+node.id[:8])
 def set_pick_mode(self,mode):
  self.viewer.pick_mode=mode
  if mode!='camera':self.update_pick_context()
  self.viewer.update()
 def update_pick_context(self,shape=None):
  try:
   values=self.model.rebuild()
   if shape is None and self.selected_id:shape=values.get(self.selected_id)
   if not isinstance(shape,cq.Shape):shape=None
   bodies=[(feature.id,solid) for feature,solid in self.model.visible_solids()]
   self.viewer.set_pick_context(shape,bodies)
  except Exception:self.viewer.set_pick_context(None,[])
 def on_pick(self,kind,result):
  if kind=='body':
   for i in range(self.tree.topLevelItemCount()):
    item=self.tree.topLevelItem(i)
    if item.data(0,Qt.UserRole)==result:self.tree.setCurrentItem(item);self.note('Выбрано тело: '+item.text(0));return
   return
  self.selected_topology=(self.selected_id,kind,result['index'])
  self.picked_point=result['point_mm']
  try:
   shape=self.model.rebuild()[self.selected_id];info=element_report(shape,kind,result['index'])
   self.note('Выбрано: '+json.dumps(info,ensure_ascii=False))
   self.properties.appendPlainText('\nВыбранная геометрия:\n'+json.dumps(info,ensure_ascii=False,indent=2))
   if self.measure_mode and kind=='vertex':
    if self.measure_start is None:self.measure_start=result['point_mm'];self.note('Первая вершина выбрана; выберите вторую')
    else:
     distance=sum((a-b)**2 for a,b in zip(self.measure_start,result['point_mm']))**.5
     self.note(f'Расстояние между вершинами: {distance:.3f} мм');self.measure_start=None;self.measure_mode=False
  except Exception as exc:self.note('Ошибка выбора: '+str(exc))
 def measure(self):
  self.measure_start=None;self.measure_mode=True;self.pick_mode.setCurrentText('vertex');self.note('Выберите две вершины последовательно для измерения расстояния')
 def analyze(self):
  if self.analysis_worker and self.analysis_worker.isRunning():return
  self.analysis_worker=AnalysisWorker(deepcopy(self.model))
  self.analysis_worker.completed.connect(lambda report:self.note('Анализ: '+json.dumps(report,ensure_ascii=False)))
  self.analysis_worker.failed.connect(lambda error:self.note('Ошибка анализа: '+error))
  self.note('Анализ геометрии в фоне...');self.analysis_worker.start()
 def selected_element(self,expected):
  if not self.selected_topology or self.selected_topology[0]!=self.selected_id or self.selected_topology[1]!=expected:
   self.note('Выберите '+('грань' if expected=='face' else 'ребро')+' на выбранном теле');return None
  return self.selected_topology[2]
 def hole_on_face(self):
  index=self.selected_element('face')
  if index is None:return
  try:
   face=self.model.rebuild()[self.selected_id].Faces()[index]
   normal=face.normalAt().normalized();reference=cq.Vector(0,0,1) if abs(normal.z)<0.9 else cq.Vector(1,0,0)
   u_axis=normal.cross(reference).normalized();v_axis=normal.cross(u_axis).normalized()
   point=cq.Vector(*self.picked_point);delta=point-face.Center()
   u,v=delta.dot(u_axis),delta.dot(v_axis)
  except Exception as exc:return self.note('Ошибка позиции отверстия: '+str(exc))
  diameter,ok=QInputDialog.getDouble(self,'Отверстие','Диаметр, мм',6,.1,1000,2)
  if not ok:return
  depth,ok=QInputDialog.getDouble(self,'Отверстие','Глубина, мм',10,.1,1000,2)
  if ok:self.run_mutation('add','face_hole',{'face_index':index,'radius':diameter/2,'depth':depth,'u':u,'v':v},[self.selected_id],name='Отверстие по грани',message='Отверстие построено')
 def shell_on_face(self):
  index=self.selected_element('face')
  if index is None:return
  thickness,ok=QInputDialog.getDouble(self,'Оболочка','Толщина стенки, мм',3,.1,1000,2)
  if ok:self.run_mutation('add','face_shell',{'thickness':thickness,'face_index':index},[self.selected_id],name='Оболочка',message='Оболочка построена')
 def fillet_edge(self):self.edge_operation('edge_fillet')
 def chamfer_edge(self):self.edge_operation('edge_chamfer')
 def edge_operation(self,kind):
  index=self.selected_element('edge')
  if index is None:return
  radius,ok=QInputDialog.getDouble(self,'Операция по ребру','Радиус/размер, мм',2,.1,1000,2)
  if ok:self.run_mutation('add',kind,{'radius':radius,'edge_indices':[index]},[self.selected_id],name=kind,message='Операция по ребру построена')
 def add_component(self):
  if not self.selected_id:return self.note('Выберите тело в дереве')
  name,ok=QInputDialog.getText(self,'Компонент','Имя компонента')
  if ok:self.run_mutation('add','component',{'translation':[0,0,0],'rotation':[0,0,0]},[self.selected_id],name=name or 'Компонент',message='Компонент добавлен')
 def add_assembly(self):
  refs=[item.data(0,Qt.UserRole) for item in self.tree.selectedItems()]
  if not 2<=len(refs)<=8:return self.note('Выделите Ctrl-кликом 2–8 компонентов или вложенных сборок')
  kinds={f.id:f.kind for f in self.model.features}
  if any(kinds.get(ref) not in ('component','assembly') for ref in refs):return self.note('Для сборки выбирайте только компоненты и сборки')
  self.run_mutation('add','assembly',{},refs,name='Сборка',message='Сборка построена')
 def run_mutation(self,method,*args,message='Модель перестроена',**kwargs):
  if self.cad_worker and self.cad_worker.isRunning():return self.note('CAD-операция ещё выполняется')
  origin=self.model
  self.cad_worker=CADWorker(deepcopy(origin),method,args,kwargs)
  self.cad_worker.completed.connect(lambda candidate,result,mesh:self.mutation_done(origin,candidate,result,mesh,message))
  self.cad_worker.failed.connect(lambda error:self.note('CAD-операция отклонена: '+error))
  self.note('Перестроение в фоне...');self.cad_worker.start()
 def mutation_done(self,origin,candidate,result,mesh,message):
  if self.model is not origin:return self.note('Проект изменился; устаревший результат CAD не применён')
  self.model=candidate
  if isinstance(result,str) and any(f.id==result for f in candidate.features):self.selected_id=result
  elif self.selected_id and not any(f.id==self.selected_id for f in candidate.features):self.selected_id=None
  self.refresh(message,mesh)
 def visibility_changed(self,item,column):
  node_id=item.data(0,Qt.UserRole)
  if node_id:self.run_mutation('update',node_id,visible=item.checkState(0)==Qt.Checked,message='Видимость изменена')
 def set_view(self,ax,az):self.viewer.ax=ax;self.viewer.az=az;self.viewer.update()
 def on_viewport_drag(self,delta):
  node=next((f for f in self.model.features if f.id==self.selected_id),None)
  if not node or node.kind not in ('component','transform'):
   return self.note('Shift-перетаскивание: сначала выберите компонент или преобразование в дереве')
  params=deepcopy(node.params)
  translated=[]
  for old,change in zip(params['translation'],delta):
   translated.append(f'({old})+({change:.4f})' if isinstance(old,str) else round(old+change,4))
  params['translation']=translated
  self.run_mutation('update',node.id,params=params,message='Компонент перемещён в плоскости вида')
 def add_sketch(self):
  dialog=SketchDialog(self,parameters=self.model.parameters)
  if dialog.exec():
   self.run_mutation('add','sketch',dialog.result_params,name='Эскиз',message='Эскиз добавлен')
 def choose_feature(self):
  choices=list(DEFAULT_PARAMS)
  kind,ok=QInputDialog.getItem(self,'CAD-операция','Выберите операцию',choices,0,False)
  if ok:self.add_feature(kind)
 def add_feature(self,kind):
  dialog=FeatureDialog(self,self.model,kind,selected_id=self.selected_id)
  if dialog.exec():
   self.run_mutation('add',kind,dialog.result_params,dialog.result_refs,dialog.name.text(),message='Операция добавлена: '+kind)
 def edit_selected(self):
  node=next((f for f in self.model.features if f.id==self.selected_id),None)
  if not node:return self.note('Выберите операцию')
  if node.kind=='sketch':
   dialog=SketchDialog(self,node.params,parameters=self.model.parameters)
   if dialog.exec():
    self.run_mutation('update',node.id,params=dialog.result_params,message='Эскиз перестроен')
   return
  dialog=FeatureDialog(self,self.model,node.kind,node=node)
  if dialog.exec():
   self.run_mutation('update',node.id,params=dialog.result_params,refs=dialog.result_refs,name=dialog.name.text(),message='Операция перестроена')
 def delete_selected(self):
  if not self.selected_id:return self.note('Выберите операцию')
  self.run_mutation('remove',self.selected_id,message='Операция удалена')
 def parameter_dialog(self):
  name,ok=QInputDialog.getText(self,'Параметр','Имя параметра')
  if not ok:return
  value,ok=QInputDialog.getDouble(self,'Параметр',name,0,-10000,10000,2)
  if ok:
   self.run_mutation('set_parameter',name,value,message='Параметр '+name+' изменён')
 def undo(self):
  if not self.model._undo:return self.note('Нет действий для отмены')
  self.run_mutation('undo',message='Отменено')
 def redo(self):
  if not self.model._redo:return self.note('Нет действий для повтора')
  self.run_mutation('redo',message='Повторено')
 def provider_config(self):
  return dict(cloud_url=self.cloud_url.text(),cloud_model=self.cloud_model.text(),api_key=self.api_key.text(),consent=self.consent.isChecked(),ollama_url=self.ollama_url.text(),ollama_model=self.ollama_model.text(),fallback=self.fallback.isChecked(),selected_id=self.selected_id,selected_topology=self.selected_topology)
 def check_provider(self):
  mode=self.mode.currentText()
  if mode in ('Offline','Auto'):
   self.connection_status.setText('Выберите Mistral, Cloud или Ollama для проверки');return
  if self.connection_worker and self.connection_worker.isRunning():return
  self.connection_status.setText('Проверка подключения...');self.check_button.setEnabled(False)
  self.connection_worker=ConnectionWorker(mode,self.provider_config())
  self.connection_worker.completed.connect(self.connection_ok);self.connection_worker.failed.connect(self.connection_failed)
  self.connection_worker.start()
 def connection_ok(self,status):
  self.connection_status.setText(status);self.check_button.setEnabled(True);self.note(status)
 def connection_failed(self,error):
  self.connection_status.setText('Не подключено: '+error[:150]);self.check_button.setEnabled(True);self.note('Подключение: '+error)
 def ai_run(self):
  if self.worker and self.worker.isRunning():return
  text=self.prompt.toPlainText().strip()
  if not text:return self.note('Введите инженерное задание')
  try:
   self.model_origin=self.model
   copy=deepcopy(self.model)
  except Exception as exc:return self.note('Ошибка модели: '+str(exc))
  self.request_history.append(text)
  item=QListWidgetItem(text[:100]);item.setData(Qt.UserRole,text);self.history.insertItem(0,item)
  self.worker=AIWorker(text,self.mode.currentText(),copy,self.provider_config())
  self.worker.progress.connect(self.ai_progress);self.worker.completed.connect(self.ai_done);self.worker.failed.connect(self.ai_failed)
  self.go.setEnabled(False);self.ai_status.setText('Выполняется: '+self.mode.currentText());self.note('ИИ обрабатывает запрос...');self.worker.start()
 def ai_progress(self,status):self.ai_status.setText(status);self.note(status)
 def ai_done(self,candidate,mode,commands,mesh):
  try:
   if self.model is not self.model_origin:raise ValueError('Проект изменился во время запроса; результат не применён')
   self.model=candidate
   if commands!='undo':
    self.selected_id=self.model.features[-1].id if self.model.features else None
    for command in commands:
     self.note('CAD: '+str(command.get('action'))+' '+str(command.get('kind') or command.get('name') or command.get('id') or ''))
   else:self.selected_id=None
   self.refresh('Готово · '+mode,mesh);self.ai_status.setText('Готово · '+mode)
  except Exception as exc:self.note('AI-команды не применены: '+str(exc));self.ai_status.setText('Ошибка')
  self.go.setEnabled(True)
 def ai_failed(self,error):
  self.note('AI: '+error);self.ai_status.setText('Ошибка: '+error[:150]);self.go.setEnabled(True)
 def new_project(self):self.model=Model();self.path=None;self.selected_id=None;self.refresh('Новый проект')
 def open(self):
  path,_=QFileDialog.getOpenFileName(self,'Открыть проект','','AI-CAD (*.json)')
  if path:
   try:self.model=load_model(path);self.path=path;self.selected_id=None;self.refresh('Открыт: '+path)
   except Exception as exc:self.note('Ошибка: '+str(exc))
 def save(self):
  path=self.path
  if not path:path,_=QFileDialog.getSaveFileName(self,'Сохранить проект','','AI-CAD (*.aicad.json)')
  if path:
   try:save_model(path,self.model);self.path=path;self.note('Сохранено: '+path)
   except Exception as exc:self.note('Ошибка: '+str(exc))
 def save_as(self):self.path=None;self.save()
 def import_step(self):
  path,_=QFileDialog.getOpenFileName(self,'Импорт STEP','','STEP (*.step *.stp)')
  if path:self.run_mutation('import_step',path,message='STEP импортирован как переносимое тело')
 def start_export(self,path,kind):
  if self.export_worker and self.export_worker.isRunning():return self.note('Экспорт уже выполняется')
  self.export_worker=ExportWorker(deepcopy(self.model),path,kind)
  self.export_worker.completed.connect(lambda saved:self.note('Экспорт завершён: '+saved))
  self.export_worker.failed.connect(lambda error:self.note('Ошибка экспорта: '+error))
  self.note('Экспорт выполняется в фоне...');self.export_worker.start()
 def export(self,ext):
  path,_=QFileDialog.getSaveFileName(self,'Экспорт CAD','model'+ext,'CAD (*'+ext+')')
  if path:self.start_export(path,ext)
 def pdf(self):
  path,_=QFileDialog.getSaveFileName(self,'Предварительный чертёж','drawing.pdf','PDF (*.pdf)')
  if path:self.start_export(path,'pdf')

def main():
 app=QApplication([]);app.setStyle('Fusion');window=UniversalWindow();window.show();return app.exec()
