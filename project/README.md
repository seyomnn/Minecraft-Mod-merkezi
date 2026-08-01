# Minecraft Modlama Merkezi

Koyu temalı, modern masaüstü mod yönetim uygulaması.

## Klasör Yapısı

```
proje/
├── main.py
├── requirements.txt
├── mods/                  ← .jar mod dosyalarını buraya koyun
├── assets/                ← ikonlar ve görseller
└── fabric\\\_installer/
    └── fabric-installer-1.1.1\\\_(1).exe
```

## Kurulum

```bash
pip install -r requirements.txt
python main.py
```

## .exe Derleme (PyInstaller)

```bash
pyinstaller --noconfirm --onefile --windowed ^
    --name "MinecraftModMerkezi" ^
    --add-data "mods;mods" ^
    --add-data "assets;assets" ^
    --add-data "fabric\\\_installer;fabric\\\_installer" ^
    main.py
```

> \\\*\\\*Not:\\\*\\\* Linux/macOS'ta `;` yerine `:` kullanın:
> `--add-data "mods:mods"`

Derlenen `.exe` dosyası `dist/` klasörüne çıkar.

## Özellikler

* **Modlar** — `.jar` dosyalarını listeler, ekler, siler ve `.minecraft/mods` klasörüne kopyalar
* **Fabric Kurulum** — `fabric\\\_installer/` içindeki kurulum dosyasını doğrudan çalıştırır
* **Kurulum Rehberi** — Adım adım Fabric kurulum rehberi, tamamlanma takibi ve önerilen modlar

