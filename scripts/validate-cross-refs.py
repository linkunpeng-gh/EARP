#!/usr/bin/env python3
"""Cross-reference validator — checks consistency across PRD, L2 spec, and SDK code.

Rules:
  R1: L2 spec version references — if A depends on B v1.0 but B is v1.1, flag it
  R2: PRD dependency vs actual spec version — PRD says Runtime v1.2, file header is v1.3?
  R3: SDKMUST coverage — MUST clauses in specs should have corresponding tests
  R4: AC vs test file coverage — each PRD AC should be referenced in test files
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ── Model ──

class Finding:
    def __init__(self, level: str, rule: str, source: str, detail: str):
        self.level = level  # P0/P1/P2
        self.rule = rule
        self.source = source
        self.detail = detail

    def __str__(self):
        return f"[{self.level}] {self.rule}: {self.source} — {self.detail}"

# ── Helpers ──

def grep(pattern: str, path: Path) -> list[str]:
    """Return list of matching lines from file."""
    if not path.exists():
        return []
    return [line.rstrip() for line in path.read_text().splitlines() if re.search(pattern, line)]

def extract_version(text: str) -> str | None:
    """Extract version from text like 'v1.2' or 'v1.1'."""
    m = re.search(r'v(\d+\.\d+)', text)
    return m.group(0) if m else None

def extract_name_and_version(text: str) -> tuple[str | None, str | None]:
    """Extract spec name and version from a dependency line like 'Runtime Spec v1.2'."""
    # Pattern: "L2-XX-NAME v1.X" or "NAME Spec v1.X" or "NAME v1.X"
    m = re.match(r'.*(?:L2-\d+-)?(?:\*\*)?([A-Za-z\s/-]+?)\s*(?:Spec|Specification)?\s*(v?\d+\.\d+)', text)
    if not m:
        return None, None
    name = m.group(1).strip().lower()
    ver = m.group(2).strip()
    return name, ver

# ── R1: Spec-to-spec version references ──

def r1_spec_cross_versions() -> list[Finding]:
    """Check version consistency across L2 spec dependency declarations."""
    findings = []
    spec_versions: dict[str, str] = {}  # canonical name → version

    spec_dir = ROOT / "arch" / "L2"
    for md_file in sorted(spec_dir.rglob("*.md")):
        # Read header to get canonical version
        text = md_file.read_text()
        head = text[:500]
        ver_match = re.search(r'版本[:：]\s*v?(\d+\.\d+)', head)
        if not ver_match:
            continue
        canonical = f"v{ver_match.group(1)}"

        key = md_file.stem.lower().replace("-specification", "").replace("-", " ")
        spec_versions[key] = canonical

    # Now check each spec's dependency list
    for md_file in sorted(spec_dir.rglob("*.md")):
        for line in grep(r'v\d+\.\d+', md_file):
            if '**版本' in line:
                continue  # skip self header
            # Look for version references
            refs = re.findall(r'([A-Za-z\s/-]+?)\s*(?:Spec|Specification)?\s*v(\d+\.\d+)', line)
            for name_raw, ver in refs:
                name = name_raw.strip().lower()
                # Normalize name
                for canon_key, canon_ver in spec_versions.items():
                    if canon_key in name or name in canon_key:
                        if ver != canon_ver:
                            findings.append(Finding(
                                "P1", "R1",
                                str(md_file.relative_to(ROOT)),
                                f"references {name_raw.strip()} {ver} but canonical is {canon_ver} ({canon_key})"
                            ))
                        break

    return findings

# ── R2: PRD dependency vs actual spec version ──

def r2_prd_vs_spec_versions() -> list[Finding]:
    """Check PRD dependency declarations against actual spec file versions."""
    findings = []

    # Build canonical map from spec files
    spec_versions: dict[str, str] = {}
    for md_file in (ROOT / "arch" / "L2").rglob("*.md"):
        text = md_file.read_text()[:500]
        ver_match = re.search(r'版本[:：]\s*v?(\d+\.\d+)', text)
        if not ver_match:
            continue
        canonical = f"v{ver_match.group(1)}"
        key = md_file.stem.lower().replace("-specification", "").replace("-", " ")
        spec_versions[key] = canonical

    # Check PRD files
    for md_file in sorted((ROOT / "prd").rglob("*.md")):
        for line in grep(r'(Runtime|Security|Audit|Observation|Workflow|Tenant|Capability|Policy)\s*(Spec)?\s*v\d+\.\d+', md_file):
            for name_raw, ver in re.findall(r'([A-Za-z\s/-]+?)\s*(?:Spec)?\s*(v\d+\.\d+)', line):
                name = name_raw.strip().lower()
                for canon_key, canon_ver in spec_versions.items():
                    if canon_key in name or name in canon_key:
                        if ver != canon_ver:
                            findings.append(Finding(
                                "P1", "R2",
                                str(md_file.relative_to(ROOT)),
                                f"depends on {name_raw.strip()} {ver} but canonical is {canon_ver}"
                            ))
                        break

    return findings

# ── R3: SDKMUST → test coverage ──

def r3_sdkmust_test_coverage() -> list[Finding]:
    """Check that each spec file's MUST clauses have corresponding test files."""
    findings = []

    for spec_file in sorted((ROOT / "arch" / "L2").rglob("*.md")):
        must_count = len(grep(r'^\s*MUST:', spec_file))
        if must_count == 0:
            continue

        # Map spec → expected test area
        spec_stem = spec_file.stem.lower()
        test_map = {
            "security": ["test_masking.py", "test_key_source.py", "test_credential.py", "test_audit.py", "test_guard.py", "test_security.py", "test_sandbox.py"],
            "runtime": ["test_invoker_http.py", "test_mock_runtime.py"],
            "workflow": ["test_sandbox.py"],  # partial
            "observation": ["test_*.py"],      # generic
        }

        # Find matching test area
        total_tests = 0
        for key, test_files in test_map.items():
            if key in spec_stem:
                for tf in test_files:
                    for t in ROOT.rglob(tf):
                        total_tests += 1
                break

        if total_tests == 0:
            findings.append(Finding(
                "P2", "R3",
                str(spec_file.relative_to(ROOT)),
                f"{must_count} MUST clauses, 0 matching test files found"
            ))

    return findings

