// @ts-check
/**
 * app.js - the page.  It reads the boxes, hands the numbers to the engine, and draws the answers.
 *
 * No physics lives here.  Everything is calculated by pvt.js, ipr.js, vlp.js, well.js and nodal.js,
 * which are translations of the Python engine and are held against it by tools/crosscheck.mjs.
 * This file only moves numbers between the screen and those files, and asks units.js to convert
 * between what the user types and what the engine calculates with.
 *
 * The screen works in gauge pressure and in whichever unit system is chosen; the engine always works
 * in absolute pressure (psia) and oilfield units, exactly like the Python.
 */

import * as pvt from "./pvt.js";
import * as ipr from "./ipr.js";
import * as vlp from "./vlp.js";
import * as wellmod from "./well.js";
import * as nodal from "./nodal.js";
import * as units from "./units.js";

const CURVE_POINTS = 41;          // points along the inflow curve on its own
const NODAL_POINTS = 25;          // points along each curve when the VLP is calculated too

// ---------------------------------------------------------------------
// Small helpers for reading the form
// ---------------------------------------------------------------------

/** The element with this id. @param {string} id */
function el(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`The page has no element called ${id}.`);
  return /** @type {HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | HTMLButtonElement} */ (node);
}

/** The number in a box, as the user typed it (screen units). @param {string} id */
function num(id) {
  const value = Number(/** @type {HTMLInputElement} */ (el(id)).value);
  return Number.isFinite(value) ? value : 0;
}

/** The chosen value of a drop-down. @param {string} id */
function pick(id) {
  return /** @type {HTMLSelectElement} */ (el(id)).value;
}

/** Whether a tick box is ticked. @param {string} id */
function ticked(id) {
  return /** @type {HTMLInputElement} */ (el(id)).checked;
}

/** Show or hide a block. @param {string} id @param {boolean} on */
function toggle(id, on) {
  const node = document.getElementById(id);
  if (node) node.classList.toggle("hidden", !on);
}

/**
 * What each box MEASURES.  This one table drives three things: the unit shown on its label, the
 * conversion into engine units, and the conversion of the number already typed when the user
 * switches unit system.  A box that is a drop-down, a tick box, a piece of text, or a pure number
 * with no unit at all (skin, specific gravity, a percentage, the exponent n) is listed as null so
 * that it is visibly accounted for rather than merely absent.
 * @type {Record<string, import("./units.js").Quantity | null>}
 */
const QUANTITY_OF = {
  // reservoir and IPR
  fluid_type: null, oil_ipr: null, gas_ipr: null, oil_regime: null,
  p_res: "pressure", t_res: "temperature",
  pi: "pi",
  vogel_q: "liquidRate", vogel_pwf: "pressure",
  fet_q1: "liquidRate", fet_pwf1: "pressure", fet_q2: "liquidRate", fet_pwf2: "pressure",
  oil_k: "permeability", oil_h: "length", oil_bo: "fvf", oil_mu: "viscosity",
  oil_re: "length", oil_rw: "length", oil_skin: null,
  oil_phi: "fraction", oil_ct: "compressibility", oil_time: "time",
  gas_k: "permeability", gas_h: "length", gas_re: "length", gas_rw: "length",
  gas_skin: null, gas_beta: "inverseLength",
  bp_c: null,                      // handled on its own: see switchSystem
  bp_n: null,
  // fluid
  api: null, gas_sg: null, rsb: "gor", oil_gor: "gor", water_cut: null, water_sg: null,
  pb_meas: "pressure", pvt_method: null, visc_method: null,
  gas_sg_g: null, water_sg_g: null, cgr: null, cond_api: null, wgr: null,
  y_h2s: null, y_co2: null, gas_visc: null,
  // equipment
  survey_mode: null, depth: "length", survey_text: null,
  tubing_id: null, roughness_in: null,          // always inches: the tubing is sized in inches worldwide
  p_wh: "pressure", correlation: null,
  t_amb_surface: "temperature", u_surface: null,
  perf_ambient_is_reservoir: null, t_amb_perf: "temperature", u_perf: null,
  // gas lift
  lift: null, gl_rate: "gasRate", gl_md: "length", gl_sg: null, gl_p_inj: "pressure",
  // matching
  gravity_mult: null, friction_mult: null, match_pwf: "pressure",
  match_q: null,                   // liquid or gas rate depending on the fluid: see rateQuantity()
  match_fit: null,
};

/** Every box on the page, in the order they are saved. */
const ALL_IDS = Object.keys(QUANTITY_OF);

/** Which rate unit the well produces, so one box can serve an oil well and a gas well. */
function rateQuantity() {
  return pick("fluid_type") === "oil" ? "liquidRate" : "gasRate";
}

/** The quantity a box measures, with the rate boxes resolved. @param {string} id */
function quantityOf(id) {
  if (id === "match_q") return rateQuantity();
  return QUANTITY_OF[id];
}

/** Read a box and convert it into the engine's units. @param {string} id */
function eng(id) {
  const quantity = quantityOf(id);
  return quantity === null ? num(id) : units.toEngine(quantity, num(id));
}

/**
 * The number the user actually typed into each box, together with the system it was typed in.
 *
 * Why this is kept: switching system rounds the number on screen to something readable (3,000 psig
 * becomes 206.843 barg, not 206.84277941...).  Switching back from that rounded number would give
 * 2,999.996 psig, and flipping back and forth a few times would walk the well away from what was
 * entered.  So the original is remembered, and returning to the system a number was typed in puts
 * that exact number back.  Any edit replaces the memory.
 * @type {Record<string, {value: number, system: import("./units.js").System}>}
 */
const TYPED = {};

/** Remember what is in a box as typed by the user, in whatever system is on screen. @param {string} id */
function noteTyped(id) {
  const node = document.getElementById(id);
  if (!node) return;
  const value = Number(/** @type {HTMLInputElement} */ (node).value);
  if (Number.isFinite(value)) TYPED[id] = { value, system: units.system() };
  else delete TYPED[id];
}

// ---------------------------------------------------------------------
// Which boxes belong to the chosen model
// ---------------------------------------------------------------------

function updateVisibility() {
  const oil = pick("fluid_type") === "oil";
  toggle("g-oil", oil);
  toggle("g-gas", !oil);
  toggle("pvt-oil", oil);
  toggle("pvt-gas", !oil);
  toggle("grp-lift", oil);            // continuous gas lift is for oil wells

  const oilModel = pick("oil_ipr");
  toggle("f-pi", oilModel === "pi");
  toggle("f-vogel", oilModel === "vogel");
  toggle("f-fet", oilModel === "fetkovich");
  toggle("f-darcy", oilModel === "darcy");
  toggle("f-transient", oilModel === "darcy" && pick("oil_regime") === "transient");

  const gasModel = pick("gas_ipr");
  toggle("f-gasrock", gasModel !== "backpressure");
  toggle("f-beta", gasModel === "jones");
  toggle("f-bp", gasModel === "backpressure");

  const vertical = pick("survey_mode") === "vertical";
  toggle("f-depth", vertical);
  toggle("f-survey", !vertical);
  toggle("f-tperf", !ticked("perf_ambient_is_reservoir"));
  toggle("f-gl", pick("lift") === "continuous");
}

