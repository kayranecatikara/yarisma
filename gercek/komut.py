# -*- coding: utf-8 -*-
"""
================================================================================
KOMUT SÜRECİ — pilot ile güdüm arasındaki HAKEM (emniyetin kalbi)
================================================================================
⛔ NİYE AYRI VE KÜÇÜK: yerden güdümlü mimaride bilgisayar kontrol
   döngüsünün İÇİNDEDİR. Güdüm süreci (YOLO + IBVS + çevirici) ağırdır ve
   çökebilir. Çökerse pilotun da komutu gidemezse araç kaybedilir.

   Bu yüzden CRSF'i yazan tek yer BURASIDIR ve burası KÜÇÜKTÜR: YOLO yok,
   numpy yok, ağır iş yok. Güdüm ölse bile bu döngü döner ve pilot uçurur.

        [kumanda USB HID] ─┐
                           ├─→ [KOMUT SÜRECİ] 50 Hz ──> ELRS ──> drone
        [güdüm süreci] ────┘    anahtar BURADA

--------------------------------------------------------------------------------
⛔⛔ DEĞİŞMEZ KURAL — ARM DAİMA PİLOTTAN
--------------------------------------------------------------------------------
Güdümün arm kanalına erişimi YOKTUR. `OtonomIstek` yapısında arm alanı
BULUNMAZ; arm değeri her tikte pilotun anahtarından okunur. Yani bir
yazılım hatası aracı arm EDEMEZ. Bekçi R35 bunu sınar.

--------------------------------------------------------------------------------
EMNİYET SIRA DÜZENİ — hangi arıza ne yapar
--------------------------------------------------------------------------------
| durum                                   | ne gönderilir        | neden |
|-----------------------------------------|----------------------|-------|
| OTONOM, pilot İZİN verdi, güdüm taze    | güdüm + pilot ARM    | normal |
| kumanda OYNATILDI (son 3 s)             | kumanda çubukları    | pilot devraldı |
| kumanda takılı ama DURUYOR               | panel çubukları      | operatör sürüyor |
| OTONOM ama pilot VETO etti              | pilot çubukları      | pilot son sözü söyler |
| OTONOM, güdüm BAYAT (>OTO_ASIM)         | pilot çubukları      | güdüm öldü, pilot uçursun |
| MANUEL                                  | pilot çubukları      | pilot komutta |
| kumanda KOPUK, güdüm taze, OTONOM       | güdüm + SON arm      | USB kopması uçağı düşürmemeli |
| kumanda kopuk VE güdüm bayat            | ⛔ PAKET YOK         | RX failsafe -> AUTO-LAND |
| kumanda kopukluğu > KMD_TESLIM (3 s)    | ⛔ PAKET YOK         | müdahale edecek kimse yok -> güvenli iniş |

⛔ "PAKET YOK" NİYE DOĞRU DAVRANIŞ: paket kesilince alıcı failsafe'e girer
   ve Betaflight `failsafe_procedure = AUTO-LAND` uygular. Alternatifler
   daha kötü: nötr çubuk göndermek aracı süzülerek uzaklaştırır; disarm
   göndermek onu DÜŞÜRÜR.

⛔ DISARM ASLA "EMNİYET TEDBİRİ" OLARAK GÖNDERİLMEZ. Havada disarm =
   serbest düşüş. Disarm yalnız pilotun kendi anahtarıyla olur.
================================================================================
"""
import os
import threading
import time

from . import crsf


