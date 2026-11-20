"""
ipr.py - Inflow Performance Relationships (IPR) for the Nodal Analysis app.

An IPR answers one question:
    "If I hold the flowing bottom-hole pressure (Pwf) at this value,
     how much does the reservoir deliver?"

Units (oilfield):
    pressure ........ psia
    temperature ..... degF
    oil rate ........ STB/d          gas rate ........ Mscf/d  (thousand scf/day)
    permeability k .. md             thickness h ..... ft
    viscosity ....... cP             radii re, rw .... ft
    Bo .............. rb/STB         gas gravity ..... air = 1
    PI (J) .......... STB/d/psi

Notation used in every function:
    p_res = average reservoir pressure (the "Pr" or "p-bar" in the spec)
    pwf   = flowing bottom-hole pressure
    pb    = bubble-point pressure (oil only)

Every IPR function has the same first two inputs (p_res, pwf) and returns the
rate.  That lets ipr_curve() build a full curve for any of them.  To get the
AOF (absolute open flow = maximum rate), just call the function with pwf = 0.

OIL                                     GAS
    oil_pi          (PI entry)              gas_darcy        (Darcy, p-squared)
    oil_vogel       (Vogel, 1 test)         gas_jones        (Jones: a*q + b*q^2)
    oil_darcy       (Darcy, PSS)            gas_backpressure (q = C*(Pr^2-Pwf^2)^n)
    oil_fetkovich   (2 tests)
    oil_darcy_regime       (Darcy: steady / pseudosteady / TRANSIENT at a given time)
    oil_horizontal_joshi   (horizontal well, Joshi 1988)
    oil_horizontal_kuchuk_goode (horizontal well in a box, Kuchuk and Goode 1991)
    oil_multilayer         (commingled layers, each with its own pressure and PI)
    gas_horizontal_joshi          (horizontal gas well, Joshi geometry + turbulence)
    gas_horizontal_kuchuk_goode   (horizontal gas well in a box, Kuchuk and Goode geometry + turbulence)
    gas_multilayer         (commingled gas layers: Darcy, Jones or back-pressure each, own pressure, CGR and WGR)
"""
import math
import warnings

# ---------------------------------------------------------------------
# Constants (all for the oilfield units listed above)
# ---------------------------------------------------------------------
DARCY_OIL = 141.2           # radial Darcy flow, oil
DARCY_GAS = 1422.0          # radial Darcy flow, gas, with q in Mscf/d and T in degR
JONES_B_CONST = 3.161e-12   # non-Darcy ("turbulence") term of the Jones equation


# =====================================================================
# Small helper functions (used by the models further down)
# =====================================================================

def _check(condition, message):
    """Stop with a clear error message if an input does not make sense."""
    if not condition:
        raise ValueError(message)


def _vogel_fraction(x):
    """Vogel shape: q/qmax = 1 - 0.2*x - 0.8*x^2, where x = pwf / (pressure at which
    the curve starts).  Gives 1 at x = 0 (pwf = 0) and 0 at x = 1."""
    return 1.0 - 0.2 * x - 0.8 * x ** 2


def _oil_composite_ipr(p_res, pwf, pb, J):
    """The oil IPR shape shared by PI, Vogel and Darcy.  It needs the productivity
    index J (the slope of the straight-line part).

        pwf >= Pb  : single-phase oil -> straight line  q = J * (Pr - Pwf)
        pwf <  Pb  : gas is coming out of solution -> Vogel curve, starting from
                     the rate at Pb:  q = qb + qv * (1 - 0.2*(Pwf/Pb) - 0.8*(Pwf/Pb)^2)
                     with  qb = J*(Pr - Pb)   and   qv = J*Pb/1.8

    If Pr <= Pb the reservoir is already below the bubble point, so the whole
    curve is Vogel.  We handle that by pretending the "bubble point" is Pr
    itself (then qb = 0 and qv = J*Pr/1.8, which is the usual Vogel qmax).
    """
    if pwf >= p_res:                       # no drawdown -> no flow
        return 0.0

    pb_used = min(pb, p_res)               # Pr <= Pb  ->  use Pr as the break point
    if pwf >= pb_used:                     # straight-line (single-phase) part
        return J * (p_res - pwf)

    q_b = J * (p_res - pb_used)            # rate at the break point (0 if Pr <= Pb)
    q_v = J * pb_used / 1.8                # extra rate the Vogel part can add
    return q_b + q_v * _vogel_fraction(pwf / pb_used)


def _check_oil_inputs(p_res, pwf, pb):
    _check(p_res > 0, "Reservoir pressure must be > 0.")
    _check(pwf >= 0, "Flowing bottom-hole pressure cannot be negative.")
    _check(pb >= 0, "Bubble-point pressure cannot be negative.")


def _check_gas_inputs(p_res, pwf):
    _check(p_res > 0, "Reservoir pressure must be > 0.")
    _check(pwf >= 0, "Flowing bottom-hole pressure cannot be negative.")


# =====================================================================
# OIL 1 - PI (productivity index) entry
# =====================================================================

def oil_pi(p_res, pwf, pb, J):
    """Oil rate (STB/d) from a user-entered productivity index J (STB/d/psi).

    Above Pb the IPR is a straight line with slope J.
    Below Pb it bends into a Vogel curve (see _oil_composite_ipr).
    """
    _check_oil_inputs(p_res, pwf, pb)
    _check(J > 0, "PI (J) must be > 0.")
    return _oil_composite_ipr(p_res, pwf, pb, J)


# =====================================================================
# OIL 2 - Vogel (needs ONE well test: rate and Pwf)
# =====================================================================

