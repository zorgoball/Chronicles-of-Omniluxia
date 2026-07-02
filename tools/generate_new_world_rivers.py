#!/usr/bin/env python3
"""Compatibility entry point for New World river generation.

The current river pass copies and transforms established western-continent
river shapes instead of routing synthetic rivers to ports.
"""

from __future__ import annotations

from copy_western_river_shapes_to_new_world import main


if __name__ == "__main__":
    raise SystemExit(main())
