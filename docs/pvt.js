// @ts-check
/**
 * pvt.js - PVT correlations for the Integrated Well Modelling Tool (oilfield units).
 *
 * This is a direct translation of pvt.py.  Every function has the same name and the same
 * arguments in the same order as the Python one, and the equations are untouched, so the two
 * can be compared number for number (see tools/crosscheck.mjs).
 *
 * Units: pressure psia | temperature degF | Rs scf/STB | Bo rb/STB | Bg rcf/scf
 *        viscosity cP  | density lb/ft3   | gas gravity (air = 1) | API degrees
 *
 * NOTE ON PRESSURE: like the Python engine, everything here is ABSOLUTE pressure (psia).
 * The screen works in gauge pressure (psig); units.js is the only place the two meet.
 */

export const ATM_PSIA = 14.7;   // one atmosphere: the lowest bubble point oilProperties() will work with

// =====================================================================
// OIL  -  bubble point, Rs, Bo
// =====================================================================

/** Oil specific gravity from API gravity. @param {number} api @returns {number} */
export function sgOil(api) {
  return 141.5 / (api + 131.5);
}

// ---- Standing -------------------------------------------------------

/** Bubble point (psia) - Standing. @param {number} rs @param {number} gg @param {number} api @param {number} T */
export function pbStanding(rs, gg, api, T) {
  return Math.max(18.2 * ((rs / gg) ** 0.83 * 10 ** (0.00091 * T - 0.0125 * api) - 1.4), 14.7);
}

/** Solution GOR (scf/STB) - Standing. @param {number} p @param {number} gg @param {number} api @param {number} T */
export function rsStanding(p, gg, api, T) {
  return gg * ((p / 18.2 + 1.4) * 10 ** (0.0125 * api - 0.00091 * T)) ** 1.2048;
}

/** Oil formation volume factor (rb/STB) - Standing. @param {number} rs @param {number} gg @param {number} api @param {number} T */
export function boStanding(rs, gg, api, T) {
  const F = rs * Math.sqrt(gg / sgOil(api)) + 1.25 * T;
  return 0.9759 + 0.00012 * F ** 1.2;
}

// ---- Glaso ----------------------------------------------------------

/** Bubble point (psia) - Glaso. @param {number} rs @param {number} gg @param {number} api @param {number} T */
export function pbGlaso(rs, gg, api, T) {
  const pbs = (rs / gg) ** 0.816 * T ** 0.172 / api ** 0.989;
  const lg = Math.log10(pbs);
  return 10 ** (1.7669 + 1.7447 * lg - 0.30218 * lg ** 2);
}

/** Solution GOR (scf/STB) - Glaso. @param {number} p @param {number} gg @param {number} api @param {number} T */
export function rsGlaso(p, gg, api, T) {
  const lpb = 2.8869 - Math.sqrt(Math.max(14.1811 - 3.3093 * Math.log10(p), 0.0));
  return gg * (api ** 0.989 / T ** 0.172 * 10 ** lpb) ** 1.2255;
}

/** Oil formation volume factor (rb/STB) - Glaso. @param {number} rs @param {number} gg @param {number} api @param {number} T */
export function boGlaso(rs, gg, api, T) {
  const bstar = rs * (gg / sgOil(api)) ** 0.526 + 0.968 * T;
  const lb = Math.log10(bstar);
  return 1.0 + 10 ** (-6.58511 + 2.91329 * lb - 0.27683 * lb ** 2);
}

// ---- Lasater --------------------------------------------------------

/** Effective oil molecular weight used by Lasater. @param {number} api */
function moLasater(api) {
  return api <= 40 ? 630.0 - 10.0 * api : 73110.0 * api ** -1.562;
}

/** Bubble point (psia) - Lasater. @param {number} rs @param {number} gg @param {number} api @param {number} T */
export function pbLasater(rs, gg, api, T) {
  const n = rs / 379.3;
  const yg = n / (n + 350.0 * sgOil(api) / moLasater(api));
  const pf = yg <= 0.6 ? 0.679 * Math.exp(2.786 * yg) - 0.323 : 8.26 * yg ** 3.56 + 1.95;
  return pf * (T + 460.0) / gg;
}

