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

/**
 * What each numeric box MEASURES.  This one table drives three things: the unit shown on its label,
 * the conversion into engine units when the case is built, and the conversion of the number already
 * typed when the user switches unit system.  A box that is a drop-down, or a pure number with no
 * unit at all (skin, specific gravity, the exponent n), is listed as null so that it is visibly
 * accounted for rather than merely absent.
 * @type {Record<string, import("./units.js").Quantity | null>}
 */
const QUANTITY_OF = {
  fluid_type: null, oil_ipr: null, gas_ipr: null, oil_regime: null, gas_visc: null,
  p_res: "pressure", t_res: "temperature", pb: "pressure",
  pi: "pi",
  vogel_q: "liquidRate", vogel_pwf: "pressure",
  fet_q1: "liquidRate", fet_pwf1: "pressure", fet_q2: "liquidRate", fet_pwf2: "pressure",
  oil_k: "permeability", oil_h: "length", oil_bo: "fvf", oil_mu: "viscosity",
  oil_re: "length", oil_rw: "length", oil_skin: null,
  oil_phi: "fraction", oil_ct: "compressibility", oil_time: "time",
  gas_sg_g: null, y_h2s: "fraction", y_co2: "fraction",
  gas_k: "permeability", gas_h: "length", gas_re: "length", gas_rw: "length",
  gas_skin: null, gas_beta: "inverseLength",
  bp_c: null,            // handled on its own: see switchSystem
  bp_n: null,
};

/**
 * The number the user actually typed into each box, together with the system it was typed in.
 *
 * Why this is kept: switching system rounds the number on screen to something readable (3,000 psig
 * becomes 206.843 barg, not 206.84277941...).  Switching back from that rounded number would give
 * 2,999.996 psig, and flipping back and forth a few times would walk the well away from what was
 * entered.  So the original is remembered, and returning to the system a number was typed in puts
 * that exact number back.  Any edit replaces the memory, because the typed number is then the new
 * original.
 * @type {Record<string, {value: number, system: import("./units.js").System}>}
 */
const TYPED = {};

/** Remember what is in a box as typed by the user, in whatever system is on screen. @param {string} id */
function noteTyped(id) {
  const value = Number(/** @type {HTMLInputElement} */ (el(id)).value);
  if (Number.isFinite(value)) TYPED[id] = { value, system: units.system() };
  else delete TYPED[id];
}

