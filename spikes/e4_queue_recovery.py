"""Exercise a WAL queue through real Windows process termination."""

import ctypes
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import closing, contextmanager
from ctypes import wintypes
from pathlib import Path
from tempfile import TemporaryDirectory

from common import OUT, Result, child_env, save, standalone


LEASE = 4.0
HEARTBEAT = 0.2
BASE_BACKOFF = 0.25
MAX_RETRIES = 3
JOBS = {"interrupted": 0, "ordinary": 0, "retry-once": 1, "dead-letter": 4}


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def connect(path):
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA synchronous=FULL")
    return db


def initialize(db):
    mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    db.executescript("""
        CREATE TABLE jobs (
            job_id INTEGER PRIMARY KEY, job_key TEXT UNIQUE NOT NULL,
            fail_first INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'ready',
            attempts INTEGER NOT NULL DEFAULT 0, retries INTEGER NOT NULL DEFAULT 0,
            available REAL NOT NULL DEFAULT 0, owner TEXT, lease_until REAL,
            heartbeats INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE effects (job_key TEXT PRIMARY KEY);
        CREATE TABLE claims (job_key TEXT, attempt INTEGER, claimed_at REAL,
                             PRIMARY KEY (job_key, attempt));
        CREATE TABLE retries (job_key TEXT, retry INTEGER, reason TEXT, backoff REAL,
                              ready_at REAL, PRIMARY KEY (job_key, retry));
    """)
    return mode


def enqueue(db, key, fail_first):
    return db.execute("INSERT OR IGNORE INTO jobs(job_key, fail_first) VALUES (?, ?)",
                      (key, fail_first)).rowcount


def schedule_retry(db, job, reason, now):
    retries = job["retries"]
    if retries >= MAX_RETRIES:
        db.execute("""UPDATE jobs SET state='dead', owner=NULL, lease_until=NULL
                      WHERE job_id=?""", (job["job_id"],))
        return
    retries += 1
    delay = BASE_BACKOFF * 2 ** (retries - 1)
    db.execute("""UPDATE jobs SET state='ready', retries=?, available=?,
                  owner=NULL, lease_until=NULL WHERE job_id=?""",
               (retries, now + delay, job["job_id"]))
    db.execute("INSERT INTO retries VALUES (?, ?, ?, ?, ?)",
               (job["job_key"], retries, reason, delay, now + delay))


def claim(db):
    with transaction(db):
        now = time.time()
        for job in db.execute("SELECT * FROM jobs WHERE state='leased' AND lease_until<=?",
                              (now,)).fetchall():
            schedule_retry(db, job, "lease expired", now)
        job = db.execute("""SELECT * FROM jobs WHERE state='ready' AND available<=?
                            ORDER BY job_id LIMIT 1""", (now,)).fetchone()
        if job is None:
            return None
        owner = uuid.uuid4().hex
        attempt = job["attempts"] + 1
        db.execute("""UPDATE jobs SET state='leased', owner=?, lease_until=?, attempts=?
                      WHERE job_id=?""", (owner, now + LEASE, attempt, job["job_id"]))
        db.execute("INSERT INTO claims VALUES (?, ?, ?)", (job["job_key"], attempt, now))
        return {**dict(job), "owner": owner, "attempts": attempt}


def heartbeat(db, job):
    with transaction(db):
        now = time.time()
        return db.execute("""UPDATE jobs SET lease_until=?, heartbeats=heartbeats+1
                             WHERE job_id=? AND owner=? AND state='leased' AND lease_until>?""",
                          (now + LEASE, job["job_id"], job["owner"], now)).rowcount == 1


def finish(db, job, failed=False):
    with transaction(db):
        now = time.time()
        active = db.execute("""SELECT * FROM jobs WHERE job_id=? AND owner=? AND state='leased'
                               AND lease_until>?""",
                            (job["job_id"], job["owner"], now)).fetchone()
        if active is None:
            return False
        if failed:
            schedule_retry(db, active, "handler failure", now)
        else:
            db.execute("INSERT INTO effects VALUES (?)", (job["job_key"],))
            db.execute("""UPDATE jobs SET state='done', owner=NULL, lease_until=NULL
                          WHERE job_id=?""", (job["job_id"],))
        return True


def worker(path, pause):
    with closing(connect(path)) as db:
        while True:
            job = claim(db)
            if job is None:
                active = db.execute("SELECT 1 FROM jobs WHERE state IN ('ready', 'leased') LIMIT 1")
                if active.fetchone() is None:
                    return
                time.sleep(0.05)
                continue
            if pause:
                while heartbeat(db, job):
                    time.sleep(HEARTBEAT)
                raise RuntimeError("Paused worker lost its lease before termination")
            if not finish(db, job, failed=job["attempts"] <= job["fail_first"]):
                raise RuntimeError("Restart worker lost its lease before completion")


