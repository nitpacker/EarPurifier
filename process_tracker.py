"""
EarPurifier - Subprocess and Thread Lifecycle Tracker
Ensures graceful termination and immediate cleanup of child processes and worker threads.
"""

import os
import signal
import subprocess
import logging
from typing import Set

logger = logging.getLogger(__name__)

# Global registry of active child subprocesses
_ACTIVE_SUBPROCESSES: Set[subprocess.Popen] = set()


def register_process(proc: subprocess.Popen) -> None:
    """Registers a subprocess.Popen instance to be tracked for cleanup."""
    if proc:
        _ACTIVE_SUBPROCESSES.add(proc)


def unregister_process(proc: subprocess.Popen) -> None:
    """Removes a finished subprocess from the tracking registry."""
    _ACTIVE_SUBPROCESSES.discard(proc)


def kill_process_tree(pid: int) -> None:
    """
    Kills a process and all of its spawned child processes.
    Uses 'taskkill /F /T /PID' on Windows for guaranteed recursive process tree destruction.
    """
    if not pid or pid <= 0:
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        except Exception as e:
            logger.debug(f"Failed to taskkill PID {pid}: {e}")
    else:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass


def cleanup_all_subprocesses() -> None:
    """
    Forcefully terminates all active registered subprocesses and their process trees.
    Guarantees no orphaned worker or utility processes survive application exit.
    """
    for proc in list(_ACTIVE_SUBPROCESSES):
        try:
            if proc.poll() is None:  # Still executing
                kill_process_tree(proc.pid)
                proc.kill()
                try:
                    proc.wait(timeout=0.5)
                except Exception:
                    pass
                proc.poll()
        except Exception as e:
            logger.debug(f"Error terminating child process {getattr(proc, 'pid', 'unknown')}: {e}")
    _ACTIVE_SUBPROCESSES.clear()


def terminate_qt_threads(threads: list, timeout_ms: int = 300) -> None:
    """
    Gracefully requests worker QThreads to stop, waits briefly, and forcefully terminates
    any thread that does not finish in time to prevent QThread destruction deadlocks.
    """
    for th in threads:
        if not th:
            continue
        try:
            if hasattr(th, "stop"):
                th.stop()
            elif hasattr(th, "requestInterruption"):
                th.requestInterruption()
        except Exception:
            pass

    for th in threads:
        if not th:
            continue
        try:
            if th.isRunning():
                if not th.wait(timeout_ms):
                    th.terminate()
                    th.wait(200)
        except Exception:
            pass
