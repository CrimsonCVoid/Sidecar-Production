"""Coil stock estimation for metal roofing cutsheet.

Metal roofing is ordered by coil, not by panel. Given panel fabrication
totals (linear feet by width/material/gauge), we estimate what coil OD
an installer needs to order to cover the job plus waste.

Geometry — annulus formula
--------------------------
A wound coil is an annulus. Total length of material wound into the coil:

    linear_ft = wraps * avg_circumference
              = (radial_buildup_in / thickness_in) * pi * (ID + buildup) / 12

which is algebraically identical to the "wraps × average circumference"
intuition used by CMG Metals and most supplier calculators.

Inverse: given required linear feet, solve for OD. Let b = buildup = (OD - ID)/2.
Then:

    linear_ft = (b / t) * pi * (ID + b) / 12
    => 12 * linear_ft * t = pi * b * (ID + b)
    => pi * b^2 + pi * ID * b - 12 * linear_ft * t = 0

Quadratic in b → b = (-pi*ID + sqrt((pi*ID)^2 + 4*pi*12*linear_ft*t)) / (2*pi).
OD = ID + 2*b.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Material / gauge spec table — CMG-calibrated
# ---------------------------------------------------------------------------
# Verified against CMG coil-calculator worked examples:
#   Aluminum 0.032 / ID 12 / W 9 / T 8  → 1309 LF, 982 SF, 437 lb
#   Steel    28ga  / ID 8  / W 10 / T 12 → 4217 LF, 3515 SF, 2197 lb
#   Copper   12oz  / ID 11 / W 12 / T 10 → 3394 LF, 3394 SF, 2546 lb
#
# Densities CMG uses (back-solved from the above):
#   Steel    : 0.2914 lb/in^3   (galvanized — base metal + zinc)
#   Aluminum : 0.0966 lb/in^3   (commercial sheet)
#   Copper   : sheet weight is the named oz/sqft directly (oz/sqft ÷ 16 = lb/sqft)
#
# Steel gauges follow the Manufacturer's Standard Gage (carbon steel).
# Aluminum "gauges" are decimal-inch thicknesses.
# Copper "gauges" are oz/sqft (industry standard for sheet copper).
_STEEL_DENSITY_LB_IN3 = 0.2914
_ALUMINUM_DENSITY_LB_IN3 = 0.0966

def _steel(thickness_in: float) -> dict[str, float]:
    return {
        "thickness_in": thickness_in,
        "lb_per_sqft": thickness_in * _STEEL_DENSITY_LB_IN3 * 144.0,
    }

def _aluminum(thickness_in: float) -> dict[str, float]:
    return {
        "thickness_in": thickness_in,
        "lb_per_sqft": thickness_in * _ALUMINUM_DENSITY_LB_IN3 * 144.0,
    }

def _copper(oz_per_sqft: float, thickness_in: float) -> dict[str, float]:
    # Copper sheet is sold by oz/sqft; weight comes straight from that spec.
    return {
        "thickness_in": thickness_in,
        "lb_per_sqft": oz_per_sqft / 16.0,
    }

COIL_SPECS: dict[str, dict[str, dict[str, float]]] = {
    "steel": {
        "20ga": _steel(0.0359),
        "22ga": _steel(0.0299),
        "24ga": _steel(0.0239),
        "26ga": _steel(0.0179),
        "28ga": _steel(0.0149),
        "30ga": _steel(0.0120),
    },
    "aluminum": {
        "0.024": _aluminum(0.024),
        "0.027": _aluminum(0.027),
        "0.032": _aluminum(0.032),
        "0.040": _aluminum(0.040),
        "0.050": _aluminum(0.050),
        "0.063": _aluminum(0.063),
    },
    "copper": {
        "12oz": _copper(12.0, 0.0162),
        "16oz": _copper(16.0, 0.0216),
        "20oz": _copper(20.0, 0.0270),
        "24oz": _copper(24.0, 0.0323),
    },
}

# Standard drum inner diameters for metal roofing coil stock (inches).
DEFAULT_ID_IN = 20.0
DEFAULT_WASTE_PCT = 10.0


@dataclass(frozen=True)
class CoilEstimate:
    """Single-coil estimate. Used both for forward (known OD) and inverse
    (required linear ft → solve OD) calculations; `from_geometry` flags which
    direction was run."""

    linear_ft: float
    sqft: float
    weight_lb: float
    wraps: float
    id_in: float
    od_in: float
    thickness_in: float
    width_in: float
    lb_per_sqft: float
    from_geometry: bool


def lookup_spec(material: str, gauge: str) -> tuple[float, float]:
    """Return (thickness_in, lb_per_sqft) from COIL_SPECS. Raises KeyError
    for unknown combos."""
    mat = COIL_SPECS[material.lower()]
    g = mat[gauge]
    return g["thickness_in"], g["lb_per_sqft"]


def coil_from_geometry(
    id_in: float,
    od_in: float,
    thickness_in: float,
    width_in: float,
    lb_per_sqft: float,
) -> CoilEstimate:
    """Forward: given inner + outer diameter, compute linear ft / sqft /
    weight of stock wound on the coil."""
    if od_in <= id_in:
        raise ValueError(f"od_in ({od_in}) must exceed id_in ({id_in})")
    if thickness_in <= 0 or width_in <= 0:
        raise ValueError("thickness_in and width_in must be positive")

    buildup_in = (od_in - id_in) / 2.0
    wraps = buildup_in / thickness_in
    avg_circ_ft = math.pi * (id_in + buildup_in) / 12.0
    linear_ft = wraps * avg_circ_ft
    sqft = linear_ft * (width_in / 12.0)
    weight_lb = sqft * lb_per_sqft

    return CoilEstimate(
        linear_ft=linear_ft,
        sqft=sqft,
        weight_lb=weight_lb,
        wraps=wraps,
        id_in=id_in,
        od_in=od_in,
        thickness_in=thickness_in,
        width_in=width_in,
        lb_per_sqft=lb_per_sqft,
        from_geometry=True,
    )


def coil_from_required_linear_ft(
    linear_ft_needed: float,
    id_in: float,
    thickness_in: float,
    width_in: float,
    lb_per_sqft: float,
) -> CoilEstimate:
    """Inverse: solve for the OD of a coil that holds at least
    `linear_ft_needed` of stock. Returns the exact OD; callers round up to
    the next supplier-available coil size."""
    if linear_ft_needed <= 0:
        raise ValueError("linear_ft_needed must be positive")
    if thickness_in <= 0 or width_in <= 0 or id_in <= 0:
        raise ValueError("id_in, thickness_in, width_in must be positive")

    # Solve pi*b^2 + pi*ID*b - 12*linear_ft*t = 0 for b (radial buildup).
    a_coef = math.pi
    b_coef = math.pi * id_in
    c_coef = -12.0 * linear_ft_needed * thickness_in
    discriminant = b_coef * b_coef - 4.0 * a_coef * c_coef
    buildup_in = (-b_coef + math.sqrt(discriminant)) / (2.0 * a_coef)
    od_in = id_in + 2.0 * buildup_in

    # Re-use forward calc so the returned fields stay internally consistent.
    est = coil_from_geometry(id_in, od_in, thickness_in, width_in, lb_per_sqft)
    return CoilEstimate(
        linear_ft=est.linear_ft,
        sqft=est.sqft,
        weight_lb=est.weight_lb,
        wraps=est.wraps,
        id_in=est.id_in,
        od_in=est.od_in,
        thickness_in=est.thickness_in,
        width_in=est.width_in,
        lb_per_sqft=est.lb_per_sqft,
        from_geometry=False,
    )


def estimate_coils_for_cutsheet(
    panel_groups: list[dict],
    waste_pct: float = DEFAULT_WASTE_PCT,
    id_in: float = DEFAULT_ID_IN,
) -> list[dict]:
    """Aggregate coil requirements for a list of panel groups.

    Each group is a dict with keys: width_in, material, gauge, linear_ft.
    Returns one coil estimate per (material, gauge, width) combination,
    with waste_pct applied to the required linear footage before the
    inverse calc.
    """
    factor = 1.0 + (waste_pct / 100.0)
    out = []
    for grp in panel_groups:
        width_in = float(grp["width_in"])
        material = str(grp["material"]).lower()
        gauge = str(grp["gauge"])
        linear_ft_raw = float(grp["linear_ft"])
        linear_ft_with_waste = linear_ft_raw * factor

        try:
            thickness_in, lb_per_sqft = lookup_spec(material, gauge)
        except KeyError:
            out.append({
                "material": material,
                "gauge": gauge,
                "width_in": width_in,
                "linear_ft_needed": round(linear_ft_with_waste, 1),
                "waste_pct": waste_pct,
                "error": f"no spec for {material} {gauge}",
            })
            continue

        est = coil_from_required_linear_ft(
            linear_ft_needed=linear_ft_with_waste,
            id_in=id_in,
            thickness_in=thickness_in,
            width_in=width_in,
            lb_per_sqft=lb_per_sqft,
        )
        out.append({
            "material": material,
            "gauge": gauge,
            "width_in": width_in,
            "linear_ft_raw": round(linear_ft_raw, 1),
            "linear_ft_needed": round(est.linear_ft, 1),
            "waste_pct": waste_pct,
            "od_in": round(est.od_in, 2),
            "id_in": round(est.id_in, 2),
            "sqft": round(est.sqft, 1),
            "weight_lb": round(est.weight_lb, 1),
            "wraps": round(est.wraps, 1),
            "thickness_in": est.thickness_in,
            "lb_per_sqft": est.lb_per_sqft,
        })
    return out
