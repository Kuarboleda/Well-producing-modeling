// @ts-check
/**
 * ipr.js - Inflow Performance Relationships (IPR), translated from ipr.py.
 *
 * An IPR answers one question:
 *     "If I hold the flowing bottom-hole pressure (Pwf) at this value,
 *      how much does the reservoir deliver?"
 *
 * Units (oilfield):
 *     pressure ........ psia            temperature ..... degF
 *     oil rate ........ STB/d           gas rate ........ Mscf/d (thousand scf/day)
 *     permeability k .. md              thickness h ..... ft
 *     viscosity ....... cP              radii re, rw .... ft
 *     Bo .............. rb/STB          gas gravity ..... air = 1
 *     PI (J) .......... STB/d/psi
 *
 * Every function keeps the SAME NAME and the SAME ARGUMENT ORDER as the Python, so the
 * cross-check can call both with one list of numbers.  Python takes some of these by keyword;
 * here they are positional, and IPR_PARAMS at the bottom gives each model's argument names so the
 * app can still pass a named object around (what `**inputs` does in the Python).
 *
 * Python's warnings.warn() has no equivalent in a browser, so warnings are collected in a list.
 * They never change a returned number; read them with takeWarnings() after a calculation.
 */

// ---------------------------------------------------------------------
// Constants (all for the oilfield units listed above)
// ---------------------------------------------------------------------
export const DARCY_OIL = 141.2;           // radial Darcy flow, oil
export const DARCY_GAS = 1422.0;          // radial Darcy flow, gas, with q in Mscf/d and T in degR
export const JONES_B_CONST = 3.161e-12;   // non-Darcy ("turbulence") term of the Jones equation

/** @type {string[]} */
let WARNINGS = [];

/**
 * Record a warning (the stand-in for Python's warnings.warn).  A curve is built by calling a model
 * once per point, so the same warning arrives many times; Python's warnings module shows it once, and
 * so does this.
 * @param {string} message
 */
function warn(message) {
  if (!WARNINGS.includes(message)) WARNINGS.push(message);
}

/** Return every warning raised since the last call, and empty the list. @returns {string[]} */
export function takeWarnings() {
  const out = WARNINGS;
  WARNINGS = [];
  return out;
}

// =====================================================================
// Small helper functions (used by the models further down)
// =====================================================================

/** Stop with a clear error message if an input does not make sense. @param {boolean} condition @param {string} message */
function check(condition, message) {
  if (!condition) throw new Error(message);
}

/** Round to a number of decimals, used only for a warning threshold. @param {number} x @param {number} nd */
function roundTo(x, nd) {
  const f = 10 ** nd;
  return Math.round(x * f) / f;
}

/** Sum of a list. @param {number[]} xs */
function sum(xs) {
  let t = 0.0;
  for (const x of xs) t += x;
  return t;
}

/**
 * Vogel shape: q/qmax = 1 - 0.2*x - 0.8*x^2, where x = pwf / (pressure at which the
 * curve starts).  Gives 1 at x = 0 (pwf = 0) and 0 at x = 1.
 * @param {number} x
 */
function vogelFraction(x) {
  return 1.0 - 0.2 * x - 0.8 * x ** 2;
}

/**
 * The oil IPR shape shared by PI, Vogel and Darcy.  It needs the productivity index J
 * (the slope of the straight-line part).
 *
 *     pwf >= Pb  : single-phase oil -> straight line  q = J * (Pr - Pwf)
 *     pwf <  Pb  : gas is coming out of solution -> Vogel curve, starting from the rate at Pb:
 *                  q = qb + qv * (1 - 0.2*(Pwf/Pb) - 0.8*(Pwf/Pb)^2)
 *                  with  qb = J*(Pr - Pb)   and   qv = J*Pb/1.8
 *
 * If Pr <= Pb the reservoir is already below the bubble point, so the whole curve is Vogel.
 * That is handled by pretending the "bubble point" is Pr itself (then qb = 0 and qv = J*Pr/1.8,
 * which is the usual Vogel qmax).
 * @param {number} p_res @param {number} pwf @param {number} pb @param {number} J
 */
function oilCompositeIpr(p_res, pwf, pb, J) {
  if (pwf >= p_res) return 0.0;              // no drawdown -> no flow

  const pbUsed = Math.min(pb, p_res);        // Pr <= Pb  ->  use Pr as the break point
  if (pwf >= pbUsed) return J * (p_res - pwf);   // straight-line (single-phase) part

  const qB = J * (p_res - pbUsed);           // rate at the break point (0 if Pr <= Pb)
  const qV = J * pbUsed / 1.8;               // extra rate the Vogel part can add
  return qB + qV * vogelFraction(pwf / pbUsed);
}

/** @param {number} p_res @param {number} pwf @param {number} pb */
function checkOilInputs(p_res, pwf, pb) {
  check(p_res > 0, "Reservoir pressure must be > 0.");
  check(pwf >= 0, "Flowing bottom-hole pressure cannot be negative.");
  check(pb >= 0, "Bubble-point pressure cannot be negative.");
}

/** @param {number} p_res @param {number} pwf */
function checkGasInputs(p_res, pwf) {
  check(p_res > 0, "Reservoir pressure must be > 0.");
  check(pwf >= 0, "Flowing bottom-hole pressure cannot be negative.");
}

// =====================================================================
// OIL 1 - PI (productivity index) entry
// =====================================================================

/**
 * Oil rate (STB/d) from a user-entered productivity index J (STB/d/psi).
 * Above Pb the IPR is a straight line with slope J; below Pb it bends into a Vogel curve.
 * @param {number} p_res @param {number} pwf @param {number} pb @param {number} J
 */
export function oil_pi(p_res, pwf, pb, J) {
  checkOilInputs(p_res, pwf, pb);
  check(J > 0, "PI (J) must be > 0.");
  return oilCompositeIpr(p_res, pwf, pb, J);
}

// =====================================================================
// OIL 2 - Vogel (needs ONE well test: rate and Pwf)
// =====================================================================

/**
 * Find the productivity index J (STB/d/psi) from one well test.
 *
 *   Case A: Pr <= Pb  (reservoir already below bubble point)
 *           whole IPR is Vogel:  qmax = q_test / (1 - 0.2*(Pwf/Pr) - 0.8*(Pwf/Pr)^2), J = 1.8*qmax/Pr
 *   Case B: Pr > Pb and test Pwf >= Pb  (test taken in the single-phase region)
 *           J = q_test / (Pr - Pwf_test)
 *   Case C: Pr > Pb and test Pwf < Pb  (test taken in the two-phase region)
 *           J = q_test / ( (Pr - Pb) + Pb/1.8 * (1 - 0.2*(Pwf/Pb) - 0.8*(Pwf/Pb)^2) )
 * @param {number} p_res @param {number} pb @param {number} q_test @param {number} pwf_test
 */
