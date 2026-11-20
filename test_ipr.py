"""Quick checks for ipr.py.  Run:  python test_ipr.py

Every "expected" number below was worked out by hand (the arithmetic is shown in
the comments, so you can repeat it with a calculator).  A check passes when the
code agrees with the hand answer to within 0.1 %.
If a check fails, the script stops and tells you which one.
"""
import math
import warnings
from ipr import *


# ---------------------------------------------------------------------
# Two tiny helpers so that every check is one short line
# ---------------------------------------------------------------------
def check(name, got, expected, tol=0.001):
    """Pass if 'got' is within tol (0.001 = 0.1 %) of 'expected'.
    (If the expected answer is exactly 0, 'got' must be within 0.000001 of it.)"""
    if expected == 0:
        ok = abs(got) <= 1e-6
    else:
        ok = abs(got - expected) <= tol * abs(expected)
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46s} got {got:14.6g}   expected {expected:14.6g}")
    assert ok, name


def check_error(name, function, *args, **kwargs):
    """Pass if calling function(...) raises a ValueError (bad input is rejected)."""
    try:
        function(*args, **kwargs)
    except ValueError:
        print(f"  PASS  {name:<46s} (ValueError raised, as wanted)")
        return
    raise AssertionError(f"{name}: expected a ValueError but none was raised")


# =====================================================================
print("== OIL: PI entry (Pr = 3000, Pb = 2000, J = 3) ==")
# Pwf = 2500 (above Pb) : 3 * (3000 - 2500)                    = 1500
# Pwf = 2000 (= Pb)     : 3 * (3000 - 2000)                    = 3000
# Pwf = 1000 (below Pb) : qb = 3000, qv = 3*2000/1.8 = 3333.33,
#                         Vogel part = 1 - 0.2*0.5 - 0.8*0.25 = 0.7
#                         q = 3000 + 3333.33*0.7               = 5333.33
# Pwf = 0               : 3000 + 3333.33                       = 6333.33
check("PI  Pwf=2500", oil_pi(3000, 2500, 2000, 3.0), 1500.0)
check("PI  Pwf=2000 (at Pb)", oil_pi(3000, 2000, 2000, 3.0), 3000.0)
check("PI  Pwf=1000", oil_pi(3000, 1000, 2000, 3.0), 5333.33)
check("PI  AOF (Pwf=0)", oil_pi(3000, 0, 2000, 3.0), 6333.33)
check("PI  Pwf=Pr gives zero rate", oil_pi(3000, 3000, 2000, 3.0), 0.0)

print("\n== OIL: PI entry when Pr < Pb (Pr = 1500, Pb = 2000, J = 3) ==")
# Whole curve is Vogel with qmax = J*Pr/1.8 = 3*1500/1.8 = 2500
# Pwf = 750 : x = 0.5 -> 1 - 0.1 - 0.2 = 0.7 -> q = 1750
check("PI (Pr<Pb)  AOF", oil_pi(1500, 0, 2000, 3.0), 2500.0)
check("PI (Pr<Pb)  Pwf=750", oil_pi(1500, 750, 2000, 3.0), 1750.0)

print("\n== OIL: Vogel case A  (Pr < Pb, test 100 STB/d at 1800 psia, Pr = 2400) ==")
# Vogel part at test = 1 - 0.2*0.75 - 0.8*0.5625 = 0.4 -> qmax = 100/0.4 = 250
# Pwf = 1200: x = 0.5 -> 0.7 -> 175 STB/d.   J = 1.8*250/2400 = 0.1875
check("Vogel A  J", vogel_productivity_index(2400, 3000, 100, 1800), 0.1875)
check("Vogel A  AOF", oil_vogel(2400, 0, 3000, 100, 1800), 250.0)
check("Vogel A  Pwf=1200", oil_vogel(2400, 1200, 3000, 100, 1800), 175.0)
check("Vogel A  reproduces the test point", oil_vogel(2400, 1800, 3000, 100, 1800), 100.0)

print("\n== OIL: Vogel case B  (Pr = 3000 > Pb = 2000, test 600 STB/d at 2500 psia, above Pb) ==")
# J = 600 / (3000 - 2500) = 1.2
# qb = 1.2*1000 = 1200 ;  qv = 1.2*2000/1.8 = 1333.33
# Pwf = 1000 : 1200 + 1333.33*0.7 = 2133.33 ;   AOF = 2533.33
check("Vogel B  J", vogel_productivity_index(3000, 2000, 600, 2500), 1.2)
check("Vogel B  Pwf=2000 (= qb)", oil_vogel(3000, 2000, 2000, 600, 2500), 1200.0)
check("Vogel B  Pwf=1000", oil_vogel(3000, 1000, 2000, 600, 2500), 2133.33)
check("Vogel B  AOF", oil_vogel(3000, 0, 2000, 600, 2500), 2533.33)
check("Vogel B  reproduces the test point", oil_vogel(3000, 2500, 2000, 600, 2500), 600.0)

print("\n== OIL: Vogel case C  (Pr = 3000 > Pb = 2000, test 2000 STB/d at 1000 psia, below Pb) ==")
# Denominator = (3000-2000) + (2000/1.8)*0.7 = 1000 + 777.78 = 1777.78
# J = 2000 / 1777.78 = 1.125 ;  qb = 1125 ;  qv = 1.125*2000/1.8 = 1250
# AOF = 1125 + 1250 = 2375
check("Vogel C  J", vogel_productivity_index(3000, 2000, 2000, 1000), 1.125)
check("Vogel C  Pwf=2000 (= qb)", oil_vogel(3000, 2000, 2000, 2000, 1000), 1125.0)
check("Vogel C  AOF", oil_vogel(3000, 0, 2000, 2000, 1000), 2375.0)
check("Vogel C  reproduces the test point", oil_vogel(3000, 1000, 2000, 2000, 1000), 2000.0)

print("\n== OIL: cases B and C must agree when they describe the same well (J = 1.2) ==")
# From case B above, the well makes 2133.33 STB/d at Pwf = 1000.
# Feeding that as a below-Pb test (case C) must give J = 1.2 back.
check("B-test and C-test give same J", vogel_productivity_index(3000, 2000, 2133.33, 1000), 1.2)

