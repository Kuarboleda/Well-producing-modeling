"""
gaslift_valves.py - gas lift valve mechanics, valve spacing/setting design and an unloading check.

Everything here follows two references (page numbers are in the comments):
    [T]  Takacs, "Gas Lift Manual" (PennWell 2005)   - valve mechanics ch. 3, design ch. 5
    [API] API RP 11V6, 2nd ed. 1999, "Design of Continuous Flow Gas Lift Installations Using
          Injection Pressure Operated Valves"

Pressures are psig unless the name says psia.  Depths are TVD (ft) inside the engine; the measured
depth of each valve is carried along for the report.  The engine has no Streamlit or plotting code.

What is in here
---------------
  1. Valve data     : a small catalogue of 1 in and 1.5 in OD valves (area ratio R = Av/Ab).
  2. Nitrogen dome  : dome pressure at valve temperature <-> at 60 degF (API Ct, Winkler-Eads, real-gas law).
  3. Valve mechanics: opening / closing pressures of unbalanced IPO and PPO valves, test rack opening
                      pressure (TRO).
  4. Gas passage    : Thornhill-Craver choke equation, port selection.
  5. Design         : valve spacing and settings for
                        - IPO valves, constant pressure drop per valve   [API] / [T] Ex 5-18
                        - IPO valves, constant surface opening pressure  [T] Ex 5-19 (design tubing pressure line)
                        - PPO valves, design tubing pressure line        [T] Ex 5-21
  6. Check          : can a string of valves that is already in the well kick off and unload?
  7. Frames         : stage-by-stage pictures of the unloading for the animation on the page.

Unbalanced valve, nitrogen dome only (no spring):
        Ab = bellows area, Av = port (seat) area, R = Av / Ab
    IPO (injection pressure acts on the bellows area less the port, production pressure on the port):
        pd = pio (1 - R) + pp R              opening injection pressure  pio = (pd - pp R) / (1 - R)
        closing injection pressure  pic = pd        test rack opening  TRO = pd60 / (1 - R)
    PPO (the pressures change places):
        pd = ppo (1 - R) + pi R              opening production pressure ppo = pd/(1-R) - R/(1-R) pi
        closing production pressure ppc = pd        TRO = pd60 / (1 - R)
"""
import math

import gaslift

ATM = 14.7                      # psi, gauge -> absolute
DISCHARGE_COEFF = 0.865         # Thornhill-Craver, gas lift ports [T] p.41
K_GAS = 1.256                   # ratio of specific heats used by [T] Example 2-17
EPS = 0.5                       # psi: tolerance when comparing pressures
TRANSFER_MARGIN = 5.0           # psi: closing pressures closer than this are called 'small margin'
CAPACITY_FRACTION = 0.80        # the operating valve should pass the gas at no more than ~80 % of its capacity
MIN_DIFFERENTIAL = gaslift.MIN_DIFFERENTIAL_PSI   # psi across the operating valve (100)

# ---------------------------------------------------------------------------------------------
# 1. Valve data  ([T] Appendix F, Table F-1: CAMCO J-40 type for 1 in OD, J-20 type for 1.5 in OD)
#    Av = seat area (sq in) from the table; R = Av/Ab rounded to 3 decimals as in the table.
# ---------------------------------------------------------------------------------------------
VALVE_CATALOGUE = {
    "1 in OD": {"ab": 0.31, "av": {0.125: 0.013, 0.1875: 0.029, 0.25: 0.051, 0.3125: 0.079, 0.375: 0.113}},
    "1.5 in OD": {"ab": 0.77, "av": {0.125: 0.013, 0.1875: 0.029, 0.25: 0.051, 0.3125: 0.079, 0.375: 0.113,
                                     0.4375: 0.154, 0.5: 0.200}},
}
# [API] Table 1: minimum safety factor (psi) added to the pressure drop per valve, by valve OD and port
SAFETY_FACTOR = {
    "1 in OD": {0.125: 5, 0.1875: 10, 0.25: 15, 0.3125: 20},
    "1.5 in OD": {0.1875: 5, 0.25: 10, 0.3125: 15, 0.375: 20, 0.4375: 25},
}
PORT_LABELS = {0.09375: "3/32", 0.125: "1/8", 0.15625: "5/32", 0.1875: "3/16", 0.25: "1/4", 0.3125: "5/16",
               0.375: "3/8", 0.4375: "7/16", 0.5: "1/2"}


def port_label(d):
    return PORT_LABELS.get(d, f"{d:.4f}") + " in"


def valve_ports(od):
    """Port diameters (in) available for a valve OD, smallest first."""
    return sorted(VALVE_CATALOGUE[od]["av"])


def valve_R(od, port):
    """R = Av/Ab of the valve."""
    cat = VALVE_CATALOGUE[od]
    if port not in cat["av"]:
        raise ValueError(f"A {od} valve has no {port_label(port)} port in the table.")
    return round(cat["av"][port] / cat["ab"], 3)


def ppef(r):
    """Production pressure effect factor R/(1-R)."""
    return r / (1.0 - r)


def safety_factor(od, port):
    table = SAFETY_FACTOR.get(od, {})
    if port in table:
        return float(table[port])
    if not table:
        return 10.0
    nearest = min(table, key=lambda p: abs(p - port))
    return float(table[nearest])


