"""Tests of gaslift_valves.py against the worked examples of Takacs "Gas Lift Manual" and API RP 11V6."""
import math
import gaslift_valves as gv

failures = []


def check(name, got, want, tol):
    ok = abs(got - want) <= tol
    print(f"{'ok  ' if ok else 'FAIL'} {name}: got {got:.4g}, expected {want:.4g} (+/- {tol})")
    if not ok:
        failures.append(name)


def check_true(name, cond):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        failures.append(name)


# ---- valve data
check("R 1in 3/16", gv.valve_R("1 in OD", 0.1875), 0.094, 1e-9)
check("R 1.5in 1/4", gv.valve_R("1.5 in OD", 0.25), 0.066, 1e-9)
check("PPEF 3/16 J-40", gv.ppef(0.094), 0.104, 0.0005)

# ---- nitrogen dome pressure: Takacs Example 3-1 (600 psig at 60 F -> about 750 psig at 180 F)
for m in ("api", "winkler", "gas_law"):
    check(f"dome 600 psig @180F ({m})", gv.dome_pressure_downhole(600.0, 180.0, m), 750.0, 12.0)
for m in ("winkler", "gas_law"):                                    # inverse is the inverse
    pd = gv.dome_pressure_downhole(800.0, 140.0, m)
    check(f"inverse ({m})", gv.dome_pressure_60(pd, 140.0, m), 800.0, 0.01)
check("Ct 123.5F (API Table A-1 0.880)", gv.ct_api(123.5), 0.880, 0.001)
check("Ct 134.6F (0.862)", gv.ct_api(134.6), 0.862, 0.001)
check("Ct 150F (0.838)", gv.ct_api(150.0), 0.838, 0.001)

# ---- Thornhill-Craver: Takacs Example 2-17 (1098 Mscf/d sub-critical, 1281 critical)
q = gv.gas_passage(0.25, 1000 - 14.7, 800 - 14.7, 0.65, 150.0, cd=0.9, k=1.256)
check("choke sub-critical", q, 1098.0, 20.0)
q = gv.gas_passage(0.25, 1000 - 14.7, 500 - 14.7, 0.65, 150.0, cd=0.9, k=1.256)
check("choke critical", q, 1281.0, 20.0)

# ---- PPO valve of Takacs Example 5-21, valve 1:  R 0.094, pi 978, ppo 547 -> pd 588, TRO 589
pd = gv.ppo_dome(0.094, 547.0, 978.0)
check("PPO pd", pd, 588.0, 1.0)
check("PPO opening back", gv.ppo_opening(pd, 0.094, 978.0), 547.0, 0.01)
check("PPO TRO (pd60 534)", gv.tro(534.0, 0.094), 589.0, 1.0)

# ---- IPO valve of API Example 3, valve 1: Pvo = (PPEF pt + pi) Ct = (0.104*430 + 1275) 0.880 = 1161
r = 0.094
pd = gv.ipo_dome(0.094, 1275.0, 430.0)
pd60 = pd * gv.ct_api(123.5)
check("API ex3 valve 1 test rack opening (R .104 form)", (0.104 * 430 + 1275) * gv.ct_api(123.5), 1161.0, 1.5)

# ---- design, Takacs Example 5-17/5-18/5-19 data
POINTS_D = [0, 1832, 3025, 3731, 4110, 4281, 4500]
POINTS_P = [100, 392, 605, 740, 814, 848, 893]
p_flow = lambda d: gv.interp(d, POINTS_D, POINTS_P)
t_flow = lambda d: 80.0 + 0.015 * d                                    # 80 F at surface, 170 F at 6000 ft
tvd_of = md_of = lambda x: x
common = dict(tvd_of=tvd_of, md_of=md_of, p_ko=950.0, p_op=950.0, p_wh=100.0, g_unload=0.468,
              gas_p=gv.constant_gradient_gas(0.015), p_flow=p_flow, t_flow=t_flow, tvd_inj=4500.0, tvd_max=6000.0,
              od="1 in OD", port=0.1875, min_spacing_md=150.0, dome_method="winkler", operating="valve")

