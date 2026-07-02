#!/usr/bin/env python3
"""Report visual map-layer coverage over new_world_region provinces."""

from __future__ import annotations

import argparse
import glob
import math
from collections import Counter
from pathlib import Path

from PIL import Image

from audit_second_continent import MAP_DATA, NEW_WORLD_SETUP, ROOT, parse_setup
from generate_new_world_locators import parse_definition_colors


TERRAIN_DIR = ROOT / "gfx" / "map" / "terrain"
RIVER_BACKGROUND_VALUES = {254, 255}


def row_data(image: Image.Image, y: int):
    row = image.crop((0, y, image.size[0], y + 1))
    return row.get_flattened_data() if hasattr(row, "get_flattened_data") else row.getdata()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    setup_ids, _, _ = parse_setup(setup_path.resolve())
    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    color_to_id = {colors[pid]: pid for pid in setup_ids}

    provinces = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    heightmap = Image.open(MAP_DATA / "heightmap.png").convert("L")
    rivers = Image.open(MAP_DATA / "rivers.png")
    width, height = provinces.size

    pixel_count = 0
    bbox = [width, height, -1, -1]
    height_min = 255
    height_max = 0
    height_sum = 0
    height_sum_sq = 0
    river_counts: Counter[int] = Counter()

    for y in range(height):
        province_row = row_data(provinces, y)
        height_row = row_data(heightmap, y)
        river_row = row_data(rivers, y)
        for x, color in enumerate(province_row):
            if color not in color_to_id:
                continue
            value = height_row[x]
            river_value = river_row[x]
            pixel_count += 1
            bbox[0] = min(bbox[0], x)
            bbox[1] = min(bbox[1], y)
            bbox[2] = max(bbox[2], x)
            bbox[3] = max(bbox[3], y)
            height_min = min(height_min, value)
            height_max = max(height_max, value)
            height_sum += value
            height_sum_sq += value * value
            river_counts.update([river_value])

    if pixel_count == 0:
        raise SystemExit("No pixels found for setup provinces.")

    height_mean = height_sum / pixel_count
    height_variance = max(0.0, (height_sum_sq / pixel_count) - (height_mean * height_mean))
    river_pixels = sum(count for value, count in river_counts.items() if value not in RIVER_BACKGROUND_VALUES)

    print(f"Setup provinces: {len(setup_ids)}")
    print(f"Province pixels: {pixel_count}")
    print(f"Province bbox: x={bbox[0]}..{bbox[2]}, y={bbox[1]}..{bbox[3]}")
    print(
        "Heightmap over provinces: "
        f"min={height_min}, max={height_max}, mean={height_mean:.2f}, stddev={math.sqrt(height_variance):.2f}"
    )
    print(f"River pixels over provinces: {river_pixels}")
    if river_pixels:
        river_values = [(value, count) for value, count in river_counts.most_common() if value not in RIVER_BACKGROUND_VALUES]
        print("River palette values:")
        for value, count in river_values[:10]:
            print(f"  {value}: {count}")

    mask_bbox = (
        bbox[0] // 2,
        bbox[1] // 2,
        min((bbox[2] + 2) // 2, width // 2 - 1),
        min((bbox[3] + 2) // 2, height // 2 - 1),
    )
    province_pixels = provinces.load()
    mask_results: list[tuple[int, int, int, str]] = []
    for mask_name in sorted(glob.glob(str(TERRAIN_DIR / "*_mask.png"))):
        mask_path = Path(mask_name)
        mask = Image.open(mask_path).convert("L")
        mask_pixels = mask.load()
        samples = 0
        painted = 0
        max_value = 0
        for my in range(mask_bbox[1], mask_bbox[3] + 1):
            py = my * 2
            for mx in range(mask_bbox[0], mask_bbox[2] + 1):
                px = mx * 2
                if province_pixels[px, py] not in color_to_id:
                    continue
                samples += 1
                value = mask_pixels[mx, my]
                if value:
                    painted += 1
                    max_value = max(max_value, value)
        mask_results.append((painted, samples, max_value, mask_path.name))

    print("Terrain mask coverage over sampled province pixels:")
    for painted, samples, max_value, name in sorted(mask_results, reverse=True):
        percent = (painted / samples * 100.0) if samples else 0.0
        print(f"  {name}: {painted}/{samples} ({percent:.2f}%), max={max_value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
