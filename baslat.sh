#!/usr/bin/env bash
# ==============================================================================
# TEKNOFEST 2026 · SAVAŞAN İHA AVCI DRONE — YARIŞMA BAŞLATMA
# ==============================================================================
# TEK KOMUT. Bütün ayarlar burada; kod değiştirmeden buradan ayarlanır.
#
#   ./baslat.sh              yarışma kipi (sunucu AÇIK, GNSS süzgeci AÇIK)
#   ./baslat.sh --deneme     sunucu KAPALI, hedef UDP 47800'den (yer denemesi)
#   ./baslat.sh --kapat      yalnız kapat
#
# ⛔ ÖNCE SKYDAGGER BACKEND HAZIR OLMALI:
#      ./skydagger/baslat_backend.sh
#      /connect <ESP32 portu> · RC_ENABLE · (2S pil tak, MAVİ) · STOP · EXTERNAL
set -u
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

kirmizi(){ printf '\033[31m%s\033[0m\n' "$*"; }
sari(){    printf '\033[33m%s\033[0m\n' "$*"; }
yesil(){   printf '\033[32m%s\033[0m\n' "$*"; }

# ==============================================================================
# 1 · YARIŞMA SUNUCUSU  (Haberleşme Dokümanı 2026)
# ==============================================================================
# ⛔ Yarışma alanında ETHERNET KABLOSUYLA sunucunun yerel ağına bağlanılır
#   (doküman §2). Adresi hakemler bildirir; aşağıdaki değeri ona göre değiştir.
# ⭐ HAKEMLERİN BİLDİRDİĞİ KESİN ADRES (2026-08-31): 10.0.0.10 : 10001
#   Yarışma yerel ağı — ethernet kablosuyla bağlanılır (doküman §2).
export DOW_SUNUCU="${DOW_SUNUCU:-http://10.0.0.10:10001}"
export DOW_SUNUCU_KADI="${DOW_SUNUCU_KADI:-hamidiye}"
export DOW_SUNUCU_SIFRE="${DOW_SUNUCU_SIFRE:-Z8vN1cR5tY}"
# ⭐ HAKEMLERİN BİLDİRDİĞİ TAKIM NUMARASI (doküman §7.1): 2
export DOW_TAKIM_NO="${DOW_TAKIM_NO:-2}"
# ⛔⛔ GÖNDERİM HIZI — DOKÜMANIN CEZALI KURALI (§7):
#   "En az 1 Hz. **2 Hz ÜZERİ 400 + hata kodu 3** ile cevaplanır."
#   1.8 Hz: üst sınıra pay bırakır, hedef verisini olabildiğince taze alır.
#   Hedef verisi YANITTA geldiği için gönderim hızı = HEDEF TAZELEME HIZI.
export DOW_SUNUCU_HZ="${DOW_SUNUCU_HZ:-1.8}"

# ==============================================================================
# 2 · GNSS SÜZGECİ — hedefin BOZULMUŞ GPS'ini temizler
# ==============================================================================
# ⛔ YARIŞMADA AÇIK. Hedef konumu kasten bozuk gelir (gürültü, sıçrama,
#   kesinti, gecikme). Ham veriyle nişan almak, uçağın ARTIK OLMADIĞI yere
#   nişan almaktır.
export DOW_GNSS_FILTRE="${DOW_GNSS_FILTRE:-1}"
# Paketler arası beklenen süre. Hedef, telemetri YANITINDA geldiği için
# gönderim hızımıza eşittir: 1.8 Hz -> 0.55 s.
export DOW_GNSS_DT="${DOW_GNSS_DT:-0.55}"
# ⛔⛔ EN ÖNEMLİ AYAR: ölçüm gürültüsü (SANTİMETRE).
#   Gerçek bozulma büyüklüğüne EŞLENMELİ. Ölçüldü (sentetik):
#     bozulma 2 m -> R=200 : %64 iyileşme, 1/200 reddedilen
#     bozulma 2 m -> R=50  : ÇÖKÜYOR, 150/200 reddedilen
#   SAHADA AYARI: panelde `gnss.reddedilen` sayacı hızla artıyorsa R KÜÇÜK.
export DOW_GNSS_R="${DOW_GNSS_R:-200}"
# GPS gecikmesi telafisi (s). Çıktı bu kadar İLERİ taşınır.
export DOW_GNSS_TELAFI="${DOW_GNSS_TELAFI:-1.0}"
# Kesintide ölü hesabın azami süresi (s).
export DOW_GNSS_DR_MAKS="${DOW_GNSS_DR_MAKS:-2.5}"