# Example 5-18: constant pressure drop 25 psi per valve, delta p valve 20 psi
res = gv.design_string("ipo_api", dp_valve=20.0, drop_mode="fixed", drop_fixed=25.0, **common)
book = [(1832, 977, 922, 836), (3025, 970, 936, 819), (3731, 956, 936, 803), (4110, 937, 925, 786), (4281, 914, 908, 768)]
check("5-18 number of valves", len(res["valves"]), 5, 0)
for v, (d, pi, pdv, p60) in zip(res["valves"], book):
    check(f"5-18 valve {v['n']} depth", v["tvd"], d, 12.0)
    check(f"5-18 valve {v['n']} pi", v["p_inj"], pi, 3.0)
    check(f"5-18 valve {v['n']} pd", v["pd"], pdv, 4.0)
    check(f"5-18 valve {v['n']} pd at 60F", v["pd60"], p60, 6.0)
check("5-18 TRO valve 1", res["valves"][0]["tro"], 922.0, 6.0)
check("5-18 TRO valve 5", res["valves"][4]["tro"], 848.0, 8.0)

# Example 5-19: constant surface opening pressure, injection point 4500 ft (tubing pressure 893 psi there)
common19 = dict(common, min_spacing_md=40.0)               # the book puts no minimum on the spacing
res = gv.design_string("ipo_optiflow", dp_valve=0.0, **common19)
book = [(1876, 978, 938, 848), (2828, 992, 962, 847), (3535, 1003, 981, 845), (4059, 1011, 994, 845),
        (4449, 1017, 1004, 844)]
check("5-19 point A", res["a"], 300.0, 0.01)
check("5-19 valves (unloading valves + operating valve at 4500)", len(res["valves"]), 6, 0)
for v, (d, pi, pdv, p60) in zip(res["valves"], book):
    check(f"5-19 valve {v['n']} depth", v["tvd"], d, 8.0)
    check(f"5-19 valve {v['n']} pi", v["p_inj"], pi, 2.0)
    check(f"5-19 valve {v['n']} pd", v["pd"], pdv, 4.0)
    check(f"5-19 valve {v['n']} pd at 60F", v["pd60"], p60, 6.0)
check("5-19 operating valve depth", res["valves"][-1]["tvd"], 4500.0, 0.01)

# Example 5-21: the same spacing with PPO valves
res = gv.design_string("ppo", dp_valve=0.0, **common19)
book = [(1876, 978, 547, 588, 534, 589), (2828, 992, 672, 702, 620, 685), (3535, 1003, 765, 788, 681, 752),
        (4059, 1011, 834, 851, 725, 800), (4449, 1017, 886, 898, 756, 835)]
for v, (d, pi, ppo, pdv, p60, tr) in zip(res["valves"], book):
    check(f"5-21 valve {v['n']} ptd", v["p_tub"], ppo, 3.0)
    check(f"5-21 valve {v['n']} pd", v["pd"], pdv, 4.0)
    check(f"5-21 valve {v['n']} pd at 60F", v["pd60"], p60, 6.0)
    check(f"5-21 valve {v['n']} TRO", v["tro"], tr, 8.0)

# ---- API RP 11V6 Example 3: mandrels already spaced.  Valve settings of Table 7 (test rack pressures) are
#      checked: the unloading should go down to the 7000 ft valve; 7500 ft is "just out of reach".
MANDRELS_MD = [2450, 3921, 5094, 5962, 6624, 7287, 7949, 8612, 9274, 9804]
MANDRELS_TVD = [2350, 3460, 4345, 5000, 5500, 6000, 6500, 7000, 7500, 7900]
SET = {2350: 1161, 3460: 1162, 5000: 1176, 6000: 1177, 6500: 1173, 7000: 1167}      # tro (R = 0.104 form)
PMIN = {2350: 430, 3460: 570, 4345: 700, 5000: 800, 5500: 880, 6000: 940, 6500: 1050, 7000: 1140, 7500: 1240,
        7900: 1310}
d_list = sorted(PMIN)
p_flow_api = lambda d: gv.interp(d, [0] + d_list, [120] + [PMIN[k] for k in d_list])
valves = []
for n, (md, tv) in enumerate(zip(MANDRELS_MD, MANDRELS_TVD), 1):
    T = 100.0 + 1.0 * tv / 100.0
    if tv in SET:
        # API quotes the test rack pressure of the (production pressure effect) form; convert to a dome pressure
        r = 0.094
        pd60 = SET[tv] * (1.0 - r)
        v = gv.make_valve(n, md, tv, "IPO", T, "1 in OD", 0.1875, SET[tv], "api")
    elif tv == 7500:
        v = gv.make_valve(n, md, tv, "orifice", T, "1 in OD", 0.25)
    else:
        v = gv.make_valve(n, md, tv, "dummy", T)
    valves.append(v)
