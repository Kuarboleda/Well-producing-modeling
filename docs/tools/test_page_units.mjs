// Drives the real page in a real browser: enters a well in oilfield units, switches to metric, and
// checks that the well did not change - only the units it is written in.  This is the test that
// matters for the unit systems, because it exercises the page, not just the conversion table
// (tools/test_units.mjs does that part).
//
// To run it:
//   npm install playwright && npx playwright install chromium     (once)
//   python3 -m http.server 8765                                   (in the docs folder, in another window)
//   node tools/test_page_units.mjs
//
// Expect "All page checks passed." and nothing else.

import { chromium } from "playwright";

const BASE = process.env.PAGE_URL || "http://127.0.0.1:8765/";
let bad = 0;
const check = (what, ok, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"}  ${what}${detail ? "  " + detail : ""}`);
  if (!ok) bad += 1;
};
const near = (a, b, tol) => Math.abs(a - b) <= tol * Math.max(Math.abs(b), 1e-12);

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("pageerror", (e) => { console.log("PAGE ERROR:", e.message); bad += 1; });
await page.goto(BASE, { waitUntil: "networkidle" });

const val = (id) => page.$eval(`#${id}`, (n) => n.value);
const setVal = async (id, v) => {
  await page.$eval(`#${id}`, (n, v) => { n.value = v; n.dispatchEvent(new Event("input", { bubbles: true })); }, v);
};
// the results panel is a list of key/value pairs, read straight from the DOM
const results = () => page.$$eval("#results li", (lis) => lis.map(
  (li) => [li.querySelector(".k")?.textContent || "", li.querySelector(".v")?.textContent || ""]));
const labelOf = (id) => page.$eval(`#${id}`, (n) => n.closest("label").innerText.replace(/\s+/g, " ").trim());
const numberFrom = (pairs, key) => {
  const hit = pairs.find(([k]) => k.includes(key));
  return hit ? Number(String(hit[1]).replace(/,/g, "")) : NaN;
};
const keysOf = (pairs) => pairs.map(([k]) => k).join(" | ");

// ---- 1. the page starts in oilfield units ----
check("starts in Oilfield", (await val("unit_system")) === "field");
check("pressure label says psig", (await labelOf("p_res")).includes("psig"), await labelOf("p_res"));

// ---- 2. a Darcy oil well.  The page opens with the same default inputs as the Python app, so
//         choosing the Darcy model is all that is needed. ----
await page.selectOption("#oil_ipr", "darcy");
await page.waitForTimeout(250);
const fieldText = await results();
const aofField = numberFrom(fieldText, "AOF");
const jField = numberFrom(fieldText, "PI from the rock");
check("field AOF is a sensible number", Number.isFinite(aofField) && aofField > 0, `AOF = ${aofField} STB/d`);
// the Python gives 1,874 STB/d for these defaults, worked out by hand when pressures moved to psig
check("field AOF agrees with the Python", near(aofField, 1874, 1e-3), `${aofField} STB/d`);
check("field PI is a sensible number", Number.isFinite(jField) && jField > 0, `J = ${jField} STB/d/psi`);
const fieldInputs = {};
for (const id of ["p_res", "t_res", "oil_k", "oil_h", "oil_bo", "oil_mu", "oil_re", "oil_rw", "pb"]) {
  fieldInputs[id] = Number(await val(id));
}

// ---- 3. switch to metric ----
await page.selectOption("#unit_system", "metric");
await page.waitForTimeout(250);
const metricText = await results();

check("pressure label now says barg", (await labelOf("p_res")).includes("barg"), await labelOf("p_res"));
check("length label now says m", (await labelOf("oil_h")).includes("(m)"), await labelOf("oil_h"));
check("temperature label now says degC", (await labelOf("t_res")).includes("degC"));
check("permeability label still says md", (await labelOf("oil_k")).includes("md"));

// the boxes must now hold the same well, written in metric
check("3000 psig became 206.84 barg",
      near(Number(await val("p_res")), fieldInputs.p_res / 14.5037738, 1e-4),
      `${await val("p_res")} barg`);
check("200 degF became 93.3 degC",
      near(Number(await val("t_res")), (fieldInputs.t_res - 32) * 5 / 9, 1e-4),
      `${await val("t_res")} degC`);
check("20 ft became 6.096 m",
      near(Number(await val("oil_h")), fieldInputs.oil_h * 0.3048, 1e-6), `${await val("oil_h")} m`);
check("0.354 ft wellbore became 0.1079 m",
      near(Number(await val("oil_rw")), fieldInputs.oil_rw * 0.3048, 1e-4), `${await val("oil_rw")} m`);
