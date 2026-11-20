"""
app.py - the Nodal Analysis web page (Streamlit).

Run it on your own computer with:
        streamlit run app.py
All the engineering is in the other files; this file only draws the page:
    left sidebar : inputs (fluid, reservoir/IPR, PVT, equipment, VLP correlation, VLP matching)
    main area    : results and the tabs (IPR/VLP chart and P-T profiles side by side, sensitivity, ...)

Streamlit re-runs this whole file from top to bottom every time you touch a widget.
That is why the results are kept in st.session_state: they stay on the screen until you
press "Calculate" again.
"""
import base64
import io
import os

import pandas as pd
import streamlit as st

from app_helpers import (to_psig, to_psia, ATM, CORRELATION_NAMES, correlation_caption, SURVEY_COLUMNS, SURVEY_MAX_POINTS, survey_points,
                         compare_to_survey, match_to_survey, make_survey_figure, AVAILABLE_CORRELATIONS, survey_rows, survey_text_from_table, perforation_md, gas_lift_performance, make_gl_performance_figure, DEFAULTS, MULTIPLIER_MIN, MULTIPLIER_MAX,
                         build_case, run_case, rate_unit, match_from_test, multiplier_note, transient_warning,
                         make_nodal_figure, make_profile_figure, make_sensitivity_figure,
                         sensitivity_options, evenly_spaced, parse_value_list, run_sensitivity, sensitivity_table, make_sensitivity_nodal_figure,
                         pvt_base, pvt_comparison_table, make_pvt_figure, with_pvt_match, pvt_match_stale_note,
                         PVT_NAMES, VISC_NAMES, multilayer_layers, multilayer_summary, make_multilayer_figure,
                         gas_multilayer_layers, gas_multilayer_summary, make_gas_multilayer_figure,
                         correlation_advice, recommend_correlation, check_correlations)
import ipr
import pvt_match
import gaslift_tab

st.set_page_config(page_title="Integrated Well Modelling Tool", layout="wide")
# Make better use of the space: less empty room at the top, smaller headers.
st.markdown("""
<style>
.block-container {padding-top: 2.8rem; padding-bottom: 1rem;}
[data-testid="stSidebarHeader"] {padding-bottom: 0; min-height: 0;}
[data-testid="stSidebarUserContent"] {padding-top: 0.5rem;}
h1 {font-size: 1.5rem !important; padding: 0 0 0.2rem 0 !important;}
h2, h3 {font-size: 1.05rem !important; padding: 0.3rem 0 0.2rem 0 !important;}
[data-testid="stSidebar"] h2 {font-size: 1.7rem !important; font-weight: 800 !important; padding: 0.2rem 0 0.1rem 0 !important;}
.byline {font-size: 0.85rem; margin: 0.6rem 0 0.6rem 0; color: #444;}

[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpander"] summary p {font-weight: 700 !important;}
.section-name {font-weight: 700; margin: 0.3rem 0 -0.4rem 0;}
</style>
""", unsafe_allow_html=True)
st.title("Integrated Well Modelling Tool")
# Byline: smaller type, bold name.  If the file assets/claude_logo.png exists, that picture is shown instead of the word "Claude".
_claude_png = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "claude_logo.png")
if os.path.exists(_claude_png):
    with open(_claude_png, "rb") as _f:
        _claude = ('<img src="data:image/png;base64,' + base64.b64encode(_f.read()).decode("ascii") +
                   '" alt="Claude" style="height:1.1em; vertical-align:text-bottom">')
else:
    _claude = "<b>Claude</b>"
st.markdown(f'<div class="byline">by <b>Vu Huu Huy</b> in collaboration with {_claude}</div>', unsafe_allow_html=True)

# Names shown on the page -> names used inside the code
SURVEY_COLUMNS = ["MD (ft)", "TVD (ft)"]
LIFT_CHOICES = {"None": "none", "Gas lift": "continuous", "ESP": "esp"}
OIL_IPR = {"PI entry (default)": "pi", "Vogel": "vogel", "Darcy": "darcy", "Fetkovich": "fetkovich",
           "Multilayer (commingled)": "multilayer",
           "Horizontal well (Joshi)": "horizontal",
           "Horizontal well (Kuchuk-Goode)": "horizontal_kg"}
OIL_REGIME = {"Pseudosteady state (closed area)": "pseudosteady", "Steady state (pressure held at re)": "steady",
              "Transient (after a given time)": "transient"}
GAS_IPR = {"Darcy": "darcy", "Jones": "jones", "Back pressure (C & n)": "backpressure",
           "Multilayer (commingled)": "multilayer",
           "Horizontal well (Joshi)": "horizontal", "Horizontal well (Kuchuk-Goode)": "horizontal_kg"}
PVT_METHODS = {"Glaso (default)": "glaso", "Standing": "standing", "Lasater": "lasater",
               "Petrosky et al": "petrosky"}
OIL_VISC = {"Beal et al (default)": "beal", "Beggs et al": "beggs", "Petrosky et al": "petrosky"}
GAS_VISC = {"Lee et al (default)": "lee", "Carr et al": "carr"}
OIL_CORRELATIONS = ["hagedorn_brown", "duns_ros", "beggs_brill", "mukherjee_brill", "orkiszewski", "ansari", "fancher_brown"]
GAS_CORRELATIONS = ["gray", "hagedorn_brown", "duns_ros", "beggs_brill", "mukherjee_brill", "orkiszewski", "ansari", "fancher_brown"]

D = DEFAULTS   # shorthand: the starting value of every input


def show_figure(fig):
    """Draw a matplotlib figure on the page at exactly the size it was built.
    st.pyplot trims the white margins of every picture, so two charts side by side end up with different
    top and bottom edges.  Here the figure is saved to a PNG as it is (no trimming) and shown as an image."""
    picture = io.BytesIO()
    fig.savefig(picture, format="png", dpi=170)
    try:
        st.image(picture, width="stretch")                  # newer Streamlit versions
    except Exception:
        st.image(picture, use_container_width=True)         # older Streamlit versions


def number(label, low, high, value, step, fmt=None, key=None, disabled=False):
    """A number box.  All numbers are floats because Streamlit does not allow int/float mixes.
    With a key, the box keeps what the user typed from one run to the next (and the program can
    change it); the starting value is then stored once in st.session_state."""
    if key is None:
        return st.number_input(label, min_value=float(low), max_value=float(high),
                               value=float(value), step=float(step), format=fmt, disabled=disabled)
    st.session_state.setdefault(key, float(value))
    return st.number_input(label, min_value=float(low), max_value=float(high),
                           step=float(step), format=fmt, key=key, disabled=disabled)


def mark_manual_pick():
    """The user chose a VLP correlation by hand: stop following the app's suggestion."""
    st.session_state["vlp_pick_manual"] = True


def follow_suggestion():
    """Button action: go back to the correlation the app suggests for the well."""
    st.session_state["vlp_pick_manual"] = False


def clear_survey_table():
    """Button action: empty the measured-points table of the VLP comparison tab (a new key gives a new, blank table)."""
    st.session_state["vc_table_ver"] = st.session_state.get("vc_table_ver", 0) + 1


def apply_pvt_match():
    """Button action: use the matched PVT (found on the PVT matching tab) in the well model."""
    fit = st.session_state.get("pvt_fit")
    if fit:
        st.session_state["pvt_applied"] = fit
        st.session_state["recalc"] = True


def remove_pvt_match():
    """Button action: go back to the correlations as published."""
    st.session_state.pop("pvt_applied", None)
    st.session_state["recalc"] = True


LAB_COLUMNS = ["Pressure (psig)", "Rs (scf/STB)", "Bo (rb/STB)", "Oil viscosity (cP)"]


def pvt_matching_window(base, start_table, start_pb):
    """The PVT matching screen (opened from 'Fluid (PVT)' in the sidebar as a pop-up window).
    base        : oil gravity, gas gravity, solution GOR and temperature taken from the sidebar
    start_table : the laboratory table to start with (what the user typed last time)
    start_pb    : the measured bubble point to start with
    Left: the lab data and the comparison of the correlations.  Right: the chart and the matched result."""
    left, right = st.columns([1.05, 1])
    lab, fit, shown = None, None, None
    with left:
        st.caption("Enter the laboratory PVT data (all at reservoir temperature). Any column may be left empty, and "
                   "you can paste a block straight from Excel. The app compares the lab points with every "
                   "correlation, and can then match the chosen correlation to the lab data.")
        st.caption(f"Used for the comparison, from the sidebar: oil gravity {base['api']:g} API, gas gravity "
                   f"{base['gas_sg']:g}, solution GOR {base['rsb']:g} scf/STB, temperature {base['temp_f']:g} degF.")
        pb_lab = number("Measured bubble point from the lab report (psig); 0 = not given", 0, 10000, start_pb, 50)
        pb_lab_abs = to_psia(pb_lab) if pb_lab else None       # psia for pvt_match; pb_lab stays psig for the page
        typed = st.data_editor(start_table, num_rows="dynamic", hide_index=True, key="lab_table_window",
                               use_container_width=True)
        # Remember what was typed: the widget forgets it when the window is closed
        st.session_state["lab_saved"] = typed
        st.session_state["lab_pb_saved"] = pb_lab
        # The lab table is typed in psig, like every pressure on the page; pvt_match works in psia.
        rows = [dict(p=None if r[LAB_COLUMNS[0]] is None or r[LAB_COLUMNS[0]] != r[LAB_COLUMNS[0]] else to_psia(r[LAB_COLUMNS[0]]),
                     rs=r[LAB_COLUMNS[1]], bo=r[LAB_COLUMNS[2]], mu=r[LAB_COLUMNS[3]])
                for r in typed.to_dict("records")]
        try:
            lab = pvt_match.clean_lab_table(rows)
        except ValueError as error:
            lab = None
            st.info(str(error))
        if lab:
            try:
                ranking = pvt_match.compare_methods(lab, base["api"], base["gas_sg"], base["rsb"],
                                                    base["temp_f"], pb_lab_abs)
                st.markdown("**How close is each correlation to the lab data?** (average absolute error, best first)")
                st.dataframe(pd.DataFrame(pvt_comparison_table(ranking)), hide_index=True)
                best = ranking[0]
                c1, c2 = st.columns(2)
                pvt_names = list(PVT_NAMES)
                visc_names = list(VISC_NAMES)
                with c1:
                    chosen_pvt = st.selectbox("Correlation for Pb, Rs, Bo", pvt_names,
                                              index=pvt_names.index(best["pvt_method"]), format_func=PVT_NAMES.get)
                with c2:
                    chosen_visc = st.selectbox("Viscosity correlation", visc_names,
                                               index=visc_names.index(best["visc_method"]), format_func=VISC_NAMES.get)
                if st.button("Match to lab data"):
                    fit = pvt_match.fit_match(lab, base["api"], base["gas_sg"], base["rsb"], base["temp_f"],
                                              pb_lab_abs, chosen_pvt, chosen_visc)
                    fit.update(pvt_method=chosen_pvt, visc_method=chosen_visc, pb_meas=pb_lab, base=base)
                    st.session_state["pvt_fit"] = fit
                saved = st.session_state.get("pvt_fit")
                if saved and (saved["pvt_method"], saved["visc_method"]) == (chosen_pvt, chosen_visc):
                    fit = saved
                shown = (chosen_pvt, chosen_visc)
            except (ValueError, RuntimeError) as error:
                st.error(f"Cannot compare: {error}")
    with right:
        if shown:
            show_figure(make_pvt_figure(lab, base, pb_lab_abs, shown[0], shown[1], fit))
            if fit:
                m = fit["match"]

                def pct(x):
                    return "no lab data" if x is None else f"{x:.1f} %"
                st.markdown(
                    f"**Matched {PVT_NAMES[shown[0]]} + {VISC_NAMES[shown[1]]}**  \n"
                    f"Rs: shape exponent {m['rs_exp']:.2f} (1 = unchanged), error {pct(fit['before']['rs'])} -> {pct(fit['after']['rs'])}  \n"
                    f"Bo: {m['bo_a']:.3f} x Bo + {m['bo_b']:.4f}, error {pct(fit['before']['bo'])} -> {pct(fit['after']['bo'])}  \n"
                    f"Viscosity: x {m['mu_mult']:.3f}, error {pct(fit['before']['mu'])} -> {pct(fit['after']['mu'])}")
                for note in fit["notes"]:
                    st.caption(note)
                if st.button("Use this match in the well model", type="primary",
                             help="Replaces the PVT correlations and the bubble point in the sidebar, then "
                                  "recalculates everything."):
                    apply_pvt_match()
                    st.rerun()                      # closes the window and redraws the page with the match on


