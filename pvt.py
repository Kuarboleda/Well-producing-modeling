"""
pvt.py - PVT correlations for the Nodal Analysis app (Oilfield units).

Units: pressure psia | temperature degF | Rs scf/STB | Bo rb/STB | Bg rcf/scf
       viscosity cP  | density lb/ft3   | gas gravity (air = 1) | API degrees
Public functions:
    oil_properties(p, T, api, gas_sg, rsb, ...)   -> dict
    gas_properties(p, T, gas_sg, ...)             -> dict
    water_properties(p, T, salinity_wt_pct)       -> dict
    wet_gas_gravity(...)                          -> well-stream gravity
"""
import math

ATM_PSIA = 14.7        # one atmosphere: the lowest bubble point oil_properties() will work with

# =====================================================================
# OIL  -  bubble point, Rs, Bo
# =====================================================================

def _sg_oil(api):
    return 141.5 / (api + 131.5)


# ---- Standing -------------------------------------------------------
def pb_standing(rs, gg, api, T):
    return max(18.2 * ((rs / gg) ** 0.83 * 10 ** (0.00091 * T - 0.0125 * api) - 1.4), 14.7)

def rs_standing(p, gg, api, T):
    return gg * ((p / 18.2 + 1.4) * 10 ** (0.0125 * api - 0.00091 * T)) ** 1.2048

def bo_standing(rs, gg, api, T):
    F = rs * math.sqrt(gg / _sg_oil(api)) + 1.25 * T
    return 0.9759 + 0.00012 * F ** 1.2


# ---- Glaso ----------------------------------------------------------
def pb_glaso(rs, gg, api, T):
    pbs = (rs / gg) ** 0.816 * T ** 0.172 / api ** 0.989
    lg = math.log10(pbs)
    return 10 ** (1.7669 + 1.7447 * lg - 0.30218 * lg ** 2)

def rs_glaso(p, gg, api, T):
    lpb = 2.8869 - math.sqrt(max(14.1811 - 3.3093 * math.log10(p), 0.0))
    return gg * (api ** 0.989 / T ** 0.172 * 10 ** lpb) ** 1.2255

def bo_glaso(rs, gg, api, T):
    bstar = rs * (gg / _sg_oil(api)) ** 0.526 + 0.968 * T
    lb = math.log10(bstar)
    return 1.0 + 10 ** (-6.58511 + 2.91329 * lb - 0.27683 * lb ** 2)


# ---- Lasater --------------------------------------------------------
def _mo_lasater(api):
    return 630.0 - 10.0 * api if api <= 40 else 73110.0 * api ** -1.562

def pb_lasater(rs, gg, api, T):
    n = rs / 379.3
    yg = n / (n + 350.0 * _sg_oil(api) / _mo_lasater(api))
    pf = 0.679 * math.exp(2.786 * yg) - 0.323 if yg <= 0.6 else 8.26 * yg ** 3.56 + 1.95
    return pf * (T + 460.0) / gg

def rs_lasater(p, gg, api, T):
    pf = p * gg / (T + 460.0)
    yg = 0.359 * math.log(1.473 * pf + 0.476) if pf <= 3.29 else (0.121 * pf - 0.236) ** 0.281
    return 132755.0 * _sg_oil(api) * yg / (_mo_lasater(api) * (1.0 - yg))

# Lasater gives no Bo correlation; Standing's Bo is used with it.
bo_lasater = bo_standing


# ---- Petrosky & Farshad --------------------------------------------
def _x_pf(api, T):
    return 7.916e-4 * api ** 1.5410 - 4.561e-5 * T ** 1.3911

def pb_petrosky(rs, gg, api, T):
    return 112.727 * rs ** 0.577421 / (gg ** 0.8439 * 10 ** _x_pf(api, T)) - 1391.51

def rs_petrosky(p, gg, api, T):
    return ((p / 112.727 + 12.340) * gg ** 0.8439 * 10 ** _x_pf(api, T)) ** 1.73184

def bo_petrosky(rs, gg, api, T):
    go = _sg_oil(api)
    return 1.0113 + 7.2046e-5 * (rs ** 0.3738 * gg ** 0.2914 / go ** 0.6265 + 0.24626 * T ** 0.5371) ** 3.0936


PB_FUNCS = {"glaso": pb_glaso, "standing": pb_standing, "lasater": pb_lasater, "petrosky": pb_petrosky}
RS_FUNCS = {"glaso": rs_glaso, "standing": rs_standing, "lasater": rs_lasater, "petrosky": rs_petrosky}
BO_FUNCS = {"glaso": bo_glaso, "standing": bo_standing, "lasater": bo_lasater, "petrosky": bo_petrosky}


# =====================================================================
# OIL  -  viscosity
# =====================================================================

