"""
gaslift_design.py - connects the valve engine (gaslift_valves.py) to a nodal-analysis case.

It turns the case of the page (well, fluid, correlation) plus the gas lift design inputs into the
pressure lines the engine needs, runs the design or the check, and draws the charts.  No Streamlit code.

The inputs of the Gas Lift Design tab are one dictionary, `g`:
    rate          design liquid rate (STB/d)
    gas_rate      injection gas rate (Mscf/d) at the design rate
    md_inj        wanted depth of the injection point (ft MD)
    md_max        deepest depth a valve may be run to (ft MD)
    gas_sg        injection gas gravity
    p_ko, p_op    surface injection pressure for kick-off / for normal operation (psig)
    p_wh          wellhead pressure during unloading and production (psig)
    g_unload      load (kill) fluid gradient (psi/ft)
    sfl_md        static liquid level in the annulus (ft MD, 0 = full)
    casing_id, tubing_od   (in) for the annulus and tubing volumes
    od, port      unloading valve OD key of gaslift_valves.VALVE_CATALOGUE and port diameter (in)
    dome_method   'api', 'winkler' or 'gas_law'
    min_spacing   (ft MD), dp_valve (psi), drop_mode ('fixed'|'min'|'max'), drop_fixed (psi)
    operating     'orifice' or 'valve' for the operating (bottom) valve
    surface_drop  psi the operator lowers the surface pressure per valve (check of existing valves)
"""
import dataclasses
import math

import numpy as np
from matplotlib.figure import Figure

import gaslift_valves as gv
from vlp import pressure_traverse, OilWaterFluid
from nodal import fluid_at_rate

PSIA = gv.ATM

GL_DEFAULTS = dict(rate=500.0, gas_rate=500.0, md_inj=6000.0, md_max=7900.0, gas_sg=0.65,
                   p_ko=1200.0, p_op=1100.0, p_wh=120.0, g_unload=0.465, sfl_md=0.0,
                   casing_id=6.276, tubing_od=2.875, od="1 in OD", port=0.1875, dome_method="api",
                   min_spacing=250.0, dp_valve=20.0, drop_mode="fixed", drop_fixed=25.0, operating="orifice",
                   surface_drop=20.0)

CHECK_KINDS = ["Dummy", "IPO valve", "PPO valve", "Orifice"]
_KIND_KEY = {"Dummy": "dummy", "IPO valve": "IPO", "PPO valve": "PPO", "Orifice": "orifice"}
_KIND_LABEL = {"dummy": "Dummy", "IPO": "IPO valve", "PPO": "PPO valve", "orifice": "Orifice"}

COLORS = {"tubing": "#1f77b4", "casing": "#d95f02", "unload": "#7f7f7f", "design": "#9467bd", "gas": "#2ca02c",
          "closed": "#9a9a9a", "open": "#2ca02c", "level": "#8c564b"}


# ---------------------------------------------------------------------------------------------
# the pressure lines
# ---------------------------------------------------------------------------------------------
def _unique_increasing(x, y):
    """Drop repeated x values (flat parts of a survey) so that interpolation against x works."""
    xs, ys = [x[0]], [y[0]]
    for a, b in zip(x[1:], y[1:]):
        if a > xs[-1] + 1e-9:
            xs.append(a)
            ys.append(b)
    return xs, ys


