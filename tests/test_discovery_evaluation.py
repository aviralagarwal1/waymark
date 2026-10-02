import json
from pathlib import Path

import pytest

from evaluations.run_discovery import run_case

CASES = json.loads((Path(__file__).parents[1] / "evaluations" / "discovery_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"] + "-" + case["label"])
def test_labeled_synthetic_case(case):
    result = run_case(case)
    assert result["passed"], result
