"""
app_helpers.py - the logic behind the Streamlit page (no Streamlit code in here).

Keeping the logic apart from the page means it can be tested on its own
(see test_app_helpers.py) and reused later, for example from a different front end.

Units: depth ft, rate STB/d (oil + water) or Mscf/d (gas), temperature degF, pipe diameter in.

PRESSURE: everything the user types or sees is GAUGE pressure (psig), as on a wellsite gauge.  The engine
underneath (vlp.py, ipr.py, pvt.py, nodal.py) works in ABSOLUTE pressure (psia), because the gas law needs it.
This file is the only place where the two meet:
    * build_case() adds ATM to every pressure that came from the page (see GAUGE_INPUTS),
    * to_psig() takes a calculated pressure back to gauge for a chart, a table or a message.
So page inputs and anything returned for display are psig; anything handed to or returned by the engine is psia.

What is in here
    DEFAULTS            - starting value of every input on the page
    build_case()        - turn the page inputs (a dictionary) into well, fluid and IPR objects
    run_case()          - operating point + curves + pressure/temperature profile
    match_from_test()   - VLP matching: multiplier that reproduces one measured test
    multiplier_note()   - plain-language line about the VLP multipliers in use
    correlation_advice(), recommend_correlation(), check_correlations() - which VLP correlation suits the well
    make_*_figure()     - the three charts
    sensitivity_options(), run_sensitivity(), sensitivity_table() - the sensitivity tab
"""
import copy
import math

import numpy as np
import pvt
import pvt_match
import gaslift
import ipr
from matplotlib.figure import Figure
from matplotlib import colormaps
from nodal import solve_well, curves, sensitivity, well_with_tubing_id, match_vlp_multiplier, match_vlp_survey, fluid_at_rate
from vlp import OilWaterFluid, GasFluid, pressure_traverse
from well import Well, vertical_survey, parse_survey_text, simple_tubing

# Correlations that exist so far (the page lists the others as "coming soon")
AVAILABLE_CORRELATIONS = ("beggs_brill", "hagedorn_brown", "gray", "orkiszewski", "ansari", "duns_ros", "mukherjee_brill", "fancher_brown")

# ---------------------------------------------------------------------
# Default value of every input (the spec's defaults where it gives one)
# ---------------------------------------------------------------------
DEFAULTS = dict(
    fluid_type="oil",            # "oil" or "gas"
    p_res=3000.0, t_res=200.0,   # reservoir pressure (psig, gauge) and temperature (degF)
    # --- equipment ---
    survey_mode="vertical",      # "vertical" or "deviated"
    depth=8000.0,                # perforation depth of a vertical well (ft)
    survey_text="0 0\n2000 2000\n6000 5500\n9000 7000",     # MD TVD, last row = perforations
    tubing_id=2.992, roughness_in=0.0006,
    p_wh=200.0,                  # wellhead flowing pressure (psig)
    t_amb_surface=80.0, u_surface=5.0,
    perf_ambient_is_reservoir=True, t_amb_perf=200.0, u_perf=5.0,
    correlation="beggs_brill",
    gravity_mult=1.0, friction_mult=1.0,    # VLP matching multipliers (1.0 = correlation unchanged)
    # --- oil and water ---
    api=35.0, gas_sg=0.75, rsb=500.0, water_cut=0.3,
    water_sg=1.02,               # specific gravity of the produced water (fresh water = 1)
    oil_gor=0.0,                 # producing (total) GOR in scf/STB; 0 = same as the solution GOR at Pb
    pb_meas=0.0,                 # measured bubble point (psig); 0 = calculate it from the correlation
    pvt_method="glaso", visc_method="beal",
    pvt_match=None,              # numbers from PVT matching to lab data (see pvt_match.py), or None
    # continuous gas lift (oil wells): lift = "none" or "continuous"
    lift="none", gl_rate=1000.0, gl_md=6000.0, gl_sg=0.65, gl_p_inj=1500.0,
    #   gl_rate = injected gas (Mscf/d), gl_md = injection depth (ft MD), gl_sg = injected gas gravity,
    #   gl_p_inj = injection pressure at the wellhead (psig), used only to check the pressure at the injection point
    oil_ipr="pi",                # "pi", "vogel", "darcy", "fetkovich", "horizontal", "horizontal_kg" or "multilayer"
    pi=3.0,
    vogel_q=2000.0, vogel_pwf=2000.0,      # one flowing test: rate (STB/d) and bottom-hole pressure (psig)
    oil_k=50.0, oil_h=20.0, oil_bo=1.25, oil_mu=0.8, oil_re=1000.0, oil_rw=0.354, oil_skin=0.0,
    oil_regime="pseudosteady",   # Darcy flow regime: "pseudosteady", "steady" or "transient"
    oil_phi=0.2, oil_ct=1.0e-5, oil_time=12.0,    # transient only: porosity, ct (1/psi), time (hours)
    fet_q1=1000.0, fet_pwf1=2500.0, fet_q2=2000.0, fet_pwf2=1800.0,   # two flowing tests: STB/d and psig
    # horizontal oil well (Joshi): kh, kv in md, h, L, drainage radius re_h and rw in ft
    hz_kh=50.0, hz_kv_ratio=0.1, hz_h=50.0, hz_length=1000.0, hz_re=1500.0, hz_rw=0.354,   # kv = kv_ratio * kh
    hz_bo=1.25, hz_mu=0.8, hz_skin=0.0,
    # Kuchuk-Goode horizontal well (box): it also uses the hz_ inputs above.  Box Lx (along the well) x Ly (across), the well
    # position as fractions (0.5 = centred) of Lx, Ly and h, ky/kx, and the top boundary "sealed" or "constant_pressure"
    kg_lx=3000.0, kg_ly=2400.0, kg_ky_ratio=1.0, kg_xw=0.5, kg_yw=0.5, kg_zw=0.5, kg_top="sealed",
    # multilayer oil IPR (commingled): one dictionary per layer, edited in the pop-up layer table.
    #   model "pi"    : the layer is given by its productivity index "pi" (STB/d/psi)
    #   model "darcy" : the layer is given by permeability "k" (md), thickness "h" (ft) and "skin"; its PI comes
    #                   from the Darcy equation with the ml_bo / ml_mu / ml_re / ml_rw values below
    #   "p_psig"      : layer pressure (psig)         "gor": formation GOR of the layer (scf/STB; 0 = the solution GOR)
    #   "wc"          : water cut of the layer (%)
    ml_layers=[
        {"model": "pi", "p_psig": 3000.0, "pi": 2.0, "k": 100.0, "h": 20.0, "skin": 0.0, "gor": 400.0, "wc": 20.0},
        {"model": "pi", "p_psig": 2800.0, "pi": 1.5, "k": 100.0, "h": 15.0, "skin": 0.0, "gor": 500.0, "wc": 30.0},
        {"model": "pi", "p_psig": 2500.0, "pi": 1.0, "k": 50.0, "h": 10.0, "skin": 0.0, "gor": 600.0, "wc": 50.0},
    ],
    ml_crossflow=False,
    ml_bo=1.25, ml_mu=0.8, ml_re=1000.0, ml_rw=0.354,      # used by the Darcy layers only
    # --- dry and wet gas ---
    gas_sg_g=0.65, cgr=0.0, cond_api=50.0, wgr=0.0, y_h2s=0.0, y_co2=0.0, gas_visc="lee",
    gas_ipr="jones",             # "darcy", "jones", "backpressure", "horizontal", "horizontal_kg" or "multilayer"
    gas_k=5.0, gas_h=40.0, gas_re=1000.0, gas_rw=0.354, gas_skin=0.0,
    gas_beta=0.0,                # 0 = estimate from permeability
    gas_h_perf=0.0,              # 0 = same as h
    bp_c=0.015, bp_n=0.85,       # back-pressure equation q = C (Pr^2 - Pwf^2)^n, q in Mscf/d
    # horizontal gas well (Joshi): kh, kv in md, h, L, drainage radius re_h and rw in ft (kv = kv_ratio * kh).
    # Z and gas viscosity are taken as for the vertical gas well; beta is gas_beta above (0 = estimate from kh).
    gh_kh=5.0, gh_kv_ratio=0.1, gh_h=40.0, gh_length=2000.0, gh_re=1500.0, gh_rw=0.354, gh_skin=0.0,
    # Kuchuk-Goode horizontal gas well (box): it also uses the gh_ inputs above.  Box Lx (along the well) x Ly (across), the
    # well position as fractions of Lx, Ly and h (0.5 = centred), ky/kx, and the top boundary "sealed" or "constant_pressure"
    gk_lx=4000.0, gk_ly=3000.0, gk_ky_ratio=1.0, gk_xw=0.5, gk_yw=0.5, gk_zw=0.5, gk_top="sealed",
    # multilayer gas IPR (commingled): one dictionary per layer, edited in the pop-up layer table.
    #   model "darcy" / "jones" : the layer is given by permeability "k" (md), thickness "h" (ft) and "skin" (Jones adds the
    #                             non-Darcy term, with beta = gm_beta or estimated from k); re and rw are the gm_ values below
    #   model "backpressure"    : the layer is given by "C" and "n"  (q = C (Pr^2 - Pwf^2)^n, Mscf/d)
    #   "p_psig" : layer pressure (psig)    "cgr", "wgr": condensate-gas and water-gas ratio of the layer (STB/MMscf)
    gm_layers=[
        {"model": "jones", "p_psig": 3000.0, "k": 8.0, "h": 20.0, "skin": 0.0, "C": 0.015, "n": 0.85, "cgr": 10.0, "wgr": 1.0},
        {"model": "jones", "p_psig": 2800.0, "k": 5.0, "h": 15.0, "skin": 0.0, "C": 0.015, "n": 0.85, "cgr": 25.0, "wgr": 2.0},
        {"model": "jones", "p_psig": 2500.0, "k": 3.0, "h": 10.0, "skin": 0.0, "C": 0.015, "n": 0.85, "cgr": 40.0, "wgr": 5.0},
    ],
    gm_crossflow=False,
    gm_re=1000.0, gm_rw=0.354, gm_beta=0.0,      # drainage radius, wellbore radius, beta (0 = estimate): all layers
)


ATM = 14.7        # psi: the page is in psig (gauge), the program works in psia (absolute)

# The page inputs that are pressures.  build_case() adds ATM to each of these before anything else sees them.
# The two with a "0 means ..." meaning are converted only when they are above 0, so the 0 keeps its meaning.
GAUGE_INPUTS = ("p_res", "p_wh", "vogel_pwf", "fet_pwf1", "fet_pwf2")
GAUGE_INPUTS_OPTIONAL = ("pb_meas", "gl_p_inj")        # 0 = "not given" / "no check": left as 0


def to_psig(p_psia):
    """A calculated absolute pressure (psia) as the gauge pressure the page shows (psig)."""
    return p_psia - ATM


def to_psia(p_psig):
    """A gauge pressure typed on the page (psig) as the absolute pressure the engine needs (psia)."""
    return p_psig + ATM


def gauge_inputs_to_absolute(inputs):
    """A copy of the page inputs with every pressure changed from psig to psia (see GAUGE_INPUTS)."""
    i = dict(inputs)
    for key in GAUGE_INPUTS:
        if key in i and i[key] is not None:
            i[key] = float(i[key]) + ATM
    for key in GAUGE_INPUTS_OPTIONAL:
        if i.get(key):                                 # 0, None and missing all stay as they are
            i[key] = float(i[key]) + ATM
    return i