def mu_dead_beal(api, T):
    a = 10 ** (0.43 + 8.33 / api)
    return (0.32 + 1.8e7 / api ** 4.53) * (360.0 / (T + 200.0)) ** a

def mu_dead_beggs(api, T):
    y = 10 ** (3.0324 - 0.02023 * api)
    return 10 ** (y * T ** -1.163) - 1.0

def mu_live_chew_connally(mud, rs):          # used with Beal dead-oil viscosity
    A = 10 ** (rs * (2.2e-7 * rs - 7.4e-4))
    B = 0.68 / 10 ** (8.62e-5 * rs) + 0.25 / 10 ** (1.1e-3 * rs) + 0.062 / 10 ** (3.74e-3 * rs)
    return A * mud ** B

def mu_live_beggs(mud, rs):
    return 10.715 * (rs + 100.0) ** -0.515 * mud ** (5.44 * (rs + 150.0) ** -0.338)

# Petrosky and Farshad (1995), Gulf of Mexico crude oils (SPE 29468).  T in degF, Rs in scf/STB, p in psia.
# Valid for roughly 16 - 45 API and 114 - 288 degF.
def mu_dead_petrosky(api, T):
    x = 4.59388 * math.log10(T) - 22.82792
    return 2.3511e7 * T ** -2.10255 * math.log10(api) ** x

def mu_live_petrosky(mud, rs):
    a = 0.1651 + 0.6165 * 10 ** (-6.0866e-4 * rs)
    b = 0.5131 + 0.5109 * 10 ** (-1.1831e-3 * rs)
    return a * mud ** b

def mu_under_petrosky(mub, p, pb):
    lg = math.log10(mub)
    a = -1.0146 + 1.3322 * lg - 0.4876 * lg ** 2 - 1.15036 * lg ** 3
    return mub + 1.3449e-3 * (p - pb) * 10 ** a

def mu_under_beal(mub, p, pb):
    return mub + 0.001 * (p - pb) * (0.024 * mub ** 1.6 + 0.038 * mub ** 0.56)

def mu_under_vasquez_beggs(mub, p, pb):
    m = 2.6 * p ** 1.187 * math.exp(-11.513 - 8.98e-5 * p)
    return mub * (p / pb) ** m


# =====================================================================
# OIL  -  everything at one (p, T)
# =====================================================================

def oil_properties(p, T, api, gas_sg, rsb, pb_meas=None,
                   pvt_method="glaso", visc_method="beal", match=None):
    """Black-oil properties at pressure p (psia) and temperature T (degF).

    rsb       : solution GOR at bubble point (scf/STB)
    pb_meas   : optional measured bubble point; correlations are matched to it
                by scaling pressure (calc Pb -> measured Pb)
    pvt_method: 'glaso' | 'standing' | 'lasater' | 'petrosky'  (Pb, Rs, Bo)
    visc_method: 'beal' | 'beggs' | 'petrosky'
    match     : optional PVT-matching numbers found from lab data (see pvt_match.py), a dict with
                    rs_exp  - Rs below Pb becomes  rsb * (Rs/rsb) ** rs_exp      (1 = unchanged)
                    bo_a, bo_b - Bo becomes  bo_a * Bo + bo_b                    (1, 0 = unchanged)
                    mu_mult - oil viscosity is multiplied by this                (1 = unchanged)
                None = the correlations as published.
    """
    if pvt_method not in PB_FUNCS:
        raise ValueError(f"Unknown PVT method: {pvt_method}")
    if visc_method not in ("beal", "beggs", "petrosky"):
        raise ValueError(f"Unknown viscosity method: {visc_method}")

    # The bubble point can come back non-physical when a correlation is used outside the data it was
    # fitted to.  Petrosky and Farshad were working on Gulf of Mexico oils with Rs from about 200 to
    # 1,900 scf/STB, and below roughly 100 scf/STB their equation turns NEGATIVE; Glaso and Lasater can
    # also fall below atmospheric.  A negative Pb used to poison everything after it in silence: with
    # p >= pb the Vasquez-Beggs viscosity raises (p/pb) to a fractional power, and a negative base there
    # made Python hand back a COMPLEX viscosity, which then flowed into the density and the VLP.  So the
    # calculated bubble point is held at atmospheric or above.  (pb_standing already does this itself.)
    # Found on 20 Nov 2026 by cross-checking against the JavaScript engine, where the same expression
    # gives NaN instead of a complex number.
    pb_calc = max(PB_FUNCS[pvt_method](rsb, gas_sg, api, T), ATM_PSIA)
    pb = pb_meas if pb_meas else pb_calc
    scale = pb_calc / pb
    go = _sg_oil(api)

    m = match or {}
    rs_exp = m.get("rs_exp", 1.0)

    if p >= pb:
        rs = rsb
        bob = BO_FUNCS[pvt_method](rsb, gas_sg, api, T)
        # Vasquez-Beggs undersaturated compressibility
        co = (-1433.0 + 5.0 * rsb + 17.2 * T - 1180.0 * gas_sg + 12.61 * api) / (1e5 * p)
        bo = bob * math.exp(co * (pb - p))
    else:
        rs = min(max(RS_FUNCS[pvt_method](p * scale, gas_sg, api, T), 0.0), rsb)   # some correlations dip below 0 near 0 psia
        if rs_exp != 1.0:                      # lab match: reshape the Rs curve, keeping Rs(Pb) = rsb
            rs = rsb * (rs / rsb) ** rs_exp
        bo = BO_FUNCS[pvt_method](rs, gas_sg, api, T)
        co = None
    bo = m.get("bo_a", 1.0) * bo + m.get("bo_b", 0.0)

    # viscosity
    if visc_method == "beal":
        mud = mu_dead_beal(api, T)
        mub = mu_live_chew_connally(mud, rsb)
        mu_sat = mu_live_chew_connally(mud, rs)
        mu = mu_under_beal(mub, p, pb) if p >= pb else mu_sat
    elif visc_method == "petrosky":
        mud = mu_dead_petrosky(api, T)
        mub = mu_live_petrosky(mud, rsb)
        mu_sat = mu_live_petrosky(mud, rs)
        mu = mu_under_petrosky(mub, p, pb) if p >= pb else mu_sat
    else:
        mud = mu_dead_beggs(api, T)
        mub = mu_live_beggs(mud, rsb)
        mu_sat = mu_live_beggs(mud, rs)
        mu = mu_under_vasquez_beggs(mub, p, pb) if p >= pb else mu_sat
    mu = m.get("mu_mult", 1.0) * mu

    rho = (350.0 * go + 0.0764 * gas_sg * rs) / (5.615 * bo)
    return {"pb": pb, "rs": rs, "bo": bo, "mu_o": mu, "rho_o": rho, "co": co}


