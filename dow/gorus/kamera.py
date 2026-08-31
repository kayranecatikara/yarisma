# -*- coding: utf-8 -*-
"""
================================================================================
DOW KAMERA MODELİ — ÖLÇÜLDÜ (2026-08-21, kendi uçuşumuz)
================================================================================
Kamera gövdeye SABİT (gimbal yok) ve burnun TILT derece YUKARISINA bakar.
Araç Angle Mode'da öne yatınca kamera da onunla aşağı döner — bu telafi
edilmezse hedef kadrajın altından kaçar. (2026-08-21'de tam bunu yaşadık:
pitch 0.28 komutu gövdeyi 17° yatırdı, kamera ekseni 25° -> 8°'ye indi,
hedef kadrajdan çıktı ve dedektör "bulamadı" sandık.)

KALİBRASYON YÖNTEMİ
  Truth geometriden (menzil, yükseliş, kerteriz) + kendi roll/pitch'imizden
  hedefin kadraj konumu öngörüldü; ölçülen bbox merkeziyle en küçük kareler.
  fx=fy kısıtlı (kare piksel FİZİKSEL zorunluluk) + aykırı değer atmalı.
  SONUÇ: artık 2.6 px, n=614 (kısıtsız serbest çözümde artık 170 px'ti).

ÖLÇÜLEN DEĞERLER
  TILT = 26.50°   f = 540.4 px   -> HFOV 121.2°, VFOV 90.0°  @1920x1080

BELİRSİZLİK (soruldu: "26.5 kesin değer mi?")
  Artık eğrisi KESKİN bir çukur yapıyor (n=635 iç küme):
     TILT 25.00 -> artık 5.10 px      (README'nin değeri)
     TILT 26.00 -> artık 3.10 px
     TILT 26.50 -> artık 2.56 px      <- EN İYİ
     TILT 27.00 -> artık 2.80 px
     TILT 28.00 -> artık 5.14 px
  BOOTSTRAP (60 yeniden örnekleme): 26.57° ± 0.11°, %5-95: 26.50-26.75
  => 25° KESİN OLARAK ELENİR: orada artık İKİ KATINA çıkıyor.

  Kalan pay SİSTEMATİK: f ile TILT fitte birbirine bağlı (eğride ikisi
  birlikte artıyor). Ölçüm paketinin bağımsız f=531.4 değeri dayatılırsa
  TILT ~26.2 çıkar. Gerçek değer 26.2-26.6 bandında; her hâlükârda 25 değil.
  SEÇİM: 26.50 (kendi kurulumumuzda, kendi ölçümümüzle).

  KIYAS: ölçüm paketi f=531.4/HFOV 122.07/VFOV 90.93/tilt 22.9
         README        HFOV 125 / tilt 25
  ⚠ Ölçüm paketi kendi kurulumunda "1536x864 mantıksal uzay, 1.25 Windows DPI
    ölçeği" notu düşmüş. Proton altında DPI zinciri FARKLI; bu yüzden onların
    f'i bize doğrudan taşınmaz. Kendi ölçümümüz esastır.

MENZİL SABİTİ (ayrı ölçüm, n=59 gerçek tespit)
  C = kutu_genisligi x menzil = 997 px·m  (%25-75: 855-1060)
  Geometrik beklenen f*S = 540.4*1.718 = 928 -> ölçülen/beklenen = 1.07
  (bbox kanat uçlarından biraz taşıyor; ampirik değer kullanılır)
  ⚠ Gazebo sabitimiz 1920'ye ölçeklenince 557 olurdu -> 1.79 KAT YANLIŞ.

İŞARET SÖZLEŞMESİ (ölçüldü)
  get_drone_rotation() -> (roll, pitch, yaw) DERECE.
  pitch NEGATİF = burun AŞAĞI (ileri uçuş). Ölçülen bant: -21°..0°.
================================================================================
"""
import math
import os

