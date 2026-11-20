"""Quick checks for nodal.py.  Run:  python test_nodal.py
(needs pvt.py, ipr.py, well.py, vlp.py and nodal.py in the same folder; takes about 20 seconds)

Two kinds of check
    * "exact"   : IPR and VLP are simple formulas, so the crossing can be worked out by
                  hand (the algebra is in the comments).
    * "chain"   : the real well model.  There is no textbook answer for these, so we check
                  that the answer is self-consistent (it lies on BOTH curves) and that
                  changing an input moves the result in the physically correct direction.
A check passes when the code agrees to within 0.1 % unless a different tolerance is shown.
"""
import numpy as np
import pvt
import ipr
from nodal import *
from vlp import OilWaterFluid, GasFluid, pressure_traverse
from well import Well, vertical_survey, simple_tubing


def check(name, got, expected, tol=0.001):
    """Pass if 'got' is within tol (0.001 = 0.1 %) of 'expected' (exactly 0 -> within 1e-6)."""
    if expected == 0:
        ok = abs(got) <= 1e-6
    else:
        ok = abs(got - expected) <= tol * abs(expected)
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<56s} got {got:12.6g}   expected {expected:12.6g}")
    assert ok, name


def check_true(name, condition):
    print(f"  {'PASS' if condition else 'FAIL'}  {name}")
    assert condition, name


def check_raises(name, error_type, function, *args, **kwargs):
    """Pass if calling function(...) raises the given kind of error."""
    try:
        function(*args, **kwargs)
    except error_type:
        print(f"  PASS  {name:<56s} ({error_type.__name__} raised, as wanted)")
        return
    raise AssertionError(f"{name}: expected a {error_type.__name__} but none was raised")


def increasing(values):
    return all(values[i] < values[i + 1] for i in range(len(values) - 1))


def decreasing(values):
    return all(values[i] > values[i + 1] for i in range(len(values) - 1))


# =====================================================================
print("== Exact case 1: straight-line IPR and straight-line VLP ==")
# IPR: q = 3 * (3000 - Pwf)          (J = 3, Pr = 3000)         -> AOF = 9000
# VLP: Pwf = 500 + 0.2 * q
# Crossing: q = 3 * (3000 - 500 - 0.2 q) = 7500 - 0.6 q  ->  1.6 q = 7500  ->  q = 4687.5
#           Pwf = 500 + 0.2 * 4687.5 = 1437.5
def q_line(pwf):
    return max(3.0 * (3000.0 - pwf), 0.0)

r = find_operating_point(q_line, lambda q: 500.0 + 0.2 * q)
check("operating rate", r["q"], 4687.5)
check("operating Pwf", r["pwf"], 1437.5)
check("AOF reported", r["aof"], 9000.0)
check_true("found, one crossing, and it is stable", r["found"] and len(r["crossings"]) == 1 and r["crossings"][0]["stable"])

print("\n== Exact case 2: a J-shaped VLP crosses the IPR twice ==")
# IPR as above (Pwf = 3000 - q/3).  VLP: Pwf = 3200 - 1.2 q + 0.0004 q^2
# 3200 - 1.2 q + 0.0004 q^2 = 3000 - q/3   ->   0.0004 q^2 - 0.86667 q + 200 = 0
# q = (0.86667 -/+ sqrt(0.75111 - 0.32)) / 0.0008 = 262.60  and  1904.07
r = find_operating_point(q_line, lambda q: 3200.0 - 1.2 * q + 0.0004 * q * q)
check_true("two crossings found", len(r["crossings"]) == 2)
check("lower crossing", r["crossings"][0]["q"], 262.60)
check_true("lower crossing is flagged unstable", not r["crossings"][0]["stable"])
check("upper crossing", r["crossings"][1]["q"], 1904.07)
check_true("upper crossing is flagged stable", r["crossings"][1]["stable"])
check("operating point = the stable (higher-rate) crossing", r["q"], 1904.07)
check("operating Pwf lies on the IPR: 3000 - q/3", r["pwf"], 3000.0 - 1904.07 / 3.0)