# =====================================================================
# GAS
# =====================================================================

def gas_pseudocritical(gas_sg, y_h2s=0.0, y_co2=0.0):
    """Sutton pseudo-criticals (degR, psia) with Wichert-Aziz sour-gas correction.
    y_h2s, y_co2 are mole fractions (0-1)."""
    tpc = 169.2 + 349.5 * gas_sg - 74.0 * gas_sg ** 2
    ppc = 756.8 - 131.0 * gas_sg - 3.6 * gas_sg ** 2
    if y_h2s > 0 or y_co2 > 0:
        A = y_h2s + y_co2
        eps = 120.0 * (A ** 0.9 - A ** 1.6) + 15.0 * (y_h2s ** 0.5 - y_h2s ** 4)
        tpc_new = tpc - eps
        ppc = ppc * tpc_new / (tpc + y_h2s * (1.0 - y_h2s) * eps)
        tpc = tpc_new
    return tpc, ppc


_DAK = (0.3265, -1.0700, -0.5339, 0.01569, -0.05165, 0.5475,
        -0.7361, 0.1844, 0.1056, 0.6134, 0.7210)

def z_dak(ppr, tpr):
    """Dranchuk & Abou-Kassem Z-factor (valid ~ 1.0<Tpr<3.0, 0.2<Ppr<30)."""
    a = _DAK

    def z_of(rr):
        return (1.0
                + (a[0] + a[1] / tpr + a[2] / tpr ** 3 + a[3] / tpr ** 4 + a[4] / tpr ** 5) * rr
                + (a[5] + a[6] / tpr + a[7] / tpr ** 2) * rr ** 2
                - a[8] * (a[6] / tpr + a[7] / tpr ** 2) * rr ** 5
                + a[9] * (1.0 + a[10] * rr ** 2) * (rr ** 2 / tpr ** 3) * math.exp(-a[10] * rr ** 2))

    def g(rr):                               # root of g(rr)=0 gives reduced density
        return z_of(rr) - 0.27 * ppr / (tpr * rr)

    lo, hi = 1e-6, 3.0
    for _ in range(100):                     # bisection
        mid = 0.5 * (lo + hi)
        if g(mid) > 0:
            hi = mid
        else:
            lo = mid
    return z_of(0.5 * (lo + hi))


def mu_gas_lee(p, T, gas_sg, z):
    """Lee-Gonzalez-Eakin gas viscosity (cP)."""
    Tr = T + 460.0
    M = 28.97 * gas_sg
    rho = 1.4935e-3 * p * M / (z * Tr)       # g/cc
    K = (9.4 + 0.02 * M) * Tr ** 1.5 / (209.0 + 19.0 * M + Tr)
    X = 3.5 + 986.0 / Tr + 0.01 * M
    Y = 2.4 - 0.2 * X
    return 1e-4 * K * math.exp(X * rho ** Y)


