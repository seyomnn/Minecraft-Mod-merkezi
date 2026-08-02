# Minecraft Mod Merkezi

> Masaüstü mod yönetim uygulaması — Yapay zeka ile yapılmıştır.

---

##  Özellikler

- ** Modlar** — `.jar` dosyalarını listeler, ekler, siler ve `.minecraft/mods` klasörüne tek tıkla kopyalar
- ** Mod Marketi** — Modrinth üzerinden binlerce modu arayıp doğrudan indirir
- ** Fabric Kurulum** — `fabric_installer/` içindeki kurulum dosyasını doğrudan çalıştırır
- ** Shader Kurulum** — Sodium + Iris Shaders + Shader paketi otomatik kurulumu
- ** Tema & Arka Plan** — Birden fazla renk teması ve arka plan seçeneği
- ** Otomatik Güncelleme** — GitHub Releases üzerinden yeni sürüm kontrolü

---

##  Klasör Yapısı

```
proje/
├── main.py                        ← Ana uygulama
├── modrinth_api.py                ← Modrinth API yardımcı modülü
├── requirements.txt
├── icon.ico
├── mods/                          ← .jar mod dosyalarını buraya koy
├── shader_files/                  ← sodium .jar / iris .jar / shader .zip
│   ├── sodium-fabric-xxx.jar
│   ├── iris-fabric-xxx.jar
│   └── ShaderPaketi.zip
└── fabric_installer/
    └── fabric-installer-1.1.1_(1).exe
```

---

##  Kurulum & Çalıştırma

### Gereksinimler

```
customtkinter >= 5.2
pillow >= 10
```

```bash
pip install -r requirements.txt
python main.py
```

---

##  .exe Derleme (PyInstaller)

```bash
pip install pyinstaller
```

```bash
pyinstaller --noconfirm --onefile --windowed ^
  --add-data "mods;mods" ^
  --add-data "fabric_installer;fabric_installer" ^
  --add-data "shader_files;shader_files" ^
  --icon=icon.ico ^
  --hidden-import modrinth_api ^
  --name "MinecraftModMerkezi" ^
  main.py
```

> **Not:** Linux/macOS'ta `;` yerine `:` kullanın:
> `--add-data "mods:mods"`

Derlenen `.exe` dosyası `dist/` klasörüne çıkar.

---

##  Yeni Sürüm Çıkarma

1. `main.py` içinde sürüm numarasını güncelle:
   ```python
   UYGULAMA_SURUMU = "1.5"
   ```
2. Yeni `.exe` derle
3. GitHub'da **Releases → Create a new release** tıkla
4. Tag: `v1.5` — Title: `v1.5 - Güncelleme`
5. `dist/MinecraftModMerkezi.exe` dosyasını Assets'e ekle
6. **Publish release** bas

Kullanıcılar uygulamayı açtığında otomatik olarak yeni sürüm algılanır ve güncelleme bildirimi gösterilir.

---

##  Lisans

Bu proje açık kaynaklıdır. Kaynak kodu incelemek, değiştirmek ve dağıtmak serbesttir.
