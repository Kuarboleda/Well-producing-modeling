// @ts-check
/**
 * vlp.js - Vertical Lift Performance: the tubing side, translated from vlp.py.
 *
 * Being written in stages, each one cross-checked against the Python before the next begins.
 * Done so far: the friction factor, surface tension, Beggs and Brill (1973),
 * Hagedorn and Brown (1965), Gray (1974), Orkiszewski (1967), Duns and Ros (1963)
 * Ansari et al. (1994), Mukherjee and Brill (1983/1985) and Fancher and Brown (1963)
 * - all eight correlations - the fluid objects, and the pressure traverse that walks a
 * gradient from the wellhead down to the perforations.
 *
 * Every function keeps the same name and the same argument order as the Python, so
 * tools/crosscheck.mjs can call both with one list of numbers.
 *
 * Units: pressure psia | length ft | velocity ft/s | density lb/ft3 | viscosity cP
 *        surface tension dyne/cm | diameter and roughness in | angle degrees from horizontal
 */

import * as pvt from "./pvt.js";
import { buildSteps, fluidTemperatures } from "./well.js";

/** @typedef {import("./well.js").Well} Well */
/** @typedef {import("./well.js").Step} Step */

export const GC = 32.174;            // gravitational constant, lbm ft / (lbf s2). Also g in ft/s2 (g/gc = 1).
export const RE_CONST = 1488.16;     // Reynolds number = 1488.16 * rho(lb/ft3) * v(ft/s) * d(ft) / mu(cP)
export const GAS_RHO_SC = 0.0764;    // lb/scf: gas density of gravity 1.0 at standard conditions
export const OIL_CP = 0.5;           // heat capacities (Btu/lb/degF) used for the temperature profile
export const GAS_CP = 0.5;
export const WATER_CP = 1.0;

/** Stop with a clear error message if an input does not make sense. @param {boolean} condition @param {string} message */
function check(condition, message) {
  if (!condition) throw new Error(message);
}

/** Degrees to radians (Python's math.radians). @param {number} deg */
function radians(deg) {
  return deg * Math.PI / 180.0;
}

/**
 * @typedef {{v_sl: number, v_sg: number, rho_l: number, rho_g: number, mu_l: number,
 *            mu_g: number, sigma: number, frac_w: number, glr: number}} FlowConditions
 * The flow conditions at one point in the tubing, as the fluid objects produce them:
 * superficial liquid and gas velocity (ft/s), liquid and gas density (lb/ft3), liquid and gas
 * viscosity (cP), surface tension (dyne/cm), the water fraction of the liquid, and the producing
 * gas-liquid ratio (scf per STB of liquid).
 */

// =====================================================================
// Friction factor
// =====================================================================

/**
 * Turbulent (Darcy) friction factor from the Colebrook equation, solved by repeating.
 * Swamee-Jain gives a good first guess, then Colebrook is iterated.
 * @param {number} re @param {number} eps_over_d
 */
function colebrook(re, eps_over_d) {
  const f0 = 0.25 / Math.log10(eps_over_d / 3.7 + 5.74 / re ** 0.9) ** 2;
  let x = 1.0 / Math.sqrt(f0);                      // x = 1/sqrt(f)
  for (let i = 0; i < 50; i++) {
    const xNew = -2.0 * Math.log10(eps_over_d / 3.7 + 2.51 * x / re);
    if (Math.abs(xNew - x) < 1e-10) { x = xNew; break; }
    x = xNew;
  }
  return 1.0 / x ** 2;
}

/**
 * Darcy (Moody) friction factor.
 *   re < 2100        : laminar, f = 64 / Re
 *   2100 <= re < 4000: straight-line blend between laminar and turbulent (no jump)
 *   re >= 4000       : Colebrook (eps_over_d = roughness / diameter)
 * @param {number} re @param {number} [eps_over_d]
 */
export function friction_factor(re, eps_over_d = 0.0) {
  check(re > 0, "Reynolds number must be > 0.");
  if (re < 2100.0) return 64.0 / re;
  if (re >= 4000.0) return colebrook(re, eps_over_d);
  const fLam = 64.0 / 2100.0;
  const fTurb = colebrook(4000.0, eps_over_d);
  return fLam + (fTurb - fLam) * (re - 2100.0) / (4000.0 - 2100.0);
}

// =====================================================================
// Surface tension (dyne/cm) - needed for the liquid velocity number
// =====================================================================

/**
 * Oil / gas surface tension (Baker and Swerdloff): the dead-oil value at 68 and 100 degF,
 * straight-line in T between them, then reduced for dissolved gas at pressure p.
 * Never allowed below 1 dyne/cm.
 * @param {number} api @param {number} T @param {number} p
 */
export function sigma_oil_gas(api, T, p) {
  const s68 = 39.0 - 0.2571 * api;
  const s100 = 37.5 - 0.2571 * api;
  const t = Math.min(Math.max(T, 68.0), 100.0);
  const sigmaDead = s68 + (s100 - s68) * (t - 68.0) / 32.0;
  const factor = Math.max(1.0 - 0.024 * p ** 0.45, 0.0);
  return Math.max(sigmaDead * factor, 1.0);
}

/**
 * Water / gas surface tension (Hough / Baker): values at 74 and 280 degF,
 * straight-line in T between them.
 * @param {number} T @param {number} p
 */
export function sigma_water_gas(T, p) {
  const s74 = 75.0 - 1.108 * p ** 0.349;
  const s280 = 53.0 - 0.1048 * p ** 0.637;
  const t = Math.min(Math.max(T, 74.0), 280.0);
  return Math.max(s74 + (s280 - s74) * (t - 74.0) / 206.0, 1.0);
}

// =====================================================================
// Beggs and Brill (1973) - works for any angle: vertical, deviated, horizontal
// =====================================================================
// Idea: first find which flow pattern WOULD exist if the pipe were horizontal, use it to get the
// liquid holdup (the fraction of the pipe cross-section filled with liquid), correct the holdup for
// the pipe angle, then add the friction and gravity pressure gradients.

/** Horizontal holdup constants:  HL(0) = a * lambda^b / NFr^c  @type {Record<string, number[]>} */
const BB_HORIZONTAL = {
  segregated: [0.98, 0.4846, 0.0868],
  intermittent: [0.845, 0.5351, 0.0173],
  distributed: [1.065, 0.5824, 0.0609],
};

/** Inclination constants:  C = (1 - lambda) * ln( d * lambda^e * NLv^f * NFr^g ) @type {Record<string, number[]>} */
const BB_UPHILL = {
  segregated: [0.011, -3.768, 3.539, -1.614],
  intermittent: [2.96, 0.305, -0.4473, 0.0978],
};
const BB_DOWNHILL = [4.70, -0.3692, 0.1244, -0.5056];     // all flow patterns

/**
 * The four flow-pattern boundaries L1..L4 (they depend on the no-slip liquid fraction).
 * @param {number} lam @returns {[number, number, number, number]}
 */
function bbLimits(lam) {
  return [316.0 * lam ** 0.302, 0.0009252 * lam ** -2.4684, 0.10 * lam ** -1.4516, 0.5 * lam ** -6.738];
}

/**
 * Horizontal flow pattern: 'segregated', 'transition', 'intermittent' or 'distributed'.
 * lam = no-slip liquid fraction, n_fr = mixture Froude number.
 * @param {number} lam @param {number} n_fr
 */
function bbFlowRegime(lam, n_fr) {
  const [l1, l2, l3, l4] = bbLimits(lam);
  if ((lam < 0.01 && n_fr < l1) || (lam >= 0.01 && n_fr < l2)) return "segregated";
  if (lam >= 0.01 && l2 <= n_fr && n_fr <= l3) return "transition";
  if ((0.01 <= lam && lam < 0.4 && l3 < n_fr && n_fr <= l1)
      || (lam >= 0.4 && l3 < n_fr && n_fr <= l4)) return "intermittent";
  return "distributed";
}

/** Liquid velocity number  NLv = 1.938 * v_sl * (rho_l / sigma)^0.25. @param {number} v_sl @param {number} rho_l @param {number} sigma */
function bbNlv(v_sl, rho_l, sigma) {
  return 1.938 * v_sl * (rho_l / sigma) ** 0.25;
}

/** Liquid holdup if the pipe were horizontal (never less than the no-slip value). @param {string} regime @param {number} lam @param {number} n_fr */
function bbHorizontalHoldup(regime, lam, n_fr) {
  const [a, b, c] = BB_HORIZONTAL[regime];
  return Math.max(a * lam ** b / n_fr ** c, lam);
}

/**
 * The factor C used in the holdup correction for pipe angle (never negative).
 * @param {string} regime @param {number} lam @param {number} n_lv @param {number} n_fr @param {number} theta_rad
 */
function bbInclinationC(regime, lam, n_lv, n_fr, theta_rad) {
  let d, e, f, g;
  if (theta_rad > 0) {                               // flow uphill
    if (regime === "distributed") return 0.0;        // no correction for distributed uphill
    [d, e, f, g] = BB_UPHILL[regime];
  } else if (theta_rad < 0) {                        // flow downhill
    [d, e, f, g] = BB_DOWNHILL;
  } else {                                           // horizontal
    return 0.0;
  }
  const c = (1.0 - lam) * Math.log(d * lam ** e * n_lv ** f * n_fr ** g);
  return Math.max(c, 0.0);
}

/**
 * Liquid holdup at the real pipe angle for ONE flow pattern.
 * @param {string} regime @param {number} lam @param {number} n_fr @param {number} n_lv @param {number} theta_rad
 */
function bbHoldupOneRegime(regime, lam, n_fr, n_lv, theta_rad) {
  const hl0 = bbHorizontalHoldup(regime, lam, n_fr);
  const c = bbInclinationC(regime, lam, n_lv, n_fr, theta_rad);
  const s = Math.sin(1.8 * theta_rad);
  const psi = 1.0 + c * (s - s ** 3 / 3.0);          // inclination correction factor
  return Math.min(hl0 * psi, 1.0);
}

/**
 * Flow pattern and liquid holdup at the real pipe angle (for 0 < lam < 1).
 * In the transition pattern the holdup is a blend of the segregated and intermittent values.
 * @param {number} lam @param {number} n_fr @param {number} n_lv @param {number} theta_rad
 * @returns {[string, number]}
 */
function bbHoldup(lam, n_fr, n_lv, theta_rad) {
  const regime = bbFlowRegime(lam, n_fr);
  if (regime === "transition") {
    const [, l2, l3] = bbLimits(lam);
    const a = (l3 - n_fr) / (l3 - l2);               // a = 1 at L2 (segregated), 0 at L3 (intermittent)
    const hl = a * bbHoldupOneRegime("segregated", lam, n_fr, n_lv, theta_rad)
             + (1.0 - a) * bbHoldupOneRegime("intermittent", lam, n_fr, n_lv, theta_rad);
    return [regime, hl];
  }
  return [regime, bbHoldupOneRegime(regime, lam, n_fr, n_lv, theta_rad)];
}

/**
 * Beggs and Brill pressure gradient in psi per ft of pipe length.  Positive means the pressure at
 * the bottom of the step is higher than at the top (the pressure the well must supply to push the
 * fluid up).
 *
 * @param {number} p pressure (psia)
 * @param {number} angle_deg pipe angle from horizontal in the flow direction (90 = vertical up)
 * @param {number} d_in pipe inner diameter (in)
 * @param {number} roughness_in pipe wall roughness (in)
 * @param {FlowConditions} c flow conditions at this point
 * @returns {{dpdl: number, hl: number, regime: string, hydrostatic: number, friction: number,
 *            f_tp: number, re: number, e_k: number}}
 */
export function beggs_brill_gradient(p, angle_deg, d_in, roughness_in, c) {
  check(p > 0 && d_in > 0, "Pressure and diameter must be > 0.");
  const d_ft = d_in / 12.0;
  const v_sl = c.v_sl, v_sg = c.v_sg;
  const v_m = v_sl + v_sg;                            // mixture velocity
  check(v_m > 0, "No flow: mixture velocity is zero.");
  let lam = v_sl / v_m;                               // no-slip liquid fraction
  const theta = radians(angle_deg);

  // ---- liquid holdup ------------------------------------------------
  let regime, hl;
  if (lam < 1e-8) {                                   // gas only
    regime = "gas"; hl = 0.0; lam = 0.0;
  } else if (lam > 1.0 - 1e-8) {                      // liquid only
    regime = "liquid"; hl = 1.0; lam = 1.0;
  } else {
    const n_fr = v_m ** 2 / (GC * d_ft);              // Froude number
    const n_lv = bbNlv(v_sl, c.rho_l, c.sigma);
    [regime, hl] = bbHoldup(lam, n_fr, n_lv, theta);
  }

  // ---- densities and viscosity --------------------------------------
  const rho_ns = c.rho_l * lam + c.rho_g * (1.0 - lam);       // no-slip mixture density
  const mu_ns = c.mu_l * lam + c.mu_g * (1.0 - lam);          // no-slip mixture viscosity
  const rho_s = c.rho_l * hl + c.rho_g * (1.0 - hl);          // in-situ (slip) density

  // ---- friction -----------------------------------------------------
  const re_ns = RE_CONST * rho_ns * v_m * d_ft / mu_ns;
  const f_n = friction_factor(re_ns, roughness_in / d_in);    // no-slip friction factor
  let f_tp;
  if (0.0 < lam && lam < 1.0) {
    const y = lam / hl ** 2;
    let s_exp;
    if (1.0 < y && y < 1.2) {
      s_exp = Math.log(2.2 * y - 1.2);
    } else {
      const ln_y = Math.log(y);
      s_exp = ln_y / (-0.0523 + 3.182 * ln_y - 0.8725 * ln_y ** 2 + 0.01853 * ln_y ** 4);
    }
    f_tp = f_n * Math.exp(s_exp);                             // two-phase friction factor
  } else {
    f_tp = f_n;
  }

  const hydrostatic = rho_s * Math.sin(theta) / 144.0;        // psi/ft
  const friction = f_tp * rho_ns * v_m ** 2 / (2.0 * GC * d_ft) / 144.0;

  // ---- acceleration term and total ---------------------------------
  const e_k = Math.min(rho_s * v_m * v_sg / (GC * p * 144.0), 0.95);
  const dpdl = (hydrostatic + friction) / (1.0 - e_k);
  return { dpdl, hl, regime, hydrostatic, friction, f_tp, re: re_ns, e_k };
}


// =====================================================================
// Hagedorn and Brown (1965) with the Griffith bubble-flow correction
// =====================================================================
// Hagedorn and Brown measured pressures in a 1500 ft vertical well and found the liquid holdup
// (fraction of the pipe filled with liquid) from three CHARTS built from four dimensionless numbers
// (the Duns and Ros numbers).  Reading charts by eye does not work in a program, so the three charts
// are replaced here by published curve fits (the same ones used in Brill and Mukherjee's book):
//     chart 1:  N_L   -> CN_L      (viscosity coefficient)
//     chart 2:  H     -> HL/psi    (holdup before correction)
//     chart 3:  B     -> psi       (correction factor)
//     holdup  = (HL/psi) * psi
// It is a VERTICAL-flow correlation: the angle is only used for the hydrostatic term (sin of the
// angle), so use it with care in strongly deviated or horizontal sections.  Two well-known
// modifications are included:
//   * Griffith bubble flow: when there is very little gas (gas fraction below LB) the holdup comes
//     from Griffith's slip equation (slip velocity 0.8 ft/s).
//   * The holdup is never allowed below the no-slip liquid fraction (liquid cannot travel slower
//     than the gas) and never above 1.

export const HB_SLIP_VELOCITY = 0.8;      // Griffith bubble-flow slip velocity, ft/s
export const HB_PATM = 14.7;              // psia, used in the pressure ratio of the holdup group
export const HB_LOW_H = 1.0e-5;           // below this the paper's chart is used instead of the fit

/**
 * Chart 1 (Fig. 12 of the paper): viscosity coefficient CN_L from the liquid viscosity number N_L.
 * The paper's Fig. 12 ends at N_L = 0.5 (CN_L about 0.011) and is flat there; the cubic fit would
 * keep rising beyond it (0.021 at N_L = 1), so N_L is held at 0.5 for very viscous liquids.
 * @param {number} n_l
 */
export function hb_cn_l(n_l) {
  n_l = Math.min(Math.max(n_l, 0.0), 0.5);
  return 0.061 * n_l ** 3 - 0.0929 * n_l ** 2 + 0.0505 * n_l + 0.0019;
}

/** The published curve fit behind chart 2. @param {number} h */
function hbFit(h) {
  const top = 0.0047 + 1123.32 * h + 729489.64 * h ** 2;
  const bottom = 1.0 + 1097.1566 * h + 722153.97 * h ** 2;
  return Math.sqrt(top / bottom);
}

/**
 * Chart 2: HL/psi from the group H.  Goes from 0 (H = 0) up to 1 (H large).
 * The published curve fit (Brill and Mukherjee) is good for H above 1e-5 but flattens to 0.07 as
 * H -> 0, while the chart in the paper keeps falling (0.01 at H = 1e-7).  That floor would put 7 %
 * liquid in a wet-gas well that carries almost none, so below H = 1e-5 the curve follows the
 * chart's slope (about H^0.55) instead.
 * @param {number} h
 */
export function hb_holdup_over_psi(h) {
  h = Math.max(h, 0.0);
  if (h < HB_LOW_H) return hbFit(HB_LOW_H) * (h / HB_LOW_H) ** 0.55;
  return hbFit(h);
}

/**
 * Chart 3: secondary correction factor psi from the group B.  Starts at 1 and grows to about 1.8
 * as the gas velocity number grows (three straight/curved pieces).
 * @param {number} b
 */
export function hb_psi(b) {
  b = Math.max(b, 0.0);
  if (b <= 0.025) return 27170.0 * b ** 3 - 317.52 * b ** 2 + 0.5472 * b + 0.9999;
  if (b <= 0.055) return -533.33 * b ** 2 + 58.524 * b + 0.1171;
  return 2.5714 * b + 1.5962;
}

/**
 * The four dimensionless numbers and the two chart groups H and B.
 * @param {number} p @param {number} d_ft @param {FlowConditions} c
 * @returns {{n_lv: number, n_gv: number, n_d: number, n_l: number, cn_l: number, h: number, b: number}}
 */
