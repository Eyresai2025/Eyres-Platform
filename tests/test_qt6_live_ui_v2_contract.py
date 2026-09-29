from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "live" / "page_qt6.py"


def source():
    return PAGE.read_text(encoding="utf-8")


def test_live_v2_parses():
    ast.parse(source())


def test_buttons_have_safe_width_contract():
    s = source()
    assert "def sizeHint(self):" in s
    assert "self._safe_width" in s
    assert "Configure Session" in s
    assert "button.setMinimumWidth(max(button.minimumWidth()" in s


def test_primary_button_uses_white_text_and_icon():
    s = source()
    assert 'is_primary = self.objectName() == "StartLiveButton"' in s
    assert 'text_color = "#FFFFFF"' in s
    assert '_tinted_pixmap(self._icon_normal, "#FFFFFF")' in s


def test_configuration_builds_camera_slots_immediately():
    s = source()
    assert "def _apply_configured_camera_slots" in s
    assert "self._apply_configured_camera_slots()" in s
    assert 'f"{count} camera slot(s) configured' in s


def test_configured_camera_status_is_preserved():
    s = source()
    assert 'f"{configured} configured · {detected} detected"' in s
    assert 'f"{detected_count} / {count} configured"' in s


def test_anomaly_ui_readability_changes():
    s = source()
    assert "side.setFixedWidth(320)" in s
    assert 'template_btn.setMinimumWidth' in s
    assert 'detect_btn.setMinimumWidth' in s
    assert "font-size:8.6px" in s


def test_preview_canvas_is_forced_dark():
    s = source()
    assert "background-color:#111827" in s
