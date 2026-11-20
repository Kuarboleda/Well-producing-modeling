// crosscheck.mjs - hold the JavaScript engine against the Python engine, case by case.
//
// The Python side (dump_pvt.py and its friends) writes every case and its answer to a JSON file.
// This script feeds the SAME inputs to the JavaScript and reports the largest disagreement, per
// function and overall.  Nothing here knows any physics: that is the point.  The Python was checked
// against the papers, so if the two agree to ten decimal places the JavaScript inherits that work.
//
// Run from the docs/ folder:   node tools/crosscheck.mjs
//
// It expects the JSON files to exist already:
//   PYTHONPATH=.. python3 tools/dump_pvt.py tools/pvt_expected.json

import { readFileSync, existsSync } from "node:fs";
import * as pvt from "../pvt.js";
import * as ipr from "../ipr.js";
import * as vlp from "../vlp.js";
import * as wellmod from "../well.js";
import * as nodal from "../nodal.js";
import * as advice from "../advice.js";

// ---------------------------------------------------------------------
// The traverse takes a well and a fluid object, which the Python side wrote out as plain
// dictionaries tagged with a "kind".  These build the JavaScript objects back from exactly the same
// numbers, so the two engines are given the same well and the same fluid and nothing else differs.
// ---------------------------------------------------------------------

/** @param {any} spec */
function build(spec) {
  const { kind, ...rest } = spec;
  if (kind === "well") {
    return wellmod.makeWell({ md: rest.md, tvd: rest.tvd, tubing: rest.tubing,
                              t_reservoir: rest.t_reservoir, roughness_in: rest.roughness_in,
                              ambient_table: rest.ambient_table });
  }
  if (kind === "oil") return new vlp.OilWaterFluid(rest);
  if (kind === "gas") return new vlp.GasFluid(rest);
  throw new Error(`unknown spec kind ${kind}`);
}

/** The object-taking functions, wrapped so the cross-check can call them positionally. */
const traverse = (w, f, ...rest) => vlp.pressure_traverse(build(w), build(f), ...rest);
const vlpCurve = (w, f, ...rest) => vlp.vlp_curve(build(w), build(f), ...rest);
const fluidConditions = (f, rate, p, T, d_in, inj) =>
  inj === undefined || inj === null
    ? build(f).conditions(rate, p, T, d_in)
    : build(f).conditions(rate, p, T, d_in, inj);
const fluidThermal = (f, rate) => {
  const fluid = build(f);
  const out = [...fluid.thermalData(rate)];
  // @ts-ignore - only an oil fluid has injected gas
  if ((fluid.injection_gas_rate ?? 0.0) > 0.0) out.push(...fluid.injectedThermal());
  return out;
};

