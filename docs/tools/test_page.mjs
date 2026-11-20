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
const lineFor = (what) => prof.traces.find((t) => t.name.includes(what));
check("depth runs downwards", prof.layout.yaxis.autorange === "reversed");
check("the profile has a pressure line and a temperature line",
      Boolean(lineFor("Pressure")) && Boolean(lineFor("Temperature")));
// temperature on the bottom axis, pressure on the top one
check("temperature is on the bottom axis", prof.layout.xaxis.title.text.includes("degF"),
      prof.layout.xaxis.title.text);
check("pressure is on the top axis", prof.layout.xaxis2.title.text.includes("psig")
      && prof.layout.xaxis2.side === "top", prof.layout.xaxis2.title.text);
check("the pressure line is drawn against the top axis", lineFor("Pressure").xaxis === "x2");
check("the pressure line is the same blue as the IPR",
      lineFor("Pressure").line.color === first.traces[0].line.color,
      `${lineFor("Pressure").line.color} vs IPR ${first.traces[0].line.color}`);
check("the profile starts at the wellhead pressure", near(lineFor("Pressure").x[0], 200, 1e-6),
      `${lineFor("Pressure").x[0]} psig`);
check("the profile ends at the operating Pwf", near(lineFor("Pressure").x.at(-1), pwf, 2e-3),
      `${lineFor("Pressure").x.at(-1)} vs ${pwf}`);
check("the profile ends at the reservoir temperature",
      near(lineFor("Temperature").x.at(-1), 200, 1e-6),
      `${lineFor("Temperature").x.at(-1)} degF`);
const profNote = await page.$eval("#profile-note", (n) => n.innerText);
check("the profile note reports both ends", profNote.includes("wellhead") && profNote.includes("perforations"));
check("the profile note reports the gravity/friction split", profNote.includes("gravity") && profNote.includes("friction"));
check("the profile note lists flow patterns", /\d+ %/.test(profNote), profNote.slice(-90));

// ---- 3. a second correlation gives a different answer, as it must ----
// Orkiszewski is offered for an oil well but is not the one the app suggests for 35 API
await page.selectOption("#correlation", "orkiszewski");
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate",
                           null, { timeout: 30000 });
const q2 = numberFrom(await results(), "Rate (");
check("another correlation gives a different rate", Number.isFinite(q2) && Math.abs(q2 - q) > 1,
      `${q2} vs ${q} STB/d`);

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

// ---- 7a. the correlation is chosen for the well, with a reason ----
const whyText = () => page.$eval("#corr-why", (n) => n.innerText);
const whyClass = () => page.$eval("#corr-why", (n) => n.className);
// section 3 chose a correlation by hand, which stops the app moving the box; put it back on auto
if (!(await page.$eval("#btn-follow", (n) => n.classList.contains("hidden")))) {
  await page.click("#btn-follow");
  await page.waitForTimeout(250);
}
check("the correlation box starts on the app's suggestion",
      (await val("correlation")) === "hagedorn_brown", await val("correlation"));
const offered = await page.$$eval("#correlation option", (os) => os.map((o) => o.value));
check("Gray is not offered for an oil well", !offered.includes("gray"), offered.join(","));
check("the seven that apply are offered", offered.length === 7, offered.join(","));
check("the advice names the correlation first",
      (await whyText()).startsWith("Hagedorn and Brown"), (await whyText()).slice(0, 60));
check("the advice says it suits this well", (await whyText()).includes("looks well suited"));
check("the advice always points at measured data",
      (await whyText()).includes("downhole pressure gauge") && (await whyText()).includes("gradient survey"));
check("a well-suited correlation is marked good", (await whyClass()).includes("good"), await whyClass());

// a deviated well must change the suggestion to the one made for any angle
await page.selectOption("#survey_mode", "deviated");
await page.waitForTimeout(250);
check("a deviated well is given Mukherjee and Brill",
      (await val("correlation")) === "mukherjee_brill", await val("correlation"));
check("the reason says it is made for any angle",
      (await whyText()).includes("any angle"), (await whyText()).slice(0, 90));
await page.selectOption("#survey_mode", "vertical");
await page.waitForTimeout(250);

// a high water cut must turn Duns and Ros to caution
await page.selectOption("#correlation", "duns_ros");
await page.waitForTimeout(200);
check("choosing by hand stops the box moving", (await val("correlation")) === "duns_ros");
check("it says Duns and Ros may not suit a 30 % water well",
      (await whyText()).includes("may not suit") && (await whyText()).includes("less than 10 % water"),
      (await whyText()).slice(0, 130));
