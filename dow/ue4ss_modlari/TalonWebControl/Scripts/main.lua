-- ============================================================================
-- TalonWebControl - Talon'u YER KONTROL ARAYUZUNDEN surer (4 eksen)
-- ============================================================================
-- Resmi SDK (TCP 12345) Talon'a komut VEREMIYOR - sadece get_target_* okur.
-- Bu yuzden arayuz ile oyun arasinda DOSYA KOPRUSU kullaniliyor:
--   web/server.py  ->  /tmp/talon_kopru.txt  ->  (Z: surucusu)  ->  bu mod
--
-- DOSYA BICIMI (tek satir, bosluk ayrilmis, ondalikli):
--   <aktif> <throttle> <yaw> <pitch> <roll> <sayac>
--     aktif    : 0/1      serbest ucus acik mi
--     throttle : 0..1     ileri hiz (0 = MIN_HIZ, 1 = MAX_HIZ)
--     yaw      : -1..1    burun sola / saga  (dumen)
--     pitch    : -1..1    alcal / tirman
--     roll      : -1..1   sola / saga yatis
--     sayac    : her yazmada artar (tazelik kontrolu)
--                (istege bagli 7. alan; yoksa 0 varsayilir - eski
--                 arayuzlerle geriye donuk uyumlu)
--
-- ROLL DAVRANISI: gercek bir ucakta yatis donus uretir. Bu yuzden roll hem
-- govdeyi yatirir hem de ROLL_DONUS kadar donus katar (koordineli donus).
-- Yaw ekseni ondan bagimsiz, dogrudan dumen gibi calisir.
--
-- Talon'u rotasindan kopartan sey: BPC_AIMove.isDead = true. Olculdu -
-- teleport/dondurma/nuclear-freeze yontemlerinin hepsi 1.5 sn icinde geri
-- snap'liyordu (sapma 0.0 cm); isDead ile 500 cm hedef -> 500.0 cm sonuc.
-- ============================================================================

local KOPRU      = "Z:\\tmp\\talon_kopru.txt"
local TIK_MS     = 30
local MIN_HIZ    = 300.0    -- throttle 0  (cm/s)
local MAX_HIZ    = 4000.0   -- throttle 1  (cm/s)
local TIRMANIS   = 600.0    -- tam pitch'te dikey hiz (cm/s)
local YAW_HIZI   = 35.0     -- tam yaw'da donus (derece/s)
local ROLL_DONUS = 20.0     -- tam roll'da EK donus (derece/s) - koordineli donus
local ROLL_GORSEL= 45.0     -- tam roll'da govde yatisi (derece)
local BURUN      = 15.0     -- tam pitch'te burun acisi (derece)
local BAYAT_TIK  = 40       -- sayac bu kadar tik degismezse eksenleri sifirla (~1.2 sn)

-- ⛔⛔ KARE ve DAIRE DESENLERI SILINDI (2026-08-27, KULLANICI KARARI)
--   *"bu daire ve kare senaryolarinda artik test yapmayalim, bu senaryolar
--   gercege hic uygun degiller. bu senaryolarda ucak ucarken bazi parcalari
--   falan kopuyor, boyle degisik bir sey oluyor. o yuzden komple kaldiralim,
--   hatta ue4ss'yi de kaldiralim ve sadece default ucus senaryosunda
--   ucuralim."*
--   Silinen: KARE_* / DAIRE_* sabitleri, kip 1 ve 2 dallari, kareAcik/
--   daireAcik/daireYay/daireTur/kareYol/kareDonulen/kareKenarNo durumu ve
--   kopru satirinin 7. alani (kip).
--   ⚠ ELLE KUMANDA (eski kip 0) DURUYOR: `araclar/manevra.py` kisa sureli
--     devralmayla kacamak yaptirmak icin bu yolu kullaniyor.
--   Olculen sonuclar `docs/GORSEL_GUDUM_SICILI.md`de kaliyor.

local talon, aimove = nil, nil
local acik = false
local X, Y, Z, YAW = 0, 0, 0, 0
local thr, yaw, pit, rol = 0.0, 0.0, 0.0, 0.0
local sonSayac, bayat, tikSayaci = -1, 0, 0

local function L(s) print("[TalonWeb] " .. tostring(s)) end

-- Ayni mesaji her tikte basma (30 ms dongu = saniyede 33 satir olurdu).
local sonMesaj, sonMesajTik = nil, -9999
local function LKis(msg)
    if msg == sonMesaj and (tikSayaci - sonMesajTik) < 200 then return end   -- ~6 sn
    sonMesaj, sonMesajTik = msg, tikSayaci
    L(msg)
