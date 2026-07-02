#!/usr/bin/env python3
"""Add first-pass climate coverage for new_world_region provinces."""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

from audit_second_continent import (
    MAP_DATA,
    NEW_WORLD_REGION,
    NEW_WORLD_SETUP,
    ROOT,
    parse_area_provinces,
    parse_climate,
    parse_region_areas,
    resolve_region_areas,
    parse_setup,
)


CLIMATE_FILE = MAP_DATA / "climate.txt"
DRY_TERRAINS = {"desert", "flood_plain"}
WARM_TERRAINS = {"jungle", "marsh", "coastal_terrain", "farmland", "eldritch_forest"}


def choose_climate(province_id: int, area_name: str, terrain: str) -> str:
    if terrain in DRY_TERRAINS:
        return "arid"
    if area_name.startswith("new_world_shouth"):
        return "mild_winter"
    if area_name.startswith("new_world_north"):
        if terrain in WARM_TERRAINS:
            return "mild_winter"
        return "normal_winter"
    return "mild_winter"


def format_ids(ids: list[int], indent: str = "\t", per_line: int = 18) -> str:
    lines: list[str] = []
    for index in range(0, len(ids), per_line):
        lines.append(indent + " ".join(map(str, ids[index : index + per_line])) + "\n")
    return "".join(lines)


def insert_into_list(text: str, list_name: str, ids: list[int]) -> str:
    if not ids:
        return text
    pattern = re.compile(rf"(?m)^({re.escape(list_name)}\s*=\s*LIST\s*\{{)(.*?)(^}})", re.S)
    match = pattern.search(text)
    if not match:
        raise ValueError(f"Could not find {list_name} list in climate.txt")
    generated = (
        f"\n# New World generated first-pass climate\n"
        f"{format_ids(ids)}"
    )
    return text[: match.start(3)] + generated + text[match.start(3) :]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=NEW_WORLD_REGION)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    setup_ids, setup_fields, _ = parse_setup(setup_path.resolve())
    existing_climate = parse_climate(CLIMATE_FILE)

    areas = parse_area_provinces(MAP_DATA / "areas.txt")
    regions = parse_region_areas(MAP_DATA / "regions.txt")
    area_by_province: dict[int, str] = {}
    for area_name in resolve_region_areas(regions, args.region):
        for province_id in areas.get(area_name, set()) & setup_ids:
            area_by_province[province_id] = area_name

    additions: dict[str, list[int]] = defaultdict(list)
    for province_id in sorted(setup_ids - set(existing_climate)):
        area_name = area_by_province.get(province_id, "")
        terrain = setup_fields[province_id].get("terrain", "plains")
        additions[choose_climate(province_id, area_name, terrain)].append(province_id)

    counts = Counter({name: len(ids) for name, ids in additions.items()})
    print(f"Setup provinces: {len(setup_ids)}")
    print(f"Already assigned climate: {len(setup_ids & set(existing_climate))}")
    print(f"Climate additions: {sum(counts.values())}")
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")

    if args.apply and additions:
        text = CLIMATE_FILE.read_text(encoding="utf-8-sig")
        for list_name in ("mild_winter", "normal_winter", "arid"):
            text = insert_into_list(text, list_name, additions.get(list_name, []))
        CLIMATE_FILE.write_text(text, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