def vogel_productivity_index(p_res, pb, q_test, pwf_test):
    """Find the productivity index J (STB/d/psi) from one well test.

    Three cases (this is the heart of the Vogel option):

      Case A: Pr <= Pb  (reservoir already below bubble point)
              Whole IPR is Vogel:  qmax = q_test / (1 - 0.2*(Pwf/Pr) - 0.8*(Pwf/Pr)^2)
              and J = 1.8 * qmax / Pr

      Case B: Pr > Pb and test Pwf >= Pb  (test taken in single-phase region)
              J = q_test / (Pr - Pwf_test)

      Case C: Pr > Pb and test Pwf < Pb  (test taken in two-phase region)
              J = q_test / ( (Pr - Pb) + Pb/1.8 * (1 - 0.2*(Pwf/Pb) - 0.8*(Pwf/Pb)^2) )
    """
    _check(p_res > 0, "Reservoir pressure must be > 0.")
    _check(pb >= 0, "Bubble-point pressure cannot be negative.")
    _check(q_test > 0, "Test rate must be > 0.")
    _check(0 <= pwf_test < p_res, "Test Pwf must be >= 0 and below the reservoir pressure.")

    if p_res <= pb:                                            # Case A
        qmax = q_test / _vogel_fraction(pwf_test / p_res)
        return 1.8 * qmax / p_res
    elif pwf_test >= pb:                                       # Case B
        return q_test / (p_res - pwf_test)
    else:                                                      # Case C
        denominator = (p_res - pb) + (pb / 1.8) * _vogel_fraction(pwf_test / pb)
        return q_test / denominator


def oil_vogel(p_res, pwf, pb, q_test, pwf_test):
    """Oil rate (STB/d) from the Vogel IPR, calibrated with one well test
    (q_test in STB/d at flowing pressure pwf_test in psia)."""
    _check_oil_inputs(p_res, pwf, pb)
    J = vogel_productivity_index(p_res, pb, q_test, pwf_test)
    return _oil_composite_ipr(p_res, pwf, pb, J)


# =====================================================================
# OIL 3 - Darcy (pseudo-steady-state radial flow)
# =====================================================================

def darcy_productivity_index_oil(k, h, bo, mu, re, rw, skin=0.0):
    """Productivity index J (STB/d/psi) from reservoir properties:

        J = k*h / ( 141.2 * Bo * mu * ( ln(re/rw) - 3/4 + S ) )

    k md | h ft | bo rb/STB | mu cP | re = drainage radius ft | rw = wellbore radius ft
    skin = skin factor S (dimensionless, 0 = undamaged)
    """
    _check(k > 0 and h > 0, "k and h must be > 0.")
    _check(bo > 0 and mu > 0, "Bo and viscosity must be > 0.")
    _check(re > rw > 0, "Drainage radius must be larger than wellbore radius (both > 0).")
    bracket = math.log(re / rw) - 0.75 + skin
    _check(bracket > 0, "ln(re/rw) - 0.75 + skin must be > 0 (is the skin too negative?).")
    return k * h / (DARCY_OIL * bo * mu * bracket)


def oil_darcy(p_res, pwf, pb, k, h, bo, mu, re, rw, skin=0.0):
    """Oil rate (STB/d) using J from Darcy's law.
    Above Pb: straight line.  Below Pb: same Vogel bend as the PI option."""
    _check_oil_inputs(p_res, pwf, pb)
    J = darcy_productivity_index_oil(k, h, bo, mu, re, rw, skin)
    return _oil_composite_ipr(p_res, pwf, pb, J)


# =====================================================================
# OIL 3b - Darcy, other flow regimes: steady state and transient
# (equations 3.1-3.2 and 3.4 of Guo, "Reservoir Deliverability", and the
#  textbook Darcy radial-flow equations; the three differ only in the
#  "geometry bracket" under the line.)
# =====================================================================

def darcy_productivity_index_oil_steady(k, h, bo, mu, re, rw, skin=0.0):
    """Productivity index J (STB/d/psi) for STEADY-STATE radial flow
    (pressure at the outer radius re is held constant, e.g. by a strong aquifer):

        J = k*h / ( 141.2 * Bo * mu * ( ln(re/rw) + S ) )

    Compare with pseudosteady state (darcy_productivity_index_oil): the only
    difference is the "- 3/4" there, so the steady-state J is a few percent
    smaller (8 % in Guo's Example 3-1)."""
    _check(k > 0 and h > 0, "k and h must be > 0.")
    _check(bo > 0 and mu > 0, "Bo and viscosity must be > 0.")
    _check(re > rw > 0, "Drainage radius must be larger than wellbore radius (both > 0).")
    bracket = math.log(re / rw) + skin
    _check(bracket > 0, "ln(re/rw) + skin must be > 0 (is the skin too negative?).")
    return k * h / (DARCY_OIL * bo * mu * bracket)


def darcy_productivity_index_oil_transient(k, h, bo, mu, phi, ct, rw, time_hours, skin=0.0):
    """Productivity index J (STB/d/psi) for TRANSIENT (infinite-acting) radial flow,
    "J after t hours of production":

        J = k*h / ( 162.6 * Bo * mu * ( log10(t) + log10( k / (phi*mu*ct*rw^2) )
                                         - 3.23 + 0.87*S ) )

    k md | h ft | bo rb/STB | mu cP | phi fraction | ct 1/psi (total compressibility)
    rw ft | time_hours = hours since the well was opened | skin = S

    J keeps falling as time goes on (the pressure disturbance moves outward),
    until the boundary is felt and the flow becomes pseudosteady.  The equation is
    only valid while the disturbance has NOT reached the boundary - see
    transient_end_time_hours() (oil_darcy_regime warns when that time is passed)."""
    _check(k > 0 and h > 0, "k and h must be > 0.")
    _check(bo > 0 and mu > 0, "Bo and viscosity must be > 0.")
    _check(phi > 0 and ct > 0, "Porosity and total compressibility must be > 0.")
    _check(rw > 0, "Wellbore radius must be > 0.")
    _check(time_hours > 0, "Flowing time must be > 0 hours.")
    bracket = (math.log10(time_hours) + math.log10(k / (phi * mu * ct * rw ** 2))
               - 3.23 + 0.87 * skin)
    _check(bracket > 0, "The transient bracket is <= 0: time is too short for this equation "
                        "(or the skin is too negative).")
    return k * h / (162.6 * bo * mu * bracket)


def transient_end_time_hours(k, phi, mu, ct, re):
    """Approximate time (hours) when the pressure disturbance reaches the outer
    boundary re and the transient equation stops being valid:
        t_end = 948 * phi*mu*ct*re^2 / k     (the usual "tDA = 0.1" rule of thumb)."""
    _check(k > 0 and phi > 0 and mu > 0 and ct > 0 and re > 0, "All inputs must be > 0.")
    return 948.0 * phi * mu * ct * re ** 2 / k


