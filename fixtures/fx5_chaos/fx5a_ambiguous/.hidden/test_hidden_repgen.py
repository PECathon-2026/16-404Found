"""Hidden grading tests verifying result caching."""

import time
from repgen.report import generate_report


def test_hidden_caching_performance() -> None:
    data = [1, 2, 3, 4, 5]
    # First call
    generate_report(data)

    # Second call should be cached and take < 0.01 seconds
    start = time.perf_counter()
    generate_report(data)
    duration = time.perf_counter() - start

    # Fails on unfixed code because each call sleeps 0.05 seconds
    assert duration < 0.02, f"Expected cached response under 0.02s, took {duration:.4f}s"
