"""Quick checks for well.py.  Run:  python test_well.py

Each "expected" number is either simple geometry or was worked out by hand (the
arithmetic is in the comments).  A check passes when the code agrees to within 0.1 %.
If a check fails, the script stops and tells you which one.
"""
from well import *


def check(name, got, expected, tol=0.001):
    """Pass if 'got' is within tol (0.001 = 0.1 %) of 'expected' (exactly 0 -> within 1e-6)."""
    if expected == 0:
        ok = abs(got) <= 1e-6
    else:
        ok = abs(got - expected) <= tol * abs(expected)
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<48s} got {got:12.6g}   expected {expected:12.6g}")
    assert ok, name


def check_error(name, function, *args, **kwargs):
    """Pass if calling function(...) raises a ValueError (bad input is rejected)."""
    try:
        function(*args, **kwargs)
    except ValueError:
        print(f"  PASS  {name:<48s} (ValueError raised, as wanted)")
        return
    raise AssertionError(f"{name}: expected a ValueError but none was raised")


# =====================================================================
print("== Vertical well, 10,000 ft, 100-ft steps ==")
md, tvd = vertical_survey(10000)
w = Well(md, tvd, simple_tubing(2.992, 10000), 200.0)
steps = build_steps(w, 100.0)
check("number of steps", len(steps), 100)
check("every step is vertical (90 deg): smallest angle", min(s["angle_deg"] for s in steps), 90.0)
check("steps add up to the full length", sum(s["length"] for s in steps), 10000.0)
check("last step ends at the perforations (MD)", steps[-1]["md_bot"], 10000.0)
check("last step ends at the perforations (TVD)", steps[-1]["tvd_bot"], 10000.0)
check("tubing ID in every step", steps[50]["id_in"], 2.992)
check("a 250-ft well with 100-ft max steps -> 3 steps",
      len(build_steps(Well(*vertical_survey(250), simple_tubing(2.992, 250), 150.0), 100.0)), 3)

print("\n== Deviated well: vertical, then 30 deg, then horizontal ==")
# MD 0-2000: TVD 0-2000          -> sin(angle) = 2000/2000 = 1    -> 90 deg
# MD 2000-4000: TVD 2000-3000    -> sin(angle) = 1000/2000 = 0.5  -> 30 deg
# MD 4000-7000: TVD stays 3000   -> angle 0 (horizontal)
md = [0, 2000, 4000, 7000]
tvd = [0, 2000, 3000, 3000]
w = Well(md, tvd, simple_tubing(2.992, 7000), 180.0)
steps = build_steps(w, 100.0)
check("number of steps (20 + 20 + 30)", len(steps), 70)
check("step in the first section (angle)", steps[10]["angle_deg"], 90.0)
check("step in the second section (angle)", steps[25]["angle_deg"], 30.0)
check("step in the third section (angle)", steps[60]["angle_deg"], 0.0)
check("TVD at the end of the second section", steps[39]["tvd_bot"], 3000.0)
check("TVD at the end of the well", steps[-1]["tvd_bot"], 3000.0)
check("tvd_at() halfway down the 30 deg section", tvd_at(w, 3000.0), 2500.0)

print("\n== Toe-up piece: the flow runs downhill there (negative angle) ==")
# MD 0-1000 vertical, MD 1000-2000: TVD goes back UP from 1000 to 500 -> sin = -0.5 -> -30 deg
w = Well([0, 1000, 2000], [0, 1000, 500], simple_tubing(2.992, 2000), 150.0)
steps = build_steps(w, 500.0)
check("angle of a toe-up step", steps[-1]["angle_deg"], -30.0)

print("\n== Tubing size change at MD 6000 ==")
w = Well(*vertical_survey(10000), [(0.0, 6000.0, 2.992), (6000.0, 10000.0, 4.0)], 200.0)
steps = build_steps(w, 100.0)
above = [s for s in steps if s["md_bot"] <= 6000.0 + 1e-6]
below = [s for s in steps if s["md_top"] >= 6000.0 - 1e-6]
check("steps above MD 6000 all have ID 2.992", min(s["id_in"] for s in above), 2.992)
check("steps above MD 6000 (largest ID)", max(s["id_in"] for s in above), 2.992)
check("steps below MD 6000 all have ID 4.0", min(s["id_in"] for s in below), 4.0)
check("one step ends exactly at MD 6000", float(any(abs(s["md_bot"] - 6000.0) < 1e-6 for s in steps)), 1.0)

print("\n== Pasted survey text ==")
text = """MD (ft)\tTVD (ft)
0\t0
1000, 1000
2000;1800
3000 2500
"""
md, tvd = parse_survey_text(text)
check("number of points read (header skipped)", len(md), 4)
check("last MD", md[-1], 3000.0)
check("last TVD", tvd[-1], 2500.0)
check("TVD of the third point", tvd[2], 1800.0)

