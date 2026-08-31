#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ÇUBUK İZLE — hedef kımıldadıkça güdümün ne komut verdiğini CANLI göster

⛔ NİYE VAR: "hedefin konumu değişince çubuklar doğru yöne gidiyor mu"
   sorusunun gözle görülür cevabı. `yon_testi.py` 90 saniye toplayıp
   istatistik verir; bu araç ise HER SANİYE tek satır basar ve o anda
   doğru mu yanlış mı söyler.

⭐ OTONOM'A BASMAYA GEREK YOK. Panel `oto_cubuk` alanında güdümün
   İSTEDİĞİ çubukları yayınlıyor — gönderilmiş olsun ya da olmasın.
   Yani aracı güdüme TESLİM ETMEDEN ne yapmak istediğini izleyebilirsin.
   En güvenli teşhis budur.

--------------------------------------------------------------------------------
NASIL OKUNUR
--------------------------------------------------------------------------------
  HEDEF sütunu : hedefin, aracın BURNUNA göre yönü
                   0° = tam önde · +90° = sağda · 180° = arkada · -90° = solda
  ÇUBUK sütunu : güdümün istediği yön   atan2(roll, pitch)
                   +pitch = ileri · +roll = sağ
  FARK         : ikisi arasındaki açı. Küçükse güdüm hedefe dönüktür.

  ⚠ ~8 m'lik İSTASYON OFSETİ: güdüm hedefin KENDİSİNE değil, ~8 m
    ARKASINDAKİ noktaya gider. Hedef yakınken bu açıyı bozar; 30 m'nin
    ötesinde etkisi 15°'nin altındadır. O yüzden UZAK TUT.

Kullanım:
    python3 gercek/cubuk_izle.py
    python3 gercek/cubuk_izle.py --sure 300      # 5 dakika izle
