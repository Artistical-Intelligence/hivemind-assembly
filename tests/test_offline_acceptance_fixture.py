"""A fresh acceptance root must not depend on a previous HA preparation run."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dev'))
from verify_offline_install import preservation_fixture


def test_fresh_private_folder_is_created(tmp_path):
    root = tmp_path / 'new-owner'
    path = preservation_fixture(root)
    assert path == root / 'private/offline-preservation-canary.txt'
    assert path.read_text() == 'retained-local-owner-data'


def test_existing_canary_is_never_replaced(tmp_path):
    path = preservation_fixture(tmp_path)
    path.write_text('previous-preserved-data')
    with pytest.raises(FileExistsError):
        preservation_fixture(tmp_path)
    assert path.read_text() == 'previous-preserved-data'