def multilayer_layers(inputs):
    """The layers of a multilayer oil IPR from the page inputs, as
        [{"p_res" psia, "J" STB/d/psi, "wc" fraction, "gor" scf/STB}, ...].
    Each layer of inputs["ml_layers"] is entered either by its productivity index (model "pi") or by
    permeability, thickness and skin (model "darcy"); a Darcy layer gets its PI from the Darcy equation with the
    Bo, viscosity, drainage radius and wellbore radius of the layer table (ml_bo, ml_mu, ml_re, ml_rw).
    A GOR of 0 means "the solution GOR (rsb)".  A layer without a pressure is an empty row and is skipped.
    Raises ValueError with a plain message when a layer makes no sense or no layer is usable."""
    i = {**DEFAULTS, **inputs}
    layers = []
    for n, row in enumerate(i["ml_layers"], start=1):
        p = row.get("p_psig")
        if p is None or p != p:
            continue                                                  # empty row
        model = row.get("model", "pi")
        if p + ATM <= 0:
            raise ValueError(f"Layer {n}: the layer pressure is below a perfect vacuum ({-ATM:,.1f} psig).")
        if model == "darcy":
            k, h, skin = row.get("k"), row.get("h"), row.get("skin") or 0.0
            if not k or not h or k <= 0 or h <= 0:
                raise ValueError(f"Layer {n}: permeability and thickness must be above 0.")
            J = ipr.darcy_productivity_index_oil(k, h, i["ml_bo"], i["ml_mu"], i["ml_re"], i["ml_rw"], skin)
        else:
            J = row.get("pi")
            if not J or J <= 0:
                raise ValueError(f"Layer {n}: the productivity index must be above 0.")
        wc = row.get("wc") or 0.0
        if not 0.0 <= wc <= 100.0:
            raise ValueError(f"Layer {n}: the water cut must be between 0 and 100 %.")
        gor = row.get("gor") or 0.0
        if gor < 0:
            raise ValueError(f"Layer {n}: the GOR cannot be negative.")
        layers.append({"p_res": float(p) + ATM, "J": float(J), "wc": wc / 100.0,
                       "gor": float(gor) if gor > 0 else float(i["rsb"])})
    if not layers:
        raise ValueError("Enter at least one layer in the layer table.")
    return layers


def multilayer_summary(inputs):
    """Rows (for st.dataframe) that describe the layer table: model, pressure, PI (calculated for Darcy layers),
    GOR and water cut.  Raises ValueError like multilayer_layers()."""
    i = {**DEFAULTS, **inputs}
    layers = multilayer_layers(i)
    rows = []
    shown = [r for r in i["ml_layers"] if r.get("p_psig") is not None and r.get("p_psig") == r.get("p_psig")]
    for n, (row, layer) in enumerate(zip(shown, layers), start=1):
        rows.append({"Layer": n, "Model": "Darcy" if row.get("model") == "darcy" else "PI",
                     "Pressure (psig)": row["p_psig"], "PI (STB/d/psi)": round(layer["J"], 3),
                     "GOR (scf/STB)": round(layer["gor"], 0), "Water cut (%)": round(layer["wc"] * 100.0, 1)})
    return rows


def gas_multilayer_layers(inputs):
    """The layers of a multilayer GAS IPR from the page inputs, as
        [{"p_res" psia, "a", "b", "cgr", "wgr"}  or  {"p_res", "C", "n", "cgr", "wgr"}, ...].
    A "darcy" or "jones" layer gets its laminar coefficient a (and, for Jones, the turbulent coefficient b) from its
    permeability, thickness and skin with the layer pressure's Z and viscosity (taken at 75 % of the layer pressure and
    the reservoir temperature, like the single-layer models), the drainage radius gm_re and wellbore radius gm_rw.
    A "backpressure" layer uses its C and n.  A layer with CGR above 0 uses the well-stream gravity for its gas.
    A layer without a pressure is an empty row and is skipped.
    Raises ValueError with a plain message when a layer makes no sense or no layer is usable."""
    i = {**DEFAULTS, **inputs}
    layers = []
    for n, row in enumerate(i["gm_layers"], start=1):
        p = row.get("p_psig")
        if p is None or p != p:
            continue
        if p + ATM <= 0:
            raise ValueError(f"Layer {n}: the layer pressure is below a perfect vacuum ({-ATM:,.1f} psig).")
        p_psia = float(p) + ATM
        cgr, wgr = row.get("cgr") or 0.0, row.get("wgr") or 0.0
        if cgr < 0 or wgr < 0:
            raise ValueError(f"Layer {n}: the CGR and WGR cannot be negative.")
        model = row.get("model", "jones")
        layer = {"p_res": p_psia, "cgr": float(cgr), "wgr": float(wgr)}
        if model == "backpressure":
            C, nn = row.get("C"), row.get("n")
            if not C or C <= 0 or not nn or not 0.0 < nn <= 1.0:
                raise ValueError(f"Layer {n}: C must be above 0 and n between 0 and 1.")
            layer.update(C=float(C), n=float(nn))
        else:
            k, h, skin = row.get("k"), row.get("h"), row.get("skin") or 0.0
            if not k or not h or k <= 0 or h <= 0:
                raise ValueError(f"Layer {n}: permeability and thickness must be above 0.")
            sg = i["gas_sg_g"]
            if cgr > 0:
                sg = pvt.wet_gas_gravity(sg, cgr, i["cond_api"])
            props = pvt.gas_properties(0.75 * p_psia, i["t_res"], sg, i["y_h2s"], i["y_co2"], i["gas_visc"])
            a = ipr.gas_a_coefficient(i["t_res"], k, h, props["mu_g"], props["z"], i["gm_re"], i["gm_rw"], skin)
            b = 0.0
            if model == "jones":
                b = ipr.gas_b_coefficient(i["t_res"], k, h, props["z"], sg, i["gm_rw"], _positive_or_none(i["gm_beta"]))
            layer.update(a=a, b=b)
        layers.append(layer)
    if not layers:
        raise ValueError("Enter at least one layer in the layer table.")
    return layers


GAS_LAYER_MODELS = {"darcy": "Darcy", "jones": "Jones", "backpressure": "Back-pressure"}


def gas_multilayer_summary(inputs):
    """Rows (for st.dataframe) that describe the gas layer table: model, pressure, AOF of the layer alone, CGR and WGR.
    Raises ValueError like gas_multilayer_layers()."""
    i = {**DEFAULTS, **inputs}
    layers = gas_multilayer_layers(i)
    shown = [r for r in i["gm_layers"] if r.get("p_psig") is not None and r.get("p_psig") == r.get("p_psig")]
    rows = []
    for n, (row, layer) in enumerate(zip(shown, layers), start=1):
        aof = ipr.gas_multilayer(layer["p_res"], 0.0, [layer])
        rows.append({"Layer": n, "Model": GAS_LAYER_MODELS.get(row.get("model", "jones"), "Jones"),
                     "Pressure (psig)": row["p_psig"], "AOF alone (Mscf/d)": round(aof, 0),
                     "CGR (STB/MMscf)": round(layer["cgr"], 1), "WGR (STB/MMscf)": round(layer["wgr"], 1)})
    return rows


def _positive_or_none(value):
    """The page uses 0 to mean 'not given'; the model wants None for that."""
    return value if value and value > 0 else None


# =====================================================================
# Inputs -> objects
# =====================================================================

def build_case(inputs):
    """Turn the page inputs into everything solve_well() needs.

    inputs : dictionary with any of the keys in DEFAULTS (missing keys use the default).  Its pressures are
             GAUGE pressures (psig), as typed on the page; they are turned into psia here and nowhere else.
    Returns a dictionary:
        solve        - the keyword arguments for nodal.solve_well() (absolute pressures, psia)
        fluid_type, rate_label, pb (oil only), gas_sg_used (gas only)
    Raises ValueError with a plain message if an input makes no sense.
    """
    i = gauge_inputs_to_absolute({**DEFAULTS, **inputs})
    is_oil = i["fluid_type"] == "oil"
    p_res_used = i["p_res"]                    # the reservoir pressure the solver starts the IPR from

    # ---- well -------------------------------------------------------
    if i["survey_mode"] == "vertical":
        md, tvd = vertical_survey(i["depth"])
    else:
        md, tvd = parse_survey_text(i["survey_text"])
    perf_md = md[-1]
    t_amb_perf = i["t_res"] if i["perf_ambient_is_reservoir"] else i["t_amb_perf"]
    well = Well(md=md, tvd=tvd, tubing=simple_tubing(i["tubing_id"], perf_md),
                t_reservoir=i["t_res"], roughness_in=i["roughness_in"],
                ambient_table=[(0.0, i["t_amb_surface"], i["u_surface"]),
                               (perf_md, t_amb_perf, i["u_perf"])])

    case = {"fluid_type": i["fluid_type"], "gas_lift": None}
    if is_oil:
        # ---- oil and water ------------------------------------------
        pb_meas = _positive_or_none(i["pb_meas"])
        gas_lift = None
        if i["lift"] == "continuous":
            if not 0.0 < i["gl_md"] < perf_md:
                raise ValueError(f"The gas injection depth ({i['gl_md']:,.0f} ft) must be above the "
                                 f"perforations ({perf_md:,.0f} ft).")
            gas_lift = {"rate": i["gl_rate"], "md": i["gl_md"], "sg": i["gl_sg"], "p_inj": i["gl_p_inj"]}
        fluid = OilWaterFluid(api=i["api"], gas_sg=i["gas_sg"], rsb=i["rsb"],
                              water_cut=i["water_cut"], gor=_positive_or_none(i["oil_gor"]), salinity=pvt.salinity_from_sg(i["water_sg"]),
                              pb_meas=pb_meas, pvt_method=i["pvt_method"],
                              visc_method=i["visc_method"], pvt_match=i["pvt_match"],
                              injection_gas_rate=gas_lift["rate"] if gas_lift else 0.0,
                              injection_md=gas_lift["md"] if gas_lift else None,
                              injection_gas_sg=gas_lift["sg"] if gas_lift else None)
        case["gas_lift"] = gas_lift
        pb = pvt.oil_properties(i["p_res"], i["t_res"], i["api"], i["gas_sg"], i["rsb"],
                                pb_meas, i["pvt_method"], i["visc_method"], i["pvt_match"])["pb"]
        model = i["oil_ipr"]
        if model == "pi":
            ipr_function, ipr_inputs = ipr.oil_pi, {"pb": pb, "J": i["pi"]}
        elif model == "vogel":
            ipr_function = ipr.oil_vogel
            ipr_inputs = {"pb": pb, "q_test": i["vogel_q"], "pwf_test": i["vogel_pwf"]}
        elif model == "darcy":
            ipr_function = ipr.oil_darcy_regime
            ipr_inputs = {"pb": pb, "k": i["oil_k"], "h": i["oil_h"], "bo": i["oil_bo"],
                          "mu": i["oil_mu"], "re": i["oil_re"], "rw": i["oil_rw"],
                          "skin": i["oil_skin"], "regime": i["oil_regime"]}
            if i["oil_regime"] == "transient":
                ipr_inputs.update(phi=i["oil_phi"], ct=i["oil_ct"], time_hours=i["oil_time"])
        elif model == "horizontal":
            ipr_function = ipr.oil_horizontal_joshi
            ipr_inputs = {"pb": pb, "kh": i["hz_kh"], "kv": i["hz_kv_ratio"] * i["hz_kh"], "h": i["hz_h"],
                          "length": i["hz_length"], "re_h": i["hz_re"], "rw": i["hz_rw"],
                          "bo": i["hz_bo"], "mu": i["hz_mu"], "skin": i["hz_skin"]}
        elif model == "horizontal_kg":
            ipr_function = ipr.oil_horizontal_kuchuk_goode
            ipr_inputs = {"pb": pb, "kh": i["hz_kh"], "kv": i["hz_kv_ratio"] * i["hz_kh"], "h": i["hz_h"],
                          "length": i["hz_length"], "lx": i["kg_lx"], "ly": i["kg_ly"],
                          "xw": i["kg_xw"] * i["kg_lx"], "yw": i["kg_yw"] * i["kg_ly"], "zw": i["kg_zw"] * i["hz_h"],
                          "rw": i["hz_rw"], "bo": i["hz_bo"], "mu": i["hz_mu"], "skin": i["hz_skin"],
                          "ky_ratio": i["kg_ky_ratio"], "top": i["kg_top"]}
        elif model == "multilayer":
            ipr_function = ipr.oil_multilayer
            layers = multilayer_layers(i)
            ipr_inputs = {"pb": pb, "layers": layers, "crossflow": bool(i["ml_crossflow"])}
            p_res_used = max(layer["p_res"] for layer in layers)      # the curve starts at the highest layer pressure
        elif model == "fetkovich":
            ipr_function = ipr.oil_fetkovich
            ipr_inputs = {"q1": i["fet_q1"], "pwf1": i["fet_pwf1"],
                          "q2": i["fet_q2"], "pwf2": i["fet_pwf2"]}
        else:
            raise ValueError(f"Unknown oil IPR model: {model}")
        case.update(rate_label="Liquid rate (STB/d)", pb=pb)
    else:
        # ---- dry and wet gas ----------------------------------------
        gas_sg = dry_sg = i["gas_sg_g"]
        model = i["gas_ipr"]
        cgr, wgr = i["cgr"], i["wgr"]
        if model == "multilayer":              # the layers decide the CGR and WGR (at every rate); start from zero
            cgr, wgr = 0.0, 0.0
        if cgr > 0:                            # wet gas: use the well-stream gravity
            gas_sg = pvt.wet_gas_gravity(gas_sg, cgr, i["cond_api"])
        fluid = GasFluid(gas_sg=gas_sg, cgr=cgr, cond_api=i["cond_api"], wgr=wgr,
                         salinity=pvt.salinity_from_sg(i["water_sg"]), y_h2s=i["y_h2s"], y_co2=i["y_co2"],
                         visc_method=i["gas_visc"], gas_sg_dry=dry_sg)
        # Darcy and Jones need Z and viscosity.  They are evaluated at 75 % of the reservoir
        # pressure (a typical average of Pr and Pwf) and the reservoir temperature.
        props = pvt.gas_properties(0.75 * i["p_res"], i["t_res"], gas_sg,
                                   i["y_h2s"], i["y_co2"], i["gas_visc"])
        common = {"temp_f": i["t_res"], "k": i["gas_k"], "h": i["gas_h"], "mu": props["mu_g"],
                  "z": props["z"], "re": i["gas_re"], "rw": i["gas_rw"], "skin": i["gas_skin"]}
        if model == "darcy":
            ipr_function, ipr_inputs = ipr.gas_darcy, common
        elif model == "jones":
            ipr_function = ipr.gas_jones
            ipr_inputs = dict(common, gas_sg=gas_sg, beta=_positive_or_none(i["gas_beta"]),
                              h_perf=_positive_or_none(i["gas_h_perf"]))
        elif model == "backpressure":
            ipr_function = ipr.gas_backpressure
            ipr_inputs = {"C": i["bp_c"], "n": i["bp_n"]}
        elif model in ("horizontal", "horizontal_kg"):
            horizontal = {"temp_f": i["t_res"], "kh": i["gh_kh"], "kv": i["gh_kv_ratio"] * i["gh_kh"],
                          "h": i["gh_h"], "length": i["gh_length"], "rw": i["gh_rw"], "mu": props["mu_g"],
                          "z": props["z"], "gas_sg": gas_sg, "skin": i["gh_skin"],
                          "beta": _positive_or_none(i["gas_beta"])}
            if model == "horizontal":
                ipr_function = ipr.gas_horizontal_joshi
                ipr_inputs = dict(horizontal, re_h=i["gh_re"])
            else:
                ipr_function = ipr.gas_horizontal_kuchuk_goode
                ipr_inputs = dict(horizontal, lx=i["gk_lx"], ly=i["gk_ly"], xw=i["gk_xw"] * i["gk_lx"],
                                  yw=i["gk_yw"] * i["gk_ly"], zw=i["gk_zw"] * i["gh_h"],
                                  ky_ratio=i["gk_ky_ratio"], top=i["gk_top"])
        elif model == "multilayer":
            ipr_function = ipr.gas_multilayer
            layers = gas_multilayer_layers(i)
            ipr_inputs = {"layers": layers, "crossflow": bool(i["gm_crossflow"])}
            p_res_used = max(layer["p_res"] for layer in layers)      # the curve starts at the highest layer pressure
        else:
            raise ValueError(f"Unknown gas IPR model: {model}")
        case.update(rate_label="Gas rate (Mscf/d)", gas_sg_used=gas_sg)

    case["solve"] = dict(well=well, fluid=fluid, ipr_function=ipr_function, p_res=p_res_used,
                         ipr_inputs=ipr_inputs, p_wh=i["p_wh"], correlation=i["correlation"],
                         max_step_ft=max(100.0, perf_md / 150.0), n_grid=30,
                         gravity_mult=i["gravity_mult"], friction_mult=i["friction_mult"])
    return case