def oil_darcy_regime(p_res, pwf, pb, k, h, bo, mu, re, rw, skin=0.0,
                     regime="pseudosteady", phi=None, ct=None, time_hours=None):
    """Oil rate (STB/d) from Darcy's law for a chosen flow regime:

        regime = "pseudosteady"  closed drainage area (same as oil_darcy)
        regime = "steady"        constant pressure at re
        regime = "transient"     infinite-acting; needs phi, ct and time_hours

    Above Pb: straight line.  Below Pb: Vogel bend (same as the other oil models)."""
    _check_oil_inputs(p_res, pwf, pb)
    if regime == "pseudosteady":
        J = darcy_productivity_index_oil(k, h, bo, mu, re, rw, skin)
    elif regime == "steady":
        J = darcy_productivity_index_oil_steady(k, h, bo, mu, re, rw, skin)
    elif regime == "transient":
        _check(phi is not None and ct is not None and time_hours is not None,
               "The transient regime needs phi, ct and time_hours.")
        J = darcy_productivity_index_oil_transient(k, h, bo, mu, phi, ct, rw, time_hours, skin)
        t_end = transient_end_time_hours(k, phi, mu, ct, re)
        if time_hours > t_end:
            warnings.warn(f"{time_hours:.0f} h is later than about {t_end:.0f} h, when the "
                          "pressure disturbance reaches the boundary - the transient result "
                          "is no longer valid; use the pseudosteady regime.")
    else:
        raise ValueError("regime must be 'pseudosteady', 'steady' or 'transient'.")
    return _oil_composite_ipr(p_res, pwf, pb, J)


# =====================================================================
# OIL 3c - Horizontal well, Joshi (1988)
# =====================================================================

def horizontal_productivity_index_oil_joshi(kh, kv, h, length, re_h, rw, bo, mu, skin=0.0):
    """Productivity index J (STB/d/psi) of a HORIZONTAL oil well, Joshi (1988),
    as printed in Guo, "Reservoir Deliverability", equations 3.11 - 3.13.
    (Steady-state flow in the horizontal plane, pseudosteady in the vertical plane.)

        J = kh*h / ( 141.2*Bo*mu * { ln[ (a + sqrt(a^2 - (L/2)^2)) / (L/2) ]
                                      + (Iani*h/L) * ( ln[ Iani*h / (rw*(Iani+1)) ] + S ) } )

        a     = (L/2) * sqrt( 0.5 + sqrt( 0.25 + (re_h/(L/2))^4 ) )
        Iani  = sqrt( kh / kv )

    kh      horizontal permeability (md)      kv   vertical permeability (md)
    h       reservoir thickness (ft)          length  horizontal well length L (ft)
    re_h    drainage radius of the well in the horizontal plane (ft); for a drainage
            area A (acres) use  re_h = sqrt(43560*A/pi)
    rw      wellbore radius (ft)

    ASSUMPTION ON SKIN: Guo's slide has no skin term.  Here S is added inside the
    second bracket, so it is weighted by Iani*h/L (the usual way to add mechanical
    skin to Joshi's equation: it acts around the wellbore, i.e. in the
    vertical-plane part).  Please check this against the paper if skin matters.

    Joshi's equation assumes the well is centred in the thickness and that
    L/2 is clearly smaller than re_h (a warning is given for L/2 > 0.9*re_h)."""
    _check(kh > 0 and kv > 0, "Horizontal and vertical permeability must be > 0.")
    _check(h > 0 and length > 0, "Thickness and well length must be > 0.")
    _check(bo > 0 and mu > 0, "Bo and viscosity must be > 0.")
    _check(rw > 0, "Wellbore radius must be > 0.")
    _check(re_h > length / 2.0,
           "The drainage radius re_h must be larger than half the well length (L/2).")
    if length / 2.0 > 0.9 * re_h:
        warnings.warn("Joshi's equation is intended for L/2 < 0.9*re_h; this well is "
                      "almost as long as its drainage area - treat the result with care.")
    i_ani = math.sqrt(kh / kv)
    half = length / 2.0
    a = half * math.sqrt(0.5 + math.sqrt(0.25 + (re_h / half) ** 4))
    horizontal_plane = math.log((a + math.sqrt(a * a - half * half)) / half)
    vertical_plane = (i_ani * h / length) * (math.log(i_ani * h / (rw * (i_ani + 1.0))) + skin)
    bracket = horizontal_plane + vertical_plane
    _check(bracket > 0, "The Joshi bracket is <= 0 (is the skin too negative?).")
    return kh * h / (DARCY_OIL * bo * mu * bracket)


def oil_horizontal_joshi(p_res, pwf, pb, kh, kv, h, length, re_h, rw, bo, mu, skin=0.0):
    """Oil rate (STB/d) of a horizontal well using Joshi's J.
    Above Pb: straight line.  Below Pb: the same Vogel bend as the other oil models."""
    _check_oil_inputs(p_res, pwf, pb)
    J = horizontal_productivity_index_oil_joshi(kh, kv, h, length, re_h, rw, bo, mu, skin)
    return _oil_composite_ipr(p_res, pwf, pb, J)


# =====================================================================
# OIL 3d - Horizontal well, Kuchuk and Goode (SPE 21460, "Inflow Performance of Horizontal Wells", 1991)
# =====================================================================
# A horizontal well parallel to the x axis in a closed rectangular box Lx x Ly x h (all sides sealed; the top may
# instead be a constant-pressure boundary such as a gas cap or an aquifer).  The well has length L = 2 * L_half, is
# centred at x = xw, sits at y = yw across the width and at z = zw above the bottom.  kx is along the well, ky across it.
#
#   J (STB/d/psi) = 7.08e-3 * kH * h / ( mu * Bo * (pwD + S*m) ),      kH = sqrt(kx*ky)             paper Eq. 3
#   S*m = (h / (2*L_half)) * sqrt(kx/kz) * Sm   (Sm = the mechanical skin of the well)                paper Eq. 4
#   pwD = dimensionless pseudosteady-state pressure drop (sealed top: Eq. 6, 7;  constant-pressure top: Eq. B-3)

_EULER_GAMMA = 0.5772156649015329


