#!/usr/bin/env python3
"""
PalayKita Desktop Application v1.0
Full-featured desktop app — Dashboard, Transactions, Unpaid, Reports, Settings.
Directly uses SQLite (no Flask needed for desktop). Settings tab starts/stops
Flask for mobile browser access on the same Wi-Fi.

Run:  python desktop.py
"""

import os, sys, socket, subprocess, threading, queue, webbrowser, time, shutil
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ── Path & mandatory dirs ─────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

for _d in ['instance',
           'exports/reports/daily',  'exports/reports/weekly',
           'exports/reports/monthly','exports/reports/custom',
           'backups']:
    os.makedirs(os.path.join(BASE_DIR, _d), exist_ok=True)

from database.engine import init_db, get_session
from database.models import User, Settings, MillingTransaction, Payment
from werkzeug.security import check_password_hash, generate_password_hash
from reports import generate_excel_report

init_db()

# ── Platform font ─────────────────────────────────────────────────────────────
_P    = sys.platform
FONT  = 'Segoe UI' if _P=='win32' else ('Helvetica Neue' if _P=='darwin' else 'DejaVu Sans')
MONO  = 'Consolas'  if _P=='win32' else ('Menlo'         if _P=='darwin' else 'DejaVu Sans Mono')

EXIT_RESTART = 75   # magic exit-code → desktop launcher auto-restarts Flask

# ── Colour palette ────────────────────────────────────────────────────────────
G = {
    # backgrounds
    'bg':          '#F0FDF4',
    'surface':     '#FFFFFF',
    'sidebar':     '#14532D',
    'sbar_sel':    '#166534',
    'sbar_hover':  '#15803D',
    'sbar_fg':     '#D1FAE5',
    'sbar_muted':  '#86EFAC',
    'header':      '#14532D',
    'header_fg':   '#FFFFFF',
    # brand
    'brand':       '#16A34A',
    'brand_dark':  '#14532D',
    'brand_dim':   '#DCFCE7',
    'brand_light': '#22C55E',
    # borders & muted
    'border':      '#D1FAE5',
    'bdr':         '#E5E7EB',
    'muted':       '#6B7280',
    'text':        '#111827',
    # status colours
    'paid_fg':     '#14532D',   'paid_bg':     '#DCFCE7',
    'unpaid_fg':   '#DC2626',   'unpaid_bg':   '#FEE2E2',
    'partial_fg':  '#92400E',   'partial_bg':  '#FEF9C3',
    # accent / danger
    'accent':      '#D97706',   'accent_bg':   '#FEF9C3',
    'danger':      '#DC2626',   'danger_bg':   '#FEE2E2',
    # log pane
    'log_bg':      '#0D1F0E',   'log_fg':      '#86EFAC',
    'log_err':     '#F87171',   'log_warn':    '#FCD34D',
    'log_url':     '#67E8F9',   'log_muted':   '#374151',
    # table
    'tbl_head':    '#F0FDF4',
    'tbl_row1':    '#FFFFFF',
    'tbl_row2':    '#F8FAFC',
    'tbl_sel':     '#DCFCE7',
}

# ── DB seed ───────────────────────────────────────────────────────────────────
def _seed():
    db = get_session()
    try:
        if not db.query(User).filter_by(username='admin').first():
            db.add(User(username='admin',
                        password_hash=generate_password_hash('admin123'),
                        role='admin', is_active=True))
        if not db.query(Settings).first():
            db.add(Settings(
                business_name='PalayKita Rice Mill',
                milling_rate_per_kg=Decimal('1.00'),
                chaff_rate_per_kg=Decimal('0.50'),
                currency_symbol='₱',
                receipt_footer='Thank you for your business! God bless.',
                server_port=5000,
            ))
        db.commit()
    finally:
        db.close()

# ── Pure helpers ──────────────────────────────────────────────────────────────
def D(v):
    return Decimal(str(v or 0))

def peso(v):
    try: return f'₱{float(D(v)):,.2f}'
    except: return '₱0.00'

def today_iso():
    return date.today().isoformat()

def fmt_date(s):
    if not s: return '—'
    try: return date.fromisoformat(str(s)[:10]).strftime('%b %d, %Y')
    except: return str(s)[:10]

def fmt_time(s):
    if not s: return ''
    try: return datetime.fromisoformat(str(s)).strftime('%I:%M %p')
    except: return ''

def fmt_kb(b):
    return f'{b/1024:.1f} KB' if b < 1_048_576 else f'{b/1_048_576:.1f} MB'

def compute_txn(kilos, mrate, has_c, ck, cr, paid):
    Q = lambda x: x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    gross  = Q(D(kilos) * D(mrate))
    deduct = Q(D(ck) * D(cr)) if has_c else D(0)
    net    = Q(gross - deduct)
    bal    = Q(net   - D(paid))
    if   bal    <= 0: st = 'Paid'
    elif D(paid) <= 0: st = 'Unpaid'
    else:             st = 'Partial'
    return {'gross': gross, 'deduct': deduct, 'net': net,
            'balance': max(bal, D(0)), 'status': st}

def gen_num(db, txn_date):
    from sqlalchemy import func
    n = db.query(func.count(MillingTransaction.id)).filter(
            MillingTransaction.transaction_date == txn_date).scalar() or 0
    return f'TRX-{txn_date.strftime("%Y%m%d")}-{n+1:04d}'

def all_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80)); ips.append(s.getsockname()[0]); s.close()
    except: pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            if info[0] == socket.AF_INET:
                ip = info[4][0]
                if ip not in ips and not ip.startswith('127.'): ips.append(ip)
    except: pass
    if '127.0.0.1' not in ips: ips.append('127.0.0.1')
    return ips

def status_color(st):
    return {'Paid': G['paid_fg'], 'Unpaid': G['unpaid_fg'],
            'Partial': G['partial_fg']}.get(st, G['muted'])

def status_bg(st):
    return {'Paid': G['paid_bg'], 'Unpaid': G['unpaid_bg'],
            'Partial': G['partial_bg']}.get(st, G['bdr'])

# ── Reusable widget helpers ───────────────────────────────────────────────────
def lbl(parent, text, font_size=10, bold=False, color=None, bg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or G['surface'],
                    fg=color or G['text'],
                    font=(FONT, font_size, 'bold' if bold else 'normal'), **kw)

def btn(parent, text, cmd, bg=G['brand'], fg='#fff', font_size=10, pad_x=16, pad_y=7, **kw):
    b = tk.Button(parent, text=text, command=cmd,
                  bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
                  font=(FONT, font_size, 'bold'), relief='flat', cursor='hand2',
                  padx=pad_x, pady=pad_y, bd=0, **kw)
    return b

def entry(parent, textvariable=None, width=20, font_size=11, **kw):
    return tk.Entry(parent, textvariable=textvariable, width=width,
                    font=(FONT, font_size), relief='solid', bd=1,
                    highlightthickness=1, highlightcolor=G['brand'],
                    highlightbackground=G['bdr'], bg='#fff',
                    fg=G['text'], **kw)

def date_entry(parent, textvariable=None, width=12, **kw):
    return entry(parent, textvariable=textvariable, width=width,
                 font_size=11, justify='left', **kw)

def combo(parent, values, textvariable=None, width=18, font_size=11, **kw):
    c = ttk.Combobox(parent, values=values, textvariable=textvariable,
                     width=width, font=(FONT, font_size), state='readonly', **kw)
    return c

def sep(parent, bg=G['bdr']):
    return tk.Frame(parent, bg=bg, height=1)

def card(parent, title=None, bg=G['surface'], pad=12):
    """Card container with optional title header."""
    outer = tk.Frame(parent, bg=G['surface'],
                     highlightbackground=G['border'],
                     highlightthickness=1, bd=0)
    if title:
        hdr = tk.Frame(outer, bg=G['brand_dim'])
        hdr.pack(fill='x')
        lbl(hdr, title, 9, bold=True, color=G['brand_dark'],
            bg=G['brand_dim'], anchor='w').pack(side='left', padx=pad, pady=6)
    inner = tk.Frame(outer, bg=bg)
    inner.pack(fill='both', expand=True)
    return outer, inner