print("\n== OIL: Darcy (k=50 md, h=20 ft, Bo=1.25, mu=0.8 cP, re=1000 ft, rw=0.5 ft) ==")
# ln(1000/0.5) - 0.75 = 7.6009 - 0.75 = 6.8509
# J = 50*20 / (141.2*1.25*0.8*6.8509) = 1000 / 967.37 = 1.03375
# Pr = 3000, Pb = 2000, Pwf = 1000: 1033.75 + (1.03375*2000/1.8)*0.7 = 1837.79
# Skin S = 5: bracket = 11.8509 -> J = 0.59760
check("Darcy oil  J (S=0)", darcy_productivity_index_oil(50, 20, 1.25, 0.8, 1000, 0.5), 1.03375)
check("Darcy oil  J (S=5)", darcy_productivity_index_oil(50, 20, 1.25, 0.8, 1000, 0.5, skin=5), 0.59760)
check("Darcy oil  q at Pwf=1000", oil_darcy(3000, 1000, 2000, 50, 20, 1.25, 0.8, 1000, 0.5), 1837.79)
check("Darcy oil  single phase q at Pwf=2500",
      oil_darcy(3000, 2500, 2000, 50, 20, 1.25, 0.8, 1000, 0.5), 1.03375 * 500)

print("\n== OIL: Fetkovich ==")
# Case n = 1 (Pr = 3000, Pr^2 = 9e6):
#   test 1: Pwf=2000 -> 9e6-4e6 = 5e6, q1 = 500
#   test 2: Pwf=1000 -> 9e6-1e6 = 8e6, q2 = 800      (500/800 = 5e6/8e6, so n = 1)
#   C = 500 / 5e6 = 1e-4 ;   Pwf = 0: 1e-4 * 9e6 = 900 ;   Pwf = 2500: 1e-4 * 2.75e6 = 275
C, n = c_and_n_from_two_tests(3000, 500, 2000, 800, 1000)
check("Fetkovich n=1 case: n", n, 1.0)
check("Fetkovich n=1 case: C", C, 1.0e-4)
check("Fetkovich n=1 case: AOF", oil_fetkovich(3000, 0, 500, 2000, 800, 1000), 900.0)
check("Fetkovich n=1 case: Pwf=2500", oil_fetkovich(3000, 2500, 500, 2000, 800, 1000), 275.0)
# Case n = 0.5, C = 0.2:  q1 = 0.2*sqrt(5e6) = 447.21 ; q2 = 0.2*sqrt(8e6) = 565.69 ; AOF = 0.2*3000 = 600
C, n = c_and_n_from_two_tests(3000, 447.2136, 2000, 565.6854, 1000)
check("Fetkovich n=0.5 case: n", n, 0.5)
check("Fetkovich n=0.5 case: C", C, 0.2)
check("Fetkovich n=0.5 case: AOF", oil_fetkovich(3000, 0, 447.2136, 2000, 565.6854, 1000), 600.0)
check("Fetkovich reproduces test point 2", oil_fetkovich(3000, 1000, 500, 2000, 800, 1000), 800.0)

# =====================================================================
# Gas well used for the Darcy / Jones checks:
#   T = 180 degF (640 degR), k = 5 md, h = 40 ft, mu = 0.02 cP, Z = 0.9,
#   gas gravity 0.65, re = 1000 ft, rw = 0.4 ft, skin 0
#   ln(re/rw) - 0.75 = ln(2500) - 0.75 = 7.07405
#   a = 1422*640*0.02*0.9*7.07405 / (5*40) = 579.42 psi^2/(Mscf/d)
GAS = dict(temp_f=180.0, k=5.0, h=40.0, mu=0.02, z=0.9, re=1000.0, rw=0.4)

print("\n== GAS: Darcy ==")
# Pr = 3000, Pwf = 2000: dp2 = 9e6 - 4e6 = 5e6  -> q = 5e6/579.42 = 8629.4 Mscf/d
# Pwf = 0              : dp2 = 9e6              -> q = 15532.9 Mscf/d
check("Darcy gas  'a' coefficient", gas_a_coefficient(180, 5, 40, 0.02, 0.9, 1000, 0.4), 579.42)
check("Darcy gas  q at Pwf=2000", gas_darcy(3000, 2000, **GAS), 8629.4)
check("Darcy gas  AOF", gas_darcy(3000, 0, **GAS), 15532.9)
check("Darcy gas  doubling k doubles q",
      gas_darcy(3000, 2000, **dict(GAS, k=10.0)), 2 * 8629.4)

print("\n== GAS: Jones (same well, gas gravity 0.65, beta estimated from k) ==")
# beta = 2.73e10 / 5^1.1045 = 4.6148e9 1/ft
# b = 3.161e-12 * 4.6148e9 * 640 * 0.65 * 0.9 / (40^2 * 0.4) = 0.0085336
# Solve 0.0085336*q^2 + 579.42*q = 5e6   ->  q = 7745.8 Mscf/d   (Darcy alone said 8629.4)
# AOF: 0.0085336*q^2 + 579.42*q = 9e6    ->  q = 13031.7 Mscf/d
check("Jones  beta from k=5 md", gas_beta_firoozabadi_katz(5.0), 4.6148e9)
check("Jones  'b' coefficient", gas_b_coefficient(180, 5, 40, 0.9, 0.65, 0.4), 0.0085336)
check("Jones  q at Pwf=2000", gas_jones(3000, 2000, gas_sg=0.65, **GAS), 7745.8)
check("Jones  AOF", gas_jones(3000, 0, gas_sg=0.65, **GAS), 13031.7)
# Own beta (1e9 1/ft) and a 20 ft perforated interval: b = 0.0073967 -> q = 7843.9
check("Jones  own beta + h_perf=20 ft",
      gas_jones(3000, 2000, gas_sg=0.65, beta=1.0e9, h_perf=20.0, **GAS), 7843.9)
# Consistency: the rate must satisfy a*q + b*q^2 = Pr^2 - Pwf^2
q = gas_jones(3000, 2000, gas_sg=0.65, **GAS)
check("Jones  a*q + b*q^2 equals Pr^2 - Pwf^2", 579.4153 * q + 0.0085336 * q ** 2, 5.0e6)
# With no turbulence (beta = 0) Jones must collapse to Darcy
check("Jones with beta = 0 equals Darcy",
      gas_jones(3000, 2000, gas_sg=0.65, beta=0.0, **GAS), 8629.4)

