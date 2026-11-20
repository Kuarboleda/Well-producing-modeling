"""
dump_vlp.py - run a large set of VLP cases through the PYTHON engine and write the answers to JSON.

The JavaScript side (tools/crosscheck.mjs) feeds the same inputs to vlp.js and compares.
The VLP is being translated in stages, so this file grows as each stage lands.

Run from the docs/ folder:   PYTHONPATH=.. python3 tools/dump_vlp.py tools/vlp_expected.json
"""
import json
import math
import random
import sys
import warnings

sys.path.insert(0, "..")
import vlp                                            # noqa: E402  (the Python engine)

warnings.simplefilter("ignore")


def conditions(v_sl, v_sg, rho_l=52.0, rho_g=2.5, mu_l=1.2, mu_g=0.018, sigma=20.0,
               frac_w=0.0, glr=500.0):
    """One set of flow conditions, in the shape the gradient functions expect."""
    return {"v_sl": v_sl, "v_sg": v_sg, "rho_l": rho_l, "rho_g": rho_g, "mu_l": mu_l,
            "mu_g": mu_g, "sigma": sigma, "frac_w": frac_w, "glr": glr}


def cases():
    """Every case: a name, the function to call, and its arguments."""
    random.seed(20261120)
    out = []

    # ---- friction factor: laminar, the blend and the turbulent range ----
    for re in (1.0, 50.0, 1000.0, 2099.0, 2100.0, 2500.0, 3999.0, 4000.0, 1e4, 1e5, 1e6, 1e8):
        for eps in (0.0, 1e-5, 1e-4, 6e-4, 0.002, 0.01, 0.05):
            out.append(("friction_factor", "friction_factor", [re, eps]))

    # ---- surface tension -------------------------------------------
    for api in (8.0, 18.7, 30.0, 45.0, 60.0):
        for T in (50.0, 68.0, 85.0, 100.0, 180.0, 300.0):
            for p in (14.7, 100.0, 800.0, 3000.0, 12000.0):
                out.append(("sigma_oil_gas", "sigma_oil_gas", [api, T, p]))
    for T in (50.0, 74.0, 150.0, 280.0, 350.0):
        for p in (14.7, 500.0, 4000.0, 15000.0):
            out.append(("sigma_water_gas", "sigma_water_gas", [T, p]))

    # ---- Beggs and Brill: every flow pattern, every angle ------------
    # The velocities are chosen to walk across all four horizontal patterns and the transition.
    v_sl_list = (0.0, 1e-9, 0.002, 0.05, 0.4, 2.0, 8.0, 30.0)
    v_sg_list = (0.0, 1e-9, 0.01, 0.3, 3.0, 25.0, 120.0)
    angles = (-90.0, -45.0, -5.0, 0.0, 5.0, 30.0, 60.0, 90.0)
    for v_sl in v_sl_list:
        for v_sg in v_sg_list:
            if v_sl + v_sg <= 0:
                continue
            for angle in angles:
                out.append(("beggs_brill_gradient", "beggs_brill_gradient",
                            [1500.0, angle, 2.992, 0.0006, conditions(v_sl, v_sg)]))

    # a spread of fluids and pipe sizes at a few representative velocities
    for d_in in (1.995, 2.441, 2.992, 4.0, 7.0):
        for rho_l, mu_l, sigma in ((45.0, 0.4, 8.0), (52.0, 1.2, 20.0), (62.4, 0.6, 60.0), (58.0, 90.0, 30.0)):
            for rho_g, mu_g in ((0.6, 0.012), (2.5, 0.018), (12.0, 0.03)):
                for v_sl, v_sg in ((0.1, 0.5), (1.5, 4.0), (0.02, 30.0), (6.0, 0.4)):
                    for angle in (90.0, 55.0, 0.0, -30.0):
                        out.append(("beggs_brill_gradient", "beggs_brill_gradient",
                                    [900.0, angle, d_in, 0.0006,
                                     conditions(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma)]))

    # random cases, to catch anything the grid steps over
    for _ in range(2500):
        v_sl = 10 ** random.uniform(-4, 1.6)
        v_sg = 10 ** random.uniform(-4, 2.3)
        out.append(("beggs_brill_gradient_random", "beggs_brill_gradient",
                    [10 ** random.uniform(1.3, 4.0),                 # 20 to 10,000 psia
                     random.uniform(-90.0, 90.0),
                     random.uniform(1.0, 7.0),
                     random.choice([0.0, 0.0006, 0.002]),
                     conditions(v_sl, v_sg,
                                random.uniform(40.0, 70.0), random.uniform(0.2, 20.0),
                                10 ** random.uniform(-1, 2), random.uniform(0.01, 0.04),
                                random.uniform(1.0, 70.0))]))

    # the pressure-only knob: the acceleration term and its cap
    for p in (20.0, 100.0, 1000.0, 20000.0):
        for v_sg in (0.5, 50.0, 300.0):
            out.append(("beggs_brill_gradient_ek", "beggs_brill_gradient",
                        [p, 90.0, 2.441, 0.0006, conditions(0.5, v_sg)]))
    return out


def run_one(func_name, args):
    value = getattr(vlp, func_name)(*args)
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
    main(sys.argv[1] if len(sys.argv) > 1 else "tools/vlp_expected.json")