export function hb_numbers(p, d_ft, c) {
  const root4 = (c.rho_l / c.sigma) ** 0.25;
  const n_lv = 1.938 * c.v_sl * root4;                             // liquid velocity number
  const n_gv = 1.938 * c.v_sg * root4;                             // gas velocity number
  const n_d = 120.872 * d_ft * (c.rho_l / c.sigma) ** 0.5;         // pipe diameter number
  const n_l = 0.15726 * c.mu_l * (1.0 / (c.rho_l * c.sigma ** 3)) ** 0.25;   // liquid viscosity number
  const cn_l = hb_cn_l(n_l);
  const h = n_lv / n_gv ** 0.575 * (p / HB_PATM) ** 0.1 * cn_l / n_d;
  const b = n_gv * n_lv ** 0.38 / n_d ** 2.14;
  return { n_lv, n_gv, n_d, n_l, cn_l, h, b };
}

/**
 * Griffith bubble-flow liquid holdup:
 *   HL = 1 - 0.5 * (1 + vm/vs - sqrt((1 + vm/vs)^2 - 4 vsg/vs))
 * @param {number} v_m @param {number} v_sg
 */
export function griffith_bubble_holdup(v_m, v_sg) {
  const x = 1.0 + v_m / HB_SLIP_VELOCITY;
  return 1.0 - 0.5 * (x - Math.sqrt(Math.max(x * x - 4.0 * v_sg / HB_SLIP_VELOCITY, 0.0)));
}

/**
 * Hagedorn and Brown pressure gradient (psi per ft of pipe), same inputs and same kind of result as
 * beggs_brill_gradient (see there for the meaning of the inputs).
 * 'regime' is 'hagedorn', 'bubble', 'liquid' or 'gas'.
 * @param {number} p @param {number} angle_deg @param {number} d_in @param {number} roughness_in
 * @param {FlowConditions} c
 * @returns {{dpdl: number, hl: number, regime: string, hydrostatic: number, friction: number,
 *            f_tp: number, re: number, e_k: number}}
 */
export function hagedorn_brown_gradient(p, angle_deg, d_in, roughness_in, c) {
  check(p > 0 && d_in > 0, "Pressure and diameter must be > 0.");
  const d_ft = d_in / 12.0;
  const v_sl = c.v_sl, v_sg = c.v_sg;
  const v_m = v_sl + v_sg;                            // mixture velocity
  check(v_m > 0, "No flow: mixture velocity is zero.");
  let lam = v_sl / v_m;                               // no-slip liquid fraction
  const theta = radians(angle_deg);
  const rho_l = c.rho_l, rho_g = c.rho_g, mu_l = c.mu_l, mu_g = c.mu_g;

  // ---- liquid holdup ------------------------------------------------
  let regime, hl;
  if (lam < 1e-8) {                                   // gas only
    regime = "gas"; hl = 0.0; lam = 0.0;
  } else if (lam > 1.0 - 1e-8) {                      // liquid only
    regime = "liquid"; hl = 1.0; lam = 1.0;
  } else {
    const lb = Math.max(1.071 - 0.2218 * v_m ** 2 / d_ft, 0.13);   // Griffith bubble-flow limit
    if (v_sg / v_m < lb) {
      regime = "bubble";
      hl = griffith_bubble_holdup(v_m, v_sg);
    } else {
      regime = "hagedorn";
      const num = hb_numbers(p, d_ft, c);
      hl = hb_holdup_over_psi(num.h) * hb_psi(num.b);
    }
    hl = Math.min(Math.max(hl, lam), 1.0);            // never below no-slip, never above 1
  }

  // ---- densities ----------------------------------------------------
  const rho_ns = rho_l * lam + rho_g * (1.0 - lam);   // no-slip mixture density
  const rho_s = rho_l * hl + rho_g * (1.0 - hl);      // in-situ (slip) density

  // ---- friction -----------------------------------------------------
  let re, f, friction;
  if (regime === "bubble") {
    // Bubble flow: the liquid fills the pipe, so friction is that of the liquid moving at its
    // true (in-situ) velocity.
    const v_l = v_sl / hl;
    re = RE_CONST * rho_l * v_l * d_ft / mu_l;
    f = friction_factor(re, roughness_in / d_in);
    friction = f * rho_l * v_l ** 2 / (2.0 * GC * d_ft) / 144.0;
  } else {
    // Original Hagedorn and Brown: viscosity weighted by the holdup, and the friction term uses
    // rho_ns^2 / rho_s.
    const mu_s = mu_l ** hl * mu_g ** (1.0 - hl);
    re = RE_CONST * rho_ns * v_m * d_ft / mu_s;
    f = friction_factor(re, roughness_in / d_in);
    friction = f * rho_ns ** 2 * v_m ** 2 / (2.0 * GC * d_ft * rho_s) / 144.0;
  }

  const hydrostatic = rho_s * Math.sin(theta) / 144.0;   // psi/ft

  // ---- acceleration term and total (same form as in Beggs and Brill) ----
  const e_k = Math.min(rho_s * v_m * v_sg / (GC * p * 144.0), 0.95);
  const dpdl = (hydrostatic + friction) / (1.0 - e_k);
  return { dpdl, hl, regime, hydrostatic, friction, f_tp: f, re, e_k };
}

// =====================================================================
// Gray (1974, API 14B) - vertical GAS wells that also make a little liquid
// =====================================================================
// Made for lean gas-condensate and wet-gas wells, where the liquid travels as a mist or a thin
// film.  Two ideas:
//   * the liquid holdup comes from one equation in a velocity number (N_v) and a diameter
//     number (N_D);
//   * a liquid film roughens the pipe wall, so the friction uses an "effective" roughness that
//     moves from the pipe's own roughness (almost no liquid) to a value set by surface tension
//     (R = liquid/gas velocity ratio of 0.007 or more).
// Gravity uses the slip density, friction uses the no-slip mixture.
// Meant for: gas velocity up to about 50 ft/s... and beyond, tubing up to 3 in, condensate below
// 50 STB/MMscf, water below 5 STB/MMscf.  Not for oil wells.

export const GRAY_SIGMA_UNIT = 0.0022046;     // 1 dyne/cm expressed in lbm/s2 (the unit N_v and N_D need)
export const GRAY_MIN_ROUGHNESS = 2.77e-5;    // ft, smallest effective roughness allowed

/**
 * Gray liquid holdup (fraction of the pipe filled with liquid).
 * r = v_sl / v_sg.  Same equation as in the API 14B manual.
 * @param {number} r @param {number} n_v @param {number} n_d
 */
export function gray_holdup(r, n_v, n_d) {
  const b = 0.0814 * (1.0 - 0.0554 * Math.log(1.0 + 730.0 * r / (r + 1.0)));
  const f1 = -2.314 * (n_v * (1.0 + 205.0 / n_d)) ** b;
  return 1.0 - (1.0 - Math.exp(f1)) / (r + 1.0);
}

/**
 * Effective wall roughness (ft) seen by the gas when a liquid film is present.
 * @param {number} r @param {number} k_ft @param {number} sigma_lbm @param {number} rho_ns @param {number} v_m
 */
export function gray_effective_roughness(r, k_ft, sigma_lbm, rho_ns, v_m) {
  const k0 = 28.5 * sigma_lbm / (rho_ns * v_m ** 2);           // roughness set by the liquid film
  let k_e;
  if (r >= 0.007) k_e = k0;
  else k_e = k_ft + r * (k0 - k_ft) / 0.007;                   // blend from the pipe's own roughness
  return Math.max(k_e, GRAY_MIN_ROUGHNESS);
}

/**
 * Gray pressure gradient (psi per ft of pipe), same inputs and same kind of result as
 * beggs_brill_gradient (see there for the meaning of the inputs).
 * 'regime' is 'gray', 'liquid' or 'gas'; 'k_eff' is the effective roughness in ft.
 * The acceleration term is kept (Gray's original leaves it out); for gas wells it is a few
 * percent near the wellhead.
 * @param {number} p @param {number} angle_deg @param {number} d_in @param {number} roughness_in
 * @param {FlowConditions} c
 * @returns {{dpdl: number, hl: number, regime: string, hydrostatic: number, friction: number,
 *            f_tp: number, re: number, e_k: number, k_eff: number}}
 */
export function gray_gradient(p, angle_deg, d_in, roughness_in, c) {
  check(p > 0 && d_in > 0, "Pressure and diameter must be > 0.");
  const d_ft = d_in / 12.0;
  const v_sl = c.v_sl, v_sg = c.v_sg;
  const v_m = v_sl + v_sg;
  check(v_m > 0, "No flow: mixture velocity is zero.");
  let lam = v_sl / v_m;                               // no-slip liquid fraction
  const theta = radians(angle_deg);
  const rho_l = c.rho_l, rho_g = c.rho_g, mu_l = c.mu_l, mu_g = c.mu_g;
  const k_ft = roughness_in / 12.0;

  let regime, hl = 0.0;
  if (lam < 1e-8) {                                   // gas only
    regime = "gas"; hl = 0.0; lam = 0.0;
  } else if (lam > 1.0 - 1e-8) {                      // liquid only
    regime = "liquid"; hl = 1.0; lam = 1.0;
  } else {
    regime = "gray";
  }
  const rho_ns = rho_l * lam + rho_g * (1.0 - lam);   // no-slip mixture density
  const mu_ns = mu_l * lam + mu_g * (1.0 - lam);      // no-slip mixture viscosity
  let k_eff = k_ft;

  if (regime === "gray") {
    const sigma = c.sigma * GRAY_SIGMA_UNIT;          // lbm/s2
    const r = v_sl / v_sg;
    const d_rho = Math.max(rho_l - rho_g, 1.0);
    const n_v = rho_ns ** 2 * v_m ** 4 / (GC * sigma * d_rho);
    const n_d = GC * d_rho * d_ft ** 2 / sigma;
    hl = Math.min(Math.max(gray_holdup(r, n_v, n_d), lam), 1.0);   // never below no-slip, never above 1
    k_eff = gray_effective_roughness(r, k_ft, sigma, rho_ns, v_m);
  }

  const rho_s = rho_l * hl + rho_g * (1.0 - hl);      // in-situ (slip) density
  const re = RE_CONST * rho_ns * v_m * d_ft / mu_ns;
  const f = friction_factor(re, Math.min(k_eff / d_ft, 0.05));     // relative roughness is capped at 0.05
  const hydrostatic = rho_s * Math.sin(theta) / 144.0;
  const friction = f * rho_ns * v_m ** 2 / (2.0 * GC * d_ft) / 144.0;
  const e_k = Math.min(rho_s * v_m * v_sg / (GC * p * 144.0), 0.95);
  const dpdl = (hydrostatic + friction) / (1.0 - e_k);
  return { dpdl, hl, regime, hydrostatic, friction, f_tp: f, re, e_k, k_eff };
}


// =====================================================================
// Orkiszewski (1967, SPE 1546) - vertical oil wells and gas lift wells
// =====================================================================
// A composite of earlier work (the paper's Appendices A-C):
//   * the flow pattern (bubble, slug, transition, mist) comes from the gas fraction and a
//     dimensionless gas velocity v_gD (Griffith-Wallis for bubble/slug, Duns-Ros for the others);
//   * bubble flow  : Griffith - a constant slip velocity of 0.8 ft/s;
//   * slug flow    : modified Griffith-Wallis - the gas bubbles rise at a velocity v_b, and a
//                    "liquid distribution coefficient" Gamma (from field data) accounts for the
//                    liquid film and the droplets in the bubbles.  This is the pattern met in most
//                    flowing and gas lift wells;
//   * mist flow    : Duns-Ros - no slip; the wall roughness seen by the gas is set by the liquid film;
//   * transition   : the slug and mist results weighted linearly with v_gD (Duns-Ros).
// The gradient is  dp/dL = (density * sin(angle) + wall friction) / (1 - kinetic term), Eq. A-3.
//
// Notes on how the paper is coded (the same decisions as the Python, kept word for word):
//   * Bubble rise velocity v_b uses the paper's own equations C-7, C-8 and C-9 for every Reynolds
//     number (the paper reads C1 and C2 from Figs. 8 and 9 only where those charts reach, up to a
//     Reynolds number of about 6000; the equations are what its Appendix D example uses).
//     Equation C-9 is written here as 1/2 (v_bi + sqrt(...)); the printed bracket is missing, but
//     only this form joins Eq. C-7 at N_b = 3000 and Eq. C-8 at N_b = 8000.
//   * Equation B-4 prints v_g where v_gD is meant (the Duns-Ros mist boundary).
//   * The constraints C-15 and C-16 on Gamma are applied as written; C-16 contains the average
//     density, which itself contains Gamma, so the inequality is solved for Gamma instead of being
//     iterated.
//   * Which liquid is the continuous phase (needed for Gamma) is not defined in the paper: water
//     when it is at least half of the liquid volume, oil otherwise.
//   * The Moody friction factor is the Colebrook equation (the paper reads a chart).

export const ORK_SLIP_VELOCITY = 0.8;        // Griffith bubble-flow slip velocity, ft/s
export const ORK_WATER_CONTINUOUS = 0.5;     // water is the continuous phase from this water fraction

/**
 * Bubble rise velocity v_b (ft/s) in slug flow, Eq. C-5 through C-9 of the paper.
 * N_Re = 1488 rho_L d v_t / mu_L (C-6) and the bubble Reynolds number N_b = 1488 v_b d rho_L / mu_L.
 * Because N_b depends on v_b, the equation that applies is chosen as follows:
 *   C-7 if the velocity it gives has N_b <= 3000, otherwise
 *   C-8 if the velocity it gives has N_b >= 8000, otherwise
 *   C-9 (the equation for 3000 < N_b < 8000).
 * @param {number} rho_l @param {number} mu_l @param {number} d_ft @param {number} v_t
 */
export function ork_bubble_rise_velocity(rho_l, mu_l, d_ft, v_t) {
  const n_re = RE_CONST * rho_l * d_ft * v_t / mu_l;
  const root = Math.sqrt(GC * d_ft);
  /** @param {number} v_b */
  const n_b = (v_b) => RE_CONST * v_b * d_ft * rho_l / mu_l;
  const v_7 = (0.546 + 8.74e-6 * n_re) * root;
  if (n_b(v_7) <= 3000.0) return v_7;
  const v_8 = (0.35 + 8.74e-6 * n_re) * root;
  if (n_b(v_8) >= 8000.0) return v_8;
  const v_bi = (0.251 + 8.74e-6 * n_re) * root;
  return 0.5 * (v_bi + Math.sqrt(v_bi ** 2 + 13.59 * mu_l / (rho_l * Math.sqrt(d_ft))));
}

/**
 * Liquid distribution coefficient Gamma before the limits C-15 and C-16 (Eq. C-11 to C-14).
 * mu_l in cP, d_ft = hydraulic diameter in ft, v_t = total velocity in ft/s; logarithms are base 10.
 * @param {number} mu_l @param {number} d_ft @param {number} v_t @param {boolean} water_continuous
 */
export function ork_gamma(mu_l, d_ft, v_t, water_continuous) {
  const lg = Math.log10;
  if (water_continuous) {
    if (v_t < 10.0) {
      return 0.013 * lg(mu_l) / d_ft ** 1.38 - 0.681 + 0.232 * lg(v_t) - 0.428 * lg(d_ft);          // C-11
    }
    return 0.045 * lg(mu_l) / d_ft ** 0.799 - 0.709 - 0.162 * lg(v_t) - 0.888 * lg(d_ft);           // C-12
  }
  if (v_t < 10.0) {
    return 0.0127 * lg(mu_l + 1.0) / d_ft ** 1.415 - 0.284 + 0.167 * lg(v_t) + 0.113 * lg(d_ft);    // C-13
  }
  return (0.0274 * lg(mu_l + 1.0) / d_ft ** 1.371 + 0.161 + 0.569 * lg(d_ft)
          - lg(v_t) * (0.01 * lg(mu_l + 1.0) / d_ft ** 1.571 + 0.397 + 0.63 * lg(d_ft)));           // C-14
}

/**
 * Bubble flow: [average density, friction gradient in lbf/ft2/ft, extra results].
 * @param {number} v_sl @param {number} v_sg @param {number} v_t @param {number} rho_l
 * @param {number} rho_g @param {number} mu_l @param {number} d_ft @param {number} eps_d
 * @returns {[number, number, {f: number, re: number}]}
 */
function orkBubble(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d) {
  const x = 1.0 + v_t / ORK_SLIP_VELOCITY;
  const f_g = 0.5 * (x - Math.sqrt(Math.max(x * x - 4.0 * v_sg / ORK_SLIP_VELOCITY, 0.0)));   // gas fraction, Eq. C-1
  const rho = (1.0 - f_g) * rho_l + f_g * rho_g;                                             // Eq. C-2
  const v_l = v_sl / (1.0 - f_g);
  const re = RE_CONST * rho_l * d_ft * v_l / mu_l;
  const f = friction_factor(re, eps_d);
  const tau = f * rho_l * v_l ** 2 / (2.0 * GC * d_ft);                                      // Eq. C-3
  return [rho, tau, { f, re }];
}

/**
 * Slug flow: [average density, friction gradient in lbf/ft2/ft, extra results].
 * @param {number} v_sl @param {number} v_sg @param {number} v_t @param {number} rho_l
 * @param {number} rho_g @param {number} mu_l @param {number} d_ft @param {number} eps_d
 * @param {boolean} water_continuous
 * @returns {[number, number, {f: number, re: number, v_b: number, gamma: number}]}
 */
function orkSlug(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d, water_continuous) {
  const v_b = ork_bubble_rise_velocity(rho_l, mu_l, d_ft, v_t);
  let gamma = ork_gamma(mu_l, d_ft, v_t, water_continuous);
  const rho_0 = (rho_l * v_sl + rho_g * v_sg + rho_l * v_b) / (v_t + v_b);    // Eq. C-4 without the Gamma term
  const share = v_b / (v_t + v_b);                                            // v_b Ap / (q_t + v_b Ap)
  gamma = Math.max(gamma, -0.065 * v_t);                                      // C-15
  if (v_t > 10.0) {    // C-16:  Gamma >= -share (1 - rho/rho_L), rho = rho_0 + Gamma rho_L
    gamma = Math.max(gamma, -share * (1.0 - rho_0 / rho_l) / (1.0 - share));
  }
  const rho = rho_0 + gamma * rho_l;                                          // Eq. C-4
  const re = RE_CONST * rho_l * d_ft * v_t / mu_l;                            // Eq. C-6
  const f = friction_factor(re, eps_d);
  const bracket = Math.max((v_sl + v_b) / (v_t + v_b) + gamma, 0.0);
  const tau = f * rho_l * v_t ** 2 / (2.0 * GC * d_ft) * bracket;             // Eq. C-10
  return [rho, tau, { f, re, v_b, gamma }];
}

