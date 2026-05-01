#!/usr/bin/env python3
"""
Ladybug Stitch Co. — EmbroideryStudio v2.0
============================================
Professional embroidery design software.

Features:
  - BX font library  (Embrilliance-compatible .bx fonts)
  - Text tool        (type text using any loaded font)
  - Image digitizing (PNG/JPG → embroidery stitches)
  - Design splitting (multi-hoop)
  - Stitch preview with zoom/pan
  - Export: PES · DST · JEF · EXP · VP3 and 50+ formats

Requirements:
  pip install pyembroidery Pillow numpy opencv-python

Usage:
  python embroidery_studio.py
"""

import os
import sys
import json
import math
import zipfile
import tempfile
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("ERROR: Pillow not installed.  pip install Pillow")
    sys.exit(1)

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import pyembroidery
    HAS_PYEMBROIDERY = True
except ImportError:
    HAS_PYEMBROIDERY = False


# ═══════════════════════════════════════════════════════════════════════════════
#  Brand / theme
# ═══════════════════════════════════════════════════════════════════════════════

APP_NAME    = "Ladybug Stitch Co."
APP_SUB     = "EmbroideryStudio"
VERSION     = "2.0.0"

# Ladybug Stitch Co. palette
LB_RED      = "#C0392B"      # ladybug red
LB_RED_LT   = "#E74C3C"      # hover / accent
LB_RED_DK   = "#96281B"      # pressed / shadow
LB_PINK     = "#FADADD"      # soft pink background
LB_ROSE     = "#F5A7B0"      # medium rose
LB_CREAM    = "#FFF8F8"      # canvas / panel background
LB_DARK     = "#3D1A1A"      # near-black text
LB_GRAY     = "#BDC3C7"      # borders / grid
LB_WHITE    = "#FFFFFF"

CANVAS_BG   = "#F9F2F2"      # very light pink canvas
HOOP_COLOR  = "#B0868A"

HOOP_SIZES = {
    "4×4  (100×100 mm)": (100, 100),
    "5×7  (130×180 mm)": (130, 180),
    "6×10 (150×250 mm)": (150, 250),
    "8×8  (200×200 mm)": (200, 200),
    "11×8 (280×200 mm)": (280, 200),
    "Custom":             (150, 150),
}

WRITE_FORMATS = [
    ("Brother PES", "*.pes"),
    ("Tajima DST",  "*.dst"),
    ("Janome JEF",  "*.jef"),
    ("Elna EXP",    "*.exp"),
    ("VP3",         "*.vp3"),
    ("All files",   "*.*"),
]
READ_FORMATS = [
    ("Embroidery Files",
     "*.pes *.dst *.jef *.exp *.vp3 *.hus *.sew *.xxx *.pec *.ksm"),
    ("Brother PES", "*.pes"),
    ("Tajima DST",  "*.dst"),
    ("Janome JEF",  "*.jef"),
    ("All files",   "*.*"),
]

PALETTE = [
    "#C0392B","#E74C3C","#FF8A80","#FADADD","#F39C12","#F5CBA7",
    "#27AE60","#A9DFBF","#2980B9","#AED6F1","#8E44AD","#D2B4DE",
    "#000000","#7F8C8D","#BDC3C7","#FFFFFF",
]

# Stitch type codes
STITCH = 0; JUMP = 1; TRIM = 2; COLOR_CHANGE = 4; END = 16


# ═══════════════════════════════════════════════════════════════════════════════
#  Persistent settings
# ═══════════════════════════════════════════════════════════════════════════════

class AppSettings:
    CONFIG_DIR  = Path.home() / ".ladybug_stitch"
    CONFIG_FILE = CONFIG_DIR  / "config.json"
    DEFAULTS    = {
        "font_folder":  "",
        "last_file":    "",
        "hoop":         "4×4  (100×100 mm)",
        "show_jumps":   False,
        "text_size_mm": 25.4,
        "text_spacing": 1.5,
    }

    def __init__(self):
        self._d = dict(self.DEFAULTS)
        self._load()

    def _load(self):
        try:
            if self.CONFIG_FILE.exists():
                with open(self.CONFIG_FILE) as f:
                    self._d.update(json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_FILE, "w") as f:
                json.dump(self._d, f, indent=2)
        except Exception:
            pass

    def get(self, key, fallback=None):
        return self._d.get(key, fallback if fallback is not None
                           else self.DEFAULTS.get(key))

    def set(self, key, value):
        self._d[key] = value
        self.save()


# ═══════════════════════════════════════════════════════════════════════════════
#  Internal design representation
# ═══════════════════════════════════════════════════════════════════════════════

class StitchThread:
    def __init__(self, color="#000000", name="Thread"):
        self.color    = color
        self.name     = name
        self.stitches = []          # (x, y, stitch_type)  — 0.1 mm units

    def add_stitch(self, x, y, t=STITCH):
        self.stitches.append((int(x), int(y), t))

    def add_jump(self, x, y):
        self.stitches.append((int(x), int(y), JUMP))


class EmbroideryDesign:
    def __init__(self):
        self.threads  = []
        self.filepath = None
        self.name     = "Untitled"

    def clear(self):
        self.threads = []

    # ── aggregates ────────────────────────────────────────────────────────

    @property
    def stitch_count(self):
        return sum(sum(1 for *_, t in th.stitches if t == STITCH)
                   for th in self.threads)

    @property
    def color_count(self):
        return len(self.threads)

    def get_bounds(self):
        xs, ys = [], []
        for th in self.threads:
            for x, y, _ in th.stitches:
                xs.append(x); ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 1, 1)

    @property
    def width_mm(self):
        b = self.get_bounds(); return (b[2]-b[0])/10.0

    @property
    def height_mm(self):
        b = self.get_bounds(); return (b[3]-b[1])/10.0

    # ── pyembroidery bridge ───────────────────────────────────────────────

    def from_pyembroidery(self, pattern):
        self.clear()
        if not pattern:
            return
        colors = getattr(pattern, "threadlist", [])

        def hex_from(idx):
            if idx < len(colors):
                c = colors[idx]
                rgb = getattr(c, "color", None)
                if rgb is not None:
                    return "#{:06X}".format(rgb)
            return PALETTE[idx % len(PALETTE)]

        ci  = 0
        cur = StitchThread(hex_from(0), "Thread 1")
        for sx, sy, cmd in pattern.stitches:
            base = cmd & 0xFF
            if base == pyembroidery.COLOR_CHANGE:
                if cur.stitches: self.threads.append(cur)
                ci += 1; cur = StitchThread(hex_from(ci), f"Thread {ci+1}")
            elif base == pyembroidery.END:
                break
            elif base == pyembroidery.STITCH:
                cur.add_stitch(sx, sy)
            elif base in (pyembroidery.JUMP, pyembroidery.TRIM):
                cur.add_jump(sx, sy)
        if cur.stitches: self.threads.append(cur)

    def to_pyembroidery(self):
        if not HAS_PYEMBROIDERY: return None
        pat = pyembroidery.EmbPattern()
        for i, th in enumerate(self.threads):
            if i > 0: pat.add_command(pyembroidery.COLOR_CHANGE)
            t = pyembroidery.EmbThread()
            t.color = int(th.color.lstrip("#"), 16)
            t.name  = th.name
            pat.threadlist.append(t)
            for x, y, st in th.stitches:
                cmd = pyembroidery.STITCH if st == STITCH else pyembroidery.JUMP
                pat.add_stitch_absolute(cmd, x, y)
        pat.add_command(pyembroidery.END)
        return pat


# ═══════════════════════════════════════════════════════════════════════════════
#  BX font system
# ═══════════════════════════════════════════════════════════════════════════════

# Known character name ↔ glyph filename stems
_CHAR_NAMES = {
    "space": " ", "sp": " ", "blank": " ",
    "period": ".", "dot": ".", "fullstop": ".",
    "comma": ",", "exclaim": "!", "exclamation": "!",
    "question": "?", "questionmark": "?",
    "colon": ":", "semicolon": ";",
    "apostrophe": "'", "quote": '"', "dquote": '"',
    "hyphen": "-", "dash": "-", "minus": "-",
    "ampersand": "&", "and": "&",
    "at": "@", "atsign": "@",
    "num": "#", "hash": "#", "pound": "#",
    "dollar": "$", "percent": "%",
    "underscore": "_", "slash": "/", "fslash": "/",
    "backslash": "\\", "bslash": "\\",
    "lparen": "(", "rparen": ")",
    "lbracket": "[", "rbracket": "]",
    "plus": "+", "equals": "=", "star": "*", "asterisk": "*",
    "tilde": "~", "caret": "^",
    "lt": "<", "gt": ">",
}

_EMB_EXTS = {".pes", ".dst", ".jef", ".exp", ".vp3",
             ".hus", ".sew", ".xxx", ".pec", ".ksm", ".shv"}


class BXGlyph:
    """Stitch data for a single character."""
    def __init__(self, char, design):
        self.char   = char
        self.design = design

    @property
    def width_mm(self):  return self.design.width_mm
    @property
    def height_mm(self): return self.design.height_mm


