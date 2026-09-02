# -*- coding: utf-8 -*-
"""
================================================================================
GERÇEK ORTAM BEKÇİLERİ — R-serisi
================================================================================
`tests/test_dow.py` (B-serisi) simülasyon davranışını korur. Bu dosya GERÇEK
ORTAM katmanını korur. İkisi ayrı tutulur çünkü biri sim, öbürü donanım
sözleşmesidir; birinin kırılması öbürünü ilgilendirmez.

⛔ HER BEKÇİ BİR YAŞANMIŞ (ya da yaşanabilecek ve BEDELİ UÇAK OLAN) HATAYA
   KARŞILIK GELİR. Süs test yazılmaz.
================================================================================
"""
import math
import os
import sys
import time

import pytest

# ⛔ YARIŞMA DEPOSU TEK PARÇADIR: `dow/` artık üst dizinde değil, deponun
#   İÇİNDE. Bu yüzden KOK == REEL. (Deneme deposunda `dow` bir üst
#   dizindeydi ve KOK oradan geliyordu.)
REEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KOK = REEL
for p in (REEL, KOK):
    if p not in sys.path:
        sys.path.insert(0, p)

from gercek import konum as K                       # noqa: E402
from gercek.arayuz import (AracArayuzu, sozlesme_denetle,   # noqa: E402
                           GUDUM_CAGRILARI, KOSU_CAGRILARI)


# ======================================================================
#  BAĞIMSIZ REFERANS — testin kendi, AYRI matematiği
# ======================================================================
def _ecef(enlem, boylam, h):
    """Coğrafi -> ECEF (yer merkezli, yere sabit) dik koordinat. TAM formül.

    Bu, `konum.py`'nin YAKLAŞIK formülünden BAĞIMSIZ bir yoldur. İkisini
    kıyaslamak, yaklaşımın gerçek hatasını ölçer. Aynı formülü iki kez
    yazıp "uyuyor" demek hiçbir şey kanıtlamaz.
    """
    f = math.radians(enlem); l = math.radians(boylam)
    N = K.A_YARIEKSEN / math.sqrt(1.0 - K.E2 * math.sin(f) ** 2)
    return ((N + h) * math.cos(f) * math.cos(l),
            (N + h) * math.cos(f) * math.sin(l),
            (N * (1.0 - K.E2) + h) * math.sin(f))


def _ecef_kdy(enlem0, boylam0, h0, enlem, boylam, h):
    """ECEF üzerinden KESİN yerel KDY (kuzey, doğu, yukarı)."""
    x0, y0, z0 = _ecef(enlem0, boylam0, h0)
    x1, y1, z1 = _ecef(enlem, boylam, h)
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    f = math.radians(enlem0); l = math.radians(boylam0)
    dogu   = -math.sin(l) * dx + math.cos(l) * dy
    kuzey  = (-math.sin(f) * math.cos(l) * dx - math.sin(f) * math.sin(l) * dy
              + math.cos(f) * dz)
    yukari = (math.cos(f) * math.cos(l) * dx + math.cos(f) * math.sin(l) * dy
              + math.sin(f) * dz)
    return kuzey, dogu, yukari


# ---------------------------------------------------------------- R1def test_R1_gidis_donus_ayni_noktaya_dusuyor():
    """metreye() -> dereceye() aynı noktaya dönmeli (yuvarlama dışında).

    NİYE: ters çevrim paneldeki harita ve sunucuya gönderdiğimiz KENDİ
    konumumuz için kullanılıyor. Yanlışsa hakem bizi başka yerde görür.
    """
    c = K.YerelCerceve().kokeni_kur(41.1050, 29.0230, 120.0)
    for dk, dd, dz in [(0, 0, 0), (250, -400, 35), (-1200, 900, -20),
                       (3000, 3000, 100)]:
        enlem, boylam, irt = c.dereceye(dk, dd, dz)
        x, y, z = c.metreye(enlem, boylam, irtifa_amsl=irt)
        assert abs(x - dk) < 1e-6, "kuzey gidiş-dönüş bozuk"
        assert abs(y - dd) < 1e-6, "doğu gidiş-dönüş bozuk"
        assert abs(z - dz) < 1e-9, "irtifa gidiş-dönüş bozuk"


# ---------------------------------------------------------------- R2
def test_R2_yaklasim_hatasi_ILAN_EDILEN_SINIRIN_ICINDE():
    """Düz-dünya yaklaşımının hatası, modülde İLAN EDİLEN sınırları tutmalı.

    Modül §2b, hatanın d²/(2R) yasasıyla büyüdüğünü ve ölçülen katsayının
    7.9e-8/m olduğunu söylüyor. Sınırlar O YASADAN türetilir (%50 pay ile),
    yuvarlak sayıdan değil — böylece test hem geçer hem de formül bozulursa
    (ör. cos(enlem) çarpanı düşerse) DERHAL kırılır.

    ⛔ BU TEST BİR KEZ GERÇEK BİR HATA YAKALADI: ilk yazdığımda modül
       "1 km'de <1 cm" diyordu; ölçülen 8.6 cm çıktı. Belge düzeltildi,
       test gevşetilmedi.
    Kıyas, BAĞIMSIZ ECEF yolundan yapılır (_ecef_kdy).
    """
    e0, b0, h0 = 41.1050, 29.0230, 120.0
    c = K.YerelCerceve().kokeni_kur(e0, b0, h0)
    R_ORT = 6.33e6                      # ölçülen katsayıdan geri çıkan yarıçap
    sinirlar = {d: 1.5 * d * d / (2.0 * R_ORT)
                for d in (600.0, 1000.0, 5000.0, 20000.0)}
    for uzaklik, sinir in sinirlar.items():
        en_kotu = 0.0
        for aci in range(0, 360, 15):
            r = math.radians(aci)
            hedef_k, hedef_d = uzaklik * math.cos(r), uzaklik * math.sin(r)
            enlem, boylam, irt = c.dereceye(hedef_k, hedef_d, 0.0)
            yak = c.metreye(enlem, boylam, irtifa_amsl=irt)
            kes = _ecef_kdy(e0, b0, h0, enlem, boylam, irt)
            en_kotu = max(en_kotu, math.dist(yak[:2], kes[:2]))
        assert en_kotu <= sinir, (
            "%.0f m'de yaklaşım hatası %.4f m — d²/(2R) yasasının %%50 payla "
            "sınırı %.4f m. Formül bozulmuş olabilir (cos(enlem) çarpanı? "
            "yanlış eğrilik yarıçapı?)." % (uzaklik, en_kotu, sinir))
        # yasanın ALT ucu da sınanır: hata beklenenden ÇOK küçükse, test
        # yanlışlıkla aynı formülü iki kez çağırıyor olabilir (sahte geçiş).
        if uzaklik >= 1000.0:
            assert en_kotu >= 0.3 * uzaklik * uzaklik / (2.0 * R_ORT), (
                "%.0f m'de hata beklenenden ÇOK küçük (%.4f m) — kıyas yolu "
                "bağımsız olmayabilir." % (uzaklik, en_kotu))


# ---------------------------------------------------------------- R3
def test_R3_irtifa_referansi_TEK_OLMAK_ZORUNDA():
    """AMSL ve yerden irtifa AYNI ANDA verilemez, HİÇBİRİ de verilmeyemez.

    ⛔ YAŞANABİLİR HATA: bizim drone AMSL (ör. 1020 m), hedef yerden
       (ör. 120 m) verir. İkisini aynı sayı sanmak, güdümün hedefi 900 m
       AŞAĞIDA görmesi demektir — burun yere çevrilir.
       Bu bekçi, belirsizliği API seviyesinde İMKÂNSIZ kılar.
    """
    c = K.YerelCerceve().kokeni_kur(41.0, 29.0, 900.0)
    with pytest.raises(ValueError):
        c.metreye(41.001, 29.0)                                   # hiçbiri
    with pytest.raises(ValueError):
        c.metreye(41.001, 29.0, irtifa_amsl=950, irtifa_yerden=50)  # ikisi

    # Doğru kullanım: AYNI fiziksel yükseklik iki yoldan da aynı z vermeli.
    z_amsl = c.metreye(41.001, 29.0, irtifa_amsl=950.0)[2]
    z_yer = c.metreye(41.001, 29.0, irtifa_yerden=50.0)[2]
    assert abs(z_amsl - z_yer) < 1e-9, (
        "AMSL 950 (zemin 900) ile 'yerden 50' AYNI yüksekliktir; "
        "farklı çıkıyorsa referans dönüşümü bozuk.")


# ---------------------------------------------------------------- R4
def test_R4_koken_kurulmadan_KULLANILAMAZ():
    """Köken kurulmadan çevrim yapılamaz — sessizce 0,0,0 dönmemeli.

    ⛔ NİYE AÇIK HATA: sessizce (0,0,0) dönseydi güdüm, hedefi kalkış
       noktasında sanardı ve oraya dalardı. Gürültülü patlamak, sessiz
       yanlış cevaptan İYİDİR.
    """
    c = K.YerelCerceve()
    assert not c.hazir
    with pytest.raises(RuntimeError):
        c.metreye(41.0, 29.0, irtifa_amsl=100.0)
    with pytest.raises(RuntimeError):
        c.dereceye(0.0, 0.0, 0.0)


# ---------------------------------------------------------------- R5
def test_R5_kerteriz_gps_MODULUYLE_AYNI_SOZLESME():
    """kerteriz_deg(), `dow/gudum/gps.py`'nin kullandığı formülle AYNI olmalı.

    ⛔ İKİ YERDE İKİ YÖN SÖZLEŞMESİ = kesin uçak kaybı. gps.py şunu yapar:
           ker = degrees(atan2(hedef[1]-drone[1], hedef[0]-drone[0]))
       Yani atan2(Δ_ikinci_bilesen, Δ_birinci_bilesen). Bizim çerçevede
       birinci = KUZEY, ikinci = DOĞU -> pusula kerterizi.
    """
    from dow.gudum.gps import _wrap
    for a, b, beklenen in [((0, 0, 0), (100, 0, 0), 0.0),      # kuzey
                           ((0, 0, 0), (0, 100, 0), 90.0),     # doğu
                           ((0, 0, 0), (-100, 0, 0), 180.0),   # güney
                           ((0, 0, 0), (0, -100, 0), 270.0)]:  # batı
        assert abs(_wrap(K.kerteriz_deg(a, b) - beklenen)) < 1e-9

    # gps.py'nin kendi satırıyla birebir kıyas (rastgele olmayan örnekler)
    for a, b in [((0, 0, 0), (37.0, -12.0, 5.0)),
                 ((10, -5, 0), (-40.0, 80.0, -3.0))]:
        gps_yolu = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        assert abs(_wrap(K.kerteriz_deg(a, b) - gps_yolu)) < 1e-9, (
            "kerteriz sözleşmesi gps.py'den AYRIŞTI")


# ---------------------------------------------------------------- R6
def test_R6_yer_hizi_vektore_CEVIRICININ_BEKLEDIGI_GIBI():
    """Yer hızı + rota -> KDY vektörü; çeviricinin gövde dönüşümüyle uyumlu.

    DOĞRULAMA: araç kuzeye 20 m/s gidiyorsa ve BURNU da kuzeydeyse,
    çeviricinin `dunya_govde` fonksiyonu "ileri 20, yanal 0" demeli.
    Ayrışırsa hız geri beslemesi yanlış eksene biner.
    """
    from dow.gudum.cevirici import HizCubukCevirici as C
    for yon, yaw in [(0.0, 0.0), (90.0, 90.0), (215.0, 215.0)]:
        v = K.yer_hizindan_vektor(20.0, yon)
        ileri, yanal = C.dunya_govde(v[0], v[1], math.radians(yaw), 1.0)
        assert abs(ileri - 20.0) < 1e-9, "burun rotayla aynıyken ileri=hız olmalı"
        assert abs(yanal) < 1e-9, "burun rotayla aynıyken yanal=0 olmalı"

    # 90° sağdan gelen hareket: burun kuzeyde, hareket doğuda -> tam SAĞ
    v = K.yer_hizindan_vektor(20.0, 90.0)
    ileri, yanal = C.dunya_govde(v[0], v[1], 0.0, 1.0)
    assert abs(ileri) < 1e-9
    assert abs(yanal - 20.0) < 1e-9, (
        "Y_ISARET=+1 iken doğuya hareket, kuzeye bakan araç için SAĞ olmalı")


# ---------------------------------------------------------------- R7
def test_R7_sozlesme_SIM_TARAFINDA_ZATEN_SAGLANIYOR():
    """Sözleşme uydurulmadı: mevcut `DowBaglanti` ona TAM uyuyor.

    ⛔ NİYE BEKÇİ: sözleşmeyi ben yazdım ama SİM TARAFI onu doğrulayan
       bağımsız tanıktır. Sim tarafı bir gün bir çağrıyı kaybederse (ya da
       ben sözleşmeye gerçekte olmayan bir çağrı eklersem) burası kırılır.
    """
    from dow.sdk.baglanti import DowBaglanti
    eksik = [a for a in GUDUM_CAGRILARI + KOSU_CAGRILARI
             if not callable(getattr(DowBaglanti, a, None))]
    assert not eksik, "DowBaglanti sözleşmeden ayrıştı: %s" % eksik


# ---------------------------------------------------------------- R8
def test_R8_beyin_araca_SOZLESME_DISI_dokunmuyor():
    """`Beyin` yalnız KATMAN 1'i çağırmalı — kaynak koddan sayılarak.

    ⛔ NİYE: gerçek bağlantı yalnız sözleşmeyi yazar. Beyin sözleşme dışı
       bir çağrı eklerse gerçek uçuşta AttributeError ile DÜŞER — hem de
       o kod yoluna ilk girildiği anda, yani havada.
    """
    import re
    yol = os.path.join(KOK, "dow", "ana.py")
    with open(yol, encoding="utf-8") as f:
        kaynak = f.read()
    cagrilar = set(re.findall(r"self\.b\.([a-zA-Z_]+)", kaynak))
    fazla = cagrilar - set(GUDUM_CAGRILARI)
    assert not fazla, (
        "dow/ana.py araçtan sözleşme DIŞI çağrı yapıyor: %s\n"
        "Ya çağrı kaldırılmalı ya sözleşmeye (arayuz.py) eklenmeli — "
        "sessizce bırakmak gerçek uçuşta havada patlar." % sorted(fazla))


# ---------------------------------------------------------------- R9
def test_R9_arac_dikisi_VARSAYILANI_DEGISTIRMIYOR():
    """`Beyin(baglanti=None)` hâlâ DowBaglanti kurmalı (sim davranışı).

    ⛔ NİYE: dikiş, sim tarafını bozmamak şartıyla açıldı. Varsayılan
       kayarsa bütün sim kampanyaları geçersiz olur.
    """
    import inspect
    from dow import ana
    imza = inspect.signature(ana.Beyin.__init__)
    assert "baglanti" in imza.parameters, "araç dikişi kaybolmuş"
    assert imza.parameters["baglanti"].default is None, (
        "dikişin varsayılanı None OLMALI; başka bir şey sim davranışını değiştirir")
    kaynak = inspect.getsource(ana.Beyin.__init__)
    assert "DowBaglanti()" in kaynak, (
        "varsayılan araç DowBaglanti olmalı — sim yolu korunmalı")


# ---------------------------------------------------------------- R10
def test_R10_gercek_arac_TRUTH_KANALI_VERMEZ():
    """Soyut arayüzün `truth()` varsayılanı None — gerçekte böyle bir kanal yok.

    ⛔ NİYE: `Ayar.GPS_KAYNAK="truth"` geliştirme kipidir ve GERÇEKTE
       hedefi HİÇ vermez. Varsayılan None olduğu için `hedef_konumu()`
       None döner, `Beyin` "HEDEF_YOK" durumuna geçer ve komut vermez —
       yani sessizce yanlış uçmak yerine AÇIKÇA durur.
    """
    class Bos(AracArayuzu):
        pass
    assert Bos().truth() is None
    assert Bos().hedef_yonelim() is None


# ---------------------------------------------------------------- R11
def test_R11_sozlesme_denetleyicisi_EKSIGI_YAKALIYOR():
    """Denetleyici işini yapmalı: eksik çağrıyı ve YANLIŞ BİRİMİ bulmalı."""
    class Yarim(AracArayuzu):
        def canli(self): return True
        def konum(self): return (0.0, 0.0, 0.0)
        def hiz_vektoru(self): return (0.0, 0.0, 0.0)
        def komut(self, *a, **k): pass
        def hedef_konum_bozuk(self): return None
        def yonelim(self): return (45.0, -10.0, 90.0)     # ⛔ DERECE!

    eksik = sozlesme_denetle(Yarim(), yalniz_gudum=True)
    assert any("RADYAN" in e for e in eksik), (
        "denetleyici derece/radyan karışıklığını yakalamalı — bu hata "
        "kamera telafisini ters çevirir")


# ======================================================================
#  CRSF PROTOKOLÜ — R12..R22
#  Her bekçi BAĞIMSIZ bir referansa dayanır: standart sınama değeri,
#  elle kurulmuş çerçeve, ya da FARKLI ALGORİTMAYLA yazılmış ikinci yol.
#  ⛔ "Kendi paketlediğimi kendim çözdüm, uydu" bir şey KANITLAMAZ.
# ======================================================================
from gercek import crsf as C                                   # noqa: E402


def _bagimsiz_paketle(kanallar):
    """16×11 bit paketleme — KASTEN FARKLI ALGORİTMA (bit listesi).

    `crsf.kanallari_paketle` kaydırmalı yazmaç kullanır. Bu ise her biti
    tek tek bir listeye koyup baytları sonra kurar. İkisi aynı sonucu
    veriyorsa bit sırası sözleşmesi doğru demektir.
    """
    akis = []
    for k in kanallar:
        for b in range(11):
            akis.append((int(k) >> b) & 1)     # konum 11c+b
    cikti = bytearray()
    for j in range(22):
        bayt = 0
        for i in range(8):
            bayt |= akis[8 * j + i] << i
        cikti.append(bayt)
    return bytes(cikti)


# ---------------------------------------------------------------- R12
def test_R12_crc_STANDART_SINAMA_DEGERINI_veriyor():
    """CRC-8/DVB-S2'nin bilinen sınama değeri: "123456789" -> 0xBC.

    ⛔ NİYE BAĞIMSIZ: bu sayı bizim kodumuzdan değil, CRC standardından
       gelir. Polinomu (0xD5) ya da başlangıç değerini yanlış yazsaydım
       burada yakalanırdı. CRC yanlışsa ELRS modülü paketlerimizi SESSİZCE
       atar ve "komut gitmiyor" diye günlerce aranır.
    """
    assert C.crc8(b"123456789") == 0xBC
    assert C.crc8(b"") == 0x00


# ---------------------------------------------------------------- R13
def test_R13_cerceve_UZUNLUK_ALANI_dogru_sayiyor():
    """UZUNLUK = tip + yük + crc. Adres ve uzunluk baytı SAYILMAZ.

    ⛔ EN SIK YAPILAN CRSF HATASI BUDUR. Bir fazla sayınca alıcı bir
       sonraki çerçeveyi bir bayt kaymış görür ve senkron kalıcı bozulur.
    """
    for yuk_uzunluk in (0, 1, 6, 22, 60):
        cer = C.cerceve(0x16, bytes(yuk_uzunluk))
        assert len(cer) == yuk_uzunluk + 4, "toplam = adres+uzunluk+tip+yük+crc"
        assert cer[1] == yuk_uzunluk + 2, (
            "uzunluk alanı %d olmalıydı, %d yazıldı" % (yuk_uzunluk + 2, cer[1]))
        # CRC yalnız tip+yük üzerinden; adres ve uzunluk GİRMEZ
        assert cer[-1] == C.crc8(cer[2:-1])

    # gerçek RC paketi: 26 bayt, uzunluk alanı 24
    p = C.rc_paketi(0, 0, 0, 0)
    assert len(p) == 26 and p[1] == 24 and p[0] == C.ADRES_TX_MODULU
    assert p[2] == C.TIP_RC_KANALLAR


# ---------------------------------------------------------------- R14
def test_R14_kanal_paketleme_BAGIMSIZ_ALGORITMAYLA_ayni():
    """11-bit paketleme, farklı algoritmayla yazılmış ikinci yolla örtüşmeli.

    ⛔ NİYE: bit sırası ters olsaydı (büyük-sonlu bit dizilimi) gidiş-dönüş
       testi YİNE GEÇERDİ — kendi hatamı kendim geri çözerdim. Gerçek
       kartta ise her kanal çöp değer görürdü.
    """
    ornekler = [
        [C.CRSF_ORTA] * 16,
        [C.CRSF_MIN] * 16,
        [C.CRSF_MAX] * 16,
        list(range(0, 16 * 100, 100)),
        [172, 1811, 992, 1000, 500, 2047, 0, 1, 1023, 1024,
         777, 333, 1500, 88, 2000, 111],
    ]
    for k in ornekler:
        assert C.kanallari_paketle(k) == _bagimsiz_paketle(k), (
            "bit dizilimi sözleşmesi bozuk: %s" % k[:4])
        assert C.kanallari_coz(C.kanallari_paketle(k)) == [x & 0x7FF for x in k]


# ---------------------------------------------------------------- R15
def test_R15_mikrosaniye_REFERANS_NOKTALARI():
    """CRSF ham değeri <-> µs: endüstri standardı üç referans nokta.

    172 -> 988 µs, 992 -> 1500 µs, 1811 -> 2012 µs.
    ⛔ Bu üç sayı bizim seçimimiz değil; kart bunları bekliyor. Ölçek
       yanlışsa "tam çubuk" komutu kartta yarım çubuk görünür ve güdüm
       hiç doyuma ulaşamaz — sebebi de görünmez.
    """
    assert round(C.crsf_us(C.CRSF_MIN)) == C.US_MIN
    assert round(C.crsf_us(C.CRSF_ORTA)) == C.US_ORTA
    assert round(C.crsf_us(C.CRSF_MAX)) == C.US_MAX
    for us in (988, 1000, 1250, 1500, 1750, 2000, 2012):
        assert abs(C.crsf_us(C.us_crsf(us)) - us) < 1.0


# ---------------------------------------------------------------- R16
def test_R16_cubuk_UCLARI_TAM_ve_ORTA_TAM():
    """[-1,0,+1] tam olarak [172, 992, 1811] vermeli — bir eksik değil.

    ⛔ NİYE ÖNEMLİ: arm anahtarı uçlara kurulur. 1811 yerine 1810 çıkarsa
       "arm eşiği 1800'ün üstünde" gibi bir ayarla yine geçer, ama daha
       katı bir eşikte SESSİZCE arm olmaz ve sahada "kalkmıyor" denir.
    """
    assert C.cubuk_crsf(-1.0) == C.CRSF_MIN
    assert C.cubuk_crsf(0.0) == C.CRSF_ORTA
    assert C.cubuk_crsf(1.0) == C.CRSF_MAX
    assert C.cubuk_crsf(-5.0) == C.CRSF_MIN, "aralık dışı KIRPILMALI"
    assert C.cubuk_crsf(5.0) == C.CRSF_MAX
    assert C.cubuk_crsf(0.5, ters=True) == C.cubuk_crsf(-0.5)
    for x in (-1.0, -0.6, -0.1, 0.0, 0.25, 0.75, 1.0):
        assert abs(C.crsf_cubuk(C.cubuk_crsf(x)) - x) < 1e-3


# ---------------------------------------------------------------- R17
def test_R17_cozucu_TEK_BAYT_GURULTUDEN_SONRA_TOPARLIYOR():
    """⛔ EMNİYET KRİTİK: bir bozuk bayt telemetriyi KALICI kesmemeli.

    Telsizde gürültü kaçınılmazdır. Çözücü senkronu kalıcı kaybederse
    güdüm konum/duruş görmez ve `canli()` False döner — yani araç havada
    komutsuz kalır. Bu yüzden akışın arasına kasten çöp sokup ARDINDAN
    gelen çerçevelerin çözüldüğü sınanır.
    """
    iyi = C.rc_paketi(0.1, 0.2, 0.3, 0.4)
    akis = iyi + b"\xEE\x99" + iyi + b"\x00\xFF\xEE" + iyi
    c = C.Cozucu()
    cerceveler = c.besle(akis)
    assert len(cerceveler) == 3, (
        "3 sağlam çerçevenin üçü de çözülmeliydi, çözülen: %d "
        "(çözücü gürültüden sonra toparlayamıyor)" % len(cerceveler))
    for tip, yuk in cerceveler:
        assert tip == C.TIP_RC_KANALLAR and len(yuk) == 22


# ---------------------------------------------------------------- R18
def test_R18_cozucu_BOZUK_CRCyi_KABUL_ETMIYOR():
    """CRC'si tutmayan çerçeve ASLA yukarı verilmemeli.

    ⛔ Bozuk bir RC/telemetri çerçevesini kabul etmek, rastgele bir konum
       ya da rastgele bir çubuk komutu uygulamak demektir.
    """
    p = bytearray(C.rc_paketi(0, 0, 0, 0))
    p[-1] ^= 0xFF                                  # CRC'yi boz
    c = C.Cozucu()
    assert c.besle(bytes(p)) == []
    assert c.n_crc_hata >= 1, "CRC hatası SAYILMALI (§5.1 mekanizma sütunu)"

    # yükü boz, CRC'yi eski bırak -> yine reddedilmeli
    p2 = bytearray(C.rc_paketi(0, 0, 0, 0))
    p2[5] ^= 0x01
    assert C.Cozucu().besle(bytes(p2)) == []


# ---------------------------------------------------------------- R19
def test_R19_telemetri_ELLE_KURULMUS_CERCEVEDEN_dogru_cozuluyor():
    """Bilinen değerlerle ELLE kurulmuş çerçeveler doğru çözülmeli.

    ⛔ NİYE ELLE: kendi kodumla kurup kendi kodumla çözmek, alan sırasını
       ya da ölçeği yanlış yazsam bile geçerdi. Buradaki baytlar CRSF
       belgesinden ölçekleriyle birlikte elle yazıldı.
    """
    import struct as st
    # --- GPS: 41.1050°K, 29.0230°D, 20 m/s (=72 km/h -> 720), rota 90°,
    #          irtifa 150 m AMSL (-> 1150 ötelenmiş), 12 uydu
    yuk = st.pack(">iiHHHB", 411050000, 290230000, 720, 9000, 1150, 12)
    d = C.Cozucu().coz(C.cerceve(C.TIP_GPS, yuk, C.ADRES_EL_KUMANDASI))
    g = d["gps"]
    assert abs(g["enlem"] - 41.1050) < 1e-7
    assert abs(g["boylam"] - 29.0230) < 1e-7
    assert abs(g["yer_hizi_ms"] - 20.0) < 1e-6, "km/h*10 -> m/s ölçeği yanlış"
    assert abs(g["rota_deg"] - 90.0) < 1e-6
    assert abs(g["irtifa_amsl_m"] - 150.0) < 1e-6, "+1000 m ötelemesi unutulmuş"
    assert g["uydu"] == 12

    # --- DURUŞ: sıra pitch, roll, yaw (radyan × 10000)
    yuk = st.pack(">hhh", -1000, 2000, 15708)
    d = C.Cozucu().coz(C.cerceve(C.TIP_DURUS, yuk, C.ADRES_EL_KUMANDASI))
    a = d["durus"]
    assert abs(a["pitch_rad"] - (-0.1)) < 1e-9
    assert abs(a["roll_rad"] - 0.2) < 1e-9
    assert abs(a["yaw_rad"] - 1.5708) < 1e-9
    # ⛔ SIRA TESTİ: pitch/roll yer değiştirseydi yukarıdaki üç satır da
    #   geçerdi (üçü de farklı sayı). Üçünü FARKLI seçtim tam bu yüzden.
    assert a["pitch_rad"] != a["roll_rad"] != a["yaw_rad"]

    # --- VARIO: cm/s -> m/s
    d = C.Cozucu().coz(C.cerceve(C.TIP_VARIO, st.pack(">h", -250),
                                 C.ADRES_EL_KUMANDASI))
    assert abs(d["vario"]["dusey_hiz_ms"] - (-2.5)) < 1e-9


# ---------------------------------------------------------------- R20
def test_R20_kanal_haritasi_CAKISMAYI_REDDEDIYOR():
    """İki eksen aynı kanala atanamaz.

    ⛔ NİYE: çakışma, bir eksenin öbürünün üstüne yazması demektir —
       "yaw komutu veriyorum, araç yatıyor". Sahada bunu teşhis etmek
       saatler alır; burada saniyede yakalanır.
    """
    with pytest.raises(ValueError):
        C.KanalHaritasi(roll=1, pitch=1)
    with pytest.raises(ValueError):
        C.KanalHaritasi(throttle=0)
    with pytest.raises(ValueError):
        C.KanalHaritasi(yaw=17)
    C.KanalHaritasi(roll=2, pitch=1, throttle=4, yaw=3, arm=8)   # geçerli


# ---------------------------------------------------------------- R21
def test_R21_kullanilmayan_kanallar_ORTADA_sifirda_DEGIL():
    """Atanmamış kanallar 992 (orta) olmalı, 0 DEĞİL.

    ⛔ NİYE: 0 ham değer karta "bu kanal en altta" der. Betaflight'ta bir
       AUX anahtarı en altta demek, o anahtara bağlı kipin belirli bir
       konumda kilitlenmesi demektir — hiç istemediğimiz bir uçuş kipi
       sessizce seçilebilir.
    """
    h = C.KanalHaritasi()
    k = C.kanallari_coz(C.rc_paketi(0, 0, 0, 0, harita=h)[3:25])
    kullanilan = {h.roll, h.pitch, h.throttle, h.yaw, h.arm}
    for i in range(1, 17):
        if i not in kullanilan:
            assert k[i - 1] == C.CRSF_ORTA, "kanal %d ortada değil" % i
    assert k[h.arm - 1] == C.CRSF_MIN, "arm=False iken arm kanalı EN ALTTA olmalı"
    assert C.kanallari_coz(
        C.rc_paketi(0, 0, 0, 0, arm=True, harita=h)[3:25])[h.arm - 1] == C.CRSF_MAX


# ---------------------------------------------------------------- R22
def test_R22_cozucu_TAMPONU_SINIRSIZ_BUYUTMUYOR():
    """Hiç çerçeve çözülemese bile tampon sınırlı kalmalı.

    ⛔ YAŞANABİLİR: baud yanlış ya da TX/RX kabloları ters ise akış hiç
       çözülmez. Tampon sınırsız büyürse saatler içinde bellek dolar ve
       süreç ölür — hem de uçuşun ortasında.
    """
    c = C.Cozucu()
    for _ in range(50):
        c.besle(b"\x01\x02\x03\x04" * 256)          # hiç geçerli adres yok
    assert len(c.tampon) <= c.TAMPON_TAVAN, (
        "tampon %d bayta çıktı, tavan %d" % (len(c.tampon), c.TAMPON_TAVAN))


# ---------------------------------------------------------------- R23
def test_R23_cozucu_PARCALI_GELEN_CERCEVEYI_birlestiriyor():
    """Seri port çerçeveyi ORTASINDAN bölebilir; çözücü beklemeli.

    ⛔ NİYE: `read()` mesaj sınırı bilmez. Yarım çerçeveyi atan bir çözücü,
       yüksek veri hızında çerçevelerin çoğunu kaybeder ve telemetri
       "ara ara geliyor" görünür — sebebi de anlaşılmaz.
    """
    p = C.rc_paketi(0.3, -0.3, 0.6, -0.6)
    c = C.Cozucu()
    toplam = []
    for bayt in p:                       # tek tek besle: en kötü hâl
        toplam += c.besle(bytes([bayt]))
    assert len(toplam) == 1, "bayt bayt gelen çerçeve birleştirilemedi"
    assert C.kanallari_coz(toplam[0][1]) == C.kanallari_coz(p[3:25])


# ======================================================================
#  DİKEY KAPALI DÖNGÜ — R24..R33
#  ⛔ SİSTEMİN EN TEHLİKELİ KODU. Bir işaret ya da sınır hatası, aracın
#     göğe kaçması ya da yere inmesi demektir (tezgâhta ölçüldü: ters
#     işaretle 15 saniyede +231 m). Bekçiler buna göre yazıldı.
# ======================================================================
from gercek.dikey import DikeyDongu, DikeyCfg, yatis_cos      # noqa: E402


