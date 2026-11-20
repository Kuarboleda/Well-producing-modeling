# Integrated Well Modelling Tool (nodal analysis)

A free web app for nodal analysis of oil, water and gas wells (oilfield units).

## Files

| File | What it does |
| --- | --- |
| `app.py` | The web page (Streamlit) |
| `app_helpers.py` | Logic behind the page: inputs -> well/fluid/IPR, charts, sensitivities |
| `nodal.py` | Finds the operating point (where IPR and VLP cross) and runs sensitivities |
| `ipr.py` | Inflow performance: PI, Vogel, Darcy, Fetkovich (oil); Darcy, Jones, back pressure (gas) |
| `vlp.py` | Tubing outflow: Beggs and Brill, Hagedorn and Brown, Gray, Orkiszewski, Ansari, Duns and Ros, Mukherjee and Brill, Fancher and Brown, fluids, pressure traverse |
| `well.py` | Well path, tubing and temperature profile |
| `pvt.py` | PVT correlations |
| `gaslift.py` | Continuous gas lift: check of the casing pressure at the injection point |
| `gaslift_valves.py` | Gas lift valve engine: nitrogen dome pressure, IPO/PPO valve mechanics, valve spacing and settings, check of an existing string, frames of the unloading |
| `gaslift_design.py` | Connects the valve engine to the page's well: pressure lines, design, check, charts |
| `gaslift_tab.py` | The page of the **Gas Lift Design** tab |
| `pvt_match.py` | PVT matching: compares lab data with the correlations and fits a match |
| `Run_Nodal_App.bat` | Double-click to start the app (Windows) |
| `test_*.py` | Test scripts: run each one with `python test_xxx.py` |
| `test_reference_cases.py` | Compares results with three solved oil and gas examples from a commercial nodal analysis package |

## PVT matching (lab data)

Open **Fluid (PVT)** in the sidebar (Oil & Water) and press **PVT matching with lab data...**; a larger window opens. (It needs Streamlit 1.37 or newer; with an older version the same screen opens in the main area.) Type or paste the lab table (pressure with any of Rs, Bo, oil viscosity)
and, if you have it, the measured bubble point.

1. The app ranks every correlation (Glaso, Standing, Lasater, Petrosky for Pb/Rs/Bo; Beal, Beggs and Petrosky for viscosity)
   by its average error against the lab data, and plots the lab points against all of them.
2. **Match to lab data** nudges the chosen correlation with four numbers: a shape exponent for Rs (Rs at the bubble
   point stays equal to the solution GOR), a multiplier and shift for Bo, and a multiplier for viscosity. The measured
   bubble point is applied directly. The errors before and after are shown.
3. **Use this match in the well model** switches the well model to the matched PVT and recalculates. A banner in the
   sidebar says the match is on; **Remove PVT match** goes back to the published correlations. If the oil gravity,
   gas gravity, GOR or temperature are changed afterwards, the app warns that the match is out of date.

Only these few numbers are fitted on purpose, so that a lab table with a handful of points is not over-fitted.
`test_pvt_match.py` builds "lab data" from a correlation changed in a known way and checks that the match finds the same numbers back.
Gas PVT matching (Z-factor, gas viscosity) is not built yet.

## Run it on your computer

```
pip install -r requirements.txt
streamlit run app.py
```

Your browser opens the page. Press **Calculate** after changing inputs.

## Put it on the web for free

1. Create a free GitHub account and a new public repository.
2. Upload all the `.py` files and `requirements.txt` to it.
3. Go to share.streamlit.io, sign in with GitHub, choose the repository and set the main file to `app.py`.

## Status

* **Pressures are gauge (psig) everywhere the user types or reads them** - the sidebar, the tables, the charts,
  the messages and the lab PVT table. The engine underneath (`vlp.py`, `ipr.py`, `pvt.py`, `nodal.py`) works in
  absolute pressure (psia), because the gas law needs it. `app_helpers.py` is the only place the two meet:
  `build_case()` adds 14.7 psi to every pressure that came from the page (the list is `GAUGE_INPUTS`), and
  `to_psig()` takes a calculated pressure back to gauge for a chart, a table or a message.
* VLP correlations available: Beggs and Brill, Hagedorn and Brown (with the Griffith bubble-flow correction),
  Gray, **Orkiszewski (1967)**, **Ansari et al. (1994)**, **Duns and Ros (1963)**, **Mukherjee and Brill (1983 / 1985)**
  and **Fancher and Brown (1963)**. The *VLP correlation* box lists them by name and starts on the one the app suggests for the well (see the advice below).
* **Orkiszewski** (SPE 1546, 1967) was written from the paper itself. It picks the flow pattern from the paper's
  boundaries (bubble, slug, transition, mist) and uses Griffith for bubble flow, a modified Griffith and Wallis for
  slug flow (bubble rise velocity and a liquid distribution coefficient) and Duns and Ros for mist, and it includes
  the kinetic-energy term. It is a vertical-flow correlation and is known to do well in heavy oil and gas lift wells.
  How it was checked: the worked example in the paper's Appendix D (flow pattern, v_gD 9.53, (L)s 272, Reynolds number
  7720, bubble rise velocity 1.74 ft/s, coefficient -0.097, density 24.9 lb/ft3, friction 2.26, 529 ft for a 100 psi
  step, all within the rounding of the paper), hand calculations of each flow pattern, continuity across the pattern
  boundaries, and the paper's Well 22 (1850 stb/d, measured drop about 800 psi), where it is within 10 % of the
  measurement and closer than Hagedorn and Brown, as the paper reports.
  Choices made where the paper is unclear: the bubble rise velocity comes from the equations (C-7, C-8, C-9) and not
  from the charts (Figs. 8 and 9); the v_gD printed in Eq. B-4 is taken as the same dimensionless gas velocity as in
  B-1; the liquid is water-continuous at a water cut of 50 % or more; friction factors use the Colebrook equation
  instead of the Moody chart; the limit C-16 on the distribution coefficient is solved in closed form; mist roughness
  follows Duns and Ros (C-21, C-22). At the bubble/slug boundary the correlation jumps by a few psi per 100 ft step,
  so the step solver accepts a larger jump for this correlation only. In a deviated well the gravity part is scaled by
  the pipe angle along the measured depth, which the paper did not test.
