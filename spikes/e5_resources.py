"""Inspect Windows resources without starting a runtime or fetching models."""

import ctypes
import os
import platform
import shutil
import struct
from ctypes import wintypes
from pathlib import Path

from common import ROOT, Result, save, standalone


GIB = 1024 ** 3


def windows_resources(evidence):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong) for name in ("total", "available", "page_total", "page_available",
                                                   "virtual_total", "virtual_available", "extended")]

    class DisplayDevice(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("name", wintypes.WCHAR * 32),
                    ("description", wintypes.WCHAR * 128), ("flags", wintypes.DWORD),
                    ("device_id", wintypes.WCHAR * 128), ("device_key", wintypes.WCHAR * 128)]

    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
    memory = MemoryStatus(length=ctypes.sizeof(MemoryStatus))
    if kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
        evidence["ram_total_bytes"] = memory.total
        evidence["ram_available_bytes"] = memory.available
    else:
        evidence["memory_error"] = ctypes.get_last_error()

    # RelationProcessorCore returns one record per physical core across processor groups.
    kernel.GetLogicalProcessorInformationEx.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    size = wintypes.DWORD()
    kernel.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))
    if size.value:
        buffer = ctypes.create_string_buffer(size.value)
        if kernel.GetLogicalProcessorInformationEx(0, buffer, ctypes.byref(size)):
            offset, cores = 0, 0
            while offset + 8 <= size.value:
                relation, record_size = struct.unpack_from("<II", buffer, offset)
                if record_size < 8 or offset + record_size > size.value:
                    break
                cores += relation == 0
                offset += record_size
            if offset == size.value and cores:
                evidence["cpu_physical_cores"] = cores
    if "cpu_physical_cores" not in evidence:
        evidence["cpu_topology_error"] = ctypes.get_last_error()

    user.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DisplayDevice),
                                        wintypes.DWORD]
    descriptions = set()
    for index in range(32):
        display = DisplayDevice(length=ctypes.sizeof(DisplayDevice))
        if not user.EnumDisplayDevicesW(None, index, ctypes.byref(display), 0):
            break
        if display.description:
            descriptions.add(display.description)
    evidence["display_adapters"] = sorted(descriptions)
    evidence["gpu_present"] = (True if any(gpu.lower().startswith(("nvidia", "amd", "intel", "radeon", "qualcomm"))
                                            for gpu in descriptions) else None)


def runtimes():
    names = {"Ollama": ("ollama",), "LM Studio": ("lms", "lmstudio"),
             "llama.cpp": ("llama-cli", "llama-server"), "Jan": ("jan",)}
    paths = {
        "Ollama": [("LOCALAPPDATA", "Programs/Ollama/ollama.exe"), ("PROGRAMFILES", "Ollama/ollama.exe")],
        "LM Studio": [("LOCALAPPDATA", "Programs/LM Studio/LM Studio.exe")],
        "Jan": [("LOCALAPPDATA", "Programs/Jan/Jan.exe"), ("PROGRAMFILES", "Jan/Jan.exe")],
    }
    found = {}
    for name, binaries in names.items():
        on_path = any(shutil.which(binary) for binary in binaries)
        standard_path = any(os.environ.get(env) and (Path(os.environ[env]) / relative).is_file()
                            for env, relative in paths.get(name, []))
        found[name] = "on PATH" if on_path else "standard install path" if standard_path else "not detected"
    return found


def run():
    disk = shutil.disk_usage(ROOT)
    evidence = {"platform": f"{platform.system()} {platform.release()} {platform.version()}",
                "python": platform.python_version(), "cpu_logical_cores": os.cpu_count(),
                "workspace_drive": ROOT.anchor, "workspace_free_bytes": disk.free,
                "local_ai_runtimes": runtimes()}
    if os.name == "nt":
        windows_resources(evidence)
    save("e5_resources.json", evidence)
    complete = all(key in evidence for key in ("cpu_physical_cores", "ram_total_bytes", "display_adapters"))
    runtime_names = [name for name, state in evidence["local_ai_runtimes"].items() if state != "not detected"]
    ram = f"{evidence['ram_total_bytes'] / GIB:.1f} GiB RAM" if "ram_total_bytes" in evidence else "RAM unverified"
    gpu = ", ".join(evidence.get("display_adapters", [])) or "GPU unverified"
    runtime = ", ".join(runtime_names) if runtime_names else "no local AI runtime detected"
    summary = (f"{evidence['platform']}, {evidence.get('cpu_physical_cores', '?')} physical / "
               f"{evidence['cpu_logical_cores']} logical cores, {ram}, {gpu}, {disk.free / GIB:.1f} GiB "
               f"free on the workspace drive, {runtime}. [Evidence](out/e5_resources.json).")
    return [Result("E5 Host resources", "PASS" if complete else "BLOCKED", summary,
                   "The runtime check covers PATH and common Windows installation paths. GPU inference, VRAM and model throughput are unverified. "
                   "The measured RAM and disk make a small quantized model a candidate for later benchmarking. "
                   "[Ollama hardware notes](https://ollama.com/blog/improved-performance-and-model-support-with-gguf).",
                   "Use rule-based fallback for the MVP. Reassess local inference after a separate model and runtime benchmark.")]


if __name__ == "__main__":
    standalone(run)