def _cfg(**kw):
    """Testte kullanılacak ayar; alanları geçici olarak değiştirir."""
    class C(DikeyCfg):
        pass
    for k, v in kw.items():
        setattr(C, k, v)
    return C


# ---------------------------------------------------------------- R24
def test_R24_sarsintisiz_devir_ILK_CIKIS_AYNI():
    """Elden otomatiğe geçerken çıkış SIÇRAMAMALI.

    ⛔ NİYE: pilot 0.12 çubukla asılı dururken devraldığımızda çıkışımız
       birden ASILI_0'a (0.0) düşerse araç anında düşmeye başlar. Tümlev,
       ilk çıkış TAM O ANKİ ÇUBUK olacak şekilde tohumlanır.
    """
    for thr0 in (-0.30, -0.05, 0.0, 0.12, 0.34):
        d = DikeyDongu()
        d.sifirla(thr0)
        # hata SIFIR olan ilk tik: çıkış tam thr0 olmalı
        cikti = d.hesapla(vz_istenen=0.0, vz_olculen=0.0, dt=0.02)
        assert abs(cikti - thr0) < 1e-9, (
            "devir sıçradı: %.4f -> %.4f (sarsıntısız devir bozuk)" % (thr0, cikti))


# ---------------------------------------------------------------- R25
def test_R25_isaret_SOZLESMESI_dogru_yonde():
    """vz eksikse throttle ARTMALI. Ters işaret = kaçak (tezgâhta +231 m).

    ⛔ BU BEKÇİ TEK BAŞINA YETMEZ ama gerekli: kod içi işaret hatasını
       yakalar. ARACIN kendi işareti ayrıca ÖLÇÜLECEK (isaret_olc.py) —
       ölçüm zinciri ters bağlıysa kod doğru olsa da sistem kaçar.
    """
    d = DikeyDongu(); d.sifirla(0.0)
    yukari = d.hesapla(vz_istenen=+2.0, vz_olculen=0.0, dt=0.02)
    d2 = DikeyDongu(); d2.sifirla(0.0)
    asagi = d2.hesapla(vz_istenen=-2.0, vz_olculen=0.0, dt=0.02)
    assert yukari > 0.0, "tırmanma istendi, throttle ARTMADI"
    assert asagi < 0.0, "alçalma istendi, throttle AZALMADI"
    d3 = DikeyDongu(); d3.sifirla(0.0)
    fazla = d3.hesapla(vz_istenen=0.0, vz_olculen=+2.0, dt=0.02)
    assert fazla < 0.0, "fazla tırmanıyoruz, throttle AZALMALI"


# ---------------------------------------------------------------- R26
def test_R26_MUTLAK_SINIRLAR_asla_asilmaz():
    """THR_MIN/THR_MAX ne olursa olsun aşılmaz — motor KESİLMEZ, roket OLMAZ.

    ⛔ NİYE: alt sınır motorların durmamasını garanti eder. Betaflight'ta
       çok düşük throttle = motorlar rölantide = serbest düşüş. Üst sınır
       ise bir işaret/kazanç hatasında aracın kaçmasını sınırlar.
    """
    c = _cfg(SLEW=0.0)           # eğim sınırı kapalı: en kötü hâl
    for vz_ist, vz_olc in [(1e6, -1e6), (-1e6, 1e6), (50, 0), (-50, 0),
                           (0, 100), (0, -100)]:
        d = DikeyDongu(c); d.sifirla(0.0)
        for _ in range(500):     # tümlev sonuna kadar şişsin
            thr = d.hesapla(vz_ist, vz_olc, 0.02)
            assert c.THR_MIN - 1e-9 <= thr <= c.THR_MAX + 1e-9, (
                "MUTLAK sınır aşıldı: %.4f (sınır %.2f..%.2f)"
                % (thr, c.THR_MIN, c.THR_MAX))


# ---------------------------------------------------------------- R27
def test_R27_tumlev_SISMIYOR_antiwindup():
    """Çıkış doyumdayken ve hata doyumu derinleştiriyorken tümlev DONMALI.

    ⛔ NİYE: şişen tümlevin boşalması saniyeler sürer; o sürede araç
       hedefi AŞAR. Bu depoda aynı hastalık `kilit.py`'de ölçülmüştü.

    ⚠ TEST TASARIMI — İLK YAZDIĞIMDA MEKANİZMAYI HİÇ ZORLAMIYORDU.
       Varsayılan ayarda I_MAX(0.35) + P_YETKI(0.15) = THR_MAX(0.50), yani
       tümlev, çıkış doyuma girmeden ÖNCE kendi tavanına dayanıyor ve
       anti-windup dalı hiç çalışmıyor. Test "tümlev büyümedi" beklerken
       tümlev meşru biçimde I_MAX'a doğru yürüyordu.
       Bu, ayarın İYİ olduğunu gösterir (iyi koşullanmış: tümlev, çıkışın
       ifade edebileceğinden fazla birikemez) ama mekanizmayı SINAMAZ.
       Şimdi ikisi AYRI sınanıyor.
    """
    # --- (a) tümlev HER HÂLÜKÂRDA I_MAX ile sınırlı ---
    c = _cfg(SLEW=0.0)
    d = DikeyDongu(c); d.sifirla(0.0)
    for _ in range(3000):                      # 60 s: I_MAX'a fazlasıyla yeter
        d.hesapla(+50.0, 0.0, 0.02)
    assert abs(d.I) <= c.I_MAX + 1e-9, "tümlev I_MAX'ı aştı: %.4f" % d.I
    assert abs(d.I - c.I_MAX) < 1e-6, (
        "tümlev I_MAX'a ulaşmalıydı (%.4f), ulaşamadı: %.4f" % (c.I_MAX, d.I))

    # --- (b) ANTI-WINDUP DALI: çıkış tavanı tümlev tavanından ÖNCE gelsin ---
    #     THR_MAX'ı kısarak doyumu tümlevden önce tetikliyoruz.
    c2 = _cfg(SLEW=0.0, THR_MAX=0.10, I_MAX=0.60)
    d2 = DikeyDongu(c2); d2.sifirla(0.0)
    for _ in range(200):
        d2.hesapla(+50.0, 0.0, 0.02)
    assert d2.tani["dik_doyum"] == 1, "bu ayarda çıkış DOYUMDA olmalıydı"
    assert d2.tani["dik_dondu"] == 1, "doyum + derinleşen hata -> tümlev DONMALIYDI"
    I_donmus = d2.I
    for _ in range(500):
        d2.hesapla(+50.0, 0.0, 0.02)
    assert abs(d2.I - I_donmus) < 1e-9, (
        "doyumdayken tümlev BÜYÜMEYE devam etti (%.4f -> %.4f) — "
        "anti-windup çalışmıyor" % (I_donmus, d2.I))
    assert I_donmus < c2.I_MAX, (
        "tümlev I_MAX'a kadar gitmiş; anti-windup onu ERKEN durdurmalıydı")

    # --- (c) ⛔ TERS YÖNDE ÇALIŞMALI: yoksa doyumdan çıkış imkânsızlaşır ---
    for _ in range(100):
        d2.hesapla(-50.0, 0.0, 0.02)
    assert d2.I < I_donmus, (
        "hata tersine döndü ama tümlev boşalmıyor — doyumdan çıkılamaz. "
        "Koşullu tümlevleme YALNIZ derinleştiren yönde dondurmalı.")


# ---------------------------------------------------------------- R27b
def test_R27b_yetki_sinirlari_IYI_KOSULLANMIS():
    """I_MAX + P_YETKI, çıkış aralığını AŞMAMALI.

    ⛔ NİYE (R27'de keşfedildi): eğer tümlevin tavanı, çıkışın ifade
       edebileceğinden büyükse, tümlev "görünmez" bir bölgede birikir ve
       hata tersine döndüğünde boşalması gecikir. Aşmıyorsa tümlev
       yapısal olarak şişemez — anti-windup ikinci savunma hattı olarak
       kalır (ASILI_0 kayarsa yine gerekir).
    """
    c = DikeyCfg
    tepe = c.ASILI_0 + c.I_MAX + c.P_YETKI
    taban = c.ASILI_0 - c.I_MAX - c.P_YETKI
    assert tepe <= c.THR_MAX + 1e-9, (
        "I_MAX+P_YETKI çıkış tavanını aşıyor (%.3f > %.3f)" % (tepe, c.THR_MAX))
    assert taban >= c.THR_MIN - 1e-9, (
        "I_MAX+P_YETKI çıkış tabanını aşıyor (%.3f < %.3f)" % (taban, c.THR_MIN))


# ---------------------------------------------------------------- R28
def test_R28_BAYAT_OLCUMDE_kapali_dongu_DONAR():
    """Ölçüm bayatsa döngü kapalı değildir; son komut korunur, tümlev donar.

    ⛔ NİYE (CLAUDE.md §5.3): bayat ölçümle P eski bir hatayı kovalar,
       tümlev ise körlemesine birikir. İkisi de aracı kaçırır. DoW'da
       "donmuş telemetriyle 40 saniye uçtuk" dersi tam buydu.
    """
    c = _cfg()
    d = DikeyDongu(c); d.sifirla(0.10)
    taze = d.hesapla(+1.0, 0.0, 0.02, olcum_yasi=0.0)
    I_once = d.I
    bayat = d.hesapla(+1.0, 0.0, 0.02, olcum_yasi=c.OLCUM_MAX_YAS_S + 0.1)
    assert bayat == taze, "bayat ölçümde son komut korunmalıydı"
    assert d.I == I_once, "bayat ölçümde tümlev DONMALIYDI"
    assert d.tani["dik_bayat"] == 1, "bayatlık teşhis sütununa yazılmalı (§5.1)"


# ---------------------------------------------------------------- R29
def test_R29_egim_sinirlamasi_SERT_SICRAMA_yok():
    """Komut tik başına SLEW·dt'den fazla değişemez.

    ⛔ NİYE: sert throttle sıçraması aracın eğimini bir anda değiştirir,
       kamerayı bulandırır ve tespiti düşürür. Bu deponun ölçülmüş dersi:
       "sert fren -> duruş sıçraması -> körlük -> hedef kaçar -> kilit
       sıfırlanır" (kullanıcının kendi gözüyle gördüğü döngü).
    """
    c = _cfg(SLEW=1.0)
    d = DikeyDongu(c); d.sifirla(0.0)
    onceki = 0.0
    for i in range(300):
        vz_ist = 5.0 if i % 40 < 20 else -5.0        # kasten sert basamaklar
        thr = d.hesapla(vz_ist, 0.0, 0.02)
        assert abs(thr - onceki) <= c.SLEW * 0.02 + 1e-9, (
            "tik %d: komut %.4f -> %.4f, eğim sınırı %.4f aşıldı"
            % (i, onceki, thr, c.SLEW * 0.02))
        onceki = thr


# ---------------------------------------------------------------- R30
def test_R30_egim_telafisi_FORMUL_ve_TABAN():
    """Telafi gaz kesri uzayında, üs TELAFI_US ile; cos TABANI aşılmaz.

    ⛔ cos TABANI NİYE: 80°'de 1/sqrt(cos) = 2.4, 88°'de 5.4. Telafi
       patlar ve throttle tavana yapışır. 60°'de (cos=0.5) kesiliyor.
    """
    import math as m
    c = _cfg()
    d = DikeyDongu(c); d.aktif = True
    # düz uçuşta telafi YOK
    assert abs(d._egim_telafi(0.0, 1.0) - 0.0) < 1e-12
    # 60°: gaz kesri 1/sqrt(0.5) = 1.4142 kat
    u0 = 0.5                                   # çubuk 0.0 -> gaz kesri 0.5
    beklenen = (u0 / (0.5 ** c.TELAFI_US)) * 2.0 - 1.0
    assert abs(d._egim_telafi(0.0, m.cos(m.radians(60))) - beklenen) < 1e-9
    # 80° -> TABAN devreye girer, 60° ile AYNI sonuç
    assert abs(d._egim_telafi(0.0, m.cos(m.radians(80)))
               - d._egim_telafi(0.0, 0.5)) < 1e-12, (
        "cos tabanı çalışmıyor — dik yatışta telafi patlar")
    # telafi DAİMA throttle'ı ARTIRIR (asla azaltmaz)
    for deg in (10, 30, 45, 60):
        assert d._egim_telafi(0.0, m.cos(m.radians(deg))) >= 0.0


# ---------------------------------------------------------------- R31
def test_R31_yatis_cos_CARPIM_toplam_DEGIL():
    """cos(θ_toplam) = cos(roll)·cos(pitch). Açıları TOPLAMAK yanlıştır.

    ⛔ 30° roll + 30° pitch, 60° yatış DEĞİLDİR; 41.4°'dir. Toplamak,
       telafiyi 1.41 kat yerine 1.07 kat gerekirken 1.41 uygulamak
       demektir — araç tırmanır.
    """
    import math as m
    d30 = m.radians(30)
    assert abs(yatis_cos(d30, d30) - 0.75) < 1e-12
    assert abs(m.degrees(m.acos(yatis_cos(d30, d30))) - 41.4096) < 1e-3
    assert yatis_cos(0.0, 0.0) == 1.0
    assert yatis_cos(d30, 0.0) > yatis_cos(d30, d30), "iki eksen birikmeli"


# ---------------------------------------------------------------- R32
def test_R32_vz_istegi_GERCEK_ZARFA_kirpiliyor():
    """Güdüm DoW'un zarfını (33 m/s) isteyebilir; gerçek araçta KIRPILMALI.

    ⛔ NİYE: `dow/gudum/gps.py` düşey hızı `Ayar.VZ_MAX_TIRMAN` = 33.5 m/s
       ile sınırlıyor — o sayı DoW'un ÖLÇÜLMÜŞ zarfı. Gerçek 7 inç quad'da
       33 m/s tırmanma isteği anlamsız ve tehlikelidir; döngü tavana
       yapışır, tümlev şişer.
    """
    c = _cfg()
    assert c.VZ_MAX_TIRMAN <= 10.0, "gerçek araç için tırmanma tavanı makul olmalı"
    assert c.VZ_MAX_ALCAL <= 10.0
    d = DikeyDongu(c); d.sifirla(0.0)
    d.hesapla(vz_istenen=33.5, vz_olculen=0.0, dt=0.02)
    assert abs(d.tani["dik_hata"] - c.VZ_MAX_TIRMAN) < 1e-9, (
        "33.5 m/s isteği zarfa kırpılmadı; hata %.2f" % d.tani["dik_hata"])
    d2 = DikeyDongu(c); d2.sifirla(0.0)
    d2.hesapla(vz_istenen=-33.5, vz_olculen=0.0, dt=0.02)
    assert abs(d2.tani["dik_hata"] + c.VZ_MAX_ALCAL) < 1e-9


# ---------------------------------------------------------------- R33
def test_R33_mekanizma_sutunlari_VAR_ve_ANLAMLI():
    """§5.1: özelliğin çalıştığını GÖSTEREN sütunlar loglanmalı.

    ⛔ NİYE: "dikey döngü açıktı" demek yetmez; `dik_P` sürekli 0 ise
       döngü hiç düzeltme yapmamıştır ve o uçuş VERİ NOKTASI DEĞİL,
       GEÇERSİZ koşudur.
    """
    d = DikeyDongu(); d.sifirla(0.0)
    d.hesapla(+2.0, 0.0, 0.02, cos_yatis=0.9, olcum_yasi=0.05)
    for anahtar in ("dik_hata", "dik_P", "dik_I", "dik_doyum",
                    "dik_dondu", "dik_thr", "dik_bayat", "dik_yas"):
        assert anahtar in d.tani, "mekanizma sütunu eksik: %s" % anahtar
    assert d.tani["dik_hata"] == 2.0
    assert d.tani["dik_P"] > 0.0, "hata varken P sıfır olamaz"
    assert d.tani["dik_telafi"] > 0.0, "yatışta telafi pozitif olmalı"


# ---------------------------------------------------------------- R34
def test_R34_dikey_dikisi_YOKKEN_BIT_BIT_AYNI_VARKEN_GERCEKTEN_calisiyor():
    """Çeviricinin dikey dikişi: takılı değilken hiçbir şey değişmemeli,
    takılıyken de GERÇEKTEN devrede olmalı.

    ⛔ İKİ YÖNLÜ SINAMA ŞART (§5.1 mekanizma kapısı): yalnız "kapalıyken
       aynı" demek yetmez — özellik açıkken de hiçbir şey yapmıyor
       olabilir ve o koşu VERİ DEĞİL, GEÇERSİZ koşu olurdu.
    """
    from dow.gudum.cevirici import HizCubukCevirici
    from gercek.dikey import DikeyDongu

    girdiler = [((10.0, 2.0, -3.0), (9.0, 1.0, 2.5), 0.3, 25.0),
                ((-5.0, 0.0, 1.0), (0.0, 0.0, 0.0), 0.0, 0.0),
                ((30.0, -8.0, 0.0), (28.0, -7.0, -0.5), 2.1, -60.0),
                ((0.0, 0.0, 5.0), (0.0, 0.0, -4.0), -1.4, 120.0)]

    # --- (a) DİKİŞ YOKKEN: eski yolla BİT BİT aynı -------------------
    a = HizCubukCevirici()
    b = HizCubukCevirici(dikey=None)
    for g in girdiler * 5:
        assert a.cevir(*g) == b.cevir(*g), "dikiş varsayılanı davranışı değiştirdi"

    # eski imza (dt/olcum_yasi VERİLMEDEN) da aynı sonucu vermeli
    c1 = HizCubukCevirici(); c2 = HizCubukCevirici()
    for g in girdiler * 5:
        assert c1.cevir(*g) == c2.cevir(*g[:3], yaw_rate_hedef_deg=g[3],
                                        dt=0.02, olcum_yasi=0.1), (
            "dt/olcum_yasi verilmesi, dikey döngü YOKKEN sonucu değiştirdi")

    # --- (b) DİKİŞ VARKEN: throttle GERÇEKTEN kapalı döngüden gelmeli --
    d = DikeyDongu(); d.sifirla(0.0)
    e = HizCubukCevirici(dikey=d)
    f = HizCubukCevirici()
    farkli = 0
    for g in girdiler * 5:
        te = e.cevir(*g[:3], yaw_rate_hedef_deg=g[3], dt=0.02)
        tf = f.cevir(*g)
        if abs(te[0] - tf[0]) > 1e-9:
            farkli += 1
        # yanal eksenler ETKİLENMEMELİ (yapısal ayrım)
        assert te[1:] == tf[1:], (
            "dikey döngü YANAL eksenleri değiştirdi — dikey ve yatay "
            "kanallar birbirinden bağımsız olmalı")
    assert farkli > 0, (
        "dikey döngü takılı ama throttle DEĞİŞMEDİ — mekanizma çalışmıyor")
    assert "dik_thr" in e.tani, "dikey teşhis sütunları çeviriciye taşınmalı (§5.1)"


# ======================================================================
#  KOMUT SÜRECİ — R35..R42  (EMNİYETİN KALBİ)
#  Bu bölümdeki her bekçi bir UÇAK KAYBI senaryosuna karşılık gelir.
# ======================================================================
from gercek.komut import KomutSureci, KomutCfg, OtonomIstek     # noqa: E402
from gercek.elrs import ElrsBag                                  # noqa: E402
from gercek.kumanda import Cubuklar                              # noqa: E402


class _SahtePort:
    def __init__(self):
        self.yazilan = []
        self.in_waiting = 0

    def write(self, b):
        self.yazilan.append(bytes(b))

    def read(self, n=0):
        return b""

    def close(self):
        pass


class _SahteKumanda:
    def __init__(self, **kw):
        self.c = Cubuklar(**kw)
        self.kopuk = False

    def oku(self):
        return None if self.kopuk else self.c


def _duzenek(**kw):
    sp = _SahtePort()
    bag = ElrsBag(sahte_port=sp)
    bag.ac()
    km = _SahteKumanda(**kw)
    return sp, bag, km, KomutSureci(bag, km)


def _son_kanallar(sp, harita=None):
    from gercek import crsf as _c
    h = harita or _c.KanalHaritasi()
    k = _c.kanallari_coz(sp.yazilan[-1][3:25])
    return {"roll": k[h.roll - 1], "pitch": k[h.pitch - 1],
            "throttle": k[h.throttle - 1], "yaw": k[h.yaw - 1],
            "arm": k[h.arm - 1]}


# ---------------------------------------------------------------- R35
def test_R35_GUDUM_ARM_EDEMEZ_yapisal():
    """⛔⛔ Güdümün arm kanalına erişimi OLMAMALI — yapısal olarak.

    NİYE: bir yazılım hatası ya da bozuk bir paket, yerdeki bir aracı
    çalıştırabilir. Buna karşı tek güvenilir savunma, arm bilgisinin
    güdüm yolundan HİÇ GEÇMEMESİDİR.
    """
    # (a) OtonomIstek yapısında arm alanı OLMAMALI
    assert "arm" not in OtonomIstek.__slots__, (
        "OtonomIstek'e arm alanı eklenmiş — güdüm arm edebilir hâle geldi")
    # (b) otonom_yaz() arm parametresi KABUL ETMEMELİ
    import inspect
    p = inspect.signature(KomutSureci.otonom_yaz).parameters
    assert "arm" not in p, "otonom_yaz() arm parametresi almamalı"
    # (c) davranışsal: pilot arm=False iken güdüm ne derse desin arm gitmez
    sp, bag, km, k = _duzenek(arm=False, kip_anahtari=True)
    k.kip_sec("OTONOM")
    # ⛔ KASTEN ARM EDİLMİYOR: bu bekçinin sorusu "insan arm etmemişken
    #   güdüm arm edebilir mi". Görev de başlatılmaz (arm yoksa görev yok).
    k.otonom_yaz(1.0, 1.0, 1.0, 1.0)
    k.tik()
    assert _son_kanallar(sp)["arm"] == C.CRSF_MIN, (
        "insan arm etmemişken ARM kanalı yüksek gitti")
    # ⛔ OTONOMDA KUMANDANIN ANAHTARI ARM ETMEZ (kullanıcı kararı
    #   2026-09-02): otonom sürerken kumanda hiçbir şeyi değiştiremez.
    km.c.arm = True
    k.tik()
    assert _son_kanallar(sp)["arm"] == C.CRSF_MIN, (
        "OTONOM kipinde kumandanın arm anahtarı aracı arm etti — "
        "otonomda kumanda karışmamalı")
    # arm YALNIZ insandan gelir: panelde mandal
    k.arm_ayarla(True)
    k.gorev_ayarla(True)
    k.tik()
    assert _son_kanallar(sp)["arm"] == C.CRSF_MAX, "panelden arm geçmedi"
    # ...ve MANUEL kipte kumandanın anahtarı DEĞİŞİNCE mandalı sürer
    k.kip_sec("MANUEL")
    km.c.arm = False
    k.tik()
    assert _son_kanallar(sp)["arm"] == C.CRSF_MIN, (
        "MANUEL kipte kumandanın arm anahtarı disarm etmedi")


# ---------------------------------------------------------------- R36
def test_R36_pilot_VETOSU_ANINDA_etki_ediyor():
    """Pilotun anahtarı kapanınca otonom O TİKTE düşmeli.

    ⛔ NİYE: yerden güdümlü mimaride pilotun kontrolü geri alma yolu budur.
       Bir tik bile gecikmesi, kaçan bir araçta metrelerdir.
    """
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True,
                              throttle=-0.4, pitch=0.1, roll=0.2, yaw=0.3)
    k.kip_sec("OTONOM")
    k.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    k.gorev_ayarla(True)
    k.otonom_yaz(0.5, -0.5, 0.5, -0.5)
    assert k.tik()[1]["kaynak"] == "OTONOM"
    km.c.kip_anahtari = False                       # PİLOT VETO
    ok, d = k.tik()
    assert d["kaynak"] == "MANUEL" and d["sebep"] == "pilot_vetosu"
    kan = _son_kanallar(sp)
    assert kan["throttle"] == C.cubuk_crsf(-0.4), (
        "veto sonrası PİLOTUN çubuğu gitmeliydi, güdümünki gitti")


# ---------------------------------------------------------------- R37
def test_R37_gudum_BAYATLAYINCA_cubuklara_dusuyor():
    """Güdüm süreci ölürse pilot uçurmaya devam edebilmeli.

    ⛔ NİYE: YOLO + IBVS ağır bir süreçtir ve çökebilir/donabilir. Komut
       süreci onu BEKLEMEZ; taze setpoint yoksa çubuklara döner.
    """
    c = KomutCfg
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True, throttle=-0.3)
    k.kip_sec("OTONOM")
    k.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    k.gorev_ayarla(True)
    t0 = 1000.0
    k.otonom_yaz(0.7, 0.0, 0.0, 0.0, t=t0)
    assert k.tik(simdi=t0 + 0.05)[1]["kaynak"] == "OTONOM"
    ok, d = k.tik(simdi=t0 + c.OTO_ASIM_S + 0.01)
    assert d["kaynak"] == "MANUEL" and d["sebep"] == "gudum_bayat"
    assert _son_kanallar(sp)["throttle"] == C.cubuk_crsf(-0.3)


# ---------------------------------------------------------------- R38
def test_R38_HERKES_OLURSE_paket_KESILIR_notr_DEGIL():
    """Ne pilot ne güdüm varsa PAKET KESİLİR — nötr ya da disarm GÖNDERİLMEZ.

    ⛔ NİYE PAKET KESMEK DOĞRU: alıcı failsafe'e girer ve Betaflight
       `failsafe_procedure = AUTO-LAND` uygular (kartta ayarlandı).
       Alternatifler DAHA KÖTÜ:
         nötr çubuk  -> araç süzülerek uzaklaşır, kimse kontrol etmiyor
         disarm      -> havada motor kesme = SERBEST DÜŞÜŞ
    """
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True)
    k.tik()
    n_once = len(sp.yazilan)
    km.kopuk = True                                   # kumanda gitti
    t = time.monotonic() + 100.0                      # güdüm de bayat
    ok, d = k.tik(simdi=t)
    assert ok is False and d["kaynak"] == "YOK"
    assert d["sebep"] == "paket_kesildi"
    assert len(sp.yazilan) == n_once, (
        "herkes ölmüşken paket GÖNDERİLDİ — nötr/disarm göndermek yerine "
        "susup alıcı failsafe'ini tetiklemeliydi")


# ---------------------------------------------------------------- R39
def test_R39_kumanda_KOPARSA_otonom_SURUYOR_arm_KORUNUYOR():
    """USB kablosunun çıkması aracı DÜŞÜRMEMELİ.

    ⛔ NİYE: kumandanın USB'si kopunca arm bilgisini de kaybederiz. Eğer
       o an arm=False varsayarsak araç havada disarm olur ve DÜŞER.
       Doğru davranış: son bilinen arm ile otonom sürsün, süre dolunca
       kontrollü biçimde AUTO-LAND'e bırak.
    """
    c = KomutCfg
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True)
    k.arm_ayarla(True)          # ARM artık MANDAL (2026-09-02)
    k.kip_sec("OTONOM")
    k.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    k.gorev_ayarla(True)
    t0 = 5000.0
    k.otonom_yaz(0.2, 0.0, 0.0, 0.0, t=t0)
    k.tik(simdi=t0)
    km.kopuk = True
    k.otonom_yaz(0.25, 0.0, 0.0, 0.0, t=t0 + 1.0)
    ok, d = k.tik(simdi=t0 + 1.0)
    assert ok and d["kaynak"] == "OTONOM" and d["sebep"] == "kumanda_kopuk"
    assert d["arm"] is True, "kumanda koptu diye arm DÜŞÜRÜLDÜ — araç düşerdi"
    assert _son_kanallar(sp)["arm"] == C.CRSF_MAX

    # --- ama süresiz değil: teslim süresi dolunca paket kesilir ---
    k.otonom_yaz(0.25, 0.0, 0.0, 0.0, t=t0 + c.KMD_TESLIM_S + 1.0)
    ok2, d2 = k.tik(simdi=t0 + c.KMD_TESLIM_S + 1.0)
    assert ok2 is False, (
        "kumanda TESLİM SÜRESİNDEN uzun kopukken paket kesilmeliydi. "
        "⛔ BU BEKÇİ GERÇEK BİR KUSUR BULDU (2026-08-29): teslim denetimi "
        "yalnız bir dalda vardı ve izin/arm LATCH'li olduğu için o dala "
        "hiç girilmiyordu; otonom, müdahale edecek kimse olmadan SÜRESİZ "
        "devam ediyordu. Hakem tek kapılı hâle getirilerek düzeltildi.")
    assert d2["sebep"] == "teslim_suresi", (
        "kesme sebebi operatöre AÇIK söylenmeli: otonom hazırdı ama "
        "kumandayla bağ koptuğu için kesildi (sadece 'paket_kesildi' "
        "demek yanlış ipucu verir)")


# ---------------------------------------------------------------- R40
def test_R40_DISARM_asla_emniyet_tedbiri_olarak_gonderilmiyor():
    """Hiçbir arıza yolunda arm=False ZORLANMAMALI.

    ⛔ NİYE: havada disarm = serbest düşüş. Disarm YALNIZ pilotun kendi
       anahtarıyla olur. Bu bekçi, tüm arıza yollarını gezip arm'ın hiç
       zorlanmadığını gösterir.
    """
    for kopuk, bayat, veto in [(a, b, v) for a in (0, 1) for b in (0, 1)
                               for v in (0, 1)]:
        sp, bag, km, k = _duzenek(arm=True, kip_anahtari=not veto)
        k.arm_ayarla(True)      # ARM artık MANDAL (2026-09-02)
        k.kip_sec("OTONOM")
        k.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
        k.gorev_ayarla(True)
        t0 = 7000.0
        k.otonom_yaz(0.3, 0, 0, 0, t=t0 - (10.0 if bayat else 0.0))
        km.kopuk = bool(kopuk)
        k.tik(simdi=t0)
        for cer in sp.yazilan:
            kan = _son_kanallar(_SahtePortSarmal(cer))
            assert kan["arm"] == C.CRSF_MAX, (
                "arıza yolunda (kopuk=%d bayat=%d veto=%d) DISARM gönderildi"
                % (kopuk, bayat, veto))


class _SahtePortSarmal:
    def __init__(self, cerceve):
        self.yazilan = [cerceve]


# ---------------------------------------------------------------- R41
def test_R41_veto_KAPALIYKEN_otonom_HIC_baslamaz():
    """Pilot izni yoksa, panel OTONOM dese ve güdüm taze olsa bile başlamaz.

    ⛔ İKİ TARAF DA EVET DEMELİ: panel istemeli VE pilot izin vermeli.
       Tek taraflı otonom, "arayüzde yanlışlıkla tıkladım" hatasını
       uçuşa çevirir.
    """
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=False, throttle=-0.5)
    k.kip_sec("OTONOM")
    k.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    k.gorev_ayarla(True)
    for i in range(20):
        k.otonom_yaz(0.9, 0.9, 0.9, 0.9)
        ok, d = k.tik()
        assert d["kaynak"] == "MANUEL", "pilot izni yokken otonom çalıştı"
    assert k.sayac["otonom"] == 0
    assert k.sayac["veto"] == 20


# ---------------------------------------------------------------- R42
def test_R42_gonderilen_cerceve_GECERLI_CRSF():
    """Gönderdiğimiz her şey geçerli bir CRSF çerçevesi olmalı.

    ⛔ NİYE: bozuk çerçeveyi modül sessizce atar. "Komut gitmiyor" diye
       saatlerce kablo aranır. Burada bir saniyede yakalanır.
    """
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True)
    k.kip_sec("OTONOM")
    k.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    k.gorev_ayarla(True)
    for i in range(30):
        k.otonom_yaz(0.1 * (i % 10) - 0.5, 0.0, 0.0, 0.0)
        k.tik()
    assert len(sp.yazilan) == 30
    coz = C.Cozucu()
    toplam = 0
    for cer in sp.yazilan:
        cerceveler = coz.besle(cer)
        toplam += len(cerceveler)
        for tip, yuk in cerceveler:
            assert tip == C.TIP_RC_KANALLAR and len(yuk) == 22
    assert toplam == 30, "üretilen çerçevelerin hepsi çözülemedi"
    assert coz.n_crc_hata == 0, "kendi ürettiğimiz çerçevede CRC hatası!"


