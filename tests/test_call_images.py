import ctypes
import json
import random
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.artifacts import Artifacts
from hivemind_assembly.domains.reverse_engineering import call_images as calls
from hivemind_assembly.domains.reverse_engineering.call_acceptance import CallAcceptance

CLANG = shutil.which('clang') or '/root/.clang-tool-chain/clang/linux/x86_64/bin/clang'
SOURCE = '''extern unsigned mix(unsigned);
unsigned recovered(unsigned *p, unsigned n, unsigned salt, unsigned a, unsigned b, unsigned c, unsigned d) {
 unsigned result=a+2*b+3*c+4*d;
 for(unsigned i=0;i<n;i++){p[i]=mix(p[i]^salt);result+=p[i];}
 return result;
}'''
HELPER = 'unsigned mix(unsigned x){return (x*33u)^(x>>7);}'


@pytest.fixture
def images(tmp_path):
    (tmp_path/'main.c').write_text(SOURCE)
    (tmp_path/'helper.c').write_text(HELPER)
    manifest={'sources':['main.c','helper.c']}
    result={}
    for abi in ('sysv','win64'):
        build=calls.build(tmp_path,manifest,'recovered',abi,Jobs(),CLANG)
        assert build['passed'],build
        result[abi]=(bytes.fromhex(build['image_hex']),calls.load(bytes.fromhex(build['image_hex']),symbol='recovered'))
    return result


def test_both_abis_linked_calls_and_buffers_match_independent_native_oracle(images,tmp_path):
    # Independent GCC/native execution rather than comparing two Unicorn runs alone.
    if not shutil.which('gcc'):
        pytest.skip('Native GCC oracle unavailable')
    native=tmp_path/'oracle.so'
    subprocess.run(['gcc','-shared','-fPIC','-O0',str(tmp_path/'main.c'),str(tmp_path/'helper.c'),'-o',str(native)],check=True)
    library=ctypes.CDLL(str(native))
    library.recovered.argtypes=[ctypes.POINTER(ctypes.c_uint),*[ctypes.c_uint]*6]
    library.recovered.restype=ctypes.c_uint
    rng=random.Random(42)
    cases=[]
    for n in (0,1,2,7,16,63):
        values=[rng.getrandbits(32) for _ in range(max(1,n))]
        buf=(ctypes.c_uint*len(values))(*values)
        salt=rng.getrandbits(32)
        expected=library.recovered(buf,n,salt,11,22,33,44)
        initial=b''.join(v.to_bytes(4,'little') for v in values).hex()
        case={'arguments':[{'buffer':'data'},n,salt,11,22,33,44], 'buffers':[{'id':'data','hex':initial}], 'output_bits':32}
        cases.append(case)
        for _,image in images.values():
            result=calls.execute(image,case)
            assert result['status']=='completed' and result['abi_ok'],result
            assert result['value']==expected
            assert result['buffers']['data']==bytes(buf).hex()
    assert calls.compare(images['win64'][1],images['sysv'][1],cases)['passed']


def test_buffer_aliasing_bounds_and_readonly(tmp_path):
    (tmp_path/'f.c').write_text('unsigned f(unsigned *a,unsigned *b){*a+=1;*b+=2;return *a;}')
    for abi in ('sysv','win64'):
        built=calls.build(tmp_path,{'sources':['f.c']},'f',abi,Jobs(),CLANG)
        image=calls.load(bytes.fromhex(built['image_hex']),symbol='f')
        case={'arguments':[{'buffer':'b'},{'buffer':'b'}],'buffers':[{'id':'b','hex':'03000000'}],'output_bits':32}
        assert calls.execute(image,case)['value']==6
        case['buffers'][0]['permissions']='r'
        assert calls.execute(image,case)['status']!='completed'
        case['buffers'][0]={'id':'b','hex':'03'}
        assert calls.execute(image,case)['status']!='completed'


def test_nonvolatile_simd_registers_are_verified():
    # pxor xmm6,xmm6; xor eax,eax; ret
    image={'abi':'win64','entry':0x10000,'segments':[{'address':0x10000,'size':7,'hex':'660fefF631c0c3','permissions':'rx'}]}
    result=calls.execute(image,{'arguments':[]})
    assert result['status']=='completed' and not result['abi_ok']


def test_mutable_image_state_cannot_escape_observation(tmp_path):
    (tmp_path/'f.c').write_text('unsigned x=7;unsigned f(void){return x++;}')
    built=calls.build(tmp_path,{'sources':['f.c']},'f','win64',Jobs(),CLANG)
    assert calls.execute(calls.load(bytes.fromhex(built['image_hex']),symbol='f'),{})['status']!='completed'


def test_hidden_cases_pinned_and_rebuilt(images,store,tmp_path):
    artifacts=Artifacts(store)
    project=store.create_project('linked','reconstruct')['project_id']
    (tmp_path/'original.dll').write_bytes(images['win64'][0])
    (tmp_path/'manifest.json').write_text(json.dumps({'sources':['main.c','helper.c']}))
    case={'arguments':[{'buffer':'b'},1,2,3,4,5,6],'buffers':[{'id':'b','hex':'01000000'}],'output_bits':32}
    import threading
    context=SimpleNamespace(jobs=Jobs(),config={'foundations':{'c_compiler':CLANG}},cancel=threading.Event())
    verifier=CallAcceptance()
    contract=verifier.prepare(tmp_path,{'scope':'x86_64_linked_calls','original_path':'original.dll',
        'original_symbol':'recovered','manifest_path':'manifest.json','function':'recovered','candidate_abi':'sysv','cases':[case,dict(case,arguments=[{'buffer':'b'},0,2,3,4,5,6])]},artifacts,project,context)
    (tmp_path/'original.dll').write_bytes(b'changed workspace original')
    assert verifier.verify(tmp_path,contract,artifacts,project,context)['passed']
    (tmp_path/'helper.c').write_text('unsigned mix(unsigned x){return 0;}')
    result=verifier.verify(tmp_path,contract,artifacts,project,context)
    assert not result['passed']
    assert '"buffers":' not in json.dumps(result) and 'failures' not in result


@pytest.mark.parametrize('case',[{'arguments':[-1]},{'arguments':[True]},{'arguments':[{'buffer':'missing'}]},
    {'buffers':[{'id':'x','hex':''}]},{'buffers':[{'id':'x','hex':'00','permissions':'rwx'}]}, {'max_instructions':0}])
def test_invalid_call_contracts(case):
    with pytest.raises(ContractError):calls.validate_case(case)


def test_bad_images_and_unresolved_dependencies(tmp_path):
    with pytest.raises(ContractError): calls.load(b'MZbad',symbol='f')
    (tmp_path/'f.c').write_text('extern int external(void); int f(void){return external();}')
    assert not calls.build(tmp_path,{'sources':['f.c']},'f','win64',Jobs(),CLANG)['passed']
