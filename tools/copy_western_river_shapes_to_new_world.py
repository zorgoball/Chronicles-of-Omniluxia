#!/usr/bin/env python3
"""Copy western-continent river shapes into the New World.

This intentionally avoids clever port-to-source routing. It extracts connected
river components from the established western half of rivers.png, transforms
those shapes, and stamps them onto New World setup land.
"""

from __future__ import annotations

import argparse
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from audit_second_continent import MAP_DATA, NEW_WORLD_SETUP, ROOT, parse_setup
from generate_new_world_locators import parse_definition_colors


BACKGROUND_VALUES = {254, 255}
RIVER_VALUES = {0, 1, 2, 3, 4, 6, 7, 8, 11, 12, 13, 14, 15}
LAND_BACKGROUND = 254
WESTERN_TEMPLATE_MAX_X = 5000
MIN_TEMPLATE_PIXELS = 100


@dataclass(frozen=True)
class RiverTemplate:
    rank: int
    pixels: tuple[tuple[float, float, int], ...]
    bbox: tuple[int, int, int, int]
    size: int


@dataclass(frozen=True)
class Placement:
    name: str
    template_rank: int
    center: tuple[int, int]
    scale: float
    angle_degrees: float
    flip_x: bool = False
    flip_y: bool = False
    search_radius: int = 96
    search_step: int = 32


# Scattered target placements across New World landmasses. These copy western
# river silhouettes; they are not forced to hit ports.
PLACEMENTS = (
    Placement("northwest_broad_basin", 0, (6540, 1320), 0.72, -26, True, False, 128),
    Placement("north_glacial_fork", 11, (6860, 790), 0.82, 72, False, True, 96),
    Placement("western_interior_branch", 6, (6320, 1830), 0.82, 34, False, False, 128),
    Placement("north_central_sweep", 1, (7160, 1510), 0.70, -48, False, False, 128),
    Placement("northeast_short_fork", 13, (7420, 1240), 0.90, 132, True, False, 96),
    Placement("inner_sea_east_bank", 7, (7590, 2330), 0.72, 58, True, False, 128),
    Placement("central_long_braid", 4, (6970, 2160), 0.66, 101, False, True, 128),
    Placement("east_coastal_curl", 16, (7740, 2700), 0.92, -38, False, False, 96),
    Placement("central_west_island", 8, (6780, 2520), 0.70, -14, True, False, 96),
    Placement("southwest_island_marsh", 10, (6650, 2870), 0.64, 92, False, False, 96),
    Placement("middle_island_west", 9, (7100, 3070), 0.62, -72, True, False, 112),
    Placement("middle_island_east", 14, (7320, 2990), 0.86, 28, False, True, 96),
    Placement("south_main_highland", 3, (7370, 3470), 0.70, 117, False, False, 144),
    Placement("south_main_eastern_fork", 2, (7680, 3370), 0.56, -62, True, False, 128),
    Placement("deep_south_crescent", 5, (7190, 3790), 0.58, 18, False, True, 128),
    Placement("far_south_tail", 12, (7600, 3770), 0.78, -115, True, False, 96),
)


def row_data(image: Image.Image, y: int):
    row = image.crop((0, y, image.size[0], y + 1))
    return row.get_flattened_data() if hasattr(row, "get_flattened_data") else row.getdata()


def extract_templates(rivers: Image.Image) -> list[RiverTemplate]:
    pixels = rivers.load()
    width, height = rivers.size
    seen: set[tuple[int, int]] = set()
    components: list[tuple[int, tuple[int, int, int, int], list[tuple[int, int, int]]]] = []

    for y in range(height):
        for x in range(min(width, WESTERN_TEMPLATE_MAX_X)):
            if (x, y) in seen or pixels[x, y] not in RIVER_VALUES:
                continue
            stack = [(x, y)]
            seen.add((x, y))
            component: list[tuple[int, int, int]] = []
            while stack:
                cx, cy = stack.pop()
                component.append((cx, cy, pixels[cx, cy]))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx = cx + dx
                        ny = cy + dy
                        if nx < 0 or nx >= WESTERN_TEMPLATE_MAX_X or ny < 0 or ny >= height:
                            continue
                        if (nx, ny) in seen or pixels[nx, ny] not in RIVER_VALUES:
                            continue
                        seen.add((nx, ny))
                        stack.append((nx, ny))

            if len(component) < MIN_TEMPLATE_PIXELS:
                continue
            xs = [point[0] for point in component]
            ys = [point[1] for point in component]
            bbox = (min(xs), min(ys), max(xs), max(ys))
            components.append((len(component), bbox, component))

    templates: list[RiverTemplate] = []
    for rank, (size, bbox, component) in enumerate(sorted(components, reverse=True)):
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        normalized = tuple((x - cx, y - cy, value) for x, y, value in component)
        templates.append(RiverTemplate(rank=rank, pixels=normalized, bbox=bbox, size=size))
    return templates


def transformed_pixels(
    template: RiverTemplate,
    placement: Placement,
    center: tuple[int, int] | None = None,
) -> dict[tuple[int, int], int]:
    cx, cy = center or placement.center
    angle = math.radians(placement.angle_degrees)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    result: dict[tuple[int, int], int] = {}

    for rel_x, rel_y, value in template.pixels:
        tx = -rel_x if placement.flip_x else rel_x
        ty = -rel_y if placement.flip_y else rel_y
        tx *= placement.scale
        ty *= placement.scale
        x = int(round(cx + tx * cos_a - ty * sin_a))
        y = int(round(cy + tx * sin_a + ty * cos_a))
        result[(x, y)] = value
    return result


