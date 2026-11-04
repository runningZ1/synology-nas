"""Run the new CLI directly from a Skill checkout, without installing it."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from synology_nas_cli.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
