"""Checks against the real local DB (skipped if not built)."""
import pytest
from dfs_intel.storage import DB, refresh_views, facts_as_of
from dfs_intel.slate_import import import_salary
from pathlib import Path
pytestmark = pytest.mark.skipif(not DB.exists(), reason="db not built")
EX = Path(__file__).resolve().parent.parent / "examples"


def test_no_leakage_nfl():
    r = facts_as_of("nfl_player_week", "2024-09-01")
    assert len(r) and r.season.max() <= 2023 and (r.effective_at <= "2024-09-01").all()


def test_example_slate_matching():
    n = import_salary(EX / "EXAMPLE_DKSalaries_NFL_SYNTHETIC.csv", store=False)
    assert n["matched"] == 5 and n["unmatched"] == 1  # 'Notareal Player' is intentionally fake
    u = import_salary(EX / "EXAMPLE_DKSalaries_UFC_SYNTHETIC.csv", store=False)
    assert u["matched"] == 2 and u["unmatched"] == 1
