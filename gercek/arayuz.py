# -*- coding: utf-8 -*-
"""
================================================================================
ARAÇ SÖZLEŞMESİ — güdümün araçtan İSTEDİĞİ ve araca VERDİĞİ her şey
================================================================================
`dow/ana.py::Beyin` bir araca bağlıdır ama HANGİ araç olduğunu bilmez. Bu
dosya o bağın TAM tanımıdır. Sözleşmeye uyan her nesne `Beyin`'e takılabilir:

    Beyin(baglanti=DowBaglanti())        # simülasyon (varsayılan)
    Beyin(baglanti=GercekBaglanti(...))  # gerçek drone

Sözleşme İKİ KATMANLIDIR — ve bu ayrım ÖLÇÜLDÜ, tahmin edilmedi:

    grep -o "self\.b\.[a-zA-Z_]*" dow/ana.py        -> KATMAN 1 (7 çağrı)
    grep -o "beyin\.b\.[a-zA-Z_]*" araclar/kosu.py  -> KATMAN 2 (+5 çağrı)

  KATMAN 1 — GÜDÜM. `Beyin.adim()` yalnız bunları çağırır. Güdüm yasası
    bu yedi çağrının ötesinde araç hakkında HİÇBİR ŞEY bilmez:
        canli()  konum()  yonelim()  hiz_vektoru()
        komut()  hedef_konum_bozuk()  truth()

  KATMAN 2 — KOŞU/KAYIT. Uçuş döngüsü ve panel kullanır; güdüme GİRMEZ:
        baglan()  yeniden_bagla()  kapat()  hiz()  hedef_yonelim()

  ⚠ AYRIM NİYE ÖNEMLİ: Katman 2'nin bir çağrısını gerçek araçta
    yazamazsak GÜDÜM YİNE ÇALIŞIR — yalnız kayıt/gösterim eksilir. Katman
    1'de bir eksik ise sistem hiç uçamaz. Sahada neyin kritik olduğunu
    bilmek, hangi arızada uçuşa devam edileceğini de belirler.

--------------------------------------------------------------------------------
⛔⛔ EKSEN VE İŞARET SÖZLEŞMESİ — BURASI UÇAK KAYBETTİREN YERDİR
--------------------------------------------------------------------------------
Bir eksen işaretini yanlış kurmak, güdümün hatayı KAPATMAK yerine BÜYÜTMESİ
demektir: araç hedeften kaçar, kumanda çubuğu doyuma çakılır ve daire çizer.
Bu depoda tam olarak bu yaşandı (bkz. `dow/gudum/cevirici.py::CevCfg.Y_ISARET`,
"tiklerin %94'ünde doyum, kapanma hızı -3.78 m/s = UZAKLAŞIYOR").

TERİMLER (CLAUDE.md §0.2 — hiçbiri tanımsız bırakılmaz):

  * ÇERÇEVE (frame): sayıların hangi eksen takımına göre ölçüldüğü. "5 m
    ileri" demek, hangi yönün "ileri" sayıldığını bilmeden anlamsızdır.
  * DÜNYA ÇERÇEVESİ: yere sabit, araç dönse de dönmeyen eksen takımı.
  * GÖVDE ÇERÇEVESİ: araca sabit; araç dönünce onunla döner ("burnun ileri").
  * YAW (yönelme): burnun yatay düzlemdeki açısı.
  * PUSULA YÖNÜ (heading): kuzeyden başlayıp SAAT YÖNÜNDE ölçülen açı.
    Kuzey = 0°, doğu = 90°, güney = 180°, batı = 270°.
  * EL'LİK (handedness): üç eksenin birbirine göre dönme yönü. Sağ-elli ve
    sol-elli takımlar birbirinin AYNA görüntüsüdür; karıştırılırsa yanal
    eksen ters döner ve yukarıdaki felaket olur.

BU SÖZLEŞMENİN ÇERÇEVESİ  —  "KDY" (Kuzey-Doğu-Yukarı):

        X  =  KUZEY   (metre)
        Y  =  DOĞU    (metre)
        Z  =  YUKARI  (metre)
        yaw = PUSULA YÖNÜ: +X'ten +Y'ye doğru, yani kuzeyden doğuya,
              SAAT YÖNÜNDE. Radyan olarak verilir.

  NEDEN BU ÇERÇEVE: DoW'un Unreal çerçevesi ile AYNI cebiri üretir, böylece
  `dow/gudum/gps.py` ve `dow/gudum/cevirici.py` içindeki formüller tek harf
  değişmeden geçerli kalır. İki yerde doğrulanabilir:
     gps.py     : ker = atan2(Δy, Δx)  ->  Δdoğu / Δkuzey = pusula kerterizi ✔
     cevirici.py: ileri = vx·cos(yaw) + vy·sin(yaw)
                  yaw=0 (burun kuzeyde) -> ileri = vx = kuzey bileşeni ✔

⚠ AMA YANAL İŞARET ARACA GÖRE DEĞİŞİR — VE ÖLÇÜLMELİDİR.
  `cevirici.py` yanal bileşeni `sag = Y_ISARET · (−vx·sin + vy·cos)` diye
  hesaplar. `Y_ISARET` bir TASARIM TERCİHİ DEĞİL, ARACIN ÖLÇÜLMÜŞ ÖZELLİĞİDİR:
  roll çubuğunun hangi işaretinin aracı hangi yöne götürdüğünü söyler.
     DoW      : Y_ISARET = −1.0   (ölçüldü: +roll aracı SOLA götürüyor)
     Betaflight: BEKLENEN +1.0    (standart: +roll sağa yatırır, sağa gider)
  ⛔ "Beklenen" YETMEZ. Gerçek araçta `araclar/isaret_olc.py` ile ÖLÇÜLECEK
     ve `DOW_Y_ISARET` ile verilecek. Ölçülmeden görsel/GPS güdüm AÇILMAZ.

--------------------------------------------------------------------------------
BİRİMLER — tek yerde, istisnasız
--------------------------------------------------------------------------------
    konum          metre
    hız            metre/saniye
    açı (yonelim)  RADYAN            (derece DEĞİL — Beyin kendisi çevirir)
    çubuk          birimsiz, [-1, +1]

⛔ Birim dönüşümü YALNIZ bu katmanda yapılır. Güdümün içinde /100, *100,
   radians(), degrees() görülmemelidir. Gazebo'da "100 kat" hatalarının
   kaynağı buydu (bkz. `dow/sdk/baglanti.py` başlığı).
================================================================================
"""