# A pop-up window needs a recent Streamlit (st.dialog); older versions show the same screen in the main area instead
if hasattr(st, "dialog"):
    open_pvt_window = st.dialog("PVT matching with laboratory data", width="large")(pvt_matching_window)
else:
    open_pvt_window = None


# ---------------------------------------------------------------------
# Multilayer layer table (pop-up window)
# ---------------------------------------------------------------------
ML_NUMBERS = ("p_psig", "pi", "k", "h", "skin", "gor", "wc")       # the number cells of one layer row
ML_COLUMNS = [("Layer", 0.45), ("Layer model", 1.1), ("Layer pressure (psig)", 1.15), ("PI (STB/d/psi)", 1.0),
              ("Layer perm (mD)", 1.0), ("Layer height (ft)", 0.95), ("Layer skin", 0.8),
              ("Formation GOR (scf/STB)", 1.15), ("Water cut (%)", 0.95), ("", 0.4)]
ML_MODELS = ["PI", "Darcy"]


def ml_layers_state():
    """The layer table kept between runs: a list of dictionaries (one per layer) with a row number "id".
    The widgets in the pop-up window forget their values when the window closes, so the values are also kept here."""
    if "ml_layers" not in st.session_state:
        st.session_state["ml_layers"] = [dict(row, id=n) for n, row in enumerate(DEFAULTS["ml_layers"])]
        st.session_state["ml_next_id"] = len(DEFAULTS["ml_layers"])
    if "ml_darcy" not in st.session_state:
        st.session_state["ml_darcy"] = {k: DEFAULTS[k] for k in ("ml_bo", "ml_mu", "ml_re", "ml_rw")}
    return st.session_state["ml_layers"]


def ml_read_widgets():
    """Copy what is typed in the window's cells into the layer table kept in session_state."""
    for row in ml_layers_state():
        for field in ML_NUMBERS:
            key = f"mlw_{row['id']}_{field}"
            if key in st.session_state:
                row[field] = float(st.session_state[key])
        key = f"mlw_{row['id']}_model"
        if key in st.session_state:
            row["model"] = "darcy" if st.session_state[key] == "Darcy" else "pi"
    for name in ("ml_bo", "ml_mu", "ml_re", "ml_rw"):
        if "mlw_" + name in st.session_state:
            st.session_state["ml_darcy"][name] = float(st.session_state["mlw_" + name])


def ml_add_layer():
    """Button action: add a layer (a copy of the last one)."""
    ml_read_widgets()
    layers = ml_layers_state()
    layers.append(dict(layers[-1], id=st.session_state["ml_next_id"]))
    st.session_state["ml_next_id"] += 1


def ml_delete_layer(row_id):
    """Button action: remove one layer (the last one cannot be removed)."""
    ml_read_widgets()
    layers = ml_layers_state()
    if len(layers) > 1:
        st.session_state["ml_layers"] = [r for r in layers if r["id"] != row_id]


def ml_apply():
    """Button action: keep the table and recalculate."""
    ml_read_widgets()
    st.session_state["recalc"] = True


def multilayer_window():
    """The layer table, in a pop-up window.  One row per layer.  The cells that do not apply to the layer's model
    are greyed out: a PI layer needs only the PI; a Darcy layer needs permeability, height and skin (its PI is then
    calculated and shown greyed).  Every layer also has its own formation GOR and water cut: the well stream is the
    sum of the layers, so the water cut and GOR that the tubing sees depend on how much each layer produces."""
    layers = ml_layers_state()
    st.caption("One row per layer. Layer pressures are in psig (the program adds 14.7 psi). Choose how each layer is "
               "described: by its productivity index (PI), or by Darcy's equation from permeability, height and "
               "skin; the cells that do not apply are greyed out. The formation GOR and water cut of each layer "
               "decide what the well produces: at each flowing pressure the layers' oil, water and gas are added "
               "and the tubing is calculated for that mixture.")
    saved = st.session_state["ml_darcy"]
    c1, c2, c3, c4 = st.columns(4)
    for col, name, label, low, high, value, step, fmt in (
            (c1, "ml_bo", "Bo, Darcy layers (rb/STB)", 1.0, 3.0, saved["ml_bo"], 0.05, "%.3f"),
            (c2, "ml_mu", "Oil viscosity (cP)", 0.05, 1000.0, saved["ml_mu"], 0.1, "%.2f"),
            (c3, "ml_re", "Drainage radius re (ft)", 10.0, 20000.0, saved["ml_re"], 50.0, "%.0f"),
            (c4, "ml_rw", "Wellbore radius rw (ft)", 0.1, 5.0, saved["ml_rw"], 0.05, "%.3f")):
        with col:
            st.session_state.setdefault("mlw_" + name, float(value))
            st.number_input(label, min_value=low, max_value=high, step=step, format=fmt, key="mlw_" + name,
                            disabled=not any(r["model"] == "darcy" for r in layers))
    ml_read_widgets()
    saved = st.session_state["ml_darcy"]

    sizes = [w for _, w in ML_COLUMNS]
    header = st.columns(sizes)
    for col, (name, _) in zip(header, ML_COLUMNS):
        col.markdown(f"**{name}**" if name else "")
    ranges = {"p_psig": (-14.0, 20000.0, 50.0, "%.0f"), "pi": (0.0, 1000.0, 0.1, "%.3f"),
              "k": (0.0, 100000.0, 10.0, "%.1f"), "h": (0.0, 2000.0, 5.0, "%.1f"),
              "skin": (-7.0, 100.0, 0.5, "%.1f"), "gor": (0.0, 50000.0, 50.0, "%.0f"),
              "wc": (0.0, 100.0, 5.0, "%.1f")}
    for n, row in enumerate(layers, start=1):
        rid = row["id"]
        cols = st.columns(sizes)
        cols[0].markdown(f"{n}")
        model_key = f"mlw_{rid}_model"
        st.session_state.setdefault(model_key, "Darcy" if row["model"] == "darcy" else "PI")
        with cols[1]:
            model = st.selectbox(f"Layer {n} model", ML_MODELS, key=model_key, label_visibility="collapsed")
        darcy = model == "Darcy"
        for col, field in zip(cols[2:9], ML_NUMBERS):
            na = (field == "pi" and darcy) or (field in ("k", "h", "skin") and not darcy)
            low, high, step, fmt = ranges[field]
            with col:
                if field == "pi" and darcy:
                    # the PI of a Darcy layer is calculated: shown greyed
                    try:
                        j = ipr.darcy_productivity_index_oil(row["k"], row["h"], saved["ml_bo"], saved["ml_mu"],
                                                             saved["ml_re"], saved["ml_rw"], row["skin"])
                        text = f"{j:.3f}"
                    except ValueError:
                        text = "-"
                    st.session_state[f"mlcalc_{rid}"] = text
                    st.text_input(f"Layer {n} calculated PI", key=f"mlcalc_{rid}", disabled=True,
                                  label_visibility="collapsed")
                elif na:
                    st.session_state[f"mlna_{rid}_{field}"] = "-"
                    st.text_input(f"Layer {n} {field} not used", key=f"mlna_{rid}_{field}", disabled=True,
                                  label_visibility="collapsed")
                else:
                    key = f"mlw_{rid}_{field}"
                    st.session_state.setdefault(key, float(min(max(row[field], low), high)))
                    st.number_input(f"Layer {n} {field}", min_value=low, max_value=high, step=step, format=fmt,
                                    key=key, label_visibility="collapsed")
        with cols[9]:
            st.button("X", key=f"mldel_{rid}", on_click=ml_delete_layer, args=(rid,), disabled=len(layers) == 1,
                      help="Remove this layer")
    ml_read_widgets()

    b1, b2 = st.columns([1, 3])
    with b1:
        st.button("Add layer", on_click=ml_add_layer)
    try:
        rows = multilayer_summary({"ml_layers": layers, **saved})
        st.caption(f"{len(rows)} layer(s), highest pressure {max(r['Pressure (psig)'] for r in rows):,.0f} psig.")
    except ValueError as error:
        st.warning(str(error))
    # The chart: every layer's IPR and the composite IPR (the bubble point is the one of the last calculation)
    try:
        pb_now = st.session_state.get("case", {}).get("pb")
        if pb_now is None:
            pb_now = DEFAULTS["rsb"] * 4.0                     # no calculation yet: only a rough kink position
        show_figure(make_multilayer_figure(multilayer_layers({"ml_layers": layers, **saved}), pb_now,
                                           bool(st.session_state.get("ml_crossflow", False))))
        st.caption(f"Bubble point used for the curves: {to_psig(pb_now):,.0f} psig (from the last calculation). Dashed: each layer "
                   "alone. Solid: all layers together.")
    except ValueError:
        pass                                                    # the warning above already says what is wrong
    if st.button("Apply and recalculate", type="primary"):
        ml_apply()
        st.rerun()                                  # closes the window and redraws the page


if hasattr(st, "dialog"):
    open_multilayer_window = st.dialog("Multilayer IPR: layer table", width="large")(multilayer_window)
else:
    open_multilayer_window = None


