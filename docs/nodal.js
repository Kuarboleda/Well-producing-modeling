// @ts-check
/**
 * nodal.js - nodal analysis, translated from nodal.py (oilfield units).
 *
 * Nodal analysis puts the two halves of the well together:
 *     IPR (ipr.js) : what the reservoir delivers at a given flowing bottom-hole pressure
 *     VLP (vlp.js) : what bottom-hole pressure the tubing needs at a given rate
 * The well flows where the two curves cross: that rate and pressure are the OPERATING POINT.
 *
 * Units: pressure psia | oil + water rate STB/d (total liquid) | gas rate Mscf/d
 *
 * Important: for an oil well the IPR rate is taken as the TOTAL LIQUID rate (oil + water), the same
 * rate the VLP uses.
 *
 * One difference from the Python, on purpose: where the Python passes the IPR as a FUNCTION
 * (ipr.oil_pi), this file passes its NAME ("oil_pi") and calls it through ipr.callIpr, which is how
 * the rest of the JavaScript already works. Everything else - the arguments, the order, the returned
 * fields - is the same, and tools/crosscheck.mjs maps one to the other so the two are compared on
 * identical cases.
 *
 * About several crossings
 *     A VLP curve is often J-shaped (it bends up again at low rates because of liquid slippage), so
 *     it can cross the IPR twice. The lower-rate crossing is UNSTABLE (the well would load up and
 *     die, or jump to the other point). The higher-rate crossing is the STABLE one and is the one
 *     reported as the operating point. All crossings are still returned in result.crossings.
 */

import * as ipr from "./ipr.js";
import * as pvt from "./pvt.js";
import { OilWaterFluid, GasFluid, pressure_traverse, vlp_curve } from "./vlp.js";

/** @typedef {import("./well.js").Well} Well */
/** @typedef {OilWaterFluid | GasFluid} Fluid */

/** Stop with a clear error message if an input does not make sense. @param {boolean} condition @param {string} message */
function check(condition, message) {
  if (!condition) throw new Error(message);
}

