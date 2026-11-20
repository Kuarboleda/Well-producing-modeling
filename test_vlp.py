"""Quick checks for vlp.py.  Run:  python test_vlp.py   (needs pvt.py and well.py in the same folder)

Where the expected numbers come from
    * "published"  : values printed in the Beggs & Brill worked examples (Brill & Mukherjee),
                     or the horizontal example in the open-source 'fluids' library.
                     (The Hagedorn & Brown curve-fit formulas are the published ones; the
                     H&B gradient checks are "hand" calculations done step by step.)
    * "hand"       : worked out with a calculator; the arithmetic is in the comments.
    * "physics"    : things that must be true (e.g. a vertical column of water gives
                     hydrostatic pressure; more heat loss cannot heat the fluid).
A check passes when the code agrees to within 0.1 % unless a different tolerance is shown.
If a check fails, the script stops and tells you which one.
"""
import math

import pvt
from vlp import *
from vlp import (_bb_limits, _bb_n_lv, _bb_horizontal_holdup, _bb_inclination_c,
                 _bb_holdup_one_regime, _bb_holdup, _bb_flow_regime)
from well import Well, vertical_survey, simple_tubing


def check(name, got, expected, tol=0.001):
    """Pass if 'got' is within tol (0.001 = 0.1 %) of 'expected' (exactly 0 -> within 1e-6)."""
    if expected == 0:
        ok = abs(got) <= 1e-6
    else:
        ok = abs(got - expected) <= tol * abs(expected)
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<52s} got {got:12.6g}   expected {expected:12.6g}")
    assert ok, name


def check_true(name, condition):
    print(f"  {'PASS' if condition else 'FAIL'}  {name}")
    assert condition, name


def check_equal(name, got, expected):
    ok = got == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<52s} got {got!s:>12}   expected {expected!s:>12}")
    assert ok, name


def check_raises(name, error_type, function, *args, **kwargs):
    """Pass if calling function(...) raises the given kind of error."""
    try:
        function(*args, **kwargs)
    except error_type:
        print(f"  PASS  {name:<52s} ({error_type.__name__} raised, as wanted)")
        return
    raise AssertionError(f"{name}: expected a {error_type.__name__} but none was raised")


# =====================================================================
print("== Friction factor ==")
# Colebrook, smooth pipe: Re = 1e5 -> 0.01799 ; Re = 1e6 -> 0.011645  (Moody chart: 0.018 and 0.0116)
# Fully rough, e/D = 0.01: f = 1 / (2*log10(3.7/0.01))^2 = 0.03790
check("smooth pipe, Re = 1e5", friction_factor(1e5, 0.0), 0.01799)
check("smooth pipe, Re = 1e6", friction_factor(1e6, 0.0), 0.011645)
check("fully rough, e/D = 0.01", friction_factor(1e8, 0.01), 0.03790)
check("laminar, Re = 1000: 64/Re", friction_factor(1000.0), 0.064)
check("no jump at Re = 2100", friction_factor(2100.001, 0.0), friction_factor(2099.999, 0.0), tol=0.001)
check("no jump at Re = 4000", friction_factor(3999.999, 0.0), friction_factor(4000.001, 0.0), tol=0.001)

print("\n== Surface tension ==")
# Oil, 35 API:  sigma(68F) = 39 - 0.2571*35 = 30.0015 ; sigma(100F) = 37.5 - 0.2571*35 = 28.5015
#   at 80 F: 30.0015 - 1.5 * (12/32) = 29.439      (pressure 0 -> no dissolved-gas reduction)
check("oil sigma at 60 F (held at the 68 F value)", sigma_oil_gas(35, 60, 0), 30.0015)
check("oil sigma at 80 F", sigma_oil_gas(35, 80, 0), 29.439)
check("oil sigma at 120 F (held at the 100 F value)", sigma_oil_gas(35, 120, 0), 28.5015)
check("oil sigma never below 1 dyne/cm (high pressure)", sigma_oil_gas(35, 80, 5000), 1.0)
# Water at p = 0: 75 dyne/cm at 74 F, 53 at 280 F, halfway (177 F) = 64
check("water sigma at 60 F", sigma_water_gas(60, 0), 75.0)
check("water sigma at 177 F", sigma_water_gas(177, 0), 64.0)
check("water sigma at 300 F", sigma_water_gas(300, 0), 53.0)

# =====================================================================
print("\n== Beggs & Brill: published worked examples ==")
# Example 5 (Brill & Mukherjee / Economides): no-slip liquid fraction 0.345 -> L1 = 229.14
check("published: L1 at lambda = 0.345", _bb_limits(0.345)[0], 229.14)
# Liquid velocity number: v_sL = 7.25 ft/s, rho_L = 47.42 lb/ft3, sigma = 29 dyne/cm -> NLv = 15.88
check("published: NLv", _bb_n_lv(7.25, 47.42, 29.0), 15.88, tol=0.002)
# Worked example: lambda = 0.35, NFr = 29.6, NLv = 10.28, intermittent, vertical upward
check("published: horizontal holdup (intermittent) 0.454",
      _bb_horizontal_holdup("intermittent", 0.35, 29.6), 0.454, tol=0.005)
check("published: C = 0.0351",
      _bb_inclination_c("intermittent", 0.35, 10.28, 29.6, math.radians(90)), 0.0351, tol=0.005)
check("published: holdup at 90 deg = 0.459",
      _bb_holdup_one_regime("intermittent", 0.35, 29.6, 10.28, math.radians(90)), 0.459, tol=0.005)

print("\n== Beggs & Brill: flow pattern map ==")
# lambda = 0.35:  L1 = 316*0.35^0.302 = 230.0 ; L2 = 0.0009252*0.35^-2.4684 = 0.01235 ; L3 = 0.1*0.35^-1.4516 = 0.4589
check_equal("lambda 0.35, NFr 29.6  (published example)", _bb_flow_regime(0.35, 29.6), "intermittent")
check_equal("lambda 0.35, NFr 0.005 (below L2)", _bb_flow_regime(0.35, 0.005), "segregated")
check_equal("lambda 0.35, NFr 0.2   (between L2 and L3)", _bb_flow_regime(0.35, 0.2), "transition")
check_equal("lambda 0.35, NFr 500   (above L1)", _bb_flow_regime(0.35, 500.0), "distributed")
# lambda = 0.001 (below 0.01): L1 = 316*0.001^0.302 = 39.3
check_equal("lambda 0.001, NFr 10 (below L1)", _bb_flow_regime(0.001, 10.0), "segregated")
check_equal("lambda 0.001, NFr 50 (above L1)", _bb_flow_regime(0.001, 50.0), "distributed")
# lambda = 0.5 (above 0.4): intermittent between L3 and L4
check_equal("lambda 0.5, NFr 5", _bb_flow_regime(0.5, 5.0), "intermittent")

print("\n== Beggs & Brill: holdup has no jumps between flow patterns ==")
l1, l2, l3, l4 = _bb_limits(0.35)
for angle in (90.0, 30.0, -30.0):
    th = math.radians(angle)
    check(f"holdup continuous at L2 ({angle:+.0f} deg)",
          _bb_holdup(0.35, l2 * (1 + 1e-9), 10.0, th)[1], _bb_holdup(0.35, l2 * (1 - 1e-9), 10.0, th)[1], tol=1e-6)
    check(f"holdup continuous at L3 ({angle:+.0f} deg)",
          _bb_holdup(0.35, l3 * (1 + 1e-9), 10.0, th)[1], _bb_holdup(0.35, l3 * (1 - 1e-9), 10.0, th)[1], tol=1e-6)

# =====================================================================
print("\n== Beggs & Brill gradient: published horizontal example ==")
# Example in the 'fluids' library documentation (SI units): m = 0.6 kg/s, gas quality 0.1,
# rho_L = 915, rho_G = 2.67 kg/m3, mu_L = 180e-6, mu_G = 14e-6 Pa s, sigma = 0.0487 N/m,
# P = 1e7 Pa, D = 0.05 m, horizontal, smooth pipe  ->  686.97 Pa per metre.
# Converted here to oilfield units, and the answer converted back.
m, x = 0.6, 0.1
D = 0.05
area = math.pi * D ** 2 / 4
FT, LB_FT3, PSI = 3.28084, 0.062428, 6894.757
c = dict(v_sl=m * (1 - x) / (915.0 * area) * FT, v_sg=m * x / (2.67 * area) * FT,
         rho_l=915.0 * LB_FT3, rho_g=2.67 * LB_FT3, mu_l=0.18, mu_g=0.014, sigma=48.7)
r = beggs_brill_gradient(1e7 / PSI, 0.0, D / 0.0254, 0.0, c)
check("published: pressure gradient in Pa/m", r["dpdl"] * PSI / 0.3048, 686.97, tol=0.002)
check_equal("published: flow pattern", r["regime"], "distributed")

print("\n== Beggs & Brill gradient: single phase, worked by hand ==")
# Water in a vertical 3.0-in pipe: rho = 62.4, mu = 1 cP, v = 0.1 ft/s, p = 1000 psia
#   hydrostatic = 62.4 / 144 = 0.43333 psi/ft ; friction is tiny (Re = 2300, about 9e-6 psi/ft)
c = dict(v_sl=0.1, v_sg=0.0, rho_l=62.4, rho_g=5.0, mu_l=1.0, mu_g=0.015, sigma=70.0)
r = beggs_brill_gradient(1000.0, 90.0, 3.0, 0.0, c)
check("water column: hydrostatic gradient", r["hydrostatic"], 0.43333)
check("water column: total gradient", r["dpdl"], 0.43334)
check_equal("water column: reported as 'liquid'", r["regime"], "liquid")
check("water column: holdup = 1", r["hl"], 1.0)
# Gas in a horizontal 3.0-in pipe: rho = 5 lb/ft3, mu = 0.015 cP, v = 20 ft/s, p = 1000 psia
#   Re = 1488.16 * 5 * 20 * 0.25 / 0.015 = 2.48e6 -> f = 0.010019 (Colebrook, smooth)
#   friction = f * rho * v^2 / (2 * 32.174 * 0.25) / 144 = 0.010019 * 5 * 400 / 16.087 / 144 = 0.0086501
#   acceleration term Ek = rho * v * v / (32.174 * 1000 * 144) = 0.00043168
#   total = 0.0086501 / (1 - 0.00043168) = 0.0086538
c = dict(v_sl=0.0, v_sg=20.0, rho_l=62.4, rho_g=5.0, mu_l=1.0, mu_g=0.015, sigma=70.0)
r = beggs_brill_gradient(1000.0, 0.0, 3.0, 0.0, c)
check("gas pipe: friction gradient", r["friction"], 0.0086501)
check("gas pipe: acceleration term Ek", r["e_k"], 0.00043168)
check("gas pipe: total gradient", r["dpdl"], 0.0086538)
check_equal("gas pipe: reported as 'gas'", r["regime"], "gas")

print("\n== Beggs & Brill gradient: two-phase physics ==")
c = dict(v_sl=1.0, v_sg=3.0, rho_l=50.0, rho_g=3.0, mu_l=2.0, mu_g=0.015, sigma=25.0)
up = beggs_brill_gradient(1000.0, 90.0, 2.992, 0.0006, c)
flat = beggs_brill_gradient(1000.0, 0.0, 2.992, 0.0006, c)
up30 = beggs_brill_gradient(1000.0, 30.0, 2.992, 0.0006, c)
down30 = beggs_brill_gradient(1000.0, -30.0, 2.992, 0.0006, c)
check_true("vertical needs more pressure than horizontal", up["dpdl"] > flat["dpdl"])
check_true("30 deg lies between horizontal and vertical", flat["dpdl"] < up30["dpdl"] < up["dpdl"])
check_true("flow downhill needs less than horizontal", down30["dpdl"] < flat["dpdl"])
check_equal("horizontal pipe: no hydrostatic part", flat["hydrostatic"], 0.0)
check("vertical hydrostatic = (rho_L*HL + rho_G*(1-HL))/144",
      up["hydrostatic"], (50.0 * up["hl"] + 3.0 * (1.0 - up["hl"])) / 144.0)
check_true("holdup lies between no-slip value and 1", 0.25 <= up["hl"] <= 1.0)
more_gas = dict(c, v_sg=8.0)
check_true("more gas makes the vertical column lighter",
           beggs_brill_gradient(1000.0, 90.0, 2.992, 0.0006, more_gas)["dpdl"] < up["dpdl"])
check_true("higher pressure makes the (compressible) acceleration term smaller",
           beggs_brill_gradient(3000.0, 90.0, 2.992, 0.0006, c)["e_k"] < up["e_k"])

# =====================================================================
print("\n== Fluid conditions: oil + water ==")
API, GG, RSB, T = 35.0, 0.75, 500.0, 200.0
pb = pvt.oil_properties(3000.0, T, API, GG, RSB)["pb"]
area = math.pi * (2.992 / 12.0) ** 2 / 4.0
# Water only, 1000 STB/d at 2000 psia, 150 degF:  v = 1000 * Bw * 5.615 / 86400 / area
w = pvt.water_properties(2000.0, 150.0, 3.0)
fl = OilWaterFluid(API, GG, RSB, water_cut=1.0)
c = fl.conditions(1000.0, 2000.0, 150.0, 2.992)
check("water only: liquid superficial velocity", c["v_sl"], 1000.0 * w["bw"] * 5.615 / 86400.0 / area)
check("water only: no gas", c["v_sg"], 0.0)
check("water only: liquid density = water density", c["rho_l"], w["rho_w"])
check("water only: liquid viscosity = water viscosity", c["mu_l"], w["mu_w"])
check("water only: sigma = water/gas value", c["sigma"], sigma_water_gas(150.0, 2000.0))
# Oil well: above the bubble point all the gas is dissolved; below it free gas appears
fl = OilWaterFluid(API, GG, RSB, water_cut=0.3)
check("above Pb: no free gas", fl.conditions(1000.0, pb + 500.0, T, 2.992)["v_sg"], 0.0)
o = pvt.oil_properties(pb - 500.0, T, API, GG, RSB)
g = pvt.gas_properties(pb - 500.0, T, GG)
expected_vsg = 700.0 * (RSB - o["rs"]) * g["bg"] / 86400.0 / area    # 700 STB/d of oil
check("below Pb: free gas velocity (hand assembly)",
      fl.conditions(1000.0, pb - 500.0, T, 2.992)["v_sg"], expected_vsg)
check_true("producing GOR above Rsb adds free gas even above Pb",
           OilWaterFluid(API, GG, RSB, gor=800.0).conditions(1000.0, pb + 500.0, T, 2.992)["v_sg"] > 0)

print("\n== Mass rate and heat capacity ==")
# Oil, 1000 STB/d, 35 API (sg = 141.5/166.5 = 0.84985), GOR 500, gas sg 0.75, no water
#   oil = 1000 * 350 * 0.84985 = 297,448 lb/d ; gas = 1000 * 500 * 0.0764 * 0.75 = 28,650 lb/d
#   total = 326,098 lb/d = 13,587 lb/h ; cp = 0.5
wt, cp = OilWaterFluid(API, GG, RSB).thermal_data(1000.0)
check("oil: mass rate (lb/h)", wt, 13587.4)
check("oil: cp", cp, 0.5)
# Dry gas, 10,000 Mscf/d, sg 0.7:  10,000 * 1000 * 0.0764 * 0.7 = 534,800 lb/d = 22,283 lb/h
wt, cp = GasFluid(0.7).thermal_data(10000.0)
check("dry gas: mass rate (lb/h)", wt, 22283.3)
check("dry gas: cp", cp, 0.5)
wt_water, cp_water = OilWaterFluid(API, GG, RSB, water_cut=1.0).thermal_data(1000.0)
check("water only: cp = 1.0", cp_water, 1.0)

print("\n== Fluid conditions: gas ==")
gas = GasFluid(0.65)
g = pvt.gas_properties(1500.0, 150.0, 0.65)
c = gas.conditions(5000.0, 1500.0, 150.0, 2.992)
check("dry gas: gas velocity = rate * Bg / area", c["v_sg"], 5000.0 * 1000.0 * g["bg"] / 86400.0 / area)
check("dry gas: no liquid", c["v_sl"], 0.0)
check("dry gas: gas density", c["rho_g"], g["rho_g"])
wet = GasFluid(0.65, cgr=50.0, wgr=10.0).conditions(5000.0, 1500.0, 150.0, 2.992)
check_true("wet gas: liquid is present", wet["v_sl"] > 0)
# 5000 Mscf/d = 5 MMscf/d -> 250 STB/d condensate + 50 STB/d water = 300 STB/d
w = pvt.water_properties(1500.0, 150.0, 3.0)
check("wet gas: liquid velocity (hand)", wet["v_sl"], (250.0 * 5.615 + 50.0 * w["bw"] * 5.615) / 86400.0 / area)

# =====================================================================
print("\n== Pressure traverse: water column (vertical, 8000 ft, 2.992-in tubing) ==")
# Water at 1000 STB/d.  Expected: Pwf = Pwh + rho*TVD/144 + friction gradient * MD,
# with the density taken at the average pressure and temperature of the traverse.
wl = Well(*vertical_survey(8000), simple_tubing(2.992, 8000), 200.0)
fl = OilWaterFluid(API, GG, RSB, water_cut=1.0)


def expected_water_pwf(well, rate, p_wh, result, tvd_total, md_total):
    """Hydrostatic + friction for a single-phase water column (hand formula)."""
    p_avg = sum(result["p"]) / len(result["p"])
    t_avg = sum(result["T"]) / len(result["T"])
    wp = pvt.water_properties(p_avg, t_avg, 3.0)
    d_in = well.tubing[0][2]
    v = rate * wp["bw"] * 5.615 / 86400.0 / (math.pi * (d_in / 12.0) ** 2 / 4.0)
    re = RE_CONST * wp["rho_w"] * v * (d_in / 12.0) / wp["mu_w"]
    f = friction_factor(re, well.roughness_in / d_in)
    fric = f * wp["rho_w"] * v ** 2 / (2.0 * GC * d_in / 12.0) / 144.0
    return p_wh + wp["rho_w"] * tvd_total / 144.0 + fric * md_total


res = pressure_traverse(wl, fl, 1000.0, 200.0)
check("Pwf = Pwh + hydrostatic + friction", res["pwf"], expected_water_pwf(wl, 1000.0, 200.0, res, 8000.0, 8000.0), tol=0.003)
check("pressure at the wellhead is the input", res["p"][0], 200.0)
check("last temperature is the reservoir temperature", res["T"][-1], 200.0)
check("last depth is the perforations", res["md"][-1], 8000.0)
check_true("pressure rises all the way down", all(res["p"][i] < res["p"][i + 1] for i in range(len(res["p"]) - 1)))
check_true("holdup is 1 everywhere (water only)", all(abs(h - 1.0) < 1e-9 for h in res["holdup"]))

print("\n== Pressure traverse: deviated water column ==")
# MD 0-2000 vertical, then 2000-8000 at sin(angle) = 4500/6000 = 0.75 -> TVD = 6500 ft
wd = Well([0.0, 2000.0, 8000.0], [0.0, 2000.0, 6500.0], simple_tubing(2.992, 8000), 200.0)
res = pressure_traverse(wd, fl, 1000.0, 200.0)
check("deviated: Pwf = Pwh + rho*TVD/144 + friction*MD", res["pwf"],
      expected_water_pwf(wd, 1000.0, 200.0, res, 6500.0, 8000.0), tol=0.003)
check_true("deviated well needs less pressure than the vertical one", res["pwf"] < pressure_traverse(wl, fl, 1000.0, 200.0)["pwf"])

print("\n== Pressure traverse: almost static gas column ==")
# At a tiny rate friction vanishes and  Pwf = Pwh * exp(0.01875 * sg * TVD / (Z_avg * T_avg))  (T in degR)
gas = GasFluid(0.65)
res = pressure_traverse(wl, gas, 100.0, 1000.0)
t_avg = sum(res["T"]) / len(res["T"]) + 460.0
pw = 1000.0
for _ in range(50):                                                # Z depends on pressure, so repeat
    z = pvt.gas_properties(0.5 * (1000.0 + pw), t_avg - 460.0, 0.65)["z"]
    pw = 1000.0 * math.exp(0.01875 * 0.65 * 8000.0 / (z * t_avg))
check("static gas column formula", res["pwf"], pw, tol=0.003)
wet_res = pressure_traverse(wl, GasFluid(0.65, cgr=50.0, wgr=10.0), 5000.0, 1000.0)
dry_res = pressure_traverse(wl, gas, 5000.0, 1000.0)
check_true("wet gas needs more bottom-hole pressure than dry gas", wet_res["pwf"] > dry_res["pwf"])

print("\n== Pressure traverse: oil well ==")
oil = OilWaterFluid(API, GG, RSB, water_cut=0.2)
rates = [500.0, 1000.0, 2000.0, 4000.0]
pwfs = vlp_curve(wl, oil, rates, 200.0)
print("  rate (STB/d) -> Pwf (psia):", ", ".join(f"{q:.0f} -> {p:.0f}" for q, p in zip(rates, pwfs)))
check_true("VLP is J-shaped: low rate needs more Pwf than mid rate (slippage)", pwfs[0] > pwfs[1])
check_true("VLP is J-shaped: high rate needs more Pwf again (friction)", pwfs[3] > pwfs[2])
check_true("every Pwf is above the wellhead pressure", all(p > 200.0 for p in pwfs))
check("vlp_curve equals the single traverse", pwfs[2], pressure_traverse(wl, oil, 2000.0, 200.0)["pwf"], tol=1e-9)
check("result hardly depends on step size (50 ft vs 200 ft)",
      pressure_traverse(wl, oil, 2000.0, 200.0, max_step_ft=50.0)["pwf"],
      pressure_traverse(wl, oil, 2000.0, 200.0, max_step_ft=200.0)["pwf"], tol=0.003)
more = pressure_traverse(wl, oil, 2000.0, 300.0)["pwf"] - pressure_traverse(wl, oil, 2000.0, 200.0)["pwf"]
check_true("+100 psi at the wellhead gives more than +100 psi at the bottom (denser mixture)", 100.0 < more < 300.0)
wh = Well([0.0, 8000.0], [0.0, 0.0], simple_tubing(2.992, 8000), 200.0)
res_h = pressure_traverse(wh, oil, 2000.0, 200.0)
check_true("horizontal well: pressure drop is friction only (< 20 % of the vertical one)",
           res_h["pwf"] - 200.0 < 0.2 * (pwfs[2] - 200.0))
check_true("holdup stays between 0 and 1", all(0.0 <= h <= 1.0 for h in res["holdup"] + res_h["holdup"]))