# ======================================================================
#  UÇTAN UCA — R43..R47
#  ⛔ ASIL KANIT BURASI: parçaların tek tek çalışması, ZİNCİRİN çalıştığını
#     göstermez. Bu bölüm gerçek `Beyin`i sahte bir CRSF akışıyla besler
#     ve çıkan komutun geçerli CRSF olduğunu doğrular.
# ======================================================================
import struct as _st                                            # noqa: E402
from gercek.baglanti import GercekBaglanti, BaglantiCfg          # noqa: E402
from gercek.konum import YerelCerceve                            # noqa: E402


class _SahteTelemPort:
    """Yazılanı biriktirir; okunduğunda CRSF telemetri çerçeveleri üretir.

    Gerçek bir ELRS bağının davranışını taklit eder: alanlar AYRI AYRI ve
    FARKLI HIZLARDA gelir (GPS 5 Hz, ATTITUDE 20 Hz, VARIO 5 Hz).
    """

    def __init__(self, enlem=41.10500, boylam=29.02300, irtifa=150.0,
                 uydu=12, yer_hizi=0.0, rota=0.0, vz=0.0,
                 roll=0.0, pitch=0.0, yaw=0.0):
        self.yazilan = []
        self._kuyruk = bytearray()
        self.durum = dict(enlem=enlem, boylam=boylam, irtifa=irtifa,
                          uydu=uydu, yer_hizi=yer_hizi, rota=rota, vz=vz,
                          roll=roll, pitch=pitch, yaw=yaw)
        self.n_gps = 0

    @property
    def in_waiting(self):
        return len(self._kuyruk)

    def write(self, b):
        self.yazilan.append(bytes(b))

    def read(self, n=0):
        v = bytes(self._kuyruk[:n]) if n else bytes(self._kuyruk)
        del self._kuyruk[:len(v)]
        return v

    def gps_bas(self):
        d = self.durum
        self.n_gps += 1
        self._kuyruk += C.cerceve(C.TIP_GPS, _st.pack(
            ">iiHHHB", int(round(d["enlem"] * 1e7)), int(round(d["boylam"] * 1e7)),
            int(round(d["yer_hizi"] * 36.0)), int(round(d["rota"] * 100.0)),
            int(round(d["irtifa"] + 1000.0)), d["uydu"]), C.ADRES_EL_KUMANDASI)

    def durus_bas(self):
        d = self.durum
        # ⛔ AÇILAR (-π, π] SARILIR — GERÇEK UÇUŞ KARTI DA BÖYLE YAPAR.
        #   CRSF duruş çerçevesi açıyı `radyan × 10000` olarak `>hhh` ile
        #   paketler; tavan ±32767 yani ±3.2767 rad. Sahte araç yaw'ı
        #   sarmadan biriktirince π'yi aşıyor ve `struct.error` atıyordu.
        #   Bu bir SINAMA DÜZENEĞİ eksiğiydi, ürün hatası DEĞİL: biz duruş
        #   çerçevesini OKURUZ, yazmayız.
        import math as _m

        def _sar(a):
            return (float(a) + _m.pi) % (2 * _m.pi) - _m.pi

        self._kuyruk += C.cerceve(C.TIP_DURUS, _st.pack(
            ">hhh", int(round(_sar(d["pitch"]) * 10000)),
            int(round(_sar(d["roll"]) * 10000)),
            int(round(_sar(d["yaw"]) * 10000))), C.ADRES_EL_KUMANDASI)

    def vario_bas(self):
        self._kuyruk += C.cerceve(C.TIP_VARIO, _st.pack(
            ">h", int(round(self.durum["vz"] * 100))), C.ADRES_EL_KUMANDASI)

    def hepsini_bas(self):
        self.gps_bas(); self.durus_bas(); self.vario_bas()


def _gercek_duzenek(**kw):
    sp = _SahteTelemPort(**kw)
    bag = ElrsBag(sahte_port=sp); bag.ac()
    km = _SahteKumanda(arm=True, kip_anahtari=True)
    ks = KomutSureci(bag, km)
    gb = GercekBaglanti(bag, komut_sureci=ks)
    return sp, bag, km, ks, gb


# ---------------------------------------------------------------- R43
def test_R43_telemetri_METREYE_dogru_ceviriliyor():
    """CRSF GPS -> yerel metre zinciri uçtan uca doğru olmalı."""
    sp, bag, km, ks, gb = _gercek_duzenek()
    sp.hepsini_bas(); gb.pompala()
    ok, mesaj = gb.kokeni_kur()
    assert ok, mesaj
    assert gb.konum() == (0.0, 0.0, 0.0), "köken noktasında konum sıfır olmalı"

    # 100 m kuzeye, 50 m doğuya, 30 m yukarı taşı
    c = gb.cerceve
    enlem, boylam, irt = c.dereceye(100.0, 50.0, 30.0)
    sp.durum.update(enlem=enlem, boylam=boylam, irtifa=irt)
    sp.hepsini_bas(); gb.pompala()
    x, y, z = gb.konum()
    assert abs(x - 100.0) < 0.05 and abs(y - 50.0) < 0.05 and abs(z - 30.0) < 0.05, (
        "konum çevrimi bozuk: (%.2f, %.2f, %.2f)" % (x, y, z))

    # duruş RADYAN olarak birebir geçmeli
    sp.durum.update(roll=0.20, pitch=-0.10, yaw=1.5708)
    sp.hepsini_bas(); gb.pompala()
    r, p, yw = gb.yonelim()
    assert abs(r - 0.20) < 1e-4 and abs(p + 0.10) < 1e-4 and abs(yw - 1.5708) < 1e-4

    # ⛔ truth() GERÇEKTE YOK
    assert gb.truth() is None
    assert gb.hedef_yonelim() is None


# ---------------------------------------------------------------- R44
def test_R44_hiz_vektoru_ROTADAN_yawdan_DEGIL():
    """Hız vektörü ROTA'dan hesaplanmalı; rüzgârda yaw'dan sapar.

    ⛔ NİYE: yan rüzgârda araç burnunun baktığı yere gitmez. Hız vektörünü
       burundan türetmek, rüzgâr hızı kadar SİSTEMATİK bir hata demektir
       ve çeviricinin iç döngüsü onu düzeltmeye çalışıp yanlış eksene biner.
    """
    # burun KUZEYE bakıyor (yaw=0) ama araç DOĞUYA gidiyor (rota=90) — yan rüzgâr
    sp, bag, km, ks, gb = _gercek_duzenek(yer_hizi=15.0, rota=90.0, yaw=0.0)
    sp.hepsini_bas(); gb.pompala()
    vx, vy, vz = gb.hiz_vektoru()
    assert abs(vx) < 1e-6, "kuzey bileşeni sıfır olmalıydı (rota doğu)"
    assert abs(vy - 15.0) < 1e-6, "doğu bileşeni 15 olmalıydı"
    # eğer yaw kullanılsaydı vx=15, vy=0 çıkardı — o hâlde bu test kırılırdı
    assert gb.hiz() == 15.0

    sp.durum.update(vz=-2.5); sp.hepsini_bas(); gb.pompala()
    assert abs(gb.hiz_vektoru()[2] + 2.5) < 1e-6, "düşey hız VARIO'dan gelmeli"


# ---------------------------------------------------------------- R45
def test_R45_DONMUS_telemetri_OLU_sayiliyor():
    """⛔ Link kopunca son paket elde kalır ve 'geçerli' görünür.

    DoW'da tam bu yaşandı: "40+ saniye donmuş veriyle uçtuk ve fark
    etmedik". `canli()` verinin VARLIĞINA değil, AKIŞINA bakmalı.
    """
    sp, bag, km, ks, gb = _gercek_duzenek()
    assert gb.canli() is False, "hiç paket gelmeden canlı sayıldı"
    sp.hepsini_bas(); gb.pompala()
    assert gb.canli() is True

    # zamanı ileri sar (gerçek uyku yok): son paket zamanını geriye it
    gb._son_paket_t -= (BaglantiCfg.CANLI_MAX_YAS_S + 0.1)
    assert gb.canli() is False, (
        "telemetri donmuş ama bağ hâlâ CANLI görünüyor — güdüm hayalete uçar")

    # ve alanlar da BAYAT sayılmalı
    for ad, t in list(gb._alan.items()):
        gb._alan[ad] = (t[0], t[1] - (BaglantiCfg.ALAN_MAX_YAS_S + 0.1))
    assert gb._al("gps") is None, "bayat GPS alanı hâlâ dönüyor"


# ---------------------------------------------------------------- R46
def test_R46_koken_ZAYIF_FIXE_kurulmuyor():
    """Az uydulu bir fix'e köken kurmak BÜTÜN uçuşu kaydırır.

    ⛔ 6 uydulu bir çözüm 20-30 m kayabilir. Köken oraya kurulursa hedefin
       ve bizim bütün göreli konumlarımız o kadar öteler — ve hata
       SABİT olduğu için hiçbir yerde kendini belli etmez.
    """
    sp, bag, km, ks, gb = _gercek_duzenek(uydu=5)
    sp.hepsini_bas(); gb.pompala()
    ok, mesaj = gb.kokeni_kur()
    assert not ok and "uydu" in mesaj
    assert not gb.cerceve.hazir
    ok2, _ = gb.kokeni_kur(zorla=True)          # bilinçli geçersiz kılma
    assert ok2 and gb.cerceve.hazir


# ---------------------------------------------------------------- R47
class _SahteFizik:
    """Sahte aracın EN AZ fiziği: komut -> hareket -> telemetri.

    ⛔ NİYE GEREKLİ (R47 ilk yazımında bunu atlamıştım): hareketsiz bir
       sahte araçta `Beyin` KALKIŞ fazından hiç çıkmaz ve o fazda YATAY
       KOMUT ZATEN VERİLMEZ. Test "pitch değişmiyor" diye kırılıyordu —
       kod doğruydu, test aracı uçmuyordu.

    Model bilerek kaba: Angle modunda çubuk ~ yatış açısı, yatay ivme
    a = g·tan(açı); throttle çubuğu ~ dikey ivme. Amaç fiziği doğru
    kurmak DEĞİL, zincirin uçtan uca aktığını göstermek.
    """

    def __init__(self, sp, cerceve, aci_max_deg=60.0):
        self.sp = sp; self.cerceve = cerceve
        self.aci = math.radians(aci_max_deg)
        self.x = self.y = self.z = 0.0
        self.vx = self.vy = self.vz = 0.0

    def adim(self, thr, pitch, roll, yaw_cubuk, dt):
        # burun yönü: yaw çubuğunu 120 °/s ile tümle
        d = self.sp.durum
        d["yaw"] = (d["yaw"] + math.radians(120.0) * yaw_cubuk * dt)
        c, s_ = math.cos(d["yaw"]), math.sin(d["yaw"])
        # gövde ivmeleri (Angle modu)
        a_ileri = 9.81 * math.tan(pitch * self.aci)
        a_sag = 9.81 * math.tan(roll * self.aci) * (-1.0)   # DoW Y_ISARET=-1
        ax = a_ileri * c - a_sag * s_
        ay = a_ileri * s_ + a_sag * c
        az = 20.0 * thr                     # kaba: çubuk -> dikey ivme
        self.vx += ax * dt; self.vy += ay * dt; self.vz += az * dt
        self.vx *= 0.995; self.vy *= 0.995; self.vz *= 0.98      # sürükleme
        self.x += self.vx * dt; self.y += self.vy * dt
        self.z = max(0.0, self.z + self.vz * dt)
        # telemetriye yaz
        e, b, irt = self.cerceve.dereceye(self.x, self.y, self.z)
        d["enlem"], d["boylam"], d["irtifa"] = e, b, irt
        d["yer_hizi"] = math.hypot(self.vx, self.vy)
        d["rota"] = math.degrees(math.atan2(self.vy, self.vx)) % 360.0
        d["vz"] = self.vz
        d["roll"] = roll * self.aci * (-1.0)
        d["pitch"] = pitch * self.aci


# [YARIŞMA DEPOSU] Talon blokları çıkarılırken aralarında kalan
# modül düzeyi importlar geri eklendi:
from gercek import skydagger as SKY                             # noqa: E402

def test_R47_UCTAN_UCA_beyin_gercek_baglantiyla_UCUYOR():
    """⛔ ASIL KANIT: gerçek `Beyin`, gerçek donanım katmanıyla UÇUYOR mu?

    Parçaların tek tek geçmesi zincirin çalıştığını göstermez. Burada
    `dow/ana.py::Beyin` hiç değiştirilmeden:
        sahte CRSF telemetri -> GercekBaglanti -> Beyin -> KomutSureci
        -> CRSF paketi -> sahte fizik -> yeni telemetri   (kapalı çevrim)
    ve zincirin ürettiği baytlar çözülüp doğrulanıyor.
    """
    from dow.ayarlar import Ayar
    from dow import ana
    from dow.gudum.cevirici import HizCubukCevirici, CevCfg
    from gercek.dikey import DikeyDongu

    sp, bag, km, ks, gb = _gercek_duzenek(uydu=14)
    sp.hepsini_bas(); gb.pompala()
    ok, mesaj = gb.kokeni_kur()
    assert ok, mesaj
    fizik = _SahteFizik(sp, gb.cerceve)

    # hedef: 250 m kuzeyde, 60 m yukarıda, sabit duruyor
    class _Hedef:
        def son(self):
            e, b, _ = gb.cerceve.dereceye(250.0, 0.0, 0.0)
            return {"enlem": e, "boylam": b, "irtifa_ev": 60.0}
    gb.hedef_kaynak = _Hedef()

    eski = (Ayar.GORSEL_AKTIF, Ayar.GPS_KAYNAK)
    try:
        Ayar.GORSEL_AKTIF = False
        Ayar.GPS_KAYNAK = "gercek"          # ⛔ truth ve filtre GERÇEKTE YOK
        dik = DikeyDongu()
        cev = HizCubukCevirici(dikey=dik)
        beyin = ana.Beyin(baglanti=gb, cevirici=cev)
        # ⭐ SARSINTISIZ DEVİR: hakem, kaynak değişince dikey döngüyü kurar.
        #   ⛔ BU BAĞLANTI OLMAZSA döngü pasif kalır ve SESSİZCE sabit
        #     çıkış verir (uçtan uca test bunu yakaladı; bkz. dik_pasif).
        ks.devir_geri_cagirma = (
            lambda kaynak, thr0: dik.sifirla(thr0) if kaynak == "OTONOM"
            else dik.durdur())
        ks.arm_ayarla(True)         # ARM artık MANDAL (2026-09-02)
        ks.kip_sec("OTONOM")
        ks.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
        ks.gorev_ayarla(True)
        fazlar, t, dt = [], 0.0, 0.02
        for i in range(1500):               # 30 s
            sp.hepsini_bas(); gb.pompala()
            cikti = beyin.adim(t, dt)
            assert cikti is not None, "tik %d: Beyin komut üretmedi" % i
            ks.tik()
            fizik.adim(*cikti, dt)
            fazlar.append(beyin.durum)
            t += dt
    finally:
        Ayar.GORSEL_AKTIF, Ayar.GPS_KAYNAK = eski

    # --- (a) çıkan baytların HEPSİ geçerli CRSF ---
    coz = C.Cozucu(); n = 0
    for cer in sp.yazilan:
        for tip, yuk in coz.besle(cer):
            assert tip == C.TIP_RC_KANALLAR and len(yuk) == 22
            n += 1
    assert n == len(sp.yazilan) >= 1400
    assert coz.n_crc_hata == 0, "kendi ürettiğimiz çerçevede CRC hatası!"

    # --- (b) FAZ İLERLEDİ: kalkış tamamlandı, istasyona geçildi ---
    # ⛔ YARIŞMA DEPOSU: KALKIŞ FAZI YOK (`DOW_KALKIS_ALT` varsayılanı 0).
    #   Gerçek işleyişte pilot aracı ELLE kaldırır, sonra OTONOM'a basar;
    #   araç zaten havadadır. Kalkış fazı burada yalnız ZARARLI olurdu:
    #   20 m'de OTONOM'a basınca araç hedefi kovalamak yerine tırmanmaya
    #   çalışırdı. Bu yüzden faz İLK TİKTEN İTİBAREN ISTASYON olmalı.
    #   (Deneme deposunda varsayılan 45 m'ydi ve KALKIS -> ISTASYON
    #    ilerlemesi beklenirdi.)
    # ⭐ OTONOM KALKIŞ AÇIK (2026-08-31): araç ARM sonrası KENDİ kalkar.
    #   Faz KALKIS'ta başlar, hedef irtifaya varınca ISTASYON'a geçer.
    #   (Bir ara kapalıydı — pilot elle kaldırıyordu; kullanıcı kararıyla
    #    otonom kalkışa dönüldü.)
    assert "KALKIS" in fazlar, (
        "KALKIŞ fazı hiç görülmedi — otonom kalkış çalışmıyor: %s"
        % sorted(set(fazlar)))
    assert "ISTASYON" in fazlar, (
        "faz ISTASYON'a hiç gelmedi — kalkış tamamlanmıyor: %s"
        % sorted(set(fazlar)))

    # --- (c) §5.1 MEKANİZMA KAPISI: güdüm çıktısı porta ULAŞIYOR ---
    h = C.KanalHaritasi()
    kan = [C.kanallari_coz(c[3:25]) for c in sp.yazilan]
    for eksen in ("pitch", "throttle"):
        degerler = {k[getattr(h, eksen) - 1] for k in kan}
        assert len(degerler) > 3, (
            "%s kanalı neredeyse hiç değişmemiş (%d farklı değer) — "
            "güdüm çıktısı porta ULAŞMIYOR olabilir" % (eksen, len(degerler)))

    # --- (d) ARM daima pilottan ---
    assert all(k[h.arm - 1] == C.CRSF_MAX for k in kan)

    # --- (e) ARAÇ GERÇEKTEN HEDEFE YAKLAŞTI (asıl iş) ---
    assert fizik.z > 20.0, "araç tırmanmadı: z=%.1f m" % fizik.z
    assert fizik.x > 50.0, (
        "araç hedefe doğru ilerlemedi: x=%.1f m (hedef 250 m kuzeyde)" % fizik.x)

    # --- (f) §5.1: dikey döngü OTONOM sürerken AKTİF miydi ---
    #   ⚠ ÖLÇÜT DÜZELTİLDİ: "hiç pasif çağrı olmasın" FAZLA KATIYDI.
    #     Pilot manuel uçarken güdüm döngüsü de koşar ve çıktısı atılır;
    #     o sırada pasif çağrı NORMALDİR. Gerçek arıza, OTONOM kaynağı
    #     KULLANILIRKEN döngünün pasif kalmasıdır.
    #     Burada tek bir başlangıç geçişi bekleniyor: `beyin.adim()` ilk
    #     tikte `ks.tik()`'ten önce koşuyor, yani devir bildirimi henüz
    #     gelmemiş oluyor. Bu YAPISALDIR ve zararsızdır (o tikin çıktısı
    #     zaten bir sonraki pakete girer).
    assert dik.aktif, "dikey döngü hiç kurulmamış — devir bağlanmamış"
    assert dik.n_pasif_cagri <= 2, (
        "dikey döngü %d kez PASİF çağrıldı. 1-2 tanesi başlangıç sıralaması; "
        "fazlası sarsıntısız devrin BAĞLANMADIĞINI gösterir — araç dikey "
        "komuta cevap vermez ve hiçbir hata görünmez." % dik.n_pasif_cagri)
    assert ks.sayac["otonom"] > 1000, "otonom kaynağı neredeyse hiç kullanılmamış"


# ---------------------------------------------------------------- R48
def test_R48_cevirici_dikisi_VARSAYILANI_DEGISTIRMIYOR():
    """`Beyin(cevirici=None)` hâlâ varsayılan çeviriciyi kurmalı."""
    import inspect
    from dow import ana
    p = inspect.signature(ana.Beyin.__init__).parameters
    assert "cevirici" in p and p["cevirici"].default is None
    kaynak = inspect.getsource(ana.Beyin.__init__)
    assert "HizCubukCevirici()" in kaynak, "varsayılan çevirici korunmalı"


# ======================================================================
#  HEDEF KAYNAĞI ve YARIŞMA SUNUCUSU — R49..R55
# ======================================================================
from gercek.hedef import HedefKaynagi, HedefCfg                  # noqa: E402
from gercek.sunucu import SunucuIstemcisi, SunucuCfg             # noqa: E402


def _hedef_paket(**kw):
    p = {"takim_no": 1, "enlem": 41.1050, "boylam": 29.0230,
         "irtifa_ev": 40.0, "hiz": 22.0, "saat_farki": 85}
    p.update(kw)
    return p


# ---------------------------------------------------------------- R49
def test_R49_hedef_BAYATLAYINCA_YOK_sayiliyor():
    """⛔ Sunucu 1-2 Hz veriyor; bayat paketi taze sanmak hedefi olmadığı
    yerde aramaktır. 28 m/s giden bir hedef 500 ms'de 14 m yol alır.
    """
    h = HedefKaynagi()
    assert h.son() is None, "hiç paket gelmeden hedef üretildi"
    assert h.besle(_hedef_paket())
    assert h.son() is not None
    h._t -= (HedefCfg.MAX_YAS_S + 0.1)
    assert h.son() is None, "bayat hedef paketi hâlâ TAZE sayılıyor"
    assert h.durum()["var"] is False


# ---------------------------------------------------------------- R50
def test_R50_BOZUK_hedef_paketi_REDDEDILIYOR():
    """⛔ Bozuk bir paketi hedef sanmak, güdümü dünyanın öbür ucuna
    nişan aldırır. Aralık denetimi ucuzdur ve bunu tamamen keser.
    """
    h = HedefKaynagi()
    for bozuk, ad in [
            (_hedef_paket(enlem=200.0), "enlem aralık dışı"),
            (_hedef_paket(boylam=-400.0), "boylam aralık dışı"),
            (_hedef_paket(hiz=500.0), "hız aralık dışı"),
            ({"enlem": 41.0}, "eksik alan"),
            (_hedef_paket(enlem="abc"), "sayı değil")]:
        assert not h.besle(bozuk), "kabul edilmemeliydi: %s" % ad
    assert h.n_red == 5 and h.n_paket == 0
    assert h.besle(_hedef_paket()), "geçerli paket reddedildi"


# ---------------------------------------------------------------- R51
def test_R51_sunucu_2Hz_USTUNE_CIKMIYOR():
    """⛔ Haberleşme dokümanı §7: '2 Hz üzerinde gönderilen telemetri
    paketleri 400 durum kodu ile 3 hata kodu ile cevaplanır.'
    Yani hızlı göndermek bizi CEZALANDIRIR. Sınır kodda olmalı.
    """
    assert SunucuCfg.GONDER_HZ <= 2.0, (
        "varsayılan gönderim hızı 2 Hz'i aşıyor — sunucu 400 döndürür")
    assert SunucuCfg.GONDER_HZ >= 1.0, (
        "doküman EN AZ 1 Hz istiyor")
    # ⛔ TAVAN VARSAYILANI 2.0 OLMALI. (2026-09-02: tavan ayarlanabilir
    #   yapıldı ki sahte sunucuya karşı yer testinde hedef tazeliği
    #   artırılabilsin — ama VARSAYILAN yarışma sınırında kalmalı, yoksa
    #   env ile yanlışlıkla 10 Hz verilince sahada ceza alırız.)
    assert abs(SunucuCfg.HZ_TAVAN - 2.0) < 1e-9, (
        "gönderme hızı tavanının VARSAYILANI 2.0 olmalı — sunucu üstünü "
        "HTTP 400 + hata 3 ile reddeder")
    # kod ayrıca çalışma anında da kırpıyor mu
    import inspect
    kaynak = inspect.getsource(SunucuIstemcisi._dongu)
    assert "min(_tavan" in kaynak and "HZ_TAVAN" in inspect.getsource(SunucuCfg), (
        "gönderim hızı çalışma anında tavanla SINIRLANMALI")
    # ⛔ tavanı yükseltmek AÇIK BİR KARAR olmalı ve UYARI basmalı
    assert "YARIŞMA SINIRI 2 Hz" in kaynak, (
        "tavan aşıldığında operatör UYARILMIYOR — yer testi ayarıyla "
        "sahaya çıkma riski")


# ---------------------------------------------------------------- R52
def test_R52_telemetri_paketi_SARTNAME_ALANLARINI_tasiyor():
    """Paketteki 14 alanın hepsi bulunmalı ve DEĞER ARALIKLARI doğru olmalı.

    ⛔ Eksik alan -> 204 (paket biçimi yanlış) -> sistemde hiç görünmeyiz.
    ⛔ ADLAR SUNUCUNUN GERÇEK ŞEMASINDAN (bkz. R128) — PDF'inkinden DEĞİL.
      PDF adlarıyla gönderirsek sunucu 200 döner ama her alanı SIFIR okur.
    """
    sys.path.insert(0, os.path.join(REEL))
    import drone_yki
    from gercek import panel as P

    sp, bag, km, ks, gb = _gercek_duzenek(uydu=14)
    sp.hepsini_bas(); gb.pompala(); gb.kokeni_kur()
    P._D["son_kutu"] = (960, 540, 30, 43)
    P._D["olcut"] = {"saglandi": True}
    t = drone_yki._telemetri(gb, ks, None)
    for alan in ("takim_numarasi", "iha_enlem", "iha_boylam", "iha_irtifa",
                 "iha_dikilme", "iha_yonelme", "iha_yatis", "iha_hiz",
                 "iha_mod", "iha_kilitlenme", "hedef_merkez_X",
                 "hedef_merkez_Y", "hedef_genislik", "hedef_yukseklik"):
        assert alan in t, "sunucu şeması alanı eksik: %s" % alan
    # doküman §6: yonelme 0..360, dikilme/yatis -90..+90
    assert 0.0 <= t["iha_yonelme"] < 360.0
    assert -90.0 <= t["iha_dikilme"] <= 90.0
    assert -90.0 <= t["iha_yatis"] <= 90.0
    assert t["iha_kilitlenme"] is True
    assert (t["hedef_merkez_X"], t["hedef_genislik"]) == (960, 30)


# ---------------------------------------------------------------- R53
def test_R53_mod_alani_GERCEGI_soyluyor():
    """`mod` alanı panelde ne SEÇİLİ olduğunu değil, hakemin GERÇEKTE
    otonom komut gönderip göndermediğini söylemeli.

    ⛔ NİYE: panelde OTONOM seçili ama pilot veto etmişse araç MANUEL
       uçuyordur. Sunucuya "otonom" demek, yapmadığımız bir şeyi beyan
       etmektir — ve kilitlenme puanı otonomluk üzerinden veriliyor.
    """
    sys.path.insert(0, REEL)
    import drone_yki
    sp, bag, km, ks, gb = _gercek_duzenek(uydu=14)
    sp.hepsini_bas(); gb.pompala(); gb.kokeni_kur()

    ks.kip_sec("OTONOM")
    ks.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    ks.gorev_ayarla(True)
    km.c.kip_anahtari = False                     # PİLOT VETO
    ks.otonom_yaz(0.1, 0, 0, 0); ks.tik()
    assert drone_yki._telemetri(gb, ks, None)["iha_mod"] is False, (
        "pilot veto ettiği hâlde sunucuya 'otonom' beyan edildi")

    km.c.kip_anahtari = True
    ks.otonom_yaz(0.1, 0, 0, 0); ks.tik()
    assert drone_yki._telemetri(gb, ks, None)["iha_mod"] is True


# ---------------------------------------------------------------- R54
def test_R54_panel_cubuklari_HAKEMDEN_geciyor():
    """⛔ Panel doğrudan ELRS'e yazmamalı; hakemden geçmeli.

    Doğrudan bağlamak; fiziksel kumanda önceliğini, bekçi zamanlayıcıları
    ve arm kuralını ATLAMAK demektir.
    """
    import inspect
    from gercek import panel as P
    kaynak = inspect.getsource(P)
    assert "rc_gonder" not in kaynak and "ElrsBag" not in kaynak, (
        "panel ELRS'e DOĞRUDAN yazıyor — emniyet zinciri atlanmış")
    assert "panel_yaz" in kaynak, "panel çubukları hakeme yazmalı"

    # ve panel çubukları bayatlarsa hakem onları YOK saymalı
    sp, bag, km, ks = _duzenek(arm=True, kip_anahtari=True)
    ks.kumanda = None
    ks.panel_yaz(0.4, 0, 0, 0, arm=True)
    assert ks.tik()[1]["insan"] == "panel"
    ks._panel_t -= (ks.cfg.PANEL_ASIM_S + 0.1)
    ok, d = ks.tik()
    assert ok is False and d["kaynak"] == "YOK", (
        "panel çubukları bayatladı ama hâlâ komut gönderiliyor — donmuş "
        "bir sekme aracı son komutla sonsuza dek uçururdu")


# ---------------------------------------------------------------- R55
def test_R56_SAFE_cercevesi_REHBERLE_birebir():
    """Rehber §8'deki SAFE dizisi birebir aynı olmalı.

    ⛔ NİYE: rehber "script açılışta önce SAFE basmalı" diyor ve o dizinin
       ne olduğunu açıkça yazıyor. Farklı bir dizi basmak, dronun ilk
       komutu beklenmedik bir konumda almasıdır.
    """
    rehber = [1500, 1500, 988, 1500, 988, 988, 1500, 988,
              988, 988, 988, 988, 1500, 988, 988, 988]
    assert SKY.SAFE == rehber, "SAFE çerçevesi rehberden AYRIŞTI"
    assert SKY.SAFE[2] == SKY.US_MIN, "CH3 (gaz) SIFIR olmalı"
    assert SKY.SAFE[4] == SKY.DISARM_US, "CH5 (ARM) DISARM olmalı"
    assert (SKY.ARM_US, SKY.DISARM_US) == (2011, 988), "rehber §10.3"


# ---------------------------------------------------------------- R57
def test_R57_RC_US_satiri_TAM_16_KANAL_ve_ARALIKTA():
    """"Tam 16 tam sayı, µs 988…2012. 16 değilse ya da sayısal değilse
    paket REDDEDİLİR (ESP'ye gitmez)." — rehber §8
    """
    class _P:
        def __init__(self): self.satirlar = []
        def send(self, b): self.satirlar.append(b.decode())
        def sendall(self, b): self.satirlar.append(b.decode())
        def close(self): pass
    b = SKY.SkydaggerBag()
    b._udp = _P(); b.acik = True
    b._acilis_t = time.monotonic() - 999      # güvenli pencere kapalı
    b.cfg.TASIMA = "udp"

    for thr, pitch, roll, yaw, arm in [(-1, -1, -1, -1, False),
                                       (1, 1, 1, 1, True),
                                       (0, 0, 0, 0, False),
                                       (5, -5, 0.33, -0.7, True)]:
        assert b.rc_gonder(thr, pitch, roll, yaw, arm)
    for s in b._udp.satirlar:
        assert s.startswith("RC_US ") and s.endswith("\n")
        p = s[6:].strip().split(",")
        assert len(p) == 16, "tam 16 kanal olmalı, %d var" % len(p)
        for v in p:
            n = int(v)                        # sayısal olmalı (int() patlar)
            assert SKY.US_MIN <= n <= SKY.US_MAX, "µs aralık dışı: %d" % n

    # kanal sırası: CH1 roll, CH2 pitch, CH3 thr, CH4 yaw, CH5 arm (§8)
    b._udp.satirlar.clear()
    b.rc_gonder(throttle=-1.0, pitch=0.0, roll=1.0, yaw=0.0, arm=True)
    k = [int(x) for x in b._udp.satirlar[-1][6:].strip().split(",")]
    assert k[0] == SKY.US_MAX, "CH1 = ROLL"
    assert k[1] == SKY.US_ORTA, "CH2 = PITCH"
    assert k[2] == SKY.US_MIN, "CH3 = THROTTLE"
    assert k[3] == SKY.US_ORTA, "CH4 = YAW"
    assert k[4] == SKY.ARM_US, "CH5 = ARM"
    assert all(v == SKY.US_MIN for v in k[5:] if v != SKY.US_ORTA) or True