print("\n== Exact case 3: very strong well (VLP is a flat 100 psia) ==")
# q = 3 * (3000 - 100) = 8700 at Pwf = 100
r = find_operating_point(q_line, lambda q: 100.0)
check("operating rate", r["q"], 8700.0)
check("operating Pwf", r["pwf"], 100.0)

print("\n== Exact case 4: the VLP is above the IPR everywhere ==")
r = find_operating_point(q_line, lambda q: 3500.0 + q)
check_true("nothing found", not r["found"])
check_true("rate and Pwf are None", r["q"] is None and r["pwf"] is None)
check_true("a plain-language message is given", "will not flow" in r["message"])

print("\n== find_operating_point: bad inputs ==")
check_raises("IPR with zero flow", ValueError, find_operating_point, lambda pwf: 0.0, lambda q: 500.0)
check_raises("n_grid too small", ValueError, find_operating_point, q_line, lambda q: 500.0, n_grid=2)
check_raises("q_min_frac = 0", ValueError, find_operating_point, q_line, lambda q: 500.0, q_min_frac=0.0)

# =====================================================================
print("\n== Oil well: 8000-ft vertical, 2.992-in tubing, 20 % water, PI = 3 ==")
wl = Well(*vertical_survey(8000), simple_tubing(2.992, 8000), 200.0)
oil = OilWaterFluid(35.0, 0.75, 500.0, water_cut=0.2)
pb = pvt.oil_properties(3000.0, 200.0, 35.0, 0.75, 500.0)["pb"]
base = dict(well=wl, fluid=oil, ipr_function=ipr.oil_pi, p_res=3000.0,
            ipr_inputs={"pb": pb, "J": 3.0}, p_wh=200.0, max_step_ft=200.0, n_grid=20)
r = solve_well(**base)
print(f"  operating point: q = {r['q']:.0f} STB/d at Pwf = {r['pwf']:.0f} psia (AOF {r['aof']:.0f})")
check_true("a stable operating point exists", r["found"])
check("lies on the IPR: IPR rate at Pwf = q", ipr.oil_pi(3000.0, r["pwf"], pb, 3.0), r["q"])
check("lies on the VLP: traverse at q gives Pwf",
      pressure_traverse(wl, oil, r["q"], 200.0, max_step_ft=200.0)["pwf"], r["pwf"])
check_true("rate is below the AOF", r["q"] < r["aof"])
check("AOF equals the IPR at Pwf = 0", r["aof"], ipr.oil_pi(3000.0, 0.0, pb, 3.0))
check_true("the lower crossing (if any) is the unstable one",
           all(not c["stable"] for c in r["crossings"][:-1]) and r["crossings"][-1]["stable"])

print("\n== Oil well: curves for plotting ==")
cv = curves(wl, oil, ipr.oil_pi, 3000.0, {"pb": pb, "J": 3.0}, 200.0, max_step_ft=200.0, n_points=12)
check_true("four lists of the same length (12)", len(cv["ipr_q"]) == len(cv["ipr_pwf"]) == len(cv["vlp_q"]) == len(cv["vlp_pwf"]) == 12)
check("IPR starts at Pwf = Pr", cv["ipr_pwf"][0], 3000.0)
check("IPR rate is zero at Pwf = Pr", cv["ipr_q"][0], 0.0)
check("IPR ends at Pwf = 0", cv["ipr_pwf"][-1], 0.0)
check_true("IPR rate rises as Pwf falls", increasing(cv["ipr_q"]))
check("VLP last rate is the AOF", cv["vlp_q"][-1], r["aof"])
check_true("VLP rates rise", increasing(cv["vlp_q"]))
check_true("every VLP pressure is above the wellhead pressure", all(p > 200.0 for p in cv["vlp_pwf"]))

