// @ts-check
/**
 * units.js - the ONE place where what the user types meets what the engine calculates with.
 *
 * The engine (pvt.js, ipr.js, vlp.js and later nodal.js) always works in OILFIELD units and in
 * ABSOLUTE pressure (psia), exactly like the Python it was translated from.  The screen works in
 * whatever system the user picked.  Every conversion lives here, so the engine never learns that
 * metric exists.
 *
 * Two systems are offered:
 *   field  - psig, degF, ft, STB/d, Mscf/d   (the default)
 *   metric - barg, degC, m,  m3/d,  e3m3/d
 *
 * Some quantities carry the same NUMBER in both systems but a different NAME, and they are listed
 * here all the same so the screen shows the right name: viscosity (1 cP = 1 mPa.s), formation
 * volume factor (a ratio either way), surface tension (1 dyne/cm = 1 mN/m), permeability (mD is
 * used worldwide), and anything dimensionless.  Writing them out costs nothing and stops someone
 * later assuming a quantity was forgotten.
 */

export const ATM_PSI = 14.7;        // one atmosphere, in psi

/** The two unit systems. @typedef {"field" | "metric"} System */
/** How one quantity is named and converted in one system.
 *  @typedef {{ unit: string, toEngine: (v: number) => number, fromEngine: (v: number) => number }} UnitSpec */
/** @typedef {{ field: UnitSpec, metric: UnitSpec }} QuantitySpec */

// Conversion constants, each written once and named, so no bare number appears twice below.
const PSI_PER_BAR = 14.5037738;
const FT_PER_M = 1 / 0.3048;                    // 3.28084
const STB_PER_M3 = 6.2898106;
const MSCF_PER_E3M3 = 1 / 0.0283168;            // 35.3147
const SCF_PER_STB_PER_SM3_PER_M3 = 5.6145833;   // 1 m3/m3 = 5.6146 scf/STB
const LB_FT3_PER_KG_M3 = 1 / 16.018463;

/** One quantity: how it is named and converted in each system.
 *  @satisfies {Record<string, QuantitySpec>} */
export const QUANTITIES = {
  // ---- pressure: GAUGE on screen, ABSOLUTE in the engine -------------
  pressure: {
    field: { unit: "psig", toEngine: (v) => v + ATM_PSI, fromEngine: (p) => p - ATM_PSI },
    metric: { unit: "barg", toEngine: (v) => v * PSI_PER_BAR + ATM_PSI, fromEngine: (p) => (p - ATM_PSI) / PSI_PER_BAR },
  },
  // a pressure DIFFERENCE or a slope: no atmosphere to add
  pressureDiff: {
    field: { unit: "psi", toEngine: (v) => v, fromEngine: (p) => p },
    metric: { unit: "bar", toEngine: (v) => v * PSI_PER_BAR, fromEngine: (p) => p / PSI_PER_BAR },
  },
  temperature: {
    field: { unit: "degF", toEngine: (v) => v, fromEngine: (t) => t },
    metric: { unit: "degC", toEngine: (v) => v * 9 / 5 + 32, fromEngine: (t) => (t - 32) * 5 / 9 },
  },
  length: {
    field: { unit: "ft", toEngine: (v) => v, fromEngine: (x) => x },
    metric: { unit: "m", toEngine: (v) => v * FT_PER_M, fromEngine: (x) => x / FT_PER_M },
  },
  liquidRate: {
    field: { unit: "STB/d", toEngine: (v) => v, fromEngine: (q) => q },
    metric: { unit: "m3/d", toEngine: (v) => v * STB_PER_M3, fromEngine: (q) => q / STB_PER_M3 },
  },
  gasRate: {
    field: { unit: "Mscf/d", toEngine: (v) => v, fromEngine: (q) => q },
    metric: { unit: "e3m3/d", toEngine: (v) => v * MSCF_PER_E3M3, fromEngine: (q) => q / MSCF_PER_E3M3 },
  },
  // productivity index = liquid rate per unit pressure DIFFERENCE
  pi: {
    field: { unit: "STB/d/psi", toEngine: (v) => v, fromEngine: (j) => j },
    metric: { unit: "m3/d/bar",
              toEngine: (v) => v * STB_PER_M3 / PSI_PER_BAR,
              fromEngine: (j) => j * PSI_PER_BAR / STB_PER_M3 },
  },
  gor: {
    field: { unit: "scf/STB", toEngine: (v) => v, fromEngine: (r) => r },
    metric: { unit: "m3/m3",
              toEngine: (v) => v * SCF_PER_STB_PER_SM3_PER_M3,
              fromEngine: (r) => r / SCF_PER_STB_PER_SM3_PER_M3 },
  },
  density: {
    field: { unit: "lb/ft3", toEngine: (v) => v, fromEngine: (d) => d },
    metric: { unit: "kg/m3", toEngine: (v) => v * LB_FT3_PER_KG_M3, fromEngine: (d) => d / LB_FT3_PER_KG_M3 },
  },
  // 1 / length, used by the Jones turbulence coefficient beta.  Like compressibility it converts
  // the other way round from the quantity it is built on.
  inverseLength: {
    field: { unit: "1/ft", toEngine: (v) => v, fromEngine: (b) => b },
    metric: { unit: "1/m", toEngine: (v) => v / FT_PER_M, fromEngine: (b) => b * FT_PER_M },
  },
  // compressibility = 1 / pressure difference, so it converts the other way round
  compressibility: {
    field: { unit: "1/psi", toEngine: (v) => v, fromEngine: (c) => c },
    metric: { unit: "1/bar", toEngine: (v) => v / PSI_PER_BAR, fromEngine: (c) => c * PSI_PER_BAR },
  },

  // ---- the same number in both systems, but a different name ---------
  permeability: {    // millidarcy is used worldwide
    field: { unit: "md", toEngine: (v) => v, fromEngine: (k) => k },
    metric: { unit: "md", toEngine: (v) => v, fromEngine: (k) => k },
  },
  viscosity: {       // 1 cP = 1 mPa.s exactly
    field: { unit: "cP", toEngine: (v) => v, fromEngine: (m) => m },
    metric: { unit: "mPa.s", toEngine: (v) => v, fromEngine: (m) => m },
  },
  fvf: {             // formation volume factor: a ratio of volumes either way
    field: { unit: "rb/STB", toEngine: (v) => v, fromEngine: (b) => b },
    metric: { unit: "m3/m3", toEngine: (v) => v, fromEngine: (b) => b },
  },
  surfaceTension: {  // 1 dyne/cm = 1 mN/m exactly
    field: { unit: "dyne/cm", toEngine: (v) => v, fromEngine: (s) => s },
    metric: { unit: "mN/m", toEngine: (v) => v, fromEngine: (s) => s },
  },
  time: {
    field: { unit: "h", toEngine: (v) => v, fromEngine: (t) => t },
    metric: { unit: "h", toEngine: (v) => v, fromEngine: (t) => t },
  },
  fraction: {        // porosity, water cut, mole fractions: dimensionless
    field: { unit: "fraction", toEngine: (v) => v, fromEngine: (x) => x },
    metric: { unit: "fraction", toEngine: (v) => v, fromEngine: (x) => x },
  },
};

