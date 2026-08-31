#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YAKALAMA ANALİZİ — drone hedefi yakalayabilir mi, nereye gider?

⛔ NİYE VAR: ilk otonom uçuştan ÖNCE şunu bilmek istiyoruz — güdüm
   dronu nereye götürür, hedefe kapanır mı, yoksa saçma bir yere mi
   gider? Uçuşta öğrenmek pahalı.

⭐ GÜDÜM GERÇEK KODDUR. `dow.gudum.gps.komut` ve `HizCubukCevirici`
   birebir uçuşta çalışan kodun aynısıdır. Uydurulan tek şey ARAÇ
   FİZİĞİdir (aşağıda açıkça yazılı) — çünkü onu henüz ölçmedik.

--------------------------------------------------------------------------------
ARAÇ MODELİ — VARSAYIM, ÖLÇÜM DEĞİL
--------------------------------------------------------------------------------
  Angle modunda çubuk bir YATIŞ AÇISI komutudur:
        θ = çubuk × ACI_MAX          (ACI_MAX = 60°)
  Yatan bir multikopterin yatay ivmesi:
        a = g · tan(θ)               60°'de 17.0 m/s²
  Sürükleme hızın karesiyle artar:
        a_sürükleme = −k·|v|·v       k, azami hızdan çözülür
  Azami hız (tam yatışta sürüklemenin ivmeyi yediği hız) BİLİNMİYOR;
  bu yüzden birkaç değerde ayrı ayrı koşulur.

⛔ EN KRİTİK SORU: aracın azami hızı hedefin hızından BÜYÜK olmalı.
   Değilse arkadan kovalayarak ASLA yetişemez — bu bir güdüm sorunu
   değil, FİZİK sorunudur.
--------------------------------------------------------------------------------
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dow.ayarlar import Ayar                                  # noqa: E402
from dow.gudum import gps as GPS                              # noqa: E402
from dow.gudum.cevirici import HizCubukCevirici, CevCfg       # noqa: E402

G = 9.81


class Arac:
    """Multikopter — Angle modu fiziği. VARSAYIMSAL MODEL."""

    def __init__(self, p, hiz_max, aci_max_deg):
        self.p = list(p)                    # kuzey, doğu, yukarı (m)
        self.v = [0.0, 0.0, 0.0]
        self.yaw = 0.0                      # derece
        self.aci_max = math.radians(aci_max_deg)
        a_max = G * math.tan(self.aci_max)
        self.k = a_max / (hiz_max ** 2)     # sürükleme katsayısı
        self.a_max = a_max
        self.doyum_tik = 0

    def adim(self, thr, pitch, roll, yaw_cubuk, dt):
        # çubuk -> gövde eğim açısı
        if abs(pitch) >= 0.999 or abs(roll) >= 0.999:
            self.doyum_tik += 1
        th_ileri = max(-1.0, min(1.0, pitch)) * self.aci_max
        th_sag = max(-1.0, min(1.0, roll)) * self.aci_max
        a_ileri = G * math.tan(th_ileri)
        a_sag = G * math.tan(th_sag)
        # gövde -> dünya
        y = math.radians(self.yaw)
        ax = a_ileri * math.cos(y) - a_sag * math.sin(y)
        ay = a_ileri * math.sin(y) + a_sag * math.cos(y)
        # sürükleme
        hiz = math.hypot(self.v[0], self.v[1])
        if hiz > 0.01:
            ax -= self.k * hiz * self.v[0]
            ay -= self.k * hiz * self.v[1]
        # dikey: throttle -> tırmanma hızı (kaba)
        vz_hedef = max(-1.0, min(1.0, thr)) * 6.0
        self.v[2] += (vz_hedef - self.v[2]) * min(1.0, dt / 0.8)
        self.v[0] += ax * dt
        self.v[1] += ay * dt
        for i in range(3):
            self.p[i] += self.v[i] * dt
        # yaw: komut derece/s
        self.yaw = (self.yaw + yaw_cubuk * 180.0 * dt) % 360.0


class Hedef:
    def __init__(self, p, hiz, mod, yaricap=250.0):
        self.p = list(p); self.V = hiz; self.mod = mod; self.R = yaricap
        self.yon = 0.0
        self.t = 0.0

    def adim(self, dt):
        self.t += dt
        if self.mod == "daire":
            w = self.V / self.R
            self.yon = math.degrees(w * self.t) % 360.0
        r = math.radians(self.yon)
        v = (self.V * math.cos(r), self.V * math.sin(r), 0.0)
        for i in range(3):
            self.p[i] += v[i] * dt
        return v


