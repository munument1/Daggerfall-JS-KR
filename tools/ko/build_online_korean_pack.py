#!/usr/bin/env python3
"""Build a DFO Online Korean translation pack from the DFU Korean patch.

Requires Python 3.10+. Only uses the standard library.
Examples:
  python tools/ko/build_online_korean_pack.py --dfu-path ../-KR-Daggerfall_Unity
  python tools/ko/build_online_korean_pack.py --dfu-path Daggerfall_Unity_Korean.zip
"""
from __future__ import annotations

import argparse
import csv
import io
import os
from pathlib import Path
import re
import sys
import subprocess
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[2]
PORT_CSV = REPO_ROOT / "locales" / "ko" / "Port_Strings.csv"
ENGLISH_CSV = REPO_ROOT / "tools" / "ko" / "reference" / "app-v0.1.9050.en.csv"
DEFAULT_OUTPUT = Path("DFO_Online_Korean_Combined.zip")


def classify(path: str) -> tuple[str, str] | None:
    """Mirror translationPacks.js: last Text/Fonts folder wins, by kind/name."""
    parts = [p for p in path.replace("\\", "/").split("/") if p and p != "."]
    index = next((i for i in range(len(parts) - 2, -1, -1)
                  if parts[i].lower() in ("text", "fonts")), -1)
    if index < 0:
        return None
    folder = parts[index].lower()
    rest = parts[index + 1:]
    if not rest:
        return None
    name = rest[-1]
    if folder == "fonts":
        if len(rest) != 1 or not re.fullmatch(r"FONT000[0-4]-SDF\.(?:ttf|otf|txt)", name, re.I):
            return None
        return ("font", "Fonts/" + name)
    if len(rest) == 2 and rest[0].lower() in ("quests", "books"):
        if not re.fullmatch(r".+-LOC\.txt", name, re.I):
            return None
        category = "quest" if rest[0].lower() == "quests" else "book"
        return (category, f"Text/{'Quests' if category == 'quest' else 'Books'}/{name}")
    if len(rest) == 1 and re.fullmatch(r"[A-Za-z0-9_]+\.(?:csv|txt)", name, re.I):
        return ("table", "Text/" + name)
    return None


def source_files(path: Path):
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as package:
            for info in package.infolist():
                if not info.is_dir() and classify(info.filename):
                    yield info.filename, package.read(info)
    elif path.is_dir():
        for base, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for filename in sorted(files):
                full = Path(base) / filename
                relative = str(full.relative_to(path)).replace(os.sep, "/")
                if classify(relative):
                    yield relative, full.read_bytes()
    else:
        raise ValueError("--dfu-path must be a directory or .zip file")


def read_csv_rows(data: bytes) -> dict[str, str]:
    with io.StringIO(data.decode("utf-8-sig"), newline="") as stream:
        reader = csv.reader(stream, strict=True)
        if next(reader, None) != ["Key", "Value"]:
            raise ValueError("CSV must begin with Key,Value")
        rows = {}
        for row in reader:
            if len(row) != 2:
                raise ValueError(f"Invalid CSV row: {row[:2]}")
            if row[0] in rows:
                raise ValueError(f"Duplicate CSV key: {row[0]}")
            rows[row[0]] = row[1]
        return rows


def build(dfu_path: Path, output: Path, english_path: Path = ENGLISH_CSV,
          preserve_existing_pack: bool = False):
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing archive: {output}")
    if not PORT_CSV.exists() or not ENGLISH_CSV.exists():
        raise FileNotFoundError("Run this tool from a checkout containing locales/ko and locales/en")
    ko = PORT_CSV.read_bytes()
    en_rows = read_csv_rows(english_path.read_bytes())
    ko_rows = read_csv_rows(ko)
    missing = sorted(set(en_rows) - set(ko_rows))
    extra = sorted(set(ko_rows) - set(en_rows))
    if missing or extra:
        raise ValueError(f"Port_Strings keys differ from English: missing={len(missing)} extra={len(extra)}")
    subprocess.run(["node", str(REPO_ROOT / "tools/ko/check_port_translations.mjs"),
                    "--english", str(english_path.resolve()),
                    "--korean", str(PORT_CSV)], check=True, cwd=REPO_ROOT)

    if preserve_existing_pack:
        # Keep every original member byte-for-byte; replace only the online string table.
        with zipfile.ZipFile(dfu_path) as source:
            names = source.namelist()
            if len({n.casefold() for n in names}) != len(names):
                raise ValueError("Existing pack contains duplicate paths")
            if "Text/Port_Strings.csv" not in names:
                raise ValueError("Existing pack lacks Text/Port_Strings.csv")
            if not all(any(n.startswith(prefix) for n in names)
                       for prefix in ("Fonts/", "Text/Quests/", "Text/Books/")):
                raise ValueError("Existing combined pack lacks fonts, quests or books")
            if source.testzip() is not None:
                raise ValueError("Existing pack failed CRC validation")
            output.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=8) as package:
                package.comment = source.comment
                for info in source.infolist():
                    data = ko if info.filename == "Text/Port_Strings.csv" else source.read(info)
                    package.writestr(info, data)
        with zipfile.ZipFile(dfu_path) as source, zipfile.ZipFile(output) as package:
            if source.namelist() != package.namelist() or package.testzip() is not None:
                raise ValueError("New archive failed structure/CRC validation")
            for name in source.namelist():
                if name != "Text/Port_Strings.csv" and source.read(name) != package.read(name):
                    raise ValueError(f"Original pack member changed: {name}")
        print(f"Created: {output.resolve()}")
        print(f"Preserved {len(names) - 1} original members; online UI keys: {len(ko_rows)}")
        return

    selected = {}
    counts = {"table": 0, "quest": 0, "book": 0, "font": 0}
    for path, data in source_files(dfu_path):
        kind, final_name = classify(path)
        selected[final_name.lower()] = (final_name, data, kind)

    selected["text/port_strings.csv"] = ("Text/Port_Strings.csv", ko, "table")
    for _, _, kind in selected.values():
        counts[kind] += 1
    if not counts["quest"] or not counts["book"] or counts["table"] < 10:
        raise ValueError(f"Unexpected source coverage; refusing incomplete package: {counts}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as package:
        for _, (name, data, _) in sorted(selected.items()):
            package.writestr(name, data)
        package.writestr("README_Online_Korean.txt",
            "DFO Online Korean combined translation pack.\n"
            "Source: munument1/-KR-Daggerfall_Unity and munument1/-KR-daggerfall-js.\n"
            "Install under Settings > Interface > Language: Korean > Translation pack.\n"
            "Only DFU-compatible Text/Fonts and online-specific Port_Strings are included.\n"
            "DFU BIOGs, textures and videos are not supported by this importer.\n")
    print(f"Created: {output.resolve()}")
    print(f"Contents: {counts}; online UI keys: {len(ko_rows)}")
    print("Note: hard-coded English strings in DFO still require upstream localization routing.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dfu-path", required=True, type=Path, help="DFU Korean patch folder or zip")
    p.add_argument("--output", default=DEFAULT_OUTPUT, type=Path, help="New output zip (must not exist)")
    p.add_argument("--english", default=ENGLISH_CSV, type=Path, help="English reference catalogue")
    p.add_argument("--preserve-existing-pack", action="store_true",
                   help="Preserve all existing ZIP members; replace only Text/Port_Strings.csv")
    args = p.parse_args()
    try:
        build(args.dfu_path, args.output, args.english, args.preserve_existing_pack)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