class KomutCfg:
    HZ          = float(os.environ.get("DOW_KMT_HZ", 50.0))
    #: Güdüm bu süre sessiz kalırsa OTONOM düşer, çubuklara dönülür.
    #: 200 ms = 10 güdüm tiki (50 Hz). Daha kısası, tek bir gecikme
    #: sıçramasında gereksiz yere kipi düşürür.
    OTO_ASIM_S  = float(os.environ.get("DOW_KMT_OTO_ASIM", 0.20))
    #: Kumanda bu süre okunamazsa "kopuk" sayılır.
    KMD_ASIM_S  = float(os.environ.get("DOW_KMT_KMD_ASIM", 0.30))
    #: Kumanda bu kadar uzun kopuk kalırsa paket kesilir (-> AUTO-LAND).
    KMD_TESLIM_S = float(os.environ.get("DOW_KMT_KMD_TESLIM", 3.0))
    #: Panel çubukları bu süre tazelenmezse YOK sayılır.
    #: ⛔ Tarayıcı sekmesi kapanır, WiFi düşer, sayfa donar — hepsi olur.
    #:   Donmuş bir çubuk değerini "pilot komutu" sanmak, aracı son
    #:   verilen komutla sonsuza dek uçurmak demektir.
    PANEL_ASIM_S = float(os.environ.get("DOW_KMT_PANEL_ASIM", 1.5))
    #: ⭐ KUMANDA DEVRALMA (kullanıcı kararı 2026-08-29):
    #:   "kumanda takılı olsa bile arayüzden kontrol olsun; eğer kumandadan
    #:    joystickler hareket etmeye başlarsa o veri değişmeye başlarsa
    #:    kumandadaki girdiye bakılsın ve drone kumanda ile yönetilsin."
    #:
    #: Yani kumanda TAKILI OLMAK'la değil, OYNATILMAK'la devralır.
    #: Bir eksen bu kadar değişirse "hareket" sayılır. 0.04 seçildi:
    #: gimbal gürültüsü/ölü bant tipik olarak ±0.02'nin altında kalır;
    #: eşik onun iki katı, yani kendiliğinden devralma olmaz.
    KMD_HAREKET_ESIK = float(os.environ.get("DOW_KMT_KMD_ESIK", 0.04))
    #: Hareketten sonra kumanda bu kadar süre HÂKİM kalır. Pilot çubuğu
    #: ortada tutarken (hareket yokken) panelin devralmasını engeller.
    KMD_HAKIMIYET_S = float(os.environ.get("DOW_KMT_KMD_HAKIM", 3.0))
    #: ⛔ KUMANDA SONRADAN TAKILIRSA YAKALANMALI (2026-08-29, sahada görüldü).
    #:   `Kumanda.ac()` yalnız açılışta çağrılıyordu; kullanıcı programı
    #:   başlatıp SONRA kumandayı takınca cihaz HİÇ algılanmıyordu ve panel
    #:   "takılı değil" diyordu. Sahada bu her seferinde olur: önce yazılım
    #:   açılır, sonra donanım toplanır.
    KMD_ARA_S = float(os.environ.get("DOW_KMT_KMD_ARA", 2.0))
    #: Pilotun VETO anahtarı zorunlu mu?
    #:   True  (varsayılan): otonom, ancak pilotun anahtarı İZİN VERİYORSA
    #:                       çalışır. Anahtar kapanınca ANINDA manuele düşer.
    #:   False            : anahtar yok (tezgâh/kumandasız sınama).
    #: ⛔ SAHADA DAİMA True. Bu, pilotun tek hareketle otonomiyi kesme
    #:   yetkisidir ve yerden güdümlü mimaride EN ÖNEMLİ emniyet unsurudur.
    VETO_ZORUNLU = os.environ.get("DOW_KMT_VETO", "1") != "0"


class OtonomIstek:
    """Güdümün ürettiği çubuk isteği.

    ⛔ `arm` ALANI KASTEN YOKTUR (bkz. modül başlığı). Güdüm arm edemez.
    """
    __slots__ = ("throttle", "pitch", "roll", "yaw", "t")

    def __init__(self, throttle=0.0, pitch=0.0, roll=0.0, yaw=0.0, t=0.0):
        self.throttle = throttle; self.pitch = pitch
        self.roll = roll; self.yaw = yaw; self.t = t


