# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import random
import threading
import time
_jitter_counter = 0
_jitter_lock = threading.Lock()

def jittered_backoff(attempt: int, *, base_delay: float=5.0, max_delay: float=120.0, jitter_ratio: float=0.5) -> float:
    """min(base * 2^(attempt-1), max_delay) + uniform jitter in
    [0, jitter_ratio * delay]. ``attempt`` is 1-based."""
    global _jitter_counter
    with _jitter_lock:
        _jitter_counter += 1
        tick = _jitter_counter
    exponent = max(0, attempt - 1)
    delay = max_delay if exponent >= 63 or base_delay <= 0 else min(base_delay * 2 ** exponent, max_delay)
    seed = (time.time_ns() ^ tick * 2654435769) & 4294967295
    return delay + random.Random(seed).uniform(0, jitter_ratio * delay)