# ---------------------------------------------------------------------------------------------
# 2. Nitrogen dome pressure  ([T] p.174-175)
# ---------------------------------------------------------------------------------------------
def n2_z(p_psia, t_f):
    """Deviation factor of nitrogen (Sage and Lacy fit, [T] Eq 3.3-3.5; 0-3000 psia, 60-400 degF)."""
    b = (1.207e-7 * t_f ** 3 - 1.302e-4 * t_f ** 2 + 5.122e-2 * t_f - 4.781) * 1e-5
    c = (-2.461e-8 * t_f ** 3 + 2.640e-5 * t_f ** 2 - 1.058e-2 * t_f + 1.880) * 1e-8
    return 1.0 + b * p_psia + c * p_psia ** 2


def ct_api(t_f):
    """Temperature factor of API RP 11V6 Table A-1:  dome pressure at 60 degF = pd * Ct."""
    return 1.0 / (1.0 + 0.00215 * (t_f - 60.0))


def _winkler_down(p60_psia, t_f):
    """[T] Eq 3.6-3.8 (Winkler and Eads): dome pressure (psia) at valve temperature from the one at 60 degF."""
    if p60_psia < 1238.0:
        m = -0.00226 + 0.001934 * p60_psia + 3.054e-7 * p60_psia ** 2
    else:
        m = -0.267 + 0.002298 * p60_psia + 1.84e-7 * p60_psia ** 2
    return p60_psia + m * (t_f - 60.0)


def _gas_law_down(p60_psia, t_f):
    """[T] Eq 3.2: real-gas law with the nitrogen Z factor, repeated until it stops changing."""
    z60 = n2_z(p60_psia, 60.0)
    pd = p60_psia
    for _ in range(50):
        new = n2_z(pd, t_f) / z60 * (t_f + 460.0) / 520.0 * p60_psia
        if abs(new - pd) < 1e-7:
            break
        pd = new
    return pd


DOME_METHODS = {"api": "API RP 11V6 temperature factor Ct",
                "winkler": "Winkler-Eads (Takacs Eq 3.6-3.8)",
                "gas_law": "Real-gas law with N2 Z factor (Takacs Eq 3.2)"}


def dome_pressure_downhole(p60, t_f, method="api"):
    """Dome pressure (psig) at valve temperature t_f from the charge pressure p60 (psig) at 60 degF."""
    if method == "api":
        return p60 / ct_api(t_f)
    if method == "winkler":
        return _winkler_down(p60 + ATM, t_f) - ATM
    if method == "gas_law":
        return _gas_law_down(p60 + ATM, t_f) - ATM
    raise ValueError(f"Unknown dome pressure method: {method}")


def dome_pressure_60(pd, t_f, method="api"):
    """Charge pressure at 60 degF (psig) that gives the dome pressure pd (psig) at temperature t_f."""
    if method == "api":
        return pd * ct_api(t_f)
    lo, hi = 0.0, max(pd, 10.0) + 1.0                           # the 60 degF pressure is always lower
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if dome_pressure_downhole(mid, t_f, method) < pd:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------------------------
# 3. Valve mechanics (nitrogen charge, no spring)
# ---------------------------------------------------------------------------------------------
def ipo_dome(r, p_inj, p_tub):
    """Dome pressure at valve temperature that makes the valve open at injection pressure p_inj when the
    tubing pressure is p_tub."""
    return p_inj * (1.0 - r) + p_tub * r


def ipo_opening(pd, r, p_tub):
    """Injection pressure (at valve depth) that opens an IPO valve for the given tubing pressure."""
    return (pd - p_tub * r) / (1.0 - r)


def ppo_dome(r, p_tub_open, p_inj):
    return p_tub_open * (1.0 - r) + p_inj * r


def ppo_opening(pd, r, p_inj):
    """Tubing (production) pressure that opens a PPO valve for the given injection pressure."""
    return pd / (1.0 - r) - ppef(r) * p_inj


def tro(pd60, r):
    """Test rack opening pressure (psig) of a nitrogen charged valve with no spring, set at 60 degF."""
    return pd60 / (1.0 - r)


def linear_temperature(tvd, tvd_total, t_surface, t_bottom):
    """Straight line from the flowing wellhead temperature to the temperature at tvd_total."""
    return t_surface + (t_bottom - t_surface) * tvd / tvd_total


# ---------------------------------------------------------------------------------------------
# 4. Gas passage ([T] Eq 2.65, Thornhill-Craver)
# ---------------------------------------------------------------------------------------------
def gas_passage(d_in, p1_psig, p2_psig, gas_sg, t_f, cd=DISCHARGE_COEFF, k=K_GAS):
    """Gas rate (Mscf/d) through a port of diameter d_in with upstream pressure p1 and downstream p2.
    Critical flow is handled by freezing the pressure ratio at its critical value."""
    p1, p2 = p1_psig + ATM, p2_psig + ATM
    if p1 <= p2 or d_in <= 0:
        return 0.0
    ratio = p2 / p1
    critical = (2.0 / (k + 1.0)) ** (k / (k - 1.0))
    ratio = max(ratio, critical)
    t_r = t_f + 459.67
    term = ratio ** (2.0 / k) - ratio ** ((k + 1.0) / k)
    return (693.0 * cd * d_in ** 2 * p1 * math.sqrt(1.0 / (gas_sg * t_r))
            * math.sqrt(2.0 * k / (k - 1.0)) * math.sqrt(max(term, 0.0)))


def choose_port(od, q_mscfd, p1_psig, p2_psig, gas_sg, t_f, fraction=CAPACITY_FRACTION):
    """Smallest catalogue port of a valve OD that passes q_mscfd at no more than `fraction` of its capacity.
    Returns (port, capacity_mscfd); the largest port is returned (with its capacity) if none is big enough."""
    best = None
    for d in valve_ports(od):
        cap = gas_passage(d, p1_psig, p2_psig, gas_sg, t_f)
        best = (d, cap)
        if q_mscfd <= fraction * cap:
            return best
    return best


