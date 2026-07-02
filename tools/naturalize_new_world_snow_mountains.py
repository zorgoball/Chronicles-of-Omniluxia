#!/usr/bin/env python3
"""Add northern snow and break up placeholder New World mountain shapes.

Run place_new_world_impassable_mountain_ranges.py after this script to restore
the art-directed central impassable range stamped from donor mountain tiles.
"""

from __future__ import annotations

import argparse
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image

from audit_second_continent import MAP_DATA, NEW_WORLD_SETUP, ROOT, parse_setup
from audit_second_continent import parse_default_lists
from generate_new_world_locators import parse_definition_colors
from refine_new_world_terrain_masks import (
    TERRAIN_DIR,
    build_new_points,
    mask_bbox_from_province_bbox,
    province_bbox,
)


MOUNTAIN_FAMILY_MASKS = {
    "mountains_mask.png",
    "rock_european_mask.png",
    "boulders_european_mask.png",
    "hills_india_01_mask.png",
    "grass_hills_mask.png",
    "gravel_1_mask.png",
    "gravel_2_mask.png",
    "rock_sandstone_mask.png",
    "boulder_sandstone_mask.png",
    "snow_mask.png",
}

MOUNTAIN_TERRAINS = {"mountain", "hills"}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def smoothstep(value: float) -> float:
    value = clamp(value)
    return value * value * (3.0 - 2.0 * value)


@lru_cache(maxsize=None)
def grid_random(ix: int, iy: int, salt: int) -> float:
    value = (
        ix * 0x45D9F3B
        + iy * 0x119DE1F3
        + salt * 0x27D4EB2D
    ) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x2C1B3C6D) & 0xFFFFFFFF
    value ^= value >> 12
    value = (value * 0x297A2D39) & 0xFFFFFFFF
    value ^= value >> 15
    return value / 0xFFFFFFFF


def value_noise(x: float, y: float, scale: float, salt: int) -> float:
    gx = x / scale
    gy = y / scale
    ix = math.floor(gx)
    iy = math.floor(gy)
    fx = smoothstep(gx - ix)
    fy = smoothstep(gy - iy)

    a = grid_random(ix, iy, salt)
    b = grid_random(ix + 1, iy, salt)
    c = grid_random(ix, iy + 1, salt)
    d = grid_random(ix + 1, iy + 1, salt)
    top = a + (b - a) * fx
    bottom = c + (d - c) * fx
    return top + (bottom - top) * fy


def ridge_field(x: float, y: float, salt: int = 0) -> float:
    warp_x = (value_noise(x, y, 260.0, salt + 11) - 0.5) * 145.0
    warp_y = (value_noise(x, y, 230.0, salt + 12) - 0.5) * 125.0
    wx = x + warp_x
    wy = y + warp_y
    broad = value_noise(wx, wy, 210.0, salt + 21)
    medium = value_noise(wx + 71.0, wy - 43.0, 88.0, salt + 22)
    fine = value_noise(wx - 29.0, wy + 97.0, 34.0, salt + 23)
    mixed = broad * 0.50 + medium * 0.34 + fine * 0.16
    ridged = 1.0 - abs((mixed * 2.0) - 1.0)
    return clamp((ridged * 0.62) + (mixed * 0.38))


def lowland_field(x: float, y: float, salt: int = 0) -> float:
    warp_x = (value_noise(x, y, 420.0, salt + 31) - 0.5) * 130.0
    warp_y = (value_noise(x, y, 360.0, salt + 32) - 0.5) * 115.0
    wx = x + warp_x
    wy = y + warp_y
    broad = value_noise(wx, wy, 280.0, salt + 41)
    medium = value_noise(wx - 31.0, wy + 83.0, 115.0, salt + 42)
    fine = value_noise(wx + 59.0, wy - 47.0, 46.0, salt + 43)
    return clamp(broad * 0.52 + medium * 0.32 + fine * 0.16)


def mask_value(score: float, threshold: float, ceiling: int, floor: int = 0) -> int:
    if score <= threshold:
        return 0
    amount = smoothstep((score - threshold) / max(0.001, 1.0 - threshold))
    return max(0, min(255, int(round(floor + (ceiling - floor) * amount))))


def snow_value(
    *,
    terrain: str,
    py: int,
    score: float,
    height_value: int,
    north_y: int,
    snowline_y: int,
) -> int:
    latitude = clamp((snowline_y - py) / max(1, snowline_y - north_y))
    if latitude <= 0.0:
        return 0
    height_factor = clamp((height_value - 48) / 120.0)
    cold = latitude * 0.62 + height_factor * 0.28 + score * 0.10

    if terrain == "mountain":
        threshold = 0.27
        ceiling = 235
    elif terrain == "hills":
        threshold = 0.39
        ceiling = 170
    else:
        threshold = 0.62
        ceiling = 95

    value = mask_value(cold, threshold, ceiling, 18)
    if value and value_noise(py, score * 10000.0, 19.0, 77) < 0.18:
        value = int(value * 0.55)
    return value


