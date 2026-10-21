"""Bounded private Windows virtual memory, separate from loader-owned mappings.

Speakeasy owns address translation. This contract owns page state, protection,
zero-on-commit and API buffer access; upstream API approximations are not used.
"""

from itertools import groupby

MEMORY_APIS = ("VirtualAlloc", "VirtualProtect", "VirtualFree")
PAGE = 4096
GRANULARITY = 65536
LIMIT = 16 * 1024 * 1024
RESERVE, COMMIT, DECOMMIT, RELEASE = 0x2000, 0x1000, 0x4000, 0x8000


def rounded(value, alignment=PAGE):
    return (value + alignment - 1) // alignment * alignment


class _Memory:
    def __init__(self, emu, memory):
        self.emu, self.memory = emu, memory

    def mem_read(self, address, size):
        self.memory.access(address, size, write=False)
        self.permitted(address, size, write=False)
        return self.emu.mem_read(address, size)

    def mem_write(self, address, data):
        self.memory.access(address, len(data), write=True)
        self.permitted(address, len(data), write=True)
        return self.emu.mem_write(address, data)

    def mem_map(self, *args, **kwargs):
        return self.emu.mem_map(*args, **kwargs)

    def permitted(self, address, size, *, write):
        from unicorn import UC_PROT_READ, UC_PROT_WRITE

        if not size:
            return
        end = address + size
        if address < 0 or size < 0 or end > 2**64:
            self.memory.deny(address, size, write, "Invalid API buffer range")
        required = UC_PROT_WRITE if write else UC_PROT_READ
        cursor = address
        # Unicorn exposes inclusive ends and its own protection bits. Check the
        # whole span; checking only the first page misses cross-page violations.
        for lo, hi, permissions in sorted(self.emu.get_mem_regions()):
            if hi < cursor:
                continue
            if lo > cursor or not permissions & required:
                break
            cursor = min(end, hi + 1)
            if cursor == end:
                return
        self.memory.deny(
            address, size, write, "API buffer violates mapped page permissions"
        )


