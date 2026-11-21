"""Optional Windows memory governor for queue claims."""

import ctypes
import os
from collections.abc import Callable
from ctypes import wintypes


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD), ("memory_load", wintypes.DWORD),
        ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong), ("avail_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
        ("avail_extended_virtual", ctypes.c_ulonglong),
    ]


def system_memory_used_percent() -> int | None:
    if os.name != "nt":
        return None
    status = _MemoryStatus(length=ctypes.sizeof(_MemoryStatus))
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return int(status.memory_load)
    return None


class MemoryGovernor:
    def __init__(
        self, max_used_percent: int | None = None,
        *, sample: Callable[[], int | None] = system_memory_used_percent,
    ) -> None:
        if max_used_percent is not None and not 0 <= max_used_percent <= 100:
            raise ValueError("The memory threshold must be between 0 and 100 percent")
        self._threshold = max_used_percent
        self._sample = sample

    def allows_claim(self) -> bool:
        if self._threshold is None:
            return True
        used = self._sample()
        return used is None or used <= self._threshold
