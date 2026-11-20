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
 * @property {boolean} [masterOpen] whether the master valves are drawn open
 * @property {boolean} [chokeOpen]  whether the production wing valve is drawn open
 */

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
export const PHASE_COLOURS = {
  oil: "#22c55e",
  water: "#3b82f6",
  gas: "#ef4444",           // the mixed stream above the gas lift valve
  liftGas: "#ff6b4a",       // injected
  solutionGas: "#dc2626",   // formation gas, below the valve
};

const STEEL = "#64748b";
const STEEL_DARK = "#334155";
const SEAL = "#dc2626";

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

  // ---- the tree, which has a fixed height whatever the well below it looks like ----
  const SWAB_Y = 21;            // the swab valve, on top of the stem
  const TEE_Y = 44;             // the tee, and the production wing arm out of it
  const UPPER_MASTER_Y = 72;    // upper master valve
  const LOWER_MASTER_Y = 98;    // lower master valve, just above the wellhead
  const ARM_END = 92;           // how far the wing arm reaches out from the centre of the well

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
  const pad = { t: spec.padTop ?? (tree ? 132 : 34), b: spec.padBottom ?? 26,
                l: compact ? 40 : 74, r: compact ? 14 : 152 };
  const half = Math.min(13 + (spec.tubing_id - 2) * 2.2, 22);     // half the bore, in pixels
  const bore = half * 2;
  const wTubing = bore + 7;
  const wAnnulus = bore + 34;
  const wCasing = bore + 42;
  const wCement = bore + 58;

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
  const ground = Y(0);
  const bx = X(0);

  const points = spec.md.map((_, i) => [X(reach[i]), Y(spec.tvd[i])]);
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" ");

  // The tubing carries on above the wellhead, up the tree to the tee.  That length is given a
  // NEGATIVE measured depth, so one set of helpers covers the whole string and the fluid can be
  // drawn flowing up through the tree without a second way of finding where things are.
  const topMd = tree ? (TEE_Y - ground) / scaleY : 0;

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
  /**
   * How far the well leans at a depth, in degrees, so a shape drawn upright can be turned to sit
   * along the pipe.  A shape's own "up" is -y, which is what a vertical well returns as zero.
   * @param {number} md
   */
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
  const glOn = spec.gl_md !== null && spec.gl_md > 0 && spec.gl_md < spec.shoe_md;
  const glMd = glOn ? Number(spec.gl_md) : 0;
  // Which side of the well the lift gas is on.  The valve goes on the LEFT of the tubing, and the
  // injection wing at surface has to be on that same left-hand side or the drawing would have the
  // gas entering one side of the annulus and leaving the other.  Both are worked out from the line
  // itself, because which way the normal points depends on which way the well is heading.
  const liftSide = normalAt(glMd)[0] > 0 ? -1 : 1;
  const wingDir = Math.sign(normalAt(0)[0] * liftSide) || -1;   // -1 when that is screen-left

  const defs = node("defs");
  svg.appendChild(defs);

  // Gas shades by depth: deep crimson where it is all solution gas, blending just above the gas
  // lift valve into the lighter red of the mixed stream.  One gradient serves every gas shape in
  // the tubing, so a bubble is the right colour for the depth it happens to be at.
  const gasGrad = node("linearGradient", { id: "wv-gas", gradientUnits: "userSpaceOnUse",
                                           x1: bx, y1: at(topMd)[1], x2: bx, y2: at(perf_md)[1] });
  if (glOn) {
    const gy = at(glMd)[1];
    const total = at(perf_md)[1] - at(topMd)[1];
    const f = (gy - at(topMd)[1]) / Math.max(total, 1);
    gasGrad.appendChild(node("stop", { offset: 0, "stop-color": PHASE_COLOURS.gas }));
    gasGrad.appendChild(node("stop", { offset: Math.max(f - 0.12, 0).toFixed(3),
                                       "stop-color": PHASE_COLOURS.gas }));
    gasGrad.appendChild(node("stop", { offset: f.toFixed(3),
                                       "stop-color": PHASE_COLOURS.solutionGas }));
  } else {
    gasGrad.appendChild(node("stop", { offset: 0, "stop-color": PHASE_COLOURS.solutionGas }));
  }
  gasGrad.appendChild(node("stop", { offset: 1, "stop-color": PHASE_COLOURS.solutionGas }));
  defs.appendChild(gasGrad);
  const GASFILL = "url(#wv-gas)";

  // ---- the ground, and the reservoir ----
  // Flat, pale bands rather than hatching and stippling: this is a conceptual completion diagram,
  // and texture behind it only competes with the completion drawn on top.
  const earthL = Math.max(pad.l - 18, 2);
  const earthR = W - pad.r + 10;
  svg.appendChild(node("rect", { x: earthL, y: ground, width: earthR - earthL,
                                 height: H - ground - 6, fill: "#f6f1e7" }));
  const payY = at(spec.perf_top)[1];
  svg.appendChild(node("rect", { x: earthL, y: payY - 4, width: earthR - earthL,
                                 height: H - 6 - (payY - 4), fill: "#e4d3ad" }));
  svg.appendChild(node("line", { x1: earthL, y1: payY - 4, x2: earthR, y2: payY - 4,
                                 stroke: "#c9b287", "stroke-width": 1 }));
  svg.appendChild(node("line", { x1: earthL - 10, y1: ground, x2: earthR, y2: ground,
                                 stroke: "#94a3b8", "stroke-width": 1.4 }));

  // ---- the well itself, as concentric strokes of one line ----
  /** @param {string} d @param {number} width @param {string} colour @param {Record<string, string|number>} [extra] */
  const stroke = (d, width, colour, extra = {}) =>
    svg.appendChild(node("path", { d, fill: "none", stroke: colour, "stroke-width": width,
                                   "stroke-linecap": "butt", "stroke-linejoin": "round", ...extra }));
  stroke(line, wCement, "#d8d2c4");                          // cement behind the casing
  stroke(line, wCasing, STEEL);                              // the casing wall
  stroke(line, wAnnulus, "#ffffff", { id: "wv-annulus" });   // the casing-tubing annulus

  // ---- what is standing in the annulus ----
  // With gas lift on the annulus is a pressurised gas column from surface down to the valve, and
  // dead completion fluid below it: that is an unloaded annulus.  With gas lift off there is no gas
  // in it at all and the whole thing is dead fluid.
  if (glOn) {
    stroke(segment(0, glMd), wAnnulus - 2, PHASE_COLOURS.liftGas,
           { id: "wv-anngas", opacity: 0.72 });
    stroke(segment(glMd, spec.packer_md), wAnnulus - 2, PHASE_COLOURS.water,
           { id: "wv-anndead", opacity: 0.45 });
  } else {
    stroke(segment(0, spec.packer_md), wAnnulus - 2, PHASE_COLOURS.water,
           { id: "wv-anndead", opacity: 0.45 });
  }

  // below the packer the casing is full of what the reservoir is giving, which is where the
  // tailpipe has its open end
  stroke(segment(spec.packer_md, perf_md), wAnnulus - 2, PHASE_COLOURS.oil,
         { id: "wv-rathole", opacity: 0.3 });

  const toShoe = segment(topMd, spec.shoe_md);
  stroke(toShoe, wTubing, STEEL, { id: "wv-tubing" });       // the tubing wall
  stroke(toShoe, bore, "#ffffff", { id: "wv-bore" });        // the bore

  // ---- the flow regimes inside the tubing ----
  // The pattern the correlation reports at each depth is DRAWN, not tinted: the liquid it is
  // flowing in, and over that the gas in whatever shape that regime takes.  Neighbouring intervals
  // reporting the same pattern are first collapsed into one run, so a regime is one continuous
  // stretch of pipe rather than thirty-odd identical slices.
  /** @type {{from: number, to: number, family: string, regime: string, px: number}[]} */
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
  bands[0].from = topMd;          // the shallowest band carries on up the tree, as the fluid does
  for (const b of bands) {
    b.px = Math.abs(at(b.to)[1] - at(b.from)[1]) + Math.abs(at(b.to)[0] - at(b.from)[0]);
  }

  for (const b of bands) {
    const d = segment(b.from, b.to);
    if (b.family === "annular" || b.family === "gas") {
      // a gas core, with the liquid carried as a film on the wall
      stroke(d, bore, GASFILL, { opacity: 0.85, class: "wv-fill" });
      if (b.family === "annular") {
        for (const side of [-1, 1]) {
          svg.appendChild(node("path", { class: "wv-film", d: filmPath(b, side),
                                         fill: "none", stroke: PHASE_COLOURS.oil, "stroke-width": bore * 0.15,
                                         "stroke-linecap": "butt", opacity: 0.85 }));
        }
      }
    } else {
      stroke(d, bore, PHASE_COLOURS.oil, { opacity: 0.5, class: "wv-fill" });
    }
  }

  /**
   * The wavy inner edge of the liquid film in an annular section, down one wall.  It is a real
   * path along the well rather than a straight band, so it waves on a deviated well too.
   * @param {{from: number, to: number}} b @param {number} side
   */
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

  // the hover labels, laid over the intervals the correlation actually reported
  if (spec.pattern) {
    for (let i = 0; i < spec.pattern.regime.length; i++) {
      const from = spec.pattern.md[i];
      if (from >= spec.shoe_md) continue;
      const to = Math.min(spec.pattern.md[i + 1] ?? spec.shoe_md, spec.shoe_md);
      const p = node("path", { class: "wv-hit", d: segment(from, to), fill: "none",
                               stroke: "transparent", "stroke-width": bore + 6,
                               "stroke-linecap": "butt" });
      const fam = flowFamily(spec.pattern.regime[i]);
      p.appendChild(node("title", {}, `${fam ? FLOW_FAMILIES[fam].label : spec.pattern.regime[i]}`
        + ` flow, ${fmt(spec.toShown(from))}-${fmt(spec.toShown(to))} ${spec.lengthUnit} MD`));
      svg.appendChild(p);
    }
  }

  // ---- the production packer, sealing tubing to casing above the perforations ----
  /**
   * A seal across the annulus: the red crossed block that means "nothing gets past here".
   * @param {number} md @param {string} cls
   */
  const sealAcross = (md, cls) => {
    const p = at(md);
    const n = normalAt(md);
    const len = (wAnnulus - wTubing) / 2;
    const angle = Math.atan2(n[1], n[0]) * 180 / Math.PI;
    for (const side of [-1, 1]) {
      const cx = p[0] + n[0] * side * (wAnnulus + wTubing) / 4;
      const cy = p[1] + n[1] * side * (wAnnulus + wTubing) / 4;
      const g = node("g", { class: cls, transform: `rotate(${angle} ${cx} ${cy})` });
      g.appendChild(node("rect", { x: cx - len / 2, y: cy - 9, width: len, height: 18,
                                   fill: "#fee2e2", stroke: SEAL, "stroke-width": 1.6 }));
      g.appendChild(node("line", { x1: cx - len / 2, y1: cy - 9, x2: cx + len / 2, y2: cy + 9,
                                   stroke: SEAL, "stroke-width": 1.4 }));
      g.appendChild(node("line", { x1: cx - len / 2, y1: cy + 9, x2: cx + len / 2, y2: cy - 9,
                                   stroke: SEAL, "stroke-width": 1.4 }));
      svg.appendChild(g);
    }
    return p;
  };
  const packPt = sealAcross(spec.packer_md, "wv-packer");

  // ---- the open tubing shoe, hanging below the packer in the perforated interval ----
  const shoePt = at(spec.shoe_md);
  const shoeN = normalAt(spec.shoe_md);
  for (const side of [-1, 1]) {
    svg.appendChild(node("path", {
      d: `M${shoePt[0] + shoeN[0] * side * (bore / 2 + 3.5)},`
         + `${shoePt[1] + shoeN[1] * side * (bore / 2 + 3.5)} `
         + `l${shoeN[0] * side * 4},${shoeN[1] * side * 4}`,
      stroke: STEEL_DARK, "stroke-width": 2.5, "stroke-linecap": "round" }));
  }

  // ---- the perforations, through both casing walls ----
  /** @type {{x: number, y: number, nx: number, ny: number}[]} */
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
                   nx: -n[0] * side, ny: -n[1] * side });
    }
  }
  // ---- the casing shoe at total depth ----
  const endPt = at(perf_md);
  const endN = normalAt(perf_md);
  svg.appendChild(node("path", {
    d: `M${endPt[0] - endN[0] * wCasing / 2},${endPt[1] - endN[1] * wCasing / 2} `
       + `L${endPt[0] + endN[0] * wCasing / 2},${endPt[1] + endN[1] * wCasing / 2}`,
    stroke: STEEL_DARK, "stroke-width": 2.5 }));
  for (const side of [-1, 1]) {
    const o = wCasing / 2 - 1;
    const ax = endPt[0] + endN[0] * side * o;
    const ay = endPt[1] + endN[1] * side * o;
    const ix = endPt[0] + endN[0] * side * (o - 9);
    const iy = endPt[1] + endN[1] * side * (o - 9);
    const dir = [-endN[1], endN[0]];                    // along the well, upwards
    svg.appendChild(node("polygon", {
      points: `${ax},${ay} ${ix},${iy} ${ax - dir[0] * 11},${ay - dir[1] * 11}`,
      fill: STEEL_DARK }));
  }

  // ---- the gas lift valve and its mandrel ----
  // The valve is in a mandrel bolted to the tubing, so it sits hard against the outside of the
  // tubing wall - not floating in the annulus - and its port goes through that wall into the bore.
  let glCentre = null;
  const GL_W = 13;
  if (glOn) {
    const p = at(glMd);
    const n = normalAt(glMd);
    const off = wTubing / 2 + GL_W / 2;                  // flush against the tubing wall
    const cx = p[0] + n[0] * liftSide * off;
    const cy = p[1] + n[1] * liftSide * off;
    glCentre = [cx, cy];
    const angle = Math.atan2(n[1], n[0]) * 180 / Math.PI;
    svg.appendChild(node("path", {
      d: `M${p[0] + n[0] * liftSide * (wTubing / 2)},${p[1] + n[1] * liftSide * (wTubing / 2)} `
         + `L${p[0] + n[0] * liftSide * (bore / 2 - 4)},${p[1] + n[1] * liftSide * (bore / 2 - 4)}`,
      stroke: PHASE_COLOURS.liftGas, "stroke-width": 3.4, "stroke-linecap": "round" }));
    svg.appendChild(node("rect", { id: "wv-glvalve",
                                   x: cx - GL_W / 2, y: cy - 9, width: GL_W, height: 18, rx: 2,
                                   fill: "#ffffff", stroke: PHASE_COLOURS.liftGas, "stroke-width": 2,
                                   transform: `rotate(${angle} ${cx} ${cy})` }));
  }

  // ---- the wellhead: the annulus seal, and the gas lift injection wing below it ----
  /**
   * The standard circle-and-cross valve symbol.  Open is drawn in full ink, shut is greyed and
   * filled in, so a glance says which it is.
   * @param {number} x @param {number} y @param {string} id @param {boolean} open
   */
  const valveSymbol = (x, y, id, open) => {
    const g = node("g", { id, class: "wv-valve" });
    const r = 8.5;
    const ink = open ? STEEL_DARK : "#9aa7b4";
    g.appendChild(node("circle", { cx: x, cy: y, r, fill: open ? "#ffffff" : "#e2e8f0",
                                   stroke: ink, "stroke-width": 1.8 }));
    const k = r * 0.707;
    g.appendChild(node("line", { x1: x - k, y1: y - k, x2: x + k, y2: y + k,
                                 stroke: ink, "stroke-width": 1.8 }));
    g.appendChild(node("line", { x1: x - k, y1: y + k, x2: x + k, y2: y - k,
                                 stroke: ink, "stroke-width": 1.8 }));
    return g;
  };

  if (tree) {
    // the annulus is sealed at surface, around the tubing: that is why the lift gas needs its own
    // way in, a little below
    const len = (wAnnulus - wTubing) / 2;
    for (const side of [-1, 1]) {
      const cx = bx + side * (wAnnulus + wTubing) / 4;
      const g = node("g", { class: "wv-wellhead-seal" });
      g.appendChild(node("rect", { x: cx - len / 2, y: ground - 9, width: len, height: 18,
                                   fill: "#fee2e2", stroke: SEAL, "stroke-width": 1.6 }));
      g.appendChild(node("line", { x1: cx - len / 2, y1: ground - 9, x2: cx + len / 2,
                                   y2: ground + 9, stroke: SEAL, "stroke-width": 1.4 }));
      g.appendChild(node("line", { x1: cx - len / 2, y1: ground + 9, x2: cx + len / 2,
                                   y2: ground - 9, stroke: SEAL, "stroke-width": 1.4 }));
      svg.appendChild(g);
    }

    if (glOn) {
      // the injection wing: a side outlet into the annulus, just under the seal
      const portY = ground + 30;
      const tip = bx + wingDir * wAnnulus / 2;
      const dir = wingDir;
      const outX = tip + dir * 70;
      svg.appendChild(node("line", { x1: outX, y1: portY, x2: tip, y2: portY,
                                     stroke: PHASE_COLOURS.liftGas, "stroke-width": 3,
                                     "stroke-linecap": "round" }));
      svg.appendChild(node("polygon", {
        points: `${tip},${portY} ${tip - dir * 10},${portY - 5} ${tip - dir * 10},${portY + 5}`,
        fill: PHASE_COLOURS.liftGas }));
      svg.appendChild(valveSymbol(tip + dir * 42, portY, "wv-annwing", true));
      svg.appendChild(node("text", { x: outX, y: portY - 15, class: "wv-lbl", fill: "#b23c20",
                                     "text-anchor": dir < 0 ? "start" : "end" }, "lift gas in"));
    }
  }

  // ---- the Christmas tree ----
  if (tree) {
    const g = node("g");
    const steel = { fill: "#cbd5e1", stroke: STEEL, "stroke-width": 1.2 };
    // the stem, carrying the tubing bore on up from the wellhead
    g.appendChild(node("rect", { x: bx - wTubing / 2, y: SWAB_Y, width: wTubing,
                                 height: ground - SWAB_Y, ...steel }));
    // the wing arm out of the tee
    const armH = Math.min(wTubing, 30);
    g.appendChild(node("rect", { x: bx + wTubing / 2 - 1, y: TEE_Y - armH / 2,
                                 width: ARM_END - wTubing / 2, height: armH, ...steel }));
    g.appendChild(node("rect", { x: bx - wTubing / 2 - 5, y: SWAB_Y - 8, width: wTubing + 10,
                                 height: 9, rx: 1.5, fill: STEEL }));
    svg.appendChild(g);
    // the bores: the stem above the tee carries the same fluid as the arm, so both are filled with
    // whatever the shallowest regime in the tubing is
    const shallow = bands[0];
    const fill = shallow.family === "annular" || shallow.family === "gas"
      ? GASFILL : PHASE_COLOURS.oil;
    const fillOp = shallow.family === "annular" || shallow.family === "gas" ? 0.85 : 0.5;
    const armBore = Math.min(bore, 22);
    svg.appendChild(node("rect", { id: "wv-armbore", x: bx + wTubing / 2 - 1,
                                   y: TEE_Y - armBore / 2, width: ARM_END - wTubing / 2 - 2,
                                   height: armBore, fill, opacity: fillOp }));
    svg.appendChild(node("rect", { x: bx - bore / 2, y: SWAB_Y, width: bore,
                                   height: at(topMd)[1] - SWAB_Y, fill, opacity: fillOp }));
    // and the outward flow arrow off the end of the arm
    const ax = bx + ARM_END;
    svg.appendChild(node("line", { x1: ax, y1: TEE_Y, x2: ax + 26, y2: TEE_Y,
                                   stroke: STEEL_DARK, "stroke-width": 2.4 }));
    svg.appendChild(node("polygon", { id: "wv-outflow",
      points: `${ax + 36},${TEE_Y} ${ax + 24},${TEE_Y - 6} ${ax + 24},${TEE_Y + 6}`,
      fill: STEEL_DARK }));

    svg.appendChild(valveSymbol(bx, SWAB_Y, "wv-swab", spec.masterOpen !== false));
    svg.appendChild(valveSymbol(bx + 52, TEE_Y, "wv-wing", spec.chokeOpen !== false));
    svg.appendChild(valveSymbol(bx, UPPER_MASTER_Y, "wv-master", spec.masterOpen !== false));
    svg.appendChild(valveSymbol(bx, LOWER_MASTER_Y, "wv-lower-master", spec.masterOpen !== false));
  }

  // ---- the depth scale ----
  // The scale is TRUE VERTICAL DEPTH, which is both what the chart beside it plots against and what
  // the ticks have to be if a depth is to be at the same height in the two panels.
  const stepFt = maxTvd > 12000 ? 4000 : maxTvd > 6000 ? 2000 : maxTvd > 2500 ? 1000 : 500;
  const axisX = earthL - 4;
  for (let d = 0; d <= maxTvd + 1; d += stepFt) {
    const y = Y(d);
    svg.appendChild(node("line", { x1: axisX - 5, y1: y, x2: axisX, y2: y, stroke: "#94a3b8",
                                   "stroke-width": 0.8 }));
    svg.appendChild(node("text", { x: axisX - 8, y: y + 3, class: "wv-depth",
                                   "text-anchor": "end" }, fmt(spec.toShown(d))));
  }
  svg.appendChild(node("line", { x1: axisX, y1: ground, x2: axisX, y2: Y(maxTvd),
                                 stroke: "#cbd5e1", "stroke-width": 0.8 }));
  svg.appendChild(node("text", { x: 2, y: ground - 14, class: "wv-depth" },
                               `TVD, ${spec.lengthUnit}`));

  // ---- the labels ----
  if (!compact) {
    const labelX = W - pad.r + 18;
    /** @type {[number, number, string][]} */
    const rows = [];
    if (tree) {
      rows.push([bx + wTubing / 2, SWAB_Y, "Swab valve"]);
      rows.push([bx + 52, TEE_Y + 9, "Production wing"]);
      rows.push([bx + wTubing / 2, UPPER_MASTER_Y, "Upper master"]);
      rows.push([bx + wTubing / 2, LOWER_MASTER_Y, "Lower master"]);
      rows.push([bx + (wAnnulus + wTubing) / 4, ground, "Annulus seal"]);
    }
    rows.push([at(perf_md * 0.3)[0] + wCasing / 2, at(perf_md * 0.3)[1], "Production casing"]);
    rows.push([at(perf_md * 0.42)[0] + wAnnulus / 2 - 4, at(perf_md * 0.42)[1], "Annulus"]);
    rows.push([at(perf_md * 0.56)[0] + bore / 2, at(perf_md * 0.56)[1], "Production tubing"]);
    // the leader starts at the valve itself, on whichever side the lift gas is, even though that
    // means crossing the tubing: a leader that stopped short of it would point at nothing
    if (glCentre) rows.push([glCentre[0], glCentre[1], "Gas lift valve"]);
    rows.push([packPt[0] + wAnnulus / 2 - 4, packPt[1], "Production packer"]);
    rows.push([shoePt[0] + bore / 2, shoePt[1] + 4, "Tubing tailpipe"]);
    rows.push([at((spec.perf_top + perf_md) / 2)[0] + wCement / 2 + 12,
               at((spec.perf_top + perf_md) / 2)[1], "Perforations"]);
    rows.push([endPt[0] + wCasing / 2 - 6, endPt[1], "Casing shoe"]);
    let lastY = -99;
    for (const [fx, fy, text] of rows) {
      const y = Math.max(fy, lastY + 15);
      lastY = y;
      svg.appendChild(node("path", { d: `M${fx},${fy} L${labelX - 7},${y}`, stroke: "#cbd5e1",
                                     "stroke-width": 0.8, fill: "none" }));
      svg.appendChild(node("circle", { cx: fx, cy: fy, r: 1.6, fill: "#cbd5e1" }));
      svg.appendChild(node("text", { x: labelX, y: y + 3.2, class: "wv-lbl" }, text));
    }
  }

  // ---- the layers the moving fluid is drawn in ----
  svg.appendChild(node("g", { id: "wv-inflow" }));
  svg.appendChild(node("g", { id: "wv-fluid" }));
  svg.appendChild(node("g", { id: "wv-jet" }));

  return { svg, spec, bands, perfs, shoePt, glCentre, glMd, glOn, liftSide,
           bore, wTubing, wAnnulus, at, normalAt, tiltAt, topMd, families,
           arm: tree ? { y: TEE_Y, from: bx, to: bx + ARM_END } : null,
           gasFill: GASFILL };
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
        add("taylor", () => node("path", { d: taylorPath(w), fill: scene.gasFill, opacity: 0.92 }),
            n, 1);
        // and the small bubbles carried in the liquid between them
        const m = clamp(Math.round(px / 34), 1, 10);
        add("bubble", () => node("circle", { r: bore * 0.07, fill: scene.gasFill, opacity: 0.9 }),
            m, 0.78);
      } else if (band.family === "bubble" || band.family === "liquid") {
        const n = band.family === "liquid" ? 0
          : clamp(Math.round(px / 15 * gassy), 2, 26);
        add("bubble", () => node("circle", { r: bore * (0.055 + Math.random() * 0.045),
                                             fill: scene.gasFill, opacity: 0.9 }), n, 1);
      } else if (band.family === "churn") {
        const n = clamp(Math.round(px / 30), 2, 9);
        add("churn", () => node("path", { d: churnPath(bore * 0.78, Math.random),
                                          fill: scene.gasFill, opacity: 0.88 }), n, 1.15);
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
        add("bubble", () => node("circle", { r: bore * 0.06, fill: scene.gasFill, opacity: 0.8 }),
            n, 1);
      }
      // the water riding in the liquid, in proportion to the water cut
      if (band.family !== "annular" && band.family !== "gas" && s.water_cut > 0.02) {
        const n = clamp(Math.round(px / 26 * s.water_cut * 2.2), 1, 14);
        add("water", () => node("circle", { r: 2 + Math.random() * 1.2,
                                            fill: PHASE_COLOURS.water, opacity: 0.95 }), n, 0.9);
      }
    }
    // where across the bore each one sits
    for (const r of risers) {
      const room = r.tag === "taylor" || r.tag === "churn" || r.tag === "froth" ? 0.06
        : r.tag === "mist" ? 0.24 : 0.3;
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
    for (let i = 0; i < 14; i++) {
      const perf = scene.perfs[i % scene.perfs.length];
      const c = node("circle", { r: 2.4 + Math.random() * 0.9,
                                 fill: Math.random() < s.water_cut
                                   ? PHASE_COLOURS.water : PHASE_COLOURS.oil });
      inHost.appendChild(c);
      inflow.push({ perf, t: Math.random(), speedScale: 0.6 + Math.random() * 0.8, node: c });
    }

    // and the flow out along the wing arm
    armFlow = [];
    if (scene.arm) {
      const shallow = scene.bands[0];
      const gasArm = shallow.family === "annular" || shallow.family === "gas";
      for (let i = 0; i < 6; i++) {
        const c = node("circle", { r: gasArm ? 2 : 2.6,
                                   fill: gasArm ? scene.gasFill
                                     : (i % 3 === 0 ? PHASE_COLOURS.water : PHASE_COLOURS.oil) });
        host.appendChild(c);
        armFlow.push({ u: i / 6, node: c });
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
