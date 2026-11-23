// =====================================================================
// FLUID_COLORS - one place for what each fluid is drawn and written in
// =====================================================================
//
// The surveillance convention every petroleum engineer already reads without thinking: oil green,
// water blue, gas red, total liquid black, with GOR orange and water cut cyan for the ratios.
//
// Each fluid has two shades of the SAME colour, not two different colours:
//
//   `line`  the pure hue, for a line or a marker on a chart and for the fluid moving in the
//           drawing, where it is a thin stroke or a small dot on white and wants every bit of
//           contrast it can get;
//   `text`  a slightly softer version, for the rate numbers across the top of the page, where a
//           pure primary at 21px is harsh to read.
//
// This file is the only place these hexes are written. app.js reads it for the charts, wellview.js
// for the fluid in the drawing, and the `.kpis` rules in index.html are the one copy that cannot
// import it and so has to be kept in step by hand - the page test compares the two so they cannot
// drift apart silently.
//
// Lives in a module of its own because both app.js and wellview.js need it and wellview.js is the
// lower of the two: the other way round would be a cycle.

/** @typedef {{line: string, text: string}} FluidColour */

/** @type {Record<"oil" | "water" | "gas" | "liquid" | "gor" | "waterCut", FluidColour>} */
export const FLUID_COLORS = {
  oil: { line: "#008000", text: "#2CA02C" },
  water: { line: "#0000FF", text: "#1F77B4" },
  gas: { line: "#FF0000", text: "#D62728" },
  liquid: { line: "#000000", text: "#1E1E1E" },
  gor: { line: "#FF7F0E", text: "#FF7F0E" },
  waterCut: { line: "#17BECF", text: "#17BECF" },
};

// The curves that are NOT a fluid. These are deliberately outside the palette above: an IPR is a
// pressure against a rate, not a stream of oil, and drawn blue it would read as water on a page
// where blue means water everywhere else.
export const CURVE_COLOURS = {
  ipr: "#2F4B6E",            // the inflow curve: dark slate blue
  vlp: "#8E44AD",            // the tubing curve: purple
  pressure: "#111827",       // the pressure down the well
  temperature: "#FF7F0E",    // temperature; GOR shares this orange, but the two are never on one chart
};
