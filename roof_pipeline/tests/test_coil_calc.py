"""Unit tests for coil calculator.

Run via:  python3 -m pytest roof_pipeline/tests/test_coil_calc.py -v
"""

import math

import pytest

from roof_pipeline.coil_calc import (
    COIL_SPECS,
    coil_from_geometry,
    coil_from_required_linear_ft,
    estimate_coils_for_cutsheet,
    lookup_spec,
)


# ---------------------------------------------------------------------------
# Forward: known ID/OD -> linear ft (cross-check against raw annulus formula)
# ---------------------------------------------------------------------------


def test_forward_24ga_steel_16in_coil():
    """24ga galvalume, ID=20", OD=40", width=16" — sanity check.
    Buildup = 10", wraps = 10 / 0.0239 = 418.4
    avg circ = pi * 30 / 12 = 7.854 ft
    linear_ft = 3286 ft (approx)
    """
    t, rho = lookup_spec("steel", "24ga")
    est = coil_from_geometry(id_in=20.0, od_in=40.0, thickness_in=t,
                             width_in=16.0, lb_per_sqft=rho)

    expected_wraps = 10.0 / 0.0239
    expected_linear_ft = expected_wraps * math.pi * 30.0 / 12.0
    assert abs(est.wraps - expected_wraps) < 0.01
    assert abs(est.linear_ft - expected_linear_ft) / expected_linear_ft < 0.001
    assert est.from_geometry is True


def test_forward_26ga_consistency():
    """26ga steel, small coil. Forward and re-computed should agree."""
    t, rho = lookup_spec("steel", "26ga")
    est = coil_from_geometry(id_in=16.0, od_in=36.0, thickness_in=t,
                             width_in=12.0, lb_per_sqft=rho)
    # Width 12" means 1 ft, so sqft should equal linear_ft exactly.
    assert abs(est.sqft - est.linear_ft) < 1e-6
    assert est.weight_lb > 0
    assert est.od_in > est.id_in


# ---------------------------------------------------------------------------
# Inverse: required linear ft -> OD -> re-solve forward should match
# ---------------------------------------------------------------------------


def test_inverse_roundtrip_24ga():
    t, rho = lookup_spec("steel", "24ga")
    target_ft = 2500.0
    est = coil_from_required_linear_ft(
        linear_ft_needed=target_ft,
        id_in=20.0,
        thickness_in=t,
        width_in=16.0,
        lb_per_sqft=rho,
    )
    assert est.from_geometry is False
    # Re-run forward with the derived OD — should get back the same linear_ft.
    forward = coil_from_geometry(
        id_in=20.0, od_in=est.od_in, thickness_in=t,
        width_in=16.0, lb_per_sqft=rho,
    )
    assert abs(forward.linear_ft - target_ft) / target_ft < 0.005
    assert abs(est.linear_ft - target_ft) / target_ft < 0.005


def test_inverse_roundtrip_aluminum():
    t, rho = lookup_spec("aluminum", "0.040")
    target_ft = 1200.0
    est = coil_from_required_linear_ft(
        linear_ft_needed=target_ft, id_in=16.0,
        thickness_in=t, width_in=20.0, lb_per_sqft=rho,
    )
    forward = coil_from_geometry(
        id_in=16.0, od_in=est.od_in, thickness_in=t,
        width_in=20.0, lb_per_sqft=rho,
    )
    assert abs(forward.linear_ft - target_ft) / target_ft < 0.005


# ---------------------------------------------------------------------------
# Gauge lookup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("material,gauge", [
    ("steel", "22ga"), ("steel", "24ga"), ("steel", "26ga"),
    ("aluminum", "0.032"), ("aluminum", "0.040"), ("aluminum", "0.050"),
    ("copper", "16oz"), ("copper", "20oz"),
])
def test_lookup_spec_all_known_combos(material, gauge):
    t, rho = lookup_spec(material, gauge)
    assert t > 0
    assert rho > 0


def test_lookup_spec_unknown_raises():
    with pytest.raises(KeyError):
        lookup_spec("titanium", "24ga")
    with pytest.raises(KeyError):
        lookup_spec("steel", "99ga")


# ---------------------------------------------------------------------------
# Aggregation helper
# ---------------------------------------------------------------------------


def test_estimate_coils_groups_and_waste():
    groups = [
        {"material": "steel", "gauge": "24ga", "width_in": 16, "linear_ft": 1000},
        {"material": "aluminum", "gauge": "0.040", "width_in": 12, "linear_ft": 500},
    ]
    out = estimate_coils_for_cutsheet(groups, waste_pct=10.0)
    assert len(out) == 2
    # 10% waste applied: 1000 -> 1100 ft of linear footage target
    assert abs(out[0]["linear_ft_needed"] - 1100.0) / 1100.0 < 0.01
    assert out[0]["od_in"] > 20.0  # buildup above default ID
    assert out[1]["material"] == "aluminum"
    assert out[1]["od_in"] > 20.0


def test_estimate_coils_unknown_material_returns_error_row():
    groups = [{"material": "unobtainium", "gauge": "24ga",
               "width_in": 16, "linear_ft": 500}]
    out = estimate_coils_for_cutsheet(groups)
    assert len(out) == 1
    assert "error" in out[0]
