# -*- coding: utf-8 -*-
"""
================================================================================
KİLİTLENME MUHASEBESİ — Teknofest şartnamesi 6.1.4
================================================================================
Bu modül TEK BİR SORUYU cevaplar: "şu an kilitli miyiz ve son 10 saniyenin
kaçında kilitliydik?"

⛔ YARIŞMA KURALI (CLAUDE.md §10) — YAPISAL GARANTİ
   Girdisi YALNIZ: kutu pikselleri (cx, cy, w, h) + zaman. Hedefin GPS'i,
   menzili, hızı FONKSİYON İMZASINDA YOKTUR. Bekçi B63 bunu sınar.

────────────────────────────────────────────────────────────────────────────
TERİMLER (CLAUDE.md §0.2 — hiçbiri tanımsız bırakılmaz)
────────────────────────────────────────────────────────────────────────────
  AK — Kamera Görüş Alanı : gördüğümüz tam kadraj. Bizde 1920x1080 piksel.
  AV — Hedef Vuruş Alanı  : kadrajın ORTASINDAKİ dikdörtgen. Şartname
       kenarları kırpar: SOLDAN ve SAĞDAN %25, ÜSTTEN ve ALTTAN %10.
       Bizde -> x ∈ [480, 1440],  y ∈ [108, 972].
       NEDEN kenarlar sayılmıyor: kadrajın kenarında duran bir hedefe
       "kilitlendim" demek, aslında ona NİŞAN ALMAMIŞ olmaktır; kamera onu
       sadece görüş açısının ucunda yakalamıştır.
  AH — Kilitlenme Dörtgeni: hedefin etrafına BİZİM çizdiğimiz kırmızı kutu.
       Bizde bu, dedektörün ürettiği bbox'un TA KENDİSİDİR. Şartname
       "AH merkezi ile hedef merkezi arası, yatayda hedef genişliğinin /
       dikeyde hedef yüksekliğinin YARISINDAN fazla olamaz" diyor; ikisi
       aynı kutu olduğu için bu şart bizde YAPISAL olarak 0 farkla sağlanır.
  HH — Hedef Hava Aracı   : rakip İHA.

BİR KARENİN "KİLİTLİ" SAYILMA ŞARTLARI (üçü birden):
  1. O karede GERÇEK bir tespit var.
     ⚠ ÖNEMLİ: köprü/öngörü kutuları (kendi ölü-hesabımızla ileri taşınan
       kutular) KİLİT SAYILMAZ. Onlar bizim tahminimizdir, kameranın
       ölçümü değil; sunucuya öyle paket göndermek şartnamenin "hatalı
       kilitlenme paketi" tanımına girer ve EKSİ PUANDIR.
  2. Hedefin merkezi AV dikdörtgeninin içinde.
  3. Hedef, ekranın yatay VEYA dikey ekseninin en az %P'sini kaplıyor.
     Şartname sınırı %5; ama kendisi şunu yazıyor: "paket gönderme
     limitinin %6 veya daha üstü olması tavsiye edilir" — çünkü %4.5'lik
     bir objeyi %5 sanıp paket göndermek HATALI KİLİTLENME sayılıyor.
     Bu yüzden varsayılanımız %6 (Ayar.KILIT_BOYUT_YUZDE).

ZAMAN İSTERİ:
  10 saniyelik KAYAN pencere içinde kilitli geçen sürelerin TOPLAMI
  >= 5 saniye. Kesintisiz olmak zorunda DEĞİL ("kilitlenme süresi, pencere
  içerisinde kesik kesik gerçekleşebilir ve birden fazla kısa kilitlenme
  aralığının toplamı olarak hesaplanabilir").

SÜRE NASIL SAYILIR (§5.3 örnekleme kuralı):
  Muhasebe ÇIKARIM BAŞINA işler (~9-10 Hz, yani 100-110 ms çözünürlük).
  Ölçtüğümüz büyüklük 5 saniyelik bir toplam; 100 ms çözünürlük bunun
  50 katı — kural fazlasıyla sağlanıyor.
  Her çıkarım, KENDİSİNDEN ÖNCEKİ boşluğu temsil eder:
      dt = min(DT_MAX, t - t_önceki_çıkarım)
  ve bu süre YALNIZ o çıkarım kilitliyse hesaba eklenir.
  DT_MAX (varsayılan 0.20 s) şartnamenin kendi toleransından geliyor:
  "5 saniyelik bir kilitlenme için %5'lik yani 200 ms'ye kadar tolerans
  mevcuttur". Yani bir çıkarım gecikirse en fazla 200 ms kredi alır;
  saniyelerce süren bir tespit boşluğu kilit süresi olarak SAYILAMAZ.
================================================================================
"""
from collections import deque


