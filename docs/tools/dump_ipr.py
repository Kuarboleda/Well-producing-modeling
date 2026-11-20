"""
dump_ipr.py - run a large set of IPR cases through the PYTHON engine and write the answers to JSON.

The JavaScript side (tools/crosscheck.mjs) feeds the same inputs to ipr.js and compares.

Run from the docs/ folder:   PYTHONPATH=.. python3 tools/dump_ipr.py tools/ipr_expected.json
"""
import json
import math
import random
import sys
import warnings

sys.path.insert(0, "..")
import ipr                                            # noqa: E402  (the Python engine)

warnings.simplefilter("ignore")                       # the warnings do not change a returned number


def cases():
    """Every case: a name, the function to call, and its arguments (positional, as ipr.js takes them)."""
    random.seed(20261120)
    out = []

    # ---- the oil IPR shape, through every model that uses it ---------
    for p_res in (800.0, 2000.0, 3014.7, 6000.0):
        for pb in (0.0, 500.0, 2498.38, 3500.0, 8000.0):
            for J in (0.3, 3.0, 25.0):
                for frac in (0.0, 0.05, 0.3, 0.5, 0.7, 0.95, 0.999, 1.0, 1.2):
                    pwf = p_res * frac
                    out.append(("oil_pi", "oil_pi", [p_res, pwf, pb, J]))
            # Vogel, calibrated from one test at a few places on the curve
            for test_frac in (0.1, 0.4, 0.75, 0.95):
                q_test = 1500.0
                pwf_test = p_res * test_frac
                out.append(("vogel_productivity_index", "vogel_productivity_index",
                            [p_res, pb, q_test, pwf_test]))
                for frac in (0.0, 0.25, 0.6, 0.9):
                    out.append(("oil_vogel", "oil_vogel", [p_res, p_res * frac, pb, q_test, pwf_test]))

    # ---- Darcy and its three regimes --------------------------------
    for k in (0.5, 20.0, 300.0):
        for h in (10.0, 50.0, 250.0):
            for skin in (-1.5, 0.0, 5.0, 20.0):
                for re, rw in ((660.0, 0.354), (1500.0, 0.25), (300.0, 0.5)):
                    out.append(("darcy_productivity_index_oil", "darcy_productivity_index_oil",
                                [k, h, 1.25, 0.8, re, rw, skin]))
                    out.append(("darcy_productivity_index_oil_steady", "darcy_productivity_index_oil_steady",
                                [k, h, 1.25, 0.8, re, rw, skin]))
                    out.append(("oil_darcy", "oil_darcy",
                                [3014.7, 1200.0, 2498.38, k, h, 1.25, 0.8, re, rw, skin]))
                    for t in (2.0, 24.0, 500.0, 20000.0):
                        out.append(("darcy_productivity_index_oil_transient",
                                    "darcy_productivity_index_oil_transient",
                                    [k, h, 1.25, 0.8, 0.2, 1.2e-5, rw, t, skin]))
                        out.append(("oil_darcy_regime_transient", "oil_darcy_regime",
                                    [3014.7, 1200.0, 2498.38, k, h, 1.25, 0.8, re, rw, skin,
                                     "transient", 0.2, 1.2e-5, t]))
                    out.append(("oil_darcy_regime_steady", "oil_darcy_regime",
                                [3014.7, 1200.0, 2498.38, k, h, 1.25, 0.8, re, rw, skin, "steady"]))
                    out.append(("transient_end_time_hours", "transient_end_time_hours",
                                [k, 0.2, 0.8, 1.2e-5, re]))

    # ---- Fetkovich and the back-pressure equation -------------------
    for p_res in (1500.0, 3014.7, 7000.0):
        for (q1, pwf1, q2, pwf2) in ((1000.0, 2500.0, 2000.0, 1800.0),
                                     (500.0, 1400.0, 900.0, 900.0),
                                     (4000.0, 1000.0, 1200.0, 1400.0)):
            if max(pwf1, pwf2) >= p_res:
                continue
            out.append(("c_and_n_from_two_tests", "c_and_n_from_two_tests", [p_res, q1, pwf1, q2, pwf2]))
            for frac in (0.0, 0.3, 0.8, 1.0):
                out.append(("oil_fetkovich", "oil_fetkovich",
                            [p_res, p_res * frac, q1, pwf1, q2, pwf2]))
        for C in (0.0005, 0.015, 2.0):
            for n in (0.5, 0.72, 1.0):
                for frac in (0.0, 0.4, 0.9, 1.0):
                    out.append(("gas_backpressure", "gas_backpressure", [p_res, p_res * frac, C, n]))

    # ---- gas Darcy and Jones ----------------------------------------
    for k in (0.1, 5.0, 100.0):
        for h in (20.0, 120.0):
            for skin in (0.0, 8.0):
                for z in (0.85, 1.05):
                    for mu in (0.015, 0.03):
                        out.append(("gas_a_coefficient", "gas_a_coefficient",
                                    [200.0, k, h, mu, z, 1500.0, 0.25, skin]))
                        out.append(("gas_darcy", "gas_darcy",
                                    [3014.7, 1500.0, 200.0, k, h, mu, z, 1500.0, 0.25, skin]))
                        for beta in (None, 1.0e8):
                            out.append(("gas_b_coefficient", "gas_b_coefficient",
                                        [200.0, k, h, z, 0.65, 0.25, beta]))
                            for frac in (0.0, 0.5, 0.95):
                                out.append(("gas_jones", "gas_jones",
                                            [3014.7, 3014.7 * frac, 200.0, k, h, mu, z, 0.65,
                                             1500.0, 0.25, skin, beta, h]))
        out.append(("gas_beta_firoozabadi_katz", "gas_beta_firoozabadi_katz", [k]))

    # ---- horizontal wells, Joshi ------------------------------------
    for kh in (5.0, 80.0):
        for kv_ratio in (0.1, 1.0):
            for length in (500.0, 2000.0, 4000.0):
                for h in (30.0, 150.0):
                    for skin in (0.0, 4.0):
                        args = [kh, kh * kv_ratio, h, length, 2500.0, 0.354, 1.25, 0.8, skin]
                        out.append(("horizontal_productivity_index_oil_joshi",
                                    "horizontal_productivity_index_oil_joshi", args))
                        out.append(("oil_horizontal_joshi", "oil_horizontal_joshi",
                                    [3014.7, 1500.0, 2498.38, kh, kh * kv_ratio, h, length,
                                     2500.0, 0.354, 1.25, 0.8, skin]))
                        out.append(("gas_a_coefficient_horizontal_joshi", "gas_a_coefficient_horizontal_joshi",
                                    [200.0, kh, kh * kv_ratio, h, length, 2500.0, 0.354, 0.02, 0.9, skin]))
                        out.append(("gas_horizontal_joshi", "gas_horizontal_joshi",
                                    [3014.7, 1500.0, 200.0, kh, kh * kv_ratio, h, length, 2500.0,
                                     0.354, 0.02, 0.9, 0.65, skin, None]))

    # ---- Bickley Ki2 (the integral behind Kuchuk and Goode) ---------
    for beta in (0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 12.0, 40.0):
        out.append(("bickley_ki2", "bickley_ki2", [beta]))

    # ---- horizontal wells, Kuchuk and Goode (slow: a few cases only) -
    for top in ("sealed", "constant_pressure"):
        for length in (1000.0, 3000.0):
            for zw in (25.0, 50.0, 90.0):
                args = [50.0, 5.0, 100.0, length, 5000.0, 3000.0, 2500.0, 1500.0, zw, 0.354, 1.25, 0.8,
                        0.0, 1.0, top]
                out.append(("horizontal_productivity_index_oil_kuchuk_goode",
                            "horizontal_productivity_index_oil_kuchuk_goode", args))
                out.append(("oil_horizontal_kuchuk_goode", "oil_horizontal_kuchuk_goode",
                            [3014.7, 1500.0, 2498.38, 50.0, 5.0, 100.0, length, 5000.0, 3000.0,
                             2500.0, 1500.0, zw, 0.354, 1.25, 0.8, 3.0, 1.0, top]))
                out.append(("gas_horizontal_kuchuk_goode", "gas_horizontal_kuchuk_goode",
                            [3014.7, 1500.0, 200.0, 50.0, 5.0, 100.0, length, 5000.0, 3000.0,
                             2500.0, 1500.0, zw, 0.354, 0.02, 0.9, 0.65, 0.0, 1.0, top, None]))

    # ---- multilayer, oil --------------------------------------------
    layer_sets = [
        [{"p_res": 3014.7, "J": 3.0}],
        [{"p_res": 3014.7, "J": 3.0}, {"p_res": 2200.0, "J": 1.2}],
        [{"p_res": 3014.7, "J": 3.0, "wc": 0.1, "gor": 400.0},
         {"p_res": 2500.0, "J": 1.5, "wc": 0.6, "gor": 900.0},
         {"p_res": 1800.0, "J": 0.4}],
    ]
    for layers in layer_sets:
        for crossflow in (False, True):
            for pwf in (0.0, 500.0, 1800.0, 2200.0, 2500.0, 3014.7, 3200.0):
                out.append(("multilayer_rates", "multilayer_rates", [3014.7, pwf, 2498.38, layers, crossflow]))
                out.append(("oil_multilayer", "oil_multilayer", [3014.7, pwf, 2498.38, layers, crossflow]))
                out.append(("multilayer_mix", "multilayer_mix",
                            [3014.7, pwf, 2498.38, layers, 0.25, 500.0, crossflow]))
            for q in (0.0, 100.0, 2000.0, 9000.0, 1e7):
                out.append(("multilayer_pwf", "multilayer_pwf", [q, 3014.7, 2498.38, layers, crossflow]))

    # ---- multilayer, gas --------------------------------------------
    gas_sets = [
        [{"p_res": 3014.7, "a": 2500.0, "b": 0.02}],
        [{"p_res": 3014.7, "a": 2500.0, "b": 0.02}, {"p_res": 2000.0, "C": 0.004, "n": 0.82}],
        [{"p_res": 4000.0, "a": 900.0, "b": 0.0, "cgr": 15.0, "wgr": 2.0},
         {"p_res": 3000.0, "C": 0.01, "n": 0.9, "cgr": 40.0},
         {"p_res": 2000.0, "a": 5000.0, "b": 0.5}],
    ]
    for layers in gas_sets:
        for crossflow in (False, True):
            for pwf in (0.0, 800.0, 2000.0, 3000.0, 4000.0, 4500.0):
                out.append(("gas_multilayer_rates", "gas_multilayer_rates", [4000.0, pwf, layers, crossflow]))
                out.append(("gas_multilayer", "gas_multilayer", [4000.0, pwf, layers, crossflow]))
                out.append(("gas_multilayer_mix", "gas_multilayer_mix", [4000.0, pwf, layers, 10.0, 1.0, crossflow]))
            for q in (0.0, 500.0, 20000.0, 1e9):
                out.append(("gas_multilayer_pwf", "gas_multilayer_pwf", [q, 4000.0, layers, crossflow]))
    return out


def run_one(func_name, args):
    value = getattr(ipr, func_name)(*args)
    if isinstance(value, tuple):
        return list(value)
    return value


def main(path):
    rows, skipped = [], 0
    for name, func_name, args in cases():
        try:
            rows.append({"name": name, "func": func_name, "args": args, "want": run_one(func_name, args)})
        except (ValueError, ZeroDivisionError, OverflowError):
            skipped += 1
    with open(path, "w") as handle:
        json.dump(rows, handle)
    print(f"{len(rows)} cases written to {path} ({skipped} refused by the Python and left out)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tools/ipr_expected.json")
