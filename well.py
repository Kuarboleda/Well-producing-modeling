"""
well.py - Well geometry and temperature for the Nodal Analysis app (Oilfield units).

Units: depth ft | pipe ID in | roughness in | temperature degF
       U (overall heat transfer coefficient) Btu/h/ft2/degF
       mass rate lb/h | heat capacity Btu/lb/degF | angle degrees from horizontal

What this file does
    1. Stores the well description in one "box" called Well.
    2. Cuts the well into short steps (build_steps).  The pressure calculation in
       vlp.py walks down these steps one at a time, from wellhead to perforations.
    3. Works out the fluid temperature along the well (fluid_temperatures).

Main public pieces
    Well                  - the well data (survey, tubing, temperatures)
    vertical_survey()     - quick survey for a vertical well
    parse_survey_text()   - turn pasted "MD TVD" text into two lists
    build_steps()         - cut the well into short steps
    fluid_temperatures()  - fluid temperature at every step boundary

Conventions
    * The survey starts at the wellhead (MD = 0, TVD = 0) and ends at the
      PERFORATIONS.  The last point is the reference depth for reservoir
      pressure and temperature (as in the spec).
    * "Angle" is measured from horizontal in the direction of flow (up the well):
      90 = vertical, 0 = horizontal.  A negative angle means the fluid flows
      downhill over that piece (e.g. a toe-up horizontal section).
"""
import math
from dataclasses import dataclass


# =====================================================================
# Small helpers
# =====================================================================

def _check(condition, message):
    """Stop with a clear error message if an input does not make sense."""
    if not condition:
        raise ValueError(message)