# =====================================================================
# Run the analysis
# =====================================================================

def run_case(case, n_curve_points=40):
    """Operating point, IPR/VLP curves and the pressure/temperature profile of a case.

    Returns {"result": ..., "curves": ..., "traverse": ...}; traverse is None when
    the well does not flow (no operating point).
    """
    s = case["solve"]
    result = solve_well(**s)
    cv = curves(s["well"], s["fluid"], s["ipr_function"], s["p_res"], s["ipr_inputs"],
                s["p_wh"], s["correlation"], s["max_step_ft"], n_points=n_curve_points,
                gravity_mult=s["gravity_mult"], friction_mult=s["friction_mult"])
    traverse = None
    fluid_op = s["fluid"]                     # the fluid at the operating point (multilayer: the commingled mix)
    if result["found"]:
        fluid_op = fluid_at_rate(s["fluid"], s["ipr_function"], s["p_res"], s["ipr_inputs"], result["q"])
        traverse = pressure_traverse(s["well"], fluid_op, result["q"], s["p_wh"],
                                     s["correlation"], s["max_step_ft"],
                                     s["gravity_mult"], s["friction_mult"])
    check = None
    if case.get("gas_lift"):
        check = gaslift.injection_check(s["well"], fluid_op, traverse, case["gas_lift"]["p_inj"])
    return {"result": result, "curves": cv, "traverse": traverse, "gas_lift_check": check, "fluid_op": fluid_op}


# =====================================================================
# PVT matching (lab data against the correlations)
# =====================================================================
PVT_NAMES = {"glaso": "Glaso", "standing": "Standing", "lasater": "Lasater", "petrosky": "Petrosky et al"}
VISC_NAMES = {"beal": "Beal et al", "beggs": "Beggs et al", "petrosky": "Petrosky et al"}
PVT_COLORS = {"glaso": "#1f77b4", "standing": "#d95f02", "lasater": "#2ca02c", "petrosky": "#9467bd"}


def pvt_base(inputs):
    """The fluid numbers a PVT match depends on (oil gravity, gas gravity, solution GOR, temperature)."""
    i = {**DEFAULTS, **inputs}
    return {"api": i["api"], "gas_sg": i["gas_sg"], "rsb": i["rsb"], "temp_f": i["t_res"]}


def pvt_comparison_table(rows):
    """Readable rows (for st.dataframe) from pvt_match.compare_methods()."""
    def pct(x):
        return "-" if x is None else round(x, 1)
    return [{"Pb, Rs, Bo correlation": PVT_NAMES[r["pvt_method"]],
             "Viscosity correlation": VISC_NAMES[r["visc_method"]],
             "Pb calculated (psig)": round(to_psig(r["pb_calc"]), 0),
             "Pb error (%)": pct(r["pb_error"]), "Rs error (%)": pct(r["rs_error"]),
             "Bo error (%)": pct(r["bo_error"]), "Viscosity error (%)": pct(r["mu_error"]),
             "Average error (%)": pct(r["score"])} for r in rows]


def with_pvt_match(inputs, applied):
    """The page inputs with a PVT match applied (applied = None leaves them alone).
    applied : {"pvt_method", "visc_method", "pb_meas", "match", "base"} as stored by the PVT tab."""
    if not applied:
        return dict(inputs)
    return {**inputs, "pvt_method": applied["pvt_method"], "visc_method": applied["visc_method"],
            "pb_meas": applied["pb_meas"] or 0.0, "pvt_match": applied["match"]}


def pvt_match_stale_note(inputs, applied):
    """'' normally.  A sentence when the oil gravity, gas gravity, GOR or temperature on the page are no
    longer the ones the PVT match was made with (the match would then not describe this fluid)."""
    if not applied:
        return ""
    now, then = pvt_base(inputs), applied["base"]
    changed = [name for name, key in (("oil gravity", "api"), ("gas gravity", "gas_sg"),
                                      ("solution GOR", "rsb"), ("reservoir temperature", "temp_f"))
               if abs(now[key] - then[key]) > 1e-9]
    if not changed:
        return ""
    return ("The PVT match was made with different " + ", ".join(changed) +
            ". Match again with the lab data, or remove the match.")


def make_pvt_figure(lab, base, pb_meas, pvt_method, visc_method, fit=None):
    """Lab data against the correlations: Rs, Bo and viscosity against pressure (three small charts).

    lab        : clean lab table (pvt_match.clean_lab_table); its pressures are psia, the charts show psig
    base       : dict from pvt_base()
    pvt_method, visc_method : the pair to highlight
    fit        : result of pvt_match.fit_match() for that pair, drawn as a dashed black line, or None"""
    fig = Figure(figsize=(13.0, 3.9))
    axes = fig.subplots(1, 3)
    pb_guess = pb_meas or pvt.PB_FUNCS[pvt_method](base["rsb"], base["gas_sg"], base["api"], base["temp_f"])
    p_max = 1.15 * max(max(r["p"] for r in lab), pb_guess)
    grid = [14.7 + (p_max - 14.7) * k / 59.0 for k in range(60)]

    def run(method, visc, match=None):
        return pvt_match.evaluate(grid, base["api"], base["gas_sg"], base["rsb"], base["temp_f"],
                                  pb_meas, method, visc, match)

    grid_g = [to_psig(x) for x in grid]                   # the charts are in gauge pressure
    for ax, key in zip(axes, pvt_match.PROPERTIES):
        if key == "mu":                                   # viscosity: the two viscosity correlations
            for visc in pvt_match.VISC_METHODS:
                chosen = visc == visc_method
                ax.plot(grid_g, run(pvt_method, visc)["mu"], lw=2.2 if chosen else 1.2,
                        alpha=1.0 if chosen else 0.7, color="#d95f02" if chosen else "#1f77b4",
                        label=VISC_NAMES[visc])
        else:                                             # Rs and Bo: the four Pb / Rs / Bo correlations
            for method in pvt_match.PVT_METHODS:
                chosen = method == pvt_method
                ax.plot(grid_g, run(method, visc_method)[key], lw=2.2 if chosen else 1.2,
                        alpha=1.0 if chosen else 0.7, color=PVT_COLORS[method], label=PVT_NAMES[method])
        if fit is not None:
            ax.plot(grid_g, run(pvt_method, visc_method, fit["match"])[key], "--", color="black", lw=2.0,
                    label="Matched")
        points = [(to_psig(r["p"]), r[key]) for r in lab if r[key] is not None]
        if points:
            ax.plot([x for x, _ in points], [y for _, y in points], "o", color="black", ms=7,
                    mec="white", label="Lab data")
        if pb_meas:
            ax.axvline(to_psig(pb_meas), color="gray", ls=":", lw=1.2)
        ax.set_xlabel("Pressure (psig)")
        ax.set_ylabel(pvt_match.PROPERTY_NAMES[key])
        ax.set_xlim(0, to_psig(p_max))
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7.5)
    fig.tight_layout()
    return fig


# =====================================================================
# VLP matching (gravity and friction multipliers)
# =====================================================================
MULTIPLIER_MIN, MULTIPLIER_MAX = 0.5, 2.0       # range offered on the page (and searched when matching)


