# -*- coding: utf-8 -*-
"""
================================================================================
KOORDİNAT KATMANI — GPS (enlem/boylam/irtifa) ↔ YEREL METRE (KDY)
================================================================================
Güdüm METRE ile çalışır; gerçek dünya DERECE verir. Bu dosya aradaki tek
köprüdür. Simde bu katman YOKTU (Unreal zaten metre veriyordu), o yüzden
tamamen yeni ve tamamen sınanması gereken bir parçadır.

--------------------------------------------------------------------------------
1 · NEDEN DOĞRUDAN ÇIKARMA YAPAMIYORUZ
--------------------------------------------------------------------------------
"Enlem farkını 111320 ile çarp" diye bir kestirme vardır ve YAKLAŞIKTIR.
İki sebeple:

  (a) Dünya küre değil, BASIK bir elipsoit. Kutuplara gidildikçe bir
      derecelik enlemin metre karşılığı DEĞİŞİR (kutupta ~111.7 km,
      ekvatorda ~110.6 km).
  (b) Bir derecelik BOYLAMIN metre karşılığı enlemle birlikte küçülür:
      ekvatorda ~111.3 km, 41° enlemde (Türkiye) ~84 km. Çünkü boylam
      çemberleri kutuplarda birleşir. Bu çarpanı unutmak, doğu-batı
      mesafesini %33 YANLIŞ hesaplamak demektir — 100 m'lik bir hatayı
      67 m sanmak.

TERİMLER (CLAUDE.md §0.2):

  * ELİPSOİT: dünyanın matematiksel modeli. WGS-84 GPS'in kullandığıdır.
  * BASIKLIK f: kutup yarıçapının ekvator yarıçapından ne kadar küçük
    olduğu. WGS-84'te f = 1/298.257 ≈ 0.00335 (yani %0.34).
  * DIŞMERKEZLİK KARESİ e² = f(2−f) = 0.0066944. Formüllerde bu geçer.
  * EĞRİLİK YARIÇAPI: elipsoit üzerinde ilerlerken "yerel çemberin"
    yarıçapı. İKİ TANEDİR ve birbirinden farklıdır:
       M (meridyen)      -> KUZEY-GÜNEY yönünde ilerlerken
       N (asal düşey)    -> DOĞU-BATI  yönünde ilerlerken
  * YEREL TEĞET DÜZLEM: elipsoide bir noktada teğet olan düz düzlem.
    Yakın çevrede dünyayı düz kabul etmek demektir.

--------------------------------------------------------------------------------
2 · TÜRETME — kullandığımız formül nereden geliyor
--------------------------------------------------------------------------------
Köken noktası (φ₀, λ₀, h₀) seçilir (kalkış yeri). O noktadaki iki eğrilik
yarıçapı:

        M(φ₀) = a(1 − e²) / (1 − e² sin²φ₀)^(3/2)      [metre]
        N(φ₀) = a          / (1 − e² sin²φ₀)^(1/2)      [metre]

  a = 6378137.0 m  (WGS-84 büyük yarı eksen)

Bir yay uzunluğu = yarıçap × açı(radyan). Buradan:

        x_kuzey = (φ − φ₀)·(π/180) · M(φ₀)
        y_dogu  = (λ − λ₀)·(π/180) · N(φ₀) · cos(φ₀)
        z_yukari = h − h₀

  cos(φ₀) çarpanı (b) maddesindeki daralmadır.

--------------------------------------------------------------------------------
2b · DOĞRULUK — ÖLÇÜLDÜ, tahmin edilmedi
--------------------------------------------------------------------------------
⚠ BURADA BİR KEZ YANILDIM VE TEST YAKALADI. Önce "1 km'de <1 cm" yazmıştım;
  bekçi R2 bağımsız ECEF yoluyla kıyaslayınca gerçek hatanın 8.6 cm olduğunu
  gösterdi. Sayı düzeltildi, test gevşetilmedi. (CLAUDE.md §5.6 ruhu: ölçüt
  senin lehine ayarlanmaz.)

HATANIN KAYNAĞI — yerküre EĞRİLİĞİ. Yerel teğet düzlem, elipsoide yalnız
kökende değer; uzaklaştıkça yüzey düzlemin ALTINA kaçar. d kadar yatay
uzaklıkta bu düşüş:

        Δz = R·(1 − cos(d/R))  ≈  d² / (2R)

Yani hata mesafenin KARESİYLE büyür ve katsayısı 1/(2R)'dir.
ÖLÇÜLEN katsayı: 7.9 × 10⁻⁸ /m  →  1/(2·6.33×10⁶) ✔ (beklenenle birebir)

    mesafe      yatay hata      düşey hata
      250 m       0.8 cm          0.5 cm
      600 m       2.8 cm          2.8 cm      <- BEKÇİ_SPAWN sınırımız
     1000 m       8.6 cm          7.9 cm
     2000 m      32.8 cm         31.4 cm
     5000 m       1.99 m          1.96 m
    20000 m      31.5  m         31.4  m

⭐ SONUÇ — BU BİZİM İÇİN ÖNEMSİZ, ve NİYE önemsiz olduğu şöyle:
   Uçuş bekçisi drone'u kalkış noktasının 600 m ötesine bırakmıyor
   (`Ayar.BEKCI_SPAWN_MAX_M`). Orada hata 2.8 cm. Kıyas için aynı sistemdeki
   ÖLÇÜLMÜŞ öbür belirsizlikler:
        GPS'in kendi yatay gürültüsü      ±1-2 m      (~50 kat büyük)
        GPS'in kendi DÜŞEY gürültüsü      ±3-10 m     (~150 kat büyük)
        istasyon tutma hatası             ~5 m        (~180 kat büyük)
        menzil sabiti C'nin %25-75 aralığı 855-1060   (%20 saçılma)
   Yani bu yaklaşımı iyileştirmek, yanında duran 150 kat büyük bir
   gürültüyü görmezden gelerek virgülden sonrasını cilalamak olurdu.

⛔ SINIR NEREDE BOZULUR: 5 km'de 2 m'ye çıkıyor. Eğer bir gün alan
   büyürse (ya da bu kod başka bir görevde kullanılırsa) TAM ECEF yoluna
   geçilmelidir — `tests/test_reel.py::_ecef_kdy` o yolu zaten yazıyor,
   kopyalanabilir. Bugün gereksiz karmaşıklıktır.

--------------------------------------------------------------------------------
3 · ⛔ İRTİFA REFERANSI — SESSİZ SİSTEMATİK HATA KAYNAĞI
--------------------------------------------------------------------------------
İki aracın irtifası FARKLI referanslarla gelir:

   BİZİM DRONE (CRSF GPS çerçevesi) : GPS irtifası = DENİZ SEVİYESİNDEN (AMSL)
   HEDEF (yarışma sunucusu)         : `irtifa_ev` = EV/YER seviyesinden

Bunları doğrudan çıkarmak, arazinin deniz seviyesinden yüksekliği kadar
SABİT bir hata verir. Ankara'da bu ~900 m'dir — güdüm hedefi 900 m altında
sanır ve burnunu yere çevirir.

ÇÖZÜM: kalkışta, araç YERDEYKEN kendi AMSL irtifamız `h_ev` olarak
kaydedilir. Ondan sonra:
        bizim_yerden_yukseklik = h_amsl − h_ev
Hedefin `irtifa_ev`'i zaten yerden. İkisi aynı referansta ✔

⚠ VARSAYIM: iki araç AYNI zeminden kalkıyor (aynı yarışma alanı). Farklı
  kotlardan kalkılırsa bu fark kalır. Yarışmada geçerli; başka yerde
  denenirse ölçülmeli.

⚠ GPS İRTİFASI GÜRÜLTÜLÜDÜR: yatay konum ±1-2 m iken düşey ±3-10 m'dir.
  Sebep geometrik: uydular hep ÜSTTEDİR, aşağıdan bakan uydu yoktur, bu
  yüzden düşey çözüm zayıf koşullanmıştır ("DOP" — seyrelme). Simde bu
  gürültü HİÇ YOKTU. Dikey kanalın gerçekte daha sakin ayarlanması
  gerekebilir; bu ÖLÇÜLECEK, şimdiden ayar değiştirilmeyecek.

--------------------------------------------------------------------------------
4 · ÇERÇEVE — `gercek/arayuz.py` ile AYNI olmak zorunda
--------------------------------------------------------------------------------
        X = KUZEY,  Y = DOĞU,  Z = YUKARI
        yaw = pusula yönü (kuzeyden saat yönünde)
Gerekçesi ve doğrulaması `arayuz.py`'de yazılı.
================================================================================
"""
import math