def land_score(
    pixels: dict[tuple[int, int], int],
    province_pixels,
    land_colors: set[tuple[int, int, int]],
    width: int,
    height: int,
    occupied: set[tuple[int, int]],
) -> tuple[int, int, int]:
    on_land = 0
    overlap = 0
    off_map = 0
    for x, y in pixels:
        if x < 0 or x >= width or y < 0 or y >= height:
            off_map += 1
            continue
        if province_pixels[x, y] not in land_colors:
            continue
        on_land += 1
        if (x, y) in occupied:
            overlap += 1
    return on_land - overlap * 3, on_land, off_map


def choose_center(
    template: RiverTemplate,
    placement: Placement,
    province_pixels,
    land_colors: set[tuple[int, int, int]],
    width: int,
    height: int,
    occupied: set[tuple[int, int]],
) -> tuple[tuple[int, int], dict[tuple[int, int], int], tuple[int, int, int]]:
    best_center = placement.center
    best_pixels = transformed_pixels(template, placement)
    best_score = land_score(best_pixels, province_pixels, land_colors, width, height, occupied)

    radius = placement.search_radius
    step = placement.search_step
    for dy in range(-radius, radius + 1, step):
        for dx in range(-radius, radius + 1, step):
            center = (placement.center[0] + dx, placement.center[1] + dy)
            candidate = transformed_pixels(template, placement, center)
            score = land_score(candidate, province_pixels, land_colors, width, height, occupied)
            if score > best_score:
                best_center = center
                best_pixels = candidate
                best_score = score

    return best_center, best_pixels, best_score


def clip_to_land(
    pixels: dict[tuple[int, int], int],
    province_pixels,
    land_colors: set[tuple[int, int, int]],
    width: int,
    height: int,
) -> dict[tuple[int, int], int]:
    return {
        (x, y): value
        for (x, y), value in pixels.items()
        if 0 <= x < width and 0 <= y < height and province_pixels[x, y] in land_colors
    }


def current_new_world_rivers(
    rivers: Image.Image,
    provinces: Image.Image,
    bbox: tuple[int, int, int, int],
    land_colors: set[tuple[int, int, int]],
) -> dict[tuple[int, int], int]:
    river_pixels = rivers.load()
    province_pixels = provinces.load()
    min_x, min_y, max_x, max_y = bbox
    result: dict[tuple[int, int], int] = {}
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if province_pixels[x, y] not in land_colors:
                continue
            value = river_pixels[x, y]
            if value in BACKGROUND_VALUES:
                continue
            result[(x, y)] = value
    return result


def find_bbox(provinces: Image.Image, land_colors: set[tuple[int, int, int]]) -> tuple[int, int, int, int]:
    bbox = [provinces.size[0], provinces.size[1], -1, -1]
    for y in range(provinces.size[1]):
        for x, color in enumerate(row_data(provinces, y)):
            if color not in land_colors:
                continue
            bbox[0] = min(bbox[0], x)
            bbox[1] = min(bbox[1], y)
            bbox[2] = max(bbox[2], x)
            bbox[3] = max(bbox[3], y)
    if bbox[2] == -1:
        raise SystemExit("No New World setup province pixels found.")
    return bbox[0], bbox[1], bbox[2], bbox[3]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    setup_ids, _, _ = parse_setup(setup_path.resolve())
    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    land_colors = {colors[province_id] for province_id in setup_ids}

    provinces = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    province_pixels = provinces.load()
    rivers = Image.open(MAP_DATA / "rivers.png")
    if rivers.mode != "P":
        raise SystemExit(f"Expected indexed rivers.png, got mode {rivers.mode}")

    templates = extract_templates(rivers)
    if not templates:
        raise SystemExit("No western river templates found.")
    template_by_rank = {template.rank: template for template in templates}
    bbox = find_bbox(provinces, land_colors)
    width, height = provinces.size

    planned: dict[tuple[int, int], int] = {}
    occupied: set[tuple[int, int]] = set()

    print(f"Setup provinces: {len(setup_ids)}")
    print(f"Province bbox: x={bbox[0]}..{bbox[2]}, y={bbox[1]}..{bbox[3]}")
    print(f"Western river templates: {len(templates)}")
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")

    for placement in PLACEMENTS:
        template = template_by_rank[placement.template_rank]
        center, candidate, score = choose_center(
            template,
            placement,
            province_pixels,
            land_colors,
            width,
            height,
            occupied,
        )
        clipped = clip_to_land(candidate, province_pixels, land_colors, width, height)
        planned.update(clipped)
        occupied.update(clipped)
        coverage = (len(clipped) / max(1, len(candidate))) * 100.0
        print(
            f"{placement.name}: template={template.rank} source_bbox={template.bbox} "
            f"center={center} pixels={len(clipped)}/{len(candidate)} ({coverage:.1f}%) "
            f"score={score[0]}"
        )

    current = current_new_world_rivers(rivers, provinces, bbox, land_colors)
    to_clear = set(current) - set(planned)
    to_write = {coord: value for coord, value in planned.items() if current.get(coord) != value}
    changed = len(to_clear) + len(to_write)
    planned_values = Counter(planned.values())

    print(f"Current New World river pixels: {len(current)}")
    print(f"Planned New World river pixels: {len(planned)}")
    print(f"Pixels to clear: {len(to_clear)}")
    print(f"Pixels to write/change: {len(to_write)}")
    print(f"Total changed pixels: {changed}")
    print("Planned palette values:")
    for value, count in sorted(planned_values.items()):
        print(f"  {value}: {count}")

    if args.apply and changed:
        river_pixels = rivers.load()
        for x, y in to_clear:
            river_pixels[x, y] = LAND_BACKGROUND
        for (x, y), value in to_write.items():
            river_pixels[x, y] = value
        rivers.save(MAP_DATA / "rivers.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
