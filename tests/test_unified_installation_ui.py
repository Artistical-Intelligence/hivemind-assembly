"""One preparation surface and honest readiness across both dashboard views."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

STATIC = Path(__file__).resolve().parents[1] / '_app/hivemind_assembly/application/static'
NODE = shutil.which('node')


@pytest.mark.skipif(not NODE, reason='requires Node to execute the real UI function')
@pytest.mark.parametrize('state,ready,busy,phrase', [
    ({}, False, False, 'Prepare HA'),
    ({'foundations': {'ready': True}}, False, False, 'configured'),
    ({'experience': {'installation': {'state': 'ready'}}}, True, False, 'checked'),
    ({'experience': {'installation': {'state': 'preparing'}}}, False, True, 'Preparing'),
    ({'experience': {'installation': {'state': 'checking'}}}, False, True, 'checking'),
    ({'experience': {'installation': {'state': 'repairing'}}}, False, True, 'checking'),
    ({'experience': {'installation': {'state': 'interrupted'}}}, False, False, 'Resume'),
    ({'experience': {'installation': {'state': 'failed'}}}, False, False, 'attention'),
    ({'experience': {'installation': {'state': 'needs_attention'}}}, False, False, 'attention'),
    ({'experience': {'installation': {'state': 'ready', 'packages': {'error': 'invalid'}}}}, False, False, 'attention'),
    ({'experience': {'installation': {'state': 'ready', 'busy': True}}}, False, True, 'Preparing'),
    ({'foundations': {'ready': True, 'installing': True}}, False, True, 'Preparing'),
    ({'experience': {'installation': {'state': 'ready'}},
      'jobs': {'owned': {'name': 'HA installation check', 'status': 'running'}}}, False, True, 'Preparing'),
    ({'experience': {'installation': {'state': 'ready'}},
      'jobs': {'unrelated': {'name': 'Project build', 'status': 'running'}}}, True, False, 'checked'),
])
def test_actual_ui_readiness_function(state, ready, busy, phrase):
    source = (STATIC / 'app.js').read_text(encoding='utf-8')
    function = source[source.index('function installationSummary(s){'):source.index('function renderSetup(s){')]
    script = ('const vm=require("node:vm"); const fs=require("node:fs"); '
              'const input=JSON.parse(fs.readFileSync(0,"utf8")); '
              'const ctx=vm.createContext({state:input.state}); '
              'vm.runInContext(input.function,ctx,{timeout:1000}); '
              'console.log(JSON.stringify(vm.runInContext("installationSummary(state)",ctx,{timeout:1000})));')
    result = subprocess.run([NODE, '-e', script],
                            input=json.dumps({'function': function, 'state': state}),
                            text=True, capture_output=True, timeout=5, check=True)
    value = json.loads(result.stdout)
    assert value['ready'] is ready
    assert value['busy'] is busy
    assert phrase in value['text']


def test_legacy_analysis_controls_are_collapsed_not_removed():
    source = (STATIC / 'index.html').read_text(encoding='utf-8')
    start = source.index('<details id="ha-analysis-advanced">')
    details = source[start:source.index('</details>', start)]
    assert '<summary>Advanced analysis diagnostics</summary>' in details
    assert 'id="install"' in details and 'id="verify-foundations"' in details
    assert '<details id="ha-analysis-advanced" open' not in source
    assert 'id="ha-experience"' in source
    assert 'Prepare HA in Settings.' in source


def test_primary_and_advanced_statuses_share_one_state_function():
    app = (STATIC / 'app.js').read_text(encoding='utf-8')
    unified = (STATIC / 'unified.js').read_text(encoding='utf-8')
    assert 'local=installationSummary(s)' in app
    assert 'const installation=installationSummary(state)' in unified
    assert 'Run analysis setup below' not in unified
    assert 'The download is large' not in app
    assert 'All tools are installed.' not in app


@pytest.mark.skipif(not NODE, reason='requires Node syntax validation')
@pytest.mark.parametrize('name', ['app.js', 'unified.js'])
def test_ui_scripts_remain_valid_javascript(name):
    subprocess.run([NODE, '--check', str(STATIC / name)], capture_output=True,
                   text=True, check=True, timeout=10)
