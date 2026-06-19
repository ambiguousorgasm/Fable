#!/usr/bin/env python3
"""
build_public_links.py — manage the FABLE Table Engine public working tree.

MODES
-----
  linked   (default)
           Create symlinks in the public tree pointing back to the dev repo.
           Use for local development. Each symlinked path resolves through to
           the live dev repo file — changes are immediate. Do NOT publish
           linked-mode symlinks as a release; they only work if consumers
           have the same sibling repo layout.

  release  Copy real files into the public tree, validate for private content,
           and produce a self-contained ZIP suitable for public distribution.

USAGE
-----
  python scripts/build_public_links.py [--mode linked|release] [options]

  Options:
    --mode linked|release   default: linked
    --output PATH           default: ../fable-table-engine-public
    --dry-run               print what would happen; do not write files
    --no-zip                skip ZIP creation in release mode

EDITING THE PUBLIC TREE
-----------------------
  - Edit ALLOWLIST below to add or remove public files/directories.
  - Edit FORBIDDEN_NAMES to extend the private-content blocklist.
  - Never add private/internal files to ALLOWLIST.
  - Run with --dry-run to preview changes before applying.

AUTHORITY
---------
  The dev repo is the source of truth. Edit there; sync here.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEV_REPO = SCRIPT_DIR.parent                              # fable-table-engine/
DEFAULT_PUBLIC = DEV_REPO.parent / "fable-table-engine-public"

# ---------------------------------------------------------------------------
# Allowlist
# Each entry: (source_relative_to_DEV_REPO, destination_name_in_public_tree)
# Only these entries are created in the public tree. Everything else is private.
# ---------------------------------------------------------------------------

ALLOWLIST: list[tuple[str, str]] = [
    ("src",              "src"),           # Python source package
    ("tests",            "tests"),         # Full test suite
    ("schemas",          "schemas"),       # JSON schemas
    ("static",           "static"),        # Static assets (fable_rules.pdf)
    ("pyproject.toml",   "pyproject.toml"), # Package manifest
    (".env.example",     ".env.example"),  # Environment variable template
    (".gitignore",       ".gitignore"),    # Git ignore rules
    ("public/README.md", "README.md"),     # Public-facing README (not dev README)
    ("public/docs",      "docs"),          # Public-safe docs only
]

# ---------------------------------------------------------------------------
# Forbidden names — must NEVER appear in the public tree by filename/dirname.
# ---------------------------------------------------------------------------

FORBIDDEN_NAMES: frozenset[str] = frozenset({
    ".claude",
    ".env",                          # actual env file (not .env.example)
    ".git",
    ".mcp.json",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "00_README.md",
    "CHANGELOG.md",
    "CLAUDE.md",
    "COMPONENTS.md",
    "DECISIONS.md",
    "FABLE_Table_Engine_Blueprint.md",
    "IMPLEMENTATION_PLAN.md",
    "MCP_SETUP.md",
    "STATUS.md",
    "fable_engine.md",
    "image_prompts",
    "memory",
    "screenshots",
    "uploads",
    "secrets",
    "credentials.json",
})

# ---------------------------------------------------------------------------
# Forbidden content patterns — scanned in text files during release validation.
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("linux-local-path",  re.compile(r"/home/[a-zA-Z0-9_]+")),
    ("macos-local-path",  re.compile(r"/Users/[a-zA-Z0-9_]+")),
    ("anthropic-api-key", re.compile(r"sk-ant-[a-zA-Z0-9]")),
    ("generic-api-key",   re.compile(r"(?i)api[_\-]?key\s*=\s*['\"]?sk-")),
    ("private-pem",       re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----")),
]

_TEXT_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml",
    ".sh", ".bash", ".cfg", ".ini", ".example",
    ".ts", ".tsx", ".js", ".jsx", ".html", ".css",
})

# ---------------------------------------------------------------------------
# DO_NOT_EDIT_HERE.md content (written as a real file, never a symlink)
# ---------------------------------------------------------------------------

_DO_NOT_EDIT = """\
# DO NOT EDIT FILES IN THIS DIRECTORY

This directory is a **generated public working tree** for the FABLE Table Engine.

- **Linked mode:** files here are symlinks to `fable-table-engine/`. Editing
  through this tree modifies the dev repo — do not do it.
- **Release mode:** files here are copies. Changes are overwritten on the next
  release build.

**Edit source files in `fable-table-engine/` only.**

---

## Refresh this tree

    # Local development (symlinks):
    python fable-table-engine/scripts/build_public_links.py --mode linked

    # Public release (real files + ZIP):
    python fable-table-engine/scripts/build_public_links.py --mode release

---

## What is included (allowlist)

    src/             Python source package
    tests/           Full test suite
    schemas/         JSON schemas
    static/          Static assets
    pyproject.toml   Package manifest
    .env.example     Environment variable template
    .gitignore       Git ignore rules
    README.md        Public-facing README (from public/README.md in dev repo)
    docs/            Public documentation (from public/docs/ in dev repo)

