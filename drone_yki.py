#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
DRONE YER KONTROL İSTASYONU — tek giriş noktası
================================================================================
DRONE BİLGİSAYARINDA çalışır. Kurduğu zincir:

  [ELRS seri]  <--CRSF-->  drone           telemetri IN / komut OUT
  [kumanda USB]            pilot çubukları  (varsa; panele göre ÖNCELİKLİ)
  [yakalama kartı]         FPV video        -> YOLO -> kilit ölçütü
  [UDP 47800]              hedef GPS        <- Talon bilgisayarı (5 Hz)
  [yarışma sunucusu]       telemetri 1-2 Hz + hedef + kilit paketi
  [panel :8810]            operatör arayüzü + manuel joystickler

⛔ HİÇBİR ŞEY OTOMATİK ARM ETMEZ. Arm yalnız insandan gelir (fiziksel
   kumanda anahtarı ya da panelde BASILI TUTULAN düğme).

⛔ OTONOM İÇİN DÖRT ŞART: panel OTONOM ister + pilot izin verir +
   güdüm taze setpoint üretir + kumandayla bağ tazedir. Biri düşerse
   anında MANUELE düşer (bkz. gercek/komut.py).

KULLANIM
    python3 reel/drone_yki.py --elrs /dev/ttyUSB0 --kamera 0
    python3 reel/drone_yki.py --sahte            # donanımsız deneme