"""
import argparse
import json
import math
import sys
import time
import urllib.request

PANEL = "http://127.0.0.1:8810/api/durum"
#: Bu mesafenin altında ölçüm GEÇERSİZ sayılır (istasyon ofseti, bkz. aşağı).
GECERLI_MIN_M = 25.0
#: Bunun altında sonuç raporlanır ama "ofset payı" uyarısıyla.
RAHAT_M = 30.0
A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)


def _al(url):
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.load(r)


def _fark(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def _ok(aci):
    """Açıyı okunur bir yön adına çevir."""
    if aci is None:
        return "?"
    a = abs(aci)
    if a <= 30:
        return "ILERI"
    if a >= 150:
        return "GERI"
    if aci > 0:
        return "SAG" if a >= 60 else "SAG-ONDE"
    return "SOL" if a >= 60 else "SOL-ONDE"


def main():
    ap = argparse.ArgumentParser(description="Çubukları canlı izle")
    ap.add_argument("--sure", type=float, default=180.0)
    ap.add_argument("--panel", default=PANEL)
    ap.add_argument("--aralik", type=float, default=1.0)
    a = ap.parse_args()

    print("=" * 78)
    print("  ÇUBUK İZLE — hedef kımıldadıkça güdümün istediği yön")
    print("=" * 78)
    print("  ⛔ PERVANESİZ · DISARM. OTONOM'a basmana gerek YOK.")
    print("  ⛔ HEDEFİ EN AZ %.0f METRE UZAKTA TUT (tercihen %.0f m)."
          % (GECERLI_MIN_M, RAHAT_M))
    print("     Güdüm hedefin 8 m ARKASINA gider; yakında bu ofset açıyı bozar")
    print("     ve araç sahte 'TERS' damgası basar.")
    print("  ⛔ Taşıyan kişi DÜZ ve DÜZGÜN yürüsün — hedefin yönü yürüme")
    print("     yönünden hesaplanıyor; her dönüşte istasyon noktası savrulur.")
    print()
    print("   sn  mesafe  HEDEF nerede        ÇUBUK ne diyor       fark   ")
    print("  " + "-" * 72)

    t0 = time.time()
    iyi = kotu = atlanan = 0
    while time.time() - t0 < a.sure:
        try:
            d = _al(a.panel)
        except Exception as e:
            print("  ⛔ panele ulaşılamıyor: %s" % e)
            time.sleep(1.0)
            continue

        oto = d.get("oto_cubuk")
        hk = d.get("hedef_ham_konum")
        ko = d.get("konum") or {}
        du = d.get("durus") or {}
        hd = d.get("hedef") or {}
        yaw = du.get("yaw")

        if not hd.get("var"):
            print("  %4.0f  ⛔ hedef YOK / BAYAT (yaş %s s)"
                  % (time.time() - t0, hd.get("yas")))
            atlanan += 1
            time.sleep(a.aralik)
            continue
        if hk is None:
            print("  %4.0f  ⛔ köken kurulmadı — panelde KÖKEN KUR'a bas"
                  % (time.time() - t0))
            atlanan += 1
            time.sleep(a.aralik)
            continue
        if oto is None or yaw is None:
            print("  %4.0f  ⛔ güdüm çubuk üretmiyor (görsel güdüm açık mı?)"
                  % (time.time() - t0))
            atlanan += 1
            time.sleep(a.aralik)
            continue

        dn = hk["kuzey"] - (ko.get("kuzey") or 0.0)
        de = hk["dogu"] - (ko.get("dogu") or 0.0)
        mesafe = math.hypot(dn, de)
        # ⛔⛔ MESAFE KAPISI — İSTASYON OFSETİ YÜZÜNDEN ZORUNLU.
        #   Güdüm hedefin KENDİSİNE değil, 8 m ARKASINDAKİ istasyon
        #   noktasına gider (`ISTASYON_MENZIL_M = 8.0`). Yakında bu iki
        #   yön TAMAMEN AYRIŞIR:
        #     hedef 5 m ileride, doğuya bakıyor -> istasyon 3 m GERİDE
        #   Böyle bir koşuda araç "TERS" damgası basar ve operatör
        #   olmayan bir arızayı kovalar. YAŞANDI (2026-08-31).
        #   Açısal bozulma ~ atan(8/R):  R=15 m -> 28°   R=30 m -> 15°
        if mesafe < GECERLI_MIN_M:
            print("  %4.0f  ⛔ GEÇERSİZ — hedef %.1f m (en az %.0f m gerekir)."
                  "  İstasyon ofseti (8 m) açıyı bozuyor."
                  % (time.time() - t0, mesafe, GECERLI_MIN_M))
            atlanan += 1
            time.sleep(a.aralik)
            continue

        kerteriz = math.degrees(math.atan2(de, dn))
        hedef_govde = _fark(kerteriz, yaw)              # burna göre hedef
        p, r = oto["pitch"], oto["roll"]
        buyukluk = math.hypot(p, r)
        if buyukluk < 0.05:
            print("  %4.0f  %5.1f m  %-8s %+6.1f°   çubuk ÇOK KÜÇÜK (%.2f)"
                  % (time.time() - t0, mesafe, _ok(hedef_govde),
                     hedef_govde, buyukluk))
            atlanan += 1
            time.sleep(a.aralik)
            continue

        cubuk_govde = math.degrees(math.atan2(r, p))
        f = _fark(cubuk_govde, hedef_govde)
        if abs(f) <= 45:
            damga = "✔"; iyi += 1
        elif abs(f) >= 135:
            damga = "⛔ TERS"; kotu += 1
        else:
            damga = "⚠"; kotu += 1
        doy = "  DOYUM" if (abs(p) >= 0.99 or abs(r) >= 0.99) else ""
        if mesafe < RAHAT_M:
            doy += "  (ofset payı ±%.0f°)" % math.degrees(math.atan(8.0 / mesafe))
        print("  %4.0f  %5.1f m  %-9s %+6.1f°   %-9s %+6.1f°  %+6.1f° %s%s"
              % (time.time() - t0, mesafe, _ok(hedef_govde), hedef_govde,
                 _ok(cubuk_govde), cubuk_govde, f, damga, doy))
        time.sleep(a.aralik)

    print()
    print("=" * 78)
    n = iyi + kotu
    if n == 0:
        print("  ⛔ DEĞERLENDİRİLECEK ÖRNEK YOK (%d atlandı)." % atlanan)
        return 1
    print("  uyumlu %d  ·  uyumsuz %d  ·  atlanan %d   ->  %%%.0f uyum"
          % (iyi, kotu, atlanan, 100.0 * iyi / n))
    if iyi >= n * 0.8:
        print("  ✔ ÇUBUKLAR HEDEFE DOĞRU — güdüm hatayı kapatıyor.")
    elif kotu >= n * 0.8:
        print("  ⛔ ÇUBUKLAR TERS — uçurma.")
        print("     DOW_CEV_Y_ISARET=-1.0 ./baslat_drone.sh --gorsel")
    else:
        print("  ⚠ KARIŞIK — hedefi uzaklaştırıp tekrarla (istasyon ofseti).")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