/**
 * Mist flow (no slip) with gas superficial velocity v_g: [density, friction gradient, extras].
 * The wall roughness seen by the gas is the Duns-Ros one (Eq. C-21, C-22), kept between 0.001 and
 * 0.5 (a gas-only well uses the pipe's own roughness instead).
 * @param {number} v_sl @param {number} v_g @param {number} rho_l @param {number} rho_g
 * @param {number} mu_l @param {number} mu_g @param {number} sigma_lbm @param {number} d_ft
 * @param {number} eps_d @param {boolean} [duns_ros_roughness]
 * @returns {[number, number, {f: number, re: number}]}
 */
function orkMist(v_sl, v_g, rho_l, rho_g, mu_l, mu_g, sigma_lbm, d_ft, eps_d, duns_ros_roughness = true) {
  const f_g = v_g / (v_g + v_sl);                                             // Eq. C-19
  const rho = (1.0 - f_g) * rho_l + f_g * rho_g;                              // Eq. C-2
  if (duns_ros_roughness) {
    const n_w = 4.52e-7 * (v_g * mu_l / sigma_lbm) ** 2 * rho_g / rho_l;
    const k = n_w > 0.005 ? 174.8 * sigma_lbm * n_w ** 0.302 : 34.0 * sigma_lbm;
    eps_d = Math.min(Math.max(k / (rho_g * v_g ** 2 * d_ft), 1e-3), 0.5);     // Eq. C-21 / C-22
  }
  const re = RE_CONST * rho_g * d_ft * v_g / mu_g;
  const f = friction_factor(re, eps_d);
  const tau = f * rho_g * v_g ** 2 / (2.0 * GC * d_ft);                       // Eq. C-20
  return [rho, tau, { f, re }];
}

/**
 * The flow pattern by the paper's Appendix B (liquid with a gas that has v_sg > 0).
 * sigma_lbm : surface tension in lbm/s2 (1 dyne/cm = 0.0022046).
 *   l_b  : bubble/slug boundary on the gas fraction (B-2, never below 0.13)
 *   v_gd : dimensionless gas velocity (B-1), root = (rho_L / (g sigma))^0.25 is its factor v_g -> v_gD
 *   l_s, l_m : slug/transition and transition/mist boundaries on v_gD (B-3, B-4)
 * @param {number} v_sl @param {number} v_sg @param {number} rho_l @param {number} sigma_lbm @param {number} d_ft
 * @returns {{regime: string, gas_fraction: number, l_b: number, v_gd: number, l_s: number, l_m: number, root: number}}
 */
export function ork_flow_regime(v_sl, v_sg, rho_l, sigma_lbm, d_ft) {
  const v_t = v_sl + v_sg;
  const gas_fraction = v_sg / v_t;
  const l_b = Math.max(1.071 - 0.2218 * v_t ** 2 / d_ft, 0.13);                  // B-2
  const root = (rho_l / (GC * sigma_lbm)) ** 0.25;
  const v_gd = v_sg * root;                                                      // B-1
  const ratio = root * v_sl;              // v_gD q_L / q_g (v_g cancels, so v_g = 0 is fine)
  const l_s = 50.0 + 36.0 * ratio;                                               // B-3
  const l_m = 75.0 + 84.0 * ratio ** 0.75;                                       // B-4 (v_gD, see the notes above)
  let regime;
  if (gas_fraction < l_b) regime = "bubble";
  else if (v_gd < l_s) regime = "slug";
  else if (v_gd < l_m) regime = "transition";
  else regime = "mist";
  return { regime, gas_fraction, l_b, v_gd, l_s, l_m, root };
}

/**
 * Orkiszewski pressure gradient (psi per ft of pipe), same inputs and same kind of result as
 * beggs_brill_gradient (c also carries 'frac_w', the water share of the liquid volume, which
 * decides the continuous liquid phase).
 * 'regime' is 'bubble', 'slug', 'transition', 'mist' or 'gas'; slug flow also returns 'v_b' and 'gamma'.
 * @param {number} p @param {number} angle_deg @param {number} d_in @param {number} roughness_in
 * @param {FlowConditions} c
 * @returns {{dpdl: number, hl: number, regime: string, hydrostatic: number, friction: number,
 *            f_tp: number, re: number, e_k: number, v_b: number|null, gamma: number|null}}
 */
export function orkiszewski_gradient(p, angle_deg, d_in, roughness_in, c) {
  check(p > 0 && d_in > 0, "Pressure and diameter must be > 0.");
  const d_ft = d_in / 12.0;
  const v_sl = c.v_sl, v_sg = c.v_sg;
  const v_t = v_sl + v_sg;                            // total velocity (q_t / A_p)
  check(v_t > 0, "No flow: mixture velocity is zero.");
  const theta = radians(angle_deg);
  const rho_l = c.rho_l, rho_g = c.rho_g, mu_l = c.mu_l, mu_g = c.mu_g;
  const sigma = c.sigma * GRAY_SIGMA_UNIT;            // lbm/s2, the unit the paper's equations use
  const eps_d = roughness_in / d_in;
  const water_continuous = (c.frac_w ?? 0.0) >= ORK_WATER_CONTINUOUS;

  /** @type {{f?: number, re?: number, v_b?: number, gamma?: number}} */
  let extra = {};
  let regime, rho, tau;
  if (v_sl < 1e-9 * v_t) {                            // no liquid at all: gas only
    regime = "gas";
    [rho, tau, extra] = orkMist(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, false);
    rho = rho_g;
  } else {
    const fp = ork_flow_regime(v_sl, v_sg, rho_l, sigma, d_ft);
    regime = fp.regime;
    if (regime === "bubble") {
      [rho, tau, extra] = orkBubble(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d);
    } else if (regime === "slug") {
      [rho, tau, extra] = orkSlug(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d, water_continuous);
    } else if (regime === "transition") {
      const [rho_s, tau_s, extraSlug] = orkSlug(v_sl, v_sg, v_t, rho_l, rho_g, mu_l, d_ft, eps_d, water_continuous);
      extra = extraSlug;
      const v_g_mist = fp.l_m / fp.root;                       // Eq. C-18: gas rate of the mist calculation
      const [rho_m, tau_m] = orkMist(v_sl, v_g_mist, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d);
      const w_slug = (fp.l_m - fp.v_gd) / (fp.l_m - fp.l_s);   // Eq. C-17: weights with v_gD
      rho = w_slug * rho_s + (1.0 - w_slug) * rho_m;
      tau = w_slug * tau_s + (1.0 - w_slug) * tau_m;
    } else {
      [rho, tau, extra] = orkMist(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d);
    }
  }

  const hl = Math.min(Math.max((rho - rho_g) / Math.max(rho_l - rho_g, 1e-9), 0.0), 1.0);
  const hydrostatic = rho * Math.sin(theta) / 144.0;  // psi/ft
  const friction = tau / 144.0;
  const mass_flux = rho_l * v_sl + rho_g * v_sg;      // w_t / A_p, lb/s/ft2
  const e_k = Math.min(mass_flux * v_sg / (GC * p * 144.0), 0.95);   // the kinetic term of Eq. A-3
  const dpdl = (hydrostatic + friction) / (1.0 - e_k);
  return { dpdl, hl, regime, hydrostatic, friction,
           f_tp: extra.f ?? 0.0, re: extra.re ?? 0.0, e_k,
           v_b: extra.v_b ?? null, gamma: extra.gamma ?? null };
}


// =====================================================================
// Ansari et al. (1994) - a mechanistic model
// =====================================================================
// Ansari, A.M., Sylvester, N.D., Sarica, C., Shoham, O. and Brill, J.P., "A Comprehensive Mechanistic
// Model for Upward Two-Phase Flow in Wellbores", SPE Production & Facilities, May 1994, p. 143.
//
// Instead of a curve fitted to field data, the model first decides the flow pattern from the physics
// (Taitel and Barnea boundaries), then uses a separate physical model for each pattern:
//     bubble / dispersed bubble : drift-flux holdup, mixture friction
//     slug (and churn)          : a Taylor bubble followed by a liquid slug (Fernandes, Sylvester,
//                                 Vo and Shoham), fully developed or still developing
//     annular                   : a liquid film on the wall and a gas core carrying liquid droplets
// The paper leaves out the acceleration term, so there is none here.  Everything inside these
// functions is in feet, pounds and seconds (g = 32.174 ft/s2); the result is in psi per ft.
//
// Notes on how the paper is coded (the same notes as the Python, and the README has the reasons):
//   * Equation 40 (the constant A in slug equation 39) is not used as printed.  The slug equation is
//     rebuilt from the paper's own equations 29 - 35, 37 and 38 (see ansSlug).
//   * Equation 45 (the Nusselt film thickness) is used with the liquid holdup H_NLTB of the film, as
//     the Nusselt film requires, where the paper prints (1 - H_NLTB).
//   * Equation 54 for the length of a developing Taylor bubble is solved for its square root
//     directly; b is taken from equations 52 and 53.
//   * The friction factor in the dispersed-bubble boundary (Eq. 4) uses the liquid Reynolds number of
//     the mixture velocity.  Moody factors are Colebrook (the paper reads a chart).
//   * Annular flow is accepted only if the film the annular model itself finds (Eq. 93) is also too
//     thin to bridge the pipe.  Without this, a gas rate just above Eq. 6 can give a thick,
//     unphysical "annular" film and a very large pressure gradient.
//   * Film instability (Eq. 8): the smaller of the two film holdups that satisfy it is used.  If
//     there is none, the film holdup at the closest approach is used, which makes the bridging test
//     of Eq. 12 fail, so the flow is not annular.

export const ANS_SLUG_LENGTH = 30.0;    // liquid slug length in pipe diameters (the paper's C' = 30)
export const ANS_SLUG_RISE = 0.35;      // Taylor bubble rise coefficient of Eq. 34
export const ANS_BUBBLE_RISE = 1.53;    // bubble swarm coefficient of Eqs. 3, 21, 35
export const ANS_FILM_BRIDGE = 0.12;    // minimum liquid fraction that can bridge the pipe (Eq. 7, 12)
export const ANS_DEV_BLEND = 1.5;       // L_c / L_TB at which the developing slug equations (Eq. 62) fully
                                        // replace the developed ones (Eq. 60).  1.0 is where the paper
                                        // switches between them; the two do not meet there, so they are
                                        // blended from 1.0 to this value.  NOT in the paper.

/**
 * Weight of the developing slug equations, 0 at ratio = 1 and 1 at ratio = ANS_DEV_BLEND, with a
 * smooth (zero-slope) start and finish, so the pressure gradient has no step and no kink where the
 * two meet.
 * @param {number} ratio
 */
export function ansBlend(ratio) {
  if (ratio <= 1.0) return 0.0;
  if (ratio >= ANS_DEV_BLEND) return 1.0;
  const x = (ratio - 1.0) / (ANS_DEV_BLEND - 1.0);
  return x * x * (3.0 - 2.0 * x);                 // smoothstep
}

/**
 * Root of fn between lo and hi by halving (fn(lo) and fn(hi) must have opposite signs).
 * @param {(x: number) => number} fn @param {number} lo @param {number} hi @param {number} [n]
 */
function ansBisect(fn, lo, hi, n = 200) {
  let f_lo = fn(lo);
  for (let i = 0; i < n; i++) {
    const mid = 0.5 * (lo + hi);
    const f_mid = fn(mid);
    if ((f_mid > 0) === (f_lo > 0)) {
      lo = mid;
      f_lo = f_mid;
    } else {
      hi = mid;
    }
    if (hi - lo < 1e-14) break;
  }
  return 0.5 * (lo + hi);
}

/**
 * Barnea film instability, Eq. 8:  Y_M = (2 - 1.5 H)/(H^3 (1 - 1.5 H)) X_M^2, solved for the film
 * holdup H.  The right-hand side has one minimum between H = 0 and 2/3.  Returns the smaller root;
 * if Y_M is below that minimum (no root) it returns the holdup at the minimum.
 * @param {number} y_m @param {number} x_m2
 */
export function ansFilmInstability(y_m, x_m2) {
  const shape = (/** @type {number} */ h) => (2.0 - 1.5 * h) / (h ** 3 * (1.0 - 1.5 * h));
  let lo = 1e-6;
  let hi = 2.0 / 3.0 - 1e-6;
  for (let i = 0; i < 200; i++) {                 // golden-section search for the minimum of shape(h)
    const m1 = lo + 0.382 * (hi - lo);
    const m2 = lo + 0.618 * (hi - lo);
    if (shape(m1) < shape(m2)) hi = m2;
    else lo = m1;
  }
  const h_min = 0.5 * (lo + hi);
  const target = x_m2 > 0 ? y_m / x_m2 : Infinity;
  if (target <= shape(h_min)) return h_min;
  return ansBisect((h) => shape(h) - target, 1e-9, h_min);
}

/**
 * Entrainment and core properties of annular flow (Eqs. 69 - 72, 87 - 90): the entrained fraction
 * F_E, the no-slip liquid fraction of the core, its density and viscosity, its superficial velocity,
 * the friction factor and the superficial pressure gradient of the core (lbf/ft2/ft).
 * @param {number} v_sl @param {number} v_sg @param {number} rho_l @param {number} rho_g
 * @param {number} mu_l @param {number} mu_g @param {number} sigma @param {number} d_ft
 * @param {number} eps_d
 */
export function ansCore(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d) {
  const v_crit = 1.0e4 * v_sg * (mu_g / RE_CONST) / sigma * Math.sqrt(rho_g / rho_l);   // Eq. 72 (mu in lbm/ft/s)
  const f_e = Math.max(1.0 - Math.exp(-0.125 * (v_crit - 1.5)), 0.0);                   // Eq. 71
  const lam_lc = f_e * v_sl / (v_sg + f_e * v_sl);                                      // Eq. 70
  const rho_c = rho_l * lam_lc + rho_g * (1.0 - lam_lc);                                // Eq. 69
  const mu_c = mu_l * lam_lc + mu_g * (1.0 - lam_lc);                                   // Eq. 90
  const v_sc = f_e * v_sl + v_sg;                                                       // Eq. 89
  const re_sc = RE_CONST * rho_c * v_sc * d_ft / mu_c;                                  // Eq. 88
  const f_sc = friction_factor(re_sc, eps_d);
  const dpdl_sc = f_sc * rho_c * v_sc ** 2 / (2.0 * d_ft * GC);                         // Eq. 87
  return { f_e, lam_lc, rho_c, mu_c, v_sc, re_sc, f_sc, dpdl_sc };
}

/**
 * Dimensionless film thickness (film thickness / diameter) of annular flow and the gradient, by
 * solving the momentum balance of the film and the core (Eqs. 91 - 93, written here as one equation
 * for delta).  Returns the core numbers of ansCore plus 'delta', 'dpdl' (lbf/ft2/ft),
 * 'hydrostatic', 'friction', 'holdup' and 'f_f'.
 * @param {number} v_sl @param {number} v_sg @param {number} rho_l @param {number} rho_g
 * @param {number} mu_l @param {number} mu_g @param {number} sigma @param {number} d_ft
 * @param {number} eps_d @param {number} theta
 */
export function ans_annular_film_thickness(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta) {
  const core = ansCore(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d);
  const { f_e, rho_c, dpdl_sc } = core;
  const re_sl = RE_CONST * rho_l * v_sl * d_ft / mu_l;                                  // Eq. 80
  const f_sl = friction_factor(re_sl, eps_d);
  const dpdl_sl = f_sl * rho_l * v_sl ** 2 / (2.0 * d_ft * GC);                         // Eq. 79
  const re_f = RE_CONST * rho_l * v_sl * (1.0 - f_e) * d_ft / mu_l;                     // Eq. 74 (no delta in it)
  const f_f = friction_factor(Math.max(re_f, 1.0), eps_d);
  const sin_t = Math.sin(theta);
  const drive = (rho_l - rho_c) * sin_t;                       // (rho_L - rho_C) g sin(theta) / gc

  const z_factor = (/** @type {number} */ delta) => {                                   // Eqs. 84, 85
    if (f_e > 0.9) return 1.0 + 300.0 * delta;
    return 1.0 + 24.0 * (rho_l / rho_g) ** (1.0 / 3.0) * delta;
  };

  const residual = (/** @type {number} */ delta) => {                                   // Eq. 93
    const film = 4.0 * delta * (1.0 - delta);
    return (z_factor(delta) * dpdl_sc / (film * (1.0 - 2.0 * delta) ** 5) - drive
            - (1.0 - f_e) ** 2 * (f_f / f_sl) * dpdl_sl / film ** 3);
  };

  // The balance can have more than one root; the first one met from the thin-film side is the
  // physical film.  (residual -> minus infinity as delta -> 0 and plus infinity as delta -> 0.5.)
  /** @type {number[]} */
  const grid = [];
  for (let i = 0; i <= 400; i++) grid.push(1e-7 * (0.5 / 1e-7) ** (i / 400.0));
  /** @type {number | null} */
  let delta = null;
  for (let i = 0; i < grid.length - 1; i++) {
    const lo = grid[i];
    const hi = grid[i + 1];
    if (residual(lo) < 0.0 && 0.0 <= residual(hi)) {
      delta = ansBisect(residual, lo, hi);
      break;
    }
  }
  if (delta === null) delta = ansBisect(residual, 1e-9, 0.5 - 1e-9);
  const dpdl = z_factor(delta) * dpdl_sc / (1.0 - 2.0 * delta) ** 5 + rho_c * sin_t;    // Eq. 91 / 102
  const hydrostatic = rho_c * sin_t;
  const holdup = 4.0 * delta * (1.0 - delta) + core.lam_lc * (1.0 - 2.0 * delta) ** 2;
  return { ...core, delta, dpdl, hydrostatic, friction: dpdl - hydrostatic, holdup,
           f_f, f_sl, dpdl_sl, drive, residual_at_root: residual(delta) };
}

