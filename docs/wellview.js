// @ts-check
/**
 * wellview.js - the live wellbore schematic: one drawing, used by two pages.
 *
 * The main page shows it beside the pressure and temperature profile, driven by the well that has
 * been entered and solved. schematic.html shows the same drawing with its own choke and master
 * valve, as a demonstration of how a well responds. Neither has a picture of its own: a schematic
 * that disagreed with the calculation beside it would be worse than no schematic.
 *
 * How the well is drawn, whatever its shape
 *     The centre line of the well is built from the survey - the horizontal distance travelled
 *     against the true vertical depth - and everything else is drawn by STROKING that same line at
 *     different widths: the cement widest, then the casing, the annulus, the tubing wall and the
 *     bore. Concentric bands come out right for a vertical well and for a deviated one with no
 *     offset arithmetic at all, and the fluid runs along the very same line.
 *
 * What the drawing insists on getting right
 *     * The production packer sits ABOVE the top of the perforations, not across them, because that
 *       is where a packer goes: it seals the annulus off above the producing interval.
 *     * The tubing ends in an open shoe at or just below the packer. Formation fluid enters the
 *       casing through the perforations, rises inside the casing below the packer, and turns into
 *       the open end of the tubing.
 *     * Lift gas enters the annulus at the tubing head, travels DOWN the annulus to the gas lift
 *       valve at its own depth, passes through the valve into the tubing, and joins the flow there.
 *     * Above that valve the gas bubbles are bigger and more frequent, and they keep growing towards
 *       surface, because that is what gas does as the pressure falls.
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
 * @property {boolean} [masterOpen] whether the master valve is drawn open
 * @property {boolean} [chokeOpen]  whether the wing valve is drawn open
 */

// The flow-pattern families, shared with the page so one pattern is one colour everywhere.
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
 * Produced gas and injected lift gas are deliberately the SAME green: it is the same gas, and two
 * colours for it suggested two different fluids.  That green used to be oil's, so oil is now the
 * brown of a tank sample - with three phases on screen each needs a colour of its own, and the
 * legend beside the drawing says which is which.
 * @type {Record<string, string>}
 */
export const PHASE_COLOURS = { oil: "#b5651d", gas: "#2f9e44", water: "#3b82c4" };