check("permeability unchanged", Number(await val("oil_k")) === fieldInputs.oil_k);
check("Bo unchanged", Number(await val("oil_bo")) === fieldInputs.oil_bo);
check("viscosity unchanged", Number(await val("oil_mu")) === fieldInputs.oil_mu);

// and the ANSWER must be the same physical well
const aofMetric = numberFrom(metricText, "AOF");
const jMetric = numberFrom(metricText, "PI from the rock");
check("AOF is the same rate in m3/d", near(aofMetric, aofField / 6.2898106, 2e-3),
      `${aofMetric} m3/d vs ${(aofField / 6.2898106).toFixed(1)} expected`);
check("PI is the same in m3/d/bar", near(jMetric, jField * 14.5037738 / 6.2898106, 2e-3),
      `${jMetric} vs ${(jField * 14.5037738 / 6.2898106).toFixed(3)} expected`);
check("results now say m3/d", keysOf(metricText).includes("m3/d"), keysOf(metricText));
check("results now say barg", keysOf(metricText).includes("barg"));

// ---- 4. and back again ----
await page.selectOption("#unit_system", "field");
await page.waitForTimeout(250);
for (const [id, was] of Object.entries(fieldInputs)) {
  check(`${id} returns to ${was}`, near(Number(await val(id)), was, 1e-6), `now ${await val(id)}`);
}
const backText = await results();
check("AOF returns to its field value", near(numberFrom(backText, "AOF"), aofField, 2e-3));

// ---- 5. the gas back-pressure case, whose C unit contains n ----
await page.selectOption("#fluid_type", "gas");
await page.selectOption("#gas_ipr", "backpressure");
await setVal("p_res", "4500");
await setVal("bp_c", "0.015");
await setVal("bp_n", "0.85");
await page.waitForTimeout(250);
const bpField = numberFrom(await results(), "AOF");
check("back-pressure AOF in Mscf/d", Number.isFinite(bpField) && bpField > 0, `${bpField} Mscf/d`);
check("C label shows its unit with n", (await labelOf("bp_c")).includes("psia^2n"), await labelOf("bp_c"));

await page.selectOption("#unit_system", "metric");
await page.waitForTimeout(250);
const bpMetric = numberFrom(await results(), "AOF");
check("back-pressure AOF is the same rate in e3m3/d",
      near(bpMetric, bpField * 0.0283168, 3e-3),
      `${bpMetric} vs ${(bpField * 0.0283168).toFixed(2)} expected`);
check("C label is now metric", (await labelOf("bp_c")).includes("bara^2n"), await labelOf("bp_c"));

// ---- 6. a number typed while in metric survives a round trip ----
await setVal("p_res", "250");                    // 250 barg
await page.waitForTimeout(200);
const typedMetric = numberFrom(await results(), "Reservoir pressure");
check("a pressure typed in metric is read as metric", near(typedMetric, 250, 1e-6), `${typedMetric} barg`);
await page.selectOption("#unit_system", "field");
await page.waitForTimeout(200);
check("250 barg reads as 3625.9 psig",
      near(Number(await val("p_res")), 250 * 14.5037738, 1e-4), `${await val("p_res")} psig`);
await page.selectOption("#unit_system", "metric");
await page.waitForTimeout(200);
check("and comes back as exactly 250", (await val("p_res")) === "250", await val("p_res"));

// ---- 7. the page opens with the Python app's own default inputs ----
const fresh = await browser.newPage();
await fresh.goto(BASE, { waitUntil: "networkidle" });
const defaults = { fluid_type: "oil", p_res: "3000", t_res: "200", oil_ipr: "pi", pi: "3",
                   pb: "2484", oil_k: "50", oil_h: "20", oil_bo: "1.25", oil_mu: "0.8",
                   oil_re: "1000", oil_rw: "0.354", oil_skin: "0", oil_regime: "pseudosteady",
                   gas_ipr: "jones", gas_sg_g: "0.65", gas_k: "5", gas_h: "40", gas_re: "1000",
                   gas_rw: "0.354", gas_skin: "0", gas_beta: "0", bp_c: "0.015", bp_n: "0.85" };
for (const [id, want] of Object.entries(defaults)) {
  const got = await fresh.$eval(`#${id}`, (n) => n.value);
  check(`default ${id} is ${want}`, got === want, got === want ? "" : `got ${got}`);
}
await fresh.close();

await browser.close();
console.log(bad === 0 ? "\nAll page checks passed." : `\n${bad} failure(s).`);
process.exit(bad === 0 ? 0 : 1);
