"""Compatibility import for the v0.1 workbench namespace."""

import importlib, sys

sys.modules[__name__] = importlib.import_module("hivemind_assembly.core.artifacts")
