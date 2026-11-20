// @ts-check
/**
 * app.js - the page: read the boxes, call the engine, draw the chart.
 *
 * Nothing in here does any petroleum engineering.  The maths is in ipr.js and pvt.js, which are
 * translations of the Python engine; this file only moves numbers between the screen and those two,
 * and asks units.js to convert between what the user types (gauge pressure) and what the engine
 * works in (absolute pressure).
 */

import * as ipr from "./ipr.js";
import * as pvt from "./pvt.js";
import * as units from "./units.js";

const CURVE_POINTS = 41;          // points along the IPR curve

// ---------------------------------------------------------------------
// Reading the form
// ---------------------------------------------------------------------

/** @param {string} id @returns {HTMLInputElement|HTMLSelectElement} */
function el(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`No element with id "${id}"`);
  return /** @type {HTMLInputElement|HTMLSelectElement} */ (node);
}

/** The number in a box. @param {string} id */
function num(id) {
  return parseFloat(/** @type {HTMLInputElement} */ (el(id)).value);
}

/** The chosen value of a dropdown. @param {string} id */
function pick(id) {
  return el(id).value;
}

/** Show or hide a block. @param {string} id @param {boolean} on */
function toggle(id, on) {
  const node = document.getElementById(id);
  if (node) node.classList.toggle("hidden", !on);
}

/** Every input that should trigger a recalculation. */
const ALL_IDS = ["fluid_type", "p_res", "t_res", "oil_ipr", "pi", "vogel_q", "vogel_pwf",
  "fet_q1", "fet_pwf1", "fet_q2", "fet_pwf2", "oil_k", "oil_h", "oil_bo", "oil_mu", "oil_re",
  "oil_rw", "oil_skin", "oil_regime", "oil_phi", "oil_ct", "oil_time", "pb",
  "gas_ipr", "gas_sg_g", "y_h2s", "y_co2", "gas_visc", "gas_k", "gas_h", "gas_re", "gas_rw",
  "gas_skin", "gas_beta", "bp_c", "bp_n"];

// ---------------------------------------------------------------------
// Which boxes belong to the chosen model
// ---------------------------------------------------------------------

function updateVisibility() {
  const oil = pick("fluid_type") === "oil";
  toggle("g-oil", oil);
  toggle("g-gas", !oil);

  const oilModel = pick("oil_ipr");
  toggle("f-pi", oilModel === "pi");
  toggle("f-vogel", oilModel === "vogel");
  toggle("f-fet", oilModel === "fetkovich");
  toggle("f-darcy", oilModel === "darcy");
  toggle("f-transient", oilModel === "darcy" && pick("oil_regime") === "transient");
  // Fetkovich gets its shape from the two tests, so it needs no bubble point
  toggle("f-pb", oilModel !== "fetkovich");

  const gasModel = pick("gas_ipr");
  toggle("f-gasrock", gasModel !== "backpressure");
  toggle("f-beta", gasModel === "jones");
  toggle("f-bp", gasModel === "backpressure");
}

/** Put the current unit names into every label that asked for one. */
function writeUnitLabels() {
  for (const node of document.querySelectorAll("[data-unit]")) {
    const quantity = /** @type {any} */ (node.getAttribute("data-unit"));
    node.textContent = `(${units.unitOf(quantity)})`;
  }
}

// ---------------------------------------------------------------------
// Building the engine call from the form
// ---------------------------------------------------------------------

/**
 * Turn the form into the name of an IPR model and its inputs, in ENGINE units (psia).
 * @returns {{name: string, inputs: Record<string, any>, p_res: number, rateUnit: "liquidRate"|"gasRate",
 *            extra: {key: string, value: string}[]}}
 */