/** Solution GOR (scf/STB) - Lasater. @param {number} p @param {number} gg @param {number} api @param {number} T */
export function rsLasater(p, gg, api, T) {
  const pf = p * gg / (T + 460.0);
  const yg = pf <= 3.29
    ? 0.359 * Math.log(1.473 * pf + 0.476)
    : (0.121 * pf - 0.236) ** 0.281;
  return 132755.0 * sgOil(api) * yg / (moLasater(api) * (1.0 - yg));
}

// Lasater gives no Bo correlation; Standing's Bo is used with it.
export const boLasater = boStanding;

// ---- Petrosky & Farshad --------------------------------------------

/** @param {number} api @param {number} T */
function xPf(api, T) {
  return 7.916e-4 * api ** 1.5410 - 4.561e-5 * T ** 1.3911;
}

/** Bubble point (psia) - Petrosky and Farshad. @param {number} rs @param {number} gg @param {number} api @param {number} T */
export function pbPetrosky(rs, gg, api, T) {
  return 112.727 * rs ** 0.577421 / (gg ** 0.8439 * 10 ** xPf(api, T)) - 1391.51;
}

/** Solution GOR (scf/STB) - Petrosky and Farshad. @param {number} p @param {number} gg @param {number} api @param {number} T */
export function rsPetrosky(p, gg, api, T) {
  return ((p / 112.727 + 12.340) * gg ** 0.8439 * 10 ** xPf(api, T)) ** 1.73184;
}

/** Oil formation volume factor (rb/STB) - Petrosky and Farshad. @param {number} rs @param {number} gg @param {number} api @param {number} T */
export function boPetrosky(rs, gg, api, T) {
  const go = sgOil(api);
  return 1.0113 + 7.2046e-5 * (rs ** 0.3738 * gg ** 0.2914 / go ** 0.6265 + 0.24626 * T ** 0.5371) ** 3.0936;
}

/** @type {Record<string, (rs: number, gg: number, api: number, T: number) => number>} */
export const PB_FUNCS = { glaso: pbGlaso, standing: pbStanding, lasater: pbLasater, petrosky: pbPetrosky };
/** @type {Record<string, (p: number, gg: number, api: number, T: number) => number>} */
export const RS_FUNCS = { glaso: rsGlaso, standing: rsStanding, lasater: rsLasater, petrosky: rsPetrosky };
/** @type {Record<string, (rs: number, gg: number, api: number, T: number) => number>} */
export const BO_FUNCS = { glaso: boGlaso, standing: boStanding, lasater: boLasater, petrosky: boPetrosky };

// =====================================================================
// OIL  -  viscosity
// =====================================================================

/** Dead-oil viscosity (cP) - Beal. @param {number} api @param {number} T */
export function muDeadBeal(api, T) {
  const a = 10 ** (0.43 + 8.33 / api);
  return (0.32 + 1.8e7 / api ** 4.53) * (360.0 / (T + 200.0)) ** a;
}

/** Dead-oil viscosity (cP) - Beggs and Robinson. @param {number} api @param {number} T */
export function muDeadBeggs(api, T) {
  const y = 10 ** (3.0324 - 0.02023 * api);
  return 10 ** (y * T ** -1.163) - 1.0;
}

/** Live-oil viscosity (cP) - Chew and Connally; used with Beal's dead oil. @param {number} mud @param {number} rs */
export function muLiveChewConnally(mud, rs) {
  const A = 10 ** (rs * (2.2e-7 * rs - 7.4e-4));
  const B = 0.68 / 10 ** (8.62e-5 * rs) + 0.25 / 10 ** (1.1e-3 * rs) + 0.062 / 10 ** (3.74e-3 * rs);
  return A * mud ** B;
}

/** Live-oil viscosity (cP) - Beggs and Robinson. @param {number} mud @param {number} rs */
export function muLiveBeggs(mud, rs) {
  return 10.715 * (rs + 100.0) ** -0.515 * mud ** (5.44 * (rs + 150.0) ** -0.338);
}