================================================================================
"""
import argparse
import math
import os
import sys
import threading
import time

KOK = os.path.dirname(os.path.abspath(__file__))
UST = os.path.dirname(KOK)
for p in (KOK, UST):
    if p not in sys.path:
        sys.path.insert(0, p)

from gercek import panel as PANEL                       # noqa: E402
from gercek.baglanti import GercekBaglanti              # noqa: E402
from gercek.dikey import DikeyDongu                     # noqa: E402
from gercek.elrs import ElrsBag                         # noqa: E402
from gercek.hedef import HedefKaynagi, UdpDinleyici     # noqa: E402
from gercek.kayit import Kayitci                       # noqa: E402
from gercek.rtl import Rtl                             # noqa: E402
from gercek.dikey_inis import DikeyInis                # noqa: E402
from gercek.kamera_yakala import Kamera, KameraCfg      # noqa: E402
from gercek.komut import KomutSureci                    # noqa: E402
from gercek.kumanda import Kumanda                      # noqa: E402
from gercek.skydagger import SkydaggerBag, SkydaggerCfg  # noqa: E402
from gercek.sunucu import SunucuIstemcisi, SunucuCfg    # noqa: E402


def _arg():
    a = argparse.ArgumentParser(description="Avcı drone yer kontrol istasyonu")
    a.add_argument("--bag", default=os.environ.get("DOW_BAG", "skydagger"),
                   choices=("skydagger", "crsf"),
                   help="skydagger = komitenin ESP32 backend'i (VARSAYILAN); "
                        "crsf = doğrudan seri CRSF (yedek yol)")
    a.add_argument("--sky-host", default=SkydaggerCfg.HOST)
    a.add_argument("--sky-tasima", default=SkydaggerCfg.TASIMA,
                   choices=("udp", "tcp"), help="RC yolu (rehber §8.3)")
    a.add_argument("--elrs", default=os.environ.get("DOW_ELRS_PORT", ""),
                   help="(yalnız --bag crsf) ELRS seri portu")
    a.add_argument("--baud", type=int, default=int(
        os.environ.get("DOW_ELRS_BAUD", 420000)),
        help="(yalnız --bag crsf) CRSF baud")
    a.add_argument("--kamera", default=os.environ.get("DOW_KAM_KAYNAK", "0"))
    a.add_argument("--port", type=int, default=8810, help="panel portu")
    a.add_argument("--gorsel", action="store_true",
                   help="YOLO + görsel güdümü aç (model gerekir)")
    a.add_argument("--kayit-yok", action="store_true",
                   help="uçuş kaydını KAPAT (varsayılan: açık)")
    a.add_argument("--kayit-hz", type=float, default=10.0,
                   help="uçuş kaydı satır hızı (varsayılan 10 Hz)")
    a.add_argument("--sunucu", default="", help="yarışma sunucusu adresi")
    a.add_argument("--hz", type=float, default=50.0, help="güdüm döngü hızı")
    a.add_argument("--sahte", action="store_true",
                   help="donanımsız deneme (seri port ve kamera aranmaz)")
    return a.parse_args()


class _SahtePort:
    def __init__(self):
        self.in_waiting = 0
        self.n = 0

    def write(self, b):
        self.n += 1

    def read(self, n=0):
        return b""

    def close(self):
        pass


def main():
    a = _arg()
    print("=" * 70)
    print("  AVCI DRONE — YER KONTROL İSTASYONU")
    print("=" * 70)

    # ---------------- 1) ELRS bağı ----------------
    # ⛔ SIRA ÖNEMLİ: --sahte EN ÖNDE. `--bag` varsayılanı "skydagger"
    #   olduğu için, skydagger dalı önce gelirse `--sahte` HİÇ ULAŞILMAZ
    #   olur: donanımsız deneme backend arar, bulamaz ve çıkış 2 verir.
    #   (29 Ağu 2026'da yakalandı — README'deki "donanımsız deneme" yolu
    #   fiilen kırıktı.)
    if a.sahte:
        bag = ElrsBag(sahte_port=_SahtePort())
        bag.ac()
        print("  ELRS      : SAHTE (donanımsız deneme)")
    elif a.bag == "skydagger":
        # ⭐ KOMİTENİN RESMÎ YOLU (Skydagger rehberi v2.0):
        #    bizim yazılım --RC_US--> backend --USB--> ESP32 --tel--> ELRS TX
        #    ⛔ Backend'i BİZ başlatmayız; operatör konsoldan /connect ve
        #      EXTERNAL yapar (rehber §8: "harici script kurulum komutu
        #      göndermez"). Biz yalnız RC_US basar, telemetri okuruz.
        SkydaggerCfg.HOST = a.sky_host
        SkydaggerCfg.TASIMA = a.sky_tasima
        bag = SkydaggerBag()
        if not bag.ac():
            print("⛔ %s" % bag.hata)
            print("   SIRA: backend'i başlat -> /connect -> RC_ENABLE ->")
            print("         (modül MAVİ) -> STOP -> EXTERNAL -> sonra bu program")
            return 2
        print("  BAĞ       : SKYDAGGER  %s:%s  (RC=%s, telemetri=TCP)"
              % (a.sky_host, SkydaggerCfg.UDP_PORT if a.sky_tasima == "udp"
                 else SkydaggerCfg.TCP_PORT, a.sky_tasima.upper()))
        print("              ⛔ İlk %.0f s YALNIZ SAFE basılacak (rehber §8) —"
              % SkydaggerCfg.GUVENLI_SURE_S)
        print("                 bu sırada modülün MAVİ ışığını doğrula.")
    else:
        if not a.elrs:
            print("⛔ --elrs verilmedi. Portu bulmak için:")
            print("     ls -l /dev/serial/by-id/   ·   ls /dev/ttyUSB* /dev/ttyACM*")
            print("   Donanımsız denemek için:  --sahte")
            return 2
        bag = ElrsBag(port=a.elrs, baud=a.baud)
        if not bag.ac():
            print("⛔ ELRS portu açılamadı: %s" % bag.hata)
            print("   · kullanıcı `dialout` grubunda mı?  sudo usermod -aG dialout $USER")
            print("   · ModemManager kapalı mı?  sudo systemctl disable --now ModemManager")
            print("   · baud: CH340 yongaları 420000'i desteklemez, 400000 dene")
            return 2
        print("  ELRS      : %s @ %d baud" % (a.elrs, a.baud))

    # ---------------- 2) kumanda ----------------
    # ⛔ NESNE ASLA ATILMAZ. Eskiden `kmd = None` yapıyordum ve o an takılı
    #   olmayan kumanda BİR DAHA ARANMIYORDU. Sahada sıra hep şudur: önce
    #   yazılım açılır, sonra donanım toplanır — yani kumanda neredeyse
    #   HER ZAMAN sonradan takılır. Hakem `hazir` False iken 2 s'de bir
    #   yeniden dener (KomutCfg.KMD_ARA_S).
    kmd = Kumanda()
    if kmd.ac():
        print("  KUMANDA   : %s (%d eksen)" % (kmd.ad, kmd.n_eksen))
    else:
        print("  KUMANDA   : şu an yok — panelin sanal çubukları kullanılır")
        print("              (%s)" % kmd.hata)
        print("              ⭐ SONRADAN TAKILIRSA kendiliğinden yakalanır")
        print("              ⚠ EdgeTX: SYS → Hardware → USB Mode = Joystick")

    # ---------------- 3) hakem ----------------
    # ⛔ ÖLÜ DAL SİLİNDİ (§5.12): `kmd` artık ASLA None olmuyor (sıcak takma
    #   için nesne korunuyor), dolayısıyla `if kmd is None:` hiç çalışmıyordu.
    #   İçindeki `VETO_ZORUNLU = True` zaten varsayılandı — davranış aynı.
    #   Otonom izni: kumanda takılıysa onun anahtarı, değilse panelin
    #   `izin` alanı. İkisi de aynı bayrağı besler.
    ks = KomutSureci(bag, kmd)

    # ---------------- 4) hedef kaynağı ----------------
    hedef = HedefKaynagi()
    # ⛔⛔ YARIŞMADA UDP DİNLEYİCİSİ KAPALI — ENJEKSİYON RİSKİ.
    #   `UdpDinleyici` 0.0.0.0:47800'ü dinler; ağdaki HERHANGİ bir makine
    #   oraya hedef paketi yollayabilir ve SON GELEN PAKET KAZANIR.
    #   Bu YAŞANDI (2026-08-30): ağdaki ikinci bir yayıncı yüzünden panel
    #   gerçek hedef yerine başka bir konumu gösterdi.
    #   ⛔ Yarışma alanında ORTAK BİR YEREL AĞA bağlanıyoruz (doküman §2);
    #     orada başka bir takımın yayını hedefimizi kaydırabilir.
    #   Bu yüzden UDP YALNIZ `--deneme` kipinde açılır; yarışmada hedef
    #   YALNIZCA sunucu yanıtından gelir.
    udp = None
    if a.sunucu:
        print("  HEDEF     : YALNIZ yarışma sunucusu yanıtı (UDP kapalı)")
    else:
        udp = UdpDinleyici(hedef)
        if udp.basla():
            print("  HEDEF     : DENEME — UDP :%d dinleniyor" % udp.port)
        else:
            print("  HEDEF     : ⛔ UDP açılamadı: %s" % udp.hata)

    # ---------------- 5) araç bağlantısı ----------------
    gb = GercekBaglanti(bag, komut_sureci=ks, hedef_kaynak=hedef)

    # ---------------- 6) güdüm ----------------
    from dow.ayarlar import Ayar
    from dow import ana
    from dow.gudum.cevirici import HizCubukCevirici, CevCfg
    Ayar.GPS_KAYNAK = "gercek"          # ⛔ truth/filtre GERÇEKTE YOK
    Ayar.GORSEL_AKTIF = bool(a.gorsel)
    PANEL._D["gorsel_aktif"] = bool(a.gorsel)

    det = None
    if a.gorsel:
        try:
            from dow.gorus.dedektor import Dedektor
            det = Dedektor()
            print("  DEDEKTÖR  : yüklendi")
        except Exception as e:
            print("  DEDEKTÖR  : ⛔ yüklenemedi (%s) — görsel KAPALI" % e)
            Ayar.GORSEL_AKTIF = False

    dik = DikeyDongu()
    cev = HizCubukCevirici(dikey=dik)
    beyin = ana.Beyin(baglanti=gb, cevirici=cev, dedektor=det)
    # ⭐ SARSINTISIZ DEVİR: hakem kaynak değiştirdiğinde dikey döngü
    #   pilotun O ANKİ çubuğuyla tohumlanır (bkz. gercek/dikey.py::sifirla)
    ks.devir_geri_cagirma = (
        lambda kaynak, thr0: dik.sifirla(thr0) if kaynak == "OTONOM"
        else dik.durdur())
    print("  ÇEVİRİCİ  : MODEL=%s  ACI_MAX=%.0f  Y_ISARET=%+.1f"
          % (CevCfg.MODEL, CevCfg.MAX_YATIS_DEG, CevCfg.Y_ISARET))
    if CevCfg.MODEL != "aci":
        print("              ⚠ GERÇEK ARAÇ İÇİN 'aci' OLMALI:")
        print("                export DOW_CEV_MODEL=aci DOW_CEV_ACI_MAX=60")

    # ---------------- 7) kamera ----------------
    # ⛔ SAHTE KİPTE DE KAMERA AÇILABİLMELİ (30 Ağu 2026).
    #   Eskiden `--sahte` kamerayı HİÇ açmıyordu; görüş yolu (kamera ->
    #   dedektör -> kutu -> panel) yalnız tam donanımla sınanabiliyordu.
    #   Oysa dizüstü kamerasıyla bile boru hattının AKTIĞI doğrulanabilir.
    #   Kural: `--kamera` AÇIKÇA verilmişse sahte kipte de açılır.
    kam = None
    _kam_istendi = ("--kamera" in sys.argv)
    if (not a.sahte) or _kam_istendi:
        KameraCfg.KAYNAK = a.kamera
        kam = Kamera()
        if kam.ac():
            time.sleep(0.5)
            w, h = kam.cozunurluk()
            print("  KAMERA    : %s  %dx%d" % (a.kamera, w, h))
            # ⛔⛔ SESSİZ %50 HATA KAPISI.
            #   F_PX ve CX/CY, kalibrasyonun YAPILDIĞI çözünürlüğe bağlıdır.
            #   Kart 1280x720 verirken 1920x1080 sabitleri kullanılırsa aynı
            #   hedef 40 px yerine 27 px görünür ve menzil 25 m yerine 37 m
            #   denir. Hiçbir yerde patlamaz; güdüm sadece yanlış nişan alır.
            from dow.gorus import kamera as _KAM
            if w and h and (int(w) != _KAM.IMG_W or int(h) != _KAM.IMG_H):
                olcek = float(w) / _KAM.IMG_W if _KAM.IMG_W else 0.0
                print("")
                print("  " + "=" * 66)
                print("  ⛔ ÇÖZÜNÜRLÜK UYUŞMAZLIĞI — GÖRSEL GÜDÜM YANLIŞ ÖLÇER")
                print("  " + "=" * 66)
                print("     kamera veriyor   : %dx%d" % (w, h))
                print("     optik kalibrasyon: %dx%d  (F_PX=%.1f)"
                      % (_KAM.IMG_W, _KAM.IMG_H, _KAM.F_PX))
                print("     menzil hatası    : ~%.0f%% (ölçek %.3f)"
                      % (abs(1.0 / olcek - 1.0) * 100 if olcek else 0.0, olcek))
                print("")
                print("     ÇÖZÜM — biri:")
                print("       a) kartı kalibrasyon çözünürlüğüne zorla:")
                print("          export DOW_KAM_W=%d DOW_KAM_H=%d"
                      % (_KAM.IMG_W, _KAM.IMG_H))
                print("       b) bu çözünürlükte YENİDEN kalibre et:")
                print("          python3 gercek/kamera_ayari.py")
                print("  " + "=" * 66 + "\n")
        else:
            print("  KAMERA    : ⛔ %s" % kam.hata)
            kam = None

    # ---------------- 8) yarışma sunucusu ----------------
    sv = None
    adres = a.sunucu or (SunucuCfg.ADRES if os.environ.get("DOW_SUNUCU") else "")
    if adres:
        SunucuCfg.ADRES = adres
        sv = SunucuIstemcisi(hedef, lambda: _telemetri(gb, ks, beyin))
        ok, mesaj = sv.giris()
        print("  SUNUCU    : %s — %s" % (adres, mesaj))
        sv.basla()
    else:
        print("  SUNUCU    : kapalı (--sunucu ile aç)")

    # ---------------- 9) panel ----------------
    PANEL.kur(kamera=kam, komut=ks, baglanti=gb, hedef=hedef,
              sunucu=sv, beyin=beyin, dikey=dik)
    p = PANEL.baslat(a.port)
    print("  PANEL     : http://127.0.0.1:%d" % p)
    print("=" * 70)
    print("  ⛔ ARM yalnız insandan gelir. Otonom için panelde OTONOM +")
    print("     kumandada izin anahtarı BİRLİKTE gerekir.")
    print("  Çıkmak için Ctrl+C")
    print("=" * 70)

    # ---------------- 9a) RTL — EVE DÖN ----------------
    # ⛔ GÜDÜMLE AYNI ÇEVİRİCİ: çubuk eşlemesi tek yerden gelmeli, yoksa
    #   RTL ile otonom güdüm aynı hız isteğine FARKLI çubuk üretir.
    rtl = Rtl(beyin.cev)
    PANEL._D["rtl"] = rtl
    inis = DikeyInis()
    PANEL._D["inis"] = inis
    print("  RTL       : hazır (irtifa %.0f m, hız %.0f m/s)"
          % (rtl.cfg.IRTIFA_M, rtl.cfg.HIZ_MS))

    # ---------------- 9b) uçuş kaydı ----------------
    # ⛔ HER ZAMAN AÇIK. İlk otonom denemeden sonra "ne oldu" sorusunu
    #   cevaplayacak veri, ancak o an kaydedilmişse vardır. Kapatmak için
    #   --kayit-yok. Yazma ayrı iplikte; güdüm döngüsünü BEKLETMEZ.
    kayitci = None
    if not a.kayit_yok:
        kayitci = Kayitci(hz=a.kayit_hz, uretici=PANEL._durum)
        if kayitci.basla():
            PANEL._D["kayit"] = kayitci
            print("  KAYIT     : %s  (%.0f Hz)" % (kayitci.yol, a.kayit_hz))
        else:
            print("  KAYIT     : ⛔ açılamadı — %s" % kayitci.hata)
            kayitci = None
    else:
        print("  KAYIT     : kapalı (--kayit-yok)")

    ks.basla()                     # 50 Hz CRSF yazıcısı kendi ipliğinde

    # ---------------- 10) ana döngü ----------------
    periyot = 1.0 / max(1.0, a.hz)
    t0 = time.monotonic()
    sonraki = time.monotonic()
    son_kare_sayac = -1
    try:
        while True:
            simdi = time.monotonic()
            t = simdi - t0
            gb.pompala()                       # CRSF telemetri -> alanlar

            # --- görüş ---
            if kam is not None:
                kare, kare_t, sayac = kam.son_kare()
                if kare is not None and sayac != son_kare_sayac:
                    son_kare_sayac = sayac
                    _gorus(beyin, kare, t, kare_t - t0, a.gorsel)

            # --- güdüm ya da RTL ---
            # ⛔ RTL GÜDÜMÜN YERİNE GEÇER, yanında değil: ikisi aynı anda
            #   `otonom_yaz` çağırsaydı son yazan kazanırdı ve araç iki
            #   hedef arasında salınırdı.
            # ⛔ EK KANALLAR TEK YERDE TEMİZLENİR: iniş kapalıysa uçuş
            #   kartının kipleri de kapanmalı. Bunu dalların İÇİNE koymak,
            #   yeni bir dal eklendiğinde atlanmasına yol açardı.
            if not inis.aktif and ks.aux:
                ks.aux_yaz({})

            # ⛔⛔ DİKEY İNİŞ TELEMETRİYE BAĞLI DEĞİL — kasten `gb.canli()`
            #   kapısının DIŞINDA. Sebebi: bu iniş hiçbir ölçüm kullanmaz;
            #   yalnız iki kanalı kaldırıp gaz çubuğunu indirir, irtifayı
            #   ve konumu uçuş kartı KENDİ barometresi/GPS'i ile tutar.
            #   Telemetri (geri bağ) ölüp RC (ileri bağ) sağlamken indirmek
            #   TAM DA istediğimiz şeydir; onu kapının içine koymak,
            #   özelliği en çok gerektiği anda kapatırdı.
            # ⛔ PİLOT ÇUBUKLA DEVRALDIYSA İNİŞ DE DURUR. Yoksa iniş
            #   "aktif" kalır ve operatör sonra OTONOM'a bastığında araç
            #   beklenmedik şekilde alçalmaya KALDIĞI YERDEN devam eder.
            if inis.aktif and (ks.kip != "OTONOM" or ks.pilot_devraldi):
                inis.dur()
                ks.aux_yaz({})

            if inis.aktif:
                thr, pit, rol, yw = inis.adim(periyot)
                ks.aux_yaz(inis.aux())
                ks.otonom_yaz(thr, pit, rol, yw)
            elif gb.canli():
                if rtl.aktif:
                    try:
                        thr, pit, rol, yw = rtl.adim(
                            gb.konum(), gb.hiz_vektoru(),
                            gb.yonelim()[2], periyot)
                        ks.otonom_yaz(thr, pit, rol, yw)
                    except Exception as e:
                        # ⛔ RTL PATLARSA SESSİZ KALMA: otonom setpoint
                        #   akmayı keser, hakem dört şarttan birini
                        #   kaybeder ve komut çubuklara düşer.
                        rtl.dur()
                        rtl.sebep = "hata: %s" % e
                        print("  ⛔ RTL durdu: %s" % e)
                else:
                    beyin.adim(t, periyot)
            sonraki += periyot
            uyku = sonraki - time.monotonic()
            time.sleep(uyku if uyku > 0 else 0.0)
            if uyku < -0.5:
                sonraki = time.monotonic()
    except KeyboardInterrupt:
        print("\n  kapatılıyor...")
        # ⛔ KAPANIŞ KESİNTİYE UĞRAMAMALI: ikinci Ctrl+C burada traceback
        #   basıp kalan temizliği (araç komutlarını bırakma) ATLIYORDU.
        try:
            if kayitci is not None:
                kayitci.dur()
                print("  KAYIT     : %d satır -> %s"
                      % (kayitci.n_satir, kayitci.yol))
        except KeyboardInterrupt:
            print("  (kayıt kapanışı kesildi)")
    finally:
        ks.dur()
        if sv:
            sv.dur()
        if udp is not None:
            udp.dur()
        if kam:
            kam.kapat()
        gb.kapat()
        PANEL.durdur()
        print("  kapandı. ⛔ Aracı havada bırakma — pilot indirsin.")
    return 0


_DET_RENK = os.environ.get("DOW_DET_RENK", "bgr").strip().lower()
if _DET_RENK not in ("bgr", "rgb"):
    raise ValueError("DOW_DET_RENK='%s' — 'bgr' ya da 'rgb' olmalı" % _DET_RENK)


def _gorus(beyin, kare, t, kare_t, gorsel_acik):
    """Kareyi dedektöre ver ve panel için kilit ölçütünü hesapla."""
    import cv2
    from dow.ayarlar import Ayar
    from dow.gudum.kilit import KilitDurumu
    if not hasattr(_gorus, "_olcut"):
        _gorus._olcut = KilitDurumu(Ayar)
    kabul = None
    if gorsel_acik and beyin.det is not None:
        # ⛔⛔ KANAL SIRASI — SESSİZ TAM ISKA (2026-08-29'da ölçüldü)
        #
        #   ultralytics, numpy dizisini BGR kabul eder (cv2.imread gibi).
        #   Buraya kadar kare zaten BGR'dir. Eskiden burada BGR2RGB
        #   çevriliyordu ve o ÇEVİRİ, sim modeli `talon_v3` için doğruydu:
        #   o model aynı çevrilmiş kareler üzerinde eğitilmişti, yani takas
        #   eğitime GÖMÜLÜ.
        #
        #   Gerçek görüntüyle eğitilen `tayarti_v1` NORMAL eğitildi ve BGR
        #   bekler. Takas edilince turuncu uçak maviye döner. ÖLÇÜLDÜ, aynı
        #   kare, imgsz 640:
        #        BGR -> güven 0.700   ✔
        #        RGB -> güven 0.000   ✗ HİÇBİR ŞEY
        #   Panelde "tespit yok" görünüyordu; model kusursuz çalışıyordu.
        #
        #   Bu yüzden kanal sırası ARTIK BİR AYAR. Varsayılan "bgr"
        #   (ultralytics'in normal sözleşmesi); sim modeline dönersen
        #   DOW_DET_RENK=rgb ver.
        girdi = kare if _DET_RENK == "bgr" else cv2.cvtColor(
            kare, cv2.COLOR_BGR2RGB)
        kabul = beyin.gorsel_tik(girdi, t, kare_t)
    bilgi = _gorus._olcut.guncelle(t, kabul)
    PANEL._D["son_kutu"] = kabul[:4] if kabul else None
    # ⭐ HAM TESPİT — güdüm reddetse bile panelde görünsün. Model çalışıyor
    #   mu sorusunu ekrandan cevaplayabilmek için (bkz. dow/ana.py kancası).
    hk = getattr(beyin, "_ham_kutu", None)
    # ⛔ HER ZAMAN GÖNDER. Kabul edilen kutu varsa panel yeşili çizer ve
    #   hamı çizmez; ama MENZİL hesabı için ham kutu yine lazım — hedef
    #   kaç metrede olursa olsun ekranda bir sayı görünsün.
    PANEL._D["ham_kutu"] = list(hk[:5]) if hk else None
    PANEL._D["ham_sebep"] = getattr(beyin, "_ham_sebep", "")
    PANEL._D["olcut"] = {"bu_kare": bool(bilgi.get("kilit_bu")),
                         "kilit_s": round(bilgi.get("kilit_s", 0.0), 2),
                         "sebep": bilgi.get("kilit_sebep", ""),
                         "saglandi": bool(_gorus._olcut.saglandi)}


def _telemetri(gb, ks, beyin):
    """Yarışma sunucusuna gönderilecek paket (haberleşme dokümanı §7.1)."""
    from dow.ayarlar import Ayar
    x, y, z = gb.konum()
    r, p, yw = gb.yonelim()
    kutu = PANEL._D.get("son_kutu") or (0, 0, 0, 0)
    olcut = PANEL._D.get("olcut") or {}
    enlem, boylam, _ = (gb.cerceve.dereceye(x, y, z) if gb.cerceve.hazir
                        else (0.0, 0.0, 0.0))
    return {
        "takim_no": SunucuCfg.TAKIM_NO,
        "enlem": round(enlem, 7), "boylam": round(boylam, 7),
        "irtifa": round(z, 1),
        "dikilme": round(math.degrees(p), 1),
        "yonelme": round(math.degrees(yw) % 360.0, 1),
        "yatis": round(math.degrees(r), 1),
        "hiz": round(gb.hiz(), 1),
        # ⛔ mod: 1 = otonom. Hakem GERÇEKTE otonom komut mu gönderiyor,
        #   onu söyler — panelde ne seçili olduğunu değil.
        "mod": 1 if ks.durum.get("kaynak") == "OTONOM" else 0,
        "kilitlenme": 1 if olcut.get("saglandi") else 0,
        "hedef_x_merkezi": int(kutu[0]), "hedef_y_merkezi": int(kutu[1]),
        "hedef_genislik": int(kutu[2]), "hedef_yukseklik": int(kutu[3]),
    }


if __name__ == "__main__":
    sys.exit(main())