// Python snake_case name -> the JavaScript function that must match it.
const MAP = {
  pb_glaso: pvt.pbGlaso, pb_standing: pvt.pbStanding, pb_lasater: pvt.pbLasater, pb_petrosky: pvt.pbPetrosky,
  rs_glaso: pvt.rsGlaso, rs_standing: pvt.rsStanding, rs_lasater: pvt.rsLasater, rs_petrosky: pvt.rsPetrosky,
  bo_glaso: pvt.boGlaso, bo_standing: pvt.boStanding, bo_lasater: pvt.boLasater, bo_petrosky: pvt.boPetrosky,
  mu_dead_beal: pvt.muDeadBeal, mu_dead_beggs: pvt.muDeadBeggs, mu_dead_petrosky: pvt.muDeadPetrosky,
  mu_live_chew_connally: pvt.muLiveChewConnally, mu_live_beggs: pvt.muLiveBeggs,
  mu_live_petrosky: pvt.muLivePetrosky,
  mu_under_beal: pvt.muUnderBeal, mu_under_petrosky: pvt.muUnderPetrosky,
  mu_under_vasquez_beggs: pvt.muUnderVasquezBeggs,
  gas_pseudocritical: pvt.gasPseudocritical, gas_properties: pvt.gasProperties,
  water_properties: pvt.waterProperties, salinity_from_sg: pvt.salinityFromSg,
  wet_gas_gravity: pvt.wetGasGravity, oil_properties: pvt.oilProperties,

  // ---- ipr.py / ipr.js (the names are identical on both sides) ----
  oil_pi: ipr.oil_pi, oil_vogel: ipr.oil_vogel, vogel_productivity_index: ipr.vogel_productivity_index,
  oil_darcy: ipr.oil_darcy, oil_darcy_regime: ipr.oil_darcy_regime,
  darcy_productivity_index_oil: ipr.darcy_productivity_index_oil,
  darcy_productivity_index_oil_steady: ipr.darcy_productivity_index_oil_steady,
  darcy_productivity_index_oil_transient: ipr.darcy_productivity_index_oil_transient,
  transient_end_time_hours: ipr.transient_end_time_hours,
  c_and_n_from_two_tests: ipr.c_and_n_from_two_tests, oil_fetkovich: ipr.oil_fetkovich,
  gas_a_coefficient: ipr.gas_a_coefficient, gas_b_coefficient: ipr.gas_b_coefficient,
  gas_beta_firoozabadi_katz: ipr.gas_beta_firoozabadi_katz,
  gas_darcy: ipr.gas_darcy, gas_jones: ipr.gas_jones, gas_backpressure: ipr.gas_backpressure,
  horizontal_productivity_index_oil_joshi: ipr.horizontal_productivity_index_oil_joshi,
  oil_horizontal_joshi: ipr.oil_horizontal_joshi,
  gas_a_coefficient_horizontal_joshi: ipr.gas_a_coefficient_horizontal_joshi,
  gas_horizontal_joshi: ipr.gas_horizontal_joshi,
  bickley_ki2: ipr.bickley_ki2,
  horizontal_productivity_index_oil_kuchuk_goode: ipr.horizontal_productivity_index_oil_kuchuk_goode,
  oil_horizontal_kuchuk_goode: ipr.oil_horizontal_kuchuk_goode,
  gas_horizontal_kuchuk_goode: ipr.gas_horizontal_kuchuk_goode,
  multilayer_rates: ipr.multilayer_rates, oil_multilayer: ipr.oil_multilayer,
  multilayer_mix: ipr.multilayer_mix, multilayer_pwf: ipr.multilayer_pwf,
  gas_multilayer_rates: ipr.gas_multilayer_rates, gas_multilayer: ipr.gas_multilayer,
  gas_multilayer_mix: ipr.gas_multilayer_mix, gas_multilayer_pwf: ipr.gas_multilayer_pwf,

  // ---- vlp.py / vlp.js (being translated in stages) ----
  friction_factor: vlp.friction_factor,
  sigma_oil_gas: vlp.sigma_oil_gas, sigma_water_gas: vlp.sigma_water_gas,
  beggs_brill_gradient: vlp.beggs_brill_gradient,
  hb_cn_l: vlp.hb_cn_l, hb_holdup_over_psi: vlp.hb_holdup_over_psi, hb_psi: vlp.hb_psi,
  hb_numbers: vlp.hb_numbers, griffith_bubble_holdup: vlp.griffith_bubble_holdup,
  hagedorn_brown_gradient: vlp.hagedorn_brown_gradient,
  gray_holdup: vlp.gray_holdup, gray_effective_roughness: vlp.gray_effective_roughness,
  gray_gradient: vlp.gray_gradient,
  ork_bubble_rise_velocity: vlp.ork_bubble_rise_velocity, ork_gamma: vlp.ork_gamma,
  ork_flow_regime: vlp.ork_flow_regime, orkiszewski_gradient: vlp.orkiszewski_gradient,
  dr_numbers: vlp.dr_numbers, dr_region_limits: vlp.dr_region_limits,
  dr_slip_region1: vlp.dr_slip_region1, dr_slip_region2: vlp.dr_slip_region2,
  dr_holdup: vlp.dr_holdup, dr_mist_film_roughness: vlp.dr_mist_film_roughness,
  dr_flow_region: vlp.dr_flow_region, duns_ros_gradient: vlp.duns_ros_gradient,
  // the keys are the PYTHON names, so the private helpers keep their underscore
  _ans_blend: vlp.ansBlend, _ans_film_instability: vlp.ansFilmInstability,
  ans_flow_pattern: vlp.ans_flow_pattern,
  ans_annular_film_thickness: vlp.ans_annular_film_thickness,
  _ans_slug: vlp.ansSlug, ansari_gradient: vlp.ansari_gradient,
  mb_numbers: vlp.mb_numbers, mb_flow_pattern: vlp.mb_flow_pattern, mb_holdup: vlp.mb_holdup,
  mb_stratified_angle: vlp.mb_stratified_angle, mb_stratified_friction: vlp.mb_stratified_friction,
  mukherjee_brill_gradient: vlp.mukherjee_brill_gradient,
  fb_glr_band: vlp.fb_glr_band, fb_friction_factor: vlp.fb_friction_factor,
  fancher_brown_gradient: vlp.fancher_brown_gradient,
  // ---- well.py / well.js ----
  build_steps: (w, ...rest) => wellmod.buildSteps(build(w), ...rest),
  tvd_at: (w, md) => wellmod.tvd_at(build(w), md),
  ambient_at: (w, md) => wellmod.ambient_at(build(w), md),
  fluid_temperatures: (w, steps, mass, cp) => wellmod.fluidTemperatures(build(w), steps, mass, cp),
  parse_survey_text: wellmod.parseSurveyText,
  // ---- the fluids and the traverse ----
  fluid_conditions: fluidConditions, fluid_thermal: fluidThermal,
  pressure_traverse: traverse, vlp_curve: vlpCurve,
  // ---- nodal.py / nodal.js ----
  // The Python passes the IPR as a function and this side by name, so the name travels in the case
  // and both look it up their own way; everything else is the same numbers in the same order.
  solve_well: (w, f, ...rest) => nodal.solve_well(build(w), build(f), ...rest),
  curves: (w, f, ...rest) => nodal.curves(build(w), build(f), ...rest),
  match_vlp_multiplier: (w, f, ...rest) => nodal.match_vlp_multiplier(build(w), build(f), ...rest),
  match_vlp_survey: (w, f, ...rest) => nodal.match_vlp_survey(build(w), build(f), ...rest),
  // ---- advice.js: the only part of the cross-check that compares WORDS ----
  max_inclination_deg: advice.max_inclination_deg,
  correlation_advice: advice.correlation_advice,
  recommend_correlation: (i) => {
    const [key, notes] = advice.recommend_correlation(i);
    return { key, notes };
  },
  correlation_caption: advice.correlation_caption,
  find_operating_point_demo: findOperatingPointDemo,
  fluid_at_rate_demo: fluidAtRateDemo,
  sensitivity_demo: sensitivityDemo,
  sensitivity_tubing_demo: sensitivityTubingDemo,
  well_with_tubing_id_demo: (w, id_in) => nodal.well_with_tubing_id(build(w), id_in),
};

