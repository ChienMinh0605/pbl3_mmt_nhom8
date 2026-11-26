"""Compatibility import for the former router path and schema names."""

import sys

from backend.app.api import probe

sys.modules[__name__] = probe