# ---------------------------------------------------------------------------------------------
# helpers for pressure lines
# ---------------------------------------------------------------------------------------------
def interp(x, xs, ys):
    """Straight-line interpolation of ys against xs (increasing); end values are held constant."""
    if x <= xs[0]:
        return ys[0]
    for k in range(1, len(xs)):
        if x <= xs[k]:
            f = (x - xs[k - 1]) / (xs[k] - xs[k - 1])
            return ys[k - 1] + f * (ys[k] - ys[k - 1])
    return ys[-1]


def constant_gradient_gas(gradient):
    """gas_p(tvd, p_surface) for a constant annulus gas gradient (psi/ft); used by the book examples."""
    return lambda tvd, p_surface: p_surface + gradient * tvd


def column_gas(gas_sg, t_surface_f, t_flow):
    """gas_p(tvd, p_surface) from the static gas column of gaslift.casing_pressure_at_depth.
    t_flow(tvd) is the flowing temperature; the column temperature is the average of the surface and that."""
    def gas_p(tvd, p_surface):
        if tvd <= 0:
            return p_surface
        t_avg = 0.5 * (t_surface_f + t_flow(tvd))
        return gaslift.casing_pressure_at_depth(p_surface + ATM, tvd, t_avg, gas_sg) - ATM
    return gas_p


def _bisect(f, lo, hi, tol=1e-4, n=100):
    """Root of a decreasing function f on [lo, hi] (f(lo) >= 0 >= f(hi))."""
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def surface_pressure_for(gas_p, tvd, p_at_depth, p_max=20000.0):
    """Surface pressure (psig) that gives p_at_depth at tvd."""
    lo, hi = 0.0, p_max
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if gas_p(tvd, mid) < p_at_depth:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-4:
            break
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------------------------
# 5. Design
# ---------------------------------------------------------------------------------------------
DESIGN_METHODS = {
    "ipo_api": "IPO valves - constant pressure drop per valve (API RP 11V6)",
    "ipo_optiflow": "IPO valves - constant surface opening pressure (design tubing pressure line)",
    "ppo": "PPO valves - design tubing pressure line",
}


def design_tubing_pressure(p_wh, p_inj, p_inj_point, tvd_inj):
    """Design tubing pressure line [T] 5.6.4.1.3: from point A at surface (WHP + 200 or WHP + 0.2 pinj,
    whichever is greater) straight to the flowing tubing pressure at the injection point (point B)."""
    a = max(p_wh + 200.0, p_wh + 0.2 * p_inj)
    return (lambda tvd: a + (p_inj_point - a) * tvd / tvd_inj), a


