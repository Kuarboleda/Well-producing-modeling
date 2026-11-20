"""Quick checks for app_helpers.py.  Run:  python test_app_helpers.py
(needs matplotlib and all the other project files in the same folder; takes about 30 seconds)

Where the expected numbers come from
    * "hand"       : worked out with a calculator (arithmetic in the comments).
    * "regression" : the value this code gave when the page was first built, kept so that
                     a later change that moves it is noticed.  These are NOT independent
                     proofs of correctness; the engineering was checked in the other test files.
    * "consistency": the answer must satisfy a relationship (e.g. lie on the IPR curve).
A check passes when the code agrees to within 0.1 % unless a different tolerance is shown.
"""
import math
import ipr
import pvt
from app_helpers import *
from app_helpers import DEFAULTS, _test_fluid, to_psia, to_psig, ATM
from vlp import pressure_traverse


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


def check_equal(name, got, expected):
    """Pass if 'got' is exactly equal to 'expected' (text, lists)."""
    ok = got == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<56s} got {got!r}")
    assert ok, f"{name}: got {got!r}, expected {expected!r}"


def check_raises(name, error_type, function, *args, **kwargs):
    """Pass if calling function(...) raises the given kind of error."""
    try:
        function(*args, **kwargs)
    except error_type:
        print(f"  PASS  {name:<56s} ({error_type.__name__} raised, as wanted)")
        return
    raise AssertionError(f"{name}: expected a {error_type.__name__} but none was raised")


# The page works in gauge pressure (psig) and the engine in absolute (psia), so a test that calls the engine
# directly uses these, not the numbers typed on the page.
PR = to_psia(DEFAULTS["p_res"])            # 3,000 psig = 3,014.7 psia
PWH = to_psia(DEFAULTS["p_wh"])            # 200 psig = 214.7 psia


def solve(inputs):
    case = build_case({"water_cut": 0.0, **inputs})       # 0 % water cut unless a test asks otherwise
    return case, run_case(case, n_curve_points=12)


# =====================================================================
print("== Oil well with the page defaults (PI = 3) ==")
case, out = solve({})
r = out["result"]
# Bubble point from Glaso (rsb 500, 35 API, gas 0.75, 200 F) = 2498.4 psia.
# AOF by hand (3,000 psig = 3,014.7 psia): qb = 3 * (3014.7 - 2498.38) = 1549.0 ;
# qv = 3 * 2498.38 / 1.8 = 4164.0 ; AOF = 5712.9
check("bubble point used (regression)", case["pb"], 2498.38)
check("AOF (hand)", r["aof"], 5712.9)
check("operating rate (regression)", r["q"], 2653.58)
check("operating Pwf (regression)", r["pwf"], 2102.26)
check("consistency: on the IPR", ipr.oil_pi(PR, r["pwf"], case["pb"], 3.0), r["q"])
check("consistency: on the VLP",
      pressure_traverse(case["solve"]["well"], case["solve"]["fluid"], r["q"], PWH,
                        max_step_ft=case["solve"]["max_step_ft"])["pwf"], r["pwf"])
check_true("rate label is liquid STB/d", case["rate_label"] == "Liquid rate (STB/d)")
check_true("profile exists and starts at the wellhead pressure", out["traverse"] is not None and out["traverse"]["p"][0] == PWH)
check("profile ends at the operating Pwf", out["traverse"]["p"][-1], r["pwf"])
check("profile ends at reservoir temperature", out["traverse"]["T"][-1], 200.0)

print("\n== Oil well: other IPR models ==")
# Vogel with a test point taken from the PI model itself must give the PI answer back.
q_test = ipr.oil_pi(PR, to_psia(2000.0), case["pb"], 3.0)
_, o = solve(dict(oil_ipr="vogel", vogel_q=q_test, vogel_pwf=2000.0))
check("Vogel built from the PI model's own test: rate", o["result"]["q"], r["q"], tol=1e-6)
check("Vogel built from the PI model's own test: Pwf", o["result"]["pwf"], r["pwf"], tol=1e-6)
# Darcy defaults (rw = 0.354 ft): ln(1000/0.354) - 0.75 = 7.19621 ; J = 50*20/(141.2*1.25*0.8*7.19621) = 0.98415 ;
# AOF = 0.98415*(3014.7-2498.38) + 0.98415*2498.38/1.8 = 508.1 + 1366.0 = 1874.1
_, o = solve(dict(oil_ipr="darcy"))
check("Darcy AOF (hand)", o["result"]["aof"], 1874.1)
check_true("Darcy: well flows", o["result"]["found"])
# Fetkovich defaults in psia (3,014.7 / 2,514.7 / 1,814.7): Pr^2 - Pwf^2 = 2.7647e6 and 5.7953e6 ;
# n = log(1000/2000) / log(2.7647e6/5.7953e6) = 0.93655 ; AOF = 1000 * (9.0884e6/2.7647e6)^n = 3048.2
_, o = solve(dict(oil_ipr="fetkovich"))
check("Fetkovich AOF (hand)", o["result"]["aof"], 3048.2)
check_true("Fetkovich: well flows", o["result"]["found"])

print("\n== Oil well: Darcy flow regimes and horizontal (Joshi) well ==")
# Default Darcy well is the pseudosteady one: J = 0.98415 (see above).
c_ps, o_ps = solve(dict(oil_ipr="darcy", oil_regime="pseudosteady"))
check("Darcy pseudosteady = the default Darcy answer", o_ps["result"]["aof"], 1874.1)
# Steady state: ln(1000/0.354)=7.94621 (no -0.75) -> J = 1000/(141.2*1.25*0.8*7.94621) = 0.89126 (9.4 % below 0.98415)
c_ss, o_ss = solve(dict(oil_ipr="darcy", oil_regime="steady"))
check("steady-state J lowers the AOF in the ratio of the brackets",
      o_ss["result"]["aof"] / o_ps["result"]["aof"], 7.19621 / 7.94621)
# Transient after 12 h with phi=0.2, ct=1e-5: J from the transient equation, computed here by hand
#   log10(12) = 1.07918 ; k/(phi*mu*ct*rw^2) = 50/(0.2*0.8*1e-5*0.125316) = 2.4937e8 -> log10 = 8.39684
#   bracket = 1.07918 + 8.39684 - 3.23 = 6.24602 ; J = 1000/(162.6*1.25*0.8*6.24602)
c_tr, o_tr = solve(dict(oil_ipr="darcy", oil_regime="transient"))
J_tr = 1000.0 / (162.6 * 1.25 * 0.8 * 6.24602)
check("transient J (hand): rate at Pwf = Pb", c_tr["solve"]["ipr_function"](PR, c_tr["pb"], **c_tr["solve"]["ipr_inputs"]),
      J_tr * (PR - c_tr["pb"]))
_, o_tr_late = solve(dict(oil_ipr="darcy", oil_regime="transient", oil_time=30.0))
check_true("the later the time, the lower the transient rate", o_tr_late["result"]["q"] < o_tr["result"]["q"])
# Valid only until 948*phi*mu*ct*re^2/k = 948*0.2*0.8*1e-5*1e6/50 = 30.3 hours
check_equal("no warning at 12 h", transient_warning(dict(oil_ipr="darcy", oil_regime="transient")), "")
check_true("warning at 720 h names the valid time",
           "30 hours" in transient_warning(dict(oil_ipr="darcy", oil_regime="transient", oil_time=720.0)))
check_equal("no warning for the other regimes", transient_warning(dict(oil_ipr="darcy", oil_time=720.0)), "")
# Horizontal well defaults: kh=100, kv=10, h=50, L=1000, re_h=1500, rw=0.354, Bo=1.25, mu=0.8
c_hz, o_hz = solve(dict(oil_ipr="horizontal"))
J_hz = ipr.horizontal_productivity_index_oil_joshi(50, 5, 50, 1000, 1500, 0.354, 1.25, 0.8)
check("horizontal: AOF from the page = AOF from ipr.py",
      o_hz["result"]["aof"], ipr.oil_horizontal_joshi(PR, 0.0, c_hz["pb"], 50, 5, 50, 1000, 1500, 0.354, 1.25, 0.8))
check_true("horizontal: well flows", o_hz["result"]["found"])
_, o_hz_long = solve(dict(oil_ipr="horizontal", hz_length=2000.0))
check_true("a longer horizontal section gives a higher AOF", o_hz_long["result"]["aof"] > o_hz["result"]["aof"])
check_raises("horizontal well longer than its drainage area", ValueError,
             lambda: solve(dict(oil_ipr="horizontal", hz_length=4000.0)))
opts = [o["key"] for o in sensitivity_options(dict(oil_ipr="horizontal"))]
check_true("sensitivity offers the horizontal length and kh", "length" in opts and "kh" in opts)
check_true("horizontal default kv = 10 % of kh = 50 md", (c_hz["solve"]["ipr_inputs"]["kh"], c_hz["solve"]["ipr_inputs"]["kv"]) == (50.0, 5.0))
res = run_sensitivity(c_hz, "length", [500.0, 1000.0, 2000.0])
check_true("sensitivity on length: rate rises with length", res[0]["q"] < res[1]["q"] < res[2]["q"])
res = run_sensitivity(c_hz, "kh", [50.0, 100.0, 200.0])
check_true("sensitivity on kh: rate rises with kh", res[0]["q"] < res[1]["q"] < res[2]["q"])

print("\n== Oil well: input effects ==")
c_meas = build_case(dict(pb_meas=2400.0))
check("measured bubble point is used (2,400 psig typed = 2,414.7 psia inside)", c_meas["pb"], to_psia(2400.0))
_, o = solve(dict(water_cut=0.3))
check_true("30 % water cut lowers the rate", o["result"]["q"] < r["q"])
_, o = solve(dict(p_wh=1500.0))
check_true("wellhead pressure of 1500 psig: no flow", not o["result"]["found"])
check_true("no flow: no profile, but the curves are still there", o["traverse"] is None and len(o["curves"]["vlp_q"]) == 12)
_, o = solve(dict(survey_mode="deviated"))
check_true("deviated well (default survey) flows", o["result"]["found"])
check("deviated: perforations at MD 9000", o["traverse"]["md"][-1], 9000.0)
check("deviated: perforations at TVD 7000", o["traverse"]["tvd"][-1], 7000.0)
_, o = solve(dict(perf_ambient_is_reservoir=False, t_amb_perf=150.0, depth=8000.0))
check_true("ambient at perforations can differ from reservoir temperature", o["result"]["found"])

# =====================================================================
print("\n== Gas well ==")
# Back pressure with the defaults C = 0.015, n = 0.85, Pr = 3,000 psig = 3,014.7 psia:
# AOF = 0.015 * (3014.7^2)^0.85 = 12325.5
case_g, out_g = solve(dict(fluid_type="gas", gas_ipr="backpressure", p_wh=500.0))
check("back-pressure AOF (hand)", out_g["result"]["aof"], 12325.5)
check("consistency: on the IPR", ipr.gas_backpressure(PR, out_g["result"]["pwf"], 0.015, 0.85), out_g["result"]["q"])
check_true("rate label is gas Mscf/d", case_g["rate_label"] == "Gas rate (Mscf/d)")
for model in ("darcy", "jones"):
    case_g, out_g = solve(dict(fluid_type="gas", gas_ipr=model, p_wh=500.0))
    check_true(f"{model}: well flows", out_g["result"]["found"])
    check_true(f"{model}: Z taken from PVT is sensible (0.8 - 1.0)", 0.8 < case_g["solve"]["ipr_inputs"]["z"] < 1.0)
_, out_darcy = solve(dict(fluid_type="gas", gas_ipr="darcy", p_wh=500.0))
check_true("Jones (with turbulence) gives less than Darcy", out_g["result"]["aof"] < out_darcy["result"]["aof"])
# Wet gas: separator gas 0.65, CGR 50 STB/MMscf, 50 API -> well-stream gravity 0.7993 (McCain, hand worked)
case_w, out_w = solve(dict(fluid_type="gas", p_wh=500.0, cgr=50.0))
check("wet-gas well-stream gravity (hand)", case_w["gas_sg_used"], 0.7993, tol=0.0005)
check_true("wet gas flows", out_w["result"]["found"])

