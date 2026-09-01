#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAFLIGHT YEDEK / GERİ YÜKLE — uçuş kartı ayarlarını CLI üzerinden taşı

⛔ NİYE VAR (2026-09-01): yarışma öncesi elimizdeki drone alınıp yerine
   FABRİKA AYARLARINA SIFIRLANMIŞ bir drone veriliyor. Bizim bütün uçuş
   davranışımız kartın ayarlarına bağlı:
     · AUX2 (kanal 6) = ALT HOLD, AUX4 (kanal 8) = POS HOLD
       -> `gercek/dikey_inis.py` FAILSAFE İNİŞİ bu iki anahtara basıyor.
          Atamalar yoksa acil iniş düğmesi HİÇBİR ŞEY YAPMAZ.
     · angle_limit = 60
       -> `DOW_CEV_ACI_MAX=60`; güdüm çubuğu bu sayıyla açıya çeviriyor.
          Kart 45'te olursa araç komut edilenden AZ yatar, hedefi ıskalar.
     · failsafe_procedure = AUTO-LAND, alt_hold_deadband = 20,
       ap_hover_throttle = 1310
     · CRSF'in hangi UART'ta olduğu -> ESP32 linki oradan geçiyor.

   Bunları elle yeniden girmek saatler sürer ve bir satır unutulursa
   sahada anlaşılmaz. `diff all` çıktısı tek dosyada hepsini taşır.

⛔⛔ TAŞINMAYACAK OLANLAR — DONANIMA ÖZEL:
   Aşağıdaki ayarlar YENİ KARTIN kendi sensörüne aittir. Eski karttan
   kopyalamak, yeni kartın sensörüne YANLIŞ sıfır noktası vermektir:
     acc_calibration   ivmeölçer sıfırı  -> yeni kartta YENİDEN kalibre
     magzero_*         manyetometre      -> yeni kartta YENİDEN kalibre
     vbat_scale        pil gerilim ölçeği-> yanlışsa failsafe yanlış tetikler
     ibata_scale       akım ölçeği
   `--temiz` (varsayılan AÇIK) bu satırları yedekten ÇIKARIR.
   `--ham` verirsen çıkarmaz — ⛔ ne yaptığını bilmiyorsan verme.

ELRS BAĞLAMASI (bind) BU DOSYADA YOK. Bind bilgisi ALICININ içindedir,
uçuş kartında değil. Yeni drone'u kumandaya ELDEN bind edeceksin.

Kullanım:
    # 1) YEDEK AL (salt-okunur, risksiz) — drone gitmeden ÖNCE
    python3 araclar/betaflight_yedek.py --al

    # 2) Yeni drone geldiğinde GERİ YÜKLE
    python3 araclar/betaflight_yedek.py --yukle yedek/bf_<zaman>.txt --onayla

    # port kendiliğinden bulunuyor; gerekirse: --port /dev/ttyACM0
