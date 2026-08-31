# -*- coding: utf-8 -*-
"""
================================================================================
UÇUŞ KAYDI — panelin gördüğü her şeyi diske yaz
================================================================================
NİYE: ilk otonom denemeden sonra "ne oldu" sorusunu cevaplayacak veri
YOKTU. Panelde akan her şey ekranda kalıyor, uçuş bitince buharlaşıyordu.
Bugün üç ayrı teşhis turu (imgsz, kanal sırası, menzil kapısı) canlı
gözlemle yapıldı; kayıt olsaydı hepsi tek dosyadan çıkardı.

⛔ SÜTUNLAR AÇIKÇA SAYILIR, sözlük otomatik düzleştirilmez.
   Otomatik düzleştirme, bir alan eklenince sütun sırasını kaydırır ve
   ESKİ KAYITLARLA KIYAS BOZULUR. Yeni alan LİSTENİN SONUNA eklenir.

⛔ YAZMA GÜDÜM DÖNGÜSÜNÜ BEKLETMEZ: satırlar kuyruğa atılır, ayrı bir
   iplik diske yazar. Disk yavaşlarsa uçuş değil kayıt aksar.

⛔ `logs/` ALTINA yazılır — `/tmp` gecelik temizleniyor (CLAUDE.md §5.7).

KULLANIM
    k = Kayitci()           # logs/ucus_YYYYMMDD_HHMMSS.csv
    k.basla()
    k.yaz(durum_sozlugu)    # her tik; hız sınırı içeride
    k.dur()

OKUMA
    python3 -c "import pandas as pd; d=pd.read_csv('logs/ucus_....csv'); print(d.describe())"
================================================================================
"""
import os
import queue
import threading
import time

# ⭐ SÜTUNLAR — (csv_adi, sozlukten_alma_yolu)
#   Yol: "a.b" -> d["a"]["b"].  Yok/None ise boş yazılır.
#   ⛔ YENİ ALAN SONA EKLENİR, araya sokulmaz.
SUTUNLAR = [
    ("t",              "t"),
    # --- hakem: komut kimden ---
    ("kaynak",         "komut.kaynak"),
    ("sebep",          "komut.sebep"),
    ("kip",            "komut.kip"),
    ("arm",            "komut.arm"),
    ("insan",          "komut.insan"),
    # --- güdüm ---
    ("gudum_durum",    "gudum.durum"),
    ("gudum_faz",      "gudum.faz"),
    # --- kendi konumumuz ---
    ("kuzey",          "konum.kuzey"),
    ("dogu",           "konum.dogu"),
    ("yukari",         "konum.yukari"),
    ("hiz_yatay",      "hiz.yatay"),
    ("hiz_dikey",      "hiz.dikey"),
    ("roll",           "durus.roll"),
    ("pitch",          "durus.pitch"),
    ("yaw",            "durus.yaw"),
    # --- araç sağlığı ---
    ("canli",          "arac.canli"),
    ("uydu",           "arac.uydu"),
    ("pil_v",          "arac.pil_v"),
    ("pil_yuzde",      "arac.pil_yuzde"),
    ("pil_akim",       "arac.pil_akim"),
    ("link_lq",        "arac.link_lq"),
    ("link_rssi",      "arac.link_rssi"),
    ("crc_hata",       "arac.crc_hata"),
    ("yas_gps",        "arac.yas_gps"),
    # --- hedef (GPS) ---
    ("hedef_var",      "hedef.var"),
    ("hedef_yas",      "hedef.yas"),
    ("hedef_yas_veri", "hedef.yas_veri"),
    ("hedef_enlem",    "hedef.ham_enlem"),
    ("hedef_boylam",   "hedef.ham_boylam"),
    ("hedef_kuzey",    "hedef_ham_konum.kuzey"),
    ("hedef_dogu",     "hedef_ham_konum.dogu"),
    ("hedef_uzaklik",  "hedef_ham_konum.uzaklik"),
    # --- görüş: KABUL EDİLEN kutu ---
    ("kutu_cx",        "kutu.0"),
    ("kutu_cy",        "kutu.1"),
    ("kutu_w",         "kutu.2"),
    ("kutu_h",         "kutu.3"),
    ("kilit_s",        "kilit.kilit_s"),
    ("kilit_sebep",    "kilit.sebep"),
    # --- görüş: REDDEDİLEN kutu ve SEBEBİ (§5.1 mekanizma sütunu) ---
    ("ham_cx",         "ham_kutu.0"),
    ("ham_cy",         "ham_kutu.1"),
    ("ham_w",          "ham_kutu.2"),
    ("ham_h",          "ham_kutu.3"),
    ("ham_conf",       "ham_kutu.4"),
    ("ham_sebep",      "ham_sebep"),
    # --- dikey döngü ---
    ("dik_aktif",      "dikey.aktif"),
    ("dik_pasif",      "dikey.pasif"),
    # --- kamera ---
    ("kam_sayac",      "kamera.sayac"),
    ("kam_yas",        "kamera.yas"),
    # --- ⭐ ARACA GİDEN ÇUBUKLAR (30 Ağu 2026 eklendi, SONA) ---
    #   ⛔ Bunlar olmadan kayıt "araç ne yaptı" sorusunu CEVAPLAYAMAZ:
    #   konum ve duruş sonucu gösterir, sebebi göstermez.
    ("cubuk_thr",      "komut.komut.0"),
    ("cubuk_pitch",    "komut.komut.1"),
    ("cubuk_roll",     "komut.komut.2"),
    ("cubuk_yaw",      "komut.komut.3"),
    ("mercek",         "optik.mercek"),
    # --- RTL (30 Ağu 2026, SONA) ---
    ("rtl_aktif",      "rtl.aktif"),
    ("rtl_asama",      "rtl.asama"),
    ("rtl_mesafe",     "rtl.mesafe"),
]


