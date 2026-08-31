# -*- coding: utf-8 -*-
"""
================================================================================
TESPİT İZLE — dedektör hedefi görüyor mu, CANLI
================================================================================
NİYE: panel yalnız EŞİĞİ GEÇEN kutuyu çizer. Model hedefi 0.35 güvenle
görüyorsa (eşik 0.40) panelde HİÇBİR ŞEY görünmez ve "model çalışmıyor"
sanırsın. Bu araç EŞİKSİZ bakar: en yüksek güveni her karede yazar.

⛔ KAMERAYI AÇMAZ. Kareyi drone panelinin `/kare.jpg` ucundan alır, yani
   `drone_yki.py` çalışırken de kullanılabilir. V4L2 kamerayı tek bir
   sürecin açmasına izin verir; ikinci bir açan olsaydı panel körleşirdi.

KULLANIM
    python3 gercek/tespit_izle.py                 # sürekli izle
    python3 gercek/tespit_izle.py --conf 0.05     # daha duyarlı bak
    python3 gercek/tespit_izle.py --kaydet        # kutulu kareleri sakla

NE GÖRECEKSİN
    guven 0.00        -> model hedefi HİÇ görmüyor (dağılım dışı)
    guven 0.10-0.39   -> GÖRÜYOR ama eşiğin altında -> eşiği düşür
    guven >= 0.40     -> panel de çizer, sorun yok
================================================================================
"""
import argparse
import os
import sys
import time
import urllib.request

BURASI = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(BURASI)
for _p in (KOK, os.path.dirname(KOK)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main():
    ap = argparse.ArgumentParser(description="Dedektör hedefi görüyor mu (canlı)")
    ap.add_argument("--panel", default="http://127.0.0.1:8810",
                    help="drone panelinin adresi")
    ap.add_argument("--model", default=None, help="model yolu (boş = DOW_MODEL)")
    ap.add_argument("--conf", type=float, default=0.01,
                    help="tarama eşiği — DÜŞÜK tut, amaç eşiği görmek")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--sure", type=float, default=0.0, help="0 = süresiz")
    ap.add_argument("--kaydet", action="store_true",
                    help="kutulu kareleri logs/tespit/ altına yaz")
    a = ap.parse_args()

    import warnings, logging
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    import cv2
    import numpy as np
    from ultralytics import YOLO

    yol = a.model or os.path.join(
        os.path.dirname(KOK), "modeller",
        "%s.pt" % os.environ.get("DOW_MODEL", "tayarti_v1"))
    print("=" * 66)
    print("  TESPİT İZLE")
    print("=" * 66)
    print("  model : %s" % yol)
    print("  panel : %s/kare.jpg" % a.panel)
    print("  eşik  : %.2f (tarama)   imgsz %d" % (a.conf, a.imgsz))
    if not os.path.exists(yol):
        print("  ⛔ model dosyası yok: %s" % yol)
        return 2
    m = YOLO(yol)
    kayit = os.path.join(KOK, "logs", "tespit")
    if a.kaydet:
        os.makedirs(kayit, exist_ok=True)
        print("  kayıt : %s" % kayit)
    print("")
    print("  ⛔ Kamerayı Talon'a DOĞRULT ve aşağıdaki 'guven' sütununa bak.")
    print("  Ctrl+C ile çık.\n")
    print("  sn    kare  guven   kutu        en_iyi_konum   durum")
    print("  " + "-" * 62)

    t0 = time.time()
    n = 0
    n_var = 0
    en_yuksek = 0.0
    son_yazim = 0.0
    while a.sure <= 0 or (time.time() - t0) < a.sure:
        try:
            ham = urllib.request.urlopen(
                "%s/kare.jpg?t=%d" % (a.panel, time.time() * 1000),
                timeout=4).read()
        except Exception as e:
            print("  ⛔ panelden kare alınamadı: %s" % str(e)[:60])
            print("     `drone_yki.py` çalışıyor mu? (%s)" % a.panel)
            time.sleep(2.0)
            continue
        im = cv2.imdecode(np.frombuffer(ham, np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            time.sleep(0.2)
            continue
        n += 1
        r = m.predict(im, imgsz=a.imgsz, conf=a.conf, verbose=False)[0]
        b = r.boxes
        if len(b):
            i = int(b.conf.argmax())
            c = float(b.conf[i])
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[i]]
            w, h = x2 - x1, y2 - y1
            n_var += 1
            en_yuksek = max(en_yuksek, c)
            durum = ("EŞİK ÜSTÜ ✔" if c >= 0.40
                     else ("EŞİK ALTI ⚠ (%.2f)" % c))
            satir = ("  %4.0f %6d  %.3f  %4.0fx%-4.0f  (%4.0f,%4.0f)  %s"
                     % (time.time() - t0, n, c, w, h,
                        (x1 + x2) / 2, (y1 + y2) / 2, durum))
            if a.kaydet and time.time() - son_yazim > 1.0:
                g = im.copy()
                cv2.rectangle(g, (int(x1), int(y1)), (int(x2), int(y2)),
                              (0, 255, 0), 2)
                cv2.putText(g, "%.2f" % c, (int(x1), max(14, int(y1) - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.imwrite(os.path.join(kayit, "t%06d_%.2f.jpg" % (n, c)), g)
                son_yazim = time.time()
        else:
            satir = ("  %4.0f %6d  0.000     —              —        "
                     "GÖRMÜYOR" % (time.time() - t0, n))
        if n % 5 == 1 or (len(b) and float(b.conf.max()) >= 0.20):
            print(satir)
        time.sleep(0.15)

    print("\n  " + "=" * 62)
    print("  kare %d · kutu bulunan %d (%%%.0f) · en yüksek güven %.3f"
          % (n, n_var, 100.0 * n_var / max(1, n), en_yuksek))
    if en_yuksek == 0.0:
        print("  ⛔ MODEL HEDEFİ HİÇ GÖRMEDİ.")
        print("     · Kamera gerçekten Talon'a mı bakıyordu?")
        print("     · Model bu görüş açısıyla eğitildi mi? (yerdeki uçağa")
        print("       yakından bakmak, havadaki uzak uçaktan çok farklıdır)")
    elif en_yuksek < 0.40:
        print("  ⚠ MODEL GÖRÜYOR AMA EŞİĞİN ALTINDA (en yüksek %.2f)." % en_yuksek)
        print("     Eşiği düşürerek dene:")
        print("       DOW_DET_CONF=%.2f ./baslat_drone.sh --gorsel"
              % max(0.05, en_yuksek * 0.7))
    else:
        print("  ✔ MODEL HEDEFİ EŞİK ÜSTÜNDE GÖRÜYOR.")
    print("  " + "=" * 62)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("")
