"""
pvt_match.py - PVT matching: use laboratory (PVT report) data to improve the black-oil PVT.

The idea (the usual "PVT matching"):
  1. Compare the lab data with every correlation and see which one is closest.
  2. Take the best one and "match" it: nudge it a little so that it passes through the lab points.
  3. Use the matched PVT in the well model.

The lab data is a table with one row per pressure.  Any column may be empty:
    p   pressure, psia          rs  solution GOR, scf/STB
    bo  oil FVF, rb/STB         mu  oil viscosity, cP
(all at reservoir temperature).  The measured bubble point is given separately (pb_meas).

The matching changes the correlation with only four numbers (in the dictionary "match", see
pvt.oil_properties):
    rs_exp   shape of Rs below Pb:   Rs = rsb * (Rs_corr / rsb) ** rs_exp      (1 = unchanged)
    bo_a, bo_b   Bo = bo_a * Bo_corr + bo_b                                      (1 and 0 = unchanged)
    mu_mult  oil viscosity = mu_mult * mu_corr                                   (1 = unchanged)
The bubble point is matched by giving pb_meas (the correlation's pressure axis is rescaled so that
its bubble point sits at the measured value).

Only a few numbers are fitted on purpose: with few lab points a flexible fit would just follow the
noise.  Everything is plain least squares written out step by step.
"""
import math
import pvt

PROPERTIES = ("rs", "bo", "mu")
PROPERTY_NAMES = {"rs": "Solution GOR Rs (scf/STB)", "bo": "Oil FVF Bo (rb/STB)", "mu": "Oil viscosity (cP)"}
PVT_METHODS = ("glaso", "standing", "lasater", "petrosky")
VISC_METHODS = ("beal", "beggs", "petrosky")
NO_MATCH = {"rs_exp": 1.0, "bo_a": 1.0, "bo_b": 0.0, "mu_mult": 1.0}


def _check(condition, message):
    if not condition:
        raise ValueError(message)


def clean_lab_table(rows):
    """Turn the table typed on the page into a clean list of {"p", "rs", "bo", "mu"} dictionaries.

    rows : list of dictionaries (or anything with the same keys); blanks / None / NaN are allowed
           in rs, bo, mu.  Rows without a pressure, or with no property at all, are dropped.
    Returns the rows sorted by pressure.  Raises ValueError for impossible values."""
    def number_or_none(value):
        if value is None:
            return None
        try:
            x = float(value)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(x) else x

    table = []
    for row in rows:
        p = number_or_none(row.get("p"))
        if p is None:
            continue
        item = {"p": p, "rs": number_or_none(row.get("rs")),
                "bo": number_or_none(row.get("bo")), "mu": number_or_none(row.get("mu"))}
        if all(item[k] is None for k in PROPERTIES):
            continue
        _check(p > 0, "Lab pressures must be > 0.")
        _check(item["rs"] is None or item["rs"] >= 0, "Lab Rs cannot be negative.")
        _check(item["bo"] is None or item["bo"] > 0, "Lab Bo must be > 0.")
        _check(item["mu"] is None or item["mu"] > 0, "Lab viscosity must be > 0.")
        table.append(item)
    _check(len(table) >= 1, "Enter at least one lab row: a pressure and at least one of Rs, Bo or viscosity.")
    table.sort(key=lambda r: r["p"])
    return table


def evaluate(pressures, api, gas_sg, rsb, temp_f, pb_meas, pvt_method, visc_method, match=None):
    """Rs, Bo and viscosity from the correlations at each pressure.
    Returns {"rs": [...], "bo": [...], "mu": [...], "pb": bubble point used}."""
    out = {"rs": [], "bo": [], "mu": [], "pb": None}
    for p in pressures:
        o = pvt.oil_properties(p, temp_f, api, gas_sg, rsb, pb_meas or None, pvt_method, visc_method, match)
        out["rs"].append(o["rs"])
        out["bo"].append(o["bo"])
        out["mu"].append(o["mu_o"])
        out["pb"] = o["pb"]
    return out


def mean_abs_percent_error(lab_values, calc_values):
    """Average of |calc - lab| / lab * 100 over the points that have a lab value; None if there are none."""
    errors = [abs(c - v) / v * 100.0 for v, c in zip(lab_values, calc_values) if v is not None and v > 0]
    return sum(errors) / len(errors) if errors else None


def lab_errors(lab, calc):
    """Mean absolute % error of Rs, Bo and viscosity (None when the lab table has no such column)."""
    return {k: mean_abs_percent_error([r[k] for r in lab], calc[k]) for k in PROPERTIES}


def _score(errors, pb_error):
    """One number to rank the correlations: the average of the errors that exist (Pb included)."""
    values = [e for e in list(errors.values()) + [pb_error] if e is not None]
    return sum(values) / len(values) if values else None