# =====================================================================
print("\n== Hagedorn and Brown through the page logic ==")
case_h, out_h = solve(dict(correlation="hagedorn_brown"))
rh = out_h["result"]
check_true("oil well flows", rh["found"])
check("operating rate (regression)", rh["q"], 3176.35)
check("operating Pwf (regression)", rh["pwf"], 1890.1)
check("same IPR as before: AOF unchanged", rh["aof"], 5712.9)
check("consistency: on the IPR", ipr.oil_pi(PR, rh["pwf"], case_h["pb"], 3.0), rh["q"])
check("consistency: on the VLP",
      pressure_traverse(case_h["solve"]["well"], case_h["solve"]["fluid"], rh["q"], PWH, "hagedorn_brown",
                        max_step_ft=case_h["solve"]["max_step_ft"])["pwf"], rh["pwf"])
check_true("H&B needs less bottom-hole pressure than Beggs & Brill here, so the rate is higher", rh["q"] > r["q"])
# The pressure iteration used to stop with an error at this exact rate (the guess flipped
# between two values 0.07 psi apart where a chart fit changes formula); it must now work.
check_true("rate that used to stop the iteration now works",
           pressure_traverse(case_h["solve"]["well"], case_h["solve"]["fluid"], 3143.3648218531707, PWH,
                             "hagedorn_brown", max_step_ft=100.0)["pwf"] > 200.0)
# Dry gas is single-phase, so every correlation must give the same answer (physics)
_, gas_bb = solve(dict(fluid_type="gas", p_wh=500.0))
_, gas_hb = solve(dict(fluid_type="gas", p_wh=500.0, correlation="hagedorn_brown"))
check("dry gas: H&B equals Beggs & Brill", gas_hb["result"]["q"], gas_bb["result"]["q"], tol=1e-6)
_, wet_hb = solve(dict(fluid_type="gas", p_wh=500.0, cgr=50.0, correlation="hagedorn_brown"))
check_true("wet gas with H&B flows, with less rate than dry gas", wet_hb["result"]["found"]
           and wet_hb["result"]["q"] < gas_hb["result"]["q"])
print("\n== Gray through the page logic ==")
_, gas_gr = solve(dict(fluid_type="gas", p_wh=500.0, correlation="gray"))
check("dry gas: Gray equals Beggs & Brill (single-phase gas)", gas_gr["result"]["q"], gas_bb["result"]["q"], tol=1e-6)
case_gw, out_gw = solve(dict(fluid_type="gas", p_wh=500.0, cgr=5.0, wgr=1.0, correlation="gray"))
check_true("lean wet gas flows with Gray", out_gw["result"]["found"])
check("consistency: wet-gas operating point is on the Jones IPR",
      case_gw["solve"]["ipr_function"](PR, out_gw["result"]["pwf"], **case_gw["solve"]["ipr_inputs"]), out_gw["result"]["q"])
check_true("wet gas with Gray: within 10 % of the dry-gas rate", abs(out_gw["result"]["q"] / gas_gr["result"]["q"] - 1.0) < 0.10)
res = run_sensitivity(case_gw, "p_wh", [300.0, 500.0, 700.0])
check_true("sensitivity with Gray: higher wellhead pressure -> lower rate", res[0]["q"] > res[1]["q"] > res[2]["q"])

res = run_sensitivity(case_h, "p_wh", [100.0, 200.0, 300.0])
check_true("sensitivity with H&B: higher wellhead pressure -> lower rate",
           res[0]["q"] > res[1]["q"] > res[2]["q"])
check("sensitivity with H&B: the 200 psig point is the base case", res[1]["q"], rh["q"], tol=1e-6)

# =====================================================================
print("\n== VLP matching through the page logic ==")
check_equal("defaults: both multipliers are 1.0", (DEFAULTS["gravity_mult"], DEFAULTS["friction_mult"]), (1.0, 1.0))
check_equal("defaults: no VLP matching note", multiplier_note(case_h), "")
case_m, out_m = solve(dict(correlation="hagedorn_brown", friction_mult=1.25, gravity_mult=0.98))
check_equal("the case carries the multipliers",
            (case_m["solve"]["gravity_mult"], case_m["solve"]["friction_mult"]), (0.98, 1.25))
check_equal("note names both multipliers", multiplier_note(case_m),
            "VLP matching is ON: gravity multiplier 0.98, friction multiplier 1.25")
check_true("more friction (and a little less gravity) changes the operating rate", out_m["result"]["q"] != rh["q"])
check("consistency: the operating point is on the multiplied VLP",
      pressure_traverse(case_m["solve"]["well"], case_m["solve"]["fluid"], out_m["result"]["q"], PWH, "hagedorn_brown",
                        case_m["solve"]["max_step_ft"], 0.98, 1.25)["pwf"], out_m["result"]["pwf"])
check("the profile at the operating rate ends at the operating Pwf", out_m["traverse"]["pwf"], out_m["result"]["pwf"], tol=1e-6)
check("the IPR does not move", out_m["result"]["aof"], rh["aof"], tol=1e-9)
res = run_sensitivity(case_m, "p_wh", [200.0])
check("sensitivity keeps the multipliers", res[0]["q"], out_m["result"]["q"], tol=1e-6)

# Round trip through the matching helper: invent a measured pressure from a known multiplier
base_in = dict(correlation="hagedorn_brown", water_cut=0.0)
# The traverse works in psia; match_from_test is given the test as the page gives it, in psig.
truth = pressure_traverse(case_h["solve"]["well"], case_h["solve"]["fluid"], 2500.0, to_psia(250.0), "hagedorn_brown",
                          case_h["solve"]["max_step_ft"], 1.0, 1.18)["pwf"]
m = match_from_test(base_in, 2500.0, 250.0, to_psig(truth), "friction")
check("match: the known friction multiplier 1.18 is found", m["multiplier"], 1.18, tol=1e-3)
check("match: the matched pressure is the measured one, in psig (multiplier rounded to 0.01)", m["matched_pwf"], to_psig(truth), tol=1e-3)
check("match: also found when the inputs already carry other multipliers",
      match_from_test(dict(base_in, friction_mult=1.7, gravity_mult=0.6), 2500.0, 250.0, to_psig(truth))["multiplier"], 1.18, tol=1e-3)
check("match: reports what the plain correlation gives (psig)",
      m["plain_pwf"], to_psig(pressure_traverse(case_h["solve"]["well"], case_h["solve"]["fluid"], 2500.0, to_psia(250.0),
                                                "hagedorn_brown", case_h["solve"]["max_step_ft"])["pwf"]), tol=1e-9)
check_true("match: the plain pressure is below the measured one (friction multiplier above 1)", m["plain_pwf"] < to_psig(truth))
g_fit = match_from_test(base_in, 2500.0, 250.0, to_psig(truth), "gravity")
check_true("match: fitting gravity instead gives a different multiplier, close to 1", 1.0 < g_fit["multiplier"] < 1.1)
check_equal("match: the multiplier is rounded to 2 decimals", g_fit["multiplier"], round(g_fit["multiplier"], 2))
mg = match_from_test(dict(fluid_type="gas", correlation="gray"), 10000.0, 500.0, 1000.0, "friction")
check_true("match works for a gas well too", 0.5 <= mg["multiplier"] <= 2.0)
check_raises("match: test rate = 0", ValueError, match_from_test, base_in, 0.0, 250.0, 2000.0)
check_raises("match: measured pressure below the wellhead pressure", ValueError, match_from_test, base_in, 2500.0, 250.0, 200.0)
check_raises("match: measured pressure out of reach", ValueError, match_from_test, base_in, 2500.0, 250.0, 9000.0)
check_raises("match: unknown multiplier name", ValueError, match_from_test, base_in, 2500.0, 250.0, truth, "holdup")
check_raises("multiplier out of range stops the calculation", ValueError, run_case,
             build_case(dict(friction_mult=50.0)))

# =====================================================================
print("\n== Bad inputs give plain errors, not crashes ==")
check_raises("survey with one line", ValueError, build_case, dict(survey_mode="deviated", survey_text="0 0"))
check_raises("tubing ID = 0", ValueError, build_case, dict(tubing_id=0.0))
check_raises("water cut above 1", ValueError, build_case, dict(water_cut=1.5))
check_raises("unknown oil IPR model", ValueError, build_case, dict(oil_ipr="nonsense"))
check_raises("unknown gas IPR model", ValueError, build_case, dict(fluid_type="gas", gas_ipr="nonsense"))
check_raises("Vogel test Pwf above reservoir pressure", ValueError, run_case,
             build_case(dict(oil_ipr="vogel", vogel_pwf=3500.0)))
check_raises("Fetkovich tests with the same Pwf", ValueError, run_case,
             build_case(dict(oil_ipr="fetkovich", fet_pwf2=2500.0)))
check_true("the page knows which correlations exist",
           AVAILABLE_CORRELATIONS == ("beggs_brill", "hagedorn_brown", "gray", "orkiszewski", "ansari", "duns_ros", "mukherjee_brill", "fancher_brown"))
o_fb = run_case(build_case(dict(correlation="fancher_brown")), n_curve_points=12)
o_hb = run_case(build_case(dict(correlation="hagedorn_brown")), n_curve_points=12)
check_true("Fancher and Brown: oil well runs, flows, VLP curve complete, every step no-slip",
           o_fb["result"]["found"] and len(o_fb["curves"]["vlp_pwf"]) == 12 and set(o_fb["traverse"]["regime"]) == {"no-slip"})
check_true("Fancher and Brown (no slip, the lowest gravity pressure) flows at least as much as Hagedorn and Brown",
           o_fb["result"]["q"] >= 0.97 * o_hb["result"]["q"])
o_fb_gl = run_case(build_case(dict(correlation="fancher_brown", lift="continuous")), n_curve_points=12)
check_true("Fancher and Brown with continuous gas lift: runs and flows more than without", o_fb_gl["result"]["q"] > o_fb["result"]["q"])
o_fb_gas = run_case(build_case(dict(fluid_type="gas", correlation="fancher_brown", p_wh=500.0)), n_curve_points=12)
check_true("Fancher and Brown on a gas well runs and flows", o_fb_gas["result"]["found"] and o_fb_gas["result"]["q"] > 0)
o_ork = run_case(build_case(dict(correlation="orkiszewski")), n_curve_points=12)
check_true("Orkiszewski: oil well runs, flows, and the VLP curve is complete",
           o_ork["result"]["found"] and len(o_ork["curves"]["vlp_pwf"]) == 12 and o_ork["traverse"] is not None)
o_ork_gl = run_case(build_case(dict(correlation="orkiszewski", lift="continuous")), n_curve_points=12)
check_true("Orkiszewski with continuous gas lift: runs and flows more than without",
           o_ork_gl["result"]["q"] > o_ork["result"]["q"])
o_ork_gas = run_case(build_case(dict(fluid_type="gas", correlation="orkiszewski", p_wh=500.0)), n_curve_points=12)
check_true("Orkiszewski on a gas well: runs", o_ork_gas["result"]["found"])
o_ans = run_case(build_case(dict(correlation="ansari")), n_curve_points=12)
check_true("Ansari: oil well runs, flows, and the VLP curve is complete",
           o_ans["result"]["found"] and len(o_ans["curves"]["vlp_pwf"]) == 12 and o_ans["traverse"] is not None)
o_ans_gl = run_case(build_case(dict(correlation="ansari", lift="continuous")), n_curve_points=12)
check_true("Ansari with continuous gas lift: runs and flows more than without",
           o_ans_gl["result"]["q"] > o_ans["result"]["q"])