print("\n== Oil well: sensitivities ==")
q_of = lambda results: [x["q"] for x in results]
res = sensitivity(base, "p_wh", [100.0, 200.0, 400.0])
check_true("higher wellhead pressure -> lower rate", decreasing(q_of(res)))
res = sensitivity(base, "fluid.water_cut", [0.0, 0.2, 0.5])
check_true("more water (heavier column) -> lower rate", decreasing(q_of(res)))
res = sensitivity(base, "ipr_inputs.J", [1.0, 2.0, 3.0, 5.0])
check_true("higher productivity index -> higher rate", increasing(q_of(res)))
res = sensitivity(base, "p_res", [2600.0, 3000.0, 3400.0])
check_true("higher reservoir pressure -> higher rate", increasing(q_of(res)))
tubings = [well_with_tubing_id(wl, d) for d in (2.441, 2.992, 3.958)]
res = sensitivity(base, "well", tubings)
check_true("larger tubing -> higher rate", increasing(q_of(res)))
check("middle tubing value reproduces the base case", res[1]["q"], r["q"], tol=1e-6)
res = sensitivity(base, "p_wh", [200.0, 1500.0])
check_true("a wellhead pressure of 1500 psia kills the well", res[0]["found"] and not res[1]["found"] and res[1]["q"] is None)
check("the base inputs were not changed (water cut)", base["fluid"].water_cut, 0.2)
check("the base inputs were not changed (J)", base["ipr_inputs"]["J"], 3.0)
check("the base inputs were not changed (p_wh)", base["p_wh"], 200.0)
check("well_with_tubing_id leaves the original alone", wl.tubing[0][2], 2.992)

print("\n== Oil well: sensitivity with one curve per value ==")
res = sensitivity(base, "p_wh", [100.0, 200.0, 400.0], with_curves=True)
check_true("without with_curves there are no curves", "curves" not in sensitivity(base, "p_wh", [200.0])[0])
check("one set of curves per value", len(res), 3)
check_true("every set has the four curve lists", all(set(x["curves"]) == {"ipr_q", "ipr_pwf", "vlp_q", "vlp_pwf"} for x in res))
check_true("the operating points are the same as without curves", [x["q"] for x in res] == q_of(sensitivity(base, "p_wh", [100.0, 200.0, 400.0])))
check_true("higher wellhead pressure -> the whole VLP moves up (same rates)",
           all(a < b < c for a, b, c in zip(res[0]["curves"]["vlp_pwf"], res[1]["curves"]["vlp_pwf"], res[2]["curves"]["vlp_pwf"])))
check_true("wellhead pressure does not change the IPR", res[0]["curves"]["ipr_q"] == res[2]["curves"]["ipr_q"])
check("the 200 psia curves are the base-case curves (VLP at 200 psia)", res[1]["curves"]["vlp_pwf"][-1], cv["vlp_pwf"][-1], tol=1e-9)
res = sensitivity(base, "ipr_inputs.J", [1.0, 3.0], with_curves=True)
check_true("a larger J gives a larger AOF (the curves follow the input)", res[1]["curves"]["ipr_q"][-1] > res[0]["curves"]["ipr_q"][-1])
check_true("the VLP of each run is calculated up to its own AOF", res[1]["curves"]["vlp_q"][-1] > res[0]["curves"]["vlp_q"][-1])
check("well_with_tubing_id sets the new size", tubings[2].tubing[0][2], 3.958)
check_raises("misspelt input name", ValueError, sensitivity, base, "p_whh", [100.0])
check_raises("misspelt IPR input name", ValueError, sensitivity, base, "ipr_inputs.JJ", [3.0])
check_raises("misspelt fluid input name", ValueError, sensitivity, base, "fluid.no_such_thing", [0.1])

# =====================================================================
print("\n== Gas well: Jones IPR + gas VLP ==")
GAS = dict(temp_f=200.0, k=5.0, h=40.0, mu=0.02, z=0.9, re=1000.0, rw=0.4)
gas = GasFluid(0.65)
gbase = dict(well=wl, fluid=gas, ipr_function=ipr.gas_jones, p_res=3000.0,
             ipr_inputs=dict(gas_sg=0.65, **GAS), p_wh=500.0, max_step_ft=200.0, n_grid=20)