end

local function Bul()
    if talon and talon:IsValid() and aimove and aimove:IsValid() then return true end
    pcall(function() talon = FindFirstOf("BPP_AIDroneTalon_C") end)
    if not (talon and talon:IsValid()) then return false end
    pcall(function() aimove = talon["BPC_AIMove"] end)
    if not (aimove and aimove:IsValid()) then
        local c = {}; pcall(function() c = FindAllOf("BPC_AIMove_C") or {} end)
        if #c > 0 then aimove = c[1] end
    end
    return aimove and aimove:IsValid()
end

-- Kopru dosyasini oku: 6 alan, ondalikli olabilir
local function Oku()
    local f = io.open(KOPRU, "r")
    if not f then return nil end
    local satir = f:read("*l")
    f:close()
    if not satir then return nil end
    local a = {}
    for tok in satir:gmatch("[-%d%.]+") do a[#a+1] = tonumber(tok) end
    if #a < 6 then return nil end
    return a[1], a[2], a[3], a[4], a[5], a[6]
end

local function Kis(v, lo, hi)
    if v == nil then return 0 end
    if v < lo then return lo elseif v > hi then return hi end
    return v
end

local function Baslat()
    if not Bul() then LKis("Talon yok - once goreve gir (FLY, sonra E)") return false end
    pcall(function() aimove["isDead"] = true end)      -- spline takibini kapat
    local l, r
    pcall(function() l = talon:K2_GetActorLocation() end)
    pcall(function() r = talon:K2_GetActorRotation() end)
    if not l then return false end
    X, Y, Z = l.X, l.Y, l.Z
    YAW = r and r.Yaw or 0
    thr, yaw, pit, rol = 0.4, 0, 0, 0
    acik = true
    L(string.format("ARAYUZ KONTROLU ACIK - irtifa %.0f m, yon %.0f", Z/100, YAW))
    return true
end

local function Durdur()
    if aimove and aimove:IsValid() then pcall(function() aimove["isDead"] = false end) end
    acik = false
    yaw, pit, rol = 0, 0, 0
    L("arayuz kontrolu kapali - Talon kendi rotasina dondu")
end

local dt = TIK_MS / 1000.0
LoopAsync(TIK_MS, function()
    tikSayaci = tikSayaci + 1
    local a, t, y, p, r, s = Oku()

    if a == nil then
        if acik then Durdur() end                      -- dosya yok/bozuk -> guvenli tarafa
        return
    end

    -- Tazelik: sayac ilerlemiyorsa arayuz donmus/kapanmis demektir.
    -- Kumanda eksenlerini sifirla ama throttle'i KORU - ucak duz ucmaya devam etsin.
    if s == sonSayac then
        bayat = bayat + 1
        if bayat > BAYAT_TIK then y, p, r = 0, 0, 0 end
    else
        bayat = 0
        sonSayac = s
    end

    if a == 1 and not acik then
        if not Baslat() then return end
    elseif a == 0 and acik then
        Durdur()
        return
    end
    if not acik then return end

    thr = Kis(t, 0.0, 1.0)
    yaw = Kis(y, -1.0, 1.0)
    pit = Kis(p, -1.0, 1.0)
    rol = Kis(r, -1.0, 1.0)

    if not (talon and talon:IsValid()) then acik = false; talon = nil; aimove = nil; return end

    local hiz = MIN_HIZ + thr * (MAX_HIZ - MIN_HIZ)
    local gorselRoll, gorselPitch = rol * ROLL_GORSEL, pit * BURUN

    -- Donus: dumen (yaw) + yatistan gelen koordineli donus (roll)
    YAW = YAW + (yaw * YAW_HIZI + rol * ROLL_DONUS) * dt
    Z = Z + pit * TIRMANIS * dt

    if YAW > 180 then YAW = YAW - 360 elseif YAW < -180 then YAW = YAW + 360 end

    local rad = math.rad(YAW)
    X = X + math.cos(rad) * hiz * dt
    Y = Y + math.sin(rad) * hiz * dt

    pcall(function()
        talon:K2_SetActorLocation({X=X, Y=Y, Z=Z}, false, {}, false)
        talon:K2_SetActorRotation({Pitch = gorselPitch, Yaw = YAW, Roll = gorselRoll}, false)
    end)
end)

L("yuklendi (4 eksen, elle kumanda) - kopru: " .. KOPRU)