/** Put the current unit names into every label that asked for one. */
function writeUnitLabels() {
  for (const node of document.querySelectorAll("[data-unit]")) {
    const quantity = /** @type {any} */ (node.getAttribute("data-unit"));
    node.textContent = `(${units.unitOf(quantity)})`;
  }
  // three labels that cannot come from the table: C carries the exponent n in its unit, beta carries
  // a note about what 0 means, and the test rate is a liquid or a gas rate depending on the fluid
  const c = document.getElementById("bp_c_unit");
  if (c) c.textContent = `(${units.backpressureCUnit()})`;
  const b = document.getElementById("beta_unit");
  if (b) b.textContent = `(${units.unitOf("inverseLength")}, 0 = estimate)`;
  const q = document.getElementById("match_q_unit");
  if (q) q.textContent = `(${units.unitOf(rateQuantity())})`;
}

/**
 * Switch unit system without changing the well.  Every number already typed is re-expressed in the
 * new system, so 3,000 psig becomes 206.844 barg and the answers stay the same.  The engine itself
 * never changes: it is always given oilfield units and absolute pressure.
 * @param {string} name
 */
function switchSystem(name) {
  const to = units.asSystem(name);
  const from = units.system();
  if (to === from) return;

  for (const id of ALL_IDS) {
    const quantity = quantityOf(id);
    if (quantity === null) continue;
    const node = /** @type {HTMLInputElement} */ (el(id));
    const value = Number(node.value);
    if (!Number.isFinite(value)) continue;
    const typed = TYPED[id] || { value, system: from };
    const converted = typed.system === to ? typed.value : units.convert(quantity, typed.value, typed.system, to);
    node.value = String(Number(converted.toFixed(units.decimalsFor(quantity, converted))));
    // the up/down arrows step in round numbers of the OLD unit, which is meaningless in the new one,
    // so remember the original and let the box take any value while it is converted
    if (!node.dataset.step0) node.dataset.step0 = node.getAttribute("step") || "any";
    node.setAttribute("step", to === "field" ? node.dataset.step0 : "any");
  }

  // C is the awkward one: its unit contains the exponent n, so it needs n to be converted
  const cBox = /** @type {HTMLInputElement} */ (el("bp_c"));
  const cValue = Number(cBox.value);
  if (Number.isFinite(cValue)) {
    const typed = TYPED.bp_c || { value: cValue, system: from };
    const c = typed.system === to ? typed.value
                                  : units.convertBackpressureC(typed.value, num("bp_n"), typed.system, to);
    cBox.value = typed.system === to ? String(c) : c.toExponential(6);
  }

  // the survey table is text, so its depths are converted line by line
  const survey = /** @type {HTMLTextAreaElement} */ (el("survey_text"));
  survey.value = survey.value.split(/\r?\n/).map((line) => {
    const parts = line.trim().split(/[\s,;]+/).filter((t) => t.length > 0);
    if (parts.length < 2 || parts.some((t) => !Number.isFinite(Number(t)))) return line;
    return parts.map((t) => {
      const v = units.convert("length", Number(t), from, to);
      return String(Number(v.toFixed(units.decimalsFor("length", v))));
    }).join(" ");
  }).join("\n");

  units.setSystem(to);
  writeUnitLabels();
  fillSensitivityChoices();
  recalculate();
}

// ---------------------------------------------------------------------
// Building the engine inputs from the form
// ---------------------------------------------------------------------

/**
 * @typedef {{fluid_type: string, well: import("./well.js").Well,
 *            fluid: vlp.OilWaterFluid | vlp.GasFluid, ipr_name: string,
 *            ipr_inputs: Record<string, any>, p_res: number, p_wh: number, correlation: string,
 *            max_step_ft: number, gravity_mult: number, friction_mult: number,
 *            rateUnit: "liquidRate"|"gasRate", perf_md: number,
 *            gas_lift: {rate: number, md: number, sg: number, p_inj: number} | null,
 *            extra: {key: string, value: string}[]}} Case
 */

/**
 * Turn the whole form into everything the solver needs, in ENGINE units (psia, oilfield).
 * This is the JavaScript of app_helpers.build_case().
 * @returns {Case}
 */