# ==============================================================================
# 3 · ARAÇ MODELİ  (ölçülmüş — tahmin değil)
# ==============================================================================
export DOW_CEV_MODEL=aci               # Angle modunda çubuk AÇIYA eşlenir
export DOW_CEV_ACI_MAX=60              # Betaflight angle_limit
export DOW_GPS_KAYNAK=gercek
# ⭐ Y_ISARET = +1.0 — YERDE KANITLANDI (2026-08-31, pervanesiz, DISARM):
#   `yon_testi.py --mod cevir`, 37 örnek, 5 burun yönü:
#     TOPLANMA  H0 0.992 vs H1 0.156      HEDEFE SAPMA  +0.4° vs -92.9°
#     mutlak sapma medyanı 1.0°
#   Araç hedeften KAÇMIYOR; güdüm hatayı KAPATIYOR.
#   İlk otonom uçuşta araç hedeften kaçıyorsa ilk bakılacak yer burasıdır.
export DOW_CEV_Y_ISARET="${DOW_CEV_Y_ISARET:-+1.0}"
# ⛔ KALKIŞ FAZI KAPALI: pilot aracı ELLE kaldırır, sonra OTONOM'a basar.
#   Açık olsaydı araç hedefi kovalamak yerine 45 m'ye tırmanmaya çalışırdı.
# ⭐ OTONOM KALKIŞ AÇIK (kullanıcı kararı 2026-08-31): araç ARM edildikten
#   sonra GÖREVİ BAŞLAT'a basılınca KALKIS fazında dikey tırmanır (yatay
#   komut YOK), hedef irtifaya varınca ISTASYON'a geçip hedefe yönelir.
export DOW_KALKIS_ALT="${DOW_KALKIS_ALT:-40}"
# ⛔⛔ TIRMANMA HIZI 12 -> 3 m/s. Dikey kapalı döngü (`dikey.py`) HİÇ
#   UÇMADI (panelde ölçüldü: aktif=false, 3470 pasif çağrı). 12 m/s ile
#   döngü salınırsa araç yerden fırlar ya da çakılır. 3 m/s'de 40 metreye
#   ~13 s'de çıkar, her an müdahale edilebilir.
export DOW_KALKIS_VZ="${DOW_KALKIS_VZ:-3.0}"

# ---- VİDEO KAYDI ----------------------------------------------------------
# ⛔ Kilitlenmeler kaydedilen videoyla inceleniyor (doküman §8).
export DOW_VIDEO_FPS="${DOW_VIDEO_FPS:-12}"

# ==============================================================================
# 4 · DEDEKTÖR  (gerçek görüntüyle eğitildi)
# ==============================================================================
export DOW_MODEL="${DOW_MODEL:-tayarti_v1}"
export DOW_DET_IMGSZ_UZAK="${DOW_DET_IMGSZ_UZAK:-640}"   # modelin eğitim boyutu
export DOW_DET_IMGSZ_YAKIN="${DOW_DET_IMGSZ_YAKIN:-640}"
export DOW_DET_YAKIN_ESIK="${DOW_DET_YAKIN_ESIK:-18}"
# ⛔ KANAL SIRASI: `tayarti_v1` BGR ister. Ölçüldü: BGR 0.700 · RGB 0.000
export DOW_DET_RENK="${DOW_DET_RENK:-bgr}"

# ==============================================================================
# 5 · KAMERA OPTİĞİ  (kalibrasyon: FOV 125° köşegen, TILT 25°, BALIKGÖZ)
# ==============================================================================
export DOW_OPTIK_W="${DOW_OPTIK_W:-640}"
export DOW_OPTIK_H="${DOW_OPTIK_H:-480}"
export DOW_OPTIK_MODEL="${DOW_OPTIK_MODEL:-esuzaklik}"
export DOW_OPTIK_FOV_KOSEGEN="${DOW_OPTIK_FOV_KOSEGEN:-125}"
export DOW_OPTIK_F_PX="${DOW_OPTIK_F_PX:-366.7}"
export DOW_OPTIK_TILT="${DOW_OPTIK_TILT:-25.0}"
# ⚠ MENZIL_C hâlâ TÜRETME, ölçüm değil. Yalnız GÖRSEL fazı etkiler.
export DOW_OPTIK_MENZIL_C="${DOW_OPTIK_MENZIL_C:-676.5}"
export DOW_OPTIK_MENZIL_C_KOSEGEN="${DOW_OPTIK_MENZIL_C_KOSEGEN:-714.7}"
export DOW_KAM_KAYNAK="${DOW_KAM_KAYNAK:-/dev/video2}"

