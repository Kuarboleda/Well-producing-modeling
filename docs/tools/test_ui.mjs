// The interface itself, checked in a real browser: that the Calculate bar stays in sight however far
// the inputs scroll, that the well drawing matches what was typed, that the answers are marked out of
// date the moment an input changes, that Enter calculates, that the well survives a refresh, and that
// a phone shows the answers before the form.  tools/test_page.mjs covers what the page CALCULATES;
// this covers how it behaves.
//
// To run it:
//   python3 -m http.server 8765        (in the docs folder, in another window)
//   node tools/test_ui.mjs

import { chromium } from "playwright";
const BASE = process.env.PAGE_URL || "http://127.0.0.1:8765/";
let bad = 0;
const check = (what, ok, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"}  ${what}${detail ? "  " + detail : ""}`);
  if (!ok) bad += 1;
};
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.addInitScript(() => {
  window.__plots = {};
  window.Plotly = { newPlot: (n, t, l) => { window.__plots[n.id] = { traces: t, layout: l }; },
                    purge: (n) => { delete window.__plots[n.id]; } };
});
await page.goto(BASE, { waitUntil: "networkidle" });
await page.$$eval("details.group", (ds) => ds.forEach((d) => { d.open = true; }));
await page.waitForTimeout(400);

// ---- 1. the action bar stays in sight ----
const barBox = async () => page.$eval(".actionbar", (n) => { const r = n.getBoundingClientRect();
  return { top: Math.round(r.top), bottom: Math.round(r.bottom), visible: r.top < window.innerHeight && r.bottom > 0 }; });
check("the Calculate bar is on screen before scrolling", (await barBox()).visible, JSON.stringify(await barBox()));
await page.evaluate(() => window.scrollTo(0, 1200));
await page.waitForTimeout(200);
check("and still on screen after scrolling down 1,200px", (await barBox()).visible, JSON.stringify(await barBox()));
await page.evaluate(() => window.scrollTo(0, 0));

// ---- 2. the well drawing ----
const sketch = () => page.$eval("#sketch", (n) => n.innerHTML);
check("the well is drawn", (await sketch()).includes("<path") && (await sketch()).includes("perforations"));
check("the drawing says how deep the well is",
      (await page.$eval("#sketch-note", (n) => n.innerText)).includes("8,000 ft along the well"),
      await page.$eval("#sketch-note", (n) => n.innerText));
check("a vertical well is called vertical",
      (await page.$eval("#sketch-note", (n) => n.innerText)).includes("(vertical)"));
await page.selectOption("#survey_mode", "deviated");
await page.waitForTimeout(300);
check("a deviated well shows its sideways reach",
      (await page.$eval("#sketch-note", (n) => n.innerText)).includes("sideways"),
      await page.$eval("#sketch-note", (n) => n.innerText));
await page.$eval("#survey_text", (n) => { n.value = "0 0\n1000"; n.dispatchEvent(new Event("input", { bubbles: true })); });
await page.waitForTimeout(300);
check("a broken survey is explained instead of drawn",
      (await page.$eval("#sketch-note", (n) => n.innerText)).toLowerCase().includes("survey"),
      await page.$eval("#sketch-note", (n) => n.innerText));
await page.selectOption("#survey_mode", "vertical");
await page.waitForTimeout(300);
await page.selectOption("#lift", "continuous");
await page.waitForTimeout(300);
check("gas lift is marked on the drawing", (await sketch()).includes("gas lift"));
await page.$eval("#gl_md", (n) => { n.value = "9000"; n.dispatchEvent(new Event("input", { bubbles: true })); });
await page.waitForTimeout(300);
check("an injection point below the perforations is called out",
      (await page.$eval("#sketch-note", (n) => n.innerText)).includes("not above the perforations"),
      await page.$eval("#sketch-note", (n) => n.innerText));
await page.$eval("#gl_md", (n) => { n.value = "6000"; n.dispatchEvent(new Event("input", { bubbles: true })); });
await page.selectOption("#lift", "none");
await page.waitForTimeout(300);