check("a doubtful correlation is marked caution", (await whyClass()).includes("caution"));
check("it still offers the app's own suggestion",
      (await page.$eval("#btn-follow", (n) => n.innerText)).includes("Hagedorn and Brown"),
      await page.$eval("#btn-follow", (n) => n.innerText));
await page.click("#btn-follow");
await page.waitForTimeout(250);
check("the button puts the suggestion back", (await val("correlation")) === "hagedorn_brown");
check("and the button goes away", await page.$eval("#btn-follow", (n) => n.classList.contains("hidden")));

// heavy oil: Orkiszewski's own paper found it best there, so its advice must say so.  (It does not
// become the suggestion: Hagedorn and Brown is rated just as well in a vertical well and comes
// first in the preference order, exactly as in the Python.)
await setVal("api", "15");
await page.selectOption("#correlation", "orkiszewski");
await page.waitForTimeout(250);
check("heavy oil makes Orkiszewski well suited",
      (await whyText()).includes("looks well suited") && (await whyText()).includes("heavy oil"),
      (await whyText()).slice(0, 110));
check("and it is marked good", (await whyClass()).includes("good"), await whyClass());
await setVal("api", "35");
await page.waitForTimeout(250);
check("at 35 API it is only usable, not well suited",
      (await whyText()).includes("should be usable"), (await whyText()).slice(0, 90));
await page.click("#btn-follow");
await page.waitForTimeout(250);

// a gas well must be given Gray
await page.selectOption("#fluid_type", "gas");
await page.waitForTimeout(250);
check("a gas well is given Gray", (await val("correlation")) === "gray", await val("correlation"));
await setVal("cgr", "200");
await page.waitForTimeout(250);
check("a very wet gas turns Gray to caution and moves away from it",
      (await val("correlation")) !== "gray", await val("correlation"));
check("the reason gives the condensate limit",
      (await whyText()).includes("50 STB/MMscf") || (await whyText()).includes("liquid dropout"),
      (await whyText()).slice(0, 130));
await setVal("cgr", "0");
await page.selectOption("#fluid_type", "oil");
await page.waitForTimeout(250);

// ---- 7b. comparing the correlations with measured data ----
await page.click("#tab-corr");
await page.waitForTimeout(150);
const ticks = await page.$$eval("#vc-corrs input", (ns) => ns.map((n) => n.id));
check("one tick box per correlation the fluid offers", ticks.length === 7, ticks.join(","));
check("they all start ticked",
      (await page.$$eval("#vc-corrs input:checked", (ns) => ns.length)) === 7);
check("the gas lift boxes are grey when there is no gas lift",
      await page.$eval("#vc_gl_rate", (n) => n.disabled));
check("and the page says why",
      (await page.$eval("#vc-gl-note", (n) => n.innerText)).includes("grey"));

// no data yet: it must say so, not break
await page.click("#btn-compare");
await page.waitForTimeout(1500);
check("with no measured data it asks for some",
      (await page.$eval("#corr-messages", (n) => n.innerText)).includes("at least one measured point"),
      (await page.$eval("#corr-messages", (n) => n.innerText)).slice(0, 90));

// A two-point gradient survey that IS what Beggs and Brill calculates for these test conditions
// (1,084 psig at 4,000 ft and 2,379 psig at 8,000 ft, worked out from the engine itself).  Feeding
// the page its own answer is the one case where the right result is known in advance: Beggs and
// Brill must come out closest, with an error of a few psi at most.
await setVal("vc_points", "4000 1084\n8000 2379");
await setVal("vc_p_wh", "200");
await setVal("vc_rate", "2000");
await page.click("#btn-compare");
await page.waitForFunction(() => document.querySelector("#btn-compare").textContent === "Compare with the measured data",
                           null, { timeout: 180000 });
await page.waitForTimeout(400);
const cmpRows = await page.$$eval("#corr-table tr", (rs) => rs.length);
check("every ticked correlation is in the table", cmpRows === 8, `${cmpRows} rows incl. header`);
const rmsCol = await page.$$eval("#corr-table tr td:nth-child(4)",
                                 (ts) => ts.map((t) => Number(t.textContent.replace(/,/g, ""))));