def scrollable(parent, bg=G['surface']):
    """Canvas + Frame that scrolls vertically."""
    canvas = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0)
    vsb    = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
    frame  = tk.Frame(canvas, bg=bg)
    frame.bind('<Configure>',
               lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    win_id = canvas.create_window((0, 0), window=frame, anchor='nw')
    canvas.configure(yscrollcommand=vsb.set)
    canvas.bind('<Configure>',
                lambda e: canvas.itemconfig(win_id, width=e.width))

    def _on_mousewheel(e):
        canvas.yview_scroll(int(-1*(e.delta/120)), 'units')
    canvas.bind_all('<MouseWheel>', _on_mousewheel)

    vsb.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    return frame

# ── ═══════════════════════════════════════════════════════════════════════════
#    LOGIN WINDOW
# ═════════════════════════════════════════════════════════════════════════════
class LoginWindow:
    def __init__(self, root, on_success):
        self.root = root
        self.on_success = on_success
        root.title('PalayKita – Login')
        root.configure(bg=G['brand'])
        root.geometry('420x500')
        root.resizable(False, False)
        try:
            root.iconbitmap(default='')
        except Exception:
            pass
        self._build()

    def _build(self):
        # Gradient-like background
        bg_frame = tk.Frame(self.root, bg=G['brand_dark'])
        bg_frame.place(relx=0, rely=0, relwidth=1, relheight=0.45)

        # Logo area
        logo_f = tk.Frame(bg_frame, bg=G['brand_dark'])
        logo_f.place(relx=0.5, rely=0.5, anchor='center')
        tk.Label(logo_f, text='🌾', font=(FONT, 40), bg=G['brand_dark'],
                 fg=G['brand_dim']).pack()
        tk.Label(logo_f, text='PalayKita', font=(FONT, 22, 'bold'),
                 bg=G['brand_dark'], fg='#fff').pack()
        tk.Label(logo_f, text='Rice Milling Profit Tracker',
                 font=(FONT, 10), bg=G['brand_dark'],
                 fg=G['sbar_muted']).pack()

        # White card
        card_frame = tk.Frame(self.root, bg='#fff',
                               highlightbackground=G['border'],
                               highlightthickness=1)
        card_frame.place(relx=0.5, rely=0.95, anchor='s',
                         relwidth=0.88, height=230)

        tk.Label(card_frame, text='Sign In to continue',
                 font=(FONT, 12, 'bold'), bg='#fff',
                 fg=G['brand_dark']).pack(pady=(20, 16))

        # Fields
        for label, attr, show in [
            ('Username', '_e_user', ''),
            ('Password', '_e_pass', '•'),
        ]:
            f = tk.Frame(card_frame, bg='#fff')
            f.pack(fill='x', padx=28, pady=4)
            tk.Label(f, text=label, font=(FONT, 9, 'bold'),
                     bg='#fff', fg=G['muted']).pack(anchor='w')
            e = entry(f, width=30, show=show)
            e.pack(fill='x', pady=(2, 0))
            setattr(self, attr, e)

        self._e_pass.bind('<Return>', lambda _: self._login())

        btn(card_frame, '  Sign In  →  ', self._login,
            font_size=11).pack(fill='x', padx=28, pady=(14, 8))

        self._err = tk.Label(card_frame, text='', font=(FONT, 10),
                              bg='#fff', fg=G['danger'])
        self._err.pack()

    def _login(self):
        un = self._e_user.get().strip()
        pw = self._e_pass.get()
        if not un or not pw:
            self._err.config(text='Enter username and password')
            return
        db = get_session()
        try:
            u = db.query(User).filter_by(username=un, is_active=True).first()
            if u and check_password_hash(u.password_hash, pw):
                db.close()
                self.on_success(u.id, u.username, u.role)
            else:
                self._err.config(text='Invalid username or password')
        except Exception as e:
            self._err.config(text=str(e))
        finally:
            try: db.close()
            except: pass


# ── ═══════════════════════════════════════════════════════════════════════════
#    TRANSACTION DIALOG  (new / edit)
# ═════════════════════════════════════════════════════════════════════════════
class TxnDialog(tk.Toplevel):
    def __init__(self, parent, app, txn_id=None):
        super().__init__(parent)
        self.app    = app
        self.txn_id = txn_id
        self.saved  = False
        self.title('Edit Transaction' if txn_id else 'New Transaction')
        self.resizable(False, True)
        self.configure(bg=G['surface'])
        self.transient(parent)
        self.grab_set()

        self.v_customer = tk.StringVar()
        self.v_contact  = tk.StringVar()
        self.v_kilos    = tk.StringVar()
        self.v_mrate    = tk.StringVar(value=str(app.settings.get('milling_rate_per_kg', 1.0)))
        self.v_chaff    = tk.BooleanVar(value=False)
        self.v_ck       = tk.StringVar()
        self.v_cr       = tk.StringVar(value=str(app.settings.get('chaff_rate_per_kg', 0.5)))
        self.v_paid     = tk.StringVar()
        self.v_method   = tk.StringVar()
        self.v_date     = tk.StringVar(value=today_iso())

        self._build()
        for v in (self.v_kilos, self.v_mrate, self.v_ck, self.v_cr, self.v_paid):
            v.trace_add('write', self._recompute)
        self.v_chaff.trace_add('write', self._toggle_chaff)
        self.v_customer.trace_add('write', self._recompute)

        if txn_id:
            self._fill()
        self._recompute()
        self.geometry('510x760')
        self._center()
        parent.wait_window(self)

    def _center(self):
        self.update_idletasks()
        pw = self.master.winfo_width()
        ph = self.master.winfo_height()
        px = self.master.winfo_rootx()
        py = self.master.winfo_rooty()
        w  = self.winfo_width()
        h  = self.winfo_height()
        self.geometry(f'+{px+(pw-w)//2}+{py+(ph-h)//2}')

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=G['header'], height=50)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        title = 'Edit Transaction' if self.txn_id else '➕  New Transaction'
        tk.Label(hdr, text=title, font=(FONT, 13, 'bold'),
                 bg=G['header'], fg='#fff').pack(side='left', padx=16)
        tk.Button(hdr, text='✕', command=self.destroy,
                  bg=G['header'], fg='#aaa', font=(FONT, 14),
                  relief='flat', bd=0, cursor='hand2',
                  padx=10, pady=5).pack(side='right', padx=8)

        # Scrollable body
        canvas = tk.Canvas(self, bg=G['surface'], highlightthickness=0)
        vsb    = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        self._body = tk.Frame(canvas, bg=G['surface'])
        self._body.bind('<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        win = canvas.create_window((0, 0), window=self._body, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.bind('<Configure>',
            lambda e: canvas.itemconfig(win, width=e.width))
        def _mw(e): canvas.yview_scroll(int(-1*(e.delta/120)), 'units')
        canvas.bind_all('<MouseWheel>', _mw)
        vsb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        b = self._body
        b.columnconfigure(0, weight=1)
        b.columnconfigure(1, weight=1)
        P = 10

        def sec(text, row):
            f = tk.Frame(b, bg=G['brand_dim'])
            f.grid(row=row, column=0, columnspan=2,
                   sticky='ew', padx=P, pady=(14, 4))
            tk.Label(f, text=text, font=(FONT, 9, 'bold'),
                     bg=G['brand_dim'], fg=G['brand_dark']).pack(
                side='left', padx=10, pady=5)
            return row + 1

        def field2(label0, w0, label1, w1, row):
            for col, (lbl_t, widget) in enumerate(
                    [(label0, w0), (label1, w1)]):
                tk.Label(b, text=lbl_t, font=(FONT, 9, 'bold'),
                         bg=G['surface'], fg=G['muted']).grid(
                    row=row, column=col, sticky='w', padx=P, pady=(6, 1))
                widget.grid(row=row+1, column=col, sticky='ew',
                            padx=P, pady=(0, 2), ipady=4)
            return row + 2

        def field1(label_t, widget, row):
            tk.Label(b, text=label_t, font=(FONT, 9, 'bold'),
                     bg=G['surface'], fg=G['muted']).grid(
                row=row, column=0, columnspan=2, sticky='w',
                padx=P, pady=(6, 1))
            widget.grid(row=row+1, column=0, columnspan=2, sticky='ew',
                        padx=P, pady=(0, 2), ipady=4)
            return row + 2

        r = 0
        # Customer
        r = sec('👤  Customer Info  (optional)', r)
        e_cust = tk.Entry(b, textvariable=self.v_customer,
                          font=(FONT, 11), relief='solid', bd=1,
                          bg='#fff', fg=G['text'])
        e_cont = tk.Entry(b, textvariable=self.v_contact,
                          font=(FONT, 11), relief='solid', bd=1,
                          bg='#fff', fg=G['text'])
        r = field2('Customer / Owner Name', e_cust,
                   'Contact Number', e_cont, r)

        # Milling
        r = sec('⚙️  Milling Details', r)
        e_kilos = tk.Entry(b, textvariable=self.v_kilos,
                           font=(FONT, 11), relief='solid', bd=1,
                           bg='#fff', fg=G['text'])
        e_mrate = tk.Entry(b, textvariable=self.v_mrate,
                           font=(FONT, 11), relief='solid', bd=1,
                           bg='#fff', fg=G['text'])
        r = field2('Kilos Milled  *', e_kilos,
                   'Milling Rate / kg (₱)', e_mrate, r)

        # Chaff
        r = sec('🌾  Rice Chaff', r)
        tk.Checkbutton(b, text='Rice chaff sold to mill (deducted from fee)',
                       variable=self.v_chaff,
                       font=(FONT, 10), bg=G['surface'],
                       fg=G['text'], selectcolor=G['brand_dim'],
                       activebackground=G['surface'],
                       relief='flat').grid(
            row=r, column=0, columnspan=2, sticky='w', padx=P, pady=4)
        r += 1

        self._chaff_f = tk.Frame(b, bg=G['surface'])
        self._chaff_f.grid(row=r, column=0, columnspan=2,
                            sticky='ew', padx=0)
        self._chaff_f.columnconfigure(0, weight=1)
        self._chaff_f.columnconfigure(1, weight=1)
        r += 1

        e_ck = tk.Entry(self._chaff_f, textvariable=self.v_ck,
                        font=(FONT, 11), relief='solid', bd=1,
                        bg='#fff', fg=G['text'])
        e_cr = tk.Entry(self._chaff_f, textvariable=self.v_cr,
                        font=(FONT, 11), relief='solid', bd=1,
                        bg='#fff', fg=G['text'])
        for col, (lbl_t, w) in enumerate(
                [('Chaff Kilos', e_ck), ('Chaff Rate / kg (₱)', e_cr)]):
            tk.Label(self._chaff_f, text=lbl_t, font=(FONT, 9, 'bold'),
                     bg=G['surface'], fg=G['muted']).grid(
                row=0, column=col, sticky='w', padx=P, pady=(4, 1))
            w.grid(row=1, column=col, sticky='ew',
                   padx=P, pady=(0, 4), ipady=4)
        self._chaff_f.grid_remove()

        # Computation preview
        r = sec('🧮  Computation', r)
        cpv = tk.Frame(b, bg=G['brand_dim'],
                       highlightbackground=G['border'],
                       highlightthickness=1)
        cpv.grid(row=r, column=0, columnspan=2,
                 sticky='ew', padx=P, pady=4)
        cpv.columnconfigure(1, weight=1)
        r += 1

        def cp_row(parent, label, row, total=False):
            size = 11 if total else 10
            wt   = 'bold' if total else 'normal'
            tk.Label(parent, text=label, font=(FONT, size, wt),
                     bg=G['brand_dim'], fg=G['brand_dark']).grid(
                row=row, column=0, sticky='w', padx=12, pady=4)
            v = tk.Label(parent, text='₱0.00', font=(FONT, size, wt),
                         bg=G['brand_dim'], fg=G['brand_dark'])
            v.grid(row=row, column=1, sticky='e', padx=12, pady=4)
            return v

        self.lbl_gross   = cp_row(cpv, 'Gross Milling Fee',   0)
        self.lbl_chaff   = cp_row(cpv, 'Chaff Deduction (–)', 1)
        tk.Frame(cpv, bg=G['border'], height=1).grid(
            row=2, column=0, columnspan=2, sticky='ew', padx=8)
        self.lbl_net     = cp_row(cpv, 'Net Amount',  3, True)
        self.lbl_balance = cp_row(cpv, 'Balance',     4)
        self.lbl_status  = cp_row(cpv, 'Status',      5)

        # Payment
        r = sec('💵  Payment', r)
        e_paid = tk.Entry(b, textvariable=self.v_paid,
                          font=(FONT, 11), relief='solid', bd=1,
                          bg='#fff', fg=G['text'])
        self._cmb_method = ttk.Combobox(
            b, textvariable=self.v_method,
            values=['', 'Cash', 'GCash', 'Maya', 'Bank Transfer', 'Other'],
            font=(FONT, 11), state='readonly')
        r = field2('Amount Paid (₱)', e_paid,
                   'Payment Method', self._cmb_method, r)

        # Notes + Date
        r = sec('📝  Additional Info', r)
        tk.Label(b, text='Notes (optional)', font=(FONT, 9, 'bold'),
                 bg=G['surface'], fg=G['muted']).grid(
            row=r, column=0, sticky='w', padx=P, pady=(6, 1))
        tk.Label(b, text='Transaction Date', font=(FONT, 9, 'bold'),
                 bg=G['surface'], fg=G['muted']).grid(
            row=r, column=1, sticky='w', padx=P, pady=(6, 1))
        r += 1

        self._e_notes = tk.Text(b, height=2, font=(FONT, 11),
                                 relief='solid', bd=1, bg='#fff',
                                 fg=G['text'])
        self._e_notes.grid(row=r, column=0, sticky='ew',
                            padx=P, pady=(0, 2))
        e_date = date_entry(b, textvariable=self.v_date)
        e_date.grid(row=r, column=1, sticky='ew',
                    padx=P, pady=(0, 2), ipady=2)
        r += 1

        # Unpaid warning
        self._warn_f = tk.Frame(b, bg='#FEF3C7',
                                 highlightbackground='#D97706',
                                 highlightthickness=1)
        self._warn_f.grid(row=r, column=0, columnspan=2,
                           sticky='ew', padx=P, pady=4)
        tk.Label(self._warn_f,
                 text='⚠️  Unpaid balance — add customer name to track who owes.',
                 font=(FONT, 9), bg='#FEF3C7', fg='#92400E',
                 wraplength=400, justify='left').pack(padx=10, pady=6, anchor='w')
        self._warn_f.grid_remove()
        r += 1

        # Buttons
        bf = tk.Frame(b, bg=G['surface'])
        bf.grid(row=r, column=0, columnspan=2, sticky='ew', padx=P, pady=12)
        bf.columnconfigure(0, weight=1); bf.columnconfigure(1, weight=2)
        tk.Button(bf, text='Cancel', command=self.destroy,
                  bg=G['bdr'], fg=G['text'],
                  font=(FONT, 11, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=12, pady=8).grid(
            row=0, column=0, sticky='ew', padx=(0, 6))
        tk.Button(bf, text='💾  Save Transaction', command=self._save,
                  bg=G['brand'], fg='#fff',
                  font=(FONT, 11, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=12, pady=8).grid(
            row=0, column=1, sticky='ew')

    def _toggle_chaff(self, *_):
        if self.v_chaff.get():
            self._chaff_f.grid()
        else:
            self._chaff_f.grid_remove()
        self._recompute()

    def _recompute(self, *_):
        try:
            r = compute_txn(
                self.v_kilos.get() or 0,
                self.v_mrate.get() or 0,
                self.v_chaff.get(),
                self.v_ck.get() or 0,
                self.v_cr.get() or 0,
                self.v_paid.get() or 0,
            )
            self.lbl_gross.config(text=peso(r['gross']))
            cd_color = G['danger'] if r['deduct'] > 0 else G['brand_dark']
            self.lbl_chaff.config(text=f'– {peso(r["deduct"])}',
                                   fg=cd_color)
            self.lbl_net.config(text=peso(r['net']))
            bal_color = G['danger'] if r['balance'] > 0 else G['brand']
            self.lbl_balance.config(text=peso(r['balance']), fg=bal_color)
            self.lbl_status.config(text=r['status'],
                                    fg=status_color(r['status']))
            show_warn = (r['balance'] > 0 and
                         not self.v_customer.get().strip())
            if show_warn: self._warn_f.grid()
            else:         self._warn_f.grid_remove()
        except Exception:
            pass

    def _fill(self):
        db = get_session()
        try:
            t = db.get(MillingTransaction, self.txn_id)
            if not t:
                return
            self.v_customer.set(t.customer_name or '')
            self.v_contact.set(t.contact_number or '')
            self.v_kilos.set(str(t.kilos_milled))
            self.v_mrate.set(str(t.milling_rate_per_kg))
            self.v_chaff.set(t.has_chaff_deduction)
            if t.has_chaff_deduction:
                self.v_ck.set(str(t.chaff_kilos))
                self.v_cr.set(str(t.chaff_rate_per_kg))
            self.v_paid.set(str(t.amount_paid))
            self.v_method.set(t.payment_method or '')
            self._e_notes.delete('1.0', 'end')
            if t.notes:
                self._e_notes.insert('1.0', t.notes)
            self.v_date.set(
                t.transaction_date.isoformat()
                if t.transaction_date else today_iso())
        finally:
            db.close()

    def _save(self):
        try:
            kilos = float(self.v_kilos.get() or 0)
        except ValueError:
            messagebox.showerror('Error', 'Enter valid kilos.', parent=self)
            return
        if kilos <= 0:
            messagebox.showerror('Error',
                                  'Kilos milled must be greater than 0.',
                                  parent=self)
            return
        try:
            mrate = float(self.v_mrate.get() or 0)
            paid  = float(self.v_paid.get()  or 0)
            has_c = self.v_chaff.get()
            ck    = float(self.v_ck.get()    or 0) if has_c else 0
            cr    = float(self.v_cr.get()    or 0) if has_c else 0
        except ValueError:
            messagebox.showerror('Error', 'Invalid numeric value.', parent=self)
            return

        txn_date_s = self.v_date.get() or today_iso()
        try:
            txn_date = date.fromisoformat(txn_date_s)
        except ValueError:
            txn_date = date.today()

        r     = compute_txn(kilos, mrate, has_c, ck, cr, paid)
        notes = self._e_notes.get('1.0', 'end').strip() or None

        db = get_session()
        try:
            if self.txn_id:
                t = db.get(MillingTransaction, self.txn_id)
                if not t:
                    messagebox.showerror('Error',
                                          'Transaction not found.',
                                          parent=self)
                    return
            else:
                t = MillingTransaction(
                    transaction_number=gen_num(db, txn_date),
                    transaction_date=txn_date,
                    created_by=self.app.username,
                )
                db.add(t)
                db.flush()

            t.customer_name       = self.v_customer.get().strip() or None
            t.contact_number      = self.v_contact.get().strip()  or None
            t.kilos_milled        = Decimal(str(kilos))
            t.milling_rate_per_kg = Decimal(str(mrate))
            t.gross_fee           = r['gross']
            t.has_chaff_deduction = has_c
            t.chaff_kilos         = Decimal(str(ck))
            t.chaff_rate_per_kg   = Decimal(str(cr))
            t.chaff_deduction     = r['deduct']
            t.net_amount          = r['net']
            t.amount_paid         = Decimal(str(paid))
            t.balance             = r['balance']
            t.payment_status      = r['status']
            t.payment_method      = self.v_method.get() or None
            t.notes               = notes
            t.updated_at          = datetime.utcnow()

            if not self.txn_id and paid > 0:
                db.add(Payment(
                    transaction_id=t.id,
                    amount=Decimal(str(paid)),
                    payment_method=t.payment_method,
                    payment_date=datetime.utcnow(),
                    notes='Initial payment',
                    created_by=self.app.username,
                ))
            db.commit()
            self.saved = True
            self.destroy()
        except Exception as e:
            db.rollback()
            messagebox.showerror('Error', str(e), parent=self)
        finally:
            db.close()


# ── ═══════════════════════════════════════════════════════════════════════════
#    PAYMENT DIALOG
# ═════════════════════════════════════════════════════════════════════════════
class PaymentDialog(tk.Toplevel):
    def __init__(self, parent, app, txn_id):
        super().__init__(parent)
        self.app    = app
        self.txn_id = txn_id
        self.saved  = False
        self.title('Record Payment')
        self.resizable(False, False)
        self.configure(bg=G['surface'])
        self.transient(parent)
        self.grab_set()
        self._build()
        self.geometry('400x380')
        self.update_idletasks()
        pw = parent.winfo_width();  ph = parent.winfo_height()
        px = parent.winfo_rootx(); py = parent.winfo_rooty()
        w  = self.winfo_width();   h  = self.winfo_height()
        self.geometry(f'+{px+(pw-w)//2}+{py+(ph-h)//2}')
        parent.wait_window(self)

    def _build(self):
        hdr = tk.Frame(self, bg=G['header'], height=50)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text='💰  Record Payment',
                 font=(FONT, 13, 'bold'), bg=G['header'],
                 fg='#fff').pack(side='left', padx=16)

        db = get_session()
        try:
            t    = db.get(MillingTransaction, self.txn_id)
            info = (f'{t.transaction_number}  ·  '
                    f'{t.customer_name or "Walk-in"}  ·  '
                    f'Balance: {peso(t.balance)}') if t else '—'
        finally:
            db.close()

        info_f = tk.Frame(self, bg=G['brand_dim'])
        info_f.pack(fill='x', padx=12, pady=(12, 4))
        tk.Label(info_f, text=info, font=(FONT, 10),
                 bg=G['brand_dim'], fg=G['brand_dark'],
                 wraplength=370).pack(padx=12, pady=8)

        body = tk.Frame(self, bg=G['surface'])
        body.pack(fill='both', expand=True, padx=16, pady=4)

        self._e_amt    = tk.Entry(body, font=(FONT, 12),
                                   relief='solid', bd=1, bg='#fff')
        self._cmb_meth = ttk.Combobox(
            body,
            values=['', 'Cash', 'GCash', 'Maya', 'Bank Transfer', 'Other'],
            font=(FONT, 11), state='readonly')
        self._e_notes  = tk.Text(body, height=3, font=(FONT, 11),
                                  relief='solid', bd=1, bg='#fff')

        for label, widget in [
            ('Payment Amount (₱)  *', self._e_amt),
            ('Payment Method',        self._cmb_meth),
            ('Notes (optional)',       self._e_notes),
        ]:
            tk.Label(body, text=label, font=(FONT, 9, 'bold'),
                     bg=G['surface'], fg=G['muted']).pack(
                anchor='w', pady=(8, 2))
            widget.pack(fill='x', ipady=3)

        bf = tk.Frame(self, bg=G['surface'])
        bf.pack(fill='x', padx=16, pady=12)
        bf.columnconfigure(0, weight=1); bf.columnconfigure(1, weight=2)
        tk.Button(bf, text='Cancel', command=self.destroy,
                  bg=G['bdr'], fg=G['text'],
                  font=(FONT, 11, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=12, pady=8).grid(
            row=0, column=0, sticky='ew', padx=(0, 6))
        tk.Button(bf, text='💾  Record Payment', command=self._save,
                  bg=G['brand'], fg='#fff',
                  font=(FONT, 11, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=12, pady=8).grid(
            row=0, column=1, sticky='ew')

    def _save(self):
        try:
            amt = Decimal(str(self._e_amt.get().strip() or 0))
        except Exception:
            messagebox.showerror('Validation',
                                  'Enter a valid amount.', parent=self)
            return
        if amt <= 0:
            messagebox.showerror('Validation',
                                  'Amount must be greater than 0.', parent=self)
            return

        db = get_session()
        try:
            t = db.get(MillingTransaction, self.txn_id)
            if not t:
                messagebox.showerror('Error',
                                      'Transaction not found.', parent=self)
                return

            db.add(Payment(
                transaction_id=self.txn_id,
                amount=amt,
                payment_method=self._cmb_meth.get() or None,
                payment_date=datetime.utcnow(),
                notes=self._e_notes.get('1.0', 'end').strip() or None,
                created_by=self.app.username,
            ))

            new_paid = D(t.amount_paid) + amt
            new_bal  = D(t.net_amount)  - new_paid
            t.amount_paid    = new_paid
            t.balance        = max(new_bal, D(0))
            t.payment_status = ('Paid' if new_bal <= 0 else 'Partial')
            t.updated_at     = datetime.utcnow()
            db.commit()
            self.saved = True
            self.destroy()
        except Exception as e:
            db.rollback()
            messagebox.showerror('Error', str(e), parent=self)
        finally:
            db.close()


# ── ═══════════════════════════════════════════════════════════════════════════
#    MAIN APP WINDOW
# ═════════════════════════════════════════════════════════════════════════════
class PalayKitaApp:

    NAV = [
        ('dashboard', '📊', 'Dashboard'),
        ('new_txn',   '➕', 'New Transaction'),
        ('records',   '📋', 'Records'),
        ('unpaid',    '💳', 'Unpaid'),
        ('reports',   '📈', 'Reports'),
        ('settings',  '⚙️', 'Settings'),
    ]

    def __init__(self, root, user_id, username, role):
        self.root      = root
        self.user_id   = user_id
        self.username  = username
        self.role      = role
        self.is_admin  = (role == 'admin')
        self.settings  = {}

        # Server management state
        self._svr_proc     = None
        self._svr_running  = False
        self._svr_port     = tk.IntVar(value=5000)
        self._auto_start   = tk.BooleanVar(value=False)
        self._auto_restart = tk.BooleanVar(value=True)
        self._log_q        = queue.Queue()

        # Records filter state
        self._rec_date_filter   = 'today'
        self._custom_date_var   = tk.StringVar(value=today_iso())
        self._status_filter_var = tk.StringVar(value='All')

        root.title('🌾  PalayKita – Rice Milling Profit Tracker')
        root.configure(bg=G['bg'])
        root.geometry('1120x700')
        root.minsize(900, 600)
        try:    root.state('zoomed')
        except Exception:
            try: root.attributes('-zoomed', True)
            except Exception: pass

        self._load_settings_data()
        self._setup_style()
        self._build_layout()
        self._pump_log()
        self._nav_click('dashboard')
        root.protocol('WM_DELETE_WINDOW', self._on_close)

    # ── ttk Style ─────────────────────────────────────────────────────────────
    def _setup_style(self):
        s = ttk.Style()
        s.theme_use('default')
        s.configure('PK.Treeview',
                     background=G['tbl_row1'], foreground=G['text'],
                     fieldbackground=G['tbl_row1'],
                     rowheight=32, font=(FONT, 10))
        s.configure('PK.Treeview.Heading',
                     background=G['brand_dim'],
                     foreground=G['brand_dark'],
                     font=(FONT, 10, 'bold'), relief='flat')
        s.map('PK.Treeview',
              background=[('selected', G['tbl_sel'])],
              foreground=[('selected', G['brand_dark'])])
        s.configure('PK.TNotebook', background=G['bg'])
        s.configure('PK.TNotebook.Tab',
                     background=G['bdr'], foreground=G['muted'],
                     padding=[14, 6], font=(FONT, 10, 'bold'))
        s.map('PK.TNotebook.Tab',
              background=[('selected', G['brand']),
                           ('active',   G['brand_dim'])],
              foreground=[('selected', '#fff')])

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build_layout(self):
        # Header
        hdr = tk.Frame(self.root, bg=G['header'], height=58)
        hdr.pack(fill='x', side='top'); hdr.pack_propagate(False)
        tk.Label(hdr, text='🌾  PalayKita',
                 font=(FONT, 18, 'bold'),
                 bg=G['header'], fg='#fff').pack(side='left', padx=18)
        tk.Label(hdr, text='Rice Milling Profit Tracker',
                 font=(FONT, 9), bg=G['header'],
                 fg=G['sbar_muted']).pack(side='left')
        rh = tk.Frame(hdr, bg=G['header'])
        rh.pack(side='right', padx=14)
        tk.Label(rh, text=f'👤  {self.username}  ({self.role})',
                 font=(FONT, 10), bg=G['header'],
                 fg='#ccc').pack(side='left', padx=8)
        tk.Button(rh, text='Sign Out', command=self._logout,
                  bg=G['header'], fg='#ccc',
                  font=(FONT, 10), relief='flat', bd=0,
                  cursor='hand2', padx=10).pack(side='left')

        # Body
        body = tk.Frame(self.root, bg=G['bg'])
        body.pack(fill='both', expand=True)

        # Sidebar
        self._sidebar = tk.Frame(body, bg=G['sidebar'], width=200)
        self._sidebar.pack(side='left', fill='y')
        self._sidebar.pack_propagate(False)

        self._biz_lbl = tk.Label(
            self._sidebar,
            text=self.settings.get('business_name', 'PalayKita'),
            font=(FONT, 9), bg=G['sidebar'],
            fg=G['sbar_muted'], wraplength=170)
        self._biz_lbl.pack(pady=(10, 4), padx=10, anchor='w')
        tk.Frame(self._sidebar, bg=G['sbar_sel'],
                 height=1).pack(fill='x', padx=10, pady=4)

        self._nav_btns = {}
        for key, icon, label in self.NAV:
            outer = tk.Frame(self._sidebar, bg=G['sidebar'], cursor='hand2')
            outer.pack(fill='x', pady=1)
            inner = tk.Frame(outer, bg=G['sidebar'])
            inner.pack(fill='x', padx=6, pady=1)
            il = tk.Label(inner, text=icon, font=(FONT, 13),
                           bg=G['sidebar'], fg=G['sbar_fg'], width=2)
            il.pack(side='left', padx=(6, 4), pady=7)
            tl = tk.Label(inner, text=label, font=(FONT, 11),
                           bg=G['sidebar'], fg=G['sbar_fg'], anchor='w')
            tl.pack(side='left', fill='x', expand=True)
            for w in (outer, inner, il, tl):
                w.bind('<Button-1>',
                       lambda e, k=key: self._nav_click(k))
                w.bind('<Enter>',
                       lambda e, fr=inner: fr.configure(bg=G['sbar_hover']))
                w.bind('<Leave>',
                       lambda e, fr=inner, k=key:
                       fr.configure(
                           bg=G['sbar_sel']
                           if self._current_nav == k
                           else G['sidebar']))
            self._nav_btns[key] = (outer, inner, il, tl)

        tk.Frame(self._sidebar, bg=G['sidebar']).pack(fill='y', expand=True)
        tk.Label(self._sidebar, text='PalayKita v1.0',
                 font=(FONT, 8), bg=G['sidebar'],
                 fg='#2d6a40').pack(pady=6)

        # Content area
        self._content = tk.Frame(body, bg=G['bg'])
        self._content.pack(side='left', fill='both', expand=True)

        self._screens     = {}
        self._current_nav = ''
        self._cur_screen  = None
        for key, _, _ in self.NAV:
            self._screens[key] = tk.Frame(self._content, bg=G['bg'])

        # Status bar
        sb = tk.Frame(self.root, bg='#E5E7EB', height=24)
        sb.pack(fill='x', side='bottom'); sb.pack_propagate(False)
        self._sb_lbl = tk.Label(sb, text='Ready',
                                 font=(FONT, 9), bg='#E5E7EB',
                                 fg=G['muted'])
        self._sb_lbl.pack(side='left', padx=12)
        self._svr_sb = tk.Label(sb, text='',
                                 font=(FONT, 9), bg='#E5E7EB',
                                 fg=G['muted'])
        self._svr_sb.pack(side='right', padx=12)

    # ── Navigation ────────────────────────────────────────────────────────────
    def _nav_click(self, key):
        if key == 'new_txn':
            self._open_txn_dialog(); return

        if self._cur_screen:
            self._cur_screen.pack_forget()

        for k, (o, inner, il, tl) in self._nav_btns.items():
            bg = G['sbar_sel'] if k == key else G['sidebar']
            for w in (inner, il, tl): w.configure(bg=bg)

        self._current_nav = key
        scr = self._screens[key]
        scr.pack(fill='both', expand=True)
        self._cur_screen = scr

        for w in scr.winfo_children(): w.destroy()
        dispatch = {
            'dashboard': self._build_dashboard,
            'records'  : self._build_records,
            'unpaid'   : self._build_unpaid,
            'reports'  : self._build_reports,
            'settings' : self._build_settings,
        }
        if key in dispatch:
            dispatch[key](scr)

    def _sb(self, msg):
        self._sb_lbl.configure(text=msg)

    def _load_settings_data(self):
        db = get_session()
        try:
            s = db.query(Settings).first()
            if s:
                self.settings = {
                    'business_name'       : s.business_name,
                    'milling_rate_per_kg' : float(s.milling_rate_per_kg),
                    'chaff_rate_per_kg'   : float(s.chaff_rate_per_kg),
                    'currency_symbol'     : s.currency_symbol,
                    'receipt_footer'      : s.receipt_footer,
                    'server_port'         : int(getattr(s, 'server_port', 5000) or 5000),
                }
                if hasattr(self, '_svr_port'):
                    self._svr_port.set(self.settings['server_port'])
        finally:
            db.close()

    # ── ══════════  DASHBOARD  ══════════ ─────────────────────────────────────
    def _build_dashboard(self, parent):
        top = tk.Frame(parent, bg=G['bg'])
        top.pack(fill='x', padx=16, pady=(14, 6))
        tk.Label(top,
                 text=f"📊  {date.today().strftime('%A, %B %d, %Y')}",
                 font=(FONT, 14, 'bold'),
                 bg=G['bg'], fg=G['brand_dark']).pack(side='left')
        tk.Button(top, text='↺ Refresh',
                  command=lambda: self._nav_click('dashboard'),
                  bg=G['bdr'], fg=G['text'],
                  font=(FONT, 9, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=10, pady=4).pack(side='right')
        tk.Button(top, text='➕ New Transaction',
                  command=self._open_txn_dialog,
                  bg=G['brand'], fg='#fff',
                  font=(FONT, 10, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=14, pady=6).pack(side='right', padx=(0, 8))

        self._dash_met_f = tk.Frame(parent, bg=G['bg'])
        self._dash_met_f.pack(fill='x', padx=16, pady=(0, 10))

        tk.Label(parent, text='Recent Transactions  (Today)',
                 font=(FONT, 12, 'bold'),
                 bg=G['bg'], fg=G['brand_dark']).pack(
            anchor='w', padx=16, pady=(4, 6))

        self._dash_tbl_f = tk.Frame(parent, bg=G['surface'],
                                     highlightbackground=G['border'],
                                     highlightthickness=1)
        self._dash_tbl_f.pack(fill='both', expand=True,
                               padx=16, pady=(0, 12))
        self._load_dashboard()

    def _load_dashboard(self):
        def _fetch():
            db = get_session()
            try:
                today = date.today()
                txns  = db.query(MillingTransaction).filter(
                    MillingTransaction.transaction_date == today).all()
                all_u = db.query(MillingTransaction).filter(
                    MillingTransaction.payment_status.in_(
                        ['Unpaid', 'Partial'])).all()
                recent = sorted(txns,
                                key=lambda x: x.created_at or datetime.min,
                                reverse=True)[:8]
                return {
                    'net'   : sum(D(t.net_amount)    for t in txns),
                    'cash'  : sum(D(t.amount_paid)   for t in txns),
                    'gross' : sum(D(t.gross_fee)     for t in txns),
                    'chaff' : sum(D(t.chaff_deduction) for t in txns),
                    'kilos' : sum(D(t.kilos_milled)  for t in txns),
                    'cnt'   : len(txns),
                    'ub_today': sum(D(t.balance) for t in txns
                                    if t.payment_status in ('Unpaid','Partial')),
                    'uc_today': sum(1 for t in txns
                                    if t.payment_status in ('Unpaid','Partial')),
                    'ub_all' : sum(D(t.balance) for t in all_u),
                    'uc_all' : len(all_u),
                    'recent' : [(t.transaction_number,
                                  fmt_time(t.created_at),
                                  t.customer_name or '—',
                                  f'{float(t.kilos_milled):.2f}',
                                  peso(t.net_amount),
                                  peso(t.amount_paid),
                                  peso(t.balance),
                                  t.payment_status,
                                  t.id)
                                 for t in recent],
                }
            finally:
                db.close()

        def _render(d):
            # Metrics grid
            mf = self._dash_met_f
            for w in mf.winfo_children(): w.destroy()
            metrics = [
                ('Net Income Today',   peso(d['net']),
                 G['brand'],  f"{d['cnt']} transaction(s)"),
                ('Cash Collected',     peso(d['cash']),
                 G['brand'],  'Actual received'),
                ('Gross Milling Fees', peso(d['gross']),
                 G['text'],   'Before deductions'),
                ('Chaff Deductions',   peso(d['chaff']),
                 G['muted'],  'Rice chaff'),
                ('Kilos Milled',
                 f"{float(d['kilos']):.2f} kg",
                 G['text'],   "Today's total"),
                ('Transactions',       str(d['cnt']),
                 G['text'],   f"{d['uc_today']} pending"),
                ('Unpaid Today',       peso(d['ub_today']),
                 G['danger'] if d['ub_today'] > 0 else G['brand'],
                 f"{d['uc_today']} record(s)"),
                ('All-time Unpaid',    peso(d['ub_all']),
                 G['danger'] if d['uc_all'] > 0 else G['brand'],
                 f"{d['uc_all']} customer(s)"),
            ]
            cols = 4
            for i, (lbl_t, val, vcol, sub) in enumerate(metrics):
                cf = tk.Frame(mf, bg=G['surface'],
                               highlightbackground=G['border'],
                               highlightthickness=1)
                cf.grid(row=i//cols, column=i%cols,
                         sticky='nsew', padx=4, pady=4)
                mf.columnconfigure(i%cols, weight=1)
                tk.Frame(cf, bg=vcol, width=4).pack(side='left', fill='y')
                inf = tk.Frame(cf, bg=G['surface'])
                inf.pack(fill='both', expand=True, padx=12, pady=10)
                tk.Label(inf, text=lbl_t.upper(),
                          font=(FONT, 8, 'bold'),
                          bg=G['surface'], fg=G['muted']).pack(anchor='w')
                tk.Label(inf, text=val,
                          font=(FONT, 16, 'bold'),
                          bg=G['surface'], fg=vcol).pack(anchor='w', pady=2)
                tk.Label(inf, text=sub,
                          font=(FONT, 9),
                          bg=G['surface'], fg=G['muted']).pack(anchor='w')

            # Recent table
            tf = self._dash_tbl_f
            for w in tf.winfo_children(): w.destroy()
            if not d['recent']:
                tk.Label(tf,
                          text='  No transactions today — click "New Transaction" to start.',
                          font=(FONT, 11), bg=G['surface'],
                          fg=G['muted']).pack(pady=30)
                return

            cols_def = [
                ('no',   'Txn No.',   120), ('time',  'Time',     70),
                ('cust', 'Customer',  160), ('kilos', 'Kilos',    70),
                ('net',  'Net Amt.',  110), ('paid',  'Paid',    110),
                ('bal',  'Balance',   110), ('st',    'Status',   90),
            ]
            tree = ttk.Treeview(tf,
                                 columns=[c[0] for c in cols_def],
                                 show='headings',
                                 style='PK.Treeview',
                                 selectmode='browse', height=8)
            for cid, heading, w in cols_def:
                tree.heading(cid, text=heading)
                tree.column(cid, width=w, minwidth=40, anchor='center')
            tree.column('cust', anchor='w')

            ys = ttk.Scrollbar(tf, orient='vertical', command=tree.yview)
            tree.configure(yscrollcommand=ys.set)
            ys.pack(side='right', fill='y')
            tree.pack(fill='both', expand=True)

            tree.tag_configure('Paid',    background=G['paid_bg'])
            tree.tag_configure('Unpaid',  background=G['unpaid_bg'])
            tree.tag_configure('Partial', background=G['partial_bg'])

            for row in d['recent']:
                tree.insert('', 'end', iid=str(row[-1]),
                             values=row[:-1], tags=(row[-2],))

            tree.bind('<Double-1>',
                      lambda e: self._open_txn_view(
                          int(tree.selection()[0]))
                      if tree.selection() else None)

            af = tk.Frame(tf, bg=G['brand_dim'])
            af.pack(fill='x')
            tk.Label(af,
                      text='  Double-click a row to view details',
                      font=(FONT, 9),
                      bg=G['brand_dim'], fg=G['brand_dark']).pack(
                side='left', padx=8, pady=5)

        self._sb('Loading dashboard…')
        threading.Thread(
            target=lambda: self.root.after(0, _render, _fetch()),
            daemon=True).start()

    # ── ══════════  RECORDS  ══════════ ───────────────────────────────────────
    def _build_records(self, parent):
        top = tk.Frame(parent, bg=G['bg'])
        top.pack(fill='x', padx=16, pady=(12, 6))
        tk.Label(top, text='📋  Transaction Records',
                 font=(FONT, 14, 'bold'),
                 bg=G['bg'], fg=G['brand_dark']).pack(side='left')
        tk.Button(top, text='➕ New Transaction',
                  command=self._open_txn_dialog,
                  bg=G['brand'], fg='#fff',
                  font=(FONT, 10, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=14, pady=6).pack(side='right')

        # Date tabs
        df = tk.Frame(parent, bg=G['bg'])
        df.pack(fill='x', padx=16, pady=(0, 6))
        self._date_tab_btns = {}
        for key, label in [('today', 'Today'), ('yesterday', 'Yesterday'),
                            ('week', 'This Week'), ('all', 'All')]:
            b = tk.Button(df, text=label,
                          font=(FONT, 10, 'bold'), relief='flat',
                          cursor='hand2', padx=14, pady=6, bd=0,
                          command=lambda k=key: self._set_rec_date(k))
            b.pack(side='left', padx=(0, 4))
            self._date_tab_btns[key] = b

        tk.Label(df, text='Custom:', font=(FONT, 9),
                 bg=G['bg'], fg=G['muted']).pack(side='left', padx=(10, 4))
        date_entry(df, textvariable=self._custom_date_var).pack(
            side='left', ipady=2)
        tk.Button(df, text='Go',
                  command=lambda: self._set_rec_date('custom'),
                  bg=G['bdr'], fg=G['text'],
                  font=(FONT, 9, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=8, pady=6).pack(side='left', padx=4)

        tk.Label(df, text='Status:', font=(FONT, 9),
                 bg=G['bg'], fg=G['muted']).pack(side='left', padx=(14, 4))
        sc = ttk.Combobox(df,
                           textvariable=self._status_filter_var,
                           values=['All', 'Paid', 'Partial', 'Unpaid'],
                           width=10, font=(FONT, 10), state='readonly')
        sc.pack(side='left')
        sc.bind('<<ComboboxSelected>>', lambda e: self._load_records())

        self._rec_tbl_f = tk.Frame(parent, bg=G['surface'],
                                    highlightbackground=G['border'],
                                    highlightthickness=1)
        self._rec_tbl_f.pack(fill='both', expand=True,
                              padx=16, pady=(0, 12))
        self._set_rec_date('today')

    def _set_rec_date(self, key):
        self._rec_date_filter = key
        for k, b in self._date_tab_btns.items():
            b.configure(
                bg=G['brand'] if k == key else G['brand_dim'],
                fg='#fff' if k == key else G['brand_dark'])
        self._load_records()

    def _load_records(self):
        df = self._rec_date_filter
        sf = self._status_filter_var.get()
        sf = sf if sf in ('Paid', 'Partial', 'Unpaid') else ''

        def _fetch():
            db = get_session()
            try:
                today = date.today()
                q     = db.query(MillingTransaction)
                if   df == 'today':
                    q = q.filter(MillingTransaction.transaction_date == today)
                elif df == 'yesterday':
                    q = q.filter(
                        MillingTransaction.transaction_date ==
                        today - timedelta(1))
                elif df == 'week':
                    q = q.filter(
                        MillingTransaction.transaction_date >=
                        today - timedelta(days=today.weekday()))
                elif df == 'custom':
                    try:
                        cd = date.fromisoformat(
                            self._custom_date_var.get())
                        q  = q.filter(
                            MillingTransaction.transaction_date == cd)
                    except Exception:
                        pass
                if sf:
                    q = q.filter(
                        MillingTransaction.payment_status == sf)
                rows = q.order_by(
                    MillingTransaction.created_at.desc()).all()
                return [(t.transaction_number,
                          fmt_date(t.transaction_date),
                          fmt_time(t.created_at),
                          t.customer_name or '—',
                          f'{float(t.kilos_milled):.2f}',
                          peso(t.gross_fee),
                          peso(t.chaff_deduction),
                          peso(t.net_amount),
                          peso(t.amount_paid),
                          peso(t.balance),
                          t.payment_status,
                          t.payment_method or '—',
                          t.id)
                         for t in rows]
            finally:
                db.close()

        def _render(rows):
            tf = self._rec_tbl_f
            for w in tf.winfo_children(): w.destroy()
            if not rows:
                tk.Label(tf,
                          text='  No transactions found.',
                          font=(FONT, 11),
                          bg=G['surface'], fg=G['muted']).pack(pady=30)
                return

            cols_def = [
                ('no',   'Txn No.',   120), ('date', 'Date',      100),
                ('time', 'Time',       70), ('cust', 'Customer',  150),
                ('kg',   'Kilos',      65), ('gr',   'Gross',     100),
                ('cd',   'Chaff Ded.', 95), ('net',  'Net Amt.',  100),
                ('pd',   'Paid',      100), ('bal',  'Balance',   100),
                ('st',   'Status',     80), ('mt',   'Method',     80),
            ]
            tree = ttk.Treeview(
                tf, columns=[c[0] for c in cols_def],
                show='headings', style='PK.Treeview',
                selectmode='browse')
            for cid, heading, w in cols_def:
                tree.heading(cid, text=heading)
                tree.column(cid, width=w, minwidth=40, anchor='center')
            tree.column('cust', anchor='w')

            ys = ttk.Scrollbar(tf, orient='vertical',   command=tree.yview)
            xs = ttk.Scrollbar(tf, orient='horizontal',  command=tree.xview)
            tree.configure(yscrollcommand=ys.set,
                            xscrollcommand=xs.set)
            ys.pack(side='right',  fill='y')
            xs.pack(side='bottom', fill='x')
            tree.pack(fill='both', expand=True)

            tree.tag_configure('Paid',    background=G['paid_bg'])
            tree.tag_configure('Unpaid',  background=G['unpaid_bg'])
            tree.tag_configure('Partial', background=G['partial_bg'])

            for row in rows:
                tree.insert('', 'end', iid=str(row[-1]),
                             values=row[:-1], tags=(row[-3],))

            def _act(action):
                sel = tree.selection()
                if not sel:
                    messagebox.showinfo('Select',
                                         'Select a transaction first.',
                                         parent=self.root)
                    return
                tid = int(sel[0])
                if   action == 'view':   self._open_txn_view(tid)
                elif action == 'edit':   self._open_txn_dialog(tid)
                elif action == 'pay':    self._open_payment(tid)
                elif action == 'delete': self._delete_txn(tid)

            tree.bind('<Double-1>', lambda e: _act('view'))

            af = tk.Frame(tf, bg=G['brand_dim'])
            af.pack(fill='x')
            tk.Label(af, text=f'  {len(rows)} record(s)',
                      font=(FONT, 9),
                      bg=G['brand_dim'],
                      fg=G['brand_dark']).pack(side='left', padx=8, pady=5)
            for lbl_t, act, bgc, fgc in [
                ('✕ Delete', 'delete', G['danger'],  '#fff'),
                ('💰 Pay',   'pay',    G['brand'],   '#fff'),
                ('✏️ Edit',  'edit',   G['bdr'],     G['text']),
                ('👁 View',  'view',   G['bdr'],     G['text']),
            ]:
                tk.Button(af, text=lbl_t,
                           command=lambda a=act: _act(a),
                           bg=bgc, fg=fgc,
                           font=(FONT, 9, 'bold'), relief='flat', bd=0,
                           cursor='hand2', padx=10, pady=4).pack(
                    side='right', padx=4, pady=4)

        self._sb('Loading records…')
        threading.Thread(
            target=lambda: self.root.after(0, _render, _fetch()),
            daemon=True).start()

    # ── ══════════  UNPAID  ══════════ ────────────────────────────────────────
    def _build_unpaid(self, parent):
        top = tk.Frame(parent, bg=G['bg'])
        top.pack(fill='x', padx=16, pady=(12, 8))
        self._unp_lbl = tk.Label(top, text='💳  Unpaid Balances',
                                  font=(FONT, 14, 'bold'),
                                  bg=G['bg'], fg=G['brand_dark'])
        self._unp_lbl.pack(side='left')
        tk.Button(top, text='↺ Refresh',
                  command=lambda: self._build_unpaid(parent),
                  bg=G['bdr'], fg=G['text'],
                  font=(FONT, 9, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=10, pady=4).pack(side='right')

        self._unp_tbl_f = tk.Frame(parent, bg=G['surface'],
                                    highlightbackground=G['border'],
                                    highlightthickness=1)
        self._unp_tbl_f.pack(fill='both', expand=True,
                              padx=16, pady=(0, 12))
        self._load_unpaid()

    def _load_unpaid(self):
        def _fetch():
            db = get_session()
            try:
                rows = db.query(MillingTransaction).filter(
                    MillingTransaction.payment_status.in_(
                        ['Unpaid', 'Partial'])
                ).order_by(
                    MillingTransaction.transaction_date.desc(),
                    MillingTransaction.created_at.desc()).all()
                total = sum(D(t.balance) for t in rows)
                return rows, total
            finally:
                db.close()

        def _render(result):
            rows, total = result
            self._unp_lbl.configure(
                text=(f'💳  Unpaid Balances  — '
                      f'{len(rows)} record(s)  ·  {peso(total)} owed'))

            tf = self._unp_tbl_f
            for w in tf.winfo_children(): w.destroy()

            if not rows:
                tk.Label(tf,
                          text='  ✅  No unpaid balances — all clear!',
                          font=(FONT, 12),
                          bg=G['surface'],
                          fg=G['brand']).pack(pady=40)
                return

            cols_def = [
                ('date', 'Date',       100), ('no',   'Txn No.',   120),
                ('cust', 'Customer',   160), ('cont', 'Contact',   110),
                ('net',  'Net Amt.',   110), ('paid', 'Paid',      110),
                ('bal',  'Balance',    110), ('st',   'Status',     80),
            ]
            tree = ttk.Treeview(
                tf, columns=[c[0] for c in cols_def],
                show='headings', style='PK.Treeview',
                selectmode='browse')
            for cid, heading, w in cols_def:
                tree.heading(cid, text=heading)
                tree.column(cid, width=w, minwidth=40, anchor='center')
            tree.column('cust', anchor='w')

            ys = ttk.Scrollbar(tf, orient='vertical', command=tree.yview)
            tree.configure(yscrollcommand=ys.set)
            ys.pack(side='right', fill='y')
            tree.pack(fill='both', expand=True)

            tree.tag_configure('Unpaid',  background=G['unpaid_bg'])
            tree.tag_configure('Partial', background=G['partial_bg'])

            for t in rows:
                tree.insert('', 'end', iid=str(t.id),
                             values=(fmt_date(t.transaction_date),
                                      t.transaction_number,
                                      t.customer_name or '—',
                                      t.contact_number or '—',
                                      peso(t.net_amount),
                                      peso(t.amount_paid),
                                      peso(t.balance),
                                      t.payment_status),
                             tags=(t.payment_status,))

            def _act(action):
                sel = tree.selection()
                if not sel:
                    messagebox.showinfo('Select', 'Select a record.',
                                         parent=self.root)
                    return
                tid = int(sel[0])
                if action == 'pay':
                    self._open_payment(tid)
                    for w in self._unp_tbl_f.winfo_children(): w.destroy()
                    self._load_unpaid()
                elif action == 'view':
                    self._open_txn_view(tid)

            tree.bind('<Double-1>', lambda e: _act('view'))

            af = tk.Frame(tf, bg=G['partial_bg'])
            af.pack(fill='x')
            tk.Label(af, text=f'  Total owed: {peso(total)}',
                      font=(FONT, 10, 'bold'),
                      bg=G['partial_bg'],
                      fg=G['partial_fg']).pack(side='left', padx=12, pady=6)
            for lbl_t, act, bgc, fgc in [
                ('👁 View',           'view', G['bdr'],   G['text']),
                ('💰 Record Payment', 'pay',  G['brand'], '#fff'),
            ]:
                tk.Button(af, text=lbl_t,
                           command=lambda a=act: _act(a),
                           bg=bgc, fg=fgc,
                           font=(FONT, 9, 'bold'), relief='flat', bd=0,
                           cursor='hand2', padx=12, pady=4).pack(
                    side='right', padx=4, pady=4)

        self._sb('Loading unpaid…')
        threading.Thread(
            target=lambda: self.root.after(0, _render, _fetch()),
            daemon=True).start()

    # ── ══════════  REPORTS  ══════════ ───────────────────────────────────────
    def _build_reports(self, parent):
        canvas = tk.Canvas(parent, bg=G['bg'], highlightthickness=0)
        vsb    = ttk.Scrollbar(parent, orient='vertical',
                                command=canvas.yview)
        body   = tk.Frame(canvas, bg=G['bg'])
        body.bind('<Configure>',
                  lambda e: canvas.configure(
                      scrollregion=canvas.bbox('all')))
        win = canvas.create_window((0, 0), window=body, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfig(win, width=e.width))
        vsb.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)

        tk.Label(body, text='📈  Generate Reports',
                 font=(FONT, 14, 'bold'),
                 bg=G['bg'], fg=G['brand_dark']).pack(
            anchor='w', padx=16, pady=(12, 8))

        # Quick buttons
        qf = tk.Frame(body, bg=G['bg'])
        qf.pack(fill='x', padx=16, pady=(0, 12))
        for icon, label, rtype in [
            ('📅', "Today",     'daily'),
            ('🗓️', "Yesterday", 'yesterday'),
            ('📆', "This Week", 'weekly'),
            ('🗂️', "This Month",'monthly'),
        ]:
            cf = tk.Frame(qf, bg=G['surface'],
                           highlightbackground=G['border'],
                           highlightthickness=1)
            cf.pack(side='left', padx=(0, 10))
            tk.Label(cf, text=icon, font=(FONT, 26),
                      bg=G['surface']).pack(pady=(12, 4))
            tk.Label(cf, text=label, font=(FONT, 10, 'bold'),
                      bg=G['surface'], fg=G['text']).pack(padx=20)
            tk.Button(cf, text='Generate',
                       command=lambda rt=rtype: self._gen_report(rt),
                       bg=G['brand'], fg='#fff',
                       font=(FONT, 9, 'bold'), relief='flat', bd=0,
                       cursor='hand2', padx=14, pady=4).pack(pady=(6, 12))

        # Custom range
        cf2 = tk.Frame(body, bg=G['surface'],
                        highlightbackground=G['border'],
                        highlightthickness=1)
        cf2.pack(fill='x', padx=16, pady=(0, 14))
        tk.Frame(cf2, bg=G['brand_dim']).pack(fill='x')
        tk.Label(cf2, text='  📋  Custom Date Range',
                  font=(FONT, 9, 'bold'),
                  bg=G['brand_dim'],
                  fg=G['brand_dark']).pack(fill='x', pady=6)

        cr = tk.Frame(cf2, bg=G['surface'])
        cr.pack(fill='x', padx=12, pady=8)
        self._rpt_s = tk.StringVar(value=today_iso())
        self._rpt_e = tk.StringVar(value=today_iso())
        for lbl_t, var in [('From:', self._rpt_s), ('To:', self._rpt_e)]:
            tk.Label(cr, text=lbl_t, font=(FONT, 10),
                      bg=G['surface'], fg=G['muted']).pack(side='left', padx=(0, 4))
            date_entry(cr, textvariable=var).pack(
                side='left', padx=(0, 16), ipady=2)
        tk.Button(cr, text='⬇  Generate',
                   command=lambda: self._gen_report('custom'),
                   bg=G['brand'], fg='#fff',
                   font=(FONT, 10, 'bold'), relief='flat', bd=0,
                   cursor='hand2', padx=14, pady=6).pack(side='left')

        # File list
        tk.Label(body, text='Generated Reports',
                  font=(FONT, 12, 'bold'),
                  bg=G['bg'], fg=G['brand_dark']).pack(
            anchor='w', padx=16, pady=(8, 4))
        self._rpt_list_f = tk.Frame(body, bg=G['surface'],
                                     highlightbackground=G['border'],
                                     highlightthickness=1)
        self._rpt_list_f.pack(fill='x', padx=16, pady=(0, 20))
        self._load_rpt_list()

    def _gen_report(self, rtype):
        today = date.today()
        if rtype in ('daily', 'yesterday'):
            d      = today if rtype == 'daily' else today - timedelta(1)
            s_date = e_date = d
            folder = 'daily'; label = d.strftime('%Y-%m-%d'); rtype = 'daily'
        elif rtype == 'weekly':
            s_date = today - timedelta(days=today.weekday())
            e_date = today; folder = 'weekly'
            label  = f'{s_date.strftime("%Y-%m-%d")}_to_{today.strftime("%Y-%m-%d")}'
        elif rtype == 'monthly':
            s_date = today.replace(day=1); e_date = today
            folder = 'monthly'; label = today.strftime('%Y-%m')
        elif rtype == 'custom':
            try:
                s_date = date.fromisoformat(self._rpt_s.get())
                e_date = date.fromisoformat(self._rpt_e.get())
            except ValueError:
                messagebox.showerror('Date Error',
                                      'Enter valid From/To dates.',
                                      parent=self.root)
                return
            folder = 'custom'
            label  = (f'{s_date.strftime("%Y-%m-%d")}'
                      f'_to_{e_date.strftime("%Y-%m-%d")}')
        else:
            return

        fname    = f'PalayKita_{rtype.capitalize()}_Report_{label}.xlsx'
        out_dir  = os.path.join(BASE_DIR, 'exports', 'reports', folder)
        filepath = os.path.join(out_dir, fname)

        def _do():
            db = get_session()
            try:
                txns = db.query(MillingTransaction).filter(
                    MillingTransaction.transaction_date >= s_date,
                    MillingTransaction.transaction_date <= e_date,
                ).order_by(
                    MillingTransaction.transaction_date,
                    MillingTransaction.created_at).all()
                s = db.query(Settings).first()
                generate_excel_report(
                    filepath=filepath, transactions=txns,
                    settings=s, report_type=rtype,
                    start_date=s_date, end_date=e_date,
                    business_name=s.business_name)
                return len(txns), filepath
            finally:
                db.close()

        def _done(result):
            cnt, fp = result
            self._sb(f'Report ready: {fname}')
            if messagebox.askyesno(
                    'Report Ready',
                    f'Saved!\n\n{fname}\n{cnt} transaction(s)\n\nOpen file?',
                    parent=self.root):
                try:
                    if _P == 'win32':    os.startfile(fp)
                    elif _P == 'darwin': subprocess.call(['open', fp])
                    else:               subprocess.call(['xdg-open', fp])
                except Exception:
                    messagebox.showinfo('Path', fp, parent=self.root)
            self._load_rpt_list()

        self._sb('Generating report…')
        threading.Thread(
            target=lambda: self.root.after(0, _done, _do()),
            daemon=True).start()

    def _load_rpt_list(self):
        rf = self._rpt_list_f
        for w in rf.winfo_children(): w.destroy()

        reports = []
        base = os.path.join(BASE_DIR, 'exports', 'reports')
        for folder in ['daily', 'weekly', 'monthly', 'custom']:
            fd = os.path.join(base, folder)
            if not os.path.exists(fd): continue
            for f in os.listdir(fd):
                if f.endswith('.xlsx'):
                    fp = os.path.join(fd, f)
                    reports.append((
                        f, folder, fp,
                        os.path.getsize(fp),
                        datetime.fromtimestamp(os.path.getmtime(fp))))
        reports.sort(key=lambda x: x[4], reverse=True)

        if not reports:
            tk.Label(rf, text='  No reports yet.',
                      font=(FONT, 11),
                      bg=G['surface'], fg=G['muted']).pack(pady=16)
            return

        icons = {'daily':'📅','weekly':'📆','monthly':'🗂️','custom':'📋'}
        for fname, folder, fp, size, mtime in reports[:40]:
            row = tk.Frame(rf, bg=G['surface'])
            row.pack(fill='x')
            tk.Frame(row, bg=G['bdr'], height=1).pack(fill='x')
            inner = tk.Frame(row, bg=G['surface'])
            inner.pack(fill='x', padx=12, pady=6)

            tk.Label(inner, text=icons.get(folder, '📄'),
                      font=(FONT, 18),
                      bg=G['surface']).pack(side='left', padx=(0, 8))
            info_f = tk.Frame(inner, bg=G['surface'])
            info_f.pack(side='left', fill='x', expand=True)
            tk.Label(info_f, text=fname,
                      font=(FONT, 10, 'bold'),
                      bg=G['surface'], fg=G['text'],
                      anchor='w').pack(anchor='w')
            kb = size / 1024
            tk.Label(info_f,
                      text=(f'{folder.capitalize()}  ·  '
                             f'{mtime.strftime("%b %d %Y %I:%M %p")}  ·  '
                             f'{kb:.1f} KB'),
                      font=(FONT, 9),
                      bg=G['surface'], fg=G['muted'],
                      anchor='w').pack(anchor='w')

            ab = tk.Frame(inner, bg=G['surface'])
            ab.pack(side='right')

            def _open(p=fp):
                try:
                    if _P == 'win32':    os.startfile(p)
                    elif _P == 'darwin': subprocess.call(['open', p])
                    else:               subprocess.call(['xdg-open', p])
                except Exception:
                    messagebox.showinfo('Path', p, parent=self.root)

            def _del(p=fp, fn=fname):
                if messagebox.askyesno('Delete', f'Delete {fn}?',
                                        parent=self.root):
                    try: os.remove(p)
                    except Exception: pass
                    self._load_rpt_list()

            tk.Button(ab, text='📂 Open', command=_open,
                       bg=G['bdr'], fg=G['text'],
                       font=(FONT, 9, 'bold'), relief='flat', bd=0,
                       cursor='hand2', padx=10, pady=4).pack(
                side='left', padx=(0, 4))
            tk.Button(ab, text='✕ Delete', command=_del,
                       bg=G['danger_bg'], fg=G['danger'],
                       font=(FONT, 9, 'bold'), relief='flat', bd=0,
                       cursor='hand2', padx=10, pady=4).pack(side='left')

    # ── ══════════  SETTINGS  ══════════ ──────────────────────────────────────
    def _build_settings(self, parent):
        nb = ttk.Notebook(parent, style='PK.TNotebook')
        nb.pack(fill='both', expand=True, padx=16, pady=12)
        tg = tk.Frame(nb, bg=G['bg'])
        ts = tk.Frame(nb, bg=G['bg'])
        tu = tk.Frame(nb, bg=G['bg'])
        nb.add(tg, text='⚙️  General')
        nb.add(ts, text='🖥️  Server')
        nb.add(tu, text='👥  Users')
        self._build_settings_general(tg)
        self._build_settings_server(ts)
        self._build_settings_users(tu)

    # ── Settings → General ────────────────────────────────────────────────────
    def _build_settings_general(self, parent):
        canvas = tk.Canvas(parent, bg=G['bg'], highlightthickness=0)
        vsb    = ttk.Scrollbar(parent, orient='vertical',
                                command=canvas.yview)
        body   = tk.Frame(canvas, bg=G['bg'])
        body.bind('<Configure>',
                  lambda e: canvas.configure(
                      scrollregion=canvas.bbox('all')))
        win = canvas.create_window((0, 0), window=body, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfig(win, width=e.width))
        vsb.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)

        cf = tk.Frame(body, bg=G['surface'],
                       highlightbackground=G['border'],
                       highlightthickness=1)
        cf.pack(fill='x', padx=8, pady=(8, 12))
        tk.Frame(cf, bg=G['brand_dim']).pack(fill='x')
        tk.Label(cf, text='  🏢  Business Settings',
                  font=(FONT, 9, 'bold'),
                  bg=G['brand_dim'], fg=G['brand_dark']).pack(
            fill='x', pady=6)

        inner = tk.Frame(cf, bg=G['surface'])
        inner.pack(fill='x', padx=12, pady=8)

        db = get_session()
        try:
            s = db.query(Settings).first()
            vals = {
                'business_name'       : s.business_name or '',
                'milling_rate_per_kg' : str(s.milling_rate_per_kg),
                'chaff_rate_per_kg'   : str(s.chaff_rate_per_kg),
                'currency_symbol'     : s.currency_symbol or '₱',
                'receipt_footer'      : s.receipt_footer or '',
            }
        finally:
            db.close()

        self._cfg_vars = {}
        self._cfg_widgets = {}
        fields = [
            ('business_name',       'Business Name',          'entry'),
            ('milling_rate_per_kg', 'Milling Rate / kg (₱)',  'entry'),
            ('chaff_rate_per_kg',   'Chaff Rate / kg (₱)',    'entry'),
            ('currency_symbol',     'Currency Symbol',         'entry'),
            ('receipt_footer',      'Receipt Footer',          'text'),
        ]
        for field, label, wtype in fields:
            row = tk.Frame(inner, bg=G['surface'])
            row.pack(fill='x', pady=4)
            tk.Label(row, text=label,
                      font=(FONT, 9, 'bold'),
                      bg=G['surface'], fg=G['muted'],
                      width=24, anchor='w').pack(side='left')
            if wtype == 'text':
                w = tk.Text(row, height=2, width=35,
                             font=(FONT, 11), relief='solid', bd=1,
                             bg='#fff', fg=G['text'])
                w.insert('1.0', vals.get(field, ''))
                w.pack(side='left', fill='x', expand=True, padx=(8, 0))
            else:
                v = tk.StringVar(value=vals.get(field, ''))
                w = tk.Entry(row, textvariable=v, width=28,
                              font=(FONT, 11), relief='solid', bd=1,
                              bg='#fff', fg=G['text'])
                w.pack(side='left', fill='x', expand=True, padx=(8, 0), ipady=4)
                self._cfg_vars[field] = v
            self._cfg_widgets[field] = w

        tk.Button(inner, text='💾  Save Settings',
                   command=self._save_settings,
                   bg=G['brand'], fg='#fff',
                   font=(FONT, 11, 'bold'), relief='flat', bd=0,
                   cursor='hand2', padx=16, pady=8).pack(
            anchor='e', pady=10)

    def _save_settings(self):
        db = get_session()
        try:
            s = db.query(Settings).first()
            for field, w in self._cfg_widgets.items():
                if isinstance(w, tk.Text):
                    val = w.get('1.0', 'end').strip()
                elif field in self._cfg_vars:
                    val = self._cfg_vars[field].get().strip()
                else:
                    val = w.get().strip()
                if field in ('milling_rate_per_kg', 'chaff_rate_per_kg'):
                    try: val = Decimal(val)
                    except Exception: continue
                setattr(s, field, val)
            s.updated_at = datetime.utcnow()
            db.commit()
            self._load_settings_data()
            self._biz_lbl.configure(
                text=self.settings.get('business_name', 'PalayKita'))
            messagebox.showinfo('Saved',
                                 'Settings saved.',
                                 parent=self.root)
        except Exception as e:
            db.rollback()
            messagebox.showerror('Error', str(e), parent=self.root)
        finally:
            db.close()

    # ── Settings → Server ─────────────────────────────────────────────────────
    def _build_settings_server(self, parent):
        canvas = tk.Canvas(parent, bg=G['bg'], highlightthickness=0)
        vsb    = ttk.Scrollbar(parent, orient='vertical',
                                command=canvas.yview)
        body   = tk.Frame(canvas, bg=G['bg'])
        body.bind('<Configure>',
                  lambda e: canvas.configure(
                      scrollregion=canvas.bbox('all')))
        win = canvas.create_window((0, 0), window=body, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfig(win, width=e.width))
        vsb.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)

        # Status card
        sc = tk.Frame(body, bg=G['surface'],
                       highlightbackground=G['border'],
                       highlightthickness=1)
        sc.pack(fill='x', padx=8, pady=(8, 8))
        tk.Frame(sc, bg=G['brand_dim']).pack(fill='x')
        tk.Label(sc, text='  🖥️  Flask Server  (for mobile access)',
                  font=(FONT, 9, 'bold'),
                  bg=G['brand_dim'], fg=G['brand_dark']).pack(fill='x', pady=6)

        si = tk.Frame(sc, bg=G['surface'])
        si.pack(fill='x', padx=12, pady=8)

        # Dot + status label
        sr = tk.Frame(si, bg=G['surface'])
        sr.pack(fill='x', pady=(0, 8))
        self._svr_dot = tk.Canvas(sr, width=14, height=14,
                                    bg=G['surface'], highlightthickness=0)
        self._svr_dot.pack(side='left', padx=(0, 8))
        self._svr_dot.create_oval(2, 2, 12, 12,
                                   fill='#9CA3AF', outline='', tags='dot')
        self._svr_st_lbl = tk.Label(sr, text='Server Stopped',
                                     font=(FONT, 12, 'bold'),
                                     bg=G['surface'], fg=G['muted'])
        self._svr_st_lbl.pack(side='left')

        tk.Frame(si, bg=G['bdr'], height=1).pack(fill='x', pady=6)

        # Port
        pr = tk.Frame(si, bg=G['surface'])
        pr.pack(fill='x', pady=4)
        tk.Label(pr, text='Port:', font=(FONT, 10, 'bold'),
                  bg=G['surface'], fg=G['muted']).pack(side='left')
        self._svr_port_e = tk.Entry(pr, textvariable=self._svr_port,
                                     width=7, font=(FONT, 11),
                                     relief='solid', bd=1, bg='#fff')
        self._svr_port_e.pack(side='left', padx=(8, 0))
        tk.Button(pr, text='Save Port',
                  command=lambda: self._save_server_port(show_message=True),
                  bg=G['brand_dim'], fg=G['brand_dark'],
                  font=(FONT, 9, 'bold'), relief='flat', bd=0,
                  cursor='hand2', padx=10, pady=3).pack(side='left', padx=(8, 0))
        tk.Label(pr, text='(stop server before changing)',
                  font=(FONT, 9), bg=G['surface'],
                  fg=G['muted']).pack(side='left', padx=(8, 0))

        tk.Frame(si, bg=G['bdr'], height=1).pack(fill='x', pady=6)

        # IP list
        tk.Label(si, text='Access URLs:',
                  font=(FONT, 10, 'bold'),
                  bg=G['surface'], fg=G['muted']).pack(anchor='w', pady=(0, 4))
        self._svr_ip_f = tk.Frame(si, bg=G['surface'])
        self._svr_ip_f.pack(fill='x', pady=(0, 8))
        self._refresh_svr_ips()

        tk.Frame(si, bg=G['bdr'], height=1).pack(fill='x', pady=6)

        # Control buttons
        bf = tk.Frame(si, bg=G['surface'])
        bf.pack(fill='x', pady=4)
        self._btn_start = tk.Button(bf, text='▶  Start Server',
                                     command=self._start_server,
                                     bg=G['brand'], fg='#fff',
                                     font=(FONT, 10, 'bold'),
                                     relief='flat', bd=0, cursor='hand2',
                                     padx=14, pady=7)
        self._btn_start.pack(side='left', padx=(0, 8))
        self._btn_stop = tk.Button(bf, text='■  Stop Server',
                                    command=self._stop_server,
                                    bg=G['danger'], fg='#fff',
                                    font=(FONT, 10, 'bold'),
                                    relief='flat', bd=0, cursor='hand2',
                                    padx=14, pady=7, state='disabled')
        self._btn_stop.pack(side='left', padx=(0, 8))
        self._btn_restart = tk.Button(bf, text='↺  Restart',
                                       command=self._restart_server,
                                       bg=G['accent'], fg='#fff',
                                       font=(FONT, 10, 'bold'),
                                       relief='flat', bd=0, cursor='hand2',
                                       padx=14, pady=7, state='disabled')
        self._btn_restart.pack(side='left', padx=(0, 8))
        tk.Button(bf, text='🌐  Open Browser',
                   command=self._open_browser,
                   bg=G['bdr'], fg=G['text'],
                   font=(FONT, 10, 'bold'),
                   relief='flat', bd=0, cursor='hand2',
                   padx=14, pady=7).pack(side='left')

        # Options
        opt = tk.Frame(si, bg=G['surface'])
        opt.pack(fill='x', pady=4)
        for var, text in [
            (self._auto_start,   'Auto-start server when this app opens'),
            (self._auto_restart, 'Auto-restart if server crashes'),
        ]:
            tk.Checkbutton(opt, text=text, variable=var,
                            bg=G['surface'], fg=G['text'],
                            selectcolor=G['brand_dim'],
                            activebackground=G['surface'],
                            font=(FONT, 10), relief='flat').pack(
                anchor='w', pady=2)

        # Log card
        lc = tk.Frame(body, bg=G['surface'],
                       highlightbackground=G['border'],
                       highlightthickness=1)
        lc.pack(fill='x', padx=8, pady=(0, 16))
        tk.Frame(lc, bg=G['brand_dim']).pack(fill='x')
        tk.Label(lc, text='  📜  Server Log',
                  font=(FONT, 9, 'bold'),
                  bg=G['brand_dim'], fg=G['brand_dark']).pack(fill='x', pady=6)

        log_f = tk.Frame(lc, bg=G['log_bg'])
        log_f.pack(fill='x', padx=12, pady=(0, 4))

        self._svr_log = tk.Text(log_f, bg=G['log_bg'], fg=G['log_fg'],
                                 font=(MONO, 9), relief='flat', bd=0,
                                 state='disabled', height=12,
                                 padx=8, pady=6)
        log_sb = ttk.Scrollbar(log_f, orient='vertical',
                                command=self._svr_log.yview)
        self._svr_log.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side='right', fill='y')
        self._svr_log.pack(fill='both', expand=True)

        for tag, col in [('info', G['log_fg']), ('err', G['log_err']),
                          ('warn', G['log_warn']), ('url', G['log_url']),
                          ('muted', G['log_muted'])]:
            self._svr_log.tag_config(tag, foreground=col)

        bf2 = tk.Frame(lc, bg=G['surface'])
        bf2.pack(fill='x', padx=12, pady=(0, 8))
        tk.Button(bf2, text='Clear Log',
                   command=self._clear_svr_log,
                   bg=G['bdr'], fg=G['text'],
                   font=(FONT, 9, 'bold'), relief='flat', bd=0,
                   cursor='hand2', padx=10, pady=4).pack(side='right')

        if self._auto_start.get() and not self._svr_running:
            self.root.after(500, self._start_server)

    def _normalized_server_port(self, raw=None):
        try:
            port = int(raw if raw is not None else self._svr_port.get())
        except Exception:
            port = 5000
        if port < 1024 or port > 65535:
            raise ValueError('Port must be between 1024 and 65535.')
        return port

    def _save_server_port(self, show_message=False):
        try:
            port = self._normalized_server_port()
        except ValueError as exc:
            messagebox.showerror('Invalid Port', str(exc), parent=self.root)
            self._svr_port.set(int(self.settings.get('server_port', 5000)))
            return None

        db = get_session()
        try:
            s = db.query(Settings).first()
            if s:
                s.server_port = port
                s.updated_at = datetime.utcnow()
                db.commit()
            self.settings['server_port'] = port
            self._svr_port.set(port)
            if hasattr(self, '_svr_ip_f'):
                self._refresh_svr_ips()
            if show_message:
                messagebox.showinfo('Saved', 'Server port saved. Restart the server to apply it.', parent=self.root)
            return port
        except Exception as e:
            db.rollback()
            messagebox.showerror('Error', str(e), parent=self.root)
            return None
        finally:
            db.close()

    def _refresh_svr_ips(self):
        for w in self._svr_ip_f.winfo_children(): w.destroy()
        port = self._svr_port.get()
        for ip in all_ips():
            url   = f'http://{ip}:{port}'
            label = 'Network' if not ip.startswith('127.') else 'Local'
            row   = tk.Frame(self._svr_ip_f, bg=G['surface'])
            row.pack(fill='x', pady=2)
            tk.Label(row, text=f'{label}:',
                      width=9, anchor='w',
                      font=(FONT, 9), bg=G['surface'],
                      fg=G['muted']).pack(side='left')
            tk.Label(row, text=url,
                      font=(MONO, 10, 'bold'),
                      bg=G['surface'], fg=G['brand'],
                      cursor='hand2').pack(side='left')
            tk.Button(row, text='⧉',
                       command=lambda u=url: self._copy(u),
                       bg=G['brand_dim'], fg=G['brand_dark'],
                       font=(FONT, 9), relief='flat', bd=0,
                       cursor='hand2', padx=6, pady=2).pack(
                side='left', padx=(6, 0))

    def _copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._sb(f'Copied: {text}')

    def _svr_log_write(self, text, tag='info'):
        if not hasattr(self, '_svr_log'): return
        ts = datetime.now().strftime('%H:%M:%S')
        self._svr_log.configure(state='normal')
        self._svr_log.insert('end', f'[{ts}] ', 'muted')
        self._svr_log.insert('end', text.rstrip('\n') + '\n', tag)
        self._svr_log.configure(state='disabled')
        self._svr_log.see('end')

    def _clear_svr_log(self):
        if not hasattr(self, '_svr_log'): return
        self._svr_log.configure(state='normal')
        self._svr_log.delete('1.0', 'end')
        self._svr_log.configure(state='disabled')

    def _dot_color(self, color):
        if not hasattr(self, '_svr_dot'): return
        c = {'green':'#22C55E','red':'#EF4444',
             'yellow':'#F59E0B','gray':'#9CA3AF'}.get(color, color)
        self._svr_dot.itemconfig('dot', fill=c)

    def _set_svr_ui(self, running, interim=False):
        self._svr_running = running
        if not hasattr(self, '_svr_st_lbl'): return
        if interim:
            self._dot_color('yellow')
            self._svr_st_lbl.configure(text='Starting…', fg=G['accent'])
        elif running:
            self._dot_color('green')
            self._svr_st_lbl.configure(text='Server Running',
                                        fg=G['brand'])
            self._svr_sb.configure(
                text=f'Flask ▶ port {self._svr_port.get()}')
        else:
            self._dot_color('gray')
            self._svr_st_lbl.configure(text='Server Stopped',
                                        fg=G['muted'])
            self._svr_sb.configure(text='')
        ss = 'normal'  if not running and not interim else 'disabled'
        rs = 'normal'  if running                     else 'disabled'
        if hasattr(self, '_btn_start'):
            self._btn_start.configure(state=ss)
            self._btn_stop.configure(state=rs)
            self._btn_restart.configure(state=rs)
            self._svr_port_e.configure(state=ss)

    def _start_server(self):
        if self._svr_running: return
        port = self._save_server_port(show_message=False)
        if port is None:
            return
        self._set_svr_ui(False, interim=True)
        self._svr_log_write(f'Starting on port {port}…')
        self._refresh_svr_ips()
        env = os.environ.copy()
        env['PALAYKITA_PORT'] = str(port)
        kw  = {}
        if _P == 'win32':
            kw['creationflags'] = subprocess.CREATE_NO_WINDOW
        try:
            self._svr_proc = subprocess.Popen(
                [PY_EXE, os.path.join(BASE_DIR, 'app.py')],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=env, cwd=BASE_DIR, bufsize=1, text=True, **kw)
        except FileNotFoundError:
            self._set_svr_ui(False)
            self._svr_log_write('ERROR: app.py not found.', 'err')
            return
        threading.Thread(target=self._read_svr,
                         args=(self._svr_proc,), daemon=True).start()
        threading.Thread(target=self._watch_svr,
                         args=(self._svr_proc, port), daemon=True).start()

    def _read_svr(self, proc):
        for line in proc.stdout:
            line = line.rstrip('\n')
            if not line: continue
            if any(x in line for x in ('ERROR','Error','Traceback')):
                tag = 'err'
            elif 'WARNING' in line:                         tag = 'warn'
            elif 'Running on' in line or 'http://' in line: tag = 'url'
            elif ' - - [' in line:                          tag = 'muted'
            else:                                            tag = 'info'
            self._log_q.put((line, tag))

    def _watch_svr(self, proc, port):
        time.sleep(2.0)
        if proc.poll() is None:
            self.root.after(0, lambda: self._set_svr_ui(True))
            self.root.after(0, lambda: self._svr_log_write(
                f'✓ Server up — http://localhost:{port}', 'url'))
        else:
            self.root.after(0, lambda: self._set_svr_ui(False))
            self.root.after(0, lambda: self._svr_log_write(
                '✗ Failed to start.', 'err'))
            return
        code = proc.wait()
        self.root.after(0, lambda: self._on_svr_exit(code, port))

    def _on_svr_exit(self, code, port):
        self._set_svr_ui(False)
        if code == EXIT_RESTART:
            self._svr_log_write('↺ Restart signal.', 'warn')
            self.root.after(800, self._start_server)
        elif code == 0:
            self._svr_log_write('■ Stopped cleanly.', 'warn')
        else:
            self._svr_log_write(f'✗ Exited (code {code}).', 'err')
            if self._auto_restart.get():
                self._svr_log_write('↺ Auto-restart in 3 s…', 'warn')
                self.root.after(3000, self._start_server)

    def _stop_server(self):
        if not self._svr_proc or not self._svr_running: return
        self._svr_log_write('■ Stopping…', 'warn')
        self._set_svr_ui(False)
        try:
            self._svr_proc.terminate()
            for _ in range(30):
                if self._svr_proc.poll() is not None: break
                time.sleep(0.1)
            else:
                self._svr_proc.kill()
        except Exception as e:
            self._svr_log_write(f'Stop error: {e}', 'err')
        self._svr_proc = None
        self._svr_sb.configure(text='')

    def _restart_server(self):
        self._svr_log_write('↺ Restarting…', 'warn')
        self._stop_server()
        self.root.after(800, self._start_server)

    def _open_browser(self):
        webbrowser.open(f'http://localhost:{self._svr_port.get()}')

    def _pump_log(self):
        try:
            while True:
                text, tag = self._log_q.get_nowait()
                self._svr_log_write(text, tag)
        except queue.Empty:
            pass
        self.root.after(80, self._pump_log)

    # ── Settings → Users ──────────────────────────────────────────────────────
    def _build_settings_users(self, parent):
        if not self.is_admin:
            tk.Label(parent,
                      text='Admin access required to manage users.',
                      font=(FONT, 12), bg=G['bg'],
                      fg=G['muted']).pack(pady=40)
            return
        top = tk.Frame(parent, bg=G['bg'])
        top.pack(fill='x', padx=8, pady=(12, 6))
        tk.Label(top, text='User Accounts',
                  font=(FONT, 12, 'bold'), bg=G['bg'],
                  fg=G['brand_dark']).pack(side='left')
        tk.Button(top, text='+ Add User',
                   command=lambda: self._user_dlg(None),
                   bg=G['brand'], fg='#fff',
                   font=(FONT, 9, 'bold'), relief='flat', bd=0,
                   cursor='hand2', padx=10, pady=4).pack(side='right')
        self._users_f = tk.Frame(parent, bg=G['surface'],
                                  highlightbackground=G['border'],
                                  highlightthickness=1)
        self._users_f.pack(fill='x', padx=8, pady=(0, 12))
        self._load_users()

    def _load_users(self):
        if not hasattr(self, '_users_f'): return
        for w in self._users_f.winfo_children(): w.destroy()
        db = get_session()
        try:
            users = db.query(User).order_by(User.created_at).all()
        finally:
            db.close()
        for u in users:
            row = tk.Frame(self._users_f, bg=G['surface'])
            row.pack(fill='x')
            tk.Frame(row, bg=G['bdr'], height=1).pack(fill='x')
            inner = tk.Frame(row, bg=G['surface'])
            inner.pack(fill='x', padx=12, pady=8)
            av = tk.Frame(inner, bg=G['brand_dim'], width=36, height=36)
            av.pack(side='left', padx=(0, 10)); av.pack_propagate(False)
            tk.Label(av, text=u.username[0].upper(),
                      font=(FONT, 14, 'bold'),
                      bg=G['brand_dim'], fg=G['brand_dark']).pack(expand=True)
            inf = tk.Frame(inner, bg=G['surface'])
            inf.pack(side='left', fill='x', expand=True)
            tk.Label(inf, text=u.username,
                      font=(FONT, 11, 'bold'),
                      bg=G['surface'], fg=G['text']).pack(anchor='w')
            tk.Label(inf,
                      text=f'{u.role}  ·  {"Active" if u.is_active else "Disabled"}',
                      font=(FONT, 9), bg=G['surface'],
                      fg=G['brand'] if u.is_active else G['muted']).pack(
                anchor='w')
            ab = tk.Frame(inner, bg=G['surface'])
            ab.pack(side='right')
            tk.Button(ab, text='Edit',
                       command=lambda uid=u.id: self._user_dlg(uid),
                       bg=G['bdr'], fg=G['text'],
                       font=(FONT, 9, 'bold'), relief='flat', bd=0,
                       cursor='hand2', padx=8, pady=4).pack(
                side='left', padx=(0, 4))
            if u.username != self.username:
                lbl_t = 'Disable' if u.is_active else 'Enable'
                bgc   = G['danger_bg'] if u.is_active else G['brand_dim']
                fgc   = G['danger']    if u.is_active else G['brand']
                tk.Button(ab, text=lbl_t,
                           command=lambda uid=u.id,
                           act=u.is_active: self._toggle_user(uid, act),
                           bg=bgc, fg=fgc,
                           font=(FONT, 9, 'bold'), relief='flat', bd=0,
                           cursor='hand2', padx=8, pady=4).pack(side='left')

    def _user_dlg(self, uid):
        dlg = tk.Toplevel(self.root)
        dlg.title('Edit User' if uid else 'Add User')
        dlg.geometry('360x300'); dlg.resizable(False, False)
        dlg.configure(bg=G['surface'])
        dlg.transient(self.root); dlg.grab_set()
        hdr = tk.Frame(dlg, bg=G['header'], height=46)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text='Edit User' if uid else 'Add User',
                  font=(FONT, 12, 'bold'),
                  bg=G['header'], fg='#fff').pack(side='left', padx=16)
        body = tk.Frame(dlg, bg=G['surface'])
        body.pack(fill='both', expand=True, padx=20, pady=12)
        v_un = tk.StringVar(); v_pw = tk.StringVar()
        v_role = tk.StringVar(value='staff')
        if uid:
            db = get_session()
            try:
                u = db.get(User, uid)
                if u: v_un.set(u.username); v_role.set(u.role)
            finally:
                db.close()
        for lbl_t, var, show, hint in [
            ('Username', v_un, '',  ''),
            ('Password', v_pw, '•', '(blank = keep)' if uid else ''),
        ]:
            tk.Label(body, text=f'{lbl_t}  {hint}',
                      font=(FONT, 9, 'bold'),
                      bg=G['surface'], fg=G['muted']).pack(anchor='w',
                                                             pady=(8, 2))
            e = tk.Entry(body, textvariable=var, show=show,
                          font=(FONT, 11), relief='solid', bd=1, bg='#fff')
            e.pack(fill='x', ipady=4)
            if uid and lbl_t == 'Username':
                e.configure(state='disabled')
        tk.Label(body, text='Role', font=(FONT, 9, 'bold'),
                  bg=G['surface'], fg=G['muted']).pack(anchor='w',
                                                         pady=(8, 2))
        ttk.Combobox(body, textvariable=v_role,
                      values=['staff', 'admin'],
                      font=(FONT, 11), state='readonly').pack(fill='x')

        def _save():
            un = v_un.get().strip(); pw = v_pw.get()
            if not uid and (not un or not pw):
                messagebox.showerror('Validation',
                                      'Username and password required.',
                                      parent=dlg); return
            db2 = get_session()
            try:
                if uid:
                    u2 = db2.get(User, uid)
                    u2.role = v_role.get()
                    if pw: u2.password_hash = generate_password_hash(pw)
                else:
                    if db2.query(User).filter_by(username=un).first():
                        messagebox.showerror('Error',
                                              f'Username "{un}" exists.',
                                              parent=dlg); return
                    db2.add(User(username=un,
                                  password_hash=generate_password_hash(pw),
                                  role=v_role.get(), is_active=True))
                db2.commit()
                dlg.destroy(); self._load_users()
            except Exception as e:
                db2.rollback()
                messagebox.showerror('Error', str(e), parent=dlg)
            finally:
                db2.close()

        bf = tk.Frame(body, bg=G['surface'])
        bf.pack(fill='x', pady=10)
        bf.columnconfigure(0, weight=1); bf.columnconfigure(1, weight=1)
        tk.Button(bf, text='Cancel', command=dlg.destroy,
                   bg=G['bdr'], fg=G['text'],
                   font=(FONT, 10, 'bold'), relief='flat', bd=0,
                   cursor='hand2', padx=12, pady=6).grid(
            row=0, column=0, sticky='ew', padx=(0, 4))
        tk.Button(bf, text='💾 Save', command=_save,
                   bg=G['brand'], fg='#fff',
                   font=(FONT, 10, 'bold'), relief='flat', bd=0,
                   cursor='hand2', padx=12, pady=6).grid(
            row=0, column=1, sticky='ew')

    def _toggle_user(self, uid, currently_active):
        db = get_session()
        try:
            u = db.get(User, uid)
            if u: u.is_active = not currently_active
            db.commit(); self._load_users()
        except Exception as e:
            db.rollback()
            messagebox.showerror('Error', str(e), parent=self.root)
        finally:
            db.close()

    # ── Transaction helpers ───────────────────────────────────────────────────
    def _open_txn_dialog(self, txn_id=None):
        dlg = TxnDialog(self.root, self, txn_id)
        if dlg.saved:
            self._sb('Transaction saved ✓')
            if self._current_nav == 'dashboard':
                self._nav_click('dashboard')
            elif self._current_nav == 'records':
                self._load_records()
            elif self._current_nav == 'unpaid':
                self._load_unpaid()

    def _open_txn_view(self, txn_id):
        db = get_session()
        try:
            t = db.get(MillingTransaction, txn_id)
            if not t: return
            d = {
                'id'       : t.id,
                'num'      : t.transaction_number,
                'customer' : t.customer_name or 'Walk-in',
                'contact'  : t.contact_number or '—',
                'date'     : fmt_date(t.transaction_date),
                'kilos'    : f'{float(t.kilos_milled):.2f} kg',
                'mrate'    : peso(t.milling_rate_per_kg),
                'gross'    : peso(t.gross_fee),
                'has_chaff': t.has_chaff_deduction,
                'ck'       : f'{float(t.chaff_kilos):.2f} kg',
                'cr'       : peso(t.chaff_rate_per_kg),
                'cd'       : peso(t.chaff_deduction),
                'net'      : peso(t.net_amount),
                'paid'     : peso(t.amount_paid),
                'balance'  : peso(t.balance),
                'status'   : t.payment_status,
                'method'   : t.payment_method or '—',
                'notes'    : t.notes or '—',
                'payments' : [(peso(p.amount),
                                p.payment_method or 'Cash',
                                fmt_time(p.payment_date),
                                p.notes or '')
                               for p in t.payments],
            }
        finally:
            db.close()

        dlg = tk.Toplevel(self.root)
        dlg.title(f'Transaction — {d["num"]}')
        dlg.geometry('460x560')
        dlg.configure(bg=G['surface'])
        dlg.transient(self.root); dlg.grab_set()

        hdr = tk.Frame(dlg, bg=G['header'], height=50)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text=d['num'],
                  font=(FONT, 13, 'bold'),
                  bg=G['header'], fg='#fff').pack(side='left', padx=16)
        tk.Label(hdr, text=d['status'],
                  font=(FONT, 10, 'bold'),
                  bg=status_bg(d['status']),
                  fg=status_color(d['status']),
                  padx=10, pady=4).pack(side='right', padx=12)

        canvas = tk.Canvas(dlg, bg=G['surface'], highlightthickness=0)
        vsb    = ttk.Scrollbar(dlg, orient='vertical',
                                command=canvas.yview)
        sv     = tk.Frame(canvas, bg=G['surface'])
        sv.bind('<Configure>',
                lambda e: canvas.configure(
                    scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=sv, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)

        def section(title):
            f = tk.Frame(sv, bg=G['brand_dim'])
            f.pack(fill='x', pady=(8, 0))
            tk.Label(f, text=title, font=(FONT, 9, 'bold'),
                      bg=G['brand_dim'],
                      fg=G['brand_dark']).pack(side='left', padx=14, pady=5)

        def row(label, value, val_col=None):
            r = tk.Frame(sv, bg=G['surface'])
            r.pack(fill='x')
            tk.Frame(r, bg=G['bdr'], height=1).pack(fill='x')
            inner = tk.Frame(r, bg=G['surface'])
            inner.pack(fill='x', padx=14, pady=7)
            tk.Label(inner, text=label, font=(FONT, 9),
                      bg=G['surface'], fg=G['muted'],
                      width=18, anchor='w').pack(side='left')
            tk.Label(inner, text=value,
                      font=(FONT, 10, 'bold'),
                      bg=G['surface'],
                      fg=val_col or G['text']).pack(side='left')

        section('Customer & Transaction')
        row('Customer', d['customer'])
        row('Contact',  d['contact'])
        row('Date',     d['date'])
        section('Milling')
        row('Kilos',    d['kilos'])
        row('Rate/kg',  d['mrate'])
        row('Gross Fee',d['gross'])
        if d['has_chaff']:
            row('Chaff kg',  d['ck'])
            row('Chaff rate',d['cr'])
            row('Deduction', d['cd'], G['danger'])
        row('Net Amount', d['net'],  G['brand_dark'])
        section('Payment')
        row('Paid',    d['paid'],    G['brand'])
        row('Balance', d['balance'],
            G['danger'] if d['balance'] != peso(0) else G['brand'])
        row('Method',  d['method'])
        if d['notes'] != '—': row('Notes', d['notes'])

        if len(d['payments']) > 1:
            section('Payment History')
            for amt, mth, ts, note in d['payments']:
                pf = tk.Frame(sv, bg=G['surface'])
                pf.pack(fill='x', padx=14, pady=4)
                tk.Label(pf, text='💰', font=(FONT, 14),
                          bg=G['surface']).pack(side='left', padx=(0, 8))
                tf2 = tk.Frame(pf, bg=G['surface'])
                tf2.pack(side='left')
                tk.Label(tf2, text=amt,
                          font=(FONT, 11, 'bold'),
                          bg=G['surface'],
                          fg=G['brand_dark']).pack(anchor='w')
                meta = f'{mth}  ·  {ts}'
                if note: meta += f'  ·  {note}'
                tk.Label(tf2, text=meta,
                          font=(FONT, 9), bg=G['surface'],
                          fg=G['muted']).pack(anchor='w')

        bf = tk.Frame(dlg, bg=G['surface'])
        bf.pack(fill='x', padx=14, pady=10)
        for lbl_t, cmd, bgc, fgc in [
            ('✏️ Edit',
             lambda: (dlg.destroy(),
                      self._open_txn_dialog(d['id'])),
             G['bdr'], G['text']),
            ('💰 Pay',
             lambda: (dlg.destroy(),
                      self._open_payment(d['id'])),
             G['brand'], '#fff'),
            ('✕ Delete',
             lambda: (dlg.destroy(),
                      self._delete_txn(d['id'])),
             G['danger'], '#fff'),
            ('Close', dlg.destroy, G['bdr'], G['text']),
        ]:
            b = tk.Button(bf, text=lbl_t, command=cmd,
                           bg=bgc, fg=fgc,
                           font=(FONT, 10, 'bold'), relief='flat', bd=0,
                           cursor='hand2', padx=12, pady=6)
            b.pack(side='left', padx=(0, 6))
            if d['status'] == 'Paid' and '💰' in lbl_t:
                b.configure(state='disabled')

    def _open_payment(self, txn_id):
        dlg = PaymentDialog(self.root, self, txn_id)
        if dlg.saved:
            self._sb('Payment recorded ✓')
            if self._current_nav == 'unpaid':
                self._load_unpaid()
            elif self._current_nav == 'records':
                self._load_records()
            elif self._current_nav == 'dashboard':
                self._nav_click('dashboard')

    def _delete_txn(self, txn_id):
        if not messagebox.askyesno(
                'Delete', 'Delete this transaction? Cannot be undone.',
                parent=self.root):
            return
        db = get_session()
        try:
            t = db.get(MillingTransaction, txn_id)
            if t: db.delete(t)
            db.commit()
            self._sb('Transaction deleted.')
            if self._current_nav in ('records', 'unpaid', 'dashboard'):
                self._nav_click(self._current_nav)
        except Exception as e:
            db.rollback()
            messagebox.showerror('Error', str(e), parent=self.root)
        finally:
            db.close()

    # ── Auth ─────────────────────────────────────────────────────────────────
    def _logout(self):
        if self._svr_running:
            if not messagebox.askyesno(
                    'Logout', 'Stop server and logout?',
                    parent=self.root): return
            self._stop_server()
        self.root.destroy()
        main()

    def _on_close(self):
        if self._svr_running:
            if messagebox.askyesno(
                    'Quit', 'Stop server and quit?',
                    parent=self.root):
                self._stop_server()
                self.root.after(400, self.root.destroy)
        else:
            self.root.destroy()


# ── ═══════════════════════════════════════════════════════════════════════════
#    ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════
_P    = sys.platform
PY_EXE = sys.executable

def main():
    _seed()
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root.withdraw()

    def _launch(uid, uname, role):
        for w in root.winfo_children(): w.destroy()
        root.configure(bg=G['bg'])
        root.deiconify()
        try:    root.state('zoomed')
        except Exception:
            try: root.attributes('-zoomed', True)
            except Exception: root.geometry('1120x700')
        PalayKitaApp(root, uid, uname, role)

    LoginWindow(root, on_success=_launch)
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f'420x500+{(sw-420)//2}+{(sh-500)//2}')
    root.deiconify()
    root.mainloop()


if __name__ == '__main__':
    main()
