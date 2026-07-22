"""Safe extraction of an uploaded Agent Skills zip archive.

Handles the three classic dangers of extracting an arbitrary user-supplied
zip: path traversal ("zip-slip", where an entry like `../../etc/passwd`
escapes the destination directory), zip bombs (a tiny compressed file that
expands to gigabytes), and archive bombs by file count (millions of empty
entries). None of the extracted files are ever executed by this module —
see app/skills/package_spec.py's module docstring for why that's fine here.
"""
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path


class SkillPackageExtractError(Exception):
    pass


@dataclass
class ExtractedPackage:
    root_dir_name: str  # the single top-level directory name inside the zip
    extracted_path: Path  # where the contents now live on disk (package's own dir)
    file_manifest: list[str]  # relative paths of every file, relative to extracted_path


def _safe_relative_path(name: str) -> Path:
    """Normalizes a zip entry name and raises if it would escape its parent
    via '..' or an absolute path — the zip-slip check."""
    # Zip entries always use "/" regardless of platform.
    normalized = os.path.normpath(name)
    if normalized.startswith("..") or Path(normalized).is_absolute():
        raise SkillPackageExtractError(f"Unsafe path in archive: {name!r}")
    return Path(normalized)


def extract_skill_zip(
    zip_bytes: bytes,
    dest_dir: Path,
    *,
    max_extracted_bytes: int,
    max_files: int,
) -> ExtractedPackage:
    """Extracts a skill zip into `dest_dir` (which must already exist and be
    empty/dedicated to this package). Expects exactly one top-level
    directory in the archive (the skill's own directory, per spec) containing
    SKILL.md — raises SkillPackageExtractError otherwise."""
    import io

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise SkillPackageExtractError(f"Not a valid zip file: {e}")

    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise SkillPackageExtractError("Zip archive contains no files")
    if len(infos) > max_files:
        raise SkillPackageExtractError(f"Archive contains {len(infos)} files, exceeding the {max_files} limit")

    total_size = sum(i.file_size for i in infos)
    if total_size > max_extracted_bytes:
        raise SkillPackageExtractError(
            f"Archive would extract to {total_size} bytes, exceeding the {max_extracted_bytes} byte limit"
        )

    # Determine the single top-level directory every entry must live under.
    safe_paths: list[tuple[zipfile.ZipInfo, Path]] = []
    top_level_names: set[str] = set()
    for info in infos:
        rel = _safe_relative_path(info.filename)
        if not rel.parts:
            continue
        top_level_names.add(rel.parts[0])
        safe_paths.append((info, rel))

    if len(top_level_names) != 1:
        raise SkillPackageExtractError(
            "Zip archive must contain exactly one top-level directory (the skill's own directory), "
            f"found: {sorted(top_level_names)}"
        )
    root_dir_name = next(iter(top_level_names))

    if not any(rel.parts == (root_dir_name, "SKILL.md") for _, rel in safe_paths):
        raise SkillPackageExtractError(f"Archive is missing {root_dir_name}/SKILL.md")

    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[str] = []
    for info, rel in safe_paths:
        # Strip the wrapping <skill-name>/ prefix — the package's own
        # directory (named by package_id, not skill name) already namespaces
        # it, so files land at dest_dir/SKILL.md, dest_dir/scripts/..., etc.
        inner_rel = Path(*rel.parts[1:]) if len(rel.parts) > 1 else None
        if inner_rel is None or str(inner_rel) in ("", "."):
            continue  # the root directory entry itself, if present as a file (shouldn't happen)
        target = (dest_dir / inner_rel).resolve()
        if not str(target).startswith(str(dest_dir.resolve())):
            raise SkillPackageExtractError(f"Unsafe path in archive: {info.filename!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            dst.write(src.read())
        manifest.append(str(inner_rel).replace(os.sep, "/"))

    return ExtractedPackage(root_dir_name=root_dir_name, extracted_path=dest_dir, file_manifest=sorted(manifest))


def zip_package(dir_path: Path, root_name: str) -> bytes:
    """Re-zips a stored package's directory back into a single archive with
    `root_name/` as the wrapping folder, for the "share it with others"
    download path — byte-for-byte re-uploadable to another instance.

    Skips `__pycache__/` and `.pyc`/`.pyo` files: nothing in this app ever
    executes a skill's scripts automatically, but a developer manually
    running `scripts/foo.py` locally (or any tool that byte-compiles the
    tree, e.g. `py_compile`) leaves one behind on disk — without this
    filter it would silently get zipped into every future download/reseed,
    polluting the file manifest with a build artifact that was never part
    of the actual skill."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(dir_path.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            arcname = f"{root_name}/{path.relative_to(dir_path).as_posix()}"
            zf.write(path, arcname)
    return buf.getvalue()