class BXFont:
    """
    Embrilliance .bx font — multi-strategy loader.

    Loading strategies (tried in order):
      1. BX001 binary  — scan the binary for embedded #PES blocks; try several
                         heuristics to map each block to a character code.
      2. ZIP archive   — some older/third-party .bx files are plain ZIPs.
      3. Companion dir — look for a folder named exactly like the .bx file
                         (minus extension) sitting next to it, containing
                         individual embroidery files per glyph.
      4. Companion PES — look for files like  FontName_A.pes / FontName065.pes
                         in the same directory as the .bx file.

    Filename → character conventions for strategies 3 & 4:
      Single letter:   A.pes  →  'A'
      Decimal ASCII:   065.pes → 'A'   (chr(65))
      Named alias:     space.pes → ' ',  period.pes → '.'
      Hex code:        41.pes (hex 41 = 'A')
    """

    def __init__(self, path):
        self.path    = Path(path)
        self.name    = self.path.stem
        self.glyphs  = {}       # char → BXGlyph  (lazy-loaded)
        # _index values are one of:
        #   ('file', Path)           – companion/ZIP file path
        #   ('bx001', int, int)      – (start_byte, end_byte) inside self.path
        self._index  = {}
        self._ok     = False
        self._scan()

    # ── top-level scan ────────────────────────────────────────────────────

    def _scan(self):
        try:
            raw = self.path.read_bytes()
        except Exception as e:
            print(f"BXFont: cannot read {self.path.name}: {e}")
            return

        # Strategy 1 – BX001 proprietary binary
        if raw[:5] == b'BX001':
            self._scan_bx001(raw)

        # Strategy 2 – ZIP archive (older / third-party fonts)
        if not self._ok:
            try:
                if zipfile.is_zipfile(self.path):
                    self._scan_zip()
            except Exception:
                pass

        # Strategy 3 – companion folder  (FontName/ next to FontName.bx)
        if not self._ok:
            companion_dir = self.path.parent / self.path.stem
            if companion_dir.is_dir():
                self._scan_folder(companion_dir)

        # Strategy 4 – PES files in same dir prefixed with font name
        if not self._ok:
            self._scan_sibling_files()

        if self._ok:
            print(f"BXFont loaded: {self.path.name} — "
                  f"{len(self._index)} chars via "
                  f"{'bx001' if any(v[0]=='bx001' for v in self._index.values()) else 'files'}")
        else:
            print(f"BXFont: no glyphs found in {self.path.name}")

    # ── Strategy 1: BX001 binary ──────────────────────────────────────────

    def _scan_bx001(self, data):
        """
        Scan binary BX001 file for embedded #PES blocks and map them to chars.

        The BX001 format stores each glyph as an embedded PES file.
        Before each PES block the character code is encoded in one of several
        ways depending on the Embrilliance version; we try them all.
        """
        import struct, re as _re

        size = len(data)
        # Collect all #PES start positions
        pes_pos = [m.start() for m in _re.finditer(b'#PES', data)]
        if not pes_pos:
            return

        # Build end-of-block map (each block runs to the next #PES start)
        pes_ends = {}
        for i, p in enumerate(pes_pos):
            pes_ends[p] = pes_pos[i + 1] if i + 1 < len(pes_pos) else size

        assigned = {}   # char → (start, end)

        for p in pes_pos:
            ch = None

            # ── Try various pre-PES encodings ────────────────────────────
            # Layout A:  [uint8 char_code] [uint32 length] [#PES ...]
            if p >= 5:
                b = data[p - 5]
                if 32 <= b <= 126:
                    ch = chr(b)

            # Layout B:  [uint16-LE char_code] [uint32 length] [#PES ...]
            if ch is None and p >= 6:
                v = struct.unpack_from('<H', data, p - 6)[0]
                if 32 <= v <= 126:
                    ch = chr(v)

            # Layout C:  [uint8 char_code] [#PES ...]  (no length prefix)
            if ch is None and p >= 1:
                b = data[p - 1]
                if 32 <= b <= 126 and b not in (ord('#'), ord('P'), ord('E'), ord('S')):
                    ch = chr(b)

            # Layout D:  [uint16-LE char_code] [#PES ...]  (no length prefix)
            if ch is None and p >= 2:
                v = struct.unpack_from('<H', data, p - 2)[0]
                if 32 <= v <= 126:
                    ch = chr(v)

            # Layout E: check 4–12 bytes before for a plausible ASCII char
            if ch is None and p >= 4:
                for look in range(4, min(13, p)):
                    b = data[p - look]
                    if 32 <= b <= 126 and b not in (ord('#'), ord('P'), ord('E'), ord('S')):
                        ch = chr(b)
                        break

            if ch and ch not in assigned:
                assigned[ch] = (p, pes_ends[p])

        # ── Sequential fallback ───────────────────────────────────────────
        # If we couldn't map chars via heuristics, assume glyphs are stored
        # in sequential ASCII order starting from space (32) or 'A' (65).
        if not assigned:
            # Guess starting code: if ~26 blocks, start at 'A'; if ~95, at ' '
            n = len(pes_pos)
            start_code = 65 if n <= 30 else 32
            for i, p in enumerate(pes_pos):
                code = start_code + i
                if 32 <= code <= 126:
                    ch = chr(code)
                    assigned[ch] = (p, pes_ends[p])

        for ch, (start, end) in assigned.items():
            self._index[ch] = ('bx001', start, end)

        self._ok = len(self._index) > 0

    # ── Strategy 2: ZIP archive ───────────────────────────────────────────

    def _scan_zip(self):
        with zipfile.ZipFile(self.path, "r") as zf:
            for member in zf.namelist():
                p    = Path(member)
                ext  = p.suffix.lower()
                if ext not in _EMB_EXTS:
                    continue
                ch = self._stem_to_char(p.stem)
                if ch and ch not in self._index:
                    self._index[ch] = ('zip', member)
        self._ok = len(self._index) > 0

    # ── Strategy 3 & 4: folder / sibling files ───────────────────────────

    def _scan_folder(self, folder):
        for f in folder.rglob("*"):
            if f.suffix.lower() not in _EMB_EXTS:
                continue
            ch = self._stem_to_char(f.stem)
            if ch and ch not in self._index:
                self._index[ch] = ('file', f)
        self._ok = len(self._index) > 0

    def _scan_sibling_files(self):
        prefix = self.path.stem.lower() + "_"
        for f in self.path.parent.iterdir():
            if f.suffix.lower() not in _EMB_EXTS:
                continue
            stem = f.stem
            # Match  FontName_A.pes  or  FontName_065.pes
            if stem.lower().startswith(prefix):
                rest = stem[len(prefix):]
            else:
                rest = stem
            ch = self._stem_to_char(rest)
            if ch and ch not in self._index:
                self._index[ch] = ('file', f)
        self._ok = len(self._index) > 0

    # ── char resolution helper ────────────────────────────────────────────

    @staticmethod
    def _stem_to_char(stem):
        """Convert a filename stem to a single character, or None."""
        stemL = stem.lower()
        # single character
        if len(stem) == 1:
            return stem
        # named alias
        if stemL in _CHAR_NAMES:
            return _CHAR_NAMES[stemL]
        # decimal ASCII  065 → 'A'
        if stemL.isdigit():
            code = int(stemL)
            if 32 <= code <= 126:
                return chr(code)
        # hex ASCII  41 → 'A'
        try:
            code = int(stemL, 16)
            if 32 <= code <= 126:
                return chr(code)
        except ValueError:
            pass
        return None

    # ── properties ───────────────────────────────────────────────────────

    @property
    def is_valid(self):         return self._ok
    @property
    def char_count(self):       return len(self._index)
    @property
    def available_chars(self):  return set(self._index.keys())

    def has_char(self, ch):
        return (ch in self._index or ch.lower() in self._index
                or ch.upper() in self._index)

    # ── glyph loading ─────────────────────────────────────────────────────

    def get_glyph(self, ch):
        """Return BXGlyph for ch, loading stitch data on first access."""
        if ch in self.glyphs:
            return self.glyphs[ch]

        entry = (self._index.get(ch) or self._index.get(ch.lower())
                 or self._index.get(ch.upper()))
        if entry is None:
            return None

        try:
            if not HAS_PYEMBROIDERY:
                return None

            pat = self._load_entry(entry)
            if pat is None:
                return None
            design = EmbroideryDesign()
            design.from_pyembroidery(pat)
            if not design.threads:
                return None
            g = BXGlyph(ch, design)
            self.glyphs[ch] = g
            return g
        except Exception as e:
            print(f"Glyph load error [{ch}] in {self.path.name}: {e}")
            return None

    def _load_entry(self, entry):
        """Load a pyembroidery pattern from any entry type."""
        kind = entry[0]

        if kind == 'file':
            _, fpath = entry
            return pyembroidery.read(str(fpath))

        if kind == 'zip':
            _, member = entry
            suffix = Path(member).suffix
            with zipfile.ZipFile(self.path, "r") as zf:
                raw = zf.read(member)
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(raw); tmp_path = tmp.name
            try:
                return pyembroidery.read(tmp_path)
            finally:
                try: os.unlink(tmp_path)
                except: pass

        if kind == 'bx001':
            _, start, end = entry
            raw = self.path.read_bytes()[start:end]
            with tempfile.NamedTemporaryFile(suffix='.pes', delete=False) as tmp:
                tmp.write(raw); tmp_path = tmp.name
            try:
                return pyembroidery.read(tmp_path)
            finally:
                try: os.unlink(tmp_path)
                except: pass

        return None

    # ── text rendering ────────────────────────────────────────────────────

    def render_text(self, text, size_mm=25.4,
                    letter_spacing_mm=1.2, word_spacing_mm=7.0):
        """
        Lay out *text* and return an EmbroideryDesign.
        size_mm   : desired cap-height in mm.
        """
        result = EmbroideryDesign()
        result.name = "text_" + text[:24].replace(" ", "_")

        # ── determine scale from reference glyph ─────────────────────────
        ref = None
        for probe in ("H", "A", "B", "M", "h", "a"):
            g = self.get_glyph(probe)
            if g and g.height_mm > 0:
                ref = g; break
        scale = (size_mm / ref.height_mm) if ref else 1.0

        cursor_x_mm = 0.0    # running x-position in mm

        # Merge same-colour threads to avoid needless colour changes
        colour_map = {}      # hex_colour → StitchThread in result

        def get_thread(colour):
            if colour not in colour_map:
                t = StitchThread(colour, f"T{len(colour_map)+1}")
                colour_map[colour] = t
                result.threads.append(t)
            return colour_map[colour]

        for ch in text:
            if ch == " ":
                cursor_x_mm += word_spacing_mm * scale
                continue
            if ch in ("\n", "\r"):
                continue

            g = self.get_glyph(ch)
            if g is None:
                cursor_x_mm += word_spacing_mm * 0.5 * scale
                continue

            b = g.design.get_bounds()   # in 0.1-mm units

            for th in g.design.threads:
                dst = get_thread(th.color)
                for x, y, st in th.stitches:
                    nx = int((x - b[0]) * scale + cursor_x_mm * 10)
                    ny = int((y - b[1]) * scale)
                    dst.stitches.append((nx, ny, st))

            cursor_x_mm += g.width_mm * scale + letter_spacing_mm

        return result