class AracArayuzu:
    """Güdümün araçtan beklediği SEKİZ çağrı. Alt sınıflar hepsini yazar.

    Bu sınıf bir "soyut taban"dır: kendisi iş yapmaz, sadece sözleşmeyi
    tarif eder ve uyulmadığında AÇIK hata verir. (Python'da `abc` modülü de
    kullanılabilirdi; burada sade tutuldu ki hata mesajı Türkçe ve öğretici
    olsun.)
    """

    # ==================================================================
    # KATMAN 1 — GÜDÜM (Beyin.adim() yalnız bunları çağırır)
    # ==================================================================
    # 1) BAĞLANTI
    def canli(self):
        """Bağlantı GERÇEKTEN yaşıyor mu? (bool)

        ⛔ "Son veri var mı" DEĞİL, "veri AKIYOR mu". Bu ayrım hayati:
           DoW'da SDK'nın alıcı iş parçacığı ölünce get_* fonksiyonları SON
           BİLİNEN değeri sonsuza dek döndürmeye devam etti; telemetri DONDU
           ama hata da vermedi ve 40+ saniye donmuş veriyle uçtuk.
           Gerçekte aynısı olur: telsiz linki koparsa son GPS paketi elde
           kalır ve güdüm hayalete nişan alır.
           KURAL: bu fonksiyon SON PAKETİN YAŞINA bakar; yaş eşiği aşarsa
           False döner. Beyin False görünce tiki atlar ve komut göndermez.
        """
        raise NotImplementedError("canli() yazılmadı")

    # ------------------------------------------------------------------
    # 2) KENDİ DURUMUMUZ
    # ------------------------------------------------------------------
    def konum(self):
        """(x, y, z) METRE — KDY çerçevesi (X kuzey, Y doğu, Z yukarı).

        Başlangıç noktası (0,0,0) SERBESTTİR; güdüm yalnız FARKLARA bakar.
        Gerçek sistemde "yerel köken" kalkış noktasıdır (bkz. konum.py).
        """
        raise NotImplementedError("konum() yazılmadı")

    def yonelim(self):
        """(roll, pitch, yaw) RADYAN.

        roll  : +? aracın ölçülmüş sözleşmesi (bkz. Y_ISARET notu yukarıda)
        pitch : NEGATİF = burun AŞAĞI  (DoW'da ölçüldü; MAVLink/CRSF de aynı)
        yaw   : pusula yönü, kuzeyden saat yönünde, radyan

        ⚠ pitch işareti kamera modelinde KRİTİK: `dow/gorus/kamera.py` kamera
          eksenini burnun TILT° yukarısında varsayar ve araç öne yatınca
          kameranın da aşağı döndüğünü telafi eder. İşaret ters olursa
          telafi hatayı İKİYE KATLAR.
        """
        raise NotImplementedError("yonelim() yazılmadı")

    def hiz_vektoru(self):
        """(vx, vy, vz) m/s — konum() ile AYNI çerçeve (Z YUKARI pozitif).

        ⛔ Bu, çeviricinin iç döngüsünün girdisidir:
               a_istenen = K_V · (v_hedef − v_ÖLÇÜLEN)
           Yani hız ölçümü bozuksa çevirici yanlış ivme ister. Örnekleme
           hızı da önemlidir (CLAUDE.md §5.3): ölçüm, ölçtüğü şeyin değişim
           hızının en az 5 katı olmalı. Kontrol döngüsü 50 Hz ve araç 0.2 s
           zaman sabitiyle yattığına göre hız ölçümü >= 25 Hz olmalıdır.
           CRSF telemetrisi bunu SAĞLAMAYABİLİR -> `araclar/telem_olc.py`
           gerçek hızı ÖLÇER; yetmiyorsa kestirim katmanı gerekir.
        """
        raise NotImplementedError("hiz_vektoru() yazılmadı")

    # ------------------------------------------------------------------
    # 3) KOMUT
    # ------------------------------------------------------------------
    def komut(self, throttle, pitch, roll, yaw, arm=True):
        """Kumanda çubuğu konumları, dördü birden, TEK paket.

        Dördü de [-1, +1] birimsiz. Anlamları uçuş kontrol kartının KİPİNE
        bağlıdır ve bu sözleşmenin dışındadır:
            Angle/Stabilize : pitch/roll = HEDEF YATIŞ AÇISI
            ALT_HOLD        : throttle   = HEDEF TIRMANMA HIZI
            Angle (baro yok): throttle   = DOĞRUDAN İTKİ  ⚠ çevirici modeli geçersiz

        ⛔ AYRI AYRI GÖNDERİLMEZ. Dördü tek çerçevede gider; yoksa ara
           karelerde tutarsız bir kombinasyon uygulanır (bir eksen yeni,
           öbürü eski). DoW'da bu kural konmuştu, CRSF'te ZATEN öyledir
           (tek pakette 16 kanal).
        """
        raise NotImplementedError("komut() yazılmadı")

    def notr(self, arm=True):
        """Bütün eksenleri sıfırla. Güvenli varsayılan."""
        self.komut(0.0, 0.0, 0.0, 0.0, arm)

    # ------------------------------------------------------------------
    # 4) HEDEF  —  ⛔ YALNIZ GÖRSEL TEMAS YOKKEN
    # ------------------------------------------------------------------
    def hedef_konum_bozuk(self):
        """(x, y, z) METRE — hedefin konumu, KDY çerçevesi. Yoksa None.

        ⛔⛔ YARIŞMA KURALI (CLAUDE.md §10, ÜSTÜN KISIT): görsel temas VARKEN
           bu fonksiyon ÇAĞRILMAZ. Kural `dow/ana.py`'de YAPISAL olarak
           uygulanır (GORSEL fazda bu satıra hiç girilmez) ve bekçilerle
           sınanır. Bu katman veriyi SUNAR; kuralı üst katman uygular.

        Gerçek sistemde kaynak:
           yarışmada : yarışma sunucusunun /api/telemetri_gonder YANITI
                       (enlem, boylam, irtifa_ev, hiz) — 1-2 Hz
           denemede  : Talon bilgisayarının aynı biçimde yayınladığı paket
        """
        raise NotImplementedError("hedef_konum_bozuk() yazılmadı")

    def truth(self):
        """SİMÜLASYONA ÖZEL: bozulmamış gerçek değerler, YALNIZ doğrulama için.

        ⛔ GERÇEK ARAÇTA DAİMA None DÖNER. Böyle bir kanal yoktur; olduğunu
           varsayan her kod yolu gerçekte sessizce hedefsiz kalırdı.
           `Ayar.GPS_KAYNAK="truth"` gerçek uçuşta KULLANILAMAZ — bekçi
           bunu sınar (bkz. reel/tests/test_reel.py).
        """
        return None

    # ==================================================================
    # KATMAN 2 — KOŞU/KAYIT (uçuş döngüsü ve panel; güdüme GİRMEZ)
    # ==================================================================
    def baglan(self, deneme=5, bekle=1.0):
        """Bağlantıyı kur. Başarılıysa True."""
        raise NotImplementedError("baglan() yazılmadı")

    def yeniden_bagla(self, deneme=6):
        """Kopan bağlantıyı yeniden kur.

        ⚠ GERÇEKTE ANLAMI FARKLI: simde soket yeniden açılır. Gerçekte
          telsiz linki kendi kendine geri gelir; burada yapılacak şey seri
          portu kapatıp açmak ve İÇ DURUMU sıfırlamaktır. Link yokken
          komut göndermeye devam etmek TEHLİKELİDİR — link geri gelince
          birikmiş eski komut uygulanabilir.
        """
        raise NotImplementedError("yeniden_bagla() yazılmadı")

    def kapat(self):
        """Aracı KONTROLSÜZ BIRAKMA (CLAUDE.md §9): önce nötr, sonra kapat."""
        raise NotImplementedError("kapat() yazılmadı")

    def hiz(self):
        """Toplam YATAY hız, m/s (skaler). Varsayılan: hız vektöründen."""
        import math as _m
        v = self.hiz_vektoru()
        return _m.hypot(v[0], v[1])

    def hedef_yonelim(self):
        """Hedefin (roll, pitch, yaw) DERECE — ÖLÇÜM/KAYIT İÇİN, güdüme GİRMEZ.

        ⛔ GERÇEK SİSTEMDE YOKTUR -> None döner. Yarışma sunucusu hedefin
           yalnız konum/irtifa/hızını verir; yönelimini VERMEZ. Simde
           analiz için vardı; gerçekte bu sütun boş kalır.
        """
        return None


