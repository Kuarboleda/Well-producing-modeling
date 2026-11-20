"""
dump_nodal.py - run nodal analysis cases through the PYTHON engine and write the answers to JSON.

The JavaScript side (tools/crosscheck.mjs) feeds the same inputs to nodal.js and compares.

Where the Python takes the IPR as a FUNCTION (ipr.oil_pi), the JavaScript takes its NAME
("oil_pi"), so every case here carries the name and this file looks the function up.  Wells and
fluids travel as plain dictionaries tagged with a "kind", exactly as in dump_vlp.py, and both sides
build their own objects from the same numbers.

Run from the docs/ folder:   python3 tools/dump_nodal.py tools/nodal_expected.json
"""
import json
import sys
import warnings

sys.path.insert(0, "..")
import ipr                                            # noqa: E402
import nodal                                          # noqa: E402
import vlp                                            # noqa: E402
import well as wellmod                                # noqa: E402

warnings.simplefilter("ignore")


def well_spec(md, tvd, tubing, t_reservoir, roughness_in=0.0006, ambient_table=None):
    return {"kind": "well", "md": md, "tvd": tvd, "tubing": tubing,
            "t_reservoir": t_reservoir, "roughness_in": roughness_in,
            "ambient_table": ambient_table}


def oil_spec(**kw):
    return {"kind": "oil", **kw}


def gas_spec(**kw):
    return {"kind": "gas", **kw}


def build(spec):
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


# ---------------------------------------------------------------------
# The wells, fluids and IPRs used below
# ---------------------------------------------------------------------
VERT = well_spec([0.0, 8000.0], [0.0, 8000.0], [[0.0, 8000.0, 2.992]], 200.0)
DEV = well_spec([0.0, 2000.0, 6000.0, 9000.0], [0.0, 2000.0, 5500.0, 7000.0],
                [[0.0, 9000.0, 2.992]], 210.0)
TWO_TUBE = well_spec([0.0, 3000.0, 9000.0], [0.0, 3000.0, 8200.0],
                     [[0.0, 4000.0, 3.958], [4000.0, 9000.0, 2.441]], 220.0)

OIL = oil_spec(api=35.0, gas_sg=0.75, rsb=500.0, water_cut=0.3)
OIL_WET = oil_spec(api=45.0, gas_sg=0.85, rsb=900.0, water_cut=0.9, salinity=12.0)
OIL_GL = oil_spec(api=30.0, gas_sg=0.7, rsb=400.0, water_cut=0.5,
                  injection_gas_rate=1200.0, injection_md=6000.0, injection_gas_sg=0.62)
GAS_DRY = gas_spec(gas_sg=0.65)
GAS_WET = gas_spec(gas_sg=0.72, cgr=25.0, cond_api=52.0, wgr=3.0, gas_sg_dry=0.65)

# the layer shape the ENGINE wants (p_res and J for oil; p_res and C, n for gas), with the produced
# fluid of each layer so that the well-stream mixture changes with the rate
OIL_LAYERS = [{"p_res": 3014.7, "J": 2.0, "gor": 400.0, "wc": 20.0},
              {"p_res": 2814.7, "J": 1.5, "gor": 500.0, "wc": 30.0},
              {"p_res": 2514.7, "J": 1.0, "gor": 600.0, "wc": 50.0}]
GAS_LAYERS = [{"p_res": 3014.7, "C": 0.015, "n": 0.85, "cgr": 10.0, "wgr": 1.0},
              {"p_res": 2814.7, "C": 0.010, "n": 0.85, "cgr": 25.0, "wgr": 2.0},
              {"p_res": 2514.7, "C": 0.006, "n": 0.85, "cgr": 40.0, "wgr": 5.0}]

IPR_FUNCS = {name: getattr(ipr, name) for name in
             ("oil_pi", "oil_vogel", "oil_darcy", "oil_fetkovich", "oil_multilayer",
              "gas_jones", "gas_darcy", "gas_backpressure", "gas_multilayer")}