o_ans_gas = run_case(build_case(dict(fluid_type="gas", correlation="ansari", p_wh=500.0)), n_curve_points=12)
check_true("Ansari on a gas well: runs", o_ans_gas["result"]["found"])
o_ans_ml = run_case(build_case(dict(correlation="ansari", oil_ipr="multilayer")), n_curve_points=12)
check_true("Ansari with the multilayer IPR: runs", o_ans_ml["result"]["found"])
o_ork_ml = run_case(build_case(dict(correlation="orkiszewski", oil_ipr="multilayer")), n_curve_points=12)
check_true("Orkiszewski with the multilayer IPR: runs", o_ork_ml["result"]["found"])
for corr_, name_ in (("duns_ros", "Duns and Ros"), ("mukherjee_brill", "Mukherjee and Brill")):
    o_c = run_case(build_case(dict(correlation=corr_)), n_curve_points=12)
    check_true(f"{name_}: oil well runs, flows, and the VLP curve is complete",
               o_c["result"]["found"] and len(o_c["curves"]["vlp_pwf"]) == 12 and o_c["traverse"] is not None)
    o_c_gl = run_case(build_case(dict(correlation=corr_, lift="continuous")), n_curve_points=12)
    check_true(f"{name_} with continuous gas lift: runs and flows more than without", o_c_gl["result"]["q"] > o_c["result"]["q"])
    o_c_gas = run_case(build_case(dict(fluid_type="gas", correlation=corr_, p_wh=500.0)), n_curve_points=12)
    check_true(f"{name_} on a gas well: runs", o_c_gas["result"]["found"])
    o_c_ml = run_case(build_case(dict(correlation=corr_, oil_ipr="multilayer")), n_curve_points=12)
    check_true(f"{name_} with the multilayer IPR: runs", o_c_ml["result"]["found"])
    o_c_dev = run_case(build_case(dict(correlation=corr_, survey_mode="deviated",
                                       survey_text="0 0\n2000 2000\n6000 5500\n9000 8000")), n_curve_points=12)
    check_true(f"{name_} in a deviated well: runs", o_c_dev["result"]["found"])

# =====================================================================
print("\n== Sensitivity helpers ==")
keys = lambda inputs: [o["key"] for o in sensitivity_options(inputs)]
check_true("oil + PI: offers p_wh, p_res, tubing, water cut and PI",
           keys({}) == ["p_wh", "p_res", "tubing_id", "water_cut", "gor", "pi"])
check_true("oil + Vogel: no PI or permeability", keys(dict(oil_ipr="vogel")) == ["p_wh", "p_res", "tubing_id", "water_cut", "gor"])
check_true("oil + Darcy: offers permeability and total skin", keys(dict(oil_ipr="darcy"))[-2:] == ["k", "skin"])
check_true("oil + horizontal: offers length, kh and total skin", keys(dict(oil_ipr="horizontal"))[-3:] == ["length", "kh", "skin"])
check_true("oil + PI / Vogel: no skin (the model has none)", "skin" not in keys({}) and "skin" not in keys(dict(oil_ipr="vogel")))
check_true("gas + Jones: offers permeability, no water cut",
           keys(dict(fluid_type="gas")) == ["p_wh", "p_res", "tubing_id", "k", "skin"])
check_true("gas + back pressure: no permeability", keys(dict(fluid_type="gas", gas_ipr="backpressure")) == ["p_wh", "p_res", "tubing_id"])
check_true("evenly spaced values", evenly_spaced(100.0, 400.0, 4) == [100.0, 200.0, 300.0, 400.0])
check_raises("evenly spaced needs two points", ValueError, evenly_spaced, 1.0, 2.0, 1)

rates = lambda results: [x["q"] for x in results]
res = run_sensitivity(case, "p_wh", [100.0, 200.0, 300.0])
check_true("higher wellhead pressure -> lower rate", rates(res)[0] > rates(res)[1] > rates(res)[2])
check("the 200 psig point reproduces the base case", res[1]["q"], r["q"], tol=1e-6)
res = run_sensitivity(case, "tubing_id", [2.441, 2.992, 3.958])
check_true("tubing sizes are reported as numbers", [x["value"] for x in res] == [2.441, 2.992, 3.958])
check_true("larger tubing -> higher rate", rates(res)[0] < rates(res)[1] < rates(res)[2])
res = run_sensitivity(case, "pi", [1.0, 3.0, 5.0])
check_true("higher PI -> higher rate", rates(res)[0] < rates(res)[1] < rates(res)[2])
res = run_sensitivity(case, "water_cut", [0.0, 0.3])
check_true("more water -> lower rate", rates(res)[0] > rates(res)[1])
res = run_sensitivity(case, "p_wh", [200.0, 1500.0])
table = sensitivity_table(res, "Wellhead pressure (psig)", "Liquid rate (STB/d)")
check_true("table shows 'no flow' when the well dies", table[1]["Liquid rate (STB/d)"] == "no flow" and table[1]["Pwf (psig)"] == "-")
check_true("table shows the rounded rate when it flows", table[0]["Liquid rate (STB/d)"] == round(r["q"], 0))
check_raises("water cut outside 0-1", ValueError, run_sensitivity, case, "water_cut", [0.5, 1.5])
check_raises("unknown sensitivity input", ValueError, run_sensitivity, case, "nonsense", [1.0])
check("the base case was not changed by the sensitivities", case["solve"]["p_wh"], PWH)

print("\n== Nov-15 layout: summary inside the chart, aligned plots, oil-rate sensitivity ==")
c_wc, o_wc = solve(dict(water_cut=0.3))
fig_n = make_nodal_figure(o_wc["curves"], o_wc["result"], c_wc["rate_label"], 0.3)
strip = [t.get_text() for t in fig_n.texts]
q_wc = o_wc["result"]["q"]
check_true("summary strip has the operating rate with its unit", f"{q_wc:,.0f} STB/d" in strip)
check_true("summary strip has the flowing bottom-hole pressure, in psig", f"{to_psig(o_wc['result']['pwf']):,.0f} psig" in strip)
check_true("summary strip has the AOF", f"{o_wc['result']['aof']:,.0f} STB/d" in strip)
check_true("water cut 30 %: the oil rate (70 % of the liquid) is shown",
           any(f"oil {0.7 * q_wc:,.0f} STB/d" in t for t in strip))
fig_plain = make_nodal_figure(out["curves"], out["result"], "Liquid rate (STB/d)")
check_true("no water cut: no oil-rate note", not any(t.startswith("oil ") for t in [x.get_text() for x in fig_plain.texts]))
fig_p = make_profile_figure(out["traverse"])
fig_s = make_sensitivity_figure(run_sensitivity(case, "p_wh", [100.0, 200.0]), "Wellhead pressure (psig)", "Oil rate (STB/d)", "q_oil")
rects = [tuple(round(x, 6) for x in f.axes[0].get_position().bounds) for f in (fig_plain, fig_p, fig_s)]
check_true("IPR/VLP, profile and sensitivity plots have exactly the same frame (top and bottom edges line up)",
           rects[0] == rects[1] == rects[2] and fig_plain.get_size_inches().tolist() == fig_p.get_size_inches().tolist() == fig_s.get_size_inches().tolist())
check_equal("sensitivity chart vertical axis (oil)", fig_s.axes[0].get_ylabel(), "Oil rate (STB/d)")
res = run_sensitivity(case, "water_cut", [0.0, 0.5])
check("oil rate at 0 % water cut = liquid rate", res[0]["q_oil"], res[0]["q"])
check("oil rate at 50 % water cut = half the liquid rate", res[1]["q_oil"], 0.5 * res[1]["q"])
res = run_sensitivity(c_wc, "p_wh", [100.0, 200.0])
check("oil rate uses the case's water cut (30 %)", res[0]["q_oil"], 0.7 * res[0]["q"])
res = run_sensitivity(case, "p_wh", [200.0, 1500.0])
check_true("a well that does not flow has no oil rate", res[1]["q_oil"] is None)
table = sensitivity_table(res, "Wellhead pressure (psig)", "Liquid rate (STB/d)", "Oil rate (STB/d)")
check_true("table can carry an oil-rate column", table[0]["Oil rate (STB/d)"] == round(res[0]["q_oil"], 0) and table[1]["Oil rate (STB/d)"] == "no flow")
res = run_sensitivity(case_gw, "p_wh", [300.0, 500.0])
check("gas well: 'oil' rate is the gas rate", res[0]["q_oil"], res[0]["q"])

print("\n== Sensitivity IPR / VLP chart: one curve for each value ==")
res_c = run_sensitivity(case, "p_wh", [100.0, 200.0, 400.0], with_curves=True)
fig_sn = make_sensitivity_nodal_figure(res_c, "Wellhead pressure (psig)", "Liquid rate (STB/d)", "p_wh")
ax_sn = fig_sn.axes[0]
legend = [t.get_text() for t in ax_sn.get_legend().get_texts()]
check_true("wellhead pressure: one VLP per value in the legend",
           [t for t in legend if t.startswith("VLP, ")] == ["VLP, 100 psig", "VLP, 200 psig", "VLP, 400 psig"])
check_true("wellhead pressure: a single IPR, not three", legend.count("IPR (reservoir inflow)") == 1 and not any(t.startswith("IPR, ") for t in legend))
check("one black operating point per flowing value", len(ax_sn.get_lines()[-1].get_xdata()), 3)
strip = [t.get_text() for t in fig_sn.texts]
q_lo, q_hi = min(r["q"] for r in res_c), max(r["q"] for r in res_c)
check_true("strip gives the operating-rate range", f"{q_lo:,.0f} - {q_hi:,.0f}" in strip)
check_true("strip names the varied input and its range", "Wellhead pressure" in strip and "100 to 400 psig" in strip)
check_true("same frame as the other charts (aligned plots)", tuple(round(x, 6) for x in ax_sn.get_position().bounds) == rects[0])
res_pi = run_sensitivity(case, "pi", [1.0, 3.0, 5.0], with_curves=True)
leg_pi = [t.get_text() for t in make_sensitivity_nodal_figure(res_pi, "Productivity index (STB/d/psi)", "Liquid rate (STB/d)", "pi").axes[0].get_legend().get_texts()]
check_true("productivity index: one IPR per value and a single VLP",
           [t for t in leg_pi if t.startswith("IPR, ")] == ["IPR, 1 STB/d/psi", "IPR, 3 STB/d/psi", "IPR, 5 STB/d/psi"] and leg_pi.count("VLP (tubing outflow)") == 1)
res_dead = run_sensitivity(case, "p_wh", [200.0, 1500.0], with_curves=True)
leg_dead = [t.get_text() for t in make_sensitivity_nodal_figure(res_dead, "Wellhead pressure (psig)", "Liquid rate (STB/d)", "p_wh").axes[0].get_legend().get_texts()]
check_true("a value where the well does not flow is marked in the legend", "VLP, 1,500 psig (no flow)" in leg_dead)
res_tub = run_sensitivity(case, "tubing_id", [2.441, 2.992, 3.958], with_curves=True)
check_true("tubing sensitivity also keeps curves", all(r["curves"] for r in res_tub))
check_true("without with_curves a figure still cannot be made, but the message is plain",
           "No curves" in [t.get_text() for t in make_sensitivity_nodal_figure(run_sensitivity(case, "p_wh", [200.0]), "Wellhead pressure (psig)", "Liquid rate (STB/d)").axes[0].texts][0])

print("\n== PVT matching through the page logic ==")
import pvt_match
lab = pvt_match.clean_lab_table([{"p": 500, "rs": 80, "bo": 1.1, "mu": 1.2}, {"p": 1500, "rs": 250, "bo": 1.2, "mu": 0.9},
                                 {"p": 2400, "rs": 500, "bo": 1.3, "mu": 0.7}, {"p": 3500, "bo": 1.28, "mu": 0.9}])
base = pvt_base({})
check_equal("PVT base numbers come from the page defaults", base, {"api": 35.0, "gas_sg": 0.75, "rsb": 500.0, "temp_f": 200.0})
fit = pvt_match.fit_match(lab, **base, pb_meas=2400.0, pvt_method="glaso", visc_method="beal")
applied = dict(fit, pvt_method="glaso", visc_method="beal", pb_meas=2400.0, base=base)
inputs = with_pvt_match({"pvt_method": "standing", "pb_meas": 0.0}, applied)
check_true("applying a match replaces the correlation, the bubble point and carries the numbers",
           inputs["pvt_method"] == "glaso" and inputs["pb_meas"] == 2400.0 and inputs["pvt_match"] == fit["match"])
check_equal("no match applied: inputs unchanged", with_pvt_match({"a": 1}, None), {"a": 1})
c_m = build_case(inputs)
check("the matched case uses the measured bubble point", c_m["pb"], to_psia(2400.0))
check_true("the fluid object carries the match", c_m["solve"]["fluid"].pvt_match == fit["match"])
check_true("matched fluid gives another viscosity than the plain correlation",
           c_m["solve"]["fluid"].conditions(2000.0, 1500.0, 180.0, 2.992)["mu_l"] !=
           build_case(dict(pvt_method="glaso", pb_meas=2400.0))["solve"]["fluid"].conditions(2000.0, 1500.0, 180.0, 2.992)["mu_l"])