# ============================================================================
#  ⭐ GERÇEK DONANIM DİKİŞİ (2026-08-29)
#
#  Aşağıdaki sabitler SİMÜLASYONDA ölçüldü. Gerçek uçakta kamera BAŞKA:
#  başka mercek, başka montaj açısı, başka yakalama çözünürlüğü. Bu
#  sabitleri gerçek değerlerle DEĞİŞTİRMEDEN görsel güdüm menzili ve
#  kerterizi YANLIŞ hesaplar — ve hata sessizdir, hiçbir yerde patlamaz.
#
#  ⛔ NEDEN ENV, NEDEN KOD DEĞİL: güdüm YASASI değişmiyor; değişen KAMERA
#    MODELİ. Simülasyonda ölçülmüş davranışın bit bit korunması için
#    varsayılanlar aynen bırakıldı — hiçbir DOW_OPTIK_* verilmezse çıktı
#    bu dosyanın önceki hâliyle BİREBİR aynıdır.
#
#  ⚠ ÇÖZÜNÜRLÜK TUZAĞI: F_PX ve CX/CY, kalibrasyonun YAPILDIĞI çözünürlüğe
#    bağlıdır. Yakalama kartı 1280x720 verirken 1920x1080 sabitleri
#    kullanılırsa aynı hedef 40 px yerine 27 px görünür ve menzil 25 m
#    yerine 37 m denir — %50 hata, sessiz. Bu yüzden DOW_OPTIK_W/H de
#    ayarlanabilir ve `drone_yki.py` gerçek kare boyutuyla karşılaştırıp
#    uyumsuzlukta YÜKSEK SESLE uyarır.
#
#  Ölçüm aracı: reel/gercek/kamera_ayari.py
# ============================================================================
def _env_f(ad, varsayilan):
    v = os.environ.get(ad)
    if v is None or v == "":
        return varsayilan
    try:
        return float(v)
    except ValueError:
        raise ValueError("%s='%s' sayı değil" % (ad, v))


IMG_W = int(_env_f("DOW_OPTIK_W", 1920))
IMG_H = int(_env_f("DOW_OPTIK_H", 1080))
CX, CY = IMG_W/2.0, IMG_H/2.0

TILT_DEG = _env_f("DOW_OPTIK_TILT", 26.50)   # kamera ekseninin burna göre YUKARI açısı
F_PX     = _env_f("DOW_OPTIK_F_PX", 540.4)   # fx = fy (kare piksel)
MENZIL_C = _env_f("DOW_OPTIK_MENZIL_C", 997.0)   # px·m; R = MENZIL_C / kutu_genisligi
# ⭐ KÖŞEGEN ÖLÇÜSÜ İÇİN AYRI SABİT (2026-08-28) — bkz. IbvsCfg.MENZIL_OLCU.
#   TÜRETME (§0.2): sabit, DÜZ UÇUŞTA algılanan menzili DEĞİŞTİRMEYECEK
#   şekilde seçildi; böylece iki ölçü arasındaki TEK fark YATIŞA
#   DUYARLILIK olur (§4 tek değişken).
#     ölçüldü (KREG24+KILIT16, |yatış|<8°):  max(w,h)·R = 951   köşegen·R = 1005
#     C_köşegen = 997 · 1005/951 = 1053.6
#   Sonuç — algılanan/gerçek menzil oranı:
#     yatış  düz    max(w,h) 1.048x   köşegen 1.048x   (BİREBİR aynı)
#     yatış >32°    max(w,h) 1.180x   köşegen 1.070x   (şişme %18 -> %7)
MENZIL_C_KOSEGEN = _env_f("DOW_OPTIK_MENZIL_C_KOSEGEN", 1053.6)
KANAT_M  = _env_f("DOW_OPTIK_KANAT", 1.718)   # Talon kanat açıklığı (belge)

HFOV_DEG = 2*math.degrees(math.atan(CX/F_PX))
VFOV_DEG = 2*math.degrees(math.atan(CY/F_PX))


