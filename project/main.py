"""
Minecraft Modlama Merkezi  –  main.py
Gereksinim: customtkinter >= 5.2, pillow >= 10, requests (opsiyonel, kullanılmıyor;
            sadece urllib ile çalışır) 
PyInstaller tek dosya derlemesi için resource_path() kullanılır.

Klasör yapısı:
    main.py
    modrinth_api.py                ← Modrinth API yardımcı modülü (BERABER kopyala!)
    mods/                          ← uygulama mod deposu
    assets/                        ← ikonlar vb.
    fabric_installer/fabric-installer-1.1.1.exe
    shader_files/                  ← sodium .jar / iris .jar / shader paketi .zip
        sodium-fabric-xxx.jar
        iris-fabric-xxx.jar
        ShaderPackAdı.zip

PyInstaller derlemesi (modrinth_api.py otomatik dahil olur, ama emin olmak için):
    pyinstaller --noconfirm --onefile --windowed ^
        --add-data "mods;mods" ^
        --add-data "fabric_installer;fabric_installer" ^
        --add-data "shader_files;shader_files" ^
        --hidden-import modrinth_api ^
        main.py
"""

import os
import random
import sys
import glob
import shutil
import threading
import subprocess
import io
import json
import customtkinter as ctk
from tkinter import filedialog, messagebox, colorchooser

try:
    from PIL import Image
    _PIL_OK = True
except Exception:
    _PIL_OK = False

import urllib.request

import modrinth_api as mrapi

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_OK = True
except Exception:
    _DND_OK = False


# ---------------------------------------------------------------------------
# Dil sistemi  — tüm UI metinlerini seçili dile çevirir.
# Türkçe (tr) uygulamanın ana dilidir, diğer diller Google Translate'in
# ücretsiz endpoint'i ile runtime'da çevrilir ve bellekte önbelleğe alınır.
# ---------------------------------------------------------------------------
_DILLER = {
    "tr": "Türkçe",
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "zh": "中文",
    "ja": "日本語",
    "ko": "한국어",
    "ru": "Русский",
    "ar": "العربية",
}

_CEVIRI_ONBELLEGI: dict[str, str] = {}   # (dil_kodu, tr_metin) -> çevrilmiş


def t(metin: str) -> str:
    """UI metni için çeviri fonksiyonu.
    Mevcut dil Türkçe (tr) ise metni olduğu gibi döner.
    Diğer dillerde Google Translate ile çevirir, sonucu önbelleğe alır.
    Ağ hatası olursa orijinal Türkçe metni döner (asla çökmez)."""
    if not metin:
        return metin
    try:
        dil = AYARLAR.get("dil", "tr")
    except NameError:
        return metin
    if dil == "tr":
        return metin
    anahtar = f"{dil}:{metin}"
    if anahtar in _CEVIRI_ONBELLEGI:
        return _CEVIRI_ONBELLEGI[anahtar]
    try:
        import urllib.parse
        params = {
            "client": "gtx", "sl": "tr", "tl": dil, "dt": "t",
            "q": metin[:400],
        }
        url = ("https://translate.googleapis.com/translate_a/single?"
               + urllib.parse.urlencode(params))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            veri = json.loads(resp.read().decode("utf-8"))
        parcalar = [seg[0] for seg in veri[0] if seg and seg[0]]
        sonuc = "".join(parcalar) if parcalar else metin
    except Exception:
        sonuc = metin
    _CEVIRI_ONBELLEGI[anahtar] = sonuc
    return sonuc


def t_async(metin: str, callback) -> None:
    """Çeviriyi arka planda yapıp sonucu callback(sonuc) ile iletir.
    Zaten önbellekte varsa direkt (senkron) döner."""
    try:
        dil = AYARLAR.get("dil", "tr")
    except NameError:
        callback(metin)
        return
    if dil == "tr":
        callback(metin)
        return
    anahtar = f"{dil}:{metin}"
    if anahtar in _CEVIRI_ONBELLEGI:
        callback(_CEVIRI_ONBELLEGI[anahtar])
        return

    def _worker():
        sonuc = t(metin)
        callback(sonuc)

    threading.Thread(target=_worker, daemon=True).start()


def _cevrilebilir_mi(metin) -> bool:
    """Bir metnin çeviriye değer olup olmadığını belirler. Sadece ikon/emoji
    (✓, ✕, ⬡ vb.), boşluk ya da sayı/sürüm gibi harfsiz metinler çeviri
    isteğine gönderilmez — bunları Google Translate'e yollamak hem gereksiz
    hem de bazen ikon karakterlerini bozabiliyor."""
    if not isinstance(metin, str) or not metin.strip():
        return False
    return any(ch.isalpha() for ch in metin)


def tum_metinleri_cevir(widget) -> None:
    """Bir widget ağacındaki (ör. App penceresinin tamamı ya da tek bir
    frame) TÜM CTkLabel / CTkButton metinlerini mevcut dile göre çevirir.

    NEDEN GEREKLİ: Kod tabanında yüzlerce yerde düz Türkçe metin doğrudan
    yazılıyor (t(...) ile sarmalanmamış). Her birini tek tek t() içine almak
    yerine, widget ağır ağacı kurulduktan SONRA burada gezilir; her
    Label/Button'ın o anki metni "orijinal Türkçe" olarak saklanır
    (widget._orijinal_metin) ve seçili dile göre t_async ile çevrilip
    yerine yazılır. Böylece dil hangisi olursa olsun UYGULAMANIN TAMAMI
    (sidebar, sekme başlıkları, açıklamalar, buton yazıları, dinamik mod
    kartları vs.) o dile döner.

    Dil Türkçe ise hiçbir şey yapmaz (gereksiz ağ isteği atmaz).
    Zaten çevrilmiş bir widget'a tekrar uygulanırsa, önbellek sayesinde
    ek bir ağ isteği olmadan aynı sonucu anında uygular.
    """
    try:
        if AYARLAR.get("dil", "tr") == "tr":
            return
    except Exception:
        return

    def _widget_cevir(w):
        try:
            if isinstance(w, (ctk.CTkLabel, ctk.CTkButton)):
                mevcut = w.cget("text")
                if _cevrilebilir_mi(mevcut):
                    if not hasattr(w, "_orijinal_metin"):
                        w._orijinal_metin = mevcut
                    kaynak_metin = w._orijinal_metin

                    def _guncelle(yeni, w=w):
                        try:
                            if w.winfo_exists():
                                w.configure(text=yeni)
                        except Exception:
                            pass

                    t_async(kaynak_metin, _guncelle)
        except Exception:
            pass

        try:
            children = w.winfo_children()
        except Exception:
            children = []
        for c in children:
            _widget_cevir(c)

    _widget_cevir(widget)


def dili_degistir(yeni_dil: str) -> None:
    """Dili değiştirir, önbelleği temizler ve ayarları kaydeder.
    App._yeniden_baslat() ile pencere yeniden inşa edilmeli."""
    global _CEVIRI_ONBELLEGI
    _CEVIRI_ONBELLEGI = {}
    AYARLAR["dil"] = yeni_dil
    ayarlari_kaydet(AYARLAR)


# ---------------------------------------------------------------------------
# Otomatik güncelleme kontrolü  (GitHub Releases API üzerinden)
# ---------------------------------------------------------------------------
# NASIL ÇALIŞIR:
#   1. GITHUB_REPO değişkenini "kullanici-adi/repo-adi" şeklinde doldur
#      (örn. "seyomnn/minecraft-mod-merkezi").
#   2. GitHub'da her yeni sürüm için bir "Release" oluştur, tag adını
#      "v1.4", "v1.5" gibi uygulamadaki SURUM_NO ile aynı formatta ver.
#   3. İstersen release'e yeni derlenmiş .exe dosyasını da ekleyebilirsin;
#      bu durumda "İndir" linki doğrudan o dosyaya gider.
#   4. GITHUB_REPO boş bırakılırsa (varsayılan), güncelleme kontrolü
#      sessizce atlanır — hiçbir hata/uyarı göstermez, uygulama normal
#      çalışmaya devam eder. Yani repo kurulana kadar bu özellik pasif
#      kalır ve zarar vermez.
# ---------------------------------------------------------------------------
GITHUB_REPO = ""   # ← BURAYA "kullanici-adi/repo-adi" yaz (repo hazır olunca)
UYGULAMA_SURUMU = "1.4"   # BilgilendirmeFrame.SURUM_NO ile senkron tutulmalı


def _surum_karsilastir(a: str, b: str) -> int:
    """İki sürüm string'ini ('1.4', 'v1.10' gibi) karşılaştırır.
    a > b ise 1, a < b ise -1, eşitse 0 döner. 'v' önekini ve
    virgülden sonrasını yoksayarak nokta ile ayrılan sayıları karşılaştırır."""
    def parcala(s):
        s = s.strip().lstrip("vV")
        parcalar = []
        for p in s.split("."):
            sayi = "".join(ch for ch in p if ch.isdigit())
            parcalar.append(int(sayi) if sayi else 0)
        return parcalar

    pa, pb = parcala(a), parcala(b)
    uzunluk = max(len(pa), len(pb))
    pa += [0] * (uzunluk - len(pa))
    pb += [0] * (uzunluk - len(pb))
    if pa > pb:
        return 1
    if pa < pb:
        return -1
    return 0