// Petrosky and Farshad (1995), Gulf of Mexico crude oils (SPE 29468).  T in degF, Rs in scf/STB, p in psia.
// Valid for roughly 16 - 45 API and 114 - 288 degF.

/** Dead-oil viscosity (cP) - Petrosky and Farshad. @param {number} api @param {number} T */
export function muDeadPetrosky(api, T) {
  const x = 4.59388 * Math.log10(T) - 22.82792;
  return 2.3511e7 * T ** -2.10255 * Math.log10(api) ** x;
}

/** Live-oil viscosity (cP) - Petrosky and Farshad. @param {number} mud @param {number} rs */
export function muLivePetrosky(mud, rs) {
  const a = 0.1651 + 0.6165 * 10 ** (-6.0866e-4 * rs);
  const b = 0.5131 + 0.5109 * 10 ** (-1.1831e-3 * rs);
  return a * mud ** b;
}

/** Undersaturated oil viscosity (cP) - Petrosky and Farshad. @param {number} mub @param {number} p @param {number} pb */
export function muUnderPetrosky(mub, p, pb) {
  const lg = Math.log10(mub);
  const a = -1.0146 + 1.3322 * lg - 0.4876 * lg ** 2 - 1.15036 * lg ** 3;
  return mub + 1.3449e-3 * (p - pb) * 10 ** a;
}

/** Undersaturated oil viscosity (cP) - Beal. @param {number} mub @param {number} p @param {number} pb */
export function muUnderBeal(mub, p, pb) {
  return mub + 0.001 * (p - pb) * (0.024 * mub ** 1.6 + 0.038 * mub ** 0.56);
}

/** Undersaturated oil viscosity (cP) - Vasquez and Beggs. @param {number} mub @param {number} p @param {number} pb */
export function muUnderVasquezBeggs(mub, p, pb) {
  const m = 2.6 * p ** 1.187 * Math.exp(-11.513 - 8.98e-5 * p);
  return mub * (p / pb) ** m;
}

// =====================================================================
// OIL  -  everything at one (p, T)
// =====================================================================

/**
 * Black-oil properties at pressure p (psia) and temperature T (degF).
 *
 * @param {number} p pressure, psia
 * @param {number} T temperature, degF
 * @param {number} api oil gravity, API
 * @param {number} gasSg gas gravity (air = 1)
 * @param {number} rsb solution GOR at the bubble point, scf/STB
 * @param {number|null} [pbMeas] optional measured bubble point; the correlations are matched to it
 *        by scaling pressure (calculated Pb -> measured Pb)
 * @param {string} [pvtMethod] 'glaso' | 'standing' | 'lasater' | 'petrosky'  (Pb, Rs, Bo)
 * @param {string} [viscMethod] 'beal' | 'beggs' | 'petrosky'
 * @param {{rs_exp?: number, bo_a?: number, bo_b?: number, mu_mult?: number}|null} [match]
 *        optional PVT-matching numbers found from lab data (see pvt_match.py):
 *          rs_exp     - Rs below Pb becomes  rsb * (Rs/rsb) ** rs_exp   (1 = unchanged)
 *          bo_a, bo_b - Bo becomes  bo_a * Bo + bo_b                    (1, 0 = unchanged)
 *          mu_mult    - oil viscosity is multiplied by this             (1 = unchanged)
 *        null = the correlations as published.
 * @returns {{pb: number, rs: number, bo: number, mu_o: number, rho_o: number, co: number|null}}
 */
