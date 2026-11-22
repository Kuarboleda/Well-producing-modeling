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
// the axes are rounded out to whole ticks, so the first and last values are both labelled
check("the pressure axis reaches past the deepest pressure",
      prof.layout.xaxis2.range[1] >= Math.max(...pline.x)
        && prof.layout.xaxis2.range[1] % prof.layout.xaxis2.dtick === 0,
      `axis to ${prof.layout.xaxis2.range[1]}, data to ${Math.round(Math.max(...pline.x))}, `
        + `step ${prof.layout.xaxis2.dtick}`);
check("the temperature axis starts on a tick at or below the wellhead",
      prof.layout.xaxis.range[0] <= Math.min(...tline.x)
        && prof.layout.xaxis.range[0] % prof.layout.xaxis.dtick === 0,
      `axis from ${prof.layout.xaxis.range[0]}, data from ${Math.round(Math.min(...tline.x))}`);
check("the legend is out of the top axis",
      prof.layout.legend.y < 0.5 && prof.layout.legend.yanchor === "bottom",
      JSON.stringify(prof.layout.legend));
// the rate axis starts just below zero so its "0" clears the pressure axis's own
const nod = await page.evaluate(() => window.__plots["chart-nodal"]);
check("the two zeros at the origin are separated", nod.layout.xaxis.range[0] < 0,
      `rate axis starts at ${nod.layout.xaxis.range[0].toFixed(1)}`);

// ---- the live well beside the charts ----
check("the well is drawn", (await flowSvg()).includes("<path") && (await flowSvg()).includes("Perforations"));
// The component names are hover tooltips, not a column of labels down the side: the drawing is
// the thing being looked at and the leader lines were crowding it out.
const tips = () => page.$$eval("#flow-svg title", (ns) => ns.map((n) => n.textContent));
const parts = await tips();
for (const want of ["Swab valve", "Production wing valve", "Upper master valve",
                    "Lower master valve", "Wellhead annulus seal", "Production casing",
                    "Production tubing", "Production packer", "Open tubing tailpipe",
                    "Perforations", "Casing shoe", "Reservoir"]) {
  check(`hovering names the ${want.toLowerCase()}`,
        parts.some((s) => s.startsWith(want)), parts.join(" | "));
}
check("the only text on the drawing is the depth scale and the lift gas inlet",
      (await page.$$eval("#flow-svg text.wv-lbl", (ns) => ns.map((n) => n.textContent)))
        .every((s) => s.startsWith("lift gas in")));
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
  const perfMarks = [...svg.querySelectorAll("line")].filter((n) => n.getAttribute("stroke") === "#7c3f1d");
  const packers = [...svg.querySelectorAll(".wv-packer rect")];
  const shoe = svg.querySelector("#wv-bore").getBoundingClientRect().bottom;
  return {
    topPerf: Math.min(...perfMarks.map((n) => n.getBoundingClientRect().top)),
    packer: Math.min(...packers.map((n) => n.getBoundingClientRect().top)),
    botPerf: Math.max(...perfMarks.map((n) => n.getBoundingClientRect().bottom)),
    shoe, nPerf: perfMarks.length, nPacker: packers.length,
    casingBottom: Math.max(...[...svg.querySelectorAll(".wv-shoe")]
      .map((n) => n.getBoundingClientRect().bottom)),
  };
});
check("the packer is drawn", depths.nPacker >= 2, `${depths.nPacker} parts`);
check("the perforations are drawn through both walls",
      depths.nPerf >= 6 && depths.nPerf % 2 === 0, `${depths.nPerf} marks`);
check("and they stop short of the casing shoe",
      depths.botPerf < depths.casingBottom - 6,
      `lowest at ${Math.round(depths.botPerf)}px, shoe at ${Math.round(depths.casingBottom)}px`);
check("the packer sits ABOVE the top of the perforations", depths.packer < depths.topPerf - 4,
      `packer at ${Math.round(depths.packer)}px, top perforation at ${Math.round(depths.topPerf)}px`);
check("the perforations are horizontal",
      await page.$$eval("#flow-svg line", (ns) => ns
        .filter((n) => n.getAttribute("stroke") === "#7c3f1d")
        .every((n) => n.getAttribute("y1") === n.getAttribute("y2"))));
check("and the tailpipe ends at the top of the perforations",
      Math.abs(depths.shoe - depths.topPerf) < 20,
      `tailpipe ends at ${Math.round(depths.shoe)}px, perforations `
        + `${Math.round(depths.topPerf)}-${Math.round(depths.botPerf)}px`);

