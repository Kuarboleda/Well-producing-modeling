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
};

/** Relative difference, falling back to the absolute one for numbers near zero. */
function diff(got, want) {
  if (want === null || got === null) return want === got ? 0 : Infinity;
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
  const d = diff(got, want);
  onField(label, d, got, want);
  return d;
}

const TOLERANCE = 1e-9;          // ten decimal places: the two should differ only by rounding

function main() {
  const files = ["tools/pvt_expected.json", "tools/ipr_expected.json",
                 "tools/vlp_expected.json"].filter(existsSync);
  if (files.length === 0) {
    console.error("No expected-answer file found. Run first:\n  PYTHONPATH=.. python3 tools/dump_pvt.py tools/pvt_expected.json\n  PYTHONPATH=.. python3 tools/dump_ipr.py tools/ipr_expected.json\n  PYTHONPATH=.. python3 tools/dump_vlp.py tools/vlp_expected.json");
    process.exit(2);
  }

  let total = 0, failures = 0, missing = new Set();
  const byName = new Map();          // name -> {worst, where, got, want, count}

  for (const file of files) {
    for (const row of JSON.parse(readFileSync(file, "utf8"))) {
      const fn = MAP[row.func];
      if (!fn) { missing.add(row.func); continue; }
      total++;
      let got;
      try {
        got = fn(...row.args);
      } catch (error) {
        failures++;
        console.log(`  THREW  ${row.name}(${JSON.stringify(row.args)}) -> ${error.message}`);
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
