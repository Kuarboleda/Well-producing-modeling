# The browser version (work in progress)

> **Why this folder is called `docs`:** GitHub Pages publishes a website straight from a folder with
> that exact name, with one setting and nothing else to install. It is a poor name for a website, but
> it is GitHub's name, not ours.

This folder is the app rewritten to run **inside the browser**, with no server. That is the whole
point: a page made of files cannot go to sleep, so it opens instantly, it is free to host forever,
and it costs nothing no matter how many people use it.

The Streamlit version in the folder above still works and is still the reference: every number this
page produces is checked against it (see below).

**Scope:** natural flow and continuous gas lift. ESP is not part of this app.

**What the page does now:** the inflow (IPR) for every model, the tubing (VLP) with all eight
correlations, the operating point where they cross, the pressure and temperature profile down the
well, continuous gas lift, sensitivities on one input at a time, the correlation chosen for the well
from its own inputs with the reason given, the correlations compared against a measured downhole
gauge reading or flowing gradient survey, and matching the chosen one to that data - in oilfield or
metric units. Every inflow model the engine carries is on the screen: PI, Vogel, Darcy in its
three regimes, Fetkovich, both horizontal models (Joshi, and Kuchuk and Goode) and commingled
layers, for oil and for gas. Still to come: the gas lift valve design, PVT matching to laboratory
data, and the survey and layer tables as tables rather than pasted text.

**Windows.** Three things on the page are tables rather than boxes, and one is a whole job rather
than an input: the survey, the oil layers, the gas layers, and comparing the correlations to a
measured survey. Each opens in a window from the section it belongs to - *Well path...* under
Equipment, *Edit the layer table...* under the inflow model, *Compare and match to measured
data...* under VLP correlation. A tab is for a view you come back to; these are jobs done once and
closed, and keeping them in the panel either swamped it or put them somewhere they did not belong.

Every table writes what it holds into a plain text value that stays in the page, and that text is
what the rest of the app reads - the survey parser, the layer parsers, what is remembered in this
browser, and every check over them. So the table is a way of filling that value in, not a second
copy of it to keep in step; anything that sets the value from outside, such as a remembered well or
*Reset*, is carried straight back into the table. Click a cell and paste a block out of a
spreadsheet: the block lands with that cell as its top left corner, rows are added if it runs past
the end, and a heading row is left out.

**Commingled layers.** One row per layer. An oil layer is either a **PI** layer, entered by its
productivity index, or a **Darcy** layer, entered by permeability, thickness and skin, which has
its index worked out from them with the Bo, viscosity, re and rw at the foot of the window - the
same two models, with the same shared numbers, as the Python. A gas layer is **Jones**, **Darcy**
or **Back pressure**; the first two are described by the rock they sit in, the third by a curve
fitted to a test, so it takes C and n instead, and the cells a model does not use are greyed out
rather than hidden, so the columns still line up. A GOR of 0 means the solution GOR. Every gas
layer gets its own Z, viscosity and well-stream gravity, worked out from its own pressure and its
own CGR: a deeper, richer layer is a different gas from the one above it. The layers bring their
own pressures, so the Pr box at the top of the panel is greyed out and the curve starts at the
highest layer. What the well produces is then the mixture at the rate it settled at - which is not
what the PVT panel says - so the rates across the top, and the fluid moving in the drawing, are
taken from that mixture.

**Colour.** Oil green, water blue, gas red, total liquid black, GOR orange, water cut cyan - the
surveillance convention, so a colour means the same thing on every chart, in the drawing and in the
rates across the top of the page. `colours.js` holds the only copy: `FLUID_COLORS` gives each fluid
two shades of its own colour, `line` (the pure hue) for a stroke or a marker on white, and `text`
(slightly softer) for the rate numbers, where a pure primary at 21px is harsh to read. The `.kpis`
rules in `index.html` are the one copy that cannot import the file, so the page test compares the
two and fails if they drift apart.

Three things are deliberately NOT in that palette. The **IPR and VLP curves** are dark slate blue
and purple: an IPR is a pressure against a rate, not a stream of oil, and drawn blue it would read
as water on a page where blue means water. The **packer** stays hatched red, as it is drawn the
world over, but a shade off the gas red. And the **lift gas** in the drawing keeps its own amber,
because the drawing is the one place that has to tell the gas going in apart from the gas coming
out. The per-series colour cycles on the correlation-comparison and sensitivity-curve charts are
unchanged: no fluid is drawn on either, and every line there carries its value in its name.

**The sensitivity chart** draws two rates against whatever is being varied: the total the well
makes and the part of it that is saleable - liquid and oil, or gas and condensate - each in the
colour that rate is written in across the top of the page. The total on its own hides what matters
for anything that moves the water cut: the liquid can hold up while the oil falls away under it.

