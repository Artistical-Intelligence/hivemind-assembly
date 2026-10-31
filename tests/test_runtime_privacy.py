"""HA opts out before initialization; this is not a traffic-capture test."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.learning.vectors import OnnxEmbedder


def test_fresh_ha_process_opts_out_before_runtime_import():
    app = Path(__file__).resolve().parents[1] / '_app'
    env = dict(os.environ, PYTHONPATH=str(app), ORT_DISABLE_TELEMETRY='0')
    source = ('import os,sys; import hivemind_assembly; '
              'assert "onnxruntime" not in sys.modules; '
              'print(os.environ["ORT_DISABLE_TELEMETRY"])')
    result = subprocess.run([sys.executable, '-c', source], env=env,
                            capture_output=True, text=True, timeout=10, check=True)
    assert result.stdout.strip() == '1'


def test_owned_native_job_does_not_inherit_telemetry_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv('ORT_DISABLE_TELEMETRY', '0')
    script = 'import os,json; print(json.dumps(os.environ.get("ORT_DISABLE_TELEMETRY")))'
    result = Jobs().run('privacy', [sys.executable, '-c', script], tmp_path)
    assert result['exit_code'] == 0
    assert json.loads(result['output']) == '1'


def test_search_disables_events_before_creating_inference_session(tmp_path, monkeypatch):
    calls = []
    def session(*args, **kwargs):
        assert calls == ['disabled']
        calls.append('session')
        return SimpleNamespace(get_inputs=lambda: [])
    fake = SimpleNamespace(disable_telemetry_events=lambda: calls.append('disabled'),
                           SessionOptions=SimpleNamespace, InferenceSession=session)
    monkeypatch.setitem(sys.modules, 'onnxruntime', fake)
    (tmp_path / 'vocab.txt').write_text('[UNK]\n[CLS]\n[SEP]\nhello\n', encoding='utf-8')
    OnnxEmbedder(tmp_path)
    assert calls == ['disabled', 'session']
