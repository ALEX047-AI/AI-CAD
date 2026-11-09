import json, tempfile, unittest
from pathlib import Path
import cadquery as cq
from aicad.core import new_spec, build, parse_offline, export_model
from aicad.project import Project, save, load

class ProjectTests(unittest.TestCase):
 def test_new_solids(self):
  for kind in ('box','cylinder','sphere','plate','bracket','enclosure'):
   solid=build(new_spec(kind));self.assertTrue(solid.isValid());self.assertGreater(solid.Volume(),0)
 def test_offline_and_history(self):
  p=Project();item=p.add(new_spec('box'));p.add(parse_offline('Добавь цилиндр диаметром 20 мм и высотой 40 мм'))
  p.select(item.id);p.update(item.id,new_spec('box',height=35));self.assertEqual(p.selected().spec.parameters['height'],35)
  self.assertTrue(p.undo());self.assertEqual(p.selected().spec.parameters['height'],30)
  self.assertTrue(p.redo());self.assertEqual(p.selected().spec.parameters['height'],35)
  p.remove(item.id);self.assertEqual(len(p.items),1);p.undo();self.assertEqual(len(p.items),2)
 def test_roundtrip_and_export(self):
  p=Project();p.add(new_spec('plate',hole_count=4,hole_diameter=6));p.add(new_spec('cylinder'))
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory);save(path/'p.aicad.json',p);q=load(path/'p.aicad.json')
   self.assertEqual(q.to_dict(),p.to_dict())
   for ext in ('step','stl'):
    output=export_model(q.combined_solid(),path/('scene.'+ext));self.assertGreater(output.stat().st_size,100)
   shape=cq.importers.importStep(str(path/'scene.step')).val();self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),2)
 def test_old_project_and_invalid(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'old.json';path.write_text(json.dumps(new_spec('plate').to_dict()))
   self.assertEqual(len(load(path).items),1)
   with self.assertRaises(ValueError):Project.from_dict({'schema_version':99})
   with self.assertRaises(ValueError):new_spec('cylinder',diameter=-1)

if __name__=='__main__':unittest.main()
