"""
vlp.py - Vertical Lift Performance (VLP) for the Nodal Analysis app (Oilfield units).

A VLP answers one question:
    "If the well makes this rate and the wellhead pressure is fixed, what flowing
     bottom-hole pressure (Pwf) is needed to push the fluid up the tubing?"

Units: pressure psia | temperature degF | length ft | pipe ID in | angle degrees
       oil / water rate STB/d | gas rate Mscf/d | velocity ft/s | density lb/ft3
       viscosity cP | surface tension dyne/cm | pressure gradient psi/ft

How the calculation works (in plain words)
    1. well.py cuts the well into short steps, wellhead -> perforations.
    2. For each step, starting from the known pressure at the top of the step, we
       guess the pressure at the bottom, take the average, get the fluid properties
       there (pvt.py), turn them into a pressure gradient (a "correlation"), and
       correct the bottom pressure.  Repeat a few times until it stops changing.
    3. The pressure at the bottom of the last step is Pwf.

Pieces in this file
    friction_factor()          - Moody friction factor (laminar / Colebrook)
    sigma_oil_gas(), sigma_water_gas() - surface tension
    beggs_brill_gradient()     - the Beggs & Brill (1973) correlation
    hagedorn_brown_gradient()  - the Hagedorn & Brown (1965) correlation (+ Griffith bubble flow)
    gray_gradient()            - the Gray (1974) correlation for gas wells with a little liquid
    orkiszewski_gradient()     - the Orkiszewski (1967) correlation (bubble, slug, transition and mist flow)
    ansari_gradient()          - the Ansari et al. (1994) mechanistic model (bubble, slug and annular flow)
    duns_ros_gradient()        - the Duns & Ros (1963) correlation (three regions and a transition, chart-based)
    mukherjee_brill_gradient() - the Mukherjee & Brill (1983 / 1985) correlation for any angle, uphill or downhill
    fancher_brown_gradient()   - the Fancher & Brown (1963) no-slip correlation (a quality-control lower bound)
    OilWaterFluid, GasFluid    - turn rate + pressure + temperature into velocities etc.
    pressure_traverse()        - the step-by-step calculation described above
    vlp_curve()                - Pwf for a list of rates

Coded: Beggs & Brill, Hagedorn & Brown, Gray, Orkiszewski, Ansari, Duns & Ros, Mukherjee & Brill and Fancher & Brown.
A new correlation is added by writing a function with the same inputs/outputs as
beggs_brill_gradient() and listing it in GRADIENT_FUNCS (further down).
"""
import bisect
import math
from dataclasses import dataclass

import pvt
from well import build_steps, fluid_temperatures

GC = 32.174            # gravitational constant, lbm ft / (lbf s2). Also g in ft/s2 (g/gc = 1).
RE_CONST = 1488.16     # Reynolds number = 1488.16 * rho(lb/ft3) * v(ft/s) * d(ft) / mu(cP)
GAS_RHO_SC = 0.0764    # lb/scf: gas density of gravity 1.0 at standard conditions (same as pvt.py)
OIL_CP = 0.5           # heat capacities (Btu/lb/degF) used for the temperature profile
GAS_CP = 0.5
WATER_CP = 1.0


def _check(condition, message):
    """Stop with a clear error message if an input does not make sense."""
    if not condition:
        raise ValueError(message)


# =====================================================================
# Friction factor
# =====================================================================

def _colebrook(re, eps_over_d):
    """Turbulent (Darcy) friction factor from the Colebrook equation, solved by repeating."""
    # Swamee-Jain gives a good first guess, then Colebrook is iterated.
    f0 = 0.25 / math.log10(eps_over_d / 3.7 + 5.74 / re ** 0.9) ** 2
    x = 1.0 / math.sqrt(f0)                          # x = 1/sqrt(f)
    for _ in range(50):
        x_new = -2.0 * math.log10(eps_over_d / 3.7 + 2.51 * x / re)
        if abs(x_new - x) < 1e-10:
            x = x_new
            break
        x = x_new
    return 1.0 / x ** 2


def friction_factor(re, eps_over_d=0.0):
    """Darcy (Moody) friction factor.

    re < 2100       : laminar, f = 64 / Re
    2100 <= re < 4000: straight-line blend between laminar and turbulent (no jump)
    re >= 4000      : Colebrook (eps_over_d = roughness / diameter)
    """
    _check(re > 0, "Reynolds number must be > 0.")
    if re < 2100.0:
        return 64.0 / re
    if re >= 4000.0:
        return _colebrook(re, eps_over_d)
    f_lam = 64.0 / 2100.0
    f_turb = _colebrook(4000.0, eps_over_d)
    return f_lam + (f_turb - f_lam) * (re - 2100.0) / (4000.0 - 2100.0)


# =====================================================================
# Surface tension (dyne/cm)  -  needed for the liquid velocity number
# =====================================================================

def sigma_oil_gas(api, T, p):
    """Oil / gas surface tension (Baker & Swerdloff): dead-oil value at 68 and 100 degF,
    straight-line in T between them, then reduced for dissolved gas at pressure p.
    Never allowed below 1 dyne/cm."""
    s68 = 39.0 - 0.2571 * api
    s100 = 37.5 - 0.2571 * api
    t = min(max(T, 68.0), 100.0)
    sigma_dead = s68 + (s100 - s68) * (t - 68.0) / 32.0
    factor = max(1.0 - 0.024 * p ** 0.45, 0.0)
    return max(sigma_dead * factor, 1.0)


def sigma_water_gas(T, p):
    """Water / gas surface tension (Hough / Baker): values at 74 and 280 degF,
    straight-line in T between them."""
    s74 = 75.0 - 1.108 * p ** 0.349
    s280 = 53.0 - 0.1048 * p ** 0.637
    t = min(max(T, 74.0), 280.0)
    return max(s74 + (s280 - s74) * (t - 74.0) / 206.0, 1.0)


# =====================================================================
# Beggs & Brill (1973) - works for any angle: vertical, deviated, horizontal
# =====================================================================
# Idea: first find which flow pattern WOULD exist if the pipe were horizontal,
# use it to get the liquid holdup (fraction of the pipe cross-section filled with
# liquid), correct the holdup for the pipe angle, then add the friction and
# gravity pressure gradients.

# Horizontal holdup constants:  HL(0) = a * lambda^b / NFr^c
_BB_HORIZONTAL = {
    "segregated":   (0.98, 0.4846, 0.0868),
    "intermittent": (0.845, 0.5351, 0.0173),
    "distributed":  (1.065, 0.5824, 0.0609),
}

# Inclination constants:  C = (1 - lambda) * ln( d * lambda^e * NLv^f * NFr^g )
_BB_UPHILL = {
    "segregated":   (0.011, -3.768, 3.539, -1.614),
    "intermittent": (2.96, 0.305, -0.4473, 0.0978),
}
_BB_DOWNHILL = (4.70, -0.3692, 0.1244, -0.5056)     # all flow patterns


def _bb_limits(lam):
    """The four flow-pattern boundaries L1..L4 (they depend on the no-slip liquid fraction)."""
    l1 = 316.0 * lam ** 0.302
    l2 = 0.0009252 * lam ** -2.4684
    l3 = 0.10 * lam ** -1.4516
    l4 = 0.5 * lam ** -6.738
    return l1, l2, l3, l4


def _bb_flow_regime(lam, n_fr):
    """Horizontal flow pattern: 'segregated', 'transition', 'intermittent' or 'distributed'.
    lam = no-slip liquid fraction, n_fr = mixture Froude number."""
    l1, l2, l3, l4 = _bb_limits(lam)
    if (lam < 0.01 and n_fr < l1) or (lam >= 0.01 and n_fr < l2):
        return "segregated"
    if lam >= 0.01 and l2 <= n_fr <= l3:
        return "transition"
    if (0.01 <= lam < 0.4 and l3 < n_fr <= l1) or (lam >= 0.4 and l3 < n_fr <= l4):
        return "intermittent"
    return "distributed"


def _bb_n_lv(v_sl, rho_l, sigma):
    """Liquid velocity number  NLv = 1.938 * v_sl * (rho_l / sigma)^0.25."""
    return 1.938 * v_sl * (rho_l / sigma) ** 0.25


def _bb_horizontal_holdup(regime, lam, n_fr):
    """Liquid holdup if the pipe were horizontal (never less than the no-slip value)."""
    a, b, c = _BB_HORIZONTAL[regime]
    return max(a * lam ** b / n_fr ** c, lam)


def _bb_inclination_c(regime, lam, n_lv, n_fr, theta_rad):
    """The factor C used in the holdup correction for pipe angle (never negative)."""
    if theta_rad > 0:                                  # flow uphill
        if regime == "distributed":
            return 0.0                                 # no correction for distributed uphill
        d, e, f, g = _BB_UPHILL[regime]
    elif theta_rad < 0:                                # flow downhill
        d, e, f, g = _BB_DOWNHILL
    else:                                              # horizontal
        return 0.0
    c = (1.0 - lam) * math.log(d * lam ** e * n_lv ** f * n_fr ** g)
    return max(c, 0.0)


def _bb_holdup_one_regime(regime, lam, n_fr, n_lv, theta_rad):
    """Liquid holdup at the real pipe angle for ONE flow pattern."""
    hl0 = _bb_horizontal_holdup(regime, lam, n_fr)
    c = _bb_inclination_c(regime, lam, n_lv, n_fr, theta_rad)
    s = math.sin(1.8 * theta_rad)
    psi = 1.0 + c * (s - s ** 3 / 3.0)                 # inclination correction factor
    return min(hl0 * psi, 1.0)


def _bb_holdup(lam, n_fr, n_lv, theta_rad):
    """Flow pattern and liquid holdup at the real pipe angle (for 0 < lam < 1).
    In the transition pattern the holdup is a blend of the segregated and intermittent values."""
    regime = _bb_flow_regime(lam, n_fr)
    if regime == "transition":
        _, l2, l3, _ = _bb_limits(lam)
        a = (l3 - n_fr) / (l3 - l2)                     # a = 1 at L2 (segregated), 0 at L3 (intermittent)
        hl = (a * _bb_holdup_one_regime("segregated", lam, n_fr, n_lv, theta_rad)
              + (1.0 - a) * _bb_holdup_one_regime("intermittent", lam, n_fr, n_lv, theta_rad))
    else:
        hl = _bb_holdup_one_regime(regime, lam, n_fr, n_lv, theta_rad)
    return regime, hl


def beggs_brill_gradient(p, angle_deg, d_in, roughness_in, c):
    """Beggs & Brill pressure gradient in psi per ft of pipe length.  Positive means the
    pressure at the bottom of the step is higher than at the top (the pressure the well
    must supply to push the fluid up).

    p            : pressure (psia)
    angle_deg    : pipe angle from horizontal in the flow direction (90 = vertical up)
    d_in         : pipe inner diameter (in)
    roughness_in : pipe wall roughness (in)
    c            : dictionary of flow conditions (see OilWaterFluid.conditions):
                   v_sl, v_sg (ft/s) | rho_l, rho_g (lb/ft3) | mu_l, mu_g (cP) | sigma (dyne/cm)

    Returns a dictionary with 'dpdl' (the total gradient) plus holdup, flow regime, etc.
    """
    _check(p > 0 and d_in > 0, "Pressure and diameter must be > 0.")
    d_ft = d_in / 12.0
    v_sl, v_sg = c["v_sl"], c["v_sg"]
    v_m = v_sl + v_sg                                   # mixture velocity
    _check(v_m > 0, "No flow: mixture velocity is zero.")
    lam = v_sl / v_m                                    # no-slip liquid fraction
    theta = math.radians(angle_deg)

    # ---- liquid holdup ------------------------------------------------
    if lam < 1e-8:                                      # gas only
        regime, hl, lam = "gas", 0.0, 0.0
    elif lam > 1.0 - 1e-8:                              # liquid only
        regime, hl, lam = "liquid", 1.0, 1.0
    else:
        n_fr = v_m ** 2 / (GC * d_ft)                   # Froude number
        n_lv = _bb_n_lv(v_sl, c["rho_l"], c["sigma"])
        regime, hl = _bb_holdup(lam, n_fr, n_lv, theta)

    # ---- densities and viscosity --------------------------------------
    rho_ns = c["rho_l"] * lam + c["rho_g"] * (1.0 - lam)        # no-slip mixture density
    mu_ns = c["mu_l"] * lam + c["mu_g"] * (1.0 - lam)           # no-slip mixture viscosity
    rho_s = c["rho_l"] * hl + c["rho_g"] * (1.0 - hl)           # in-situ (slip) density

    # ---- friction -----------------------------------------------------
    re_ns = RE_CONST * rho_ns * v_m * d_ft / mu_ns
    f_n = friction_factor(re_ns, roughness_in / d_in)           # no-slip friction factor
    if 0.0 < lam < 1.0:
        y = lam / hl ** 2
        if 1.0 < y < 1.2:
            s_exp = math.log(2.2 * y - 1.2)
        else:
            ln_y = math.log(y)
            s_exp = ln_y / (-0.0523 + 3.182 * ln_y - 0.8725 * ln_y ** 2 + 0.01853 * ln_y ** 4)
        f_tp = f_n * math.exp(s_exp)                            # two-phase friction factor
    else:
        f_tp = f_n

    hydrostatic = rho_s * math.sin(theta) / 144.0               # psi/ft
    friction = f_tp * rho_ns * v_m ** 2 / (2.0 * GC * d_ft) / 144.0

    # ---- acceleration term and total ---------------------------------
    e_k = min(rho_s * v_m * v_sg / (GC * p * 144.0), 0.95)
    dpdl = (hydrostatic + friction) / (1.0 - e_k)
    return {"dpdl": dpdl, "hl": hl, "regime": regime, "hydrostatic": hydrostatic,
            "friction": friction, "f_tp": f_tp, "re": re_ns, "e_k": e_k}


# =====================================================================
# Hagedorn & Brown (1965) with the Griffith bubble-flow correction
# =====================================================================
# Hagedorn & Brown measured pressures in a 1500 ft vertical well and found the
# liquid holdup (fraction of the pipe filled with liquid) from three CHARTS that
# were built from four dimensionless numbers (the Duns & Ros numbers).  Reading
# charts by eye does not work in a program, so the three charts are replaced here
# by published curve fits (the same ones used in Brill & Mukherjee's book):
#     chart 1:  N_L   -> CN_L      (viscosity coefficient)
#     chart 2:  H     -> HL/psi    (holdup before correction)
#     chart 3:  B     -> psi       (correction factor)
#     holdup  = (HL/psi) * psi
# It is a VERTICAL-flow correlation: the angle is only used for the hydrostatic
# term (sin of the angle), so use it with care in strongly deviated or horizontal
# sections.  Two well-known modifications are included:
#   * Griffith bubble flow: when there is very little gas (gas fraction below
#     LB) the holdup comes from Griffith's slip equation (slip velocity 0.8 ft/s).
#   * The holdup is never allowed below the no-slip liquid fraction (liquid cannot
#     travel slower than the gas) and never above 1.

HB_SLIP_VELOCITY = 0.8        # Griffith bubble-flow slip velocity, ft/s
HB_PATM = 14.7                # psia, used in the pressure ratio of the holdup group


def hb_cn_l(n_l):
    """Chart 1 (Fig. 12 of the paper): viscosity coefficient CN_L from the liquid viscosity number N_L."""
    # The paper's Fig. 12 ends at N_L = 0.5 (CN_L about 0.011) and is flat there; the cubic fit would keep rising
    # beyond it (0.021 at N_L = 1), so N_L is held at 0.5 for very viscous liquids.
    n_l = min(max(n_l, 0.0), 0.5)
    return 0.061 * n_l ** 3 - 0.0929 * n_l ** 2 + 0.0505 * n_l + 0.0019


def hb_holdup_over_psi(h):
    """Chart 2: HL/psi from the group H.  Goes from 0 (H = 0) up to 1 (H large).

    The published curve fit (Brill & Mukherjee) is good for H above 1e-5 but flattens
    to 0.07 as H -> 0, while the chart in the paper keeps falling (0.01 at H = 1e-7).
    That floor would put 7 % liquid in a wet-gas well that carries almost none, so
    below H = 1e-5 the curve follows the chart's slope (about H^0.55) instead."""
    h = max(h, 0.0)
    if h < HB_LOW_H:
        return _hb_fit(HB_LOW_H) * (h / HB_LOW_H) ** 0.55
    return _hb_fit(h)


HB_LOW_H = 1.0e-5       # below this the paper's chart is used (power law) instead of the fit