function buildCase() {
  const pRes = units.toEngine("pressure", num("p_res"));
  const tRes = units.toEngine("temperature", num("t_res"));
  /** @type {{key: string, value: string}[]} */
  const extra = [];

  if (pick("fluid_type") === "oil") {
    const model = pick("oil_ipr");
    const pb = units.toEngine("pressure", num("pb"));

    if (model === "pi") {
      return { name: "oil_pi", p_res: pRes, rateUnit: "liquidRate", extra,
               inputs: { pb, J: units.toEngine("pi", num("pi")) } };
    }
    if (model === "vogel") {
      const inputs = { pb, q_test: units.toEngine("liquidRate", num("vogel_q")),
                       pwf_test: units.toEngine("pressure", num("vogel_pwf")) };
      // show the PI the test implies, which is the useful number from a Vogel fit
      const J = ipr.vogel_productivity_index(pRes, pb, inputs.q_test, inputs.pwf_test);
      extra.push({ key: `PI from the test (${units.unitOf("pi")})`, value: units.show(units.fromEngine("pi", J), 2) });
      return { name: "oil_vogel", p_res: pRes, rateUnit: "liquidRate", extra, inputs };
    }
    if (model === "fetkovich") {
      const inputs = { q1: units.toEngine("liquidRate", num("fet_q1")),
                       pwf1: units.toEngine("pressure", num("fet_pwf1")),
                       q2: units.toEngine("liquidRate", num("fet_q2")),
                       pwf2: units.toEngine("pressure", num("fet_pwf2")) };
      const [C, n] = ipr.c_and_n_from_two_tests(pRes, inputs.q1, inputs.pwf1, inputs.q2, inputs.pwf2);
      extra.push({ key: "n from the two tests", value: n.toFixed(3) });
      extra.push({ key: "C from the two tests", value: C.toExponential(3) });
      return { name: "oil_fetkovich", p_res: pRes, rateUnit: "liquidRate", extra, inputs };
    }
    // Darcy, with its three flow regimes
    const regime = pick("oil_regime");
    const inputs = { pb, k: num("oil_k"), h: units.toEngine("length", num("oil_h")),
                     bo: num("oil_bo"), mu: num("oil_mu"),
                     re: units.toEngine("length", num("oil_re")),
                     rw: units.toEngine("length", num("oil_rw")),
                     skin: num("oil_skin"), regime,
                     phi: regime === "transient" ? num("oil_phi") : null,
                     ct: regime === "transient" ? num("oil_ct") : null,
                     time_hours: regime === "transient" ? num("oil_time") : null };
    let J;
    if (regime === "pseudosteady") {
      J = ipr.darcy_productivity_index_oil(inputs.k, inputs.h, inputs.bo, inputs.mu, inputs.re, inputs.rw, inputs.skin);
    } else if (regime === "steady") {
      J = ipr.darcy_productivity_index_oil_steady(inputs.k, inputs.h, inputs.bo, inputs.mu, inputs.re, inputs.rw, inputs.skin);
    } else {
      J = ipr.darcy_productivity_index_oil_transient(inputs.k, inputs.h, inputs.bo, inputs.mu,
                                                     /** @type {number} */ (inputs.phi),
                                                     /** @type {number} */ (inputs.ct), inputs.rw,
                                                     /** @type {number} */ (inputs.time_hours), inputs.skin);
      const tEnd = ipr.transient_end_time_hours(inputs.k, /** @type {number} */ (inputs.phi), inputs.mu,
                                                /** @type {number} */ (inputs.ct), inputs.re);
      extra.push({ key: "Transient valid until (h)", value: units.show(tEnd, 0) });
    }
    extra.push({ key: `PI from the rock (${units.unitOf("pi")})`, value: units.show(units.fromEngine("pi", J), 3) });
    return { name: "oil_darcy_regime", p_res: pRes, rateUnit: "liquidRate", extra, inputs };
  }

  // ---- gas ----
  const model = pick("gas_ipr");
  const gasSg = num("gas_sg_g");
  if (model === "backpressure") {
    return { name: "gas_backpressure", p_res: pRes, rateUnit: "gasRate", extra,
             inputs: { C: num("bp_c"), n: num("bp_n") } };
  }
  // Darcy and Jones need Z and viscosity.  Exactly as the Python does it, they are evaluated at
  // 75 % of the reservoir pressure (a typical average of Pr and Pwf) and the reservoir temperature.
  const props = pvt.gasProperties(0.75 * pRes, tRes, gasSg, num("y_h2s"), num("y_co2"), pick("gas_visc"));
  extra.push({ key: "Z at 0.75 Pr", value: props.z.toFixed(4) });
  extra.push({ key: "Gas viscosity (cP)", value: props.mu_g.toFixed(5) });
  const common = { temp_f: tRes, k: num("gas_k"), h: units.toEngine("length", num("gas_h")),
                   mu: props.mu_g, z: props.z,
                   re: units.toEngine("length", num("gas_re")),
                   rw: units.toEngine("length", num("gas_rw")), skin: num("gas_skin") };
  if (model === "darcy") {
    return { name: "gas_darcy", p_res: pRes, rateUnit: "gasRate", extra, inputs: common };
  }
  const beta = num("gas_beta") > 0 ? num("gas_beta") : null;
  if (beta === null) {
    extra.push({ key: "beta estimated (1/ft)", value: ipr.gas_beta_firoozabadi_katz(common.k).toExponential(3) });
  }
  return { name: "gas_jones", p_res: pRes, rateUnit: "gasRate", extra,
           inputs: { ...common, gas_sg: gasSg, beta, h_perf: null } };
}

