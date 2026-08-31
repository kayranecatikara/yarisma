# -*- coding: utf-8 -*-
"""
================================================================================
GNSS DÜZELTİCİ — yarışma sunucusunun BOZULMUŞ hedef GPS'ini temizler
================================================================================
⛔ NİYE VAR: yarışmada hedef İHA'nın konumu bize **kasten bozulmuş** gelir
   (konum gürültüsü, ani sıçrama, veri kesintisi, gecikme). Ham veriyle
   nişan almak, uçağın ARTIK OLMADIĞI yere nişan almaktır.

⛔ ALGORİTMA KULLANICININ — DOKUNULMADI. `gnss_filtre_eniyi.py` olduğu gibi
   alındı; aşağıdaki `GNSSDuzeltici` sınıfı birebir aynıdır. Bu dosyanın
   eklediği tek şey, onu bizim boru hattımıza bağlayan ince bir sarmalayıcı
   (`HedefSuzgeci`) ve BİRİM ÇEVRİMİdir.

--------------------------------------------------------------------------------
⛔⛔ BİRİM UYARISI — EN KOLAY HATA BURADA
--------------------------------------------------------------------------------
   `GNSSDuzeltici` **SANTİMETRE** ile çalışır (kaynak başlığında yazılı:
   "Birimler: cm, cm/s, s"). Bizim boru hattımız **METRE** kullanır.
   Sarmalayıcı girişte ×100, çıkışta ÷100 yapar. Bu çevrim atlanırsa
   filtre 100 kat büyük bir dünyada çalışır: kapılar hiç açılmaz, hız
   sınırı (`hiz_max=3000 cm/s = 30 m/s`) anlamsızlaşır ve çıktı çöp olur.

--------------------------------------------------------------------------------
NASIL ÇALIŞIR (CLAUDE.md §0.2 — terimler tanımsız bırakılmaz)
--------------------------------------------------------------------------------
  * KALMAN FİLTRESİ: gürültülü ölçümle bir hareket MODELİNİ birleştirip,
    ikisinden de daha iyi bir kestirim üreten özyineli yöntem.
  * CT-EKF (coordinated-turn genişletilmiş Kalman): hedefin sabit bir
    dönüş hızıyla döndüğünü varsayar. Düz uçan bir model, viraja giren
    uçağı sürekli geriden takip ederdi; bu model dönüşü ÖNGÖRÜR.
    Durum: (x, y, vx, vy, ω) — konum, hız, dönüş hızı.
  * MAHALANOBIS KAPISI: ölçümün, beklenen belirsizliğe ORANLA ne kadar
    uzak olduğu. Jammer'ın attığı sıçrama istatistiksel olarak
    "imkânsız" çıkar ve REDDEDİLİR. Ham eşik (metre) kullanmaktan
    üstündür: filtre eminken dar, belirsizken geniş davranır.
  * KAÇIŞ MEKANİZMASI: kapı üst üste `kacis_esik` kez reddederse
    belirsizlik şişirilir. Yoksa jammer yeni bir rejime geçtiğinde
    filtre "her şeyi reddediyorum" diye SONSUZA KADAR kilitli kalırdı.
  * DEAD RECKONING (ölü hesap): veri kesildiğinde son hız ve dönüşle
    ileri gitmek. `dr_maks_sn` ile sınırlıdır — sonsuza kadar tahmin
    yürütmek, uydurmaktır.
  * LEAD / TELAFİ: GPS gecikmelidir (ölçülmüş ~1.13 s). Çıktı, o
    gecikmeyi kapatmak için `telafi_sn` kadar İLERİ taşınır.

--------------------------------------------------------------------------------
BORU HATTINDAKİ YERİ
--------------------------------------------------------------------------------
    sunucu -> hedef.py (yaş kapısı) -> cerceve.metreye() -> [BU FİLTRE] -> güdüm
                                                             ^
                                    `baglanti.hedef_konum_bozuk()` içinde

⛔ FİLTRE YEREL METRİK ÇERÇEVEDE ÇALIŞIR, enlem/boylamda DEĞİL. Sebebi:
   derece cinsinden mesafeler enlemle ölçeklenir ve Kalman'ın doğrusal
   varsayımları bozulur. Önce metreye çevrilir, sonra süzülür.

⛔ KAPALIYKEN BİT BİT ESKİ DAVRANIŞ: `DOW_GNSS_FILTRE=0` iken ham konum
   olduğu gibi döner. Bekçi R122 bunu sınar.
================================================================================
"""
import os