// ---- the demo wrappers, one for each in dump_nodal.py -----------------

/** A straight IPR of the given AOF and a J-shaped VLP pwf = a q^2 + b q + c. */
function findOperatingPointDemo(aof, pr, a, b, c, n_grid, q_min_frac) {
  return nodal.find_operating_point((pwf) => aof * (1.0 - pwf / pr),
                                    (q) => a * q * q + b * q + c, n_grid, q_min_frac);
}

/** fluid_at_rate(), reporting the fields that can change so they compare as numbers. */
function fluidAtRateDemo(fluid_spec, ipr_name, p_res, ipr_inputs, q) {
  const f = nodal.fluid_at_rate(build(fluid_spec), ipr_name, p_res, ipr_inputs, q);
  if (ipr_name === "gas_multilayer") return { cgr: f.cgr, wgr: f.wgr, gas_sg: f.gas_sg };
  return { water_cut: f.water_cut, gor: f.gor };
}

/** The solve inputs, built from the plain list the Python side writes out. */
function baseInputs(base) {
  const [well_s, fluid_s, ipr_name, p_res, ipr_inputs, p_wh, corr, step, n_grid, gm, fm] = base;
  return { well: build(well_s), fluid: build(fluid_s), ipr_name, p_res,
           ipr_inputs: { ...ipr_inputs }, p_wh, correlation: corr, max_step_ft: step,
           n_grid, gravity_mult: gm, friction_mult: fm };
}

function sensitivityDemo(base, name, values, with_curves, n_points) {
  return nodal.sensitivity(baseInputs(base), name, values, with_curves, n_points);
}

/** The tubing-size sensitivity: each value is a whole new well, and the row carries the diameter. */
function sensitivityTubingDemo(base, ids, n_points) {
  const inputs = baseInputs(base);
  const wells = ids.map((d) => nodal.well_with_tubing_id(inputs.well, d));
  const rows = nodal.sensitivity(inputs, "well", wells, false, n_points);
  rows.forEach((row, i) => { row.value = ids[i]; });
  return rows;
}

/**
 * Fields whose whole job is to be zero, so a RELATIVE comparison of them is meaningless: they are a
 * leftover residual of a root-finding solve, not a result.  Python and JavaScript halve the interval
 * the same number of times but accumulate rounding differently, so their residuals differ in the
 * last digits of a number that is already around 1e-11.  For these the test is that both are
 * negligible, which is what the solve promises.
 */
const NEAR_ZERO_FIELDS = new Set(["residual_at_root"]);
const NEAR_ZERO_LIMIT = 1e-6;

/** Relative difference, falling back to the absolute one for numbers near zero. */
function diff(got, want) {
  if (want === null || got === null) return want === got ? 0 : Infinity;
  // words, and anything else that is not a number, must match exactly: advice.js and app_helpers.py
  // have to say the same sentence about the same well
  if (typeof want === "string" || typeof got === "string") return got === want ? 0 : Infinity;
  if (!Number.isFinite(got) || !Number.isFinite(want)) return got === want ? 0 : Infinity;
  const scale = Math.max(Math.abs(want), 1e-9);
  return Math.abs(got - want) / scale;
}