* **Fancher and Brown** (SPE 440-PA, 1963) was written from the paper (all of it read, including the figures). It is
  Poettmann and Carpenter's method: gas and liquid are one fluid with the no-slip density and all losses go into one
  Fanning friction factor, dp/dH = [rho + f (qM)^2 / (7.413e10 rho d^5)] / 144 (Eq. 2). The paper's finding is that the
  factor depends on the producing gas-liquid ratio as well as on N = 1.4737e-5 qM/d (= rho v d), so there is one line for
  each of GLR < 1500, 1500 - 3000 and > 3000 scf/STB (Figs. 7, 8, 9). Things to know:
  (1) **it is only a quality-check bound**, not for real work: it ignores slip, so it gives the lowest gravity part
  and shows no well loading (its VLP curve is flat at low rates instead of J-shaped). The app labels it that way, shows it
  last in "Compare all correlations" and never recommends it; a measured flowing pressure below it points to wrong
  PVT or pressure data. (2) The three friction lines are **chart readings** from the paper's figures (about 3 %), checked
  against Fig. 6, which draws them together; Fig. 7 is a curve (steep below N = 6), Figs. 8 and 9 are straight on log-log
  paper. The lines are drawn for N = 3.4 - 35, 4.7 - 27 and 3.7 - 15; each is continued as drawn in Fig. 6 (to N = 70, 35
  and 23) and the factor is held constant beyond that and below the start of the line. (3) The friction factor jumps where
  the GLR crosses 1500 or 3000, so a gas lift VLP can step by a few percent at the rate where that happens (the paper has no
  smoothing). The GLR is the producing one: all gas at the surface (dissolved, free and injected) per STB of liquid.
  (4) The paper has no angle, viscosity, roughness or acceleration term; the app only applies sin(angle) to the gravity part.
  (5) It was measured in a 2 3/8 in oil-and-water gas lift well (75 - 936 B/D); a gas well is far outside that.
  Tests: hand calculation of Eq. 2 and of Eq. 1 turned round, each friction line against its figure, the GLR boundaries,
  the GLR handed over by the fluid classes (with gas lift), whole-well runs (gravity part below every slip correlation
  except Orkiszewski, flat low-rate VLP, gas lift, deviated, wet gas) and 3,000 random conditions.
