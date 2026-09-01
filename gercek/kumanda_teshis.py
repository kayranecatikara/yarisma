#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
KUMANDA TEŞHİSİ — hangi eksen ne, ve otonomu kim kesiyor
================================================================================

⛔ NİYE VAR (2026-09-01'de yaşandı)
   Sahada panelde OTONOM'a basılıyor, hakem otonomu bir tik verip hemen
   düşürüyordu:  `kaynak=MANUEL  sebep=pilot_devraldi`.
   Sebep: `komut.py` kumandanın DÖRT analog ekseninden herhangi biri
   `KMD_HAREKET_ESIK` (varsayılan 0.04) kadar oynarsa "pilot çubuğa
   dokundu" sayar ve otonomu MANDALLI olarak keser — kendiliğinden
   geri gelmez. Canlı okuduğumuzda gaz ekseni `0.0 → −0.15 → −1.00`
   diye zıplıyordu. Bu ya gerçek bir titreşim, ya yanlış eksen eşlemesi,
   ya da YANLIŞ CİHAZ okumaktı. Üçünü ayırmadan uçulmaz.

⛔ NE YAPMAZ
   Araca HİÇBİR ŞEY göndermez. Yalnız oyun kolunu okur. Pervane takılı
   olsun ya da olmasın güvenlidir; araç bağlı olmasa bile çalışır.

────────────────────────────────────────────────────────────────────────
TERİMLER (CLAUDE.md §0.2 — hiçbiri tanımsız bırakılmaz)
────────────────────────────────────────────────────────────────────────
  HAM EKSEN   : işletim sisteminin verdiği ham sayı, [-1, +1]. Kumandanın
                hangi çubuğunun hangi numaraya düştüğü ÜRETİCİYE ve
                EdgeTX kanal sırasına bağlıdır — tahmin edilmez, ÖLÇÜLÜR.
  EŞLEME      : "ham eksen 2 = gaz" gibi bir atama. Bizde `DOW_KMD_EKS_*`
                env değişkenleriyle verilir.
  ÖLÜ BANT    : çubuk tam ortada durmasa da 0 sayılan aralık
                (`DOW_KMD_OLU_BANT`, varsayılan 0.02). Ekseni okurken
                UYGULANIR; yani 0.02'nin altındaki titreşim zaten silinir.
  HAREKET EŞİĞİ: iki ardışık okuma arasındaki fark bunu aşarsa "pilot
                çubuğu oynattı" sayılır (`DOW_KMT_KMD_ESIK`, 0.04).
                ⚠ ÖLÜ BANTTAN BÜYÜKTÜR: 0.02–0.04 arası titreşim
                sessizce yutulur, 0.04 üstü otonomu KESER.
  MANDAL      : bir kez tetiklenince kendiliğinden dönmeyen kilit.
                Devralma mandallıdır; yalnız panelde OTONOM'a basmak siler.

────────────────────────────────────────────────────────────────────────
ÜÇ AŞAMA
────────────────────────────────────────────────────────────────────────
 0) CİHAZ  — sistemdeki bütün oyun kolları listelenir ve `Kumanda`nın
             HANGİSİNİ seçeceği gösterilir. (`Kumanda.ac()` sıralı ilk
             `/dev/input/js*` cihazını alır; ortamda başka bir HID cihazı
             varsa YANLIŞ cihaz okunuyor olabilir.)
 1) DURGUNLUK — 10 saniye HİÇBİR ŞEYE DOKUNMA. Her eksenin tepe-tepe
             gezinmesi ölçülür ve hareket eşiğiyle kıyaslanır. Ayrıca
             `komut.py`'nin devralma dedektörü BİREBİR taklit edilir:
             "bu 10 saniyede otonom kaç kez kesilirdi?"
 2) EKSEN BULMA — sırayla tek tek çubuk oynatılır, hangi ham eksenin
             kıpırdadığı ölçülür ve mevcut eşlemeyle KIYASLANIR.
 3) CANLI  — ham eksenler + güdümün gördüğü değerler, sürekli.

Kullanım:
    python3 gercek/kumanda_teshis.py
    python3 gercek/kumanda_teshis.py --durgunluk 20     # daha uzun ölçüm
    python3 gercek/kumanda_teshis.py --asama canli      # doğrudan canlı