# ---------------------------------------------------------------------
# Multilayer GAS layer table (pop-up window)
# ---------------------------------------------------------------------
GM_NUMBERS = ("p_psig", "k", "h", "skin", "C", "n", "cgr", "wgr")       # the number cells of one gas layer row
GM_COLUMNS = [("Layer", 0.4), ("Layer model", 1.15), ("Layer pressure (psig)", 1.1), ("Layer perm (mD)", 0.95),
              ("Layer height (ft)", 0.9), ("Layer skin", 0.75), ("C (Mscf/d per psi^2n)", 1.05), ("n", 0.7),
              ("CGR (STB/MMscf)", 0.95), ("WGR (STB/MMscf)", 0.95), ("", 0.4)]
GM_MODELS = ["Jones", "Darcy", "Back-pressure"]
GM_MODEL_KEYS = {"Jones": "jones", "Darcy": "darcy", "Back-pressure": "backpressure"}
GM_MODEL_NAMES = {v: k for k, v in GM_MODEL_KEYS.items()}


def gm_layers_state():
    """The gas layer table kept between runs (a list of dictionaries with a row number "id"), like ml_layers_state()."""
    if "gm_layers" not in st.session_state:
        st.session_state["gm_layers"] = [dict(row, id=n) for n, row in enumerate(DEFAULTS["gm_layers"])]
        st.session_state["gm_next_id"] = len(DEFAULTS["gm_layers"])
    if "gm_common" not in st.session_state:
        st.session_state["gm_common"] = {k: DEFAULTS[k] for k in ("gm_re", "gm_rw", "gm_beta")}
    return st.session_state["gm_layers"]


def gm_read_widgets():
    """Copy what is typed in the window's cells into the layer table kept in session_state."""
    for row in gm_layers_state():
        for field in GM_NUMBERS:
            key = f"gmw_{row['id']}_{field}"
            if key in st.session_state:
                row[field] = float(st.session_state[key])
        key = f"gmw_{row['id']}_model"
        if key in st.session_state:
            row["model"] = GM_MODEL_KEYS[st.session_state[key]]
    for name in ("gm_re", "gm_rw", "gm_beta"):
        if "gmw_" + name in st.session_state:
            st.session_state["gm_common"][name] = float(st.session_state["gmw_" + name])


def gm_add_layer():
    """Button action: add a layer (a copy of the last one)."""
    gm_read_widgets()
    layers = gm_layers_state()
    layers.append(dict(layers[-1], id=st.session_state["gm_next_id"]))
    st.session_state["gm_next_id"] += 1


def gm_delete_layer(row_id):
    """Button action: remove one layer (the last one cannot be removed)."""
    gm_read_widgets()
    layers = gm_layers_state()
    if len(layers) > 1:
        st.session_state["gm_layers"] = [r for r in layers if r["id"] != row_id]


def gm_apply():
    """Button action: keep the table and recalculate."""
    gm_read_widgets()
    st.session_state["recalc"] = True


def gas_multilayer_window():
    """The gas layer table, in a pop-up window.  One row per layer.  A Jones or Darcy layer is described by permeability,
    height and skin; a back-pressure layer by C and n (the cells that do not apply are greyed out).  Every layer has its own
    condensate-gas and water-gas ratio: the well stream is the sum of the layers, so the CGR and WGR that the tubing sees
    depend on how much each layer produces."""
    layers = gm_layers_state()
    st.caption("One row per layer. Layer pressures are in psig (the program adds 14.7 psi). A Jones layer includes the "
               "non-Darcy (turbulence) loss, a Darcy layer does not; a back-pressure layer is given by C and n. The cells "
               "that do not apply are greyed out. The CGR and WGR of each layer decide what the well produces: at each "
               "flowing pressure the layers' gas, condensate and water are added and the tubing is calculated for that "
               "mixture. Z and viscosity are taken at 75 % of each layer's pressure.")
    saved = st.session_state["gm_common"]
    c1, c2, c3 = st.columns(3)
    for col, name, label, low, high, value, step, fmt in (
            (c1, "gm_re", "Drainage radius re (ft)", 10.0, 20000.0, saved["gm_re"], 50.0, "%.0f"),
            (c2, "gm_rw", "Wellbore radius rw (ft)", 0.1, 5.0, saved["gm_rw"], 0.05, "%.3f"),
            (c3, "gm_beta", "Non-Darcy factor beta (1/ft); 0 = estimate from each layer's k", 0.0, 1e12,
             saved["gm_beta"], 1e8, "%.3e")):
        with col:
            st.session_state.setdefault("gmw_" + name, float(value))
            st.number_input(label, min_value=low, max_value=high, step=step, format=fmt, key="gmw_" + name,
                            disabled=(name == "gm_beta" and not any(r["model"] == "jones" for r in layers)) or
                                     (name != "gm_beta" and all(r["model"] == "backpressure" for r in layers)))
    gm_read_widgets()

    sizes = [w for _, w in GM_COLUMNS]
    header = st.columns(sizes)
    for col, (name, _) in zip(header, GM_COLUMNS):
        col.markdown(f"**{name}**" if name else "")
    ranges = {"p_psig": (-14.0, 20000.0, 50.0, "%.0f"), "k": (0.0, 100000.0, 1.0, "%.2f"),
              "h": (0.0, 2000.0, 5.0, "%.1f"), "skin": (-7.0, 100.0, 0.5, "%.1f"),
              "C": (0.0, 1e6, 0.001, "%.5f"), "n": (0.0, 1.0, 0.05, "%.3f"),
              "cgr": (0.0, 1000.0, 5.0, "%.1f"), "wgr": (0.0, 1000.0, 1.0, "%.1f")}
    for n, row in enumerate(layers, start=1):
        rid = row["id"]
        cols = st.columns(sizes)
        cols[0].markdown(f"{n}")
        model_key = f"gmw_{rid}_model"
        st.session_state.setdefault(model_key, GM_MODEL_NAMES.get(row["model"], "Jones"))
        with cols[1]:
            model = st.selectbox(f"Layer {n} model", GM_MODELS, key=model_key, label_visibility="collapsed")
        back = model == "Back-pressure"
        for col, field in zip(cols[2:10], GM_NUMBERS):
            na = (field in ("k", "h", "skin") and back) or (field in ("C", "n") and not back)
            low, high, step, fmt = ranges[field]
            with col:
                if na:
                    st.session_state[f"gmna_{rid}_{field}"] = "-"
                    st.text_input(f"Layer {n} {field} not used", key=f"gmna_{rid}_{field}", disabled=True,
                                  label_visibility="collapsed")
                else:
                    key = f"gmw_{rid}_{field}"
                    st.session_state.setdefault(key, float(min(max(row[field], low), high)))
                    st.number_input(f"Layer {n} {field}", min_value=low, max_value=high, step=step, format=fmt,
                                    key=key, label_visibility="collapsed")
        with cols[10]:
            st.button("X", key=f"gmdel_{rid}", on_click=gm_delete_layer, args=(rid,), disabled=len(layers) == 1,
                      help="Remove this layer")
    gm_read_widgets()

    b1, b2 = st.columns([1, 3])
    with b1:
        st.button("Add layer", on_click=gm_add_layer)
    probe = {"gm_layers": layers, **saved}
    try:
        rows = gas_multilayer_summary(probe)
        st.caption(f"{len(rows)} layer(s), highest pressure {max(r['Pressure (psig)'] for r in rows):,.0f} psig.")
    except ValueError as error:
        st.warning(str(error))
    try:
        show_figure(make_gas_multilayer_figure(gas_multilayer_layers({**st.session_state.get("inputs", {}), **probe}),
                                               bool(st.session_state.get("gm_crossflow", False))))
        st.caption("Dashed: each layer alone. Solid: all layers together. The gas gravity, condensate gravity, temperature "
                   "and contaminants are those of the Fluid (PVT) and Inflow performance sections.")
    except ValueError:
        pass                                                    # the warning above already says what is wrong
    if st.button("Apply and recalculate", type="primary"):
        gm_apply()
        st.rerun()                                  # closes the window and redraws the page


if hasattr(st, "dialog"):
    open_gas_multilayer_window = st.dialog("Gas multilayer IPR: layer table", width="large")(gas_multilayer_window)
else:
    open_gas_multilayer_window = None