/** A number with thousands separators and no decimals, for an error message. @param {number} v */
function round0(v) {
  return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

// =====================================================================
// The fluid that a multilayer well produces
// =====================================================================

/**
 * True when the IPR is a multilayer one (oil or gas) AND its layers carry their own produced-fluid
 * data (water cut and GOR for oil, CGR and WGR for gas).
 * @param {string} ipr_name @param {Record<string, any>} ipr_inputs
 */
export function hasLayerFluid(ipr_name, ipr_inputs) {
  const layers = ipr_inputs.layers || [];
  if (ipr_name === "oil_multilayer") {
    return layers.some((/** @type {any} */ layer) => "wc" in layer || "gor" in layer);
  }
  if (ipr_name === "gas_multilayer") {
    return layers.some((/** @type {any} */ layer) => "cgr" in layer || "wgr" in layer);
  }
  return false;
}

/** A copy of a fluid with some fields changed, the way Python's dataclasses.replace does.
 * @param {Fluid} fluid @param {Record<string, any>} changes @returns {Fluid} */
export function replaceFluid(fluid, changes) {
  if (fluid instanceof OilWaterFluid) {
    return new OilWaterFluid({ api: fluid.api, gas_sg: fluid.gas_sg, rsb: fluid.rsb,
      water_cut: fluid.water_cut, gor: fluid.gor, salinity: fluid.salinity, pb_meas: fluid.pb_meas,
      pvt_method: fluid.pvt_method, visc_method: fluid.visc_method, pvt_match: fluid.pvt_match,
      injection_gas_rate: fluid.injection_gas_rate, injection_md: fluid.injection_md,
      injection_gas_sg: fluid.injection_gas_sg, ...changes });
  }
  return new GasFluid({ gas_sg: fluid.gas_sg, cgr: fluid.cgr, cond_api: fluid.cond_api,
    wgr: fluid.wgr, salinity: fluid.salinity, y_h2s: fluid.y_h2s, y_co2: fluid.y_co2,
    visc_method: fluid.visc_method, gas_sg_dry: fluid.gas_sg_dry, ...changes });
}

/**
 * The fluid the well produces at the total rate q (STB/d liquid for oil, Mscf/d for gas).
 *
 * For an ordinary IPR this is just `fluid`. For a multilayer IPR whose layers have their own fluid
 * data, the layers produce different amounts at different flowing pressures, so the fluid of the well
 * stream changes with the rate: the flowing pressure the IPR needs for q is found, the layers'
 * fluids are added up at that pressure, and a copy of `fluid` with that mixture is returned. The PVT
 * (bubble point, gravities, ...) stays that of `fluid`; for a wet gas the well-stream gravity is
 * recalculated from the mixed CGR when the dry-gas gravity is known.
 * @param {Fluid} fluid @param {string} ipr_name @param {number} p_res
 * @param {Record<string, any>} ipr_inputs @param {number} q @returns {Fluid}
 */
export function fluid_at_rate(fluid, ipr_name, p_res, ipr_inputs, q) {
  if (!hasLayerFluid(ipr_name, ipr_inputs)) return fluid;
  const layers = ipr_inputs.layers;
  const crossflow = ipr_inputs.crossflow ?? false;
  if (ipr_name === "gas_multilayer") {
    const gas = /** @type {GasFluid} */ (fluid);
    const pwf = ipr.gas_multilayer_pwf(q, p_res, layers, crossflow);
    const mix = ipr.gas_multilayer_mix(p_res, pwf, layers, gas.cgr, gas.wgr, crossflow);
    /** @type {Record<string, any>} */
    const changes = { cgr: Math.max(mix.cgr, 0.0), wgr: Math.max(mix.wgr, 0.0) };
    if (gas.gas_sg_dry > 0) {
      changes.gas_sg = changes.cgr > 0
        ? pvt.wetGasGravity(gas.gas_sg_dry, changes.cgr, gas.cond_api)
        : gas.gas_sg_dry;
    }
    return replaceFluid(fluid, changes);
  }
  const oil = /** @type {OilWaterFluid} */ (fluid);
  const pb = ipr_inputs.pb;
  const pwf = ipr.multilayer_pwf(q, p_res, pb, layers, crossflow);
  const mix = ipr.multilayer_mix(p_res, pwf, pb, layers, oil.water_cut, oil.producingGor(), crossflow);
  return replaceFluid(fluid, { water_cut: Math.min(Math.max(mix.water_cut, 0.0), 1.0), gor: mix.gor });
}

// =====================================================================
// The intersection of an IPR and a VLP
// =====================================================================

/**
 * @typedef {{found: boolean, q: number | null, pwf: number | null, aof: number,
 *            crossings: {q: number, pwf: number, stable: boolean}[], message: string,
 *            mix?: Record<string, number>}} OperatingPoint
 */

/**
 * Find where an IPR and a VLP cross.
 *
 *   q_ipr(pwf)   the reservoir rate for a flowing pressure (the IPR)
 *   pwf_vlp(q)   the pressure the tubing needs for a rate (the VLP)
 *   n_grid       number of rates scanned between ~0 and the AOF to look for crossings
 *   q_min_frac   first rate scanned, as a fraction of the AOF
 *
 * Idea: at a given rate q the VLP needs pressure pwf_vlp(q); the reservoir could deliver
 * q_ipr(pwf_vlp(q)) at that pressure. The well is in balance where
 *     g(q) = q_ipr(pwf_vlp(q)) - q = 0.
 * We scan g over a grid of rates, look for sign changes, and refine each one by halving the interval
 * that contains the crossing.
 * @param {(pwf: number) => number} q_ipr @param {(q: number) => number} pwf_vlp
 * @param {number} [n_grid] @param {number} [q_min_frac] @returns {OperatingPoint}
 */
export function find_operating_point(q_ipr, pwf_vlp, n_grid = 30, q_min_frac = 0.01) {
  check(n_grid >= 4, "n_grid must be at least 4.");
  check(0.0 < q_min_frac && q_min_frac < 0.5, "q_min_frac must be between 0 and 0.5.");
  const aof = q_ipr(0.0);
  check(aof > 0, "The IPR gives no flow even at Pwf = 0 - check the IPR inputs.");

  const g = (/** @type {number} */ q) => q_ipr(pwf_vlp(q)) - q;

  // 1) scan a grid of rates and remember g at each one
  /** @type {number[]} */
  const qs = [];
  for (let i = 0; i <= n_grid; i++) qs.push(aof * (q_min_frac + (1.0 - q_min_frac) * i / n_grid));
  const gs = qs.map(g);

  // 2) every place where g changes sign holds a crossing: refine it by halving the interval
  /** @type {{q: number, pwf: number, stable: boolean}[]} */
  const crossings = [];
  for (let i = 0; i < n_grid; i++) {
    if (gs[i] === 0 || gs[i] * gs[i + 1] >= 0) continue;
    let lo = qs[i];
    let hi = qs[i + 1];
    let g_lo = gs[i];
    for (let k = 0; k < 60; k++) {
      const mid = 0.5 * (lo + hi);
      const g_mid = g(mid);
      if (g_mid * g_lo > 0) {
        lo = mid;
        g_lo = g_mid;
      } else {
        hi = mid;
      }
      if (hi - lo < 1e-7 * aof) break;
    }
    const q_cross = 0.5 * (lo + hi);
    crossings.push({ q: q_cross, pwf: pwf_vlp(q_cross), stable: gs[i] > 0 });  // + to - : stable
  }

  const stable = crossings.filter((c) => c.stable);
  if (stable.length === 0) {
    return { found: false, q: null, pwf: null, aof, crossings,
             message: "The VLP is above the IPR at every rate: the well will not flow naturally. "
                      + "Lower the wellhead pressure, enlarge the tubing, or consider artificial lift." };
  }
  const best = stable[stable.length - 1];              // highest-rate stable crossing
  return { found: true, q: best.q, pwf: best.pwf, aof, crossings, message: "" };
}

// =====================================================================
// The whole chain: well + fluid + IPR  ->  operating point
// =====================================================================

/**
 * Operating point of a well.
 *
 *   well          a well from well.js
 *   fluid         OilWaterFluid or GasFluid
 *   ipr_name      the name of an IPR model, for example "oil_pi" or "gas_jones"
 *   p_res         reservoir pressure (psia)
 *   ipr_inputs    the other inputs of that model, for example {pb: 2000, J: 3.0}
 *   p_wh          wellhead flowing pressure (psia)
 *   correlation   VLP correlation name (see vlp.js)
 *   gravity_mult, friction_mult   VLP matching multipliers (1.0 = correlation unchanged)
 * @param {Well} well @param {Fluid} fluid @param {string} ipr_name @param {number} p_res
 * @param {Record<string, any>} ipr_inputs @param {number} p_wh @param {string} [correlation]
 * @param {number} [max_step_ft] @param {number} [n_grid] @param {number} [gravity_mult]
 * @param {number} [friction_mult] @returns {OperatingPoint}
 */
export function solve_well(well, fluid, ipr_name, p_res, ipr_inputs, p_wh,
                           correlation = "beggs_brill", max_step_ft = 100.0, n_grid = 30,
                           gravity_mult = 1.0, friction_mult = 1.0) {
  check(p_res > 0 && p_wh > 0, "Reservoir and wellhead pressure must be > 0.");

  const q_ipr = (/** @type {number} */ pwf) => ipr.callIpr(ipr_name, { p_res, pwf, ...ipr_inputs });

  const pwf_vlp = (/** @type {number} */ q) => {
    // multilayer: the mixture the well produces depends on the rate
    const fluid_q = fluid_at_rate(fluid, ipr_name, p_res, ipr_inputs, q);
    return pressure_traverse(well, fluid_q, q, p_wh, correlation, max_step_ft,
                             gravity_mult, friction_mult).pwf;
  };

  const result = find_operating_point(q_ipr, pwf_vlp, n_grid);
  if (result.found && hasLayerFluid(ipr_name, ipr_inputs)) {
    const f = fluid_at_rate(fluid, ipr_name, p_res, ipr_inputs, /** @type {number} */ (result.q));
    if (ipr_name === "gas_multilayer") {
      const gas = /** @type {GasFluid} */ (f);
      result.mix = { cgr: gas.cgr, wgr: gas.wgr };      // what the gas layers produce at the operating point
    } else {
      const oil = /** @type {OilWaterFluid} */ (f);
      result.mix = { water_cut: oil.water_cut, gor: /** @type {number} */ (oil.gor) };
    }
  }
  return result;
}

/**
 * VLP matching from ONE measured test: find the multiplier that makes the tubing calculation
 * reproduce a measured flowing bottom-hole pressure.
 *
 *   rate, p_wh     rate and wellhead flowing pressure (psia) of the test
 *   pwf_measured   flowing bottom-hole pressure (psia) measured in that test, at the perforation
 *                  (reference) depth of the well
 *   fit            'friction' (the usual choice) or 'gravity': which multiplier to find. The other
 *                  one stays at 1.0.
 *   low, high      the range searched
 *   message_offset, message_unit   the offset is subtracted from every pressure WRITTEN IN AN ERROR
 *                  MESSAGE and the unit is the name printed after it, so a page working in gauge
 *                  pressure can show psig (pass 14.7 and "psig"); neither changes the calculation
 *
 * The calculated pressure rises steadily with either multiplier, so we halve the interval until the
 * calculated pressure equals the measured one. Returns the multiplier, and throws if the measured
 * pressure cannot be reached inside [low, high] (the message says what the calculation gives at both
 * ends).
 * @param {Well} well @param {Fluid} fluid @param {number} rate @param {number} p_wh
 * @param {number} pwf_measured @param {string} [correlation] @param {number} [max_step_ft]
 * @param {string} [fit] @param {number} [low] @param {number} [high]
 * @param {number} [message_offset] @param {string} [message_unit]
 */
export function match_vlp_multiplier(well, fluid, rate, p_wh, pwf_measured, correlation = "beggs_brill",
                                     max_step_ft = 100.0, fit = "friction", low = 0.5, high = 2.0,
                                     message_offset = 0.0, message_unit = "psia") {
  check(fit === "friction" || fit === "gravity", "fit must be 'friction' or 'gravity'.");
  check(0 < low && low < high, "The search range must have 0 < low < high.");
  check(pwf_measured > p_wh, "The measured bottom-hole pressure must be above the wellhead pressure.");

  const pwf_for = (/** @type {number} */ m) => {
    const g = fit === "friction" ? 1.0 : m;
    const f = fit === "friction" ? m : 1.0;
    return pressure_traverse(well, fluid, rate, p_wh, correlation, max_step_ft, g, f).pwf;
  };

  const p_low = pwf_for(low);
  const p_high = pwf_for(high);
  if (!(p_low <= pwf_measured && pwf_measured <= p_high)) {
    throw new Error(
      `The measured pressure (${round0(pwf_measured - message_offset)} ${message_unit}) cannot be matched `
      + `by changing the ${fit} multiplier alone: the calculation gives `
      + `${round0(p_low - message_offset)} ${message_unit} at ${low} and `
      + `${round0(p_high - message_offset)} ${message_unit} at ${high}. Check the test data, the well `
      + "description and the fluid first; a different correlation may also fit better.");
  }
  let lo = low;
  let hi = high;
  for (let i = 0; i < 50; i++) {
    const mid = 0.5 * (lo + hi);
    if (pwf_for(mid) < pwf_measured) lo = mid;
    else hi = mid;
    if (hi - lo < 1e-5) break;
  }
  return 0.5 * (lo + hi);
}

/**
 * Solve a small set of linear equations A x = b by Gauss elimination with partial pivoting.  Only
 * ever 1x1 or 2x2 here (one multiplier or two), so nothing cleverer is needed.
 * @param {number[][]} a @param {number[]} b @returns {number[]}
 */
function solveLinear(a, b) {
  const n = b.length;
  const m = a.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < n; col++) {
    let pivot = col;
    for (let r = col + 1; r < n; r++) if (Math.abs(m[r][col]) > Math.abs(m[pivot][col])) pivot = r;
    if (Math.abs(m[pivot][col]) < 1e-300) throw new Error("The matching equations have no solution.");
    [m[col], m[pivot]] = [m[pivot], m[col]];
    for (let r = col + 1; r < n; r++) {
      const factor = m[r][col] / m[col][col];
      for (let k = col; k <= n; k++) m[r][k] -= factor * m[col][k];
    }
  }
  const x = new Array(n).fill(0);
  for (let r = n - 1; r >= 0; r--) {
    let s = m[r][n];
    for (let k = r + 1; k < n; k++) s -= m[r][k] * x[k];
    x[r] = s / m[r][r];
  }
  return x;
}

