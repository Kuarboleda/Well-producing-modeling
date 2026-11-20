// @ts-check
/**
 * advice.js - which VLP correlation suits this well, translated from the advice part of
 * app_helpers.py.
 *
 * There is no physics here: it is the published range of validity of each correlation, turned into a
 * rating and a sentence.  The rules and where they come from are written out in correlation_advice()
 * below, with the paper named each time a paper says it and "field practice" said plainly when none
 * does.
 *
 * The one thing this file insists on saying, every time, is that it has only looked at the fluid,
 * the equipment and the well path.  No set of rules can tell you which correlation is right for a
 * well; only a measured flowing pressure can.  So every caption ends by pointing at the comparison
 * with a downhole gauge reading or a flowing gradient survey.
 */

/**
 * The names shown on the page.  These are word for word the names in app_helpers.CORRELATION_NAMES,
 * because the cross-check compares the sentences this file writes with the ones the Streamlit app
 * writes, and a well should not be described differently by the two.  The year of each paper is in
 * correlation_detail() below.
 */
export const CORRELATION_NAMES = {
  gray: "Gray",
  hagedorn_brown: "Hagedorn and Brown",
  duns_ros: "Duns and Ros",
  beggs_brill: "Beggs and Brill",
  orkiszewski: "Orkiszewski",
  mukherjee_brill: "Mukherjee and Brill",
  ansari: "Ansari et al (mechanistic)",
  fancher_brown: "Fancher and Brown (no slip, quality check)",
};

export const DEVIATED_ABOVE_DEG = 30.0;      // steeper than this from vertical anywhere = deviated (rule of thumb)
export const GRAY_MAX_CGR = 50.0;            // STB/MMscf: Gray holds up to about this condensate ratio (field guidance)
export const DUNS_ROS_MAX_WATER_CUT = 0.10;  // Duns and Ros (1963) tested with less than 10 % water
export const HEAVY_OIL_API = 20.0;           // Orkiszewski (1967) was found best for heavy oil

/** Which correlations are offered, best first when the ratings are equal. */
export const PREFERENCE_OIL = ["hagedorn_brown", "mukherjee_brill", "duns_ros", "orkiszewski",
                               "ansari", "beggs_brill"];
export const PREFERENCE_GAS = ["gray", "duns_ros", "mukherjee_brill", "hagedorn_brown",
                               "orkiszewski", "ansari", "beggs_brill"];

// Fancher and Brown ignores slip, so it gives the lowest VLP of all, and it is useful only as a
// quality-check bound: it should never be used for a real calculation.  It is shown in the
// comparison but never recommended.
export const QC_ONLY = ["fancher_brown"];
export const QC_NOTE = "A quality-check bound, not a method to rely on: it ignores slip, so it gives "
  + "the lowest pressure. A measured flowing pressure below it points to a wrong fluid density (PVT) "
  + "or wrong pressure data.";

/** @type {Record<string, number>} */
const RATING_RANK = { good: 0, ok: 1, caution: 2 };

/** The name of a correlation, by key. @param {string} key */
export function nameOf(key) {
  return CORRELATION_NAMES[/** @type {keyof typeof CORRELATION_NAMES} */ (key)] || key;
}

/**
 * @typedef {{fluid_type?: string, water_cut?: number, api?: number, cgr?: number,
 *            survey_mode?: string, md?: number[], tvd?: number[]}} AdviceInputs
 * water_cut is a fraction (0 - 1), cgr is STB/MMscf, and md/tvd are the survey in feet (only needed
 * when survey_mode is not "vertical").
 */

/**
 * The steepest part of the well, in degrees from vertical (0 = vertical, 90 = horizontal).
 * @param {AdviceInputs} i
 */
export function max_inclination_deg(i) {
  if ((i.survey_mode || "vertical") === "vertical") return 0.0;
  const md = i.md || [];
  const tvd = i.tvd || [];
  if (md.length < 2 || md.length !== tvd.length) return 0.0;
  let worst = 0.0;
  for (let k = 1; k < md.length; k++) {
    const d_md = md[k] - md[k - 1];
    const d_tvd = tvd[k] - tvd[k - 1];
    if (d_md > 0) {
      const ratio = Math.max(-1.0, Math.min(1.0, d_tvd / d_md));
      worst = Math.max(worst, Math.acos(ratio) * 180.0 / Math.PI);
    }
  }
  return worst;
}