class KilitDurumu:
    """Kayan pencerede kümülatif kilit süresi. Girdi YALNIZ piksel + zaman."""

    def __init__(self, cfg=None):
        from dow.ayarlar import Ayar
        self.cfg = cfg or Ayar
        self.sifirla()

    def sifirla(self):
        self._ornek = deque()      # (t, dt, kilitli)
        self._t_onceki = None
        self.kumulatif_s = 0.0
        self.en_iyi_s = 0.0        # koşu boyunca görülen en yüksek kümülatif
        self.saglandi = False      # MANDALLI: bir kez sağlandıysa geri dönmez
        self.saglandi_t = None
        self.kilit_bu = False
        self.sebep = "baslangic"
        self.n_kilitli = 0
        self.n_ornek = 0

    # ---------------- şartname ölçütü — TEK KARE ----------------
    def kare_kilitli(self, kutu):
        """Şartname 6.1.4: bu kare kilitli mi. Döner (kilit, sebep).

        `kutu` = (cx, cy, w, h, conf) ya da None. YALNIZ PİKSEL."""
        if kutu is None:
            return False, "tespit_yok"
        cx, cy, w, h = kutu[0], kutu[1], kutu[2], kutu[3]
        c = self.cfg
        from dow.gorus import kamera as KAM
        x0 = c.KILIT_KIRP_X * KAM.IMG_W
        x1 = (1.0 - c.KILIT_KIRP_X) * KAM.IMG_W
        y0 = c.KILIT_KIRP_Y * KAM.IMG_H
        y1 = (1.0 - c.KILIT_KIRP_Y) * KAM.IMG_H
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            return False, "AV_disi"
        p = c.KILIT_BOYUT_YUZDE / 100.0
        # "yatay ve dikey eksenlerinden EN AZ BİRİNDE" -> VEYA
        if not (w >= p * KAM.IMG_W or h >= p * KAM.IMG_H):
            return False, "kucuk"
        return True, ""

    # ---------------- kayan pencere ----------------
    def guncelle(self, t, kutu):
        """Bir ÇIKARIM işle. `kutu` None ise o çıkarım kilitsizdir.

        Döner: tanı sözlüğü (ölçüm + §5.1 mekanizma sütunları)."""
        c = self.cfg
        kilit, sebep = self.kare_kilitli(kutu)
        dt = 0.0 if self._t_onceki is None else min(
            c.KILIT_DT_MAX_S, max(0.0, t - self._t_onceki))
        self._t_onceki = t
        self._ornek.append((t, dt, kilit))
        self.n_ornek += 1
        if kilit:
            self.kumulatif_s += dt
            self.n_kilitli += 1
        # pencereden düşenleri at
        while self._ornek and (t - self._ornek[0][0]) > c.KILIT_PENCERE_S:
            _t, _dt, _k = self._ornek.popleft()
            if _k:
                self.kumulatif_s -= _dt
        self.kumulatif_s = max(0.0, self.kumulatif_s)
        if self.kumulatif_s > self.en_iyi_s:
            self.en_iyi_s = self.kumulatif_s
        self.kilit_bu = kilit
        self.sebep = sebep
        if not self.saglandi and self.kumulatif_s >= c.KILIT_GEREKLI_S:
            self.saglandi = True
            self.saglandi_t = t
        return {"kilit_bu": int(kilit),
                "kilit_s": round(self.kumulatif_s, 2),
                "kilit_en_iyi_s": round(self.en_iyi_s, 2),
                "kilit_sebep": sebep,
                "kilit_saglandi": int(self.saglandi)}