export function vogel_productivity_index(p_res, pb, q_test, pwf_test) {
  check(p_res > 0, "Reservoir pressure must be > 0.");
  check(pb >= 0, "Bubble-point pressure cannot be negative.");
  check(q_test > 0, "Test rate must be > 0.");
  check(0 <= pwf_test && pwf_test < p_res, "Test Pwf must be >= 0 and below the reservoir pressure.");

  if (p_res <= pb) {                                     // Case A
    const qmax = q_test / vogelFraction(pwf_test / p_res);
    return 1.8 * qmax / p_res;
  } else if (pwf_test >= pb) {                           // Case B
    return q_test / (p_res - pwf_test);
  }
  const denominator = (p_res - pb) + (pb / 1.8) * vogelFraction(pwf_test / pb);   // Case C
  return q_test / denominator;
}

/**
 * Oil rate (STB/d) from the Vogel IPR, calibrated with one well test.
 * @param {number} p_res @param {number} pwf @param {number} pb @param {number} q_test @param {number} pwf_test
 */
export function oil_vogel(p_res, pwf, pb, q_test, pwf_test) {
  checkOilInputs(p_res, pwf, pb);
  const J = vogel_productivity_index(p_res, pb, q_test, pwf_test);
  return oilCompositeIpr(p_res, pwf, pb, J);
}

// =====================================================================
// OIL 3 - Darcy (pseudo-steady-state radial flow)
// =====================================================================

/**
 * Productivity index J (STB/d/psi) from reservoir properties:
 *     J = k*h / ( 141.2 * Bo * mu * ( ln(re/rw) - 3/4 + S ) )
 * @param {number} k @param {number} h @param {number} bo @param {number} mu
 * @param {number} re @param {number} rw @param {number} [skin]
 */
export function darcy_productivity_index_oil(k, h, bo, mu, re, rw, skin = 0.0) {
  check(k > 0 && h > 0, "k and h must be > 0.");
  check(bo > 0 && mu > 0, "Bo and viscosity must be > 0.");
  check(re > rw && rw > 0, "Drainage radius must be larger than wellbore radius (both > 0).");
  const bracket = Math.log(re / rw) - 0.75 + skin;
  check(bracket > 0, "ln(re/rw) - 0.75 + skin must be > 0 (is the skin too negative?).");
  return k * h / (DARCY_OIL * bo * mu * bracket);
}

/**
 * Oil rate (STB/d) using J from Darcy's law.
 * @param {number} p_res @param {number} pwf @param {number} pb @param {number} k @param {number} h
 * @param {number} bo @param {number} mu @param {number} re @param {number} rw @param {number} [skin]
 */
export function oil_darcy(p_res, pwf, pb, k, h, bo, mu, re, rw, skin = 0.0) {
  checkOilInputs(p_res, pwf, pb);
  const J = darcy_productivity_index_oil(k, h, bo, mu, re, rw, skin);
  return oilCompositeIpr(p_res, pwf, pb, J);
}

// =====================================================================
// OIL 3b - Darcy, other flow regimes: steady state and transient
// =====================================================================

/**
 * Productivity index J (STB/d/psi) for STEADY-STATE radial flow (pressure held at re):
 *     J = k*h / ( 141.2 * Bo * mu * ( ln(re/rw) + S ) )
 * The only difference from pseudosteady state is the missing "- 3/4".
 * @param {number} k @param {number} h @param {number} bo @param {number} mu
 * @param {number} re @param {number} rw @param {number} [skin]
 */
export function darcy_productivity_index_oil_steady(k, h, bo, mu, re, rw, skin = 0.0) {
  check(k > 0 && h > 0, "k and h must be > 0.");
  check(bo > 0 && mu > 0, "Bo and viscosity must be > 0.");
  check(re > rw && rw > 0, "Drainage radius must be larger than wellbore radius (both > 0).");
  const bracket = Math.log(re / rw) + skin;
  check(bracket > 0, "ln(re/rw) + skin must be > 0 (is the skin too negative?).");
  return k * h / (DARCY_OIL * bo * mu * bracket);
}

/**
 * Productivity index J (STB/d/psi) for TRANSIENT (infinite-acting) radial flow, "J after t hours":
 *     J = k*h / ( 162.6 * Bo * mu * ( log10(t) + log10( k/(phi*mu*ct*rw^2) ) - 3.23 + 0.87*S ) )
 * J keeps falling with time until the boundary is felt - see transient_end_time_hours().
 * @param {number} k @param {number} h @param {number} bo @param {number} mu @param {number} phi
 * @param {number} ct @param {number} rw @param {number} time_hours @param {number} [skin]
 */
export function darcy_productivity_index_oil_transient(k, h, bo, mu, phi, ct, rw, time_hours, skin = 0.0) {
  check(k > 0 && h > 0, "k and h must be > 0.");
  check(bo > 0 && mu > 0, "Bo and viscosity must be > 0.");
  check(phi > 0 && ct > 0, "Porosity and total compressibility must be > 0.");
  check(rw > 0, "Wellbore radius must be > 0.");
  check(time_hours > 0, "Flowing time must be > 0 hours.");
  const bracket = (Math.log10(time_hours) + Math.log10(k / (phi * mu * ct * rw ** 2))
                   - 3.23 + 0.87 * skin);
  check(bracket > 0, "The transient bracket is <= 0: time is too short for this equation "
                     + "(or the skin is too negative).");
  return k * h / (162.6 * bo * mu * bracket);
}

/**
 * Approximate time (hours) when the pressure disturbance reaches the outer boundary re:
 *     t_end = 948 * phi*mu*ct*re^2 / k     (the usual "tDA = 0.1" rule of thumb).
 * @param {number} k @param {number} phi @param {number} mu @param {number} ct @param {number} re
 */
export function transient_end_time_hours(k, phi, mu, ct, re) {
  check(k > 0 && phi > 0 && mu > 0 && ct > 0 && re > 0, "All inputs must be > 0.");
  return 948.0 * phi * mu * ct * re ** 2 / k;
}

/**
 * Oil rate (STB/d) from Darcy's law for a chosen flow regime:
 *   regime = "pseudosteady" closed drainage area (same as oil_darcy)
 *   regime = "steady"       constant pressure at re
 *   regime = "transient"    infinite-acting; needs phi, ct and time_hours
 * @param {number} p_res @param {number} pwf @param {number} pb @param {number} k @param {number} h
 * @param {number} bo @param {number} mu @param {number} re @param {number} rw @param {number} [skin]
 * @param {string} [regime] @param {number|null} [phi] @param {number|null} [ct] @param {number|null} [time_hours]
 */
export function oil_darcy_regime(p_res, pwf, pb, k, h, bo, mu, re, rw, skin = 0.0,
                                 regime = "pseudosteady", phi = null, ct = null, time_hours = null) {
  checkOilInputs(p_res, pwf, pb);
  let J;
  if (regime === "pseudosteady") {
    J = darcy_productivity_index_oil(k, h, bo, mu, re, rw, skin);
  } else if (regime === "steady") {
    J = darcy_productivity_index_oil_steady(k, h, bo, mu, re, rw, skin);
  } else if (regime === "transient") {
    check(phi !== null && ct !== null && time_hours !== null,
          "The transient regime needs phi, ct and time_hours.");
    J = darcy_productivity_index_oil_transient(k, h, bo, mu, /** @type {number} */ (phi),
                                               /** @type {number} */ (ct), rw,
                                               /** @type {number} */ (time_hours), skin);
    const tEnd = transient_end_time_hours(k, /** @type {number} */ (phi), mu, /** @type {number} */ (ct), re);
    if (/** @type {number} */ (time_hours) > tEnd) {
      warn(`${Math.round(/** @type {number} */ (time_hours))} h is later than about ${Math.round(tEnd)} h, `
           + "when the pressure disturbance reaches the boundary - the transient result is no longer "
           + "valid; use the pseudosteady regime.");
    }
  } else {
    throw new Error("regime must be 'pseudosteady', 'steady' or 'transient'.");
  }
  return oilCompositeIpr(p_res, pwf, pb, J);
}

