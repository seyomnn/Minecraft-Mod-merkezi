"""
Minecraft Modlama Merkezi
Sekmeli Tkinter uygulaması: Modlar yönetimi ve Fabric kurulumu.

PyInstaller ile tek dosya (.exe) derleme:
    pyinstaller --noconfirm --onefile --windowed ^
        --add-data "mods;mods" ^
        --add-data "fabric_installer;fabric_installer" ^
        minecraft_modlama_merkezi.py
"""

import os
import sys
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess


def resource_path(relative):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative)


MODS_KLASORU     = resource_path("mods")
FABRIC_INSTALLER = resource_path(os.path.join("fabric_installer",
                                               "fabric-installer-1.1.1_(1).exe"))

ZEMIN      = "#1a1a2e"
KART       = "#16213e"
KART_HOVER = "#1c2a4a"
PRIM       = "#0f3460"
PRIM_HOVER = "#16447f"
ACC        = "#00adb5"
ACC_HOVER  = "#00c4cc"
YAZI       = "#e8e8e8"
YAZI_SOLUK = "#9aa0b5"
BASARI     = "#2ecc71"
HATA       = "#e74c3c"
UYARI      = "#f39c12"
TRACK      = "#1e2a47"


class RoundedCanvas(tk.Canvas):
    def __init__(self, master=None, **kwargs):
        tk.Canvas.__init__(self, master, **kwargs)

    def create_rounded_rect(self, x1, y1, x2, y2, radius=12, **kwargs):
        w = x2 - x1
        h = y2 - y1
        if w <= 0 or h <= 0:
            return None
        r = max(1.0, min(float(radius), w / 2.0, h / 2.0))
        pts = [
            x1 + r, y1,        x2 - r, y1,
            x2,     y1,        x2,     y1 + r,
            x2,     y2 - r,    x2,     y2,
            x2 - r, y2,        x1 + r, y2,
            x1,     y2,        x1,     y2 - r,
            x1,     y1 + r,    x1,     y1,
        ]
        return self.create_polygon(pts, smooth=True, **kwargs)


class CustomScrollbar(RoundedCanvas):
    def __init__(self, master=None, command=None,
                 thumb_color=ACC, thumb_hover=ACC_HOVER,
                 bg=KART, width=10, **kwargs):
        RoundedCanvas.__init__(self, master, bg=bg,
                               highlightthickness=0, width=width, **kwargs)
        self._cmd      = command
        self._tc       = thumb_color
        self._tc_h     = thumb_hover
        self._thumb    = None
        self._first    = 0.0
        self._size     = 1.0
        self._drag     = False
        self._drag_y   = 0

        self.bind("<Configure>",       lambda e: self._render())
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", False))
        self.bind("<Enter>",           lambda e: self._tint(self._tc_h))
        self.bind("<Leave>",           lambda e: self._tint(self._tc))

    def set(self, first, last):
        self._first = float(first)
        self._size  = max(float(last) - float(first), 0.05)
        self._render()

    def _render(self):
        self.delete("all")
        H = self.winfo_height()
        W = self.winfo_width()
        if H < 4 or W < 4:
            return
        th = max(int(H * self._size), 20)
        ty = int((H - th) * self._first / max(1 - self._size, 1e-6))
        ty = max(0, min(H - th, ty))
        self._thumb = self.create_rounded_rect(
            1, ty, W - 1, ty + th, radius=W // 2,
            fill=self._tc, outline="", width=0)

    def _tint(self, c):
        if self._thumb:
            try:
                self.itemconfig(self._thumb, fill=c)
            except Exception:
                pass

    def _on_press(self, ev):
        if not self._thumb:
            return
        bb = self.bbox(self._thumb)
        if bb and bb[1] <= ev.y <= bb[3]:
            self._drag = True
            self._drag_y = ev.y
        else:
            step = max(int(self._size * 5), 1)
            if self._cmd:
                self._cmd("scroll", -step if (bb and ev.y < bb[1]) else step, "units")

    def _on_drag(self, ev):
        if not self._drag or not self._cmd:
            return
        H = max(self.winfo_height(), 1)
        th = max(int(H * self._size), 20)
        mov = H - th
        if mov <= 0:
            return
        delta = (ev.y - self._drag_y) / mov
        self._drag_y = ev.y
        self._cmd("moveto", str(max(0.0, min(1.0 - self._size, self._first + delta))))