## What is NOT included

    memory/, uploads/, CLAUDE.md, .claude/, .mcp.json
    IMPLEMENTATION_PLAN.md, DECISIONS.md, COMPONENTS.md
    STATUS.md, CHANGELOG.md, FABLE_Table_Engine_Blueprint.md
    00_README.md, fable_engine.md, docs/MCP_SETUP.md
    .env, .venv/, .git/, screenshots/, image_prompts/
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str, dry_run: bool = False) -> None:
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}{msg}")


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS


def _check_forbidden_name(name: str) -> bool:
    """Return True if the name matches a forbidden entry."""
    return name in FORBIDDEN_NAMES


def _symlink_target(symlink_location: Path, target: Path) -> Path:
    """Compute a relative path from symlink_location's parent to target."""
    return Path(os.path.relpath(target, symlink_location.parent))


def _validate_allowlist(dev_repo: Path) -> list[str]:
    """Return list of warning messages for allowlist entries whose sources don't exist."""
    warnings = []
    for src_rel, _ in ALLOWLIST:
        src = dev_repo / src_rel
        if not src.exists():
            warnings.append(f"  WARNING: allowlist source does not exist: {src_rel}")
    return warnings


def _collect_names_in_dir(path: Path) -> set[str]:
    """Recursively collect all file/directory names under path."""
    names: set[str] = set()
    for p in path.rglob("*"):
        names.add(p.name)
    return names


def _scan_file_content(path: Path) -> list[str]:
    """Scan a text file for forbidden content patterns. Return list of violation messages."""
    violations: list[str] = []
    if not _is_text_file(path):
        return violations
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return violations
    for label, pattern in _FORBIDDEN_PATTERNS:
        m = pattern.search(text)
        if m:
            violations.append(f"  FORBIDDEN-CONTENT [{label}] in {path}: matched {m.group()!r}")
    return violations


# ---------------------------------------------------------------------------
# Linked mode
# ---------------------------------------------------------------------------

def _mode_linked(public_dir: Path, dev_repo: Path, dry_run: bool) -> int:
    """
    Create the public tree using symlinks.
    - Removes stale symlinks that we control (i.e. whose names appear in ALLOWLIST).
    - Creates relative symlinks for each allowlist entry.
    - Writes DO_NOT_EDIT_HERE.md as a real file.
    - Never touches files/dirs not in our allowlist.
    """
    errors = 0

    if not dry_run:
        public_dir.mkdir(parents=True, exist_ok=True)

    _log(f"Public tree: {public_dir}", dry_run)
    _log(f"Dev repo:    {dev_repo}", dry_run)
    _log("Mode: linked (symlinks)", dry_run)
    print()

    # -- Validate allowlist sources
    for w in _validate_allowlist(dev_repo):
        print(w)

    # -- Remove stale symlinks we control
    managed_dsts = {dst for _, dst in ALLOWLIST} | {"DO_NOT_EDIT_HERE.md"}
    if public_dir.exists():
        for dst_name in managed_dsts:
            existing = public_dir / dst_name
            if existing.is_symlink():
                _log(f"  remove stale symlink: {dst_name}", dry_run)
                if not dry_run:
                    existing.unlink()

    # -- Create symlinks
    for src_rel, dst_name in ALLOWLIST:
        src = dev_repo / src_rel
        dst = public_dir / dst_name

        if not src.exists():
            print(f"  SKIP (source missing): {src_rel} -> {dst_name}")
            continue

        rel_target = _symlink_target(dst, src)

        _log(f"  symlink: {dst_name} -> {rel_target}", dry_run)
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_symlink() or dst.exists():
                if dst.is_symlink():
                    dst.unlink()
                else:
                    _log(f"  WARNING: {dst_name} exists as a real file/dir; skipping", dry_run)
                    errors += 1
                    continue
            dst.symlink_to(rel_target)

    # -- Write DO_NOT_EDIT_HERE.md as a real file (not a symlink)
    warning_file = public_dir / "DO_NOT_EDIT_HERE.md"
    _log("  write: DO_NOT_EDIT_HERE.md (real file, not a symlink)", dry_run)
    if not dry_run:
        warning_file.write_text(_DO_NOT_EDIT, encoding="utf-8")

    print()
    if errors:
        print(f"Linked mode complete with {errors} error(s). Review warnings above.")
    else:
        print("Linked mode complete.")
    print()
    print("IMPORTANT: This public tree uses symlinks. It is suitable for local")
    print("development only. Do NOT publish symlinks to GitHub or distribute")
    print("them as a release package — they will not work on other machines.")
    print()
    print("To create a distributable release package:")
    print(f"  python {Path(__file__).name} --mode release")
    return errors


# ---------------------------------------------------------------------------
# Release mode
# ---------------------------------------------------------------------------

