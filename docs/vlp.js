// @ts-check
/**
 * vlp.js - Vertical Lift Performance: the tubing side, translated from vlp.py.
 *
 * Being written in stages, each one cross-checked against the Python before the next begins.
 * Done so far: the friction factor, surface tension, Beggs and Brill (1973),
 * Hagedorn and Brown (1965) and Gray (1974).
 * Still to come: Orkiszewski, Ansari, Duns and Ros, Mukherjee and Brill,
 * Fancher and Brown, the fluids and the pressure traverse.
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
