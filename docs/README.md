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
metric units. Still to come: the gas lift valve design, the ESP design, PVT matching to laboratory
data, horizontal-well and multilayer inflow on the screen (the engine behind them is already
translated), and the survey table as a table rather than pasted text.

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
* Beside the pressure and temperature profile, a second drawing shows **the flow pattern in the
  tubing**: the pipe from wellhead to perforations, coloured by the pattern the correlation reports
  at each step, with bubbles, slugs or a wall film drawn inside it and the depths where the pattern
  changes marked. Only five of the eight correlations work out a pattern at all; for the other three
  the drawing is left blank and says so rather than guessing one.
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
| `nodal.js` | translation of `nodal.py`: the operating point, VLP matching, sensitivities |
| `advice.js` | translation of the advice part of `app_helpers.py`: which correlation suits this well, and why |
| `units.js` | the one place where what you type (psig, or barg in metric) meets what the engine uses (always psia and oilfield units) |
| `tools/dump_pvt.py`, `tools/dump_ipr.py` | run the PYTHON engine over thousands of cases and save the answers |
| `tools/dump_nodal.py` | the same for the nodal analysis: operating points, matching, sensitivities |
| `tools/crosscheck.mjs` | feed the same cases to the JavaScript and report the largest disagreement |
| `tools/test_units.mjs` | checks the unit conversions on their own, including a round trip through both systems |
| `tools/dump_advice.py` | the same for the correlation advice - the only part that compares WORDS |
| `tools/test_ui.mjs` | drives the real page and checks the interface: the Calculate bar, the two well drawings, the flow patterns of every correlation, the out-of-date marker, Enter, the remembered well, the three-column layout, the phone layout (71 checks) |
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
