"""Hivemind Assembly: collaborative automation and learning."""

# This must precede any import that initializes ONNX Runtime. It is also
# inherited by HA-owned helpers; native inference remains local-only.
import os

os.environ["ORT_DISABLE_TELEMETRY"] = "1"

__version__ = "0.37.4"
