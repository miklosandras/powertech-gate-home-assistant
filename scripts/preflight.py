#!/usr/bin/env python3
"""Local pre-release validation for the custom integration."""

from __future__ import annotations

import json
from pathlib import Path
import py_compile
import sys

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "powertech_gate"

errors: list[str] = []

for path in COMP.glob("*.py"):
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as err:
        errors.append(str(err))

for path in (
    COMP / "manifest.json",
    COMP / "translations" / "en.json",
    COMP / "translations" / "hu.json",
    ROOT / "hacs.json",
):
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001 - release helper
        errors.append(f"{path}: {err}")

manifest = json.loads((COMP / "manifest.json").read_text(encoding="utf-8"))
for field in ("documentation", "issue_tracker"):
    if "OWNER/REPOSITORY" in str(manifest.get(field, "")):
        errors.append(f"manifest.json: replace OWNER/REPOSITORY in {field}")

if not manifest.get("codeowners"):
    errors.append("manifest.json: add at least one GitHub codeowner")

if errors:
    print("Preflight FAILED:")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print("Preflight OK")