def _hb_fit(h):
    top = 0.0047 + 1123.32 * h + 729489.64 * h ** 2
    bottom = 1.0 + 1097.1566 * h + 722153.97 * h ** 2
    return math.sqrt(top / bottom)


def hb_psi(b):
    """Chart 3: secondary correction factor psi from the group B.  Starts at 1 and grows
    to about 1.8 as the gas velocity number grows (three straight/curved pieces)."""
    b = max(b, 0.0)
    if b <= 0.025:
        return 27170.0 * b ** 3 - 317.52 * b ** 2 + 0.5472 * b + 0.9999
    if b <= 0.055:
        return -533.33 * b ** 2 + 58.524 * b + 0.1171
    return 2.5714 * b + 1.5962


def hb_numbers(p, d_ft, c):
    """The four dimensionless numbers and the two chart groups H and B.
    Returns a dictionary with n_lv, n_gv, n_d, n_l, cn_l, h, b."""
    root4 = (c["rho_l"] / c["sigma"]) ** 0.25
    n_lv = 1.938 * c["v_sl"] * root4                              # liquid velocity number
    n_gv = 1.938 * c["v_sg"] * root4                              # gas velocity number
    n_d = 120.872 * d_ft * (c["rho_l"] / c["sigma"]) ** 0.5       # pipe diameter number
    n_l = 0.15726 * c["mu_l"] * (1.0 / (c["rho_l"] * c["sigma"] ** 3)) ** 0.25   # liquid viscosity number
    cn_l = hb_cn_l(n_l)
    h = n_lv / n_gv ** 0.575 * (p / HB_PATM) ** 0.1 * cn_l / n_d
    b = n_gv * n_lv ** 0.38 / n_d ** 2.14
    return {"n_lv": n_lv, "n_gv": n_gv, "n_d": n_d, "n_l": n_l, "cn_l": cn_l, "h": h, "b": b}


def griffith_bubble_holdup(v_m, v_sg):
    """Griffith bubble-flow liquid holdup:  HL = 1 - 0.5 * (1 + vm/vs - sqrt((1 + vm/vs)^2 - 4 vsg/vs))"""
    x = 1.0 + v_m / HB_SLIP_VELOCITY
    return 1.0 - 0.5 * (x - math.sqrt(max(x * x - 4.0 * v_sg / HB_SLIP_VELOCITY, 0.0)))


def hagedorn_brown_gradient(p, angle_deg, d_in, roughness_in, c):
    """Hagedorn & Brown pressure gradient (psi per ft of pipe), same inputs and same
    kind of result as beggs_brill_gradient (see there for the meaning of the inputs).

    The returned dictionary has 'dpdl', 'hl', 'regime' ('hagedorn', 'bubble', 'liquid' or
    'gas'), 'hydrostatic', 'friction', 'f_tp' (friction factor used), 're' and 'e_k'.
    """
    _check(p > 0 and d_in > 0, "Pressure and diameter must be > 0.")
    d_ft = d_in / 12.0
    v_sl, v_sg = c["v_sl"], c["v_sg"]
    v_m = v_sl + v_sg                                   # mixture velocity
    _check(v_m > 0, "No flow: mixture velocity is zero.")
    lam = v_sl / v_m                                    # no-slip liquid fraction
    theta = math.radians(angle_deg)
    rho_l, rho_g, mu_l, mu_g = c["rho_l"], c["rho_g"], c["mu_l"], c["mu_g"]

    # ---- liquid holdup ------------------------------------------------
    if lam < 1e-8:                                      # gas only
        regime, hl, lam = "gas", 0.0, 0.0
    elif lam > 1.0 - 1e-8:                              # liquid only
        regime, hl, lam = "liquid", 1.0, 1.0
    else:
        lb = max(1.071 - 0.2218 * v_m ** 2 / d_ft, 0.13)          # Griffith bubble-flow limit
        if v_sg / v_m < lb:
            regime = "bubble"
            hl = griffith_bubble_holdup(v_m, v_sg)
        else:
            regime = "hagedorn"
            num = hb_numbers(p, d_ft, c)
            hl = hb_holdup_over_psi(num["h"]) * hb_psi(num["b"])
        hl = min(max(hl, lam), 1.0)                     # never below no-slip, never above 1

    # ---- densities ----------------------------------------------------
    rho_ns = rho_l * lam + rho_g * (1.0 - lam)          # no-slip mixture density
    rho_s = rho_l * hl + rho_g * (1.0 - hl)             # in-situ (slip) density

    # ---- friction -----------------------------------------------------
    if regime == "bubble":
        # Bubble flow: the liquid fills the pipe, so friction is that of the liquid
        # moving at its true (in-situ) velocity.
        v_l = v_sl / hl
        re = RE_CONST * rho_l * v_l * d_ft / mu_l
        f = friction_factor(re, roughness_in / d_in)
        friction = f * rho_l * v_l ** 2 / (2.0 * GC * d_ft) / 144.0
    else:
        # Original Hagedorn & Brown: viscosity weighted by the holdup, and the friction
        # term uses rho_ns^2 / rho_s.
        mu_s = mu_l ** hl * mu_g ** (1.0 - hl)
        re = RE_CONST * rho_ns * v_m * d_ft / mu_s
        f = friction_factor(re, roughness_in / d_in)
        friction = f * rho_ns ** 2 * v_m ** 2 / (2.0 * GC * d_ft * rho_s) / 144.0

    hydrostatic = rho_s * math.sin(theta) / 144.0       # psi/ft

    # ---- acceleration term and total (same form as in Beggs & Brill) ----
    e_k = min(rho_s * v_m * v_sg / (GC * p * 144.0), 0.95)
    dpdl = (hydrostatic + friction) / (1.0 - e_k)
    return {"dpdl": dpdl, "hl": hl, "regime": regime, "hydrostatic": hydrostatic,
            "friction": friction, "f_tp": f, "re": re, "e_k": e_k}


# =====================================================================
# Gray (1974, API 14B) - vertical GAS wells that also make a little liquid
# =====================================================================
# Made for lean gas-condensate and wet-gas wells, where the liquid travels as a mist
# or a thin film.  Two ideas:
#   * the liquid holdup comes from one equation in a velocity number (N_v) and a
#     diameter number (N_D);
#   * a liquid film roughens the pipe wall, so the friction uses an "effective"
#     roughness that moves from the pipe's own roughness (almost no liquid) to a
#     value set by surface tension (R = liquid/gas velocity ratio of 0.007 or more).
# Gravity uses the slip density, friction uses the no-slip mixture.
# Meant for: gas velocity up to about 50 ft/s... and beyond, tubing up to 3 in,
# condensate below 50 STB/MMscf, water below 5 STB/MMscf.  Not for oil wells.

GRAY_SIGMA_UNIT = 0.0022046     # 1 dyne/cm expressed in lbm/s2 (the unit N_v and N_D need)
GRAY_MIN_ROUGHNESS = 2.77e-5    # ft, smallest effective roughness allowed


def gray_holdup(r, n_v, n_d):
    """Gray liquid holdup (fraction of the pipe filled with liquid).
    r = v_sl / v_sg.  Same equation as in the API 14B manual."""
    b = 0.0814 * (1.0 - 0.0554 * math.log(1.0 + 730.0 * r / (r + 1.0)))
    f1 = -2.314 * (n_v * (1.0 + 205.0 / n_d)) ** b
    return 1.0 - (1.0 - math.exp(f1)) / (r + 1.0)


def gray_effective_roughness(r, k_ft, sigma_lbm, rho_ns, v_m):
    """Effective wall roughness (ft) seen by the gas when a liquid film is present."""
    k0 = 28.5 * sigma_lbm / (rho_ns * v_m ** 2)                  # roughness set by the liquid film
    if r >= 0.007:
        k_e = k0
    else:                                                        # blend from the pipe's own roughness
        k_e = k_ft + r * (k0 - k_ft) / 0.007
    return max(k_e, GRAY_MIN_ROUGHNESS)


def gray_gradient(p, angle_deg, d_in, roughness_in, c):
    """Gray pressure gradient (psi per ft of pipe), same inputs and same kind of result
    as beggs_brill_gradient (see there for the meaning of the inputs).

    The returned dictionary has 'dpdl', 'hl', 'regime' ('gray', 'liquid' or 'gas'),
    'hydrostatic', 'friction', 'f_tp' (friction factor used), 're', 'e_k' and
    'k_eff' (effective roughness, ft).
    The acceleration term is kept (Gray's original leaves it out); for gas wells it is
    a few percent near the wellhead.
    """
    _check(p > 0 and d_in > 0, "Pressure and diameter must be > 0.")
    d_ft = d_in / 12.0
    v_sl, v_sg = c["v_sl"], c["v_sg"]
    v_m = v_sl + v_sg
    _check(v_m > 0, "No flow: mixture velocity is zero.")
    lam = v_sl / v_m                                    # no-slip liquid fraction
    theta = math.radians(angle_deg)
    rho_l, rho_g, mu_l, mu_g = c["rho_l"], c["rho_g"], c["mu_l"], c["mu_g"]
    k_ft = roughness_in / 12.0

    if lam < 1e-8:                                      # gas only
        regime, hl, lam = "gas", 0.0, 0.0
    elif lam > 1.0 - 1e-8:                              # liquid only
        regime, hl, lam = "liquid", 1.0, 1.0
    else:
        regime = "gray"
    rho_ns = rho_l * lam + rho_g * (1.0 - lam)          # no-slip mixture density
    mu_ns = mu_l * lam + mu_g * (1.0 - lam)             # no-slip mixture viscosity
    k_eff = k_ft

    if regime == "gray":
        sigma = c["sigma"] * GRAY_SIGMA_UNIT            # lbm/s2
        r = v_sl / v_sg
        d_rho = max(rho_l - rho_g, 1.0)
        n_v = rho_ns ** 2 * v_m ** 4 / (GC * sigma * d_rho)
        n_d = GC * d_rho * d_ft ** 2 / sigma
        hl = min(max(gray_holdup(r, n_v, n_d), lam), 1.0)   # never below no-slip, never above 1
        k_eff = gray_effective_roughness(r, k_ft, sigma, rho_ns, v_m)

    rho_s = rho_l * hl + rho_g * (1.0 - hl)             # in-situ (slip) density
    re = RE_CONST * rho_ns * v_m * d_ft / mu_ns
    f = friction_factor(re, min(k_eff / d_ft, 0.05))    # relative roughness is capped at 0.05
    hydrostatic = rho_s * math.sin(theta) / 144.0
    friction = f * rho_ns * v_m ** 2 / (2.0 * GC * d_ft) / 144.0
    e_k = min(rho_s * v_m * v_sg / (GC * p * 144.0), 0.95)
    dpdl = (hydrostatic + friction) / (1.0 - e_k)
    return {"dpdl": dpdl, "hl": hl, "regime": regime, "hydrostatic": hydrostatic,
            "friction": friction, "f_tp": f, "re": re, "e_k": e_k, "k_eff": k_eff}


# =====================================================================
# Orkiszewski (1967, SPE 1546) - vertical oil wells and gas lift wells
# =====================================================================
# A composite of earlier work (the paper's Appendices A-C):
#   * the flow pattern (bubble, slug, transition, mist) comes from the gas fraction and a dimensionless gas
#     velocity v_gD (Griffith-Wallis for bubble/slug, Duns-Ros for the other boundaries);
#   * bubble flow  : Griffith - a constant slip velocity of 0.8 ft/s;
#   * slug flow    : modified Griffith-Wallis - the gas bubbles rise at a velocity v_b, and a "liquid distribution
#                    coefficient" Gamma (from field data) accounts for the liquid film and the droplets in the
#                    bubbles.  This is the pattern met in most flowing and gas lift wells;
#   * mist flow    : Duns-Ros - no slip; the wall roughness seen by the gas is set by the liquid film;
#   * transition   : the slug and mist results weighted linearly with v_gD (Duns-Ros).
# The gradient is  dp/dL = (density * sin(angle) + wall friction) / (1 - kinetic term), as in the paper's Eq. A-3.
#
# Notes on how the paper is coded
#   * Bubble rise velocity v_b uses the paper's own equations C-7, C-8 and C-9 for every Reynolds number (the paper
#     reads C1 and C2 from Figs. 8 and 9 only where those charts reach, up to a Reynolds number of about 6000; the
#     equations are what its Appendix D example uses).  Equation C-9 is written here as 1/2 (v_bi + sqrt(...)); the
#     printed bracket is missing, but only this form joins Eq. C-7 at N_b = 3000 and Eq. C-8 at N_b = 8000.
#   * Equation B-4 prints v_g where v_gD is meant (the Duns-Ros mist boundary).
#   * The constraints C-15 and C-16 on Gamma are applied as written; C-16 contains the average density, which itself
#     contains Gamma, so the inequality is solved for Gamma instead of being iterated.
#   * Which liquid is the continuous phase (needed for Gamma) is not defined in the paper: water when it is at
#     least half of the liquid volume, oil otherwise.
#   * The Moody friction factor is the Colebrook equation (the paper reads a chart).

ORK_SLIP_VELOCITY = 0.8        # Griffith bubble-flow slip velocity, ft/s
ORK_WATER_CONTINUOUS = 0.5     # water is taken as the continuous liquid phase from this water fraction of the liquid


def ork_bubble_rise_velocity(rho_l, mu_l, d_ft, v_t):
    """Bubble rise velocity v_b (ft/s) in slug flow, Eq. C-5 through C-9 of the paper.
    N_Re = 1488 rho_L d v_t / mu_L (C-6) and the bubble Reynolds number N_b = 1488 v_b d rho_L / mu_L.
    Because N_b depends on v_b, the equation that applies is chosen as follows:
      C-7 if the velocity it gives has N_b <= 3000, otherwise
      C-8 if the velocity it gives has N_b >= 8000, otherwise
      C-9 (the equation for 3000 < N_b < 8000)."""
    n_re = RE_CONST * rho_l * d_ft * v_t / mu_l
    root = math.sqrt(GC * d_ft)

    def n_b(v_b):
        return RE_CONST * v_b * d_ft * rho_l / mu_l
    v_7 = (0.546 + 8.74e-6 * n_re) * root
    if n_b(v_7) <= 3000.0:
        return v_7
    v_8 = (0.35 + 8.74e-6 * n_re) * root
    if n_b(v_8) >= 8000.0:
        return v_8
    v_bi = (0.251 + 8.74e-6 * n_re) * root
    return 0.5 * (v_bi + math.sqrt(v_bi ** 2 + 13.59 * mu_l / (rho_l * math.sqrt(d_ft))))


def ork_gamma(mu_l, d_ft, v_t, water_continuous):
    """Liquid distribution coefficient Gamma before the limits C-15 and C-16 (Eq. C-11 to C-14).
    mu_l in cP, d_ft = hydraulic diameter in ft, v_t = total velocity in ft/s; logarithms are base 10."""
    lg = math.log10
    if water_continuous:
        if v_t < 10.0:
            return 0.013 * lg(mu_l) / d_ft ** 1.38 - 0.681 + 0.232 * lg(v_t) - 0.428 * lg(d_ft)           # C-11
        return 0.045 * lg(mu_l) / d_ft ** 0.799 - 0.709 - 0.162 * lg(v_t) - 0.888 * lg(d_ft)             # C-12
    if v_t < 10.0:
        return 0.0127 * lg(mu_l + 1.0) / d_ft ** 1.415 - 0.284 + 0.167 * lg(v_t) + 0.113 * lg(d_ft)      # C-13
    return (0.0274 * lg(mu_l + 1.0) / d_ft ** 1.371 + 0.161 + 0.569 * lg(d_ft)
            - lg(v_t) * (0.01 * lg(mu_l + 1.0) / d_ft ** 1.571 + 0.397 + 0.63 * lg(d_ft)))               # C-14


def _ork_bubble(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d):
    """Bubble flow: (average density, friction gradient in lbf/ft2/ft, extra results)."""
    x = 1.0 + v_t / ORK_SLIP_VELOCITY
    f_g = 0.5 * (x - math.sqrt(max(x * x - 4.0 * v_sg / ORK_SLIP_VELOCITY, 0.0)))        # gas fraction, Eq. C-1
    rho = (1.0 - f_g) * rho_l + f_g * rho_g                                              # Eq. C-2
    v_l = v_sl / (1.0 - f_g)
    re = RE_CONST * rho_l * d_ft * v_l / mu_l
    f = friction_factor(re, eps_d)
    tau = f * rho_l * v_l ** 2 / (2.0 * GC * d_ft)                                       # Eq. C-3
    return rho, tau, {"f": f, "re": re}


