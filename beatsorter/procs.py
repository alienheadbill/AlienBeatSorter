"""Make sure Beat Sorter's helper processes never outlive the app.

Two layers:
* stop_all(): called when the window closes; ends analysis workers right
  away (instead of letting them finish the whole scan in the background).
* On Windows, helpers are also put in a "job" that Windows closes when
  Beat Sorter exits for any reason (crash, Task Manager), which ends them.
  Only our own helpers are added, so a browser or folder window opened
  from the app is never affected.
"""

from __future__ import annotations

import os
import threading
from typing import List

_job = None
_lock = threading.Lock()
_pools: List[object] = []


def _windows_job():
    """A job object that kills its processes when Beat Sorter closes."""
    global _job
    if _job is not None or os.name != "nt":
        return _job
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        return None
    _job = (k32, job)
    return _job


def tie_to_app(pid: int) -> None:
    """Windows: end this helper process (and anything it starts) when Beat
    Sorter exits, even after a crash. Elsewhere: nothing to do."""
    if os.name != "nt" or not pid:
        return
    try:
        with _lock:
            j = _windows_job()
        if not j:
            return
        k32, job = j
        from ctypes import wintypes
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x0101, False, pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if h:
            k32.AssignProcessToJobObject(job, h)
            k32.CloseHandle(h)
    except Exception:
        pass  # best effort; stop_all() still runs on a normal close


def watch_pool(pool) -> None:
    """Remember an analysis pool so stop_all() can end it, and tie its
    worker processes to the app."""
    with _lock:
        _pools.append(pool)
    for p in list(getattr(pool, "_processes", {}).values()):
        tie_to_app(p.pid)


def forget_pool(pool) -> None:
    with _lock:
        if pool in _pools:
            _pools.remove(pool)


def stop_all() -> None:
    """End every analysis worker now (the app is closing)."""
    with _lock:
        pools = list(_pools)
    for pool in pools:
        for p in list(getattr(pool, "_processes", {}).values()):
            try:
                p.terminate()
            except Exception:
                pass
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