# Birimler: cm, cm/s, s.  Kullanim: GNSSDuzeltici().guncelle(x, y, z)
# ============================================================
import numpy as np


class GNSSDuzeltici:

    def __init__(self, telafi_sn=1.0, dt=0.2,
                 R=50.0, Qp=500.0, Qw=3e-2, Rz=150.0, Qz=10.0,
                 gate_xy=5.0, kacis_esik=12, kacis_carpan=100.0,   # [D1][D2]
                 w_max=1.0, hiz_max=3000.0,                        # [D4]
                 vz_max=2500.0, gate_z=5.0, joseph=True,
                 dr_maks_sn=2.5,
                 adaptif_q=True, q_ref=2.0, q_boost_max=25.0, q_ema=0.85):                                  # [D5]
        self.telafi_sn = telafi_sn
        self.dt   = dt
        self.gate_xy = gate_xy
        self.kacis_esik   = kacis_esik
        self.kacis_carpan = kacis_carpan
        self.w_max   = w_max
        self.hiz_max = hiz_max
        self.vz_max  = vz_max
        self.gate_z  = gate_z
        self.joseph  = joseph
        self.dr_maks_sn = dr_maks_sn
        self.Hxy  = np.array([[1,0,0,0,0],[0,1,0,0,0]], float)
        self.Rxy  = np.eye(2) * R**2
        self.Hz   = np.array([[1,0]], float)
        self.Rz_m = np.array([[Rz**2]])
        self.Qz_m = np.eye(2) * Qz
        self.Qd   = np.diag([Qp, Qp, Qp, Qp, Qw])
        self._I5  = np.eye(5)
        self._x = self._P = self._z = self._Pz = None
        self._baslandi  = False
        self._ilk       = None
        self._ilk_t     = None      # [D3]
        self._son_bozuk = None
        self._adim      = 0
        self._son_zaman = None
        self._t_update  = None
        self._ret_sayac = 0         # [D2] ust uste ret sayaci
        # teshis (istege bagli okunur)
        self.son_d2 = None; self.son_kabul = None
        self.adaptif_q = adaptif_q; self.q_ref = q_ref
        self.q_boost_max = q_boost_max; self.q_ema = q_ema
        self._d2_ema = q_ref

    def _ct(self, d, dt):
        px,py,vx,vy,w = d
        if abs(w) < 1e-6: w = 1e-6
        s,c = np.sin(w*dt), np.cos(w*dt)
        return np.array([px+(vx*s-vy*(1-c))/w,
                         py+(vx*(1-c)+vy*s)/w,
                         vx*c-vy*s, vx*s+vy*c, w])

    def _jac(self, x, dt, eps=1e-5):
        f0=self._ct(x,dt); F=np.eye(5)
        for j in range(5):
            xp=x.copy(); xp[j]+=eps
            F[:,j]=(self._ct(xp,dt)-f0)/eps
        return F

    def _kisitla(self):
        if self.w_max is not None and abs(self._x[4]) > self.w_max:
            self._x[4] = float(np.clip(self._x[4], -self.w_max, self.w_max))
        if self.hiz_max is not None:
            hiz = np.hypot(self._x[2], self._x[3])
            if hiz > self.hiz_max:
                o = self.hiz_max / hiz
                self._x[2] *= o; self._x[3] *= o

    def _kisitla_z(self):
        if self.vz_max is not None:
            self._z[1] = float(np.clip(self._z[1], -self.vz_max, self.vz_max))

    def guncelle(self, bozuk_x, bozuk_y, bozuk_z, simdi=None):
        import time as _t
        if simdi is None: simdi = _t.perf_counter()
        bx,by,bz = float(bozuk_x), float(bozuk_y), float(bozuk_z)
        self._adim += 1

        if self._adim == 1:
            self._son_bozuk = np.array([bx,by,bz]); return None

        if self._son_bozuk is not None and np.allclose([bx,by,bz], self._son_bozuk):
            self._son_bozuk = np.array([bx,by,bz])
            # DEAD RECKONING: son hiz+donusle ileri git; sure sinirli [D5]
            if getattr(self,'_baslandi',False) and self._t_update is not None:
                gecen  = min(self.dr_maks_sn, max(0.0, simdi - self._t_update))
                fr = self._ct(self._x, gecen + self.telafi_sn)
                z_ileri = self._z[0] + self._z[1]*gecen        # Z: lead yok [D5]
                return float(fr[0]), float(fr[1]), float(z_ileri)
            return None
        self._son_bozuk = np.array([bx,by,bz])

        if not self._baslandi:
            if self._ilk is None:
                self._ilk = np.array([bx,by,bz]); self._ilk_t = simdi; return None
            dt0 = max(0.05, min(1.0, simdi - self._ilk_t)) if self._ilk_t else self.dt  # [D3]
            self._x  = np.array([self._ilk[0], self._ilk[1],
                                  (bx-self._ilk[0])/dt0, (by-self._ilk[1])/dt0, 0.05])  # [D3]
            self._P  = np.eye(5)*1e6
            self._z  = np.array([self._ilk[2], 0.0])
            self._Pz = np.eye(2)*1e6
            self._baslandi = True

        # PREDICT (ADAPTIF dt)
        if self._son_zaman is None:
            dt_eff = self.dt
        else:
            dt_eff = min(3.0, max(0.02, simdi - self._son_zaman))
        self._son_zaman = simdi
        olcek = dt_eff / self.dt
        Fz_eff = np.array([[1, dt_eff],[0, 1]])
        xe = self._x.copy()
        self._x  = self._ct(xe, dt_eff)
        F        = self._jac(xe, dt_eff)
        if self.adaptif_q:
            qboost = min(self.q_boost_max, max(1.0, self._d2_ema / self.q_ref))
            Qd_eff = self.Qd.copy(); Qd_eff[4,4] *= qboost
        else:
            Qd_eff = self.Qd
        self._P  = F @ self._P @ F.T + Qd_eff * olcek
        self._z  = Fz_eff @ self._z
        self._Pz = Fz_eff @ self._Pz @ Fz_eff.T + self.Qz_m * olcek

        # UPDATE XY: gercek Mahalanobis kapisi [D1] + kacis [D2]
        yk = np.array([bx,by]) - self.Hxy @ self._x
        Sx = self.Hxy @ self._P @ self.Hxy.T + self.Rxy
        Sx_inv = np.linalg.inv(Sx)
        d2 = float(yk @ Sx_inv @ yk)
        self.son_d2 = d2
        self._d2_ema = self.q_ema*self._d2_ema + (1.0-self.q_ema)*d2
        kabul = (self.gate_xy is None) or (d2 < self.gate_xy**2)
        if not kabul:
            self._ret_sayac += 1
            if self._ret_sayac >= self.kacis_esik:      # [D2] kacis:
                self._P = self._P * self.kacis_carpan    # belirsizligi sisir,
                self._ret_sayac = 0                      # yeni rejime kilitlen
                Sx = self.Hxy @ self._P @ self.Hxy.T + self.Rxy
                Sx_inv = np.linalg.inv(Sx)
                kabul = True
        else:
            self._ret_sayac = 0
        self.son_kabul = kabul
        if kabul:
            K = self._P @ self.Hxy.T @ Sx_inv
            self._x = self._x + K @ yk
            if self.joseph:
                A = self._I5 - K @ self.Hxy
                self._P = A @ self._P @ A.T + K @ self.Rxy @ K.T
            else:
                self._P = (self._I5 - K @ self.Hxy) @ self._P

        # UPDATE Z (+ gate + Joseph) — degismedi
        yz = np.array([bz]) - self.Hz @ self._z
        Sz = self.Hz @ self._Pz @ self.Hz.T + self.Rz_m
        Sz_inv = np.linalg.inv(Sz)
        z_ok = True
        if self.gate_z is not None:
            z_ok = float(yz @ Sz_inv @ yz) < self.gate_z**2
        if z_ok:
            Kz = self._Pz @ self.Hz.T @ Sz_inv
            self._z = self._z + Kz @ yz
            if self.joseph:
                Az = np.eye(2) - Kz @ self.Hz
                self._Pz = Az @ self._Pz @ Az.T + Kz @ self.Rz_m @ Kz.T
            else:
                self._Pz = (np.eye(2) - Kz @ self.Hz) @ self._Pz

        self._kisitla()
        self._kisitla_z()
        self._t_update = simdi
        f = self._ct(self._x, self.telafi_sn)
        return float(f[0]), float(f[1]), float(self._z[0])