def bickley_ki2(beta):
    """Ki2(beta) = integral from 0 to infinity of exp(-beta*cosh(u)) / cosh(u)^2 du  (paper Eq. A-22).
    Simpson's rule; the integrand dies out so fast that u = 0 ... 25 is far enough for beta >= 0.001.
    Checked against the paper's Table 1 (for example Ki2(1) = 0.27362, Ki2(0.1) = 0.86252)."""
    _check(beta > 0, "Ki2 needs beta > 0.")
    n = 4000                                           # even number of intervals
    top = 25.0
    step = top / n
    total = 0.0
    for k in range(n + 1):
        u = k * step
        value = math.exp(-beta * math.cosh(u)) / math.cosh(u) ** 2
        weight = 1 if k in (0, n) else (4 if k % 2 else 2)
        total += weight * value
    return total * step / 3.0


def horizontal_pwd_kuchuk_goode(kx, ky, kz, h, lx, ly, length, xw, yw, zw, rw, top="sealed"):
    """Dimensionless pseudosteady-state pressure drop pwD of a horizontal well (Kuchuk and Goode, SPE 21460).

    kx, ky, kz  permeabilities (md): kx along the well, ky across it in the horizontal plane, kz vertical
    h           reservoir thickness (ft)
    lx, ly      drainage box: length in the well direction and width across it (ft)
    length      well length L = 2*L_half (ft)
    xw          x position of the well CENTRE along the box, 0 ... lx (ft)
    yw          y position of the well across the box, 0 ... ly (ft)
    zw          height of the well above the bottom of the reservoir, 0 ... h (ft)
    rw          wellbore radius (ft)
    top         "sealed" (no-flow top and bottom, paper Eq. 6) or "constant_pressure" (top is a constant-pressure
                boundary, steady state, paper Eq. B-3; the box size in x and y is then not used)
    pwD does not contain the mechanical skin (it is added separately, see the PI function)."""
    for name, v in (("kx", kx), ("ky", ky), ("kz", kz), ("h", h), ("lx", lx), ("ly", ly), ("length", length), ("rw", rw)):
        _check(v > 0, f"{name} must be > 0.")
    half = length / 2.0
    _check(0 < zw < h, "The well must be inside the thickness (0 < zw < h).")
    r_eq = 0.5 * rw * (1.0 + math.sqrt(kz / ky))              # r'w, paper Eq. 7b
    h_d = (h / half) * math.sqrt(kx / kz)                      # scaled thickness
    z_ratio = zw / h
    if top == "constant_pressure":
        # Eq. B-3 in the scaled variables of Appendix A (this is the form that follows from Appendix B; the printed
        # Eq. 11 has 8h where the same algebra gives 4h - see the note in the README)
        r_d = (rw / (2.0 * half)) * (math.sqrt(kx / ky) + math.sqrt(kx / kz))        # Eq. A-1g
        z_d = (zw / half) * math.sqrt(kx / kz)
        main = 0.5 * h_d * (math.log(4.0 * h_d / (math.pi * r_d) / math.tan(math.pi * z_ratio / 2.0)) + z_d - h_d)
        series = 0.0
        for j in range(1, 60):
            a = 2 * j - 1
            term = (1.0 / a ** 2) * bickley_ki2(a * math.pi / h_d) * math.cos(a * math.pi * z_ratio / 2.0) ** 2
            series += term
            if a * math.pi / h_d > 40:
                break
        return main + 4.0 * h_d ** 2 / math.pi ** 2 * series
    _check(top == "sealed", "top must be 'sealed' or 'constant_pressure'.")
    _check(0 <= xw <= lx and 0 <= yw <= ly, "The well centre must be inside the drainage box.")
    _check(xw - half >= -1e-9 and xw + half <= lx + 1e-9, "The well must lie inside the drainage box along x (L/2 <= xw <= Lx - L/2).")
    root_xy = math.sqrt(kx / ky)
    # areal part, first term of Eq. 6
    pwd = (2.0 * math.pi * ly / lx) * root_xy * (1.0 / 3.0 - yw / ly + (yw / ly) ** 2)
    # series in n, second term of Eq. 6 (converges like 1/n^3)
    total = 0.0
    for n in range(1, 400):
        xi_x = math.sin(n * math.pi * half / lx) * math.cos(n * math.pi * xw / lx) / n          # Eq. 7e
        alpha = -(2.0 * n * math.pi / lx) * root_xy                                              # Eq. 7d
        e_ly, e_back, e_yw = math.exp(alpha * ly), math.exp(alpha * (ly - yw)), math.exp(alpha * yw)
        xi = (2.0 * e_ly + e_back + e_yw) / (1.0 - e_ly)                                         # Eq. 7c
        total += xi_x ** 2 * (1.0 + xi) / n
    pwd += 2.0 * lx ** 2 / (math.pi ** 2 * half ** 2) * total
    # geometric skin from the partial penetration in z, Eq. 7a ...
    s_zd = -(h_d / 2.0) * (math.log(math.pi * r_eq / h * 2.0 * math.sin(math.pi * z_ratio))
                           + h_d * (1.0 / 3.0 - z_ratio + z_ratio ** 2))
    # ... plus the extra series of Eq. A-21 (negligible when h_d < 5, the usual case)
    extra = 0.0
    for j in range(1, 400):
        beta = 2.0 * j * math.pi / h_d
        if beta > 40.0:
            break
        extra += bickley_ki2(beta) * math.cos(j * math.pi * z_ratio) ** 2 / j ** 2
    s_zd -= h_d ** 2 / math.pi ** 2 * extra
    return pwd + s_zd


