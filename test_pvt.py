"""Quick checks for pvt.py. Run:  python test_pvt.py"""
from pvt import *

API, GG, RSB, T = 35.0, 0.75, 500.0, 200.0

print("== Oil: Pb from Rsb, then Rs(Pb) should return ~Rsb ==")
for m in ("glaso", "standing", "lasater", "petrosky"):
    pb = PB_FUNCS[m](RSB, GG, API, T)
    rs_back = RS_FUNCS[m](pb, GG, API, T)
    bob = BO_FUNCS[m](RSB, GG, API, T)
    print(f"{m:9s} Pb={pb:7.0f} psia  Rs(Pb)={rs_back:6.1f}  Bob={bob:.3f}")
    assert abs(rs_back - RSB) / RSB < 0.03, m

print("\n== Oil profile (Glaso + Beal) ==")
for p in (500, 1500, 2500, 3500, 5000):
    o = oil_properties(p, T, API, GG, RSB)
    print(f"p={p:5d}  Rs={o['rs']:6.1f}  Bo={o['bo']:.3f}  mu={o['mu_o']:.3f} cP  rho={o['rho_o']:.1f}")

print("\n== Oil: Pb matching (measured 2000 psia) ==")
o = oil_properties(2000, T, API, GG, RSB, pb_meas=2000)
print(f"at Pb: Rs={o['rs']:.1f} (should equal {RSB})")
assert abs(o["rs"] - RSB) < 1.0

print("\n== Viscosity methods at 1500 psia ==")
for v in ("beal", "beggs"):
    print(v, round(oil_properties(1500, T, API, GG, RSB, visc_method=v)["mu_o"], 3))

print("\n== Gas (SG 0.70, 200F) ==")
for p in (500, 1500, 3000, 5000):
    gl = gas_properties(p, T, 0.70)
    gc = gas_properties(p, T, 0.70, visc_method="carr")
    print(f"p={p:5d}  Z={gl['z']:.3f}  Bg={gl['bg']:.5f}  rho={gl['rho_g']:.2f}  "
          f"mu(Lee)={gl['mu_g']:.4f}  mu(Carr)={gc['mu_g']:.4f}")

print("\n== Wet gas gravity (sep gas 0.70, CGR 50 STB/MMscf, 50 API) ==")
print(round(wet_gas_gravity(0.70, 50, 50), 3))

print("\n== Water (3% salinity, 200F) ==")
for p in (1000, 3000):
    w = water_properties(p, T, 3.0)
    print(f"p={p}  Bw={w['bw']:.4f}  rho={w['rho_w']:.2f}  mu={w['mu_w']:.3f}")
print("\n== Bubble point is never below atmospheric (bug found 20 Nov 2026) ==")
# Petrosky and Farshad were fitted on Rs from about 200 to 1,900 scf/STB.  Below roughly
# 100 scf/STB their equation goes negative, and a negative Pb used to make the Vasquez-Beggs
# undersaturated viscosity return a COMPLEX number, silently, which then poisoned the density
# and the VLP.  oil_properties() now holds the calculated bubble point at atmospheric or above.
import pvt as _pvt
assert _pvt.pb_petrosky(30.0, 0.75, 21.0, 263.0) < 0.0, "the raw correlation should still be negative here"
_bad = 0
for _api in range(10, 56, 2):
    for _gg in (0.55, 0.65, 0.8, 1.0, 1.2):
        for _T in range(90, 300, 20):
            for _rsb in (5, 10, 20, 30, 50, 80, 200, 900):
                for _m in ("glaso", "standing", "lasater", "petrosky"):
                    for _v in ("beal", "beggs", "petrosky"):
                        _o = oil_properties(2000.0, _T, _api, _gg, _rsb, pvt_method=_m, visc_method=_v)
                        for _k, _val in _o.items():
                            if _val is None:
                                continue
                            if isinstance(_val, complex) or _val != _val:     # complex or NaN
                                _bad += 1
                        assert _o["pb"] >= _pvt.ATM_PSIA, f"Pb below atmospheric: {_m} {_rsb} -> {_o['pb']}"
assert _bad == 0, f"{_bad} properties came back complex or NaN"
print(f"every property is a real number over {24 * 5 * 11 * 8 * 4 * 3:,} oil cases, and Pb >= {_pvt.ATM_PSIA} psia")

print("\nAll checks passed.")