_DEMPSEY = (-2.46211820, 2.97054714, -2.86264054e-1, 8.05420522e-3,
            2.80860949, -3.49803305, 3.60373020e-1, -1.04432413e-2,
            -7.93385684e-1, 1.39643306, -1.49144925e-1, 4.41015512e-3,
            8.39387178e-2, -1.86408848e-1, 2.03367881e-2, -6.09579263e-4)

def mu_gas_carr(p, T, gas_sg, ppr, tpr):
    """Carr-Kobayashi-Burrows gas viscosity: Standing 1-atm viscosity +
    Dempsey polynomial for the viscosity ratio (cP). Hydrocarbon gas only."""
    mu1 = (1.709e-5 - 2.062e-6 * gas_sg) * T + 8.188e-3 - 6.15e-3 * math.log10(gas_sg)
    a = _DEMPSEY
    s = 0.0
    for i in range(4):                       # powers of Tpr
        s += tpr ** i * (a[4 * i] + a[4 * i + 1] * ppr + a[4 * i + 2] * ppr ** 2 + a[4 * i + 3] * ppr ** 3)
    return mu1 * math.exp(s) / tpr


def gas_properties(p, T, gas_sg, y_h2s=0.0, y_co2=0.0, visc_method="lee"):
    """Z, Bg (rcf/scf), density (lb/ft3), viscosity (cP) of a gas at (p, T)."""
    tpc, ppc = gas_pseudocritical(gas_sg, y_h2s, y_co2)
    tpr, ppr = (T + 460.0) / tpc, p / ppc
    z = z_dak(ppr, tpr)
    bg = 0.02827 * z * (T + 460.0) / p
    rho = 2.699 * gas_sg * p / (z * (T + 460.0))
    if visc_method == "lee":
        mu = mu_gas_lee(p, T, gas_sg, z)
    elif visc_method == "carr":
        mu = mu_gas_carr(p, T, gas_sg, ppr, tpr)
    else:
        raise ValueError(f"Unknown gas viscosity method: {visc_method}")
    return {"z": z, "bg": bg, "rho_g": rho, "mu_g": mu, "ppr": ppr, "tpr": tpr}


def wet_gas_gravity(gas_sg, cgr_stb_per_mmscf, cond_api):
    """Well-stream gravity of a wet gas (McCain) from separator gas gravity,
    condensate-gas ratio (STB/MMscf) and condensate API. Cragoe molecular weight."""
    R = 1e6 / cgr_stb_per_mmscf              # scf/STB
    go = _sg_oil(cond_api)
    Mo = 6084.0 / (cond_api - 5.9)
    return (R * gas_sg + 4602.0 * go) / (R + 133316.0 * go / Mo)


# =====================================================================
# WATER (McCain)
# =====================================================================

def salinity_from_sg(sg):
    """Water salinity (wt %) from the specific gravity of the brine at standard conditions
    (fresh water = 1.0, for example 1.02 for sea-water-like brine).

    water_properties() takes the standard-condition density as  62.368 + 0.438603*S + 0.00160074*S^2
    (lb/ft3, S in wt %), and fresh water is 62.368 lb/ft3, so
        sg = 1 + (0.438603*S + 0.00160074*S^2) / 62.368
    which is solved here for S (a quadratic).  1.02 -> 2.84 wt %,  1.05 -> 6.99 wt %."""
    if not 1.0 <= sg <= 1.25:
        raise ValueError("Water specific gravity must be between 1.00 (fresh) and 1.25.")
    a, b, c = 1.60074e-3, 0.438603, -62.368 * (sg - 1.0)
    return (-b + math.sqrt(b * b - 4.0 * a * c)) / (2.0 * a)


def water_properties(p, T, salinity_wt_pct=3.0):
    S = salinity_wt_pct
    dvt = -1.0001e-2 + 1.33391e-4 * T + 5.50654e-7 * T ** 2
    dvp = (-1.95301e-9 * p * T - 1.72834e-13 * p ** 2 * T
           - 3.58922e-7 * p - 2.25341e-10 * p ** 2)
    bw = (1.0 + dvt) * (1.0 + dvp)
    rho_sc = 62.368 + 0.438603 * S + 1.60074e-3 * S ** 2
    A = 109.574 - 8.40564 * S + 0.313314 * S ** 2 + 8.72213e-3 * S ** 3
    B = (-1.12166 + 2.63951e-2 * S - 6.79461e-4 * S ** 2
         - 5.47119e-5 * S ** 3 + 1.55586e-6 * S ** 4)
    mu1 = A * T ** B
    mu = mu1 * (0.9994 + 4.0295e-5 * p + 3.1062e-9 * p ** 2)
    return {"bw": bw, "rho_w": rho_sc / bw, "mu_w": mu}
