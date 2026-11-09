"""Регрессионные проверки геометрии при изменении топологии, сборок и параметров."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cadquery as cq

from aicad.commands import execute
from aicad.core import export_model
from aicad.inspection import (component_interferences, element_report,
                              pick_topology, shape_report, vertex_distance,screen_drag_to_world)
from aicad.universal import Model, load_model, save_model
import aicad.universal_ai as ai


class TopologyAndAssemblyTests(unittest.TestCase):
    def test_pick_real_faces_edges_vertices_and_measure(self):
        model=Model();model.add('box',{'length':40,'width':30,'height':10})
        shape=model.solid()
        projector=lambda xyz:(xyz[0],xyz[1],-xyz[2])
        top=pick_topology(shape,projector,0,0,'face')
        self.assertIsNotNone(top)
        self.assertAlmostEqual(element_report(shape,'face',top['index'])['center_mm'][2],10)
        self.assertIsNotNone(pick_topology(shape,projector,20,0,'edge'))
        self.assertIsNotNone(pick_topology(shape,projector,20,15,'vertex'))
        self.assertGreater(vertex_distance(shape,0,shape,1),0)
        report=shape_report(shape)
        self.assertEqual(report['solid_count'],1)
        self.assertAlmostEqual(report['volume_mm3'],12000)

    def test_face_hole_at_picked_location_and_index_validation(self):
        model=Model();base=model.add('box',{'length':60,'width':40,'height':12})
        face_index=next(i for i,f in enumerate(model.rebuild()[base].Faces())
                        if f.geomType()=='PLANE' and f.normalAt().z>.9)
        before=model.solid().Volume()
        hole=model.add('face_hole',{'face_index':face_index,'radius':3,'depth':12,'u':8,'v':5},[base])
        self.assertAlmostEqual(before-model.solid().Volume(),3.141592653589793*9*12,places=3)
        snapshot=model.to_dict()
        with self.assertRaises(ValueError):model.update(hole,params={'face_index':500,'radius':3,'depth':12,'u':0,'v':0})
        self.assertEqual(snapshot,model.to_dict())
        with self.assertRaises(ValueError):model.add('face_hole',{'face_index':face_index,'radius':2,'depth':5,'u':500,'v':0},[base])

    def test_addressed_edges_and_face_shell(self):
        m=Model();base=m.add('box',{'length':60,'width':40,'height':20})
        edge=m.add('edge_fillet',{'radius':2,'edge_indices':[0]},[base])
        self.assertLess(m.solid().Volume(),m.rebuild()[base].Volume())
        m.add('edge_chamfer',{'radius':1,'edge_indices':[0]},[edge]);self.assertTrue(m.solid().isValid())
        shell=Model();base=shell.add('box',{'length':60,'width':40,'height':20})
        top=next(i for i,f in enumerate(shell.rebuild()[base].Faces()) if f.normalAt().z>.9)
        shell.add('face_shell',{'thickness':2,'face_index':top},[base])
        self.assertTrue(shell.solid().isValid())
        self.assertLess(shell.solid().Volume(),60*40*20)

    def test_components_interference_undo_rebuild_save_and_export(self):
        m=Model();m.set_parameter('span',40);m.set_parameter('reach','span+20')
        base=m.add('box',{'length':'reach','width':20,'height':10})
        left=m.add('component',{'translation':[0,0,0],'rotation':[0,0,0]},[base],name='left')
        right=m.add('component',{'translation':['reach+5',0,0],'rotation':[0,0,0]},[base],name='right')
        assembly=m.add('assembly',{},[left,right])
        self.assertEqual(len(m.rebuild()[assembly].Solids()),2)
        self.assertEqual(component_interferences(m),[])
        self.assertAlmostEqual(m.solid().BoundingBox().xlen,125)
        m.set_parameter('span',50);self.assertAlmostEqual(m.solid().BoundingBox().xlen,145)
        m.undo();self.assertAlmostEqual(m.solid().BoundingBox().xlen,125)
        m.redo();self.assertAlmostEqual(m.solid().BoundingBox().xlen,145)
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory);save_model(directory/'assembly.aicad.json',m)
            loaded=load_model(directory/'assembly.aicad.json')
            self.assertEqual([f.kind for f in loaded.features],[f.kind for f in m.features])
            self.assertAlmostEqual(loaded.solid().Volume(),m.solid().Volume())
            for ext in ('step','stl'):
                path=export_model(loaded.solid(),directory/('assembly.'+ext))
                self.assertGreater(path.stat().st_size,100)
            self.assertTrue(cq.importers.importStep(str(directory/'assembly.step')).val().isValid())

    def test_interference_and_atomic_ai_use_same_operations(self):
        m=Model();base=m.add('box',{'length':20,'width':20,'height':10})
        commands=[{'action':'add','kind':'component','params':{'translation':[0,0,0],'rotation':[0,0,0]},'refs':[base],'alias':'one'},
                  {'action':'add','kind':'component','params':{'translation':[10,0,0],'rotation':[0,0,0]},'refs':[base],'alias':'two'},
                  {'action':'add','kind':'assembly','params':{},'refs':['one','two']}]
        execute(m,commands)
        self.assertAlmostEqual(component_interferences(m)[0]['overlap_mm3'],2000)
        self.assertTrue(all(f.source=='ai' for f in m.features[1:]))
        snapshot=m.to_dict()
        with self.assertRaises(ValueError):execute(m,[{'action':'add','kind':'component','params':{'translation':[0,0,0],'rotation':[0,0,0]},'refs':[base]},
                                                  {'action':'add','kind':'face_hole','params':{'face_index':500,'radius':3,'depth':4,'u':0,'v':0},'refs':[base]}])
        self.assertEqual(snapshot,m.to_dict())

    def test_parameter_cycle_rejected_without_corrupting_model(self):
        m=Model();m.set_parameter('a',10);m.set_parameter('b','a*2')
        m.add('box',{'length':'b','width':10,'height':10})
        self.assertAlmostEqual(m.solid().Volume(),2000)
        with self.assertRaisesRegex(ValueError,'Циклическая'):m.set_parameter('a','b+1')
        self.assertEqual(m.parameters['a'],10)

    def test_arbitrary_sketch_plane_and_vector_hole(self):
        m=Model();profile=m.add('sketch',{'plane':{'normal':[0,1,1],'x_dir':[1,0,0]},
                         'origin':[0,0,5],'entities':[{'type':'rectangle','center':[0,0],'width':20,'height':10}]})
        m.add('extrude',{'distance':8},[profile]);self.assertAlmostEqual(m.solid().Volume(),1600)
        with self.assertRaises(ValueError):Model().add('sketch',{'plane':{'normal':[0,0,1],'x_dir':[0,0,1]},'entities':[]})
        h=Model();base=h.add('box',{'length':40,'width':40,'height':20})
        h.add('hole',{'center':[0,-20,10],'radius':3,'depth':40,'axis':[0,1,0]},[base])
        self.assertLess(h.solid().Volume(),40*40*20)
        self.assertTrue(h.solid().isValid())

    def test_portable_step_import_and_invalid_embedded_data(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);step=folder/'input.step'
            cq.exporters.export(cq.Workplane('XY').box(20,10,5).val(),str(step))
            m=Model();imported=m.import_step(step)
            save_model(folder/'portable.aicad.json',m);step.unlink()
            loaded=load_model(folder/'portable.aicad.json')
            self.assertAlmostEqual(loaded.solid().Volume(),1000)
            loaded.add('hole',{'center':[0,0,-2.5],'radius':2,'depth':5,'axis':'Z'},[imported])
            self.assertLess(loaded.solid().Volume(),1000)
            with self.assertRaises(ValueError):Model().add('import_brep',{'data':'malformed'})

    def test_screen_plane_drag_geometry(self):
        moved=screen_drag_to_world(30,-20,10,0,0)
        self.assertEqual(tuple(round(v,4) for v in moved),(3,0,2))
        self.assertAlmostEqual(sum(v*v for v in screen_drag_to_world(30,-20,10,.5,.7))**.5,(3**2+2**2)**.5)

    def test_ai_receives_selected_topology_and_explains_valid_plan(self):
        m=Model();base=m.add('box',{'length':40,'width':30,'height':10})
        face=next(i for i,f in enumerate(m.rebuild()[base].Faces()) if f.normalAt().z>.9)
        result=json.dumps({'commands':[{'action':'add','kind':'face_hole','params':{'face_index':face,'radius':2,'depth':10,'u':0,'v':0},'refs':[base]}],
                           'explanation':'Отверстие в верхней грани'},ensure_ascii=False)
        calls=[]
        def post(url,headers=None,json=None,timeout=None):
            calls.append(json)
            return SimpleNamespace(status_code=200,json=lambda:{'choices':[{'message':{'content':result}}]},raise_for_status=lambda:None)
        config={'cloud_url':'https://api.mistral.ai/v1','cloud_model':'mistral-large-latest','api_key':'MOCK_TOKEN',
                'consent':True,'fallback':False,'selected_id':base,'selected_topology':(base,'face',face)}
        status=[]
        with patch.dict(os.environ,{'MISTRAL_API_KEY':'MOCK_TOKEN'}),patch.object(ai,'requests',SimpleNamespace(post=post)):
            commands,provider=ai.request_commands('Добавь отверстие в выбранной грани','Mistral',m,config,status.append)
        self.assertEqual(provider,'Mistral')
        self.assertIn('selected_feature_id',calls[0]['messages'][1]['content'])
        self.assertTrue(any('Отверстие в верхней грани' in value for value in status))
        execute(m,commands);self.assertLess(m.solid().Volume(),12000)

    def test_ai_context_omits_embedded_brep_and_can_edit_import(self):
        with tempfile.TemporaryDirectory() as directory:
            step=Path(directory)/'source.step'
            cq.exporters.export(cq.Workplane('XY').box(12,10,8).val(),str(step))
            model=Model();imported=model.import_step(step)
            response=json.dumps({'commands':[{'action':'add','kind':'transform','params':{'translation':[20,0,0],'rotation':[0,0,0]},'refs':[imported]}]})
            calls=[]
            def post(url,headers=None,json=None,timeout=None):
                calls.append(json)
                return SimpleNamespace(status_code=200,json=lambda:{'choices':[{'message':{'content':response}}]},raise_for_status=lambda:None)
            config={'consent':True,'fallback':False,'cloud_url':'https://api.mistral.ai/v1','cloud_model':'mistral-large-latest'}
            with patch.dict(os.environ,{'MISTRAL_API_KEY':'MOCK_TOKEN'}),patch.object(ai,'requests',SimpleNamespace(post=post)):
                commands,_=ai.request_commands('Перемести импортированный компонент на 20 мм','Mistral',model,config)
            prompt=calls[0]['messages'][1]['content']
            self.assertIn('embedded_geometry',prompt)
            self.assertNotIn(model.features[0].params['data'],prompt)
            execute(model,commands)
            self.assertAlmostEqual(model.solid().BoundingBox().xmin,14)


if __name__=='__main__':unittest.main()