# --- WGS-84 sabitleri (GPS'in kullandığı elipsoit) ---
A_YARIEKSEN = 6378137.0                  # m, büyük yarı eksen
F_BASIKLIK  = 1.0 / 298.257223563
E2          = F_BASIKLIK * (2.0 - F_BASIKLIK)     # 0.00669437999014

#: Enlem/boylam sıçraması bu kadar metreyi aşarsa paket BOZUK sayılır.
#: 200 m, 30 m/s'de 6.7 saniyelik yol — hiçbir meşru pakette olamaz.
SICRAMA_ESIK_M = 200.0


def egrilik_yaricaplari(enlem_deg):
    """Verilen enlemde (M, N) eğrilik yarıçapları, metre.

    M: kuzey-güney yönünde ilerlerken geçerli yarıçap (meridyen)
    N: doğu-batı yönünde ilerlerken geçerli yarıçap (asal düşey)
    """
    s = math.sin(math.radians(enlem_deg))
    t = 1.0 - E2 * s * s
    M = A_YARIEKSEN * (1.0 - E2) / (t ** 1.5)
    N = A_YARIEKSEN / math.sqrt(t)
    return M, N


class YerelCerceve:
    """Bir kökene göre GPS ↔ yerel metre çevrimi (KDY: kuzey, doğu, yukarı).

    KULLANIM:
        cer = YerelCerceve()
        cer.kokeni_kur(enlem, boylam, irtifa_amsl)    # kalkışta, YERDE
        x, y, z = cer.metreye(enlem, boylam, irtifa_amsl)
        enlem, boylam, irtifa = cer.dereceye(x, y, z)

    ⛔ KÖKEN BİR KEZ KURULUR. Uçuş ortasında değiştirmek, güdümün altındaki
       zemini kaydırmak demektir: bütün konumlar bir anda sıçrar ve güdüm
       dev bir hata görüp tam komut verir.
    """

    def __init__(self):
        self.enlem0 = None
        self.boylam0 = None
        self.irtifa0 = None        # AMSL, metre — "ev/yer seviyesi"
        self._M = None
        self._N = None
        self._kurulma_t = None

    # ---------------- köken ----------------
    @property
    def hazir(self):
        return self.enlem0 is not None

    def kokeni_kur(self, enlem, boylam, irtifa_amsl, t=None):
        """Yerel kökeni sabitle. Araç YERDEYKEN, kalkıştan ÖNCE çağrılır."""
        self.enlem0 = float(enlem)
        self.boylam0 = float(boylam)
        self.irtifa0 = float(irtifa_amsl)
        self._M, self._N = egrilik_yaricaplari(self.enlem0)
        self._kurulma_t = t
        return self

    # ---------------- ileri çevrim ----------------
    def metreye(self, enlem, boylam, irtifa_amsl=None, irtifa_yerden=None):
        """GPS -> (x_kuzey, y_dogu, z_yukari) metre.

        İRTİFA İKİ YOLDAN VERİLEBİLİR — ve İKİSİ AYNI ANDA VERİLEMEZ:
          irtifa_amsl   : deniz seviyesinden (bizim drone; CRSF GPS böyle verir)
          irtifa_yerden : yer/ev seviyesinden (hedef; sunucu böyle verir)
        Çıktı HER İKİ HALDE DE yerden yüksekliktir (z_yukari), yani ortak
        referanstadır. Bölüm 3'teki sistematik hata böyle kapanır.
        """
        if not self.hazir:
            raise RuntimeError(
                "YerelCerceve kökeni kurulmadı. Uçuştan önce kokeni_kur() "
                "çağrılmalı (araç YERDEYKEN).")
        if (irtifa_amsl is None) == (irtifa_yerden is None):
            raise ValueError(
                "irtifa_amsl VEYA irtifa_yerden — tam olarak biri verilmeli. "
                "İkisini birden ya da hiçbirini vermek, hangi referansta "
                "olduğunu belirsiz bırakır (bkz. modül başlığı §3).")
        x = math.radians(float(enlem) - self.enlem0) * self._M
        y = math.radians(float(boylam) - self.boylam0) * self._N \
            * math.cos(math.radians(self.enlem0))
        if irtifa_amsl is not None:
            z = float(irtifa_amsl) - self.irtifa0
        else:
            z = float(irtifa_yerden)
        return x, y, z

    # ---------------- ters çevrim ----------------
    def dereceye(self, x, y, z=0.0):
        """(x_kuzey, y_dogu, z_yukari) metre -> (enlem, boylam, irtifa_amsl).

        Panelde harita çizmek ve sunucuya KENDİ konumumuzu bildirmek için.
        """
        if not self.hazir:
            raise RuntimeError("YerelCerceve kökeni kurulmadı.")
        enlem = self.enlem0 + math.degrees(x / self._M)
        boylam = self.boylam0 + math.degrees(
            y / (self._N * math.cos(math.radians(self.enlem0))))
        return enlem, boylam, self.irtifa0 + z

    # ---------------- yardımcı ----------------
    def yerden_yukseklik(self, irtifa_amsl):
        """AMSL irtifayı yer/ev seviyesine çevir (sunucuya `irtifa` alanı)."""
        if not self.hazir:
            raise RuntimeError("YerelCerceve kökeni kurulmadı.")
        return float(irtifa_amsl) - self.irtifa0


