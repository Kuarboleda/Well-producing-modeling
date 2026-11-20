// Drives the whole page in a real browser: every tab, every button, both unit systems, an oil well
// and a gas well, gas lift, a deviated survey, and a bad input.  This is the test that says the page
// WORKS; the engine behind it is checked against the Python by tools/crosscheck.mjs, and the unit
// conversions on their own by tools/test_units.mjs.
//
// To run it:
//   npm install playwright && npx playwright install chromium     (once)
//   python3 -m http.server 8765                                   (in the docs folder, another window)
//   node tools/test_page.mjs
//
// Expect "All page checks passed." and nothing else.

import { chromium } from "playwright";

const BASE = process.env.PAGE_URL || "http://127.0.0.1:8765/";
let bad = 0;
const check = (what, ok, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"}  ${what}${detail ? "  " + detail : ""}`);
  if (!ok) bad += 1;
};

const browser = await chromium.launch();
const page = await browser.newPage();
// cdn.plot.ly cannot be reached from here, so a stub records what the page asks to draw.  The test
// is about the numbers and the labels the page produces, which is what this captures; whether
// Plotly then draws them correctly is Plotly's business.
await page.addInitScript(() => {
  window.__plots = {};
  window.Plotly = {
    newPlot: (node, traces, layout) => { window.__plots[node.id] = { traces, layout }; },
    purge: (node) => { delete window.__plots[node.id]; },
  };
});
const errors = [];
page.on("pageerror", (e) => { errors.push(e.message); });
page.on("console", (m) => {
  // cdn.plot.ly is unreachable from this sandbox, and the stub above stands in for it, so its
  // failure to load is the one console error that is expected here
  if (m.type() === "error" && !m.text().includes("Failed to load resource")) {
    errors.push("console: " + m.text());
  }
});
await page.goto(BASE, { waitUntil: "networkidle" });
// the sidebar sections start closed, like the Streamlit expanders; open them all so the test can
// reach every box
await page.$$eval("details.group", (ds) => ds.forEach((d) => { d.open = true; }));

const val = (id) => page.$eval(`#${id}`, (n) => n.value);
const setVal = async (id, v) => {
  await page.$eval(`#${id}`, (n, v) => { n.value = v; n.dispatchEvent(new Event("input", { bubbles: true })); }, v);
};
const results = () => page.$$eval("#results li", (lis) => lis.map(
  (li) => [li.querySelector(".k")?.textContent || "", li.querySelector(".v")?.textContent || ""]));
const numberFrom = (pairs, key) => {
  const hit = pairs.find(([k]) => k.includes(key));
  return hit ? Number(String(hit[1]).replace(/,/g, "")) : NaN;
};
const traceCount = (id) => page.evaluate((id) => (window.__plots[id]?.traces || []).length, id);
const plotOf = (id) => page.evaluate((id) => window.__plots[id] || null, id);
const noteText = () => page.$eval("#messages", (n) => n.innerText.trim()).catch(() => "");
const near = (a, b, tol) => Math.abs(a - b) <= tol * Math.max(Math.abs(b), 1e-12);

// ---- 1. the page opens with the inflow only ----
check("opens with an AOF", numberFrom(await results(), "AOF") > 0, `${numberFrom(await results(), "AOF")} STB/d`);
// PI = 3 STB/d/psi, Pr = 3,014.7 psia, Pb = 2,498.4 psia: the composite (Vogel below Pb) AOF
check("the AOF matches the Python PI default", near(numberFrom(await results(), "AOF"), 5713, 1e-3),
      `${numberFrom(await results(), "AOF")}`);
check("the bubble point is calculated from the PVT",
      near(numberFrom(await results(), "Bubble point"), 2484, 1e-3),
      `${numberFrom(await results(), "Bubble point")} psig`);
check("it says to press Calculate", (await noteText()).includes("Calculate"));
check("one line on the IPR chart", (await traceCount("chart-nodal")) === 1);
const first = await plotOf("chart-nodal");
check("the chart axis is labelled in psig", first.layout.yaxis.title.text.includes("psig"),
      first.layout.yaxis.title.text);
