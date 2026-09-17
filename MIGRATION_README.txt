EYRES v1.2.0 - WHITE UI PHASE 1
================================

This is a complete clean baseline, not an overlay patch.

1. Extract the Eyres folder as:
       D:\Eyres_AI_Platform_v1.2.0

2. Reuse the tested Python environment:
       D:\Eyres_AI_Platform_v1.1\eyres_env\Scripts\activate

3. Run verification from the new folder:
       cd D:\Eyres_AI_Platform_v1.2.0
       python -m unittest discover -s tests -v
       python Main_GUI.py

Do not copy this package over v1.1 during initial testing. Keeping v1.1 unchanged
provides an immediate rollback. Runtime MongoDB data is not moved or modified.

PHASE 1 MIGRATED UI
-------------------
- Login and password reset
- Application shell and navigation
- Dashboard
- Machines and machine dialog
- Projects and project dialog
- User Management
- System Maintenance
- Diagnostics

PHASE 2 (UNCHANGED INTERNAL UI FOR NOW)
---------------------------------------
- Image Capturing
- Annotation
- Augmentation
- Model Training
- ROI
- PLC Live
- Live inspection

The supported launcher remains Main_GUI.py.
