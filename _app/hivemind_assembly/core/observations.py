"""Bounded, owner-defined comparisons for native frame and audio captures.

Captures are raw, tightly packed data in the declared order. No image alignment,
anti-alias exclusion, audio resampling, gain normalization or time shifting is
performed: those transformations can conceal reconstruction regressions.
"""

import math
import struct
from .common import ContractError


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ContractError(f"{name} must be an integer from {low} to {high}")
    return value


def validate_comparators(value, outputs, limit):
    if not isinstance(value, dict) or set(value) - set(outputs):
        raise ContractError("Comparators must name observed output paths")
    for name, rule in value.items():
        if not isinstance(rule, dict):
            raise ContractError("Output comparator must be an object")
        kind = rule.get("format")
        if kind in ("rgba8", "rgba8_sequence"):
            fields = {
                "format",
                "width",
                "height",
                "max_channel_error",
                "max_bad_pixels",
            }
            if kind == "rgba8_sequence":
                fields |= {"frames", "frame_rate_num", "frame_rate_den"}
            if set(rule) - fields:
                raise ContractError("Unknown RGBA comparator fields")
            width = _integer(rule.get("width"), "width", 1, limit // 4)
            height = _integer(rule.get("height"), "height", 1, limit // 4)
            size = width * height * 4
            if kind == "rgba8_sequence":
                size *= _integer(rule.get("frames"), "frames", 1, 4096)
                _integer(rule.get("frame_rate_num"), "frame_rate_num", 1, 1000000)
                _integer(rule.get("frame_rate_den"), "frame_rate_den", 1, 1000000)
            _integer(
                rule.setdefault("max_channel_error", 0), "max_channel_error", 0, 255
            )
            _integer(
                rule.setdefault("max_bad_pixels", 0),
                "max_bad_pixels",
                0,
                width * height,
            )
        elif kind == "pcm_s16le":
            if set(rule) - {
                "format",
                "channels",
                "sample_rate",
                "frames",
                "max_sample_error",
                "max_rms_error",
            }:
                raise ContractError("Unknown PCM comparator fields")
            channels = _integer(rule.get("channels"), "channels", 1, 32)
            _integer(rule.get("sample_rate"), "sample_rate", 1, 384000)
            frames = _integer(rule.get("frames"), "frames", 1, limit // 2)
            size = channels * frames * 2
            _integer(
                rule.setdefault("max_sample_error", 0), "max_sample_error", 0, 65535
            )
            rms = rule.setdefault("max_rms_error", 0)
            if (
                type(rms) not in (int, float)
                or not math.isfinite(rms)
                or not 0 <= rms <= 65535
            ):
                raise ContractError(
                    "max_rms_error must be finite and between 0 and 65535"
                )
        else:
            raise ContractError("Comparator format must be rgba8, rgba8_sequence or pcm_s16le")
        if size > limit:
            raise ContractError("Declared capture exceeds output size limit")
    return value


def capture_size(rule):
    if rule["format"] in ("rgba8", "rgba8_sequence"):
        frames = rule["frames"] if rule["format"] == "rgba8_sequence" else 1
        return rule["width"] * rule["height"] * 4 * frames
    return rule["channels"] * rule["frames"] * 2


def compare_capture(actual, expected, rule):
    """Compare validated byte captures; metrics refer to raw sample units."""
    result = {"format": rule["format"], "passed": False, "exact": False}
    size = capture_size(rule)
    if actual is None or expected is None:
        return result | {"reason": "missing_capture"}
    if len(actual) != size or len(expected) != size:
        return result | {
            "reason": "capture_size_mismatch",
            "required_bytes": size,
            "actual_bytes": len(actual),
            "expected_bytes": len(expected),
        }
    result["exact"] = actual == expected
    if rule["format"] == "rgba8_sequence":
        stride = rule["width"] * rule["height"] * 4
        frame_rule = rule | {"format": "rgba8"}
        frames = [
            compare_capture(actual[offset:offset + stride], expected[offset:offset + stride], frame_rule)
            for offset in range(0, size, stride)
        ]
        return result | {
            "passed": all(frame["passed"] for frame in frames),
            "reason": "compared",
            "different_frames": sum(not frame["exact"] for frame in frames),
            "failed_frames": sum(not frame["passed"] for frame in frames),
            "first_difference_frame": next((i for i, frame in enumerate(frames) if not frame["exact"]), None),
            "first_failed_frame": next((i for i, frame in enumerate(frames) if not frame["passed"]), None),
            "declared_duration_seconds": rule["frames"] * rule["frame_rate_den"] / rule["frame_rate_num"],
            "frames": frames,
        }
    if rule["format"] == "rgba8":
        bad = different = peak = 0
        bounds = None
        for offset in range(0, size, 4):
            error = max(
                abs(actual[offset + c] - expected[offset + c]) for c in range(4)
            )
            peak = max(peak, error)
            different += error != 0
            if error > rule["max_channel_error"]:
                bad += 1
                x, y = (offset // 4) % rule["width"], (offset // 4) // rule["width"]
                if bounds is None:
                    bounds = [x, y, x, y]
                else:
                    bounds = [
                        min(bounds[0], x),
                        min(bounds[1], y),
                        max(bounds[2], x),
                        max(bounds[3], y),
                    ]
        return result | {
            "passed": bad <= rule["max_bad_pixels"],
            "reason": "compared",
            "different_pixels": different,
            "bad_pixels": bad,
            "peak_channel_error": peak,
            "bad_pixel_bounds": bounds,
        }
    channels = rule["channels"]
    peaks, sums, changed = [0] * channels, [0] * channels, [0] * channels
    first = None
    for i, (a, b) in enumerate(
        zip(struct.iter_unpack("<h", actual), struct.iter_unpack("<h", expected))
    ):
        channel = i % channels
        error = abs(a[0] - b[0])
        peaks[channel] = max(peaks[channel], error)
        sums[channel] += error * error
        changed[channel] += error != 0
        if error and first is None:
            first = {"frame": i // channels, "channel": channel}
    rms = [math.sqrt(total / rule["frames"]) for total in sums]
    return result | {
        "passed": all(
            p <= rule["max_sample_error"] and r <= rule["max_rms_error"]
            for p, r in zip(peaks, rms)
        ),
        "reason": "compared",
        "peak_sample_error": peaks,
        "rms_error": rms,
        "different_samples": changed,
        "first_difference": first,
        "duration_seconds": rule["frames"] / rule["sample_rate"],
    }


def compare_observation(actual, expected, comparators):
    """Execution/streams stay exact; only explicitly named files get tolerance."""
    base_keys = ("status", "exit_code", "stdout_hex", "stderr_hex")
    passed = (
        actual.get("status") == expected.get("status") == "completed"
        and type(actual.get("exit_code")) is int
        and 0 <= actual["exit_code"] < 0xC0000000
        and all(actual.get(k) == expected.get(k) for k in base_keys)
    )
    metrics = {}
    if set(actual["files"]) != set(expected["files"]):
        passed = False
    for name in expected["files"]:
        if name in comparators:
            captures = [
                row.get("file_contents_hex", {}).get(name) for row in (actual, expected)
            ]
            detail = compare_capture(
                *(bytes.fromhex(v) if v is not None else None for v in captures),
                comparators[name],
            )
        else:
            detail = {
                "format": "exact",
                "passed": name in actual["files"]
                and actual["files"][name] == expected["files"][name],
            }
        metrics[name] = detail
        passed = passed and detail["passed"]
    return {"passed": bool(passed), "files": metrics}