/**
 * The flow pattern by the paper's boundaries (Eqs. 1 - 12).  v_sl > 0 and v_sg > 0 are expected, and
 * sigma is in lbm/s2.  Returns the regime ('bubble', 'dispersed', 'slug' or 'annular') and the
 * numbers used: v_s (Eq. 3), d_min (Eq. 1), v_sg_a (Eq. 2), v_sg_d (Eq. 6), h_lf, core_liquid.
 * @param {number} v_sl @param {number} v_sg @param {number} rho_l @param {number} rho_g
 * @param {number} mu_l @param {number} mu_g @param {number} sigma @param {number} d_ft
 * @param {number} eps_d @param {number} theta
 */
export function ans_flow_pattern(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta) {
  const v_m = v_sl + v_sg;
  const d_rho = rho_l - rho_g;
  const v0 = (GC * sigma * d_rho / rho_l ** 2) ** 0.25;
  const v_s = ANS_BUBBLE_RISE * v0;                                                     // Eq. 3
  const d_min = 19.01 * Math.sqrt(d_rho * sigma / (rho_l ** 2 * GC));                   // Eq. 1
  const v_sg_a = 0.25 * v_s + 0.333 * v_sl;                                             // Eq. 2 (transition A)
  const v_sg_d = 3.1 * (GC * sigma * d_rho / rho_g ** 2) ** 0.25;                       // Eq. 6 (transition D)
  /** @type {{regime: string, v_s: number, d_min: number, v_sg_a: number, v_sg_d: number,
   *          h_lf: number | null, core_liquid: number | null,
   *          annular?: ReturnType<typeof ans_annular_film_thickness>}} */
  const info = { regime: "slug", v_s, d_min, v_sg_a, v_sg_d, h_lf: null, core_liquid: null };

  // annular flow: fast enough gas AND a film too thin to bridge the pipe (Barnea, Eqs. 7 - 15)
  if (v_sg > v_sg_d) {
    const core = ansCore(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d);
    const re_sl = RE_CONST * rho_l * v_sl * d_ft / mu_l;
    const f_sl = friction_factor(re_sl, eps_d);
    const dpdl_sl = f_sl * rho_l * v_sl ** 2 / (2.0 * d_ft * GC);
    const f_f = friction_factor(Math.max(RE_CONST * rho_l * v_sl * (1.0 - core.f_e) * d_ft / mu_l, 1.0), eps_d);
    const b = (1.0 - core.f_e) ** 2 * f_f / f_sl;
    const x_m2 = b * dpdl_sl / core.dpdl_sc;                                            // X_M squared (Eq. 9)
    const y_m = (rho_l - core.rho_c) * Math.sin(theta) / core.dpdl_sc;                  // Eq. 10
    const h_lf = ansFilmInstability(y_m, x_m2);
    const core_liquid = core.lam_lc * (1.0 - h_lf);          // lambda_LC A_C/A_p, with A_C/A_p = 1 - H_LF
    info.h_lf = h_lf;
    info.core_liquid = core_liquid;
    if (h_lf + core_liquid <= ANS_FILM_BRIDGE) {                                        // Eq. 12 not satisfied
      // The film that the annular model really finds must not bridge the pipe either.  Just above
      // the boundary of Eq. 6 the gas can be too slow to hold the film up; the model then gives a
      // thick film (more liquid than Eq. 12 allows) and the flow is slug, not annular.
      const an = ans_annular_film_thickness(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta);
      if (an.holdup <= ANS_FILM_BRIDGE) {
        info.regime = "annular";
        info.annular = an;
        return info;
      }
    }
  }

  // dispersed bubble: turbulence breaks the bubbles up (Eq. 4) and the gas fraction is below 0.76 (Eq. 5)
  if (v_sg <= 3.17 * v_sl) {
    const f_m = friction_factor(RE_CONST * rho_l * v_m * d_ft / mu_l, eps_d);
    const lhs = (2.0 * (0.4 * sigma / (d_rho * GC)) ** 0.5 * (rho_l / sigma) ** 0.6
                 * (f_m / (2.0 * d_ft)) ** 0.4 * v_m ** 1.2);
    const rhs = 0.725 + 4.15 * Math.sqrt(v_sg / v_m);
    if (lhs >= rhs) {
      info.regime = "dispersed";
      return info;
    }
  }

  // bubble flow: wide enough pipe and a low gas rate (Eqs. 1, 2)
  if (d_ft >= d_min && v_sg <= v_sg_a) {
    info.regime = "bubble";
    return info;
  }
  info.regime = "slug";
  return info;
}

/**
 * Liquid holdup of bubble flow from Eq. 22:
 *   1.53 [g sigma d_rho / rho_L^2]^0.25 H^0.5 = v_Sg/(1 - H) - 1.2 v_m
 * @param {number} v_sl @param {number} v_sg @param {number} v0
 */
export function ansBubbleHoldup(v_sl, v_sg, v0) {
  const v_m = v_sl + v_sg;
  return ansBisect((h) => v_sg / (1.0 - h) - 1.2 * v_m - ANS_BUBBLE_RISE * v0 * Math.sqrt(h),
                   1e-9, 1.0 - 1e-12);
}

/**
 * The slug flow model (Eqs. 29 - 66).  Returns the slug unit variables, its elevation density
 * (lb/ft3, to be multiplied by sin(theta)) and its friction gradient (lbf/ft2/ft).
 * @param {number} v_sl @param {number} v_sg @param {number} rho_l @param {number} rho_g
 * @param {number} mu_l @param {number} mu_g @param {number} sigma @param {number} d_ft
 * @param {number} eps_d
 */
export function ansSlug(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d) {
  const v_m = v_sl + v_sg;
  const d_rho = rho_l - rho_g;
  const v0 = (GC * sigma * d_rho / rho_l ** 2) ** 0.25;
  const v_tb = 1.2 * v_m + ANS_SLUG_RISE * Math.sqrt(GC * d_ft * d_rho / rho_l);        // Eq. 34
  const h_gls = v_sg / (0.425 + 2.65 * v_m);                                            // Eq. 38
  const h_lls = 1.0 - h_gls;
  const v_gls = 1.2 * v_m + ANS_BUBBLE_RISE * v0 * Math.sqrt(h_lls);                    // Eq. 35

  // Eq. 37 with H_gTB = 1 - H_LTB
  const v_ltb_of = (/** @type {number} */ h_ltb) =>
    9.916 * Math.sqrt(GC * d_ft * (1.0 - Math.sqrt(1.0 - h_ltb)));

  // The eight equations 29 - 35, 37, 38 reduce to one equation in H_LTB (Vo and Shoham).  Equations
  // 32 and 33 make the flux of liquid plus gas equal in the Taylor bubble and in the liquid slug, and
  // equations 29 + 30 say that flux is v_m; this gives (compare Eqs. 39 - 41):
  //     v_LTB H_LTB - v_TB (1 - H_LTB - H_gLS) + (v_m - v_gLS H_gLS) = 0
  const residual = (/** @type {number} */ h_ltb) =>
    v_ltb_of(h_ltb) * h_ltb - v_tb * (1.0 - h_ltb - h_gls) + (v_m - v_gls * h_gls);

  const lo = 1e-9;
  const hi = 1.0 - 1e-9;
  let h_ltb;
  if (residual(lo) >= 0.0) h_ltb = lo;
  else if (residual(hi) <= 0.0) h_ltb = hi;
  else h_ltb = ansBisect(residual, lo, hi);

  const h_gtb = 1.0 - h_ltb;
  const v_ltb = v_ltb_of(h_ltb);
  const v_lls = v_tb - (v_tb + v_ltb) * h_ltb / h_lls;                                  // Eq. 32
  const v_gtb = v_tb - (v_tb - v_gls) * h_gls / h_gtb;                                  // Eq. 33
  const denom = v_lls * h_lls + v_ltb * h_ltb;
  let beta = denom > 0 ? (v_lls * h_lls - v_sl) / denom : 0.5;                           // Eq. 30
  beta = Math.min(Math.max(beta, 1e-4), 0.999);
  const l_ls = ANS_SLUG_LENGTH * d_ft;                                                   // Eq. 48
  const l_tb = l_ls * beta / (1.0 - beta);                                               // Eq. 49

  const rho_ls = rho_l * h_lls + rho_g * h_gls;                                          // Eq. 61
  const mu_ls = mu_l * h_lls + mu_g * h_gls;
  /** @type {{beta: number, h_ltb: number, h_gls: number, v_tb: number, v_gls: number,
   *           v_ltb: number, v_lls: number, v_gtb: number, l_ls: number, l_tb: number,
   *           developing: boolean, l_c: number | null, l_tb_star?: number, blend?: number}} */
  const out = { beta, h_ltb, h_gls, v_tb, v_gls, v_ltb, v_lls, v_gtb, l_ls, l_tb,
                developing: false, l_c: null };

  // Developing or developed?  Compare the cap length of the Taylor bubble (Eq. 44) with its developed
  // length.  The film at the end of the cap has the Nusselt thickness (Eqs. 45 - 47).
  if (v_tb > v_gls) {
    const mu_l_si = mu_l / RE_CONST;                                                     // lbm/ft/s

    const nusselt = (/** @type {number} */ delta) => {        // delta = film thickness / d
      const g_n = (1.0 - 2.0 * delta) ** 2;                   // gas fraction of the Taylor bubble section
      const h_n = 1.0 - g_n;                                                             // Eq. 46
      const v_ngtb = v_tb - (v_tb - v_gls) * h_gls / g_n;                                // Eq. 47
      const v_nltb = (v_ngtb * g_n - v_m) / h_n;              // film velocity from the flux balance
      return { h_n, v_ngtb, v_nltb };
    };

    const nusselt_residual = (/** @type {number} */ delta) => {                          // Eq. 45 cubed
      const { h_n, v_nltb } = nusselt(delta);
      return (delta * d_ft) ** 3 - 0.75 * d_ft * mu_l_si * v_nltb * h_n / (GC * d_rho);
    };

    if (nusselt_residual(1e-9) < 0.0 && 0.0 < nusselt_residual(0.5 - 1e-9)) {
      const delta_n = ansBisect(nusselt_residual, 1e-9, 0.5 - 1e-9);
      const { v_nltb } = nusselt(delta_n);
      const l_c = (v_tb + v_nltb) ** 2 / (2.0 * GC);                                     // Eq. 44
      out.l_c = l_c;
      if (l_c >= l_tb) {
        const a = 1.0 - v_sg / v_tb;                                                     // Eq. 55
        const b = (v_sg - v_gls * h_gls) * l_ls / v_tb;                                  // Eqs. 52, 53
        const cc = (v_tb - v_lls) * h_lls / Math.sqrt(2.0 * GC);                         // Eq. 57
        const disc = cc * cc + a * b;
        if (a > 1e-9 && disc >= 0.0) {
          const x = (cc + Math.sqrt(disc)) / a;                     // = sqrt(L*_TB), Eq. 54
          const l_star = x * x;
          if (l_star > 0.0) {
            out.developing = true;
            out.l_tb_star = l_star;
          }
        }
      }
    }
  }

  // Developed (Eq. 60) and developing (Eq. 62) do not agree where they meet (at L_c = L_TB).  Eq. 60
  // treats the Taylor bubble as pure gas; Eq. 62 counts the liquid film in it through rho_TBA.  The
  // two therefore differ by about beta * rho_L * H_LTB, which here is roughly half the slug-unit
  // density, and the model steps: on a gas-lifted well the VLP curve jumped about 50 psi between two
  // neighbouring rates, enough to move the operating point.  Both of the paper's expressions are
  // kept, and they are blended over 1 <= L_c/L_TB <= ANS_DEV_BLEND so that the gradient is
  // continuous: at the switch the weight is 0, so the developed equations (which reproduce
  // Orkiszewski's measured well 22 best) still apply, and the developing equations take over once the
  // Taylor bubble is clearly shorter than its own cap.
  // THIS BLEND IS A DEVIATION FROM THE PAPER (see the README); its two end points are the paper's own.
  const rho_dev = (1.0 - beta) * rho_ls + beta * rho_g;                                  // Eq. 60
  const holdup_dev = (1.0 - beta) * h_lls + beta * h_ltb;
  let rho_elev = rho_dev;
  let beta_f = beta;
  let holdup = holdup_dev;
  if (out.developing) {
    const l_star = /** @type {number} */ (out.l_tb_star);
    const beta_e = l_star / (l_star + l_ls);                        // beta* = L*_TB / L*_SU
    const h_ltba = Math.min(2.0 * (v_tb - v_lls) * h_lls / Math.sqrt(2.0 * GC * l_star), 1.0);  // Eq. 64
    const rho_tba = rho_l * h_ltba + rho_g * (1.0 - h_ltba);                             // Eq. 63
    const rho_ing = (1.0 - beta_e) * rho_ls + beta_e * rho_tba;                          // Eq. 62
    const holdup_ing = (1.0 - beta_e) * h_lls + beta_e * h_ltba;
    const w = l_tb > 0.0 ? ansBlend(/** @type {number} */ (out.l_c) / l_tb) : 1.0;
    out.blend = w;
    rho_elev = (1.0 - w) * rho_dev + w * rho_ing;
    beta_f = (1.0 - w) * beta + w * beta_e;
    holdup = (1.0 - w) * holdup_dev + w * holdup_ing;
  }
  const re_ls = RE_CONST * rho_ls * v_m * d_ft / mu_ls;                                  // Eq. 66
  const f_ls = friction_factor(re_ls, eps_d);
  const friction = f_ls * rho_ls * v_m ** 2 / (2.0 * d_ft * GC) * (1.0 - beta_f);        // Eq. 65
  return { ...out, rho_elev, friction, f: f_ls, re: re_ls, holdup };
}

/**
 * Ansari et al. (1994) pressure gradient (psi per ft of pipe), same inputs and same kind of result as
 * beggs_brill_gradient.  The result has 'dpdl', 'hl' (liquid holdup of the pattern), 'regime'
 * ('bubble', 'dispersed', 'slug', 'annular', 'liquid' or 'gas'), 'hydrostatic', 'friction', 'f_tp',
 * 're', 'e_k' (always 0: the paper has no acceleration term) and, for slug flow, 'beta' (the Taylor
 * bubble fraction of the slug unit) and 'developing' (true while the Taylor bubble is still growing).
 * @param {number} p @param {number} angle_deg @param {number} d_in @param {number} roughness_in
 * @param {FlowConditions} c
 */
export function ansari_gradient(p, angle_deg, d_in, roughness_in, c) {
  check(p > 0 && d_in > 0, "Pressure and diameter must be > 0.");
  const d_ft = d_in / 12.0;
  const v_sl = c.v_sl;
  const v_sg = c.v_sg;
  const v_m = v_sl + v_sg;
  check(v_m > 0, "No flow: mixture velocity is zero.");
  const theta = radians(angle_deg);
  const sin_t = Math.sin(theta);
  const { rho_l, rho_g, mu_l, mu_g } = c;
  const sigma = c.sigma * GRAY_SIGMA_UNIT;                  // lbm/s2
  const eps_d = roughness_in / d_in;

  let regime;
  let hl;
  let fric;
  let hydro;
  /** @type {{f?: number, re?: number, beta?: number, developing?: boolean, delta?: number}} */
  let extra = {};

  if (v_sg < 1e-9 * v_m) {                                  // liquid only
    regime = "liquid";
    hl = 1.0;
    const re = RE_CONST * rho_l * v_m * d_ft / mu_l;
    const f = friction_factor(re, eps_d);
    fric = f * rho_l * v_m ** 2 / (2.0 * d_ft * GC);
    extra = { f, re };
    hydro = rho_l * sin_t;
  } else if (v_sl < 1e-9 * v_m) {                           // gas only
    regime = "gas";
    hl = 0.0;
    const re = RE_CONST * rho_g * v_m * d_ft / mu_g;
    const f = friction_factor(re, eps_d);
    fric = f * rho_g * v_m ** 2 / (2.0 * d_ft * GC);
    extra = { f, re };
    hydro = rho_g * sin_t;
  } else {
    const fp = ans_flow_pattern(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta);
    regime = fp.regime;
    if (regime === "bubble" || regime === "dispersed") {
      if (regime === "bubble") {
        const v0 = (GC * sigma * (rho_l - rho_g) / rho_l ** 2) ** 0.25;
        hl = ansBubbleHoldup(v_sl, v_sg, v0);                                            // Eq. 22
      } else {
        hl = v_sl / v_m;                                                                 // Eq. 19 (no slip)
      }
      const rho = rho_l * hl + rho_g * (1.0 - hl);                                       // Eqs. 16, 23
      const mu = mu_l * hl + mu_g * (1.0 - hl);                                          // Eqs. 17, 24
      const re = RE_CONST * rho * v_m * d_ft / mu;                                       // Eq. 28
      const f = friction_factor(re, eps_d);
      fric = f * rho * v_m ** 2 / (2.0 * d_ft * GC);                                     // Eq. 27
      hydro = rho * sin_t;                                                               // Eq. 26
      extra = { f, re };
    } else if (regime === "slug") {
      const sl = ansSlug(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d);
      hl = sl.holdup;
      fric = sl.friction;
      hydro = sl.rho_elev * sin_t;
      extra = { f: sl.f, re: sl.re, beta: sl.beta, developing: sl.developing };
    } else {
      const an = fp.annular
        || ans_annular_film_thickness(v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, eps_d, theta);
      hl = an.holdup;
      fric = an.friction;
      hydro = an.hydrostatic;
      extra = { f: an.f_sc, re: an.re_sc, delta: an.delta };
    }
  }
  return { dpdl: (hydro + fric) / 144.0, hl, regime, hydrostatic: hydro / 144.0,
           friction: fric / 144.0, f_tp: extra.f ?? 0.0, re: extra.re ?? 0.0, e_k: 0.0,
           beta: extra.beta ?? null, developing: extra.developing ?? null,
           delta: extra.delta ?? null };
}

