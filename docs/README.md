# The browser version (work in progress)

> **Why this folder is called `docs`:** GitHub Pages publishes a website straight from a folder with
> that exact name, with one setting and nothing else to install. It is a poor name for a website, but
> it is GitHub's name, not ours.

This folder is the app rewritten to run **inside the browser**, with no server. That is the whole
point: a page made of files cannot go to sleep, so it opens instantly, it is free to host forever,
and it costs nothing no matter how many people use it.

The Streamlit version in the folder above still works and is still the reference. Nothing here
replaces it yet.

## What is here so far

| File | What it is |
|---|---|
| `index.html` | the page: the input panel, the chart area and the results |
| `app.js` | wiring only - reads the boxes, calls the engine, draws the chart. No engineering in it |
| `pvt.js` | translation of `pvt.py`: bubble point, Rs, Bo, oil and gas viscosity, Z, water |
| `ipr.js` | translation of `ipr.py`: PI, Vogel, Darcy (3 regimes), Fetkovich, gas Darcy / Jones / back pressure, horizontal wells, multilayer |
| `vlp.js` | translation of `vlp.py`, **in progress**: so far the friction factor, surface tension and Beggs and Brill |
| `units.js` | the one place where psig (what you type) meets psia (what the engine uses) |
| `tools/dump_pvt.py`, `tools/dump_ipr.py` | run the PYTHON engine over thousands of cases and save the answers |
| `tools/crosscheck.mjs` | feed the same cases to the JavaScript and report the largest disagreement |

`vlp.py` is 2,000 lines and eight correlations, so it is being translated in stages, each one
cross-checked before the next begins:

1. **done** - friction factor, surface tension, Beggs and Brill (1973)
2. Hagedorn and Brown, Gray
3. Orkiszewski, Duns and Ros
4. Ansari (including the slug-flow blend), Mukherjee and Brill
5. Fancher and Brown, the fluid objects, the pressure traverse and the step solver

After that: the nodal solver, gas lift, and the rest of the screens. Until the traverse lands there is
no operating point, so the page draws the inflow only.

## How the JavaScript is kept honest

The Python engine was checked against the SPE papers and against a commercial package. Rather than
repeat that work, the JavaScript is checked against the **Python**:

```
cd docs
PYTHONPATH=.. python3 tools/dump_pvt.py tools/pvt_expected.json
PYTHONPATH=.. python3 tools/dump_ipr.py tools/ipr_expected.json
PYTHONPATH=.. python3 tools/dump_vlp.py tools/vlp_expected.json
node tools/crosscheck.mjs
```

Every function keeps the same name and the same argument order on both sides, so the comparison needs
no knowledge of the physics. The tolerance is 1e-9 (about ten decimal places).

As of 20 Nov 2026: **16,693 cases, 0 failures, largest disagreement 6.56e-13** - which is nothing but
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
* **Metric units.** Not offered yet, but `units.js` already holds the conversions, so turning them on
  later is a change in one file rather than in every file.
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