function buildCase() {
  const isOil = pick("fluid_type") === "oil";
  const p_res = eng("p_res");
  const t_res = eng("t_res");
  /** @type {{key: string, value: string}[]} */
  const extra = [];

  // ---- the well ----
  const [md, tvd] = pick("survey_mode") === "vertical"
    ? wellmod.verticalSurvey(eng("depth"))
    : surveyFromText();
  const perf_md = md[md.length - 1];
  const t_amb_perf = ticked("perf_ambient_is_reservoir") ? t_res : eng("t_amb_perf");
  const well = wellmod.makeWell({
    md, tvd, tubing: wellmod.simpleTubing(num("tubing_id"), perf_md), t_reservoir: t_res,
    roughness_in: num("roughness_in"),
    ambient_table: [[0.0, eng("t_amb_surface"), num("u_surface")],
                    [perf_md, t_amb_perf, num("u_perf")]],
  });

  const base = { well, p_wh: eng("p_wh"), correlation: pick("correlation"),
                 max_step_ft: Math.max(100.0, perf_md / 150.0),
                 gravity_mult: num("gravity_mult"), friction_mult: num("friction_mult"),
                 perf_md, extra };

  if (isOil) {
    // ---- oil and water ----
    const pb_meas = num("pb_meas") > 0 ? eng("pb_meas") : null;
    /** @type {{rate: number, md: number, sg: number, p_inj: number} | null} */
    let gas_lift = null;
    if (pick("lift") === "continuous") {
      const gl_md = eng("gl_md");
      if (!(gl_md > 0 && gl_md < perf_md)) {
        throw new Error(`The gas injection depth (${show(units.fromEngine("length", gl_md), 0)} `
          + `${units.unitOf("length")}) must be above the perforations `
          + `(${show(units.fromEngine("length", perf_md), 0)} ${units.unitOf("length")}).`);
      }
      gas_lift = { rate: eng("gl_rate"), md: gl_md, sg: num("gl_sg"), p_inj: eng("gl_p_inj") };
    }
    const fluid = new vlp.OilWaterFluid({
      api: num("api"), gas_sg: num("gas_sg"), rsb: eng("rsb"),
      water_cut: num("water_cut") / 100.0,
      gor: num("oil_gor") > 0 ? eng("oil_gor") : null,
      salinity: pvt.salinityFromSg(num("water_sg")),
      pb_meas, pvt_method: pick("pvt_method"), visc_method: pick("visc_method"),
      injection_gas_rate: gas_lift ? gas_lift.rate : 0.0,
      injection_md: gas_lift ? gas_lift.md : null,
      injection_gas_sg: gas_lift ? gas_lift.sg : null,
    });
    // The bubble point the inflow model uses comes from the PVT, with the measured value as an
    // override - exactly as the Python does it.
    const pb = pvt.oilProperties(p_res, t_res, num("api"), num("gas_sg"), eng("rsb"), pb_meas,
                                 pick("pvt_method"), pick("visc_method")).pb;
    extra.push({ key: `Bubble point (${units.unitOf("pressure")})`,
                 value: show(units.fromEngine("pressure", pb), 0) });

    const model = pick("oil_ipr");
    /** @type {Record<string, any>} */
    let ipr_inputs;
    let ipr_name;
    if (model === "pi") {
      ipr_name = "oil_pi";
      ipr_inputs = { pb, J: eng("pi") };
    } else if (model === "vogel") {
      ipr_name = "oil_vogel";
      ipr_inputs = { pb, q_test: eng("vogel_q"), pwf_test: eng("vogel_pwf") };
      const J = ipr.vogel_productivity_index(p_res, pb, ipr_inputs.q_test, ipr_inputs.pwf_test);
      extra.push({ key: `PI from the test (${units.unitOf("pi")})`,
                   value: show(units.fromEngine("pi", J), 2) });
    } else if (model === "fetkovich") {
      ipr_name = "oil_fetkovich";
      ipr_inputs = { q1: eng("fet_q1"), pwf1: eng("fet_pwf1"),
                     q2: eng("fet_q2"), pwf2: eng("fet_pwf2") };
      const [C, n] = ipr.c_and_n_from_two_tests(p_res, ipr_inputs.q1, ipr_inputs.pwf1,
                                                ipr_inputs.q2, ipr_inputs.pwf2);
      extra.push({ key: "n from the two tests", value: n.toFixed(3) });
      extra.push({ key: "C from the two tests", value: C.toExponential(3) });
    } else {
      const regime = pick("oil_regime");
      ipr_name = "oil_darcy_regime";
      ipr_inputs = { pb, k: eng("oil_k"), h: eng("oil_h"), bo: eng("oil_bo"), mu: eng("oil_mu"),
                     re: eng("oil_re"), rw: eng("oil_rw"), skin: eng("oil_skin"), regime };
      if (regime === "transient") {
        ipr_inputs.phi = eng("oil_phi");
        ipr_inputs.ct = eng("oil_ct");
        ipr_inputs.time_hours = eng("oil_time");
      }
      const J = regime === "pseudosteady"
        ? ipr.darcy_productivity_index_oil(ipr_inputs.k, ipr_inputs.h, ipr_inputs.bo, ipr_inputs.mu,
                                           ipr_inputs.re, ipr_inputs.rw, ipr_inputs.skin)
        : regime === "steady"
          ? ipr.darcy_productivity_index_oil_steady(ipr_inputs.k, ipr_inputs.h, ipr_inputs.bo,
                                                    ipr_inputs.mu, ipr_inputs.re, ipr_inputs.rw,
                                                    ipr_inputs.skin)
          : ipr.darcy_productivity_index_oil_transient(ipr_inputs.k, ipr_inputs.h, ipr_inputs.bo,
                                                       ipr_inputs.mu, ipr_inputs.phi, ipr_inputs.ct,
                                                       ipr_inputs.rw, ipr_inputs.time_hours,
                                                       ipr_inputs.skin);
      if (regime === "transient") {
        const tEnd = ipr.transient_end_time_hours(ipr_inputs.k, ipr_inputs.phi, ipr_inputs.mu,
                                                  ipr_inputs.ct, ipr_inputs.re);
        extra.push({ key: `Transient valid until (${units.unitOf("time")})`,
                     value: show(units.fromEngine("time", tEnd), 0) });
      }
      extra.push({ key: `PI from the rock (${units.unitOf("pi")})`,
                   value: show(units.fromEngine("pi", J), 3) });
    }
    return { ...base, fluid_type: "oil", fluid, ipr_name, ipr_inputs, p_res,
             rateUnit: "liquidRate", gas_lift };
  }

  // ---- dry and wet gas ----
  const dry_sg = num("gas_sg_g");
  const model = pick("gas_ipr");
  const cgr = num("cgr");
  const wgr = num("wgr");
  // a wet gas flows as its well-stream gravity, which is heavier than the separator gas
  const gas_sg = cgr > 0 ? pvt.wetGasGravity(dry_sg, cgr, num("cond_api")) : dry_sg;
  if (cgr > 0) extra.push({ key: "Well-stream gravity (air = 1)", value: gas_sg.toFixed(4) });
  const y_h2s = num("y_h2s") / 100.0;
  const y_co2 = num("y_co2") / 100.0;
  const fluid = new vlp.GasFluid({ gas_sg, cgr, cond_api: num("cond_api"), wgr,
                                   salinity: pvt.salinityFromSg(num("water_sg_g")),
                                   y_h2s, y_co2, visc_method: pick("gas_visc"), gas_sg_dry: dry_sg });

  if (model === "backpressure") {
    // C is in engine units already if the screen is in oilfield units; in metric it is converted
    // back, and that needs n
    const n = num("bp_n");
    const C = units.convertBackpressureC(num("bp_c"), n, units.system(), "field");
    return { ...base, fluid_type: "gas", fluid, ipr_name: "gas_backpressure",
             ipr_inputs: { C, n }, p_res, rateUnit: "gasRate", gas_lift: null };
  }
  // Darcy and Jones need Z and viscosity.  Exactly as the Python does it, they are evaluated at 75 %
  // of the reservoir pressure (a typical average of Pr and Pwf) and the reservoir temperature.
  const props = pvt.gasProperties(0.75 * p_res, t_res, gas_sg, y_h2s, y_co2, pick("gas_visc"));
  extra.push({ key: "Z at 0.75 Pr", value: props.z.toFixed(4) });
  extra.push({ key: `Gas viscosity (${units.unitOf("viscosity")})`,
               value: units.fromEngine("viscosity", props.mu_g).toFixed(5) });
  const common = { temp_f: t_res, k: eng("gas_k"), h: eng("gas_h"), mu: props.mu_g, z: props.z,
                   re: eng("gas_re"), rw: eng("gas_rw"), skin: eng("gas_skin") };
  if (model === "darcy") {
    return { ...base, fluid_type: "gas", fluid, ipr_name: "gas_darcy", ipr_inputs: common, p_res,
             rateUnit: "gasRate", gas_lift: null };
  }
  const beta = num("gas_beta") > 0 ? eng("gas_beta") : null;
  if (beta === null) {
    const estimated = ipr.gas_beta_firoozabadi_katz(common.k);
    extra.push({ key: `beta estimated (${units.unitOf("inverseLength")})`,
                 value: units.fromEngine("inverseLength", estimated).toExponential(3) });
  }
  return { ...base, fluid_type: "gas", fluid, ipr_name: "gas_jones",
           ipr_inputs: { ...common, gas_sg, beta, h_perf: null }, p_res,
           rateUnit: "gasRate", gas_lift: null };
}

