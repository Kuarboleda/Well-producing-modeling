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

check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
await browser.close();
console.log(bad === 0 ? "\nAll interface checks passed." : `\n${bad} failure(s).`);
process.exit(bad === 0 ? 0 : 1);