================================================================================
"""
import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gercek.kumanda import Kumanda, KumandaCfg, _JsOkuyucu   # noqa: E402
from gercek.komut import KomutCfg                            # noqa: E402

ADLAR = ("roll", "pitch", "throttle", "yaw", "arm", "kip")


def _eşleme():
    c = KumandaCfg
    return [("roll", c.EKSEN_ROLL), ("pitch", c.EKSEN_PITCH),
            ("throttle", c.EKSEN_THROTTLE), ("yaw", c.EKSEN_YAW),
            ("arm", c.EKSEN_ARM), ("kip", c.EKSEN_KIP)]


# ---------------------------------------------------------------- 0
def asama_cihaz():
    print("=" * 74)
    print("  0) CİHAZLAR")
    print("=" * 74)
    yollar = sorted(glob.glob("/dev/input/js*"))
    if not yollar:
        print("  ⛔ /dev/input/js* YOK.")
        print("     · Kumanda açık mı?")
        print("     · EdgeTX: SYS → Hardware → USB Mode = Joystick")
        print("     · Kabloyu çıkarıp tak, sonra tekrar çalıştır.")
        return None
    for i, y in enumerate(yollar):
        o = _JsOkuyucu(y)
        if o.ac():
            ham = o.oku() or []
            isaret = "  ⬅ `Kumanda` BUNU SEÇER" if i == 0 else ""
            print("  %-16s %-28s %d eksen%s" % (y, o.ad or "?", len(ham), isaret))
            o.kapat()
        else:
            print("  %-16s (açılamadı)" % y)
    if len(yollar) > 1:
        print()
        print("  ⚠ BİRDEN FAZLA CİHAZ VAR. `Kumanda.ac()` sıralı İLK cihazı")
        print("    alır. Yukarıda 'BUNU SEÇER' yazan kumandan DEĞİLSE,")
        print("    okuduğumuz eksenler başka bir cihazın ve `pilot_devraldi`")
        print("    bundan tetikleniyor olabilir.")
    return yollar[0]


# ---------------------------------------------------------------- 1
def asama_durgunluk(kmd, sure):
    print()
    print("=" * 74)
    print("  1) DURGUNLUK — %g saniye HİÇBİR ŞEYE DOKUNMA" % sure)
    print("=" * 74)
    print("  Ellerini kumandadan ÇEK. Çubuklara, anahtarlara, trim'lere")
    print("  dokunma. Ölçüm başlıyor...")
    esik = KomutCfg.KMD_HAREKET_ESIK
    n = kmd.n_eksen or 8
    en_az = [9e9] * n
    en_cok = [-9e9] * n
    onceki = None
    devralma = 0
    hangi = {}
    t0 = time.monotonic()
    ornek = 0
    while time.monotonic() - t0 < sure:
        s = kmd.oku()
        if s is None:
            print("  ⛔ okuma kesildi: %s" % kmd.hata)
            return
        ham = list(s.ham or [])
        for i, v in enumerate(ham[:n]):
            en_az[i] = min(en_az[i], v)
            en_cok[i] = max(en_cok[i], v)
        # ⛔ komut.py'deki devralma dedektörünün BİREBİR aynısı
        simdiki = (s.throttle, s.pitch, s.roll, s.yaw)
        if onceki is not None:
            for k in range(4):
                if abs(simdiki[k] - onceki[k]) > esik:
                    devralma += 1
                    ad = ("throttle", "pitch", "roll", "yaw")[k]
                    hangi[ad] = hangi.get(ad, 0) + 1
                    break
        onceki = simdiki
        ornek += 1
        time.sleep(0.02)
    print()
    print("  ham eksen   en az     en çok   tepe-tepe   durum")
    print("  " + "-" * 58)
    for i in range(n):
        if en_az[i] > 8e8:
            continue
        tt = en_cok[i] - en_az[i]
        durum = "sakin" if tt <= esik else "⛔ GEZİNİYOR (eşik %.2f)" % esik
        print("    eksen %-2d  %+7.3f  %+7.3f   %7.3f    %s"
              % (i, en_az[i], en_cok[i], tt, durum))
    print()
    print("  ÖRNEK: %d   ·   HAREKET EŞİĞİ: %.3f" % (ornek, esik))
    if devralma:
        print("  ⛔⛔ BU %g SANİYEDE OTONOM %d KEZ KESİLİRDİ (pilot_devraldi)."
              % (sure, devralma))
        for ad, k in sorted(hangi.items(), key=lambda x: -x[1]):
            print("       tetikleyen: %-9s %d kez" % (ad, k))
        print()
        print("  ⛔ SEBEBİ ÜÇTEN BİRİDİR — 2. aşama hangisi olduğunu söyler:")
        print("     (a) YANLIŞ CİHAZ okunuyor (bkz. 0. aşama)")
        print("     (b) EŞLEME yanlış: o numara bir çubuk değil, gezinen")
        print("         bir AUX/trim kanalı")
        print("     (c) gerçek donanım titreşimi — o eksen ölü banttan")
        print("         büyük gezinen bir potansiyometre")
    else:
        print("  ✔ Otonom kesilmezdi. Devralma dedektörü bu kumandada temiz.")


# ---------------------------------------------------------------- 2
def asama_eksen(kmd, sure=6.0):
    print()
    print("=" * 74)
    print("  2) EKSEN BULMA — sırayla TEK BİR şeyi oynat")
    print("=" * 74)
    mevcut = dict(_eşleme())
    bulunan = {}
    for ad in ADLAR:
        if ad == "kip" and mevcut.get("kip", -1) < 0:
            print("\n  [kip] atanmamış (DOW_KMD_EKS_KIP=-1) — atlanıyor.")
            continue
        print()
        print("  >>> ŞİMDİ **%s** oynat (%g s). Başka hiçbir şeye dokunma."
              % (ad.upper(), sure))
        for g in (3, 2, 1):
            print("      %d..." % g); time.sleep(1.0)
        n = kmd.n_eksen or 8
        en_az = [9e9] * n; en_cok = [-9e9] * n
        t0 = time.monotonic()
        while time.monotonic() - t0 < sure:
            s = kmd.oku()
            if s is None:
                break
            for i, v in enumerate((s.ham or [])[:n]):
                en_az[i] = min(en_az[i], v); en_cok[i] = max(en_cok[i], v)
            time.sleep(0.02)
        gez = [(en_cok[i] - en_az[i]) if en_az[i] < 8e8 else 0.0
               for i in range(n)]
        sirali = sorted(range(n), key=lambda i: -gez[i])
        kaz = sirali[0]
        ikinci = gez[sirali[1]] if len(sirali) > 1 else 0.0
        bulunan[ad] = kaz
        m = mevcut.get(ad)
        isaret = "✔ eşleme DOĞRU" if m == kaz else (
            "⛔ EŞLEME YANLIŞ — ayarda eksen %s yazıyor" % m)
        print("      en çok gezinen: eksen %d (%.3f)   ikinci: eksen %d (%.3f)"
              % (kaz, gez[kaz], sirali[1] if len(sirali) > 1 else -1, ikinci))
        if gez[kaz] < 0.2:
            print("      ⚠ hiçbir eksen anlamlı gezinmedi — oynatıldı mı?")
        elif ikinci > gez[kaz] * 0.5:
            print("      ⚠ İKİ eksen birden gezindi; tek tek oynat.")
        else:
            print("      %s" % isaret)
    print()
    print("  ÖNERİLEN AYAR (yanlış olanları `baslat.sh`'a yaz):")
    ENV = {"roll": "DOW_KMD_EKS_ROLL", "pitch": "DOW_KMD_EKS_PITCH",
           "throttle": "DOW_KMD_EKS_THR", "yaw": "DOW_KMD_EKS_YAW",
           "arm": "DOW_KMD_EKS_ARM", "kip": "DOW_KMD_EKS_KIP"}
    for ad, i in bulunan.items():
        if mevcut.get(ad) != i:
            print("    export %s=%d" % (ENV[ad], i))
    if all(mevcut.get(a) == i for a, i in bulunan.items()):
        print("    (değişiklik gerekmiyor — eşleme zaten doğru)")


# ---------------------------------------------------------------- 3
def asama_canli(kmd):
    print()
    print("=" * 74)
    print("  3) CANLI — Ctrl+C ile çık")
    print("=" * 74)
    esik = KomutCfg.KMD_HAREKET_ESIK
    onceki = None
    try:
        while True:
            s = kmd.oku()
            if s is None:
                print("  kumanda koptu: %s" % kmd.hata); return
            ham = " ".join("%d:%+.2f" % (i, v)
                           for i, v in enumerate(s.ham or []))
            simdiki = (s.throttle, s.pitch, s.roll, s.yaw)
            kes = ""
            if onceki and any(abs(simdiki[k] - onceki[k]) > esik
                              for k in range(4)):
                kes = "  ⛔ pilot_devraldi TETİKLENİR"
            onceki = simdiki
            sys.stdout.write(
                "\r  T%+.2f P%+.2f R%+.2f Y%+.2f  arm=%d kip=%s | %s%s   "
                % (s.throttle, s.pitch, s.roll, s.yaw, int(s.arm),
                   s.kip_anahtari, ham, kes))
            sys.stdout.flush()
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()


def main():
    a = argparse.ArgumentParser(description="Kumanda teşhisi (araca hiçbir "
                                            "şey göndermez)")
    a.add_argument("--durgunluk", type=float, default=10.0,
                   help="durgunluk ölçümü kaç saniye (varsayılan 10)")
    a.add_argument("--asama", default="hepsi",
                   choices=("hepsi", "cihaz", "durgunluk", "eksen", "canli"))
    a = a.parse_args()

    print()
    if a.asama in ("hepsi", "cihaz"):
        if asama_cihaz() is None and a.asama == "cihaz":
            return 1
    kmd = Kumanda()
    if not kmd.ac():
        print("\n  ⛔ kumanda açılamadı: %s" % kmd.hata)
        return 1
    print("\n  AÇILDI: %s   (%s, %d eksen)" % (kmd.ad, kmd.yol, kmd.n_eksen))
    print("  MEVCUT EŞLEME: " + "  ".join("%s=%d" % (a_, i)
                                          for a_, i in _eşleme()))
    try:
        if a.asama in ("hepsi", "durgunluk"):
            asama_durgunluk(kmd, a.durgunluk)
        if a.asama in ("hepsi", "eksen"):
            asama_eksen(kmd)
        if a.asama in ("hepsi", "canli"):
            asama_canli(kmd)
    finally:
        kmd.kapat()
    return 0


if __name__ == "__main__":
    sys.exit(main())
