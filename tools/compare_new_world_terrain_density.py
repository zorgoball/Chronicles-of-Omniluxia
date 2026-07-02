#!/usr/bin/env python3
"""Compare terrain-mask density between the old west and new_world_region."""

from __future__ import annotations

import argparse
import glob
from dataclasses import dataclass
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


TERRAIN_DIR = ROOT / "gfx" / "map" / "terrain"


@dataclass
class Stats:
    samples: int = 0
    painted: int = 0
    total: int = 0
    total_sq: int = 0
    transitions: int = 0
    comparable_edges: int = 0

    def add(self, value: int) -> None:
        self.samples += 1
        if value:
            self.painted += 1
            self.total += value
            self.total_sq += value * value

    def coverage(self) -> float:
        return self.painted / self.samples if self.samples else 0.0

    def mean(self) -> float:
        return self.total / self.painted if self.painted else 0.0

    def transition_rate(self) -> float:
        return self.transitions / self.comparable_edges if self.comparable_edges else 0.0


def read_all_setup_ids() -> set[int]:
    ids: set[int] = set()
    for path in SETUP_PROVINCES.glob("*.txt"):
        setup_ids, _, _ = parse_setup(path)
        ids.update(setup_ids)
    return ids


def province_bbox(province_ids: set[int], color_to_id: dict[tuple[int, int, int], int]) -> tuple[int, int, int, int]:
    provinces = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    width, height = provinces.size
    bbox = [width, height, -1, -1]
    for y in range(height):
        row_image = provinces.crop((0, y, width, y + 1))
        row = row_image.get_flattened_data() if hasattr(row_image, "get_flattened_data") else row_image.getdata()
        for x, color in enumerate(row):
            province_id = color_to_id.get(color)
            if province_id not in province_ids:
                continue
            bbox[0] = min(bbox[0], x)
            bbox[1] = min(bbox[1], y)
            bbox[2] = max(bbox[2], x)
            bbox[3] = max(bbox[3], y)
    if bbox[2] == -1:
        raise SystemExit("No pixels found for requested provinces.")
    return (bbox[0], bbox[1], bbox[2], bbox[3])


def collect_stats(mask: Image.Image, sample_points: list[tuple[int, int]]) -> Stats:
    pixels = mask.load()
    point_set = set(sample_points)
    stats = Stats()
    for mx, my in sample_points:
        value = pixels[mx, my]
        stats.add(value)
        right = (mx + 1, my)
        if right in point_set:
            stats.comparable_edges += 1
            if pixels[right[0], right[1]] != value:
                stats.transitions += 1
        down = (mx, my + 1)
        if down in point_set:
            stats.comparable_edges += 1
            if pixels[down[0], down[1]] != value:
                stats.transitions += 1
    return stats


def build_sample_points(
    province_ids: set[int],
    color_to_id: dict[tuple[int, int, int], int],
    *,
    x_max_exclusive: int | None = None,
    bbox: tuple[int, int, int, int] | None = None,
) -> list[tuple[int, int]]:
    provinces = Image.open(MAP_DATA / "provinces.png").convert("RGB")
    width, height = provinces.size
    province_pixels = provinces.load()
    if bbox is None:
        bbox = (0, 0, width - 1, height - 1)
    mask_bbox = (
        bbox[0] // 2,
        bbox[1] // 2,
        min((bbox[2] + 2) // 2, width // 2 - 1),
        min((bbox[3] + 2) // 2, height // 2 - 1),
    )

    points: list[tuple[int, int]] = []
    for my in range(mask_bbox[1], mask_bbox[3] + 1):
        py = my * 2
        for mx in range(mask_bbox[0], mask_bbox[2] + 1):
            px = mx * 2
            if x_max_exclusive is not None and px >= x_max_exclusive:
                continue
            province_id = color_to_id.get(province_pixels[px, py])
            if province_id in province_ids:
                points.append((mx, my))
    return points


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", type=Path, default=NEW_WORLD_SETUP)
    args = parser.parse_args()

    setup_path = args.setup if args.setup.is_absolute() else ROOT / args.setup
    new_ids, _, _ = parse_setup(setup_path.resolve())
    all_setup_ids = read_all_setup_ids()
    defaults = parse_default_lists(MAP_DATA / "default.map")
    special = defaults["sea_zones"] | defaults["lakes"] | defaults["impassable_terrain"]

    colors = parse_definition_colors(MAP_DATA / "definition.csv")
    color_to_id = {color: province_id for province_id, color in colors.items()}
    new_bbox = province_bbox(new_ids, color_to_id)

    west_ids = all_setup_ids - new_ids - special
    west_points = build_sample_points(west_ids, color_to_id, x_max_exclusive=new_bbox[0])
    new_points = build_sample_points(new_ids, color_to_id, bbox=new_bbox)

    print(f"Western source samples: {len(west_points)}")
    print(f"New World samples: {len(new_points)}")
    print(f"New World province bbox: x={new_bbox[0]}..{new_bbox[2]}, y={new_bbox[1]}..{new_bbox[3]}")
    print()
    print("mask,west_cov,new_cov,west_mean,new_mean,west_transition,new_transition")
    for mask_name in sorted(glob.glob(str(TERRAIN_DIR / "*_mask.png"))):
        mask_path = Path(mask_name)
        mask = Image.open(mask_path).convert("L")
        west = collect_stats(mask, west_points)
        new = collect_stats(mask, new_points)
        print(
            f"{mask_path.name},"
            f"{west.coverage() * 100.0:.2f},"
            f"{new.coverage() * 100.0:.2f},"
            f"{west.mean():.2f},"
            f"{new.mean():.2f},"
            f"{west.transition_rate() * 100.0:.2f},"
            f"{new.transition_rate() * 100.0:.2f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