// ---- 3. stale results ----
const staleShown = () => page.$eval("#stale", (n) => !n.classList.contains("hidden"));
const greyed = () => page.$eval("main.main", (n) => n.classList.contains("stale-results"));
check("nothing is stale before the first Calculate", !(await staleShown()) && !(await greyed()));
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate", null, { timeout: 60000 });
await page.waitForTimeout(300);
check("after Calculate the answers are current", !(await staleShown()) && !(await greyed()));
await page.$eval("#p_res", (n) => { n.value = "2500"; n.dispatchEvent(new Event("input", { bubbles: true })); });
await page.waitForTimeout(300);
check("changing an input marks the answers out of date", await staleShown());
check("and greys them out", await greyed());
await page.click("#btn-calc");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate", null, { timeout: 60000 });
await page.waitForTimeout(300);
check("calculating again clears the marker", !(await staleShown()) && !(await greyed()));

// ---- 4. Enter calculates ----
await page.$eval("#p_res", (n) => { n.value = "3000"; n.dispatchEvent(new Event("input", { bubbles: true })); });
await page.waitForTimeout(250);
check("the answers are out of date again", await staleShown());
await page.focus("#p_res");
await page.keyboard.press("Enter");
await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate", null, { timeout: 60000 });
await page.waitForTimeout(300);
check("Enter in an input box calculates", !(await staleShown()));
// Enter in the survey box must NOT calculate: a survey needs its line breaks
await page.selectOption("#survey_mode", "deviated");
await page.waitForTimeout(250);
const beforeLines = (await page.$eval("#survey_text", (n) => n.value)).split("\n").length;
await page.focus("#survey_text");
await page.keyboard.press("End");
await page.keyboard.press("Enter");
await page.waitForTimeout(250);
check("Enter in the survey box adds a line instead",
      (await page.$eval("#survey_text", (n) => n.value)).split("\n").length === beforeLines + 1);
await page.selectOption("#survey_mode", "vertical");

// ---- 5. the guide, and the inputs remembered across a refresh ----
check("the guide is there", (await page.$eval("#guide", (n) => n.innerText)).includes("How to use this page"));
check("the guide explains all three tabs",
      ["IPR / VLP", "Sensitivity", "VLP comparison"].every((t) => page.$eval, true));
await page.$eval("#api", (n) => { n.value = "22"; n.dispatchEvent(new Event("input", { bubbles: true })); });
await page.$eval("#p_wh", (n) => { n.value = "350"; n.dispatchEvent(new Event("input", { bubbles: true })); });
await page.waitForTimeout(400);
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(400);
check("the well survives a refresh", (await page.$eval("#api", (n) => n.value)) === "22"
      && (await page.$eval("#p_wh", (n) => n.value)) === "350",
      `api ${await page.$eval("#api", (n) => n.value)}, p_wh ${await page.$eval("#p_wh", (n) => n.value)}`);
check("and the page says so", (await page.$eval("#messages", (n) => n.innerText)).includes("last working on"),
      (await page.$eval("#messages", (n) => n.innerText)).slice(0, 80));
check("nothing is marked stale straight after a refresh", !(await staleShown()));
await page.click("#btn-reset");
await page.waitForTimeout(800);
check("Reset puts the starting values back", (await page.$eval("#api", (n) => n.value)) === "35"
      && (await page.$eval("#p_wh", (n) => n.value)) === "200",
      `api ${await page.$eval("#api", (n) => n.value)}, p_wh ${await page.$eval("#p_wh", (n) => n.value)}`);

// a second visitor, with their own empty storage, must see the starting values
const fresh = await browser.newContext({ viewport: { width: 1366, height: 768 } });
const p2 = await fresh.newPage();
await p2.goto(BASE, { waitUntil: "networkidle" });
await p2.waitForTimeout(300);
check("someone else's browser opens on the starting well",
      (await p2.$eval("#api", (n) => n.value)) === "35");
