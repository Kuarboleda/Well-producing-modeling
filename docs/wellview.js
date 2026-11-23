// @ts-check

/**
 * wellview.js - the live wellbore schematic.
 *
 * A clean conceptual completion diagram, drawn from the depths that were entered and animated from
 * the answer the solver found.  There is no stock picture anywhere in it: a schematic that
 * disagreed with the calculation beside it would be worse than no schematic at all.
 *
 * How the well is drawn, whatever its shape
 *     The centre line of the well is built from the survey - the horizontal distance travelled
 *     against the true vertical depth - and everything else is drawn by STROKING that same line at
 *     different widths: the casing widest, then the annulus, the tubing wall and the bore.
 *     Concentric bands come out right for a vertical well and for a deviated one with no offset
 *     arithmetic at all, and the fluid runs along the very same line.  Measured depths above the
 *     wellhead are negative, which carries the tubing straight up through the tree.
 *
 * What the drawing insists on getting right
 *     * The annulus is sealed at surface, and the lift gas enters BELOW that seal through its own
 *       wing valve - which is the only way gas can get into a sealed annulus.
 *     * With gas lift on, the annulus holds a gas column from surface down to the gas lift valve
 *       and dead completion fluid below it, because that is what an unloaded annulus looks like.
 *       With gas lift off the whole annulus is dead fluid.
 *     * The packer sits ABOVE the perforations and seals tubing to casing with no gap; the tailpipe
 *       runs on down past it into the perforated interval.
 *     * Inside the tubing the flow regime is DRAWN, not tinted: dispersed bubbles, Taylor bubbles
 *       with liquid slugs between them, churning pockets, or a gas core inside a liquid film,
 *       whichever the correlation reports at that depth.
 */

const NS = "http://www.w3.org/2000/svg";

/**
 * @param {string} name @param {Record<string, string | number>} attrs @param {string} [text]
 * @returns {any} an SVG element; the callers that measure a path need its path methods
 */
function node(name, attrs = {}, text = "") {
  const n = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  if (text) n.textContent = text;
  return n;
}

/** @param {number} v @param {number} [d] */
const fmt = (v, d = 0) => Number(v).toLocaleString("en-US",
  { minimumFractionDigits: d, maximumFractionDigits: d });

/** @param {number} a @param {number} lo @param {number} hi */
const clamp = (a, lo, hi) => Math.min(Math.max(a, lo), hi);

/** Blend two #rrggbb colours, k = 0 giving the first and k = 1 the second.
 * @param {string} a @param {string} b @param {number} k */