def _mode_release(
    public_dir: Path,
    dev_repo: Path,
    dry_run: bool,
    create_zip: bool,
) -> int:
    """
    Copy real files into the public tree, validate for private content,
    optionally create a ZIP.
    """
    errors = 0

    _log(f"Public tree: {public_dir}", dry_run)
    _log(f"Dev repo:    {dev_repo}", dry_run)
    _log("Mode: release (real files)", dry_run)
    print()

    # -- Validate allowlist sources
    for w in _validate_allowlist(dev_repo):
        print(w)

    # -- Wipe and recreate output directory
    if public_dir.exists():
        _log(f"  removing existing output dir: {public_dir}", dry_run)
        if not dry_run:
            shutil.rmtree(public_dir)

    _log(f"  creating output dir: {public_dir}", dry_run)
    if not dry_run:
        public_dir.mkdir(parents=True)

    # -- Copy each allowlist entry
    for src_rel, dst_name in ALLOWLIST:
        src = dev_repo / src_rel
        dst = public_dir / dst_name

        if not src.exists():
            print(f"  SKIP (source missing): {src_rel}")
            continue

        if src.is_dir():
            _log(f"  copy dir:  {src_rel}/ -> {dst_name}/", dry_run)
            if not dry_run:
                shutil.copytree(
                    src, dst,
                    symlinks=False,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache"),
                )
        else:
            _log(f"  copy file: {src_rel} -> {dst_name}", dry_run)
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    # -- Write DO_NOT_EDIT_HERE.md
    warning_file = public_dir / "DO_NOT_EDIT_HERE.md"
    _log("  write: DO_NOT_EDIT_HERE.md", dry_run)
    if not dry_run:
        warning_file.write_text(_DO_NOT_EDIT, encoding="utf-8")

    print()

    # -- Validate output
    if not dry_run:
        print("Validating release output...")
        validation_errors = _validate_release_output(public_dir)
        if validation_errors:
            print(f"\n{'='*60}")
            print("VALIDATION FAILED — do not publish this release:")
            print('='*60)
            for msg in validation_errors:
                print(msg)
            print('='*60)
            errors += len(validation_errors)
        else:
            print("  Validation passed: no private content detected.")
    else:
        print("[DRY-RUN] Skipping validation (dry run).")

    # -- Create ZIP
    if create_zip and not errors and not dry_run:
        zip_path = _create_zip(public_dir)
        print(f"\nRelease ZIP: {zip_path}")
    elif create_zip and dry_run:
        zip_path = public_dir.parent / f"{public_dir.name}.zip"
        _log(f"  would create ZIP: {zip_path}", dry_run)
    elif errors:
        print("\nSkipping ZIP creation due to validation errors.")

    print()
    if errors:
        print(f"Release mode FAILED with {errors} error(s). Do not publish.")
        print("Fix the issues above, then rerun.")
    else:
        print("Release mode complete.")
        if not dry_run and create_zip:
            print()
            print("To publish:")
            print(f"  1. Inspect {public_dir}")
            print(f"  2. Run tests from the release dir:")
            print(f"       cd {public_dir}")
            print(f"       python3 -m venv .venv && ./.venv/bin/pip install -e '.[dev]'")
            print(f"       ./.venv/bin/python -m pytest -q")
            print(f"  3. Publish the ZIP or push {public_dir} to the public Git repo.")

    return errors


def _validate_release_output(public_dir: Path) -> list[str]:
    """
    Scan the release output for private content.
    Returns a list of violation messages (empty = clean).
    """
    violations: list[str] = []

    for item in public_dir.rglob("*"):
        # Skip DO_NOT_EDIT_HERE.md itself (it mentions private paths deliberately)
        if item.name == "DO_NOT_EDIT_HERE.md":
            continue

        # Check forbidden names
        if _check_forbidden_name(item.name):
            violations.append(f"  FORBIDDEN-NAME: {item.relative_to(public_dir)}")
            continue

        # Check for symlinks (should not appear in release mode)
        if item.is_symlink():
            violations.append(f"  UNEXPECTED-SYMLINK: {item.relative_to(public_dir)}")
            continue

        # Check file content
        if item.is_file():
            violations.extend(_scan_file_content(item))

    return violations


def _create_zip(public_dir: Path) -> Path:
    """Create a ZIP of the release directory adjacent to it."""
    zip_path = public_dir.parent / f"{public_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in public_dir.rglob("*"):
            if item.is_file() and not item.is_symlink():
                arcname = item.relative_to(public_dir.parent)
                zf.write(item, arcname)
    return zip_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or update the FABLE Table Engine public working tree.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["linked", "release"],
        default="linked",
        help="linked: symlinks for local dev (default). release: real files for distribution.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Path for the public tree (default: {DEFAULT_PUBLIC})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen; do not write files.",
    )
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="Skip ZIP creation in release mode.",
    )
    args = parser.parse_args(argv)

    public_dir: Path = args.output if args.output else DEFAULT_PUBLIC

    print(f"FABLE Table Engine — public tree builder")
    print(f"{'='*50}")

    if args.mode == "linked":
        return _mode_linked(public_dir, DEV_REPO, args.dry_run)
    else:
        return _mode_release(public_dir, DEV_REPO, args.dry_run, not args.no_zip)


if __name__ == "__main__":
    sys.exit(main())
