# -*- coding: utf-8 -*-
"""
================================================================================
ELRS SERİ BAĞI — CRSF çerçevelerini yazan/okuyan tek nokta
================================================================================
Fiziksel yol iki türlü olabilir ve BU DOSYA İKİSİNDE DE AYNIDIR:

  YOL A  PC --seri--> [kumandanın eğitmen girişi] --> [modül] ))) --> drone
  YOL B  PC --seri--> [Ranger Micro doğrudan]           ))) --> drone

Değişen tek şey portun fiziksel ucu. Kod, protokol ve emniyet aynı.

⚠ BAUD: CRSF standardı 420000'dir; ELRS modülleri 400000'i de kabul eder.
  ⛔ USB-seri yongası önemli: CP2102 ve FT232 keyfî baud üretebilir,
     CH340 ise standart olmayan baud'larda SORUN ÇIKARIR. Bağ kurulamazsa
     ilk bakılacak yer budur (`araclar/link_testi.py` ikisini de dener).

⚠ TEK YAZICI KURALI: seri portu TEK bir süreç açar. Panel ve komut süreci
  aynı portu açmaya çalışırsa ikisi de bozuk çalışır — `talon_arayuz`
  belgesindeki "portu tek süreç açabilir" tuzağının aynısı.
================================================================================
"""
import threading
import time

from . import crsf


class ElrsBag:
    """CRSF seri bağı. Donanım yoksa `sahte_port` ile tezgâhta koşar."""

    def __init__(self, port=None, baud=420000, sahte_port=None, zaman_asimi=0.0):
        self.port_adi = port
        self.baud = baud
        self._sp = sahte_port          # test/tezgâh için: write()/read() olan nesne
        self._ser = None
        self._kilit = threading.Lock()
        self.cozucu = crsf.Cozucu()
        self.acik = False
        self.hata = None
        self.zaman_asimi = zaman_asimi
        # §5.1 mekanizma sütunları
        self.n_yazilan = 0
        self.n_okunan_bayt = 0
        self.n_yazma_hatasi = 0

    # ---------------- bağlantı ----------------
    def ac(self):
        if self._sp is not None:
            self.acik = True
            return True
        try:
            import serial
        except ImportError:
            self.hata = ("pyserial kurulu değil:  pip install pyserial")
            return False
        try:
            self._ser = serial.Serial(self.port_adi, self.baud,
                                      timeout=self.zaman_asimi,
                                      write_timeout=0.05)
            self.acik = True
            return True
        except Exception as e:
            self.hata = "%s: %s" % (type(e).__name__, e)
            return False

    def kapat(self):
        self.acik = False
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass

    # ---------------- yazma ----------------
    def yaz(self, cerceve):
        """Bir CRSF çerçevesi gönder. Başarılıysa True."""
        if not self.acik:
            return False
        try:
            with self._kilit:
                hedef = self._sp if self._sp is not None else self._ser
                hedef.write(cerceve)
            self.n_yazilan += 1
            return True
        except Exception as e:
            self.n_yazma_hatasi += 1
            self.hata = "yazma: %s" % e
            return False

    def rc_gonder(self, throttle, pitch, roll, yaw, arm, harita=None, aux=None):
        return self.yaz(crsf.rc_paketi(throttle, pitch, roll, yaw,
                                       arm=arm, harita=harita, aux=aux))

    # ---------------- okuma ----------------
    def oku(self, en_fazla=4096):
        """Gelen baytları çöz. Döner: {"gps": {...}, "durus": {...}, ...}

        ⛔ BLOKE ETMEZ: `timeout=0` ile açılır, eldeki ne varsa alınır.
           Kontrol döngüsünün içinde bloke bir okuma, döngüyü telemetri
           hızına düşürür — 50 Hz güdüm 5 Hz'e iner.
        """
        if not self.acik:
            return {}
        try:
            kaynak = self._sp if self._sp is not None else self._ser
            if hasattr(kaynak, "in_waiting"):
                n = min(kaynak.in_waiting, en_fazla)
                veri = kaynak.read(n) if n else b""
            else:
                veri = kaynak.read(en_fazla)
        except Exception as e:
            self.hata = "okuma: %s" % e
            return {}
        if not veri:
            return {}
        self.n_okunan_bayt += len(veri)
        return self.cozucu.coz(veri)