export function oilProperties(p, T, api, gasSg, rsb, pbMeas = null,
                              pvtMethod = "glaso", viscMethod = "beal", match = null) {
  if (!(pvtMethod in PB_FUNCS)) throw new Error(`Unknown PVT method: ${pvtMethod}`);
  if (!["beal", "beggs", "petrosky"].includes(viscMethod)) {
    throw new Error(`Unknown viscosity method: ${viscMethod}`);
  }

  // The bubble point can come back non-physical when a correlation is used outside the data it was
  // fitted to.  Petrosky and Farshad were working on Gulf of Mexico oils with Rs from about 200 to
  // 1,900 scf/STB, and below roughly 100 scf/STB their equation turns NEGATIVE; Glaso and Lasater can
  // also fall below atmospheric.  A negative Pb poisons everything after it: with p >= pb the
  // Vasquez-Beggs viscosity raises (p/pb) to a fractional power, and a negative base there gives NaN
  // in JavaScript (and a complex number in Python).  So the calculated bubble point is held at
  // atmospheric or above.  pvt.py does exactly the same, for the same reason.
  const pbCalc = Math.max(PB_FUNCS[pvtMethod](rsb, gasSg, api, T), ATM_PSIA);
  const pb = pbMeas ? pbMeas : pbCalc;
  const scale = pbCalc / pb;
  const go = sgOil(api);

  const m = match || {};
  const rsExp = m.rs_exp ?? 1.0;

  let rs, bo, co;
  if (p >= pb) {
    rs = rsb;
    const bob = BO_FUNCS[pvtMethod](rsb, gasSg, api, T);
    // Vasquez-Beggs undersaturated compressibility
    co = (-1433.0 + 5.0 * rsb + 17.2 * T - 1180.0 * gasSg + 12.61 * api) / (1e5 * p);
    bo = bob * Math.exp(co * (pb - p));
  } else {
    // some correlations dip below 0 near 0 psia
    rs = Math.min(Math.max(RS_FUNCS[pvtMethod](p * scale, gasSg, api, T), 0.0), rsb);
    if (rsExp !== 1.0) {           // lab match: reshape the Rs curve, keeping Rs(Pb) = rsb
      rs = rsb * (rs / rsb) ** rsExp;
    }
    bo = BO_FUNCS[pvtMethod](rs, gasSg, api, T);
    co = null;
  }
  bo = (m.bo_a ?? 1.0) * bo + (m.bo_b ?? 0.0);

  // viscosity
  let mud, mub, muSat, mu;
  if (viscMethod === "beal") {
    mud = muDeadBeal(api, T);
    mub = muLiveChewConnally(mud, rsb);
    muSat = muLiveChewConnally(mud, rs);
    mu = p >= pb ? muUnderBeal(mub, p, pb) : muSat;
  } else if (viscMethod === "petrosky") {
    mud = muDeadPetrosky(api, T);
    mub = muLivePetrosky(mud, rsb);
    muSat = muLivePetrosky(mud, rs);
    mu = p >= pb ? muUnderPetrosky(mub, p, pb) : muSat;
  } else {
    mud = muDeadBeggs(api, T);
    mub = muLiveBeggs(mud, rsb);
    muSat = muLiveBeggs(mud, rs);
    mu = p >= pb ? muUnderVasquezBeggs(mub, p, pb) : muSat;
  }
  mu = (m.mu_mult ?? 1.0) * mu;

  const rho = (350.0 * go + 0.0764 * gasSg * rs) / (5.615 * bo);
  return { pb, rs, bo, mu_o: mu, rho_o: rho, co };
}

// =====================================================================
// GAS
// =====================================================================

/**
 * Sutton pseudo-criticals (degR, psia) with the Wichert-Aziz sour-gas correction.
 * y_h2s and y_co2 are mole fractions (0 - 1).
 * @param {number} gasSg @param {number} [yH2s] @param {number} [yCo2]
 * @returns {[number, number]} [Tpc degR, Ppc psia]
 */
export function gasPseudocritical(gasSg, yH2s = 0.0, yCo2 = 0.0) {
  let tpc = 169.2 + 349.5 * gasSg - 74.0 * gasSg ** 2;
  let ppc = 756.8 - 131.0 * gasSg - 3.6 * gasSg ** 2;
  if (yH2s > 0 || yCo2 > 0) {
    const A = yH2s + yCo2;
    const eps = 120.0 * (A ** 0.9 - A ** 1.6) + 15.0 * (yH2s ** 0.5 - yH2s ** 4);
    const tpcNew = tpc - eps;
    ppc = ppc * tpcNew / (tpc + yH2s * (1.0 - yH2s) * eps);
    tpc = tpcNew;
  }
  return [tpc, ppc];
}