# =====================================================================
# Sidebar: all the inputs
# =====================================================================
inp = {}                                              # filled in below, then given to build_case()
with st.sidebar:
    st.header("Inputs")
    st.markdown('<div class="section-name">Fluid</div>', unsafe_allow_html=True)
    fluid_choice = st.radio("Fluid", ["Oil & Water", "Dry & Wet gas"], horizontal=True, label_visibility="collapsed")
    is_oil = fluid_choice == "Oil & Water"
    inp["fluid_type"] = "oil" if is_oil else "gas"

    if is_oil:
        st.markdown('<div class="section-name">Artificial lift</div>', unsafe_allow_html=True)
        lift_label = st.selectbox("Artificial lift", list(LIFT_CHOICES), label_visibility="collapsed")
        inp["lift"] = LIFT_CHOICES[lift_label]
        if inp["lift"] == "esp":
            st.caption("ESP design is coming soon (see the ESP Design tab). It is not used in the calculation yet.")
    else:
        inp["lift"] = "none"

    # ---------------- reservoir and IPR ----------------
    gm_table_slot = None                    # the gas layer table is drawn here for a multilayer gas well (filled later)
    with st.expander("Reservoir and IPR", expanded=True):
        inp["p_res"] = number("Static reservoir pressure (psig)", 300, 10000, D["p_res"], 50)
        inp["t_res"] = number("Reservoir temperature (degF)", 100, 300, D["t_res"], 5)
        if is_oil:
            ipr_label = st.selectbox("IPR model", list(OIL_IPR))
            inp["oil_ipr"] = OIL_IPR[ipr_label]
            if inp["oil_ipr"] == "pi":
                inp["pi"] = number("Productivity index (STB/d/psi)", 0.01, 500, D["pi"], 0.1, "%.2f")
            elif inp["oil_ipr"] == "vogel":
                st.caption("One well test: rate and flowing pressure. Works for Pr above or below the "
                           "bubble point, and for a test Pwf above or below it.")
                inp["vogel_q"] = number("Test liquid rate (STB/d)", 1, 1e6, D["vogel_q"], 100)
                inp["vogel_pwf"] = number("Test flowing bottom-hole pressure (psig)", 0, 10000, D["vogel_pwf"], 50)
            elif inp["oil_ipr"] == "darcy":
                regime_label = st.selectbox("Flow regime", list(OIL_REGIME))
                inp["oil_regime"] = OIL_REGIME[regime_label]
                if inp["oil_regime"] == "transient":
                    st.caption("Transient: the well has produced for the time below and the pressure "
                               "disturbance has not reached the boundary yet. Productivity falls as time goes on.")
                    inp["oil_phi"] = number("Porosity (fraction)", 0.01, 0.6, D["oil_phi"], 0.01, "%.2f")
                    inp["oil_ct"] = number("Total compressibility ct (1/psi)", 1e-7, 1e-3, D["oil_ct"], 1e-6, "%.2e")
                    inp["oil_time"] = number("Time since the well opened (hours)", 1, 1e5, D["oil_time"], 12)
                inp["oil_k"] = number("Permeability k (md)", 0.01, 1e5, D["oil_k"], 5)
                inp["oil_h"] = number("Net thickness h (ft)", 1, 5000, D["oil_h"], 5)
                inp["oil_bo"] = number("Formation volume factor Bo (rb/STB)", 1.0, 3.0, D["oil_bo"], 0.05, "%.3f")
                inp["oil_mu"] = number("Oil viscosity (cP)", 0.05, 1000, D["oil_mu"], 0.1, "%.2f")
                inp["oil_re"] = number("Drainage radius re (ft)", 10, 20000, D["oil_re"], 50)
                inp["oil_rw"] = number("Wellbore radius rw (ft)", 0.1, 5, D["oil_rw"], 0.05, "%.3f")
                inp["oil_skin"] = number("Total skin factor", -5, 100, D["oil_skin"], 0.5)
                if transient_warning(inp):
                    st.warning(transient_warning(inp))
            elif inp["oil_ipr"] == "horizontal":
                st.caption("Joshi (1988): steady flow in the horizontal plane, pseudosteady in the vertical "
                           "plane. The well is assumed to sit in the middle of the thickness.")
                inp["hz_kh"] = number("Horizontal permeability kh (md)", 0.01, 1e5, D["hz_kh"], 10)
                inp["hz_kv_ratio"] = number("Vertical / horizontal permeability ratio kv/kh", 0.001, 1.0,
                                            D["hz_kv_ratio"], 0.05, "%.3f")
                st.caption(f"Vertical permeability kv = {inp['hz_kv_ratio'] * inp['hz_kh']:,.2f} md")
                inp["hz_h"] = number("Net thickness h (ft)", 1, 5000, D["hz_h"], 5)
                inp["hz_length"] = number("Horizontal well length L (ft)", 50, 20000, D["hz_length"], 100)
                inp["hz_re"] = number("Drainage radius in the horizontal plane (ft)", 100, 50000, D["hz_re"], 100)
                inp["hz_rw"] = number("Wellbore radius rw (ft)", 0.1, 5, D["hz_rw"], 0.05, "%.3f")
                inp["hz_bo"] = number("Formation volume factor Bo (rb/STB)", 1.0, 3.0, D["hz_bo"], 0.05, "%.3f")
                inp["hz_mu"] = number("Oil viscosity (cP)", 0.05, 1000, D["hz_mu"], 0.1, "%.2f")
                inp["hz_skin"] = number("Total skin factor", -5, 100, D["hz_skin"], 0.5)
            elif inp["oil_ipr"] == "horizontal_kg":
                st.caption("Kuchuk and Goode (SPE 21460, 1991): a well of any length at any place in a closed rectangular "
                           "box (all sides sealed). The top can instead be a constant-pressure boundary (gas cap or aquifer).")
                inp["hz_kh"] = number("Permeability along the well kx (md)", 0.01, 1e5, D["hz_kh"], 10)
                inp["kg_ky_ratio"] = number("Permeability across the well: ky / kx", 0.01, 10.0, D["kg_ky_ratio"], 0.1, "%.2f")
                inp["hz_kv_ratio"] = number("Vertical / horizontal permeability ratio kv/kx", 0.001, 1.0,
                                            D["hz_kv_ratio"], 0.05, "%.3f")
                st.caption(f"ky = {inp['kg_ky_ratio'] * inp['hz_kh']:,.2f} md,  kv = {inp['hz_kv_ratio'] * inp['hz_kh']:,.2f} md")
                inp["hz_h"] = number("Net thickness h (ft)", 1, 5000, D["hz_h"], 5)
                inp["hz_length"] = number("Horizontal well length L (ft)", 50, 20000, D["hz_length"], 100)
                inp["kg_top"] = "constant_pressure" if st.radio(
                    "Top boundary", ["Sealed (no flow)", "Constant pressure (gas cap / aquifer)"]).startswith("Constant") else "sealed"
                if inp["kg_top"] == "sealed":
                    inp["kg_lx"] = number("Drainage box length along the well Lx (ft)", 100, 50000, D["kg_lx"], 100)
                    inp["kg_ly"] = number("Drainage box width across the well Ly (ft)", 100, 50000, D["kg_ly"], 100)
                    inp["kg_xw"] = number("Well centre along the box (fraction of Lx, 0.5 = middle)", 0.0, 1.0, D["kg_xw"], 0.05, "%.2f")
                    inp["kg_yw"] = number("Well position across the box (fraction of Ly, 0.5 = middle)", 0.0, 1.0, D["kg_yw"], 0.05, "%.2f")
                else:
                    st.caption("With a constant-pressure top the box size and the position along and across it are not used.")
                inp["kg_zw"] = number("Well height above the bottom (fraction of h, 0.5 = middle)", 0.0, 1.0, D["kg_zw"], 0.05, "%.2f")
                inp["hz_rw"] = number("Wellbore radius rw (ft)", 0.1, 5, D["hz_rw"], 0.05, "%.3f")
                inp["hz_bo"] = number("Formation volume factor Bo (rb/STB)", 1.0, 3.0, D["hz_bo"], 0.05, "%.3f")
                inp["hz_mu"] = number("Oil viscosity (cP)", 0.05, 1000, D["hz_mu"], 0.1, "%.2f")
                inp["hz_skin"] = number("Mechanical skin Sm", -5, 100, D["hz_skin"], 0.5)
            elif inp["oil_ipr"] == "multilayer":
                st.caption("Several layers produce into the same well at the same flowing pressure; the layer rates are "
                           "added. Each layer has its own pressure, PI (or permeability, height and skin), formation GOR "
                           "and water cut, entered in the layer table. The static pressure above is not used here: the "
                           "curve starts at the highest layer pressure.")
                ml_layers_state()
                inp["ml_layers"] = [dict(r) for r in st.session_state["ml_layers"]]
                inp.update(st.session_state["ml_darcy"])
                try:
                    st.dataframe(pd.DataFrame(multilayer_summary(inp)), hide_index=True)
                except ValueError as error:
                    st.warning(str(error))
                if st.button("Edit layer table...", help="Opens the layer table: model, pressure, PI or "
                                                         "permeability/height/skin, GOR and water cut of each layer."):
                    if open_multilayer_window:
                        open_multilayer_window()
                    else:
                        st.session_state["ml_inline"] = True
                inp["ml_crossflow"] = st.checkbox("Allow crossflow (a layer below the flowing pressure takes fluid)",
                                                  value=False, key="ml_crossflow")
                st.caption("All layers are taken at the perforation reference depth and share one bubble point. "
                           "The water cut and GOR of the well stream are worked out from the layers at every rate.")
            else:
                st.caption("Two well tests (rate and flowing pressure).")
                inp["fet_q1"] = number("Test 1 rate (STB/d)", 1, 1e6, D["fet_q1"], 100)
                inp["fet_pwf1"] = number("Test 1 Pwf (psig)", 0, 10000, D["fet_pwf1"], 50)
                inp["fet_q2"] = number("Test 2 rate (STB/d)", 1, 1e6, D["fet_q2"], 100)
                inp["fet_pwf2"] = number("Test 2 Pwf (psig)", 0, 10000, D["fet_pwf2"], 50)
        else:
            ipr_label = st.selectbox("IPR model", list(GAS_IPR), index=1)
            inp["gas_ipr"] = GAS_IPR[ipr_label]
            if inp["gas_ipr"] == "backpressure":
                inp["bp_c"] = number("C (Mscf/d per psi^2n)", 1e-9, 1e6, D["bp_c"], 0.001, "%.5f")
                inp["bp_n"] = number("n (0.5 to 1.0)", 0.05, 1.0, D["bp_n"], 0.05, "%.3f")
            elif inp["gas_ipr"] in ("horizontal", "horizontal_kg"):
                if inp["gas_ipr"] == "horizontal":
                    st.caption("Joshi geometry (steady flow in the horizontal plane, pseudosteady in the vertical plane) "
                               "for gas, in pressure-squared form with a non-Darcy term. The well is assumed to sit in the "
                               "middle of the thickness.")
                    inp["gh_kh"] = number("Horizontal permeability kh (md)", 0.001, 1e5, D["gh_kh"], 1)
                else:
                    st.caption("Kuchuk and Goode geometry for gas: a well of any length at any place in a closed rectangular "
                               "box (all sides sealed), or with a constant-pressure top (gas cap or aquifer).")
                    inp["gh_kh"] = number("Permeability along the well kx (md)", 0.001, 1e5, D["gh_kh"], 1)
                    inp["gk_ky_ratio"] = number("Permeability across the well: ky / kx", 0.01, 10.0, D["gk_ky_ratio"], 0.1, "%.2f")
                inp["gh_kv_ratio"] = number("Vertical / horizontal permeability ratio kv/kh", 0.001, 1.0, D["gh_kv_ratio"], 0.05, "%.3f")
                st.caption(f"Vertical permeability kv = {inp['gh_kv_ratio'] * inp['gh_kh']:,.3f} md")
                inp["gh_h"] = number("Net thickness h (ft)", 1, 5000, D["gh_h"], 5)
                inp["gh_length"] = number("Horizontal well length L (ft)", 50, 20000, D["gh_length"], 100)
                if inp["gas_ipr"] == "horizontal":
                    inp["gh_re"] = number("Drainage radius in the horizontal plane (ft)", 100, 50000, D["gh_re"], 100)
                else:
                    inp["gk_top"] = "constant_pressure" if st.radio(
                        "Top boundary", ["Sealed (no flow)", "Constant pressure (gas cap / aquifer)"],
                        key="gk_top_radio").startswith("Constant") else "sealed"
                    if inp["gk_top"] == "sealed":
                        inp["gk_lx"] = number("Drainage box length along the well Lx (ft)", 100, 50000, D["gk_lx"], 100)
                        inp["gk_ly"] = number("Drainage box width across the well Ly (ft)", 100, 50000, D["gk_ly"], 100)
                        inp["gk_xw"] = number("Well centre along the box (fraction of Lx, 0.5 = middle)", 0.0, 1.0, D["gk_xw"], 0.05, "%.2f")
                        inp["gk_yw"] = number("Well position across the box (fraction of Ly, 0.5 = middle)", 0.0, 1.0, D["gk_yw"], 0.05, "%.2f")
                    else:
                        st.caption("With a constant-pressure top the box size and the position along and across it are not used.")
                    inp["gk_zw"] = number("Well height above the bottom (fraction of h, 0.5 = middle)", 0.0, 1.0, D["gk_zw"], 0.05, "%.2f")
                inp["gh_rw"] = number("Wellbore radius rw (ft)", 0.1, 5, D["gh_rw"], 0.05, "%.3f")
                inp["gh_skin"] = number("Total skin factor" if inp["gas_ipr"] == "horizontal" else "Mechanical skin Sm",
                                        -5, 100, D["gh_skin"], 0.5)
                inp["gas_beta"] = number("Non-Darcy factor beta (1/ft); 0 = estimate from kh", 0, 1e12, D["gas_beta"], 1e8, "%.3e")
                st.caption("Turbulence is applied over the well length L (a long horizontal well has very little). "
                           "Gas Z-factor and viscosity are taken at 75 % of reservoir pressure.")
            elif inp["gas_ipr"] == "multilayer":
                st.caption("Several gas layers produce into the same well at the same flowing pressure; the layer rates are "
                           "added. Each layer has its own pressure, deliverability (Jones, Darcy, or C and n) and its own "
                           "condensate-gas and water-gas ratio, entered in the layer table. The static pressure above is "
                           "not used here: the curve starts at the highest layer pressure.")
                gm_layers_state()
                inp["gm_layers"] = [dict(r) for r in st.session_state["gm_layers"]]
                inp.update(st.session_state["gm_common"])
                gm_table_slot = st.empty()          # filled further down, once the gas properties (PVT section) are known
                if st.button("Edit gas layer table...", help="Opens the layer table: model, pressure, permeability/height/skin "
                                                             "or C and n, CGR and WGR of each layer."):
                    if open_gas_multilayer_window:
                        open_gas_multilayer_window()
                    else:
                        st.session_state["gm_inline"] = True
                inp["gm_crossflow"] = st.checkbox("Allow crossflow (a layer below the flowing pressure takes gas)",
                                                  value=False, key="gm_crossflow")
                st.caption("All layers are taken at the perforation reference depth and share one gas. The CGR and WGR "
                           "of the well stream are worked out from the layers at every rate.")
            else:
                inp["gas_k"] = number("Permeability k (md)", 0.001, 1e5, D["gas_k"], 1)
                inp["gas_h"] = number("Net thickness h (ft)", 1, 5000, D["gas_h"], 5)
                inp["gas_re"] = number("Drainage radius re (ft)", 10, 20000, D["gas_re"], 50)
                inp["gas_rw"] = number("Wellbore radius rw (ft)", 0.1, 5, D["gas_rw"], 0.05, "%.3f")
                inp["gas_skin"] = number("Total skin factor", -5, 100, D["gas_skin"], 0.5)
                if inp["gas_ipr"] == "jones":
                    inp["gas_beta"] = number("Non-Darcy factor beta (1/ft); 0 = estimate from k",
                                             0, 1e12, D["gas_beta"], 1e8, "%.3e")
                    inp["gas_h_perf"] = number("Perforated thickness (ft); 0 = same as h",
                                               0, 5000, D["gas_h_perf"], 5)
                st.caption("Gas Z-factor and viscosity are taken at 75 % of reservoir pressure.")

    # ---------------- fluid (PVT) ----------------
    with st.expander("Fluid (PVT)"):
        if is_oil:
            inp["api"] = number("Oil gravity (API)", 5, 70, D["api"], 1)
            inp["gas_sg"] = number("Solution gas gravity (air = 1)", 0.55, 1.5, D["gas_sg"], 0.01, "%.3f")
            inp["rsb"] = number("Solution GOR at bubble point (scf/STB)", 1, 5000, D["rsb"], 10)
            if inp["oil_ipr"] == "multilayer":
                st.caption("Water cut and producing GOR come from the layer table (Inflow performance).")
                inp["oil_gor"], inp["water_cut"] = 0.0, 0.0
            else:
                inp["oil_gor"] = number("Total (producing) GOR (scf/STB); 0 = same as solution GOR", 0, 50000,
                                        D["oil_gor"], 10)
                inp["water_cut"] = number("Water cut (%)", 0, 99, D["water_cut"] * 100, 5) / 100.0
            inp["water_sg"] = number("Water specific gravity (fresh water = 1)", 1.0, 1.25, D["water_sg"], 0.01, "%.3f")
            matched = st.session_state.get("pvt_applied")        # a PVT match from lab data is in use
            inp["pb_meas"] = number("Measured bubble point (psig); 0 = calculate", 0, 10000, D["pb_meas"], 50)
            inp["pvt_method"] = PVT_METHODS[st.selectbox("Pb, Rs, Bo correlation", list(PVT_METHODS), disabled=bool(matched))]
            inp["visc_method"] = OIL_VISC[st.selectbox("Oil viscosity correlation", list(OIL_VISC), disabled=bool(matched))]
            if matched:
                st.success(f"PVT matched to lab data: {PVT_NAMES[matched['pvt_method']]} + "
                           f"{VISC_NAMES[matched['visc_method']]}"
                           + (f", bubble point {matched['pb_meas']:,.0f} psig" if matched["pb_meas"] else "")
                           + ". The correlation and bubble-point boxes above are not used while the match is on.")
                st.button("Remove PVT match", on_click=remove_pvt_match)
                stale = pvt_match_stale_note(inp, matched)
                if stale:
                    st.warning(stale)
                inp = with_pvt_match(inp, matched)
            else:
                st.caption("Black-oil PVT.")
            if st.button("PVT matching with lab data...", help="Compare the correlations with laboratory PVT data "
                                                              "and match them (opens a larger window)."):
                lab_start = st.session_state.get("lab_saved")
                if lab_start is None:
                    lab_start = pd.DataFrame({c: [None] * 8 for c in LAB_COLUMNS}, dtype="float64")
                if open_pvt_window:
                    open_pvt_window(pvt_base(inp), lab_start, st.session_state.get("lab_pb_saved", 0.0))
                else:
                    st.session_state["pvt_inline"] = True
        else:
            inp["gas_sg_g"] = number("Gas gravity (air = 1)", 0.55, 1.5, D["gas_sg_g"], 0.01, "%.3f")
            if inp["gas_ipr"] == "multilayer":
                st.caption("Condensate-gas and water-gas ratios come from the layer table (Inflow performance).")
                inp["cgr"], inp["wgr"] = 0.0, 0.0
                inp["cond_api"] = number("Condensate gravity (API)", 30, 70, D["cond_api"], 1)
            else:
                inp["cgr"] = number("Condensate-gas ratio (STB/MMscf); 0 = dry gas", 0, 1000, D["cgr"], 5)
                inp["cond_api"] = number("Condensate gravity (API)", 30, 70, D["cond_api"], 1)
                inp["wgr"] = number("Water-gas ratio (STB/MMscf)", 0, 1000, D["wgr"], 1)
            inp["water_sg"] = number("Water specific gravity (fresh water = 1)", 1.0, 1.25, D["water_sg"], 0.01, "%.3f")
            inp["y_h2s"] = number("H2S (mole %)", 0, 50, D["y_h2s"] * 100, 0.5) / 100.0
            inp["y_co2"] = number("CO2 (mole %)", 0, 50, D["y_co2"] * 100, 0.5) / 100.0
            inp["gas_visc"] = GAS_VISC[st.selectbox("Gas viscosity correlation", list(GAS_VISC))]
            st.caption("PVT matching to lab data is available for Oil & Water; gas PVT matching is planned.")

    if gm_table_slot is not None and not is_oil:           # the gas layer table, now that gravity, T, H2S and CO2 are known
        try:
            gm_table_slot.dataframe(pd.DataFrame(gas_multilayer_summary(inp)), hide_index=True)
        except ValueError as error:
            gm_table_slot.warning(str(error))

    # ---------------- equipment ----------------
    with st.expander("Equipment"):
        shape = st.radio("Well path", ["Vertical", "Deviated / horizontal (MD, TVD table)"])
        if shape == "Vertical":
            inp["survey_mode"] = "vertical"
            inp["depth"] = number("Perforation depth, MD = TVD (ft)", 500, 40000, D["depth"], 100)
        else:
            inp["survey_mode"] = "deviated"
            st.caption("Survey table: measured depth (MD) and true vertical depth (TVD) in ft. Click the first cell "
                       "and paste two columns straight from Excel; add rows at the bottom. The first row is the "
                       "wellhead, the last row the perforations.")
            survey_start = pd.DataFrame(survey_rows(D["survey_text"]), columns=SURVEY_COLUMNS, dtype="float64")
            survey_table = st.data_editor(survey_start, num_rows="dynamic", hide_index=True, key="survey_table",
                                          use_container_width=True)
            inp["survey_text"] = survey_text_from_table(survey_table.to_dict("records"), SURVEY_COLUMNS)
        st.caption("The perforation depth is the reference depth for reservoir pressure and temperature.")
        inp["tubing_id"] = number("Tubing inner diameter (in)", 0.5, 12, D["tubing_id"], 0.1, "%.3f")
        inp["roughness_in"] = number("Pipe roughness (in)", 0, 0.1, D["roughness_in"], 0.0001, "%.4f")
        inp["p_wh"] = number("Wellhead flowing pressure (psig)", 0, 5000, D["p_wh"], 10)
        st.markdown("**Temperature profile**")
        inp["t_amb_surface"] = number("Ambient temperature at surface (degF)", -20, 150, D["t_amb_surface"], 5)
        inp["u_surface"] = number("Overall heat transfer coefficient at surface (Btu/h/ft2/F)", 0, 50, D["u_surface"], 0.5)
        inp["perf_ambient_is_reservoir"] = st.checkbox("Ambient temperature at perforations = reservoir temperature", value=True)
        if not inp["perf_ambient_is_reservoir"]:
            inp["t_amb_perf"] = number("Ambient temperature at perforations (degF)", 50, 400, D["t_amb_perf"], 5)
        inp["u_perf"] = number("Overall heat transfer coefficient at perforations (Btu/h/ft2/F)", 0, 50, D["u_perf"], 0.5)

    # ---------------- gas lift ----------------
    if inp["lift"] == "continuous":
        with st.expander("Gas lift (continuous)", expanded=True):
            st.caption("The lift gas is injected at one depth (valve or orifice). Above that depth the tubing "
                       "carries the formation gas plus the lift gas, so the column is lighter.")
            inp["gl_rate"] = number("Gas injection rate (Mscf/d)", 0, 1e6, D["gl_rate"], 100)
            inp["gl_md"] = number("Injection depth (ft, measured depth)", 100, 40000, D["gl_md"], 100)
            perf = perforation_md(inp)
            if perf:
                st.caption(f"Perforations are at {perf:,.0f} ft MD; the injection depth must be above them.")
            inp["gl_sg"] = number("Injection gas gravity (air = 1)", 0.55, 1.5, D["gl_sg"], 0.01, "%.3f")
            inp["gl_p_inj"] = number("Injection pressure at the wellhead (psig); 0 = no check", 0, 10000,
                                     D["gl_p_inj"], 50)
            st.caption("The injection pressure is only used to check that the casing gas pressure at the "
                       "injection depth is higher than the tubing pressure there.")

    # ---------------- VLP correlation ----------------
    choices = OIL_CORRELATIONS if is_oil else GAS_CORRELATIONS
    # The box starts on the correlation the app suggests for the fluid, the water cut and the well path (see
    # correlation_advice() in app_helpers.py) and follows that suggestion while the inputs change, until the user
    # chooses a correlation by hand.  The text under it says why the correlation may suit the well.
    st.markdown('<div class="section-name">VLP correlation</div>', unsafe_allow_html=True)
    suggested, _why = recommend_correlation(inp)
    st.session_state.setdefault("vlp_pick_manual", False)
    if not st.session_state["vlp_pick_manual"] or st.session_state.get("vlp_pick") not in choices:
        st.session_state["vlp_pick"] = suggested
        st.session_state["vlp_pick_manual"] = False
    picked = st.selectbox("VLP correlation", choices, key="vlp_pick", label_visibility="collapsed",
                          format_func=lambda key: CORRELATION_NAMES[key], on_change=mark_manual_pick)
    inp["correlation"] = picked
    st.caption(correlation_caption(inp, picked))
    if st.session_state["vlp_pick_manual"] and picked != suggested:
        st.button(f"Use the app's suggestion ({CORRELATION_NAMES[suggested]})", on_click=follow_suggestion)
    if inp["correlation"] == "orkiszewski":
        st.caption("Orkiszewski (1967) was made for vertical oil and gas lift wells (it was found best for heavy "
                   "oil). In a deviated well the app uses it along the measured length with the gravity part "
                   "scaled by the pipe angle, so treat it as less certain there.")
    if inp["correlation"] == "ansari":
        st.caption("Ansari et al. (1994) is a mechanistic model: it picks the flow pattern (bubble, slug or annular) "
                   "from the physics and uses a separate model for each. It was developed and tested on vertical "
                   "wells; in a deviated well the app only scales the gravity part by the pipe angle, so treat it "
                   "as less certain there.")
    if inp["correlation"] == "duns_ros":
        st.caption("Duns and Ros (1963) is a vertical-flow correlation with three flow regions (bubble/plug/froth, "
                   "slug and mist) and a transition between slug and mist. Its charts were read from the paper, so "
                   "expect small differences from other implementations. In a deviated well the app only scales the "
                   "gravity part by the pipe angle. It was made for less than 10% water.")
    if inp["correlation"] == "mukherjee_brill":
        st.caption("Mukherjee and Brill (1983/1985) works at any angle, uphill or downhill, so it is the one to try for "
                   "deviated and horizontal sections. Its flow-pattern map and friction method are from the 1985 "
                   "pressure-drop paper (see the README for what was checked).")
    if inp["correlation"] == "fancher_brown":
        st.caption("Fancher and Brown (1963) treats gas and liquid as one fluid with no slip, so it gives the lowest "
                   "possible VLP and shows no well loading. It is useful only as a quality check: a measured "
                   "flowing pressure that falls below it means the fluid density (PVT) or the pressure data are wrong. "
                   "It was measured in a 2 3/8 in oil and water gas lift well; do not use it for real predictions. "
                   "Its friction factor steps where the gas-liquid ratio crosses 1500 and 3000 scf/STB.")
    if not is_oil and inp["correlation"] in ("beggs_brill", "hagedorn_brown", "orkiszewski", "duns_ros", "mukherjee_brill", "ansari"):
        st.caption("For gas wells that make a little condensate or water, Gray is the "
                   "correlation made for the job. Beggs and Brill and Hagedorn and Brown "
                   "tend to over- or under-estimate the pressure loss.")

    # ---------------- VLP matching: gravity and friction multipliers ----------------
    # No correlation fits every well.  When a measured flowing pressure is available, these two numbers scale the
    # correlation's pressure drop to match it (the usual "VLP matching").  The controls live on the
    # *VLP comparison and matching* tab, next to the comparison with the measured data, because the two belong
    # together: you compare the correlations with your measurement, then match the one you keep.  Only the values
    # are read here, because build_case() needs them before the tabs are drawn.
    st.session_state.setdefault("gravity_mult", D["gravity_mult"])
    st.session_state.setdefault("friction_mult", D["friction_mult"])
    pending = st.session_state.pop("pending_mult", None)         # set by a match on the VLP comparison tab
    if pending:                                                  # (applied before the sliders are drawn there)
        st.session_state["gravity_mult"], st.session_state["friction_mult"] = pending
        st.session_state["recalc"] = True
    inp["gravity_mult"] = st.session_state["gravity_mult"]
    inp["friction_mult"] = st.session_state["friction_mult"]
    fitted = False
    if (inp["gravity_mult"], inp["friction_mult"]) == (1.0, 1.0):
        st.caption("VLP matching is off (both multipliers 1.00, the correlations as published). "
                   "The *VLP comparison and matching* tab compares the correlations with a measured pressure "
                   "and matches the one you keep.")
    else:
        st.caption(f"VLP matching is ON: gravity x{inp['gravity_mult']:.2f}, friction x{inp['friction_mult']:.2f} "
                   "(set on the *VLP comparison and matching* tab).")

    run = st.button("Calculate", type="primary") or fitted or st.session_state.pop("recalc", False)