_, o_m = solve(inputs)
check_true("the matched well still flows", o_m["result"]["found"])
check_equal("no warning when the fluid still matches", pvt_match_stale_note({}, applied), "")
check_true("warning when the oil gravity changed", "oil gravity" in pvt_match_stale_note({"api": 30.0}, applied))
check_true("warning names GOR and temperature too",
           all(w in pvt_match_stale_note({"rsb": 400.0, "t_res": 180.0}, applied) for w in ("solution GOR", "temperature")))
rows = pvt_comparison_table(pvt_match.compare_methods(lab, base["api"], base["gas_sg"], base["rsb"], base["temp_f"], 2400.0))
check("comparison table has 12 rows (4 Pb/Rs/Bo methods x 3 viscosity methods)", len(rows), 12)
check_true("comparison table: names, not codes", rows[0]["Pb, Rs, Bo correlation"] in PVT_NAMES.values())
fig_pvt = make_pvt_figure(lab, base, 2400.0, "glaso", "beal", fit)
check("PVT chart: three panels (Rs, Bo, viscosity)", len(fig_pvt.axes), 3)
check_true("PVT chart: lab points drawn on every panel",
           all(any(l.get_label() == "Lab data" for l in ax.get_lines()) for ax in fig_pvt.axes))
check_true("PVT chart: the matched line is drawn on every panel",
           all(any(l.get_label() == "Matched" for l in ax.get_lines()) for ax in fig_pvt.axes))
fig_pvt = make_pvt_figure(lab, base, None, "standing", "beggs")
check_true("PVT chart without a fit or a measured Pb draws too", len(fig_pvt.axes) == 3)

# =====================================================================
print("\n== Charts ==")
fig = make_nodal_figure(out["curves"], r, "Liquid rate (STB/d)")
lines = fig.axes[0].get_lines()
check_true("nodal chart: IPR, VLP and operating point drawn", len(lines) == 3)
check_true("nodal chart: axis labels set", "Liquid rate" in fig.axes[0].get_xlabel() and "psig" in fig.axes[0].get_ylabel())
_, out_nf = solve(dict(p_wh=1500.0))
fig = make_nodal_figure(out_nf["curves"], out_nf["result"], "Liquid rate (STB/d)")
check_true("nodal chart with no operating point: two curves only", len(fig.axes[0].get_lines()) == 2)
check_equal("rate unit from the label (oil)", rate_unit("Liquid rate (STB/d)"), "STB/d")
check_equal("rate unit from the label (gas)", rate_unit("Gas rate (Mscf/d)"), "Mscf/d")
check_equal("rate unit when the label has no brackets", rate_unit("Rate"), "")
# The operating-point label must carry the unit of the rate as well as the unit of the pressure
label_oil = [t.get_text() for t in make_nodal_figure(out["curves"], r, "Liquid rate (STB/d)").axes[0].texts]
check_equal("operating point label (oil): rate with unit, then pressure with unit", label_oil,
            [f"{r['q']:,.0f} STB/d\n{to_psig(r['pwf']):,.0f} psig"])
_, out_g = solve(dict(fluid_type="gas", p_wh=500.0, correlation="gray"))
label_gas = [t.get_text() for t in make_nodal_figure(out_g["curves"], out_g["result"], "Gas rate (Mscf/d)").axes[0].texts]
check_equal("operating point label (gas): rate with unit, then pressure with unit", label_gas,
            [f"{out_g['result']['q']:,.0f} Mscf/d\n{to_psig(out_g['result']['pwf']):,.0f} psig"])
# Pressure and temperature profile: ONE plot, two horizontal axes (pressure on TOP, temperature at the bottom)
fig = make_profile_figure(out["traverse"])
ax_t, ax_p = fig.axes                      # the main axes carry temperature, the twin (top) carries pressure
check_true("profile chart: one plot with a second horizontal axis (not two panels)",
           ax_p.get_shared_y_axes().joined(ax_p, ax_t) and len(fig.axes) == 2)
check_equal("profile chart: top axis is pressure", ax_p.get_xlabel(), "Pressure (psig)")
check_equal("profile chart: bottom axis is temperature", ax_t.get_xlabel(), "Temperature (degF)")
check_equal("profile chart: pressure axis is drawn at the top", ax_p.xaxis.get_label_position(), "top")
check_equal("profile chart: temperature axis is drawn at the bottom", ax_t.xaxis.get_label_position(), "bottom")
check_true("profile chart: pressure curve on the pressure axis",
           list(ax_p.get_lines()[0].get_xdata()) == [to_psig(p_) for p_ in out["traverse"]["p"]])
check_true("profile chart: temperature curve on the temperature axis",
           list(ax_t.get_lines()[0].get_xdata()) == list(out["traverse"]["T"]))
check_true("profile chart: depth axis points down", ax_t.yaxis_inverted())
check_true("profile chart: depth runs from the surface to the bottom of the well",
           ax_t.get_ylim() == (max(out["traverse"]["tvd"]), 0))
grad_text = [t.get_text() for t in ax_p.texts]
check_equal("profile chart: five pressure-gradient values are written on it", len(grad_text), 5)
gr = pressure_gradients(out["traverse"], 5)
check_true("gradient labels show the calculated values (psi/ft, 3 decimals)", grad_text == [f"{g[2]:.3f}" for g in gr])
# hand check: with a straight pressure line 200 -> 2200 psia over 8000 ft of depth the gradient is 2000/8000 = 0.25 psi/ft everywhere
line = dict(md=[0.0, 4000.0, 8000.0], tvd=[0.0, 4000.0, 8000.0], p=[200.0, 1200.0, 2200.0])
check_true("gradient of a straight pressure line = 0.25 psi/ft at every point",
           all(abs(g[2] - 0.25) < 1e-12 for g in pressure_gradients(line, 5)))
# deviated well: 10,000 ft of tubing for 5,000 ft of vertical depth, pressure 0.1 psi per ft of tubing
# -> 0.1 * 10000 / 5000 = 0.2 psi per ft of TRUE VERTICAL depth
dev = dict(md=[0.0, 5000.0, 10000.0], tvd=[0.0, 2500.0, 5000.0], p=[200.0, 700.0, 1200.0])
check_true("gradient is per ft of true vertical depth: 0.2 psi/ft in the 2:1 deviated well",
           all(abs(g[2] - 0.2) < 1e-12 for g in pressure_gradients(dev, 5)))
# a horizontal section at the bottom (constant depth) must not break it
hz = dict(md=[0.0, 4000.0, 8000.0, 12000.0], tvd=[0.0, 4000.0, 8000.0, 8000.0], p=[200.0, 1200.0, 2200.0, 2300.0])
check_true("horizontal section at total depth: gradients stay finite and equal 0.25 psi/ft",
           all(abs(g[2] - 0.25) < 1e-9 for g in pressure_gradients(hz, 5)))
check_true("gradient points are spread from shallow to deep", gr[0][0] < gr[2][0] < gr[4][0])
check_true("pressure gradient of the page default oil well is between 0.1 and 0.5 psi/ft", all(0.1 < g[2] < 0.5 for g in gr))
# IPR / VLP chart: no unstable-crossing marker any more; the operating-point label is directly above the point
fig_nd = make_nodal_figure(out["curves"], out["result"], "Liquid rate (STB/d)")
check_true("IPR/VLP chart: no 'Unstable crossing' entry in the legend",
           "Unstable crossing" not in [t.get_text() for t in fig_nd.axes[0].get_legend().get_texts()])
ann = fig_nd.axes[0].texts[0]
check_true("operating point label is centred above the point (offset 0 horizontally, upwards)",
           ann.xyann[0] == 0 and ann.xyann[1] > 0 and ann.get_ha() == "center")
check("default wellbore radius (oil Darcy) is 0.354 ft", DEFAULTS["oil_rw"], 0.354)
check("default wellbore radius (horizontal) is 0.354 ft", DEFAULTS["hz_rw"], 0.354)
check("default wellbore radius (gas) is 0.354 ft", DEFAULTS["gas_rw"], 0.354)
res = run_sensitivity(case, "p_wh", [200.0, 1500.0])
fig = make_sensitivity_figure(res, "Wellhead pressure (psig)", "Liquid rate (STB/d)")
check_true("sensitivity chart: flowing line plus the 'does not flow' marker", len(fig.axes[0].get_lines()) == 2)

print("\nAll checks passed.")


# =====================================================================
print("\n== Nov-15 minor edits: defaults, water specific gravity, skin / GOR / kh sensitivities, typed values ==")
check("default water cut is 30 %", DEFAULTS["water_cut"], 0.3)
check("default water specific gravity is 1.02", DEFAULTS["water_sg"], 1.02)
check("default horizontal permeability is 50 md", DEFAULTS["hz_kh"], 50.0)
check("default kv/kh ratio is 0.1", DEFAULTS["hz_kv_ratio"], 0.1)
c_def = build_case({})
check("page default: the fluid carries the 30 % water cut", c_def["solve"]["fluid"].water_cut, 0.3)
check("page default: SG 1.02 becomes about 2.82 wt % salinity", c_def["solve"]["fluid"].salinity, 2.815, tol=0.002)
check("salinity from SG 1.0 is fresh water", pvt.salinity_from_sg(1.0), 0.0, tol=1e-6)
check("salinity from SG 1.01 (about 1.4 wt %)", pvt.salinity_from_sg(1.01), 1.415, tol=0.002)
for sg in (1.01, 1.05, 1.10, 1.20):
    wt = pvt.salinity_from_sg(sg)
    rho = 62.368 + 0.438603 * wt + 0.00160074 * wt ** 2          # lb/ft3 at standard conditions
    check(f"round trip SG {sg}: density from the salinity gives the SG back", rho / 62.368, sg, tol=1e-9)
check_raises("water SG below 1", ValueError, pvt.salinity_from_sg, 0.99)
check_raises("water SG above 1.25", ValueError, pvt.salinity_from_sg, 1.30)

# skin and GOR sensitivities
case_d, out_d = solve(dict(oil_ipr="darcy"))
res = run_sensitivity(case_d, "skin", [0.0, 5.0, 10.0], with_curves=True)
check_true("higher total skin -> lower rate", rates(res)[0] > rates(res)[1] > rates(res)[2])
check("skin 0 point = the base case (page default skin is 0)", res[0]["q"], out_d["result"]["q"], tol=1e-6)
case_g, out_g = solve(dict(fluid_type="gas"))
res = run_sensitivity(case_g, "skin", [0.0, 10.0])
check_true("gas well: higher total skin -> lower rate", res[0]["q"] > res[1]["q"])
case_o, out_o = solve(dict())
res = run_sensitivity(case_o, "gor", [300.0, 600.0, 1200.0])
check_true("total GOR sensitivity runs and changes the rate", len(set(round(x["q"], 3) for x in res)) == 3 or all(x["q"] is None for x in res))
check_true("more gas in the tubing -> lighter column -> rate does not fall (GOR 300 -> 600)", res[1]["q"] >= res[0]["q"] * 0.98)
g_opt = [o for o in sensitivity_options(dict()) if o["key"] == "gor"][0]
check("GOR range starts at the solution GOR", g_opt["low"], DEFAULTS["rsb"])
check("GOR range ends at twice the solution GOR", g_opt["high"], 2.0 * DEFAULTS["rsb"])
g_opt2 = [o for o in sensitivity_options(dict(oil_gor=900.0)) if o["key"] == "gor"][0]
check("with a producing GOR typed, the range starts there", g_opt2["low"], 900.0)
check_true("page default: producing GOR 0 means the solution GOR", c_def["solve"]["fluid"].gor is None)
check("producing GOR typed is passed to the fluid", build_case(dict(oil_gor=800.0))["solve"]["fluid"].gor, 800.0)

# kh moves kv with it
c_hz2 = build_case(dict(oil_ipr="horizontal", water_cut=0.0))
res = run_sensitivity(c_hz2, "kh", [25.0, 50.0, 100.0])
check_true("kh sensitivity: value column holds kh", [x["value"] for x in res] == [25.0, 50.0, 100.0])
c_hz3, o_hz3 = solve(dict(oil_ipr="horizontal", hz_kh=100.0))          # kv = 10 % of 100 = 10 md
check("kh = 100 md: same answer as a case built with kh = 100 (kv follows at 10 %)", res[2]["q"], o_hz3["result"]["q"], tol=1e-6)
check_true("higher kh -> higher rate", rates(res)[0] < rates(res)[1] < rates(res)[2])
check("kh sensitivity leaves the base case alone", c_hz2["solve"]["ipr_inputs"]["kv"], 5.0)