/** Read a box and convert it into the engine's units. @param {string} id */
function eng(id) {
  const quantity = QUANTITY_OF[id];
  return quantity === null ? num(id) : units.toEngine(quantity, num(id));
}

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
  // two labels that cannot come from the table: C carries the exponent n in its unit, and beta
  // carries a note about what 0 means
  const c = el("bp_c_unit");
  if (c) c.textContent = `(${units.backpressureCUnit()})`;
  const b = el("beta_unit");
  if (b) b.textContent = `(${units.unitOf("inverseLength")}, 0 = estimate)`;
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
    const quantity = QUANTITY_OF[id];
    if (quantity === null) continue;
    const node = /** @type {HTMLInputElement} */ (el(id));
    const value = Number(node.value);
    if (!Number.isFinite(value)) continue;
    const typed = TYPED[id] || { value, system: from };
    const converted = typed.system === to ? typed.value : units.convert(quantity, typed.value, typed.system, to);
    node.value = String(Number(converted.toFixed(units.decimalsFor(quantity, converted))));
    // the up/down arrows step in round numbers of the OLD unit, which is meaningless in the new
    // one, so remember the original and let the box take any value while it is converted
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

  units.setSystem(to);
  writeUnitLabels();
  recalculate();
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
  const pRes = eng("p_res");
  const tRes = eng("t_res");
  /** @type {{key: string, value: string}[]} */
  const extra = [];

  if (pick("fluid_type") === "oil") {
    const model = pick("oil_ipr");
    const pb = eng("pb");

    if (model === "pi") {
      return { name: "oil_pi", p_res: pRes, rateUnit: "liquidRate", extra,
               inputs: { pb, J: eng("pi") } };
    }
    if (model === "vogel") {
      const inputs = { pb, q_test: eng("vogel_q"), pwf_test: eng("vogel_pwf") };
      // show the PI the test implies, which is the useful number from a Vogel fit
      const J = ipr.vogel_productivity_index(pRes, pb, inputs.q_test, inputs.pwf_test);
      extra.push({ key: `PI from the test (${units.unitOf("pi")})`, value: units.show(units.fromEngine("pi", J), 2) });
      return { name: "oil_vogel", p_res: pRes, rateUnit: "liquidRate", extra, inputs };
    }
    if (model === "fetkovich") {
      const inputs = { q1: eng("fet_q1"), pwf1: eng("fet_pwf1"),
                       q2: eng("fet_q2"), pwf2: eng("fet_pwf2") };
      const [C, n] = ipr.c_and_n_from_two_tests(pRes, inputs.q1, inputs.pwf1, inputs.q2, inputs.pwf2);
      extra.push({ key: "n from the two tests", value: n.toFixed(3) });
      extra.push({ key: "C from the two tests", value: C.toExponential(3) });
      return { name: "oil_fetkovich", p_res: pRes, rateUnit: "liquidRate", extra, inputs };
    }
    // Darcy, with its three flow regimes
    const regime = pick("oil_regime");
    const inputs = { pb, k: eng("oil_k"), h: eng("oil_h"),
                     bo: eng("oil_bo"), mu: eng("oil_mu"),
                     re: eng("oil_re"), rw: eng("oil_rw"),
                     skin: eng("oil_skin"), regime,
                     phi: regime === "transient" ? eng("oil_phi") : null,
                     ct: regime === "transient" ? eng("oil_ct") : null,
                     time_hours: regime === "transient" ? eng("oil_time") : null };
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
      extra.push({ key: `Transient valid until (${units.unitOf("time")})`,
                   value: units.show(units.fromEngine("time", tEnd), 0) });
    }
    extra.push({ key: `PI from the rock (${units.unitOf("pi")})`, value: units.show(units.fromEngine("pi", J), 3) });
    return { name: "oil_darcy_regime", p_res: pRes, rateUnit: "liquidRate", extra, inputs };
  }

  // ---- gas ----
  const model = pick("gas_ipr");
  const gasSg = num("gas_sg_g");
  if (model === "backpressure") {
    // C is already in engine units if the screen is in oilfield units; in metric it has to be
    // converted back, and that needs n
    const n = num("bp_n");
    const C = units.convertBackpressureC(num("bp_c"), n, units.system(), "field");
    return { name: "gas_backpressure", p_res: pRes, rateUnit: "gasRate", extra, inputs: { C, n } };
  }
  // Darcy and Jones need Z and viscosity.  Exactly as the Python does it, they are evaluated at
  // 75 % of the reservoir pressure (a typical average of Pr and Pwf) and the reservoir temperature.
  const props = pvt.gasProperties(0.75 * pRes, tRes, gasSg, eng("y_h2s"), eng("y_co2"), pick("gas_visc"));
  extra.push({ key: "Z at 0.75 Pr", value: props.z.toFixed(4) });
  extra.push({ key: `Gas viscosity (${units.unitOf("viscosity")})`,
               value: units.fromEngine("viscosity", props.mu_g).toFixed(5) });
  const common = { temp_f: tRes, k: eng("gas_k"), h: eng("gas_h"),
                   mu: props.mu_g, z: props.z,
                   re: eng("gas_re"), rw: eng("gas_rw"), skin: eng("gas_skin") };
  if (model === "darcy") {
    return { name: "gas_darcy", p_res: pRes, rateUnit: "gasRate", extra, inputs: common };
  }
  const beta = num("gas_beta") > 0 ? eng("gas_beta") : null;
  if (beta === null) {
    const estimated = ipr.gas_beta_firoozabadi_katz(common.k);
    extra.push({ key: `beta estimated (${units.unitOf("inverseLength")})`,
                 value: units.fromEngine("inverseLength", estimated).toExponential(3) });
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
  // the samples are written in oilfield units, so they are converted if the screen is in metric
  const to = units.system();
  for (const [id, value] of Object.entries(sample)) {
    const quantity = QUANTITY_OF[id];
    const number = Number(value);
    if (quantity === null || quantity === undefined || !Number.isFinite(number) || to === "field") {
      el(id).value = value;
    } else {
      const converted = units.convert(quantity, number, "field", to);
      el(id).value = String(Number(converted.toFixed(units.decimalsFor(quantity, converted))));
      // the sample's own number, in oilfield units, is the original: so switching to oilfield gives
      // back the round figures the sample was written with
      TYPED[id] = { value: number, system: "field" };
      continue;
    }
    noteTyped(id);
  }
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
  data._unit_system = units.system();        // so the numbers mean the same thing when reopened
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
      // the system first, so the saved numbers are read in the units they were written in
      const savedSystem = units.asSystem(saved._unit_system || "field");
      if (savedSystem !== units.system()) {
        units.setSystem(savedSystem);
        /** @type {HTMLSelectElement} */ (el("unit_system")).value = savedSystem;
        writeUnitLabels();
      }
      for (const id of ALL_IDS) {
        if (saved[id] === undefined) continue;
        el(id).value = saved[id];
        noteTyped(id);          // the saved numbers are now the originals
      }
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
  for (const event of ["input", "change"]) {
    el(id).addEventListener(event, () => { noteTyped(id); recalculate(); });
  }
  noteTyped(id);               // the numbers the page opens with count as typed
}
el("sample").addEventListener("change", () => {});
document.getElementById("btn-sample")?.addEventListener("click", loadSample);
document.getElementById("btn-save")?.addEventListener("click", saveCase);
document.getElementById("btn-open")?.addEventListener("click", () => el("file-open").click());
el("file-open").addEventListener("change", openCase);
el("unit_system").addEventListener("change", (event) => {
  switchSystem(/** @type {HTMLSelectElement} */ (event.target).value);
});
recalculate();
