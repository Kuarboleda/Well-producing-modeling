// @ts-check
/**
 * vlp.js - Vertical Lift Performance: the tubing side, translated from vlp.py.
 *
 * Being written in stages, each one cross-checked against the Python before the next begins.
 * Done so far: the friction factor, surface tension, Beggs and Brill (1973),
 * Hagedorn and Brown (1965), Gray (1974), Orkiszewski (1967) and Duns and Ros (1963).
 * Still to come: Ansari, Mukherjee and Brill, Fancher and Brown, the fluids and the
 * pressure traverse.
 *
 * Every function keeps the same name and the same argument order as the Python, so
 * tools/crosscheck.mjs can call both with one list of numbers.
 *
 * Units: pressure psia | length ft | velocity ft/s | density lb/ft3 | viscosity cP
 *        surface tension dyne/cm | diameter and roughness in | angle degrees from horizontal
 */

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
