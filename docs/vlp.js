// @ts-check
/**
 * vlp.js - Vertical Lift Performance: the tubing side, translated from vlp.py.
 *
 * Being written in stages, each one cross-checked against the Python before the next begins.
 * Done so far: the friction factor, surface tension, and Beggs and Brill (1973).
 * Still to come: Hagedorn and Brown, Gray, Orkiszewski, Ansari, Duns and Ros,
 * Mukherjee and Brill, Fancher and Brown, the fluids and the pressure traverse.
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