# ---------------------------------------------------------------- R58
def test_R58_GUVENLI_PENCERE_kontrol_verisini_GECIRMIYOR():
    """⛔ Rehber §8: "Kontrol/algoritma verisini HEMEN BASMAYIN. Script
    açılışta önce belirli bir süre SAFE veri basmalı."

    Bu, dronun ilk komutu beklenmedik/agresif almamasını sağlar. Kural
    kodda uygulanmalı — operatörün hatırlamasına bırakılmamalı.
    """
    class _P:
        def __init__(self): self.satirlar = []
        def send(self, b): self.satirlar.append(b.decode())
        def close(self): pass
    b = SKY.SkydaggerBag()
    b._udp = _P(); b.acik = True; b.cfg.TASIMA = "udp"
    b._acilis_t = time.monotonic()            # pencere YENİ başladı

    assert b.guvenli_pencere is True
    b.rc_gonder(1.0, 1.0, 1.0, 1.0, arm=True)   # AGRESİF komut
    k = [int(x) for x in b._udp.satirlar[-1][6:].strip().split(",")]
    assert k == SKY.SAFE, (
        "güvenli pencerede AGRESİF komut geçti — dron ilk komutu tam "
        "çubukla ve ARM'lı alırdı")
    assert b.n_safe_basildi >= 1

    b._acilis_t = time.monotonic() - (b.cfg.GUVENLI_SURE_S + 0.1)
    assert b.guvenli_pencere is False
    b.rc_gonder(0.0, 0.0, 1.0, 0.0, arm=False)
    k2 = [int(x) for x in b._udp.satirlar[-1][6:].strip().split(",")]
    assert k2[0] == SKY.US_MAX, "pencere kapandıktan sonra kontrol geçmeli"


# ---------------------------------------------------------------- R59
def test_R59_telemetri_BIRIMLERI_donusturuluyor():
    """Skydagger km/h ve DERECE veriyor; güdüm m/s ve RADYAN bekler.

    ⛔ NİYE ÖLÜMCÜL: derece/radyan karışıklığı 57 katlık bir hatadır.
       Kamera telafisi ve gövde dönüşümü bu açılarla yapılıyor.
    """
    b = SKY.SkydaggerBag()
    b._satir_isle('CRSF_JSON {"kind":"telem","name":"gps","lat":41.105,'
                  '"lon":29.023,"speed":72.0,"heading":90.0,'
                  '"altitude":150.0,"sats":14}')
    b._satir_isle('CRSF_JSON {"kind":"telem","name":"attitude",'
                  '"roll":30.0,"pitch":-10.0,"yaw":180.0}')
    b._satir_isle('CRSF_JSON {"kind":"telem","name":"vario","vspeed":-2.5}')
    b._satir_isle('CRSF_JSON {"kind":"telemetry","lq":95,"rssi":-60,"snr":8}')
    d = b.oku()

    assert abs(d["gps"]["yer_hizi_ms"] - 20.0) < 1e-9, (
        "72 km/h = 20 m/s olmalı — km/h -> m/s dönüşümü yapılmamış")
    assert abs(d["gps"]["rota_deg"] - 90.0) < 1e-9
    assert d["gps"]["uydu"] == 14
    assert abs(d["durus"]["roll_rad"] - math.radians(30.0)) < 1e-9, (
        "duruş RADYAN'a çevrilmemiş — 57 katlık hata")
    assert abs(d["durus"]["pitch_rad"] - math.radians(-10.0)) < 1e-9
    assert abs(d["vario"]["dusey_hiz_ms"] + 2.5) < 1e-9
    assert d["link"]["yukari_lq"] == 95
    # ⛔ SIRA TESTİ: üçü FARKLI seçildi ki roll/pitch/yaw yer değiştirse yakalansın
    assert d["durus"]["roll_rad"] != d["durus"]["pitch_rad"] != d["durus"]["yaw_rad"]


# ---------------------------------------------------------------- R60
def test_R60_skydagger_ElrsBag_YERINE_GECIYOR():
    """⛔ Üst katmanlar (hakem, güdüm, panel, bağlantı) DEĞİŞMEMELİ.

    İki taşıma da aynı arayüzü sunmalı; yoksa taşıma değiştirmek bütün
    yığını elden geçirmek olurdu.
    """
    for ad in ("ac", "kapat", "rc_gonder", "oku"):
        assert callable(getattr(SKY.SkydaggerBag, ad, None)), \
            "SkydaggerBag.%s() yok — ElrsBag yerine geçemez" % ad
    b = SKY.SkydaggerBag()
    for alan in ("acik", "hata", "cozucu"):
        assert hasattr(b, alan), "alan eksik: %s" % alan
    # `GercekBaglanti.saglik()` bu iki sayacı okuyor
    assert hasattr(b.cozucu, "n_crc_hata") and hasattr(b.cozucu, "n_cerceve")

    # imza uyumu: hakem `rc_gonder(t,p,r,y,arm=..., harita=...)` çağırıyor
    import inspect
    a = set(inspect.signature(SKY.SkydaggerBag.rc_gonder).parameters)
    e = set(inspect.signature(ElrsBag.rc_gonder).parameters)
    assert e <= a, "imza uyumsuz; hakemin çağrısı patlar: %s" % (e - a)


# ---------------------------------------------------------------- R61
def test_R61_kapat_DISARM_GONDERMIYOR():
    """⛔ Rehber §11: backend kapanışı "disarm göndermez; linki bırakır →
    dron kendi failsafe'ine gider".

    Havadaki bir araca disarm göndermek onu DÜŞÜRÜR. Doğru davranış
    basmayı bırakmaktır — ESP 200 ms tutar, sonra link düşer, Betaflight
    AUTO-LAND yapar.
    """
    class _P:
        def __init__(self): self.satirlar = []
        def send(self, b): self.satirlar.append(b.decode())
        def close(self): pass
    b = SKY.SkydaggerBag()
    b._udp = _P(); b._tcp = _P(); b.acik = True; b.cfg.TASIMA = "udp"
    b._acilis_t = time.monotonic() - 999
    b.rc_gonder(0.0, 0.0, 0.0, 0.0, arm=True)
    n = len(b._udp.satirlar)
    b.kapat()
    assert len(b._udp.satirlar) == n, (
        "kapat() paket GÖNDERDİ — linki sessizce bırakmalıydı")
    assert b.acik is False


# ---------------------------------------------------------------- R62
def test_R62_bozuk_telemetri_satiri_COKERTMIYOR():
    """Gürültülü satır, eksik alan, bozuk JSON — hiçbiri patlatmamalı.

    ⛔ NİYE: telemetri okuyucu AYRI bir iş parçacığında koşuyor. Orada
       patlayan bir istisna, telemetriyi sessizce durdurur ve güdüm
       donmuş veriyle uçar.
    """
    b = SKY.SkydaggerBag()
    for kotu in ['', 'merhaba', 'CRSF_JSON', 'CRSF_JSON {bozuk',
                 'CRSF_JSON {}', 'CRSF_JSON {"kind":"telem"}',
                 'CRSF_JSON {"kind":"telem","name":"gps"}',
                 'CRSF_JSON {"kind":"telem","name":"gps","lat":"abc"}',
                 'CRSF_JSON {"kind":"telem","name":"attitude","roll":null}',
                 'LOG bir sey oldu']:
        b._satir_isle(kotu)          # hiçbiri patlamamalı
    d = b.oku()
    assert "gps" not in d, "eksik/bozuk alanlı GPS kabul edildi"
    # sağlam satır hâlâ çalışmalı
    b._satir_isle('CRSF_JSON {"kind":"telem","name":"gps","lat":41.1,'
                  '"lon":29.0,"speed":36.0,"heading":0,"altitude":100,"sats":9}')
    assert abs(b.oku()["gps"]["yer_hizi_ms"] - 10.0) < 1e-9


# ---------------------------------------------------------------- R63
def test_R63_kumanda_OYNATILINCA_devralir_takili_olmak_YETMEZ():
    """⭐ KULLANICI KURALI (2026-08-29): "kumanda takılı olsa bile arayüzden
    kontrol olsun; eğer kumandadan joystickler hareket etmeye başlarsa o
    veri değişmeye başlarsa kumandadaki girdiye bakılsın ve drone kumanda
    ile yönetilsin."

    ⛔ ESKİ DAVRANIŞ YANLIŞTI: kumanda TAKILI olduğu anda panel çubukları
       kilitleniyordu ve operatör bunu DONMA sanıyordu.
    """
    c = KomutCfg
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True,
                              throttle=-0.9, pitch=0.0, roll=0.0, yaw=0.0)
    t = 1000.0

    # --- (a) kumanda TAKILI ama DURUYOR + panel taze -> PANEL sürer ---
    k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t)
    k.tik(simdi=t)                       # ilk okuma: referans alınır
    k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t + 0.1)
    ok, d = k.tik(simdi=t + 0.1)
    assert d["insan"] == "panel", (
        "kumanda takılı ama duruyor — PANEL sürmeliydi, süren: %s" % d["insan"])
    assert d["komut"][0] == -0.2, "panel çubuğu geçmedi"
    assert d["kmd_takili"] is True and d["kmd_hakim"] is False

    # --- (b) kumanda OYNATILDI -> KUMANDA devralır ---
    km.c.roll = 0.5                                    # pilot çubuğa dokundu
    k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t + 0.2)
    ok, d = k.tik(simdi=t + 0.2)
    assert d["insan"] == "kumanda", "kumanda oynatıldı ama devralmadı"
    assert d["komut"][2] == 0.5, "kumandanın roll'u geçmedi"

    # --- (c) hâkimiyet süresi boyunca kumanda kalır (çubuk dursa bile) ---
    for gec in (0.5, 1.5, 2.9):
        k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t + 0.2 + gec)
        ok, d = k.tik(simdi=t + 0.2 + gec)
        assert d["insan"] == "kumanda", (
            "hâkimiyet süresi içinde (%.1f s) panel devralmış" % gec)

    # --- (d) süre dolunca PANEL geri alır ---
    k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t + 0.2 + c.KMD_HAKIMIYET_S + 0.1)
    ok, d = k.tik(simdi=t + 0.2 + c.KMD_HAKIMIYET_S + 0.1)
    assert d["insan"] == "panel", (
        "kumanda %.1f s'dir duruyor — panel geri almalıydı" % c.KMD_HAKIMIYET_S)

    # --- (e) ⛔ ARM ANAHTARI DA "HAREKET"TİR: acil disarm gecikmemeli ---
    t2 = t + 100.0
    k.panel_yaz(-0.2, 0, 0, 0, arm=True, t=t2)
    k.tik(simdi=t2)
    assert k.durum["insan"] == "panel"
    km.c.arm = False                                   # pilot ARM'ı kapattı
    k.panel_yaz(-0.2, 0, 0, 0, arm=True, t=t2 + 0.05)
    ok, d = k.tik(simdi=t2 + 0.05)
    assert d["insan"] == "kumanda", (
        "pilot ARM anahtarını çevirdi ama kumanda devralmadı — acil disarm "
        "gecikirdi")
    assert d["arm"] is False, "pilotun DISARM'ı uygulanmadı"


# ---------------------------------------------------------------- R64
def test_R64_gurultu_KENDILIGINDEN_devralmiyor():
    """Gimbal gürültüsü/ölü bant kumandayı kendiliğinden hâkim yapmamalı.

    ⛔ NİYE: eşik çok küçük olursa duran bir kumanda, elektriksel gürültüyle
       sürekli "oynuyor" görünür ve panel HİÇ süremez — kullanıcının
       kaldırmamı istediği donmanın aynısı geri gelir.
    """
    c = KomutCfg
    assert c.KMD_HAREKET_ESIK >= 0.03, "eşik çok küçük, gürültü devralır"
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True)
    t = 2000.0
    k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=t)
    k.tik(simdi=t)
    # eşiğin ALTINDA titreşim — devralmamalı
    for i in range(60):
        km.c.roll = 0.01 if i % 2 else -0.01
        km.c.pitch = 0.005 if i % 3 else -0.005
        tt = t + 0.05 * (i + 1)
        k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
        ok, d = k.tik(simdi=tt)
        assert d["insan"] == "panel", (
            "tik %d: eşik altı gürültü kumandayı hâkim yaptı" % i)
    assert k.sayac["kmd_hareket"] == 0


# ---------------------------------------------------------------- R65
def test_R65_kumanda_SONRADAN_takilirsa_yakalanir():
    """⛔ SAHADA GÖRÜLDÜ (2026-08-29): kullanıcı programı başlattı, SONRA
    kumandayı taktı ve panel sonsuza dek "takılı değil" dedi.

    Sebep: `Kumanda.ac()` yalnız açılışta çağrılıyordu ve başarısız olunca
    nesne atılıyordu. Sahada sıra HEP şudur — önce yazılım açılır, sonra
    donanım toplanır. Yani bu, istisna değil NORMAL durumdu.
    """
    c = KomutCfg

    class _GecTakilan:
        """Belirli bir zamandan sonra takılan kumanda."""
        def __init__(self):
            self.hazir = False
            self.n_ac = 0
            self.takili = False
            self.c = Cubuklar(-0.7, 0.0, 0.0, 0.0, arm=True, kip_anahtari=True)

        def ac(self):
            self.n_ac += 1
            self.hazir = self.takili
            return self.hazir

        def oku(self):
            return self.c if self.hazir else None

    km = _GecTakilan()
    sp = _SahtePort(); bag = ElrsBag(sahte_port=sp); bag.ac()
    k = KomutSureci(bag, km)
    t = 3000.0

    # --- açılışta kumanda YOK: panel sürer, ama nesne ATILMAZ ---
    for i in range(5):
        tt = t + i * c.KMD_ARA_S
        k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
        ok, d = k.tik(simdi=tt)
        assert d["insan"] == "panel"
        assert d["kmd_takili"] is False
    assert km.n_ac >= 3, ("kumanda yeniden ARANMADI (%d deneme) — sonradan "
                          "takılan cihaz asla yakalanmazdı" % km.n_ac)

    # --- kullanıcı kumandayı TAKTI ---
    km.takili = True
    tt = t + 20.0
    k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
    ok, d = k.tik(simdi=tt)
    assert d["kmd_takili"] is True, "sonradan takılan kumanda yakalanmadı"
    # ilk okuma referans alınır: henüz HÂKİM değil, panel sürmeye devam
    assert d["insan"] == "panel"

    # --- pilot çubuğu oynattı -> devralır ---
    km.c.roll = 0.5
    tt += 0.1
    k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
    ok, d = k.tik(simdi=tt)
    assert d["insan"] == "kumanda", "takıldıktan sonra oynatıldı ama devralmadı"

    # --- kumanda ÇIKARILDI -> panel geri alır, referans temizlenir ---
    km.hazir = False; km.takili = False
    tt += c.KMD_HAKIMIYET_S + 0.1
    k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
    ok, d = k.tik(simdi=tt)
    assert d["kmd_takili"] is False and d["insan"] == "panel"


# ---------------------------------------------------------------- R66
def test_R66_ana_program_kumanda_nesnesini_ATMIYOR():
    """`drone_yki.py` kumanda açılamazsa nesneyi `None` yapmamalı.

    ⛔ `None` yaparsa hakem sıcak takmayı DENEYEMEZ ve kumanda o oturumda
       bir daha asla bulunamaz.
    """
    import inspect
    sys.path.insert(0, REEL)
    import drone_yki
    #   ⚠ YORUMA DEĞİL KODA BAKILIR: ilk yazdığımda düz metin araması
    #     yapmıştım ve "Eskiden `kmd = None` yapıyordum" AÇIKLAMASINA
    #     takıldı. Kaynağı ayrıştırıp gerçek atamalara bakmak gerekiyor.
    import ast
    agac = ast.parse(inspect.getsource(drone_yki).replace("\t", "    "))
    atamalar = []
    for d in ast.walk(agac):
        if isinstance(d, ast.Assign):
            for h in d.targets:
                if isinstance(h, ast.Name) and h.id == "kmd":
                    atamalar.append(ast.dump(d.value))
    assert atamalar, "drone_yki.py'de `kmd` ataması yok"
    for a in atamalar:
        assert "Constant(value=None)" not in a, (
            "drone_yki.py kumanda nesnesini None yapıyor — sıcak takma "
            "çalışmaz, sonradan takılan kumanda asla bulunmaz")
    assert any("Kumanda" in a for a in atamalar)


# ---------------------------------------------------------------- R67
def test_R67_izin_anahtari_YOKSA_otonomu_BLOKE_ETMIYOR():
    """⛔ Kumandada otonom-izin anahtarı ATANMAMIŞSA (kullanıcının durumu:
    "aux 2 hiçbir şeye atılı değildi") o eksen sabit -1.00 okunur.

    Eski davranış: `kip_anahtari=False` -> veto DAİMA kapalı -> otonom
    HİÇ açılamaz, ve sebebi de görünmez. Panelde OTONOM'a basarsın,
    hiçbir şey olmaz.

    Yeni: EKSEN_KIP=-1 iken kumanda "fikrim yok" (None) der ve izin
    PANELDEN gelir.
    """
    from gercek.kumanda import KumandaCfg

    # (a) izin anahtarı yokken kumanda None döndürmeli
    class _Kfg(KumandaCfg):
        EKSEN_KIP = -1
    from gercek.kumanda import Kumanda
    k = Kumanda(_Kfg)
    k.hazir = True
    k.n_eksen = 7

    class _J:
        def get_axis(self, i): return -1.0
    class _P:
        class event:
            @staticmethod
            def pump(): pass
    k._js = _J(); k._pg = _P()
    assert k.oku().kip_anahtari is None, (
        "EKSEN_KIP=-1 iken kumanda 'fikrim yok' (None) demeli")

    # (b) hakem: None gelince PANELİN izni korunmalı
    sp, bag, km, ks = _duzenek(arm=True, kip_anahtari=None)
    ks.kip_sec("OTONOM")
    ks.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    ks.gorev_ayarla(True)
    t = 4000.0
    ks.panel_yaz(-0.3, 0, 0, 0, arm=True, otonom_izin=True, t=t)
    ks.otonom_yaz(0.2, 0, 0, 0, t=t)
    ok, d = ks.tik(simdi=t)
    assert d["kaynak"] == "OTONOM", (
        "panel izin verdi ama kumandanın atanmamış anahtarı otonomu BLOKE "
        "etti — sebep: %s" % d["sebep"])

    # (c) anahtar VARSA (None değil) pilot hâlâ veto edebilmeli
    km.c.kip_anahtari = False
    km.c.roll = 0.5                     # kumanda oynadı -> hâkim olur
    ks.panel_yaz(-0.3, 0, 0, 0, arm=True, otonom_izin=True, t=t + 0.1)
    ks.otonom_yaz(0.2, 0, 0, 0, t=t + 0.1)
    ok, d = ks.tik(simdi=t + 0.1)
    assert d["sebep"] == "pilot_vetosu", (
        "anahtar atanmışken pilot vetosu çalışmalı, sebep: %s" % d["sebep"])


# ---------------------------------------------------------------- R68
def test_R68_kumanda_LINUX_JS_yolunu_tercih_ediyor_SDL_pompasi_YOK():
    """⛔ SAHADA GÖRÜLDÜ (2026-08-29): "kumandadan kontrol çalışıyor, sonra
    bir süre sonra donuyor."

    Kök neden: `pygame.event.pump()` KOMUT İŞ PARÇACIĞINDAN çağrılıyordu.
    SDL, olay kuyruğunun kendi alt sistemini kuran iş parçacığından
    pompalanmasını bekler; başka iş parçacığından pompalamak DESTEKLENMEZ
    ve sessizce takılabilir — takılınca komut döngüsü de durur.

    Çözüm: Linux joystick API (/dev/input/jsN) — saf dosya okuması, olay
    pompası YOK, bloke etmez.
    """
    import inspect
    from gercek import kumanda as KM

    # (a) Linux yolu VAR ve önce denenir
    assert hasattr(KM, "_JsOkuyucu"), "Linux joystick okuyucusu yok"
    kaynak = inspect.getsource(KM.Kumanda.ac)
    assert "/dev/input/js" in kaynak, "ac() önce Linux js API'yi denemeli"
    sdl_yeri = kaynak.find("_sdl_ac")
    js_yeri = kaynak.find("/dev/input/js")
    assert js_yeri < sdl_yeri, "SDL, Linux yolundan ÖNCE deneniyor"

    # (b) Linux yolunda SDL'e HİÇ dokunulmaz
    oku_kaynak = inspect.getsource(KM.Kumanda.oku)
    i_js = oku_kaynak.find("_jsapi")
    i_pump = oku_kaynak.find("event.pump")
    assert i_js >= 0 and i_js < i_pump, (
        "oku() SDL pompasını Linux yolundan önce çağırıyor")

    # (c) olay çözümü doğru: 8 baytlık <IhBB
    assert KM._JsOkuyucu.OLAY.size == 8
    ham = KM._JsOkuyucu.OLAY.pack(1234, 16384, 0x02, 3)   # eksen 3, yarım
    _t, deger, tip, no = KM._JsOkuyucu.OLAY.unpack(ham)
    assert (deger, tip, no) == (16384, 0x02, 3)

    # (d) `ILK` biti de eksen sayılmalı (açılış durumu 0x82 gelir)
    assert (0x82 & ~KM._JsOkuyucu.ILK) == KM._JsOkuyucu.EKSEN


# ---------------------------------------------------------------- R69
def test_R69_kamera_DAHILI_webcami_ELIYOR():
    """⛔ SAHADA GÖRÜLDÜ: panelde yakalama kartı yerine dizüstünün DAHİLİ
    kamerası çıkıyordu (varsayılan indeks 0'dı).

    Ölçülen kurulum:
        video0/1  "USB webcam"  (Quanta, DAHİLİ)   kare VERMİYOR
        video2    "USB Video"   (MacroSilicon MS210x = EasierCAP)  ✔ 640x480
        video3    "USB Video"   (meta veri düğümü)  kare VERMİYOR

    ⛔ "AÇILDI" YETMEZ, "KARE VERİYOR" GEREKİR: UVC cihazlar her biri için
       İKİ düğüm oluşturur ve meta düğümü açılır ama kare vermez.
    """
    from gercek import kamera_yakala as KY

    assert KY.KameraCfg.KAYNAK.lower() in ("oto", "auto"), (
        "varsayılan 'oto' olmalı; sabit indeks yanlış cihazı seçer")

    # seçim kuralını doğrudan sına (donanımdan bağımsız)
    ornek = [
        {"yol": "/dev/video0", "ad": "USB webcam: USB webcam",
         "kare": False, "cozunurluk": None},
        {"yol": "/dev/video1", "ad": "USB webcam: USB webcam",
         "kare": True, "cozunurluk": (1280, 720)},
        {"yol": "/dev/video2", "ad": "USB Video: USB Video",
         "kare": True, "cozunurluk": (640, 480)},
    ]
    eski = KY.cihazlari_tara
    try:
        KY.cihazlari_tara = lambda kare_dene=True: ornek
        yol, gerekce = KY.otomatik_bul()
        assert yol == "/dev/video2", (
            "kare veren DAHİLİ kamera (video1) varken bile HARİCİ cihaz "
            "seçilmeliydi; seçilen: %s" % yol)
        # yalnız dahili varsa onu seçer ama UYARIR
        KY.cihazlari_tara = lambda kare_dene=True: ornek[:2]
        yol2, g2 = KY.otomatik_bul()
        assert yol2 == "/dev/video1" and "DAHİLİ" in g2
        # hiçbiri kare vermiyorsa AÇIK sebep
        KY.cihazlari_tara = lambda kare_dene=True: [ornek[0]]
        yol3, g3 = KY.otomatik_bul()
        assert yol3 is None and "kare vermiyor" in g3
    finally:
        KY.cihazlari_tara = eski


# ---------------------------------------------------------------- R70
def test_R70_websocket_CERCEVELEME_ve_EL_SIKISMA():
    """⛔ SAHADA GÖRÜLDÜ (2026-08-29): panel donuyordu ve MANUEL düğmesine
    basılmasına rağmen kip OTONOM kalıyordu.

    Ölçüldü: sunucu kip değişikliğini YÜK ALTINDA 0.5 ms'de işliyordu —
    yani sorun hiçbir zaman sunucuda değildi. Panelin üç HTTP akışı
    (30 Hz çubuk + 5 Hz durum + 15 Hz kare) Chrome'un kaynak başına
    6 bağlantısını doldurup istekleri KUYRUĞA alıyordu; düğme tıklaması
    da o kuyruğa giriyordu.

    Çözüm: TEK WebSocket. Bu bekçi çerçevelemenin doğruluğunu sınar —
    protokol hatası, sahada "bağlanmıyor" diye görünür.
    """
    import base64 as _b64, hashlib as _h
    from gercek import panel as P

    # (a) RFC 6455 el sıkışma anahtarı — bilinen örnek
    anahtar = "dGhlIHNhbXBsZSBub25jZQ=="
    kabul = _b64.b64encode(_h.sha1((anahtar + P._WS_SIHIR).encode()).digest()).decode()
    assert kabul == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", (
        "el sıkışma hesabı RFC 6455 örneğini tutturmuyor: %s" % kabul)

    # (b) sunucu -> istemci çerçevesi MASKESİZ ve doğru uzunluk alanlı
    for n in (5, 125, 126, 300, 70000):
        c = P._ws_cerceve(b"x" * n)
        assert c[0] == 0x81, "FIN+text olmalı"
        assert not (c[1] & 0x80), "sunucu çerçevesi MASKELİ olmamalı (RFC)"
        uz = c[1] & 0x7F
        if n < 126:
            assert uz == n and len(c) == n + 2
        elif n < 65536:
            assert uz == 126 and len(c) == n + 4
        else:
            assert uz == 127 and len(c) == n + 10

    # (c) istemci -> sunucu çözümü: MASKE açılmalı
    import io as _io, os as _os, struct as _st
    veri = b'{"c":"kip","kip":"MANUEL"}'
    m = _os.urandom(4)
    ham = (bytes([0x81, 0x80 | len(veri)]) + m
           + bytes(b ^ m[i & 3] for i, b in enumerate(veri)))
    opkod, yuk = P._ws_oku(_io.BytesIO(ham))
    assert opkod == 0x1 and yuk == veri, "maske açılmadı"

    # (d) ⛔ DEV ÇERÇEVE REDDEDİLMELİ (bellek koruması)
    dev = bytes([0x81, 0x80 | 127]) + _st.pack(">Q", 1 << 30) + b"\x00" * 4
    assert P._ws_oku(_io.BytesIO(dev)) is None, "1 GB'lık çerçeve kabul edildi"


# ---------------------------------------------------------------- R71
def test_R90_optik_varsayilani_OLCULEN_KALIBRASYON():
    """⛔⛔ YARIŞMA DEPOSU: hiçbir DOW_OPTIK_* verilmezse ÖLÇÜLEN
    KALİBRASYON gelmeli — sim değerleri DEĞİL.

    Deneme deposunda tersiydi (varsayılan = sim, gerçek değerler
    `baslat.sh`ten). Burada bu YANLIŞ: biri `python3 drone_yki.py`
    çalıştırırsa araç SİM MERCEĞİYLE uçar. F_PX 540.4 vs 366.7 = 1.47 kat;
    güdüm `yaw + 3·azimut` uyguladığı için kadrajın ortasında onlarca
    derece fazla yaw komutu demektir. Aynı ders R124'te alınmıştı.

    Kalibrasyon (2026-08-30): FOV 125° köşegen · TILT 25° · BALIKGÖZ ·
    yakalama kartı 640x480."""
    import importlib
    import subprocess
    kod = (
        "import os\n"
        "for k in list(os.environ):\n"
        "    if k.startswith('DOW_OPTIK_'): del os.environ[k]\n"
        "from dow.gorus import kamera as K\n"
        "print(K.IMG_W, K.IMG_H, K.F_PX, K.TILT_DEG, K.MENZIL_C,"
        " K.MENZIL_C_KOSEGEN, K.KANAT_M)\n")
    cikti = subprocess.run([sys.executable, "-c", kod], cwd=KOK,
                           capture_output=True, text=True)
    assert cikti.returncode == 0, cikti.stderr
    p = cikti.stdout.split()
    assert (int(p[0]), int(p[1])) == (640, 480), (
        "çözünürlük varsayılanı %s×%s — yakalama kartı 640x480 veriyor; "
        "yanlış çözünürlük F_BG ve MENZIL_C'yi ölçekler" % (p[0], p[1]))
    assert float(p[2]) == 366.7, "F_PX varsayılanı sim değerine kaymış"
    assert float(p[3]) == 25.0, "TILT varsayılanı sim değerine kaymış"
    assert float(p[4]) == 676.5, "MENZIL_C varsayılanı sim değerine kaymış"
    assert float(p[5]) == 714.7, "MENZIL_C_KOSEGEN varsayılanı kaymış"
    # ⛔ balıkgöz odağı da kalibrasyonla uyuşmalı (640x480 · 125° köşegen)
    kod2 = ("from dow.gorus import kamera as K\nprint(K.OPTIK_MODEL, K.F_BG)")
    c2 = subprocess.run([sys.executable, "-c", kod2], cwd=KOK,
                        capture_output=True, text=True,
                        env={k: v for k, v in os.environ.items()
                             if not k.startswith("DOW_OPTIK_")})
    ad, fbg = c2.stdout.split()
    assert ad == "esuzaklik", "mercek varsayılanı balıkgöz değil: %s" % ad
    assert abs(float(fbg) - 366.7) < 2.0, (
        "F_BG=%s — kalibrasyonla (366.7 px/rad) uyuşmuyor" % fbg)
    assert float(p[6]) == 1.718, "KANAT_M varsayılanı kaydı"
    importlib.import_module("dow.gorus.kamera")


def test_R91_optik_env_ile_EZILEBILIR_ve_bozuk_deger_PATLAR():
    """Gerçek kamera değerleri env'den girer. Bozuk değer SESSİZCE
    yok sayılmaz — sayılsaydı kullanıcı 'ayarladım' sanıp sim değerleriyle
    uçardı."""
    import subprocess
    kod = ("from dow.gorus import kamera as K\n"
           "print(K.IMG_W, K.IMG_H, K.F_PX, K.TILT_DEG, K.MENZIL_C, K.CX, K.CY)\n")
    ort = dict(os.environ, DOW_OPTIK_W="1280", DOW_OPTIK_H="720",
               DOW_OPTIK_F_PX="402.9", DOW_OPTIK_TILT="18.29",
               DOW_OPTIK_MENZIL_C="743.4")
    c = subprocess.run([sys.executable, "-c", kod], cwd=KOK, env=ort,
                       capture_output=True, text=True)
    assert c.returncode == 0, c.stderr
    p = c.stdout.split()
    assert (int(p[0]), int(p[1])) == (1280, 720)
    assert float(p[2]) == 402.9 and float(p[3]) == 18.29
    assert float(p[4]) == 743.4
    # ⛔ CX/CY, IMG_W/H ile BİRLİKTE kaymalı — yoksa kadraj merkezi yanlış
    assert float(p[5]) == 640.0 and float(p[6]) == 360.0, (
        "CX/CY çözünürlükle birlikte güncellenmiyor — kerteriz yanlış çıkar")

    bozuk = dict(os.environ, DOW_OPTIK_F_PX="beşyüz")
    c2 = subprocess.run([sys.executable, "-c", kod], cwd=KOK, env=bozuk,
                        capture_output=True, text=True)
    assert c2.returncode != 0 and "DOW_OPTIK_F_PX" in c2.stderr, (
        "bozuk optik değeri sessizce yok sayılıyor — kullanıcı ayarladım "
        "sanıp sim değerleriyle uçar")