// ---------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------

/** @param {string} html @param {string} [kind] */
function message(html, kind = "") {
  const box = document.getElementById("messages");
  if (box) box.innerHTML = html ? `<p class="note ${kind}">${html}</p>` : "";
}

/** @param {{key: string, value: string}[]} items */
function drawResults(items) {
  const list = document.getElementById("results");
  if (!list) return;
  list.innerHTML = items
    .map((it) => `<li><span class="k">${it.key}</span><span class="v">${it.value}</span></li>`)
    .join("");
}

/** Empty the chart area (used when an input is not usable). */
function clearChart() {
  const box = document.getElementById("chart");
  // @ts-ignore - Plotly comes from the CDN script tag
  if (box && typeof Plotly !== "undefined") Plotly.purge(box);
  if (box) box.innerHTML = "";
}

/** @param {number[]} pwfShown @param {number[]} qShown @param {string} rateLabel @param {string} pressureLabel */
function drawChart(pwfShown, qShown, rateLabel, pressureLabel) {
  // @ts-ignore - Plotly comes from the CDN script tag
  if (typeof Plotly === "undefined") {
    // The chart library could not be fetched (no connection, or a blocked network).  The numbers are
    // all still there, so say so plainly rather than leaving an empty space.
    const box = document.getElementById("chart");
    if (box) {
      box.innerHTML = '<p class="note warn">The chart library could not be loaded, so the curve '
        + 'cannot be drawn. Everything else on this page is calculated and correct - open '
        + '<b>The curve as numbers</b> below to read it. Check the internet connection and reload.</p>';
    }
    return;
  }
  // @ts-ignore
  Plotly.react("chart", [{
    x: qShown, y: pwfShown, type: "scatter", mode: "lines",
    line: { color: getComputedStyle(document.documentElement).getPropertyValue("--ipr").trim() || "#1f77b4", width: 2.4 },
    name: "IPR", hovertemplate: `%{x:,.0f} ${rateLabel}<br>%{y:,.0f} ${pressureLabel}<extra></extra>`,
  }], {
    margin: { l: 70, r: 20, t: 20, b: 55 },
    xaxis: { title: { text: `Rate (${rateLabel})` }, rangemode: "tozero", zeroline: false,
             gridcolor: "#eef2f5", separatethousands: true },
    // The engine's curve ends at zero ABSOLUTE pressure, which is -14.7 psig, so the axis is told to
    // start at zero gauge; the small tail below it is simply not shown.  The engine is left alone:
    // it quotes AOF at zero absolute pressure, the same convention as the desktop version and as the
    // slides the inflow models were checked against.
    yaxis: { title: { text: `Flowing bottom-hole pressure (${pressureLabel})` },
             range: [0, Math.max(...pwfShown) * 1.02],
             zeroline: false, gridcolor: "#eef2f5", separatethousands: true },
    showlegend: false,
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "-apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif", size: 13, color: "#16202b" },
  }, { displaylogo: false, responsive: true,
       modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] });
}

/** @param {number[]} pwfShown @param {number[]} qShown @param {string} rateLabel @param {string} pressureLabel */
function drawTable(pwfShown, qShown, rateLabel, pressureLabel) {
  const table = document.getElementById("curve-table");
  if (!table) return;
  const step = Math.max(1, Math.floor(pwfShown.length / 15));
  let html = `<tr><th>Pwf (${pressureLabel})</th><th>Rate (${rateLabel})</th></tr>`;
  for (let i = 0; i < pwfShown.length; i += step) {
    if (pwfShown[i] < 0) continue;              // below zero gauge: the engine's last point only
    html += `<tr><td>${units.show(pwfShown[i], 0)}</td><td>${units.show(qShown[i], 0)}</td></tr>`;
  }
  html += `<tr><td>0 <span style="color:var(--ink-soft)">(AOF)</span></td>`
        + `<td>${units.show(qShown[qShown.length - 1], 0)}</td></tr>`;
  table.innerHTML = html;
}

// ---------------------------------------------------------------------
// The whole calculation, run on every change
// ---------------------------------------------------------------------

