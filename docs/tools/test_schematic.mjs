// The wellbore schematic page: that it draws the well, animates the fluid, and that the telemetry
// answers the controls the way the physics says it must.  The numbers come from the same engine as
// the rest of the app, so they can be checked against each other rather than just for being present.
//
// To run it:
//   python3 -m http.server 8765        (in the docs folder, in another window)
//   node tools/test_schematic.mjs

import { chromium } from "playwright";

const BASE = (process.env.PAGE_URL || "http://127.0.0.1:8765/") + "schematic.html";
let bad = 0;
const check = (what, ok, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"}  ${what}${detail ? "  " + detail : ""}`);
  if (!ok) bad += 1;
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForTimeout(900);

const number = async (id) => Number((await page.$eval(`#${id}`, (n) => n.innerText))
  .replace(/[^\d.-]/g, ""));
const state = () => page.$eval("#state", (n) => n.innerText);
const setRange = async (id, v) => {
  await page.$eval(`#${id}`, (n, v) => { n.value = v; n.dispatchEvent(new Event("input", { bubbles: true })); }, v);
  await page.waitForTimeout(450);
};
const setNum = setRange;
const toggle = async (id) => { await page.click(`#${id}`); await page.waitForTimeout(450); };

// ---- 1. the drawing has every part the schematic is meant to show ----
const labels = await page.$$eval("#well text.lbl", (ns) => ns.map((n) => n.textContent));
for (const want of ["Christmas tree", "Master valve", "Wing valve and choke", "Production casing",
                    "Cement sheath", "Production tubing", "Production packer", "Perforations",
                    "Casing-tubing annulus"]) {
  check(`the drawing labels the ${want.toLowerCase()}`, labels.includes(want), labels.join(" | "));
}
const depths = await page.$$eval("#well text.depth", (ns) => ns.map((n) => n.textContent));
check("the depth scale runs from 0 to the perforations",
      depths.includes("0") && depths.includes("10,000"), depths.join(" "));
check("the perforations are drawn as arrows through the casing",
      (await page.$$eval("#well path", (ns) => ns.length)) > 10);

// ---- 2. the fluid moves, in three phases ----
const colours = await page.$$eval("#fluid circle", (ns) => [...new Set(ns.map((n) => n.getAttribute("fill")))]);
check("oil, gas and water are all drawn", colours.length === 3, colours.join(","));
check("there is a stream of particles",
      (await page.$$eval("#fluid circle", (ns) => ns.length)) > 20);
const before = await page.$$eval("#fluid circle", (ns) => ns.slice(0, 5).map((n) => n.getAttribute("cy")));
await page.waitForTimeout(600);
const after = await page.$$eval("#fluid circle", (ns) => ns.slice(0, 5).map((n) => n.getAttribute("cy")));
check("the fluid is moving", before.join() !== after.join());
const dashBefore = await page.$eval("#flowline", (n) => n.getAttribute("stroke-dashoffset"));
await page.waitForTimeout(400);
check("the flow line is a moving dashed line",
      (await page.$eval("#flowline", (n) => n.getAttribute("stroke-dashoffset"))) !== dashBefore);

// ---- 3. the telemetry is real, and answers the choke the way it must ----
const q60 = await number("t-q");
const bhp60 = await number("t-bhp");
const whp60 = await number("t-whp");
check("a rate comes out", q60 > 0, `${q60} bbl/d`);
check("the bottomhole pressure is below the reservoir pressure", bhp60 < 4000 && bhp60 > 0,
      `${bhp60} psig`);
check("the wellhead pressure is well below the bottomhole pressure", whp60 < bhp60, `${whp60} psig`);
// PI = 4 bbl/d/psi, so the rate must equal 4 x the drawdown - the readouts have to agree with
// each other, not merely look plausible
check("the rate matches the productivity index times the drawdown",
      Math.abs(q60 - 4 * (4000 - bhp60)) / q60 < 0.02,
      `${q60} vs ${(4 * (4000 - bhp60)).toFixed(0)}`);
check("the oil rate is the liquid rate less the water",
      Math.abs((await number("t-qo")) - q60 * 0.75) / q60 < 0.02);
check("the gas rate is the oil rate times the GOR",
      Math.abs((await number("t-qg")) - (await number("t-qo")) * 0.5) / (await number("t-qg")) < 0.02);

await setRange("choke", "100");
const q100 = await number("t-q");
check("opening the choke raises the rate", q100 > q60, `${q100} vs ${q60} bbl/d`);
check("and lowers the wellhead pressure", (await number("t-whp")) < whp60,
      `${await number("t-whp")} vs ${whp60} psig`);
await setRange("choke", "20");
const q20 = await number("t-q");
check("closing it towards shut lowers the rate", q20 < q60, `${q20} vs ${q60} bbl/d`);
check("and raises the wellhead pressure", (await number("t-whp")) > whp60);
await setRange("choke", "0");
check("a shut choke stops the flow", (await number("t-q")) === 0, `${await number("t-q")}`);
check("and says so", (await state()).toLowerCase().includes("closed"), await state());
await setRange("choke", "60");

// ---- 4. the master valve ----
await toggle("master");
check("closing the master valve stops the flow", (await number("t-q")) === 0);
check("the bottomhole pressure builds back up to the reservoir pressure",
      Math.abs((await number("t-bhp")) - 4000) < 1, `${await number("t-bhp")} psig`);
check("the page says the well is shut in", (await state()).includes("shut in"), await state());
check("the drawing shows the pressure building under the valve",
      (await page.$eval("#shutnote", (n) => n.getAttribute("opacity"))) === "1");
check("the master valve is drawn closed",
      (await page.$eval("#v-master .vstate", (n) => n.getAttribute("fill"))).includes("shut"));
const stoppedA = await page.$$eval("#fluid circle", (ns) => ns.slice(0, 5).map((n) => n.getAttribute("cy")));
await page.waitForTimeout(600);
const stoppedB = await page.$$eval("#fluid circle", (ns) => ns.slice(0, 5).map((n) => n.getAttribute("cy")));
check("and the fluid has stopped moving", stoppedA.join() === stoppedB.join());
await toggle("master");
check("opening it again starts the flow", (await number("t-q")) > 0);
check("the master valve is drawn open",
      (await page.$eval("#v-master .vstate", (n) => n.getAttribute("fill"))).includes("open"));

// ---- 5. gas lift ----
check("the gas lift sliders start greyed out",
      await page.$eval("#lift-controls", (n) => n.classList.contains("disabled")));
check("no gas lift valve is drawn yet",
      !(await page.$$eval("#well text.lbl", (ns) => ns.map((n) => n.textContent)))
        .includes("Gas lift valve"));
const qNatural = await number("t-q");
await toggle("lift");
check("the sliders come alive", !(await page.$eval("#lift-controls", (n) => n.classList.contains("disabled"))));
check("the gas lift valve appears on the tubing",
      (await page.$$eval("#well text.lbl", (ns) => ns.map((n) => n.textContent)))
        .includes("Gas lift valve"));
const qLift = await number("t-q");
check("gas lift raises the rate", qLift > qNatural, `${qLift} with lift vs ${qNatural} without`);
check("and the page says what it is doing",
      (await state()).includes("gas lift") && (await state()).includes("lightens"), await state());
const liftMoving1 = await page.$$eval("#liftfluid circle", (ns) => ns.slice(0, 3).map((n) => n.getAttribute("cy")));
await page.waitForTimeout(600);
const liftMoving2 = await page.$$eval("#liftfluid circle", (ns) => ns.slice(0, 3).map((n) => n.getAttribute("cy")));
check("the injection gas is animated down the annulus", liftMoving1.join() !== liftMoving2.join());
check("the injection line is visible",
      Number(await page.$eval("#liftline", (n) => n.getAttribute("opacity"))) > 0.2);
await setRange("glr", "3000");
check("more injection gas changes the rate again", (await number("t-q")) !== qLift,
      `${await number("t-q")} vs ${qLift} bbl/d`);
await setRange("gld", "3000");
check("the valve depth can be moved", (await number("t-q")) > 0);
await toggle("lift");
check("turning gas lift off hides the valve again",
      !(await page.$$eval("#well text.lbl", (ns) => ns.map((n) => n.textContent)))
        .includes("Gas lift valve"));

// ---- 6. the well inputs redraw the picture ----
await setNum("depth", "6000");
const d6 = await page.$$eval("#well text.depth", (ns) => ns.map((n) => n.textContent));
check("a shallower well redraws the depth scale", d6.includes("6,000") && !d6.includes("10,000"),
      d6.join(" "));
check("and it flows at a different rate", (await number("t-q")) > 0);
await setNum("depth", "10000");
await setNum("tubing_id", "4.5");
check("a bigger tubing flows more", (await number("t-q")) > q60, `${await number("t-q")} vs ${q60}`);
await setNum("tubing_id", "2.992");

// ---- 7. a well that cannot flow must say so rather than draw a lie ----
await setNum("p_res", "800");
check("a weak reservoir is reported as not flowing", (await number("t-q")) === 0,
      `${await number("t-q")} bbl/d`);
check("with a reason", (await state()).length > 20, await state());
await setNum("p_res", "4000");
check("and it recovers", (await number("t-q")) > 0);

check("no page errors at all", errors.length === 0, errors.slice(0, 3).join(" | "));
await browser.close();
console.log(bad === 0 ? "\nAll schematic checks passed." : `\n${bad} failure(s).`);
process.exit(bad === 0 ? 0 : 1);