const DAK = [0.3265, -1.0700, -0.5339, 0.01569, -0.05165, 0.5475,
             -0.7361, 0.1844, 0.1056, 0.6134, 0.7210];

/**
 * Dranchuk and Abou-Kassem Z-factor (valid roughly 1.0 < Tpr < 3.0, 0.2 < Ppr < 30).
 * The same 100-step bisection as the Python, so both give bit-for-bit the same root.
 * @param {number} ppr @param {number} tpr
 */
export function zDak(ppr, tpr) {
  const a = DAK;

  /** @param {number} rr */
  const zOf = (rr) => (
    1.0
    + (a[0] + a[1] / tpr + a[2] / tpr ** 3 + a[3] / tpr ** 4 + a[4] / tpr ** 5) * rr
    + (a[5] + a[6] / tpr + a[7] / tpr ** 2) * rr ** 2
    - a[8] * (a[6] / tpr + a[7] / tpr ** 2) * rr ** 5
    + a[9] * (1.0 + a[10] * rr ** 2) * (rr ** 2 / tpr ** 3) * Math.exp(-a[10] * rr ** 2)
  );

  /** root of g(rr) = 0 gives the reduced density @param {number} rr */
  const g = (rr) => zOf(rr) - 0.27 * ppr / (tpr * rr);

  let lo = 1e-6, hi = 3.0;
  for (let i = 0; i < 100; i++) {         // bisection
    const mid = 0.5 * (lo + hi);
    if (g(mid) > 0) hi = mid; else lo = mid;
  }
  return zOf(0.5 * (lo + hi));
}

/** Lee-Gonzalez-Eakin gas viscosity (cP). @param {number} p @param {number} T @param {number} gasSg @param {number} z */
export function muGasLee(p, T, gasSg, z) {
  const Tr = T + 460.0;
  const M = 28.97 * gasSg;
  const rho = 1.4935e-3 * p * M / (z * Tr);   // g/cc
  const K = (9.4 + 0.02 * M) * Tr ** 1.5 / (209.0 + 19.0 * M + Tr);
  const X = 3.5 + 986.0 / Tr + 0.01 * M;
  const Y = 2.4 - 0.2 * X;
  return 1e-4 * K * Math.exp(X * rho ** Y);
}

const DEMPSEY = [-2.46211820, 2.97054714, -2.86264054e-1, 8.05420522e-3,
                 2.80860949, -3.49803305, 3.60373020e-1, -1.04432413e-2,
                 -7.93385684e-1, 1.39643306, -1.49144925e-1, 4.41015512e-3,
                 8.39387178e-2, -1.86408848e-1, 2.03367881e-2, -6.09579263e-4];

/**
 * Carr-Kobayashi-Burrows gas viscosity: Standing's 1-atm viscosity plus the
 * Dempsey polynomial for the viscosity ratio (cP).  Hydrocarbon gas only.
 * @param {number} p @param {number} T @param {number} gasSg @param {number} ppr @param {number} tpr
 */
export function muGasCarr(p, T, gasSg, ppr, tpr) {
  const mu1 = (1.709e-5 - 2.062e-6 * gasSg) * T + 8.188e-3 - 6.15e-3 * Math.log10(gasSg);
  const a = DEMPSEY;
  let s = 0.0;
  for (let i = 0; i < 4; i++) {           // powers of Tpr
    s += tpr ** i * (a[4 * i] + a[4 * i + 1] * ppr + a[4 * i + 2] * ppr ** 2 + a[4 * i + 3] * ppr ** 3);
  }
  return mu1 * Math.exp(s) / tpr;
}

/**
 * Z, Bg (rcf/scf), density (lb/ft3) and viscosity (cP) of a gas at (p, T).
 * @param {number} p @param {number} T @param {number} gasSg
 * @param {number} [yH2s] @param {number} [yCo2] @param {string} [viscMethod] 'lee' | 'carr'
 * @returns {{z: number, bg: number, rho_g: number, mu_g: number, ppr: number, tpr: number}}
 */
