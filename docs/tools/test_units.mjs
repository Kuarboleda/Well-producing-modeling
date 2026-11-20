// Checks units.js on its own: known hand conversions, and the rule that matters most - converting a
// number into the other system and back must give the number you started with.
//
//   node tools/test_units.mjs
//
// Run this whenever units.js is touched.  It needs nothing installed.

import * as units from "../units.js";

let checks = 0;
let bad = 0;

/**
 * Compare two numbers.  `floor` is the smallest scale worth measuring against: for a quantity with
 * an offset, such as gauge pressure (+14.7) or degF (+32), a round trip through a VERY small number
 * loses the last digits of the offset, which looks enormous as a fraction of the small number but is
 * nothing at all as a fraction of what the engine actually worked with.  Passing a floor measures
 * the error against that scale instead.
 * @param {string} what @param {number} got @param {number} want @param {number} [tol] @param {number} [floor]
 */
function close(what, got, want, tol = 1e-9, floor = 1e-30) {
  checks += 1;
  const scale = Math.max(Math.abs(want), floor);
  const diff = Math.abs(got - want) / scale;
  if (!(diff <= tol)) {
    bad += 1;
    console.log(`FAIL  ${what}: got ${got}, want ${want}  (relative difference ${diff.toExponential(2)})`);
  }
}

/** @param {string} what @param {unknown} got @param {unknown} want */
function same(what, got, want) {
  checks += 1;
  if (got !== want) {
    bad += 1;
    console.log(`FAIL  ${what}: got ${got}, want ${want}`);
  }
}

// ---------------------------------------------------------------------
// 1. hand conversions, worked out independently of the table
// ---------------------------------------------------------------------
// pressure is GAUGE on screen and ABSOLUTE in the engine
close("3000 psig -> psia", units.toEngine("pressure", 3000, "field"), 3014.7);
close("0 psig -> psia", units.toEngine("pressure", 0, "field"), 14.7);
// 3000 psig = 3000 / 14.5037738 = 206.8428... barg, and in psia that is 3014.7 again
close("3000 psig as barg", units.convert("pressure", 3000, "field", "metric"), 3000 / 14.5037738);
close("206.8428 barg -> psia", units.toEngine("pressure", 3000 / 14.5037738, "metric"), 3014.7);

close("200 degF -> degC", units.convert("temperature", 200, "field", "metric"), (200 - 32) * 5 / 9);
close("93.333 degC -> degF", units.toEngine("temperature", (200 - 32) * 5 / 9, "metric"), 200);

close("1000 ft -> m", units.convert("length", 1000, "field", "metric"), 304.8);
close("304.8 m -> ft", units.toEngine("length", 304.8, "metric"), 1000);

close("1000 STB/d -> m3/d", units.convert("liquidRate", 1000, "field", "metric"), 1000 / 6.2898106);
close("10000 Mscf/d -> e3m3/d", units.convert("gasRate", 10000, "field", "metric"), 10000 * 0.0283168);

// the productivity index: 1 STB/d/psi is a BIGGER number in m3/d/bar?  No - smaller.
// 1 STB/d/psi = (1/6.2898106) m3/d per (1/14.5037738) bar = 14.5037738/6.2898106 = 2.3060 m3/d/bar
close("1 STB/d/psi -> m3/d/bar", units.convert("pi", 1, "field", "metric"), 14.5037738 / 6.2898106);
close("PI the other way", units.convert("pi", 14.5037738 / 6.2898106, "metric", "field"), 1);

// 1000 scf/STB = 1000 / 5.6145833 = 178.1076 m3/m3
close("1000 scf/STB -> m3/m3", units.convert("gor", 1000, "field", "metric"), 1000 / 5.6145833);

close("62.4 lb/ft3 -> kg/m3", units.convert("density", 62.4, "field", "metric"), 62.4 * 16.018463);

// compressibility is 1/pressure, so it moves the OPPOSITE way to a pressure
close("1e-5 1/psi -> 1/bar", units.convert("compressibility", 1e-5, "field", "metric"), 1e-5 * 14.5037738);
// beta is 1/length, likewise
close("1e-6 1/ft -> 1/m", units.convert("inverseLength", 1e-6, "field", "metric"), 1e-6 / 0.3048);