OIL_CASES = [
    ("oil_pi", {"pb": 2498.4, "J": 3.0}),
    ("oil_vogel", {"pb": 2498.4, "q_test": 1500.0, "pwf_test": 1114.7}),
    ("oil_darcy", {"pb": 2498.4, "k": 50.0, "h": 20.0, "bo": 1.25, "mu": 0.8, "re": 1000.0,
                   "rw": 0.354, "skin": 0.0}),
    ("oil_fetkovich", {"q1": 1000.0, "pwf1": 2514.7, "q2": 2000.0, "pwf2": 1814.7}),
]
GAS_CASES = [
    ("gas_jones", {"temp_f": 220.0, "k": 5.0, "h": 40.0, "mu": 0.02, "z": 0.95, "re": 1000.0,
                   "rw": 0.354, "skin": 0.0, "gas_sg": 0.72}),
    ("gas_darcy", {"temp_f": 220.0, "k": 5.0, "h": 40.0, "mu": 0.02, "z": 0.95, "re": 1000.0,
                   "rw": 0.354, "skin": 0.0}),
    ("gas_backpressure", {"C": 0.015, "n": 0.85}),
]


def cases():
    """Every case: a name, the function to call, and its arguments."""
    out = []

    # ---- find_operating_point on its own, with curves given as numbers ----
    # The two curves are handed over as (slope, intercept) pairs so that both languages can build
    # exactly the same functions without passing code: a straight IPR and a J-shaped VLP.
    for aof, pr in ((5000.0, 3014.7), (800.0, 2014.7)):
        for a, b, c in ((2.0e-4, -0.6, 900.0), (1.0e-4, -0.1, 1500.0), (5.0e-5, 0.3, 2600.0)):
            out.append(("find_operating_point", "find_operating_point_demo",
                        [aof, pr, a, b, c, 30, 0.01]))

    # ---- the whole chain -------------------------------------------------
    for corr in ("beggs_brill", "hagedorn_brown", "gray", "orkiszewski", "ansari", "duns_ros",
                 "mukherjee_brill", "fancher_brown"):
        for name, inputs in OIL_CASES:
            out.append(("solve_well_oil", "solve_well",
                        [VERT, OIL, name, 3014.7, inputs, 214.7, corr, 100.0, 20, 1.0, 1.0]))
        for name, inputs in GAS_CASES:
            out.append(("solve_well_gas", "solve_well",
                        [TWO_TUBE, GAS_WET, name, 3014.7, inputs, 514.7, corr, 100.0, 20, 1.0, 1.0]))
        out.append(("solve_well_dev", "solve_well",
                    [DEV, OIL_WET, "oil_pi", 3014.7, {"pb": 2498.4, "J": 6.0}, 314.7, corr,
                     100.0, 20, 1.0, 1.0]))
        out.append(("solve_well_gaslift", "solve_well",
                    [DEV, OIL_GL, "oil_pi", 3014.7, {"pb": 2498.4, "J": 2.0}, 214.7, corr,
                     100.0, 20, 1.0, 1.0]))
        out.append(("solve_well_mult", "solve_well",
                    [VERT, OIL, "oil_pi", 3014.7, {"pb": 2498.4, "J": 3.0}, 214.7, corr,
                     100.0, 20, 0.9, 1.3]))
        out.append(("solve_well_nonflowing", "solve_well",
                    [VERT, OIL, "oil_pi", 1014.7, {"pb": 900.0, "J": 0.05}, 714.7, corr,
                     100.0, 20, 1.0, 1.0]))
        out.append(("curves_oil", "curves",
                    [VERT, OIL, "oil_pi", 3014.7, {"pb": 2498.4, "J": 3.0}, 214.7, corr, 100.0,
                     11, 1.0, 1.0]))
        out.append(("curves_gas", "curves",
                    [TWO_TUBE, GAS_DRY, "gas_backpressure", 3014.7, {"C": 0.015, "n": 0.85},
                     514.7, corr, 100.0, 11, 1.0, 1.0]))

    # ---- multilayer: the produced fluid changes with the rate ------------
    for q in (200.0, 1500.0, 4000.0):
        out.append(("fluid_at_rate_oil", "fluid_at_rate_demo",
                    [OIL, "oil_multilayer", 3014.7,
                     {"pb": 2498.4, "layers": OIL_LAYERS, "crossflow": False}, q]))
    for q in (500.0, 5000.0, 20000.0):
        out.append(("fluid_at_rate_gas", "fluid_at_rate_demo",
                    [GAS_WET, "gas_multilayer", 3014.7,
                     {"layers": GAS_LAYERS, "crossflow": False}, q]))
    out.append(("solve_well_multilayer", "solve_well",
                [VERT, OIL, "oil_multilayer", 3014.7,
                 {"pb": 2498.4, "layers": OIL_LAYERS, "crossflow": False}, 214.7,
                 "beggs_brill", 100.0, 20, 1.0, 1.0]))
    out.append(("curves_multilayer", "curves",
                [VERT, OIL, "oil_multilayer", 3014.7,
                 {"pb": 2498.4, "layers": OIL_LAYERS, "crossflow": False}, 214.7,
                 "beggs_brill", 100.0, 9, 1.0, 1.0]))

    # ---- VLP matching ---------------------------------------------------
    for corr in ("beggs_brill", "hagedorn_brown", "duns_ros"):
        for pwf_meas in (2400.0, 2600.0, 2800.0):
            for fit in ("friction", "gravity"):
                out.append(("match_vlp_multiplier", "match_vlp_multiplier",
                            [VERT, OIL, 2000.0, 214.7, pwf_meas, corr, 100.0, fit, 0.5, 2.0,
                             14.7, "psig"]))
        for fit in ("both", "friction", "gravity"):
            out.append(("match_vlp_survey", "match_vlp_survey",
                        [VERT, OIL, 2000.0, 214.7, [2000.0, 5000.0, 8000.0],
                         [800.0, 1700.0, 2500.0], corr, 100.0, fit, 0.5, 2.0]))
        out.append(("match_vlp_survey_one", "match_vlp_survey",
                    [VERT, OIL, 2000.0, 214.7, [8000.0], [2500.0], corr, 100.0, "friction",
                     0.5, 2.0]))

    # ---- sensitivities --------------------------------------------------
    base = [VERT, OIL, "oil_pi", 3014.7, {"pb": 2498.4, "J": 3.0}, 214.7, "beggs_brill",
            100.0, 20, 1.0, 1.0]
    out.append(("sensitivity_pwh", "sensitivity_demo", [base, "p_wh", [114.7, 214.7, 414.7], False, 9]))
    out.append(("sensitivity_j", "sensitivity_demo", [base, "ipr_inputs.J", [1.0, 3.0, 8.0], False, 9]))
    out.append(("sensitivity_wc", "sensitivity_demo",
                [base, "fluid.water_cut", [0.0, 0.3, 0.9], False, 9]))
    out.append(("sensitivity_curves", "sensitivity_demo",
                [base, "p_wh", [114.7, 414.7], True, 9]))
    out.append(("sensitivity_tubing", "sensitivity_tubing_demo",
                [base, [2.441, 2.992, 3.958], 9]))
    for id_in in (2.441, 3.958):
        out.append(("well_with_tubing_id", "well_with_tubing_id_demo", [VERT, id_in]))

    return out


