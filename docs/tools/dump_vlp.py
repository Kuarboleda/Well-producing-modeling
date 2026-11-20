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

    # ---- Hagedorn and Brown: the three chart fits on their own -------
    for n_l in (0.0, 1e-4, 0.002, 0.05, 0.2, 0.5, 0.8, 5.0):
        out.append(("hb_cn_l", "hb_cn_l", [n_l]))
    # H spans the power-law piece below 1e-5, the join, and the fit above it
    for h in (0.0, 1e-9, 1e-7, 9.9e-6, 1e-5, 1.1e-5, 1e-4, 0.002, 0.05, 0.5, 5.0, 100.0):
        out.append(("hb_holdup_over_psi", "hb_holdup_over_psi", [h]))
    # B spans all three pieces and both joins
    for b in (0.0, 0.005, 0.0249, 0.025, 0.0251, 0.04, 0.0549, 0.055, 0.0551, 0.1, 0.5, 3.0):
        out.append(("hb_psi", "hb_psi", [b]))
    for v_m in (0.1, 1.0, 5.0, 40.0):
        for v_sg in (0.0, 0.05, 0.5, 2.0):
            if v_sg <= v_m:
                out.append(("griffith_bubble_holdup", "griffith_bubble_holdup", [v_m, v_sg]))
    for p in (50.0, 1500.0, 9000.0):
        for d_ft in (0.1, 0.2493, 0.5):
            for v_sl, v_sg in ((0.5, 2.0), (0.01, 40.0), (5.0, 0.2)):
                out.append(("hb_numbers", "hb_numbers", [p, d_ft, conditions(v_sl, v_sg)]))

    # ---- Hagedorn and Brown and Gray: the whole gradient -------------
    # The velocities walk from bubble flow (little gas) through to mist (almost all gas),
    # so both the Griffith branch and the chart branch are exercised.
    for name, func in (("hagedorn_brown_gradient", "hagedorn_brown_gradient"),
                       ("gray_gradient", "gray_gradient")):
        for v_sl in (0.0, 1e-9, 0.001, 0.05, 0.5, 3.0, 20.0):
            for v_sg in (0.0, 1e-9, 0.02, 0.4, 4.0, 40.0, 200.0):
                if v_sl + v_sg <= 0:
                    continue
                for angle in (90.0, 60.0, 15.0, 0.0, -45.0):
                    out.append((name, func, [1200.0, angle, 2.441, 0.0006, conditions(v_sl, v_sg)]))
        for d_in in (1.995, 2.992, 5.0):
            for rho_l, mu_l, sigma in ((45.0, 0.4, 8.0), (62.4, 0.6, 60.0), (55.0, 40.0, 25.0)):
                for rho_g, mu_g in ((0.5, 0.011), (6.0, 0.022)):
                    for p in (80.0, 2500.0, 9000.0):
                        out.append((name, func, [p, 90.0, d_in, 0.0006,
                                                 conditions(0.3, 6.0, rho_l, rho_g, mu_l, mu_g, sigma)]))
        for _ in range(1500):
            out.append((name + "_random", func,
                        [10 ** random.uniform(1.3, 4.0),
                         random.uniform(-90.0, 90.0),
                         random.uniform(1.0, 7.0),
                         random.choice([0.0, 0.0006, 0.002]),
                         conditions(10 ** random.uniform(-4, 1.4), 10 ** random.uniform(-4, 2.3),
                                    random.uniform(40.0, 70.0), random.uniform(0.2, 20.0),
                                    10 ** random.uniform(-1, 2), random.uniform(0.01, 0.04),
                                    random.uniform(1.0, 70.0))]))

    # ---- Orkiszewski: each piece and every flow pattern ---------------
    for rho_l in (45.0, 62.4):
        for mu_l in (0.3, 2.0, 50.0):
            for d_ft in (0.1, 0.2035, 0.2493, 0.5):
                for v_t in (0.2, 2.0, 9.9, 10.0, 10.1, 40.0, 150.0):
                    out.append(("ork_bubble_rise_velocity", "ork_bubble_rise_velocity",
                                [rho_l, mu_l, d_ft, v_t]))
                    for wc in (True, False):
                        out.append(("ork_gamma", "ork_gamma", [mu_l, d_ft, v_t, wc]))
    for v_sl in (0.01, 0.3, 3.0, 20.0):
        for v_sg in (0.001, 0.2, 3.0, 30.0, 200.0):
            for d_ft in (0.1, 0.2493, 0.5):
                out.append(("ork_flow_regime", "ork_flow_regime",
                            [v_sl, v_sg, 52.0, 20.0 * 0.0022046, d_ft]))
    # the whole gradient: the velocities walk through bubble, slug, transition and mist,
    # and frac_w switches the continuous liquid phase for Gamma
    for frac_w in (0.0, 0.3, 0.5, 0.9):
        for v_sl in (0.0, 1e-9, 0.002, 0.08, 0.8, 5.0, 25.0):
            for v_sg in (0.0, 1e-9, 0.03, 0.5, 5.0, 50.0, 250.0):
                if v_sl + v_sg <= 0:
                    continue
                for angle in (90.0, 45.0, 0.0):
                    out.append(("orkiszewski_gradient", "orkiszewski_gradient",
                                [1200.0, angle, 2.441, 0.0006,
                                 conditions(v_sl, v_sg, frac_w=frac_w)]))
    for _ in range(2000):
        out.append(("orkiszewski_gradient_random", "orkiszewski_gradient",
                    [10 ** random.uniform(1.3, 4.0),
                     random.uniform(-90.0, 90.0),
                     random.uniform(1.0, 7.0),
                     random.choice([0.0, 0.0006, 0.002]),
                     conditions(10 ** random.uniform(-4, 1.4), 10 ** random.uniform(-4, 2.3),
                                random.uniform(40.0, 70.0), random.uniform(0.2, 20.0),
                                10 ** random.uniform(-1, 2), random.uniform(0.01, 0.04),
                                random.uniform(1.0, 70.0), random.choice([0.0, 0.4, 0.6, 1.0]))]))

    # ---- Duns and Ros: the chart tables, the slip laws and the regions -
    for n_l in (0.001, 0.002, 0.0035, 0.02, 0.0529, 0.2399, 0.8453, 1.8, 3.0):
        for n in (0.0, 0.5, 5.0, 50.0):
            for rn in (0.1, 5.0, 60.0, 400.0):
                for n_d in (10.0, 50.0, 102.6, 260.0, 500.0):
                    out.append(("dr_slip_region1", "dr_slip_region1", [n, rn, n_d, n_l]))
                    out.append(("dr_slip_region2", "dr_slip_region2", [n, rn, n_d, n_l]))
    for n in (0.0, 0.1, 1.0, 10.0, 100.0):
        out.append(("dr_region_limits", "dr_region_limits", [n]))
    for v_sl in (0.01, 0.5, 4.0, 30.0):
        for v_sg in (0.005, 0.3, 4.0, 40.0, 300.0):
            for d_ft in (0.1, 0.2493, 0.6):
                out.append(("dr_numbers", "dr_numbers", [v_sl, v_sg, 52.0, 20.0, 1.2, d_ft]))
                out.append(("dr_flow_region", "dr_flow_region", [v_sl, v_sg, 52.0, 20.0, 1.2, d_ft]))
            for s_ in (-2.0, 0.0, 0.5, 5.0, 50.0):
                out.append(("dr_holdup", "dr_holdup", [v_sl, v_sg, s_, 4.0]))
    for v_sg in (0.5, 5.0, 60.0, 400.0):
        for mu_l in (0.2, 2.0, 60.0):
            for rho_g in (0.4, 3.0, 15.0):
                out.append(("dr_mist_film_roughness", "dr_mist_film_roughness",
                            [v_sg, rho_g, 52.0, mu_l, 20.0, 0.2493, 0.00025]))
    # the whole gradient: across all three regions and the transition between II and III
    for v_sl in (0.0, 1e-9, 0.003, 0.1, 1.0, 6.0, 30.0):
        for v_sg in (0.0, 1e-9, 0.04, 0.6, 6.0, 60.0, 300.0):
            if v_sl + v_sg <= 0:
                continue
            for angle in (90.0, 50.0, 0.0, -60.0):
                out.append(("duns_ros_gradient", "duns_ros_gradient",
                            [1200.0, angle, 2.441, 0.0006, conditions(v_sl, v_sg)]))
    for _ in range(2000):
        out.append(("duns_ros_gradient_random", "duns_ros_gradient",
                    [10 ** random.uniform(1.3, 4.0),
                     random.uniform(-90.0, 90.0),
                     random.uniform(1.0, 7.0),
                     random.choice([0.0, 0.0006, 0.002, 0.06]),      # 0.06 exercises Eq. 15
                     conditions(10 ** random.uniform(-4, 1.4), 10 ** random.uniform(-4, 2.3),
                                random.uniform(40.0, 70.0), random.uniform(0.2, 20.0),
                                10 ** random.uniform(-1, 2), random.uniform(0.01, 0.04),
                                random.uniform(1.0, 70.0))]))

    # ---- Gray's two pieces on their own ------------------------------
    for r in (1e-6, 0.001, 0.0069, 0.007, 0.0071, 0.05, 0.5, 5.0, 100.0):
        for n_v in (0.01, 1.0, 100.0, 1e4):
            for n_d in (1.0, 50.0, 500.0, 1e4):
                out.append(("gray_holdup", "gray_holdup", [r, n_v, n_d]))
        for rho_ns, v_m in ((1.0, 5.0), (30.0, 40.0), (0.3, 1.0)):
            out.append(("gray_effective_roughness", "gray_effective_roughness",
                        [r, 0.0006 / 12.0, 20.0 * 0.0022046, rho_ns, v_m]))
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