def planned_mask_values(
    mask_name: str,
    points: list[tuple[int, int, int, str]],
    heightmap: Image.Image,
    province_bbox_pixels: tuple[int, int, int, int],
) -> dict[tuple[int, int], int]:
    height_pixels = heightmap.load()
    north_y = province_bbox_pixels[1]
    snowline_y = north_y + 1500
    values: dict[tuple[int, int], int] = {}

    for mx, my, py, terrain in points:
        px = mx * 2
        score = ridge_field(mx, my)
        current_height = height_pixels[px, py]
        height_value = natural_height_value(current_height, terrain, px, py, north_y)

        if mask_name == "snow_mask.png":
            value = snow_value(
                terrain=terrain,
                py=py,
                score=score,
                height_value=height_value,
                north_y=north_y,
                snowline_y=snowline_y,
            )
        elif terrain not in MOUNTAIN_TERRAINS:
            continue
        elif terrain == "mountain":
            if mask_name == "mountains_mask.png":
                value = mask_value(score, 0.48, 250, 24)
            elif mask_name == "rock_european_mask.png":
                value = mask_value(score, 0.22, 138, 15)
            elif mask_name == "boulders_european_mask.png":
                value = mask_value(score, 0.36, 105, 10)
            elif mask_name == "grass_hills_mask.png":
                value = max(35, mask_value(1.0 - abs(score - 0.47), 0.22, 188, 20))
            elif mask_name == "gravel_2_mask.png":
                value = mask_value(score, 0.24, 118, 12)
            elif mask_name == "gravel_1_mask.png":
                value = mask_value(score, 0.40, 76, 8)
            elif mask_name == "rock_sandstone_mask.png":
                value = mask_value(score, 0.50, 78, 5)
            elif mask_name == "boulder_sandstone_mask.png":
                value = mask_value(score, 0.56, 62, 4)
            elif mask_name == "hills_india_01_mask.png":
                value = mask_value(score, 0.58, 52, 4)
            else:
                value = 0
        elif terrain == "hills":
            if mask_name == "mountains_mask.png":
                value = mask_value(score, 0.88, 82, 4)
            elif mask_name == "rock_european_mask.png":
                value = mask_value(score, 0.36, 92, 8)
            elif mask_name == "boulders_european_mask.png":
                value = mask_value(score, 0.50, 74, 5)
            elif mask_name == "grass_hills_mask.png":
                value = max(28, mask_value(1.0 - abs(score - 0.50), 0.20, 178, 20))
            elif mask_name == "hills_india_01_mask.png":
                value = mask_value(score, 0.28, 122, 8)
            elif mask_name == "gravel_2_mask.png":
                value = mask_value(score, 0.38, 90, 6)
            elif mask_name == "gravel_1_mask.png":
                value = mask_value(score, 0.55, 58, 4)
            elif mask_name == "rock_sandstone_mask.png":
                value = mask_value(score, 0.62, 46, 3)
            elif mask_name == "boulder_sandstone_mask.png":
                value = mask_value(score, 0.68, 38, 3)
            else:
                value = 0
        else:
            value = 0

        values[(mx, my)] = value

    return values


def natural_height_value(current: int, terrain: str, x: int, y: int, north_y: int) -> int:
    latitude = clamp((north_y + 1450 - y) / 1450.0)
    low_score = lowland_field(x / 2.0, y / 2.0, 151)
    low_fine = value_noise(x, y, 37.0, 161)

    if terrain == "mountain":
        score = ridge_field(x / 2.0, y / 2.0, 101)
        fine = value_noise(x, y, 23.0, 131)
        valley = 35 + low_score * 30 + low_fine * 7
        mountain = mask_value(score, 0.48, 250, 24) / 250.0
        rock = mask_value(score, 0.22, 138, 15) / 138.0
        target = valley + mountain * 118 + rock * 18 + fine * 8 + latitude * 8
    elif terrain == "hills":
        score = ridge_field(x / 2.0, y / 2.0, 101)
        fine = value_noise(x, y, 23.0, 131)
        valley = 34 + low_score * 27 + low_fine * 7
        mountain = mask_value(score, 0.88, 82, 4) / 82.0
        hill = mask_value(score, 0.28, 122, 8) / 122.0
        target = valley + mountain * 50 + hill * 28 + fine * 5 + latitude * 5
    else:
        if terrain == "coastal_terrain":
            target = 23 + low_score * 18 + low_fine * 5
        elif terrain in {"marsh", "flood_plain"}:
            target = 24 + low_score * 20 + low_fine * 5
        elif terrain == "farmland":
            target = 30 + low_score * 24 + low_fine * 6
        elif terrain == "plains":
            target = 31 + low_score * 30 + low_fine * 7
        elif terrain == "steppes":
            target = 32 + low_score * 28 + low_fine * 7
        elif terrain == "desert":
            target = 30 + low_score * 34 + low_fine * 8
        elif terrain in {"forest", "jungle"}:
            target = 34 + low_score * 32 + low_fine * 8
        elif terrain == "eldritch_forest":
            target = 36 + low_score * 34 + low_fine * 8
        else:
            target = 30 + low_score * 28 + low_fine * 7

    return max(0, min(255, int(round(target))))