/** @typedef {keyof typeof QUANTITIES} Quantity */

export const SYSTEMS = /** @type {System[]} */ (["field", "metric"]);
export const SYSTEM_NAMES = { field: "Oilfield", metric: "Metric" };

/** @type {System} */
let current = "field";             // oilfield is the default

/** The unit system in use ("field" or "metric"). */
export function system() {
  return current;
}

/**
 * Check that a name really is one of the two systems, and hand it back as one.  Used wherever a
 * system name arrives as plain text - from the drop-down, or from a saved case file.
 * @param {string} name @returns {System}
 */
export function asSystem(name) {
  if (name !== "field" && name !== "metric") throw new Error(`Unknown unit system: ${name}`);
  return name;
}

/** Change the unit system. @param {string} name */
export function setSystem(name) {
  current = asSystem(name);
}

/** The unit text for a quantity, for a label. @param {Quantity} quantity @param {System} [inSystem] */
export function unitOf(quantity, inSystem) {
  return QUANTITIES[quantity][inSystem || current].unit;
}

/** What the user typed -> what the engine needs. @param {Quantity} quantity @param {number} value @param {System} [inSystem] */
export function toEngine(quantity, value, inSystem) {
  return QUANTITIES[quantity][inSystem || current].toEngine(value);
}

/** What the engine gave -> what the screen shows. @param {Quantity} quantity @param {number} value @param {System} [inSystem] */
export function fromEngine(quantity, value, inSystem) {
  return QUANTITIES[quantity][inSystem || current].fromEngine(value);
}

/**
 * The same physical amount, re-expressed from one system into another.  Used when the user switches
 * system: every box is converted so the well does not change, only the units it is written in.
 * @param {Quantity} quantity @param {number} value @param {System} from @param {System} to
 */
export function convert(quantity, value, from, to) {
  if (from === to) return value;
  return fromEngine(quantity, toEngine(quantity, value, from), to);
}

/**
 * The back-pressure coefficient C is the awkward one: q = C (Pr^2 - Pwf^2)^n, so its unit is
 * [rate] / [pressure^2]^n and it depends on n itself.  Converting it needs n, which is why it
 * cannot live in the table above.  The pressures in that equation are ABSOLUTE, so only the scale
 * of the pressure unit matters here, not the atmosphere offset.
 * @param {number} C @param {number} n @param {System} from @param {System} to
 */
export function convertBackpressureC(C, n, from, to) {
  if (from === to) return C;
  const rateFactor = fromEngine("gasRate", toEngine("gasRate", 1.0, from), to);   // 1 unit of "from" rate, in "to" rate
  const pressureFactor = from === "field" ? 1.0 / PSI_PER_BAR : PSI_PER_BAR;      // 1 unit of "from" pressure, in "to"
  return C * rateFactor / pressureFactor ** (2.0 * n);
}

/**
 * The unit text for the back-pressure coefficient C, which has no fixed name because the exponent
 * n sits in it: q = C (Pr^2 - Pwf^2)^n.  Written out for a label.
 * @param {System} [inSystem]
 */
export function backpressureCUnit(inSystem) {
  const sys = inSystem || current;
  const rate = QUANTITIES.gasRate[sys].unit;
  const press = sys === "field" ? "psia" : "bara";
  return `${rate} / ${press}^2n`;
}

/**
 * A number formatted for reading: thousands separated, sensible decimals.
 * @param {number} value @param {number} [decimals]
 */
export function show(value, decimals = 0) {
  if (!Number.isFinite(value)) return "-";
  return value.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/**
 * How many decimals a box should keep when the system is switched, so that the well is not quietly
 * rounded away (3,000 psig is 206.84 barg, not 207).
 * @param {Quantity} quantity @param {number} value
 */
export function decimalsFor(quantity, value) {
  if (quantity === "compressibility") return 10;
  const size = Math.abs(value);
  if (size === 0) return 0;
  if (size >= 1000) return 2;
  if (size >= 10) return 3;
  if (size >= 1) return 4;
  return Math.min(12, 4 + Math.ceil(-Math.log10(size)));
}