export function gasProperties(p, T, gasSg, yH2s = 0.0, yCo2 = 0.0, viscMethod = "lee") {
  const [tpc, ppc] = gasPseudocritical(gasSg, yH2s, yCo2);
  const tpr = (T + 460.0) / tpc;
  const ppr = p / ppc;
  const z = zDak(ppr, tpr);
  const bg = 0.02827 * z * (T + 460.0) / p;
  const rho = 2.699 * gasSg * p / (z * (T + 460.0));
  let mu;
  if (viscMethod === "lee") mu = muGasLee(p, T, gasSg, z);
  else if (viscMethod === "carr") mu = muGasCarr(p, T, gasSg, ppr, tpr);
  else throw new Error(`Unknown gas viscosity method: ${viscMethod}`);
  return { z, bg, rho_g: rho, mu_g: mu, ppr, tpr };
}

/**
 * Well-stream gravity of a wet gas (McCain) from the separator gas gravity,
 * the condensate-gas ratio (STB/MMscf) and the condensate API.  Cragoe molecular weight.
 * @param {number} gasSg @param {number} cgrStbPerMmscf @param {number} condApi
 */
export function wetGasGravity(gasSg, cgrStbPerMmscf, condApi) {
  const R = 1e6 / cgrStbPerMmscf;         // scf/STB
  const go = sgOil(condApi);
  const Mo = 6084.0 / (condApi - 5.9);
  return (R * gasSg + 4602.0 * go) / (R + 133316.0 * go / Mo);
}

// =====================================================================
// WATER (McCain)
// =====================================================================

/**
 * Water salinity (wt %) from the specific gravity of the brine at standard conditions
 * (fresh water = 1.0, for example 1.02 for a sea-water-like brine).
 *
 * waterProperties() takes the standard-condition density as
 * 62.368 + 0.438603*S + 0.00160074*S^2 (lb/ft3, S in wt %), and fresh water is
 * 62.368 lb/ft3, so  sg = 1 + (0.438603*S + 0.00160074*S^2) / 62.368,
 * which is solved here for S (a quadratic).  1.02 -> 2.84 wt %,  1.05 -> 6.99 wt %.
 * @param {number} sg
 */
export function salinityFromSg(sg) {
  if (!(sg >= 1.0 && sg <= 1.25)) {
    throw new Error("Water specific gravity must be between 1.00 (fresh) and 1.25.");
  }
  const a = 1.60074e-3, b = 0.438603, c = -62.368 * (sg - 1.0);
  return (-b + Math.sqrt(b * b - 4.0 * a * c)) / (2.0 * a);
}

/**
 * Bw (rb/STB), density (lb/ft3) and viscosity (cP) of brine at (p, T).
 * @param {number} p @param {number} T @param {number} [salinityWtPct]
 * @returns {{bw: number, rho_w: number, mu_w: number}}
 */
export function waterProperties(p, T, salinityWtPct = 3.0) {
  const S = salinityWtPct;
  const dvt = -1.0001e-2 + 1.33391e-4 * T + 5.50654e-7 * T ** 2;
  const dvp = (-1.95301e-9 * p * T - 1.72834e-13 * p ** 2 * T
               - 3.58922e-7 * p - 2.25341e-10 * p ** 2);
  const bw = (1.0 + dvt) * (1.0 + dvp);
  const rhoSc = 62.368 + 0.438603 * S + 1.60074e-3 * S ** 2;
  const A = 109.574 - 8.40564 * S + 0.313314 * S ** 2 + 8.72213e-3 * S ** 3;
  const B = (-1.12166 + 2.63951e-2 * S - 6.79461e-4 * S ** 2
             - 5.47119e-5 * S ** 3 + 1.55586e-6 * S ** 4);
  const mu1 = A * T ** B;
  const mu = mu1 * (0.9994 + 4.0295e-5 * p + 3.1062e-9 * p ** 2);
  return { bw, rho_w: rhoSc / bw, mu_w: mu };
}
