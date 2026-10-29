"""Report generator module."""

import time
from typing import Dict, List


def generate_report(data: List[int]) -> Dict[str, float]:
    """Generates analytical metrics from numerical data."""
    # Simulates expensive calculation
    time.sleep(0.05)
    if not data:
        return {"count": 0, "mean": 0.0, "sum": 0.0}

    total = float(sum(data))
    count = len(data)
    mean = total / count
    return {"count": float(count), "mean": mean, "sum": total}