def _ork_slug(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d, water_continuous):
    """Slug flow: (average density, friction gradient in lbf/ft2/ft, extra results)."""
    v_b = ork_bubble_rise_velocity(rho_l, mu_l, d_ft, v_t)
    gamma = ork_gamma(mu_l, d_ft, v_t, water_continuous)
    rho_0 = (rho_l * v_sl + rho_g * v_sg + rho_l * v_b) / (v_t + v_b)    # Eq. C-4 without the Gamma term
    share = v_b / (v_t + v_b)                                            # v_b Ap / (q_t + v_b Ap)
    gamma = max(gamma, -0.065 * v_t)                                     # C-15
    if v_t > 10.0:                                                       # C-16:  Gamma >= -share (1 - rho/rho_L), rho = rho_0 + Gamma rho_L
        gamma = max(gamma, -share * (1.0 - rho_0 / rho_l) / (1.0 - share))
    rho = rho_0 + gamma * rho_l                                          # Eq. C-4
    re = RE_CONST * rho_l * d_ft * v_t / mu_l                            # Eq. C-6
    f = friction_factor(re, eps_d)
    bracket = max((v_sl + v_b) / (v_t + v_b) + gamma, 0.0)
    tau = f * rho_l * v_t ** 2 / (2.0 * GC * d_ft) * bracket             # Eq. C-10
    return rho, tau, {"f": f, "re": re, "v_b": v_b, "gamma": gamma}


def _ork_mist(v_sl, v_g, rho_l, rho_g, mu_l, mu_g, sigma_lbm, d_ft, eps_d, duns_ros_roughness=True):
    """Mist flow (no slip) with gas superficial velocity v_g: (density, friction gradient lbf/ft2/ft, extras).
    The wall roughness seen by the gas is the Duns-Ros one (Eq. C-21, C-22), kept between 0.001 and 0.5
    (a gas-only well uses the pipe's own roughness instead)."""
    f_g = v_g / (v_g + v_sl)                                             # Eq. C-19
    rho = (1.0 - f_g) * rho_l + f_g * rho_g                              # Eq. C-2
    if duns_ros_roughness:
        n_w = 4.52e-7 * (v_g * mu_l / sigma_lbm) ** 2 * rho_g / rho_l
        k = 174.8 * sigma_lbm * n_w ** 0.302 if n_w > 0.005 else 34.0 * sigma_lbm
        eps_d = min(max(k / (rho_g * v_g ** 2 * d_ft), 1e-3), 0.5)       # Eq. C-21 / C-22
    re = RE_CONST * rho_g * d_ft * v_g / mu_g
    f = friction_factor(re, eps_d)
    tau = f * rho_g * v_g ** 2 / (2.0 * GC * d_ft)                       # Eq. C-20
    return rho, tau, {"f": f, "re": re}


def ork_flow_regime(v_sl, v_sg, rho_l, sigma_lbm, d_ft):
    """The flow pattern by the paper's Appendix B (liquid with a gas that has v_sg > 0).
    sigma_lbm : surface tension in lbm/s2 (1 dyne/cm = 0.0022046).
    Returns {"regime", "gas_fraction" (q_g/q_t), "l_b", "v_gd", "l_s", "l_m", "root"} where
      l_b  : bubble/slug boundary on the gas fraction (B-2, never below 0.13)
      v_gd : dimensionless gas velocity (B-1), root = (rho_L / (g sigma))^0.25 is its factor v_g -> v_gD
      l_s, l_m : slug/transition and transition/mist boundaries on v_gD (B-3, B-4)"""
    v_t = v_sl + v_sg
    gas_fraction = v_sg / v_t
    l_b = max(1.071 - 0.2218 * v_t ** 2 / d_ft, 0.13)                       # B-2
    root = (rho_l / (GC * sigma_lbm)) ** 0.25
    v_gd = v_sg * root                                                      # B-1
    ratio = root * v_sl                                                     # v_gD q_L / q_g (v_g cancels, so v_g = 0 is fine)
    l_s = 50.0 + 36.0 * ratio                                               # B-3
    l_m = 75.0 + 84.0 * ratio ** 0.75                                       # B-4 (v_gD, see the notes above)
    if gas_fraction < l_b:
        regime = "bubble"
    elif v_gd < l_s:
        regime = "slug"
    elif v_gd < l_m:
        regime = "transition"
    else:
        regime = "mist"
    return {"regime": regime, "gas_fraction": gas_fraction, "l_b": l_b, "v_gd": v_gd, "l_s": l_s, "l_m": l_m, "root": root}


def orkiszewski_gradient(p, angle_deg, d_in, roughness_in, c):
    """Orkiszewski pressure gradient (psi per ft of pipe), same inputs and same kind of result as
    beggs_brill_gradient (see there for the meaning of the inputs; c also carries 'frac_w', the water
    share of the liquid volume, which decides the continuous liquid phase).

    The returned dictionary has 'dpdl', 'hl' (liquid holdup from the density), 'regime' ('bubble', 'slug',
    'transition', 'mist' or 'gas'), 'hydrostatic', 'friction', 'f_tp' (friction factor used), 're', 'e_k',
    and for slug flow 'v_b' and 'gamma'.
    """
    _check(p > 0 and d_in > 0, "Pressure and diameter must be > 0.")
    d_ft = d_in / 12.0
    v_sl, v_sg = c["v_sl"], c["v_sg"]
    v_t = v_sl + v_sg                                   # total velocity (q_t / A_p)
    _check(v_t > 0, "No flow: mixture velocity is zero.")
    theta = math.radians(angle_deg)
    rho_l, rho_g, mu_l, mu_g = c["rho_l"], c["rho_g"], c["mu_l"], c["mu_g"]
    sigma = c["sigma"] * GRAY_SIGMA_UNIT                # lbm/s2, the unit the paper's equations use
    eps_d = roughness_in / d_in
    water_continuous = c.get("frac_w", 0.0) >= ORK_WATER_CONTINUOUS

    extra = {}
    if v_sl < 1e-9 * v_t:                               # no liquid at all: gas only
        regime = "gas"
        rho, tau, extra = _ork_mist(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, False)
        rho = rho_g
    else:
        fp = ork_flow_regime(v_sl, v_sg, rho_l, sigma, d_ft)
        regime = fp["regime"]
        if regime == "bubble":
            rho, tau, extra = _ork_bubble(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d)
        elif regime == "slug":
            rho, tau, extra = _ork_slug(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d, water_continuous)
        elif regime == "transition":
            rho_s, tau_s, extra = _ork_slug(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d, water_continuous)
            v_g_mist = fp["l_m"] / fp["root"]                       # Eq. C-18: gas rate of the mist calculation
            rho_m, tau_m, _ = _ork_mist(v_sl, v_g_mist, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d)
            w_slug = (fp["l_m"] - fp["v_gd"]) / (fp["l_m"] - fp["l_s"])   # Eq. C-17: weights with v_gD
            rho = w_slug * rho_s + (1.0 - w_slug) * rho_m
            tau = w_slug * tau_s + (1.0 - w_slug) * tau_m
        else:
            rho, tau, extra = _ork_mist(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d)

    hl = min(max((rho - rho_g) / max(rho_l - rho_g, 1e-9), 0.0), 1.0)
    hydrostatic = rho * math.sin(theta) / 144.0         # psi/ft
    friction = tau / 144.0
    mass_flux = rho_l * v_sl + rho_g * v_sg             # w_t / A_p, lb/s/ft2
    e_k = min(mass_flux * v_sg / (GC * p * 144.0), 0.95)   # the kinetic term of Eq. A-3 (4637 = 144 g_c)
    dpdl = (hydrostatic + friction) / (1.0 - e_k)
    return {"dpdl": dpdl, "hl": hl, "regime": regime, "hydrostatic": hydrostatic, "friction": friction,
            "f_tp": extra.get("f", 0.0), "re": extra.get("re", 0.0), "e_k": e_k,
            "v_b": extra.get("v_b"), "gamma": extra.get("gamma")}


# =====================================================================
# Ansari et al. (1994) - a mechanistic model, SPE 20630
# =====================================================================
# Ansari, Sylvester, Sarica, Shoham and Brill, "A Comprehensive Mechanistic Model for Upward Two-Phase Flow in
# Wellbores", SPE Production & Facilities, May 1994, p. 143.
#
# Instead of a curve fitted to field data, the model first decides the flow pattern from the physics (Taitel and
# Barnea boundaries), then uses a separate physical model for each pattern:
#     bubble / dispersed bubble : drift-flux holdup, mixture friction
#     slug (and churn)          : a Taylor bubble followed by a liquid slug (Fernandes, Sylvester, Vo and Shoham),
#                                 fully developed or still developing
#     annular                   : a liquid film on the wall and a gas core carrying liquid droplets (Alves, Wallis)
# The paper leaves out the acceleration term, so there is none here.  Everything is in feet, pounds and seconds
# inside these functions (g = 32.174 ft/s2); the result is in psi per ft like the other correlations.
#
# Notes on how the paper is coded (see the README for the reasons):
#   * Equation 40 (the constant A in the slug equation 39) is not used as printed.  The slug equation is rebuilt
#     from the paper's own equations 29 - 35, 37 and 38 (see _ans_slug); the tests check that the solution
#     satisfies every one of them.
#   * Equation 45 (the Nusselt film thickness) is used with the liquid holdup H_NLTB of the film, as the Nusselt
#     film requires, where the paper prints (1 - H_NLTB).
#   * Equation 54 for the length of a developing Taylor bubble is solved for its square root directly (the
#     printed quadratic is the squared form of that equation); b is taken from equations 52 and 53.
#   * The friction factor in the dispersed-bubble boundary (Eq. 4) uses the liquid Reynolds number of the
#     mixture velocity.  Moody factors are Colebrook (the paper reads a chart).
#   * Annular flow is accepted only if the film that the annular model itself finds (Eq. 93) is also too thin to
#     bridge the pipe (holdup of film plus core liquid <= 0.12).  Without this, a gas rate just above Eq. 6 can
#     give a thick, unphysical "annular" film and a very large pressure gradient.
#   * Film instability (Eq. 8): the smaller of the two film holdups that satisfy it is used.  If there is none
#     (liquid rate too high for a stable film) the film holdup at the closest approach is used, which makes the
#     bridging test of Eq. 12 fail, i.e. the flow is not annular.

ANS_SLUG_LENGTH = 30.0         # liquid slug length in pipe diameters (the paper's C' = 30)
ANS_SLUG_RISE = 0.35           # Taylor bubble rise coefficient of Eq. 34
ANS_BUBBLE_RISE = 1.53         # bubble swarm coefficient of Eqs. 3, 21, 35
ANS_FILM_BRIDGE = 0.12         # minimum liquid fraction that can bridge the pipe (Eq. 7, 12)
ANS_DEV_BLEND = 1.5            # L_c / L_TB at which the developing slug equations (Eq. 62) fully replace the
                               # developed ones (Eq. 60).  1.0 is where the paper switches between them; the two
                               # do not meet there, so they are blended from 1.0 to this value.  NOT in the paper.


def _ans_blend(ratio):
    """Weight of the developing slug equations, 0 at ratio = 1 and 1 at ratio = ANS_DEV_BLEND, with a smooth
    (zero-slope) start and finish, so the pressure gradient has no step and no kink where the two meet."""
    if ratio <= 1.0:
        return 0.0
    if ratio >= ANS_DEV_BLEND:
        return 1.0
    x = (ratio - 1.0) / (ANS_DEV_BLEND - 1.0)
    return x * x * (3.0 - 2.0 * x)              # smoothstep


def _ans_bisect(fn, lo, hi, n=200):
    """Root of fn between lo and hi by halving (fn(lo) and fn(hi) must have opposite signs)."""
    f_lo = fn(lo)
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        f_mid = fn(mid)
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
        if hi - lo < 1e-14:
            break
    return 0.5 * (lo + hi)


def _ans_film_instability(y_m, x_m2):
    """Barnea film instability, Eq. 8:  Y_M = (2 - 1.5 H)/(H^3 (1 - 1.5 H)) X_M^2,  solved for the film holdup H.
    The right-hand side has one minimum between H = 0 and 2/3.  Returns the smaller root; if Y_M is below that
    minimum (no root) it returns the holdup at the minimum."""
    def shape(h):
        return (2.0 - 1.5 * h) / (h ** 3 * (1.0 - 1.5 * h))
    lo, hi = 1e-6, 2.0 / 3.0 - 1e-6
    for _ in range(200):                                # golden-section search for the minimum of shape(h)
        m1, m2 = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
        if shape(m1) < shape(m2):
            hi = m2
        else:
            lo = m1
    h_min = 0.5 * (lo + hi)
    target = y_m / x_m2 if x_m2 > 0 else float("inf")
    if target <= shape(h_min):
        return h_min
    return _ans_bisect(lambda h: shape(h) - target, 1e-9, h_min)


def _ans_core(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d):
    """Entrainment and core properties of annular flow (Eqs. 69 - 72, 87 - 90): the entrained fraction F_E,
    the no-slip liquid fraction of the core, its density and viscosity, its superficial velocity, the friction
    factor and the superficial pressure gradient of the core (lbf/ft2/ft)."""
    v_crit = 1.0e4 * v_sg * (mu_g / RE_CONST) / sigma * math.sqrt(rho_g / rho_l)     # Eq. 72 (mu in lbm/ft/s)
    f_e = max(1.0 - math.exp(-0.125 * (v_crit - 1.5)), 0.0)                            # Eq. 71
    lam_lc = f_e * v_sl / (v_sg + f_e * v_sl)                                          # Eq. 70
    rho_c = rho_l * lam_lc + rho_g * (1.0 - lam_lc)                                    # Eq. 69
    mu_c = mu_l * lam_lc + mu_g * (1.0 - lam_lc)                                       # Eq. 90
    v_sc = f_e * v_sl + v_sg                                                           # Eq. 89
    re_sc = RE_CONST * rho_c * v_sc * d_ft / mu_c                                      # Eq. 88
    f_sc = friction_factor(re_sc, eps_d)
    dpdl_sc = f_sc * rho_c * v_sc ** 2 / (2.0 * d_ft * GC)                             # Eq. 87
    return {"f_e": f_e, "lam_lc": lam_lc, "rho_c": rho_c, "mu_c": mu_c, "v_sc": v_sc, "re_sc": re_sc,
            "f_sc": f_sc, "dpdl_sc": dpdl_sc}


def ans_annular_film_thickness(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta):
    """Dimensionless film thickness (film thickness / diameter) of annular flow and the gradient, by solving the
    momentum balance of the film and the core (Eqs. 91 - 93, written here as one equation for delta).
    Returns a dictionary with 'delta', 'dpdl' (lbf/ft2/ft), 'hydrostatic', 'friction' (lbf/ft2/ft), 'holdup',
    the core numbers of _ans_core and 'f_f'."""
    core = _ans_core(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d)
    f_e, rho_c, dpdl_sc = core["f_e"], core["rho_c"], core["dpdl_sc"]
    re_sl = RE_CONST * rho_l * v_sl * d_ft / mu_l                                      # Eq. 80
    f_sl = friction_factor(re_sl, eps_d)
    dpdl_sl = f_sl * rho_l * v_sl ** 2 / (2.0 * d_ft * GC)                             # Eq. 79
    re_f = RE_CONST * rho_l * v_sl * (1.0 - f_e) * d_ft / mu_l                         # Eq. 74 (it does not depend on delta)
    f_f = friction_factor(max(re_f, 1.0), eps_d)
    sin_t = math.sin(theta)
    drive = (rho_l - rho_c) * sin_t                                                    # (rho_L - rho_C) g sin(theta)/gc

    def z_factor(delta):                                                               # Eqs. 84, 85
        if f_e > 0.9:
            return 1.0 + 300.0 * delta
        return 1.0 + 24.0 * (rho_l / rho_g) ** (1.0 / 3.0) * delta

    def residual(delta):                                                               # Eq. 93
        film = 4.0 * delta * (1.0 - delta)
        return (z_factor(delta) * dpdl_sc / (film * (1.0 - 2.0 * delta) ** 5) - drive
                - (1.0 - f_e) ** 2 * (f_f / f_sl) * dpdl_sl / film ** 3)

    # The balance can have more than one root; the first one met from the thin-film side is the physical film.
    # (residual -> minus infinity as delta -> 0 and plus infinity as delta -> 0.5.)
    grid = [1e-7 * (0.5 / 1e-7) ** (i / 400.0) for i in range(401)]
    delta = None
    for lo, hi in zip(grid[:-1], grid[1:]):
        if residual(lo) < 0.0 <= residual(hi):
            delta = _ans_bisect(residual, lo, hi)
            break
    if delta is None:
        delta = _ans_bisect(residual, 1e-9, 0.5 - 1e-9)
    dpdl = z_factor(delta) * dpdl_sc / (1.0 - 2.0 * delta) ** 5 + rho_c * sin_t         # Eq. 91 / 102
    hydrostatic = rho_c * sin_t
    holdup = 4.0 * delta * (1.0 - delta) + core["lam_lc"] * (1.0 - 2.0 * delta) ** 2
    out = dict(core)
    out.update({"delta": delta, "dpdl": dpdl, "hydrostatic": hydrostatic, "friction": dpdl - hydrostatic,
                "holdup": holdup, "f_f": f_f, "f_sl": f_sl, "dpdl_sl": dpdl_sl, "drive": drive,
                "residual_at_root": residual(delta)})
    return out