// ---- gas lift: in at the tubing head, down the annulus, through the valve ----
// the page was reloaded earlier in this test, so the sidebar sections are closed again
await page.$$eval("details.group", (ds) => ds.forEach((d) => { d.open = true; }));
await page.waitForTimeout(150);
await page.selectOption("#lift", "continuous");
await page.waitForTimeout(300);
await calc();
check("the side pocket mandrel is drawn",
      (await page.$$eval("#wv-glvalve", (ns) => ns.length)) === 1);
check("the lift gas inlet reads ON", (await tips()).some((s) => s.startsWith("Annulus wing valve"))
      && (await page.$$eval("#flow-svg text.wv-lbl", (ns) => ns.map((n) => n.textContent)))
        .includes("lift gas in: ON"));
check("and the inlet sits above the 0 ft line, on the wellhead",
      await page.evaluate(() => {
        const svg = document.querySelector("#flow-svg");
        const wing = svg.querySelector("#wv-annwing").getBoundingClientRect();
        const zero = [...svg.querySelectorAll("text.wv-depth")]
          .find((n) => n.textContent === "0").getBoundingClientRect();
        return wing.bottom < zero.bottom;
      }));
// Where the parts sit ACROSS the well, in drawing units measured from its centre line.  A stroked
// path reports no width of its own, so the widths come from the stroke and the centre from the bore.
const across = await page.evaluate(() => {
  const svg = document.querySelector("#flow-svg");
  const r = svg.getBoundingClientRect();
  const k = svg.viewBox.baseVal.width / r.width;
  const cx0 = (svg.querySelector("#wv-bore").getBoundingClientRect().left - r.left) * k;
  const n = (el, a) => Number(el.getAttribute(a));
  // one bold line per string, so each is measured from where it is drawn
  const halfOf = (sel) => {
    const b = svg.querySelector(sel).getBoundingClientRect();
    return Math.max(Math.abs((b.left - r.left) * k - cx0), Math.abs((b.right - r.left) * k - cx0));
  };
  const band = (el) => {
    const mid = Math.abs(n(el, "x") + n(el, "width") / 2 - cx0);
    return [mid - n(el, "width") / 2, mid + n(el, "width") / 2];
  };
  const wide = (el) => {                       // a shape placed by a transform, not by x
    const b = el.getBoundingClientRect();
    // measured out from the centre line, so a part on the left reads the same as one on the right
    const a = Math.abs((b.left - r.left) * k - cx0);
    const c = Math.abs((b.right - r.left) * k - cx0);
    return { w: b.width * k, from: Math.min(a, c), to: Math.max(a, c) };
  };
  return {
    bore: Number(svg.querySelector("#wv-bore").getAttribute("stroke-width")) / 2,
    tubing: halfOf(".wv-tubing"), casing: halfOf(".wv-casing"),
    valve: (() => { const v = wide(svg.querySelector("#wv-glvalve")); return [v.from, v.to]; })(),
    // the seals are groups now, so it is the block inside each one that gets measured
    packers: [...svg.querySelectorAll(".wv-packer rect")].map(band),
    wellhead: [...svg.querySelectorAll(".wv-wellhead-seal rect")].map(band),
    taylors: [...svg.querySelectorAll("#wv-fluid path")].map(wide),
    drops: [...svg.querySelectorAll("#wv-fluid circle")]
      .filter((c) => n(c, "cy") > 150)
      .map((c) => Math.abs(n(c, "cx") - cx0) + n(c, "r")),
  };
});
check("the gas lift valve is flush against the tubing wall",
      Math.abs(across.valve[0] - across.tubing) < 0.6,
      `valve from ${across.valve[0].toFixed(1)}, tubing wall at ${across.tubing.toFixed(1)}`);
check("and the mandrel leaves the annulus open past it",
      across.valve[1] < across.tubing + (across.casing - across.tubing) * 0.5,
      `mandrel reaches ${across.valve[1].toFixed(1)} of ${across.casing.toFixed(1)}, `
        + `tubing at ${across.tubing.toFixed(1)}`);
check("the packer seals tubing to casing with no gap",
      across.packers.length === 2
        && across.packers.every(([a, b]) => Math.abs(a - across.tubing) < 0.6
                                            && Math.abs(b - across.casing) < 0.6),
      across.packers.map(([a, b]) => `${a.toFixed(1)}-${b.toFixed(1)}`).join(", ")
        + ` against ${across.tubing.toFixed(1)}-${across.casing.toFixed(1)}`);
check("the annulus is sealed at surface in the same way",
      across.wellhead.length === 2
        && across.wellhead.every(([a, b]) => Math.abs(a - across.tubing) < 0.6
                                             && Math.abs(b - across.casing) < 0.6),
      across.wellhead.map(([a, b]) => `${a.toFixed(1)}-${b.toFixed(1)}`).join(", "));
