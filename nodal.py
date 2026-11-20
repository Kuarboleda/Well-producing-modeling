"""
nodal.py - Nodal analysis for the Nodal Analysis app (Oilfield units).

Nodal analysis puts the two halves of the well together:
    IPR  (ipr.py) : what the reservoir delivers at a given flowing bottom-hole pressure
    VLP  (vlp.py) : what bottom-hole pressure the tubing needs at a given rate
The well flows where the two curves cross: that rate and pressure are the OPERATING POINT.

Units: pressure psia | oil + water rate STB/d (total liquid) | gas rate Mscf/d
       (all other units as in ipr.py, vlp.py and well.py)

Important: for an oil well the IPR rate is taken as the TOTAL LIQUID rate (oil + water),
the same rate that the VLP uses.

Pieces in this file
    find_operating_point() - the intersection of two curves (any IPR and any VLP)
    fluid_at_rate()        - the fluid a multilayer well produces at a rate (water cut and GOR of the commingled layers)
    solve_well()           - the whole chain: well + fluid + IPR -> operating point
    match_vlp_multiplier() - VLP matching: the multiplier that reproduces one measured test
    curves()               - IPR and VLP curves, ready to plot
    sensitivity()          - repeat solve_well() for several values of one input
    well_with_tubing_id()  - copy of a Well with a different tubing size (for sensitivities)

About several crossings
    A VLP curve is often J-shaped (it bends up again at low rates because of liquid
    slippage), so it can cross the IPR twice.  The lower-rate crossing is UNSTABLE
    (the well would load up and die or jump to the other point).  The higher-rate
    crossing is the STABLE one and is the one reported as the operating point.
    All crossings are still returned in result["crossings"].
"""
import copy
import dataclasses

import numpy as np

import ipr
import pvt
from well import Well
from vlp import pressure_traverse, vlp_curve


def _check(condition, message):
    """Stop with a clear error message if an input does not make sense."""
    if not condition:
        raise ValueError(message)


# =====================================================================
# The fluid that a multilayer well produces
# =====================================================================

def _has_layer_fluid(ipr_function, ipr_inputs):
    """True when the IPR is a multilayer one (oil or gas) AND its layers carry their own produced-fluid data
    (water cut and GOR for oil, CGR and WGR for gas)."""
    if ipr_function is ipr.oil_multilayer:
        return any("wc" in layer or "gor" in layer for layer in ipr_inputs.get("layers", []))
    if ipr_function is ipr.gas_multilayer:
        return any("cgr" in layer or "wgr" in layer for layer in ipr_inputs.get("layers", []))
    return False


def fluid_at_rate(fluid, ipr_function, p_res, ipr_inputs, q):
    """The fluid the well produces at the total rate q (STB/d liquid for oil, Mscf/d for gas).

    For an ordinary IPR this is just `fluid`.  For a multilayer IPR whose layers have their own fluid data,
    the layers produce different amounts at different flowing pressures, so the fluid of the well stream changes
    with the rate: the flowing pressure that the IPR needs for q is found, the layers' fluids are added up at that
    pressure (ipr.multilayer_mix for oil: water cut and GOR; ipr.gas_multilayer_mix for gas: CGR and WGR), and a
    copy of `fluid` with that mixture is returned.  The PVT (bubble point, gravities, ...) stays that of `fluid`;
    for a wet gas the well-stream gravity is recalculated from the mixed CGR when the dry-gas gravity is known."""
    if not _has_layer_fluid(ipr_function, ipr_inputs):
        return fluid
    layers = ipr_inputs["layers"]
    crossflow = ipr_inputs.get("crossflow", False)
    if ipr_function is ipr.gas_multilayer:
        pwf = ipr.gas_multilayer_pwf(q, p_res, layers, crossflow)
        mix = ipr.gas_multilayer_mix(p_res, pwf, layers, fluid.cgr, fluid.wgr, crossflow)
        changes = {"cgr": max(mix["cgr"], 0.0), "wgr": max(mix["wgr"], 0.0)}
        if fluid.gas_sg_dry > 0:
            changes["gas_sg"] = (pvt.wet_gas_gravity(fluid.gas_sg_dry, changes["cgr"], fluid.cond_api)
                                 if changes["cgr"] > 0 else fluid.gas_sg_dry)
        return dataclasses.replace(fluid, **changes)
    pb = ipr_inputs["pb"]
    pwf = ipr.multilayer_pwf(q, p_res, pb, layers, crossflow)
    mix = ipr.multilayer_mix(p_res, pwf, pb, layers, fluid.water_cut, fluid._gor(), crossflow)
    return dataclasses.replace(fluid, water_cut=min(max(mix["water_cut"], 0.0), 1.0), gor=mix["gor"])


