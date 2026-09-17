<p align="center">
  <img src="Media/LOGO-02.png" alt="EYRES logo" width="300">
</p>

<h1 align="center">EYRES AI Inspection Platform</h1>
<p align="center"><b>Version 1.1 — Platform Foundation</b></p>

## Overview

EYRES is a centralized Windows desktop platform for industrial computer-vision
inspection. It covers machine and recipe configuration, camera capture,
annotation, augmentation, model training, ROI measurement, PLC monitoring, and
live inference.

## Platform features

- Machine, PLC, project, and inspection-recipe management
- Area-scan, line-scan, and Hikrobot image capture
- Bounding-box and polygon annotation workflows
- Dataset preprocessing and augmentation
- YOLO detection and segmentation training
- ROI measurement and live inspection workspaces
- Central MongoDB persistence
- Bounded database timeouts and degraded-state error reporting
- Rotating runtime logs and a global exception boundary
- Debounced feature navigation with rapid-click cancellation
- Structured audit events for login, logout, navigation, and shutdown
- Best-effort component cleanup during navigation and application shutdown
- Thread-pool adapter for non-UI database, filesystem, and validation work
- PBKDF2 password storage with automatic migration of legacy hashes

## Quick start

Use Python 3.10 or 3.11 on Windows. GPU training requires a compatible NVIDIA
driver and the CUDA build pinned in `requirements.txt`.

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Required only when provisioning the first administrator account.
$env:EYRES_BOOTSTRAP_ADMIN_PASSWORD = "use-a-strong-first-run-password"

python Main_GUI.py
```

MongoDB must be reachable at `mongodb://localhost:27017` by default. Configure
another endpoint with `EYRES_MONGODB_URI`. The full machine configuration is in
`.env.example`. Runtime logs default to
`%USERPROFILE%\EyresAI_Data\logs\eyres-platform.log`.

Operational records are stored beside the application log:

- `page_timings.csv` records page activation times. If Excel locks that file,
  EYRES spools new rows to `page_timings_pending_<pid>.csv`.
- `audit.jsonl` records operator and lifecycle events without passwords, tokens,
  or security answers.

Always launch the supported entry point with `python Main_GUI.py`.

## Verification

```powershell
python -m unittest discover -s tests -v
python -m compileall .
```

Hardware workflows must additionally be validated with the actual camera, PLC,
GPU, and MongoDB versions used on the inspection machine.

## Engineering documentation

- `docs/ARCHITECTURE.md` defines module boundaries and responsiveness rules.
- `docs/INDUSTRIAL_ROADMAP.md` defines the remaining reliability, unified UI,
  data integrity, centralized scale, and release-test increments.

## Contributor

- [Yerriswamy Chakala](https://github.com/Yerriswamy2001)