def transient_warning(inputs):
    """'' normally.  A plain sentence when the Darcy transient regime is chosen and the time is
    later than the moment the pressure disturbance reaches the drainage radius (the transient
    equation is then no longer valid)."""
    i = {**DEFAULTS, **inputs}
    if i["fluid_type"] != "oil" or i["oil_ipr"] != "darcy" or i["oil_regime"] != "transient":
        return ""
    t_end = ipr.transient_end_time_hours(i["oil_k"], i["oil_phi"], i["oil_mu"], i["oil_ct"], i["oil_re"])
    if i["oil_time"] <= t_end:
        return ""
    return (f"The transient equation is only valid for about {t_end:,.0f} hours with these inputs "
            f"(the pressure disturbance then reaches the drainage radius). After that the flow is "
            f"pseudosteady - choose that regime, or enlarge the drainage radius.")


def multiplier_note(case):
    """One plain line about the VLP multipliers of a case, or '' when both are 1.0."""
    s = case["solve"]
    g, f = s["gravity_mult"], s["friction_mult"]
    if g == 1.0 and f == 1.0:
        return ""
    return f"VLP matching is ON: gravity multiplier {g:.2f}, friction multiplier {f:.2f}"


def match_from_test(inputs, test_rate, test_p_wh, test_pwf, fit="friction", test_gl_rate=None, test_gl_md=None):
    """VLP matching from one measured test.

    inputs     : the page inputs (the multipliers in them are ignored: the plain correlation is matched)
    test_rate  : measured rate (STB/d of liquid for oil, Mscf/d for gas)
    test_p_wh  : wellhead flowing pressure during the test (psig, as typed on the page)
    test_pwf   : measured flowing bottom-hole pressure (psig), at the perforation depth
    fit        : 'friction' (recommended) or 'gravity': the multiplier to find
    test_gl_rate, test_gl_md : gas lift gas rate (Mscf/d) and injection depth (MD, ft) during the test; used only
                 when the well is on continuous gas lift (otherwise they are ignored); None = the page's values

    Returns {"fit", "multiplier", "plain_pwf", "matched_pwf"}:
        multiplier   the answer, rounded to 2 decimals (what the page's slider can hold)
        plain_pwf    the bottom-hole pressure (psig) the correlation gives for the test WITHOUT any multiplier
        matched_pwf  the pressure (psig) it gives WITH the (rounded) multiplier, to show how close it gets
    Raises ValueError with a plain message when the test cannot be matched.
    """
    if test_rate <= 0:
        raise ValueError("The test rate must be above 0.")
    test_p_wh, test_pwf = to_psia(test_p_wh), to_psia(test_pwf)      # the page is in psig, the engine in psia
    changes = {"gravity_mult": 1.0, "friction_mult": 1.0}
    if inputs.get("lift") == "continuous":                 # the gas lift of the test (greyed out on the page otherwise)
        if test_gl_rate is not None:
            changes["gl_rate"] = test_gl_rate
        if test_gl_md is not None:
            changes["gl_md"] = test_gl_md
    case = build_case({**inputs, **changes})
    s = case["solve"]
    fluid_test = fluid_at_rate(s["fluid"], s["ipr_function"], s["p_res"], s["ipr_inputs"], test_rate)
    multiplier = match_vlp_multiplier(s["well"], fluid_test, test_rate, test_p_wh, test_pwf,
                                      s["correlation"], s["max_step_ft"], fit,
                                      MULTIPLIER_MIN, MULTIPLIER_MAX, message_offset=ATM, message_unit="psig")
    multiplier = round(multiplier, 2)
    g, f = (1.0, multiplier) if fit == "friction" else (multiplier, 1.0)

    def pwf_for(gravity_mult, friction_mult):
        return pressure_traverse(s["well"], fluid_test, test_rate, test_p_wh, s["correlation"],
                                 s["max_step_ft"], gravity_mult, friction_mult)["pwf"]
    return {"fit": fit, "multiplier": multiplier,
            "plain_pwf": to_psig(pwf_for(1.0, 1.0)), "matched_pwf": to_psig(pwf_for(g, f))}


# =====================================================================
# VLP comparison and matching with a measured pressure survey (a gauge reading or a flowing gradient survey)
# =====================================================================
SURVEY_MAX_POINTS = 10                                  # a gauge reading or a gradient survey rarely needs more
SURVEY_COLUMNS = ("Depth MD (ft)", "Pressure (psig)")

CORRELATION_NAMES = {"gray": "Gray", "hagedorn_brown": "Hagedorn and Brown", "duns_ros": "Duns and Ros",
                     "beggs_brill": "Beggs and Brill", "orkiszewski": "Orkiszewski",
                     "mukherjee_brill": "Mukherjee and Brill",
                     "ansari": "Ansari et al (mechanistic)",
                     "fancher_brown": "Fancher and Brown (no slip, quality check)"}


def survey_points(records, md_bottom=None):
    """The measured points from the table of the page: a list of dicts (or rows) with the two columns of
    SURVEY_COLUMNS.  Empty rows are skipped; a row with only one of the two numbers is an error.
    md_bottom is the depth of the perforations (the bottom of the calculation).
    Returns ([depths], [pressures]) sorted by depth.  Raises ValueError with a plain message."""
    points = []
    for n, row in enumerate(records, start=1):
        d, p = row.get(SURVEY_COLUMNS[0]), row.get(SURVEY_COLUMNS[1])
        blank_d = d is None or (isinstance(d, float) and math.isnan(d))
        blank_p = p is None or (isinstance(p, float) and math.isnan(p))
        if blank_d and blank_p:
            continue
        if blank_d or blank_p:
            raise ValueError(f"Point {n} needs both a depth and a pressure.")
        d, p = float(d), float(p)
        if d < 0 or p <= 0:
            raise ValueError(f"Point {n}: the depth must be 0 or more and the pressure above 0.")
        if md_bottom is not None and d > md_bottom + 1e-6:
            raise ValueError(f"Point {n}: the depth {d:,.0f} ft is below the perforations ({md_bottom:,.0f} ft MD), "
                             "where the calculation ends.")
        points.append((d, p))
    if not points:
        raise ValueError("Enter at least one measured point (depth and pressure).")
    if len(points) > SURVEY_MAX_POINTS:
        raise ValueError(f"At most {SURVEY_MAX_POINTS} points can be used.")
    points.sort()
    return [d for d, _ in points], [p for _, p in points]


def survey_test_inputs(inputs, test):
    """The page inputs changed to the conditions of the survey, and the rate to run.

    test: p_wh (wellhead flowing pressure, psig), rate (STB/d for oil, Mscf/d for gas),
          rate_type ('liquid' or 'oil'; oil wells only), water_cut (fraction) and gor (scf/STB; 0 = the page's
          solution GOR) for an oil well, cgr and wgr (STB/MMscf) for a gas well, gl_rate (Mscf/d) and
          gl_md (ft MD): the gas lift of the test, used only when the page has continuous gas lift.
    Returns (inputs for build_case, rate that pressure_traverse needs: liquid for oil, gas for gas)."""
    i = {**DEFAULTS, **inputs, "gravity_mult": 1.0, "friction_mult": 1.0}
    if test["rate"] <= 0:
        raise ValueError("The test rate must be above 0.")
    i["p_wh"] = test["p_wh"]
    if i["fluid_type"] == "oil":
        wc = test["water_cut"]
        if not 0.0 <= wc < 1.0:
            raise ValueError("The water cut must be from 0 to below 100 %.")
        i["water_cut"], i["oil_gor"] = wc, test["gor"]
        rate = test["rate"] / (1.0 - wc) if test.get("rate_type") == "oil" else test["rate"]
    else:
        i["cgr"], i["wgr"] = test["cgr"], test["wgr"]
        rate = test["rate"]
    if i["lift"] == "continuous":
        i["gl_rate"], i["gl_md"] = test["gl_rate"], test["gl_md"]
    return i, rate


def _test_fluid(inputs, test, key):
    """(well data, fluid, liquid-or-gas rate, max step) of the survey test, for the correlation `key`."""
    i, rate = survey_test_inputs(inputs, test)
    s = build_case({**i, "correlation": key})["solve"]
    fluid = fluid_at_rate(s["fluid"], s["ipr_function"], s["p_res"], s["ipr_inputs"], rate)
    return s, fluid, rate


def compare_to_survey(inputs, test, depths, pressures, keys, matched=None):
    """Run the test conditions with each correlation and compare the pressure at the measured depths.

    keys    : correlations to run (each with both multipliers 1.0, as published)
    matched : optional (key, gravity_mult, friction_mult): one more run, of that correlation with its multipliers
    Returns {"rate", "depths", "measured", "rows", "curves", "best"}.  A row has label, key, ok, error, calc (pressure
    at each measured depth), err (calculated - measured), bias (mean error), mae (mean absolute error), rms (psi)
    and pct (mean absolute error as % of the measured pressures).  curves[label] = (md list, pressure list).
    best is the label with the smallest rms (the no-slip quality-check bound is never picked)."""
    runs = [(CORRELATION_NAMES[k], k, 1.0, 1.0) for k in keys]
    if matched:
        runs.append((CORRELATION_NAMES[matched[0]].split(" (")[0] + f" matched (gravity x{matched[1]:.2f}, friction x{matched[2]:.2f})",
                     matched[0], matched[1], matched[2]))
    meas = np.asarray(pressures, dtype=float)              # measured: psig, like everything the page shows
    rate, rows, curves = None, [], {}
    for label, key, g, f in runs:
        row = {"label": label, "key": key, "ok": False, "error": "", "calc": [], "err": [], "bias": None,
               "mae": None, "rms": None, "pct": None}
        try:
            s, fluid, rate = _test_fluid(inputs, test, key)
            tr = pressure_traverse(s["well"], fluid, rate, s["p_wh"], key, s["max_step_ft"], g, f)
            calc = np.interp(depths, tr["md"], tr["p"]) - ATM        # the traverse is psia; compare in psig
            err = calc - meas
            row.update(ok=True, calc=[float(x) for x in calc], err=[float(x) for x in err], bias=float(err.mean()),
                       mae=float(np.abs(err).mean()), rms=float(np.sqrt((err ** 2).mean())),
                       pct=float(100.0 * np.abs(err / meas).mean()))
            curves[label] = ([float(x) for x in tr["md"]], [float(x) - ATM for x in tr["p"]])
        except (ValueError, RuntimeError, NotImplementedError) as error:
            row["error"] = str(error)
        rows.append(row)
    ranked = [r for r in rows if r["ok"] and r["key"] not in QC_ONLY and "matched" not in r["label"]]
    best = min(ranked, key=lambda r: r["rms"])["label"] if ranked else None
    return {"rate": rate, "depths": list(depths), "measured": list(pressures), "rows": rows, "curves": curves, "best": best}


def match_to_survey(inputs, test, depths, pressures, correlation, fit="both"):
    """Find the gravity and friction multipliers that bring `correlation` closest to the survey (see
    nodal.match_vlp_survey).  The multipliers are rounded to 2 decimals (what the sliders hold); the errors
    given are for the rounded values.  Returns {"gravity", "friction", "rms_before", "rms_after", "at_limit"}."""
    s, fluid, rate = _test_fluid(inputs, test, correlation)
    p_abs = [to_psia(p) for p in pressures]                # the engine works in psia; the errors are the same either way
    found = match_vlp_survey(s["well"], fluid, rate, s["p_wh"], depths, p_abs, correlation, s["max_step_ft"],
                             fit, MULTIPLIER_MIN, MULTIPLIER_MAX)
    g, f = round(found["gravity"], 2), round(found["friction"], 2)
    tr = pressure_traverse(s["well"], fluid, rate, s["p_wh"], correlation, s["max_step_ft"], g, f)
    err = np.interp(depths, tr["md"], tr["p"]) - np.asarray(p_abs, dtype=float)
    found.update(gravity=g, friction=f, rms_after=float(np.sqrt((err ** 2).mean())))
    return found