# =====================================================================
# The intersection of an IPR and a VLP
# =====================================================================

def find_operating_point(q_ipr, pwf_vlp, n_grid=30, q_min_frac=0.01):
    """Find where an IPR and a VLP cross.

    q_ipr(pwf)  : function giving the reservoir rate for a flowing pressure (the IPR)
    pwf_vlp(q)  : function giving the pressure the tubing needs for a rate (the VLP)
    n_grid      : number of rates scanned between ~0 and the AOF to look for crossings
    q_min_frac  : first rate scanned, as a fraction of the AOF

    Idea: at a given rate q, the VLP needs pressure pwf_vlp(q); the reservoir could
    deliver q_ipr(pwf_vlp(q)) at that pressure.  The well is in balance where
        g(q) = q_ipr(pwf_vlp(q)) - q = 0.
    We scan g over a grid of rates, look for sign changes, and refine each one by
    bisection (repeatedly halving the interval that contains the crossing).

    Returns a dictionary:
        found     True / False
        q, pwf    the STABLE operating point (None if there is none)
        aof       the absolute open flow of the IPR (rate at Pwf = 0)
        crossings list of {"q", "pwf", "stable"} for every crossing, low rate first
        message   plain-language note when nothing is found
    """
    _check(n_grid >= 4, "n_grid must be at least 4.")
    _check(0.0 < q_min_frac < 0.5, "q_min_frac must be between 0 and 0.5.")
    aof = q_ipr(0.0)
    _check(aof > 0, "The IPR gives no flow even at Pwf = 0 - check the IPR inputs.")

    def g(q):
        return q_ipr(pwf_vlp(q)) - q

    # 1) scan a grid of rates and remember g at each one
    qs = [aof * (q_min_frac + (1.0 - q_min_frac) * i / n_grid) for i in range(n_grid + 1)]
    gs = [g(q) for q in qs]

    # 2) every place where g changes sign holds a crossing: refine it by bisection
    crossings = []
    for i in range(n_grid):
        if gs[i] == 0 or gs[i] * gs[i + 1] >= 0:
            continue
        lo, hi, g_lo = qs[i], qs[i + 1], gs[i]
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            g_mid = g(mid)
            if g_mid * g_lo > 0:
                lo, g_lo = mid, g_mid
            else:
                hi = mid
            if hi - lo < 1e-7 * aof:
                break
        q_cross = 0.5 * (lo + hi)
        crossings.append({"q": q_cross,
                          "pwf": pwf_vlp(q_cross),
                          "stable": gs[i] > 0})        # g goes from + to - : stable

    stable = [c for c in crossings if c["stable"]]
    if not stable:
        return {"found": False, "q": None, "pwf": None, "aof": aof, "crossings": crossings,
                "message": "The VLP is above the IPR at every rate: the well will not flow "
                           "naturally. Lower the wellhead pressure, enlarge the tubing, "
                           "or consider artificial lift."}
    best = stable[-1]                                  # highest-rate stable crossing
    return {"found": True, "q": best["q"], "pwf": best["pwf"], "aof": aof,
            "crossings": crossings, "message": ""}


# =====================================================================
# The whole chain: well + fluid + IPR  ->  operating point
# =====================================================================

