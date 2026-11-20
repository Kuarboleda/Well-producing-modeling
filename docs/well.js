// @ts-check
/**
 * well.js - well geometry and temperature, translated from well.py (oilfield units).
 *
 * Units: depth ft | pipe ID in | roughness in | temperature degF
 *        U (overall heat transfer coefficient) Btu/h/ft2/degF
 *        mass rate lb/h | heat capacity Btu/lb/degF | angle degrees from horizontal
 *
 * What this file does
 *     1. Stores the well description in one "box" called Well.
 *     2. Cuts the well into short steps (buildSteps).  The pressure calculation in vlp.js walks
 *        down these steps one at a time, from wellhead to perforations.
 *     3. Works out the fluid temperature along the well (fluidTemperatures).
 *
 * Conventions
 *     * The survey starts at the wellhead (MD = 0, TVD = 0) and ends at the PERFORATIONS.  The last
 *       point is the reference depth for reservoir pressure and temperature.
 *     * "Angle" is measured from horizontal in the direction of flow (up the well): 90 = vertical,
 *       0 = horizontal.  A negative angle means the fluid flows downhill over that piece.
 *
 * Every function keeps the same behaviour as the Python; the names are camelCase here where the
 * Python used snake_case, and tools/crosscheck.mjs maps one to the other.
 */

/** Stop with a clear error message if an input does not make sense. @param {boolean} condition @param {string} message */
function check(condition, message) {
  if (!condition) throw new Error(message);
}

/**
 * Straight-line interpolation of y at x, given xs (increasing) and ys.  Outside the range the first
 * or last y is returned.
 * @param {number} x @param {number[]} xs @param {number[]} ys
 */
function interp(x, xs, ys) {
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  for (let i = 0; i < xs.length - 1; i++) {
    if (xs[i] <= x && x <= xs[i + 1]) {
      const fraction = (x - xs[i]) / (xs[i + 1] - xs[i]);
      return ys[i] + fraction * (ys[i + 1] - ys[i]);
    }
  }
  return ys[ys.length - 1];           // unreachable with an increasing xs; keeps the types happy
}

/**
 * @typedef {[number, number, number]} TubingSection  [md_from, md_to, id_in]
 * @typedef {[number, number, number]} AmbientRow     [md, ambient degF, U]
 * @typedef {{md: number[], tvd: number[], tubing: TubingSection[], t_reservoir: number,
 *            roughness_in: number, ambient_table: AmbientRow[]}} Well
 * @typedef {{md_top: number, md_bot: number, tvd_top: number, tvd_bot: number, length: number,
 *            angle_deg: number, id_in: number, inj_scfd?: number}} Step
 */

// =====================================================================
// Survey helpers
// =====================================================================

/**
 * Survey [md_list, tvd_list] of a straight vertical well of the given depth (ft).
 * @param {number} depth @returns {[number[], number[]]}
 */
export function verticalSurvey(depth) {
  return [[0.0, Number(depth)], [0.0, Number(depth)]];
}

/**
 * Turn pasted text (for example copied from a spreadsheet) into [md_list, tvd_list].
 *
 * Each line holds two numbers: measured depth and true vertical depth.  They can be separated by
 * spaces, tabs, commas or semicolons.  Lines that are blank or are not numbers (like a header
 * "MD  TVD") are skipped.
 * @param {string} text @returns {[number[], number[]]}
 */
export function parseSurveyText(text) {
  /** @type {number[]} */
  const md_list = [];
  /** @type {number[]} */
  const tvd_list = [];
  for (const line of String(text).split(/\r?\n/)) {
    const parts = line.replace(/[,;]/g, " ").split(/\s+/).filter((t) => t.length > 0);
    if (parts.length < 2) continue;
    const md = Number(parts[0]);
    const tvd = Number(parts[1]);
    // Python's float() raises on a header line, which is skipped; Number() gives NaN, same meaning.
    // An empty string would become 0 in JavaScript, so it is filtered out above.
    if (!Number.isFinite(md) || !Number.isFinite(tvd)) continue;
    md_list.push(md);
    tvd_list.push(tvd);
  }
  check(md_list.length >= 2, "Need at least two survey points (MD and TVD).");
  return [md_list, tvd_list];
}

// =====================================================================
// The Well "box"
// =====================================================================