/** The survey table as two lists of depths, converted into feet. @returns {[number[], number[]]} */
function surveyFromText() {
  const [md, tvd] = wellmod.parseSurveyText(/** @type {HTMLTextAreaElement} */ (el("survey_text")).value);
  return [md.map((v) => units.toEngine("length", v)), tvd.map((v) => units.toEngine("length", v))];
}

// ---------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------

const show = units.show;

/** @param {string} where @param {string} html @param {string} [kind] */
function message(where, html, kind = "") {
  const node = document.getElementById(where);
  if (node) node.innerHTML = html ? `<p class="note ${kind}">${html}</p>` : "";
}

/** @param {{key: string, value: string}[]} items */
function drawResults(items) {
  const list = document.getElementById("results");
  if (!list) return;
  list.innerHTML = items
    .map((it) => `<li><span class="k">${it.key}</span><span class="v">${it.value}</span></li>`)
    .join("");
}

/** @param {string} id */
function clearChart(id) {
  const node = document.getElementById(id);
  if (!node) return;
  // @ts-ignore - Plotly is loaded from the page
  if (window.Plotly) window.Plotly.purge(node);
  node.innerHTML = "";
}

/** The look shared by every chart on the page. @param {string} xTitle @param {string} yTitle */
function layoutFor(xTitle, yTitle) {
  return {
    margin: { l: 62, r: 16, t: 10, b: 48 },
    xaxis: { title: { text: xTitle }, zeroline: false, gridcolor: "#eef2f5", rangemode: "tozero" },
    yaxis: { title: { text: yTitle }, zeroline: false, gridcolor: "#eef2f5", rangemode: "tozero" },
    showlegend: true,
    legend: { orientation: "h", y: 1.12, x: 0 },
    font: { family: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
            size: 12, color: "#16202b" },
    paper_bgcolor: "#fff",
    plot_bgcolor: "#fff",
    hovermode: "closest",
  };
}

const PLOT_CONFIG = { displayModeBar: false, responsive: true };

/** Draw a set of lines in one chart. @param {string} id @param {any[]} traces @param {any} layout */
function plot(id, traces, layout) {
  const node = document.getElementById(id);
  // @ts-ignore - Plotly is loaded from the page
  if (!node || !window.Plotly) {
    if (node) node.innerHTML = '<p class="note warn">The chart library could not be loaded, so the '
      + 'numbers are shown in the table instead.</p>';
    return;
  }
  // @ts-ignore
  window.Plotly.newPlot(node, traces, layout, PLOT_CONFIG);
}

/** The inflow curve as a table of numbers. @param {number[]} pwfShown @param {number[]} qShown
 *  @param {string} rateLabel @param {string} pressureLabel */
function drawTable(pwfShown, qShown, rateLabel, pressureLabel) {
  const table = document.getElementById("curve-table");
  if (!table) return;
  let html = `<tr><th>Pwf (${pressureLabel})</th><th>Rate (${rateLabel})</th></tr>`;
  for (let i = 0; i < pwfShown.length; i++) {
    if (pwfShown[i] < 0) continue;              // the engine's last point sits at zero ABSOLUTE
    html += `<tr><td>${show(pwfShown[i], 0)}</td><td>${show(qShown[i], 0)}</td></tr>`;
  }
  html += `<tr><td>0 (AOF)</td><td>${show(qShown[qShown.length - 1], 0)}</td></tr>`;
  table.innerHTML = html;
}

// ---------------------------------------------------------------------
// The first tab: the operating point
// ---------------------------------------------------------------------

/** @type {Case | null} */
let lastCase = null;

/**
 * The inflow curve on its own.  This runs on every keystroke, because it is fast.  The tubing side
 * waits for the Calculate button, because a traverse at 25 rates takes a few tenths of a second.
 */
function recalculate() {
  updateVisibility();
  let c;
  try {
    c = buildCase();
    lastCase = c;
  } catch (error) {
    lastCase = null;
    drawResults([]);
    clearChart("chart-nodal");
    clearChart("chart-profile");
    drawTable([], [], "", "");
    message("messages", /** @type {Error} */ (error).message, "error");
    return;
  }

  let curve;
  try {
    curve = ipr.ipr_curve(c.ipr_name, c.p_res, CURVE_POINTS, c.ipr_inputs);
  } catch (error) {
    drawResults([]);
    clearChart("chart-nodal");
    drawTable([], [], "", "");
    message("messages", /** @type {Error} */ (error).message, "error");
    return;
  }

  const pressureLabel = units.unitOf("pressure");
  const rateLabel = units.unitOf(c.rateUnit);
  const pwfShown = curve.pwf.map((p) => units.fromEngine("pressure", p));
  const qShown = curve.q.map((q) => units.fromEngine(c.rateUnit, q));
  const aof = qShown[qShown.length - 1];

  drawResults([
    { key: `AOF (${rateLabel})`, value: show(aof, 0) },
    { key: `Reservoir pressure (${pressureLabel})`,
      value: show(units.fromEngine("pressure", c.p_res), 0) },
    ...c.extra,
  ]);
  drawTable(pwfShown, qShown, rateLabel, pressureLabel);
  plot("chart-nodal", [{
    x: qShown, y: pwfShown, mode: "lines", name: "IPR",
    line: { color: "#1f77b4", width: 2.5 },
    hovertemplate: `%{x:,.0f} ${rateLabel}<br>%{y:,.0f} ${pressureLabel}<extra>IPR</extra>`,
  }], {
    ...layoutFor(`Rate (${rateLabel})`, `Flowing bottom-hole pressure (${pressureLabel})`),
    yaxis: { ...layoutFor("", "").yaxis, title: { text: `Flowing bottom-hole pressure (${pressureLabel})` },
             range: [0, Math.max(...pwfShown) * 1.02] },
  });
  clearChart("chart-profile");
  const note = document.getElementById("profile-note");
  if (note) note.textContent = "";
  const warnings = ipr.takeWarnings();
  message("messages", warnings.length
    ? warnings.join(" ")
    : "Press <b>Calculate</b> to add the tubing (VLP), the operating point and the pressure and "
      + "temperature profile.", warnings.length ? "warn" : "");
}

