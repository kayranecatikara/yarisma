#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SAHTE SKYDAGGER BACKEND — donanımsız sınama için
================================================================================
Komitenin backend'inin YERİNE geçer: TCP 8766 + UDP 8767 dinler, `RC_US`
satırlarını kabul eder ve `CRSF_JSON` telemetrisi üretir.

⛔ BU BİR OYUNCAK DEĞİL, BİR SINAMA TEZGÂHIDIR — ama KANIT DA DEĞİLDİR
   (CLAUDE.md §2). İşi, gerçek backend'e bağlanmadan önce bizim tarafımızın
   protokole UYDUĞUNU göstermek. Gerçek zincirin çalıştığını yalnız gerçek
   donanım kanıtlar.

Ürettiği telemetri, rehber §8.2'deki alanların birebir aynısıdır ve
komutlara TEPKİ VERİR (basit fizik), böylece kapalı çevrim sınanabilir.

Kullanım:  python3 reel/araclar/sahte_skydagger.py
"""
import json
import math
import os
import socket
import threading
import time

HOST = "127.0.0.1"
TCP_PORT, UDP_PORT = 8766, 8767

_durum = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0,
          "lat": 41.10500, "lon": 29.02300, "alt": 150.0,
          "vz": 0.0, "hiz": 0.0, "sats": 14,
          "kanal": [1500, 1500, 988, 1500, 988] + [988] * 11,
          "n_rc": 0, "son_rc": 0.0, "arm": False}
_kilit = threading.Lock()
_istemciler = []


def _us_oran(us):
    us = max(988, min(2012, int(us)))
    return (us - 1500) / 512.0


def _fizik():
    """Kaba model: kanal -> duruş -> konum. Kapalı çevrim sınaması için."""
    onceki = time.monotonic()
    while True:
        time.sleep(0.02)
        simdi = time.monotonic()
        dt = simdi - onceki
        onceki = simdi
        with _kilit:
            k = list(_durum["kanal"])
            bayat = (simdi - _durum["son_rc"]) > 0.2      # ESP 200 ms tutar
        if bayat:
            continue                                      # link düştü sayılır
        roll = _us_oran(k[0]) * 60.0
        pitch = _us_oran(k[1]) * 60.0
        thr = (k[2] - 988) / 1024.0
        yaw_hizi = _us_oran(k[3]) * 120.0
        armli = k[4] > 1500
        with _kilit:
            _durum["arm"] = armli
            _durum["roll"], _durum["pitch"] = roll, pitch
            _durum["yaw"] = (_durum["yaw"] + yaw_hizi * dt) % 360.0
            if armli:
                _durum["vz"] += (20.0 * (thr - 0.5) - 0.5 * _durum["vz"]) * dt
                _durum["alt"] = max(0.0, _durum["alt"] + _durum["vz"] * dt)
                a = 9.81 * math.tan(math.radians(pitch))
                _durum["hiz"] = max(0.0, _durum["hiz"] + a * dt - 0.05 * _durum["hiz"])
                r = math.radians(_durum["yaw"])
                _durum["lat"] += (_durum["hiz"] * math.cos(r) * dt) / 111320.0
                _durum["lon"] += ((_durum["hiz"] * math.sin(r) * dt) /
                                  (111320.0 * math.cos(math.radians(41.105))))
            else:
                _durum["vz"] *= 0.9
                _durum["hiz"] *= 0.9


def _telem_dongusu():
    """Rehber §8.2 alanları, ölçülü hızlarda (attitude sık, GPS seyrek)."""
    n = 0
    while True:
        time.sleep(0.05)                       # 20 Hz taban
        n += 1
        with _kilit:
            d = dict(_durum)
        satirlar = [{"kind": "telem", "name": "attitude",
                     "roll": round(d["roll"], 1), "pitch": round(d["pitch"], 1),
                     "yaw": round(d["yaw"], 1)}]
        if n % 4 == 0:                         # 5 Hz GPS
            satirlar.append({"kind": "telem", "name": "gps",
                             "lat": round(d["lat"], 7), "lon": round(d["lon"], 7),
                             "speed": round(d["hiz"] * 3.6, 1),
                             "heading": round(d["yaw"], 1),
                             "altitude": round(d["alt"], 1), "sats": d["sats"]})
            satirlar.append({"kind": "telem", "name": "vario",
                             "vspeed": round(d["vz"], 2)})
        if n % 20 == 0:                        # 1 Hz
            satirlar.append({"kind": "telemetry", "lq": 100, "rssi": -55, "snr": 9})
            satirlar.append({"kind": "telem", "name": "battery",
                             "voltage": 15.8, "current": 12.0, "remaining": 78})
        gonder = b"".join(("CRSF_JSON " + json.dumps(s) + "\n").encode()
                          for s in satirlar)
        for c in list(_istemciler):
            try:
                c.sendall(gonder)
            except Exception:
                try:
                    _istemciler.remove(c)
                except ValueError:
                    pass


def _rc_isle(satir):
    if not satir.startswith("RC_US"):
        return False
    try:
        p = [int(x) for x in satir[5:].strip().split(",")]
    except ValueError:
        return False
    if len(p) != 16:
        return False
    with _kilit:
        _durum["kanal"] = p
        _durum["n_rc"] += 1
        _durum["son_rc"] = time.monotonic()
    return True


def _tcp_istemci(c):
    _istemciler.append(c)
    tampon = b""
    try:
        while True:
            v = c.recv(4096)
            if not v:
                break
            tampon += v
            while b"\n" in tampon:
                s, tampon = tampon.split(b"\n", 1)
                _rc_isle(s.decode("utf-8", "replace").strip())
    except Exception:
        pass
    finally:
        try:
            _istemciler.remove(c)
        except ValueError:
            pass
        c.close()


def _tcp_sunucu():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((HOST, TCP_PORT)); s.listen(8)
    except OSError as e:
        # ⛔ AYRI İŞ PARÇACIĞINDA PATLAYAN İSTİSNA SESSİZDİR: yığın izi
        #   loga düşer ama süreç yaşamaya devam eder ve "çalışıyor" görünür.
        #   Açık mesaj ver ve SÜRECİ BİTİR.
        print("⛔ TCP %d bağlanamadı: %s\n"
              "   Zaten çalışan bir sahte backend var. Kapat:\n"
              "     pkill -f '[s]ahte_skydagger'" % (TCP_PORT, e), flush=True)
        os._exit(2)
    while True:
        c, _ = s.accept()
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=_tcp_istemci, args=(c,), daemon=True).start()


def _udp_sunucu():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((HOST, UDP_PORT))
    except OSError as e:
        print("⛔ UDP %d bağlanamadı: %s" % (UDP_PORT, e), flush=True)
        os._exit(2)
    while True:
        try:
            v, _ = s.recvfrom(4096)
        except Exception:
            break
        _rc_isle(v.decode("utf-8", "replace").strip())


def main():
    print("=" * 66)
    print("  SAHTE SKYDAGGER BACKEND  (yalnız sınama — kanıt değildir)")
    print("=" * 66)
    print("  TCP %s:%d  (RC + telemetri)" % (HOST, TCP_PORT))
    print("  UDP %s:%d  (RC)" % (HOST, UDP_PORT))
    print("  Ctrl+C ile kapanır\n")
    for f in (_tcp_sunucu, _udp_sunucu, _fizik, _telem_dongusu):
        threading.Thread(target=f, daemon=True).start()
    try:
        while True:
            time.sleep(2.0)
            with _kilit:
                d = dict(_durum)
            print("  RC %6d  arm=%-5s  gaz %4d  irtifa %6.1f m  hiz %5.1f m/s  "
                  "yaw %5.1f  istemci %d"
                  % (d["n_rc"], d["arm"], d["kanal"][2], d["alt"], d["hiz"],
                     d["yaw"], len(_istemciler)))
    except KeyboardInterrupt:
        print("\n  kapandı.")


if __name__ == "__main__":
    main()
