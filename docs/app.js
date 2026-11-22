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
import * as advice from "./advice.js";
import * as wellview from "./wellview.js";

// One place for the chart colours, so a pressure line is the same colour wherever it is drawn.
const IPR_COLOUR = "#1f77b4";     // the inflow curve
const PROFILE_P = "#111827";      // the pressure down the well: black, so it is not the IPR
const VLP_COLOUR = "#d62728";     // the tubing curve
const TEMP_COLOUR = "#ff7f0e";    // temperature
const GASLIFT_COLOUR = "#2ca02c"; // the gas lift injection depth

const CURVE_POINTS = 41;          // points along the inflow curve on its own
const NODAL_POINTS = 25;          // points along each curve when the VLP is calculated too

// The shared depth scale.  The pressure and temperature profile and the wellbore schematic are the
// same height and put TVD = 0 and the deepest point at the same two heights, so a depth read off
// one panel is at the same place on the other: these are the chart's top and bottom margins, and
// the schematic is told to use them as its own padding.
// This is only the paper a chart needs above its own plot: the pressure axis along the top of the
// profile, and the legend over the inflow curve.  The drawing's column starts higher up the page,
// where the strip of rates and the titles are, and drawWell adds that head start to its own
// padding, so the tree has more room than this without any of it going to waste on the charts.
const DEPTH_TOP = 66;             // pixels above TVD = 0: the top axis in one, the tree in the other
const DEPTH_BOTTOM = 62;          // below the deepest point: the bottom axis, and the reservoir

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
  // the VLP comparison with measured data
  vc_p_wh: "pressure", vc_rate_type: null, vc_rate: "liquidRate", vc_wc: null, vc_gor: "gor",
  vc_rate_gas: "gasRate", vc_cgr: null, vc_wgr: null,
  vc_gl_rate: "gasRate", vc_gl_md: "length", vc_points: null,
  // matching
  gravity_mult: null, friction_mult: null, match_fit: null,
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

  // the comparison tab: the test conditions follow the fluid, and the gas lift boxes are live only
  // when the well is actually on continuous gas lift
  toggle("vc-oil", oil);
  toggle("vc-gas", !oil);
  const onGasLift = oil && pick("lift") === "continuous";
  for (const id of ["vc_gl_rate", "vc_gl_md"]) {
    const node = document.getElementById(id);
    if (node) /** @type {HTMLInputElement} */ (node).disabled = !onGasLift;
  }
  const glNote = document.getElementById("vc-gl-note");
  if (glNote) {
    glNote.textContent = onGasLift
      ? "The test's own lift gas rate and injection depth, which may differ from the ones on the left."
      : "The gas lift boxes are grey because the artificial lift is not continuous gas lift.";
  }

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

/**
 * What advice.js needs to judge the correlations: the fluid, the water cut or condensate ratio, the
 * oil gravity, and the well path.  Everything is in ENGINE units, as the Python's own inputs are.
 * @returns {import("./advice.js").AdviceInputs}
 */
function adviceInputs() {
  /** @type {number[]} */
  let md = [];
  /** @type {number[]} */
  let tvd = [];
  const mode = pick("survey_mode");
  try {
    [md, tvd] = mode === "vertical" ? wellmod.verticalSurvey(eng("depth")) : surveyFromText();
  } catch {
    md = [];                        // an unreadable survey counts as vertical, as it does in Python
    tvd = [];
  }
  return { fluid_type: pick("fluid_type"), water_cut: num("water_cut") / 100.0, api: num("api"),
           cgr: num("cgr"), survey_mode: md.length >= 2 ? mode : "vertical", md, tvd };
}

/**
 * Keep the correlation box on the app's suggestion until the user chooses one by hand.
 *
 * The suggestion comes from the fluid, the water cut, the oil gravity and the well path, so it moves
 * as those are typed - which is the point: the box should already hold the sensible choice before
 * anyone thinks about it.  Once the user picks a correlation themselves, the app stops moving the box
 * and offers a button to go back to its own suggestion instead.
 */
let correlationPickedByHand = false;

function updateCorrelationAdvice() {
  const inputs = adviceInputs();
  const [suggested] = advice.recommend_correlation(inputs);
  const box = /** @type {HTMLSelectElement} */ (el("correlation"));
  if (!correlationPickedByHand) box.value = suggested;
  const key = box.value;

  const judged = advice.correlation_advice(inputs)[key];
  if (!judged) return;              // not a correlation for this fluid: the box is about to be refilled
  const rating = judged.rating;

  // The short line is always on screen: the correlation's name and the verdict in three words.  The
  // reasons are a paragraph, and a paragraph under every input makes the panel unreadable, so they
  // wait behind the (i) button.
  const why = document.getElementById("corr-why");
  const short = document.getElementById("corr-short");
  if (why) why.className = `advice ${rating}`;
  if (short) {
    const verdict = { good: "looks well suited to this well",
                      ok: "should be usable for this well",
                      caution: "may not suit this well" }[rating];
    short.innerHTML = `<b>${escapeHtml(advice.nameOf(key))}</b> &mdash; ${verdict}`;
  }

  // behind the button: the reasons, the paragraph about the correlation, and the way back to the
  // app's own suggestion
  const reasons = document.getElementById("corr-reasons");
  if (reasons) {
    const caption = advice.correlation_caption(inputs, key);
    const name = advice.nameOf(key);
    // the first sentence is the verdict, which the short line already says
    const rest = caption.slice(name.length).replace(/^[^.]*\.\s*/, "");
    reasons.textContent = rest;
  }
  const detail = document.getElementById("corr-detail");
  if (detail) detail.textContent = advice.correlation_detail(key, pick("fluid_type") === "oil");

  const follow = /** @type {HTMLButtonElement} */ (el("btn-follow"));
  const offer = correlationPickedByHand && key !== suggested;
  follow.classList.toggle("hidden", !offer);
  follow.textContent = offer ? `Use the app's suggestion (${advice.nameOf(suggested)})` : "";
}

/** Text going into innerHTML. @param {string} text */
function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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

/**
 * The numbers that belong to the inflow model rather than to the well - the bubble point, the PI
 * the rock gives, Z and the gas viscosity, how long the transient solution lasts.  They sit under
 * the charts, out of the way of the telemetry.
 * @param {{key: string, value: string}[]} items
 */
function drawExtras(items) {
  const list = document.getElementById("extras");
  if (!list) return;
  list.innerHTML = items
    .map((it) => `<li><span class="k">${it.key}</span><span class="v">${it.value}</span></li>`)
    .join("");
}

/**
 * The strip across the top of the three panels: what the well makes, and how hard it is pulling to
 * make it.  These are the numbers someone looks for first, so they are not left to be found among
 * the telemetry beside the drawing.
 * @param {{key: string, value: string, phase?: string}[]} items @param {boolean} [waiting] true before Calculate
 */
function drawKpis(items, waiting = false) {
  const list = document.getElementById("kpis");
  if (!list) return;
  list.classList.toggle("waiting", waiting);
  list.innerHTML = items
    .map((it) => `<li class="${it.phase ?? ""}"><span class="k">${it.key}</span>`
                 + `<span class="v">${it.value}</span></li>`)
    .join("");
}

/** Which rate the inflow curve is drawn against: the liquid for an oil well, the gas for a gas
 * well.  "Rate" on its own left it to the reader to work out. @param {Case} c */