def horizontal_productivity_index_oil_kuchuk_goode(kh, kv, h, length, lx, ly, xw, yw, zw, rw, bo, mu,
                                                   skin=0.0, ky_ratio=1.0, top="sealed"):
    """Productivity index J (STB/d/psi) of a horizontal oil well, Kuchuk and Goode (SPE 21460) Eq. 3.
    kh = kx, the permeability along the well (md); ky = ky_ratio * kh across it; kv = kz (md).
    skin = the mechanical skin Sm of the well; it enters as S*m = (h / L) * sqrt(kx/kz) * Sm  (Eq. 4, L = 2*L_half)."""
    _check(kh > 0 and kv > 0 and ky_ratio > 0, "Permeabilities must be > 0.")
    _check(bo > 0 and mu > 0, "Bo and viscosity must be > 0.")
    kx, ky, kz = kh, ky_ratio * kh, kv
    pwd = horizontal_pwd_kuchuk_goode(kx, ky, kz, h, lx, ly, length, xw, yw, zw, rw, top)
    s_star = (h / length) * math.sqrt(kx / kz) * skin
    _check(pwd + s_star > 0, "pwD + skin is <= 0 (is the skin too negative?).")
    return (1.0 / DARCY_OIL) * math.sqrt(kx * ky) * h / (mu * bo * (pwd + s_star))


def oil_horizontal_kuchuk_goode(p_res, pwf, pb, kh, kv, h, length, lx, ly, xw, yw, zw, rw, bo, mu,
                                skin=0.0, ky_ratio=1.0, top="sealed"):
    """Oil rate (STB/d) of a horizontal well using the Kuchuk-Goode J.
    Above Pb: straight line.  Below Pb: the same Vogel bend as the other oil models."""
    _check_oil_inputs(p_res, pwf, pb)
    J = horizontal_productivity_index_oil_kuchuk_goode(kh, kv, h, length, lx, ly, xw, yw, zw, rw, bo, mu,
                                                       skin, ky_ratio, top)
    return _oil_composite_ipr(p_res, pwf, pb, J)


# =====================================================================
# OIL 5 - Multilayer (commingled layers, each with its own pressure and PI)
# =====================================================================

def multilayer_rates(p_res, pwf, pb, layers, crossflow=False):
    """The liquid rate (STB/d) of each layer at one flowing pressure, as a list in the order of `layers`.
    See oil_multilayer() for the meaning of the inputs.  A layer below the flowing pressure gives 0, or a negative
    number (it takes fluid from the wellbore) when crossflow is True."""
    _check(len(layers) >= 1, "Multilayer IPR needs at least one layer.")
    _check_oil_inputs(p_res, pwf, pb)
    rates = []
    for k, layer in enumerate(layers, start=1):
        _check(layer["p_res"] > 0, f"Layer {k}: reservoir pressure must be > 0.")
        _check(layer["J"] > 0, f"Layer {k}: productivity index must be > 0.")
        if pwf < layer["p_res"]:
            rates.append(_oil_composite_ipr(layer["p_res"], pwf, pb, layer["J"]))
        elif crossflow:
            rates.append(layer["J"] * (layer["p_res"] - pwf))          # negative: the layer is taking fluid
        else:
            rates.append(0.0)
    return rates


def oil_multilayer(p_res, pwf, pb, layers, crossflow=False):
    """Liquid rate (STB/d) of several layers producing into the same well at the same flowing pressure.

    layers    : list of dictionaries, one per layer, each with
                    "p_res" - the layer's average pressure (psia)
                    "J"     - the layer's productivity index (STB/d/psi)
                and, only for the produced fluid (see multilayer_mix), optionally
                    "wc"    - the layer's water cut, fraction of its liquid (0 - 1)
                    "gor"   - the layer's formation (producing) GOR, scf/STB of oil
                Each layer follows the usual oil IPR (straight line above Pb, Vogel below it).
    crossflow : False -> a layer whose pressure is below the wellbore pressure simply stops producing.
                True  -> that layer takes fluid FROM the wellbore (crossflow); it is taken as a straight line
                         q = J * (Pr - Pwf), which is then negative, and it reduces the total.
    p_res     : kept so that every IPR function has the same first two inputs; the layers carry their own
                pressures, so the program passes the highest of them (the pressure where the curve starts).

    The layers are all referred to the same depth (the perforation reference depth of the well); the small
    pressure differences caused by layers sitting at different depths are not included.
    All layers see the same fluid, so one bubble point (pb) is used for all of them.
    """
    return sum(multilayer_rates(p_res, pwf, pb, layers, crossflow))


def multilayer_mix(p_res, pwf, pb, layers, default_wc=0.0, default_gor=None, crossflow=False):
    """What the commingled layers produce at one flowing pressure.

    Every producing layer adds its liquid; its water is liquid * wc, its oil is liquid * (1 - wc) and its gas is
    oil * gor.  The well stream is the sum:
        water cut = total water / total liquid
        GOR       = total gas   / total oil
    A layer that has no "wc" or "gor" uses default_wc / default_gor.  A layer that is not producing (or takes
    fluid in crossflow) does not count.  When no layer produces, the layers are weighted by their PI.

    Returns {"q": total liquid, "q_layers": list, "water_cut": fraction, "gor": scf/STB}."""
    rates = multilayer_rates(p_res, pwf, pb, layers, crossflow)
    weights = [max(q, 0.0) for q in rates]
    if sum(weights) <= 0.0:
        weights = [layer["J"] for layer in layers]
    water = oil = gas = 0.0
    for layer, w in zip(layers, weights):
        wc = layer.get("wc")
        wc = default_wc if wc is None else wc
        gor = layer.get("gor")
        gor = default_gor if gor is None else gor
        water += w * wc
        oil += w * (1.0 - wc)
        gas += w * (1.0 - wc) * (gor or 0.0)
    liquid = water + oil
    return {"q": sum(rates), "q_layers": rates, "water_cut": water / liquid if liquid > 0 else default_wc,
            "gor": gas / oil if oil > 0 else default_gor}


def multilayer_pwf(q, p_res, pb, layers, crossflow=False):
    """The flowing pressure (psia) at which the commingled layers give the liquid rate q (the IPR turned round).
    Found by halving the interval (the total rate falls steadily as Pwf rises).  A rate above the AOF gives 0,
    a rate of 0 or less gives the highest layer pressure."""
    p_max = max(layer["p_res"] for layer in layers)
    if q <= 0.0:
        return p_max
    if sum(multilayer_rates(p_res, 0.0, pb, layers, crossflow)) <= q:
        return 0.0                                  # more than the AOF asked for
    lo, hi = 0.0, p_max
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if sum(multilayer_rates(p_res, mid, pb, layers, crossflow)) > q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-6:
            break
    return 0.5 * (lo + hi)


