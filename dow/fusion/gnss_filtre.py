# ============================================================
# GNSS DUZELTICI v2 — POZISYON-TABANLI + ADAPTIF SUREC GURULTUSU
# ------------------------------------------------------------
# Hedefin jammer'la bozulmus GPS'ini (konum gurultusu, ani sicrama,
# veri kesintisi, gecikme) temizler. YALNIZCA bozuk GPS kullanir:
# SDK'dan get_target_location() -> (x, y, z). Hedef yaw/attitude
# KULLANMAZ (Bilgilendirme Dok. Bolum 2: hedef telemetrisi lat/lon/
# alt/hiz; attitude yok -> finalle birebir ortusur).
#
# MIMARI:
#  - CT-EKF cekirdek (durum: x, y, vx, vy, omega) -> manevra ongorusu
#    (coordinated-turn EKF: hedefin sabit donus hiziyla dondugunu
#     varsayip donusu ongorebilen genisletilmis Kalman filtresi)
#  - Fiziksel zarf (w_max/hiz_max/vz_max): kestirim, ucagin kinematik
#    sinirlari disina cikamaz
#  - Mahalanobis kapilari (gate_xy/gate_z): jammer sicramalarini
#    istatistiksel olarak reddeder (innovation'in beklenen belirsizlige
#    orani; ki-kare testi)
#  - Kacis mekanizmasi: kapi ust uste reddederse P sisirilir -> jammer
#    yeni rejime gecerse filtre ~2-3 s'de yeniden kilitlenir (divergence
#    onleyici)
#  - ADAPTIF dt: iki taze paket arasi GERCEK sure perf_counter ile
#    olculur -> cagri/dongu hizindan bagimsiz
#  - DEAD RECKONING: kesikte son hiz+donusle ileri ekstrapolasyon
#    (dr_maks_sn ile sinirli)
#  - LEAD (telafi_sn): cikti, GPS gecikmesini kapatmak icin ileri
#    tasinir; olculen gecikme ~1.13 s oldugundan varsayilan 1.0.
#
# YENI: adaptif_q -> son innovation'lar (olcum-tahmin farki) buyudugunde
# omega surec gurultusu Qw gecici yukselir; boylece omega manevrada hizli
# doner, duz ucusta sakin kalir (IMM'in hafif muadili). Dropout spike'ini
# COZMEZ (o anlarda olcum yok). Duz+veri-olan manevrada ~%5-15 iyilesme.
# AYAR NOTU: Qw=1e-2 (omega surec gurultusu; 1e-3 yerine, omega'nin
# manevrada biraz daha hizli donmesine izin verir -> ~%38 daha iyi).
# Birimler: cm, cm/s, s.  Kullanim: GNSSDuzeltici().guncelle(x, y, z)
# ============================================================
import numpy as np


class GNSSDuzeltici:

    def __init__(self, telafi_sn=1.0, dt=0.2,
                 R=50.0, Qp=500.0, Qw=1e-2, Rz=150.0, Qz=10.0,
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