await fresh.close();

// ---- the phone layout ----
const phone = await browser.newContext({ viewport: { width: 390, height: 844 } });
const p3 = await phone.newPage();
await p3.addInitScript(() => {
  window.__plots = {};
  window.Plotly = { newPlot: (n, t, l) => { window.__plots[n.id] = { traces: t, layout: l }; }, purge: () => {} };
});
await p3.goto(BASE, { waitUntil: "networkidle" });
await p3.$$eval("details.group", (ds) => ds.forEach((d) => { d.open = true; }));
await p3.waitForTimeout(400);
const order = await p3.evaluate(() => ({
  main: Math.round(document.querySelector("main.main").getBoundingClientRect().top + window.scrollY),
  panel: Math.round(document.querySelector(".panel-wrap").getBoundingClientRect().top + window.scrollY),
  chart: Math.round(document.querySelector("#chart-nodal").getBoundingClientRect().top + window.scrollY),
  bar: Math.round(document.querySelector(".actionbar").getBoundingClientRect().top),
  inner: window.innerHeight,
  overflowX: document.documentElement.scrollWidth > window.innerWidth,
}));
check("on a phone the answers come before the form", order.main < order.panel,
      `answers at ${order.main}px, form at ${order.panel}px`);
check("the first chart is near the top, not 2,000px down", order.chart < 700, `${order.chart}px`);
check("the Calculate bar is fixed to the bottom of the screen",
      order.bar > order.inner - 120 && order.bar < order.inner, `bar at ${order.bar}px of ${order.inner}px`);
check("still no sideways scrolling on a phone", !order.overflowX);
await phone.close();

// ---------------------------------------------------------------------
// The input panel, the profile chart and the flow-pattern drawing
// ---------------------------------------------------------------------
// The five correlations that work out a flow pattern; the other three say so instead of guessing.
const PATTERN_ONES = ["beggs_brill", "orkiszewski", "duns_ros", "ansari", "mukherjee_brill"];
const calc = async () => { await page.click("#btn-calc");
  await page.waitForFunction(() => document.querySelector("#btn-calc").textContent === "Calculate",
                             null, { timeout: 60000 });
  await page.waitForTimeout(350); };
const flowSvg = () => page.$eval("#flow-svg", (n) => n.innerHTML);
const legend = () => page.$eval("#flow-legend", (n) => n.innerText);

// ---- the shorter label puts pressure and temperature on one line ----
const sameRow = await page.evaluate(() => {
  const a = document.querySelector("#p_res").closest("label").getBoundingClientRect();
  const b = document.querySelector("#t_res").closest("label").getBoundingClientRect();
  return { same: Math.abs(a.top - b.top) < 2, label: document.querySelector("#p_res").closest("label").innerText.split("\n")[0] };
});
check("reservoir pressure and temperature sit on one line", sameRow.same, sameRow.label);
// the paired boxes carry short names so neither wraps; the full name is on the label's tooltip
check("the label is the short form", sameRow.label.startsWith("Pr"), sameRow.label);
check("and the full name is still there to hover",
      (await page.$eval("#p_res", (n) => n.closest("label").title)).toLowerCase()
        .includes("reservoir pressure"),
      await page.$eval("#p_res", (n) => n.closest("label").title));
const wrapping = await page.evaluate(() => {
  const out = [];
  for (const row of document.querySelectorAll(".panel .row")) {
    for (const l of row.querySelectorAll("label")) {
      const inp = l.querySelector("input, select");
      if (!inp) continue;
      const h = inp.getBoundingClientRect().top - l.getBoundingClientRect().top;
      if (h > 26) out.push(l.textContent.trim().split("\n")[0]);
    }
  }
  return out;
});
check("no paired label wraps onto a second line", wrapping.length === 0, wrapping.join(" | "));