# ==============================================================================
# 6 · KUMANDA  (JUMPER-RC / RadioMaster — ÖLÇÜLDÜ, varsayılmadı)
# ==============================================================================
export DOW_KMD_EKS_ROLL="${DOW_KMD_EKS_ROLL:-0}"
export DOW_KMD_EKS_PITCH="${DOW_KMD_EKS_PITCH:-1}"
export DOW_KMD_EKS_THR="${DOW_KMD_EKS_THR:-2}"
export DOW_KMD_EKS_YAW="${DOW_KMD_EKS_YAW:-3}"
export DOW_KMD_EKS_ARM="${DOW_KMD_EKS_ARM:-4}"
# ⛔ -1 = kumandada otonom VETO anahtarı YOK. İzin panelden gelir.
#   Boş bir anahtarı AUX2'ye (kanal 6 = eksen 5) atarsan burayı 5 yap.
export DOW_KMD_EKS_KIP="${DOW_KMD_EKS_KIP:--1}"

# ==============================================================================
# 7 · DİKEY İNİŞ  (uçuş kartının ALT HOLD + POS HOLD kipleri)
# ==============================================================================
# Betaflight'tan doğrulandı: ALTHOLD AUX2 (kanal 6), POS HOLD AUX4 (kanal 8),
# ikisi de 1700-2100 aralığında. Ölü bant `alt_hold_deadband = 20`.
export DOW_INIS_CUBUK="${DOW_INIS_CUBUK:--0.35}"

EK=(); SUNUCU=1; SAHTE=0
for x in "$@"; do
    case "$x" in
        --deneme) SUNUCU=0 ;;
        --kapat)  ;;
        --sahte)  SAHTE=1; EK+=("$x") ;;
        *) EK+=("$x") ;;
    esac
done

# ---- önceki örneği temizle (desen köşeli parantezle kırık) ----
if pgrep -f "[d]rone_yki" >/dev/null 2>&1; then
    sari "  önceki yer kontrolü kapatılıyor"
    pkill -f "[d]rone_yki" 2>/dev/null || true; sleep 1
    pkill -9 -f "[d]rone_yki" 2>/dev/null || true
fi
if [ "${1:-}" = "--kapat" ]; then yesil "  kapatıldı."; exit 0; fi

python3 -c "import cv2,numpy" 2>/dev/null || {
    kirmizi "  HATA: paketler eksik ->  pip install -r requirements.txt"; exit 1; }

# ---- backend ayakta mı ----
# ⛔ --sahte donanımsız denemedir (seri port ve kamera aranmaz);
#   backend de aranmaz. Aksi hâlde "donanımsız" yol fiilen kırık
#   olur — bu tuzağa `drone_yki.main()` içinde bir kez düşülmüştü
#   (29 Ağu 2026). HABERLEŞME TESTİNİN YOLU BUDUR: drone açmadan
#   sunucuya bağlanılır, hedef verisi panelde görülür.
#   ⚠ Bu kipte sunucuya giden telemetri SAHTEdir.
if [ "$SAHTE" = "1" ]; then
    sari "  SAHTE KİP — backend/kamera/seri port aranmıyor"
    sari "  ⚠ Sunucuya giden telemetri SAHTE (gerçek veri için drone gerekir)"
elif ! python3 - <<'PY'
import socket, sys
try: socket.create_connection(("127.0.0.1", 8766), timeout=1.5).close()
except Exception: sys.exit(1)
PY
then
    kirmizi "  HATA: Skydagger backend'e ulaşılamıyor (127.0.0.1:8766)"
    echo "     ./skydagger/baslat_backend.sh  ->  /connect <port> -> RC_ENABLE"
    echo "     -> 2S pili tak (MAVİ) -> STOP -> EXTERNAL"
    exit 1
else
    yesil "  Skydagger backend: BULUNDU"
fi

if [ "$SUNUCU" = "1" ]; then
    [ "$DOW_TAKIM_NO" = "0" ] && kirmizi "  ⛔ DOW_TAKIM_NO=0 — HAKEMDEN ALDIĞIN NUMARAYI GİR!"
    EK+=(--sunucu "$DOW_SUNUCU")
    echo "  SUNUCU  : $DOW_SUNUCU   takım $DOW_TAKIM_NO   kadı $DOW_SUNUCU_KADI"
    echo "  GÖNDERİM: $DOW_SUNUCU_HZ Hz  (⛔ doküman sınırı 2 Hz)"
    echo "  GNSS    : süzgeç AÇIK  R=$DOW_GNSS_R cm  dt=$DOW_GNSS_DT s"
else
    sari "  DENEME KİPİ — sunucu KAPALI, hedef UDP 47800'den bekleniyor"
fi
echo "  PANEL   : http://127.0.0.1:8810"
echo
exec python3 -u drone_yki.py --bag skydagger --kamera "$DOW_KAM_KAYNAK" \
     --gorsel "${EK[@]}"