/**
 * Rate every correlation of this fluid type for this well.
 *
 * Returns {key: {rating: "good" | "ok" | "caution", notes: [short sentences]}}.  The rules and where
 * they come from (the correlations' own papers, and field practice where no paper says it):
 *   * a well steeper than DEVIATED_ABOVE_DEG: Mukherjee and Brill is the only coded correlation made
 *     for any angle (uphill and downhill); the vertical-flow ones only scale the gravity part by the
 *     pipe angle.
 *   * oil: Hagedorn and Brown does well in slug flow at moderate to high rates (its test well was
 *     mostly in slug flow); Duns and Ros covers mist flow and high GOR but was tested with less than
 *     10 % water (its paper); Beggs and Brill was built for pipelines and generally over-predicts the
 *     pressure drop in wells; Orkiszewski often matches well but his formulas jump where the flow
 *     pattern changes, and he found his method best for heavy oil (his paper); Ansari is a
 *     mechanistic model made for vertical wells.
 *   * gas: Gray holds up to a condensate ratio of about 50 STB/MMscf and with high water ratios;
 *     above that Duns and Ros is the usual choice; Hagedorn and Brown should not be used for
 *     condensates.
 * @param {AdviceInputs} inputs
 * @returns {Record<string, {rating: string, notes: string[]}>}
 */
export function correlation_advice(inputs) {
  const i = inputs;
  const is_oil = (i.fluid_type || "oil") === "oil";
  const incl = max_inclination_deg(i);
  const deviated = incl > DEVIATED_ABOVE_DEG;
  /** @type {Record<string, {rating: string, notes: string[]}>} */
  const advice = {};
  const put = (/** @type {string} */ key, /** @type {string} */ rating,
               /** @type {string[]} */ ...notes) => {
    advice[key] = { rating, notes: notes.filter((n) => n) };
  };

  const steep = `Made for vertical flow; this well reaches ${incl.toFixed(0)} degrees from vertical, `
    + "where the app only scales the gravity part by the pipe angle.";

  if (is_oil) {
    const wc = i.water_cut ?? 0.0;
    const api = i.api ?? 35.0;
    put("hagedorn_brown", deviated ? "caution" : "good",
        ...(deviated ? [steep]
                     : ["Performs well in slug flow at moderate to high rates: the test well behind "
                        + "the correlation (SPE 940-PA) was mostly in slug flow."]),
        "Poor at low rates (well loading) and not for mist flow.");
    put("mukherjee_brill", deviated ? "good" : "ok",
        deviated ? "Made for any angle, uphill or downhill."
                 : "Works at any angle; in a vertical well other correlations are better tested.");
    const notes = ["Its Region III was built for mist flow and it covers high gas-liquid ratios "
                   + "(Duns and Ros, 1963); it tends to over-predict the VLP of oil wells."];
    let rating = "ok";
    if (wc > DUNS_ROS_MAX_WATER_CUT) {
      rating = "caution";
      notes.unshift(`Tested with less than 10 % water; this well makes ${(100 * wc).toFixed(0)} %.`);
    }
    if (deviated) {
      rating = "caution";
      notes.unshift(steep);
    }
    put("duns_ros", rating, ...notes);
    const heavy = api < HEAVY_OIL_API;
    put("orkiszewski", deviated ? "caution" : (heavy ? "good" : "ok"),
        ...(deviated ? [steep] : []),
        ...(heavy ? ["Found best for heavy oil in the paper."] : []),
        "Often matches well, but his formulas jump where the flow pattern changes, so the traverse "
        + "can be unsteady.");
    put("ansari", deviated ? "caution" : "ok",
        deviated ? steep : "Mechanistic model made and tested for vertical wells.");
    put("beggs_brill", "caution",
        "Built from an inclined pipeline test loop (Beggs and Brill, 1973); it generally "
        + "over-predicts the pressure drop in vertical and deviated wells.");
    put("fancher_brown", "caution", QC_NOTE);
  } else {
    const cgr = i.cgr ?? 0.0;
    /** @type {string[]} */
    const gray_notes = [];
    let gray_rating = "good";
    if (cgr > GRAY_MAX_CGR) {
      gray_rating = "caution";
      gray_notes.push(`Good up to about ${GRAY_MAX_CGR.toFixed(0)} STB/MMscf of condensate; `
                      + `this well has ${cgr.toFixed(0)}.`);
    }
    if (deviated) {
      gray_rating = "caution";
      gray_notes.push(steep);
    }
    put("gray", gray_rating,
        ...(gray_notes.length ? gray_notes
                              : ["Made for gas wells (Gray, 1974); it holds up with condensate to "
                                 + "about 50 STB/MMscf and with high water ratios."]));
    put("duns_ros", (cgr > GRAY_MAX_CGR && !deviated) ? "good" : "ok",
        cgr > GRAY_MAX_CGR
          ? "The usual choice where the liquid dropout is very high; a retrograde-condensate PVT "
            + "would be needed too, which this app does not have."
          : "Handles mist flow, which is the usual pattern in a gas well.",
        ...(deviated ? [steep] : []));
    put("mukherjee_brill", deviated ? "good" : "ok",
        ...(deviated ? ["Made for any angle, uphill or downhill."] : []));
    put("hagedorn_brown", (cgr > 0 || deviated) ? "caution" : "ok",
        ...(cgr > 0 ? ["Should not be used for condensates, or where mist flow is the main pattern: "
                       + "its data came from an oil and water well."] : []),
        ...(deviated ? [steep] : []));
    put("orkiszewski", deviated ? "caution" : "ok", ...(deviated ? [steep] : []));
    put("ansari", deviated ? "caution" : "ok", ...(deviated ? [steep] : []));
    put("beggs_brill", "caution",
        "Mainly a pipeline correlation; tends to over- or under-estimate the pressure loss of a gas well.");
    put("fancher_brown", "caution", QC_NOTE,
        "Its friction lines were measured in an oil/water gas lift well, so a gas well is far "
        + "outside them.");
  }
  return advice;
}

