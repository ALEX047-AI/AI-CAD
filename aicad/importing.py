"""Импорт STEP с использованием встроенных ограниченных по размеру данных BREP OpenCascade."""
from __future__ import annotations

import base64
import tempfile
import zlib
from pathlib import Path

import cadquery as cq

MAX_COMPRESSED=700_000
MAX_BREP=5_000_000


def encode_step(path):
    path=Path(path)
    if path.suffix.lower() not in ('.step','.stp'):raise ValueError('Для импорта выберите STEP (.step/.stp)')
    if not path.is_file() or not 0<path.stat().st_size<20_000_000:raise ValueError('STEP отсутствует или слишком велик')
    work=cq.importers.importStep(str(path));solids=[]
    for item in work.vals():solids.extend(item.Solids())
    if not solids:raise ValueError('STEP не содержит объёмных тел')
    shape=cq.Compound.makeCompound(solids)
    if not shape.isValid():raise ValueError('STEP содержит некорректную геометрию')
    with tempfile.TemporaryDirectory() as directory:
        brep=Path(directory)/'part.brep';shape.exportBrep(str(brep));raw=brep.read_bytes()
    if len(raw)>MAX_BREP:raise ValueError('Импортируемая геометрия слишком велика для проекта')
    compressed=zlib.compress(raw,9)
    if len(compressed)>MAX_COMPRESSED:raise ValueError('Импортируемая геометрия слишком велика для проекта')
    return base64.b64encode(compressed).decode('ascii')


def decode_brep(data):
    if not isinstance(data,str) or len(data)>4*MAX_COMPRESSED//3+8:raise ValueError('Некорректные данные импортированного тела')
    try:
        compressed=base64.b64decode(data,validate=True)
        if len(compressed)>MAX_COMPRESSED:raise ValueError('Слишком большой BREP')
        decoder=zlib.decompressobj();raw=decoder.decompress(compressed,MAX_BREP+1)
        if len(raw)>MAX_BREP or not decoder.eof or decoder.unused_data:raise ValueError('Некорректный или слишком большой BREP')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'part.brep';path.write_bytes(raw)
            shape=cq.importers.importBrep(str(path)).val()
        if not shape.isValid() or not shape.Solids():raise ValueError('Импортированное тело повреждено')
        return shape
    except (ValueError,zlib.error,TypeError) as exc:raise ValueError('Не удалось прочитать импортированное тело') from exc