def ans_flow_pattern(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta):
    """The flow pattern by the paper's boundaries (Eqs. 1 - 12).  v_sl > 0 and v_sg > 0 are expected.
    sigma is in lbm/s2.  Returns {"regime": 'bubble' | 'dispersed' | 'slug' | 'annular', and the numbers
    used: "v_s" (Eq. 3), "d_min" (Eq. 1), "v_sg_a" (Eq. 2), "v_sg_d" (Eq. 6), "h_lf", "core_liquid"}."""
    v_m = v_sl + v_sg
    d_rho = rho_l - rho_g
    v0 = (GC * sigma * d_rho / rho_l ** 2) ** 0.25
    v_s = ANS_BUBBLE_RISE * v0                                                          # Eq. 3
    d_min = 19.01 * math.sqrt(d_rho * sigma / (rho_l ** 2 * GC))                        # Eq. 1
    v_sg_a = 0.25 * v_s + 0.333 * v_sl                                                  # Eq. 2 (transition A)
    v_sg_d = 3.1 * (GC * sigma * d_rho / rho_g ** 2) ** 0.25                            # Eq. 6 (transition D)
    info = {"v_s": v_s, "d_min": d_min, "v_sg_a": v_sg_a, "v_sg_d": v_sg_d, "h_lf": None, "core_liquid": None}

    # annular flow: fast enough gas AND a film too thin to bridge the pipe (Barnea, Eqs. 7 - 15)
    if v_sg > v_sg_d:
        core = _ans_core(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d)
        re_sl = RE_CONST * rho_l * v_sl * d_ft / mu_l
        f_sl = friction_factor(re_sl, eps_d)
        dpdl_sl = f_sl * rho_l * v_sl ** 2 / (2.0 * d_ft * GC)
        f_f = friction_factor(max(RE_CONST * rho_l * v_sl * (1.0 - core["f_e"]) * d_ft / mu_l, 1.0), eps_d)
        b = (1.0 - core["f_e"]) ** 2 * f_f / f_sl
        x_m2 = b * dpdl_sl / core["dpdl_sc"]                                            # X_M squared (Eq. 9)
        y_m = (rho_l - core["rho_c"]) * math.sin(theta) / core["dpdl_sc"]               # Eq. 10
        h_lf = _ans_film_instability(y_m, x_m2)
        core_liquid = core["lam_lc"] * (1.0 - h_lf)                                     # lambda_LC A_C/A_p, with A_C/A_p = 1 - H_LF
        info["h_lf"], info["core_liquid"] = h_lf, core_liquid
        if h_lf + core_liquid <= ANS_FILM_BRIDGE:                                       # Eq. 12 not satisfied
            # The film that the annular model really finds must not bridge the pipe either.  Just above the
            # boundary of Eq. 6 the gas can be too slow to hold the film up; the model then gives a thick film
            # (more liquid than Eq. 12 allows) and the flow is slug, not annular.
            an = ans_annular_film_thickness(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta)
            if an["holdup"] <= ANS_FILM_BRIDGE:
                info["regime"] = "annular"
                info["annular"] = an
                return info

    # dispersed bubble: turbulence breaks the bubbles up (Eq. 4) and the gas fraction is below 0.76 (Eq. 5)
    if v_sg <= 3.17 * v_sl:
        f_m = friction_factor(RE_CONST * rho_l * v_m * d_ft / mu_l, eps_d)
        lhs = (2.0 * (0.4 * sigma / (d_rho * GC)) ** 0.5 * (rho_l / sigma) ** 0.6
               * (f_m / (2.0 * d_ft)) ** 0.4 * v_m ** 1.2)
        rhs = 0.725 + 4.15 * math.sqrt(v_sg / v_m)
        if lhs >= rhs:
            info["regime"] = "dispersed"
            return info

    # bubble flow: wide enough pipe and a low gas rate (Eqs. 1, 2)
    if d_ft >= d_min and v_sg <= v_sg_a:
        info["regime"] = "bubble"
        return info
    info["regime"] = "slug"
    return info


def _ans_bubble_holdup(v_sl, v_sg, v0):
    """Liquid holdup of bubble flow from Eq. 22:  1.53 [g sigma d_rho / rho_L^2]^0.25 H^0.5 = v_Sg/(1 - H) - 1.2 v_m."""
    v_m = v_sl + v_sg
    return _ans_bisect(lambda h: v_sg / (1.0 - h) - 1.2 * v_m - ANS_BUBBLE_RISE * v0 * math.sqrt(h), 1e-9, 1.0 - 1e-12)


def _ans_slug(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d):
    """The slug flow model (Eqs. 29 - 66).  Returns the slug unit variables and its elevation density
    (lbm/ft3, to be multiplied by sin(theta)) and friction gradient (lbf/ft2/ft)."""
    v_m = v_sl + v_sg
    d_rho = rho_l - rho_g
    v0 = (GC * sigma * d_rho / rho_l ** 2) ** 0.25
    v_tb = 1.2 * v_m + ANS_SLUG_RISE * math.sqrt(GC * d_ft * d_rho / rho_l)             # Eq. 34
    h_gls = v_sg / (0.425 + 2.65 * v_m)                                                 # Eq. 38
    h_lls = 1.0 - h_gls
    v_gls = 1.2 * v_m + ANS_BUBBLE_RISE * v0 * math.sqrt(h_lls)                         # Eq. 35

    def v_ltb_of(h_ltb):                                                                # Eq. 37 with H_gTB = 1 - H_LTB
        return 9.916 * math.sqrt(GC * d_ft * (1.0 - math.sqrt(1.0 - h_ltb)))

    def residual(h_ltb):
        # The eight equations 29 - 35, 37, 38 reduce to one equation in H_LTB (Vo and Shoham).  Equations 32 and 33
        # make the flux of liquid plus gas equal in the Taylor bubble and in the liquid slug, and equations 29 + 30
        # say that flux is v_m; this gives (compare Eqs. 39 - 41):
        #     v_LTB H_LTB - v_TB (1 - H_LTB - H_gLS) + (v_m - v_gLS H_gLS) = 0
        return (v_ltb_of(h_ltb) * h_ltb - v_tb * (1.0 - h_ltb - h_gls) + (v_m - v_gls * h_gls))

    lo, hi = 1e-9, 1.0 - 1e-9
    if residual(lo) >= 0.0:
        h_ltb = lo
    elif residual(hi) <= 0.0:
        h_ltb = hi
    else:
        h_ltb = _ans_bisect(residual, lo, hi)
    h_gtb = 1.0 - h_ltb
    v_ltb = v_ltb_of(h_ltb)
    v_lls = v_tb - (v_tb + v_ltb) * h_ltb / h_lls                                        # Eq. 32
    v_gtb = v_tb - (v_tb - v_gls) * h_gls / h_gtb                                        # Eq. 33
    denom = v_lls * h_lls + v_ltb * h_ltb
    beta = (v_lls * h_lls - v_sl) / denom if denom > 0 else 0.5                          # Eq. 30
    beta = min(max(beta, 1e-4), 0.999)
    l_ls = ANS_SLUG_LENGTH * d_ft                                                        # Eq. 48
    l_tb = l_ls * beta / (1.0 - beta)                                                    # Eq. 49

    rho_ls = rho_l * h_lls + rho_g * h_gls                                               # Eq. 61
    mu_ls = mu_l * h_lls + mu_g * h_gls
    out = {"beta": beta, "h_ltb": h_ltb, "h_gls": h_gls, "v_tb": v_tb, "v_gls": v_gls, "v_ltb": v_ltb,
           "v_lls": v_lls, "v_gtb": v_gtb, "l_ls": l_ls, "l_tb": l_tb, "developing": False, "l_c": None}

    # Developing or developed?  Compare the cap length of the Taylor bubble (Eq. 44) with its developed length.
    # The film at the end of the cap has the Nusselt thickness (Eqs. 45 - 47).
    v_ntb_state = None
    if v_tb > v_gls:
        mu_l_si = mu_l / RE_CONST                                                        # lbm/ft/s

        def nusselt(delta):                                                              # delta = film thickness / d
            g_n = (1.0 - 2.0 * delta) ** 2                                               # gas fraction of the Taylor bubble section
            h_n = 1.0 - g_n                                                              # Eq. 46
            v_ngtb = v_tb - (v_tb - v_gls) * h_gls / g_n                                 # Eq. 47
            v_nltb = (v_ngtb * g_n - v_m) / h_n                                          # film velocity from the flux balance
            return h_n, v_ngtb, v_nltb

        def nusselt_residual(delta):                                                     # Eq. 45 cubed
            h_n, _, v_nltb = nusselt(delta)
            return (delta * d_ft) ** 3 - 0.75 * d_ft * mu_l_si * v_nltb * h_n / (GC * d_rho)

        if nusselt_residual(1e-9) < 0.0 < nusselt_residual(0.5 - 1e-9):
            delta_n = _ans_bisect(nusselt_residual, 1e-9, 0.5 - 1e-9)
            h_n, v_ngtb, v_nltb = nusselt(delta_n)
            l_c = (v_tb + v_nltb) ** 2 / (2.0 * GC)                                      # Eq. 44
            out["l_c"] = l_c
            if l_c >= l_tb:
                a = 1.0 - v_sg / v_tb                                                    # Eq. 55
                b = (v_sg - v_gls * h_gls) * l_ls / v_tb                                 # Eqs. 52, 53
                c = (v_tb - v_lls) * h_lls / math.sqrt(2.0 * GC)                         # Eq. 57
                disc = c * c + a * b
                if a > 1e-9 and disc >= 0.0:
                    x = (c + math.sqrt(disc)) / a                                        # = sqrt(L*_TB), Eq. 54
                    l_star = x * x
                    if l_star > 0.0:
                        out["developing"] = True
                        out["l_tb_star"] = l_star
    # Developed (Eq. 60) and developing (Eq. 62) do not agree where they meet (at L_c = L_TB).  Eq. 60 treats the
    # Taylor bubble as pure gas; Eq. 62 counts the liquid film in it through rho_TBA.  The two therefore differ by
    # about beta * rho_L * H_LTB, which here is roughly half the slug-unit density, and the model steps: on a
    # gas-lifted well the VLP curve jumped about 50 psi between two neighbouring rates, enough to move the
    # operating point.  Both of the paper's expressions are kept, and they are blended over
    # 1 <= L_c/L_TB <= ANS_DEV_BLEND so that the gradient is continuous: at the switch the weight is 0, so the
    # developed equations (which reproduce Orkiszewski's measured well 22 best) still apply, and the developing
    # equations take over once the Taylor bubble is clearly shorter than its own cap.
    # THIS BLEND IS A DEVIATION FROM THE PAPER (see the README); its two end points are the paper's own.
    rho_dev = (1.0 - beta) * rho_ls + beta * rho_g                                       # Eq. 60
    holdup_dev = (1.0 - beta) * h_lls + beta * h_ltb
    rho_elev, beta_f, holdup = rho_dev, beta, holdup_dev
    if out["developing"]:
        l_star = out["l_tb_star"]
        beta_e = l_star / (l_star + l_ls)                                                # beta* = L*_TB / L*_SU
        h_ltba = min(2.0 * (v_tb - v_lls) * h_lls / math.sqrt(2.0 * GC * l_star), 1.0)   # Eq. 64
        rho_tba = rho_l * h_ltba + rho_g * (1.0 - h_ltba)                                # Eq. 63
        rho_ing = (1.0 - beta_e) * rho_ls + beta_e * rho_tba                             # Eq. 62
        holdup_ing = (1.0 - beta_e) * h_lls + beta_e * h_ltba
        w = _ans_blend(out["l_c"] / l_tb) if l_tb > 0.0 else 1.0
        out["blend"] = w
        rho_elev = (1.0 - w) * rho_dev + w * rho_ing
        beta_f = (1.0 - w) * beta + w * beta_e
        holdup = (1.0 - w) * holdup_dev + w * holdup_ing
    re_ls = RE_CONST * rho_ls * v_m * d_ft / mu_ls                                       # Eq. 66
    f_ls = friction_factor(re_ls, eps_d)
    friction = f_ls * rho_ls * v_m ** 2 / (2.0 * d_ft * GC) * (1.0 - beta_f)             # Eq. 65
    out.update({"rho_elev": rho_elev, "friction": friction, "f": f_ls, "re": re_ls, "holdup": holdup})
    return out


def ansari_gradient(p, angle_deg, d_in, roughness_in, c):
    """Ansari et al. (1994) pressure gradient (psi per ft of pipe), same inputs and same kind of result as
    beggs_brill_gradient.  The result has 'dpdl', 'hl' (liquid holdup of the pattern), 'regime' ('bubble',
    'dispersed', 'slug', 'annular', 'liquid' or 'gas'), 'hydrostatic', 'friction', 'f_tp', 're', 'e_k' (always 0:
    the paper has no acceleration term) and, for slug flow, 'beta' (Taylor bubble fraction of the slug unit) and
    'developing' (True while the Taylor bubble is still developing)."""
    _check(p > 0 and d_in > 0, "Pressure and diameter must be > 0.")
    d_ft = d_in / 12.0
    v_sl, v_sg = c["v_sl"], c["v_sg"]
    v_m = v_sl + v_sg
    _check(v_m > 0, "No flow: mixture velocity is zero.")
    theta = math.radians(angle_deg)
    sin_t = math.sin(theta)
    rho_l, rho_g, mu_l, mu_g = c["rho_l"], c["rho_g"], c["mu_l"], c["mu_g"]
    sigma = c["sigma"] * GRAY_SIGMA_UNIT                # lbm/s2
    eps_d = roughness_in / d_in
    extra = {}

    if v_sg < 1e-9 * v_m:                               # liquid only
        regime, hl = "liquid", 1.0
        rho, mu = rho_l, mu_l
        re = RE_CONST * rho * v_m * d_ft / mu
        f = friction_factor(re, eps_d)
        fric = f * rho * v_m ** 2 / (2.0 * d_ft * GC)
        extra = {"f": f, "re": re}
        hydro = rho * sin_t
    elif v_sl < 1e-9 * v_m:                             # gas only
        regime, hl = "gas", 0.0
        rho, mu = rho_g, mu_g
        re = RE_CONST * rho * v_m * d_ft / mu
        f = friction_factor(re, eps_d)
        fric = f * rho * v_m ** 2 / (2.0 * d_ft * GC)
        extra = {"f": f, "re": re}
        hydro = rho * sin_t
    else:
        fp = ans_flow_pattern(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta)
        regime = fp["regime"]
        if regime in ("bubble", "dispersed"):
            if regime == "bubble":
                v0 = (GC * sigma * (rho_l - rho_g) / rho_l ** 2) ** 0.25
                hl = _ans_bubble_holdup(v_sl, v_sg, v0)                                  # Eq. 22
            else:
                hl = v_sl / v_m                                                          # Eq. 19 (no slip)
            rho = rho_l * hl + rho_g * (1.0 - hl)                                        # Eqs. 16, 23
            mu = mu_l * hl + mu_g * (1.0 - hl)                                           # Eqs. 17, 24
            re = RE_CONST * rho * v_m * d_ft / mu                                        # Eq. 28
            f = friction_factor(re, eps_d)
            fric = f * rho * v_m ** 2 / (2.0 * d_ft * GC)                                # Eq. 27
            hydro = rho * sin_t                                                          # Eq. 26
            extra = {"f": f, "re": re}
        elif regime == "slug":
            sl = _ans_slug(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d)
            hl, fric, hydro = sl["holdup"], sl["friction"], sl["rho_elev"] * sin_t
            extra = {"f": sl["f"], "re": sl["re"], "beta": sl["beta"], "developing": sl["developing"]}
        else:
            an = fp.get("annular") or ans_annular_film_thickness(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta)
            hl, fric, hydro = an["holdup"], an["friction"], an["hydrostatic"]
            extra = {"f": an["f_sc"], "re": an["re_sc"], "delta": an["delta"]}
    return {"dpdl": (hydro + fric) / 144.0, "hl": hl, "regime": regime, "hydrostatic": hydro / 144.0,
            "friction": fric / 144.0, "f_tp": extra.get("f", 0.0), "re": extra.get("re", 0.0), "e_k": 0.0,
            "beta": extra.get("beta"), "developing": extra.get("developing"), "delta": extra.get("delta")}