# ============================================================================
#  ⭐ BALIKGÖZ (FISHEYE) DİKİŞİ — 30 Ağu 2026
#
#  SİMDE YOKTU: oyun motorları (UE5) PERSPEKTİF, yani delikli iğne
#  projeksiyonuyla render eder. Gerçek FPV merceği balıkgözdür ve iki
#  şeyi birden bozar:
#
#   1. KERTERİZ. `atan(r/F_PX)` delikli iğnenin tersidir. Balıkgözde
#      gerçek açı bambaşkadır. FOV'dan pinhole formülüyle türetilen
#      F_PX yalnız KÖŞEDE doğrudur (formül oraya oturtulur); merkez
#      civarında 1.76 KAT yanılır. Güdüm `yaw + 3.0·azimut` uyguladığı
#      için bu, 38°'ye varan fazla yaw komutu demektir.
#
#   2. MENZİL. Kutu boyutu kadraj konumuna göre değişir. Eşuzaklık
#      balıkgözde cisim kenarda TEĞET yönde uzar (radyal yönde aynı
#      kalır); köşede köşegen ölçüsü %11 büyür -> menzil %10 yakın
#      sanılır. Bu, kerteriz hatasının yanında küçüktür ama vardır.
#
#  ⛔ GÖRÜNTÜ DÜZELTİLMEZ (`cv2.fisheye.undistortImage` KULLANILMAZ):
#     dedektör BOZUK karelerle eğitildi; düzeltilmiş kare onun eğitim
#     dağılımının dışına çıkar ve tespit KÖTÜLEŞİR. Ayrıca her karede
#     tam görüntü dönüşümü pahalıdır. Bize görüntü değil, İKİ SKALER
#     EŞLEME lazım: piksel->açı ve kutu->menzil. İkisi de analitik.
#
#  MODELLER
#    pinhole    : r = F_PX·tan θ          (VARSAYILAN — bit bit eski hâl)
#    esuzaklik  : r = f·θ                 (tek parametre; FOV'dan çıkar)
#    opencv     : r = f·θ(1+k₁θ²+k₂θ⁴+k₃θ⁶+k₄θ⁸)   (Kannala-Brandt)
#                 OpenCV `cv2.fisheye.calibrate` tam bunu verir.
#
#  ⛔ VARSAYILAN `pinhole` — hiçbir DOW_OPTIK_MODEL verilmezse davranış
#     BİREBİR eskisidir; `araclar/denklik.py` bunu doğrular.
# ============================================================================
OPTIK_MODEL = os.environ.get("DOW_OPTIK_MODEL", "pinhole").strip().lower()
if OPTIK_MODEL not in ("pinhole", "esuzaklik", "opencv"):
    raise ValueError("DOW_OPTIK_MODEL='%s' — pinhole | esuzaklik | opencv"
                     % OPTIK_MODEL)

#: balıkgöz odak (px/radyan). Verilmezse köşegen FOV'dan türetilir.
_FBG_VAR = os.environ.get("DOW_OPTIK_FBG")
if _FBG_VAR:
    F_BG = float(_FBG_VAR)
else:
    # yarı_köşegen / (yarı_FOV radyan).  FOV verilmezse pinhole F_PX'ten
    # eşdeğer köşegen FOV'a geçilir — kaba ama tutarlı bir başlangıç.
    _fov_kos = os.environ.get("DOW_OPTIK_FOV_KOSEGEN")
    _yari_kos = math.hypot(IMG_W, IMG_H) / 2.0
    if _fov_kos:
        F_BG = _yari_kos / math.radians(float(_fov_kos) / 2.0)
    else:
        F_BG = _yari_kos / math.atan(_yari_kos / F_PX)

#: OpenCV fisheye bozulma katsayıları k1..k4 ("k1,k2,k3,k4")
_D_VAR = os.environ.get("DOW_OPTIK_D", "")
D_KATSAYI = ([float(x) for x in _D_VAR.replace(" ", "").split(",")]
             if _D_VAR else [0.0, 0.0, 0.0, 0.0])
if len(D_KATSAYI) != 4:
    raise ValueError("DOW_OPTIK_D dört sayı olmalı: k1,k2,k3,k4")


def _theta_d(th):
    """Kannala-Brandt ileri eşleme: θ -> θ_d  (r = f·θ_d)."""
    k1, k2, k3, k4 = D_KATSAYI
    t2 = th * th
    return th * (1.0 + t2 * (k1 + t2 * (k2 + t2 * (k3 + t2 * k4))))


def _theta_d_turev(th):
    """dθ_d/dθ — radyal yerel ölçek (merkezde 1)."""
    k1, k2, k3, k4 = D_KATSAYI
    t2 = th * th
    return 1.0 + t2 * (3.0 * k1 + t2 * (5.0 * k2 + t2 * (7.0 * k3
                                                         + t2 * 9.0 * k4)))