* **Ansari et al.** (SPE 20630, 1994) is a mechanistic model: instead of a fitted curve it decides the flow pattern from
  the physics (Taitel and Barnea boundaries: bubble, dispersed bubble, slug, annular) and uses a separate physical
  model for each. Bubble flow uses a drift-flux holdup, slug flow a Taylor bubble followed by a liquid slug (fully
  developed or still developing), and annular flow a liquid film and a gas core carrying droplets. The paper has no acceleration
  term, so there is none. In the paper's own test on 1,712 field wells it was the best on the wells that were not used to
  build Hagedorn and Brown, and slightly behind Hagedorn and Brown on the whole databank; it was weak on deviated wells.
  How it was checked here: every equation of the flow-pattern map, the bubble, slug and annular models was
  checked by hand-calculation; the slug solution satisfies all eight equations of the paper (largest residual below 1e-9);
  the film and core momentum equations of annular flow give the same gradient; 3,000 random conditions give no failure; and
  the paper's Well 22 case (measured drop about 800 psi) comes out about 25 % high, like Beggs and Brill and
  Hagedorn and Brown (the paper gives no worked example, so there is no number to reproduce).
  Choices made where the paper is unclear or misprinted:
  the constant in the slug equation (Eq. 40) is rebuilt from the paper's own equations 29 - 35, 37 and 38 (the printed
  form does not satisfy them); the Nusselt film (Eq. 45) uses the film's liquid holdup where the paper prints (1 - H);
  the developing Taylor bubble length (Eq. 54) is solved from Eqs. 52 and 53; the friction factor in the dispersed-bubble
  boundary (Eq. 4) uses the liquid Reynolds number of the mixture velocity; Moody factors are Colebrook. One addition:
  a flow is called annular only if the film that the annular model itself finds is also thin enough not to bridge
  the pipe (film plus core liquid 12 % of the pipe or less). Without this, a gas rate just above the boundary of Eq. 6
  gives a thick, unphysical "annular" film and a very high gradient. The effect is that annular flow starts at roughly
  two to four times the gas velocity of Eq. 6 (for example 19 ft/s against 5.4 ft/s at 0.05 ft/s liquid in 3 in tubing)
  and slug flow is used in between. Where the pattern changes, the pressure gradient jumps (as it does in all
  flow-pattern models), so the step solver accepts a larger jump for this correlation, as it does for Orkiszewski.
  It is a vertical-flow model; in a deviated well the app only scales the gravity part by the pipe angle.
  **The slug-flow branches are blended (19 Nov 2026).** The paper's developed slug flow (Eq. 60) treats the Taylor
  bubble as pure gas, while its developing slug flow (Eq. 62) counts the liquid film in the Taylor bubble through
  rho_TBA. The two therefore do not agree at the point where the paper switches between them (cap length
  L_c = L_TB): they differ by roughly beta x rho_L x H_LTB, here about half the slug-unit density. Taken literally
  the model steps - on the default well with 1,000 Mscf/d of lift gas the VLP curve jumped about 50 psi between two
  neighbouring rates, enough to move the operating point (this is what the curve looked like before the fix: a steep
  rise to about 1,000 STB/d and then almost flat). Both of the paper's expressions are kept and they are blended
  with a smoothstep weight over 1 <= L_c/L_TB <= `ANS_DEV_BLEND` (1.5). At the switch the weight is 0, so the
  developed equations still apply there; the developing equations take over once the Taylor bubble is clearly
  shorter than its own cap. This is a **deviation from the paper**, and it was chosen after testing the
  alternatives: using rho_TBA in both branches also removes the step but makes Well 22 +33 % instead of +25 %
  against the measurement, and using pure gas in both flattens the curve unphysically. With the blend the largest
  change of slope is 2.4 psi per 25 STB/d (48 psi before) and Well 22 is unchanged at +25 %.
  Checks: `test_vlp.py` (the weight at both ends and in the middle, the curve's smoothness over 116 rates, and that
  the ends of the curve are still the paper's own values).
* **Duns and Ros** (6th World Petroleum Congress, 1963) was written from the paper. Pipe flow is described by four
  numbers (liquid and gas velocity, pipe diameter and liquid viscosity) and three regions: I (liquid continuous: bubble,
  plug, part of froth), II (slug and the rest of froth) and III (gas continuous: mist), plus a transition between slug and
  mist where the gradient is interpolated on the gas velocity number at a fixed gas mass flow. Each region has its own
  slip velocity (Eqs. 4, 6, 8), which gives the holdup and the static gradient, and its own wall friction (Eqs. 10 - 13);
  the mist film roughness follows Eq. 14 and Fig. 10, and the acceleration term (Eq. 17) is used in the transition and mist
  ranges, as the paper says. The correlation is for vertical flow; in a deviated well the app scales the gravity part by the
  pipe angle.
  **Important: the paper's functions are charts, not equations.** F1 - F4 (Fig. 5), L1 and L2 (Fig. 6), F5 - F7 (Fig. 7) and
  f2 (Fig. 9) were read from the scanned figures (axes calibrated, each curve traced by computer and checked on an overlay)
  and are stored as tables in `vlp.py` (interpolated on log x), so every value is a reading of a chart, good to about 2 - 3 %
  of the chart; f1 (Fig. 8) is the Moody diagram and is replaced by the Colebrook equation. Other programs use their own fits
  of the same charts, so small differences from them (and from the reference package) are expected.
  How it was checked: the chart tables against the landmark values of each chart; the dimensionless numbers against the
  paper's laboratory pipe of Fig. 3; hand calculations of the slip velocity (both regions), holdup, Region I-II friction,
  mist friction and acceleration; the friction equations in dimensionless form against the same friction in ordinary units;
  liquid-only and gas-only limits; continuity at the slug/transition and transition/mist boundaries; 4,000 random conditions
  with no failure; and the measured lines of the paper's Fig. 3 (8 cm pipe, air and 4.2 cP oil), which the correlation
  follows: the gradient falls with gas rate, passes a minimum at about 1,000 - 2,000 cm/s and rises in mist flow to
  within 12 % of the figure (0.30 against 0.34 at 10,000 cm/s); mist flow starts above 1,500 cm/s at 2 cm/s liquid, as the paper says.
  The pressure drop for an oil well is in the range of the other correlations.
  Choices and limits: (1) the paper's Eq. 18 for wet mixtures (below 10 % water) needs the dry-oil and the water gradients
  separately; the gradient functions here carry one blended liquid, so it is not used (as for the other correlations), and
  the correlation was made for dry mixtures or water cuts under 10 %. (2) A negative slip velocity is taken as zero. (3) The
  mist film roughness is never below the pipe roughness (at least 0.001 of the diameter) or above 0.5, and Eq. 15 is used for
  a relative roughness above 0.05. (4) The two slip equations of Regions I and II are separate fits and do not meet exactly at
  the boundary L1 + L2 N: for ordinary tubing the gradient differs by 6 % (median) and 22 % (90th percentile) across it, so the step solver
  accepts a larger jump for this correlation (as for Orkiszewski), and the step solver now halves its search bracket every second
  step so that a jump never stops it. (5) For pipe diameter numbers below about 20 (1.5 in tubing or less with light oil)
  the diameter correction in Region I is large (F4 / N_d) and the two regions differ more; this is the edge of the paper's
  charts. (6) The first part of the f2 chart is set to exactly 1 (no gas, no correction).
* **Mukherjee and Brill** is built from three papers by the same authors, all read for this code. SPE 10923 (1983) gives the
  liquid holdup equation (Eq. 1: H_L = exp[(c1 + c2 sin a + c3 sin^2 a + c4 N_L^2) N_gv^c5 / N_Lv^c6]) and the three coefficient
  sets of Table 1 (uphill and horizontal; downhill stratified; other downhill). The flow-pattern paper (Int. J. Multiphase Flow
  11, 1985, p. 299) gives the boundaries (N_gv(SM), N_Lv(BS), N_gv(BS), N_Lv(ST)) and the flow chart of its Fig. 16; the
  pressure-drop paper (J. Energy Resources Technology 107, 1985, p. 549) gives the friction method, Table 2 (f_R) and the
  calculation steps. All of these were checked line by line against the printed papers, and in addition the book example
  (6 in vertical pipe, v_sg 3.86 and v_sL 3.97 ft/s, slug flow) and the open-source package's example (holdup 0.32725,
  4403 Pa/m, to 0.1 %) are reproduced.
  What it does: annular-mist above N_gv(SM). Uphill: bubble above N_Lv(BS), otherwise slug. Downhill **and horizontal** (the
  chart treats them together): steeper than 30 degrees, bubble if N_gv <= N_gv(BS), otherwise stratified below N_Lv(ST) and
  slug above it; 30 degrees or less, stratified below N_Lv(ST), otherwise bubble or slug by N_gv(BS). Friction: Moody factor at
  the no-slip Reynolds number applied to the slip density (bubble and slug); the same factor times f_R(H_R) on the no-slip
  density (annular-mist); stratified flow uses Eq. 15 of the paper, the momentum balance of the gas phase (gas wall shear over
  its wetted wall and only the gas weight), no acceleration term. Acceleration elsewhere: E_k = rho_s v_m v_sg / p.
  Things to know: (1) the paper's smooth interface has no formula for the interfacial shear, so it is neglected in stratified
  flow (only matters for downhill and horizontal flow lines, not for ordinary producing wells). (2) Printed Eqs. 26-27 write the
  wall shear as f rho v^2 / (2 g) with a Moody factor, which is four times the usual f rho v^2 / 8 and does not reproduce the
  Darcy-Weisbach drop of Eq. 2, so the code uses the /8 form. (3) Earlier versions of this code treated horizontal flow as
  uphill and used the liquid and gas wall shear for stratified flow (from the book layout); both were corrected with the 1985 papers.
  Other tests: hand calculations of every boundary at a chosen point (uphill, downhill, horizontal), of the holdup for each
  coefficient set, of the stratified geometry and friction (half-full pipe), of the annular friction and acceleration; the
  gravity part at every angle from -90 to +90 degrees; 6,000 random conditions at 11 angles with no failure; whole-well checks
  with gas lift, deviated, horizontal and "up then down" wells.
