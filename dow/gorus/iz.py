# -*- coding: utf-8 -*-
"""
================================================================================
TEK HEDEFLİ İZ — bir takipçinin BİZE YARAYAN yarısı
================================================================================
NEDEN HYBRIDSORT DEĞİL: bir takipçinin beş işlevi vardır —
  1) veri ilişkilendirme   2) durum kestirimi (öngör + güncelle)
  3) iz yaşam döngüsü      4) kimlik koruma / yeniden tanıma
  5) HybridSORT'un kendi katkısı (görünüm gömmesi, zayıf ipuçları)
Bizim sahnede TEK hedef var ve örtüşme yok: (4) ve (5) tamamen karşılıksız.
HybridSORT ayrıca 2026-08-22'de kaldırılmıştı çünkü dedektörün YANLIŞ
POZİTİFİNİ de iz olarak benimseyip 20 kare ileri taşıyordu. Bu dosya
yalnız (1)(2)(3)'ü, tek hedef için, ölçülmüş eşiklerle kurar.

⭐ TASARIMIN TAMAMI ÖLÇÜMDEN ÇIKTI (2026-08-24, 36 koşu, hedefin kadrajdaki
   GERÇEK konumu üzerinden — dedektörden bağımsız):

A) KONUM İLERİ TAŞINMAZ, DONDURULUR.
   Kutu kaybolunca hedefin gerçek yerini kestirmede hata medyanı:
       ufuk    dondur   sabit hızla ileri taşı
       0.5 s     29 px        35 px
       1.0 s     50 px        86 px
       1.5 s     79 px       157 px      <- ileri taşıma İKİ KAT kötü
   Sebep: kadrajdaki konum hem hedefin dönüşleriyle hem BİZİM manevramızla
   belirleniyor ve YÖN DEĞİŞTİRİYOR. Sabit hız varsayımı yanlış tarafa
   götürüyor. Bu yüzden konum, `ana.py`nin köprüsüyle (yalnız kendi
   dönüşümüzün telafisi) DONDURULMUŞ kalır.

B) BOYUT İLERİ TAŞINIR — ve `1/w` üzerinden.
   w = MENZIL_C / menzil olduğu için, menzil düzgün azalırken `w` HİPERBOLİK
   büyür ama `1/w` DOĞRUSAL değişir. Ölçüldü (boyut hatası medyanı):
       ufuk    dondur   w doğrusal   1/w doğrusal
       0.5 s     25 px      14 px         9 px    <- en iyi
       1.0 s     62 px      39 px        29 px
       1.5 s    112 px      83 px        82 px
   Kullanılan: sabit kazançlı alfa-beta süzgeci (Kalman'ın sabit kazançlı
   hâli) — kovaryans hesabına gerek yok, çünkü kapı eşikleri aşağıda
   ÖLÇÜLMÜŞ yüzdeliklerden geliyor, filtre belirsizliğinden değil.

C) BUGÜNKÜ SABİT KAPI GERÇEK HEDEFİ REDDEDİYOR — kanıt:
   gerçek_w / donmuş_w oranının yüzdelikleri:
       ufuk      p05   medyan    p90    p95
       0.5 s    1.00     1.24   1.50   1.66
       1.0 s    1.00     1.55   2.12   2.47   <- 2.0 kapısı p90'ı KESİYOR
       1.5 s    0.92     1.99   2.94   3.31   <- p50 bile sınırda
   Öngörüyle (1/w, 3 kat kırpmalı) aynı oran:
       0.5 s    0.48     1.00   1.13   1.17
       1.0 s    0.34     1.21   1.46   1.53
       1.5 s    0.34     1.58   2.15   2.31

D) KONUM TOLERANSI: dondurulmuş referansın gerçek sapması p90 =
   85 px @0.5 s, 169 @1.0 s, 239 @1.5 s -> ≈ 165 px/saniye (doğrusal, temiz).

⭐ YAPISAL GÜVENCE: aşağıdaki eşikler, HER yaşta bugünkü sabit kapıdan
   (konum 60+2w, boyut 0.5-2.0) DAHA GENİŞTİR. Yani yeni kapı, eskisinin
   kabul ettiği hiçbir adayı reddedemez — "kapı elemesi" kaynaklı bayatlık
   (ölçüldü: bayat karelerin %24.5'i) yalnız AZALABİLİR. Bekçi: B37.
   Bedeli yanlış-pozitif riskidir; ölçütü `yanlis%` (§5.2).

⛔ ÇÖZMEDİĞİ ŞEY: bayat karelerin %67.6'sı "model hiç kutu bulamadı"dır.
   İz kutu İCAT EDEMEZ. Bu dosya yalnız %24.5'lik dilimi hedefler.
================================================================================
"""
import os