function rateName(c) {
  return c.fluid_type === "oil" ? "Liquid rate" : "Gas rate";
}

/**
 * What the well makes, for the strip across the top.
 *
 * The same five slots whichever fluid it is, so the strip does not rearrange itself when the fluid
 * type changes: the liquid, what of it is saleable, the water, the gas, and the drawdown it takes.
 * Before Calculate the labels are there and the values are dashes, so the strip is not a surprise
 * that appears later.  The gas is the FORMATION gas; lift gas is injected, not produced, and the
 * line under the drawing says how much of it is going in.
 * @param {Case} c @param {{q: number, pwf: number} | null} res
 */
function kpiItems(c, res) {
  const liquid = units.unitOf("liquidRate");
  const gas = units.unitOf("gasRate");
  const dp = units.unitOf("pressureDiff");
  const q = res ? res.q : 0;
  /** @param {number} x @param {import("./units.js").Quantity} quantity */
  const v = (x, quantity) => (res ? show(units.fromEngine(quantity, x), 0) : "—");
  if (c.fluid_type === "oil") {
    const f = /** @type {vlp.OilWaterFluid} */ (c.fluid);
    const oil = q * (1 - f.water_cut);
    return [
      { key: `Liquid rate (${liquid})`, value: v(q, "liquidRate"), phase: "liquid" },
      { key: `Oil rate (${liquid})`, value: v(oil, "liquidRate"), phase: "oil" },
      { key: `Water rate (${liquid})`, value: v(q * f.water_cut, "liquidRate"), phase: "water" },
      { key: `Gas rate (${gas})`, value: v(oil * f.producingGor() / 1000, "gasRate"),
        phase: "gas" },
      { key: `Drawdown (${dp})`, value: v(c.p_res - (res ? res.pwf : 0), "pressureDiff") },
    ];
  }
  const f = /** @type {vlp.GasFluid} */ (c.fluid);
  return [
    { key: `Liquid rate (${liquid})`, value: v(q * (f.cgr + f.wgr) / 1000, "liquidRate"),
      phase: "liquid" },
    { key: `Condensate rate (${liquid})`, value: v(q * f.cgr / 1000, "liquidRate"), phase: "oil" },
    { key: `Water rate (${liquid})`, value: v(q * f.wgr / 1000, "liquidRate"), phase: "water" },
    { key: `Gas rate (${gas})`, value: v(q, "gasRate"), phase: "gas" },
    { key: `Drawdown (${dp})`, value: v(c.p_res - (res ? res.pwf : 0), "pressureDiff") },
  ];
}

/**
 * A round number to step an axis by, at or just above what was asked for: 1, 2, 2.5 or 5 times a
 * power of ten.  Plotly picks its own steps well enough, but it stops the axis at the data, which
 * leaves the last tick unlabelled - so the page works out the step itself and then rounds the axis
 * out to a whole number of them.
 * @param {number} rough
 */
