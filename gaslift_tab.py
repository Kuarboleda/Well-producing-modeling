"""
gaslift_tab.py - the page of the "Gas Lift Design" tab (Streamlit code only; the calculations are in
gaslift_design.py and gaslift_valves.py).

Three jobs, chosen at the top of the tab:
    1. check the gas lift mandrels and valves that are already in the well (can it kick off? can it unload?)
    2. design a string of IPO (injection pressure operated) nitrogen charged valves     [API RP 11V6]
    3. design a string of PPO (production pressure operated) nitrogen charged valves    [design tubing pressure line]
Each one can show an optional step-by-step animation of the unloading.

All inputs of this tab live in this tab (not in the sidebar).  Pressures here are psig.
"""
import io
import time

import gaslift_design as gd
import gaslift_valves as gv

MODES = ["Check the valves already in the well", "Design IPO valves (nitrogen charged)",
         "Design PPO valves (nitrogen charged)"]
PSIA = gv.ATM


def _draw(container, fig):
    """Show a figure at the size it was built (same idea as show_figure on the main page)."""
    picture = io.BytesIO()
    fig.savefig(picture, format="png", dpi=150)
    try:
        container.image(picture, width="stretch")
    except Exception:
        container.image(picture, use_container_width=True)


def _default_table(case, g):
    """First rows of the mandrel table: the valves of an IPO design for the current inputs (so the check
    starts from something that works), or four blank-ish rows if a design cannot be made."""
    try:
        run = gd.run_design(case, g, "ipo_api")
        rows = gd.table_from_valves(run["valves"])
        for r in rows:
            r["TRO (psig)"] = float(r["TRO (psig)"])
        return rows
    except (ValueError, RuntimeError):
        return [{"MD (ft)": md, "Kind": "Dummy", "Valve OD": "1 in OD", "Port (in)": 0.1875, "TRO (psig)": 0.0}
                for md in (2000.0, 3500.0, 5000.0, 6500.0)]