class HizRegulatoru:
    """KİLİT fazının hız regülatörü — girdi YALNIZ piksel hatası + zaman.

    ⛔ NİYE AYRI BİR SINIF: `ibvs.komut()` durumsuzdur (integrali çağıran
       taşır). Değişim hızı tavanı (slew) için BİR ÖNCEKİ komutu da tutmak
       gerekiyor; iki durumu çağrı imzasına eklemek yerine burada, tek
       yerde tutuluyor. Nesne her Beyin'e ait ve faz geçişinde sıfırlanır.

    ⛔ YARIŞMA KURALI (§10): metotların imzasında hedefin konumu/menzili
       YOKTUR — yalnız `hata_px` (piksel) ve `dt` (saniye). Bekçi B69 sınar.

    YASA (§0.2 — terimler):
      v_ham = K_FWD · hata_px + I          PI: P anlık hatayla, I birikmiş
                                           hatayla orantılı çıktı verir.
      v     = kırp(v_ham, V_MIN, V_MAX)    doyum (clamp)
      |Δv/Δt| <= SLEW                      değişim hızı tavanı (rate limit)

    ANTI-WINDUP (koşullu integrasyon): çıkış doyumdayken ve hata doyumu
    DERİNLEŞTİRİYORKEN integral güncellenmez. Yoksa integral doyum boyunca
    şişer ("windup") ve hata işaret değiştirdiğinde boşalması saniyeler
    sürer — araç geç tepki verir, aşar, salınır.
    """

    def __init__(self, cfg=None):
        from dow.ayarlar import Ayar
        self.cfg = cfg or Ayar
        self.sifirla()

    def sifirla(self, v0=None):
        self.I = 0.0
        # İlk komut sıçramasın diye slew başlangıcı: verilmezse V_MIN.
        self.son_v = self.cfg.KILIT_V_MIN if v0 is None else float(v0)
        self.doyum = 0            # §5.1 mekanizma: kaç tik doyumda
        self.slew_kesti = 0       # §5.1 mekanizma: kaç tik slew devrede

    def hiz(self, hata_px, dt):
        c = self.cfg
        # ⛔ KAZANÇ ÇİZELGELEMESİ DENENDİ VE ELENDİ — 2026-08-28 (§5.12 ile
        #   koddan tamamen çıkarıldı). Kampanya CZ24, 24 uçuş, n=6/kol/senaryo:
        #     kademeli  KİLİT 6/6 -> 0/6 · isabet 4/6 -> 0/6 · en yakın 0.90 -> 6.52 m
        #     duz       6/6 = 6/6 (fark yok; orada hata zaten <50 px)
        #   KÖK NEDEN (ölçüldü): "sarsıntısız geçiş" düzeltmesi
        #   `I += (K_eski-K_yeni)*hata`, kazanç UZAKTA yükselirken hata
        #   büyük olduğu için integrali ADIM ADIM AŞAĞI itiyordu:
        #     kilit_I  8-12 m: +8.3 · 12-18 m: -1.7 · >18 m: -11.0
        #   Yani çizelgenin eklemesi gereken yetkiyi düzeltmenin kendisi
        #   iptal edip TERSİNE çeviriyordu; araç 11.9 m'de asılı kaldı,
        #   kapanma her bantta +0.00 m/s.
        #   Zaten GEREKSİZDİ: köşegen ölçüsü (995d8df) `kademeli`de kilit
        #   bandı oranını %33'ten %46'ya çıkarıp KİLİT'i 6/6 yapmıştı.
        ham = c.KILIT_K_FWD * hata_px + self.I
        v = ham
        if v < c.KILIT_V_MIN:
            v = c.KILIT_V_MIN
        elif v > c.KILIT_V_MAX:
            v = c.KILIT_V_MAX
        doymus = (ham != v)
        if doymus:
            self.doyum += 1
        # koşullu integrasyon
        derinlestiriyor = doymus and ((hata_px > 0) == (ham > c.KILIT_V_MAX))
        if not derinlestiriyor:
            self.I = max(-c.KILIT_I_MAX,
                         min(c.KILIT_I_MAX, self.I + 0.04 * hata_px * dt))
        # değişim hızı tavanı
        if c.KILIT_SLEW > 0.0:
            tav = c.KILIT_SLEW * dt
            dv = v - self.son_v
            if dv > tav:
                v = self.son_v + tav; self.slew_kesti += 1
            elif dv < -tav:
                v = self.son_v - tav; self.slew_kesti += 1
        self.son_v = v
        return v