def design_context(case, g):
    """Everything the engine needs from the page's case: well, fluid and the flowing pressure and
    temperature against depth at the design rate with gas injected at g['md_inj'].  Oil wells only."""
    if case["fluid_type"] != "oil":
        raise ValueError("Gas lift design is for oil and water wells. Choose Oil & Water in the sidebar.")
    s = case["solve"]
    well = s["well"]
    # multilayer well: the water cut and GOR of the commingled layers at the design rate
    fluid = fluid_at_rate(s["fluid"], s["ipr_function"], s["p_res"], s["ipr_inputs"], g["rate"])
    perf_md = well.md[-1]
    if not 0.0 < g["md_inj"] < perf_md:
        raise ValueError(f"The injection depth must be between 0 and the perforations ({perf_md:,.0f} ft MD).")
    if g["md_max"] > perf_md:
        raise ValueError(f"The deepest valve depth cannot be below the perforations ({perf_md:,.0f} ft MD).")
    if g["md_inj"] > g["md_max"]:
        raise ValueError("The wanted injection depth is deeper than the deepest valve depth.")
    if g["rate"] <= 0 or g["gas_rate"] < 0:
        raise ValueError("The design liquid rate must be > 0 and the injection gas rate cannot be negative.")
    if g["p_ko"] < g["p_op"]:
        raise ValueError("The kick-off pressure cannot be lower than the operating injection pressure.")
    fluid_d = dataclasses.replace(fluid, injection_gas_rate=g["gas_rate"], injection_md=g["md_inj"],
                                  injection_gas_sg=g["gas_sg"])
    p_wh_psia = g["p_wh"] + PSIA
    tr = pressure_traverse(well, fluid_d, g["rate"], p_wh_psia, s["correlation"], s["max_step_ft"],
                           s["gravity_mult"], s["friction_mult"])
    tvd_u, p_u = _unique_increasing(tr["tvd"], [p - PSIA for p in tr["p"]])
    _, t_u = _unique_increasing(tr["tvd"], tr["T"])
    md_tvd_x, md_tvd_y = _unique_increasing(well.tvd, well.md)

    tvd_of = lambda md: float(np.interp(md, well.md, well.tvd))
    md_of = lambda tvd: float(np.interp(tvd, md_tvd_x, md_tvd_y))
    p_flow = lambda tvd: float(np.interp(tvd, tvd_u, p_u))
    t_flow = lambda tvd: float(np.interp(tvd, tvd_u, t_u))
    t_surface = well.ambient_table[0][1]
    gas_p = gv.column_gas(g["gas_sg"], t_surface, t_flow)
    tubing_id = well.tubing[-1][2] if well.tubing else 2.992
    for sec in well.tubing:                                      # the tubing at the depth of injection
        if sec[0] <= g["md_inj"] <= sec[1]:
            tubing_id = sec[2]
    cap = lambda d_in: math.pi / 4.0 * d_in ** 2 / 144.0 / 5.615  # bbl/ft
    ann = math.pi / 4.0 * (g["casing_id"] ** 2 - g["tubing_od"] ** 2) / 144.0 / 5.615
    if ann <= 0:
        raise ValueError("The casing ID must be larger than the tubing OD.")
    return {"well": well, "fluid": fluid_d, "traverse": tr, "tvd_of": tvd_of, "md_of": md_of, "p_flow": p_flow,
            "t_flow": t_flow, "gas_p": gas_p, "annulus_cap": ann, "tubing_cap": cap(tubing_id),
            "tvd_inj": tvd_of(g["md_inj"]), "tvd_max": tvd_of(g["md_max"]), "tvd_bottom": tvd_of(perf_md),
            "sfl_tvd": tvd_of(g["sfl_md"]) if g["sfl_md"] > 0 else 0.0}


# ---------------------------------------------------------------------------------------------
# design and check
# ---------------------------------------------------------------------------------------------
def run_design(case, g, method):
    """Design a new string.  method: 'ipo_api', 'ipo_optiflow' or 'ppo'."""
    ctx = design_context(case, g)
    res = gv.design_string(
        method, tvd_of=ctx["tvd_of"], md_of=ctx["md_of"], p_ko=g["p_ko"], p_op=g["p_op"], p_wh=g["p_wh"],
        g_unload=g["g_unload"], gas_p=ctx["gas_p"], p_flow=ctx["p_flow"], t_flow=ctx["t_flow"],
        tvd_inj=ctx["tvd_inj"], tvd_max=ctx["tvd_max"], od=g["od"], port=g["port"],
        min_spacing_md=g["min_spacing"], dp_valve=g["dp_valve"], drop_mode=g["drop_mode"],
        drop_fixed=g["drop_fixed"], sfl_tvd=ctx["sfl_tvd"], dome_method=g["dome_method"],
        gas_rate_mscfd=g["gas_rate"] or None, gas_sg=g["gas_sg"], operating=g["operating"],
        p_tub_first=lambda d: gv.first_valve_tubing_pressure(d, g["p_wh"], g["g_unload"], ctx["sfl_tvd"],
                                                             ctx["annulus_cap"], ctx["tubing_cap"]))
    # the design as a string of valves, to be checked in the same way as an existing one
    valves = []
    for v in res["valves"]:
        w = dict(v)
        if v["kind"] in ("IPO", "PPO"):     # rebuilt from the test rack pressure, as an existing valve would be
            w.update(gv.make_valve(v["n"], v["md"], v["tvd"], v["kind"], v["T"], v["od"], v["port"], v["tro"],
                                   g["dome_method"]))
        valves.append(w)
    check = check_valves(valves, ctx, g, target_tvd=valves[-1]["tvd"] if res["reached"] else None,
                         p_ko=g["p_ko"], surface_drop=res["pressure_drop"] if method == "ipo_api" else 0.0)
    return {"design": res, "ctx": ctx, "valves": valves, "check": check, "method": method}