def correlation_caption(inputs, key):
    """The sentence(s) shown under the VLP correlation box: whether the correlation looks suitable for the well
    entered, why, and the pointer to the comparison with measured data."""
    advice = correlation_advice(inputs)[key]
    name = CORRELATION_NAMES[key]
    phrase = {"good": "looks well suited to this well", "ok": "should be usable for this well",
              "caution": "may not suit this well"}[advice["rating"]]
    text = f"**{name}** {phrase}. " + " ".join(advice["notes"])
    best = recommend_correlation(inputs)[0]
    if best != key:
        text += f" From the fluid and well entered, the app would suggest {CORRELATION_NAMES[best]}."
    return (text + " This only uses the fluid, equipment and well path entered. If you have a downhole pressure "
            "gauge reading or a flowing gradient survey, compare the correlations with it on the *VLP comparison* "
            "tab and match the one you keep.")


# =====================================================================
# Charts (matplotlib Figure objects; the page shows them with st.pyplot)
# =====================================================================
GAS_COLOR = "#1d8a7e"      # gas lift injection (teal)
IPR_COLOR = "#1f77b4"
VLP_COLOR = "#d95f02"


def rate_unit(rate_label):
    """The unit inside the brackets of a rate label: 'Liquid rate (STB/d)' -> 'STB/d'."""
    if "(" in rate_label and rate_label.rstrip().endswith(")"):
        return rate_label.rsplit("(", 1)[1].rstrip().rstrip(")")
    return ""


# All three charts on the page use the same figure size and the same plot rectangle, so that the
# top and bottom edges of the plots line up when they stand side by side.  The strip above the plot
# frame is free for text (the summary on the IPR/VLP chart, the top temperature axis on the profile).
FIGSIZE = (6.2, 4.9)
PLOT_RECT = [0.14, 0.12, 0.82, 0.68]          # left, bottom, width, height (fractions of the figure)


def _new_figure():
    """A figure with the standard plot area; returns (figure, axes)."""
    fig = Figure(figsize=FIGSIZE)
    ax = fig.add_axes(PLOT_RECT)
    return fig, ax


def _summary_strip(fig, items, size=12.5, widths=None):
    """Write 'label / big value / small note' blocks in the strip above the plot frame.
    items : list of (label, value, note); note may be ''.
    widths: relative width of each block (default: all equal)."""
    n = len(items)
    widths = widths or [1.0] * n
    starts = [sum(widths[:k]) / sum(widths) for k in range(n)]
    for k, (label, value, note) in enumerate(items):
        x = PLOT_RECT[0] + starts[k] * PLOT_RECT[2]
        fig.text(x, 0.955, label, fontsize=8, color="#666666", va="top")
        fig.text(x, 0.915, value, fontsize=size, fontweight="bold", color="#222222", va="top")
        if note:
            fig.text(x, 0.855, note, fontsize=7.5, color="#666666", va="top")


def make_nodal_figure(cv, result, rate_label, water_cut=0.0, gas_lift=None):
    """IPR and VLP curves with the operating point.  The operating rate, flowing bottom-hole pressure
    and AOF are summarised in the strip above the plot (water_cut > 0 adds the oil rate).
    gas_lift : the case's gas lift data (rate, md), or None; the VLP legend then says it includes gas lift."""
    fig, ax = _new_figure()
    # The chart is in gauge pressure, like every pressure on the page; the numbers arrive as psia.
    ipr_g = [to_psig(p) for p in cv["ipr_pwf"]]
    vlp_g = [to_psig(p) for p in cv["vlp_pwf"]]
    ax.plot(cv["ipr_q"], ipr_g, color=IPR_COLOR, lw=2.2, label="IPR (reservoir inflow)")
    vlp_label = "VLP (tubing outflow)"
    if gas_lift and gas_lift["rate"] > 0:
        vlp_label = f"VLP with gas lift ({gas_lift['rate']:,.0f} Mscf/d)"
    ax.plot(cv["vlp_q"], vlp_g, color=VLP_COLOR, lw=2.2, label=vlp_label)
    unit = rate_unit(rate_label)
    if result["found"]:
        pwf_g = to_psig(result["pwf"])
        ax.plot(result["q"], pwf_g, "o", color="black", ms=10, label="Operating point")
        # Both numbers get their unit: the rate (STB/d or Mscf/d) and the pressure (psig)
        rate_text = f"{result['q']:,.0f} {unit}".strip()
        # The label sits directly above the point (white background so it stays readable over a curve)
        ax.annotate(f"{rate_text}\n{pwf_g:,.0f} psig", (result["q"], pwf_g),
                    textcoords="offset points", xytext=(0, 11), ha="center", va="bottom", fontsize=9,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8), zorder=6)
        note = f"oil {result['q'] * (1.0 - water_cut):,.0f} {unit} (water cut {water_cut * 100:.0f} %)" if water_cut > 0 else ""
        items = [("Operating rate", rate_text, note),
                 ("Flowing bottom-hole pressure", f"{pwf_g:,.0f} psig", "")]
    else:
        items = [("Operating point", "none: the well does not flow", ""),
                 ("", "", "")]
    items.append(("AOF (inflow at Pwf = 0)", f"{result['aof']:,.0f} {unit}".strip(), ""))
    _summary_strip(fig, items, widths=[0.95, 1.2, 1.0])
    ax.set_xlabel(rate_label)
    ax.set_ylabel("Flowing bottom-hole pressure (psig)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=9)      # the lower-left corner is empty: the IPR starts at Pr
    return fig


def make_multilayer_figure(layers, pb, crossflow=False, n_points=60):
    """The IPR of each layer (thin lines) and the composite IPR of all layers together (thick line),
    flowing bottom-hole pressure against liquid rate.
    layers    : the list from multilayer_layers() ({"p_res" psia, "J", ...})
    pb        : bubble point (psia), shared by all layers
    crossflow : the same option as the IPR (a layer below Pwf takes fluid, or is simply shut)
    The composite is the sum of the layer rates at each Pwf; its kinks are where Pwf passes a layer pressure."""
    p_top = max(layer["p_res"] for layer in layers)
    grid = {p_top * k / (n_points - 1) for k in range(n_points)}
    grid.update(layer["p_res"] for layer in layers)               # a point at every layer pressure keeps the kinks sharp
    pwfs = sorted(grid, reverse=True)
    per_layer = [[] for _ in layers]
    total = []
    pwfs_g = [to_psig(p) for p in pwfs]                 # the chart is in gauge pressure
    for pwf in pwfs:
        rates = ipr.multilayer_rates(p_top, pwf, pb, layers, crossflow)
        for k, q in enumerate(rates):
            per_layer[k].append(q)
        total.append(sum(rates))
    fig = Figure(figsize=(10.0, 3.9))
    ax = fig.add_axes([0.075, 0.15, 0.9, 0.8])
    colors = colormaps["tab10"]
    for k, (layer, qs) in enumerate(zip(layers, per_layer), start=1):
        ax.plot(qs, pwfs_g, color=colors((k - 1) % 10), lw=1.3, ls="--",
                label=f"Layer {k}: {to_psig(layer['p_res']):,.0f} psig, PI {layer['J']:.2f}")
    ax.plot(total, pwfs_g, color="black", lw=2.4, label=f"Composite IPR (AOF {total[-1]:,.0f} STB/d)")
    ax.set_xlabel("Liquid rate (STB/d)")
    ax.set_ylabel("Flowing bottom-hole pressure (psig)")
    ax.set_xlim(left=min(0.0, min(min(qs) for qs in per_layer)))
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=8)
    return fig


def make_gas_multilayer_figure(layers, crossflow=False, n_points=60):
    """The IPR of each gas layer (thin lines) and the composite IPR of all layers (thick line), flowing bottom-hole
    pressure against gas rate.  layers: the list from gas_multilayer_layers()."""
    p_top = max(layer["p_res"] for layer in layers)
    grid = {p_top * k / (n_points - 1) for k in range(n_points)}
    grid.update(layer["p_res"] for layer in layers)
    pwfs = sorted(grid, reverse=True)
    per_layer = [[] for _ in layers]
    total = []
    pwfs_g = [to_psig(p) for p in pwfs]                 # the chart is in gauge pressure
    for pwf in pwfs:
        rates = ipr.gas_multilayer_rates(p_top, pwf, layers, crossflow)
        for k, q in enumerate(rates):
            per_layer[k].append(q)
        total.append(sum(rates))
    fig = Figure(figsize=(10.0, 3.9))
    ax = fig.add_axes([0.075, 0.15, 0.9, 0.8])
    colors = colormaps["tab10"]
    for k, (layer, qs) in enumerate(zip(layers, per_layer), start=1):
        ax.plot(qs, pwfs_g, color=colors((k - 1) % 10), lw=1.3, ls="--",
                label=f"Layer {k}: {to_psig(layer['p_res']):,.0f} psig, AOF {qs[-1]:,.0f}")
    ax.plot(total, pwfs_g, color="black", lw=2.4, label=f"Composite IPR (AOF {total[-1]:,.0f} Mscf/d)")
    ax.set_xlabel("Gas rate (Mscf/d)")
    ax.set_ylabel("Flowing bottom-hole pressure (psig)")
    ax.set_xlim(left=min(0.0, min(min(qs) for qs in per_layer)))
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=8)
    return fig


def pressure_gradients(traverse, n=5):
    """Pressure gradient in psi per ft of TRUE VERTICAL depth, at n evenly spaced depths (TVD).
    Each value is the pressure change divided by the vertical depth change over a window of 80 % of the
    spacing around the depth, so one small step of the calculation cannot make it jump.
    Returns a list of (tvd, pressure, gradient)."""
    tvd, p = traverse["tvd"], traverse["p"]
    top, bottom = tvd[0], max(tvd)
    out = []
    for k in range(n):
        centre = top + (bottom - top) * (k + 0.5) / n
        half = 0.4 * (bottom - top) / n
        p1, p2 = float(np.interp(centre - half, tvd, p)), float(np.interp(centre + half, tvd, p))
        out.append((float(centre), float(np.interp(centre, tvd, p)), (p2 - p1) / (2.0 * half)))
    return out


def make_profile_figure(traverse, n_gradients=5, injection_md=None):
    """Pressure and temperature against vertical depth, at the operating rate, in ONE plot:
    pressure on the TOP horizontal axis (the more important one), temperature on the bottom axis.
    A few pressure-gradient values (psi per ft of true vertical depth) are written along the pressure curve."""
    fig, ax_t = _new_figure()                # bottom horizontal axis: temperature
    ax_p = ax_t.twiny()                      # second horizontal axis (on top): pressure, same depth axis
    line_t, = ax_t.plot(traverse["T"], traverse["tvd"], color=VLP_COLOR, lw=2.2, ls="--",
                        label="Temperature (bottom axis)")
    p_gauge = [to_psig(p) for p in traverse["p"]]        # the chart is in gauge pressure
    line_p, = ax_p.plot(p_gauge, traverse["tvd"], color=IPR_COLOR, lw=2.2, label="Pressure (top axis)")
    # Colour each axis like its curve so it is clear which axis belongs to which curve
    ax_p.set_xlabel("Pressure (psig)", color=IPR_COLOR)
    ax_p.tick_params(axis="x", colors=IPR_COLOR)
    ax_t.set_xlabel("Temperature (degF)", color=VLP_COLOR)
    ax_t.tick_params(axis="x", colors=VLP_COLOR)
    ax_t.set_ylabel("True vertical depth (ft)")
    ax_t.set_ylim(max(traverse["tvd"]), 0)   # depth increases downwards (the top axis shares it)
    ax_p.set_xlim(left=0)                    # pressure starts at 0 psig, so the wellhead pressure reads off easily
    ax_p.grid(alpha=0.3)
    # Pressure gradients: a dot on the pressure curve and the value (psi/ft) just to the right of it
    gradients = pressure_gradients(traverse, n_gradients)
    dots, = ax_p.plot([to_psig(g[1]) for g in gradients], [g[0] for g in gradients], "o", color=IPR_COLOR, ms=5,
                      mfc="white", mew=1.6, zorder=5, label="Pressure gradient (psi/ft TVD)")
    for depth, pressure, grad in gradients:
        ax_p.annotate(f"{grad:.3f}", (to_psig(pressure), depth), textcoords="offset points", xytext=(7, 1),
                      ha="left", va="center", fontsize=8.5, color=IPR_COLOR, fontweight="bold",
                      bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.8), zorder=6)
    if injection_md:                         # gas lift: mark the depth where the lift gas joins the flow
        tvd_inj = float(np.interp(injection_md, traverse["md"], traverse["tvd"]))
        ax_t.axhline(tvd_inj, color=GAS_COLOR, lw=1.6, ls=(0, (4, 3)), zorder=2)
        ax_t.text(0.985, tvd_inj, f"gas injection, {injection_md:,.0f} ft MD", color=GAS_COLOR, fontsize=8.5,
                  fontweight="bold", ha="right", va="bottom", transform=ax_t.get_yaxis_transform(),
                  bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.8), zorder=6)
    # Both curves rise with depth, so the lower-left corner is empty
    ax_t.legend(handles=[line_p, line_t, dots], loc="lower left", fontsize=8.5)
    return fig