// =====================================================================
// Duns and Ros (1963) - "Vertical flow of gas and liquid mixtures in wells"
// =====================================================================
// Duns, H. Jr. and Ros, N.C.J., Proc. 6th World Petroleum Congress, Frankfurt, 1963,
// Section II, Paper 22-PD6, p. 451.
//
// The pipe is described by four dimensionless numbers (the same ones Hagedorn and Brown use):
//     N   = N_LV, liquid velocity number          RN = N_GV, gas velocity number
//     N_d = pipe diameter number                  N_l = liquid viscosity number
// and three flow regions, each with its own slip velocity and its own wall friction:
//     Region I   (liquid continuous: bubble, plug and part of froth flow)   RN <= L1 + L2 N
//     Region II  (slug flow and the rest of froth flow)                     up to RN = 50 + 36 N
//     transition (between slug and mist)                                    50 + 36 N < RN < 75 + 84 N^0.75
//     Region III (gas continuous: mist flow, no slip)                       RN >= 75 + 84 N^0.75
// Slip velocity S (dimensionless) gives the liquid holdup, and with it the static gradient (Eq. 1).
// The wall friction is added as a fraction of the liquid static gradient (Eq. 10 for Regions I-II,
// Eq. 12 for III).  In the transition the gradient is interpolated on RN between the two region
// boundaries, at a fixed gas mass flow (section VII).  The acceleration term (Eq. 17) is used in the
// mist and transition ranges only, as the paper says.
//
// THE PAPER'S FUNCTIONS ARE CHARTS.  F1 - F4 (Fig. 5), L1, L2 (Fig. 6), F5 - F7 (Fig. 7) and f2
// (Fig. 9) were read from the scanned figures (axis-calibrated, curve traced and checked on an
// overlay) and are stored here as tables, interpolated on log(x) - the same numbers as the Python,
// copied across mechanically rather than retyped.  Each value is good to roughly +-2 % of the
// chart's reading; the chart's own scatter of the fit to its data is the 3 / 8 / 6 % the paper
// quotes.  f1 (Fig. 8) is the Moody diagram, so the Colebrook equation is used (Fanning factor =
// Darcy factor / 4).  Fig. 10 is the Weber-number correlation that Orkiszewski copied as C-21/C-22.
//
// Not used: Eq. 18 for wet mixtures.  It needs the dry oil and the water properties separately, and
// the gradient interface carries one blended liquid (as for every other correlation here).  The
// paper itself restricts it to a water cut below 10 %.  The correlation is for vertical flow; for an
// inclined pipe the static gradient is multiplied by sin(angle) and the friction is unchanged.

// Fig. 5: functions of the liquid viscosity number N_l
const DR_F1 = [
  [0.002, 0.002573, 0.00331, 0.004259, 0.005479, 0.007049, 0.009068, 0.01167, 0.01501, 0.01931, 0.02484, 0.03196, 0.04112, 0.0529, 0.06805, 0.08755, 0.1126, 0.1449, 0.1864, 0.2399, 0.3086, 0.397, 0.5107, 0.6571, 0.8453, 1.088, 1.399, 1.8],
  [1.253, 1.25, 1.245, 1.245, 1.245, 1.245, 1.241, 1.25, 1.259, 1.268, 1.293, 1.363, 1.483, 1.631, 1.782, 1.922, 2.011, 2.041, 2.041, 1.994, 1.894, 1.755, 1.612, 1.433, 1.255, 1.09, 0.9642, 0.8825]];
const DR_F2 = [
  [0.002, 0.002573, 0.00331, 0.004259, 0.005479, 0.007049, 0.009068, 0.01167, 0.01501, 0.01931, 0.02484, 0.03196, 0.04112, 0.0529, 0.06805, 0.08755, 0.1126, 0.1449, 0.1864, 0.2399, 0.3086, 0.397, 0.5107, 0.6571, 0.8453, 1.088, 1.399, 1.8],
  [0.2416, 0.2416, 0.2416, 0.2411, 0.2411, 0.2408, 0.2405, 0.2411, 0.246, 0.2667, 0.3046, 0.3777, 0.4709, 0.5807, 0.7116, 0.8472, 0.9499, 1.003, 1.015, 1.011, 0.9887, 0.9574, 0.9205, 0.881, 0.8393, 0.796, 0.7526, 0.7083]];
const DR_F3 = [
  [0.002, 0.002573, 0.00331, 0.004259, 0.005479, 0.007049, 0.009068, 0.01167, 0.01501, 0.01931, 0.02484, 0.03196, 0.04112, 0.0529, 0.06805, 0.08755, 0.1126, 0.1449, 0.1864, 0.2399, 0.3086, 0.397, 0.5107, 0.6571, 0.8453, 1.088, 1.399, 1.8],
  [0.822, 0.822, 0.8295, 0.8377, 0.8661, 0.9778, 1.124, 1.25, 1.481, 1.778, 2.05, 2.279, 2.511, 2.725, 2.924, 3.104, 3.253, 3.371, 3.525, 3.618, 3.693, 3.774, 3.849, 3.916, 3.981, 4.036, 4.082, 4.141]];
const DR_F4 = [
  [0.002, 0.002573, 0.00331, 0.004259, 0.005479, 0.007049, 0.009068, 0.01167, 0.01501, 0.01931, 0.02484, 0.03196, 0.04112, 0.0529, 0.06805, 0.08755, 0.1126, 0.1449, 0.1864, 0.2399, 0.3086, 0.397, 0.5107, 0.6571, 0.8453, 1.088, 1.399, 1.8],
  [-15.92, -8.31, -1.591, 4.567, 9.987, 15.76, 21.13, 26.25, 31.01, 35.75, 39.81, 44.17, 48.24, 51.08, 52.93, 53.88, 54.47, 54.85, 55.34, 55.44, 55.34, 55.05, 54.51, 54.76, 54.56, 54.56, 54.66, 54.76]];
// Fig. 7: functions of N_l (F6 is the part of F6' that does not depend on the diameter)
const DR_F5 = [
  [0.002, 0.002578, 0.003324, 0.004284, 0.005523, 0.00712, 0.009178, 0.01183, 0.01525, 0.01966, 0.02534, 0.03267, 0.04212, 0.05429, 0.06999, 0.09022, 0.1163, 0.1499, 0.1933, 0.2492, 0.3212, 0.414, 0.5337, 0.688, 0.8869, 1.143, 1.474, 1.9],
  [0.2193, 0.2147, 0.21, 0.2026, 0.1996, 0.1948, 0.1892, 0.1837, 0.1777, 0.1708, 0.1634, 0.1535, 0.1368, 0.1154, 0.09169, 0.07099, 0.05695, 0.04407, 0.04446, 0.04928, 0.05517, 0.06179, 0.07018, 0.07862, 0.08727, 0.09618, 0.1047, 0.1123]];
const DR_F6 = [
  [0.002, 0.002578, 0.003324, 0.004284, 0.005523, 0.00712, 0.009178, 0.01183, 0.01525, 0.01966, 0.02534, 0.03267, 0.04212, 0.05429, 0.06999, 0.09022, 0.1163, 0.1499, 0.1933, 0.2492, 0.3212, 0.414, 0.5337, 0.688, 0.8869, 1.143, 1.474, 1.9],
  [0.829, 0.5999, 0.3948, 0.2387, 0.1101, 0.0102, -0.05731, -0.09881, -0.1158, -0.1206, 0.2942, 0.7332, 1.006, 1.322, 1.615, 2.039, 2.166, 2.1, 2, 1.918, 1.851, 1.808, 1.779, 1.765, 1.761, 1.763, 1.773, 1.779]];
const DR_F7 = [
  [0.002, 0.002578, 0.003324, 0.004284, 0.005523, 0.00712, 0.009178, 0.01183, 0.01525, 0.01966, 0.02534, 0.03267, 0.04212, 0.05429, 0.06999, 0.09022, 0.1163, 0.1499, 0.1933, 0.2492, 0.3212, 0.414, 0.5337, 0.688, 0.8869, 1.143, 1.474, 1.9],
  [0.1312, 0.1267, 0.1201, 0.1131, 0.1053, 0.09798, 0.09077, 0.08349, 0.07637, 0.07017, 0.06406, 0.06109, 0.05689, 0.05395, 0.05079, 0.04763, 0.04447, 0.04131, 0.03815, 0.03499, 0.03182, 0.02866, 0.02719, 0.02614, 0.02524, 0.02438, 0.02376, 0.02321]];
// Fig. 6: limits of Region I, as functions of the diameter number N_d (RN <= L1 + L2 N)
const DR_L1 = [
  [16, 18.27, 20.87, 23.83, 27.21, 31.08, 35.49, 40.53, 46.28, 52.85, 60.36, 68.92, 78.71, 89.89, 102.6, 117.2, 133.9, 152.9, 174.6, 199.4, 227.7, 260],
  [1.991, 1.991, 1.99, 1.987, 1.967, 1.907, 1.753, 1.571, 1.394, 1.213, 1.064, 1.006, 1, 1, 1, 1, 1, 1.01, 1.01, 1.01, 1.01, 1.01]];
const DR_L2 = [
  [16, 18.27, 20.87, 23.83, 27.21, 31.08, 35.49, 40.53, 46.28, 52.85, 60.36, 68.92, 78.71, 89.89, 102.6, 117.2, 133.9, 152.9, 174.6, 199.4, 227.7, 260],
  [0.4862, 0.5273, 0.5781, 0.6383, 0.7005, 0.7644, 0.8321, 0.904, 0.9704, 1.01, 1.052, 1.076, 1.087, 1.097, 1.103, 1.111, 1.114, 1.125, 1.121, 1.119, 1.114, 1.111]];
// Fig. 9: friction factor f2 against f1 * R * N_d^(2/3), R = v_sg / v_sl
const DR_FRICTION_F2 = [
  [0.0014, 0.002386, 0.004066, 0.00693, 0.01181, 0.02013, 0.0343, 0.05846, 0.09963, 0.1698, 0.2894, 0.4932, 0.8405, 1.432, 2.441, 4.161, 7.091, 12.08, 20.59, 35.1, 59.82, 101.9, 173.7, 296.1, 504.6, 860],
  [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0.9757, 0.8045, 0.673, 0.5623, 0.4647, 0.3866, 0.3195, 0.2735, 0.2431, 0.2206, 0.2032, 0.2005, 0.2005, 0.201, 0.204]];

/**
 * Value of a tabulated chart curve at x: straight line in log(x) between the nodes, constant beyond
 * the first and last node (the charts end there).
 * @param {number} x @param {number[][]} table
 */
function drTable(x, table) {
  const xs = table[0], ys = table[1];
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  // the same index Python's bisect.bisect_right(xs, x) - 1 gives
  let lo = 0, hi = xs.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (x < xs[mid]) hi = mid; else lo = mid + 1;
  }
  const i = lo - 1;
  const w = (Math.log(x) - Math.log(xs[i])) / (Math.log(xs[i + 1]) - Math.log(xs[i]));
  return ys[i] + w * (ys[i + 1] - ys[i]);
}

/**
 * The Duns and Ros dimensionless numbers (field units in, same constants as hagedorn_brown).
 * f_v converts a velocity in ft/s into a velocity number.
 * @param {number} v_sl @param {number} v_sg @param {number} rho_l @param {number} sigma
 * @param {number} mu_l @param {number} d_ft
 * @returns {{n: number, rn: number, n_d: number, n_l: number, f_v: number}}
 */
export function dr_numbers(v_sl, v_sg, rho_l, sigma, mu_l, d_ft) {
  const f_v = 1.938 * (rho_l / sigma) ** 0.25;
  return { n: f_v * v_sl, rn: f_v * v_sg,
           n_d: 120.872 * d_ft * (rho_l / sigma) ** 0.5,
           n_l: 0.15726 * mu_l * (1.0 / (rho_l * sigma ** 3)) ** 0.25,
           f_v };
}

/**
 * RN at the end of Region II (Eq. 7) and at the start of Region III (Eq. 9).  The end of Region I
 * (L1 + L2 N, Eq. 5) also needs N_d and is found in dr_flow_region().
 * @param {number} n @returns {[number, number]}
 */
export function dr_region_limits(n) {
  return [50.0 + 36.0 * n, 75.0 + 84.0 * n ** 0.75];
}

/**
 * Dimensionless slip velocity of Region I (Eq. 4):
 *   S = F1 + F2 N + F3' (RN / (1 + N))^2,  F3' = F3 - F4 / N_d
 * @param {number} n @param {number} rn @param {number} n_d @param {number} n_l
 */
export function dr_slip_region1(n, rn, n_d, n_l) {
  const f3p = drTable(n_l, DR_F3) - drTable(n_l, DR_F4) / n_d;
  return drTable(n_l, DR_F1) + drTable(n_l, DR_F2) * n + f3p * (rn / (1.0 + n)) ** 2;
}

/**
 * Dimensionless slip velocity of Region II (Eq. 6):
 *   S = (1 + F5) (RN^0.982 + F6') / (1 + F7 N)^2,  F6' = 0.029 N_d + F6
 * @param {number} n @param {number} rn @param {number} n_d @param {number} n_l
 */
export function dr_slip_region2(n, rn, n_d, n_l) {
  const f6p = 0.029 * n_d + drTable(n_l, DR_F6);
  return (1.0 + drTable(n_l, DR_F5)) * (rn ** 0.982 + f6p) / (1.0 + drTable(n_l, DR_F7) * n) ** 2;
}

/**
 * Liquid holdup from the dimensionless slip S (Eqs. 2 and 3): v_s = S / f_v is the slip velocity
 * v_sg/(1-H) - v_sl/H, solved for H.  S below zero (liquid faster than gas) is not possible upward
 * and is taken as 0.
 * @param {number} v_sl @param {number} v_sg @param {number} s @param {number} f_v
 */
export function dr_holdup(v_sl, v_sg, s, f_v) {
  const v_s = Math.max(s, 0.0) / f_v;
  // v_sg/(1-H) - v_sl/H = v_s  ->  v_s H^2 - (v_s - v_sg - v_sl) H - v_sl = 0, written so v_s = 0 is allowed
  const b = v_s - v_sg - v_sl;
  return 2.0 * v_sl / (-b + Math.sqrt(b * b + 4.0 * v_s * v_sl));
}

/**
 * Fanning friction factor of Fig. 8: Colebrook / 4, and Eq. 15 for a relative roughness above 0.05
 * (the Moody diagram stops there).
 * @param {number} re @param {number} eps_d
 */
function drFanning(re, eps_d) {
  if (eps_d > 0.05 && re >= 4000.0) {
    return 1.0 / (4.0 * Math.log10(0.27 * eps_d)) ** 2 + 0.067 * eps_d ** 1.73;
  }
  return friction_factor(re, eps_d) / 4.0;
}

/**
 * Relative roughness e/D of the liquid film on the wall in mist flow (Eq. 14 and Fig. 10).
 * Weber number We = rho_g v_sg^2 e / sigma is 34, or higher for a viscous liquid
 * (We = 174.8 X^0.302 with X = rho_g v_sg^2 mu_L^2 / (rho_L sigma^2) above X = 0.0044 - the form
 * Orkiszewski copied as Eqs. C-21 / C-22).  The result is kept between the pipe's own roughness
 * (at least 0.001) and 0.5 (liquid bridges).
 * @param {number} v_sg @param {number} rho_g @param {number} rho_l @param {number} mu_l
 * @param {number} sigma_dyne @param {number} d_ft @param {number} pipe_eps_d
 * @returns {[number, number]} [relative roughness, Weber number]
 */
export function dr_mist_film_roughness(v_sg, rho_g, rho_l, mu_l, sigma_dyne, d_ft, pipe_eps_d) {
  const sigma = sigma_dyne * GRAY_SIGMA_UNIT;                            // lbm/s2
  const x = 4.52e-7 * (v_sg * mu_l / sigma) ** 2 * rho_g / rho_l;        // 4.52e-7 turns cP into lbm/ft/s squared
  const we = x > 0.0 ? Math.max(34.0, 174.8 * x ** 0.302) : 34.0;
  const e_d = we * sigma / (rho_g * v_sg ** 2 * d_ft);
  return [Math.min(Math.max(e_d, 0.001, pipe_eps_d), 0.5), we];
}

/**
 * Holdup, static gradient and friction gradient of one region, both as fractions of the liquid
 * static gradient (G_st, G_fr).  region = 1, 2 or 3.
 * @param {number} region @param {number} v_sl @param {number} v_sg @param {number} rho_l
 * @param {number} rho_g @param {number} mu_l @param {number} mu_g @param {number} sigma
 * @param {number} d_ft @param {number} pipe_eps_d
 * @returns {[number, number, number, number, number]} [holdup, G_st, G_fr, f used, Reynolds number]
 */
function drGradientParts(region, v_sl, v_sg, rho_l, rho_g, mu_l, mu_g, sigma, d_ft, pipe_eps_d) {
  const nm = dr_numbers(v_sl, v_sg, rho_l, sigma, mu_l, d_ft);
  const n = nm.n, rn = nm.rn, n_d = nm.n_d, n_l = nm.n_l;
  let h, g_fr, f_used, re;
  if (region === 3) {
    h = v_sl / (v_sl + v_sg);                                            // Eq. 8: no slip
    const [eps_d] = dr_mist_film_roughness(v_sg, rho_g, rho_l, mu_l, sigma, d_ft, pipe_eps_d);
    re = RE_CONST * rho_g * v_sg * d_ft / mu_g;
    const f1 = drFanning(re, eps_d);
    g_fr = 2.0 * f1 * (rho_g / rho_l) * rn ** 2 / n_d;                   // Eq. 12
    f_used = f1;
  } else {
    const s = region === 1 ? dr_slip_region1(n, rn, n_d, n_l) : dr_slip_region2(n, rn, n_d, n_l);
    h = dr_holdup(v_sl, v_sg, s, nm.f_v);
    re = RE_CONST * rho_l * v_sl * d_ft / mu_l;                          // liquid Reynolds number
    const f1 = drFanning(re, pipe_eps_d);
    const r = v_sg / v_sl;
    const f2 = drTable(f1 * r * n_d ** (2.0 / 3.0), DR_FRICTION_F2);
    const f3 = 1.0 + f1 * Math.sqrt(r / 50.0);
    f_used = f1 * f2 / f3;                                               // Eq. 11
    g_fr = 2.0 * f_used * n * (n + rn) / n_d;                            // Eq. 10
  }
  const g_st = h + (1.0 - h) * rho_g / rho_l;                            // Eq. 1
  return [h, g_st, g_fr, f_used, re];
}