print("\n== GAS: back-pressure (C and n) ==")
# C = 1e-4, n = 1, Pr = 3000: Pwf = 2000 -> 1e-4*5e6 = 500 ; AOF = 1e-4*9e6 = 900
# C = 0.2,  n = 0.5:          AOF = 0.2*sqrt(9e6) = 600
check("Back-pressure  n=1  Pwf=2000", gas_backpressure(3000, 2000, 1.0e-4, 1.0), 500.0)
check("Back-pressure  n=1  AOF", gas_backpressure(3000, 0, 1.0e-4, 1.0), 900.0)
check("Back-pressure  n=0.5  AOF", gas_backpressure(3000, 0, 0.2, 0.5), 600.0)
C, n = c_and_n_from_two_tests(3000, 500, 2000, 800, 1000)
check("Back-pressure  C from two tests", C, 1.0e-4)
check("Back-pressure  n from two tests", n, 1.0)

# =====================================================================
print("\n== Examples 3-1 ... 3-5 of Guo, 'Reservoir Deliverability' (published answers) ==")
# Guo rounds his answers (e.g. 122 for 121.54), so these checks allow 0.5 %.
GUO = dict(k=8.2, h=53, bo=1.1, mu=1.7, re=2980, rw=0.328)
# Example 3-1  (Pr = 5651, Pb = 50 psia; q at Pwf = 50 is the straight line J*(Pr-50))
check("Ex 3-1 transient J (1 month)",
      darcy_productivity_index_oil_transient(8.2, 53, 1.1, 1.7, 0.19, 1.29e-5, 0.328, 30 * 24), 0.2075, 0.005)
check("Ex 3-1 transient q at Pwf=50",
      oil_darcy_regime(5651, 50, 50, regime="transient", phi=0.19, ct=1.29e-5, time_hours=720, **GUO), 1162, 0.005)
check("Ex 3-1 steady J", darcy_productivity_index_oil_steady(8.2, 53, 1.1, 1.7, 2980, 0.328), 0.1806, 0.005)
check("Ex 3-1 steady q at Pwf=50",
      oil_darcy_regime(5651, 50, 50, regime="steady", **GUO), 1011, 0.005)
check("Ex 3-1 pseudosteady J", darcy_productivity_index_oil(8.2, 53, 1.1, 1.7, 2980, 0.328), 0.1968, 0.005)
check("Ex 3-1 pseudosteady q at Pwf=50", oil_darcy(5651, 50, 50, **GUO), 1102, 0.005)
# Example 3-2 (saturated, Pb = Pr -> pure Vogel, qmax = J*Pr/1.8 = 618)
check("Ex 3-2 qmax (Pwf=0)", oil_darcy(5651, 0, 5651, **GUO), 618, 0.005)
check("Ex 3-2 Pwf=3000", oil_darcy(5651, 3000, 5651, **GUO), 413, 0.005)
check("Ex 3-2 Pwf=5000", oil_darcy(5651, 5000, 5651, **GUO), 122, 0.005)
# Example 3-3 (Pb = 3000 -> straight line above, Vogel below)
check("Ex 3-3 qb (Pwf=Pb)", oil_darcy(5651, 3000, 3000, **GUO), 522, 0.005)
check("Ex 3-3 AOF", oil_darcy(5651, 0, 3000, **GUO), 850, 0.005)
check("Ex 3-3 Pwf=1695", oil_darcy(5651, 1695, 3000, **GUO), 729, 0.005)
# Example 3-4 (two wells, one test each, Pr = 5000, Pb = 3000)
check("Ex 3-4 Well A J (test above Pb)", vogel_productivity_index(5000, 3000, 300, 4000), 0.3000)
check("Ex 3-4 Well A AOF", oil_vogel(5000, 0, 3000, 300, 4000), 1100, 0.005)
check("Ex 3-4 Well B J (test below Pb)", vogel_productivity_index(5000, 3000, 900, 2000), 0.3156, 0.005)
check("Ex 3-4 Well B AOF", oil_vogel(5000, 0, 3000, 900, 2000), 1157, 0.005)
check("Ex 3-4 Well B Pwf=2500", oil_vogel(5000, 2500, 3000, 900, 2000), 777, 0.005)
# Example 3-5 (saturated, Pr = 3000; tests 500 @ 2000 and 800 @ 1000)
check("Ex 3-5 Vogel qmax", oil_vogel(3000, 0, 3000, 500, 2000), 978, 0.005)
check("Ex 3-5 Vogel Pwf=1000", oil_vogel(3000, 1000, 3000, 500, 2000), 826, 0.005)
check("Ex 3-5 Fetkovich n", c_and_n_from_two_tests(3000, 500, 2000, 800, 1000)[1], 1.0)
check("Ex 3-5 Fetkovich C", c_and_n_from_two_tests(3000, 500, 2000, 800, 1000)[0], 1e-4)
check("Ex 3-5 Fetkovich AOF", oil_fetkovich(3000, 0, 500, 2000, 800, 1000), 900, 0.005)
check("Ex 3-5 Fetkovich Pwf=2500", oil_fetkovich(3000, 2500, 500, 2000, 800, 1000), 275, 0.005)

print("\n== OIL: transient J falls with time; steady < pseudosteady ==")
J_early = darcy_productivity_index_oil_transient(8.2, 53, 1.1, 1.7, 0.19, 1.29e-5, 0.328, 24)
J_late = darcy_productivity_index_oil_transient(8.2, 53, 1.1, 1.7, 0.19, 1.29e-5, 0.328, 24 * 90)
check("J(90 days) < J(1 day)", float(J_late < J_early), 1.0)
# Ten times more time adds exactly 1 to log10(t): bracket(24 h) + 1 = bracket(240 h)
J_10x = darcy_productivity_index_oil_transient(8.2, 53, 1.1, 1.7, 0.19, 1.29e-5, 0.328, 240)
check("1/J grows by 162.6*Bo*mu/(k*h) per decade", 1 / J_10x - 1 / J_early,
      162.6 * 1.1 * 1.7 / (8.2 * 53))