# =====================================================================
# Run the calculation (on the first visit, and every time Calculate is pressed)
# =====================================================================
if run or "output" not in st.session_state:
    if inp["correlation"] not in AVAILABLE_CORRELATIONS:
        ready = ", ".join(CORRELATION_NAMES[k] for k in choices if k in AVAILABLE_CORRELATIONS)
        st.warning(f"{CORRELATION_NAMES[inp['correlation']]} is not available yet. "
                   f"Please choose one of: {ready}.")
    else:
        try:
            with st.spinner("Calculating..."):
                case = build_case(inp)
                st.session_state["output"] = run_case(case)
                st.session_state["case"] = case
                st.session_state["inputs"] = dict(inp)
                st.session_state.pop("sensitivity", None)         # old sensitivity no longer matches
                st.session_state.pop("corr_check", None)          # and so does an old correlation check
                st.session_state.pop("vc_result", None)           # and an old comparison with measured pressures
                st.session_state.pop("glp", None)
                st.session_state.pop("gld_result", None)      # a gas lift design no longer matches
        except (ValueError, RuntimeError) as error:
            st.error(f"Cannot calculate: {error}")


# =====================================================================
# Show the results
# =====================================================================
if "output" in st.session_state:
    out = st.session_state["output"]
    case = st.session_state["case"]
    res = out["result"]
    rate_label = case["rate_label"]
    unit = rate_unit(rate_label)                                  # "STB/d" or "Mscf/d"

    matching_note = multiplier_note(case)
    if matching_note:                      # never let adjusted results pass for the plain correlation
        st.info(f"{matching_note}. These results are not the plain correlation. "
                "To remove the adjustment, open the *VLP comparison and matching* tab and press Reset to 1.00.")

    if not res["found"]:
        st.error(res["message"])

    notes = []
    if "pb" in case:
        notes.append(f"Bubble point used: {to_psig(case['pb']):,.0f} psig")
    if "gas_sg_used" in case:
        notes.append(f"Gas gravity used: {case['gas_sg_used']:.3f}")
    if any(not c["stable"] for c in res["crossings"]):
        notes.append("A second, unstable crossing exists at a lower rate (marked with a grey cross)")
    water_cut = getattr(case["solve"]["fluid"], "water_cut", 0.0)    # gas wells have none here
    if res.get("mix") and "cgr" in res["mix"]:                          # gas multilayer: the mix at the operating point
        notes.append(f"Commingled gas layers at the operating point: CGR {res['mix']['cgr']:,.1f} STB/MMscf, "
                     f"WGR {res['mix']['wgr']:,.1f} STB/MMscf")
    elif res.get("mix"):                                                # oil multilayer: the mix at the operating point
        water_cut = res["mix"]["water_cut"]
        notes.append(f"Commingled layers at the operating point: water cut {res['mix']['water_cut'] * 100:.1f} %, "
                     f"GOR {res['mix']['gor']:,.0f} scf/STB")

    tab_charts, tab_sens, tab_vlp, tab_lift, tab_esp = st.tabs(
        ["IPR / VLP and P-T profiles", "Sensitivity", "VLP comparison and matching", "Gas Lift Design", "ESP Design"])

    with tab_charts:
        # The two charts side by side: inflow/outflow curves on the left, profile on the right.
        # The operating rate, bottom-hole pressure and AOF are written inside the IPR/VLP chart.
        left, right = st.columns(2)
        with left:
            st.subheader("IPR / VLP")
            show_figure(make_nodal_figure(out["curves"], res, rate_label, water_cut, case["gas_lift"]))
        with right:
            st.subheader("Pressure and temperature profile")
            if out["traverse"] is None:
                st.info("There is no operating point, so there is no profile to show.")
            else:
                tr = out["traverse"]
                show_figure(make_profile_figure(tr, injection_md=case["gas_lift"]["md"] if case["gas_lift"] else None))
        if notes:
            st.caption(" | ".join(notes))
        if out.get("gas_lift_check") and not out["gas_lift_check"]["ok"]:
            st.warning(out["gas_lift_check"]["message"])
        if out["traverse"] is not None:
            tr = out["traverse"]
            st.caption(f"At the operating rate: wellhead {to_psig(tr['p'][0]):,.0f} psig and {tr['T'][0]:,.0f} degF; "
                       f"perforations {to_psig(tr['p'][-1]):,.0f} psig and {tr['T'][-1]:,.0f} degF. "
                       f"Pressure drop in the tubing: gravity {tr['dp_hydrostatic']:,.0f} psi, "
                       f"friction {tr['dp_friction']:,.0f} psi.")

        # ---- is this the right VLP correlation? ----
        with st.expander("Check the VLP correlation for this well"):
            st.caption("No correlation fits every well; only a measured flowing pressure (VLP matching) can say which one "
                       "is right. This runs the well with every correlation and shows what each one gives, the flow "
                       "patterns it finds, and the advice for this fluid and well path. It takes about "
                       "ten seconds.")
            if st.button("Compare all correlations"):
                try:
                    with st.spinner("Running every correlation..."):
                        st.session_state["corr_check"] = check_correlations(st.session_state["inputs"])
                except (ValueError, RuntimeError) as error:
                    st.error(f"Cannot compare: {error}")
            check = st.session_state.get("corr_check")
            if check:
                table = []
                for row in check["rows"]:
                    patterns = ", ".join(f"{name} {100 * share:.0f} %" for name, share in
                                         sorted(row["shares"].items(), key=lambda kv: -kv[1]))
                    table.append({"Correlation": CORRELATION_NAMES[row["key"]],
                                  "Rating": row["rating"],
                                  f"Rate ({unit})": f"{row['q']:,.0f}" if row["q"] else "no flow",
                                  "Bottom-hole pressure (psig)": f"{to_psig(row['pwf']):,.0f}" if row["pwf"] else "",
                                  "Flow patterns (share of the well)": patterns,
                                  "Notes": row["error"] or " ".join(row["notes"])})
                st.dataframe(pd.DataFrame(table), hide_index=True)
                for line in check["why"]:
                    st.caption(line)
                if check["suggested"]:
                    st.caption(f"Suggested for this well: **{CORRELATION_NAMES[check['suggested']]}**. "
                               "Choose it in the sidebar and press Calculate.")

    with tab_sens:
        options = sensitivity_options(st.session_state["inputs"])
        by_label = {o["label"]: o for o in options}
        # The vertical axis of the sensitivity chart is the PRODUCED rate: oil for an oil & water well, gas for a gas well
        is_oil_case = case["fluid_type"] == "oil"
        sens_rate_label = "Oil rate (STB/d)" if is_oil_case else "Produced gas rate (Mscf/d)"
        chosen = by_label[st.selectbox("Input to vary", list(by_label))]
        # Explain why an input is missing from the list instead of leaving the user guessing
        saved = st.session_state["inputs"]
        if (inp.get("oil_ipr"), inp.get("gas_ipr")) != (saved.get("oil_ipr"), saved.get("gas_ipr")):
            st.info("You changed the IPR model in the sidebar. Press Calculate so this list matches the new model.")
        elif "skin" not in [o["key"] for o in options]:
            st.caption("Total skin factor is offered when the IPR model has a skin term: Darcy or horizontal well "
                       "(oil), Darcy or Jones (gas). The current IPR model (PI, Vogel, Fetkovich or back pressure) "
                       "has no skin factor; choose Darcy in the sidebar and press Calculate.")
        entry = st.radio("Values to use", ["Automatic range", "Enter my own values"], horizontal=True)
        values, values_error = None, None
        if entry == "Automatic range":
            low_col, high_col, n_col = st.columns(3)
            step = max((chosen["high"] - chosen["low"]) / 20.0, 0.001)
            with low_col:
                low = number("From", -1e9, 1e9, chosen["low"], step, "%.3f")
            with high_col:
                high = number("To", -1e9, 1e9, chosen["high"], step, "%.3f")
            with n_col:
                n_values = st.slider("Number of points", 3, 8, 5)
            if high <= low:
                values_error = "'To' must be larger than 'From'."
            else:
                values = evenly_spaced(low, high, n_values)
        else:
            suggestion = ", ".join(f"{v:.4g}" for v in evenly_spaced(chosen["low"], chosen["high"], 5))
            typed = st.text_input("Values, separated by commas (2 to 12 values)", value=suggestion)
            try:
                values = parse_value_list(typed)
            except ValueError as error:
                values_error = str(error)
        if st.button("Run sensitivity"):
            if values_error:
                st.error(values_error)
            else:
                try:
                    with st.spinner("Running sensitivity..."):
                        results = run_sensitivity(case, chosen["key"], values, with_curves=True)
                        st.session_state["sensitivity"] = {"results": results, "label": chosen["label"],
                                                           "key": chosen["key"]}
                except (ValueError, RuntimeError) as error:
                    st.error(f"Cannot calculate: {error}")
        # Two charts side by side: IPR / VLP on the left (one curve for each value of the varied input once the
        # sensitivity has been run, otherwise the base case), the sensitivity on the right
        left, right = st.columns(2)
        with left:
            st.subheader("IPR / VLP")
            if "sensitivity" in st.session_state:
                sens = st.session_state["sensitivity"]
                show_figure(make_sensitivity_nodal_figure(sens["results"], sens["label"], rate_label, sens["key"]))
            else:
                show_figure(make_nodal_figure(out["curves"], res, rate_label, water_cut, case["gas_lift"]))
        with right:
            st.subheader("Sensitivity")
            if "sensitivity" in st.session_state:
                sens = st.session_state["sensitivity"]
                show_figure(make_sensitivity_figure(sens["results"], sens["label"], sens_rate_label, "q_oil"))
            else:
                st.info("Choose the input and its range above, then press 'Run sensitivity'.")
        if "sensitivity" in st.session_state:
            sens = st.session_state["sensitivity"]
            st.dataframe(pd.DataFrame(sensitivity_table(sens["results"], sens["label"], rate_label,
                                                        sens_rate_label if is_oil_case else None)),
                         hide_index=True)

    with tab_vlp:
        # ---- compare the VLP correlations with a measured pressure survey, and match the selected one to it ----
        saved = {**D, **st.session_state["inputs"]}              # the inputs of the last Calculate
        saved_oil = saved["fluid_type"] == "oil"
        saved_names = CORRELATION_NAMES[saved["correlation"]]
        st.subheader("VLP comparison and matching (optional)")
        st.caption("Enter the conditions of a flowing survey and the measured pressures (a downhole gauge reading or a "
                   "flowing gradient survey, up to "
                   f"{SURVEY_MAX_POINTS} points). The app runs the tubing calculation with each correlation you tick and "
                   "shows how close it comes. Depths are measured depth (MD); every pressure is gauge pressure (psig). "
                   "It uses the fluid, well and IPR entered in the sidebar at the last Calculate. "
                   "The multipliers that carry the match into the rest of the app are at the bottom of this tab.")
        left_c, right_c = st.columns([5, 4])
        with left_c:
            st.markdown("**Test conditions**")
            t_p_wh = number("Wellhead flowing pressure (psig)", 0, 10000, saved["p_wh"], 10, key="vc_p_wh")
            test = {"p_wh": t_p_wh}
            if saved_oil:
                gor_default = saved["oil_gor"] if saved["oil_gor"] > 0 else saved["rsb"]
                t_wc = number("Water cut (%)", 0, 99, saved["water_cut"] * 100, 5, key="vc_wc")
                t_type = st.radio("Rate type", ["Liquid rate", "Oil rate"], horizontal=True, key="vc_rate_type")
                t_rate = number("Rate (STB/d)", 1, 1e7, 2000.0, 100, key="vc_rate_oil")
                t_gor = number("GOR (scf/STB of oil)", 0, 100000, gor_default, 50, key="vc_gor")
                test.update(rate=t_rate, rate_type="oil" if t_type == "Oil rate" else "liquid",
                            water_cut=t_wc / 100.0, gor=t_gor)
                if saved["oil_ipr"] == "multilayer":
                    st.caption("The IPR is multilayer, so the water cut and GOR of the layers' mix at this rate are used instead.")
            else:
                t_rate = number("Gas rate (Mscf/d)", 1, 1e7, 5000.0, 100, key="vc_rate_gas")
                t_cgr = number("Condensate-gas ratio (STB/MMscf)", 0, 1000, saved["cgr"], 5, key="vc_cgr")
                t_wgr = number("Water-gas ratio (STB/MMscf)", 0, 1000, saved["wgr"], 5, key="vc_wgr")
                test.update(rate=t_rate, cgr=t_cgr, wgr=t_wgr)
            # Gas lift: the boxes are live only when the well is on continuous gas lift, otherwise grey
            on_gl = saved["lift"] == "continuous"
            test["gl_rate"] = number("Gas lift gas rate (Mscf/d)", 0, 1e6, saved["gl_rate"], 100,
                                     key="vc_gl_rate", disabled=not on_gl)
            test["gl_md"] = number("Depth of injection (ft, measured depth)", 100, 40000, saved["gl_md"], 100,
                                   key="vc_gl_md", disabled=not on_gl)
            if not on_gl:
                st.caption("The gas lift boxes are grey because the artificial lift is not continuous gas lift.")
        with right_c:
            st.markdown("**Measured data**")
            st.caption("Click the first cell and paste two columns straight from Excel (depth, pressure).")
            version = st.session_state.setdefault("vc_table_ver", 0)
            blank = pd.DataFrame({c: [None] * SURVEY_MAX_POINTS for c in SURVEY_COLUMNS}, dtype="float64")
            table = st.data_editor(blank, num_rows="fixed", key=f"vc_table_{version}", use_container_width=True)
            st.button("Clear table", on_click=clear_survey_table)

        st.markdown("**Correlations to compare**")
        names_now = OIL_CORRELATIONS if saved_oil else GAS_CORRELATIONS
        st.session_state["vc_corrs"] = [k for k in st.session_state.get("vc_corrs", names_now) if k in names_now]
        chosen_corrs = st.multiselect("Correlations", names_now, key="vc_corrs", label_visibility="collapsed",
                                      format_func=lambda key: CORRELATION_NAMES[key])
        if st.button("Compare", type="primary"):
            try:
                depths, pressures = survey_points(table.to_dict("records"), perforation_md(saved))
                if not chosen_corrs:
                    raise ValueError("Tick at least one correlation.")
                g_now, f_now = saved["gravity_mult"], saved["friction_mult"]
                with st.spinner("Running the correlations..."):
                    st.session_state["vc_result"] = compare_to_survey(
                        saved, test, depths, pressures, chosen_corrs,
                        matched=(saved["correlation"], g_now, f_now) if (g_now, f_now) != (1.0, 1.0) else None)
                st.session_state["vc_points"] = (depths, pressures, dict(test))
            except (ValueError, RuntimeError) as error:
                st.session_state.pop("vc_result", None)
                st.error(f"Cannot compare: {error}")
        cmp_result = st.session_state.get("vc_result")
        if cmp_result:
            rows = [r for r in cmp_result["rows"] if r["ok"]]
            for r in cmp_result["rows"]:
                if not r["ok"]:
                    st.warning(f"{r['label']}: {r['error']}")
            if rows:
                chart_c, table_c = st.columns([5, 4])
                with chart_c:
                    show_figure(make_survey_figure(cmp_result))
                with table_c:
                    st.dataframe(pd.DataFrame([
                        {"Correlation": r["label"], "Mean error (psi)": f"{r['bias']:+,.0f}",
                         "Mean absolute error (psi)": f"{r['mae']:,.0f}", "RMS error (psi)": f"{r['rms']:,.0f}",
                         "Mean absolute error (%)": f"{r['pct']:.1f}"} for r in rows]), hide_index=True)
                    st.caption("Error = calculated minus measured pressure, over the measured points. "
                               "A positive mean error means the correlation over-predicts the pressure drop.")
                if cmp_result["best"]:
                    best_row = [r for r in rows if r["label"] == cmp_result["best"]][0]
                    st.success(f"Closest to the measured data: **{cmp_result['best']}** "
                               f"(RMS error {best_row['rms']:,.0f} psi, {best_row['pct']:.1f} % mean absolute error).")
                fb_rows = [r for r in rows if r["key"] == "fancher_brown"]
                if fb_rows and saved_oil:
                    deepest = max(range(len(cmp_result["depths"])), key=lambda n: cmp_result["depths"][n])
                    if cmp_result["measured"][deepest] < fb_rows[0]["calc"][deepest]:
                        st.warning("The deepest measured pressure is below the Fancher and Brown (no slip) calculation, which "
                                   "should be the lowest possible. Check the fluid density (PVT), the rate and the pressure data first.")
                with st.expander("Calculated pressure at each measured depth"):
                    detail = {"Depth MD (ft)": [f"{d:,.0f}" for d in cmp_result["depths"]],
                              "Measured (psig)": [f"{p:,.0f}" for p in cmp_result["measured"]]}
                    for r in rows:
                        detail[r["label"]] = [f"{x:,.0f}" for x in r["calc"]]
                    st.dataframe(pd.DataFrame(detail), hide_index=True)

        # ---- match the selected correlation ----
        st.markdown("**Match the selected correlation to the measured data**")
        st.caption(f"The selected correlation is **{saved_names}**. The app finds the gravity and friction "
                   "multipliers that bring it closest to your measured pressures (least squares), puts them on the "
                   "sliders at the bottom of this tab, and recalculates. Two or more points at different depths "
                   "can fix both multipliers; one point can fix only one. Keep the multipliers near 1.00: a match that "
                   "needs a value at the edge of 0.50 - 2.00 means the fluid, rate or well data should be checked first.")
        fit_labels = {"Friction and gravity together (2 or more points)": "both", "Friction only": "friction",
                      "Gravity only": "gravity"}
        fit_pick = fit_labels[st.radio("Multipliers to find", list(fit_labels), horizontal=True, key="vc_fit")]
        if st.button("Match to the measured data"):
            try:
                depths, pressures = survey_points(table.to_dict("records"), perforation_md(saved))
                with st.spinner("Matching..."):
                    found = match_to_survey(saved, test, depths, pressures, saved["correlation"], fit_pick)
                msg = (f"{saved_names}: gravity multiplier {found['gravity']:.2f}, friction multiplier "
                       f"{found['friction']:.2f}. The RMS error at the measured points falls from "
                       f"{found['rms_before']:,.0f} to {found['rms_after']:,.0f} psi. The sliders below are set and "
                       "the whole case is recalculated.")
                if found["at_limit"]:
                    msg += (" The " + " and ".join(found["at_limit"]) + " multiplier is at the edge of its range, so "
                            "the match is not reliable: check the fluid, the rate and the pressure data, or try another correlation.")
                st.session_state["vc_match_msg"] = msg
                st.session_state["pending_mult"] = (found["gravity"], found["friction"])
                st.session_state.pop("vc_result", None)
                st.rerun()
            except (ValueError, RuntimeError) as error:
                st.session_state.pop("vc_match_msg", None)
                st.error(f"Cannot match: {error}")
        if st.session_state.get("vc_match_msg"):
            st.success(st.session_state["vc_match_msg"])

        # ---- match from one measured test (no survey: a single bottom-hole pressure) ----
        st.markdown("---")
        with st.expander("Match from a single measured test (one rate, one bottom-hole pressure)"):
            st.caption("Use this when there is only one measured flowing bottom-hole pressure and no gradient "
                       "survey. One test can fix one multiplier, not both. The fluid, well and IPR are the ones "
                       "entered in the sidebar at the last Calculate.")
            unit_text = "STB/d" if saved_oil else "Mscf/d"
            test_rate = number(f"Test rate ({unit_text})", 1, 1e7, 2000.0 if saved_oil else 5000.0, 100,
                               key="match_rate_oil" if saved_oil else "match_rate_gas")
            test_p_wh = number("Wellhead pressure in the test (psig)", 0, 10000, saved["p_wh"], 10, key="match_p_wh")
            test_pwf = number("Measured bottom-hole pressure (psig)", 0, 20000, 2000.0, 50, key="match_pwf")
            # The gas lift of the test: only for a well on continuous gas lift, otherwise the boxes are greyed out
            on_gas_lift = saved["lift"] == "continuous"
            test_gl_rate = number("Gas lift gas rate in the test (Mscf/d)", 0, 1e6, saved["gl_rate"], 100,
                                  key="match_gl_rate", disabled=not on_gas_lift)
            test_gl_md = number("Gas injection depth in the test (ft, measured depth)", 100, 40000, saved["gl_md"], 100,
                                key="match_gl_md", disabled=not on_gas_lift)
            if not on_gas_lift:
                st.caption("The gas lift boxes are grey because the artificial lift is not continuous gas lift.")
            fit_choice = st.radio("Multiplier to find", ["Friction (recommended)", "Gravity"], horizontal=True,
                                  key="match_fit",
                                  help="Friction is the usual first choice (pipe roughness is the least certain input) "
                                       "and works best for gas wells, where friction is most of the pressure drop. "
                                       "Choose Gravity if the weight of the fluid column looks wrong.")
            if st.button("Find multiplier"):
                try:
                    which = "friction" if fit_choice.startswith("Friction") else "gravity"
                    with st.spinner("Matching..."):
                        found1 = match_from_test(saved, test_rate, test_p_wh, test_pwf, which,
                                                 test_gl_rate if on_gas_lift else None,
                                                 test_gl_md if on_gas_lift else None)
                    pair = {"friction": (1.0, found1["multiplier"]), "gravity": (found1["multiplier"], 1.0)}[which]
                    st.session_state["vc_match_msg"] = (
                        f"{which.capitalize()} multiplier set to {found1['multiplier']:.2f}. Without it the "
                        f"correlation gives {found1['plain_pwf']:,.0f} psig for this test; with it "
                        f"{found1['matched_pwf']:,.0f} psig (measured {test_pwf:,.0f} psig). "
                        "The whole case is recalculated.")
                    st.session_state["pending_mult"] = pair
                    st.session_state.pop("vc_result", None)
                    st.rerun()
                except (ValueError, RuntimeError) as error:
                    st.error(f"Cannot match: {error}")

        # ---- the multipliers themselves: what the rest of the app uses ----
        st.markdown("---")
        st.markdown("**Multipliers in use**")
        st.caption("These two numbers scale the pressure drop of the selected correlation everywhere else in the "
                   "app (the IPR / VLP chart, the profile, the sensitivities and the gas lift design). "
                   "**1.00 = the correlation as published.** A match above sets them; you can also move them by hand.")
        mc1, mc2 = st.columns(2)
        with mc1:
            st.slider("Gravity multiplier", MULTIPLIER_MIN, MULTIPLIER_MAX, step=0.01, format="%.2f",
                      key="gravity_mult",
                      help="Scales the weight of the fluid column (the hydrostatic part of the pressure drop). "
                           "Leave at 1.00 unless the fluid density in the tubing is clearly not what the "
                           "correlation predicts.")
        with mc2:
            st.slider("Friction multiplier", MULTIPLIER_MIN, MULTIPLIER_MAX, step=0.01, format="%.2f",
                      key="friction_mult",
                      help="Scales the friction part of the pressure drop. This is the one normally adjusted: "
                           "above 1.00 the tubing needs more pressure at a given rate, below 1.00 less.")
        in_use = (st.session_state["gravity_mult"], st.session_state["friction_mult"])
        applied = (saved["gravity_mult"], saved["friction_mult"])
        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button("Use these multipliers", type="primary" if in_use != applied else "secondary"):
                st.session_state["pending_mult"] = in_use
                st.session_state.pop("vc_match_msg", None)
                st.session_state.pop("vc_result", None)
                st.rerun()
        with bc2:
            if st.button("Reset to 1.00"):
                st.session_state["pending_mult"] = (1.0, 1.0)
                st.session_state.pop("vc_match_msg", None)
                st.session_state.pop("vc_result", None)
                st.rerun()
        if in_use != applied:
            st.warning(f"The results shown elsewhere still use gravity x{applied[0]:.2f}, friction x{applied[1]:.2f}. "
                       "Press **Use these multipliers** to recalculate with the values above.")
        elif in_use == (1.0, 1.0):
            st.caption("VLP matching is off: the correlations are used exactly as published.")
        else:
            st.caption(f"In use everywhere: gravity x{applied[0]:.2f}, friction x{applied[1]:.2f}.")

    with tab_lift:
        # Check existing valves / design IPO or PPO valves / unloading animation: see gaslift_tab.py.
        # Its inputs are in the tab itself (not in the sidebar).
        gaslift_tab.render(st, pd, case, out, inp, show_figure, number)
        st.markdown("---")
        st.markdown("**Gas lift performance (rate against injected gas)** - uses the gas lift settings of the sidebar")
        if not case["gas_lift"]:
            st.info("Choose **Gas lift** under 'Artificial lift' in the sidebar (Oil & Water), then press "
                    "Calculate. The IPR / VLP chart and the Sensitivity tab then include the lift gas.")
        else:
            gl = case["gas_lift"]
            st.caption(f"Injecting {gl['rate']:,.0f} Mscf/d at {gl['md']:,.0f} ft MD "
                       f"(gas gravity {gl['sg']:g}).")
            check = out.get("gas_lift_check")
            if check:
                (st.success if check["ok"] else st.warning)(check["message"])
            else:
                st.caption("Type an injection pressure in the sidebar to check the pressure across the injection point.")
            st.markdown("**Gas lift performance curve**: oil rate against the injected gas rate "
                        "(the other inputs stay as they are).")
            c1, c2, c3 = st.columns(3)
            with c1:
                glp_low = number("From (Mscf/d)", 0, 1e6, 0.0, 100, "%.0f")
            with c2:
                glp_high = number("To (Mscf/d)", 1, 1e6, 2.0 * max(gl["rate"], 500.0), 100, "%.0f")
            with c3:
                glp_n = st.slider("Number of points", 4, 10, 7)
            if st.button("Run gas lift performance"):
                if glp_high <= glp_low:
                    st.error("'To' must be larger than 'From'.")
                else:
                    try:
                        with st.spinner("Running gas lift performance..."):
                            glp_results, glp_best = gas_lift_performance(case, evenly_spaced(glp_low, glp_high, glp_n))
                            st.session_state["glp"] = {"results": glp_results, "best": glp_best}
                    except (ValueError, RuntimeError) as error:
                        st.error(f"Cannot calculate: {error}")
            if "glp" in st.session_state:
                glp = st.session_state["glp"]
                left, right = st.columns(2)
                with left:
                    show_figure(make_gl_performance_figure(glp["results"], glp["best"]))
                with right:
                    st.dataframe(pd.DataFrame(sensitivity_table(glp["results"], "Gas injection rate (Mscf/d)",
                                                                rate_label, "Oil rate (STB/d)")), hide_index=True)
                if glp["best"] is None:
                    st.warning("The well does not flow at any of these injection rates.")
                else:
                    st.caption(f"Highest oil rate in this range: {glp['best']['q_oil']:,.0f} STB/d at "
                               f"{glp['best']['value']:,.0f} Mscf/d. Past the highest point, more gas only adds "
                               f"friction and the oil rate falls.")

    with tab_esp:
        st.subheader("ESP Design")
        st.info("Coming soon: electrical submersible pump selection and design. Inputs for the ESP will be entered "
                "in this tab.")

    # Older Streamlit without pop-up windows: the layer table opens here instead
    if open_multilayer_window is None and st.session_state.get("ml_inline"):
        with st.expander("Multilayer IPR: layer table", expanded=True):
            multilayer_window()

    if open_gas_multilayer_window is None and st.session_state.get("gm_inline"):
        with st.expander("Gas multilayer IPR: layer table", expanded=True):
            gas_multilayer_window()

    # Older Streamlit without pop-up windows: the PVT matching screen opens here instead
    if open_pvt_window is None and st.session_state.get("pvt_inline"):
        with st.expander("PVT matching with laboratory data", expanded=True):
            lab_start = st.session_state.get("lab_saved")
            if lab_start is None:
                lab_start = pd.DataFrame({c: [None] * 8 for c in LAB_COLUMNS}, dtype="float64")
            pvt_matching_window(pvt_base(inp), lab_start, st.session_state.get("lab_pb_saved", 0.0))