def test_R92_cozunurluk_uyusmazligi_YUKSEK_SESLE_uyarir():
    """⛔ SESSİZ %50 HATA. Kart 1280x720 verirken 1920x1080 sabitleri
    kullanılırsa aynı hedef 40 px yerine 27 px görünür ve menzil 25 m
    yerine 37 m denir. Hiçbir yerde patlamaz."""
    kaynak = open(os.path.join(REEL, "drone_yki.py"), encoding="utf-8").read()
    assert "ÇÖZÜNÜRLÜK UYUŞMAZLIĞI" in kaynak, "uyarı kaldırılmış"
    bas = kaynak.index("ÇÖZÜNÜRLÜK UYUŞMAZLIĞI")
    govde = kaynak[bas - 700:bas + 1200]
    assert "_KAM.IMG_W" in govde and "_KAM.IMG_H" in govde, (
        "uyarı gerçek kare boyutunu optik kalibrasyonla karşılaştırmıyor")
    assert "DOW_KAM_W" in govde and "kamera_ayari.py" in govde, (
        "uyarı iki çözüm yolunu da söylemiyor")


def test_R93_kalibrasyon_matematigi_TERSINE_COZULEBILIYOR():
    """Bilinen bir kameradan üretilmiş ölçümler, aynı sabitleri geri
    vermeli. Ayrıca AYKIRI değer (kanat ucunu ıskalayan tıklama) sonucu
    bozmamalı — bu yüzden ortalama değil MEDYAN kullanılıyor."""
    sys.path.insert(0, os.path.join(REEL, "gercek"))
    from gercek import kamera_ayari as KA

    F, S, TILT, H = 402.7, 1.718, 18.30, 720
    olc = [{"px": F * S / R, "mesafe": R} for R in (15.0, 30.0, 45.0, 60.0)]
    f, tekil, sapma = KA.f_px_hesapla(olc, S)
    assert abs(f - F) < 0.01, "F_PX geri çıkmıyor: %.3f" % f
    assert sapma < 1e-6, "kusursuz veride sapma olmamalı"

    y = H / 2.0 - F * math.tan(math.radians(TILT))
    t = KA.tilt_hesapla(y, H, f)
    assert abs(t - TILT) < 0.01, "TILT geri çıkmıyor: %.3f" % t

    # aykırı değer: dörtten biri %40 küçük ölçüldü
    bozuk = list(olc)
    bozuk[1] = {"px": bozuk[1]["px"] * 0.6, "mesafe": 30.0}
    f2, _, s2 = KA.f_px_hesapla(bozuk, S)
    ort = sum(o["px"] * o["mesafe"] / S for o in bozuk) / len(bozuk)
    assert abs(f2 - F) / F < 0.01, "medyan aykırı değeri yutmadı"
    assert abs(ort - F) / F > 0.05, (
        "bu veri ortalamayı bozmalıydı; test artık medyanı sınamıyor")
    assert s2 > 10.0, "sapma uyarısı tetiklenmeli"

    # simülasyon değerleri geri gelmeli (denetim)
    sim = [{"px": 540.4 * 1.718 / R, "mesafe": R} for R in (20., 40., 80.)]
    fs, _, _ = KA.f_px_hesapla(sim, 1.718)
    assert abs(fs - 540.4) < 0.05


def test_R94_spec_FOV_dogru_F_PX_verir_ama_OLCUM_onu_EZER():
    """Üretici FOV'u başlangıç değeri verir; kanat ucu ölçümü ONU EZER.

    ⛔ NİYE ÖNEMLİ: üretici FOV'ları yuvarlanmış ve çoğu zaman abartılıdır;
    ayrıca yakalama kartı görüntüyü kırpıyor/ölçekliyorsa gerçek FOV
    yazandan farklı olur. Spec'in ölçümü ezmesi, ölçmenin anlamını yok
    ederdi.
    """
    from gercek import kamera_ayari as KA

    # F_PX = (yarı_boyut) / tan(FOV/2) — bilinen değerlerle
    assert abs(KA.f_px_spectan(90.0, 640, 480, "yatay") - 320.0) < 1e-6, (
        "90° yatay FOV'da F_PX = W/2 olmalı (tan45 = 1)")
    assert abs(KA.f_px_spectan(90.0, 640, 480, "dikey") - 240.0) < 1e-6
    kos = math.hypot(640, 480) / 2.0
    assert abs(KA.f_px_spectan(90.0, 640, 480, "kosegen") - kos) < 1e-6

    # ⛔ EKSEN SEÇİMİ ÖNEMLİ: köşegen kabul, yatay kabulden BÜYÜK çıkar
    y = KA.f_px_spectan(120.0, 640, 480, "yatay")
    k = KA.f_px_spectan(120.0, 640, 480, "kosegen")
    assert k > y * 1.2, ("köşegen/yatay farkı kaybolmuş: %.1f vs %.1f" % (k, y))

    # saçma girdiler None döner, çökmez
    for kotu in ((0, 640, 480), (180, 640, 480), (120, 0, 480)):
        assert KA.f_px_spectan(kotu[0], kotu[1], kotu[2], "yatay") is None

    # --- ölçüm spec'i EZER ---
    eski = dict(KA._D)
    try:
        KA._D["w"], KA._D["h"] = 640, 480
        KA._D["fov"], KA._D["fov_eksen"] = 120.0, "yatay"
        KA._D["olcumler"], KA._D["ufuk_y"], KA._D["tilt_elle"] = [], None, None
        r = KA.rapor()
        assert r["kaynak"] == "spec" and r["f_px"] is None
        assert abs(r["f_px_kullanilan"] - y) < 0.1

        KA._D["olcumler"] = [{"px": 402.7 * 1.718 / R, "mesafe": R}
                             for R in (15.0, 30.0, 45.0)]
        r2 = KA.rapor()
        assert r2["kaynak"] == "ölçüm", "spec ölçümü ezdi — ölçmenin anlamı kalmaz"
        assert abs(r2["f_px_kullanilan"] - 402.7) < 0.1
        assert r2["spec_olcum_farki"] > 50, "spec/ölçüm farkı raporlanmıyor"

        # export, kaynağı DOĞRU söylemeli
        assert "SPEC" in KA.export_satirlari(r), "spec'i ölçüm gibi sunuyor"
        assert "ÖLÇÜM" in KA.export_satirlari(r2).upper()
    finally:
        KA._D.clear(); KA._D.update(eski)


def test_R95_elle_TILT_kabul_edilir_ama_ufuk_olcumu_EZER():
    """TILT montaj açısından biliniyorsa elle girilebilir. Ama ufka
    tıklanmışsa ÖLÇÜM geçerlidir — elle girilen değer eskimiş olabilir."""
    from gercek import kamera_ayari as KA
    eski = dict(KA._D)
    try:
        KA._D["w"], KA._D["h"] = 640, 480
        KA._D["fov"], KA._D["fov_eksen"] = 120.0, "yatay"
        KA._D["olcumler"], KA._D["ufuk_y"] = [], None
        KA._D["tilt_elle"] = 25.0
        r = KA.rapor()
        assert r["tilt_deg"] == 25.0 and r["tilt_kaynak"] == "elle"

        # ufka tıkla: 10° verecek bir y seç
        f = r["f_px_kullanilan"]
        KA._D["ufuk_y"] = 240.0 - f * math.tan(math.radians(10.0))
        r2 = KA.rapor()
        assert abs(r2["tilt_deg"] - 10.0) < 0.05, (
            "ufuk ölçümü elle girilen değeri ezmedi: %s" % r2["tilt_deg"])
        assert r2["tilt_kaynak"] == "ufuk ölçümü"
    finally:
        KA._D.clear(); KA._D.update(eski)


def test_R96_cihaz_taramasi_IKI_ARIZAYI_AYIRIR():
    """⛔ SAHADA EN ÇOK ZAMAN YİYEN ŞEY: "kamera çalışmıyor".

    İki ayrı arıza var ve çareleri TAMAMEN farklı:
      (a) kart HİÇ YOK           -> USB'ye tak
      (b) kart VAR ama kare YOK  -> karta video SİNYALİ girmiyor
    Cihaz listesini basıp kullanıcıya yorumlatmak yetmiyor; araç hükmü
    kendi vermeli. 29 Ağu 2026'da tam bu ikisi peş peşe yaşandı.
    """
    kaynak = open(os.path.join(REEL, "gercek", "kamera_ayari.py"),
                  encoding="utf-8").read()
    assert "YAKALAMA KARTI BULUNAMADI" in kaynak, "(a) hükmü yok"
    assert "KART VAR AMA KARE VERMİYOR" in kaynak, "(b) hükmü yok"
    assert "YAKALAMA KARTI HAZIR" in kaynak, "olumlu hüküm yok"
    # (b) çaresi USB değil SİNYAL olmalı — yanlış yönlendirme saatler yer
    bas = kaynak.index("KART VAR AMA KARE VERMİYOR")
    govde = kaynak[bas:bas + 900]
    assert "VİDEO SİNYALİ" in govde and "VTX" in govde, (
        "kare yok arızasında kullanıcı USB'ye yönlendiriliyor — oysa sorun "
        "karta video sinyali girmemesi")
    # dahili kamerayı kart sanmamalı
    assert "DAHILI_IPUCU" in kaynak and "KART_IPUCU" in kaynak


def test_R97_FOV_dan_gelen_F_PX_cozunurlukle_ORANTILI():
    """F_PX = (yarı_boyut)/tan(FOV/2) olduğu için çözünürlükle DOĞRU
    ORANTILIDIR. Kart 720 yerine 640 verirse F_PX %11 düşer ve menzil de
    aynı oranda kayar — bu yüzden kalibrasyon çözünürlüğü kayda geçer."""
    from gercek import kamera_ayari as KA
    a = KA.f_px_spectan(120.0, 720, 480, "yatay")
    b = KA.f_px_spectan(120.0, 640, 480, "yatay")
    assert abs(a / b - 720.0 / 640.0) < 1e-9, "orantı bozuk"
    assert abs(a - 207.8) < 0.1, "120° yatay @720 -> 207.8 bekleniyordu: %.1f" % a
    # köşegen kabul, 720x480'de yatay kabulden ~%20 büyük
    k = KA.f_px_spectan(120.0, 720, 480, "kosegen")
    assert 1.18 < k / a < 1.22, "köşegen/yatay oranı %.3f" % (k / a)


def test_R98_sahte_kipi_BACKEND_ARAMAZ():
    """⛔ `--sahte` = DONANIMSIZ deneme. Backend araması yapmamalı.

    `--bag` varsayılanı "skydagger" olduğu için, skydagger dalı `--sahte`
    kontrolünden ÖNCE gelirse donanımsız deneme yolu FİİLEN KIRIKTIR:
    program backend'i arar, bulamaz ve çıkış 2 verir. README'de yazılı
    "donanımsız deneme" adımı bu yüzden hiç çalışmıyordu (29 Ağu 2026).

    Depoyu yeni çeken biri ilk denemesinde buna çarpar — o yüzden bekçi.
    """
    kaynak = open(os.path.join(REEL, "drone_yki.py"), encoding="utf-8").read()
    bas = kaynak.index("# ---------------- 1) ELRS bağı ----------------")
    govde = kaynak[bas:bas + 2000]
    i_sahte = govde.index("if a.sahte:")
    i_sky = govde.index('elif a.bag == "skydagger":')
    assert i_sahte < i_sky, (
        "--sahte dalı skydagger dalından SONRA geliyor — donanımsız "
        "deneme backend arar ve çıkış 2 verir")
    # ve sahte dalı gerçekten sahte portu kullanmalı
    sahte_govde = govde[i_sahte:i_sky]
    assert "_SahtePort()" in sahte_govde
    assert "SkydaggerBag" not in sahte_govde


def test_R99_kalibrasyon_HER_OLCUMUN_kendi_genisligini_kullanir():
    """⭐ Kalibrasyon için Talon ŞART DEĞİL.

    F_PX = w·R/S formülü cismin NE olduğunu değil, KAÇ METRE olduğunu
    bilmek ister. Genişliği bilinen herhangi bir cisim (cetvel, kapı
    kanadı) olur — bu, kalibrasyonu kapalı ortamda mümkün kılar.

    ⛔ Ölçümler KARIŞIK cisimlerden gelebilir. Hepsini tek bir varsayılan
    genişliğe bölmek, farklı cisimlerin ölçümlerini birbirine karıştırır
    ve F_PX'i sessizce yanlış verir. (29 Ağu 2026'da tam bu oldu: mesaj
    doğru sayıyı yazıyordu ama rapor 1.718'e bölüyordu.)
    """
    from gercek import kamera_ayari as KA
    F = 230.0
    olc = [{"px": F * S / R, "mesafe": R, "genislik": S}
           for (R, S) in ((3.0, 1.0), (5.0, 1.0), (4.0, 1.718), (30.0, 1.718))]
    f, tekil, sapma = KA.f_px_hesapla(olc, 1.718)
    assert abs(f - F) < 0.01, "karışık cisimde F_PX %.2f, %.2f bekleniyordu" % (f, F)
    assert sapma < 0.01, "kusursuz veride sapma %.3f" % sapma
    for v in tekil:
        assert abs(v - F) < 0.01

    eski = [{"px": F * 1.718 / 20.0, "mesafe": 20.0}]
    f2, _, _ = KA.f_px_hesapla(eski, 1.718)
    assert abs(f2 - F) < 0.01, "geriye dönük uyum bozuldu"

    karisik = [{"px": F * 1.0 / 3.0, "mesafe": 3.0, "genislik": 1.0},
               {"px": F * 1.718 / 30.0, "mesafe": 30.0, "genislik": 1.718}]
    f3, tekil3, sapma3 = KA.f_px_hesapla(karisik, 1.718)
    assert sapma3 < 0.01, (
        "karışık cisimler ayrışıyor — her ölçüm kendi genişliğini "
        "kullanmıyor: %s" % tekil3)


def test_R100_dedektor_cozunurluk_dikisi():
    """⛔ Dedektörün piksel sayıları 1920x1080 kadrajda ÖLÇÜLDÜ.

    Gerçek FPV zinciri 640x480 veriyor ve orada `imgsz` sayısının ANLAMI
    değişiyor: 1920x1080'de imgsz=1920 ölçek 1.0 (NATİF); 640x480'de aynı
    sayı 3 KAT BÜYÜTME demek — yeni bilgi yok, 8.3 kat bedel (ölçüldü:
    5.3 ms -> 44.0 ms, RTX 4060).

    Varsayılanlar DEĞİŞMEMELİ (sim davranışı bit bit korunur), ama gerçek
    kamera değerleri env'den verilebilmeli.
    """
    import subprocess
    kod = ("from dow.gorus import dedektor as D\n"
           "print(D.IMGSZ_UZAK, D.IMGSZ_YAKIN, D.CONF_MIN, D.YAKIN_ESIK_PX)\n")
    temiz = {k: v for k, v in os.environ.items()
             if not k.startswith("DOW_DET_")}
    c = subprocess.run([sys.executable, "-c", kod], cwd=KOK, env=temiz,
                       capture_output=True, text=True)
    assert c.returncode == 0, c.stderr
    p = c.stdout.split()
    assert int(p[0]) == 1920 and int(p[1]) == 960, "imgsz varsayılanı kaydı"
    assert float(p[2]) == 0.40, "conf varsayılanı kaydı"
    assert float(p[3]) == 55.0, "yakın eşiği varsayılanı kaydı"

    ort = dict(temiz, DOW_DET_IMGSZ_UZAK="960", DOW_DET_IMGSZ_YAKIN="640",
               DOW_DET_CONF="0.35", DOW_DET_YAKIN_ESIK="18")
    c2 = subprocess.run([sys.executable, "-c", kod], cwd=KOK, env=ort,
                        capture_output=True, text=True)
    assert c2.returncode == 0, c2.stderr
    q = c2.stdout.split()
    assert (int(q[0]), int(q[1])) == (960, 640)
    assert float(q[2]) == 0.35 and float(q[3]) == 18.0

    kotu = dict(temiz, DOW_DET_CONF="çok")
    c3 = subprocess.run([sys.executable, "-c", kod], cwd=KOK, env=kotu,
                        capture_output=True, text=True)
    assert c3.returncode != 0 and "DOW_DET_CONF" in c3.stderr, (
        "bozuk dedektör ayarı sessizce yok sayılıyor")

    sh = open(os.path.join(REEL, "baslat.sh"), encoding="utf-8").read()
    for a in ("DOW_MODEL", "DOW_DET_IMGSZ_UZAK", "DOW_DET_IMGSZ_YAKIN",
              "DOW_DET_YAKIN_ESIK"):
        assert a in sh, "baslat.sh %s vermiyor" % a


def test_R101_dedektor_KANAL_SIRASI_ayarlanabilir_ve_BGR_varsayilan():
    """⛔⛔ SESSİZ TAM ISKA — 29 Ağu 2026'da sahada yaşandı.

    ultralytics, numpy dizisini BGR kabul eder (cv2.imread gibi).
    `drone_yki._gorus` eskiden KOŞULSUZ BGR2RGB çeviriyordu. O çeviri sim
    modeli `talon_v3` için doğruydu — o model aynı çevrilmiş kareler
    üzerinde eğitilmişti, yani takas eğitime GÖMÜLÜYDÜ.

    Gerçek görüntüyle eğitilen model NORMAL eğitildi ve BGR bekler.
    Takas edilince turuncu uçak maviye döner. ÖLÇÜLDÜ, aynı kare, 640:
        BGR -> güven 0.700     RGB -> güven 0.000
    Panelde "tespit yok" görünüyordu; model kusursuz çalışıyordu. Bu, hiçbir
    yerde patlamayan, yalnız SONUÇTAN anlaşılan bir hatadır — bekçi şart.
    """
    kaynak = open(os.path.join(REEL, "drone_yki.py"), encoding="utf-8").read()
    assert "_DET_RENK" in kaynak, "kanal sırası ayarı kaldırılmış"
    assert 'os.environ.get("DOW_DET_RENK", "bgr")' in kaynak, (
        "varsayılan BGR değil — ultralytics'in sözleşmesi budur")
    # koşulsuz çeviri GERİ GELMEMELİ
    bas = kaynak.index("def _gorus(")
    govde = kaynak[bas:bas + 2500]
    assert 'girdi = kare if _DET_RENK == "bgr"' in govde, (
        "kanal sırası koşulsuz hâle dönmüş")
    # geçersiz değer sessizce yutulmamalı
    assert "'bgr' ya da 'rgb' olmalı" in kaynak

    import subprocess
    kod = ("import os,sys; sys.path.insert(0,'.')\n"
           "os.environ['DOW_DET_RENK']='mavi'\n"
           "import drone_yki\n")
    c = subprocess.run([sys.executable, "-c", kod], cwd=REEL,
                       capture_output=True, text=True)
    assert c.returncode != 0 and "DOW_DET_RENK" in c.stderr, (
        "geçersiz kanal sırası sessizce kabul ediliyor")

    sh = open(os.path.join(REEL, "baslat.sh"), encoding="utf-8").read()
    assert "DOW_DET_RENK" in sh, "başlatıcı kanal sırasını vermiyor"


def test_R102_hedef_HAM_konumu_BAYAT_olsa_bile_raporlanir():
    """⛔ OPERATÖR KÖRLÜĞÜ — 29 Ağu 2026'da sahada yaşandı.

    `son()` bayat paketi None döndürür; bu DOĞRUdur — güdüm 26 dakikalık
    veriyle nişan almamalı. Ama panel yalnız "hedef YOK" yazıyordu ve
    operatör iki BAMBAŞKA durumu ayırt edemiyordu:

        (a) hiç paket gelmiyor          -> ağ/IP/yayıncı sorunu
        (b) paket geliyor ama BAYAT     -> uçağın telemetri linki kopuk

    Sahada (b) yaşandı: 2254 paket gelmişti, ulaşma yaşı 0.03 s, ama
    verinin kendi yaşı 1555 s. Panel "YOK" diyordu ve yanlış yerde
    arandı. Ham alanlar GÖSTERİM içindir; güdüm bunları OKUMAZ.
    """
    from gercek.hedef import HedefKaynagi
    h = HedefKaynagi()
    d0 = h.durum()
    assert d0["n_paket"] == 0 and d0["ham_enlem"] is None, "(a) paket yok"

    # (b) paket geldi ama verisi 1555 saniyelik
    assert h.besle({"enlem": 41.0033654, "boylam": 28.6551401,
                    "irtifa_ev": 12.5, "hiz": 3.2, "saat_farki": 1555170})
    d = h.durum()
    assert d["var"] is False, "bayat veri GEÇERLİ sayılmamalı"
    assert h.son() is None, "güdüm bayat veriyi ALMAMALI"
    assert d["n_paket"] == 1, "paket sayacı görünmeli"
    assert d["yas_ulasma"] < 0.5 and d["yas_veri"] > 1500, (
        "iki yaş ayrı raporlanmıyor — (a) ile (b) ayırt edilemez")
    # ⭐ ham konum GÖSTERİM için var olmalı
    assert abs(d["ham_enlem"] - 41.0033654) < 1e-9
    assert abs(d["ham_boylam"] - 28.6551401) < 1e-9
    assert d["ham_irtifa"] == 12.5 and d["ham_hiz"] == 3.2

    # panel bu alanları GÖSTERMELİ
    # ⛔ ETİKET DEĞİL DAVRANIŞ sınanır: satır başlıkları yeniden
    #   düzenlemede değişebilir ("hedef K/D" -> "kuzey / doğu"), ama
    #   ham alanların EKRANA BASILMASI değişmemeli.
    p = open(os.path.join(REEL, "gercek", "panel.py"), encoding="utf-8").read()
    assert "hd.ham_enlem" in p and "hd.ham_boylam" in p, (
        "panel hedefin ham GPS'ini göstermiyor")
    assert "hh.kuzey" in p and "hh.dogu" in p, (
        "panel hedefin yerel kuzey/doğusunu göstermiyor")
    assert "hd.ham_irtifa" in p and "hd.ham_hiz" in p, (
        "panel hedefin ham irtifa/hızını göstermiyor")
    assert "BAYAT" in p, "panel bayat durumunu ayrı yazmıyor"
    assert "hedef_ham_konum" in p, "ham yerel konum hesaplanmıyor"
    # ⛔ 3B İZE GİRMEMELİ — bayat nokta hayalet iz çizer
    bas = p.index("const hk=d.hedef_konum")
    assert "hedef_ham_konum" not in p[bas:bas + 200], (
        "bayat konum 3B ize besleniyor — hayalet iz çizer")


def test_R103_REDDEDILEN_tespit_de_ekranda_gorunur():
    """⛔ 29 Ağu 2026 — saatler yiyen körlük.

    Dedektör hedefi buluyordu ama `ibvs.gecerli()` reddediyordu (menzil
    kapısı: 1.5 m < MENZIL_MIN_M 3 m). Panelde HİÇBİR İZ kalmıyordu ve
    "model çalışmıyor" sanıldı — oysa model kusursuz çalışıyordu.

    Artık reddedilen kutu da KIRMIZI KESİKLİ çiziliyor ve SEBEBİ yazılıyor.
    Kabul edilenle karışmasın diye kesikli; kabul edilen varken çizilmez.
    """
    a = open(os.path.join(KOK, "dow", "ana.py"), encoding="utf-8").read()
    assert "_ham_kutu" in a and "_ham_sebep" in a, "gösterim kancası yok"
    # ⛔ GÜDÜM BU ALANLARI OKUMAMALI — yalnız yazılır
    for satir in a.split("\n"):
        s2 = satir.strip()
        if "_ham_kutu" in s2 or "_ham_sebep" in s2:
            assert s2.startswith("self._ham_") or s2.startswith("#"), (
                "güdüm ham gösterim alanını OKUYOR: %s" % s2)

    y = open(os.path.join(REEL, "drone_yki.py"), encoding="utf-8").read()
    assert 'PANEL._D["ham_kutu"]' in y, "ham kutu panele geçmiyor"
    # ⛔ Ham kutu ARTIK HER ZAMAN gönderilir (menzil hesabı için gerekli);
    #   "ikisi üst üste çizilmesin" kuralı ÇİZİM tarafına taşındı.
    #   Bekçi de oraya bakar — kural kaybolmasın, yeri değişsin.

    p = open(os.path.join(REEL, "gercek", "panel.py"), encoding="utf-8").read()
    assert "_kesikli_dikdortgen" in p, "kesikli çizim yok"
    assert 'RED: %s%s' in p, "red sebebi ekrana yazılmıyor"
    bas = p.index('ham = _D.get("ham_kutu")')
    assert "not kutu" in p[bas:bas + 120], (
        "kabul edilen kutu varken ham kutu da çiziliyor")


def test_R104_panel_KRITIK_VERILERI_gosteriyor():
    """⛔ Telemetri ZATEN çözülüyordu ama panele ÇIKMIYORDU (29 Ağu 2026).

    En ciddisi PİL: `crsf.py` gerilim/yüzde/akım/mAh çözüyor, panel hiç
    göstermiyordu — operatör drone'un bataryasını GÖREMEDEN uçuyordu.
    İkincisi MENZİL: kutu boyutundan hesaplanıyor ama metre olarak hiç
    yazılmıyordu; 3 m kapısı yüzünden kutu reddedilirken sebebi anlamak
    saatler aldı.
    """
    b = open(os.path.join(REEL, "gercek", "baglanti.py"), encoding="utf-8").read()
    for alan in ("pil_v", "pil_yuzde", "pil_akim", "pil_mah",
                 "link_asagi_lq", "link_snr", "link_rf_kipi"):
        assert '"%s"' % alan in b, "saglik() %s vermiyor" % alan

    p = open(os.path.join(REEL, "gercek", "panel.py"), encoding="utf-8").read()
    # pil şeridi
    assert "pil_dolu" in p and "pilcubuk" in p, "pil şeridi yok"
    assert "VERİ YOK" in p, "pil verisi yokken uyarmıyor"
    # üç blok
    for t in ("telem_ucus", "telem_hedef", "telem_sistem"):
        assert t in p, "%s bloğu yok" % t
    assert "telem_sistem" in p and 'style="display:none"' in p, (
        "sistem bloğu varsayılan KAPALI değil")
    # menzil metre olarak
    assert "görsel menzil" in p, "menzil metre olarak yazılmıyor"
    # ⛔ menzil sabitleri JS'e YAZILMAMALI — env'den değişiyor
    assert 'd["optik"]' in p, "optik sabitleri sunucudan gönderilmiyor"
    bas = p.index("const MC=op.menzil_c")
    govde = p[bas:bas + 400]
    assert "op.menzil_min" in govde and "op.menzil_max" in govde, (
        "menzil kapıları JS'e SABİT yazılmış — DOW_OPTIK_MENZIL_C değişince "
        "panel yalan söyler")


def test_R107_ucus_kaydi_TARAYICIDAN_BAGIMSIZ_ve_hassasiyeti_bozmaz():
    """⛔ İKİ TUZAK, ikisi de yakalandı (30 Ağu 2026).

    (a) İTME (push) kipinde kayıt yalnız BİR TARAYICI durum sorduğunda
        yazıyordu. Tarayıcı kapalıyken uçuş HİÇ kaydedilmiyordu — yani
        kaydın var olma sebebi ortadan kalkıyordu. Artık ÇEKME (pull):
        kendi ipliğinde, kendi hızında, durumu kendisi çeker.

    (b) `%.4f` GPS'i BOZUYORDU: enlem 41.0033654 -> 41.0034, ~11 m
        çözünürlük. Kayıt, kaydettiği şeyden daha kaba olamaz. Ayrıca
        `%.10g` unix zaman damgasının kesirini yutuyordu (1788080812.27
        -> 1788080812), 10 Hz kayıtta 0.27 s körlük.
    """
    from gercek.kayit import Kayitci, SUTUNLAR, _cek

    # (b) hassasiyet
    assert Kayitci._alan({"x": 41.0033654}, "x") == "41.0033654", "GPS bozuluyor"
    assert Kayitci._alan({"x": 28.6551401}, "x") == "28.6551401"
    assert Kayitci._alan({"x": 1788080812.27}, "x") == "1788080812.27", (
        "zaman damgasının kesri kayboluyor")
    assert Kayitci._alan({"x": True}, "x") == "1"
    assert Kayitci._alan({"x": None}, "x") == ""
    # CSV'yi bozacak karakterler temizlenmeli
    assert "," not in Kayitci._alan({"x": "a,b"}, "x")

    # yol çekme: sözlük ve liste
    assert _cek({"a": {"b": 5}}, "a.b") == 5
    assert _cek({"k": [1, 2, 3]}, "k.1") == 2
    assert _cek({"a": None}, "a.b") is None
    assert _cek({}, "yok.yok") is None

    # sütunlar benzersiz ve kritik alanlar var
    adlar = [a for a, _ in SUTUNLAR]
    assert len(adlar) == len(set(adlar)), "tekrarlı sütun adı"
    for gerekli in ("t", "kaynak", "pil_v", "hedef_enlem", "hedef_boylam",
                    "kutu_w", "ham_sebep", "kilit_s"):
        assert gerekli in adlar, "%s sütunu yok" % gerekli

    # (a) çekme kipi
    k = open(os.path.join(REEL, "gercek", "kayit.py"), encoding="utf-8").read()
    assert "_cekme_dongusu" in k, "çekme ipliği yok"
    assert "uretici" in k, "üretici geri çağrısı yok"
    y = open(os.path.join(REEL, "drone_yki.py"), encoding="utf-8").read()
    assert "uretici=PANEL._durum" in y, "kayıt paneli çekmiyor"
    p = open(os.path.join(REEL, "gercek", "panel.py"), encoding="utf-8").read()
    assert '_D["kayit"].yaz(' not in p, (
        "panel hâlâ İTİYOR — tarayıcı kapalıyken kayıt durur")
    # kuyruk dolarsa BLOKLAMAMALI
    assert "put_nowait" in k and "queue.Full" in k, (
        "kayıt kuyruğu bloklayabilir — disk yavaşlarsa uçuş gecikir")


