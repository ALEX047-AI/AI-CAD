"""Настольное приложение Qt с интерактивным программным отображением CAD-сетки без доступа к сети."""
from __future__ import annotations
import math, os
from PySide6.QtCore import Qt, QPointF, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPolygonF
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
 QLineEdit,QTextEdit,QPushButton,QLabel,QComboBox,QDoubleSpinBox,QFileDialog,QMessageBox,QSplitter,QScrollArea,QCheckBox,QTreeWidget,QTreeWidgetItem)
from .core import new_spec,build,save_project,load_project,export_model,FIELDS
from .ai import interpret
from .project import Project, save as save_multi, load as load_multi
from .drawing import export_pdf
from .inspection import pick_topology,screen_drag_to_world

class Viewport(QWidget):
 picked=Signal(str,object)
 dragged=Signal(object)
 def __init__(self):
  super().__init__();self.vertices=[];self.faces=[];self.highlight_vertices=[];self.highlight_faces=[];self.ax=0.45;self.az=-0.6;self.zoom=1;self.last=None;self.press_pos=None;self.pick_mode='camera';self.pick_shape=None;self.pick_bodies=[];self.picked_element=None
  self.setMinimumSize(430,330);self.setStyleSheet('background:#18212e')
 def set_solid(self,solid):
  verts,faces=solid.tessellate(1.2)
  self.set_mesh([(v.x,v.y,v.z) for v in verts],[tuple(f) for f in faces])
 def set_mesh(self,vertices,faces):
  self.vertices=vertices;self.faces=faces
  if self.vertices:
   mins=[min(v[i] for v in self.vertices) for i in range(3)]
   maxs=[max(v[i] for v in self.vertices) for i in range(3)]
   self.center=[(a+b)/2 for a,b in zip(mins,maxs)];self.extent=max(b-a for a,b in zip(mins,maxs)) or 1
  self.update()
 def set_highlight(self,solid):
  if solid is None:self.highlight_vertices=[];self.highlight_faces=[]
  else:
   verts,faces=solid.tessellate(1.5)
   self.highlight_vertices=[(v.x,v.y,v.z) for v in verts];self.highlight_faces=[tuple(f) for f in faces]
  self.update()
 def set_pick_context(self,shape=None,bodies=None):
  self.pick_shape=shape;self.pick_bodies=bodies or [];self.picked_element=None;self.update()
 def mousePressEvent(self,event):self.last=event.position();self.press_pos=event.position()
 def mouseMoveEvent(self,event):
  if self.last and event.buttons() & Qt.LeftButton:
   p=event.position()
   if not event.modifiers() & Qt.ShiftModifier:
    self.az+=(p.x()-self.last.x())*.012;self.ax+=(p.y()-self.last.y())*.012
    self.ax=max(-1.5,min(1.5,self.ax))
   self.last=p;self.update()
 def mouseReleaseEvent(self,event):
  if self.press_pos:
   dx=event.position().x()-self.press_pos.x();dy=event.position().y()-self.press_pos.y()
   if event.modifiers() & Qt.ShiftModifier and abs(dx)+abs(dy)>=5 and self.vertices:
    scale=min(self.width(),self.height())*.68/self.extent*self.zoom
    self.dragged.emit(screen_drag_to_world(dx,dy,scale,self.az,self.ax))
   elif self.pick_mode!='camera' and abs(dx)+abs(dy)<5:self.pick_at(event.position().x(),event.position().y())
  self.last=None;self.press_pos=None
 def pick_at(self,x,y):
  if self.pick_mode=='body':
   candidate=None
   for feature_id,shape in self.pick_bodies:
    hit=pick_topology(shape,self._project,x,y,'face')
    if hit and (candidate is None or self._project(hit['point_mm'])[2]<candidate[0]):candidate=(self._project(hit['point_mm'])[2],feature_id)
   if candidate:self.picked.emit('body',candidate[1])
   return
  if self.pick_shape is None:return
  hit=pick_topology(self.pick_shape,self._project,x,y,self.pick_mode)
  if hit:
   self.picked_element=(self.pick_mode,hit['index']);self.picked.emit(self.pick_mode,hit);self.update()
 def wheelEvent(self,event):self.zoom=max(.15,min(8,self.zoom*(1.15 if event.angleDelta().y()>0 else 1/1.15)));self.update()
 def _project(self,v):
  x,y,z=(v[i]-self.center[i] for i in range(3))
  ca,sa=math.cos(self.az),math.sin(self.az);x,y=x*ca-y*sa,x*sa+y*ca
  cb,sb=math.cos(self.ax),math.sin(self.ax);y,z=y*cb-z*sb,y*sb+z*cb
  sc=min(self.width(),self.height())*.68/self.extent*self.zoom
  return (self.width()/2+x*sc,self.height()/2-z*sc,y)
 def paintEvent(self,event):
  p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
  p.fillRect(self.rect(),QColor('#18212e'))
  if not self.vertices:
   p.setPen(QColor('#b7c7d8'));p.drawText(self.rect(),Qt.AlignCenter,'Создайте деталь для 3D-просмотра');return
  pts=[self._project(v) for v in self.vertices];triangles=[]
  for f in self.faces:
   if len(f)!=3:continue
   a,b,c=[pts[i] for i in f]
   depth=(a[2]+b[2]+c[2])/3
   # Треугольники с плоским затенением сортируются по глубине; перетаскивание вращает модель, колесо меняет масштаб
   ux,uy=b[0]-a[0],b[1]-a[1];vx,vy=c[0]-a[0],c[1]-a[1]
   intensity=abs(ux*vy-uy*vx)/(abs(ux*vy-uy*vx)+180)
   triangles.append((depth,QPolygonF([QPointF(a[0],a[1]),QPointF(b[0],b[1]),QPointF(c[0],c[1])]),intensity))
  for depth,poly,shade in sorted(triangles,key=lambda t:t[0],reverse=True):
   level=int(115+90*shade);p.setBrush(QBrush(QColor(level,level+15,min(255,level+32))))
   p.setPen(QPen(QColor('#46566a'),.35));p.drawPolygon(poly)
  if self.highlight_vertices:
   hp=[self._project(v) for v in self.highlight_vertices]
   p.setPen(QPen(QColor('#f6b94c'),1.25));p.setBrush(Qt.NoBrush)
   for face in self.highlight_faces[:4000]:
    if len(face)==3:
     a,b,c=[hp[i] for i in face]
     p.drawLine(QPointF(a[0],a[1]),QPointF(b[0],b[1]));p.drawLine(QPointF(b[0],b[1]),QPointF(c[0],c[1]));p.drawLine(QPointF(c[0],c[1]),QPointF(a[0],a[1]))
  if self.picked_element and self.pick_shape is not None:
   kind,index=self.picked_element
   p.setPen(QPen(QColor('#ffb020'),2.5));p.setBrush(Qt.NoBrush)
   if kind=='face':elements=self.pick_shape.Faces()[index].Edges()
   elif kind=='edge':elements=[self.pick_shape.Edges()[index]]
   else:elements=[]
   for edge in elements:
    points=[self._project((v.x,v.y,v.z)) for v in edge.sample(20)[0]]
    for a,b in zip(points,points[1:]):p.drawLine(QPointF(a[0],a[1]),QPointF(b[0],b[1]))
   if kind=='vertex':
    v=self.pick_shape.Vertices()[index].Center();point=self._project((v.x,v.y,v.z));p.setBrush(QColor('#ffb020'));p.drawEllipse(QPointF(point[0],point[1]),5,5)
  p.setPen(QColor('#d8e3f0'));p.drawText(12,23,'ЛКМ: вращение/выбор   •   Shift+ЛКМ: переместить компонент   •   Колесо: масштаб')