def solve_well(well, fluid, ipr_function, p_res, ipr_inputs, p_wh,
               correlation="beggs_brill", max_step_ft=100.0, n_grid=30,
               gravity_mult=1.0, friction_mult=1.0):
    """Operating point of a well.

    well         : a well.Well
    fluid        : vlp.OilWaterFluid or vlp.GasFluid
    ipr_function : an IPR function from ipr.py, e.g. ipr.oil_pi or ipr.gas_jones
    p_res        : reservoir pressure (psia)
    ipr_inputs   : dictionary with the other inputs of that IPR function, e.g.
                   {"pb": 2000, "J": 3.0} for oil_pi
    p_wh         : wellhead flowing pressure (psia)
    correlation  : VLP correlation name (see vlp.py)
    gravity_mult, friction_mult : VLP matching multipliers (1.0 = correlation unchanged)

    Returns the dictionary of find_operating_point().
    """
    _check(p_res > 0 and p_wh > 0, "Reservoir and wellhead pressure must be > 0.")

    def q_ipr(pwf):
        return ipr_function(p_res=p_res, pwf=pwf, **ipr_inputs)

    def pwf_vlp(q):
        fluid_q = fluid_at_rate(fluid, ipr_function, p_res, ipr_inputs, q)      # multilayer: mix depends on the rate
        return pressure_traverse(well, fluid_q, q, p_wh, correlation, max_step_ft,
                                 gravity_mult, friction_mult)["pwf"]

    result = find_operating_point(q_ipr, pwf_vlp, n_grid=n_grid)
    if result["found"] and _has_layer_fluid(ipr_function, ipr_inputs):
        f = fluid_at_rate(fluid, ipr_function, p_res, ipr_inputs, result["q"])
        if ipr_function is ipr.gas_multilayer:
            result["mix"] = {"cgr": f.cgr, "wgr": f.wgr}                       # what the gas layers produce at the operating point
        else:
            result["mix"] = {"water_cut": f.water_cut, "gor": f.gor}           # what the oil layers produce at the operating point
    return result


def match_vlp_multiplier(well, fluid, rate, p_wh, pwf_measured, correlation="beggs_brill",
                         max_step_ft=100.0, fit="friction", low=0.5, high=2.0, message_offset=0.0, message_unit="psia"):
    """VLP matching from ONE measured test: find the multiplier that makes the tubing
    calculation reproduce a measured flowing bottom-hole pressure.

    rate, p_wh   : rate and wellhead flowing pressure (psia) of the test
    pwf_measured : flowing bottom-hole pressure (psia) measured in that test, at the
                   perforation (reference) depth of the well
    fit          : 'friction' (the usual choice) or 'gravity': which multiplier to find.
                   The other one stays at 1.0.
    low, high    : the range searched
    message_offset, message_unit : the offset is subtracted from every pressure WRITTEN IN AN ERROR MESSAGE
                   and the unit is the name printed after it, so that a page working in gauge pressure can
                   show psig (pass 14.7 and "psig"); neither changes anything in the calculation

    The calculated pressure rises steadily with either multiplier, so we halve the interval
    (bisection) until the calculated pressure equals the measured one.
    Returns the multiplier.  Raises ValueError if the measured pressure cannot be reached
    inside [low, high] (the message says what the calculation gives at both ends).
    """
    _check(fit in ("friction", "gravity"), "fit must be 'friction' or 'gravity'.")
    _check(0 < low < high, "The search range must have 0 < low < high.")
    _check(pwf_measured > p_wh, "The measured bottom-hole pressure must be above the wellhead pressure.")

    def pwf_for(m):
        g, f = (1.0, m) if fit == "friction" else (m, 1.0)
        return pressure_traverse(well, fluid, rate, p_wh, correlation, max_step_ft, g, f)["pwf"]

    p_low, p_high = pwf_for(low), pwf_for(high)
    if not p_low <= pwf_measured <= p_high:
        raise ValueError(
            f"The measured pressure ({pwf_measured - message_offset:,.0f} {message_unit}) cannot be matched by changing "
            f"the {fit} multiplier alone: the calculation gives {p_low - message_offset:,.0f} {message_unit} at "
            f"{low:g} and {p_high - message_offset:,.0f} {message_unit} at {high:g}. Check the test data, the "
            f"well description and the "
            f"fluid first; a different correlation may also fit better.")
    for _ in range(50):
        mid = 0.5 * (low + high)
        if pwf_for(mid) < pwf_measured:
            low = mid
        else:
            high = mid
        if high - low < 1e-5:
            break
    return 0.5 * (low + high)


