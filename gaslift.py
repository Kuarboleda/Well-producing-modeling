"""
gaslift.py - continuous gas lift helpers.

The gas lift calculation itself (the extra gas in the tubing above the injection point) lives in vlp.py:
OilWaterFluid(injection_gas_rate=..., injection_md=...).  This file adds the check that the gas can
actually get into the tubing: the casing (annulus) pressure at the injection depth must be higher than
the tubing pressure there.

Static gas column in the annulus (no flow, no friction):
        p_depth = p_surface * exp( 0.01875 * SG * TVD / (Z * T) )
    SG = gas gravity (air = 1), TVD in ft, T in degR (average annulus temperature), Z at average conditions.
The 0.01875 is  M_air / (R) = 28.97 / 1544  in these units.
"""
import math

import pvt

# Smallest pressure difference (psi) across the injection valve / orifice that we call "enough".
# Field rules of thumb are 100 - 200 psi for a reliable operating valve; 100 is used here.
MIN_DIFFERENTIAL_PSI = 100.0
ATM = 14.7                    # psi: this module works in psia; its message to the page is in psig


def _interp(x, xs, ys):
    """Straight-line interpolation of ys against xs (xs increasing)."""
    if x <= xs[0]:
        return ys[0]
    for k in range(1, len(xs)):
        if x <= xs[k]:
            f = (x - xs[k - 1]) / (xs[k] - xs[k - 1])
            return ys[k - 1] + f * (ys[k] - ys[k - 1])
    return ys[-1]


def casing_pressure_at_depth(p_surface, tvd, t_avg_f, gas_sg):
    """Pressure (psia) at depth tvd (ft) of a static gas column that has p_surface (psia) at the top.
    t_avg_f = average temperature of the column (degF).  Z changes with pressure, so the result is
    found by repeating (3 to 5 times is plenty)."""
    if p_surface <= 0 or tvd < 0 or gas_sg <= 0:
        raise ValueError("Injection pressure and gas gravity must be > 0 and the depth cannot be negative.")
    t_r = t_avg_f + 459.67
    p = p_surface
    for _ in range(30):
        z = pvt.gas_properties(0.5 * (p_surface + p), t_avg_f, gas_sg)["z"]
        p_new = p_surface * math.exp(0.01875 * gas_sg * tvd / (z * t_r))
        if abs(p_new - p) < 1e-6:
            break
        p = p_new
    return p


def injection_check(well, fluid, traverse, p_inj_surface):
    """Is there enough casing pressure at the injection point?

    well, fluid : the Well and the OilWaterFluid used for the traverse (fluid has the gas lift data)
    traverse    : pressure_traverse() result at the operating rate (with the gas lift on)
    p_inj_surface : gas injection pressure at the wellhead (psia), 0 or None = not given
                    (the page sends psig; build_case() turns it into psia)

    Returns None when gas lift is off or no pressure was given.  Otherwise a dictionary:
        md, tvd             : depth of the injection point (ft)
        p_tubing            : flowing tubing pressure there (psia)
        p_casing            : casing (annulus) gas pressure there (psia)
        differential        : p_casing - p_tubing (psi)
        ok                  : differential >= MIN_DIFFERENTIAL_PSI
        message             : one plain sentence for the page
    """
    if not p_inj_surface or getattr(fluid, "injection_gas_rate", 0.0) <= 0.0 or traverse is None:
        return None
    md_inj = fluid.injection_md
    tvd = _interp(md_inj, traverse["md"], traverse["tvd"])
    p_tub = _interp(md_inj, traverse["md"], traverse["p"])
    t_tub = _interp(md_inj, traverse["md"], traverse["T"])
    t_surface = well.ambient_table[0][1]
    p_csg = casing_pressure_at_depth(p_inj_surface, tvd, 0.5 * (t_surface + t_tub), fluid.injected_gas_sg())
    dp = p_csg - p_tub
    ok = dp >= MIN_DIFFERENTIAL_PSI
    # The message is for the page, so its pressures are gauge (psig); the numbers above stay absolute.
    csg_g, tub_g = p_csg - ATM, p_tub - ATM
    if ok:
        message = (f"Casing pressure at the injection point ({md_inj:,.0f} ft MD) is {csg_g:,.0f} psig against "
                   f"{tub_g:,.0f} psig in the tubing: {dp:,.0f} psi across the valve - enough.")
    elif dp > 0:
        message = (f"Casing pressure at the injection point ({md_inj:,.0f} ft MD) is {csg_g:,.0f} psig against "
                   f"{tub_g:,.0f} psig in the tubing: only {dp:,.0f} psi across the valve (about "
                   f"{MIN_DIFFERENTIAL_PSI:,.0f} psi is wanted). Raise the injection pressure or inject shallower.")
    else:
        message = (f"Casing pressure at the injection point ({md_inj:,.0f} ft MD) is {csg_g:,.0f} psig but the "
                   f"tubing pressure there is {tub_g:,.0f} psig: the gas cannot enter. Raise the injection "
                   f"pressure or inject shallower.")
    return {"md": md_inj, "tvd": tvd, "p_tubing": p_tub, "p_casing": p_csg, "differential": dp,
            "ok": ok, "message": message}
