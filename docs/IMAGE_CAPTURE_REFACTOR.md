# Image Capturing architecture

The Image Capturing feature is divided into three layers:

- `pages/capture/page.py` contains the seven-step PyQt5 workflow and user interaction.
- `services/capture/backend.py` contains camera discovery, Arena/Lucid setup, Hikrobot integration, frame acquisition, image writing, and capture workers.
- `ui/theme/capture.py` contains the dedicated white industrial stylesheet and standalone palette.

`camera_app.py` remains as a compatibility entry point. Existing code may still import
`CameraWidget` from it, while the main application imports from `pages.capture` directly.

The refactor preserves capture modes, camera overrides, MongoDB persistence, project output
folders, filenames, preview behavior, worker signals, and optional SDK loading.

## Simulation mode

Set `EYRES_CAMERA_SIMULATION=1` before starting the application to expose virtual Lucid and
Hikrobot devices. Simulation generates Mono8 preview/capture frames and saves them below a
`simulation` subfolder. It never connects to physical camera SDK devices. Set the value to
`0`, or open a new terminal without the variable, to restore hardware mode.