# ---------------------------------------------------------------------
# The demo wrappers: they turn the plain numbers above into the objects and functions that nodal.py
# wants, and return plain numbers again.  crosscheck.mjs has one of each with the same name.
# ---------------------------------------------------------------------

def find_operating_point_demo(aof, pr, a, b, c, n_grid, q_min_frac):
    """A straight IPR of the given AOF and a J-shaped VLP pwf = a q^2 + b q + c."""
    def q_ipr(pwf):
        return aof * (1.0 - pwf / pr)

    def pwf_vlp(q):
        return a * q * q + b * q + c

    return nodal.find_operating_point(q_ipr, pwf_vlp, n_grid=n_grid, q_min_frac=q_min_frac)


def fluid_at_rate_demo(fluid_spec, ipr_name, p_res, ipr_inputs, q):
    """fluid_at_rate(), reporting the fields that can change so they can be compared as numbers."""
    f = nodal.fluid_at_rate(build(fluid_spec), IPR_FUNCS[ipr_name], p_res, ipr_inputs, q)
    if ipr_name == "gas_multilayer":
        return {"cgr": f.cgr, "wgr": f.wgr, "gas_sg": f.gas_sg}
    return {"water_cut": f.water_cut, "gor": f.gor}


def base_kwargs(base):
    well_s, fluid_s, ipr_name, p_res, ipr_inputs, p_wh, corr, step, n_grid, gm, fm = base
    return {"well": build(well_s), "fluid": build(fluid_s), "ipr_function": IPR_FUNCS[ipr_name],
            "p_res": p_res, "ipr_inputs": dict(ipr_inputs), "p_wh": p_wh, "correlation": corr,
            "max_step_ft": step, "n_grid": n_grid, "gravity_mult": gm, "friction_mult": fm}