# ==============================================================================
#  SARMALAYICI — boru hattına bağlar. Algoritmaya DOKUNMAZ.
# ==============================================================================
def _f(ad, varsayilan):
    try:
        return float(os.environ.get(ad, varsayilan))
    except (TypeError, ValueError):
        return varsayilan


class SuzgecCfg:
    #: Kill-switch. 0 -> ham konum aynen döner (bit bit eski davranış).
    ACIK = os.environ.get("DOW_GNSS_FILTRE", "0") not in ("0", "", "kapali")
    #: GPS gecikmesi telafisi (s). Çıktı bu kadar İLERİ taşınır.
    TELAFI_SN = _f("DOW_GNSS_TELAFI", 1.0)
    #: Beklenen paket aralığı (s). Sunucu 1.5 Hz ise ~0.67, 5 Hz ise 0.2.
    #  ⚠ Yalnız ilk ölçek içindir; gerçek dt her adımda ÖLÇÜLÜR.
    DT = _f("DOW_GNSS_DT", 0.2)
    #: Ölçüm gürültüsü (cm). Bozulma büyükse yükselt.
    R = _f("DOW_GNSS_R", 50.0)
    #: Kesintide ölü hesabın azami süresi (s). Aşılırsa filtre susar.
    DR_MAKS_SN = _f("DOW_GNSS_DR_MAKS", 2.5)