"""
import argparse
import glob
import os
import re
import sys
import time

try:
    import serial
except ImportError:
    print("⛔ pyserial yok:  pip install pyserial")
    sys.exit(1)

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEDEK_DIZIN = os.path.join(KOK, "yedek")

#: Donanıma özel — yeni karta KOPYALANMAZ (yukarıdaki açıklama).
DONANIMA_OZEL = (
    "acc_calibration", "magzero_x", "magzero_y", "magzero_z",
    "mag_calibration", "vbat_scale", "ibata_scale", "vbat_divider",
    "vbat_multiplier", "acc_trim_pitch", "acc_trim_roll",
    "gyro_1_align_", "accgyro_",
)

#: Yedekte MUTLAKA bulunması gereken satırlar. Yoksa yedek EKSİKTİR ve
#  uçuş davranışımız yeni kartta farklı olur (yukarıdaki gerekçe).
KRITIK = {
    "aux ": "AUX kanal atamaları (ALT HOLD / POS HOLD) — failsafe inişi",
    "angle_limit": "azami yatış açısı — güdüm çubuk->açı çevirimi",
    "failsafe_procedure": "failsafe davranışı (AUTO-LAND)",
    "serialrx_provider": "alıcı protokolü (CRSF)",
    "serial ": "UART atamaları — ESP32/CRSF linki",
}


#: ⭐ FABRİKA VARSAYILANI OLDUĞU İÇİN `diff all` ÇIKTISINDA GÖRÜNMEYEN
#  ama uçuşumuzun BAĞLI OLDUĞU ayarlar (2026-09-01'de karttan `get` ile
#  okundu, SPEDIXF405 / Betaflight 2025.12.5).
#  Yeni drone farklı bir Betaflight sürümündeyse varsayılanlar DEĞİŞMİŞ
#  olabilir; o yüzden geri yüklemeden sonra bunlar TEK TEK sorulur.
BEKLENEN = {
    "angle_limit":        ("60",        "güdüm çubuk->açı çevirimi (DOW_CEV_ACI_MAX=60)"),
    "failsafe_procedure": ("AUTO-LAND", "link kesilince araç kendi iner"),
    "serialrx_provider":  ("CRSF",      "ELRS alıcı protokolü"),
    "alt_hold_deadband":  ("20",        "ALT HOLD ölü bandı — dikey iniş rampası"),
    "ap_hover_throttle":  ("1310",      "ALT HOLD asılı kalma gazı"),
    "small_angle":        ("90",        "bu açının üstünde ARM edilmez"),
}


def port_bul(verilen=None):
    """Uçuş kartını bul. BF kartları ttyACM olarak görünür (STM32 VCP)."""
    if verilen:
        return verilen
    adaylar = sorted(glob.glob("/dev/ttyACM*"))
    if not adaylar:
        return None
    return adaylar[0]


def _oku_sessizlige_kadar(sp, sessizlik=1.2, azami=25.0):
    """Veri akışı `sessizlik` saniye durana kadar oku.

    ⛔ `diff all` çıktısı uzun ve parça parça gelir; sabit bir sleep ile
      okumak çıktının ORTASINDAN keser ve eksik yedek üretir — üstelik
      dosya dolu göründüğü için fark edilmez.
    """
    tampon = bytearray()
    son = time.monotonic()
    bas = son
    while True:
        n = sp.in_waiting
        if n:
            tampon += sp.read(n)
            son = time.monotonic()
        else:
            time.sleep(0.05)
        if time.monotonic() - son > sessizlik and tampon:
            break
        if time.monotonic() - bas > azami:
            break
    return tampon.decode("utf-8", "replace")


def cli_ac(sp):
    """Kartı CLI kipine sok. Betaflight '#' görünce CLI'a girer."""
    sp.reset_input_buffer()
    sp.write(b"#")
    sp.flush()
    yanit = _oku_sessizlige_kadar(sp, sessizlik=0.8, azami=6.0)
    return ("CLI" in yanit or "#" in yanit), yanit


def komut(sp, satir, sessizlik=1.2, azami=25.0):
    sp.write((satir + "\r\n").encode())
    sp.flush()
    return _oku_sessizlige_kadar(sp, sessizlik, azami)