chk = gv.check_string(valves, p_ko=1200.0, p_op=1100.0, p_wh=120.0, g_unload=0.465,
                      gas_p=gv.constant_gradient_gas(0.032), p_flow=p_flow_api, sfl_tvd=0.0, dp_valve=0.0,
                      surface_drop=20.0, target_tvd=7500.0)
for s in chk["stages"]:
    print("   stage", s["n"], s["md"], s["tvd"], s["kind"], f"p_tub {s['p_tub']:.0f} p_inj {s['p_inj']:.0f} opens {s['opens']}")
print(chk["verdict"])
for i in chk["issues"]:
    print("   -", i)
check_true("API ex 3: kick-off is possible", chk["kickoff_ok"])
check_true("API ex 3: unloads through valve 6 (7000 ft)", chk["reached"] is not None and chk["reached"]["tvd"] >= 7000)

# ---- the checks say NO when they should
# kick-off pressure too low for the top valve
lowko = gv.check_string(valves, p_ko=900.0, p_op=800.0, p_wh=120.0, g_unload=0.465,
                        gas_p=gv.constant_gradient_gas(0.032), p_flow=p_flow_api, dp_valve=0.0)
check_true("check: kick-off with too little pressure fails", not lowko["kickoff_ok"] and not lowko["ok"])
# too much operating pressure opens the upper valves again (multi-pointing)
hi = gv.check_string(valves, p_ko=1200.0, p_op=1250.0, p_wh=120.0, g_unload=0.465,
                     gas_p=gv.constant_gradient_gas(0.032), p_flow=p_flow_api, dp_valve=0.0, surface_drop=20.0)
check_true("check: operating pressure too high gives multi-pointing", bool(hi["operating"]["multi_pointing"]) and not hi["ok"])
# a PPO valve below an IPO valve whose tubing pressure stays high does not close
# ---- design on the default well of the page; every design that reaches its injection point passes its own check
import app_helpers as ah
import gaslift_design as gd
case = ah.build_case(dict(ah.DEFAULTS))
g = dict(gd.GL_DEFAULTS)
g.update(rate=600.0, gas_rate=500.0, md_inj=6000.0, md_max=7900.0, p_ko=1300.0, p_op=1200.0, p_wh=185.0, min_spacing=250.0)
for sfl in (0.0, 2500.0):
    for method in ("ipo_api", "ppo"):
        g["sfl_md"] = sfl
        run = gd.run_design(case, g, method)
        v = run["valves"]
        label = f"default well, {method}, liquid level {sfl:.0f} ft"
        check_true(f"{label}: design reaches the injection depth", run["design"]["reached"])
        check_true(f"{label}: passes its own check ({run['check']['verdict'][:40]}...)", run["check"]["ok"])
        check_true(f"{label}: valve depths increase", all(b["md"] > a["md"] for a, b in zip(v, v[1:])))
        check_true(f"{label}: no valve above the liquid level", all(x["md"] >= sfl - 1.0 for x in v))
        check_true(f"{label}: spacing at least 250 ft MD", all(b["md"] - a["md"] >= 249.0 for a, b in zip(v, v[1:])))
        check_true(f"{label}: frames made", len(gd.frames_for(run, run["valves"], run["ctx"], g, run["check"])) > 5)
# IPO closing pressures (as a surface pressure) fall down the string
g["sfl_md"] = 0.0
run = gd.run_design(case, g, "ipo_api")
close_surface = [gv.surface_pressure_for(run["ctx"]["gas_p"], v["tvd"], v["pd"]) for v in run["valves"] if v["kind"] == "IPO"]
check_true("IPO design: closing pressures fall with depth",
           all(b < a + gv.TRANSFER_MARGIN for a, b in zip(close_surface, close_surface[1:])))
# a lower kick-off pressure gives a shallower string, a higher operating pressure a deeper reach
g2 = dict(g, p_ko=1000.0, p_op=900.0)
run2 = gd.run_design(case, g2, "ipo_api")
check_true("lower pressures: the string does not reach as deep", run2["valves"][-1]["md"] <= run["valves"][-1]["md"])

if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    raise SystemExit(1)
print("\nAll gas lift valve tests passed.")
