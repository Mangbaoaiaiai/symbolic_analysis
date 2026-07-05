#!/usr/bin/env python3
"""Compatibility entry point for the maintained symbolic executor.

Older experiment scripts call ``scripts/se_script.py`` directly. The maintained
implementation now lives in ``scripts/se_script_improved.py``; this wrapper keeps
the old command stable without carrying a second symbolic-execution engine.
"""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    target = Path(__file__).with_name("se_script_improved.py")
    runpy.run_path(str(target), run_name="__main__")