/** The whole nodal calculation: the VLP, the operating point and the profile. */
function calculate() {
  updateVisibility();
  const button = /** @type {HTMLButtonElement} */ (el("btn-calc"));
  button.disabled = true;
  button.textContent = "Calculating...";
  // let the browser paint the disabled button before the arithmetic blocks it
  setTimeout(() => {
    try {
      runNodal();
    } catch (error) {
      message("messages", /** @type {Error} */ (error).message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Calculate";
    }
  }, 10);
}

function runNodal() {
  const c = buildCase();
  lastCase = c;
  const pressureLabel = units.unitOf("pressure");
  const rateLabel = units.unitOf(c.rateUnit);

  const cv = nodal.curves(c.well, c.fluid, c.ipr_name, c.p_res, c.ipr_inputs, c.p_wh,
                          c.correlation, c.max_step_ft, NODAL_POINTS,
                          c.gravity_mult, c.friction_mult);
  const res = nodal.solve_well(c.well, c.fluid, c.ipr_name, c.p_res, c.ipr_inputs, c.p_wh,
                               c.correlation, c.max_step_ft, 30, c.gravity_mult, c.friction_mult);

  const toRate = (/** @type {number} */ q) => units.fromEngine(c.rateUnit, q);
  const toP = (/** @type {number} */ p) => units.fromEngine("pressure", p);

  /** @type {any[]} */
  const traces = [
    { x: cv.ipr_q.map(toRate), y: cv.ipr_pwf.map(toP), mode: "lines", name: "IPR",
      line: { color: "#1f77b4", width: 2.5 } },
    { x: cv.vlp_q.map(toRate), y: cv.vlp_pwf.map(toP), mode: "lines", name: "VLP",
      line: { color: "#d62728", width: 2.5 } },
  ];
  const items = [];
  if (res.found) {
    traces.push({ x: [toRate(/** @type {number} */ (res.q))],
                  y: [toP(/** @type {number} */ (res.pwf))],
                  mode: "markers", name: "Operating point",
                  marker: { color: "#111", size: 11, symbol: "circle" } });
    const unstable = res.crossings.filter((x) => !x.stable);
    if (unstable.length) {
      traces.push({ x: unstable.map((x) => toRate(x.q)), y: unstable.map((x) => toP(x.pwf)),
                    mode: "markers", name: "Unstable crossing",
                    marker: { color: "#999", size: 9, symbol: "circle-open" } });
    }
    items.push({ key: `Rate (${rateLabel})`, value: show(toRate(/** @type {number} */ (res.q)), 0) });
    items.push({ key: `Pwf (${pressureLabel})`, value: show(toP(/** @type {number} */ (res.pwf)), 0) });
    if (c.fluid_type === "oil") {
      const wc = /** @type {vlp.OilWaterFluid} */ (c.fluid).water_cut;
      items.push({ key: `Oil rate (${rateLabel})`,
                   value: show(toRate(/** @type {number} */ (res.q)) * (1 - wc), 0) });
    }
  }
  items.push({ key: `AOF (${rateLabel})`, value: show(toRate(res.aof), 0) });
  items.push({ key: `Reservoir pressure (${pressureLabel})`, value: show(toP(c.p_res), 0) });
  drawResults([...items, ...c.extra]);

  const allP = [...cv.ipr_pwf.map(toP), ...cv.vlp_pwf.map(toP)];
  plot("chart-nodal", traces, {
    ...layoutFor(`Rate (${rateLabel})`, `Flowing bottom-hole pressure (${pressureLabel})`),
    yaxis: { ...layoutFor("", "").yaxis, title: { text: `Flowing bottom-hole pressure (${pressureLabel})` },
             range: [0, Math.max(...allP) * 1.05] },
  });
  drawTable(cv.ipr_pwf.map(toP), cv.ipr_q.map(toRate), rateLabel, pressureLabel);

  const note = document.getElementById("profile-note");
  if (!res.found) {
    clearChart("chart-profile");
    if (note) note.textContent = "";
    message("messages", res.message, "warn");
    return;
  }

  // ---- the pressure and temperature profile at the operating rate ----
  const fluidAt = nodal.fluid_at_rate(c.fluid, c.ipr_name, c.p_res, c.ipr_inputs,
                                      /** @type {number} */ (res.q));
  const tr = vlp.pressure_traverse(c.well, fluidAt, /** @type {number} */ (res.q), c.p_wh,
                                   c.correlation, c.max_step_ft, c.gravity_mult, c.friction_mult);
  drawProfile(tr, c);

  const lengthLabel = units.unitOf("length");
  const tempLabel = units.unitOf("temperature");
  if (note) {
    note.textContent =
      `At the operating rate: wellhead ${show(toP(tr.p[0]), 0)} ${pressureLabel} and `
      + `${show(units.fromEngine("temperature", tr.T[0]), 0)} ${tempLabel}; perforations `
      + `${show(toP(tr.p[tr.p.length - 1]), 0)} ${pressureLabel} and `
      + `${show(units.fromEngine("temperature", tr.T[tr.T.length - 1]), 0)} ${tempLabel}. `
      + `Pressure drop in the tubing: gravity ${show(units.fromEngine("pressureDiff", tr.dp_hydrostatic), 0)} `
      + `${units.unitOf("pressureDiff")}, friction `
      + `${show(units.fromEngine("pressureDiff", tr.dp_friction), 0)} ${units.unitOf("pressureDiff")}. `
      + `Flow patterns: ${patternShares(tr.regime, tr.md)}. Steps are `
      + `${show(units.fromEngine("length", c.max_step_ft), 0)} ${lengthLabel} long.`;
  }

  const lift = c.gas_lift ? gasLiftCheck(c, tr) : "";
  message("messages", lift, lift ? "warn" : "");
}

/** The flow patterns the correlation found, as a share of the well. @param {string[]} regimes @param {number[]} md */
function patternShares(regimes, md) {
  /** @type {Record<string, number>} */
  const share = {};
  let total = 0;
  for (let i = 0; i < regimes.length; i++) {
    const length = md[i + 1] - md[i];
    share[regimes[i]] = (share[regimes[i]] || 0) + length;
    total += length;
  }
  return Object.entries(share)
    .sort((a, b) => b[1] - a[1])
    .map(([name, v]) => `${name} ${(100 * v / total).toFixed(0)} %`)
    .join(", ");
}

/**
 * Is the casing gas pressure at the injection depth above the tubing pressure there?  This is the
 * check gaslift.py does in the Python; it is the one thing that makes a gas lift design impossible.
 * @param {Case} c @param {any} tr
 */
function gasLiftCheck(c, tr) {
  const gl = c.gas_lift;
  if (!gl || gl.p_inj <= 0) return "";
  // the gas column in the casing, by the same static gas gradient the Python uses
  const t_avg = 0.5 * (tr.T[0] + wellmod.tvd_at(c.well, gl.md) / c.perf_md
                       * (tr.T[tr.T.length - 1] - tr.T[0]) + tr.T[0]);
  const tvd = wellmod.tvd_at(c.well, gl.md);
  // p = p_inj * exp(0.01875 * sg * TVD / (z * T_R)), the standard static gas column
  const z = pvt.gasProperties(gl.p_inj, t_avg, gl.sg).z;
  const p_casing = gl.p_inj * Math.exp(0.01875 * gl.sg * tvd / (z * (t_avg + 459.67)));
  const p_tubing = interpAt(gl.md, tr.md, tr.p);
  if (p_casing > p_tubing) return "";
  const u = units.unitOf("pressure");
  return `The lift gas cannot get in: at the injection depth the casing gas is at about `
    + `${show(units.fromEngine("pressure", p_casing), 0)} ${u} but the tubing is at `
    + `${show(units.fromEngine("pressure", p_tubing), 0)} ${u}. Raise the injection pressure, or `
    + `move the injection point shallower.`;
}

/** Straight-line interpolation of one value. @param {number} x @param {number[]} xs @param {number[]} ys */
function interpAt(x, xs, ys) {
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  let i = 0;
  while (i < xs.length - 2 && xs[i + 1] < x) i += 1;
  return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i]);
}