class FontLibrary:
    """
    Manages all BX fonts in the user-specified folder.
    Results are cached; call scan() to refresh.

    Also picks up "loose" font folders — subdirectories that contain
    embroidery files per glyph but no .bx file.
    """

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.fonts    = {}   # name → BXFont

    @property
    def folder(self):
        return self.settings.get("font_folder", "")

    def scan(self, progress=None):
        self.fonts.clear()
        folder = self.folder
        if not folder or not os.path.isdir(folder):
            if progress:
                progress(100, "No font folder set — choose one in Settings.")
            return

        root = Path(folder)

        # ── collect candidate paths ──────────────────────────────────────
        # 1. Every .bx file found anywhere under the font folder
        bx_files = list(root.rglob("*.bx"))

        # 2. Direct sub-folders that contain embroidery files but no .bx
        loose_dirs = []
        for d in root.iterdir():
            if not d.is_dir():
                continue
            # Skip folders that already have a sibling .bx (handled above)
            has_bx = any(d.parent.glob(d.name + ".bx"))
            if has_bx:
                continue
            emb_files = [f for f in d.iterdir()
                         if f.suffix.lower() in _EMB_EXTS]
            if len(emb_files) >= 5:      # at least 5 glyphs → treat as font
                loose_dirs.append(d)

        total = len(bx_files) + len(loose_dirs)
        if total == 0:
            if progress:
                progress(100, "No font files found in that folder.")
            return

        done = 0

        # ── load .bx files ───────────────────────────────────────────────
        for f in bx_files:
            if progress:
                progress(int(100 * done / total), f"Scanning {f.name} …")
            try:
                font = BXFont(f)
                if font.is_valid:
                    self.fonts[font.name] = font
                    print(f"  ✓ {font.name}  ({font.char_count} glyphs)")
                else:
                    print(f"  ✗ {f.name}  (no glyphs found)")
            except Exception as e:
                print(f"FontLibrary: skip {f.name} — {e}")
            done += 1

        # ── load loose folders ───────────────────────────────────────────
        for d in loose_dirs:
            if progress:
                progress(int(100 * done / total), f"Scanning folder {d.name} …")
            try:
                font = _LooseFont(d)
                if font.is_valid:
                    self.fonts[font.name] = font
                    print(f"  ✓ {font.name}  ({font.char_count} glyphs, loose folder)")
            except Exception as e:
                print(f"FontLibrary: skip folder {d.name} — {e}")
            done += 1

        if progress:
            progress(100, f"Loaded {len(self.fonts)} font(s).")

    def names(self):
        return sorted(self.fonts.keys(), key=str.lower)

    def get(self, name):
        return self.fonts.get(name)


class _LooseFont(BXFont):
    """
    Treat a plain folder full of embroidery files as a BX-style font.
    Re-uses BXFont's glyph machinery; just skips the .bx binary scan.
    """
    def __init__(self, folder_path):
        self.path    = Path(folder_path)
        self.name    = self.path.name
        self.glyphs  = {}
        self._index  = {}
        self._ok     = False
        self._scan_folder(self.path)    # strategy 3 directly


# ═══════════════════════════════════════════════════════════════════════════════
#  Digitizer
# ═══════════════════════════════════════════════════════════════════════════════

class Digitizer:
    UNITS_PER_MM = 10

    def __init__(self, num_colors=6, stitch_mm=2.5, width_mm=100, height_mm=100):
        self.num_colors = max(2, min(num_colors, 16))
        self.stitch_mm  = stitch_mm
        self.width_mm   = width_mm
        self.height_mm  = height_mm

    def digitize(self, image_path, progress=None):
        def _p(pct, msg):
            if progress: progress(pct, msg)

        _p(5,  "Loading image …")
        img = Image.open(image_path).convert("RGB")
        aspect = img.width / img.height
        if aspect >= 1:
            tw, th = int(self.width_mm), int(self.width_mm / aspect)
        else:
            th, tw = int(self.height_mm), int(self.height_mm * aspect)
        tw, th = max(tw, 10), max(th, 10)
        img  = img.resize((tw, th), Image.LANCZOS)
        arr  = np.array(img)
        H, W = arr.shape[:2]

        _p(15, "Quantising colours …")
        pixels = arr.reshape(-1, 3).astype(np.float32)
        n = min(self.num_colors, len(np.unique(pixels, axis=0)))
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 60, 0.5)
        _, labels, centers = cv2.kmeans(pixels, n, None, crit, 6,
                                        cv2.KMEANS_PP_CENTERS)
        centers  = centers.astype(np.uint8)
        lbl2d    = labels.reshape(H, W)

        _p(30, "Building stitches …")
        order  = sorted(range(n),
                        key=lambda i: int(np.sum(lbl2d == i)), reverse=True)
        design = EmbroideryDesign()
        design.name = Path(image_path).stem
        U   = self.UNITS_PER_MM
        spx = max(1, int(self.stitch_mm))

        for ci, idx in enumerate(order):
            _p(30 + int(60*ci/n), f"Colour {ci+1}/{n} …")
            mask = ((lbl2d == idx)*255).astype(np.uint8)
            if int(np.sum(mask)) < spx*spx*4:
                continue
            c   = centers[idx]
            col = "#{:02X}{:02X}{:02X}".format(int(c[0]),int(c[1]),int(c[2]))
            th  = StitchThread(col, f"Color {ci+1}")

            for ry in range(0, H, spx):
                runs = self._runs(mask[ry])
                if not runs: continue
                if (ry//spx)%2 == 1:
                    runs = [(e,s) for s,e in runs]
                for rs, re in runs:
                    step = spx if rs<=re else -spx
                    pts  = list(range(rs, re+step, step))
                    if len(pts) < 2: continue
                    th.add_jump(pts[0]*U, ry*U)
                    for px in pts[1:]:
                        th.add_stitch(px*U, ry*U)

            # outline
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_TC89_L1)
            for cnt in cnts:
                if len(cnt) < 3: continue
                eps = max(1.0, 0.01*cv2.arcLength(cnt, True))
                app = cv2.approxPolyDP(cnt, eps, True).reshape(-1,2)
                if len(app) < 2: continue
                th.add_jump(int(app[0][0])*U, int(app[0][1])*U)
                for pt in app[1:]:
                    th.add_stitch(int(pt[0])*U, int(pt[1])*U)
                th.add_stitch(int(app[0][0])*U, int(app[0][1])*U)

            if th.stitches:
                design.threads.append(th)

        _p(100, "Done!")
        return design

    @staticmethod
    def _runs(row):
        runs, inside, s = [], False, 0
        for x, v in enumerate(row):
            if v > 0 and not inside:  inside, s = True, x
            elif v == 0 and inside:   runs.append((s, x-1)); inside = False
        if inside: runs.append((s, len(row)-1))
        return runs


# ═══════════════════════════════════════════════════════════════════════════════
#  Design splitter
# ═══════════════════════════════════════════════════════════════════════════════

class DesignSplitter:
    @staticmethod
    def _new(src, suf):
        d = EmbroideryDesign(); d.name = src.name+suf; return d

    @classmethod
    def split_horizontal(cls, design, y_split):
        top, bot = cls._new(design,"_top"), cls._new(design,"_bottom")
        for th in design.threads:
            t1,t2 = StitchThread(th.color,th.name), StitchThread(th.color,th.name)
            for x,y,st in th.stitches:
                (t1 if y<=y_split else t2).stitches.append((x,y,st))
            if t1.stitches: top.threads.append(t1)
            if t2.stitches: bot.threads.append(t2)
        return top, bot

    @classmethod
    def split_vertical(cls, design, x_split):
        lft, rgt = cls._new(design,"_left"), cls._new(design,"_right")
        for th in design.threads:
            t1,t2 = StitchThread(th.color,th.name), StitchThread(th.color,th.name)
            for x,y,st in th.stitches:
                (t1 if x<=x_split else t2).stitches.append((x,y,st))
            if t1.stitches: lft.threads.append(t1)
            if t2.stitches: rgt.threads.append(t2)
        return lft, rgt

    @classmethod
    def split_by_color(cls, design):
        parts = []
        for th in design.threads:
            d = cls._new(design, f"_{th.name}"); d.threads = [th]; parts.append(d)
        return parts


# ═══════════════════════════════════════════════════════════════════════════════
#  File I/O
# ═══════════════════════════════════════════════════════════════════════════════

