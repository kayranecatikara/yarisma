#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SUNUCU TESTİ — yarışma sunucusuna bağlanabiliyor muyuz, paketimiz geçiyor mu

⛔ YARIŞMA GÜNÜ İLK ÇALIŞTIRILACAK ŞEY. Uçuştan önce şunları kanıtlar:
   1. Adres doğru mu, ağ ulaşıyor mu
   2. Kullanıcı adı/şifre geçiyor mu (`/api/giris`)
   3. Sunucu saati alınıyor mu
   4. Telemetri paketimiz KABUL EDİLİYOR mu (§7.1 biçimi)
   5. Yanıtta HEDEF verisi geliyor mu (§7.2) ve KAÇ Hz tazeleniyor
   6. Hız sınırını (2 Hz) aşmıyor muyuz

⛔ ARAÇ GEREKMEZ: sahte ama BİÇİM OLARAK GEÇERLİ bir telemetri gönderir.
   Böylece drone açılmadan önce ağ ve kimlik doğrulanmış olur.

Kullanım:
    python3 araclar/sunucu_testi.py
    python3 araclar/sunucu_testi.py --sure 30 --hz 1.8
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gercek.hedef import HedefKaynagi                    # noqa: E402
from gercek.sunucu import SunucuIstemcisi, SunucuCfg     # noqa: E402


def _sahte_telemetri():
    """SUNUCUNUN GERÇEK ŞEMASINDA sahte paket — 14 alan.

    ⛔ Adlar haberleşme dokümanının PDF'inden DEĞİL, komiteden gelen
      gerçek C# şemasından. İkisi tutmuyor; PDF adlarıyla gönderirsek
      sunucu paketi KABUL EDER (HTTP 200) ama her alanı SIFIR okur.
      Bkz. `drone_yki._telemetri` ve bekçi R128.
    """
    return {
        "takim_numarasi": SunucuCfg.TAKIM_NO,
        "iha_enlem": 41.0000000, "iha_boylam": 29.0000000,
        "iha_irtifa": 50.0,
        "iha_dikilme": 0.0, "iha_yonelme": 0.0, "iha_yatis": 0.0,
        "iha_hiz": 0.0,
        "iha_mod": False, "iha_kilitlenme": False,
        "hedef_merkez_X": 0, "hedef_merkez_Y": 0,
        "hedef_genislik": 0, "hedef_yukseklik": 0,
    }


def main():
    a = argparse.ArgumentParser(description="Yarışma sunucusu testi")
    a.add_argument("--sure", type=float, default=20.0)
    a.add_argument("--hz", type=float, default=None, help="gönderim hızı")
    a = a.parse_args()
    if a.hz:
        SunucuCfg.GONDER_HZ = a.hz

    print("=" * 70)
    print("  YARIŞMA SUNUCUSU TESTİ")
    print("=" * 70)
    print("  adres    : %s" % SunucuCfg.ADRES)
    print("  kullanıcı: %s" % (SunucuCfg.KADI or "⛔ BOŞ"))
    print("  takım no : %s%s" % (SunucuCfg.TAKIM_NO,
                                 "   ⛔ 0 — HAKEMDEN ALDIĞINI GİR!"
                                 if SunucuCfg.TAKIM_NO == 0 else ""))
    print("  gönderim : %.2f Hz   (⛔ doküman sınırı 2 Hz)" % SunucuCfg.GONDER_HZ)
    print()

    if SunucuCfg.GONDER_HZ > 2.0:
        print("  ⛔ HIZ SINIRI AŞILDI — doküman §7: 2 Hz üzeri 400 + hata 3")
        return 2

    hedef = HedefKaynagi()
    ist = SunucuIstemcisi(hedef, _sahte_telemetri)

    print("  [1] OTURUM AÇMA (/api/giris)…")
    ok, mesaj = ist.giris()
    print("      %s %s" % ("✔" if ok else "⛔", mesaj))
    if not ok:
        print()
        print("      · adres doğru mu, ethernet takılı mı (doküman §2)")
        print("      · kullanıcı adı/şifre doğru mu")
        return 1

    print("  [2] SUNUCU SAATİ (/api/sunucusaati)…")
    s = ist.saati_al()
    print("      %s %s" % ("✔" if s else "⛔", s or ist.son_hata))

    print("  [3] TELEMETRİ + HEDEF (%g s)…" % a.sure)
    print()
    print("      sn   gönderilen  hata  hedef_paket  yaş(s)   hedef konum")
    print("      " + "-" * 62)
    ist.basla()
    t0 = time.time()
    son_n = 0
    try:
        while time.time() - t0 < a.sure:
            time.sleep(2.0)
            d = ist.durum()
            hd = hedef.durum()
            h = hedef.son()
            konum = ("%.6f, %.6f  irt %.0f" % (h["enlem"], h["boylam"],
                                               h["irtifa_ev"])) if h else "—"
            print("      %4.0f   %8d  %5d  %10s  %6s   %s"
                  % (time.time() - t0, d["gonderilen"], d["hata"],
                     hd.get("n_paket"), hd.get("yas"), konum))
            son_n = hd.get("n_paket") or 0
    except KeyboardInterrupt:
        pass
    ist.dur()

    d = ist.durum()
    gecen = max(0.001, time.time() - t0)
    print()
    print("=" * 70)
    print("  gönderilen : %d   (%.2f Hz)" % (d["gonderilen"],
                                             d["gonderilen"] / gecen))
    print("  hata       : %d   %s" % (d["hata"], d["hata"] and d["hata"] or ""))
    print("  hız ihlali : %d   (kod kendi kendini frenledi)" % d["hiz_ihlali"])
    print("  hedef paket: %d   (%.2f Hz)" % (son_n, son_n / gecen))
    print("  son hata   : %s" % (ist.son_hata or "yok"))
    print()
    if d["gonderilen"] == 0:
        print("  ⛔ HİÇ PAKET GİTMEDİ.")
        return 1
    if son_n == 0:
        print("  ⚠ TELEMETRİ GİDİYOR ama YANITTA HEDEF VERİSİ YOK.")
        print("     · hedef İHA henüz havada olmayabilir")
        print("     · takım numarası yanlış olabilir")
        return 1
    if d["gonderilen"] / gecen > 2.05:
        print("  ⛔ 2 Hz AŞILDI — doküman cezalandırıyor.")
        return 1
    print("  ✔ SUNUCU HAZIR — telemetri gidiyor, hedef verisi geliyor.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