class KomutSureci:
    """50 Hz CRSF yazıcısı + kaynak hakemi + bekçi zamanlayıcı."""

    def __init__(self, bag, kumanda=None, harita=None, cfg=KomutCfg):
        self.bag = bag
        self.kumanda = kumanda
        self.harita = harita or crsf.KanalHaritasi()
        self.cfg = cfg
        self.kip = "MANUEL"              # MANUEL | OTONOM
        # ⭐ DEVİR BİLDİRİMİ — SARSINTISIZ GEÇİŞİN DOĞDUĞU YER.
        #   fn(yeni_kaynak, son_manuel_throttle) diye çağrılır.
        #   MANUEL -> OTONOM anında güdüm tarafı dikey döngüyü pilotun
        #   O ANKİ çubuğuyla tohumlar; çıkış sıçramaz ve asılı gazın
        #   ÖLÇÜLMÜŞ değeri bedavaya gelir.
        #   OTONOM -> MANUEL anında döngü durdurulur; pilot uçarken
        #   tümlevin körlemesine birikmesi engellenir.
        self.devir_geri_cagirma = None
        self._onceki_kaynak = "MANUEL"
        self._son_manuel_thr = 0.0
        self._oto = None
        self._oto_kilit = threading.Lock()
        # ⛔⛔ ARM ARTIK BİR MANDAL (kullanıcı kararı 2026-09-02).
        #   ESKİ HÂLİ: panelin ARM düğmesi BASILI TUTMA istiyordu ve arm
        #   her tikte `cubuk.arm`dan okunuyordu. Kullanıcı: "arma basılı
        #   tutarken arm olmasın, bir kere basıp bıraktığımızda arm olsun,
        #   bir daha basınca disarm olsun."
        #   Mandalı DEĞİŞTİREBİLENLER:
        #     · panel  : `arm_ayarla()` (düğme, her kipte)
        #     · kumanda: arm anahtarı DEĞİŞTİĞİNDE — YALNIZ MANUEL kipte
        self._arm = False
        #: kumanda arm anahtarının önceki hâli (KENAR yakalamak için)
        self._kmd_arm_onceki = None
        # ⛔⛔ GÖREV, KİPTEN AYRI (kullanıcı kararı 2026-09-02).
        #   ESKİ HÂLİ: OTONOM'a basmak görevi DE başlatıyordu; araç o
        #   anda tırmanmaya kalkıyordu. Kullanıcı: "otonom moda basınca
        #   direkt görev başlamasın; orada bir ARM ve bir GÖREV BAŞLAT
        #   düğmesi olsun; otonom modda araç ARM'ken görev başlata
        #   basılırsa görev başlasın."
        #   ⭐ TEKNİK OLARAK DA ŞART: uçuş kartı gaz çubuğu AŞAĞIDA
        #     değilken ARM ETMEZ (`min_check` ~1050 µs). OTONOM'a basar
        #     basmaz güdüm tırmanış gazı verirse arm etmek İMKÂNSIZ hâle
        #     gelir. Doğru sıra: ARM -> sonra GÖREV.
        self._gorev = False
        self._son_kmd_t = 0.0
        self._veto_izin = False        # pilot izin vermeden otonom YOK
        # ⛔⛔ FAILSAFE İNİŞ KİLİDİ (kullanıcı kararı 2026-08-30).
        #   True iken HİÇBİR paket gönderilmez — ne pilot, ne otonom, ne
        #   başka herhangi bir kaynak.
        #   Alıcı ~200 ms sonra failsafe'e girer ve Betaflight AUTO-LAND yapar.
        #
        #   NİYE "SUSMAK" EN SAĞLAM İNİŞ: alternatifler bizi döngüde
        #   tutardı (iniş çubuğu hesaplamak, eve dönüş koşturmak) ve laptop ya da
        #   bağ arızasında ÖLÜRLERDİ. Susmak hiçbir hesaba dayanmaz;
        #   yazılımın kendini devreden ÇIKARMASIDIR. Aracın iniş yeteneği
        #   uçuş kontrolcüsünün içindedir ve bizden bağımsızdır.
        #
        #   ⛔ ÖNKOŞUL: Betaflight `failsafe_procedure` = LAND olmalı.
        #     DROP ise motorlar KESİLİR ve araç DÜŞER. Ayar Configurator
        #     "Failsafe" sekmesinde, Stage 2 = "Landing".
        #
        #   ⛔ MANDALLIDIR: bir kez açılınca kendiliğinden kapanmaz. Panik
        #     anında basılan düğmenin bir sonraki tikte geri alınması,
        #     düğmenin varlık sebebini yok ederdi.
        self._inis_kilidi = False
        # ⛔ EK KANALLAR (AUX) — uçuş kartının KENDİ kiplerini açmak için.
        #   Sözlük: {kanal_no: çubuk_degeri}. Boşsa hiçbir ek kanal
        #   sürülmez ve çerçeve eskisiyle BİT BİT aynı kalır.
        #
        #   ⛔⛔ YALNIZ "OTONOM" KAYNAĞINDA GEÇER. Pilot çubuğa dokunup
        #     devraldığı an ek kanallar DÜŞER. Sebebi somut: ALT HOLD
        #     açıkken gaz çubuğu bir TIRMANMA HIZI komutudur, kapalıyken
        #     İTKİ. Pilot devraldığında çubuğunun anlamının sessizce
        #     değişmiş olması, elindeki aracı tanımaması demektir.
        self._aux = {}
        #: Pilot çubukla devraldı mı (panelde gösterilir).
        # ⭐ PANEL ÇUBUKLARI — fiziksel kumanda YOKKEN insan girdisi.
        #   ⛔ ARM KURALI DEĞİŞMEDİ: arm bir İNSAN kaynağından gelir
        #     (fiziksel kumanda ya da panel), GÜDÜMDEN ASLA. Güdümün
        #     `otonom_yaz()` yolunda arm alanı hâlâ YOKTUR (bekçi R35).
        self._panel = None
        self._panel_t = 0.0
        # ⭐ KUMANDA HAREKET TAKİBİ
        self._kmd_onceki = None       # son okunan çubuk değerleri
        self._kmd_hareket_t = -9e9    # son HAREKET anı
        self._kmd_takili = False
        self._kmd_ara_t = 0.0         # son bağlanma denemesi
        self._calisiyor = False
        self._is = None
        # §5.1 mekanizma / teşhis
        self.sayac = {"tik": 0, "gonderilen": 0, "kesilen": 0,
                      "oto_dusme": 0, "kmd_kopuk": 0, "manuel": 0,
                      "otonom": 0, "veto": 0, "kmd_hareket": 0}
        self.durum = {"kaynak": "-", "sebep": "-", "arm": False}
        self.insan_kaynagi = ""

    # ---------------- güdümün arayüzü ----------------
    def otonom_yaz(self, throttle, pitch, roll, yaw, t=None):
        """Güdüm süreci bunu her tikte çağırır. Bloke etmez."""
        with self._oto_kilit:
            self._oto = OtonomIstek(throttle, pitch, roll, yaw,
                                    t if t is not None else time.monotonic())

    def panel_yaz(self, throttle, pitch, roll, yaw, arm=None,
                  otonom_izin=None, t=None):
        """Panelin sanal çubukları. Fiziksel kumanda varsa O ÖNCELİKLİDİR.

        `arm` ve `otonom_izin` None ise önceki değer korunur — panel her
        karede arm göndermek zorunda kalmasın.
        """
        from .kumanda import Cubuklar
        self._panel = Cubuklar(throttle, pitch, roll, yaw,
                               arm=self._arm if arm is None else bool(arm),
                               kip_anahtari=(self._veto_izin
                                             if otonom_izin is None
                                             else bool(otonom_izin)))
        self._panel_t = time.monotonic() if t is None else t

    def _panel_oku(self, simdi):
        if self._panel is None:
            return None
        if (simdi - self._panel_t) > self.cfg.PANEL_ASIM_S:
            return None
        return self._panel

    def aux_yaz(self, aux):
        """Ek kanalları ayarla. `None` ya da boş sözlük -> hiçbiri sürülmez.

        ⚠ Bu bir TAŞIMA ayarıdır, güdüm kararı değil: hakem neyi
          göndereceğine yine kendi kurallarıyla karar verir; burası
          yalnız "gönderirken şu kanallar da şöyle olsun" der.
        """
        self._aux = dict(aux) if aux else {}

    @property
    def aux(self):
        return dict(self._aux)

    def inis_kes(self, ac=True):
        """FAILSAFE İNİŞ — RC paketlerini KES (mandallı).

        `ac=True`  : bu andan itibaren hiçbir paket gönderilmez.
        `ac=False` : kilidi kaldırır (operatörün bilinçli kararı).

        ⚠ Kilidi kaldırmak aracı otomatik kurtarmaz: Betaflight failsafe'e
          girdikten sonra kendi kurtarma kurallarını uygular; çoğu ayarda
          disarm olana kadar failsafe'te KALIR. Yani bu düğme pratikte
          TEK YÖNLÜDÜR — öyle kabul et.
        """
        self._inis_kilidi = bool(ac)
        return self._inis_kilidi

    @property
    def otonom_istek(self):
        """Güdümün SON İSTEDİĞİ çubuklar — gönderilmiş olsun ya da olmasın.

        ⛔ YALNIZ GÖSTERİM/TEŞHİS İÇİN. Hakemin kararına girmez; burayı
          okumak hiçbir şeyi değiştirmez.

        NİYE VAR: güdümün ne yapmak İSTEDİĞİNİ, aracı ona TESLİM ETMEDEN
        görebilmek. Yerde "çubuklar hedefe doğru mu" sorusunu OTONOM'a
        basmadan cevaplar — en güvenli teşhis budur.
        """
        with self._oto_kilit:
            o = self._oto
        if o is None:
            return None
        return {"throttle": o.throttle, "pitch": o.pitch,
                "roll": o.roll, "yaw": o.yaw,
                "yas": round(time.monotonic() - o.t, 3)}

    @property
    def inis_kilitli(self):
        return self._inis_kilidi

    def gorev_ayarla(self, ac):
        """Görevi başlat/durdur. ⛔ YALNIZ OTONOM kipinde anlamlıdır.

        MANUEL'e geçmek görevi KENDİLİĞİNDEN durdurur (bkz. `kip_sec`) —
        iki kip arasında hiçbir bağ kalmasın diye.
        """
        self._gorev = bool(ac)
        return self._gorev

    @property
    def gorev(self):
        return self._gorev

    def arm_ayarla(self, ac):
        """ARM mandalını panelden ayarla. `ac` True/False.

        ⛔ HER KİPTE ÇALIŞIR: kullanıcı otonom uçuşta da panelden disarm
           edebilmeli — otonomdayken kumanda yok sayıldığı için (bkz.
           `tik`) panel TEK arm yetkisidir.
        """
        self._arm = bool(ac)
        return self._arm

    @property
    def arm_durumu(self):
        return self._arm

    def kip_sec(self, kip):
        if kip not in ("MANUEL", "OTONOM"):
            raise ValueError("kip MANUEL ya da OTONOM olmalı: %r" % kip)
        # ⛔ SERT AYRIM: MANUEL'e geçmek görevi DURDURUR. Yoksa görev
        #   "açık" kalır ve operatör sonra OTONOM'a bastığında araç
        #   beklenmedik şekilde kaldığı yerden tırmanmaya devam eder.
        if kip != "OTONOM":
            self._gorev = False
        self.kip = kip

    # ---------------- tek tik ----------------
    def tik(self, simdi=None):
        """Bir karar + bir paket. Döner: (gonderildi_mi, durum_sozlugu)."""
        c = self.cfg
        simdi = time.monotonic() if simdi is None else simdi
        self.sayac["tik"] += 1

        # --- 0) ⛔⛔ FAILSAFE İNİŞ — HER ŞEYDEN ÖNCE, TEK ÇIKIŞ ---
        #   Burada ERKEN dönülür ki AŞAĞIDAKİ HİÇBİR dal `rc_gonder`
        #   çağıramasın. Kapıyı hakemin içine koymak yetmezdi: yeni bir
        #   dal eklendiğinde atlanabilirdi. Fonksiyonun ilk satırı olması
        #   YAPISAL garantidir. Bekçi R118 bunu sınar.
        if self._inis_kilidi:
            self.sayac["kesilen"] += 1
            self.durum = {"kaynak": "YOK", "sebep": "failsafe_inis",
                          "komut": None, "arm": self._arm,
                          "insan": self.insan_kaynagi,
                          "kmd_takili": self._kmd_takili,
                          "kmd_hakim": False, "kmd_kopuk": True,
                          "inis_kilidi": True}
            return False, self.durum

        # --- 1) İNSAN GİRDİSİ — kumanda OYNATILINCA devralır ---
        #   ⭐ KURAL (kullanıcı 2026-08-29): kumanda TAKILI OLMAK'la değil,
        #     OYNATILMAK'la devralır. Takılı ama duruyorsa panel sürer;
        #     pilot çubuğa dokunduğu an kumanda hâkim olur ve
        #     KMD_HAKIMIYET_S boyunca öyle kalır.
        #   ⛔ ARM/İZİN ANAHTARI DA "HAREKET"TİR: pilot arm anahtarını
        #     çevirdiği an devralmalı — yoksa acil disarm gecikirdi.
        # ⭐ SICAK TAKMA: kumanda kapalıysa periyodik olarak yeniden dene.
        #   Çıkarılırsa `oku()` None döner ve `hazir` düşer; bir sonraki
        #   aramada tekrar yakalanır. Deneme ARALIKLIDIR — her tikte pygame
        #   sorgulamak 50 Hz'de gereksiz yük olurdu.
        #   ⚠ `hazir`/`ac()` OLMAYAN bir kaynak da meşrudur (test sahtesi,
        #     başka bir girdi cihazı). Öyleyse "zaten hazır" sayılır —
        #     eksik alanı hataya çevirmek, hakem döngüsünü öldürürdü.
        if (self.kumanda is not None
                and not getattr(self.kumanda, "hazir", True)
                and callable(getattr(self.kumanda, "ac", None))
                and (simdi - self._kmd_ara_t) >= c.KMD_ARA_S):
            self._kmd_ara_t = simdi
            self.sayac["kmd_arama"] = self.sayac.get("kmd_arama", 0) + 1
            if self.kumanda.ac():
                self._kmd_onceki = None          # yeni cihaz: referansı sıfırla
                self.sayac["kmd_baglandi"] = self.sayac.get("kmd_baglandi", 0) + 1

        kmd = self.kumanda.oku() if self.kumanda is not None else None
        self._kmd_takili = kmd is not None
        if kmd is None:
            self._kmd_onceki = None              # kopunca referans temizlenir
        if kmd is not None:
            # ⛔ DEĞERLER SAKLANIR, NESNE REFERANSI DEĞİL — bekçi R63 bunu
            #   yakaladı. Kaynak her çağrıda AYNI nesneyi döndürürse (ki
            #   meşru bir uygulamadır: tampon yeniden kullanmak) referans
            #   saklamak, "önceki" ile "şimdiki"yi AYNI şey yapar ve
            #   hareket SESSİZCE hiç görünmez. Pilot çubuğu oynatır,
            #   sistem duymaz.
            simdiki = (kmd.throttle, kmd.pitch, kmd.roll, kmd.yaw,
                       bool(kmd.arm), bool(kmd.kip_anahtari))
            o = self._kmd_onceki
            if o is None:
                self._kmd_onceki = simdiki      # ilk okuma: referans, hareket DEĞİL
            else:
                # HÂKİMİYET — hangi insan sürüyor: çubuklar + arm + veto
                # anahtarı. Anahtar çevirmek de bir müdahaledir.
                # ⚠ Bu YALNIZ çubuk önceliğini belirler; KİP'e dokunmaz
                #   (çubukla devralma 2026-09-02'de söküldü).
                oynadi = (any(abs(simdiki[i] - o[i]) > c.KMD_HAREKET_ESIK
                              for i in range(4))
                          or simdiki[4] != o[4] or simdiki[5] != o[5])
                if oynadi:
                    self._kmd_hareket_t = simdi
                    self.sayac["kmd_hareket"] = self.sayac.get("kmd_hareket", 0) + 1
                self._kmd_onceki = simdiki

        kmd_hakim = (kmd is not None
                     and (simdi - self._kmd_hareket_t) <= c.KMD_HAKIMIYET_S)

        # ⛔⛔ ÇUBUKLA DEVRALMA SÖKÜLDÜ (kullanıcı kararı 2026-09-02).
        #   ESKİ HÂLİ: kumandanın dört analog ekseninden biri
        #   KMD_HAREKET_ESIK (0.04) kadar oynarsa otonom MANDALLI olarak
        #   kesiliyordu (kullanıcı kararı 2026-08-31).
        #
        #   ⛔ NİYE SÖKÜLDÜ: eşik çubuk gezinmesinin %2'si kadar hassastı
        #   ve sahada otonomu HER TİKTE kesiyordu — panelde OTONOM'a
        #   basılıyor, bir tik veriliyor, hemen `sebep=pilot_devraldi`
        #   ile MANUEL'e düşülüyordu. Bir yarışma hakkı buna gitti.
        #
        #   YENİ KURAL: kip YALNIZ PANELDEN seçilir. MANUEL düğmesi
        #   manuele, OTONOM düğmesi otonoma geçirir. Çubuk oynatmak kipi
        #   DEĞİŞTİRMEZ.
        #
        #   ⚠ PİLOTUN ARACI DURDURMA YOLU KAPANMADI, tersine AÇILDI:
        #     kumandanın ARM ANAHTARI artık hâkimiyetten BAĞIMSIZ okunuyor
        #     (bkz. aşağıdaki "ARM DAİMA PİLOTTAN"). Anahtarı kapatmak
        #     aracı O TİKTE disarm eder — çubuktan daha kesin bir dur.
        #     Ayrıca panelde MANUEL, DİKEY İNİŞ ve PAKET KES duruyor.
        panel = self._panel_oku(simdi)

        # ⛔⛔ OTONOM'DA KUMANDA GÜDÜME KARIŞAMAZ — ama ÖLDÜĞÜNDE
        #   yerine geçebilir. Kullanıcı (2026-09-02) kumandanın otonoma
        #   KARIŞMASINI istemiyordu; bu iki ayrı yolla ZATEN sağlandı:
        #     · ARM artık MANDAL; kumandanın anahtarı yalnız MANUEL kipte
        #       ve yalnız DEĞİŞTİĞİNDE mandalı sürer (aşağıda)
        #     · çubukla devralma tamamen SÖKÜLDÜ
        #   Yani otonom sürerken kumanda hiçbir şeyi değiştirmez.
        #
        #   ⛔ ÇUBUK SEÇİMİNİ KİPE BAĞLAMADIM ve sebebi şu: otonom BAŞKA
        #     bir sebeple düşerse (güdüm bayatladı, veto, teslim süresi)
        #     komut İNSANA döner. O anda pilotun FİZİKSEL çubuklarına
        #     dönmek, panelin nötr çubuklarına dönmekten emniyetlidir —
        #     güdüm havada çökerse aracı pilot uçurmalı. Bekçiler R37 ve
        #     R39 tam bunu koruyor ve ikisi de yaşanmış olaylardan geldi.
        if kmd_hakim:
            cubuk = kmd
            self.insan_kaynagi = "kumanda"
        elif panel is not None:
            cubuk = panel
            self.insan_kaynagi = "panel"
        elif kmd is not None:
            # Panel yok/bayat ama kumanda takılı: yine de o sürsün —
            # insansız kalmaktansa duran bir çubuk iyidir.
            cubuk = kmd
            self.insan_kaynagi = "kumanda"
        else:
            cubuk = None
            self.insan_kaynagi = ""
        # ⛔ CANLILIK KOMUTTAN AYRI. Kumanda OTONOM'da komut VERMEZ ama
        #   VARLIĞI sayılır: teslim süresi (hakemin (d) şartı) "ortada
        #   müdahale edebilecek biri var mı" sorusudur, "kim sürüyor"
        #   değil. Ayırmazsak panel bir an sussa RC KESİLİRDİ.
        if cubuk is not None or kmd is not None:
            self._son_kmd_t = simdi
        if cubuk is not None:
            # ⛔⛔ PİLOTUN VETO ANAHTARI — panelden seçilen kipi EZER.
            #   Pilot anahtarı kapatınca otonom O TİKTE düşer; panelin
            #   ne dediği önemsizdir. Bu, yerden güdümlü mimaride pilotun
            #   tek hareketle kontrolü geri alma yoludur.
            #   ⚠ "İzin" olarak kurgulandı, "kip seçimi" olarak değil:
            #     anahtar AÇIK iken otonom OTOMATİK başlamaz — panel de
            #     istemelidir. İki taraf da evet demeden otonom olmaz.
            # ⛔ None = "kumandanın izin konusunda fikri yok" (anahtar
            #   atanmamış). Önceki değer KORUNUR; böylece panelin verdiği
            #   izin kumandanın sabit -1.00'ıyla EZİLMEZ.
            if cubuk.kip_anahtari is not None:
                self._veto_izin = bool(cubuk.kip_anahtari)
        # --- ARM MANDALI ---
        # ⛔ Kumandanın arm anahtarı YALNIZ MANUEL kipte ve YALNIZ
        #   DEĞİŞTİĞİNDE (kenar) mandalı sürer. Kenar olarak okumak şart:
        #   yoksa sabit duran anahtar, panelden verilen arm kararını her
        #   tikte ezerdi ve panel düğmesi hiç iş görmezdi.
        if kmd is not None:
            _a = bool(kmd.arm)
            if (self.kip != "OTONOM" and self._kmd_arm_onceki is not None
                    and _a != self._kmd_arm_onceki):
                self._arm = _a
            self._kmd_arm_onceki = _a
        else:
            self._kmd_arm_onceki = None

        kmd_kopuk = (simdi - self._son_kmd_t) > c.KMD_ASIM_S
        # ⛔⛔ TESLİM SÜRESİ — R39 BUNU EKSİK BULDU (2026-08-29).
        #   İlk yazdığımda `KMD_TESLIM_S` denetimi yalnız BİR dalda vardı ve
        #   izin/arm LATCH'li olduğu için o dala hiç girilmiyordu. Sonuç:
        #   kumanda kopup kopuk KALSA BİLE otonom SÜRESİZ devam ediyordu —
        #   yani havada, müdahale edebilecek kimse olmadan.
        #   Şimdi denetim TÜM otonom yollarının ÖNÜNDE, tek yerde.
        kmd_teslim = (simdi - self._son_kmd_t) > c.KMD_TESLIM_S
        if kmd_kopuk:
            self.sayac["kmd_kopuk"] += 1

        # --- 2) güdüm tazeliği ---
        with self._oto_kilit:
            oto = self._oto
        oto_taze = oto is not None and (simdi - oto.t) <= c.OTO_ASIM_S

        # --- 3) HAKEM — otonom için DÖRT şart birden ---
        #   (a) panel OTONOM istiyor
        #   (b) pilot izin veriyor (veto anahtarı)
        #   (c) güdüm taze setpoint üretiyor
        #   (d) kumandayla bağ TESLİM SÜRESİ içinde
        #   Biri bile düşerse otonom YOK.
        #   ⚠ VETO_ZORUNLU=False (tezgâh kipi) hem (b)'yi hem (d)'yi devre
        #     dışı bırakır: kumandasız sınamada pilot zinciri zaten yoktur.
        izin = (not c.VETO_ZORUNLU) or getattr(self, "_veto_izin", False)
        teslim_engeli = c.VETO_ZORUNLU and kmd_teslim
        if self.kip == "OTONOM" and not izin:
            self.sayac["veto"] += 1
        # ⛔ BEŞİNCİ ŞART DEĞİL, OPERATÖR NİYETİ: görev başlatılmadıysa
        #   güdüm komutu araca GİTMEZ. Emniyet kapısı (dört şart)
        #   değişmedi; bu, "otonom seçmek" ile "görevi başlatmak"ı
        #   ayırmak içindir.
        otonom_uygun = (self.kip == "OTONOM" and self._gorev and izin
                        and oto_taze and not teslim_engeli)

        if otonom_uygun:
            komut = (oto.throttle, oto.pitch, oto.roll, oto.yaw)
            # ⚠ Kumanda kopukken de bu dal çalışır (izin ve arm LATCH'lidir).
            #   Sebep alanı bunu SÖYLEMELİ: operatör "otonom sürüyor ama
            #   kumandayla bağım yok" durumunu görmeden fark edemez.
            kaynak = "OTONOM"
            sebep = "kumanda_kopuk" if kmd_kopuk else "-"
            self.sayac["otonom"] += 1
        elif cubuk is not None:
            komut = (cubuk.throttle, cubuk.pitch, cubuk.roll, cubuk.yaw)
            kaynak = "MANUEL"
            if self.kip != "OTONOM":
                sebep = "-"
            elif not self._gorev:
                sebep = "gorev_baslamadi"
            elif not izin:
                sebep = "pilot_vetosu"; self.sayac["oto_dusme"] += 1
            elif not oto_taze:
                sebep = "gudum_bayat"; self.sayac["oto_dusme"] += 1
            else:
                sebep = "teslim_suresi"; self.sayac["oto_dusme"] += 1
            self.sayac["manuel"] += 1
        else:
            # ⛔ NE PİLOT NE OTONOM -> PAKET KESİLİR.
            #    Alıcı failsafe'e girer, Betaflight AUTO-LAND yapar.
            self.sayac["kesilen"] += 1
            # Etiket AYIRIMI: "teslim_suresi", otonomun GERÇEKTEN
            # engellendiği hâldir (panel istiyordu, güdüm tazeydi, ama
            # kumandayla bağ koptuğu için kesildi). Hiçbir kaynak yokken
            # sebep sadece "paket_kesildi"dir — operatöre yanlış ipucu
            # vermemek için ikisi ayrı tutulur.
            _teslimden = teslim_engeli and self.kip == "OTONOM" and oto_taze
            # ⚠ TEŞHİS ALANLARI BU DALDA DA OLMALI: eksik olunca panel
            #   "kumanda: —" gösteriyor ve operatör sistemin ARAYIP
            #   aramadığını göremiyor.
            self.durum = {"kaynak": "YOK", "insan": self.insan_kaynagi,
                          "komut": None,
                          "kmd_takili": self._kmd_takili,
                          "kmd_hakim": False,
                          "gorev": self._gorev,
                          "sebep": ("teslim_suresi" if _teslimden
                                    else "paket_kesildi"),
                          "arm": self._arm, "kmd_kopuk": kmd_kopuk}
            return False, self.durum

        # --- 3b) DEVİR BİLDİRİMİ (kaynak değiştiyse) ---
        if kaynak != self._onceki_kaynak:
            if self.devir_geri_cagirma is not None:
                try:
                    self.devir_geri_cagirma(kaynak, self._son_manuel_thr)
                except Exception:
                    # ⛔ Geri çağırma patlarsa KOMUT DÖNGÜSÜ DURMAZ.
                    #   Bu döngü pilotun tek yoludur; onu bir yardımcı
                    #   fonksiyonun hatası öldüremez.
                    pass
            self._onceki_kaynak = kaynak
        if kaynak == "MANUEL":
            self._son_manuel_thr = komut[0]

        # --- 4) ⛔ ARM DAİMA PİLOTTAN ---
        arm = self._arm
        # ⛔ EK KANALLAR YALNIZ OTONOM'DA: pilot elle uçarken çubuklarının
        #   anlamı uçuş kartı kipiyle değişmesin.
        _aux = self._aux if (kaynak == "OTONOM" and self._aux) else None
        ok = self.bag.rc_gonder(komut[0], komut[1], komut[2], komut[3],
                                arm=arm, harita=self.harita, aux=_aux)
        if ok:
            self.sayac["gonderilen"] += 1
        self.durum = {"kaynak": kaynak, "sebep": sebep, "arm": arm,
                      "gorev": self._gorev,
                      "inis_kilidi": False, "aux": dict(_aux or {}),
                      "kmd_kopuk": kmd_kopuk, "komut": komut,
                      "insan": self.insan_kaynagi,
                      "kmd_takili": self._kmd_takili,
                      "kmd_hakim": bool(kmd_hakim)}
        return ok, self.durum

    # ---------------- kendi iş parçacığı ----------------
    def basla(self):
        if self._calisiyor:
            return
        self._calisiyor = True
        self._is = threading.Thread(target=self._dongu, daemon=True,
                                    name="komut-sureci")
        self._is.start()

    def dur(self):
        self._calisiyor = False
        if self._is is not None:
            self._is.join(timeout=1.0)

    def _dongu(self):
        periyot = 1.0 / self.cfg.HZ
        sonraki = time.monotonic()
        while self._calisiyor:
            self.tik()
            sonraki += periyot
            uyku = sonraki - time.monotonic()
            if uyku > 0:
                time.sleep(uyku)
            else:
                # ⛔ GERİ KALMIŞSAK BİRİKMİŞ TİKLERİ KOVALAMA: sonraki'yi
                #   şimdiye çek. Yoksa sistem yavaşladığında yüzlerce tik
                #   art arda koşar ve durum daha da kötüleşir.
                sonraki = time.monotonic()
