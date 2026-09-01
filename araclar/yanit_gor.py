#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YANIT GÖR — sunucunun döndürdüğü HAM JSON'u ekrana bas

⛔ NİYE VAR: gönderme tarafında dokümanın PDF'ine güvendik ve alan adları
   TUTMADI; sunucu HTTP 200 dönerken her alanı SIFIR okuyordu (bkz. R128).
   Aynı tuzak YANIT tarafında da olabilir — hedefin konumunu okuyamazsak
   bunu HİÇ göremeyiz, çünkü hata vermez, sadece "hedef yok" görünür.

   Bu araç sunucunun ne gönderdiğini OLDUĞU GİBİ basar ve bizim
   beklediğimiz alanlarla karşılaştırır.

⛔ `baslat.sh` ÇALIŞIRKEN KULLANMA: ikisi birden gönderirse doküman §7'nin
   2 Hz sınırı aşılır ve 400 + hata kodu 3 alırsın.

Kullanım:
    python3 araclar/yanit_gor.py
    python3 araclar/yanit_gor.py --tekrar 5      # 5 kez sor, degisimi gor
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gercek.sunucu import SunucuCfg                       # noqa: E402

#: Kodumuzun hedef paketinde ARADIĞI alanlar (`gercek/hedef.py`).
BEKLENEN = ("enlem", "boylam", "irtifa_ev", "hiz", "saat_farki")


def main():
    a = argparse.ArgumentParser(description="Sunucu yanıtını ham göster")
    a.add_argument("--tekrar", type=int, default=1)
    a.add_argument("--bekle", type=float, default=1.0,
                   help="istekler arası saniye (⛔ 0.5'in altına inme)")
    a = a.parse_args()

    cerez = [None]

    def ist(yol, govde=None):
        v = json.dumps(govde).encode() if govde is not None else None
        r = urllib.request.Request(SunucuCfg.ADRES.rstrip("/") + yol, data=v,
                                   method="POST" if v is not None else "GET")
        r.add_header("Content-Type", "application/json")
        if cerez[0]:
            r.add_header("Cookie", cerez[0])
        with urllib.request.urlopen(r, timeout=5) as y:
            c = y.headers.get("Set-Cookie")
            if c:
                cerez[0] = c.split(";")[0]
            return json.loads(y.read() or b"{}")

    print("=" * 70)
    print("  SUNUCU YANITI — HAM")
    print("=" * 70)
    print("  adres : %s   takım %s" % (SunucuCfg.ADRES, SunucuCfg.TAKIM_NO))
    print()

    try:
        ist("/api/giris", {"kadi": SunucuCfg.KADI, "sifre": SunucuCfg.SIFRE})
        print("  giriş ✔")
    except Exception as e:
        print("  ⛔ giriş başarısız: %s" % e)
        return 1

    paket = {
        "takim_numarasi": SunucuCfg.TAKIM_NO,
        "iha_enlem": 41.0, "iha_boylam": 29.0, "iha_irtifa": 50.0,
        "iha_dikilme": 0.0, "iha_yonelme": 0.0, "iha_yatis": 0.0,
        "iha_hiz": 0.0, "iha_mod": False, "iha_kilitlenme": False,
        "hedef_merkez_X": 0, "hedef_merkez_Y": 0,
        "hedef_genislik": 0, "hedef_yukseklik": 0,
    }

    son = None
    for i in range(max(1, a.tekrar)):
        if i:
            time.sleep(max(0.55, a.bekle))
        try:
            son = ist("/api/telemetri_gonder", paket)
        except Exception as e:
            print("  ⛔ istek hatası: %s" % e)
            return 1
        print("  --- yanıt %d ---" % (i + 1))
        print(json.dumps(son, indent=2, ensure_ascii=False))
        print()

    # ---- karşılaştırma ----
    print("=" * 70)
    if not isinstance(son, dict):
        print("  ⛔ yanıt sözlük değil")
        return 1
    print("  ÜST DÜZEY ANAHTARLAR:", list(son.keys()))
    hedefler = son.get("hedef_iha_verileri")
    if hedefler is None:
        print("  ⛔ `hedef_iha_verileri` anahtarı YOK.")
        print("     Sunucu başka bir ad kullanıyor olabilir — üstteki")
        print("     anahtar listesine bak ve bana söyle.")
        return 1
    if not hedefler:
        print("  ⚠ `hedef_iha_verileri` BOŞ — havada hedef İHA yok.")
        print("     Bu bir HATA DEĞİL; hedef uçunca dolacak.")
        return 0
    h = hedefler[0]
    print("  HEDEF KAYDININ ALANLARI:", list(h.keys()))
    eksik = [k for k in BEKLENEN if k not in h]
    fazla = [k for k in h if k not in BEKLENEN]
    if eksik:
        print()
        print("  ⛔⛔ KODUMUZUN ARADIĞI ALANLAR EKSİK: %s" % eksik)
        print("     Sunucudaki karşılıkları: %s" % fazla)
        print("     `gercek/hedef.py` bu adlara göre DÜZELTİLMELİ —")
        print("     yoksa hedefi HİÇ göremeyiz ve hata da vermez.")
        return 1
    print("  ✔ Beklediğimiz alanların hepsi var — okuma doğru çalışır.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