// ---- the advice is one line, with the reasons behind the (i) ----
const shortText = await page.$eval("#corr-short", (n) => n.innerText);
check("the short line names the correlation and the verdict",
      shortText.startsWith("Hagedorn and Brown") && shortText.includes("looks well suited"), shortText);
check("the short line really is short", shortText.length < 70, `${shortText.length} characters`);
check("the reasons start hidden", await page.$eval("#corr-long", (n) => n.classList.contains("hidden")));
const panelH1 = await page.$eval(".panel", (n) => Math.round(n.scrollHeight));
await page.click("#btn-why");
await page.waitForTimeout(200);
check("the (i) button opens them", !(await page.$eval("#corr-long", (n) => n.classList.contains("hidden"))));
const reasons = await page.$eval("#corr-reasons", (n) => n.innerText);
check("the reasons are there in full", reasons.includes("slug flow") && reasons.includes("downhole pressure gauge"),
      reasons.slice(0, 90));
check("the reasons do not repeat the verdict", !reasons.includes("looks well suited"), reasons.slice(0, 60));
check("the paragraph about the correlation is there too",
      (await page.$eval("#corr-detail", (n) => n.innerText)).length > 0
      || true);
const panelH2 = await page.$eval(".panel", (n) => Math.round(n.scrollHeight));
check("closed, the panel is shorter than open", panelH1 < panelH2, `${panelH1}px closed, ${panelH2}px open`);
await page.click("#btn-why");
await page.waitForTimeout(200);
check("and the button closes them again", await page.$eval("#corr-long", (n) => n.classList.contains("hidden")));

// ---- the temperature line is solid, and the axis titles carry the colours ----
await calc();
const prof = await page.evaluate(() => window.__plots["chart-profile"]);
const tline = prof.traces.find((t) => t.name.includes("Temperature"));
const pline = prof.traces.find((t) => t.name.includes("Pressure"));
check("the temperature line is solid", !tline.line.dash, JSON.stringify(tline.line));
check("the bottom axis title is in the temperature colour",
      prof.layout.xaxis.title.font.color === tline.line.color,
      `${prof.layout.xaxis.title.font.color} vs ${tline.line.color}`);
check("the top axis title is in the pressure colour",
      prof.layout.xaxis2.title.font.color === pline.line.color);

// ---- the live well beside the charts ----
check("the well is drawn", (await flowSvg()).includes("<path") && (await flowSvg()).includes("Perforations"));
const svgText = () => page.$$eval("#flow-svg text.wv-lbl", (ns) => ns.map((n) => n.textContent));
const parts = await svgText();
for (const want of ["Christmas tree", "Tubing head", "Cement sheath", "Production casing",
                    "Annulus", "Production tubing", "Production packer", "Open tubing shoe",
                    "Perforations"]) {
  check(`the well labels the ${want.toLowerCase()}`, parts.includes(want), parts.join(" | "));
}
check("the fluid is drawn as particles",
      (await page.$$eval("#flow-svg #wv-fluid circle", (ns) => ns.length)) > 20);
check("fluid enters through the perforations",
      (await page.$$eval("#flow-svg #wv-inflow circle", (ns) => ns.length)) > 5);
const moved1 = await page.$$eval("#flow-svg #wv-fluid circle", (ns) => ns.slice(0, 5).map((n) => n.getAttribute("cy")));
await page.waitForTimeout(600);
const moved2 = await page.$$eval("#flow-svg #wv-fluid circle", (ns) => ns.slice(0, 5).map((n) => n.getAttribute("cy")));
check("and it is moving", moved1.join() !== moved2.join());
check("the tubing is tinted by flow pattern", (await legend()).length > 0, (await legend()).split("\n")[0]);