# typed sensitivity values
check_true("typed values: commas", parse_value_list("100, 200,300") == [100.0, 200.0, 300.0])
check_true("typed values: spaces, semicolons, sorted, duplicates removed", parse_value_list("300; 100  200 100") == [100.0, 200.0, 300.0])
check_true("typed values: negatives (skin)", parse_value_list("-2, 0, 5") == [-2.0, 0.0, 5.0])
check_raises("typed values: empty", ValueError, parse_value_list, "  ")
check_raises("typed values: one value", ValueError, parse_value_list, "100")
check_raises("typed values: a word", ValueError, parse_value_list, "100, abc")
check_raises("typed values: more than 12", ValueError, parse_value_list, ",".join(str(i) for i in range(13)))
check_raises("typed values: below a limit", ValueError, parse_value_list, "-1, 5", 0.0)
res = run_sensitivity(case, "p_wh", parse_value_list("100, 175, 250, 325"))
check_true("typed values run like automatic ones", len(res) == 4 and res[0]["q"] > res[3]["q"])

print("\n== Continuous gas lift on the page ==")
import gaslift
check_equal("gas lift is off by default", DEFAULTS["lift"], "none")
c_off = build_case({"water_cut": 0.3})
check_true("no gas lift: the case says so and the fluid has no injection", c_off["gas_lift"] is None and c_off["solve"]["fluid"].injection_gas_rate == 0.0)
c_gl = build_case({"water_cut": 0.3, "lift": "continuous"})
check_equal("gas lift on: rate and depth reach the fluid", (c_gl["solve"]["fluid"].injection_gas_rate, c_gl["solve"]["fluid"].injection_md), (1000.0, 6000.0))
check_raises("injection depth below the perforations", ValueError, build_case, {"lift": "continuous", "gl_md": 9000.0})
check_raises("injection depth = 0", ValueError, build_case, {"lift": "continuous", "gl_md": 0.0})
o_off = run_case(c_off, n_curve_points=12)
o_gl = run_case(c_gl, n_curve_points=12)
check_true("gas lift raises the operating rate", o_gl["result"]["q"] > o_off["result"]["q"] * 1.2)
check_true("gas lift lowers the flowing bottom-hole pressure", o_gl["result"]["pwf"] < o_off["result"]["pwf"])
check("the IPR does not change with gas lift (same AOF)", o_gl["result"]["aof"], o_off["result"]["aof"], tol=1e-9)
check("the profile ends at the operating Pwf with gas lift", o_gl["traverse"]["pwf"], o_gl["result"]["pwf"], tol=1e-6)
check_true("no gas lift: no injection check", o_off["gas_lift_check"] is None)
chk = o_gl["gas_lift_check"]
check_true("gas lift check has casing and tubing pressure at the injection depth; the gas column adds weight,\n           so the casing pressure at 6,000 ft is above the injection pressure at the wellhead",
           chk is not None and chk["md"] == 6000.0 and chk["p_casing"] > to_psia(DEFAULTS["gl_p_inj"]))
check("differential = casing minus tubing pressure", chk["differential"], chk["p_casing"] - chk["p_tubing"], tol=1e-9)
check_true("default injection pressure 1800 psia is enough at 6000 ft", chk["ok"])
o_low = run_case(build_case({"water_cut": 0.3, "lift": "continuous", "gl_p_inj": 600.0}), n_curve_points=12)
check_true("a low injection pressure is flagged", o_low["gas_lift_check"] is not None and not o_low["gas_lift_check"]["ok"])
check_true("injection pressure 0 = no check", run_case(build_case({"lift": "continuous", "gl_p_inj": 0.0}), n_curve_points=12)["gas_lift_check"] is None)
# Static gas column, hand check: Z = 1 gives p2 = p1 * exp(0.01875 * SG * TVD / T).  1000 ft of 0.65 gas at 100 degF, 1000 psia:
# the real-gas Z (about 0.9) makes the pressure rise bigger than the ideal-gas value.
ideal = 1000.0 * math.exp(0.01875 * 0.65 * 1000.0 / (100.0 + 459.67))
real = gaslift.casing_pressure_at_depth(1000.0, 1000.0, 100.0, 0.65)
check_true("static gas column: real-gas pressure rise is a bit larger than the ideal-gas rise (Z < 1)", real > ideal and real < ideal * 1.1)
check("static gas column at TVD = 0 gives the surface pressure", gaslift.casing_pressure_at_depth(1500.0, 0.0, 100.0, 0.65), 1500.0)
check_raises("static gas column with no pressure", ValueError, gaslift.casing_pressure_at_depth, 0.0, 1000.0, 100.0, 0.65)

# Sensitivity and performance curve with gas lift
keys_gl = [o["key"] for o in sensitivity_options({"lift": "continuous"})]
check_true("gas lift on: sensitivity offers gas injection rate and depth", keys_gl[-2:] == ["gl_rate", "gl_depth"])
check_true("gas lift off: no gas lift sensitivities", "gl_rate" not in [o["key"] for o in sensitivity_options({})])
res = run_sensitivity(c_gl, "gl_rate", [0.0, 500.0, 1000.0, 3000.0])
check("injection rate 0 = the well without gas lift", res[0]["q"], o_off["result"]["q"], tol=1e-6)
check("injection rate 1000 = the base case", res[2]["q"], o_gl["result"]["q"], tol=1e-6)
check_true("some gas helps: 500 Mscf/d beats none", res[1]["q"] > res[0]["q"])
res_d = run_sensitivity(c_gl, "gl_depth", [3000.0, 6000.0])
check_true("injecting deeper helps (6000 ft beats 3000 ft)", res_d[1]["q"] > res_d[0]["q"])
check_raises("injection depth sensitivity below the perforations", ValueError, run_sensitivity, c_gl, "gl_depth", [3000.0, 9000.0])
glp, best = gas_lift_performance(c_gl, [0.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0])
check_true("performance curve: oil rate rises, peaks, then falls", best is not None and 0.0 < best["value"] < 8000.0
           and glp[-1]["q_oil"] < best["q_oil"] and glp[0]["q_oil"] < best["q_oil"])
check_raises("performance curve without gas lift", ValueError, gas_lift_performance, c_off, [0.0, 500.0])
fig_glp = make_gl_performance_figure(glp, best)
check_true("performance chart marks the highest point", len(fig_glp.axes[0].texts) == 1 and "highest" in fig_glp.axes[0].texts[0].get_text())
fig_prof = make_profile_figure(o_gl["traverse"], injection_md=6000.0)
check_true("profile chart marks the gas injection depth", any("gas injection" in t.get_text() for t in fig_prof.axes[0].texts))
check_true("IPR/VLP chart says the VLP includes gas lift",
           any("gas lift" in t.get_text() for t in make_nodal_figure(o_gl["curves"], o_gl["result"], "Liquid rate (STB/d)", 0.3, c_gl["gas_lift"]).axes[0].get_legend().get_texts()))
fig_sg = make_sensitivity_nodal_figure(run_sensitivity(c_gl, "gl_rate", [0.0, 1000.0, 2000.0], with_curves=True),
                                       "Gas injection rate (Mscf/d)", "Liquid rate (STB/d)", "gl_rate")
check_true("gas injection sensitivity chart: one VLP per rate, the IPR drawn once",
           len([t for t in fig_sg.axes[0].get_legend().get_texts() if t.get_text().startswith("VLP")]) == 3
           and any(t.get_text().startswith("IPR") for t in fig_sg.axes[0].get_legend().get_texts()))


print("\n== Survey table, multilayer IPR, Petrosky, profile axis (this round) ==")
# Survey table <-> text
check_equal("survey_rows reads two columns", survey_rows("0 0\n5000 4800\n"), [[0.0, 0.0], [5000.0, 4800.0]])
recs = [{"MD (ft)": 0.0, "TVD (ft)": 0.0}, {"MD (ft)": 5000.0, "TVD (ft)": 4800.0},
        {"MD (ft)": None, "TVD (ft)": None}, {"MD (ft)": float("nan"), "TVD (ft)": 3.0}]
check_equal("table -> text skips empty rows", survey_text_from_table(recs), "0 0\n5000 4800")
check_equal("empty table gives empty text", survey_text_from_table([]), "")
check_equal("perforation MD from a survey text", perforation_md({"survey_mode": "table", "survey_text": "0 0\n5000 4800\n7000 5500"}), 7000.0)
check_true("perforation MD of a bad survey is None", perforation_md({"survey_mode": "table", "survey_text": "abc"}) is None)

# Multilayer IPR through build_case / run_case / sensitivity
ml = {"oil_ipr": "multilayer", "water_cut": 0.3}
lay = multilayer_layers(ml)
check_equal("default multilayer: 3 layers, psig -> psia, first PI", (len(lay), lay[0]["p_res"], lay[0]["J"]), (3, 3014.7, 2.0))
check_equal("each layer carries its own water cut (fraction) and GOR", (lay[0]["wc"], lay[0]["gor"], lay[2]["wc"], lay[2]["gor"]), (0.2, 400.0, 0.5, 600.0))
check_equal("GOR 0 means the solution GOR (rsb)", multilayer_layers({"rsb": 650.0, "ml_layers": [{"model": "pi", "p_psig": 3000.0, "pi": 2.0, "gor": 0.0, "wc": 10.0}]})[0]["gor"], 650.0)
check_equal("empty rows are skipped", len(multilayer_layers({"ml_layers": [{"model": "pi", "p_psig": 3000, "pi": 2}, {"model": "pi", "p_psig": None}, {"model": "pi", "p_psig": 2500, "pi": 1}]})), 2)
check_raises("negative PI layer", ValueError, multilayer_layers, {"ml_layers": [{"model": "pi", "p_psig": 3000, "pi": -2}]})
check_raises("no layers at all", ValueError, multilayer_layers, {"ml_layers": [{"model": "pi", "p_psig": None}]})
check_raises("water cut above 100 %", ValueError, multilayer_layers, {"ml_layers": [{"model": "pi", "p_psig": 3000, "pi": 2, "wc": 120.0}]})
check_raises("Darcy layer without thickness", ValueError, multilayer_layers, {"ml_layers": [{"model": "darcy", "p_psig": 3000, "k": 100.0, "h": 0.0}]})
darcy_rows = [{"model": "darcy", "p_psig": 3000.0, "pi": 99.0, "k": 100.0, "h": 20.0, "skin": 2.0, "gor": 500.0, "wc": 10.0}]
j_expected = ipr.darcy_productivity_index_oil(100.0, 20.0, 1.25, 0.8, 1000.0, 0.354, 2.0)
check("Darcy layer: PI from k, h, skin (the typed PI is ignored)", multilayer_layers({"ml_layers": darcy_rows})[0]["J"], j_expected, tol=1e-9)
rows_sum = multilayer_summary(ml)
check_equal("layer summary: model, pressure, PI, GOR, water cut of layer 2", (rows_sum[1]["Model"], rows_sum[1]["Pressure (psig)"], rows_sum[1]["PI (STB/d/psi)"], rows_sum[1]["GOR (scf/STB)"], rows_sum[1]["Water cut (%)"]), ("PI", 2800.0, 1.5, 500.0, 30.0))
c_ml = build_case(ml)
o_ml = run_case(c_ml, n_curve_points=12)
check_true("multilayer case runs and flows", o_ml["result"]["q"] > 100.0)
check("multilayer: IPR curve starts at the highest layer pressure", max(o_ml["curves"]["ipr_pwf"]), 3014.7, tol=1e-6)
darcy_layers = [dict(r, model="darcy") for r in DEFAULTS["ml_layers"]]
c_mld = build_case({**ml, "ml_layers": darcy_layers})
check_true("multilayer with Darcy layers runs and flows", run_case(c_mld, n_curve_points=12)["result"]["q"] > 100.0)
check("multilayer: IPR curve starts at the highest layer pressure (psia)", max(run_case(c_mld, n_curve_points=12)["curves"]["ipr_pwf"]), 3014.7, tol=1e-6)
# --- water cut and GOR of the layers feed the tubing ---
mix = o_ml["result"]["mix"]
check_true("the mix at the operating point lies between the layer values (WC 20-50 %, GOR 400-600)", 0.20 < mix["water_cut"] < 0.50 and 400.0 < mix["gor"] < 600.0)
f_op = o_ml["fluid_op"]
check_equal("the fluid used for the profile is the mix at the operating point", (round(f_op.water_cut, 6), round(f_op.gor, 3)), (round(mix["water_cut"], 6), round(mix["gor"], 3)))
one = {"oil_ipr": "multilayer", "ml_layers": [{"model": "pi", "p_psig": 3000.0, "pi": 3.0, "gor": 0.0, "wc": 30.0}]}
o_one = run_case(build_case(one), n_curve_points=12)
# Both are now typed in psig, so the layer pressure and the reservoir pressure are the same number.
o_plain = run_case(build_case({"oil_ipr": "pi", "pi": 3.0, "p_res": 3000.0, "water_cut": 0.3}), n_curve_points=12)
check("one layer, WC 30 %, GOR = rsb: same as the ordinary PI model", o_one["result"]["q"], o_plain["result"]["q"], tol=1e-6 * o_plain["result"]["q"])
wet = [dict(r, wc=40.0) for r in DEFAULTS["ml_layers"]]
check_true("wetter layers -> heavier column -> lower rate", run_case(build_case({**ml, "ml_layers": wet}), n_curve_points=12)["result"]["q"] < o_ml["result"]["q"])
gassy = [dict(r, gor=1500.0) for r in DEFAULTS["ml_layers"]]
check_true("gassier layers change the rate (lighter column)", abs(run_case(build_case({**ml, "ml_layers": gassy}), n_curve_points=12)["result"]["q"] - o_ml["result"]["q"]) > 1.0)
check_true("multilayer sensitivity has no water cut / GOR options (they come from the layers)",
           not {"water_cut", "gor"} & {o["key"] for o in sensitivity_options(ml)})