def guncelleme_kontrol_et(callback):
    """GitHub Releases API'sinden en son sürümü sorar, mevcut sürümden
    yeniyse callback(True, surum_str, indirme_url, release_notu) çağırır.
    Yeni sürüm yoksa veya GITHUB_REPO boşsa/hata olursa
    callback(False, None, None, None) çağırır. Ağ isteği arka planda
    (thread içinde) yapılır, callback ana thread'e after(0, ...) ile
    güvenli şekilde iletilir — bu fonksiyonun çağrıldığı yerde bir
    tkinter widget'ının `.after` metodunu kullanabilmesi gerekir."""
    if not GITHUB_REPO:
        callback(False, None, None, None)
        return

    def worker():
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(
                url, headers={"User-Agent": "MinecraftModMerkezi",
                              "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                veri = json.loads(resp.read().decode("utf-8"))
            son_surum = str(veri.get("tag_name", "")).lstrip("vV")
            release_notu = veri.get("body", "") or ""
            indirme_url = veri.get("html_url", f"https://github.com/{GITHUB_REPO}/releases")
            # Release'e eklenmiş bir .exe varsa, doğrudan o dosyanın linkini tercih et.
            for asset in veri.get("assets", []):
                ad = asset.get("name", "")
                if ad.lower().endswith(".exe"):
                    indirme_url = asset.get("browser_download_url", indirme_url)
                    break
            if son_surum and _surum_karsilastir(son_surum, UYGULAMA_SURUMU) > 0:
                callback(True, son_surum, indirme_url, release_notu)
            else:
                callback(False, None, None, None)
        except Exception:
            callback(False, None, None, None)

    threading.Thread(target=worker, daemon=True).start()


# resource_path  –  PyInstaller + geliştirme ortamı (SADECE salt-okunur
# kaynaklar için: fabric installer .exe'si, ikon vb. — bunlar PyInstaller'ın
# --add-data ile pakete gömdüğü dosyalardır, değiştirilmezler)
# ---------------------------------------------------------------------------
def resource_path(relative: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative)


def _kalici_taban_klasor() -> str:
    taban = os.environ.get("APPDATA") or os.path.expanduser("~")
    klasor = os.path.join(taban, "MinecraftModMerkezi")
    os.makedirs(klasor, exist_ok=True)
    return klasor


def veri_yolu(relative: str) -> str:
    return os.path.join(_kalici_taban_klasor(), relative)


# Sabit yollar
MODS_DIR        = veri_yolu("mods")
SHADER_FILES    = veri_yolu("shader_files")   # ← sodium + iris + shader pack buraya
FABRIC_EXE      = resource_path(os.path.join("fabric_installer",
                                              "fabric-installer-1.1.1_(1).exe"))

APPDATA         = os.environ.get("APPDATA", "")
MC_DIR          = os.path.join(APPDATA, ".minecraft")
MC_MODS_DIR     = os.path.join(MC_DIR, "mods")
MC_SHADERS_DIR  = os.path.join(MC_DIR, "shaderpacks")

USER_HOME       = os.path.expanduser("~")
DOWNLOADS_DIR   = os.path.join(USER_HOME, "Downloads")

AYARLAR_DOSYASI = veri_yolu("ayarlar.json")

VARSAYILAN_AYARLAR = {
    "tema": "yesil",
    "tema_ozel_hex": None,
    "arkaplan": "koyu_gri",
    "arkaplan_ozel_hex": None,
    "scroll_hizi": 30,
    "market_indirme_hedefi": "modlar",
    "modlari_yukle_hedefi": "minecraft",
    "dil": "tr",   # "tr" | "en" | "de" | "fr" | "es" | "zh" | "ja" | "ko" | "ru" | "ar"
}


def ayarlari_yukle():
    try:
        with open(AYARLAR_DOSYASI, "r", encoding="utf-8") as f:
            veri = json.load(f)
        sonuc = dict(VARSAYILAN_AYARLAR)
        sonuc.update({k: v for k, v in veri.items() if k in VARSAYILAN_AYARLAR})
        return sonuc
    except Exception:
        return dict(VARSAYILAN_AYARLAR)


def ayarlari_kaydet(ayarlar: dict):
    try:
        with open(AYARLAR_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(ayarlar, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


AYARLAR = ayarlari_yukle()

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


def _hex_koyulastir(hex_renk: str, faktor: float) -> str:
    try:
        hex_renk = hex_renk.lstrip("#")
        r = int(hex_renk[0:2], 16)
        g = int(hex_renk[2:4], 16)
        b = int(hex_renk[4:6], 16)
        r = max(0, min(255, int(r * faktor)))
        g = max(0, min(255, int(g * faktor)))
        b = max(0, min(255, int(b * faktor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_renk if hex_renk.startswith("#") else f"#{hex_renk}"


_TEMA_PALETLERI = {
    "yesil":   dict(ad="Yeşil",     GREEN="#22c55e", GREEN_HOVER="#16a34a", GREEN_DIM="#15803d"),
    "gri":     dict(ad="Gri",       GREEN="#9ca3af", GREEN_HOVER="#b0b8c4", GREEN_DIM="#6b7280"),
    "mavi":    dict(ad="Mavi",      GREEN="#3b82f6", GREEN_HOVER="#2563eb", GREEN_DIM="#1d4ed8"),
    "mor":     dict(ad="Mor",       GREEN="#a855f7", GREEN_HOVER="#9333ea", GREEN_DIM="#7e22ce"),
    "kirmizi": dict(ad="Kırmızı",   GREEN="#ef4444", GREEN_HOVER="#dc2626", GREEN_DIM="#b91c1c"),
    "turuncu": dict(ad="Turuncu",   GREEN="#f97316", GREEN_HOVER="#ea580c", GREEN_DIM="#c2410c"),
    "pembe":   dict(ad="Pembe",     GREEN="#ec4899", GREEN_HOVER="#db2777", GREEN_DIM="#be185d"),
    "altin":   dict(ad="Altın",     GREEN="#eab308", GREEN_HOVER="#ca8a04", GREEN_DIM="#a16207"),
}

if AYARLAR.get("tema") == "ozel" and AYARLAR.get("tema_ozel_hex"):
    _oh = AYARLAR["tema_ozel_hex"]
    _TEMA_PALETLERI["ozel"] = dict(
        ad="Özel", GREEN=_oh,
        GREEN_HOVER=_hex_koyulastir(_oh, 0.82),
        GREEN_DIM=_hex_koyulastir(_oh, 0.62))
_TEMA_ANAHTARI = AYARLAR.get("tema", "yesil")
if _TEMA_ANAHTARI not in _TEMA_PALETLERI:
    _TEMA_ANAHTARI = "yesil"
GREEN        = _TEMA_PALETLERI[_TEMA_ANAHTARI]["GREEN"]
GREEN_HOVER  = _TEMA_PALETLERI[_TEMA_ANAHTARI]["GREEN_HOVER"]
GREEN_DIM    = _TEMA_PALETLERI[_TEMA_ANAHTARI]["GREEN_DIM"]

_ARKAPLAN_PALETLERI = {
    "koyu_gri": dict(
        ad="Koyu Gri",
        BG_SIDEBAR="#111111", BG_MAIN="#161616", BG_CARD="#1e1e1e",
        BG_CARD2="#252525", BG_HOVER="#2a2a2a", BORDER="#2d2d2d"),
    "siyah": dict(
        ad="Siyah",
        BG_SIDEBAR="#000000", BG_MAIN="#0a0a0a", BG_CARD="#141414",
        BG_CARD2="#1c1c1c", BG_HOVER="#222222", BORDER="#262626"),
    "lacivert": dict(
        ad="Lacivert",
        BG_SIDEBAR="#0d1321", BG_MAIN="#11182b", BG_CARD="#171f36",
        BG_CARD2="#1d2640", BG_HOVER="#242f4d", BORDER="#2a3552"),
    "antrasit": dict(
        ad="Antrasit",
        BG_SIDEBAR="#1a1d23", BG_MAIN="#20242b", BG_CARD="#272b33",
        BG_CARD2="#2e323b", BG_HOVER="#363a44", BORDER="#3a3f49"),
    "koyu_yesil": dict(
        ad="Koyu Yeşil",
        BG_SIDEBAR="#0d1a14", BG_MAIN="#11221a", BG_CARD="#162b21",
        BG_CARD2="#1c3429", BG_HOVER="#234032", BORDER="#284838"),
    "koyu_mor": dict(
        ad="Koyu Mor",
        BG_SIDEBAR="#160d21", BG_MAIN="#1b1129", BG_CARD="#221534",
        BG_CARD2="#291a3e", BG_HOVER="#31204a", BORDER="#382554"),
    "bordo": dict(
        ad="Bordo",
        BG_SIDEBAR="#1f0d12", BG_MAIN="#271116", BG_CARD="#30151c",
        BG_CARD2="#3a1a22", BG_HOVER="#452029", BORDER="#4d242e"),
    "koyu_kahve": dict(
        ad="Koyu Kahve",
        BG_SIDEBAR="#1a140d", BG_MAIN="#221a11", BG_CARD="#2b2116",
        BG_CARD2="#34281b", BG_HOVER="#3d3020", BORDER="#453624"),
}

if AYARLAR.get("arkaplan") == "ozel" and AYARLAR.get("arkaplan_ozel_hex"):
    _oah = AYARLAR["arkaplan_ozel_hex"]
    _ARKAPLAN_PALETLERI["ozel"] = dict(
        ad="Özel",
        BG_SIDEBAR=_hex_koyulastir(_oah, 0.7),
        BG_MAIN=_oah,
        BG_CARD=_hex_koyulastir(_oah, 1.15),
        BG_CARD2=_hex_koyulastir(_oah, 1.35),
        BG_HOVER=_hex_koyulastir(_oah, 1.55),
        BORDER=_hex_koyulastir(_oah, 1.45))

_ARKAPLAN_ANAHTARI = AYARLAR.get("arkaplan", "koyu_gri")
if _ARKAPLAN_ANAHTARI not in _ARKAPLAN_PALETLERI:
    _ARKAPLAN_ANAHTARI = "koyu_gri"
_ap = _ARKAPLAN_PALETLERI[_ARKAPLAN_ANAHTARI]

BG_SIDEBAR   = _ap["BG_SIDEBAR"]
BG_MAIN      = _ap["BG_MAIN"]
BG_CARD      = _ap["BG_CARD"]
BG_CARD2     = _ap["BG_CARD2"]
BG_HOVER     = _ap["BG_HOVER"]
BORDER       = _ap["BORDER"]
TXT_PRIMARY  = "#f5f5f5"
TXT_MUTED    = "#6b7280"
TXT_LABEL    = "#9ca3af"
RED_FG       = "#3f1515"
RED_HOVER    = "#6b1d1d"
RED_BORDER   = "#7f1d1d"
RED_TXT      = "#fca5a5"
PURPLE       = GREEN
PURPLE_HOVER = GREEN_HOVER
ORANGE       = "#d97706"
BLUE         = "#2563eb"


def arkaplani_uygula(arkaplan_adi: str, ozel_hex: str = None):
    global BG_SIDEBAR, BG_MAIN, BG_CARD, BG_CARD2, BG_HOVER, BORDER
    if ozel_hex:
        BG_MAIN = ozel_hex
        BG_SIDEBAR = _hex_koyulastir(ozel_hex, 0.7)
        BG_CARD = _hex_koyulastir(ozel_hex, 1.15)
        BG_CARD2 = _hex_koyulastir(ozel_hex, 1.35)
        BG_HOVER = _hex_koyulastir(ozel_hex, 1.55)
        BORDER = _hex_koyulastir(ozel_hex, 1.45)
        _ARKAPLAN_PALETLERI["ozel"] = dict(
            ad="Özel", BG_SIDEBAR=BG_SIDEBAR, BG_MAIN=BG_MAIN, BG_CARD=BG_CARD,
            BG_CARD2=BG_CARD2, BG_HOVER=BG_HOVER, BORDER=BORDER)
        AYARLAR["arkaplan"] = "ozel"
        AYARLAR["arkaplan_ozel_hex"] = ozel_hex
        ayarlari_kaydet(AYARLAR)
        return
    palet = _ARKAPLAN_PALETLERI.get(arkaplan_adi, _ARKAPLAN_PALETLERI["koyu_gri"])
    BG_SIDEBAR = palet["BG_SIDEBAR"]
    BG_MAIN = palet["BG_MAIN"]
    BG_CARD = palet["BG_CARD"]
    BG_CARD2 = palet["BG_CARD2"]
    BG_HOVER = palet["BG_HOVER"]
    BORDER = palet["BORDER"]
    AYARLAR["arkaplan"] = arkaplan_adi
    ayarlari_kaydet(AYARLAR)


def temayi_uygula(tema_adi: str, ozel_hex: str = None):
    global GREEN, GREEN_HOVER, GREEN_DIM, PURPLE, PURPLE_HOVER
    if ozel_hex:
        GREEN = ozel_hex
        GREEN_HOVER = _hex_koyulastir(ozel_hex, 0.82)
        GREEN_DIM = _hex_koyulastir(ozel_hex, 0.62)
        PURPLE = GREEN
        PURPLE_HOVER = GREEN_HOVER
        _TEMA_PALETLERI["ozel"] = dict(
            ad="Özel", GREEN=GREEN, GREEN_HOVER=GREEN_HOVER, GREEN_DIM=GREEN_DIM)
        AYARLAR["tema"] = "ozel"
        AYARLAR["tema_ozel_hex"] = ozel_hex
        ayarlari_kaydet(AYARLAR)
        return
    palet = _TEMA_PALETLERI.get(tema_adi, _TEMA_PALETLERI["yesil"])
    GREEN = palet["GREEN"]
    GREEN_HOVER = palet["GREEN_HOVER"]
    GREEN_DIM = palet["GREEN_DIM"]
    PURPLE = palet["GREEN"]
    PURPLE_HOVER = palet["GREEN_HOVER"]
    AYARLAR["tema"] = tema_adi
    ayarlari_kaydet(AYARLAR)

RECOMMENDED_MODS = [
    ("Sodium",        "Performans", BLUE,    "FPS artışı için en iyi mod"),
    ("Lithium",       "Performans", BLUE,    "Oyun mekaniği optimizasyonu"),
    ("Iris Shaders",  "Görsel",     PURPLE,  "Shader desteği"),
    ("JEI",           "Yardımcı",   ORANGE,  "Craft tarifleri görüntüleyici"),
    ("Xaero's Minimap","Yardımcı",  ORANGE,  "Mini harita"),
    ("AppleSkin",     "Yardımcı",   ORANGE,  "Yiyecek bilgilerini göster"),
]

KURULUM_ADIMLARI = [
    ("Java Kurulu mu Kontrol Et",
     "Fabric çalıştırmak için Java 17+ gereklidir.",
     "Fabric çalıştırmak için Java 17 veya üzeri gereklidir. Bilgisayarında kurulu\n"
     "olduğundan emin ol."),
    ("Fabric Installer'ı İndir",
     "Fabric'in resmi sitesinden installer'ı indirin.",
     "Sol menüdeki 'Fabric Kurulum' sekmesinden doğrudan kurulumu başlatabilirsin."),
    ("Installer'ı Çalıştır",
     "İndirilen .jar dosyasını çift tıklayarak aç.",
     "Alternatif olarak bu uygulamadaki 'Fabric'i Kur' butonunu kullan."),
    ("Fabric API'yi İndir",
     "Çoğu mod Fabric API gerektirir.",
     "Mod Marketi sekmesinden 'Fabric API' arayıp indirebilirsin."),
    ("Modları Kur",
     "Modlarını .minecraft/mods klasörüne kopyala.",
     "Bu uygulamanın 'Modlar' sekmesinden 'Modları Yükle' butonunu kullan."),
    ("Minecraft Launcher'ı Aç",
     "Fabric profilini seç ve oyna!",
     "Launcher'da 'Fabric' profili görünüyorsa kurulum başarılı demektir."),
]


# ===========================================================================
#  Yardımcı bileşenler
# ===========================================================================
class SidebarButton(ctk.CTkButton):
    def __init__(self, master, text, icon="", command=None, **kw):
        super().__init__(
            master,
            text=f"  {icon}  {text}" if icon else f"     {text}",
            command=command,
            height=40,
            corner_radius=8,
            font=ctk.CTkFont("Segoe UI", 15),
            anchor="w",
            fg_color="transparent",
            hover_color=BG_HOVER,
            text_color=TXT_LABEL,
            **kw)
        self._active = False

    def set_active(self, active: bool):
        self._active = active
        if active:
            self.configure(fg_color=GREEN_DIM, text_color=TXT_PRIMARY,
                           hover_color=GREEN_DIM)
        else:
            self.configure(fg_color="transparent", text_color=TXT_LABEL,
                           hover_color=BG_HOVER)


class TagLabel(ctk.CTkLabel):
    def __init__(self, master, text, color="#2563eb", **kw):
        super().__init__(master, text=text,
                         fg_color=color, text_color="white",
                         corner_radius=4,
                         font=ctk.CTkFont("Segoe UI", 12, "bold"),
                         width=0, height=20,
                         padx=6, pady=0,
                         **kw)


class Card(ctk.CTkFrame):
    def __init__(self, master, **kw):
        kw.setdefault("fg_color", BG_CARD)
        kw.setdefault("corner_radius", 10)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", BORDER)
        super().__init__(master, **kw)


class Divider(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, height=1, fg_color=BORDER, **kw)


class ToggleOptionMenu(ctk.CTkOptionMenu):
    """customtkinter'ın CTkOptionMenu'sü varsayılan olarak her tıklamada
    YENİ bir dropdown açar. Bu sınıf, ikinci tıklamayı yakalayıp dropdown'ı
    kapatacak şekilde davranışı düzeltir."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tom_acik = False
        self.bind("<Button-1>", self._tom_on_click, add="+")
        if hasattr(self, "_text_label") and self._text_label is not None:
            self._text_label.bind("<Button-1>", self._tom_on_click, add="+")
        if hasattr(self, "_canvas") and self._canvas is not None:
            self._canvas.bind("<Button-1>", self._tom_on_click, add="+")

    def _tom_on_click(self, event):
        if self._tom_acik:
            self._tom_acik = False
            try:
                self._dropdown_menu.unpost()
            except Exception:
                pass
            return "break"
        self._tom_acik = True
        self.after(150, self._tom_durum_kontrol)
        return None

    def _tom_durum_kontrol(self):
        try:
            durum = self._dropdown_menu.winfo_viewable()
        except Exception:
            durum = False
        if not durum:
            self._tom_acik = False
        else:
            self.after(150, self._tom_durum_kontrol)


def hizlandirilmis_scroll(scrollable_frame, carpan=None):
    canvas = getattr(scrollable_frame, "_parent_canvas", None)
    if canvas is None:
        return

    def _gecerli_carpan():
        if carpan is not None:
            return carpan
        try:
            return max(1, int(AYARLAR.get("scroll_hizi", 20)))
        except Exception:
            return 20

    def _on_wheel(event):
        yon = -1 if event.delta > 0 else 1
        kat = max(abs(event.delta) // 120, 1)
        adim = _gecerli_carpan() * kat
        canvas.yview_scroll(int(yon * adim), "units")
        return "break"

    def _bagla(widget):
        if not getattr(widget, "_hizli_scroll_bagli", False):
            try:
                widget.bind("<MouseWheel>", _on_wheel, add="+")
                widget._hizli_scroll_bagli = True
            except Exception:
                pass
        for child in widget.winfo_children():
            _bagla(child)

    def _ilk_baglama(_e=None):
        _bagla(scrollable_frame)

    canvas.bind("<MouseWheel>", _on_wheel, add="+")
    scrollable_frame.bind("<MouseWheel>", _on_wheel, add="+")

    scrollable_frame.after(150, _ilk_baglama)

    scrollable_frame._hizli_scroll_yenile = _ilk_baglama
    return _ilk_baglama


def progress_bar_animasyonlu_set(bar: "ctk.CTkProgressBar", hedef: float,
                                  sure_ms: int = 220, adim_ms: int = 16):
    try:
        baslangic = bar.get()
    except Exception:
        try:
            bar.set(hedef)
        except Exception:
            pass
        return

    if baslangic is None:
        baslangic = 0.0

    hedef = max(0.0, min(1.0, hedef))
    fark = hedef - baslangic
    if abs(fark) < 0.001:
        try:
            bar.set(hedef)
        except Exception:
            pass
        return

    toplam_adim = max(1, sure_ms // adim_ms)

    def adim(i):
        if i > toplam_adim:
            try:
                bar.set(hedef)
            except Exception:
                pass
            return
        ilerleme = i / toplam_adim
        yumusatilmis = 1 - (1 - ilerleme) ** 2
        deger = baslangic + fark * yumusatilmis
        try:
            bar.set(deger)
        except Exception:
            return
        bar.after(adim_ms, lambda: adim(i + 1))

    adim(0)


# ===========================================================================
#  Mod Ekle Penceresi  (dosya seç VEYA sürükle-bırak)
# ===========================================================================
class ModEklePenceresi(ctk.CTkToplevel):
    def __init__(self, master, on_ekle, **kw):
        super().__init__(master, **kw)
        self._on_ekle = on_ekle
        self._secilen_yollar: list[str] = []

        self.title("Mod Ekle")
        self.geometry("520x360")
        self.minsize(460, 320)
        self.configure(fg_color=BG_MAIN)
        self.transient(master)
        self.grab_set()

        self._build()
        self._dnd_kaydet()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(18, 10))
        ctk.CTkLabel(hdr, text="Mod Ekle",
                     font=ctk.CTkFont("Segoe UI", 17, "bold"),
                     text_color=TXT_PRIMARY).pack(side="left")
        ctk.CTkButton(
            hdr, text="✕", width=28, height=28,
            fg_color="transparent", hover_color=BG_HOVER,
            text_color=TXT_MUTED, font=ctk.CTkFont("Segoe UI", 14),
            command=self.destroy).pack(side="right")

        self._drop_zone = ctk.CTkFrame(
            self, fg_color=BG_CARD2, corner_radius=10,
            border_width=2, border_color=BORDER)
        self._drop_zone.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        self._drop_zone_inner = ctk.CTkFrame(self._drop_zone, fg_color="transparent")
        self._drop_zone_inner.place(relx=0.5, rely=0.5, anchor="center")

        self._dz_icon = ctk.CTkLabel(
            self._drop_zone_inner, text="⬆",
            font=ctk.CTkFont("Segoe UI", 28),
            text_color=TXT_MUTED)
        self._dz_icon.pack()
        self._dz_baslik = ctk.CTkLabel(
            self._drop_zone_inner, text="Mod dosyası seçmek için tıkla",
            font=ctk.CTkFont("Segoe UI", 14),
            text_color=TXT_LABEL)
        self._dz_baslik.pack(pady=(10, 2))
        self._dz_alt = ctk.CTkLabel(
            self._drop_zone_inner, text=".jar dosyaları desteklenir",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=TXT_MUTED)
        self._dz_alt.pack()

        for w in (self._drop_zone, self._drop_zone_inner,
                  self._dz_icon, self._dz_baslik, self._dz_alt):
            w.bind("<Button-1>", lambda e: self._dosya_sec())
            w.configure(cursor="hand2") if hasattr(w, "configure") else None

        alt = ctk.CTkFrame(self, fg_color="transparent")
        alt.pack(fill="x", padx=20, pady=(0, 18))

        self._ekle_btn = ctk.CTkButton(
            alt, text="Ekle", width=90, height=34,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            text_color="#0a0a0a",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            corner_radius=8,
            state="disabled",
            command=self._ekle_tiklandi)
        self._ekle_btn.pack(side="right")

        ctk.CTkButton(
            alt, text="İptal", width=80, height=34,
            fg_color="transparent", hover_color=BG_HOVER,
            text_color=TXT_LABEL,
            font=ctk.CTkFont("Segoe UI", 12),
            corner_radius=8,
            command=self.destroy).pack(side="right", padx=(0, 8))

    def _dnd_kaydet(self):
        try:
            kok = self.master.winfo_toplevel()
            if _DND_OK and getattr(kok, "dnd_destekli", False):
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._dosya_birakildi)
                self.dnd_bind("<<DragEnter>>", lambda e: self._vurgula(True))
                self.dnd_bind("<<DragLeave>>", lambda e: self._vurgula(False))
        except Exception:
            pass

    def _vurgula(self, aktif: bool):
        try:
            self._drop_zone.configure(
                border_color=GREEN if aktif else BORDER,
                fg_color=GREEN_DIM if aktif else BG_CARD2)
        except Exception:
            pass

    def _dosya_sec(self):
        paths = filedialog.askopenfilenames(
            title="Mod dosyası seçin (.jar)",
            filetypes=[("Jar dosyaları", "*.jar")])
        if paths:
            self._yollari_ekle(list(paths))

    def _dosya_birakildi(self, event):
        self._vurgula(False)
        ham = event.data
        yollar = []
        buf = ""
        icinde = False
        for ch in ham:
            if ch == "{":
                icinde = True
                buf = ""
            elif ch == "}":
                icinde = False
                yollar.append(buf)
                buf = ""
            elif ch == " " and not icinde:
                if buf:
                    yollar.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            yollar.append(buf)
        if yollar:
            self._yollari_ekle(yollar)

    def _yollari_ekle(self, yollar: list[str]):
        jar_yollari = [y for y in yollar if y.lower().endswith(".jar")]
        if not jar_yollari:
            messagebox.showwarning("Uyarı", "Sadece .jar dosyaları eklenebilir.")
            return
        for y in jar_yollari:
            if y not in self._secilen_yollar:
                self._secilen_yollar.append(y)
        self._secim_gorunumunu_guncelle()

    def _secim_gorunumunu_guncelle(self):
        n = len(self._secilen_yollar)
        if n == 0:
            self._dz_icon.configure(text="⬆")
            self._dz_baslik.configure(text="Mod dosyası seçmek için tıkla")
            self._dz_alt.configure(text=".jar dosyaları desteklenir")
            self._ekle_btn.configure(state="disabled")
        else:
            self._dz_icon.configure(text="✓")
            isimler = "\n".join(os.path.basename(y) for y in self._secilen_yollar[:4])
            if n > 4:
                isimler += f"\n… ve {n - 4} dosya daha"
            self._dz_baslik.configure(text=f"{n} dosya seçildi")
            self._dz_alt.configure(text=isimler)
            self._ekle_btn.configure(state="normal")

    def _ekle_tiklandi(self):
        if not self._secilen_yollar:
            return
        self._on_ekle(self._secilen_yollar)
        self.destroy()


# ===========================================================================
#  Mod Kütüphanesi sekmesi  (Modlar)
# ===========================================================================
class ModlarFrame(ctk.CTkFrame):

    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._secili = set()
        self._satirlar = {}
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 6))

        self._title_lbl = ctk.CTkLabel(
            hdr, text=t("Mod Kütüphanesi"),
            font=ctk.CTkFont("Segoe UI", 24, "bold"),
            text_color=TXT_PRIMARY)
        self._title_lbl.pack(anchor="w")

        self._count_lbl = ctk.CTkLabel(
            hdr, text=t("0 mod kayıtlı"),
            font=ctk.CTkFont("Segoe UI", 14),
            text_color=TXT_MUTED)
        self._count_lbl.pack(anchor="w")

        if _DND_OK:
            ctk.CTkLabel(
                hdr, text=t("💡 .jar dosyalarını bu pencereye sürükleyip bırakarak da ekleyebilirsin."),
                font=ctk.CTkFont("Segoe UI", 12),
                text_color=TXT_MUTED).pack(anchor="w", pady=(2, 0))

        tb = ctk.CTkFrame(self, fg_color="transparent")
        tb.pack(fill="x", pady=(8, 6))

        self._search = ctk.CTkEntry(
            tb, placeholder_text=t("Mod ara..."),
            height=36, width=280,
            fg_color=BG_CARD2, border_color=BORDER,
            text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 14))
        self._search.pack(side="left")
        self._search.bind("<KeyRelease>", lambda e: self._filtrele())

        ctk.CTkButton(
            tb, text=t("+ Mod Ekle"), height=36,
            fg_color=BG_CARD2, hover_color=BG_HOVER,
            border_width=1, border_color=BORDER,
            text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 14),
            corner_radius=8,
            command=self._mod_ekle).pack(side="right")

        ctk.CTkButton(
            tb, text=t("Modları Yükle"), height=36,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            text_color="#0a0a0a",
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
            corner_radius=8,
            command=self._modlari_yukle).pack(side="right", padx=(0, 8))

        ctk.CTkButton(
            tb, text=t("Yenile"), height=36,
            fg_color=BG_CARD2, hover_color=BG_HOVER,
            border_width=1, border_color=BORDER,
            text_color=TXT_MUTED,
            font=ctk.CTkFont("Segoe UI", 14),
            corner_radius=8,
            command=self.listele).pack(side="right", padx=(0, 8))

        tb2 = ctk.CTkFrame(self, fg_color="transparent")
        tb2.pack(fill="x", pady=(0, 12))

        self._secim_lbl = ctk.CTkLabel(
            tb2, text=t("Hiçbir mod seçilmedi."),
            font=ctk.CTkFont("Segoe UI", 13),
            text_color=TXT_MUTED)
        self._secim_lbl.pack(side="left")

        ctk.CTkButton(
            tb2, text=t("Tümünü Kaldır"), height=32, width=120,
            fg_color=RED_FG, hover_color=RED_HOVER,
            border_width=1, border_color=RED_BORDER,
            text_color=RED_TXT,
            font=ctk.CTkFont("Segoe UI", 13),
            corner_radius=6,
            command=self._tumunu_kaldir).pack(side="right")

        self._secili_kaldir_btn = ctk.CTkButton(
            tb2, text=t("Seçileni Kaldır (0)"), height=32, width=150,
            fg_color=RED_FG, hover_color=RED_HOVER,
            border_width=1, border_color=RED_BORDER,
            text_color=RED_TXT,
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            corner_radius=6,
            state="disabled",
            command=self._secili_kaldir)
        self._secili_kaldir_btn.pack(side="right", padx=(0, 8))

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color=BORDER)
        self._scroll.pack(fill="both", expand=True)
        self._scroll_yenile = hizlandirilmis_scroll(self._scroll)

        try:
            kok = self.winfo_toplevel()
            if _DND_OK and getattr(kok, "dnd_destekli", False):
                ic_canvas = getattr(self._scroll, "_parent_canvas", None)
                hedefler = [self, self._scroll]
                if ic_canvas is not None:
                    hedefler.append(ic_canvas)
                for hedef in hedefler:
                    hedef.drop_target_register(DND_FILES)
                    hedef.dnd_bind("<<Drop>>", self._dosya_birakildi)
                    hedef.dnd_bind("<<DragEnter>>", self._surukleme_basladi)
                    hedef.dnd_bind("<<DragLeave>>", self._surukleme_bitti)
        except Exception:
            pass

        alt_bar = ctk.CTkFrame(self, fg_color="transparent")
        alt_bar.pack(fill="x", pady=(6, 0))

        self._status = ctk.CTkLabel(
            alt_bar, text="", font=ctk.CTkFont("Segoe UI", 13),
            text_color=TXT_MUTED)
        self._status.pack(side="left", anchor="w")

        self._iptal_btn = ctk.CTkButton(
            alt_bar, text=t("✕ Seçileni İptal Et"), height=28, width=150,
            fg_color=BG_CARD2, hover_color=BG_HOVER,
            border_width=1, border_color=BORDER,
            text_color=TXT_MUTED,
            font=ctk.CTkFont("Segoe UI", 13),
            corner_radius=6,
            command=self._secimi_iptal_et)

        self._modlar: list[str] = []
        self.listele()

    def _mod_dosyalari(self) -> list[str]:
        if not os.path.isdir(MODS_DIR):
            return []
        try:
            return sorted(f for f in os.listdir(MODS_DIR)
                          if os.path.isfile(os.path.join(MODS_DIR, f))
                          and f.endswith(".jar"))
        except Exception:
            return []

    def listele(self):
        self._modlar = self._mod_dosyalari()
        self._secili = {m for m in self._secili if m in self._modlar}
        self._render(self._modlar)

    def _filtrele(self):
        q = self._search.get().lower()
        filtre = [m for m in self._modlar if q in m.lower()] if q else self._modlar
        self._render(filtre)

    def _render(self, modlar: list[str]):
        for w in self._scroll.winfo_children():
            w.destroy()
        self._satirlar = {}
        sayi = len(modlar)
        self._count_lbl.configure(text=t(f"{sayi} mod kayıtlı"))
        if not modlar:
            self._bos_goster()
        else:
            for mod in modlar:
                self._mod_satiri(mod)
        self._secim_durumunu_guncelle()
        if self._scroll_yenile:
            self.after(50, self._scroll_yenile)
        self._scroll_en_uste_sarmala()
        # Yeni oluşturulan tüm satırların metinlerini seçili dile çevir
        # (dil Türkçe ise tum_metinleri_cevir hiçbir şey yapmaz).
        tum_metinleri_cevir(self._scroll)

    def _scroll_en_uste_sarmala(self):
        self._scroll_canvas_en_uste(self._scroll)
        self.after(30, lambda: self._scroll_canvas_en_uste(self._scroll))
        self.after(90, lambda: self._scroll_canvas_en_uste(self._scroll))
        self.after(180, lambda: self._scroll_canvas_en_uste(self._scroll))
        self.after(320, lambda: self._scroll_canvas_en_uste(self._scroll))

    @staticmethod
    def _scroll_canvas_en_uste(scroll_frame):
        canvas = getattr(scroll_frame, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            scroll_frame.update_idletasks()
            canvas.update_idletasks()
        except Exception:
            pass
        try:
            canvas.yview("moveto", 0.0)
        except Exception:
            pass
        try:
            canvas.yview_moveto(0.0)
        except Exception:
            pass
        sb = getattr(scroll_frame, "_scrollbar", None)
        if sb is not None:
            try:
                sb.set(0.0, sb.get()[1] if sb.get() else 1.0)
            except Exception:
                pass

    def _bos_goster(self):
        box = ctk.CTkFrame(self._scroll, fg_color="transparent")
        box.pack(expand=True, pady=60)
        ic = ctk.CTkFrame(box, width=60, height=60,
                          fg_color=BG_CARD2, corner_radius=14)
        ic.pack()
        ctk.CTkLabel(ic, text="⬡", font=ctk.CTkFont("Segoe UI", 30),
                     text_color=TXT_MUTED).place(relx=.5, rely=.5, anchor="center")
        ctk.CTkLabel(box, text=t("Mod bulunamadı"),
                     font=ctk.CTkFont("Segoe UI", 17, "bold"),
                     text_color=TXT_PRIMARY).pack(pady=(12, 4))
        ctk.CTkLabel(box, text=t("Henüz hiç mod eklenmemiş."),
                     font=ctk.CTkFont("Segoe UI", 14),
                     text_color=TXT_MUTED).pack()
        ctk.CTkButton(
            box, text=t("+ İlk Modu Ekle"), height=38,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            text_color="#0a0a0a",
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
            corner_radius=8,
            command=self._mod_ekle).pack(pady=16)

    def _mod_satiri(self, mod: str):
        secili = mod in self._secili
        row = Card(self._scroll,
                   border_color=GREEN if secili else BORDER,
                   border_width=2 if secili else 1,
                   fg_color=BG_CARD,
                   cursor="hand2")
        row.pack(fill="x", pady=3)

        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)

        icon_lbl = ctk.CTkLabel(inner, text="✓" if secili else "⬡",
                     font=ctk.CTkFont("Segoe UI", 20),
                     text_color=GREEN,
                     width=28)
        icon_lbl.pack(side="left", padx=(0, 10))

        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text=mod,
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY,
                     anchor="w").pack(anchor="w")
        size_kb = ""
        try:
            b = os.path.getsize(os.path.join(MODS_DIR, mod))
            size_kb = f"{b / 1024:.0f} KB"
        except Exception:
            pass
        ctk.CTkLabel(info, text=size_kb,
                     font=ctk.CTkFont("Segoe UI", 13),
                     text_color=TXT_MUTED,
                     anchor="w").pack(anchor="w")

        self._satirlar[mod] = {"row": row, "icon": icon_lbl}

        for w in (row, inner, info):
            w.bind("<Button-1>", lambda e, m=mod: self._secimi_degistir(m))
        for child in info.winfo_children():
            child.bind("<Button-1>", lambda e, m=mod: self._secimi_degistir(m))

    def _secimi_degistir(self, mod):
        if mod in self._secili:
            self._secili.discard(mod)
        else:
            self._secili.add(mod)
        self._satir_gorunumunu_guncelle(mod)
        self._secim_durumunu_guncelle()

    def _satir_gorunumunu_guncelle(self, mod):
        ref = self._satirlar.get(mod)
        if not ref:
            return
        secili = mod in self._secili
        try:
            ref["row"].configure(
                border_color=GREEN if secili else BORDER,
                border_width=2 if secili else 1)
            ref["icon"].configure(text="✓" if secili else "⬡")
        except Exception:
            pass

    def _secimi_iptal_et(self):
        eski = list(self._secili)
        self._secili.clear()
        for mod in eski:
            self._satir_gorunumunu_guncelle(mod)
        self._secim_durumunu_guncelle()

    def _secim_durumunu_guncelle(self):
        n = len(self._secili)
        if n == 0:
            self._secim_lbl.configure(text=t("Hiçbir mod seçilmedi."))
            self._secili_kaldir_btn.configure(
                state="disabled", text=t("Seçileni Kaldır (0)"))
            self._iptal_btn.pack_forget()
        else:
            self._secim_lbl.configure(text=t(f"{n} mod seçildi."))
            self._secili_kaldir_btn.configure(
                state="normal", text=t(f"Seçileni Kaldır ({n})"))
            self._iptal_btn.pack(side="right", anchor="e")

    def _mod_ekle(self):
        ModEklePenceresi(self, on_ekle=self._dosyalari_kopyala)

    def _dosyalari_kopyala(self, paths):
        os.makedirs(MODS_DIR, exist_ok=True)
        n = 0
        guncellendi = 0
        atlandi = 0
        for p in paths:
            if not p.lower().endswith(".jar"):
                atlandi += 1
                continue
            hedef = os.path.join(MODS_DIR, os.path.basename(p))
            zaten_vardi = os.path.exists(hedef)
            try:
                shutil.copy2(p, hedef)
                if zaten_vardi:
                    guncellendi += 1
                else:
                    n += 1
            except Exception as e:
                messagebox.showerror("Kopyalama Hatası", str(e))
        if n or guncellendi:
            parcalar = []
            if n:
                parcalar.append(f"{n} yeni mod eklendi")
            if guncellendi:
                parcalar.append(f"{guncellendi} mod zaten ekliydi, güncellendi")
            mesaj = ", ".join(parcalar) + "."
            if atlandi:
                mesaj += f"  ({atlandi} dosya .jar olmadığı için atlandı.)"
            self._status.configure(text=t(mesaj), text_color=GREEN)
            self.listele()
        elif atlandi:
            messagebox.showwarning(
                "Uyarı", "Sadece .jar dosyaları mod olarak eklenebilir.")

    def _surukleme_basladi(self, event=None):
        try:
            self.winfo_toplevel().drop_overlay_goster()
        except Exception:
            pass

    def _surukleme_bitti(self, event=None):
        try:
            self.winfo_toplevel().drop_overlay_gizle()
        except Exception:
            pass

    def _dosya_birakildi(self, event):
        self._surukleme_bitti()
        ham = event.data
        yollar = []
        buf = ""
        icinde = False
        for ch in ham:
            if ch == "{":
                icinde = True
                buf = ""
            elif ch == "}":
                icinde = False
                yollar.append(buf)
                buf = ""
            elif ch == " " and not icinde:
                if buf:
                    yollar.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            yollar.append(buf)
        if yollar:
            self._dosyalari_kopyala(yollar)

    def _secili_kaldir(self):
        if not self._secili:
            return
        n = len(self._secili)
        if not messagebox.askyesno("Onayla", f"{n} mod silinsin mi?"):
            return
        hata = []
        for mod in list(self._secili):
            try:
                os.remove(os.path.join(MODS_DIR, mod))
            except Exception as e:
                hata.append(f"{mod}: {e}")
        self._secili.clear()
        self.listele()
        if hata:
            messagebox.showerror("Bazıları silinemedi", "\n".join(hata))
        else:
            self._status.configure(text=t(f"{n} mod silindi."), text_color=GREEN)

    def _tumunu_kaldir(self):
        dosyalar = self._mod_dosyalari()
        if not dosyalar:
            messagebox.showinfo("Bilgi", "Kaldırılacak mod yok.")
            return
        if not messagebox.askyesno(
                "Onayla", f"mods/ klasöründeki TÜM {len(dosyalar)} mod silinsin mi?\n"
                          "Bu işlem geri alınamaz."):
            return
        hata = []
        for mod in dosyalar:
            try:
                os.remove(os.path.join(MODS_DIR, mod))
            except Exception as e:
                hata.append(f"{mod}: {e}")
        self._secili.clear()
        self.listele()
        if hata:
            messagebox.showerror("Bazıları silinemedi", "\n".join(hata))
        else:
            self._status.configure(text=t("Tüm modlar silindi."), text_color=GREEN)

    def _modlari_yukle(self):
        dosyalar = self._mod_dosyalari()
        if not dosyalar:
            messagebox.showwarning(
                "Uyarı",
                "mods/ klasöründe yüklenecek .jar dosyası bulunamadı.\n"
                "Önce 'Mod Ekle' ile mod ekleyin.")
            return

        if AYARLAR.get("modlari_yukle_hedefi") == "indirilenler":
            hedef = DOWNLOADS_DIR
        elif not os.path.isdir(MC_DIR):
            hedef = filedialog.askdirectory(
                title="Minecraft mods klasörünü seçin (otomatik bulunamadı)")
            if not hedef:
                messagebox.showerror(
                    "Hata",
                    "Minecraft kurulu dizini bulunamadı!\n"
                    "Lütfen Minecraft'ın yüklü olduğundan emin olun.")
                return
        else:
            hedef = MC_MODS_DIR
        os.makedirs(hedef, exist_ok=True)
        threading.Thread(
            target=self._kopyala_thread,
            args=(dosyalar, hedef),
            daemon=True).start()

    def _kopyala_thread(self, dosyalar: list[str], hedef: str):
        toplam = len(dosyalar)
        hata = []
        for i, ad in enumerate(dosyalar, 1):
            try:
                shutil.copy2(os.path.join(MODS_DIR, ad),
                             os.path.join(hedef, ad))
                self.after(0, lambda i=i:
                    self._status.configure(
                        text=t(f"Kopyalanıyor… {i}/{toplam}"),
                        text_color=TXT_LABEL))
            except Exception as e:
                hata.append(f"{ad}: {e}")

        def bitti():
            if hata:
                messagebox.showerror(
                    "Bazı dosyalar kopyalanamadı", "\n".join(hata))
            else:
                self._status.configure(
                    text=t(f"{toplam} mod yüklendi  →  {hedef}"),
                    text_color=GREEN)
                messagebox.showinfo("Başarılı",
                    f"{toplam} mod başarıyla kopyalandı:\n{hedef}")
        self.after(0, bitti)


# ===========================================================================
#  Mod Marketi sekmesi  (Modrinth üzerinden arama / indirme)
# ===========================================================================
class ModKarti(Card):
    ICON_BOYUT = 56

    def __init__(self, master, hit: dict, on_indir, on_ziyaret, **kw):
        super().__init__(master, **kw)
        self._hit = hit
        self._on_indir = on_indir
        self._on_ziyaret = on_ziyaret
        self._build()

    def _build(self):
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)

        self._icon_frame = ctk.CTkFrame(
            inner, width=self.ICON_BOYUT, height=self.ICON_BOYUT,
            fg_color=BG_CARD2, corner_radius=10)
        self._icon_frame.pack(side="left", padx=(0, 14))
        self._icon_frame.pack_propagate(False)

        self._icon_lbl = ctk.CTkLabel(
            self._icon_frame, text="⬡",
            font=ctk.CTkFont("Segoe UI", 24),
            text_color=TXT_MUTED)
        self._icon_lbl.place(relx=.5, rely=.5, anchor="center")
        self.after(random.randint(0, 350), self._yukle_icon_async)

        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)

        top = ctk.CTkFrame(info, fg_color="transparent")
        top.pack(fill="x", anchor="w")
        ctk.CTkLabel(top, text=self._hit.get("title", "?"),
                     font=ctk.CTkFont("Segoe UI", 16, "bold"),
                     text_color=TXT_PRIMARY).pack(side="left")

        indirme = self._hit.get("downloads", 0)
        ctk.CTkLabel(top, text=f"  ↓ {self._format_sayi(indirme)}",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED).pack(side="left", padx=(8, 0))

        begeni = self._hit.get("follows", 0)
        ctk.CTkLabel(top, text=f"  ♥ {self._format_sayi(begeni)}",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED).pack(side="left", padx=(8, 0))

        self._aciklama_lbl = ctk.CTkLabel(
            info, text=self._hit.get("description", ""),
            font=ctk.CTkFont("Segoe UI", 13),
            text_color=TXT_LABEL, anchor="w", justify="left",
            wraplength=440)
        self._aciklama_lbl.pack(anchor="w", pady=(3, 0), fill="x")
        self.after(random.randint(0, 350), self._ceviri_async)

        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="right", padx=(10, 0))

        mevcut_surumler = self._hit.get("versions", []) or []
        secenekler = [v for v in mrapi.MC_VERSIONS_SIMPLE if v in mevcut_surumler]
        if not secenekler:
            secenekler = mevcut_surumler[:20] if mevcut_surumler else ["—"]

        self._surum_var = ctk.StringVar(value=secenekler[0])
        self._surum_combo = ToggleOptionMenu(
            right, values=secenekler, variable=self._surum_var,
            width=120, height=30,
            fg_color=BG_CARD2, button_color=GREEN, button_hover_color=GREEN_HOVER,
            dropdown_fg_color=BG_CARD2, dropdown_hover_color=BG_HOVER,
            text_color=TXT_PRIMARY, dropdown_text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 12))
        self._surum_combo.pack(pady=(0, 6))

        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.pack()

        self._indir_btn = ctk.CTkButton(
            btn_row, text=t("↓ İndir"), width=82, height=30,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            text_color="#0a0a0a",
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            corner_radius=6,
            command=self._indir_tiklandi)
        self._indir_btn.pack(side="left", padx=(0, 6))
        self._indir_btn._owner_card = self

        ctk.CTkButton(
            btn_row, text=t("↗ Ziyaret Et"), width=92, height=30,
            fg_color=BG_CARD2, hover_color=BG_HOVER,
            border_width=1, border_color=BORDER,
            text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 13),
            corner_radius=6,
            command=self._ziyaret_tiklandi).pack(side="left")

    @staticmethod
    def _format_sayi(n):
        try:
            n = int(n)
        except Exception:
            return str(n)
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)

    def _yukle_icon_async(self):
        url = self._hit.get("icon_url")
        if not url or not _PIL_OK:
            return

        def worker():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    veri = resp.read()
                img = Image.open(io.BytesIO(veri)).convert("RGBA")
                img = img.resize((self.ICON_BOYUT, self.ICON_BOYUT), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                       size=(self.ICON_BOYUT, self.ICON_BOYUT))
                self.after(0, lambda: self._uygula_icon(ctk_img))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _uygula_icon(self, ctk_img):
        try:
            self._icon_lbl.configure(image=ctk_img, text="")
            self._icon_lbl.image = ctk_img
        except Exception:
            pass

    def _ceviri_async(self):
        orijinal = self._hit.get("description", "")
        if not orijinal:
            return

        def callback(ceviri):
            self.after(0, lambda: self._aciklama_lbl.configure(text=ceviri))

        mrapi.translate_async(orijinal, callback)

    def _indir_tiklandi(self):
        surum = self._surum_var.get()
        self._indir_btn.configure(state="disabled")
        self._indirme_animasyonu_baslat()
        self._on_indir(self._hit, surum, self._indir_btn)

    def _indirme_animasyonu_baslat(self):
        self._indirme_animasyon_aktif = True
        desenler = [t("İndiriliyor"), t("İndiriliyor."), t("İndiriliyor.."), t("İndiriliyor...")]

        def adim(i=0):
            if not getattr(self, "_indirme_animasyon_aktif", False):
                return
            try:
                if not self._indir_btn.winfo_exists():
                    return
                self._indir_btn.configure(text=desenler[i % len(desenler)])
            except Exception:
                return
            self.after(280, lambda: adim(i + 1))

        adim()

    def _indirme_animasyonu_durdur(self):
        self._indirme_animasyon_aktif = False

    def _ziyaret_tiklandi(self):
        slug = self._hit.get("slug") or self._hit.get("project_id")
        self._on_ziyaret(slug)


class MarketFrame(ctk.CTkFrame):
    SAYFA_BOYUTU = 15
    DAHA_FAZLA_ADIM = 20

    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._offset = 0
        self._son_sonuclar = []
        self._daha_var_mi = True
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(hdr, text=t("Mod Marketi"),
                     font=ctk.CTkFont("Segoe UI", 24, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(hdr, text=t("Modrinth üzerinden binlerce modu keşfet ve indir"),
                     font=ctk.CTkFont("Segoe UI", 14),
                     text_color=TXT_MUTED).pack(anchor="w", pady=(0, 8))

        bilgi_kart = Card(self, border_color=GREEN_DIM)
        bilgi_kart.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            bilgi_kart,
            text=t("ℹ  Mod indirdiğiniz zaman, Modlar bölümünden 'Yenile' butonuna "
                 "bastığınızda indirdiğiniz mod orada görünecektir."),
            font=ctk.CTkFont("Segoe UI", 13),
            text_color=TXT_LABEL, justify="left",
            padx=12, pady=10).pack(anchor="w")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 6))

        self._search = ctk.CTkEntry(
            bar, placeholder_text=t("Mod ara..."),
            height=36,
            fg_color=BG_CARD2, border_color=BORDER,
            text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 14))
        self._search.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._search.bind("<Return>", lambda e: self._ara(yeni=True))

        self._loader_var = ctk.StringVar(value="fabric")
        self._loader_combo = ToggleOptionMenu(
            bar, values=["hepsi"] + mrapi.LOADERS,
            variable=self._loader_var, width=110, height=36,
            fg_color=BG_CARD2, button_color=GREEN, button_hover_color=GREEN_HOVER,
            dropdown_fg_color=BG_CARD2, dropdown_hover_color=BG_HOVER,
            text_color=TXT_PRIMARY, dropdown_text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 13),
            command=lambda _v: self._ara(yeni=True))
        self._loader_combo.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            bar, text=t("🔍 Ara"), height=36, width=90,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            text_color="#0a0a0a",
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
            corner_radius=8,
            command=lambda: self._ara(yeni=True)).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            bar, text=t("↻ Yenile"), height=36, width=90,
            fg_color=BG_CARD2, hover_color=BG_HOVER,
            border_width=1, border_color=BORDER,
            text_color=TXT_MUTED,
            font=ctk.CTkFont("Segoe UI", 14),
            corner_radius=8,
            command=lambda: self._ara(yeni=True)).pack(side="left")

        bar2 = ctk.CTkFrame(self, fg_color="transparent")
        bar2.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(bar2, text=t("Sırala:"),
                     font=ctk.CTkFont("Segoe UI", 13),
                     text_color=TXT_MUTED).pack(side="left", padx=(0, 6))

        self._sort_label_to_key = {ad: anahtar for anahtar, ad in mrapi.SORT_OPTIONS}
        self._sort_var = ctk.StringVar(value=mrapi.SORT_OPTIONS[1][1])
        self._sort_combo = ToggleOptionMenu(
            bar2, values=[ad for _k, ad in mrapi.SORT_OPTIONS],
            variable=self._sort_var, width=160, height=32,
            fg_color=BG_CARD2, button_color=GREEN, button_hover_color=GREEN_HOVER,
            dropdown_fg_color=BG_CARD2, dropdown_hover_color=BG_HOVER,
            text_color=TXT_PRIMARY, dropdown_text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 13),
            command=lambda _v: self._ara(yeni=True))
        self._sort_combo.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(bar2, text=t("Sürüm:"),
                     font=ctk.CTkFont("Segoe UI", 13),
                     text_color=TXT_MUTED).pack(side="left", padx=(0, 6))

        self._versiyon_var = ctk.StringVar(value="Hepsi")
        self._versiyon_combo = ToggleOptionMenu(
            bar2, values=["Hepsi"] + mrapi.MC_VERSIONS_SIMPLE,
            variable=self._versiyon_var, width=120, height=32,
            fg_color=BG_CARD2, button_color=GREEN, button_hover_color=GREEN_HOVER,
            dropdown_fg_color=BG_CARD2, dropdown_hover_color=BG_HOVER,
            text_color=TXT_PRIMARY, dropdown_text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 13),
            command=lambda _v: self._ara(yeni=True))
        self._versiyon_combo.pack(side="left")

        self._sonuc_lbl = ctk.CTkLabel(
            bar2, text="", font=ctk.CTkFont("Segoe UI", 13),
            text_color=TXT_MUTED)
        self._sonuc_lbl.pack(side="right")

        hizli = ctk.CTkFrame(self, fg_color="transparent")
        hizli.pack(fill="x", pady=(0, 10))
        for etiket, sorgu in [
            (t("⚡ Performans"), "performance"),
            (t("🗺 Harita"), "map"),
            (t("🍖 Yiyecek"), "food"),
            (t("📦 Depo"), "storage"),
            (t("⚔ Silah"), "weapon"),
            (t("🌿 Doğa"), "nature"),
        ]:
            ctk.CTkButton(
                hizli, text=etiket, height=28,
                fg_color=BG_CARD2, hover_color=BG_HOVER,
                border_width=1, border_color=BORDER,
                text_color=TXT_LABEL,
                font=ctk.CTkFont("Segoe UI", 12),
                corner_radius=14,
                command=lambda s=sorgu: self._hizli_filtre(s)
            ).pack(side="left", padx=(0, 6))

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color=BORDER)
        self._scroll.pack(fill="both", expand=True)
        self._scroll_yenile = hizlandirilmis_scroll(self._scroll)

        self._durum_lbl = ctk.CTkLabel(
            self._scroll, text=t("Aramak için yukarıdan bir kelime yaz veya hızlı filtrelere tıkla."),
            font=ctk.CTkFont("Segoe UI", 14),
            text_color=TXT_MUTED)
        self._durum_lbl.pack(pady=40)

        self._daha_fazla_btn = None
        self.after(200, lambda: self._ara(yeni=True))

    def _hizli_filtre(self, sorgu):
        self._search.delete(0, "end")
        self._search.insert(0, sorgu)
        self._ara(yeni=True)

    def _gecerli_loader(self):
        v = self._loader_var.get()
        return None if v == "hepsi" else v

    def _gecerli_versiyon(self):
        v = self._versiyon_var.get()
        return None if v == "Hepsi" else v

    def _gecerli_sort(self):
        ad = self._sort_var.get()
        return self._sort_label_to_key.get(ad, "relevance")

    def _ara(self, yeni=False, limit=None):
        if yeni:
            self._offset = 0
            self._daha_var_mi = True
        sorgu = self._search.get().strip()
        loader = self._gecerli_loader()
        versiyon = self._gecerli_versiyon()
        index = self._gecerli_sort()
        kullanilacak_limit = limit if limit is not None else self.SAYFA_BOYUTU

        if yeni:
            for w in self._scroll.winfo_children():
                w.destroy()
            self._daha_fazla_btn = None
            self._durum_lbl = ctk.CTkLabel(
                self._scroll, text=t("Aranıyor…"),
                font=ctk.CTkFont("Segoe UI", 14),
                text_color=TXT_MUTED)
            self._durum_lbl.pack(pady=40)
            self._scroll_en_uste_sarmala()

        def worker():
            sonuc = mrapi.search_mods(
                query=sorgu, loader=loader, game_version=versiyon,
                index=index, offset=self._offset, limit=kullanilacak_limit)
            self.after(0, lambda: self._sonuclari_goster(sonuc, yeni))

        threading.Thread(target=worker, daemon=True).start()

    def _scroll_en_uste_sarmala(self):
        for ms in (0, 30, 90, 220, 400):
            self.after(ms, lambda: ModlarFrame._scroll_canvas_en_uste(self._scroll))

    def _sonuclari_goster(self, sonuc: dict, yeni: bool):
        if yeni:
            try:
                if self._durum_lbl.winfo_exists():
                    self._durum_lbl.destroy()
            except Exception:
                pass

        if sonuc.get("error"):
            if yeni:
                ctk.CTkLabel(
                    self._scroll,
                    text=f"⚠ {t('Bağlantı hatası')}: {sonuc['error']}\n{t('İnternet bağlantını kontrol et.')}",
                    font=ctk.CTkFont("Segoe UI", 14),
                    text_color="#ef4444", justify="left").pack(pady=40)
            return

        hits = sonuc.get("hits", [])
        toplam = sonuc.get("total_hits", 0)

        if yeni and not hits:
            ctk.CTkLabel(
                self._scroll, text=t("Sonuç bulunamadı."),
                font=ctk.CTkFont("Segoe UI", 14),
                text_color=TXT_MUTED).pack(pady=40)
            self._sonuc_lbl.configure(text="")
            return

        if self._daha_fazla_btn is not None:
            try:
                self._daha_fazla_btn.destroy()
            except Exception:
                pass
            self._daha_fazla_btn = None

        self._offset += len(hits)
        self._daha_var_mi = self._offset < toplam
        self._sonuc_lbl.configure(text=f"{toplam} {t('mod bulundu')}  •  {self._loader_var.get()}")

        def kart_ekle(index=0):
            if index >= len(hits):
                self._liste_sonu_eklentisini_ekle()
                if self._scroll_yenile:
                    self.after(30, self._scroll_yenile)
                # Yeni eklenen kartların metinlerini de çevir
                tum_metinleri_cevir(self._scroll)
                return
            hit = hits[index]
            try:
                ModKarti(self._scroll, hit,
                         on_indir=self._mod_indir,
                         on_ziyaret=self._ziyaret_et).pack(fill="x", pady=4)
            except Exception:
                pass
            self.after(25, lambda: kart_ekle(index + 1))

        kart_ekle(0)

    def _liste_sonu_eklentisini_ekle(self):
        if self._daha_var_mi:
            self._daha_fazla_btn = ctk.CTkButton(
                self._scroll, text=t("Daha Fazla Göster (+20)"), height=36,
                fg_color=BG_CARD2, hover_color=BG_HOVER,
                border_width=1, border_color=BORDER,
                text_color=TXT_PRIMARY,
                font=ctk.CTkFont("Segoe UI", 14),
                corner_radius=8,
                command=self._daha_fazla)
            self._daha_fazla_btn.pack(pady=14)
        else:
            ctk.CTkLabel(
                self._scroll, text=t("— Tüm sonuçlar gösteriliyor —"),
                font=ctk.CTkFont("Segoe UI", 12),
                text_color=TXT_MUTED).pack(pady=14)

    def _daha_fazla(self):
        self._ara(yeni=False, limit=self.DAHA_FAZLA_ADIM)

    def _ziyaret_et(self, slug):
        if not slug:
            return
        import webbrowser
        webbrowser.open(f"https://modrinth.com/mod/{slug}")

    def _mod_indir(self, hit: dict, mc_surumu: str, buton: ctk.CTkButton):
        project_id = hit.get("project_id") or hit.get("slug")
        loader = self._gecerli_loader() or "fabric"

        def worker():
            versiyonlar = mrapi.get_project_versions(
                project_id, loader=loader,
                game_version=None if mc_surumu == "—" else mc_surumu)
            if not versiyonlar:
                versiyonlar = mrapi.get_project_versions(project_id, loader=loader)
            if not versiyonlar:
                self.after(0, lambda: self._indir_basarisiz(
                    buton, t("Bu sürüm için dosya bulunamadı.")))
                return

            dosya = mrapi.get_primary_file(versiyonlar[0])
            if not dosya:
                self.after(0, lambda: self._indir_basarisiz(
                    buton, t("İndirilecek dosya bulunamadı.")))
                return

            hedef_klasor = (DOWNLOADS_DIR
                            if AYARLAR.get("market_indirme_hedefi") == "indirilenler"
                            else MODS_DIR)
            os.makedirs(hedef_klasor, exist_ok=True)
            hedef_yol = os.path.join(hedef_klasor, dosya["filename"])

            basarili = mrapi.download_file(dosya["url"], hedef_yol)
            if basarili:
                self.after(0, lambda: self._indir_basarili(
                    buton, hit.get("title", "Mod"), hedef_klasor))
            else:
                self.after(0, lambda: self._indir_basarisiz(buton, t("İndirme başarısız.")))

        threading.Thread(target=worker, daemon=True).start()

    def _indir_basarili(self, buton, ad, hedef_klasor):
        kart = getattr(buton, "_owner_card", None)
        if kart:
            kart._indirme_animasyonu_durdur()
        self._buton_basari_flasi(buton)
        if AYARLAR.get("market_indirme_hedefi") == "indirilenler":
            messagebox.showinfo(
                t("Başarılı"),
                f"'{ad}' {t('indirildi')}!\n\n{t('Konum')}: {hedef_klasor}")
        else:
            messagebox.showinfo(
                t("Başarılı"),
                f"'{ad}' {t('indirildi ve mods/ klasörüne eklendi')}!\n\n"
                f"{t('Modlar sekmesinden Yenileye basınca listede görünecektir.')}")

    def _buton_basari_flasi(self, buton):
        try:
            buton.configure(state="normal", text=t("✓ İndirildi"),
                             fg_color=GREEN_HOVER)
        except Exception:
            return

        def koyulastir():
            try:
                if buton.winfo_exists():
                    buton.configure(fg_color=GREEN_DIM)
            except Exception:
                pass

        self.after(260, koyulastir)

    def _indir_basarisiz(self, buton, mesaj):
        kart = getattr(buton, "_owner_card", None)
        if kart:
            kart._indirme_animasyonu_durdur()
        try:
            buton.configure(state="normal", text=t("✕ Başarısız"), fg_color="#ef4444")
        except Exception:
            pass

        def eski_haline_don():
            try:
                if buton.winfo_exists():
                    buton.configure(text=t("↓ İndir"), fg_color=GREEN)
            except Exception:
                pass

        self.after(1400, eski_haline_don)
        messagebox.showerror(t("İndirme Hatası"), mesaj)


# ===========================================================================
#  Fabric Kurulum sekmesi
# ===========================================================================
class FabricFrame(ctk.CTkFrame):

    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            hdr, text=t("Fabric Kurulum"),
            font=ctk.CTkFont("Segoe UI", 24, "bold"),
            text_color=TXT_PRIMARY).pack(anchor="w")

        ctk.CTkLabel(
            hdr, text=t("Fabric Mod Loader'ı bilgisayarınıza kurun."),
            font=ctk.CTkFont("Segoe UI", 14),
            text_color=TXT_MUTED).pack(anchor="w", pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color=BORDER)
        scroll.pack(fill="both", expand=True)
        hizlandirilmis_scroll(scroll)

        installer_card = Card(scroll, border_color=GREEN_DIM)
        installer_card.pack(fill="x", pady=(0, 16))

        ic_inner = ctk.CTkFrame(installer_card, fg_color="transparent")
        ic_inner.pack(fill="x", padx=20, pady=20)

        ctk.CTkLabel(ic_inner,
                     text=t("Fabric Installer    v1.1.1"),
                     font=ctk.CTkFont("Segoe UI", 18, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="center")
        ctk.CTkLabel(ic_inner,
                     text=t("Butona tıkla — installer otomatik açılır ve kurulum başlar."),
                     font=ctk.CTkFont("Segoe UI", 13),
                     text_color=TXT_MUTED, justify="center").pack(pady=(4, 14))

        self._kur_btn = ctk.CTkButton(
            ic_inner,
            text=t("↓  Fabric'i Kur  —  Kurulumu Başlat"),
            height=48,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            text_color="#0a0a0a",
            font=ctk.CTkFont("Segoe UI", 16, "bold"),
            corner_radius=10,
            command=self._kur)
        self._kur_btn.pack(fill="x")

        self._prog_bar = ctk.CTkProgressBar(
            ic_inner, height=8,
            fg_color=BORDER, progress_color=GREEN)
        self._prog_bar.pack(fill="x", pady=(10, 0))
        self._prog_bar.set(0)

        self._fab_status = ctk.CTkLabel(
            ic_inner, text=t("fabric-installer.exe  •  Windows"),
            font=ctk.CTkFont("Segoe UI", 12),
            text_color=TXT_MUTED)
        self._fab_status.pack(pady=(5, 0))

        grid = ctk.CTkFrame(scroll, fg_color="transparent")
        grid.pack(fill="x", pady=(0, 20))
        grid.columnconfigure((0, 1), weight=1, uniform="col")

        bilgiler = [
            ("⚙", GREEN, t("Java Gereksinimi"),
             t("Fabric çalıştırmak için Java 17 veya üzeri\ngereklidir.")),
            ("✓", GREEN, t("Desteklenen Sürümler"),
             t("Fabric Loader, Minecraft 1.14 ve üzeri tüm\nsürümleri destekler.")),
            ("📁", ORANGE, t("Mods Klasörü"),
             t("Kurulum sonrasında modların\n.minecraft/mods klasörüne atılması\ngerekir.")),
            ("🎮", PURPLE, t("Fabric API"),
             t("Çoğu mod Fabric API gerektirir. Mod Marketi'nden\nFabric API'yi de indir.")),
        ]

        for i, (ic, c, bas, alt) in enumerate(bilgiler):
            r, col = divmod(i, 2)
            card = Card(grid)
            card.grid(row=r, column=col, padx=4, pady=4, sticky="nsew")
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=14)
            ctk.CTkLabel(inner, text=ic, font=ctk.CTkFont("Segoe UI", 20),
                         text_color=c).pack(anchor="w")
            ctk.CTkLabel(inner, text=bas,
                         font=ctk.CTkFont("Segoe UI", 14, "bold"),
                         text_color=c).pack(anchor="w", pady=(4, 2))
            ctk.CTkLabel(inner, text=alt,
                         font=ctk.CTkFont("Segoe UI", 12),
                         text_color=TXT_MUTED, justify="left").pack(anchor="w")

        ctk.CTkLabel(
            scroll, text=t("Kurulum Adımları"),
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
            text_color=TXT_PRIMARY).pack(anchor="w", pady=(4, 8))

        adimlar = [
            t("Bu sayfadaki yeşil butona tıkla"),
            t("Açılan pencerede Minecraft sürümünü seç"),
            t("Install butonuna bas ve bitir"),
            t("Launcher'da Fabric profilini seç ve oyna!"),
        ]
        for i, bas in enumerate(adimlar, 1):
            row = Card(scroll)
            row.pack(fill="x", pady=3)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=10)
            num = ctk.CTkFrame(inner, width=26, height=26,
                               fg_color=BG_CARD2, corner_radius=13)
            num.pack(side="left", padx=(0, 12))
            num.pack_propagate(False)
            ctk.CTkLabel(num, text=str(i),
                         font=ctk.CTkFont("Segoe UI", 13, "bold"),
                         text_color=TXT_LABEL).place(relx=.5, rely=.5, anchor="center")
            ctk.CTkLabel(inner, text=bas,
                         font=ctk.CTkFont("Segoe UI", 14),
                         text_color=TXT_PRIMARY).pack(side="left", anchor="w")

    def _kur(self):
        if not os.path.isfile(FABRIC_EXE):
            messagebox.showerror(
                "Hata",
                f"Fabric installer bulunamadı!\n\nBeklenen konum:\n{FABRIC_EXE}")
            return
        self._kur_btn.configure(state="disabled", text=t("Başlatılıyor…"))
        self._fab_status.configure(text=t("Kurulum başlatılıyor…"), text_color=GREEN)
        progress_bar_animasyonlu_set(self._prog_bar, 0.1)
        threading.Thread(target=self._kur_thread, daemon=True).start()

    def _kur_thread(self):
        try:
            self.after(0, lambda: progress_bar_animasyonlu_set(self._prog_bar, 0.3))
            self.after(0, lambda: self._fab_status.configure(
                text=t("Installer başlatılıyor…"), text_color=TXT_LABEL))

            proc = subprocess.Popen([FABRIC_EXE])

            self.after(0, lambda: progress_bar_animasyonlu_set(self._prog_bar, 0.6))
            self.after(0, lambda: self._fab_status.configure(
                text=t("Installer penceresi açıldı, bekleniyor…"), text_color=TXT_LABEL))

            proc.wait()

            self.after(0, lambda: progress_bar_animasyonlu_set(self._prog_bar, 1.0))
            self.after(0, lambda: self._fab_status.configure(
                text=t("✓  Kurulum tamamlandı!"), text_color=GREEN))

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Hata", str(e)))
            self.after(0, lambda: self._fab_status.configure(
                text=t("Hata oluştu."), text_color="#ef4444"))
            self.after(0, lambda: progress_bar_animasyonlu_set(self._prog_bar, 0))
        finally:
            self.after(500, lambda: self._kur_btn.configure(
                state="normal", text=t("↓  Fabric'i Kur  —  Kurulumu Başlat")))


# ===========================================================================
#  Sürüm Seçme Penceresi
# ===========================================================================
class SurumSecPenceresi(ctk.CTkToplevel):
    def __init__(self, master, baslik: str, project_slug: str,
                 loader: str, on_secildi, **kw):
        super().__init__(master, **kw)
        self.title(baslik)
        self.geometry("525x560")
        self.minsize(460, 380)
        self.configure(fg_color=BG_MAIN)
        self.transient(master)
        self.grab_set()

        self._project_slug = project_slug
        self._loader = loader
        self._on_secildi = on_secildi

        self._build(baslik)
        self.after(100, self._yukle)

    def _build(self, baslik):
        ctk.CTkLabel(self, text=baslik,
                     font=ctk.CTkFont("Segoe UI", 20, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(self, text=t("Fabric uyumlu sürümler — Modrinth"),
                     font=ctk.CTkFont("Segoe UI", 13),
                     text_color=TXT_MUTED).pack(anchor="w", padx=20, pady=(0, 14))

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color=BORDER)
        self._scroll.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        hizlandirilmis_scroll(self._scroll)

        self._durum_lbl = ctk.CTkLabel(
            self._scroll, text=t("Sürümler yükleniyor…"),
            font=ctk.CTkFont("Segoe UI", 14),
            text_color=TXT_MUTED)
        self._durum_lbl.pack(pady=30)

    def _yukle(self):
        def worker():
            versiyonlar = mrapi.get_project_versions(
                self._project_slug, loader=self._loader)
            self.after(0, lambda: self._goster(versiyonlar))

        threading.Thread(target=worker, daemon=True).start()

    def _goster(self, versiyonlar: list):
        self._durum_lbl.destroy()

        if not versiyonlar:
            ctk.CTkLabel(
                self._scroll,
                text=t("⚠ Sürüm listesi alınamadı.\nİnternet bağlantını kontrol et."),
                font=ctk.CTkFont("Segoe UI", 14),
                text_color="#ef4444").pack(pady=30)
            return

        gorulen_mc_surumleri = set()
        gosterilecekler = []
        for v in versiyonlar:
            mc_list = v.get("game_versions", [])
            yeni_mc = [m for m in mc_list if m not in gorulen_mc_surumleri]
            if not yeni_mc:
                continue
            for m in yeni_mc:
                gorulen_mc_surumleri.add(m)
            gosterilecekler.append((yeni_mc, v))

        if not gosterilecekler:
            ctk.CTkLabel(
                self._scroll, text=t("Uygun sürüm bulunamadı."),
                font=ctk.CTkFont("Segoe UI", 14),
                text_color=TXT_MUTED).pack(pady=30)
            return

        for mc_list, v in gosterilecekler:
            self._satir_olustur(mc_list, v)

    def _satir_olustur(self, mc_list, version_obj):
        row = Card(self._scroll)
        row.pack(fill="x", pady=3)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)

        ad = version_obj.get("version_number", "?")
        mc_metin = ", ".join(mc_list[:3]) + ("…" if len(mc_list) > 3 else "")

        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text=ad,
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=TXT_PRIMARY, anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=f"MC: {mc_metin}",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED, anchor="w").pack(anchor="w")

        btn = ctk.CTkButton(
            inner, text=t("İndir"), width=70, height=30,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            text_color="#0a0a0a",
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            corner_radius=6)
        btn.pack(side="right")
        btn.configure(command=lambda b=btn, v=version_obj: self._secildi(v, b))

    def _secildi(self, version_obj, buton):
        buton.configure(state="disabled", text="…")
        dosya = mrapi.get_primary_file(version_obj)
        if not dosya:
            messagebox.showerror("Hata", t("İndirilecek dosya bulunamadı."))
            buton.configure(state="normal", text=t("İndir"))
            return

        def worker():
            os.makedirs(SHADER_FILES, exist_ok=True)
            hedef = os.path.join(SHADER_FILES, dosya["filename"])
            basarili = mrapi.download_file(dosya["url"], hedef)
            self.after(0, lambda: self._indirme_bitti(basarili, hedef, buton))

        threading.Thread(target=worker, daemon=True).start()

    def _indirme_bitti(self, basarili, hedef, buton):
        if basarili:
            self._on_secildi(hedef)
            self.destroy()
        else:
            messagebox.showerror("Hata", t("İndirme başarısız oldu."))
            buton.configure(state="normal", text=t("İndir"))


# ===========================================================================
#  Hazır Shader Paketi Seçme Penceresi
# ===========================================================================
class ShaderPaketSecPenceresi(ctk.CTkToplevel):
    SAYFA_BOYUTU = 15

    def __init__(self, master, on_secildi, **kw):
        super().__init__(master, **kw)
        self._on_secildi = on_secildi
        self._offset = 0
        self._daha_var_mi = True
        self.title(t("Hazır Shader Paketleri"))
        self.geometry("600x680")
        self.minsize(500, 460)
        self.configure(fg_color=BG_MAIN)
        self.transient(master)
        self.grab_set()
        self._build()
        self.after(100, lambda: self._ara(yeni=True))

    def _build(self):
        ctk.CTkLabel(self, text=t("Hazır Shader Paketleri"),
                     font=ctk.CTkFont("Segoe UI", 20, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(self, text=t("Modrinth üzerindeki shader paketlerinden seç"),
                     font=ctk.CTkFont("Segoe UI", 13),
                     text_color=TXT_MUTED).pack(anchor="w", padx=20, pady=(0, 10))

        arama_satiri = ctk.CTkFrame(self, fg_color="transparent")
        arama_satiri.pack(fill="x", padx=20, pady=(0, 8))
        self._arama = ctk.CTkEntry(
            arama_satiri, placeholder_text=t("Shader paketi ara…"),
            height=34, fg_color=BG_CARD2, border_color=BORDER,
            text_color=TXT_PRIMARY, font=ctk.CTkFont("Segoe UI", 13))
        self._arama.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._arama.bind("<Return>", lambda e: self._ara(yeni=True))
        ctk.CTkButton(
            arama_satiri, text=t("Ara"), width=70, height=34,
            fg_color=GREEN, hover_color=GREEN_HOVER, text_color="#0a0a0a",
            font=ctk.CTkFont("Segoe UI", 13, "bold"), corner_radius=8,
            command=lambda: self._ara(yeni=True)).pack(side="left")

        filtre_satiri = ctk.CTkFrame(self, fg_color="transparent")
        filtre_satiri.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(filtre_satiri, text=t("Sırala:"),
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TXT_MUTED).pack(side="left", padx=(0, 6))
        self._sort_label_to_key = {ad: anahtar for anahtar, ad in mrapi.SORT_OPTIONS}
        self._sort_var = ctk.StringVar(value=mrapi.SORT_OPTIONS[1][1])
        self._sort_combo = ToggleOptionMenu(
            filtre_satiri, values=[ad for _k, ad in mrapi.SORT_OPTIONS],
            variable=self._sort_var, width=150, height=30,
            fg_color=BG_CARD2, button_color=GREEN, button_hover_color=GREEN_HOVER,
            dropdown_fg_color=BG_CARD2, dropdown_hover_color=BG_HOVER,
            text_color=TXT_PRIMARY, dropdown_text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 12),
            command=lambda _v: self._ara(yeni=True))
        self._sort_combo.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(filtre_satiri, text=t("Sürüm:"),
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TXT_MUTED).pack(side="left", padx=(0, 6))
        self._versiyon_var = ctk.StringVar(value="Hepsi")
        self._versiyon_combo = ToggleOptionMenu(
            filtre_satiri, values=["Hepsi"] + mrapi.MC_VERSIONS_SIMPLE,
            variable=self._versiyon_var, width=110, height=30,
            fg_color=BG_CARD2, button_color=GREEN, button_hover_color=GREEN_HOVER,
            dropdown_fg_color=BG_CARD2, dropdown_hover_color=BG_HOVER,
            text_color=TXT_PRIMARY, dropdown_text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 12),
            command=lambda _v: self._ara(yeni=True))
        self._versiyon_combo.pack(side="left")

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color=BORDER)
        self._scroll.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._scroll_yenile = hizlandirilmis_scroll(self._scroll)

        self._durum_lbl = ctk.CTkLabel(
            self._scroll, text=t("Shader paketleri yükleniyor…"),
            font=ctk.CTkFont("Segoe UI", 14),
            text_color=TXT_MUTED)
        self._durum_lbl.pack(pady=30)
        self._daha_fazla_btn = None

    def _gecerli_sort(self):
        return self._sort_label_to_key.get(self._sort_var.get(), "relevance")

    def _gecerli_versiyon(self):
        v = self._versiyon_var.get()
        return None if v == "Hepsi" else v

    def _ara(self, yeni=False):
        if yeni:
            self._offset = 0
        sorgu = self._arama.get().strip()
        index = self._gecerli_sort()
        versiyon = self._gecerli_versiyon()

        if yeni:
            for w in self._scroll.winfo_children():
                w.destroy()
            self._daha_fazla_btn = None
            self._durum_lbl = ctk.CTkLabel(
                self._scroll, text=t("Aranıyor…"),
                font=ctk.CTkFont("Segoe UI", 14),
                text_color=TXT_MUTED)
            self._durum_lbl.pack(pady=30)

        def worker():
            sonuc = mrapi.search_mods(
                query=sorgu, loader="hepsi", game_version=versiyon,
                index=index, offset=self._offset, limit=self.SAYFA_BOYUTU,
                project_type="shader")
            self.after(0, lambda: self._goster(sonuc, yeni))

        threading.Thread(target=worker, daemon=True).start()

    def _daha_fazla(self):
        self._ara(yeni=False)

    def _goster(self, sonuc: dict, yeni: bool):
        try:
            if yeni and self._durum_lbl.winfo_exists():
                self._durum_lbl.destroy()
        except Exception:
            pass

        if sonuc.get("error"):
            if yeni:
                ctk.CTkLabel(
                    self._scroll,
                    text=f"⚠ {t('Bağlantı hatası')}: {sonuc['error']}",
                    font=ctk.CTkFont("Segoe UI", 14),
                    text_color="#ef4444").pack(pady=30)
            return

        hits = sonuc.get("hits", [])
        toplam = sonuc.get("total_hits", 0)

        if yeni and not hits:
            ctk.CTkLabel(
                self._scroll, text=t("Sonuç bulunamadı."),
                font=ctk.CTkFont("Segoe UI", 14),
                text_color=TXT_MUTED).pack(pady=30)
            return

        if self._daha_fazla_btn is not None:
            try:
                self._daha_fazla_btn.destroy()
            except Exception:
                pass
            self._daha_fazla_btn = None

        for paket in hits:
            self._paket_karti(paket)

        self._offset += len(hits)
        self._daha_var_mi = self._offset < toplam

        if self._daha_var_mi:
            self._daha_fazla_btn = ctk.CTkButton(
                self._scroll, text=t("Daha Fazla Göster (+15)"), height=34,
                fg_color=BG_CARD2, hover_color=BG_HOVER,
                border_width=1, border_color=BORDER,
                text_color=TXT_PRIMARY,
                font=ctk.CTkFont("Segoe UI", 13),
                corner_radius=8,
                command=self._daha_fazla)
            self._daha_fazla_btn.pack(pady=12)

        if self._scroll_yenile:
            self.after(50, self._scroll_yenile)

    def _paket_karti(self, paket: dict):
        row = Card(self._scroll)
        row.pack(fill="x", pady=4)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)

        icon_frame = ctk.CTkFrame(
            inner, width=48, height=48, fg_color=BG_CARD2, corner_radius=10)
        icon_frame.pack(side="left", padx=(0, 12))
        icon_frame.pack_propagate(False)
        icon_lbl = ctk.CTkLabel(icon_frame, text="✦",
                                font=ctk.CTkFont("Segoe UI", 20),
                                text_color=TXT_MUTED)
        icon_lbl.place(relx=.5, rely=.5, anchor="center")
        self._ikon_yukle_async(paket, icon_lbl)

        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)
        baslik = paket.get("title") or paket.get("name", "?")
        ctk.CTkLabel(info, text=baslik,
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=TXT_PRIMARY, anchor="w").pack(anchor="w")
        aciklama = (paket.get("description") or "")[:110]
        ctk.CTkLabel(info, text=aciklama,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=TXT_LABEL, anchor="w",
                     wraplength=320, justify="left").pack(anchor="w", pady=(2, 0))

        btn = ctk.CTkButton(
            inner, text=t("Kur"), width=78, height=32,
            fg_color=GREEN, hover_color=GREEN_HOVER, text_color="#0a0a0a",
            font=ctk.CTkFont("Segoe UI", 12, "bold"), corner_radius=6)
        btn.pack(side="right")
        slug = paket.get("slug") or paket.get("project_id") or paket.get("id")
        btn.configure(command=lambda b=btn, s=slug: self._paket_secildi(s, b))

    def _ikon_yukle_async(self, paket: dict, icon_lbl):
        url = paket.get("icon_url")
        if not url or not _PIL_OK:
            return

        def worker():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    veri = resp.read()
                img = Image.open(io.BytesIO(veri)).convert("RGBA")
                img = img.resize((48, 48), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(48, 48))
                self.after(0, lambda: self._ikon_uygula(icon_lbl, ctk_img))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _ikon_uygula(self, icon_lbl, ctk_img):
        try:
            icon_lbl.configure(image=ctk_img, text="")
            icon_lbl.image = ctk_img
        except Exception:
            pass

    def _paket_secildi(self, slug: str, buton):
        buton.configure(state="disabled", text="…")

        def worker():
            versiyonlar = mrapi.get_project_versions(slug, loader=None)
            if not versiyonlar:
                self.after(0, lambda: self._hata(buton, t("Sürüm bulunamadı.")))
                return
            dosya = mrapi.get_primary_file(versiyonlar[0])
            if not dosya:
                self.after(0, lambda: self._hata(buton, t("İndirilecek dosya bulunamadı.")))
                return
            os.makedirs(SHADER_FILES, exist_ok=True)
            hedef = os.path.join(SHADER_FILES, dosya["filename"])
            basarili = mrapi.download_file(dosya["url"], hedef)
            if basarili:
                self.after(0, lambda: self._basarili(hedef, buton))
            else:
                self.after(0, lambda: self._hata(buton, t("İndirme başarısız.")))

        threading.Thread(target=worker, daemon=True).start()

    def _basarili(self, hedef, buton):
        self._on_secildi(hedef)
        self.destroy()

    def _hata(self, buton, mesaj):
        messagebox.showerror("Hata", mesaj)
        try:
            buton.configure(state="normal", text=t("Kur"))
        except Exception:
            pass


# ===========================================================================
#  Shader Kurulum sekmesi
# ===========================================================================
class ShaderFrame(ctk.CTkFrame):
    SODIUM_SLUG = "sodium"
    IRIS_SLUG   = "iris"

    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._build()

    def _find_sodium(self):
        if not os.path.isdir(SHADER_FILES): return None
        hits = glob.glob(os.path.join(SHADER_FILES, "sodium*.jar"))
        return hits[0] if hits else None

    def _find_sodium_tumu(self):
        if not os.path.isdir(SHADER_FILES): return []
        return glob.glob(os.path.join(SHADER_FILES, "sodium*.jar"))

    def _find_iris(self):
        if not os.path.isdir(SHADER_FILES): return None
        hits = glob.glob(os.path.join(SHADER_FILES, "iris*.jar"))
        return hits[0] if hits else None

    def _find_iris_tumu(self):
        if not os.path.isdir(SHADER_FILES): return []
        return glob.glob(os.path.join(SHADER_FILES, "iris*.jar"))

    def _find_shader_pack(self):
        if not os.path.isdir(SHADER_FILES): return None
        hits = glob.glob(os.path.join(SHADER_FILES, "*.zip"))
        return hits[0] if hits else None

    def _find_shader_pack_tumu(self):
        if not os.path.isdir(SHADER_FILES): return []
        return glob.glob(os.path.join(SHADER_FILES, "*.zip"))

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(hdr, text=t("Shader Kurulum"),
                     font=ctk.CTkFont("Segoe UI", 24, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(hdr, text=t("Sodium + Iris Shaders + Shader Paketi otomatik kurulumu"),
                     font=ctk.CTkFont("Segoe UI", 14),
                     text_color=TXT_MUTED).pack(anchor="w", pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color=BORDER)
        scroll.pack(fill="both", expand=True)
        hizlandirilmis_scroll(scroll)

        info_card = Card(scroll, border_color=GREEN_DIM)
        info_card.pack(fill="x", pady=(0, 16))
        info_inner = ctk.CTkFrame(info_card, fg_color="transparent")
        info_inner.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(info_inner, text=t("🌟  Shader Nedir?"),
                     font=ctk.CTkFont("Segoe UI", 16, "bold"),
                     text_color=PURPLE).pack(anchor="w", pady=(0, 10))
        ctk.CTkLabel(info_inner,
                     text=t("Shader paketleri Minecraft'ın görselliğini dramatik biçimde iyileştirir: "
                             "gerçekçi ışık ve gölgeler, su yansımaları, dinamik bulutlar ve çok daha fazlası.\n\n"
                             "Neden Sodium + Iris Shaders kullanıyoruz?\n"
                             "Optifine FPS'i düşürürken Sodium %50-200 arası FPS artışı sağlar. "
                             "Iris Shaders ise Sodium ile uyumlu çalışan shader desteği ekler.\n\n"
                             "⌨  Kısayollar:  K → Shader aç/kapat    I → Shader paketini değiştir"),
                     font=ctk.CTkFont("Segoe UI", 13),
                     text_color=TXT_LABEL, justify="left", anchor="w",
                     wraplength=700).pack(anchor="w")

        self._status_card = Card(scroll)
        self._status_card.pack(fill="x", pady=(0, 16))
        self._render_status_card()

        prog_outer = ctk.CTkFrame(scroll, fg_color="transparent")
        prog_outer.pack(fill="x", pady=(0, 10))

        self._prog_bar = ctk.CTkProgressBar(
            prog_outer, height=8, fg_color=BORDER, progress_color=PURPLE)
        self._prog_bar.pack(fill="x")
        self._prog_bar.set(0)

        self._status_lbl = ctk.CTkLabel(
            prog_outer, text=t("Hazır — kuruluma başlamak için butona bas."),
            font=ctk.CTkFont("Segoe UI", 13), text_color=TXT_MUTED)
        self._status_lbl.pack(anchor="w", pady=(6, 0))

        self._kur_btn = ctk.CTkButton(
            scroll,
            text=t("🌟  Sodium + Shader + İris Shaders'ı Kur"),
            height=50,
            fg_color=PURPLE, hover_color=PURPLE_HOVER,
            text_color="white",
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
            corner_radius=12,
            command=self._kur)
        self._kur_btn.pack(fill="x", pady=(4, 20))

        ctk.CTkLabel(scroll, text=t("Kurulum Ne Yapar?"),
                     font=ctk.CTkFont("Segoe UI", 17, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 8))

        adimlar = [
            ("1", t("Sodium .jar"), t("shader_files/sodium*.jar  →  .minecraft/mods/  kopyalanır")),
            ("2", t("Iris Shaders .jar"), t("shader_files/iris*.jar  →  .minecraft/mods/  kopyalanır")),
            ("3", t("Shader Paketi"), t("shader_files/*.zip  →  .minecraft/shaderpacks/  kopyalanır")),
            ("4", t("Oyunu Başlat"), t("Minecraft'ı Fabric profiliyle aç, Options → Video → Shaders'a gir")),
            ("5", t("Shader Seç"), t("Shader listesinden paketi seç, uygulamak için 'Done' butonuna bas")),
        ]
        for num, bas, alt in adimlar:
            row = Card(scroll)
            row.pack(fill="x", pady=3)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=10)
            nb = ctk.CTkFrame(inner, width=26, height=26,
                              fg_color=PURPLE, corner_radius=13)
            nb.pack(side="left", padx=(0, 12))
            nb.pack_propagate(False)
            ctk.CTkLabel(nb, text=num,
                         font=ctk.CTkFont("Segoe UI", 13, "bold"),
                         text_color="white").place(relx=.5, rely=.5, anchor="center")
            info2 = ctk.CTkFrame(inner, fg_color="transparent")
            info2.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(info2, text=bas,
                         font=ctk.CTkFont("Segoe UI", 14, "bold"),
                         text_color=TXT_PRIMARY, anchor="w").pack(anchor="w")
            ctk.CTkLabel(info2, text=alt,
                         font=ctk.CTkFont("Segoe UI", 12),
                         text_color=TXT_MUTED, anchor="w").pack(anchor="w")

    def _render_status_card(self):
        for w in self._status_card.winfo_children():
            w.destroy()
        sc_inner = ctk.CTkFrame(self._status_card, fg_color="transparent")
        sc_inner.pack(fill="x", padx=18, pady=14)
        ctk.CTkLabel(sc_inner, text=t("📂  shader_files/ klasörü"),
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 10))
        self._dosya_satiri(sc_inner, "Sodium:", self._find_sodium(),
                            t("sodium*.jar bulunamadı"),
                            t("Sürüm Değiştir"), self._sodium_surum_degistir)
        self._dosya_satiri(sc_inner, "Iris Shaders:", self._find_iris(),
                            t("iris*.jar bulunamadı"),
                            t("Sürüm Değiştir"), self._iris_surum_degistir)
        self._dosya_satiri(sc_inner, t("Shader paketi:"), self._find_shader_pack(),
                            t("*.zip bulunamadı"),
                            t("Değiştir"), self._shader_pack_degistir)
        ctk.CTkLabel(sc_inner, text=f"{t('Klasör yolu')}:  {SHADER_FILES}",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED).pack(anchor="w", pady=(10, 0))

    def _dosya_satiri(self, parent, etiket, dosya_yolu, bos_metin, buton_text, buton_command):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ok = dosya_yolu is not None
        ad = os.path.basename(dosya_yolu) if ok else bos_metin
        ctk.CTkLabel(row, text="✓" if ok else "✗",
                     font=ctk.CTkFont("Segoe UI", 16, "bold"),
                     text_color=GREEN if ok else "#ef4444", width=20).pack(side="left")
        ctk.CTkLabel(row, text=f"{etiket}  ",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=TXT_LABEL).pack(side="left")
        ctk.CTkLabel(row, text=ad,
                     font=ctk.CTkFont("Segoe UI", 13),
                     text_color=TXT_MUTED).pack(side="left", padx=(0, 10))
        ctk.CTkButton(row, text=buton_text, width=110, height=26,
                      fg_color=BG_CARD2, hover_color=BG_HOVER,
                      border_width=1, border_color=BORDER, text_color=TXT_PRIMARY,
                      font=ctk.CTkFont("Segoe UI", 12), corner_radius=6,
                      command=buton_command).pack(side="right")

    def _sodium_surum_degistir(self):
        def secildi(yeni_yol):
            for eski in self._find_sodium_tumu():
                if os.path.abspath(eski) != os.path.abspath(yeni_yol):
                    try: os.remove(eski)
                    except Exception: pass
            self._render_status_card()
            messagebox.showinfo(t("Başarılı"), t("Sodium sürümü güncellendi."))
        SurumSecPenceresi(self, t("Sodium Sürüm Seç"), self.SODIUM_SLUG,
                          "fabric", on_secildi=secildi)

    def _iris_surum_degistir(self):
        def secildi(yeni_yol):
            for eski in self._find_iris_tumu():
                if os.path.abspath(eski) != os.path.abspath(yeni_yol):
                    try: os.remove(eski)
                    except Exception: pass
            self._render_status_card()
            messagebox.showinfo(t("Başarılı"), t("Iris Shaders sürümü güncellendi."))
        SurumSecPenceresi(self, t("Iris Shaders Sürüm Seç"), self.IRIS_SLUG,
                          "fabric", on_secildi=secildi)

    def _shader_pack_degistir(self):
        secim = ctk.CTkToplevel(self)
        secim.title(t("Shader Paketi Değiştir"))
        secim.geometry("380x220")
        secim.minsize(340, 200)
        secim.configure(fg_color=BG_MAIN)
        secim.transient(self.winfo_toplevel())
        secim.grab_set()

        ctk.CTkLabel(secim, text=t("Shader Paketini Nasıl Eklemek İstersin?"),
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY, wraplength=320,
                     justify="left").pack(padx=20, pady=(22, 18))

        def hazir_listeyi_ac():
            secim.destroy()
            ShaderPaketSecPenceresi(self, on_secildi=self._shader_pack_indirildi)

        def bilgisayardan_sec():
            secim.destroy()
            self._shader_pack_dosyadan_sec()

        ctk.CTkButton(secim, text=t("✦  Hazır Shader Paketlerinden Seç"), height=42,
                      fg_color=GREEN, hover_color=GREEN_HOVER, text_color="#0a0a0a",
                      font=ctk.CTkFont("Segoe UI", 13, "bold"), corner_radius=8,
                      command=hazir_listeyi_ac).pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkButton(secim, text=t("📁  Bilgisayardan Dosya Seç"), height=42,
                      fg_color=BG_CARD2, hover_color=BG_HOVER,
                      border_width=1, border_color=BORDER, text_color=TXT_PRIMARY,
                      font=ctk.CTkFont("Segoe UI", 13), corner_radius=8,
                      command=bilgisayardan_sec).pack(fill="x", padx=20, pady=(0, 10))

    def _shader_pack_dosyadan_sec(self):
        path = filedialog.askopenfilename(
            title=t("Shader paketi seçin (.zip)"),
            filetypes=[("Zip dosyaları", "*.zip")])
        if not path:
            return
        try:
            os.makedirs(SHADER_FILES, exist_ok=True)
            hedef = os.path.join(SHADER_FILES, os.path.basename(path))
            for eski in self._find_shader_pack_tumu():
                if os.path.abspath(eski) != os.path.abspath(hedef):
                    try: os.remove(eski)
                    except Exception: pass
            shutil.copy2(path, hedef)
            self._render_status_card()
            messagebox.showinfo(t("Başarılı"), t("Shader paketi güncellendi."))
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _shader_pack_indirildi(self, yeni_yol):
        for eski in self._find_shader_pack_tumu():
            if os.path.abspath(eski) != os.path.abspath(yeni_yol):
                try: os.remove(eski)
                except Exception: pass
        self._render_status_card()
        messagebox.showinfo(t("Başarılı"), t("Shader paketi kuruldu."))

    def _kur(self):
        sodium_file = self._find_sodium()
        iris_file = self._find_iris()
        shader_file = self._find_shader_pack()

        eksik = []
        if not sodium_file: eksik.append(t("• shader_files/ içinde sodium*.jar bulunamadı"))
        if not iris_file:   eksik.append(t("• shader_files/ içinde iris*.jar bulunamadı"))
        if not shader_file: eksik.append(t("• shader_files/ içinde *.zip bulunamadı"))

        if eksik:
            messagebox.showerror(t("Dosya Eksik"),
                t("Kurulum için gerekli dosyalar bulunamadı:") + "\n\n" +
                "\n".join(eksik) + f"\n\n{t('Klasör')}: {SHADER_FILES}")
            return

        self._kur_btn.configure(state="disabled", text=t("Kuruluyor…"))
        progress_bar_animasyonlu_set(self._prog_bar, 0.05)
        self._status_lbl.configure(text=t("Kurulum başlatıldı…"), text_color=TXT_LABEL)

        threading.Thread(target=self._kur_thread,
                         args=(sodium_file, iris_file, shader_file),
                         daemon=True).start()

    def _kur_thread(self, sodium_src, iris_src, shader_src):
        def ui(prog, msg, color=TXT_LABEL):
            self.after(0, lambda: progress_bar_animasyonlu_set(self._prog_bar, prog))
            self.after(0, lambda: self._status_lbl.configure(text=msg, text_color=color))

        try:
            ui(0.1, t("Minecraft dizini kontrol ediliyor…"))
            if os.path.isdir(MC_DIR):
                mods_hedef = MC_MODS_DIR
                shaders_hedef = MC_SHADERS_DIR
            else:
                self.after(0, lambda: self._sor_dizin(sodium_src, iris_src, shader_src))
                return

            os.makedirs(mods_hedef, exist_ok=True)
            os.makedirs(shaders_hedef, exist_ok=True)

            ui(0.25, t("Sodium kopyalanıyor → mods/"))
            shutil.copy2(sodium_src, os.path.join(mods_hedef, os.path.basename(sodium_src)))
            ui(0.5, t("Sodium kopyalandı ✓"))

            ui(0.6, t("Iris Shaders kopyalanıyor → mods/"))
            shutil.copy2(iris_src, os.path.join(mods_hedef, os.path.basename(iris_src)))
            ui(0.8, t("Iris Shaders kopyalandı ✓"))

            ui(0.9, t("Shader paketi kopyalanıyor → shaderpacks/"))
            shutil.copy2(shader_src, os.path.join(shaders_hedef, os.path.basename(shader_src)))
            ui(1.0, t("✓  Kurulum tamamlandı!"), GREEN)

            self.after(0, lambda: messagebox.showinfo(
                t("Başarılı 🎉"),
                f"{t('Kurulum tamamlandı')}!\n\n"
                f"Sodium + Iris Shaders  →  {mods_hedef}\n"
                f"{t('Shader paketi')}  →  {shaders_hedef}\n\n"
                f"{t('Minecraft Fabric profiliyle baslat, ardindan Options - Video - Shaders yolunu izle.')}"))

        except Exception as e:
            ui(0.0, f"{t('Hata')}: {e}", "#ef4444")
            self.after(0, lambda: messagebox.showerror(t("Kurulum Hatası"), str(e)))
        finally:
            self.after(0, lambda: self._kur_btn.configure(
                state="normal", text=t("🌟  Sodium + Shader + İris Shaders'ı Kur")))

    def _sor_dizin(self, sodium_src, iris_src, shader_src):
        messagebox.showwarning(t("Minecraft Bulunamadı"),
            t(".minecraft klasörü otomatik bulunamadı.\n"
              "Sonraki iki pencerede önce 'mods', sonra 'shaderpacks' klasörünü seç."))

        mods_hedef = filedialog.askdirectory(title=t("mods klasörünü seçin"))
        if not mods_hedef:
            self._status_lbl.configure(text=t("İptal edildi."), text_color=TXT_MUTED)
            self._kur_btn.configure(state="normal", text=t("🌟  Sodium + Shader + İris Shaders'ı Kur"))
            return

        shaders_hedef = filedialog.askdirectory(title=t("shaderpacks klasörünü seçin"))
        if not shaders_hedef:
            self._status_lbl.configure(text=t("İptal edildi."), text_color=TXT_MUTED)
            self._kur_btn.configure(state="normal", text=t("🌟  Sodium + Shader + İris Shaders'ı Kur"))
            return

        def ui(prog, msg, color=TXT_LABEL):
            self.after(0, lambda: progress_bar_animasyonlu_set(self._prog_bar, prog))
            self.after(0, lambda: self._status_lbl.configure(text=msg, text_color=color))

        def worker():
            try:
                os.makedirs(mods_hedef, exist_ok=True)
                os.makedirs(shaders_hedef, exist_ok=True)
                ui(0.3, t("Sodium kopyalanıyor…"))
                shutil.copy2(sodium_src, os.path.join(mods_hedef, os.path.basename(sodium_src)))
                ui(0.6, t("Iris Shaders kopyalanıyor…"))
                shutil.copy2(iris_src, os.path.join(mods_hedef, os.path.basename(iris_src)))
                ui(0.85, t("Shader paketi kopyalanıyor…"))
                shutil.copy2(shader_src, os.path.join(shaders_hedef, os.path.basename(shader_src)))
                ui(1.0, t("✓  Kurulum tamamlandı!"), GREEN)
                self.after(0, lambda: messagebox.showinfo(t("Başarılı 🎉"), t("Kurulum tamamlandı!")))
            except Exception as e:
                ui(0.0, f"{t('Hata')}: {e}", "#ef4444")
                self.after(0, lambda: messagebox.showerror("Hata", str(e)))
            finally:
                self.after(0, lambda: self._kur_btn.configure(
                    state="normal", text=t("🌟  Sodium + Shader + İris Shaders'ı Kur")))

        threading.Thread(target=worker, daemon=True).start()


# ===========================================================================
#  Ayarlar sekmesi
# ===========================================================================
class AyarlarFrame(ctk.CTkFrame):

    def __init__(self, master, on_tema_degisti=None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._on_tema_degisti = on_tema_degisti
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text=t("Ayarlar"),
                     font=ctk.CTkFont("Segoe UI", 24, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(self, text=t("Uygulamanın görünümünü ve davranışını özelleştir"),
                     font=ctk.CTkFont("Segoe UI", 14),
                     text_color=TXT_MUTED).pack(anchor="w", pady=(0, 18))

        scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color=BORDER)
        scroll.pack(fill="both", expand=True)
        hizlandirilmis_scroll(scroll)

        # ── Tema kartı ───────────────────────────────────────────────────
        tema_kart = Card(scroll)
        tema_kart.pack(fill="x", pady=(0, 12))
        ti = ctk.CTkFrame(tema_kart, fg_color="transparent")
        ti.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(ti, text=t("🎨  Renk Teması"),
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(ti, text=t("Vurgu rengini (butonlar, seçili kenarlıklar) değiştirir."),
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED, justify="left").pack(anchor="w", pady=(0, 12))

        tema_grid = ctk.CTkFrame(ti, fg_color="transparent")
        tema_grid.pack(fill="x")
        for c in range(3):
            tema_grid.columnconfigure(c, weight=1, uniform="tema")

        self._tema_anahtar = AYARLAR.get("tema", "yesil")
        self._tema_butonlari = {}
        for i, (anahtar, palet) in enumerate(_TEMA_PALETLERI.items()):
            r, c = divmod(i, 3)
            self._tema_butonlari[anahtar] = self._tema_dugmesi_olustur(
                tema_grid, anahtar, palet, r, c)

        ctk.CTkButton(
            ti, text=t("🎨  Özel Renk Seç…"), height=32,
            fg_color=BG_CARD2, hover_color=BG_HOVER,
            border_width=1, border_color=BORDER, text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 12), corner_radius=8,
            command=self._ozel_renk_sec).pack(fill="x", pady=(10, 0))

        # ── Arka Plan kartı ──────────────────────────────────────────────
        ap_kart = Card(scroll)
        ap_kart.pack(fill="x", pady=(0, 12))
        api = ctk.CTkFrame(ap_kart, fg_color="transparent")
        api.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(api, text=t("🖼  Arka Plan"),
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(api, text=t("Uygulamanın genel arka plan rengini değiştirir."),
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED, justify="left").pack(anchor="w", pady=(0, 12))

        ap_grid = ctk.CTkFrame(api, fg_color="transparent")
        ap_grid.pack(fill="x")
        for c in range(3):
            ap_grid.columnconfigure(c, weight=1, uniform="ap")

        self._ap_anahtar = AYARLAR.get("arkaplan", "koyu_gri")
        self._ap_butonlari = {}
        for i, (anahtar, palet) in enumerate(_ARKAPLAN_PALETLERI.items()):
            r, c = divmod(i, 3)
            self._ap_butonlari[anahtar] = self._ap_dugmesi_olustur(
                ap_grid, anahtar, palet, r, c)

        ctk.CTkButton(
            api, text=t("🖼  Özel Arka Plan Rengi Seç…"), height=32,
            fg_color=BG_CARD2, hover_color=BG_HOVER,
            border_width=1, border_color=BORDER, text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 12), corner_radius=8,
            command=self._ozel_arkaplan_sec).pack(fill="x", pady=(10, 0))

        # ── Mod Marketi indirme hedefi ───────────────────────────────────
        hedef_kart = Card(scroll)
        hedef_kart.pack(fill="x", pady=(0, 12))
        hi = ctk.CTkFrame(hedef_kart, fg_color="transparent")
        hi.pack(fill="x", padx=18, pady=16)

        ust = ctk.CTkFrame(hi, fg_color="transparent")
        ust.pack(fill="x")
        sol = ctk.CTkFrame(ust, fg_color="transparent")
        sol.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(sol, text=t("↓  Mod Marketi: İndirme Hedefi"),
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(sol,
                     text=t("Kapalı → Modlar sekmesine eklenir.\nAçık → İndirilenler klasörüne iner."),
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED, justify="left").pack(anchor="w")

        baslangic = AYARLAR.get("market_indirme_hedefi", "modlar") == "indirilenler"
        self._indirme_switch = ctk.CTkSwitch(
            ust, text="", width=46,
            progress_color=GREEN, button_color="white",
            command=self._indirme_hedefi_degisti)
        if baslangic:
            self._indirme_switch.select()
        else:
            self._indirme_switch.deselect()
        self._indirme_switch.pack(side="right")

        # ── Modları Yükle hedefi ─────────────────────────────────────────
        yukle_kart = Card(scroll)
        yukle_kart.pack(fill="x", pady=(0, 12))
        yi = ctk.CTkFrame(yukle_kart, fg_color="transparent")
        yi.pack(fill="x", padx=18, pady=16)

        ust3 = ctk.CTkFrame(yi, fg_color="transparent")
        ust3.pack(fill="x")
        sol3 = ctk.CTkFrame(ust3, fg_color="transparent")
        sol3.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(sol3, text=t("📂  Modlar: İndirilenler'e Yükle"),
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(sol3,
                     text=t("Kapalı → .minecraft/mods klasörüne kopyalanır.\nAçık → İndirilenler klasörüne kopyalanır."),
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED, justify="left").pack(anchor="w")

        yukle_baslangic = AYARLAR.get("modlari_yukle_hedefi", "minecraft") == "indirilenler"
        self._yukle_switch = ctk.CTkSwitch(
            ust3, text="", width=46,
            progress_color=GREEN, button_color="white",
            command=self._yukle_hedefi_degisti)
        if yukle_baslangic:
            self._yukle_switch.select()
        else:
            self._yukle_switch.deselect()
        self._yukle_switch.pack(side="right")

        # ── Kaydırma hızı ────────────────────────────────────────────────
        scroll_kart = Card(scroll)
        scroll_kart.pack(fill="x", pady=(0, 12))
        si = ctk.CTkFrame(scroll_kart, fg_color="transparent")
        si.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(si, text=t("🖱  Kaydırma Hızı (Scroll)"),
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(si, text=t("Mouse tekerleğiyle yukarı/aşağı kaydırma hızını ayarlar."),
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED, justify="left").pack(anchor="w", pady=(0, 12))

        slider_row = ctk.CTkFrame(si, fg_color="transparent")
        slider_row.pack(fill="x")

        ctk.CTkLabel(slider_row, text=t("Yavaş"),
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED).pack(side="left", padx=(0, 8))

        mevcut_hiz = int(AYARLAR.get("scroll_hizi", 30))
        self._scroll_deger_lbl = ctk.CTkLabel(
            slider_row, text=str(mevcut_hiz),
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            text_color=GREEN, width=28)

        self._scroll_slider = ctk.CTkSlider(
            slider_row, from_=1, to=100, number_of_steps=99,
            progress_color=GREEN, button_color=GREEN,
            button_hover_color=GREEN_HOVER,
            command=self._scroll_hizi_degisti)
        self._scroll_slider.set(mevcut_hiz)
        self._scroll_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkLabel(slider_row, text=t("Hızlı"),
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED).pack(side="left", padx=(0, 10))
        self._scroll_deger_lbl.pack(side="left")

        # ── Klasörler ────────────────────────────────────────────────────
        diger_kart = Card(scroll)
        diger_kart.pack(fill="x", pady=(0, 12))
        di = ctk.CTkFrame(diger_kart, fg_color="transparent")
        di.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(di, text=t("📦  Klasörler"),
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 10))
        self._klasor_satiri(di, t("Modlar klasörü:"), MODS_DIR)
        self._klasor_satiri(di, t("Shader dosyaları:"), SHADER_FILES)
        self._klasor_satiri(di, t("Minecraft mods:"), MC_MODS_DIR)
        self._klasor_satiri(di, t("İndirilenler:"), DOWNLOADS_DIR)

        # ── Güncelleme kontrolü ──────────────────────────────────────────
        guncelleme_kart = Card(scroll)
        guncelleme_kart.pack(fill="x", pady=(0, 12))
        gi = ctk.CTkFrame(guncelleme_kart, fg_color="transparent")
        gi.pack(fill="x", padx=18, pady=16)

        ust_g = ctk.CTkFrame(gi, fg_color="transparent")
        ust_g.pack(fill="x")
        sol_g = ctk.CTkFrame(ust_g, fg_color="transparent")
        sol_g.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(sol_g, text=f"{t('🔄  Güncellemeler')} — v{UYGULAMA_SURUMU}",
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self._guncelleme_durum_lbl = ctk.CTkLabel(
            sol_g, text=t("Şu anki sürümünü kullanıyorsun."),
            font=ctk.CTkFont("Segoe UI", 12),
            text_color=TXT_MUTED, justify="left")
        self._guncelleme_durum_lbl.pack(anchor="w")

        self._guncelleme_btn = ctk.CTkButton(
            ust_g, text=t("Kontrol Et"), height=32, width=120,
            fg_color=BG_CARD2, hover_color=BG_HOVER,
            border_width=1, border_color=BORDER, text_color=TXT_PRIMARY,
            font=ctk.CTkFont("Segoe UI", 12), corner_radius=6,
            command=self._guncelleme_kontrol_et_tiklandi)
        self._guncelleme_btn.pack(side="right")

        # ── Sıfırla ──────────────────────────────────────────────────────
        sifirla_kart = Card(scroll, border_color=RED_BORDER)
        sifirla_kart.pack(fill="x", pady=(0, 12))
        zi = ctk.CTkFrame(sifirla_kart, fg_color="transparent")
        zi.pack(fill="x", padx=18, pady=16)

        ust2 = ctk.CTkFrame(zi, fg_color="transparent")
        ust2.pack(fill="x")
        ctk.CTkLabel(ust2, text=t("↺  Ayarları Sıfırla"),
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(side="left")
        ctk.CTkButton(
            ust2, text=t("Varsayılana Döndür"), height=32, width=160,
            fg_color=RED_FG, hover_color=RED_HOVER,
            border_width=1, border_color=RED_BORDER, text_color=RED_TXT,
            font=ctk.CTkFont("Segoe UI", 13), corner_radius=6,
            command=self._sifirla).pack(side="right")

    def _klasor_satiri(self, parent, etiket, yol):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=etiket,
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=TXT_LABEL, width=220, anchor="w").pack(side="left")
        ctk.CTkLabel(row, text=yol,
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED, anchor="w").pack(side="left", fill="x", expand=True)

    def _tema_dugmesi_olustur(self, parent, anahtar, palet, row, col):
        secili = anahtar == self._tema_anahtar
        kart = ctk.CTkFrame(parent, fg_color=BG_CARD2, corner_radius=10,
                            border_width=2,
                            border_color=palet["GREEN"] if secili else BORDER,
                            cursor="hand2")
        kart.grid(row=row, column=col, padx=5, pady=5, sticky="ew")
        renk_kare = ctk.CTkFrame(kart, width=28, height=28, corner_radius=8,
                                 fg_color=palet["GREEN"])
        renk_kare.pack(pady=(10, 6))
        renk_kare.pack_propagate(False)
        isim_lbl = ctk.CTkLabel(kart,
                                text=("✓ " if secili else "") + palet["ad"],
                                font=ctk.CTkFont("Segoe UI", 13, "bold" if secili else "normal"),
                                text_color=TXT_PRIMARY if secili else TXT_LABEL)
        isim_lbl.pack(pady=(0, 10))
        for w in (kart, renk_kare, isim_lbl):
            w.bind("<Button-1>", lambda e, a=anahtar: self._tema_sec(a))
        return {"kart": kart, "renk_kare": renk_kare, "isim_lbl": isim_lbl}

    def _tema_sec(self, anahtar):
        if anahtar == self._tema_anahtar:
            return
        self._tema_anahtar = anahtar
        temayi_uygula(anahtar)
        for key, refs in self._tema_butonlari.items():
            secili = key == anahtar
            palet = _TEMA_PALETLERI[key]
            try:
                refs["kart"].configure(border_color=palet["GREEN"] if secili else BORDER)
                refs["isim_lbl"].configure(
                    text=("✓ " if secili else "") + palet["ad"],
                    font=ctk.CTkFont("Segoe UI", 13, "bold" if secili else "normal"),
                    text_color=TXT_PRIMARY if secili else TXT_LABEL)
            except Exception:
                pass
        if self._on_tema_degisti:
            self._on_tema_degisti()

    def _ap_dugmesi_olustur(self, parent, anahtar, palet, row, col):
        secili = anahtar == self._ap_anahtar
        kart = ctk.CTkFrame(parent, fg_color=BG_CARD2, corner_radius=10,
                            border_width=2,
                            border_color=GREEN if secili else BORDER,
                            cursor="hand2")
        kart.grid(row=row, column=col, padx=5, pady=5, sticky="ew")
        renk_kare = ctk.CTkFrame(kart, width=28, height=28, corner_radius=8,
                                 fg_color=palet["BG_MAIN"], border_width=1,
                                 border_color=palet["BORDER"])
        renk_kare.pack(pady=(10, 6))
        renk_kare.pack_propagate(False)
        isim_lbl = ctk.CTkLabel(kart,
                                text=("✓ " if secili else "") + palet["ad"],
                                font=ctk.CTkFont("Segoe UI", 13, "bold" if secili else "normal"),
                                text_color=TXT_PRIMARY if secili else TXT_LABEL)
        isim_lbl.pack(pady=(0, 10))
        for w in (kart, renk_kare, isim_lbl):
            w.bind("<Button-1>", lambda e, a=anahtar: self._ap_sec(a))
        return {"kart": kart, "renk_kare": renk_kare, "isim_lbl": isim_lbl}

    def _ap_sec(self, anahtar):
        if anahtar == self._ap_anahtar:
            return
        self._ap_anahtar = anahtar
        arkaplani_uygula(anahtar)
        for key, refs in self._ap_butonlari.items():
            secili = key == anahtar
            try:
                refs["kart"].configure(border_color=GREEN if secili else BORDER)
                refs["isim_lbl"].configure(
                    text=("✓ " if secili else "") + _ARKAPLAN_PALETLERI[key]["ad"],
                    font=ctk.CTkFont("Segoe UI", 13, "bold" if secili else "normal"),
                    text_color=TXT_PRIMARY if secili else TXT_LABEL)
            except Exception:
                pass
        if self._on_tema_degisti:
            self._on_tema_degisti()

    def _indirme_hedefi_degisti(self):
        acik = self._indirme_switch.get() == 1
        AYARLAR["market_indirme_hedefi"] = "indirilenler" if acik else "modlar"
        ayarlari_kaydet(AYARLAR)

    def _yukle_hedefi_degisti(self):
        acik = self._yukle_switch.get() == 1
        AYARLAR["modlari_yukle_hedefi"] = "indirilenler" if acik else "minecraft"
        ayarlari_kaydet(AYARLAR)

    def _ozel_renk_sec(self):
        sonuc = colorchooser.askcolor(color=GREEN, title=t("Tema Rengi Seç"),
                                      parent=self.winfo_toplevel())
        hex_kod = sonuc[1] if sonuc else None
        if not hex_kod:
            return
        self._tema_anahtar = "ozel"
        temayi_uygula("ozel", ozel_hex=hex_kod)
        if self._on_tema_degisti:
            self._on_tema_degisti()

    def _ozel_arkaplan_sec(self):
        sonuc = colorchooser.askcolor(color=BG_MAIN, title=t("Arka Plan Rengi Seç"),
                                      parent=self.winfo_toplevel())
        hex_kod = sonuc[1] if sonuc else None
        if not hex_kod:
            return
        self._ap_anahtar = "ozel"
        arkaplani_uygula("ozel", ozel_hex=hex_kod)
        if self._on_tema_degisti:
            self._on_tema_degisti()

    def _scroll_hizi_degisti(self, deger):
        deger_int = int(round(deger))
        self._scroll_deger_lbl.configure(text=str(deger_int))
        AYARLAR["scroll_hizi"] = deger_int
        ayarlari_kaydet(AYARLAR)

    def _guncelleme_kontrol_et_tiklandi(self):
        self._guncelleme_btn.configure(state="disabled", text="Kontrol ediliyor…")
        self._guncelleme_durum_lbl.configure(text="Kontrol ediliyor…")

        def sonuc(yeni_var, surum, url, notlar):
            def uygula():
                self._guncelleme_btn.configure(state="normal", text="Kontrol Et")
                if not GITHUB_REPO:
                    self._guncelleme_durum_lbl.configure(
                        text="Güncelleme kontrolü henüz aktif değil.\n"
                             "GITHUB_REPO değişkenini doldurun.")
                elif yeni_var:
                    # Yeni sürüm var → direkt tarayıcıda aç, kullanıcıdan onay istemeden
                    self._guncelleme_durum_lbl.configure(
                        text=f"✓  Yeni sürüm bulundu: v{surum}  →  Tarayıcı açılıyor…",
                        text_color=GREEN)
                    import webbrowser
                    webbrowser.open(url)
                else:
                    self._guncelleme_durum_lbl.configure(
                        text="✓  En güncel sürümü kullanıyorsun.",
                        text_color=TXT_MUTED)
            self.after(0, uygula)

        guncelleme_kontrol_et(sonuc)

    def _sifirla(self):
        if not messagebox.askyesno("Onayla", t("Tüm ayarlar varsayılana döndürülsün mü?")):
            return
        AYARLAR.update(VARSAYILAN_AYARLAR)
        ayarlari_kaydet(AYARLAR)
        temayi_uygula(AYARLAR["tema"])
        arkaplani_uygula(AYARLAR["arkaplan"])
        if self._on_tema_degisti:
            self._on_tema_degisti()


# ===========================================================================
#  Ana Pencere
# ===========================================================================
class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("Minecraft Mod Merkezi")
        self.geometry("1100x700")
        self.minsize(900, 600)
        self.configure(fg_color=BG_MAIN)
        self._guncelleme_seridi = None

        try:
            self.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass

        self.dnd_destekli = False
        if _DND_OK:
            try:
                TkinterDnD._require(self)
                self.dnd_destekli = True
            except Exception:
                self.dnd_destekli = False

        # Global sürükle-bırak overlay
        self._global_drop_overlay = ctk.CTkFrame(
            self, fg_color="#1a2332", corner_radius=0, border_width=0)
        ov_inner = ctk.CTkFrame(self._global_drop_overlay, fg_color="transparent")
        ov_inner.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(ov_inner, text="📎",
                     font=ctk.CTkFont("Segoe UI", 40),
                     text_color="#5b8def").pack()
        ctk.CTkLabel(ov_inner, text=t("Dosyaları buraya bırakın"),
                     font=ctk.CTkFont("Segoe UI", 18, "bold"),
                     text_color="#5b8def").pack(pady=(8, 0))
        self._global_drop_overlay_sub = ctk.CTkLabel(
            ov_inner, text=t(".jar dosyaları Mod Kütüphanesi'ne eklenecek"),
            font=ctk.CTkFont("Segoe UI", 12),
            text_color="#8fa8d9")
        self._global_drop_overlay_sub.pack(pady=(4, 0))

        self._build()
        self.after(1500, self._guncelleme_kontrolu_baslat)

    def _guncelleme_kontrolu_baslat(self):
        def sonuc(yeni_var, surum, url, notlar):
            if yeni_var:
                self.after(0, lambda: self._guncelleme_bildirimi_goster(surum, url, notlar))
        guncelleme_kontrol_et(sonuc)

    def _guncelleme_bildirimi_goster(self, surum, url, notlar):
        try:
            if self._guncelleme_seridi is not None:
                return
            serit = ctk.CTkFrame(self, fg_color=GREEN_DIM, corner_radius=0, height=42)
            serit.place(relx=0, rely=0, relwidth=1)
            serit.pack_propagate(False)
            self._guncelleme_seridi = serit

            ic = ctk.CTkFrame(serit, fg_color="transparent")
            ic.pack(fill="both", expand=True, padx=16, pady=6)

            ctk.CTkLabel(
                ic, text=f"🎉  {t('Yeni bir sürüm mevcut')}: v{surum}  —  {t('güncellemek için tıkla')}",
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
                text_color="white", cursor="hand2").pack(side="left")

            def ac(_e=None):
                import webbrowser
                webbrowser.open(url)
            ic.bind("<Button-1>", ac)

            def kapat():
                try:
                    serit.destroy()
                except Exception:
                    pass
                self._guncelleme_seridi = None

            ctk.CTkButton(
                ic, text="✕", width=28, height=28,
                fg_color="transparent", hover_color=GREEN_HOVER,
                text_color="white", font=ctk.CTkFont("Segoe UI", 13),
                command=kapat).pack(side="right")
        except Exception:
            pass

    def drop_overlay_goster(self, alt_metin=None):
        if alt_metin:
            try:
                self._global_drop_overlay_sub.configure(text=alt_metin)
            except Exception:
                pass
        try:
            self._global_drop_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._global_drop_overlay.lift()
        except Exception:
            pass

    def drop_overlay_gizle(self):
        try:
            self._global_drop_overlay.place_forget()
        except Exception:
            pass

    def _build(self):
        self.configure(fg_color=BG_MAIN)
        try:
            self.configure(bg=BG_MAIN)
        except Exception:
            pass

        # ── Sol Sidebar ──────────────────────────────────────────────────
        sidebar = ctk.CTkFrame(self, width=210, corner_radius=0,
                               fg_color=BG_SIDEBAR)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        logo_f = ctk.CTkFrame(sidebar, fg_color="transparent")
        logo_f.pack(fill="x", padx=16, pady=(20, 24))

        logo_ic = ctk.CTkFrame(logo_f, width=36, height=36,
                               fg_color=GREEN_DIM, corner_radius=8)
        logo_ic.pack(side="left")
        logo_ic.pack_propagate(False)
        ctk.CTkLabel(logo_ic, text="M",
                     font=ctk.CTkFont("Segoe UI", 20, "bold"),
                     text_color="white").place(relx=.5, rely=.5, anchor="center")

        txt_f = ctk.CTkFrame(logo_f, fg_color="transparent")
        txt_f.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(txt_f, text="Minecraft",
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=TXT_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(txt_f, text="Mod Merkezi",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=TXT_MUTED).pack(anchor="w")

        Divider(sidebar).pack(fill="x", padx=16, pady=(0, 12))

        self._nav_btns: dict[str, SidebarButton] = {}
        nav_items = [
            ("modlar",  "⬡", t("Modlar")),
            ("market",  "🛒", t("Mod Marketi")),
            ("fabric",  "⚙", t("Fabric Kurulum")),
            ("shader",  "✦", t("Shader Kurulum")),
            ("ayarlar", "🛠", t("Ayarlar")),
        ]
        for key, ic, lbl in nav_items:
            btn = SidebarButton(sidebar, text=lbl, icon=ic,
                                command=lambda k=key: self._goster(k))
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_btns[key] = btn

        alt_f = ctk.CTkFrame(sidebar, fg_color="transparent")
        alt_f.pack(side="bottom", fill="x", pady=10, padx=10)
        ctk.CTkLabel(alt_f, text="Minecraft Mod Merkezi",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color="#333333").pack(anchor="w")
        ctk.CTkLabel(alt_f, text="v1.4",
                     font=ctk.CTkFont("Segoe UI", 11, slant="italic"),
                     text_color="#3a3a3a").pack(anchor="w", pady=(2, 0))

        # ── Sağ İçerik ───────────────────────────────────────────────────
        self._main = ctk.CTkFrame(self, fg_color=BG_MAIN)
        self._main.pack(side="right", fill="both", expand=True, padx=28, pady=24)

        self._frames: dict[str, ctk.CTkFrame] = {
            "modlar": ModlarFrame(self._main),
            "market": MarketFrame(self._main),
            "fabric": FabricFrame(self._main),
            "shader": ShaderFrame(self._main),
            "ayarlar": AyarlarFrame(self._main, on_tema_degisti=self._yeniden_baslat),
        }

        self._goster("modlar")

        # Tüm penceredeki metinleri seçili dile çevir
        # (Türkçe ise tum_metinleri_cevir hiçbir şey yapmaz)
        self.after(400, lambda: tum_metinleri_cevir(self))

    def _yeniden_baslat(self):
        for w in self.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._guncelleme_seridi = None
        self._build()

    def _goster(self, key: str):
        for k, f in self._frames.items():
            f.pack_forget()
        hedef = self._frames[key]
        for k, b in self._nav_btns.items():
            b.set_active(k == key)
        hedef.pack(fill="both", expand=True)


# ===========================================================================
def _ilk_kurulumda_ornek_dosyalari_kopyala():
    if not hasattr(sys, "_MEIPASS"):
        return
    for klasor_adi, kalici_yol in (("mods", MODS_DIR), ("shader_files", SHADER_FILES)):
        gomulu_kaynak = os.path.join(sys._MEIPASS, klasor_adi)
        if not os.path.isdir(gomulu_kaynak):
            continue
        os.makedirs(kalici_yol, exist_ok=True)
        try:
            kalici_bos = len(os.listdir(kalici_yol)) == 0
        except Exception:
            kalici_bos = True
        if not kalici_bos:
            continue
        for ad in os.listdir(gomulu_kaynak):
            kaynak = os.path.join(gomulu_kaynak, ad)
            hedef = os.path.join(kalici_yol, ad)
            try:
                if os.path.isfile(kaynak):
                    shutil.copy2(kaynak, hedef)
            except Exception:
                pass


def main():
    os.makedirs(MODS_DIR, exist_ok=True)
    os.makedirs(SHADER_FILES, exist_ok=True)
    _ilk_kurulumda_ornek_dosyalari_kopyala()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
