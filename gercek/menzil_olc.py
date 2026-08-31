# -*- coding: utf-8 -*-
"""
================================================================================
MENZİL ÖLÇÜMÜ — MENZIL_C'yi TÜRETME değil ÖLÇÜM yap
================================================================================
NİYE: `MENZIL_C` şu an TÜRETİLMİŞ ve içinde İKİ VARSAYIM var:
  (a) FOV'un hangi eksende verildiği   (köşegen/yatay/dikey → C 676/541/406)
  (b) dedektörün kutusunun gerçek kanat açıklığından ne kadar geniş
      olduğu ("kutu payı"; simde %7.4 ölçülmüştü, GERÇEK MODELDE bilinmiyor)

Bu araç ikisini birden gereksiz kılar. Benzer üçgenlerden:

        kutu_ölçüsü  =  C / R        ⟹        C = kutu_ölçüsü × R

`R`'yi ŞERİT METREYLE ölçüyorsun, `kutu_ölçüsü`nü dedektörün KENDİSİ
veriyor. Aradaki her şey — mercek eğrisi, kutu payı, çözünürlük, kartın
kırpması — ölçüme ZATEN dahil. Hiçbirini ayrı bilmene gerek yok.

⛔ BALIKGÖZ TELAFİSİ: kutu kadrajın kenarındaysa balıkgöz onu büyütür.
   `C` MERKEZ referanslı olmalı, yoksa her ölçüm kutunun nerede
   durduğuna göre farklı çıkar. Araç bunu `olcek_duzeltme` ile geri
   alır ve kutunun kadraj yarıçapını da yazar — ölçümü ORTADA yapman
   için uyarır.

NASIL KULLANILIR
  1. Talon'u kameraya TAM KARŞIDAN, DİK tut — kanat açıklığı tam görünsün.
  2. Kamera ile kanat düzlemi arasını şerit metreyle ölç.
  3. Çalıştır:
         python3 gercek/menzil_olc.py --mesafe 10
     (drone_yki çalışıyorsa kareyi ondan alır; çalışmıyorsa kamerayı
      kendisi açar)
  4. Araç birkaç saniye örnekler, MEDYANI alır ve yapıştırılacak
     `export` satırını yazar.
  5. 2-3 farklı mesafede tekrarla. Çıkan `C` değerleri TUTARLI olmalı;
     olmuyorsa bir şey yanlış (mesafe ölçümü, ya da hedef kadrajın
     kenarında).

⛔ MEDYAN, ORTALAMA DEĞİL: tek bir kötü kare (yarım görünen uçak,
   yanlış-pozitif) ortalamayı çeker, medyanı çekmez.
================================================================================
"""
import argparse
import math
import os
import statistics
import sys
import time
import urllib.request