# =====================================================================
# Duns & Ros (1963) - SPE/WPC "Vertical flow of gas and liquid mixtures in wells"
# =====================================================================
# Duns, H. Jr. and Ros, N.C.J., "Vertical Flow of Gas and Liquid Mixtures in Wells", Proc. 6th World Petroleum
# Congress, Frankfurt, 1963, Section II, Paper 22-PD6, p. 451.
#
# The pipe is described by four dimensionless numbers (the same ones Hagedorn & Brown use):
#     N   = N_LV, liquid velocity number          RN = N_GV, gas velocity number
#     N_d = pipe diameter number                  N_l = liquid viscosity number
# and three flow regions, each with its own slip velocity and its own wall friction:
#     Region I   (liquid continuous: bubble, plug and part of froth flow)   RN <= L1 + L2 N
#     Region II  (slug flow and the rest of froth flow)                     up to RN = 50 + 36 N
#     transition (between slug and mist)                                    50 + 36 N < RN < 75 + 84 N^0.75
#     Region III (gas continuous: mist flow, no slip)                       RN >= 75 + 84 N^0.75
# Slip velocity S (dimensionless) gives the liquid holdup, and with it the static gradient (Eq. 1).  The wall
# friction is added as a fraction of the liquid static gradient (Eq. 10 for Regions I-II, Eq. 12 for III).  In the
# transition the gradient is interpolated on RN between the two region boundaries, at a fixed gas mass flow
# (section VII).  The acceleration term (Eq. 17) is used in the mist and transition ranges only, as the paper says.
#
# THE PAPER'S FUNCTIONS ARE CHARTS.  F1 - F4 (Fig. 5), L1, L2 (Fig. 6), F5 - F7 (Fig. 7) and f2 (Fig. 9) were
# read from the scanned figures (axis-calibrated, curve traced and checked on an overlay) and are stored here as
# tables, interpolated on log(x).  Each value is good to roughly +-2 % of the chart's reading; the chart's own
# scatter of the fit to its data is the 3 / 8 / 6 % the paper quotes.  f1 (Fig. 8) is the Moody diagram, so the
# Colebrook equation is used (Fanning factor = Darcy factor / 4).  Fig. 10 is the Weber-number correlation that
# Orkiszewski copied as Eqs. C-21 / C-22.
#
# Not used: Eq. 18 for wet mixtures.  It needs the dry oil and the water properties separately, and the gradient
# interface carries one blended liquid (as for every other correlation here).  The paper itself restricts it to
# a water cut below 10 %.  The correlation is for vertical flow; for an inclined pipe the static gradient is
# multiplied by sin(angle) and the friction is unchanged.

# Fig. 5: functions of the liquid viscosity number N_l
DR_F1 = (
    [0.002, 0.002573, 0.00331, 0.004259, 0.005479, 0.007049, 0.009068, 0.01167, 0.01501, 0.01931, 0.02484, 0.03196, 0.04112, 0.0529, 0.06805, 0.08755, 0.1126, 0.1449, 0.1864, 0.2399, 0.3086, 0.397, 0.5107, 0.6571, 0.8453, 1.088, 1.399, 1.8],
    [1.253, 1.25, 1.245, 1.245, 1.245, 1.245, 1.241, 1.25, 1.259, 1.268, 1.293, 1.363, 1.483, 1.631, 1.782, 1.922, 2.011, 2.041, 2.041, 1.994, 1.894, 1.755, 1.612, 1.433, 1.255, 1.09, 0.9642, 0.8825])
DR_F2 = (
    [0.002, 0.002573, 0.00331, 0.004259, 0.005479, 0.007049, 0.009068, 0.01167, 0.01501, 0.01931, 0.02484, 0.03196, 0.04112, 0.0529, 0.06805, 0.08755, 0.1126, 0.1449, 0.1864, 0.2399, 0.3086, 0.397, 0.5107, 0.6571, 0.8453, 1.088, 1.399, 1.8],
    [0.2416, 0.2416, 0.2416, 0.2411, 0.2411, 0.2408, 0.2405, 0.2411, 0.246, 0.2667, 0.3046, 0.3777, 0.4709, 0.5807, 0.7116, 0.8472, 0.9499, 1.003, 1.015, 1.011, 0.9887, 0.9574, 0.9205, 0.881, 0.8393, 0.796, 0.7526, 0.7083])
DR_F3 = (
    [0.002, 0.002573, 0.00331, 0.004259, 0.005479, 0.007049, 0.009068, 0.01167, 0.01501, 0.01931, 0.02484, 0.03196, 0.04112, 0.0529, 0.06805, 0.08755, 0.1126, 0.1449, 0.1864, 0.2399, 0.3086, 0.397, 0.5107, 0.6571, 0.8453, 1.088, 1.399, 1.8],
    [0.822, 0.822, 0.8295, 0.8377, 0.8661, 0.9778, 1.124, 1.25, 1.481, 1.778, 2.05, 2.279, 2.511, 2.725, 2.924, 3.104, 3.253, 3.371, 3.525, 3.618, 3.693, 3.774, 3.849, 3.916, 3.981, 4.036, 4.082, 4.141])
DR_F4 = (
    [0.002, 0.002573, 0.00331, 0.004259, 0.005479, 0.007049, 0.009068, 0.01167, 0.01501, 0.01931, 0.02484, 0.03196, 0.04112, 0.0529, 0.06805, 0.08755, 0.1126, 0.1449, 0.1864, 0.2399, 0.3086, 0.397, 0.5107, 0.6571, 0.8453, 1.088, 1.399, 1.8],
    [-15.92, -8.31, -1.591, 4.567, 9.987, 15.76, 21.13, 26.25, 31.01, 35.75, 39.81, 44.17, 48.24, 51.08, 52.93, 53.88, 54.47, 54.85, 55.34, 55.44, 55.34, 55.05, 54.51, 54.76, 54.56, 54.56, 54.66, 54.76])
# Fig. 7: functions of the liquid viscosity number N_l (F6 is the part of F6' that does not depend on the diameter)
DR_F5 = (
    [0.002, 0.002578, 0.003324, 0.004284, 0.005523, 0.00712, 0.009178, 0.01183, 0.01525, 0.01966, 0.02534, 0.03267, 0.04212, 0.05429, 0.06999, 0.09022, 0.1163, 0.1499, 0.1933, 0.2492, 0.3212, 0.414, 0.5337, 0.688, 0.8869, 1.143, 1.474, 1.9],
    [0.2193, 0.2147, 0.21, 0.2026, 0.1996, 0.1948, 0.1892, 0.1837, 0.1777, 0.1708, 0.1634, 0.1535, 0.1368, 0.1154, 0.09169, 0.07099, 0.05695, 0.04407, 0.04446, 0.04928, 0.05517, 0.06179, 0.07018, 0.07862, 0.08727, 0.09618, 0.1047, 0.1123])
DR_F6 = (
    [0.002, 0.002578, 0.003324, 0.004284, 0.005523, 0.00712, 0.009178, 0.01183, 0.01525, 0.01966, 0.02534, 0.03267, 0.04212, 0.05429, 0.06999, 0.09022, 0.1163, 0.1499, 0.1933, 0.2492, 0.3212, 0.414, 0.5337, 0.688, 0.8869, 1.143, 1.474, 1.9],
    [0.829, 0.5999, 0.3948, 0.2387, 0.1101, 0.0102, -0.05731, -0.09881, -0.1158, -0.1206, 0.2942, 0.7332, 1.006, 1.322, 1.615, 2.039, 2.166, 2.1, 2, 1.918, 1.851, 1.808, 1.779, 1.765, 1.761, 1.763, 1.773, 1.779])
DR_F7 = (
    [0.002, 0.002578, 0.003324, 0.004284, 0.005523, 0.00712, 0.009178, 0.01183, 0.01525, 0.01966, 0.02534, 0.03267, 0.04212, 0.05429, 0.06999, 0.09022, 0.1163, 0.1499, 0.1933, 0.2492, 0.3212, 0.414, 0.5337, 0.688, 0.8869, 1.143, 1.474, 1.9],
    [0.1312, 0.1267, 0.1201, 0.1131, 0.1053, 0.09798, 0.09077, 0.08349, 0.07637, 0.07017, 0.06406, 0.06109, 0.05689, 0.05395, 0.05079, 0.04763, 0.04447, 0.04131, 0.03815, 0.03499, 0.03182, 0.02866, 0.02719, 0.02614, 0.02524, 0.02438, 0.02376, 0.02321])
# Fig. 6: limits of Region I, as functions of the diameter number N_d (RN <= L1 + L2 N)
DR_L1 = (
    [16, 18.27, 20.87, 23.83, 27.21, 31.08, 35.49, 40.53, 46.28, 52.85, 60.36, 68.92, 78.71, 89.89, 102.6, 117.2, 133.9, 152.9, 174.6, 199.4, 227.7, 260],
    [1.991, 1.991, 1.99, 1.987, 1.967, 1.907, 1.753, 1.571, 1.394, 1.213, 1.064, 1.006, 1, 1, 1, 1, 1, 1.01, 1.01, 1.01, 1.01, 1.01])
DR_L2 = (
    [16, 18.27, 20.87, 23.83, 27.21, 31.08, 35.49, 40.53, 46.28, 52.85, 60.36, 68.92, 78.71, 89.89, 102.6, 117.2, 133.9, 152.9, 174.6, 199.4, 227.7, 260],
    [0.4862, 0.5273, 0.5781, 0.6383, 0.7005, 0.7644, 0.8321, 0.904, 0.9704, 1.01, 1.052, 1.076, 1.087, 1.097, 1.103, 1.111, 1.114, 1.125, 1.121, 1.119, 1.114, 1.111])
# Fig. 9: friction factor f2 against f1 * R * N_d^(2/3), R = v_sg / v_sl
DR_FRICTION_F2 = (
    [0.0014, 0.002386, 0.004066, 0.00693, 0.01181, 0.02013, 0.0343, 0.05846, 0.09963, 0.1698, 0.2894, 0.4932, 0.8405, 1.432, 2.441, 4.161, 7.091, 12.08, 20.59, 35.1, 59.82, 101.9, 173.7, 296.1, 504.6, 860],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0.9757, 0.8045, 0.673, 0.5623, 0.4647, 0.3866, 0.3195, 0.2735, 0.2431, 0.2206, 0.2032, 0.2005, 0.2005, 0.201, 0.204])


def _dr_table(x, table):
    """Value of a tabulated chart curve at x: straight line in log(x) between the nodes, constant beyond the
    first and last node (the charts end there)."""
    xs, ys = table
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, x) - 1
    w = (math.log(x) - math.log(xs[i])) / (math.log(xs[i + 1]) - math.log(xs[i]))
    return ys[i] + w * (ys[i + 1] - ys[i])


def dr_numbers(v_sl, v_sg, rho_l, sigma, mu_l, d_ft):
    """The Duns & Ros dimensionless numbers (field units in, same constants as hagedorn_brown).
    Returns {"n", "rn", "n_d", "n_l", "f_v"}; f_v converts a velocity in ft/s into a velocity number."""
    f_v = 1.938 * (rho_l / sigma) ** 0.25
    return {"n": f_v * v_sl, "rn": f_v * v_sg,
            "n_d": 120.872 * d_ft * (rho_l / sigma) ** 0.5,
            "n_l": 0.15726 * mu_l * (1.0 / (rho_l * sigma ** 3)) ** 0.25,
            "f_v": f_v}


def dr_region_limits(n):
    """RN at the end of Region II (Eq. 7) and at the start of Region III (Eq. 9).  The end of Region I
    (L1 + L2 N, Eq. 5) also needs N_d and is found in dr_flow_region()."""
    return 50.0 + 36.0 * n, 75.0 + 84.0 * n ** 0.75


def dr_slip_region1(n, rn, n_d, n_l):
    """Dimensionless slip velocity of Region I (Eq. 4):  S = F1 + F2 N + F3' (RN / (1 + N))^2, F3' = F3 - F4 / N_d."""
    f3p = _dr_table(n_l, DR_F3) - _dr_table(n_l, DR_F4) / n_d
    return _dr_table(n_l, DR_F1) + _dr_table(n_l, DR_F2) * n + f3p * (rn / (1.0 + n)) ** 2


def dr_slip_region2(n, rn, n_d, n_l):
    """Dimensionless slip velocity of Region II (Eq. 6):  S = (1 + F5) (RN^0.982 + F6') / (1 + F7 N)^2,
    F6' = 0.029 N_d + F6."""
    f6p = 0.029 * n_d + _dr_table(n_l, DR_F6)
    return (1.0 + _dr_table(n_l, DR_F5)) * (rn ** 0.982 + f6p) / (1.0 + _dr_table(n_l, DR_F7) * n) ** 2


def dr_holdup(v_sl, v_sg, s, f_v):
    """Liquid holdup from the dimensionless slip S (Eqs. 2 and 3): v_s = S / f_v is the slip velocity
    v_sg/(1-H) - v_sl/H, solved for H.  S below zero (liquid faster than gas) is not possible upward and is taken as 0."""
    v_s = max(s, 0.0) / f_v
    # v_sg/(1-H) - v_sl/H = v_s  ->  v_s H^2 - (v_s - v_sg - v_sl) H - v_sl = 0, written so that v_s = 0 is allowed
    b = v_s - v_sg - v_sl
    return 2.0 * v_sl / (-b + math.sqrt(b * b + 4.0 * v_s * v_sl))


def _dr_fanning(re, eps_d):
    """Fanning friction factor of Fig. 8: Colebrook / 4, and Eq. 15 for a relative roughness above 0.05 (the Moody
    diagram stops there)."""
    if eps_d > 0.05 and re >= 4000.0:
        return 1.0 / (4.0 * math.log10(0.27 * eps_d)) ** 2 + 0.067 * eps_d ** 1.73
    return friction_factor(re, eps_d) / 4.0


def dr_mist_film_roughness(v_sg, rho_g, rho_l, mu_l, sigma_dyne, d_ft, pipe_eps_d):
    """Relative roughness e/D of the liquid film on the wall in mist flow (Eq. 14 and Fig. 10).
    Weber number We = rho_g v_sg^2 e / sigma is 34, or higher for a viscous liquid (We = 174.8 X^0.302 with
    X = rho_g v_sg^2 mu_L^2 / (rho_L sigma^2) above X = 0.0044 - the form Orkiszewski copied as Eqs. C-21 / C-22).
    The result is kept between the pipe's own roughness (at least 0.001) and 0.5 (liquid bridges)."""
    sigma = sigma_dyne * GRAY_SIGMA_UNIT                                   # lbm/s2
    x = 4.52e-7 * (v_sg * mu_l / sigma) ** 2 * rho_g / rho_l               # 4.52e-7 turns cP into lbm/ft/s squared
    we = max(34.0, 174.8 * x ** 0.302) if x > 0.0 else 34.0
    e_d = we * sigma / (rho_g * v_sg ** 2 * d_ft)
    return min(max(e_d, 0.001, pipe_eps_d), 0.5), we


def _dr_gradient_parts(region, v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, pipe_eps_d):
    """Holdup, static gradient and friction gradient of one region, both as fractions of the liquid static gradient
    (G_st, G_fr).  region = 1, 2 or 3.  Returns (holdup, G_st, G_fr, f used, Reynolds number used)."""
    nm = dr_numbers(v_sl, v_sg, rho_l, sigma, mu_l, d_ft)
    n, rn, n_d, n_l = nm["n"], nm["rn"], nm["n_d"], nm["n_l"]
    if region == 3:
        h = v_sl / (v_sl + v_sg)                                            # Eq. 8: no slip
        eps_d, _ = dr_mist_film_roughness(v_sg, rho_g, rho_l, mu_l, sigma, d_ft, pipe_eps_d)
        re = RE_CONST * rho_g * v_sg * d_ft / mu_g
        f1 = _dr_fanning(re, eps_d)
        g_fr = 2.0 * f1 * (rho_g / rho_l) * rn ** 2 / n_d                     # Eq. 12
        f_used = f1
    else:
        s = dr_slip_region1(n, rn, n_d, n_l) if region == 1 else dr_slip_region2(n, rn, n_d, n_l)
        h = dr_holdup(v_sl, v_sg, s, nm["f_v"])
        re = RE_CONST * rho_l * v_sl * d_ft / mu_l                          # liquid Reynolds number
        f1 = _dr_fanning(re, pipe_eps_d)
        r = v_sg / v_sl
        f2 = _dr_table(f1 * r * n_d ** (2.0 / 3.0), DR_FRICTION_F2)
        f3 = 1.0 + f1 * math.sqrt(r / 50.0)
        f_used = f1 * f2 / f3                                               # Eq. 11
        g_fr = 2.0 * f_used * n * (n + rn) / n_d                            # Eq. 10
    g_st = h + (1.0 - h) * rho_g / rho_l                                    # Eq. 1
    return h, g_st, g_fr, f_used, re