/** Straight-line interpolation at each x in `xs`, from a table (table_x increasing). Python's np.interp.
 * @param {number[]} xs @param {number[]} table_x @param {number[]} table_y */
function interpAll(xs, table_x, table_y) {
  return xs.map((x) => {
    if (x <= table_x[0]) return table_y[0];
    if (x >= table_x[table_x.length - 1]) return table_y[table_y.length - 1];
    let i = 0;
    while (i < table_x.length - 2 && table_x[i + 1] < x) i += 1;
    const frac = (x - table_x[i]) / (table_x[i + 1] - table_x[i]);
    return table_y[i] + frac * (table_y[i + 1] - table_y[i]);
  });
}

/**
 * VLP matching from a measured pressure SURVEY (a gauge at one or more depths in the tubing).
 *
 *   depths_md, pressures   the measured points: depth along the well (MD, ft) and pressure (psia)
 *   fit                    'both' (the gravity AND the friction multiplier, needs 2 or more points at
 *                          different depths), 'friction' or 'gravity' (one multiplier; the other
 *                          stays at 1.0)
 *   low, high              the range searched for each multiplier
 *
 * The multipliers that make the calculated pressures closest to the measured ones (least squares) are
 * found with Gauss-Newton steps: the pressure at each depth changes almost in proportion to each
 * multiplier, so the iteration settles in a few steps. A step that makes things worse is halved.
 * Returns {gravity, friction, rms_before, rms_after, at_limit}: the rms values are the root-mean-square
 * pressure errors (psi) before (both multipliers 1.0) and after matching; at_limit lists the
 * multipliers that ended on the edge of the range (the match is then not reliable).
 * @param {Well} well @param {Fluid} fluid @param {number} rate @param {number} p_wh
 * @param {number[]} depths_md @param {number[]} pressures @param {string} [correlation]
 * @param {number} [max_step_ft] @param {string} [fit] @param {number} [low] @param {number} [high]
 */