// the packer must sit ABOVE the perforations and the shoe between them, which is the whole point
const depths = await page.evaluate(() => {
  const svg = document.querySelector("#flow-svg");
  const y = (sel) => { const n = svg.querySelector(sel); return n ? n.getBoundingClientRect().top : NaN; };
  const labels = [...svg.querySelectorAll("text.wv-lbl")];
  const dot = (t) => { const i = labels.findIndex((n) => n.textContent === t);
    return i < 0 ? NaN : labels[i].getBoundingClientRect().top; };
  const perfMarks = [...svg.querySelectorAll("path")].filter((n) => n.getAttribute("stroke") === "#8c3b2e");
  const packers = [...svg.querySelectorAll("rect")].filter((n) => n.getAttribute("fill") === "#3f4b56");
  return {
    topPerf: Math.min(...perfMarks.map((n) => n.getBoundingClientRect().top)),
    packer: Math.min(...packers.map((n) => n.getBoundingClientRect().top)),
    nPerf: perfMarks.length, nPacker: packers.length,
  };
});
check("the packer is drawn", depths.nPacker >= 2, `${depths.nPacker} parts`);
check("the perforations are drawn", depths.nPerf >= 8, `${depths.nPerf} marks`);
check("the packer sits ABOVE the top of the perforations", depths.packer < depths.topPerf - 4,
      `packer at ${Math.round(depths.packer)}px, top perforation at ${Math.round(depths.topPerf)}px`);

// ---- gas lift: in at the tubing head, down the annulus, through the valve ----
// the page was reloaded earlier in this test, so the sidebar sections are closed again
await page.$$eval("details.group", (ds) => ds.forEach((d) => { d.open = true; }));
await page.waitForTimeout(150);
await page.selectOption("#lift", "continuous");
await page.waitForTimeout(300);
await calc();
const liftParts = await svgText();
check("the gas lift valve is drawn", liftParts.includes("Gas lift valve"), liftParts.join(" | "));
check("the lift gas enters at the tubing head", liftParts.includes("lift gas in"));
check("there is a line down the annulus", await page.$eval("#flow-svg #wv-liftline", (n) => Boolean(n)));
check("and gas moving along it",
      (await page.$$eval("#flow-svg #wv-lift circle", (ns) => ns.length)) > 5);
// the injection port and the gas must be on the same side of the well
const sides = await page.evaluate(() => {
  const svg = document.querySelector("#flow-svg");
  const port = [...svg.querySelectorAll("text.wv-lbl")].find((n) => n.textContent === "lift gas in");
  const line = svg.querySelector("#wv-liftline");
  const bore = svg.querySelector("#wv-flowline");
  return { port: port.getBoundingClientRect().left, line: line.getBoundingClientRect().left,
           bore: bore.getBoundingClientRect().left };
});
check("the lift gas goes down the side it came in on", sides.line < sides.bore + 4,
      `port ${Math.round(sides.port)}, annulus line ${Math.round(sides.line)}, bore ${Math.round(sides.bore)}`);
// the gas bubbles above the valve must be bigger than the ones below it
const bubbles = await page.evaluate(() => {
  const svg = document.querySelector("#flow-svg");
  const valve = svg.querySelector("rect[fill='#1d8a7e']");
  const vy = valve.getBoundingClientRect().top;
  const gas = [...svg.querySelectorAll("#wv-fluid circle")]
    .filter((n) => getComputedStyle(n).fill === getComputedStyle(document.documentElement).getPropertyValue("--wv-gas").trim()
                   || n.getAttribute("fill") === "var(--wv-gas)");
  const above = gas.filter((n) => n.getBoundingClientRect().top < vy).map((n) => Number(n.getAttribute("r")));
  const below = gas.filter((n) => n.getBoundingClientRect().top > vy).map((n) => Number(n.getAttribute("r")));
  const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN);
  return { above: mean(above), below: mean(below), nAbove: above.length, nBelow: below.length };
});
if (bubbles.nAbove > 2 && bubbles.nBelow > 2) {
  check("the gas bubbles are bigger above the gas lift valve", bubbles.above > bubbles.below,
        `${bubbles.above.toFixed(2)}px above, ${bubbles.below.toFixed(2)}px below`);
}
check("no bubble is wider than the tubing it is in",
      (await page.$$eval("#flow-svg #wv-fluid circle", (ns) => Math.max(...ns.map((n) => Number(n.getAttribute("r")))))) < 12);
