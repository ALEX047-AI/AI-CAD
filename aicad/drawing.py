"""Предварительный чертёж в трёх проекциях с размерами. Не является сертифицированной конструкторской документацией."""
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from .core import PartSpec

def export_pdf(spec,path):
 spec.validate(); p=spec.parameters
 if spec.kind=='plate': L,W,H=p['length'],p['width'],p['thickness']
 elif spec.kind=='bracket':L,W,H=p['horizontal_length'],p['width'],p['vertical_height']
 elif spec.kind=='cylinder':L=W=p['diameter'];H=p['height']
 elif spec.kind=='sphere':L=W=H=p['diameter']
 else:L,W,H=p['length'],p['width'],p['height']
 c=canvas.Canvas(str(path),pagesize=A4);pw,ph=A4
 c.setFont('Helvetica-Bold',17);c.drawString(45,ph-50,'AI-CAD | PRELIMINARY DRAWING')
 c.setFont('Helvetica',10);c.drawString(45,ph-70,f'Part: {spec.kind} | Units: mm | NOT FOR MANUFACTURING APPROVAL')
 scale=min(1.7,200/max(L,W,H));c.setLineWidth(1.4)
 def rect_view(x,y,a,b,title,lab_a,lab_b):
  c.rect(x,y,a*scale,b*scale)
  c.setFont('Helvetica',10);c.drawString(x,y-22,title)
  c.drawCentredString(x+a*scale/2,y-13,f'{lab_a:g} mm')
  c.drawString(x+a*scale+7,y+b*scale/2,f'{lab_b:g}')
 rect_view(55,ph-340,L,W,'TOP',L,W)
 rect_view(55,ph-585,L,H,'FRONT',L,H)
 rect_view(340,ph-585,W,H,'SIDE',W,H)
 if spec.kind=='plate' and p['hole_count']:
  x0,y0=55,ph-340
  for x in (p['edge_offset'],L-p['edge_offset']):
   for y in (p['edge_offset'],W-p['edge_offset']):
    c.circle(x0+x*scale,y0+y*scale,p['hole_diameter']/2*scale)
  c.drawString(55,ph-370,f"4 x DIA {p['hole_diameter']:g} mm; edge offset {p['edge_offset']:g} mm")
 if spec.kind=='enclosure':c.drawString(55,ph-620,f"Wall {p['wall_thickness']:g} mm | Floor {p['floor_thickness']:g} mm")
 if spec.kind=='bracket':c.drawString(55,ph-620,f"L-bracket thickness {p['thickness']:g} mm")
 c.setFont('Helvetica-Oblique',9);c.drawString(45,40,'Simplified schematic projections. Not a standards-compliant production drawing.')
 c.showPage();c.save()

def export_universal_pdf(model,path):
 """Предварительный лист проекций рёбер для поддерживаемого графа операций."""
 from pathlib import Path
 solid=model.solid();bb=solid.BoundingBox();out=Path(path)
 if out.suffix.lower()!='.pdf':raise ValueError('Требуется файл PDF')
 width,height=A4;c=canvas.Canvas(str(out),pagesize=A4)
 c.setFont('Helvetica-Bold',16);c.drawString(40,height-45,'AI-CAD | PRELIMINARY CAD DRAWING')
 c.setFont('Helvetica',9);c.drawString(40,height-62,'Units: mm  |  Orthographic projections  |  Not a certified production drawing')
 dimensions=(bb.xlen,bb.ylen,bb.zlen)
 edges=solid.Edges()
 def view(title,origin,axes,dims):
  x0,y0=origin;available_w,available_h=245,205
  scale=min(available_w/max(dims[0],1),available_h/max(dims[1],1),2.4)
  c.setStrokeColorRGB(.18,.31,.48);c.setLineWidth(.55)
  def xy(v):
   coords=(v.x-bb.xmin,v.y-bb.ymin,v.z-bb.zmin)
   return x0+coords[axes[0]]*scale,y0+coords[axes[1]]*scale
  for edge in edges:
   try:
    pts=edge.sample(24)[0]
    if len(pts)<2:continue
    path_obj=c.beginPath();path_obj.moveTo(*xy(pts[0]))
    for point in pts[1:]:path_obj.lineTo(*xy(point))
    c.drawPath(path_obj)
   except Exception:continue
  c.setStrokeColorRGB(0,0,0);c.setFont('Helvetica-Bold',10);c.drawString(x0,y0-21,title)
  c.setFont('Helvetica',9);c.drawCentredString(x0+dims[0]*scale/2,y0-12,f'{dims[0]:.2f} mm')
  c.drawString(x0+dims[0]*scale+6,y0+dims[1]*scale/2,f'{dims[1]:.2f} mm')
 view('TOP (X-Y)',(50,510),(0,1),(dimensions[0],dimensions[1]))
 view('FRONT (X-Z)',(50,250),(0,2),(dimensions[0],dimensions[2]))
 view('RIGHT (Y-Z)',(330,250),(1,2),(dimensions[1],dimensions[2]))
 c.setFont('Helvetica',9);c.drawString(45,125,f'Overall: X {bb.xlen:.2f} | Y {bb.ylen:.2f} | Z {bb.zlen:.2f} mm')
 c.drawString(45,108,f'Features: {len(model.features)} | Visible solids: {len(model.visible_solids())}')
 c.drawString(45,70,'Simplified edge projection. Hidden-line removal, tolerances and standards symbols absent.')
 c.showPage();c.save()
 if not out.exists() or out.stat().st_size<500:raise RuntimeError('PDF не создан')
 return out