class FileIO:
    @staticmethod
    def load(path):
        if not HAS_PYEMBROIDERY:
            raise RuntimeError("pyembroidery not installed.")
        pat = pyembroidery.read(path)
        if pat is None: raise ValueError(f"Cannot read: {path}")
        d = EmbroideryDesign()
        d.filepath = path; d.name = Path(path).stem
        d.from_pyembroidery(pat)
        return d

    @staticmethod
    def save(design, path):
        if not HAS_PYEMBROIDERY:
            raise RuntimeError("pyembroidery not installed.")
        pyembroidery.write(design.to_pyembroidery(), path)
        design.filepath = path


# ═══════════════════════════════════════════════════════════════════════════════
#  Embroidery canvas
# ═══════════════════════════════════════════════════════════════════════════════

class EmbroideryCanvas(tk.Canvas):
    SCALE = 0.04   # px per 0.1-mm unit at zoom=1

    def __init__(self, parent, app, **kw):
        super().__init__(parent, bg=CANVAS_BG, highlightthickness=0, **kw)
        self.app    = app
        self.zoom   = 1.0
        self.pan_x  = 50.0
        self.pan_y  = 50.0
        self._drag  = None
        self._split_pt = None
        self._split_ids = []
        self.bind("<ButtonPress-1>",   self._press)
        self.bind("<B1-Motion>",       self._move)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<MouseWheel>",      self._scroll)
        self.bind("<Button-4>",        self._scroll)
        self.bind("<Button-5>",        self._scroll)
        self.bind("<Configure>",       lambda _: self.redraw())

    def d2c(self, dx, dy):
        s = self.SCALE * self.zoom
        return dx*s + self.pan_x, dy*s + self.pan_y

    def c2d(self, cx, cy):
        s = self.SCALE * self.zoom
        return (cx-self.pan_x)/s, (cy-self.pan_y)/s

    def redraw(self, design=None, hoop=None, show_jumps=False):
        self.delete("all")
        if design is None: design = self.app.design
        self._grid()
        if hoop: self._hoop(hoop)
        if not design or not design.threads:
            self._placeholder(); return
        lw = max(0.5, self.zoom*0.45)
        for th in design.threads:
            col  = th.color
            prev = None
            for x, y, st in th.stitches:
                cx, cy = self.d2c(x, y)
                if prev:
                    if st == STITCH:
                        self.create_line(*prev, cx, cy, fill=col, width=lw,
                                         capstyle=tk.ROUND, tags="s")
                    elif show_jumps and st == JUMP:
                        self.create_line(*prev, cx, cy, fill="#D4B0B0",
                                         width=0.5, dash=(3,5), tags="s")
                prev = (cx, cy)

    def _grid(self):
        W = self.winfo_width()  or 800
        H = self.winfo_height() or 600
        sp = max(18, 100*self.zoom)
        x  = self.pan_x % sp
        while x < W:
            self.create_line(x,0,x,H, fill="#EDE0E0", width=1); x+=sp
        y  = self.pan_y % sp
        while y < H:
            self.create_line(0,y,W,y, fill="#EDE0E0", width=1); y+=sp

    def _hoop(self, size_mm):
        wm, hm = size_mm
        x1,y1 = self.d2c(0,0)
        x2,y2 = self.d2c(wm*10, hm*10)
        self.create_rectangle(x1+3,y1+3,x2+3,y2+3, fill="#D8C0C0", outline="")
        self.create_rectangle(x1,y1,x2,y2, fill="white",
                               outline=HOOP_COLOR, width=2)
        mx,my = (x1+x2)/2, (y1+y2)/2; s=12
        self.create_line(mx-s,my,mx+s,my, fill=HOOP_COLOR)
        self.create_line(mx,my-s,mx,my+s, fill=HOOP_COLOR)
        self.create_text(mx,y1-10, text=f"{wm} mm",
                         fill=HOOP_COLOR, font=("Arial",8))
        self.create_text(x2+10,my, text=f"{hm} mm",
                         fill=HOOP_COLOR, font=("Arial",8), angle=90)

    def _placeholder(self):
        W = self.winfo_width()  or 800
        H = self.winfo_height() or 600
        # Ladybug logo placeholder
        cx, cy = W//2, H//2-40
        r = 32
        self.create_oval(cx-r,cy-r,cx+r,cy+r, fill=LB_RED, outline=LB_RED_DK, width=2)
        self.create_oval(cx-r,cy-r,cx,cy+r,   fill=LB_RED_DK, outline="")
        self.create_oval(cx-5,cy-r-6,cx+5,cy-r+6, fill=LB_DARK, outline="")
        for dx,dy in [(-14,-8),(4,-14),(14,0),(-14,8),(6,12)]:
            self.create_oval(cx+dx-5,cy+dy-5,cx+dx+5,cy+dy+5,
                             fill=LB_DARK, outline="")
        self.create_text(W//2, H//2+14,
                         text="Ladybug Stitch Co.",
                         font=("Georgia",20,"bold"), fill=LB_RED)
        self.create_text(W//2, H//2+42,
                         text="Open a design  •  Digitize an image  •  Add text",
                         font=("Arial",11), fill="#B08080")

    def fit_design(self, design=None):
        if design is None: design = self.app.design
        if not design or not design.threads: return
        W = self.winfo_width()  or 800
        H = self.winfo_height() or 600
        b = design.get_bounds()
        dw,dh = b[2]-b[0], b[3]-b[1]
        if dw==0 or dh==0: return
        self.zoom = min((W*0.82)/(dw*self.SCALE),
                        (H*0.82)/(dh*self.SCALE), 24.0)
        cx0,cy0 = self.d2c((b[0]+b[2])/2,(b[1]+b[3])/2)
        self.pan_x += W/2-cx0; self.pan_y += H/2-cy0

    def _press(self, e):
        t = self.app.current_tool
        if   t == "pan":   self._drag = (e.x,e.y,self.pan_x,self.pan_y); self.config(cursor="fleur")
        elif t == "split":
            self._split_pt = (e.x,e.y)
            for i in self._split_ids: self.delete(i)
            self._split_ids.clear()

    def _move(self, e):
        t = self.app.current_tool
        if t == "pan" and self._drag:
            sx,sy,spx,spy = self._drag
            self.pan_x = spx+e.x-sx; self.pan_y = spy+e.y-sy
            self.redraw()
        elif t == "split" and self._split_pt:
            W = self.winfo_width(); H = self.winfo_height()
            sx,sy = self._split_pt
            dx,dy = abs(e.x-sx), abs(e.y-sy)
            for i in self._split_ids: self.delete(i)
            mid_y = (e.y+sy)/2; mid_x = (e.x+sx)/2
            if dx >= dy:
                lid = self.create_line(0,mid_y,W,mid_y,
                                       fill=LB_RED,width=2,dash=(10,5))
            else:
                lid = self.create_line(mid_x,0,mid_x,H,
                                       fill=LB_RED,width=2,dash=(10,5))
            self._split_ids = [lid]
            self._split_pending = (dx,dy,mid_x,mid_y)

    def _release(self, e):
        t = self.app.current_tool
        if t == "pan":
            self.config(cursor="crosshair"); self._drag = None
        elif t == "split" and self._split_pt and hasattr(self,"_split_pending"):
            dx,dy,mx,my = self._split_pending
            self.app.apply_canvas_split(dx>=dy,mx,my)
            self._split_pt = None

    def _scroll(self, e):
        f  = 1.12 if (e.num==4 or e.delta>0) else 0.88
        mx,my = e.x,e.y
        self.pan_x = mx-(mx-self.pan_x)*f
        self.pan_y = my-(my-self.pan_y)*f
        self.zoom  = max(0.05, min(40.0, self.zoom*f))
        self.redraw()


# ═══════════════════════════════════════════════════════════════════════════════
#  Dialogs
# ═══════════════════════════════════════════════════════════════════════════════

# ── shared styled button helper ───────────────────────────────────────────────
def _rb(parent, text, cmd, bg=LB_RED, fg="white", **kw):
    return tk.Button(parent, text=text, command=cmd,
                     bg=bg, fg=fg, activebackground=LB_RED_DK,
                     relief="flat", padx=10, pady=5,
                     font=("Arial",10,"bold"), **kw)


