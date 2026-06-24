#!/usr/bin/env python3
"""
PalayKita – Desktop Launcher
Manages the Flask server with a full GUI. Double-click this file to launch.
"""
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
import subprocess
import threading
import queue
import socket
import sys
import os
import webbrowser
import time
import json

# ── Resolve paths ─────────────────────────────────────────────────────────────
LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SCRIPT   = os.path.join(LAUNCHER_DIR, 'app.py')
PYTHON_EXE   = sys.executable          # same Python that's running this launcher

# ── Colours (PalayKita green palette) ─────────────────────────────────────────
C = {
    'bg'          : '#F0FDF4',
    'surface'     : '#FFFFFF',
    'header_bg'   : '#15803D',
    'header_fg'   : '#FFFFFF',
    'brand'       : '#16A34A',
    'brand_dark'  : '#14532D',
    'brand_dim'   : '#DCFCE7',
    'accent'      : '#D97706',
    'danger'      : '#DC2626',
    'danger_bg'   : '#FEE2E2',
    'text'        : '#111827',
    'muted'       : '#6B7280',
    'border'      : '#D1FAE5',
    'log_bg'      : '#0F1B10',
    'log_fg'      : '#86EFAC',
    'log_info'    : '#4ADE80',
    'log_warn'    : '#FCD34D',
    'log_err'     : '#F87171',
    'btn_start_bg': '#16A34A',
    'btn_stop_bg' : '#DC2626',
    'btn_fg'      : '#FFFFFF',
    'btn_neu_bg'  : '#E5E7EB',
    'btn_neu_fg'  : '#374151',
}

# ── Restart sentinel exit code ─────────────────────────────────────────────────
EXIT_RESTART = 75