/**
 * Region of the Duns and Ros correlation: 'bubble' (Region I), 'slug' (Region II), 'transition' or
 * 'mist' (Region III).  rn_1 is the end of I, rn_2 the end of II, rn_3 the start of III.
 * @param {number} v_sl @param {number} v_sg @param {number} rho_l @param {number} sigma
 * @param {number} mu_l @param {number} d_ft
 * @returns {{n: number, rn: number, n_d: number, n_l: number, f_v: number, regime: string,
 *            rn_1: number, rn_2: number, rn_3: number}}
 */
export function dr_flow_region(v_sl, v_sg, rho_l, sigma, mu_l, d_ft) {
  const nm = dr_numbers(v_sl, v_sg, rho_l, sigma, mu_l, d_ft);
  const rn_1 = drTable(nm.n_d, DR_L1) + drTable(nm.n_d, DR_L2) * nm.n;       // Eq. 5
  const [rn_2, rn_3] = dr_region_limits(nm.n);
  let regime;
  if (nm.rn <= rn_1) regime = "bubble";
  else if (nm.rn <= rn_2) regime = "slug";
  else if (nm.rn < rn_3) regime = "transition";
  else regime = "mist";
  return { ...nm, regime, rn_1, rn_2, rn_3 };
}

/**
 * Duns and Ros pressure gradient (psi per ft of pipe), same inputs and same kind of result as
 * beggs_brill_gradient.  'regime' is 'bubble' (Region I), 'slug' (Region II), 'transition',
 * 'mist' (Region III) or 'gas'; 'f_tp' is the paper's f_w, or f1 in mist flow; 're' is the Reynolds
 * number f1 was read at; 'e_k' is the acceleration term of Eq. 17, only in the transition and mist
 * ranges; 'rn' and 'n' are the velocity numbers.
 * @param {number} p @param {number} angle_deg @param {number} d_in @param {number} roughness_in
 * @param {FlowConditions} c
 * @returns {{dpdl: number, hl: number, regime: string, hydrostatic: number, friction: number,
 *            f_tp: number, re: number, e_k: number, rn: number, n: number}}
 */
export function duns_ros_gradient(p, angle_deg, d_in, roughness_in, c) {
  check(p > 0 && d_in > 0, "Pressure and diameter must be > 0.");
  const d_ft = d_in / 12.0;
  const v_sl = c.v_sl, v_sg = c.v_sg;
  check(v_sl + v_sg > 0, "No flow: mixture velocity is zero.");
  const sin_t = Math.sin(radians(angle_deg));
  const rho_l = c.rho_l, rho_g = c.rho_g, mu_l = c.mu_l, mu_g = c.mu_g, sigma = c.sigma;
  const pipe_eps_d = roughness_in / d_in;
  const mass_flux = rho_l * v_sl + rho_g * v_sg;                            // lb/s/ft2

  if (v_sl < 1e-9 * (v_sl + v_sg)) {                                        // no liquid: single-phase gas
    const re = RE_CONST * rho_g * v_sg * d_ft / mu_g;
    const f = friction_factor(re, pipe_eps_d);
    const hydrostatic = rho_g * sin_t / 144.0;
    const friction = f * rho_g * v_sg ** 2 / (2.0 * GC * d_ft) / 144.0;
    const e_k = Math.min(mass_flux * v_sg / (GC * p * 144.0), 0.95);
    return { dpdl: (hydrostatic + friction) / (1.0 - e_k), hl: 0.0, regime: "gas",
             hydrostatic, friction, f_tp: f, re, e_k,
             rn: 1.938 * v_sg * (rho_l / sigma) ** 0.25, n: 0.0 };
  }

  const fp = dr_flow_region(v_sl, v_sg, rho_l, sigma, mu_l, d_ft);
  const regime = fp.regime;
  let h, g_st, g_fr, f_used, re;
  if (regime === "bubble" || regime === "slug" || regime === "mist") {
    const region = { bubble: 1, slug: 2, mist: 3 }[regime];
    [h, g_st, g_fr, f_used, re] = drGradientParts(region, v_sl, v_sg, rho_l, rho_g, mu_l, mu_g,
                                                  sigma, d_ft, pipe_eps_d);
  } else {
    // Transition: linear in RN between the end of Region II and the start of Region III (section
    // VII).  The mist end is evaluated at the gas velocity of that RN with the gas density that
    // keeps rho_g v_sg fixed.
    const v_sg_2 = fp.rn_2 / fp.f_v;
    const v_sg_3 = fp.rn_3 / fp.f_v;
    const [h2, st2, fr2, f2used, re2] = drGradientParts(2, v_sl, v_sg_2, rho_l, rho_g, mu_l, mu_g,
                                                        sigma, d_ft, pipe_eps_d);
    const [h3, st3, fr3] = drGradientParts(3, v_sl, v_sg_3, rho_l, rho_g * v_sg / v_sg_3, mu_l,
                                           mu_g, sigma, d_ft, pipe_eps_d);
    f_used = f2used; re = re2;
    const w3 = (fp.rn - fp.rn_2) / (fp.rn_3 - fp.rn_2);                   // weight of the mist end
    h = (1.0 - w3) * h2 + w3 * h3;
    g_st = (1.0 - w3) * st2 + w3 * st3;
    g_fr = (1.0 - w3) * fr2 + w3 * fr3;
  }

  const hydrostatic = g_st * rho_l * sin_t / 144.0;        // G = (dp/dh) / (rho_L g), g / gc = 1
  const friction = g_fr * rho_l / 144.0;
  let e_k = 0.0;
  if (regime === "transition" || regime === "mist") {
    e_k = Math.min(mass_flux * v_sg / (GC * p * 144.0), 0.95);            // Eq. 17
  }
  return { dpdl: (hydrostatic + friction) / (1.0 - e_k), hl: h, regime,
           hydrostatic, friction, f_tp: f_used, re, e_k, rn: fp.rn, n: fp.n };
}

// =====================================================================
// Mukherjee & Brill (1983 / 1985) - holdup and pressure drop for inclined two-phase flow
// =====================================================================
// Mukherjee, H. and Brill, J.P., "Liquid Holdup Correlations for Inclined Two-Phase Flow",
// J. Pet. Tech., May 1983, p. 1003 (SPE 10923).  This paper gives the HOLDUP equation (Eq. 1) and
// its coefficients (Table 1):
//     H_L = exp[ (c1 + c2 sin(a) + c3 sin(a)^2 + c4 N_L^2) * N_gv^c5 / N_Lv^c6 ]
// with one set of c1 ... c6 for uphill and horizontal flow (all flow patterns), one for downhill
// stratified flow and one for the other downhill patterns.  N_Lv, N_gv and N_L are the same
// dimensionless numbers as in Duns & Ros and Hagedorn & Brown.
//
// The flow-pattern map and the friction method are from the two companion papers:
//   Mukherjee, H. and Brill, J.P., "Empirical Equations to Predict Flow Patterns in Two-Phase
//       Inclined Flow", Int. J. Multiphase Flow 11 (3), 1985, p. 299: Eqs. [1]-[4] and Fig. 16;
//   Mukherjee, H. and Brill, J.P., "Pressure Drop Correlations for Inclined Two-Phase Flow",
//       J. Energy Resources Technology 107, Dec. 1985, p. 549: Eqs. (1)-(27), Table 2.
//
//     flow pattern   uphill (angle > 0)           downhill and horizontal (angle <= 0)
//     annular-mist   N_gv > N_gv(SM)              N_gv > N_gv(SM)
//     bubble         N_Lv > N_Lv(BS)              N_gv <= N_gv(BS)  (and, for |angle| <= 30, N_Lv > N_Lv(ST))
//     stratified     (none)                       N_Lv <= N_Lv(ST)  (steeper than 30 degrees: N_gv > N_gv(BS) too)
//     slug           the rest                     the rest
//
//     friction       bubble, slug : Moody factor at the no-slip Reynolds number, on the slip density
//                    annular-mist : the same factor times f_R(H_R), H_R = no-slip holdup / holdup,
//                                   applied to the no-slip density
//                    stratified   : Eq. 15, the momentum balance of the gas on a flat interface.  The
//                                   paper's "smooth interface" has no interfacial shear formula, so it
//                                   is neglected.  No acceleration.
//
// Printed Eqs. 26-27 write the wall shear as f*gamma*v^2/(2g) with a MOODY factor f, which is four
// times the usual Fanning shear f*rho*v^2/8; the Darcy-Weisbach pressure drop of Eq. 2 only comes out
// right with the /8 form, so that is what is coded here.

/** (c1 ... c6) of Table 1 */
export const MB_COEFFICIENTS = {
  uphill: [-0.380113, 0.129875, -0.119788, 2.343227, 0.475686, 0.288657],
  downhill_stratified: [-1.330282, 4.808139, 4.171584, 56.262268, 0.079951, 0.504887],
  downhill_other: [-0.516644, 0.789805, 0.551627, 15.519214, 0.371771, 0.393952],
};

/** Annular-mist friction ratio f_R against H_R = (no-slip holdup) / (holdup)  (1985 paper, tabulated) */
export const MB_FRICTION_RATIO = [[0.01, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0, 10.0],
                                  [1.00, 0.98, 1.20, 1.25, 1.30, 1.25, 1.00, 1.00]];

/**
 * Liquid velocity number N_Lv, gas velocity number N_gv and liquid viscosity number N_L (field units).
 * @param {number} v_sl @param {number} v_sg @param {number} rho_l @param {number} sigma @param {number} mu_l
 */
export function mb_numbers(v_sl, v_sg, rho_l, sigma, mu_l) {
  const f_v = 1.938 * (rho_l / sigma) ** 0.25;
  return { n_lv: f_v * v_sl, n_gv: f_v * v_sg,
           n_l: 0.15726 * mu_l * (1.0 / (rho_l * sigma ** 3)) ** 0.25 };
}

/**
 * Flow pattern of the Mukherjee & Brill map (Fig. 16 of the flow-pattern paper): 'annular', 'bubble',
 * 'slug' or 'stratified' (downhill or horizontal only).  Needs N_lv > 0 and N_gv > 0.  The boundaries
 * that do not apply are null.
 * @param {number} n_lv @param {number} n_gv @param {number} n_l @param {number} angle_deg
 */
export function mb_flow_pattern(n_lv, n_gv, n_l, angle_deg) {
  const sin_a = Math.sin(radians(angle_deg));
  const n_gv_sm = 10.0 ** (1.401 - 2.694 * n_l + 0.521 * n_lv ** 0.329);
  /** @type {{n_gv_sm: number, n_lv_bs: number | null, n_gv_bs: number | null,
   *          n_lv_st: number | null, regime?: string}} */
  const out = { n_gv_sm, n_lv_bs: null, n_gv_bs: null, n_lv_st: null };
  if (angle_deg > 0.0) {              // uphill only; horizontal follows the downhill branch
    out.n_lv_bs = 10.0 ** (Math.log10(n_gv) + 0.940 + 0.074 * sin_a - 0.855 * sin_a ** 2 + 3.695 * n_l);
  } else {
    const log_lv = Math.log10(n_lv);
    out.n_gv_bs = 10.0 ** (0.431 - 3.003 * n_l - 1.138 * log_lv * sin_a
                           - 0.429 * log_lv ** 2 * sin_a + 1.132 * sin_a);
    out.n_lv_st = 10.0 ** (0.321 - 0.017 * n_gv - 4.267 * sin_a - 2.972 * n_l
                           - 0.033 * Math.log10(n_gv) ** 2 - 3.925 * sin_a ** 2);
  }
  let regime;
  if (n_gv > n_gv_sm) {
    regime = "annular";
  } else if (angle_deg > 0.0) {
    regime = n_lv > /** @type {number} */ (out.n_lv_bs) ? "bubble" : "slug";
  } else if (Math.abs(angle_deg) > 30.0) {
    if (n_gv > /** @type {number} */ (out.n_gv_bs)) {
      regime = n_lv > /** @type {number} */ (out.n_lv_st) ? "slug" : "stratified";
    } else {
      regime = "bubble";
    }
  } else if (n_lv > /** @type {number} */ (out.n_lv_st)) {
    regime = n_gv > /** @type {number} */ (out.n_gv_bs) ? "slug" : "bubble";
  } else {
    regime = "stratified";
  }
  out.regime = regime;
  return out;
}

/**
 * Liquid holdup of Mukherjee & Brill, Eq. 1 with the coefficients of Table 1 (kept between 0 and 1).
 * regime is only needed for downhill flow (stratified or not).
 * @param {number} n_lv @param {number} n_gv @param {number} n_l @param {number} angle_deg @param {string} regime
 */
export function mb_holdup(n_lv, n_gv, n_l, angle_deg, regime) {
  const c = angle_deg >= 0.0
    ? MB_COEFFICIENTS.uphill
    : (regime === "stratified" ? MB_COEFFICIENTS.downhill_stratified : MB_COEFFICIENTS.downhill_other);
  const sin_a = Math.sin(radians(angle_deg));
  const t1 = c[0] + c[1] * sin_a + c[2] * sin_a ** 2 + c[3] * n_l ** 2;
  const x = t1 * n_gv ** c[4] / n_lv ** c[5];
  return x >= 0.0 ? 1.0 : Math.exp(Math.max(x, -700.0));   // a positive exponent would give H_L > 1
}

/**
 * Angle delta (radians, 0 to 2 pi) of the liquid-wetted part of the wall for a flat liquid layer of
 * holdup H_L:  (delta - sin delta) / (2 pi) = H_L, found by halving the interval.
 * @param {number} h_l
 */
export function mb_stratified_angle(h_l) {
  let lo = 0.0;
  let hi = 2.0 * Math.PI;
  for (let i = 0; i < 100; i++) {
    const mid = 0.5 * (lo + hi);
    if ((mid - Math.sin(mid)) / (2.0 * Math.PI) < h_l) lo = mid;
    else hi = mid;
  }
  return 0.5 * (lo + hi);
}

/**
 * Friction gradient (lbf/ft2 per ft) of stratified flow, Eq. 15 of the 1985 pressure-drop paper with
 * the interface shear neglected (smooth interface): the wall shear of the gas over its wetted wall,
 * divided by the area of the gas.
 *     friction = tau_wg * P_g / A_g,     tau_wg = f_g * rho_g * v_g^2 / (8 g_c)
 * The gas runs at v_g = v_sg / (1 - H_L) and its Reynolds number uses the hydraulic diameter D_Eg of
 * Eq. 25.  Returns [friction, extras].
 * @param {number} h_l @param {number} v_sg @param {number} rho_g @param {number} mu_g
 * @param {number} d_ft @param {number} eps_d
 * @returns {[number, {f: number, re: number, delta: number}]}
 */
export function mb_stratified_friction(h_l, v_sg, rho_g, mu_g, d_ft, eps_d) {
  const h = Math.min(Math.max(h_l, 1e-6), 1.0 - 1e-6);
  const delta = mb_stratified_angle(h);                                            // Eq. 20, solved for delta
  const d_eg = d_ft * (2.0 * Math.PI - (delta - Math.sin(delta)))
                    / (2.0 * Math.PI - delta + 2.0 * Math.sin(0.5 * delta));       // Eq. 25
  const v_g = v_sg / (1.0 - h);
  const re_g = RE_CONST * rho_g * v_g * d_eg / mu_g;
  const f_g = friction_factor(re_g, eps_d);
  const tau_g = f_g * rho_g * v_g ** 2 / (8.0 * GC);
  const perimeter = Math.PI * d_ft;
  const p_g = (1.0 - delta / (2.0 * Math.PI)) * perimeter;                         // Eq. 23
  const a_g = (1.0 - h) * Math.PI * d_ft ** 2 / 4.0;                               // Eq. 21
  return [tau_g * p_g / a_g, { f: f_g, re: re_g, delta }];
}

/**
 * Mukherjee & Brill pressure gradient (psi per ft of pipe), same inputs and same kind of result as
 * beggs_brill_gradient.  Works for any angle: uphill, horizontal and downhill.  The result has
 * 'dpdl', 'hl', 'regime' ('bubble', 'slug', 'annular', 'stratified', or 'liquid' / 'gas' for one
 * phase only), 'hydrostatic', 'friction', 'f_tp' (the Moody factor used), 're', 'e_k' and the three
 * dimensionless numbers 'n_lv', 'n_gv', 'n_l'.
 * @param {number} p @param {number} angle_deg @param {number} d_in @param {number} roughness_in
 * @param {FlowConditions} c
 */