// =====================================================================
// OIL 3c - Horizontal well, Joshi (1988)
// =====================================================================

/**
 * Productivity index J (STB/d/psi) of a HORIZONTAL oil well, Joshi (1988), as printed in
 * Guo, "Reservoir Deliverability", equations 3.11 - 3.13.
 *
 *     J = kh*h / ( 141.2*Bo*mu * { ln[ (a + sqrt(a^2 - (L/2)^2)) / (L/2) ]
 *                                   + (Iani*h/L) * ( ln[ Iani*h / (rw*(Iani+1)) ] + S ) } )
 *     a    = (L/2) * sqrt( 0.5 + sqrt( 0.25 + (re_h/(L/2))^4 ) )
 *     Iani = sqrt( kh / kv )
 *
 * ASSUMPTION ON SKIN: Guo's slide has no skin term.  S is added inside the second bracket, so it is
 * weighted by Iani*h/L (the usual way to add mechanical skin to Joshi's equation: it acts around the
 * wellbore, that is, in the vertical-plane part).
 * @param {number} kh @param {number} kv @param {number} h @param {number} length
 * @param {number} re_h @param {number} rw @param {number} bo @param {number} mu @param {number} [skin]
 */
export function horizontal_productivity_index_oil_joshi(kh, kv, h, length, re_h, rw, bo, mu, skin = 0.0) {
  check(kh > 0 && kv > 0, "Horizontal and vertical permeability must be > 0.");
  check(h > 0 && length > 0, "Thickness and well length must be > 0.");
  check(bo > 0 && mu > 0, "Bo and viscosity must be > 0.");
  check(rw > 0, "Wellbore radius must be > 0.");
  check(re_h > length / 2.0,
        "The drainage radius re_h must be larger than half the well length (L/2).");
  if (length / 2.0 > 0.9 * re_h) {
    warn("Joshi's equation is intended for L/2 < 0.9*re_h; this well is almost as long as its "
         + "drainage area - treat the result with care.");
  }
  const iAni = Math.sqrt(kh / kv);
  const half = length / 2.0;
  const a = half * Math.sqrt(0.5 + Math.sqrt(0.25 + (re_h / half) ** 4));
  const horizontalPlane = Math.log((a + Math.sqrt(a * a - half * half)) / half);
  const verticalPlane = (iAni * h / length) * (Math.log(iAni * h / (rw * (iAni + 1.0))) + skin);
  const bracket = horizontalPlane + verticalPlane;
  check(bracket > 0, "The Joshi bracket is <= 0 (is the skin too negative?).");
  return kh * h / (DARCY_OIL * bo * mu * bracket);
}

/**
 * Oil rate (STB/d) of a horizontal well using Joshi's J.
 * @param {number} p_res @param {number} pwf @param {number} pb @param {number} kh @param {number} kv
 * @param {number} h @param {number} length @param {number} re_h @param {number} rw
 * @param {number} bo @param {number} mu @param {number} [skin]
 */
export function oil_horizontal_joshi(p_res, pwf, pb, kh, kv, h, length, re_h, rw, bo, mu, skin = 0.0) {
  checkOilInputs(p_res, pwf, pb);
  const J = horizontal_productivity_index_oil_joshi(kh, kv, h, length, re_h, rw, bo, mu, skin);
  return oilCompositeIpr(p_res, pwf, pb, J);
}

// =====================================================================
// OIL 3d - Horizontal well, Kuchuk and Goode (SPE 21460, 1991)
// =====================================================================
// A horizontal well parallel to the x axis in a closed rectangular box Lx x Ly x h (all sides sealed;
// the top may instead be a constant-pressure boundary such as a gas cap or an aquifer).  The well has
// length L = 2*L_half, is centred at x = xw, sits at y = yw across the width and z = zw above the bottom.
// kx is along the well, ky across it.
//
//   J (STB/d/psi) = 7.08e-3 * kH * h / ( mu * Bo * (pwD + S*m) ),  kH = sqrt(kx*ky)        paper Eq. 3
//   S*m = (h / (2*L_half)) * sqrt(kx/kz) * Sm   (Sm = mechanical skin)                      paper Eq. 4
//   pwD = dimensionless pseudosteady pressure drop (sealed top: Eq. 6, 7; constant-pressure top: Eq. B-3)

/**
 * Ki2(beta) = integral from 0 to infinity of exp(-beta*cosh(u)) / cosh(u)^2 du  (paper Eq. A-22).
 * Simpson's rule with the same 4,000 intervals as the Python, so both give the same number.
 * Checked against the paper's Table 1 (for example Ki2(1) = 0.27362, Ki2(0.1) = 0.86252).
 * @param {number} beta
 */
export function bickley_ki2(beta) {
  check(beta > 0, "Ki2 needs beta > 0.");
  const n = 4000;                                    // even number of intervals
  const top = 25.0;
  const step = top / n;
  let total = 0.0;
  for (let k = 0; k <= n; k++) {
    const u = k * step;
    const value = Math.exp(-beta * Math.cosh(u)) / Math.cosh(u) ** 2;
    const weight = (k === 0 || k === n) ? 1 : (k % 2 !== 0 ? 4 : 2);
    total += weight * value;
  }
  return total * step / 3.0;
}

/**
 * Dimensionless pseudosteady-state pressure drop pwD of a horizontal well (Kuchuk and Goode).
 * pwD does not contain the mechanical skin (that is added separately, see the PI function).
 * @param {number} kx along the well (md) @param {number} ky across it (md) @param {number} kz vertical (md)
 * @param {number} h thickness (ft) @param {number} lx box length along the well (ft)
 * @param {number} ly box width across it (ft) @param {number} length well length L = 2*L_half (ft)
 * @param {number} xw x of the well CENTRE, 0..lx (ft) @param {number} yw y across the box, 0..ly (ft)
 * @param {number} zw height above the bottom, 0..h (ft) @param {number} rw wellbore radius (ft)
 * @param {string} [top] "sealed" (Eq. 6) or "constant_pressure" (Eq. B-3; the box size is then unused)
 */