# =====================================================================
print("\n== Hagedorn & Brown: the three chart curve fits ==")
# "chart" : points that can be read from the original H&B charts (and from the fits' own formulas).
check("CN_L at N_L = 0.002 (chart starts at about 0.002)", hb_cn_l(0.002), 0.0020006)
# N_L = 0.1 : 0.061e-3 - 0.0929e-2 + 0.00505 + 0.0019 = 0.0060810
check("CN_L at N_L = 0.1 (hand)", hb_cn_l(0.1), 0.006081)
check_true("CN_L grows with N_L (viscous liquids)", hb_cn_l(0.01) < hb_cn_l(0.1) < hb_cn_l(0.5))
check("HL/psi at H = 0 is 0 (no liquid, no holdup)", hb_holdup_over_psi(0.0), 0.0, tol=1e-9)
# values read from Fig. 13 of SPE 940 at the low end, where the published fit is not used
check_true("HL/psi at H = 1e-7 close to the chart (0.010 +- 0.01)", abs(hb_holdup_over_psi(1e-7) - 0.0101) < 0.01)
check_true("HL/psi at H = 1e-6 close to the chart (0.032 +- 0.01)", abs(hb_holdup_over_psi(1e-6) - 0.0318) < 0.01)
check_true("HL/psi has no jump where the chart piece meets the fit (1e-5)",
           abs(hb_holdup_over_psi(1e-5 * 0.999999) - hb_holdup_over_psi(1e-5)) < 1e-4)
_wet = dict(v_sl=3e-4, v_sg=30.0, rho_l=50.0, rho_g=3.0, mu_l=2.0, mu_g=0.015, sigma=25.0, frac_w=0.0)
_hb = hagedorn_brown_gradient(1000.0, 90.0, 2.992, 0.0018, _wet)
check_true("H&B wet gas (0.01 % liquid): holdup well under 1 %", _hb["hl"] < 0.01)
_gr = gray_gradient(1000.0, 90.0, 2.992, 0.0018, _wet)
check("H&B wet gas gradient within 5 % of Gray", _hb["dpdl"], _gr["dpdl"], tol=0.05)
check("HL/psi at H = 0.01 is 1 (chart top)", hb_holdup_over_psi(0.01), 1.0, tol=0.001)
check_true("HL/psi rises with H", hb_holdup_over_psi(1e-5) < hb_holdup_over_psi(1e-4) < hb_holdup_over_psi(1e-3))
check("psi at B = 0 is 1", hb_psi(0.0), 0.9999)
# B = 0.025: first piece 0.42453 - 0.19845 + 0.01368 + 0.9999 = 1.23966 ; second piece gives 1.24686
check("psi at B = 0.025 (first piece, hand)", hb_psi(0.025), 1.23966)
check("psi pieces join at B = 0.025 (within 1 %)", hb_psi(0.025), hb_psi(0.0250001), tol=0.01)
check("psi pieces join at B = 0.055 (within 1 %)", hb_psi(0.055), hb_psi(0.0550001), tol=0.01)
# B = 0.09 : 2.5714 * 0.09 + 1.5962 = 1.82763
check("psi at B = 0.09 (last piece, hand)", hb_psi(0.09), 1.82763)

print("\n== Hagedorn & Brown: dimensionless numbers (hand-worked) ==")
# 2.992 in pipe (0.24933 ft), rho_l = 50, sigma = 30, mu_l = 2, vsl = 1.5, vsg = 3.0, p = 1000
#   (rho_l/sigma)^0.25 = 1.13622 ; N_Lv = 1.938*1.5*1.13622 = 3.30299 ; N_gv = 6.60598
#   N_d = 120.872 * 0.24933 * 1.29099 = 38.9072 ; N_L = 0.15726*2*0.029337 = 0.0092271
c = dict(v_sl=1.5, v_sg=3.0, rho_l=50.0, rho_g=3.0, mu_l=2.0, mu_g=0.015, sigma=30.0)
num = hb_numbers(1000.0, 2.992 / 12.0, c)
check("N_Lv", num["n_lv"], 3.30299)
check("N_gv", num["n_gv"], 6.60598)
check("N_d", num["n_d"], 38.9072)
check("N_L", num["n_l"], 0.0092271)
check("CN_L", num["cn_l"], 0.0023581)
check("H group", num["h"], 1.03097e-4)
check("B group", num["b"], 4.11582e-3)

print("\n== Hagedorn & Brown: pressure gradient (hand-worked) ==")
# Case A: ordinary H&B regime, vertical.  Hand steps (numbers above):
#   HL/psi = 0.338291 ; psi = 0.998668 ; HL = 0.337841 (above the no-slip value 0.3333, so kept)
#   rho_ns = 18.6667 ; rho_s = 18.8785 ; mu_s = 2^0.337841 * 0.015^0.662159 = 0.078340
#   Re = 1488.16*18.6667*4.5*0.24933/0.07834 = 397,857 ; f(Colebrook, e/D = 0.0006/2.992) = 0.015773
#   hydrostatic = 18.8785/144 = 0.131101 ; friction = f*rho_ns^2*vm^2/(2*gc*d*rho_s)/144 = 0.0025517
#   Ek = 5.5009e-5 ; dp/dL = (0.131101 + 0.0025517) / (1 - 5.5009e-5) = 0.133660
r = hagedorn_brown_gradient(1000.0, 90.0, 2.992, 0.0006, c)
check_equal("A: regime", r["regime"], "hagedorn")
check("A: liquid holdup", r["hl"], 0.337841)
check("A: Reynolds number", r["re"], 397857.0)
check("A: friction factor", r["f_tp"], 0.015773)
check("A: hydrostatic gradient (psi/ft)", r["hydrostatic"], 0.131101)
check("A: friction gradient (psi/ft)", r["friction"], 0.0025517)
check("A: total gradient (psi/ft)", r["dpdl"], 0.133660)
# Case B: Griffith bubble flow.  p = 500, vsl = 1.0, vsg = 0.1, vm = 1.1
#   LB = max(1.071 - 0.2218*1.21/0.24933, 0.13) = 0.13 ; gas fraction 0.0909 < 0.13 -> bubble flow
#   x = 1 + 1.1/0.8 = 2.375 ; HL = 1 - 0.5*(2.375 - sqrt(5.640625 - 0.5)) = 0.946147
#   vL = 1.0/0.946147 = 1.05692 ; Re = 1488.16*50*1.05692*0.24933/2 = 9804.2 ; f = 0.031351
#   friction = f*50*vL^2/(2*gc*d)/144 = 7.5792e-4 ; rho_s = 47.4689 ; hydrostatic = 0.329645
cb = dict(v_sl=1.0, v_sg=0.1, rho_l=50.0, rho_g=3.0, mu_l=2.0, mu_g=0.015, sigma=30.0)
r = hagedorn_brown_gradient(500.0, 90.0, 2.992, 0.0006, cb)
check_equal("B: regime", r["regime"], "bubble")
check("B: Griffith holdup", r["hl"], 0.946147)
check("B: Reynolds number (liquid at in-situ velocity)", r["re"], 9804.2)
check("B: hydrostatic gradient (psi/ft)", r["hydrostatic"], 0.329645)
check("B: friction gradient (psi/ft)", r["friction"], 7.5792e-4)
check("B: total gradient (psi/ft)", r["dpdl"], 0.330404)
check("Griffith: no gas -> holdup 1", griffith_bubble_holdup(1.0, 0.0), 1.0)
# Case C: the holdup would come out below the no-slip fraction, so it is raised to it.
#   vsl = vsg = 2.0 : H = 1.7355e-4, B = 3.0609e-3, HL/psi = 0.427595, psi = 0.999379 -> HL = 0.42733 < 0.5
cc = dict(v_sl=2.0, v_sg=2.0, rho_l=50.0, rho_g=3.0, mu_l=2.0, mu_g=0.015, sigma=30.0)
r = hagedorn_brown_gradient(1000.0, 90.0, 2.992, 0.0006, cc)
check_equal("C: holdup raised to the no-slip value 0.5", r["hl"], 0.5)
check_true("holdup never above 1 (very viscous, high H)",
           hagedorn_brown_gradient(1000.0, 90.0, 2.992, 0.0006,
                                   dict(v_sl=0.9, v_sg=0.3, rho_l=50.0, rho_g=3.0, mu_l=2.0, mu_g=0.015, sigma=30.0))["hl"] <= 1.0)
# Case D: liquid only: friction of a single liquid, Re = 27,829, f = 0.0244186, friction = 0.0047562
r = hagedorn_brown_gradient(1000.0, 90.0, 2.992, 0.0006, dict(c, v_sl=3.0, v_sg=0.0))
check_equal("D: regime", r["regime"], "liquid")
check("D: total gradient = 50/144 + friction", r["dpdl"], 0.351978)
# Case E: gas only, vsg = 20 ft/s: Re = 1.48419e6, f = 0.014407, friction = 0.0074830,
#   hydrostatic = 3/144 = 0.0208333, Ek = 2.59e-4
r = hagedorn_brown_gradient(1000.0, 90.0, 2.992, 0.0006, dict(c, v_sl=0.0, v_sg=20.0))
check_equal("E: regime", r["regime"], "gas")
check("E: total gradient", r["dpdl"], 0.0283237)
# Angle: hydrostatic part scales with sin(angle), friction does not change
r30 = hagedorn_brown_gradient(1000.0, 30.0, 2.992, 0.0006, c)
check("30 degrees: hydrostatic = vertical * sin(30)", r30["hydrostatic"], 0.131101 * 0.5)
check("30 degrees: friction unchanged", r30["friction"], 0.0025517)
rd = hagedorn_brown_gradient(1000.0, -30.0, 2.992, 0.0006, c)
check_true("downhill flow: hydrostatic term is negative", rd["hydrostatic"] < 0)
check_raises("H&B: no flow", ValueError, hagedorn_brown_gradient, 1000.0, 90.0, 3.0, 0.0,
             dict(v_sl=0.0, v_sg=0.0, rho_l=62.4, rho_g=5.0, mu_l=1.0, mu_g=0.015, sigma=70.0))

print("\n== Hagedorn & Brown: pressure traverse ==")
res = pressure_traverse(wl, fl, 1000.0, 200.0, "hagedorn_brown")
check("water column: Pwf = Pwh + hydrostatic + friction", res["pwf"],
      expected_water_pwf(wl, 1000.0, 200.0, res, 8000.0, 8000.0), tol=0.003)
check_true("water column: holdup is 1 everywhere", all(abs(h - 1.0) < 1e-9 for h in res["holdup"]))
res = pressure_traverse(wl, gas, 100.0, 1000.0, "hagedorn_brown")
check("almost static gas column (same formula as above)", res["pwf"], pw, tol=0.003)
hb_pwfs = vlp_curve(wl, oil, rates, 200.0, "hagedorn_brown")
print("  H&B rate (STB/d) -> Pwf (psia):", ", ".join(f"{q:.0f} -> {p:.0f}" for q, p in zip(rates, hb_pwfs)))
check_true("oil well: every Pwf is above the wellhead pressure", all(p > 200.0 for p in hb_pwfs))
check_true("oil well: VLP is J-shaped (high rate needs more Pwf again)", hb_pwfs[3] > hb_pwfs[2])
# Beggs & Brill is known to over-predict holdup (so Pwf) in vertical wells, most at low rate:
# here H&B comes out 8 % (4000 STB/d) to 27 % (500 STB/d) lower.  Only a sanity band is checked.
check_true("oil well: H&B and Beggs & Brill are within 35 % of each other (same order)",
           all(abs(h - b) < 0.35 * b for h, b in zip(hb_pwfs, pwfs)))
check_true("oil well: the gap between the two shrinks as the rate rises",
           abs(hb_pwfs[3] - pwfs[3]) / pwfs[3] < abs(hb_pwfs[0] - pwfs[0]) / pwfs[0])
check("result hardly depends on step size (50 ft vs 200 ft)",
      pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 50.0)["pwf"],
      pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0)["pwf"], tol=0.003)