def aci_yaricaptan(r_px):
    """Piksel yarıçapı -> KAMERA EKSENİNDEN gerçek açı (radyan).

    ⛔ Bu, güdümün nişan aldığı AÇIDIR. Yanlışsa uçak yanlış yöne döner.
    """
    if r_px <= 0.0:
        return 0.0
    if OPTIK_MODEL == "pinhole":
        return math.atan(r_px / F_PX)
    if OPTIK_MODEL == "esuzaklik":
        return r_px / F_BG
    # opencv: θ_d = r/f biliniyor, θ için Newton (birkaç adım yeter)
    hedef = r_px / F_BG
    th = hedef                      # k=0 iken tam çözüm
    for _ in range(8):
        f = _theta_d(th) - hedef
        d = _theta_d_turev(th)
        if abs(d) < 1e-12:
            break
        yeni = th - f / d
        if abs(yeni - th) < 1e-10:
            th = yeni
            break
        th = yeni
    return max(0.0, th)


def olcek_duzeltme(cx_px, cy_px):
    """Kutu boyutunun MERKEZE GÖRE yerel ölçeği (köşegen ölçüsü için).

    Menzil `R = C/boyut` ile hesaplanıyor ve `C` MERKEZDE kalibre edilir.
    Kadrajın kenarında aynı cisim farklı piksel kaplar; düzeltme:

        R_doğru = C · olcek_duzeltme(cx, cy) / boyut

    Yerel ölçekler (merkeze göre):
        radyal   = dθ_d/dθ
        teğetsel = θ_d / sin θ
    Köşegen ölçüsü ikisinin arasında; geometrik ortalama alınır.

    ⚠ VARSAYIM: kutunun yönelimi bilinmiyor, izotropik yaklaşım yapılıyor.
      Kenarda kutu radyal/teğet ayrımına duyarlıdır; hata ikinci derecedir.
    """
    if OPTIK_MODEL == "pinhole":
        return 1.0                      # eski davranış — hiç dokunma
    r = math.hypot(cx_px - CX, cy_px - CY)
    if r <= 1e-6:
        return 1.0
    th = aci_yaricaptan(r)
    if th <= 1e-9:
        return 1.0
    radyal = _theta_d_turev(th)
    tegetsel = _theta_d(th) / math.sin(th)
    kosegen = math.sqrt(max(1e-9, radyal * tegetsel))
    return kosegen


def menzil(kutu_genislik_px):
    """Kutu genişliğinden menzil (m). Delik-iğne benzer üçgenler: p = C/R."""
    if kutu_genislik_px <= 0:
        return None
    return MENZIL_C / float(kutu_genislik_px)


def piksel_aci(cx_px, cy_px):
    """Kadraj konumundan KAMERA EKSENİNE göre (yatay, dikey) açı (derece).
    dikey>0 = kamera ekseninin ÜSTÜNDE."""
    dx, dy = (cx_px - CX), (CY - cy_px)
    if OPTIK_MODEL == "pinhole":
        # ⛔ ESKİ DAVRANIŞ — bit bit korunur
        return (math.degrees(math.atan(dx / F_PX)),
                math.degrees(math.atan(dy / F_PX)))
    # ⭐ BALIKGÖZ: gerçek açı yarıçaptan çıkar, sonra bileşenlere ayrılır.
    #   Yön (dx, dy) korunur; yalnız BÜYÜKLÜK doğru modelden gelir.
    r = math.hypot(dx, dy)
    if r <= 1e-9:
        return (0.0, 0.0)
    th = aci_yaricaptan(r)                     # gerçek açı (rad)
    # Küre üstündeki yönü düzleme izdüşür: tan(θ) ölçeğiyle bileşenlere böl.
    # Böylece küçük açıda eski davranışla sürekli, büyük açıda doğru olur.
    t = math.tan(th)
    return (math.degrees(math.atan(t * dx / r)),
            math.degrees(math.atan(t * dy / r)))


def piksel_kerteriz(cx_px, cy_px, own_pitch_deg, own_roll_deg=0.0):
    """Kadraj konumundan GÖVDE-BAĞIMSIZ kerteriz (derece):
    (azimut, yükseliş). Kendi pitch/roll'umuz telafi edilir.

    ⚠ YARIŞMA KURALI (§10): girdi YALNIZ bbox pikselleri + KENDİ IMU'muz.
      Hedefin GPS'i kullanılmaz -> görsel fazda meşrudur (ego-motion telafisi).
    """
    yat, dik = piksel_aci(cx_px, cy_px)
    # kamera ekseni: burun + TILT yukarı; gövde pitch'i (negatif=burun aşağı)
    # kamera eksenini o kadar aşağı çevirir.
    yukselis = dik + TILT_DEG + own_pitch_deg
    # roll, yatay/dikey bileşenleri karıştırır (küçük açı için birinci derece)
    if own_roll_deg:
        r = math.radians(own_roll_deg)
        c, s = math.cos(r), math.sin(r)
        yat, yukselis = yat*c - yukselis*s, yat*s + yukselis*c
    return yat, yukselis