# Skin S = 5 adds 0.87*5 = 4.35 to the bracket
J_skin = darcy_productivity_index_oil_transient(8.2, 53, 1.1, 1.7, 0.19, 1.29e-5, 0.328, 720, 5.0)
J_0 = darcy_productivity_index_oil_transient(8.2, 53, 1.1, 1.7, 0.19, 1.29e-5, 0.328, 720)
check("transient skin adds 0.87*S to the bracket", 1 / J_skin - 1 / J_0,
      162.6 * 1.1 * 1.7 / (8.2 * 53) * 4.35)
# Boundary time: 948*0.19*1.7*1.29e-5*2980^2/8.2 = 4277 h
check("Time when boundary is felt", transient_end_time_hours(8.2, 0.19, 1.7, 1.29e-5, 2980), 4277, 0.005)
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    oil_darcy_regime(5651, 1000, 50, regime="transient", phi=0.19, ct=1.29e-5, time_hours=8000, **GUO)
check("Warning when time is past the boundary time", float(len(caught)), 1.0)
check_error("Transient without time", oil_darcy_regime, 5651, 1000, 50, regime="transient", **GUO)
check_error("Unknown regime", oil_darcy_regime, 5651, 1000, 50, regime="banana", **GUO)
check_error("Transient time = 0", darcy_productivity_index_oil_transient, 8.2, 53, 1.1, 1.7, 0.19, 1.29e-5, 0.328, 0)

print("\n== OIL: horizontal well, Joshi (kh=100, kv=10, h=50, L=1000, re_h=1500, rw=0.35, Bo=1.2, mu=1) ==")
# Worked by hand:  L/2 = 500 ;  (re_h/(L/2))^4 = 3^4 = 81
#   a = 500*sqrt(0.5 + sqrt(0.25 + 81)) = 500*sqrt(0.5 + 9.01388) = 500*3.08437 = 1542.23
#   sqrt(a^2 - 500^2) = sqrt(2378469.5 - 250000) = 1458.93
#   horizontal-plane term = ln((1542.23 + 1458.93)/500) = ln(6.00232) = 1.79214
#   Iani = sqrt(100/10) = 3.16228 ;  Iani*h/L = 0.158114
#   ln( Iani*h / (rw*(Iani+1)) ) = ln(158.114 / (0.35*4.16228)) = ln(108.54) = 4.68708
#   vertical-plane term = 0.158114*4.68708 = 0.74109
#   J = 100*50 / (141.2*1.2*1.0*(1.79214 + 0.74109)) = 5000 / 429.24 = 11.6487 STB/d/psi
JOSHI = dict(kh=100, kv=10, h=50, length=1000, re_h=1500, rw=0.35, bo=1.2, mu=1.0)
check("Joshi J", horizontal_productivity_index_oil_joshi(**JOSHI), 11.6487)
# Skin 5: vertical-plane term = 0.158114*(4.68708 + 5) = 1.53164 -> J = 5000/(169.44*3.32378) = 8.8781
check("Joshi J with skin 5", horizontal_productivity_index_oil_joshi(**JOSHI, skin=5.0), 8.8781)
# Pr = 3000, Pb = 2000, Pwf = 2500: straight line J*500 = 5824.4
check("Joshi rate Pwf=2500", oil_horizontal_joshi(3000, 2500, 2000, **JOSHI), 5824.4)
# Same well, Pwf = 1000: qb = 11.6487*1000 = 11648.7, qv = 11.6487*2000/1.8 = 12943.0, *0.7 = 9060.1
check("Joshi rate Pwf=1000 (Vogel below Pb)", oil_horizontal_joshi(3000, 1000, 2000, **JOSHI), 20708.8)
# Physical trends (no hand number needed, but they must hold)
long_well = dict(JOSHI, length=2000)
check("Longer well -> higher J", float(horizontal_productivity_index_oil_joshi(**long_well) > 11.6487), 1.0)
tight = dict(JOSHI, kv=1.0)
check("Lower kv -> lower J", float(horizontal_productivity_index_oil_joshi(**tight) < 11.6487), 1.0)
check("J is proportional to kh*h at fixed anisotropy and h/L ... (double kh and kv)",
      horizontal_productivity_index_oil_joshi(**dict(JOSHI, kh=200, kv=20)) / 11.6487, 2.0)
check_error("Well longer than its drainage area", horizontal_productivity_index_oil_joshi,
            **dict(JOSHI, length=3200))
check_error("kv = 0", horizontal_productivity_index_oil_joshi, **dict(JOSHI, kv=0.0))

# =====================================================================
print("\n== IPR curve builder ==")
pwf_list, q_list = ipr_curve(oil_pi, 3000, n_points=7, pb=2000, J=3.0)
# 7 points -> Pwf = 3000, 2500, 2000, 1500, 1000, 500, 0
check("Curve has 7 points", len(q_list), 7)
check("Curve starts at Pwf = Pr", pwf_list[0], 3000.0)
check("Curve starts at zero rate", q_list[0], 0.0)
check("Curve ends at Pwf = 0", pwf_list[-1], 0.0)
check("Curve ends at the AOF", q_list[-1], 6333.33)
check("Curve point 2 (Pwf=2500)", q_list[1], 1500.0)
check("Rate increases as Pwf drops",
      float(all(q_list[i] < q_list[i + 1] for i in range(6))), 1.0)
# The same builder works for the gas and Vogel models, too
pwf_list, q_list = ipr_curve(gas_jones, 3000, n_points=5, gas_sg=0.65, **GAS)
check("Jones curve ends at the Jones AOF", q_list[-1], 13031.7)