/** Walk a number, a list or a dictionary of numbers and return the worst difference in it. */
function worstDiff(got, want, label, onField) {
  if (Array.isArray(want)) {
    let worst = 0;
    for (let i = 0; i < want.length; i++) worst = Math.max(worst, worstDiff(got[i], want[i], `${label}[${i}]`, onField));
    return worst;
  }
  if (want !== null && typeof want === "object") {
    let worst = 0;
    for (const key of Object.keys(want)) worst = Math.max(worst, worstDiff(got[key], want[key], `${label}.${key}`, onField));
    return worst;
  }
  const field = label.split(".").pop();
  if (field !== undefined && NEAR_ZERO_FIELDS.has(field)) {
    const d0 = Math.abs(got) < NEAR_ZERO_LIMIT && Math.abs(want) < NEAR_ZERO_LIMIT ? 0 : diff(got, want);
    onField(label, d0, got, want);
    return d0;
  }
  const d = diff(got, want);
  onField(label, d, got, want);
  return d;
}

const TOLERANCE = 1e-9;          // ten decimal places: the two should differ only by rounding

function main() {
  const files = ["tools/pvt_expected.json", "tools/ipr_expected.json",
                 "tools/vlp_expected.json", "tools/nodal_expected.json",
                 "tools/advice_expected.json"].filter(existsSync);
  if (files.length === 0) {
    console.error("No expected-answer file found. Run first:\n  PYTHONPATH=.. python3 tools/dump_pvt.py tools/pvt_expected.json\n  PYTHONPATH=.. python3 tools/dump_ipr.py tools/ipr_expected.json\n  PYTHONPATH=.. python3 tools/dump_vlp.py tools/vlp_expected.json\n  python3 tools/dump_nodal.py tools/nodal_expected.json");
    process.exit(2);
  }

  let total = 0, failures = 0, missing = new Set();
  const byName = new Map();          // name -> {worst, where, got, want, count}

  for (const file of files) {
    for (const row of JSON.parse(readFileSync(file, "utf8"))) {
      const fn = MAP[row.func];
      if (!fn) { missing.add(row.func); continue; }
      total++;
      // A case the Python refused on purpose (an input it rejects, a match that cannot be reached):
      // the JavaScript must refuse it too, and the message is its own business.
      const wantsError = row.want !== null && typeof row.want === "object" && "error" in row.want;
      let got;
      try {
        got = fn(...row.args);
      } catch (error) {
        if (wantsError) {
          const rec = byName.get(row.name) || { worst: 0, where: "", got: null, want: null, count: 0 };
          rec.count++;
          byName.set(row.name, rec);
          continue;                 // both refused: that is agreement
        }
        failures++;
        console.log(`  THREW  ${row.name}(${JSON.stringify(row.args)}) -> ${error.message}`);
        continue;
      }
      if (wantsError) {
        failures++;
        console.log(`  SHOULD HAVE REFUSED  ${row.name}(${JSON.stringify(row.args)})`);
        console.log(`         the Python raised ${row.want.error}; the JavaScript returned ${JSON.stringify(got)}`);
        continue;
      }
      const record = byName.get(row.name) || { worst: 0, where: "", got: null, want: null, count: 0 };
      record.count++;
      const worst = worstDiff(got, row.want, row.name, (label, d, g, w) => {
        if (d > record.worst) { record.worst = d; record.where = label; record.got = g; record.want = w; }
      });
      byName.set(row.name, record);
      if (worst > TOLERANCE) {
        failures++;
        if (failures <= 10) {
          console.log(`  DIFFER ${row.name}  args=${JSON.stringify(row.args)}`);
          console.log(`         worst at ${record.where}: javascript ${record.got}  python ${record.want}  (relative ${worst.toExponential(2)})`);
        }
      }
    }
  }

  console.log("\n  function                        cases      worst relative difference");
  console.log("  " + "-".repeat(70));
  for (const [name, r] of [...byName.entries()].sort((a, b) => b[1].worst - a[1].worst)) {
    const flag = r.worst > TOLERANCE ? "  <-- TOO BIG" : "";
    console.log(`  ${name.padEnd(30)} ${String(r.count).padStart(6)}      ${r.worst.toExponential(2)}${flag}`);
  }
  if (missing.size) console.log(`\n  not compared (no JavaScript yet): ${[...missing].join(", ")}`);

  const overall = Math.max(0, ...[...byName.values()].map((r) => r.worst));
  console.log(`\n  ${total} cases compared, ${failures} outside the tolerance of ${TOLERANCE.toExponential(0)}.`);
  console.log(`  Largest disagreement anywhere: ${overall.toExponential(2)}`);
  if (failures === 0) console.log("  The JavaScript matches the Python.");
  process.exit(failures === 0 ? 0 : 1);
}

main();
