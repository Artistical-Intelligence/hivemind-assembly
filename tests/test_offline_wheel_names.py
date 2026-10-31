"""Wheel distribution normalization does not change version or integrity rules."""
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dev'))
from assemble_offline import locked_wheels


@pytest.mark.parametrize('distribution', ['jaraco.classes', 'jaraco_classes', 'Jaraco.Classes'])
@pytest.mark.parametrize('requirement', ['jaraco-classes', 'jaraco.classes', 'jaraco_classes'])
def test_legal_dotted_wheel_matches_canonical_requirement(tmp_path, distribution, requirement):
    wheel = tmp_path / (distribution + '-3.4.0-py3-none-any.whl')
    wheel.write_bytes(b'inert-package-fixture')
    expected = hashlib.sha256(wheel.read_bytes()).hexdigest()
    lock = tmp_path / 'requirements.lock'
    lock.write_text(requirement + '==3.4.0 --hash=sha256:' + expected + '\n')
    assert locked_wheels(lock, tmp_path) == [(wheel, expected)]


def test_normalization_never_accepts_wrong_bytes(tmp_path):
    wheel = tmp_path / 'jaraco.classes-3.4.0-py3-none-any.whl'
    wheel.write_bytes(b'changed')
    lock = tmp_path / 'requirements.lock'
    lock.write_text('jaraco-classes==3.4.0 --hash=sha256:' + '0' * 64 + '\n')
    with pytest.raises(ValueError, match='pinned lock'):
        locked_wheels(lock, tmp_path)


def test_normalization_never_accepts_wrong_version(tmp_path):
    wheel = tmp_path / 'jaraco.classes-3.5.0-py3-none-any.whl'
    wheel.write_bytes(b'same-package-fixture')
    lock = tmp_path / 'requirements.lock'
    lock.write_text('jaraco-classes==3.4.0 --hash=sha256:' + hashlib.sha256(wheel.read_bytes()).hexdigest() + '\n')
    with pytest.raises(ValueError, match='packages missing'):
        locked_wheels(lock, tmp_path)
