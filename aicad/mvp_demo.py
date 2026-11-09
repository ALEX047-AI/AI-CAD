"""Воспроизводимая офлайн-демонстрация параметрического CAD без GUI и API."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import cadquery as cq
from .commands import execute
from .universal import Model, load_model, save_model
from .universal_ai import request_commands


def run(output_dir: str | Path) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    model = Model()
    model.set_parameter('length', 80)
    sketch = model.add('sketch', {'plane': 'XY', 'entities': [{'type': 'rectangle', 'center': [0, 0], 'width': 'length', 'height': 40}]}, name='Основание корпуса')
    body = model.add('extrude', {'distance': 8}, [sketch], name='Основание 8 мм')
    command = json.dumps({'commands': [{'action': 'add', 'kind': 'hole', 'params': {'center': [20, 0, 0], 'radius': 4, 'depth': 8, 'axis': 'Z'}, 'refs': [body], 'alias': 'mount_hole'}]})
    commands, provider = request_commands(command, 'Offline', model, {})
    execute(model, commands)
    initial_volume = model.solid().Volume()
    model.set_parameter('length', 100)
    updated_volume = model.solid().Volume()
    if updated_volume <= initial_volume:
        raise RuntimeError('Параметрическое перестроение не изменило объём')
    before = model.to_dict()
    try:
        execute(model, [{'action': 'add', 'kind': 'box', 'params': {'length': -1, 'width': 10, 'height': 10}}])
    except ValueError:
        pass
    else:
        raise RuntimeError('Недопустимая CAD-команда была выполнена')
    if model.to_dict() != before:
        raise RuntimeError('Недопустимая команда повредила проект')
    project_path = out / 'mvp.aicad.json'
    save_model(project_path, model)
    restored = load_model(project_path)
    if abs(restored.solid().Volume() - updated_volume) > 1e-5:
        raise RuntimeError('Ошибка восстановления проекта')
    step_path = out / 'mvp.step'
    stl_path = out / 'mvp.stl'
    cq.exporters.export(restored.solid(), str(step_path))
    cq.exporters.export(restored.solid(), str(stl_path))
    imported = cq.importers.importStep(str(step_path)).val()
    if not imported.isValid() or abs(imported.Volume() - updated_volume) > 1e-3:
        raise RuntimeError('STEP roundtrip не прошёл')
    report = {'status': 'ok', 'provider': provider, 'features': len(restored.features), 'initial_volume_mm3': initial_volume, 'updated_volume_mm3': updated_volume, 'invalid_command_rejected': True, 'project_roundtrip': True, 'step_roundtrip': True, 'files': [project_path.name, step_path.name, stl_path.name]}
    (out / 'mvp_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description='Проверка офлайн-сценария AI-CAD Desktop')
    parser.add_argument('--output', default='demo_output/mvp', help='Каталог для результатов')
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