class FontBrowserDialog(tk.Toplevel):
    """
    Browse loaded BX fonts, preview them, type text, set size, and insert
    the text as stitches into the current design.
    """

    def __init__(self, parent, library: FontLibrary, settings: AppSettings,
                 on_insert):
        super().__init__(parent)
        self.library    = library
        self.settings   = settings
        self.on_insert  = on_insert   # callback(EmbroideryDesign)
        self.title("Font Library — Ladybug Stitch Co.")
        self.geometry("860x580")
        self.resizable(True, True)
        self.grab_set()

        self._sel_font  = tk.StringVar()
        self._text_var  = tk.StringVar(value="Ladybug Stitch Co.")
        self._size_var  = tk.DoubleVar(value=settings.get("text_size_mm", 25.4))
        self._spacing_v = tk.DoubleVar(value=settings.get("text_spacing",  1.2))
        self._preview_img = None

        self._build()
        self._populate_fonts()
        self._center()

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self):
        # ── title bar ─────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=LB_RED, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🐞  Font Library",
                 font=("Georgia",15,"bold"),
                 bg=LB_RED, fg="white").pack(side="left", padx=16)

        body = tk.Frame(self, bg=LB_CREAM)
        body.pack(fill="both", expand=True)

        # ── left: font list ───────────────────────────────────────────────
        lp = tk.Frame(body, bg=LB_PINK, width=230)
        lp.pack(side="left", fill="y")
        lp.pack_propagate(False)

        tk.Label(lp, text="Your Fonts", font=("Arial",11,"bold"),
                 bg=LB_PINK, fg=LB_DARK).pack(pady=(10,4), padx=10, anchor="w")

        # search box
        sf = tk.Frame(lp, bg=LB_PINK); sf.pack(fill="x", padx=8, pady=2)
        self._search = tk.StringVar()
        self._search.trace_add("write", lambda *_: self._filter_fonts())
        se = tk.Entry(sf, textvariable=self._search, font=("Arial",9),
                      relief="solid", bd=1)
        se.pack(fill="x"); se.insert(0, "Search…")
        se.bind("<FocusIn>",  lambda _: se.delete(0,"end") if se.get()=="Search…" else None)
        se.bind("<FocusOut>", lambda _: se.insert(0,"Search…") if se.get()=="" else None)

        # listbox
        lf = tk.Frame(lp, bg=LB_PINK); lf.pack(fill="both", expand=True, padx=8, pady=4)
        sb = ttk.Scrollbar(lf); sb.pack(side="right", fill="y")
        self._font_lb = tk.Listbox(lf, yscrollcommand=sb.set,
                                   selectbackground=LB_RED,
                                   selectforeground="white",
                                   font=("Arial",10), relief="flat",
                                   bg=LB_CREAM, bd=0, activestyle="none")
        self._font_lb.pack(fill="both", expand=True)
        sb.config(command=self._font_lb.yview)
        self._font_lb.bind("<<ListboxSelect>>", lambda _: self._on_select())

        # reload button
        _rb(lp, "⟳  Reload Fonts", self._reload,
            bg=LB_ROSE, fg=LB_DARK).pack(fill="x", padx=8, pady=(0,8))

        # ── right: preview + text controls ───────────────────────────────
        rp = tk.Frame(body, bg=LB_CREAM)
        rp.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        # font info
        self._info_var = tk.StringVar(value="Select a font to preview")
        tk.Label(rp, textvariable=self._info_var, font=("Arial",10),
                 fg="#A06060", bg=LB_CREAM).pack(anchor="w")

        # preview canvas
        pf = tk.Frame(rp, bg="#FFFFFF", relief="solid", bd=1)
        pf.pack(fill="x", pady=6)
        self._prev_canvas = tk.Canvas(pf, height=100, bg="#FFFFFF",
                                      highlightthickness=0)
        self._prev_canvas.pack(fill="x")

        ttk.Separator(rp).pack(fill="x", pady=6)

        # text entry
        tk.Label(rp, text="Text to add:", font=("Arial",10,"bold"),
                 bg=LB_CREAM, fg=LB_DARK).pack(anchor="w")
        te = tk.Entry(rp, textvariable=self._text_var, font=("Arial",12),
                      relief="solid", bd=1)
        te.pack(fill="x", pady=4)
        te.bind("<KeyRelease>", lambda _: self._update_preview())

        # size & spacing
        cf = tk.Frame(rp, bg=LB_CREAM); cf.pack(fill="x", pady=4)
        for col,(lbl,var,lo,hi,res,unit) in enumerate([
            ("Size", self._size_var, 5, 150, 0.5, "mm"),
            ("Letter spacing", self._spacing_v, 0, 10, 0.1, "mm"),
        ]):
            fr = tk.Frame(cf, bg=LB_CREAM); fr.grid(row=0,column=col,padx=8,sticky="ew")
            cf.columnconfigure(col, weight=1)
            tk.Label(fr, text=lbl, bg=LB_CREAM, font=("Arial",9)).pack(anchor="w")
            row2 = tk.Frame(fr, bg=LB_CREAM); row2.pack(fill="x")
            tk.Scale(row2, from_=lo, to=hi, resolution=res, variable=var,
                     orient="horizontal", bg=LB_CREAM,
                     troughcolor=LB_ROSE, showvalue=False,
                     command=lambda _: self._update_preview()
                     ).pack(side="left", fill="x", expand=True)
            tk.Label(row2, textvariable=var, width=5,
                     font=("Arial",9,"bold"), bg=LB_CREAM).pack(side="left")
            tk.Label(row2, text=unit, bg=LB_CREAM, fg="#999").pack(side="left")

        # bottom buttons
        bf = tk.Frame(rp, bg=LB_CREAM); bf.pack(side="bottom", fill="x", pady=8)
        tk.Button(bf, text="Cancel", command=self.destroy,
                  relief="flat", bg=LB_GRAY, padx=12, pady=5).pack(side="right", padx=4)
        _rb(bf, "➕  Add to Design", self._insert,
            bg=LB_RED).pack(side="right", padx=4)

    # ── font list management ──────────────────────────────────────────────

    def _populate_fonts(self):
        self._all_names = self.library.names()
        self._filter_fonts()
        if self._all_names:
            self._font_lb.selection_set(0)
            self._on_select()

    def _filter_fonts(self):
        q = self._search.get().lower().strip()
        if q in ("", "search…"):
            names = self._all_names
        else:
            names = [n for n in self._all_names if q in n.lower()]
        self._font_lb.delete(0, "end")
        for n in names:
            self._font_lb.insert("end", n)

    def _reload(self):
        self._info_var.set("Scanning fonts …")
        self.update()
        self.library.scan()
        self._all_names = self.library.names()
        self._filter_fonts()
        self._info_var.set(f"{len(self._all_names)} fonts loaded.")

    def _on_select(self):
        sel = self._font_lb.curselection()
        if not sel:
            return
        name = self._font_lb.get(sel[0])
        self._sel_font.set(name)
        font = self.library.get(name)
        if font:
            chars = sorted(font.available_chars)
            sample = "".join(c for c in "ABCabc123!?" if c in font.available_chars)
            self._info_var.set(
                f"{name}  ·  {font.char_count} glyphs  "
                f"({'  '.join(sample[:8])}{'…' if len(chars)>8 else ''})"
            )
        self._update_preview()

    def _update_preview(self):
        """Draw a simple text preview using system font (actual stitch preview
        is shown on the main canvas after insertion)."""
        c = self._prev_canvas
        c.delete("all")
        W = c.winfo_width() or 580
        text = self._text_var.get() or "Preview"
        font_name = self._sel_font.get() or "—"
        # Draw styled preview label
        c.create_rectangle(0,0,W,100, fill="#FFF8F8", outline="")
        c.create_text(W//2, 38, text=text,
                      font=("Georgia",22,"bold"), fill=LB_RED, anchor="center")
        c.create_text(W//2, 72, text=f"Font: {font_name}  |  "
                                      f"{self._size_var.get():.1f} mm",
                      font=("Arial",9), fill="#999999", anchor="center")

    # ── insert ────────────────────────────────────────────────────────────

    def _insert(self):
        name = self._sel_font.get()
        if not name:
            messagebox.showwarning("No font selected",
                                   "Please select a font first.", parent=self)
            return
        text = self._text_var.get().strip()
        if not text:
            messagebox.showwarning("No text",
                                   "Please enter some text.", parent=self)
            return
        if not HAS_PYEMBROIDERY:
            messagebox.showerror("Missing library",
                "pyembroidery is required to render font stitches.\n\n"
                "pip install pyembroidery", parent=self)
            return
        font = self.library.get(name)
        if not font:
            messagebox.showerror("Font error",
                                  f"Could not load font: {name}", parent=self)
            return

        self._info_var.set("Rendering stitches …")
        self.update()
        try:
            design = font.render_text(
                text,
                size_mm         = self._size_var.get(),
                letter_spacing_mm = self._spacing_v.get(),
            )
            if not design.threads:
                messagebox.showwarning("No output",
                    "The font produced no stitches. Some glyphs may be missing "
                    "from this font for the characters you typed.", parent=self)
                self._info_var.set("Ready.")
                return
            self.settings.set("text_size_mm", self._size_var.get())
            self.settings.set("text_spacing",  self._spacing_v.get())
            self.on_insert(design)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Render error", str(e), parent=self)
            self._info_var.set("Error — see console.")

    def _center(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - self.winfo_width())  // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")


class DigitizeDialog(tk.Toplevel):
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.callback = callback
        self.title("Digitize Image — Ladybug Stitch Co.")
        self.resizable(False, False)
        self.grab_set()
        self.img_path   = tk.StringVar()
        self.n_colors   = tk.IntVar(value=6)
        self.stitch_len = tk.DoubleVar(value=2.5)
        self.out_w      = tk.IntVar(value=90)
        self.out_h      = tk.IntVar(value=90)
        self._build(); self._center()

    def _build(self):
        hdr = tk.Frame(self, bg=LB_RED, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🖼  Digitize Image",
                 font=("Georgia",14,"bold"), bg=LB_RED, fg="white").pack(padx=16)

        body = tk.Frame(self, bg=LB_CREAM, padx=16, pady=10)
        body.pack(fill="both", expand=True)

        # File row
        fr = tk.Frame(body, bg=LB_CREAM); fr.pack(fill="x", pady=4)
        tk.Label(fr, text="Image file:", width=16, anchor="w",
                 bg=LB_CREAM).pack(side="left")
        tk.Entry(fr, textvariable=self.img_path, width=34,
                 relief="solid", bd=1).pack(side="left", padx=4)
        tk.Button(fr, text="Browse…", command=self._browse,
                  relief="flat", bg=LB_ROSE, padx=8).pack(side="left")

        sf = tk.LabelFrame(body, text=" Settings ",
                           bg=LB_CREAM, fg=LB_DARK, padx=10, pady=6)
        sf.pack(fill="x", pady=8)
        for lbl, var, lo, hi, res in [
            ("Thread colours",    self.n_colors,   2,   16,  1),
            ("Stitch length (mm)", self.stitch_len, 1.0, 6.0, 0.5),
            ("Width  (mm)",       self.out_w,       20,  350, 5),
            ("Height (mm)",       self.out_h,       20,  350, 5),
        ]:
            row = tk.Frame(sf, bg=LB_CREAM); row.pack(fill="x", pady=3)
            tk.Label(row, text=lbl, width=20, anchor="w", bg=LB_CREAM).pack(side="left")
            tk.Scale(row, from_=lo, to=hi, resolution=res, variable=var,
                     orient="horizontal", length=160, bg=LB_CREAM,
                     troughcolor=LB_ROSE, showvalue=False).pack(side="left")
            tk.Label(row, textvariable=var, width=6,
                     font=("Arial",9,"bold"), bg=LB_CREAM).pack(side="left")

        bf = tk.Frame(body, bg=LB_CREAM); bf.pack(pady=6)
        tk.Button(bf, text="Cancel", command=self.destroy,
                  relief="flat", bg=LB_GRAY, padx=12, pady=5).pack(side="left", padx=8)
        _rb(bf, "✨  Digitize!", self._go, bg=LB_RED).pack(side="left")

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Images","*.png *.jpg *.jpeg *.bmp *.tiff *.gif"),
                       ("All","*.*")])
        if p: self.img_path.set(p)

    def _go(self):
        if not self.img_path.get():
            messagebox.showwarning("No image","Select an image file.",parent=self); return
        self.callback(self.img_path.get(), self.n_colors.get(),
                      self.stitch_len.get(), self.out_w.get(), self.out_h.get())
        self.destroy()

    def _center(self):
        self.update_idletasks()
        x=(self.winfo_screenwidth()-self.winfo_width())//2
        y=(self.winfo_screenheight()-self.winfo_height())//2
        self.geometry(f"+{x}+{y}")