check("the chart x axis is labelled in STB/d", first.layout.xaxis.title.text.includes("STB/d"),
      first.layout.xaxis.title.text);
check("the chart y axis starts at zero gauge, not -14.7", first.layout.yaxis.range[0] === 0,
      String(first.layout.yaxis.range));

// ---- 2. Calculate: the operating point and the profile ----
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate",
                           null, { timeout: 30000 });
await page.waitForTimeout(400);
const r = await results();
const q = numberFrom(r, "Rate (");
const pwf = numberFrom(r, "Pwf (");
check("an operating rate appears", Number.isFinite(q) && q > 0, `${q} STB/d`);
check("an operating Pwf appears", Number.isFinite(pwf) && pwf > 0, `${pwf} psig`);
check("Pwf is between the wellhead and the reservoir pressure", pwf > 200 && pwf < 3000, `${pwf} psig`);
check("an oil rate is shown too", Number.isFinite(numberFrom(r, "Oil rate")),
      `${numberFrom(r, "Oil rate")} STB/d`);
check("the oil rate is 70 % of the liquid rate",
      near(numberFrom(r, "Oil rate"), q * 0.7, 2e-3));
check("IPR, VLP and the operating point are all drawn", (await traceCount("chart-nodal")) >= 3,
      `${await traceCount("chart-nodal")} traces`);
check("the profile chart is drawn", (await traceCount("chart-profile")) === 2);
const prof = await plotOf("chart-profile");
check("depth runs downwards", prof.layout.yaxis.autorange === "reversed");
check("the profile has a pressure line and a temperature line",
      prof.traces[0].name.includes("Pressure") && prof.traces[1].name.includes("Temperature"));
check("the profile starts at the wellhead pressure", near(prof.traces[0].x[0], 200, 1e-6),
      `${prof.traces[0].x[0]} psig`);
check("the profile ends at the operating Pwf", near(prof.traces[0].x.at(-1), pwf, 2e-3),
      `${prof.traces[0].x.at(-1)} vs ${pwf}`);
check("the profile ends at the reservoir temperature", near(prof.traces[1].x.at(-1), 200, 1e-6),
      `${prof.traces[1].x.at(-1)} degF`);
const profNote = await page.$eval("#profile-note", (n) => n.innerText);
check("the profile note reports both ends", profNote.includes("wellhead") && profNote.includes("perforations"));
check("the profile note reports the gravity/friction split", profNote.includes("gravity") && profNote.includes("friction"));
check("the profile note lists flow patterns", /\d+ %/.test(profNote), profNote.slice(-90));

// ---- 3. a second correlation gives a different answer, as it must ----
await page.selectOption("#correlation", "hagedorn_brown");
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate",
                           null, { timeout: 30000 });
const q2 = numberFrom(await results(), "Rate (");
check("Hagedorn and Brown gives a different rate", Number.isFinite(q2) && Math.abs(q2 - q) > 1,
      `${q2} vs ${q} STB/d`);
await page.selectOption("#correlation", "beggs_brill");

// ---- 4. a deviated survey ----
await page.selectOption("#survey_mode", "deviated");
await page.waitForTimeout(200);
check("the survey box appears", await page.$eval("#f-survey", (n) => !n.classList.contains("hidden")));
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate",
                           null, { timeout: 30000 });
const qDev = numberFrom(await results(), "Rate (");
check("the deviated well solves", Number.isFinite(qDev) && qDev > 0, `${qDev} STB/d`);
check("the deviated well flows more than the vertical one (7,000 ft TVD, not 8,000)", qDev > q,
      `${qDev} vs ${q}`);
await page.selectOption("#survey_mode", "vertical");

// ---- 5. gas lift ----
await page.selectOption("#lift", "continuous");
await page.waitForTimeout(150);
check("the gas lift boxes appear", await page.$eval("#f-gl", (n) => !n.classList.contains("hidden")));
await setVal("gl_rate", "1500");
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate",
                           null, { timeout: 30000 });
