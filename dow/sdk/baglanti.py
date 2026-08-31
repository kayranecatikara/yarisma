# -*- coding: utf-8 -*-
"""
================================================================================
DOW SDK SARMALAYICISI — birim ve eksen sınırı
================================================================================
Resmi `drone_sdk.py` DEĞİŞTİRİLMEDEN kullanılır; bu dosya onun üstüne
TEK BİR SORUMLULUK ekler: **birim ve eksen dönüşümü**.

NEDEN AYRI BİR KATMAN:
  SDK her şeyi santimetre (cm) ve DERECE verir; güdüm yasamız metre (m) ve
  RADYAN bekler. Bu dönüşümü güdümün içine serpiştirmek, Gazebo'da
  yaşadığımız "100 kat" hatalarının kaynağıdır. Burada TEK YERDE yapılır;
  bu dosyanın dışında hiçbir yerde /100 ya da radians() görülmemelidir.

⚠ YARIŞMA KURALI (CLAUDE.md §10): get_hedef_*() fonksiyonları GPS kaynaklıdır
  ve görsel temas VARKEN güdüme GİREMEZ. Bu dosya veriyi sunar, kuralı
  uygulamak üst katmanın (supervisor) işidir.
================================================================================
"""
import math
import time

from . import drone_sdk as _sdk

CM = 0.01          # cm -> m
MS = 0.01          # cm/s -> m/s


class DowBaglanti:
    """SDK'yı SI birimlerinde ve radyanda sunan ince sarmalayıcı."""

    def __init__(self, host="127.0.0.1", port=12345):
        self.host, self.port = host, port
        self.bagli = False
        self._son_komut = None

    # ---------------- bağlantı ----------------
    def baglan(self, deneme=5, bekle=1.0):
        for i in range(deneme):
            if _sdk.connect(self.host, self.port):
                self.bagli = True
                return True
            time.sleep(bekle)
        return False

    def canli(self):
        """Bağlantı GERÇEKTEN yaşıyor mu?

        ⛔ DERS (2026-08-21): SDK'nın alıcı iş parçacığı ölünce (oyun
        bağlantıyı kapatır, ör. drone despawn) get_* fonksiyonları SON
        BİLİNEN değeri sonsuza dek döndürmeye devam eder. Telemetri DONAR
        ama hata da vermez. Bir uçtan uca koşuda 40+ saniye donmuş veriyle
        uçmaya çalıştık ve fark etmedik. Ekran kapısı bunu göremez —
        soketin kendisine bakmak gerekir."""
        return _sdk.is_connected()

    def yeniden_bagla(self, deneme=6):
        try: _sdk.disconnect()
        except Exception: pass
        self.bagli = False
        return self.baglan(deneme=deneme)

    def kapat(self):
        # Aracı havada KONTROLSÜZ bırakma (CLAUDE.md §9): önce nötr + disarm.
        try:
            _sdk.set_control_surfaces(0.0, 0.0, 0.0, 0.0, False)
        except Exception:
            pass
        _sdk.disconnect()
        self.bagli = False

    # ---------------- komut ----------------
    def komut(self, throttle, pitch, roll, yaw, arm=True):
        """TEK TCP satırı. Ayrı set_* çağrıları YASAK — ara kareler tutarsız olur.
        Dördü de birimsiz çubuk konumu [-1, +1]."""
        t = max(-1.0, min(1.0, float(throttle)))
        p = max(-1.0, min(1.0, float(pitch)))
        r = max(-1.0, min(1.0, float(roll)))
        y = max(-1.0, min(1.0, float(yaw)))
        self._son_komut = (t, p, r, y, bool(arm))
        _sdk.set_control_surfaces(t, p, r, y, bool(arm))

    def notr(self, arm=True):
        self.komut(0.0, 0.0, 0.0, 0.0, arm)

    # ---------------- kendi telemetrimiz (TEMİZ) ----------------
    def konum(self):
        """(x, y, z) METRE, Unreal ekseni (Z YUKARI)."""
        x, y, z = _sdk.get_drone_location()
        return x * CM, y * CM, z * CM

    def yonelim(self):
        """(roll, pitch, yaw) RADYAN."""
        r, p, y = _sdk.get_drone_rotation()
        return math.radians(r), math.radians(p), math.radians(y)

    def hiz_vektoru(self):
        """(vx, vy, vz) m/s — Unreal ekseni. SDK'nın v[6..8] alanı."""
        vx, vy, vz = _sdk.get_telemetry()["drone"]["velocity"]
        return vx * MS, vy * MS, vz * MS

    def hiz(self):
        """Toplam hız m/s (skaler)."""
        return _sdk.get_drone_speed() * MS

    def irtifa(self):
        return _sdk.get_drone_altitude() * CM

    # ---------------- hedef (BOZUK GPS) ----------------
    def hedef_konum_bozuk(self):
        """(x, y, z) METRE — JAMMER'LI. Ham; filtreye girer.
        ⚠ get_target_speed() DAİMA 0 döner (234587 örnekte doğrulandı) —
          hedef hızı konumdan türetilmek zorunda."""
        x, y, z = _sdk.get_target_location()
        return x * CM, y * CM, z * CM

    def hedef_yonelim(self):
        """Hedefin (roll, pitch, yaw) DERECE. SDK indeksi 14-16.

        ⚠ NEDEN AYRI: `hedef_yon` diye kullandığımız büyüklük, hedefin
          KONUM FARKINDAN türetilmiş EMA'lı ROTA'dır — gerçek yönelim değil.
          Virajda EMA geride kalır ve istasyon noktası yanlış yere kurulur.
          Ayrıca hedefin YATIŞI (roll) ve PITCH'i orada hiç yoktur; oysa
          kadrajda gördüğümüz kutunun genişliği hedefin BAKIŞ AÇISINA bağlı.

        ⚠ BU KANAL BOZULMUŞ OLABİLİR. `telemetry["target"]` jammer'lı
          kanaldır; konum orada bozuluyor. Rotasyonun bozulup bozulmadığı
          ÖLÇÜLMEDİ -> şimdilik YALNIZ KAYIT/ANALİZ için okunur, güdüme
          GİRMEZ. (truth kanalında hedef rotasyonu YOK; indeks 23-26 sadece
          konum ve hız veriyor.)
        """
        return _sdk.get_target_rotation()

    # ---------------- ölçüm/debug (yarışmada YOK) ----------------
    def truth(self):
        """Bozulmamış gerçek değerler; YALNIZ zarf ölçümü ve doğrulama için.
        Güdüme ASLA girmez."""
        d = _sdk.get_debug_truth()
        if not d.get("available"):
            return None
        tp = d["target"]["position"]; dp = d["drone"]["position"]
        return {
            "hedef_m": (tp[0] * CM, tp[1] * CM, tp[2] * CM),
            "drone_m": (dp[0] * CM, dp[1] * CM, dp[2] * CM),
            "drone_hiz_ms": d["drone"]["speed"] * MS,
            "bozma_maske": d.get("corruption_mask", 0),
            "bozma_aktif": d.get("corruption_active", []),
            "bozma_param": d.get("corruption_params", {}),
        }
