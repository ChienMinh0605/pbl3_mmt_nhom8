"""Compatibility import for the former router path."""

import sys

from backend.app.api import csi_reliability

sys.modules[__name__] = csi_reliability
