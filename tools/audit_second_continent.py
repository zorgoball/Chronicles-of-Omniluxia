#!/usr/bin/env python3
"""Audit map/setup coverage for Omniluxia's second-continent work.

The script is intentionally read-only. It cross-checks the province IDs in
map_data/areas.txt, map_data/default.map, setup/provinces/00_new_world_region.txt,
and gfx/map/map_object_data/*_locators.txt so broad map work can be tracked
without opening the map editor for every question.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_DATA = ROOT / "map_data"
SETUP_PROVINCES = ROOT / "setup" / "provinces"
LOCATORS = ROOT / "gfx" / "map" / "map_object_data"
SETUP_MAIN = ROOT / "setup" / "main"

NEW_WORLD_REGION = "new_world_region"
NEW_WORLD_SETUP = SETUP_PROVINCES / "00_new_world_region.txt"

LOCATOR_FILES = {
    "city": LOCATORS / "city_locators.txt",
    "fort": LOCATORS / "fort_locators.txt",
    "great_work": LOCATORS / "great_work_locators.txt",
    "unit_stack": LOCATORS / "unit_stack_locators.txt",
    "combat": LOCATORS / "combat_locators.txt",
    "vfx": LOCATORS / "vfx_locators.txt",
    "port": LOCATORS / "port_locators.txt",
}


def strip_comments(text: str) -> str:
    return re.sub(r"#.*", "", text)


def parse_definition_ids(path: Path) -> set[int]:
    ids: set[int] = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle, delimiter=";"):
            if row and row[0].isdigit():
                ids.add(int(row[0]))
    return ids


def parse_named_blocks(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8-sig")
    blocks: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\s*([A-Za-z0-9_]+)\s*=\s*\{", text):
        name = match.group(1)
        start = match.end()
        depth = 1
        index = start
        while index < len(text) and depth:
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            index += 1
        blocks[name] = text[start : index - 1]
    return blocks


def parse_area_provinces(path: Path) -> dict[str, set[int]]:
    areas: dict[str, set[int]] = {}
    for area, body in parse_named_blocks(path).items():
        body = strip_comments(body)
        ids: set[int] = set()
        for provinces in re.findall(r"provinces\s*=\s*\{([^}]*)\}", body, re.S):
            ids.update(map(int, re.findall(r"\d+", provinces)))
        areas[area] = ids
    return areas


def parse_region_areas(path: Path) -> dict[str, set[str]]:
    regions: dict[str, set[str]] = {}
    for region, body in parse_named_blocks(path).items():
        body = strip_comments(body)
        match = re.search(r"areas\s*=\s*\{([^}]*)\}", body, re.S)
        if not match:
            regions[region] = set()
            continue
        regions[region] = set(re.findall(r"[A-Za-z0-9_]+", match.group(1)))
    return regions


def resolve_region_areas(regions: dict[str, set[str]], region_name: str) -> set[str]:
    region_areas = set(regions.get(region_name, set()))
    if region_areas or region_name != NEW_WORLD_REGION:
        return region_areas

    # The New World can be represented either as one broad region or as many
    # generated subregions. Treat all land-side new_world_* regions as the same
    # audit target, while leaving new_world_seas out.
    for name, areas in regions.items():
        if not name.startswith("new_world_") or "seas" in name:
            continue
        region_areas.update(areas)
    return region_areas


def parse_setup(path: Path) -> tuple[set[int], dict[int, dict[str, str]], Counter[str]]:
    text = path.read_text(encoding="utf-8-sig")
    setup_ids: set[int] = set()
    fields: dict[int, dict[str, str]] = {}
    terrain_counts: Counter[str] = Counter()

    for match in re.finditer(r"(?m)^\s*(\d+)\s*=\s*\{", text):
        province_id = int(match.group(1))
        setup_ids.add(province_id)
        start = match.end()
        depth = 1
        index = start
        while index < len(text) and depth:
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            index += 1
        body = text[start : index - 1]
        province_fields: dict[str, str] = {}
        for key in ("terrain", "culture", "religion", "trade_goods", "province_rank"):
            value = re.search(rf"\b{key}\s*=\s*\"?([A-Za-z0-9_]+)\"?", body)
            if value:
                province_fields[key] = value.group(1)
        fields[province_id] = province_fields
        terrain_counts.update([province_fields.get("terrain", "<missing>")])

    return setup_ids, fields, terrain_counts


def parse_default_lists(path: Path) -> dict[str, set[int]]:
    text = strip_comments(path.read_text(encoding="utf-8-sig"))
    result: dict[str, set[int]] = defaultdict(set)
    for match in re.finditer(
        r"\b(sea_zones|lakes|impassable_terrain)\s*=\s*(?:(LIST|RANGE)\s*)?\{([^}]*)\}",
        text,
        re.S,
    ):
        key, kind, body = match.groups()
        nums = list(map(int, re.findall(r"\d+", body)))
        if kind == "RANGE":
            if len(nums) == 2:
                result[key].update(range(nums[0], nums[1] + 1))
            else:
                result[key].update(nums)
        else:
            result[key].update(nums)
    return result


def parse_locator_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    return set(map(int, re.findall(r"\bid\s*=\s*(\d+)\b", path.read_text(encoding="utf-8-sig"))))


def parse_ports(path: Path) -> set[int]:
    if not path.exists():
        return set()
    ids: set[int] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line or line.startswith("#"):
            continue
        first = line.split(";", 1)[0].strip()
        if first.isdigit():
            ids.add(int(first))
    return ids


def parse_country_ownership(path: Path) -> dict[int, str]:
    text = strip_comments(path.read_text(encoding="utf-8-sig"))
    ownership: dict[int, str] = {}
    for country_match in re.finditer(r"(?m)^\s*([A-Z0-9]{3})\s*=\s*\{", text):
        tag = country_match.group(1)
        start = country_match.end()
        depth = 1
        index = start
        while index < len(text) and depth:
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            index += 1
        body = text[start : index - 1]
        owned = re.search(r"\bown_control_core\s*=\s*\{([^}]*)\}", body, re.S)
        if not owned:
            continue
        for province_id in map(int, re.findall(r"\d+", owned.group(1))):
            ownership[province_id] = tag
    return ownership


def parse_road_network(path: Path) -> set[tuple[int, int]]:
    text = strip_comments(path.read_text(encoding="utf-8-sig"))
    edges: set[tuple[int, int]] = set()
    for left, right in re.findall(r"(?m)^\s*(\d+)\s*=\s*(\d+)\b", text):
        a = int(left)
        b = int(right)
        edges.add((min(a, b), max(a, b)))
    return edges


def parse_climate(path: Path) -> dict[int, str]:
    text = strip_comments(path.read_text(encoding="utf-8-sig"))
    climate: dict[int, str] = {}
    for name, body in re.findall(r"(?m)^\s*([A-Za-z0-9_]+)\s*=\s*LIST\s*\{([^}]*)\}", text, re.S):
        for province_id in map(int, re.findall(r"\d+", body)):
            climate[province_id] = name
    return climate


def sample(values: set[int], limit: int = 20) -> str:
    ordered = sorted(values)
    shown = " ".join(map(str, ordered[:limit]))
    if len(ordered) > limit:
        shown += f" ... (+{len(ordered) - limit} more)"
    return shown if shown else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--region",
        default=NEW_WORLD_REGION,
        help="Region key in map_data/regions.txt to audit.",
    )
    parser.add_argument(
        "--setup",
        type=Path,
        default=NEW_WORLD_SETUP,
        help="Province setup file to audit against the selected region.",
    )
    args = parser.parse_args()

    definition_ids = parse_definition_ids(MAP_DATA / "definition.csv")
    areas = parse_area_provinces(MAP_DATA / "areas.txt")
    regions = parse_region_areas(MAP_DATA / "regions.txt")
    defaults = parse_default_lists(MAP_DATA / "default.map")
    setup_path = args.setup
    if not setup_path.is_absolute():
        setup_path = ROOT / setup_path
    setup_path = setup_path.resolve()

    setup_ids, setup_fields, terrain_counts = parse_setup(setup_path)
    locator_ids = {name: parse_locator_ids(path) for name, path in LOCATOR_FILES.items()}
    port_rows = parse_ports(MAP_DATA / "ports.csv")
    ownership = parse_country_ownership(SETUP_MAIN / "02_countries.txt")
    roads = parse_road_network(SETUP_MAIN / "02_road_network.txt")
    climate = parse_climate(MAP_DATA / "climate.txt")

    region_areas = resolve_region_areas(regions, args.region)
    region_provinces: set[int] = set()
    missing_area_defs = set()
    for area in region_areas:
        if area not in areas:
            missing_area_defs.add(area)
            continue
        region_provinces.update(areas[area])

    sea_lake_impassable = (
        defaults["sea_zones"] | defaults["lakes"] | defaults["impassable_terrain"]
    )
    playable_region = region_provinces - sea_lake_impassable

    print(f"Region: {args.region}")
    print(f"Areas in region: {len(region_areas)}")
    print(f"Region provinces: {len(region_provinces)}")
    print(f"Playable region provinces: {len(playable_region)}")
    print(f"Setup file: {setup_path.relative_to(ROOT)}")
    print(f"Setup entries: {len(setup_ids)}")
    print()

    print("Coverage")
    checks = {
        "region areas missing definitions": missing_area_defs,
        "region provinces missing definition.csv": region_provinces - definition_ids,
        "setup IDs outside definition.csv": setup_ids - definition_ids,
        "playable region provinces missing setup": playable_region - setup_ids,
        "setup provinces outside selected region": setup_ids - region_provinces,
        "playable setup provinces marked sea/lake/impassable": setup_ids & sea_lake_impassable,
    }
    for label, values in checks.items():
        print(f"  {label}: {len(values)}")
        if values:
            print(f"    {sample(values if isinstance(values, set) else set())}")

    print()
    print("Required setup fields")
    for field in ("terrain", "culture", "religion", "trade_goods", "province_rank"):
        missing = {pid for pid in setup_ids if field not in setup_fields.get(pid, {})}
        print(f"  missing {field}: {len(missing)}")
        if missing:
            print(f"    {sample(missing)}")

    print()
    print("Terrain distribution")
    for terrain, count in terrain_counts.most_common():
        print(f"  {terrain}: {count}")

    print()
    print("Locator coverage for setup provinces")
    for name in ("city", "fort", "great_work", "unit_stack", "combat", "vfx"):
        missing = setup_ids - locator_ids[name]
        print(f"  {name}: missing {len(missing)}")
        if missing:
            print(f"    {sample(missing)}")

    expected_ports = port_rows & setup_ids
    print()
    print(f"Ports in setup file listed in ports.csv: {len(expected_ports)}")
    missing_port_locators = expected_ports - locator_ids["port"]
    extra_port_locators = (locator_ids["port"] & setup_ids) - port_rows
    print(f"  missing port locators for ports.csv rows: {len(missing_port_locators)}")
    if missing_port_locators:
        print(f"    {sample(missing_port_locators)}")
    print(f"  port locators on setup provinces not in ports.csv: {len(extra_port_locators)}")
    if extra_port_locators:
        print(f"    {sample(extra_port_locators)}")

    owned_setup = setup_ids & set(ownership)
    unowned_setup = setup_ids - set(ownership)
    country_counts = Counter(ownership[pid] for pid in owned_setup)
    print()
    print("Country ownership")
    print(f"  owned setup provinces: {len(owned_setup)}")
    print(f"  unowned setup provinces: {len(unowned_setup)}")
    if unowned_setup:
        print(f"    {sample(unowned_setup)}")
    print(f"  countries with land here: {len(country_counts)}")

    region_roads = {edge for edge in roads if edge[0] in setup_ids or edge[1] in setup_ids}
    internal_roads = {edge for edge in region_roads if edge[0] in setup_ids and edge[1] in setup_ids}
    outbound_roads = region_roads - internal_roads
    provinces_with_roads = {pid for edge in region_roads for pid in edge if pid in setup_ids}
    print()
    print("Road network")
    print(f"  road edges touching setup provinces: {len(region_roads)}")
    print(f"  internal road edges: {len(internal_roads)}")
    print(f"  outbound road edges: {len(outbound_roads)}")
    print(f"  setup provinces on at least one road: {len(provinces_with_roads)}")

    setup_climate = setup_ids & set(climate)
    missing_climate = setup_ids - set(climate)
    climate_counts = Counter(climate[pid] for pid in setup_climate)
    print()
    print("Climate")
    print(f"  setup provinces with climate: {len(setup_climate)}")
    print(f"  setup provinces missing climate: {len(missing_climate)}")
    if missing_climate:
        print(f"    {sample(missing_climate)}")
    for climate_name, count in climate_counts.most_common():
        print(f"  {climate_name}: {count}")

    print()
    print("Default.map special province counts")
    for key in ("sea_zones", "lakes", "impassable_terrain"):
        ids = defaults[key]
        print(f"  {key}: {len(ids)} total, {len(ids & region_provinces)} in region")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