export function horizontal_pwd_kuchuk_goode(kx, ky, kz, h, lx, ly, length, xw, yw, zw, rw, top = "sealed") {
  /** @type {[string, number][]} */
  const named = [["kx", kx], ["ky", ky], ["kz", kz], ["h", h], ["lx", lx], ["ly", ly],
                 ["length", length], ["rw", rw]];
  for (const [name, v] of named) check(v > 0, `${name} must be > 0.`);
  const half = length / 2.0;
  check(0 < zw && zw < h, "The well must be inside the thickness (0 < zw < h).");
  const rEq = 0.5 * rw * (1.0 + Math.sqrt(kz / ky));         // r'w, paper Eq. 7b
  const hD = (h / half) * Math.sqrt(kx / kz);                // scaled thickness
  const zRatio = zw / h;

  if (top === "constant_pressure") {
    // Eq. B-3 in the scaled variables of Appendix A (this is the form that follows from Appendix B;
    // the printed Eq. 11 has 8h where the same algebra gives 4h - see the note in the README)
    const rD = (rw / (2.0 * half)) * (Math.sqrt(kx / ky) + Math.sqrt(kx / kz));    // Eq. A-1g
    const zD = (zw / half) * Math.sqrt(kx / kz);
    const main = 0.5 * hD * (Math.log(4.0 * hD / (Math.PI * rD) / Math.tan(Math.PI * zRatio / 2.0)) + zD - hD);
    let series = 0.0;
    for (let j = 1; j < 60; j++) {
      const a = 2 * j - 1;
      const term = (1.0 / a ** 2) * bickley_ki2(a * Math.PI / hD) * Math.cos(a * Math.PI * zRatio / 2.0) ** 2;
      series += term;
      if (a * Math.PI / hD > 40) break;
    }
    return main + 4.0 * hD ** 2 / Math.PI ** 2 * series;
  }

  check(top === "sealed", "top must be 'sealed' or 'constant_pressure'.");
  check(0 <= xw && xw <= lx && 0 <= yw && yw <= ly, "The well centre must be inside the drainage box.");
  check(xw - half >= -1e-9 && xw + half <= lx + 1e-9,
        "The well must lie inside the drainage box along x (L/2 <= xw <= Lx - L/2).");
  const rootXy = Math.sqrt(kx / ky);
  // areal part, first term of Eq. 6
  let pwd = (2.0 * Math.PI * ly / lx) * rootXy * (1.0 / 3.0 - yw / ly + (yw / ly) ** 2);
  // series in n, second term of Eq. 6 (converges like 1/n^3)
  let total = 0.0;
  for (let n = 1; n < 400; n++) {
    const xiX = Math.sin(n * Math.PI * half / lx) * Math.cos(n * Math.PI * xw / lx) / n;      // Eq. 7e
    const alpha = -(2.0 * n * Math.PI / lx) * rootXy;                                        // Eq. 7d
    const eLy = Math.exp(alpha * ly), eBack = Math.exp(alpha * (ly - yw)), eYw = Math.exp(alpha * yw);
    const xi = (2.0 * eLy + eBack + eYw) / (1.0 - eLy);                                      // Eq. 7c
    total += xiX ** 2 * (1.0 + xi) / n;
  }
  pwd += 2.0 * lx ** 2 / (Math.PI ** 2 * half ** 2) * total;
  // geometric skin from the partial penetration in z, Eq. 7a ...
  let sZd = -(hD / 2.0) * (Math.log(Math.PI * rEq / h * 2.0 * Math.sin(Math.PI * zRatio))
                           + hD * (1.0 / 3.0 - zRatio + zRatio ** 2));
  // ... plus the extra series of Eq. A-21 (negligible when h_d < 5, the usual case)
  let extra = 0.0;
  for (let j = 1; j < 400; j++) {
    const beta = 2.0 * j * Math.PI / hD;
    if (beta > 40.0) break;
    extra += bickley_ki2(beta) * Math.cos(j * Math.PI * zRatio) ** 2 / j ** 2;
  }
  sZd -= hD ** 2 / Math.PI ** 2 * extra;
  return pwd + sZd;
}

/**
 * Productivity index J (STB/d/psi) of a horizontal oil well, Kuchuk and Goode Eq. 3.
 * kh = kx along the well; ky = ky_ratio * kh across it; kv = kz.
 * skin = the mechanical skin Sm; it enters as S*m = (h/L) * sqrt(kx/kz) * Sm (Eq. 4, L = 2*L_half).
 * @param {number} kh @param {number} kv @param {number} h @param {number} length @param {number} lx
 * @param {number} ly @param {number} xw @param {number} yw @param {number} zw @param {number} rw
 * @param {number} bo @param {number} mu @param {number} [skin] @param {number} [ky_ratio] @param {string} [top]
 */
export function horizontal_productivity_index_oil_kuchuk_goode(kh, kv, h, length, lx, ly, xw, yw, zw, rw, bo, mu,
                                                               skin = 0.0, ky_ratio = 1.0, top = "sealed") {
  check(kh > 0 && kv > 0 && ky_ratio > 0, "Permeabilities must be > 0.");
  check(bo > 0 && mu > 0, "Bo and viscosity must be > 0.");
  const kx = kh, ky = ky_ratio * kh, kz = kv;
  const pwd = horizontal_pwd_kuchuk_goode(kx, ky, kz, h, lx, ly, length, xw, yw, zw, rw, top);
  const sStar = (h / length) * Math.sqrt(kx / kz) * skin;
  check(pwd + sStar > 0, "pwD + skin is <= 0 (is the skin too negative?).");
  return (1.0 / DARCY_OIL) * Math.sqrt(kx * ky) * h / (mu * bo * (pwd + sStar));
}

/**
 * Oil rate (STB/d) of a horizontal well using the Kuchuk-Goode J.
 * @param {number} p_res @param {number} pwf @param {number} pb @param {number} kh @param {number} kv
 * @param {number} h @param {number} length @param {number} lx @param {number} ly @param {number} xw
 * @param {number} yw @param {number} zw @param {number} rw @param {number} bo @param {number} mu
 * @param {number} [skin] @param {number} [ky_ratio] @param {string} [top]
 */
export function oil_horizontal_kuchuk_goode(p_res, pwf, pb, kh, kv, h, length, lx, ly, xw, yw, zw, rw, bo, mu,
                                            skin = 0.0, ky_ratio = 1.0, top = "sealed") {
  checkOilInputs(p_res, pwf, pb);
  const J = horizontal_productivity_index_oil_kuchuk_goode(kh, kv, h, length, lx, ly, xw, yw, zw, rw, bo, mu,
                                                           skin, ky_ratio, top);
  return oilCompositeIpr(p_res, pwf, pb, J);
}

// =====================================================================
// OIL 5 - Multilayer (commingled layers, each with its own pressure and PI)
// =====================================================================

/**
 * @typedef {{p_res: number, J: number, wc?: number|null, gor?: number|null}} OilLayer
 */

/**
 * The liquid rate (STB/d) of each layer at one flowing pressure, in the order of `layers`.
 * A layer below the flowing pressure gives 0, or a negative number (it takes fluid from the
 * wellbore) when crossflow is true.
 * @param {number} p_res @param {number} pwf @param {number} pb
 * @param {OilLayer[]} layers @param {boolean} [crossflow]
 * @returns {number[]}
 */