def wanted_depth(ctx, g):
    """Depth (TVD) the existing string should reach: the wanted injection depth, less the minimum valve spacing
    (a valve closer to it than that counts as being at it)."""
    return ctx["tvd_inj"] - 0.9 * g["min_spacing"]


def check_valves(valves, ctx, g, target_tvd=None, p_ko=None, surface_drop=None):
    return gv.check_string(
        valves, p_ko=g["p_ko"] if p_ko is None else p_ko, p_op=g["p_op"], p_wh=g["p_wh"], g_unload=g["g_unload"],
        gas_p=ctx["gas_p"], p_flow=ctx["p_flow"], sfl_tvd=ctx["sfl_tvd"], annulus_cap=ctx["annulus_cap"],
        tubing_cap=ctx["tubing_cap"], dp_valve=g["dp_valve"], gas_rate_mscfd=g["gas_rate"] or None,
        gas_sg=g["gas_sg"], target_tvd=target_tvd, surface_drop=g["surface_drop"] if surface_drop is None else surface_drop)


def _num(x, default=0.0):
    """A number from a table cell; blank (None / NaN) gives the default."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(x) else x


def valves_from_table(rows, ctx, g):
    """Valves of an existing string from the rows of the page's table.
    Each row: MD (ft), Kind (one of CHECK_KINDS), Valve OD, Port (in), TRO (psig, test rack opening at 60 degF)."""
    valves = []
    last_md = -1.0
    rows = [r for r in rows if _num(r.get("MD (ft)"), None) is not None]      # blank rows are ignored
    for n, row in enumerate(rows, 1):
        md = _num(row["MD (ft)"])
        if md <= last_md:
            raise ValueError(f"Mandrel {n}: the measured depths must increase down the table.")
        if md > ctx["well"].md[-1]:
            raise ValueError(f"Mandrel {n} ({md:,.0f} ft) is below the perforations.")
        last_md = md
        kind = _KIND_KEY.get(row.get("Kind"), "dummy")
        od = row.get("Valve OD") if row.get("Valve OD") in gv.VALVE_CATALOGUE else "1 in OD"
        port = _num(row.get("Port (in)"), 0.1875) or 0.1875
        tro = _num(row.get("TRO (psig)"))
        tvd = ctx["tvd_of"](md)
        valves.append(gv.make_valve(n, md, tvd, kind, ctx["t_flow"](tvd), od, port, tro if tro > 0 else None,
                                    g["dome_method"]))
    if not [v for v in valves if v["kind"] != "dummy"]:
        raise ValueError("Every mandrel is a dummy: there is no valve to check.")
    return valves


def table_from_valves(valves):
    """Rows for the page's table from a list of valves (a design, for example)."""
    rows = []
    for v in valves:
        rows.append({"MD (ft)": round(v["md"], 0), "Kind": _KIND_LABEL[v["kind"]],
                     "Valve OD": v.get("od") or "1 in OD", "Port (in)": float(v.get("port") or 0.1875),
                     "TRO (psig)": round(v.get("tro", 0.0) or 0.0, 0)})
    return rows