/**
 * The correlation this app suggests for the well: the best rating from correlation_advice(), equal
 * ratings decided by PREFERENCE_OIL / PREFERENCE_GAS.
 * @param {AdviceInputs} inputs @returns {[string, string[]]} [key, reasons]
 */
export function recommend_correlation(inputs) {
  const advice = correlation_advice(inputs);
  const order = (inputs.fluid_type || "oil") === "oil" ? PREFERENCE_OIL : PREFERENCE_GAS;
  let best = order[0];
  let bestRank = [RATING_RANK[advice[best].rating], 0];
  order.forEach((k, index) => {
    const rank = [RATING_RANK[advice[k].rating], index];
    if (rank[0] < bestRank[0] || (rank[0] === bestRank[0] && rank[1] < bestRank[1])) {
      best = k;
      bestRank = rank;
    }
  });
  return [best, advice[best].notes];
}

/**
 * The sentences shown under the VLP correlation box: whether the correlation looks suitable for the
 * well entered, why, and the pointer to the comparison with measured data.
 * @param {AdviceInputs} inputs @param {string} key
 */
export function correlation_caption(inputs, key) {
  const advice = correlation_advice(inputs)[key];
  const name = nameOf(key);
  const phrase = { good: "looks well suited to this well",
                   ok: "should be usable for this well",
                   caution: "may not suit this well" }[advice.rating];
  let text = `${name} ${phrase}. ` + advice.notes.join(" ");
  const best = recommend_correlation(inputs)[0];
  if (best !== key) {
    text += ` From the fluid and well entered, the app would suggest ${nameOf(best)}.`;
  }
  return text + " This only uses the fluid, equipment and well path entered. If you have a downhole "
    + "pressure gauge reading or a flowing gradient survey, compare the correlations with it on the "
    + "VLP comparison tab and match the one you keep.";
}

/**
 * The extra paragraph some correlations get, so the page says the same thing the Streamlit app does.
 * @param {string} key @param {boolean} isOil
 */
export function correlation_detail(key, isOil) {
  /** @type {Record<string, string>} */
  const detail = {
    orkiszewski: "Orkiszewski (1967) was made for vertical oil and gas lift wells (it was found best "
      + "for heavy oil). In a deviated well the app uses it along the measured length with the "
      + "gravity part scaled by the pipe angle, so treat it as less certain there.",
    ansari: "Ansari et al (1994) is a mechanistic model: it picks the flow pattern (bubble, slug "
      + "or annular) from the physics and uses a separate model for each. It was developed and "
      + "tested on vertical wells; in a deviated well the app only scales the gravity part by the "
      + "pipe angle, so treat it as less certain there.",
    duns_ros: "Duns and Ros (1963) is a vertical-flow correlation with three flow regions "
      + "(bubble/plug/froth, slug and mist) and a transition between slug and mist. Its charts were "
      + "read from the paper, so expect small differences from other implementations. In a deviated "
      + "well the app only scales the gravity part by the pipe angle. It was made for less than 10 % "
      + "water.",
    mukherjee_brill: "Mukherjee and Brill (1983/1985) works at any angle, uphill or downhill, so it "
      + "is the one to try for deviated and horizontal sections.",
    fancher_brown: "Fancher and Brown (1963) treats gas and liquid as one fluid with no slip, so it "
      + "gives the lowest possible VLP and shows no well loading. It is useful only as a quality "
      + "check: a measured flowing pressure that falls below it means the fluid density (PVT) or the "
      + "pressure data are wrong. It was measured in a 2 3/8 in oil and water gas lift well; do not "
      + "use it for real predictions.",
  };
  let text = detail[key] || "";
  if (!isOil && ["beggs_brill", "hagedorn_brown", "orkiszewski", "duns_ros", "mukherjee_brill",
                 "ansari"].includes(key)) {
    text += (text ? " " : "")
      + "For gas wells that make a little condensate or water, Gray is the correlation made for the "
      + "job.";
  }
  return text;
}