export function multilayer_rates(p_res, pwf, pb, layers, crossflow = false) {
  check(layers.length >= 1, "Multilayer IPR needs at least one layer.");
  checkOilInputs(p_res, pwf, pb);
  const rates = [];
  for (let i = 0; i < layers.length; i++) {
    const layer = layers[i], k = i + 1;
    check(layer.p_res > 0, `Layer ${k}: reservoir pressure must be > 0.`);
    check(layer.J > 0, `Layer ${k}: productivity index must be > 0.`);
    if (pwf < layer.p_res) {
      rates.push(oilCompositeIpr(layer.p_res, pwf, pb, layer.J));
    } else if (crossflow) {
      rates.push(layer.J * (layer.p_res - pwf));        // negative: the layer is taking fluid
    } else {
      rates.push(0.0);
    }
  }
  return rates;
}

/**
 * Liquid rate (STB/d) of several layers producing into the same well at the same flowing pressure.
 * Each layer follows the usual oil IPR (straight line above Pb, Vogel below it).  All layers are
 * referred to the same depth and share one bubble point.
 * @param {number} p_res @param {number} pwf @param {number} pb
 * @param {OilLayer[]} layers @param {boolean} [crossflow]
 */
export function oil_multilayer(p_res, pwf, pb, layers, crossflow = false) {
  return sum(multilayer_rates(p_res, pwf, pb, layers, crossflow));
}

/**
 * What the commingled layers produce at one flowing pressure.  Every producing layer adds its
 * liquid; its water is liquid*wc, its oil is liquid*(1-wc) and its gas is oil*gor.  When no layer
 * produces, the layers are weighted by their PI.
 * @param {number} p_res @param {number} pwf @param {number} pb @param {OilLayer[]} layers
 * @param {number} [default_wc] @param {number|null} [default_gor] @param {boolean} [crossflow]
 * @returns {{q: number, q_layers: number[], water_cut: number, gor: number|null}}
 */
export function multilayer_mix(p_res, pwf, pb, layers, default_wc = 0.0, default_gor = null, crossflow = false) {
  const rates = multilayer_rates(p_res, pwf, pb, layers, crossflow);
  let weights = rates.map((q) => Math.max(q, 0.0));
  if (sum(weights) <= 0.0) weights = layers.map((layer) => layer.J);
  let water = 0.0, oil = 0.0, gas = 0.0;
  for (let i = 0; i < layers.length; i++) {
    const layer = layers[i], w = weights[i];
    const wcRaw = layer.wc ?? null;
    const wc = wcRaw === null ? default_wc : wcRaw;
    const gorRaw = layer.gor ?? null;
    const gor = gorRaw === null ? default_gor : gorRaw;
    water += w * wc;
    oil += w * (1.0 - wc);
    gas += w * (1.0 - wc) * (gor || 0.0);
  }
  const liquid = water + oil;
  return { q: sum(rates), q_layers: rates,
           water_cut: liquid > 0 ? water / liquid : default_wc,
           gor: oil > 0 ? gas / oil : default_gor };
}

/**
 * The flowing pressure (psia) at which the commingled layers give the liquid rate q (the IPR turned
 * round), by halving the interval.  A rate above the AOF gives 0, a rate of 0 or less gives the
 * highest layer pressure.
 * @param {number} q @param {number} p_res @param {number} pb @param {OilLayer[]} layers @param {boolean} [crossflow]
 */
export function multilayer_pwf(q, p_res, pb, layers, crossflow = false) {
  const pMax = Math.max(...layers.map((layer) => layer.p_res));
  if (q <= 0.0) return pMax;
  if (sum(multilayer_rates(p_res, 0.0, pb, layers, crossflow)) <= q) return 0.0;   // more than the AOF
  let lo = 0.0, hi = pMax;
  for (let i = 0; i < 60; i++) {
    const mid = 0.5 * (lo + hi);
    if (sum(multilayer_rates(p_res, mid, pb, layers, crossflow)) > q) lo = mid; else hi = mid;
    if (hi - lo < 1e-6) break;
  }
  return 0.5 * (lo + hi);
}

// =====================================================================
// Fetkovich (oil) and back-pressure (gas) share the same equation:
//       q = C * (Pr^2 - Pwf^2)^n
// =====================================================================

/**
 * Find C and n from two well tests (q1 at pwf1, q2 at pwf2).
 *     n = log(q1/q2) / log( (Pr^2 - Pwf1^2) / (Pr^2 - Pwf2^2) )
 *     C = q1 / (Pr^2 - Pwf1^2)^n
 * n should lie between 0.5 (fully turbulent) and 1.0 (fully laminar).
 * @param {number} p_res @param {number} q1 @param {number} pwf1 @param {number} q2 @param {number} pwf2
 * @returns {[number, number]} [C, n]
 */
export function c_and_n_from_two_tests(p_res, q1, pwf1, q2, pwf2) {
  check(p_res > 0, "Reservoir pressure must be > 0.");
  check(q1 > 0 && q2 > 0, "Both test rates must be > 0.");
  check(0 <= pwf1 && pwf1 < p_res && 0 <= pwf2 && pwf2 < p_res,
        "Test Pwf values must be >= 0 and below the reservoir pressure.");
  check(pwf1 !== pwf2, "The two tests need different flowing pressures.");
  check(q1 !== q2, "The two tests need different rates (otherwise n = 0).");

  const dp2_1 = p_res ** 2 - pwf1 ** 2;        // "pressure-squared drawdown" of test 1
  const dp2_2 = p_res ** 2 - pwf2 ** 2;        // ... and of test 2
  const n = Math.log10(q1 / q2) / Math.log10(dp2_1 / dp2_2);
  check(n > 0, "Test data gives n <= 0: the larger drawdown must give the larger rate.");
  if (roundTo(n, 4) < 0.5 || roundTo(n, 4) > 1.0) {    // rounding avoids false alarms from 0.49999999
    warn(`n = ${n.toFixed(3)} is outside the usual range 0.5-1.0 - please check the test data.`);
  }
  const C = q1 / dp2_1 ** n;
  return [C, n];
}

/**
 * Oil rate (STB/d) from Fetkovich's equation q = C*(Pr^2 - Pwf^2)^n, with C and n from two tests.
 * @param {number} p_res @param {number} pwf @param {number} q1 @param {number} pwf1
 * @param {number} q2 @param {number} pwf2
 */
export function oil_fetkovich(p_res, pwf, q1, pwf1, q2, pwf2) {
  check(p_res > 0, "Reservoir pressure must be > 0.");
  check(pwf >= 0, "Flowing bottom-hole pressure cannot be negative.");
  const [C, n] = c_and_n_from_two_tests(p_res, q1, pwf1, q2, pwf2);
  if (pwf >= p_res) return 0.0;
  return C * (p_res ** 2 - pwf ** 2) ** n;
}

// =====================================================================
// GAS - Darcy and Jones (pressure-squared form)
// =====================================================================
// For gas we work with pressure squared.  Both models solve
//       Pr^2 - Pwf^2 = a*q + b*q^2
// a*q = laminar (Darcy) loss, b*q^2 = turbulent (non-Darcy) loss.  Darcy is the case b = 0.
// z and mu are normally taken at the AVERAGE pressure (Pr + Pwf)/2 and the reservoir temperature.