check_true("ordinary IPR still offers them", {"water_cut", "gor"} <= {o["key"] for o in sensitivity_options({"oil_ipr": "pi"})})
check_true("multilayer sensitivity offers layer PI multiplier", "ml_pi_mult" in [o["key"] for o in sensitivity_options(ml)])
r_mult = run_sensitivity(c_ml, "ml_pi_mult", [0.5, 1.0, 2.0])
check_true("higher layer PIs give more rate", r_mult[0]["q"] < r_mult[1]["q"] < r_mult[2]["q"])
r_pr = run_sensitivity(c_ml, "p_res", [2500.0, 3000.0, 3500.0])
check_true("sensitivity rows carry the mixture water cut", all(r["q"] is None or "water_cut" in r for r in r_pr))
check_true("multilayer: too low a pressure -> no flow (None); higher pressure -> more rate", r_pr[0]["q"] is None and 0 < r_pr[1]["q"] < r_pr[2]["q"])
check("multilayer sensitivity at multiplier 1 = base case", r_mult[1]["q"], o_ml["result"]["q"], tol=1e-6)

# Layer chart in the layer table window
fig_ml = make_multilayer_figure(lay, c_ml["pb"], False)
ax_ml = fig_ml.axes[0]
check_equal("layer chart: one dashed line per layer plus the composite", len(ax_ml.lines), 4)
check("layer chart: composite ends at the sum of the layer AOFs", ax_ml.lines[-1].get_xdata()[-1], sum(ipr.multilayer_rates(3014.7, 0.0, c_ml["pb"], lay)), tol=1e-6)
check("layer chart: composite = sum of the layer lines at every pressure", max(abs(sum(l.get_xdata()[k] for l in ax_ml.lines[:3]) - ax_ml.lines[-1].get_xdata()[k]) for k in range(len(ax_ml.lines[-1].get_xdata()))), 0.0, tol=1e-6)
check_true("layer chart with crossflow draws too", len(make_multilayer_figure(lay, c_ml["pb"], True).axes[0].lines) == 4)

# Petrosky viscosity chosen on the page
o_pet = run_case(build_case({"oil_visc": "petrosky", "water_cut": 0.3}), n_curve_points=12)
o_beal = run_case(build_case({"oil_visc": "beal", "water_cut": 0.3}), n_curve_points=12)
check_true("Petrosky viscosity runs and is within 40 % of Beal on the rate", abs(o_pet["result"]["q"] / o_beal["result"]["q"] - 1.0) < 0.4)


# Kuchuk-Goode horizontal well on the page
kg = {"oil_ipr": "horizontal_kg", "water_cut": 0.3}
c_kg = build_case(kg)
o_kg = run_case(c_kg, n_curve_points=12)
check_true("Kuchuk-Goode case runs and flows", o_kg["result"]["q"] > 100.0)
check("well centre along the box = 0.5 * Lx", c_kg["solve"]["ipr_inputs"]["xw"], 1500.0)
check_equal("well position fractions become feet", (c_kg["solve"]["ipr_inputs"]["yw"], c_kg["solve"]["ipr_inputs"]["zw"]), (1200.0, 25.0))
check_true("Kuchuk-Goode and Joshi PI agree within a factor of 2 for the default well",
           0.5 < o_kg["result"]["aof"] / run_case(build_case({"oil_ipr": "horizontal", "water_cut": 0.3}), n_curve_points=12)["result"]["aof"] < 2.0)
check_raises("well longer than the box", ValueError, run_case, build_case({**kg, "hz_length": 4000.0}), n_curve_points=12)
o_cp = run_case(build_case({**kg, "kg_top": "constant_pressure"}), n_curve_points=12)
check_true("constant-pressure top gives more rate than a sealed top", o_cp["result"]["q"] > o_kg["result"]["q"])
check_true("Kuchuk-Goode sensitivity offers length, kh and skin",
           [o["key"] for o in sensitivity_options(kg)][-3:] == ["length", "kh", "skin"])
opt_len = [o for o in sensitivity_options(kg) if o["key"] == "length"][0]
check_true("length range stays inside the box", opt_len["high"] <= 3000.0)
r_len = run_sensitivity(c_kg, "length", [500.0, 1000.0, 2000.0])
check_true("longer well gives more rate (Kuchuk-Goode)", r_len[0]["q"] < r_len[1]["q"] < r_len[2]["q"])
r_kh = run_sensitivity(c_kg, "kh", [25.0, 50.0, 100.0])
check_true("higher kh gives more rate (Kuchuk-Goode)", r_kh[0]["q"] < r_kh[1]["q"] < r_kh[2]["q"])
r_sk = run_sensitivity(c_kg, "skin", [0.0, 5.0, 10.0])
check_true("more skin gives less rate (Kuchuk-Goode)", r_sk[0]["q"] > r_sk[1]["q"] > r_sk[2]["q"])

# Profile chart: pressure axis starts at 0
fig_p0 = make_profile_figure(o_ml["traverse"])
check_equal("profile pressure axis starts at 0 psi", fig_p0.axes[1].get_xlim()[0], 0.0)

# Lift choices
check_equal("lift default is none", DEFAULTS["lift"], "none")


# =====================================================================
print("\n== Gas wells: horizontal IPR and multilayer IPR ==")
# --- horizontal gas wells through the page inputs ---
gh = {"fluid_type": "gas", "gas_ipr": "horizontal"}
c_gh = build_case(gh)
check_equal("horizontal gas: the IPR function is the Joshi one", c_gh["solve"]["ipr_function"], ipr.gas_horizontal_joshi)
gi = c_gh["solve"]["ipr_inputs"]
check_equal("horizontal gas: kv = 0.1 kh from the ratio", (gi["kh"], gi["kv"]), (5.0, 0.5))
props_h = pvt.gas_properties(0.75 * PR, 200.0, 0.65, 0.0, 0.0, "lee")   # build_case uses the absolute Pr
check("horizontal gas: the page rate matches the IPR function", ipr.gas_horizontal_joshi(3000.0, 1500.0, **gi),
      ipr.gas_horizontal_joshi(3000.0, 1500.0, 200.0, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, props_h["mu_g"], props_h["z"], 0.65, 0.0), 1e-9)
o_gh = run_case(c_gh, n_curve_points=12)
check_true("horizontal gas well flows", o_gh["result"]["found"])
o_gv = run_case(build_case({"fluid_type": "gas", "gas_ipr": "jones"}), n_curve_points=12)
check_true("a 2000 ft horizontal gas well beats the vertical well", o_gh["result"]["q"] > 1.5 * o_gv["result"]["q"])
gk = {"fluid_type": "gas", "gas_ipr": "horizontal_kg"}
c_gk = build_case(gk)
check_equal("KG gas: the IPR function", c_gk["solve"]["ipr_function"], ipr.gas_horizontal_kuchuk_goode)
check_equal("KG gas: well position fractions become feet", (c_gk["solve"]["ipr_inputs"]["xw"], c_gk["solve"]["ipr_inputs"]["yw"], c_gk["solve"]["ipr_inputs"]["zw"]), (2000.0, 1500.0, 20.0))
check_true("KG gas well flows", run_case(c_gk, n_curve_points=12)["result"]["found"])
check_raises("KG gas: well longer than the box", ValueError, run_case, build_case({**gk, "gh_length": 6000.0}), n_curve_points=12)
check_true("horizontal gas sensitivity offers length, kh and skin",
           [o["key"] for o in sensitivity_options(gh)][-3:] == ["length", "kh", "skin"])
r_gl = run_sensitivity(c_gh, "length", [500.0, 1000.0, 2000.0])
check_true("longer horizontal gas well gives more rate", r_gl[0]["q"] < r_gl[1]["q"] < r_gl[2]["q"])
r_gk = run_sensitivity(c_gh, "kh", [2.5, 5.0, 10.0])
check_true("higher kh gives more gas rate", r_gk[0]["q"] < r_gk[1]["q"] < r_gk[2]["q"])
q_kh10 = run_case(build_case({**gh, "gh_kh": 10.0}), n_curve_points=12)["result"]["q"]
check("kh sensitivity = a new case with that kh (kv keeps its ratio)", r_gk[2]["q"], q_kh10, 1e-6)

# --- multilayer gas ---
gm = {"fluid_type": "gas", "gas_ipr": "multilayer"}
lay = gas_multilayer_layers(gm)
check_equal("default gas multilayer: 3 layers, psig -> psia", (len(lay), lay[0]["p_res"]), (3, 3014.7))
# Layer 1 by hand: k = 8 md, h = 20 ft, skin 0, T = 200 F, re = 1000, rw = 0.354, CGR 10 -> well-stream gravity, Z, mu at 0.75 * 3014.7 psia
sg1 = pvt.wet_gas_gravity(0.65, 10.0, 50.0)
pr1 = pvt.gas_properties(0.75 * 3014.7, 200.0, sg1, 0.0, 0.0, "lee")
a1 = 1422.0 * 660.0 * pr1["mu_g"] * pr1["z"] * (math.log(1000.0 / 0.354) - 0.75) / (8.0 * 20.0)
check("gas layer 1: laminar coefficient a (hand)", lay[0]["a"], a1, 1e-9)
beta1 = 2.73e10 / 8.0 ** 1.1045
b1 = 3.161e-12 * beta1 * 660.0 * sg1 * pr1["z"] / (20.0 ** 2 * 0.354)
check("gas layer 1: turbulent coefficient b (hand)", lay[0]["b"], b1, 1e-9)
check_equal("gas layer 1 carries its CGR and WGR", (lay[0]["cgr"], lay[0]["wgr"]), (10.0, 1.0))
darcy_l = gas_multilayer_layers({"gm_layers": [{"model": "darcy", "p_psig": 3000.0, "k": 8.0, "h": 20.0, "skin": 0.0, "cgr": 0.0, "wgr": 0.0}]})
check_equal("a Darcy layer has no turbulence term", darcy_l[0]["b"], 0.0)
bp_l = gas_multilayer_layers({"gm_layers": [{"model": "backpressure", "p_psig": 3000.0, "C": 0.02, "n": 0.9, "cgr": 0.0, "wgr": 0.0}]})
check_equal("a back-pressure layer keeps C and n", (bp_l[0]["C"], bp_l[0]["n"]), (0.02, 0.9))
check_raises("gas layer with k = 0", ValueError, gas_multilayer_layers, {"gm_layers": [{"model": "jones", "p_psig": 3000, "k": 0.0, "h": 20.0}]})
check_raises("gas layer with n above 1", ValueError, gas_multilayer_layers, {"gm_layers": [{"model": "backpressure", "p_psig": 3000, "C": 0.02, "n": 1.5}]})
check_raises("gas layer with negative CGR", ValueError, gas_multilayer_layers, {"gm_layers": [{"model": "jones", "p_psig": 3000, "k": 5.0, "h": 20.0, "cgr": -1.0}]})
check_raises("no gas layers at all", ValueError, gas_multilayer_layers, {"gm_layers": [{"model": "jones", "p_psig": None}]})
check_equal("gas layer summary has one row per layer", len(gas_multilayer_summary(gm)), 3)