export function match_vlp_survey(well, fluid, rate, p_wh, depths_md, pressures,
                                 correlation = "beggs_brill", max_step_ft = 100.0, fit = "both",
                                 low = 0.5, high = 2.0) {
  check(fit === "both" || fit === "friction" || fit === "gravity",
        "fit must be 'both', 'friction' or 'gravity'.");
  check(0 < low && low < high, "The search range must have 0 < low < high.");
  const depths = depths_md.map(Number);
  const measured = pressures.map(Number);
  check(depths.length === measured.length && depths.length >= 1, "Give at least one measured point.");
  check(fit !== "both" || new Set(depths.map((d) => Number(d.toFixed(3)))).size >= 2,
        "Matching both multipliers needs at least two points at different depths. With one point, "
        + "match the friction or the gravity multiplier alone.");

  const errors = (/** @type {number} */ g, /** @type {number} */ f) => {
    const tr = pressure_traverse(well, fluid, rate, p_wh, correlation, max_step_ft, g, f);
    check(Math.max(...depths) <= tr.md[tr.md.length - 1] + 1e-6,
          "A measured depth is below the bottom of the tubing.");
    return interpAll(depths, tr.md, tr.p).map((p, i) => p - measured[i]);
  };
  const rms = (/** @type {number[]} */ e) =>
    Math.sqrt(e.reduce((s, v) => s + v * v, 0) / e.length);

  const names = fit === "both" ? ["gravity", "friction"] : [fit];
  let x = new Array(names.length).fill(1.0);

  /** @returns {[number, number]} */
  const full = (/** @type {number[]} */ values) => {
    /** @type {Record<string, number>} */
    const d = { gravity: 1.0, friction: 1.0 };
    names.forEach((n, i) => { d[n] = values[i]; });
    return [d.gravity, d.friction];
  };

  let e = errors(...full(x));
  const rms_before = rms(e);
  for (let iter = 0; iter < 15; iter++) {
    // the slope of every error with respect to every multiplier (finite differences)
    const jac = depths.map(() => new Array(x.length).fill(0));
    for (let k = 0; k < x.length; k++) {
      const xk = [...x];
      xk[k] += 0.02;
      const ek = errors(...full(xk));
      for (let r = 0; r < depths.length; r++) jac[r][k] = (ek[r] - e[r]) / 0.02;
    }
    // A = J'J + a small number on the diagonal (so a flat direction cannot blow the step up)
    const jtj = x.map((_, i) => x.map((__, j) =>
      jac.reduce((s, row) => s + row[i] * row[j], 0)));
    const trace = jtj.reduce((s, row, i) => s + row[i], 0);
    const ridge = 1e-9 * Math.max(trace, 1.0);
    for (let i = 0; i < x.length; i++) jtj[i][i] += ridge;
    const jte = x.map((_, i) => jac.reduce((s, row, r) => s + row[i] * e[r], 0));
    const step = solveLinear(jtj, jte).map((v) => -v);

    let scale = 1.0;
    let improved = false;
    /** @type {number[]} */
    let trial = [...x];
    /** @type {number[]} */
    let e_trial = e;
    for (let h = 0; h < 6; h++) {                // halve the step until the match gets better
      trial = x.map((v, i) => Math.min(Math.max(v + scale * step[i], low), high));
      e_trial = errors(...full(trial));
      if (rms(e_trial) < rms(e) - 1e-9) { improved = true; break; }
      scale *= 0.5;
    }
    if (!improved) break;
    const change = Math.max(...trial.map((v, i) => Math.abs(v - x[i])));
    x = trial;
    e = e_trial;
    if (change < 1e-4) break;
  }
  const [g, f] = full(x);
  return { gravity: g, friction: f, rms_before, rms_after: rms(e),
           at_limit: names.filter((_, i) => x[i] <= low + 1e-3 || x[i] >= high - 1e-3) };
}