def design_string(method, *, tvd_of, md_of, p_ko, p_op, p_wh, g_unload, gas_p, p_flow, t_flow,
                  tvd_inj, tvd_max, od="1 in OD", port=0.1875, min_spacing_md=150.0, dp_valve=20.0,
                  drop_mode="fixed", drop_fixed=25.0, sfl_tvd=0.0, dome_method="api", max_valves=30,
                  gas_rate_mscfd=None, gas_sg=0.65, operating="orifice", p_tub_first=None):
    """Space and set the unloading valves of a new string.

    method   : 'ipo_api', 'ipo_optiflow' or 'ppo' (see DESIGN_METHODS)
    tvd_of, md_of : depth conversions (functions); gas_p(tvd, p_surface), p_flow(tvd), t_flow(tvd) as above
    p_ko     : surface kick-off pressure (psig), used for the top valve
    p_op     : surface operating injection pressure (psig)
    p_wh     : wellhead pressure while unloading (psig);  g_unload : load fluid gradient (psi/ft)
    p_flow   : flowing tubing pressure (psig) against TVD at the design rate and GLR, lifting from tvd_inj
    tvd_inj  : wanted depth of the point of injection;  tvd_max : deepest depth a valve may go
    drop_mode: 'fixed' (drop_fixed psi per valve), 'min' (PPEF*100 + safety factor, API 4.9.5a) or
               'max' (20 + PPEF*200, API 4.9.5b); only for ipo_api
    sfl_tvd  : static fluid level in the annulus; the top valve is not placed above it
    operating: 'orifice' or 'valve' for the bottom (operating) valve
    p_tub_first : function tvd -> tubing pressure (psig) at the top valve when the annulus liquid reaches it
               (depends on the static liquid level, see first_valve_tubing_pressure); None = tubing full of load fluid

    Returns a dictionary: valves (list, top first), notes (list of strings), reached (True when the string
    reaches tvd_inj), a (point A of the design tubing pressure line or None).
    """
    if method not in DESIGN_METHODS:
        raise ValueError(f"Unknown design method: {method}")
    if g_unload <= 0:
        raise ValueError("The unloading gradient must be > 0.")
    r = valve_R(od, port)
    notes = []
    ptd_line, point_a = (None, None)
    if method in ("ipo_optiflow", "ppo"):
        ptd_line, point_a = design_tubing_pressure(p_wh, p_op, p_flow(tvd_inj), tvd_inj)
    min_spacing_tvd = min_spacing_md * 0.9                      # a rough TVD equivalent; checked again in MD below

    def drop_for(rr):
        if drop_mode == "min":
            return ppef(rr) * 100.0 + safety_factor(od, port)
        if drop_mode == "max":
            return 20.0 + ppef(rr) * 200.0
        return drop_fixed

    pd_drop = drop_for(r) if method == "ipo_api" else 0.0
    depths, surf_open, tub_here = [], [], []                    # TVD, surface opening pressure, tubing pressure

    # ---- top valve: where the unloading line from the WHP meets the casing pressure at kick-off
    margin1 = dp_valve
    f1 = lambda d: gas_p(d, p_ko) - (p_wh + g_unload * d) - margin1
    if f1(0.0) <= 0:
        raise ValueError("The kick-off pressure is not even enough to open a valve just below the surface. "
                         "Raise the kick-off pressure or lower the wellhead pressure.")
    d1 = tvd_max if f1(tvd_max) > 0 else _bisect(f1, 0.0, tvd_max)
    if sfl_tvd and d1 < sfl_tvd:
        notes.append(f"The static fluid level ({md_of(sfl_tvd):,.0f} ft MD) is below the calculated top valve depth, so "
                     "the top valve is placed at the fluid level.")
        d1 = sfl_tvd
    if sfl_tvd and p_tub_first is not None and method in ("ipo_optiflow", "ppo"):
        # a PPO valve opens on tubing pressure: it must be deep enough for the load fluid to reach the design pressure
        while d1 < tvd_max and p_tub_first(d1) < ptd_line(d1) + dp_valve:
            d1 = min(d1 + 25.0, tvd_max)
        if p_tub_first(d1) < ptd_line(d1) + dp_valve:
            notes.append("With this liquid level the load fluid never gives the tubing pressure the top valve needs "
                         "to open: lower the liquid level or raise the design wellhead pressure.")
    extra = 0.0
    if method == "ipo_api" and p_tub_first is not None:
        # the top valve is set for the (lower) tubing pressure it meets when uncovered, which lowers its closing
        # pressure by R times the difference: the surface pressure of the valves below is lowered by the same
        # amount so that the closing pressures still fall down the string
        extra = max(0.0, r * (p_flow(d1) - p_tub_first(d1)))
    depths.append(d1)
    surf_open.append(p_ko)

    # ---- the rest, one valve at a time, until the injection point is reached (or the pressure runs out)
    reached, stalled = False, False
    if d1 >= tvd_inj - 1e-6:
        depths[0], reached = tvd_inj, True                    # the top valve is already at the injection point
    elif tvd_inj - d1 < min_spacing_tvd:
        reached = True                                         # close enough: the top valve is the operating valve
    while not reached and len(depths) < max_valves:
        n = len(depths) + 1
        prev = depths[-1]
        if method == "ipo_api":
            p_s = p_ko - (n - 1) * pd_drop - extra
            line = lambda d, prev=prev: (p_flow(prev) + g_unload * (d - prev)) + dp_valve
        else:
            p_s = p_op
            line = lambda d, prev=prev: ptd_line(prev) + g_unload * (d - prev) + dp_valve
        f = lambda d, p_s=p_s, line=line: gas_p(d, p_s) - line(d)
        if f(prev) <= 0:
            stalled = True
            break
        nxt = tvd_max if f(tvd_max) > 0 else _bisect(f, prev, tvd_max)
        if nxt >= tvd_inj - 1e-6:                              # the injection point can be reached from this valve
            depths.append(tvd_inj)
            surf_open.append(p_s)
            reached = True
            break
        if nxt - prev < min_spacing_tvd or md_of(nxt) - md_of(prev) < min_spacing_md:
            stalled = True
            break
        depths.append(nxt)
        surf_open.append(p_s)
        if tvd_inj - nxt < min_spacing_tvd:                    # close enough to the wanted depth: it operates
            reached = True
    if reached and depths[-1] < tvd_inj - 1.0:
        notes.append(f"The operating valve is at {md_of(depths[-1]):,.0f} ft MD, a little above the wanted "
                     f"{md_of(tvd_inj):,.0f} ft MD, so that the valves keep their minimum spacing.")
    if not reached:
        notes.append(f"The valves cannot be spaced deeper than about {md_of(depths[-1]):,.0f} ft MD with this "
                     f"injection pressure; the injection point wanted ({md_of(tvd_inj):,.0f} ft MD) is out of reach. "
                     "The last valve becomes the operating valve.")

    # ---- settings of every valve
    valves = []
    for i, d in enumerate(depths):
        n = i + 1
        t_v = t_flow(d)
        last_valve = (i == len(depths) - 1)
        is_operating = last_valve
        p_s = surf_open[i]
        p_i = gas_p(d, p_s)                                       # injection pressure at depth when it opens
        if method == "ipo_optiflow" or method == "ppo":
            p_t = ptd_line(d)
        else:
            p_t = p_flow(d)
            if i == 0 and p_tub_first is not None:             # the top valve has to open against the load fluid
                p_t = min(p_t, p_tub_first(d))
        v = {"n": n, "tvd": d, "md": md_of(d), "T": t_v, "od": od, "port": port, "R": r,
             "p_surface_open": p_s, "p_inj": p_i, "p_tub": p_t, "operating": is_operating}
        if is_operating and operating == "orifice":
            v.update({"kind": "orifice", "R": 0.0})
        else:
            kind = "PPO" if method == "ppo" else "IPO"
            pd = ppo_dome(r, p_t, p_i) if kind == "PPO" else ipo_dome(r, p_i, p_t)
            pd60 = dome_pressure_60(pd, t_v, dome_method)
            v.update({"kind": kind, "pd": pd, "pd60": pd60, "tro": tro(pd60, r)})
            if kind == "PPO":
                v["p_open_tub"] = p_t
        valves.append(v)

    # ---- gas passage of the operating valve
    if gas_rate_mscfd:
        v = valves[-1]
        p_up = v["p_inj"] if method != "ppo" else gas_p(v["tvd"], p_op)
        p_dn = p_flow(v["tvd"])
        if v["kind"] == "orifice":
            port_op, cap = choose_port("1 in OD", gas_rate_mscfd, p_up, p_dn, gas_sg, v["T"])
            v["port"], v["capacity"] = port_op, cap
        else:
            v["capacity"] = gas_passage(v["port"], p_up, p_dn, gas_sg, v["T"])
        v["gas_rate_needed"] = gas_rate_mscfd
        if gas_rate_mscfd > CAPACITY_FRACTION * v["capacity"]:
            notes.append(f"The {port_label(v['port'])} port at the operating depth passes about {v['capacity']:,.0f} "
                         f"Mscf/d at the design pressures, less than the {gas_rate_mscfd:,.0f} Mscf/d wanted "
                         f"(the port is kept to {CAPACITY_FRACTION * 100:.0f} % of its capacity). Use a larger port or "
                         "a higher injection pressure.")
    return {"valves": valves, "notes": notes, "reached": reached, "a": point_a, "method": method,
            "pressure_drop": pd_drop}