# =====================================================================
print("\n== Bad inputs must be rejected ==")
check_error("Negative Pwf", oil_pi, 3000, -10, 2000, 3.0)
check_error("PI = 0", oil_pi, 3000, 1000, 2000, 0.0)
check_error("Vogel test Pwf above Pr", oil_vogel, 3000, 1000, 2000, 500, 3500)
check_error("Vogel test rate = 0", oil_vogel, 3000, 1000, 2000, 0, 2500)
check_error("Darcy re smaller than rw", oil_darcy, 3000, 1000, 2000, 50, 20, 1.25, 0.8, 0.3, 0.5)
check_error("Fetkovich tests with same Pwf", oil_fetkovich, 3000, 1000, 500, 2000, 800, 2000)
check_error("Fetkovich: more rate at higher Pwf (n<0)", oil_fetkovich, 3000, 1000, 800, 2000, 500, 1000)
check_error("Back-pressure n above 1", gas_backpressure, 3000, 1000, 1e-4, 1.5)
check_error("Gas Z = 0", gas_darcy, 3000, 1000, 180, 5, 40, 0.02, 0.0, 1000, 0.4)

print("\n== Multilayer oil IPR ==")
# Two layers, Pb = 1500: layer 1  Pr 3000, J 2 ;  layer 2  Pr 2500, J 1
LAYERS = [{"p_res": 3000.0, "J": 2.0}, {"p_res": 2500.0, "J": 1.0}]
# Pwf = 2000 (above Pb, straight lines):  2 * (3000 - 2000) + 1 * (2500 - 2000) = 2000 + 500 = 2500
check("both layers above Pb: sum of the two straight lines", oil_multilayer(3000, 2000, 1500, LAYERS), 2500.0)
# Pwf = 2700 is above the pressure of layer 2: without crossflow only layer 1 produces: 2 * 300 = 600
check("layer 2 below the flowing pressure stops producing", oil_multilayer(3000, 2700, 1500, LAYERS), 600.0)
# with crossflow layer 2 takes fluid: 1 * (2500 - 2700) = -200  ->  600 - 200 = 400
check("with crossflow the layer takes fluid", oil_multilayer(3000, 2700, 1500, LAYERS, crossflow=True), 400.0)
# Pwf = 1000 (below Pb): each layer has its Vogel part.  fraction = 1 - 0.2 * (1000/1500) - 0.8 * (1000/1500)^2 = 0.51111
#   layer 1: 2 * 1500 + 2 * 1500 / 1.8 * 0.51111 = 3000 + 851.85 ;  layer 2: 1 * 1000 + 1500 / 1.8 * 0.51111 = 1000 + 425.93
check("below Pb: each layer follows the Vogel curve", oil_multilayer(3000, 1000, 1500, LAYERS), 3000 + 851.852 + 1000 + 425.926, 1e-5)
# AOF (Pwf = 0):  layer 1  3000 + 1666.67 ;  layer 2  1000 + 833.33  =  6500
check("AOF = sum of the layer AOFs", oil_multilayer(3000, 0, 1500, LAYERS), 6500.0)
check("one layer = the plain PI model", oil_multilayer(3000, 1200, 1500, [{"p_res": 3000.0, "J": 2.0}]), oil_pi(3000, 1200, 1500, 2.0), 1e-12)
check("no drawdown on any layer: no flow", oil_multilayer(3000, 3000, 1500, LAYERS), 0.0)
check_error("multilayer without layers", oil_multilayer, 3000, 1000, 1500, [])
check_error("layer with PI = 0", oil_multilayer, 3000, 1000, 1500, [{"p_res": 3000.0, "J": 0.0}])
check_error("layer with pressure = 0", oil_multilayer, 3000, 1000, 1500, [{"p_res": 0.0, "J": 1.0}])
pwf_list, q_list = ipr_curve(oil_multilayer, 3000, 31, pb=1500, layers=LAYERS)
ok = all(q_list[k] <= q_list[k + 1] for k in range(len(q_list) - 1))
print(f"  {'PASS' if ok else 'FAIL'}  multilayer curve rises as Pwf falls (also across the layer-2 kink at 2500 psia)")
assert ok


print("\n== OIL: Horizontal well, Kuchuk and Goode (SPE 21460) ==")
# Ki2(beta) against the paper's Table 1 (the printed value for beta = 0.5 reads 0.60637; the neighbours 0.57566 and
# 0.44637 and the curve itself show it must be 0.50637, so that is used here).
for beta, table in [(0.001, 0.99843), (0.01, 0.98460), (0.1, 0.86252), (0.5, 0.50637), (1.0, 0.27362),
                    (2.0, 0.085491), (5.0, 0.0031784), (10.0, 1.6336e-5)]:
    check(f"Ki2({beta}) = Table 1", bickley_ki2(beta), table, 2e-4)
# Fig. 2 of the paper: 4000 x 4000 ft box, h = 50, zw = 25, rw = 0.25, kH = 50 md, mu = 1 cp, Bo = 1, well centred.
# The expected values are the paper's simulator points read off the figure (+- 0.3 B/D/psi), so the tolerance is 5 %.
FIG2 = {1.0:  {0.0625: 6.8, 0.125: 10.2, 0.25: 17.8, 0.3125: 21.0, 0.375: 25.4, 0.5: 30.7},
        0.1:  {0.0625: 5.2, 0.125: 8.3,  0.25: 14.4, 0.3125: 18.1, 0.375: 21.6, 0.5: 25.8},
        0.01: {0.0625: 2.8, 0.125: 4.9,  0.25: 9.1,  0.3125: 11.4, 0.375: 13.6, 0.5: 17.0}}
for kv_over_kh, points in FIG2.items():
    for ratio, expected in points.items():
        J = horizontal_productivity_index_oil_kuchuk_goode(50, 50 * kv_over_kh, 50, 2 * ratio * 4000, 4000, 4000,
                                                           2000, 2000, 25, 0.25, 1.0, 1.0)
        check(f"Fig. 2: kv/kh {kv_over_kh}, L/2Lx {ratio}", J, expected, 0.05)
# the series are converged: the same well in a box twice as long (well still centred) gives the same pwD only when the
# box is big; instead check an exact limit: the well spans the whole box width in x -> the flow is 2D in y-z.
# Constant-pressure top, well 5 ft below it, isotropic: pwD -> (h/L) ln(2 d / rw)  (a cylinder near a constant-pressure plane)
p = horizontal_pwd_kuchuk_goode(50, 50, 50, 100, 4000, 4000, 1000, 2000, 2000, 95.0, 0.354, top="constant_pressure")
check("constant-pressure top, well 5 ft below it", p, (100.0 / 1000.0) * math.log(2 * 5.0 / 0.354), 0.01)
check("constant-pressure top gives a higher PI than a sealed top",
      float(horizontal_pwd_kuchuk_goode(50, 50, 50, 100, 4000, 4000, 1000, 2000, 2000, 50.0, 0.354, top="constant_pressure")
            < horizontal_pwd_kuchuk_goode(50, 50, 50, 100, 4000, 4000, 1000, 2000, 2000, 50.0, 0.354)), 1.0)