class ModernProgressBar(RoundedCanvas):
    def __init__(self, master=None, fill_color=ACC, bg=KART, height=24, **kwargs):
        RoundedCanvas.__init__(self, master, bg=bg,
                               highlightthickness=0, height=height, **kwargs)
        self._fill   = fill_color
        self._prog   = 0.0
        self._status = "Hazır"
        self.bind("<Configure>", lambda e: self._render())

    def set_progress(self, value, status=None):
        self._prog = max(0.0, min(1.0, float(value)))
        if status is not None:
            self._status = status
        self._render()

    def _render(self):
        self.delete("all")
        W = self.winfo_width()
        H = self.winfo_height()
        if W < 4 or H < 4:
            return
        r = H // 2 - 1
        self.create_rounded_rect(1, 1, W - 1, H - 1, radius=r,
                                 fill=TRACK, outline="", width=0)
        fw = int((W - 2) * self._prog)
        if fw > 2:
            self.create_rounded_rect(1, 1, 1 + fw, H - 1,
                                     radius=min(r, fw // 2),
                                     fill=self._fill, outline="", width=0)
        txt = f"%{int(self._prog * 100)}  {self._status}" if self._status \
              else f"%{int(self._prog * 100)}"
        self.create_text(W // 2, H // 2, text=txt,
                         fill=YAZI, font=("Segoe UI", 9, "bold"))


class PremiumButton(RoundedCanvas):
    def __init__(self, master=None, text="", command=None,
                 width=160, height=40,
                 bg=PRIM, hover_color=PRIM_HOVER,
                 text_color=YAZI, radius=11,
                 font_size=10, bold=True, **kwargs):
        RoundedCanvas.__init__(self, master, bg=bg,
                               highlightthickness=0,
                               width=width, height=height, **kwargs)
        self._bg      = bg
        self._hover   = hover_color
        self._tc      = text_color
        self._text    = text
        self._cmd     = command
        self._r       = radius
        self._font    = ("Segoe UI", font_size, "bold" if bold else "normal")
        self._enabled = True
        self._rid     = None
        self._tid     = None

        self.bind("<Configure>",       lambda e: self._render())
        self.bind("<Enter>",           self._on_enter)
        self.bind("<Leave>",           self._on_leave)
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_state(self, enabled=True):
        self._enabled = enabled
        self._render()

    def set_text(self, text):
        self._text = text
        self._render()

    def _cur_bg(self):
        return self._bg if self._enabled else TRACK

    def _render(self):
        self.delete("all")
        W = self.winfo_width()
        H = self.winfo_height()
        if W < 2 or H < 2:
            return
        bg = self._cur_bg()
        self.config(bg=bg)
        self._rid = self.create_rounded_rect(0, 0, W, H, radius=self._r,
                                             fill=bg, outline="", width=0)
        self._tid = self.create_text(W // 2, H // 2, text=self._text,
                                     fill=self._tc if self._enabled else YAZI_SOLUK,
                                     font=self._font)

    def _on_enter(self, _):
        if self._enabled:
            self.config(bg=self._hover)
            if self._rid:
                try:
                    self.itemconfig(self._rid, fill=self._hover)
                except Exception:
                    pass

    def _on_leave(self, _):
        if self._enabled:
            self.config(bg=self._bg)
            if self._rid:
                try:
                    self.itemconfig(self._rid, fill=self._bg)
                except Exception:
                    pass

    def _on_press(self, _):
        if self._enabled and self._rid:
            try:
                self.itemconfig(self._rid, fill=ACC)
                self.config(bg=ACC)
            except Exception:
                pass

    def _on_release(self, ev):
        if not self._enabled:
            return
        if self._rid:
            try:
                self.itemconfig(self._rid, fill=self._hover)
                self.config(bg=self._hover)
            except Exception:
                pass
        if 0 <= ev.x <= self.winfo_width() and 0 <= ev.y <= self.winfo_height():
            if self._cmd:
                self._cmd()


class TabButton(RoundedCanvas):
    def __init__(self, master=None, text="", command=None,
                 width=130, height=42, **kwargs):
        RoundedCanvas.__init__(self, master, bg=ZEMIN,
                               highlightthickness=0,
                               width=width, height=height, **kwargs)
        self._text   = text
        self._cmd    = command
        self._active = False

        self.bind("<Configure>",     lambda e: self._render())
        self.bind("<Enter>",         self._on_enter)
        self.bind("<Leave>",         self._on_leave)
        self.bind("<ButtonPress-1>", lambda e: self._cmd() if self._cmd else None)

    def set_active(self, active):
        self._active = active
        self._render()

    def _render(self):
        self.delete("all")
        W = self.winfo_width()
        H = self.winfo_height()
        if W < 2 or H < 2:
            return
        if self._active:
            self.create_rounded_rect(1, 3, W - 1, H - 1, radius=9,
                                     fill=KART, outline="", width=0)
            uw = min(40, W // 2)
            self.create_rounded_rect(W // 2 - uw // 2, H - 5,
                                     W // 2 + uw // 2, H - 2,
                                     radius=2, fill=ACC, outline="", width=0)
            tc = YAZI
        else:
            tc = YAZI_SOLUK
        self.create_text(W // 2, H // 2 - 2, text=self._text,
                         fill=tc, font=("Segoe UI", 10, "bold"))

    def _on_enter(self, _):
        if not self._active:
            self.delete("all")
            W = self.winfo_width()
            H = self.winfo_height()
            self.create_rounded_rect(1, 3, W - 1, H - 1, radius=9,
                                     fill=KART_HOVER, outline="", width=0)
            self.create_text(W // 2, H // 2 - 2, text=self._text,
                             fill=YAZI, font=("Segoe UI", 10, "bold"))

    def _on_leave(self, _):
        if not self._active:
            self._render()


# ===========================================================================
#  Kaydırılabilir Frame yardımcısı (tkinter için)
# ===========================================================================
class ScrollableFrame(tk.Frame):
    """Mouse wheel + scrollbar destekli kaydırılabilir tk.Frame."""

    def __init__(self, master, bg=ZEMIN, **kwargs):
        tk.Frame.__init__(self, master, bg=bg, **kwargs)

        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self._sb = CustomScrollbar(
            self, command=self._canvas.yview,
            bg=bg, thumb_color=ACC, thumb_hover=ACC_HOVER, width=10)

        self._sb.pack(side="right", fill="y", padx=(2, 2), pady=4)
        self._canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self._canvas, bg=bg)
        self._win = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.configure(yscrollcommand=self._sb.set)

        # Mouse wheel
        self._canvas.bind("<Enter>", self._bind_wheel)
        self._canvas.bind("<Leave>", self._unbind_wheel)

    def _on_inner_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._win, width=event.width)

    def _bind_wheel(self, _event=None):
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _event=None):
        self._canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# ===========================================================================
