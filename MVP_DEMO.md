# AI-CAD Desktop — проверка MVP

1. На Windows активировать `conda activate aicad-universal`.
2. Выполнить `python -m pytest -q` и сохранить вывод.
3. Выполнить `python run.py`.
4. Создать эскиз прямоугольника 80×50 мм, extrude 8 мм.
5. Изменить длину до 100 мм, проверить перестроение.
6. Добавить отверстие и убедиться, что объём уменьшился.
7. Выполнить допустимую структурированную Offline AI-команду.
8. Выполнить недопустимую команду, проверить rollback.
9. Проверить Undo/Redo, save/reload, экспорт STEP/STL.
10. Выполнить `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1`.
11. Только при успешной сборке запустить `dist\AI-CAD\AI-CAD.exe` на другом Windows без Conda.

**Состояние:** сценарий подготовлен; фактическое выполнение на Windows с этой редакцией не подтверждено.