# ── R4: AC vs test file coverage ──

def r4_ac_test_coverage() -> list[Finding]:
    """Check PRD AC coverage in test files — heuristic: count ACs and test functions."""
    findings = []

    for prd_file in sorted((ROOT / "prd").rglob("*.md")):
        ac_lines = grep(r'AC-\d+', prd_file)
        ac_count = len(ac_lines)
        if ac_count == 0:
            continue

        # Heuristic: look for related test files by keyword in AC descriptions
        keywords: set[str] = set()
        for line in ac_lines:
            for word in ["masking", "credential", "audit", "guard", "key_source",
                         "connector", "runtime", "plugin", "sandbox", "security"]:
                if word in line.lower():
                    keywords.add(word)

        related_tests = 0
        for kw in keywords:
            for test_file in ROOT.rglob(f"test_{kw}*.py"):
                related_tests += 1

        if related_tests == 0 and keywords:
            findings.append(Finding(
                "P2", "R4",
                str(prd_file.relative_to(ROOT)),
                f"{ac_count} ACs but no matching test files for keywords: {keywords}"
            ))

    return findings

# ── Main ──

def main():
    findings: list[Finding] = []
    findings.extend(r1_spec_cross_versions())
    findings.extend(r2_prd_vs_spec_versions())
    findings.extend(r3_sdkmust_test_coverage())
    findings.extend(r4_ac_test_coverage())

    if not findings:
        print("✅ All cross-reference checks passed.")
        return 0

    by_level = defaultdict(list)
    for f in findings:
        by_level[f.level].append(f)

    print(f"🔍 Cross-Reference Validation Report\n")
    for level in ("P0", "P1", "P2"):
        items = by_level.get(level, [])
        if items:
            print(f"## {level} ({len(items)} findings)")
            for f in items:
                print(f"  {f}")
            print()

    total = len(findings)
    print(f"Total: {total} findings (P0={len(by_level['P0'])}, P1={len(by_level['P1'])}, P2={len(by_level['P2'])})")

    # Exit code: non-zero if P0 or P1 found
    return 1 if by_level["P0"] or by_level["P1"] else 0

if __name__ == "__main__":
    sys.exit(main())