# ----------------------------------------------------------------------
# SÖZLEŞME DENETLEYİCİSİ — uçuştan ÖNCE, masada koşar
# ----------------------------------------------------------------------
#: KATMAN 1 — bunlar olmadan GÜDÜM ÇALIŞMAZ. `dow/ana.py`'den TÜRETİLDİ:
#:   grep -o "self\.b\.[a-zA-Z_]*" dow/ana.py
GUDUM_CAGRILARI = ("canli", "konum", "yonelim", "hiz_vektoru",
                   "komut", "hedef_konum_bozuk", "truth")

#: KATMAN 2 — bunlar olmadan güdüm çalışır, KAYIT/PANEL eksilir.
#:   grep -o "beyin\.b\.[a-zA-Z_]*" araclar/kosu.py
KOSU_CAGRILARI = ("baglan", "yeniden_bagla", "kapat", "hiz", "hedef_yonelim")

GEREKLI_CAGRILAR = GUDUM_CAGRILARI + KOSU_CAGRILARI


def sozlesme_denetle(nesne, yalniz_gudum=False):
    """Bir bağlantı nesnesi sözleşmeye uyuyor mu? (eksikler listesi döner)

    Sadece "fonksiyon var mı" bakmaz; ÇAĞIRIR ve dönen şeyin biçimini
    denetler. Sahada "AttributeError" görmek yerine masada eksiği görmek
    içindir.

    yalniz_gudum=True ise KATMAN 1 denetlenir (çevrimdışı denklik testi
    gibi, koşu döngüsü olmayan bağlamlar için).
    """
    eksik = []
    aranan = GUDUM_CAGRILARI if yalniz_gudum else GEREKLI_CAGRILAR
    for ad in aranan:
        if not callable(getattr(nesne, ad, None)):
            eksik.append("%s() YOK" % ad)
    if eksik:
        return eksik

    def _uclu(ad, deger, izin_none=False):
        if deger is None:
            if not izin_none:
                eksik.append("%s() None döndü" % ad)
            return
        try:
            x, y, z = deger
            float(x); float(y); float(z)
        except Exception:
            eksik.append("%s() üç SAYI döndürmeli, döndürdüğü: %r" % (ad, deger))

    try:
        if not isinstance(nesne.canli(), bool):
            eksik.append("canli() bool döndürmeli")
    except Exception as e:
        eksik.append("canli() patladı: %s" % e)

    for ad in ("konum", "yonelim", "hiz_vektoru"):
        try:
            _uclu(ad, getattr(nesne, ad)())
        except Exception as e:
            eksik.append("%s() patladı: %s" % (ad, e))

    try:
        _uclu("hedef_konum_bozuk", nesne.hedef_konum_bozuk(), izin_none=True)
    except Exception as e:
        eksik.append("hedef_konum_bozuk() patladı: %s" % e)

    # yonelim RADYAN olmalı: |değer| > 2π ise neredeyse kesin DERECE gelmiş
    try:
        r, p, y = nesne.yonelim()
        import math as _m
        if max(abs(r), abs(p)) > 2 * _m.pi:
            eksik.append("yonelim() RADYAN değil DERECE veriyor gibi "
                         "(roll=%.1f pitch=%.1f) — birim dönüşümü bu "
                         "katmanda yapılmalı" % (r, p))
    except Exception:
        pass

    return eksik