def dr_flow_region(v_sl, v_sg, rho_l, sigma, mu_l, d_ft):
    """Region of the Duns & Ros correlation: 'bubble' (Region I), 'slug' (Region II), 'transition' or 'mist'
    (Region III).  Returns {"regime", "n", "rn", "n_d", "n_l", "rn_1" (end of I), "rn_2" (end of II),
    "rn_3" (start of III), "f_v"}."""
    nm = dr_numbers(v_sl, v_sg, rho_l, sigma, mu_l, d_ft)
    rn_1 = _dr_table(nm["n_d"], DR_L1) + _dr_table(nm["n_d"], DR_L2) * nm["n"]       # Eq. 5
    rn_2, rn_3 = dr_region_limits(nm["n"])
    if nm["rn"] <= rn_1:
        regime = "bubble"
    elif nm["rn"] <= rn_2:
        regime = "slug"
    elif nm["rn"] < rn_3:
        regime = "transition"
    else:
        regime = "mist"
    nm.update({"regime": regime, "rn_1": rn_1, "rn_2": rn_2, "rn_3": rn_3})
    return nm


def duns_ros_gradient(p, angle_deg, d_in, roughness_in, c):
    """Duns & Ros pressure gradient (psi per ft of pipe), same inputs and same kind of result as
    beggs_brill_gradient (see there for the meaning of the inputs).

    The returned dictionary has 'dpdl', 'hl' (liquid holdup), 'regime' ('bubble' = Region I, 'slug' = Region II,
    'transition', 'mist' = Region III or 'gas'), 'hydrostatic', 'friction', 'f_tp' (the paper's f_w, or f1 in mist
    flow), 're' (the Reynolds number that f1 was read at), 'e_k' (the acceleration term of Eq. 17, only in the
    transition and mist ranges) and 'rn' / 'n' (the velocity numbers)."""
    _check(p > 0 and d_in > 0, "Pressure and diameter must be > 0.")
    d_ft = d_in / 12.0
    v_sl, v_sg = c["v_sl"], c["v_sg"]
    _check(v_sl + v_sg > 0, "No flow: mixture velocity is zero.")
    sin_t = math.sin(math.radians(angle_deg))
    rho_l, rho_g, mu_l, mu_g, sigma = c["rho_l"], c["rho_g"], c["mu_l"], c["mu_g"], c["sigma"]
    pipe_eps_d = roughness_in / d_in
    mass_flux = rho_l * v_sl + rho_g * v_sg                                   # lb/s/ft2

    if v_sl < 1e-9 * (v_sl + v_sg):                                           # no liquid: single-phase gas
        re = RE_CONST * rho_g * v_sg * d_ft / mu_g
        f = friction_factor(re, pipe_eps_d)
        hydrostatic = rho_g * sin_t / 144.0
        friction = f * rho_g * v_sg ** 2 / (2.0 * GC * d_ft) / 144.0
        e_k = min(mass_flux * v_sg / (GC * p * 144.0), 0.95)
        return {"dpdl": (hydrostatic + friction) / (1.0 - e_k), "hl": 0.0, "regime": "gas",
                "hydrostatic": hydrostatic, "friction": friction, "f_tp": f, "re": re, "e_k": e_k,
                "rn": 1.938 * v_sg * (rho_l / sigma) ** 0.25, "n": 0.0}

    fp = dr_flow_region(v_sl, v_sg, rho_l, sigma, mu_l, d_ft)
    regime = fp["regime"]
    args = (rho_l, rho_g, mu_l, mu_g, sigma, d_ft, pipe_eps_d)
    if regime in ("bubble", "slug", "mist"):
        region = {"bubble": 1, "slug": 2, "mist": 3}[regime]
        h, g_st, g_fr, f_used, re = _dr_gradient_parts(region, v_sl, v_sg, *args)
    else:
        # Transition: linear in RN between the end of Region II and the start of Region III (section VII).
        # The mist end is evaluated at the gas velocity of that RN with the gas density that keeps rho_g v_sg fixed.
        v_sg_2 = fp["rn_2"] / fp["f_v"]
        v_sg_3 = fp["rn_3"] / fp["f_v"]
        args_3 = (rho_l, rho_g * v_sg / v_sg_3, mu_l, mu_g, sigma, d_ft, pipe_eps_d)
        h2, st2, fr2, f_used, re = _dr_gradient_parts(2, v_sl, v_sg_2, *args)
        h3, st3, fr3, _, _ = _dr_gradient_parts(3, v_sl, v_sg_3, *args_3)
        w3 = (fp["rn"] - fp["rn_2"]) / (fp["rn_3"] - fp["rn_2"])             # weight of the mist end
        h = (1.0 - w3) * h2 + w3 * h3
        g_st = (1.0 - w3) * st2 + w3 * st3
        g_fr = (1.0 - w3) * fr2 + w3 * fr3

    hydrostatic = g_st * rho_l * sin_t / 144.0                              # G = (dp/dh) / (rho_L g), g / gc = 1
    friction = g_fr * rho_l / 144.0
    e_k = 0.0
    if regime in ("transition", "mist"):
        e_k = min(mass_flux * v_sg / (GC * p * 144.0), 0.95)               # Eq. 17
    return {"dpdl": (hydrostatic + friction) / (1.0 - e_k), "hl": h, "regime": regime,
            "hydrostatic": hydrostatic, "friction": friction, "f_tp": f_used, "re": re, "e_k": e_k,
            "rn": fp["rn"], "n": fp["n"]}


# =====================================================================
# Mukherjee & Brill (1983 / 1985) - liquid holdup and pressure drop for inclined two-phase flow
# =====================================================================
# Mukherjee, H. and Brill, J.P., "Liquid Holdup Correlations for Inclined Two-Phase Flow", J. Pet. Tech., May 1983,
# p. 1003 (SPE 10923).  This paper gives the HOLDUP equation (Eq. 1) and its coefficients (Table 1):
#     H_L = exp[ (c1 + c2 sin(a) + c3 sin(a)^2 + c4 N_L^2) * N_gv^c5 / N_Lv^c6 ]
# with one set of c1 ... c6 for uphill and horizontal flow (all flow patterns), one for downhill stratified flow and
# one for the other downhill patterns.  N_Lv, N_gv and N_L are the same dimensionless numbers as in Duns & Ros and
# Hagedorn & Brown.
#
# The flow-pattern map and the friction method are from the two companion papers (both read for this code):
#   Mukherjee, H. and Brill, J.P., "Empirical Equations to Predict Flow Patterns in Two-Phase Inclined Flow",
#       Int. J. Multiphase Flow 11 (3), 1985, p. 299: Eqs. [1]-[4] and the flow chart of its Fig. 16;
#   Mukherjee, H. and Brill, J.P., "Pressure Drop Correlations for Inclined Two-Phase Flow", J. Energy Resources
#       Technology 107, Dec. 1985, p. 549: Eqs. (1)-(27), Table 2 and the calculation steps.
# (Fig. 16, followed from the top: N_gv > N_gv(SM) is annular-mist; then UPHILL (angle > 0) is bubble above N_Lv(BS) and
# slug below it.  Downhill AND HORIZONTAL (angle <= 0) go on to the steepness test.)
#
#     flow pattern   uphill (angle > 0)              downhill and horizontal (angle <= 0)
#     annular-mist   N_gv > N_gv(SM)                N_gv > N_gv(SM)
#     bubble         N_Lv > N_Lv(BS)               N_gv <= N_gv(BS)   (and, for |angle| <= 30, N_Lv > N_Lv(ST))
#     stratified     (none)                         N_Lv <= N_Lv(ST)   (steeper than 30 degrees: N_gv > N_gv(BS) too)
#     slug           the rest                       the rest
#
#     friction       bubble, slug : Moody factor at the no-slip Reynolds number, applied to the slip density (Eq. 14)
#                    annular-mist : the same factor times f_R(H_R), H_R = no-slip holdup / holdup (Table 2), applied to the
#                                   no-slip density (steps 1-6 of the paper)
#                    stratified   : Eq. 15, the momentum balance of the gas phase on a flat interface: the gas wall shear
#                                   over its wetted wall, plus the weight of the gas column.  The paper's "smooth
#                                   interface" has no interfacial shear formula, so it is neglected.  No acceleration.
#
# Printed Eqs. 26-27 write the wall shear as f*gamma*v^2/(2g) with a MOODY factor f, which is four times the usual
# f*rho*v^2/8 (the Fanning shear); the Darcy-Weisbach pressure drop of Eq. 2 only comes out right with the /8 form,
# so that is what is coded here.
# For the acceleration term the paper gives E_k = gamma_m v_m v_sg / (g p) (Eq. 1 with the stratified exception).

# (c1 ... c6) of Table 1
MB_COEFFICIENTS = {
    "uphill": (-0.380113, 0.129875, -0.119788, 2.343227, 0.475686, 0.288657),
    "downhill_stratified": (-1.330282, 4.808139, 4.171584, 56.262268, 0.079951, 0.504887),
    "downhill_other": (-0.516644, 0.789805, 0.551627, 15.519214, 0.371771, 0.393952),
}

# Annular-mist friction ratio f_R against H_R = (no-slip holdup) / (holdup)  (1985 paper, tabulated)
MB_FRICTION_RATIO = ([0.01, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0, 10.0],
                     [1.00, 0.98, 1.20, 1.25, 1.30, 1.25, 1.00, 1.00])


def mb_numbers(v_sl, v_sg, rho_l, sigma, mu_l):
    """Liquid velocity number N_Lv, gas velocity number N_gv and liquid viscosity number N_L (field units)."""
    f_v = 1.938 * (rho_l / sigma) ** 0.25
    return {"n_lv": f_v * v_sl, "n_gv": f_v * v_sg,
            "n_l": 0.15726 * mu_l * (1.0 / (rho_l * sigma ** 3)) ** 0.25}


def mb_flow_pattern(n_lv, n_gv, n_l, angle_deg):
    """Flow pattern of the Mukherjee & Brill map (Fig. 16 of the flow-pattern paper): 'annular', 'bubble', 'slug' or
    'stratified' (downhill or horizontal only).
    Needs N_lv > 0 and N_gv > 0.  Returns {"regime", "n_gv_sm" (slug / annular-mist), "n_lv_bs" (uphill bubble / slug),
    "n_gv_bs" (downhill and horizontal bubble / slug), "n_lv_st" (downhill and horizontal stratified)}; boundaries that
    do not apply are None."""
    sin_a = math.sin(math.radians(angle_deg))
    n_gv_sm = 10.0 ** (1.401 - 2.694 * n_l + 0.521 * n_lv ** 0.329)
    out = {"n_gv_sm": n_gv_sm, "n_lv_bs": None, "n_gv_bs": None, "n_lv_st": None}
    if angle_deg > 0.0:                                           # uphill only; horizontal follows the downhill branch
        out["n_lv_bs"] = 10.0 ** (math.log10(n_gv) + 0.940 + 0.074 * sin_a - 0.855 * sin_a ** 2 + 3.695 * n_l)
    else:
        log_lv = math.log10(n_lv)
        out["n_gv_bs"] = 10.0 ** (0.431 - 3.003 * n_l - 1.138 * log_lv * sin_a - 0.429 * log_lv ** 2 * sin_a + 1.132 * sin_a)
        out["n_lv_st"] = 10.0 ** (0.321 - 0.017 * n_gv - 4.267 * sin_a - 2.972 * n_l
                                  - 0.033 * math.log10(n_gv) ** 2 - 3.925 * sin_a ** 2)
    if n_gv > n_gv_sm:
        regime = "annular"
    elif angle_deg > 0.0:
        regime = "bubble" if n_lv > out["n_lv_bs"] else "slug"
    elif abs(angle_deg) > 30.0:
        if n_gv > out["n_gv_bs"]:
            regime = "slug" if n_lv > out["n_lv_st"] else "stratified"
        else:
            regime = "bubble"
    else:
        if n_lv > out["n_lv_st"]:
            regime = "slug" if n_gv > out["n_gv_bs"] else "bubble"
        else:
            regime = "stratified"
    out["regime"] = regime
    return out


def mb_holdup(n_lv, n_gv, n_l, angle_deg, regime):
    """Liquid holdup of Mukherjee & Brill, Eq. 1 with the coefficients of Table 1 (kept between 0 and 1).
    regime is only needed for downhill flow (stratified or not)."""
    if angle_deg >= 0.0:
        c = MB_COEFFICIENTS["uphill"]
    else:
        c = MB_COEFFICIENTS["downhill_stratified" if regime == "stratified" else "downhill_other"]
    sin_a = math.sin(math.radians(angle_deg))
    t1 = c[0] + c[1] * sin_a + c[2] * sin_a ** 2 + c[3] * n_l ** 2
    x = t1 * n_gv ** c[4] / n_lv ** c[5]
    return 1.0 if x >= 0.0 else math.exp(max(x, -700.0))                # a positive exponent would give H_L > 1


def mb_stratified_angle(h_l):
    """Angle delta (radians, 0 to 2 pi) of the liquid-wetted part of the wall for a flat liquid layer of holdup H_L:
    (delta - sin delta) / (2 pi) = H_L, found by halving the interval."""
    lo, hi = 0.0, 2.0 * math.pi
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if (mid - math.sin(mid)) / (2.0 * math.pi) < h_l:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def mb_stratified_friction(h_l, v_sg, rho_g, mu_g, d_ft, eps_d):
    """Friction gradient (lbf/ft2 per ft) of stratified flow, Eq. 15 of the 1985 pressure-drop paper with the interface
    shear neglected (smooth interface): the wall shear of the gas over its wetted wall, divided by the area of the gas.
        friction = tau_wg * P_g / A_g,     tau_wg = f_g * rho_g * v_g^2 / (8 g_c)
    The gas runs at v_g = v_sg / (1 - H_L) and its Reynolds number uses the hydraulic diameter D_Eg of Eq. 25.
    Returns (friction, extras)."""
    h = min(max(h_l, 1e-6), 1.0 - 1e-6)
    delta = mb_stratified_angle(h)                                            # Eq. 20, solved for delta
    d_eg = d_ft * (2.0 * math.pi - (delta - math.sin(delta))) / (2.0 * math.pi - delta + 2.0 * math.sin(0.5 * delta))   # Eq. 25
    v_g = v_sg / (1.0 - h)
    re_g = RE_CONST * rho_g * v_g * d_eg / mu_g
    f_g = friction_factor(re_g, eps_d)
    tau_g = f_g * rho_g * v_g ** 2 / (8.0 * GC)
    perimeter = math.pi * d_ft
    p_g = (1.0 - delta / (2.0 * math.pi)) * perimeter                         # Eq. 23
    a_g = (1.0 - h) * math.pi * d_ft ** 2 / 4.0                               # Eq. 21
    return tau_g * p_g / a_g, {"f": f_g, "re": re_g, "delta": delta}


