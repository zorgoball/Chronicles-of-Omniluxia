#!/usr/bin/env python3
"""Generate a first-pass adjacent road network for new_world_region.

The generator reads province borders from provinces.png, so each emitted
``A = B`` pair connects actual neighboring provinces. It creates roads between
country capitals and owned cities, then adds light area-level trunk roads
between urban/capital waypoints.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import math
import re
from collections import defaultdict
from pathlib import Path

from PIL import Image

from audit_second_continent import (
    MAP_DATA,
    NEW_WORLD_REGION,
    NEW_WORLD_SETUP,
    ROOT,
    SETUP_MAIN,
    parse_area_provinces,
    parse_definition_ids,
    parse_named_blocks,
    parse_region_areas,
    resolve_region_areas,
    parse_road_network,
    parse_setup,
    strip_comments,
)
from generate_new_world_locators import parse_locator_positions


ROAD_FILE = SETUP_MAIN / "02_road_network.txt"


def parse_definition_colors(path: Path) -> dict[int, tuple[int, int, int]]:
    colors: dict[int, tuple[int, int, int]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle, delimiter=";"):
            if row and row[0].isdigit():
                colors[int(row[0])] = (int(row[1]), int(row[2]), int(row[3]))
    return colors


def parse_country_blocks(path: Path) -> dict[str, dict[str, object]]:
    countries: dict[str, dict[str, object]] = {}
    for tag, body in parse_named_blocks(path).items():
        if not re.fullmatch(r"[A-Z0-9]{3}", tag):
            continue
        clean = strip_comments(body)
        capital_match = re.search(r"\bcapital\s*=\s*(\d+)", clean)
        owned_match = re.search(r"\bown_control_core\s*=\s*\{([^}]*)\}", clean, re.S)
        owned = set(map(int, re.findall(r"\d+", owned_match.group(1)))) if owned_match else set()
        countries[tag] = {
            "capital": int(capital_match.group(1)) if capital_match else None,
            "owned": owned,
        }
    return countries


def build_adjacency(
    image_path: Path,
    province_colors: dict[int, tuple[int, int, int]],
    relevant_ids: set[int],
) -> dict[int, set[int]]:
    color_to_id = {province_colors[pid]: pid for pid in relevant_ids}
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    adjacency: dict[int, set[int]] = {pid: set() for pid in relevant_ids}

    previous_row: list[int | None] | None = None
    for y in range(height):
        row_image = image.crop((0, y, width, y + 1))
        row_data = (
            row_image.get_flattened_data()
            if hasattr(row_image, "get_flattened_data")
            else row_image.getdata()
        )
        row = [color_to_id.get(color) for color in row_data]
        last = row[0]
        for x in range(1, width):
            current = row[x]
            if current is not None and last is not None and current != last:
                adjacency[current].add(last)
                adjacency[last].add(current)
            if previous_row is not None:
                above = previous_row[x]
                if current is not None and above is not None and current != above:
                    adjacency[current].add(above)
                    adjacency[above].add(current)
            last = current
        if previous_row is not None:
            current = row[0]
            above = previous_row[0]
            if current is not None and above is not None and current != above:
                adjacency[current].add(above)
                adjacency[above].add(current)
        previous_row = row

    return adjacency


def edge_distance(a: int, b: int, positions: dict[int, tuple[float, float]]) -> float:
    ax, az = positions[a]
    bx, bz = positions[b]
    return math.hypot(ax - bx, az - bz)


def shortest_path(
    start: int,
    goal: int,
    adjacency: dict[int, set[int]],
    positions: dict[int, tuple[float, float]],
) -> list[int] | None:
    if start == goal:
        return [start]

    queue: list[tuple[float, int]] = [(0.0, start)]
    distances = {start: 0.0}
    previous: dict[int, int] = {}

    while queue:
        distance, node = heapq.heappop(queue)
        if node == goal:
            break
        if distance != distances[node]:
            continue
        for neighbor in adjacency[node]:
            new_distance = distance + edge_distance(node, neighbor, positions)
            if new_distance >= distances.get(neighbor, float("inf")):
                continue
            distances[neighbor] = new_distance
            previous[neighbor] = node
            heapq.heappush(queue, (new_distance, neighbor))

    if goal not in distances:
        return None

    path = [goal]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return path


def path_edges(path: list[int]) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for a, b in zip(path, path[1:]):
        edges.add((min(a, b), max(a, b)))
    return edges


def nearest_tree_pairs(points: list[int], positions: dict[int, tuple[float, float]]) -> list[tuple[int, int]]:
    if len(points) < 2:
        return []
    connected = {points[0]}
    remaining = set(points[1:])
    pairs: list[tuple[int, int]] = []
    while remaining:
        best_pair: tuple[int, int] | None = None
        best_distance = float("inf")
        for a in connected:
            ax, az = positions[a]
            for b in remaining:
                bx, bz = positions[b]
                distance = math.hypot(ax - bx, az - bz)
                if distance < best_distance:
                    best_pair = (a, b)
                    best_distance = distance
        assert best_pair is not None
        pairs.append(best_pair)
        connected.add(best_pair[1])
        remaining.remove(best_pair[1])
    return pairs


def append_road_edges(path: Path, edges: set[tuple[int, int]]) -> None:
    text = path.read_text(encoding="utf-8-sig")
    index = text.rfind("\n}")
    if index == -1:
        raise ValueError(f"Could not find road network footer in {path}")
    lines = ["\n\t# New World generated first-pass roads\n"]
    lines.extend(f"\t{a} = {b}\n" for a, b in sorted(edges))
    new_text = text[:index] + "".join(lines) + text[index:]
    path.write_text(new_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=NEW_WORLD_REGION)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    setup_ids, setup_fields, _ = parse_setup(setup_path.resolve())
    definition_ids = parse_definition_ids(MAP_DATA / "definition.csv")
    missing_definition = setup_ids - definition_ids
    if missing_definition:
        raise SystemExit(f"Setup IDs missing definition.csv rows: {sorted(missing_definition)[:20]}")

    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    positions = parse_locator_positions(ROOT / "gfx" / "map" / "map_object_data" / "vfx_locators.txt")
    missing_positions = setup_ids - set(positions)
    if missing_positions:
        raise SystemExit(f"Setup IDs missing vfx positions: {sorted(missing_positions)[:20]}")

    print("Building province adjacency from provinces.png...")
    adjacency = build_adjacency(MAP_DATA / "provinces.png", colors, setup_ids)
    adjacency_edges = {tuple(sorted((a, b))) for a, ns in adjacency.items() for b in ns}
    print(f"Setup provinces: {len(setup_ids)}")
    print(f"Adjacent province edges: {len(adjacency_edges)}")

    countries = parse_country_blocks(SETUP_MAIN / "02_countries.txt")
    owned_by_tag: dict[str, set[int]] = {}
    capitals: dict[str, int] = {}
    for tag, data in countries.items():
        owned = set(data["owned"]) & setup_ids
        capital = data["capital"]
        if not owned or not isinstance(capital, int) or capital not in setup_ids:
            continue
        owned_by_tag[tag] = owned
        capitals[tag] = capital

    road_pairs: set[tuple[int, int]] = set()
    route_failures: list[tuple[int, int, str]] = []

    def add_route(start: int, goal: int, reason: str) -> None:
        if start == goal:
            return
        path = shortest_path(start, goal, adjacency, positions)
        if path is None:
            route_failures.append((start, goal, reason))
            return
        road_pairs.update(path_edges(path))

    for tag, owned in sorted(owned_by_tag.items()):
        capital = capitals[tag]
        owned_cities = sorted(
            pid for pid in owned if setup_fields.get(pid, {}).get("province_rank") == "city"
        )
        for city in owned_cities:
            add_route(capital, city, f"{tag} capital-city")

    areas = parse_area_provinces(MAP_DATA / "areas.txt")
    regions = parse_region_areas(MAP_DATA / "regions.txt")
    area_by_province: dict[int, str] = {}
    for area_name in resolve_region_areas(regions, args.region):
        for province_id in areas.get(area_name, set()) & setup_ids:
            area_by_province[province_id] = area_name

    waypoints_by_area: dict[str, set[int]] = defaultdict(set)
    for capital in capitals.values():
        area = area_by_province.get(capital)
        if area:
            waypoints_by_area[area].add(capital)
    for province_id, fields in setup_fields.items():
        if fields.get("province_rank") != "city":
            continue
        area = area_by_province.get(province_id)
        if area:
            waypoints_by_area[area].add(province_id)

    for area_name, points in sorted(waypoints_by_area.items()):
        ordered_points = sorted(points, key=lambda pid: positions[pid])
        for start, goal in nearest_tree_pairs(ordered_points, positions):
            add_route(start, goal, f"{area_name} trunk")

    existing_roads = parse_road_network(ROAD_FILE)
    new_roads = road_pairs - existing_roads

    print(f"Countries with owned land and capitals here: {len(owned_by_tag)}")
    print(f"Capital/city/area routed road edges: {len(road_pairs)}")
    print(f"New road edges to add: {len(new_roads)}")
    print(f"Route failures: {len(route_failures)}")
    if route_failures:
        for start, goal, reason in route_failures[:20]:
            print(f"  {start} -> {goal} ({reason})")
        if len(route_failures) > 20:
            print(f"  ... (+{len(route_failures) - 20} more)")

    print(f"Mode: {'apply' if args.apply else 'dry-run'}")
    if args.apply and new_roads:
        append_road_edges(ROAD_FILE, new_roads)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