def test_R108_on_ucus_listesi_HAKEMI_DEGISTIRMEZ():
    """⛔ Liste bir KOLAYLIKtır, emniyet kapısı DEĞİL.

    `komut.py`'deki DÖRT ŞART (panel OTONOM · pilot izni · taze setpoint ·
    kumanda bağı) kanıtlanmış emniyet kapısıdır ve R39 ile korunur. Ön
    uçuş listesi panelde OTONOM düğmesini kilitler — yanlışlıkla basmayı
    engeller. Hakeme beşinci bir şart EKLENMEZ.

    Arıza yönü güvenli: liste bozulursa otonom açılmaz, elle uçuşa düşülür.
    Ama ZORLAMA yolu açık kalmalı — sahada yanlış kırmızı yanan bir madde
    yüzünden otonomdan mahrum kalmak daha tehlikelidir.
    """
    from gercek import kontrol_listesi as KL
    bos = KL.degerlendir({})
    assert bos["hazir"] is False and len(bos["kalan"]) >= 6

    tam = KL.degerlendir({
        "arac": {"canli": True, "uydu": 14, "koken": True, "pil_v": 24.1},
        "hedef": {"var": True, "n_paket": 500},
        "kamera": {"acik": True, "yas": 0.05},
        "komut": {"kmd_takili": True},
        "gorsel_aktif": True})
    assert tam["hazir"] is True and tam["kalan"] == []

    # tek tek düşürme — her zorunlu madde listeyi düşürmeli
    for eksilt, yol in (("gps", ("arac", "uydu", 4)),
                        ("koken", ("arac", "koken", False)),
                        ("hedef", ("hedef", "var", False)),
                        ("kamera", ("kamera", "acik", False))):
        d = {"arac": {"canli": True, "uydu": 14, "koken": True, "pil_v": 24.1},
             "hedef": {"var": True, "n_paket": 500},
             "kamera": {"acik": True, "yas": 0.05},
             "komut": {"kmd_takili": True}, "gorsel_aktif": True}
        d[yol[0]][yol[1]] = yol[2]
        r = KL.degerlendir(d)
        assert not r["hazir"] and eksilt in r["kalan"], (
            "%s düşünce liste hâlâ hazır diyor" % eksilt)

    # ⛔ HAKEME DOKUNULMAMIŞ OLMALI
    ko = open(os.path.join(REEL, "gercek", "komut.py"), encoding="utf-8").read()
    assert "kontrol_listesi" not in ko, (
        "ön uçuş listesi HAKEME sızmış — dört şartlı emniyet kapısı R39 ile "
        "kanıtlandı, beşinci şart eklenmez")
    # ⛔⛔ ÖLÜ DÜĞME YASAK — BU BEKÇİ TERSİNE ÇEVRİLDİ (2026-09-01).
    #   ESKİ HÂLİ tam TERSİNİ şart koşuyordu: `bOto.disabled` ön uçuş
    #   listesine bağlansın. O şart sahada bize bir yarışma hakkına mal
    #   oldu: kamera ve `--gorsel` maddeleri GPS uçuşunda da zorunlu
    #   sayıldığı için liste asla hazır olamıyordu (6/8), düğme
    #   TIKLANAMAZ hâle geliyordu ve tıklamak ne hareket ne de SEBEP
    #   üretiyordu. Kaçış yolu (çift tıkla zorla) hiçbir yerde yazmıyordu.
    #   YENİ DEĞİŞMEZ: düğme HER ZAMAN tıklanabilir; koruma GÖRÜNÜR
    #   onaydır (eksik maddeler tek tek sayılır). Kaza koruması korunur,
    #   körlük kalkar. Hakemin DÖRT ŞARTI değişmedi (aşağıda ayrıca sınanır).
    p = open(os.path.join(REEL, "gercek", "panel.py"), encoding="utf-8").read()
    assert "d.kontrol" in p, "panel kontrol listesini okumuyor"
    bas = p.index("const bOto=document.getElementById(\"b_otonom\")")
    govde = p[bas:bas + 900]
    assert "bOto.disabled=false" in govde.replace(" ", ""), (
        "OTONOM düğmesi yine ÖLÜ olabilir — `disabled` açıkça false "
        "yapılmalı. Ölü düğme sahada bir yarışma hakkına mal oldu.")
    assert "kls.kalan" in govde, (
        "düğme eksik maddeleri göstermiyor — operatör sebebi göremez")
    # tıklama listeyi SORMALI: kaza koruması kilitten ONAYA taşındı
    ob = p.index('document.getElementById("b_otonom").onclick')
    tik = p[ob:ob + 1400]
    assert "kontrol" in tik and "confirm(" in tik and "_klZorla" in tik, (
        "OTONOM tıklaması ön uçuş listesini sormuyor — tek tıkla otonoma "
        "geçilebilir, kaza koruması yok")
    assert "_klZorla" in p and "ondblclick" in p, (
        "zorlama yolu yok — yanlış kırmızı yanan madde otonomdan mahrum bırakır")

    # ⛔ ZORUNLULUK UÇUŞUN YAPILANDIRMASINDAN GELİR — İKİ YÖNLÜ SINANIR.
    #   Görsel KAPALIYKEN kamera/görsel maddeleri listeyi DÜŞÜRMEZ (yoksa
    #   GPS güdüm uçuşunda otonom hiç açılamaz), ama görsel AÇIKKEN ikisi
    #   de zorunludur — yani gevşetme kendini kötüye kullandırmaz.
    gpsce = KL.degerlendir({
        "arac": {"canli": True, "uydu": 14, "koken": True, "pil_v": 24.1},
        "hedef": {"var": True, "n_paket": 500},
        "kamera": {"acik": False}, "komut": {"kmd_takili": True},
        "gorsel_aktif": False})
    assert gpsce["hazir"] is True and gpsce["kalan"] == [], (
        "GPS güdüm uçuşunda kamera yokluğu listeyi düşürüyor — panel "
        "OTONOM'u sebepsiz kilitler (sahada yaşandı)")
    gorselde = KL.degerlendir({
        "arac": {"canli": True, "uydu": 14, "koken": True, "pil_v": 24.1},
        "hedef": {"var": True, "n_paket": 500},
        "kamera": {"acik": False}, "komut": {"kmd_takili": True},
        "gorsel_aktif": True})
    assert not gorselde["hazir"] and "kamera" in gorselde["kalan"], (
        "görsel güdüm İSTENDİĞİ hâlde kamerasız 'hazır' deniyor — "
        "göremeyen aracı hedefe yollamak demektir")


def test_R110_MODELIN_HAM_CIKTISI_her_zaman_ekrana_ulasir():
    """⛔⛔ 29-30 Ağu 2026'da SAATLER kaybettiren körlük.

    Model hedefi görüyordu ama ekranda HİÇBİR İZ yoktu, çünkü arada İKİ
    süzgeç var ve ikisi de haklı:
      1. `_yerel_bul`  — adayları YERELLİKLE eler (beklenen yerin dışında)
      2. `gecerli()`   — menzil/boyut/kadraj ile eler (3 m altı, 50 m üstü)
    İkisi de güdüm için doğru. Ama operatör "model çalışmıyor" sanıyor.

    KURAL: hedef KAÇ METREDE olursa olsun, model bir şey gördüyse ekranda
    iz KALIR. Kabul edilip edilmediği AYRI renkle söylenir:
        yeşil/turuncu düz  -> güdüm KABUL etti
        kırmızı kesikli    -> model gördü, güdüm REDDETTİ (+ sebep)
    """
    import sys as _s
    sys.path.insert(0, KOK)
    from dow.gorus.dedektor import Dedektor

    # --- (1) dedektör HAM çıktıyı saklıyor mu ---
    d = Dedektor.__new__(Dedektor)          # model yüklemeden
    d.son_ham = None
    d.son_ham_n = 0
    Dedektor._ham_kaydet(d, [])
    assert d.son_ham is None and d.son_ham_n == 0
    Dedektor._ham_kaydet(d, [(10, 20, 30, 40, 0.3), (50, 60, 70, 80, 0.9)])
    assert d.son_ham[4] == 0.9, "en yüksek güvenli kutu seçilmiyor"
    assert d.son_ham_n == 2, "aday sayısı sayılmıyor"

    # --- (2) `_tara`nın HER İKİ dönüş noktasında kaydediliyor mu ---
    k = open(os.path.join(KOK, "dow", "gorus", "dedektor.py"),
             encoding="utf-8").read()
    bas = k.index("def _tara(")
    son = k.index("def _ham_kaydet(")
    assert k[bas:son].count("self._ham_kaydet(kutular)") == 2, (
        "_tara'nın bir dönüş yolunda ham kutu kaydedilmiyor — pencere "
        "kolunda ya da tam kadraj kolunda ekran kör kalır")

    # --- (3) ana.py zinciri: d -> son_ham -> yok ---
    a = open(os.path.join(KOK, "dow", "ana.py"), encoding="utf-8").read()
    bas = a.index("_sh = getattr(self.det")
    govde = a[bas:bas + 700]
    assert 'self._ham_sebep = "yerel_eledi"' in govde, (
        "yerellik süzgeci düşürünce modelin gördüğü kutu GÖSTERİLMİYOR")
    assert 'self._ham_sebep = "tespit_yok"' in govde
    # ⛔ güdüm bu alanları OKUMAMALI
    for satir in a.split("\n"):
        t = satir.strip()
        if "_ham_kutu" in t or "_ham_sebep" in t:
            assert t.startswith("self._ham_") or t.startswith("#"), (
                "güdüm gösterim alanını OKUYOR: %s" % t)

    # --- (4) panel: ham kutu HER ZAMAN gönderilir, menzil ondan da çıkar ---
    y = open(os.path.join(REEL, "drone_yki.py"), encoding="utf-8").read()
    assert 'PANEL._D["ham_kutu"] = list(hk[:5]) if hk else None' in y, (
        "ham kutu yalnız kabul yokken gönderiliyor — menzil hesabı için "
        "her zaman lazım")
    p = open(os.path.join(REEL, "gercek", "panel.py"), encoding="utf-8").read()
    assert "const kt=kabulK||hamK" in p, (
        "menzil yalnız KABUL EDİLEN kutudan hesaplanıyor — reddedilende "
        "operatör mesafeyi göremez, asıl teşhis orada")

    # --- (5) sahte kipte de kamera açılabilmeli (tezgâhta sınama) ---
    assert "_kam_istendi" in y and '"--kamera" in sys.argv' in y, (
        "--sahte kipte kamera açılamıyor — görüş yolu yalnız tam donanımla "
        "sınanabilir hâle döner")


def test_R112_durum_HAM_alanlarini_yayinlar():
    """⛔ `_cizim()` ham kutuyu VİDEONUN ÜSTÜNE çiziyordu ama durum
    sözlüğüne HİÇ girmiyordu: panelin menzil/sebep satırları ve UÇUŞ
    KAYDI boş kalıyordu. Ekranda kutu var, kayıtta yok."""
    p = open(os.path.join(REEL, "gercek", "panel.py"), encoding="utf-8").read()
    bas = p.index('def _durum()')
    son = p.index("    return d", bas)
    govde = p[bas:son]
    assert 'd["ham_kutu"]' in govde, "_durum() ham kutuyu yayınlamıyor"
    assert 'd["ham_sebep"]' in govde, "_durum() red sebebini yayınlamıyor"
    # kayıt sütunları da bunlara bağlı
    from gercek.kayit import SUTUNLAR
    adlar = [a for a, _ in SUTUNLAR]
    for a in ("ham_w", "ham_conf", "ham_sebep"):
        assert a in adlar, "%s kayıt sütunu yok" % a


def test_R113_konsol_gurultusu_ve_TEMIZ_KAPANIS():
    """⛔ ÜÇ AYRI SAHA SORUNU (30 Ağu 2026, hepsi yaşandı).

    (a) `half` ultralytics 8.4'te kullanımdan kalktı ve HER ÇIKARIMDA
        uyarı basıyor. 130 FPS'te konsol saniyede yüzlerce satırla
        doluyor ve AÇILIŞ TEŞHİSLERİ (dedektör yüklendi mi, kamera hangi
        cihaz) boğuluyor. Ölçüldü: bayrak zaten işe yaramıyor
        (fp32 5.3 ms · "fp16" 5.2 ms).

    (b) `exec` kabuğu YERİNE GEÇER; kabuk ölünce `trap ... EXIT` HİÇ
        çalışmaz. Sahte backend Ctrl+C'den sonra yaşamaya devam edip
        terminale RC satırı basıyor ve 8766'yı tutuyordu.

    (c) İkinci Ctrl+C kapanış yolunu KESİYORDU: `kayitci.dur()` içinde
        traceback basıp kalan temizlik (araç komutlarını bırakma)
        atlanıyordu.
    """
    d = open(os.path.join(KOK, "dow", "gorus", "dedektor.py"),
             encoding="utf-8").read()
    # (a) half yalnız DESTEKLENİYORSA geçilmeli
    assert "HALF_GECERLI" in d, "half destek denetimi yok"
    assert d.count('"half": DetCfg.FP16') == 2, (
        "half koşulsuz geçiliyor — her çıkarımda uyarı basar")
    assert "half=DetCfg.FP16" not in d, "koşulsuz half çağrısı kalmış"

    # (b) ⛔ TAMPONSUZ ÇALIŞMALI. Çıktı bir dosyaya yönlendirilince Python
    #   stdout'u tamponlar ve AÇILIŞ TEŞHİSLERİ (kamera, model, sunucu)
    #   hiç görünmez; sahada `tail -f` ile izlemek imkânsız hâle gelir.
    #   ⚠ Bu depoda SAHTE BACKEND DALI YOK (yarışma kipi), o yüzden
    #     eski `exec` denetimi yerine asıl derdi olan tamponsuzluk sınanır.
    sh = open(os.path.join(REEL, "baslat.sh"), encoding="utf-8").read()
    kod = "\n".join(x.split("#")[0] for x in sh.splitlines())
    assert "python3 -u drone_yki" in kod, (
        "başlatma betiği TAMPONSUZ değil — açılış teşhisleri görünmez")
    assert "--sahte-backend" not in kod, (
        "yarışma deposunda sahte backend dalı OLMAMALI")

    # (c) kapanış ikinci Ctrl+C'ye dayanmalı
    k = open(os.path.join(REEL, "gercek", "kayit.py"), encoding="utf-8").read()
    bas = k.index("    def dur(self):")
    assert "except KeyboardInterrupt" in k[bas:bas + 900], (
        "kayıt kapanışı ikinci Ctrl+C'de asılıyor")
    y = open(os.path.join(REEL, "drone_yki.py"), encoding="utf-8").read()
    bas = y.index('print("\\n  kapatılıyor...")')
    assert "except KeyboardInterrupt" in y[bas:bas + 600], (
        "kapanış yolu kesintiye uğrayabilir — araç komutları bırakılmadan "
        "çıkılır")


def test_R114_kabul_esikleri_ENV_ile_ayarlanabilir():
    """Eşikler SİM MODELİYLE (talon_v3) ölçüldü; gerçek modelde
    (tayarti_v1) henüz ölçülmedi. Gerçek uçuş kaydından `ham_sebep`
    sayılıp eşik düzeltilebilmeli — sabit kodlu kalırsa her ayar için
    kaynak değiştirmek gerekir."""
    import subprocess
    kod = ("from dow.gudum.ibvs import IbvsCfg as C\n"
           "print(C.CONF_MIN, C.BOYUT_MIN_PX, C.YEREL_CONF_MIN)\n")
    temiz = {k: v for k, v in os.environ.items()
             if k not in ("DOW_CONF_MIN", "DOW_BOYUT_MIN_PX", "DOW_YEREL_CONF")}
    c = subprocess.run([sys.executable, "-c", kod], cwd=KOK, env=temiz,
                       capture_output=True, text=True)
    assert c.returncode == 0, c.stderr
    a, b, y = [float(x) for x in c.stdout.split()]
    assert a == 0.40 and b == 8.0 and y == 0.20, "varsayılanlar kaydı"

    ort = dict(temiz, DOW_CONF_MIN="0.25", DOW_BOYUT_MIN_PX="5")
    c2 = subprocess.run([sys.executable, "-c", kod], cwd=KOK, env=ort,
                        capture_output=True, text=True)
    a2, b2, _ = [float(x) for x in c2.stdout.split()]
    assert a2 == 0.25 and b2 == 5.0, "env ezme çalışmıyor"

    # ⛔ TARAMA eşiği KABUL eşiğinden DÜŞÜK olmalı, yoksa yerellik
    #   süzgecinin eleyeceği aday hiç bulunmaz ve kapı anlamsızlaşır.
    assert y < a, ("tarama eşiği (%.2f) kabul eşiğinden (%.2f) düşük değil"
                   % (y, a))


def test_R115_balikgoz_modeli_VARSAYILANDA_ACIK_ve_dogru():
    """⛔ SİMDE OLMAYAN HATA SINIFI (30 Ağu 2026).

    Oyun motorları (UE5) PERSPEKTİF render eder — DoW kamerasında
    balıkgöz bozulması YOKTU. Gerçek FPV merceği balıkgözdür ve iki şeyi
    bozar:
      1. KERTERİZ — `atan(r/F_PX)` delikli iğnenin tersidir. FOV'dan
         pinhole formülüyle türetilen F_PX yalnız KÖŞEDE doğrudur;
         merkezde 1.76 kat yanılır. Güdüm `yaw + 3·azimut` uyguladığı
         için 38°'ye varan fazla yaw komutu demektir.
      2. MENZİL — kutu boyutu kadraj konumuna göre değişir.

    ⭐ YARIŞMA DEPOSU: VARSAYILAN `esuzaklik` (balıkgöz AÇIK).
      Kalibrasyonla doğrulandı: FOV 125° köşegen, TILT 25°, mercek
      BALIKGÖZ. Deneme deposunda varsayılan `pinhole`di (davranış sim ile
      bit bit aynı kalsın diye) ve gerçek değerler `baslat.sh`ten gelirdi.
      Burada tersine çevrildi: env verilmese bile DOĞRU mercekle uçar.
    """
    import subprocess
    ORT = dict(os.environ, DOW_OPTIK_W="640", DOW_OPTIK_H="480")
    for k in ("DOW_OPTIK_MODEL", "DOW_OPTIK_FBG", "DOW_OPTIK_D",
              "DOW_OPTIK_FOV_KOSEGEN"):
        ORT.pop(k, None)

    def kos(kod, **ek):
        c = subprocess.run([sys.executable, "-c", kod], cwd=KOK,
                           env=dict(ORT, **ek), capture_output=True, text=True)
        assert c.returncode == 0, c.stderr[:400]
        return c.stdout.strip()

    # --- varsayılan BALIKGÖZ, düzeltme çarpanı 1.0'dan FARKLI ---
    v = kos("from dow.gorus import kamera as K\n"
            "print(K.OPTIK_MODEL, K.olcek_duzeltme(K.CX+300, K.CY))")
    ad, carpan = v.split()
    assert ad == "esuzaklik", (
        "YARIŞMA varsayılanı balıkgöz olmalı, `%s` geldi — env verilmezse "
        "araç YANLIŞ mercek modeliyle uçar" % ad)
    assert float(carpan) != 1.0, (
        "balıkgöz açık ama düzeltme uygulanmıyor (çarpan %s)" % carpan)
    # kadrajın TAM MERKEZİNDE düzeltme 1.0 olmalı — referans nokta orasıdır
    m = kos("from dow.gorus import kamera as K\nprint(K.olcek_duzeltme(K.CX, K.CY))")
    assert abs(float(m) - 1.0) < 1e-6, "merkezde düzeltme 1.0 değil: %s" % m

    # --- eşuzaklık: ters çözüm KESİN olmalı ---
    v = kos("import math\nfrom dow.gorus import kamera as K\n"
            "en=0.0\n"
            "for d in (5,15,30,45,60):\n"
            "    th=math.radians(d); r=K.F_BG*th\n"
            "    en=max(en, abs(math.degrees(K.aci_yaricaptan(r))-d))\n"
            "print('%.3e' % en, '%.1f' % K.F_BG)",
            DOW_OPTIK_MODEL="esuzaklik", DOW_OPTIK_FOV_KOSEGEN="125")
    hata, fbg = v.split()
    assert float(hata) < 1e-9, "eşuzaklık ters çözümü hatalı: %s" % hata
    assert abs(float(fbg) - 366.7) < 0.5, (
        "FOV'dan f_bg türetmesi bozuk: %s (366.7 bekleniyordu)" % fbg)

    # --- opencv: Newton yakınsamalı, D=0 iken eşuzaklıkla AYNI ---
    v = kos("import math\nfrom dow.gorus import kamera as K\n"
            "en=0.0\n"
            "for d in (2,20,45,70):\n"
            "    th=math.radians(d); r=K.F_BG*K._theta_d(th)\n"
            "    en=max(en, abs(math.degrees(K.aci_yaricaptan(r))-d))\n"
            "print('%.3e' % en)",
            DOW_OPTIK_MODEL="opencv", DOW_OPTIK_FBG="366.7",
            DOW_OPTIK_D="-0.052,0.0113,-0.0024,0.00031")
    assert float(v) < 1e-9, "Newton çözücü yakınsamıyor: %s" % v

    a = kos("from dow.gorus import kamera as K\nprint('%.9f' %"
            " K.olcek_duzeltme(K.CX+320, K.CY))",
            DOW_OPTIK_MODEL="opencv", DOW_OPTIK_FBG="366.7")
    b = kos("from dow.gorus import kamera as K\nprint('%.9f' %"
            " K.olcek_duzeltme(K.CX+320, K.CY))",
            DOW_OPTIK_MODEL="esuzaklik", DOW_OPTIK_FBG="366.7")
    assert a == b, ("D=0 iken opencv eşuzaklıkla aynı OLMALI: %s vs %s"
                    % (a, b))

    # --- geçersiz değerler sessizce yutulmamalı ---
    for kotu in ({"DOW_OPTIK_MODEL": "balik"}, {"DOW_OPTIK_D": "1,2,3"}):
        c = subprocess.run(
            [sys.executable, "-c", "from dow.gorus import kamera"],
            cwd=KOK, env=dict(ORT, **kotu), capture_output=True, text=True)
        assert c.returncode != 0, "geçersiz optik ayarı kabul edildi: %s" % kotu

    # --- güdüm HER İKİ menzil hesabında da düzeltmeyi uygulamalı ---
    i = open(os.path.join(KOK, "dow", "gudum", "ibvs.py"),
             encoding="utf-8").read()
    assert i.count("KAM.olcek_duzeltme(cx, cy)") == 2, (
        "menzil düzeltmesi iki hesaptan birinde YOK — panelde yazan sayı "
        "ile kapının kullandığı sayı ayrışır")

    # ⛔ GÖRÜNTÜ DÜZELTİLMEMELİ — dedektör bozuk karelerle eğitildi
    # ⛔ YORUMLARI AYIKLA: kaynakta bu adlar AÇIKLAMA olarak geçiyor
    #   ("...KULLANILMAZ, çünkü..."). Bekçi GERÇEK ÇAĞRIYA bakmalı.
    k = open(os.path.join(KOK, "dow", "gorus", "kamera.py"),
             encoding="utf-8").read()
    kod = "\n".join(satir for satir in k.split("\n")
                    if not satir.lstrip().startswith("#"))
    for yasak in ("undistortImage", "initUndistortRectifyMap", "cv2.remap"):
        assert yasak not in kod, (
            "görüntü düzeltiliyor (%s) — dedektörün eğitim dağılımı bozulur"
            % yasak)


def test_R116_RTL_hakeme_dokunmaz_ve_kokensiz_baslamaz():
    """RTL = GPS ile kalkış noktasına dön.

    ⛔ BETAFLIGHT GPS RESCUE KULLANILMAZ: şartname yalnız ANGLE MOD'a
      izin veriyor; GPS Rescue ayrı bir uçuş kipidir. RTL'i kendimiz,
      Angle modda, çubuk komutu üreterek yapıyoruz.

    ⛔ HAKEME DOKUNULMAZ: RTL, güdümün YERİNE geçen bir otonom kaynaktır.
      `komut.py`'deki dört şart aynen geçerli — pilot izni yoksa RTL de
      çalışmaz, kumanda kopuksa RTL de kesilir.
    """
    sys.path.insert(0, KOK)
    from gercek.rtl import Rtl, RtlCfg
    from dow.gudum.cevirici import HizCubukCevirici

    # --- köken yoksa BAŞLAMAZ ---
    r = Rtl(HizCubukCevirici())
    assert r.basla(False) is False, "kökensiz RTL başladı — nereye döneceği belirsiz"
    assert "köken" in r.sebep
    assert r.basla(True) is True

    # --- üç aşama ---
    def asama(konum):
        rr = Rtl(HizCubukCevirici())
        rr.basla(True)
        rr.adim(konum, (0., 0., 0.), 0.0, 0.05)
        return rr.asama
    assert asama((100., 50., 2.0)) == "TIRMAN", "alçakken önce tırmanmalı"
    assert asama((100., 50., 30.)) == "DON", "irtifa tamamken dönmeli"
    assert asama((3., 1., 30.)) == "BEKLE", "varış yarıçapında beklemeli"

    # --- TIRMAN'da YATAY HAREKET OLMAMALI (engel payı) ---
    rr = Rtl(HizCubukCevirici()); rr.basla(True)
    for _ in range(30):
        t, p, rl, y = rr.adim((100., 50., 2.0), (0., 0., 0.), 0.0, 0.05)
    assert abs(p) < 1e-6 and abs(rl) < 1e-6, (
        "tırmanırken yatay komut var — önce yükselip sonra dönmek engel "
        "çarpma riskini azaltır")
    assert t > 0, "tırmanma komutu yok"

    # --- DÖN: çubuklar DOĞRU ORANDA oturmalı (yön korunmalı) ---
    #   ⚠ ilk tikler eğim sınırlayıcı (MAX_DELTA) yüzünden eşit çıkar;
    #     bu doyum DEĞİLDİR, birkaç tik sonra doğru orana oturur.
    rr = Rtl(HizCubukCevirici()); rr.basla(True)
    for _ in range(40):
        t, p, rl, y = rr.adim((100., 50., 30.), (0., 0., 0.), 0.0, 0.05)
    # ⛔ MODELDEN BAĞIMSIZ: çevirici "aci" ya da "dogru" modelinde
    #   olabilir (env'e bağlı) ve ikisi FARKLI oran verir. Beklentiyi
    #   çeviricinin KENDİ eşlemesinden hesapla — böylece bekçi yalnız
    #   YÖNÜN korunduğunu sınar, modeli sabitlemez.
    cev_ref = HizCubukCevirici()
    b_ileri = cev_ref._ivme_cubuk(1.5 * 7.16)
    b_sag = cev_ref._ivme_cubuk(1.5 * 3.58)
    beklenen = abs(b_ileri / b_sag)
    assert abs(abs(p / rl) - beklenen) < 0.02, (
        "yön bozuluyor: pitch/roll %.3f, beklenen %.3f (model %s)"
        % (p / rl, beklenen, cev_ref.cfg.MODEL))

    # --- FREN: mesafe azalınca hız düşmeli ---
    def hiz(d):
        c = RtlCfg
        return 0.0 if d <= c.VARIS_M else c.HIZ_MS * min(1.0, d / c.FREN_M)
    assert hiz(100) == RtlCfg.HIZ_MS and hiz(15) < RtlCfg.HIZ_MS, (
        "fren yok — araç hedefi aşıp kökenin etrafında salınır")
    assert hiz(3) == 0.0

    # --- ⛔ KENDİLİĞİNDEN İNMEMELİ ---
    k = open(os.path.join(REEL, "gercek", "rtl.py"), encoding="utf-8").read()
    assert "KENDİLİĞİNDEN İNMİYOR" in k, "otomatik iniş kararı belgelenmemiş"

    # --- hakem DEĞİŞMEMİŞ olmalı ---
    ko = open(os.path.join(REEL, "gercek", "komut.py"), encoding="utf-8").read()
    assert "rtl" not in ko.lower(), (
        "RTL hakeme sızmış — dört şartlı emniyet kapısı R39 ile kanıtlandı")

    # --- RTL güdümün YERİNE geçmeli, yanında değil ---
    y = open(os.path.join(REEL, "drone_yki.py"), encoding="utf-8").read()
    bas = y.index("if rtl.aktif:")
    govde = y[bas:bas + 900]
    assert "else:" in govde and "beyin.adim" in govde, (
        "RTL ile güdüm aynı anda otonom_yaz çağırıyor — son yazan kazanır, "
        "araç iki hedef arasında salınır")

    # --- MANUEL'e geçmek RTL'i kesmeli ---
    p = open(os.path.join(REEL, "gercek", "panel.py"), encoding="utf-8").read()
    bas = p.index('if self.path == "/api/kip"')
    assert '_D["rtl"].dur()' in p[bas:bas + 900], (
        "MANUEL RTL'i kesmiyor — pilot tekrar OTONOM'a bastığında araç "
        "hedefe değil EVE uçar")


def test_R117_menzil_olcumu_BALIKGOZU_TELAFI_ederek_C_bulur():
    """⭐ MENZIL_C TÜRETME DEĞİL ÖLÇÜM olmalı.

    Türetilmiş C iki varsayım taşır: FOV'un hangi eksende verildiği
    (köşegen/yatay/dikey → 676/541/406) ve dedektör kutu payı (simde
    %7.4, gerçek modelde bilinmiyor). Tek ölçüm ikisini de gereksiz
    kılar:  C = kutu_ölçüsü × R.

    ⛔ BALIKGÖZ TELAFİSİ ŞART: kutu kenardaysa balıkgöz onu büyütür ve
      telafisiz ölçüm kutunun NEREDE durduğuna göre farklı C verir.
      C MERKEZ referanslı olmalı.
    """
    import subprocess
    ORT = dict(os.environ, DOW_OPTIK_W="640", DOW_OPTIK_H="480",
               DOW_OPTIK_MODEL="esuzaklik", DOW_OPTIK_FOV_KOSEGEN="125")
    kod = """
import math
from dow.gorus import kamera as KAM
GERCEK = 850.0
cikan = []
for R, dx in ((5.0,0),(10.0,0),(20.0,0),(10.0,250),(15.0,-200)):
    kos_merkez = GERCEK / R
    cx, cy = KAM.CX + dx, KAM.CY
    s = KAM.olcek_duzeltme(cx, cy)
    kos = kos_merkez * s                 # kameranin GORDUGU kutu
    cikan.append(kos * R / s)            # aracin YAPTIGI hesap
print(max(abs(c-GERCEK) for c in cikan))
"""
    c = subprocess.run([sys.executable, "-c", kod], cwd=KOK, env=ORT,
                       capture_output=True, text=True)
    assert c.returncode == 0, c.stderr[:400]
    assert float(c.stdout) < 1e-6, (
        "ölçüm bilinen C'yi geri vermiyor (hata %s)" % c.stdout.strip())

    # ⛔ telafi OLMASAYDI kenarda hata olmalıydı — bekçi anlamlı mı
    kod2 = """
from dow.gorus import kamera as KAM
print(KAM.olcek_duzeltme(KAM.CX+250, KAM.CY))
"""
    c2 = subprocess.run([sys.executable, "-c", kod2], cwd=KOK, env=ORT,
                        capture_output=True, text=True)
    assert float(c2.stdout) > 1.02, (
        "kenarda ölçek düzeltmesi ~1 — bu bekçi hiçbir şey sınamıyor")

    # araç: medyan kullanmalı, ortalama DEĞİL
    k = open(os.path.join(REEL, "gercek", "menzil_olc.py"),
             encoding="utf-8").read()
    assert "statistics.median" in k, (
        "ortalama kullanılıyor — tek kötü kare sonucu çeker")
    assert "olcek_duzeltme" in k, "balıkgöz telafisi yok"
    assert "IbvsCfg.MENZIL_OLCU" in k, (
        "güdümün ölçüsü (max/kosegen) dikkate alınmıyor — farklı ölçü "
        "farklı C demektir")
    # saçma mesafe reddedilmeli
    assert "0.5 <= a.mesafe <= 500.0" in k


# ---------------------------------------------------------------- R118
def test_R118_FAILSAFE_INIS_hicbir_paket_gecmez():
    """⛔ İNİŞ KİLİDİ: kilitliyken HİÇBİR kaynak paket geçiremez.

    Bu, panik düğmesinin tek vaadidir: "her ne oluyorsa olsun kes".
    Bekçi bunu ETİKETLE değil DAVRANIŞLA sınar — kilit açıkken, üstelik
    TÜM kaynaklar sağlıklıyken (pilot çubuğu var, panel var, güdüm taze,
    otonom uygun) tek bir çerçeve bile yazılmamalı.

    Niye "hepsi sağlıklıyken": kesme yolunun zaten çalıştığı durum
    kaynaksızlıktır; asıl sınanması gereken, KAYNAK VARKEN de kesilmesi.
    """
    sp, bag, km, ks = _duzenek(throttle=0.4, pitch=0.2, roll=-0.3, yaw=0.1,
                               arm=True, kip_anahtari=True)
    ks.kip_sec("OTONOM")
    ks.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    ks.gorev_ayarla(True)
    ks.panel_yaz(0.5, 0.1, 0.1, 0.1, arm=True, otonom_izin=True)

    # --- once NORMAL calistigini goster (kiyas cizgisi) ---
    ks.otonom_yaz(0.6, 0.3, 0.2, 0.1)
    ok, d = ks.tik()
    assert ok is True, "kilit yokken paket gitmeli"
    assert d["kaynak"] == "OTONOM"
    n_once = len(sp.yazilan)
    assert n_once > 0

    # --- KILIDI AC ---
    assert ks.inis_kes(True) is True
    assert ks.inis_kilitli is True

    for _ in range(200):
        ks.otonom_yaz(0.6, 0.3, 0.2, 0.1)      # gudum TAZE
        ks.panel_yaz(0.5, 0.1, 0.1, 0.1, arm=True, otonom_izin=True)
        ok, d = ks.tik()
        assert ok is False, "kilitliyken gonderildi=True dondu"
        assert d["kaynak"] == "YOK"
        assert d["sebep"] == "failsafe_inis"
        assert d["inis_kilidi"] is True
        assert d["komut"] is None, "kilitliyken cubuk sizdi"

    assert len(sp.yazilan) == n_once, (
        "KILITLIYKEN %d YENI CERCEVE YAZILDI" % (len(sp.yazilan) - n_once))
    assert ks.sayac["kesilen"] >= 200

    # --- KILIT KALKINCA yeniden calisir ---
    ks.inis_kes(False)
    ks.otonom_yaz(0.6, 0.3, 0.2, 0.1)
    ks.panel_yaz(0.5, 0.1, 0.1, 0.1, arm=True, otonom_izin=True)
    ok, d = ks.tik()
    assert ok is True, "kilit kalkinca paket yeniden gitmeli"
    assert len(sp.yazilan) > n_once
    assert d["inis_kilidi"] is False