SURVEY_COLORS = ["#1f77b4", "#d95f02", "#2ca02c", "#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22"]


def make_survey_figure(comparison):
    """Pressure against measured depth for every correlation of compare_to_survey(), with the measured points
    (black squares) on top: the usual way measured pressures are compared with the correlations."""
    fig, ax = _new_figure()
    deepest = max(comparison["depths"])
    for k, (label, (md, p)) in enumerate(comparison["curves"].items()):
        matched = "matched" in label
        ax.plot(p, md, lw=2.2 if matched else 1.8, ls="--" if matched else "-",
                color="black" if matched else SURVEY_COLORS[k % len(SURVEY_COLORS)], label=label)
        deepest = max(deepest, md[-1])
    ax.plot(comparison["measured"], comparison["depths"], "s", color="black", mfc="#ffd43b", ms=8, mew=1.5,
            zorder=6, label="Measured")
    ax.set_xlabel("Pressure (psig)")
    ax.set_ylabel("Measured depth (ft)")
    ax.set_ylim(deepest * 1.02, 0)
    ax.set_xlim(left=0)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", fontsize=8)
    return fig


def make_sensitivity_figure(results, label, rate_label, rate_key="q"):
    """Production rate against the varied input (rate_key: "q" = the operating rate, "q_oil" = oil rate).
    Points where the well does not flow are red crosses."""
    fig, ax = _new_figure()
    flowing = [(r["value"], r[rate_key]) for r in results if r["found"]]
    dead = [r["value"] for r in results if not r["found"]]
    if flowing:
        ax.plot([v for v, _ in flowing], [q for _, q in flowing], "o-", color=IPR_COLOR, lw=2.2, ms=7)
    if dead:
        ax.plot(dead, [0.0] * len(dead), "x", color="red", ms=10, mew=2.5, clip_on=False,
                label="Well does not flow")
        ax.legend(fontsize=9, loc="best")
    fig.text(PLOT_RECT[0], 0.955, "Sensitivity", fontsize=8, color="#666666", va="top")
    fig.text(PLOT_RECT[0], 0.915, f"{rate_label.split(' (')[0]} against {label.split(' (')[0].lower()}",
             fontsize=12.5, fontweight="bold", color="#222222", va="top")
    ax.set_xlabel(label)
    ax.set_ylabel(rate_label)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    return fig


def _split_label(label):
    """'Wellhead pressure (psia)' -> ('Wellhead pressure', 'psia');  no brackets -> (label, '')."""
    if label.endswith(")") and " (" in label:
        name, unit = label[:-1].rsplit(" (", 1)
        return name, unit
    return label, ""


# Which curve each sensitivity input changes: the IPR (what the reservoir gives) or the VLP (the tubing).
# (The VLP is calculated over a rate range that follows the AOF, so the two cannot be told apart by comparing
#  the curve points - the input decides.)
IPR_INPUTS = ("p_res", "pi", "k", "kh", "length", "skin", "ml_pi_mult")


