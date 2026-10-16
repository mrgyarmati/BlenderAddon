"""Unit tests run outside Blender (plain CPython 3.13+).

Run: python -m unittest discover -s tests/unit -t .   (or: python -m pytest tests/unit -q)
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDON_DIR = os.path.join(ROOT, "addon")
if ADDON_DIR not in sys.path:
    sys.path.insert(0, ADDON_DIR)
