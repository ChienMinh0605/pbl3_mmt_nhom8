"""Compatibility import for the former router path and schema names."""

import sys

from backend.app.api import device_activity

sys.modules[__name__] = device_activity