/**
 * Laminar (Darcy) coefficient 'a' in psi^2 per (Mscf/d):
 *     a = 1422 * T * mu * z * ( ln(re/rw) - 3/4 + S ) / (k*h)      T in degR
 * @param {number} temp_f @param {number} k @param {number} h @param {number} mu @param {number} z
 * @param {number} re @param {number} rw @param {number} [skin]
 */
export function gas_a_coefficient(temp_f, k, h, mu, z, re, rw, skin = 0.0) {
  check(k > 0 && h > 0, "k and h must be > 0.");
  check(mu > 0 && z > 0, "Gas viscosity and Z must be > 0.");
  check(re > rw && rw > 0, "Drainage radius must be larger than wellbore radius (both > 0).");
  const bracket = Math.log(re / rw) - 0.75 + skin;
  check(bracket > 0, "ln(re/rw) - 0.75 + skin must be > 0 (is the skin too negative?).");
  const tempR = temp_f + 460.0;                            // degF -> degR
  return DARCY_GAS * tempR * mu * z * bracket / (k * h);
}

/**
 * Estimate the non-Darcy (turbulence) factor beta in 1/ft from permeability k (md):
 * beta = 2.73e10 / k^1.1045  (Firoozabadi and Katz).  Only an estimate.
 * @param {number} k
 */
export function gas_beta_firoozabadi_katz(k) {
  check(k > 0, "k must be > 0.");
  return 2.73e10 / k ** 1.1045;
}

/**
 * Turbulent (non-Darcy) coefficient 'b' in psi^2 per (Mscf/d)^2:
 *     b = 3.161e-12 * beta * T * gas_sg * z / ( h_perf^2 * rw )      T in degR
 * h_perf = perforated (open) thickness in ft.  beta in 1/ft (estimated from k if null).
 * @param {number} temp_f @param {number} k @param {number} h_perf @param {number} z
 * @param {number} gas_sg @param {number} rw @param {number|null} [beta]
 */
export function gas_b_coefficient(temp_f, k, h_perf, z, gas_sg, rw, beta = null) {
  check(h_perf > 0 && rw > 0, "h_perf and rw must be > 0.");
  check(gas_sg > 0 && z > 0, "Gas gravity and Z must be > 0.");
  if (beta === null || beta === undefined) beta = gas_beta_firoozabadi_katz(k);
  check(beta >= 0, "beta cannot be negative.");
  const tempR = temp_f + 460.0;
  return JONES_B_CONST * beta * tempR * gas_sg * z / (h_perf ** 2 * rw);
}

/**
 * Solve  b*q^2 + a*q = dp2  for q (positive root).
 * The textbook form is q = (-a + sqrt(a^2 + 4*b*dp2)) / (2*b); the identical form used here also
 * works when b = 0 (pure Darcy) and avoids subtracting two nearly equal numbers.
 * @param {number} a @param {number} b @param {number} dp2
 */
function solveRate(a, b, dp2) {
  return 2.0 * dp2 / (a + Math.sqrt(a ** 2 + 4.0 * b * dp2));
}

/**
 * Gas rate (Mscf/d) from Darcy's law in pressure-squared form (no turbulence).
 * @param {number} p_res @param {number} pwf @param {number} temp_f @param {number} k @param {number} h
 * @param {number} mu @param {number} z @param {number} re @param {number} rw @param {number} [skin]
 */
export function gas_darcy(p_res, pwf, temp_f, k, h, mu, z, re, rw, skin = 0.0) {
  checkGasInputs(p_res, pwf);
  const a = gas_a_coefficient(temp_f, k, h, mu, z, re, rw, skin);
  if (pwf >= p_res) return 0.0;
  return (p_res ** 2 - pwf ** 2) / a;
}

/**
 * Gas rate (Mscf/d) from the Jones equation  Pr^2 - Pwf^2 = a*q + b*q^2.
 * @param {number} p_res @param {number} pwf @param {number} temp_f @param {number} k @param {number} h
 * @param {number} mu @param {number} z @param {number} gas_sg @param {number} re @param {number} rw
 * @param {number} [skin] @param {number|null} [beta] non-Darcy factor 1/ft (null = estimate from k)
 * @param {number|null} [h_perf] perforated thickness ft (null = same as h)
 */
export function gas_jones(p_res, pwf, temp_f, k, h, mu, z, gas_sg, re, rw,
                          skin = 0.0, beta = null, h_perf = null) {
  checkGasInputs(p_res, pwf);
  if (h_perf === null || h_perf === undefined) h_perf = h;
  const a = gas_a_coefficient(temp_f, k, h, mu, z, re, rw, skin);
  const b = gas_b_coefficient(temp_f, k, h_perf, z, gas_sg, rw, beta);
  if (pwf >= p_res) return 0.0;
  return solveRate(a, b, p_res ** 2 - pwf ** 2);
}

// =====================================================================
// GAS - back-pressure equation (C and n)
// =====================================================================

/**
 * Gas rate from the back-pressure equation  q = C*(Pr^2 - Pwf^2)^n.
 * The rate has the same unit as the rate used to find C (use Mscf/d to match the other models).
 * @param {number} p_res @param {number} pwf @param {number} C @param {number} n
 */
export function gas_backpressure(p_res, pwf, C, n) {
  checkGasInputs(p_res, pwf);
  check(C > 0, "C must be > 0.");
  check(0.0 < n && n <= 1.0, "n must be between 0 and 1 (usually 0.5 - 1.0).");
  if (pwf >= p_res) return 0.0;
  return C * (p_res ** 2 - pwf ** 2) ** n;
}

// =====================================================================
// GAS - Horizontal wells (Joshi, Kuchuk and Goode)
// =====================================================================
// The shape of the flow in the reservoir is the same for oil and gas.  For oil the geometry gives
// J = kh*h / (141.2*Bo*mu*B) (B = the Joshi bracket, or pwD + skin for Kuchuk-Goode).  For gas in
// pressure-squared form the same bracket gives the laminar coefficient
//       a = 1422 * T * mu * z * B / (kh*h)        [psi^2 / (Mscf/d)]
// so a is found from the oil routine with Bo = 1 and mu = 1:  a = 1422*T*mu*z / (141.2*J1).
// Turbulence: the Jones b*q^2 term is kept with the wellbore length L in place of the perforated
// thickness, so b = 3.161e-12 * beta * T * gas_sg * z / (L^2 * rw).  With a long horizontal section b
// is very small: horizontal gas wells are almost free of non-Darcy loss.
// ASSUMPTION: this turbulence term is the usual engineering extension, not a published
// horizontal-well equation; give beta yourself when you have it.

/**
 * Laminar coefficient a (psi^2 per Mscf/d) of a horizontal gas well, Joshi geometry.
 * @param {number} temp_f @param {number} kh @param {number} kv @param {number} h @param {number} length
 * @param {number} re_h @param {number} rw @param {number} mu @param {number} z @param {number} [skin]
 */