def al(a):
    port = port_bul(a.port)
    if not port:
        print("⛔ Uçuş kartı bulunamadı (/dev/ttyACM* yok).")
        print("   USB kablosunu UÇUŞ KARTINA tak (ESP32'ye değil).")
        print("   Takılıyken tekrar bak:  ls /dev/ttyACM*")
        return 1
    print("  port      : %s" % port)
    sp = serial.Serial(port, 115200, timeout=0.2)
    time.sleep(0.4)

    tamam, yanit = cli_ac(sp)
    if not tamam:
        print("⛔ CLI'a girilemedi. Kartın Betaflight olduğundan emin ol.")
        print("   Gelen: %r" % yanit[:200])
        sp.close()
        return 1
    print("  CLI       : açıldı")

    surum = komut(sp, "version", sessizlik=0.8, azami=8.0)
    surum_satiri = ""
    for s in surum.splitlines():
        if s.startswith("# Betaflight"):
            surum_satiri = s.strip()
            break
    print("  sürüm     : %s" % (surum_satiri or "(okunamadı)"))

    print("  `diff all` alınıyor…")
    cikti = komut(sp, "diff all", sessizlik=2.0, azami=60.0)
    # ⛔ `exit` kartı YENİDEN BAŞLATIR ama HİÇBİR ŞEY KAYDETMEZ.
    #   Yedek salt-okunur olsun diye `save` ASLA gönderilmiyor.
    sp.write(b"exit\r\n")
    sp.flush()
    time.sleep(0.3)
    sp.close()

    satirlar = [s.rstrip() for s in cikti.splitlines()]
    # komut yankısını ve boş baş kısmı at
    while satirlar and ("diff all" in satirlar[0] or not satirlar[0].strip()):
        satirlar.pop(0)

    if len(satirlar) < 20:
        print("⛔ Çıktı şüpheli derecede kısa (%d satır). Yedek YAZILMADI."
              % len(satirlar))
        print(cikti[:500])
        return 1

    atilan = []
    tutulan = []
    for s in satirlar:
        cip = s.strip()
        if not a.ham and any(cip.startswith("set " + k) or
                             cip.startswith(k) for k in DONANIMA_OZEL):
            atilan.append(cip)
            continue
        tutulan.append(s)

    os.makedirs(YEDEK_DIZIN, exist_ok=True)
    ad = a.dosya or os.path.join(
        YEDEK_DIZIN, "bf_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
    with open(ad, "w") as f:
        f.write("# ---------------------------------------------------------\n")
        f.write("# BETAFLIGHT YEDEĞİ  %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        f.write("# %s\n" % (surum_satiri or "sürüm okunamadı"))
        f.write("# kaynak port: %s\n" % port)
        if atilan:
            f.write("# DONANIMA ÖZEL %d satır ÇIKARILDI (yeni kartta\n"
                    "#   yeniden kalibre edilecek):\n" % len(atilan))
            for s in atilan:
                f.write("#   %s\n" % s)
        f.write("# ---------------------------------------------------------\n")
        f.write("\n".join(tutulan))
        f.write("\n")

    print()
    print("  ✔ YEDEK YAZILDI: %s" % ad)
    print("    %d satır tutuldu, %d donanıma özel satır çıkarıldı"
          % (len(tutulan), len(atilan)))
    print()

    # ---- kritik satır denetimi ----
    govde = "\n".join(tutulan)
    print("  KRİTİK AYAR DENETİMİ")
    eksik = 0
    for anahtar, niye in KRITIK.items():
        n = len(re.findall(r"(?m)^\s*" + re.escape(anahtar), govde))
        if n:
            print("    ✔ %-20s %d satır   (%s)" % (anahtar.strip(), n, niye))
        else:
            print("    ⛔ %-20s YOK        (%s)" % (anahtar.strip(), niye))
            eksik += 1
    if eksik:
        print()
        print("  ⚠ %d kritik ayar yedekte YOK. Bu, o ayarın kartta FABRİKA"
              % eksik)
        print("    değerinde olduğu anlamına gelir (diff yalnız FARKLARI")
        print("    basar). Yeni kartta da fabrika değerinde olacağı için")
        print("    sorun OLMAYABİLİR — ama AUX satırı eksikse ciddi sorundur.")
    return 0


def yukle(a):
    yol = a.yukle
    if not os.path.exists(yol):
        print("⛔ dosya yok: %s" % yol)
        return 1
    with open(yol) as f:
        ham = f.read()
    satirlar = [s.strip() for s in ham.splitlines()]
    satirlar = [s for s in satirlar if s and not s.startswith("#")]
    if not satirlar:
        print("⛔ dosyada uygulanacak satır yok")
        return 1

    port = port_bul(a.port)
    if not port:
        print("⛔ Uçuş kartı bulunamadı (/dev/ttyACM* yok).")
        return 1

    print("=" * 70)
    print("  GERİ YÜKLEME")
    print("=" * 70)
    print("  dosya : %s" % yol)
    print("  satır : %d" % len(satirlar))
    print("  port  : %s" % port)
    print()
    if not a.onayla:
        print("  ⛔ KURU ÇALIŞMA (hiçbir şey yazılmadı).")
        print("     Gerçekten yazmak için sona `--onayla` ekle.")
        print()
        print("  İlk 15 satır:")
        for s in satirlar[:15]:
            print("    %s" % s)
        return 0

    sp = serial.Serial(port, 115200, timeout=0.2)
    time.sleep(0.4)
    tamam, yanit = cli_ac(sp)
    if not tamam:
        print("⛔ CLI'a girilemedi: %r" % yanit[:200])
        sp.close()
        return 1
    print("  CLI: açıldı")

    hatalar = []
    for i, s in enumerate(satirlar, 1):
        y = komut(sp, s, sessizlik=0.25, azami=5.0)
        if re.search(r"(?i)invalid|unknown|error|not found", y):
            hatalar.append((i, s, " ".join(y.split())[:120]))
            print("  ⛔ %4d  %s" % (i, s))
            print("         -> %s" % hatalar[-1][2])
        elif i % 25 == 0:
            print("  … %d/%d" % (i, len(satirlar)))

    print()
    if hatalar:
        print("  ⚠ %d satır KABUL EDİLMEDİ (üstte listelendi)." % len(hatalar))
        print("    Genelde sebebi: yeni kartın Betaflight sürümü farklı.")
        print("    O ayarları elle gözden geçir; özellikle `aux` satırları.")
    else:
        print("  ✔ Bütün satırlar kabul edildi.")

    print()
    print("  `save` gönderiliyor — kart yeniden başlayacak…")
    sp.write(b"save\r\n")
    sp.flush()
    time.sleep(2.0)
    sp.close()
    print("  ✔ KAYDEDİLDİ.")
    print()
    print("  ⛔⛔ ŞİMDİ YENİ KARTTA ELLE YAPILACAKLAR:")
    print("     1. İVMEÖLÇER kalibrasyonu (araç DÜZ zeminde, hareketsiz)")
    print("     2. MANYETOMETRE kalibrasyonu (metalden uzakta)")
    print("     3. PİL gerilim ölçeği (vbat) doğrulaması")
    print("     4. ELRS alıcısını kumandaya BIND et")
    print("     5. Motor dönüş yönleri ve pervane yönü kontrolü")
    return 0


def dogrula(a):
    """Kritik ayarları karttan `get` ile TEK TEK oku ve beklenenle kıyasla.

    ⛔ NİYE AYRI BİR KİP: `diff all` yalnız fabrika ayarından FARKLI
      olanları basar. Bizim bağlı olduğumuz ayarların çoğu fabrika
      değeriyle AYNI olduğu için yedekte HİÇ GÖRÜNMEZ. Yeni kartın
      Betaflight sürümü farklıysa o fabrika değeri BAŞKA olabilir ve
      bunu yedeğe bakarak ANLAYAMAYIZ. Bu yüzden karta doğrudan sorulur.
    """
    port = port_bul(a.port)
    if not port:
        print("⛔ Uçuş kartı bulunamadı (/dev/ttyACM* yok).")
        return 1
    sp = serial.Serial(port, 115200, timeout=0.2)
    time.sleep(0.4)
    tamam, yanit = cli_ac(sp)
    if not tamam:
        print("⛔ CLI'a girilemedi: %r" % yanit[:200])
        sp.close()
        return 1
    surum = komut(sp, "version", sessizlik=0.8, azami=8.0)
    for x in surum.splitlines():
        if x.startswith("# Betaflight"):
            print("  sürüm: %s" % x.strip())
            break
    print()
    kotu = 0
    for k, (bek, niye) in BEKLENEN.items():
        y = komut(sp, "get %s" % k, sessizlik=0.5, azami=6.0)
        deger = None
        for x in y.splitlines():
            m = re.match(r"^\s*%s\s*=\s*(\S+)" % re.escape(k), x)
            if m:
                deger = m.group(1)
                break
        if deger is None:
            print("  ⛔ %-20s OKUNAMADI            (%s)" % (k, niye))
            kotu += 1
        elif deger.upper() == bek.upper():
            print("  ✔ %-20s %-12s        (%s)" % (k, deger, niye))
        else:
            print("  ⛔ %-20s %-12s BEKLENEN %s  (%s)"
                  % (k, deger, bek, niye))
            kotu += 1
    sp.write(b"exit\r\n")
    sp.flush()
    time.sleep(0.3)
    sp.close()
    print()
    if kotu:
        print("  ⛔ %d ayar beklenenden FARKLI. Düzeltmek için CLI'da:" % kotu)
        print("     set <ad> = <deger>   ->   save")
        return 1
    print("  ✔ Bütün kritik ayarlar beklenen değerde.")
    return 0


def main():
    a = argparse.ArgumentParser(
        description="Betaflight ayarlarını yedekle / geri yükle")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--al", action="store_true", help="yedek al (salt-okunur)")
    g.add_argument("--yukle", metavar="DOSYA", help="yedeği karta yaz")
    g.add_argument("--dogrula", action="store_true",
                   help="kritik ayarları karttan oku ve beklenenle kıyasla")
    a.add_argument("--port", default=None, help="ör. /dev/ttyACM0")
    a.add_argument("--dosya", default=None, help="yedek çıktı yolu")
    a.add_argument("--ham", action="store_true",
                   help="⛔ donanıma özel satırları da tut (önerilmez)")
    a.add_argument("--onayla", action="store_true",
                   help="geri yüklemede GERÇEKTEN yaz")
    a = a.parse_args()
    if a.al:
        return al(a)
    if a.dogrula:
        return dogrula(a)
    return yukle(a)


if __name__ == "__main__":
    sys.exit(main())