def los_seviye(cx_px, cy_px, roll_deg, pitch_deg):
    """Piksel + aracın KENDİ duruşu → SEVİYE çerçevesinde (azimut, yükseliş).

    ⭐ Kullanıcının Gazebo deposundaki `bbox_ibvs.los_seviye` AYNEN taşındı
      (yalnız derece/radyan sarmalayıcısı eklendi, matematik birebir).

    NEDEN GEREKLİ: `piksel_kerteriz` roll'u BİRİNCİ DERECE küçük-açı
      yaklaşımıyla çeviriyor. Gazebo'da ölçülmüş: 30-40° yatışta bu
      yaklaşım 11-14° sapma veriyor. Bu zincir TAM dönüşüm yapar:
        1) piksel → kamera ışını      [sağ, aşağı, ileri]
        2) kamera → GÖVDE (FRD)       kamera TILT° yukarı vidalı: Ry(−tilt)
        3) gövde → SEVİYE             Ry(pitch)·Rx(roll) ile duruş çıkarılır

    ⭐ GİRDİ YALNIZ: bbox pikselleri + KENDİ IMU'muz (§10 temiz).
    Dönüş: (azimut, yükseliş) DERECE — azimut burna göre sağ+, yükseliş yukarı+.
    """
    x = (cx_px - CX) / F_PX
    y = (cy_px - CY) / F_PX
    t = math.radians(TILT_DEG)
    ct, st = math.cos(t), math.sin(t)
    bx = ct + st * y                     # ileri
    by = x                               # sağ
    bz = ct * y - st                     # aşağı
    r = math.radians(roll_deg); p = math.radians(pitch_deg)
    cr, sr = math.cos(r), math.sin(r)
    y1 = by * cr - bz * sr
    z1 = by * sr + bz * cr
    cp, sp = math.cos(p), math.sin(p)
    x2 = bx * cp + z1 * sp
    z2 = -bx * sp + z1 * cp
    return (math.degrees(math.atan2(y1, x2)),
            math.degrees(math.atan2(-z2, math.hypot(x2, y1))))


def seviye_piksel(azimut_deg, yukselis_deg, roll_deg, pitch_deg):
    """`los_seviye`in TAM TERSİ: seviye çerçevesindeki yönden kadraj konumu.

    Zincir ters çevrilir: seviye → gövde (Rx(roll)·Ry(-pitch)) → kamera
    (Ry(+tilt)) → piksel. Bridge (T5) bunu kullanır.
    ⭐ GİRDİ YALNIZ: açı + KENDİ IMU'muz. Menzil/GPS yok (§10 temiz).
    """
    a = math.radians(azimut_deg); e = math.radians(yukselis_deg)
    # seviye çerçevesinde birim vektör (ileri, sağ, aşağı)
    ce = math.cos(e)
    x2, y1, z2 = ce * math.cos(a), ce * math.sin(a), -math.sin(e)
    # seviye -> gövde: pitch geri
    p = math.radians(pitch_deg)
    cp, sp = math.cos(p), math.sin(p)
    bx = x2 * cp - z2 * sp
    z1 = x2 * sp + z2 * cp
    # gövde: roll geri
    r = math.radians(roll_deg)
    cr, sr = math.cos(r), math.sin(r)
    by = y1 * cr + z1 * sr
    bz = -y1 * sr + z1 * cr
    # gövde -> kamera ışını (Ry(+tilt) tersi)
    t = math.radians(TILT_DEG)
    ct, st = math.cos(t), math.sin(t)
    ileri = ct * bx - st * bz          # kamera ekseni bileşeni
    if abs(ileri) < 1e-9:
        return float("nan"), float("nan")
    y = (st * bx + ct * bz) / ileri
    x = by / ileri
    return CX + F_PX * x, CY + F_PX * y