def _cek(d, yol):
    """`"a.b.0"` yolunu sözlükten/listeden çek. Yoksa None."""
    x = d
    for p in yol.split("."):
        if x is None:
            return None
        if isinstance(x, (list, tuple)):
            try:
                x = x[int(p)]
            except (ValueError, IndexError):
                return None
        elif isinstance(x, dict):
            x = x.get(p)
        else:
            return None
    return x


class Kayitci:
    """Uçuş kaydı. İş parçacığı güvenli, güdüm döngüsünü BEKLETMEZ."""

    def __init__(self, dizin=None, hz=10.0, kuyruk_max=2000, uretici=None):
        # ⛔ ÜRETİCİ (pull) — İTME (push) DEĞİL.
        #   Eskiden satırlar `_durum()` içinden İTİLİYORDU; o da yalnız bir
        #   TARAYICI sorduğunda çalışıyor. Tarayıcı kapalıyken uçuş HİÇ
        #   kaydedilmiyordu — kaydın var olmasının tek sebebi ortadan
        #   kalkıyordu. Artık kayıt KENDİ ipliğinde, kendi hızında, durumu
        #   kendisi ÇEKİYOR. Panel açık olsun olmasın kayıt akar.
        self.uretici = uretici
        kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.dizin = dizin or os.path.join(kok, "logs")
        self.hz = max(0.5, float(hz))
        self._min_aralik = 1.0 / self.hz
        self._kuyruk = queue.Queue(maxsize=kuyruk_max)
        self._is = None
        self._calisiyor = False
        self._son_t = 0.0
        self.yol = None
        self.n_satir = 0
        self.n_dusen = 0          # kuyruk dolduğu için ATILAN satır
        self.hata = None

    # ---------------------------------------------------------------- açılış
    def basla(self):
        try:
            os.makedirs(self.dizin, exist_ok=True)
            ad = "ucus_%s.csv" % time.strftime("%Y%m%d_%H%M%S")
            self.yol = os.path.join(self.dizin, ad)
            self._d = open(self.yol, "w", encoding="utf-8", newline="")
            self._d.write(",".join(a for a, _ in SUTUNLAR) + "\n")
            self._d.flush()
        except OSError as e:
            self.hata = "%s: %s" % (type(e).__name__, e)
            return False
        self._calisiyor = True
        self._is = threading.Thread(target=self._dongu, daemon=True,
                                    name="ucus-kaydi")
        self._is.start()
        if self.uretici is not None:
            self._cekici = threading.Thread(target=self._cekme_dongusu,
                                            daemon=True, name="ucus-kaydi-cek")
            self._cekici.start()
        return True

    def _cekme_dongusu(self):
        """Durumu KENDİ hızında çek. Tarayıcıdan bağımsız."""
        while self._calisiyor:
            t0 = time.monotonic()
            try:
                d = self.uretici()
                if d:
                    self.yaz(d)
            except Exception as e:          # üretici patlarsa kayıt ölmesin
                self.hata = "üretici: %s" % e
            uyku = self._min_aralik - (time.monotonic() - t0)
            time.sleep(uyku if uyku > 0 else 0.0)

    # ---------------------------------------------------------------- yazma
    def yaz(self, durum):
        """Bir durum sözlüğünü kuyruğa at. Hız sınırı burada uygulanır.

        ⛔ ASLA BLOKLAMAZ: kuyruk doluysa satır DÜŞÜRÜLÜR ve sayılır.
          Diskin yavaşlaması uçuşu geciktiremez.
        """
        if not self._calisiyor:
            return False
        simdi = time.monotonic()
        if simdi - self._son_t < self._min_aralik:
            return False
        self._son_t = simdi
        try:
            self._kuyruk.put_nowait(durum)
            return True
        except queue.Full:
            self.n_dusen += 1
            return False

    def _dongu(self):
        while self._calisiyor or not self._kuyruk.empty():
            try:
                d = self._kuyruk.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._d.write(",".join(self._alan(d, y) for _, y in SUTUNLAR))
                self._d.write("\n")
                self.n_satir += 1
                if self.n_satir % 50 == 0:
                    self._d.flush()     # çökme hâlinde en fazla 5 s kaybolur
            except (OSError, ValueError) as e:
                self.hata = "%s: %s" % (type(e).__name__, e)

    @staticmethod
    def _alan(d, yol):
        v = _cek(d, yol)
        if v is None:
            return ""
        if isinstance(v, bool):
            return "1" if v else "0"
        if isinstance(v, float):
            # ⛔ %.4f GPS'İ BOZAR: enlem 41.0033654 -> 41.0034, yani ~11 m
            #   çözünürlük. Kayıt, kaydettiği şeyden daha kaba olamaz.
            #   %.12g: 12 anlamlı hane -> enlemde ~1 cm, küçük sayılarda
            #   gereksiz sıfır yok (0.07 -> "0.07"). 12 hane ŞART: unix zaman
            #   damgası 1788080812.27 -> 10 hanede ".27" KAYBOLUYORDU.
            return "%.12g" % v
        s = str(v)
        # CSV'yi bozmasın: virgül ve tırnak temizlenir (alanlar kısa metin)
        return s.replace(",", ";").replace('"', "'").replace("\n", " ")

    # ---------------------------------------------------------------- kapanış
    def dur(self):
        """⛔ İKİNCİ Ctrl+C'DE ASILMAMALI (30 Ağu 2026'da yaşandı).

        `join()` sırasında yeni bir KeyboardInterrupt gelirse traceback
        basıp kapanışın GERİ KALANINI atlıyordu — araç komutları
        temizlenmeden çıkılıyordu. Kapanış yolu KESİNTİYE UĞRAMAMALI.
        """
        self._calisiyor = False
        if self._is:
            try:
                self._is.join(timeout=3.0)
            except KeyboardInterrupt:
                pass
        try:
            if getattr(self, "_d", None):
                self._d.flush()
                self._d.close()
        except (OSError, KeyboardInterrupt):
            pass

    def durum(self):
        return {"aciks": bool(self._calisiyor), "yol": self.yol,
                "satir": self.n_satir, "dusen": self.n_dusen,
                "hata": self.hata,
                "mb": round(os.path.getsize(self.yol) / 1e6, 2)
                if (self.yol and os.path.exists(self.yol)) else 0.0}
