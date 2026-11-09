"""Анализ топологии CAD-модели и выбор элементов на экране с использованием геометрии CadQuery."""
from __future__ import annotations
import math


def shape_report(shape):
    bb=shape.BoundingBox()
    return {'volume_mm3':shape.Volume(),'bbox_mm':[bb.xlen,bb.ylen,bb.zlen],
            'solid_count':len(shape.Solids()),'face_count':len(shape.Faces()),
            'edge_count':len(shape.Edges()),'vertex_count':len(shape.Vertices())}


def element_report(shape,kind,index):
    elements={'face':shape.Faces(),'edge':shape.Edges(),'vertex':shape.Vertices()}.get(kind)
    if elements is None or type(index) is not int or not 0<=index<len(elements):raise ValueError('Неизвестный топологический элемент')
    element=elements[index];point=element.Center()
    report={'kind':kind,'index':index,'center_mm':[point.x,point.y,point.z]}
    if kind=='face':
        report.update(area_mm2=element.Area(),geometry=element.geomType())
        if element.geomType()=='PLANE':
            normal=element.normalAt();report['normal']=[normal.x,normal.y,normal.z]
    elif kind=='edge':report.update(length_mm=element.Length(),geometry=element.geomType())
    else:report['point_mm']=[point.x,point.y,point.z]
    return report


def _triangle_weights(point,a,b,c):
    px,py=point;ax,ay=a[:2];bx,by=b[:2];cx,cy=c[:2]
    denominator=(by-cy)*(ax-cx)+(cx-bx)*(ay-cy)
    if abs(denominator)<1e-10:return None
    u=((by-cy)*(px-cx)+(cx-bx)*(py-cy))/denominator
    v=((cy-ay)*(px-cx)+(ax-cx)*(py-cy))/denominator
    w=1-u-v
    return (u,v,w) if min(u,v,w)>=-1e-6 else None


def _segment_distance(point,a,b):
    vx,vy=b[0]-a[0],b[1]-a[1];length=vx*vx+vy*vy
    t=max(0,min(1,((point[0]-a[0])*vx+(point[1]-a[1])*vy)/length)) if length else 0
    nearest=(a[0]+t*vx,a[1]+t*vy)
    return math.dist(point,nearest),t


def pick_topology(shape,projector,screen_x,screen_y,kind,max_pixels=9):
    """Вернуть индекс видимого элемента и точку в пространстве модели."""
    point=(screen_x,screen_y);best=None;candidate=None
    visible_face=pick_topology(shape,projector,screen_x,screen_y,'face') if kind in ('edge','vertex') else None
    front_depth=projector(visible_face['point_mm'])[2] if visible_face else None
    if kind=='face':
        for index,face in enumerate(shape.Faces()):
            vertices,triangles=face.tessellate(1.2)
            projected=[projector((v.x,v.y,v.z)) for v in vertices]
            for tri in triangles:
                weights=_triangle_weights(point,*[projected[i] for i in tri])
                if weights is None:continue
                depth=sum(projected[i][2]*w for i,w in zip(tri,weights))
                key=(depth,0)
                if best is None or key<best:
                    world=[sum((vertices[i].x,vertices[i].y,vertices[i].z)[j]*w for i,w in zip(tri,weights)) for j in range(3)]
                    best=key;candidate={'kind':kind,'index':index,'point_mm':world,'screen_distance':0}
    elif kind=='edge':
        for index,edge in enumerate(shape.Edges()):
            samples=edge.sample(24)[0];projected=[projector((v.x,v.y,v.z)) for v in samples]
            for i,(a,b) in enumerate(zip(projected,projected[1:])):
                distance,t=_segment_distance(point,a,b)
                if distance>max_pixels:continue
                depth=a[2]+t*(b[2]-a[2]);key=(distance,depth)
                if front_depth is not None and depth>front_depth+.5:continue
                if best is None or key<best:
                    world=[(samples[i].x,samples[i].y,samples[i].z)[j]*(1-t)+(samples[i+1].x,samples[i+1].y,samples[i+1].z)[j]*t for j in range(3)]
                    best=key;candidate={'kind':kind,'index':index,'point_mm':world,'screen_distance':distance}
    elif kind=='vertex':
        for index,vertex in enumerate(shape.Vertices()):
            center=vertex.Center();world=(center.x,center.y,center.z);p=projector(world)
            distance=math.dist(point,p[:2])
            if distance>max_pixels:continue
            key=(distance,p[2])
            if front_depth is not None and p[2]>front_depth+.5:continue
            if best is None or key<best:
                best=key;candidate={'kind':kind,'index':index,'point_mm':list(world),'screen_distance':distance}
    else:raise ValueError('Режим выбора: face, edge или vertex')
    return candidate


def component_interferences(model,tolerance_mm3=1e-5):
    values=model.rebuild();components=[(f,values[f.id]) for f in model.features if f.kind=='component']
    if len(components)>30:raise ValueError('Слишком много компонентов для анализа')
    collisions=[]
    for i,(a,shape_a) in enumerate(components):
        for b,shape_b in components[i+1:]:
            volume=shape_a.intersect(shape_b).Volume()
            if volume>tolerance_mm3:collisions.append({'a':a.id,'b':b.id,'a_name':a.name,'b_name':b.name,'overlap_mm3':volume})
    return collisions


def vertex_distance(shape_a,index_a,shape_b,index_b):
    a=element_report(shape_a,'vertex',index_a)['point_mm']
    b=element_report(shape_b,'vertex',index_b)['point_mm']
    return math.dist(a,b)


def screen_drag_to_world(dx,dy,scale,azimuth,elevation):
    """Преобразовать перемещение указателя в плоскость вида при неизменной глубине камеры."""
    if scale<=0:raise ValueError('Некорректный масштаб камеры')
    horizontal=dx/scale;vertical=-dy/scale
    pitch_y=vertical*math.sin(elevation)
    return (horizontal*math.cos(azimuth)+pitch_y*math.sin(azimuth),
            -horizontal*math.sin(azimuth)+pitch_y*math.cos(azimuth),
            vertical*math.cos(elevation))