def kerteriz_piksel(azimut_deg, yukselis_deg, own_pitch_deg, own_roll_deg=0.0):
    """`piksel_kerteriz`in TAM TERSİ: gövde-bağımsız kerterizden kadraj
    konumu (cx, cy).

    ⭐ YARIŞMA KURALI AÇISINDAN TEMİZ: girdisi yalnız AÇI + KENDİ IMU'muz.
      Menzil, hedef konumu, GPS — hiçbiri yok. (`beklenen_kadraj` bundan
      farklıdır: o menzil ve truth geometri ister, güdümde KULLANILMAZ.)

    KULLANIM: bbox köprüsü. İki çıkarım arasında (10 Hz -> 100 ms) ve tespit
    boşluklarında, son kutunun ATALET YÖNÜNÜ sabit tutup KENDİ dönüşümüzü
    telafi ederek kutunun kadrajda nereye kaydığını hesaplarız. Araç
    yattıkça (ölçüldü: roll p90 52.7°) hedef kadrajda hızla kayıyor;
    köprü bu kaymayı kapatır.
    """
    # ⚠ SIRA ÖNEMLİ. İleri dönüşüm (piksel_kerteriz) şunu yapıyor:
    #      dik  = piksel açısı
    #      yuk  = dik + TILT + pitch          <- ÖNCE kaydır
    #      (yat, yuk) roll ile +r döndürülür  <- SONRA döndür
    #   Tersi bu yüzden ÖNCE −r döndürüp SONRA kaydırmayı geri almalı.
    #   (İlk yazımımda sıra terstim: yatışlıyken 30° girdide 3.9° hata
    #    veriyordu — yani köprünün EN ÇOK gerektiği anda bozuluyordu.
    #    Bekçi B26'nın gidiş-dönüş kimlik sınaması yakaladı.)
    yat, yuk = azimut_deg, yukselis_deg
    if own_roll_deg:
        r = math.radians(own_roll_deg); c, s_ = math.cos(r), math.sin(r)
        yat, yuk = yat*c + yuk*s_, -yat*s_ + yuk*c
    dik = yuk - TILT_DEG - own_pitch_deg
    return (CX + F_PX*math.tan(math.radians(yat)),
            CY - F_PX*math.tan(math.radians(dik)))


def beklenen_kadraj(menzil_m, yukselis_deg, azimut_deg, own_pitch_deg, own_roll_deg=0.0):
    """TERS yön (yalnız DOĞRULAMA/ölçüm için; güdümde KULLANILMAZ çünkü
    hedefin GPS'ini gerektirir). (cx, cy, beklenen_kutu_px) veya None.

    ⛔ ARKA YARIKÜRE KAPISI — 2026-08-27, YAŞANMIŞ ANALİZ HATASI.

    `tan()` 90°'de kutuptan geçer ve ötesinde İŞARET DEĞİŞTİREREK küçülür:
        tan(170°) = -0.176  ->  cx = 960 - 0.176*F  = kadrajın İÇİNDE
    Yani TAM ARKAMIZDAKİ hedef, "kadrajın ortasında" gibi görünür. Bu
    izdüşüm ölçüm-only olduğu için güdümü hiç etkilemedi, ama KAYIP
    SINIFLANDIRMASINI kirletti: hedefin üstünden geçtikten sonraki
    kareler "kadraj içinde ama dedektör kör" (B kovası) sayıldı.

    ÖLÇÜLDÜ: KM2 kademeli__t2, kare 21 — t=10.7 s, gerçek menzil 6.58 m,
    izdüşüm (1338, 477) diyordu; KAREYE BAKINCA hedef YOK, çünkü hedef
    arkada kalmıştı. Bu tek kare, üstüne aday tasarladığım "B kovası
    59 kare" sayısının şişkin olduğunu gösterdi.

    KAPI: |yat| veya |dik| 85°'yi geçerse hedef görüntü düzleminin
    ARKASINDADIR; izdüşüm ANLAMSIZDIR ve None döner. 85° seçildi çünkü
    kameranın yatay yarı-görüş açısı ~60°; 85 ile 90 arasında zaten
    kadraj dışıdır ama tan() henüz patlamamıştır."""
    dik = yukselis_deg - TILT_DEG - own_pitch_deg
    yat = azimut_deg
    if own_roll_deg:
        r = math.radians(-own_roll_deg); c,s = math.cos(r), math.sin(r)
        yat, dik = yat*c - dik*s, yat*s + dik*c
    if abs(yat) >= 85.0 or abs(dik) >= 85.0:
        return None                      # hedef ARKADA — izdüşüm anlamsız
    return (CX + F_PX*math.tan(math.radians(yat)),
            CY - F_PX*math.tan(math.radians(dik)),
            MENZIL_C/max(menzil_m, 1e-6))
