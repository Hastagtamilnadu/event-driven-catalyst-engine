from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Common secret regex patterns
PATTERNS: dict[str, re.Pattern[str]] = {
    "Google / Gemini API Key": re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    "OpenAI API Key": re.compile(r"sk-[a-zA-Z0-9]{32,}"),
    "AWS Access Key ID": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Generic Private Key": re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH|PGP)? ?PRIVATE KEY-----"),
    "Hardcoded Password in String": re.compile(r'(?i)(api[_-]?key|password|secret)[ \t]*[:=][ \t]*["\']([a-zA-Z0-9_\-!@#$%^&*]{8,})["\']'),
}

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "backups",
    "logs",
    "dist",
    "build",
}

EXCLUDED_FILES = {
    "uv.lock",
    "secret_scan.py",
    ".env",
}


def scan_file(path: Path) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return findings

    lines = content.splitlines()
    for line_idx, line in enumerate(lines, start=1):
        # Ignore comments or mock tokens
        if "mock" in line.lower() or "example" in line.lower() or "test" in line.lower():
            continue
        for name, pattern in PATTERNS.items():
            match = pattern.search(line)
            if match:
                # Mask secret
                matched_text = match.group(0)
                masked = matched_text[:4] + "..." + matched_text[-4:] if len(matched_text) > 8 else "***"
                findings.append((name, line_idx, masked))
    return findings


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    print(f"Scanning codebase for exposed secrets at: {project_root}")

    total_findings = 0
    scanned_files = 0

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for f in files:
            if f in EXCLUDED_FILES or f.endswith((".db", ".parquet", ".pdf", ".png", ".jpg", ".pyc")):
                continue
            file_path = Path(root) / f
            scanned_files += 1
            findings = scan_file(file_path)
            if findings:
                rel_path = file_path.relative_to(project_root)
                for secret_type, line_num, masked in findings:
                    print(f"  [ALERT] {rel_path}:{line_num} - {secret_type} ({masked})")
                    total_findings += 1

    print(f"Secret scan completed. {scanned_files} files scanned.")
    if total_findings > 0:
        print(f"FAILED: {total_findings} potential secret(s) found!")
        sys.exit(1)
    else:
        print("PASS: No secret scanner findings unresolved.")
        sys.exit(0)


if __name__ == "__main__":
    main()