class SplitDialog(tk.Toplevel):
    def __init__(self, parent, design, callback):
        super().__init__(parent)
        self.design = design; self.callback = callback
        self.title("Split Design — Ladybug Stitch Co.")
        self.resizable(False, False)
        self.grab_set()
        self.split_dir = tk.StringVar(value="horizontal")
        self.split_pct = tk.DoubleVar(value=50.0)
        self._build(); self._center()

    def _build(self):
        hdr = tk.Frame(self, bg=LB_RED, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="✂  Split Design",
                 font=("Georgia",14,"bold"), bg=LB_RED, fg="white").pack(padx=16)
        b = self.design.get_bounds()
        wm=(b[2]-b[0])/10; hm=(b[3]-b[1])/10
        body = tk.Frame(self, bg=LB_CREAM, padx=16, pady=10)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=f"Design: {wm:.1f} × {hm:.1f} mm  ·  "
                             f"{self.design.stitch_count:,} stitches",
                 fg="#A06060", bg=LB_CREAM).pack(anchor="w", pady=4)
        df = tk.LabelFrame(body, text=" Direction ", bg=LB_CREAM,
                           fg=LB_DARK, padx=10, pady=6)
        df.pack(fill="x", pady=6)
        for txt,val in [("Horizontal (top / bottom)","horizontal"),
                        ("Vertical   (left / right)","vertical"),
                        ("By colour  (one file per thread)","by_color")]:
            tk.Radiobutton(df, text=txt, variable=self.split_dir,
                           value=val, bg=LB_CREAM,
                           selectcolor=LB_ROSE).pack(anchor="w")
        pf = tk.LabelFrame(body, text=" Position % ",
                           bg=LB_CREAM, fg=LB_DARK, padx=10, pady=6)
        pf.pack(fill="x", pady=6)
        tk.Scale(pf, from_=10, to=90, resolution=1,
                 variable=self.split_pct, orient="horizontal",
                 length=260, bg=LB_CREAM, troughcolor=LB_ROSE,
                 showvalue=False).pack(side="left")
        tk.Label(pf, textvariable=self.split_pct, width=4,
                 font=("Arial",9,"bold"), bg=LB_CREAM).pack(side="left")
        tk.Label(pf, text="%", bg=LB_CREAM).pack(side="left")
        bf = tk.Frame(body, bg=LB_CREAM); bf.pack(pady=6)
        tk.Button(bf, text="Cancel", command=self.destroy,
                  relief="flat", bg=LB_GRAY, padx=12, pady=5).pack(side="left", padx=8)
        _rb(bf, "✂  Split!", self._go, bg=LB_RED).pack(side="left")

    def _go(self):
        self.callback(self.split_dir.get(), self.split_pct.get()/100.0)
        self.destroy()

    def _center(self):
        self.update_idletasks()
        x=(self.winfo_screenwidth()-self.winfo_width())//2
        y=(self.winfo_screenheight()-self.winfo_height())//2
        self.geometry(f"+{x}+{y}")


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, settings: AppSettings, on_save):
        super().__init__(parent)
        self.settings = settings
        self.on_save  = on_save
        self.title("Settings — Ladybug Stitch Co.")
        self.resizable(False, False)
        self.grab_set()
        self._folder = tk.StringVar(value=settings.get("font_folder",""))
        self._build(); self._center()

    def _build(self):
        hdr = tk.Frame(self, bg=LB_RED, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚙  Settings",
                 font=("Georgia",14,"bold"), bg=LB_RED, fg="white").pack(padx=16)
        body = tk.Frame(self, bg=LB_CREAM, padx=16, pady=12)
        body.pack(fill="both", expand=True)

        ff = tk.LabelFrame(body, text=" BX Font Folder ",
                           bg=LB_CREAM, fg=LB_DARK, padx=10, pady=8)
        ff.pack(fill="x", pady=6)
        tk.Label(ff,
                 text="Folder containing your .bx font files. Sub-folders are scanned too.",
                 bg=LB_CREAM, fg="#888", font=("Arial",9),
                 justify="left").pack(anchor="w")
        row = tk.Frame(ff, bg=LB_CREAM); row.pack(fill="x", pady=6)
        tk.Entry(row, textvariable=self._folder, width=42,
                 relief="solid", bd=1).pack(side="left", padx=(0,6))
        tk.Button(row, text="Browse...", command=self._browse,
                  relief="flat", bg=LB_ROSE, padx=8).pack(side="left")
        bf = tk.Frame(body, bg=LB_CREAM); bf.pack(pady=6)
        tk.Button(bf, text="Cancel", command=self.destroy,
                  relief="flat", bg=LB_GRAY, padx=12, pady=5).pack(side="left", padx=8)
        _rb(bf, "Save & Scan", self._save, bg=LB_RED).pack(side="left")

    def _browse(self):
        p = filedialog.askdirectory(title="Select BX font folder")
        if p: self._folder.set(p)

    def _save(self):
        self.settings.set("font_folder", self._folder.get())
        self.on_save()
        self.destroy()

    def _center(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - self.winfo_width())  // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")