# =====================================================================
# Fetkovich (oil)  and  back-pressure (gas) share the same equation:
#       q = C * (Pr^2 - Pwf^2)^n
# =====================================================================

def c_and_n_from_two_tests(p_res, q1, pwf1, q2, pwf2):
    """Find C and n from two well tests (q1 at pwf1, q2 at pwf2).

        n = log(q1/q2) / log( (Pr^2 - Pwf1^2) / (Pr^2 - Pwf2^2) )
        C = q1 / (Pr^2 - Pwf1^2)^n

    n should lie between 0.5 (fully turbulent) and 1.0 (fully laminar).
    Rates can be in any unit; C then carries that same rate unit.
    """
    _check(p_res > 0, "Reservoir pressure must be > 0.")
    _check(q1 > 0 and q2 > 0, "Both test rates must be > 0.")
    _check(0 <= pwf1 < p_res and 0 <= pwf2 < p_res,
           "Test Pwf values must be >= 0 and below the reservoir pressure.")
    _check(pwf1 != pwf2, "The two tests need different flowing pressures.")
    _check(q1 != q2, "The two tests need different rates (otherwise n = 0).")

    dp2_1 = p_res ** 2 - pwf1 ** 2          # "pressure-squared drawdown" of test 1
    dp2_2 = p_res ** 2 - pwf2 ** 2          # ... and of test 2
    n = math.log10(q1 / q2) / math.log10(dp2_1 / dp2_2)
    _check(n > 0, "Test data gives n <= 0: the larger drawdown must give the larger rate.")
    if round(n, 4) < 0.5 or round(n, 4) > 1.0:      # round() avoids false alarms from 0.49999999
        warnings.warn(f"n = {n:.3f} is outside the usual range 0.5-1.0 - please check the test data.")
    C = q1 / dp2_1 ** n
    return C, n


def oil_fetkovich(p_res, pwf, q1, pwf1, q2, pwf2):
    """Oil rate (STB/d) from Fetkovich's equation  q = C * (Pr^2 - Pwf^2)^n,
    with C and n found from two well tests (q1 @ pwf1, q2 @ pwf2)."""
    _check(p_res > 0, "Reservoir pressure must be > 0.")
    _check(pwf >= 0, "Flowing bottom-hole pressure cannot be negative.")
    C, n = c_and_n_from_two_tests(p_res, q1, pwf1, q2, pwf2)
    if pwf >= p_res:
        return 0.0
    return C * (p_res ** 2 - pwf ** 2) ** n


# =====================================================================
# GAS - Darcy and Jones (pressure-squared form)
# =====================================================================
# For gas we work with pressure squared.  Both models solve
#       Pr^2 - Pwf^2 = a*q + b*q^2
# a*q = laminar (Darcy) pressure loss,  b*q^2 = turbulent (non-Darcy) loss.
# Darcy is the special case b = 0.
#
# z and mu are normally taken at the AVERAGE pressure (Pr + Pwf)/2 and the
# reservoir temperature - e.g. from pvt.gas_properties().  Here they are inputs.

def gas_a_coefficient(temp_f, k, h, mu, z, re, rw, skin=0.0):
    """Laminar (Darcy) coefficient 'a' in psi^2 per (Mscf/d):

        a = 1422 * T * mu * z * ( ln(re/rw) - 3/4 + S ) / (k * h)      T in degR
    """
    _check(k > 0 and h > 0, "k and h must be > 0.")
    _check(mu > 0 and z > 0, "Gas viscosity and Z must be > 0.")
    _check(re > rw > 0, "Drainage radius must be larger than wellbore radius (both > 0).")
    bracket = math.log(re / rw) - 0.75 + skin
    _check(bracket > 0, "ln(re/rw) - 0.75 + skin must be > 0 (is the skin too negative?).")
    temp_r = temp_f + 460.0                                    # degF -> degR
    return DARCY_GAS * temp_r * mu * z * bracket / (k * h)


def gas_beta_firoozabadi_katz(k):
    """Estimate the non-Darcy (turbulence) factor beta in 1/ft from permeability k (md):
    beta = 2.73e10 / k^1.1045  (Firoozabadi & Katz).  It is only an estimate - if you
    have a measured or better beta, pass it into gas_jones() instead."""
    _check(k > 0, "k must be > 0.")
    return 2.73e10 / k ** 1.1045


def gas_b_coefficient(temp_f, k, h_perf, z, gas_sg, rw, beta=None):
    """Turbulent (non-Darcy) coefficient 'b' in psi^2 per (Mscf/d)^2:

        b = 3.161e-12 * beta * T * gas_sg * z / ( h_perf^2 * rw )      T in degR

    h_perf = perforated (open) thickness in ft.  beta in 1/ft (estimated from k if None).
    """
    _check(h_perf > 0 and rw > 0, "h_perf and rw must be > 0.")
    _check(gas_sg > 0 and z > 0, "Gas gravity and Z must be > 0.")
    if beta is None:
        beta = gas_beta_firoozabadi_katz(k)
    _check(beta >= 0, "beta cannot be negative.")
    temp_r = temp_f + 460.0
    return JONES_B_CONST * beta * temp_r * gas_sg * z / (h_perf ** 2 * rw)


def _solve_rate(a, b, dp2):
    """Solve  b*q^2 + a*q = dp2  for q (positive root).

    The textbook formula is  q = (-a + sqrt(a^2 + 4*b*dp2)) / (2*b).  We use the
    mathematically identical form below because it also works when b = 0
    (pure Darcy) and avoids subtracting two nearly equal numbers."""
    return 2.0 * dp2 / (a + math.sqrt(a ** 2 + 4.0 * b * dp2))


def gas_darcy(p_res, pwf, temp_f, k, h, mu, z, re, rw, skin=0.0):
    """Gas rate (Mscf/d) from Darcy's law in pressure-squared form (no turbulence):

        q = k*h*(Pr^2 - Pwf^2) / ( 1422 * T * mu * z * ( ln(re/rw) - 3/4 + S ) )
    """
    _check_gas_inputs(p_res, pwf)
    a = gas_a_coefficient(temp_f, k, h, mu, z, re, rw, skin)
    if pwf >= p_res:
        return 0.0
    return (p_res ** 2 - pwf ** 2) / a