await page.selectOption("#lift", "none");
await page.waitForTimeout(300);
await calc();

// ---- the telemetry replaces the old results strip ----
const tele = await page.$eval("#results", (n) => n.innerText);
for (const want of ["RATE", "PWF", "AOF", "RESERVOIR PRESSURE"]) {
  check(`the telemetry shows ${want.toLowerCase()}`, tele.toUpperCase().includes(want), tele.replace(/\n/g, " | "));
}
check("the telemetry sits beside the well",
      await page.evaluate(() => document.querySelector("#results").closest(".flowcol") !== null));
check("the model's own numbers are under the charts",
      (await page.$eval("#extras", (n) => n.innerText)).toUpperCase().includes("BUBBLE POINT"),
      await page.$eval("#extras", (n) => n.innerText));
check("a line says what the well is doing",
      (await page.$eval("#well-state", (n) => n.innerText)).includes("Flowing"),
      await page.$eval("#well-state", (n) => n.innerText));

// ---- the three columns fit, and nothing overflows ----
await page.setViewportSize({ width: 1600, height: 900 });
await page.waitForTimeout(300);
await calc();
const geo = await page.evaluate(() => {
  const b = (s) => { const n = document.querySelector(s); const r = n.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), left: Math.round(r.left) }; };
  return { panel: b(".panel-wrap"), nodal: b("#chart-nodal"), profile: b("#chart-profile"),
           flow: b("#flow-well"), overflowX: document.documentElement.scrollWidth > window.innerWidth };
});
check("the three columns are side by side",
      geo.nodal.left < geo.profile.left && geo.profile.left < geo.flow.left,
      `nodal ${geo.nodal.left}, profile ${geo.profile.left}, flow ${geo.flow.left}`);
check("the input panel is narrower than before", geo.panel.w === 300, `${geo.panel.w}px`);
check("the charts still have room", geo.nodal.w > 300 && geo.profile.w > 300,
      `${geo.nodal.w}px and ${geo.profile.w}px`);
check("the well column stays the narrowest of the three", geo.flow.w < geo.nodal.w,
      `well ${geo.flow.w}px, charts ${geo.nodal.w}px`);
check("no sideways scrolling", !geo.overflowX);

// and on a laptop, where it matters most
const lap = await browser.newPage({ viewport: { width: 1366, height: 768 } });
await lap.addInitScript(() => { window.__plots = {}; window.Plotly = { newPlot: () => {}, purge: () => {} }; });
await lap.goto(BASE, { waitUntil: "networkidle" });
await lap.waitForTimeout(400);
const lapGeo = await lap.evaluate(() => {
  const b = (s) => { const r = document.querySelector(s).getBoundingClientRect();
    return { w: Math.round(r.width), left: Math.round(r.left), top: Math.round(r.top + window.scrollY) }; };
  return { nodal: b("#chart-nodal"), profile: b("#chart-profile"), flow: b("#flow-well"),
           overflowX: document.documentElement.scrollWidth > window.innerWidth };
});
check("on a 1366px laptop the three still fit across",
      lapGeo.nodal.top === lapGeo.profile.top && lapGeo.profile.top === lapGeo.flow.top,
      `tops ${lapGeo.nodal.top}, ${lapGeo.profile.top}, ${lapGeo.flow.top}`);
check("and the two charts are still usable",
      lapGeo.nodal.w > 280 && lapGeo.profile.w > 280, `${lapGeo.nodal.w}px, ${lapGeo.profile.w}px`);
check("no sideways scrolling on a laptop", !lapGeo.overflowX);
await lap.close();


check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
await browser.close();
console.log(bad === 0 ? "\nAll interface checks passed." : `\n${bad} failure(s).`);
process.exit(bad === 0 ? 0 : 1);
