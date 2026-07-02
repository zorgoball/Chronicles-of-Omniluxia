#!/usr/bin/env python3
"""Place donor impassable mountain ranges over the central New World scar.

The central straight artifact sits mostly on existing impassable province IDs,
so this tool treats those IDs as the target and stamps mountain texture from
known-good impassable mountain tiles onto them. It does not change provinces.png
or convert playable setup provinces into impassable terrain.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image

from audit_second_continent import MAP_DATA, ROOT
from generate_new_world_locators import parse_definition_colors
from refine_new_world_terrain_masks import TERRAIN_DIR


DONOR_IDS = (5752, 5751, 3074, 5743, 5745)
TARGET_IDS = (1067, 1668, 1627, 598)

MASKS = {
    "mountains_mask.png": (1.12, 70, 0),
    "rock_european_mask.png": (1.18, 42, 18),
    "boulders_european_mask.png": (1.18, 34, 10),
    "boulder_sandstone_mask.png": (1.08, 22, 4),
    "grass_hills_mask.png": (1.00, 58, 42),
    "gravel_1_mask.png": (1.10, 28, 8),
    "gravel_2_mask.png": (1.14, 42, 14),
    "hills_india_01_mask.png": (1.04, 26, 5),
    "rock_sandstone_mask.png": (1.04, 32, 6),
    "snow_mask.png": (0.78, 30, 0),
}


@dataclass(frozen=True)
class Stamp:
    cx: float
    cy: float
    rx: float
    ry: float
    angle_degrees: float
    donor_id: int
    strength: float = 1.0


STAMPS = (
    Stamp(7320, 1438, 245, 95, -12, 5751, 0.95),
    Stamp(7225, 1598, 180, 120, -28, 3074, 1.00),
    Stamp(7425, 1748, 240, 118, 14, 5752, 1.00),
    Stamp(7245, 1925, 185, 140, 22, 5743, 0.92),
    Stamp(7475, 2108, 245, 145, -18, 5745, 1.00),
    Stamp(7355, 2290, 195, 118, 8, 5751, 0.86),
)


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


@lru_cache(maxsize=None)
def stable_noise(x: int, y: int, salt: int) -> float:
    value = (x * 0x45D9F3B + y * 0x119DE1F3 + salt * 0x27D4EB2D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x2C1B3C6D) & 0xFFFFFFFF
    value ^= value >> 12
    return value / 0xFFFFFFFF


def row_data(image: Image.Image, y: int):
    row = image.crop((0, y, image.size[0], y + 1))
    return row.get_flattened_data() if hasattr(row, "get_flattened_data") else row.getdata()


def find_bboxes(
    provinces: Image.Image,
    colors: dict[int, tuple[int, int, int]],
    ids: set[int],
) -> dict[int, tuple[int, int, int, int]]:
    wanted = {colors[province_id]: province_id for province_id in ids}
    boxes = {province_id: [provinces.size[0], provinces.size[1], -1, -1] for province_id in ids}
    for y in range(provinces.size[1]):
        for x, color in enumerate(row_data(provinces, y)):
            province_id = wanted.get(color)
            if province_id is None:
                continue
            box = boxes[province_id]
            box[0] = min(box[0], x)
            box[1] = min(box[1], y)
            box[2] = max(box[2], x)
            box[3] = max(box[3], y)

    result: dict[int, tuple[int, int, int, int]] = {}
    for province_id, box in boxes.items():
        if box[2] == -1:
            raise SystemExit(f"Could not locate province {province_id} in provinces.png")
        result[province_id] = (box[0], box[1], box[2], box[3])
    return result


def stamp_at(x: float, y: float) -> tuple[Stamp | None, float, float, float]:
    best: tuple[Stamp | None, float, float, float] = (None, 0.0, 0.0, 0.0)
    for stamp in STAMPS:
        angle = math.radians(stamp.angle_degrees)
        dx = x - stamp.cx
        dy = y - stamp.cy
        local_x = math.cos(angle) * dx + math.sin(angle) * dy
        local_y = -math.sin(angle) * dx + math.cos(angle) * dy
        q = (local_x / stamp.rx) ** 2 + (local_y / stamp.ry) ** 2
        if q >= 1.0:
            continue
        influence = smoothstep(1.0 - q) * stamp.strength
        if influence > best[1]:
            best = (stamp, influence, local_x / stamp.rx, local_y / stamp.ry)
    return best


def donor_sample_coord(
    donor_box: tuple[int, int, int, int],
    local_x: float,
    local_y: float,
    half_res: bool,
) -> tuple[int, int]:
    min_x, min_y, max_x, max_y = donor_box
    sx = min_x + ((local_x + 1.0) * 0.5) * (max_x - min_x)
    sy = min_y + ((local_y + 1.0) * 0.5) * (max_y - min_y)
    if half_res:
        return int(round(sx / 2.0)), int(round(sy / 2.0))
    return int(round(sx)), int(round(sy))


def target_union_box(boxes: dict[int, tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (
        min(box[0] for box in boxes.values()),
        min(box[1] for box in boxes.values()),
        max(box[2] for box in boxes.values()),
        max(box[3] for box in boxes.values()),
    )


def planned_mask_value(
    *,
    current: int,
    donor: int,
    mask_name: str,
    influence: float,
    x: int,
    y: int,
) -> int:
    scale, peak_floor, valley_floor = MASKS[mask_name]
    if influence <= 0.0:
        if valley_floor <= 0:
            return 0
        grain = stable_noise(x, y, len(mask_name))
        return int(round(valley_floor * (0.65 + grain * 0.45)))

    snow_threshold = 0.78
    if mask_name == "snow_mask.png" and influence < snow_threshold:
        return 0

    grain = stable_noise(x, y, len(mask_name) + 99)
    peak = max(peak_floor * influence, donor * scale)
    value = valley_floor * (1.0 - influence) + peak * influence
    value *= 0.88 + grain * 0.24
    if mask_name == "snow_mask.png":
        value *= smoothstep((influence - snow_threshold) / (1.0 - snow_threshold))
    return max(0, min(255, int(round(value))))


def planned_height_value(
    *,
    current: int,
    donor: int,
    influence: float,
    x: int,
    y: int,
) -> int:
    low = 54 + stable_noise(x, y, 501) * 24 + stable_noise(x // 5, y // 5, 502) * 16
    if influence <= 0.0:
        return int(round(low))

    peak = 96 + donor * 0.46 + stable_noise(x, y, 503) * 22
    value = low * (1.0 - influence) + peak * influence
    return max(0, min(255, int(round(value))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    provinces = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    province_pixels = provinces.load()
    color_to_id = {colors[province_id]: province_id for province_id in set(DONOR_IDS) | set(TARGET_IDS)}
    boxes = find_bboxes(provinces, colors, set(DONOR_IDS) | set(TARGET_IDS))
    target_box = target_union_box({province_id: boxes[province_id] for province_id in TARGET_IDS})

    print(f"Donor impassable tiles: {' '.join(map(str, DONOR_IDS))}")
    print(f"Target impassable tiles: {' '.join(map(str, TARGET_IDS))}")
    print(
        "Target bbox: "
        f"x={target_box[0]}..{target_box[2]}, y={target_box[1]}..{target_box[3]}"
    )
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")

    target_colors = {colors[province_id]: province_id for province_id in TARGET_IDS}
    mask_bbox = (
        target_box[0] // 2,
        target_box[1] // 2,
        min((target_box[2] + 2) // 2, provinces.size[0] // 2 - 1),
        min((target_box[3] + 2) // 2, provinces.size[1] // 2 - 1),
    )

    for mask_name in MASKS:
        path = TERRAIN_DIR / mask_name
        image = Image.open(path).convert("L")
        pixels = image.load()
        changed = 0
        sampled = 0
        painted = 0
        total = 0
        for my in range(mask_bbox[1], mask_bbox[3] + 1):
            py = my * 2
            for mx in range(mask_bbox[0], mask_bbox[2] + 1):
                px = mx * 2
                if province_pixels[px, py] not in target_colors:
                    continue
                sampled += 1
                stamp, influence, local_x, local_y = stamp_at(px, py)
                donor = 0
                if stamp is not None:
                    sx, sy = donor_sample_coord(boxes[stamp.donor_id], local_x, local_y, True)
                    sx = max(0, min(image.size[0] - 1, sx))
                    sy = max(0, min(image.size[1] - 1, sy))
                    donor = pixels[sx, sy]
                value = planned_mask_value(
                    current=pixels[mx, my],
                    donor=donor,
                    mask_name=mask_name,
                    influence=influence,
                    x=mx,
                    y=my,
                )
                if value:
                    painted += 1
                    total += value
                if pixels[mx, my] == value:
                    continue
                changed += 1
                if args.apply:
                    pixels[mx, my] = value
        coverage = painted / sampled * 100.0 if sampled else 0.0
        mean = total / painted if painted else 0.0
        print(
            f"{mask_name}: sampled={sampled}, changed={changed}, "
            f"coverage={coverage:.2f}%, mean={mean:.2f}"
        )
        if args.apply and changed:
            image.save(path)

    heightmap = Image.open(MAP_DATA / "heightmap.png").convert("L")
    height_pixels = heightmap.load()
    changed = 0
    sampled = 0
    total_before = 0
    total_after = 0
    for y in range(target_box[1], target_box[3] + 1):
        for x in range(target_box[0], target_box[2] + 1):
            if province_pixels[x, y] not in target_colors:
                continue
            sampled += 1
            current = height_pixels[x, y]
            stamp, influence, local_x, local_y = stamp_at(x, y)
            donor = 0
            if stamp is not None:
                sx, sy = donor_sample_coord(boxes[stamp.donor_id], local_x, local_y, False)
                sx = max(0, min(heightmap.size[0] - 1, sx))
                sy = max(0, min(heightmap.size[1] - 1, sy))
                donor = height_pixels[sx, sy]
            value = planned_height_value(
                current=current,
                donor=donor,
                influence=influence,
                x=x,
                y=y,
            )
            total_before += current
            total_after += value
            if current == value:
                continue
            changed += 1
            if args.apply:
                height_pixels[x, y] = value

    before_mean = total_before / sampled if sampled else 0.0
    after_mean = total_after / sampled if sampled else 0.0
    print(
        "heightmap.png: "
        f"sampled={sampled}, changed={changed}, "
        f"target_mean={before_mean:.2f}->{after_mean:.2f}"
    )
    if args.apply and changed:
        heightmap.save(MAP_DATA / "heightmap.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