def _f(k, v): return float(os.environ.get(k, v))
def _b(k, v): return os.environ.get(k, str(int(v))).strip() not in ("0","","false","False")


class IzCfg:
    """Canlı ayarlar — SINIF nitelikleri (panel uçuş sırasında değiştirebilir)."""
    AKTIF        = _b("DOW_IZ", False)      # kill-switch
    # --- boyut öngörüsü ---
    HIZ_ALFA     = _f("DOW_IZ_ALFA", 0.35)  # 1/w hızının yumuşatma kazancı
    ONGORU_UFUK_S= _f("DOW_IZ_UFUK", 0.7)   # bu süreden sonrasına öngörü YOK
                                            # (ölçüldü: 1.5 s'de öngörü zaten
                                            #  dondurmayla eşitleniyor)
    ONGORU_KAT   = _f("DOW_IZ_KAT", 3.0)    # öngörü en çok bu kat büyütür/küçültür
    DT_MIN       = 0.02                     # hız kestirimi için geçerli aralık
    DT_MAX       = 0.60
    # --- kapı eşikleri (hepsi ÖLÇÜLDÜ, bkz. başlık C ve D) ---
    KONUM_HIZ_PX = _f("DOW_IZ_KONUM_HIZ", 165.0)  # px/s, p90 sapmadan
    BOYUT_ALT    = _f("DOW_IZ_BOYUT_ALT", 0.35)   # p05 = 0.34
    BOYUT_TABAN  = _f("DOW_IZ_BOYUT_TABAN", 2.0)  # bugünküyle aynı taban
    BOYUT_HIZ    = _f("DOW_IZ_BOYUT_HIZ", 1.0)    # üst sınır /saniye büyür
    # --- yaşam döngüsü ---
    OMUR_S       = _f("DOW_IZ_OMUR", 1.0)   # referans bu kadar bayatlarsa BIRAK
                                            # (sayı tabanlı YEREL_KURTAR yerine)


class Iz:
    """Tek hedefin izi. Konum DONDURULUR, boyut 1/w üzerinden ÖNGÖRÜLÜR."""

    def __init__(self):
        self.sifirla()

    def sifirla(self):
        self.var = False
        self.cx = self.cy = self.w = 0.0
        self.s = 0.0          # s = 1/w, menzille orantılı
        self.s_hiz = 0.0      # ds/dt
        self.t = 0.0
        self.olcum = 0

    def guncelle(self, kutu, t):
        """Kabul edilmiş bir kutuyla izi tazele. kutu = (cx, cy, w, h, conf)."""
        cx, cy, w = float(kutu[0]), float(kutu[1]), max(float(kutu[2]), 1.0)
        s = 1.0 / w
        if self.var:
            dt = t - self.t
            if IzCfg.DT_MIN <= dt <= IzCfg.DT_MAX:
                ham = (s - self.s) / dt
                a = IzCfg.HIZ_ALFA
                self.s_hiz = (1.0 - a) * self.s_hiz + a * ham
        self.cx, self.cy, self.w, self.s = cx, cy, w, s
        self.t = t
        self.var = True
        self.olcum += 1

    def yas(self, t):
        return max(0.0, t - self.t) if self.var else -1.0

    def ongor(self, t):
        """(cx, cy, w_ongoru, yas) ya da None.
        KONUM dondurulmuş döner (ölçüldü: ileri taşımak zararlı);
        BOYUT 1/w doğrusal öngörüsüyle döner, kırpmalı."""
        if not self.var:
            return None
        yas = max(0.0, t - self.t)
        d = min(yas, IzCfg.ONGORU_UFUK_S)
        s = self.s + self.s_hiz * d
        # ⛔ KIRPMA ŞART: 1/w sıfıra yaklaşırsa w patlar. Ölçümde kırpmasız
        #   p95 999748'e çıkıyordu (bölme uçması).
        kat = max(1.0, IzCfg.ONGORU_KAT)
        s = min(max(s, self.s / kat), self.s * kat)
        return self.cx, self.cy, 1.0 / max(s, 1e-9), yas

    def kapi(self, t, rw=None):
        """(yaricap_px, boyut_alt, boyut_ust) — yaşla GENİŞLEYEN kapı.
        Her yaşta bugünkü sabit kapıdan (60+2w, 0.5-2.0) daha geniştir."""
        y = self.yas(t)
        if y < 0: y = 0.0
        w = rw if rw else self.w
        yaricap = 60.0 + 2.0 * w + IzCfg.KONUM_HIZ_PX * y
        ust = max(IzCfg.BOYUT_TABAN, IzCfg.BOYUT_TABAN + IzCfg.BOYUT_HIZ * y)
        return yaricap, min(IzCfg.BOYUT_ALT, 0.5), ust