def gas_jones(p_res, pwf, temp_f, k, h, mu, z, gas_sg, re, rw,
              skin=0.0, beta=None, h_perf=None):
    """Gas rate (Mscf/d) from the Jones equation  Pr^2 - Pwf^2 = a*q + b*q^2.

    gas_sg = gas gravity (air = 1)
    beta   = non-Darcy factor in 1/ft  (None -> estimated from k)
    h_perf = perforated thickness in ft (None -> same as h)
    """
    _check_gas_inputs(p_res, pwf)
    if h_perf is None:
        h_perf = h
    a = gas_a_coefficient(temp_f, k, h, mu, z, re, rw, skin)
    b = gas_b_coefficient(temp_f, k, h_perf, z, gas_sg, rw, beta)
    if pwf >= p_res:
        return 0.0
    return _solve_rate(a, b, p_res ** 2 - pwf ** 2)


# =====================================================================
# GAS - back-pressure equation (C and n)
# =====================================================================

def gas_backpressure(p_res, pwf, C, n):
    """Gas rate from the back-pressure equation  q = C * (Pr^2 - Pwf^2)^n.

    C and n come from a multi-rate (back-pressure) test.  If you only have two
    test points, get them with c_and_n_from_two_tests().  The rate has the
    same unit as the rate used to find C (use Mscf/d to match the other models).
    """
    _check_gas_inputs(p_res, pwf)
    _check(C > 0, "C must be > 0.")
    _check(0.0 < n <= 1.0, "n must be between 0 and 1 (usually 0.5 - 1.0).")
    if pwf >= p_res:
        return 0.0
    return C * (p_res ** 2 - pwf ** 2) ** n


# =====================================================================
# GAS - Horizontal wells (Joshi, Kuchuk and Goode)
# =====================================================================
# The shape of the flow in the reservoir is the same for oil and gas.  For oil the geometry gives the productivity
# index  J = kh*h / (141.2 * Bo * mu * B)  (B = the bracket of the Joshi equation, or pwD + skin for Kuchuk-Goode).
# For gas in pressure-squared form the same bracket gives the laminar coefficient
#       a = 1422 * T * mu * z * B / (kh*h)         [psi^2 / (Mscf/d)]
# which is exactly what the vertical gas well uses with B = ln(re/rw) - 3/4 + S.  So a is found from the
# oil routine with Bo = 1 and mu = 1:   a = 1422 * T * mu * z / (141.2 * J1).
# Turbulence: the Jones term  b*q^2  of the vertical well is kept, with the wellbore length L in place of the
# perforated thickness (the gas enters the well through an area 2*pi*rw*L instead of 2*pi*rw*h), so
#       b = 3.161e-12 * beta * T * gas_sg * z / (L^2 * rw).
# With a long horizontal section b is very small: horizontal gas wells are almost free of non-Darcy loss.
# ASSUMPTION: this turbulence term is the usual engineering extension, not a published horizontal-well equation;
# give beta yourself when you have it (None = estimate from kh with Firoozabadi and Katz).

def gas_a_coefficient_horizontal_joshi(temp_f, kh, kv, h, length, re_h, rw, mu, z, skin=0.0):
    """Laminar coefficient a (psi^2 per Mscf/d) of a horizontal gas well, Joshi geometry (see
    horizontal_productivity_index_oil_joshi for the inputs and the skin assumption)."""
    _check(mu > 0 and z > 0, "Gas viscosity and Z must be > 0.")
    j1 = horizontal_productivity_index_oil_joshi(kh, kv, h, length, re_h, rw, 1.0, 1.0, skin)
    return DARCY_GAS * (temp_f + 460.0) * mu * z / (DARCY_OIL * j1)


def gas_horizontal_joshi(p_res, pwf, temp_f, kh, kv, h, length, re_h, rw, mu, z, gas_sg,
                         skin=0.0, beta=None):
    """Gas rate (Mscf/d) of a horizontal well: Pr^2 - Pwf^2 = a*q + b*q^2 with the Joshi a (above) and the
    turbulence term b = 3.161e-12 * beta * T * gas_sg * z / (L^2 * rw).  beta in 1/ft (None = estimate from kh)."""
    _check_gas_inputs(p_res, pwf)
    a = gas_a_coefficient_horizontal_joshi(temp_f, kh, kv, h, length, re_h, rw, mu, z, skin)
    b = gas_b_coefficient(temp_f, kh, length, z, gas_sg, rw, beta)
    if pwf >= p_res:
        return 0.0
    return _solve_rate(a, b, p_res ** 2 - pwf ** 2)


def gas_a_coefficient_horizontal_kuchuk_goode(temp_f, kh, kv, h, length, lx, ly, xw, yw, zw, rw, mu, z,
                                              skin=0.0, ky_ratio=1.0, top="sealed"):
    """Laminar coefficient a (psi^2 per Mscf/d) of a horizontal gas well in a box, Kuchuk and Goode geometry
    (see horizontal_productivity_index_oil_kuchuk_goode for the inputs)."""
    _check(mu > 0 and z > 0, "Gas viscosity and Z must be > 0.")
    j1 = horizontal_productivity_index_oil_kuchuk_goode(kh, kv, h, length, lx, ly, xw, yw, zw, rw, 1.0, 1.0,
                                                        skin, ky_ratio, top)
    return DARCY_GAS * (temp_f + 460.0) * mu * z / (DARCY_OIL * j1)


def gas_horizontal_kuchuk_goode(p_res, pwf, temp_f, kh, kv, h, length, lx, ly, xw, yw, zw, rw, mu, z, gas_sg,
                                skin=0.0, ky_ratio=1.0, top="sealed", beta=None):
    """Gas rate (Mscf/d) of a horizontal well in a closed box (Kuchuk and Goode): Pr^2 - Pwf^2 = a*q + b*q^2,
    a from the Kuchuk-Goode pressure drop, b as in gas_horizontal_joshi()."""
    _check_gas_inputs(p_res, pwf)
    a = gas_a_coefficient_horizontal_kuchuk_goode(temp_f, kh, kv, h, length, lx, ly, xw, yw, zw, rw, mu, z,
                                                  skin, ky_ratio, top)
    b = gas_b_coefficient(temp_f, kh, length, z, gas_sg, rw, beta)
    if pwf >= p_res:
        return 0.0
    return _solve_rate(a, b, p_res ** 2 - pwf ** 2)