def mesafe_m(a, b):
    """İki yerel nokta arasındaki 3B mesafe (metre)."""
    return math.dist(a, b)


def kerteriz_deg(a, b):
    """a'dan b'ye PUSULA kerterizi (derece, kuzeyden saat yönünde).

    ⚠ `dow/gudum/gps.py` ile AYNI formül: atan2(Δdoğu, Δkuzey). Farklı
      yazmak, iki yerde iki farklı yön sözleşmesi demektir.
    """
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360.0


def yer_hizindan_vektor(yer_hizi_ms, yon_deg, dikey_hiz_ms=0.0):
    """Yer hızı + pusula yönünü KDY hız vektörüne çevirir.

    NEDEN GEREKLİ: CRSF telemetrisi hızı VEKTÖR olarak vermez; büyüklük
    (yer hızı) ve YÖN (heading) olarak verir. Çeviricinin iç döngüsü ise
    vektör ister. Dönüşüm:
        vx_kuzey = v · cos(yön)
        vy_dogu  = v · sin(yön)

    ⚠ TUZAK — "yön" İKİ AYRI ŞEY OLABİLİR:
        ROTA (course over ground) : aracın GERÇEKTEN gittiği yön
        BURUN  (heading)          : burnun baktığı yön
      Rüzgârda ikisi AYRIŞIR (yan rüzgârda uçak yan yan gider). Hız
      vektörü ROTA'dan hesaplanmalıdır. CRSF GPS çerçevesindeki `heading`
      alanı ROTA'dır (GPS'ten türetilir); duruş çerçevesindeki `yaw` ise
      BURUN'dur. Karıştırmak, rüzgârda yanal hatayı yanlış işaretle
      besler. Bu modül ROTA bekler; çağıran doğru alanı vermekle yükümlü.
    """
    r = math.radians(yon_deg)
    return (yer_hizi_ms * math.cos(r), yer_hizi_ms * math.sin(r),
            float(dikey_hiz_ms))