def compare_methods(lab, api, gas_sg, rsb, temp_f, pb_meas=None):
    """Compare every Pb/Rs/Bo correlation with every viscosity correlation against the lab data.

    Returns a list of rows (best first):
        pvt_method, visc_method, pb_calc, pb_error (% , None without a measured Pb),
        rs_error, bo_error, mu_error (mean absolute %, None without that lab column), score.
    The bubble point is NOT forced to the measured value here, so that the table shows how well each
    correlation predicts it by itself; Rs, Bo and viscosity are compared at the lab pressures with the
    measured Pb applied (otherwise a wrong Pb would spoil every point below it)."""
    pressures = [r["p"] for r in lab]
    rows = []
    for method in PVT_METHODS:
        pb_calc = pvt.PB_FUNCS[method](rsb, gas_sg, api, temp_f)
        pb_error = abs(pb_calc - pb_meas) / pb_meas * 100.0 if pb_meas else None
        for visc in VISC_METHODS:
            calc = evaluate(pressures, api, gas_sg, rsb, temp_f, pb_meas, method, visc)
            errors = lab_errors(lab, calc)
            rows.append({"pvt_method": method, "visc_method": visc, "pb_calc": pb_calc,
                         "pb_error": pb_error, "rs_error": errors["rs"], "bo_error": errors["bo"],
                         "mu_error": errors["mu"], "score": _score(errors, pb_error)})
    rows.sort(key=lambda r: (r["score"] is None, r["score"]))
    return rows


def _least_squares_line(x, y):
    """Best straight line y = a*x + b through the points (ordinary least squares)."""
    n = len(x)
    mean_x, mean_y = sum(x) / n, sum(y) / n
    sxx = sum((xi - mean_x) ** 2 for xi in x)
    if sxx < 1e-12:
        return None
    a = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / sxx
    return a, mean_y - a * mean_x


def fit_match(lab, api, gas_sg, rsb, temp_f, pb_meas, pvt_method, visc_method):
    """Find the matching numbers for one correlation pair, one property at a time:

      1. Rs : rs_exp so that Rs = rsb*(Rs_corr/rsb)**rs_exp fits the lab Rs below the bubble point
              (least squares on logarithms; needs at least one lab Rs below Pb).
      2. Bo : straight line Bo = a*Bo_corr + b through the lab Bo (needs 2 points that differ; with
              only one lab point just the multiplier a is used so the curve passes through it).
      3. Mu : mu_mult = geometric average of lab / calculated viscosity.
    Each step uses the result of the step before, because Bo and viscosity depend on Rs.

    Returns {"match": {...four numbers...}, "before": errors dict, "after": errors dict,
             "pb": bubble point used, "notes": [plain sentences about what could not be fitted]}."""
    pressures = [r["p"] for r in lab]
    pb_used = pb_meas or pvt.PB_FUNCS[pvt_method](rsb, gas_sg, api, temp_f)
    match = dict(NO_MATCH)
    notes = []

    def calc(m):
        return evaluate(pressures, api, gas_sg, rsb, temp_f, pb_meas, pvt_method, visc_method, m)

    before = lab_errors(lab, calc(match))

    # 1. Rs
    base = calc(match)
    pairs = [(math.log(r["rs"] / rsb), math.log(c / rsb))
             for r, c in zip(lab, base["rs"])
             if r["rs"] is not None and r["rs"] > 0 and r["p"] < pb_used and 0 < c < 0.999 * rsb]
    if pairs and sum(y * y for _, y in pairs) > 1e-12:
        exponent = sum(x * y for x, y in pairs) / sum(y * y for _, y in pairs)
        match["rs_exp"] = min(max(exponent, 0.3), 3.0)
        if match["rs_exp"] != exponent:
            notes.append("The Rs match hit its limit (0.3 to 3): check the lab Rs and the solution GOR.")
    elif any(r["rs"] is not None for r in lab):
        notes.append("No lab Rs below the bubble point, so Rs was not matched.")

    # 2. Bo
    base = calc(match)
    pts = [(c, r["bo"]) for r, c in zip(lab, base["bo"]) if r["bo"] is not None]
    if len(pts) >= 2 and _least_squares_line([c for c, _ in pts], [v for _, v in pts]):
        match["bo_a"], match["bo_b"] = _least_squares_line([c for c, _ in pts], [v for _, v in pts])
    elif len(pts) >= 1:
        match["bo_a"] = sum(v for _, v in pts) / sum(c for c, _ in pts)
        notes.append("Fewer than two different Bo points: only a multiplier was fitted to Bo.")

    # 3. Viscosity
    base = calc(match)
    ratios = [math.log(r["mu"] / c) for r, c in zip(lab, base["mu"]) if r["mu"] is not None and c > 0]
    if ratios:
        match["mu_mult"] = math.exp(sum(ratios) / len(ratios))

    after = lab_errors(lab, calc(match))
    return {"match": match, "before": before, "after": after, "pb": pb_used, "notes": notes}


def curves(pressures, api, gas_sg, rsb, temp_f, pb_meas, pvt_method, visc_method, match=None):
    """Same as evaluate(); named for the plotting code."""
    return evaluate(pressures, api, gas_sg, rsb, temp_f, pb_meas, pvt_method, visc_method, match)