function niceStep(rough) {
  if (!(rough > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(rough));
  const n = rough / power;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * power;
}

/** One line under the telemetry saying what the well is doing. @param {string} text @param {boolean} [shut] */
function wellState(text, shut = false) {
  const node = document.getElementById("well-state");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("shut", shut);
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

/**
 * The layout of the inflow-and-tubing chart.
 *
 * The rate axis starts a whisker BELOW zero.  Drawn from exactly zero, its "0" tick label printed
 * on top of the pressure axis's own "0" in the corner and the two were unreadable; starting a little
 * to the left of the origin moves the rate's zero clear of the corner without moving the curves.
 * @param {string} rateLabel @param {string} pressureLabel @param {number[]} q @param {number[]} p
 * @param {any[]} [annotations]
 */
function nodalLayout(rateLabel, pressureLabel, q, p, annotations = []) {
  const qMax = Math.max(...q, 1);
  const pMax = Math.max(...p, 1);
  const base = layoutFor(rateLabel, `Flowing bottom-hole pressure (${pressureLabel})`);
  return {
    ...base,
    xaxis: { title: { text: rateLabel }, zeroline: false, gridcolor: "#eef2f5",
             range: [-qMax * 0.022, qMax * 1.03] },
    yaxis: { title: { text: `Flowing bottom-hole pressure (${pressureLabel})` }, zeroline: false,
             gridcolor: "#eef2f5", range: [0, pMax * 1.05] },
    // the same plot area as the profile beside it, so the two charts line up top and bottom
    margin: { l: 70, r: 16, t: DEPTH_TOP, b: DEPTH_BOTTOM },
    legend: { orientation: "h", y: 1.02, yanchor: "bottom", x: 0 },
    annotations,
  };
}

/**
 * The numbers that used to sit in a list beside the drawing, written on the inflow chart at the
 * places they actually mean: the reservoir pressure where the inflow curve meets the pressure
 * axis, the AOF where it meets the rate axis, and at the operating point the rate and the flowing
 * pressure TOGETHER - they are one fact about one point and reading them apart was the problem.
 * @param {Case} c @param {number[]} q @param {number[]} p @param {number} aof
 * @param {{q: number, pwf: number} | null} op
 */
function inflowMarks(c, q, p, aof, op) {
  const pres = units.fromEngine("pressure", c.p_res);
  const rateUnit = units.unitOf(c.rateUnit);
  const pressureUnit = units.unitOf("pressure");
  /** @type {any[]} */
  const out = [
    { x: 0, y: pres, xanchor: "left", yanchor: "bottom", xshift: 8, yshift: 4, showarrow: false,
      text: `Reservoir pressure ${show(pres, 0)} ${pressureUnit}`,
      font: { size: 11, color: IPR_COLOUR }, bgcolor: "rgba(255,255,255,0.8)" },
    { x: aof, y: 0, xanchor: "right", yanchor: "bottom", xshift: -4, yshift: 6, showarrow: false,
      text: `AOF ${show(aof, 0)} ${rateUnit}`,
      font: { size: 11, color: IPR_COLOUR }, bgcolor: "rgba(255,255,255,0.8)" },
  ];
  if (op) {
    out.push({ x: op.q, y: op.pwf, ax: 34, ay: -30, showarrow: true, arrowhead: 0, arrowwidth: 1,
               arrowcolor: "#64748b", xanchor: "left", align: "left",
               text: `<b>${show(op.q, 0)} ${rateUnit}</b><br>${show(op.pwf, 0)} ${pressureUnit}`,
               font: { size: 11, color: "#111827" }, bgcolor: "rgba(255,255,255,0.85)",
               bordercolor: "#cbd5e1", borderwidth: 1, borderpad: 3 });
  }
  return out;
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
  updateCorrelationAdvice();
  drawSketch();
  setStale(true);
  rememberInputs();
  let c;
  try {
    c = buildCase();
    lastCase = c;
  } catch (error) {
    lastCase = null;
    drawExtras([]);
    drawKpis([], true);
    wellState("");
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
    drawExtras([]);
    drawKpis(kpiItems(c, null), true);
    wellState("");
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

  drawExtras(c.extra);
  drawKpis(kpiItems(c, null), true);
  wellState("The inflow only. Press Calculate for the tubing, the operating point and the flow.");
  drawWell(c, null, 0);
  drawTable(pwfShown, qShown, rateLabel, pressureLabel);
  plot("chart-nodal", [{
    x: qShown, y: pwfShown, mode: "lines", name: "IPR",
    line: { color: IPR_COLOUR, width: 2.5 },
    hovertemplate: `%{x:,.0f} ${rateLabel}<br>%{y:,.0f} ${pressureLabel}<extra>IPR</extra>`,
  }], nodalLayout(`${rateName(c)} (${rateLabel})`, pressureLabel, qShown, pwfShown,
                  inflowMarks(c, qShown, pwfShown, aof, null)));
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
  hasNodalResults = true;
  setStale(false);
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
      line: { color: IPR_COLOUR, width: 2.5 } },
    { x: cv.vlp_q.map(toRate), y: cv.vlp_pwf.map(toP), mode: "lines", name: "VLP",
      line: { color: VLP_COLOUR, width: 2.5 } },
  ];
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
  }
  drawExtras(c.extra);
  drawKpis(kpiItems(c, res.found
    ? { q: /** @type {number} */ (res.q), pwf: /** @type {number} */ (res.pwf) }
    : null), !res.found);

  const allQ = [...cv.ipr_q.map(toRate), ...cv.vlp_q.map(toRate)];
  const allP = [...cv.ipr_pwf.map(toP), ...cv.vlp_pwf.map(toP)];
  plot("chart-nodal", traces,
       nodalLayout(`${rateName(c)} (${rateLabel})`, pressureLabel, allQ, allP,
                   inflowMarks(c, allQ, allP, toRate(res.aof), res.found
                     ? { q: toRate(/** @type {number} */ (res.q)),
                         pwf: toP(/** @type {number} */ (res.pwf)) }
                     : null)));
  drawTable(cv.ipr_pwf.map(toP), cv.ipr_q.map(toRate), rateLabel, pressureLabel);

  const note = document.getElementById("profile-note");
  if (!res.found) {
    clearChart("chart-profile");
    if (note) note.textContent = "";
    drawWell(c, null, 0);
    wellState("The well will not flow: the tubing needs more pressure than the reservoir can give "
              + "at any rate.", true);
    message("messages", res.message, "warn");
    return;
  }

  // ---- the pressure and temperature profile at the operating rate ----
  const fluidAt = nodal.fluid_at_rate(c.fluid, c.ipr_name, c.p_res, c.ipr_inputs,
                                      /** @type {number} */ (res.q));
  const tr = vlp.pressure_traverse(c.well, fluidAt, /** @type {number} */ (res.q), c.p_wh,
                                   c.correlation, c.max_step_ft, c.gravity_mult, c.friction_mult);
  drawProfile(tr, c);

  // the flow-pattern tint: the chosen correlation's own pattern when it works one out, otherwise
  // the best suited of the five that do, run on the same well at the same rate
  let patternFrom = patternCorrelationFor(adviceInputs(), c.correlation);
  let borrowed = patternFrom !== c.correlation;
  let patternTr = tr;
  if (borrowed) {
    try {
      patternTr = vlp.pressure_traverse(c.well, fluidAt, /** @type {number} */ (res.q), c.p_wh,
                                        patternFrom, c.max_step_ft, c.gravity_mult, c.friction_mult);
    } catch {
      patternTr = tr;                 // it would not run: show the chosen correlation's own output
      patternFrom = c.correlation;
      borrowed = false;
    }
  }
  drawWell(c, patternTr, /** @type {number} */ (res.q), patternFrom, borrowed);
  const drawdown = show(units.fromEngine("pressureDiff",
                                         c.p_res - /** @type {number} */ (res.pwf)), 0);
  wellState(c.gas_lift
    ? `Flowing on gas lift: ${show(units.fromEngine("gasRate", c.gas_lift.rate), 0)} `
      + `${units.unitOf("gasRate")} injected at `
      + `${show(units.fromEngine("length", c.gas_lift.md), 0)} ${units.unitOf("length")}. `
      + `Drawdown ${drawdown} ${units.unitOf("pressureDiff")}.`
    : `Flowing naturally. Drawdown ${drawdown} ${units.unitOf("pressureDiff")}.`);

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
  // Temperature on the bottom axis, pressure on the top one, and the pressure drawn in the same blue
  // as the IPR so that the pressure line is the same colour wherever it appears on the page.
  const pressure = tr.p.map((/** @type {number} */ p) => units.fromEngine("pressure", p));
  const temperature = tr.T.map((/** @type {number} */ t) => units.fromEngine("temperature", t));
  /** @type {any[]} */
  const traces = [
    { x: temperature, y: tvd,
      mode: "lines", name: `Temperature (${tempLabel})`,
      // solid, not dashed: the axis titles below are written in each line's own colour, which says
      // which line belongs to which axis better than a dash does
      line: { color: TEMP_COLOUR, width: 2.5 },
      hovertemplate: `%{x:,.0f} ${tempLabel} at %{y:,.0f} ${lengthLabel}<extra></extra>` },
    { x: pressure, y: tvd, xaxis: "x2",
      mode: "lines", name: `Pressure (${pressureLabel})`,
      line: { color: PROFILE_P, width: 2.5 },
      hovertemplate: `%{x:,.0f} ${pressureLabel} at %{y:,.0f} ${lengthLabel}<extra></extra>` },
  ];
  /** @type {any[]} */
  const annotations = [];
  // The slope of the pressure traverse, at five depths down it.  The gradient is what an engineer
  // reads a profile FOR - it says what the fluid in that stretch of pipe weighs - and working it
  // out off the axes by eye is the one thing the chart was not doing for them.
  const gradUnit = `${pressureLabel}/${lengthLabel}`;
  for (let i = 1; i <= 5; i++) {
    const at = Math.round((tvd.length - 1) * (i - 0.5) / 5);
    const lo = Math.max(at - 1, 0);
    const hi = Math.min(at + 1, tvd.length - 1);
    const dz = tvd[hi] - tvd[lo];
    if (!(Math.abs(dz) > 1e-9)) continue;
    annotations.push({
      x: pressure[at], y: tvd[at], xref: "x2", yref: "y",
      text: `${((pressure[hi] - pressure[lo]) / dz).toFixed(3)} ${gradUnit}`,
      showarrow: false, xanchor: "right", xshift: -6, yanchor: "middle",
      font: { size: 10, color: PROFILE_P }, bgcolor: "rgba(255, 255, 255, 0.82)",
    });
  }
  if (c.gas_lift) {
    const depth = units.fromEngine("length", wellmod.tvd_at(c.well, c.gas_lift.md));
    // drawn across the pressure axis, which is the line this depth belongs to
    traces.push({ x: [Math.min(...pressure), Math.max(...pressure)], y: [depth, depth], xaxis: "x2",
                  mode: "lines", name: "Gas injection",
                  line: { color: GASLIFT_COLOUR, width: 1.5, dash: "dash" } });
    // and written on the line itself, so the depth can be read without going to the axis
    annotations.push({
      x: Math.max(...pressure), y: depth, xref: "x2", yref: "y",
      text: `Gas lift injection at ${show(depth, 0)} ${lengthLabel}`,
      showarrow: false, xanchor: "right", yanchor: "bottom", yshift: 3,
      font: { color: GASLIFT_COLOUR, size: 11 },
      bgcolor: "rgba(255, 255, 255, 0.82)",
    });
  }
  // Both axes are rounded out to a whole number of ticks.  Left to the data, the pressure axis
  // stopped just above the deepest pressure with no tick to label it, and the temperature axis
  // started just below the wellhead temperature and so never printed it.
  const pStep = niceStep(Math.max(...pressure) / 4);
  const tLo = Math.min(...temperature);
  const tStep = niceStep(Math.max((Math.max(...temperature) - tLo) / 4, 1));
  const tFrom = Math.floor(tLo / tStep) * tStep;
  // the depth axis runs 0 to the deepest point exactly, which is what lets the wellbore schematic
  // beside it put the same depths at the same heights
  const deepest = Math.max(...tvd);
  plot("chart-profile", traces, {
    ...layoutFor(`Temperature (${tempLabel})`, `True vertical depth (${lengthLabel})`),
    yaxis: { title: { text: `True vertical depth (${lengthLabel})` }, range: [deepest, 0],
             gridcolor: "#eef2f5", zeroline: false },
    xaxis: { title: { text: `Temperature (${tempLabel})`, font: { color: TEMP_COLOUR } },
             tickfont: { color: TEMP_COLOUR }, gridcolor: "#eef2f5", zeroline: false,
             tick0: tFrom, dtick: tStep,
             range: [tFrom, Math.ceil(Math.max(...temperature) / tStep) * tStep] },
    xaxis2: { title: { text: `Pressure (${pressureLabel})`, font: { color: PROFILE_P } },
              tickfont: { color: PROFILE_P }, overlaying: "x", side: "top",
              gridcolor: "transparent", zeroline: false, tick0: 0, dtick: pStep,
              range: [0, Math.ceil(Math.max(...pressure) / pStep) * pStep] },
    // inside the chart, in the corner the two lines leave empty: between the top axis title and its
    // tick numbers the legend sat right where the pressure scale has to be read
    legend: { x: 0.03, y: 0.03, xanchor: "left", yanchor: "bottom",
              bgcolor: "rgba(255, 255, 255, 0.82)", bordercolor: "#e3e8ec", borderwidth: 1 },
    annotations,
    margin: { l: 70, r: 16, t: DEPTH_TOP, b: DEPTH_BOTTOM },
  });
}

