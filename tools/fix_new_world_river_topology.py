#!/usr/bin/env python3
"""Fix New World river topology so the engine accepts it.

The western-shape copy pass produced strokes that are 2px thick in places
(rotation/scaling artifacts). Imperator requires rivers to be 1px wide with no
loops; thick spots create 2x2 pixel blocks and cycles, which surface in
error.log as "Circular river found at X, Y" and crash the game while building
cached adjacency data ("Updating cached data...").

This tool, restricted to the New World bounding box:
1. Thins the river mask to a 1px skeleton (preserving special pixels 0-2:
   source / merge / split).
2. Removes any remaining 2x2 blocks.
3. Breaks every remaining 4-connected cycle via spanning-tree pruning.
4. Verifies the result has zero 2x2 blocks and zero cycles.

Safe to re-run after any river regeneration.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
RIVERS = ROOT / "map_data" / "rivers.png"

X0, X1, Y0, Y1 = 5840, 8134, 368, 3866
LAND = 254
SPECIAL = (0, 1, 2)  # source, merge, split markers


def count_topology(mask: np.ndarray) -> tuple[int, int, int, int, int]:
    v = int(mask.sum())
    e = int((mask[:, 1:] & mask[:, :-1]).sum()) + int((mask[1:] & mask[:-1]).sum())
    _, c = ndimage.label(mask, structure=[[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    blocks = int((mask[1:, 1:] & mask[1:, :-1] & mask[:-1, 1:] & mask[:-1, :-1]).sum())
    return v, e, c, e - v + c, blocks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for a dry run.")
    args = parser.parse_args()

    from skimage.morphology import thin

    img = Image.open(RIVERS)
    if img.mode != "P":
        raise SystemExit(f"rivers.png is {img.mode}, expected P (palette)")
    arr = np.array(img)
    sub = arr[Y0:Y1, X0:X1].copy()
    mask = sub < 16
    special = np.isin(sub, SPECIAL)

    v0 = count_topology(mask)
    print(f"before: pixels={v0[0]} cycles={v0[3]} 2x2blocks={v0[4]}")

    # 1. Thin to skeleton, keeping special pixels pinned.
    skel = thin(mask)
    skel |= special

    # 2. Remove remaining 2x2 blocks: drop one non-special corner per block.
    def kill_blocks(m: np.ndarray) -> int:
        removed = 0
        blocks = m[1:, 1:] & m[1:, :-1] & m[:-1, 1:] & m[:-1, :-1]
        for y, x in zip(*np.nonzero(blocks)):
            for dy, dx in ((1, 1), (1, 0), (0, 1), (0, 0)):
                yy, xx = y + dy, x + dx
                if m[yy, xx] and not special[yy, xx]:
                    m[yy, xx] = False
                    removed += 1
                    break
        return removed

    removed_blocks = kill_blocks(skel)

    # 3. Break remaining 4-connected cycles: BFS spanning tree per component;
    # for each extra edge, delete a non-special endpoint.
    coords = {tuple(p): i for i, p in enumerate(np.argwhere(skel))}
    parent = list(range(len(coords)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    removed_cycle = 0
    pts = list(coords)
    for (y, x) in pts:
        if not skel[y, x]:
            continue
        for dy, dx in ((0, 1), (1, 0)):
            yy, xx = y + dy, x + dx
            if (yy, xx) in coords and skel[yy, xx]:
                a, b = find(coords[(y, x)]), find(coords[(yy, xx)])
                if a == b:
                    # cycle edge: remove one endpoint
                    if not special[y, x]:
                        skel[y, x] = False
                    elif not special[yy, xx]:
                        skel[yy, xx] = False
                    removed_cycle += 1
                else:
                    parent[a] = b

    # rebuild union-find after removals is overkill; verify instead and loop.
    for _ in range(4):
        v = count_topology(skel)
        if v[3] == 0 and v[4] == 0:
            break
        kill_blocks(skel)
        # brute-force: cut one edge of each remaining cycle
        lab, n = ndimage.label(skel, structure=[[0, 1, 0], [1, 1, 1], [0, 1, 0]])
        # recompute with fresh union-find
        coords = {tuple(p): i for i, p in enumerate(np.argwhere(skel))}
        parent = list(range(len(coords)))
        for (y, x) in list(coords):
            if not skel[y, x]:
                continue
            for dy, dx in ((0, 1), (1, 0)):
                yy, xx = y + dy, x + dx
                if (yy, xx) in coords and skel[yy, xx]:
                    a, b = find(coords[(y, x)]), find(coords[(yy, xx)])
                    if a == b:
                        target = (y, x) if not special[y, x] else (yy, xx)
                        skel[target] = False
                        removed_cycle += 1
                    else:
                        parent[a] = b

    v1 = count_topology(skel)
    print(f"after: pixels={v1[0]} cycles={v1[3]} 2x2blocks={v1[4]} "
          f"(thinned {v0[0]-v1[0]}, block-fixes {removed_blocks}, cycle-cuts {removed_cycle})")
    if v1[3] != 0 or v1[4] != 0:
        raise SystemExit("could not fully clean river topology; not writing")

    new_sub = np.where(skel, np.where(mask, sub, 3), LAND).astype(np.uint8)
    # special pixels keep their original values
    new_sub[special] = sub[special]
    changed = int((new_sub != sub).sum())
    print(f"changed pixels: {changed}")

    if args.apply:
        out = arr.copy()
        out[Y0:Y1, X0:X1] = new_sub
        res = Image.fromarray(out, mode="P")
        res.putpalette(img.getpalette())
        res.save(RIVERS)
        print("rivers.png written")
    else:
        print("Dry run only. Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