def child_args(mode, path):
    return [sys.executable, __file__, mode, str(path)]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def await_heartbeat(db, process):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = db.execute("SELECT * FROM jobs WHERE job_key='interrupted'").fetchone()
        if job["state"] == "leased" and job["heartbeats"] >= 2:
            return dict(job)
        require(process.poll() is None, "Original process exited before two heartbeats")
        time.sleep(0.05)
    raise RuntimeError("Original worker did not reach two heartbeats within 10 seconds")


def kill(pid, tree):
    args = ["taskkill.exe", "/PID", str(pid), "/F"]
    if tree:
        args.append("/T")
    result = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=10, env=child_env())
    return {"command": args, "exit": result.returncode,
            "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


@contextmanager
def windows_job(process):
    """Own the supervisor and its future descendants through an OS job handle."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                 wintypes.DWORD, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    class Accounting(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in
                    ("user_time", "kernel_time", "period_user_time", "period_kernel_time")] + [
                    (name, wintypes.DWORD) for name in ("faults", "total", "active", "terminated")]

    def members():
        counts = Accounting()
        if not kernel.QueryInformationJobObject(handle, 1, ctypes.byref(counts), ctypes.sizeof(counts), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"total": counts.total, "active": counts.active}

    def terminate():
        if not kernel.TerminateJobObject(handle, 137):
            raise ctypes.WinError(ctypes.get_last_error())

    try:
        # Popen owns a Windows process handle, even when opening a PID from another process is denied.
        if not kernel.AssignProcessToJobObject(handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        yield members, terminate
    finally:
        kernel.CloseHandle(handle)


def terminate_original(db, path, tree, original, evidence, members=None, terminate=None):
    child_pid_path = path.with_suffix(".pid")
    if tree:
        path.with_suffix(".start").touch()
    before = await_heartbeat(db, original)
    worker_pid = int(child_pid_path.read_text()) if tree else original.pid
    evidence["original_pids"] = {"root": original.pid, "worker": worker_pid}
    evidence["before_kill"] = {key: before[key] for key in ("state", "attempts", "retries", "heartbeats")}
    if tree:
        evidence["job_members_before_kill"] = members()
        require(worker_pid != original.pid and evidence["job_members_before_kill"]["active"] == 2,
                "Supervisor and worker were not both assigned to the job object")
    try:
        evidence["taskkill"] = kill(original.pid, tree)
    except subprocess.SubprocessError as exc:
        evidence["taskkill"] = {"exit": None, "error": type(exc).__name__}
    if evidence["taskkill"]["exit"] == 0:
        evidence["termination_method"] = "taskkill /F /T" if tree else "taskkill /F"
    elif tree:
        terminate()
        evidence["termination_method"] = "TerminateJobObject"
    else:
        original.kill()
        evidence["termination_method"] = "TerminateProcess (Popen.kill)"
    evidence["killed_root_exit"] = original.wait(timeout=10)
    require(evidence["killed_root_exit"] != 0, "Original process exited normally")
    if tree:
        deadline = time.monotonic() + 2
        while members()["active"] and time.monotonic() < deadline:
            time.sleep(0.05)
        evidence["job_members_after_kill"] = members()
        require(evidence["job_members_after_kill"] == {"total": 2, "active": 0},
                "The whole process tree was not terminated")
    return before


def scenario(path, tree, evidence):
    with closing(connect(path)) as db:
        evidence["journal_mode"] = initialize(db)
        require(evidence["journal_mode"] == "wal", "SQLite did not enter WAL mode")
        for key, fail_first in JOBS.items():
            require(enqueue(db, key, fail_first) == 1, "Initial enqueue failed")
        evidence["duplicate_enqueue_inserted"] = enqueue(db, "interrupted", 99)
        require(evidence["duplicate_enqueue_inserted"] == 0, "Queue accepted a duplicate key")

        mode = "--supervisor" if tree else "--pause"
        with subprocess.Popen(child_args(mode, path), env=child_env()) as original:
            try:
                if tree:
                    with windows_job(original) as (members, terminate):
                        try:
                            before = terminate_original(db, path, tree, original, evidence, members, terminate)
                        finally:
                            if members()["active"]:
                                terminate()
                else:
                    before = terminate_original(db, path, tree, original, evidence)
            finally:
                if original.poll() is None:
                    original.kill()

    # Reopen the database and restart a fresh worker while the killed lease is still valid.
    with closing(connect(path)) as db:
        persisted = db.execute("SELECT * FROM jobs WHERE job_id=?", (before["job_id"],)).fetchone()
        evidence["after_kill_before_restart"] = {key: persisted[key] for key in
                                                ("state", "attempts", "retries", "heartbeats")}
        require(persisted["state"] == "leased" and persisted["attempts"] == 1
                and persisted["retries"] == 0 and persisted["heartbeats"] >= 2,
                "Killed lease or counters were lost")
        require(time.time() < persisted["lease_until"], "Lease expired before restart")
        recovered = subprocess.run(child_args("--drain", path), timeout=20, env=child_env())
        evidence["restart_exit"] = recovered.returncode
        require(recovered.returncode == 0, "Restart worker exited with an error")

        evidence["after_restart"] = [dict(row) for row in db.execute(
            "SELECT job_key, state, attempts, retries, heartbeats FROM jobs ORDER BY job_id")]
        evidence["effects"] = [row[0] for row in db.execute("SELECT job_key FROM effects ORDER BY 1")]
        evidence["retry_history"] = [dict(row) for row in db.execute("""
            SELECT retries.job_key, retry, reason, backoff,
                   round(claimed_at-ready_at, 3) AS seconds_after_eligible,
                   claimed_at >= ready_at AS respected_backoff
            FROM retries JOIN claims ON retries.job_key=claims.job_key AND attempt=retry+1
            ORDER BY retries.job_key, retry
        """)]
        evidence["stale_finish_accepted"] = finish(db, before)
        evidence["integrity_check"] = db.execute("PRAGMA integrity_check").fetchone()[0]
        actual = {row["job_key"]: (row["state"], row["attempts"], row["retries"])
                  for row in evidence["after_restart"]}
        require(actual == {"interrupted": ("done", 2, 1), "ordinary": ("done", 1, 0),
                           "retry-once": ("done", 2, 1), "dead-letter": ("dead", 4, 3)},
                "Unexpected state, attempts or retry counts after restart")
        require(evidence["effects"] == ["interrupted", "ordinary", "retry-once"]
                and not evidence["stale_finish_accepted"], "Missing or duplicate completion")
        history = evidence["retry_history"]
        expired = db.execute("SELECT ready_at-backoff FROM retries WHERE job_key='interrupted' AND retry=1").fetchone()
        evidence["expired_before_reclaim"] = bool(expired and expired[0] >= persisted["lease_until"])
        require(len(history) == 5 and all(row["respected_backoff"] for row in history)
                and [row["backoff"] for row in history if row["job_key"] == "dead-letter"]
                == [0.25, 0.5, 1.0]
                and evidence["expired_before_reclaim"]
                and any(row["job_key"] == "interrupted" and row["reason"] == "lease expired"
                        for row in history), "Lease recovery or exponential backoff was not observed")
        require(evidence["integrity_check"] == "ok", "Database integrity check failed")


def run():
    if os.name != "nt":
        return [Result("E4 Windows queue recovery", "BLOCKED", "Windows taskkill required.",
                       "Windows crash scenarios were not run.", "Run on Windows.")]
    OUT.mkdir(exist_ok=True)
    rows = []
    for tree in (False, True):
        label = "process tree" if tree else "worker process"
        evidence = {"scenario": label, "enqueued": len(JOBS), "max_retries": MAX_RETRIES}
        try:
            with TemporaryDirectory(dir=OUT, prefix="queue-") as directory:
                scenario(Path(directory) / "queue.sqlite", tree, evidence)
            verdict = "PASS"
            taskkill = evidence["taskkill"]
            diagnostic = taskkill.get("stderr") or taskkill.get("error") or ""
            summary = (f"taskkill exit {taskkill['exit']}" + (f" ({diagnostic})" if diagnostic else "") +
                       f". {evidence['termination_method']} killed the process{' tree' if tree else ''}. "
                       f"Killed root exit {evidence['killed_root_exit']}, restart exit {evidence['restart_exit']}. "
                       "4 jobs retained, 3 unique completions, 1 dead letter. Lease reclaimed.")
        except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            verdict = "FAIL"
            summary = f"{type(exc).__name__}: {exc}"
            evidence["error"] = summary
        filename = f"e4_{'tree' if tree else 'worker'}.json"
        save(filename, evidence)
        rows.append(Result(f"E4 Windows queue recovery ({label})", verdict,
                           f"{summary} See [evidence](out/{filename}).",
                           "Forced process termination. SQLite effects share the completion transaction. "
                           "Power loss and external side effects were unverified.",
                           "Use WAL, fenced leases, backoff and dead letters for the MVP queue."))
    return rows


if __name__ == "__main__":
    if len(sys.argv) == 1:
        standalone(run)
    else:
        mode, path = sys.argv[1], Path(sys.argv[2])
        if mode == "--supervisor":
            deadline = time.monotonic() + 10
            while not path.with_suffix(".start").exists():
                require(time.monotonic() < deadline, "Supervisor start was never signaled")
                time.sleep(0.05)
            with subprocess.Popen(child_args("--pause", path), env=child_env()) as child:
                path.with_suffix(".pid").write_text(str(child.pid), encoding="ascii")
                sys.exit(child.wait())
        elif mode in {"--pause", "--drain"}:
            worker(path, pause=mode == "--pause")
        else:
            sys.exit("Unknown worker mode")
