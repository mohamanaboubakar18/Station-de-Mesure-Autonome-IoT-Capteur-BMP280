import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import serial
import serial.tools.list_ports
import threading
import re
import sqlite3
from datetime import datetime
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import csv
import queue
from collections import deque

# ── Configuration ──────────────────────────────────────────────────────────────
DB_NAME          = 'bmp280.db'
BAUDRATES        = [9600, 115200]
DEFAULT_BAUD     = 9600
MAX_POINTS       = 50
REFRESH_GRAPH_MS = 1000
MAX_LOG_LINES    = 300

# ── Palette ────────────────────────────────────────────────────────────────────
BG_ROOT   = "#12121f"
BG_DARK   = "#1a1a2e"
BG_PANEL  = "#1e2240"
BG_TOPBAR = "#161628"
BG_LOG    = "#111827"
BG_CARD   = "#252847"

ACCENT    = "#e94560"
CLR_TEMP  = "#e94560"
CLR_PRESS = "#34d399"
CLR_ALT   = "#60a5fa"
CLR_LOG   = "#fbbf24"
CLR_WHITE = "#dde3f0"
CLR_MUTED = "#55607a"
CLR_SEP   = "#252840"

# ── DB ─────────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS mesures
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT NOT NULL,
                  temperature REAL,
                  pression    REAL,
                  altitude    REAL)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON mesures(timestamp)')
    conn.commit()
    conn.close()

init_db()


def make_card(parent, accent_color=None, bg=BG_PANEL, padx=0, pady=0):
    """
    Carte avec coins simulés : frame extérieure sombre (BG_ROOT),
    frame intérieure colorée (bg). Pas de Canvas, pas de bug.
    L'accent est une barre de 3px en haut.
    """
    outer = tk.Frame(parent, bg=BG_ROOT, padx=2, pady=2)
    if accent_color:
        bar = tk.Frame(outer, bg=accent_color, height=3)
        bar.pack(fill="x")
    inner = tk.Frame(outer, bg=bg, padx=padx, pady=pady)
    inner.pack(fill="both", expand=True)
    return outer, inner