res_d = pressure_traverse(wd, oil, 2000.0, 200.0, "hagedorn_brown")
check_true("deviated well needs less pressure than the vertical one",
           res_d["pwf"] < pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown")["pwf"])
check_true("holdup stays between 0 and 1 (all steps, deviated well)", all(0.0 <= h <= 1.0 for h in res_d["holdup"]))
wet_hb = pressure_traverse(wl, GasFluid(0.65, cgr=50.0, wgr=10.0), 5000.0, 1000.0, "hagedorn_brown")
check_true("wet gas needs more bottom-hole pressure than dry gas",
           wet_hb["pwf"] > pressure_traverse(wl, gas, 5000.0, 1000.0, "hagedorn_brown")["pwf"])

print("\n== Gray: holdup and effective roughness (hand-worked) ==")
# 2.992 in pipe (0.24933 ft), rho_l = 50, rho_g = 3, sigma = 20 dyne/cm = 0.044092 lbm/s2
# Case A: vsl = 0.05, vsg = 40 ft/s -> R = 0.00125, no-slip liquid fraction 0.0012484, rho_ns = 3.05868
#   N_v = rho_ns^2 vm^4 / (g sigma drho) = 361,006 ; N_D = g drho d^2 / sigma = 2132.08
#   B = 0.0814 (1 - 0.0554 ln(1 + 730 R/(R+1))) = 0.0784786
#   f1 = -2.314 (N_v (1 + 205/N_D))^B = -6.36266 ; HL = 1 - (1 - e^f1)/(R+1) = 0.00297107
check("A: B", 0.0814 * (1.0 - 0.0554 * math.log(1.0 + 730.0 * 0.00125 / 1.00125)), 0.0784786)
check("A: holdup", gray_holdup(0.00125, 361006.0, 2132.08), 0.00297107)
check_true("holdup is never below the no-slip fraction R/(R+1) (the equation guarantees it)",
           all(gray_holdup(rr, nv_, 2132.08) >= rr / (rr + 1.0) for rr in (1e-4, 1e-3, 0.01, 0.1) for nv_ in (1.0, 1e3, 1e6)))
check_true("holdup grows when the velocity number falls (more liquid left behind)",
           gray_holdup(0.05, 0.5, 2132.08) > gray_holdup(0.05, 5e4, 2132.08) > gray_holdup(0.05, 5e6, 2132.08))
#   k0 = 28.5 sigma / (rho_ns vm^2) = 28.5 * 0.044092 / (3.05868 * 40.05^2) = 2.56133e-4 ft
#   R < 0.007 : k_e = k + R (k0 - k)/0.007 with k = 0.0018/12 = 1.5e-4 ft -> 1.68952e-4 ft
check("A: effective roughness (blend)", gray_effective_roughness(0.00125, 1.5e-4, 0.044092, 3.05868, 40.05), 1.68952e-4)
check("R = 0: the pipe's own roughness", gray_effective_roughness(0.0, 1.5e-4, 0.044092, 3.05868, 40.05), 1.5e-4)
# Case B: R = 0.025 (>= 0.007) -> k_e = k0 = 28.5 * 0.044092 / (4.14634 * 20.5^2) = 7.2116e-4 ft
check("B: effective roughness (R >= 0.007)", gray_effective_roughness(0.025, 1.5e-4, 0.044092, 4.14634, 20.5), 7.2116e-4)
check("effective roughness never below 2.77e-5 ft", gray_effective_roughness(0.5, 1.5e-4, 0.044092, 5.0, 500.0), 2.77e-5)

print("\n== Gray: pressure gradient (hand-worked) ==")
cg = dict(v_sl=0.05, v_sg=40.0, rho_l=50.0, rho_g=3.0, mu_l=2.0, mu_g=0.015, sigma=20.0)
# Case A (continued): Re = 2.60058e6, f(Colebrook, k_e/d = 6.7765e-4) = 0.0180607
#   rho_s = 50*0.00297107 + 3*(1 - 0.00297107) = 3.13964 -> hydrostatic = 0.0218031
#   friction = f rho_ns vm^2 / (2 gc d) / 144 = 0.0383526 ; Ek = 0.00108561 ; dp/dL = 0.0602211
r = gray_gradient(1000.0, 90.0, 2.992, 0.0018, cg)
check_equal("A: regime", r["regime"], "gray")
check("A: liquid holdup", r["hl"], 0.00297107)
check("A: effective roughness (ft)", r["k_eff"], 1.68952e-4)
check("A: Reynolds number", r["re"], 2.60058e6)
check("A: friction factor", r["f_tp"], 0.0180607)
check("A: hydrostatic gradient (psi/ft)", r["hydrostatic"], 0.0218031)
check("A: friction gradient (psi/ft)", r["friction"], 0.0383526)
check("A: total gradient (psi/ft)", r["dpdl"], 0.0602211)
# Case B: vsl = 0.5, vsg = 20 (R = 0.025): HL = 0.0321225, k_e = 7.2116e-4, f = 0.0261839, dp/dL = 0.0510864
r = gray_gradient(1000.0, 90.0, 2.992, 0.0018, dict(cg, v_sl=0.5, v_sg=20.0))
check("B: liquid holdup", r["hl"], 0.0321225)
check("B: friction factor", r["f_tp"], 0.0261839)
check("B: total gradient (psi/ft)", r["dpdl"], 0.0510864)
# Case C: vsl = 0.05, vsg = 1 (very slow): k0 = 0.2176 ft is wider than the pipe, so the
#   relative roughness is capped at 0.05: f = 0.0727725, HL = 0.150541, dp/dL = 0.0701503
r = gray_gradient(1000.0, 90.0, 2.992, 0.0018, dict(cg, v_sg=1.0))
check("C: liquid holdup", r["hl"], 0.150541)
check("C: friction factor with the 0.05 cap", r["f_tp"], 0.0727725)
check("C: total gradient (psi/ft)", r["dpdl"], 0.0701503)
# Gas only: the same single-phase gas as Beggs & Brill, so the two must agree
cgas = dict(cg, v_sl=0.0, v_sg=40.0)
rg = gray_gradient(1000.0, 90.0, 2.992, 0.0018, cgas)
check_equal("gas only: regime", rg["regime"], "gas")
check("gas only: same as Beggs & Brill", rg["dpdl"], beggs_brill_gradient(1000.0, 90.0, 2.992, 0.0018, cgas)["dpdl"], tol=1e-9)
rl_ = gray_gradient(1000.0, 90.0, 2.992, 0.0018, dict(cg, v_sl=3.0, v_sg=0.0))
check_equal("liquid only: regime", rl_["regime"], "liquid")
check("liquid only: same as Beggs & Brill", rl_["dpdl"], beggs_brill_gradient(1000.0, 90.0, 2.992, 0.0018, dict(cg, v_sl=3.0, v_sg=0.0))["dpdl"], tol=1e-9)
check("30 degrees: hydrostatic = vertical * sin(30)", gray_gradient(1000.0, 30.0, 2.992, 0.0018, cg)["hydrostatic"], 0.0218031 * 0.5)
check_raises("Gray: no flow", ValueError, gray_gradient, 1000.0, 90.0, 3.0, 0.0,
             dict(v_sl=0.0, v_sg=0.0, rho_l=62.4, rho_g=5.0, mu_l=1.0, mu_g=0.015, sigma=70.0))

print("\n== Gray: pressure traverse ==")
gas_gray = pressure_traverse(wl, gas, 100.0, 1000.0, "gray")
check("almost static dry gas column (same formula as above)", gas_gray["pwf"], pw, tol=0.003)
check("dry gas: Gray = Beggs & Brill (single-phase gas)", pressure_traverse(wl, gas, 5000.0, 1000.0, "gray")["pwf"],
      pressure_traverse(wl, gas, 5000.0, 1000.0)["pwf"], tol=1e-9)
wet_gray = pressure_traverse(wl, GasFluid(0.65, cgr=5.0, wgr=1.0), 5000.0, 1000.0, "gray")
check_true("lean wet gas: Gray is close to dry gas (within 5 %)",
           abs(wet_gray["pwf"] - pressure_traverse(wl, gas, 5000.0, 1000.0, "gray")["pwf"]) < 0.05 * wet_gray["pwf"])
check_true("holdup stays between 0 and 1", all(0.0 <= h <= 1.0 for h in wet_gray["holdup"]))
# The old repeat-until-it-stops loop gave up here: 6 in tubing at 400,000 Mscf/d has a
# wellhead gas velocity of several hundred ft/s and the bottom-pressure search zig-zagged.
very_fast = pressure_traverse(Well(*vertical_survey(5000), simple_tubing(2.441, 5000), 180.0),
                              GasFluid(0.65, cgr=5.0), 150000.0, 500.0, "gray")
check_true("very high gas rate still converges", very_fast["pwf"] > 500.0)

print("\n== Pressure traverse: a correlation with a tiny jump must not crash ==")
# Some correlations jump a little where one formula hands over to the next, so the bottom-pressure
# guess can flip between two nearly equal values for ever.  A made-up gradient shows how that is handled:
#   gradient = 0.404 psi/ft when the average pressure is below 220.1 psia, otherwise 0.400.
# Step 1 (100 ft, top at 200 psia): the bottom-pressure search closes on the jump at 240.2 psia
# (the residual is 0.2 psi on either side, below the 0.5 psi allowed);
# the other 79 steps are above 220.1 psia and add 40.0 each:  200 + 40.2 + 79 * 40 = 3400.2
def jumpy_gradient(size_of_jump):
    def gradient(p, angle_deg, d_in, roughness_in, c):
        return {"dpdl": 0.40 if p >= 220.1 else 0.40 + size_of_jump, "hl": 1.0}
    return gradient


try:
    GRADIENT_FUNCS["jumpy_small"] = jumpy_gradient(0.004)
    GRADIENT_FUNCS["jumpy_big"] = jumpy_gradient(0.02)
    res = pressure_traverse(wl, oil, 1000.0, 200.0, "jumpy_small", 100.0)
    check("jump of 0.4 psi: the step settles at the jump", res["pwf"], 3400.2, tol=1e-4)
    # A jump of 2 psi at 240 psia (0.8 % of the pressure) has no exact answer in a 100 ft step.  The step is cut in halves until the
    # jump is small enough to accept (_step_with_split).  The first 47.6 ft are in the 0.42 psi/ft region (it ends where the
    # average pressure reaches 220.1: 200 + 0.42 x = 240.2 gives x = 47.6 ft), so the extra pressure is 0.02 x 47.6 = 0.95 psi:
    # 3400 + 0.95 = 3400.95 psia (within the 0.5 psi that a closed jump is allowed to differ by)
    res_big = pressure_traverse(wl, oil, 1000.0, 200.0, "jumpy_big", 100.0)
    check("jump of 2 psi: the step is cut in halves and settles at the jump", res_big["pwf"], 3400.95, tol=3e-4)
    # a gradient that flips between 50.4 and 0.4 psi/ft has no solution however short the step (3 ft after five halvings):
    # it is still reported, not hidden
    GRADIENT_FUNCS["jumpy_huge"] = jumpy_gradient(50.0)
    check_raises("a jump of 50 psi/ft: reported as no convergence", RuntimeError,
                 pressure_traverse, wl, oil, 1000.0, 200.0, "jumpy_huge", 100.0)
finally:
    GRADIENT_FUNCS.pop("jumpy_small", None)
    GRADIENT_FUNCS.pop("jumpy_big", None)
    GRADIENT_FUNCS.pop("jumpy_huge", None)

# The same 2 psi jump at 1,460 psia is only 0.15 % of the pressure.  This happened for real with Beggs and
# Brill, where the gradient jumps by about 2 psi per 100 ft where the flow pattern changes from intermittent to
# distributed.  The step must settle at the jump instead of stopping the whole calculation.
def jump_at_1460(p, angle_deg, d_in, roughness_in, c):
    return {"dpdl": 0.282 if p < 1463.0 else 0.2599, "hl": 1.0}


try:
    GRADIENT_FUNCS["jump_deep"] = jump_at_1460
    one_step = {"md_top": 0.0, "md_bot": 100.0, "tvd_top": 0.0, "tvd_bot": 100.0, "length": 100.0,
                "angle_deg": 90.0, "id_in": 2.992}
    from vlp import _step_bottom_pressure
    p_bottom, _ = _step_bottom_pressure(jump_at_1460, oil, 1000.0, 1449.3, 190.0, one_step, 0.0006)
    check_true("a 2 psi jump at 1,460 psia (0.15 %) is accepted, within 2.2 psi of both sides",
               1449.3 + 26.0 < p_bottom < 1449.3 + 28.3)

    # Here the gradient is SMALLER below the jump (0.2599) and larger above it (0.2820), so the residual is
    # negative on both sides of the jump and the true answer lies further down:
    # There are two self-consistent answers: 1475.29 psia (0.2599 * 100 = 25.99 psi, average 1462.3, below the
    # jump) and 1477.50 psia (0.282 * 100 = 28.2 psi, average 1463.4, above the jump).  Either is acceptable;
    # what matters is that the search ends instead of bouncing between two points for ever.
    def jump_other_way(p, angle_deg, d_in, roughness_in, c):
        return {"dpdl": 0.2599 if p < 1463.386 else 0.282, "hl": 1.0}
    p_bottom, _ = _step_bottom_pressure(jump_other_way, oil, 1000.0, 1449.3, 190.0, one_step, 0.0006)
    check_true("a jump with a negative residual on both sides ends with one of the two valid answers",
               abs(p_bottom - 1475.29) < 0.01 or abs(p_bottom - 1477.5) < 0.01)
finally:
    GRADIENT_FUNCS.pop("jump_deep", None)

# =====================================================================
print("\n== VLP matching multipliers at the gradient level (exact) ==")
# At fixed conditions the gravity and friction parts must scale EXACTLY with their multipliers, and
# the total must be rebuilt the same way as inside each correlation: (gravity + friction) / (1 - e_k).
from vlp import _with_multipliers
# 500 psi below the bubble point there is free gas: real two-phase flow
P_TEST = pb - 500.0
c_oil = OilWaterFluid(API, GG, RSB, water_cut=0.3).conditions(1000.0, P_TEST, 150.0, 2.992)
check_true("the test condition has free gas", c_oil["v_sg"] > 0)
for name, func in GRADIENT_FUNCS.items():
    base_res = func(P_TEST, 60.0, 2.992, 0.0006, c_oil)
    scaled = _with_multipliers(func, 1.1, 1.3)(P_TEST, 60.0, 2.992, 0.0006, c_oil)
    check(f"{name}: gravity part x 1.1", scaled["hydrostatic"], 1.1 * base_res["hydrostatic"], tol=1e-12)
    check(f"{name}: friction part x 1.3", scaled["friction"], 1.3 * base_res["friction"], tol=1e-12)
    check(f"{name}: total rebuilt from the scaled parts", scaled["dpdl"],
          (1.1 * base_res["hydrostatic"] + 1.3 * base_res["friction"]) / (1.0 - base_res["e_k"]), tol=1e-12)
    check(f"{name}: holdup untouched", scaled["hl"], base_res["hl"], tol=1e-12)
check_true("multipliers of exactly 1 and 1 return the very same function", _with_multipliers(beggs_brill_gradient, 1.0, 1.0) is beggs_brill_gradient)

# =====================================================================
print("\n== Gravity / friction split of the pressure drop ==")
# pwf - p_wh = gravity part + friction part + a small acceleration part, for every correlation.
for corr in ("beggs_brill", "hagedorn_brown"):
    res = pressure_traverse(wl, oil, 2000.0, 200.0, corr)
    parts = res["dp_hydrostatic"] + res["dp_friction"]
    check(f"{corr}: gravity + friction is close to the whole pressure drop", parts, res["pwf"] - 200.0, tol=0.02)
    check_true(f"{corr}: gravity part is the big one in a vertical oil well", res["dp_hydrostatic"] > res["dp_friction"] > 0)
res = pressure_traverse(wd, oil, 2000.0, 200.0, "hagedorn_brown")
res_v = pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown")
# wd has TVD 6500 ft against 8000 ft for the vertical well, so it must have less gravity pressure.
# Its average gravity gradient (psi per ft of TVD) must be physical: below water (0.433) and above gas.
check_true("deviated well: less gravity pressure than the deeper vertical well", res["dp_hydrostatic"] < res_v["dp_hydrostatic"])
check_true("deviated well: average gravity gradient between 0.1 and 0.433 psi/ft", 0.1 < res["dp_hydrostatic"] / 6500.0 < 0.433)

# =====================================================================
print("\n== Orkiszewski (1967, SPE 1546) ==")
# "published": Appendix D of the paper, Well 22, first increment (670 psia at the wellhead, a 100 psi step, mean
# pressure 720 psia).  The paper's flowing properties there are:  q_L = 0.129 and q_g = 0.199 ft3/s in a pipe of
# 0.0488 ft2 (0.249 ft), rho_L = 55.8, rho_g = 2.84 lb/ft3, liquid viscosity 18 cP, sigma = 0.0582 lbm/s2 (26.4 dyne/cm),
# relative roughness 0.0006.  The paper rounds its numbers and reads the friction factor from a chart, so the
# agreement asked for is that of its rounding (a fraction of a percent to about 2 %).
AP_O, D_O = 0.0488, 0.249
c_o = dict(v_sl=0.129 / AP_O, v_sg=0.199 / AP_O, rho_l=55.8, rho_g=2.84, mu_l=18.0, mu_g=0.012,
           sigma=0.0582 / 0.0022046, frac_w=0.0)
fp = ork_flow_regime(c_o["v_sl"], c_o["v_sg"], 55.8, 0.0582, D_O)
check_equal("Appendix D: flow pattern is slug", fp["regime"], "slug")
check("Appendix D: dimensionless gas velocity v_gD (B-1) = 9.53", fp["v_gd"], 9.53, tol=0.005)
check("Appendix D: slug/transition boundary (L)s (B-3) = 272", fp["l_s"], 272.0, tol=0.005)
check("Appendix D: bubble boundary is held at its lower limit 0.13", fp["l_b"], 0.13)
o_ex = orkiszewski_gradient(720.0, 90.0, D_O * 12.0, 0.0006 * D_O * 12.0, c_o)
check("Appendix D: Reynolds number (C-6) = 7720", o_ex["re"], 7720.0, tol=0.001)
check("Appendix D: bubble rise velocity (C-7) = 1.74 ft/s", o_ex["v_b"], 1.74, tol=0.005)
check("Appendix D: liquid distribution coefficient (C-13) = -0.097", o_ex["gamma"], -0.097, tol=0.015)
check("Appendix D: friction factor (paper reads 0.034 from a chart)", o_ex["f_tp"], 0.034, tol=0.015)
check("Appendix D: average density (C-4) = 24.9 lb/ft3", o_ex["hydrostatic"] * 144.0, 24.9, tol=0.01)
check("Appendix D: friction gradient (C-10) = 2.26 lbf/ft2/ft", o_ex["friction"] * 144.0, 2.26, tol=0.025)
check("Appendix D: depth for a 100 psi step (A-3) = 529 ft", 100.0 / o_ex["dpdl"], 529.0, tol=0.015)

# "hand": bubble flow (vertical, 3.0 in, q_g/q_t = 0.09 < 0.13).  Slip 0.8 ft/s:
#   x = 1 + 3.3/0.8 = 5.125;  F_g = (x - sqrt(x^2 - 4*0.3/0.8))/2 = 0.074246;  density = 0.925754*50 + 0.074246*2 = 46.4362
#   v_L = 3.0/(1 - 0.074246) = 3.2406 ft/s;  Re = 1488.16*50*0.25*3.2406/2 = 30141;  f (Colebrook, 0.0006/3) = 0.023994
#   friction = f*50*3.2406^2/(2*32.174*0.25) = 0.78314 lbf/ft2/ft
c_b = dict(v_sl=3.0, v_sg=0.3, rho_l=50.0, rho_g=2.0, mu_l=2.0, mu_g=0.012, sigma=30.0)
o_b = orkiszewski_gradient(1000.0, 90.0, 3.0, 0.0006, c_b)
check_equal("bubble flow: pattern", o_b["regime"], "bubble")
check("bubble flow: density", o_b["hydrostatic"] * 144.0, 46.4362, tol=1e-5)
check("bubble flow: Reynolds number", o_b["re"], 30141.0, tol=1e-4)
check("bubble flow: friction gradient", o_b["friction"] * 144.0, 0.78314, tol=1e-4)
check("inclined 30 degrees: gravity part is sin(30) of the vertical one", orkiszewski_gradient(1000.0, 30.0, 3.0, 0.0006, c_b)["hydrostatic"], 0.5 * o_b["hydrostatic"], tol=1e-9)

# "hand": mist flow (almost all gas), sigma = 30 dyne/cm = 0.066138 lbm/s2.  Gas Reynolds number 1488.16*1*0.25*100/0.012.
#   N_w = 4.52e-7 (v_g mu_L / sigma)^2 rho_g/rho_L = 4.52e-7 * (100*1/0.066138)^2 / 50 = 0.0207  (above 0.005, so C-22)
#   e/D = 174.8 sigma N_w^0.302 / (rho_g v_g^2 d) = 174.8*0.066138*0.0207^0.302/(1*100^2*0.25) = 0.001440
c_m = dict(v_sl=0.05, v_sg=100.0, rho_l=50.0, rho_g=1.0, mu_l=1.0, mu_g=0.012, sigma=30.0)
o_m = orkiszewski_gradient(500.0, 90.0, 3.0, 0.0006, c_m)
check_equal("mist flow: pattern", o_m["regime"], "mist")
sig = 30.0 * 0.0022046
n_w = 4.52e-7 * (100.0 * 1.0 / sig) ** 2 * 1.0 / 50.0
check("mist flow: N_w (hand 0.0207)", n_w, 0.0207, tol=0.01)
eps_m = 174.8 * sig * n_w ** 0.302 / (1.0 * 100.0 ** 2 * 0.25)
check("mist flow: relative roughness of Duns-Ros, C-22 (hand 0.00144)", eps_m, 0.00144, tol=0.01)
fg_m = 100.0 / 100.05
rho_m = (1 - fg_m) * 50.0 + fg_m * 1.0
f_m = friction_factor(1488.16 * 1.0 * 0.25 * 100.0 / 0.012, eps_m)
check("mist flow: no-slip density", o_m["hydrostatic"] * 144.0, rho_m, tol=1e-9)
check("mist flow: friction uses the gas (C-20)", o_m["friction"] * 144.0, f_m * 1.0 * 100.0 ** 2 / (2 * 32.174 * 0.25), tol=1e-9)
# a thin liquid (0.5 cP, N_w below 0.005): C-21, e/D = 34 sigma / (rho_g v_g^2 d) = 34*0.066138/(1*60^2*0.25) = 0.002499
c_m2 = dict(v_sl=0.02, v_sg=60.0, rho_l=50.0, rho_g=1.0, mu_l=0.5, mu_g=0.012, sigma=30.0)
o_m2 = orkiszewski_gradient(500.0, 90.0, 3.0, 0.0006, c_m2)
check_equal("mist flow, thin liquid: pattern", o_m2["regime"], "mist")
f_m2 = friction_factor(1488.16 * 1.0 * 0.25 * 60.0 / 0.012, 34.0 * sig / (1.0 * 60.0 ** 2 * 0.25))
check("mist flow, thin liquid: roughness from C-21", o_m2["friction"] * 144.0, f_m2 * 1.0 * 60.0 ** 2 / (2 * 32.174 * 0.25), tol=1e-9)
c_g = dict(c_m, v_sl=0.0)
o_g = orkiszewski_gradient(500.0, 90.0, 3.0, 0.0006, c_g)
check_equal("gas only: pattern", o_g["regime"], "gas")
check("gas only: density is the gas density", o_g["hydrostatic"] * 144.0, 1.0, tol=1e-9)
o_l = orkiszewski_gradient(1000.0, 90.0, 3.0, 0.0006, dict(c_b, v_sg=0.0, rho_l=62.4))
check("liquid only: the weight of the liquid", o_l["hydrostatic"], 62.4 / 144.0, tol=1e-9)

# Continuity: the transition region joins the slug region and the mist region (C-17 weights with v_gD)
def edge(which, v_sl=0.5, **extra):
    """gas velocity (ft/s) at which v_gD equals (L)s or (L)m, found by halving the interval"""
    lo, hi = 1.0, 500.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        f_ = ork_flow_regime(v_sl, mid, 50.0, 0.066138, 0.25)
        if f_["v_gd"] < f_["l_s" if which == "s" else "l_m"]:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
c_t = dict(v_sl=0.5, v_sg=1.0, rho_l=50.0, rho_g=3.0, mu_l=1.0, mu_g=0.012, sigma=30.0)
for which, label in (("s", "slug / transition"), ("m", "transition / mist")):
    v_edge = edge(which)
    below = orkiszewski_gradient(800.0, 90.0, 3.0, 0.0006, dict(c_t, v_sg=v_edge * (1 - 1e-7)))
    above = orkiszewski_gradient(800.0, 90.0, 3.0, 0.0006, dict(c_t, v_sg=v_edge * (1 + 1e-7)))
    check_true(f"{label}: patterns on the two sides ({below['regime']} / {above['regime']})",
               {below["regime"], above["regime"]} == ({"slug", "transition"} if which == "s" else {"transition", "mist"}))
    check(f"{label}: the gradient is continuous", below["dpdl"], above["dpdl"], tol=1e-3)
# halfway through the transition region the density is the mean of the slug and the mist values (C-17)
v_mid = 0.5 * (edge("s") + edge("m"))
f_mid = ork_flow_regime(0.5, v_mid, 50.0, 0.066138, 0.25)
w_s = (f_mid["l_m"] - f_mid["v_gd"]) / (f_mid["l_m"] - f_mid["l_s"])
check_true("transition: weight of the slug value is between 0 and 1", 0.0 < w_s < 1.0)

# Bubble rise velocity: the equation for 3000 < N_b < 8000 (C-9) must join C-7 and C-8 at the two ends
d_t, rho_t = 0.249, 55.0
root_t = math.sqrt(32.174 * d_t)
v7, v8 = 0.546 * root_t, 0.35 * root_t                                   # C-7 and C-8 at N_Re = 0
mu_3000 = 1488.16 * rho_t * d_t * v7 / 3000.0
mu_8000 = 1488.16 * rho_t * d_t * v8 / 8000.0
check("bubble rise: C-7 at N_b below 3000", ork_bubble_rise_velocity(rho_t, mu_3000 * 1.001, d_t, 1e-9), v7, tol=1e-3)
check("bubble rise: C-9 joins C-7 at N_b = 3000", ork_bubble_rise_velocity(rho_t, mu_3000 * 0.999, d_t, 1e-9), v7, tol=0.02)
check("bubble rise: C-9 joins C-8 at N_b = 8000", ork_bubble_rise_velocity(rho_t, mu_8000 * 1.001, d_t, 1e-9), v8, tol=0.04)
check("bubble rise: C-8 above N_b = 8000", ork_bubble_rise_velocity(rho_t, mu_8000 * 0.5, d_t, 1e-9), v8, tol=1e-3)

# The limits on the liquid distribution coefficient (C-15, C-16) hold in every slug case of a grid
bad = 0
n_slug = 0
for v_sl in (0.05, 0.3, 1.0, 3.0, 8.0):
    for v_sg in (0.2, 1.0, 3.0, 8.0, 14.0, 25.0):
        for mu in (0.5, 3.0, 40.0, 400.0):
            for frac_w in (0.0, 0.9):
                cc = dict(v_sl=v_sl, v_sg=v_sg, rho_l=52.0, rho_g=4.0, mu_l=mu, mu_g=0.013, sigma=30.0, frac_w=frac_w)
                r_ = orkiszewski_gradient(900.0, 90.0, 2.992, 0.0018, cc)
                if r_["regime"] not in ("slug", "transition"):
                    continue
                n_slug += 1
                vt_ = v_sl + v_sg
                rho_ = r_["hydrostatic"] * 144.0 if r_["regime"] == "slug" else None
                if r_["gamma"] < -0.065 * vt_ - 1e-9:
                    bad += 1
                if rho_ is not None and vt_ > 10.0:
                    share = r_["v_b"] / (vt_ + r_["v_b"])
                    if r_["gamma"] < -share * (1.0 - rho_ / 52.0) - 1e-9:
                        bad += 1
                if not (r_["dpdl"] > 0 and r_["friction"] >= 0):
                    bad += 1
check_true(f"Gamma limits C-15 / C-16 and positive gradients in {n_slug} slug/transition cases", n_slug > 30 and bad == 0)

# Whole-well check: Well 22 of the paper (Table 3): 1850 STB/d, GOR 575, 18.7 API, gas gravity 0.75, wellhead 670 psia,
# 3890 ft, 2.988 in tubing, 126 -> 150 degF.  The measured pressure drop was about 800 psi (Fig. 14).  Our own PVT
# correlations replace the paper's (Frick's) charts, so only the right size is asked: within 10 %, and closer than
# Hagedorn & Brown, which the paper found to over-predict this heavy-oil well.
w22 = Well(md=[0.0, 3890.0], tvd=[0.0, 3890.0], tubing=[(0.0, 3890.0, 2.988)], t_reservoir=150.0, roughness_in=0.0018,
           ambient_table=[(0.0, 126.0, 50.0), (3890.0, 150.0, 50.0)])
for visc in ("beal", "beggs"):
    f22 = OilWaterFluid(api=18.7, gas_sg=0.75, rsb=575.0, water_cut=0.0, visc_method=visc)
    dp_o = pressure_traverse(w22, f22, 1850.0, 670.0, "orkiszewski")["pwf"] - 670.0
    dp_h = pressure_traverse(w22, f22, 1850.0, 670.0, "hagedorn_brown")["pwf"] - 670.0
    check(f"Well 22 pressure drop, {visc} viscosity (measured ~800 psi)", dp_o, 800.0, tol=0.10)
    check_true(f"Well 22: closer to the measurement than Hagedorn & Brown ({dp_o:.0f} against {dp_h:.0f} psi)", abs(dp_o - 800.0) < abs(dp_h - 800.0))

# Through the traverse: gas lift gas, VLP multipliers, a deviated well, and the physical shape of a VLP curve
res_o = pressure_traverse(wl, oil, 2000.0, 200.0, "orkiszewski")
check_true("traverse: Pwf above the wellhead pressure, split into gravity and friction", res_o["pwf"] > 200.0 and res_o["dp_hydrostatic"] > res_o["dp_friction"] > 0)
check_true("traverse: gravity multiplier 1.1 raises Pwf", pressure_traverse(wl, oil, 2000.0, 200.0, "orkiszewski", gravity_mult=1.1)["pwf"] > res_o["pwf"])
gl_o = copy.deepcopy(oil) if "copy" in globals() else None
import copy as _copy
gl_o = _copy.deepcopy(oil)
gl_o.injection_gas_rate, gl_o.injection_md = 1500.0, 6000.0
check_true("traverse: gas lift lowers Pwf", pressure_traverse(wl, gl_o, 2000.0, 200.0, "orkiszewski")["pwf"] < res_o["pwf"])
check_true("traverse: deviated well has less gravity pressure than the vertical one",
           pressure_traverse(wd, oil, 2000.0, 200.0, "orkiszewski")["dp_hydrostatic"] < res_o["dp_hydrostatic"])
rates_o = [100.0 * 1.6 ** k for k in range(10)]
pw_o = vlp_curve(wl, oil, rates_o, 200.0, "orkiszewski")
check_true("VLP curve converges at every rate (including the bubble/slug jump at low rates)", len(pw_o) == 10 and all(p > 200.0 for p in pw_o))

# =====================================================================
print("\n== Hagedorn & Brown checked against the paper (SPE 940) ==")
# Values read from the paper's own charts (page 481: Figs. 9, 12 and 13), by measuring the curve on the printed page.
# Our three chart fits must stay close to them.
for n_l_, cn_paper in [(0.0114, 0.00247), (0.0335, 0.00341), (0.0982, 0.00638), (0.2013, 0.00913), (0.4127, 0.01107)]:
    check(f"Fig. 12 viscosity coefficient CN_L at N_L = {n_l_}", hb_cn_l(n_l_), cn_paper, tol=0.08)
check("CN_L is held flat beyond the end of Fig. 12 (N_L = 0.5)", hb_cn_l(0.9), hb_cn_l(0.5), tol=1e-12)
for b_, psi_paper in [(0.02, 1.105), (0.03, 1.40), (0.04, 1.595), (0.06, 1.75), (0.08, 1.814)]:
    check(f"Fig. 9 secondary correction psi at B = {b_}", hb_psi(b_), psi_paper, tol=0.02)
# Fig. 13: the published curve fit is a little above the chart in the middle of the range (by up to 0.09 in HL/psi,
# about 10 %); it is kept because it is closer to PROSPER's own Hagedorn & Brown (see the PROSPER tutorials test).
worst13 = 0.0
for h_, v_paper in [(1.03e-5, 0.133), (2.8e-5, 0.181), (7.4e-5, 0.264), (1.2e-4, 0.327), (3.2e-4, 0.502), (8.6e-4, 0.721), (2.3e-3, 0.855)]:
    worst13 = max(worst13, abs(hb_holdup_over_psi(h_) - v_paper))
check_true(f"Fig. 13 holdup factor HL/psi: the fit stays within 0.10 of the chart (worst {worst13:.3f})", worst13 < 0.10)
# Eq. 15 of the paper (the correlating function in field units; its D is in ft) against our dimensionless numbers
qL_, WOR_, Bo_, Bw_, p_, T_, Z_, rhoL_, sig_, D_in_, GLR_, Rs_, muL_ = 2500.0, 0.25, 1.2, 1.02, 800.0, 560.0, 0.9, 48.0, 28.0, 2.992, 700.0, 250.0, 3.0
cn_ = hb_cn_l(0.15726 * muL_ * (1 / (rhoL_ * sig_ ** 3)) ** 0.25)
eq15 = (0.00326 * qL_ ** 0.425 * ((1 / (1 + WOR_)) * Bo_ + (WOR_ / (1 + WOR_)) * Bw_) * p_ ** 0.675 * sig_ ** 0.394 * cn_
        / ((D_in_ / 12.0) ** 1.85 * (T_ * Z_) ** 0.575 * rhoL_ ** 0.394 * (GLR_ - Rs_ / (1 + WOR_)) ** 0.575))
A_ = math.pi * (D_in_ / 12.0) ** 2 / 4.0
v_sl_ = qL_ * ((1 / (1 + WOR_)) * Bo_ + (WOR_ / (1 + WOR_)) * Bw_) * 5.615 / 86400.0 / A_
v_sg_ = qL_ * (GLR_ - Rs_ / (1 + WOR_)) * (14.7 / p_) * (T_ / 520.0) * Z_ / 86400.0 / A_
num_ = hb_numbers(p_, D_in_ / 12.0, dict(v_sl=v_sl_, v_sg=v_sg_, rho_l=rhoL_, rho_g=1.0, mu_l=muL_, mu_g=0.01, sigma=sig_))
check("Eq. 15: the paper's field-unit correlating function equals our N_LV/N_GV^0.575 (p/pa)^0.1 CN_L/N_D", num_["h"], eq15, tol=0.02)

# =====================================================================
print("\n== Ansari et al. (1994, SPE 20630) ==")
from vlp import ans_flow_pattern, ans_annular_film_thickness, ansari_gradient, _ans_slug, _ans_core, GRAY_SIGMA_UNIT
G_A = 32.174
SIG_A = 25.0 * 0.0022046                     # 25 dyne/cm in lbm/s2
RL_A, RG_A, ML_A, MG_A = 50.0, 3.0, 2.0, 0.015
D_A = 0.25                                    # 3 in
EPS_A = 0.0006
V0_A = (G_A * SIG_A * (RL_A - RG_A) / RL_A ** 2) ** 0.25        # [g sigma d_rho / rho_L^2]^0.25, ft/s


def pattern(v_sl, v_sg, d=D_A):
    return ans_flow_pattern(v_sl, v_sg, RL_A, RG_A, ML_A, MG_A, SIG_A, d, EPS_A, math.pi / 2)


# "hand": the boundaries of the flow-pattern map (Eqs. 1, 2, 3, 6)
fp_a = pattern(0.5, 0.2)
check("bubble rise velocity, Eq. 3: 1.53 [g sigma d_rho/rho_L^2]^0.25", fp_a["v_s"], 1.53 * V0_A, tol=1e-9)
check("minimum bubble diameter, Eq. 1: 19.01 sqrt(d_rho sigma/(rho_L^2 g))", fp_a["d_min"],
      19.01 * math.sqrt((RL_A - RG_A) * SIG_A / (RL_A ** 2 * G_A)), tol=1e-9)
check("bubble/slug boundary, Eq. 2: 0.25 v_s + 0.333 v_SL", fp_a["v_sg_a"], 0.25 * 1.53 * V0_A + 0.333 * 0.5, tol=1e-9)
check("annular boundary, Eq. 6: 3.1 [g sigma d_rho/rho_g^2]^0.25", fp_a["v_sg_d"],
      3.1 * (G_A * SIG_A * (RL_A - RG_A) / RG_A ** 2) ** 0.25, tol=1e-9)
check_equal("just below the bubble/slug boundary: bubble", pattern(0.5, 0.99 * fp_a["v_sg_a"])["regime"], "bubble")
check_equal("just above the bubble/slug boundary: slug", pattern(0.5, 1.01 * fp_a["v_sg_a"])["regime"], "slug")
check_equal("pipe narrower than d_min (1 in): no bubble flow, slug", pattern(0.5, 0.5 * fp_a["v_sg_a"], d=1.0 / 12.0)["regime"], "slug")
fp_b = pattern(0.05, 1.0)
check_equal("below the annular boundary of Eq. 6: not annular", pattern(0.05, 0.99 * fp_b["v_sg_d"])["regime"], "slug")
# Above Eq. 6 the flow is annular only once the film that the annular model finds (Eq. 93) is thin enough not to bridge the
# pipe (film + core liquid <= 0.12, Eq. 12).  Find that gas velocity by halving.
lo_, hi_ = 1.01 * fp_b["v_sg_d"], 200.0
for _ in range(60):
    mid_ = 0.5 * (lo_ + hi_)
    if pattern(0.05, mid_)["regime"] == "annular":
        hi_ = mid_
    else:
        lo_ = mid_
an_lo = ans_annular_film_thickness(0.05, lo_, RL_A, RG_A, ML_A, MG_A, SIG_A, D_A, EPS_A, math.pi / 2)
an_hi = ans_annular_film_thickness(0.05, hi_, RL_A, RG_A, ML_A, MG_A, SIG_A, D_A, EPS_A, math.pi / 2)
check_true(f"annular starts at v_Sg = {hi_:.1f} ft/s (Eq. 6 gives {fp_b['v_sg_d']:.1f}): the film holdup there is {an_hi['holdup']:.3f}, "
           f"just before it {an_lo['holdup']:.3f} (limit 0.12)", an_hi["holdup"] <= 0.12 < an_lo["holdup"])
check_equal("well above that velocity: still annular", pattern(0.05, 3.0 * hi_)["regime"], "annular")
# dispersed bubble: Eq. 4 at v_SL = 12, v_Sg = 3 ft/s, hand evaluation
v_m_d = 15.0
f_d = friction_factor(1488.16 * RL_A * v_m_d * D_A / ML_A, EPS_A)
lhs_d = 2.0 * (0.4 * SIG_A / ((RL_A - RG_A) * G_A)) ** 0.5 * (RL_A / SIG_A) ** 0.6 * (f_d / (2 * D_A)) ** 0.4 * v_m_d ** 1.2
rhs_d = 0.725 + 4.15 * math.sqrt(3.0 / v_m_d)
check_true(f"dispersed bubble: Eq. 4 left side {lhs_d:.2f} >= right side {rhs_d:.2f}, so dispersed", lhs_d >= rhs_d and pattern(12.0, 3.0)["regime"] == "dispersed")
check_true("below Eq. 4 (v_SL = 8, v_Sg = 2 ft/s): not dispersed", pattern(8.0, 2.0)["regime"] != "dispersed")
check_true("no dispersed bubble above 3.17 v_SL (Eq. 5), even at a high liquid rate", pattern(3.0, 10.0)["regime"] != "dispersed")

# "hand": bubble flow, v_SL = 3, v_Sg = 0.3 ft/s: holdup from Eq. 22, no-slip friction on the mixture (Eqs. 23 - 28)
c_ab = dict(v_sl=3.0, v_sg=0.3, rho_l=RL_A, rho_g=RG_A, mu_l=ML_A, mu_g=MG_A, sigma=25.0)
a_b = ansari_gradient(1000.0, 90.0, 3.0, EPS_A * 3.0, c_ab)
check_equal("bubble flow: pattern", a_b["regime"], "bubble")
h_b = a_b["hl"]
check("bubble flow: holdup satisfies Eq. 22 (residual)", 1.53 * V0_A * math.sqrt(h_b) - (0.3 / (1 - h_b) - 1.2 * 3.3), 0.0)
rho_b = RL_A * h_b + RG_A * (1 - h_b)
mu_b = ML_A * h_b + MG_A * (1 - h_b)
f_b = friction_factor(1488.16 * rho_b * 3.3 * D_A / mu_b, EPS_A)
check("bubble flow: elevation gradient rho_TP", a_b["hydrostatic"] * 144.0, rho_b, tol=1e-9)
check("bubble flow: friction gradient f rho v^2/(2 d)", a_b["friction"] * 144.0, f_b * rho_b * 3.3 ** 2 / (2 * G_A * D_A), tol=1e-9)
check("bubble flow: no acceleration term", a_b["e_k"], 0.0)
check("inclined 30 degrees: gravity part is sin(30) of the vertical one",
      ansari_gradient(1000.0, 30.0, 3.0, EPS_A * 3.0, c_ab)["hydrostatic"], 0.5 * a_b["hydrostatic"], tol=1e-9)
c_ad = dict(c_ab, v_sl=12.0, v_sg=3.0)
a_d = ansari_gradient(1000.0, 90.0, 3.0, EPS_A * 3.0, c_ad)
check_equal("dispersed bubble: pattern", a_d["regime"], "dispersed")
check("dispersed bubble: no-slip density (Eqs. 16, 19)", a_d["hydrostatic"] * 144.0, 0.8 * RL_A + 0.2 * RG_A, tol=1e-9)

# slug flow: the solution must satisfy all eight equations of the paper (29 - 35, 37, 38), for several rates.
worst = 0.0
n_dev = n_full = 0
for v_sl_, v_sg_ in [(1.0, 0.5), (1.0, 3.0), (2.0, 6.0), (0.3, 2.0), (0.05, 3.0), (0.1, 1.0), (0.5, 8.0), (4.0, 3.0)]:
    s_ = _ans_slug(v_sl_, v_sg_, RL_A, RG_A, ML_A, MG_A, SIG_A, D_A, EPS_A)
    b_, hl_, hls_ = s_["beta"], s_["h_ltb"], 1.0 - s_["h_gls"]
    v_m_ = v_sl_ + v_sg_
    res_ = [v_sg_ - (b_ * s_["v_gtb"] * (1 - hl_) + (1 - b_) * s_["v_gls"] * (1 - hls_)),                  # Eq. 29
            v_sl_ - ((1 - b_) * s_["v_lls"] * hls_ - b_ * s_["v_ltb"] * hl_),                              # Eq. 30
            (s_["v_tb"] - s_["v_lls"]) * hls_ - (s_["v_tb"] + s_["v_ltb"]) * hl_,                          # Eq. 32
            (s_["v_tb"] - s_["v_gls"]) * (1 - hls_) - (s_["v_tb"] - s_["v_gtb"]) * (1 - hl_),              # Eq. 33
            s_["v_tb"] - (1.2 * v_m_ + 0.35 * math.sqrt(G_A * D_A * (RL_A - RG_A) / RL_A)),                # Eq. 34
            s_["v_gls"] - (1.2 * v_m_ + 1.53 * V0_A * math.sqrt(hls_)),                                    # Eq. 35
            s_["v_ltb"] - 9.916 * math.sqrt(G_A * D_A * (1 - math.sqrt(1 - hl_))),                         # Eq. 37
            (1 - s_["h_gls"]) - (1 - v_sg_ / (0.425 + 2.65 * v_m_))]                                       # Eq. 38
    worst = max(worst, max(abs(x) for x in res_))
    n_dev += s_["developing"]
    n_full += not s_["developing"]
check_true(f"slug flow: equations 29 - 35, 37, 38 all satisfied (largest residual {worst:.1e})", worst < 1e-9)
check_true(f"slug flow: both developing ({n_dev}) and fully developed ({n_full}) Taylor bubbles occur in the test cases", n_dev > 0 and n_full > 0)
# hand values for v_SL = 1, v_Sg = 3 ft/s:  v_m = 4;  v_TB = 1.2*4 + 0.35 sqrt(32.174*0.25*47/50) = 5.7621
#   H_gLS = 3/(0.425 + 2.65*4) = 0.26274 (Eq. 38)
s_1 = _ans_slug(1.0, 3.0, RL_A, RG_A, ML_A, MG_A, SIG_A, D_A, EPS_A)
check("slug flow: Taylor bubble rise velocity, Eq. 34 (hand 5.762)", s_1["v_tb"], 4.8 + 0.35 * math.sqrt(32.174 * 0.25 * 47.0 / 50.0), tol=1e-9)
check("slug flow: gas fraction of the liquid slug, Eq. 38 (hand 0.2627)", s_1["h_gls"], 3.0 / 11.025, tol=1e-9)
check("slug flow: liquid slug length 30 d = 7.5 ft (Eq. 48)", s_1["l_ls"], 7.5)
check("slug flow: Taylor bubble length L_TB = L_LS beta/(1 - beta) (Eq. 49)", s_1["l_tb"], 7.5 * s_1["beta"] / (1 - s_1["beta"]), tol=1e-9)
# the gradient of fully developed slug flow, Eqs. 60, 61, 65, 66
a_s = ansari_gradient(1000.0, 90.0, 3.0, EPS_A * 3.0, dict(c_ab, v_sl=1.0, v_sg=3.0))
check_equal("slug flow: pattern", a_s["regime"], "slug")
check_true("slug flow: this case is fully developed", a_s["developing"] is False)
rho_ls = RL_A * (1 - s_1["h_gls"]) + RG_A * s_1["h_gls"]
b1 = s_1["beta"]
check("slug flow: elevation density (1 - beta) rho_LS + beta rho_g (Eq. 60)", a_s["hydrostatic"] * 144.0, (1 - b1) * rho_ls + b1 * RG_A, tol=1e-9)
mu_ls = ML_A * (1 - s_1["h_gls"]) + MG_A * s_1["h_gls"]
f_ls = friction_factor(1488.16 * rho_ls * 4.0 * D_A / mu_ls, EPS_A)
check("slug flow: friction f_LS rho_LS v_m^2 (1 - beta)/(2 d) (Eq. 65)", a_s["friction"] * 144.0, f_ls * rho_ls * 16.0 / (2 * G_A * D_A) * (1 - b1), tol=1e-9)
# developing slug flow: the length of the developing Taylor bubble solves Eq. 53 (a L - 2 c sqrt(L) - b = 0)
s_d = _ans_slug(1.0, 0.5, RL_A, RG_A, ML_A, MG_A, SIG_A, D_A, EPS_A)
check_true("developing slug flow: the cap length is longer than the developed Taylor bubble (Eq. 44)", s_d["developing"] and s_d["l_c"] >= s_d["l_tb"])
a_ = 1.0 - 0.5 / s_d["v_tb"]
b_ = (0.5 - s_d["v_gls"] * s_d["h_gls"]) * s_d["l_ls"] / s_d["v_tb"]
c_ = (s_d["v_tb"] - s_d["v_lls"]) * (1.0 - s_d["h_gls"]) / math.sqrt(2 * G_A)
check("developing slug flow: Taylor bubble length satisfies Eq. 53", a_ * s_d["l_tb_star"] - 2 * c_ * math.sqrt(s_d["l_tb_star"]) - b_, 0.0)
check_true("developing slug flow: the elevation density lies between the liquid slug's and the gas's",
           RG_A < ansari_gradient(1000.0, 90.0, 3.0, EPS_A * 3.0, dict(c_ab, v_sl=1.0, v_sg=0.5))["hydrostatic"] * 144.0 < RL_A)
s_h = ansari_gradient(1000.0, 90.0, 3.0, EPS_A * 3.0, dict(c_ab, v_sl=1.0, v_sg=3.0))["hydrostatic"]
check("inclined 45 degrees, slug flow: gravity part is sin(45) of the vertical one",
      ansari_gradient(1000.0, 45.0, 3.0, EPS_A * 3.0, dict(c_ab, v_sl=1.0, v_sg=3.0))["hydrostatic"], math.sin(math.radians(45.0)) * s_h, tol=1e-9)

# annular flow: v_SL = 0.05, v_Sg = 60 ft/s.  Entrainment by hand (Eqs. 71, 72); film and core gradients must agree.
c_an = dict(c_ab, v_sl=0.05, v_sg=60.0)
a_a = ansari_gradient(1000.0, 90.0, 3.0, EPS_A * 3.0, c_an)
check_equal("annular flow: pattern", a_a["regime"], "annular")
v_crit_ = 1e4 * 60.0 * (MG_A / 1488.16) / SIG_A * math.sqrt(RG_A / RL_A)
fe_ = 1.0 - math.exp(-0.125 * (v_crit_ - 1.5))
core_ = _ans_core(0.05, 60.0, RL_A, RG_A, ML_A, MG_A, SIG_A, D_A, EPS_A)
check("annular flow: entrained fraction F_E (Eqs. 71, 72)", core_["f_e"], fe_, tol=1e-9)
lam_ = fe_ * 0.05 / (60.0 + fe_ * 0.05)
check("annular flow: liquid fraction of the core, Eq. 70", core_["lam_lc"], lam_, tol=1e-9)
check("annular flow: core density, Eq. 69", core_["rho_c"], RL_A * lam_ + RG_A * (1 - lam_), tol=1e-9)
an_ = ans_annular_film_thickness(0.05, 60.0, RL_A, RG_A, ML_A, MG_A, SIG_A, D_A, EPS_A, math.pi / 2)
dl = an_["delta"]
z_ = 1.0 + 300.0 * dl if fe_ > 0.9 else 1.0 + 24.0 * (RL_A / RG_A) ** (1.0 / 3.0) * dl
core_grad = z_ * an_["dpdl_sc"] / (1 - 2 * dl) ** 5 + an_["rho_c"]                                     # Eq. 91
film_grad = ((1 - fe_) ** 2 * (an_["f_f"] / an_["f_sl"]) / (64 * dl ** 3 * (1 - dl) ** 3) * an_["dpdl_sl"]
             - z_ / (4 * dl * (1 - dl) * (1 - 2 * dl) ** 3) * an_["dpdl_sc"] + RL_A)                   # Eq. 92
check("annular flow: core gradient (Eq. 91) = film gradient (Eq. 92)", film_grad, core_grad, tol=1e-6)
check("annular flow: gradient returned is Eq. 91", a_a["dpdl"] * 144.0, core_grad, tol=1e-9)
check_true("annular flow: the film is thin (delta/d below 0.05) and the holdup small", 0 < dl < 0.05 and a_a["hl"] < 0.12)
check("annular flow: holdup = film + core liquid", a_a["hl"], 4 * dl * (1 - dl) + lam_ * (1 - 2 * dl) ** 2, tol=1e-9)
# no liquid: gas only; no gas: liquid only
c_ag = dict(c_an, v_sl=0.0)
check("gas only: the weight of the gas", ansari_gradient(500.0, 90.0, 3.0, EPS_A * 3.0, c_ag)["hydrostatic"] * 144.0, RG_A, tol=1e-9)
a_l = ansari_gradient(1000.0, 90.0, 3.0, EPS_A * 3.0, dict(c_ab, v_sg=0.0, rho_l=62.4))
check("liquid only: the weight of the liquid", a_l["hydrostatic"] * 144.0, 62.4, tol=1e-9)
check_raises("no flow", ValueError, ansari_gradient, 1000.0, 90.0, 3.0, 0.0, dict(c_ab, v_sl=0.0, v_sg=0.0))

# robustness: many random conditions must give finite, positive gradients, and every pattern must occur
import random as _random
_random.seed(11)
n_by = {}
n_bad = 0
for _ in range(3000):
    c_r = dict(v_sl=10 ** _random.uniform(-3, 1), v_sg=10 ** _random.uniform(-2, 2.0), rho_l=_random.uniform(40, 65),
               rho_g=_random.uniform(0.2, 12.0), mu_l=10 ** _random.uniform(-0.3, 2), mu_g=0.012, sigma=_random.uniform(5, 70))
    r_r = ansari_gradient(10 ** _random.uniform(1.7, 3.5), _random.choice([90, 90, 75, 45, 15]), _random.choice([1.995, 2.992, 3.958]),
                          0.0018, c_r)
    n_by[r_r["regime"]] = n_by.get(r_r["regime"], 0) + 1
    n_bad += not (math.isfinite(r_r["dpdl"]) and r_r["dpdl"] > 0.0)
check_true(f"3000 random conditions: no failure, no negative gradient; patterns met: {sorted(n_by)}",
           n_bad == 0 and {"bubble", "dispersed", "slug", "annular"} <= set(n_by))

# Whole-well check: Well 22 of Orkiszewski's paper (see above).  The measured pressure drop was about 800 psi.  A mechanistic model
# is not tuned to this well, so it is asked only to be of the right size (within 30 %); it comes out about 25 % high, like
# Beggs & Brill and Hagedorn & Brown (24 - 26 % and 17 - 36 % high).
for visc in ("beal", "beggs"):
    f22a = OilWaterFluid(api=18.7, gas_sg=0.75, rsb=575.0, water_cut=0.0, visc_method=visc)
    dp_a = pressure_traverse(w22, f22a, 1850.0, 670.0, "ansari")["pwf"] - 670.0
    check(f"Well 22 pressure drop, {visc} viscosity (measured ~800 psi)", dp_a, 800.0, tol=0.30)

# Through the traverse: gas lift gas, VLP multipliers, a deviated well, and the shape of a VLP curve
res_a = pressure_traverse(wl, oil, 2000.0, 200.0, "ansari")
check_true("traverse: Pwf above the wellhead pressure, split into gravity and friction", res_a["pwf"] > 200.0 and res_a["dp_hydrostatic"] > res_a["dp_friction"] > 0)
check_true("traverse: gravity multiplier 1.1 raises Pwf", pressure_traverse(wl, oil, 2000.0, 200.0, "ansari", gravity_mult=1.1)["pwf"] > res_a["pwf"])
gl_a = _copy.deepcopy(oil)
gl_a.injection_gas_rate, gl_a.injection_md = 1500.0, 6000.0
check_true("traverse: gas lift lowers Pwf", pressure_traverse(wl, gl_a, 2000.0, 200.0, "ansari")["pwf"] < res_a["pwf"])
check_true("traverse: deviated well has less gravity pressure than the vertical one",
           pressure_traverse(wd, oil, 2000.0, 200.0, "ansari")["dp_hydrostatic"] < res_a["dp_hydrostatic"])
pw_a = vlp_curve(wl, oil, rates_o, 200.0, "ansari")
check_true("VLP curve converges at every rate", len(pw_a) == 10 and all(p > 200.0 for p in pw_a))
gl_hi = _copy.deepcopy(gl_a)
gl_hi.injection_gas_rate = 1000.0
check_true("gas lift: converges at 12 rates from 100 to 6000 STB/d",
           len(vlp_curve(wl, gl_hi, [100.0 * 1.45 ** k for k in range(12)], 200.0, "ansari")) == 12)

# The developed (Eq. 60) and developing (Eq. 62) slug equations do not meet where the paper switches between them,
# so _ans_slug blends them over 1 <= L_c/L_TB <= ANS_DEV_BLEND.  Without the blend a gas-lifted well showed a step
# of about 50 psi in the VLP curve between two neighbouring rates.  The curve is checked for smoothness: with the
# rate in steps of 25 STB/d, the change of slope from one step to the next must stay small (a step shows as a spike).
from vlp import _ans_blend, ANS_DEV_BLEND
check_equal("blend weight: 0 at the paper's switch point", _ans_blend(1.0), 0.0)
check_equal("blend weight: 0 below it (developed flow, the paper's Eq. 60)", _ans_blend(0.4), 0.0)
check_equal("blend weight: 1 once the cap is clearly longer (the paper's Eq. 62)", _ans_blend(ANS_DEV_BLEND + 2.0), 1.0)
check("blend weight: half way at the middle", _ans_blend(1.0 + 0.5 * (ANS_DEV_BLEND - 1.0)), 0.5, tol=1e-12)
check_true("blend weight never falls and never leaves 0 - 1",
           all(0.0 <= _ans_blend(1.0 + 0.02 * k) <= _ans_blend(1.0 + 0.02 * (k + 1)) <= 1.0 for k in range(100)))
q_sm = [100.0 + 25.0 * k for k in range(116)]                      # 100 to 2975 STB/d in steps of 25
pw_sm = vlp_curve(wl, gl_hi, q_sm, 200.0, "ansari")
d_sm = [pw_sm[k + 1] - pw_sm[k] for k in range(len(pw_sm) - 1)]
kink = max(abs(d_sm[k + 1] - d_sm[k]) for k in range(len(d_sm) - 1))
check_true(f"gas-lifted VLP curve has no step: largest change of slope {kink:.1f} psi per 25 STB/d (48 before the blend)",
           kink < 10.0)
check_true("the curve still rises all the way with rate", all(d_sm[k] > -2.0 for k in range(40, len(d_sm))))

# =====================================================================
print("\n== Duns & Ros (1963, 6th World Petroleum Congress) ==")
from vlp import (dr_numbers, dr_region_limits, dr_flow_region, dr_slip_region1, dr_slip_region2, dr_holdup,
                 dr_mist_film_roughness, duns_ros_gradient, DR_F1, DR_F2, DR_F3, DR_F4, DR_F5, DR_F6, DR_F7, DR_L1, DR_L2,
                 DR_FRICTION_F2, _dr_table, _dr_fanning, _dr_gradient_parts, _NOT_YET)

# The paper's charts were read from the scan and stored as tables.  Each table is checked against its chart.
for name, tab in (("F1", DR_F1), ("F2", DR_F2), ("F3", DR_F3), ("F4", DR_F4), ("F5", DR_F5), ("F6", DR_F6), ("F7", DR_F7),
                  ("L1", DR_L1), ("L2", DR_L2), ("f2", DR_FRICTION_F2)):
    check_true(f"chart table {name}: same number of x and y, x increasing", len(tab[0]) == len(tab[1]) and
               all(a < b for a, b in zip(tab[0], tab[0][1:])))
check("table: a node returns its own value", _dr_table(DR_F3[0][10], DR_F3), DR_F3[1][10], tol=1e-12)
x_mid = math.sqrt(DR_F3[0][10] * DR_F3[0][11])                     # halfway on the log axis -> halfway in value
check("table: straight line in log(x) between nodes", _dr_table(x_mid, DR_F3), 0.5 * (DR_F3[1][10] + DR_F3[1][11]), tol=1e-9)
check("table: below the first node the chart's end value is kept", _dr_table(1e-6, DR_F1), DR_F1[1][0], tol=1e-12)
check("table: above the last node the chart's end value is kept", _dr_table(50.0, DR_F1), DR_F1[1][-1], tol=1e-12)
# Fig. 5 landmarks (left axis F1, F2, F3; right axis F4): F1 starts near 1.25 and peaks near 2.0 at N_l = 0.15,
# F2 starts at 0.24 and peaks near 1.0, F3 climbs from 0.82 to about 4.1, F4 rises to a plateau near 55
check("Fig. 5: F1 at N_l = 0.003 (chart reads 1.25)", _dr_table(0.003, DR_F1), 1.25, tol=0.03)
check("Fig. 5: F1 peak (chart reads 2.04)", max(DR_F1[1]), 2.04, tol=0.03)
check("Fig. 5: F2 at N_l = 0.003 (chart reads 0.24)", _dr_table(0.003, DR_F2), 0.24, tol=0.03)
check("Fig. 5: F2 peak (chart reads 1.0)", max(DR_F2[1]), 1.0, tol=0.03)
check("Fig. 5: F3 at N_l = 0.003 (chart reads 0.82)", _dr_table(0.003, DR_F3), 0.83, tol=0.03)
check("Fig. 5: F3 at N_l = 1.8 (chart reads 4.1)", _dr_table(1.8, DR_F3), 4.1, tol=0.03)
check("Fig. 5: F4 plateau (right axis reads 55)", _dr_table(0.5, DR_F4), 55.0, tol=0.03)
check_true("Fig. 5: F4 is zero near N_l = 0.0035 (right axis: -20 ... 100)", abs(_dr_table(0.0035, DR_F4)) < 3.0)
# Fig. 6: L1 = 2 for small pipes, falling to 1 at N_d = 80; L2 from 0.5 to 1.1
check("Fig. 6: L1 at N_d = 16 (chart reads 2.0)", _dr_table(16.0, DR_L1), 2.0, tol=0.02)
check("Fig. 6: L1 at N_d = 100 (chart reads 1.0)", _dr_table(100.0, DR_L1), 1.0, tol=0.02)
check("Fig. 6: L2 at N_d = 16 (chart reads 0.5)", _dr_table(16.0, DR_L2), 0.49, tol=0.03)
check("Fig. 6: L2 at N_d = 150 (chart reads 1.12)", _dr_table(150.0, DR_L2), 1.12, tol=0.03)
# Fig. 7: F5 falls from 0.22 to a minimum of 0.044 at N_l = 0.15; F7 falls from 0.13 to 0.023; F6 dips below zero
check("Fig. 7: F5 at N_l = 0.002 (chart reads 0.22)", _dr_table(0.002, DR_F5), 0.22, tol=0.03)
check("Fig. 7: F5 minimum (chart reads 0.044)", min(DR_F5[1]), 0.044, tol=0.05)
check("Fig. 7: F7 at N_l = 0.002 (chart reads 0.13)", _dr_table(0.002, DR_F7), 0.13, tol=0.03)
check("Fig. 7: F7 at N_l = 1.9 (chart reads 0.023)", _dr_table(1.9, DR_F7), 0.023, tol=0.03)
check_true("Fig. 7: F6 has a dip below zero near N_l = 0.015 and a peak of about 2.2 near 0.12",
           min(DR_F6[1]) < -0.05 and abs(max(DR_F6[1]) - 2.17) < 0.1)
# Fig. 9: f2 = 1 when the gas-liquid ratio is small, falling to 0.2
check("Fig. 9: f2 = 1 for small f1 R N_d^(2/3)", _dr_table(0.01, DR_FRICTION_F2), 1.0, tol=0.01)
check("Fig. 9: f2 falls to 0.2 at large f1 R N_d^(2/3)", _dr_table(500.0, DR_FRICTION_F2), 0.2, tol=0.02)
check_true("Fig. 9: f2 never above 1", max(DR_FRICTION_F2[1]) <= 1.0 + 1e-12)

# Dimensionless numbers: the paper's laboratory pipe of Fig. 3 (D = 8.02 cm, rho_L = 0.827 g/cm3, 4.2 cP, 27.5 dyne/cm).
# By hand in the paper's own cgs units:  N_d = D sqrt(rho g / sigma) = 8.02 sqrt(0.827 * 981 / 27.5) = 43.56
#   N_l = mu (g / (rho sigma^3))^0.25 with mu in poise = 0.042: 0.042 * (981 / (0.827 * 27.5^3))^0.25 = 0.00668
#   N   = v_sl (rho / (g sigma))^0.25 = 20 * (0.827 / (981 * 27.5))^0.25 = 20 * 0.07441 = 1.488  (v_sl = 20 cm/s)
RHO_FIG3 = 0.827 * 62.428
nm3 = dr_numbers(20.0 / 30.48, 1000.0 / 30.48, RHO_FIG3, 27.5, 4.2, 8.02 / 30.48)
check("Fig. 3 pipe: N_d (hand 43.56)", nm3["n_d"], 8.02 * math.sqrt(0.827 * 981.0 / 27.5), tol=0.002)
check("Fig. 3 pipe: N_l", nm3["n_l"], 0.042 * (981.0 / (0.827 * 27.5 ** 3)) ** 0.25, tol=0.002)
check("Fig. 3 pipe: liquid velocity number N (v_sl = 20 cm/s)", nm3["n"], 20.0 * (0.827 / (981.0 * 27.5)) ** 0.25, tol=0.002)
check("Fig. 3 pipe: gas velocity number RN (v_sg = 1000 cm/s)", nm3["rn"], 1000.0 * (0.827 / (981.0 * 27.5)) ** 0.25, tol=0.002)
hbn = hb_numbers(100.0, 0.2, dict(v_sl=1.3, v_sg=7.0, rho_l=50.0, sigma=30.0, mu_l=2.0))
drn = dr_numbers(1.3, 7.0, 50.0, 30.0, 2.0, 0.2)
check("same four numbers as Hagedorn & Brown: N_LV", drn["n"], hbn["n_lv"], tol=1e-12)
check("same four numbers as Hagedorn & Brown: N_GV", drn["rn"], hbn["n_gv"], tol=1e-12)
check("same four numbers as Hagedorn & Brown: N_d", drn["n_d"], hbn["n_d"], tol=1e-12)
check("same four numbers as Hagedorn & Brown: N_L", drn["n_l"], hbn["n_l"], tol=1e-12)

# Region limits (Eqs. 7 and 9) at N = 0.1:  50 + 3.6 = 53.6;  75 + 84 * 0.1^0.75 = 75 + 84 * 0.177828 = 89.937
lim2, lim3 = dr_region_limits(0.1)
check("Eq. 7: end of Region II at N = 0.1", lim2, 53.6, tol=1e-9)
check("Eq. 9: start of Region III at N = 0.1", lim3, 75.0 + 84.0 * 0.1 ** 0.75, tol=1e-9)

# Slip velocity, by hand with chart values read at a table node.  Region I (Eq. 4) at N_l = 0.1126:
#   F1 = 2.011, F2 = 0.9499, F3 = 3.253, F4 = 54.47;  N = 0.3, RN = 2, N_d = 40:
#   F3' = 3.253 - 54.47/40 = 1.89125;  S = 2.011 + 0.9499*0.3 + 1.89125*(2/1.3)^2 = 6.7724
n_l1 = DR_F3[0][16]
check_true("test node: N_l = 0.1126", abs(n_l1 - 0.1126) < 1e-9)
check("Region I slip (Eq. 4)", dr_slip_region1(0.3, 2.0, 40.0, n_l1), 2.011 + 0.9499 * 0.3 + (3.253 - 54.47 / 40.0) * (2.0 / 1.3) ** 2, tol=2e-3)
# Region II (Eq. 6) at N_l = 0.1163:  F5 = 0.05695, F6 = 2.166, F7 = 0.04447;  N = 0.3, RN = 20, N_d = 40:
#   F6' = 0.029*40 + 2.166 = 3.326;  S = (1.05695)(20^0.982 + 3.326)/(1 + 0.04447*0.3)^2 = 1.05695 * (18.9488 + 3.326)/1.02692 = 22.927
n_l2 = DR_F5[0][16]
check_true("test node: N_l = 0.1163", abs(n_l2 - 0.1163) < 1e-9)
check("Region II slip (Eq. 6)", dr_slip_region2(0.3, 20.0, 40.0, n_l2), 1.05695 * (20.0 ** 0.982 + 0.029 * 40.0 + 2.166) / (1.0 + 0.04447 * 0.3) ** 2, tol=2e-3)

# Holdup from slip: the slip definition v_sg/(1-H) - v_sl/H = v_s holds, and S = 0 means no slip
for v_sl_, v_sg_, s_ in ((0.5, 2.0, 3.0), (3.0, 0.2, 1.5), (0.02, 40.0, 25.0), (1.0, 1.0, 0.1)):
    f_v_ = 1.938 * (50.0 / 30.0) ** 0.25
    h_ = dr_holdup(v_sl_, v_sg_, s_, f_v_)
    check(f"holdup solves the slip definition (v_sl {v_sl_}, v_sg {v_sg_}, S {s_})", v_sg_ / (1 - h_) - v_sl_ / h_, s_ / f_v_, tol=1e-9)
check("S = 0: no slip, H = v_sl / (v_sl + v_sg)", dr_holdup(0.7, 2.1, 0.0, 2.2), 0.25, tol=1e-12)
check("no gas: H = 1", dr_holdup(0.7, 0.0, 3.0, 2.2), 1.0, tol=1e-12)
check("a negative slip (impossible upward) is taken as zero", dr_holdup(0.7, 2.1, -2.0, 2.2), 0.25, tol=1e-12)

# Friction factor of Fig. 8: Fanning = Darcy / 4, and Eq. 15 above e/D = 0.05
check("Fig. 8: laminar Fanning factor 16 / Re", _dr_fanning(1000.0, 0.001), 16.0 / 1000.0, tol=1e-12)
check("Fig. 8: turbulent = Colebrook / 4", _dr_fanning(1.0e5, 0.001), friction_factor(1.0e5, 0.001) / 4.0, tol=1e-12)
e15 = 0.2
check("Eq. 15 for e/D = 0.2 (hand: 1/(4 log10(0.054))^2 + 0.067*0.2^1.73)", _dr_fanning(1.0e6, e15),
      1.0 / (4.0 * math.log10(0.27 * e15)) ** 2 + 0.067 * e15 ** 1.73, tol=1e-12)
check("Eq. 15 joins the Moody diagram at e/D = 0.05 (within 5 %)", _dr_fanning(1.0e6, 0.0501), _dr_fanning(1.0e6, 0.0499), tol=0.05)

# Film roughness in mist flow (Eq. 14, Fig. 10): We = 34 for a thin liquid, so e/D = 34 sigma / (rho_g v^2 D) (>= 0.001)
sig3 = 30.0 * GRAY_SIGMA_UNIT
e_thin, we_thin = dr_mist_film_roughness(60.0, 1.0, 50.0, 0.5, 30.0, 0.25, 0.0002)
check("mist film roughness, thin liquid: We = 34", we_thin, 34.0, tol=1e-12)
check("mist film roughness, thin liquid: e/D = We sigma / (rho_g v^2 D)", e_thin, 34.0 * sig3 / (1.0 * 60.0 ** 2 * 0.25), tol=1e-9)
e_visc, we_visc = dr_mist_film_roughness(100.0, 1.0, 50.0, 1.0, 30.0, 0.25, 0.0002)
x_w = 4.52e-7 * (100.0 * 1.0 / sig3) ** 2 * 1.0 / 50.0
check("mist film roughness, viscous liquid: We = 174.8 X^0.302 (hand X = 0.0207)", we_visc, 174.8 * x_w ** 0.302, tol=1e-9)
check_true("mist film roughness: never below 0.001 or the pipe's own, never above 0.5",
           dr_mist_film_roughness(400.0, 1.0, 50.0, 0.5, 30.0, 0.25, 0.0002)[0] == 0.001
           and dr_mist_film_roughness(400.0, 1.0, 50.0, 0.5, 30.0, 0.25, 0.004)[0] == 0.004
           and dr_mist_film_roughness(1.0, 1.0, 50.0, 0.5, 30.0, 0.25, 0.0002)[0] == 0.5)

# Friction of Regions I-II (Eqs. 10, 11), worked by hand: 3.0-in pipe, v_sl = 3 ft/s, v_sg = 0.3 ft/s (bubble flow),
# rho_L = 50, rho_g = 2 lb/ft3, 2 cP, 30 dyne/cm, roughness 0.0006 in
c_d = dict(v_sl=3.0, v_sg=0.3, rho_l=50.0, rho_g=2.0, mu_l=2.0, mu_g=0.012, sigma=30.0)
d_d = 0.25
r_d = duns_ros_gradient(1000.0, 90.0, 3.0, 0.0006, c_d)
check_equal("bubble flow: Region I", r_d["regime"], "bubble")
nm_d = dr_numbers(3.0, 0.3, 50.0, 30.0, 2.0, d_d)
re_d = 1488.16 * 50.0 * 3.0 * d_d / 2.0                                       # liquid Reynolds number = 55 806
f1_d = friction_factor(re_d, 0.0002) / 4.0
f2_d = _dr_table(f1_d * (0.3 / 3.0) * nm_d["n_d"] ** (2.0 / 3.0), DR_FRICTION_F2)
f3_d = 1.0 + f1_d * math.sqrt((0.3 / 3.0) / 50.0)
fw_d = f1_d * f2_d / f3_d
g_fr_d = 2.0 * fw_d * nm_d["n"] * (nm_d["n"] + nm_d["rn"]) / nm_d["n_d"]
check("bubble flow: liquid Reynolds number", r_d["re"], re_d, tol=1e-9)
check("bubble flow: friction factor f_w = f1 f2 / f3 (Eq. 11)", r_d["f_tp"], fw_d, tol=1e-9)
check("bubble flow: friction gradient from Eq. 10", r_d["friction"], g_fr_d * 50.0 / 144.0, tol=1e-9)
# the same friction in ordinary units: dp/dL = 4 f_w * rho_L v_sl (v_sl + v_sg) / (2 g_c D)  (Eq. 9 text, Fanning)
check("bubble flow: same friction written with velocities", r_d["friction"], 4.0 * fw_d * 50.0 * 3.0 * 3.3 / (2.0 * 32.174 * d_d) / 144.0, tol=5e-4)   # the 1.938 and 120.872 constants give g = 32.17 +- 0.02 %
s_d = dr_slip_region1(nm_d["n"], nm_d["rn"], nm_d["n_d"], nm_d["n_l"])
h_d = dr_holdup(3.0, 0.3, s_d, nm_d["f_v"])
check("bubble flow: holdup from the slip", r_d["hl"], h_d, tol=1e-9)
check("bubble flow: static gradient (Eq. 1)", r_d["hydrostatic"], (h_d * 50.0 + (1.0 - h_d) * 2.0) / 144.0, tol=1e-9)
check_equal("bubble flow: no acceleration term", r_d["e_k"], 0.0)
check_true("bubble flow: holdup is high (gas is only 9 % of the volume)", 0.85 < r_d["hl"] < 1.0)
check("inclined 30 degrees: gravity part is sin(30) of the vertical one",
      duns_ros_gradient(1000.0, 30.0, 3.0, 0.0006, c_d)["hydrostatic"], 0.5 * r_d["hydrostatic"], tol=1e-9)
check("inclination does not change the friction", duns_ros_gradient(1000.0, 30.0, 3.0, 0.0006, c_d)["friction"], r_d["friction"], tol=1e-12)
check_equal("horizontal: no gravity part", duns_ros_gradient(1000.0, 0.0, 3.0, 0.0006, c_d)["hydrostatic"], 0.0)
check_true("downhill: gravity part is negative", duns_ros_gradient(1000.0, -30.0, 3.0, 0.0006, c_d)["hydrostatic"] < 0.0)

# Mist flow (Region III), worked by hand: 3.0 in, v_sl = 0.05, v_sg = 100 ft/s, rho_g = 1 lb/ft3, 1 cP, 500 psia
c_dm = dict(v_sl=0.05, v_sg=100.0, rho_l=50.0, rho_g=1.0, mu_l=1.0, mu_g=0.012, sigma=30.0)
r_dm = duns_ros_gradient(500.0, 90.0, 3.0, 0.0006, c_dm)
check_equal("mist flow: Region III", r_dm["regime"], "mist")
e_dm, _ = dr_mist_film_roughness(100.0, 1.0, 50.0, 1.0, 30.0, 0.25, 0.0002)
re_dm = 1488.16 * 1.0 * 0.25 * 100.0 / 0.012
f1_dm = friction_factor(re_dm, e_dm) / 4.0
nm_dm = dr_numbers(0.05, 100.0, 50.0, 30.0, 1.0, 0.25)
check("mist flow: gas Reynolds number", r_dm["re"], re_dm, tol=1e-9)
check("mist flow: friction gradient from Eq. 12, N_rho RN^2 / N_d", r_dm["friction"],
      2.0 * f1_dm * (1.0 / 50.0) * nm_dm["rn"] ** 2 / nm_dm["n_d"] * 50.0 / 144.0, tol=1e-9)
check("mist flow: the same friction in ordinary units (f rho_g v^2 / (2 g_c D))", r_dm["friction"],
      4.0 * f1_dm * 1.0 * 100.0 ** 2 / (2.0 * 32.174 * 0.25) / 144.0, tol=5e-4)
check("mist flow: holdup without slip (Eq. 8)", r_dm["hl"], 0.05 / 100.05, tol=1e-9)
mass_dm = 50.0 * 0.05 + 1.0 * 100.0
check("mist flow: acceleration term of Eq. 17", r_dm["e_k"], mass_dm * 100.0 / (32.174 * 500.0 * 144.0), tol=1e-9)
check("mist flow: gradient = (static + friction) / (1 - acceleration term)", r_dm["dpdl"] * (1.0 - r_dm["e_k"]),
      r_dm["hydrostatic"] + r_dm["friction"], tol=1e-12)
check_true("mist flow: the acceleration term is bigger at a lower pressure",
           duns_ros_gradient(200.0, 90.0, 3.0, 0.0006, c_dm)["e_k"] > r_dm["e_k"])

# Single phase: gas only and liquid only
o_g = duns_ros_gradient(500.0, 90.0, 3.0, 0.0006, dict(c_dm, v_sl=0.0))
check_equal("gas only: pattern", o_g["regime"], "gas")
check("gas only: weight of the gas", o_g["hydrostatic"], 1.0 / 144.0, tol=1e-9)
o_l = duns_ros_gradient(1000.0, 90.0, 3.0, 0.0006, dict(c_d, v_sg=0.0, rho_l=62.4))
check("liquid only: the weight of the liquid", o_l["hydrostatic"], 62.4 / 144.0, tol=1e-9)
check("liquid only: holdup 1", o_l["hl"], 1.0, tol=1e-12)
f_l = friction_factor(1488.16 * 62.4 * 3.0 * 0.25 / 2.0, 0.0002)
check("liquid only: Eq. 10 reduces to the single-phase Darcy friction", o_l["friction"], f_l * 62.4 * 3.0 ** 2 / (2.0 * 32.174 * 0.25) / 144.0, tol=5e-4)

# The paper's Fig. 3 (measured pressure gradient G of a 8.02 cm pipe, air and a 0.827 g/cm3, 4.2 cP oil at atmospheric pressure),
# read from the figure within about +-10 %:  mist flow at v_sl = 2 cm/s, v_sg = 10 000 cm/s: G = 0.34;
# v_sl = 320 cm/s: G starts at 1.1 (liquid + friction), has its minimum of 0.88 near v_sg = 500 cm/s
def fig3_g(v_sl_cm, v_sg_cm):
    c3 = dict(v_sl=v_sl_cm / 30.48, v_sg=v_sg_cm / 30.48, rho_l=RHO_FIG3, rho_g=0.075, mu_l=4.2, mu_g=0.018, sigma=27.5)
    r3 = duns_ros_gradient(14.7, 90.0, 8.02 / 2.54, 0.0, c3)
    return r3["dpdl"] * 144.0 / RHO_FIG3, r3
g1, r1_ = fig3_g(2.0, 1.0e4)
check("Fig. 3: mist flow, v_sl = 2 cm/s, v_sg = 10^4 cm/s (figure 0.34)", g1, 0.34, tol=0.2)
check_equal("Fig. 3: that point is in Region III", r1_["regime"], "mist")
check("Fig. 3: v_sl = 320 cm/s, v_sg = 0.5 cm/s: liquid column plus friction (figure 1.1)", fig3_g(320.0, 0.5)[0], 1.1, tol=0.1)
check("Fig. 3: v_sl = 320 cm/s, minimum near v_sg = 500 cm/s (figure 0.88)", min(fig3_g(320.0, v)[0] for v in (300.0, 500.0, 800.0)), 0.88, tol=0.2)
check_true("Fig. 3: v_sl = 2 cm/s, v_sg = 0.5 cm/s: nearly all liquid (holdup > 0.95)", fig3_g(2.0, 0.5)[1]["hl"] > 0.95)
check_true("Fig. 3: v_sl = 2 cm/s: the gradient falls steadily with gas rate up to the mist range",
           all(fig3_g(2.0, a)[0] > fig3_g(2.0, b)[0] for a, b in ((3.0, 30.0), (30.0, 300.0), (300.0, 1000.0))))
check_true("Fig. 3: v_sl = 2 cm/s: mist flow friction raises the gradient again after a minimum (1000 - 3000 cm/s)",
           fig3_g(2.0, 5000.0)[0] > fig3_g(2.0, 2000.0)[0] > fig3_g(2.0, 1500.0)[0] and fig3_g(2.0, 800.0)[0] > fig3_g(2.0, 1500.0)[0])
check("Fig. 3: v_sl = 2 cm/s: the minimum gradient (figure 0.0145 near 1100 cm/s)", min(fig3_g(2.0, v)[0] for v in (1100.0, 1300.0, 1500.0, 1700.0)), 0.0145, tol=0.35)
check_equal("Fig. 3: v_sl = 2 cm/s, v_sg = 1500 cm/s is mist flow (text: mist above 1500 cm/s)", fig3_g(2.0, 1500.0)[1]["regime"], "mist")
check_equal("Fig. 3: v_sl = 20 cm/s, v_sg = 500 cm/s is slug flow", fig3_g(20.0, 500.0)[1]["regime"], "slug")
check_equal("Fig. 3: v_sl = 20 cm/s, v_sg = 5 cm/s is bubble flow", fig3_g(20.0, 5.0)[1]["regime"], "bubble")

# Region boundaries: the flow region follows RN against L1 + L2 N, 50 + 36 N and 75 + 84 N^0.75 exactly
fr = dr_flow_region(0.5, 1.0, 50.0, 30.0, 1.0, 0.25)
check("regions: L1 + L2 N (Eq. 5) with the Fig. 6 values at this N_d", fr["rn_1"], _dr_table(fr["n_d"], DR_L1) + _dr_table(fr["n_d"], DR_L2) * fr["n"], tol=1e-12)
check("regions: end of Region II is 50 + 36 N", fr["rn_2"], 50.0 + 36.0 * fr["n"], tol=1e-12)
check("regions: start of Region III is 75 + 84 N^0.75", fr["rn_3"], 75.0 + 84.0 * fr["n"] ** 0.75, tol=1e-12)
def region_edge(name, v_sl=0.5, d_ft=0.25, rho_l=50.0, sigma=30.0, mu_l=1.0):
    """gas velocity (ft/s) at which RN reaches the given boundary, by halving the interval"""
    lo, hi = 1e-3, 2000.0
    for _ in range(100):
        mid = math.sqrt(lo * hi)
        f_ = dr_flow_region(v_sl, mid, rho_l, sigma, mu_l, d_ft)
        if f_["rn"] < f_[name]:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)