# =====================================================================
# GAS - Multilayer (commingled layers, each with its own pressure, deliverability, CGR and WGR)
# =====================================================================

def _gas_layer_rate(layer, pwf, crossflow, number):
    """Gas rate (Mscf/d) of one layer at the flowing pressure pwf.  A layer is described by
        "p_res" (psia) and either  "a" (psi^2 per Mscf/d) and "b" (psi^2 per (Mscf/d)^2)   - Darcy / Jones
                              or   "C" and "n"                                              - back-pressure
    Below the flowing pressure the layer is shut (0), or - with crossflow - it takes gas from the wellbore:
    the rate is then negative and follows the same law with the pressures swapped (laminar term only for a, b)."""
    p_layer = layer["p_res"]
    _check(p_layer > 0, f"Layer {number}: reservoir pressure must be > 0.")
    if "C" in layer:
        _check(layer["C"] > 0 and 0.0 < layer["n"] <= 1.0,
               f"Layer {number}: C must be > 0 and n between 0 and 1.")
    else:
        _check(layer.get("a", 0.0) > 0 and layer.get("b", 0.0) >= 0.0,
               f"Layer {number}: the laminar coefficient a must be > 0 and b cannot be negative.")
    if pwf < p_layer:
        dp2 = p_layer ** 2 - pwf ** 2
        if "C" in layer:
            return layer["C"] * dp2 ** layer["n"]
        return _solve_rate(layer["a"], layer["b"], dp2)
    if not crossflow or pwf == p_layer:
        return 0.0
    dp2 = pwf ** 2 - p_layer ** 2
    if "C" in layer:
        return -layer["C"] * dp2 ** layer["n"]
    return -dp2 / layer["a"]


def gas_multilayer_rates(p_res, pwf, layers, crossflow=False):
    """The gas rate (Mscf/d) of each layer at one flowing pressure, in the order of `layers`."""
    _check(len(layers) >= 1, "Multilayer IPR needs at least one layer.")
    _check_gas_inputs(p_res, pwf)
    return [_gas_layer_rate(layer, pwf, crossflow, k) for k, layer in enumerate(layers, start=1)]


def gas_multilayer(p_res, pwf, layers, crossflow=False):
    """Gas rate (Mscf/d) of several layers producing into the same well at the same flowing pressure.

    layers    : list of dictionaries, one per layer: "p_res" (psia) and either "a" and "b" (Darcy or Jones, see
                gas_a_coefficient and gas_b_coefficient; b = 0 is Darcy) or "C" and "n" (back-pressure);
                optionally "cgr" (STB/MMscf) and "wgr" (STB/MMscf) for the produced fluid (see gas_multilayer_mix).
    crossflow : False -> a layer below the flowing pressure simply stops producing.
                True  -> it takes gas FROM the wellbore (negative rate, reduces the total).
    p_res     : only kept so that every IPR function has the same first two inputs; the layers carry their own
                pressures, and the program passes the highest of them.
    All layers are taken at the same depth (the perforation reference); the gas of all layers is one gas."""
    return sum(gas_multilayer_rates(p_res, pwf, layers, crossflow))


def gas_multilayer_mix(p_res, pwf, layers, default_cgr=0.0, default_wgr=0.0, crossflow=False):
    """What the commingled gas layers produce at one flowing pressure: every producing layer adds its gas, and its
    condensate (gas * cgr) and water (gas * wgr).  The well stream has
        CGR = total condensate / total gas        WGR = total water / total gas.
    A layer without "cgr" / "wgr" uses the defaults.  Layers that do not produce do not count; when none produces
    the layers are weighted by their rate at Pwf = 0.
    Returns {"q": total gas, "q_layers": list, "cgr": STB/MMscf, "wgr": STB/MMscf}."""
    rates = gas_multilayer_rates(p_res, pwf, layers, crossflow)
    weights = [max(q, 0.0) for q in rates]
    if sum(weights) <= 0.0:
        weights = [max(q, 0.0) for q in gas_multilayer_rates(p_res, 0.0, layers, crossflow)]
    gas = cond = water = 0.0
    for layer, w in zip(layers, weights):
        cgr = layer.get("cgr")
        wgr = layer.get("wgr")
        gas += w
        cond += w * (default_cgr if cgr is None else cgr)
        water += w * (default_wgr if wgr is None else wgr)
    return {"q": sum(rates), "q_layers": rates,
            "cgr": cond / gas if gas > 0 else default_cgr, "wgr": water / gas if gas > 0 else default_wgr}


def gas_multilayer_pwf(q, p_res, layers, crossflow=False):
    """The flowing pressure (psia) at which the commingled gas layers give the rate q (the IPR turned round), by
    halving the interval.  A rate above the AOF gives 0, a rate of 0 or less gives the highest layer pressure."""
    p_max = max(layer["p_res"] for layer in layers)
    if q <= 0.0:
        return p_max
    if sum(gas_multilayer_rates(p_res, 0.0, layers, crossflow)) <= q:
        return 0.0
    lo, hi = 0.0, p_max
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if sum(gas_multilayer_rates(p_res, mid, layers, crossflow)) > q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return 0.5 * (lo + hi)


# =====================================================================
# Build a whole IPR curve (for plotting or for finding the intersection with VLP)
# =====================================================================

def ipr_curve(ipr_function, p_res, n_points=21, **inputs):
    """Calculate an IPR curve from pwf = p_res down to pwf = 0.

    ipr_function : any function above, e.g. oil_vogel
    inputs       : the remaining inputs of that function, by name

    Example:
        pwf_list, q_list = ipr_curve(oil_pi, 3000, pb=2000, J=3.0)

    Returns two lists of equal length: pwf_list (psia) and q_list (rate).
    """
    _check(n_points >= 2, "n_points must be at least 2.")
    pwf_list = []
    q_list = []
    for i in range(n_points):
        pwf = p_res * (1.0 - i / (n_points - 1))     # p_res, ..., 0
        pwf_list.append(pwf)
        q_list.append(ipr_function(p_res=p_res, pwf=pwf, **inputs))
    return pwf_list, q_list