/**
 * IPR and VLP curves for plotting (rate on the x axis, Pwf on the y axis).
 *     ipr_q, ipr_pwf   the IPR, from Pwf = Pr down to 0
 *     vlp_q, vlp_pwf   the VLP, from 2 % of the AOF up to the AOF
 * @param {Well} well @param {Fluid} fluid @param {string} ipr_name @param {number} p_res
 * @param {Record<string, any>} ipr_inputs @param {number} p_wh @param {string} [correlation]
 * @param {number} [max_step_ft] @param {number} [n_points] @param {number} [gravity_mult]
 * @param {number} [friction_mult]
 */
export function curves(well, fluid, ipr_name, p_res, ipr_inputs, p_wh, correlation = "beggs_brill",
                       max_step_ft = 100.0, n_points = 25, gravity_mult = 1.0, friction_mult = 1.0) {
  check(n_points >= 3, "n_points must be at least 3.");
  /** @type {number[]} */
  const ipr_pwf = [];
  for (let i = 0; i < n_points; i++) ipr_pwf.push(p_res * (1.0 - i / (n_points - 1)));
  const ipr_q = ipr_pwf.map((pwf) => ipr.callIpr(ipr_name, { p_res, pwf, ...ipr_inputs }));
  const aof = ipr_q[ipr_q.length - 1];
  check(aof > 0, "The IPR gives no flow even at Pwf = 0 - check the IPR inputs.");
  /** @type {number[]} */
  const vlp_q = [];
  for (let i = 0; i < n_points; i++) vlp_q.push(aof * (0.02 + 0.98 * i / (n_points - 1)));
  const vlp_pwf = hasLayerFluid(ipr_name, ipr_inputs)
    ? vlp_q.map((q) => pressure_traverse(well, fluid_at_rate(fluid, ipr_name, p_res, ipr_inputs, q),
                                         q, p_wh, correlation, max_step_ft,
                                         gravity_mult, friction_mult).pwf)
    : vlp_curve(well, fluid, vlp_q, p_wh, correlation, max_step_ft, gravity_mult, friction_mult);
  return { ipr_q, ipr_pwf, vlp_q, vlp_pwf };
}