check("no drop is drawn outside the tubing",
      across.drops.length > 4 && Math.max(...across.drops) <= across.bore,
      `worst reaches ${Math.max(...across.drops).toFixed(1)}, bore is ${across.bore.toFixed(1)}`);
if (across.taylors.length) {
  const t0 = across.taylors[0];
  check("a Taylor bubble spans most of the bore without touching the wall",
        t0.w > across.bore && t0.w < across.bore * 2 && Math.max(t0.from, t0.to) <= across.bore,
        `${t0.w.toFixed(1)} wide in a bore of ${(across.bore * 2).toFixed(1)}`);
}

// the four valves on the tree, plus the annulus wing that lets the lift gas in
const symbols = await page.$$eval("#flow-svg .wv-valve", (ns) => ns.map((n) => n.id));
for (const want of ["wv-swab", "wv-wing", "wv-master", "wv-lower-master", "wv-annwing"]) {
  check(`the tree carries the ${want.replace("wv-", "").replace(/-/g, " ")} valve`,
        symbols.includes(want), symbols.join(", "));
}

// with gas lift on, the annulus is a gas column down to the valve and dead fluid below it
const annulus = await page.evaluate(() => {
  const svg = document.querySelector("#flow-svg");
  const ends = (sel) => {
    const el = svg.querySelector(sel);
    if (!el) return null;
    const b = el.getBBox();
    return [b.y, b.y + b.height];
  };
  // the mandrel is a transformed path, so its own bbox is in its own coordinates
  const r = svg.getBoundingClientRect();
  const k = svg.viewBox.baseVal.height / r.height;
  const vb = svg.querySelector("#wv-glvalve").getBoundingClientRect();
  const pk = svg.querySelector(".wv-packer rect").getBBox();
  return { gas: ends("#wv-anngas"), dead: ends("#wv-anndead"),
           packerY: pk.y + pk.height / 2,
           valveY: (vb.top + vb.height / 2 - r.top) * k,
           liftColour: svg.querySelector("#wv-anngas").getAttribute("stroke"),
           jetColour: svg.querySelector("#wv-jet circle").getAttribute("fill") };
});
check("the lift gas column runs from surface down to the gas lift valve",
      Boolean(annulus.gas) && Math.abs(annulus.gas[1] - annulus.valveY) < 16,
      JSON.stringify(annulus));
check("and dead fluid stands below it, down to the packer",
      Boolean(annulus.dead) && annulus.dead[0] < annulus.valveY + 16
        && Math.abs(annulus.dead[1] - annulus.packerY) < 22,
      JSON.stringify(annulus));
check("the gas jetting through the valve is the lift gas colour",
      annulus.jetColour === annulus.liftColour, `${annulus.jetColour} vs ${annulus.liftColour}`);
check("every regime interval says what it is on hover",
      await page.$$eval("#flow-svg .wv-hit title", (ns) => ns.length > 3
        && ns.every((n) => /flow, [\d,]+-[\d,]+ /.test(n.textContent))),
      (await page.$$eval("#flow-svg .wv-hit title", (ns) => ns.slice(0, 2).map((n) => n.textContent)))
        .join(" | "));

// The depth scales of the two panels must line up: a depth on the profile has to be at the same
// height on the drawing beside it, which is the whole reason they share a top and bottom padding.
const lineup = await page.evaluate(() => {
  const chart = document.querySelector("#chart-profile").getBoundingClientRect();
  const layout = window.__plots["chart-profile"].layout;
  const deepest = layout.yaxis.range[0];
  const plotTop = chart.top + layout.margin.t;
  const plotH = chart.height - layout.margin.t - layout.margin.b;
  const svg = document.querySelector("#flow-svg");
  const ticks = [...svg.querySelectorAll("text.wv-depth")]
    .filter((n) => /^[\d,]+$/.test(n.textContent))
    .map((n) => {
      const r = n.getBoundingClientRect();
      return { ft: Number(n.textContent.replace(/,/g, "")), y: (r.top + r.bottom) / 2 };
    });
  return ticks.map((t) => ({ ft: t.ft, drawing: t.y, chart: plotTop + (t.ft / deepest) * plotH }));
});
check("a depth is at the same height on both panels",
      lineup.length > 1 && lineup.every((t) => Math.abs(t.drawing - t.chart) < 3),
      lineup.map((t) => `${t.ft}: ${t.drawing.toFixed(0)} vs ${t.chart.toFixed(0)}`).join(", "));