/** One tubing section from the wellhead down to the perforations. @param {number} id_in @param {number} perf_md */
export function simpleTubing(id_in, perf_md) {
  return /** @type {TubingSection[]} */ ([[0.0, Number(perf_md), Number(id_in)]]);
}

/**
 * Build a Well and check it, the way the Python dataclass does in __post_init__.
 * ambient_table of null gives the default: 80 degF and U = 5 at surface, reservoir temperature and
 * U = 5 at the perforations.
 * @param {{md: number[], tvd: number[], tubing: TubingSection[], t_reservoir: number,
 *          roughness_in?: number, ambient_table?: AmbientRow[] | null}} spec
 * @returns {Well}
 */
export function makeWell(spec) {
  /** @type {Well} */
  const well = { md: spec.md, tvd: spec.tvd, tubing: spec.tubing, t_reservoir: spec.t_reservoir,
                 roughness_in: spec.roughness_in ?? 0.0006,
                 ambient_table: spec.ambient_table ?? [] };
  checkWell(well);
  if (!spec.ambient_table) {
    well.ambient_table = [[0.0, 80.0, 5.0], [well.md[well.md.length - 1], well.t_reservoir, 5.0]];
  }
  check(well.ambient_table.length >= 1, "Ambient temperature table is empty.");
  const mds = well.ambient_table.map((row) => row[0]);
  for (let i = 0; i < mds.length - 1; i++) {
    check(mds[i] < mds[i + 1], "Ambient temperature table: MD must increase from row to row.");
  }
  for (const row of well.ambient_table) check(row[2] >= 0, "U cannot be negative.");
  return well;
}

/** Check the survey and tubing sections; throw a clear error if something is wrong. @param {Well} well */
export function checkWell(well) {
  const { md, tvd } = well;
  check(md.length === tvd.length && md.length >= 2,
        "MD and TVD lists need the same length (at least 2 points).");
  check(md[0] === 0 && tvd[0] === 0, "The survey must start at MD = 0 and TVD = 0 (the wellhead).");
  for (let i = 0; i < md.length - 1; i++) {
    const d_md = md[i + 1] - md[i];
    const d_tvd = tvd[i + 1] - tvd[i];
    check(d_md > 0, `MD must increase (check survey row ${i + 2}).`);
    check(Math.abs(d_tvd) <= d_md + 1e-6,
          `TVD changes by more than MD between survey rows ${i + 1} and ${i + 2} - impossible.`);
  }
  check(well.roughness_in >= 0, "Roughness cannot be negative.");
  check(well.t_reservoir > 0, "Reservoir temperature must be > 0.");

  const perf_md = md[md.length - 1];
  check(well.tubing.length >= 1, "Define at least one tubing section.");
  let expected_from = 0.0;
  for (const [md_from, md_to, id_in] of well.tubing) {
    check(Math.abs(md_from - expected_from) < 1e-6,
          "Tubing sections must run without gaps, starting at MD = 0.");
    check(md_to > md_from && id_in > 0, "Each tubing section needs MD_to > MD_from and ID > 0.");
    expected_from = md_to;
  }
  check(Math.abs(expected_from - perf_md) < 1e-6,
        `Tubing sections must end at the perforation depth (MD = ${perf_md}).`);
}

/** True vertical depth (ft) at a measured depth (ft). @param {Well} well @param {number} md */
export function tvd_at(well, md) {
  return interp(md, well.md, well.tvd);
}

/**
 * Ambient (surroundings) temperature in degF and U at a measured depth, from the table.
 * @param {Well} well @param {number} md @returns {[number, number]}
 */
export function ambient_at(well, md) {
  const mds = well.ambient_table.map((row) => row[0]);
  const temps = well.ambient_table.map((row) => row[1]);
  const us = well.ambient_table.map((row) => row[2]);
  return [interp(md, mds, temps), interp(md, mds, us)];
}

/** Tubing inner diameter (in) at a measured depth. @param {Well} well @param {number} md */
function tubingIdAt(well, md) {
  for (const [md_from, md_to, id_in] of well.tubing) {
    if (md_from <= md && md <= md_to) return id_in;
  }
  return well.tubing[well.tubing.length - 1][2];
}

// =====================================================================
// Cut the well into short steps
// =====================================================================

