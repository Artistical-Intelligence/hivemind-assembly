"""Installed runtime probes using only freshly generated, source-known code."""

import ctypes
import os
import platform
import shutil
from pathlib import Path

from hivemind_assembly.core.common import Blocked, file_hash, uid
from hivemind_assembly.core.jobs import Jobs
from hivemind_assembly.domains.reverse_engineering import (
    call_images,
    platform_runtime,
    program,
)


def verify_runtime_lanes(root, foundations, jobs=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    jobs = jobs or Jobs()
    compiler = foundations.get("c_compiler", "")
    checks = {}
    try:
        folder = root / "linux-files"
        folder.mkdir(exist_ok=True)
        (folder / "main.c").write_text(
            """int ha_main(void){
            const char *key=ha_getenv("HA_KEY");
            if(ha_argc()!=2 || !key || key[0]!='K' || ha_argv(1)[0]!='x')return 9;
            unsigned char b[16];long f=ha_open("input",0,0);
            long n=ha_file_read(f,b,16);ha_close(f);
            for(long i=0;i<n;i++)b[i]^=(unsigned char)key[0];
            ha_mkdir("out",448);f=ha_open("out/result",577,384);
            ha_file_write(f,b,n);ha_close(f);ha_write(b,n);return 0;
        }"""
        )
        built = program.build(folder, {"sources": ["main.c"]}, jobs, compiler)
        if not built["passed"]:
            raise Blocked(
                "Linux runtime probe compilation failed: " + str(built.get("build"))
            )
        source = b"known input"
        expected = bytes(value ^ ord("K") for value in source).hex()
        result = platform_runtime.replay(
            bytes.fromhex(built["elf_hex"]),
            argv=["program", "x"],
            env={"HA_KEY": "K"},
            files={"/input": source.hex()},
        )
        if (
            result["status"] != "completed"
            or result["exit_code"] != 0
            or result["stdout_hex"] != expected
            or result["files"] != {"/input": source.hex(), "/out/result": expected}
            or result["directories"] != ["/out"]
        ):
            raise Blocked(
                "Declared Linux process/files probe did not match known results"
            )
        checks["qiling_runtime"] = {
            "passed": True,
            "engine": result["engine"],
            "process_inputs": True,
            "file_effects": True,
            "image_sha256": built["sha256"],
        }
    except Exception as error:
        checks["qiling_runtime"] = {"passed": False, "reason": str(error)}

    try:
        folder = root / "linked-functions"
        folder.mkdir(exist_ok=True)
        source = "unsigned recovered(unsigned *p,unsigned x){*p+=x;return *p*3;}"
        (folder / "function.c").write_text(source)
        case = {
            "arguments": [{"buffer": "value"}, 7],
            "buffers": [{"id": "value", "hex": "02000000"}],
            "output_bits": 32,
        }
        images, results = {}, {}
        for abi in ("sysv", "win64"):
            built = call_images.build(
                folder, {"sources": ["function.c"]}, "recovered", abi, jobs, compiler
            )
            if not built["passed"]:
                raise Blocked("Linked " + abi + " probe compilation failed")
            images[abi] = bytes.fromhex(built["image_hex"])
            result = call_images.execute(
                call_images.load(images[abi], symbol="recovered"), case
            )
            if (
                result["status"] != "completed"
                or not result["abi_ok"]
                or result["value"] != 27
                or result["buffers"] != {"value": "09000000"}
            ):
                raise Blocked(
                    "Linked "
                    + abi
                    + " probe did not match known pointer/return results"
                )
            results[abi] = result
        if os.name == "nt":
            native = folder / "known-native.dll"
            native.write_bytes(images["win64"])
        elif platform.system() == "Linux":
            executable = (
                shutil.which(compiler)
                if compiler
                else (shutil.which("clang") or shutil.which("gcc"))
            )
            native = folder / "known-native.so"
            result = jobs.run(
                uid("native-oracle"),
                [
                    executable,
                    "-shared",
                    "-fPIC",
                    "-ffreestanding",
                    "-fno-stack-protector",
                    "-nostdlib",
                    "function.c",
                    "-o",
                    native.name,
                ],
                folder,
                timeout=30,
            )
            if result["status"] != "completed" or result["exit_code"] != 0:
                raise Blocked("Native pointer oracle compilation failed")
        else:
            raise Blocked("Native runtime probe supports Windows and Linux hosts")
        library = ctypes.CDLL(str(native))
        function = library.recovered
        function.argtypes = [ctypes.POINTER(ctypes.c_uint), ctypes.c_uint]
        function.restype = ctypes.c_uint
        value = ctypes.c_uint(2)
        if function(ctypes.byref(value), 7) != 27 or value.value != 9:
            raise Blocked("Native pointer oracle disagrees with linked replay")
        checks["linked_functions"] = {
            "passed": True,
            "abis": list(results),
            "native_oracle": {
                "passed": True,
                "host": platform.system(),
                "sha256": file_hash(native),
            },
        }
    except Exception as error:
        checks["linked_functions"] = {"passed": False, "reason": str(error)}
    return checks