c_t = dict(v_sl=0.5, v_sg=1.0, rho_l=50.0, rho_g=3.0, mu_l=1.0, mu_g=0.012, sigma=30.0)
for name, label, pair in (("rn_2", "slug / transition", {"slug", "transition"}), ("rn_3", "transition / mist", {"transition", "mist"})):
    v_edge = region_edge(name)
    below = duns_ros_gradient(800.0, 90.0, 3.0, 0.0006, dict(c_t, v_sg=v_edge * (1 - 1e-7)))
    above = duns_ros_gradient(800.0, 90.0, 3.0, 0.0006, dict(c_t, v_sg=v_edge * (1 + 1e-7)))
    check_true(f"{label}: regions on the two sides ({below['regime']} / {above['regime']})", {below["regime"], above["regime"]} == pair)
    check(f"{label}: the gradient is continuous", below["dpdl"], above["dpdl"], tol=0.02)
    check(f"{label}: the holdup is continuous", below["hl"], above["hl"], tol=0.02)
# halfway (on RN) through the transition: the gradient before acceleration is the mean of the two boundary values (section VII),
# the mist end with its gas density corrected to keep rho_g v_sg fixed
v_mid = 0.5 * (region_edge("rn_2") + region_edge("rn_3"))
fm = dr_flow_region(0.5, v_mid, 50.0, 30.0, 1.0, 0.25)
w3 = (fm["rn"] - fm["rn_2"]) / (fm["rn_3"] - fm["rn_2"])
v2, v3 = fm["rn_2"] / fm["f_v"], fm["rn_3"] / fm["f_v"]
a2 = _dr_gradient_parts(2, 0.5, v2, 50.0, 3.0, 1.0, 0.012, 30.0, 0.25, 0.0002)
a3 = _dr_gradient_parts(3, 0.5, v3, 50.0, 3.0 * v_mid / v3, 1.0, 0.012, 30.0, 0.25, 0.0002)
r_mid = duns_ros_gradient(800.0, 90.0, 3.0, 0.0006, dict(c_t, v_sg=v_mid))
check_equal("transition: halfway point is in the transition", r_mid["regime"], "transition")
check_true("transition: weight of the mist end is between 0 and 1", 0.0 < w3 < 1.0)
check("transition: friction is the weighted mean of the two boundary values", r_mid["friction"],
      ((1 - w3) * a2[2] + w3 * a3[2]) * 50.0 / 144.0, tol=1e-9)