# Skin, hand check of Eq. 4: S*m = (h/L) * sqrt(kx/kz) * Sm.  h = 50, L = 1000, kx/kz = 4 -> 0.05 * 2 * 5 = 0.5
base = horizontal_productivity_index_oil_kuchuk_goode(50, 12.5, 50, 1000, 4000, 4000, 2000, 2000, 25, 0.354, 1.25, 0.8)
skinned = horizontal_productivity_index_oil_kuchuk_goode(50, 12.5, 50, 1000, 4000, 4000, 2000, 2000, 25, 0.354, 1.25, 0.8, skin=5.0)
pwd = horizontal_pwd_kuchuk_goode(50, 50, 12.5, 50, 4000, 4000, 1000, 2000, 2000, 25, 0.354)
check("skin 5 reduces J as pwD / (pwD + 0.5)", skinned / base, pwd / (pwd + 0.5), 1e-9)
# J by Eq. 3, by hand from pwD:  7.08e-3 -> 1/141.2;  kH = 50, h = 50, mu*Bo = 0.8 * 1.25 = 1
check("J from Eq. 3", base, 50.0 * 50.0 / (141.2 * 1.0 * pwd), 1e-9)
# symmetry: moving the well to the mirror position across the width gives the same PI
a = horizontal_pwd_kuchuk_goode(50, 50, 10, 50, 3000, 2000, 1000, 1500, 500, 20, 0.354)
b = horizontal_pwd_kuchuk_goode(50, 50, 10, 50, 3000, 2000, 1000, 1500, 1500, 20, 0.354)
check("mirror position across the width (y)", a, b, 1e-9)
c = horizontal_pwd_kuchuk_goode(50, 50, 10, 50, 3000, 2000, 1000, 800, 1000, 20, 0.354)
d = horizontal_pwd_kuchuk_goode(50, 50, 10, 50, 3000, 2000, 1000, 2200, 1000, 20, 0.354)
check("mirror position along the box (x)", c, d, 1e-9)
e = horizontal_pwd_kuchuk_goode(50, 50, 10, 50, 3000, 2000, 1000, 1500, 1000, 15, 0.354)
f = horizontal_pwd_kuchuk_goode(50, 50, 10, 50, 3000, 2000, 1000, 1500, 1000, 35, 0.354)
check("mirror position in the thickness (z)", e, f, 1e-9)
check("a longer well has a lower pwD", float(horizontal_pwd_kuchuk_goode(50, 50, 10, 50, 3000, 2000, 2000, 1500, 1000, 25, 0.354)
      < horizontal_pwd_kuchuk_goode(50, 50, 10, 50, 3000, 2000, 1000, 1500, 1000, 25, 0.354)), 1.0)
check("IPR: AOF = J * Pr above Pb everywhere", oil_horizontal_kuchuk_goode(3000, 0, 500, 50, 12.5, 50, 1000, 4000, 4000, 2000, 2000, 25, 0.354, 1.25, 0.8),
      oil_pi(3000, 0, 500, base) , 1e-9)
check_error("well sticks out of the box", horizontal_pwd_kuchuk_goode, 50, 50, 10, 50, 3000, 2000, 2500, 1000, 1000, 25, 0.354)
check_error("well above the top", horizontal_pwd_kuchuk_goode, 50, 50, 10, 50, 3000, 2000, 1000, 1500, 1000, 55, 0.354)
check_error("unknown top boundary", horizontal_pwd_kuchuk_goode, 50, 50, 10, 50, 3000, 2000, 1000, 1500, 1000, 25, 0.354, "open")
check_error("negative permeability", horizontal_productivity_index_oil_kuchuk_goode, -1, 10, 50, 1000, 3000, 2000, 1500, 1000, 25, 0.354, 1.25, 0.8)


# --- what the commingled layers produce: water cut and GOR of the well stream ---
# Pwf = 2000 psia, Pb = 1500: layer 1 gives 2000 STB/d, layer 2 gives 500 STB/d.
#   layer 1: water cut 0.2, GOR 400   -> water 400, oil 1600, gas 640,000 scf/d
#   layer 2: water cut 0.6, GOR 1000  -> water 300, oil  200, gas 200,000 scf/d
#   well stream: water cut = 700 / 2500 = 0.28 ;  GOR = 840,000 / 1800 = 466.667
WET = [{"p_res": 3000.0, "J": 2.0, "wc": 0.2, "gor": 400.0}, {"p_res": 2500.0, "J": 1.0, "wc": 0.6, "gor": 1000.0}]
m = multilayer_mix(3000, 2000, 1500, WET)
check("commingled water cut (hand calculation)", m["water_cut"], 0.28, 1e-12)
check("commingled GOR (hand calculation)", m["gor"], 840000.0 / 1800.0, 1e-9)
check("commingled mix: total rate = IPR rate", m["q"], 2500.0)
m2 = multilayer_mix(3000, 2700, 1500, WET)
check("only layer 1 produces above layer 2's pressure: water cut = layer 1's", m2["water_cut"], 0.2, 1e-12)
check("only layer 1 produces above layer 2's pressure: GOR = layer 1's", m2["gor"], 400.0, 1e-12)
check("a layer without its own water cut or GOR uses the defaults", multilayer_mix(3000, 2000, 1500, LAYERS, 0.4, 700.0)["water_cut"], 0.4, 1e-12)
check("flowing pressure for a given rate is the IPR turned round", multilayer_pwf(2500.0, 3000, 1500, WET), 2000.0, 1e-4)
check("rate above the AOF gives Pwf = 0", multilayer_pwf(1e6, 3000, 1500, WET), 0.0)
check("rate 0 gives the highest layer pressure", multilayer_pwf(0.0, 3000, 1500, WET), 3000.0)
check("round trip below Pb", oil_multilayer(3000, multilayer_pwf(4000.0, 3000, 1500, WET), 1500, WET), 4000.0, 1e-4)