def sensitivity_demo(base, name, values, with_curves, n_points):
    return nodal.sensitivity(base_kwargs(base), name, values, with_curves, n_points)


def sensitivity_tubing_demo(base, ids, n_points):
    """The tubing-size sensitivity: each value is a whole new Well, so the rows carry the diameter
    instead of the well itself (a Well does not fit in JSON, and the diameter is what identifies the
    run anyway)."""
    kwargs = base_kwargs(base)
    wells = [nodal.well_with_tubing_id(kwargs["well"], d) for d in ids]
    rows = nodal.sensitivity(kwargs, "well", wells, False, n_points)
    for row, d in zip(rows, ids):
        row["value"] = d
    return rows


def well_with_tubing_id_demo(well_s, id_in):
    w = nodal.well_with_tubing_id(build(well_s), id_in)
    return {"md": list(w.md), "tvd": list(w.tvd), "tubing": [list(t) for t in w.tubing],
            "t_reservoir": w.t_reservoir, "roughness_in": w.roughness_in,
            "ambient_table": [list(r) for r in w.ambient_table]}


OBJECT_ARGS = {"solve_well": (0, 1), "curves": (0, 1), "match_vlp_multiplier": (0, 1),
               "match_vlp_survey": (0, 1)}
IPR_NAME_ARG = {"solve_well": 2, "curves": 2}

DEMOS = {"find_operating_point_demo": find_operating_point_demo,
         "fluid_at_rate_demo": fluid_at_rate_demo,
         "sensitivity_demo": sensitivity_demo,
         "sensitivity_tubing_demo": sensitivity_tubing_demo,
         "well_with_tubing_id_demo": well_with_tubing_id_demo}


def run_one(func_name, args):
    if func_name in DEMOS:
        return DEMOS[func_name](*args)
    args = list(args)
    for i in OBJECT_ARGS.get(func_name, ()):
        args[i] = build(args[i])
    if func_name in IPR_NAME_ARG:
        args[IPR_NAME_ARG[func_name]] = IPR_FUNCS[args[IPR_NAME_ARG[func_name]]]
    value = getattr(nodal, func_name)(*args)
    if isinstance(value, tuple):
        return list(value)
    return value


def main(path):
    rows, skipped = [], 0
    for name, func_name, args in cases():
        try:
            rows.append({"name": name, "func": func_name, "args": args,
                         "want": run_one(func_name, args)})
        except (ValueError, ZeroDivisionError, OverflowError, RuntimeError, NotImplementedError) as err:
            # a case the Python itself refuses is left out, and the reason is kept so the two sides
            # can be compared on what IS calculable
            rows.append({"name": name, "func": func_name, "args": args,
                         "want": {"error": type(err).__name__}})
            skipped += 1
    with open(path, "w") as handle:
        json.dump(rows, handle)
    print(f"{len(rows)} cases written to {path} ({skipped} of them refused by the Python)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tools/nodal_expected.json")