check("transition: static gradient is the weighted mean", r_mid["hydrostatic"], ((1 - w3) * a2[1] + w3 * a3[1]) * 50.0 / 144.0, tol=1e-9)
check_true("transition: acceleration term is applied", r_mid["e_k"] > 0.0)
check("mist end of the transition: gas mass flow rho_g v_sg is the real one", 3.0 * v_mid / v3 * v3, 3.0 * v_mid, tol=1e-12)

# Region I / II boundary: the two slip equations are separate fits, so the paper gives no exact match; for the
# usual tubing sizes (N_d 25 - 80) the gradient on either side of the boundary agrees to a few percent in most cases
rnd = _random.Random(7)
jumps = []
for _ in range(400):
    rho_x, mu_x, sig_x, d_x = rnd.uniform(45.0, 64.0), 10 ** rnd.uniform(-0.3, 1.5), rnd.uniform(20.0, 70.0), rnd.uniform(2.4, 4.5)
    v_sl_x = 10 ** rnd.uniform(-1.5, 0.6)
    nmx = dr_numbers(v_sl_x, 1.0, rho_x, sig_x, mu_x, d_x / 12.0)
    if not 25.0 < nmx["n_d"] < 80.0:
        continue
    rn1 = _dr_table(nmx["n_d"], DR_L1) + _dr_table(nmx["n_d"], DR_L2) * nmx["n"]
    cx = dict(v_sl=v_sl_x, rho_l=rho_x, rho_g=3.0, mu_l=mu_x, mu_g=0.015, sigma=sig_x)
    lo_ = duns_ros_gradient(1500.0, 90.0, d_x, 0.0006, dict(cx, v_sg=rn1 * 0.999 / nmx["f_v"]))["dpdl"]
    hi_ = duns_ros_gradient(1500.0, 90.0, d_x, 0.0006, dict(cx, v_sg=rn1 * 1.001 / nmx["f_v"]))["dpdl"]
    jumps.append(abs(hi_ - lo_) / lo_)