const qLift = numberFrom(await results(), "Rate (");
check("the gas-lifted well solves", Number.isFinite(qLift) && qLift > 0, `${qLift} STB/d`);
check("gas lift raises the rate", qLift > q, `${qLift} with lift vs ${q} without`);
check("the injection depth is marked on the profile", (await traceCount("chart-profile")) === 3);
await page.selectOption("#lift", "none");

// ---- 6. the sensitivity tab ----
await page.click("#tab-sens");
await page.waitForTimeout(150);
check("the sensitivity page shows", await page.$eval("#page-sens", (n) => n.classList.contains("on")));
const choices = await page.$$eval("#sens_name option", (os) => os.map((o) => o.value));
check("the sensitivity list offers the wellhead pressure", choices.includes("p_wh"), choices.join(","));
check("it offers the PI for a PI well", choices.includes("ipr_inputs.J"));
check("it does not offer a gas-only input", !choices.includes("ipr_inputs.C"));
// the starting values follow the wellhead pressure already typed (200 psig), so they straddle it
check("the values follow the well", (await val("sens_values")) === "100, 150, 200, 300",
      await val("sens_values"));
await page.click("#btn-sens");
await page.waitForFunction(() => document.querySelector("#btn-sens").textContent === "Run sensitivity",
                           null, { timeout: 60000 });
await page.waitForTimeout(300);
const sensRows = await page.$$eval("#sens-table tr", (rs) => rs.length);
check("the sensitivity table has a row per value", sensRows === 5, `${sensRows} rows incl. header`);
check("the sensitivity curves are drawn", (await traceCount("chart-sens-curves")) >= 8,
      `${await traceCount("chart-sens-curves")} traces`);
check("the operating-point line is drawn", (await traceCount("chart-sens")) === 1);
const sensRates = await page.$$eval("#sens-table tr td:nth-child(2)", (ts) => ts.map((t) => t.textContent));
const flowed = sensRates.map((t) => Number(t.replace(/,/g, ""))).filter((v) => Number.isFinite(v));
check("every value flows at these starting values", flowed.length === 4, sensRates.join(" | "));
check("a higher wellhead pressure gives a lower rate",
      flowed.every((v, i) => i === 0 || v < flowed[i - 1]), sensRates.join(" | "));

// ---- 7. the correlation comparison and matching ----
await page.click("#tab-corr");
await page.waitForTimeout(150);
await page.click("#btn-corr");
await page.waitForFunction(() => document.querySelector("#btn-corr").textContent === "Compare all correlations",
                           null, { timeout: 120000 });
await page.waitForTimeout(300);
const corrRows = await page.$$eval("#corr-table tr", (rs) => rs.length);
check("every correlation is in the table", corrRows === 9, `${corrRows} rows incl. header`);
const corrRates = await page.$$eval("#corr-table tr td:nth-child(2)",
                                    (ts) => ts.map((t) => Number(t.textContent.replace(/,/g, ""))));
check("all eight give a rate", corrRates.filter((v) => v > 0).length === 8, corrRates.join(","));
check("they do not all agree (the spread is the point)",
      new Set(corrRates.map((v) => Math.round(v))).size > 3, corrRates.join(","));
const patterns = await page.$eval("#corr-table tr:nth-child(2) td:nth-child(4)", (n) => n.textContent);
check("the flow patterns are listed", /\d+ %/.test(patterns), patterns);

await setVal("match_q", "2000");
await setVal("match_pwf", "2500");
await page.click("#btn-match");
await page.waitForTimeout(3000);
const matchNote = await page.$eval("#match-messages", (n) => n.innerText);
check("the match reports a multiplier or says why not", matchNote.length > 20, matchNote.slice(0, 110));
if (matchNote.includes("multiplier that reproduces")) {
  const m = Number(await val("friction_mult"));
  check("the multiplier landed in the box", m > 0.5 && m < 2.0, `${m}`);
  await page.click("#btn-reset-mult");
  check("reset puts it back to 1", (await val("friction_mult")) === "1");
}