check("every one reports an RMS error", rmsCol.filter((v) => Number.isFinite(v)).length >= 7,
      rmsCol.join(","));
const cmpNote = await page.$eval("#corr-note", (n) => n.innerText);
check("the closest correlation is named", cmpNote.includes("Closest to the measured data"),
      cmpNote.slice(0, 150));
check("the data came from Beggs and Brill, so that is the closest",
      cmpNote.includes("Closest to the measured data: Beggs and Brill"), cmpNote.slice(0, 160));
const bbRms = await page.$$eval("#corr-table tr", (rs) => {
  const row = rs.find((r) => r.children[0] && r.children[0].textContent.startsWith("Beggs and Brill"));
  return row ? Number(row.children[3].textContent.replace(/,/g, "")) : NaN;
});
check("and it reproduces its own survey to within a few psi", bbRms < 5, `RMS ${bbRms} psi`);
check("the sign convention is explained", cmpNote.includes("over-predicts"));
const surveyPlot = await plotOf("chart-survey");
check("the chart shows the measured points", surveyPlot.traces.at(-1).name === "Measured");
check("and one line per correlation", surveyPlot.traces.length === 8,
      `${surveyPlot.traces.length} traces`);
check("depth runs downwards there too", surveyPlot.layout.yaxis.autorange === "reversed");

// ---- 7c. matching the chosen correlation to that data ----
await page.selectOption("#correlation", "duns_ros");
await page.waitForTimeout(200);
await page.selectOption("#match_fit", "both");
await page.click("#btn-match");
await page.waitForFunction(() => !document.querySelector("#btn-match").disabled,
                           null, { timeout: 180000 });
await page.waitForTimeout(300);
const matchNote = await page.$eval("#match-messages", (n) => n.innerText);
check("the match reports both multipliers and the error before and after",
      matchNote.includes("gravity x") && matchNote.includes("friction x")
        && matchNote.includes("root-mean-square"), matchNote.slice(0, 170));
const gm = Number(await val("gravity_mult"));
const fm = Number(await val("friction_mult"));
check("the multipliers landed in the boxes", gm >= 0.1 && gm <= 10 && fm >= 0.1 && fm <= 10,
      `gravity ${gm}, friction ${fm}`);
// matching must have made the fit better, which is the only claim worth making about it
const rmsPair = matchNote.match(/from ([\d,]+) to ([\d,]+)/);
check("the match improved the fit", rmsPair
        && Number(rmsPair[2].replace(/,/g, "")) <= Number(rmsPair[1].replace(/,/g, "")),
      rmsPair ? rmsPair.slice(1).join(" -> ") : matchNote.slice(0, 90));
// and the matched run must appear in the comparison, so it can be judged against the rest
await page.click("#btn-compare");
await page.waitForFunction(() => document.querySelector("#btn-compare").textContent === "Compare with the measured data",
                           null, { timeout: 180000 });
await page.waitForTimeout(400);
const labels = await page.$$eval("#corr-table tr td:first-child", (ts) => ts.map((t) => t.textContent));
check("the matched correlation is shown alongside the published ones",
      labels.some((t) => t.includes("matched")), labels.join(" | "));
await page.click("#btn-reset-mult");
check("reset puts the multipliers back to 1",
      (await val("gravity_mult")) === "1" && (await val("friction_mult")) === "1");
await page.selectOption("#correlation", "beggs_brill");
await page.waitForTimeout(200);

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

// A fresh page must open with the same inputs as the Python app's DEFAULTS.  browser.newPage() makes
// its own browser context, so this page has empty storage and is a first-time visitor - which is the
// point: the remembered-well feature must not change what a newcomer sees.
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
                   roughness_in: "0.0006", p_wh: "200",
                   // the correlation box is not a default: the app chooses it from the well, and
                   // for these inputs (35 API, 30 % water, vertical) that is Hagedorn and Brown
                   correlation: "hagedorn_brown",
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

// ---- 13. the build marker, so a cached page can be spotted ----
const build = await page.$eval("#build", (n) => n.innerText);
check("the page shows which build it is", /^build \d{2} \w{3} \d{4} \d{2}:\d{2} \(/.test(build), build);

// ---- 14. no errors anywhere ----
check("no page errors at all", errors.length === 0, errors.slice(0, 3).join(" | "));

await browser.close();
console.log(bad === 0 ? "\nAll page checks passed." : `\n${bad} failure(s).`);
process.exit(bad === 0 ? 0 : 1);