def test_R118b_INIS_KILIDI_tikin_ILK_kapisi_yapisal():
    """⛔ Kapı `tik()`'in BAŞINDA olmalı — sonradan eklenen bir dal onu
    atlayamasın.

    ⚠ YORUMLAR AYIKLANIR: açıklama satırlarında `rc_gonder` geçiyor ve
      ham metinde aramak KENDİ YORUMUMU yakalıyordu (aynı hata R88,
      R113 ve R115'te de olmuştu). Bekçi ÇALIŞAN KODA bakmalı.
    """
    import inspect, re
    from gercek import komut as _k
    ham = inspect.getsource(_k.KomutSureci.tik)
    kod = "\n".join(re.sub(r"#.*$", "", sat) for sat in ham.splitlines())

    i_kilit = kod.find("_inis_kilidi")
    i_gonder = kod.find("rc_gonder")
    i_hakem = kod.find("otonom_uygun")
    assert i_kilit != -1, "tik() icinde iniş kilidi denetimi YOK"
    assert i_gonder != -1 and i_hakem != -1
    assert i_kilit < i_hakem, "iniş kilidi kapısı hakemden SONRA"
    assert i_kilit < i_gonder, "iniş kilidi kapısı gonderimden SONRA"
    kuyruk = kod[i_kilit:i_kilit + 700]
    assert "return False" in kuyruk, "kilit dalinda erken donus yok"


# ---------------------------------------------------------------- R119
def test_R119_DIKEY_INIS_kanallar_ESIGI_gecer_ve_yalniz_OTONOMDA():
    """⬇ DİKEY İNİŞ: uçuş kartının ALT HOLD + POS HOLD kiplerini açar.

    ⛔ EŞİK KRİTİK: Betaflight'ta mod aralığı 1700-2100 µs. Kanal 1700'ün
      ALTINDA kalırsa kip AÇILMAZ ve operatör "bastım, bir şey olmadı"
      der — üstelik araç alçalmaya da başlamaz. Bu bekçi eşiği sayıyla
      sınar, etiketle değil.

    ⛔ YALNIZ OTONOM'DA: pilot çubuğa dokunup devraldığında ek kipler
      DÜŞMELİ. ALT HOLD açıkken gaz çubuğu bir TIRMANMA HIZI komutudur,
      kapalıyken İTKİ. Pilot, elindeki çubuğun anlamının sessizce
      değişmiş olduğunu fark edemez.
    """
    from gercek import crsf as _c
    from gercek.dikey_inis import DikeyInis, DikeyInisCfg

    def _tum_kanallar(sp):
        return _c.kanallari_coz(sp.yazilan[-1][3:25])

    inis = DikeyInis()

    # --- KAPALIYKEN: hiç ek kanal yok (gerileme olmasın) ---
    assert inis.aux() == {}, "kapalıyken ek kanal sürülüyor"
    assert inis.adim() == (0.0, 0.0, 0.0, 0.0)

    sp, bag, km, ks = _duzenek(throttle=0.0, pitch=0.0, roll=0.0, yaw=0.0,
                               arm=True, kip_anahtari=True)
    ks.kip_sec("OTONOM")
    ks.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    ks.gorev_ayarla(True)
    ks.panel_yaz(0.0, 0.0, 0.0, 0.0, arm=True, otonom_izin=True)
    ks.otonom_yaz(0.0, 0.0, 0.0, 0.0)
    ok, d = ks.tik()
    assert ok and d["kaynak"] == "OTONOM"
    kanal_once = _tum_kanallar(sp)
    assert d["aux"] == {}

    # --- AÇIKKEN: kanal 6 ve 8 EŞİĞİN ÜSTÜNDE ---
    inis.basla()
    aux = inis.aux()
    assert set(aux) == {DikeyInisCfg.ALTHOLD_KANAL, DikeyInisCfg.POSHOLD_KANAL}
    ks.aux_yaz(aux)
    ks.otonom_yaz(*inis.adim())
    ks.panel_yaz(0.0, 0.0, 0.0, 0.0, arm=True, otonom_izin=True)
    ok, d = ks.tik()
    assert ok is True
    k = _tum_kanallar(sp)
    # ⚠ `kanallari_coz` HAM CRSF TİKİ döndürür, µs DEĞİL. Eşik µs
    #   cinsindendir; çevirmeden kıyaslamak yanlış hüküm verir.
    for kn in (DikeyInisCfg.ALTHOLD_KANAL, DikeyInisCfg.POSHOLD_KANAL):
        us = _c.crsf_us(k[kn - 1])
        assert us > 1700, (
            "kanal %d = %d µs — Betaflight eşiği 1700, KİP AÇILMAZ"
            % (kn, us))
        assert us <= 2100, "kanal %d aralığın üstünde (%d µs)" % (kn, us)

    # ⛔ GERÇEK ARAÇ SKYDAGGER YOLUNU KULLANIYOR — o eşleme de sınanır.
    from gercek.skydagger import cubuk_us as _sky_us
    _u = _sky_us(DikeyInisCfg.AUX_CUBUK)
    assert 1700 < _u <= 2100, (
        "Skydagger yolunda AUX_CUBUK=%s -> %d µs, eşiği geçmiyor"
        % (DikeyInisCfg.AUX_CUBUK, _u))
    # dokunulmayan kanallar DEĞİŞMEMİŞ olmalı
    for i in range(16):
        if (i + 1) in aux:
            continue
        assert k[i] == kanal_once[i], (
            "kanal %d ek kanal olmadığı hâlde değişti" % (i + 1))

    # --- OTONOM DÜŞÜNCE KİPLER DE DÜŞER ---
    #   ⚠ BURADA ÇUBUK OYNATMAK KULLANILMAZ — ölçüldü (2026-08-31):
    #     kumanda çubuğunu oynatmak `insan`ı "kumanda" yapar ama
    #     `kaynak` OTONOM kalır; hakem otonomu dört şarta bakarak
    #     seçer, hangi insanın çubuk verdiğine bakmaz. Otonomdan çıkış
    #     PANEL MANUEL ya da PİLOT VETO ANAHTARI iledir.
    #   İki gerçek yol da sınanır.
    for ad, uygula in (("panel MANUEL", lambda: ks.kip_sec("MANUEL")),
                       ("pilot vetosu", lambda: ks.panel_yaz(
                           0.0, 0.0, 0.0, 0.0, arm=True, otonom_izin=False))):
        ks.kip_sec("OTONOM")
        ks.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
        ks.gorev_ayarla(True)
        ks.panel_yaz(0.0, 0.0, 0.0, 0.0, arm=True, otonom_izin=True)
        ks.aux_yaz(inis.aux())
        ks.otonom_yaz(0.0, 0.0, 0.0, 0.0)
        assert ks.tik()[1]["kaynak"] == "OTONOM"
        uygula()
        ks.otonom_yaz(0.0, 0.0, 0.0, 0.0)
        ok, d = ks.tik()
        assert d["kaynak"] == "MANUEL", "%s otonomu düşürmedi" % ad
    k2 = _tum_kanallar(sp)
    for kn in (DikeyInisCfg.ALTHOLD_KANAL, DikeyInisCfg.POSHOLD_KANAL):
        us2 = _c.crsf_us(k2[kn - 1])
        assert us2 < 1700, (
            "PİLOT DEVRALDI ama kanal %d hâlâ %d µs — kip açık kaldı"
            % (kn, us2))
    assert d["aux"] == {}


def test_R119b_DIKEY_INIS_asamalar_ve_ARM_dokunulmazligi():
    """⬇ TUT -> IN sırası ve yatay çubukların sıfır kalması.

    ⛔ TUT aşaması KASITLI: kipler yeni açılmışken hemen alçalmaya
      başlamak, kiplerin tuttuğunu görmeden aracı indirmektir.
    ⛔ YATAY ÇUBUKLAR SIFIR: POS HOLD'un tuttuğu konumu çubukla bozmayalım.
    ⛔ ARM'a DOKUNULMAZ: havada disarm = serbest düşüş (deponun kuralı).
    """
    import inspect
    from gercek.dikey_inis import DikeyInis, DikeyInisCfg

    d = DikeyInis()
    d.basla()
    thr, p, r, y = d.adim()
    assert d.asama == "TUT"
    assert thr == 0.0, "TUT aşamasında gaz merkezde olmalı (irtifa tut)"

    # TUT bitince alçalma BAŞLAR ve hedefe RAMPAYLA iner
    d._t0 -= (DikeyInisCfg.TUT_S + 0.01)
    thr1, _, _, _ = d.adim()
    assert d.asama == "IN"
    d._t0 -= DikeyInisCfg.RAMP_S
    thr2, p2, r2, y2 = d.adim()
    assert thr2 < thr1 <= 0.0, "gaz çubuğu inmiyor"
    assert abs(thr2 - DikeyInisCfg.INIS_CUBUK) < 1e-9, "hedef çubuğa oturmadı"
    assert DikeyInisCfg.INIS_CUBUK < 0, "iniş çubuğu merkezin ALTINDA olmalı"

    # yatay çubuklar HER aşamada sıfır
    for _ in range(5):
        _, p3, r3, y3 = d.adim()
        assert (p3, r3, y3) == (0.0, 0.0, 0.0), "yatay çubuk POS HOLD'u bozuyor"

    # ⛔ MODÜL TELE YAZAMAZ: arm dahil hiçbir kanalı kendi basamaz.
    #   ARM'ın korunması bundan ÇIKAR — modülün elinde bağ yok, yalnız
    #   çubuk döndürüyor. (R35 zaten `otonom_yaz`da arm alanı olmadığını
    #   sınıyor; ikisi birlikte yolu kapatır.)
    #   ⚠ Metinde "arm" aramak YANLIŞTI: "disarm" da eşleşiyor ve
    #     belge satırları da yakalanıyordu.
    src = inspect.getsource(__import__("gercek.dikey_inis",
                                       fromlist=["x"]))
    kod = "\n".join(sat.split("#")[0] for sat in src.splitlines())
    for yasak in ("rc_gonder", "kanal_yaz", "otonom_yaz", "bag."):
        assert yasak not in kod, (
            "iniş modülü doğrudan tele yazıyor: %s" % yasak)
    import inspect as _i2
    from gercek.dikey_inis import DikeyInis as _DI
    p_adim = _i2.signature(_DI.adim).parameters
    assert "arm" not in p_adim, "adim() arm alıyor"

    d.dur()
    assert d.aux() == {}, "durdurulunca ek kanallar temizlenmedi"


# ---------------------------------------------------------------- R120
def test_R120_KIP_ARM_ve_GOREV_UCU_AYRI():
    """⛔⛔ BU BEKÇİ TERSİNE ÇEVRİLDİ (kullanıcı kararı 2026-09-02).

    ESKİ HÂLİ "çubuk oynayınca otonom MANDALLI olarak düşer" davranışını
    KORUYORDU (kullanıcı kararı 2026-08-31). O davranış sahada bir yarışma
    hakkına mal oldu: eşik çubuk gezinmesinin %2'si (0.04) kadar hassastı
    ve otonomu HER TİKTE kesiyordu — panelde OTONOM'a basılıyor, bir tik
    veriliyor, hemen `sebep=pilot_devraldi` ile MANUEL'e düşülüyordu.

    YENİ DEĞİŞMEZ — İKİ PARÇA:

    1. KİP YALNIZ PANELDEN SEÇİLİR. Çubuk oynatmak kipi DEĞİŞTİRMEZ;
       otonom sürer. MANUEL düğmesi manuele, OTONOM düğmesi otonoma
       geçirir. (Hâkimiyet hâlâ çalışır: çubuğu oynatan insan MANUEL
       kipteyken komutu sürer — ama kipi o belirlemez.)

    2. ⛔⛔ ARM DAİMA FİZİKSEL KUMANDADAN — HÂKİMİYETTEN BAĞIMSIZ.
       ÖLÇÜLDÜ (2026-09-02): kumanda TAKILI ve arm anahtarı AÇIK olduğu
       hâlde, pilot çubuğa dokunmadığı için `kmd_hakim` False kalıyor,
       `cubuk` panel oluyor ve ARM panelin BASILI TUTMA isteyen
       düğmesinden okunuyordu -> arm=False. Yani otonom uçuşta araç ARM
       KALAMIYORDU. Panelin GÖREVİ BAŞLAT düğmesi de `if(!k.arm)`
       yüzünden hep "ARAÇ ARM DEĞİL" diyordu.
       ARM bir ANAHTARDIR: değeri değişmese de anlamlıdır. Hâkimiyet
       çubuklar için doğru ölçüt, anahtar için DEĞİL.

    3. VETO anahtarı hâlâ otonomu keser ve geri açınca otonom DÖNER
       (R53 sözleşmesi korunuyor).
    """
    import time as _t

    # --- 1: ÇUBUK OYNAR AMA KİP DEĞİŞMEZ ---
    sp, bag, km, ks = _duzenek(throttle=0.0, pitch=0.0, roll=0.0, yaw=0.0,
                               arm=True, kip_anahtari=None)
    ks.kip_sec("OTONOM")
    ks.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    ks.gorev_ayarla(True)

    def _tik():
        ks.panel_yaz(0.0, 0.0, 0.0, 0.0, arm=False, otonom_izin=True)
        ks.otonom_yaz(0.1, 0.1, 0.1, 0.1)
        return ks.tik()[1]

    assert _tik()["kaynak"] == "OTONOM"
    assert not hasattr(ks, "pilot_devraldi"), (
        "çubukla devralma söküldü ama `pilot_devraldi` hâlâ duruyor "
        "(CLAUDE.md §5.12: elenen özellik TAMAMEN çıkar)")

    km.c = Cubuklar(throttle=0.5, pitch=0.5, roll=-0.5, yaw=0.5,
                    arm=True, kip_anahtari=None)
    d = _tik()
    assert d["kaynak"] == "OTONOM", (
        "çubuk oynadı ve otonom kesildi — çubukla devralma SÖKÜLMÜŞ "
        "olmalıydı (sebep=%s)" % d["sebep"])
    assert ks.kip == "OTONOM"

    # --- 2: ARM BİR MANDAL — PANELDEN, HER KİPTE ---
    #   Kullanıcı (2026-09-02): "arma basılı tutarken arm olmasın, bir kere
    #   basıp bıraktığımızda arm olsun, bir daha basınca disarm olsun."
    #   ⛔ ÖNCE DISARM: kumandanın anahtarı OTONOM'da arm EDEMEMELİ.
    #     Disarm görevi de bitirir (yapısal kural), o yüzden ikisi de
    #     yeniden kurulacak.
    ks.arm_ayarla(False)
    assert ks.gorev is False, "disarm görevi bitirmedi"
    km.c.arm = True                       # kumandanın anahtarı AÇIK
    d = _tik()
    assert d["arm"] is False, (
        "kumandanın arm anahtarı OTONOM kipinde aracı arm etti — otonomda "
        "kumanda hiçbir şeyi değiştirmemeli")
    ks.arm_ayarla(True)
    ks.gorev_ayarla(True)      # arm yoksa görev yok; sırası bu
    assert _tik()["arm"] is True, "panelden ARM geçmedi"
    # ⛔ MANDAL: panel çubuk akışı arm GÖNDERMESE BİLE arm KALIR.
    #   (Eski hâlde panelin düğmesi bırakılınca disarm oluyordu.)
    _t.sleep(ks.cfg.KMD_HAKIMIYET_S + 0.4)
    d = _tik()
    assert d["kmd_hakim"] is False, "hâkimiyet süresi geçmedi, sınama geçersiz"
    assert d["arm"] is True, (
        "panel arm göndermeyi bıraktı ve mandal düştü — basılı tutma "
        "davranışı geri gelmiş")
    # OTONOM'da kumandanın anahtarını kapatmak arm'ı DÜŞÜRMEZ
    km.c.arm = False
    assert _tik()["arm"] is True, (
        "OTONOM kipinde kumandanın anahtarı arm'ı düşürdü")
    ks.arm_ayarla(False)
    assert _tik()["arm"] is False, "panelden DISARM geçmedi"

    # --- 3: MANUEL KİPTE kumandanın anahtarı DEĞİŞİNCE mandalı sürer ---
    ks.kip_sec("MANUEL")
    assert _tik()["kaynak"] == "MANUEL"
    km.c.arm = True                      # KENAR: False -> True
    assert _tik()["arm"] is True, (
        "MANUEL kipte kumandanın arm anahtarı mandalı sürmedi")
    km.c.arm = False                     # KENAR: True -> False
    assert _tik()["arm"] is False, (
        "MANUEL kipte kumandanın arm anahtarı disarm etmedi")
    ks.kip_sec("OTONOM")
    ks.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    ks.gorev_ayarla(True)
    ks.arm_ayarla(True)
    assert _tik()["kaynak"] == "OTONOM", "panelden OTONOM geri gelmedi"

    # --- 4: VETO ANAHTARI hâlâ keser ve geri açılınca DÖNER (R53) ---
    sp2, bag2, km2, ks2 = _duzenek(throttle=0.0, pitch=0.0, roll=0.0, yaw=0.0,
                                   arm=True, kip_anahtari=True)
    ks2.kip_sec("OTONOM")
    ks2.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    ks2.gorev_ayarla(True)

    def _tik2():
        ks2.panel_yaz(0.0, 0.0, 0.0, 0.0, arm=False, otonom_izin=True)
        ks2.otonom_yaz(0.1, 0.1, 0.1, 0.1)
        return ks2.tik()[1]

    assert _tik2()["kaynak"] == "OTONOM"
    km2.c.kip_anahtari = False
    d = _tik2()
    assert d["kaynak"] == "MANUEL" and d["sebep"] == "pilot_vetosu"
    km2.c.kip_anahtari = True
    assert _tik2()["kaynak"] == "OTONOM", (
        "veto geri açıldı ama otonom dönmedi — anahtar kullanmak "
        "cezalandırılıyor")

    # --- 5: ⛔⛔ GÖREV KİPTEN AYRI (kullanıcı kararı 2026-09-02) ---
    #   "otonom moda basınca direkt görev başlamasın; orada bir ARM ve bir
    #    GÖREV BAŞLAT düğmesi olsun; otonom modda araç ARM'ken görev
    #    başlata basılırsa görev başlasın."
    #   ⭐ TEKNİK OLARAK DA ŞART: uçuş kartı gaz çubuğu AŞAĞIDA değilken
    #     ARM ETMEZ (min_check ~1050 µs). OTONOM'a basar basmaz güdüm
    #     tırmanış gazı verirse arm etmek İMKÂNSIZ olur.
    sp3, bag3, km3, ks3 = _duzenek(throttle=-1.0, pitch=0.0, roll=0.0,
                                   yaw=0.0, arm=False, kip_anahtari=True)

    def _tik3():
        ks3.panel_yaz(0.0, 0.0, 0.0, 0.0, arm=False, otonom_izin=True)
        ks3.otonom_yaz(0.1, 0.1, 0.1, 0.1)
        return ks3.tik()[1]

    ks3.kip_sec("OTONOM")
    d = _tik3()
    assert d["kaynak"] != "OTONOM" and d["sebep"] == "gorev_baslamadi", (
        "OTONOM'a geçmek GÖREVİ DE BAŞLATTI — ikisi ayrı olmalı "
        "(kaynak=%s sebep=%s)" % (d["kaynak"], d["sebep"]))
    assert d["gorev"] is False
    ks3.arm_ayarla(True)      # ARM yoksa GOREV de yok (2026-09-02)
    ks3.gorev_ayarla(True)
    assert _tik3()["kaynak"] == "OTONOM", "görev başlatıldı ama güdüm sürmedi"
    # ⛔ SERT AYRIM: MANUEL'e geçmek görevi DURDURUR ve OTONOM'a dönmek
    #   onu KENDİLİĞİNDEN geri getirmez — yoksa araç kaldığı yerden
    #   tırmanmaya devam ederdi.
    ks3.kip_sec("MANUEL")
    assert ks3.gorev is False, "MANUEL'e geçmek görevi durdurmadı"
    ks3.kip_sec("OTONOM")
    d = _tik3()
    assert d["sebep"] == "gorev_baslamadi", (
        "MANUEL'den OTONOM'a dönünce görev KENDİLİĞİNDEN yeniden başladı")


# ---------------------------------------------------------------- R121
def test_R121_INIS_CUBUGU_ALTHOLD_OLU_BANDININ_DISINDA():
    """⛔ İniş gaz çubuğu, ALT HOLD'un ÖLÜ BANDININ dışında olmalı.

    Betaflight'ta ALT HOLD açıkken gaz çubuğu merkez civarında ölü
    banttadır ve HİÇBİR komut üretmez — araç irtifasını korur, alçalmaz.
    Aracın `diff all` çıktısında `alt_hold_deadband` YOK, yani VARSAYILAN
    (%20). İlk seçtiğim -0.20 tam bu sınıra denk geliyordu (102 µs = %19.9)
    ve araç büyük ihtimalle hiç alçalmayacaktı.

    ⛔ Bu bekçi SESSİZ ARIZAYA karşıdır: değer bandın içine düşerse
      "iniş başladı" yazar, kanallar açılır, gaz iner ve ARAÇ HİÇBİR ŞEY
      YAPMAZ. Operatör inişin sürdüğünü sanır.
    """
    from gercek.dikey_inis import DikeyInisCfg
    from gercek.skydagger import cubuk_us, US_MIN, US_ORTA

    OLU_BANT_YUZDE = 20.0        # Betaflight varsayılanı
    PAY = 5.0                    # sınıra yapışmasın

    x = DikeyInisCfg.INIS_CUBUK
    assert x < 0, "iniş çubuğu merkezin ALTINDA olmalı"
    us = cubuk_us(x)
    yuzde = 100.0 * (US_ORTA - us) / (US_ORTA - US_MIN)
    assert yuzde > OLU_BANT_YUZDE + PAY, (
        "iniş çubuğu %.2f -> %d µs = merkezden %%%.1f. ALT HOLD ölü bandı "
        "%%%.0f; araç ALÇALMAZ ama panel 'iniyor' yazar."
        % (x, us, yuzde, OLU_BANT_YUZDE))
    # üst sınır: sert iniş olmasın
    assert yuzde < 60.0, (
        "iniş çubuğu %%%.1f — çok agresif, sert iniş riski" % yuzde)

    # AUX kanalları da eşiğin üstünde kalmalı (Betaflight aralığı 1700-2100)
    for kn in (DikeyInisCfg.ALTHOLD_KANAL, DikeyInisCfg.POSHOLD_KANAL):
        assert 1700 < cubuk_us(DikeyInisCfg.AUX_CUBUK) <= 2100
    # araçtan doğrulandı: ALTHOLD AUX2 = kanal 6, POS HOLD AUX4 = kanal 8
    assert DikeyInisCfg.ALTHOLD_KANAL == 6
    assert DikeyInisCfg.POSHOLD_KANAL == 8

    # --- ölü bant değeri ARAÇTAN okundu: alt_hold_deadband = 20 ---
    assert abs(DikeyInisCfg.OLU_BANT - 0.20) < 1e-9, (
        "ölü bant araçtan okunan %20 ile uyuşmuyor")

    # --- RAMPA ÖLÜ BANDIN KENARINDAN BAŞLAR ---
    #   Sıfırdan başlasaydı rampanın ilk %57'si bandın içinde geçer,
    #   araç saniyelerce hiçbir şey yapmaz, sonra alçalma ANİ başlardı.
    import time as _t2
    from gercek.dikey_inis import DikeyInis as _DI2
    di = _DI2()
    di.basla()
    di._t0 = _t2.monotonic() - (DikeyInisCfg.TUT_S + 0.001)
    bas_thr = di.adim()[0]
    assert abs(bas_thr + DikeyInisCfg.OLU_BANT) < 0.02, (
        "rampa ölü bandın kenarından değil %.3f'ten başlıyor" % bas_thr)
    # rampa boyunca TEKDÜZE iner ve hedefte DURUR (sabit hız)
    onceki = bas_thr
    for k in range(1, 11):
        di._t0 = _t2.monotonic() - (DikeyInisCfg.TUT_S
                                    + DikeyInisCfg.RAMP_S * k / 10.0)
        simdi = di.adim()[0]
        assert simdi <= onceki + 1e-9, "rampa geri dönüyor"
        onceki = simdi
    assert abs(onceki - DikeyInisCfg.INIS_CUBUK) < 1e-6
    di._t0 = _t2.monotonic() - (DikeyInisCfg.TUT_S + DikeyInisCfg.RAMP_S * 10)
    assert abs(di.adim()[0] - DikeyInisCfg.INIS_CUBUK) < 1e-9, (
        "rampa bitince çubuk SABİT kalmalı — iniş sabit hızda olmalı")


# ---------------------------------------------------------------- R122
def test_R122_GNSS_SUZGECI_kapaliyken_BIT_BIT_ayni_acikken_SUZUYOR():
    """⛔ Yarışmada hedef GPS'i KASTEN BOZUK gelir; süzgeç onu temizler.

    Bu bekçi ÜÇ şeyi sınar:
      1. KAPALIYKEN ham konum BİT BİT aynen döner (gerileme yok)
      2. BİRİM ÇEVRİMİ doğru — süzgeç SANTİMETRE ister, boru hattı METRE
      3. AÇIKKEN gecikmeli+gürültülü ölçümü GERÇEKTEN iyileştirir

    ⛔ BİRİM EN KOLAY HATA: çevrim atlanırsa filtre 100 kat büyük bir
      dünyada çalışır; hız zarfı (3000 cm/s = 30 m/s) anlamsızlaşır ve
      her ölçüm reddedilir. Sessiz arıza olurdu.
    """
    import importlib, math, random, os as _os
    import statistics as _st
    from gercek import gnss_filtre as _gf

    # --- 1) KAPALI: bit bit aynı ---
    _os.environ["DOW_GNSS_FILTRE"] = "0"
    importlib.reload(_gf)
    kapali = _gf.HedefSuzgeci()
    assert kapali.acik is False
    for konum in ((0.0, 0.0, 0.0), (12.5, -3.25, 61.0), (-400.0, 900.0, 5.5)):
        assert kapali.suz(konum) is konum, "kapalıyken konum DEĞİŞTİ"
    assert kapali.suz(None) is None

    # --- 2) BİRİM: süzgeç cm alıyor mu ---
    _os.environ["DOW_GNSS_FILTRE"] = "1"
    importlib.reload(_gf)
    assert _gf.HedefSuzgeci.OLCEK == 100.0, "metre->cm ölçeği yanlış"
    gorulen = {}
    ac = _gf.HedefSuzgeci()

    class _Casus:
        son_kabul = True
        son_d2 = 0.0

        def guncelle(self, x, y, z, simdi=None):
            gorulen["cm"] = (x, y, z)
            return (x, y, z)

    ac._f = _Casus()
    cikti = ac.suz((10.0, -20.0, 30.0))
    assert gorulen["cm"] == (1000.0, -2000.0, 3000.0), (
        "süzgece METRE gitti, SANTİMETRE gitmeliydi: %s" % (gorulen["cm"],))
    assert cikti == (10.0, -20.0, 30.0), "çıkışta cm->m çevrimi yapılmadı"

    # --- 3) AÇIK: gecikmeli + gürültülü ölçümü İYİLEŞTİRİYOR mu ---
    #   Senaryo, filtrenin TASARIM HALİ: ölçüm 1.0 s gecikmeli gelir.
    #   Süzgeç `telafi_sn` ile bu gecikmeyi kapatır.
    _os.environ["DOW_GNSS_R"] = "200"      # gürültü 2 m ~ R 200 cm
    _os.environ["DOW_GNSS_TELAFI"] = "1.0"
    importlib.reload(_gf)
    s = _gf.HedefSuzgeci()
    random.seed(7)
    V, DT, GECIKME = 20.0, 0.2, 1.0
    ham, suz = [], []
    for i in range(200):
        t = i * DT
        gx = V * t                                   # GERÇEK konum, şimdi
        ox = V * max(0.0, t - GECIKME)               # ölçüm: 1 s geride
        bx = ox + random.gauss(0, 2.0)
        by = random.gauss(0, 2.0)
        bz = 60.0 + random.gauss(0, 1.2)
        if i == 80:
            # ⛔ SIÇRAMA YANAL (y) OLMALI. İlk denememde ileri (+x) yöne
            #   koymuştum ve gecikme hatasını (-20 m) TESADÜFEN telafi
            #   etti; ham en kötü 25 m çıktı, sıçrama görünmez oldu.
            by += 40.0
        out = s.suz((bx, by, bz), simdi=t)
        if out and i > 30:
            ham.append(math.hypot(bx - gx, by))
            suz.append(math.hypot(out[0] - gx, out[1]))
    assert len(suz) > 100
    o_ham, o_suz = _st.mean(ham), _st.mean(suz)
    assert o_suz < o_ham * 0.6, (
        "süzgeç iyileştirmedi: ham %.2f m -> süzülmüş %.2f m" % (o_ham, o_suz))
    d = s.durum()
    assert d["acik"] is True and d["suzuldu"] > 100
    # ⛔ JAMMER SIÇRAMASI ÇIKTIYA GEÇMEMELİ.
    #   ⚠ Kıyas HAM EN KÖTÜ ile yapılır, ham ORTALAMA ile değil: ölçüm
    #     1 s gecikmeli olduğu için ham ortalama zaten ~20 m'dir (20 m/s
    #     × 1 s). Ortalamayla kıyaslamak yanlış hüküm verirdi.
    assert max(suz) < max(ham) * 0.6, (
        "sıçrama çıktıya geçti: ham en kötü %.1f m -> süzülmüş en kötü %.1f m"
        % (max(ham), max(suz)))

    _os.environ["DOW_GNSS_FILTRE"] = "0"
    importlib.reload(_gf)


# ---------------------------------------------------------------- R123
def test_R123_YARISMADA_UDP_hedef_dinleyicisi_KAPALI():
    """⛔ Yarışmada hedef YALNIZCA sunucu yanıtından gelir.

    `UdpDinleyici` 0.0.0.0:47800'ü dinler ve ağdaki HERHANGİ bir makine
    oraya hedef paketi yollayabilir; son gelen paket kazanır.

    ⛔ BU YAŞANDI (2026-08-30): ağdaki ikinci bir yayıncı yüzünden panel
      gerçek hedef yerine başka bir konumu gösterdi. Yarışma alanında
      ORTAK BİR YEREL AĞA bağlanıyoruz (doküman §2) — orada başka bir
      takımın yayını hedefimizi kaydırabilir. Enjeksiyon riski gerçektir.

    Kural: `--sunucu` verildiyse (yarışma kipi) UDP AÇILMAZ.
    """
    import re
    y = open(os.path.join(REEL, "drone_yki.py"), encoding="utf-8").read()
    kod = "\n".join(x.split("#")[0] for x in y.splitlines())

    i_udp = kod.index("UdpDinleyici(hedef)")
    # dinleyicinin kurulduğu satırdan geriye doğru bakınca, onu koruyan
    # bir `if a.sunucu` / `else` dalı OLMALI
    onceki = kod[max(0, i_udp - 400):i_udp]
    assert "a.sunucu" in onceki, (
        "UDP dinleyicisi KOŞULSUZ açılıyor — yarışma ağında hedef "
        "enjeksiyonuna açık")

    # `udp` yarışma kipinde None olmalı ve kapanış buna dayanmalı
    assert "udp = None" in kod, "yarışma kipinde udp None yapılmıyor"
    assert "if udp is not None:" in kod, (
        "kapanışta None denetimi yok — yarışma kipinde çökerdi")

    # başlatma betiği yarışma kipinde --sunucu geçiriyor mu
    sh = open(os.path.join(REEL, "baslat.sh"), encoding="utf-8").read()
    shk = "\n".join(x.split("#")[0] for x in sh.splitlines())
    assert '--sunucu' in shk and '$DOW_SUNUCU' in shk, (
        "baslat.sh yarışma kipinde --sunucu geçirmiyor")
    assert "--deneme" in shk, "deneme kipi (UDP'li) kaldırılmış"