def design_table(valves):
    """Setting table of a design for display: a list of dictionaries."""
    rows = []
    for v in valves:
        row = {"No.": v["n"], "MD (ft)": round(v["md"]), "TVD (ft)": round(v["tvd"]),
               "Valve": ("Operating " if v.get("operating") else "") + _KIND_LABEL[v["kind"]],
               "Port (in)": gv.port_label(v["port"]) if v.get("port") else "",
               "R": round(v["R"], 3) if v["R"] else "", "Temp (degF)": round(v["T"]),
               "Opening surface p (psig)": round(v.get("p_surface_open", 0.0)),
               "Injection p at depth (psig)": round(v.get("p_inj", 0.0)),
               "Tubing p (psig)": round(v.get("p_tub", 0.0))}
        if v["kind"] in ("IPO", "PPO"):
            row.update({"Dome p at depth (psig)": round(v["pd"]), "Charge at 60 degF (psig)": round(v["pd60"]),
                        "TRO (psig)": round(v["tro"])})
        rows.append(row)
    return rows


def check_table(check):
    """The stages of a check for display."""
    rows = []
    for s in check["stages"]:
        row = {"Mandrel": s["n"], "MD (ft)": round(s["md"]), "Valve": _KIND_LABEL[s["kind"]],
               "Tubing p when uncovered (psig)": round(s["p_tub"]),
               "Surface p available (psig)": round(s["p_surface"]),
               "Surface p needed to open (psig)": round(s["p_surface_needed"]) if "p_surface_needed" in s else "",
               "Opens": "yes" if s["opens"] else "NO"}
        if "closes_upper" in s:
            row["Upper valve closes"] = "yes" if s["closes_upper"] else "NO"
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------------------------
def _axes(title=None):
    fig = Figure(figsize=(7.2, 8.0))
    ax = fig.add_axes([0.11, 0.20, 0.86, 0.72])
    ax.grid(alpha=0.3)
    ax.set_xlabel("Pressure (psig)")
    ax.set_ylabel("True vertical depth (ft)")
    return fig, ax


def make_design_figure(run, g):
    """Pressure-depth chart of a design (like Fig. 28 of API RP 11V6): flowing tubing pressure, unloading
    gradient, casing pressure, design tubing pressure line and the valves."""
    ctx, valves, des = run["ctx"], run["valves"], run["design"]
    fig, ax = _axes()
    bottom = ctx["tvd_bottom"]
    depths = np.linspace(0.0, bottom, 60)
    top_valve = valves[0]
    ax.plot([ctx["p_flow"](d) for d in depths if d <= ctx["tvd_inj"]], [d for d in depths if d <= ctx["tvd_inj"]],
            color=COLORS["tubing"], lw=2, label="Flowing tubing pressure (design rate)")
    ax.plot([g["p_wh"] + g["g_unload"] * d for d in depths], depths, color=COLORS["unload"], lw=1.5, ls="--",
            label="Unloading gradient from the wellhead")
    ax.plot([ctx["gas_p"](d, g["p_ko"]) for d in depths], depths, color=COLORS["casing"], lw=1.6,
            label=f"Casing pressure, kick-off ({g['p_ko']:,.0f} psig)")
    ax.plot([ctx["gas_p"](d, g["p_op"]) for d in depths], depths, color=COLORS["casing"], lw=1.6, ls=":",
            label=f"Casing pressure, operating ({g['p_op']:,.0f} psig)")
    if run["method"] in ("ipo_optiflow", "ppo") and des["a"] is not None:
        line, _ = gv.design_tubing_pressure(g["p_wh"], g["p_op"], ctx["p_flow"](ctx["tvd_inj"]), ctx["tvd_inj"])
        dd = [d for d in depths if d <= ctx["tvd_inj"]]
        ax.plot([line(d) for d in dd], dd, color=COLORS["design"], lw=1.8, ls="-.", label="Design tubing pressure line")
    if ctx["sfl_tvd"] > 0:
        ax.axhline(ctx["sfl_tvd"], color=COLORS["level"], lw=1.2, ls=(0, (4, 3)))
        ax.text(0.99, ctx["sfl_tvd"], "static liquid level", transform=ax.get_yaxis_transform(), ha="right",
                va="bottom", fontsize=8, color=COLORS["level"])
    for v in valves:
        ax.plot([v["p_inj"]], [v["tvd"]], "s", color=COLORS["gas"] if not v.get("operating") else "black", ms=8, zorder=5)
        ax.plot([v["p_tub"]], [v["tvd"]], "o", color=COLORS["tubing"], ms=5, zorder=5)
        ax.annotate(f"{v['n']}", (v["p_inj"], v["tvd"]), textcoords="offset points", xytext=(8, -3), fontsize=9,
                    fontweight="bold")
    ax.plot([], [], "s", color=COLORS["gas"], label="Valve (injection pressure at depth)")
    ax.plot([], [], "s", color="black", label="Operating valve")
    ax.plot([], [], "o", color=COLORS["tubing"], label="Tubing pressure used for the setting")
    deepest = max(v["tvd"] for v in valves)
    ax.set_ylim(min(bottom, max(1.15 * deepest, deepest + 600.0)), 0)
    ax.set_xlim(0, 1.2 * max(ctx["gas_p"](deepest, g["p_ko"]), ctx["gas_p"](deepest, g["p_op"])))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=2, fontsize=8, frameon=False)
    fig.text(0.11, 0.95, "Gas lift design: " + gv.DESIGN_METHODS[run["method"]], fontsize=11, fontweight="bold")
    return fig