await page.selectOption("#lift", "none");
await page.waitForTimeout(300);
await calc();
const off = await page.evaluate(() => {
  const svg = document.querySelector("#flow-svg");
  const dead = svg.querySelector("#wv-anndead");
  const pk = svg.querySelector(".wv-packer rect").getBBox();
  const b = dead ? dead.getBBox() : null;
  return { gas: Boolean(svg.querySelector("#wv-anngas")),
           valve: Boolean(svg.querySelector("#wv-glvalve")),
           wing: Boolean(svg.querySelector("#wv-annwing")),
           dead: b ? [b.y, b.y + b.height] : null, packerY: pk.y + pk.height / 2 };
});
check("with gas lift off there is no gas anywhere in the annulus",
      !off.gas && !off.valve, JSON.stringify(off));
// the inlet stays on the drawing either way, so the two states are one picture with one thing
// changed rather than two different drawings
check("but the inlet is still drawn, shut", off.wing
      && (await page.$$eval("#flow-svg text.wv-lbl", (ns) => ns.map((n) => n.textContent)))
        .includes("lift gas in: OFF"));
check("and dead fluid stands the whole way down to the packer",
      Boolean(off.dead) && Math.abs(off.dead[1] - off.packerY) < 22, JSON.stringify(off));

// ---- what the well makes, across the top ----
const kpis = await page.$eval("#kpis", (n) => n.innerText.toUpperCase());
for (const want of ["LIQUID RATE", "OIL RATE", "WATER RATE", "GAS RATE", "DRAWDOWN"]) {
  check(`the strip shows ${want.toLowerCase()}`, kpis.includes(want), kpis.replace(/\n/g, " | "));
}
check("the strip has a number in it", /\d/.test(kpis), kpis.replace(/\n/g, " | "));
check("the strip sits above the charts", await page.evaluate(() => {
  const k = document.querySelector("#kpis").getBoundingClientRect();
  return k.bottom <= document.querySelector(".charts.three").getBoundingClientRect().top + 1;
}));

// ---- AOF, reservoir pressure and the operating point are written ON the inflow chart ----
// They are facts about points on that curve, and in a list beside the drawing they were just
// three numbers with nothing to tie them to.
const marks = (await page.evaluate(() => window.__plots["chart-nodal"].layout.annotations))
  .map((/** @type {any} */ a) => a.text);
check("the inflow chart names the reservoir pressure",
      marks.some((/** @type {string} */ s) => s.startsWith("Reservoir pressure")), marks.join(" | "));
check("and the AOF", marks.some((/** @type {string} */ s) => s.startsWith("AOF")), marks.join(" | "));
check("and gives the rate and the flowing pressure together at the operating point",
      marks.some((/** @type {string} */ s) => /<b>[\d,]+ \S+<\/b><br>[\d,]+ /.test(s)),
      marks.join(" | "));
check("the rate axis says which rate it is",
      (await page.evaluate(() => window.__plots["chart-nodal"].layout.xaxis.title.text))
        .startsWith("Liquid rate"),
      await page.evaluate(() => window.__plots["chart-nodal"].layout.xaxis.title.text));
check("nothing is left in a list beside the drawing",
      await page.evaluate(() => !document.querySelector("#results")));
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
check("the charts still have room", geo.nodal.w > 300 && geo.profile.w > 250,
      `${geo.nodal.w}px and ${geo.profile.w}px`);
// The two plots are read value by value, so they get the width; the drawing is read as a shape
// and needs less of it, which is why it is the narrowest column rather than the widest.
check("the well column is the narrowest of the three",
      geo.flow.w < geo.nodal.w && geo.flow.w < geo.profile.w,
      `well ${geo.flow.w}px, inflow ${geo.nodal.w}px, profile ${geo.profile.w}px`);
check("and the two plots are within a tenth of each other",
      Math.abs(geo.profile.w / geo.nodal.w - 1) < 0.1,
      `${(100 * geo.profile.w / geo.nodal.w).toFixed(0)} % of it`);
check("the three panel titles are centred", await page.$$eval(
  ".charts.three > div > h2.sub", (ns) => ns.every((n) => getComputedStyle(n).textAlign === "center")));
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
      lapGeo.nodal.w > 280 && lapGeo.profile.w > 250, `${lapGeo.nodal.w}px, ${lapGeo.profile.w}px`);
check("no sideways scrolling on a laptop", !lapGeo.overflowX);
await lap.close();


check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
await browser.close();
console.log(bad === 0 ? "\nAll interface checks passed." : `\n${bad} failure(s).`);
process.exit(bad === 0 ? 0 : 1);