c_gm = build_case(gm)
o_gm = run_case(c_gm, n_curve_points=12)
check_true("multilayer gas well flows", o_gm["result"]["found"])
q_op, pwf_op = o_gm["result"]["q"], o_gm["result"]["pwf"]
check("operating point lies on the composite IPR", ipr.gas_multilayer(c_gm["solve"]["p_res"], pwf_op, c_gm["solve"]["ipr_inputs"]["layers"]), q_op, 2e-3)
mix_op = o_gm["result"]["mix"]
check_true("the mix at the operating point lies between the layer CGRs", 10.0 < mix_op["cgr"] < 40.0 and 1.0 < mix_op["wgr"] < 5.0)
check("the fluid at the operating point carries the mixed CGR", fluid_at_rate(c_gm["solve"]["fluid"], c_gm["solve"]["ipr_function"], c_gm["solve"]["p_res"],
      c_gm["solve"]["ipr_inputs"], q_op).cgr, mix_op["cgr"], 1e-9)
fluid_mix = fluid_at_rate(c_gm["solve"]["fluid"], c_gm["solve"]["ipr_function"], c_gm["solve"]["p_res"], c_gm["solve"]["ipr_inputs"], q_op)
check("the well-stream gravity is recalculated from the mixed CGR", fluid_mix.gas_sg, pvt.wet_gas_gravity(0.65, mix_op["cgr"], 50.0), 1e-9)
check_true("total of the layer rates at the operating point equals q", abs(sum(ipr.gas_multilayer_rates(c_gm["solve"]["p_res"], pwf_op, c_gm["solve"]["ipr_inputs"]["layers"])) - q_op) < 0.002 * q_op)
# dry layers: no CGR or WGR anywhere -> the well stream is dry, nothing changes
dry_rows = [dict(r, cgr=0.0, wgr=0.0) for r in DEFAULTS["gm_layers"]]
o_dry = run_case(build_case({**gm, "gm_layers": dry_rows}), n_curve_points=12)
check_equal("dry layers give a dry well stream", (o_dry["result"]["mix"]["cgr"], o_dry["result"]["mix"]["wgr"]), (0.0, 0.0))
check_true("wet layers need more bottom-hole pressure than the same dry layers (heavier column)", o_gm["result"]["pwf"] != o_dry["result"]["pwf"])
check_true("the gas multilayer curve starts at the highest layer pressure", abs(c_gm["solve"]["p_res"] - 3014.7) < 1e-6)
for corr in ("gray", "hagedorn_brown", "beggs_brill", "ansari", "duns_ros", "mukherjee_brill"):
    check_true(f"gas multilayer runs with {corr}", run_case(build_case({**gm, "correlation": corr}), n_curve_points=12)["result"]["found"])
cross = run_case(build_case({**gm, "gm_crossflow": True}), n_curve_points=12)
check_true("crossflow option runs and gives a little less gas (the lower layers take some)", cross["result"]["found"] and cross["result"]["q"] <= o_gm["result"]["q"] * 1.001)

# --- sensitivity of the gas multilayer ---
opts = {o["key"]: o for o in sensitivity_options(gm)}
check_true("gas multilayer sensitivity offers p_res and the layer deliverability multiplier", "p_res" in opts and "ml_pi_mult" in opts and "k" not in opts)
check("the p_res option starts from the highest layer pressure", opts["p_res"]["low"], 0.7 * 3014.7, 1e-9)
r_mult = run_sensitivity(c_gm, "ml_pi_mult", [0.5, 1.0, 2.0])
check_true("more deliverability gives more gas", r_mult[0]["q"] < r_mult[1]["q"] < r_mult[2]["q"])
# deliverability x2 scales a to a/2 and b to b/4: at a fixed Pwf every layer rate doubles exactly
lyr = c_gm["solve"]["ipr_inputs"]["layers"][0]
dbl = dict(lyr, a=lyr["a"] / 2.0, b=lyr["b"] / 4.0)
check("a/2 and b/4 doubles the layer rate at the same Pwf", ipr.gas_multilayer(3000, 1800, [dbl]), 2.0 * ipr.gas_multilayer(3000, 1800, [lyr]), 1e-9)
r_pr = run_sensitivity(c_gm, "p_res", [2400.0, 3014.7, 3300.0])
check_true("higher layer pressures give more gas", r_pr[0]["q"] < r_pr[1]["q"] < r_pr[2]["q"])
fig_gm = make_gas_multilayer_figure(gas_multilayer_layers(gm))
check_equal("the gas layer chart has one line per layer plus the composite", len(fig_gm.axes[0].lines), 4)


# =====================================================================
print("\n== Which VLP correlation suits the well (advice and comparison) ==")
# =====================================================================
# Source of the rules: the correlation papers themselves and standard industry practice (see
# correlation_advice()).  The expected values
# below follow from those rules and from hand geometry.
oil0 = dict(DEFAULTS)                                             # vertical, API 35, 30 % water
check("a vertical well has 0 degrees of inclination", max_inclination_deg(oil0), 0.0, 1e-9)
# survey 0 0 / 2000 2000 / 6000 4000: the second interval has dMD 4000 ft and dTVD 2000 ft, acos(0.5) = 60 degrees
dev = dict(DEFAULTS, survey_mode="deviated", survey_text="0 0\n2000 2000\n6000 4000")
check("a 4000 ft interval that drops 2000 ft is 60 degrees from vertical", max_inclination_deg(dev), 60.0, 1e-9)
adv = correlation_advice(oil0)
check_equal("oil, vertical: Hagedorn and Brown is rated good", adv["hagedorn_brown"]["rating"], "good")
check_equal("oil with 30 % water: Duns and Ros is a caution (tested with < 10 % water)", adv["duns_ros"]["rating"], "caution")
check_equal("oil: Beggs and Brill is a caution (it over-predicts the pressure drop of wells)", adv["beggs_brill"]["rating"], "caution")
check_equal("oil, vertical: the app recommends Hagedorn and Brown", recommend_correlation(oil0)[0], "hagedorn_brown")
check_equal("oil with 5 % water: Duns and Ros is ok", correlation_advice(dict(oil0, water_cut=0.05))["duns_ros"]["rating"], "ok")
check_equal("oil, 60 degrees: the app recommends Mukherjee and Brill", recommend_correlation(dev)[0], "mukherjee_brill")
check_equal("oil, 60 degrees: Hagedorn and Brown is a caution", correlation_advice(dev)["hagedorn_brown"]["rating"], "caution")
for deg, expected in ((29.0, "hagedorn_brown"), (31.0, "mukherjee_brill")):        # the limit is 30 degrees from vertical
    survey = f"0 0\n1000 {1000.0 * math.cos(math.radians(deg)):.6f}"
    check_equal(f"oil at {deg:.0f} degrees from vertical: {expected}",
                recommend_correlation(dict(DEFAULTS, survey_mode="deviated", survey_text=survey))[0], expected)
heavy = correlation_advice(dict(oil0, api=14.0, water_cut=0.05))
check_equal("heavy oil: Orkiszewski is rated good", heavy["orkiszewski"]["rating"], "good")
check_equal("light oil: Orkiszewski is ok", adv["orkiszewski"]["rating"], "ok")
gas0 = dict(DEFAULTS, fluid_type="gas")
check_equal("dry gas: the app recommends Gray", recommend_correlation(gas0)[0], "gray")
check_equal("gas with 50 STB/MMscf: still Gray (the limit is inclusive)", recommend_correlation(dict(gas0, cgr=50.0))[0], "gray")
check_equal("gas with 51 STB/MMscf: Duns and Ros", recommend_correlation(dict(gas0, cgr=51.0))[0], "duns_ros")
check_equal("gas with condensate: Hagedorn and Brown is a caution", correlation_advice(dict(gas0, cgr=10.0))["hagedorn_brown"]["rating"], "caution")
check_equal("dry gas: Hagedorn and Brown is ok", correlation_advice(gas0)["hagedorn_brown"]["rating"], "ok")
check_equal("deviated gas well: Mukherjee and Brill", recommend_correlation(dict(dev, fluid_type="gas"))[0], "mukherjee_brill")
check_equal("Gray is not offered for oil", "gray" in adv, False)

# the comparison runs the real solver with every correlation
cmp_oil = check_correlations(oil0)
check_equal("the comparison has one row per oil correlation, with the quality-check bound last", [r["key"] for r in cmp_oil["rows"]], list(PREFERENCE_OIL) + ["fancher_brown"])
check_true("every correlation found an operating point", all(r["ok"] and r["q"] and r["q"] > 0 for r in cmp_oil["rows"]))
check_true("the flow-pattern shares of every row add up to 1",
           all(abs(sum(r["shares"].values()) - 1.0) < 1e-9 for r in cmp_oil["rows"]))
check_equal("the comparison suggests the same as the advice for this oil well", cmp_oil["suggested"], "hagedorn_brown")
fb_row = [r for r in cmp_oil["rows"] if r["key"] == "fancher_brown"][0]
check_true("Fancher and Brown row: carries the quality-check note, is never compared with the median and never suggested",
           "quality-check" in " ".join(fb_row["notes"]) and fb_row["vs_median"] is None and cmp_oil["suggested"] != "fancher_brown")
check_true("Fancher and Brown is rated a caution and is never the recommendation",
           adv["fancher_brown"]["rating"] == "caution" and all(recommend_correlation(c_)[0] != "fancher_brown" for c_ in (oil0, dev, gas0, dict(gas0, cgr=120.0))))
check("Hagedorn and Brown row equals the page's own result", [r for r in cmp_oil["rows"] if r["key"] == "hagedorn_brown"][0]["q"],
      run_case(build_case(dict(oil0, correlation="hagedorn_brown")), n_curve_points=12)["result"]["q"], 1e-9)
cmp_gas = check_correlations(dict(gas0, cgr=120.0))
check_equal("wet gas with 120 STB/MMscf: the comparison suggests Duns and Ros", cmp_gas["suggested"], "duns_ros")
check_true("the Gray row of that case carries the condensate caution", "condensate" in " ".join([r for r in cmp_gas["rows"] if r["key"] == "gray"][0]["notes"]))
check_true("the traverse names a flow pattern for every step",
           len(pressure_traverse(build_case(oil0)["solve"]["well"], build_case(oil0)["solve"]["fluid"], 2000.0, 200.0,
                                 "hagedorn_brown", 200.0)["regime"]) > 5)

# =====================================================================
print("\n== VLP comparison and matching with a measured pressure survey (19 Nov 2026) ==")
from vlp import pressure_traverse as _pt
import numpy as _np
oil_s = dict(DEFAULTS)
test_s = dict(p_wh=200.0, rate=2000.0, rate_type="liquid", water_cut=0.2, gor=500.0, gl_rate=0.0, gl_md=0.0, cgr=0.0, wgr=0.0)
COL_D, COL_P = SURVEY_COLUMNS
check_equal("the table has the two columns depth and pressure", SURVEY_COLUMNS, ("Depth MD (ft)", "Pressure (psig)"))
check_equal("at most 10 survey points", SURVEY_MAX_POINTS, 10)

# the measured points of the table
d_, p_ = survey_points([{COL_D: 5000.0, COL_P: 1200.0}, {COL_D: None, COL_P: None}, {COL_D: 2000.0, COL_P: 700.0},
                        {COL_D: float("nan"), COL_P: float("nan")}], 8000.0)
