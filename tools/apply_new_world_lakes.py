#!/usr/bin/env python3
"""Convert selected New World provinces into first-pass lake provinces.

The lake IDs were chosen from unowned, roadless, non-port interior provinces so
this pass can add real gameplay lakes without disturbing country ownership,
roads, or coast/port setup.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from audit_second_continent import (
    LOCATOR_FILES,
    MAP_DATA,
    NEW_WORLD_SETUP,
    ROOT,
    parse_area_provinces,
    parse_country_ownership,
    parse_default_lists,
    parse_region_areas,
    parse_road_network,
    parse_setup,
    resolve_region_areas,
)


LAKE_IDS = (471, 581, 1103, 1204, 2453, 2835, 4851, 5408)


def parse_ports(path: Path) -> set[int]:
    ids: set[int] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line or line.startswith("#"):
            continue
        first = line.split(";", 1)[0].strip()
        if first.isdigit():
            ids.add(int(first))
    return ids


def new_world_region_ids() -> set[int]:
    areas = parse_area_provinces(MAP_DATA / "areas.txt")
    regions = parse_region_areas(MAP_DATA / "regions.txt")
    region_areas = resolve_region_areas(regions, "new_world_region")
    province_ids: set[int] = set()
    for area in region_areas:
        province_ids.update(areas.get(area, set()))
    return province_ids


def validate_lake_ids(ids: set[int]) -> None:
    defaults = parse_default_lists(MAP_DATA / "default.map")
    setup_ids, _, _ = parse_setup(NEW_WORLD_SETUP)
    region_ids = new_world_region_ids()
    ownership = parse_country_ownership(ROOT / "setup" / "main" / "02_countries.txt")
    roads = parse_road_network(ROOT / "setup" / "main" / "02_road_network.txt")
    road_ids = {province_id for edge in roads for province_id in edge}
    ports = parse_ports(MAP_DATA / "ports.csv")

    errors: list[str] = []
    missing_region = ids - region_ids
    if missing_region:
        errors.append(f"not in new_world_region: {sorted(missing_region)}")

    missing_setup_or_lake = ids - setup_ids - defaults["lakes"]
    if missing_setup_or_lake:
        errors.append(
            "not setup provinces or existing lakes: "
            f"{sorted(missing_setup_or_lake)}"
        )

    sea_ids = ids & defaults["sea_zones"]
    if sea_ids:
        errors.append(f"already sea zones: {sorted(sea_ids)}")

    impassable_ids = ids & defaults["impassable_terrain"]
    if impassable_ids:
        errors.append(f"already impassable terrain: {sorted(impassable_ids)}")

    owned_ids = ids & set(ownership)
    if owned_ids:
        details = ", ".join(f"{province_id}:{ownership[province_id]}" for province_id in sorted(owned_ids))
        errors.append(f"owned provinces: {details}")

    roaded_ids = ids & road_ids
    if roaded_ids:
        errors.append(f"road network endpoints: {sorted(roaded_ids)}")

    port_ids = ids & ports
    if port_ids:
        errors.append(f"ports.csv rows: {sorted(port_ids)}")

    if errors:
        raise SystemExit("Refusing to apply New World lakes:\n  " + "\n  ".join(errors))


def update_default_map(text: str, ids: tuple[int, ...]) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == "# 00_new_world_region.txt"),
        None,
    )
    if start is None:
        raise ValueError("Could not find # 00_new_world_region.txt in default.map")

    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].strip() == "# 00_wastelands_of_omniluxia.txt"
        ),
        None,
    )
    if end is None:
        raise ValueError("Could not find # 00_wastelands_of_omniluxia.txt in default.map")

    # Preserve any existing impassable_terrain lines in this section (do not clobber
    # the impassables written by apply_new_world_impassables.py).
    preserved = [
        line for line in lines[start + 1 : end]
        if line.strip().startswith("impassable_terrain") or "impassable" in line.strip().lower() and line.strip().startswith("#")
    ]
    desired = (
        "# 00_new_world_region.txt\n"
        "# First-pass New World inland lakes; selected from unowned, roadless interior provinces.\n"
        f"lakes = LIST {{ {' '.join(map(str, ids))} }}\n"
        + "".join(preserved)
        + "# Remaining new_world_region provinces are passable (terrain assigned in setup).\n"
    )
    new_text = "".join(lines[:start]) + desired + "".join(lines[end:])
    return new_text, new_text != text


def remove_setup_blocks(text: str, ids: set[int]) -> tuple[str, list[int]]:
    pattern = re.compile(r"(?m)^\s*(\d+)\s*=\s*\{")
    pieces: list[str] = []
    cursor = 0
    removed: list[int] = []

    for match in pattern.finditer(text):
        province_id = int(match.group(1))
        if province_id not in ids:
            continue

        depth = 1
        index = match.end()
        while index < len(text) and depth:
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            index += 1
        if depth:
            raise ValueError(f"Unbalanced setup block for province {province_id}")

        end = index
        if text[end : end + 2] == "\r\n":
            end += 2
        elif end < len(text) and text[end] == "\n":
            end += 1

        pieces.append(text[cursor : match.start()])
        cursor = end
        removed.append(province_id)

    pieces.append(text[cursor:])
    return "".join(pieces), removed


def remove_ids_from_text(text: str, ids: set[int]) -> tuple[str, int]:
    pattern = re.compile(r"(?<!\d)(?:" + "|".join(map(str, sorted(ids))) + r")(?!\d)")
    return pattern.subn("", text)


def remove_locator_instances(text: str, ids: set[int]) -> tuple[str, int]:
    pattern = re.compile(
        r"\n\t\t\{\r?\n"
        r"\t\t\tid=(\d+)\r?\n"
        r"\t\t\tposition=\{[^\n]*\}\r?\n"
        r"\t\t\trotation=\{[^\n]*\}\r?\n"
        r"\t\t\tscale=\{[^\n]*\}\r?\n"
        r"\t\t\}",
        re.S,
    )

    removed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        province_id = int(match.group(1))
        if province_id not in ids:
            return match.group(0)
        removed += 1
        return ""

    return pattern.sub(replace, text), removed


def read_styled_text(path: Path) -> tuple[str, str, bool]:
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    return text, newline, has_bom


def write_styled_text(path: Path, text: str, newline: str, has_bom: bool) -> None:
    raw = text.replace("\n", newline).encode("utf-8")
    if has_bom:
        raw = b"\xef\xbb\xbf" + raw
    path.write_bytes(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for a dry run.")
    args = parser.parse_args()

    ids = set(LAKE_IDS)
    validate_lake_ids(ids)
    mode = "apply" if args.apply else "dry-run"
    print(f"Mode: {mode}")
    print(f"Lake IDs: {' '.join(map(str, LAKE_IDS))}")

    default_path = MAP_DATA / "default.map"
    default_text, default_newline, default_bom = read_styled_text(default_path)
    new_default, default_changed = update_default_map(default_text, LAKE_IDS)
    if default_changed and args.apply:
        write_styled_text(default_path, new_default, default_newline, default_bom)
    print(f"default.map changed: {default_changed}")

    setup_text, setup_newline, setup_bom = read_styled_text(NEW_WORLD_SETUP)
    new_setup, removed_setup = remove_setup_blocks(setup_text, ids)
    if new_setup != setup_text and args.apply:
        write_styled_text(NEW_WORLD_SETUP, new_setup, setup_newline, setup_bom)
    print(f"setup blocks removed: {len(removed_setup)} {removed_setup}")

    climate_path = MAP_DATA / "climate.txt"
    climate_text, climate_newline, climate_bom = read_styled_text(climate_path)
    new_climate, removed_climate_numbers = remove_ids_from_text(climate_text, ids)
    if new_climate != climate_text and args.apply:
        write_styled_text(climate_path, new_climate, climate_newline, climate_bom)
    print(f"climate IDs removed: {removed_climate_numbers}")

    total_locator_removed = 0
    for locator_name, path in LOCATOR_FILES.items():
        text, newline, has_bom = read_styled_text(path)
        new_text, removed = remove_locator_instances(text, ids)
        total_locator_removed += removed
        if new_text != text and args.apply:
            write_styled_text(path, new_text, newline, has_bom)
        print(f"{locator_name} locator instances removed: {removed}")

    if not args.apply:
        print("Dry run only. Re-run with --apply to write changes.")
    print(f"total locator instances removed: {total_locator_removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