// ---------------------------------------------------------------------
// The live well: the schematic beside the charts
// ---------------------------------------------------------------------
// The drawing is wellview.js, which both knows nothing about this page and is the only thing that
// draws a well, so the picture cannot disagree with the calculation beside it.  This part works out
// where the packer, the shoe, the perforations and the gas lift valve go for the well that has been
// entered, and hands the traverse over so the fluid moves at the rate the engine found.

// The five correlations that work out a flow pattern.  The other three say so instead of guessing,
// and the drawing borrows a pattern from the best suited of these for the same well.
const PATTERN_CORRELATIONS = ["beggs_brill", "orkiszewski", "duns_ros", "ansari", "mukherjee_brill"];

/**
 * Which correlation the flow-pattern tint should come from: the chosen one when it works out a
 * pattern, otherwise the best suited of the five that do, judged for this same well by the same
 * rules that pick the correlation in the first place.  Only the pattern is borrowed; every pressure
 * stays the chosen correlation's.
 * @param {import("./advice.js").AdviceInputs} inputs @param {string} chosen
 */
function patternCorrelationFor(inputs, chosen) {
  if (PATTERN_CORRELATIONS.includes(chosen)) return chosen;
  const rated = advice.correlation_advice(inputs);
  const order = inputs.fluid_type === "oil" ? advice.PREFERENCE_OIL : advice.PREFERENCE_GAS;
  /** @type {Record<string, number>} */
  const rank = { good: 0, ok: 1, caution: 2 };
  let best = "";
  let bestRank = [9, 9];
  order.forEach((key, index) => {
    if (!PATTERN_CORRELATIONS.includes(key)) return;
    const here = [rank[rated[key]?.rating] ?? 9, index];
    if (here[0] < bestRank[0] || (here[0] === bestRank[0] && here[1] < bestRank[1])) {
      best = key;
      bestRank = here;
    }
  });
  return best || "beggs_brill";
}

/**
 * Where the completion sits in this well.
 *
 * The perforated interval is the net thickness when the inflow model asks for one (the Darcy and
 * Jones models do), and a sensible fraction of the depth otherwise.  The packer goes ABOVE the top
 * of the perforations, which is where a packer goes: it seals the annulus off above the producing
 * interval.  The tubing ends in an open shoe just below it, so the fluid that enters through the
 * perforations rises inside the casing and turns into the open end of the tubing.
 * @param {Case} c
 */
function completionDepths(c) {
  const perf_md = c.perf_md;
  const h = Number(c.ipr_inputs.h);
  // The depth that was entered is the TOP of the perforations, which is where the solver works the
  // flowing pressure out and where the well drawing stops.  The perforated interval runs BELOW it,
  // outside the depth scale the two panels share, so it is drawn in the margin under the well.
  const interval = Math.min(Math.max(Number.isFinite(h) && h > 0 ? h : 0.03 * perf_md, 30),
                            perf_md * 0.2);
  const perf_top = perf_md;
  const gap = Math.max(400, 0.05 * perf_md);
  const packer_md = Math.max(perf_top - gap, perf_md * 0.4);
  const shoe_md = perf_top;          // the tailpipe ends at the top of the perforations
  return { perf_top, packer_md, shoe_md };
}

/** @type {{view: any, player: any} | null} */
let wellView = null;
/** What was last drawn, so a window resize can draw it again at the new size. @type {any[] | null} */
let lastWellArgs = null;

// The drawing is sized from its box, so it has to be drawn again when the box changes.  Plotly
// redraws itself (responsive: true); this does the same for the well.
let resizeTimer = 0;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (lastWellArgs) drawWell(...(/** @type {[any, any, number, string, boolean]} */ (lastWellArgs)));
  }, 150);
});

/**
 * Draw the well, and set the fluid moving at the rate that was found.
 * @param {Case} c @param {any} tr the traverse, or null when nothing has been solved yet
 * @param {number} rate STB/d or Mscf/d, 0 when the well is not flowing
 * @param {string} patternFrom which correlation the pattern tint came from
 * @param {boolean} borrowed whether that is a different correlation from the one in use
 */
