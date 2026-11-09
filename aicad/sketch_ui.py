"""Простой редактор двумерных эскизов с размерами, без решателя геометрических ограничений."""
from __future__ import annotations
import json,math
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QColor,QPainter,QPen,QPainterPath
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QPushButton,QPlainTextEdit,QLabel,QWidget,QMessageBox
from .universal import Model,_number

class SketchCanvas(QWidget):
 def __init__(self,changed):
  super().__init__();self.changed=changed;self.entities=[];self.tool='rectangle';self.pending=[];self.parameters={}
  self.setMinimumSize(500,390);self.setMouseTracking(True)
 def xy(self,point):return (round((point.x()-self.width()/2)/4,1),round((self.height()/2-point.y())/4,1))
 def value(self,number):return _number(number,self.parameters)
 def screen(self,point):return QPointF(self.width()/2+self.value(point[0])*4,self.height()/2-self.value(point[1])*4)
 def mousePressEvent(self,event):
  if event.button()!=Qt.LeftButton:return
  point=self.xy(event.position());self.pending.append(point)
  if self.tool in ('polygon','path'):self.update();return
  if len(self.pending)<2:return
  a,b=self.pending;self.pending=[]
  if a==b:return
  if self.tool=='rectangle':
   entity=dict(type='rectangle',center=[(a[0]+b[0])/2,(a[1]+b[1])/2],width=abs(a[0]-b[0]),height=abs(a[1]-b[1]))
  elif self.tool=='circle':entity=dict(type='circle',center=list(a),radius=round(math.dist(a,b),2))
  else:entity=dict(type='line',start=list(a),end=list(b))
  self.entities.append(entity);self.changed();self.update()
 def mouseDoubleClickEvent(self,event):
  if self.tool not in ('polygon','path'):return
  pts=self.pending
  if len(pts)>1 and pts[-1]==pts[-2]:pts=pts[:-1]
  minimum=3 if self.tool=='polygon' else 2
  if len(pts)>=minimum:self.entities.append(dict(type=self.tool,points=[list(p) for p in pts]));self.changed()
  self.pending=[];self.update()
 def paintEvent(self,event):
  p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.fillRect(self.rect(),QColor('#f7f9fb'))
  p.setPen(QPen(QColor('#e5eaf0'),1))
  for x in range(self.width()//2%40,self.width(),40):p.drawLine(x,0,x,self.height())
  for y in range(self.height()//2%40,self.height(),40):p.drawLine(0,y,self.width(),y)
  p.setPen(QPen(QColor('#96a5b7'),1));p.drawLine(self.width()//2,0,self.width()//2,self.height());p.drawLine(0,self.height()//2,self.width(),self.height()//2)
  p.setPen(QPen(QColor('#176bb0'),2))
  for ent in self.entities:
   try:self.draw_entity(p,ent)
   except (ValueError,TypeError,KeyError):continue
  if self.pending:
   p.setPen(QPen(QColor('#e77d22'),2));pts=[self.screen(v) for v in self.pending]
   for a,b in zip(pts,pts[1:]):p.drawLine(a,b)
   for a in pts:p.drawEllipse(a,3,3)
  p.setPen(QColor('#334155'));p.drawText(10,20,'Шаг сетки 10 мм • масштаб 4 px/мм • двойной щелчок завершает полигон/траекторию')
 def draw_entity(self,p,ent):
  kind=ent['type']
  if kind=='rectangle':
   x,y=(self.value(v) for v in ent['center']);w=self.value(ent['width']);h=self.value(ent['height'])
   a=self.screen((x-w/2,y+h/2));p.drawRect(int(a.x()),int(a.y()),int(w*4),int(h*4))
  elif kind=='circle':
   a=self.screen(ent['center']);r=self.value(ent['radius'])*4;p.drawEllipse(a,r,r)
  elif kind in ('polygon','path'):
   pts=[self.screen(v) for v in ent['points']]
   for a,b in zip(pts,pts[1:]+(pts[:1] if kind=='polygon' else [])):p.drawLine(a,b)
  elif kind=='profile':
   path=QPainterPath(self.screen(ent['start']))
   for segment in ent['segments']:
    if segment['type']=='line':path.lineTo(self.screen(segment['to']))
    else:path.quadTo(self.screen(segment['mid']),self.screen(segment['to']))
   if ent['closed']:path.closeSubpath()
   p.drawPath(path)
  elif kind=='line':p.drawLine(self.screen(ent['start']),self.screen(ent['end']))

class SketchDialog(QDialog):
 def __init__(self,parent=None,params=None,parameters=None):
  super().__init__(parent);self.setWindowTitle('Редактор эскиза');self.resize(760,650)
  layout=QVBoxLayout(self);row=QHBoxLayout();layout.addLayout(row)
  row.addWidget(QLabel('Плоскость'))
  self.plane=QComboBox();self.plane.addItems(['XY','XZ','YZ','Custom']);row.addWidget(self.plane)
  row.addWidget(QLabel('Инструмент'))
  self.tool=QComboBox();self.tool.addItems(['rectangle','circle','polygon','line','path']);row.addWidget(self.tool)
  self.canvas=SketchCanvas(self.sync_text);self.parameters=parameters or {};self.canvas.parameters=self.parameters;layout.addWidget(self.canvas,1)
  self.tool.currentTextChanged.connect(self.set_tool)
  row2=QHBoxLayout();layout.addLayout(row2)
  for title,handler in [('Удалить последний',self.remove_last),('Применить JSON',self.apply_json)]:
   b=QPushButton(title);b.clicked.connect(handler);row2.addWidget(b)
  layout.addWidget(QLabel('Размеры и координаты можно точно изменить в JSON. Открытые линии не выдавливаются.'))
  self.text=QPlainTextEdit();self.text.setMaximumHeight(135);layout.addWidget(self.text)
  buttons=QHBoxLayout();layout.addLayout(buttons)
  for title,handler in [('Отмена',self.reject),('Сохранить эскиз',self.accept)]:
   b=QPushButton(title);b.clicked.connect(handler);buttons.addWidget(b)
  params=params or {'plane':'XY','origin':[0,0,0],'entities':[]}
  plane=params.get('plane','XY');self.custom_plane=plane if isinstance(plane,dict) else {'normal':[0,0,1],'x_dir':[1,0,0]}
  self.plane.setCurrentText('Custom' if isinstance(plane,dict) else plane);self.canvas.entities=params.get('entities',[]);self.origin=params.get('origin',[0,0,0]);self.constraints=params.get('constraints',[]);self.sync_text();self.plane.currentTextChanged.connect(lambda _:self.sync_text())
 def set_tool(self,tool):self.canvas.tool=tool;self.canvas.pending=[];self.canvas.update()
 def sync_text(self):
  plane=self.custom_plane if self.plane.currentText()=='Custom' else self.plane.currentText()
  self.text.setPlainText(json.dumps({'plane':plane,'origin':self.origin,'entities':self.canvas.entities,'constraints':self.constraints},ensure_ascii=False,indent=2))
 def apply_json(self):
  try:
   data=json.loads(self.text.toPlainText());
   if not isinstance(data,dict):raise ValueError('Эскиз должен быть JSON-объектом')
   self.origin=data.get('origin',[0,0,0]);self.constraints=data.get('constraints',[])
   plane=data.get('plane','XY')
   if isinstance(plane,dict):self.custom_plane=plane;self.plane.setCurrentText('Custom')
   else:self.plane.setCurrentText(plane)
   self.canvas.entities=data.get('entities',[]);self.canvas.pending=[];self.canvas.update();self.sync_text()
  except Exception as exc:QMessageBox.warning(self,'Ошибка эскиза',str(exc))
 def remove_last(self):
  if self.canvas.entities:self.canvas.entities.pop();self.sync_text();self.canvas.update()
 def accept(self):
  try:
   self.result_params=json.loads(self.text.toPlainText());
   if not isinstance(self.result_params,dict):raise ValueError('Эскиз должен быть JSON-объектом')
  except Exception as exc:QMessageBox.warning(self,'Ошибка эскиза',str(exc));return
  super().accept()
