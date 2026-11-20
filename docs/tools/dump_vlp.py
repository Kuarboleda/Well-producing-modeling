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
import well as wellmod                                # noqa: E402

warnings.simplefilter("ignore")


def conditions(v_sl, v_sg, rho_l=52.0, rho_g=2.5, mu_l=1.2, mu_g=0.018, sigma=20.0,
               frac_w=0.0, glr=500.0):
    """One set of flow conditions, in the shape the gradient functions expect."""
    return {"v_sl": v_sl, "v_sg": v_sg, "rho_l": rho_l, "rho_g": rho_g, "mu_l": mu_l,
            "mu_g": mu_g, "sigma": sigma, "frac_w": frac_w, "glr": glr}


# ---------------------------------------------------------------------
# The traverse takes a Well and a Fluid object, which cannot go into JSON as they are.  They are
# written out as plain dictionaries with a "kind" tag, and crosscheck.mjs builds the JavaScript
# objects back from exactly the same numbers.
# ---------------------------------------------------------------------

def well_spec(md, tvd, tubing, t_reservoir, roughness_in=0.0006, ambient_table=None):
    return {"kind": "well", "md": md, "tvd": tvd, "tubing": tubing,
            "t_reservoir": t_reservoir, "roughness_in": roughness_in,
            "ambient_table": ambient_table}


def oil_spec(**kw):
    return {"kind": "oil", **kw}


def gas_spec(**kw):
    return {"kind": "gas", **kw}


def build(spec):
    """Turn one of those dictionaries back into the Python object."""
    kind = spec["kind"]
    rest = {k: v for k, v in spec.items() if k != "kind"}
    if kind == "well":
        return wellmod.Well(md=rest["md"], tvd=rest["tvd"],
                            tubing=[tuple(t) for t in rest["tubing"]],
                            t_reservoir=rest["t_reservoir"],
                            roughness_in=rest["roughness_in"],
                            ambient_table=([tuple(r) for r in rest["ambient_table"]]
                                           if rest["ambient_table"] else None))
    if kind == "oil":
        return vlp.OilWaterFluid(**rest)
    if kind == "gas":
        return vlp.GasFluid(**rest)
    raise ValueError(f"unknown spec kind {kind}")


OBJECT_ARGS = {"pressure_traverse": (0, 1), "vlp_curve": (0, 1),
               "fluid_conditions": (0,), "fluid_thermal": (0,)}


def fluid_conditions(fluid, rate, p, T, d_in, inj_scfd=None):
    """conditions() reached through one positional call, so the dump and the cross-check agree."""
    if inj_scfd is None:
        return fluid.conditions(rate, p, T, d_in)
    return fluid.conditions(rate, p, T, d_in, inj_scfd=inj_scfd)


def fluid_thermal(fluid, rate):
    """[mass rate lb/h, cp] plus the gas lift gas when there is any."""
    out = list(fluid.thermal_data(rate))
    if getattr(fluid, "injection_gas_rate", 0.0) > 0.0:
        out.extend(fluid.injected_thermal())
    return out