function mix(a, b, k) {
  const part = (/** @type {string} */ c, /** @type {number} */ i) =>
    parseInt(c.slice(1 + i * 2, 3 + i * 2), 16);
  const out = [0, 1, 2].map((i) => Math.round(part(a, i) + (part(b, i) - part(a, i)) * k));
  return `#${out.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

/**
 * One drop of what the well is producing, picked at random: water against oil by the water cut,
 * and gas as well wherever there is free gas to see.  At the perforations there is only when the
 * reservoir itself is below its bubble point, which is what freeGasIn says.  By the time the
 * stream turns out of the tee it has fallen to flowline pressure, so the solution gas has come
 * out of the oil on the way up whatever the reservoir was doing.
 * @param {WellSpec} s @param {boolean} [surface] @returns {string}
 */
function phaseIn(s, surface = false) {
  const share = surface ? clamp(0.12 + s.gor / 20000, 0, 0.45)
    : s.freeGasIn ? clamp(0.08 + s.gor / 16000, 0, 0.35) : 0;
  if (Math.random() < share) return PHASE_COLOURS.gas;
  return Math.random() < clamp(s.water_cut, 0, 1) ? PHASE_COLOURS.water : PHASE_COLOURS.oil;
}

/**
 * @typedef {object} WellSpec
 * @property {number[]} md          survey measured depths, ft, starting at 0
 * @property {number[]} tvd         survey true vertical depths, ft
 * @property {number} tubing_id     tubing inner diameter, inches
 * @property {number} perf_top      top of the perforated interval, ft MD
 * @property {number} packer_md     the packer, ft MD (above perf_top)
 * @property {number} shoe_md       the open end of the tubing, ft MD
 * @property {number|null} gl_md    the gas lift valve, ft MD, or null for none
 * @property {number} water_cut     0 to 1
 * @property {number} gor           producing gas-liquid ratio, scf per STB of liquid
 * @property {boolean} flowing      whether the well is flowing at all
 * @property {number} speed         how fast the fluid should move, pixels per second
 * @property {string} lengthUnit    what to write after a depth
 * @property {(ft: number) => number} toShown  a depth in feet, in the unit shown
 * @property {{md: number[], regime: string[]}|null} pattern  the flow pattern down the tubing
 * @property {boolean} [compact]    leave out the labels, for a narrow column
 * @property {boolean} [tree]       draw the Christmas tree and its valves
 * @property {number} [padTop]      pixels above TVD = 0, to match the chart beside it
 * @property {number} [padBottom]   pixels below the deepest TVD, likewise
 * @property {boolean} [depthAxis]  draw the depth scale down the left; on unless turned off
 * @property {boolean} [freeGasIn]  gas breaks out in the reservoir itself, so it arrives at the
 *                                  perforations as free gas rather than all in solution
 * @property {boolean} [masterOpen] whether the master valves are drawn open
 * @property {boolean} [chokeOpen]  whether the production wing valve is drawn open
 */

import { FLUID_COLORS } from "./colours.js";

// The flow-pattern families.  Each one is DRAWN differently inside the tubing, so these carry the
// name to put in the legend and in the tooltip rather than a colour to tint with.
/** @type {Record<string, {colour: string, label: string}>} */
export const FLOW_FAMILIES = {
  liquid: { colour: "#1f5c8b", label: "Liquid only" },
  bubble: { colour: "#4e9ed4", label: "Bubble" },
  slug: { colour: "#8bc34a", label: "Slug / intermittent" },
  churn: { colour: "#f5a623", label: "Churn / transition" },
  annular: { colour: "#d0686a", label: "Annular / mist" },
  gas: { colour: "#b9b9b9", label: "Gas only" },
  none: { colour: "#ccd5dc", label: "Not identified by this correlation" },
};

/**
 * The fluid colours.
 *
 * Oil is green and water is blue, as they are on every completion diagram.  Gas is red, in three
 * shades that say where it came from: the lift gas going down the annulus and jetting through the
 * valve is the bright one, the solution gas coming up from the reservoir below the valve is the
 * deep one, and above the valve - where the two streams have mixed - it is the one in between.
 * @type {Record<string, string>}
 */
// The produced fluids come straight from the shared palette, so a drop travelling up the drawing
// is the colour its rate is written in at the top of the page.  The two extra entries are the two
// kinds of gas the drawing has to tell apart, which a rate strip never has to: the gas going IN
// through the lift valve, and the formation gas below it that came out of the oil on its own.
export const PHASE_COLOURS = {
  oil: FLUID_COLORS.oil.line,
  water: FLUID_COLORS.water.line,
  gas: FLUID_COLORS.gas.line,   // the mixed stream above the gas lift valve
  liftGas: "#ff6b4a",           // injected
  solutionGas: FLUID_COLORS.gas.text,   // formation gas, below the valve: a shade of the same red
};

const STEEL = "#64748b";
const STEEL_DARK = "#334155";
// A packer is drawn as hatched red the world over, so it stays red; a shade off the gas red,
// because on this page a pure red dot is gas and nothing else.
const SEAL = "#A93226";

/** @type {Record<string, string>} */
export const FLOW_FAMILY_OF = {
  liquid: "liquid", gas: "gas",
  bubble: "bubble", dispersed: "bubble", "dispersed bubble": "bubble",
  slug: "slug", plug: "slug", "slug/churn": "churn", churn: "churn",
  transition: "churn", froth: "churn",
  annular: "annular", mist: "annular", "annular/mist": "annular", "annular mist": "annular",
  stratified: "slug",
  segregated: "annular", intermittent: "slug", distributed: "bubble",
  griffith: "bubble",
  hagedorn: "none", gray: "none", "no-slip": "none",
  "region 1": "bubble", "region 2": "slug", "region 3": "annular",
};

/** The family of one reported pattern name, or "" when it is not one this knows. @param {string} name */
export function flowFamily(name) {
  return FLOW_FAMILY_OF[String(name || "").toLowerCase().trim()] || "";
}
/**
 * Build the drawing inside an <svg> element and return the handle the animation needs.
 * @param {SVGSVGElement} svg @param {WellSpec} spec
 */
export function render(svg, spec) {
  const W = Number(svg.getAttribute("data-w") || 300);
  const H = Number(svg.getAttribute("data-h") || 560);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.textContent = "";

  const compact = Boolean(spec.compact);
  const tree = Boolean(spec.tree);
  const perf_md = spec.md[spec.md.length - 1];

  // ---- the centre line of the well, in drawing coordinates ----
  const reach = [0];
  for (let i = 1; i < spec.md.length; i++) {
    const dmd = spec.md[i] - spec.md[i - 1];
    const dtvd = spec.tvd[i] - spec.tvd[i - 1];
    reach.push(reach[i - 1] + Math.sqrt(Math.max(dmd * dmd - dtvd * dtvd, 0)));
  }
  const maxReach = Math.max(...reach);
  const maxTvd = Math.max(...spec.tvd, 1);

  // The depth scale is shared with the pressure and temperature profile beside it: TVD = 0 sits
  // pad.t pixels below the top of the panel and the deepest point pad.b above the bottom in BOTH,
  // so a depth read off one panel is at the same height on the other.  The page passes the two
  // paddings in, because they are the chart's own top and bottom margins.
  // With no scale down the side there is nothing on the left to make room for but the lift gas
  // line, so that margin goes back to the drawing.
  const depthAxis = spec.depthAxis !== false;
  const pad = { t: spec.padTop ?? (tree ? 200 : 34), b: spec.padBottom ?? 26,
                l: !depthAxis ? 12 : compact ? 40 : 60, r: compact ? 14 : 20 };

  const glOn = spec.gl_md !== null && spec.gl_md > 0 && spec.gl_md < spec.shoe_md;
  const glMd = glOn ? Number(spec.gl_md) : 0;
  const wingRoom = tree && !compact ? clamp(W * 0.17, 48, 86) : 20;

  // How fat to draw the completion.
  //
  // It barely grows with the panel, and stops growing altogether past a point.  Sized to FILL the
  // width it came out nearly twice this on a wide monitor, which is not what a wellbore looks
  // like: a well is a slim thing in a lot of rock, and the extra width belongs to the margins.
  // The casing is not an input, so it is a fixed width; the TUBING is, so it scales with the size
  // that was typed - a 4 1/2" string visibly fills more of the annulus than a 2 7/8" one.
  const girth = compact ? 1 : clamp(W / 400, 0.72, 1.1);
  const rCasing = 57 * girth;
  const half0 = Math.min(13 + (spec.tubing_id - 2) * 2.2, 22);
  const rTubing = clamp(half0 * 1.383 * girth, 12 * girth, rCasing - 20 * girth);
  const bore = rTubing * 2;

  const usableW = W - pad.l - pad.r - 2 * rCasing;
  const usableH = H - pad.t - pad.b;
  const scaleY = usableH / maxTvd;
  const scaleX = maxReach > 1 ? Math.min(usableW / maxReach, scaleY) : scaleY;
  // Sat a little right of centre: the lift gas line and the depth scale both want the left,
  // and the room on the right was going spare.
  const x0 = Math.max(pad.l + wingRoom + rCasing, (pad.l + W - pad.r) / 2 + W * 0.045);
  const X = (/** @type {number} */ r) => x0 + r * scaleX;
  const Y = (/** @type {number} */ d) => pad.t + d * scaleY;
  const ground = Y(0);
  const bx = X(0);
  const axisX = Math.max(pad.l - 12, 28);

  // ---- the tree, laid out in the room above ground that the shared depth scale gives it ----
  // Everything is a fraction of that room, so the tree keeps its shape whatever height the page
  // settles on, and the valve symbol is sized against the tubing but never big enough to collide.
  const VR = tree ? Math.min(bore * 0.38, pad.t * 0.072) : 0;
  const INLET_Y = ground - pad.t * 0.085;     // the lift gas in, just above 0 ft
  const SEAL_Y = ground - pad.t * 0.19;       // the annulus seal, above it
  const LM_Y = ground - pad.t * 0.31;         // lower master
  const UM_Y = ground - pad.t * 0.46;         // upper master
  const TEE_Y = ground - pad.t * 0.63;        // the tee, and the wing arm
  const SWAB_Y = ground - pad.t * 0.80;       // the swab, shut: nothing stands above it
  const CAP_Y = ground - pad.t * 0.93;
  const armEnd = bx + Math.max(W * 0.22, rTubing + 60);

  // The tubing carries on above the wellhead, up to the swab valve.  That length is given a
  // NEGATIVE measured depth, so one set of helpers covers the whole string.
  const topMd = tree ? (SWAB_Y - ground) / scaleY : 0;

  const points = spec.md.map((_, i) => [X(reach[i]), Y(spec.tvd[i])]);

  /** A depth in MD, as a point on the drawing. @param {number} md */
  const at = (md) => {
    if (md <= 0) return [bx, ground + Math.max(md, topMd) * scaleY];
    const d = Math.min(md, perf_md);
    let i = 0;
    while (i < spec.md.length - 2 && spec.md[i + 1] < d) i += 1;
    const f = (d - spec.md[i]) / Math.max(spec.md[i + 1] - spec.md[i], 1e-9);
    return [points[i][0] + f * (points[i + 1][0] - points[i][0]),
            points[i][1] + f * (points[i + 1][1] - points[i][1])];
  };
  const step = Math.max(perf_md * 0.01, 1);
  /** The direction across the well at a depth. @param {number} md */
  const normalAt = (md) => {
    const a = at(clamp(md - step, topMd, perf_md));
    const b = at(clamp(md + step, topMd, perf_md));
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    return [-dy / len, dx / len];
  };
  /** How far the well leans at a depth, in degrees. A shape's own "up" is -y. @param {number} md */
  const tiltAt = (md) => {
    const a = at(clamp(md - step, topMd, perf_md));
    const b = at(clamp(md + step, topMd, perf_md));
    return Math.atan2(-(b[0] - a[0]), b[1] - a[1]) * 180 / Math.PI;
  };
  /** The part of the centre line between two depths. @param {number} from @param {number} to */
  const segment = (from, to) => {
    const pts = [at(from)];
    for (let i = 0; i < spec.md.length; i++) {
      if (spec.md[i] > from && spec.md[i] < to) pts.push(points[i]);
    }
    pts.push(at(to));
    return pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" ");
  };
  // Which side the lift gas is on: the valve goes on the LEFT of the tubing and the injection wing
  // at surface has to be on that same side, or the gas would enter one side and leave the other.
  const liftSide = normalAt(glMd || perf_md * 0.5)[0] > 0 ? -1 : 1;
  const wingDir = Math.sign(normalAt(0)[0] * liftSide) || -1;

  const defs = node("defs");
  svg.appendChild(defs);
  /** Put a hover label on something: the component names live here, not in a label gutter.
   * @param {any} el @param {string} text */
  const tip = (el, text) => { el.appendChild(node("title", {}, text)); return el; };
  /** @param {string} d @param {number} width @param {string} colour @param {Record<string, string|number>} [extra] */
  const stroke = (d, width, colour, extra = {}) =>
    svg.appendChild(node("path", { d, fill: "none", stroke: colour, "stroke-width": width,
                                   "stroke-linecap": "butt", "stroke-linejoin": "round", ...extra }));

  /** The gas colour at a depth: crimson where it is all solution gas, lighter where the two have
   * mixed above the valve.  A moving shape asks by depth, because a gradient in user space is read
   * in the shape's own coordinates once it carries a transform. @param {number} md */
  const gasAt = (md) => {
    if (!glOn) return PHASE_COLOURS.solutionGas;
    const yTop = at(topMd)[1];
    const span = Math.max(at(perf_md)[1] - yTop, 1);
    const k = clamp(((at(glMd)[1] - yTop) / span - (at(md)[1] - yTop) / span) / 0.12, 0, 1);
    return mix(PHASE_COLOURS.solutionGas, PHASE_COLOURS.gas, k);
  };

  // ---- the reservoir, below the depth the well is drawn to ----
  // The depth that was entered is the TOP of the perforations, so that is where the shared depth
  // scale ends and where the well stops.  The perforated interval hangs below it in the bottom
  // margin, not to scale: it is there to say the well is completed into rock, not how thick it is.
  // Washed across the whole width the band turned the fluid inside the casing olive, so it is
  // drawn either side of the hole and not behind it.
  const payTop = Y(maxTvd);
  const payBot = payTop + Math.min(pad.b - 14, 42);
  for (const s of [-1, 1]) {
    tip(svg.appendChild(node("rect", { class: "wv-pay",
      x: s < 0 ? bx - rCasing - 30 : bx + rCasing, y: payTop,
      width: 30, height: Math.max(payBot - payTop, 3), fill: "#b98a5a", opacity: 0.4 })),
      "Reservoir: the perforated interval, below the top perforation depth");
  }

  // ---- what is standing in the annulus, and in the casing below the packer ----
  // The standing fluid is washed in rather than laid on: a pure blue at full strength reads as a
  // painted bar, and what is wanted is a column of brine you can see the casing wall through.
  const annTop = tree ? (SEAL_Y - ground) / scaleY : 0;
  const annWidth = 2 * rCasing;      // laid down full width; the tubing fluid covers the middle
  if (glOn) {
    tip(stroke(segment(annTop, glMd), annWidth, PHASE_COLOURS.liftGas, { id: "wv-anngas" }),
        "Lift gas: a pressurised column from surface down to the gas lift valve");
    tip(stroke(segment(glMd, spec.packer_md), annWidth, PHASE_COLOURS.water,
               { id: "wv-anndead", opacity: 0.3 }),
        "Dead completion fluid, below the gas lift valve");
  } else {
    tip(stroke(segment(annTop, spec.packer_md), annWidth, PHASE_COLOURS.water,
               { id: "wv-anndead", opacity: 0.3 }),
        "Dead completion fluid: no gas is being injected");
  }
  tip(stroke(segment(spec.packer_md, perf_md), 2 * rCasing, PHASE_COLOURS.oil,
             { id: "wv-rathole", opacity: 0.22 }), "Reservoir fluid, below the packer");
  svg.appendChild(node("rect", { x: at(perf_md)[0] - rCasing, y: Y(maxTvd),
                                 width: 2 * rCasing, height: Math.min(pad.b - 14, 42),
                                 fill: PHASE_COLOURS.oil, opacity: 0.22 }));

  // ---- the fluid in the tubing ----
  // It stops at the swab valve, which is shut: nothing stands in the pipe above it.
  const toShoe = segment(topMd, spec.shoe_md);
  // Cleared to white first: the annulus is laid down full width behind it, and a see-through
  // liquid colour over the lift gas came out olive.  The wash over it is the LIQUID standing in
  // the pipe, tinted between oil and water by the water cut - it used to be oil green at 0.38,
  // which left the oil moving up through it invisible against its own background.
  const liquidTint = mix(PHASE_COLOURS.oil, PHASE_COLOURS.water, clamp(spec.water_cut, 0, 1));
  stroke(toShoe, bore, "#ffffff");
  stroke(toShoe, bore, liquidTint, { id: "wv-bore", opacity: 0.13 });

  // ---- the flow regimes, drawn rather than tinted ----
  /** @type {{from: number, to: number, family: string, regime: string, px: number,
   *           riserFrom?: number}[]} */
  const bands = [];
  /** @type {Set<string>} */
  const families = new Set();
  if (spec.pattern) {
    for (let i = 0; i < spec.pattern.regime.length; i++) {
      const from = spec.pattern.md[i];
      if (from >= spec.shoe_md) continue;
      const to = Math.min(spec.pattern.md[i + 1] ?? spec.shoe_md, spec.shoe_md);
      const family = flowFamily(spec.pattern.regime[i]) || "none";
      if (family !== "none") families.add(family);
      const last = bands[bands.length - 1];
      if (last && last.family === family) last.to = to;
      else bands.push({ from, to, family, regime: spec.pattern.regime[i], px: 0 });
    }
  }
  if (!bands.length) bands.push({ from: 0, to: spec.shoe_md, family: "liquid", regime: "", px: 0 });
  bands[0].from = topMd;
  for (const b of bands) {
    b.px = Math.abs(at(b.to)[1] - at(b.from)[1]) + Math.abs(at(b.to)[0] - at(b.from)[0]);
    b.riserFrom = b.from;
  }
  // the shapes stop short of the tee, where the mask would otherwise crop them into a block
  if (tree) bands[0].riserFrom = topMd + 26 / scaleY;

  /** The wavy inner edge of the liquid film in an annular section. @param {{from:number,to:number}} b @param {number} side */
  function filmPath(b, side) {
    const n = Math.max(8, Math.round(Math.abs(b.to - b.from) / 40));
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const md = b.from + (b.to - b.from) * i / n;
      const p = at(md);
      const nn = normalAt(md);
      const off = bore * 0.385 + Math.sin(i * 1.1) * bore * 0.03;
      pts.push(`${(p[0] + nn[0] * side * off).toFixed(2)},${(p[1] + nn[1] * side * off).toFixed(2)}`);
    }
    return `M${pts.join(" L")}`;
  }
  for (const b of bands) {
    if (b.family !== "annular" && b.family !== "gas") continue;
    stroke(segment(b.from, b.to), bore, gasAt((b.from + b.to) / 2),
           { class: "wv-fill", opacity: 0.85 });
    if (b.family === "annular") {
      for (const side of [-1, 1]) {
        svg.appendChild(node("path", { class: "wv-film", d: filmPath(b, side), fill: "none",
                                       stroke: PHASE_COLOURS.oil, "stroke-width": bore * 0.15,
                                       "stroke-linecap": "butt", opacity: 0.85 }));
      }
    }
  }
  // the hover labels, over the intervals the correlation actually reported
  if (spec.pattern) {
    for (let i = 0; i < spec.pattern.regime.length; i++) {
      const from = spec.pattern.md[i];
      if (from >= spec.shoe_md) continue;
      const to = Math.min(spec.pattern.md[i + 1] ?? spec.shoe_md, spec.shoe_md);
      const fam = flowFamily(spec.pattern.regime[i]);
      tip(svg.appendChild(node("path", { class: "wv-hit", d: segment(from, to), fill: "none",
                                         stroke: "transparent", "stroke-width": bore + 6,
                                         "stroke-linecap": "butt" })),
          `${fam ? FLOW_FAMILIES[fam].label : spec.pattern.regime[i]}`
          + ` flow, ${fmt(spec.toShown(from))}-${fmt(spec.toShown(to))} ${spec.lengthUnit} MD`);
    }
  }

  // ---- the strings: ONE bold line each, with the fluid filling right up to it ----
  // A pair of lines for each string read as four pipes rather than two.
  const INK = "#111827";
  const casTop = tree ? annTop : 0;
  for (const s of [-1, 1]) {
    const cas = spec.md.map((_, i) => {
      const n = normalAt(spec.md[i]);
      return [points[i][0] + n[0] * s * rCasing, points[i][1] + n[1] * s * rCasing];
    });
    const top = at(casTop);
    const nTop = normalAt(casTop);
    tip(svg.appendChild(node("path", { class: "wv-casing",
      d: `M${top[0] + nTop[0] * s * rCasing},${top[1] + nTop[1] * s * rCasing} `
         + cas.map((p) => `L${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" "),
      fill: "none", stroke: INK, "stroke-width": 3.2 })), "Production casing");
    const tub = [];
    for (let md = topMd; md < spec.shoe_md; md += Math.max(perf_md / 40, 1)) {
      const p = at(md);
      const n = normalAt(md);
      tub.push([p[0] + n[0] * s * rTubing, p[1] + n[1] * s * rTubing]);
    }
    const endP = at(spec.shoe_md);
    const endN = normalAt(spec.shoe_md);
    tub.push([endP[0] + endN[0] * s * rTubing, endP[1] + endN[1] * s * rTubing]);
    // the casing runs on down through the perforated interval, which is below the depth scale
    cas.push([cas[cas.length - 1][0], payBot]);
    const nCap = normalAt(topMd);
    const capP = [bx + nCap[0] * s * rTubing, CAP_Y];
    tip(svg.appendChild(node("path", { class: "wv-tubing",
      d: `M${capP[0]},${capP[1]} ` + tub.map((p) => `L${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" "),
      fill: "none", stroke: INK, "stroke-width": 3.2 })), "Production tubing");
  }

  // ---- the seals: red crossed blocks across the annulus ----
  /** @param {number} cx @param {number} cy @param {number} angle @param {string} cls @param {string} label */
  const sealBlock = (cx, cy, angle, cls, label) => {
    const len = rCasing - rTubing;
    const g = node("g", { class: cls, transform: `rotate(${angle} ${cx} ${cy})` });
    g.appendChild(node("rect", { x: cx - len / 2, y: cy - 7, width: len, height: 14,
                                 fill: "#fecaca", stroke: SEAL, "stroke-width": 1.5 }));
    g.appendChild(node("line", { x1: cx - len / 2, y1: cy - 7, x2: cx + len / 2, y2: cy + 7,
                                 stroke: SEAL, "stroke-width": 1.3 }));
    g.appendChild(node("line", { x1: cx - len / 2, y1: cy + 7, x2: cx + len / 2, y2: cy - 7,
                                 stroke: SEAL, "stroke-width": 1.3 }));
    tip(g, label);
    svg.appendChild(g);
  };
  const packPt = at(spec.packer_md);
  {
    const n = normalAt(spec.packer_md);
    const angle = Math.atan2(n[1], n[0]) * 180 / Math.PI;
    for (const side of [-1, 1]) {
      sealBlock(packPt[0] + n[0] * side * (rCasing + rTubing) / 2,
                packPt[1] + n[1] * side * (rCasing + rTubing) / 2,
                angle, "wv-packer", "Production packer: seals the annulus above the perforations");
    }
  }

  // ---- the open tubing tailpipe, ending at the top of the perforations ----
  // Nothing is drawn across the end: the tubing is open, and a stub either side read as a shoe
  // closing it off.
  const shoePt = at(spec.shoe_md);

  // ---- the perforations: horizontal, through both walls, stopping short of the shoe ----
  /** @type {{x: number, y: number, nx: number, ny: number}[]} */
  const perfs = [];
  const endX = at(perf_md)[0];
  const perfBotY = payBot - 11;                 // they stop short of the shoe, leaving a sump
  const nPerf = clamp(Math.round((perfBotY - payTop - 6) / 9), 3, 8);
  for (let i = 0; i < nPerf; i++) {
    const y = payTop + 6 + (perfBotY - payTop - 6) * i / Math.max(nPerf - 1, 1);
    for (const side of [-1, 1]) {
      tip(svg.appendChild(node("line", { x1: endX + side * rCasing, y1: y,
        x2: endX + side * (rCasing + 20), y2: y,
        stroke: "#7c3f1d", "stroke-width": 2.6, "stroke-linecap": "round" })), "Perforations");
      perfs.push({ x: endX + side * (rCasing + 20), y, nx: -side, ny: 0 });
    }
  }

  // ---- the casing shoe, at the bottom of the reservoir ----
  // A solid wedge standing on the bottom of the casing: straight edge up the casing wall, flat base
  // along the bottom and the slope facing out into the formation.
  svg.appendChild(node("line", { x1: endX - rCasing, y1: payBot, x2: endX + rCasing, y2: payBot,
                                 stroke: INK, "stroke-width": 3.2 }));
  for (const side of [-1, 1]) {
    const ax = endX + side * rCasing;
    const up = 15 * girth;
    const out = 9 * girth;
    tip(svg.appendChild(node("polygon", { class: "wv-shoe",
      points: `${ax},${payBot} ${ax},${payBot - up} ${ax + side * out},${payBot}`,
      fill: INK })), "Casing shoe");
  }

  // ---- the side pocket mandrel, with the gas lift valve in it ----
  let glCentre = null;
  if (glOn) {
    const p = at(glMd);
    const n = normalAt(glMd);
    const w = Math.max((rCasing - rTubing) * 0.3, 7);
    const h = Math.max(bore * 1.1, 32);
    const px = p[0] + n[0] * liftSide * rTubing;
    const py = p[1] + n[1] * liftSide * rTubing;
    const angle = Math.atan2(n[1] * liftSide, n[0] * liftSide) * 180 / Math.PI;
    glCentre = [px + n[0] * liftSide * w / 2, py + n[1] * liftSide * w / 2];
    tip(svg.appendChild(node("path", { id: "wv-glvalve",
      d: `M0,${-h / 2} C${w * 0.95},${-h * 0.3} ${w},${-h * 0.1} ${w},0 `
         + `C${w},${h * 0.1} ${w * 0.95},${h * 0.3} 0,${h / 2} Z`,
      transform: `translate(${px},${py}) rotate(${angle})`,
      fill: "#ffffff", stroke: INK, "stroke-width": 1.6, "stroke-linejoin": "round" })),
      "Side pocket mandrel with the gas lift valve, injecting into the tubing");
    svg.appendChild(node("circle", { cx: glCentre[0], cy: glCentre[1],
                                     r: Math.min(w * 0.4, 4), fill: PHASE_COLOURS.liftGas }));
  }

  // ---- the valve symbol: context, not the subject, so it is drawn in grey ----
  /** @param {number} x @param {number} y @param {string} id @param {boolean} open @param {string} label */
  const valveSymbol = (x, y, id, open, label) => {
    const g = node("g", { id, class: "wv-valve" });
    const ink = open ? "#8d9aa8" : "#c3ccd4";
    const k = VR * 0.707;
    g.appendChild(node("circle", { cx: x, cy: y, r: VR, fill: "#ffffff", stroke: ink,
                                   "stroke-width": 1.5 }));
    g.appendChild(node("line", { x1: x - k, y1: y - k, x2: x + k, y2: y + k,
                                 stroke: ink, "stroke-width": 1.5 }));
    g.appendChild(node("line", { x1: x - k, y1: y + k, x2: x + k, y2: y - k,
                                 stroke: ink, "stroke-width": 1.5 }));
    tip(g, `${label}${open ? "" : " (shut)"}`);
    return g;
  };

  if (tree) {
    // the annulus seal, standing above the ground line on the wellhead
    for (const side of [-1, 1]) {
      sealBlock(bx + side * (rCasing + rTubing) / 2, SEAL_Y, 0, "wv-wellhead-seal",
                "Wellhead annulus seal: the annulus is closed at surface");
    }
    // The gas lift inlet is ALWAYS drawn, open when injecting and shut when not, so the two states
    // are the same picture with one thing changed rather than two different drawings.
    const tipX = bx + wingDir * rCasing;
    const outX = tipX + wingDir * (wingRoom - 10);
    svg.appendChild(node("line", { x1: outX, y1: INLET_Y, x2: tipX, y2: INLET_Y,
                                   stroke: glOn ? PHASE_COLOURS.liftGas : "#9aa7b4",
                                   "stroke-width": 3, "stroke-linecap": "round" }));
    if (glOn) {
      svg.appendChild(node("polygon", {
        points: `${tipX},${INLET_Y} ${tipX + wingDir * 11},${INLET_Y - 5.5} `
                + `${tipX + wingDir * 11},${INLET_Y + 5.5}`, fill: PHASE_COLOURS.liftGas }));
    }
    svg.appendChild(valveSymbol(outX - wingDir * (wingRoom - 10) * 0.42, INLET_Y, "wv-annwing",
                                glOn, "Annulus wing valve: lift gas into the annulus"));
    // Over the inlet it names, running outwards from the casing wall: out at the panel edge it
    // was a caption with a lot of white between it and the thing it labelled.
    svg.appendChild(node("text", { x: tipX + wingDir * 10, y: INLET_Y - 14,
                                   class: "wv-lbl", fill: glOn ? "#8a5a00" : "#64748b",
                                   "text-anchor": wingDir < 0 ? "end" : "start" },
                                 glOn ? "lift gas in: ON" : "lift gas in: OFF"));

    // the tee and the flowline out of it
    const armH = Math.min(bore * 1.3, 34);
    const grey = { fill: "#d7dde3", stroke: "#8d9aa8", "stroke-width": 1.4 };
    tip(svg.appendChild(node("rect", { x: bx + rTubing - 1, y: TEE_Y - armH / 2,
                                       width: armEnd - bx - rTubing, height: armH, ...grey })),
        "Flowline");
    const armBore = Math.min(bore * 0.72, 30);
    const shallow = bands[0];
    const gassy = shallow.family === "annular" || shallow.family === "gas";
    svg.appendChild(node("rect", { id: "wv-armbore", x: bx - rTubing,
                                   y: TEE_Y - armBore / 2, width: armEnd - bx + rTubing - 2,
                                   height: armBore,
                                   fill: gassy ? gasAt(topMd) : PHASE_COLOURS.oil,
                                   opacity: gassy ? 0.85 : 0.38 }));
    svg.appendChild(node("rect", { x: bx - rTubing - 6, y: CAP_Y - 10, width: 2 * rTubing + 12,
                                   height: 10, rx: 1.5, fill: "#8d9aa8" }));
    svg.appendChild(node("line", { x1: armEnd, y1: TEE_Y, x2: armEnd + 20, y2: TEE_Y,
                                   stroke: "#8d9aa8", "stroke-width": 2.2 }));
    svg.appendChild(node("polygon", { id: "wv-outflow",
      points: `${armEnd + 30},${TEE_Y} ${armEnd + 18},${TEE_Y - 6} ${armEnd + 18},${TEE_Y + 6}`,
      fill: "#8d9aa8" }));

    svg.appendChild(valveSymbol(bx, SWAB_Y, "wv-swab", false, "Swab valve"));
    svg.appendChild(valveSymbol(bx + (armEnd - bx) * 0.62, TEE_Y, "wv-wing",
                                spec.chokeOpen !== false, "Production wing valve"));
    svg.appendChild(valveSymbol(bx, UM_Y, "wv-master", spec.masterOpen !== false,
                                "Upper master valve"));
    svg.appendChild(valveSymbol(bx, LM_Y, "wv-lower-master", spec.masterOpen !== false,
                                "Lower master valve"));
  }

  // ---- the depth scale ----
  // The depth the drawing is to is recorded on the SVG itself whether or not the scale is drawn,
  // because the panel beside it has to be able to line its own depths up with this one.
  svg.setAttribute("data-y-zero", String(ground));
  svg.setAttribute("data-y-deep", String(Y(maxTvd)));
  svg.setAttribute("data-deep-tvd", String(maxTvd));
  if (depthAxis) {
    const stepFt = maxTvd > 12000 ? 4000 : maxTvd > 6000 ? 2000 : maxTvd > 2500 ? 1000 : 500;
    for (let d = 0; d <= maxTvd + 1; d += stepFt) {
      const y = Y(d);
      svg.appendChild(node("line", { x1: axisX - 5, y1: y, x2: axisX, y2: y, stroke: "#94a3b8",
                                     "stroke-width": 0.8 }));
      svg.appendChild(node("text", { x: axisX - 8, y: y + 3, class: "wv-depth",
                                     "text-anchor": "end" }, fmt(spec.toShown(d))));
    }
    svg.appendChild(node("line", { x1: axisX, y1: ground, x2: axisX, y2: Y(maxTvd),
                                   stroke: "#e2e8f0", "stroke-width": 0.8 }));
    svg.appendChild(node("text", { x: 2, y: ground - 14, class: "wv-depth" },
                                 `TVD, ${spec.lengthUnit}`));
  }

  // ---- the layers the moving fluid is drawn in ----
  // The fluid is masked to the inside of the pipe it is in.  The mask leaves out the pipe above the
  // swab valve, which is shut, so nothing is ever drawn standing in it.
  const armOut = tree ? { y: TEE_Y, from: bx + rTubing, to: armEnd + 26 } : null;
  const mask = node("mask", { id: "wv-inside", maskUnits: "userSpaceOnUse",
                              x: 0, y: 0, width: W, height: H });
  mask.appendChild(node("path", { d: toShoe, fill: "none", stroke: "#ffffff",
                                  "stroke-width": bore, "stroke-linecap": "butt" }));
  if (armOut) {
    const armBore = Math.min(bore * 0.72, 30);
    mask.appendChild(node("rect", { x: armOut.from - 2, y: armOut.y - armBore / 2,
                                    width: armOut.to - armOut.from + 6, height: armBore,
                                    fill: "#ffffff" }));
  }
  defs.appendChild(mask);
  svg.appendChild(node("g", { id: "wv-inflow" }));
  svg.appendChild(node("g", { id: "wv-fluid", mask: "url(#wv-inside)" }));
  svg.appendChild(node("g", { id: "wv-jet", mask: "url(#wv-inside)" }));

  return { svg, spec, bands, perfs, shoePt, glCentre, glMd, glOn, liftSide, annTop,
           bore, wTubing: 2 * rTubing, wAnnulus: 2 * rCasing, at, normalAt, tiltAt, topMd,
           families, girth, arm: armOut, gasAt };
}

/**
 * A bullet-shaped Taylor bubble, drawn around the origin with its dome pointing up: a round nose,
 * straight sides down most of the bore, and a bottom that bows up into the bubble, which is what
 * the tail of one looks like with the liquid film running back down past it.
 * @param {number} w
 */
function taylorPath(w) {
  const r = w / 2;
  const h = w * 1.7;
  return `M${-r},${-h / 2 + r} A${r},${r} 0 0 1 ${r},${-h / 2 + r} L${r},${h / 2} `
       + `Q0,${h / 2 - w * 0.3} ${-r},${h / 2} Z`;
}

/** A lumpy, distorted gas pocket for churn flow. @param {number} w @param {() => number} rnd */
function churnPath(w, rnd) {
  const r = w / 2;
  const h = w * 0.95;
  const p = (/** @type {number} */ a, /** @type {number} */ b) =>
    `${(a * r * (0.75 + rnd() * 0.5)).toFixed(1)},${(b * h / 2 * (0.75 + rnd() * 0.5)).toFixed(1)}`;
  return `M${p(0, -1)} Q${p(1.1, -0.8)} ${p(0.9, 0)} Q${p(1.1, 0.8)} ${p(0, 1)} `
       + `Q${p(-1.1, 0.8)} ${p(-0.9, 0)} Q${p(-1.1, -0.8)} ${p(0, -1)} Z`;
}

/**
 * Animate the fluid in a drawing built by render().  Returns a handle with stop() and replace().
 * @param {ReturnType<typeof render>} view
 */
export function animate(view) {
  let scene = view;
  let running = true;

  /** @type {any[]} */
  let risers = [];
  /** @type {any[]} */
  let inflow = [];
  /** @type {any[]} */
  let jet = [];
  /** @type {any[]} */
  let armFlow = [];

  function build() {
    const s = scene.spec;
    const bore = scene.bore;
    const host = scene.svg.querySelector("#wv-fluid");
    const jetHost = scene.svg.querySelector("#wv-jet");
    const inHost = scene.svg.querySelector("#wv-inflow");
    if (!host || !jetHost || !inHost) return;
    host.textContent = "";
    jetHost.textContent = "";
    inHost.textContent = "";
    risers = [];

    // How much of the pipe is gas, which is what sets how many bubbles are worth drawing.  It is a
    // look, not a calculation: the regime the correlation reported is what decides the SHAPE.
    const gassy = Math.min(0.9, 0.25 + s.gor / 2500);

    for (const band of scene.bands) {
      const px = Math.max(band.px, 1);
      /** @param {string} tag @param {any} el @param {number} n @param {number} speed */
      const add = (tag, el, n, speed) => {
        for (let i = 0; i < n; i++) {
          const g = el(i);
          host.appendChild(g);
          risers.push({ band, u: (i + Math.random() * 0.6) / n, speed, node: g, tag,
                        across: 0, wobble: Math.random() * 6.3 });
        }
      };
      if (band.family === "slug") {
        // Taylor bubbles nearly filling the bore, with liquid slugs between them
        const w = bore * 0.74;
        const n = clamp(Math.round(px / (w * 2.6)), 1, 10);
        add("taylor", () => node("path", { d: taylorPath(w), fill: scene.gasAt(band.to),
                                           "data-gas": 1, opacity: 0.92 }),
            n, 1);
        // and the small bubbles carried in the liquid between them
        const m = clamp(Math.round(px / 34), 1, 10);
        add("bubble", () => node("circle", { r: bore * 0.07, fill: scene.gasAt(band.to), "data-gas": 1, opacity: 0.9 }),
            m, 0.78);
      } else if (band.family === "bubble" || band.family === "liquid") {
        const n = band.family === "liquid" ? 0
          : clamp(Math.round(px / 15 * gassy), 2, 26);
        add("bubble", () => node("circle", { r: bore * (0.055 + Math.random() * 0.045),
                                             fill: scene.gasAt(band.to), "data-gas": 1, opacity: 0.9 }), n, 1);
      } else if (band.family === "churn") {
        const n = clamp(Math.round(px / 30), 2, 9);
        add("churn", () => node("path", { d: churnPath(bore * 0.78, Math.random),
                                          fill: scene.gasAt(band.to), "data-gas": 1, opacity: 0.88 }), n, 1.15);
        const m = clamp(Math.round(px / 26), 2, 8);
        add("froth", () => node("ellipse", { rx: bore * 0.3, ry: bore * 0.09,
                                             fill: PHASE_COLOURS.oil, opacity: 0.75 }), m, 1.05);
      } else if (band.family === "annular" || band.family === "gas") {
        // entrained liquid droplets, carried fast up the middle of the gas core
        const n = clamp(Math.round(px / 16), 3, 22);
        add("mist", () => node("circle", { r: 1.2 + Math.random() * 1.1,
                                           fill: Math.random() < s.water_cut
                                             ? PHASE_COLOURS.water : PHASE_COLOURS.oil,
                                           opacity: 0.95 }), n, 2.1);
      } else {
        const n = clamp(Math.round(px / 22), 2, 14);
        add("bubble", () => node("circle", { r: bore * 0.06, fill: scene.gasAt(band.to), "data-gas": 1, opacity: 0.8 }),
            n, 1);
      }
      // The liquid riding up with the gas, split between oil and water by the water cut.  Both
      // are drawn: oil used to be the colour of the pipe's background and nothing else, so it was
      // the one phase on the page that never appeared to move.
      if (band.family !== "annular" && band.family !== "gas") {
        const liquid = clamp(Math.round(px / 24), 2, 18);
        const nWater = Math.round(liquid * clamp(s.water_cut, 0, 1));
        const nOil = liquid - nWater;
        if (nOil > 0) {
          add("oil", () => node("circle", { r: 2.1 + Math.random() * 1.2,
                                            fill: PHASE_COLOURS.oil, opacity: 0.95 }), nOil, 0.92);
        }
        if (nWater > 0) {
          add("water", () => node("circle", { r: 2 + Math.random() * 1.2,
                                              fill: PHASE_COLOURS.water, opacity: 0.95 }),
              nWater, 0.9);
        }
      }
    }
    // where across the bore each one sits
    for (const r of risers) {
      const room = r.tag === "taylor" || r.tag === "churn" || r.tag === "froth" ? 0.06
        : r.tag === "mist" ? 0.24 : r.tag === "oil" || r.tag === "water" ? 0.34 : 0.3;
      r.across = (Math.random() - 0.5) * scene.bore * room * 2;
    }

    // the lift gas jetting through the valve into the tubing
    jet = [];
    if (scene.glOn && scene.glCentre) {
      for (let i = 0; i < 7; i++) {
        const c = node("circle", { r: 1.8 + Math.random() * 1.3, fill: PHASE_COLOURS.liftGas });
        jetHost.appendChild(c);
        jet.push({ u: i / 7, node: c });
      }
    }

    // the fluid coming in through the perforations and turning up into the tailpipe
    inflow = [];
    for (let i = 0; i < 16; i++) {
      const perf = scene.perfs[i % scene.perfs.length];
      const c = node("circle", { r: 2.4 + Math.random() * 0.9, fill: phaseIn(s) });
      inHost.appendChild(c);
      inflow.push({ perf, t: Math.random(), speedScale: 0.6 + Math.random() * 0.8, node: c });
    }

    // and the flow out along the wing arm
    // Out along the wing arm.  What turns the corner at the tee is whatever came up the tubing,
    // so the arm carries the same three phases rather than oil on its own.
    armFlow = [];
    if (scene.arm) {
      for (let i = 0; i < 9; i++) {
        const c = node("circle", { r: 2.6, class: "wv-arm", fill: phaseIn(s, true) });
        host.appendChild(c);
        armFlow.push({ u: i / 9, node: c });
      }
    }
  }

  let last = performance.now();
  /** @param {number} now */
  function frame(now) {
    if (!running) return;
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    const s = scene.spec;
    // A well that found no operating point is not flowing: everything stops where it is, which is
    // the whole point of showing it.
    const speed = s.flowing ? s.speed : 0;

    for (const r of risers) {
      const spanFt = r.band.to - r.band.from;
      if (speed > 0) {
        r.u += speed * r.speed * dt / Math.max(r.band.px, 1);
        if (r.u > 1.06) r.u -= 1.12;
      }
      r.wobble += dt * 3;
      const md = r.band.to - r.u * spanFt;
      const p = scene.at(md);
      const n = scene.normalAt(md);
      const sway = r.tag === "bubble" || r.tag === "mist" ? Math.sin(r.wobble) * 1.6 : 0;
      const off = r.across + sway;
      const x = p[0] + n[0] * off;
      const y = p[1] + n[1] * off;
      if (r.tag === "taylor" || r.tag === "churn" || r.tag === "froth") {
        const wob = r.tag === "churn" ? 1 + Math.sin(r.wobble) * 0.09 : 1;
        r.node.setAttribute("transform",
          `translate(${x.toFixed(2)},${y.toFixed(2)}) rotate(${scene.tiltAt(md).toFixed(1)}) `
          + `scale(${wob.toFixed(3)},${(2 - wob).toFixed(3)})`);
      } else {
        r.node.setAttribute("cx", x.toFixed(2));
        r.node.setAttribute("cy", y.toFixed(2));
      }
      r.node.setAttribute("opacity", s.flowing ? "0.92" : "0.35");
    }

    // the jet through the gas lift valve: out of the valve, across into the bore, and away up it
    if (scene.glCentre) {
      const n = scene.normalAt(scene.glMd);
      for (const j of jet) {
        if (speed > 0) j.u = (j.u + dt * 1.6) % 1;
        const into = Math.min(j.u * 2.2, 1);
        const up = Math.max(j.u - 0.45, 0) / 0.55;
        const off = (scene.wTubing / 2) * scene.liftSide * (1 - into)
          + n[0] * 0 + scene.liftSide * (scene.bore * 0.18) * into;
        const base = scene.at(scene.glMd - up * (scene.glMd - scene.topMd) * 0.1);
        j.node.setAttribute("cx", String(base[0] + n[0] * off));
        j.node.setAttribute("cy", String(base[1] + n[1] * off));
        j.node.setAttribute("opacity", s.flowing ? String(0.95 - 0.7 * up) : "0");
      }
    }

    for (const p of inflow) {
      p.t += dt * (s.flowing ? 0.45 : 0) * p.speedScale;
      if (p.t > 1) p.t -= 1;
      const inLen = 0.42;
      let x;
      let y;
      if (p.t < inLen) {
        const f = p.t / inLen;
        x = p.perf.x + p.perf.nx * f * 26;
        y = p.perf.y + p.perf.ny * f * 26;
      } else {
        const f = (p.t - inLen) / (1 - inLen);
        const sx = p.perf.x + p.perf.nx * 26;
        const sy = p.perf.y + p.perf.ny * 26;
        x = sx + (scene.shoePt[0] - sx) * f;
        y = sy + (scene.shoePt[1] - sy) * f;
      }
      p.node.setAttribute("cx", String(x));
      p.node.setAttribute("cy", String(y));
      p.node.setAttribute("opacity", s.flowing ? String(0.9 - 0.5 * Math.max(p.t - 0.75, 0) * 4) : "0");
    }

    if (scene.arm) {
      for (const a of armFlow) {
        if (speed > 0) a.u = (a.u + speed * dt / Math.max(scene.arm.to - scene.arm.from, 1)) % 1;
        a.node.setAttribute("cx", String(scene.arm.from + a.u * (scene.arm.to - scene.arm.from)));
        a.node.setAttribute("cy", String(scene.arm.y));
        a.node.setAttribute("opacity", s.flowing ? "0.92" : "0.25");
      }
      const out = scene.svg.querySelector("#wv-outflow");
      if (out) out.setAttribute("opacity", s.flowing ? "1" : "0.25");
    }

    requestAnimationFrame(frame);
  }

  build();
  requestAnimationFrame(frame);
  return {
    stop() { running = false; },
    /** @param {ReturnType<typeof render>} next */
    replace(next) {
      scene = next;
      build();
    },
  };
}
