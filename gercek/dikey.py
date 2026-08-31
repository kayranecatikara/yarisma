# -*- coding: utf-8 -*-
"""
================================================================================
DİKEY KAPALI DÖNGÜ — Angle modunda "tırmanma hızı" komutunu BİZ üretiriz
================================================================================
⛔ NİYE VAR: yarışma şartnamesi **yalnız Angle modu** kullanmaya izin veriyor.
   Angle modunda throttle çubuğu bir HIZ komutu DEĞİL, bir İTKİ komutudur.
   Sabit bir throttle'da araç durmadan hızlanır ya da düşer; yani "şu çubuk
   şu tırmanma hızını verir" diye statik bir eşleme YOKTUR.

   Simde vardı: DoW'un throttle'ı gerçekten hız komutuydu ve ölçülmüştü
   (`cevirici.CevCfg` içindeki iki kollu tablo). Gerçekte o tablo TANIMSIZ.
   Bu dosya onun yerine geçen KAPALI DÖNGÜdür.

⛔ NE DEĞİŞTİRMİYOR: güdüm yasası. Yukarıdaki katmanlar (görsel ve GPS) hâlâ
   "saniyede kaç metre tırmanayım" diyor. Değişen tek şey, o isteği çubuğa
   çevirme yolu — yani ARAÇ MODELİ. `cevirici.py` başlığındaki ayrım aynen
   geçerli: yasa araçtan bağımsız, model araca özgü.

--------------------------------------------------------------------------------
TERİMLER (CLAUDE.md §0.2 — hiçbiri tanımsız bırakılmaz)
--------------------------------------------------------------------------------
  * AÇIK DÖNGÜ  : "şu komutu ver, şu olur" varsayımı. Ölçüme bakmaz.
  * KAPALI DÖNGÜ: sonucu ÖLÇER, istenenle karşılaştırır, farkı düzeltir.
    Burada ölçtüğümüz şey DÜŞEY HIZ (barometreden), istediğimiz de o.
  * P (oransal) terimi: düzeltme, hatayla ORANTILI. Hızlı ama hatayı tam
    sıfırlayamaz — sıfırlasa kendisi de sıfır olurdu.
  * I (tümlev/integral) terimi: hatanın ZAMAN İÇİNDE BİRİKİMİ. Kalıcı
    hatayı sıfırlar. Buradaki işi çok somut: **asılı gazı bulmak.**
  * ASILI GAZ (hover throttle): aracı ne yükselten ne alçaltan çubuk konumu.
    Araç ağırlığına, pervaneye ve PİL GERİLİMİNE bağlıdır; pil boşaldıkça
    YÜKSELİR. Bu yüzden sabit yazılamaz — tümlev onu bulur ve takip eder.
  * DOYUM (saturation): çıkışın sınıra dayanıp artamaması.
  * TÜMLEV ŞİŞMESİ (integral windup): çıkış doyumdayken hata devam ettiği
    için tümlevin büyümeye devam etmesi. Sonra hata tersine dönse bile
    tümlevin boşalması saniyeler sürer ve araç hedefi AŞAR. Çaresi
    "koşullu tümlevleme": doyumdayken ve hata doyumu DERİNLEŞTİRİYORKEN
    tümlev DONDURULUR. (Bu depoda aynı çare `dow/gudum/kilit.py`'de var.)
  * EĞİM SINIRI (slew): komutun saniyede en fazla ne kadar değişebileceği.
  * İLERİ BESLEME (feedforward): ölçümü beklemeden, BİLİNEN bir bozucuyu
    doğrudan komuta eklemek. Burada bozucu = aracın yatması.
  * SARSINTISIZ DEVİR (bumpless transfer): elden otomatiğe geçerken çıkışın
    sıçramaması. Tümlevi, çıkış O ANKİ çubukla aynı olacak şekilde
    tohumlayarak sağlanır.

--------------------------------------------------------------------------------
YASA
--------------------------------------------------------------------------------
    hata     = vz_istenen − vz_ölçülen                       [m/s]
    P        = kırp(KP · hata, ±P_YETKI)
    I       += KI · hata · dt          (koşullu; ±I_MAX ile sınırlı)
    ham      = ASILI_0 + I + P
    ham      = eğim_telafisi(ham, cos_yatış)                  ← ileri besleme
    çubuk    = eğim_sınırla(kırp(ham, THR_MIN, THR_MAX))

--------------------------------------------------------------------------------
ÜÇ SINIRIN ÜÇ AYRI İŞİ VAR — karıştırılmamalı
--------------------------------------------------------------------------------
  P_YETKI  ±0.15  ANİ yetki. Ne kadar sert bir düzeltme yapılabileceğini
                  sınırlar. ±0.15 çubuk ≈ ±2.9 m/s² dikey ivme. Amaç:
                  aracın sarsılmaması ve kameranın bulanmaması.
  I_MAX    ±0.35  YAVAŞ yetki. Asılı gazı arama aralığı. Geniş olmalı,
                  çünkü asılı gaz araca/pile göre 0.35 kadar kayabilir.
  THR_MIN  −0.50  MUTLAK emniyet. Bu ikisi ne olursa olsun aşılmaz.
  THR_MAX  +0.50  Alt sınır motorun KESİLMEMESİNİ, üst sınır aracın
                  roket gibi kaçmamasını garanti eder.

  ⭐ ÜÇÜ ARASINDAKİ İLİŞKİ — KASTEN İYİ KOŞULLANMIŞ (bekçi R27b):
        ASILI_0 + I_MAX + P_YETKI  =  0.0 + 0.35 + 0.15  =  0.50  =  THR_MAX
     Yani tümlev, çıkışın İFADE EDEBİLECEĞİNDEN fazla birikemez. Bu,
     şişmeyi YAPISAL olarak imkânsız kılar; koşullu tümlevleme ikinci
     savunma hattı olarak kalır (ASILI_0 ölçümle kayarsa yine gerekir).
     ⚠ Bu ilişki bozulursa tümlev "görünmez" bir bölgede birikir ve hata
       tersine döndüğünde boşalması gecikir. R27b bunu sınar.

--------------------------------------------------------------------------------
KAZANÇLARIN TÜRETMESİ (sayılar nereden geliyor)
--------------------------------------------------------------------------------
1) UYARICI KAZANCI. İtki T = k·u² (u = 0..1 gaz kesri). Asılıda T = m·g:
       k·u_a² = m·g   →   dT/du = 2·m·g/u_a   →   da_z/du = 2g/u_a
   Çubuk [-1,+1] aralığı gaz kesri [0,1]'e denk düştüğü için du/dçubuk = 0.5:
       u_a = 0.50  →  da_z/dçubuk ≈ 19.6 m/s²  (K_UYARICI)

2) ORANSAL KAZANÇ. Saf P ile kapalı döngü birinci mertebedir:
       τ = 1 / (K_UYARICI · KP)
       τ = 1.0 s  →  KP = 1/(19.6·1.0) = 0.0510

3) ⚠ τ SEÇİMİMİ TEZGÂH ÇÜRÜTTÜ — ve gerekçesi öğreticidir.
   ÖNCE τ = 2.0 s seçmiştim. Gerekçem "ölçüm gecikmesi ~450 ms, kural
   gecikme < τ/3, o hâlde τ > 1.35 s" idi. `araclar/dikey_sim.py`
   ölçünce bunun YANLIŞ olduğu çıktı:

       τ=3.0 (KP=0.017) -> aşım +0.50 m/s
       τ=2.0 (KP=0.026) -> aşım +0.31 m/s
       τ=1.0 (KP=0.051) -> aşım +0.11 m/s      <- EN İYİ
       τ=0.5 (KP=0.102) -> aşım +0.41 m/s

   SEBEP: buradaki aşımı GECİKME değil TÜMLEV üretiyor. P zayıf olunca
   hata uzun sürüyor, tümlev o sürede birikiyor ve sonra hedefi aşıyor.
   Güçlü P hatayı hızlı kapatınca tümlev neredeyse hiç kımıldamıyor.
   "gecikme < τ/3" kuralı SAF KAZANÇLI bir döngü içindir; PI'da tümlev
   baskın olduğunda yanıltır.
   ⛔ DERS: kural kitabından gelen bir sayı, ölçülmeden varsayılan yapılmaz.

4) TÜMLEV KAZANCI. Ti = 10 s → KI = KP/Ti = 0.0051.
   Tarandı (KP sabit, Ti değişken, kötü gecikme koşulunda):
       Ti= 1.0  KI=0.0510 -> aşım 1.18, kötü gecikmede 11 salınım  ⛔
       Ti= 2.5  KI=0.0204 -> aşım 0.55, kötü gecikmede 10 salınım  ⛔
       Ti= 6.0  KI=0.0085 -> aşım 0.24, 3 geçiş
       Ti=10.0  KI=0.0051 -> aşım 0.14, 3 geçiş                    <- SEÇİLDİ
   Yavaş görünüyor ve KASTEN öyle: asılı gazın İLK değeri tahminle değil,
   SARSINTISIZ DEVİRLE geliyor (pilotun o andaki çubuğu). Tümlevin işi
   yalnız pil düşüşünü takip etmek — o da dakikalar sürer.

5) TÜMLEVİN KALICI HATASI — formül ve niye önemsiz
   PI kontrolcü BASAMAK bozucuya sıfır kalıcı hata verir, ama RAMPA
   bozucuya sabit hata bırakır (pil düşüşü bir rampadır):
           e_kalıcı = R / KI          R = asılı gazın çubuk/s kayması
   Gerçekçi R: LiPo 4.2→3.5 V/hücre, itki ~%30 düşer, gaz kesri 1.20 kat
   artar (0.45→0.54), 300 s'de 0.18 çubuk → R = 0.0006 çubuk/s
           e_kalıcı = 0.0006 / 0.0051 = 0.12 m/s
   ⭐ VE BU BİLE KAÇMAZ: güdümün DIŞ döngüsü (gps.py: vz = KP_Z·Δz,
     KP_Z=0.9) bu hızı sabit bir İRTİFA ÖTELEMESİNE çevirir:
           0.12 / 0.9 = 0.13 m        (tezgâhta ölçüldü: −0.131 m)
   ⛔ Bu ayrımı görmeden dikey döngüyü TEK BAŞINA ölçüp "1.5 m/s kalıcı
     hata var, kaçıyor" demek YANLIŞ TEŞHİSTİR. İlk ölçümümde tam bunu
     yapmıştım.

6) ÖLÇÜLEN KARARLILIK ZARFI (araclar/dikey_sim.py, +2 m/s basamağı, aşım m/s)

       gecikme / T/W      2.5   3.0   4.0   5.0   6.0   8.0
       10 Hz / 0.15 s     0.10  0.09  0.09  0.08  0.08  0.08
        8 Hz / 0.25 s     0.11  0.11  0.12  0.14  0.17  0.23
        5 Hz / 0.40 s     0.20  0.23  0.30  0.36  0.43  0.55
        3 Hz / 0.60 s     0.44  0.51  0.64  0.75  0.87  1.04 ⚠

   24 hücrenin 23'ü rahat oturuyor. TEK sınır hücre üçlü en-kötü köşe:
   3 Hz telemetri VE 0.6 s baro gecikmesi VE T/W 8. (Salınım değil,
   yalnız yüksek aşım.) 7 inç bir avcı drone kamera+VTX taşıdığı için
   T/W 8'de olması beklenmez; yine de:
   ⛔ İŞLETME KURALI: telemetri hızı UÇUŞTAN ÖNCE ÖLÇÜLÜR
     (`reel/araclar/telem_olc.py`). Ölçülen hız TELEM_MIN_HZ altındaysa
     otonom dikey döngü AÇILMAZ. Bu, yukarıdaki sınır hücreye hiç
     girmemeyi garanti eder.

7) GÜRÜLTÜ — kısıt DEĞİL (ölçüldü)
   Ölçüm gürültüsü 0.6 m/s iken çubuk oynaması tik başına 0.015 birim
   = ~8 µs. Motorlar bunu görmez bile. Yani KP'yi büyütmenin bedeli
   gürültü değil, yalnız model kazancı belirsizliğidir (madde 8).

8) MODEL KAZANCI BELİRSİZLİĞİ — asıl kısıt
   K = g·sqrt(T/W). Fiziksel aralıkta (T/W 2.5-8) K = 15.5..27.7, yani
   tahminimizin ×0.79..×1.42'si. Bu DAR bir bant ve seçilen KP tüm
   bandda oturuyor (madde 6 tablosu). ⚠ İlk taramamı "kazanç ×3'e kadar"
   diye kurmuştum; o, asılı gazın %16.7 olması = 36:1 itki/ağırlık
   demekti — fiziksel değil, ve her ayarı sahte biçimde "kırık"
   gösteriyordu. Doğru tarama değişkeni İTKİ/AĞIRLIK oranıdır.

--------------------------------------------------------------------------------
EĞİM TELAFİSİ — niye ve neden karekök
--------------------------------------------------------------------------------
Araç θ kadar yattığında itkinin DİKEY bileşeni T·cos(θ)'ya iner. Aynı dikey
kuvveti sürdürmek için itki T/cos(θ) olmalı. İtki gazın KARESİYLE arttığı
için (T ∝ u²) gerekli gaz:
        u' = u / sqrt(cos θ)
    θ=30° → 1.075x    θ=45° → 1.189x    θ=60° → 1.414x
⚠ Betaflight'ın gaz→itki eğrisi tam kare değildir (`thrust_linear`, motor
  eğrisi). Bu yüzden üs AYARLANABİLİR (TELAFI_US): 0.5 = kare model,
  1.0 = doğrusal model. Bu bir İLERİ BESLEMEDİR; yaklaşık doğru olması
  yeter, kalanını tümlev kapatır.
⛔ cos TABANI: 60°'de cos = 0.5. Daha dikte telafi patlar (80° → 5.8 kat).
  Bu yüzden cos, COS_TABAN'ın altına indirilmez.
================================================================================
"""
import math
import os