// =====================================================================
// Sensitivities
// =====================================================================

/**
 * Copy of a well whose tubing is ONE section of the given inner diameter (in).
 * @param {Well} well @param {number} id_in @returns {Well}
 */
export function well_with_tubing_id(well, id_in) {
  return { md: [...well.md], tvd: [...well.tvd],
           tubing: [[0.0, well.md[well.md.length - 1], Number(id_in)]],
           t_reservoir: well.t_reservoir, roughness_in: well.roughness_in,
           ambient_table: well.ambient_table.map((row) => /** @type {[number, number, number]} */ ([...row])) };
}

/**
 * @typedef {{well: Well, fluid: Fluid, ipr_name: string, p_res: number,
 *            ipr_inputs: Record<string, any>, p_wh: number, correlation?: string,
 *            max_step_ft?: number, n_grid?: number, gravity_mult?: number,
 *            friction_mult?: number}} SolveInputs
 */

/**
 * A copy of the solve inputs that can be changed without touching the original, which is what
 * Python's copy.deepcopy does there.  The well is plain data, so its lists are copied; the fluid is
 * an object, so it is rebuilt from its own fields.
 * @param {SolveInputs} base
 */
function copyInputs(base) {
  return { ...base,
           well: { ...base.well, md: [...base.well.md], tvd: [...base.well.tvd],
                   tubing: base.well.tubing.map((t) => /** @type {[number, number, number]} */ ([...t])),
                   ambient_table: base.well.ambient_table.map(
                     (r) => /** @type {[number, number, number]} */ ([...r])) },
           fluid: replaceFluid(base.fluid, {}),
           ipr_inputs: structuredClone(base.ipr_inputs) };
}