/**
 * Cut the well into short steps, listed from the WELLHEAD DOWN to the perforations.
 *
 * A step never crosses a survey point or a tubing-size change, and is never longer than max_step_ft.
 * @param {Well} well @param {number} [max_step_ft] @param {number[] | null} [extra_breaks]
 * @returns {Step[]}
 */
export function buildSteps(well, max_step_ft = 100.0, extra_breaks = null) {
  check(max_step_ft > 0, "max_step_ft must be > 0.");
  const perf_md = well.md[well.md.length - 1];

  // 1) all the depths where something changes (survey points, tubing changes, gas lift injection)
  const raw = [...well.md, ...(extra_breaks || [])];
  for (const [md_from, md_to] of well.tubing) {
    raw.push(md_from);
    raw.push(md_to);
  }
  // Python: sorted(set(round(b, 6) for b in breaks if 0 <= b <= perf_md)).  Python's round() is
  // banker's rounding on a tie; at six decimal places on a depth in feet that can never change the
  // step boundaries, so toFixed(6) is used and the two agree on every real survey.
  const seen = new Set();
  for (const b of raw) {
    if (b >= 0 && b <= perf_md) seen.add(Number(b.toFixed(6)));
  }
  const breaks = [...seen].sort((a, b) => a - b);

  // 2) cut each piece between two break depths into equal short steps
  /** @type {Step[]} */
  const steps = [];
  for (let k = 0; k < breaks.length - 1; k++) {
    const a = breaks[k];
    const b = breaks[k + 1];
    const n = Math.max(1, Math.ceil((b - a) / max_step_ft - 1e-9));
    for (let j = 0; j < n; j++) {
      const md_top = a + (b - a) * j / n;
      const md_bot = a + (b - a) * (j + 1) / n;
      const tvd_top = tvd_at(well, md_top);
      const tvd_bot = tvd_at(well, md_bot);
      const length = md_bot - md_top;
      const sine = Math.max(-1.0, Math.min(1.0, (tvd_bot - tvd_top) / length));
      steps.push({ md_top, md_bot, tvd_top, tvd_bot, length,
                   angle_deg: Math.asin(sine) * 180.0 / Math.PI,
                   id_in: tubingIdAt(well, 0.5 * (md_top + md_bot)) });
    }
  }
  return steps;
}

// =====================================================================
// Temperature profile
// =====================================================================

/**
 * Fluid temperature (degF) at every step boundary, wellhead first.
 *
 * mass_rate_lb_hr and cp are one number each, or one number per step (an array) when the flow
 * changes along the well, for example when gas lift gas joins it part of the way up.
 *
 * The list has steps.length + 1 values: element 0 is the wellhead and the last element is the
 * perforations (= reservoir temperature).
 *
 * Method: start at the perforations and move UP the well.  In each step the fluid loses heat to the
 * surroundings, so it moves towards the ambient temperature:
 *     T_top = T_ambient + (T_bottom - T_ambient) * exp(-A * L),   A = pi * d * U / (w * cp)
 * Friction heating and Joule-Thomson cooling are ignored.
 * @param {Well} well @param {Step[]} steps @param {number | number[]} mass_rate_lb_hr
 * @param {number | number[]} cp
 */
export function fluidTemperatures(well, steps, mass_rate_lb_hr, cp) {
  const n = steps.length;
  const masses = Array.isArray(mass_rate_lb_hr) ? [...mass_rate_lb_hr] : new Array(n).fill(mass_rate_lb_hr);
  const cps = Array.isArray(cp) ? [...cp] : new Array(n).fill(cp);
  check(masses.length === n && cps.length === n, "mass rate and cp need one value per step.");
  for (const c of cps) check(c > 0, "cp must be > 0.");
  const temps = new Array(n + 1).fill(0.0);
  temps[n] = well.t_reservoir;
  for (let i = n - 1; i >= 0; i--) {                 // bottom step first
    const s = steps[i];
    const [t_amb, u] = ambient_at(well, 0.5 * (s.md_top + s.md_bot));
    const mass = masses[i];
    const cpi = cps[i];
    if (mass <= 0) {                                 // no flow -> fluid sits at ambient
      temps[i] = t_amb;
      continue;
    }
    const d_ft = s.id_in / 12.0;
    const a = Math.PI * d_ft * u / (mass * cpi);
    temps[i] = t_amb + (temps[i + 1] - t_amb) * Math.exp(-a * s.length);
  }
  return temps;
}