def match_vlp_survey(well, fluid, rate, p_wh, depths_md, pressures, correlation="beggs_brill",
                     max_step_ft=100.0, fit="both", low=0.5, high=2.0):
    """VLP matching from a measured pressure SURVEY (a gauge at one or more depths in the tubing).

    well, fluid, rate, p_wh : the test conditions (rate and wellhead flowing pressure, psia)
    depths_md, pressures    : the measured points: depth along the well (MD, ft) and pressure (psia)
    fit                     : 'both' (the gravity AND the friction multiplier, needs 2 or more points at different
                              depths), 'friction' or 'gravity' (one multiplier; the other stays at 1.0)
    low, high               : the range searched for each multiplier

    The multipliers that make the calculated pressures closest to the measured ones (least squares) are found
    with Gauss-Newton steps: the pressure at each depth changes almost in proportion to each multiplier, so the
    iteration settles in a few steps.  A step that makes things worse is halved.
    Returns {"gravity", "friction", "rms_before", "rms_after", "at_limit"}: the rms values are the root-mean-square
    pressure errors (psi) before (both multipliers 1.0) and after matching; at_limit lists the multipliers that
    ended on the edge of the range (the match is then not reliable).
    Raises ValueError when the points cannot be used.
    """
    _check(fit in ("both", "friction", "gravity"), "fit must be 'both', 'friction' or 'gravity'.")
    _check(0 < low < high, "The search range must have 0 < low < high.")
    depths = np.asarray(depths_md, dtype=float)
    measured = np.asarray(pressures, dtype=float)
    _check(len(depths) == len(measured) and len(depths) >= 1, "Give at least one measured point.")
    _check(fit != "both" or len(set(np.round(depths, 3))) >= 2,
           "Matching both multipliers needs at least two points at different depths. With one point, match the "
           "friction or the gravity multiplier alone.")

    def errors(g, f):
        tr = pressure_traverse(well, fluid, rate, p_wh, correlation, max_step_ft, g, f)
        _check(depths.max() <= tr["md"][-1] + 1e-6, "A measured depth is below the bottom of the tubing.")
        return np.interp(depths, tr["md"], tr["p"]) - measured

    def rms(e):
        return float(np.sqrt(np.mean(e ** 2)))

    names = ["gravity", "friction"] if fit == "both" else [fit]
    x = np.ones(len(names))

    def full(values):
        d = {"gravity": 1.0, "friction": 1.0}
        d.update(dict(zip(names, values)))
        return d["gravity"], d["friction"]

    e = errors(*full(x))
    rms_before = rms(e)
    for _ in range(15):
        # the slope of every error with respect to every multiplier (finite differences)
        jac = np.empty((len(depths), len(x)))
        for k in range(len(x)):
            xk = x.copy()
            xk[k] += 0.02
            jac[:, k] = (errors(*full(xk)) - e) / 0.02
        a = jac.T @ jac + 1e-9 * np.eye(len(x)) * max(np.trace(jac.T @ jac), 1.0)
        step = -np.linalg.solve(a, jac.T @ e)
        scale, improved = 1.0, False
        for _ in range(6):                                   # halve the step until the match gets better
            trial = np.clip(x + scale * step, low, high)
            e_trial = errors(*full(trial))
            if rms(e_trial) < rms(e) - 1e-9:
                improved = True
                break
            scale *= 0.5
        if not improved:
            break
        change = float(np.max(np.abs(trial - x)))
        x, e = trial, e_trial
        if change < 1e-4:
            break
    g, f = full(x)
    return {"gravity": float(g), "friction": float(f), "rms_before": rms_before, "rms_after": rms(e),
            "at_limit": [n for n, v in zip(names, x) if v <= low + 1e-3 or v >= high - 1e-3]}


def curves(well, fluid, ipr_function, p_res, ipr_inputs, p_wh,
           correlation="beggs_brill", max_step_ft=100.0, n_points=25,
           gravity_mult=1.0, friction_mult=1.0):
    """IPR and VLP curves for plotting (rate on the x axis, Pwf on the y axis).

    Returns a dictionary of equal-length lists:
        ipr_q, ipr_pwf  : the IPR, from Pwf = Pr down to 0
        vlp_q, vlp_pwf  : the VLP, from 2 % of the AOF up to the AOF
    """
    _check(n_points >= 3, "n_points must be at least 3.")
    ipr_pwf = [p_res * (1.0 - i / (n_points - 1)) for i in range(n_points)]
    ipr_q = [ipr_function(p_res=p_res, pwf=pwf, **ipr_inputs) for pwf in ipr_pwf]
    aof = ipr_q[-1]
    _check(aof > 0, "The IPR gives no flow even at Pwf = 0 - check the IPR inputs.")
    vlp_q = [aof * (0.02 + 0.98 * i / (n_points - 1)) for i in range(n_points)]
    if _has_layer_fluid(ipr_function, ipr_inputs):
        vlp_pwf = [pressure_traverse(well, fluid_at_rate(fluid, ipr_function, p_res, ipr_inputs, q), q, p_wh,
                                     correlation, max_step_ft, gravity_mult, friction_mult)["pwf"] for q in vlp_q]
    else:
        vlp_pwf = vlp_curve(well, fluid, vlp_q, p_wh, correlation, max_step_ft, gravity_mult, friction_mult)
    return {"ipr_q": ipr_q, "ipr_pwf": ipr_pwf, "vlp_q": vlp_q, "vlp_pwf": vlp_pwf}