print("\n== Ambient temperature table ==")
w = Well(*vertical_survey(8000), simple_tubing(2.992, 8000), 200.0)
# Default table: 80 degF / U = 5 at surface and 200 degF (reservoir) / U = 5 at the perforations
t_amb, u = ambient_at(w, 4000.0)
check("default ambient at the surface", ambient_at(w, 0.0)[0], 80.0)
check("default ambient halfway down (80 + 120/2)", t_amb, 140.0)
check("default U", u, 5.0)
check("default ambient at the perforations", ambient_at(w, 8000.0)[0], 200.0)
w2 = Well(*vertical_survey(8000), simple_tubing(2.992, 8000), 200.0,
          ambient_table=[(0.0, 60.0, 3.0), (8000.0, 200.0, 7.0)])
check("user table: U halfway down (3 + 7)/2", ambient_at(w2, 4000.0)[1], 5.0)
check("user table: T halfway down (60 + 200)/2", ambient_at(w2, 4000.0)[0], 130.0)

print("\n== Fluid temperature ==")
# Hand calculation, one 1000-ft step, ID 3.0 in (d = 0.25 ft), U = 5, constant ambient 80 degF,
# w = 10,000 lb/h, cp = 0.5:   A = pi*0.25*5 / (10000*0.5) = 7.854e-4 per ft ; A*L = 0.7854
#   T_top = 80 + (200 - 80) * exp(-0.7854) = 80 + 120 * 0.45594 = 134.71 degF
w = Well(*vertical_survey(1000), simple_tubing(3.0, 1000), 200.0,
         ambient_table=[(0.0, 80.0, 5.0), (1000.0, 80.0, 5.0)])
temps = fluid_temperatures(w, build_steps(w, 1000.0), 10000.0, 0.5)
check("one step: wellhead temperature", temps[0], 134.71)
check("one step: temperature at the perforations", temps[1], 200.0)
temps = fluid_temperatures(w, build_steps(w, 100.0), 10000.0, 0.5)
check("ten steps give the same wellhead temperature", temps[0], 134.71)
check("ten steps: 11 temperatures", len(temps), 11)

w = Well(*vertical_survey(8000), simple_tubing(2.992, 8000), 200.0)
steps = build_steps(w, 100.0)
temps = fluid_temperatures(w, steps, 20000.0, 0.5)
check("normal rate: wellhead is between ambient and reservoir",
      float(80.0 < temps[0] < 200.0), 1.0)
check("temperature rises steadily downwards",
      float(all(temps[i] < temps[i + 1] for i in range(len(temps) - 1))), 1.0)
temps = fluid_temperatures(w, steps, 1e-3, 0.5)
check("tiny rate: fluid takes the ambient temperature (80 + 120*50/8000)", temps[0], 80.75)
w_hot = Well(*vertical_survey(8000), simple_tubing(2.992, 8000), 200.0,
             ambient_table=[(0.0, 80.0, 0.0), (8000.0, 200.0, 0.0)])
temps = fluid_temperatures(w_hot, build_steps(w_hot, 100.0), 20000.0, 0.5)
check("U = 0 (no heat loss): wellhead = reservoir temperature", temps[0], 200.0)
temps = fluid_temperatures(w, steps, 0.0, 0.5)
check("no flow: wellhead at ambient temperature (80.75)", temps[0], 80.75)

print("\n== Bad inputs must be rejected ==")
check_error("survey does not start at zero", Well, [10, 1000], [10, 1000], simple_tubing(2.992, 1000), 150.0)
check_error("MD not increasing", Well, [0, 1000, 900], [0, 900, 800], simple_tubing(2.992, 900), 150.0)
check_error("TVD changes more than MD", Well, [0, 1000], [0, 1200], simple_tubing(2.992, 1000), 150.0)
check_error("tubing gap", Well, *vertical_survey(1000), [(0.0, 400.0, 2.992), (500.0, 1000.0, 2.992)], 150.0)
check_error("tubing stops short of the perforations", Well, *vertical_survey(1000), [(0.0, 800.0, 2.992)], 150.0)
check_error("tubing ID = 0", Well, *vertical_survey(1000), [(0.0, 1000.0, 0.0)], 150.0)
check_error("ambient table MD not increasing", Well, *vertical_survey(1000), simple_tubing(2.992, 1000), 150.0,
            ambient_table=[(0.0, 80.0, 5.0), (0.0, 150.0, 5.0)])
check_error("survey text with one point", parse_survey_text, "0 0")
check_error("step length = 0", build_steps, w, 0.0)

print("\nAll checks passed.")
