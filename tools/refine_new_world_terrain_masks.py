#!/usr/bin/env python3
"""Refine new_world_region terrain masks with old-world texture density.

The first-pass painter fills each province terrain with constant mask values.
This pass keeps the same province/terrain intent, but modulates those values
with donor texture from the established western landmass and adds conservative
secondary overlays so the new continent does not read as bare.
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

from PIL import Image

from audit_second_continent import (
    MAP_DATA,
    NEW_WORLD_SETUP,
    ROOT,
    SETUP_PROVINCES,
    parse_default_lists,
    parse_setup,
)
from generate_new_world_locators import parse_definition_colors
from generate_new_world_terrain_masks import TERRAIN_DIR, terrain_target


EXTRA_TERRAIN_MASKS: dict[str, dict[str, int]] = {
    "plains": {
        "grass_hills_mask.png": 70,
        "grass_dry_mask.png": 55,
        "gravel_2_mask.png": 28,
    },
    "farmland": {
        "grass_2_mask.png": 65,
        "grass_hills_mask.png": 42,
        "dark_brown_dirt_mask.png": 24,
        "gravel_1_mask.png": 18,
    },
    "forest": {
        "grass_hills_mask.png": 54,
        "dark_brown_dirt_mask.png": 32,
        "gravel_2_mask.png": 20,
    },
    "jungle": {
        "marshlands_europe_mask.png": 62,
        "grass_hills_mask.png": 36,
        "dark_brown_dirt_mask.png": 44,
    },
    "eldritch_forest": {
        "grass_hills_mask.png": 56,
        "marshlands_europe_mask.png": 48,
        "gravel_2_mask.png": 24,
    },
    "hills": {
        "grass_2_mask.png": 62,
        "grass_dry_mask.png": 48,
        "gravel_2_mask.png": 72,
        "gravel_1_mask.png": 42,
        "boulders_european_mask.png": 68,
    },
    "mountain": {
        "grass_hills_mask.png": 78,
        "gravel_2_mask.png": 84,
        "gravel_1_mask.png": 52,
        "rock_sandstone_mask.png": 46,
        "boulder_sandstone_mask.png": 38,
    },
    "desert": {
        "cracked_earth_soft_mask.png": 72,
        "rock_sandstone_mask.png": 64,
        "boulder_sandstone_mask.png": 52,
        "gravel_2_mask.png": 46,
        "grass_yellow_mask.png": 38,
    },
    "flood_plain": {
        "marshlands_europe_mask.png": 76,
        "dark_brown_dirt_mask.png": 48,
        "grass_2_mask.png": 44,
        "gravel_1_mask.png": 22,
    },
    "marsh": {
        "forest_floor_mask.png": 72,
        "woodlands_mask.png": 64,
        "dark_brown_dirt_mask.png": 58,
        "grass_plain_mask.png": 44,
    },
    "steppes": {
        "grass_hills_mask.png": 68,
        "gravel_2_mask.png": 42,
        "grass_2_mask.png": 38,
        "cracked_earth_soft_mask.png": 24,
    },
    "coastal_terrain": {
        "grass_hills_mask.png": 38,
        "grass_dry_mask.png": 34,
        "gravel_1_mask.png": 28,
        "dark_brown_dirt_mask.png": 20,
    },
}

TEXTURE_OFFSETS = ((0, 0), (389, 157), (911, 431))


def row_data(image: Image.Image, y: int):
    row = image.crop((0, y, image.size[0], y + 1))
    return row.get_flattened_data() if hasattr(row, "get_flattened_data") else row.getdata()


def stable_noise(x: int, y: int, salt: int) -> float:
    value = (x * 374761393 + y * 668265263 + salt * 1442695041) & 0xFFFFFFFF
    value ^= value >> 13
    value = (value * 1274126177) & 0xFFFFFFFF
    value ^= value >> 16
    return value / 0xFFFFFFFF


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 1
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * pct))))
    return sorted(values)[index]


def province_bbox(
    province_ids: set[int],
    color_to_id: dict[tuple[int, int, int], int],
) -> tuple[int, int, int, int]:
    provinces = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    width, height = provinces.size
    bbox = [width, height, -1, -1]
    for y in range(height):
        for x, color in enumerate(row_data(provinces, y)):
            if color_to_id.get(color) not in province_ids:
                continue
            bbox[0] = min(bbox[0], x)
            bbox[1] = min(bbox[1], y)
            bbox[2] = max(bbox[2], x)
            bbox[3] = max(bbox[3], y)
    if bbox[2] == -1:
        raise SystemExit("No pixels found for new_world_region.")
    return (bbox[0], bbox[1], bbox[2], bbox[3])


def mask_bbox_from_province_bbox(
    bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    width, height = image_size
    return (
        bbox[0] // 2,
        bbox[1] // 2,
        min((bbox[2] + 2) // 2, width // 2 - 1),
        min((bbox[3] + 2) // 2, height // 2 - 1),
    )


def read_all_setup_ids() -> set[int]:
    ids: set[int] = set()
    for path in SETUP_PROVINCES.glob("*.txt"):
        setup_ids, _, _ = parse_setup(path)
        ids.update(setup_ids)
    return ids


def build_new_points(
    provinces: Image.Image,
    setup_ids: set[int],
    setup_fields: dict[int, dict[str, str]],
    color_to_id: dict[tuple[int, int, int], int],
    new_mask_bbox: tuple[int, int, int, int],
) -> list[tuple[int, int, int, str]]:
    province_pixels = provinces.load()
    points: list[tuple[int, int, int, str]] = []
    for my in range(new_mask_bbox[1], new_mask_bbox[3] + 1):
        py = my * 2
        for mx in range(new_mask_bbox[0], new_mask_bbox[2] + 1):
            px = mx * 2
            province_id = color_to_id.get(province_pixels[px, py])
            if province_id not in setup_ids:
                continue
            terrain = setup_fields[province_id].get("terrain", "plains")
            points.append((mx, my, py, terrain))
    return points


def build_western_points(
    provinces: Image.Image,
    west_ids: set[int],
    all_color_to_id: dict[tuple[int, int, int], int],
    new_mask_bbox: tuple[int, int, int, int],
) -> list[tuple[int, int]]:
    province_pixels = provinces.load()
    points: list[tuple[int, int]] = []
    for my in range(provinces.size[1] // 2):
        py = my * 2
        for mx in range(new_mask_bbox[0]):
            px = mx * 2
            province_id = all_color_to_id.get(province_pixels[px, py])
            if province_id in west_ids:
                points.append((mx, my))
    return points


def collect_western_values(mask: Image.Image, western_points: list[tuple[int, int]]) -> list[int]:
    pixels = mask.load()
    values: list[int] = []
    for mx, my in western_points:
        value = pixels[mx, my]
        if value:
            values.append(value)
    return values


def donor_value(
    pixels,
    mx: int,
    my: int,
    mask_height: int,
    source_width: int,
    new_mask_bbox: tuple[int, int, int, int],
) -> int:
    local_x = mx - new_mask_bbox[0]
    values: list[int] = []
    for dx, dy in TEXTURE_OFFSETS:
        sx = (local_x + dx) % source_width
        sy = (my + dy) % mask_height
        values.append(pixels[sx, sy])
    return max(values)


def target_parts(mask_name: str, terrain: str, py: int) -> tuple[int, int]:
    base = terrain_target(mask_name, terrain, py)
    extra = EXTRA_TERRAIN_MASKS.get(terrain, {}).get(mask_name, 0)
    return base, extra


def refined_value(
    *,
    target: int,
    donor: int,
    donor_p90: int,
    mx: int,
    my: int,
    salt: int,
) -> int:
    if target <= 0:
        return 0

    texture = min(1.0, donor / max(1, donor_p90)) if donor else 0.0
    grain = stable_noise(mx, my, salt)
    fine = stable_noise(mx + 37, my - 19, salt + 17)

    # Keep terrain legible while letting the western donor texture break up
    # the flat first-pass plates.
    value = target * (0.28 + 0.62 * texture + 0.28 * grain)
    if donor == 0 and fine < 0.34:
        value *= 0.32
    if fine > 0.91:
        value *= 1.18

    return max(0, min(255, int(round(value))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    setup_ids, setup_fields, _ = parse_setup(setup_path.resolve())
    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    color_to_id = {colors[pid]: pid for pid in setup_ids}
    all_color_to_id = {color: province_id for province_id, color in colors.items()}

    provinces = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    province_bbox_pixels = province_bbox(setup_ids, color_to_id)
    new_mask_bbox = mask_bbox_from_province_bbox(province_bbox_pixels, provinces.size)
    source_width = max(1, new_mask_bbox[0])
    defaults = parse_default_lists(MAP_DATA / "default.map")
    special_ids = defaults["sea_zones"] | defaults["lakes"] | defaults["impassable_terrain"]
    west_ids = read_all_setup_ids() - setup_ids - special_ids
    new_points = build_new_points(provinces, setup_ids, setup_fields, color_to_id, new_mask_bbox)
    western_points = build_western_points(provinces, west_ids, all_color_to_id, new_mask_bbox)

    print(f"Setup provinces: {len(setup_ids)}")
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
    print(f"New World mask samples: {len(new_points)}")
    print(f"Western source mask samples: {len(western_points)}")
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")

    for salt, mask_name in enumerate(sorted(glob.glob(str(TERRAIN_DIR / "*_mask.png"))), start=1):
        mask_path = Path(mask_name)
        image = Image.open(mask_path).convert("L")
        pixels = image.load()
        donor_values = collect_western_values(image, western_points)
        donor_p90 = percentile(donor_values, 0.90)
        west_coverage = len(donor_values) / len(western_points) if western_points else 0.0

        planned_values: dict[tuple[int, int], int] = {}
        extra_candidates: list[tuple[float, int, int, int, int]] = []
        base_painted = 0
        total = 0
        for mx, my, py, terrain in new_points:
            base, extra = target_parts(mask_path.name, terrain, py)
            donor = donor_value(pixels, mx, my, image.size[1], source_width, new_mask_bbox)
            if base:
                target = max(base, extra)
                value = refined_value(
                    target=target,
                    donor=donor,
                    donor_p90=donor_p90,
                    mx=mx,
                    my=my,
                    salt=salt,
                )
                if value:
                    base_painted += 1
                    total += value
                planned_values[(mx, my)] = value
            elif extra:
                texture = min(1.0, donor / max(1, donor_p90)) if donor else 0.0
                score = (0.72 * texture) + (0.28 * stable_noise(mx, my, salt + 101))
                extra_candidates.append((score, mx, my, extra, donor))

        target_painted = max(base_painted, int(round(west_coverage * len(new_points))))
        extra_needed = max(0, min(len(extra_candidates), target_painted - base_painted))
        for _score, mx, my, extra, donor in sorted(extra_candidates, reverse=True)[:extra_needed]:
            value = refined_value(
                target=extra,
                donor=donor,
                donor_p90=donor_p90,
                mx=mx,
                my=my,
                salt=salt,
            )
            if value:
                total += value
                planned_values[(mx, my)] = value

        changed = 0
        for mx, my, _py, _terrain in new_points:
            value = planned_values.get((mx, my), 0)
            if pixels[mx, my] == value:
                continue
            changed += 1
            if args.apply:
                pixels[mx, my] = value

        painted = sum(1 for value in planned_values.values() if value)
        mean = total / painted if painted else 0.0
        coverage = (painted / len(new_points) * 100.0) if new_points else 0.0
        print(
            f"{mask_path.name}: sampled={len(new_points)}, changed={changed}, "
            f"coverage={coverage:.2f}%, west={west_coverage * 100.0:.2f}%, "
            f"mean={mean:.2f}, donor_p90={donor_p90}"
        )
        if args.apply and changed:
            image.save(mask_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