**What can be varied, one at a time:** wellhead pressure, reservoir pressure, tubing size, water
cut, producing GOR, and whichever of the inflow model's own numbers it actually has - the
productivity index for a PI entry, C for a back-pressure curve, the permeability and the skin for
anything read from the rock, and the well length for a horizontal well. A model fitted to a well
test (PI, Vogel, Fetkovich, back pressure) has its skin already buried in the test, so there is
none to vary and none is offered. When the well is on continuous gas lift, the injection rate and
the injection depth can be varied too: both live on the fluid rather than in the inflow model,
because what the gas changes is the weight of the column above the injection point. A value the
model refuses outright - a horizontal well longer than the area it drains, say - is reported in its
own row rather than throwing the whole sweep away.

## The interface, and why it is this shape

A panel of inputs on the left and the answers on the right is what every nodal tool does, and it is
what the Streamlit version does, so the two stay recognisably one app. What was wrong with it was
measurable rather than a matter of taste, so it was measured:

* With the input sections open on a 1366x768 laptop, **Calculate sat 2,055px down the page** - three
  screens below the fold. You changed a pressure at the top, scrolled down to press the button, then
  scrolled back to read the answer. It is now in a bar that sticks to the bottom of the panel and
  never leaves the screen.
* On a phone the first chart was **2,163px down**, so you scrolled past every input before seeing a
  single answer. The answers now come first and the bar is fixed to the bottom of the screen; the
  chart starts at 578px.
* The tubing side waits for the button, so the page could show an operating point for a well that had
  since been edited. Any input change now greys the answers and the bar says to press Calculate
  again - a wrong number in a report is worse than a slow page.
* **Enter** in any input box calculates. In the survey box it adds a line, as it must.
* The Equipment section draws **the well**: its path, the tubing, the perforations and the gas lift
  injection point, from the same survey the calculation uses. A survey typed wrong or a valve below
  the perforations is obvious in a picture and invisible in a column of numbers.
* Beside the pressure and temperature profile is **the well itself**, drawn from the inputs: the
  Christmas tree - cap, swab, two master valves and the production wing - the wellhead annulus
  seal standing above the ground line, the gas lift inlet below it, the casing, the tubing, the
  packer, the tailpipe, the side pocket mandrel, the perforations and the casing shoe.

  It is flat line art rather than a shaded picture: one bold black line for the casing and one for
  the tubing, with the fluid filling right up to each.  A pair of lines for each string read as four
  pipes instead of two.  The tree is drawn in grey because it is context, not the subject, and the
  component names are hover tooltips rather than a column of labels down the side.  The tubing is
  drawn at the size that was entered while the casing stays put, so a 4 1/2" string visibly fills
  more of the annulus than a 2 7/8" one.

  The gas lift inlet is ALWAYS on the drawing, open and amber when injecting and greyed and shut
  when not, so the two states are one picture with one thing changed rather than two different
  drawings.  With gas lift on the annulus holds a gas column from the wellhead seal down to the
  valve and dead completion fluid below it, which is what an unloaded annulus looks like, and gas
  jets through the mandrel into the tubing.  With gas lift off the whole annulus is dead fluid.

  The packer sits above the perforations and the tailpipe ends at the top of them.  The swab valve
  is shut, so nothing is ever drawn standing in the pipe above it, and everything the well makes
  leaves through the production wing - the pocket above the tee is a dead leg, drawn filled but
  still.

  Inside the tubing the flow regime is DRAWN, not tinted.  Bubble flow is a liquid column with
  dispersed bubbles in it; slug flow is dome-topped Taylor bubbles spanning most of the bore with
  liquid slugs between them; churn is distorted gas pockets and frothy liquid bridges; annular is a
  gas core inside a wavy liquid film on the wall, with entrained droplets.  Hovering anywhere on
  the tubing says which regime it is and over what depths.  Which regimes appear is the
  correlation's answer, not the drawing's choice.  Oil is green, water blue and gas red - bright
  for injected lift gas, deep for solution gas below the valve, and the red in between above it.

  The depth scale is shared with the pressure and temperature profile beside it: both panels put
  TVD = 0 and the deepest point at the same two heights, so a depth read off one is at the same
  place on the other.

  What the well makes - liquid, oil, water and gas rates and the drawdown - is in the strip across
  the top of the three panels; Pwf, AOF and reservoir pressure sit beside the drawing.

  Only five of the eight work out a pattern at all: Hagedorn and Brown has one holdup correlation for
  everything, Gray assumes the gas is continuous without naming a pattern, and Fancher and Brown
  ignores slip. When one of those is in use, the drawing borrows the pattern from the best suited of
  the five that do - judged for the same well by the same rules that pick the correlation - and says
  underneath whose pattern it is and that every pressure on the page is still the chosen
  correlation's. Mapping a correlation's own output to a plausible-looking pattern it never computed
  would be the drawing claiming something the calculation never said.
