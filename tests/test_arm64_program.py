import json
import os
import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest
from native_fixtures import elf_compiler, LINUX_ORACLE
from test_program import example
from hivemind_assembly.core.artifacts import Artifacts
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import program
from hivemind_assembly.domains.reverse_engineering.program_acceptance import ProgramAcceptance

CLANG = os.environ.get('HA_TEST_CLANG') or shutil.which('clang')
pytestmark = pytest.mark.skipif(not CLANG, reason='Clang and LLD required')


def compile_arm(root, manifest):
    built = program.build(root, {**manifest, 'architecture': 'aarch64'}, Jobs(), CLANG)
    assert built['passed'], built
    assert built['architecture'] == 'aarch64'
    return bytes.fromhex(built['elf_hex'])


@pytest.mark.parametrize('optimization', ['O0', 'O2'])
def test_cross_architecture_multifile_stateful_program(tmp_path, optimization):
    manifest = {**example(tmp_path), 'optimization': optimization}
    original = compile_arm(tmp_path, manifest)
    candidate = program.build(tmp_path, example(tmp_path), Jobs(), elf_compiler())
    assert candidate['passed'], candidate
    cases = [{'input_hex': data.hex()} for data in (b'', b'abc', bytes(range(32)), b'\xff' * 32)]
    result = program.compare(original, bytes.fromhex(candidate['elf_hex']), cases)
    assert result['passed'], result
    # An independent integer recurrence checks memory initialization and output.
    for case in cases:
        state, expected = 0, bytearray()
        for value in bytes.fromhex(case['input_hex']):
            state = (state * 3 + value) % 251
            expected.append(state)
        actual = program.replay(original, bytes.fromhex(case['input_hex']))
        assert actual['stdout_hex'] == expected.hex()
    wrong = program.build(tmp_path, example(tmp_path, True), Jobs(), elf_compiler())
    assert wrong['passed']
    assert not program.compare(original, bytes.fromhex(wrong['elf_hex']), cases)['passed']


@LINUX_ORACLE
def test_arm_program_against_actual_native_gcc_process(tmp_path):
    manifest = example(tmp_path)
    arm = compile_arm(tmp_path, manifest)
    native = program.build(tmp_path, manifest, Jobs(), shutil.which('gcc'))
    assert native['passed'], native
    path = tmp_path / 'native-oracle'
    path.write_bytes(bytes.fromhex(native['elf_hex']))
    path.chmod(0o700)
    for data in (b'', b'Hello world', bytes(range(32)), b'\xff' * 32):
        result = subprocess.run([str(path)], input=data, capture_output=True, timeout=5)
        observed = program.replay(arm, data)
        assert observed['status'] == 'completed'
        assert (observed['exit_code'], bytes.fromhex(observed['stdout_hex']), bytes.fromhex(observed['stderr_hex'])) == (result.returncode, result.stdout, result.stderr)


def test_arm_process_inputs_clock_and_memory_errors(tmp_path):
    (tmp_path / 'main.c').write_text('''int ha_main(void){
        long s,ns; if(ha_clock(1,&s,&ns))return 1;
        if(s!=12 || ns!=34 || ha_argc()!=2)return 2;
        const char *p=ha_getenv("VALUE"); if(!p)return 3;
        ha_write(ha_argv(1),3); ha_write(p,3);
        if(ha_file_write(2,"err",3)!=3)return 4;
        if(ha_write((const void*)1,4)!=-14)return 5;
        return 0;
    }''')
    image = compile_arm(tmp_path, {'sources': ['main.c']})
    result = program.replay(image, argv=['target', 'arg'], env={'VALUE': 'env'}, clock_ns=12_000_000_034)
    assert result['status'] == 'completed' and result['exit_code'] == 0, result
    assert bytes.fromhex(result['stdout_hex']) == b'argenv'
    assert bytes.fromhex(result['stderr_hex']) == b'err'
    assert result['events'][-2]['returned'] == -14
    with pytest.raises(ContractError, match='Qiling'):
        program.compare(image, image, [{'files': {'/unexpected': '00'}}])


def assembly_elf(root, source):
    (root / 'input.s').write_text('.text\n.global _start\n_start:\n' + source + '\n')
    subprocess.run([CLANG, '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-static', '-Wl,-e,_start', str(root / 'input.s'), '-o', str(root / 'input.elf')], check=True, capture_output=True)
    return (root / 'input.elf').read_bytes()


@pytest.mark.parametrize('source,status', [
    ('mov x8, #999\nsvc #0', 'unsupported_syscall'),
    ('mov x8, #93\nsvc #1', 'unsupported_cpu_state'),
    ('mrs x0, cntvct_el0\nmov x8, #93\nsvc #0', 'unsupported_cpu_state'),
    ('sub sp, sp, #8\nmov x8, #93\nsvc #0', 'unsupported_cpu_state'),
    ('b .', 'budget_exhausted'),
    ('mov x0, #0\nldr x1, [x0]', 'fault'),
])
def test_arm_program_rejects_unmodeled_effects(tmp_path, source, status):
    image = assembly_elf(tmp_path, source)
    result = program.replay(image, max_instructions=100)
    assert result['status'] == status, result
    assert result['exit_code'] is None


def test_arm_program_cancel_and_protected_cross_architecture_acceptance(tmp_path, store):
    loop = assembly_elf(tmp_path, 'b .')
    cancel = threading.Event()
    cancel.set()
    assert program.replay(loop, max_instructions=10000, cancel=cancel)['status'] == 'cancelled'
    manifest = example(tmp_path)
    original = compile_arm(tmp_path, manifest)
    (tmp_path / 'original.elf').write_bytes(original)
    (tmp_path / 'build.json').write_text(json.dumps(manifest))
    task = store.create_project('ARM application', 'Recover a static application')
    artifacts = Artifacts(store)
    context = SimpleNamespace(jobs=Jobs(), config={'foundations': {'c_compiler': CLANG}}, cancel=threading.Event())
    spec = {'scope': 'linux_program', 'original_path': 'original.elf', 'manifest_path': 'build.json', 'cases': [{'input_hex': ''}, {'input_hex': '616263'}]}
    verifier = ProgramAcceptance()
    contract = verifier.prepare(tmp_path, spec, artifacts, task['project_id'], context)
    (tmp_path / 'original.elf').write_bytes(b'edited source must not replace oracle')
    assert verifier.verify(tmp_path, contract, artifacts, task['project_id'], context)['passed']
    (tmp_path / 'build.json').write_text(json.dumps({**manifest, 'architecture': 'aarch64'}))
    assert verifier.verify(tmp_path, contract, artifacts, task['project_id'], context)['passed']
    example(tmp_path, True)
    assert not verifier.verify(tmp_path, contract, artifacts, task['project_id'], context)['passed']
    with pytest.raises(Blocked, match='architecture'):
        program.load_image(original)  # Existing default remains x86-64.