def make_frame_figure(frame, valves, ctx, p_max, y_max):
    """One picture of the unloading animation."""
    fig, ax = _axes()
    ax.plot(frame["p_tubing"], frame["depth"], color=COLORS["tubing"], lw=2.2, label="Tubing")
    ax.plot(frame["p_casing"], frame["depth"], color=COLORS["casing"], lw=2.2, label="Annulus (casing)")
    lev = frame["level_annulus"]
    ax.axhline(lev, color=COLORS["level"], lw=1.3, ls=(0, (4, 3)))
    ax.text(0.99, lev, "annulus liquid level", transform=ax.get_yaxis_transform(), ha="right", va="bottom",
            fontsize=8, color=COLORS["level"])
    for v in valves:
        if v["kind"] == "dummy":
            continue
        inj = frame["valve_state"].get(v["n"]) == "injecting"
        ax.plot([p_max * 0.02], [v["tvd"]], "s", color=COLORS["open"] if inj else COLORS["closed"], ms=10, zorder=5)
        ax.annotate(f"{v['n']}  {'injecting' if inj else 'closed'}", (p_max * 0.02, v["tvd"]),
                    textcoords="offset points", xytext=(10, -3), fontsize=8,
                    color=COLORS["open"] if inj else "#666666",
                    bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.8))
    ax.set_xlim(0, p_max)
    ax.set_ylim(y_max, 0)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=2, fontsize=9, frameon=False)
    fig.text(0.11, 0.955, frame["title"], fontsize=11, fontweight="bold")
    fig.text(0.11, 0.93, f"Surface casing pressure {frame['p_surface']:,.0f} psig   |   about {frame['hours']:.1f} h "
                          "after kick-off (rough estimate)", fontsize=8.5, color="#555555")
    return fig


def frames_for(run_or_check, valves, ctx, g, check):
    """Frames of the unloading for a list of valves and its check result."""
    return gv.unloading_frames(
        valves, check, p_ko=g["p_ko"], p_op=g["p_op"], p_wh=g["p_wh"], g_unload=g["g_unload"], gas_p=ctx["gas_p"],
        p_flow=ctx["p_flow"], sfl_tvd=ctx["sfl_tvd"], tvd_bottom=ctx["tvd_bottom"],
        annulus_cap=ctx["annulus_cap"], tubing_cap=ctx["tubing_cap"], md_of=ctx["md_of"],
        gas_rate_mscfd=g["gas_rate"] or None, gas_sg=g["gas_sg"])


def frame_limits(valves, ctx, g):
    """(highest pressure, deepest depth) shown in every picture of the animation."""
    deepest = max(v["tvd"] for v in valves if v["kind"] != "dummy")
    y_max = min(ctx["tvd_bottom"], max(1.15 * deepest, deepest + 600.0))
    p_max = 1.25 * max(ctx["gas_p"](y_max, g["p_ko"]), ctx["p_flow"](deepest) + g["g_unload"] * (y_max - deepest))
    return p_max, y_max