* The note under the correlation box is **one line** - the name and the verdict - with the reasons
  behind an (i) button, because a paragraph under every input makes the panel unread.
* The well is **remembered in this browser** (and only there - nothing is sent anywhere), so a
  refresh does not throw it away. **Reset** puts the starting values back. A first-time visitor sees
  the starting well, not someone else's.

## Choosing the correlation

The correlation box starts on the one the app suggests for the well that has been entered - the
fluid, the water cut or condensate ratio, the oil gravity and the well path - and follows that
suggestion as those inputs change, until a correlation is chosen by hand. Underneath it, the page
names the correlation, says whether it looks well suited, usable, or doubtful for this well, and
gives the reason from the correlation's own paper.

Every one of those notes ends the same way, on purpose: **this only uses the fluid, the equipment and
the well path.** No set of rules can say which correlation is right for a well. Only a measured
flowing pressure can, which is what the *VLP comparison and matching* tab is for.

## What is here so far

| File | What it is |
|---|---|
| `index.html` | the page: the input panel on the left, three tabs on the right |
| `app.js` | wiring only - reads the boxes, calls the engine, draws the charts. No engineering in it |
| `pvt.js` | translation of `pvt.py`: bubble point, Rs, Bo, oil and gas viscosity, Z, water |
| `ipr.js` | translation of `ipr.py`: PI, Vogel, Darcy (3 regimes), Fetkovich, gas Darcy / Jones / back pressure, horizontal wells, multilayer |
| `vlp.js` | translation of `vlp.py`: the fluids, the pressure traverse and all eight gradient correlations - friction factor, surface tension, Beggs and Brill, Hagedorn and Brown, Gray, Orkiszewski, Duns and Ros, Ansari, Mukherjee and Brill, Fancher and Brown |
| `well.js` | translation of `well.py`: the survey, cutting the well into steps, the temperature profile |
| `wellview.js` | the live well drawing: the completion, and the fluid animated through it |
| `nodal.js` | translation of `nodal.py`: the operating point, VLP matching, sensitivities |
| `advice.js` | translation of the advice part of `app_helpers.py`: which correlation suits this well, and why |
| `units.js` | the one place where what you type (psig, or barg in metric) meets what the engine uses (always psia and oilfield units) |
| `colours.js` | `FLUID_COLORS`: the one place the fluid colours are written, read by the charts and by the drawing |
| `tools/dump_pvt.py`, `tools/dump_ipr.py` | run the PYTHON engine over thousands of cases and save the answers |
| `tools/dump_nodal.py` | the same for the nodal analysis: operating points, matching, sensitivities |
| `tools/crosscheck.mjs` | feed the same cases to the JavaScript and report the largest disagreement |
| `tools/test_units.mjs` | checks the unit conversions on their own, including a round trip through both systems |
| `tools/dump_advice.py` | the same for the correlation advice - the only part that compares WORDS |
| `tools/test_ui.mjs` | drives the real page and checks the interface: the Calculate bar, the well drawing, the packer and the wellhead seal, the tailpipe in the perforations, the tree's four valves, the annulus state with gas lift on and off, the flow regimes, the shared depth scale, the rate strip, the telemetry, the out-of-date marker, Enter, the remembered well, the three-column layout, the phone layout |
| `tools/test_page.mjs` | drives the real page in a real browser: every tab, every button, both unit systems, oil and gas, gas lift, a deviated survey, the correlation advice, the comparison with measured data and a bad input (110 checks) |

`vlp.py` is 2,000 lines and eight correlations, so it is being translated in stages, each one
cross-checked before the next begins:

1. **done** - friction factor, surface tension, Beggs and Brill (1973)
2. **done** - Hagedorn and Brown (1965) with the Griffith bubble correction, Gray (1974)
3. **done** - Orkiszewski (1967), Duns and Ros (1963) with its eight chart tables
4. **done** - Ansari et al. (1994) including the slug-flow blend, Mukherjee and Brill
   (1983/1985), Fancher and Brown (1963): all eight correlations are now translated
5. **done** - `well.js` (survey, steps, temperature profile), the fluid objects
   (`OilWaterFluid`, `GasFluid`), the step solver and the pressure traverse

After that: gas lift, PVT matching, and the rest of the screens.

## How the JavaScript is kept honest