class AIWorker(QThread):
 completed=Signal(object,str);failed=Signal(str)
 def __init__(self,text,mode,current,config):
  super().__init__();self.text=text;self.mode=mode;self.current=current;self.config=config
 def run(self):
  try:
   spec,used=interpret(self.text,self.mode,self.current,self.config)
   build(spec);self.completed.emit(spec,used)
  except Exception as e:self.failed.emit(str(e))

class Window(QMainWindow):
 def __init__(self):
  super().__init__();self.setWindowTitle('AI-CAD Desktop 0.1');self.resize(1220,770)
  self.project=Project();self.path=None;self.spec=None;self.solid=None;self.inputs={};self.worker=None
  root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
  splitter=QSplitter(Qt.Horizontal);layout.addWidget(splitter,1)
  left=QWidget();lv=QVBoxLayout(left);lv.addWidget(QLabel('AI-CAD • Проект'))
  self.kind=QComboBox();self.kind.addItems(['plate','bracket','enclosure','box','cylinder','sphere']);self.kind.currentTextChanged.connect(self.kind_changed)
  lv.addWidget(self.kind)
  self.tree=QTreeWidget();self.tree.setHeaderLabels(['Объекты / история']);self.tree.currentItemChanged.connect(self.select_tree);lv.addWidget(self.tree,1)
  self.form=QFormLayout();lv.addLayout(self.form)
  self.pose={}
  for group in ('Позиция','Поворот'):
   for axis in 'XYZ':
    spin=QDoubleSpinBox();spin.setRange(-10000,10000);spin.setDecimals(2);self.form.addRow(group+' '+axis,spin);self.pose[group+axis]=spin
  row=QHBoxLayout()
  for title,handler in [('Добавить',self.add_manual),('Удалить',self.remove_selected),('Undo',self.undo),('Redo',self.redo)]:
   btn=QPushButton(title);btn.clicked.connect(handler);row.addWidget(btn)
  lv.addLayout(row)
  lv.addWidget(QLabel('Параметры в миллиметрах'))
  regen=QPushButton('Перестроить по параметрам');regen.clicked.connect(self.regenerate);lv.addWidget(regen)
  for name,handler in [('Сохранить проект',self.save),('Открыть проект',self.open),('Экспорт STEP',lambda:self.export('.step')),('Экспорт STL',lambda:self.export('.stl')),('Чертёж PDF',self.pdf)]:
   b=QPushButton(name);b.clicked.connect(handler);lv.addWidget(b)
  lv.addStretch();splitter.addWidget(left)
  self.viewer=Viewport();splitter.addWidget(self.viewer)
  right=QWidget();rv=QVBoxLayout(right);rv.addWidget(QLabel('ИИ-помощник'))
  self.mode=QComboBox();self.mode.addItems(['Offline','Auto','Cloud','Ollama']);rv.addWidget(self.mode)
  self.prompt=QTextEdit();self.prompt.setPlaceholderText('Создай пластину 100×60×5 мм с четырьмя отверстиями диаметром 6 мм');self.prompt.setMaximumHeight(105);rv.addWidget(self.prompt)
  self.go=QPushButton('Создать / изменить');self.go.clicked.connect(self.generate);rv.addWidget(self.go)
  rv.addWidget(QLabel('Настройки облачного ИИ'))
  self.cloud_url=QLineEdit('https://api.openai.com/v1');rv.addWidget(self.cloud_url)
  self.cloud_model=QLineEdit();self.cloud_model.setPlaceholderText('Имя модели');rv.addWidget(self.cloud_model)
  self.api_key=QLineEdit(os.environ.get('AICAD_API_KEY',''));self.api_key.setEchoMode(QLineEdit.Password);self.api_key.setPlaceholderText('API-ключ (только в памяти)');rv.addWidget(self.api_key)
  self.consent=QCheckBox('Разрешить отправку текста в облако');rv.addWidget(self.consent)
  rv.addWidget(QLabel('Локальная Ollama'))
  self.ollama_url=QLineEdit('http://localhost:11434');rv.addWidget(self.ollama_url)
  self.ollama_model=QLineEdit('llama3.2');rv.addWidget(self.ollama_model)
  self.fallback=QCheckBox('Резервный офлайн-парсер');self.fallback.setChecked(True);rv.addWidget(self.fallback)
  self.log=QTextEdit();self.log.setReadOnly(True);rv.addWidget(self.log,1)
  splitter.addWidget(right);splitter.setSizes([260,670,290]);self.kind_changed('plate')
  self.prompt.setPlainText('Создай пластину 100×60×5 мм с четырьмя отверстиями диаметром 6 мм')
  menu=self.menuBar().addMenu('Файл')
  for title,handler in [('Новый',self.new_project),('Открыть',self.open),('Сохранить',self.save),('Сохранить как',self.save_as)]:menu.addAction(title,handler)
  edit=self.menuBar().addMenu('Правка');edit.addAction('Отменить',self.undo);edit.addAction('Повторить',self.redo)
  views=self.menuBar().addMenu('Вид')
  for title,ax,az in [('Изометрия',.45,-.6),('Сверху',0,0),('Спереди',1.57,0),('Справа',1.57,1.57)]:views.addAction(title,lambda x=ax,y=az:self.set_view(x,y))
  self.statusBar().showMessage('Готово. Начните с офлайн-запроса.')
 def refresh(self,mode='Ручное'):
  self.tree.blockSignals(True);self.tree.clear()
  for item in self.project.items:
   node=QTreeWidgetItem([item.name+' — '+item.spec.kind]);node.setData(0,Qt.UserRole,item.id);self.tree.addTopLevelItem(node)
   if item.id==self.project.selected_id:self.tree.setCurrentItem(node)
  history=QTreeWidgetItem(['История ('+str(len(self.project.operations))+')']);self.tree.addTopLevelItem(history)
  for op in self.project.operations[-30:]:history.addChild(QTreeWidgetItem([op['source']+': '+op['action']]))
  self.tree.blockSignals(False)
  item=self.project.selected()
  if item:
   self.set_spec(item.spec,mode)
   for group,values in [('Позиция',item.position),('Поворот',item.rotation)]:
    for axis,value in zip('XYZ',values):self.pose[group+axis].setValue(value)
  else:
   self.spec=None;self.solid=None;self.viewer.vertices=[];self.viewer.faces=[];self.viewer.update()
 def select_tree(self,current,previous):
  if current is None:return
  item_id=current.data(0,Qt.UserRole)
  if item_id:self.project.select(item_id);self.refresh('Выбор объекта')
 def add_manual(self):
  try:
   spec=new_spec(self.kind.currentText(),**{k:w.value() for k,w in self.inputs.items()})
   self.project.add(spec);self.refresh('Ручное создание')
  except Exception as e:self.message('Ошибка: '+str(e))
 def remove_selected(self):
  try:
   if self.project.selected_id:self.project.remove(self.project.selected_id);self.refresh('Удаление')
  except Exception as e:self.message('Ошибка: '+str(e))
 def undo(self):
  if self.project.undo():self.refresh('Undo')
 def redo(self):
  if self.project.redo():self.refresh('Redo')
 def new_project(self):
  self.project=Project();self.path=None;self.refresh('Новый проект')
 def save_as(self):
  self.path=None;self.save()
 def set_view(self,ax,az):self.viewer.ax=ax;self.viewer.az=az;self.viewer.update()
 def message(self,text):self.log.append(text);self.statusBar().showMessage(text[:200])
 def kind_changed(self,kind):
  for widget in self.inputs.values():
   self.form.removeWidget(widget);widget.deleteLater()
  # Поля параметров добавляются под постоянными элементами управления положением и поворотом.
  while self.form.rowCount()>6:self.form.removeRow(6)
  self.inputs={}
  defaults=new_spec(kind).parameters
  for name,value in defaults.items():
   w=QDoubleSpinBox();w.setRange(0,1000);w.setDecimals(2);w.setValue(value)
   if name=='hole_count':w.setDecimals(0);w.setSingleStep(4)
   self.form.addRow(name,w);self.inputs[name]=w
 def set_spec(self,spec,mode='Параметры'):
  self.spec=spec;self.kind.blockSignals(True);self.kind.setCurrentText(spec.kind);self.kind.blockSignals(False)
  self.kind_changed(spec.kind)
  for k,v in spec.parameters.items():self.inputs[k].setValue(v)
  self.solid=self.project.combined_solid() if self.project.items else build(spec);self.viewer.set_solid(self.solid)
  self.message(f'✓ {spec.kind} построена. Режим: {mode}. Объём {self.solid.Volume():.1f} мм³')
  if spec.kind=='plate' and spec.parameters['hole_count']:self.message('Смещение центров отверстий от краёв: '+str(spec.parameters['edge_offset'])+' мм (значение по умолчанию)')
 def regenerate(self):
  try:
   spec=new_spec(self.kind.currentText(),**{k:w.value() for k,w in self.inputs.items()})
   item=self.project.selected()
   if item:self.project.update(item.id,spec,tuple(self.pose['Позиция'+a].value() for a in 'XYZ'),tuple(self.pose['Поворот'+a].value() for a in 'XYZ'))
   else:self.project.add(spec)
   self.refresh('Редактор параметров')
  except Exception as e:self.message('Ошибка: '+str(e))
 def generate(self):
  if self.prompt.toPlainText().strip().lower() in ('удали последнее изменение','отмени последнее изменение'):
   if self.project.undo():self.refresh('ИИ: отмена')
   else:self.message('Нет изменений для отмены')
   return
  if self.worker and self.worker.isRunning():return
  config=dict(cloud_url=self.cloud_url.text(),cloud_model=self.cloud_model.text(),api_key=self.api_key.text(),consent=self.consent.isChecked(),ollama_url=self.ollama_url.text(),ollama_model=self.ollama_model.text(),fallback=self.fallback.isChecked())
  self.worker=AIWorker(self.prompt.toPlainText(),self.mode.currentText(),self.spec,config)
  self.worker.completed.connect(self.finish);self.worker.failed.connect(lambda e:self.finish_error(e));self.go.setEnabled(False);self.message('Обрабатываю запрос...');self.worker.start()
 def finish(self,spec,mode):
  try:
   if self.project.selected() and (self.prompt.toPlainText().lower().startswith(('измени','увеличь','поменяй','установи'))):self.project.update(self.project.selected_id,spec,source=mode)
   else:self.project.add(spec,source=mode)
   self.refresh(mode)
  except Exception as e:self.message('Ошибка геометрии: '+str(e))
  self.go.setEnabled(True)
 def finish_error(self,e):self.message('Ошибка: '+e);self.go.setEnabled(True)
 def save(self):
  if not self.project.items:return self.message('Сначала создайте деталь')
  path=self.path
  if not path:path,_=QFileDialog.getSaveFileName(self,'Сохранить проект','','AI-CAD (*.aicad.json)')
  if path:
   try:save_multi(path,self.project);self.path=path;self.message('Сохранено: '+path)
   except Exception as e:self.message('Ошибка: '+str(e))
 def open(self):
  path,_=QFileDialog.getOpenFileName(self,'Открыть проект','','AI-CAD (*.json)')
  if path:
   try:self.project=load_multi(path);self.path=path;self.refresh('Загруженный проект')
   except Exception as e:self.message('Ошибка: '+str(e))
 def export(self,ext):
  if not self.project.items:return self.message('Сначала создайте деталь')
  path,_=QFileDialog.getSaveFileName(self,'Экспорт CAD','model'+ext,'CAD (*'+ext+')')
  if path:
   try:export_model(self.project.combined_solid(),path);self.message('Экспортировано: '+path)
   except Exception as e:self.message('Ошибка: '+str(e))
 def pdf(self):
  if self.spec is None:return self.message('Сначала создайте деталь')
  path,_=QFileDialog.getSaveFileName(self,'Чертёж','drawing.pdf','PDF (*.pdf)')
  if path:
   try:export_pdf(self.spec,path);self.message('Чертёж создан: '+path)
   except Exception as e:self.message('Ошибка: '+str(e))

def main():
 app=QApplication([]);app.setStyle('Fusion');w=Window();w.show();app.exec()