/** The pressure and temperature against depth. @param {any} tr @param {Case} c */
function drawProfile(tr, c) {
  const pressureLabel = units.unitOf("pressure");
  const tempLabel = units.unitOf("temperature");
  const lengthLabel = units.unitOf("length");
  const tvd = tr.tvd.map((/** @type {number} */ v) => units.fromEngine("length", v));
  /** @type {any[]} */
  const traces = [
    { x: tr.p.map((/** @type {number} */ p) => units.fromEngine("pressure", p)), y: tvd,
      mode: "lines", name: `Pressure (${pressureLabel})`,
      line: { color: "#d62728", width: 2.5 },
      hovertemplate: `%{x:,.0f} ${pressureLabel} at %{y:,.0f} ${lengthLabel}<extra></extra>` },
    { x: tr.T.map((/** @type {number} */ t) => units.fromEngine("temperature", t)), y: tvd,
      mode: "lines", name: `Temperature (${tempLabel})`, xaxis: "x2",
      line: { color: "#ff7f0e", width: 2, dash: "dot" },
      hovertemplate: `%{x:,.0f} ${tempLabel} at %{y:,.0f} ${lengthLabel}<extra></extra>` },
  ];
  if (c.gas_lift) {
    const depth = units.fromEngine("length", wellmod.tvd_at(c.well, c.gas_lift.md));
    traces.push({ x: [Math.min(...traces[0].x), Math.max(...traces[0].x)], y: [depth, depth],
                  mode: "lines", name: "Gas injection",
                  line: { color: "#2ca02c", width: 1.5, dash: "dash" } });
  }
  plot("chart-profile", traces, {
    ...layoutFor(`Pressure (${pressureLabel})`, `True vertical depth (${lengthLabel})`),
    yaxis: { title: { text: `True vertical depth (${lengthLabel})` }, autorange: "reversed",
             gridcolor: "#eef2f5", zeroline: false },
    xaxis: { title: { text: `Pressure (${pressureLabel})` }, gridcolor: "#eef2f5", zeroline: false,
             rangemode: "tozero" },
    xaxis2: { title: { text: `Temperature (${tempLabel})` }, overlaying: "x", side: "top",
              gridcolor: "transparent", zeroline: false },
    margin: { l: 70, r: 16, t: 42, b: 48 },
  });
}

// ---------------------------------------------------------------------
// The second tab: sensitivity
// ---------------------------------------------------------------------

/**
 * What can be varied, and in which unit.  `path` is what nodal.sensitivity understands.
 *
 * The starting values matter more than they look.  A fixed list such as 100, 200, 400, 800 psig can
 * easily put three of its four values outside what the well can do, and the user then sees a page of
 * "no flow" and has to work out why.  So most choices take their values from the box the user has
 * already filled in - half of it, all of it, one and a half times it - which always straddles the
 * answer.  `scale` does that, reading the box named in `box`; `values` is for the few inputs where
 * fixed numbers are the sensible thing (water cut, tubing sizes).
 * @type {{path: string, label: string, quantity: import("./units.js").Quantity | null,
 *         oil?: boolean, gas?: boolean, box?: string, scale?: number[], values?: number[]}[]}
 */
const SENSITIVITY_CHOICES = [
  { path: "p_wh", label: "Wellhead flowing pressure", quantity: "pressure",
    box: "p_wh", scale: [0.5, 0.75, 1.0, 1.5] },
  { path: "p_res", label: "Reservoir pressure", quantity: "pressure",
    box: "p_res", scale: [0.8, 0.9, 1.0, 1.1] },
  { path: "tubing_id", label: "Tubing inner diameter (in)", quantity: null,
    values: [2.441, 2.992, 3.958] },
  { path: "ipr_inputs.J", label: "Productivity index", quantity: "pi", oil: true,
    box: "pi", scale: [0.5, 1.0, 2.0, 3.0] },
  { path: "fluid.water_cut", label: "Water cut (fraction)", quantity: null, oil: true,
    values: [0, 0.3, 0.6, 0.9] },
  { path: "fluid.gor", label: "Producing GOR", quantity: "gor", oil: true,
    box: "rsb", scale: [0.5, 1.0, 2.0, 4.0] },
  { path: "ipr_inputs.C", label: "Back-pressure C", quantity: null, gas: true,
    box: "bp_c", scale: [0.5, 1.0, 1.5, 2.0] },
  { path: "ipr_inputs.k", label: "Permeability", quantity: "permeability",
    box: "", scale: [0.2, 1.0, 2.0, 5.0] },
];

/** Fill the sensitivity drop-down with what suits this case. */
function fillSensitivityChoices() {
  const box = /** @type {HTMLSelectElement} */ (el("sens_name"));
  const isOil = pick("fluid_type") === "oil";
  /** @type {typeof SENSITIVITY_CHOICES} */
  const wanted = SENSITIVITY_CHOICES.filter((o) => {
    if (o.oil && !isOil) return false;
    if (o.gas && isOil) return false;
    if (o.path === "ipr_inputs.J" && pick("oil_ipr") !== "pi") return false;
    if (o.path === "ipr_inputs.C" && pick("gas_ipr") !== "backpressure") return false;
    if (o.path === "ipr_inputs.k") {
      return isOil ? pick("oil_ipr") === "darcy" : pick("gas_ipr") !== "backpressure";
    }
    return true;
  });
  const before = box.value;
  box.innerHTML = wanted.map((o) => {
    const unit = o.quantity ? ` (${units.unitOf(o.quantity)})` : "";
    const label = o.quantity ? `${o.label}${unit}` : o.label;
    return `<option value="${o.path}">${label}</option>`;
  }).join("");
  if (wanted.some((o) => o.path === before)) box.value = before;
  fillSensitivityValues();
}

/**
 * Put sensible starting values in the values box, in whatever units are on screen.  For a `scale`
 * choice they are multiples of what the user has already typed, so they are always in the right
 * region for this well.
 */
function fillSensitivityValues() {
  const choice = SENSITIVITY_CHOICES.find((o) => o.path === pick("sens_name"));
  if (!choice) return;
  /** @type {number[]} */
  let values;
  if (choice.scale) {
    const box = choice.box || (pick("fluid_type") === "oil" ? "oil_k" : "gas_k");
    const now = num(box) || 1;
    values = choice.scale.map((f) => roundNicely(f * now));
  } else {
    const q = choice.quantity;
    const fixed = choice.values || [];
    values = q
      ? fixed.map((v) => Number(units.convert(q, v, "field", units.system())
                                     .toFixed(units.decimalsFor(q, v))))
      : fixed;
  }
  /** @type {HTMLInputElement} */ (el("sens_values")).value = values.join(", ");
}