The Python engine was checked against the SPE papers and against published reference cases. Rather
than repeat that work, the JavaScript is checked against the **Python**:

```
cd docs
PYTHONPATH=.. python3 tools/dump_pvt.py tools/pvt_expected.json
PYTHONPATH=.. python3 tools/dump_ipr.py tools/ipr_expected.json
PYTHONPATH=.. python3 tools/dump_vlp.py tools/vlp_expected.json
python3 tools/dump_nodal.py tools/nodal_expected.json
python3 tools/dump_advice.py tools/advice_expected.json
node tools/crosscheck.mjs
```

Every function keeps the same name and the same argument order on both sides, so the comparison needs
no knowledge of the physics. The tolerance is 1e-9 (about ten decimal places).

`advice.js` is the exception: its answers are **sentences**, so those 1,324 cases are compared word
for word. If a sentence is reworded on one side only, the cross-check fails - which is the point,
because the browser version and the Streamlit version must say the same thing about the same well.

As of 20 Nov 2026: **37,952 cases, 0 failures, largest disagreement 6.56e-13** - which is nothing but
floating-point rounding. Most IPR functions agree exactly, to the last bit.

This is not a formality. Within the first ten minutes it found a real bug in the Python: `pb_petrosky`
returns a **negative** bubble point below roughly 100 scf/STB of solution GOR (6,738 of 7,590 low-GOR
cases tried). Python then raised `(p/pb)` to a fractional power with a negative base in the
Vasquez-Beggs undersaturated viscosity and quietly returned a **complex number**, which flowed on into
the density and the VLP with no error or warning. JavaScript gives `NaN` for the same expression,
which is why the comparison caught it. Both engines now hold the calculated bubble point at
atmospheric or above; `test_pvt.py` checks 126,720 oil cases for it.

## Running it on your own computer

The files use ES modules, which browsers refuse to load straight off the disk (`file://`), so it needs
a web address even locally. Python gives you one in a line:

```
cd docs
python3 -m http.server 8000
```

then open `http://localhost:8000` in the browser. On the real site (GitHub Pages) nothing is needed:
the address is already a web address.

## Checking the code for mistakes

There is no build step - the files served are the files written. Types are described in comments, and
TypeScript can check them without compiling anything:

```
npx tsc --noEmit --allowJs --checkJs --target es2022 --module esnext --moduleResolution bundler *.js
```

This catches arguments passed in the wrong order or the wrong shape, which is the mistake that matters
most in a file full of numbers.

## Things decided along the way

* **Pressure.** The engine works in psia throughout, exactly like the Python. Everything you see and
  type is psig. `units.js` is the only crossing point.
* **The page opens with the same default inputs as the Python app** (`DEFAULTS` in
  `app_helpers.py`), so a well can be read straight off it without entering anything. There is no
  separate list of example wells: the defaults *are* the example.
* **Two unit systems**, oilfield (the default) and metric, chosen from the box at the top right. The
  engine never learns that metric exists: it is always handed oilfield units and absolute pressure,
  so it stays line for line the same calculation as the Python. Everything the screen shows or reads
  passes through `units.js`.
* **Switching system does not change the well.** Every number already typed is re-expressed, so
  3,000 psig becomes 206.843 barg. The number you *typed* is also remembered, so switching back
  gives 3,000 again and not 2,999.996 - flipping between systems any number of times cannot walk the
  well away from what was entered.
* **The back-pressure coefficient C** is the one unit that cannot be written down in advance, because
  the exponent n sits inside it: q = C (Pr² − Pwf²)ⁿ, so C is measured in rate per pressure-squared
  to the power n. It is converted with n rather than from a table, and its label is written out in
  full next to the box.
* **AOF** is quoted at zero *absolute* pressure, the convention the Python uses and the one the inflow
  models were checked against. On the chart the axis starts at zero gauge, so the small tail below it
  is simply not drawn.
* **Plotly** draws the chart, loaded from a CDN at an exact version. If it cannot be fetched the page
  says so and the curve is still readable as a table.
* **Saving a case** writes a small `.json` file to your computer and opening one reads it back. There
  is no server, so there is nowhere else for it to go - which also means nothing you type is ever sent
  anywhere.

## Licence

Copyright (c) 2026 Vu Huu Huy. Free for non-commercial use; see `LICENSE.md` at the top of the
repository.

Worth knowing, because it follows from how this app works: a browser app sends its JavaScript to
every visitor, so anyone can read `pvt.js`, `ipr.js` and `vlp.js` from the page itself. That is
inherent to running without a server and has nothing to do with the repository being public. The
licence sets out what people may legally do with the code; it does not and cannot stop them reading
it.