# =====================================================================
print("\n== GAS: horizontal well (Joshi geometry), by hand ==")
# kh = 5 md, kv = 0.5 md, h = 40 ft, L = 2000 ft, re_h = 1500 ft, rw = 0.354 ft, skin 1, T = 200 F, mu = 0.02 cP, z = 0.9
#   half = L/2 = 1000 ;  a = 1000 * sqrt(0.5 + sqrt(0.25 + 1.5^4)) = 1000 * sqrt(0.5 + 2.3452) = 1686.8
#   plane 1 = ln[(1686.8 + sqrt(1686.8^2 - 1000^2)) / 1000] = ln[(1686.8 + 1358.1)/1000] = ln 3.0449 = 1.11332
#   Iani = sqrt(10) = 3.16228 ;  plane 2 = (3.16228*40/2000) * (ln[3.16228*40/(0.354*4.16228)] + 1)
#        = 0.063246 * (ln 85.84 + 1) = 0.063246 * 5.4524 = 0.34486
#   B = 1.45818 ;  a_coef = 1422 * 660 * 0.02 * 0.9 * B / (5 * 40) (the code below repeats this arithmetic)
T_, MU_, Z_ = 200.0, 0.02, 0.9
half = 1000.0
a_big = half * math.sqrt(0.5 + math.sqrt(0.25 + (1500.0 / half) ** 4))
plane1 = math.log((a_big + math.sqrt(a_big ** 2 - half ** 2)) / half)
iani = math.sqrt(10.0)
plane2 = (iani * 40.0 / 2000.0) * (math.log(iani * 40.0 / (0.354 * (iani + 1.0))) + 1.0)
a_hand = 1422.0 * (T_ + 460.0) * MU_ * Z_ * (plane1 + plane2) / (5.0 * 40.0)
check("horizontal gas: laminar coefficient a (hand)", gas_a_coefficient_horizontal_joshi(T_, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, MU_, Z_, 1.0), a_hand, 2e-3)
q_darcy = (3000.0 ** 2 - 1500.0 ** 2) / a_hand
check("horizontal gas: no turbulence (beta = 0) is pure Darcy", gas_horizontal_joshi(3000, 1500, T_, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, MU_, Z_, 0.65, 1.0, beta=0.0), q_darcy, 2e-3)
b_hand = 3.161e-12 * 1.0e8 * (T_ + 460.0) * 0.65 * Z_ / (2000.0 ** 2 * 0.354)       # beta = 1e8 1/ft, turbulence over the length L
dp2 = 3000.0 ** 2 - 1500.0 ** 2
q_hand = 2.0 * dp2 / (a_hand + math.sqrt(a_hand ** 2 + 4.0 * b_hand * dp2))
check("horizontal gas: with turbulence (hand)", gas_horizontal_joshi(3000, 1500, T_, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, MU_, Z_, 0.65, 1.0, beta=1.0e8), q_hand, 2e-3)
check("horizontal gas: rate at Pwf = Pr is 0", gas_horizontal_joshi(3000, 3000, T_, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, MU_, Z_, 0.65), 0.0)
q_short = gas_horizontal_joshi(3000, 1500, T_, 5.0, 0.5, 40.0, 1000.0, 1500.0, 0.354, MU_, Z_, 0.65, 0.0)
q_long = gas_horizontal_joshi(3000, 1500, T_, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, MU_, Z_, 0.65, 0.0)
check("horizontal gas: a longer well delivers more", float(q_long > q_short), 1.0)
q_vert = gas_darcy(3000, 1500, T_, 5.0, 40.0, MU_, Z_, 1000.0, 0.354, 0.0)
check("horizontal gas (2000 ft) beats the vertical well in the same layer", float(q_long > 2.0 * q_vert), 1.0)
check("horizontal gas: turbulence lowers the rate", float(gas_horizontal_joshi(3000, 500, T_, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, MU_, Z_, 0.65, 0.0, beta=1e10)
      < gas_horizontal_joshi(3000, 500, T_, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, MU_, Z_, 0.65, 0.0, beta=0.0)), 1.0)
check("horizontal gas: b falls with length squared (L doubled -> b/4)",
      gas_b_coefficient(T_, 5.0, 4000.0, Z_, 0.65, 0.354, 1e8) * 4.0, gas_b_coefficient(T_, 5.0, 2000.0, Z_, 0.65, 0.354, 1e8), 1e-12)
# the same geometry as the oil model:  a = 1422 T mu z / (141.2 * J(Bo = 1, mu = 1))
j_oil = horizontal_productivity_index_oil_joshi(5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, 1.0, 1.0, 1.0)
check("horizontal gas a is the oil geometry in gas units", gas_a_coefficient_horizontal_joshi(T_, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, MU_, Z_, 1.0),
      1422.0 * (T_ + 460.0) * MU_ * Z_ / (141.2 * j_oil), 1e-12)
check_error("gas horizontal: drainage radius too small", gas_horizontal_joshi, 3000, 1500, T_, 5.0, 0.5, 40.0, 2000.0, 900.0, 0.354, MU_, Z_, 0.65)
check_error("gas horizontal: negative Pwf", gas_horizontal_joshi, 3000, -1, T_, 5.0, 0.5, 40.0, 2000.0, 1500.0, 0.354, MU_, Z_, 0.65)

print("\n== GAS: horizontal well in a box (Kuchuk and Goode geometry) ==")
kg_args = (5.0, 0.5, 40.0, 2000.0, 4000.0, 3000.0, 2000.0, 1500.0, 20.0, 0.354)
j_kg = horizontal_productivity_index_oil_kuchuk_goode(*kg_args, 1.0, 1.0, 1.0)
a_kg = 1422.0 * (T_ + 460.0) * MU_ * Z_ / (141.2 * j_kg)
check("KG gas: laminar coefficient a (oil geometry in gas units)", gas_a_coefficient_horizontal_kuchuk_goode(T_, *kg_args[:], MU_, Z_, 1.0), a_kg, 1e-12)
check("KG gas: no turbulence is pure Darcy", gas_horizontal_kuchuk_goode(3000, 1500, T_, *kg_args, MU_, Z_, 0.65, 1.0, beta=0.0), dp2 / a_kg, 1e-9)
check("KG gas: rate at Pwf = Pr is 0", gas_horizontal_kuchuk_goode(3000, 3000, T_, *kg_args, MU_, Z_, 0.65), 0.0)
check("KG gas: constant-pressure top delivers more than a sealed top",
      float(gas_horizontal_kuchuk_goode(3000, 1500, T_, *kg_args, MU_, Z_, 0.65, 0.0, 1.0, "constant_pressure", 0.0)
            > gas_horizontal_kuchuk_goode(3000, 1500, T_, *kg_args, MU_, Z_, 0.65, 0.0, 1.0, "sealed", 0.0)), 1.0)