/** A number with enough figures to be meaningful and few enough to read. @param {number} v */
function roundNicely(v) {
  if (v === 0) return 0;
  const size = Math.abs(v);
  const decimals = size >= 100 ? 0 : size >= 1 ? 2 : Math.min(10, 3 + Math.ceil(-Math.log10(size)));
  return Number(v.toFixed(decimals));
}

function runSensitivity() {
  const button = /** @type {HTMLButtonElement} */ (el("btn-sens"));
  button.disabled = true;
  button.textContent = "Running...";
  setTimeout(() => {
    try {
      sensitivityNow();
    } catch (error) {
      message("sens-messages", /** @type {Error} */ (error).message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Run sensitivity";
    }
  }, 10);
}

function sensitivityNow() {
  const c = buildCase();
  const path = pick("sens_name");
  const choice = SENSITIVITY_CHOICES.find((o) => o.path === path);
  if (!choice) throw new Error("Choose something to vary.");
  const typed = /** @type {HTMLInputElement} */ (el("sens_values")).value
    .split(",").map((t) => Number(t.trim())).filter((v) => Number.isFinite(v));
  if (typed.length < 2) throw new Error("Give at least two values, separated by commas.");

  // the values arrive in screen units and go to the engine in its own
  const quantity = choice.quantity;
  const engineValues = quantity ? typed.map((v) => units.toEngine(quantity, v)) : typed;

  /** @type {import("./nodal.js").SolveInputs} */
  const base = { well: c.well, fluid: c.fluid, ipr_name: c.ipr_name, p_res: c.p_res,
                 ipr_inputs: c.ipr_inputs, p_wh: c.p_wh, correlation: c.correlation,
                 max_step_ft: c.max_step_ft, n_grid: 20,
                 gravity_mult: c.gravity_mult, friction_mult: c.friction_mult };

  // the tubing size is not one number inside the inputs: each value is a whole new well
  const rows = path === "tubing_id"
    ? nodal.sensitivity(base, "well", engineValues.map((d) => nodal.well_with_tubing_id(c.well, d)),
                        true, NODAL_POINTS)
    : nodal.sensitivity(base, path, engineValues, true, NODAL_POINTS);
  rows.forEach((row, i) => { row.value = typed[i]; });

  const rateLabel = units.unitOf(c.rateUnit);
  const pressureLabel = units.unitOf("pressure");
  const toRate = (/** @type {number} */ q) => units.fromEngine(c.rateUnit, q);
  const toP = (/** @type {number} */ p) => units.fromEngine("pressure", p);
  const colours = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b"];

  // one IPR and one VLP per value
  /** @type {any[]} */
  const curveTraces = [];
  rows.forEach((row, i) => {
    if (!row.curves) return;
    const colour = colours[i % colours.length];
    curveTraces.push({ x: row.curves.ipr_q.map(toRate), y: row.curves.ipr_pwf.map(toP),
                       mode: "lines", name: `IPR ${row.value}`,
                       line: { color: colour, width: 2 } });
    curveTraces.push({ x: row.curves.vlp_q.map(toRate), y: row.curves.vlp_pwf.map(toP),
                       mode: "lines", name: `VLP ${row.value}`,
                       line: { color: colour, width: 2, dash: "dash" } });
    if (row.found) {
      curveTraces.push({ x: [toRate(row.q)], y: [toP(row.pwf)], mode: "markers",
                         showlegend: false, marker: { color: colour, size: 9 } });
    }
  });
  plot("chart-sens-curves", curveTraces,
       layoutFor(`Rate (${rateLabel})`, `Flowing bottom-hole pressure (${pressureLabel})`));

  // the operating rate against the varied input
  const found = rows.filter((r) => r.found);
  plot("chart-sens", [{
    x: found.map((r) => r.value), y: found.map((r) => toRate(r.q)),
    mode: "lines+markers", name: `Rate (${rateLabel})`,
    line: { color: "#1f77b4", width: 2.5 }, marker: { size: 8 },
  }], layoutFor(choice.quantity ? `${choice.label} (${units.unitOf(choice.quantity)})` : choice.label,
                `Operating rate (${rateLabel})`));

  const table = document.getElementById("sens-table");
  if (table) {
    const head = choice.quantity ? `${choice.label} (${units.unitOf(choice.quantity)})` : choice.label;
    table.innerHTML = `<tr><th>${head}</th><th>Rate (${rateLabel})</th>`
      + `<th>Pwf (${pressureLabel})</th></tr>`
      + rows.map((r) => `<tr><td>${r.value}</td>`
          + `<td>${r.found ? show(toRate(r.q), 0) : "no flow"}</td>`
          + `<td>${r.found ? show(toP(r.pwf), 0) : ""}</td></tr>`).join("");
  }
  message("sens-messages", "");
}

// ---------------------------------------------------------------------
// The third tab: every correlation, and matching
// ---------------------------------------------------------------------

const CORRELATION_NAMES = {
  beggs_brill: "Beggs and Brill", hagedorn_brown: "Hagedorn and Brown", gray: "Gray",
  orkiszewski: "Orkiszewski", ansari: "Ansari and others", duns_ros: "Duns and Ros",
  mukherjee_brill: "Mukherjee and Brill", fancher_brown: "Fancher and Brown (no slip)",
};

function compareCorrelations() {
  const button = /** @type {HTMLButtonElement} */ (el("btn-corr"));
  button.disabled = true;
  button.textContent = "Running every correlation...";
  setTimeout(() => {
    try {
      compareNow();
    } catch (error) {
      message("corr-messages", /** @type {Error} */ (error).message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Compare all correlations";
    }
  }, 10);
}

function compareNow() {
  const c = buildCase();
  const rateLabel = units.unitOf(c.rateUnit);
  const pressureLabel = units.unitOf("pressure");
  const rows = [];
  for (const key of Object.keys(CORRELATION_NAMES)) {
    try {
      const res = nodal.solve_well(c.well, c.fluid, c.ipr_name, c.p_res, c.ipr_inputs, c.p_wh,
                                   key, c.max_step_ft, 20, c.gravity_mult, c.friction_mult);
      let patterns = "";
      if (res.found) {
        const f = nodal.fluid_at_rate(c.fluid, c.ipr_name, c.p_res, c.ipr_inputs,
                                      /** @type {number} */ (res.q));
        const tr = vlp.pressure_traverse(c.well, f, /** @type {number} */ (res.q), c.p_wh, key,
                                         c.max_step_ft, c.gravity_mult, c.friction_mult);
        patterns = patternShares(tr.regime, tr.md);
      }
      rows.push({ key, found: res.found, q: res.q, pwf: res.pwf, patterns, error: "" });
    } catch (error) {
      rows.push({ key, found: false, q: null, pwf: null, patterns: "",
                  error: /** @type {Error} */ (error).message });
    }
  }
  const table = document.getElementById("corr-table");
  if (table) {
    table.innerHTML = `<tr><th>Correlation</th><th>Rate (${rateLabel})</th>`
      + `<th>Pwf (${pressureLabel})</th><th>Flow patterns</th><th>Notes</th></tr>`
      + rows.map((r) => {
        const best = r.key === c.correlation ? ' class="best"' : "";
        return `<tr${best}><td>${CORRELATION_NAMES[/** @type {keyof typeof CORRELATION_NAMES} */ (r.key)]}`
          + `${best ? " (in use)" : ""}</td>`
          + `<td>${r.found ? show(units.fromEngine(c.rateUnit, /** @type {number} */ (r.q)), 0) : "no flow"}</td>`
          + `<td>${r.found ? show(units.fromEngine("pressure", /** @type {number} */ (r.pwf)), 0) : ""}</td>`
          + `<td style="text-align:left">${r.patterns}</td>`
          + `<td style="text-align:left">${r.error}</td></tr>`;
      }).join("");
  }
  message("corr-messages", "The spread between these is the honest uncertainty of the tubing "
    + "calculation for this well. Only a measured flowing pressure can narrow it.", "");
}

function runMatch() {
  const button = /** @type {HTMLButtonElement} */ (el("btn-match"));
  button.disabled = true;
  setTimeout(() => {
    try {
      const c = buildCase();
      const m = nodal.match_vlp_multiplier(c.well, c.fluid, eng("match_q"), c.p_wh, eng("match_pwf"),
                                           c.correlation, c.max_step_ft, pick("match_fit"),
                                           0.5, 2.0, units.ATM_PSI, units.unitOf("pressure"));
      const which = pick("match_fit") === "friction" ? "friction_mult" : "gravity_mult";
      const other = which === "friction_mult" ? "gravity_mult" : "friction_mult";
      /** @type {HTMLInputElement} */ (el(which)).value = m.toFixed(3);
      /** @type {HTMLInputElement} */ (el(other)).value = "1";
      noteTyped(which);
      noteTyped(other);
      message("match-messages", `The ${pick("match_fit")} multiplier that reproduces that test is `
        + `<b>${m.toFixed(3)}</b>. It is now in the boxes below and is used everywhere in the app; `
        + "press Calculate to see the operating point with it.", "");
    } catch (error) {
      message("match-messages", /** @type {Error} */ (error).message, "error");
    } finally {
      button.disabled = false;
    }
  }, 10);
}

// ---------------------------------------------------------------------
// Save and open a case (a small file on the user's own computer)
// ---------------------------------------------------------------------
// There is no server, so "save" writes a file into the Downloads folder and "open" reads one back.

function saveCase() {
  /** @type {Record<string, string>} */
  const data = {};
  for (const id of ALL_IDS) {
    const node = document.getElementById(id);
    if (!node) continue;
    data[id] = node instanceof HTMLInputElement && node.type === "checkbox"
      ? String(node.checked)
      : /** @type {HTMLInputElement} */ (node).value;
  }
  data._unit_system = units.system();        // so the numbers mean the same thing when reopened
  const blob = new Blob([JSON.stringify({ tool: "Integrated Well Modelling Tool", version: 2, inputs: data }, null, 2)],
                        { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "well_case.json";
  link.click();
  URL.revokeObjectURL(link.href);
}

/** @param {Event} event */
function openCase(event) {
  const input = /** @type {HTMLInputElement} */ (event.target);
  const file = input.files && input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const parsed = JSON.parse(String(reader.result));
      const saved = parsed && parsed.inputs;
      if (!saved) throw new Error("this file has no saved inputs");
      // the system first, so the saved numbers are read in the units they were written in
      const savedSystem = units.asSystem(saved._unit_system || "field");
      if (savedSystem !== units.system()) {
        units.setSystem(savedSystem);
        /** @type {HTMLSelectElement} */ (el("unit_system")).value = savedSystem;
        writeUnitLabels();
      }
      for (const id of ALL_IDS) {
        if (saved[id] === undefined) continue;
        const node = document.getElementById(id);
        if (!node) continue;
        if (node instanceof HTMLInputElement && node.type === "checkbox") node.checked = saved[id] === "true";
        else /** @type {HTMLInputElement} */ (node).value = saved[id];
        noteTyped(id);          // the saved numbers are now the originals
      }
      fillSensitivityChoices();
      recalculate();
      message("messages", `Opened <b>${file.name}</b>. Press Calculate for the operating point.`, "");
    } catch (error) {
      message("messages", `That file could not be read: ${/** @type {Error} */ (error).message}`, "error");
    }
    input.value = "";
  };
  reader.readAsText(file);
}

// ---------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------

const TABS = [["tab-nodal", "page-nodal"], ["tab-sens", "page-sens"], ["tab-corr", "page-corr"]];

/** @param {string} tabId */
function showTab(tabId) {
  for (const [tab, page] of TABS) {
    const on = tab === tabId;
    el(tab).setAttribute("aria-selected", String(on));
    const node = document.getElementById(page);
    if (node) node.classList.toggle("on", on);
  }
}

// ---------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------

writeUnitLabels();
for (const id of ALL_IDS) {
  const node = document.getElementById(id);
  if (!node) continue;
  for (const event of ["input", "change"]) {
    node.addEventListener(event, () => { noteTyped(id); recalculate(); });
  }
  noteTyped(id);               // the numbers the page opens with count as typed
}
el("fluid_type").addEventListener("change", fillSensitivityChoices);
el("oil_ipr").addEventListener("change", fillSensitivityChoices);
el("gas_ipr").addEventListener("change", fillSensitivityChoices);
el("sens_name").addEventListener("change", fillSensitivityValues);
el("unit_system").addEventListener("change", (event) => {
  switchSystem(/** @type {HTMLSelectElement} */ (event.target).value);
});
el("btn-calc").addEventListener("click", calculate);
el("btn-sens").addEventListener("click", runSensitivity);
el("btn-corr").addEventListener("click", compareCorrelations);
el("btn-match").addEventListener("click", runMatch);
el("btn-reset-mult").addEventListener("click", () => {
  /** @type {HTMLInputElement} */ (el("gravity_mult")).value = "1";
  /** @type {HTMLInputElement} */ (el("friction_mult")).value = "1";
  noteTyped("gravity_mult");
  noteTyped("friction_mult");
  message("match-messages", "Both multipliers are back at 1.00: the correlation is unchanged.", "");
});
el("btn-save").addEventListener("click", saveCase);
el("btn-open").addEventListener("click", () => /** @type {HTMLInputElement} */ (el("file-open")).click());
el("file-open").addEventListener("change", openCase);
for (const [tab] of TABS) el(tab).addEventListener("click", () => showTab(tab));

fillSensitivityChoices();
recalculate();