# ---------------------------------------------------------------------------------------------
# 6. Check of a string that is already in the well
# ---------------------------------------------------------------------------------------------
def make_valve(n, md, tvd, kind, t_f, od="1 in OD", port=0.1875, tro_psig=None, dome_method="api"):
    """A valve of an existing string.  kind: 'IPO', 'PPO', 'orifice' or 'dummy'.
    tro_psig = test rack opening pressure at 60 degF (IPO or PPO); port = orifice diameter for an orifice."""
    v = {"n": n, "md": md, "tvd": tvd, "T": t_f, "kind": kind, "od": od, "port": port}
    if kind in ("IPO", "PPO"):
        r = valve_R(od, port)
        if tro_psig is None or tro_psig <= 0:
            raise ValueError(f"Valve {n}: the test rack opening pressure is missing.")
        pd60 = tro_psig * (1.0 - r)
        v.update({"R": r, "tro": tro_psig, "pd60": pd60, "pd": dome_pressure_downhole(pd60, t_f, dome_method)})
    elif kind == "orifice":
        v["R"] = 0.0
    return v


def _p_tub_unloading(prev, valve, p_wh, g_unload, p_flow, first_tub_pressure=None):
    """Tubing pressure at `valve` at the moment the annulus liquid level reaches it."""
    if prev is None:
        return first_tub_pressure if first_tub_pressure is not None else p_wh + g_unload * valve["tvd"]
    return p_flow(prev["tvd"]) + g_unload * (valve["tvd"] - prev["tvd"])


def first_valve_tubing_pressure(tvd, p_wh, g_unload, sfl_tvd, annulus_cap, tubing_cap):
    """Tubing pressure at the top valve when the annulus liquid has been pushed down to it.
    The static level is the same in tubing and annulus; the annulus liquid between that level and the
    valve goes into the tubing and raises the liquid level there (up to the surface at most)."""
    if sfl_tvd >= tvd:
        return p_wh                                             # valve above the liquid: gas only
    height = (tvd - sfl_tvd) * (1.0 + annulus_cap / tubing_cap)
    return p_wh + g_unload * min(tvd, height)


def _opens(v, p_inj, p_tub):
    kind = v["kind"]
    if kind == "orifice":
        return p_inj > p_tub
    if kind == "IPO":
        return p_inj >= ipo_opening(v["pd"], v["R"], p_tub) - EPS
    if kind == "PPO":
        return p_tub >= ppo_opening(v["pd"], v["R"], p_inj) - EPS and p_inj > p_tub
    return False