// ---- 8. a gas well, right through ----
await page.click("#tab-nodal");
await page.selectOption("#fluid_type", "gas");
await page.waitForTimeout(200);
check("the gas PVT section appears", await page.$eval("#pvt-gas", (n) => !n.classList.contains("hidden")));
check("gas lift is hidden for a gas well", await page.$eval("#grp-lift", (n) => n.classList.contains("hidden")));
await setVal("p_res", "4500");
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate",
                           null, { timeout: 30000 });
const gasRes = await results();
check("the gas well solves", numberFrom(gasRes, "Rate (") > 0, `${numberFrom(gasRes, "Rate (")} Mscf/d`);
check("the rate is in Mscf/d", gasRes.some(([k]) => k.includes("Mscf/d")), gasRes.map(([k]) => k).join(" | "));
check("Z is reported", Number.isFinite(numberFrom(gasRes, "Z at")), `${numberFrom(gasRes, "Z at")}`);

// a wet gas: the well-stream gravity must be heavier than the separator gas
await setVal("cgr", "40");
await page.waitForTimeout(200);
const wet = numberFrom(await results(), "Well-stream gravity");
check("a wet gas gets a heavier well-stream gravity", wet > 0.65, `${wet}`);
await setVal("cgr", "0");

// ---- 9. metric, right through ----
await page.selectOption("#fluid_type", "oil");
await setVal("p_res", "3000");
await page.waitForTimeout(150);
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate",
                           null, { timeout: 30000 });
const qField = numberFrom(await results(), "Rate (");
await page.selectOption("#unit_system", "metric");
await page.waitForTimeout(200);
check("3000 psig became 206.843 barg", near(Number(await val("p_res")), 3000 / 14.5037738, 1e-4),
      `${await val("p_res")}`);
check("8000 ft became 2438.4 m", near(Number(await val("depth")), 8000 * 0.3048, 1e-6),
      `${await val("depth")}`);
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate",
                           null, { timeout: 30000 });
const qMetric = numberFrom(await results(), "Rate (");
check("the operating rate is the same well in m3/d", near(qMetric, qField / 6.2898106, 3e-3),
      `${qMetric} m3/d vs ${(qField / 6.2898106).toFixed(1)} expected`);
check("the profile is drawn in metric", (await traceCount("chart-profile")) === 2);
await page.selectOption("#unit_system", "field");
await page.waitForTimeout(200);
check("switching back restores 3000 psig exactly", (await val("p_res")) === "3000", await val("p_res"));
check("switching back restores 8000 ft exactly", (await val("depth")) === "8000", await val("depth"));

// ---- 10. a survey in metric must convert line by line ----
await page.selectOption("#survey_mode", "deviated");
await page.selectOption("#unit_system", "metric");
await page.waitForTimeout(200);
const survey = await val("survey_text");
check("the survey depths were converted", survey.split("\n")[1].startsWith("609.6"), survey.replace(/\n/g, " / "));
await page.selectOption("#unit_system", "field");
await page.waitForTimeout(200);
check("the survey came back unchanged", (await val("survey_text")).split("\n")[1] === "2000 2000",
      (await val("survey_text")).replace(/\n/g, " / "));
await page.selectOption("#survey_mode", "vertical");

// ---- 11. a bad input must say so, not break ----
await page.selectOption("#survey_mode", "deviated");
await setVal("survey_text", "0 0");                     // one point is not a survey
await page.waitForTimeout(250);
const badNote = await page.$eval("#messages", (n) => n.innerText);
check("a one-line survey is reported, not crashed", badNote.toLowerCase().includes("survey"),
      badNote.slice(0, 90));
check("nothing stale is left in the results", (await results()).length === 0);
check("no stale chart is left", (await traceCount("chart-nodal")) === 0);
await setVal("survey_text", "0 0\n4000 4000\n8000 7600");
await page.waitForTimeout(250);
check("it recovers when the survey is fixed", numberFrom(await results(), "AOF") > 0);
await page.selectOption("#survey_mode", "vertical");
await page.waitForTimeout(200);