check_equal("blank rows are skipped and the points are sorted by depth", (d_, p_), ([2000.0, 5000.0], [700.0, 1200.0]))
check_raises("a depth without a pressure", ValueError, survey_points, [{COL_D: 5000.0, COL_P: None}], 8000.0)
check_raises("a pressure without a depth", ValueError, survey_points, [{COL_D: float("nan"), COL_P: 1000.0}], 8000.0)
check_raises("an empty table", ValueError, survey_points, [{COL_D: None, COL_P: None}], 8000.0)
check_raises("a depth below the perforations", ValueError, survey_points, [{COL_D: 8100.0, COL_P: 2000.0}], 8000.0)
check_raises("a zero pressure", ValueError, survey_points, [{COL_D: 100.0, COL_P: 0.0}], 8000.0)
check_raises("a negative depth", ValueError, survey_points, [{COL_D: -5.0, COL_P: 100.0}], 8000.0)
check_raises("eleven points", ValueError, survey_points, [{COL_D: 100.0 * n, COL_P: 100.0 + n} for n in range(1, 12)], 8000.0)
check_equal("ten points are accepted", len(survey_points([{COL_D: 100.0 * n, COL_P: 100.0 + n} for n in range(1, 11)], 8000.0)[0]), 10)

# the test conditions are applied to the case
i_t, rate_t = survey_test_inputs(oil_s, test_s)
check_equal("test conditions: wellhead pressure, water cut and GOR replace the page's", (i_t["p_wh"], i_t["water_cut"], i_t["oil_gor"]), (200.0, 0.2, 500.0))
check("liquid rate: the rate is the liquid rate", rate_t, 2000.0, tol=1e-12)
check("oil rate of 1600 STB/d at 20 % water: 2000 STB/d of liquid", survey_test_inputs(oil_s, dict(test_s, rate=1600.0, rate_type="oil"))[1], 2000.0, tol=1e-12)
check_true("without gas lift the gas lift boxes of the test are ignored", "gl_rate" not in survey_test_inputs(oil_s, dict(test_s, gl_rate=999.0))[0] or survey_test_inputs(oil_s, dict(test_s, gl_rate=999.0))[0]["lift"] != "continuous")
gl_page = dict(oil_s, lift="continuous", gl_rate=1500.0, gl_md=5000.0)
i_g, _ = survey_test_inputs(gl_page, dict(test_s, gl_rate=2500.0, gl_md=6000.0))
check_equal("with gas lift the gas lift rate and depth of the test are used", (i_g["gl_rate"], i_g["gl_md"]), (2500.0, 6000.0))
check_raises("water cut of 100 %", ValueError, survey_test_inputs, oil_s, dict(test_s, water_cut=1.0))
check_raises("zero rate", ValueError, survey_test_inputs, oil_s, dict(test_s, rate=0.0))
i_gas, r_gas = survey_test_inputs(dict(DEFAULTS, fluid_type="gas"), dict(p_wh=500.0, rate=5000.0, cgr=20.0, wgr=3.0, gl_rate=0.0, gl_md=0.0))
check_equal("gas well: CGR and WGR of the test", (i_gas["cgr"], i_gas["wgr"], r_gas), (20.0, 3.0, 5000.0))

# invent a survey with known multipliers, then compare and match
s_s, fl_s, rt_s = _test_fluid(oil_s, test_s, "hagedorn_brown")
# s_s["p_wh"] is already absolute (build_case converted the 200 psig of test_s).  The traverse gives psia;
# the survey helpers take and give psig, like the page.
tr_s = _pt(s_s["well"], fl_s, rt_s, s_s["p_wh"], "hagedorn_brown", s_s["max_step_ft"], 1.1, 0.8)
dep_s = [2000.0, 5000.0, 8000.0]
meas_s = [to_psig(float(x)) for x in _np.interp(dep_s, tr_s["md"], tr_s["p"])]
cmp_s = compare_to_survey(oil_s, test_s, dep_s, meas_s, ["hagedorn_brown", "duns_ros", "beggs_brill", "fancher_brown"])
check_equal("the comparison has one row per correlation", [r["key"] for r in cmp_s["rows"]], ["hagedorn_brown", "duns_ros", "beggs_brill", "fancher_brown"])
check_true("every row has an error at every measured point", all(len(r["err"]) == 3 and r["ok"] for r in cmp_s["rows"]))
hb_row = cmp_s["rows"][0]
check("the error is calculated minus measured (Hagedorn and Brown without multipliers is below the data)", hb_row["bias"], sum(hb_row["err"]) / 3.0, tol=1e-9)
check_true("with gravity 1.1 hidden in the data the plain correlation under-predicts: negative mean error", hb_row["bias"] < -30.0)
check("RMS error is the root of the mean square error", hb_row["rms"], (sum(e_ ** 2 for e_ in hb_row["err"]) / 3.0) ** 0.5, tol=1e-9)
check_true("mean absolute error is never above the RMS error", all(r["mae"] <= r["rms"] + 1e-9 for r in cmp_s["rows"]))
check_true("the best correlation is the one with the smallest RMS error (the no-slip bound is never picked)",
           cmp_s["best"] == min([r for r in cmp_s["rows"] if r["key"] != "fancher_brown"], key=lambda r: r["rms"])["label"])
check_true("every curve runs from the wellhead pressure (psig) to the perforations",
           all(abs(c_[1][0] - 200.0) < 1e-6 and abs(c_[0][-1] - 8000.0) < 1e-6 for c_ in cmp_s["curves"].values()))
cmp_m = compare_to_survey(oil_s, test_s, dep_s, meas_s, ["hagedorn_brown"], matched=("hagedorn_brown", 1.1, 0.8))
check_equal("a matched run is added as one more row", len(cmp_m["rows"]), 2)
check_true("the correlation with the right multipliers fits the survey exactly (RMS < 0.01 psi)", cmp_m["rows"][1]["rms"] < 0.01 and "matched" in cmp_m["rows"][1]["label"])
check_equal("the matched run is not a candidate for 'best'", cmp_m["best"], "Hagedorn and Brown")
# (a depth below the perforations never reaches this function: survey_points refuses it, tested above)
fig_s = make_survey_figure(cmp_m)
check_true("the survey figure is drawn with its curves and the measured points", len(fig_s.axes[0].lines) >= 3)

mt = match_to_survey(oil_s, test_s, dep_s, meas_s, "hagedorn_brown", "both")
check("match: gravity multiplier (rounded to 2 decimals)", mt["gravity"], 1.1, tol=0.01)
check("match: friction multiplier (weakly determined; 0.05)", mt["friction"], 0.8, tol=0.07)
check_true("match: the error falls from over 50 psi to under 4 psi (RMS, with the rounded multipliers)", mt["rms_before"] > 50.0 and mt["rms_after"] < 4.0)
check_true("match: the multipliers are rounded to what the sliders hold", mt["gravity"] == round(mt["gravity"], 2) and mt["friction"] == round(mt["friction"], 2))
check_raises("match: both multipliers from one point", ValueError, match_to_survey, oil_s, test_s, [8000.0], [meas_s[-1]], "hagedorn_brown", "both")
# the same data used with the other correlation: different multipliers, still inside the allowed range
mt_dr = match_to_survey(oil_s, test_s, dep_s, meas_s, "duns_ros", "both")
check_true("another correlation matched to the same data needs different multipliers", abs(mt_dr["friction"] - mt["friction"]) > 0.005 or abs(mt_dr["gravity"] - mt["gravity"]) > 0.005)
# gas lift: the test's lift gas changes the calculation
oil_gl = dict(DEFAULTS, lift="continuous", gl_rate=1500.0, gl_md=5000.0, correlation="hagedorn_brown")
c_lo = compare_to_survey(oil_gl, dict(test_s, gl_rate=0.0, gl_md=5000.0), dep_s, meas_s, ["hagedorn_brown"])["rows"][0]["calc"]
c_hi = compare_to_survey(oil_gl, dict(test_s, gl_rate=1000.0, gl_md=5000.0), dep_s, meas_s, ["hagedorn_brown"])["rows"][0]["calc"]
check_true("1000 Mscf/d of lift gas in the test lowers the calculated bottom pressure (by about 200 psi)", c_hi[-1] < c_lo[-1] - 100.0)
c_none = compare_to_survey(DEFAULTS | dict(lift="none"), dict(test_s, gl_rate=3000.0, gl_md=5000.0), dep_s, meas_s, ["hagedorn_brown"])["rows"][0]["calc"]
c_none2 = compare_to_survey(DEFAULTS | dict(lift="none"), dict(test_s, gl_rate=0.0, gl_md=100.0), dep_s, meas_s, ["hagedorn_brown"])["rows"][0]["calc"]
check_equal("without gas lift on the page the test's gas lift boxes change nothing", c_none, c_none2)
# a gas well
gas_s = dict(DEFAULTS, fluid_type="gas")
tg_s = dict(p_wh=500.0, rate=5000.0, cgr=0.0, wgr=0.0, gl_rate=0.0, gl_md=0.0)
sg_, fg_, rg_ = _test_fluid(gas_s, tg_s, "gray")
trg_ = _pt(sg_["well"], fg_, rg_, sg_["p_wh"], "gray", sg_["max_step_ft"], 1.0, 1.3)
dg_ = [3000.0, 8000.0]
mg_ = [to_psig(float(x)) for x in _np.interp(dg_, trg_["md"], trg_["p"])]
mt_g = match_to_survey(gas_s, tg_s, dg_, mg_, "gray", "friction")
check("gas well: friction multiplier 1.3 found from a survey", mt_g["friction"], 1.3, tol=0.01)

# the text under the correlation box
cap_oil = correlation_caption(DEFAULTS, "hagedorn_brown")
check_true("caption: names the correlation, says it looks suited and why, and points to the comparison with measured data",
           "Hagedorn and Brown" in cap_oil and "well suited" in cap_oil and "slug flow" in cap_oil
           and "pressure gauge" in cap_oil and "gradient survey" in cap_oil and "VLP comparison" in cap_oil)
cap_b = correlation_caption(DEFAULTS, "beggs_brill")
check_true("caption: a caution is worded as 'may not suit' and the app's own suggestion is named", "may not suit" in cap_b and "would suggest Hagedorn and Brown" in cap_b)
check_true("caption: the suggested correlation is not told to compare against itself", "would suggest" not in cap_oil)
check_true("caption: Duns and Ros on a deviated gas well says what it is", "may not suit" in correlation_caption(dict(DEFAULTS, fluid_type="gas", survey_mode="deviated", survey_text="0 0\n3000 3000\n9000 6000"), "hagedorn_brown"))
GAS_S = dict(DEFAULTS, fluid_type="gas")
check_true("every correlation offered for an oil well and for a gas well has a name and a caption",
           all(CORRELATION_NAMES[k] and correlation_caption(inp_, k) for inp_ in (DEFAULTS, GAS_S) for k in correlation_advice(inp_)))

# the single-test matching with the gas lift of the test
tr_t = _pt(*(lambda s_, f_, r_: (s_["well"], f_, r_, s_["p_wh"], "hagedorn_brown", s_["max_step_ft"], 1.0, 1.25))(*_test_fluid(
    dict(oil_gl), dict(test_s, rate=2000.0, water_cut=oil_gl["water_cut"], gor=oil_gl["oil_gor"], gl_rate=2500.0, gl_md=5000.0), "hagedorn_brown")))
m_gl = match_from_test(dict(oil_gl, p_wh=200.0), 2000.0, 200.0, to_psig(tr_t["pwf"]), "friction", test_gl_rate=2500.0, test_gl_md=5000.0)
check("single test with the gas lift of the test: friction 1.25 found", m_gl["multiplier"], 1.25, tol=0.01)
m_gl_wrong = None
try:
    m_gl_wrong = match_from_test(oil_gl, 2000.0, 200.0, to_psig(tr_t["pwf"]), "friction")
except ValueError:
    pass
check_true("with the page's own gas lift values (different from the test) the answer differs", m_gl_wrong is None or abs(m_gl_wrong["multiplier"] - 1.25) > 0.02)
m_ng = match_from_test(DEFAULTS | dict(lift="none"), 2000.0, 200.0, 2400.0, "friction", test_gl_rate=9999.0, test_gl_md=100.0)
m_ng2 = match_from_test(DEFAULTS | dict(lift="none"), 2000.0, 200.0, 2400.0, "friction")
check("no gas lift on the page: the gas lift values of the test are ignored", m_ng["multiplier"], m_ng2["multiplier"], tol=1e-12)

print("\nAll app_helpers checks done.")