jumps.sort()
print(f"  (Region I/II boundary, {len(jumps)} tubing cases: gradient jump median {jumps[len(jumps) // 2]:.1%}, 90th percentile {jumps[int(0.9 * len(jumps))]:.1%})")
check_true("Region I / II: median jump below 10 %", jumps[len(jumps) // 2] < 0.10)

# Many random conditions: no failures, and the physical limits hold
bad = 0
n_tot = 0
reg_seen = set()
for _ in range(4000):
    cx = dict(v_sl=10 ** rnd.uniform(-3.5, 1.0), v_sg=10 ** rnd.uniform(-3.0, 2.6), rho_l=rnd.uniform(40.0, 66.0),
              rho_g=10 ** rnd.uniform(-0.5, 1.8), mu_l=10 ** rnd.uniform(-0.5, 3.0), mu_g=rnd.uniform(0.01, 0.03),
              sigma=rnd.uniform(2.0, 75.0))
    p_x, d_x, ang_x = 10 ** rnd.uniform(1.3, 4.0), rnd.uniform(1.0, 8.0), rnd.choice([90.0, 60.0, 30.0, 0.0, -30.0])
    r_x = duns_ros_gradient(p_x, ang_x, d_x, 0.0006, cx)
    n_tot += 1
    reg_seen.add(r_x["regime"])
    ok = all(math.isfinite(r_x[k]) for k in ("dpdl", "hl", "hydrostatic", "friction", "f_tp", "re", "e_k"))
    ok = ok and 0.0 <= r_x["hl"] <= 1.0 and r_x["friction"] >= 0.0 and 0.0 <= r_x["e_k"] <= 0.95
    ok = ok and abs(r_x["dpdl"] * (1.0 - r_x["e_k"]) - (r_x["hydrostatic"] + r_x["friction"])) < 1e-9 * max(1.0, abs(r_x["dpdl"]))
    if ang_x == 0.0:
        ok = ok and r_x["hydrostatic"] == 0.0
    bad += 0 if ok else 1
check_true(f"{n_tot} random conditions: finite, holdup in [0, 1], gradient = (gravity + friction)/(1 - e_k), no failures", bad == 0)
check_true("the random conditions covered bubble, slug, transition and mist flow", {"bubble", "slug", "transition", "mist"} <= reg_seen)

# Whole-well checks through the traverse
res_d = pressure_traverse(wl, oil, 2000.0, 200.0, "duns_ros")
check_true("traverse: Pwf above the wellhead pressure, split into gravity and friction", res_d["pwf"] > 200.0 and res_d["dp_hydrostatic"] > res_d["dp_friction"] > 0)
others = [pressure_traverse(wl, oil, 2000.0, 200.0, k)["pwf"] for k in ("beggs_brill", "hagedorn_brown", "orkiszewski", "ansari")]
check_true(f"traverse: Pwf {res_d['pwf']:.0f} psia is within 25 % of the other four correlations ({min(others):.0f} - {max(others):.0f})",
           0.75 * min(others) < res_d["pwf"] < 1.25 * max(others))
check_true("traverse: gravity multiplier 1.1 raises Pwf", pressure_traverse(wl, oil, 2000.0, 200.0, "duns_ros", gravity_mult=1.1)["pwf"] > res_d["pwf"])
gl_d = _copy.deepcopy(oil)
gl_d.injection_gas_rate, gl_d.injection_md = 1500.0, 6000.0
check_true("traverse: gas lift lowers Pwf", pressure_traverse(wl, gl_d, 2000.0, 200.0, "duns_ros")["pwf"] < res_d["pwf"])
check_true("traverse: deviated well has less gravity pressure than the vertical one",
           pressure_traverse(wd, oil, 2000.0, 200.0, "duns_ros")["dp_hydrostatic"] < res_d["dp_hydrostatic"])
pw_d = vlp_curve(wl, oil, rates_o, 200.0, "duns_ros")
check_true("VLP curve converges at every rate", len(pw_d) == 10 and all(p > 200.0 for p in pw_d))
check_true("VLP is J-shaped: low rate needs more Pwf than mid rate, high rate more again",
           pw_d[0] > min(pw_d) and pw_d[-1] > min(pw_d) and min(pw_d) < pw_d[3])
n_conv = 0
for tub_ in (1.38, 1.995, 2.441, 2.992):
    w_ = Well(*vertical_survey(8000), simple_tubing(tub_, 8000), 200.0)
    for wc_ in (0.0, 0.5):
        for gor_ in (300.0, 2000.0):
            f_ = OilWaterFluid(API, GG, gor_, water_cut=wc_)
            n_conv += len(vlp_curve(w_, f_, [50.0 * 2.0 ** k for k in range(8)], 150.0, "duns_ros"))
check_true("converges for 4 tubing sizes, 2 water cuts, 2 GORs at 8 rates", n_conv == 4 * 2 * 2 * 8)
gas_d = pressure_traverse(wl, GasFluid(0.65, cgr=30.0, wgr=5.0), 5000.0, 1000.0, "duns_ros")
check_true("wet gas well: Pwf above the wellhead pressure and the mist/gas regime is used", gas_d["pwf"] > 1000.0)
check_true("duns_ros is no longer 'not yet coded'", "duns_ros" in GRADIENT_FUNCS and "duns_ros" not in _NOT_YET)
check_raises("no flow", ValueError, duns_ros_gradient, 1000.0, 90.0, 3.0, 0.0006, dict(c_d, v_sl=0.0, v_sg=0.0))
check_raises("zero pressure", ValueError, duns_ros_gradient, 0.0, 90.0, 3.0, 0.0006, c_d)

# =====================================================================
print("\n== Mukherjee & Brill (1983 holdup, SPE 10923; 1985 flow patterns and friction) ==")
from vlp import (mb_numbers, mb_flow_pattern, mb_holdup, mb_stratified_angle, mb_stratified_friction,
                 mukherjee_brill_gradient, MB_COEFFICIENTS, MB_FRICTION_RATIO)

# Table 1 of SPE 10923, as printed
check_equal("Table 1: uphill coefficients", MB_COEFFICIENTS["uphill"],
            (-0.380113, 0.129875, -0.119788, 2.343227, 0.475686, 0.288657))
check_equal("Table 1: downhill stratified coefficients", MB_COEFFICIENTS["downhill_stratified"],
            (-1.330282, 4.808139, 4.171584, 56.262268, 0.079951, 0.504887))
check_equal("Table 1: downhill other coefficients", MB_COEFFICIENTS["downhill_other"],
            (-0.516644, 0.789805, 0.551627, 15.519214, 0.371771, 0.393952))

# Brill & Mukherjee, Multiphase Flow in Wells (1999), Examples 3.2 / 4.8: 6-in. vertical pipe, v_sg = 3.86, v_sL = 3.97 ft/s,
# rho_g = 5.88, rho_L = 47.61 lb/ft3, 0.016 and 0.97 cP, sigma = 8.41 dyne/cm.  Published: N_Lv = 11.87, N_gv = 11.54,
# N_L = 0.0118, N_gv(SM) = 350.8, N_Lv(BS) = 18.40, so the flow is slug flow (N_Lv < N_Lv(BS), N_gv < N_gv(SM)).
c_bk = dict(v_sl=3.97, v_sg=3.86, rho_l=47.61, rho_g=5.88, mu_l=0.97, mu_g=0.016, sigma=8.41)
nm_bk = mb_numbers(3.97, 3.86, 47.61, 8.41, 0.97)
check("book example: N_Lv", nm_bk["n_lv"], 11.87, tol=0.002)
check("book example: N_gv", nm_bk["n_gv"], 11.54, tol=0.002)
check("book example: N_L", nm_bk["n_l"], 0.0118, tol=0.005)
fp_bk = mb_flow_pattern(nm_bk["n_lv"], nm_bk["n_gv"], nm_bk["n_l"], 90.0)
check("book example: N_gv(SM)", fp_bk["n_gv_sm"], 350.8, tol=0.002)
check("book example: N_Lv(BS)", fp_bk["n_lv_bs"], 18.40, tol=0.002)
check_equal("book example: slug flow", fp_bk["regime"], "slug")
# holdup by hand, Eq. 1:  c1 + c2 + c3 + c4 N_L^2 = -0.380113 + 0.129875 - 0.119788 + 2.343227*0.011759^2 = -0.369702
#   N_gv^c5 = 11.539^0.475686 = 3.2022;  N_Lv^c6 = 11.868^0.288657 = 2.0426;  H_L = exp(-0.369702 * 3.2022/2.0426) = 0.5600
check("book example: holdup (hand 0.560)", mb_holdup(nm_bk["n_lv"], nm_bk["n_gv"], nm_bk["n_l"], 90.0, "slug"), 0.5600, tol=0.002)
r_bk = mukherjee_brill_gradient(1000.0, 90.0, 6.0, 0.0006 * 6.0, c_bk)
check("book example: gradient function uses that holdup", r_bk["hl"], mb_holdup(nm_bk["n_lv"], nm_bk["n_gv"], nm_bk["n_l"], 90.0, "slug"), tol=1e-12)
rho_s_bk = r_bk["hl"] * 47.61 + (1 - r_bk["hl"]) * 5.88
check("book example: gravity gradient is the slip density (psi/ft)", r_bk["hydrostatic"], rho_s_bk / 144.0, tol=1e-9)
# slug friction by hand: no-slip lambda = 3.97/7.83 = 0.50703; rho_ns = 0.50703*47.61 + 0.49297*5.88 = 27.038; mu_ns = 0.50703*0.97 + 0.49297*0.016 = 0.49968
#   Re = 1488.16 * 27.038 * 7.83 * 0.5 / 0.49968 = 315 245 (ratio to code below);  friction = f * rho_s * v_m^2 / (2 g_c d)
lam_bk = 3.97 / 7.83
rho_ns_bk = lam_bk * 47.61 + (1 - lam_bk) * 5.88
mu_ns_bk = lam_bk * 0.97 + (1 - lam_bk) * 0.016
re_bk = 1488.16 * rho_ns_bk * 7.83 * 0.5 / mu_ns_bk
check("book example: no-slip Reynolds number", r_bk["re"], re_bk, tol=1e-9)
check("book example: slug friction = f_ns rho_s v_m^2 / (2 g_c d)", r_bk["friction"],
      friction_factor(re_bk, 0.0006) * rho_s_bk * 7.83 ** 2 / (2.0 * 32.174 * 0.5) / 144.0, tol=1e-9)

# Flow-pattern boundaries, by hand.  N_L = 0.01, N_Lv = 1 (log = 0), N_gv = 1 (log = 0):
#   N_gv(SM) = 10^(1.401 - 2.694*0.01 + 0.521*1) = 10^1.89506 = 78.5
#   uphill, 90 deg:  N_Lv(BS) = 10^(0 + 0.940 + 0.074 - 0.855 + 3.695*0.01) = 10^0.19595 = 1.5703
#   downhill, -60 deg (sin = -0.866025):  N_gv(BS) = 10^(0.431 - 0.03003 + 1.132*(-0.866025)) = 10^-0.5794 = 0.2634
#                                         N_Lv(ST) = 10^(0.321 - 0.017 + 3.69539 - 0.02972 - 3.925*0.75) = 10^1.02592 = 10.61
fp_u = mb_flow_pattern(1.0, 1.0, 0.01, 90.0)
check("boundary N_gv(SM)", fp_u["n_gv_sm"], 10 ** 1.89506, tol=1e-4)
check("boundary uphill N_Lv(BS) at 90 deg", fp_u["n_lv_bs"], 10 ** 0.19595, tol=1e-4)
fp_d = mb_flow_pattern(1.0, 1.0, 0.01, -60.0)
check("boundary downhill N_gv(BS) at -60 deg", fp_d["n_gv_bs"], 10 ** -0.5794, tol=2e-3)
check("boundary downhill N_Lv(ST) at -60 deg", fp_d["n_lv_st"], 10 ** 1.02592, tol=2e-3)
check_equal("uphill: N_Lv below N_Lv(BS) is slug flow", mb_flow_pattern(1.0, 1.0, 0.01, 90.0)["regime"], "slug")
check_equal("uphill: N_Lv above N_Lv(BS) is bubble flow", mb_flow_pattern(1.6, 1.0, 0.01, 90.0)["regime"], "bubble")
check_equal("uphill: N_gv above N_gv(SM) is annular-mist flow", mb_flow_pattern(1.0, 80.0, 0.01, 90.0)["regime"], "annular")
# Horizontal flow goes down the "downhill and horizontal" branch of Fig. 16 of the flow-pattern paper (it is not uphill) and can be
# stratified.  By hand at angle 0, N_L = 0.01:  N_gv(BS) = 10^(0.431 - 0.03003) = 10^0.40097 = 2.518 (a vertical line, Eq. 3)
#   N_Lv(ST) at N_gv = 0.5: 10^(0.321 - 0.0085 - 0.02972 - 0.033*0.09062) = 10^0.27979 = 1.904
#   N_Lv(ST) at N_gv = 4:   10^(0.321 - 0.068 - 0.02972 - 0.033*0.36248) = 10^0.21132 = 1.627
fp_h = mb_flow_pattern(0.05, 0.5, 0.01, 0.0)
check("horizontal: N_gv(BS) = 10^0.40097 (a function of viscosity only)", fp_h["n_gv_bs"], 10 ** 0.40097, tol=1e-4)
check("horizontal: N_Lv(ST) at N_gv = 0.5", fp_h["n_lv_st"], 10 ** 0.27979, tol=1e-4)
check("horizontal: N_Lv(ST) at N_gv = 4", mb_flow_pattern(5.0, 4.0, 0.01, 0.0)["n_lv_st"], 10 ** 0.21132, tol=1e-4)
check_true("horizontal: the uphill boundary N_Lv(BS) does not apply", fp_h["n_lv_bs"] is None)
check_equal("horizontal: N_Lv below N_Lv(ST) is stratified", fp_h["regime"], "stratified")
check_equal("horizontal: N_Lv above N_Lv(ST), N_gv below N_gv(BS): bubble", mb_flow_pattern(5.0, 0.5, 0.01, 0.0)["regime"], "bubble")
check_equal("horizontal: N_Lv above N_Lv(ST), N_gv above N_gv(BS): slug", mb_flow_pattern(5.0, 4.0, 0.01, 0.0)["regime"], "slug")
check_equal("horizontal: N_gv above N_gv(SM) is annular-mist", mb_flow_pattern(0.05, 80.0, 0.01, 0.0)["regime"], "annular")
check_equal("a hair above horizontal is uphill: slug", mb_flow_pattern(0.05, 0.5, 0.01, 0.1)["regime"], "slug")
check_equal("downhill -60 deg: N_Lv below N_Lv(ST), N_gv above N_gv(BS): stratified", fp_d["regime"], "stratified")
check_equal("downhill -60 deg: N_gv below N_gv(BS): bubble", mb_flow_pattern(1.0, 0.2, 0.01, -60.0)["regime"], "bubble")
check_equal("downhill -60 deg: N_Lv above N_Lv(ST): slug", mb_flow_pattern(12.0, 10.0, 0.01, -60.0)["regime"], "slug")
check_equal("downhill -10 deg: N_Lv below N_Lv(ST): stratified", mb_flow_pattern(0.2, 0.3, 0.01, -10.0)["regime"], "stratified")
check_equal("downhill -10 deg: N_Lv above N_Lv(ST), N_gv below N_gv(BS): bubble", mb_flow_pattern(30.0, 0.1, 0.01, -10.0)["regime"], "bubble")

# Holdup: Eq. 1 with the right coefficient set; bubble and slug use the same equation, so the holdup is continuous there
check("uphill holdup uses the uphill set", mb_holdup(2.0, 3.0, 0.01, 30.0, "slug"),
      math.exp((-0.380113 + 0.129875 * 0.5 - 0.119788 * 0.25 + 2.343227 * 1e-4) * 3.0 ** 0.475686 / 2.0 ** 0.288657), tol=1e-12)
check("downhill stratified holdup", mb_holdup(2.0, 3.0, 0.01, -30.0, "stratified"),
      math.exp((-1.330282 - 4.808139 * 0.5 + 4.171584 * 0.25 + 56.262268 * 1e-4) * 3.0 ** 0.079951 / 2.0 ** 0.504887), tol=1e-12)
check("downhill other holdup", mb_holdup(2.0, 3.0, 0.01, -30.0, "slug"),
      math.exp((-0.516644 - 0.789805 * 0.5 + 0.551627 * 0.25 + 15.519214 * 1e-4) * 3.0 ** 0.371771 / 2.0 ** 0.393952), tol=1e-12)
check("holdup does not depend on the pattern for uphill flow", mb_holdup(2.0, 3.0, 0.01, 60.0, "bubble"),
      mb_holdup(2.0, 3.0, 0.01, 60.0, "annular"), tol=1e-12)
check_true("holdup stays between 0 and 1 even for a very viscous liquid", 0.0 <= mb_holdup(0.5, 0.5, 0.6, -20.0, "stratified") <= 1.0)
check_true("uphill: holdup rises with the liquid velocity and falls with the gas velocity",
           mb_holdup(3.0, 5.0, 0.01, 90.0, "slug") > mb_holdup(1.0, 5.0, 0.01, 90.0, "slug")
           and mb_holdup(2.0, 8.0, 0.01, 90.0, "slug") < mb_holdup(2.0, 2.0, 0.01, 90.0, "slug"))
check_true("more viscous liquid: more holdup (positive c4)", mb_holdup(2.0, 3.0, 0.1, 90.0, "slug") > mb_holdup(2.0, 3.0, 0.01, 90.0, "slug"))
check_true("downhill: far less holdup than uphill at the same velocities", mb_holdup(0.5, 2.0, 0.01, -30.0, "stratified") < 0.5 * mb_holdup(0.5, 2.0, 0.01, 30.0, "slug"))

# Stratified geometry: (delta - sin delta) / (2 pi) = H_L.  Half full: delta = pi, both hydraulic diameters pi D / (pi + 2).
check("stratified angle for a half-full pipe is pi", mb_stratified_angle(0.5), math.pi, tol=1e-9)
for h_ in (0.05, 0.3, 0.8):
    d_ = mb_stratified_angle(h_)
    check(f"stratified angle satisfies (delta - sin delta)/(2 pi) = {h_}", (d_ - math.sin(d_)) / (2.0 * math.pi), h_, tol=1e-9)
# Eq. 15 with no interface shear: gas wall shear over the gas area.  Half-full pipe (delta = pi), v_sg = 1 ft/s, so the gas runs at
# v_g = v_sg / (1 - 0.5) = 2 ft/s.  D_Eg = D pi / (pi + 2) (Eq. 25).  P_g = pi D / 2 (Eq. 23) and A_g = pi D^2 / 8, so P_g / A_g = 4 / D,
# and tau_wg = f rho v^2 / 8 g_c gives  friction = tau * 4 / D = f rho_g v_g^2 / (2 g_c D)  with the Moody factor at Re = rho v D_Eg / mu.
d_h = math.pi * 0.25 / (math.pi + 2.0)
f_sym, ex_sym = mb_stratified_friction(0.5, 1.0, 3.0, 0.015, 0.25, 0.0002)
re_sym = 1488.16 * 3.0 * 2.0 * d_h / 0.015
check("stratified, half-full pipe: Reynolds number of the gas", ex_sym["re"], re_sym, tol=1e-9)
check("stratified, half-full pipe: friction = f rho_g v_g^2 / (2 g_c D)", f_sym,
      friction_factor(re_sym, 0.0002) * 3.0 * 2.0 ** 2 / (2.0 * 32.174 * 0.25), tol=1e-9)
check_true("stratified friction is finite and positive at extreme holdups",
           all(mb_stratified_friction(h_, 5.0, 1.0, 0.015, 0.25, 0.0002)[0] > 0.0 for h_ in (0.0, 1e-4, 0.5, 1.0)))

# Friction of annular-mist flow: f_R from the table by H_R = no-slip holdup / holdup, applied to the no-slip density
c_an = dict(v_sl=0.4, v_sg=80.0, rho_l=50.0, rho_g=3.0, mu_l=1.0, mu_g=0.015, sigma=30.0)
r_an = mukherjee_brill_gradient(800.0, 90.0, 3.0, 0.0006, c_an)
check_equal("annular-mist flow: pattern", r_an["regime"], "annular")
lam_an = 0.4 / 80.4
rho_ns_an = lam_an * 50.0 + (1 - lam_an) * 3.0
re_an = 1488.16 * rho_ns_an * 80.4 * 0.25 / (lam_an * 1.0 + (1 - lam_an) * 0.015)
h_r_an = lam_an / r_an["hl"]
xs_r, ys_r = MB_FRICTION_RATIO
i_r = max(i for i, x in enumerate(xs_r) if x <= h_r_an)
f_r_an = ys_r[i_r] + (ys_r[i_r + 1] - ys_r[i_r]) * (h_r_an - xs_r[i_r]) / (xs_r[i_r + 1] - xs_r[i_r])
check("annular-mist: friction = f_ns f_R rho_ns v_m^2 / (2 g_c d)", r_an["friction"],
      friction_factor(re_an, 0.0002) * f_r_an * rho_ns_an * 80.4 ** 2 / (2.0 * 32.174 * 0.25) / 144.0, tol=1e-9)
check("annular-mist: gravity from the slip density", r_an["hydrostatic"], (r_an["hl"] * 50.0 + (1 - r_an["hl"]) * 3.0) / 144.0, tol=1e-9)
check_true("friction-ratio table: 1 at both ends, largest (1.30) at H_R = 0.5", ys_r[0] == 1.0 and ys_r[-1] == 1.0 and max(ys_r) == 1.30 and xs_r[ys_r.index(1.30)] == 0.5)

# Acceleration, inclination, single phase
check("acceleration term E_k = rho_s v_m v_sg / (g_c p)", r_an["e_k"],
      (r_an["hl"] * 50.0 + (1 - r_an["hl"]) * 3.0) * 80.4 * 80.0 / (32.174 * 800.0 * 144.0), tol=1e-9)
check("gradient = (gravity + friction) / (1 - E_k)", r_an["dpdl"] * (1.0 - r_an["e_k"]), r_an["hydrostatic"] + r_an["friction"], tol=1e-12)
c_ms = dict(v_sl=0.5, v_sg=2.0, rho_l=50.0, rho_g=3.0, mu_l=1.0, mu_g=0.015, sigma=30.0)
for ang_ in (90.0, 45.0, 10.0, -10.0, -45.0, -90.0):
    r_ = mukherjee_brill_gradient(1000.0, ang_, 2.992, 0.0018, c_ms)
    rho_use = 3.0 if r_["regime"] == "stratified" else r_["hl"] * 50.0 + (1 - r_["hl"]) * 3.0      # stratified: only the gas weighs (Eq. 15)
    check(f"gravity gradient at {ang_:.0f} deg ({r_['regime']}) = rho sin(angle) / 144", r_["hydrostatic"],
          rho_use * math.sin(math.radians(ang_)) / 144.0, tol=1e-9)
check_equal("horizontal: no gravity part", mukherjee_brill_gradient(1000.0, 0.0, 2.992, 0.0018, c_ms)["hydrostatic"], 0.0)
c_st = dict(c_ms, v_sl=0.2, v_sg=0.5)
r_st = mukherjee_brill_gradient(1000.0, -10.0, 2.992, 0.0018, c_st)
check_equal("stratified downhill: pattern", r_st["regime"], "stratified")
check("stratified downhill: only the gas column weighs (Eq. 15): rho_g sin(angle) / 144", r_st["hydrostatic"], 3.0 * math.sin(math.radians(-10.0)) / 144.0, tol=1e-9)
check("stratified downhill: no acceleration term (the paper sets it to zero)", r_st["e_k"], 0.0, tol=1e-12)
check("stratified downhill: friction is the gas wall friction of Eq. 15", r_st["friction"],
      mb_stratified_friction(r_st["hl"], 0.5, 3.0, 0.015, 2.992 / 12.0, 0.0018 / 2.992)[0] / 144.0, tol=1e-9)
check("stratified downhill: gradient = gravity + friction (no acceleration)", r_st["dpdl"], r_st["hydrostatic"] + r_st["friction"], tol=1e-12)
c_hs = dict(c_ms, v_sl=0.05, v_sg=0.5)
r_hs = mukherjee_brill_gradient(1000.0, 0.0, 2.992, 0.0018, c_hs)
check_equal("horizontal, little liquid and gas: stratified", r_hs["regime"], "stratified")
check_true("horizontal stratified: friction only and no acceleration", r_hs["hydrostatic"] == 0.0 and r_hs["friction"] > 0.0 and r_hs["e_k"] == 0.0)
check_true("downhill flow: stratified pattern, small holdup, negative gravity part",
           (lambda r_: r_["regime"] == "stratified" and r_["hl"] < 0.2 and r_["hydrostatic"] < 0.0)(mukherjee_brill_gradient(1000.0, -10.0, 2.992, 0.0018, dict(c_ms, v_sl=0.2, v_sg=0.5))))
o_g = mukherjee_brill_gradient(500.0, 90.0, 3.0, 0.0006, dict(c_an, v_sl=0.0))
check_equal("gas only: pattern", o_g["regime"], "gas")
check("gas only: weight of the gas", o_g["hydrostatic"], 3.0 / 144.0, tol=1e-9)
o_l = mukherjee_brill_gradient(1000.0, 90.0, 3.0, 0.0006, dict(c_an, v_sg=0.0, v_sl=3.0))
check_equal("liquid only: pattern", o_l["regime"], "liquid")
check("liquid only: weight of the liquid", o_l["hydrostatic"], 50.0 / 144.0, tol=1e-9)
check("liquid only: single-phase Darcy friction", o_l["friction"],
      friction_factor(1488.16 * 50.0 * 3.0 * 0.25 / 1.0, 0.0002) * 50.0 * 9.0 / (2.0 * 32.174 * 0.25) / 144.0, tol=1e-9)

# Cross-check with the open-source implementation that the 1985 equations were taken from, on its own example
# (SI: v_sG = 5, v_sL = 1 m/s, 0.1 m pipe, 1 and 1000 kg/m3, 1e-5 and 1e-3 Pa s, 0.072 N/m, vertical, roughness 0.0001 m).
# It prints slug flow, H_L = 0.3272534, dP/dL = 4403.03 Pa/m (3213.68 gravity + 1189.36 friction).
c_si = dict(v_sl=1.0 / 0.3048, v_sg=5.0 / 0.3048, rho_l=1000.0 / 16.01846, rho_g=1.0 / 16.01846, mu_l=1.0, mu_g=0.01, sigma=72.0)
r_si = mukherjee_brill_gradient(1.0e9, 90.0, 0.1 / 0.0254, 0.0001 / 0.0254, c_si)
pa_m = 6894.757 / 0.3048                                                    # psi/ft -> Pa/m
check_equal("open-source example: slug flow", r_si["regime"], "slug")
check("open-source example: holdup 0.3272534", r_si["hl"], 0.3272534, tol=1e-4)
check("open-source example: gravity gradient 3213.68 Pa/m", r_si["hydrostatic"] * pa_m, 3213.676, tol=2e-3)
check("open-source example: friction gradient 1189.36 Pa/m", r_si["friction"] * pa_m, 1189.355, tol=2e-3)

# Random conditions at every angle: no failures, limits hold
rnd2 = _random.Random(21)
bad = 0
seen = set()
for _ in range(6000):
    cx = dict(v_sl=10 ** rnd2.uniform(-3.5, 1.0), v_sg=10 ** rnd2.uniform(-3.0, 2.6), rho_l=rnd2.uniform(40.0, 66.0),
              rho_g=10 ** rnd2.uniform(-0.5, 1.8), mu_l=10 ** rnd2.uniform(-0.5, 3.0), mu_g=rnd2.uniform(0.01, 0.03),
              sigma=rnd2.uniform(2.0, 75.0))
    p_x, d_x = 10 ** rnd2.uniform(1.3, 4.0), rnd2.uniform(1.0, 8.0)
    ang_x = rnd2.choice([90.0, 75.0, 45.0, 20.0, 5.0, 0.0, -5.0, -20.0, -45.0, -75.0, -90.0])
    r_x = mukherjee_brill_gradient(p_x, ang_x, d_x, 0.0006, cx)
    seen.add(r_x["regime"])
    ok = all(math.isfinite(r_x[k]) for k in ("dpdl", "hl", "hydrostatic", "friction", "f_tp", "re", "e_k"))
    ok = ok and 0.0 <= r_x["hl"] <= 1.0 and r_x["friction"] >= 0.0 and 0.0 <= r_x["e_k"] <= 0.95
    ok = ok and abs(r_x["dpdl"] * (1.0 - r_x["e_k"]) - (r_x["hydrostatic"] + r_x["friction"])) < 1e-9 * max(1.0, abs(r_x["dpdl"]))
    if ang_x == 0.0:
        ok = ok and r_x["hydrostatic"] == 0.0
    if ang_x > 0.0:
        ok = ok and r_x["hydrostatic"] > 0.0
    if ang_x < 0.0:
        ok = ok and r_x["hydrostatic"] < 0.0
    bad += 0 if ok else 1
check_true("6000 random conditions at 11 angles: finite, holdup in [0, 1], gradient = (gravity + friction)/(1 - E_k), no failures", bad == 0)
check_true("the random conditions covered bubble, slug, annular and stratified flow", {"bubble", "slug", "annular", "stratified"} <= seen)

# Whole-well checks
res_m = pressure_traverse(wl, oil, 2000.0, 200.0, "mukherjee_brill")
check_true("traverse: Pwf above the wellhead pressure, split into gravity and friction", res_m["pwf"] > 200.0 and res_m["dp_hydrostatic"] > res_m["dp_friction"] > 0)
others = [pressure_traverse(wl, oil, 2000.0, 200.0, k)["pwf"] for k in ("beggs_brill", "hagedorn_brown", "orkiszewski", "ansari", "duns_ros")]
check_true(f"traverse: Pwf {res_m['pwf']:.0f} psia is within 25 % of the other correlations ({min(others):.0f} - {max(others):.0f})",
           0.75 * min(others) < res_m["pwf"] < 1.25 * max(others))
check_true("traverse: gravity multiplier 1.1 raises Pwf", pressure_traverse(wl, oil, 2000.0, 200.0, "mukherjee_brill", gravity_mult=1.1)["pwf"] > res_m["pwf"])
gl_m = _copy.deepcopy(oil)
gl_m.injection_gas_rate, gl_m.injection_md = 1500.0, 6000.0
check_true("traverse: gas lift lowers Pwf", pressure_traverse(wl, gl_m, 2000.0, 200.0, "mukherjee_brill")["pwf"] < res_m["pwf"])
check_true("traverse: deviated well has less gravity pressure than the vertical one",
           pressure_traverse(wd, oil, 2000.0, 200.0, "mukherjee_brill")["dp_hydrostatic"] < res_m["dp_hydrostatic"])
check_true("horizontal well: pressure drop is friction only (< 20 % of the vertical one)",
           pressure_traverse(wh, oil, 2000.0, 200.0, "mukherjee_brill")["pwf"] - 200.0 < 0.2 * (res_m["pwf"] - 200.0))
w_dn = Well([0.0, 3000.0, 6000.0], [0.0, 3000.0, 0.0], simple_tubing(2.992, 6000), 200.0)            # up, then back down (a flow line)
res_dn = pressure_traverse(w_dn, oil, 2000.0, 200.0, "mukherjee_brill")
check_true("a well that turns downhill still gives a pressure", res_dn["pwf"] > 200.0 and all(0.0 <= h <= 1.0 for h in res_dn["holdup"]))
pw_m = vlp_curve(wl, oil, rates_o, 200.0, "mukherjee_brill")
check_true("VLP curve converges at every rate", len(pw_m) == 10 and all(p > 200.0 for p in pw_m))
check_true("VLP is J-shaped: low rate needs more Pwf than the minimum, high rate more again", pw_m[0] > min(pw_m) and pw_m[-1] > min(pw_m))
n_conv = 0
for tub_ in (1.38, 1.995, 2.441, 2.992):
    w_ = Well(*vertical_survey(8000), simple_tubing(tub_, 8000), 200.0)
    for wc_ in (0.0, 0.5):
        for gor_ in (300.0, 2000.0):
            f_ = OilWaterFluid(API, GG, gor_, water_cut=wc_)
            n_conv += len(vlp_curve(w_, f_, [50.0 * 2.0 ** k for k in range(8)], 150.0, "mukherjee_brill"))
check_true("converges for 4 tubing sizes, 2 water cuts, 2 GORs at 8 rates", n_conv == 4 * 2 * 2 * 8)
gas_m = pressure_traverse(wl, GasFluid(0.65, cgr=30.0, wgr=5.0), 5000.0, 1000.0, "mukherjee_brill")
check_true("wet gas well: Pwf above the wellhead pressure", gas_m["pwf"] > 1000.0)
check_true("mukherjee_brill is listed", "mukherjee_brill" in GRADIENT_FUNCS)
check_raises("no flow", ValueError, mukherjee_brill_gradient, 1000.0, 90.0, 3.0, 0.0006, dict(c_ms, v_sl=0.0, v_sg=0.0))
check_raises("zero pressure", ValueError, mukherjee_brill_gradient, 0.0, 90.0, 3.0, 0.0006, c_ms)

# =====================================================================
print("\n== Fancher & Brown (1963, SPE 440-PA) ==")
from vlp import (fb_glr_band, fb_friction_factor, fancher_brown_gradient, FB_FRICTION_LINES, FB_N_MAX, FB_GLR_LIMITS)

# The three friction lines (Figs. 7, 8, 9 of the paper) are chart readings.  Each one is checked against the figure:
# Fig. 9 (GLR > 3000) crosses f = 0.01 at N = 10; Fig. 8 (1500 - 3000) crosses f = 0.0225 at N = 10 and 0.01 at N = 20;
# Fig. 7 (GLR < 1500) crosses f = 0.0357 at N = 10 and 0.01 at N = 31 (the printed figure, read to about 3 %).
check_equal("GLR 100 is the low band", fb_glr_band(100.0), "low")
check_equal("GLR 1499 is the low band", fb_glr_band(1499.0), "low")
check_equal("GLR 1500 is where the middle band starts", fb_glr_band(1500.0), "mid")
check_equal("GLR 3000 is still the middle band", fb_glr_band(3000.0), "mid")
check_equal("GLR 3001 is the high band", fb_glr_band(3001.0), "high")
check_equal("a dry gas (huge GLR) is the high band", fb_glr_band(1.0e9), "high")
check("Fig. 9 at N = 10: f = 0.0099 (line through 0.01)", fb_friction_factor(10.0, 5000.0), 0.0099, tol=0.03)
check("Fig. 8 at N = 10: f = 0.0224", fb_friction_factor(10.0, 2000.0), 0.0224, tol=0.03)
check("Fig. 8 at N = 20: f = 0.0103", fb_friction_factor(20.0, 2000.0), 0.0103, tol=0.03)
check("Fig. 7 at N = 10: f = 0.0360", fb_friction_factor(10.0, 500.0), 0.0360, tol=0.03)
check("Fig. 7 at N = 30: f = 0.0100", fb_friction_factor(30.0, 500.0), 0.0100, tol=0.04)
check("Fig. 7 at N = 4.7 (where its curve is steep): f = 0.111", fb_friction_factor(4.7, 500.0), 0.111, tol=0.01)
check_true("at the same N the factor falls as the GLR rises (the paper's finding, Fig. 6): N = 10, 15, 20",
           all(fb_friction_factor(n_, 500.0) > fb_friction_factor(n_, 2000.0) > fb_friction_factor(n_, 5000.0) for n_ in (10.0, 15.0, 20.0)))
check_true("the factor falls as N rises on every line (inside the drawn part: strictly; outside it is held)",
           all(fb_friction_factor(n_ * 1.05, g_) < fb_friction_factor(n_, g_) for g_ in (500.0, 2000.0, 5000.0) for n_ in (6.0, 10.0, 12.0))
           and all(fb_friction_factor(n_ * 1.05, g_) <= fb_friction_factor(n_, g_) for g_ in (500.0, 2000.0, 5000.0) for n_ in (0.5, 3.0, 22.0, 60.0, 400.0)))
check("a straight line on log-log paper: slope of the middle band is -1.122", math.log(fb_friction_factor(20.0, 2000.0) / fb_friction_factor(10.0, 2000.0)) / math.log(2.0), -1.12195, tol=1e-3)
check("above the end of the line the factor is held (high band, N = 23 and 500)", fb_friction_factor(500.0, 5000.0), fb_friction_factor(FB_N_MAX["high"], 5000.0), tol=1e-12)
check("below the start of the line the factor is held (low band, N = 3.4 and 0.2)", fb_friction_factor(0.2, 500.0), 0.259, tol=1e-12)
check_true("the factors stay above a smooth pipe's at the end of every line (about 0.003)", all(fb_friction_factor(FB_N_MAX[b_], g_) > 0.003 for b_, g_ in (("low", 500.0), ("mid", 2000.0), ("high", 5000.0))))
check_true("the line is continuous at every point of the tables", all(abs(fb_friction_factor(n_ * (1 + 1e-9), g_) / fb_friction_factor(n_ * (1 - 1e-9), g_) - 1.0) < 1e-6
           for g_, b_ in ((500.0, "low"), (2000.0, "mid"), (5000.0, "high")) for n_, _f in FB_FRICTION_LINES[b_][1:-1]))
check_raises("N = 0", ValueError, fb_friction_factor, 0.0, 500.0)

# By hand (Eq. 2), vertical, 2.992 in tubing, v_sl = 1 and v_sg = 4 ft/s, rho_L = 50 and rho_g = 5 lb/ft3:
#   d = 0.249333 ft, A = 0.0488259 ft2, v_m = 5 ft/s, lambda_L = 0.2, rho = 0.2*50 + 0.8*5 = 14.0 lb/ft3
#   mass flux G = 50*1 + 5*4 = 70 lb/s/ft2, q M = 70 * 0.0488259 * 86400 = 295 299 lb/day
#   N = 1.4737e-5 * 295 299 / 0.249333 = 17.4538
#   GLR 1000 (low line):  f = 10^(-0.26574 - 1.17775*1.241891) = 0.0186906 ;  friction = f (qM)^2 / (7.413e10 rho d^5) / 144 = 0.0113178 psi/ft
#   GLR 2000 (mid line):  f = 10^(-0.52769 - 1.12195*1.241891) = 0.0119942 ;  friction = 0.0072629
#   GLR 5000 (high line): f = 10^(-0.73798 - 1.26576*1.241891) = 0.0048987 ;  friction = 0.0029663
#   gravity = 14.0 / 144 = 0.0972222 psi/ft
c_fb = dict(v_sl=1.0, v_sg=4.0, rho_l=50.0, rho_g=5.0, mu_l=1.0, mu_g=0.015, sigma=30.0, frac_w=0.0, glr=1000.0)
r_fb = fancher_brown_gradient(1000.0, 90.0, 2.992, 0.0006, c_fb)
check("by hand: no-slip holdup = liquid fraction", r_fb["hl"], 0.2, tol=1e-12)
check_equal("by hand: the regime is called no-slip", r_fb["regime"], "no-slip")
check("by hand: Fanning factor of the low line", r_fb["f_tp"], 0.0186906, tol=1e-4)
check("by hand: gravity gradient = rho/144", r_fb["hydrostatic"], 0.0972222, tol=1e-6)
check("by hand: friction gradient (low line)", r_fb["friction"], 0.0113178, tol=2e-4)
check("by hand: total = gravity + friction, no acceleration term", r_fb["dpdl"], 0.0972222 + 0.0113178, tol=2e-4)
check("no acceleration term", r_fb["e_k"], 0.0, tol=0.0)
check("by hand: friction on the middle line", fancher_brown_gradient(1000.0, 90.0, 2.992, 0.0006, dict(c_fb, glr=2000.0))["friction"], 0.0072629, tol=2e-4)
check("by hand: friction on the high line", fancher_brown_gradient(1000.0, 90.0, 2.992, 0.0006, dict(c_fb, glr=5000.0))["friction"], 0.0029663, tol=2e-4)
# Eq. 2 is the Fanning form 2 f rho v^2 / (g_c d): the constant 7.413e10 is what that gives (7.408e10 exactly)
check("Eq. 2 friction = 2 f rho v^2 / (g_c d) (the constant 7.413e10 is 0.07 % from the exact one)", r_fb["friction"],
      2.0 * r_fb["f_tp"] * 14.0 * 5.0 ** 2 / (32.174 * (2.992 / 12.0)) / 144.0, tol=1.5e-3)
# Eq. 1 is Eq. 2 turned round: the factor back-calculated from the gradient is the chart factor
m_fb = 70.0 * (math.pi * (2.992 / 12.0) ** 2 / 4.0) * 86400.0
f_back = 7.413e10 * 14.0 * (2.992 / 12.0) ** 5 * 144.0 * (r_fb["dpdl"] - 14.0 / 144.0) / m_fb ** 2
check("Eq. 1 (back-calculated factor) returns the chart factor", f_back, r_fb["f_tp"], tol=1e-9)
check("the roughness and the pressure are not used", fancher_brown_gradient(3000.0, 90.0, 2.992, 0.01, c_fb)["dpdl"], r_fb["dpdl"], tol=1e-12)
check("the viscosity is not used (the paper found viscous shear negligible)",
      fancher_brown_gradient(1000.0, 90.0, 2.992, 0.0006, dict(c_fb, mu_l=300.0))["dpdl"], r_fb["dpdl"], tol=1e-12)
check("inclined 30 degrees: gravity part is halved, friction unchanged",
      fancher_brown_gradient(1000.0, 30.0, 2.992, 0.0006, c_fb)["dpdl"], 0.5 * 14.0 / 144.0 + r_fb["friction"], tol=1e-9)
check("horizontal: gravity part is zero", fancher_brown_gradient(1000.0, 0.0, 2.992, 0.0006, c_fb)["hydrostatic"], 0.0, tol=1e-12)
check_true("downhill: gravity part is negative, friction still positive",
           (lambda r_: r_["hydrostatic"] < 0.0 < r_["friction"])(fancher_brown_gradient(1000.0, -45.0, 2.992, 0.0006, c_fb)))
r_liq = fancher_brown_gradient(1000.0, 90.0, 2.992, 0.0006, dict(c_fb, v_sg=0.0))
check("liquid only: holdup 1", r_liq["hl"], 1.0, tol=1e-12)
check("liquid only: the gravity part is the liquid's", r_liq["hydrostatic"], 50.0 / 144.0, tol=1e-12)
r_gas = fancher_brown_gradient(1000.0, 90.0, 2.992, 0.0006, dict(c_fb, v_sl=0.0, glr=1.0e9))
check_true("gas only: holdup 0", r_gas["hl"] == 0.0)
check("gas only: the gravity part is the gas's", r_gas["hydrostatic"], 5.0 / 144.0, tol=1e-12)
check_raises("no flow", ValueError, fancher_brown_gradient, 1000.0, 90.0, 3.0, 0.0006, dict(c_fb, v_sl=0.0, v_sg=0.0))

# The producing gas-liquid ratio handed to the correlation by the fluid classes (scf per STB of liquid)
c_g0 = OilWaterFluid(35.0, 0.7, 500.0, water_cut=0.2).conditions(1000.0, 1500.0, 150.0, 2.992)
check("oil well: GLR = producing GOR x oil share = 500 x 0.8 = 400 scf/STB of liquid", c_g0["glr"], 400.0, tol=1e-12)
c_g1 = OilWaterFluid(35.0, 0.7, 500.0, water_cut=0.2, gor=800.0).conditions(1000.0, 1500.0, 150.0, 2.992)
check("oil well with a producing GOR of 800: GLR = 640", c_g1["glr"], 640.0, tol=1e-12)
c_g2 = OilWaterFluid(35.0, 0.7, 500.0, water_cut=0.2).conditions(1000.0, 1500.0, 150.0, 2.992, inj_scfd=600000.0)
check("gas lift: GLR = (400 000 + 600 000 scf/d injected) / 1000 STB/d = 1000", c_g2["glr"], 1000.0, tol=1e-12)
check("a wet gas of 30 STB/MMscf condensate and 5 STB/MMscf water: GLR = 1e6 / 35 scf/STB",
      GasFluid(0.65, cgr=30.0, wgr=5.0).conditions(5000.0, 1500.0, 150.0, 2.992)["glr"], 1.0e6 / 35.0, tol=1e-12)
check_true("a dry gas has a very large GLR", GasFluid(0.65).conditions(5000.0, 1500.0, 150.0, 2.992)["glr"] > 1.0e8)

# Whole-well checks
res_f = pressure_traverse(wl, oil, 2000.0, 200.0, "fancher_brown")
check_true("traverse: Pwf above the wellhead pressure; every step is no-slip", res_f["pwf"] > 200.0 and set(res_f["regime"]) == {"no-slip"})
check_true("traverse: gravity part is the big one", res_f["dp_hydrostatic"] > res_f["dp_friction"] > 0)
check("traverse: gravity + friction = the whole pressure drop (no acceleration term)", res_f["dp_hydrostatic"] + res_f["dp_friction"], res_f["pwf"] - 200.0, tol=1e-4)
# PROSPER calls it the "lowest possible VLP" because it ignores slip.  That is exact for the gravity part (the no-slip density is
# the lightest mixture): it is below that of every correlation here except Orkiszewski, whose slug-flow liquid distribution term
# can lower its density under the no-slip one (a known artefact of that method).  The whole pressure also depends on the friction,
# which each method takes from its own chart, so only the gravity part is held to the ordering.
others_f = {k: pressure_traverse(wl, oil, 2000.0, 200.0, k) for k in ("beggs_brill", "hagedorn_brown", "ansari", "duns_ros", "mukherjee_brill")}
check_true("traverse: gravity pressure " + f"{res_f['dp_hydrostatic']:.0f} psi is below that of every slip correlation ("
           + ", ".join(f"{k} {v['dp_hydrostatic']:.0f}" for k, v in others_f.items()) + ")",
           all(res_f["dp_hydrostatic"] < v["dp_hydrostatic"] for v in others_f.values()))
check_true("traverse: Pwf is the same order as Hagedorn and Brown (within 15 %)", abs(res_f["pwf"] / others_f["hagedorn_brown"]["pwf"] - 1.0) < 0.15)
check_true("traverse: gravity multiplier 1.1 raises Pwf", pressure_traverse(wl, oil, 2000.0, 200.0, "fancher_brown", gravity_mult=1.1)["pwf"] > res_f["pwf"])
check_true("traverse: friction multiplier 2 raises Pwf", pressure_traverse(wl, oil, 2000.0, 200.0, "fancher_brown", friction_mult=2.0)["pwf"] > res_f["pwf"])
check_true("traverse: gas lift lowers Pwf", pressure_traverse(wl, gl_m, 2000.0, 200.0, "fancher_brown")["pwf"] < res_f["pwf"])
check_true("traverse: deviated well has less gravity pressure than the vertical one",
           pressure_traverse(wd, oil, 2000.0, 200.0, "fancher_brown")["dp_hydrostatic"] < res_f["dp_hydrostatic"])
gas_f = pressure_traverse(wl, GasFluid(0.65, cgr=30.0, wgr=5.0), 5000.0, 1000.0, "fancher_brown")
check_true("wet gas well: Pwf above the wellhead pressure", gas_f["pwf"] > 1000.0)
pw_f = vlp_curve(wl, oil, rates_o, 200.0, "fancher_brown")
check_true("VLP curve converges at every rate", len(pw_f) == 10 and all(p > 200.0 for p in pw_f))
# with no slip there is no well loading: the low-rate end is flat instead of rising (the J of the slip correlations), and rises with friction at high rates
pw_h = vlp_curve(wl, oil, rates_o, 200.0, "hagedorn_brown")
check_true("VLP curve: flat at low rates (no loading), rising at high rates", pw_f[1] < 1.05 * pw_f[0] and pw_f[-1] > 1.5 * pw_f[0] and pw_f[-1] > pw_f[-2] > pw_f[-3])
check_true("VLP curve: at the lowest rate it is far below Hagedorn and Brown, which shows the loading (no-slip is a lower bound)", pw_f[0] < 0.8 * pw_h[0])
# the step between two GLR lines: with gas lift the GLR changes at the injection point only, so the solver never meets a jump
# 2000 STB/d with a GOR of 500 on 80 % oil: GLR = 400 + injected Mscf/d / 2, so 2100 Mscf/d is GLR 1450 and 2300 Mscf/d is GLR 1500 + 50
import dataclasses
pw_lo, pw_hi = (pressure_traverse(wl, dataclasses.replace(gl_m, injection_gas_rate=q_inj), 2000.0, 200.0, "fancher_brown")["pwf"] for q_inj in (2100.0, 2300.0))
check_true(f"gas lift GLR crossing 1500 (the friction line changes): Pwf {pw_lo:.0f} then {pw_hi:.0f}, a finite change of less than 10 %",
           abs(pw_hi / pw_lo - 1.0) < 0.10)
rnd_f = _random.Random(63)
bad_f = 0
for _ in range(3000):
    cx = dict(v_sl=10 ** rnd_f.uniform(-3.5, 1.0), v_sg=10 ** rnd_f.uniform(-3.0, 2.6), rho_l=rnd_f.uniform(40.0, 66.0),
              rho_g=10 ** rnd_f.uniform(-0.5, 1.8), mu_l=10 ** rnd_f.uniform(-0.5, 3.0), mu_g=rnd_f.uniform(0.01, 0.03),
              sigma=rnd_f.uniform(2.0, 75.0), glr=10 ** rnd_f.uniform(1.5, 9.0))
    ang_f = rnd_f.choice([90.0, 60.0, 20.0, 0.0, -30.0, -90.0])
    r_x = fancher_brown_gradient(10 ** rnd_f.uniform(1.3, 4.0), ang_f, rnd_f.uniform(1.0, 8.0), 0.0006, cx)
    ok = all(math.isfinite(r_x[k]) for k in ("dpdl", "hl", "hydrostatic", "friction", "f_tp", "re", "e_k"))
    ok = ok and r_x["friction"] > 0.0 and 0.0 <= r_x["hl"] <= 1.0 and abs(r_x["dpdl"] - r_x["hydrostatic"] - r_x["friction"]) < 1e-12
    bad_f += 0 if ok else 1
check_true("3000 random conditions: finite, friction positive, gradient = gravity + friction", bad_f == 0)
check_true("fancher_brown is listed and nothing is left 'not coded yet'", "fancher_brown" in GRADIENT_FUNCS and len(_NOT_YET) == 0)

# =====================================================================
print("\n== A step that straddles a flow-pattern jump (Ansari at a high GOR) ==")
# =====================================================================
# Ansari's annular-to-slug boundary jumps the gradient by about 0.17 psi/ft at a low pressure and a high gas rate (here
# at about 300 psia, 2500 STB/d, GOR 3000 scf/STB).  In a 100 ft step the bottom pressure then has no exact answer; the step
# used to stop with "Pressure did not converge" (found by comparing every correlation on the same well).  A step with no
# answer is now cut in halves (_step_with_split), so the jump in the residual shrinks with the step length.
from vlp import _step_with_split, _step_bottom_pressure
w_jump = Well(*vertical_survey(8000), simple_tubing(2.992, 8000), 200.0)
f_jump = OilWaterFluid(API, GG, RSB, water_cut=0.1, gor=3000.0)
pw_jump = {q_: pressure_traverse(w_jump, f_jump, q_, 200.0, "ansari", 100.0) for q_ in (2000.0, 2500.0, 3000.0)}
check_true("Ansari now solves the 2500 STB/d rate that used to fail", pw_jump[2500.0]["pwf"] > 0.0)
check_true("its bottom-hole pressure lies between the neighbouring rates (no spurious jump)",
           pw_jump[2000.0]["pwf"] < pw_jump[2500.0]["pwf"] < pw_jump[3000.0]["pwf"])
fine = pressure_traverse(w_jump, f_jump, 2500.0, 200.0, "ansari", 25.0)
check("the 100 ft steps agree with 25 ft steps within 1 %", pw_jump[2500.0]["pwf"], fine["pwf"], 0.01)
check_equal("the traverse reports one flow pattern per step", len(pw_jump[2500.0]["regime"]), len(pw_jump[2500.0]["holdup"]))
check_true("gravity + friction + acceleration still add up to the pressure change",
           abs((pw_jump[2500.0]["pwf"] - 200.0) - (pw_jump[2500.0]["dp_hydrostatic"] + pw_jump[2500.0]["dp_friction"])) < 0.05 * (pw_jump[2500.0]["pwf"] - 200.0))
# a step that has an answer is not changed by the splitting wrapper
step_ok = {"md_top": 0.0, "md_bot": 100.0, "tvd_top": 0.0, "tvd_bot": 100.0, "length": 100.0, "angle_deg": 90.0, "id_in": 2.992}
direct = _step_bottom_pressure(GRADIENT_FUNCS["hagedorn_brown"], f_jump, 2000.0, 200.0, 150.0, step_ok, 0.0006)
wrapped = _step_with_split(GRADIENT_FUNCS["hagedorn_brown"], f_jump, 2000.0, 200.0, 150.0, step_ok, 0.0006)
check("a step with an answer is solved exactly as before", wrapped[0], direct[0], 1e-12)

# =====================================================================
print("\n== A rate the tubing cannot carry gives a very high pressure, not a crash ==")
# =====================================================================
# 6000 STB/d at a GOR of 8000 scf/STB through 1.995 in tubing needs far more than 20,000 psia.  Found by the random sweep:
# the bottom-pressure search wandered to 117,000 psia, where the viscosity correlation goes negative, and the
# calculation stopped with "Reynolds number must be > 0".  The pressure is now capped at P_MAX.
w_small = Well(*vertical_survey(9000), simple_tubing(1.995, 9000), 200.0)
f_rich = OilWaterFluid(25.0, GG, 2000.0, water_cut=0.3, gor=8000.0)
for corr_ in ("beggs_brill", "hagedorn_brown", "duns_ros", "mukherjee_brill"):
    r_cap = pressure_traverse(w_small, f_rich, 6000.0, 100.0, corr_, 100.0)
    check_true(f"{corr_}: an impossible rate gives a very high bottom-hole pressure ({r_cap['pwf']:,.0f} psia)",
               r_cap["pwf"] > 5000.0 and r_cap["pwf"] <= P_MAX + 1e-9)
check_equal("the cap is 20,000 psia", P_MAX, 20000.0)
r_ok = pressure_traverse(w_small, f_rich, 300.0, 100.0, "hagedorn_brown", 100.0)
check_true("a rate the tubing can carry is not touched by the cap", 100.0 < r_ok["pwf"] < 10000.0)

# =====================================================================
print("\n== Bad inputs must be rejected ==")
check_raises("friction factor with Re = 0", ValueError, friction_factor, 0.0)
c = dict(v_sl=0.0, v_sg=0.0, rho_l=62.4, rho_g=5.0, mu_l=1.0, mu_g=0.015, sigma=70.0)
check_raises("no flow in the correlation", ValueError, beggs_brill_gradient, 1000.0, 90.0, 3.0, 0.0, c)
check_raises("water cut above 1", ValueError, OilWaterFluid, API, GG, RSB, water_cut=1.5)
check_raises("rate = 0", ValueError, pressure_traverse, wl, oil, 0.0, 200.0)
check_raises("wellhead pressure = 0", ValueError, pressure_traverse, wl, oil, 1000.0, 0.0)
check_raises("unknown correlation", ValueError, pressure_traverse, wl, oil, 1000.0, 200.0, "no_such_method")
check_raises("gas gravity = 0", ValueError, GasFluid, 0.0)

# =====================================================================
print("\n== Continuous gas lift: gas injected at one depth ==")
import copy
import dataclasses
gl = copy.deepcopy(oil)
gl.injection_gas_rate, gl.injection_md = 0.0, 5000.0
check("gas lift rate 0 = no gas lift (same Pwf)", pressure_traverse(wl, gl, 2000.0, 200.0, "beggs_brill")["pwf"],
      pressure_traverse(wl, oil, 2000.0, 200.0, "beggs_brill")["pwf"], tol=1e-12)
# The lift gas adds its own volume to the gas flow: v_sg(with) - v_sg(without) = injected scf/d * Bg / area / 86400
# (hand: Bg of the injected gas from pvt.gas_properties; the pipe area is pi/4 d^2)
gl.injection_gas_rate = 1000.0
p_t, t_f, d_in, inj = 1500.0, 150.0, 2.992, 1.0e6
c0 = gl.conditions(2000.0, p_t, t_f, d_in)
c1 = gl.conditions(2000.0, p_t, t_f, d_in, inj_scfd=inj)
bg = pvt.gas_properties(p_t, t_f, gl.gas_sg)["bg"]
area = math.pi * (d_in / 12.0) ** 2 / 4.0
check("lift gas adds inj * Bg / area / 86400 to the superficial gas velocity", c1["v_sg"] - c0["v_sg"], inj * bg / area / 86400.0)
check("liquid velocity is not changed by the lift gas", c1["v_sl"], c0["v_sl"], tol=1e-12)
check("same gas gravity: mixed gas density is the formation gas density", c1["rho_g"], c0["rho_g"], tol=1e-9)
gl_heavy = copy.deepcopy(gl)
gl_heavy.injection_gas_sg = 1.2
c2 = gl_heavy.conditions(2000.0, p_t, t_f, d_in, inj_scfd=inj)
check_true("heavier lift gas: the gas mixture is denser", c2["rho_g"] > c1["rho_g"])
res_n = pressure_traverse(wl, oil, 2000.0, 200.0, "beggs_brill")
res_g = pressure_traverse(wl, gl, 2000.0, 200.0, "beggs_brill")
check_true("gas lift lowers the flowing bottom-hole pressure (lighter column)", res_g["pwf"] < res_n["pwf"] - 100.0)
check_true("the calculation has a step boundary exactly at the injection depth", 5000.0 in res_g["md"])
check_true("more lift gas -> lower Pwf (500 -> 1000 Mscf/d at this rate)",
           pressure_traverse(wl, dataclasses.replace(gl, injection_gas_rate=500.0), 2000.0, 200.0)["pwf"] > res_g["pwf"])
check_true("the wellhead is warmer with gas lift (more mass flowing up the tubing)", res_g["T"][0] > res_n["T"][0])
check_true("the temperature at the perforations is still the reservoir temperature", abs(res_g["T"][-1] - wl.t_reservoir) < 1e-9)
check_raises("injection below the perforations", ValueError, pressure_traverse, wl,
             dataclasses.replace(gl, injection_md=9000.0), 2000.0, 200.0)
check_raises("gas lift without an injection depth", ValueError, OilWaterFluid, API, GG, RSB, injection_gas_rate=500.0)
check_raises("negative injection rate", ValueError, OilWaterFluid, API, GG, RSB, injection_gas_rate=-5.0, injection_md=3000.0)

print("\nAll checks passed.")