def check_string(valves, *, p_ko, p_op, p_wh, g_unload, gas_p, p_flow, sfl_tvd=0.0, annulus_cap=0.0309,
                 tubing_cap=0.00579, dp_valve=20.0, gas_rate_mscfd=None, gas_sg=0.65, target_tvd=None,
                 surface_drop=0.0):
    """Can this string of valves kick off the well, unload it and then lift in a stable way?

    valves     : list from make_valve(), top first (dummies are skipped)
    p_ko       : highest surface injection pressure available for kick-off (psig)
    p_op       : surface injection pressure during normal operation (psig)
    sfl_tvd    : static annulus liquid level (TVD ft, 0 = full)
    annulus_cap, tubing_cap : bbl/ft of the annulus and of the tubing (used for the first valve)
    dp_valve   : pressure difference (psi) wanted between the casing and the tubing for gas to enter
    target_tvd : depth the well should be lifted from (None = no wish)
    surface_drop : psi the operator lowers the surface pressure per valve transferred (0 = none)

    The surface pressure available when a valve has to be opened is the kick-off pressure less
    surface_drop for each valve already passed, and never more than the pressure that would reopen
    an upper valve that has already closed.

    Returns a dictionary with a list of stages (one per active valve, as far as the unloading gets),
    flags kickoff_ok, reached (index into valves of the deepest valve that takes gas), operating
    (details at the end), issues and a verdict.
    """
    active = [v for v in valves if v["kind"] != "dummy"]
    active.sort(key=lambda v: v["tvd"])
    issues = []
    stages = []
    closed = []                                                  # valves that have taken gas and closed again
    above = [v for v in active if v["tvd"] < sfl_tvd]
    if above:
        issues.append(f"{len(above)} valve(s) at or above the static fluid level ({above[0]['md']:,.0f} ft MD …) "
                      "are in gas. They will pass the kick-off gas straight into the tubing and may stop "
                      "pressure building up: replace them by dummies.")
    work = [v for v in active if v["tvd"] >= sfl_tvd]
    kickoff_ok = False
    current = None
    p_avail = p_ko
    for i, v in enumerate(work):
        pu = _p_tub_unloading(current, v, p_wh, g_unload, p_flow,
                              first_tub_pressure=first_valve_tubing_pressure(v["tvd"], p_wh, g_unload, sfl_tvd,
                                                                             annulus_cap, tubing_cap)
                              if current is None else None)
        if current is not None and surface_drop:
            p_avail = min(p_avail, p_ko - len(closed) * surface_drop) if closed else p_avail
        p_try = p_avail
        pi = gas_p(v["tvd"], p_try)
        st = {"n": v["n"], "md": v["md"], "tvd": v["tvd"], "kind": v["kind"], "p_tub": pu, "p_surface": p_try,
              "p_inj": pi, "opens": _opens(v, pi, pu) and pi - pu >= dp_valve - EPS}
        # surface pressure needed to open it
        if v["kind"] == "IPO":
            st["p_surface_needed"] = surface_pressure_for(gas_p, v["tvd"], ipo_opening(v["pd"], v["R"], pu))
            st["p_surface_needed"] = max(st["p_surface_needed"],
                                         surface_pressure_for(gas_p, v["tvd"], pu + dp_valve))
        elif v["kind"] == "PPO":
            st["p_tub_needed"] = ppo_opening(v["pd"], v["R"], pi)
        else:
            st["p_surface_needed"] = surface_pressure_for(gas_p, v["tvd"], pu + dp_valve)
        if not st["opens"]:
            st["note"] = _why_not_open(v, st, pi, pu, dp_valve)
            stages.append(st)
            if current is None:
                issues.append(f"Kick-off is not possible: {st['note']}")
            else:
                issues.append(f"The unloading stops at valve {current['n']} ({current['md']:,.0f} ft MD): {st['note']}")
            break
        if current is None:
            kickoff_ok = True
        # --- the valve above must close now (IPO: casing pressure at its depth <= its dome pressure,
        #     PPO: tubing pressure at its depth <= its dome pressure) without closing this valve
        if current is not None:
            st["closes_upper"], st["close_note"] = _transfer(current, v, gas_p, p_flow, p_try, p_op)
            if current["kind"] == "IPO":
                st["p_close_upper"] = surface_pressure_for(gas_p, current["tvd"], current["pd"])
            if not st["closes_upper"]:
                issues.append(f"Valve {current['n']} ({current['md']:,.0f} ft MD) may not close when valve {v['n']} "
                              f"({v['md']:,.0f} ft MD) starts to inject: {st['close_note']}")
        stages.append(st)
        if current is not None:
            closed.append(current)
        current = v
        # the pressure that may be used for the next valve: not above the reopening pressure of a closed valve
        p_avail = p_ko
        for j in closed:
            if j["kind"] == "IPO":
                p_re = surface_pressure_for(gas_p, j["tvd"], ipo_opening(j["pd"], j["R"], p_flow(j["tvd"])))
                p_avail = min(p_avail, p_re)
        if surface_drop:
            p_avail = min(p_avail, p_ko - len(closed) * surface_drop)
    reached = current

    # --- stable operation from the deepest valve that took gas
    operating = None
    if reached is not None:
        operating = _operating_check(reached, closed, p_op, gas_p, p_flow, dp_valve, gas_rate_mscfd, gas_sg)
        for msg in operating["issues"]:
            issues.append(msg)
    if target_tvd is not None and reached is not None and reached["tvd"] < target_tvd - 1.0:
        issues.append(f"The deepest valve that can be reached is at {reached['md']:,.0f} ft MD; "
                      f"lifting from the wanted depth is not possible with this string.")
    elif target_tvd is not None and reached is None:
        issues.append("No valve takes gas, so the well cannot be lifted.")
    transfers_ok = all(st.get("closes_upper", True) for st in stages)
    ok = (reached is not None and operating is not None and operating["stable"] and transfers_ok
          and (target_tvd is None or reached["tvd"] >= target_tvd - 1.0))
    if reached is None:
        verdict = ("The well cannot be kicked off with this string and these pressures: redesign needed. "
                   "Options: a higher kick-off pressure, a lighter load fluid, lowering the liquid level first "
                   "(swabbing or a nitrogen unit), or a top valve nearer the liquid level.")
    elif ok:
        verdict = (f"The well can be kicked off and unloaded down to valve {reached['n']} at {reached['md']:,.0f} ft MD "
                   "and should then lift in a stable way: no redesign needed.")
    else:
        verdict = (f"The well kicks off and unloads down to valve {reached['n']} at {reached['md']:,.0f} ft MD, but "
                   "the string does not fully meet the requirements: see the points listed; a redesign (or changes "
                   "to the valves / pressures) is needed.")
    return {"stages": stages, "kickoff_ok": kickoff_ok, "reached": reached, "closed": closed,
            "operating": operating, "issues": issues, "ok": ok, "verdict": verdict}


def _why_not_open(v, st, pi, pu, dp_valve):
    if v["kind"] == "IPO":
        need = st["p_surface_needed"]
        return (f"valve {v['n']} at {v['md']:,.0f} ft MD needs about {need:,.0f} psig at the surface to open "
                f"(tubing pressure {pu:,.0f} psig there) but only {st['p_surface']:,.0f} psig is available.")
    if v["kind"] == "PPO":
        return (f"valve {v['n']} at {v['md']:,.0f} ft MD needs {st['p_tub_needed']:,.0f} psig of tubing pressure to "
                f"open but the load fluid gives only {pu:,.0f} psig.")
    return (f"gas cannot enter at {v['md']:,.0f} ft MD: casing pressure {pi:,.0f} psig against {pu:,.0f} psig in the tubing.")


