# -*- coding: utf-8 -*-
"""
================================================================================
HEDEF TESTİ — Talon'dan GPS geliyor mu?
================================================================================
Talon bilgisayarındaki `yayinci.py`, hedefin konumunu UDP 47800'e basar.
Bu araç o akışı dinler ve SAYIYLA rapor eder. Drone yer kontrolünü
başlatmadan ÖNCE çalıştırılır: akış yoksa otonom güdüm hedefsiz kalır.

⛔ NEYE BAKILIR — üçü birden:
   1. PAKET GELİYOR MU        yoksa: ağ/IP/yayıncı sorunu
   2. HIZI YETERLİ Mİ         5 Hz altı: yayıncı zorlanıyor ya da paket düşüyor
   3. VERİ TAZE Mİ            yaş = ulaşma yaşı + saat_farki
      ⚠ Paket az önce gelmiş olabilir ama İÇİNDEKİ veri eski olabilir:
        yayıncı kalp atışı basar ve telsiz koparsa son bilinen konumu
        tekrarlar. 28 m/s giden hedef 500 ms'de 14 m yol alır.

Kullanım:
    python3 gercek/hedef_testi.py              # 15 s dinle, rapor et
    python3 gercek/hedef_testi.py --sure 60
    python3 gercek/hedef_testi.py --port 47800

⛔ Bu araç hiçbir komut göndermez; yalnız dinler.
================================================================================
"""
import argparse
import os
import sys
import time

BURASI = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(BURASI)
for _p in (KOK, os.path.dirname(KOK)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gercek.hedef import HedefKaynagi, UdpDinleyici, HedefCfg   # noqa: E402


def _yerel_ipler():
    """Bu makinenin yerel IP'leri. Talon tarafına verilecek adres budur.

    ⛔ Kabuk komutu ÇAĞIRMIYORUZ: `ip` /usr/sbin altında olabilir ve
       alt sürecin PATH'inde bulunmayabilir — sahada boş liste basıyordu.
    """
    import socket
    bulunan = []
    # 1) dışarı giden yolu soran numara (paket GÖNDERMEZ)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        bulunan.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    # 2) ana makine adından çözülenler
    try:
        for bilgi in socket.getaddrinfo(socket.gethostname(), None,
                                        socket.AF_INET):
            ip = bilgi[4][0]
            if not ip.startswith("127.") and ip not in bulunan:
                bulunan.append(ip)
    except OSError:
        pass
    return bulunan or ["(bulunamadı — `ip -4 addr` ile bak)"]


def main():
    ap = argparse.ArgumentParser(description="Talon'dan hedef GPS'i geliyor mu")
    ap.add_argument("--sure", type=float, default=15.0, help="dinleme süresi (s)")
    ap.add_argument("--port", type=int, default=HedefCfg.UDP_PORT)
    a = ap.parse_args()

    print("=" * 66)
    print("  HEDEF TESTİ — UDP %d, %.0f saniye dinleniyor" % (a.port, a.sure))
    print("=" * 66)

    h = HedefKaynagi()
    u = UdpDinleyici(h, port=a.port)
    if not u.basla():
        print("  ⛔ port dinlenemedi: %s" % u.hata)
        print("     Başka bir program 47800'ü tutuyor olabilir:")
        print("       ss -lunp | grep %d" % a.port)
        return 2

    t0 = time.time()
    onceki = 0
    print("\n  sn   paket  Hz    yaş(s)   enlem       boylam      irtifa  hız")
    print("  " + "-" * 64)
    try:
        while time.time() - t0 < a.sure:
            time.sleep(1.0)
            gecen = time.time() - t0
            d = h.durum()
            hz = h.n_paket - onceki
            onceki = h.n_paket
            p = h.son()
            if p:
                print("  %4.0f %6d  %4d  %6.2f   %-11.6f %-11.6f %6.1f %5.1f"
                      % (gecen, h.n_paket, hz, d["yas"], p["enlem"],
                         p["boylam"], p["irtifa_ev"], p["hiz"]))
            else:
                print("  %4.0f %6d  %4d  %6s   %s"
                      % (gecen, h.n_paket, hz,
                         "—" if d["yas"] > 1e6 else "%.2f" % d["yas"],
                         "VERİ YOK" if h.n_paket == 0 else "BAYAT (yaş aşıldı)"))
    except KeyboardInterrupt:
        pass
    finally:
        u.dur()

    gecen = max(1e-6, time.time() - t0)
    d = h.durum()
    print("\n  " + "=" * 62)
    if h.n_paket == 0:
        print("  ⛔ HİÇ PAKET GELMEDİ")
        print("")
        print("     SIRAYLA KONTROL ET:")
        print("       1. Talon bilgisayarında yayıncı çalışıyor mu?")
        print("            ./baslat_talon.sh <seri-port> <BU-BILGISAYARIN-IP>")
        print("       2. IP doğru mu? Bu bilgisayarın IP'si:")
        for ip in _yerel_ipler():
            print("            %s" % ip)
        print("       3. İki bilgisayar AYNI ağda mı? (ping ile dene)")
        print("       4. Güvenlik duvarı UDP %d'i kesiyor olabilir." % a.port)
        print("  " + "=" * 62)
        return 3

    hz = h.n_paket / gecen
    print("  paket        : %d  (%.1f Hz ortalama)" % (h.n_paket, hz))
    print("  reddedilen   : %d  %s" % (h.n_red, h.son_red_sebep or ""))
    print("  son yaş      : %.2f s  (ulaşma %.2f + veri %.2f)"
          % (d["yas"], d["yas_ulasma"], d["yas_veri"]))
    print("")
    sorun = 0
    if hz < 4.0:
        print("  ⚠ HIZ DÜŞÜK (%.1f Hz). Beklenen 5-10 Hz." % hz)
        print("    Ağ paketi düşürüyor ya da yayıncı araçtan konum alamıyor.")
        sorun += 1
    if h.n_red:
        print("  ⚠ %d PAKET REDDEDİLDİ: %s" % (h.n_red, h.son_red_sebep))
        sorun += 1
    if not d["var"]:
        print("  ⛔ SON VERİ BAYAT — güdüm hedefi YOK sayar.")
        print("    Yayıncı son bilinen konumu tekrarlıyor olabilir.")
        sorun += 1
    if not sorun:
        print("  ✔ AKIŞ SAĞLIKLI — otonom güdüm hedefi görebilir.")
    print("  " + "=" * 62)
    return 0 if not sorun else 1


if __name__ == "__main__":
    sys.exit(main())
