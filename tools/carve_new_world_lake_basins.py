#!/usr/bin/env python3
"""Carve heightmap basins for the New World gameplay lakes.

Lakes flagged in default.map only render as water where the heightmap sits
below the waterline (WATERLEVEL 3.9 / 25.5 * 255 = ~39). This tool sinks each
lake province into a smooth basin (edge ~36, center ~22) and blends a shore
slope into the surrounding land so the carve reads naturally. It only ever
lowers terrain, never raises it, so rivers/sea/neighboring lowlands are safe.

Run after apply_new_world_lakes.py. Remember to regenerate the packed
heightmap afterwards or the game will not show the change.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
MAP_DATA = ROOT / "map_data"

LAKE_IDS = (471, 581, 1103, 1204, 2453, 2835, 4851, 5408)

WATERLINE = 39
EDGE_DEPTH = 36        # height at the lake rim (below waterline)
CENTER_DEPTH = 22      # height toward the lake center
DEPTH_RAMP_PX = 10     # px from rim over which depth reaches CENTER_DEPTH
SHORE_BLEND_PX = 12    # px of land outside the lake blended into a shore slope
SHORE_HEIGHT = 42      # land height right at the shore before blending out


def load_colors() -> dict[int, tuple[int, int, int]]:
    colors: dict[int, tuple[int, int, int]] = {}
    with open(MAP_DATA / "definition.csv", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle, delimiter=";"):
            if row and row[0].isdigit():
                colors[int(row[0])] = (int(row[1]), int(row[2]), int(row[3]))
    return colors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for a dry run.")
    args = parser.parse_args()

    colors = load_colors()
    prov = np.array(Image.open(MAP_DATA / "provinces.png").convert("RGB"))
    hm_img = Image.open(MAP_DATA / "heightmap.png")
    hm = np.array(hm_img.convert("L")).astype(np.float32)
    original = hm.copy()

    for pid in LAKE_IDS:
        rgb = colors[pid]
        mask = (prov[:, :, 0] == rgb[0]) & (prov[:, :, 1] == rgb[1]) & (prov[:, :, 2] == rgb[2])
        if not mask.any():
            raise SystemExit(f"Province {pid} has no pixels in provinces.png")

        ys, xs = np.nonzero(mask)
        pad = SHORE_BLEND_PX + 4
        y0, y1 = max(0, ys.min() - pad), min(hm.shape[0], ys.max() + pad + 1)
        x0, x1 = max(0, xs.min() - pad), min(hm.shape[1], xs.max() + pad + 1)
        m = mask[y0:y1, x0:x1]
        sub = hm[y0:y1, x0:x1]

        # Basin floor: deeper toward the interior.
        d_in = ndimage.distance_transform_edt(m)
        ramp = np.clip(d_in / DEPTH_RAMP_PX, 0.0, 1.0)
        basin = EDGE_DEPTH - (EDGE_DEPTH - CENTER_DEPTH) * ramp
        sub[m] = np.minimum(sub[m], basin[m])

        # Shore slope: blend surrounding land down toward the rim (lower only).
        d_out = ndimage.distance_transform_edt(~m)
        ring = (~m) & (d_out <= SHORE_BLEND_PX)
        t = d_out / SHORE_BLEND_PX
        blend = SHORE_HEIGHT * (1.0 - t) + sub * t
        sub[ring] = np.minimum(sub[ring], blend[ring])

        # Gentle smoothing over the touched area so the carve is not terraced.
        touched = m | ring
        smooth = ndimage.gaussian_filter(sub, sigma=1.2)
        sub[touched] = smooth[touched]
        # Re-assert water depth after smoothing.
        sub[m] = np.minimum(sub[m], WATERLINE - 2)

        hm[y0:y1, x0:x1] = sub
        wet = int((sub[m] < WATERLINE).sum())
        print(
            f"{pid}: pixels={int(m.sum())} below-waterline={wet} "
            f"h now min={sub[m].min():.0f} max={sub[m].max():.0f} mean={sub[m].mean():.1f}"
        )

    changed = int((hm.astype(np.uint8) != original.astype(np.uint8)).sum())
    print(f"changed pixels: {changed}")
    if args.apply:
        out = Image.fromarray(hm.astype(np.uint8), mode="L")
        out.save(MAP_DATA / "heightmap.png")
        print("heightmap.png written")
    else:
        print("Dry run only. Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