def mukherjee_brill_gradient(p, angle_deg, d_in, roughness_in, c):
    """Mukherjee & Brill pressure gradient (psi per ft of pipe), same inputs and same kind of result as
    beggs_brill_gradient (see there for the meaning of the inputs).  Works for any angle: uphill, horizontal
    and downhill.

    The returned dictionary has 'dpdl', 'hl', 'regime' ('bubble', 'slug', 'annular', 'stratified', or 'liquid' / 'gas'
    for one phase only), 'hydrostatic', 'friction', 'f_tp' (the Moody friction factor used), 're' (its Reynolds number),
    'e_k' (acceleration term), and 'n_lv', 'n_gv', 'n_l'."""
    _check(p > 0 and d_in > 0, "Pressure and diameter must be > 0.")
    d_ft = d_in / 12.0
    v_sl, v_sg = c["v_sl"], c["v_sg"]
    v_m = v_sl + v_sg
    _check(v_m > 0, "No flow: mixture velocity is zero.")
    sin_a = math.sin(math.radians(angle_deg))
    rho_l, rho_g, mu_l, mu_g, sigma = c["rho_l"], c["rho_g"], c["mu_l"], c["mu_g"], c["sigma"]
    eps_d = roughness_in / d_in
    nm = mb_numbers(v_sl, v_sg, rho_l, sigma, mu_l)

    if v_sl < 1e-9 * v_m or v_sg < 1e-9 * v_m:                     # one phase only
        gas = v_sl < 1e-9 * v_m
        rho, mu, v = (rho_g, mu_g, v_sg) if gas else (rho_l, mu_l, v_sl)
        re = RE_CONST * rho * v * d_ft / mu
        f = friction_factor(re, eps_d)
        hydrostatic = rho * sin_a / 144.0
        friction = f * rho * v ** 2 / (2.0 * GC * d_ft) / 144.0
        e_k = min(rho * v * v / (GC * p * 144.0), 0.95) if gas else 0.0
        return {"dpdl": (hydrostatic + friction) / (1.0 - e_k), "hl": 0.0 if gas else 1.0,
                "regime": "gas" if gas else "liquid", "hydrostatic": hydrostatic, "friction": friction,
                "f_tp": f, "re": re, "e_k": e_k, **nm}

    fp = mb_flow_pattern(nm["n_lv"], nm["n_gv"], nm["n_l"], angle_deg)
    regime = fp["regime"]
    h_l = mb_holdup(nm["n_lv"], nm["n_gv"], nm["n_l"], angle_deg, regime)
    lam = v_sl / v_m                                                # no-slip holdup
    rho_s = h_l * rho_l + (1.0 - h_l) * rho_g                       # slip (holdup) density
    rho_ns = lam * rho_l + (1.0 - lam) * rho_g
    mu_ns = lam * mu_l + (1.0 - lam) * mu_g
    re_ns = RE_CONST * rho_ns * v_m * d_ft / mu_ns
    if regime == "stratified":
        friction, extra = mb_stratified_friction(h_l, v_sg, rho_g, mu_g, d_ft, eps_d)
        f_used, re_used = extra["f"], extra["re"]
        rho_s = rho_g                                               # Eq. 15: the weight of the gas column only
    else:
        f_ns = friction_factor(re_ns, eps_d)
        if regime == "annular":
            xs, ys = MB_FRICTION_RATIO
            h_r = min(max(lam / max(h_l, 1e-9), xs[0]), xs[-1])
            i = max(bisect.bisect_right(xs, h_r) - 1, 0)
            i = min(i, len(xs) - 2)
            f_r = ys[i] + (ys[i + 1] - ys[i]) * (h_r - xs[i]) / (xs[i + 1] - xs[i])   # f_R, straight line in H_R
            f_used = f_ns * f_r
            friction = f_used * rho_ns * v_m ** 2 / (2.0 * GC * d_ft)
        else:
            f_used = f_ns
            friction = f_ns * rho_s * v_m ** 2 / (2.0 * GC * d_ft)
        re_used = re_ns
    hydrostatic = rho_s * sin_a / 144.0
    friction = friction / 144.0
    e_k = 0.0 if regime == "stratified" else min(rho_s * v_m * v_sg / (GC * p * 144.0), 0.95)    # no acceleration in stratified flow
    return {"dpdl": (hydrostatic + friction) / (1.0 - e_k), "hl": h_l, "regime": regime, "hydrostatic": hydrostatic,
            "friction": friction, "f_tp": f_used, "re": re_used, "e_k": e_k, **nm}


# =====================================================================
# Fluids: turn (rate, pressure, temperature) into velocities and fluid properties
# =====================================================================
# Each fluid class has two methods used by the traverse:
#     conditions(rate, p, T, d_in)  -> dict of velocities, densities, viscosities, sigma
#     thermal_data(rate)            -> (mass rate lb/h, heat capacity) for the temperature profile

def _pipe_area(d_in):
    """Cross-section area (ft2) of a pipe of inner diameter d_in (inches)."""
    return math.pi * (d_in / 12.0) ** 2 / 4.0


def _water_density_sc(salinity):
    """Water density (lb/ft3) at about standard conditions."""
    return pvt.water_properties(14.7, 60.0, salinity)["rho_w"]


@dataclass
class OilWaterFluid:
    api: float                    # stock-tank oil gravity (API)
    gas_sg: float                 # gas gravity (air = 1)
    rsb: float                    # solution GOR at the bubble point (scf/STB)
    water_cut: float = 0.0        # water fraction of the liquid rate, 0 - 1
    gor: float = None             # producing GOR (scf/STB); None = same as rsb
    salinity: float = 3.0         # water salinity (wt %)
    pb_meas: float = None         # measured bubble point (psia), optional
    pvt_method: str = "glaso"     # Pb, Rs, Bo correlation (see pvt.py)
    visc_method: str = "beal"     # oil viscosity correlation (see pvt.py)
    pvt_match: dict = None        # numbers from PVT matching to lab data (see pvt_match.py), optional
    # Continuous gas lift: gas injected into the tubing at one depth (0 = no gas lift)
    injection_gas_rate: float = 0.0     # injected gas, Mscf/d
    injection_md: float = None          # depth of the injection point (valve / orifice), ft measured depth
    injection_gas_sg: float = None      # gravity of the injected gas (air = 1); None = same as gas_sg

    def __post_init__(self):
        _check(0.0 <= self.water_cut <= 1.0, "Water cut must be between 0 and 1.")
        _check(self.injection_gas_rate >= 0.0, "The gas injection rate cannot be negative.")
        _check(self.injection_gas_rate == 0.0 or (self.injection_md is not None and self.injection_md > 0.0),
               "Gas lift needs an injection depth above the perforations (greater than 0).")
        _check(self.api > 0 and self.gas_sg > 0 and self.rsb > 0, "api, gas_sg and rsb must be > 0.")

    def _gor(self):
        return self.gor if self.gor is not None else self.rsb

    def injected_gas_sg(self):
        return self.injection_gas_sg if self.injection_gas_sg is not None else self.gas_sg

    def conditions(self, rate, p, T, d_in, inj_scfd=0.0):
        """Flow conditions at pressure p, temperature T, for a liquid rate (STB/d).
        inj_scfd : gas lift gas (scf/d) that has already joined the flow at this point (0 below the injection point)."""
        _check(rate > 0, "Rate must be > 0.")
        q_o = rate * (1.0 - self.water_cut)
        q_w = rate * self.water_cut
        o = pvt.oil_properties(p, T, self.api, self.gas_sg, self.rsb, self.pb_meas,
                               self.pvt_method, self.visc_method, self.pvt_match)
        w = pvt.water_properties(p, T, self.salinity)
        g = pvt.gas_properties(p, T, self.gas_sg)

        free_gor = max(self._gor() - o["rs"], 0.0)               # gas that is NOT dissolved
        vol_o = q_o * o["bo"] * 5.615                            # ft3/d at pressure p
        vol_w = q_w * w["bw"] * 5.615
        vol_g = q_o * free_gor * g["bg"]
        rho_gas, mu_gas = g["rho_g"], g["mu_g"]
        if inj_scfd > 0.0:
            # Gas lift gas joins the formation gas.  Its volume at p and T comes from its own gravity;
            # density and viscosity of the gas mixture are the volume-weighted averages of the two gases.
            gi = pvt.gas_properties(p, T, self.injected_gas_sg())
            vol_i = inj_scfd * gi["bg"]
            vol_total = vol_g + vol_i
            rho_gas = (vol_g * g["rho_g"] + vol_i * gi["rho_g"]) / vol_total
            mu_gas = (vol_g * g["mu_g"] + vol_i * gi["mu_g"]) / vol_total
            vol_g = vol_total
        area = _pipe_area(d_in)
        frac_o = vol_o / (vol_o + vol_w)                         # oil share of the liquid volume

        sigma_o = sigma_oil_gas(self.api, T, p)
        sigma_w = sigma_water_gas(T, p)
        return {
            "v_sl": (vol_o + vol_w) / area / 86400.0,
            "v_sg": vol_g / area / 86400.0,
            "rho_l": frac_o * o["rho_o"] + (1.0 - frac_o) * w["rho_w"],
            "rho_g": rho_gas,
            "mu_l": frac_o * o["mu_o"] + (1.0 - frac_o) * w["mu_w"],
            "mu_g": mu_gas,
            "sigma": frac_o * sigma_o + (1.0 - frac_o) * sigma_w,
            "frac_w": 1.0 - frac_o,                              # water share of the liquid volume (Orkiszewski)
            # producing gas-liquid ratio, scf per STB of liquid: all the gas at the surface (dissolved + free + injected)
            "glr": (q_o * self._gor() + inj_scfd) / rate,        # (Fancher and Brown)
        }

    def thermal_data(self, rate):
        """(total mass rate in lb/h, mixture heat capacity in Btu/lb/degF)."""
        q_o = rate * (1.0 - self.water_cut)
        q_w = rate * self.water_cut
        m_o = q_o * 350.0 * 141.5 / (self.api + 131.5)           # lb/d (350 lb per bbl of water)
        m_w = q_w * 5.615 * _water_density_sc(self.salinity)
        m_g = q_o * self._gor() * GAS_RHO_SC * self.gas_sg
        total = m_o + m_w + m_g
        cp = (OIL_CP * m_o + WATER_CP * m_w + GAS_CP * m_g) / total
        return total / 24.0, cp


    def injected_thermal(self):
        """(mass rate in lb/h, heat capacity in Btu/lb/degF) of the gas lift gas."""
        return self.injection_gas_rate * 1000.0 * GAS_RHO_SC * self.injected_gas_sg() / 24.0, GAS_CP


@dataclass
class GasFluid:
    gas_sg: float                 # gas gravity (air = 1); for a wet gas use the well-stream gravity
    cgr: float = 0.0              # condensate-gas ratio (STB/MMscf)
    cond_api: float = 50.0        # condensate gravity (API)
    wgr: float = 0.0              # water-gas ratio (STB/MMscf)
    salinity: float = 3.0         # water salinity (wt %)
    y_h2s: float = 0.0            # H2S mole fraction (0 - 1)
    y_co2: float = 0.0            # CO2 mole fraction (0 - 1)
    visc_method: str = "lee"      # gas viscosity: 'lee' or 'carr'
    gas_sg_dry: float = 0.0       # separator (dry) gas gravity; when > 0 the well-stream gravity is recalculated if the
                                  # CGR changes (commingled layers).  0 = gas_sg is kept as it is

    def __post_init__(self):
        _check(self.gas_sg > 0, "Gas gravity must be > 0.")
        _check(self.cgr >= 0 and self.wgr >= 0, "CGR and WGR cannot be negative.")

    def conditions(self, rate, p, T, d_in):
        """Flow conditions for a gas rate (Mscf/d) at pressure p and temperature T."""
        _check(rate > 0, "Rate must be > 0.")
        g = pvt.gas_properties(p, T, self.gas_sg, self.y_h2s, self.y_co2, self.visc_method)
        area = _pipe_area(d_in)
        vol_g = rate * 1000.0 * g["bg"]                          # ft3/d at pressure p

        q_c = rate * self.cgr / 1000.0                           # condensate, STB/d
        q_w = rate * self.wgr / 1000.0                           # water, STB/d
        w = pvt.water_properties(p, T, self.salinity)
        vol_c = q_c * 5.615                                      # condensate Bo taken as 1
        vol_w = q_w * w["bw"] * 5.615
        vol_l = vol_c + vol_w

        if vol_l <= 0:                                           # dry gas: liquid values are not used
            rho_l, mu_l, sigma = 62.4, 1.0, 50.0
        else:
            frac_c = vol_c / vol_l
            rho_c = 350.0 * 141.5 / (self.cond_api + 131.5) / 5.615
            rho_l = frac_c * rho_c + (1.0 - frac_c) * w["rho_w"]
            mu_l = frac_c * pvt.mu_dead_beal(self.cond_api, T) + (1.0 - frac_c) * w["mu_w"]
            sigma = (frac_c * sigma_oil_gas(self.cond_api, T, p)
                     + (1.0 - frac_c) * sigma_water_gas(T, p))
        return {
            "v_sl": vol_l / area / 86400.0,
            "v_sg": vol_g / area / 86400.0,
            "rho_l": rho_l, "rho_g": g["rho_g"],
            "mu_l": mu_l, "mu_g": g["mu_g"],
            "sigma": sigma,
            "frac_w": 0.0 if vol_l <= 0 else vol_w / vol_l,
            "glr": 1.0e6 / (self.cgr + self.wgr) if (self.cgr + self.wgr) > 0 else 1.0e9,    # scf per STB of liquid
        }

    def thermal_data(self, rate):
        """(total mass rate in lb/h, mixture heat capacity in Btu/lb/degF)."""
        m_g = rate * 1000.0 * GAS_RHO_SC * self.gas_sg
        m_c = rate * self.cgr / 1000.0 * 350.0 * 141.5 / (self.cond_api + 131.5)
        m_w = rate * self.wgr / 1000.0 * 5.615 * _water_density_sc(self.salinity)
        total = m_g + m_c + m_w
        cp = (GAS_CP * m_g + OIL_CP * m_c + WATER_CP * m_w) / total
        return total / 24.0, cp


# =====================================================================
# Fancher & Brown (1963) - no-slip pressure gradient for flow in tubing
# =====================================================================
# Source: Fancher, G.H. and Brown, K.E., "Prediction of Pressure Gradients for Multiphase Flow in Tubing",
#         SPE Journal, March 1963, p. 59 (SPE 440-PA), Eqs. (1)-(2) and Figs. 5-9.
#
# It is Poettmann and Carpenter's energy-balance method: the gas and the liquid are treated as one fluid with the
# NO-SLIP density, and all the losses (wall friction and the slip that really happens) are put into one Fanning
# friction factor.  Fancher and Brown measured their own factors in an 8,000 ft test well (2 3/8 in tubing, 75 - 936
# B/D, producing gas-liquid ratio 105 - 9,433 scf/bbl) and found that the factor depends on the producing GAS-LIQUID
# RATIO as well as on the numerator of the Reynolds number, so the paper gives one line for each of three ranges:
#
#     dp/dH = [ rho + f q^2 M^2 / (7.413e10 rho d^5) ] / 144                     (psi/ft; Eq. 2)
#     N = 1.4737e-5 q M / d  (= rho v d, the numerator of the Reynolds number; q M is the mass rate in lb/day)
#     f = Fanning friction factor read from Fig. 7 (GLR < 1500 scf/bbl), Fig. 8 (1500 - 3000) or Fig. 9 (> 3000)
#
# The factor is a function of N and the GLR only: the viscosity, the pipe roughness and the angle are not in it
# (the paper found viscous shear negligible).  There is no acceleration term.
#
# How it is meant to be used: because it ignores slip it gives the LOWEST possible VLP, so it belongs in the
# correlation comparison as a quality check - a measured flowing pressure to the left of it means the PVT or the
# pressure data are wrong - and not in a real calculation.  That is how the app labels it.
#
# The lines are chart readings (digitised from the paper's figures, about +/- 3 %).  Fig. 7 is a curve (steep below
# N = 6 and straight on the log-log paper above); Figs. 8 and 9 are straight lines.  The lines are drawn in the paper for
# N = 3.4 - 35 (GLR < 1500), 4.7 - 27 (1500 - 3000) and 3.7 - 15 (> 3000).  The comparison chart (Fig. 6) carries
# the lines further, to N = 70, 35 and 23, so each line is continued to there; beyond that the factor is held at its value
# at the end (a straight line for ever would give a friction factor far below a smooth pipe's), and below the start of
# the drawn line it is held too (the friction term is tiny at such a low mass rate anyway).
FB_GLR_LIMITS = (1500.0, 3000.0)           # scf per STB of liquid: where the paper changes from one line to the next
FB_N_MAX = {"low": 70.0, "mid": 35.0, "high": 23.0}     # the factor is held constant above this N (end of the lines in Fig. 6)

# (N, f) points of the three lines; between two points the factor is a straight line on log-log paper
FB_FRICTION_LINES = {
    "low": ((3.4, 0.259), (3.8, 0.188), (4.2, 0.145), (4.7, 0.111), (5.3, 0.087), (6.0, 0.0675),
            (7.0, 10 ** (-0.26574 - 1.17775 * math.log10(7.0))), (50.0, 10 ** (-0.26574 - 1.17775 * math.log10(50.0)))),
    "mid": ((4.7, 10 ** (-0.52769 - 1.12195 * math.log10(4.7))), (27.0, 10 ** (-0.52769 - 1.12195 * math.log10(27.0)))),
    "high": ((3.7, 10 ** (-0.73798 - 1.26576 * math.log10(3.7))), (15.0, 10 ** (-0.73798 - 1.26576 * math.log10(15.0)))),
}