BURASI = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(BURASI)
DEPO = os.path.dirname(KOK)
for _p in (KOK, DEPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _panelden_kare(adres, zaman_asimi=4.0):
    ham = urllib.request.urlopen(
        "%s/kare.jpg?t=%d" % (adres, time.time() * 1000),
        timeout=zaman_asimi).read()
    import cv2
    import numpy as np
    return cv2.imdecode(np.frombuffer(ham, np.uint8), cv2.IMREAD_COLOR)


def main():
    ap = argparse.ArgumentParser(
        description="MENZIL_C'yi ölçerek bul (türetme değil)")
    ap.add_argument("--mesafe", type=float, required=True,
                    metavar="METRE",
                    help="kamera ile Talon'un KANAT DÜZLEMİ arası, ŞERİT "
                         "METREYLE ölçülmüş")
    ap.add_argument("--sure", type=float, default=8.0, help="örnekleme (s)")
    ap.add_argument("--panel", default="http://127.0.0.1:8810",
                    help="drone_yki adresi ('yok' = kamerayı kendim aç)")
    ap.add_argument("--kamera", default=os.environ.get("DOW_KAM_KAYNAK", "oto"))
    ap.add_argument("--conf", type=float, default=0.20,
                    help="tarama eşiği (kabul eşiği DEĞİL)")
    a = ap.parse_args()

    if not (0.5 <= a.mesafe <= 500.0):
        print("  ⛔ mesafe %g m — 0.5..500 m arası olmalı" % a.mesafe)
        return 2

    import warnings
    import logging
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    import cv2
    from ultralytics import YOLO
    from dow.gorus import kamera as KAM
    from dow.gudum.ibvs import IbvsCfg, olcu
    from dow.gorus.dedektor import MODEL_YOLU

    print("=" * 68)
    print("  MENZİL ÖLÇÜMÜ — Talon %g m'de" % a.mesafe)
    print("=" * 68)
    print("  model     : %s" % MODEL_YOLU)
    print("  mercek    : %s   f_bg %.1f" % (KAM.OPTIK_MODEL, KAM.F_BG))
    print("  ölçü      : %s" % IbvsCfg.MENZIL_OLCU)
    _C_simdi = (KAM.MENZIL_C_KOSEGEN if IbvsCfg.MENZIL_OLCU == "kosegen"
                else KAM.MENZIL_C)
    print("  şu anki C : %.1f   (tablodaki 'şimdiki' bununla hesaplanır)"
          % _C_simdi)
    print("")
    print("  ⛔ Talon'u TAM KARŞIDAN, DİK tut — kanat açıklığı tam görünsün.")
    print("  ⛔ Kadrajın ORTASINDA tut — kenarda balıkgöz ölçüyü bozar.")
    print("")

    if not os.path.exists(MODEL_YOLU):
        print("  ⛔ model yok: %s" % MODEL_YOLU)
        return 2
    m = YOLO(MODEL_YOLU)

    kam = None
    panel = a.panel if a.panel.lower() != "yok" else None
    if panel:
        try:
            _panelden_kare(panel, 3.0)
            print("  kaynak    : PANEL %s/kare.jpg" % panel)
        except Exception:
            panel = None
    if panel is None:
        from gercek.kamera_yakala import Kamera, KameraCfg
        KameraCfg.KAYNAK = a.kamera
        kam = Kamera()
        if not kam.ac():
            print("  ⛔ kamera açılamadı: %s" % kam.hata)
            return 2
        time.sleep(0.8)
        print("  kaynak    : KAMERA %s" % a.kamera)

    print("")
    print("  sn   kutu(px)     köşegen  güven  yarıçap   şimdiki   ÇIKAN C")
    print("  " + "-" * 64)

    ornekler = []
    t0 = time.time()
    n_kare = 0
    while time.time() - t0 < a.sure:
        try:
            im = (_panelden_kare(panel) if panel
                  else kam.son_kare()[0])
        except Exception:
            time.sleep(0.3)
            continue
        if im is None:
            time.sleep(0.1)
            continue
        n_kare += 1
        r = m.predict(im, imgsz=640, conf=a.conf, verbose=False)[0]
        b = r.boxes
        if not len(b):
            time.sleep(0.1)
            continue
        i = int(b.conf.argmax())
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[i]]
        w, h = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        c = float(b.conf[i])
        boyut, C_simdi = olcu(w, h, IbvsCfg)
        # ⛔ BALIKGÖZ TELAFİSİ — C MERKEZ referanslı olmalı
        s = KAM.olcek_duzeltme(cx, cy)
        C_cikan = boyut * a.mesafe / max(1e-6, s)
        simdiki = C_simdi * s / boyut if boyut > 0 else 0.0
        yaricap = math.hypot(cx - KAM.CX, cy - KAM.CY)
        ornekler.append((C_cikan, boyut, c, yaricap))
        if len(ornekler) % 3 == 1:
            print("  %4.0f  %4.0fx%-4.0f  %7.1f  %5.2f  %6.0f px  %6.1f m  %8.1f"
                  % (time.time() - t0, w, h, boyut, c, yaricap, simdiki, C_cikan))
        time.sleep(0.1)

    if kam:
        kam.kapat()

    print("")
    print("  " + "=" * 64)
    if len(ornekler) < 3:
        print("  ⛔ YETERLİ ÖRNEK YOK (%d kutu / %d kare)."
              % (len(ornekler), n_kare))
        print("     · Talon kadrajda mı, tam karşıdan mı?")
        print("     · `python3 gercek/tespit_izle.py` ile güveni izle.")
        print("  " + "=" * 64)
        return 3

    Cs = sorted(x[0] for x in ornekler)
    med = statistics.median(Cs)
    sapma = max(abs(v - med) for v in Cs) / med * 100.0
    yari_ort = statistics.median(x[3] for x in ornekler)
    kanat = float(os.environ.get("DOW_OPTIK_KANAT", "1.718"))

    print("  örnek     : %d kutu / %d kare" % (len(ornekler), n_kare))
    print("  ÇIKAN C   : %.1f   (en düşük %.1f, en yüksek %.1f)"
          % (med, Cs[0], Cs[-1]))
    print("  sapma     : %%%.1f  %s" % (sapma,
          "✔ tutarlı" if sapma < 10 else "⛔ DAĞINIK — ölçümü tekrarla"))
    print("  kutu yarıçapı medyanı: %.0f px %s"
          % (yari_ort, "" if yari_ort < 150 else
             "⚠ KENARA YAKIN — ortada tekrarla"))
    print("")
    eski = (KAM.MENZIL_C_KOSEGEN if IbvsCfg.MENZIL_OLCU == "kosegen"
            else KAM.MENZIL_C)
    print("  şu anki C : %.1f   ->   ölçülen: %.1f   (%+.0f%% fark)"
          % (eski, med, (med / eski - 1) * 100))
    print("  ima edilen odak: %.1f px  (kutu payı dahil, kanat %.3f m)"
          % (med / kanat, kanat))
    print("")
    print("  --- baslat_drone.sh'a yapıştır ---")
    if IbvsCfg.MENZIL_OLCU == "kosegen":
        print("  export DOW_OPTIK_MENZIL_C_KOSEGEN=%.1f" % med)
        print("  export DOW_OPTIK_MENZIL_C=%.1f   # köşegen/max oranı 1.0568"
              % (med / 1.0568))
    else:
        print("  export DOW_OPTIK_MENZIL_C=%.1f" % med)
    print("")
    print("  ⚠ 2-3 FARKLI MESAFEDE tekrarla. Çıkan C'ler tutarlı olmalı;")
    print("    değilse mesafe ölçümü ya da hedefin duruşu şüphelidir.")
    print("  " + "=" * 64)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("")
