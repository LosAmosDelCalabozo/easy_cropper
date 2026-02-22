"""
Image Cropper Tool
------------------
- Open an image file via File > Open or Ctrl+O
- Draw a rectangle to select a crop region
- Drag handles to resize, drag inside to move, Esc to clear
- Enter or Space to save the crop
- Left/Right arrows to navigate images in the folder
- Settings button to customise output folder and filename pattern
"""

import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import os
import sys
import configparser

SUPPORTED_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.image_cropper.ini')

HANDLE_SIZE = 8
HIT_RADIUS  = 10

DEFAULT_FOLDER_MODE   = 'subfolder'   # 'subfolder' | 'same' | 'custom'
DEFAULT_SUBFOLDER     = 'cropped'
DEFAULT_CUSTOM_FOLDER = ''
DEFAULT_PATTERN       = '{base}_cr{n}'


# ------------------------------------------------------------------
#  Config helpers
# ------------------------------------------------------------------

def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    return {
        'last_file':     cfg.get('state',    'last_file',     fallback=None),
        'folder_mode':   cfg.get('settings', 'folder_mode',   fallback=DEFAULT_FOLDER_MODE),
        'subfolder':     cfg.get('settings', 'subfolder',     fallback=DEFAULT_SUBFOLDER),
        'custom_folder': cfg.get('settings', 'custom_folder', fallback=DEFAULT_CUSTOM_FOLDER),
        'pattern':       cfg.get('settings', 'pattern',       fallback=DEFAULT_PATTERN),
        'overwrite':     cfg.get('settings', 'overwrite',     fallback='false'),
    }


def save_config(data):
    cfg = configparser.ConfigParser()
    cfg['state']    = {'last_file':     data.get('last_file', '')}
    cfg['settings'] = {
        'folder_mode':   data.get('folder_mode',   DEFAULT_FOLDER_MODE),
        'subfolder':     data.get('subfolder',     DEFAULT_SUBFOLDER),
        'custom_folder': data.get('custom_folder', DEFAULT_CUSTOM_FOLDER),
        'pattern':       data.get('pattern',       DEFAULT_PATTERN),
        'overwrite':     data.get('overwrite',     'false'),
    }
    with open(CONFIG_PATH, 'w') as f:
        cfg.write(f)


# ------------------------------------------------------------------
#  Main app
# ------------------------------------------------------------------