def render(st, pd, case, out, inp, show_figure, number):
    """Draw the whole tab.  st = streamlit, pd = pandas, case/out = results of the main calculation,
    inp = the sidebar inputs, show_figure and number = the page's helper functions."""
    st.subheader("Gas Lift Design")
    if case["fluid_type"] != "oil":
        st.info("Gas lift design is for oil and water wells. Choose **Oil & Water** under Fluid in the sidebar and "
                "press Calculate.")
        return
    well = case["solve"]["well"]
    perf_md = float(well.md[-1])
    sidebar_gl = case.get("gas_lift")

    mode = st.radio("What would you like to do?", MODES, horizontal=True)

    # ------------------------------------------------------------------ inputs
    q_op = out["result"]["q"] if out["result"]["found"] else 500.0
    st.markdown("**Well and gas supply**")
    c1, c2, c3 = st.columns(3)
    with c1:
        rate = number("Design liquid rate (STB/d)", 10, 100000, round(q_op, -1) or 500.0, 50, "%.0f", key="gld_rate")
        gas_rate = number("Injection gas rate at that rate (Mscf/d)", 0, 1e6,
                          sidebar_gl["rate"] if sidebar_gl else 500.0, 50, "%.0f", key="gld_gas_rate")
    with c2:
        md_inj = number("Wanted depth of gas injection (ft MD)", 100, perf_md, min(
            sidebar_gl["md"] if sidebar_gl else 0.75 * perf_md, perf_md - 10.0), 100, "%.0f", key="gld_md_inj")
        md_max = number("Deepest depth a valve may be run to (ft MD)", 100, perf_md, perf_md - 100.0, 100, "%.0f",
                        key="gld_md_max")
    with c3:
        gas_sg = number("Injection gas gravity (air = 1)", 0.55, 1.5, sidebar_gl["sg"] if sidebar_gl else 0.65, 0.01,
                        "%.3f", key="gld_gas_sg")
        p_wh = number("Wellhead pressure, unloading and producing (psig)", 0, 5000,
                      max(inp["p_wh"] - PSIA, 0.0), 10, "%.0f", key="gld_p_wh")
    st.markdown("**Injection pressure and the annulus**")
    c1, c2, c3 = st.columns(3)
    with c1:
        p_ko = number("Kick-off pressure at the surface (psig)", 50, 10000,
                      max((sidebar_gl["p_inj"] - PSIA) if sidebar_gl and sidebar_gl.get("p_inj") else 1200.0, 50.0), 50,
                      "%.0f", key="gld_p_ko")
        p_op = number("Operating injection pressure at the surface (psig)", 50, 10000, 1100.0, 50, "%.0f", key="gld_p_op")
    with c2:
        sfl_md = number("Static liquid level in the annulus (ft MD, 0 = full to surface)", 0, perf_md, 0.0, 100,
                        "%.0f", key="gld_sfl")
        g_unload = number("Load (kill) fluid gradient (psi/ft)", 0.2, 0.6, 0.465, 0.005, "%.3f", key="gld_gu")
    with c3:
        casing_id = number("Casing inner diameter (in)", 2.0, 20.0, 6.276, 0.1, "%.3f", key="gld_csg")
        tubing_od = number("Tubing outer diameter (in)", 1.0, 10.0, 2.875, 0.125, "%.3f", key="gld_tod")
    if p_ko < p_op:
        st.warning("The kick-off pressure is lower than the operating pressure; the kick-off pressure is the highest "
                   "pressure the compressor can give, so it should not be lower.")

    st.markdown("**Valves and design rules**")
    c1, c2, c3 = st.columns(3)
    with c1:
        od = st.selectbox("Valve OD", list(gv.VALVE_CATALOGUE), key="gld_od")
        ports = gv.valve_ports(od)
        port = st.selectbox("Port size of the unloading valves", ports, index=min(1, len(ports) - 1),
                            format_func=gv.port_label)
        st.caption(f"R = Av/Ab = {gv.valve_R(od, port):.3f}; production pressure effect factor "
                   f"{gv.ppef(gv.valve_R(od, port)):.3f}")
    with c2:
        dome_method = st.selectbox("Nitrogen dome pressure correction", list(gv.DOME_METHODS),
                                   format_func=lambda k: gv.DOME_METHODS[k], key="gld_dome")
        min_spacing = number("Smallest spacing between valves (ft MD)", 0, 5000, 250.0, 25, "%.0f", key="gld_min_sp")
    with c3:
        dp_valve = number("Pressure difference to let gas in, casing over tubing (psi)", 0, 500, 20.0, 5, "%.0f",
                          key="gld_dp")
        operating = "orifice"
        drop_mode, drop_fixed, surface_drop = "fixed", 25.0, 20.0
        if mode == MODES[0]:
            surface_drop = number("Surface pressure lowered per valve passed during unloading (psi)", 0, 500, 20.0, 5,
                                  "%.0f", key="gld_drop_check")
        else:
            operating = st.selectbox("Bottom (operating) valve", ["orifice", "valve"],
                                     format_func=lambda k: "Orifice valve" if k == "orifice" else "Same type as the others")
            if mode == MODES[1]:
                drop_mode = st.selectbox(
                    "Pressure drop per valve", ["fixed", "min", "max"],
                    format_func=lambda k: {"fixed": "Fixed value", "min": "API minimum: PPEF x 100 + safety factor",
                                           "max": "API maximum: 20 + PPEF x 200"}[k], key="gld_drop_mode")
                if drop_mode == "fixed":
                    drop_fixed = number("Pressure drop per valve (psi)", 0, 200, 25.0, 5, "%.0f", key="gld_drop")

    g = dict(rate=rate, gas_rate=gas_rate, md_inj=md_inj, md_max=md_max, gas_sg=gas_sg, p_ko=p_ko, p_op=p_op, p_wh=p_wh,
             g_unload=g_unload, sfl_md=sfl_md, casing_id=casing_id, tubing_od=tubing_od, od=od, port=port,
             dome_method=dome_method, min_spacing=min_spacing, dp_valve=dp_valve, drop_mode=drop_mode,
             drop_fixed=drop_fixed, operating=operating, surface_drop=surface_drop)

    # ------------------------------------------------------------------ mandrel table (check only)
    table = None
    if mode == MODES[0]:
        st.markdown("**Mandrels and valves in the well**")
        st.caption("One row per mandrel, top first. Kind: Dummy (no valve), IPO or PPO valve (give OD, port and the "
                   "test rack opening pressure TRO at 60 degF) or Orifice (give the port). The starting rows are the "
                   "valves of an IPO design for the inputs above: replace them with the real completion.")
        if "gld_start" not in st.session_state:
            st.session_state["gld_start"] = pd.DataFrame(_default_table(case, g))
        if st.button("Fill the table with an IPO design for the inputs above"):
            st.session_state["gld_start"] = pd.DataFrame(_default_table(case, g))
            st.session_state.pop("gld_table", None)
        cfg = getattr(st, "column_config", None)
        kwargs = {}
        if cfg is not None:
            kwargs["column_config"] = {
                "Kind": cfg.SelectboxColumn("Kind", options=gd.CHECK_KINDS),
                "Valve OD": cfg.SelectboxColumn("Valve OD", options=list(gv.VALVE_CATALOGUE)),
                "Port (in)": cfg.NumberColumn("Port (in)", format="%.4f"),
                "TRO (psig)": cfg.NumberColumn("TRO (psig)", format="%.0f"),
            }
        table = st.data_editor(st.session_state["gld_start"], num_rows="dynamic", hide_index=True, key="gld_table",
                               use_container_width=True, **kwargs)

    label = {MODES[0]: "Check the valves", MODES[1]: "Design the IPO valves", MODES[2]: "Design the PPO valves"}[mode]
    if st.button(label, type="primary"):
        st.session_state.pop("gld_result", None)
        try:
            with st.spinner("Calculating..."):
                if mode == MODES[0]:
                    ctx = gd.design_context(case, g)
                    valves = gd.valves_from_table(table.to_dict("records"), ctx, g)
                    check = gd.check_valves(valves, ctx, g, target_tvd=gd.wanted_depth(ctx, g))
                    run = {"ctx": ctx, "valves": valves, "check": check, "design": None, "method": None}
                else:
                    run = gd.run_design(case, g, "ipo_api" if mode == MODES[1] else "ppo")
                frames = gd.frames_for(run, run["valves"], run["ctx"], g, run["check"])
            st.session_state["gld_result"] = {"mode": mode, "run": run, "frames": frames, "g": g}
        except (ValueError, RuntimeError) as error:
            st.error(f"Cannot calculate: {error}")

    res = st.session_state.get("gld_result")
    if not res:
        st.info("Fill in the inputs above and press the button. Pressures are psig; depths are measured depth (MD) "
                "unless TVD is written.")
        return
    if res["mode"] != mode:
        st.caption("The results below are for the other job chosen earlier; press the button to update them.")

    # ------------------------------------------------------------------ results
    run, frames, g_res = res["run"], res["frames"], res["g"]
    check = run["check"]
    if check["ok"]:
        st.success(check["verdict"])
    elif check["reached"] is None:
        st.error(check["verdict"])
    else:
        st.warning(check["verdict"])
    if run["design"] and run["design"]["notes"]:
        for note in run["design"]["notes"]:
            st.warning(note)
    if check["issues"]:
        st.markdown("**Points to look at**")
        for issue in check["issues"]:
            st.caption("- " + issue)
    op = check["operating"]
    if op:
        extra = ""
        if "capacity" in op:
            extra = (f"; the port passes about {op['capacity']:,.0f} Mscf/d at these pressures "
                     f"({g_res['gas_rate']:,.0f} Mscf/d wanted)")
        st.caption(f"Normal operation from valve {check['reached']['n']} at {op['md']:,.0f} ft MD: casing "
                   f"{op['p_casing']:,.0f} psig, tubing {op['p_tubing']:,.0f} psig, "
                   f"{op['differential']:,.0f} psi across the valve{extra}.")

    left, right = st.columns(2)
    with left:
        if run["design"]:
            show_figure(gd.make_design_figure(run, g_res))
        else:
            p_max, y_max = gd.frame_limits(run["valves"], run["ctx"], g_res)
            show_figure(gd.make_frame_figure(frames[-1], run["valves"], run["ctx"], p_max, y_max))
    with right:
        if run["design"]:
            st.markdown("**Valve settings**")
            st.dataframe(pd.DataFrame(gd.design_table(run["valves"])), hide_index=True)
            st.caption("TRO = test rack opening pressure at 60 degF (what the workshop sets). "
                       "Dome p = nitrogen pressure at the valve temperature. Settings are by the "
                       f"{gv.DOME_METHODS[g_res['dome_method']]} method.")
        st.markdown("**Unloading, valve by valve**")
        if check["stages"]:
            st.dataframe(pd.DataFrame(gd.check_table(check)), hide_index=True)

    # ------------------------------------------------------------------ animation
    with st.expander("Unloading animation (optional)"):
        st.caption("A step-by-step picture of the kick-off and unloading with the valves above. Each step is a "
                   "pressure snapshot (quasi-steady), not a full transient simulation; the times are rough "
                   "estimates from the gas that passes the valves.")
        p_max, y_max = gd.frame_limits(run["valves"], run["ctx"], g_res)
        n = len(frames)
        step = 1
        if n > 1:
            step = st.slider("Step", 1, n, 1, key="gld_step")
        holder = st.empty()
        if st.button("Play the animation"):
            for k, frame in enumerate(frames):
                _draw(holder, gd.make_frame_figure(frame, run["valves"], run["ctx"], p_max, y_max))
                time.sleep(0.6)
            step = n
        else:
            _draw(holder, gd.make_frame_figure(frames[step - 1], run["valves"], run["ctx"], p_max, y_max))
        st.caption(frames[step - 1]["text"])