export function gas_a_coefficient_horizontal_joshi(temp_f, kh, kv, h, length, re_h, rw, mu, z, skin = 0.0) {
  check(mu > 0 && z > 0, "Gas viscosity and Z must be > 0.");
  const j1 = horizontal_productivity_index_oil_joshi(kh, kv, h, length, re_h, rw, 1.0, 1.0, skin);
  return DARCY_GAS * (temp_f + 460.0) * mu * z / (DARCY_OIL * j1);
}

/**
 * Gas rate (Mscf/d) of a horizontal well: Pr^2 - Pwf^2 = a*q + b*q^2 with the Joshi a.
 * @param {number} p_res @param {number} pwf @param {number} temp_f @param {number} kh @param {number} kv
 * @param {number} h @param {number} length @param {number} re_h @param {number} rw @param {number} mu
 * @param {number} z @param {number} gas_sg @param {number} [skin] @param {number|null} [beta]
 */
export function gas_horizontal_joshi(p_res, pwf, temp_f, kh, kv, h, length, re_h, rw, mu, z, gas_sg,
                                     skin = 0.0, beta = null) {
  checkGasInputs(p_res, pwf);
  const a = gas_a_coefficient_horizontal_joshi(temp_f, kh, kv, h, length, re_h, rw, mu, z, skin);
  const b = gas_b_coefficient(temp_f, kh, length, z, gas_sg, rw, beta);
  if (pwf >= p_res) return 0.0;
  return solveRate(a, b, p_res ** 2 - pwf ** 2);
}

/**
 * Laminar coefficient a (psi^2 per Mscf/d) of a horizontal gas well in a box, Kuchuk-Goode geometry.
 * @param {number} temp_f @param {number} kh @param {number} kv @param {number} h @param {number} length
 * @param {number} lx @param {number} ly @param {number} xw @param {number} yw @param {number} zw
 * @param {number} rw @param {number} mu @param {number} z @param {number} [skin]
 * @param {number} [ky_ratio] @param {string} [top]
 */
export function gas_a_coefficient_horizontal_kuchuk_goode(temp_f, kh, kv, h, length, lx, ly, xw, yw, zw, rw, mu, z,
                                                          skin = 0.0, ky_ratio = 1.0, top = "sealed") {
  check(mu > 0 && z > 0, "Gas viscosity and Z must be > 0.");
  const j1 = horizontal_productivity_index_oil_kuchuk_goode(kh, kv, h, length, lx, ly, xw, yw, zw, rw, 1.0, 1.0,
                                                            skin, ky_ratio, top);
  return DARCY_GAS * (temp_f + 460.0) * mu * z / (DARCY_OIL * j1);
}

/**
 * Gas rate (Mscf/d) of a horizontal well in a closed box (Kuchuk and Goode).
 * @param {number} p_res @param {number} pwf @param {number} temp_f @param {number} kh @param {number} kv
 * @param {number} h @param {number} length @param {number} lx @param {number} ly @param {number} xw
 * @param {number} yw @param {number} zw @param {number} rw @param {number} mu @param {number} z
 * @param {number} gas_sg @param {number} [skin] @param {number} [ky_ratio] @param {string} [top]
 * @param {number|null} [beta]
 */
export function gas_horizontal_kuchuk_goode(p_res, pwf, temp_f, kh, kv, h, length, lx, ly, xw, yw, zw, rw, mu, z, gas_sg,
                                            skin = 0.0, ky_ratio = 1.0, top = "sealed", beta = null) {
  checkGasInputs(p_res, pwf);
  const a = gas_a_coefficient_horizontal_kuchuk_goode(temp_f, kh, kv, h, length, lx, ly, xw, yw, zw, rw, mu, z,
                                                      skin, ky_ratio, top);
  const b = gas_b_coefficient(temp_f, kh, length, z, gas_sg, rw, beta);
  if (pwf >= p_res) return 0.0;
  return solveRate(a, b, p_res ** 2 - pwf ** 2);
}

// =====================================================================
// GAS - Multilayer (own pressure, deliverability, CGR and WGR per layer)
// =====================================================================

/**
 * @typedef {{p_res: number, a?: number, b?: number, C?: number, n?: number,
 *            cgr?: number|null, wgr?: number|null}} GasLayer
 */

/**
 * Gas rate (Mscf/d) of one layer at the flowing pressure pwf.  A layer carries "p_res" and either
 * "a" and "b" (Darcy / Jones) or "C" and "n" (back-pressure).  Below the flowing pressure the layer
 * is shut (0), or - with crossflow - takes gas from the wellbore: the rate is then negative and
 * follows the same law with the pressures swapped (laminar term only for a, b).
 * @param {GasLayer} layer @param {number} pwf @param {boolean} crossflow @param {number} number
 */
function gasLayerRate(layer, pwf, crossflow, number) {
  const pLayer = layer.p_res;
  check(pLayer > 0, `Layer ${number}: reservoir pressure must be > 0.`);
  if ("C" in layer) {
    check(/** @type {number} */ (layer.C) > 0 && 0.0 < /** @type {number} */ (layer.n) && /** @type {number} */ (layer.n) <= 1.0,
          `Layer ${number}: C must be > 0 and n between 0 and 1.`);
  } else {
    check((layer.a ?? 0.0) > 0 && (layer.b ?? 0.0) >= 0.0,
          `Layer ${number}: the laminar coefficient a must be > 0 and b cannot be negative.`);
  }
  if (pwf < pLayer) {
    const dp2 = pLayer ** 2 - pwf ** 2;
    if ("C" in layer) return /** @type {number} */ (layer.C) * dp2 ** /** @type {number} */ (layer.n);
    return solveRate(/** @type {number} */ (layer.a), /** @type {number} */ (layer.b), dp2);
  }
  if (!crossflow || pwf === pLayer) return 0.0;
  const dp2 = pwf ** 2 - pLayer ** 2;
  if ("C" in layer) return -(/** @type {number} */ (layer.C)) * dp2 ** /** @type {number} */ (layer.n);
  return -dp2 / /** @type {number} */ (layer.a);
}

/**
 * The gas rate (Mscf/d) of each layer at one flowing pressure, in the order of `layers`.
 * @param {number} p_res @param {number} pwf @param {GasLayer[]} layers @param {boolean} [crossflow]
 * @returns {number[]}
 */
export function gas_multilayer_rates(p_res, pwf, layers, crossflow = false) {
  check(layers.length >= 1, "Multilayer IPR needs at least one layer.");
  checkGasInputs(p_res, pwf);
  return layers.map((layer, i) => gasLayerRate(layer, pwf, crossflow, i + 1));
}

/**
 * Gas rate (Mscf/d) of several layers producing into the same well at the same flowing pressure.
 * @param {number} p_res @param {number} pwf @param {GasLayer[]} layers @param {boolean} [crossflow]
 */
export function gas_multilayer(p_res, pwf, layers, crossflow = false) {
  return sum(gas_multilayer_rates(p_res, pwf, layers, crossflow));
}