def kosu(hiz_max, hedef_hiz, mod, baslangic_geri, sure=90.0, dt=0.02,
         yazdir=False):
    cev = HizCubukCevirici()
    # drone hedefin `baslangic_geri` metre ARKASINDA, aynı irtifada
    hedef = Hedef([0.0, 0.0, 80.0], hedef_hiz, mod)
    arac = Arac([-baslangic_geri, 0.0, 80.0], hiz_max, CevCfg.MAX_YATIS_DEG)
    arac.yaw = 0.0

    en_yakin = 9e9; en_yakin_t = 0.0; t = 0.0
    kapandi_mi = False
    iz = []
    n = int(sure / dt)
    for i in range(n):
        hv = hedef.adim(dt)
        v_dunya, vz_ned, yaw_rate, tani = GPS.komut(
            tuple(arac.p), arac.yaw, tuple(hedef.p), hv, hedef.yon)
        thr, pitch, roll, yaw_c = cev.cevir(
            (v_dunya[0], v_dunya[1], vz_ned),
            (arac.v[0], arac.v[1], arac.v[2]),
            math.radians(arac.yaw), yaw_rate)
        arac.adim(thr, pitch, roll, yaw_c, dt)
        t += dt
        d = math.dist(arac.p[:2], hedef.p[:2])
        if d < en_yakin:
            en_yakin, en_yakin_t = d, t
        if d < 10.0:
            kapandi_mi = True
        if yazdir and i % int(5.0 / dt) == 0:
            iz.append((t, d, math.hypot(arac.v[0], arac.v[1]),
                       arac.yaw, pitch, roll))
    return {"en_yakin": en_yakin, "en_yakin_t": en_yakin_t,
            "son_mesafe": d, "kapandi": kapandi_mi,
            "son_hiz": math.hypot(arac.v[0], arac.v[1]),
            "doyum_oran": 100.0 * arac.doyum_tik / n, "iz": iz}


def main():
    a = argparse.ArgumentParser(description="Yakalama analizi")
    a.add_argument("--sure", type=float, default=90.0)
    a.add_argument("--geri", type=float, default=200.0,
                   help="drone hedefin kaç m arkasından başlıyor")
    a = a.parse_args()

    print("=" * 74)
    print("  YAKALAMA ANALİZİ — güdüm GERÇEK KOD, araç fiziği VARSAYIM")
    print("=" * 74)
    print("  ACI_MAX %g°  ->  azami yatay ivme %.1f m/s²"
          % (CevCfg.MAX_YATIS_DEG, G * math.tan(math.radians(CevCfg.MAX_YATIS_DEG))))
    print("  İSTASYON: hedefin %g m arkası, %g×menzil altı"
          % (Ayar.ISTASYON_MENZIL_M, Ayar.ISTASYON_ALT_ORAN))
    print("  Başlangıç: drone hedefin %g m arkasında, %g s koşu"
          % (a.geri, a.sure))
    print()

    print("  [1] DÜZ UÇAN HEDEF — arkadan kovalama")
    print("      drone_max  hedef_hiz    en yakın    ne zaman   son hız  doyum")
    print("      " + "-" * 62)
    for hmax in (25.0, 30.0, 35.0, 40.0):
        for hh in (18.0, 22.0, 25.0):
            r = kosu(hmax, hh, "duz", a.geri, a.sure)
            damga = "✔ YAKALADI" if r["en_yakin"] < 15 else (
                "~ yaklaştı" if r["en_yakin"] < 60 else "⛔ YETİŞEMEDİ")
            print("      %5.0f m/s  %5.0f m/s   %7.1f m   %6.1f s   %5.1f   %%%2.0f  %s"
                  % (hmax, hh, r["en_yakin"], r["en_yakin_t"], r["son_hiz"],
                     r["doyum_oran"], damga))
        print()

    print("  [2] DAİRE ÇİZEN HEDEF (250 m yarıçap) — köşe kesilebilir")
    print("      drone_max  hedef_hiz    en yakın    ne zaman   son hız")
    print("      " + "-" * 62)
    for hmax in (25.0, 30.0, 35.0):
        for hh in (20.0, 25.0):
            r = kosu(hmax, hh, "daire", a.geri, a.sure)
            damga = "✔ YAKALADI" if r["en_yakin"] < 15 else (
                "~ yaklaştı" if r["en_yakin"] < 60 else "⛔ YETİŞEMEDİ")
            print("      %5.0f m/s  %5.0f m/s   %7.1f m   %6.1f s   %5.1f   %s"
                  % (hmax, hh, r["en_yakin"], r["en_yakin_t"], r["son_hiz"], damga))
        print()

    print("  [3] YAKINDAN İZ — drone 30 m/s, hedef 22 m/s, düz")
    r = kosu(30.0, 22.0, "duz", a.geri, a.sure, yazdir=True)
    print("        sn   mesafe   drone hızı   burun    pitch    roll")
    print("      " + "-" * 58)
    for t, d, v, yaw, p, rl in r["iz"]:
        print("      %4.0f  %7.1f m   %6.1f m/s  %6.1f°  %+6.2f  %+6.2f"
              % (t, d, v, yaw, p, rl))
    print()
    print("=" * 74)


if __name__ == "__main__":
    main()