* **Hagedorn and Brown checked against the original paper** (SPE 940, 1965). The Duns and Ros numbers, the gradient equation
  (Eq. 15) and the Reynolds number follow the paper, and the CN_L and psi chart fits were read against Figs. 12 and 9
  (`test_vlp.py`, section "checked against the paper"). Two changes came out of the check:
  (1) CN_L stops at N_L = 0.5, where the paper's Fig. 12 ends (the cubic fit would otherwise curve away outside the chart);
  (2) the HL/psi curve fit used by most programs flattens to 0.07 as the group H goes to 0, while the chart in the paper keeps
  falling (about 0.01 at H = 1e-7). That floor put 7 % liquid in a wet-gas well and made the gradient about 28 % too high
  at 0.0001 % liquid. Below H = 1e-5 the curve now follows the chart (H^0.55), and above it the fit is unchanged, so the
  match with reference cases 1, 2 and 3 does not move. The fit is up to about 10 % above the paper's chart for H = 1e-4
  to 1e-2; it is kept because it gives the closer match with the reference package. The Griffith bubble-flow correction is kept too.
* **Re-check of all VLP correlations** (this round): the Beggs and Brill and Gray equations were compared line by line with
  the published forms; 6,000 random conditions (every pipe angle from -90 to +90 degrees, zero gas, zero liquid, all
  five correlations) give no failure, no NaN and no negative vertical-flow gradient; for every correlation
  gradient x (1 - e_k) equals gravity + friction (so the VLP multipliers act in the right place), and a horizontal pipe has no
  gravity part; whole-well VLP curves for an oil well and a wet-gas well are smooth for all correlations (only the usual
  J-shape at low oil rates).
* Hagedorn and Brown is a vertical-flow correlation. It matches the reference package well for a 35 - 40 degree well (reference case 3), but it has not been checked for strongly deviated or horizontal wells.
* Gray is for gas wells that make a little condensate or water. Not for oil wells.
* Oil IPR models: PI entry, Vogel (one test), Darcy (pseudosteady, steady state or transient after a chosen time),
  Fetkovich (two tests), a horizontal well (Joshi 1988 or **Kuchuk and Goode 1991**) and a **multilayer (commingled) well**. Gas IPR models: Darcy, Jones, back pressure, **horizontal well (Joshi or Kuchuk and Goode geometry)** and a **multilayer (commingled) gas well**.
* PVT matching to lab data for oil (see the section above).
* Pressure-temperature profile: pressure on the top axis, temperature on the bottom axis, and five pressure-gradient
  values (psi per ft of true vertical depth) written along the pressure curve. Each gradient is the pressure change
  over a window of depth around the point, so a small step in the calculation cannot make it jump.
* The page title is "Integrated Well Modelling Tool". To show a picture instead of the word "Claude" in the byline,
  put a small PNG at `assets/claude_logo.png` (next to `app.py`); it is picked up automatically.
* **Gas lift** (continuous, oil wells): choose it under *Artificial lift* (the list is None / Gas lift / ESP). Inputs: gas injection rate, injection depth
  (measured depth of the valve or orifice), injected gas gravity and, optionally, the injection pressure at the
  wellhead (default 1,500 psig).
  Above the injection depth the tubing carries the formation gas plus the lift gas (their volumes, densities and
  viscosities are mixed), so the VLP drops; the IPR does not change. The pressure and temperature profile marks the
  injection depth and its gradient labels show the lighter column. The calculation is done step by step as before, with a
  step boundary exactly at the injection depth; above it the heat capacity and mass rate for the temperature profile
  include the lift gas.
  With an injection pressure the app checks that the static gas column in the casing gives at least about 100 psi more
  than the tubing pressure at the injection depth. Gas injection rate and depth are also offered in the Sensitivity tab,
  and the **Gas Lift Design** tab draws the gas lift performance curve (oil rate against injection rate, highest point marked).
  Not included: injection through several valves at once, gas lift gas temperature other than the tubing temperature,
  annulus (casing) flow.
* **ESP** is in the *Artificial lift* list but only as a placeholder: choosing it shows a note and nothing is calculated.
  The **ESP Design** tab is a placeholder ("coming soon") for the pump selection inputs and results. The gas lift inputs
  needed for the IPR/VLP and sensitivity calculation (rate, depth, gas gravity, injection pressure) stay in the sidebar.