/**
 * Set one input inside the solve inputs.
 *     "p_wh"             -> inputs.p_wh
 *     "ipr_inputs.J"     -> inputs.ipr_inputs.J
 *     "fluid.water_cut"  -> inputs.fluid.water_cut
 *     "well"             -> replace the whole well (for example from well_with_tubing_id)
 * A misspelt name throws (a silent typo would give a flat, useless sensitivity).
 * @param {Record<string, any>} inputs @param {string} path @param {any} value
 */
export function setPath(inputs, path, value) {
  const parts = path.split(".");
  check(parts[0] in inputs, `Unknown input '${parts[0]}'. Choose from: ${Object.keys(inputs).join(", ")}`);
  if (parts.length === 1) {
    inputs[parts[0]] = value;
    return;
  }
  let target = inputs[parts[0]];
  for (const name of parts.slice(1, -1)) target = target[name];
  const last = parts[parts.length - 1];
  check(last in target, `Unknown input '${path}'.`);
  target[last] = value;
}

/**
 * Run solve_well() once for each value of ONE input and collect the operating points.
 *
 *   base    the solve_well inputs as one object (see SolveInputs)
 *   name    which input to vary (see setPath), e.g. "p_wh", "ipr_inputs.J", "fluid.water_cut"
 *   values  the values to try
 *   with_curves   also keep the IPR and VLP curves of every run, so the chart can show one curve
 *                 per value - for example one VLP for each wellhead pressure
 *
 * The base inputs are never changed (every run works on a copy).  "curves" is null for a value whose
 * IPR gives no flow at all.
 * @param {SolveInputs} base @param {string} name @param {any[]} values
 * @param {boolean} [with_curves] @param {number} [n_points]
 */
export function sensitivity(base, name, values, with_curves = false, n_points = 25) {
  /** @type {Record<string, any>[]} */
  const results = [];
  for (const value of values) {
    const inputs = /** @type {any} */ (copyInputs(base));
    setPath(inputs, name, value);
    const r = solve_well(inputs.well, inputs.fluid, inputs.ipr_name, inputs.p_res, inputs.ipr_inputs,
                         inputs.p_wh, inputs.correlation ?? "beggs_brill",
                         inputs.max_step_ft ?? 100.0, inputs.n_grid ?? 30,
                         inputs.gravity_mult ?? 1.0, inputs.friction_mult ?? 1.0);
    /** @type {Record<string, any>} */
    const row = { value, found: r.found, q: r.q, pwf: r.pwf };
    if (r.mix && "water_cut" in r.mix) row.water_cut = r.mix.water_cut;   // multilayer: this run's water cut
    if (with_curves) {
      try {
        row.curves = curves(inputs.well, inputs.fluid, inputs.ipr_name, inputs.p_res,
                            inputs.ipr_inputs, inputs.p_wh, inputs.correlation ?? "beggs_brill",
                            inputs.max_step_ft ?? 100.0, n_points,
                            inputs.gravity_mult ?? 1.0, inputs.friction_mult ?? 1.0);
      } catch {
        row.curves = null;
      }
    }
    results.push(row);
  }
  return results;
}
