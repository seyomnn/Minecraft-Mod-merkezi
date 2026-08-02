# Minecraft Mod Merkezi

 Masaüstü mod yönetim uygulaması.

## Klasör Yapısı

```
proje/
├── main.py
├── requirements.txt
├── mods/                  ← .jar mod dosyalarını buraya koyun
├── assets/                
└── fabric\\\_installer/
    └── fabric-installer-1.1.1\\\_(1).exe
```



## .exe Derleme (PyInstaller)

```bash
pyinstaller --noconfirm --onefile --windowed --add-data "mods;mods" --add-data "fabric_installer;fabric_installer" --add-data "shader_files;shader_files" --icon=icon.ico --hidden-import modrinth_api --name "MinecraftModMerkezi" main.py
```

> \\\*\\\*Not:\\\*\\\* Linux/macOS'ta `;` yerine `:` kullanın:
> `--add-data "mods:mods"`

Derlenen `.exe` dosyası `dist/` klasörüne çıkar.

## Özellikler

* **Modlar** — `.jar` dosyalarını listeler, ekler, siler ve `.minecraft/mods` klasörüne kopyalar
* **Fabric Kurulum** — `fabric\\\_installer/` içindeki kurulum dosyasını doğrudan çalıştırır
* **Kurulum Rehberi** — Adım adım Fabric kurulum rehberi, tamamlanma takibi ve önerilen modlar