/**
 * What the commingled gas layers produce at one flowing pressure: every producing layer adds its gas,
 * its condensate (gas*cgr) and its water (gas*wgr).  When none produces, the layers are weighted by
 * their rate at Pwf = 0.
 * @param {number} p_res @param {number} pwf @param {GasLayer[]} layers
 * @param {number} [default_cgr] @param {number} [default_wgr] @param {boolean} [crossflow]
 * @returns {{q: number, q_layers: number[], cgr: number, wgr: number}}
 */
export function gas_multilayer_mix(p_res, pwf, layers, default_cgr = 0.0, default_wgr = 0.0, crossflow = false) {
  const rates = gas_multilayer_rates(p_res, pwf, layers, crossflow);
  let weights = rates.map((q) => Math.max(q, 0.0));
  if (sum(weights) <= 0.0) {
    weights = gas_multilayer_rates(p_res, 0.0, layers, crossflow).map((q) => Math.max(q, 0.0));
  }
  let gas = 0.0, cond = 0.0, water = 0.0;
  for (let i = 0; i < layers.length; i++) {
    const layer = layers[i], w = weights[i];
    const cgr = layer.cgr ?? null;
    const wgr = layer.wgr ?? null;
    gas += w;
    cond += w * (cgr === null ? default_cgr : cgr);
    water += w * (wgr === null ? default_wgr : wgr);
  }
  return { q: sum(rates), q_layers: rates,
           cgr: gas > 0 ? cond / gas : default_cgr, wgr: gas > 0 ? water / gas : default_wgr };
}

/**
 * The flowing pressure (psia) at which the commingled gas layers give the rate q, by halving the
 * interval.  A rate above the AOF gives 0, a rate of 0 or less gives the highest layer pressure.
 * @param {number} q @param {number} p_res @param {GasLayer[]} layers @param {boolean} [crossflow]
 */
export function gas_multilayer_pwf(q, p_res, layers, crossflow = false) {
  const pMax = Math.max(...layers.map((layer) => layer.p_res));
  if (q <= 0.0) return pMax;
  if (sum(gas_multilayer_rates(p_res, 0.0, layers, crossflow)) <= q) return 0.0;
  let lo = 0.0, hi = pMax;
  for (let i = 0; i < 80; i++) {
    const mid = 0.5 * (lo + hi);
    if (sum(gas_multilayer_rates(p_res, mid, layers, crossflow)) > q) lo = mid; else hi = mid;
    if (hi - lo < 1e-7) break;
  }
  return 0.5 * (lo + hi);
}

// =====================================================================
// Argument names, so a named object can be used like Python's **inputs
// =====================================================================
// Python calls an IPR as  ipr_function(p_res=..., pwf=..., **ipr_inputs).  JavaScript has no keyword
// arguments, so each model lists its argument names here in order; callIpr() then expands a named
// object into the right positional call.  The first two are always p_res and pwf.

/** @type {Record<string, string[]>} */
export const IPR_PARAMS = {
  oil_pi: ["p_res", "pwf", "pb", "J"],
  oil_vogel: ["p_res", "pwf", "pb", "q_test", "pwf_test"],
  oil_darcy: ["p_res", "pwf", "pb", "k", "h", "bo", "mu", "re", "rw", "skin"],
  oil_darcy_regime: ["p_res", "pwf", "pb", "k", "h", "bo", "mu", "re", "rw", "skin",
                     "regime", "phi", "ct", "time_hours"],
  oil_fetkovich: ["p_res", "pwf", "q1", "pwf1", "q2", "pwf2"],
  oil_horizontal_joshi: ["p_res", "pwf", "pb", "kh", "kv", "h", "length", "re_h", "rw", "bo", "mu", "skin"],
  oil_horizontal_kuchuk_goode: ["p_res", "pwf", "pb", "kh", "kv", "h", "length", "lx", "ly",
                                "xw", "yw", "zw", "rw", "bo", "mu", "skin", "ky_ratio", "top"],
  oil_multilayer: ["p_res", "pwf", "pb", "layers", "crossflow"],
  gas_darcy: ["p_res", "pwf", "temp_f", "k", "h", "mu", "z", "re", "rw", "skin"],
  gas_jones: ["p_res", "pwf", "temp_f", "k", "h", "mu", "z", "gas_sg", "re", "rw", "skin", "beta", "h_perf"],
  gas_backpressure: ["p_res", "pwf", "C", "n"],
  gas_horizontal_joshi: ["p_res", "pwf", "temp_f", "kh", "kv", "h", "length", "re_h", "rw",
                         "mu", "z", "gas_sg", "skin", "beta"],
  gas_horizontal_kuchuk_goode: ["p_res", "pwf", "temp_f", "kh", "kv", "h", "length", "lx", "ly",
                                "xw", "yw", "zw", "rw", "mu", "z", "gas_sg", "skin", "ky_ratio", "top", "beta"],
  gas_multilayer: ["p_res", "pwf", "layers", "crossflow"],
};

/** @type {Record<string, Function>} */
export const IPR_FUNCS = {
  oil_pi, oil_vogel, oil_darcy, oil_darcy_regime, oil_fetkovich,
  oil_horizontal_joshi, oil_horizontal_kuchuk_goode, oil_multilayer,
  gas_darcy, gas_jones, gas_backpressure,
  gas_horizontal_joshi, gas_horizontal_kuchuk_goode, gas_multilayer,
};

/**
 * Call an IPR model by name with a NAMED object of inputs, the way the Python does with **inputs.
 * Anything the object does not give is left to the function's own default.
 * @param {string} name a key of IPR_FUNCS
 * @param {Record<string, any>} named p_res, pwf and whatever that model needs
 * @returns {number} the rate (STB/d for oil, Mscf/d for gas)
 */
export function callIpr(name, named) {
  const fn = IPR_FUNCS[name];
  const params = IPR_PARAMS[name];
  if (!fn || !params) throw new Error(`Unknown IPR model: ${name}`);
  // Trim the trailing arguments that were not given, so each one keeps its own default.
  const args = params.map((key) => named[key]);
  while (args.length > 0 && args[args.length - 1] === undefined) args.pop();
  const missing = params.slice(0, args.length).filter((key, i) => args[i] === undefined);
  if (missing.length) throw new Error(`${name} is missing: ${missing.join(", ")}`);
  return fn(...args);
}

// =====================================================================
// Build a whole IPR curve (for plotting, or for finding the VLP intersection)
// =====================================================================

/**
 * Calculate an IPR curve from pwf = p_res down to pwf = 0.
 * @param {string} name a key of IPR_FUNCS, for example "oil_pi"
 * @param {number} p_res reservoir pressure (psia)
 * @param {number} [n_points]
 * @param {Record<string, any>} [inputs] the remaining inputs of that model, by name
 * @returns {{pwf: number[], q: number[]}} two lists of equal length
 */
export function ipr_curve(name, p_res, n_points = 21, inputs = {}) {
  check(n_points >= 2, "n_points must be at least 2.");
  const pwfList = [], qList = [];
  for (let i = 0; i < n_points; i++) {
    const pwf = p_res * (1.0 - i / (n_points - 1));      // p_res, ..., 0
    pwfList.push(pwf);
    qList.push(callIpr(name, { ...inputs, p_res, pwf }));
  }
  return { pwf: pwfList, q: qList };
}