def _f(ad, v):
    return float(os.environ.get(ad, v))


def _kirp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class DikeyCfg:
    """Dikey döngü ayarları. Hepsi `DOW_DIK_*` env ile geçersiz kılınabilir.

    ⛔ VARSAYILANLAR "GÜVENLİ TARAF"TIR, "İYİ AYAR" DEĞİL. İlk uçuşta yavaş
       ve yetkisi kısık olmaları KASTENDİR. Ayar, ölçümle açılır (§4).
    """
    KP        = _f("DOW_DIK_KP", 0.0510)     # çubuk/(m/s); τ=1.0 s (ölçüldü)
    KI        = _f("DOW_DIK_KI", 0.0051)     # çubuk/(m/s)/s; Ti=10 s (tarandı)
    P_YETKI   = _f("DOW_DIK_P_YETKI", 0.15)  # ANİ yetki
    I_MAX     = _f("DOW_DIK_I_MAX", 0.35)    # YAVAŞ yetki (asılı gaz arama)
    THR_MIN   = _f("DOW_DIK_THR_MIN", -0.50)  # MUTLAK alt sınır
    THR_MAX   = _f("DOW_DIK_THR_MAX", 0.50)   # MUTLAK üst sınır
    ASILI_0   = _f("DOW_DIK_ASILI", 0.0)     # ilk tahmin (0 = 1500 µs = %50)
    SLEW      = _f("DOW_DIK_SLEW", 1.0)      # çubuk/s
    TELAFI_US = _f("DOW_DIK_TELAFI_US", 0.5)  # 0.5 = kare itki modeli
    COS_TABAN = _f("DOW_DIK_COS_TABAN", 0.5)  # 60°'den dike telafi yok
    # Düşey hız isteğinin kendi tavanı. Güdüm 33 m/s isteyebilir (DoW'un
    # zarfı); gerçek 7" quad'da o sayı anlamsız ve TEHLİKELİDİR.
    VZ_MAX_TIRMAN = _f("DOW_DIK_VZ_TIRMAN", 5.0)   # m/s
    VZ_MAX_ALCAL  = _f("DOW_DIK_VZ_ALCAL", 4.0)    # m/s
    # Ölçüm bu kadar bayatsa döngü DONAR (§5.3 — bayat ölçümle kapalı döngü
    # kapalı değildir, açık döngüdür ve kaçar).
    OLCUM_MAX_YAS_S = _f("DOW_DIK_OLCUM_YAS", 0.5)
    # ⛔ İŞLETME KAPISI (başlık madde 6): telemetri bu hızın altındaysa
    #    otonom dikey döngü açılmaz. Zarf tablosunun sınır hücresine hiç
    #    girmemeyi garanti eder. Ölçüm: reel/araclar/telem_olc.py
    TELEM_MIN_HZ = _f("DOW_DIK_TELEM_MIN_HZ", 4.0)