def fb_glr_band(glr):
    """Which of the paper's three lines applies: 'low' (GLR < 1500), 'mid' (1500 - 3000) or 'high' (> 3000)."""
    return "low" if glr < FB_GLR_LIMITS[0] else ("mid" if glr <= FB_GLR_LIMITS[1] else "high")


def fb_friction_factor(n_re, glr):
    """Fanning friction factor of Figs. 7-9 at N = rho v d (lb/s/ft) for a producing gas-liquid ratio glr (scf/STB)."""
    _check(n_re > 0, "The Fancher and Brown Reynolds numerator must be > 0.")
    pts = FB_FRICTION_LINES[fb_glr_band(glr)]
    n = min(max(n_re, pts[0][0]), FB_N_MAX[fb_glr_band(glr)])
    # the segment to read: the one that holds n, or the first / last one when n is outside the drawn line
    k = 0
    while k < len(pts) - 2 and n > pts[k + 1][0]:
        k += 1
    (n1, f1), (n2, f2) = pts[k], pts[k + 1]
    slope = math.log(f2 / f1) / math.log(n2 / n1)
    return f1 * (n / n1) ** slope


def fancher_brown_gradient(p, angle_deg, d_in, roughness_in, c):
    """Pressure gradient (psi/ft, positive in the flow direction) from Eq. 2 of Fancher and Brown.

    Inputs as in beggs_brill_gradient(); c must also hold 'glr', the producing gas-liquid ratio (scf per STB of
    LIQUID, all the gas that reaches the surface including the dissolved and the injected gas).  Pressure and
    roughness are not used: the paper's friction factor depends on N and the GLR only.
    The gravity part is rho sin(angle) with the no-slip density (the paper is for vertical wells; sin(90) = 1).
    """
    v_sl, v_sg = c["v_sl"], c["v_sg"]
    d_ft = d_in / 12.0
    area = math.pi * d_ft ** 2 / 4.0
    v_m = v_sl + v_sg
    lam = v_sl / v_m if v_m > 0 else 0.0                                   # no-slip liquid fraction
    rho = lam * c["rho_l"] + (1.0 - lam) * c["rho_g"]                      # flowing (no-slip) density, lb/ft3
    mass_rate = (c["rho_l"] * v_sl + c["rho_g"] * v_sg) * area * 86400.0   # q M of the paper, lb/day
    n_re = 1.4737e-5 * mass_rate / d_ft                                    # rho v d, lb/s/ft
    f = fb_friction_factor(n_re, c["glr"])
    friction = f * mass_rate ** 2 / (7.413e10 * rho * d_ft ** 5) / 144.0   # psi/ft
    hydrostatic = rho * math.sin(math.radians(angle_deg)) / 144.0
    mu_ns = lam * c["mu_l"] + (1.0 - lam) * c["mu_g"]
    return {"dpdl": hydrostatic + friction, "hl": lam, "regime": "no-slip", "hydrostatic": hydrostatic,
            "friction": friction, "f_tp": f, "re": RE_CONST * rho * v_m * d_ft / mu_ns, "e_k": 0.0, "glr": c["glr"]}


# =====================================================================
# The pressure traverse: wellhead -> perforations
# =====================================================================

GRADIENT_FUNCS = {"beggs_brill": beggs_brill_gradient,
                  "hagedorn_brown": hagedorn_brown_gradient,
                  "gray": gray_gradient,
                  "orkiszewski": orkiszewski_gradient,
                  "ansari": ansari_gradient,
                  "duns_ros": duns_ros_gradient,
                  "mukherjee_brill": mukherjee_brill_gradient,
                  "fancher_brown": fancher_brown_gradient}

# Correlations whose flow-pattern boundaries are known to make real jumps in the gradient: the pressure step
# accepts a jump up to this fraction of its own pressure change (see _step_bottom_pressure)
JUMPY_CORRELATIONS = {"orkiszewski": 0.5, "ansari": 0.5, "duns_ros": 0.5, "mukherjee_brill": 0.5}

# Named in the spec but not coded yet (none left)
_NOT_YET = ()


# A rate so high that the tubing would need more than this pressure can never be produced (no reservoir in this app is
# this high, and the PVT correlations are not meant for more).  Without a cap the search for the bottom pressure of a
# step at such a rate can wander to 100,000 psia, where the correlations return negative viscosities and the calculation
# stops with "Reynolds number must be > 0".  With the cap the VLP simply reads P_MAX there, far above the IPR.
P_MAX = 20000.0       # psia


def _step_bottom_pressure(gradient, fluid, rate, p_top, t_avg, s, roughness_in, jump_fraction=0.0):
    """Pressure at the bottom of one step, given the pressure at its top.

    The gradient depends on the average pressure of the step, which depends on the
    bottom pressure we are looking for, so we search for the bottom pressure x that
    satisfies   x = p_top + gradient(average of p_top and x) * length.
    Write residual(x) = (that right-hand side) - x; we need residual = 0.

    Method (robust, still simple):
      * the first guess is made from a typical gradient, the second is the plain
        'repeat' step;
      * after that, a secant step (a straight line through the last two points);
      * we remember the closest x below the answer (residual > 0) and the closest x
        above it (residual < 0).  If a secant step falls outside this bracket it is
        replaced by the middle of the bracket, so the search can never run away.
    A correlation with a tiny jump (where one formula hands over to the next) has no
    exact answer; the bracket then closes on the jump, and that is accepted if the
    residual on both sides is below 0.5 psi or 0.3 % of the pressure, whichever is larger (Beggs and Brill
    jumps by about 2 psi in a 100 ft step where the flow pattern changes).  jump_fraction > 0 allows a
    larger jump, as that fraction of the pressure change of the step: Orkiszewski's bubble/slug boundary
    is known to jump by a few psi per 100 ft at low rates (see JUMPY_CORRELATIONS).

    Returns (bottom pressure, the correlation's result dictionary).
    """
    tol = 0.01                                          # psi

    def residual(x):
        p_avg = max(0.5 * (p_top + x), 14.7)
        if s.get("inj_scfd"):                           # gas lift gas is in the flow above the injection point
            c = fluid.conditions(rate, p_avg, t_avg, s["id_in"], inj_scfd=s["inj_scfd"])
        else:
            c = fluid.conditions(rate, p_avg, t_avg, s["id_in"])
        res = gradient(p_avg, s["angle_deg"], s["id_in"], roughness_in, c)
        p_new = min(max(p_top + res["dpdl"] * s["length"], 1.0), P_MAX)
        return p_new - x, res

    x = p_top + 0.4 * max(s["tvd_bot"] - s["tvd_top"], 1.0)
    f, res = residual(x)
    below = above = None                                # (x, residual) of the bracket ends
    x_old = f_old = None
    for it in range(60):
        if abs(f) < tol:
            return x + f, res
        if f > 0 and (below is None or x > below[0]):
            below = (x, f)
        if f < 0 and (above is None or x < above[0]):
            above = (x, f)
        if below and above and above[0] - below[0] < tol:      # bracket closed on a jump
            if max(abs(below[1]), abs(above[1])) < max(0.5, 0.003 * x, jump_fraction * abs(x - p_top)):
                return 0.5 * (below[0] + above[0]), res
            break
        if x_old is None or f == f_old:
            x_new = x + f                               # plain repeat step
        else:
            x_new = x - f * (x - x_old) / (f - f_old)   # secant step
        # Only one side of the answer is known (for example a flow-pattern jump makes the residual
        # negative on both sides of the jump, with the true answer further down).  The secant step
        # may then just bounce between the same two points, so step away from the known side instead.
        if above and not below and x_new >= above[0]:
            x_new = above[0] - max(2.0 * abs(above[1]), 1.0)
        elif below and not above and x_new <= below[0]:
            x_new = below[0] + max(2.0 * abs(below[1]), 1.0)
        if below and above and (not (below[0] < x_new < above[0]) or it % 2 == 1):
            x_new = 0.5 * (below[0] + above[0])         # keep inside the bracket; every second step halves it
                                                        # (secant steps alone close very slowly on a jump)
        x_new = min(max(x_new, 1.0), P_MAX)
        x_old, f_old = x, f
        x = x_new
        f, res = residual(x)
    raise RuntimeError(f"Pressure did not converge in the step at MD {s['md_top']:.0f} ft.")


def _step_with_split(gradient, fluid, rate, p_top, t_avg, s, roughness_in, jump_fraction=0.0, depth=0):
    """_step_bottom_pressure(), but a step that has no solution is cut in two halves and each half is solved.

    A correlation whose flow-pattern boundary makes a big jump in the gradient (Ansari, from annular to slug at a
    low pressure and a high gas rate, jumps by about 0.17 psi/ft) can have no solution at all in a 100 ft
    step: the bottom pressure would need to sit exactly on the boundary.  The jump in the residual is the
    gradient jump times the step length, so a shorter step has a smaller jump, and after one or two halvings it
    is small enough for _step_bottom_pressure() to accept.  The halves are solved one after the other, the
    second starting from the bottom of the first.  The returned dictionary has the length-weighted holdup,
    hydrostatic and friction gradients of the two halves, so the totals of the traverse stay correct.
    """
    try:
        return _step_bottom_pressure(gradient, fluid, rate, p_top, t_avg, s, roughness_in, jump_fraction)
    except RuntimeError:
        if depth >= 5:                                  # 100 ft cut into 3 ft pieces and still no answer
            raise
    md_mid = 0.5 * (s["md_top"] + s["md_bot"])
    tvd_mid = 0.5 * (s["tvd_top"] + s["tvd_bot"])
    upper = dict(s, md_bot=md_mid, tvd_bot=tvd_mid, length=0.5 * s["length"])
    lower = dict(s, md_top=md_mid, tvd_top=tvd_mid, length=0.5 * s["length"])
    p_mid, res_upper = _step_with_split(gradient, fluid, rate, p_top, t_avg, upper, roughness_in, jump_fraction, depth + 1)
    p_bot, res_lower = _step_with_split(gradient, fluid, rate, p_mid, t_avg, lower, roughness_in, jump_fraction, depth + 1)
    res = dict(res_lower)
    for key in ("hl", "hydrostatic", "friction"):
        res[key] = 0.5 * (res_upper.get(key, 0.0) + res_lower.get(key, 0.0))
    return p_bot, res


MULTIPLIER_MIN, MULTIPLIER_MAX = 0.1, 10.0      # sanity limits for the VLP multipliers


def _with_multipliers(gradient, gravity_mult, friction_mult):
    """Wrap a gradient function so that its gravity and friction parts are scaled.

    This is what the industry calls "VLP matching": no correlation fits every well, so the gravity
    (hydrostatic) part and the friction part of the pressure drop can each be multiplied by
    a number found by matching measured data.  1.0 and 1.0 leave the correlation unchanged.

    All three correlations build their gradient the same way,
        dpdl = (hydrostatic + friction) / (1 - e_k)     (e_k = the small acceleration term)
    so the multipliers go in at exactly that place.
    """
    if gravity_mult == 1.0 and friction_mult == 1.0:
        return gradient

    def scaled(p, angle_deg, d_in, roughness_in, c):
        res = dict(gradient(p, angle_deg, d_in, roughness_in, c))
        res["hydrostatic"] *= gravity_mult
        res["friction"] *= friction_mult
        res["dpdl"] = (res["hydrostatic"] + res["friction"]) / (1.0 - res["e_k"])
        return res
    return scaled


def pressure_traverse(well, fluid, rate, p_wh, correlation="beggs_brill", max_step_ft=100.0,
                      gravity_mult=1.0, friction_mult=1.0):
    """Calculate pressure and temperature down the well for one rate.

    well        : a well.Well
    fluid       : OilWaterFluid or GasFluid
    rate        : STB/d of liquid (oil + water) for OilWaterFluid, Mscf/d for GasFluid
    p_wh        : wellhead flowing pressure (psia)
    correlation : 'beggs_brill', 'hagedorn_brown', 'gray', 'orkiszewski', 'ansari', 'duns_ros' or
                  'mukherjee_brill' (Fancher & Brown is not coded yet)
    max_step_ft : longest step; smaller = slower but a little more accurate
    gravity_mult, friction_mult : VLP matching multipliers (see _with_multipliers); 1.0 = none

    Returns a dictionary of lists (wellhead first): md, tvd, p, T, plus
    'holdup' (one value per step) and 'pwf' = pressure at the perforations.
    It also gives 'dp_hydrostatic' and 'dp_friction' (psi, added up over the whole
    well).  They are the usual "dP Gravity" and "dP Friction" split;
    the rest of (pwf - p_wh) is the small acceleration term.
    """
    if correlation in _NOT_YET:
        raise NotImplementedError(f"The {correlation} correlation is not coded yet.")
    _check(correlation in GRADIENT_FUNCS, f"Unknown VLP correlation: {correlation}")
    _check(rate > 0, "Rate must be > 0.")
    _check(p_wh > 0, "Wellhead pressure must be > 0.")
    _check(MULTIPLIER_MIN <= gravity_mult <= MULTIPLIER_MAX,
           f"The gravity multiplier must be between {MULTIPLIER_MIN} and {MULTIPLIER_MAX}.")
    _check(MULTIPLIER_MIN <= friction_mult <= MULTIPLIER_MAX,
           f"The friction multiplier must be between {MULTIPLIER_MIN} and {MULTIPLIER_MAX}.")
    gradient = _with_multipliers(GRADIENT_FUNCS[correlation], gravity_mult, friction_mult)

    inj_rate = getattr(fluid, "injection_gas_rate", 0.0)            # gas lift gas, Mscf/d (0 = none)
    inj_md = getattr(fluid, "injection_md", None)
    if inj_rate > 0.0:
        _check(0.0 < inj_md < well.md[-1],
               f"The gas injection depth ({inj_md:,.0f} ft) must be above the perforations "
               f"({well.md[-1]:,.0f} ft) and below the surface.")
        steps = build_steps(well, max_step_ft, extra_breaks=[inj_md])
        for s in steps:                                             # steps above the injection point carry the lift gas
            s["inj_scfd"] = inj_rate * 1000.0 if s["md_bot"] <= inj_md + 1e-6 else 0.0
    else:
        steps = build_steps(well, max_step_ft)
    mass_rate, cp = fluid.thermal_data(rate)
    if inj_rate > 0.0:
        m_i, cp_i = fluid.injected_thermal()
        above = [s["inj_scfd"] > 0.0 for s in steps]
        mass_rate = [mass_rate + m_i if a else mass_rate for a in above]
        cp = [(cp * (mass_rate[k] - m_i) + cp_i * m_i) / mass_rate[k] if a else cp for k, a in enumerate(above)]
    temps = fluid_temperatures(well, steps, mass_rate, cp)

    md_list = [steps[0]["md_top"]]
    tvd_list = [steps[0]["tvd_top"]]
    p_list = [p_wh]
    holdups = []
    regimes = []                  # the flow pattern the correlation reports in each step (a word)
    dp_hydrostatic = 0.0          # psi, added up step by step
    dp_friction = 0.0

    p_top = p_wh
    for i, s in enumerate(steps):
        t_avg = 0.5 * (temps[i] + temps[i + 1])
        # first guess for the bottom pressure, then repeat until it stops changing
        p_bot, res = _step_with_split(gradient, fluid, rate, p_top, t_avg, s, well.roughness_in,
                                      JUMPY_CORRELATIONS.get(correlation, 0.0))
        md_list.append(s["md_bot"])
        tvd_list.append(s["tvd_bot"])
        p_list.append(p_bot)
        holdups.append(res["hl"])
        regimes.append(res.get("regime", ""))
        dp_hydrostatic += res.get("hydrostatic", 0.0) * s["length"]
        dp_friction += res.get("friction", 0.0) * s["length"]
        p_top = p_bot

    return {"md": md_list, "tvd": tvd_list, "p": p_list, "T": temps,
            "holdup": holdups, "regime": regimes, "pwf": p_list[-1],
            "dp_hydrostatic": dp_hydrostatic, "dp_friction": dp_friction}


def vlp_curve(well, fluid, rates, p_wh, correlation="beggs_brill", max_step_ft=100.0,
              gravity_mult=1.0, friction_mult=1.0):
    """Flowing bottom-hole pressure (psia) for each rate in the list `rates`
    (all rates must be > 0).  Returns a list of the same length."""
    return [pressure_traverse(well, fluid, q, p_wh, correlation, max_step_ft,
                              gravity_mult, friction_mult)["pwf"]
            for q in rates]
