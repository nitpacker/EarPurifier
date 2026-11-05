# Future Code Hardening Plans

This document records identified code hardening, defensive engineering, and infrastructure improvements. 

Entries follow a standardized template so future development sessions can easily re-investigate, scope, and implement them.

---

## Entry Template

When appending a new plan, use the following structure:

```markdown
### [HARDEN-XXX] <Title>
- **Target Component(s)**: `<relative/path/to/file.py>`
- **Category**: Stability / Platform Limits / Maintainability / Security
- **Issue Description**: Brief summary of the edge case, risk, or technical limitation.
- **Proposed Solution**: High-level design and implementation approach.
```

---

## Hardening Plans

### [HARDEN-001] Startup Scavenger for Orphaned Datasets
- **Target Component(s)**: [`kaggle_bridge.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/kaggle_bridge.py), [`main.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/main.py)
- **Category**: Platform Limits & Cleanliness
- **Issue Description**:
  Ephemeral audio buffers (`earpurifier-audio-buffer-<id>`) are deleted on clean job completion or handled abortion. If the application terminates abnormally (system crash, power loss, force-kill), the remote dataset remains on the user's Kaggle account. Over extended periods, accumulating orphaned datasets could approach Kaggle's free account ceilings (100 private datasets, 20 GB private storage).
- **Proposed Solution**:
  Implement an asynchronous scavenger during startup (or idle queue state). Query `api.datasets_list(user=self.username)`, locate datasets matching the `earpurifier-audio-buffer-` prefix, inspect creation timestamps, and delete any orphaned datasets older than a defined safety window (e.g. >2–12 hours).

---

### [HARDEN-002] Decouple Master Dataset Slug
- **Target Component(s)**: [`config_manager.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/config_manager.py), [`kaggle_bridge.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/kaggle_bridge.py), [`releases/latest.json`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/releases/latest.json)
- **Category**: Maintainability & Hot-Swapping
- **Issue Description**:
  The asset dataset slug (`"verymuch/earpurifier-cloud-assets-v2"`) is hardcoded in `kaggle_bridge.py:134`. If the dataset ever needs migration, recreation, or renaming, client applications would require an executable rebuild and update.
- **Proposed Solution**:
  Store the active asset dataset slug in `config.json` with a hardcoded default fallback. Allow `update_checker.py` to inspect a remote metadata key (e.g., `cloud_assets_dataset` in `releases/latest.json` or a remote config gist) during routine update checks and sync it to local configuration, allowing remote cache redirection without modifying client binaries.

---

### [HARDEN-003] Symlink Cached Weights into Writable Directory in worker.py
- **Target Component(s)**: [`worker/worker.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/worker/worker.py)
- **Category**: Stability & Defensive Execution
- **Issue Description**:
  Kaggle mounts input datasets under `/kaggle/input/` as strictly read-only FUSE filesystems. Currently, `worker.py` assigns `model_dir` directly to the read-only `/kaggle/input/.../models` path and passes it to `audio-separator` as `model_file_dir`. If `audio-separator` attempts to write lockfiles, download missing auxiliary configurations, or fetch a model not present in the cache, the write fails with `OSError: [Errno 30] Read-only file system`, crashing the remote job.
- **Proposed Solution**:
  Configure `model_file_dir` in `worker.py` to always point to `/kaggle/working/models` (which resides on the writable container filesystem). Before instantiating `Separator`, check whether the requested model file exists in the read-only cache under `/kaggle/input/.../models/`. If found, create a symbolic link (`os.symlink`) pointing from the cache into `/kaggle/working/models/` (falling back to `shutil.copy2` if symlinking fails). This maintains instant zero-copy loading while guaranteeing a writable workspace for `audio-separator`.
