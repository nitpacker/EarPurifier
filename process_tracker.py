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
    if not pid or pid <= 0 or pid == os.getpid():
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
        # POSIX (macOS & Linux)
        try:
            # 1. Recursively find and terminate child processes via pgrep
            try:
                res = subprocess.run(
                    ["pgrep", "-P", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
                if res.returncode == 0:
                    for child_pid_str in res.stdout.strip().split():
                        if child_pid_str.isdigit():
                            child_pid = int(child_pid_str)
                            if child_pid > 0 and child_pid != os.getpid() and child_pid != pid:
                                kill_process_tree(child_pid)
            except Exception:
                pass

            sigkill = getattr(signal, "SIGKILL", getattr(signal, "SIGTERM", 9))
            # 2. Safely terminate the process or its process group
            parent_pgrp = getattr(os, "getpgrp", lambda: -1)()
            try:
                getpgid_fn = getattr(os, "getpgid", None)
                pgid = getpgid_fn(pid) if getpgid_fn else -1
                killpg_fn = getattr(os, "killpg", None)
                # CRITICAL: Only kill process group if it is strictly valid and detached from the parent's group
                if killpg_fn and pgid > 0 and pgid != parent_pgrp:
                    killpg_fn(pgid, sigkill)
                else:
                    os.kill(pid, sigkill)
            except (ProcessLookupError, OSError):
                try:
                    os.kill(pid, sigkill)
                except Exception:
                    pass
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.debug(f"Error terminating POSIX process {pid}: {e}")


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