* **Gas Lift Design tab** (oil and water wells; all its inputs are in the tab, pressures in psig). Three jobs, from
  Takacs, *Gas Lift Manual*, and API RP 11V6 (2nd ed. 1999):
  1. **Check the valves already in the well.** Enter the mandrels (MD, dummy / IPO valve / PPO valve / orifice, valve OD,
     port, test rack opening pressure TRO), the kick-off and operating pressures, the static liquid level in the
     annulus, the load fluid gradient and the casing and tubing sizes. The program goes down the string like the unloading
     does: the tubing pressure when each valve is uncovered, the surface pressure needed to open it, whether the valve
     above closes, and finally whether normal operation is stable (upper valves stay closed, casing over tubing pressure
     at the operating valve, gas passage of the port). The answer is "kicks off / does not kick off", the deepest valve
     reached and a list of what to fix. Valves above the liquid level, closing pressures that do not fall down the string
     and multi-pointing are flagged. The method for a string that is already spaced is the one of API RP 11V6 Example 3.
  2. **Design IPO nitrogen charged valves** by the API RP 11V6 constant pressure drop per valve method (fixed drop, or the
     API minimum PPEF x 100 + safety factor of its Table 1, or the maximum 20 + PPEF x 200). The top valve is where the
     unloading gradient from the wellhead meets the casing pressure at kick-off; the others follow from the flowing
     tubing pressure at the valve above (a pressure traverse at the design rate and gas rate), the pressure difference
     wanted across the valve and the drop per valve. Output: depths, valve temperature, dome pressure at depth, charge
     pressure at 60 degF and TRO. The operating valve can be an orifice; its port is chosen from the gas rate wanted with
     the Thornhill-Craver equation, at no more than 80 % of its capacity.
  3. **Design PPO nitrogen charged valves** with the design tubing pressure line (point A = WHP + 200 psi or WHP + 20 % of
     the injection pressure, whichever is larger; point B = flowing tubing pressure at the injection point).
  The nitrogen dome pressure at valve temperature can be found three ways: the API RP 11V6 temperature factor Ct,
  Winkler-Eads (Takacs Eq 3.6 - 3.8) or the real-gas law with the nitrogen Z factor (Takacs Eq 3.2). A static liquid
  level in the annulus is used for the top valve (not above the level; the tubing pressure when it is uncovered comes
  from the annulus liquid pushed into the tubing).
  Each job can show an **unloading animation**: a slider (or Play) steps through the kick-off, each valve being
  uncovered, injection transfer from valve to valve and normal operation. It is a quasi-steady picture (a pressure
  snapshot at the end of each step), not a transient multiphase simulation; times are rough estimates from the gas
  that the valves pass.
  Not included: the variable pressure drop (CAMCO) design, balanced valves, pilot and throttling valves, spring loaded
  valves, designs for unknown injection points with bracketing valves, gas lift gas temperature in the annulus other than
  the average of surface and tubing temperature.
* **Multilayer IPR** (commingled layers, entered in a pop-up table): press *Edit layer table...* under the IPR model. One
  row per layer, with the columns *Layer model* (PI or Darcy, a drop-down), *Layer pressure (psig)*, PI, *Layer perm (mD)*,
  *Layer height (ft)*, *Layer skin*, *Formation GOR (scf/STB)* and *Water cut (%)*. The cells that do not apply to the
  chosen model are greyed out: a PI layer needs only its PI; a Darcy layer needs perm, height and skin and its PI is
  calculated (Darcy equation, pseudosteady, with the Bo, viscosity, re and rw at the top of the window) and shown greyed.
  Pressures are in psig (the program adds 14.7 psi). Layers are added and removed with *Add layer* and the X buttons;
  *Apply and recalculate* closes the window. A GOR of 0 means the solution GOR. Layers produce into the same flowing
  bottom-hole pressure; each is a straight line above the bubble point and Vogel below it (as the PI model). Option
  The pop-up also draws the IPR of each layer (dashed) and the composite IPR (solid black), using the bubble point of the
  last calculation. Option *crossflow*: a layer whose pressure is below Pwf takes fluid in (linear in the pressure difference); off, such a layer
  is simply shut. The IPR curve starts at the highest layer pressure.
  **What the layers produce.** At a flowing pressure, each producing layer adds its liquid; its water is
  liquid x water cut, its oil is liquid x (1 - water cut) and its gas is oil x its GOR. The well stream is the sum:
  water cut = total water / total liquid, GOR = total gas / total oil. Because the layers produce different shares at
  different pressures, the mixture depends on the rate: for every rate the program takes the flowing pressure the IPR
  needs for that rate, works out the mixture at that pressure, and calculates the tubing with that water cut and GOR.
  So the VLP curve, the operating point, the profile, the gas lift design and the gas lift performance curve all use the
  commingled mixture, and the water cut and GOR at the operating point are shown under the charts. For this IPR the
  water cut and GOR boxes under *Fluid (PVT)* are not used (the layer table replaces them) and the water cut and GOR
  sensitivities are not offered. Sensitivity: reservoir pressure (highest layer, the others scale with it) and a
  multiplier on all layer PIs. Layers are taken at the same depth and share one bubble point and one PVT.
