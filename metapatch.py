"""
MetaPatch v1.0 — HEVC/x265 Metadata Patcher
by MetaPatch Team

Features:
  · x265 encoder string patching (single + batch)
  · Full HEVC options builder (collapsible sub-tabs)
  · mkvmerge remux pass (updates Writing Application)
  · H.264 track remover
  · Custom preset maker
  · Splash screen (drop images in splash_images/)
  · Credits & Disclaimer tab
  · Tips system
  · Light/Dark theme (fully working)

Requires: pip install customtkinter pillow
Build EXE:
  pyinstaller --onefile --windowed --name MetaPatch ^
    --collect-all customtkinter ^
    --add-data "splash_images;splash_images" ^
    metapatch.py
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk
import shutil, threading, json, os, sys, re, subprocess, random, time
from pathlib import Path
from datetime import datetime

# ── App identity ────────────────────────────────────────────────────────────
APP_NAME    = "MetaPatch"
APP_VERSION = "1.0.0"
APP_AUTHOR  = "MetaPatch Team"

# ── Colours ─────────────────────────────────────────────────────────────────
DARK = dict(
    ACCENT="#00C9A7", ACCENT2="#0095FF", ACCENT3="#B060FF",
    BG_DARK="#0D0F14", BG_MID="#13161E", BG_PANEL="#1A1E2C",
    BG_CARD="#202436",
    TEXT_PRI="#E8EAF0", TEXT_SEC="#8891A8", TEXT_DIM="#454D64",
    ERR="#FF5B5B", WARN="#FFB347", OK="#00C9A7",
)
LIGHT = dict(
    ACCENT="#007A65", ACCENT2="#0060CC", ACCENT3="#7030CC",
    BG_DARK="#F0F2F5", BG_MID="#E4E8EE", BG_PANEL="#FFFFFF",
    BG_CARD="#F8F9FB",
    TEXT_PRI="#1A1D26", TEXT_SEC="#4A5068", TEXT_DIM="#9099B0",
    ERR="#CC2222", WARN="#CC7700", OK="#007A65",
)
C = dict(DARK)   # active palette — mutated on theme switch

SCAN_SIZE = 8 * 1024 * 1024
KEY       = b"x265 (build "

TIPS = [
    "💡 Drop images into splash_images/ to show on startup.",
    "💡 Use 'Generate from HEVC tab' to auto-build options strings.",
    "💡 mkvmerge remux updates Writing Application to mkvmerge.",
    "💡 Batch mode supports recursive folder scanning.",
    "💡 Backup files are created as filename.ext.backup automatically.",
    "💡 Custom presets are saved and persist between sessions.",
    "💡 H.264 remover strips H.264 tracks keeping HEVC only.",
    "💡 Hold mouse over any HEVC option label to see a tooltip.",
    "💡 The Raw Block tab shows hex + ASCII of the original block.",
    "💡 Patch history stores last 100 operations with full details.",
    "💡 Use 'Save As' to write a new file without touching the original.",
    "💡 CRF 18–24 is visually lossless for most content.",
    "💡 --tune grain preserves film grain without raising bitrate much.",
    "💡 veryslow preset takes much longer but meaningfully improves quality.",
    "💡 --hdr10 --hdr10-opt together enable full HDR10 signalling.",
]

CONFIG_PATH = Path(os.path.expanduser("~")) / ".metapatch_v1.json"

def load_cfg():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_cfg(d):
    try:
        with open(CONFIG_PATH,"w") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

# ── x265 binary helpers ─────────────────────────────────────────────────────

def is_ascii(b): return 32 <= b <= 126

def find_x265_block(buf, start_from=0):
    pos = buf.find(KEY, start_from)
    if pos == -1: return None
    s = pos
    while s > 0 and is_ascii(buf[s-1]): s -= 1
    e = pos
    while e < len(buf) and is_ascii(buf[e]): e += 1
    return s, e, buf[s:e]

def build_rep(olen, build, custom, opts, prefix, copyright_txt, url_txt):
    base = f"{prefix}x265 (build {build}) -"
    if custom: base += f" {custom}"
    base += f" - H.265/HEVC codec - {copyright_txt} - {url_txt} - options:"
    if opts:   base += f" {opts}"
    enc = base.encode("ascii","replace")
    if len(enc) > olen: return None, len(enc)
    return enc.ljust(olen, b" "), len(enc)

# ── HEVC option definitions ──────────────────────────────────────────────────
# (key, label, widget, default, min, max, choices, tip)
HEVC_SECTIONS = {
    "Preset & Profile": [
        ("preset",      "Preset",          "combo",   "medium",  0,0, ["ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow","placebo"], "Overall speed vs quality tradeoff"),
        ("tune",        "Tune",            "combo",   "none",    0,0, ["none","film","animation","grain","stillimage","fastdecode","zerolatency","psnr","ssim"], "Psychovisual content tuning"),
        ("profile",     "Profile",         "combo",   "auto",    0,0, ["auto","main","main10","main444-8","main444-10","main444-16"], "HEVC profile"),
        ("level-idc",   "Level IDC",       "combo",   "auto",    0,0, ["auto","1","2","2.1","3","3.1","4","4.1","5","5.1","5.2","6","6.1","6.2"], "HEVC level"),
        ("high-tier",   "High Tier",       "check",   False, 0,0,[], "Use high tier for given level"),
        ("no-high-tier","No High Tier",    "check",   False, 0,0,[], "Force main tier"),
        ("allow-non-conformance","Non-Conformance","check",False,0,0,[], "Allow non-conforming bitstreams"),
        ("include-preset-in-stats","Preset in Stats","check",False,0,0,[],"Include preset in stats file"),
        ("preset-include-options","Preset Include Options","check",False,0,0,[],"Include all preset option changes"),
    ],
    "Rate Control": [
        ("crf",         "CRF",             "fslider", 28.0, 0.0,51.0,[], "Constant Rate Factor (0=lossless, 28=default, 51=worst)"),
        ("crf-max",     "CRF Max",         "fslider", 0.0,  0.0,51.0,[], "CRF ceiling when VBV is active"),
        ("crf-min",     "CRF Min",         "fslider", 0.0,  0.0,51.0,[], "CRF floor (prevents going too low)"),
        ("bitrate",     "Bitrate (kbps)",  "entry",   "",   0,0,[],   "Target average bitrate in kbps"),
        ("vbv-maxrate", "VBV Max Rate",    "entry",   "",   0,0,[],   "VBV maximum bitrate kbps"),
        ("vbv-bufsize", "VBV Buf Size",    "entry",   "",   0,0,[],   "VBV buffer size in kbits"),
        ("vbv-init",    "VBV Init",        "fslider", 0.9,  0.0,1.0,[],"Initial VBV buffer occupancy"),
        ("qp",          "Force QP",        "islider", 0,    0,69,[],  "Force constant QP (0=disabled)"),
        ("qpmin",       "QP Min",          "islider", 0,    0,69,[],  "Minimum quantizer"),
        ("qpmax",       "QP Max",          "islider", 69,   0,69,[],  "Maximum quantizer"),
        ("qpstep",      "QP Step",         "islider", 4,    1,32,[],  "Max QP step between frames"),
        ("qblur",       "QP Blur",         "fslider", 0.5,  0.0,99.0,[],"Quant curve blur"),
        ("cplxblur",    "Complexity Blur", "fslider", 20.0, 0.0,999.0,[],"QP fluctuation reduction strength"),
        ("pass",        "Multi-pass",      "combo",   "none",0,0,["none","1","2","3"],"Multi-pass encoding pass"),
        ("stats",       "Stats File",      "entry",   "",   0,0,[],   "Stats filename for multi-pass"),
        ("slow-firstpass","Slow 1st Pass", "check",   False,0,0,[],   "Full analysis on first pass"),
        ("ipratio",     "I:P Ratio",       "fslider", 1.4,  0.5,3.0,[],"I-frame to P-frame QP ratio"),
        ("pbratio",     "P:B Ratio",       "fslider", 1.3,  0.5,3.0,[],"P-frame to B-frame QP ratio"),
        ("ratetol",     "Rate Tolerance",  "fslider", 1.0,  0.1,100.0,[],"ABR rate tolerance"),
        ("lossless",    "Lossless",        "check",   False,0,0,[],   "True lossless (CRF 0 with no quant)"),
    ],
    "AQ / Zones": [
        ("aq-mode",     "AQ Mode",         "combo",   "2",  0,0,["0","1","2","3","4"],"Adaptive quantization mode (2=default)"),
        ("aq-strength", "AQ Strength",     "fslider", 1.0,  0.0,3.0,[],"AQ strength"),
        ("aq-motion",   "AQ Motion",       "check",   False,0,0,[],   "AQ based on motion vectors"),
        ("hevc-aq",     "HEVC AQ",         "check",   False,0,0,[],   "HEVC AQ compatibility mode"),
        ("qg-size",     "QG Size",         "combo",   "32", 0,0,["8","16","32","64"],"Quantization group size"),
        ("cbqpoffs",    "CB QP Offset",    "islider", 0,-12,12,[],    "Cb component QP offset"),
        ("crqpoffs",    "CR QP Offset",    "islider", 0,-12,12,[],    "Cr component QP offset"),
        ("zones",       "Zones",           "entry",   "",   0,0,[],   "Zone overrides e.g. 0,100,crf=20/101,200,crf=30"),
        ("zonefile",    "Zone File",       "entry",   "",   0,0,[],   "Zone definitions file path"),
        ("rc-grain",    "RC Grain",        "check",   False,0,0,[],   "Grain-friendly rate control"),
        ("const-vbv",   "Const VBV",       "check",   False,0,0,[],   "Constant VBV (strict HRD)"),
    ],
    "GOP / Frame": [
        ("keyint",      "Max Keyint",      "islider", 250,  1,999,[],  "Max keyframe (IDR) interval"),
        ("min-keyint",  "Min Keyint",      "islider", 0,    0,250,[],  "Min keyframe interval (0=auto)"),
        ("gop-lookahead","GOP Lookahead",  "islider", 0,    0,16,[],   "Frames for GOP decisions"),
        ("no-open-gop", "Closed GOP",      "check",   False,0,0,[],   "Use closed GOPs"),
        ("bframes",     "B-frames",        "islider", 4,    0,16,[],   "Max consecutive B-frames"),
        ("bframe-bias", "B-frame Bias",    "islider", 0,-90,100,[],   "Bias B-frame decisions"),
        ("b-adapt",     "B Adapt",         "combo",   "2",  0,0,["0","1","2"],"B-frame adaptive mode"),
        ("bpyramid",    "B Pyramid",       "check",   False,0,0,[],   "B-frames as references"),
        ("ref",         "Ref Frames",      "islider", 3,    1,16,[],   "Number of reference frames"),
        ("limit-refs",  "Limit Refs",      "islider", 3,    0,3,[],    "Limit ME reference frames"),
        ("scenecut",    "Scenecut",        "islider", 40,   0,100,[],  "Scenecut sensitivity"),
        ("no-scenecut", "Disable Scenecut","check",   False,0,0,[],   "Disable adaptive I-frame placement"),
        ("hist-scenecut","Hist Scenecut",  "check",   False,0,0,[],   "Histogram-based scenecut"),
        ("intra-refresh","Intra Refresh",  "check",   False,0,0,[],   "Use intra-refresh instead of IDR"),
        ("rc-grain",    "RC Grain",        "check",   False,0,0,[],   "Grain-friendly rate control"),
    ],
    "Motion Est.": [
        ("me",          "ME Algorithm",    "combo",   "hex",0,0,["dia","hex","umh","star","sea","full"],"Motion estimation algorithm"),
        ("merange",     "ME Range",        "islider", 57,   0,32768,[],"Motion search range in pixels"),
        ("subme",       "Sub-ME",          "islider", 2,    0,7,[],    "Sub-pixel motion refinement level"),
        ("max-merge",   "Max Merge",       "islider", 2,    1,5,[],    "Max merge candidates"),
        ("temporal-mvp","Temporal MVP",    "check",   True, 0,0,[],   "Temporal motion vector prediction"),
        ("hme",         "Hierarchical ME", "check",   False,0,0,[],   "Hierarchical motion estimation"),
        ("hme-search",  "HME Search",      "combo",   "hex",0,0,["dia","hex","umh","star","sea","full"],"HME search method"),
        ("hme-range",   "HME Range",       "entry",   "",   0,0,[],   "HME range per level e.g. 16,32,48"),
        ("weight-p",    "Weighted P",      "check",   True, 0,0,[],   "Weighted prediction P-frames"),
        ("weight-b",    "Weighted B",      "check",   False,0,0,[],   "Weighted prediction B-frames"),
        ("early-skip",  "Early Skip",      "check",   False,0,0,[],   "Early SKIP detection"),
        ("fast-intra",  "Fast Intra",      "check",   False,0,0,[],   "Fast intra-prediction"),
        ("no-amp",      "Disable AMP",     "check",   False,0,0,[],   "Disable asymmetric motion partitions"),
        ("no-rect",     "Disable Rect",    "check",   False,0,0,[],   "Disable rectangular motion partitions"),
        ("rdpenalty",   "RD Penalty",      "islider", 0,    0,2,[],    "Penalty for 32x32 intra TUs"),
        ("tskip",       "Transform Skip",  "check",   False,0,0,[],   "Transform skip for intra CUs"),
    ],
    "Quality / RDO": [
        ("rd",          "RD Level",        "islider", 3,    0,6,[],    "Rate-distortion optimisation level"),
        ("rdoq-level",  "RDOQ Level",      "islider", 0,    0,2,[],    "RDOQ strength"),
        ("psy-rd",      "Psy-RD",          "fslider", 2.0,  0.0,5.0,[],"Psychovisual RD strength"),
        ("psy-rdoq",    "Psy-RDOQ",        "fslider", 0.0,  0.0,50.0,[],"Psychovisual RDOQ strength"),
        ("no-psy",      "Disable Psy",     "check",   False,0,0,[],   "Disable psychovisual optimisations"),
        ("tu-intra-depth","TU Intra Depth","islider", 1,    1,4,[],    "Max TU recursion depth intra"),
        ("tu-inter-depth","TU Inter Depth","islider", 1,    1,4,[],    "Max TU recursion depth inter"),
        ("limit-tu",    "Limit TU",        "islider", 0,    0,4,[],    "Limit TU recursion in intra CUs"),
        ("limit-modes", "Limit Modes",     "check",   False,0,0,[],   "Limit modes checked in intra CUs"),
        ("ssim-rd",     "SSIM-RD",         "check",   False,0,0,[],   "SSIM-optimised RD decisions"),
        ("cu-lossless", "CU Lossless",     "check",   False,0,0,[],   "Try lossless per CU"),
        ("rskip",       "Residual Skip",   "islider", 1,    0,2,[],    "Residual skip mode"),
        ("splitrd-skip","SplitRD Skip",    "check",   False,0,0,[],   "Skip split RD at low depth"),
    ],
    "Filters": [
        ("deblock",     "Deblock Strength","islider", 0,   -6,6,[],    "Deblock filter strength"),
        ("no-deblock",  "Disable Deblock", "check",   False,0,0,[],   "Disable deblock filter"),
        ("no-sao",      "Disable SAO",     "check",   False,0,0,[],   "Disable SAO filter"),
        ("limit-sao",   "Limit SAO",       "check",   False,0,0,[],   "Limit SAO to save time"),
        ("selective-sao","Selective SAO",  "islider", 0,    0,4,[],    "SAO selection level"),
        ("sao-non-deblock","SAO Non-Deblock","check", False,0,0,[],   "SAO without deblock reapply"),
        ("no-strong-intra-smoothing","No Intra Smooth","check",False,0,0,[],"Disable 32x32 intra smoothing"),
    ],
    "Lookahead / Threads": [
        ("lookahead",   "Lookahead",       "islider", 20,   0,250,[],  "Lookahead frame count"),
        ("rc-lookahead","RC Lookahead",    "islider", 20,   0,250,[],  "Rate-control lookahead"),
        ("lookahead-slices","LA Slices",   "islider", 4,    0,16,[],   "Lookahead slices per frame"),
        ("b-intra",     "B Intra",         "check",   False,0,0,[],   "Intra prediction in B-frames"),
        ("pools",       "Thread Pools",    "entry",   "",   0,0,[],    "Thread pool sizes e.g. 8 or 4,4"),
        ("frame-threads","Frame Threads",  "islider", 0,    0,16,[],   "Parallel frame threads (0=auto)"),
        ("wpp",         "WPP",             "check",   True, 0,0,[],   "Wavefront parallel processing"),
        ("pme",         "Parallel ME",     "check",   False,0,0,[],   "Parallel motion estimation"),
        ("pmode",       "Parallel Mode",   "check",   False,0,0,[],   "Parallel mode analysis"),
        ("slices",      "Slices",          "islider", 1,    1,16,[],   "Slices per frame"),
    ],
    "HDR / Colour": [
        ("hdr10",       "HDR10",           "check",   False,0,0,[],   "HDR10 signalling in SEI"),
        ("hdr10-opt",   "HDR10 Optimize",  "check",   False,0,0,[],   "HDR10 content optimisation"),
        ("master-display","Master Display", "entry",   "",   0,0,[],   "SMPTE 2086 display e.g. G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)"),
        ("max-cll",     "Max CLL/FALL",    "entry",   "",   0,0,[],   "Max content light level e.g. 1000,400"),
        ("min-luma",    "Min Luma",        "islider", 0,    0,65535,[],"Minimum luma value"),
        ("max-luma",    "Max Luma",        "islider", 255,  0,65535,[],"Maximum luma value"),
        ("output-depth","Output Depth",    "combo",   "auto",0,0,["auto","8","10","12"],"Output bit depth"),
        ("input-csp",   "Chroma Subsampling","combo","auto",0,0,["auto","i400","i420","i422","i444"],"Input chroma format"),
        ("range",       "Luma Range",      "combo",   "auto",0,0,["auto","limited","full"],"Luma signal range"),
        ("colorprim",   "Color Primaries", "combo",   "undef",0,0,["undef","bt709","bt2020","smpte170m","smpte240m","film","bt470m","bt470bg","smpte428","smpte431","smpte432"],"Colour primaries"),
        ("transfer",    "Transfer",        "combo",   "undef",0,0,["undef","bt709","bt2020-10","bt2020-12","smpte2084","arib-std-b67","linear","log100","smpte170m","smpte240m"],"Transfer characteristics"),
        ("colormatrix", "Color Matrix",    "combo",   "undef",0,0,["undef","bt709","bt2020nc","bt2020c","smpte170m","smpte240m","gbr","ycgco","ictcp"],"Colour matrix"),
        ("chromaloc",   "Chroma Location", "islider", 0,    0,5,[],    "Chroma sample location"),
        ("video-signal-type-preset","Signal Preset","combo","auto",0,0,["auto","SDR","HDR10","HLG","SDR-TV","HDR10-TV","HLG-TV"],"Video signal type preset"),
        ("dhdr10-info", "DHDR10 Info",     "entry",   "",   0,0,[],   "DHDR10 SEI JSON file path"),
        ("dhdr10-opt",  "DHDR10 Optimize", "check",   False,0,0,[],   "DHDR10 optimisation"),
    ],
    "Output / SEI": [
        ("repeat-headers","Repeat Headers","check",   False,0,0,[],   "Emit SPS/PPS/VPS every IDR"),
        ("aud",         "AUD NALs",        "check",   False,0,0,[],   "Access unit delimiter NALs"),
        ("annexb",      "Annex B",         "check",   True, 0,0,[],   "Annex B byte-stream output"),
        ("info",        "Encoder Info SEI","check",   True, 0,0,[],   "Emit encoder version/options SEI"),
        ("hash",        "Frame Hash SEI",  "combo",   "none",0,0,["none","md5","crc","checksum"],"Decoded picture hash SEI"),
        ("temporal-layers","Temporal Layers","check", False,0,0,[],   "Enable temporal layer output"),
        ("vui-timing-info","VUI Timing",   "check",   True, 0,0,[],   "VUI timing info"),
        ("vui-hrd-info","VUI HRD",         "check",   True, 0,0,[],   "VUI HRD info"),
        ("pic-struct",  "Pic Struct",      "check",   False,0,0,[],   "Pic_struct in VUI timing SEI"),
        ("atc-sei",     "ATC SEI",         "islider",-1,  -1,200,[],  "SMPTE 91M ATC SEI (-1=off)"),
        ("csv",         "CSV Output",      "entry",   "",   0,0,[],   "Per-frame stats CSV path"),
        ("log-level",   "Log Level",       "combo",   "info",0,0,["none","error","warning","info","debug","full"],"Verbosity"),
        ("no-progress", "No Progress",     "check",   False,0,0,[],   "Suppress progress indicator"),
    ],
}

DEFAULT_PRESETS = [
    {"name":"Streaming",   "build":"3744","custom":"streaming",   "options":"--preset fast --tune zerolatency"},
    {"name":"Film Master", "build":"3744","custom":"film-master",  "options":"--preset slow --tune film"},
    {"name":"Anime",       "build":"3744","custom":"anime",        "options":"--preset medium --tune animation"},
    {"name":"Archive",     "build":"3744","custom":"archival",     "options":"--preset veryslow --tune grain"},
    {"name":"HDR10",       "build":"3744","custom":"hdr10-master", "options":"--preset slow --hdr10 --hdr10-opt"},
]

# ─────────────────────────────────────────────────────────────────────────────
#  SPLASH SCREEN
# ─────────────────────────────────────────────────────────────────────────────

class SplashScreen(tk.Toplevel):
    def __init__(self, parent, on_done):
        super().__init__(parent)
        self._parent = parent
        self._on_done = on_done
        self._img_tk = None

        self.overrideredirect(True)
        self.configure(bg="#0D0F14")
        W, H = 960, 620
        self.geometry(f"{W}x{H}+0+0")  # place first
        self.update_idletasks()
        self.withdraw()  # hide while calculating
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw // 2) - (W // 2)
        y = (sh // 2) - (H // 2)
        self.geometry(f"{W}x{H}+{x}+{y}")
        self.deiconify()  # show at correct position        
        self.lift()
        self.attributes("-topmost", True)

        # find splash images
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        folder = base / "splash_images"
        imgs = []
        if folder.exists():
            for ext in ("*.jpg","*.jpeg","*.png","*.webp"):
                imgs.extend(folder.glob(ext))

        # image panel
        self.img_lbl = tk.Label(self, bg="#0D0F14")
        self.img_lbl.place(x=0, y=0, width=W, height=H-90)

        if imgs:
            self._images = imgs
            self._show_random_image(W, H-90)
        else:
            tk.Label(self, text="⬡", font=("Consolas", 64),
                     bg="#0D0F14", fg="#00C9A7").place(relx=0.5, y=80, anchor="n")

        # bottom bar
        bar = tk.Frame(self, bg="#13161E", height=90)
        bar.place(x=0, y=H-90, width=W, height=90)

        tk.Label(bar, text=APP_NAME,
                 font=("Consolas", 26, "bold"),
                 bg="#13161E", fg="#00C9A7").place(x=20, y=6)
        tk.Label(bar, text=f"v{APP_VERSION}  ·  HEVC Metadata Patcher",
                 font=("Consolas", 11),
                 bg="#13161E", fg="#8891A8").place(x=22, y=44)
        tk.Label(bar, text=random.choice(TIPS),
                 font=("Consolas", 9),
                 bg="#13161E", fg="#454D64",
                 wraplength=700, justify="left").place(x=22, y=64)
        tk.Label(bar, text="© Images belong to their respective owners",
                 font=("Consolas", 8),
                 bg="#13161E", fg="#00C9A7").place(relx=1.0, rely=1.0,
                                                    x=-10, y=-8, anchor="se")

        # animated progress bar
        self._pb_canvas = tk.Canvas(self, bg="#0D0F14", highlightthickness=0)
        self._pb_canvas.place(x=0, y=H-93, width=W, height=3)
        self._pb_rect = self._pb_canvas.create_rectangle(
            0, 0, 0, 3, fill="#00C9A7", outline="")
        self._W = W
        self._start = time.time()
        self._duration = 5.0
        self._pb_after_id = None
        self._animate_pb()
        
    def _show_random_image(self, w, h):
        try:
            path = random.choice(self._images)
            img = Image.open(path).convert("RGBA")
            img.thumbnail((w, h), Image.LANCZOS)
            canvas = Image.new("RGBA", (w, h), (13, 15, 20, 255))
            ox = (w - img.width) // 2
            oy = (h - img.height) // 2
            canvas.paste(img, (ox, oy), img)
            self._img_tk = ImageTk.PhotoImage(canvas)
            self.img_lbl.configure(image=self._img_tk)
        except Exception:
            pass

    def _animate_pb(self):
        try:
            if not self.winfo_exists():
                return
            elapsed = time.time() - self._start
            frac = min(elapsed / self._duration, 1.0)
            self._pb_canvas.coords(self._pb_rect, 0, 0,
                                   int(self._W * frac), 3)
            if frac < 1.0:
                self._pb_after_id = self._parent.after(
                    30, self._animate_pb)
            else:
                try:
                    self._parent.after_cancel(self._pb_after_id)
                except Exception:
                    pass
                self._parent.quit()
        except Exception:
            pass
            
# ─────────────────────────────────────────────────────────────────────────────
#  MAIN APP
# ─────────────────────────────────────────────────────────────────────────────

class MetaPatchApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1260x900")
        self.minsize(1000,720)

        self.cfg = load_cfg()
        self._theme = self.cfg.get("theme","dark")
        self._apply_theme(self._theme)

        # state
        self.file_path   = None
        self.file_bytes  = None
        self.block_start = 0
        self.block_end   = 0
        self.block_bytes = None
        self.second_off  = -1
        self.hevc_vars   = {}
        self.batch_files = []
        self._tip_after  = None

        self._build_ui()
        self._restore_settings()
        self._rotate_tip()
        
    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self, name):
        self._theme = name
        palette = LIGHT if name == "light" else DARK
        C.clear(); C.update(palette)
        ctk.set_appearance_mode("light" if name == "light" else "dark")

    def _toggle_theme(self):
        new = "light" if self._theme == "dark" else "dark"
        self._apply_theme(new)
        self.cfg["theme"] = new
        save_cfg(self.cfg)
        self._theme_btn.configure(
            text="☾ Dark" if new == "light" else "☀ Light")
        self._show_styled_dialog(
            "Theme Updated",
            f"Switched to {new} mode.\nRestart MetaPatch for full effect.",
            icon="🎨"
        )
    
    def _show_styled_dialog(self, title, message, icon="ℹ"):
        dlg = ctk.CTkToplevel(self)
        dlg.title(title)
        dlg.geometry("400x180")
        dlg.resizable(False, False)
        dlg.configure(fg_color=C["BG_MID"])
        dlg.grab_set()
        dlg.lift()
        dlg.attributes("-topmost", True)

        # centre on parent
        self.update_idletasks()
        px = self.winfo_x() + self.winfo_width()  // 2
        py = self.winfo_y() + self.winfo_height() // 2
        dlg.geometry(f"400x180+{px-200}+{py-90}")

        ctk.CTkLabel(dlg, text=f"{icon}  {title}",
                     font=("Consolas", 14, "bold"),
                     text_color=C["ACCENT"]).pack(anchor="w", padx=20, pady=(18,4))

        ctk.CTkFrame(dlg, fg_color=C["TEXT_DIM"], height=1).pack(fill="x", padx=20)

        ctk.CTkLabel(dlg, text=message,
                     font=("Consolas", 11),
                     text_color=C["TEXT_SEC"],
                     justify="left", wraplength=360).pack(anchor="w", padx=20, pady=12)

        ctk.CTkButton(dlg, text="OK", width=80, height=30,
                      font=("Consolas", 12),
                      fg_color=C["ACCENT"], hover_color="#009F84",
                      text_color="black",
                      command=dlg.destroy).pack(anchor="e", padx=20, pady=(0,16))
    
    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.configure(fg_color=C["BG_DARK"])

        # Titlebar
        tb = ctk.CTkFrame(self, fg_color=C["BG_MID"], height=52, corner_radius=0)
        tb.pack(fill="x")
        tb.pack_propagate(False)

        ctk.CTkLabel(tb, text=f"⬡  {APP_NAME}",
                     font=("Consolas",17,"bold"),
                     text_color=C["ACCENT"]).pack(side="left", padx=18)
        self._tip_lbl = ctk.CTkLabel(tb, text="",
                                     font=("Consolas",10),
                                     text_color=C["TEXT_DIM"])
        self._tip_lbl.pack(side="left", padx=6)

        self._theme_btn = ctk.CTkButton(
            tb, text="☀ Light" if self._theme=="dark" else "☾ Dark",
            width=84, height=28, fg_color="transparent",
            border_width=1, border_color=C["TEXT_DIM"],
            text_color=C["TEXT_SEC"], font=("Consolas",11),
            command=self._toggle_theme)
        self._theme_btn.pack(side="right", padx=12)

        # Main split
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True)

        sb = ctk.CTkFrame(main, fg_color=C["BG_MID"], width=268, corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        self._build_sidebar(sb)
        self._build_tabs(right)

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self, p):
        self._slbl("FILE", p, 14)
        fc = self._card(p)
        ctk.CTkButton(fc, text="📂  Browse File", font=("Consolas",12),
                      fg_color=C["ACCENT2"], hover_color="#0060AA",
                      text_color="white", height=36,
                      command=self._browse_single).pack(fill="x", padx=8, pady=(8,4))
        self.file_lbl = ctk.CTkLabel(fc, text="no file selected",
                                     font=("Consolas",10),
                                     text_color=C["TEXT_DIM"],
                                     wraplength=220, justify="left")
        self.file_lbl.pack(anchor="w", padx=8, pady=(2,8))

        self._slbl("INFO", p)
        ic = self._card(p)
        self.info_lbls = {}
        for k, lbl in [("size","Size"),("offset","Offset"),
                       ("blksize","Block"),("second","2nd block")]:
            r = ctk.CTkFrame(ic, fg_color="transparent")
            r.pack(fill="x", padx=8, pady=2)
            ctk.CTkLabel(r, text=lbl+":", font=("Consolas",10),
                         text_color=C["TEXT_DIM"], width=72, anchor="w").pack(side="left")
            v = ctk.CTkLabel(r, text="—", font=("Consolas",10),
                             text_color=C["TEXT_SEC"])
            v.pack(side="left")
            self.info_lbls[k] = v
        ctk.CTkFrame(ic, fg_color="transparent", height=4).pack()

        self._slbl("OPTIONS", p)
        oc = self._card(p)
        self.backup_var       = ctk.BooleanVar(value=True)
        self.patch2_var       = ctk.BooleanVar(value=True)
        self.remux_var        = ctk.BooleanVar(value=False)
        self.include_preset_var = ctk.BooleanVar(value=False)
        for var, txt in [
            (self.backup_var,    "Auto-backup (.backup)"),
            (self.patch2_var,    "Patch 2nd identical block"),
            (self.remux_var,     "mkvmerge remux after patch"),
            (self.include_preset_var, "Include --preset in options"),
        ]:
            ctk.CTkCheckBox(oc, text=txt, variable=var,
                            font=("Consolas",11), text_color=C["TEXT_PRI"],
                            checkmark_color=C["ACCENT"], fg_color=C["ACCENT"]
                            ).pack(anchor="w", padx=8, pady=3)
        ctk.CTkFrame(oc, fg_color="transparent", height=4).pack()

        self._slbl("MKVMERGE", p)
        mc = self._card(p)
        self.mkvmerge_var = ctk.StringVar(value=self.cfg.get("mkvmerge","mkvmerge"))
        ctk.CTkEntry(mc, textvariable=self.mkvmerge_var,
                     font=("Consolas",10), fg_color=C["BG_CARD"],
                     border_color=C["TEXT_DIM"], text_color=C["TEXT_PRI"],
                     placeholder_text="mkvmerge or full path"
                     ).pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(mc, text="Browse mkvmerge.exe", font=("Consolas",10),
                      fg_color="transparent", border_width=1,
                      border_color=C["TEXT_DIM"], text_color=C["TEXT_SEC"],
                      hover_color=C["BG_CARD"], height=26,
                      command=self._browse_mkvmerge
                      ).pack(fill="x", padx=8, pady=(0,8))

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _build_tabs(self, p):
        self.tabs = ctk.CTkTabview(
            p, fg_color=C["BG_MID"],
            segmented_button_fg_color=C["BG_PANEL"],
            segmented_button_selected_color=C["ACCENT"],
            segmented_button_selected_hover_color=C["ACCENT"],
            segmented_button_unselected_color=C["BG_PANEL"],
            text_color=C["TEXT_PRI"],
            segmented_button_unselected_hover_color=C["BG_CARD"])
        self.tabs.pack(fill="both", expand=True, padx=8, pady=8)

        TABS = ["  Patch  ","  HEVC Options  ","  Batch  ",
                "  H264 Remover  ","  Presets  ",
                "  Raw Block  ","  History  ","  Credits  "]
        for t in TABS: self.tabs.add(t)

        self._build_patch_tab(self.tabs.tab("  Patch  "))
        self._build_hevc_tab(self.tabs.tab("  HEVC Options  "))
        self._build_batch_tab(self.tabs.tab("  Batch  "))
        self._build_h264_tab(self.tabs.tab("  H264 Remover  "))
        self._build_presets_tab(self.tabs.tab("  Presets  "))
        self._build_raw_tab(self.tabs.tab("  Raw Block  "))
        self._build_history_tab(self.tabs.tab("  History  "))
        self._build_credits_tab(self.tabs.tab("  Credits  "))

    # ── Patch Tab ─────────────────────────────────────────────────────────────

    def _build_patch_tab(self, p):
        p.configure(fg_color="transparent")
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)

        s1 = self._sect(sc, "ENCODER IDENTIFICATION")
        fields = [
            ("prefix_var",    "Prefix char",  "N",  80,  C["ACCENT"],   "Replaces the 'x' in 'x265' e.g. N → Nx265"),
            ("build_var",     "Build number", "",  140, C["ACCENT"],   "Numeric build e.g. 3744"),
            ("custom_var",    "Custom tag",   "",  360, C["TEXT_PRI"], "Optional studio / label tag"),
        ]
        for attr, lbl, default, w, col, ph in fields:
            r = ctk.CTkFrame(s1, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=lbl+":", font=("Consolas",12),
                         text_color=C["TEXT_SEC"], width=130, anchor="w").pack(side="left")
            var = ctk.StringVar(value=self.cfg.get(attr, default))
            var.trace("w", lambda *a: self._update_preview())
            setattr(self, attr, var)
            ctk.CTkEntry(r, textvariable=var, width=w, placeholder_text=ph,
                         font=("Consolas",13), fg_color=C["BG_CARD"],
                         border_color=C["TEXT_DIM"], text_color=col
                         ).pack(side="left")

        s2 = self._sect(sc, "COPYRIGHT & URL")
        for attr, lbl, default, w in [
            ("copyright_var","Copyright","Copyright 2013-2018 (c) Multicoreware, Inc",430),
            ("url_var",      "URL",      "http://x265.org", 300),
        ]:
            r = ctk.CTkFrame(s2, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=lbl+":", font=("Consolas",12),
                         text_color=C["TEXT_SEC"], width=130, anchor="w").pack(side="left")
            var = ctk.StringVar(value=self.cfg.get(attr, default))
            var.trace("w", lambda *a: self._update_preview())
            setattr(self, attr, var)
            ctk.CTkEntry(r, textvariable=var, width=w,
                         font=("Consolas",12), fg_color=C["BG_CARD"],
                         border_color=C["TEXT_DIM"], text_color=C["TEXT_PRI"]
                         ).pack(side="left")

        s3 = self._sect(sc, "OPTIONS STRING  ·  blank = auto-build from HEVC Options tab")
        self.options_var = ctk.StringVar()
        self.options_var.trace("w", lambda *a: self._update_preview())
        ctk.CTkEntry(s3, textvariable=self.options_var,
                     font=("Consolas",11), fg_color=C["BG_CARD"],
                     border_color=C["TEXT_DIM"], text_color=C["TEXT_PRI"],
                     placeholder_text="manual override — leave blank to auto-generate"
                     ).pack(fill="x", pady=4)
        ctk.CTkButton(s3, text="→  Generate from HEVC Options",
                      font=("Consolas",11), fg_color=C["ACCENT3"],
                      hover_color="#9040EE", text_color="white", height=30,
                      command=self._push_hevc_options).pack(anchor="w", pady=(0,4))

        s4 = self._sect(sc, "LIVE PREVIEW")
        self.preview_box = ctk.CTkTextbox(s4, height=72, font=("Consolas",11),
                                          fg_color=C["BG_CARD"], text_color=C["ACCENT"],
                                          border_color=C["TEXT_DIM"], border_width=1,
                                          wrap="word")
        self.preview_box.pack(fill="x", pady=4)
        self.preview_box.configure(state="disabled")
        self.size_lbl = ctk.CTkLabel(s4, text="", font=("Consolas",11),
                                     text_color=C["TEXT_SEC"])
        self.size_lbl.pack(anchor="w")

        br = ctk.CTkFrame(sc, fg_color="transparent")
        br.pack(fill="x", pady=10, padx=4)
        self.apply_btn = ctk.CTkButton(
            br, text="⚡  Apply (in-place)", font=("Consolas",13,"bold"),
            fg_color=C["ACCENT"], hover_color="#009F84", text_color="black",
            height=40, width=200, command=self._apply_patch, state="disabled")
        self.apply_btn.pack(side="left", padx=(0,8))
        self.saveas_btn = ctk.CTkButton(
            br, text="💾  Save As", font=("Consolas",13),
            fg_color=C["ACCENT2"], hover_color="#0060AA", text_color="white",
            height=40, width=130, command=self._save_as, state="disabled")
        self.saveas_btn.pack(side="left", padx=(0,8))
        ctk.CTkButton(br, text="🔄  Restore Backup", font=("Consolas",12),
                      fg_color="transparent", border_width=1,
                      border_color=C["WARN"], text_color=C["WARN"],
                      hover_color=C["BG_CARD"], height=40,
                      command=self._restore_backup).pack(side="left", padx=(0,8))
        ctk.CTkButton(br, text="✕  Clear", font=("Consolas",12),
                      fg_color="transparent", border_width=1,
                      border_color=C["TEXT_DIM"], text_color=C["TEXT_SEC"],
                      hover_color=C["BG_CARD"], height=40,
                      command=self._clear_patch).pack(side="right")

        self.remux_status_lbl = ctk.CTkLabel(sc, text="", font=("Consolas",11),
                                              text_color=C["TEXT_DIM"])
        self.remux_status_lbl.pack(anchor="w", padx=4, pady=2)

        ls = self._sect(sc, "LOG")
        self.log_box = ctk.CTkTextbox(ls, height=170, font=("Consolas",11),
                                      fg_color=C["BG_CARD"], text_color=C["TEXT_SEC"],
                                      border_color=C["TEXT_DIM"], border_width=1)
        self.log_box.pack(fill="x", pady=4)
        self.log_box.configure(state="disabled")

    # ── HEVC Options Tab (sub-tabs per category) ──────────────────────────────

    def _build_hevc_tab(self, p):
        p.configure(fg_color="transparent")

        inner_tabs = ctk.CTkTabview(
            p, fg_color=C["BG_PANEL"],
            segmented_button_fg_color=C["BG_CARD"],
            segmented_button_selected_color=C["ACCENT2"],
            segmented_button_selected_hover_color=C["ACCENT2"],
            segmented_button_unselected_color=C["BG_CARD"],
            text_color=C["TEXT_PRI"],
            segmented_button_unselected_hover_color=C["BG_MID"])
        inner_tabs.pack(fill="both", expand=True, padx=4, pady=4)

        for section_name, opts in HEVC_SECTIONS.items():
            inner_tabs.add(f" {section_name} ")
            tab = inner_tabs.tab(f" {section_name} ")
            tab.configure(fg_color="transparent")
            self._populate_hevc_section(tab, opts)

        # bottom bar
        bot = ctk.CTkFrame(p, fg_color="transparent")
        bot.pack(fill="x", padx=4, pady=(0,4))
        ctk.CTkButton(bot, text="→  Push to Options String",
                      font=("Consolas",12), fg_color=C["ACCENT"],
                      hover_color="#009F84", text_color="black", height=34,
                      command=self._push_hevc_options).pack(side="left", padx=(0,8))
        ctk.CTkButton(bot, text="Reset all to defaults",
                      font=("Consolas",11), fg_color="transparent",
                      border_width=1, border_color=C["TEXT_DIM"],
                      text_color=C["TEXT_SEC"], hover_color=C["BG_CARD"], height=34,
                      command=self._reset_hevc).pack(side="left")
        self.hevc_preview_lbl = ctk.CTkLabel(bot, text="",
                                              font=("Consolas",10),
                                              text_color=C["TEXT_DIM"],
                                              wraplength=600, justify="left")
        self.hevc_preview_lbl.pack(side="left", padx=12)

    def _populate_hevc_section(self, parent, opts):
        sc = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        sc.pack(fill="both", expand=True)

        # two-column grid
        sc.columnconfigure(0, weight=1)
        sc.columnconfigure(1, weight=1)

        for idx, (key, label, wtype, default, mn, mx, choices, tip) in enumerate(opts):
            uid = f"hevc_{section_uid(key)}"
            if uid in self.hevc_vars:
                uid = f"hevc_{section_uid(key)}_{idx}"

            col = idx % 2
            row = idx // 2

            cell = ctk.CTkFrame(sc, fg_color=C["BG_PANEL"], corner_radius=8)
            cell.grid(row=row, column=col, padx=5, pady=4, sticky="ew")

            lbl_w = ctk.CTkLabel(cell, text=label,
                                  font=("Consolas",11,"bold"),
                                  text_color=C["TEXT_SEC"],
                                  anchor="w")
            lbl_w.pack(anchor="w", padx=10, pady=(8,2))
            if tip:
                tip_lbl = ctk.CTkLabel(cell, text=tip,
                                       font=("Consolas",9),
                                       text_color=C["TEXT_DIM"],
                                       wraplength=260, justify="left")
                tip_lbl.pack(anchor="w", padx=10, pady=(0,4))

            var = self._make_hevc_widget(cell, uid, wtype, default, mn, mx, choices)
            self.hevc_vars[uid] = var

    def _make_hevc_widget(self, parent, uid, wtype, default, mn, mx, choices):
        if wtype == "combo":
            var = ctk.StringVar(value=str(default))
            ctk.CTkOptionMenu(parent, variable=var, values=choices,
                              fg_color=C["BG_CARD"], button_color=C["BG_CARD"],
                              button_hover_color=C["ACCENT2"],
                              dropdown_fg_color=C["BG_PANEL"],
                              text_color=C["TEXT_PRI"], font=("Consolas",11),
                              width=200,
                              command=lambda *a: self._update_hevc_preview()
                              ).pack(padx=10, pady=(0,10), anchor="w")

        elif wtype == "check":
            var = ctk.BooleanVar(value=default)
            ctk.CTkCheckBox(parent, text="Enable", variable=var,
                            font=("Consolas",11), text_color=C["TEXT_PRI"],
                            checkmark_color=C["ACCENT"], fg_color=C["ACCENT"],
                            command=self._update_hevc_preview
                            ).pack(padx=10, pady=(0,10), anchor="w")

        elif wtype == "islider":
            var = ctk.IntVar(value=int(default))
            val_lbl = ctk.CTkLabel(parent, text=str(int(default)),
                                   font=("Consolas",11,"bold"),
                                   text_color=C["ACCENT"])
            val_lbl.pack(anchor="e", padx=10)
            def _sl(v, vl=val_lbl, va=var):
                vl.configure(text=str(int(float(v))))
                self._update_hevc_preview()
            ctk.CTkSlider(parent, from_=mn, to=mx, variable=var,
                          button_color=C["ACCENT"], button_hover_color="#009F84",
                          progress_color=C["ACCENT"], fg_color=C["BG_CARD"],
                          command=_sl).pack(fill="x", padx=10, pady=(0,10))

        elif wtype in ("fslider","slider"):
            var = ctk.DoubleVar(value=float(default))
            val_lbl = ctk.CTkLabel(parent, text=f"{float(default):.2f}",
                                   font=("Consolas",11,"bold"),
                                   text_color=C["ACCENT"])
            val_lbl.pack(anchor="e", padx=10)
            def _sl(v, vl=val_lbl):
                vl.configure(text=f"{float(v):.2f}")
                self._update_hevc_preview()
            ctk.CTkSlider(parent, from_=mn, to=mx, variable=var,
                          button_color=C["ACCENT"], button_hover_color="#009F84",
                          progress_color=C["ACCENT"], fg_color=C["BG_CARD"],
                          command=_sl).pack(fill="x", padx=10, pady=(0,10))

        elif wtype == "entry":
            var = ctk.StringVar(value=str(default))
            var.trace("w", lambda *a: self._update_hevc_preview())
            ctk.CTkEntry(parent, textvariable=var,
                         font=("Consolas",11), fg_color=C["BG_CARD"],
                         border_color=C["TEXT_DIM"], text_color=C["TEXT_PRI"],
                         placeholder_text="leave blank = omit"
                         ).pack(fill="x", padx=10, pady=(0,10))
        else:
            var = ctk.StringVar(value=str(default))

        return var

    def _update_hevc_preview(self):
        opts = self._build_hevc_opts_str()
        short = opts[:120]+"…" if len(opts)>120 else opts
        self.hevc_preview_lbl.configure(text=short or "(defaults — nothing will be appended)")

    # ── Batch Tab ─────────────────────────────────────────────────────────────

    def _build_batch_tab(self, p):
        p.configure(fg_color="transparent")

        top = ctk.CTkFrame(p, fg_color="transparent")
        top.pack(fill="x", pady=6, padx=4)
        ctk.CTkButton(top, text="➕  Add Files", font=("Consolas",12),
                      fg_color=C["ACCENT2"], hover_color="#0060AA",
                      text_color="white", height=34,
                      command=self._batch_add_files).pack(side="left", padx=(0,6))
        ctk.CTkButton(top, text="📁  Add Folder", font=("Consolas",12),
                      fg_color=C["ACCENT2"], hover_color="#0060AA",
                      text_color="white", height=34,
                      command=self._batch_add_folder).pack(side="left", padx=(0,6))
        ctk.CTkButton(top, text="✕  Clear", font=("Consolas",12),
                      fg_color="transparent", border_width=1,
                      border_color=C["ERR"], text_color=C["ERR"],
                      hover_color=C["BG_CARD"], height=34,
                      command=self._batch_clear).pack(side="left", padx=(0,6))
        self.batch_count_lbl = ctk.CTkLabel(top, text="0 files",
                                            font=("Consolas",12),
                                            text_color=C["TEXT_SEC"])
        self.batch_count_lbl.pack(side="left", padx=10)

        # output mode
        om = ctk.CTkFrame(p, fg_color=C["BG_PANEL"], corner_radius=8)
        om.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(om, text="Output mode:", font=("Consolas",12),
                     text_color=C["TEXT_SEC"]).pack(side="left", padx=10, pady=8)
        self.batch_mode_var = ctk.StringVar(value="inplace")
        for val, txt in [("inplace","In-place"),("suffix","Add suffix"),("folder","Output folder")]:
            ctk.CTkRadioButton(om, text=txt, variable=self.batch_mode_var, value=val,
                               font=("Consolas",11), text_color=C["TEXT_PRI"],
                               fg_color=C["ACCENT"], hover_color="#009F84"
                               ).pack(side="left", padx=8, pady=8)
        self.batch_suffix_var = ctk.StringVar(value="_patched")
        ctk.CTkEntry(om, textvariable=self.batch_suffix_var, width=100,
                     font=("Consolas",11), fg_color=C["BG_CARD"],
                     border_color=C["TEXT_DIM"], text_color=C["TEXT_PRI"],
                     placeholder_text="suffix").pack(side="left", padx=4)
        self.batch_outdir_var = ctk.StringVar()
        ctk.CTkEntry(om, textvariable=self.batch_outdir_var, width=180,
                     font=("Consolas",11), fg_color=C["BG_CARD"],
                     border_color=C["TEXT_DIM"], text_color=C["TEXT_PRI"],
                     placeholder_text="output folder").pack(side="left", padx=4)
        ctk.CTkButton(om, text="📁", width=30, font=("Consolas",12),
                      fg_color="transparent", border_width=1,
                      border_color=C["TEXT_DIM"], text_color=C["TEXT_SEC"],
                      hover_color=C["BG_CARD"],
                      command=lambda: self.batch_outdir_var.set(
                          filedialog.askdirectory() or self.batch_outdir_var.get())
                      ).pack(side="left", padx=(0,10), pady=8)

        # file list
        self.batch_list_box = ctk.CTkTextbox(p, font=("Consolas",11),
                                             fg_color=C["BG_CARD"],
                                             text_color=C["TEXT_SEC"],
                                             border_color=C["TEXT_DIM"],
                                             border_width=1)
        self.batch_list_box.pack(fill="both", expand=True, padx=4, pady=4)
        self.batch_list_box.configure(state="disabled")

        # log
        ctk.CTkLabel(p, text="Batch log:", font=("Consolas",11,"bold"),
                     text_color=C["TEXT_DIM"]).pack(anchor="w", padx=6)
        self.batch_log_box = ctk.CTkTextbox(p, height=140, font=("Consolas",10),
                                            fg_color=C["BG_CARD"],
                                            text_color=C["TEXT_SEC"],
                                            border_color=C["TEXT_DIM"],
                                            border_width=1)
        self.batch_log_box.pack(fill="x", padx=4, pady=(0,4))
        self.batch_log_box.configure(state="disabled")

        # progress + buttons
        pr = ctk.CTkFrame(p, fg_color="transparent")
        pr.pack(fill="x", padx=4, pady=4)
        self.batch_pb = ctk.CTkProgressBar(pr, height=14,
                                           fg_color=C["BG_CARD"],
                                           progress_color=C["ACCENT"])
        self.batch_pb.pack(fill="x", side="left", expand=True, padx=(0,10))
        self.batch_pb.set(0)
        self.batch_stat_lbl = ctk.CTkLabel(pr, text="",
                                           font=("Consolas",11),
                                           text_color=C["TEXT_SEC"], width=180)
        self.batch_stat_lbl.pack(side="left")

        br = ctk.CTkFrame(p, fg_color="transparent")
        br.pack(fill="x", padx=4, pady=(0,6))
        self.batch_run_btn = ctk.CTkButton(
            br, text="⚡  Run Batch", font=("Consolas",13,"bold"),
            fg_color=C["ACCENT"], hover_color="#009F84", text_color="black",
            height=40, command=self._run_batch)
        self.batch_run_btn.pack(side="left", padx=(0,8))
        self.batch_stop_var = ctk.BooleanVar(value=False)
        ctk.CTkButton(br, text="■  Stop", font=("Consolas",12),
                      fg_color="transparent", border_width=1,
                      border_color=C["ERR"], text_color=C["ERR"],
                      hover_color=C["BG_CARD"], height=40,
                      command=lambda: self.batch_stop_var.set(True)
                      ).pack(side="left")

    # ── H264 Remover Tab ──────────────────────────────────────────────────────

    def _build_h264_tab(self, p):
        p.configure(fg_color="transparent")
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)

        info = self._sect(sc, "H.264 TRACK REMOVER")
        ctk.CTkLabel(info,
            text=("Remove H.264 video tracks from MKV files that contain both H.264 and\n"
                  "HEVC (H.265) tracks — keeping only the HEVC track plus all audio/subs.\n"
                  "Uses mkvmerge. Set the path in the sidebar."),
            font=("Consolas",11), text_color=C["TEXT_SEC"],
            justify="left").pack(anchor="w", pady=4)

        s2 = self._sect(sc, "SINGLE FILE")
        r1 = ctk.CTkFrame(s2, fg_color="transparent")
        r1.pack(fill="x", pady=4)
        self.h264_file_var = ctk.StringVar()
        ctk.CTkEntry(r1, textvariable=self.h264_file_var, width=480,
                     font=("Consolas",11), fg_color=C["BG_CARD"],
                     border_color=C["TEXT_DIM"], text_color=C["TEXT_PRI"],
                     placeholder_text="path to .mkv file"
                     ).pack(side="left", padx=(0,8))
        ctk.CTkButton(r1, text="Browse", font=("Consolas",11),
                      fg_color=C["ACCENT2"], hover_color="#0060AA",
                      text_color="white", height=32,
                      command=self._h264_browse).pack(side="left")

        self.h264_mode_var = ctk.StringVar(value="saveas")
        r2 = ctk.CTkFrame(s2, fg_color="transparent")
        r2.pack(fill="x", pady=4)
        for val, txt in [("inplace","Overwrite original"),("saveas","Save as new file")]:
            ctk.CTkRadioButton(r2, text=txt, variable=self.h264_mode_var, value=val,
                               font=("Consolas",11), text_color=C["TEXT_PRI"],
                               fg_color=C["ACCENT"], hover_color="#009F84"
                               ).pack(side="left", padx=(0,16))

        ctk.CTkButton(s2, text="⚡  Remove H.264 Track", font=("Consolas",13,"bold"),
                      fg_color=C["ERR"], hover_color="#AA2222",
                      text_color="white", height=38,
                      command=self._h264_remove_single).pack(anchor="w", pady=8)

        s3 = self._sect(sc, "BATCH H.264 REMOVAL")
        r3 = ctk.CTkFrame(s3, fg_color="transparent")
        r3.pack(fill="x", pady=4)
        self.h264_batch_dir_var = ctk.StringVar()
        ctk.CTkEntry(r3, textvariable=self.h264_batch_dir_var, width=400,
                     font=("Consolas",11), fg_color=C["BG_CARD"],
                     border_color=C["TEXT_DIM"], text_color=C["TEXT_PRI"],
                     placeholder_text="folder with MKV files"
                     ).pack(side="left", padx=(0,8))
        ctk.CTkButton(r3, text="Browse Folder", font=("Consolas",11),
                      fg_color=C["ACCENT2"], hover_color="#0060AA",
                      text_color="white", height=32,
                      command=lambda: self.h264_batch_dir_var.set(
                          filedialog.askdirectory() or self.h264_batch_dir_var.get())
                      ).pack(side="left")

        self.h264_recursive_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(s3, text="Recursive (include subfolders)",
                        variable=self.h264_recursive_var,
                        font=("Consolas",11), text_color=C["TEXT_PRI"],
                        checkmark_color=C["ACCENT"], fg_color=C["ACCENT"]
                        ).pack(anchor="w", pady=4)

        ctk.CTkButton(s3, text="⚡  Run Batch H.264 Removal",
                      font=("Consolas",13,"bold"),
                      fg_color=C["ERR"], hover_color="#AA2222",
                      text_color="white", height=38,
                      command=self._h264_batch).pack(anchor="w", pady=8)

        s4 = self._sect(sc, "LOG")
        self.h264_log = ctk.CTkTextbox(s4, height=200, font=("Consolas",11),
                                       fg_color=C["BG_CARD"], text_color=C["TEXT_SEC"],
                                       border_color=C["TEXT_DIM"], border_width=1)
        self.h264_log.pack(fill="x", pady=4)
        self.h264_log.configure(state="disabled")

    # ── Presets Tab ───────────────────────────────────────────────────────────

    def _build_presets_tab(self, p):
        p.configure(fg_color="transparent")
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)

        self._preset_frames = []
        self._presets_container = sc

        ctk.CTkLabel(sc, text="SAVED PRESETS",
                     font=("Consolas",11,"bold"), text_color=C["ACCENT"]
                     ).pack(anchor="w", padx=4, pady=(8,4))

        self._presets_list_frame = ctk.CTkFrame(sc, fg_color="transparent")
        self._presets_list_frame.pack(fill="x", padx=4)

        self._refresh_presets_ui()

        # Creator
        creator = self._sect(sc, "CREATE / EDIT PRESET")

        cr_fields = [
            ("preset_name_var",    "Name",       "My Preset",  280, C["TEXT_PRI"]),
            ("preset_build_var",   "Build",      "3744",       120, C["ACCENT"]),
            ("preset_custom_var",  "Custom tag", "",           280, C["TEXT_PRI"]),
            ("preset_options_var", "Options",    "",           500, C["TEXT_PRI"]),
        ]
        for attr, lbl, default, w, col in cr_fields:
            r = ctk.CTkFrame(creator, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=lbl+":", font=("Consolas",12),
                         text_color=C["TEXT_SEC"], width=110, anchor="w").pack(side="left")
            var = ctk.StringVar(value=default)
            setattr(self, attr, var)
            ctk.CTkEntry(r, textvariable=var, width=w,
                         font=("Consolas",12), fg_color=C["BG_CARD"],
                         border_color=C["TEXT_DIM"], text_color=col
                         ).pack(side="left")

        # auto-adjust by duration hint
        hint_row = ctk.CTkFrame(creator, fg_color="transparent")
        hint_row.pack(fill="x", pady=4)
        ctk.CTkLabel(hint_row, text="Auto-adjust for duration:",
                     font=("Consolas",12), text_color=C["TEXT_SEC"]
                     ).pack(side="left", padx=(0,8))
        self.preset_duration_var = ctk.StringVar(value="any")
        for val, txt in [("any","Any"),("short","< 20 min"),
                         ("medium","20–60 min"),("long","> 60 min")]:
            ctk.CTkRadioButton(hint_row, text=txt,
                               variable=self.preset_duration_var, value=val,
                               font=("Consolas",11), text_color=C["TEXT_PRI"],
                               fg_color=C["ACCENT3"], hover_color="#9040EE"
                               ).pack(side="left", padx=6)

        ctk.CTkLabel(creator,
            text=("Duration hint adjusts CRF: short → CRF-2 (higher quality),\n"
                  "long → CRF+2 (smaller size). Applied when preset is loaded."),
            font=("Consolas",10), text_color=C["TEXT_DIM"], justify="left"
            ).pack(anchor="w", pady=(0,6))

        btn_row = ctk.CTkFrame(creator, fg_color="transparent")
        btn_row.pack(fill="x", pady=4)
        ctk.CTkButton(btn_row, text="💾  Save Preset", font=("Consolas",12),
                      fg_color=C["ACCENT"], hover_color="#009F84",
                      text_color="black", height=34,
                      command=self._save_preset).pack(side="left", padx=(0,8))
        ctk.CTkButton(btn_row, text="→  Load from current Patch settings",
                      font=("Consolas",11), fg_color="transparent",
                      border_width=1, border_color=C["TEXT_DIM"],
                      text_color=C["TEXT_SEC"], hover_color=C["BG_CARD"], height=34,
                      command=self._load_into_creator).pack(side="left")

    def _refresh_presets_ui(self):
        for w in self._presets_list_frame.winfo_children():
            w.destroy()
        presets = self.cfg.get("presets", DEFAULT_PRESETS)
        if not presets:
            ctk.CTkLabel(self._presets_list_frame, text="No saved presets.",
                         font=("Consolas",11), text_color=C["TEXT_DIM"]
                         ).pack(anchor="w", pady=4)
            return
        for i, pr in enumerate(presets):
            card = ctk.CTkFrame(self._presets_list_frame,
                                fg_color=C["BG_PANEL"], corner_radius=8)
            card.pack(fill="x", pady=4)
            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True, padx=10, pady=8)
            ctk.CTkLabel(left, text=pr.get("name","Preset"),
                         font=("Consolas",13,"bold"),
                         text_color=C["ACCENT"]).pack(anchor="w")
            ctk.CTkLabel(left,
                text=f"build={pr.get('build','')}  tag={pr.get('custom','')}",
                font=("Consolas",10), text_color=C["TEXT_SEC"]).pack(anchor="w")
            opts_short = pr.get("options","")[:80]
            ctk.CTkLabel(left, text=opts_short or "(no options)",
                         font=("Consolas",10), text_color=C["TEXT_DIM"]
                         ).pack(anchor="w")
            dur = pr.get("duration","any")
            if dur != "any":
                ctk.CTkLabel(left, text=f"duration hint: {dur}",
                             font=("Consolas",9), text_color=C["ACCENT3"]
                             ).pack(anchor="w")
            right = ctk.CTkFrame(card, fg_color="transparent")
            right.pack(side="right", padx=10, pady=8)
            ctk.CTkButton(right, text="Apply", font=("Consolas",11),
                          fg_color=C["ACCENT"], hover_color="#009F84",
                          text_color="black", height=28, width=70,
                          command=lambda pr=pr: self._apply_preset(pr)
                          ).pack(pady=2)
            ctk.CTkButton(right, text="Delete", font=("Consolas",11),
                          fg_color="transparent", border_width=1,
                          border_color=C["ERR"], text_color=C["ERR"],
                          hover_color=C["BG_CARD"], height=28, width=70,
                          command=lambda i=i: self._delete_preset(i)
                          ).pack(pady=2)

    # ── Raw Block Tab ─────────────────────────────────────────────────────────

    def _build_raw_tab(self, p):
        p.configure(fg_color="transparent")
        ctk.CTkLabel(p, text="ASCII content of original x265 block",
                     font=("Consolas",11,"bold"),
                     text_color=C["TEXT_DIM"]).pack(anchor="w", padx=4, pady=(8,4))
        self.raw_box = ctk.CTkTextbox(p, font=("Consolas",11),
                                      fg_color=C["BG_CARD"],
                                      text_color=C["TEXT_SEC"],
                                      border_color=C["TEXT_DIM"], border_width=1)
        self.raw_box.pack(fill="both", expand=True, padx=4, pady=(0,4))
        self.raw_box.configure(state="disabled")

        ctk.CTkLabel(p, text="Hex dump — first 512 bytes",
                     font=("Consolas",11,"bold"),
                     text_color=C["TEXT_DIM"]).pack(anchor="w", padx=4, pady=(4,4))
        self.hex_box = ctk.CTkTextbox(p, height=190, font=("Consolas",10),
                                      fg_color=C["BG_CARD"],
                                      text_color="#5DCAA5",
                                      border_color=C["TEXT_DIM"], border_width=1)
        self.hex_box.pack(fill="x", padx=4, pady=(0,8))
        self.hex_box.configure(state="disabled")

    # ── History Tab ───────────────────────────────────────────────────────────

    def _build_history_tab(self, p):
        p.configure(fg_color="transparent")
        top = ctk.CTkFrame(p, fg_color="transparent")
        top.pack(fill="x", pady=4)
        ctk.CTkLabel(top, text="Patch history",
                     font=("Consolas",12), text_color=C["TEXT_SEC"]
                     ).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Clear", font=("Consolas",11),
                      fg_color="transparent", border_width=1,
                      border_color=C["ERR"], text_color=C["ERR"],
                      hover_color=C["BG_CARD"], height=28,
                      command=self._clear_history).pack(side="right", padx=4)
        self.hist_box = ctk.CTkTextbox(p, font=("Consolas",11),
                                       fg_color=C["BG_CARD"],
                                       text_color=C["TEXT_SEC"],
                                       border_color=C["TEXT_DIM"], border_width=1)
        self.hist_box.pack(fill="both", expand=True, padx=4, pady=4)
        self.hist_box.configure(state="disabled")
        self._refresh_history()

    # ── Credits Tab ───────────────────────────────────────────────────────────

    def _build_credits_tab(self, p):
        p.configure(fg_color="transparent")
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)

        ctk.CTkLabel(sc, text=APP_NAME,
                     font=("Consolas",32,"bold"),
                     text_color=C["ACCENT"]).pack(pady=(24,4))
        ctk.CTkLabel(sc, text=f"Version {APP_VERSION}",
                     font=("Consolas",14), text_color=C["TEXT_SEC"]).pack()
        ctk.CTkLabel(sc, text="HEVC / x265 Metadata Patcher · mkvmerge Remuxer · Batch Processor",
                     font=("Consolas",11), text_color=C["TEXT_DIM"]).pack(pady=(0,24))

        sections = [
            ("TOOLS USED", [
                ("x265",        "https://x265.org",          "HEVC encoder & metadata format"),
                ("mkvmerge",    "https://mkvtoolnix.download","MKV container remuxing"),
                ("CustomTkinter","https://github.com/TomSchimansky/CustomTkinter","Modern Tkinter UI framework"),
                ("Pillow",      "https://python-pillow.org",  "Image processing for splash screen"),
                ("PyInstaller", "https://pyinstaller.org",    "EXE packaging"),
            ]),
            ("DISCLAIMER", [
                ("Usage",       "", "This tool modifies binary metadata strings in video files."),
                ("Backup",      "", "Always keep backups of original files before patching."),
                ("Liability",   "", "The authors are not responsible for any data loss or file corruption."),
                ("Legal",       "", "Only use on files you own or have rights to modify."),
                ("x265 marks",  "", "x265, HEVC, H.265 are trademarks of their respective owners."),
            ]),
            ("CREDITS & SPLASH IMAGES", [
                ("Splash images", "", "Add your own images to the splash_images/ folder."),
                ("Art credit",    "", "Image credits belong to their respective artists/studios."),
                ("Author",        "", f"Built with ❤ by {APP_AUTHOR}"),
            ]),
        ]

        for sec_title, items in sections:
            s = self._sect(sc, sec_title)
            for name, url, desc in items:
                r = ctk.CTkFrame(s, fg_color=C["BG_CARD"], corner_radius=6)
                r.pack(fill="x", pady=3)
                ctk.CTkLabel(r, text=name, font=("Consolas",12,"bold"),
                             text_color=C["ACCENT2"], width=160, anchor="w"
                             ).pack(side="left", padx=10, pady=8)
                ctk.CTkLabel(r, text=desc, font=("Consolas",11),
                             text_color=C["TEXT_SEC"]).pack(side="left", padx=4)
                if url:
                    ctk.CTkLabel(r, text=url, font=("Consolas",10),
                                 text_color=C["TEXT_DIM"]).pack(side="right", padx=10)

        ctk.CTkLabel(sc,
            text=f"© {datetime.now().year} {APP_AUTHOR}  ·  MIT License  ·  {APP_NAME} {APP_VERSION}",
            font=("Consolas",10), text_color=C["TEXT_DIM"]).pack(pady=20)

    # ── Helper widgets ────────────────────────────────────────────────────────

    def _sect(self, parent, title):
        outer = ctk.CTkFrame(parent, fg_color=C["BG_PANEL"], corner_radius=10)
        outer.pack(fill="x", padx=4, pady=5)
        ctk.CTkLabel(outer, text=title, font=("Consolas",10,"bold"),
                     text_color=C["ACCENT"]).pack(anchor="w", padx=12, pady=(8,2))
        inner = ctk.CTkFrame(outer, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=(0,10))
        return inner

    def _card(self, parent):
        f = ctk.CTkFrame(parent, fg_color=C["BG_PANEL"], corner_radius=8)
        f.pack(fill="x", padx=12, pady=4)
        return f

    def _slbl(self, text, parent, top=8):
        ctk.CTkLabel(parent, text=text, font=("Consolas",10,"bold"),
                     text_color=C["TEXT_DIM"]).pack(anchor="w", padx=16, pady=(top,2))

    def _set_tb(self, box, text):
        box.configure(state="normal")
        box.delete("1.0","end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    def _log(self, msg, level="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        sym = {"ok":"✓","err":"✗","info":"·"}.get(level,"·")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}] {sym} {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _blog(self, msg, level="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        sym = {"ok":"✓","err":"✗","info":"·"}.get(level,"·")
        self.batch_log_box.configure(state="normal")
        self.batch_log_box.insert("end", f"[{ts}] {sym} {msg}\n")
        self.batch_log_box.see("end")
        self.batch_log_box.configure(state="disabled")

    def _hlog(self, msg, level="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        sym = {"ok":"✓","err":"✗","info":"·"}.get(level,"·")
        self.h264_log.configure(state="normal")
        self.h264_log.insert("end", f"[{ts}] {sym} {msg}\n")
        self.h264_log.see("end")
        self.h264_log.configure(state="disabled")

    def _rotate_tip(self):
        self._tip_lbl.configure(text=random.choice(TIPS))
        self._tip_after = self.after(12000, self._rotate_tip)

    # ── File scanning ─────────────────────────────────────────────────────────

    def _browse_single(self):
        path = filedialog.askopenfilename(
            title="Select video file",
            filetypes=[("Video files","*.mkv *.mp4 *.hevc *.265 *.h265 *.ts *.m2ts"),
                       ("All files","*.*")])
        if path:
            self.file_path = Path(path)
            self.file_lbl.configure(text=self.file_path.name, text_color=C["ACCENT"])
            threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        try:
            path = self.file_path
            fsize = path.stat().st_size
            with open(path,"rb") as f:
                buf = f.read(SCAN_SIZE)
            found = find_x265_block(buf)
            if not found:
                self.after(0,lambda: self._log("No x265 block in first 8MB","err"))
                return
            s, e, blk = found
            self.block_start = s
            self.block_end   = e
            self.block_bytes = blk

            with open(path,"rb") as f:
                full = f.read()
            self.file_bytes = full
            found2 = find_x265_block(bytearray(full), e)
            self.second_off = found2[0] if found2 and found2[2]==blk else -1

            bt = blk.decode("ascii","replace")
            words = len(bt.split())

            def upd():
                self.info_lbls["size"].configure(text=f"{fsize/1024/1024:.2f} MB")
                self.info_lbls["offset"].configure(text=f"0x{s:X}")
                self.info_lbls["blksize"].configure(text=f"{e-s} B")
                self.info_lbls["second"].configure(
                    text=f"0x{self.second_off:X}" if self.second_off!=-1 else "—",
                    text_color=C["OK"] if self.second_off!=-1 else C["TEXT_DIM"])

                self._set_tb(self.raw_box, bt)
                chunk=blk[:512]
                lines=[]
                for i in range(0,len(chunk),16):
                    row=chunk[i:i+16]
                    hp=" ".join(f"{b:02X}" for b in row).ljust(48)
                    ap="".join(chr(b) if 32<=b<=126 else "." for b in row)
                    lines.append(f"{i:04X}  {hp}  {ap}")
                self._set_tb(self.hex_box, "\n".join(lines))

                m=re.search(r"x265 \(build (\d+)\)", bt)
                if m and not self.build_var.get():
                    self.build_var.set(m.group(1))

                self.apply_btn.configure(state="normal")
                self.saveas_btn.configure(state="normal")
                self._log(f"Block  offset=0x{s:X}  size={e-s}B  words={words}","ok")
                if self.second_off!=-1:
                    self._log(f"2nd block at 0x{self.second_off:X}","ok")
                self._update_preview()
            self.after(0, upd)
        except Exception as ex:
            self.after(0,lambda: self._log(f"Scan error: {ex}","err"))

    # ── HEVC options string builder ────────────────────────────────────────────

    def _build_hevc_opts_str(self):
        # defaults lookup
        defs = {}
        for sect_opts in HEVC_SECTIONS.values():
            for idx,(key,label,wtype,default,mn,mx,choices,tip) in enumerate(sect_opts):
                uid = f"hevc_{section_uid(key)}"
                if uid not in defs:
                    defs[uid] = (default, wtype, key)
                else:
                    defs[f"hevc_{section_uid(key)}_{idx}"] = (default, wtype, key)

        parts = []
        include_preset = self.include_preset_var.get()

        for uid, var in self.hevc_vars.items():
            info = defs.get(uid)
            if not info: continue
            default, wtype, key = info
            if key == "preset" and not include_preset:
                continue
            v = var.get()
            if wtype == "check":
                if v: parts.append(f"--{key}")
            elif wtype == "combo":
                sv = str(v)
                if sv not in ("none","auto","undef","medium","info"):
                    parts.append(f"--{key}={sv}")
            elif wtype == "islider":
                iv = int(float(v))
                if iv != int(default):
                    parts.append(f"--{key}={iv}")
            elif wtype in ("fslider","slider"):
                fv = float(v)
                if abs(fv - float(default)) > 0.005:
                    parts.append(f"--{key}={fv:.2f}")
            elif wtype == "entry":
                sv = str(v).strip()
                if sv: parts.append(f"--{key}={sv}")
        return " ".join(parts)

    def _push_hevc_options(self):
        opts = self._build_hevc_opts_str()
        self.options_var.set(opts)
        self._log(f"Options generated ({len(opts)}B)","ok")
        self._update_hevc_preview()

    def _reset_hevc(self):
        defs = {}
        for sect_opts in HEVC_SECTIONS.values():
            for idx,(key,label,wtype,default,*_) in enumerate(sect_opts):
                uid = f"hevc_{section_uid(key)}"
                if uid not in defs: defs[uid] = (default,wtype)
                else: defs[f"hevc_{section_uid(key)}_{idx}"] = (default,wtype)
        for uid, var in self.hevc_vars.items():
            info = defs.get(uid)
            if not info: continue
            default, wtype = info
            try:
                if isinstance(var, ctk.BooleanVar): var.set(bool(default))
                elif isinstance(var, ctk.IntVar):   var.set(int(default))
                elif isinstance(var, ctk.DoubleVar): var.set(float(default))
                else: var.set(str(default))
            except Exception: pass
        self._update_hevc_preview()

    # ── Patch / replacement ───────────────────────────────────────────────────

    def _get_rep(self, olen=None):
        build  = self.build_var.get().strip()
        custom = self.custom_var.get().strip()
        prefix = self.prefix_var.get().strip() or "N"
        opts   = self.options_var.get().strip() or self._build_hevc_opts_str()
        cr     = self.copyright_var.get().strip()
        url    = self.url_var.get().strip()
        if not build:    return None,"Enter a build number"
        if not build.isdigit(): return None,"Build must be numeric"
        if self.block_bytes is None and olen is None: return None,"No file loaded"
        ol = olen if olen is not None else (self.block_end-self.block_start)
        rep, nl = build_rep(ol, build, custom, opts, prefix, cr, url)
        if rep is None: return None, f"Too long by {nl-ol}B"
        return rep, None

    def _update_preview(self, *_):
        if self.block_bytes is None: return
        rep, err = self._get_rep()
        if err:
            self._set_tb(self.preview_box, f"[ERROR] {err}")
            self.size_lbl.configure(text=err, text_color=C["ERR"])
            return
        text = rep.rstrip(b" ").decode("ascii","replace")
        self._set_tb(self.preview_box, text)
        olen = self.block_end-self.block_start
        nlen = len(rep.rstrip(b" "))
        self.size_lbl.configure(
            text=f"✓  original {olen}B  ·  new {nlen}B  ·  padding {olen-nlen}B",
            text_color=C["OK"])

    def _apply_patch(self):
        rep, err = self._get_rep()
        if err: messagebox.showerror("Error",err); return
        threading.Thread(target=self._do_patch_inplace, args=(rep,), daemon=True).start()

    def _save_as(self):
        rep, err = self._get_rep()
        if err: messagebox.showerror("Error",err); return
        out = filedialog.asksaveasfilename(
            defaultextension=self.file_path.suffix,
            initialfile=self.file_path.stem+"_patched"+self.file_path.suffix,
            filetypes=[("Video","*.mkv *.mp4 *.hevc *.265"),("All","*.*")])
        if out:
            threading.Thread(target=self._do_save_as, args=(Path(out),rep,), daemon=True).start()

    def _do_patch_inplace(self, rep):
        try:
            path = self.file_path
            if self.backup_var.get():
                bk = path.with_suffix(path.suffix+".backup")
                if not bk.exists():
                    shutil.copy(path,bk)
                    self.after(0,lambda: self._log(f"Backup → {bk.name}","ok"))
            with open(path,"r+b") as f:
                f.seek(self.block_start); f.write(rep)
                if self.patch2_var.get() and self.second_off!=-1:
                    f.seek(self.second_off); f.write(rep)
                    self.after(0,lambda: self._log(f"2nd block @ 0x{self.second_off:X}","ok"))
            self.after(0,lambda: self._log(f"Patched: {path.name}","ok"))
            self._record_history(path,rep)
            if self.remux_var.get() and path.suffix.lower()==".mkv":
                self.after(0,lambda: self._start_remux(path))
            else:
                self.after(0,lambda: messagebox.showinfo("Done","Patch applied!"))
        except Exception as ex:
            self.after(0,lambda: messagebox.showerror("Error",str(ex)))

    def _do_save_as(self, out, rep):
        try:
            data = bytearray(self.file_bytes)
            data[self.block_start:self.block_end] = rep
            if self.patch2_var.get() and self.second_off!=-1:
                data[self.second_off:self.second_off+len(rep)] = rep
            with open(out,"wb") as f: f.write(data)
            self.after(0,lambda: self._log(f"Saved: {out.name}","ok"))
            self._record_history(out,rep)
            if self.remux_var.get() and out.suffix.lower()==".mkv":
                self.after(0,lambda: self._start_remux(out))
            else:
                self.after(0,lambda: messagebox.showinfo("Done","Saved!"))
        except Exception as ex:
            self.after(0,lambda: messagebox.showerror("Error",str(ex)))

    # ── mkvmerge ─────────────────────────────────────────────────────────────

    def _start_remux(self, path):
        self.remux_status_lbl.configure(text="⟳  remuxing…", text_color=C["WARN"])
        threading.Thread(target=self._do_remux, args=(path,), daemon=True).start()

    def _do_remux(self, path: Path):
        mkvmerge = self.mkvmerge_var.get().strip() or "mkvmerge"
        tmp = path.with_suffix(".tmp_remux.mkv")
        try:
            cmd = [mkvmerge,"-o",str(tmp),str(path)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode not in (0,1):
                raise RuntimeError(r.stderr.strip() or "mkvmerge failed")
            path.unlink(); tmp.rename(path)
            self.after(0,lambda: self._log(f"Remux done: {path.name}","ok"))
            self.after(0,lambda: self.remux_status_lbl.configure(
                text="✓  remux done — Writing application = mkvmerge", text_color=C["OK"]))
            self.after(0,lambda: messagebox.showinfo("Done","Patch + remux complete!"))
        except FileNotFoundError:
            if tmp.exists(): tmp.unlink()
            self.after(0,lambda: self._log("mkvmerge not found","err"))
            self.after(0,lambda: self.remux_status_lbl.configure(
                text="✗  mkvmerge not found", text_color=C["ERR"]))
        except Exception as ex:
            if tmp.exists(): tmp.unlink()
            self.after(0,lambda: self._log(f"Remux error: {ex}","err"))
            self.after(0,lambda: self.remux_status_lbl.configure(
                text=f"✗  {ex}", text_color=C["ERR"]))

    # ── Batch ─────────────────────────────────────────────────────────────────

    def _batch_add_files(self):
        paths = filedialog.askopenfilenames(
            title="Add files",
            filetypes=[("Video","*.mkv *.mp4 *.hevc *.265 *.h265 *.ts *.m2ts"),
                       ("All","*.*")])
        for p in paths:
            fp=Path(p)
            if fp not in self.batch_files: self.batch_files.append(fp)
        self._refresh_batch_list()

    def _batch_add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            exts={".mkv",".mp4",".hevc",".265",".h265",".ts",".m2ts"}
            for p in Path(folder).rglob("*"):
                if p.suffix.lower() in exts and p not in self.batch_files:
                    self.batch_files.append(p)
        self._refresh_batch_list()

    def _batch_clear(self):
        self.batch_files.clear()
        self._refresh_batch_list()

    def _refresh_batch_list(self):
        lines=[f"[{i+1:>3}]  {p}" for i,p in enumerate(self.batch_files)]
        self._set_tb(self.batch_list_box,"\n".join(lines) or "No files.")
        self.batch_count_lbl.configure(text=f"{len(self.batch_files)} files")

    def _run_batch(self):
        if not self.batch_files:
            messagebox.showwarning("Empty","Add files first."); return
        build=self.build_var.get().strip()
        if not build or not build.isdigit():
            messagebox.showerror("Error","Set a valid build number in Patch tab first."); return
        custom=self.custom_var.get().strip()
        prefix=self.prefix_var.get().strip() or "N"
        opts=self.options_var.get().strip() or self._build_hevc_opts_str()
        cr=self.copyright_var.get().strip()
        url=self.url_var.get().strip()
        mode=self.batch_mode_var.get()
        suffix=self.batch_suffix_var.get()
        outdir=self.batch_outdir_var.get().strip()
        do_remux=self.remux_var.get()
        do_backup=self.backup_var.get()
        do_patch2=self.patch2_var.get()
        mkvmerge=self.mkvmerge_var.get().strip() or "mkvmerge"

        self.batch_stop_var.set(False)
        self.batch_run_btn.configure(state="disabled")
        self.batch_pb.set(0)
        total=len(self.batch_files)

        def run():
            ok=err_c=skip=0
            for i,path in enumerate(self.batch_files):
                if self.batch_stop_var.get():
                    self.after(0,lambda: self._blog("Stopped by user","warn"))
                    break
                self.after(0,lambda i=i,p=path: (
                    self.batch_stat_lbl.configure(text=f"{i+1}/{total} {p.name[:30]}"),
                    self.batch_pb.set((i)/total)
                ))
                try:
                    with open(path,"rb") as f:
                        buf=f.read(SCAN_SIZE)
                    found=find_x265_block(buf)
                    if not found:
                        self.after(0,lambda p=path: self._blog(f"SKIP no block: {p.name}","err"))
                        skip+=1; continue

                    s,e,blk=found
                    olen=e-s
                    rep,nl=build_rep(olen,build,custom,opts,prefix,cr,url)
                    if rep is None:
                        self.after(0,lambda p=path,nl=nl,olen=olen:
                            self._blog(f"SKIP too long {nl}B>{olen}B: {p.name}","err"))
                        skip+=1; continue

                    with open(path,"rb") as f: full=f.read()
                    found2=find_x265_block(bytearray(full),e)
                    second=found2[0] if found2 and found2[2]==blk else -1

                    if mode=="inplace":
                        out_path=path
                        if do_backup:
                            bk=path.with_suffix(path.suffix+".backup")
                            if not bk.exists(): shutil.copy(path,bk)
                    elif mode=="suffix":
                        out_path=path.with_name(path.stem+suffix+path.suffix)
                    else:
                        if not outdir:
                            self.after(0,lambda: self._blog("No output folder set","err"))
                            skip+=1; continue
                        Path(outdir).mkdir(parents=True,exist_ok=True)
                        out_path=Path(outdir)/path.name

                    data=bytearray(full)
                    data[s:e]=rep
                    if do_patch2 and second!=-1:
                        data[second:second+len(rep)]=rep
                    with open(out_path,"wb") as f: f.write(data)

                    if do_remux and out_path.suffix.lower()==".mkv":
                        tmp=out_path.with_suffix(".tmp_remux.mkv")
                        r=subprocess.run([mkvmerge,"-o",str(tmp),str(out_path)],
                                         capture_output=True,text=True,timeout=600)
                        if r.returncode in (0,1):
                            out_path.unlink(); tmp.rename(out_path)
                            self.after(0,lambda p=path: self._blog(f"✓ remux+patch: {p.name}","ok"))
                        else:
                            if tmp.exists(): tmp.unlink()
                            raise RuntimeError(f"mkvmerge: {r.stderr[:60]}")
                    else:
                        self.after(0,lambda p=path: self._blog(f"✓ patched: {p.name}","ok"))
                    ok+=1
                except Exception as ex:
                    self.after(0,lambda p=path,ex=ex: self._blog(f"✗ {p.name}: {ex}","err"))
                    err_c+=1
                self.after(0,lambda v=(i+1)/total: self.batch_pb.set(v))

            def done():
                self.batch_stat_lbl.configure(text=f"Done · {ok} ok · {err_c} err · {skip} skip")
                self.batch_run_btn.configure(state="normal")
                self.batch_pb.set(1)
                messagebox.showinfo("Batch done",
                    f"Finished {total} files\n✓ {ok} patched\n✗ {err_c} errors\n⊘ {skip} skipped")
            self.after(0,done)
        threading.Thread(target=run, daemon=True).start()

    # ── H.264 remover ─────────────────────────────────────────────────────────

    def _h264_browse(self):
        p=filedialog.askopenfilename(
            title="Select MKV",
            filetypes=[("MKV","*.mkv"),("All","*.*")])
        if p: self.h264_file_var.set(p)

    def _h264_remove_single(self):
        path=Path(self.h264_file_var.get().strip())
        if not path.exists():
            messagebox.showerror("Error","File not found."); return
        mode=self.h264_mode_var.get()
        threading.Thread(target=self._do_h264_remove,
                         args=([path],mode), daemon=True).start()

    def _h264_batch(self):
        folder=Path(self.h264_batch_dir_var.get().strip())
        if not folder.exists():
            messagebox.showerror("Error","Folder not found."); return
        glob = folder.rglob("*.mkv") if self.h264_recursive_var.get() else folder.glob("*.mkv")
        files=list(glob)
        if not files:
            messagebox.showwarning("No files","No MKV files found."); return
        threading.Thread(target=self._do_h264_remove,
                         args=(files,"inplace"), daemon=True).start()

    def _do_h264_remove(self, paths, mode):
        mkvmerge=self.mkvmerge_var.get().strip() or "mkvmerge"
        ok=err_c=0
        for path in paths:
            try:
                # probe tracks with mkvmerge -J
                probe=subprocess.run([mkvmerge,"-J",str(path)],
                                     capture_output=True,text=True,timeout=60)
                if probe.returncode!=0:
                    raise RuntimeError("mkvmerge -J failed")
                info=json.loads(probe.stdout)
                tracks=info.get("tracks",[])

                hevc_ids=[t["id"] for t in tracks
                          if t.get("codec","").upper() in ("HEVC","H.265","H265","V_MPEGH/ISO/HEVC")]
                h264_ids=[t["id"] for t in tracks
                          if t.get("codec","").upper() in ("AVC","H.264","H264","V_MPEG4/ISO/AVC")]

                if not hevc_ids:
                    self.after(0,lambda p=path: self._hlog(f"SKIP no HEVC track: {p.name}","err"))
                    continue
                if not h264_ids:
                    self.after(0,lambda p=path: self._hlog(f"SKIP no H.264 track: {p.name}","err"))
                    continue

                # build track exclusion args
                exclude=[f"!{tid}" for tid in h264_ids]
                track_arg=",".join([str(tid) for tid in
                                    [t["id"] for t in tracks if t["id"] not in h264_ids]])

                if mode=="saveas":
                    out=path.with_name(path.stem+"_hevc_only"+path.suffix)
                else:
                    out=path.with_suffix(".h264rm_tmp.mkv")

                cmd=[mkvmerge,"-o",str(out),
                     "--video-tracks",
                     ",".join(str(i) for i in hevc_ids),
                     str(path)]
                r=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
                if r.returncode not in (0,1):
                    if out.exists(): out.unlink()
                    raise RuntimeError(r.stderr.strip()[:80])

                if mode=="inplace":
                    path.unlink(); out.rename(path)

                self.after(0,lambda p=path: self._hlog(f"✓ H.264 removed: {p.name}","ok"))
                ok+=1
            except Exception as ex:
                self.after(0,lambda p=path,ex=ex: self._hlog(f"✗ {p.name}: {ex}","err"))
                err_c+=1

        self.after(0,lambda: messagebox.showinfo("Done",
            f"H.264 removal complete\n✓ {ok} done\n✗ {err_c} errors"))

    # ── Presets ───────────────────────────────────────────────────────────────

    def _save_preset(self):
        name=self.preset_name_var.get().strip()
        build=self.preset_build_var.get().strip()
        if not name:
            messagebox.showwarning("Error","Enter a preset name."); return
        p={
            "name":name,"build":build,
            "custom":self.preset_custom_var.get().strip(),
            "options":self.preset_options_var.get().strip(),
            "duration":self.preset_duration_var.get(),
        }
        presets=self.cfg.get("presets",list(DEFAULT_PRESETS))
        # update if name exists
        found=False
        for i,pr in enumerate(presets):
            if pr["name"]==name:
                presets[i]=p; found=True; break
        if not found: presets.append(p)
        self.cfg["presets"]=presets
        save_cfg(self.cfg)
        self._refresh_presets_ui()
        self._log(f"Preset saved: {name}","ok")

    def _delete_preset(self, idx):
        presets=self.cfg.get("presets",list(DEFAULT_PRESETS))
        if 0<=idx<len(presets):
            del presets[idx]
            self.cfg["presets"]=presets
            save_cfg(self.cfg)
            self._refresh_presets_ui()

    def _apply_preset(self, pr):
        build=pr.get("build","")
        dur=pr.get("duration","any")
        # auto-adjust CRF in options string for duration
        opts=pr.get("options","")
        if dur=="short":
            # boost quality slightly
            opts=self._shift_crf(opts,-2)
        elif dur=="long":
            opts=self._shift_crf(opts,+2)

        self.build_var.set(build)
        self.custom_var.set(pr.get("custom",""))
        self.options_var.set(opts)
        self._log(f"Preset applied: {pr.get('name','')}","ok")
        self.tabs.set("  Patch  ")

    def _shift_crf(self, opts_str, delta):
        def repl(m):
            old=float(m.group(1))
            new=max(0,min(51,old+delta))
            return f"--crf={new:.1f}"
        return re.sub(r"--crf=(\d+\.?\d*)", repl, opts_str)

    def _load_into_creator(self):
        self.preset_build_var.set(self.build_var.get())
        self.preset_custom_var.set(self.custom_var.get())
        self.preset_options_var.set(self.options_var.get())
        self.tabs.set("  Presets  ")

    # ── Misc actions ─────────────────────────────────────────────────────────

    def _restore_backup(self):
        if not self.file_path:
            messagebox.showwarning("No file","Load a file first."); return
        bk=self.file_path.with_suffix(self.file_path.suffix+".backup")
        if not bk.exists():
            messagebox.showwarning("No backup",f"No backup: {bk.name}"); return
        if messagebox.askyesno("Restore",f"Restore from {bk.name}?"):
            shutil.copy(bk,self.file_path)
            self._log("Backup restored","ok")

    def _clear_patch(self):
        self.build_var.set(""); self.custom_var.set("")
        self.options_var.set("")
        self._set_tb(self.preview_box,"")
        self.size_lbl.configure(text="")

    def _browse_mkvmerge(self):
        p=filedialog.askopenfilename(
            title="mkvmerge.exe",
            filetypes=[("Executable","*.exe"),("All","*.*")])
        if p: self.mkvmerge_var.set(p)

    def _record_history(self, path, rep):
        e={"time":datetime.now().isoformat(),"file":str(path),
           "build":self.build_var.get(),"custom":self.custom_var.get(),
           "options":self.options_var.get()[:200]}
        h=self.cfg.get("history",[])
        h.insert(0,e); self.cfg["history"]=h[:100]
        save_cfg(self.cfg)
        self.after(0,self._refresh_history)

    def _refresh_history(self):
        h=self.cfg.get("history",[])
        lines=[]
        for e in h:
            lines.append(f"[{e['time'][:19]}]  {Path(e['file']).name}")
            lines.append(f"  build={e['build']}  tag={e['custom']}")
            if e.get("options"): lines.append(f"  opts={e['options'][:100]}")
            lines.append("")
        self._set_tb(self.hist_box,"\n".join(lines) or "No history.")

    def _clear_history(self):
        self.cfg["history"]=[]; save_cfg(self.cfg); self._refresh_history()

    def _restore_settings(self):
        last=self.cfg.get("last",{})
        for attr,key in [("build_var","build_var"),("custom_var","custom_var")]:
            v=last.get(key,"")
            if v:
                try: getattr(self,attr).set(v)
                except Exception: pass

    def on_close(self):
        self.cfg["last"]={"build_var":self.build_var.get(),
                          "custom_var":self.custom_var.get()}
        self.cfg["mkvmerge"]=self.mkvmerge_var.get()
        save_cfg(self.cfg)
        if self._tip_after: self.after_cancel(self._tip_after)
        self.destroy()


# ── helpers ───────────────────────────────────────────────────────────────────

def section_uid(key):
    return key.replace("-","_").replace(".","_")


if __name__ == "__main__":

    root = tk.Tk()
    root.withdraw()
    SplashScreen(root, lambda: None)
    root.mainloop()  
    
    try:
        root.destroy()
    except Exception:
        pass

    import time as _time
    _time.sleep(0.3)

    app = MetaPatchApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()