function drawWell(c, tr, rate, patternFrom = "", borrowed = false) {
  lastWellArgs = [c, tr, rate, patternFrom, borrowed];
  const svg = /** @type {any} */ (document.getElementById("flow-svg"));
  if (!svg) return;
  // The drawing is given the size of the box it is in, rather than a fixed size scaled to fit,
  // because the depth scale has to be in step with the chart beside it: one drawing unit must be one
  // pixel, or the padding that aligns the two panels would be scaled away with everything else.
  const box = svg.parentElement;
  // The drawing's box runs the full height of the row, while the plots beside it start lower down,
  // under the strip of rates and their own titles.  TVD = 0 still has to sit level with depth zero
  // on the profile, so that head start is added to the padding above the drawing.
  let headStart = 0;
  if (box) {
    const r = box.getBoundingClientRect();
    if (r.width > 40 && r.height > 40) {
      svg.setAttribute("data-w", String(Math.round(r.width)));
      svg.setAttribute("data-h", String(Math.round(r.height)));
      const plot = document.getElementById("chart-profile");
      const pr = plot ? plot.getBoundingClientRect() : null;
      if (pr && pr.height > 40) headStart = Math.max(Math.round(pr.top - r.top), 0);
    }
  }
  const { perf_top, packer_md, shoe_md } = completionDepths(c);
  const oil = /** @type {vlp.OilWaterFluid} */ (c.fluid);
  const isOil = c.fluid_type === "oil";

  // how fast the fluid should move on screen: from the real mixture velocity in the tubing
  let speed = 0;
  if (rate > 0) {
    const area = Math.PI * (num("tubing_id") / 12) ** 2 / 4;
    const ftPerS = isOil ? rate * 5.615 / 86400 / area : rate * 1000 / 86400 / area;
    speed = Math.min(Math.max(ftPerS * 22, 10), 220);
  }

  /** @type {import("./wellview.js").WellSpec} */
  const spec = {
    md: c.well.md, tvd: c.well.tvd, tubing_id: num("tubing_id"),
    perf_top, packer_md, shoe_md,
    gl_md: c.gas_lift ? c.gas_lift.md : null,
    water_cut: isOil ? oil.water_cut : 0.35,
    gor: isOil ? oil.producingGor() : 6000,
    flowing: rate > 0,
    speed,
    lengthUnit: units.unitOf("length"),
    toShown: (ft) => units.fromEngine("length", ft),
    pattern: tr ? { md: tr.md, regime: tr.regime } : null,
    tree: true,
    padTop: DEPTH_TOP + headStart,
    padBottom: DEPTH_BOTTOM,
    // the profile next to it carries the depths; a second scale on the drawing only costs width
    depthAxis: false,
  };
  const view = wellview.render(svg, spec);
  if (wellView) wellView.player.replace(view);
  else wellView = { view, player: wellview.animate(view) };
  wellView.view = view;

  // the legend: the patterns this well has, and where they came from
  const legend = document.getElementById("flow-legend");
  if (legend) {
    if (!tr) {
      legend.innerHTML = "";
    } else {
      // the phases first, as round drops, because that is how they are drawn
      const phases = c.fluid_type === "oil"
        ? [["oil", "Oil"], ["water", "Water"], ["gas", "Gas"]]
        : [["gas", "Gas"], ["oil", "Condensate"], ["water", "Water"]];
      let html = phases
        .map(([key, label]) => `<span><i style="background:`
             + `${wellview.PHASE_COLOURS[key]};border-radius:50%"></i>${label}</span>`)
        .join("");
      if (c.gas_lift) {
        html += `<span><i style="background:${wellview.PHASE_COLOURS.liftGas};`
          + `border-radius:50%"></i>Lift gas</span>`;
      }
      // then the regimes this well has, named rather than swatched: each one is drawn as its own
      // shape inside the tubing, so a colour chip would say nothing
      const rows = Object.keys(wellview.FLOW_FAMILIES)
        .filter((f) => view.families.has(f))
        .map((f) => wellview.FLOW_FAMILIES[f].label);
      if (rows.length) {
        html += `<span class="flow-note">Up the tubing, ${advice.nameOf(patternFrom)} works out `
          + `<b>${rows.join("</b>, <b>")}</b> flow, each drawn as it looks; hover on the tubing `
          + `for the depths.`
          + (borrowed
            ? ` ${advice.nameOf(c.correlation)}, the correlation in use, works out no pattern of `
              + `its own, so the shapes are ${advice.nameOf(patternFrom)}'s for the same well at `
              + `the same rate. Every pressure here is still ${advice.nameOf(c.correlation)}'s.`
            : "")
          + `</span>`;
      }
      legend.innerHTML = html;
    }
  }
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
    line: { color: IPR_COLOUR, width: 2.5 }, marker: { size: 8 },
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
// The third tab: compare the correlations with measured data, and match one to it
// ---------------------------------------------------------------------

// the names live in advice.js, which is where the Streamlit app's own names were translated to
const nameOf = advice.nameOf;

export const SURVEY_MAX_POINTS = 10;      // as many points as the Streamlit table holds

/**
 * The correlations offered for the fluid on screen, best first.  Gray is a gas-well correlation and
 * is not offered for an oil well; the no-slip quality-check bound comes last, after the methods
 * meant to be used.  This is the same split the Streamlit app makes.
 */
function correlationChoices() {
  const isOil = pick("fluid_type") === "oil";
  return [...(isOil ? advice.PREFERENCE_OIL : advice.PREFERENCE_GAS), ...advice.QC_ONLY];
}

/**
 * Fill the correlation box with those choices.  If what was chosen is not among them any more - the
 * fluid type has changed - the app's suggestion is taken instead, and the box goes back to following
 * the suggestion, because the old choice said nothing about this fluid.
 */
function fillCorrelationChoices() {
  const box = /** @type {HTMLSelectElement} */ (el("correlation"));
  const keys = correlationChoices();
  const before = box.value;
  box.innerHTML = keys.map((k) => `<option value="${k}">${nameOf(k)}</option>`).join("");
  if (keys.includes(before)) {
    box.value = before;
  } else {
    correlationPickedByHand = false;
    box.value = advice.recommend_correlation(adviceInputs())[0];
  }
}

/** Build the tick boxes, one per correlation this fluid type offers. */
function fillCorrelationTicks() {
  const host = document.getElementById("vc-corrs");
  if (!host) return;
  const keys = correlationChoices();
  const before = new Set([...host.querySelectorAll("input:checked")].map((n) => n.id));
  const first = host.children.length === 0;
  host.innerHTML = keys.map((k) => {
    const id = `vc_on_${k}`;
    // the first time, everything is ticked; afterwards the user's own choice is kept
    const on = first || before.has(id) ? " checked" : "";
    return `<label><input type="checkbox" id="${id}"${on}>${nameOf(k)}</label>`;
  }).join("");
}

/** Which correlations are ticked. */
function tickedCorrelations() {
  const host = document.getElementById("vc-corrs");
  if (!host) return [];
  return [...host.querySelectorAll("input:checked")].map((n) => n.id.replace("vc_on_", ""));
}

/**
 * The measured points, read from the text box: [depths in ft, pressures in psia], sorted by depth.
 * This is survey_points() of app_helpers.py, with the same errors in the same words.
 * @param {number} perf_md @returns {[number[], number[]]}
 */
function measuredPoints(perf_md) {
  /** @type {[number, number][]} */
  const points = [];
  const lines = /** @type {HTMLTextAreaElement} */ (el("vc_points")).value.split(/\r?\n/);
  let n = 0;
  for (const line of lines) {
    const parts = line.replace(/[,;]/g, " ").split(/\s+/).filter((t) => t.length > 0);
    if (parts.length === 0) continue;
    n += 1;
    if (parts.length < 2) throw new Error(`Point ${n} needs both a depth and a pressure.`);
    const d = Number(parts[0]);
    const p = Number(parts[1]);
    if (!Number.isFinite(d) || !Number.isFinite(p)) {
      throw new Error(`Point ${n}: both the depth and the pressure must be numbers.`);
    }
    if (d < 0 || p <= 0) {
      throw new Error(`Point ${n}: the depth must be 0 or more and the pressure above 0.`);
    }
    const depth = units.toEngine("length", d);
    if (depth > perf_md + 1e-6) {
      throw new Error(`Point ${n}: the depth ${show(d, 0)} ${units.unitOf("length")} is below the `
        + `perforations (${show(units.fromEngine("length", perf_md), 0)} ${units.unitOf("length")}), `
        + "where the calculation ends.");
    }
    points.push([depth, units.toEngine("pressure", p)]);
  }
  if (points.length === 0) {
    throw new Error("Enter at least one measured point: a depth and a pressure.");
  }
  if (points.length > SURVEY_MAX_POINTS) {
    throw new Error(`At most ${SURVEY_MAX_POINTS} measured points; there are ${points.length}.`);
  }
  points.sort((a, b) => a[0] - b[0]);
  return [points.map((x) => x[0]), points.map((x) => x[1])];
}

/**
 * The case as the TEST was flowing, not as the well is now: the test's wellhead pressure, rate,
 * water cut and GOR (or condensate and water ratios), and its gas lift.  This is
 * survey_test_inputs() of app_helpers.py.  The multipliers are left at 1.0, because the comparison is
 * of the correlations as published.
 * @returns {{c: Case, fluid: vlp.OilWaterFluid | vlp.GasFluid, rate: number}}
 */
function testCase() {
  const c = buildCase();
  c.gravity_mult = 1.0;
  c.friction_mult = 1.0;
  c.p_wh = eng("vc_p_wh");
  let rate;
  if (c.fluid_type === "oil") {
    const wc = num("vc_wc") / 100.0;
    if (!(wc >= 0.0 && wc < 1.0)) throw new Error("The water cut must be from 0 to below 100 %.");
    const typed = eng("vc_rate");
    if (!(typed > 0)) throw new Error("The test rate must be above 0.");
    rate = pick("vc_rate_type") === "oil" ? typed / (1.0 - wc) : typed;
    const oil = /** @type {vlp.OilWaterFluid} */ (c.fluid);
    c.fluid = new vlp.OilWaterFluid({
      api: oil.api, gas_sg: oil.gas_sg, rsb: oil.rsb, water_cut: wc,
      gor: num("vc_gor") > 0 ? eng("vc_gor") : null, salinity: oil.salinity,
      pb_meas: oil.pb_meas, pvt_method: oil.pvt_method, visc_method: oil.visc_method,
      injection_gas_rate: c.gas_lift ? eng("vc_gl_rate") : 0.0,
      injection_md: c.gas_lift ? eng("vc_gl_md") : null,
      injection_gas_sg: c.gas_lift ? c.gas_lift.sg : null,
    });
    if (c.gas_lift) c.gas_lift = { ...c.gas_lift, rate: eng("vc_gl_rate"), md: eng("vc_gl_md") };
  } else {
    rate = eng("vc_rate_gas");
    if (!(rate > 0)) throw new Error("The test rate must be above 0.");
    const gas = /** @type {vlp.GasFluid} */ (c.fluid);
    const cgr = num("vc_cgr");
    const gas_sg = cgr > 0 ? pvt.wetGasGravity(gas.gas_sg_dry, cgr, gas.cond_api) : gas.gas_sg_dry;
    c.fluid = new vlp.GasFluid({ gas_sg, cgr, cond_api: gas.cond_api, wgr: num("vc_wgr"),
                                 salinity: gas.salinity, y_h2s: gas.y_h2s, y_co2: gas.y_co2,
                                 visc_method: gas.visc_method, gas_sg_dry: gas.gas_sg_dry });
  }
  // a multilayer well's mixture depends on the rate, so the fluid is taken at the test rate
  const fluid = nodal.fluid_at_rate(c.fluid, c.ipr_name, c.p_res, c.ipr_inputs, rate);
  return { c, fluid, rate };
}

/** @type {{depths: number[], measured: number[], rows: any[], best: string} | null} */
let lastComparison = null;

function compareToSurvey() {
  const button = /** @type {HTMLButtonElement} */ (el("btn-compare"));
  button.disabled = true;
  button.textContent = "Running the correlations...";
  setTimeout(() => {
    try {
      compareNow();
    } catch (error) {
      lastComparison = null;
      clearChart("chart-survey");
      const table = document.getElementById("corr-table");
      if (table) table.innerHTML = "";
      message("corr-messages", `Cannot compare: ${/** @type {Error} */ (error).message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Compare with the measured data";
    }
  }, 10);
}

function compareNow() {
  const keys = tickedCorrelations();
  if (keys.length === 0) throw new Error("Tick at least one correlation.");
  const { c, fluid, rate } = testCase();
  const [depths, measured] = measuredPoints(c.perf_md);

  /** @type {{key: string, label: string, ok: boolean, error: string, calc: number[],
   *          bias: number, mae: number, rms: number, pct: number, md: number[], p: number[]}[]} */
  const rows = [];
  const runs = keys.map((k) => ({ key: k, label: nameOf(k),
                                  g: 1.0, f: 1.0 }));
  // if multipliers are in use, the matched correlation is shown as well, so the match can be judged
  const gNow = num("gravity_mult");
  const fNow = num("friction_mult");
  if (gNow !== 1.0 || fNow !== 1.0) {
    runs.push({ key: c.correlation,
                label: `${nameOf(c.correlation)} matched `
                       + `(gravity x${gNow.toFixed(2)}, friction x${fNow.toFixed(2)})`,
                g: gNow, f: fNow });
  }

  for (const run of runs) {
    try {
      const tr = vlp.pressure_traverse(c.well, fluid, rate, c.p_wh, run.key, c.max_step_ft,
                                       run.g, run.f);
      const calc = depths.map((d) => interpAt(d, tr.md, tr.p));
      const err = calc.map((p, i) => p - measured[i]);
      rows.push({ key: run.key, label: run.label, ok: true, error: "", calc,
                  bias: err.reduce((a, b) => a + b, 0) / err.length,
                  mae: err.reduce((a, b) => a + Math.abs(b), 0) / err.length,
                  rms: Math.sqrt(err.reduce((a, b) => a + b * b, 0) / err.length),
                  pct: 100.0 * err.reduce((a, b, i) => a + Math.abs(b / measured[i]), 0) / err.length,
                  md: tr.md, p: tr.p });
    } catch (error) {
      rows.push({ key: run.key, label: run.label, ok: false,
                  error: /** @type {Error} */ (error).message, calc: [], bias: NaN, mae: NaN,
                  rms: NaN, pct: NaN, md: [], p: [] });
    }
  }

  // the closest one, ignoring the no-slip quality-check bound and the already-matched run
  const ranked = rows.filter((r) => r.ok && !advice.QC_ONLY.includes(r.key)
                                    && !r.label.includes("matched"));
  const best = ranked.length
    ? ranked.reduce((a, b) => (b.rms < a.rms ? b : a)).label
    : "";
  lastComparison = { depths, measured, rows, best };
  drawSurveyChart(depths, measured, rows, c);
  drawSurveyTable(rows, measured, depths, best, c);
}

/** @param {number[]} depths @param {number[]} measured @param {any[]} rows @param {Case} c */
function drawSurveyChart(depths, measured, rows, c) {
  const pressureLabel = units.unitOf("pressure");
  const lengthLabel = units.unitOf("length");
  const colours = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b",
                   "#7f7f7f"];
  /** @type {any[]} */
  const traces = [];
  rows.filter((r) => r.ok).forEach((r, i) => {
    traces.push({ x: r.p.map((/** @type {number} */ p) => units.fromEngine("pressure", p)),
                  y: r.md.map((/** @type {number} */ d) => units.fromEngine("length", d)),
                  mode: "lines", name: r.label,
                  line: { color: colours[i % colours.length], width: 2,
                          dash: r.label.includes("matched") ? "dash" : "solid" } });
  });
  traces.push({ x: measured.map((p) => units.fromEngine("pressure", p)),
                y: depths.map((d) => units.fromEngine("length", d)),
                mode: "markers", name: "Measured",
                marker: { color: "#111", size: 11, symbol: "diamond" } });
  plot("chart-survey", traces, {
    ...layoutFor(`Pressure (${pressureLabel})`, `Measured depth (${lengthLabel})`),
    yaxis: { title: { text: `Measured depth (${lengthLabel})` }, autorange: "reversed",
             gridcolor: "#eef2f5", zeroline: false },
    margin: { l: 70, r: 16, t: 42, b: 48 },
  });
}

/** @param {any[]} rows @param {number[]} measured @param {number[]} depths @param {string} best @param {Case} c */
function drawSurveyTable(rows, measured, depths, best, c) {
  const table = document.getElementById("corr-table");
  const u = units.unitOf("pressureDiff");
  if (table) {
    table.innerHTML = `<tr><th>Correlation</th><th>Mean error (${u})</th>`
      + `<th>Mean absolute (${u})</th><th>RMS (${u})</th><th>Mean absolute (%)</th></tr>`
      + rows.map((r) => {
        if (!r.ok) {
          return `<tr><td>${r.label}</td><td colspan="4" style="text-align:left">${r.error}</td></tr>`;
        }
        const mark = r.label === best ? ' class="best"' : "";
        const d = (/** @type {number} */ v) => show(units.fromEngine("pressureDiff", v), 0);
        const sign = r.bias >= 0 ? "+" : "-";
        return `<tr${mark}><td>${r.label}${r.label === best ? " &larr; closest" : ""}</td>`
          + `<td>${sign}${d(Math.abs(r.bias))}</td><td>${d(r.mae)}</td><td>${d(r.rms)}</td>`
          + `<td>${r.pct.toFixed(1)}</td></tr>`;
      }).join("");
  }
  const note = document.getElementById("corr-note");
  const notes = ["Error = calculated minus measured pressure, over the measured points. A positive "
                 + "mean error means the correlation over-predicts the pressure drop."];
  if (best) {
    const row = rows.find((r) => r.label === best);
    notes.push(`Closest to the measured data: ${best} (RMS error `
      + `${show(units.fromEngine("pressureDiff", row.rms), 0)} ${u}, `
      + `${row.pct.toFixed(1)} % mean absolute error). Choose it on the left if you want to keep it.`);
  }
  // the no-slip bound should be the lowest pressure there is; below it, the data or the PVT is wrong
  const fb = rows.find((r) => r.ok && r.key === "fancher_brown");
  if (fb && c.fluid_type === "oil") {
    const deepest = depths.indexOf(Math.max(...depths));
    if (measured[deepest] < fb.calc[deepest]) {
      notes.push("The deepest measured pressure is BELOW the Fancher and Brown (no slip) "
        + "calculation, which should be the lowest possible. Check the fluid density (PVT), the "
        + "rate and the pressure data before trusting any match.");
    }
  }
  if (note) note.textContent = notes.join(" ");
  message("corr-messages", "");
}

/** Match the chosen correlation to the measured data. */
function runMatch() {
  const button = /** @type {HTMLButtonElement} */ (el("btn-match"));
  button.disabled = true;
  setTimeout(() => {
    try {
      const { c, fluid, rate } = testCase();
      const [depths, measured] = measuredPoints(c.perf_md);
      const found = nodal.match_vlp_survey(c.well, fluid, rate, c.p_wh, depths, measured,
                                           c.correlation, c.max_step_ft, pick("match_fit"),
                                           vlp.MULTIPLIER_MIN, 2.0);
      const g = Number(found.gravity.toFixed(2));
      const f = Number(found.friction.toFixed(2));
      /** @type {HTMLInputElement} */ (el("gravity_mult")).value = String(g);
      /** @type {HTMLInputElement} */ (el("friction_mult")).value = String(f);
      noteTyped("gravity_mult");
      noteTyped("friction_mult");
      const u = units.unitOf("pressureDiff");
      const name = nameOf(c.correlation);
      let text = `<b>${name}</b> matched: gravity x${g.toFixed(2)}, friction x${f.toFixed(2)}. `
        + `The root-mean-square error over the measured points went from `
        + `${show(units.fromEngine("pressureDiff", found.rms_before), 0)} to `
        + `${show(units.fromEngine("pressureDiff", found.rms_after), 0)} ${u}. `
        + "The multipliers are in the boxes below and are used everywhere in the app; press "
        + "Calculate for the operating point with them.";
      if (found.at_limit.length) {
        text += ` The ${found.at_limit.join(" and ")} multiplier ran to the end of its range, so `
          + "this match is not reliable: something other than the correlation is probably wrong.";
      }
      message("match-messages", text, found.at_limit.length ? "warn" : "");
    } catch (error) {
      message("match-messages", `Cannot match: ${/** @type {Error} */ (error).message}`, "error");
    } finally {
      button.disabled = false;
    }
  }, 10);
}

// ---------------------------------------------------------------------
// The well drawing
// ---------------------------------------------------------------------
// A survey typed wrong, or a gas lift valve put below the perforations, is obvious in a picture and
// invisible in a column of numbers.  The drawing is plain SVG, built from the same survey the
// calculation uses, so it cannot show a different well from the one being solved.

function drawSketch() {
  const svg = document.getElementById("sketch");
  const note = document.getElementById("sketch-note");
  if (!svg) return;
  /** @type {number[]} */
  let md = [];
  /** @type {number[]} */
  let tvd = [];
  try {
    [md, tvd] = pick("survey_mode") === "vertical"
      ? wellmod.verticalSurvey(eng("depth"))
      : surveyFromText();
  } catch (error) {
    svg.innerHTML = "";
    if (note) note.textContent = /** @type {Error} */ (error).message;
    return;
  }

  // the horizontal distance along the well, worked out from MD and TVD step by step
  const reach = [0];
  for (let i = 1; i < md.length; i++) {
    const dmd = md[i] - md[i - 1];
    const dtvd = tvd[i] - tvd[i - 1];
    reach.push(reach[i - 1] + Math.sqrt(Math.max(dmd * dmd - dtvd * dtvd, 0)));
  }

  const W = 300;
  const H = 200;
  const pad = { l: 16, r: 16, t: 20, b: 14 };
  const maxX = Math.max(...reach, 1);
  const maxY = Math.max(...tvd, 1);
  // one scale for both directions, so a deviated well looks deviated and a vertical one looks vertical
  const scale = Math.min((W - pad.l - pad.r) / Math.max(maxX, maxY * 0.35),
                         (H - pad.t - pad.b) / maxY);
  const x = (/** @type {number} */ r) => pad.l + r * scale;
  const y = (/** @type {number} */ d) => pad.t + d * scale;
  const path = md.map((_, i) => `${i === 0 ? "M" : "L"}${x(reach[i]).toFixed(1)},${y(tvd[i]).toFixed(1)}`).join(" ");

  const lengthLabel = units.unitOf("length");
  const shown = (/** @type {number} */ ft) => show(units.fromEngine("length", ft), 0);
  const parts = [
    `<line class="ground" x1="0" y1="${y(0)}" x2="${W}" y2="${y(0)}"/>`,
    `<text x="${x(0) + 4}" y="${y(0) - 6}">wellhead</text>`,
    `<path class="hole" d="${path}" stroke-width="7" stroke-linecap="round"/>`,   // the hole
    `<path class="tube" d="${path}"/>`,                                            // the tubing in it
  ];

  // the perforations, at the bottom of the survey
  const last = md.length - 1;
  parts.push(`<line class="perf" x1="${x(reach[last]) - 7}" y1="${y(tvd[last])}" `
    + `x2="${x(reach[last]) + 7}" y2="${y(tvd[last])}"/>`);
  parts.push(`<text x="${Math.min(x(reach[last]) + 10, W - 70)}" y="${y(tvd[last]) + 3}">`
    + `perforations ${shown(md[last])} ${lengthLabel} MD</text>`);

  // the gas lift injection point, if there is one
  /** @type {string[]} */
  const notes = [];
  if (pick("lift") === "continuous") {
    const inj = eng("gl_md");
    if (inj > 0 && inj < md[last]) {
      const injTvd = wellmod.tvd_at({ md, tvd, tubing: [[0, md[last], 1]], t_reservoir: 100,
                                      roughness_in: 0, ambient_table: [[0, 80, 5]] }, inj);
      // where along the well that depth is, by interpolating the reach on MD
      let i = 0;
      while (i < md.length - 2 && md[i + 1] < inj) i += 1;
      const f = (inj - md[i]) / (md[i + 1] - md[i]);
      const injReach = reach[i] + f * (reach[i + 1] - reach[i]);
      parts.push(`<line class="inj" x1="${x(injReach) - 9}" y1="${y(injTvd)}" `
        + `x2="${x(injReach) + 9}" y2="${y(injTvd)}"/>`);
      parts.push(`<text x="${Math.min(x(injReach) + 12, W - 60)}" y="${y(injTvd) + 3}">`
        + `gas lift ${shown(inj)} ${lengthLabel} MD</text>`);
    } else {
      notes.push("The gas lift injection depth is not above the perforations.");
    }
  }

  svg.innerHTML = parts.join("");
  const deviation = Math.max(...md.map((_, i) => reach[i]));
  notes.unshift(`${shown(md[last])} ${lengthLabel} along the well, `
    + `${shown(tvd[last])} ${lengthLabel} straight down`
    + (deviation > 1 ? `, ${shown(deviation)} ${lengthLabel} sideways` : " (vertical)")
    + `, ${num("tubing_id")} in tubing.`);
  if (note) note.textContent = notes.join(" ");
}

// ---------------------------------------------------------------------
// Are the answers on screen still the answers to what is in the boxes?
// ---------------------------------------------------------------------
// The tubing side waits for the Calculate button, so the page can show an operating point for a well
// that has since been edited.  That is how a wrong number ends up in a report, so the moment an input
// changes the answers go grey and the bar says to press Calculate again.

let resultsAreStale = false;

/** @param {boolean} stale */
function setStale(stale) {
  resultsAreStale = stale;
  const marker = document.getElementById("stale");
  const main = document.querySelector("main.main");
  // nothing to go stale until the tubing has been calculated at least once
  const show_it = stale && hasNodalResults;
  if (marker) marker.classList.toggle("hidden", !show_it);
  if (main) main.classList.toggle("stale-results", show_it);
}

let hasNodalResults = false;

// ---------------------------------------------------------------------
// Remembering the well in this browser
// ---------------------------------------------------------------------
// There is no server and no login, so a refresh would otherwise throw the well away.  The inputs are
// kept in this browser only: they never leave the machine, and another person opening the page sees
// the starting values.  Every read and write is wrapped, because browser storage can be switched off
// or full, and the page must work either way.

const STORE_KEY = "iwmt.inputs.v1";

function rememberInputs() {
  try {
    /** @type {Record<string, string>} */
    const data = {};
    for (const id of ALL_IDS) {
      const node = document.getElementById(id);
      if (!node) continue;
      data[id] = node instanceof HTMLInputElement && node.type === "checkbox"
        ? String(node.checked)
        : /** @type {HTMLInputElement} */ (node).value;
    }
    data._unit_system = units.system();
    data._by_hand = String(correlationPickedByHand);
    localStorage.setItem(STORE_KEY, JSON.stringify(data));
  } catch {
    // storage off, private window, or full: the page works without it
  }
}

/** Put back whatever was remembered.  @returns {boolean} whether anything was restored */
function restoreInputs() {
  /** @type {Record<string, string> | null} */
  let data = null;
  try {
    const raw = localStorage.getItem(STORE_KEY);
    data = raw ? JSON.parse(raw) : null;
  } catch {
    return false;
  }
  if (!data || typeof data !== "object") return false;
  try {
    const system = units.asSystem(data._unit_system || "field");
    if (system !== units.system()) {
      units.setSystem(system);
      /** @type {HTMLSelectElement} */ (el("unit_system")).value = system;
    }
    correlationPickedByHand = data._by_hand === "true";
    fillCorrelationChoices();
    for (const id of ALL_IDS) {
      if (data[id] === undefined) continue;
      const node = document.getElementById(id);
      if (!node) continue;
      if (node instanceof HTMLInputElement && node.type === "checkbox") {
        node.checked = data[id] === "true";
      } else {
        /** @type {HTMLInputElement} */ (node).value = data[id];
      }
      noteTyped(id);
    }
    writeUnitLabels();
    return true;
  } catch {
    return false;
  }
}

/** Put every input back to the value the page opens with. */
function resetInputs() {
  try {
    localStorage.removeItem(STORE_KEY);
  } catch {
    // nothing to clear
  }
  location.reload();
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
  // The correlation box has its own listener further down, because it must record that the user
  // chose by hand BEFORE anything recalculates.  Wired here as well, it would recalculate first and
  // put the app's own suggestion straight back, so a correlation could not be chosen at all.
  if (id !== "correlation") {
    for (const event of ["input", "change"]) {
      node.addEventListener(event, () => { noteTyped(id); recalculate(); });
    }
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
// Enter anywhere in the form calculates, rather than doing nothing or submitting the form
el("panel").addEventListener("keydown", (event) => {
  const key = /** @type {KeyboardEvent} */ (event);
  if (key.key !== "Enter") return;
  const target = /** @type {HTMLElement} */ (key.target);
  if (target instanceof HTMLTextAreaElement) return;      // a survey needs its line breaks
  key.preventDefault();
  calculate();
});
el("btn-reset").addEventListener("click", resetInputs);
el("btn-why").addEventListener("click", () => {
  const box = el("corr-long");
  const open = box.classList.toggle("hidden");
  el("btn-why").setAttribute("aria-expanded", String(!open));
});
el("btn-sens").addEventListener("click", runSensitivity);
el("btn-compare").addEventListener("click", compareToSurvey);
el("btn-match").addEventListener("click", runMatch);
el("correlation").addEventListener("change", () => {
  correlationPickedByHand = true;       // the user has chosen; stop moving the box for them
  noteTyped("correlation");
  recalculate();
});
el("btn-follow").addEventListener("click", () => {
  correlationPickedByHand = false;
  updateCorrelationAdvice();
  recalculate();
});
el("fluid_type").addEventListener("change", () => {
  fillCorrelationChoices();
  fillCorrelationTicks();
  updateCorrelationAdvice();
});
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
fillCorrelationChoices();
fillCorrelationTicks();
// the well this browser was last working on, if there is one
const restored = restoreInputs();
fillSensitivityChoices();
fillCorrelationTicks();
recalculate();
setStale(false);                 // nothing has been calculated yet, so nothing is out of date
if (restored) {
  message("messages", "This is the well you were last working on, remembered in this browser. "
    + "<b>Reset</b> puts everything back to the starting values. Press <b>Calculate</b> to add the "
    + "tubing, the operating point and the profile.", "");
}