# =====================================================================
# Sensitivities
# =====================================================================

def well_with_tubing_id(well, id_in):
    """Copy of a Well whose tubing is ONE section of the given inner diameter (in)."""
    return Well(md=list(well.md), tvd=list(well.tvd),
                tubing=[(0.0, well.md[-1], float(id_in))],
                t_reservoir=well.t_reservoir, roughness_in=well.roughness_in,
                ambient_table=list(well.ambient_table))


def _set_path(kwargs, path, value):
    """Set one input inside the dictionary of solve_well inputs.

    path examples:  "p_wh"            -> kwargs["p_wh"]
                    "p_res"           -> kwargs["p_res"]
                    "ipr_inputs.J"    -> kwargs["ipr_inputs"]["J"]
                    "fluid.water_cut" -> kwargs["fluid"].water_cut
                    "well"            -> replace the whole Well (e.g. from well_with_tubing_id)
    A misspelt name raises an error (a silent typo would give a flat, useless sensitivity).
    """
    parts = path.split(".")
    _check(parts[0] in kwargs, f"Unknown input '{parts[0]}'. Choose from: {', '.join(kwargs)}")
    if len(parts) == 1:
        kwargs[parts[0]] = value
        return
    target = kwargs[parts[0]]
    for name in parts[1:-1]:
        target = target[name] if isinstance(target, dict) else getattr(target, name)
    last = parts[-1]
    if isinstance(target, dict):
        _check(last in target, f"Unknown input '{path}'.")
        target[last] = value
    else:
        _check(hasattr(target, last), f"Unknown input '{path}'.")
        setattr(target, last, value)


def sensitivity(base, name, values, with_curves=False, n_points=25):
    """Run solve_well() once for each value of ONE input and collect the operating points.

    base   : dictionary of the solve_well() inputs, for example
             {"well": w, "fluid": fl, "ipr_function": ipr.oil_pi, "p_res": 3000,
              "ipr_inputs": {"pb": 2000, "J": 3.0}, "p_wh": 200}
    name   : which input to vary (see _set_path), e.g. "p_wh", "ipr_inputs.J", "fluid.water_cut"
    values : list of values to try

    with_curves : also keep the IPR and VLP curves of every run (as made by curves()), so that the
                  chart can show one curve per value - for example one VLP for each wellhead pressure.

    The base inputs are never changed (every run works on a copy).
    Returns a list of {"value", "found", "q", "pwf"} (plus "curves" with with_curves), one per value.
    "curves" is None for a value whose IPR gives no flow at all.
    """
    results = []
    for value in values:
        kwargs = copy.deepcopy(base)
        _set_path(kwargs, name, value)
        r = solve_well(**kwargs)
        row = {"value": value, "found": r["found"], "q": r["q"], "pwf": r["pwf"]}
        if r.get("mix") and "water_cut" in r["mix"]:
            row["water_cut"] = r["mix"]["water_cut"]                  # multilayer: the water cut of this run
        if with_curves:
            try:
                row["curves"] = curves(kwargs["well"], kwargs["fluid"], kwargs["ipr_function"],
                                       kwargs["p_res"], kwargs["ipr_inputs"], kwargs["p_wh"],
                                       kwargs.get("correlation", "beggs_brill"),
                                       kwargs.get("max_step_ft", 100.0), n_points,
                                       kwargs.get("gravity_mult", 1.0), kwargs.get("friction_mult", 1.0))
            except ValueError:
                row["curves"] = None
        results.append(row)
    return results