class BMP280App:
    def __init__(self, root):
        self.root = root
        self.root.title("BMP280 — Station de mesures")
        self.root.geometry("1400x860")
        self.root.minsize(1000, 660)
        self.root.configure(bg=BG_ROOT)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.serial_conn    = None
        self.reading        = False
        self.data_queue     = queue.Queue()
        self.serial_thread  = None
        self.graph_after_id = None

        self.temp_vals  = deque(maxlen=MAX_POINTS)
        self.press_vals = deque(maxlen=MAX_POINTS)
        self.alt_vals   = deque(maxlen=MAX_POINTS)
        self.time_axis  = deque(maxlen=MAX_POINTS)
        self.counter    = 0

        self.prev_temp  = None
        self.prev_press = None
        self.prev_alt   = None

        self.stat_temp  = {"min": None, "max": None, "avg": 0.0, "count": 0}
        self.stat_press = {"min": None, "max": None, "avg": 0.0, "count": 0}
        self.stat_alt   = {"min": None, "max": None, "avg": 0.0, "count": 0}

        self._apply_styles()
        self.create_widgets()
        self.refresh_ports()
        self.process_incoming_data()

    # ── Styles ─────────────────────────────────────────────────────────────────
    def _apply_styles(self):
        s = ttk.Style()
        s.theme_use("clam")

        s.configure("TNotebook", background=BG_ROOT, borderwidth=0)
        s.configure("TNotebook.Tab", background=BG_TOPBAR, foreground=CLR_MUTED,
                    padding=[20, 8], font=("Segoe UI", 9, "bold"))
        s.map("TNotebook.Tab",
              background=[("selected", BG_DARK)],
              foreground=[("selected", ACCENT)])

        s.configure("Treeview", background=BG_PANEL, foreground=CLR_WHITE,
                    fieldbackground=BG_PANEL, rowheight=28,
                    font=("Segoe UI", 9))
        s.configure("Treeview.Heading", background=BG_CARD, foreground=CLR_WHITE,
                    font=("Segoe UI", 9, "bold"), relief="flat")
        s.map("Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", CLR_WHITE)])

        for ori in ("Vertical", "Horizontal"):
            s.configure(f"{ori}.TScrollbar", background=BG_CARD,
                        troughcolor=BG_PANEL, arrowcolor=CLR_MUTED,
                        bordercolor=BG_PANEL)

        s.configure("TCombobox", fieldbackground=BG_CARD, background=BG_CARD,
                    foreground=CLR_WHITE, arrowcolor=CLR_WHITE,
                    bordercolor=BG_CARD)
        s.map("TCombobox",
              fieldbackground=[("readonly", BG_CARD)],
              selectbackground=[("readonly", BG_CARD)],
              selectforeground=[("readonly", CLR_WHITE)])

    # ── Widgets ────────────────────────────────────────────────────────────────
    def create_widgets(self):
        self._build_topbar()
        self._build_notebook()

    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=BG_TOPBAR, padx=16, pady=10)
        bar.pack(fill="x")

        tk.Label(bar, text="BMP280", bg=BG_TOPBAR, fg=ACCENT,
                 font=("Segoe UI", 14, "bold")).pack(side="left", padx=(0, 8))
        tk.Label(bar, text="Station de mesures", bg=BG_TOPBAR, fg=CLR_MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 18))
        self._vsep(bar)

        tk.Label(bar, text="Port :", bg=BG_TOPBAR, fg=CLR_MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(10, 5))
        self.combo_ports = ttk.Combobox(bar, width=10, state="readonly",
                                        font=("Segoe UI", 9))
        self.combo_ports.pack(side="left")
        self.btn_refresh = tk.Button(bar, text="↻", command=self.refresh_ports,
                  bg=BG_CARD, fg=CLR_MUTED, activebackground=ACCENT,
                  activeforeground=CLR_WHITE, relief="flat", bd=0,
                  width=3, cursor="hand2",
                  font=("Segoe UI", 12))
        self.btn_refresh.pack(side="left", padx=4)

        tk.Label(bar, text="Bauds :", bg=BG_TOPBAR, fg=CLR_MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(14, 5))
        self.combo_baud = ttk.Combobox(bar, width=8, state="readonly",
                                       values=[str(b) for b in BAUDRATES],
                                       font=("Segoe UI", 9))
        self.combo_baud.set(str(DEFAULT_BAUD))
        self.combo_baud.pack(side="left")
        self._vsep(bar)

        self.btn_connect = tk.Button(
            bar, text="⏻  Connecter", command=self.toggle_connection,
            bg=ACCENT, fg="#fff", activebackground="#c73652",
            activeforeground="#fff", relief="flat", bd=0,
            padx=14, pady=5, cursor="hand2",
            font=("Segoe UI", 9, "bold"))
        self.btn_connect.pack(side="left", padx=10)

        self.cv_dot = tk.Canvas(bar, width=10, height=10, bg=BG_TOPBAR,
                                highlightthickness=0)
        self.cv_dot.pack(side="left", padx=(10, 4))
        self.dot = self.cv_dot.create_oval(1, 1, 9, 9, fill=ACCENT, outline="")

        self.lbl_status = tk.Label(bar, text="Déconnecté", bg=BG_TOPBAR,
                                   fg=ACCENT, font=("Segoe UI", 9))
        self.lbl_status.pack(side="left")

        self.lbl_clock = tk.Label(bar, text="", bg=BG_TOPBAR, fg=CLR_MUTED,
                                  font=("Segoe UI", 9))
        self.lbl_clock.pack(side="right", padx=10)
        self._tick()

    def _vsep(self, parent):
        tk.Frame(parent, bg=CLR_SEP, width=1, height=24).pack(side="left", padx=8)

    def _tick(self):
        self.lbl_clock.config(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick)

    # ── Notebook ───────────────────────────────────────────────────────────────
    def _build_notebook(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(6, 8))

        self.tab_live    = ttk.Frame(self.nb)
        self.tab_history = ttk.Frame(self.nb)
        self.tab_stats   = ttk.Frame(self.nb)

        self.nb.add(self.tab_live,    text="  📡  Temps réel  ")
        self.nb.add(self.tab_history, text="  🗃  Historique  ")
        self.nb.add(self.tab_stats,   text="  📊  Statistiques  ")

        self._build_live_tab(self.tab_live)
        self._build_history_tab(self.tab_history)
        self._build_stats_tab(self.tab_stats)

    # ── Onglet Temps réel ──────────────────────────────────────────────────────
    def _build_live_tab(self, parent):
        # Fond de l'onglet
        parent.configure(style="TFrame")
        bg_tab = tk.Frame(parent, bg=BG_ROOT)
        bg_tab.pack(fill="both", expand=True)

        # ── Rangée de jauges ──
        gauge_row = tk.Frame(bg_tab, bg=BG_ROOT)
        gauge_row.pack(fill="x", padx=8, pady=(8, 6))
        gauge_row.columnconfigure(0, weight=1)
        gauge_row.columnconfigure(1, weight=1)
        gauge_row.columnconfigure(2, weight=1)

        self.gauge_temp  = self._make_gauge(gauge_row, "Température", "°C",  CLR_TEMP,  0)
        self.gauge_press = self._make_gauge(gauge_row, "Pression",    "hPa", CLR_PRESS, 1)
        self.gauge_alt   = self._make_gauge(gauge_row, "Altitude",    "m",   CLR_ALT,   2)

        # ── Grille 2×2 ──
        grid = tk.Frame(bg_tab, bg=BG_ROOT)
        grid.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)

        self.ax_temp_live,  self.canvas_temp  = self._make_graph_cell(grid, "Température", CLR_TEMP,  0, 0)
        self.ax_press_live, self.canvas_press = self._make_graph_cell(grid, "Pression",    CLR_PRESS, 0, 1)
        self.ax_alt_live,   self.canvas_alt   = self._make_graph_cell(grid, "Altitude",    CLR_ALT,   1, 0)
        self._make_log_cell(grid, 1, 1)

    # ── Jauge ──────────────────────────────────────────────────────────────────
    def _make_gauge(self, parent, title, unit, color, col):
        outer, inner = make_card(parent, accent_color=color, bg=BG_PANEL, padx=14, pady=8)
        outer.grid(row=0, column=col, padx=5, sticky="nsew")

        tk.Label(inner, text=title.upper(), bg=BG_PANEL, fg=CLR_MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        val_lbl = tk.Label(inner, text="--.--", bg=BG_PANEL, fg=color,
                           font=("Segoe UI", 26, "bold"))
        val_lbl.pack(anchor="w", pady=(2, 0))

        foot = tk.Frame(inner, bg=BG_PANEL)
        foot.pack(fill="x")
        tk.Label(foot, text=unit, bg=BG_PANEL, fg=CLR_MUTED,
                 font=("Segoe UI", 10)).pack(side="left")
        trend = tk.Label(foot, text="", bg=BG_PANEL, fg=CLR_MUTED,
                         font=("Segoe UI", 9))
        trend.pack(side="right")

        # On attache les refs sur outer pour y accéder depuis update_gauge
        outer.val_lbl = val_lbl
        outer.trend   = trend
        outer.color   = color
        return outer

    def _update_gauge(self, gauge, value, prev):
        gauge.val_lbl.config(text=f"{value:.2f}")
        if prev is not None:
            delta = value - prev
            if abs(delta) < 1e-4:
                gauge.trend.config(text="—", fg=CLR_MUTED)
            else:
                arrow = "▲" if delta > 0 else "▼"
                col   = CLR_TEMP if delta > 0 else CLR_ALT
                gauge.trend.config(text=f"{arrow} {abs(delta):.2f}", fg=col)

    # ── Cellule graphique ──────────────────────────────────────────────────────
    def _make_graph_cell(self, parent, title, color, row, col):
        outer, inner = make_card(parent, accent_color=color, bg=BG_PANEL)
        outer.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")

        # En-tête
        hdr = tk.Frame(inner, bg=BG_PANEL, padx=10, pady=5)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=color, width=3, height=14).pack(side="left", padx=(0, 8))
        tk.Label(hdr, text=title.upper(), bg=BG_PANEL, fg=color,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        # Figure matplotlib
        fig = Figure(facecolor=BG_PANEL, dpi=88)
        ax  = fig.add_subplot(111)
        ax.set_facecolor(BG_DARK)
        ax.tick_params(colors=CLR_MUTED, labelsize=7)
        for spine in ax.spines.values():
            spine.set_color(CLR_SEP)
        ax.grid(True, color=CLR_SEP, linestyle="--", alpha=0.9)
        fig.subplots_adjust(left=0.12, right=0.97, top=0.95, bottom=0.13)

        canvas = FigureCanvasTkAgg(fig, master=inner)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=(0, 5))
        canvas.get_tk_widget().configure(bg=BG_PANEL, highlightthickness=0)
        return ax, canvas

    # ── Cellule logs UART ──────────────────────────────────────────────────────
    def _make_log_cell(self, parent, row, col):
        outer, inner = make_card(parent, accent_color=CLR_LOG, bg=BG_LOG)
        outer.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")

        # En-tête
        hdr = tk.Frame(inner, bg=BG_LOG, padx=10, pady=5)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=CLR_LOG, width=3, height=14).pack(side="left", padx=(0, 8))
        tk.Label(hdr, text="LOGS UART", bg=BG_LOG, fg=CLR_LOG,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Button(hdr, text="✕ Clear", command=self._clear_logs,
                  bg=BG_CARD, fg=CLR_MUTED, activebackground=ACCENT,
                  activeforeground=CLR_WHITE, relief="flat", bd=0,
                  padx=8, pady=2, cursor="hand2",
                  font=("Segoe UI", 8)).pack(side="right", padx=4)
        self.lbl_log_count = tk.Label(hdr, text="0 ligne(s)", bg=BG_LOG,
                                      fg=CLR_MUTED, font=("Segoe UI", 8))
        self.lbl_log_count.pack(side="right", padx=6)

        # Séparateur
        tk.Frame(inner, bg=CLR_SEP, height=1).pack(fill="x")

        # Zone texte
        txt = tk.Frame(inner, bg=BG_LOG)
        txt.pack(fill="both", expand=True, padx=5, pady=5)

        self.log_text = tk.Text(
            txt, bg=BG_LOG, fg=CLR_LOG,
            insertbackground=CLR_LOG, selectbackground=BG_CARD,
            font=("Consolas", 9), relief="flat", bd=0,
            wrap="none", state="disabled", cursor="arrow")

        vs = ttk.Scrollbar(txt, orient="vertical",   command=self.log_text.yview)
        hs = ttk.Scrollbar(txt, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        self.log_text.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        txt.rowconfigure(0, weight=1)
        txt.columnconfigure(0, weight=1)

        self.log_text.tag_configure("bmp",   foreground=CLR_LOG)
        self.log_text.tag_configure("info",  foreground="#60a5fa")
        self.log_text.tag_configure("warn",  foreground="#fb923c")
        self.log_text.tag_configure("error", foreground=CLR_TEMP)
        self.log_text.tag_configure("sys",   foreground="#a0aec0")
        self.log_text.tag_configure("ts",    foreground=CLR_MUTED)
        self.log_line_count = 0

    def _append_log(self, raw_line):
        self.root.after(0, self._do_append_log, raw_line)

    def _do_append_log(self, raw_line):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        ll = raw_line.lower()
        tag = ("bmp"   if "bmp280" in ll else
               "error" if any(w in ll for w in ("error", "err", "fail")) else
               "warn"  if "warn" in ll else
               "sys"   if raw_line.startswith("===") else "info")
        self.log_text.insert("end", f"[{ts}] ", "ts")
        self.log_text.insert("end", raw_line + "\n", tag)
        self.log_line_count += 1
        if self.log_line_count > MAX_LOG_LINES:
            self.log_text.delete("1.0", "2.0")
            self.log_line_count -= 1
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.lbl_log_count.config(text=f"{self.log_line_count} ligne(s)")

    def _clear_logs(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.log_line_count = 0
        self.lbl_log_count.config(text="0 ligne(s)")

    # ── Onglet Historique ──────────────────────────────────────────────────────
    def _build_history_tab(self, parent):
        bg = tk.Frame(parent, bg=BG_ROOT)
        bg.pack(fill="both", expand=True)

        tf = tk.Frame(bg, bg=BG_ROOT)
        tf.pack(fill="both", expand=True, padx=10, pady=10)

        cols = ("id", "timestamp", "temperature", "pression", "altitude")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=18)
        for col, text, w, anchor in [
                ("id",          "ID",               55,  "center"),
                ("timestamp",   "Horodatage",       210, "w"),
                ("temperature", "Température (°C)", 145, "center"),
                ("pression",    "Pression (hPa)",   145, "center"),
                ("altitude",    "Altitude (m)",     125, "center")]:
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=w, minwidth=50, anchor=anchor,
                             stretch=(col == "timestamp"))
        self.tree.tag_configure("odd",  background="#181830")
        self.tree.tag_configure("even", background="#1e2240")

        vs = ttk.Scrollbar(tf, orient="vertical",   command=self.tree.yview)
        hs = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)

        bf = tk.Frame(bg, bg=BG_ROOT, pady=6)
        bf.pack(fill="x", padx=10)
        self._btn(bf, "↺  Rafraîchir",      self.load_history_table, BG_CARD  ).pack(side="left", padx=4)
        self._btn(bf, "✕  Effacer la base", self.clear_database,     ACCENT   ).pack(side="left", padx=4)
        self._btn(bf, "⬇  Exporter CSV",    self.export_to_csv,      "#166534").pack(side="left", padx=4)
        self.lbl_row_count = tk.Label(bf, text="0 mesure(s)", bg=BG_ROOT,
                                      fg=CLR_MUTED, font=("Segoe UI", 9))
        self.lbl_row_count.pack(side="right", padx=10)

    # ── Onglet Statistiques ────────────────────────────────────────────────────
    def _build_stats_tab(self, parent):
        bg = tk.Frame(parent, bg=BG_ROOT)
        bg.pack(fill="both", expand=True)

        outer = tk.Frame(bg, bg=BG_ROOT)
        outer.pack(fill="both", expand=True, padx=20, pady=20)
        self.stat_labels = {}

        for ci, (name, unit, color) in enumerate([
                ("Température", "°C",  CLR_TEMP),
                ("Pression",    "hPa", CLR_PRESS),
                ("Altitude",    "m",   CLR_ALT)]):
            host = tk.Frame(outer, bg=BG_ROOT)
            host.grid(row=0, column=ci, padx=10, pady=10, sticky="nsew")

            card_outer, inner = make_card(host, accent_color=color, bg=BG_PANEL, padx=18, pady=14)
            card_outer.pack(fill="both", expand=True)

            tk.Label(inner, text=name, bg=BG_PANEL, fg=color,
                     font=("Segoe UI", 12, "bold")).pack(anchor="w")
            tk.Label(inner, text=unit, bg=BG_PANEL, fg=CLR_MUTED,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

            labels = {}
            for key, lbl_txt in [("min","Minimum"),("max","Maximum"),
                                  ("avg","Moyenne"),("count","Mesures")]:
                row = tk.Frame(inner, bg=BG_PANEL)
                row.pack(fill="x", pady=3)
                tk.Frame(row, bg=CLR_SEP, height=1).pack(fill="x", pady=(0, 3))
                tk.Label(row, text=lbl_txt, bg=BG_PANEL, fg=CLR_MUTED,
                         font=("Segoe UI", 9), anchor="w").pack(side="left")
                v = tk.Label(row, text="—", bg=BG_PANEL,
                             fg=color if key != "count" else CLR_WHITE,
                             font=("Segoe UI", 11, "bold"))
                v.pack(side="right")
                labels[key] = v
            self.stat_labels[name] = labels

        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(2, weight=1)
        self._btn(outer, "↺  Actualiser", self.update_stats_display, BG_CARD
                  ).grid(row=1, column=1, pady=20)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _btn(self, parent, text, cmd, bg):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=CLR_WHITE,
                         activebackground=ACCENT, activeforeground=CLR_WHITE,
                         relief="flat", bd=0, padx=10, pady=5,
                         cursor="hand2", font=("Segoe UI", 9))

    # ── Traitement données ─────────────────────────────────────────────────────
    def process_incoming_data(self):
        try:
            while True:
                item = self.data_queue.get_nowait()
                if item[0] == "error":
                    self._on_serial_error()
                    break
                temp, press, alt = item
                self._update_gauge(self.gauge_temp,  temp,  self.prev_temp)
                self._update_gauge(self.gauge_press, press, self.prev_press)
                self._update_gauge(self.gauge_alt,   alt,   self.prev_alt)
                self.prev_temp, self.prev_press, self.prev_alt = temp, press, alt
                self.store_measurement(temp, press, alt)
                self.temp_vals.append(temp)
                self.press_vals.append(press)
                self.alt_vals.append(alt)
                self.time_axis.append(self.counter)
                self.counter += 1
        except queue.Empty:
            pass
        self.update_stats()
        self.root.after(200, self.process_incoming_data)

    def _on_serial_error(self):
        self.reading = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        self.btn_connect.config(text="⏻  Connecter", bg=ACCENT)
        self.lbl_status.config(text="Erreur série", fg=ACCENT)
        self.cv_dot.itemconfig(self.dot, fill=ACCENT)
        self.combo_ports.config(state="readonly")
        self.combo_baud.config(state="readonly")
        messagebox.showerror("Erreur série", "La connexion série a été perdue.")

    # ── Graphiques ─────────────────────────────────────────────────────────────
    def start_graph_updates(self):
        self.update_live_graph()

    def update_live_graph(self):
        if not self.reading:
            self.graph_after_id = None
            return
        if self.time_axis:
            x = list(self.time_axis)
            for ax, canvas, data, col, unit in [
                    (self.ax_temp_live,  self.canvas_temp,  list(self.temp_vals),  CLR_TEMP,  "°C"),
                    (self.ax_press_live, self.canvas_press, list(self.press_vals), CLR_PRESS, "hPa"),
                    (self.ax_alt_live,   self.canvas_alt,   list(self.alt_vals),   CLR_ALT,   "m")]:
                ax.clear()
                ax.plot(x, data, color=col, linewidth=1.5,
                        marker="o", markersize=2.5,
                        markerfacecolor=col, markeredgewidth=0)
                mn = min(data)
                ax.fill_between(x, data, mn - abs(max(data) - mn) * 0.05,
                                color=col, alpha=0.10)
                ax.set_facecolor(BG_DARK)
                ax.tick_params(colors=CLR_MUTED, labelsize=7)
                for spine in ax.spines.values():
                    spine.set_color(CLR_SEP)
                ax.grid(True, color=CLR_SEP, linestyle="--", alpha=0.9)
                ax.set_ylabel(unit, color=col, fontsize=7, labelpad=4)
                canvas.draw()
        self.graph_after_id = self.root.after(REFRESH_GRAPH_MS, self.update_live_graph)

    # ── Connexion série ────────────────────────────────────────────────────────
    def toggle_connection(self):
        if not self.reading:
            port = self.combo_ports.get()
            if not port:
                messagebox.showerror("Erreur", "Veuillez sélectionner un port COM.")
                return
            baud = int(self.combo_baud.get())
            try:
                self.serial_conn = serial.Serial(port, baud, timeout=1)
                self.reading = True
                self.serial_thread = threading.Thread(target=self.serial_reader, daemon=True)
                self.serial_thread.start()
                self.btn_connect.config(text="⏻  Déconnecter", bg="#7f1d1d")
                self.lbl_status.config(text=f"Connecté — {port} @ {baud} bds", fg=CLR_PRESS)
                self.cv_dot.itemconfig(self.dot, fill=CLR_PRESS)
                self.combo_ports.config(state="disabled")
                self.combo_baud.config(state="disabled")
                self._append_log(f"=== Connexion ouverte : {port} @ {baud} bds ===")
                self.start_graph_updates()
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible d'ouvrir le port :\n{e}")
        else:
            self.reading = False
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
            self.btn_connect.config(text="⏻  Connecter", bg=ACCENT)
            self.lbl_status.config(text="Déconnecté", fg=ACCENT)
            self.cv_dot.itemconfig(self.dot, fill=ACCENT)
            self.combo_ports.config(state="readonly")
            self.combo_baud.config(state="readonly")
            self._append_log("=== Connexion fermée ===")
            if self.graph_after_id:
                self.root.after_cancel(self.graph_after_id)

    def serial_reader(self):
        pattern = re.compile(
            r'BMP280:\s+T=([\d\.\-]+)\s+C\s+P=([\d\.\-]+)\s+hPa\s+Alt=([\d\.\-]+)\s+m')
        while self.reading:
            try:
                if self.serial_conn and self.serial_conn.is_open:
                    line = self.serial_conn.readline().decode('utf-8', errors='replace').strip()
                    if not line:
                        continue
                    self._append_log(line)
                    m = pattern.search(line)
                    if m:
                        self.data_queue.put((float(m.group(1)),
                                            float(m.group(2)),
                                            float(m.group(3))))
            except serial.SerialException:
                self.data_queue.put(("error",))
                break
            except Exception:
                continue

    # ── DB ─────────────────────────────────────────────────────────────────────
    def store_measurement(self, temp, press, alt):
        now = datetime.now().isoformat(timespec="seconds")
        try:
            conn = sqlite3.connect(DB_NAME)
            conn.execute(
                "INSERT INTO mesures (timestamp,temperature,pression,altitude) VALUES (?,?,?,?)",
                (now, temp, press, alt))
            conn.commit()
        except sqlite3.Error as e:
            print("DB error:", e)
        finally:
            conn.close()

    def load_history_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        try:
            conn = sqlite3.connect(DB_NAME)
            rows = conn.execute(
                "SELECT * FROM mesures ORDER BY id DESC LIMIT 200").fetchall()
            conn.close()
            for i, r in enumerate(reversed(rows)):
                self.tree.insert("", "end", values=(
                    r[0], r[1],
                    f"{r[2]:.2f}" if r[2] is not None else "—",
                    f"{r[3]:.2f}" if r[3] is not None else "—",
                    f"{r[4]:.1f}" if r[4] is not None else "—",
                ), tags=("odd" if i % 2 == 0 else "even",))
            self.lbl_row_count.config(text=f"{len(rows)} mesure(s) affichée(s)")
        except sqlite3.Error as e:
            messagebox.showerror("Erreur DB", str(e))

    def clear_database(self):
        if messagebox.askyesno("Confirmation",
                               "Supprimer toutes les données ?"):
            try:
                conn = sqlite3.connect(DB_NAME)
                conn.execute("DELETE FROM mesures")
                conn.commit()
                conn.close()
                self.load_history_table()
                messagebox.showinfo("Succès", "Base de données effacée.")
            except sqlite3.Error as e:
                messagebox.showerror("Erreur", str(e))

    def export_to_csv(self):
        try:
            conn = sqlite3.connect(DB_NAME)
            rows = conn.execute("SELECT * FROM mesures ORDER BY id").fetchall()
            conn.close()
            if not rows:
                messagebox.showwarning("Aucune donnée", "La base est vide.")
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv"), ("Tous", "*.*")],
                title="Exporter les mesures")
            if not path:
                return
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f, delimiter=';')
                w.writerow(["ID","Horodatage","Température (°C)","Pression (hPa)","Altitude (m)"])
                for r in rows:
                    w.writerow([r[0], r[1],
                                f"{r[2]:.2f}" if r[2] is not None else "",
                                f"{r[3]:.2f}" if r[3] is not None else "",
                                f"{r[4]:.1f}" if r[4] is not None else ""])
            messagebox.showinfo("Export terminé", f"✅ {len(rows)} mesure(s) :\n{path}")
        except Exception as e:
            messagebox.showerror("Erreur d'export", str(e))

    # ── Stats ──────────────────────────────────────────────────────────────────
    def update_stats(self):
        if not self.temp_vals:
            return
        for vals, stat in zip(
                (self.temp_vals, self.press_vals, self.alt_vals),
                (self.stat_temp, self.stat_press, self.stat_alt)):
            v = list(vals)
            stat.update({"min": min(v), "max": max(v),
                         "avg": sum(v)/len(v), "count": len(v)})
        self.update_stats_display()

    def update_stats_display(self):
        for name, stat in [("Température", self.stat_temp),
                            ("Pression",    self.stat_press),
                            ("Altitude",    self.stat_alt)]:
            lbl = self.stat_labels.get(name)
            if not lbl:
                continue
            if stat["min"] is not None:
                lbl["min"].config(text=f"{stat['min']:.2f}")
                lbl["max"].config(text=f"{stat['max']:.2f}")
                lbl["avg"].config(text=f"{stat['avg']:.2f}")
                lbl["count"].config(text=str(stat["count"]))
            else:
                for k in ("min","max","avg"):
                    lbl[k].config(text="—")
                lbl["count"].config(text="0")

    # ── Ports ──────────────────────────────────────────────────────────────────
    def refresh_ports(self):
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.config(fg=ACCENT)
            self.root.after(300, lambda: self.btn_refresh.config(fg=CLR_MUTED))
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.combo_ports['values'] = ports
        if ports:
            if not self.reading:
                current = self.combo_ports.get()
                if current in ports:
                    self.combo_ports.set(current)
                else:
                    self.combo_ports.current(0)
        else:
            self.combo_ports.set("")
            if hasattr(self, 'btn_refresh'):
                self.btn_refresh.config(fg=CLR_TEMP)
                self.root.after(600, lambda: self.btn_refresh.config(fg=CLR_MUTED))






    def on_closing(self):
        self.reading = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        if self.graph_after_id:
            self.root.after_cancel(self.graph_after_id)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app  = BMP280App(root)
    root.mainloop()