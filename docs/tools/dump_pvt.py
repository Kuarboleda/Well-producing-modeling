"""
dump_pvt.py - run a large set of PVT cases through the PYTHON engine and write the answers to JSON.

This is half of the cross-check.  The other half (crosscheck.mjs) feeds the same inputs to the
JavaScript engine and compares, so the browser version is held against the Python version that was
checked against the papers.

Run from the docs/ folder:   PYTHONPATH=.. python3 tools/dump_pvt.py tools/pvt_expected.json
"""
import json
import math
import random
import sys

sys.path.insert(0, "..")
import pvt                                            # noqa: E402  (the Python engine)

PVT_METHODS = ("glaso", "standing", "lasater", "petrosky")
VISC_METHODS = ("beal", "beggs", "petrosky")
GAS_VISC = ("lee", "carr")


def cases():
    """Every case: a name, the function to call, and its arguments."""
    random.seed(20261120)                             # same list every run
    out = []

    # ---- the individual oil correlations, over a wide grid -----------
    for api in (12.0, 18.7, 25.0, 32.0, 40.0, 45.0, 55.0):
        for gg in (0.55, 0.65, 0.8, 1.1):
            for T in (90.0, 150.0, 200.0, 280.0):
                for rs in (20.0, 150.0, 575.0, 1200.0, 2500.0):
                    for m in PVT_METHODS:
                        out.append((f"pb_{m}", f"pb_{m}", [rs, gg, api, T]))
                        out.append((f"bo_{m}", f"bo_{m}", [rs, gg, api, T]))
                for p in (50.0, 500.0, 2000.0, 5000.0, 9000.0):
                    for m in PVT_METHODS:
                        out.append((f"rs_{m}", f"rs_{m}", [p, gg, api, T]))

    # ---- oil viscosity ----------------------------------------------
    for api in (12.0, 20.0, 30.0, 42.0):
        for T in (100.0, 180.0, 260.0):
            out.append(("mu_dead_beal", "mu_dead_beal", [api, T]))
            out.append(("mu_dead_beggs", "mu_dead_beggs", [api, T]))
            out.append(("mu_dead_petrosky", "mu_dead_petrosky", [api, T]))
            for rs in (0.0, 100.0, 600.0, 1800.0):
                mud = pvt.mu_dead_beal(api, T)
                out.append(("mu_live_chew_connally", "mu_live_chew_connally", [mud, rs]))
                out.append(("mu_live_beggs", "mu_live_beggs", [pvt.mu_dead_beggs(api, T), rs]))
                out.append(("mu_live_petrosky", "mu_live_petrosky", [pvt.mu_dead_petrosky(api, T), rs]))
            for mub in (0.3, 1.5, 12.0, 90.0):
                for p, pb in ((3000.0, 2000.0), (6000.0, 2500.0), (2100.0, 2000.0)):
                    out.append(("mu_under_beal", "mu_under_beal", [mub, p, pb]))
                    out.append(("mu_under_petrosky", "mu_under_petrosky", [mub, p, pb]))
                    out.append(("mu_under_vasquez_beggs", "mu_under_vasquez_beggs", [mub, p, pb]))

    # ---- gas --------------------------------------------------------
    for gg in (0.56, 0.65, 0.8, 1.0, 1.2):
        for h2s, co2 in ((0.0, 0.0), (0.05, 0.10), (0.0, 0.25), (0.3, 0.0)):
            out.append(("gas_pseudocritical", "gas_pseudocritical", [gg, h2s, co2]))
        for T in (80.0, 160.0, 250.0, 350.0):
            for p in (100.0, 800.0, 3000.0, 7000.0, 12000.0):
                out.append(("z_dak_via_props", "gas_properties", [p, T, gg, 0.0, 0.0, "lee"]))
                for vm in GAS_VISC:
                    out.append((f"gas_properties_{vm}", "gas_properties", [p, T, gg, 0.0, 0.0, vm]))
                out.append(("gas_properties_sour", "gas_properties", [p, T, gg, 0.04, 0.08, "lee"]))

    # ---- water ------------------------------------------------------
    for S in (0.0, 3.0, 8.0, 15.0, 25.0):
        for T in (80.0, 160.0, 250.0):
            for p in (100.0, 2000.0, 8000.0):
                out.append(("water_properties", "water_properties", [p, T, S]))
    for sg in (1.0, 1.02, 1.05, 1.12, 1.25):
        out.append(("salinity_from_sg", "salinity_from_sg", [sg]))

    # ---- wet gas gravity --------------------------------------------
    for cgr in (1.0, 5.0, 25.0, 60.0, 150.0):
        for api in (45.0, 55.0, 65.0):
            for gg in (0.6, 0.75):
                out.append(("wet_gas_gravity", "wet_gas_gravity", [gg, cgr, api]))

    # ---- oil_properties: the whole thing, including a PVT match ------
    for _ in range(1200):
        api = random.uniform(10.0, 55.0)
        gg = random.uniform(0.55, 1.2)
        T = random.uniform(90.0, 300.0)
        rsb = random.uniform(10.0, 2500.0)
        p = random.uniform(20.0, 9000.0)
        pvt_m = random.choice(PVT_METHODS)
        visc_m = random.choice(VISC_METHODS)
        pb_meas = random.choice([None, None, random.uniform(500.0, 5000.0)])
        match = random.choice([
            None, None,
            {"rs_exp": random.uniform(0.6, 1.5)},
            {"bo_a": random.uniform(0.9, 1.1), "bo_b": random.uniform(-0.05, 0.05)},
            {"mu_mult": random.uniform(0.5, 2.0),
             "rs_exp": random.uniform(0.8, 1.2),
             "bo_a": random.uniform(0.95, 1.05), "bo_b": 0.0},
        ])
        out.append(("oil_properties", "oil_properties",
                    [p, T, api, gg, rsb, pb_meas, pvt_m, visc_m, match]))
    return out


def run_one(func_name, args):
    """Call one engine function and return its answer in a JSON-friendly form."""
    value = getattr(pvt, func_name)(*args)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return {k: v for k, v in value.items()}
    return value


def main(path):
    rows = []
    skipped = 0
    for name, func_name, args in cases():
        try:
            rows.append({"name": name, "func": func_name, "args": args, "want": run_one(func_name, args)})
        except (ValueError, ZeroDivisionError, OverflowError):
            skipped += 1                              # a case the correlation itself refuses
    with open(path, "w") as handle:
        json.dump(rows, handle)
    print(f"{len(rows)} cases written to {path} ({skipped} refused by the Python and left out)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tools/pvt_expected.json")