export function mukherjee_brill_gradient(p, angle_deg, d_in, roughness_in, c) {
  check(p > 0 && d_in > 0, "Pressure and diameter must be > 0.");
  const d_ft = d_in / 12.0;
  const v_sl = c.v_sl;
  const v_sg = c.v_sg;
  const v_m = v_sl + v_sg;
  check(v_m > 0, "No flow: mixture velocity is zero.");
  const sin_a = Math.sin(radians(angle_deg));
  const { rho_l, rho_g, mu_l, mu_g, sigma } = c;
  const eps_d = roughness_in / d_in;
  const nm = mb_numbers(v_sl, v_sg, rho_l, sigma, mu_l);

  if (v_sl < 1e-9 * v_m || v_sg < 1e-9 * v_m) {                    // one phase only
    const gas = v_sl < 1e-9 * v_m;
    const rho = gas ? rho_g : rho_l;
    const mu = gas ? mu_g : mu_l;
    const v = gas ? v_sg : v_sl;
    const re = RE_CONST * rho * v * d_ft / mu;
    const f = friction_factor(re, eps_d);
    const hydrostatic = rho * sin_a / 144.0;
    const friction = f * rho * v ** 2 / (2.0 * GC * d_ft) / 144.0;
    const e_k = gas ? Math.min(rho * v * v / (GC * p * 144.0), 0.95) : 0.0;
    return { dpdl: (hydrostatic + friction) / (1.0 - e_k), hl: gas ? 0.0 : 1.0,
             regime: gas ? "gas" : "liquid", hydrostatic, friction,
             f_tp: f, re, e_k, ...nm };
  }

  const fp = mb_flow_pattern(nm.n_lv, nm.n_gv, nm.n_l, angle_deg);
  const regime = /** @type {string} */ (fp.regime);
  const h_l = mb_holdup(nm.n_lv, nm.n_gv, nm.n_l, angle_deg, regime);
  const lam = v_sl / v_m;                                          // no-slip holdup
  let rho_s = h_l * rho_l + (1.0 - h_l) * rho_g;                    // slip (holdup) density
  const rho_ns = lam * rho_l + (1.0 - lam) * rho_g;
  const mu_ns = lam * mu_l + (1.0 - lam) * mu_g;
  const re_ns = RE_CONST * rho_ns * v_m * d_ft / mu_ns;
  let friction;
  let f_used;
  let re_used;
  if (regime === "stratified") {
    const [fr, extra] = mb_stratified_friction(h_l, v_sg, rho_g, mu_g, d_ft, eps_d);
    friction = fr;
    f_used = extra.f;
    re_used = extra.re;
    rho_s = rho_g;                                                 // Eq. 15: the weight of the gas column only
  } else {
    const f_ns = friction_factor(re_ns, eps_d);
    if (regime === "annular") {
      const [xs, ys] = MB_FRICTION_RATIO;
      const h_r = Math.min(Math.max(lam / Math.max(h_l, 1e-9), xs[0]), xs[xs.length - 1]);
      // the same index Python's bisect.bisect_right(xs, h_r) - 1 gives
      let i = 0;
      while (i < xs.length && xs[i] <= h_r) i += 1;
      i = Math.min(Math.max(i - 1, 0), xs.length - 2);
      const f_r = ys[i] + (ys[i + 1] - ys[i]) * (h_r - xs[i]) / (xs[i + 1] - xs[i]);  // straight line in H_R
      f_used = f_ns * f_r;
      friction = f_used * rho_ns * v_m ** 2 / (2.0 * GC * d_ft);
    } else {
      f_used = f_ns;
      friction = f_ns * rho_s * v_m ** 2 / (2.0 * GC * d_ft);
    }
    re_used = re_ns;
  }
  const hydrostatic = rho_s * sin_a / 144.0;
  friction = friction / 144.0;
  // no acceleration in stratified flow
  const e_k = regime === "stratified" ? 0.0 : Math.min(rho_s * v_m * v_sg / (GC * p * 144.0), 0.95);
  return { dpdl: (hydrostatic + friction) / (1.0 - e_k), hl: h_l, regime, hydrostatic,
           friction, f_tp: f_used, re: re_used, e_k, ...nm };
}

// =====================================================================
// Fluids: turn (rate, pressure, temperature) into velocities and fluid properties
// =====================================================================
// Each fluid has two methods used by the traverse:
//     conditions(rate, p, T, d_in)  -> the flow conditions the gradient functions want
//     thermalData(rate)             -> [mass rate lb/h, heat capacity] for the temperature profile
//
// In the Python these are dataclasses; here they are classes with the same fields and the same
// defaults, built from one object so that a call reads the same way in both languages.

/** Cross-section area (ft2) of a pipe of inner diameter d_in (inches). @param {number} d_in */
function pipeArea(d_in) {
  return Math.PI * (d_in / 12.0) ** 2 / 4.0;
}

/** Water density (lb/ft3) at about standard conditions. @param {number} salinity */
function waterDensitySc(salinity) {
  return pvt.waterProperties(14.7, 60.0, salinity).rho_w;
}

/**
 * An oil well producing oil, water and gas, with continuous gas lift if asked for.
 *
 * Fields (all optional but api, gas_sg and rsb):
 *   api, gas_sg, rsb      stock-tank oil gravity (API), gas gravity (air = 1), solution GOR at Pb
 *   water_cut             water fraction of the liquid rate, 0 - 1
 *   gor                   producing GOR (scf/STB); null = the same as rsb
 *   salinity              water salinity (wt %)
 *   pb_meas               measured bubble point (psia), optional
 *   pvt_method            Pb, Rs, Bo correlation (see pvt.js)
 *   visc_method           oil viscosity correlation
 *   pvt_match             numbers from PVT matching to lab data, optional
 *   injection_gas_rate    gas lift gas, Mscf/d (0 = no gas lift)
 *   injection_md          depth of the injection point, ft MD
 *   injection_gas_sg      gravity of the injected gas; null = the same as gas_sg
 */
export class OilWaterFluid {
  /**
   * @param {{api: number, gas_sg: number, rsb: number, water_cut?: number, gor?: number | null,
   *          salinity?: number, pb_meas?: number | null, pvt_method?: string, visc_method?: string,
   *          pvt_match?: any, injection_gas_rate?: number, injection_md?: number | null,
   *          injection_gas_sg?: number | null}} spec
   */
  constructor(spec) {
    this.api = spec.api;
    this.gas_sg = spec.gas_sg;
    this.rsb = spec.rsb;
    this.water_cut = spec.water_cut ?? 0.0;
    this.gor = spec.gor ?? null;
    this.salinity = spec.salinity ?? 3.0;
    this.pb_meas = spec.pb_meas ?? null;
    this.pvt_method = spec.pvt_method ?? "glaso";
    this.visc_method = spec.visc_method ?? "beal";
    this.pvt_match = spec.pvt_match ?? null;
    this.injection_gas_rate = spec.injection_gas_rate ?? 0.0;
    this.injection_md = spec.injection_md ?? null;
    this.injection_gas_sg = spec.injection_gas_sg ?? null;

    check(0.0 <= this.water_cut && this.water_cut <= 1.0, "Water cut must be between 0 and 1.");
    check(this.injection_gas_rate >= 0.0, "The gas injection rate cannot be negative.");
    check(this.injection_gas_rate === 0.0 || (this.injection_md !== null && this.injection_md > 0.0),
          "Gas lift needs an injection depth above the perforations (greater than 0).");
    check(this.api > 0 && this.gas_sg > 0 && this.rsb > 0, "api, gas_sg and rsb must be > 0.");
  }

  /** The producing GOR (scf/STB): the one given, or the solution GOR at the bubble point. */
  producingGor() {
    return this.gor !== null ? this.gor : this.rsb;
  }

  /** Gravity of the injected gas (air = 1). */
  injectedGasSg() {
    return this.injection_gas_sg !== null ? this.injection_gas_sg : this.gas_sg;
  }

  /**
   * Flow conditions at pressure p and temperature T, for a liquid rate (STB/d).
   * inj_scfd is gas lift gas (scf/d) that has already joined the flow at this point (0 below the
   * injection point).
   * @param {number} rate @param {number} p @param {number} T @param {number} d_in @param {number} [inj_scfd]
   * @returns {FlowConditions}
   */
  conditions(rate, p, T, d_in, inj_scfd = 0.0) {
    check(rate > 0, "Rate must be > 0.");
    const q_o = rate * (1.0 - this.water_cut);
    const q_w = rate * this.water_cut;
    const o = pvt.oilProperties(p, T, this.api, this.gas_sg, this.rsb, this.pb_meas,
                                this.pvt_method, this.visc_method, this.pvt_match);
    const w = pvt.waterProperties(p, T, this.salinity);
    const g = pvt.gasProperties(p, T, this.gas_sg);

    const free_gor = Math.max(this.producingGor() - o.rs, 0.0);       // gas that is NOT dissolved
    const vol_o = q_o * o.bo * 5.615;                                 // ft3/d at pressure p
    const vol_w = q_w * w.bw * 5.615;
    let vol_g = q_o * free_gor * g.bg;
    let rho_gas = g.rho_g;
    let mu_gas = g.mu_g;
    if (inj_scfd > 0.0) {
      // Gas lift gas joins the formation gas.  Its volume at p and T comes from its own gravity;
      // density and viscosity of the gas mixture are the volume-weighted averages of the two gases.
      const gi = pvt.gasProperties(p, T, this.injectedGasSg());
      const vol_i = inj_scfd * gi.bg;
      const vol_total = vol_g + vol_i;
      rho_gas = (vol_g * g.rho_g + vol_i * gi.rho_g) / vol_total;
      mu_gas = (vol_g * g.mu_g + vol_i * gi.mu_g) / vol_total;
      vol_g = vol_total;
    }
    const area = pipeArea(d_in);
    const frac_o = vol_o / (vol_o + vol_w);                           // oil share of the liquid volume

    const sigma_o = sigma_oil_gas(this.api, T, p);
    const sigma_w = sigma_water_gas(T, p);
    return {
      v_sl: (vol_o + vol_w) / area / 86400.0,
      v_sg: vol_g / area / 86400.0,
      rho_l: frac_o * o.rho_o + (1.0 - frac_o) * w.rho_w,
      rho_g: rho_gas,
      mu_l: frac_o * o.mu_o + (1.0 - frac_o) * w.mu_w,
      mu_g: mu_gas,
      sigma: frac_o * sigma_o + (1.0 - frac_o) * sigma_w,
      frac_w: 1.0 - frac_o,                   // water share of the liquid volume (Orkiszewski)
      // producing gas-liquid ratio, scf per STB of liquid: all the gas at the surface
      // (dissolved + free + injected), for Fancher and Brown
      glr: (q_o * this.producingGor() + inj_scfd) / rate,
    };
  }

  /** [total mass rate in lb/h, mixture heat capacity in Btu/lb/degF]. @param {number} rate @returns {[number, number]} */
  thermalData(rate) {
    const q_o = rate * (1.0 - this.water_cut);
    const q_w = rate * this.water_cut;
    const m_o = q_o * 350.0 * 141.5 / (this.api + 131.5);        // lb/d (350 lb per bbl of water)
    const m_w = q_w * 5.615 * waterDensitySc(this.salinity);
    const m_g = q_o * this.producingGor() * GAS_RHO_SC * this.gas_sg;
    const total = m_o + m_w + m_g;
    const cp = (OIL_CP * m_o + WATER_CP * m_w + GAS_CP * m_g) / total;
    return [total / 24.0, cp];
  }

  /** [mass rate in lb/h, heat capacity in Btu/lb/degF] of the gas lift gas. @returns {[number, number]} */
  injectedThermal() {
    return [this.injection_gas_rate * 1000.0 * GAS_RHO_SC * this.injectedGasSg() / 24.0, GAS_CP];
  }
}

/**
 * A gas well, dry or wet (with condensate and water).
 *
 * Fields (all optional but gas_sg):
 *   gas_sg        gas gravity (air = 1); for a wet gas use the well-stream gravity
 *   cgr, wgr      condensate-gas and water-gas ratio (STB/MMscf)
 *   cond_api      condensate gravity (API)
 *   salinity      water salinity (wt %)
 *   y_h2s, y_co2  H2S and CO2 mole fractions (0 - 1)
 *   visc_method   gas viscosity: 'lee' or 'carr'
 *   gas_sg_dry    separator (dry) gas gravity; when > 0 the well-stream gravity is recalculated if
 *                 the CGR changes (commingled layers).  0 = gas_sg is kept as it is
 */
export class GasFluid {
  /**
   * @param {{gas_sg: number, cgr?: number, cond_api?: number, wgr?: number, salinity?: number,
   *          y_h2s?: number, y_co2?: number, visc_method?: string, gas_sg_dry?: number}} spec
   */
  constructor(spec) {
    this.gas_sg = spec.gas_sg;
    this.cgr = spec.cgr ?? 0.0;
    this.cond_api = spec.cond_api ?? 50.0;
    this.wgr = spec.wgr ?? 0.0;
    this.salinity = spec.salinity ?? 3.0;
    this.y_h2s = spec.y_h2s ?? 0.0;
    this.y_co2 = spec.y_co2 ?? 0.0;
    this.visc_method = spec.visc_method ?? "lee";
    this.gas_sg_dry = spec.gas_sg_dry ?? 0.0;

    check(this.gas_sg > 0, "Gas gravity must be > 0.");
    check(this.cgr >= 0 && this.wgr >= 0, "CGR and WGR cannot be negative.");
  }

  /**
   * Flow conditions for a gas rate (Mscf/d) at pressure p and temperature T.
   * @param {number} rate @param {number} p @param {number} T @param {number} d_in @returns {FlowConditions}
   */
  conditions(rate, p, T, d_in) {
    check(rate > 0, "Rate must be > 0.");
    const g = pvt.gasProperties(p, T, this.gas_sg, this.y_h2s, this.y_co2, this.visc_method);
    const area = pipeArea(d_in);
    const vol_g = rate * 1000.0 * g.bg;                      // ft3/d at pressure p

    const q_c = rate * this.cgr / 1000.0;                    // condensate, STB/d
    const q_w = rate * this.wgr / 1000.0;                    // water, STB/d
    const w = pvt.waterProperties(p, T, this.salinity);
    const vol_c = q_c * 5.615;                               // condensate Bo taken as 1
    const vol_w = q_w * w.bw * 5.615;
    const vol_l = vol_c + vol_w;

    let rho_l;
    let mu_l;
    let sigma;
    if (vol_l <= 0) {                                        // dry gas: liquid values are not used
      rho_l = 62.4;
      mu_l = 1.0;
      sigma = 50.0;
    } else {
      const frac_c = vol_c / vol_l;
      const rho_c = 350.0 * 141.5 / (this.cond_api + 131.5) / 5.615;
      rho_l = frac_c * rho_c + (1.0 - frac_c) * w.rho_w;
      mu_l = frac_c * pvt.muDeadBeal(this.cond_api, T) + (1.0 - frac_c) * w.mu_w;
      sigma = (frac_c * sigma_oil_gas(this.cond_api, T, p)
               + (1.0 - frac_c) * sigma_water_gas(T, p));
    }
    return {
      v_sl: vol_l / area / 86400.0,
      v_sg: vol_g / area / 86400.0,
      rho_l, rho_g: g.rho_g,
      mu_l, mu_g: g.mu_g,
      sigma,
      frac_w: vol_l <= 0 ? 0.0 : vol_w / vol_l,
      // scf per STB of liquid
      glr: (this.cgr + this.wgr) > 0 ? 1.0e6 / (this.cgr + this.wgr) : 1.0e9,
    };
  }

  /** [total mass rate in lb/h, mixture heat capacity in Btu/lb/degF]. @param {number} rate @returns {[number, number]} */
  thermalData(rate) {
    const m_g = rate * 1000.0 * GAS_RHO_SC * this.gas_sg;
    const m_c = rate * this.cgr / 1000.0 * 350.0 * 141.5 / (this.cond_api + 131.5);
    const m_w = rate * this.wgr / 1000.0 * 5.615 * waterDensitySc(this.salinity);
    const total = m_g + m_c + m_w;
    const cp = (GAS_CP * m_g + OIL_CP * m_c + WATER_CP * m_w) / total;
    return [total / 24.0, cp];
  }
}

/** @typedef {OilWaterFluid | GasFluid} Fluid */

// =====================================================================
// Fancher & Brown (1963) - the no-slip "lowest possible VLP"
// =====================================================================
// Fancher, G.H. Jr. and Brown, K.E., "Prediction of Pressure Gradients for Multiphase Flow in
// Tubing", SPE Journal, March 1963, p. 59.
//
//     dp/dH = [ rho + f q^2 M^2 / (7.413e10 rho d^5) ] / 144                  (psi/ft; Eq. 2)
//     N = 1.4737e-5 q M / d  (= rho v d, the numerator of the Reynolds number; q M is lb/day)
//     f = Fanning friction factor read from Fig. 7 (GLR < 1500 scf/bbl), Fig. 8 (1500 - 3000)
//         or Fig. 9 (> 3000)
//
// The factor is a function of N and the GLR only: the viscosity, the pipe roughness and the angle are
// not in it (the paper found viscous shear negligible).  There is no acceleration term, and no slip,
// which is why it gives the LOWEST possible VLP: it belongs in the correlation comparison as a
// quality check - a measured flowing pressure to the left of it means the PVT or the pressure data
// are wrong - and not in a real calculation.
//
// The lines are chart readings (digitised from the paper's figures, about +/- 3 %).  Fig. 7 is a curve
// (steep below N = 6, straight on log-log paper above); Figs. 8 and 9 are straight lines.  They are
// drawn for N = 3.4 - 35 (GLR < 1500), 4.7 - 27 (1500 - 3000) and 3.7 - 15 (> 3000); the comparison
// chart (Fig. 6) carries them to N = 70, 35 and 23, so each line is continued to there.  Beyond that
// the factor is held at its end value (a straight line for ever would give a friction factor far
// below a smooth pipe's), and below the start of the line it is held too.

export const FB_GLR_LIMITS = [1500.0, 3000.0];   // scf per STB of liquid: where one line gives way to the next
export const FB_N_MAX = { low: 70.0, mid: 35.0, high: 23.0 };   // the factor is held constant above this N

/** (N, f) points of the three lines; between two points the factor is a straight line on log-log paper */
export const FB_FRICTION_LINES = {
  low: [[3.4, 0.259], [3.8, 0.188], [4.2, 0.145], [4.7, 0.111], [5.3, 0.087], [6.0, 0.0675],
        [7.0, 10 ** (-0.26574 - 1.17775 * Math.log10(7.0))],
        [50.0, 10 ** (-0.26574 - 1.17775 * Math.log10(50.0))]],
  mid: [[4.7, 10 ** (-0.52769 - 1.12195 * Math.log10(4.7))],
        [27.0, 10 ** (-0.52769 - 1.12195 * Math.log10(27.0))]],
  high: [[3.7, 10 ** (-0.73798 - 1.26576 * Math.log10(3.7))],
         [15.0, 10 ** (-0.73798 - 1.26576 * Math.log10(15.0))]],
};

/**
 * Which of the paper's three lines applies: 'low' (GLR < 1500), 'mid' (1500 - 3000) or 'high' (> 3000).
 * @param {number} glr
 */
export function fb_glr_band(glr) {
  return glr < FB_GLR_LIMITS[0] ? "low" : (glr <= FB_GLR_LIMITS[1] ? "mid" : "high");
}

/**
 * Fanning friction factor of Figs. 7-9 at N = rho v d (lb/s/ft) for a producing gas-liquid ratio glr
 * (scf/STB).
 * @param {number} n_re @param {number} glr
 */
export function fb_friction_factor(n_re, glr) {
  check(n_re > 0, "The Fancher and Brown Reynolds numerator must be > 0.");
  const band = fb_glr_band(glr);
  const pts = FB_FRICTION_LINES[/** @type {"low"|"mid"|"high"} */ (band)];
  const n = Math.min(Math.max(n_re, pts[0][0]), FB_N_MAX[/** @type {"low"|"mid"|"high"} */ (band)]);
  // the segment to read: the one that holds n, or the first / last one when n is off the drawn line
  let k = 0;
  while (k < pts.length - 2 && n > pts[k + 1][0]) k += 1;
  const [n1, f1] = pts[k];
  const [n2, f2] = pts[k + 1];
  const slope = Math.log(f2 / f1) / Math.log(n2 / n1);
  return f1 * (n / n1) ** slope;
}