class HedefSuzgeci:
    """Hedefin bozuk yerel konumunu (METRE) süzer. Girdi/çıktı METREdir.

    ⛔ İÇERİDE SANTİMETREYE ÇEVİRİR — `GNSSDuzeltici` cm ile çalışır.
    """

    #: metre -> santimetre
    OLCEK = 100.0

    def __init__(self, cfg=SuzgecCfg):
        self.cfg = cfg
        self.acik = bool(cfg.ACIK)
        self._f = None
        self.sayac = {"cagri": 0, "suzuldu": 0, "ham_dondu": 0, "reddedilen": 0}
        self.son_duzeltme_m = 0.0
        if self.acik:
            self._f = GNSSDuzeltici(telafi_sn=cfg.TELAFI_SN, dt=cfg.DT,
                                    R=cfg.R, dr_maks_sn=cfg.DR_MAKS_SN)

    def suz(self, konum_m, simdi=None):
        """(x, y, z) metre -> süzülmüş (x, y, z) metre.

        `simdi`: dış zaman damgası (s). None ise gerçek saat kullanılır.
        ⛔ SINAMA/LOG TEKRARI İÇİN ŞART: filtre `perf_counter` ile GERÇEK
          süreyi ölçer. Kaydı hızlı oynatırken zamanı enjekte etmezsen
          filtre hedefi 400 m/s gidiyor sanır, hız zarfına (30 m/s)
          çarpar ve HER ÖLÇÜMÜ REDDEDER. (Bu tuzağa düşüldü, 2026-08-31.)

        ⛔ FİLTRE HENÜZ KİLİTLENMEDİYSE (ilk paketler) ya da kesintide ölü
          hesap süresi dolduysa `None` döner. O hâlde HAM konum döndürülür —
          hedefi kaybetmektense gürültülü görmek yeğdir. Yaş kapısı
          (`hedef.py`) zaten bayat veriyi ayrıca eler.
        """
        if not self.acik or self._f is None or konum_m is None:
            return konum_m
        self.sayac["cagri"] += 1
        x, y, z = konum_m
        s = self.OLCEK
        try:
            cikti = self._f.guncelle(x * s, y * s, z * s, simdi=simdi)
        except Exception:
            # ⛔ FİLTRE PATLARSA UÇUŞ DURMAZ. Ham konuma düşülür.
            self.sayac["ham_dondu"] += 1
            return konum_m
        if self._f.son_kabul is False:
            self.sayac["reddedilen"] += 1
        if cikti is None:
            self.sayac["ham_dondu"] += 1
            return konum_m
        fx, fy, fz = cikti[0] / s, cikti[1] / s, cikti[2] / s
        self.sayac["suzuldu"] += 1
        self.son_duzeltme_m = round(((fx - x) ** 2 + (fy - y) ** 2) ** 0.5, 2)
        return fx, fy, fz

    def durum(self):
        d = {"acik": self.acik, "duzeltme_m": self.son_duzeltme_m, **self.sayac}
        if self._f is not None:
            d["son_d2"] = (round(self._f.son_d2, 1)
                           if self._f.son_d2 is not None else None)
            d["kabul"] = self._f.son_kabul
        return d
