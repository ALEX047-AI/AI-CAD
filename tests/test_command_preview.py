"""Регрессия предварительной проверки AI-команд без изменения проекта."""
import pytest

from aicad.commands import execute, preview
from aicad.universal import Model


def test_preview_does_not_mutate_model_or_history():
    model = Model()
    model.add('box', {'length': 20, 'width': 10, 'height': 5})
    before = model.to_dict()
    undo_before = len(model._undo)
    redo_before = len(model._redo)
    result = preview(model, [{'action': 'set_parameter', 'name': 'length', 'value': 40}])
    assert result['project']['parameters']['length'] == 40
    assert model.to_dict() == before
    assert len(model._undo) == undo_before
    assert len(model._redo) == redo_before


def test_preview_rejects_invalid_geometry_without_mutation():
    model = Model()
    model.add('box', {'length': 20, 'width': 10, 'height': 5})
    before = model.to_dict()
    with pytest.raises(ValueError):
        preview(model, [{'action': 'add', 'kind': 'box', 'params': {'length': -1, 'width': 10, 'height': 10}}])
    assert model.to_dict() == before


def test_preview_matches_real_execution_and_undo():
    model = Model()
    commands = [{'action': 'add', 'kind': 'box', 'params': {'length': 20, 'width': 10, 'height': 5}}]
    predicted = preview(model, commands)
    assert not model.features
    execute(model, commands)
    assert model.to_dict() == predicted['project'] or (
        len(model.features) == predicted['features_count']
        and abs(model.solid().Volume() - predicted['volume_mm3']) < 1e-6
    )
    assert model.undo()
    assert not model.features