EXTRA_FUNCS = {"fluid_conditions": fluid_conditions, "fluid_thermal": fluid_thermal,
               "build_steps": wellmod.build_steps, "fluid_temperatures": wellmod.fluid_temperatures,
               "tvd_at": wellmod.tvd_at, "ambient_at": wellmod.ambient_at,
               "parse_survey_text": wellmod.parse_survey_text}


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

    # ---- Ansari et al. (1994) ----------------------------------------
    # The four flow patterns, the two single-phase ends, and the developing/developed slug blend.
    for v_sl in (0.0, 1e-9, 0.01, 0.2, 1.5, 6.0, 25.0):
        for v_sg in (0.0, 1e-9, 0.02, 0.3, 3.0, 20.0, 120.0, 600.0):
            if v_sl + v_sg <= 0:
                continue
            for angle in (90.0, 55.0, 15.0):            # the model is for upward flow
                out.append(("ansari_gradient", "ansari_gradient",
                            [1200.0, angle, 2.441, 0.0006, conditions(v_sl, v_sg)]))
    # a spread of fluids and pipes, to reach every branch of the pattern map and both slug forms
    for _ in range(2500):
        out.append(("ansari_gradient_random", "ansari_gradient",
                    [10 ** random.uniform(1.3, 4.0),
                     random.uniform(1.0, 90.0),
                     random.uniform(1.0, 7.0),
                     random.choice([0.0, 0.0006, 0.002, 0.06]),
                     conditions(10 ** random.uniform(-4, 1.4), 10 ** random.uniform(-4, 2.4),
                                random.uniform(40.0, 70.0), random.uniform(0.2, 20.0),
                                10 ** random.uniform(-1, 2), random.uniform(0.01, 0.04),
                                random.uniform(1.0, 70.0))]))
    # the pieces on their own, so a disagreement can be placed
    for v_sl in (0.05, 0.5, 3.0, 20.0):
        for v_sg in (0.05, 0.5, 5.0, 50.0, 300.0):
            for d_ft in (0.0829, 0.2034, 0.5):
                args = [v_sl, v_sg, 52.0, 2.5, 1.2, 0.018, 20.0 * 0.0022046, d_ft, 0.0024,
                        math.radians(90.0)]
                out.append(("ans_flow_pattern", "ans_flow_pattern", args))
                out.append(("ans_annular_film_thickness", "ans_annular_film_thickness", args))
                out.append(("ans_slug", "_ans_slug", args[:9]))
    # the film-instability solve and the blend, over their whole range
    for y_m in (-5.0, 0.0, 1e-3, 0.5, 20.0, 5000.0):
        for x_m2 in (0.0, 1e-6, 0.01, 1.0, 100.0):
            out.append(("ans_film_instability", "_ans_film_instability", [y_m, x_m2]))
    for ratio in (0.5, 1.0, 1.0001, 1.1, 1.25, 1.4999, 1.5, 3.0):
        out.append(("ans_blend", "_ans_blend", [ratio]))

    # ---- Mukherjee & Brill (1983 / 1985) ------------------------------
    # every branch of Fig. 16: uphill, horizontal and downhill, including stratified flow
    for v_sl in (0.0, 1e-9, 0.02, 0.4, 2.0, 10.0, 40.0):
        for v_sg in (0.0, 1e-9, 0.05, 0.8, 8.0, 80.0, 400.0):
            if v_sl + v_sg <= 0:
                continue
            for angle in (90.0, 45.0, 5.0, 0.0, -5.0, -45.0, -90.0):
                out.append(("mukherjee_brill_gradient", "mukherjee_brill_gradient",
                            [1200.0, angle, 2.441, 0.0006, conditions(v_sl, v_sg)]))
    for _ in range(2500):
        out.append(("mukherjee_brill_gradient_random", "mukherjee_brill_gradient",
                    [10 ** random.uniform(1.3, 4.0),
                     random.uniform(-90.0, 90.0),
                     random.uniform(1.0, 7.0),
                     random.choice([0.0, 0.0006, 0.002, 0.06]),
                     conditions(10 ** random.uniform(-4, 1.4), 10 ** random.uniform(-4, 2.4),
                                random.uniform(40.0, 70.0), random.uniform(0.2, 20.0),
                                10 ** random.uniform(-1, 2), random.uniform(0.01, 0.04),
                                random.uniform(1.0, 70.0))]))
    # the pieces on their own
    for v_sl in (0.05, 0.5, 3.0, 20.0):
        for v_sg in (0.05, 0.5, 5.0, 50.0, 300.0):
            out.append(("mb_numbers", "mb_numbers", [v_sl, v_sg, 52.0, 20.0, 1.2]))
    for n_lv in (0.01, 0.5, 5.0, 50.0):
        for n_gv in (0.01, 0.5, 5.0, 50.0, 500.0):
            for n_l in (0.002, 0.05, 1.0):
                for angle in (90.0, 31.0, 30.0, 1.0, 0.0, -1.0, -30.0, -31.0, -90.0):
                    out.append(("mb_flow_pattern", "mb_flow_pattern", [n_lv, n_gv, n_l, angle]))
                    for regime in ("slug", "stratified"):
                        out.append(("mb_holdup", "mb_holdup", [n_lv, n_gv, n_l, angle, regime]))
    for h_l in (1e-6, 0.01, 0.1, 0.35, 0.5, 0.8, 0.999999):
        out.append(("mb_stratified_angle", "mb_stratified_angle", [h_l]))
        for v_sg in (0.5, 5.0, 50.0):
            out.append(("mb_stratified_friction", "mb_stratified_friction",
                        [h_l, v_sg, 2.5, 0.018, 0.2034, 0.00025]))

    # ---- Fancher & Brown (1963) ---------------------------------------
    for glr in (0.0, 100.0, 1499.9, 1500.0, 2000.0, 3000.0, 3000.1, 9000.0):
        for n_re in (0.5, 3.4, 3.7, 4.7, 5.3, 6.0, 7.0, 15.0, 23.0, 27.0, 35.0, 50.0, 70.0, 500.0):
            out.append(("fb_friction_factor", "fb_friction_factor", [n_re, glr]))
        out.append(("fb_glr_band", "fb_glr_band", [glr]))
    for v_sl in (0.01, 0.3, 2.0, 15.0):
        for v_sg in (0.0, 0.05, 1.0, 10.0, 100.0):
            for glr in (200.0, 2000.0, 20000.0):
                out.append(("fancher_brown_gradient", "fancher_brown_gradient",
                            [1200.0, 90.0, 2.441, 0.0006, conditions(v_sl, v_sg, glr=glr)]))
    for _ in range(800):
        out.append(("fancher_brown_gradient_random", "fancher_brown_gradient",
                    [10 ** random.uniform(1.3, 4.0),
                     random.uniform(-90.0, 90.0),
                     random.uniform(1.0, 7.0),
                     0.0006,
                     conditions(10 ** random.uniform(-3, 1.4), 10 ** random.uniform(-3, 2.4),
                                random.uniform(40.0, 70.0), random.uniform(0.2, 20.0),
                                10 ** random.uniform(-1, 2), random.uniform(0.01, 0.04),
                                random.uniform(1.0, 70.0), 0.0,
                                10 ** random.uniform(1, 4.5))]))

    # ---- well.py: the survey, the steps and the temperature profile ----
    VERT = well_spec([0.0, 8000.0], [0.0, 8000.0], [[0.0, 8000.0, 2.992]], 200.0)
    DEV = well_spec([0.0, 2000.0, 6000.0, 9000.0], [0.0, 2000.0, 5500.0, 7000.0],
                    [[0.0, 9000.0, 2.992]], 210.0)
    TWO_TUBE = well_spec([0.0, 3000.0, 9000.0], [0.0, 3000.0, 8200.0],
                         [[0.0, 4000.0, 3.958], [4000.0, 9000.0, 2.441]], 220.0)
    TOE_UP = well_spec([0.0, 5000.0, 7000.0, 9000.0], [0.0, 5000.0, 6500.0, 6400.0],
                       [[0.0, 9000.0, 2.992]], 200.0, 0.0012,
                       [[0.0, 70.0, 4.0], [4000.0, 120.0, 6.0], [9000.0, 200.0, 5.0]])
    for w in (VERT, DEV, TWO_TUBE, TOE_UP):
        for step_ft in (50.0, 100.0, 237.0, 1000.0, 20000.0):
            out.append(("build_steps", "build_steps", [w, step_ft]))
        out.append(("build_steps_breaks", "build_steps", [w, 100.0, [1234.0, 6000.0]]))
        for md in (0.0, 1.0, 1999.9, 2000.0, 4500.0, 7999.0, 1e6):
            out.append(("tvd_at", "tvd_at", [w, md]))
            out.append(("ambient_at", "ambient_at", [w, md]))
        steps = wellmod.build_steps(build(w), 100.0)
        for mass, cp_ in ((1000.0, 0.5), (50000.0, 0.62), (1.0, 1.0), (0.0, 0.5)):
            out.append(("fluid_temperatures", "fluid_temperatures", [w, steps, mass, cp_]))
        # one value per step, as gas lift makes it
        masses = [2000.0 if k < len(steps) // 2 else 1500.0 for k in range(len(steps))]
        cps = [0.55 if k < len(steps) // 2 else 0.5 for k in range(len(steps))]
        out.append(("fluid_temperatures_list", "fluid_temperatures", [w, steps, masses, cps]))
    for text in ("0 0\n2000 2000\n6000 5500\n9000 7000",
                 "MD\tTVD\n0,0\n1000;1000\n 5000  4800 \n",
                 "0 0\nrubbish\n\n3000 2900"):
        out.append(("parse_survey_text", "parse_survey_text", [text]))

    # ---- the fluid objects --------------------------------------------
    OIL = oil_spec(api=35.0, gas_sg=0.75, rsb=500.0, water_cut=0.3)
    OIL_DRY = oil_spec(api=22.0, gas_sg=0.65, rsb=200.0, water_cut=0.0, gor=350.0,
                       pvt_method="standing", visc_method="beggs")
    OIL_WET = oil_spec(api=45.0, gas_sg=0.85, rsb=900.0, water_cut=0.95, salinity=12.0,
                       pb_meas=2600.0, pvt_method="petrosky", visc_method="petrosky")
    OIL_GL = oil_spec(api=30.0, gas_sg=0.7, rsb=400.0, water_cut=0.5,
                      injection_gas_rate=1500.0, injection_md=6000.0, injection_gas_sg=0.62)
    GAS_DRY = gas_spec(gas_sg=0.65)
    GAS_WET = gas_spec(gas_sg=0.72, cgr=25.0, cond_api=52.0, wgr=3.0, y_h2s=0.02, y_co2=0.05,
                       visc_method="carr")
    for f in (OIL, OIL_DRY, OIL_WET, OIL_GL):
        for rate in (10.0, 500.0, 3000.0, 20000.0):
            for p in (50.0, 500.0, 2000.0, 6000.0):
                for T in (80.0, 150.0, 240.0):
                    out.append(("fluid_conditions_oil", "fluid_conditions", [f, rate, p, T, 2.992]))
            out.append(("fluid_thermal_oil", "fluid_thermal", [f, rate]))
        for inj in (1.0, 1.5e6):
            out.append(("fluid_conditions_oil_gl", "fluid_conditions",
                        [f, 1200.0, 900.0, 160.0, 2.992, inj]))
    for f in (GAS_DRY, GAS_WET):
        for rate in (100.0, 5000.0, 50000.0):
            for p in (50.0, 500.0, 2000.0, 6000.0):
                for T in (80.0, 150.0, 240.0):
                    out.append(("fluid_conditions_gas", "fluid_conditions", [f, rate, p, T, 2.441]))
            out.append(("fluid_thermal_gas", "fluid_thermal", [f, rate]))

    # ---- the pressure traverse ----------------------------------------
    # Every correlation on every well shape, plus gas lift, a gas well, and the VLP multipliers.
    for corr in ("beggs_brill", "hagedorn_brown", "gray", "orkiszewski", "ansari", "duns_ros",
                 "mukherjee_brill", "fancher_brown"):
        for w in (VERT, DEV, TWO_TUBE, TOE_UP):
            for rate in (200.0, 2000.0, 12000.0):
                out.append(("pressure_traverse", "pressure_traverse",
                            [w, OIL, rate, 214.7, corr, 100.0, 1.0, 1.0]))
        out.append(("pressure_traverse_wet", "pressure_traverse",
                    [DEV, OIL_WET, 4000.0, 314.7, corr, 100.0, 1.0, 1.0]))
        out.append(("pressure_traverse_gaslift", "pressure_traverse",
                    [DEV, OIL_GL, 1500.0, 214.7, corr, 100.0, 1.0, 1.0]))
        out.append(("pressure_traverse_gas", "pressure_traverse",
                    [TWO_TUBE, GAS_WET, 8000.0, 514.7, corr, 100.0, 1.0, 1.0]))
        out.append(("pressure_traverse_drygas", "pressure_traverse",
                    [VERT, GAS_DRY, 15000.0, 414.7, corr, 100.0, 1.0, 1.0]))
        out.append(("pressure_traverse_mult", "pressure_traverse",
                    [VERT, OIL, 2000.0, 214.7, corr, 100.0, 0.85, 1.4]))
        out.append(("pressure_traverse_step50", "pressure_traverse",
                    [VERT, OIL, 2000.0, 214.7, corr, 50.0, 1.0, 1.0]))
        out.append(("vlp_curve", "vlp_curve",
                    [VERT, OIL, [100.0, 800.0, 2500.0, 8000.0, 25000.0], 214.7, corr, 100.0, 1.0, 1.0]))

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
    if func_name in OBJECT_ARGS:
        args = [build(a) if i in OBJECT_ARGS[func_name] else a for i, a in enumerate(args)]
    elif func_name in ("build_steps", "fluid_temperatures", "tvd_at", "ambient_at"):
        args = [build(args[0]) if isinstance(args[0], dict) and args[0].get("kind") == "well" else args[0],
                *args[1:]]
    func = EXTRA_FUNCS.get(func_name) or getattr(vlp, func_name)
    value = func(*args)
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