class DikeyDongu:
    """Düşey hız isteğini throttle çubuğuna çeviren PI + ileri besleme.

    KULLANIM:
        d = DikeyDongu()
        d.sifirla(thr_pilotun_o_anki)      # SARSINTISIZ devir
        thr = d.hesapla(vz_istenen=+2.0, vz_olculen=+0.4, dt=0.02,
                        cos_yatis=0.87, olcum_yasi=0.12)
    """

    def __init__(self, cfg=DikeyCfg):
        self.cfg = cfg
        self.I = 0.0
        self.son_thr = None
        self.aktif = False
        self.tani = {}
        # §5.1 MEKANİZMA SAYACI — pasifken kaç kez çağrıldık?
        # ⛔ SESSİZ ARIZA TUZAĞI (2026-08-29, uçtan uca test yakaladı):
        #   `sifirla()` çağrılmadan `hesapla()` çalışırsa döngü SABİT
        #   ASILI_0 döndürür. Araç komuta cevap vermez ve HİÇBİR HATA
        #   GÖRÜNMEZ. Sahada bu, "sistem bozuk" diye bir gün yakardı.
        #
        # ⚠ AMA "dik_pasif > 0" TEK BAŞINA ARIZA DEĞİLDİR — ilk ölçütüm
        #   fazla katıydı ve testte yakalandı. Pilot MANUEL uçarken güdüm
        #   döngüsü de koşmaya devam eder ve çıktısı ATILIR; o sırada
        #   binlerce pasif çağrı olması NORMALDİR.
        #   ARIZA ŞUDUR: OTONOM kaynağı KULLANILIRKEN döngünün pasif
        #   olması. Onu `aktif` bayrağı ile birlikte okuyun:
        #       kaynak=OTONOM  ve  aktif=False   -> GEÇERSİZ koşu
        #   Koşu araçları bu iki sütunu YAN YANA raporlar.
        self.n_pasif_cagri = 0

    # ------------------------------------------------------------------
    def sifirla(self, thr_baslangic=None):
        """Döngüyü kur. `thr_baslangic` verilirse SARSINTISIZ DEVİR yapılır.

        ⛔ NİYE ÖNEMLİ: pilot elle asılı dururken otomatiğe geçtiğimizde
           çıkışımız birden ASILI_0'a sıçrarsa araç ya düşer ya fırlar.
           Tümlevi, ilk çıkış TAM O ANKİ ÇUBUK olacak şekilde tohumluyoruz:
               ASILI_0 + I = thr_baslangic   ->   I = thr_baslangic − ASILI_0
           Böylece devir anında komut DEĞİŞMEZ; döngü oradan devam eder.
           Ayrıca bu, asılı gazın ÖLÇÜLMÜŞ değerini bedavaya verir —
           pilotun çubuğu zaten o bilgidir.
        """
        c = self.cfg
        if thr_baslangic is None:
            self.I = 0.0
            self.son_thr = None
        else:
            self.I = _kirp(float(thr_baslangic) - c.ASILI_0, -c.I_MAX, c.I_MAX)
            self.son_thr = float(thr_baslangic)
        self.aktif = True
        self.tani = {}

    def durdur(self):
        self.aktif = False

    # ------------------------------------------------------------------
    def _egim_telafi(self, thr, cos_yatis):
        """Yatışın dikey itki kaybını ÖNCEDEN telafi et (ileri besleme).

        Çubuk uzayında değil GAZ KESRİ uzayında yapılır: çubuk [-1,+1]
        aralığı gaz kesri [0,1]'e denk düşer, ve fizik gaz kesrinde geçerli.
        """
        c = self.cfg
        cz = max(float(cos_yatis), c.COS_TABAN)
        if cz >= 0.9999:
            return thr
        u = (thr + 1.0) * 0.5                       # çubuk -> gaz kesri
        u = u / (cz ** c.TELAFI_US)
        return u * 2.0 - 1.0                        # gaz kesri -> çubuk

    def hesapla(self, vz_istenen, vz_olculen, dt, cos_yatis=1.0,
                olcum_yasi=0.0, tumlevle=True):
        """Bir tik. Döner: throttle çubuğu [-1, +1].

        vz_istenen : güdümün istediği düşey hız, m/s, + = YUKARI
        vz_olculen : ÖLÇÜLEN düşey hız, m/s, + = YUKARI  (CRSF VARIO)
        cos_yatis  : cos(toplam yatış açısı); 1.0 = düz
        olcum_yasi : `vz_olculen` kaç saniye önceki ölçüm
        tumlevle   : False ise tümlev DONDURULUR (yerde / disarm / devir)
        """
        c = self.cfg
        if not self.aktif:
            self.n_pasif_cagri += 1
            self.tani = {"dik_pasif": self.n_pasif_cagri, "dik_thr": c.ASILI_0,
                         "dik_hata": 0.0, "dik_P": 0.0, "dik_I": 0.0,
                         "dik_doyum": 0, "dik_dondu": 0, "dik_bayat": 0,
                         "dik_yas": 0.0, "dik_telafi": 0.0, "dik_ham": c.ASILI_0}
            return c.ASILI_0

        # --- ölçüm bayatsa: kapalı döngü DEĞİLDİR, dondur ---------------
        # ⛔ Bayat ölçümle P terimi eski bir hatayı kovalar; tümlev ise
        #    körlemesine birikir. İkisi de aracı kaçırır. Güvenli davranış:
        #    son çubuğu koru (donmuş komut), tümlevi dondur.
        bayat = olcum_yasi > c.OLCUM_MAX_YAS_S
        if bayat and self.son_thr is not None:
            self.tani = {"dik_bayat": 1, "dik_yas": round(olcum_yasi, 3),
                         "dik_thr": round(self.son_thr, 4),
                         "dik_I": round(self.I, 4), "dik_hata": 0.0,
                         "dik_P": 0.0, "dik_doyum": 0, "dik_telafi": 1.0}
            return self.son_thr

        vz_ist = _kirp(float(vz_istenen), -c.VZ_MAX_ALCAL, c.VZ_MAX_TIRMAN)
        hata = vz_ist - float(vz_olculen)

        P = _kirp(c.KP * hata, -c.P_YETKI, c.P_YETKI)
        ham = c.ASILI_0 + self.I + P
        telafili = self._egim_telafi(ham, cos_yatis)
        kirpik = _kirp(telafili, c.THR_MIN, c.THR_MAX)

        # --- KOŞULLU TÜMLEVLEME (anti-windup) ---------------------------
        # Çıkış doyumdaysa VE hata doyumu DERİNLEŞTİRİYORSA tümlev donar.
        # Aksi hâlde (hata doyumdan ÇIKARACAK yöndeyse) tümlev çalışır —
        # yoksa doyumdan çıkış da imkânsızlaşırdı.
        doymus = abs(kirpik - telafili) > 1e-12
        derinlestiriyor = doymus and (
            (hata > 0 and telafili > kirpik) or (hata < 0 and telafili < kirpik))
        if tumlevle and not derinlestiriyor:
            self.I = _kirp(self.I + c.KI * hata * dt, -c.I_MAX, c.I_MAX)

        # --- eğim sınırı ------------------------------------------------
        if self.son_thr is None:
            self.son_thr = kirpik
        elif c.SLEW > 0.0:
            tavan = c.SLEW * dt
            self.son_thr += _kirp(kirpik - self.son_thr, -tavan, tavan)
        else:
            self.son_thr = kirpik

        # §5.1 MEKANİZMA SÜTUNLARI — "özellik gerçekten çalıştı mı"
        #   dik_P sürekli 0 ise döngü hiç düzeltme yapmıyordur.
        #   dik_doyum sürekli 1 ise yetki yetmiyordur (ya da işaret ters).
        self.tani = {
            "dik_hata": round(hata, 3),
            "dik_P": round(P, 4),
            "dik_I": round(self.I, 4),
            "dik_ham": round(ham, 4),
            "dik_telafi": round((telafili - ham), 4),
            "dik_doyum": int(doymus),
            "dik_dondu": int(derinlestiriyor),
            "dik_thr": round(self.son_thr, 4),
            "dik_bayat": 0,
            "dik_yas": round(olcum_yasi, 3),
            "dik_pasif": self.n_pasif_cagri,
        }
        return self.son_thr


def yatis_cos(roll_rad, pitch_rad):
    """Toplam yatış açısının kosinüsü — itkinin dikey bileşen çarpanı.

    TÜRETME: gövde Z ekseninin dünya dikeyiyle yaptığı açının kosinüsü,
    dönme matrisinin (3,3) elemanıdır:
            cos(θ_toplam) = cos(roll) · cos(pitch)
    ⚠ "roll + pitch"i toplamak YANLIŞTIR: 30° roll + 30° pitch, 60° yatış
      DEĞİLDİR. Doğrusu cos30·cos30 = 0.75 → θ = 41.4°.
    """
    return math.cos(float(roll_rad)) * math.cos(float(pitch_rad))
