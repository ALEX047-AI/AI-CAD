import tempfile
from pathlib import Path
from aicad.mvp_demo import run


def test_mvp_offline_roundtrip():
    with tempfile.TemporaryDirectory() as directory:
        report = run(directory)
        assert report['status'] == 'ok'
        assert report['provider'] == 'Offline'
        assert report['invalid_command_rejected']
        assert report['updated_volume_mm3'] > report['initial_volume_mm3']
        assert all((Path(directory) / name).stat().st_size > 0 for name in report['files'])
