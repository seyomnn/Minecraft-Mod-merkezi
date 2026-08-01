"""
modrinth_api.py
Modrinth API (https://docs.modrinth.com) ile iletişim için yardımcı fonksiyonlar.
Hiçbir API key gerektirmez (Modrinth public API).

Kullanılan uçlar:
    GET  /v2/search                 → mod arama
    GET  /v2/project/{id}/version   → bir modun sürüm listesi
    GET  /v2/project/{id}           → mod detayları (ikon dahil)

Ayrıca ücretsiz/resmi olmayan Google Translate endpoint'i ile
açıklamaları Türkçeye çevirir (internet gerektirir, başarısız
olursa orijinal İngilizce metni döner — uygulama asla çökmez).
"""

import json
import urllib.request
import urllib.parse
import urllib.error
import threading

API_BASE = "https://api.modrinth.com/v2"
CDN_TIMEOUT = 12

# Desteklenen Minecraft sürümleri (1.19 → 26.2), yeniden eskiye
MC_VERSIONS = [
    "26.2", "26.2-rc-2", "26.2-rc-1", "26.1.2", "26.1.1", "26.1",
    "25.2.2", "25.2.1", "25.2", "25.1.2", "25.1.1", "25.1",
    "24.2.1", "24.2", "24.1.1", "24.1",
    "1.21.11", "1.21.10", "1.21.9", "1.21.8", "1.21.7", "1.21.6",
    "1.21.5", "1.21.4", "1.21.3", "1.21.2", "1.21.1", "1.21",
    "1.20.6", "1.20.5", "1.20.4", "1.20.3", "1.20.2", "1.20.1", "1.20",
    "1.19.4", "1.19.3", "1.19.2", "1.19.1", "1.19",
]

# Basitleştirilmiş seçim listesi (dropdown'larda göstermek için ana sürümler)
MC_VERSIONS_SIMPLE = [
    "26.2", "26.1", "25.2", "25.1", "24.2", "24.1",
    "1.21.11", "1.21.8", "1.21.5", "1.21.4", "1.21.1", "1.21",
    "1.20.6", "1.20.4", "1.20.1", "1.20",
    "1.19.4", "1.19.3", "1.19.2", "1.19",
]

LOADERS = ["fabric", "forge", "quilt", "neoforge"]

SORT_OPTIONS = [
    ("relevance", "Alaka Düzeyi"),
    ("downloads", "En Çok İndirilen"),
    ("follows",   "En Çok Beğenilen"),
    ("newest",    "En Yeni"),
    ("updated",   "Son Güncellenen"),
]


def _http_get_json(url: str, timeout: int = CDN_TIMEOUT):
    req = urllib.request.Request(url, headers={
        "User-Agent": "MinecraftModMerkezi/1.0 (iletisim: seyomnn)"
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def search_mods(query="", loader="fabric", game_version=None,
                 index="relevance", offset=0, limit=20, project_type="mod"):
    """
    Modrinth'te mod (veya project_type="shader" ile shader paketi) arar.
    Döner: {"hits": [...], "total_hits": int}
    Hata olursa: {"hits": [], "total_hits": 0, "error": "..."}
    """
    facets = [[f"project_type:{project_type}"]]
    if loader and loader != "hepsi":
        facets.append([f"categories:{loader}"])
    if game_version:
        facets.append([f"versions:{game_version}"])

    params = {
        "query": query,
        "limit": limit,
        "offset": offset,
        "index": index,
        "facets": json.dumps(facets),
    }
    url = f"{API_BASE}/search?{urllib.parse.urlencode(params)}"
    try:
        return _http_get_json(url)
    except Exception as e:
        return {"hits": [], "total_hits": 0, "error": str(e)}


def get_project_versions(project_id, loader=None, game_version=None):
    """
    Bir modun sürüm listesini döner (en yeniden en eskiye).
    Her eleman: {"id", "version_number", "game_versions", "loaders", "files": [...]}
    """
    params = {}
    if loader:
        params["loaders"] = json.dumps([loader])
    if game_version:
        params["game_versions"] = json.dumps([game_version])
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    url = f"{API_BASE}/project/{project_id}/version{qs}"
    try:
        return _http_get_json(url)
    except Exception:
        return []


def get_primary_file(version_obj):
    """Bir version objesinden indirilecek ana dosyayı (jar) bulur."""
    files = version_obj.get("files", [])
    if not files:
        return None
    for f in files:
        if f.get("primary"):
            return f
    return files[0]


def download_file(url, dest_path, progress_cb=None, timeout=30):
    """
    Dosyayı indirir. progress_cb(yapilan_oran: float) periyodik çağrılır.
    Başarılıysa True, hata olursa False döner (exception fırlatmaz).
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "MinecraftModMerkezi/1.0 (iletisim: seyomnn)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = resp.length or int(resp.headers.get("Content-Length", 0) or 0)
            written = 0
            chunk = 64 * 1024
            with open(dest_path, "wb") as out:
                while True:
                    block = resp.read(chunk)
                    if not block:
                        break
                    out.write(block)
                    written += len(block)
                    if progress_cb and total:
                        progress_cb(min(written / total, 1.0))
        return True
    except Exception:
        return False


def get_project_icon_url(project_id_or_slug):
    """Mod detay sayfasından icon_url alır."""
    try:
        data = _http_get_json(f"{API_BASE}/project/{project_id_or_slug}")
        return data.get("icon_url")
    except Exception:
        return None


def get_project_info(project_id_or_slug):
    """Bir projenin (mod veya shader paketi) tam bilgisini döner:
    {"title", "description", "icon_url", "slug", "project_id", ...}.
    Proje bulunamazsa veya hata olursa None döner (exception fırlatmaz)."""
    try:
        data = _http_get_json(f"{API_BASE}/project/{project_id_or_slug}")
        if not data:
            return None
        return {
            "title": data.get("title"),
            "description": data.get("description"),
            "icon_url": data.get("icon_url"),
            "slug": data.get("slug", project_id_or_slug),
            "project_id": data.get("id"),
            "downloads": data.get("downloads", 0),
            "follows": data.get("followers", 0),
        }
    except Exception:
        return None


def translate_to_tr(text: str, timeout: int = 6) -> str:
    """
    Ücretsiz/resmi olmayan Google Translate endpoint'i ile metni Türkçeye çevirir.
    İnternet yoksa veya hata olursa, orijinal metni döner (asla çökmez).
    """
    if not text:
        return text
    text_clip = text[:480]  # endpoint uzun metinlerde sorun çıkarabilir
    try:
        params = {
            "client": "gtx",
            "sl": "en",
            "tl": "tr",
            "dt": "t",
            "q": text_clip,
        }
        url = "https://translate.googleapis.com/translate_a/single?" + \
              urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parcalar = [seg[0] for seg in data[0] if seg and seg[0]]
        return "".join(parcalar) if parcalar else text
    except Exception:
        return text


def translate_async(text: str, callback, timeout: int = 6):
    """
    Çeviriyi arka planda yapar, sonucu callback(sonuc_metin) ile döner.
    UI thread'ini bloklamamak için kullanılır.
    """
    def worker():
        sonuc = translate_to_tr(text, timeout=timeout)
        callback(sonuc)
    threading.Thread(target=worker, daemon=True).start()