// the ones that keep the same number
for (const q of /** @type {const} */ (["permeability", "viscosity", "fvf", "surfaceTension", "time", "fraction"])) {
  close(`${q} keeps its number`, units.convert(q, 7.25, "field", "metric"), 7.25);
}

// ---------------------------------------------------------------------
// 2. every quantity: into the other system and back again
// ---------------------------------------------------------------------
const quantities = /** @type {import("../units.js").Quantity[]} */ (Object.keys(units.QUANTITIES));
for (const q of quantities) {
  for (const value of [0, 1, 0.137, 55, 2847.6, 1.0e-6, -40]) {
    for (const from of units.SYSTEMS) {
      const to = from === "field" ? "metric" : "field";
      // the floor is 1 unit: an offset quantity cannot carry 12 digits through a round trip at a
      // value of 1e-6, and does not need to - nobody enters a millionth of a psi
      close(`${q} ${value} ${from}->${to}->${from}`,
            units.convert(q, units.convert(q, value, from, to), to, from), value, 1e-12, 1.0);
      // and the engine must see the same absolute amount whichever system it was typed in
      const inOther = units.convert(q, value, from, to);
      close(`${q} ${value} reaches the engine the same way`,
            units.toEngine(q, inOther, to), units.toEngine(q, value, from), 1e-12, 1.0);
    }
  }
}

// ---------------------------------------------------------------------
// 3. the back-pressure coefficient C, whose unit contains the exponent n
// ---------------------------------------------------------------------
// q = C (Pr^2 - Pwf^2)^n.  Converting C must leave the RATE unchanged once both the rate and the
// pressures are read in the new system.  That is what is checked here, rather than a formula.
for (const n of [1.0, 0.85, 0.6, 0.5]) {
  for (const C of [0.015, 1e-5, 3.2]) {
    const prPsia = 4514.7;                                   // 4500 psig
    const pwfPsia = 2514.7;                                  // 2500 psig
    const qField = C * (prPsia ** 2 - pwfPsia ** 2) ** n;    // Mscf/d

    const cMetric = units.convertBackpressureC(C, n, "field", "metric");
    const prBara = prPsia / 14.5037738;
    const pwfBara = pwfPsia / 14.5037738;
    const qMetric = cMetric * (prBara ** 2 - pwfBara ** 2) ** n;   // e3m3/d

    close(`C with n=${n}, C=${C}: same rate`, qMetric, qField * 0.0283168, 1e-12);
    close(`C with n=${n}, C=${C}: back again`,
          units.convertBackpressureC(cMetric, n, "metric", "field"), C, 1e-12);
  }
}

// ---------------------------------------------------------------------
// 4. the small things the screen relies on
// ---------------------------------------------------------------------
same("default system is oilfield", units.system(), "field");
same("oilfield pressure unit", units.unitOf("pressure", "field"), "psig");
same("metric pressure unit", units.unitOf("pressure", "metric"), "barg");
same("C unit in oilfield", units.backpressureCUnit("field"), "Mscf/d / psia^2n");
same("C unit in metric", units.backpressureCUnit("metric"), "e3m3/d / bara^2n");
same("a bad system name is refused", (() => {
  try { units.asSystem("imperial"); return "accepted"; } catch { return "refused"; }
})(), "refused");

// switching the system must actually change what unitOf() says, and changing it back must restore it
units.setSystem("metric");
same("after setSystem, system() follows", units.system(), "metric");
same("after setSystem, the unit follows", units.unitOf("length"), "m");
units.setSystem("field");
same("switching back restores the unit", units.unitOf("length"), "ft");

// decimalsFor must keep enough figures that a well is not rounded away
close("3000 psig in barg keeps its value",
      Number(units.convert("pressure", 3000, "field", "metric")
               .toFixed(units.decimalsFor("pressure", 206.84))), 206.843, 1e-4);
same("compressibility keeps many decimals", units.decimalsFor("compressibility", 1.45e-4) >= 10, true);

// ---------------------------------------------------------------------
console.log(`\n${checks} checks, ${bad} failure${bad === 1 ? "" : "s"}.`);
process.exit(bad === 0 ? 0 : 1);