def _transfer(upper, lower, gas_p, p_flow, p_surface, p_op):
    """Does `upper` close once `lower` injects?  Returns (ok, text)."""
    if upper["kind"] == "orifice":
        return False, "an orifice never closes; it should be the bottom valve only."
    if upper["kind"] == "IPO":
        p_close = surface_pressure_for(gas_p, upper["tvd"], upper["pd"])
        if lower["kind"] == "IPO":
            p_stay = surface_pressure_for(gas_p, lower["tvd"], lower["pd"])
            if p_stay >= p_close + TRANSFER_MARGIN:
                return False, (f"the lower valve closes at {p_stay:,.0f} psig surface pressure, not below the "
                               f"{p_close:,.0f} psig at which the upper one closes (closing pressures must fall with depth).")
            if p_stay >= p_close - TRANSFER_MARGIN:
                return True, (f"the surface pressure has to be brought below {p_close:,.0f} psig to close it; the margin "
                              f"to the lower valve ({p_stay:,.0f} psig) is small.")
        return True, f"the surface pressure has to be brought below {p_close:,.0f} psig to close it."
    # PPO: closes when the tubing pressure at its depth drops below its dome pressure
    p_t = p_flow(upper["tvd"])
    if p_t > upper["pd"]:
        return False, (f"the tubing pressure there stays at {p_t:,.0f} psig, above the {upper['pd']:,.0f} psig it closes at.")
    return True, "the lighter tubing pressure closes it."


def _operating_check(reached, closed, p_op, gas_p, p_flow, dp_valve, gas_rate, gas_sg):
    """Stability of normal operation with injection from `reached` at surface pressure p_op."""
    issues = []
    p_cas = gas_p(reached["tvd"], p_op)
    p_tub = p_flow(reached["tvd"])
    stable = True
    info = {"md": reached["md"], "tvd": reached["tvd"], "p_casing": p_cas, "p_tubing": p_tub,
            "differential": p_cas - p_tub}
    if p_cas - p_tub < dp_valve:
        stable = False
        issues.append(f"At the operating pressure of {p_op:,.0f} psig the casing pressure at "
                      f"{reached['md']:,.0f} ft MD is {p_cas:,.0f} psig against {p_tub:,.0f} psig in the tubing: "
                      f"only {p_cas - p_tub:,.0f} psi across the valve.")
    if reached["kind"] == "IPO" and p_cas < reached["pd"]:
        stable = False
        issues.append(f"The operating valve ({reached['md']:,.0f} ft MD) closes below {reached['pd']:,.0f} psig "
                      f"injection pressure at its depth; at {p_op:,.0f} psig surface it only has {p_cas:,.0f} psig, "
                      "so it will cycle or stay closed.")
    elif reached["kind"] == "PPO" and p_tub < ppo_opening(reached["pd"], reached["R"], p_cas):
        issues.append(f"The operating PPO valve needs {ppo_opening(reached['pd'], reached['R'], p_cas):,.0f} psig of "
                      f"tubing pressure to open and the flowing pressure is {p_tub:,.0f} psig: it can close.")
        stable = False
    multi = []
    for j in closed:
        pi = gas_p(j["tvd"], p_op)
        pt = p_flow(j["tvd"])
        if _opens(j, pi, pt):
            multi.append(j)
    if multi:
        stable = False
        names = ", ".join(f"{j['n']} ({j['md']:,.0f} ft)" for j in multi)
        issues.append(f"Valve(s) {names} are open at normal operation (multi-pointing): gas leaks in above the "
                      "operating valve. Reduce the operating pressure or reset those valves.")
    if gas_rate:
        if reached["kind"] in ("IPO", "PPO", "orifice"):
            cap = gas_passage(reached["port"], p_cas, p_tub, gas_sg, reached["T"])
            info["capacity"] = cap
            info["gas_rate_needed"] = gas_rate
            if gas_rate > cap:
                issues.append(f"The {port_label(reached['port'])} port at {reached['md']:,.0f} ft MD passes about "
                              f"{cap:,.0f} Mscf/d at these pressures; {gas_rate:,.0f} Mscf/d is wanted.")
    info["stable"] = stable
    info["issues"] = issues
    info["multi_pointing"] = [j["n"] for j in multi]
    return info