#  Ana Uygulama
# ===========================================================================
class MinecraftModlamaMerkezi:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Minecraft Modlama Merkezi")
        self.root.geometry("820x660")
        self.root.minsize(740, 580)
        self.root.configure(bg=ZEMIN)
        self._kopyalama_aktif = False
        self._ui_kur()

    def _ui_kur(self):
        # Başlık
        hdr = tk.Frame(self.root, bg=ZEMIN)
        hdr.pack(fill="x", padx=24, pady=(18, 6))

        logo = tk.Canvas(hdr, width=44, height=44, bg=ZEMIN, highlightthickness=0)
        logo.pack(side="left", padx=(0, 10))
        logo.create_rectangle(3,  3,  41, 41, fill=PRIM,      outline="")
        logo.create_rectangle(7,  7,  21, 21, fill=ACC,        outline="")
        logo.create_rectangle(23, 7,  37, 21, fill=PRIM_HOVER, outline="")
        logo.create_rectangle(7,  23, 21, 37, fill=PRIM_HOVER, outline="")
        logo.create_rectangle(23, 23, 37, 37, fill=ACC,        outline="")

        tk.Label(hdr, text="Minecraft Modlama Merkezi",
                 bg=ZEMIN, fg=YAZI,
                 font=("Segoe UI", 17, "bold")).pack(side="left")
        tk.Label(hdr, text="• Mod yönetimi & Fabric kurulumu",
                 bg=ZEMIN, fg=YAZI_SOLUK,
                 font=("Segoe UI", 9)).pack(side="left", padx=(8, 0), pady=(4, 0))

        # Sekmeler
        tabs = tk.Frame(self.root, bg=ZEMIN)
        tabs.pack(fill="x", padx=24, pady=(4, 10))

        self._tab_mod = TabButton(tabs, text="Modlar",
                                  command=lambda: self._sekme("modlar"),
                                  width=130, height=42)
        self._tab_mod.pack(side="left", padx=(0, 6))

        self._tab_fab = TabButton(tabs, text="Fabric Kurulumu",
                                  command=lambda: self._sekme("fabric"),
                                  width=165, height=42)
        self._tab_fab.pack(side="left")

        # İçerik
        self._content = tk.Frame(self.root, bg=ZEMIN)
        self._content.pack(fill="both", expand=True, padx=24)

        self._fr_mod = tk.Frame(self._content, bg=ZEMIN)
        self._fr_fab = tk.Frame(self._content, bg=ZEMIN)

        self._modlar_kur()
        self._fabric_kur()

        self._imza = tk.Label(
            self.root,
            text="seyomnn tarafından yapıldı",
            bg=ZEMIN, fg="#383854",
            font=("Segoe UI", 8, "italic"))
        self._imza.pack(side="bottom", anchor="e", padx=14, pady=(0, 6))

        self._sekme("modlar")
        self.root.after(150, self._mod_listele)

    def _sekme(self, isim):
        self._tab_mod.set_active(isim == "modlar")
        self._tab_fab.set_active(isim == "fabric")
        self._fr_mod.pack_forget()
        self._fr_fab.pack_forget()
        (self._fr_mod if isim == "modlar" else self._fr_fab).pack(
            fill="both", expand=True)

    # -----------------------------------------------------------------------
    #  Modlar sekmesi
    # -----------------------------------------------------------------------
    def _modlar_kur(self):
        f = self._fr_mod

        info = tk.Frame(f, bg=KART, highlightbackground=PRIM, highlightthickness=1)
        info.pack(fill="x", pady=(0, 10))
        tk.Label(info,
                 text="  'mods' klasöründeki tüm modlar otomatik algılanır.\n"
                      "  'Modları Yükle' ile tümünü seçtiğiniz klasöre kopyalayın.",
                 bg=KART, fg=YAZI_SOLUK, font=("Segoe UI", 9),
                 justify="left", padx=6, pady=8).pack(anchor="w")

        br = tk.Frame(f, bg=ZEMIN)
        br.pack(fill="x", pady=(0, 8))

        self._btn_listele = PremiumButton(
            br, text="Yenile", width=100, height=34,
            command=self._mod_listele, bg=PRIM, hover_color=PRIM_HOVER)
        self._btn_listele.pack(side="left", padx=(0, 6))

        self._btn_ekle = PremiumButton(
            br, text="Mod Ekle", width=110, height=34,
            command=self._mod_ekle,
            bg=ACC, hover_color=ACC_HOVER, text_color="#0a0a12")
        self._btn_ekle.pack(side="left", padx=(0, 6))

        self._btn_kaldir = PremiumButton(
            br, text="Seçileni Kaldır", width=145, height=34,
            command=self._mod_kaldir,
            bg="#7b1d3a", hover_color="#9c2550")
        self._btn_kaldir.pack(side="left")

        lc = tk.Frame(f, bg=KART, highlightbackground=PRIM, highlightthickness=1)
        lc.pack(fill="both", expand=True, pady=(0, 8))

        self._scrollbar = CustomScrollbar(
            lc, width=12, bg=KART,
            thumb_color=ACC, thumb_hover=ACC_HOVER,
            command=self._sb_komut)
        self._scrollbar.pack(side="right", fill="y", padx=(2, 4), pady=4)

        self._listbox = tk.Listbox(
            lc, bg=KART, fg=YAZI,
            selectbackground=ACC, selectforeground="#0a0a12",
            font=("Consolas", 10),
            relief="flat", highlightthickness=0, bd=0,
            activestyle="none",
            yscrollcommand=self._lb_scroll)
        self._listbox.pack(side="left", fill="both", expand=True,
                           padx=(4, 0), pady=4)
        self._listbox.bind("<Motion>", self._lb_hover)

        sp = tk.Frame(f, bg=ZEMIN)
        sp.pack(fill="x", pady=(0, 8))

        self._durum = tk.Label(sp, text="Hazır.", bg=ZEMIN, fg=YAZI_SOLUK,
                               font=("Segoe UI", 9), anchor="w")
        self._durum.pack(fill="x", pady=(0, 4))

        self._progress = ModernProgressBar(sp, fill_color=ACC, bg=KART, height=26)
        self._progress.pack(fill="x")

        br2 = tk.Frame(f, bg=ZEMIN)
        br2.pack(fill="x", pady=(6, 10))

        self._btn_yukle = PremiumButton(
            br2, text="Modları Yükle", width=175, height=46,
            command=self._mod_yukle,
            bg=ACC, hover_color=ACC_HOVER,
            text_color="#0a0a12", font_size=12)
        self._btn_yukle.pack(side="right")

    # -----------------------------------------------------------------------
    #  Fabric sekmesi  —  SCROLLABLE
    # -----------------------------------------------------------------------
    def _fabric_kur(self):
        f = self._fr_fab

        # Kaydırılabilir alan
        sf = ScrollableFrame(f, bg=ZEMIN)
        sf.pack(fill="both", expand=True)
        inner = sf.inner   # tüm widget'lar buraya eklenir

        # Bilgi kartı
        info = tk.Frame(inner, bg=KART,
                        highlightbackground=PRIM, highlightthickness=1)
        info.pack(fill="x", pady=(0, 20))
        tk.Label(info,
                 text="  'İndir ve Kur' butonuna basın — Fabric installer otomatik çalışır.",
                 bg=KART, fg=YAZI_SOLUK, font=("Segoe UI", 10),
                 justify="left", padx=10, pady=14).pack(anchor="w")

        # Installer dosyası durum göstergesi
        ok = os.path.isfile(FABRIC_INSTALLER)
        tk.Label(inner,
                 text=("✓  " + os.path.basename(FABRIC_INSTALLER)) if ok
                      else "⚠  fabric-installer bulunamadı — fabric_installer/ klasörünü kontrol edin.",
                 bg=ZEMIN, fg=BASARI if ok else UYARI,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(0, 16))

        # Durum etiketi + ilerleme çubuğu
        self._fab_durum = tk.Label(inner, text="Durum: Bekleniyor.",
                                   bg=ZEMIN, fg=YAZI_SOLUK,
                                   font=("Segoe UI", 9), anchor="w")
        self._fab_durum.pack(fill="x", pady=(0, 6))

        self._fab_progress = ModernProgressBar(inner, fill_color=ACC, bg=KART, height=26)
        self._fab_progress.pack(fill="x", pady=(0, 30))

        # "İndir ve Kur" butonu
        self._btn_kur = PremiumButton(
            inner, text="⬇  İndir ve Kur",
            width=300, height=64,
            command=self._indir_ve_kur,
            bg=ACC, hover_color=ACC_HOVER,
            text_color="#0a0a12", font_size=15)
        self._btn_kur.pack(anchor="center", pady=(0, 30))

        # Adım adım rehber kartı
        rehber = tk.Frame(inner, bg=KART,
                          highlightbackground=PRIM, highlightthickness=1)
        rehber.pack(fill="x", pady=(0, 20))

        tk.Label(rehber, text="  Kurulum Adımları",
                 bg=KART, fg=ACC,
                 font=("Segoe UI", 11, "bold"),
                 padx=10, pady=10).pack(anchor="w")

        adimlar = [
            "1.  Butona bas → installer otomatik açılır.",
            "2.  Minecraft sürümünü seç (1.20.x önerilir).",
            "3.  'Install' butonuna bas.",
            "4.  Launcher'da 'Fabric' profilini seç ve oyna!",
            "5.  Fabric API modunu modrinth.com'dan indirip mods klasörüne at.",
        ]
        for a in adimlar:
            tk.Label(rehber, text=a,
                     bg=KART, fg=YAZI,
                     font=("Segoe UI", 9),
                     padx=18, pady=3,
                     justify="left", anchor="w").pack(fill="x")

        tk.Frame(rehber, bg=KART, height=10).pack()  # alt boşluk

    # -----------------------------------------------------------------------
    #  Modlar — iş mantığı
    # -----------------------------------------------------------------------
    def _mod_listele(self):
        self._listbox.delete(0, tk.END)
        dosyalar = self._mod_dosyalari()
        if not dosyalar:
            self._durum.config(text="mods klasörü boş veya bulunamadı.", fg=UYARI)
            return
        for d in dosyalar:
            self._listbox.insert(tk.END, "  " + d)
        self._durum.config(
            text=f"{len(dosyalar)} mod algılandı  •  {MODS_KLASORU}",
            fg=YAZI_SOLUK)
        self._progress.set_progress(0.0, "Hazır")

    def _mod_dosyalari(self):
        if not os.path.isdir(MODS_KLASORU):
            return []
        try:
            return sorted(f for f in os.listdir(MODS_KLASORU)
                          if os.path.isfile(os.path.join(MODS_KLASORU, f)))
        except Exception:
            return []

    def _mod_ekle(self):
        paths = filedialog.askopenfilenames(
            title="Mod dosyaları seçin",
            filetypes=[("Jar dosyaları", "*.jar"), ("Tüm dosyalar", "*.*")])
        if not paths:
            return
        os.makedirs(MODS_KLASORU, exist_ok=True)
        n = 0
        for p in paths:
            try:
                shutil.copy2(p, os.path.join(MODS_KLASORU, os.path.basename(p)))
                n += 1
            except Exception as e:
                messagebox.showerror("Kopyalama Hatası", str(e))
        if n:
            self._durum.config(text=f"{n} mod eklendi.", fg=BASARI)
            self._mod_listele()

    def _mod_kaldir(self):
        sel = self._listbox.curselection()
        if not sel:
            messagebox.showwarning("Uyarı", "Önce bir mod seçin.")
            return
        ad = self._listbox.get(sel[0]).strip()
        if not messagebox.askyesno("Onayla", f"'{ad}' silinsin mi?"):
            return
        try:
            os.remove(os.path.join(MODS_KLASORU, ad))
            self._mod_listele()
            self._durum.config(text=f"Silindi: {ad}", fg=BASARI)
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _mod_yukle(self):
        if self._kopyalama_aktif:
            messagebox.showinfo("Bilgi", "Kopyalama zaten devam ediyor…")
            return
        dosyalar = self._mod_dosyalari()
        if not dosyalar:
            messagebox.showwarning("Uyarı",
                "mods klasöründe kopyalanacak dosya bulunamadı.\n"
                "Önce 'Mod Ekle' ile mod ekleyin.")
            return
        hedef = filedialog.askdirectory(title="Minecraft mods klasörünü seçin (hedef)")
        if not hedef:
            return

        self._kopyalama_aktif = True
        for b in (self._btn_yukle, self._btn_ekle,
                  self._btn_kaldir, self._btn_listele):
            b.set_state(False)

        threading.Thread(
            target=self._kopyala_thread,
            args=(dosyalar, hedef),
            daemon=True).start()

    def _kopyala_thread(self, dosyalar, hedef_dir):
        toplam = len(dosyalar)

        def ui(prog, mesaj):
            self.root.after(0, lambda p=prog, m=mesaj:
                            self._progress.set_progress(p, m))

        try:
            for i, ad in enumerate(dosyalar):
                src = os.path.join(MODS_KLASORU, ad)
                dst = os.path.join(hedef_dir, ad)
                boyut = max(os.path.getsize(src), 1)
                chunk = 32 * 1024
                yaz = 0
                with open(src, "rb") as fi, open(dst, "wb") as fo:
                    while True:
                        blok = fi.read(chunk)
                        if not blok:
                            break
                        fo.write(blok)
                        yaz += len(blok)
                        dosya_prog = yaz / boyut
                        genel = (i + dosya_prog) / toplam
                        ui(min(genel, 0.99), f"Kopyalanıyor: {ad}")

            ui(1.0, f"{toplam} mod kopyalandı.")
            self.root.after(0, lambda: self._durum.config(
                text=f"{toplam} mod yüklendi  →  {hedef_dir}", fg=BASARI))
        except Exception as e:
            ui(0.0, "Hata!")
            self.root.after(0, lambda: messagebox.showerror("Hata", str(e)))
        finally:
            self._kopyalama_aktif = False
            self.root.after(0, self._kopyalama_bitti)

    def _kopyalama_bitti(self):
        for b in (self._btn_yukle, self._btn_ekle,
                  self._btn_kaldir, self._btn_listele):
            b.set_state(True)

    def _sb_komut(self, *args):
        self._listbox.yview(*args)

    def _lb_scroll(self, first, last):
        self._scrollbar.set(float(first), float(last))

    def _lb_hover(self, event):
        try:
            self._listbox.activate(self._listbox.nearest(event.y))
        except Exception:
            pass

    # -----------------------------------------------------------------------
    #  Fabric — iş mantığı
    # -----------------------------------------------------------------------
    def _indir_ve_kur(self):
        if not os.path.isfile(FABRIC_INSTALLER):
            messagebox.showerror(
                "Hata",
                f"Fabric installer bulunamadı!\n\nAranan yol:\n{FABRIC_INSTALLER}\n\n"
                "fabric_installer/ klasöründe .exe dosyasının bulunduğundan emin olun.")
            return

        if not messagebox.askyesno(
                "Onayla",
                f"Fabric installer çalıştırılacak:\n\n"
                f"  {os.path.basename(FABRIC_INSTALLER)}\n\nDevam edilsin mi?"):
            return

        self._btn_kur.set_state(False)
        self._fab_progress.set_progress(0.15, "Başlatılıyor…")
        self._fab_durum.config(text="Fabric installer başlatılıyor…", fg=ACC)
        threading.Thread(target=self._fabric_thread, daemon=True).start()

    def _fabric_thread(self):
        def ui(p, s, renk=YAZI_SOLUK):
            self.root.after(0, lambda: self._fab_progress.set_progress(p, s))
            self.root.after(0, lambda: self._fab_durum.config(text=s, fg=renk))

        try:
            ui(0.35, "Installer çalışıyor…")
            proc = subprocess.Popen(
                [FABRIC_INSTALLER],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
            ui(0.6, "Installer penceresi bekleniyor…")
            _, err = proc.communicate()
            code = proc.returncode

            if code == 0:
                ui(1.0, "Kurulum tamamlandı!", BASARI)
                self.root.after(0, lambda: messagebox.showinfo(
                    "Başarılı", "Fabric installer başarıyla tamamlandı!"))
            else:
                ui(1.0, f"Installer kapandı (kod: {code})", UYARI)
                self.root.after(0, lambda: messagebox.showwarning(
                    "Bilgi",
                    f"Installer tamamlandı (çıkış kodu: {code}).\n"
                    "Kurulumun gerçekleşip gerçekleşmediğini kontrol edin."))
        except Exception as e:
            ui(0.0, f"Hata: {e}", HATA)
            self.root.after(0, lambda: messagebox.showerror("Hata", str(e)))
        finally:
            self.root.after(0, lambda: self._btn_kur.set_state(True))


def main():
    os.makedirs(MODS_KLASORU, exist_ok=True)
    root = tk.Tk()
    MinecraftModlamaMerkezi(root)
    root.mainloop()


if __name__ == "__main__":
    main()