check_error("KG gas: well sticks out of the box", gas_horizontal_kuchuk_goode, 3000, 1500, T_, 5.0, 0.5, 40.0, 5000.0, 4000.0, 3000.0, 2000.0, 1500.0, 20.0, 0.354, MU_, Z_, 0.65)

print("\n== GAS: multilayer (commingled layers), by hand ==")
# Layer 1: Pr = 3000, a = 100, b = 0.002  -> Pwf = 2000:  dp2 = 9e6 - 4e6 = 5e6
#   b q^2 + a q = 5e6 :  q = (-100 + sqrt(100^2 + 4*0.002*5e6)) / (2*0.002) = (-100 + sqrt(50000)) / 0.004 = (-100 + 223.607)/0.004 = 30901.7
# Layer 2: back-pressure, Pr = 2500, C = 0.01, n = 0.8 -> dp2 = 6.25e6 - 4e6 = 2.25e6 ;  q = 0.01 * (2.25e6)^0.8 = 0.01 * 10^(0.8*6.352183) = 0.01 * 10^5.081747 = 1207.0
GL = [{"p_res": 3000.0, "a": 100.0, "b": 0.002, "cgr": 10.0, "wgr": 2.0},
      {"p_res": 2500.0, "C": 0.01, "n": 0.8, "cgr": 50.0, "wgr": 0.0}]
q1 = (-100.0 + math.sqrt(100.0 ** 2 + 4 * 0.002 * 5.0e6)) / (2 * 0.002)
q2 = 0.01 * (2.25e6) ** 0.8
check("layer 1 alone (Jones form, hand)", gas_multilayer(3000, 2000, GL[:1]), q1, 1e-9)
check("layer 2 alone (back-pressure form, hand)", gas_multilayer(3000, 2000, GL[1:]), q2, 1e-9)
check("two layers: the rates add", gas_multilayer(3000, 2000, GL), q1 + q2, 1e-9)
check("rates are returned layer by layer", gas_multilayer_rates(3000, 2000, GL)[1], q2, 1e-9)
check("layer 2 below the flowing pressure stops producing", gas_multilayer(3000, 2700, GL), (-100.0 + math.sqrt(100.0 ** 2 + 4 * 0.002 * (9.0e6 - 2700.0 ** 2))) / 0.004, 1e-9)
cross = -0.01 * (2700.0 ** 2 - 2500.0 ** 2) ** 0.8
check("crossflow: the back-pressure layer takes gas from the well (hand)", gas_multilayer_rates(3000, 2700, GL, crossflow=True)[1], cross, 1e-9)
GD = [{"p_res": 3000.0, "a": 100.0, "b": 0.0}, {"p_res": 2500.0, "a": 200.0, "b": 0.0}]
check("crossflow, Darcy layer: -(Pwf^2 - Pr^2)/a (hand)", gas_multilayer_rates(3000, 2700, GD, crossflow=True)[1], -(2700.0 ** 2 - 2500.0 ** 2) / 200.0, 1e-9)
check("AOF = sum of the layer AOFs", gas_multilayer(3000, 0, GD), 9.0e6 / 100.0 + 6.25e6 / 200.0, 1e-9)
check("one layer equals the single-layer Darcy model", gas_multilayer(3000, 1200, GD[:1]), (3000.0 ** 2 - 1200.0 ** 2) / 100.0, 1e-9)

# --- what the commingled gas layers produce: CGR and WGR ---
# At Pwf = 2000: layer 1 gives q1 with CGR 10 and WGR 2 ; layer 2 gives q2 with CGR 50 and WGR 0
#   CGR = (10 q1 + 50 q2) / (q1 + q2) ;  WGR = (2 q1) / (q1 + q2)
mix = gas_multilayer_mix(3000, 2000, GL)
check("commingled CGR (hand calculation)", mix["cgr"], (10.0 * q1 + 50.0 * q2) / (q1 + q2), 1e-9)
check("commingled WGR (hand calculation)", mix["wgr"], 2.0 * q1 / (q1 + q2), 1e-9)
check("commingled mix: total = IPR rate", mix["q"], q1 + q2, 1e-9)
only1 = gas_multilayer_mix(3000, 2700, GL)
check("only layer 1 produces above layer 2's pressure: CGR = layer 1's", only1["cgr"], 10.0, 1e-9)
check("a layer without its own CGR uses the default", gas_multilayer_mix(3000, 2000, GD, default_cgr=30.0)["cgr"], 30.0, 1e-12)
check("flowing pressure for a given rate is the IPR turned round", gas_multilayer_pwf(q1 + q2, 3000, GL), 2000.0, 1e-5)
check("round trip", gas_multilayer(3000, gas_multilayer_pwf(20000.0, 3000, GL), GL), 20000.0, 1e-6)
check("rate above the AOF gives Pwf = 0", gas_multilayer_pwf(1e12, 3000, GL), 0.0)
check("rate 0 gives the highest layer pressure", gas_multilayer_pwf(0.0, 3000, GL), 3000.0)
check_error("gas multilayer: no layers", gas_multilayer, 3000, 2000, [])
check_error("gas multilayer: layer with a = 0", gas_multilayer, 3000, 2000, [{"p_res": 3000.0, "a": 0.0, "b": 0.0}])
check_error("gas multilayer: n above 1", gas_multilayer, 3000, 2000, [{"p_res": 3000.0, "C": 0.01, "n": 1.2}])

print("\nAll checks passed.")