# ---------------------------------------------------------------------------------------------
# 7. Frames for the unloading picture / animation
#    This is a quasi-steady picture: each frame is a pressure-against-depth snapshot at the end of one
#    step of the unloading (it is not a transient multiphase simulation).
# ---------------------------------------------------------------------------------------------
def unloading_frames(valves, check, *, p_ko, p_op, p_wh, g_unload, gas_p, p_flow, sfl_tvd, tvd_bottom,
                     annulus_cap, tubing_cap, md_of, gas_rate_mscfd=None, gas_sg=0.65, n_between=3):
    """List of frames for the animation.  Each frame is a dictionary:
        title, text, depth (TVD list), p_casing, p_tubing, level_annulus, level_tubing (TVD, 0 = surface),
        p_surface (casing, psig), valve_state {n: 'closed' | 'injecting'}, hours (estimated time since kick-off)
    """
    depth = [tvd_bottom * k / 120.0 for k in range(121)]
    state = {v["n"]: "closed" for v in valves}
    hours = 0.0

    def tubing_line(top_level, gas_from_valve=None):
        """Tubing pressure at each depth: gas / lightened column above `gas_to`, load fluid gradient below."""
        out = []
        for d in depth:
            if gas_from_valve is not None and d <= gas_from_valve["tvd"]:
                out.append(p_flow(d))
            elif gas_from_valve is not None:
                out.append(p_flow(gas_from_valve["tvd"]) + g_unload * (d - gas_from_valve["tvd"]))
            else:
                out.append(p_wh + g_unload * max(d - top_level, 0.0))
        return out

    def casing_line(p_s, level):
        out = []
        p_level = gas_p(level, p_s) if level > 0 else p_s
        for d in depth:
            out.append(gas_p(d, p_s) if d <= level else p_level + g_unload * (d - level))
        return out

    frames = []

    def add(title, text, p_s, level_a, level_t, gas_valve=None, tubing=None, at_hours=None):
        frames.append({"title": title, "text": text, "depth": list(depth),
                       "p_casing": casing_line(p_s, level_a),
                       "p_tubing": tubing if tubing is not None else tubing_line(level_t, gas_from_valve=gas_valve),
                       "level_annulus": level_a, "level_tubing": level_t, "p_surface": p_s,
                       "valve_state": dict(state), "hours": hours if at_hours is None else at_hours})

    add("Before kick-off",
        f"Well loaded with kill fluid. The liquid level in the annulus and in the tubing is at "
        f"{md_of(sfl_tvd):,.0f} ft MD; no gas pressure yet.", 0.0, sfl_tvd, sfl_tvd)
    work = [s for s in check["stages"] if s.get("opens")]
    by_n = {v["n"]: v for v in valves}
    if not work:
        add("Kick-off fails",
            "The available kick-off pressure cannot open the top valve; the annulus liquid cannot be displaced into "
            "the tubing.", p_ko, sfl_tvd, sfl_tvd)
        return frames
    prev_v, prev_level_t = None, sfl_tvd
    for k, st in enumerate(work):
        v = by_n[st["n"]]
        start = sfl_tvd if prev_v is None else prev_v["tvd"]
        dh = _stage_hours(prev_v, st, annulus_cap, max(v["tvd"] - start, 0.0), gas_p, p_flow, gas_sg)
        # the annulus liquid level goes down to the valve
        for j in range(1, n_between + 1):
            lev = start + (v["tvd"] - start) * j / n_between
            if prev_v is None:
                lev_t = max(0.0, sfl_tvd - (lev - sfl_tvd) * annulus_cap / tubing_cap)    # tubing level rises
                tub = None
                title = "Kick-off: gas pressure pushes the annulus liquid down"
                txt = (f"Surface casing pressure {p_ko:,.0f} psig. The annulus liquid is displaced through the top "
                       f"valve into the tubing, so the tubing liquid level rises.")
                add(title, txt, p_ko, lev, lev_t, at_hours=hours + dh * j / n_between)
            else:
                tub = tubing_line(0.0, gas_from_valve=prev_v)
                title = f"Valve {prev_v['n']} injects: the annulus level goes down towards valve {v['n']}"
                txt = (f"Gas is entering at {prev_v['md']:,.0f} ft MD and lightening the tubing. The liquid left in the "
                       f"annulus is pushed through valve {prev_v['n']}.")
                add(title, txt, st["p_surface"], lev, 0.0, gas_valve=prev_v, tubing=tub,
                    at_hours=hours + dh * j / n_between)
        hours += dh
        state[v["n"]] = "injecting"
        add(f"Valve {v['n']} uncovered and open",
            f"Valve {v['n']} at {v['md']:,.0f} ft MD opens (surface pressure {st['p_surface']:,.0f} psig). "
            "Gas starts to enter the tubing there.", st["p_surface"], v["tvd"], 0.0, gas_valve=v)
        if prev_v is not None:
            state[prev_v["n"]] = "closed"
            add(f"Valve {prev_v['n']} closes",
                f"Gas now enters through valve {v['n']}; the surface pressure is lowered and valve {prev_v['n']} "
                f"({prev_v['md']:,.0f} ft MD) closes.", min(st["p_surface"], st.get("p_close_upper", st["p_surface"])),
                v["tvd"], 0.0, gas_valve=v)
        prev_v = v
    last = prev_v
    add(f"Normal operation from valve {last['n']}",
        f"All unloading valves are closed; gas is injected at {last['md']:,.0f} ft MD with {p_op:,.0f} psig at the "
        "surface and the well produces at its design flowing pressure.", p_op, last["tvd"], 0.0, gas_valve=last)
    if check["issues"] and not check["ok"]:
        frames[-1]["text"] += " (This string does not meet all the requirements; see the check above.)"
    return frames


def _stage_hours(prev_v, st, annulus_cap, delta_tvd, gas_p, p_flow, gas_sg):
    """Rough time to push the annulus liquid down delta_tvd with the gas that passes the valve above."""
    if delta_tvd <= 0:
        return 0.0
    p_cas = st["p_inj"] + ATM
    vol_scf = annulus_cap * 5.615 * delta_tvd * p_cas / ATM          # gas needed to fill the volume (scf)
    if prev_v is None or prev_v.get("port") is None:
        rate = 500.0                                                 # Mscf/d, nominal (first valve)
    else:
        rate = gas_passage(prev_v["port"], st["p_inj"], st["p_tub"], gas_sg, prev_v["T"]) or 500.0
    return vol_scf / (rate * 1000.0) * 24.0
