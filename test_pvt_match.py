"""Checks for pvt_match.py (PVT matching to lab data).  Run:  python test_pvt_match.py

The idea of the tests: build "lab data" from the program's own correlation after changing it in a KNOWN
way (Rs reshaped by exponent 1.3, Bo scaled by 1.03 and shifted, viscosity doubled).  The matching must
then find those same numbers back.  A fit that recovers a change it was never told about is a fit that works.
"""
import pvt
import pvt_match as pm

API, GG, RSB, T = 35.0, 0.75, 500.0, 200.0


def check(name, got, expected, tol=1e-6):
    ok = abs(got - expected) <= tol * max(abs(expected), 1e-12) if expected != 0 else abs(got) <= tol
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<58s} got {got:12.6g}   expected {expected:12.6g}")
    assert ok, name


def check_true(name, condition):
    print(f"  {'PASS' if condition else 'FAIL'}  {name}")
    assert condition, name


def check_error(name, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except ValueError:
        print(f"  PASS  {name:<58s} (ValueError raised, as wanted)")
        return
    raise AssertionError(f"{name}: expected a ValueError")


PB = pvt.pb_standing(RSB, GG, API, T)            # Standing's bubble point: 2205.09 psia
PRESSURES = [500.0, 1000.0, 1500.0, 2000.0, PB, PB + 1500.0, PB + 3000.0]


def fake_lab(match):
    """Lab rows made from Standing + Beal with a known change applied."""
    rows = []
    for p in PRESSURES:
        o = pvt.oil_properties(p, T, API, GG, RSB, None, "standing", "beal", match)
        rows.append({"p": p, "rs": o["rs"], "bo": o["bo"], "mu": o["mu_o"]})
    return pm.clean_lab_table(rows)


print("== The match numbers in pvt.oil_properties ==")
plain = pvt.oil_properties(1500.0, T, API, GG, RSB, None, "standing", "beal")
check("no match numbers = unchanged Bo", pvt.oil_properties(1500.0, T, API, GG, RSB, None, "standing", "beal", pm.NO_MATCH)["bo"], plain["bo"])
check("viscosity x 2 doubles the viscosity",
      pvt.oil_properties(1500.0, T, API, GG, RSB, None, "standing", "beal", {"mu_mult": 2.0})["mu_o"], 2 * plain["mu_o"])
changed = pvt.oil_properties(1500.0, T, API, GG, RSB, None, "standing", "beal", {"bo_a": 1.1, "bo_b": 0.02})
check("Bo = 1.1 * Bo + 0.02", changed["bo"], 1.1 * plain["bo"] + 0.02)
at_pb = pvt.oil_properties(PB, T, API, GG, RSB, None, "standing", "beal", {"rs_exp": 1.3})
check("Rs exponent keeps Rs(Pb) = rsb", at_pb["rs"], RSB, 1e-9)
low = pvt.oil_properties(1500.0, T, API, GG, RSB, None, "standing", "beal", {"rs_exp": 1.3})
check("Rs exponent: Rs = rsb*(Rs/rsb)^1.3", low["rs"], RSB * (plain["rs"] / RSB) ** 1.3)
check("Rs never below zero (Lasater near 0 psia)", float(pvt.oil_properties(20.0, T, API, GG, RSB, None, "lasater", "beal")["rs"] >= 0.0), 1.0)

print("\n== Cleaning the lab table typed on the page ==")
table = pm.clean_lab_table([{"p": 2000, "rs": None, "bo": 1.2, "mu": float("nan")},
                            {"p": float("nan"), "rs": 100, "bo": None, "mu": None},     # no pressure: dropped
                            {"p": 500, "rs": 80, "bo": None, "mu": None},
                            {"p": 900, "rs": None, "bo": None, "mu": None}])            # no property: dropped
check("two usable rows are kept", len(table), 2)
check("rows are sorted by pressure", table[0]["p"], 500.0)
check_true("blank cells become None", table[1]["rs"] is None and table[1]["mu"] is None)
check_error("empty table", pm.clean_lab_table, [])
check_error("negative viscosity", pm.clean_lab_table, [{"p": 500, "mu": -1}])
check_error("zero pressure", pm.clean_lab_table, [{"p": 0, "rs": 10}])

print("\n== Matching finds a known change (Rs exponent 1.3, Bo x1.03 + 0.01, viscosity x 2) ==")
truth = {"rs_exp": 1.3, "bo_a": 1.03, "bo_b": 0.01, "mu_mult": 2.0}
lab = fake_lab(truth)
fit = pm.fit_match(lab, API, GG, RSB, T, None, "standing", "beal")
check("Rs exponent found", fit["match"]["rs_exp"], 1.3, 1e-3)
check("Bo multiplier found", fit["match"]["bo_a"], 1.03, 1e-3)
check("Bo shift found", fit["match"]["bo_b"], 0.01, 1e-2)
check("viscosity multiplier found", fit["match"]["mu_mult"], 2.0, 1e-3)
check_true("errors before are real, errors after are ~0",
           fit["before"]["rs"] > 3 and fit["before"]["bo"] > 1 and fit["before"]["mu"] > 50 and
           all(v < 1e-3 for v in fit["after"].values()))
check("bubble point used = Standing's (none measured)", fit["pb"], PB, 1e-9)

print("\n== Matching with little data ==")
one_bo = pm.fit_match(pm.clean_lab_table([{"p": 1500, "bo": 1.25}]), API, GG, RSB, T, None, "standing", "beal")
check("one Bo point: curve passes through it", pvt.oil_properties(1500.0, T, API, GG, RSB, None, "standing", "beal", one_bo["match"])["bo"], 1.25, 1e-9)
check_true("one Bo point: a plain-language note says only a multiplier was fitted", any("multiplier" in n for n in one_bo["notes"]))
check("no Rs lab data: Rs left alone", one_bo["match"]["rs_exp"], 1.0)
above = pm.fit_match(pm.clean_lab_table([{"p": PB + 500, "rs": RSB}]), API, GG, RSB, T, None, "standing", "beal")
check_true("lab Rs only above Pb: not matched, with a note", above["match"]["rs_exp"] == 1.0 and any("Rs" in n for n in above["notes"]))

print("\n== Which correlation is closest ==")
ranking = pm.compare_methods(fake_lab(pm.NO_MATCH), API, GG, RSB, T, PB)
check_true("the correlation that made the data is ranked first", ranking[0]["pvt_method"] == "standing" and ranking[0]["visc_method"] == "beal")
check("its errors are zero", ranking[0]["score"], 0.0, 1e-9)
check("12 combinations (4 x 3) are compared", len(ranking), 12)
check_true("sorted best first", all(ranking[i]["score"] <= ranking[i + 1]["score"] for i in range(11)))
no_pb = pm.compare_methods(fake_lab(pm.NO_MATCH), API, GG, RSB, T, None)
check_true("without a measured Pb the Pb error is None", all(r["pb_error"] is None for r in no_pb))
check("mean absolute error: lab 100 vs calc 110 and 80", pm.mean_abs_percent_error([100.0, 100.0], [110.0, 80.0]), 15.0)

print("\n== Measured bubble point ==")
fit_pb = pm.fit_match(lab, API, GG, RSB, T, 2400.0, "standing", "beal")
check("bubble point used = the measured one", fit_pb["pb"], 2400.0)

print("\n== Petrosky and Farshad viscosity (SPE 29468) ==")
import math
# Dead oil, 30 API at 200 degF, worked by hand with logarithms:
#   log10(200) = 2.30103 ; X = 4.59388 * 2.30103 - 22.82792 = -12.25722 ; log10(30) = 1.47712
#   ln(mud) = ln(2.3511e7) - 2.10255 ln(200) + X ln(1.47712) = 16.97273 - 11.14008 + (-12.25722)(0.39005) = 1.0517  ->  mud = 2.862 cP
x_pet = 4.59388 * math.log10(200.0) - 22.82792
mud_hand = math.exp(math.log(2.3511e7) - 2.10255 * math.log(200.0) + x_pet * math.log(math.log10(30.0)))
check("dead oil (hand, through logarithms)", pvt.mu_dead_petrosky(30.0, 200.0), mud_hand, 1e-9)
check("dead oil = 2.862 cP (the hand number above)", pvt.mu_dead_petrosky(30.0, 200.0), 2.862, 1e-3)
# Saturated at Rs = 500: A = 0.1651 + 0.6165 * 10^(-0.30433) = 0.47145 ; B = 0.5131 + 0.5109 * 10^(-0.59155) = 0.64370 ; mu = A * 2.862^B
a_sat = 0.1651 + 0.6165 * 10 ** (-6.0866e-4 * 500.0)
b_sat = 0.5131 + 0.5109 * 10 ** (-1.1831e-3 * 500.0)
check("saturated oil, Rs 500 (hand)", pvt.mu_live_petrosky(2.862, 500.0), a_sat * 2.862 ** b_sat, 1e-9)
check("saturated oil, Rs 500 = 0.927 cP", pvt.mu_live_petrosky(pvt.mu_dead_petrosky(30.0, 200.0), 500.0), 0.927, 2e-3)
check("no dissolved gas: A = 0.7816, B = 1.024", pvt.mu_live_petrosky(1.0, 0.0), 0.1651 + 0.6165, 1e-12)
# Undersaturated: mu = mub + 1.3449e-3 (p - pb) 10^A with log10(0.927) = -0.03292:
#   A = -1.0146 + 1.3322(-0.03292) - 0.4876(0.001084) - 1.15036(-0.0000357) = -1.05855 ; 10^A = 0.08716
mub = 0.927
lg = math.log10(mub)
a_us = -1.0146 + 1.3322 * lg - 0.4876 * lg ** 2 - 1.15036 * lg ** 3
check("undersaturated, 1000 psi above Pb (hand)", pvt.mu_under_petrosky(mub, 3000.0, 2000.0), mub + 1.3449e-3 * 1000.0 * 10 ** a_us, 1e-9)
check("undersaturated at the bubble point = the saturated value", pvt.mu_under_petrosky(mub, 2000.0, 2000.0), mub, 1e-12)
# Sanity against the other correlations (not an independent proof, but a wrong constant would show): dead oil within 20 %
for api, temp in ((25.0, 150.0), (30.0, 200.0), (35.0, 200.0), (40.0, 250.0)):
    pet, bg = pvt.mu_dead_petrosky(api, temp), pvt.mu_dead_beggs(api, temp)
    check_true(f"dead oil {api:.0f} API, {temp:.0f} degF: within 20 % of Beggs-Robinson ({pet:.2f} vs {bg:.2f} cP)", abs(pet / bg - 1.0) < 0.2)
op = [pvt.oil_properties(p, T, API, GG, RSB, None, "glaso", "petrosky")["mu_o"] for p in (500.0, 1500.0, 2500.0, 3500.0, 4500.0)]
check_true("viscosity falls as pressure rises to Pb (more gas dissolves) and rises above Pb",
           op[0] > op[1] > op[2] and op[4] > op[3] > op[2])
check_error("unknown viscosity method", pvt.oil_properties, 1000.0, T, API, GG, RSB, None, "glaso", "nonsense")

print("\nAll checks passed.")
