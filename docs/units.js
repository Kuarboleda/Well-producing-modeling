// @ts-check
/**
 * units.js - the ONE place where what the user types meets what the engine calculates with.
 *
 * The engine (pvt.js, ipr.js and later vlp.js, nodal.js) always works in oilfield units and in
 * ABSOLUTE pressure (psia), exactly like the Python it was translated from.  The screen works in
 * whatever the user picked.  Every conversion lives here, so adding a second unit system later means
 * adding entries to UNIT_SYSTEMS - not touching the engine or the page.
 *
 * Today only field units are offered.  The metric column is written out but not shown yet; when it is
 * wanted, set METRIC_READY to true and the selector appears.  The point of doing it this way now is
 * that the page never holds a raw number without knowing what it is.
 */

export const ATM_PSI = 14.7;        // one atmosphere, in psi

/** A quantity the page knows how to show and convert. Each gives the label and the maths per system. */
export const QUANTITIES = {
  // gauge pressure: the user types psig, the engine wants psia
  pressure: {
    field: { unit: "psig", toEngine: (v) => v + ATM_PSI, fromEngine: (p) => p - ATM_PSI },
    metric: { unit: "barg", toEngine: (v) => v * 14.5037738 + ATM_PSI, fromEngine: (p) => (p - ATM_PSI) / 14.5037738 },
  },
  // a pressure DIFFERENCE or a slope: no atmosphere to add
  pressureDiff: {
    field: { unit: "psi", toEngine: (v) => v, fromEngine: (p) => p },
    metric: { unit: "bar", toEngine: (v) => v * 14.5037738, fromEngine: (p) => p / 14.5037738 },
  },
  temperature: {
    field: { unit: "degF", toEngine: (v) => v, fromEngine: (t) => t },
    metric: { unit: "degC", toEngine: (v) => v * 9 / 5 + 32, fromEngine: (t) => (t - 32) * 5 / 9 },
  },
  length: {
    field: { unit: "ft", toEngine: (v) => v, fromEngine: (x) => x },
    metric: { unit: "m", toEngine: (v) => v / 0.3048, fromEngine: (x) => x * 0.3048 },
  },
  liquidRate: {
    field: { unit: "STB/d", toEngine: (v) => v, fromEngine: (q) => q },
    metric: { unit: "m3/d", toEngine: (v) => v / 0.1589873, fromEngine: (q) => q * 0.1589873 },
  },
  gasRate: {
    field: { unit: "Mscf/d", toEngine: (v) => v, fromEngine: (q) => q },
    metric: { unit: "e3m3/d", toEngine: (v) => v / 0.0283168, fromEngine: (q) => q * 0.0283168 },
  },
  pi: {   // productivity index
    field: { unit: "STB/d/psi", toEngine: (v) => v, fromEngine: (j) => j },
    metric: { unit: "m3/d/bar", toEngine: (v) => v * 14.5037738 / 6.2898106, fromEngine: (j) => j * 6.2898106 / 14.5037738 },
  },
};

export const METRIC_READY = false;         // flip to true when the metric column has been checked
let current = "field";

/** The unit system in use ("field" or "metric"). */
export function system() {
  return current;
}

/** Change the unit system. @param {string} name */
export function setSystem(name) {
  if (!(name === "field" || name === "metric")) throw new Error(`Unknown unit system: ${name}`);
  current = name;
}

/** The unit text for a quantity, for a label. @param {keyof typeof QUANTITIES} quantity */
export function unitOf(quantity) {
  return QUANTITIES[quantity][current].unit;
}

/** What the user typed -> what the engine needs. @param {keyof typeof QUANTITIES} quantity @param {number} value */
export function toEngine(quantity, value) {
  return QUANTITIES[quantity][current].toEngine(value);
}

/** What the engine gave -> what the screen shows. @param {keyof typeof QUANTITIES} quantity @param {number} value */
export function fromEngine(quantity, value) {
  return QUANTITIES[quantity][current].fromEngine(value);
}

/**
 * A number formatted for reading: thousands separated, sensible decimals.
 * @param {number} value @param {number} [decimals]
 */
export function show(value, decimals = 0) {
  if (!Number.isFinite(value)) return "-";
  return value.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
