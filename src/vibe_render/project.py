"""Copy a bounded source snapshot, keeping the original working tree untouched."""

# Git supplies candidate filenames. Filesystem checks stop links from copying outside the project.
import hashlib
import os
import stat
import subprocess
from pathlib import Path

# These local state folders and conventional secret files are never uploaded, even if tracked.
SKIP_DIRS = {
    ".git",
    ".vibe",
    ".vibe-render",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".ssh",
    ".aws",
    ".kube",
    ".terraform",
    ".next",
    "dist",
    "build",
}
SKIP_NAMES = {".npmrc", ".pypirc", "credentials", "credentials.json", "id_rsa", "id_ed25519"}
MAX_FILES, MAX_BYTES = 5000, 50 * 1024 * 1024


def git(root: Path, *args: str) -> bytes:
    """Ask Git about files, disabling its optional host-side filesystem watcher."""
    return subprocess.check_output(
        ["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], stderr=subprocess.PIPE
    )


def excluded(path: Path) -> bool:
    """Recognize files that should not cross from the computer into the sandbox."""
    return (
        any(part in SKIP_DIRS for part in path.parts)
        or path.name.startswith(".env")
        or path.name in SKIP_NAMES
        or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
    )


def snapshot(root: Path, target: Path) -> dict:
    """Copy current file contents, including uncommitted edits, and record their hashes."""
    root = root.resolve(strict=True)
    if Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip()).resolve() != root:
        raise ValueError("Choose the Git repository root, not a subdirectory")
    names = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")
    manifest, skipped, total = {}, [], 0
    target.mkdir(parents=True, exist_ok=False)
    for raw in sorted(set(filter(None, names))):
        rel = Path(os.fsdecode(raw))
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Git returned an unsafe filename")
        if excluded(rel):
            skipped.append(str(rel))
            continue
        source = root / rel
        if not source.exists() and not source.is_symlink():
            continue  # A deleted tracked file is absent from the starting snapshot too.
        # Resolve every parent, and reject links rather than following them outside the project.
        if source.is_symlink() or any(p.is_symlink() for p in source.parents if p != root):
            raise ValueError(f"Source snapshot does not support symbolic links: {rel}")
        if not source.is_file():
            raise ValueError(f"Source snapshot requires regular files: {rel}")
        with source.open("rb") as handle:
            data = handle.read(MAX_BYTES - total + 1)
        total += len(data)
        if total > MAX_BYTES or len(manifest) >= MAX_FILES:
            raise ValueError("Source snapshot exceeds 50 MiB or 5000 files")
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o755 if source.stat().st_mode & stat.S_IXUSR else 0o644)
        manifest[str(rel)] = hashlib.sha256(data).hexdigest()
    if not manifest:
        raise ValueError("No source files remain after exclusions")
    return {"files": manifest, "bytes": total, "excluded": skipped}