* **Gas wells: horizontal and multilayer IPR.**
  *Horizontal gas well* (two models, *Horizontal well (Joshi)* and *Horizontal well (Kuchuk-Goode)* in the gas IPR list).
  The shape of the flow in the reservoir is the same for oil and gas, so the oil geometry is reused in pressure-squared
  form: the laminar coefficient is a = 1422 T mu z B / (kh h) [psi^2 per Mscf/d], where B is the bracket of the Joshi equation
  (or pwD + skin for Kuchuk and Goode); for a vertical well B = ln(re/rw) - 3/4 + S gives the usual Darcy gas equation. Then
  Pr^2 - Pwf^2 = a q + b q^2 as for the Jones model. **Assumption to check:** the turbulence term b = 3.161e-12 beta T gas_sg z /
  (L^2 rw) is the vertical-well Jones term with the well length L in place of the perforated thickness (the gas enters through
  2 pi rw L instead of 2 pi rw h). It is the usual engineering extension, not a published horizontal-well equation. A long
  horizontal well has very little turbulence loss. Z and viscosity are taken at 75 % of the reservoir pressure; beta is
  entered, or estimated from kh (Firoozabadi and Katz). Inputs are the same as for the oil horizontal wells (kh, kv/kh,
  thickness, length, drainage radius or the Kuchuk-Goode box, rw, skin). Sensitivity: length, kh, skin.
  *Multilayer gas well* (*Multilayer (commingled)* in the gas IPR list): press *Edit gas layer table...*. One row per layer:
  *Layer model* (Jones, Darcy or Back-pressure), layer pressure (psig), permeability, height, skin (Jones and Darcy
  layers) or C and n (back-pressure layers), and the layer's own **CGR and WGR** (STB/MMscf). Drainage radius, wellbore
  radius and beta (0 = estimate from each layer's k) at the top of the window are common to all layers. A Jones or Darcy layer gets
  its a (and b) from its own k, h and skin, with Z and viscosity at 75 % of the layer pressure (the well-stream gravity of the
  layer's CGR is used for its gas). The layer rates at the same Pwf are added (each layer is solved from its own Pr^2 - Pwf^2 =
  a q + b q^2, or q = C (Pr^2 - Pwf^2)^n). *Crossflow*: a layer below Pwf takes gas (negative rate, laminar law for Jones
  and Darcy layers); off, it is shut. The curve starts at the highest layer pressure.
  **What the layers produce.** Each producing layer adds its gas, its condensate (gas x CGR) and its water (gas x WGR);
  the well stream has CGR = total condensate / total gas and WGR = total water / total gas. As in the oil case, for every
  rate the flowing pressure the IPR needs is found, the mixture at that pressure is calculated, the well-stream gas gravity
  is recalculated from the mixed CGR (McCain) and the tubing is calculated for that fluid. The CGR and WGR at the operating
  point are shown under the charts. For this IPR the CGR and WGR boxes under *Fluid (PVT)* are not used. Sensitivity: layer
  pressures (highest layer, the others scale with it) and a multiplier on the layer deliverabilities (a divided by the
  multiplier, b by its square, C multiplied by it: every layer rate at a given Pwf is multiplied exactly).
  Layers are at one depth and share one gas (one gravity, H2S and CO2). Checks: `test_ipr.py` (hand calculations of the
  Joshi and Kuchuk-Goode a and b, the Jones and back-pressure layers, crossflow, the CGR and WGR mixture, the Pwf-for-rate
  inversion) and `test_app_helpers.py` (the layer table to a and b by hand, the operating point on the composite IPR, the
  well-stream gravity from the mixed CGR, sensitivities).
* **Horizontal well, Kuchuk and Goode** (SPE 21460, "Inflow Performance of Horizontal Wells", 1991), implemented from the paper:
  a well of any length at any place in a closed rectangular box (Eq. 3, 4, 6, 7 and Appendix A, including the extra
  series of Eq. A-21). Inputs: kx (along the well), ky/kx, kv/kx, thickness, well length, box length Lx and width Ly, well
  position as fractions of Lx, Ly and h (0.5 = middle), rw, Bo, viscosity and the mechanical skin Sm (which enters as
  S*m = (h/L) sqrt(kx/kz) Sm, Eq. 4). The top can instead be a **constant-pressure boundary** (gas cap or aquifer; Appendix B,
  Eq. B-3; the box size and the x/y position are then not used). The result is a productivity index, so the IPR is a straight
  line above the bubble point and Vogel below it, like the other oil models. Checks (`test_ipr.py`): the Bickley function
  Ki2 against the paper's Table 1; 24 points of the paper's Fig. 2 (PI against well length for three anisotropies, read from
  the simulator points in the figure) agree within 4.5 %, and the full-width well within 1.5 %; symmetry of the well
  position; the constant-pressure top against the exact limit of a cylinder near a constant-pressure plane.
  Two points in the printed paper were not taken literally: (1) Table 1 prints 0.60637 for beta = 0.5, which breaks the
  trend (0.57566 before, 0.44637 after); the value 0.50637 is what the integral gives and what is used; (2) Eq. 11 (constant-pressure
  top) prints 8h inside the logarithm, but Eq. B-3 and the algebra of Appendix A give 4h, which also reproduces the exact
  limit, so Eq. B-3 is used. The sign of the Eq. A-21 sum could not be checked independently; it changes the answer by less
  than 1 % unless sqrt(kx/kz) h / (L/2) is above 5 (a short well in a thick reservoir).
* **Petrosky and Farshad (1995)** oil viscosity (dead, saturated and undersaturated) is selectable next to Beal and
  Beggs, and is also ranked in the PVT matching window. It is within about 15 % of Beal / Beggs for typical oils.
* Deviated / horizontal wells: the survey is typed in a two-column table (MD, TVD). You can paste two columns straight
  from Excel; add rows at the bottom of the table.
* Pressure axis of the IPR / VLP chart and of the pressure-temperature profile starts at 0 psi, so the wellhead pressure
  reads off easily.
* Default wellbore radius is 0.354 ft (a 8.5 in hole) for every IPR model.
* Sensitivity tab: the IPR / VLP chart shows one curve for each value of the varied input (for example one VLP for each
  wellhead pressure, one IPR for each productivity index), with the operating point of each value; the chart next to it
  plots the oil rate (or produced gas rate) against the input. The values can be an automatic range (from, to, number
  of points) or typed by hand (comma separated, 2 to 12 values). Inputs you can vary: wellhead pressure, reservoir
  pressure, tubing size, water cut, total GOR, and, depending on the IPR model, PI, permeability, horizontal length,
  horizontal permeability (kv moves with kh) and total skin factor.
* Defaults: water cut 30 %, water specific gravity 1.02 (the page converts it to wt % salinity for the PVT equations),
  horizontal well kh 50 md with kv = 10 % of kh. "Total (producing) GOR" 0 means the same as the solution GOR.
* **Which VLP correlation?** The *VLP correlation* box shows the name of the correlation (no "Recommended" entry any
  more); the page starts on the one the app suggests for the well. Under the box a short text says whether the selected
  correlation looks well suited, should be usable or may not suit this well, and why, and (when it is not the app's own
  suggestion) which one the app would suggest. It only uses the fluid, the equipment and the well path entered, so it
  ends by pointing to the *VLP comparison* tab for a comparison with a measured downhole pressure gauge or flowing gradient
  survey. The text follows
  `correlation_advice()` in `app_helpers.py`, which rates each correlation "good", "ok" or "caution" from the fluid, the
  water cut and the well path, with the reason shown under the list. The rules come from the correlations' own papers and from common field practice: Hagedorn and Brown for slug flow at moderate to high rates but not for mist flow or
  condensates; Duns and Ros for mist flow and high GOR, tested with less than 10 % water; Gray for gas wells up to about
  50 STB/MMscf of condensate (above that, Duns and Ros); Beggs and Brill is mainly a pipeline correlation and over-predicts
  the pressure drop of wells; Orkiszewski found best for heavy oil (API below 20) but its formulas jump where the flow
  pattern changes; Mukherjee and Brill is the one made for any angle, so a well that is steeper than 30 degrees from
  vertical anywhere gets it. The 30 degrees, 20 API and 10 % water limits are rules of thumb you can change (the constants at
  the top of that section). For an ordinary vertical light-oil well the recommendation is still Hagedorn and Brown, and
  for a dry or lean gas well still Gray, so the default only changes for a deviated well or a rich gas.
  Any correlation can still be picked by hand; one with a "caution" shows the reason.
  *Check the VLP correlation for this well* (under the charts) runs the well with every correlation
  (`check_correlations()`): rate, bottom-hole pressure, the flow patterns each one meets and its advice, and flags a
  correlation whose rate is more than 25 % from the median. If Duns and Ros finds mist or transition flow over more than
  half the well, Hagedorn and Brown is marked "caution" (it is not for mist flow). This is a screening aid. There is no
  universal rule: only a measured flowing pressure (VLP matching) tells which one is right.
  Checks: `test_app_helpers.py` (the rules at their limits, e.g. 29 and 31 degrees, 50 and 51 STB/MMscf, 60 degrees from a
  hand survey; the comparison reproduces the page's own result).
* The pressure in a step is capped at 20,000 psia (`P_MAX` in `vlp.py`). A rate that the tubing cannot carry (for example 40,000 Mscf/d
  of a rich gas in 2 in tubing) used to send the search to 100,000 psia, where the viscosity correlations go negative and the
  calculation stopped with "Reynolds number must be > 0". Now the VLP simply reads very high there, far above the IPR, and the
  operating point is found at a lower rate. The random sweep (about 40,000 pressure traverses with all correlations, oil and gas,
  vertical and deviated, with and without gas lift) now ends without a failure.
* The pressure step now cuts a step in halves when the correlation has no exact answer in it (a flow-pattern boundary with
  a big jump in the gradient: Ansari at a high GOR failed with "Pressure did not converge" before). The 100 ft steps agree
  with 25 ft steps within 1 % there (`test_vlp.py`).
* Not yet: ESP design, a horizontal-well VLP (the lateral section), gas transient IPR, live well schematic.

## Gas lift valve design: how it was tested

`test_gaslift_valves.py` reproduces worked examples of the references:

* Takacs Examples 5-18 (constant pressure drop, IPO), 5-19 (design tubing pressure line, IPO) and 5-21 (PPO): every
  valve depth, injection pressure, dome pressure, charge pressure at 60 degF and TRO within a few psi (the book reads
  charts for the 60 degF pressure).
* Takacs Example 3-1 and API RP 11V6 Table A-1 (nitrogen dome pressure and Ct), Example 2-17 (choke gas rate) and the
  valve settings of API Example 3.
* API RP 11V6 Example 3 (mandrels already spaced): with the valve settings of its Table 7 the check finds the same
  result as the text: the unloading reaches the 7000 ft valve and the 7500 ft mandrel is just out of reach.
* A design made for the page's default well passes its own check (kick-off, every transfer, stable operation) with and
  without a static liquid level; lower pressures give a shallower string.

Notes on the book formulas: the printed spacing formula of Takacs has a wrong sign in front of the gas-gradient term
(the numbers of the examples confirm the corrected form used here), and the printed "-2.226e-3" in the inverse
Winkler-Eads formula should read -2.26e-3, as in Eq 3.7.

## VLP comparison and matching (one tab)

Comparing the correlations with a measured pressure and matching the one you keep are the same job, so they
live together on the **VLP comparison and matching** tab. The sidebar only reports whether matching is on.

The tab, from top to bottom:

1. **Test conditions and measured data** - the conditions of the flowing survey and up to 10 measured points.
2. **Compare** - every correlation you tick is run and compared with the measurements.
3. **Match to the measured data** - the gravity and friction multipliers that bring the selected correlation
   closest to the measurements (least squares).
4. **Match from a single measured test** - for a well with one measured bottom-hole pressure and no survey.
5. **Multipliers in use** - the two sliders themselves, **Use these multipliers** and **Reset to 1.00**.

The *gravity multiplier* scales the weight of the fluid column, the *friction multiplier* scales the friction
part of the pressure drop; 1.00 and 1.00 give the correlation as published (the default). They apply everywhere
else in the app - the IPR/VLP chart, the profile, the sensitivities and the gas lift design - and while either
is not 1.00 a blue note above the results says so.

* One test fixes one multiplier, and a single point cannot tell which one is right. In reference case 2,
  a gravity multiplier of 1.04 brought the VLP curve above 2000 stb/d from 5.2 % to 0.7 % of the reference,
  while a friction multiplier of 1.23 (which reproduces the same test point) only brought it to 4.8 %.
  Tests at two different rates are needed to fix both multipliers.

### Comparing with a measured pressure survey

For a well with a downhole pressure gauge reading or a flowing gradient survey. The usual tubing correlation comparison:

1. Enter the test conditions: wellhead flowing pressure, water cut, rate (liquid or oil, STB/d; gas: Mscf/d with the
   condensate and water gas ratios) and the producing GOR. The page's own values are the starting point.
2. Enter up to **10 points** (measured depth in ft, pressure in psig) in the table; blank rows are skipped, the points are
   sorted by depth, and a point below the perforations is refused with a plain message.
3. Tick the correlations to compare and press **Compare**. The chart (pressure against measured depth, black squares for
   the measurements) and the table give the mean error (calculated minus measured), the mean
   absolute error and the RMS error in psi. The correlation with the smallest RMS error is named. Fancher and Brown is
   never named: it is a no-slip quality check, not a prediction.
4. Select one correlation and press **Match to the measured data**. The gravity and friction multipliers are found together by
   least squares (Gauss-Newton, `nodal.match_vlp_survey`), limited to 0.5 - 2.0, set on the sliders at the bottom of
   the same tab (rounded to
   0.01) and the case is recalculated. With the *Multipliers to find* choice set to friction only or gravity only, just that one is changed. One point can fix
   only one multiplier. A multiplier that ends at 0.5 or 2.0 is flagged: the correlation may simply be wrong for this well.
   The "matched" curve is added to the chart.

Things to know:

* The **friction multiplier is only weakly determined** by pressures at a few depths in a vertical well, because the
  weight of the column dominates. The tests recover gravity within 1 % and friction within about 0.07. Do not read the
  friction multiplier as physical truth; use it to reproduce the data.
* The test conditions apply to the comparison only; the sidebar case is not changed until you match.
* With a multilayer IPR the test water cut and GOR are replaced by the mix of the layers at that rate (the page says so).
* Pressures are **psig**, as everywhere in the app.
* A separate *free gas* GOR box is not included: the producing GOR already covers the free gas.
* **Gas lift:** when the well is on continuous gas lift, the test has a *gas lift gas rate* and an *injection depth*
  (also in the single-test matching below it). They are greyed out for any other lift type.

Checks: `test_nodal.py` ("VLP matching from a pressure survey": synthetic surveys with known multipliers are recovered,
a perfect survey gives 1.00, error cases) and `test_app_helpers.py` (reading of the table, test conditions, comparison
rows and best choice, matching, the caption text, gas lift of the test). The Streamlit page itself was checked only with
a stand-in for Streamlit; its layout has not been looked at in the real Streamlit yet.

## IPR models checked against Dr. Boyun Guo's "Reservoir Deliverability" slides

`test_ipr.py` reproduces Examples 3-1 to 3-5 of the slides (transient, steady-state and pseudosteady Darcy,
Vogel, generalised Vogel, two-well test points, Vogel and Fetkovich from tests). All of our results agree with the
published tables within the rounding of the slides (largest difference 0.4 %, on a 122 STB/d point).

* **Transient** (slides eq. 3.1): `J = kh / (162.6 Bo mu (log t + log(k / (phi mu ct rw^2)) - 3.23 + 0.87 S))`, t in hours.
  Example 3-1 gives J = 0.2075 after one month, as published. The equation only holds until the pressure disturbance
  reaches the boundary (about `948 phi mu ct re^2 / k` hours); the page warns when the chosen time is later.
* **Horizontal well** (slides eq. 3.11 - 3.13, Joshi 1988): no worked example in the slides, so the test uses a
  by-hand calculation. In Joshi's equation as printed there is no skin term; here skin is added inside the
  vertical-plane term (weighted by `Iani h / L`). Please confirm that against the paper if skin matters.
* The slides have no gas examples, so the gas IPRs are not covered by this check.

Horizontal well against the horizontal reference case (inflow only; the reference package uses the Kuchuk-Goode model and its own PVT):
our Joshi AOF with skin +5 is 10 - 17 % below the reference 82,547 STB/d, depending on which table PVT values are used (83 - 90 % of it).
The new Kuchuk-Goode model gives 8 - 17 % ABOVE it (108 - 117 %, centred well in a 5000 x 5000 ft box, ky = kx).
The reference number lies between the two. The remaining gap cannot be pinned on one cause from here: the reference package takes Bo and viscosity
from its own matched PVT (we only have the table values), and its skin convention and well position are not given in the
manual text. The Kuchuk-Goode implementation itself matches the paper's own figure to a few percent (see above).

## Comparison with a commercial nodal analysis package

`test_reference_cases.py` reproduces three solved examples from the manual of a commercial nodal analysis package
(case 1, a gas well; case 2, an oil well; case 3, a deviated oil well) and prints the difference
at the operating point and at every one of the 20 points of its IPR / VLP results table.
The package's own in-house correlation is not published, so a small difference is normal.

| | Reference | This program | Match |
| --- | --- | --- | --- |
| Case 2 oil, vertical: rate (Hagedorn and Brown) | 10,897.5 stb/d | 11,348 stb/d | 95.9 % |
| Case 2 oil, vertical: bottom-hole pressure | 2,656 psia | 2,600 psia | 97.9 % |
| Case 3 oil, deviated: rate (Hagedorn and Brown) | 10,899.5 stb/d | 11,199 stb/d | 97.3 % |
| Case 3 oil, deviated: bottom-hole pressure | 2,683 psia | 2,647 psia | 98.7 % |
| Case 1 gas: rate (dry gas + Jones) | 19,400 Mscf/d | 19,436 Mscf/d | 99.8 % |
| Case 1 gas: bottom-hole pressure | 2,108.6 psia | 2,105.2 psia | 99.8 % |

What the point-by-point comparison shows:

* **IPR**: our Darcy oil IPR is within 0.25 % of the reference at all 20 points (both oil wells); our Jones gas IPR is within 3 %.
* **Oil VLP**: the reference lies between our two correlations. Hagedorn and Brown is 2 - 6 % low, Beggs and Brill 7 - 19 % high.
  The gravity part of the pressure drop agrees with the reference (case 3: 2,006.6 against 2,006.3 psi); the friction part
  is 11 - 12 % low with Hagedorn and Brown.
* **Gas VLP**: with only 5 stb/MMscf of condensate the reference behaves like a dry-gas well (our dry-gas calculation is
  within 0.3 % at every rate). Gray with the condensate is within 3 % between 3 and 20 MMscf/d, but 70 % high at the lowest
  rate and 12 % low at the highest.
* **Known gap**: the wellhead temperature of the deviated well (reference 179 F, ours 152 F). The vertical well agrees within 2 F.

Check results against a commercial program before relying on them for decisions.
