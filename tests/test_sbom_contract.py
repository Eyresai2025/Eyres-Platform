import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from tools.generate_sbom import build, canonical, read_requirements

class SBOMTests(unittest.TestCase):
    def test_name_normalization(self):
        self.assertEqual(canonical("PyQt5_sip"), "pyqt5-sip")

    def test_requirements_parser(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "requirements.txt"
            path.write_text("Demo_Pkg==1.2.3\n# note\nOther>=2\n", encoding="utf-8")
            parsed = read_requirements(path)
            self.assertEqual(parsed["demo-pkg"]["required_version"], "1.2.3")
            self.assertIsNone(parsed["other"]["required_version"])

    def test_report_detects_missing_mismatch_and_unpinned(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "requirements.txt"
            path.write_text("alpha==1.0\nbeta==2.0\ngamma>=3\n", encoding="utf-8")
            fake = {"alpha": {"name": "alpha", "version": "0.9", "license": "MIT"},
                    "gamma": {"name": "gamma", "version": "3.1", "license": "MIT"}}
            with patch("tools.generate_sbom.installed_packages", return_value=fake):
                bom, report = build(path)
            self.assertEqual(bom["bomFormat"], "CycloneDX")
            self.assertEqual(len(report["missing"]), 1)
            self.assertEqual(len(report["version_mismatches"]), 1)
            self.assertEqual(len(report["unpinned"]), 1)
            self.assertEqual(report["status"], "REVIEW")

if __name__ == "__main__": unittest.main()