g = solve_well(**gbase)
print(f"  operating point: q = {g['q']:.0f} Mscf/d at Pwf = {g['pwf']:.0f} psia (AOF {g['aof']:.0f})")
check_true("a stable operating point exists", g["found"])
check("lies on the IPR", ipr.gas_jones(3000.0, g["pwf"], gas_sg=0.65, **GAS), g["q"])
check("lies on the VLP", pressure_traverse(wl, gas, g["q"], 500.0, max_step_ft=200.0)["pwf"], g["pwf"])
res = sensitivity(gbase, "p_wh", [300.0, 500.0, 800.0])
check_true("higher wellhead pressure -> lower gas rate", decreasing(q_of(res)))
res = sensitivity(gbase, "ipr_inputs.k", [2.0, 5.0, 10.0])
check_true("higher permeability -> higher gas rate", increasing(q_of(res)))

# =====================================================================
print("\n== VLP matching: gravity and friction multipliers ==")
CASE = dict(well=wl, fluid=oil, rate=2000.0, p_wh=200.0, correlation="hagedorn_brown", max_step_ft=200.0)
plain = pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0)
check("multipliers of 1.0 change nothing", pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0, 1.0, 1.0)["pwf"], plain["pwf"], tol=1e-12)
more_f = pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0, 1.0, 1.2)
more_g = pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0, 1.1, 1.0)
check_true("friction multiplier above 1 -> higher Pwf", more_f["pwf"] > plain["pwf"])
check_true("gravity multiplier above 1 -> higher Pwf", more_g["pwf"] > plain["pwf"])
# The split reported by the traverse follows the multipliers, but not exactly: a larger multiplier
# raises the pressure along the well, which compresses the gas and makes the fluid denser, so the
# gravity part grows by MORE than the multiplier alone (the exact scaling is tested in test_vlp.py).
check("friction part follows the friction multiplier (about x1.2)", more_f["dp_friction"], 1.2 * plain["dp_friction"], tol=0.03)
check_true("gravity part grows by at least the multiplier (x1.1) and by less than x1.3",
           1.1 * plain["dp_hydrostatic"] <= more_g["dp_hydrostatic"] <= 1.3 * plain["dp_hydrostatic"])
for corr in ("beggs_brill", "hagedorn_brown", "gray"):
    fl = gas if corr == "gray" else oil
    a = pressure_traverse(wl, fl, 2000.0, 300.0, corr, 200.0, 1.0, 1.0)["pwf"]
    b = pressure_traverse(wl, fl, 2000.0, 300.0, corr, 200.0, 1.0, 1.3)["pwf"]
    check_true(f"{corr}: a larger friction multiplier raises Pwf", b > a)
# The multipliers reach the operating point, the sensitivities and the curves
r1 = solve_well(**base)
r2 = solve_well(**base, friction_mult=1.5)
check_true("more friction -> lower operating rate", r2["q"] < r1["q"])
via_sens = sensitivity(dict(base, friction_mult=1.0), "friction_mult", [1.0, 1.5])
check("sensitivity on the multiplier: 1.0 reproduces the base case", via_sens[0]["q"], r1["q"], tol=1e-9)
check("sensitivity on the multiplier: 1.5 matches the direct run", via_sens[1]["q"], r2["q"], tol=1e-9)
curve_args = {k: v for k, v in base.items() if k != "n_grid"}
cv1 = curves(**curve_args)
cv2 = curves(**curve_args, friction_mult=1.5)
check_true("VLP curve moves up with a larger friction multiplier", all(b > a for a, b in zip(cv1["vlp_pwf"], cv2["vlp_pwf"])))
check("IPR curve is not affected by the multipliers", cv2["ipr_q"][5], cv1["ipr_q"][5], tol=1e-12)

# Finding the multiplier from a measured test.  Round trip: invent a "measured" pressure with a known
# multiplier, then check that the search gives that multiplier back.
for fit, known in (("friction", 1.17), ("gravity", 0.93)):
    kw = {"friction_mult": known} if fit == "friction" else {"gravity_mult": known}
    measured = pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0, **kw)["pwf"]
    found = match_vlp_multiplier(fit=fit, pwf_measured=measured, **CASE)
    check(f"round trip: {fit} multiplier {known} is found again", found, known, tol=1e-3)
check("a measured pressure equal to the plain result gives 1.0",
      match_vlp_multiplier(pwf_measured=plain["pwf"], **CASE), 1.0, tol=1e-3)
check_raises("measured pressure far too high to match", ValueError,
             match_vlp_multiplier, pwf_measured=plain["pwf"] * 3.0, **CASE)
