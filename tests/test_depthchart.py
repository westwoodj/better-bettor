import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.services.depthchart_service import DepthChartService


def test_parse_sample_depthchart_orders_ranks():
    svc = DepthChartService()
    fp = os.path.join(ROOT, "src", "data", "espn", "football", "nfl", "depthcharts", "2-2025.json")
    result = svc.parse_from_file(fp, force=True)
    # Expect schemas for the sample file
    assert any("Base" in k or "Base_4-3_D" in k for k in result.keys())

    # Pick the Base 4-3 D schema key
    key = None
    for k in result.keys():
        if k.endswith("_2025") and "Base" in k:
            key = k
            break
    assert key is not None
    df = result[key]
    # DataFrame must have columns including position and rank
    assert "position" in df.columns
    assert "rank" in df.columns

    # For each (position, slot) group, ranks should be ordered ascending
    grouped = df.groupby(["position", "slot"])
    for _, group in grouped:
        ranks = list(group["rank"].dropna().astype(int).tolist())
        assert ranks == sorted(ranks)