class PalayKitaLauncher:

    # ──────────────────────────────────────────────────────────────────────────
    def __init__(self, root: tk.Tk):
        self.root      = root
        self.process   = None          # Popen handle for Flask subprocess
        self.running   = False
        self.log_queue = queue.Queue()
        self._stop_evt = threading.Event()
        self._log_thread = None
        self.port_var    = tk.IntVar(value=5000)
        self.auto_start  = tk.BooleanVar(value=True)
        self.auto_restart= tk.BooleanVar(value=True)
        self.open_browser= tk.BooleanVar(value=False)

        self._build_ui()
        self._refresh_ips()
        self._start_log_pump()

        # Auto-start
        if self.auto_start.get():
            self.root.after(600, self._start_server)

        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        self.root.title('PalayKita – Server Manager')
        self.root.geometry('720x620')
        self.root.minsize(600, 500)
        self.root.configure(bg=C['bg'])
        try:
            self.root.iconbitmap(default='')   # suppress default icon error
        except Exception:
            pass

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=C['header_bg'], height=64)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)

        hdr_inner = tk.Frame(hdr, bg=C['header_bg'])
        hdr_inner.pack(fill='both', expand=True, padx=20)

        title_frame = tk.Frame(hdr_inner, bg=C['header_bg'])
        title_frame.pack(side='left', fill='y')

        tk.Label(title_frame, text='🌾  PalayKita',
                 font=('Segoe UI', 18, 'bold'),
                 bg=C['header_bg'], fg=C['header_fg']).pack(side='left', pady=14)
        tk.Label(title_frame, text='Rice Milling Server Manager',
                 font=('Segoe UI', 9), bg=C['header_bg'],
                 fg='#86EFAC').pack(side='left', padx=(10, 0), pady=14)

        # Status pill in header
        self.status_frame = tk.Frame(hdr_inner, bg=C['header_bg'])
        self.status_frame.pack(side='right', fill='y')

        self.status_dot = tk.Canvas(self.status_frame, width=12, height=12,
                                     bg=C['header_bg'], highlightthickness=0)
        self.status_dot.pack(side='left', padx=(0, 6), pady=22)
        self._draw_dot('gray')

        self.status_lbl = tk.Label(self.status_frame, text='Stopped',
                                    font=('Segoe UI', 11, 'bold'),
                                    bg=C['header_bg'], fg='#D1D5DB')
        self.status_lbl.pack(side='left', pady=22)

        # ── Body container ─────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=C['bg'])
        body.pack(fill='both', expand=True, padx=16, pady=12)

        # ── Left column ────────────────────────────────────────────────────────
        left = tk.Frame(body, bg=C['bg'])
        left.pack(side='left', fill='both', expand=False, padx=(0, 10))

        # Access URLs card
        url_card = self._card(left, 'Access URLs')
        url_card.pack(fill='x', pady=(0, 10))

        self.urls_inner = tk.Frame(url_card, bg=C['surface'])
        self.urls_inner.pack(fill='x', padx=12, pady=(0, 10))

        # Port row
        port_row = tk.Frame(url_card, bg=C['surface'])
        port_row.pack(fill='x', padx=12, pady=(0, 10))
        tk.Label(port_row, text='Port:', font=('Segoe UI', 10),
                 bg=C['surface'], fg=C['muted']).pack(side='left')
        self.port_entry = tk.Entry(port_row, textvariable=self.port_var,
                                    width=6, font=('Segoe UI', 10),
                                    relief='solid', bd=1, fg=C['text'])
        self.port_entry.pack(side='left', padx=(6, 0))
        tk.Label(port_row, text='(change before starting)',
                 font=('Segoe UI', 8), bg=C['surface'], fg=C['muted']).pack(side='left', padx=(8, 0))

        # ── Action buttons card ────────────────────────────────────────────────
        btn_card = self._card(left, 'Server Controls')
        btn_card.pack(fill='x', pady=(0, 10))

        btn_inner = tk.Frame(btn_card, bg=C['surface'])
        btn_inner.pack(fill='x', padx=12, pady=(0, 12))

        self.btn_start = self._btn(btn_inner, '▶  Start Server',
                                    C['btn_start_bg'], C['btn_fg'],
                                    self._start_server, width=18)
        self.btn_start.pack(fill='x', pady=(0, 6))

        self.btn_stop = self._btn(btn_inner, '■  Stop Server',
                                   C['btn_stop_bg'], C['btn_fg'],
                                   self._stop_server, width=18)
        self.btn_stop.pack(fill='x', pady=(0, 6))
        self.btn_stop.configure(state='disabled')

        self.btn_restart = self._btn(btn_inner, '↺  Restart Server',
                                      C['accent'], C['btn_fg'],
                                      self._restart_server, width=18)
        self.btn_restart.pack(fill='x', pady=(0, 6))
        self.btn_restart.configure(state='disabled')

        self.btn_open = self._btn(btn_inner, '🌐  Open in Browser',
                                   C['btn_neu_bg'], C['btn_neu_fg'],
                                   self._open_browser, width=18)
        self.btn_open.pack(fill='x')

        # ── Options card ───────────────────────────────────────────────────────
        opt_card = self._card(left, 'Options')
        opt_card.pack(fill='x')

        opt_inner = tk.Frame(opt_card, bg=C['surface'])
        opt_inner.pack(fill='x', padx=12, pady=(0, 12))

        for var, text in [
            (self.auto_start,   'Auto-start server on open'),
            (self.auto_restart, 'Auto-restart on crash'),
            (self.open_browser, 'Open browser when started'),
        ]:
            cb = tk.Checkbutton(opt_inner, text=text, variable=var,
                                 bg=C['surface'], fg=C['text'],
                                 activebackground=C['surface'],
                                 selectcolor=C['brand_dim'],
                                 font=('Segoe UI', 10),
                                 relief='flat', bd=0)
            cb.pack(anchor='w', pady=2)

        # ── Right column – Log ─────────────────────────────────────────────────
        right = tk.Frame(body, bg=C['bg'])
        right.pack(side='left', fill='both', expand=True)

        log_hdr = tk.Frame(right, bg=C['bg'])
        log_hdr.pack(fill='x', pady=(0, 6))
        tk.Label(log_hdr, text='Activity Log',
                 font=('Segoe UI', 11, 'bold'),
                 bg=C['bg'], fg=C['brand_dark']).pack(side='left')
        self._btn(log_hdr, 'Clear', C['btn_neu_bg'], C['btn_neu_fg'],
                  self._clear_log, width=6).pack(side='right')

        log_frame = tk.Frame(right, bg=C['log_bg'],
                              relief='flat', bd=0,
                              highlightbackground=C['border'],
                              highlightthickness=1)
        log_frame.pack(fill='both', expand=True)

        self.log_text = tk.Text(log_frame, bg=C['log_bg'], fg=C['log_fg'],
                                 font=('Consolas', 9),
                                 relief='flat', bd=0, wrap='word',
                                 state='disabled', padx=10, pady=8,
                                 selectbackground='#166534',
                                 insertbackground=C['log_fg'],
                                 spacing1=1)
        scrollbar = ttk.Scrollbar(log_frame, orient='vertical',
                                   command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.log_text.pack(side='left', fill='both', expand=True)

        # Configure log text tags
        self.log_text.tag_config('info',  foreground=C['log_info'])
        self.log_text.tag_config('warn',  foreground=C['log_warn'])
        self.log_text.tag_config('err',   foreground=C['log_err'])
        self.log_text.tag_config('muted', foreground='#4B5563')
        self.log_text.tag_config('ts',    foreground='#374151')
        self.log_text.tag_config('url',   foreground='#67E8F9')

        # ── Status bar ─────────────────────────────────────────────────────────
        sb = tk.Frame(self.root, bg='#E5E7EB', height=26)
        sb.pack(fill='x', side='bottom')
        sb.pack_propagate(False)
        self.sb_label = tk.Label(sb, text='PalayKita v1.0  ·  Ready',
                                  font=('Segoe UI', 9), bg='#E5E7EB',
                                  fg=C['muted'])
        self.sb_label.pack(side='left', padx=12)

        self.sb_pid = tk.Label(sb, text='',
                                font=('Segoe UI', 9), bg='#E5E7EB',
                                fg=C['muted'])
        self.sb_pid.pack(side='right', padx=12)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _card(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=C['surface'],
                          relief='flat', bd=0,
                          highlightbackground=C['border'],
                          highlightthickness=1)
        tk.Label(outer, text=title,
                 font=('Segoe UI', 10, 'bold'),
                 bg=C['brand_dim'], fg=C['brand_dark'],
                 padx=12, pady=6, anchor='w').pack(fill='x')
        return outer

    def _btn(self, parent, text, bg, fg, cmd, width=None):
        kw = dict(text=text, bg=bg, fg=fg, command=cmd,
                  font=('Segoe UI', 10, 'bold'),
                  relief='flat', bd=0, cursor='hand2',
                  activebackground=bg, activeforeground=fg,
                  padx=12, pady=7)
        if width:
            kw['width'] = width
        return tk.Button(parent, **kw)

    def _draw_dot(self, colour: str):
        colour_map = {
            'green': '#22C55E', 'red': '#EF4444',
            'yellow': '#F59E0B', 'gray': '#9CA3AF'
        }
        hex_c = colour_map.get(colour, colour)
        self.status_dot.delete('all')
        self.status_dot.create_oval(1, 1, 11, 11,
                                    fill=hex_c, outline='')

    def _set_status(self, running: bool, interim: bool = False):
        self.running = running
        if interim:
            self._draw_dot('yellow')
            self.status_lbl.configure(text='Starting…', fg='#FCD34D')
        elif running:
            self._draw_dot('green')
            self.status_lbl.configure(text='Running', fg='#86EFAC')
        else:
            self._draw_dot('gray')
            self.status_lbl.configure(text='Stopped', fg='#D1D5DB')

        # Buttons
        start_state  = 'normal'  if not running and not interim else 'disabled'
        stop_state   = 'normal'  if running else 'disabled'
        rest_state   = 'normal'  if running else 'disabled'
        open_state   = 'normal'  if running else 'disabled'
        port_state   = 'normal'  if not running and not interim else 'disabled'

        self.btn_start.configure(state=start_state)
        self.btn_stop.configure(state=stop_state)
        self.btn_restart.configure(state=rest_state)
        self.btn_open.configure(state=open_state)
        self.port_entry.configure(state=port_state)

    def _sb(self, msg: str):
        self.sb_label.configure(text=msg)

    def _refresh_ips(self):
        """Rebuild the URL list widget."""
        for w in self.urls_inner.winfo_children():
            w.destroy()

        port = self.port_var.get()
        ips  = _get_all_ips()

        for ip in ips:
            url   = f'http://{ip}:{port}'
            label = 'Local Network' if ip != '127.0.0.1' else 'This Computer'
            row   = tk.Frame(self.urls_inner, bg=C['surface'])
            row.pack(fill='x', pady=3)
            tk.Label(row, text=f'{label}:', width=14, anchor='w',
                     font=('Segoe UI', 9), bg=C['surface'],
                     fg=C['muted']).pack(side='left')
            url_lbl = tk.Label(row, text=url,
                                font=('Consolas', 10, 'bold'),
                                bg=C['surface'], fg=C['brand'],
                                cursor='hand2')
            url_lbl.pack(side='left')
            url_lbl.bind('<Button-1>', lambda e, u=url: self._open_url(u))

            cp = tk.Button(row, text='⧉', bg=C['brand_dim'], fg=C['brand_dark'],
                           relief='flat', bd=0, padx=4, pady=0,
                           font=('Segoe UI', 9), cursor='hand2',
                           command=lambda u=url: self._copy(u))
            cp.pack(side='left', padx=(6, 0))

    # ── Logging ────────────────────────────────────────────────────────────────
    def _write_log(self, text: str, tag: str = ''):
        ts = time.strftime('%H:%M:%S')
        self.log_text.configure(state='normal')
        self.log_text.insert('end', f'[{ts}] ', 'ts')
        self.log_text.insert('end', text.rstrip('\n') + '\n', tag or 'info')
        self.log_text.configure(state='disabled')
        self.log_text.see('end')

    def _clear_log(self):
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    def _start_log_pump(self):
        """Poll the queue and write to log widget every 80 ms."""
        while True:
            try:
                text, tag = self.log_queue.get_nowait()
                self._write_log(text, tag)
            except queue.Empty:
                break
        self.root.after(80, self._start_log_pump)

    def _enqueue(self, text: str, tag: str = 'info'):
        self.log_queue.put((text, tag))

    # ── Server lifecycle ───────────────────────────────────────────────────────
    def _start_server(self):
        if self.running:
            return
        port = self.port_var.get()
        if not (1024 <= port <= 65535):
            messagebox.showerror('Invalid Port', 'Port must be between 1024 and 65535.')
            return

        self._set_status(False, interim=True)
        self._sb(f'Starting server on port {port}…')
        self._enqueue(f'Starting PalayKita server on port {port}…', 'info')

        env = os.environ.copy()
        env['PALAYKITA_PORT'] = str(port)

        # On Windows: hide the console window that Flask would spawn
        kwargs = {}
        if sys.platform == 'win32':
            import subprocess as _sp
            kwargs['creationflags'] = _sp.CREATE_NO_WINDOW

        try:
            self.process = subprocess.Popen(
                [PYTHON_EXE, APP_SCRIPT],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=LAUNCHER_DIR,
                bufsize=1,
                text=True,
                **kwargs
            )
        except FileNotFoundError:
            self._set_status(False)
            self._enqueue(f'ERROR: Could not find app.py at {APP_SCRIPT}', 'err')
            messagebox.showerror('Error', f'app.py not found at:\n{APP_SCRIPT}')
            return

        self._sb(f'PID {self.process.pid} | port {port}')
        self.sb_pid.configure(text=f'PID: {self.process.pid}')

        # Read stdout in a daemon thread
        self._stop_evt.clear()
        self._log_thread = threading.Thread(
            target=self._read_output,
            args=(self.process,),
            daemon=True
        )
        self._log_thread.start()

        # Monitor process state in another thread
        threading.Thread(target=self._watch_process,
                         args=(self.process, port),
                         daemon=True).start()

    def _read_output(self, proc):
        """Stream subprocess stdout → log queue."""
        for line in proc.stdout:
            line = line.rstrip('\n')
            if not line:
                continue
            # Colour-code Flask/Werkzeug output
            if 'ERROR' in line or 'Error' in line or 'Traceback' in line:
                tag = 'err'
            elif 'WARNING' in line or 'Warning' in line:
                tag = 'warn'
            elif 'Running on' in line or 'http://' in line:
                tag = 'url'
            elif ' - - [' in line:            # access log
                tag = 'muted'
            else:
                tag = 'info'
            self.log_queue.put((line, tag))

    def _watch_process(self, proc, port):
        """Block until process exits; update UI accordingly."""
        # Give Flask ~2 s to start before marking as running
        time.sleep(1.8)
        if proc.poll() is None:
            # Still running → mark as up
            self.root.after(0, lambda: self._on_server_started(port))
        else:
            self.root.after(0, self._on_server_failed)
            return

        # Now wait for it to exit
        exit_code = proc.wait()
        self.root.after(0, lambda: self._on_server_exited(exit_code, port))

    def _on_server_started(self, port):
        self._set_status(True)
        self._sb(f'Server running  ·  port {port}  ·  PID {self.process.pid}')
        self._enqueue(f'✓ Server is up — http://localhost:{port}', 'info')
        self._refresh_ips()
        if self.open_browser.get():
            self._open_browser()

    def _on_server_failed(self):
        self._set_status(False)
        self._sb('Server failed to start — check the log.')
        self._enqueue('✗ Server failed to start. See errors above.', 'err')
        self.sb_pid.configure(text='')

    def _on_server_exited(self, exit_code: int, port: int):
        self._set_status(False)
        self.sb_pid.configure(text='')
        if exit_code == EXIT_RESTART:
            self._enqueue(f'↺ Server exited with restart signal (code {EXIT_RESTART}).', 'warn')
            self._sb('Restarting…')
            self.root.after(800, self._start_server)
        elif exit_code == 0:
            self._enqueue('■ Server stopped cleanly.', 'warn')
            self._sb('Server stopped.')
        else:
            self._enqueue(f'✗ Server exited with code {exit_code}.', 'err')
            if self.auto_restart.get():
                self._enqueue('↺ Auto-restart in 3 s…', 'warn')
                self._sb('Server crashed — auto-restarting…')
                self.root.after(3000, self._start_server)
            else:
                self._sb(f'Server stopped (exit {exit_code}).')

    def _stop_server(self):
        if not self.process or not self.running:
            return
        self._enqueue('■ Stopping server…', 'warn')
        self._set_status(False)
        try:
            self.process.terminate()
            # Give it 3 s to exit cleanly, then kill
            for _ in range(30):
                if self.process.poll() is not None:
                    break
                time.sleep(0.1)
            else:
                self.process.kill()
        except Exception as e:
            self._enqueue(f'Stop error: {e}', 'err')
        self.process = None
        self.sb_pid.configure(text='')
        self._sb('Server stopped.')

    def _restart_server(self):
        self._enqueue('↺ Restarting server…', 'warn')
        self._stop_server()
        self.root.after(800, self._start_server)

    def _open_browser(self):
        port = self.port_var.get()
        url  = f'http://localhost:{port}'
        webbrowser.open(url)
        self._enqueue(f'Opened {url} in browser', 'muted')

    def _open_url(self, url: str):
        webbrowser.open(url)

    def _copy(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._enqueue(f'Copied: {text}', 'muted')
        self._sb(f'Copied {text}')

    def _on_close(self):
        if self.running:
            if messagebox.askyesno(
                    'Quit PalayKita?',
                    'The server is running.\n\nStop server and quit?'):
                self._stop_server()
                self.root.after(400, self.root.destroy)
        else:
            self.root.destroy()


# ── IP helper (module-level, used by launcher and app.py) ─────────────────────
def _get_all_ips() -> list:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        primary = s.getsockname()[0]
        s.close()
        if primary not in ips:
            ips.append(primary)
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            if info[0] == socket.AF_INET:
                ip = info[4][0]
                if ip not in ips and not ip.startswith('127.'):
                    ips.append(ip)
    except Exception:
        pass
    if '127.0.0.1' not in ips:
        ips.append('127.0.0.1')
    return ips


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    root = tk.Tk()

    # DPI-awareness on Windows
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = PalayKitaLauncher(root)

    # Centre window on screen
    root.update_idletasks()
    w, h   = 720, 620
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')

    root.mainloop()


if __name__ == '__main__':
    main()