/** Everything to do with gas is this green: the bubbles, the valve, the port and the lift line. */
const GAS = PHASE_COLOURS.gas;
const GAS_DARK = "#1b7a33";

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
  // the horizontal distance travelled, worked out from MD and TVD step by step
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
  const pad = { t: spec.padTop ?? (tree ? 104 : 34), b: spec.padBottom ?? 26,
                l: compact ? 40 : 66, r: compact ? 14 : 140 };
  const half = Math.min(13 + (spec.tubing_id - 2) * 2.2, 22);     // half the bore, in pixels
  const bore = half * 2;
  const wTubing = bore + 7;
  const wAnnulus = bore + 34;
  const wCasing = bore + 42;
  const wCement = bore + 62;

  const usableW = W - pad.l - pad.r - wCement;
  const usableH = H - pad.t - pad.b;
  // The vertical scale is fixed by the shared depth scale, so the well always spans exactly the
  // aligned height.  The horizontal one is squeezed to fit the room left over and never stretched
  // past the vertical one, which keeps a deviated well looking deviated without pulling its depths
  // out of line with the chart beside it.
  const scaleY = usableH / maxTvd;
  const scaleX = maxReach > 1 ? Math.min(usableW / maxReach, scaleY) : scaleY;
  // centred in the room it has: a vertical well pinned to the left of the panel left a wide empty
  // field of rock to the right of it
  const x0 = pad.l + wCement / 2 + Math.max(usableW - maxReach * scaleX, 0) / 2;
  const X = (/** @type {number} */ r) => x0 + r * scaleX;
  const Y = (/** @type {number} */ d) => pad.t + d * scaleY;

  const points = spec.md.map((_, i) => [X(reach[i]), Y(spec.tvd[i])]);
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" ");

  /** A depth in MD, as a point on the drawing. @param {number} md */
  const at = (md) => {
    const d = Math.min(Math.max(md, 0), perf_md);
    let i = 0;
    while (i < spec.md.length - 2 && spec.md[i + 1] < d) i += 1;
    const f = (d - spec.md[i]) / Math.max(spec.md[i + 1] - spec.md[i], 1e-9);
    return [points[i][0] + f * (points[i + 1][0] - points[i][0]),
            points[i][1] + f * (points[i + 1][1] - points[i][1])];
  };
  /** The direction of the well at a depth, and the direction across it. @param {number} md */
  const normalAt = (md) => {
    const a = at(Math.max(md - perf_md * 0.01, 0));
    const b = at(Math.min(md + perf_md * 0.01, perf_md));
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    return [-dy / len, dx / len];
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
  // Which side of the well the lift gas is on.  The surface port is drawn on the left, so the gas
  // must run down the left of the annulus and the valve must be on the left of the tubing: all three
  // read this, so they cannot disagree.  normalAt points left for a well heading down, but not for
  // one heading up or sideways, so the sign is worked out from the line rather than assumed.
  const liftSide = normalAt(0)[0] > 0 ? -1 : 1;

  // ---- the patterns ----
  const defs = node("defs");
  const cem = node("pattern", { id: "wv-cem", width: 6, height: 6, patternUnits: "userSpaceOnUse",
                                patternTransform: "rotate(45)" });
  cem.appendChild(node("rect", { width: 6, height: 6, fill: "#c9bda8" }));
  cem.appendChild(node("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "#ab9e85", "stroke-width": 1.1 }));
  defs.appendChild(cem);
  const rock = node("pattern", { id: "wv-rock", width: 11, height: 11, patternUnits: "userSpaceOnUse" });
  rock.appendChild(node("rect", { width: 11, height: 11, fill: "#ded5c2" }));
  rock.appendChild(node("circle", { cx: 3, cy: 4, r: 1, fill: "#c7bba1" }));
  rock.appendChild(node("circle", { cx: 8, cy: 9, r: 1.1, fill: "#c7bba1" }));
  defs.appendChild(rock);
  const pay = node("pattern", { id: "wv-pay", width: 9, height: 9, patternUnits: "userSpaceOnUse" });
  pay.appendChild(node("rect", { width: 9, height: 9, fill: "#e9dcbc" }));
  pay.appendChild(node("circle", { cx: 2.5, cy: 3, r: 1.5, fill: "#cbb98f" }));
  pay.appendChild(node("circle", { cx: 7, cy: 7, r: 1.4, fill: "#cbb98f" }));
  defs.appendChild(pay);
  svg.appendChild(defs);

  // ---- the ground, and the reservoir band ----
  const ground = Y(0);
  const earthL = Math.max(pad.l - 18, 2);
  const earthR = W - pad.r + 10;
  svg.appendChild(node("rect", { x: earthL, y: ground, width: earthR - earthL,
                                 height: H - ground - 6, fill: "url(#wv-rock)", opacity: 0.6 }));
  const payY = at(spec.perf_top)[1];
  svg.appendChild(node("rect", { x: earthL, y: payY - 4, width: earthR - earthL,
                                 height: H - 6 - (payY - 4), fill: "url(#wv-pay)" }));
  svg.appendChild(node("line", { x1: earthL, y1: payY - 4, x2: earthR, y2: payY - 4,
                                 stroke: "#b8a77f", "stroke-width": 1 }));
  svg.appendChild(node("line", { x1: earthL - 10, y1: ground, x2: earthR, y2: ground,
                                 stroke: "#9aa7b2", "stroke-width": 1.4 }));

  // ---- the well itself, as concentric strokes of one line ----
  /** @param {string} d @param {number} width @param {string} colour @param {Record<string, string|number>} [extra] */
  const stroke = (d, width, colour, extra = {}) =>
    svg.appendChild(node("path", { d, fill: "none", stroke: colour, "stroke-width": width,
                                   "stroke-linecap": "butt", "stroke-linejoin": "round", ...extra }));
  stroke(line, wCement, "url(#wv-cem)");
  stroke(line, wCasing, "#8b98a5");
  stroke(line, wAnnulus, "#eef3f7", { id: "wv-annulus" });   // the casing-tubing annulus
  const toShoe = segment(0, spec.shoe_md);
  stroke(toShoe, wTubing, "#8b98a5", { id: "wv-tubing" });   // the tubing wall
  stroke(toShoe, bore, "#f4fafe", { id: "wv-bore" });        // the bore

  // the tubing above ground, into the tubing head.  The head is a shallow spool, not a tall block:
  // what matters above ground is the tree and the lift gas line, not the thickness of the flange.
  const HEAD_H = 24;
  const TREE_TOP = 16;           // the crown of the tree
  const WING_Y = 40;             // the flowline arm, and the wing valve on it
  const ARM_END = 88;            // how far the arm reaches out from the centre of the well
  const headTop = tree ? pad.t - HEAD_H : ground - 16;
  const up = `M${points[0][0]},${headTop} L${points[0][0]},${ground}`;
  stroke(up, wTubing, "#8b98a5");
  stroke(up, bore, "#f4fafe");

  // ---- the flow pattern, as a tint inside the bore ----
  // One stroke of the whole tubing, filled with a vertical gradient.  A band of flat colour for each
  // pattern drew a hard line across the tubing where one gave way to the next, and the flow does not
  // change like that: bubble becomes slug over a length of pipe, not at a depth.
  //
  // So the segments are first collapsed into RUNS of one pattern, and each run puts a single colour
  // stop at its own middle.  The gradient then shades from the middle of one run to the middle of
  // the next, which is a long, soft transition rather than a line - and above the gas lift valve,
  // where the injected gas changes the pattern, that is the smooth shading up to surface.  Where the
  // boundary actually falls is not lost: the tooltips are laid over the original intervals.
  /** @type {Set<string>} */
  const families = new Set();
  if (spec.pattern) {
    /** @type {{from: number, to: number, colour: string}[]} */
    const runs = [];
    for (let i = 0; i < spec.pattern.regime.length; i++) {
      if (spec.pattern.md[i] >= spec.shoe_md) continue;
      const fam = flowFamily(spec.pattern.regime[i]);
      if (fam) families.add(fam);
      const colour = fam ? FLOW_FAMILIES[fam].colour : "#9e9e9e";
      const from = spec.pattern.md[i];
      const to = Math.min(spec.pattern.md[i + 1], spec.shoe_md);
      const last = runs[runs.length - 1];
      if (last && last.colour === colour) last.to = to;
      else runs.push({ from, to, colour });
      const p = node("path", { d: segment(from, to), fill: "none", stroke: "transparent",
                               "stroke-width": bore, "stroke-linecap": "butt" });
      p.appendChild(node("title", {}, `${spec.pattern.regime[i]} at `
        + `${fmt(spec.toShown(from))}-${fmt(spec.toShown(spec.pattern.md[i + 1]))} `
        + `${spec.lengthUnit} MD`));
      svg.appendChild(p);
    }
    const yTop = headTop;
    const yBot = at(spec.shoe_md)[1];
    const span = Math.max(yBot - yTop, 1);
    const stops = runs.map((r) => ({
      off: Math.min(Math.max((at((r.from + r.to) / 2)[1] - yTop) / span, 0), 1),
      colour: r.colour,
    }));
    if (stops.length) {
      stops.sort((a, b) => a.off - b.off);
      // carry the end colours out to the ends of the pipe, so the top and the shoe are not blank
      const grad = node("linearGradient", { id: "wv-pattern", gradientUnits: "userSpaceOnUse",
                                            x1: points[0][0], y1: yTop, x2: points[0][0], y2: yBot });
      grad.appendChild(node("stop", { offset: 0, "stop-color": stops[0].colour }));
      for (const s of stops) {
        grad.appendChild(node("stop", { offset: s.off.toFixed(4), "stop-color": s.colour }));
      }
      grad.appendChild(node("stop", { offset: 1, "stop-color": stops[stops.length - 1].colour }));
      defs.appendChild(grad);
      const tint = node("path", { d: `${toShoe} M${points[0][0]},${yTop} L${points[0][0]},${Y(0)}`,
                                  fill: "none", stroke: "url(#wv-pattern)", "stroke-width": bore,
                                  "stroke-linecap": "butt", opacity: 0.32,
                                  "pointer-events": "none" });
      svg.appendChild(tint);
    }
  }

  // ---- the packer, above the top of the perforations ----
  const packPt = at(spec.packer_md);
  const packN = normalAt(spec.packer_md);
  // A packer seals the annulus, so it has to reach all the way from the outside of the tubing to the
  // inside of the casing with nothing left over on either side: any gap at all would be a leak path
  // and the drawing would be saying the opposite of what a packer does.
  const packLen = (wAnnulus - wTubing) / 2;
  for (const side of [-1, 1]) {
    const ix = packPt[0] + packN[0] * side * (wAnnulus + wTubing) / 4;
    const iy = packPt[1] + packN[1] * side * (wAnnulus + wTubing) / 4;
    svg.appendChild(node("rect", {
      class: "wv-packer",
      x: ix - packLen / 2, y: iy - 9, width: packLen, height: 18, rx: 2, fill: "#3f4b56",
      transform: `rotate(${Math.atan2(packN[1], packN[0]) * 180 / Math.PI} ${ix} ${iy})`,
    }));
  }

  // ---- the open tubing shoe ----
  const shoePt = at(spec.shoe_md);
  const shoeN = normalAt(spec.shoe_md);
  for (const side of [-1, 1]) {
    svg.appendChild(node("path", {
      d: `M${shoePt[0] + shoeN[0] * side * (bore / 2 + 3)},${shoePt[1] + shoeN[1] * side * (bore / 2 + 3)} `
         + `l${shoeN[0] * side * 4},${shoeN[1] * side * 4}`,
      stroke: "#5d6b78", "stroke-width": 2.5, "stroke-linecap": "round" }));
  }

  // ---- the perforations ----
  /** @type {{x: number, y: number, nx: number, ny: number, side: number}[]} */
  const perfs = [];
  const nPerf = Math.max(4, Math.min(9, Math.round((perf_md - spec.perf_top) / 60)));
  for (let i = 0; i < nPerf; i++) {
    const md = spec.perf_top + (perf_md - spec.perf_top) * (i + 0.5) / nPerf;
    const p = at(md);
    const n = normalAt(md);
    for (const side of [-1, 1]) {
      const from = wCasing / 2 - 1;
      const to = wCement / 2 + 13;
      svg.appendChild(node("path", {
        d: `M${p[0] + n[0] * side * from},${p[1] + n[1] * side * from} `
           + `L${p[0] + n[0] * side * to},${p[1] + n[1] * side * to}`,
        stroke: "#8c3b2e", "stroke-width": 2.2, "stroke-linecap": "round" }));
      perfs.push({ x: p[0] + n[0] * side * to, y: p[1] + n[1] * side * to,
                   nx: -n[0] * side, ny: -n[1] * side, side });
    }
  }
  // the bottom of the casing
  const endPt = at(perf_md);
  const endN = normalAt(perf_md);
  svg.appendChild(node("path", {
    d: `M${endPt[0] - endN[0] * wCasing / 2},${endPt[1] - endN[1] * wCasing / 2} `
       + `L${endPt[0] + endN[0] * wCasing / 2},${endPt[1] + endN[1] * wCasing / 2}`,
    stroke: "#3f4b56", "stroke-width": 2.5 }));

  // ---- the gas lift valve ----
  // The valve is in a mandrel bolted to the tubing, so it sits hard against the outside of the
  // tubing wall - not floating in the annulus - and its port goes through that wall into the bore.
  // It is on the same side as the lift gas, so the gas coming down the annulus arrives at it.
  let glPt = null;
  let glCentre = null;
  const GL_W = 13;
  if (spec.gl_md !== null && spec.gl_md > 0 && spec.gl_md < spec.shoe_md) {
    glPt = at(spec.gl_md);
    const n = normalAt(spec.gl_md);
    const off = wTubing / 2 + GL_W / 2;                  // flush against the tubing wall
    const cx = glPt[0] + n[0] * liftSide * off;
    const cy = glPt[1] + n[1] * liftSide * off;
    glCentre = [cx, cy];
    const angle = Math.atan2(n[1], n[0]) * 180 / Math.PI;
    // the port through the tubing wall, drawn first so the valve body covers its outer end
    svg.appendChild(node("path", {
      d: `M${glPt[0] + n[0] * liftSide * (wTubing / 2)},${glPt[1] + n[1] * liftSide * (wTubing / 2)} `
         + `L${glPt[0] + n[0] * liftSide * (bore / 2 - 4)},${glPt[1] + n[1] * liftSide * (bore / 2 - 4)}`,
      stroke: GAS, "stroke-width": 3.4, "stroke-linecap": "round" }));
    svg.appendChild(node("rect", { id: "wv-glvalve",
                                   x: cx - GL_W / 2, y: cy - 9, width: GL_W, height: 18, rx: 2.5,
                                   fill: GAS, stroke: GAS_DARK, "stroke-width": 1,
                                   transform: `rotate(${angle} ${cx} ${cy})` }));
  }

  // ---- the Christmas tree, and the lift gas entering the annulus ----
  if (tree) {
    const bx = points[0][0];
    const headY = headTop;
    const g = node("g");
    const steel = { fill: "#7d8a96", stroke: "#5d6b78", "stroke-width": 1 };
    // the tubing head: a shallow spool across the top of the casing and the annulus
    g.appendChild(node("rect", { x: bx - wCasing / 2 - 8, y: headY, width: wCasing + 16,
                                 height: ground - headY, rx: 2, ...steel }));
    // The body of the tree carries the same bore as the tubing, because the produced fluid flows up
    // through it: drawn narrower than the tubing, the drops would have run outside the steel.
    g.appendChild(node("rect", { x: bx - wTubing / 2, y: TREE_TOP, width: wTubing,
                                 height: headY - TREE_TOP, ...steel }));
    g.appendChild(node("rect", { x: bx - bore / 2, y: TREE_TOP, width: bore,
                                 height: headY - TREE_TOP, fill: "#f4fafe" }));
    g.appendChild(node("rect", { x: bx - wTubing / 2 - 5, y: TREE_TOP - 9, width: wTubing + 10,
                                 height: 10, rx: 2, fill: "#5d6b78" }));
    // The flowline arm out to the wing valve, with a bore wide enough to hold the biggest bubble
    // the tubing can send through it, and no wider: the arm has to leave room for the master valve
    // between itself and the head.
    const armH = Math.min(wTubing, 28);
    const armBore = Math.min(bore, 22);
    g.appendChild(node("rect", { x: bx + wTubing / 2 - 1, y: WING_Y - armH / 2,
                                 width: ARM_END - wTubing / 2, height: armH, ...steel }));
    g.appendChild(node("rect", { x: bx + wTubing / 2 - 1, y: WING_Y - armBore / 2,
                                 width: ARM_END - wTubing / 2 - 2, height: armBore, fill: "#f4fafe" }));
    g.appendChild(node("rect", { x: bx + ARM_END - 1, y: WING_Y - 12, width: 9, height: 24, rx: 2,
                                 fill: "#5d6b78" }));
    svg.appendChild(g);

    /** @param {number} x @param {number} y @param {boolean} horizontal @param {string} id @param {boolean} open */
    const valve = (x, y, horizontal, id, open) => {
      const gg = node("g", { id });
      const s = 9;
      gg.appendChild(node("polygon", {
        points: horizontal ? `${x - s},${y - s} ${x - s},${y + s} ${x + s},${y - s} ${x + s},${y + s}`
                           : `${x - s},${y - s} ${x + s},${y - s} ${x - s},${y + s} ${x + s},${y + s}`,
        fill: "#fff", stroke: "#5d6b78", "stroke-width": 1.5 }));
      gg.appendChild(node("circle", { class: "vstate", cx: x, cy: y, r: 4.2,
                                      fill: open ? "#1a7f37" : "#d1242f" }));
      return gg;
    };
    // the master valve goes between the flowline arm and the head, which is where it is on a tree
    svg.appendChild(valve(bx, Math.min((WING_Y + headY) / 2 + 6, headY - 10), false, "wv-master",
                          spec.masterOpen !== false));
    svg.appendChild(valve(bx + 50, WING_Y, true, "wv-wing", spec.chokeOpen !== false));

    // The lift gas line comes in just under the tubing head, which is where the casing spool is and
    // so where the annulus is open to it.  The arrow stops at the cement, and the gas carries on
    // down the annulus from there.
    if (glPt) {
      const portY = ground + 14;                        // just under the head, into the annulus
      const tip = bx - wAnnulus / 2 + 2;          // right up to the annulus it is feeding
      const turn = bx - wCement / 2 - 13;
      const inX = Math.max(turn - 44, 4);
      svg.appendChild(node("path", {
        d: `M${inX},28 L${turn},28 L${turn},${portY} L${tip},${portY}`,
        fill: "none", stroke: GAS, "stroke-width": 3, "stroke-linejoin": "round",
        "stroke-linecap": "round" }));
      svg.appendChild(node("path", { d: `M${tip - 9},${portY - 4.5} L${tip},${portY} `
                                        + `L${tip - 9},${portY + 4.5}`, fill: GAS }));
      svg.appendChild(node("text", { x: inX, y: 20, class: "wv-lbl", fill: GAS_DARK },
                                   "lift gas in"));
    }
  }

  // ---- the depth scale ----
  // The scale is TRUE VERTICAL DEPTH, which is both what the chart beside it plots against and what
  // the ticks have to be if a depth is to be at the same height in the two panels.  It used to
  // label measured depths at their true vertical heights, which for a deviated well is two
  // different numbers in one place.
  const stepFt = maxTvd > 12000 ? 4000 : maxTvd > 6000 ? 2000 : maxTvd > 2500 ? 1000 : 500;
  const axisX = earthL - 4;
  for (let md = 0; md <= maxTvd + 1; md += stepFt) {
    const y = Y(md);
    svg.appendChild(node("line", { x1: axisX - 5, y1: y, x2: axisX, y2: y, stroke: "#9aa7b2",
                                   "stroke-width": 0.8 }));
    svg.appendChild(node("text", { x: axisX - 8, y: y + 3, class: "wv-depth",
                                   "text-anchor": "end" }, fmt(spec.toShown(md))));
  }
  svg.appendChild(node("line", { x1: axisX, y1: ground, x2: axisX, y2: Y(maxTvd),
                                 stroke: "#c3ccd4", "stroke-width": 0.8 }));
  // the title sits above the scale and runs rightwards, which is the only way it fits once the
  // numbers are large enough to read
  svg.appendChild(node("text", { x: 2, y: ground - 9, class: "wv-depth" },
                               `TVD, ${spec.lengthUnit}`));

  // ---- the labels ----
  if (!compact) {
    const labelX = W - pad.r + 18;
    /** @type {[number, number, string][]} */
    const rows = [];
    if (tree) rows.push([points[0][0] + 16, 20, "Christmas tree"]);
    rows.push([points[0][0] + wCasing / 2, ground - 6, "Tubing head"]);
    rows.push([at(perf_md * 0.3)[0] + wCement / 2, at(perf_md * 0.3)[1], "Cement sheath"]);
    rows.push([at(perf_md * 0.42)[0] + wCasing / 2, at(perf_md * 0.42)[1], "Production casing"]);
    rows.push([at(perf_md * 0.54)[0] + wAnnulus / 2 - 4, at(perf_md * 0.54)[1], "Annulus"]);
    rows.push([at(perf_md * 0.66)[0] + bore / 2, at(perf_md * 0.66)[1], "Production tubing"]);
    // the leader starts at the valve itself, on whichever side the lift gas is, even though that
    // means crossing the tubing: a leader that stopped short of it would point at nothing
    if (glCentre) rows.push([glCentre[0], glCentre[1], "Gas lift valve"]);
    rows.push([packPt[0] + wAnnulus / 2 - 4, packPt[1], "Production packer"]);
    rows.push([shoePt[0] + bore / 2, shoePt[1] + 4, "Open tubing shoe"]);
    rows.push([at((spec.perf_top + perf_md) / 2)[0] + wCement / 2 + 12,
               at((spec.perf_top + perf_md) / 2)[1], "Perforations"]);
    let lastY = -99;
    for (const [fx, fy, text] of rows) {
      const y = Math.max(fy, lastY + 14);
      lastY = y;
      svg.appendChild(node("path", { d: `M${fx},${fy} L${labelX - 7},${y}`, stroke: "#b6c0c9",
                                     "stroke-width": 0.8, fill: "none" }));
      svg.appendChild(node("circle", { cx: fx, cy: fy, r: 1.6, fill: "#b6c0c9" }));
      svg.appendChild(node("text", { x: labelX, y: y + 3.2, class: "wv-lbl" }, text));
    }
  }

  // ---- the lines the fluid runs along, and the layers it is drawn in ----
  // up the tubing and, when the tree is drawn, out through the wing valve - stopping at the end of
  // the flowline stub, so nothing flies off into open space
  const produced = node("path", { id: "wv-flowline", d: tree
    ? `${segment(spec.shoe_md, 0)} L${points[0][0]},${WING_Y} L${points[0][0] + ARM_END + 4},${WING_Y}`
    : `${segment(spec.shoe_md, 0)} L${points[0][0]},${headTop}`,
    fill: "none", stroke: "#1f6feb", "stroke-width": 1.6, "stroke-dasharray": "6 8", opacity: 0.3 });
  svg.appendChild(produced);
  // the lift gas: down the annulus on one side, then across into the tubing
  // The gas runs down the middle of the annulus on the side the port is on and STOPS at the gas lift
  // valve: the bubbles arrive at the valve and end there, because that is where the gas leaves the
  // annulus.  What happens on the other side of the valve is the tubing's business, and the tubing
  // shows it by the bubbles above the valve growing.
  let liftLine = null;
  if (glPt && glCentre) {
    const n = normalAt(spec.gl_md ?? 0);
    const offset = (wTubing + wAnnulus) / 4;
    const annulus = spec.md.map((_, i) => {
      const nn = normalAt(spec.md[i]);
      return [points[i][0] + nn[0] * liftSide * offset, points[i][1] + nn[1] * liftSide * offset];
    }).filter((_, i) => spec.md[i] <= (spec.gl_md ?? 0));
    annulus.unshift([points[0][0] + normalAt(0)[0] * liftSide * offset, ground + 14]);
    annulus.push([glPt[0] + n[0] * liftSide * offset, glPt[1]]);
    annulus.push([glCentre[0], glCentre[1]]);                      // into the valve, and no further
    liftLine = node("path", { id: "wv-liftline",
      d: annulus.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" "),
      fill: "none", stroke: GAS, "stroke-width": 1.5, "stroke-dasharray": "4 6", opacity: 0.4 });
    svg.appendChild(liftLine);
  }

  svg.appendChild(node("g", { id: "wv-inflow" }));
  svg.appendChild(node("g", { id: "wv-lift" }));
  svg.appendChild(node("g", { id: "wv-fluid" }));

  return { svg, spec, produced, liftLine, perfs, shoePt, glPt, bore,
           glFraction: glPt ? produced.getTotalLength() * 0 : 0, families };
}

/**
 * Animate the fluid in a drawing built by render().  Returns a handle with stop() and update(spec).
 * @param {ReturnType<typeof render>} view
 */
export function animate(view) {
  const PRODUCED = 44;
  const INFLOW = 14;
  const LIFT = 18;
  let scene = view;
  let running = true;

  /** @type {any[]} */
  let produced = [];
  /** @type {any[]} */
  let inflow = [];
  /** @type {any[]} */
  let lift = [];
  let dash = 0;
  let liftDash = 0;

  function build() {
    const s = scene.spec;
    const len = scene.produced.getTotalLength();
    // where along the produced line the gas lift valve is: everything after it carries lift gas
    let glAt = 1.1;
    if (scene.glPt && s.gl_md !== null) {
      glAt = (s.shoe_md - s.gl_md) / Math.max(s.shoe_md, 1);       // the line runs shoe -> surface
    }
    const gasShare = Math.min(0.5, s.gor / 3200);
    produced = [];
    for (let i = 0; i < PRODUCED; i++) {
      const r = Math.random();
      const phase = r < gasShare ? "gas" : r < gasShare + (1 - s.water_cut) * (1 - gasShare)
        ? "oil" : "water";
      produced.push({ s: len * i / PRODUCED, phase, glAt,
                      jitter: (Math.random() - 0.5) * (scene.bore - 6),
                      base: phase === "gas" ? 1.7 + Math.random() * 1.1 : 2.4 + Math.random() * 1.1,
                      wobble: Math.random() * 6.28 });
    }
    inflow = [];
    for (let i = 0; i < INFLOW; i++) {
      const perf = scene.perfs[i % scene.perfs.length];
      inflow.push({ perf, t: Math.random(), speedScale: 0.6 + Math.random() * 0.8,
                    phase: Math.random() < s.water_cut ? "water" : "oil",
                    size: 2.4 + Math.random() * 0.9 });
    }
    lift = [];
    if (scene.liftLine) {
      const liftLen = scene.liftLine.getTotalLength();
      for (let i = 0; i < LIFT; i++) {
        lift.push({ s: liftLen * i / LIFT, size: 1.6 + Math.random() * 0.9 });
      }
    }
    for (const [id, list, colour] of [["wv-fluid", produced, ""],
                                      ["wv-inflow", inflow, ""],
                                      ["wv-lift", lift, PHASE_COLOURS.gas]]) {
      const host = scene.svg.querySelector(`#${id}`);
      if (!host) continue;
      host.textContent = "";
      for (const p of /** @type {any[]} */ (list)) {
        const c = node("circle", { r: Number(p.size ?? p.base),
                                   fill: String(colour || PHASE_COLOURS[p.phase]) });
        p.node = c;
        host.appendChild(c);
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
    const speed = s.flowing ? s.speed : 0;
    const len = scene.produced.getTotalLength();

    dash = (dash - speed * dt * 0.5) % 14;
    scene.produced.setAttribute("stroke-dashoffset", String(dash));
    scene.produced.setAttribute("opacity", s.flowing ? "0.3" : "0.1");

    for (const p of produced) {
      p.s = (p.s + speed * dt) % len;
      const pt = scene.produced.getPointAtLength(p.s);
      p.wobble += dt * 3.4;
      const frac = p.s / len;                          // 0 at the shoe, 1 at surface
      // Above the gas lift valve the gas is injected gas as well as solution gas, so the bubbles
      // are bigger and there are more of them; and every bubble keeps growing towards surface as
      // the pressure falls, which is what gas actually does on the way up.
      const lifted = scene.glPt && frac > p.glAt;
      const expansion = 1 + 0.95 * frac ** 1.5;
      const injected = lifted ? 1.35 : 1.0;
      // a bubble can grow until it nearly fills the bore and no further, or it would spill out of
      // the pipe it is supposed to be inside
      const r = p.phase === "gas"
        ? Math.min(p.base * expansion * injected, scene.bore * 0.24)
        : p.base;
      p.node.setAttribute("r", String(r));
      // How far off the centre line the drop sits.  It is then held inside the pipe: a drop whose
      // edge went past the bore would be drawn in the steel, or outside the well altogether, and a
      // bubble big enough to fill the bore has nowhere to wander to.
      const across = p.jitter * (p.phase === "gas" ? 0.8 : 1)
        + Math.sin(p.wobble) * (p.phase === "gas" ? 2.6 : 0.8);
      const limit = Math.max(scene.bore / 2 - r - 1.5, 0);
      p.node.setAttribute("cx", String(pt.x + Math.max(-limit, Math.min(limit, across))));
      p.node.setAttribute("cy", String(pt.y));
      p.node.setAttribute("opacity", s.flowing ? (p.phase === "gas" ? "0.95" : "0.85") : "0.12");
    }

    // the fluid coming in through the perforations, turning up into the open shoe
    for (const p of inflow) {
      p.t += dt * (s.flowing ? 0.45 : 0) * p.speedScale;
      if (p.t > 1) p.t -= 1;
      // out of the formation, in through the perforation, then along to the shoe
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

    if (scene.liftLine) {
      const liftLen = scene.liftLine.getTotalLength();
      const on = s.flowing && s.gl_md !== null;
      liftDash = (liftDash - (on ? 60 : 0) * dt) % 10;
      scene.liftLine.setAttribute("stroke-dashoffset", String(liftDash));
      scene.liftLine.setAttribute("opacity", on ? "0.4" : "0");
      for (const p of lift) {
        if (!on) {
          p.node.setAttribute("opacity", "0");
          continue;
        }
        p.s = (p.s + 52 * dt) % liftLen;
        const pt = scene.liftLine.getPointAtLength(p.s);
        p.node.setAttribute("cx", String(pt.x));
        p.node.setAttribute("cy", String(pt.y));
        p.node.setAttribute("opacity", "0.9");
      }
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