class Memory:
    def __init__(self, state):
        self.state = state
        self.regions = []
        self.total = 0
        self.next_base = 0x400000000
        self.fault_access = None

    def deny(self, address, size, write, reason):
        self.fault_access = {
            "address": address,
            "size": size,
            "access": "write" if write else "read",
        }
        self.state.stop("fault", reason)

    def memory(self, emu):
        return _Memory(emu, self)

    def access(self, address, size, *, write):
        # Host-side Unicorn reads/writes bypass page protections. Every modeled
        # API uses this facade, including file I/O and output-count pointers.
        for region in self.regions:
            lo = max(address, region["base"])
            hi = min(address + size, region["base"] + region["size"])
            if hi <= lo:
                continue
            first = (lo - region["base"]) // PAGE
            last = (hi - 1 - region["base"]) // PAGE
            allowed = (4,) if write else (2, 4)
            if any(p not in allowed for p in region["pages"][first : last + 1]):
                self.deny(
                    address,
                    size,
                    write,
                    "API buffer accesses inaccessible virtual memory",
                )

    def region(self, address, size):
        if not size or size > LIMIT or address + size > 2**64:
            self.state.unsupported("Invalid or oversized virtual memory range")
        for region in self.regions:
            if (
                not region["released"]
                and region["base"] <= address
                and address + size <= region["base"] + region["size"]
            ):
                return region
        self.state.unsupported(
            "Virtual memory operation is outside an owned reservation"
        )

    def protect(self, value):
        # No execution, guards, copy-on-write, cache modifiers or physical pages.
        if value not in (1, 2, 4):
            self.state.unsupported(
                "Virtual memory supports NOACCESS, READONLY and READWRITE"
            )
        return value

    @staticmethod
    def permissions(value):
        from speakeasy.common import PERM_MEM_READ, PERM_MEM_WRITE

        return {0: 0, 1: 0, 2: PERM_MEM_READ, 4: PERM_MEM_READ | PERM_MEM_WRITE}[value]

    def set_pages(self, emu, region, start, end, protection):
        if all(p == protection for p in region["pages"][start:end]):
            return
        # One protect call per contiguous range avoids quadratic region splitting
        # in Unicorn when a program reserves or releases thousands of pages.
        emu.mem_protect(
            region["base"] + start * PAGE,
            (end - start) * PAGE,
            self.permissions(protection),
        )
        region["pages"][start:end] = [protection] * (end - start)

    def event(self, name, region, address, size, **values):
        # Relocatable identities: implementation-specific addresses do not enter
        # the strict trace. Actual pointer-dependent output is still compared.
        self.state.events.append(
            {
                "call": name,
                "allocation": region["id"],
                "offset": address - region["base"],
                "size": size,
                **values,
            }
        )

    def call(self, emu, buffers, name, args):
        self.state.error = None
        address, size = args[:2]
        if name == "VirtualAlloc":
            flags, protection = args[2] & 0xFFFFFFFF, self.protect(args[3] & 0xFFFFFFFF)
            if flags not in (RESERVE, COMMIT, RESERVE | COMMIT):
                self.state.unsupported("Unsupported virtual allocation flags")
            if not size or size > LIMIT:
                self.state.unsupported(
                    "Virtual allocation size is outside replay bounds"
                )
            if flags & RESERVE or not address:
                if address:
                    self.state.unsupported("Fixed-address reservations are unsupported")
                length = rounded(size)
                if self.total + length > LIMIT or len(self.regions) >= 256:
                    self.state.stop(
                        "budget_exhausted", "Virtual reservation budget exhausted"
                    )
                # Keep released mappings inaccessible instead of permitting the
                # loader's allocator to reuse them. Lifetime bytes remain bounded.
                base = emu.mem_map(
                    length, base=self.next_base, perms=0, tag="ha.virtual"
                )
                if base != self.next_base:
                    self.state.unsupported(
                        "Virtual reservation collides with loader memory"
                    )
                region = {
                    "base": base,
                    "size": length,
                    "id": len(self.regions) + 1,
                    "pages": [0] * (length // PAGE),
                    "released": False,
                }
                self.regions.append(region)
                self.total += length
                self.next_base = base + rounded(length, GRANULARITY) + GRANULARITY
                address = base
            else:
                region = self.region(address, size)
            start = (address - region["base"]) // PAGE
            end = rounded(address + size - region["base"]) // PAGE
            if flags & COMMIT:
                if any(p not in (0, protection) for p in region["pages"][start:end]):
                    self.state.unsupported(
                        "Recommit with changed protection requires VirtualProtect"
                    )
                for fresh, indices in groupby(
                    range(start, end), lambda i: region["pages"][i] == 0
                ):
                    # Recommitting an already committed page preserves its data
                    # and protection. Decommitted pages receive fresh zero bytes.
                    indices = list(indices)
                    if fresh:
                        lo, hi = indices[0], indices[-1] + 1
                        emu.mem_write(
                            region["base"] + lo * PAGE, bytes((hi - lo) * PAGE)
                        )
                        self.set_pages(emu, region, lo, hi, protection)
            self.event(name, region, address, size, flags=flags, protection=protection)
            return region["base"] + start * PAGE

        if name == "VirtualProtect":
            protection = self.protect(args[2] & 0xFFFFFFFF)
            output = args[3]
            region = self.region(address, size)
            start = (address - region["base"]) // PAGE
            end = rounded(address + size - region["base"]) // PAGE
            if not output or any(p == 0 for p in region["pages"][start:end]):
                # The API documents failure but not a portable last-error value.
                self.event(name, region, address, size, protection=protection, result=0)
                return 0
            # Output aliasing the changed range has OS-specific ordering; do not
            # manufacture a successful result from host writes past protections.
            lo, hi = region["base"] + start * PAGE, region["base"] + end * PAGE
            if output < hi and output + 4 > lo:
                self.state.unsupported("Protection output overlaps the changed pages")
            buffers.mem_write(output, region["pages"][start].to_bytes(4, "little"))
            self.set_pages(emu, region, start, end, protection)
            self.event(name, region, address, size, protection=protection, result=1)
            return 1

        flags = args[2] & 0xFFFFFFFF
        if flags not in (DECOMMIT, RELEASE):
            self.state.unsupported("Unsupported virtual free flags")
        region = self.region(address, size or 1)
        if flags == RELEASE:
            if address != region["base"] or size:
                self.state.unsupported(
                    "Release requires the allocation base and zero size"
                )
            start, end = 0, len(region["pages"])
            region["released"] = True
        elif size == 0:
            if address != region["base"]:
                self.state.unsupported(
                    "Zero-size decommit requires the allocation base"
                )
            start, end = 0, len(region["pages"])
        else:
            start = (address - region["base"]) // PAGE
            end = rounded(address + size - region["base"]) // PAGE
        self.set_pages(emu, region, start, end, 0)
        self.event(name, region, address, size, flags=flags)
        return 1