class App:
    def __init__(self, root):
        self.root         = root
        self.root.title(f"{APP_NAME} -- {APP_SUB}")
        self.root.geometry("1280x780")
        self.root.configure(bg=LB_PINK)
        self.settings     = AppSettings()
        self.library      = FontLibrary(self.settings)
        self.design       = EmbroideryDesign()
        self.current_tool = "pan"
        self.show_jumps   = tk.BooleanVar(value=self.settings.get("show_jumps", False))
        self.hoop_var     = tk.StringVar(value=self.settings.get("hoop", "4x4  (100x100 mm)"))
        self.status_var   = tk.StringVar(value="Welcome to Ladybug Stitch Co.")
        self._build_ui()
        self._center_window()
        if self.settings.get("font_folder"):
            threading.Thread(target=self._bg_scan_fonts, daemon=True).start()

    def _bg_scan_fonts(self):
        def prog(pct, msg):
            self.root.after(0, lambda: self.status_var.set(msg))
        self.library.scan(prog)
        count = len(self.library.fonts)
        self.root.after(0, lambda: self.status_var.set(
            f"Font library ready -- {count} font(s) loaded."))

    def _build_ui(self):
        self._build_menu()
        self._build_titlebar()
        self._build_toolbar()
        main = tk.Frame(self.root, bg=LB_PINK)
        main.pack(fill="both", expand=True)
        lp = tk.Frame(main, width=190, bg=LB_PINK)
        lp.pack(side="left", fill="y"); lp.pack_propagate(False)
        tk.Label(lp, text="Threads", font=("Georgia",11,"bold"),
                 bg=LB_PINK, fg=LB_DARK).pack(pady=(10,4), padx=10, anchor="w")
        self.thread_frame = tk.Frame(lp, bg=LB_PINK)
        self.thread_frame.pack(fill="both", expand=True, padx=8)
        self.canvas = EmbroideryCanvas(main, self)
        self.canvas.pack(side="left", fill="both", expand=True)
        rp = tk.Frame(main, width=205, bg=LB_PINK)
        rp.pack(side="right", fill="y"); rp.pack_propagate(False)
        tk.Label(rp, text="Properties", font=("Georgia",11,"bold"),
                 bg=LB_PINK, fg=LB_DARK).pack(pady=(10,4), padx=10, anchor="w")
        self.stat_vars = {}
        sf = tk.Frame(rp, bg=LB_PINK); sf.pack(fill="x", padx=12)
        for lbl in ("Stitches","Colours","Width mm","Height mm"):
            row = tk.Frame(sf, bg=LB_PINK); row.pack(fill="x", pady=3)
            tk.Label(row, text=lbl+":", bg=LB_PINK, width=11,
                     anchor="w", fg=LB_DARK).pack(side="left")
            v = tk.StringVar(value="--")
            tk.Label(row, textvariable=v, bg=LB_PINK,
                     font=("Arial",10,"bold"), fg=LB_RED).pack(side="left")
            self.stat_vars[lbl] = v
        ttk.Separator(rp).pack(fill="x", pady=10, padx=8)
        tk.Label(rp, text="Quick Export", font=("Georgia",10,"bold"),
                 bg=LB_PINK, fg=LB_DARK).pack(pady=(0,4), anchor="center")
        for name, ext in [("Brother  .PES",".pes"),("Tajima   .DST",".dst"),("Janome   .JEF",".jef")]:
            tk.Button(rp, text=name, command=lambda e=ext: self._quick_export(e),
                      relief="flat", bg=LB_ROSE, fg=LB_DARK,
                      activebackground=LB_RED, activeforeground="white",
                      pady=4, font=("Arial",9)).pack(fill="x", padx=10, pady=2)
        sb = tk.Frame(self.root, bd=1, relief="sunken", bg=LB_RED_DK)
        sb.pack(fill="x", side="bottom")
        tk.Label(sb, textvariable=self.status_var, bg=LB_RED_DK, fg="white",
                 anchor="w", font=("Arial",9)).pack(side="left", padx=10, pady=3)
        if not HAS_PYEMBROIDERY:
            tk.Label(sb, text="  pyembroidery missing -- pip install pyembroidery",
                     bg="#856404", fg="white", font=("Arial",9)).pack(side="right", padx=10, pady=3)
        self.root.after(140, self._refresh)

    def _build_titlebar(self):
        hdr = tk.Frame(self.root, bg=LB_RED, pady=6); hdr.pack(fill="x")
        tk.Label(hdr, text="Ladybug Stitch Co.", font=("Georgia",16,"bold"),
                 bg=LB_RED, fg="white").pack(side="left", padx=16)
        tk.Label(hdr, text=f"EmbroideryStudio  v{VERSION}", font=("Arial",9),
                 bg=LB_RED, fg="#FFBBBB").pack(side="right", padx=16)

    def _build_toolbar(self):
        tb = tk.Frame(self.root, bg=LB_PINK, bd=0, pady=4); tb.pack(fill="x", padx=8)
        def tbtn(txt, cmd, bg=LB_CREAM, fg=LB_DARK, bold=False):
            f = ("Arial",9,"bold") if bold else ("Arial",9)
            b = tk.Button(tb, text=txt, command=cmd, bg=bg, fg=fg, relief="flat",
                          activebackground=LB_ROSE, padx=8, pady=4, font=f)
            b.pack(side="left", padx=2, pady=2); return b
        tbtn("Open",    self.open_file)
        tbtn("Save",    self.save_file)
        tbtn("Export",  self.save_as)
        tk.Frame(tb, bg=LB_ROSE, width=1).pack(side="left", fill="y", padx=6, pady=3)
        tbtn("Fonts",    self.open_font_browser, bg=LB_RED,    fg="white", bold=True)
        tbtn("Digitize", self._open_digitize,    bg=LB_RED_LT, fg="white", bold=True)
        tbtn("Split",    self._open_split,        bg=LB_RED_LT, fg="white", bold=True)
        tk.Frame(tb, bg=LB_ROSE, width=1).pack(side="left", fill="y", padx=6, pady=3)
        self._tool_btns = {}
        for name, icon in [("pan","Pan"),("split","Split Line")]:
            b = tbtn(icon, lambda n=name: self._set_tool(n)); self._tool_btns[name] = b
        tbtn("Fit",  self.fit_to_window)
        tbtn("Z+",   lambda: self._zoom(1.3))
        tbtn("Z-",   lambda: self._zoom(0.75))
        tk.Frame(tb, bg=LB_ROSE, width=1).pack(side="left", fill="y", padx=6, pady=3)
        tk.Label(tb, text="Hoop:", bg=LB_PINK, fg=LB_DARK, font=("Arial",9)).pack(side="left", padx=4)
        cb = ttk.Combobox(tb, textvariable=self.hoop_var,
                          values=list(HOOP_SIZES.keys()), width=20, state="readonly")
        cb.pack(side="left", padx=2)
        cb.bind("<<ComboboxSelected>>", lambda _: self._refresh())

    def _build_menu(self):
        m = tk.Menu(self.root); self.root.config(menu=m)
        fm = tk.Menu(m, tearoff=0); m.add_cascade(label="File", menu=fm)
        fm.add_command(label="New",      command=self.new_design)
        fm.add_command(label="Open...",  command=self.open_file)
        fm.add_command(label="Save",     command=self.save_file)
        fm.add_command(label="Save As...", command=self.save_as)
        fm.add_separator()
        fm.add_command(label="Export...", command=self.save_as)
        fm.add_separator()
        fm.add_command(label="Exit",     command=self.root.quit)
        fnm = tk.Menu(m, tearoff=0); m.add_cascade(label="Fonts", menu=fnm)
        fnm.add_command(label="Open Font Browser...", command=self.open_font_browser)
        fnm.add_command(label="Set Font Folder...",   command=self._open_settings)
        fnm.add_command(label="Reload Font Library",  command=self._reload_fonts)
        tm = tk.Menu(m, tearoff=0); m.add_cascade(label="Tools", menu=tm)
        tm.add_command(label="Digitize Image...", command=self._open_digitize)
        tm.add_command(label="Split Design...",   command=self._open_split)
        tm.add_separator()
        tm.add_checkbutton(label="Show Jump Stitches",
                           variable=self.show_jumps, command=self._refresh)
        tm.add_command(label="Fit to Window", command=self.fit_to_window)
        vm = tk.Menu(m, tearoff=0); m.add_cascade(label="View", menu=vm)
        vm.add_command(label="Zoom In",  command=lambda: self._zoom(1.25))
        vm.add_command(label="Zoom Out", command=lambda: self._zoom(0.80))
        vm.add_command(label="Fit",      command=self.fit_to_window)
        pm = tk.Menu(m, tearoff=0); m.add_cascade(label="Settings", menu=pm)
        pm.add_command(label="Preferences...", command=self._open_settings)
        hm = tk.Menu(m, tearoff=0); m.add_cascade(label="Help", menu=hm)
        hm.add_command(label="About", command=self._about)
        self.root.bind("<Control-n>", lambda _: self.new_design())
        self.root.bind("<Control-o>", lambda _: self.open_file())
        self.root.bind("<Control-s>", lambda _: self.save_file())
        self.root.bind("<f>",         lambda _: self.fit_to_window())

    def _set_tool(self, name):
        self.current_tool = name
        for n, b in self._tool_btns.items():
            b.config(relief="sunken" if n==name else "flat",
                     bg=LB_ROSE    if n==name else LB_CREAM)

    def _zoom(self, f):
        W = self.canvas.winfo_width()  or 800
        H = self.canvas.winfo_height() or 600
        self.canvas.pan_x = W/2-(W/2-self.canvas.pan_x)*f
        self.canvas.pan_y = H/2-(H/2-self.canvas.pan_y)*f
        self.canvas.zoom  = max(0.05, min(40.0, self.canvas.zoom*f))
        self._refresh()

    def open_font_browser(self):
        if not self.library.fonts and not self.settings.get("font_folder"):
            if messagebox.askyesno("No font folder",
                "No BX font folder has been set.\n\n"
                "Would you like to set your font folder now?"):
                self._open_settings()
            return
        if not self.library.fonts:
            self.status_var.set("Scanning fonts…")
            self.library.scan()
        FontBrowserDialog(self.root, self.library, self.settings,
                          self._insert_text_design)

    def _insert_text_design(self, text_design):
        """Merge text_design into the current design."""
        if not self.design.threads:
            self.design = text_design
        else:
            # Offset text below existing design
            b_existing = self.design.get_bounds()
            b_text     = text_design.get_bounds()
            offset_y   = b_existing[3] - b_text[1] + 50  # 5 mm gap
            for th in text_design.threads:
                new_th = StitchThread(th.color, th.name)
                for x, y, st in th.stitches:
                    new_th.stitches.append((x, y+offset_y, st))
                self.design.threads.append(new_th)

        self.canvas.fit_design()
        self._refresh(); self._update_stats(); self._update_thread_panel()
        self.root.title(f"{APP_NAME} — {APP_SUB}")
        self.status_var.set(
            f"Text added  ·  {self.design.stitch_count:,} stitches total ✨")

    def _reload_fonts(self):
        self.status_var.set("Rescanning font library…")
        threading.Thread(target=self._bg_scan_fonts, daemon=True).start()

    def _open_settings(self):
        SettingsDialog(self.root, self.settings, self._reload_fonts)

    # ── file ops ──────────────────────────────────────────────────────────

    def new_design(self):
        if messagebox.askyesno("New design", "Clear current design?"):
            self.design = EmbroideryDesign()
            self._refresh(); self._update_stats(); self._update_thread_panel()
            self.root.title(f"{APP_NAME} — {APP_SUB}")

    def open_file(self):
        if not HAS_PYEMBROIDERY:
            messagebox.showerror("Missing",
                "pyembroidery not installed.\npip install pyembroidery"); return
        p = filedialog.askopenfilename(title="Open embroidery file",
                                       filetypes=READ_FORMATS)
        if not p: return
        try:
            self.status_var.set("Loading …")
            self.design = FileIO.load(p)
            self.root.after(40, self._post_load)
        except Exception as e:
            messagebox.showerror("Open error", str(e))

    def _post_load(self):
        self.canvas.fit_design()
        self._refresh(); self._update_stats(); self._update_thread_panel()
        self.root.title(f"{APP_NAME} — {self.design.name}")
        self.status_var.set(
            f"{self.design.name}  ·  {self.design.stitch_count:,} stitches  ·  "
            f"{self.design.color_count} colours  ·  "
            f"{self.design.width_mm:.1f}×{self.design.height_mm:.1f} mm")

    def save_file(self):
        if not self.design.filepath: self.save_as(); return
        try:
            FileIO.save(self.design, self.design.filepath)
            self.status_var.set(f"Saved: {self.design.filepath}")
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    def save_as(self):
        if not HAS_PYEMBROIDERY:
            messagebox.showerror("Missing",
                "pyembroidery not installed.\npip install pyembroidery"); return
        p = filedialog.asksaveasfilename(
            title="Save / Export",
            defaultextension=".pes",
            initialfile=(self.design.name or "design")+".pes",
            filetypes=WRITE_FORMATS)
        if p:
            try:
                FileIO.save(self.design, p)
                self.root.title(f"{APP_NAME} — {self.design.name}")
                self.status_var.set(f"Saved: {p}")
            except Exception as e:
                messagebox.showerror("Save error", str(e))

    def _quick_export(self, ext):
        if not HAS_PYEMBROIDERY:
            messagebox.showerror("Missing",
                "pyembroidery not installed.\npip install pyembroidery"); return
        p = filedialog.asksaveasfilename(
            title=f"Export {ext.upper()}",
            defaultextension=ext,
            initialfile=(self.design.name or "design")+ext)
        if p:
            try:
                FileIO.save(self.design, p)
                self.status_var.set(f"Exported: {p}")
            except Exception as e:
                messagebox.showerror("Export error", str(e))

    # ── digitizing ────────────────────────────────────────────────────────

    def _open_digitize(self):
        if not (HAS_CV2 and HAS_NUMPY):
            messagebox.showerror("Missing libraries",
                "Digitizer needs OpenCV and NumPy.\n\npip install opencv-python numpy"); return
        DigitizeDialog(self.root, self._run_digitize)

    def _run_digitize(self, path, nc, sl, wm, hm):
        pw = tk.Toplevel(self.root)
        pw.title("Digitizing…")
        pw.geometry("380x140")
        pw.resizable(False,False)
        pw.configure(bg=LB_CREAM)
        pw.grab_set()
        tk.Label(pw, text="🐞  Digitizing your image…",
                 font=("Georgia",12,"bold"), bg=LB_CREAM, fg=LB_RED
                 ).pack(pady=12)
        lbl = tk.Label(pw, text="Starting…", bg=LB_CREAM, fg=LB_DARK,
                       wraplength=340)
        lbl.pack()
        bar = ttk.Progressbar(pw, length=340, mode="determinate")
        bar.pack(pady=8)

        def cb(pct, msg):
            bar["value"]=pct; lbl.config(text=msg); pw.update()

        def run():
            try:
                d = Digitizer(nc,sl,wm,hm).digitize(path,cb)
                self.root.after(0, lambda: self._dig_done(d,pw))
            except Exception as e:
                self.root.after(0, lambda: self._dig_fail(str(e),pw))

        threading.Thread(target=run, daemon=True).start()

    def _dig_done(self, design, pw):
        pw.destroy()
        self.design = design
        self.canvas.fit_design()
        self._refresh(); self._update_stats(); self._update_thread_panel()
        self.root.title(f"{APP_NAME} — {design.name} (digitized)")
        self.status_var.set(
            f"Digitized ✨  ·  {design.stitch_count:,} stitches  ·  "
            f"{design.color_count} colours  ·  "
            f"{design.width_mm:.1f}×{design.height_mm:.1f} mm")
        messagebox.showinfo("Done!",
            f"Digitizing complete! ✨\n\n"
            f"Stitches : {design.stitch_count:,}\n"
            f"Colours  : {design.color_count}\n"
            f"Size     : {design.width_mm:.1f} × {design.height_mm:.1f} mm")

    def _dig_fail(self, err, pw):
        pw.destroy(); messagebox.showerror("Digitize error", err)

    # ── splitting ─────────────────────────────────────────────────────────

    def _open_split(self):
        if not self.design.threads:
            messagebox.showwarning("No design","Open or digitize a design first."); return
        SplitDialog(self.root, self.design, self._do_split)

    def _do_split(self, direction, pct):
        b = self.design.get_bounds()
        if direction == "by_color":
            parts = DesignSplitter.split_by_color(self.design)
        elif direction == "horizontal":
            y = b[1]+(b[3]-b[1])*pct
            parts = list(DesignSplitter.split_horizontal(self.design,y))
        else:
            x = b[0]+(b[2]-b[0])*pct
            parts = list(DesignSplitter.split_vertical(self.design,x))
        self._offer_save_parts(parts)

    def apply_canvas_split(self, is_h, cx, cy):
        if not self.design.threads: return
        dx,dy = self.canvas.c2d(cx,cy)
        if is_h:
            parts = list(DesignSplitter.split_horizontal(self.design,dy))
        else:
            parts = list(DesignSplitter.split_vertical(self.design,dx))
        self._offer_save_parts(parts)

    def _offer_save_parts(self, parts):
        parts = [p for p in parts if p.threads]
        if not parts:
            messagebox.showwarning("Empty split","No stitches in split result."); return
        msg = (f"Split into {len(parts)} part(s).\n\n" +
               "\n".join(f"  Part {i+1}: {p.name}  "
                         f"({p.stitch_count:,} stitches, {p.color_count} colours)"
                         for i,p in enumerate(parts)) +
               "\n\nSave each part now?")
        if messagebox.askyesno("Split complete 🎉", msg):
            for i, part in enumerate(parts):
                p = filedialog.asksaveasfilename(
                    title=f"Save part {i+1}/{len(parts)}: {part.name}",
                    defaultextension=".pes",
                    initialfile=part.name+".pes",
                    filetypes=WRITE_FORMATS)
                if p:
                    try:
                        FileIO.save(part,p)
                        self.status_var.set(f"Saved: {p}")
                    except Exception as e:
                        messagebox.showerror("Save error",str(e))
        self.design = parts[0]
        self.canvas.fit_design()
        self._refresh(); self._update_stats(); self._update_thread_panel()

    # ── canvas ────────────────────────────────────────────────────────────

    def _refresh(self):
        hoop = HOOP_SIZES.get(self.hoop_var.get())
        self.canvas.redraw(show_jumps=self.show_jumps.get(), hoop=hoop)

    def fit_to_window(self):
        self.canvas.fit_design(); self._refresh()

    # ── panels ────────────────────────────────────────────────────────────

    def _update_stats(self):
        d = self.design
        self.stat_vars["Stitches"].set(f"{d.stitch_count:,}")
        self.stat_vars["Colours"].set(str(d.color_count))
        self.stat_vars["Width mm"].set(f"{d.width_mm:.1f}")
        self.stat_vars["Height mm"].set(f"{d.height_mm:.1f}")

    def _change_thread_color(self, thread):
        """Open color picker and apply new color to the thread."""
        from tkinter import colorchooser
        result = colorchooser.askcolor(
            color=thread.color,
            title=f"Pick color for {thread.name}",
            parent=self.root
        )
        if result and result[1]:
            thread.color = result[1].upper()
            self._update_thread_panel()
            self._refresh()

    def _update_thread_panel(self):
        for w in self.thread_frame.winfo_children(): w.destroy()
        for i, th in enumerate(self.design.threads):
            row = tk.Frame(self.thread_frame, bg=LB_PINK)
            row.pack(fill="x", pady=2)

            # Clickable color swatch — opens color picker
            swatch = tk.Button(
                row, bg=th.color, width=2, relief="solid",
                cursor="hand2", bd=1,
                activebackground=th.color,
                command=lambda t=th: self._change_thread_color(t)
            )
            swatch.pack(side="left", padx=4, ipady=4)
            swatch.bind("<Enter>", lambda e, b=swatch: b.config(relief="raised"))
            swatch.bind("<Leave>", lambda e, b=swatch: b.config(relief="solid"))

            n_s = sum(1 for _,_,t in th.stitches if t==STITCH)
            tk.Label(row, text=f"{i+1}. {th.name}",
                     bg=LB_PINK, font=("Arial",9), anchor="w",
                     fg=LB_DARK).pack(side="left")
            tk.Label(row, text=f"({n_s:,})", bg=LB_PINK, fg="#B08080",
                     font=("Arial",8)).pack(side="right", padx=3)
    def _center_window(self):
        self.root.update_idletasks()
        sw,sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"1280x780+{(sw-1280)//2}+{(sh-780)//2}")

    def _about(self):
        messagebox.showinfo(f"About {APP_NAME}",
            f"🐞  {APP_NAME}\n{APP_SUB}  v{VERSION}\n\n"
            "Features\n"
            "  • BX font library (Embrilliance-compatible)\n"
            "  • Text tool — type with your fonts\n"
            "  • Image digitising (PNG/JPG → stitches)\n"
            "  • Design splitting (multi-hoop)\n"
            "  • Export: PES · DST · JEF · EXP · VP3 …\n"
            "  • Stitch preview with zoom & pan\n\n"
            "Powered by pyembroidery · Pillow · OpenCV · NumPy")


# ═══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    root = tk.Tk()
    root.title(f"{APP_NAME} — {APP_SUB}")

    try:
        icon = Image.new("RGBA",(48,48),(0,0,0,0))
        d    = ImageDraw.Draw(icon)
        d.ellipse([2,2,46,46],  fill="#C0392B")
        d.ellipse([2,2,24,46],  fill="#96281B")
        d.ellipse([18,0,30,12], fill="#3D1A1A")
        for dx,dy in [(-12,-6),(4,-12),(14,0),(-12,8),(5,10)]:
            d.ellipse([24+dx-4,24+dy-4,24+dx+4,24+dy+4], fill="#3D1A1A")
        root.iconphoto(True, ImageTk.PhotoImage(icon))
    except Exception:
        pass

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