function recalculate() {
  updateVisibility();
  ipr.takeWarnings();                                 // start with an empty warning list

  // On a bad input, clear the answers before showing the error.  Leaving the previous numbers on
  // screen under an error message is worse than showing nothing: they look like the answer to what
  // was just typed.
  let built, curve;
  try {
    built = buildCase();
    curve = ipr.ipr_curve(built.name, built.p_res, CURVE_POINTS, built.inputs);
  } catch (error) {
    drawResults([]);
    clearChart();
    const table = document.getElementById("curve-table");
    if (table) table.innerHTML = "";
    message(`<b>Cannot calculate:</b> ${/** @type {Error} */ (error).message}`, "error");
    return;
  }

  const { name, inputs, p_res, rateUnit, extra } = built;

  const pressureLabel = units.unitOf("pressure");
  const rateLabel = units.unitOf(rateUnit);
  const pwfShown = curve.pwf.map((p) => units.fromEngine("pressure", p));
  const qShown = curve.q.map((q) => units.fromEngine(rateUnit, q));

  // AOF is the rate at Pwf = 0 psia, which is the last point of the curve.
  const aof = qShown[qShown.length - 1];
  /** @type {{key: string, value: string}[]} */
  const items = [
    { key: `AOF (${rateLabel})`, value: `${units.show(aof, 0)}` },   // at zero absolute pressure
    { key: `Reservoir pressure (${pressureLabel})`, value: units.show(units.fromEngine("pressure", p_res), 0) },
    ...extra,
  ];
  drawResults(items);
  drawChart(pwfShown, qShown, rateLabel, pressureLabel);
  drawTable(pwfShown, qShown, rateLabel, pressureLabel);

  const warnings = ipr.takeWarnings();
  message(warnings.length ? `<b>Note:</b> ${warnings.join(" ")}` : "", "warn");
}

// ---------------------------------------------------------------------
// Example wells
// ---------------------------------------------------------------------

/** @type {Record<string, Record<string, string>>} */
const SAMPLES = {
  oil_pi: { fluid_type: "oil", oil_ipr: "pi", p_res: "3000", t_res: "200", pi: "3", pb: "2484" },
  oil_vogel: { fluid_type: "oil", oil_ipr: "vogel", p_res: "2200", t_res: "180",
               vogel_q: "1500", vogel_pwf: "1100", pb: "2800" },
  oil_darcy: { fluid_type: "oil", oil_ipr: "darcy", p_res: "3000", t_res: "200",
               oil_k: "50", oil_h: "20", oil_bo: "1.25", oil_mu: "0.8",
               oil_re: "1000", oil_rw: "0.354", oil_skin: "0", oil_regime: "pseudosteady", pb: "2484" },
  gas_jones: { fluid_type: "gas", gas_ipr: "jones", p_res: "4500", t_res: "230",
               gas_sg_g: "0.65", gas_k: "5", gas_h: "40", gas_re: "1000", gas_rw: "0.354",
               gas_skin: "0", gas_beta: "0" },
};

function loadSample() {
  const key = pick("sample");
  const sample = SAMPLES[key];
  if (!sample) return;
  for (const [id, value] of Object.entries(sample)) el(id).value = value;
  recalculate();
}

// ---------------------------------------------------------------------
// Save and open a case (a small file on the user's own computer)
// ---------------------------------------------------------------------
// There is no server, so "save" writes a file into the Downloads folder and "open" reads one back.
// The file is plain text, so it can be kept in a well folder or emailed.

function saveCase() {
  /** @type {Record<string, string>} */
  const data = {};
  for (const id of ALL_IDS) data[id] = el(id).value;
  const blob = new Blob([JSON.stringify({ tool: "Integrated Well Modelling Tool", version: 1, inputs: data }, null, 2)],
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
      for (const id of ALL_IDS) if (saved[id] !== undefined) el(id).value = saved[id];
      recalculate();
    } catch (error) {
      message(`<b>Cannot open that file:</b> ${/** @type {Error} */ (error).message}`, "error");
    }
    input.value = "";                                  // so the same file can be opened again
  };
  reader.readAsText(file);
}

// ---------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------

writeUnitLabels();
for (const id of ALL_IDS) {
  el(id).addEventListener("input", recalculate);
  el(id).addEventListener("change", recalculate);
}
el("sample").addEventListener("change", () => {});
document.getElementById("btn-sample")?.addEventListener("click", loadSample);
document.getElementById("btn-save")?.addEventListener("click", saveCase);
document.getElementById("btn-open")?.addEventListener("click", () => el("file-open").click());
el("file-open").addEventListener("change", openCase);
recalculate();