class ImageCropper:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Cropper — by Los Amos del Calabozo")
        self.root.configure(bg='#2b2b2b')

        self.image_path = None
        self.folder_images = []
        self.folder_index = 0
        self.pil_image = None
        self.tk_image = None
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0

        self.sel_x0 = self.sel_y0 = self.sel_x1 = self.sel_y1 = None
        self._drag_mode = None
        self._drag_ox = 0
        self._drag_oy = 0
        self._drag_sel_snapshot = None

        self.crop_counter = {}

        self._toast_items = []
        self._toast_after = None

        self.config = load_config()

        self._build_ui()
        self._bind_keys()

        if len(sys.argv) > 1:
            self._load_image(sys.argv[1])

    # ------------------------------------------------------------------
    #  UI
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    #  Tooltip helper
    # ------------------------------------------------------------------

    def _make_tooltip(self, widget, text):
        tip_win = None

        def show(e):
            nonlocal tip_win
            if tip_win:
                return
            x = widget.winfo_rootx() + widget.winfo_width() // 2
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tip_win = tk.Toplevel(widget)
            tip_win.wm_overrideredirect(True)
            tip_win.wm_geometry(f"+{x}+{y}")
            tk.Label(tip_win, text=text, bg='#2b2b2b', fg='#00d4ff',
                     font=('Segoe UI', 8), relief='flat', bd=0,
                     padx=6, pady=3).pack()

        def hide(e):
            nonlocal tip_win
            if tip_win:
                tip_win.destroy()
                tip_win = None

        widget.bind('<Enter>', show)
        widget.bind('<Leave>', hide)

    def _build_ui(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Image...", command=self._open_file, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)
        self.root.bind('<Control-o>', lambda e: self._open_file())

        self.info_var = tk.StringVar(value="Open an image to begin (File > Open or Ctrl+O)")

        top_bar = tk.Frame(self.root, bg='#1e1e1e')
        top_bar.pack(side=tk.TOP, fill=tk.X)

        tk.Label(top_bar, textvariable=self.info_var, bg='#1e1e1e', fg='#cccccc',
                 anchor='w', padx=8, pady=4, font=('Segoe UI', 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)

        btn_style = dict(bg='#3a3a3a', fg='#cccccc', activebackground='#00d4ff',
                         activeforeground='#000000', relief='flat', bd=0,
                         font=('Segoe UI', 9, 'bold'), cursor='hand2', padx=8, pady=2)

        # Right-side utility buttons
        help_btn = tk.Button(top_bar, text=' ? ', command=self._show_help, **btn_style)
        help_btn.pack(side=tk.RIGHT, padx=(0, 6), pady=3)
        self._make_tooltip(help_btn, 'Help')

        settings_btn = tk.Button(top_bar, text=' ⚙ ', command=self._show_settings, **btn_style)
        settings_btn.pack(side=tk.RIGHT, padx=(0, 2), pady=3)
        self._make_tooltip(settings_btn, 'Settings')

        # Divider
        tk.Frame(top_bar, bg='#333333', width=1).pack(side=tk.RIGHT, fill=tk.Y, pady=4, padx=4)

        # Navigation & action buttons
        nav_style = dict(bg='#2a2a2a', fg='#cccccc', activebackground='#00d4ff',
                         activeforeground='#000000', relief='flat', bd=0,
                         font=('Segoe UI', 11), cursor='hand2', padx=10, pady=2)

        next_btn = tk.Button(top_bar, text='▶', command=self._next_image, **nav_style)
        next_btn.pack(side=tk.RIGHT, padx=(0, 1), pady=3)
        self._make_tooltip(next_btn, 'Next image  [Right arrow]')

        prev_btn = tk.Button(top_bar, text='◀', command=self._prev_image, **nav_style)
        prev_btn.pack(side=tk.RIGHT, padx=(0, 1), pady=3)
        self._make_tooltip(prev_btn, 'Previous image  [Left arrow]')

        # Divider
        tk.Frame(top_bar, bg='#333333', width=1).pack(side=tk.RIGHT, fill=tk.Y, pady=4, padx=4)

        save_btn = tk.Button(top_bar, text='💾  Save crop',
                             command=self._save_crop,
                             bg='#00d4ff', fg='#000000',
                             activebackground='#00b8de', activeforeground='#000000',
                             relief='flat', bd=0, font=('Segoe UI', 9, 'bold'),
                             cursor='hand2', padx=10, pady=2)
        save_btn.pack(side=tk.RIGHT, padx=(0, 2), pady=3)
        self._make_tooltip(save_btn, 'Save crop  [Enter] or [Space]')

        self.canvas = tk.Canvas(self.root, bg='#3c3c3c', cursor='crosshair', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.status_var, bg='#1e1e1e', fg='#888888',
                 anchor='w', padx=8, pady=3, font=('Segoe UI', 8)).pack(side=tk.BOTTOM, fill=tk.X)

        self.canvas.bind('<ButtonPress-1>',   self._on_mouse_down)
        self.canvas.bind('<B1-Motion>',       self._on_mouse_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_mouse_up)
        self.canvas.bind('<Motion>',          self._on_mouse_move)
        self.canvas.bind('<Configure>',       self._on_canvas_resize)

    def _bind_keys(self):
        self.root.bind('<Return>', self._save_crop)
        self.root.bind('<space>',  self._save_crop)
        self.root.bind('<Right>',  self._next_image)
        self.root.bind('<Left>',   self._prev_image)
        self.root.bind('<Escape>', self._clear_selection)

    # ------------------------------------------------------------------
    #  Settings dialog
    # ------------------------------------------------------------------

    def _show_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.configure(bg='#1e1e1e')
        win.resizable(True, True)
        win.grab_set()

        self.root.update_idletasks()
        rx, ry = self.root.winfo_x(), self.root.winfo_y()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        ww, wh = 500, 420
        win.geometry(f"{ww}x{wh}+{rx + (rw - ww)//2}+{ry + (rh - wh)//2}")
        win.minsize(340, 300)

        # Title (fixed, outside scroll area)
        tk.Label(win, text="Settings", bg='#1e1e1e', fg='#00d4ff',
                 font=('Segoe UI', 13, 'bold'), pady=14).pack()

        # --- Scrollable content area ---
        container = tk.Frame(win, bg='#1e1e1e')
        container.pack(fill=tk.BOTH, expand=True)

        scroll_canvas = tk.Canvas(container, bg='#1e1e1e', highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(container, orient='vertical', command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(scroll_canvas, bg='#1e1e1e')
        inner_id = scroll_canvas.create_window((0, 0), window=inner, anchor='nw')

        def on_inner_configure(e):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox('all'))
        def on_canvas_configure(e):
            scroll_canvas.itemconfig(inner_id, width=e.width)

        inner.bind('<Configure>', on_inner_configure)
        scroll_canvas.bind('<Configure>', on_canvas_configure)

        def on_mousewheel(e):
            scroll_canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        scroll_canvas.bind_all('<MouseWheel>', on_mousewheel)
        win.bind('<Destroy>', lambda e: scroll_canvas.unbind_all('<MouseWheel>'))

        pad = dict(padx=20, pady=6)

        # --- Output folder ---
        tk.Label(inner, text="Output folder", bg='#1e1e1e', fg='#aaaaaa',
                 font=('Segoe UI', 9, 'bold'), anchor='w').pack(fill=tk.X, **pad)

        folder_mode = tk.StringVar(value=self.config['folder_mode'])

        radio_frame = tk.Frame(inner, bg='#1e1e1e')
        radio_frame.pack(fill=tk.X, padx=28, pady=(0, 4))

        radio_style = dict(bg='#1e1e1e', fg='#cccccc', selectcolor='#2b2b2b',
                           activebackground='#1e1e1e', activeforeground='#00d4ff',
                           font=('Segoe UI', 9))

        rb_subfolder = tk.Radiobutton(radio_frame, text="Subfolder next to image:", variable=folder_mode,
                       value='subfolder', **radio_style)
        rb_subfolder.grid(row=0, column=0, sticky='w')

        subfolder_var = tk.StringVar(value=self.config['subfolder'])
        subfolder_entry = tk.Entry(radio_frame, textvariable=subfolder_var, width=14,
                                   bg='#2b2b2b', fg='#cccccc', insertbackground='#cccccc',
                                   relief='flat', font=('Segoe UI', 9))
        subfolder_entry.grid(row=0, column=1, padx=(8, 0), sticky='w')

        rb_same = tk.Radiobutton(radio_frame, text="Same folder as image", variable=folder_mode,
                       value='same', **radio_style)
        rb_same.grid(row=1, column=0, sticky='w', pady=2)

        rb_custom = tk.Radiobutton(radio_frame, text="Custom folder:", variable=folder_mode,
                       value='custom', **radio_style)
        rb_custom.grid(row=2, column=0, sticky='w')

        custom_folder_var = tk.StringVar(value=self.config['custom_folder'])
        custom_frame = tk.Frame(radio_frame, bg='#1e1e1e')
        custom_frame.grid(row=2, column=1, padx=(8, 0), sticky='ew')

        custom_entry = tk.Entry(custom_frame, textvariable=custom_folder_var, width=18,
                                bg='#2b2b2b', fg='#cccccc', insertbackground='#cccccc',
                                relief='flat', font=('Segoe UI', 9))
        custom_entry.pack(side=tk.LEFT)

        def browse_folder():
            folder_mode.set('custom')
            d = filedialog.askdirectory(title="Choose output folder")
            if d:
                custom_folder_var.set(d)

        browse_btn = tk.Button(custom_frame, text='…', command=browse_folder,
                  bg='#3a3a3a', fg='#cccccc', relief='flat', bd=0,
                  font=('Segoe UI', 9), cursor='hand2', padx=4)
        browse_btn.pack(side=tk.LEFT, padx=(4, 0))

        # --- Separator ---
        sep1 = tk.Frame(inner, bg='#333333', height=1)
        sep1.pack(fill=tk.X, padx=20, pady=8)

        # --- Naming pattern ---
        lbl_pattern_title = tk.Label(inner, text="Filename pattern", bg='#1e1e1e', fg='#aaaaaa',
                 font=('Segoe UI', 9, 'bold'), anchor='w')
        lbl_pattern_title.pack(fill=tk.X, **pad)

        pattern_var = tk.StringVar(value=self.config['pattern'])
        pattern_entry = tk.Entry(inner, textvariable=pattern_var, bg='#2b2b2b', fg='#cccccc',
                 insertbackground='#cccccc', relief='flat', font=('Segoe UI', 9),
                 width=30)
        pattern_entry.pack(padx=28, anchor='w')

        lbl_placeholders = tk.Label(inner, text="Available placeholders:  {base} = original filename without extension"
                             "   {n} = crop number   {ext} = extension",
                 bg='#1e1e1e', fg='#666666', font=('Segoe UI', 8),
                 wraplength=420, justify='left')
        lbl_placeholders.pack(padx=28, anchor='w', pady=(4, 0))

        preview_var = tk.StringVar()

        def update_preview(*_):
            base = 'photo'
            ext  = '.jpg'
            pat  = pattern_var.get().strip() or DEFAULT_PATTERN
            try:
                name = pat.format(base=base, n=1, ext=ext) + ext
            except Exception:
                name = '(invalid pattern)'
            preview_var.set(f"Preview:  {name}")

        pattern_var.trace_add('write', update_preview)
        update_preview()

        lbl_preview = tk.Label(inner, textvariable=preview_var, bg='#1e1e1e', fg='#00d4ff',
                 font=('Segoe UI', 9, 'italic'))
        lbl_preview.pack(padx=28, anchor='w', pady=(2, 0))

        # Collect all widgets that should be greyed out when overwrite is on
        _output_widgets = [
            rb_subfolder, rb_same, rb_custom,
            subfolder_entry, custom_entry, browse_btn,
            pattern_entry, lbl_pattern_title, lbl_placeholders, lbl_preview,
        ]

        def _set_output_widgets_state(enabled):
            state = 'normal' if enabled else 'disabled'
            fg_normal, fg_dimmed = '#cccccc', '#444444'
            for w in _output_widgets:
                try:
                    w.configure(state=state)
                except Exception:
                    pass
                try:
                    w.configure(fg=fg_normal if enabled else fg_dimmed)
                except Exception:
                    pass

        # --- Overwrite original ---
        tk.Frame(inner, bg='#333333', height=1).pack(fill=tk.X, padx=20, pady=(12, 4))

        overwrite_var = tk.BooleanVar(value=self.config.get('overwrite', 'false') == 'true')

        danger_frame = tk.Frame(inner, bg='#2a0a0a', bd=0)
        danger_frame.pack(fill=tk.X, padx=20, pady=(4, 4))

        tk.Label(danger_frame, text="  ⚠  DANGER ZONE", bg='#2a0a0a', fg='#ff4444',
                 font=('Segoe UI', 9, 'bold'), anchor='w').pack(fill=tk.X, padx=8, pady=(6, 2))

        cb = tk.Checkbutton(danger_frame,
                            text="Overwrite original image with crop",
                            variable=overwrite_var,
                            bg='#2a0a0a', fg='#ff8888',
                            selectcolor='#1a0000',
                            activebackground='#2a0a0a', activeforeground='#ff4444',
                            font=('Segoe UI', 9),
                            cursor='hand2')
        cb.pack(anchor='w', padx=16, pady=(0, 4))

        tk.Label(danger_frame,
                 text="  This will permanently replace the source file. There is no undo.",
                 bg='#2a0a0a', fg='#884444', font=('Segoe UI', 8, 'italic'),
                 anchor='w', wraplength=420, justify='left').pack(fill=tk.X, padx=8, pady=(0, 8))

        # Apply initial greyed state if overwrite already enabled
        _set_output_widgets_state(not overwrite_var.get())

        def on_overwrite_toggled():
            if overwrite_var.get():
                answer = messagebox.askyesno(
                    "⚠ Are you sure?",
                    "WARNING: Enabling this option will permanently overwrite your original image "
                    "file with the cropped region every time you save.\n\n"
                    "This CANNOT be undone. The original file will be lost forever.\n\n"
                    "Are you absolutely sure you want to enable this?",
                    icon='warning',
                    parent=win
                )
                if not answer:
                    overwrite_var.set(False)
                    _set_output_widgets_state(True)
                else:
                    _set_output_widgets_state(False)
            else:
                _set_output_widgets_state(True)

        cb.config(command=on_overwrite_toggled)

        # --- Config path ---
        tk.Frame(inner, bg='#333333', height=1).pack(fill=tk.X, padx=20, pady=(12, 4))
        tk.Label(inner, text=f"Settings saved to: {CONFIG_PATH}",
                 bg='#1e1e1e', fg='#444444', font=('Segoe UI', 8),
                 wraplength=440, justify='left').pack(padx=20, anchor='w', pady=(0, 12))

        # --- Buttons (fixed at bottom, outside scroll) ---
        tk.Frame(win, bg='#333333', height=1).pack(fill=tk.X, padx=20)

        btn_row = tk.Frame(win, bg='#1e1e1e')
        btn_row.pack(pady=12)

        def on_save():
            pat = pattern_var.get().strip()
            if not pat:
                messagebox.showwarning("Invalid pattern", "Pattern cannot be empty.", parent=win)
                return
            try:
                pat.format(base='x', n=1, ext='.jpg')
            except Exception as e:
                messagebox.showwarning("Invalid pattern", f"Pattern error: {e}", parent=win)
                return
            self.config['folder_mode']   = folder_mode.get()
            self.config['subfolder']     = subfolder_var.get().strip() or DEFAULT_SUBFOLDER
            self.config['custom_folder'] = custom_folder_var.get().strip()
            self.config['pattern']       = pat
            self.config['overwrite']     = 'true' if overwrite_var.get() else 'false'
            save_config(self.config)
            win.destroy()

        tk.Button(btn_row, text="Save", command=on_save,
                  bg='#00d4ff', fg='#000000', activebackground='#00b8de',
                  relief='flat', bd=0, font=('Segoe UI', 9, 'bold'),
                  padx=20, pady=6, cursor='hand2').pack(side=tk.LEFT, padx=6)

        tk.Button(btn_row, text="Cancel", command=win.destroy,
                  bg='#3a3a3a', fg='#cccccc', activebackground='#555555',
                  relief='flat', bd=0, font=('Segoe UI', 9),
                  padx=20, pady=6, cursor='hand2').pack(side=tk.LEFT, padx=6)

        def on_reset():
            if messagebox.askyesno("Reset to defaults",
                                   "Reset all settings to their defaults?",
                                   parent=win):
                folder_mode.set(DEFAULT_FOLDER_MODE)
                subfolder_var.set(DEFAULT_SUBFOLDER)
                custom_folder_var.set(DEFAULT_CUSTOM_FOLDER)
                pattern_var.set(DEFAULT_PATTERN)
                overwrite_var.set(False)
                _set_output_widgets_state(True)

        tk.Button(btn_row, text="Reset defaults", command=on_reset,
                  bg='#2a2a2a', fg='#888888', activebackground='#3a3a3a',
                  activeforeground='#cccccc',
                  relief='flat', bd=0, font=('Segoe UI', 9),
                  padx=20, pady=6, cursor='hand2').pack(side=tk.LEFT, padx=6)

        win.bind('<Escape>', lambda e: win.destroy())

    # ------------------------------------------------------------------
    #  Help dialog
    # ------------------------------------------------------------------

    def _show_help(self):
        win = tk.Toplevel(self.root)
        win.title("Help")
        win.configure(bg='#1e1e1e')
        win.resizable(True, True)
        win.grab_set()

        self.root.update_idletasks()
        rx, ry = self.root.winfo_x(), self.root.winfo_y()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        ww, wh = 480, 540
        win.geometry(f"{ww}x{wh}+{rx + (rw - ww)//2}+{ry + (rh - wh)//2}")
        win.minsize(340, 320)

        tk.Label(win, text="Image Cropper — Help", bg='#1e1e1e', fg='#00d4ff',
                 font=('Segoe UI', 13, 'bold'), pady=14).pack()
        tk.Label(win, text="by Los Amos del Calabozo", bg='#1e1e1e', fg='#555555',
                 font=('Segoe UI', 9, 'italic'), pady=0).pack()

        container = tk.Frame(win, bg='#1e1e1e')
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg='#1e1e1e', highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(container, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg='#1e1e1e')
        inner_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox('all'))
        def on_canvas_configure(e):
            canvas.itemconfig(inner_id, width=e.width)

        inner.bind('<Configure>', on_inner_configure)
        canvas.bind('<Configure>', on_canvas_configure)

        def on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', on_mousewheel)
        win.bind('<Destroy>', lambda e: canvas.unbind_all('<MouseWheel>'))

        sections = [
            ("Opening images",
             "• File > Open  or  Ctrl+O  to browse for an image.\n"
             "• The last opened image is remembered and reopened automatically next launch."),

            ("Making a selection",
             "• Click and drag anywhere on the image to draw a crop rectangle.\n"
             "• Clicking outside an existing selection and dragging immediately starts a new one."),

            ("Resizing & moving the selection",
             "• Drag any of the 8 handles (corners + edge midpoints) to resize the selection.\n"
             "• Drag inside the selection to move it without changing its size.\n"
             "• Press Esc to clear the selection entirely."),

            ("Saving a crop",
             "• Press Enter or Space to save the selected region.\n"
             "• A brief confirmation toast appears in the bottom-right corner.\n"
             "• Multiple crops from the same image are numbered automatically: _cr1, _cr2, …"),

            ("Output folder (configurable via ⚙ Settings)",
             "• Subfolder next to image — saves into a named subfolder beside the source file (default: 'cropped').\n"
             "• Same folder — saves alongside the original image.\n"
             "• Custom folder — saves to any folder you choose."),

            ("Filename pattern (configurable via ⚙ Settings)",
             "• The filename pattern controls how saved crops are named.\n"
             "• Available placeholders:\n"
             "    {base}  — original filename without extension\n"
             "    {n}     — crop number (1, 2, 3, …)\n"
             "    {ext}   — file extension (e.g. .jpg)\n"
             "• Default pattern:  {base}_cr{n}\n"
             "• Example result:  photo_cr1.jpg"),

            ("Navigating images",
             "• Press the Right arrow to go to the next image in the same folder.\n"
             "• Press the Left arrow to go to the previous image."),

            ("Config file",
             f"All settings and the last opened file are stored in:\n{CONFIG_PATH}"),
        ]

        for title, body in sections:
            frm = tk.Frame(inner, bg='#1e1e1e')
            frm.pack(fill=tk.X, padx=20, pady=(0, 12))
            tk.Label(frm, text=title, bg='#1e1e1e', fg='#00d4ff',
                     font=('Segoe UI', 10, 'bold'), anchor='w').pack(anchor='w')
            tk.Label(frm, text=body, bg='#1e1e1e', fg='#aaaaaa',
                     font=('Segoe UI', 9), anchor='w', justify='left',
                     wraplength=400).pack(anchor='w', padx=10, pady=(2, 0))
            tk.Frame(inner, bg='#2d2d2d', height=1).pack(fill=tk.X, padx=20, pady=(6, 0))

        tk.Button(win, text="Close", command=win.destroy,
                  bg='#00d4ff', fg='#000000', activebackground='#00b8de',
                  relief='flat', bd=0, font=('Segoe UI', 9, 'bold'),
                  padx=20, pady=6, cursor='hand2').pack(pady=12)

        win.bind('<Escape>', lambda e: win.destroy())
        win.bind('<Return>', lambda e: win.destroy())

    # ------------------------------------------------------------------
    #  File handling
    # ------------------------------------------------------------------

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp"),
                       ("All files", "*.*")]
        )
        if path:
            self._load_image(path)

    def _load_image(self, path):
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            messagebox.showerror("Error", f"File not found:\n{path}")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_EXTS:
            messagebox.showerror("Error", f"Unsupported file type: {ext}")
            return
        try:
            self.pil_image = Image.open(path)
            self._display_pil = (self.pil_image.convert('RGBA')
                                 if self.pil_image.mode in ('P', 'RGBA')
                                 else self.pil_image)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open image:\n{e}")
            return

        self.image_path = path
        folder = os.path.dirname(path)
        all_files = sorted(os.listdir(folder))
        self.folder_images = [
            os.path.join(folder, f) for f in all_files
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
        ]
        try:
            self.folder_index = self.folder_images.index(path)
        except ValueError:
            self.folder_images.append(path)
            self.folder_index = len(self.folder_images) - 1

        self._clear_selection()
        self._render_image()
        self._update_info()

        self.config['last_file'] = path
        save_config(self.config)

    # ------------------------------------------------------------------
    #  Rendering
    # ------------------------------------------------------------------

    def _render_image(self):
        if self.pil_image is None:
            return
        cw = self.canvas.winfo_width() or 800
        ch = self.canvas.winfo_height() or 600
        img_w, img_h = self.pil_image.size

        self.scale = min(cw / img_w, ch / img_h)
        new_w = int(img_w * self.scale)
        new_h = int(img_h * self.scale)
        self.offset_x = (cw - new_w) // 2
        self.offset_y = (ch - new_h) // 2

        resized = self._display_pil.resize((new_w, new_h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(resized)
        self.canvas.delete('all')
        self.canvas.create_image(self.offset_x, self.offset_y, anchor='nw', image=self.tk_image)

        if self._has_selection():
            self._draw_selection()

    def _update_info(self):
        if self.image_path is None:
            return
        fname  = os.path.basename(self.image_path)
        w, h   = self.pil_image.size
        idx    = self.folder_index + 1
        total  = len(self.folder_images)
        count  = self.crop_counter.get(self.image_path, 0)
        self.info_var.set(f"  {fname}  [{idx}/{total}]  —  {w}x{h}px  |  Crops saved: {count}")
        self.status_var.set("Draw a rectangle, then Enter/Space to crop  |  Drag handles to resize  |  ← → navigate  |  Esc clear")

    # ------------------------------------------------------------------
    #  Selection helpers
    # ------------------------------------------------------------------

    def _has_selection(self):
        return None not in (self.sel_x0, self.sel_y0, self.sel_x1, self.sel_y1)

    def _norm_sel(self):
        return (min(self.sel_x0, self.sel_x1), min(self.sel_y0, self.sel_y1),
                max(self.sel_x0, self.sel_x1), max(self.sel_y0, self.sel_y1))

    def _handles(self):
        lx, ty, rx, by = self._norm_sel()
        mx, my = (lx + rx) / 2, (ty + by) / 2
        return {
            'nw': (lx, ty), 'n': (mx, ty), 'ne': (rx, ty),
            'w':  (lx, my),                'e':  (rx, my),
            'sw': (lx, by), 's': (mx, by), 'se': (rx, by),
        }

    def _handle_cursor(self, name):
        return {'nw': 'size_nw_se', 'se': 'size_nw_se',
                'ne': 'size_ne_sw', 'sw': 'size_ne_sw',
                'n':  'size_ns',    's':  'size_ns',
                'w':  'size_we',    'e':  'size_we'}.get(name, 'fleur')

    def _hit_handle(self, x, y):
        if not self._has_selection():
            return None
        for name, (hx, hy) in self._handles().items():
            if abs(x - hx) <= HIT_RADIUS and abs(y - hy) <= HIT_RADIUS:
                return name
        return None

    def _inside_selection(self, x, y):
        if not self._has_selection():
            return False
        lx, ty, rx, by = self._norm_sel()
        return lx <= x <= rx and ty <= y <= by

    def _clear_selection(self, event=None):
        self.sel_x0 = self.sel_y0 = self.sel_x1 = self.sel_y1 = None
        self._drag_mode = None
        self.canvas.delete('selection')
        self.canvas.configure(cursor='crosshair')

    # ------------------------------------------------------------------
    #  Drawing the selection
    # ------------------------------------------------------------------

    def _draw_selection(self):
        self.canvas.delete('selection')
        if not self._has_selection():
            return

        lx, ty, rx, by = self._norm_sel()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()

        for coords in [(0, 0, cw, ty), (0, by, cw, ch),
                       (0, ty, lx, by), (rx, ty, cw, by)]:
            self.canvas.create_rectangle(*coords, fill='#000000', outline='',
                                         stipple='gray50', tags='selection')

        self.canvas.create_rectangle(lx - 1, ty - 1, rx + 1, by + 1,
                                     outline='#000000', width=1, tags='selection')
        self.canvas.create_rectangle(lx, ty, rx, by,
                                     outline='#00d4ff', width=2, tags='selection')

        for frac in (1/3, 2/3):
            gx = lx + (rx - lx) * frac
            gy = ty + (by - ty) * frac
            self.canvas.create_line(gx, ty, gx, by, fill='#00d4ff',
                                    stipple='gray50', tags='selection')
            self.canvas.create_line(lx, gy, rx, gy, fill='#00d4ff',
                                    stipple='gray50', tags='selection')

        hs = HANDLE_SIZE
        for name, (hx, hy) in self._handles().items():
            self.canvas.create_rectangle(hx - hs, hy - hs, hx + hs, hy + hs,
                                         fill='#00d4ff', outline='#ffffff',
                                         width=1, tags='selection')

    # ------------------------------------------------------------------
    #  Mouse events
    # ------------------------------------------------------------------

    def _on_mouse_move(self, event):
        if not self._has_selection():
            self.canvas.configure(cursor='crosshair')
            return
        handle = self._hit_handle(event.x, event.y)
        if handle:
            self.canvas.configure(cursor=self._handle_cursor(handle))
        elif self._inside_selection(event.x, event.y):
            self.canvas.configure(cursor='fleur')
        else:
            self.canvas.configure(cursor='crosshair')

    def _on_mouse_down(self, event):
        if self.pil_image is None:
            return
        x, y = event.x, event.y

        handle = self._hit_handle(x, y)
        if handle:
            self._drag_mode = handle
            self._drag_ox, self._drag_oy = x, y
            lx, ty, rx, by = self._norm_sel()
            self._drag_sel_snapshot = (lx, ty, rx, by)
            return

        if self._inside_selection(x, y):
            self._drag_mode = 'move'
            self._drag_ox, self._drag_oy = x, y
            self._drag_sel_snapshot = (self.sel_x0, self.sel_y0, self.sel_x1, self.sel_y1)
            return

        self._clear_selection()
        self._drag_mode = 'new'
        self.sel_x0, self.sel_y0 = x, y
        self.sel_x1, self.sel_y1 = x, y

    def _on_mouse_drag(self, event):
        if self._drag_mode is None:
            return
        x, y = event.x, event.y

        if self._drag_mode == 'new':
            self.sel_x1, self.sel_y1 = x, y

        elif self._drag_mode == 'move':
            dx = x - self._drag_ox
            dy = y - self._drag_oy
            sx0, sy0, sx1, sy1 = self._drag_sel_snapshot
            self.sel_x0, self.sel_y0 = sx0 + dx, sy0 + dy
            self.sel_x1, self.sel_y1 = sx1 + dx, sy1 + dy

        else:
            h = self._drag_mode
            sx0, sy0, sx1, sy1 = self._drag_sel_snapshot
            dx = x - self._drag_ox
            dy = y - self._drag_oy
            if 'w' in h: sx0 += dx
            if 'e' in h: sx1 += dx
            if 'n' in h: sy0 += dy
            if 's' in h: sy1 += dy
            self.sel_x0, self.sel_y0, self.sel_x1, self.sel_y1 = sx0, sy0, sx1, sy1

        self._draw_selection()

    def _on_mouse_up(self, event):
        if self._has_selection():
            self.sel_x0, self.sel_x1 = min(self.sel_x0, self.sel_x1), max(self.sel_x0, self.sel_x1)
            self.sel_y0, self.sel_y1 = min(self.sel_y0, self.sel_y1), max(self.sel_y0, self.sel_y1)
        self._drag_mode = None
        self._drag_sel_snapshot = None

    # ------------------------------------------------------------------
    #  Coordinate conversion
    # ------------------------------------------------------------------

    def _canvas_to_image(self, cx, cy):
        return (cx - self.offset_x) / self.scale, (cy - self.offset_y) / self.scale

    # ------------------------------------------------------------------
    #  Save crop
    # ------------------------------------------------------------------

    def _resolve_out_folder(self):
        mode = self.config.get('folder_mode', DEFAULT_FOLDER_MODE)
        src_folder = os.path.dirname(self.image_path)
        if mode == 'same':
            return src_folder
        elif mode == 'custom':
            custom = self.config.get('custom_folder', '').strip()
            return custom if custom else src_folder
        else:  # subfolder
            sub = self.config.get('subfolder', DEFAULT_SUBFOLDER).strip() or DEFAULT_SUBFOLDER
            return os.path.join(src_folder, sub)

    def _save_crop(self, event=None):
        if self.pil_image is None:
            self.status_var.set("No image loaded.")
            return
        if not self._has_selection():
            self.status_var.set("Draw a rectangle first!")
            return

        lx, ty, rx, by = self._norm_sel()
        ix0, iy0 = self._canvas_to_image(lx, ty)
        ix1, iy1 = self._canvas_to_image(rx, by)

        left   = max(0, int(min(ix0, ix1)))
        top    = max(0, int(min(iy0, iy1)))
        right  = min(self.pil_image.width,  int(max(ix0, ix1)))
        bottom = min(self.pil_image.height, int(max(iy0, iy1)))

        if right <= left or bottom <= top:
            self.status_var.set("Selection too small, try again.")
            return

        crop = self.pil_image.crop((left, top, right, bottom))

        base, ext = os.path.splitext(os.path.basename(self.image_path))
        if not ext:
            ext = '.png'
        output_ext = ext if ext.lower() in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff') else '.png'

        out_folder = self._resolve_out_folder()
        try:
            os.makedirs(out_folder, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Could not create output folder:\n{out_folder}\n\n{e}")
            return

        count = self.crop_counter.get(self.image_path, 0) + 1
        self.crop_counter[self.image_path] = count

        pattern = self.config.get('pattern', DEFAULT_PATTERN)
        try:
            out_stem = pattern.format(base=base, n=count, ext=output_ext)
        except Exception:
            out_stem = f"{base}_cr{count}"

        out_name = out_stem + output_ext
        out_path = os.path.join(out_folder, out_name)

        save_img = crop
        if output_ext.lower() in ('.jpg', '.jpeg') and crop.mode in ('RGBA', 'P'):
            save_img = crop.convert('RGB')

        if self.config.get('overwrite', 'false') == 'true':
            # Save only over original, then reload it into the viewer
            save_img.save(self.image_path)
            fname = os.path.basename(self.image_path)
            self.status_var.set(f"Overwritten: {self.image_path}  ({right-left}x{bottom-top}px)")
            self._show_toast(f"Overwritten  {fname}")
            # Reload the now-modified image into the viewer
            self.pil_image = Image.open(self.image_path)
            self._display_pil = (self.pil_image.convert('RGBA')
                                 if self.pil_image.mode in ('P', 'RGBA')
                                 else self.pil_image)
            self._clear_selection()
            self._render_image()
        else:
            save_img.save(out_path)
            self.status_var.set(f"Saved: {out_path}  ({right-left}x{bottom-top}px)")
            self._show_toast(f"Saved  {out_name}")
        self._update_info()

    # ------------------------------------------------------------------
    #  Toast notification
    # ------------------------------------------------------------------

    def _show_toast(self, message):
        for tid in self._toast_items:
            self.canvas.delete(tid)
        self._toast_items = []
        if self._toast_after is not None:
            self.root.after_cancel(self._toast_after)
            self._toast_after = None

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        x, y = cw - 16, ch - 16

        shadow = self.canvas.create_text(x + 1, y + 1, text=message, anchor='se',
                                         font=('Segoe UI', 11, 'bold'),
                                         fill='#000000', tags='toast')
        label  = self.canvas.create_text(x, y, text=message, anchor='se',
                                         font=('Segoe UI', 11, 'bold'),
                                         fill='#00d4ff', tags='toast')
        self._toast_items = [shadow, label]

        fade_colors  = ['#00d4ff','#00b8de','#009cbd','#00809c',
                        '#00647b','#00485a','#002c39','#001018']
        shadow_fades = ['#000000','#222222','#444444','#666666',
                        '#888888','#aaaaaa','#cccccc','#eeeeee']

        def fade(step=0):
            if step < len(fade_colors):
                self.canvas.itemconfig(label,  fill=fade_colors[step])
                self.canvas.itemconfig(shadow, fill=shadow_fades[step])
                self._toast_after = self.root.after(80, lambda: fade(step + 1))
            else:
                for tid in self._toast_items:
                    self.canvas.delete(tid)
                self._toast_items = []
                self._toast_after = None

        self._toast_after = self.root.after(1000, fade)

    # ------------------------------------------------------------------
    #  Navigation
    # ------------------------------------------------------------------

    def _next_image(self, event=None):
        if not self.folder_images:
            return
        self.folder_index = (self.folder_index + 1) % len(self.folder_images)
        self._load_image(self.folder_images[self.folder_index])

    def _prev_image(self, event=None):
        if not self.folder_images:
            return
        self.folder_index = (self.folder_index - 1) % len(self.folder_images)
        self._load_image(self.folder_images[self.folder_index])

    def _on_canvas_resize(self, event):
        self._render_image()


def main():
    root = tk.Tk()
    root.geometry("1000x700")
    root.minsize(400, 300)
    try:
        root.iconbitmap(default='')
    except Exception:
        pass

    app = ImageCropper(root)

    if len(sys.argv) <= 1:
        last = app.config.get('last_file')
        if last and os.path.isfile(last):
            root.after(50, lambda: app._load_image(last))

    root.mainloop()


if __name__ == '__main__':
    main()
