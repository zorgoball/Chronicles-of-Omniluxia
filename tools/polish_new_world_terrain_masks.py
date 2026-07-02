#!/usr/bin/env python3
"""Terrain-mask polish for the New World.

Matches western-continent conventions measured from the shipped masks:

1. Beach mask around lake shores and any bare coastal seams
   (west profile: ~25-38 intensity at the shoreline fading over ~3 mask px).
2. Seafloor mask under New World coastal water and lakes
   (west profile: ramps 65 -> 140 with distance from shore; east had none).
3. Feathers the hard edges of the snow and desert masks so the snow line and
   desert borders blend instead of ending in a straight seam.

Masks are half resolution (4096x2048) relative to the 8192x4096 map.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
MAP_DATA = ROOT / "map_data"
TERRAIN = ROOT / "gfx" / "map" / "terrain"

# New World bbox in map pixels -> mask space is /2
MX0, MX1, MY0, MY1 = 5840 // 2, 8134 // 2, 368 // 2, 3866 // 2
WATERLINE = 39
LAKE_IDS = (471, 581, 1103, 1204, 2453, 2835, 4851, 5408)

FEATHER_MASKS = ("snow_mask.png", "desert_mask.png", "dunes_mask.png", "desert_blank_mask.png")
FEATHER_SIGMA = 2.0


def load_gray(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("L"))


def lake_mask_halfres() -> np.ndarray:
    import csv

    wanted = {}
    with open(MAP_DATA / "definition.csv", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle, delimiter=";"):
            if row and row[0].isdigit() and int(row[0]) in LAKE_IDS:
                wanted[int(row[0])] = (int(row[1]), int(row[2]), int(row[3]))
    prov = np.array(Image.open(MAP_DATA / "provinces.png").convert("RGB"))[::2, ::2]
    mask = np.zeros(prov.shape[:2], dtype=bool)
    for rgb in wanted.values():
        mask |= (prov[:, :, 0] == rgb[0]) & (prov[:, :, 1] == rgb[1]) & (prov[:, :, 2] == rgb[2])
    return mask


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for a dry run.")
    args = parser.parse_args()

    hm = np.array(Image.open(MAP_DATA / "heightmap.png").convert("L"))[::2, ::2]
    water = hm < WATERLINE
    lakes = lake_mask_halfres()

    box = np.zeros_like(water)
    box[MY0:MY1, MX0:MX1] = True

    d_from_land = ndimage.distance_transform_edt(water)      # 0 on land
    d_from_water = ndimage.distance_transform_edt(~water)    # 0 in water

    # --- 1. Beach around lake shores (and bare coast seams inside the box).
    beach_path = TERRAIN / "beach_mask.png"
    beach = load_gray(beach_path)
    lake_shore = ndimage.binary_dilation(lakes, iterations=4)
    shore_zone = box & (lake_shore | ((d_from_water <= 3) | (d_from_land <= 3)))
    beach_target = np.zeros_like(beach, dtype=np.float32)
    # on land: 25 at shoreline fading out; in water: 37 fading out
    land_side = shore_zone & ~water & (d_from_water <= 3)
    water_side = shore_zone & water & (d_from_land <= 3)
    beach_target[land_side] = np.maximum(0, 28 - 8 * (d_from_water[land_side] - 1))
    beach_target[water_side] = np.maximum(0, 38 - 9 * (d_from_land[water_side] - 1))
    beach_target = ndimage.gaussian_filter(beach_target, 1.0)
    new_beach = np.maximum(beach, beach_target.astype(np.uint8))
    beach_changed = int((new_beach != beach).sum())

    # --- 2. Seafloor under New World water (coastal shallows + lakes).
    sf_path = TERRAIN / "seafloor_mask.png"
    seafloor = load_gray(sf_path)
    sf_target = np.zeros_like(seafloor, dtype=np.float32)
    sea_zone = box & water
    ramp = np.clip(65 + (d_from_land - 1) * 19, 0, 145)
    sf_target[sea_zone] = ramp[sea_zone]
    sf_target[box & lakes] = np.clip(60 + (d_from_land[box & lakes] - 1) * 12, 0, 110)
    sf_target = ndimage.gaussian_filter(sf_target, 1.0)
    new_seafloor = np.maximum(seafloor, sf_target.astype(np.uint8))
    seafloor_changed = int((new_seafloor != seafloor).sum())

    print(f"beach px changed: {beach_changed}")
    print(f"seafloor px changed: {seafloor_changed}")

    # --- 3. Feather snow/desert edges inside the box.
    feathered: list[tuple[Path, np.ndarray, int]] = []
    for name in FEATHER_MASKS:
        path = TERRAIN / name
        arr = load_gray(path)
        sub = arr[MY0:MY1, MX0:MX1].astype(np.float32)
        present = sub > 8
        if not present.any():
            print(f"{name}: nothing to feather")
            continue
        edge = ndimage.binary_dilation(present, iterations=3) & ~ndimage.binary_erosion(present, iterations=3)
        blurred = ndimage.gaussian_filter(sub, FEATHER_SIGMA)
        sub[edge] = blurred[edge]
        new_arr = arr.copy()
        new_arr[MY0:MY1, MX0:MX1] = np.clip(np.rint(sub), 0, 255).astype(np.uint8)
        changed = int((new_arr != arr).sum())
        feathered.append((path, new_arr, changed))
        print(f"{name}: feathered px changed: {changed}")

    if args.apply:
        Image.fromarray(new_beach, mode="L").save(beach_path)
        Image.fromarray(new_seafloor, mode="L").save(sf_path)
        for path, new_arr, _ in feathered:
            Image.fromarray(new_arr, mode="L").save(path)
        print("masks written")
    else:
        print("Dry run only. Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