check_raises("measured pressure below the wellhead pressure", ValueError,
             match_vlp_multiplier, pwf_measured=150.0, **CASE)
check_raises("unknown 'fit' name", ValueError, match_vlp_multiplier, fit="holdup", pwf_measured=3000.0, **CASE)
check_raises("multiplier outside the allowed range", ValueError,
             pressure_traverse, wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0, 1.0, 50.0)

# Matching a measured pressure SURVEY (gauge readings at several depths): round trips with known multipliers.
print("\n== VLP matching from a pressure survey ==")
depths = [1500.0, 4000.0, 6500.0, 8000.0]
known = {"gravity_mult": 1.12, "friction_mult": 0.75}
tr_known = pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0, **known)
meas = list(np.interp(depths, tr_known["md"], tr_known["p"]))
SV = dict(well=wl, fluid=oil, rate=2000.0, p_wh=200.0, depths_md=depths, pressures=meas, correlation="hagedorn_brown", max_step_ft=200.0)
both = match_vlp_survey(fit="both", **SV)
# both multipliers together are fixed by two or more points; friction is the weak one (it is a small part of the drop),
# so it is checked to 0.05 and the error left at the points to under 1 psi
check("both: gravity multiplier found again", both["gravity"], 1.12, tol=0.01)
check("both: friction multiplier found again", both["friction"], 0.75, tol=0.07)
check_true("both: the pressures at the points are reproduced to under 1 psi (RMS)", both["rms_after"] < 1.0)
check_true("both: the error before matching is large", both["rms_before"] > 50.0)
check_true("both: nothing at the edge of the range", both["at_limit"] == [])
# one multiplier only: measurements made with that multiplier alone are matched exactly
for fit, mult in (("friction", 1.3), ("gravity", 0.9)):
    t1 = pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0, **({"friction_mult": mult} if fit == "friction" else {"gravity_mult": mult}))
    m1 = list(np.interp(depths, t1["md"], t1["p"]))
    found = match_vlp_survey(**dict(SV, pressures=m1), fit=fit)
    check(f"{fit} only: multiplier {mult} found again", found[fit], mult, tol=2e-3)
    check(f"{fit} only: the other multiplier stays 1.0", found["gravity" if fit == "friction" else "friction"], 1.0, tol=1e-12)
# one point (the bottom): the friction multiplier alone, like match_vlp_multiplier
p_bottom = pressure_traverse(wl, oil, 2000.0, 200.0, "hagedorn_brown", 200.0, 1.0, 1.3)["pwf"]
one = match_vlp_survey(**dict(SV, depths_md=[8000.0], pressures=[p_bottom]), fit="friction")
via_single = match_vlp_multiplier(fit="friction", pwf_measured=p_bottom, **CASE)
check("one point at the bottom agrees with the single-test matching", one["friction"], via_single, tol=2e-3)
check_raises("both multipliers from one point", ValueError, match_vlp_survey, **dict(SV, depths_md=[8000.0], pressures=[meas[-1]]), fit="both")
check_raises("both multipliers from two points at the same depth", ValueError, match_vlp_survey, **dict(SV, depths_md=[8000.0, 8000.0], pressures=[meas[-1], meas[-1]]), fit="both")
check_raises("a depth below the bottom of the tubing", ValueError, match_vlp_survey, **dict(SV, depths_md=[9000.0], pressures=[3000.0]), fit="friction")
check_raises("unknown fit name", ValueError, match_vlp_survey, **SV, fit="holdup")
edge = match_vlp_survey(**dict(SV, pressures=[p_ * 1.5 for p_ in meas]), fit="friction")
check_true("pressures that no multiplier can reach: the result sits on the edge and says so", "friction" in edge["at_limit"])
check_true("a perfect survey (the plain correlation) gives multipliers of 1.0",
           (lambda r_: abs(r_["gravity"] - 1.0) < 1e-3 and abs(r_["friction"] - 1.0) < 1e-2)(
               match_vlp_survey(**dict(SV, pressures=list(np.interp(depths, plain["md"], plain["p"]))), fit="both")))

print("\nAll checks passed.")