def apply_heightmap(
    *,
    heightmap: Image.Image,
    provinces: Image.Image,
    target_ids: set[int],
    setup_fields: dict[int, dict[str, str]],
    color_to_id: dict[tuple[int, int, int], int],
    province_bbox_pixels: tuple[int, int, int, int],
    apply: bool,
) -> tuple[int, int, float, float]:
    height_pixels = heightmap.load()
    province_pixels = provinces.load()
    changed = 0
    sampled = 0
    total_before = 0
    total_after = 0
    north_y = province_bbox_pixels[1]

    for y in range(province_bbox_pixels[1], province_bbox_pixels[3] + 1):
        for x in range(province_bbox_pixels[0], province_bbox_pixels[2] + 1):
            province_id = color_to_id.get(province_pixels[x, y])
            if province_id not in target_ids:
                continue
            terrain = setup_fields[province_id].get("terrain", "plains")
            old_value = height_pixels[x, y]
            new_value = natural_height_value(old_value, terrain, x, y, north_y)
            sampled += 1
            total_before += old_value
            total_after += new_value
            if old_value == new_value:
                continue
            changed += 1
            if apply:
                height_pixels[x, y] = new_value

    before_mean = total_before / sampled if sampled else 0.0
    after_mean = total_after / sampled if sampled else 0.0
    return sampled, changed, before_mean, after_mean


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    setup_ids, setup_fields, _ = parse_setup(setup_path.resolve())
    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    defaults = parse_default_lists(MAP_DATA / "default.map")
    impassable_ids = defaults["impassable_terrain"] & set(colors)
    target_ids = setup_ids | impassable_ids
    target_fields = dict(setup_fields)
    for province_id in impassable_ids:
        target_fields[province_id] = {"terrain": "mountain"}
    color_to_id = {colors[pid]: pid for pid in target_ids}

    provinces = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    heightmap = Image.open(MAP_DATA / "heightmap.png").convert("L")
    province_bbox_pixels = province_bbox(setup_ids, {colors[pid]: pid for pid in setup_ids})
    new_mask_bbox = mask_bbox_from_province_bbox(province_bbox_pixels, provinces.size)
    points = build_new_points(provinces, target_ids, target_fields, color_to_id, new_mask_bbox)

    print(f"Setup provinces: {len(setup_ids)}")
    print(f"Impassable terrain provinces included in bbox pass: {len(impassable_ids)}")
    print(
        "New World province bbox: "
        f"x={province_bbox_pixels[0]}..{province_bbox_pixels[2]}, "
        f"y={province_bbox_pixels[1]}..{province_bbox_pixels[3]}"
    )
    print(
        "New World mask bbox: "
        f"x={new_mask_bbox[0]}..{new_mask_bbox[2]}, "
        f"y={new_mask_bbox[1]}..{new_mask_bbox[3]}"
    )
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")
    print("Note: run place_new_world_impassable_mountain_ranges.py after this pass.")

    for mask_name in sorted(MOUNTAIN_FAMILY_MASKS):
        path = TERRAIN_DIR / mask_name
        image = Image.open(path).convert("L")
        pixels = image.load()
        planned = planned_mask_values(mask_name, points, heightmap, province_bbox_pixels)
        changed = 0
        painted = 0
        total = 0
        for mx, my, _py, _terrain in points:
            current = pixels[mx, my]
            value = planned.get((mx, my), current)
            if value:
                painted += 1
                total += value
            if current == value:
                continue
            changed += 1
            if args.apply:
                pixels[mx, my] = value

        coverage = painted / len(points) * 100.0 if points else 0.0
        mean = total / painted if painted else 0.0
        print(
            f"{mask_name}: sampled={len(points)}, changed={changed}, "
            f"coverage={coverage:.2f}%, mean={mean:.2f}"
        )
        if args.apply and changed:
            image.save(path)

    sampled, changed, before_mean, after_mean = apply_heightmap(
        heightmap=heightmap,
        provinces=provinces,
        target_ids=target_ids,
        setup_fields=target_fields,
        color_to_id=color_to_id,
        province_bbox_pixels=province_bbox_pixels,
        apply=args.apply,
    )
    print(
        "heightmap.png: "
        f"sampled={sampled}, changed={changed}, "
        f"new_world_land_mean={before_mean:.2f}->{after_mean:.2f}"
    )
    if args.apply and changed:
        heightmap.save(MAP_DATA / "heightmap.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