def make_sensitivity_nodal_figure(results, label, rate_label, key="p_wh"):
    """IPR / VLP chart for a sensitivity: one curve for every value of the varied input.

    results : run_sensitivity(..., with_curves=True)
    The curves that change with the input are drawn once per value, in shades of the usual colour
    (VLP orange, IPR blue; darker = larger value), with the operating point of each value as a black dot.
    The curve that does not change (for example the IPR when the wellhead pressure is varied) is drawn once.
    key     : the sensitivity input (as in sensitivity_options); it decides whether the IPR or the VLP changes.
    The strip above the plot gives the range of the operating rate and bottom-hole pressure."""
    fig, ax = _new_figure()
    name, unit = _split_label(label)
    unit_text = rate_unit(rate_label)
    usable = [r for r in results if r.get("curves")]
    if not usable:
        ax.text(0.5, 0.5, "No curves to show", transform=ax.transAxes, ha="center")
        return fig
    ipr_varies = key in IPR_INPUTS
    vlp_varies = not ipr_varies
    # the curve that does not change: take the run whose curve reaches the highest rate (the longest one)
    fixed = max(usable, key=lambda r: r["curves"]["vlp_q"][-1] if ipr_varies else r["curves"]["ipr_q"][0])["curves"]
    shades = [0.35 + 0.6 * k / max(len(usable) - 1, 1) for k in range(len(usable))]   # light -> dark

    def tag(r):
        text = f"{r['value']:,.4g} {unit}".strip()
        return text if r["found"] else text + " (no flow)"

    if not ipr_varies:
        ax.plot(fixed["ipr_q"], [to_psig(p) for p in fixed["ipr_pwf"]], color=IPR_COLOR, lw=2.4, label="IPR (reservoir inflow)")
    if not vlp_varies:
        ax.plot(fixed["vlp_q"], [to_psig(p) for p in fixed["vlp_pwf"]], color=VLP_COLOR, lw=2.4, label="VLP (tubing outflow)")
    for r, shade in zip(usable, shades):
        if ipr_varies:
            ax.plot(r["curves"]["ipr_q"], [to_psig(p) for p in r["curves"]["ipr_pwf"]], color=colormaps["Blues"](shade), lw=2.0,
                    label=f"IPR, {tag(r)}")
        if vlp_varies:
            ax.plot(r["curves"]["vlp_q"], [to_psig(p) for p in r["curves"]["vlp_pwf"]], color=colormaps["Oranges"](shade), lw=2.0,
                    label=f"VLP, {tag(r)}")
    found = [r for r in results if r["found"]]
    if found:
        ax.plot([r["q"] for r in found], [to_psig(r["pwf"]) for r in found], "o", color="black", ms=7, zorder=5,
                label="Operating points")
    ax.set_xlabel(rate_label)
    ax.set_ylabel("Flowing bottom-hole pressure (psig)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=7.5, title=name, title_fontsize=8, framealpha=0.9)

    values = [r["value"] for r in results]
    items = [("Varied input", name, f"{min(values):,.4g} to {max(values):,.4g} {unit}".strip())]
    if found:
        items.append((f"Operating rate ({unit_text})", f"{min(r['q'] for r in found):,.0f} - {max(r['q'] for r in found):,.0f}", ""))
        items.append(("Flowing bottom-hole pressure (psig)",
                      f"{to_psig(min(r['pwf'] for r in found)):,.0f} - {to_psig(max(r['pwf'] for r in found)):,.0f}", ""))
    else:
        items.append(("Operating point", "none: the well does not flow", ""))
    _summary_strip(fig, items, size=10.5, widths=[1.15, 1.0, 1.15])
    return fig


# =====================================================================
# Sensitivities
# =====================================================================

def survey_rows(text):
    """The rows of a survey text ("MD TVD" per line) as a list of [md, tvd] numbers, for the survey table."""
    return [[float(x) for x in line.split()[:2]] for line in text.strip().splitlines() if len(line.split()) >= 2]


def survey_text_from_table(records, columns=("MD (ft)", "TVD (ft)")):
    """Turn the rows of the survey table (a list of dictionaries, as pandas gives them) into the "MD TVD"
    text that parse_survey_text() reads.  Rows where either number is empty are skipped, so the empty rows
    at the bottom of the table do no harm."""
    lines = []
    for row in records:
        md, tvd = row.get(columns[0]), row.get(columns[1])
        if md is None or tvd is None or md != md or tvd != tvd:        # empty cell (None or NaN)
            continue
        lines.append(f"{md:g} {tvd:g}")
    return "\n".join(lines)


def perforation_md(inputs):
    """Measured depth of the perforations (ft) from the page inputs, or None if the survey cannot be read."""
    i = {**DEFAULTS, **inputs}
    try:
        return (vertical_survey(i["depth"])[0] if i["survey_mode"] == "vertical"
                else parse_survey_text(i["survey_text"])[0])[-1]
    except ValueError:
        return None


# =====================================================================
# Which VLP correlation suits this well?
# =====================================================================
# No correlation fits every well, and there is no universal rule for choosing one, so this part does two honest
# things and nothing more:
#   1. correlation_advice(): rules taken from the correlations' own papers and from common field practice, applied to the
#      fluid, the well path and the water cut.  It rates each correlation "good", "ok" or "caution", with the reason.
#   2. check_correlations(): runs the case with every correlation and shows what each one gives (operating rate and
#      bottom-hole pressure, the flow patterns it meets), so a correlation that is far from the others, or a well
#      that is mostly in mist flow, is seen at once.  Only a measured flowing pressure (VLP matching) can say
#      which one is right.
DEVIATED_ABOVE_DEG = 30.0       # a well steeper than this from vertical anywhere counts as deviated (rule of thumb)
GRAY_MAX_CGR = 50.0             # STB/MMscf: Gray holds up to about this condensate ratio (common field guidance)
DUNS_ROS_MAX_WATER_CUT = 0.10   # Duns and Ros (1963) tested with less than 10 % water
MIST_SHARE_LIMIT = 0.5          # Duns and Ros finds mist or transition flow over more than this share of the well
HEAVY_OIL_API = 20.0            # Orkiszewski (1967) was found best for heavy oil
CHECK_OUTLIER = 0.25            # a correlation's rate this far from the median of the others is called out

# The order in which equal ratings are decided (the first is the default when nothing speaks against it)
PREFERENCE_OIL = ("hagedorn_brown", "mukherjee_brill", "duns_ros", "orkiszewski", "ansari", "beggs_brill")
PREFERENCE_GAS = ("gray", "duns_ros", "mukherjee_brill", "hagedorn_brown", "orkiszewski", "ansari", "beggs_brill")
_RATING_RANK = {"good": 0, "ok": 1, "caution": 2}
# Fancher and Brown ignores slip, so it gives the lowest VLP of all, and it is useful only as a quality-check bound:
# it should never be used for a real calculation.  It is shown in the comparison but never recommended and never
# counted in the median that the other correlations are compared with.
QC_ONLY = ("fancher_brown",)
QC_NOTE = ("A quality-check bound, not a method to rely on: it ignores slip, so it gives the lowest pressure. "
           "A measured flowing pressure below it points to a wrong fluid density (PVT) or wrong pressure data.")


def max_inclination_deg(inputs):
    """The steepest part of the well, in degrees from vertical (0 = vertical, 90 = horizontal)."""
    i = {**DEFAULTS, **inputs}
    if i["survey_mode"] == "vertical":
        return 0.0
    try:
        md, tvd = parse_survey_text(i["survey_text"])
    except ValueError:
        return 0.0
    worst = 0.0
    for k in range(1, len(md)):
        d_md, d_tvd = md[k] - md[k - 1], tvd[k] - tvd[k - 1]
        if d_md > 0:
            worst = max(worst, math.degrees(math.acos(max(-1.0, min(1.0, d_tvd / d_md)))))
    return worst


def _gas_cgr(i):
    """The condensate-gas ratio (STB/MMscf) of a gas case; for a multilayer well, the highest layer value."""
    if i.get("gas_ipr") == "multilayer":
        try:
            return max(layer["cgr"] for layer in gas_multilayer_layers(i))
        except (ValueError, KeyError, TypeError):
            return 0.0
    return i["cgr"]


def correlation_advice(inputs):
    """Rate every correlation of this fluid type for this well.

    Returns {key: {"rating": "good" | "ok" | "caution", "notes": [short sentences]}}.  The rules and where they
    come from (the correlations' own papers, and field practice where no paper says it):
      * well steeper than DEVIATED_ABOVE_DEG: Mukherjee and Brill is the only coded correlation made for any angle
        (uphill and downhill); the vertical-flow ones only scale the gravity part by the pipe angle.
      * oil: Hagedorn and Brown does well in slug flow at moderate to high rates (its test well was mostly in slug
        flow); Duns and Ros covers mist flow and high GOR but was tested with less than 10 % water (its paper);
        Beggs and Brill was built for pipelines and generally over-predicts the pressure drop in wells; Orkiszewski
        often matches well but his formulas jump where the flow pattern changes, and he found his method best for
        heavy oil (his paper); Ansari is a mechanistic model made for vertical wells.
      * gas: Gray holds up to a condensate ratio of about 50 STB/MMscf and with high water ratios; above that
        Duns and Ros is the usual choice; Hagedorn and Brown should not be used for condensates.
    """
    i = {**DEFAULTS, **inputs}
    is_oil = i["fluid_type"] == "oil"
    incl = max_inclination_deg(i)
    deviated = incl > DEVIATED_ABOVE_DEG
    advice = {}

    def put(key, rating, *notes):
        advice[key] = {"rating": rating, "notes": list(notes)}

    steep = f"Made for vertical flow; this well reaches {incl:.0f} degrees from vertical, where the app only scales the gravity part by the pipe angle."
    if is_oil:
        wc, api = i["water_cut"], i["api"]
        put("hagedorn_brown", "caution" if deviated else "good",
            *([steep] if deviated else ["Performs well in slug flow at moderate to high rates: the test well "
                                        "behind the correlation (SPE 940-PA) was mostly in slug flow."]),
            "Poor at low rates (well loading) and not for mist flow.")
        put("mukherjee_brill", "good" if deviated else "ok",
            *(["Made for any angle, uphill or downhill."] if deviated else ["Works at any angle; in a vertical well other correlations are better tested."]))
        notes = ["Its Region III was built for mist flow and it covers high gas-liquid ratios (Duns and Ros, 1963); it tends to over-predict the VLP of oil wells."]
        rating = "ok"
        if wc > DUNS_ROS_MAX_WATER_CUT:
            rating = "caution"
            notes.insert(0, f"Tested with less than 10 % water; this well makes {100 * wc:.0f} %.")
        if deviated:
            rating = "caution"
            notes.insert(0, steep)
        put("duns_ros", rating, *notes)
        heavy = api < HEAVY_OIL_API
        put("orkiszewski", "caution" if deviated else ("good" if heavy else "ok"),
            *([steep] if deviated else []),
            *(["Found best for heavy oil in the paper."] if heavy else []),
            "Often matches well, but his formulas jump where the flow pattern changes, so the traverse can be unsteady.")
        put("ansari", "caution" if deviated else "ok",
            *([steep] if deviated else ["Mechanistic model made and tested for vertical wells."]))
        put("beggs_brill", "caution", "Built from an inclined pipeline test loop (Beggs and Brill, 1973); it generally over-predicts the pressure drop in vertical and deviated wells.")
        put("fancher_brown", "caution", QC_NOTE)
    else:
        cgr = _gas_cgr(i)
        gray_notes = []
        gray_rating = "good"
        if cgr > GRAY_MAX_CGR:
            gray_rating = "caution"
            gray_notes.append(f"Good up to about {GRAY_MAX_CGR:.0f} STB/MMscf of condensate; this well has {cgr:.0f}.")
        if deviated:
            gray_rating = "caution"
            gray_notes.append(steep)
        put("gray", gray_rating, *(gray_notes or ["Made for gas wells (Gray, 1974); it holds up with condensate to about 50 STB/MMscf and with high water ratios."]))
        put("duns_ros", "good" if cgr > GRAY_MAX_CGR and not deviated else "ok",
            *(["The usual choice where the liquid dropout is very high; a retrograde-condensate PVT would be needed too, which this app does not have."]
              if cgr > GRAY_MAX_CGR else ["Handles mist flow, which is the usual pattern in a gas well."]),
            *([steep] if deviated else []))
        put("mukherjee_brill", "good" if deviated else "ok",
            *(["Made for any angle, uphill or downhill."] if deviated else []))
        put("hagedorn_brown", "caution" if cgr > 0 or deviated else "ok",
            *(["Should not be used for condensates, or where mist flow is the main pattern: its data came from an oil and water well."] if cgr > 0 else []),
            *([steep] if deviated else []))
        put("orkiszewski", "caution" if deviated else "ok", *([steep] if deviated else []))
        put("ansari", "caution" if deviated else "ok", *([steep] if deviated else []))
        put("beggs_brill", "caution", "Mainly a pipeline correlation; tends to over- or under-estimate the pressure loss of a gas well.")
        put("fancher_brown", "caution", QC_NOTE, "Its friction lines were measured in an oil/water gas lift well, so a gas well is far outside them.")
    return advice


def recommend_correlation(inputs):
    """The correlation this app suggests for the well: the best rating from correlation_advice(), equal ratings
    decided by PREFERENCE_OIL / PREFERENCE_GAS.  Returns (key, [reasons])."""
    i = {**DEFAULTS, **inputs}
    advice = correlation_advice(i)
    order = PREFERENCE_OIL if i["fluid_type"] == "oil" else PREFERENCE_GAS
    best = min(order, key=lambda k: (_RATING_RANK[advice[k]["rating"]], order.index(k)))
    return best, advice[best]["notes"]


def _regime_shares(traverse):
    """{regime: share of the measured length} from the flow patterns of a pressure traverse."""
    md, names = traverse["md"], traverse["regime"]
    total = md[-1] - md[0]
    shares = {}
    for k, name in enumerate(names):
        shares[name] = shares.get(name, 0.0) + (md[k + 1] - md[k]) / total
    return shares


def check_correlations(inputs, keys=None):
    """Run the case with each correlation and compare what comes out (this takes a few seconds per correlation).

    Returns {"rows": [...], "suggested": key, "why": [sentences]}.  A row has: key, ok (False if the correlation
    could not solve the case; "error" says why), q (operating rate), pwf, shares (flow patterns along the well,
    share of its length), vs_median (rate difference from the median of the working correlations, as a fraction)
    and "notes" (the advice plus what this check found).
    """
    i = {**DEFAULTS, **inputs}
    is_oil = i["fluid_type"] == "oil"
    order = PREFERENCE_OIL if is_oil else PREFERENCE_GAS
    keys = list(keys or (tuple(order) + QC_ONLY))        # the quality-check bound is shown last
    advice = correlation_advice(i)
    rows = []
    for key in keys:
        row = {"key": key, "ok": False, "error": "", "q": None, "pwf": None, "shares": {}, "vs_median": None,
               "rating": advice[key]["rating"], "notes": list(advice[key]["notes"])}
        try:
            case = build_case({**i, "correlation": key})
            s = case["solve"]
            result = solve_well(**s)
            row["ok"] = True
            if result["found"]:
                row["q"], row["pwf"] = result["q"], result["pwf"]
                fluid_op = fluid_at_rate(s["fluid"], s["ipr_function"], s["p_res"], s["ipr_inputs"], result["q"])
                traverse = pressure_traverse(s["well"], fluid_op, result["q"], s["p_wh"], key, s["max_step_ft"],
                                             s["gravity_mult"], s["friction_mult"])
                row["shares"] = _regime_shares(traverse)
            else:
                row["error"] = "the well does not flow (no operating point)"
        except (ValueError, RuntimeError, NotImplementedError) as error:
            row["error"] = str(error)
        rows.append(row)

    why = []
    flowing = sorted(r["q"] for r in rows if r["q"] and r["key"] not in QC_ONLY)
    if len(flowing) >= 3:
        median = flowing[len(flowing) // 2]
        for r in rows:
            if r["q"] and r["key"] not in QC_ONLY:
                r["vs_median"] = r["q"] / median - 1.0
                if abs(r["vs_median"]) > CHECK_OUTLIER:
                    r["notes"].append(f"Its rate is {100 * r['vs_median']:+.0f} % from the median of the correlations.")
    by_key = {r["key"]: r for r in rows}
    dr = by_key.get("duns_ros")
    if dr and dr["shares"]:
        mist = dr["shares"].get("mist", 0.0) + dr["shares"].get("transition", 0.0)
        if mist > MIST_SHARE_LIMIT:
            why.append(f"Duns and Ros finds mist or transition flow over {100 * mist:.0f} % of the well. "
                       "Hagedorn and Brown should not be used where mist flow is the main pattern.")
            if "hagedorn_brown" in by_key:
                by_key["hagedorn_brown"]["rating"] = "caution"
                by_key["hagedorn_brown"]["notes"].append("Mist or transition flow over most of the well (found by Duns and Ros).")
            dr["rating"] = "good" if not (max_inclination_deg(i) > DEVIATED_ABOVE_DEG or (is_oil and i["water_cut"] > DUNS_ROS_MAX_WATER_CUT)) else dr["rating"]
    candidates = [r for r in rows if r["ok"] and r["q"] and r["key"] not in QC_ONLY]
    if not candidates:
        return {"rows": rows, "suggested": None, "why": why + ["No correlation could find an operating point."]}
    best = min(candidates, key=lambda r: (_RATING_RANK[r["rating"]],
                                          1 if (r["vs_median"] is not None and abs(r["vs_median"]) > CHECK_OUTLIER) else 0,
                                          order.index(r["key"])))
    why.append(f"Best rating for this fluid and well: {best['rating']}. " + " ".join(best["notes"][:2]))
    return {"rows": rows, "suggested": best["key"], "why": why}


def sensitivity_options(inputs):
    """The inputs the sensitivity tab offers for this case, with sensible default ranges.
    Each option is a dictionary: key, label, low, high."""
    i = {**DEFAULTS, **inputs}
    p_res_now = i["p_res"]
    gas_multilayer_on = i["fluid_type"] == "gas" and i["gas_ipr"] == "multilayer"
    if i["fluid_type"] == "oil" and i["oil_ipr"] == "multilayer":
        try:
            p_res_now = max(layer["p_res"] for layer in multilayer_layers(i))   # highest layer pressure
        except ValueError:
            pass
    if gas_multilayer_on:
        try:
            p_res_now = max(layer["p_res"] for layer in gas_multilayer_layers(i))
        except ValueError:
            pass
    options = [
        {"key": "p_wh", "label": "Wellhead pressure (psig)",
         "low": max(50.0, 0.5 * i["p_wh"]), "high": 2.0 * i["p_wh"]},
        {"key": "p_res", "label": "Reservoir pressure (psig)" + (", highest layer (others scale with it)" if p_res_now != i["p_res"] or i["oil_ipr"] == "multilayer" or gas_multilayer_on else ""),
         "low": 0.7 * p_res_now, "high": 1.2 * p_res_now},
        {"key": "tubing_id", "label": "Tubing inner diameter (in)", "low": 2.0, "high": 4.5},
    ]
    skin_models = False                                  # does the chosen IPR model have a total skin factor?
    skin_now = 0.0
    if i["fluid_type"] == "oil":
        if i["oil_ipr"] != "multilayer":         # a multilayer well gets its water cut and GOR from the layer table
            options.append({"key": "water_cut", "label": "Water cut (fraction)", "low": 0.0, "high": 0.8})
            gor_now = i["oil_gor"] if i["oil_gor"] > 0 else i["rsb"]
            options.append({"key": "gor", "label": "Total (producing) GOR (scf/STB)", "low": gor_now, "high": 2.0 * gor_now})
        if i["oil_ipr"] == "multilayer":
            options.append({"key": "ml_pi_mult", "label": "Layer PIs, all multiplied by", "low": 0.5, "high": 2.0})
        elif i["oil_ipr"] == "pi":
            options.append({"key": "pi", "label": "Productivity index (STB/d/psi)", "low": 1.0, "high": 5.0})
        elif i["oil_ipr"] == "darcy":
            options.append({"key": "k", "label": "Permeability (md)",
                            "low": 0.5 * i["oil_k"], "high": 2.0 * i["oil_k"]})
            skin_models, skin_now = True, i["oil_skin"]
        elif i["oil_ipr"] == "horizontal_kg":
            # the well must stay inside the box: half the length cannot pass the nearer end of the box
            room = 2.0 * min(i["kg_xw"], 1.0 - i["kg_xw"]) * i["kg_lx"]
            options.append({"key": "length", "label": "Horizontal well length (ft)",
                            "low": 0.5 * i["hz_length"], "high": min(2.0 * i["hz_length"], 0.98 * room)})
            options.append({"key": "kh", "label": "Horizontal permeability kh (md)",
                            "low": 0.5 * i["hz_kh"], "high": 2.0 * i["hz_kh"]})
            skin_models, skin_now = True, i["hz_skin"]
        elif i["oil_ipr"] == "horizontal":
            options.append({"key": "length", "label": "Horizontal well length (ft)",
                            "low": 0.5 * i["hz_length"], "high": min(2.0 * i["hz_length"], 1.8 * i["hz_re"])})
            options.append({"key": "kh", "label": "Horizontal permeability kh (md)",
                            "low": 0.5 * i["hz_kh"], "high": 2.0 * i["hz_kh"]})
            skin_models, skin_now = True, i["hz_skin"]
    elif i["gas_ipr"] in ("darcy", "jones"):
        options.append({"key": "k", "label": "Permeability (md)",
                        "low": 0.5 * i["gas_k"], "high": 2.0 * i["gas_k"]})
        skin_models, skin_now = True, i["gas_skin"]
    elif i["gas_ipr"] == "multilayer":
        options.append({"key": "ml_pi_mult", "label": "Layer deliverabilities, all multiplied by", "low": 0.5, "high": 2.0})
    elif i["gas_ipr"] == "horizontal":
        options.append({"key": "length", "label": "Horizontal well length (ft)",
                        "low": 0.5 * i["gh_length"], "high": min(2.0 * i["gh_length"], 1.8 * i["gh_re"])})
        options.append({"key": "kh", "label": "Horizontal permeability kh (md)",
                        "low": 0.5 * i["gh_kh"], "high": 2.0 * i["gh_kh"]})
        skin_models, skin_now = True, i["gh_skin"]
    elif i["gas_ipr"] == "horizontal_kg":
        room = 2.0 * min(i["gk_xw"], 1.0 - i["gk_xw"]) * i["gk_lx"]
        options.append({"key": "length", "label": "Horizontal well length (ft)",
                        "low": 0.5 * i["gh_length"], "high": min(2.0 * i["gh_length"], 0.98 * room)})
        options.append({"key": "kh", "label": "Horizontal permeability kh (md)",
                        "low": 0.5 * i["gh_kh"], "high": 2.0 * i["gh_kh"]})
        skin_models, skin_now = True, i["gh_skin"]
    if i["fluid_type"] == "oil" and i["lift"] == "continuous":
        perf_md = perforation_md(i)
        options.append({"key": "gl_rate", "label": "Gas injection rate (Mscf/d)",
                        "low": 0.0, "high": 2.0 * max(i["gl_rate"], 1.0)})
        high_md = 1.2 * i["gl_md"] if perf_md is None else min(1.2 * i["gl_md"], 0.95 * perf_md)
        options.append({"key": "gl_depth", "label": "Gas injection depth (ft MD)",
                        "low": 0.6 * i["gl_md"], "high": max(high_md, 0.6 * i["gl_md"] + 1.0)})
    if skin_models:
        options.append({"key": "skin", "label": "Total skin factor", "low": skin_now, "high": skin_now + 10.0})
    return options


def parse_value_list(text, low_limit=None):
    """Values typed by the user for a sensitivity, e.g. "100, 150 250;300" -> [100.0, 150.0, 250.0, 300.0].

    Commas, semicolons, spaces and line breaks all separate values.  The result is sorted from small to
    large (the charts and tables read best that way).  2 to 12 distinct values are needed.
    Raises ValueError with a plain message for anything else."""
    pieces = text.replace(";", " ").replace(",", " ").split()
    if not pieces:
        raise ValueError("Type at least two values, separated by commas.")
    values = []
    for piece in pieces:
        try:
            values.append(float(piece))
        except ValueError:
            raise ValueError(f"'{piece}' is not a number.") from None
    values = sorted(set(values))
    if len(values) < 2:
        raise ValueError("Type at least two different values.")
    if len(values) > 12:
        raise ValueError("Use at most 12 values (each one needs a full calculation).")
    if low_limit is not None and values[0] < low_limit:
        raise ValueError(f"Values cannot be below {low_limit:g}.")
    return values


def evenly_spaced(low, high, n):
    """n values from low to high, equally spaced."""
    if n < 2:
        raise ValueError("Need at least 2 values.")
    return [low + (high - low) * j / (n - 1) for j in range(n)]


_SENSITIVITY_PATHS = {"p_wh": "p_wh", "p_res": "p_res", "water_cut": "fluid.water_cut",
                      "pi": "ipr_inputs.J", "k": "ipr_inputs.k",
                      "length": "ipr_inputs.length", "kh": "ipr_inputs.kh",
                      "skin": "ipr_inputs.skin", "gor": "fluid.gor",
                      "gl_rate": "fluid.injection_gas_rate", "gl_depth": "fluid.injection_md"}


def _add_oil_rate(results, base, key):
    """Add "q_oil" to every result: the operating rate of OIL.  For an oil & water well the page works
    with the total liquid rate, so oil = liquid * (1 - water cut), using the water cut of each run
    (it is the varied input when key is "water_cut").  For a gas well it is the gas rate itself."""
    fluid = base["fluid"]
    for r in results:
        wc = r["value"] if key == "water_cut" else r.get("water_cut", getattr(fluid, "water_cut", 0.0))
        if r["q"] is None:                    # the well does not flow
            r["q_oil"] = None
        else:
            r["q_oil"] = r["q"] * (1.0 - wc) if hasattr(fluid, "water_cut") else r["q"]
    return results


SENSITIVITY_GAUGE = ("p_wh", "p_res")        # these are pressures: typed in psig, used by the engine in psia


def run_sensitivity(case, key, values, with_curves=False):
    """Operating point for each value of one input (key from sensitivity_options).
    values are in the units of the page, so a pressure is in psig; each result keeps that same value in
    its "value", while the calculation itself uses psia.
    with_curves=True also keeps the IPR and VLP curves of every value ("curves" in each result)."""
    if key == "water_cut":
        if not all(0.0 <= v <= 1.0 for v in values):
            raise ValueError("Water cut must be between 0 and 1.")
    shown = list(values)                     # what the page asked for, kept for the tables and charts
    if key in SENSITIVITY_GAUGE:
        values = [to_psia(v) for v in values]
    base = case["solve"]
    if key == "tubing_id":
        wells = [well_with_tubing_id(base["well"], v) for v in values]
        results = sensitivity(base, "well", wells, with_curves)
        for r, v in zip(results, values):
            r["value"] = v                    # show the diameter, not the Well object
        return _add_oil_rate(results, base, key)
    multilayer = "layers" in base["ipr_inputs"]
    if multilayer and key in ("p_res", "ml_pi_mult"):
        # every layer moves together: layer pressures scale with the highest one, or all PIs are multiplied
        results = []
        for v in values:
            b = copy.deepcopy(base)
            if key == "p_res":
                factor = v / b["p_res"]
                for layer in b["ipr_inputs"]["layers"]:
                    layer["p_res"] *= factor
                b["p_res"] = v
            else:
                for layer in b["ipr_inputs"]["layers"]:
                    if "J" in layer:                                  # oil layer: PI
                        layer["J"] *= v
                    elif "C" in layer:                                # gas layer, back-pressure: q scales with C
                        layer["C"] *= v
                    else:                                             # gas layer, a and b: q scales with v when a/v, b/v^2
                        layer["a"] /= v
                        layer["b"] /= v * v
            row = sensitivity(b, "p_wh", [b["p_wh"]], with_curves)[0]
            row["value"] = v
            results.append(row)
        for r, v in zip(results, shown):
            r["value"] = v               # the table and the chart show what was typed (psig for a pressure)
        return _add_oil_rate(results, base, key)
    if key == "kh":
        # kh and kv move together: kv keeps the same share of kh as in the base case
        ratio = base["ipr_inputs"]["kv"] / base["ipr_inputs"]["kh"]
        results = []
        for v in values:
            b = copy.deepcopy(base)
            b["ipr_inputs"]["kh"], b["ipr_inputs"]["kv"] = v, ratio * v
            row = sensitivity(b, "p_wh", [b["p_wh"]], with_curves)[0]
            row["value"] = v
            results.append(row)
        return _add_oil_rate(results, base, key)
    if key not in _SENSITIVITY_PATHS:
        raise ValueError(f"Unknown sensitivity input: {key}")
    results = sensitivity(base, _SENSITIVITY_PATHS[key], values, with_curves)
    for r, v in zip(results, shown):
        r["value"] = v                       # the table and the chart show what was typed (psig for a pressure)
    return _add_oil_rate(results, base, key)


def gas_lift_performance(case, values):
    """Gas lift performance curve: the operating point for each gas injection rate in `values` (Mscf/d).
    Returns (results, best); best is the result with the highest oil rate, or None when no rate flows.
    Past the best point more gas only adds friction and the oil rate falls again."""
    if not case.get("gas_lift"):
        raise ValueError("Choose continuous gas lift under 'Artificial lift' first.")
    results = run_sensitivity(case, "gl_rate", values)
    flowing = [r for r in results if r["found"]]
    best = max(flowing, key=lambda r: r["q_oil"]) if flowing else None
    return results, best


def make_gl_performance_figure(results, best):
    """Oil rate against gas injection rate, with the highest point marked."""
    fig = make_sensitivity_figure(results, "Gas injection rate (Mscf/d)", "Oil rate (STB/d)", "q_oil")
    ax = fig.axes[0]
    if best is not None:
        ax.set_ylim(0, 1.15 * best["q_oil"])              # room for the star above the curve
        ax.plot([best["value"]], [best["q_oil"]], "*", color="#f2c200", mec="black", ms=17, mew=1.0, zorder=6)
        ax.annotate(f"highest: {best['q_oil']:,.0f} STB/d\nat {best['value']:,.0f} Mscf/d", (best["value"], best["q_oil"]),
                    textcoords="offset points", xytext=(0, -34), ha="center", va="top", fontsize=9,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
    return fig


def sensitivity_table(results, label, rate_label, oil_label=None):
    """Rows for a table: the input value, the operating rate and Pwf (or 'no flow').
    With oil_label (for example "Oil rate (STB/d)") the oil rate is added as a column."""
    rows = []
    for r in results:
        row = {label: round(r["value"], 4),
               rate_label: round(r["q"], 0) if r["found"] else "no flow"}
        if oil_label:
            row[oil_label] = round(r["q_oil"], 0) if r["found"] else "no flow"
        row["Pwf (psig)"] = round(to_psig(r["pwf"]), 0) if r["found"] else "-"
        rows.append(row)
    return rows
