"""Статическая проверка ограничений конфигурации Windows-сборки."""
from pathlib import Path
import unittest

class WindowsBuildConfigTests(unittest.TestCase):
    def test_excludes_unneeded_qtwebengine(self):
        script = (Path(__file__).resolve().parents[1] / 'build_windows.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn("'--collect-all', 'PySide6'", script)
        for module in ('PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick'):
            self.assertIn("'--exclude-module', '" + module + "'", script)

if __name__ == '__main__':
    unittest.main()
