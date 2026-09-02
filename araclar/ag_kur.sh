#!/usr/bin/env bash
# ==============================================================================
# YARIŞMA AĞI — ethernet ile sunucunun yerel ağına bağlan
# ==============================================================================
# Haberleşme dokümanı §2: yarışma alanında sunucuya ETHERNET KABLOSUYLA
# bağlanılır. Sunucu 10.0.0.10:10001, bize verilen adres 10.0.0.114/24.
#
# ⛔ NİYE BETİK: NetworkManager aktif. Elle `ip addr add` yazmak İŞE YARAMAZ —
#   NM birkaç saniye içinde ezer. Kalıcı bir profil gerekir (`nmcli`).
# ⛔ never-default: bu bağlantı VARSAYILAN ROTAYI ALMAZ. Yarışma ağında
#   internet çıkışı yok; varsayılanı alırsa makinenin ağı komple kopar.
#   Sunucu aynı /24'te olduğu için ağ geçidine gerek de yok.
#
# Kullanım:
#     sudo ./araclar/ag_kur.sh            # kur ve doğrula
#     sudo ./araclar/ag_kur.sh --kaldir   # yarışma sonrası temizle
set -u
ARAYUZ="${AG_ARAYUZ:-enp4s0}"
ADRES="${AG_ADRES:-10.0.0.114/24}"
SUNUCU_IP="${AG_SUNUCU:-10.0.0.10}"
SUNUCU_PORT="${AG_PORT:-10001}"
PROFIL="yarisma"

kirmizi(){ printf '\033[31m%s\033[0m\n' "$*"; }
sari(){    printf '\033[33m%s\033[0m\n' "$*"; }
yesil(){   printf '\033[32m%s\033[0m\n' "$*"; }

if [ "${1:-}" = "--kaldir" ]; then
    nmcli con down "$PROFIL" 2>/dev/null
    nmcli con delete "$PROFIL" 2>/dev/null
    yesil "  '$PROFIL' profili kaldırıldı."
    exit 0
fi

[ "$(id -u)" = "0" ] || { kirmizi "  sudo ile çalıştır:  sudo ./araclar/ag_kur.sh"; exit 1; }

echo "=============================================================="
echo "  YARIŞMA AĞI KURULUMU"
echo "=============================================================="
echo "  arayüz : $ARAYUZ"
echo "  adres  : $ADRES"
echo "  sunucu : $SUNUCU_IP:$SUNUCU_PORT"
echo

# ---- 1) kablo takılı mı ----
if [ ! -e "/sys/class/net/$ARAYUZ" ]; then
    kirmizi "  ⛔ $ARAYUZ diye bir arayüz YOK.  ip link  ile bak."; exit 1
fi
ip link set "$ARAYUZ" up 2>/dev/null
sleep 1
if [ "$(cat /sys/class/net/$ARAYUZ/carrier 2>/dev/null)" != "1" ]; then
    kirmizi "  ⛔ KABLO TAKILI DEĞİL ($ARAYUZ: NO-CARRIER)."
    echo   "     Ethernet kablosunu tak, sonra tekrar çalıştır."
    exit 1
fi
yesil "  ✔ kablo takılı"

# ---- 2) profili kur ----
nmcli con down "$PROFIL" 2>/dev/null
nmcli con delete "$PROFIL" 2>/dev/null
nmcli con add type ethernet ifname "$ARAYUZ" con-name "$PROFIL" \
      ipv4.method manual ipv4.addresses "$ADRES" \
      ipv4.never-default yes ipv6.method disabled >/dev/null || {
    kirmizi "  ⛔ profil oluşturulamadı"; exit 1; }
nmcli con up "$PROFIL" >/dev/null || { kirmizi "  ⛔ profil açılamadı"; exit 1; }
sleep 2

# ---- 3) doğrula ----
IP_VAR=$(ip -4 addr show "$ARAYUZ" | grep -oP 'inet \K[0-9.]+/[0-9]+' | head -1)
if [ -z "$IP_VAR" ]; then
    kirmizi "  ⛔ adres atanmadı"; exit 1
fi
yesil "  ✔ adres atandı: $IP_VAR"

if ping -c 2 -W 2 "$SUNUCU_IP" >/dev/null 2>&1; then
    yesil "  ✔ sunucuya ping geçiyor ($SUNUCU_IP)"
else
    sari  "  ⚠ ping GEÇMİYOR. Sunucu ICMP'yi kapatmış olabilir —"
    sari  "    aşağıdaki HTTP denemesi asıl ölçüttür."
fi

KOD=$(curl -s -m 4 -o /dev/null -w '%{http_code}' \
      "http://$SUNUCU_IP:$SUNUCU_PORT/api/sunucusaati" 2>/dev/null)
if [ "$KOD" = "200" ]; then
    yesil "  ✔ SUNUCU CEVAP VERİYOR (HTTP $KOD)"
elif [ -n "$KOD" ] && [ "$KOD" != "000" ]; then
    sari  "  ⚠ sunucu HTTP $KOD döndü — ağ TAMAM, uç noktayı hakemle teyit et"
else
    kirmizi "  ⛔ SUNUCUYA ULAŞILAMIYOR."
    echo   "     · kablo doğru prizde mi"
    echo   "     · hakemlerin verdiği adres/port hâlâ 10.0.0.10:10001 mi"
    echo   "     · bize verilen IP hâlâ 10.0.0.114 mü"
    exit 1
fi

echo
yesil "  AĞ HAZIR."
echo "  Sıradaki:  python3 araclar/sunucu_testi.py --sure 20"