// ---- 12. the labels, the awkward C unit, and the page's own defaults ----
const labelOf = (id) => page.$eval(`#${id}`, (n) => n.closest("label").innerText.replace(/\s+/g, " ").trim());
check("pressure labels say psig", (await labelOf("p_res")).includes("psig"), await labelOf("p_res"));
check("permeability stays md in both systems", (await labelOf("oil_k")).includes("md"));
await page.selectOption("#fluid_type", "gas");
await page.selectOption("#gas_ipr", "backpressure");
await page.waitForTimeout(200);
check("the C label spells out its unit with n", (await labelOf("bp_c")).includes("psia^2n"),
      await labelOf("bp_c"));
const bpField = numberFrom(await results(), "AOF");
await page.selectOption("#unit_system", "metric");
await page.waitForTimeout(250);
check("the C label is metric now", (await labelOf("bp_c")).includes("bara^2n"), await labelOf("bp_c"));
check("temperature says degC", (await labelOf("t_res")).includes("degC"));
check("length says m", (await labelOf("gas_h")).includes("(m)"), await labelOf("gas_h"));
check("the back-pressure AOF is the same rate in e3m3/d",
      near(numberFrom(await results(), "AOF"), bpField * 0.0283168, 3e-3),
      `${numberFrom(await results(), "AOF")} vs ${(bpField * 0.0283168).toFixed(1)}`);
// a number typed in metric must survive the round trip exactly
await setVal("p_res", "250");
await page.waitForTimeout(200);
await page.selectOption("#unit_system", "field");
await page.waitForTimeout(200);
check("250 barg reads as 3625.9 psig", near(Number(await val("p_res")), 250 * 14.5037738, 1e-4),
      `${await val("p_res")}`);
await page.selectOption("#unit_system", "metric");
await page.waitForTimeout(200);
check("and comes back as exactly 250", (await val("p_res")) === "250", await val("p_res"));
await page.selectOption("#unit_system", "field");
await page.waitForTimeout(200);

// a fresh page must open with the same inputs as the Python app's DEFAULTS
const fresh = await browser.newPage();
await fresh.goto(BASE, { waitUntil: "networkidle" });
const defaults = { fluid_type: "oil", p_res: "3000", t_res: "200", oil_ipr: "pi", pi: "3",
                   oil_k: "50", oil_h: "20", oil_bo: "1.25", oil_mu: "0.8", oil_re: "1000",
                   oil_rw: "0.354", oil_skin: "0", oil_regime: "pseudosteady",
                   api: "35", gas_sg: "0.75", rsb: "500", oil_gor: "0", water_cut: "30",
                   water_sg: "1.02", pb_meas: "0", pvt_method: "glaso", visc_method: "beal",
                   gas_ipr: "jones", gas_sg_g: "0.65", gas_k: "5", gas_h: "40", gas_re: "1000",
                   gas_rw: "0.354", gas_skin: "0", gas_beta: "0", bp_c: "0.015", bp_n: "0.85",
                   survey_mode: "vertical", depth: "8000", tubing_id: "2.992",
                   roughness_in: "0.0006", p_wh: "200", correlation: "beggs_brill",
                   t_amb_surface: "80", u_surface: "5", u_perf: "5",
                   lift: "none", gl_rate: "1000", gl_md: "6000", gl_sg: "0.65", gl_p_inj: "1500",
                   gravity_mult: "1", friction_mult: "1" };
let wrong = [];
for (const [id, want] of Object.entries(defaults)) {
  const got = await fresh.$eval(`#${id}`, (n) => n.value);
  if (got !== want) wrong.push(`${id}: ${got} not ${want}`);
}
check(`all ${Object.keys(defaults).length} defaults match the Python DEFAULTS`, wrong.length === 0,
      wrong.join("; "));
await fresh.close();

// ---- 13. no errors anywhere ----
check("no page errors at all", errors.length === 0, errors.slice(0, 3).join(" | "));

await browser.close();
console.log(bad === 0 ? "\nAll page checks passed." : `\n${bad} failure(s).`);
process.exit(bad === 0 ? 0 : 1);
