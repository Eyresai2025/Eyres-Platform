"""Generate an offline CycloneDX JSON SBOM and dependency consistency report."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import sys
from uuid import uuid4

NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(?:==\s*([^\s;]+))?")

def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()

def read_requirements(path: Path) -> dict[str, dict]:
    result = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-r", "--")):
            continue
        match = NAME_RE.match(line)
        if match:
            result[canonical(match.group(1))] = {
                "name": match.group(1), "required_version": match.group(2),
                "declaration": line, "line": number,
            }
    return result

def installed_packages() -> dict[str, dict]:
    packages = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or dist.name
        license_name = dist.metadata.get("License-Expression") or dist.metadata.get("License")
        if not license_name:
            classifiers = dist.metadata.get_all("Classifier") or []
            license_name = next((x.split(" :: ")[-1] for x in classifiers if x.startswith("License ::")), "UNKNOWN")
        packages[canonical(name)] = {
            "name": name, "version": dist.version,
            "license": str(license_name).strip()[:300] or "UNKNOWN",
        }
    return packages

def build(requirements: Path) -> tuple[dict, dict]:
    declared, installed = read_requirements(requirements), installed_packages()
    components, missing, mismatched, unpinned = [], [], [], []
    for key, item in sorted(installed.items()):
        declared_item = declared.get(key)
        component = {"type": "library", "name": item["name"], "version": item["version"],
                     "bom-ref": f"pkg:pypi/{key}@{item['version']}",
                     "purl": f"pkg:pypi/{key}@{item['version']}",
                     "licenses": [{"license": {"name": item["license"]}}],
                     "properties": [{"name": "eyres:direct-dependency",
                                     "value": str(bool(declared_item)).lower()}]}
        components.append(component)
    for key, item in sorted(declared.items()):
        actual = installed.get(key)
        if not actual:
            missing.append(item["declaration"])
        elif item["required_version"] and actual["version"] != item["required_version"]:
            mismatched.append({"package": item["name"], "required": item["required_version"],
                               "installed": actual["version"]})
        if not item["required_version"]:
            unpinned.append(item["declaration"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    bom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{uuid4()}",
           "version": 1, "metadata": {"timestamp": now,
           "component": {"type": "application", "name": "EYRES AI Inspection Platform", "version": "1.1.6"},
           "properties": [{"name": "eyres:python", "value": platform.python_version()},
                          {"name": "eyres:platform", "value": platform.platform()}]},
           "components": components}
    report = {"generated_utc": now, "requirements_file": str(requirements),
              "declared_count": len(declared), "installed_count": len(installed),
              "missing": missing, "version_mismatches": mismatched, "unpinned": unpinned,
              "status": "PASS" if not (missing or mismatched or unpinned) else "REVIEW"}
    return bom, report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--output-dir", default="reports/dependencies")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    requirements, output = Path(args.requirements).resolve(), Path(args.output_dir).resolve()
    if not requirements.is_file():
        raise SystemExit(f"Requirements file not found: {requirements}")
    output.mkdir(parents=True, exist_ok=True)
    bom, report = build(requirements)
    (output / "sbom.cdx.json").write_text(json.dumps(bom, indent=2), encoding="utf-8")
    (output / "dependency_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"SBOM: {output / 'sbom.cdx.json'}")
    print(f"Report: {output / 'dependency_report.json'}")
    print(f"Status: {report['status']} | missing={len(report['missing'])} | "
          f"mismatched={len(report['version_mismatches'])} | unpinned={len(report['unpinned'])}")
    if args.strict and report["status"] != "PASS":
        raise SystemExit(2)

if __name__ == "__main__": main()
