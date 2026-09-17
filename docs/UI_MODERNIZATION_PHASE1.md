# EYRES v1.2.0 — White UI Foundation and Clean Page Structure

## Scope

Phase 1 introduces the professional white EyRes.AI visual system and migrates the application shell, authentication, dashboard, machine, project and administration pages. Camera, annotation, augmentation, training, ROI, PLC and live internals remain functionally unchanged for Phase 2.

## Structure

```text
Eyres/
├── Main_GUI.py
├── app_core/                 # configuration, security and runtime services
├── pages/
│   ├── auth/
│   ├── dashboard/
│   ├── machines/
│   ├── projects/
│   └── administration/
├── ui/
│   ├── assets/               # official app icon and logo mark
│   └── theme/                # tokens, asset lookup and global QSS
├── tools/
├── tests/
├── utils/
└── docs/
```

The legacy root page modules and `Main_GUI_v1_1_2.py` are intentionally absent from the clean package. Runtime caches, reports and local state are also excluded.

## Safety

- No database schema changes.
- No camera, PLC, training or inference logic changes.
- Existing RBAC, audit, backup, diagnostics and login-security controls remain active.
- The legacy `app_core.ui_foundation` import remains as a compatibility facade.

## Verification

Run `python -m unittest discover -s tests -v`, then `python Main_GUI.py`. Verify login, reset password, Dashboard, Machines, Projects, User Management, System Maintenance and Diagnostics.
