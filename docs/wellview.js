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
  const CAP_Y = 6;              // the tree cap, with a short spool between it and the swab valve
  const SWAB_Y = 30;            // the swab valve
  const TEE_Y = 58;             // the tee, and the production wing arm out of it
  const UPPER_MASTER_Y = 86;    // upper master valve
  const LOWER_MASTER_Y = 108;   // lower master valve, on top of the wellhead
  const ARM_REACH = 96;         // how far the wing arm reaches out from the centre of the well
  const SPOOL_H = 32;           // the wellhead spool, which stands ABOVE ground

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
  const pad = { t: spec.padTop ?? (tree ? 150 : 34), b: spec.padBottom ?? 26,
                l: compact ? 40 : 74, r: compact ? 14 : 22 };

  // How fat to draw the completion.  The widths below are the natural ones for the tubing size, and
  // they are then scaled up together to fill the panel: with the component names in tooltips
  // instead of a label gutter down the right-hand side, a well drawn at its natural size would sit
  // in the middle of a wide empty field of rock.
  const half0 = Math.min(13 + (spec.tubing_id - 2) * 2.2, 22);
  const glOn = spec.gl_md !== null && spec.gl_md > 0 && spec.gl_md < spec.shoe_md;
  // the room the lift gas line needs on the left, which is also how far the formation reaches
  // beyond the well on each side
  // in proportion to the panel: a fixed run pushed the whole well to the right of a narrow column
  const wingRoom = tree && glOn && !compact ? clamp(W * 0.2, 58, 96) : 22;
  const girth = compact ? 1
    : clamp((W - pad.l - pad.r - 2 * wingRoom) / (half0 * 2 + 58), 0.9, 1.9);
  const half = half0 * girth;
  const bore = half * 2;
  const wTubing = bore + 7 * girth;
  const wAnnulus = bore + 34 * girth;
  const wCasing = bore + 42 * girth;
  const wCement = bore + 58 * girth;

  const usableW = W - pad.l - pad.r - wCement;
  const usableH = H - pad.t - pad.b;
  // The vertical scale is fixed by the shared depth scale, so the well always spans exactly the
  // aligned height.  The horizontal one is squeezed to fit the room left over and never stretched
  // past the vertical one, which keeps a deviated well looking deviated without pulling its depths
  // out of line with the chart beside it.
  const scaleY = usableH / maxTvd;
  const scaleX = maxReach > 1 ? Math.min(usableW / maxReach, scaleY) : scaleY;
  // placed so the formation's left edge lands exactly where the lift gas line starts
  const x0 = pad.l + wingRoom + wCement / 2;
  const X = (/** @type {number} */ r) => x0 + r * scaleX;
  const Y = (/** @type {number} */ d) => pad.t + d * scaleY;
  const ground = Y(0);
  const bx = X(0);
  const axisX = Math.max(pad.l - 10, 30);
  const SPOOL_TOP = ground - SPOOL_H;
  const SEAL_Y = SPOOL_TOP + 7;          // the annulus seal, at the top of the spool, above 0 ft
  const WING_Y = ground - 9;             // the lift gas in, under the seal but still above ground

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
  const glMd = glOn ? Number(spec.gl_md) : 0;
  // Which side of the well the lift gas is on.  The valve goes on the LEFT of the tubing, and the
  // injection wing at surface has to be on that same left-hand side or the drawing would have the
  // gas entering one side of the annulus and leaving the other.  Both are worked out from the line
  // itself, because which way the normal points depends on which way the well is heading.
  const liftSide = normalAt(glMd)[0] > 0 ? -1 : 1;
  const wingDir = Math.sign(normalAt(0)[0] * liftSide) || -1;   // -1 when that is screen-left

  /** the run out through the wing, which the fluid leaves by @type {any} */
  let armOut = null;

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

  /**
   * The gas colour at a depth, as a plain colour.
   *
   * The gradient above serves the band fills, which are strokes of the centre line and so are read
   * in the drawing's own coordinates.  A Taylor bubble is not: it is a small shape carried to its
   * depth by a transform, and a gradient in user space is then read in the SHAPE's coordinates, so
   * every one of them sampled the same end of the ramp wherever it happened to be.  Moving shapes
   * therefore ask for their colour by depth instead.
   * @param {number} md
   */
  const gasAt = (md) => {
    if (!glOn) return PHASE_COLOURS.solutionGas;
    const yTop = at(topMd)[1];
    const span = Math.max(at(perf_md)[1] - yTop, 1);
    const f = (at(md)[1] - yTop) / span;
    const fv = (at(glMd)[1] - yTop) / span;
    const k = clamp((fv - f) / 0.12, 0, 1);          // 0 at the valve, 1 well above it
    return mix(PHASE_COLOURS.solutionGas, PHASE_COLOURS.gas, k);
  };

  // ---- the ground, the reservoir, and how tightly they frame the well ----
  // The formation is a band around the well, not a wash across the whole panel: drawn edge to edge
  // it left a wide field of empty rock either side of a vertical well, which said nothing and
  // crowded out the drawing.  On the left it stops exactly where the lift gas line starts.
  const frameL = bx - wCement / 2 - wingRoom;
  const frameR = Math.min(bx + wCement / 2 + wingRoom, W - 4);
  svg.appendChild(node("rect", { x: frameL, y: ground, width: frameR - frameL,
                                 height: H - ground - 4, fill: "#f6f1e7" }));
  // The reservoir section: the casing is run right through it and perforated across the whole of
  // it, so its base is where the casing ends.
  const payTop = at(spec.perf_top)[1];
  const payBot = at(perf_md)[1];
  svg.appendChild(node("rect", { id: "wv-pay", x: frameL, y: payTop, width: frameR - frameL,
                                 height: Math.max(payBot - payTop, 3), fill: "#e4d3ad" }));
  svg.appendChild(node("line", { x1: axisX, y1: ground, x2: frameR, y2: ground,
                                 stroke: "#94a3b8", "stroke-width": 1.4 }));

  // ---- the well itself, as concentric strokes of one line ----
  /** Put a hover label on something.  The component names live here now, not in a label gutter.
   * @param {any} el @param {string} text */
  const tip = (el, text) => { el.appendChild(node("title", {}, text)); return el; };
  /** @param {string} d @param {number} width @param {string} colour @param {Record<string, string|number>} [extra] */
  const stroke = (d, width, colour, extra = {}) =>
    svg.appendChild(node("path", { d, fill: "none", stroke: colour, "stroke-width": width,
                                   "stroke-linecap": "butt", "stroke-linejoin": "round", ...extra }));
  tip(stroke(line, wCement, "#d8d2c4"), "Cement sheath");
  tip(stroke(line, wCasing, STEEL), "Production casing");
  tip(stroke(line, wAnnulus, "#ffffff", { id: "wv-annulus" }), "Casing-tubing annulus");

  // ---- what is standing in the annulus ----
  // With gas lift on the annulus is a pressurised gas column from the wellhead seal down to the
  // valve, and dead completion fluid below it: that is an unloaded annulus.  With gas lift off
  // there is no gas in it at all and the whole thing is dead fluid.
  const annTop = tree ? (SEAL_Y - ground) / scaleY : 0;     // the seal stands above the ground line
  if (glOn) {
    tip(stroke(segment(annTop, glMd), wAnnulus - 2, PHASE_COLOURS.liftGas,
               { id: "wv-anngas", opacity: 0.72 }),
        "Lift gas: a pressurised column from surface down to the gas lift valve");
    tip(stroke(segment(glMd, spec.packer_md), wAnnulus - 2, PHASE_COLOURS.water,
               { id: "wv-anndead", opacity: 0.45 }),
        "Dead completion fluid, below the gas lift valve");
  } else {
    tip(stroke(segment(annTop, spec.packer_md), wAnnulus - 2, PHASE_COLOURS.water,
               { id: "wv-anndead", opacity: 0.45 }),
        "Dead completion fluid: no gas is being injected");
  }

  // below the packer the casing is full of what the reservoir is giving, which is where the
  // tailpipe has its open end
  tip(stroke(segment(spec.packer_md, perf_md), wAnnulus - 2, PHASE_COLOURS.oil,
             { id: "wv-rathole", opacity: 0.3 }), "Reservoir fluid, below the packer");

  const toShoe = segment(topMd, spec.shoe_md);
  tip(stroke(toShoe, wTubing, STEEL, { id: "wv-tubing" }), "Production tubing");
  stroke(toShoe, bore, "#ffffff", { id: "wv-bore" });

  // ---- the flow regimes inside the tubing ----
  // The pattern the correlation reports at each depth is DRAWN, not tinted: the liquid it is
  // flowing in, and over that the gas in whatever shape that regime takes.  Neighbouring intervals
  // reporting the same pattern are first collapsed into one run, so a regime is one continuous
  // stretch of pipe rather than thirty-odd identical slices.
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
  bands[0].from = topMd;          // the shallowest band carries on up the tree, as the fluid does
  for (const b of bands) {
    b.px = Math.abs(at(b.to)[1] - at(b.from)[1]) + Math.abs(at(b.to)[0] - at(b.from)[0]);
    b.riserFrom = b.from;
  }
  // The shapes rising up the tubing stop a little short of the tee.  Carried right into it they
  // piled up in the corner, where the mask cropped them into a solid block; what goes on round the
  // corner and out of the wing is drawn by the run along the arm instead.
  if (tree) bands[0].riserFrom = topMd + 26 / scaleY;

  for (const b of bands) {
    const d = segment(b.from, b.to);
    if (b.family === "annular" || b.family === "gas") {
      // a gas core, with the liquid carried as a film on the wall
      stroke(d, bore, GASFILL, { opacity: 0.85, class: "wv-fill" });
      if (b.family === "annular") {
        for (const side of [-1, 1]) {
          svg.appendChild(node("path", { class: "wv-film", d: filmPath(b, side), fill: "none",
                                         stroke: PHASE_COLOURS.oil, "stroke-width": bore * 0.15,
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
      const fam = flowFamily(spec.pattern.regime[i]);
      tip(svg.appendChild(node("path", { class: "wv-hit", d: segment(from, to), fill: "none",
                                         stroke: "transparent", "stroke-width": bore + 6,
                                         "stroke-linecap": "butt" })),
          `${fam ? FLOW_FAMILIES[fam].label : spec.pattern.regime[i]}`
          + ` flow, ${fmt(spec.toShown(from))}-${fmt(spec.toShown(to))} ${spec.lengthUnit} MD`);
    }
  }

  // ---- the seals: the red crossed blocks that mean "nothing gets past here" ----
  /**
   * @param {number} cx @param {number} cy @param {number} angle @param {string} cls @param {string} label
   */
  const sealBlock = (cx, cy, angle, cls, label) => {
    const len = (wAnnulus - wTubing) / 2;
    const g = node("g", { class: cls, transform: `rotate(${angle} ${cx} ${cy})` });
    g.appendChild(node("rect", { x: cx - len / 2, y: cy - 7, width: len, height: 14,
                                 fill: "#fee2e2", stroke: SEAL, "stroke-width": 1.6 }));
    g.appendChild(node("line", { x1: cx - len / 2, y1: cy - 7, x2: cx + len / 2, y2: cy + 7,
                                 stroke: SEAL, "stroke-width": 1.4 }));
    g.appendChild(node("line", { x1: cx - len / 2, y1: cy + 7, x2: cx + len / 2, y2: cy - 7,
                                 stroke: SEAL, "stroke-width": 1.4 }));
    tip(g, label);
    svg.appendChild(g);
  };
  const packPt = at(spec.packer_md);
  {
    const n = normalAt(spec.packer_md);
    const angle = Math.atan2(n[1], n[0]) * 180 / Math.PI;
    for (const side of [-1, 1]) {
      sealBlock(packPt[0] + n[0] * side * (wAnnulus + wTubing) / 4,
                packPt[1] + n[1] * side * (wAnnulus + wTubing) / 4,
                angle, "wv-packer", "Production packer: seals the annulus above the perforations");
    }
  }

  // ---- the open tubing tailpipe, hanging below the packer in the perforated interval ----
  const shoePt = at(spec.shoe_md);
  const shoeN = normalAt(spec.shoe_md);
  for (const side of [-1, 1]) {
    tip(svg.appendChild(node("path", {
      d: `M${shoePt[0] + shoeN[0] * side * (bore / 2 + 3.5 * girth)},`
         + `${shoePt[1] + shoeN[1] * side * (bore / 2 + 3.5 * girth)} `
         + `l${shoeN[0] * side * 4},${shoeN[1] * side * 4}`,
      stroke: STEEL_DARK, "stroke-width": 2.5, "stroke-linecap": "round" })),
      "Open tubing tailpipe");
  }

  // ---- the perforations, through both casing walls, across the whole reservoir ----
  /** @type {{x: number, y: number, nx: number, ny: number}[]} */
  const perfs = [];
  const payPx = Math.max(payBot - payTop, 1);
  const nPerf = Math.max(3, Math.min(10, Math.round(payPx / 11)));
  for (let i = 0; i < nPerf; i++) {
    const md = spec.perf_top + (perf_md - spec.perf_top) * (i + 0.5) / nPerf;
    const p = at(md);
    const n = normalAt(md);
    for (const side of [-1, 1]) {
      const from = wCasing / 2 - 1;
      const to = wCement / 2 + 13;
      tip(svg.appendChild(node("path", {
        d: `M${p[0] + n[0] * side * from},${p[1] + n[1] * side * from} `
           + `L${p[0] + n[0] * side * to},${p[1] + n[1] * side * to}`,
        stroke: "#8c3b2e", "stroke-width": 2.2, "stroke-linecap": "round" })),
        "Perforations");
      perfs.push({ x: p[0] + n[0] * side * to, y: p[1] + n[1] * side * to,
                   nx: -n[0] * side, ny: -n[1] * side });
    }
  }

  // ---- the casing shoe, at the base of the reservoir ----
  // Each triangle stands on the bottom of the casing with its straight edge up the outside of the
  // casing wall and its sloped edge facing out, which is how a guide shoe is drawn.
  const endPt = at(perf_md);
  const endN = normalAt(perf_md);
  const down = [endN[1], -endN[0]];                 // along the well, downwards
  tip(svg.appendChild(node("path", {
    d: `M${endPt[0] - endN[0] * wCasing / 2},${endPt[1] - endN[1] * wCasing / 2} `
       + `L${endPt[0] + endN[0] * wCasing / 2},${endPt[1] + endN[1] * wCasing / 2}`,
    stroke: STEEL_DARK, "stroke-width": 2.5 })), "Casing shoe");
  for (const side of [-1, 1]) {
    const o = wCasing / 2;
    const ax = endPt[0] + endN[0] * side * o;       // the foot of the casing wall
    const ay = endPt[1] + endN[1] * side * o;
    const up = 15 * girth;
    const out = 9 * girth;
    tip(svg.appendChild(node("polygon", {
      class: "wv-shoe",
      points: `${ax},${ay} ${ax - down[0] * up},${ay - down[1] * up} `
              + `${ax + endN[0] * side * out},${ay + endN[1] * side * out}`,
      fill: STEEL_DARK })), "Casing shoe");
  }

  // ---- the side pocket mandrel, with the gas lift valve in it ----
  // A mandrel is a slim pocket welded to the outside of the tubing, not a block across the annulus:
  // it takes up well under half the annulus so that gas can still pass it on its way down.
  let glCentre = null;
  if (glOn) {
    const p = at(glMd);
    const n = normalAt(glMd);
    const w = Math.max((wAnnulus - wTubing) / 2 * 0.44, 4.5);
    const h = Math.max(bore * 1.15, 34);
    const px = p[0] + n[0] * liftSide * wTubing / 2;
    const py = p[1] + n[1] * liftSide * wTubing / 2;
    const angle = Math.atan2(n[1] * liftSide, n[0] * liftSide) * 180 / Math.PI;
    glCentre = [px + n[0] * liftSide * w / 2, py + n[1] * liftSide * w / 2];
    // the port through the tubing wall, drawn first so the mandrel covers its outer end
    svg.appendChild(node("path", {
      d: `M${px},${py} L${p[0] + n[0] * liftSide * (bore / 2 - 4)},`
         + `${p[1] + n[1] * liftSide * (bore / 2 - 4)}`,
      stroke: PHASE_COLOURS.liftGas, "stroke-width": 3.4, "stroke-linecap": "round" }));
    tip(svg.appendChild(node("path", {
      id: "wv-glvalve",
      d: `M0,${-h / 2} C${w * 0.95},${-h * 0.3} ${w},${-h * 0.1} ${w},0 `
         + `C${w},${h * 0.1} ${w * 0.95},${h * 0.3} 0,${h / 2} Z`,
      transform: `translate(${px},${py}) rotate(${angle})`,
      fill: "#ffffff", stroke: STEEL_DARK, "stroke-width": 1.6,
      "stroke-linejoin": "round" })),
      "Side pocket mandrel with the gas lift valve, injecting into the tubing");
    // the valve itself, in the pocket
    svg.appendChild(node("circle", { cx: glCentre[0], cy: glCentre[1], r: Math.min(w * 0.42, 4.5),
                                     fill: PHASE_COLOURS.liftGas }));
  }

  /**
   * The standard circle-and-cross valve symbol.  Open is drawn in full ink, shut is greyed and
   * filled in, so a glance says which it is.
   * @param {number} x @param {number} y @param {string} id @param {boolean} open @param {string} label
   */
  const valveSymbol = (x, y, id, open, label) => {
    const g = node("g", { id, class: "wv-valve" });
    const r = 8.5 * Math.min(girth, 1.3);
    const ink = open ? STEEL_DARK : "#9aa7b4";
    g.appendChild(node("circle", { cx: x, cy: y, r, fill: open ? "#ffffff" : "#e2e8f0",
                                   stroke: ink, "stroke-width": 1.8 }));
    const k = r * 0.707;
    g.appendChild(node("line", { x1: x - k, y1: y - k, x2: x + k, y2: y + k,
                                 stroke: ink, "stroke-width": 1.8 }));
    g.appendChild(node("line", { x1: x - k, y1: y + k, x2: x + k, y2: y - k,
                                 stroke: ink, "stroke-width": 1.8 }));
    tip(g, `${label}${open ? "" : " (shut)"}`);
    return g;
  };

  // ---- the wellhead spool, standing above ground ----
  if (tree) {
    const steel = { fill: "#cbd5e1", stroke: STEEL, "stroke-width": 1.2 };
    tip(svg.appendChild(node("rect", { x: bx - wCasing / 2 - 7, y: SPOOL_TOP, width: wCasing + 14,
                                       height: ground - SPOOL_TOP, rx: 2, ...steel })),
        "Wellhead spool");
    // the gas column carries on up inside it, to the seal
    if (glOn) {
      for (const side of [-1, 1]) {
        svg.appendChild(node("rect", {
          x: bx + side * (wTubing / 2) - (side < 0 ? (wAnnulus - wTubing) / 2 : 0),
          y: SEAL_Y, width: (wAnnulus - wTubing) / 2, height: ground - SEAL_Y,
          fill: PHASE_COLOURS.liftGas, opacity: 0.72 }));
      }
    }
    // the seal across the top of the annulus, above the ground line
    for (const side of [-1, 1]) {
      sealBlock(bx + side * (wAnnulus + wTubing) / 4, SEAL_Y, 0, "wv-wellhead-seal",
                "Wellhead annulus seal: the annulus is closed at surface");
    }
    if (glOn) {
      // the injection wing, into the spool below the seal and above ground
      const tipX = bx + wingDir * (wCasing / 2 + 7);
      const outX = tipX + wingDir * (wingRoom - 14);
      svg.appendChild(node("line", { x1: outX, y1: WING_Y, x2: tipX, y2: WING_Y,
                                     stroke: PHASE_COLOURS.liftGas, "stroke-width": 3,
                                     "stroke-linecap": "round" }));
      svg.appendChild(node("polygon", {
        points: `${tipX},${WING_Y} ${tipX - wingDir * 10},${WING_Y - 5} `
                + `${tipX - wingDir * 10},${WING_Y + 5}`, fill: PHASE_COLOURS.liftGas }));
      svg.appendChild(valveSymbol(outX + (tipX - outX) * 0.42, WING_Y, "wv-annwing", true,
                                  "Annulus wing valve: lift gas into the annulus"));
      svg.appendChild(node("text", { x: outX - 2, y: WING_Y - 14, class: "wv-lbl",
                                     fill: "#b23c20",
                                     "text-anchor": wingDir < 0 ? "start" : "end" }, "lift gas in"));
    }
  }

  // ---- the Christmas tree ----
  if (tree) {
    const g = node("g");
    const steel = { fill: "#cbd5e1", stroke: STEEL, "stroke-width": 1.2 };
    const armEnd = bx + Math.max(ARM_REACH, wTubing / 2 + 70);
    // the stem, carrying the tubing bore on up from the wellhead
    tip(g.appendChild(node("rect", { x: bx - wTubing / 2, y: CAP_Y + 10, width: wTubing,
                                     height: SPOOL_TOP - CAP_Y - 10, ...steel })), "Christmas tree");
    // the wing arm out of the tee
    const armH = Math.min(wTubing, 34);
    g.appendChild(node("rect", { x: bx + wTubing / 2 - 1, y: TEE_Y - armH / 2,
                                 width: armEnd - bx - wTubing / 2, height: armH, ...steel }));
    // the cap, with a short spool of pipe between it and the swab valve
    g.appendChild(node("rect", { x: bx - wTubing / 2 - 5, y: CAP_Y, width: wTubing + 10,
                                 height: 9, rx: 1.5, fill: STEEL }));
    svg.appendChild(g);
    // the bores: the stem above the tee and the arm carry whatever the shallowest regime is
    const shallow = bands[0];
    const gassy = shallow.family === "annular" || shallow.family === "gas";
    const fill = gassy ? GASFILL : PHASE_COLOURS.oil;
    const fillOp = gassy ? 0.85 : 0.5;
    const armBore = Math.min(bore * 0.72, 30);
    svg.appendChild(node("rect", { id: "wv-armbore", x: bx - bore / 2,
                                   y: TEE_Y - armBore / 2, width: armEnd - bx + bore / 2 - 2,
                                   height: armBore, fill, opacity: fillOp }));
    // the dead-end pocket above the tee: filled, but nothing moves in it, because nothing does
    tip(svg.appendChild(node("rect", { id: "wv-deadleg", x: bx - bore / 2, y: CAP_Y + 10,
                                       width: bore,
                                       height: TEE_Y + armBore / 2 - CAP_Y - 10,
                                       fill, opacity: fillOp * 0.8 })),
        "Dead leg: the pocket above the tee, where nothing flows");
    // and the outward flow arrow off the end of the arm
    svg.appendChild(node("line", { x1: armEnd, y1: TEE_Y, x2: armEnd + 20, y2: TEE_Y,
                                   stroke: STEEL_DARK, "stroke-width": 2.4 }));
    svg.appendChild(node("polygon", { id: "wv-outflow",
      points: `${armEnd + 30},${TEE_Y} ${armEnd + 18},${TEE_Y - 6} ${armEnd + 18},${TEE_Y + 6}`,
      fill: STEEL_DARK }));

    svg.appendChild(valveSymbol(bx, SWAB_Y, "wv-swab", spec.masterOpen !== false, "Swab valve"));
    svg.appendChild(valveSymbol(bx + (armEnd - bx) * 0.6, TEE_Y, "wv-wing",
                                spec.chokeOpen !== false, "Production wing valve"));
    svg.appendChild(valveSymbol(bx, UPPER_MASTER_Y, "wv-master", spec.masterOpen !== false,
                                "Upper master valve"));
    svg.appendChild(valveSymbol(bx, LOWER_MASTER_Y, "wv-lower-master", spec.masterOpen !== false,
                                "Lower master valve"));
    armOut = { y: TEE_Y, from: bx + wTubing / 2, to: armEnd + 26 };
  }

  // ---- the depth scale ----
  // The scale is TRUE VERTICAL DEPTH, which is both what the chart beside it plots against and what
  // the ticks have to be if a depth is to be at the same height in the two panels.
  const stepFt = maxTvd > 12000 ? 4000 : maxTvd > 6000 ? 2000 : maxTvd > 2500 ? 1000 : 500;
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

  // ---- the layers the moving fluid is drawn in ----
  // The fluid is masked to the inside of the pipe.  A Taylor bubble nearly fills the bore and the
  // shapes grow as they rise, so without this they reach into the steel; and the mask deliberately
  // leaves out the pocket above the tee, which is a dead leg where nothing should be seen moving.
  const mask = node("mask", { id: "wv-inside", maskUnits: "userSpaceOnUse",
                              x: 0, y: 0, width: W, height: H });
  mask.appendChild(node("path", { d: toShoe, fill: "none", stroke: "#ffffff",
                                  "stroke-width": bore, "stroke-linecap": "butt" }));
  if (armOut) {
    // The arm's window starts at the OUTSIDE of the stem.  Reaching across the stem, it opened a
    // slot above the tee through which the fluid rising up the tubing showed in the dead leg.
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
           bore, wTubing, wAnnulus, at, normalAt, tiltAt, topMd, families, girth,
           arm: armOut, gasFill: GASFILL, gasAt };
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
  let pulses = [];
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
          risers.push({ band, from: band.riserFrom ?? band.from, to: band.to,
                        u: (i + Math.random() * 0.6) / n, speed, node: g, tag,
                        across: 0, wobble: Math.random() * 6.3, bucket: -1,
                        gas: g.getAttribute("fill") === scene.gasFill,
                        r0: Number(g.getAttribute("r") || 0) });
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

    // The lift gas jetting through the mandrel into the tubing, and the slow pulses that say the
    // column in the annulus is being pushed down rather than just standing there.
    jet = [];
    pulses = [];
    if (scene.glOn && scene.glCentre) {
      for (let i = 0; i < 9; i++) {
        const c = node("circle", { r: 2 + Math.random() * 1.6, fill: PHASE_COLOURS.liftGas });
        jetHost.appendChild(c);
        jet.push({ u: i / 9, node: c });
      }
      const off = (scene.wTubing + scene.wAnnulus) / 4;
      for (let i = 0; i < 10; i++) {
        const c = node("path", { d: `M${-off * 0.22},0 L0,5 L${off * 0.22},0`, fill: "none",
                                 stroke: "#ffffff", "stroke-width": 1.6, "stroke-linecap": "round",
                                 "stroke-linejoin": "round", opacity: 0.5 });
        jetHost.appendChild(c);
        pulses.push({ u: (i % 5) / 5, side: i < 5 ? -1 : 1, node: c, off });
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

    // The flow out through the wing: both phases leave that way, because that is the only way out
    // of the tree.  The pocket above the tee is a dead leg and nothing is drawn moving in it.
    armFlow = [];
    if (scene.arm) {
      const mix = ["gas", "oil", "gas", "water", "oil", "gas", "oil", "water"];
      for (let i = 0; i < mix.length; i++) {
        const phase = mix[i] === "water" && s.water_cut < 0.05 ? "oil" : mix[i];
        const c = node("circle", { r: phase === "gas" ? 2.4 : 3,
                                   fill: phase === "gas" ? scene.gasFill
                                     : PHASE_COLOURS[phase] });
        host.appendChild(c);
        armFlow.push({ u: i / mix.length, node: c, lift: (i % 3 - 1) * 2.5 });
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
      const spanFt = r.to - r.from;
      if (speed > 0) {
        r.u += speed * r.speed * dt / Math.max(r.band.px, 1);
        if (r.u > 1.06) r.u -= 1.12;
      }
      r.wobble += dt * 3;
      const md = r.to - r.u * spanFt;
      const p = scene.at(md);
      const n = scene.normalAt(md);
      const sway = r.tag === "bubble" || r.tag === "mist" ? Math.sin(r.wobble) * 1.6 : 0;
      const off = r.across + sway;
      const x = p[0] + n[0] * off;
      const y = p[1] + n[1] * off;
      // Gas grows on the way up as the pressure falls, continuously and across the whole string,
      // so one regime shades into the next instead of changing at a line.
      const deep = clamp((md - scene.topMd) / Math.max(s.shoe_md - scene.topMd, 1), 0, 1);
      const grow = r.tag === "mist" || r.tag === "water" || r.tag === "froth"
        ? 1 : 0.76 + 0.46 * (1 - deep);
      // the gas shades with depth, so the colour is refreshed as it rises - in steps, because
      // the eye cannot see a finer change and a new colour string every frame is wasted work
      if (r.gas) {
        const bucket = Math.round(deep * 10);
        if (bucket !== r.bucket) {
          r.bucket = bucket;
          r.node.setAttribute("fill", scene.gasAt(md));
        }
      }
      if (r.tag === "taylor" || r.tag === "churn" || r.tag === "froth") {
        const wob = r.tag === "churn" ? 1 + Math.sin(r.wobble) * 0.09 : 1;
        r.node.setAttribute("transform",
          `translate(${x.toFixed(2)},${y.toFixed(2)}) rotate(${scene.tiltAt(md).toFixed(1)}) `
          + `scale(${(wob * grow).toFixed(3)},${((2 - wob) * grow).toFixed(3)})`);
      } else {
        r.node.setAttribute("cx", x.toFixed(2));
        r.node.setAttribute("cy", y.toFixed(2));
        if (r.r0) r.node.setAttribute("r", (r.r0 * grow).toFixed(2));
      }
      r.node.setAttribute("opacity", s.flowing ? "0.92" : "0.35");
    }

    // the gas column being pushed down the annulus towards the valve
    for (const q of pulses) {
      if (speed > 0) q.u = (q.u + dt * 0.22) % 1;
      const md = scene.annTop + q.u * (scene.glMd - scene.annTop);
      const p = scene.at(md);
      const n = scene.normalAt(md);
      q.node.setAttribute("transform",
        `translate(${(p[0] + n[0] * q.side * q.off).toFixed(2)},${p[1].toFixed(2)})`);
      q.node.setAttribute("opacity", s.flowing ? String(0.55 * Math.sin(q.u * Math.PI)) : "0");
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
        j.node.setAttribute("opacity", s.flowing ? String(0.95 - 0.85 * up) : "0");
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
        a.node.setAttribute("cy", String(scene.arm.y + a.lift));
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
