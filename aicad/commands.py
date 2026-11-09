"""Общий протокол команд интерфейса и ИИ. Пакет операций выполняется атомарно."""
from __future__ import annotations
from copy import deepcopy
from .universal import Model, KINDS


def execute(model:Model,commands:list[dict]):
    if not isinstance(commands,list) or not 1<=len(commands)<=30:raise ValueError('Ожидается 1–30 CAD-команд')
    before=model._snapshot();old_undo=deepcopy(model._undo);old_redo=deepcopy(model._redo)
    aliases={};results=[]
    try:
        for command in commands:
            if not isinstance(command,dict) or len(command)>8:raise ValueError('Некорректная CAD-команда')
            action=command.get('action')
            if action=='add':
                if set(command)-{'action','kind','params','refs','name','alias','source'}:raise ValueError('Неизвестное поле add')
                kind=command.get('kind');params=command.get('params');refs=command.get('refs',[])
                if kind not in KINDS or not isinstance(params,dict) or not isinstance(refs,list):raise ValueError('Некорректная операция add')
                refs=[aliases.get(r,r) for r in refs]
                alias=command.get('alias')
                if alias is not None and (not isinstance(alias,str) or not alias.isidentifier() or alias in aliases):raise ValueError('Некорректный псевдоним')
                source=command.get('source','ai')
                result=model.add(kind,params,refs,command.get('name'),source)
                if alias is not None:aliases[alias]=result
                results.append(result)
            elif action=='update':
                if set(command)-{'action','id','params','refs','name','visible'}:raise ValueError('Неизвестное поле update')
                node_id=aliases.get(command.get('id'),command.get('id'))
                if not isinstance(node_id,str) or not any(k in command for k in ('params','refs','name','visible')):raise ValueError('Укажите узел и изменение')
                refs=command.get('refs')
                if refs is not None:
                    if not isinstance(refs,list):raise ValueError('Некорректные ссылки update')
                    refs=[aliases.get(ref,ref) for ref in refs]
                model.update(node_id,params=command.get('params'),refs=refs,name=command.get('name'),visible=command.get('visible'))
                results.append(node_id)
            elif action=='remove':
                if set(command)!={'action','id'}:raise ValueError('Некорректная команда remove')
                node_id=aliases.get(command['id'],command['id']);model.remove(node_id);results.append(node_id)
            elif action=='set_parameter':
                if set(command)!={'action','name','value'}:raise ValueError('Некорректная команда set_parameter')
                model.set_parameter(command['name'],command['value']);results.append(command['name'])
            else:raise ValueError('Неизвестная CAD-команда')
        # Один пакет команд соответствует одному действию отмены.
        model._undo=old_undo+[before];model._redo=[]
        return results
    except Exception:
        model.parameters,model.features=before;model._undo=old_undo;model._redo=old_redo
        raise


def preview(model: Model, commands: list[dict]) -> dict:
    """Проверить пакет CAD-команд на независимой копии модели.

    Не меняет исходную модель, историю Undo/Redo или параметры.
    Возвращает результат и геометрические характеристики будущей модели.
    """
    candidate = Model.from_dict(model.to_dict())
    results = execute(candidate, commands)
    solids = candidate.visible_solids()
    total_volume = sum(shape.Volume() for _, shape in solids)
    return {
        'results': results,
        'features_count': len(candidate.features),
        'solids_count': len(solids),
        'volume_mm3': total_volume,
        'project': candidate.to_dict(),
    }
