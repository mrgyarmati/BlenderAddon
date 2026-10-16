"""Run the Blender integration tests.

    blender --background --factory-startup --python-exit-code 1 \
        --python tests/blender/run_all.py -- [--addon-dir DIR] [-k PATTERN] [-v]

``--addon-dir`` must contain an ``unreal_exporter`` package folder (defaults to
the repository's ``addon/`` directory; the release gate passes an unzipped
build instead). Exits with code 1 when any test fails.
"""

import argparse
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon-dir", default=os.path.join(REPO_ROOT, "addon"))
    parser.add_argument("-k", dest="pattern", default="")
    parser.add_argument("-v", dest="verbose", action="store_true")
    return parser.parse_args(argv)


def main():
    args = _args()
    from tests.blender import harness

    harness.load_addon(os.path.abspath(args.addon_dir))
    loader = unittest.TestLoader()
    if args.pattern:
        loader.testNamePatterns = ["*%s*" % args.pattern]
    suite = loader.discover(HERE, pattern="test_*.py", top_level_dir=REPO_ROOT)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2 if args.verbose else 1)
    result = runner.run(suite)
    sys.stdout.flush()
    if not result.wasSuccessful() or result.testsRun == 0:
        sys.exit(1)


main()
