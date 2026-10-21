"""Declared ELF interpreter/shared-library inputs for upstream Qiling loading."""

import io
from pathlib import PurePosixPath
from elftools.elf.elffile import ELFFile
from hivemind_assembly.core.common import Blocked, ContractError, scoped


def guest_path(name):
    if (
        not isinstance(name, str)
        or not name.startswith("/")
        or "\\" in name
        or "\0" in name
        or len(name) > 1024
        or name == "/"
        or str(PurePosixPath(name)) != name
        or ".." in PurePosixPath(name).parts
        or name == "/.ha"
        or name.startswith("/.ha/")
    ):
        raise ContractError("Dependencies require canonical absolute guest paths")
    return name


def inspect(data, library=False):
    if not isinstance(data, bytes) or not 64 <= len(data) <= (
        8_000_000 if library else 2_000_000
    ):
        raise ContractError("ELF image exceeds bounds")
    try:
        elf = ELFFile(io.BytesIO(data))
        if (
            elf.elfclass != 64
            or not elf.little_endian
            or elf["e_machine"] not in ("EM_X86_64", "EM_AARCH64")
            or elf["e_type"] not in ("ET_EXEC", "ET_DYN")
        ):
            raise Blocked("Linux replay requires little-endian x86-64 or AArch64 ELF")
        if not 1 <= elf.num_segments() <= 128:
            raise ContractError("ELF segment count exceeds bounds")
        total, executable, interpreter, needed, dynamic = 0, False, None, [], False
        for segment in elf.iter_segments():
            if segment["p_offset"] + segment["p_filesz"] > len(data):
                raise ContractError("Truncated ELF segment")
            if segment["p_type"] == "PT_LOAD":
                size, address = segment["p_memsz"], segment["p_vaddr"]
                if (
                    size < segment["p_filesz"]
                    or size > 32_000_000
                    or address + size >= 2**47
                ):
                    raise ContractError("ELF load segment exceeds bounds")
                total += size
                executable |= address <= elf["e_entry"] < address + size and bool(
                    segment["p_flags"] & 1
                )
            elif segment["p_type"] == "PT_INTERP":
                if interpreter is not None:
                    raise ContractError("Multiple ELF interpreters")
                interpreter = guest_path(segment.get_interp_name())
            elif segment["p_type"] == "PT_DYNAMIC":
                dynamic = True
                for tag in segment.iter_tags():
                    if tag.entry.d_tag == "DT_NEEDED":
                        name = tag.needed
                        if (
                            not name
                            or len(name) > 1024
                            or "\0" in name
                            or "\\" in name
                            or ".." in PurePosixPath(name).parts
                        ):
                            raise ContractError("Invalid ELF dependency name")
                        needed.append(name)
        if (
            not total
            or total > 64_000_000
            or (not library and not executable)
            or len(needed) > 64
        ):
            raise ContractError("Invalid or oversized ELF image")
        if not library and dynamic and not interpreter:
            raise Blocked("Dynamic executable requires a declared ELF interpreter")
        return {
            "interpreter": interpreter,
            "needed": needed,
            "dynamic": dynamic,
            "machine": elf["e_machine"],
        }
    except (Blocked, ContractError):
        raise
    except Exception as error:
        raise ContractError("Malformed ELF image") from error


def validate(data, dependencies=None):
    dependencies = {} if dependencies is None else dependencies
    if not isinstance(dependencies, dict) or len(dependencies) > 32:
        raise ContractError("At most 32 declared ELF dependencies")
    info = inspect(data)
    modules = [info]
    total = 0
    for name, content in dependencies.items():
        guest_path(name)
        module = inspect(content, library=True)
        # Static reconstructions retain original modules as read-only input files;
        # they do not load them. A dynamic loader must only execute its own ISA.
        if info["dynamic"] and module["machine"] != info["machine"]:
            raise Blocked("ELF dependencies must match the program architecture")
        modules.append(module)
        total += len(content)
    if total > 32_000_000:
        raise ContractError("ELF dependencies exceed 32 MB")
    for module in modules:
        if module["interpreter"] and module["interpreter"] not in dependencies:
            raise Blocked(
                "ELF interpreter is not explicitly supplied: " + module["interpreter"]
            )
        for needed in module["needed"]:
            found = (
                needed in dependencies
                if needed.startswith("/")
                else any(PurePosixPath(p).name == needed for p in dependencies)
            )
            if not found:
                raise Blocked("ELF library is not explicitly supplied: " + needed)
    return info


def read_dependencies(root, paths):
    if not isinstance(paths, dict) or len(paths) > 32:
        raise ContractError("At most 32 declared ELF dependencies")
    result = {}
    for name, relative in paths.items():
        guest_path(name)
        path = scoped(root, relative)
        if path.stat().st_size > 8_000_000:
            raise Blocked("ELF dependency exceeds 8 MB")
        result[name] = path.read_bytes()
        if sum(map(len, result.values())) > 32_000_000:
            raise Blocked("ELF dependencies exceed 32 MB")
    return result
