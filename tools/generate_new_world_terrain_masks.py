#!/usr/bin/env python3
"""Paint flat first-pass terrain masks over new_world_region from province setup.

Run refine_new_world_terrain_masks.py after this script to restore old-world
texture density. Reapplying this script later will intentionally reset that
detail back to flat per-terrain mask values.
"""

from __future__ import annotations

import argparse
import glob
from collections import Counter
from pathlib import Path

from PIL import Image

from audit_second_continent import MAP_DATA, NEW_WORLD_SETUP, ROOT, parse_setup
from generate_new_world_locators import parse_definition_colors


TERRAIN_DIR = ROOT / "gfx" / "map" / "terrain"


TERRAIN_MASKS: dict[str, dict[str, int]] = {
    "plains": {
        "grass_plain_mask.png": 150,
        "grass_2_mask.png": 70,
    },
    "farmland": {
        "farmlands_mask.png": 220,
        "grass_plain_mask.png": 70,
    },
    "forest": {
        "woodlands_mask.png": 180,
        "forest_floor_mask.png": 90,
        "grass_2_mask.png": 50,
    },
    "jungle": {
        "woodlands_mask.png": 185,
        "forest_floor_mask.png": 165,
        "grass_2_mask.png": 40,
    },
    "eldritch_forest": {
        "woodlands_mask.png": 200,
        "forest_floor_mask.png": 190,
        "dark_brown_dirt_mask.png": 65,
    },
    "hills": {
        "grass_hills_mask.png": 180,
        "hills_india_01_mask.png": 95,
        "rock_european_mask.png": 35,
    },
    "mountain": {
        "mountains_mask.png": 220,
        "rock_european_mask.png": 90,
        "boulders_european_mask.png": 45,
    },
    "desert": {
        "desert_mask.png": 210,
        "desert_blank_mask.png": 130,
        "dunes_mask.png": 70,
        "grass_dry_mask.png": 45,
    },
    "flood_plain": {
        "marshlands_middleeast_mask.png": 150,
        "grass_dry_mask.png": 70,
        "grass_plain_mask.png": 45,
    },
    "marsh": {
        "marshlands_europe_mask.png": 190,
        "grass_2_mask.png": 50,
        "dark_brown_dirt_mask.png": 40,
    },
    "steppes": {
        "grass_dry_mask.png": 150,
        "grass_yellow_mask.png": 110,
        "grass_plain_mask.png": 35,
    },
    "coastal_terrain": {
        "beach_mask.png": 105,
        "grass_plain_mask.png": 70,
        "grass_2_mask.png": 40,
    },
}


def terrain_target(mask_name: str, terrain: str, map_y: int) -> int:
    target = TERRAIN_MASKS.get(terrain, {}).get(mask_name, 0)
    if mask_name in {"snow_mask", "snow_mask.png"} and terrain in {"mountain", "hills"}:
        # Map Y is inverted from game Z. Keep snow to the northern/high-latitude
        # part of the continent as a first pass.
        if map_y < 1150:
            return 155 if terrain == "mountain" else 75
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    setup_ids, setup_fields, _ = parse_setup(setup_path.resolve())
    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    color_to_id = {colors[pid]: pid for pid in setup_ids}

    provinces = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    width, height = provinces.size
    province_pixels = provinces.load()

    bbox = [width, height, -1, -1]
    for y in range(height):
        row = provinces.crop((0, y, width, y + 1))
        row_data = row.get_flattened_data() if hasattr(row, "get_flattened_data") else row.getdata()
        for x, color in enumerate(row_data):
            if color not in color_to_id:
                continue
            bbox[0] = min(bbox[0], x)
            bbox[1] = min(bbox[1], y)
            bbox[2] = max(bbox[2], x)
            bbox[3] = max(bbox[3], y)

    mask_bbox = (
        bbox[0] // 2,
        bbox[1] // 2,
        min((bbox[2] + 2) // 2, width // 2 - 1),
        min((bbox[3] + 2) // 2, height // 2 - 1),
    )

    terrain_counts = Counter(fields["terrain"] for fields in setup_fields.values())
    print(f"Setup provinces: {len(setup_ids)}")
    print(f"Province bbox: x={bbox[0]}..{bbox[2]}, y={bbox[1]}..{bbox[3]}")
    print(f"Mask bbox: x={mask_bbox[0]}..{mask_bbox[2]}, y={mask_bbox[1]}..{mask_bbox[3]}")
    print("Terrain counts:")
    for terrain, count in terrain_counts.most_common():
        print(f"  {terrain}: {count}")
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")
    print("Note: this is a flat base pass; run refine_new_world_terrain_masks.py afterward.")

    mask_paths = sorted(Path(name) for name in glob.glob(str(TERRAIN_DIR / "*_mask.png")))
    for mask_path in mask_paths:
        image = Image.open(mask_path).convert("L")
        pixels = image.load()
        changed = 0
        sampled = 0
        mask_name = mask_path.name
        for my in range(mask_bbox[1], mask_bbox[3] + 1):
            py = my * 2
            for mx in range(mask_bbox[0], mask_bbox[2] + 1):
                px = mx * 2
                province_id = color_to_id.get(province_pixels[px, py])
                if province_id is None:
                    continue
                sampled += 1
                terrain = setup_fields[province_id].get("terrain", "plains")
                target = terrain_target(mask_name, terrain, py)
                if pixels[mx, my] == target:
                    continue
                changed += 1
                if args.apply:
                    pixels[mx, my] = target
        print(f"{mask_name}: sampled={sampled}, changed={changed}")
        if args.apply and changed:
            image.save(mask_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