/**
 * Pressure gradient (psi/ft, positive in the flow direction) from Eq. 2 of Fancher and Brown.
 * c must also hold 'glr', the producing gas-liquid ratio (scf per STB of LIQUID, all the gas that
 * reaches the surface including the dissolved and the injected gas).  Pressure and roughness are not
 * used: the paper's friction factor depends on N and the GLR only.  The gravity part is
 * rho sin(angle) with the no-slip density (the paper is for vertical wells; sin(90) = 1).
 * @param {number} p @param {number} angle_deg @param {number} d_in @param {number} roughness_in
 * @param {FlowConditions} c
 */
export function fancher_brown_gradient(p, angle_deg, d_in, roughness_in, c) {
  const v_sl = c.v_sl;
  const v_sg = c.v_sg;
  const d_ft = d_in / 12.0;
  const area = Math.PI * d_ft ** 2 / 4.0;
  const v_m = v_sl + v_sg;
  const lam = v_m > 0 ? v_sl / v_m : 0.0;                            // no-slip liquid fraction
  const rho = lam * c.rho_l + (1.0 - lam) * c.rho_g;                 // flowing (no-slip) density, lb/ft3
  const mass_rate = (c.rho_l * v_sl + c.rho_g * v_sg) * area * 86400.0;  // q M of the paper, lb/day
  const n_re = 1.4737e-5 * mass_rate / d_ft;                         // rho v d, lb/s/ft
  const f = fb_friction_factor(n_re, c.glr);
  const friction = f * mass_rate ** 2 / (7.413e10 * rho * d_ft ** 5) / 144.0;    // psi/ft
  const hydrostatic = rho * Math.sin(radians(angle_deg)) / 144.0;
  const mu_ns = lam * c.mu_l + (1.0 - lam) * c.mu_g;
  return { dpdl: hydrostatic + friction, hl: lam, regime: "no-slip", hydrostatic,
           friction, f_tp: f, re: RE_CONST * rho * v_m * d_ft / mu_ns, e_k: 0.0, glr: c.glr };
}

// =====================================================================
// The pressure traverse: wellhead -> perforations
// =====================================================================

/** @typedef {(p: number, angle_deg: number, d_in: number, roughness_in: number, c: FlowConditions) => any} GradientFn */

/** @type {Record<string, GradientFn>} */
export const GRADIENT_FUNCS = {
  beggs_brill: beggs_brill_gradient,
  hagedorn_brown: hagedorn_brown_gradient,
  gray: gray_gradient,
  orkiszewski: orkiszewski_gradient,
  ansari: ansari_gradient,
  duns_ros: duns_ros_gradient,
  mukherjee_brill: mukherjee_brill_gradient,
  fancher_brown: fancher_brown_gradient,
};

// Correlations whose flow-pattern boundaries are known to make real jumps in the gradient: the
// pressure step accepts a jump up to this fraction of its own pressure change (see stepBottomPressure)
export const JUMPY_CORRELATIONS = { orkiszewski: 0.5, ansari: 0.5, duns_ros: 0.5, mukherjee_brill: 0.5 };

// A rate so high that the tubing would need more than this pressure can never be produced (no
// reservoir in this app is this high, and the PVT correlations are not meant for more).  Without a
// cap the search for the bottom pressure of a step at such a rate can wander to 100,000 psia, where
// the correlations return negative viscosities and the calculation stops with "Reynolds number must
// be > 0".  With the cap the VLP simply reads P_MAX there, far above the IPR.
export const P_MAX = 20000.0;       // psia

/**
 * Pressure at the bottom of one step, given the pressure at its top.
 *
 * The gradient depends on the average pressure of the step, which depends on the bottom pressure we
 * are looking for, so we search for the bottom pressure x that satisfies
 *     x = p_top + gradient(average of p_top and x) * length.
 * Write residual(x) = (that right-hand side) - x; we need residual = 0.
 *
 * Method (robust, still simple):
 *   * the first guess is made from a typical gradient, the second is the plain 'repeat' step;
 *   * after that, a secant step (a straight line through the last two points);
 *   * we remember the closest x below the answer (residual > 0) and the closest x above it
 *     (residual < 0).  If a secant step falls outside this bracket it is replaced by the middle of
 *     the bracket, so the search can never run away.
 * A correlation with a tiny jump (where one formula hands over to the next) has no exact answer; the
 * bracket then closes on the jump, and that is accepted if the residual on both sides is below
 * 0.5 psi or 0.3 % of the pressure, whichever is larger.  jump_fraction > 0 allows a larger jump, as
 * that fraction of the pressure change of the step (see JUMPY_CORRELATIONS).
 *
 * Returns [bottom pressure, the correlation's result].
 * @param {GradientFn} gradient @param {Fluid} fluid @param {number} rate @param {number} p_top
 * @param {number} t_avg @param {Step} s @param {number} roughness_in @param {number} [jump_fraction]
 * @returns {[number, any]}
 */
export function stepBottomPressure(gradient, fluid, rate, p_top, t_avg, s, roughness_in, jump_fraction = 0.0) {
  const tol = 0.01;                                   // psi

  /** @returns {[number, any]} */
  const residual = (/** @type {number} */ x) => {
    const p_avg = Math.max(0.5 * (p_top + x), 14.7);
    const c = s.inj_scfd                              // gas lift gas is in the flow above the injection point
      ? /** @type {OilWaterFluid} */ (fluid).conditions(rate, p_avg, t_avg, s.id_in, s.inj_scfd)
      : fluid.conditions(rate, p_avg, t_avg, s.id_in);
    const res = gradient(p_avg, s.angle_deg, s.id_in, roughness_in, c);
    const p_new = Math.min(Math.max(p_top + res.dpdl * s.length, 1.0), P_MAX);
    return [p_new - x, res];
  };

  let x = p_top + 0.4 * Math.max(s.tvd_bot - s.tvd_top, 1.0);
  let [f, res] = residual(x);
  /** @type {[number, number] | null} */
  let below = null;                                   // [x, residual] of the bracket ends
  /** @type {[number, number] | null} */
  let above = null;
  /** @type {number | null} */
  let x_old = null;
  let f_old = 0.0;
  for (let it = 0; it < 60; it++) {
    if (Math.abs(f) < tol) return [x + f, res];
    if (f > 0 && (below === null || x > below[0])) below = [x, f];
    if (f < 0 && (above === null || x < above[0])) above = [x, f];
    if (below && above && above[0] - below[0] < tol) {        // bracket closed on a jump
      if (Math.max(Math.abs(below[1]), Math.abs(above[1]))
          < Math.max(0.5, 0.003 * x, jump_fraction * Math.abs(x - p_top))) {
        return [0.5 * (below[0] + above[0]), res];
      }
      break;
    }
    let x_new;
    if (x_old === null || f === f_old) {
      x_new = x + f;                                  // plain repeat step
    } else {
      x_new = x - f * (x - x_old) / (f - f_old);      // secant step
    }
    // Only one side of the answer is known (for example a flow-pattern jump makes the residual
    // negative on both sides of the jump, with the true answer further down).  The secant step may
    // then just bounce between the same two points, so step away from the known side instead.
    if (above && !below && x_new >= above[0]) {
      x_new = above[0] - Math.max(2.0 * Math.abs(above[1]), 1.0);
    } else if (below && !above && x_new <= below[0]) {
      x_new = below[0] + Math.max(2.0 * Math.abs(below[1]), 1.0);
    }
    if (below && above && (!(below[0] < x_new && x_new < above[0]) || it % 2 === 1)) {
      x_new = 0.5 * (below[0] + above[0]);            // keep inside the bracket; every second step
                                                      // halves it (secant steps alone close very
                                                      // slowly on a jump)
    }
    x_new = Math.min(Math.max(x_new, 1.0), P_MAX);
    x_old = x;
    f_old = f;
    x = x_new;
    [f, res] = residual(x);
  }
  throw new StepDidNotConverge(`Pressure did not converge in the step at MD ${s.md_top.toFixed(0)} ft.`);
}

/**
 * The error stepBottomPressure throws when it cannot find the bottom pressure of a step.  It has its
 * own class so that stepWithSplit can catch exactly this and not swallow a real mistake, the way the
 * Python catches RuntimeError and not ValueError.
 */
export class StepDidNotConverge extends Error {
  /** @param {string} message */
  constructor(message) {
    super(message);
    this.name = "StepDidNotConverge";
  }
}

/**
 * stepBottomPressure(), but a step that has no solution is cut in two halves and each half solved.
 *
 * A correlation whose flow-pattern boundary makes a big jump in the gradient (Ansari, from annular to
 * slug at a low pressure and a high gas rate, jumps by about 0.17 psi/ft) can have no solution at all
 * in a 100 ft step: the bottom pressure would need to sit exactly on the boundary.  The jump in the
 * residual is the gradient jump times the step length, so a shorter step has a smaller jump, and
 * after one or two halvings it is small enough to accept.  The halves are solved one after the other,
 * the second starting from the bottom of the first.  The returned result has the length-weighted
 * holdup, hydrostatic and friction gradients of the two halves, so the totals stay correct.
 * @param {GradientFn} gradient @param {Fluid} fluid @param {number} rate @param {number} p_top
 * @param {number} t_avg @param {Step} s @param {number} roughness_in @param {number} [jump_fraction]
 * @param {number} [depth] @returns {[number, any]}
 */
export function stepWithSplit(gradient, fluid, rate, p_top, t_avg, s, roughness_in,
                              jump_fraction = 0.0, depth = 0) {
  try {
    return stepBottomPressure(gradient, fluid, rate, p_top, t_avg, s, roughness_in, jump_fraction);
  } catch (err) {
    if (!(err instanceof StepDidNotConverge)) throw err;
    if (depth >= 5) throw err;                      // 100 ft cut into 3 ft pieces and still no answer
  }
  const md_mid = 0.5 * (s.md_top + s.md_bot);
  const tvd_mid = 0.5 * (s.tvd_top + s.tvd_bot);
  const upper = { ...s, md_bot: md_mid, tvd_bot: tvd_mid, length: 0.5 * s.length };
  const lower = { ...s, md_top: md_mid, tvd_top: tvd_mid, length: 0.5 * s.length };
  const [p_mid, res_upper] = stepWithSplit(gradient, fluid, rate, p_top, t_avg, upper,
                                           roughness_in, jump_fraction, depth + 1);
  const [p_bot, res_lower] = stepWithSplit(gradient, fluid, rate, p_mid, t_avg, lower,
                                           roughness_in, jump_fraction, depth + 1);
  const res = { ...res_lower };
  for (const key of ["hl", "hydrostatic", "friction"]) {
    res[key] = 0.5 * ((res_upper[key] ?? 0.0) + (res_lower[key] ?? 0.0));
  }
  return [p_bot, res];
}

export const MULTIPLIER_MIN = 0.1;      // sanity limits for the VLP multipliers
export const MULTIPLIER_MAX = 10.0;

/**
 * Wrap a gradient function so that its gravity and friction parts are scaled.
 *
 * This is what the industry calls "VLP matching": no correlation fits every well, so the gravity
 * (hydrostatic) part and the friction part of the pressure drop can each be multiplied by a number
 * found by matching measured data.  1.0 and 1.0 leave the correlation unchanged.
 *
 * Every correlation builds its gradient the same way,
 *     dpdl = (hydrostatic + friction) / (1 - e_k)      (e_k = the small acceleration term)
 * so the multipliers go in at exactly that place.
 * @param {GradientFn} gradient @param {number} gravity_mult @param {number} friction_mult
 * @returns {GradientFn}
 */
export function withMultipliers(gradient, gravity_mult, friction_mult) {
  if (gravity_mult === 1.0 && friction_mult === 1.0) return gradient;
  return (p, angle_deg, d_in, roughness_in, c) => {
    const res = { ...gradient(p, angle_deg, d_in, roughness_in, c) };
    res.hydrostatic *= gravity_mult;
    res.friction *= friction_mult;
    res.dpdl = (res.hydrostatic + res.friction) / (1.0 - res.e_k);
    return res;
  };
}

/**
 * Calculate pressure and temperature down the well for one rate.
 *
 *   well        a well from well.js
 *   fluid       OilWaterFluid or GasFluid
 *   rate        STB/d of liquid (oil + water) for OilWaterFluid, Mscf/d for GasFluid
 *   p_wh        wellhead flowing pressure (psia)
 *   correlation one of the keys of GRADIENT_FUNCS
 *   max_step_ft longest step; smaller = slower but a little more accurate
 *   gravity_mult, friction_mult   VLP matching multipliers; 1.0 = none
 *
 * Returns lists (wellhead first): md, tvd, p, T, plus 'holdup' and 'regime' (one value per step) and
 * 'pwf' = the pressure at the perforations.  It also gives 'dp_hydrostatic' and 'dp_friction' (psi,
 * added up over the whole well): the usual "dP Gravity" and "dP Friction" split, with the rest of
 * (pwf - p_wh) being the small acceleration term.
 * @param {Well} well @param {Fluid} fluid @param {number} rate @param {number} p_wh
 * @param {string} [correlation] @param {number} [max_step_ft]
 * @param {number} [gravity_mult] @param {number} [friction_mult]
 */
export function pressure_traverse(well, fluid, rate, p_wh, correlation = "beggs_brill",
                                  max_step_ft = 100.0, gravity_mult = 1.0, friction_mult = 1.0) {
  check(correlation in GRADIENT_FUNCS, `Unknown VLP correlation: ${correlation}`);
  check(rate > 0, "Rate must be > 0.");
  check(p_wh > 0, "Wellhead pressure must be > 0.");
  check(MULTIPLIER_MIN <= gravity_mult && gravity_mult <= MULTIPLIER_MAX,
        `The gravity multiplier must be between ${MULTIPLIER_MIN} and ${MULTIPLIER_MAX}.`);
  check(MULTIPLIER_MIN <= friction_mult && friction_mult <= MULTIPLIER_MAX,
        `The friction multiplier must be between ${MULTIPLIER_MIN} and ${MULTIPLIER_MAX}.`);
  const gradient = withMultipliers(GRADIENT_FUNCS[correlation], gravity_mult, friction_mult);

  const oil = /** @type {OilWaterFluid} */ (fluid);
  const inj_rate = oil.injection_gas_rate ?? 0.0;               // gas lift gas, Mscf/d (0 = none)
  const inj_md = oil.injection_md ?? null;
  /** @type {Step[]} */
  let steps;
  const perf_md = well.md[well.md.length - 1];
  if (inj_rate > 0.0) {
    check(inj_md !== null && 0.0 < inj_md && inj_md < perf_md,
          `The gas injection depth (${Number(inj_md).toLocaleString("en-US", { maximumFractionDigits: 0 })} ft) `
          + `must be above the perforations (${perf_md.toLocaleString("en-US", { maximumFractionDigits: 0 })} ft) `
          + "and below the surface.");
    steps = buildSteps(well, max_step_ft, [/** @type {number} */ (inj_md)]);
    for (const s of steps) {          // steps above the injection point carry the lift gas
      s.inj_scfd = s.md_bot <= /** @type {number} */ (inj_md) + 1e-6 ? inj_rate * 1000.0 : 0.0;
    }
  } else {
    steps = buildSteps(well, max_step_ft);
  }
  let [massRate, cpValue] = fluid.thermalData(rate);
  /** @type {number | number[]} */
  let mass_rate = massRate;
  /** @type {number | number[]} */
  let cp = cpValue;
  if (inj_rate > 0.0) {
    const [m_i, cp_i] = oil.injectedThermal();
    const above = steps.map((s) => (s.inj_scfd ?? 0.0) > 0.0);
    const masses = above.map((a) => (a ? massRate + m_i : massRate));
    mass_rate = masses;
    cp = above.map((a, k) => (a ? (cpValue * (masses[k] - m_i) + cp_i * m_i) / masses[k] : cpValue));
  }
  const temps = fluidTemperatures(well, steps, mass_rate, cp);

  const md_list = [steps[0].md_top];
  const tvd_list = [steps[0].tvd_top];
  const p_list = [p_wh];
  /** @type {number[]} */
  const holdups = [];
  /** @type {string[]} */
  const regimes = [];              // the flow pattern the correlation reports in each step
  let dp_hydrostatic = 0.0;        // psi, added up step by step
  let dp_friction = 0.0;

  let p_top = p_wh;
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    const t_avg = 0.5 * (temps[i] + temps[i + 1]);
    const [p_bot, res] = stepWithSplit(gradient, fluid, rate, p_top, t_avg, s, well.roughness_in,
                                       JUMPY_CORRELATIONS[/** @type {keyof typeof JUMPY_CORRELATIONS} */ (correlation)] ?? 0.0);
    md_list.push(s.md_bot);
    tvd_list.push(s.tvd_bot);
    p_list.push(p_bot);
    holdups.push(res.hl);
    regimes.push(res.regime ?? "");
    dp_hydrostatic += (res.hydrostatic ?? 0.0) * s.length;
    dp_friction += (res.friction ?? 0.0) * s.length;
    p_top = p_bot;
  }

  return { md: md_list, tvd: tvd_list, p: p_list, T: temps,
           holdup: holdups, regime: regimes, pwf: p_list[p_list.length - 1],
           dp_hydrostatic, dp_friction };
}

/**
 * Flowing bottom-hole pressure (psia) for each rate in `rates` (all rates must be > 0).  Returns an
 * array of the same length.
 * @param {Well} well @param {Fluid} fluid @param {number[]} rates @param {number} p_wh
 * @param {string} [correlation] @param {number} [max_step_ft]
 * @param {number} [gravity_mult] @param {number} [friction_mult]
 */
export function vlp_curve(well, fluid, rates, p_wh, correlation = "beggs_brill", max_step_ft = 100.0,
                          gravity_mult = 1.0, friction_mult = 1.0) {
  return rates.map((q) => pressure_traverse(well, fluid, q, p_wh, correlation, max_step_ft,
                                            gravity_mult, friction_mult).pwf);
}