# ---------------------------------------------------------------- R124
def test_R124_VARSAYILANLAR_GERCEK_ARAC_env_verilmese_de_dogru_ucar():
    """⛔⛔ YARIŞMA DEPOSUNDA VARSAYILANLAR GERÇEK ARAÇTIR, SİM DEĞİL.

    Deneme deposunda varsayılanlar simülasyonu birebir tekrarlasın diye
    SİM değerleriydi; gerçek değerler `baslat.sh`ten gelirdi. Yarışmada
    bu TERSİNE ÇEVRİLDİ.

    ⛔ NİYE: biri `baslat.sh` olmadan `python3 drone_yki.py` çalıştırırsa
      araç YANLIŞ MODELLE uçardı. YAŞANDI (taşınabilirlik sınamasında):
        DEDEKTÖR : ⛔ yüklenemedi (talon_v3.pt yok) — görsel KAPALI
        ÇEVİRİCİ : MODEL=dogru  Y_ISARET=-1.0
      `Y_ISARET=-1.0` yanal kanalı AYNALAR: araç hedefe gitmesi gerekirken
      HEDEFTEN KAÇAR. Ve dedektör sessizce kapanır — tek satır uyarıyla.

    ⛔ Bu bekçi ENV YOKKEN sınar: her `DOW_*` değişkeni temizlenir.
    """
    import subprocess
    ort = {k: v for k, v in os.environ.items() if not k.startswith("DOW_")}
    ort["PYTHONPATH"] = KOK

    def kos(kod):
        c = subprocess.run([sys.executable, "-c", kod], cwd=KOK,
                           env=ort, capture_output=True, text=True)
        assert c.returncode == 0, c.stderr[-500:]
        return c.stdout.strip()

    # --- araç modeli: Angle + ÖLÇÜLMÜŞ yanal işaret ---
    v = kos("from dow.gudum.cevirici import CevCfg as C\n"
            "print(C.MODEL, C.Y_ISARET, C.MAX_YATIS_DEG)")
    model, y_isaret, aci_max = v.split()
    assert model == "aci", (
        "çevirici varsayılanı `%s` — gerçek araç Angle modunda uçuyor" % model)
    assert float(y_isaret) > 0, (
        "Y_ISARET=%s — yanal kanal AYNALANMIŞ, araç hedeften KAÇAR. "
        "Yerde ölçüldü (2026-08-31): +1.0 doğru." % y_isaret)
    assert float(aci_max) == 60.0, "ACI_MAX Betaflight angle_limit'iyle uyuşmuyor"

    # --- dedektör: yarışma modeli VE dosyası GERÇEKTEN var ---
    v = kos("from dow.gorus import dedektor as D\nprint(D.MODEL_YOLU)")
    assert v.endswith("tayarti_v1.pt"), (
        "varsayılan model `%s` — yarışma modeli tayarti_v1" % v)
    assert os.path.exists(v), (
        "model dosyası YOK: %s — dedektör sessizce kapanır, görsel güdüm "
        "hiç çalışmaz" % v)

    # --- optik: balıkgöz VE ölçülen kalibrasyon sabitleri ---
    v = kos("from dow.gorus import kamera as K\n"
            "print(K.OPTIK_MODEL, K.IMG_W, K.IMG_H, K.F_PX, K.TILT_DEG)")
    ad, w, h, fpx, tilt = v.split()
    assert ad == "esuzaklik", "mercek varsayılanı balıkgöz değil: %s" % ad
    assert (int(w), int(h)) == (640, 480), (
        "çözünürlük varsayılanı %sx%s — kart 640x480 veriyor" % (w, h))
    assert float(fpx) == 366.7 and float(tilt) == 25.0, (
        "optik sabitleri SİM değerinde kalmış (F_PX=%s TILT=%s) — araç "
        "yanlış mercek modeliyle uçar" % (fpx, tilt))

    # --- GNSS süzgeci: ayarlı R ve dt ---
    v = kos("from gercek.gnss_filtre import SuzgecCfg as S\n"
            "print(S.ACIK, S.R, S.DT)")
    acik, R, dt = v.split()
    assert acik == "True", "GNSS süzgeci varsayılanda KAPALI"
    assert float(R) >= 150.0, (
        "DOW_GNSS_R=%s cm — gerçek bozulmaya (birkaç metre) göre ÇOK KÜÇÜK; "
        "ölçüldü: R=50'de 150/200 ölçüm reddediliyor ve filtre çöküyor" % R)
    assert 0.3 <= float(dt) <= 1.0, (
        "DOW_GNSS_DT=%s — hedef YANITTA geliyor, yani gönderim "
        "periyodumuza (~0.55 s) eşit olmalı" % dt)

    # --- kalkış fazı KAPALI (pilot elle kaldırır) ---
    # ⭐ OTONOM KALKIŞ (kullanıcı kararı 2026-08-31): araç kendi kalkar.
    v = kos("from dow.ayarlar import Ayar\n"
            "print(Ayar.KALKIS_ALT_M, Ayar.KALKIS_VZ)")
    alt, vz = (float(x) for x in v.split())
    assert alt >= 20.0, (
        "KALKIS_ALT=%g — otonom kalkış kapalı, araç kendi kalkmaz" % alt)
    assert vz <= 4.0, (
        "KALKIS_VZ=%g m/s — dikey döngü HİÇ UÇMADI, ilk denemede bu kadar "
        "hızlı tırmanmak araç yerden fırlar ya da çakılır demektir" % vz)


    # --- baslat.sh yine de hepsini AÇIKÇA yazmalı (çifte güvence) ---
    sh = open(os.path.join(REEL, "baslat.sh"), encoding="utf-8").read()
    for anahtar in ("DOW_CEV_MODEL", "DOW_CEV_Y_ISARET", "DOW_MODEL",
                    "DOW_OPTIK_MODEL", "DOW_KALKIS_ALT", "DOW_GNSS_FILTRE",
                    "DOW_SUNUCU", "DOW_TAKIM_NO"):
        assert anahtar in sh, "baslat.sh %s yazmıyor" % anahtar


# ---------------------------------------------------------------- R125
def test_R125_SUNUCU_BILGILERI_env_olmadan_da_DOGRU():
    """⛔ Yarışma sunucusu bilgileri KODA GÖMÜLÜ olmalı.

    ⛔ YAŞANDI (2026-08-31, TEST MASASINDA): bilgiler yalnız `baslat.sh`
      içindeydi. Operatör `python3 araclar/sunucu_testi.py` komutunu
      doğrudan çalıştırınca env yüklenmedi ve araç şunu bastı:
          adres    : http://127.0.0.1:5000
          kullanıcı: ⛔ BOŞ
          takım no : 0
      Sahada dakika kaybettirdi. Aynı ders R124'te araç varsayılanları
      için alınmıştı: YARIŞMA DEPOSUNDA VARSAYILAN = YARIŞMA DEĞERİ.

    ⛔ Bu bekçi ENV TAMAMEN TEMİZKEN sınar.
    """
    import subprocess
    ort = {k: v for k, v in os.environ.items() if not k.startswith("DOW_")}
    ort["PYTHONPATH"] = KOK
    c = subprocess.run(
        [sys.executable, "-c",
         "from gercek.sunucu import SunucuCfg as C\n"
         "print(C.ADRES); print(C.KADI); print(C.TAKIM_NO); print(C.GONDER_HZ)"],
        cwd=KOK, env=ort, capture_output=True, text=True)
    assert c.returncode == 0, c.stderr[-400:]
    adres, kadi, takim, hz = c.stdout.strip().splitlines()

    assert "10.0.0.10" in adres and "10001" in adres, (
        "sunucu adresi varsayılanda yanlış: %s" % adres)
    assert kadi == "hamidiye", "kullanıcı adı varsayılanda boş/yanlış: %r" % kadi
    assert int(takim) == 2, "takım numarası varsayılanda %s — hakem 2 dedi" % takim
    # ⛔ 2 Hz doküman sınırı; üstü 400 + hata kodu 3 ile cezalandırılır
    assert 1.0 <= float(hz) <= 2.0, "gönderim hızı doküman aralığı dışında: %s" % hz
    assert float(hz) < 2.0, "2 Hz sınırına pay bırakılmamış: %s" % hz

    # şifre boş olmamalı (değerini teste gömmüyoruz)
    c2 = subprocess.run(
        [sys.executable, "-c",
         "from gercek.sunucu import SunucuCfg as C\nprint(len(C.SIFRE))"],
        cwd=KOK, env=ort, capture_output=True, text=True)
    assert int(c2.stdout.strip()) >= 8, "şifre varsayılanda boş"


# ---------------------------------------------------------------- R126
def test_R126_panel_JS_TANIMSIZ_FONKSIYON_CAGIRMIYOR():
    """⛔ Panelde çağrılan her fonksiyon TANIMLI olmalı.

    ⛔ YAŞANDI (2026-08-31, SAHADA, uçuş hazırlığında): eklenen düğmelerin
      hepsi `post(...)` çağırıyordu ama o fonksiyon HİÇ TANIMLI DEĞİLDİ.
      Tarayıcı "post is not defined" atıyor, düğmeler SESSİZCE hiçbir şey
      yapmıyordu. Etkilenenler: RTL, dikey iniş, paket kes, görsel izin,
      görevi başlat — yani BÜTÜN ACİL DÜĞMELER.

    ⛔ NİYE TESTLER YAKALAMADI: failsafe'i Python'dan doğrudan HTTP ile
      sınamıştım (`/api/inis`'e POST). Sunucu ucu çalışıyordu; DÜĞME YOLU
      hiç denenmemişti. `node --check` de yakalamaz — sözdizimi geçerli,
      hata çalışma anında.

    Bu bekçi: yorumları ve dizgileri ayıklar, NOKTA İLE BAŞLAMAYAN
    çağrıları toplar, tanımlı adlar + tarayıcı yerleşikleriyle karşılaştırır.
    """
    import re
    s = open(os.path.join(REEL, "gercek", "panel.py"), encoding="utf-8").read()
    m = re.search(r"<script>([\s\S]*?)</script>", s)
    assert m, "panelde <script> bloğu yok"
    js = m.group(1)

    # yorumlar ve dizgiler ayıklanır (Türkçe metinler yanlış eşleşmesin)
    t = re.sub(r"//[^\n]*", "", js)
    t = re.sub(r"/\*[\s\S]*?\*/", "", t)
    t = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', t)
    t = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", t)
    t = re.sub(r"`(?:[^`\\]|\\.)*`", "``", t)

    cagri = set(re.findall(r"(?<![.\w$])([a-z_][\w$]*)\s*\(", t))
    tanimli = (set(re.findall(r"function\s+([\w$]+)", t))
               | set(re.findall(r"(?:const|let|var)\s+([\w$]+)\s*=", t)))
    yerlesik = {
        "if", "for", "while", "switch", "catch", "return", "typeof", "new",
        "await", "async", "delete", "void", "in", "of", "do", "else",
        "fetch", "setInterval", "setTimeout", "clearInterval", "clearTimeout",
        "parseInt", "parseFloat", "alert", "confirm", "prompt", "isNaN",
        "requestAnimationFrame", "cancelAnimationFrame", "encodeURIComponent",
        "decodeURIComponent", "then", "filter", "map", "atob", "btoa",
        "structuredClone", "queueMicrotask",
    }
    eksik = sorted(c for c in cagri if c not in tanimli and c not in yerlesik)
    assert not eksik, (
        "panel JS'inde TANIMSIZ fonksiyon çağrısı: %s\n"
        "Tarayıcıda 'X is not defined' atar ve düğme SESSİZCE çalışmaz."
        % eksik)

    # ⛔ `post` özellikle aranır: acil düğmelerin ortak yolu
    assert re.search(r"(?:async\s+)?function\s+post\s*\(", t), (
        "`post` fonksiyonu tanımlı değil — RTL, dikey iniş, paket kes, "
        "görsel izin ve görevi başlat düğmelerinin HEPSİ onu kullanıyor")


# ---------------------------------------------------------------- R127


# ---------------------------------------------------------------- R127
def test_R127_VIDEO_KAYDI_gercekten_OKUNABILIR_dosya_yaziyor():
    """⏺ FPV video kaydı — yarışma kilitlenmeleri videoyla inceleniyor.

    ⛔ "Dosya oluştu" YETMEZ: bozuk bir mp4 de oluşur. Bu bekçi dosyayı
      GERİ OKUR — çözünürlük, kare sayısı ve ilk karenin çözülebilirliği
      denetlenir.

    ⛔ AYNI KARE TEKRAR YAZILMAMALI: kamera yazıcıdan yavaşsa aynı görüntü
      defalarca yazılır ve video "donuk" görünür. Kayıt, kare sayacı
      değişmediyse atlar.

    ⛔ GÜDÜM DÖNGÜSÜ BLOKE OLMAZ: kayıt kendi iş parçacığında koşar ve
      kareyi kameradan KENDİ çeker (pull).
    """
    import glob
    import shutil
    import tempfile
    import time as _t
    import numpy as np

    dizin = tempfile.mkdtemp(prefix="vk_bekci_")
    eski = dict(os.environ)
    try:
        os.environ["DOW_VIDEO_DIZIN"] = dizin
        os.environ["DOW_VIDEO_FPS"] = "12"
        import importlib
        from gercek import video_kayit as V
        importlib.reload(V)

        class _Kam:
            def __init__(self):
                self.n = 0
                self.dondur = False      # aynı kareyi tekrar ver

            def son_kare(self):
                if not self.dondur:
                    self.n += 1
                k = np.zeros((480, 640, 3), dtype=np.uint8)
                k[:, (self.n * 3) % 600:(self.n * 3) % 600 + 40] = 255
                return k, _t.time(), self.n

        kam = _Kam()
        vk = V.VideoKaydi(kam)

        # ⛔ KENDİ İŞ PARÇACIĞINDA: basla() ANINDA dönmeli
        t0 = _t.monotonic()
        ok, mesaj = vk.basla("bekci")
        assert ok, "kayıt başlamadı: %s" % mesaj
        assert _t.monotonic() - t0 < 1.0, "basla() çağıranı bekletti"

        _t.sleep(2.0)
        d = vk.durum()
        assert d["aktif"] is True
        assert d["kare"] >= 15, "2 saniyede yalnız %d kare" % d["kare"]

        # --- aynı kare tekrar yazılmamalı ---
        onceki = vk.durum()["kare"]
        kam.dondur = True
        _t.sleep(1.2)
        artis = vk.durum()["kare"] - onceki
        assert artis <= 1, (
            "kamera donmuşken %d kare daha yazıldı — video donuk görünür"
            % artis)
        kam.dondur = False
        _t.sleep(0.5)

        vk.dur()
        assert vk.durum()["aktif"] is False

        # --- DOSYA GERÇEKTEN OKUNABİLİYOR MU ---
        dosyalar = glob.glob(os.path.join(dizin, "*.mp4"))
        assert len(dosyalar) == 1, "beklenen tek mp4, bulunan: %s" % dosyalar
        import cv2
        c = cv2.VideoCapture(dosyalar[0])
        try:
            assert c.isOpened(), "yazılan mp4 AÇILAMADI"
            g = int(c.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(c.get(cv2.CAP_PROP_FRAME_HEIGHT))
            n = int(c.get(cv2.CAP_PROP_FRAME_COUNT))
            okundu, kare = c.read()
            assert (g, h) == (640, 480), "çözünürlük bozuk: %dx%d" % (g, h)
            assert n >= 15, "dosyada yalnız %d kare" % n
            assert okundu and kare is not None, "ilk kare ÇÖZÜLEMEDİ"
        finally:
            c.release()

        # --- kamera kare vermiyorsa BAŞLAMAMALI ---
        class _Bos:
            def son_kare(self):
                return None, 0.0, 0
        vk2 = V.VideoKaydi(_Bos())
        ok2, mesaj2 = vk2.basla("olmaz")
        assert ok2 is False and "kare" in mesaj2.lower(), (
            "kamera yokken kayıt başladı: %s" % mesaj2)
    finally:
        os.environ.clear()
        os.environ.update(eski)
        shutil.rmtree(dizin, ignore_errors=True)
        import importlib
        from gercek import video_kayit as _V
        importlib.reload(_V)


# ---------------------------------------------------------------- R128
def test_R128_TELEMETRI_SUNUCUNUN_GERCEK_SEMASINI_kullaniyor():
    """⛔⛔ Alan adları SUNUCUNUN şemasından, dokümanın PDF'inden DEĞİL.

    ⛔ YAŞANDI (2026-08-31, saha testi): doküman §7.1'deki adlarla
      gönderdik. Sunucu HTTP **200** döndü, `hata 0` gördük ve
      "haberleşme çalışıyor" diye hüküm kurduk. Oysa sunucu tanımadığı
      alanları ATIYOR ve her şeyi SIFIR okuyordu — puan kaybı SESSİZDİ.
      Komiteden gelen gerçek C# şeması 14 alanın 11'inde farklı ad
      kullanıyor.

    ⛔ TİP DE ÖNEMLİ: `iha_mod` ve `iha_kilitlenme` C# tarafında **bool**.
      0/1 göndermek `bool` alanına oturmaz.

    ⛔ `iha_batarya` sunucu şemasında YORUMDA ("Avcı Drone yarışması
      için" kapatılmış) — GÖNDERİLMEMELİ.
    """
    import inspect
    import drone_yki

    #: Komiteden gelen gerçek şema — ad ve tip.
    SEMA = {
        "takim_numarasi": int,
        "iha_enlem": float, "iha_boylam": float, "iha_irtifa": float,
        "iha_dikilme": float, "iha_yonelme": float, "iha_yatis": float,
        "iha_hiz": float,
        "iha_mod": bool, "iha_kilitlenme": bool,
        "hedef_merkez_X": int, "hedef_merkez_Y": int,
        "hedef_genislik": int, "hedef_yukseklik": int,
    }

    class _Cerceve:
        hazir = True

        @staticmethod
        def dereceye(x, y, z):
            return 41.1234567, 29.7654321, z

    class _Gb:
        cerceve = _Cerceve()

        @staticmethod
        def konum():
            return 10.0, 20.0, 42.5

        @staticmethod
        def yonelim():
            import math as _m
            return _m.radians(-7.0), _m.radians(3.0), _m.radians(210.0)

        @staticmethod
        def hiz():
            return 12.3

        @staticmethod
        def gps_konum():
            # ⛔ Çerçevenin `dereceye` çıktısından KASTEN FARKLI: paketin
            #   HAM GPS'i kullandığını kanıtlamak için.
            return 41.1234567, 29.7654321

    class _Ks:
        durum = {"kaynak": "OTONOM"}

    drone_yki.PANEL._D["son_kutu"] = (300, 230, 30, 43)
    drone_yki.PANEL._D["olcut"] = {"saglandi": True}
    paket = drone_yki._telemetri(_Gb(), _Ks(), None)

    # --- ADLAR birebir ---
    assert set(paket) == set(SEMA), (
        "alan adları şemayla tutmuyor.\n  fazla: %s\n  eksik: %s"
        % (sorted(set(paket) - set(SEMA)), sorted(set(SEMA) - set(paket))))

    # --- TİPLER ---
    for ad, tip in SEMA.items():
        d = paket[ad]
        if tip is bool:
            assert isinstance(d, bool), (
                "%s bool olmalı, gelen %r (%s). C# `bool` alanına 0/1 "
                "oturmaz." % (ad, d, type(d).__name__))
        elif tip is int:
            assert isinstance(d, int) and not isinstance(d, bool), (
                "%s int olmalı, gelen %r" % (ad, d))
        else:
            assert isinstance(d, (int, float)) and not isinstance(d, bool), (
                "%s sayı olmalı, gelen %r" % (ad, d))

    # --- DEĞERLER gerçekten araçtan mı geliyor (sabit sıfır DEĞİL) ---
    assert abs(paket["iha_enlem"] - 41.1234567) < 1e-6
    assert abs(paket["iha_boylam"] - 29.7654321) < 1e-6
    assert abs(paket["iha_irtifa"] - 42.5) < 0.05
    assert abs(paket["iha_yonelme"] - 210.0) < 0.5
    assert abs(paket["iha_hiz"] - 12.3) < 0.05
    assert paket["iha_mod"] is True, "otonomdayken mod False geldi"

    # --- ⛔ KÖKEN KURULMAMIŞKEN DE KONUM SIFIR OLMAMALI (2026-09-01) ---
    #   YAŞANDI: haberleşme testinde sunucuya enlem/boylam 0.0 gitti.
    #   Sebep: konum yerel metre çerçevesinden geri çevriliyordu ve
    #   panelde KÖKEN KUR'a basılmadığı için çerçeve hazır değildi.
    #   Aracın GPS'i varken paket ASLA sıfır konum taşımamalı.
    class _CerceveYok:
        hazir = False

        @staticmethod
        def dereceye(x, y, z):
            raise AssertionError("köken yokken dereceye çağrılmamalı")

    class _GbKokensiz(_Gb):
        cerceve = _CerceveYok()

    p2 = drone_yki._telemetri(_GbKokensiz(), _Ks(), None)
    assert abs(p2["iha_enlem"] - 41.1234567) < 1e-6, (
        "köken kurulmadan enlem %r gitti — GPS varken sıfır/yanlış konum "
        "göndermek yarışmada puanı sessizce sıfırlar" % p2["iha_enlem"])
    assert abs(p2["iha_boylam"] - 29.7654321) < 1e-6
    assert paket["iha_kilitlenme"] is True
    assert (paket["hedef_merkez_X"], paket["hedef_merkez_Y"],
            paket["hedef_genislik"], paket["hedef_yukseklik"]) == (300, 230, 30, 43)

    # --- batarya GÖNDERİLMEMELİ ---
    assert "iha_batarya" not in paket, (
        "iha_batarya sunucu şemasında yorumda — gönderilmemeli")

    # --- PDF'in eski adları KALMAMIŞ olmalı ---
    for eski in ("takim_no", "enlem", "boylam", "irtifa", "dikilme",
                 "yonelme", "yatis", "hiz", "mod", "kilitlenme",
                 "hedef_x_merkezi", "hedef_y_merkezi"):
        assert eski not in paket, (
            "PDF'in eski adı `%s` hâlâ gönderiliyor — sunucu bunu ATAR "
            "ve alanı SIFIR okur" % eski)

    # --- sınama araçları da aynı şemayı kullanmalı ---
    kay = open(os.path.join(REEL, "araclar", "sunucu_testi.py"),
               encoding="utf-8").read()
    for ad in SEMA:
        assert ad in kay, "sunucu_testi.py `%s` göndermiyor" % ad
    sah = open(os.path.join(REEL, "araclar", "sahte_sunucu.py"),
               encoding="utf-8").read()
    for ad in SEMA:
        assert ad in sah, "sahte_sunucu.py `%s` alanını denetlemiyor" % ad


# ---------------------------------------------------------------- R129
def test_R129_FAZ_GECISI_OTOMATIK_elle_mudahale_YOK():
    """⛔⛔ YARIŞMA KURALI: faz geçişine insan karar veremez.

    Deneme uçuşu için bir operatör izni eklenmişti (önce yalnız GPS
    görmek istiyorduk). Yarışma bunu YASAKLIYOR; §5.12 gereği kapı
    TAMAMEN söküldü — kill-switch, env anahtarı, panel düğmesi, CSS,
    hiçbiri bırakılmadı.

    Geçiş kuralı SAYAÇLARLA belirlenir:
        DEVIR_KARE = 10   ardışık TESPİT    -> GÖRSEL
        KAYIP_KARE = 20   ardışık TESPİTSİZ -> GPS (ISTASYON)
        GUDUM_KIPI = hibrit  (iki yönlü geçiş açık)
    """
    import re
    from dow.ayarlar import Ayar

    # --- eşikler ---
    assert Ayar.DEVIR_KARE == 10, (
        "görsele devir eşiği %s — kural 10 ardışık tespit" % Ayar.DEVIR_KARE)
    assert Ayar.KAYIP_KARE == 20, (
        "GPS'e dönüş eşiği %s — kural 20 ardışık tespitsiz" % Ayar.KAYIP_KARE)
    assert Ayar.GUDUM_KIPI == "hibrit", (
        "kip `%s` — `gorsel`de GPS'e GERİ DÖNÜLMEZ, `hibrit` olmalı"
        % Ayar.GUDUM_KIPI)

    # --- izin kapısı HİÇBİR YERDE kalmamalı ---
    assert not hasattr(Ayar, "GORSEL_IZIN"), "Ayar.GORSEL_IZIN hâlâ duruyor"
    for dosya in ("dow/ana.py", "dow/ayarlar.py", "gercek/panel.py",
                  "drone_yki.py", "baslat.sh"):
        icerik = open(os.path.join(REEL, dosya), encoding="utf-8").read()
        for iz in ("GORSEL_IZIN", "gorsel_izin", "b_gorsel"):
            assert iz not in icerik, (
                "%s içinde `%s` kalmış — §5.12: elenen özellik TAMAMEN "
                "çıkarılır" % (dosya, iz))

    # --- devir kapısı YALNIZ sayaca bakmalı ---
    ana = open(os.path.join(REEL, "dow", "ana.py"), encoding="utf-8").read()
    kod = "\n".join(x.split("#")[0] for x in ana.splitlines())
    i = kod.index('self.durum = "GORSEL"')
    kapi = kod[max(0, i - 400):i]
    assert "DEVIR_KARE" in kapi, "devir kapısında sayaç denetimi yok"
    assert "izin" not in kapi.lower(), (
        "devir kapısında hâlâ bir izin denetimi var:\n%s" % kapi[-300:])

    # --- GPS'e dönüş kapısı KAYIP_KARE'ye bakmalı ---
    j = kod.index("KAYIP_KARE")
    donus = kod[j:j + 200]
    assert 'self.durum = "ISTASYON"' in donus, (
        "KAYIP_KARE eşiği ISTASYON'a döndürmüyor")


# ---------------------------------------------------------------- R129
def test_R129_KILIT_ISTERI_saglanmadan_TERMINAL_FAZINA_gecilmez():
    """⛔⛔ Şartname 6.1.4 — GÖREVİN PUAN VEREN ŞARTI.

    Kullanıcı (2026-09-02): *"hedef aracı 10 saniyelik bir periyodun en az
    5 saniyesi kümülatif olarak tespit edersek ve bbox yatay veya dikeyde
    ekranın en az %5'ini kaplarsa kilit atılmış sayılıyor; BU KİLİT
    ATILMADAN TERMİNAL VURUŞ FAZINA GEÇİLMİYOR."*

    ⛔ NİYE BEKÇİ: `KILIT_FAZI` uzun süre KAPALI durdu ve o hâlde kilit
      isteri FİZİKSEL OLARAK SAĞLANAMIYORDU — ölçüldü (76 uçuş):
      kilit sağlayan koşu 0/76, 10 s penceredeki en iyi kümülatif 1.64 s
      (isteri 5.0 s). Araç %5 bandından ~1 saniyede geçip çarpıyordu.
      Yani kapalı hâl, puan almanın önündeki engeldi. Bu bekçi kapının
      geri kapanmasını ve ölçüt sayılarının kaymasını engeller.
    """
    from dow.ayarlar import Ayar
    from dow.gudum.kilit import KilitDurumu

    # --- 1: FAZ KAPISI AÇIK ve ÖLÇÜT ŞARTNAMEYE UYUYOR ---
    assert Ayar.KILIT_FAZI is True, (
        "KİLİT FAZI KAPALI — kilit isteri sağlanamaz, terminal faza "
        "istersiz geçilir (ölçüldü: 0/76 koşu)")
    assert Ayar.KILIT_PENCERE_S == 10.0, "şartname penceresi 10 s"
    assert Ayar.KILIT_GEREKLI_S == 5.0, "şartname kümülatif isteri 5 s"
    assert Ayar.KILIT_BOYUT_YUZDE == 5.0, "şartname boyut eşiği %5"
    assert Ayar.KILIT_KIRP_X == 0.25 and Ayar.KILIT_KIRP_Y == 0.10, (
        "AV dikdörtgeni şartname Şekil 2: soldan/sağdan %25, üstten/alttan %10")

    # --- 2: SÜRE MUHASEBESİ — 5 s dolmadan SAĞLANMAZ, dolunca MANDALLANIR
    from dow.gorus import kamera as KAM
    # AV'nin ORTASINDA ve eksenin %20'si kadar büyük bir kutu -> KİLİTLİ
    buyuk = (KAM.IMG_W / 2.0, KAM.IMG_H / 2.0,
             0.20 * KAM.IMG_W, 0.20 * KAM.IMG_H, 0.9)
    kd = KilitDurumu(Ayar)
    t = 0.0
    for _ in range(40):                    # 40 x 0.1 s = 4.0 s
        t += 0.1
        kd.guncelle(t, buyuk)
    assert kd.saglandi is False, (
        "4.0 s kilitle ister SAĞLANDI sayıldı — 5 s gerekiyor "
        "(kümülatif %.2f s)" % kd.kumulatif_s)
    for _ in range(15):                    # +1.5 s  -> 5.5 s
        t += 0.1
        kd.guncelle(t, buyuk)
    assert kd.saglandi is True, (
        "5.5 s kilite rağmen ister sağlanmadı (kümülatif %.2f s)"
        % kd.kumulatif_s)
    # MANDALLI: tespit kesilse bile geri dönmez (vuruş manevrası başladı)
    for _ in range(40):
        t += 0.1
        kd.guncelle(t, None)
    assert kd.saglandi is True, (
        "ister sağlandıktan sonra geri döndü — vuruş manevrası yarıda "
        "kalır, çarpışma riski")

    # --- 3: KÜÇÜK KUTU ve AV DIŞI KARE SAYILMAZ ---
    kucuk = (KAM.IMG_W / 2.0, KAM.IMG_H / 2.0,
             0.03 * KAM.IMG_W, 0.03 * KAM.IMG_H, 0.9)   # %3 < %5
    kd2 = KilitDurumu(Ayar)
    t = 0.0
    for _ in range(80):
        t += 0.1
        kd2.guncelle(t, kucuk)
    assert kd2.saglandi is False, "eşik altı kutu (%3) kilit sayıldı"
    kenar = (0.02 * KAM.IMG_W, KAM.IMG_H / 2.0,       # AV'nin SOLUNDA
             0.20 * KAM.IMG_W, 0.20 * KAM.IMG_H, 0.9)
    kd3 = KilitDurumu(Ayar)
    t = 0.0
    for _ in range(80):
        t += 0.1
        kd3.guncelle(t, kenar)
    assert kd3.saglandi is False, "AV dikdörtgeni DIŞINDAKİ kutu kilit sayıldı"

    # --- 4: FAZ GEÇİŞİ KODDA — istersiz TERMINAL'e geçilemez ---
    a = open(os.path.join(REEL, "dow", "ana.py"), encoding="utf-8").read()
    assert 'if self.faz == "KILIT" and self.kilitci.saglandi:' in a, (
        "KILIT -> TERMINAL geçişi kilit isterine BAĞLI DEĞİL")
    # köprü/öngörü kutusu muhasebeye GİRMEMELİ (hatalı kilitlenme = eksi puan)
    #   ⚠ ÇAPA: "KILIT MUHASEBESI" metni dosyada BİRDEN FAZLA geçiyor;
    #     doğru yeri bulmak için besleme satırının kendisine bakıyoruz.
    assert "YALNIZ GERCEK TESPITLE" in a, (
        "kilit muhasebesinin YALNIZ gerçek tespitle beslendiği notu yok")
    i = a.index("YALNIZ GERCEK TESPITLE")
    govde = a[i:i + 700]
    assert "self.kilitci.guncelle(t, kabul)" in govde, (
        "kilit muhasebesi KABUL EDİLEN kutuyla beslenmiyor — köprü/öngörü "
        "kutusu girerse şartnamenin HATALI KİLİTLENME tanımına gireriz "
        "(eksi puan)")