def _interp(x, xs, ys):
    """Straight-line interpolation of y at x, given lists xs (increasing) and ys.
    Outside the range the first / last y value is returned."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            fraction = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + fraction * (ys[i + 1] - ys[i])


# =====================================================================
# Survey helpers
# =====================================================================

def vertical_survey(depth):
    """Survey (md_list, tvd_list) of a straight vertical well of the given depth (ft)."""
    return [0.0, float(depth)], [0.0, float(depth)]


def parse_survey_text(text):
    """Turn pasted text (e.g. copied from Excel) into (md_list, tvd_list).

    Each line holds two numbers: measured depth and true vertical depth.  They can
    be separated by spaces, tabs, commas or semicolons.  Lines that are blank or
    are not numbers (like a header "MD  TVD") are skipped.
    """
    md_list = []
    tvd_list = []
    for line in text.splitlines():
        parts = line.replace(",", " ").replace(";", " ").split()   # split on any separator
        if len(parts) < 2:
            continue
        try:
            md = float(parts[0])
            tvd = float(parts[1])
        except ValueError:
            continue                                               # header line -> skip
        md_list.append(md)
        tvd_list.append(tvd)
    _check(len(md_list) >= 2, "Need at least two survey points (MD and TVD).")
    return md_list, tvd_list


# =====================================================================
# The Well "box"
# =====================================================================
# A dataclass is just a labelled box of values: Well(md=..., tvd=..., ...) creates
# one, and afterwards you read the values as well.md, well.tvd, and so on.

@dataclass
class Well:
    md: list                   # measured depths (ft): starts at 0, ends at the perforations
    tvd: list                  # true vertical depths (ft), same length as md
    tubing: list               # tubing sections [(md_from, md_to, id_in), ...] covering 0 -> perforations
    t_reservoir: float         # reservoir temperature at the perforations (degF)
    roughness_in: float = 0.0006    # pipe wall roughness (in)
    ambient_table: list = None      # [(md, ambient degF, U), ...]; None = default (see below)

    def __post_init__(self):
        # Python runs this automatically right after the Well is created.
        check_well(self)
        if self.ambient_table is None:
            # Default from the spec: 80 degF and U = 5 at surface; at the perforations
            # the surroundings are at reservoir temperature (U = 5 as well).
            self.ambient_table = [(0.0, 80.0, 5.0), (self.md[-1], self.t_reservoir, 5.0)]
        _check(len(self.ambient_table) >= 1, "Ambient temperature table is empty.")
        mds = [row[0] for row in self.ambient_table]
        _check(all(mds[i] < mds[i + 1] for i in range(len(mds) - 1)),
               "Ambient temperature table: MD must increase from row to row.")
        _check(all(row[2] >= 0 for row in self.ambient_table), "U cannot be negative.")


def simple_tubing(id_in, perf_md):
    """One tubing section from the wellhead down to the perforations."""
    return [(0.0, float(perf_md), float(id_in))]


def check_well(well):
    """Check the survey and tubing sections; raise a clear error if something is wrong."""
    md, tvd = well.md, well.tvd
    _check(len(md) == len(tvd) and len(md) >= 2, "MD and TVD lists need the same length (at least 2 points).")
    _check(md[0] == 0 and tvd[0] == 0, "The survey must start at MD = 0 and TVD = 0 (the wellhead).")
    for i in range(len(md) - 1):
        d_md = md[i + 1] - md[i]
        d_tvd = tvd[i + 1] - tvd[i]
        _check(d_md > 0, f"MD must increase (check survey row {i + 2}).")
        _check(abs(d_tvd) <= d_md + 1e-6,
               f"TVD changes by more than MD between survey rows {i + 1} and {i + 2} - impossible.")
    _check(well.roughness_in >= 0, "Roughness cannot be negative.")
    _check(well.t_reservoir > 0, "Reservoir temperature must be > 0.")

    perf_md = md[-1]
    _check(len(well.tubing) >= 1, "Define at least one tubing section.")
    expected_from = 0.0
    for (md_from, md_to, id_in) in well.tubing:
        _check(abs(md_from - expected_from) < 1e-6,
               "Tubing sections must run without gaps, starting at MD = 0.")
        _check(md_to > md_from and id_in > 0, "Each tubing section needs MD_to > MD_from and ID > 0.")
        expected_from = md_to
    _check(abs(expected_from - perf_md) < 1e-6,
           f"Tubing sections must end at the perforation depth (MD = {perf_md}).")


def tvd_at(well, md):
    """True vertical depth (ft) at a measured depth (ft)."""
    return _interp(md, well.md, well.tvd)


def ambient_at(well, md):
    """Ambient (surroundings) temperature in degF and U at a measured depth, from the table."""
    mds = [row[0] for row in well.ambient_table]
    temps = [row[1] for row in well.ambient_table]
    us = [row[2] for row in well.ambient_table]
    return _interp(md, mds, temps), _interp(md, mds, us)


def _tubing_id_at(well, md):
    """Tubing inner diameter (in) at a measured depth."""
    for (md_from, md_to, id_in) in well.tubing:
        if md_from <= md <= md_to:
            return id_in
    return well.tubing[-1][2]


# =====================================================================
# Cut the well into short steps
# =====================================================================

def build_steps(well, max_step_ft=100.0, extra_breaks=None):
    """Cut the well into short steps, listed from the WELLHEAD DOWN to the perforations.

    A step never crosses a survey point or a tubing-size change, and is never
    longer than max_step_ft.  Each step is a dictionary with:
        md_top, md_bot, tvd_top, tvd_bot (ft) | length (ft, along the pipe)
        angle_deg (from horizontal, flow direction = up the well) | id_in (inches)
    """
    _check(max_step_ft > 0, "max_step_ft must be > 0.")
    perf_md = well.md[-1]

    # 1) all the depths where something changes (survey points and tubing changes)
    breaks = list(well.md) + list(extra_breaks or [])        # extra_breaks: e.g. a gas lift injection depth
    for (md_from, md_to, id_in) in well.tubing:
        breaks.append(md_from)
        breaks.append(md_to)
    breaks = sorted(set(round(b, 6) for b in breaks if 0 <= b <= perf_md))

    # 2) cut each piece between two break depths into equal short steps
    steps = []
    for k in range(len(breaks) - 1):
        a, b = breaks[k], breaks[k + 1]
        n = max(1, math.ceil((b - a) / max_step_ft - 1e-9))
        for j in range(n):
            md_top = a + (b - a) * j / n
            md_bot = a + (b - a) * (j + 1) / n
            tvd_top = tvd_at(well, md_top)
            tvd_bot = tvd_at(well, md_bot)
            length = md_bot - md_top
            sine = max(-1.0, min(1.0, (tvd_bot - tvd_top) / length))
            steps.append({
                "md_top": md_top, "md_bot": md_bot,
                "tvd_top": tvd_top, "tvd_bot": tvd_bot,
                "length": length,
                "angle_deg": math.degrees(math.asin(sine)),
                "id_in": _tubing_id_at(well, 0.5 * (md_top + md_bot)),
            })
    return steps


# =====================================================================
# Temperature profile
# =====================================================================

def fluid_temperatures(well, steps, mass_rate_lb_hr, cp):
    """Fluid temperature (degF) at every step boundary, wellhead first.

    mass_rate_lb_hr and cp are one number each, or one number per step (a list) when the flow changes
    along the well, for example when gas lift gas joins it part of the way up.

    The list has len(steps) + 1 values: element 0 is the wellhead and the last
    element is the perforations (= reservoir temperature).

    Method: start at the perforations and move UP the well.  In each step the fluid
    loses heat to the surroundings, so it moves towards the ambient temperature:

        T_top = T_ambient + (T_bottom - T_ambient) * exp(-A * L)
        A     = pi * d * U / (w * cp)

    d = pipe diameter (ft), U = overall heat transfer coefficient (Btu/h/ft2/degF),
    w = total mass rate (lb/h), cp = heat capacity of the flowing mixture (Btu/lb/degF),
    L = step length (ft).  Ambient temperature and U are taken at the middle of the step.
    Friction heating and Joule-Thomson cooling are ignored.
    """
    n = len(steps)
    masses = list(mass_rate_lb_hr) if isinstance(mass_rate_lb_hr, (list, tuple)) else [mass_rate_lb_hr] * n
    cps = list(cp) if isinstance(cp, (list, tuple)) else [cp] * n
    _check(len(masses) == n and len(cps) == n, "mass rate and cp need one value per step.")
    _check(all(c > 0 for c in cps), "cp must be > 0.")
    temps = [0.0] * (n + 1)
    temps[n] = well.t_reservoir
    for i in range(n - 1, -1, -1):                     # bottom step first
        s = steps[i]
        t_amb, u = ambient_at(well, 0.5 * (s["md_top"] + s["md_bot"]))
        mass_rate_lb_hr, cp = masses[i], cps[i]
        if mass_rate_lb_hr <= 0:                       # no flow -> fluid sits at ambient
            temps[i] = t_amb
            continue
        d_ft = s["id_in"] / 12.0
        a = math.pi * d_ft * u / (mass_rate_lb_hr * cp)
        temps[i] = t_amb + (temps[i + 1] - t_amb) * math.exp(-a * s["length"])
    return temps
