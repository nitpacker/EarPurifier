# Upcoming Features Roadmap

This document records planned functional additions, UI expansions, and pipeline capabilities.

Entries follow a standardized template so future development sessions can easily review, research the fine details, and implement them.

---

## Entry Template

When appending a new feature plan, use the following structure:

```markdown
### [FEAT-XXX] <Feature Title>
- **Target Component(s)**: `<relative/path/to/files>`
- **Category**: Audio Processing / UI & UX / Pipeline / Cloud Infrastructure
- **Feature Summary**: High-level description of the new capability and user value.
- **Proposed Architecture**: Proposed UX flow, model selection, engine integration, and technical design.
```

---

## Planned Features

### [FEAT-001] Environmental Noise Removal & Categorized Model Menu
- **Target Component(s)**: [`ui/dialogs.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/ui/dialogs.py), [`ui/job_queue_section.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/ui/job_queue_section.py), [`local_processor.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/local_processor.py), [`worker/worker.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/worker/worker.py), [`i18n.py`](file:///c:/Users/Rawan/Desktop/Workstation/cleanerEARS/i18n.py)
- **Category**: Audio Processing & UI Expansion
- **Feature Summary**:
  Expand EarPurifier beyond music/vocal separation to include dedicated environmental and ambient noise cancellation (air conditioning, preamp hiss, computer fans, room rumble). Organize the model selection UI into two distinct categorized menu sections: **Music Removal** and **Noise Removal**.
- **Proposed Architecture**:
  - **Categorized Model Selection Menu**:
    - Update the model selector in Settings and Job Queue to separate models into two labeled groups:
      1. **Music Removal**: The 3 existing vocal separation models (`RoFormer`, `MDX23C`, `Kim Vocal 2`).
      2. **Noise Removal**: Dedicated speech denoising models:
         - **Mel-Band RoFormer Denoise** (`denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt`): Heavyweight studio-grade SOTA (~1.8 GB) delivering ~28 dB SDR with full vocal air and harmonic preservation.
         - **UVR-DeNoise-Lite** (`UVR-DeNoise-Lite.pth`): Lightweight, ultra-fast VR-Arch alternative (~55 MB) optimized for low-resource CPU execution.
  - **Native Engine Execution**:
    - Both denoise models are natively supported by `audio-separator`, avoiding any new external dependencies or separate C++/Python runtimes.
  - **Local & Cloud Provisioning**:
    - Add checkpoint metadata to `dependency_manager.py` for on-demand local downloads.
    - Upload weights to the Kaggle master asset dataset (`earpurifier-cloud-assets-v2`) for instant 2-second cloud warmups.
  - **Stream & Stem Invariants**:
    - Update stem selection in `local_processor.py` and `worker.py` to correctly extract the purified speech track from the noise model outputs.
