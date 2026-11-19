import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import sqlite3
import shutil
import json
from pathlib import Path
from datetime import datetime
import hashlib
import secrets
import string
import html
import webbrowser

import sys
import os

# Resource files are bundled by PyInstaller under _MEIPASS in one-file mode.
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

# In a frozen EXE, never put the database beside temporary extracted resources:
# use a stable, writable per-user directory so data survives app restarts.
if getattr(sys, "frozen", False):
    APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OmidAyandeh"
    APP_DIR.mkdir(parents=True, exist_ok=True)
else:
    APP_DIR = Path(__file__).resolve().parent

DB_PATH = APP_DIR / "bank_manager.db"

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return salt, digest.hex()


def normalize_national_id(value):
    """یکسان‌سازی کد ملی برای جلوگیری از ثبت تکراری با ارقام فارسی/عربی یا فاصله."""
    value = (value or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    return "".join(ch for ch in value if not ch.isspace() and ch not in "-‐‑")

class BankManager:
    def __init__(self, root):
        self.root = root
        self.root.title("سامانه مدیریت بانکی رویال")
        self.root.geometry("1180x740")
        self.root.minsize(900, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.confirm_exit)
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.setup_db()
        self.root.geometry(self.get_setting("window_size", "1180x740"))
        self.ui_font = self.get_setting("ui_font", "IRANSans")
        # نمایش قرمز اطلاعات جدولی؛ شماره حساب‌ها در تمام جدول‌های برنامه برجسته می‌شوند.
        self.ttk_style = ttk.Style(self.root)
        self.ttk_style.configure("Treeview", foreground="#c00000")
        # Use a modern Persian typeface on login when installed; gracefully fall back on Windows.
        try:
            available_fonts = set(self.root.tk.call("font", "families"))
            self.login_font = next((name for name in ("IRANSans", "Iran Sans", "IRAN Sans", "Vazirmatn", "Segoe UI", self.ui_font, "Tahoma")
                                   if name in available_fonts), self.ui_font)
        except tk.TclError:
            self.login_font = self.ui_font
        self.selected_theme = self.get_setting("ui_theme", "آبی سازمانی")
        self.style()
        self.set_theme(self.selected_theme)
        self.apply_font(self.ui_font)
        self.current_user = None
        self.show_login()

    def format_money_entry(self, entry):
        """نمایش جداکننده سه‌رقمی و رنگ سبز برای ورودی‌های مبلغ."""
        entry.configure(foreground="#16803c")
        def reformat(_event=None):
            try:
                raw = entry.get()
                cursor = entry.index(tk.INSERT)
                before = raw[:cursor]
                digits_before = sum(ch.isdigit() for ch in before)
                normalized = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
                normalized = normalized.replace(",", "").replace("٬", "").replace(" ", "")
                if not normalized:
                    return
                # نگهداری بخش اعشاری در صورت ورود ممیز
                sign = "-" if normalized.startswith("-") else ""
                normalized = normalized.lstrip("-")
                if normalized.count(".") > 1:
                    normalized = normalized.replace(".", "")
                if "." in normalized:
                    integer, decimal = normalized.split(".", 1)
                    decimal = "".join(ch for ch in decimal if ch.isdigit())
                else:
                    integer, decimal = normalized, None
                integer = "".join(ch for ch in integer if ch.isdigit())
                grouped = f"{int(integer):,}" if integer else ""
                formatted = sign + grouped + (("." + decimal) if decimal is not None else "")
                if formatted != raw:
                    entry.delete(0, tk.END)
                    entry.insert(0, formatted)
                    pos = 0
                    count = 0
                    while pos < len(formatted) and count < digits_before:
                        if formatted[pos].isdigit(): count += 1
                        pos += 1
                    entry.icursor(pos)
            except (ValueError, tk.TclError):
                pass
        entry.bind("<KeyRelease>", reformat, add="+")
        entry.bind("<FocusOut>", reformat, add="+")
        return entry

    def confirm_exit(self):
        """Ask whether to back up data before closing the application."""
        choice = messagebox.askyesnocancel(
            "خروج از برنامه",
            "آیا پیش از خروج، از اطلاعات برنامه نسخه پشتیبان تهیه شود؟\n\nبله: پشتیبان‌گیری و خروج\nخیر: خروج بدون پشتیبان‌گیری\nلغو: بازگشت به برنامه",
            parent=self.root
        )
        if choice is None:
            return
        if choice:
            try:
                self.conn.commit()
                backup_dir = APP_DIR / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_path = backup_dir / f"royal_bank_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                target = sqlite3.connect(str(backup_path))
                self.conn.backup(target)
                target.close()
                messagebox.showinfo("پشتیبان‌گیری موفق", f"نسخه پشتیبان ذخیره شد:\n{backup_path}", parent=self.root)
            except Exception as exc:
                if not messagebox.askyesno("خطا در پشتیبان‌گیری", f"پشتیبان‌گیری انجام نشد:\n{exc}\n\nبدون پشتیبان‌گیری خارج شوید؟", parent=self.root):
                    return
        try:
            self.conn.close()
        finally:
            self.root.destroy()

    def setup_db(self):
        cur = self.conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, salt TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'کارمند',
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS accounts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_no TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL, national_id TEXT, phone TEXT, account_type TEXT NOT NULL,
            balance REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'فعال',
            created_at TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_no TEXT NOT NULL,
            kind TEXT NOT NULL, amount REAL NOT NULL, description TEXT,
            created_at TEXT NOT NULL, created_by TEXT NOT NULL)""")
        transaction_columns = {row[1] for row in cur.execute("PRAGMA table_info(transactions)").fetchall()}
        if "document_no" not in transaction_columns:
            cur.execute("ALTER TABLE transactions ADD COLUMN document_no TEXT")
        # رکوردهای قدیمی: شماره سند قبلی همان شناسه تراکنش است.
        cur.execute("UPDATE transactions SET document_no=CAST(id AS TEXT) WHERE document_no IS NULL OR document_no=''")

        cur.execute("""CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS cards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_no TEXT UNIQUE NOT NULL,
            account_no TEXT NOT NULL,
            card_type TEXT NOT NULL DEFAULT 'نقدی',
            status TEXT NOT NULL DEFAULT 'فعال',
            requested_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            expiry_date TEXT)""")
        # سازگاری با پایگاه‌داده‌های قدیمی: ستون‌های رمز کارت را بدون حذف اطلاعات اضافه کن.
        card_columns = {row[1] for row in cur.execute("PRAGMA table_info(cards)").fetchall()}
        if "pin_hash" not in card_columns:
            cur.execute("ALTER TABLE cards ADD COLUMN pin_hash TEXT")
        if "pin_salt" not in card_columns:
            cur.execute("ALTER TABLE cards ADD COLUMN pin_salt TEXT")
        if "failed_attempts" not in card_columns:
            cur.execute("ALTER TABLE cards ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0")

        cur.execute("""CREATE TABLE IF NOT EXISTS funds(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_name TEXT NOT NULL UNIQUE,
            balance REAL NOT NULL DEFAULT 0,
            description TEXT,
            created_at TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS checks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_no TEXT NOT NULL UNIQUE,
            account_no TEXT NOT NULL,
            beneficiary TEXT NOT NULL,
            amount REAL NOT NULL,
            issue_date TEXT,
            due_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'در انتظار',
            notes TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS card_pin_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_no TEXT NOT NULL,
            account_no TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'در انتظار بررسی',
            requested_at TEXT NOT NULL,
            requested_by TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS loans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_no TEXT NOT NULL,
            principal REAL NOT NULL,
            remaining REAL NOT NULL,
            monthly_payment REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'فعال',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            notes TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS loans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_no TEXT NOT NULL,
            principal REAL NOT NULL,
            outstanding REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'فعال',
            created_at TEXT NOT NULL,
            description TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS account_raffles(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            prize TEXT NOT NULL,
            winner_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS account_raffle_winners(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raffle_id INTEGER NOT NULL,
            account_no TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(raffle_id) REFERENCES account_raffles(id))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS sim_recharges(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            carrier TEXT NOT NULL,
            amount REAL NOT NULL,
            recharge_type TEXT NOT NULL DEFAULT 'شارژ مستقیم',
            recharge_code TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            notes TEXT)""")
        # سازگاری با پایگاه‌داده‌های ساخته‌شده در نسخه‌های قبلی
        recharge_columns = {row[1] for row in cur.execute("PRAGMA table_info(sim_recharges)").fetchall()}
        if "recharge_code" not in recharge_columns:
            cur.execute("ALTER TABLE sim_recharges ADD COLUMN recharge_code TEXT")
        card_columns = {row[1] for row in cur.execute("PRAGMA table_info(cards)").fetchall()}
        if "expiry_date" not in card_columns:
            cur.execute("ALTER TABLE cards ADD COLUMN expiry_date TEXT")
        loan_columns = {row[1] for row in cur.execute("PRAGMA table_info(loans)").fetchall()}
        for column, declaration in (("remaining", "REAL NOT NULL DEFAULT 0"),
                                    ("monthly_payment", "REAL NOT NULL DEFAULT 0"),
                                    ("duration_months", "INTEGER NOT NULL DEFAULT 0"),
                                    ("installment_count", "INTEGER NOT NULL DEFAULT 0"),
                                    ("created_by", "TEXT NOT NULL DEFAULT ''"),
                                    ("notes", "TEXT"),
                                    ("interest_rate", "REAL NOT NULL DEFAULT 0.0")):
            if column not in loan_columns:
                cur.execute(f"ALTER TABLE loans ADD COLUMN {column} {declaration}")
        loan_columns = {row[1] for row in cur.execute("PRAGMA table_info(loans)").fetchall()}
        if "outstanding" in loan_columns:
            cur.execute("UPDATE loans SET remaining=outstanding WHERE remaining=0 AND outstanding>0")
        # یکسان‌سازی کدهای ملی قدیمی (ارقام فارسی/عربی، فاصله و خط تیره).
        existing_accounts = cur.execute("SELECT account_no, national_id FROM accounts WHERE national_id IS NOT NULL").fetchall()
        for account_row in existing_accounts:
            normalized = normalize_national_id(account_row["national_id"])
            if normalized != account_row["national_id"]:
                cur.execute("UPDATE accounts SET national_id=? WHERE account_no=?", (normalized or None, account_row["account_no"]))
        # تریگرهای پایگاه داده کدهای ملی را با ارقام فارسی/عربی و فاصله‌های متفاوت مقایسه می‌کنند.
        def sql_nid_expr(expr):
            for src, dst in zip("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"):
                expr = f"REPLACE({expr},'{src}','{dst}')"
            for char in (" ", "-", "‐", "‑"):
                expr = f"REPLACE({expr},'{char}','')"
            return expr
        old_nid_expr = sql_nid_expr("TRIM(a.national_id)")
        new_nid_expr = sql_nid_expr("TRIM(NEW.national_id)")
        cur.execute("DROP TRIGGER IF EXISTS trg_accounts_nid_unique_insert")
        cur.execute("DROP TRIGGER IF EXISTS trg_accounts_nid_unique_update")
        cur.execute(f"""CREATE TRIGGER trg_accounts_nid_unique_insert
            BEFORE INSERT ON accounts WHEN NEW.national_id IS NOT NULL AND TRIM(NEW.national_id)<>''
            BEGIN
              SELECT CASE WHEN EXISTS(SELECT 1 FROM accounts a
                WHERE a.national_id IS NOT NULL AND TRIM(a.national_id)<>''
                AND {old_nid_expr} = {new_nid_expr})
                THEN RAISE(ABORT, 'کد ملی تکراری است') END;
            END""")
        cur.execute(f"""CREATE TRIGGER trg_accounts_nid_unique_update
            BEFORE UPDATE OF national_id ON accounts WHEN NEW.national_id IS NOT NULL AND TRIM(NEW.national_id)<>''
            BEGIN
              SELECT CASE WHEN EXISTS(SELECT 1 FROM accounts a WHERE a.account_no<>NEW.account_no
                AND a.national_id IS NOT NULL AND TRIM(a.national_id)<>''
                AND {old_nid_expr} = {new_nid_expr})
                THEN RAISE(ABORT, 'کد ملی تکراری است') END;
            END""")
        duplicate_nid = cur.execute("""SELECT 1 FROM accounts WHERE national_id IS NOT NULL AND TRIM(national_id)<>''
            GROUP BY national_id HAVING COUNT(*)>1 LIMIT 1""").fetchone()
        if not duplicate_nid:
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_national_id_unique ON accounts(national_id) WHERE national_id IS NOT NULL AND TRIM(national_id)<>''")
        if not cur.execute("SELECT id FROM users LIMIT 1").fetchone():
            salt, digest = hash_password("Admin123!")
            cur.execute("INSERT INTO users(username,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,1,?)",
                        ("admin", digest, salt, "مدیر", datetime.now().isoformat(timespec="seconds")))
        self.conn.commit()

    def get_setting(self, key, default=""):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def save_setting(self, key, value):
        self.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.conn.commit()

    def apply_font(self, font_name=None):
        if font_name:
            self.ui_font = font_name
        size = int(self.get_setting("ui_font_size", "10"))
        density = self.get_setting("layout_density", "استاندارد")
        compact = density == "جمع‌وجور"
        roomy = density == "درشت و خوانا"
        st = ttk.Style()
        # دکمه‌های یکدست، کم‌ارتفاع‌تر و جمع‌وجورتر در تمام بخش‌ها
        button_size = max(8, size - 1)
        button_padding = (4, 2) if compact else ((9, 6) if roomy else (6, 3))
        st.configure("TButton", font=(self.ui_font, button_size), padding=button_padding)
        st.configure("TButton", anchor="center")
        st.map("TButton", relief=[("pressed", "sunken"), ("active", "raised")])
        st.configure("TLabel", font=(self.ui_font, size))
        st.configure("Title.TLabel", font=(self.ui_font, size + 10, "bold"))
        row_height = size * (2 if compact else (3 if roomy else 2.6))
        st.configure("Treeview", font=(self.ui_font, size), rowheight=int(row_height))
        st.configure("Treeview.Heading", font=(self.ui_font, size, "bold"))
        st.configure("AccountNumber.TLabel", foreground="#d62828")
        st.configure("CardNumber.TLabel", foreground="#d62828")
        st.configure("TLabelframe.Label", font=(self.ui_font, size + 1, "bold"))
        self.save_setting("ui_font", self.ui_font)

    def set_theme(self, theme_name, show_message=False):
        palettes = {
            "آبی سازمانی": ("#16324f", "#eef2f7", "#e7f3ff"), "سبز امید": ("#145744", "#edf7f1", "#d9f2e5"),
            "بنفش مدرن": ("#503778", "#f3eff9", "#e9e0f7"), "فیروزه‌ای": ("#087e8b", "#eaf8f8", "#d0f0ef"),
            "زرشکی": ("#842d46", "#fbf0f3", "#f4dce4"), "نارنجی گرم": ("#a84b12", "#fff5eb", "#ffe3c7"),
            "ذغالی تیره": ("#303640", "#e9edf1", "#d5dbe2"), "صورتی ملایم": ("#a33c72", "#fff0f6", "#f9dce9"),
            "اقیانوسی": ("#145b8c", "#edf6fc", "#d8ebfa"), "طلایی کلاسیک": ("#80621a", "#fbf7e9", "#f2e7bf"),
            "قرمز یاقوتی": ("#9b1c31", "#fff0f1", "#f8dadd"), "سبز زمردی": ("#087f5b", "#edf9f3", "#d2f2e4"),
            "آبی آسمانی": ("#1769aa", "#eff8ff", "#d7edff"), "نیلی شب": ("#3730a3", "#eef2ff", "#dfe3ff"),
            "نعنایی": ("#287d68", "#effbf6", "#d5f5e8"), "مرجانی": ("#c2413b", "#fff3ef", "#ffddd4"),
            "قهوه‌ای شکلاتی": ("#70452a", "#f8f1eb", "#ead8c8"), "لیمویی": ("#687a12", "#fbfce9", "#edf2c4"),
            "لاجوردی": ("#2447a8", "#eff3ff", "#dce5ff"), "خاکستری نقره‌ای": ("#596579", "#f1f4f8", "#dfe5ec"),
            "سبز زیتونی": ("#626b24", "#f7f8ed", "#e8ebcf"), "بنفش اسطوخودوسی": ("#7654a6", "#f7f2ff", "#e9dcff"),
            "آبی یخی": ("#277da1", "#f0fbff", "#d7f3fb"), "رزگلد": ("#a45b68", "#fff4f4", "#f6dce0"),
            "سبز جنگلی": ("#285943", "#eef6ef", "#d5e8d8"),
            "Office 2007": ("#1f497d", "#f3f6fb", "#dbe8f7"),
            "Windows 7": ("#245b83", "#edf4fa", "#d6e8f7"),
            "Longhorn": ("#365f91", "#eaf0f8", "#d3e0f2"),
            "Office Black": ("#f2f2f2", "#202020", "#383838"),
            "مشکی مات": ("#f0f0f0", "#171717", "#303030"),
            "مشکی و نقره‌ای": ("#eeeeee", "#242424", "#454545"),
            "سرمه‌ای کلاسیک": ("#182848", "#f0f3f8", "#dce5f3"), "سبز یشمی": ("#176b55", "#edf8f3", "#d1eee2"),
            "بنفش سلطنتی": ("#5b2c83", "#f7f0fc", "#e9d9f5"), "خاکستری مدرن": ("#424b57", "#f3f5f7", "#e1e6eb"),
            "آبی نفتی": ("#155e75", "#eff9fb", "#d2edf2"), "سبز پسته‌ای": ("#557c35", "#f4f8ed", "#e2edcf")
        }
        primary, background, accent = palettes.get(theme_name, palettes["آبی سازمانی"])
        self.selected_theme = theme_name if theme_name in palettes else "آبی سازمانی"
        self.root.configure(bg=background)
        st = ttk.Style()
        st.configure("TLabel", background=background, foreground=primary, font=(self.ui_font, int(self.get_setting("ui_font_size", "10"))))
        st.configure("Title.TLabel", foreground=primary, background=background, font=(self.ui_font, int(self.get_setting("ui_font_size", "10"))+10, "bold"))
        st.configure("TFrame", background=background)
        st.configure("TLabelframe", background=background)
        st.configure("TLabelframe.Label", background=background, foreground=primary, font=(self.ui_font, int(self.get_setting("ui_font_size", "10"))+1, "bold"))
        st.configure("TButton", font=(self.ui_font, int(self.get_setting("ui_font_size", "10"))), padding=7, background=accent, foreground=primary)
        st.map("TButton", background=[("active", primary), ("pressed", primary)], foreground=[("active", "white"), ("pressed", "white")])
        dark_theme = theme_name in ("Office Black", "مشکی مات", "مشکی و نقره‌ای")
        field_bg = "#292929" if dark_theme else "white"
        field_fg = "#f4f4f4" if dark_theme else "#202938"
        tree_bg = "#242424" if dark_theme else "white"
        tree_fg = "#eeeeee" if dark_theme else "#202938"
        st.configure("TEntry", fieldbackground=field_bg, foreground=field_fg, insertcolor=field_fg)
        st.configure("TCombobox", fieldbackground=field_bg, foreground=field_fg)
        st.map("TCombobox", fieldbackground=[("readonly", field_bg)], foreground=[("readonly", field_fg)])
        st.configure("Treeview", background=tree_bg, fieldbackground=tree_bg, foreground=tree_fg, font=(self.ui_font, int(self.get_setting("ui_font_size", "10"))), rowheight=int(self.get_setting("ui_font_size", "10")))
        st.configure("Treeview.Heading", background=primary, foreground="white", font=(self.ui_font, int(self.get_setting("ui_font_size", "10")), "bold"))
        st.map("Treeview", background=[("selected", primary)], foreground=[("selected", "white")])
        st.map("Treeview.Heading", background=[("active", primary)])
        self.save_setting("ui_theme", self.selected_theme)
        if show_message:
            messagebox.showinfo("تم برنامه", f"پوسته «{self.selected_theme}» اعمال شد.")

    def overdue_installments(self):
        """محاسبه اقساط سررسیدشده با توجه به ماه‌های سپری‌شده و پرداخت‌های ثبت‌شده."""
        today = datetime.now().date()
        result = []
        loans = self.conn.execute("SELECT id,account_no,principal,remaining,monthly_payment,installment_count,created_at,status FROM loans WHERE status='فعال' AND remaining>0").fetchall()
        for loan in loans:
            try:
                created = datetime.fromisoformat(loan["created_at"][:19]).date()
            except (ValueError, TypeError):
                continue
            months = (today.year-created.year)*12 + today.month-created.month
            if today.day < created.day:
                months -= 1
            due_count = max(0, min(int(loan["installment_count"] or 0), months))
            if due_count <= 0:
                continue
            paid_row = self.conn.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_no=? AND kind='پرداخت قسط وام' AND description LIKE ?", (loan["account_no"], f"%{loan['id']}%")).fetchone()
            paid = float(paid_row[0] or 0)
            expected = min(float(loan["principal"]), due_count * float(loan["monthly_payment"] or 0))
            overdue_amount = max(0, expected-paid)
            if overdue_amount > 0:
                result.append({"id":loan["id"], "account_no":loan["account_no"], "due_count":due_count, "monthly":float(loan["monthly_payment"] or 0), "overdue":overdue_amount, "created":created.isoformat()})
        return result

    def show_overdue_installments(self):
        self.panel("یادآوری اقساط معوقه")
        rows = self.overdue_installments()
        summary = ttk.Label(self.content, text=f"تعداد وام‌های دارای قسط معوق: {len(rows)} | مجموع مبلغ معوق: {sum(r['overdue'] for r in rows):,.0f} تومان")
        summary.pack(anchor="e", pady=(0,8))
        cols=("id","account","due","monthly","amount","created")
        tree=ttk.Treeview(self.content, columns=cols, show="headings", height=14)
        tree.tag_configure("number_red", foreground="#d62828")
        for c, h, w in zip(cols, ("شناسه وام","شماره حساب","اقساط سررسیدشده","مبلغ هر قسط","مبلغ معوق","تاریخ ثبت وام"), (90,140,130,140,150,140)):
            tree.heading(c,text=h); tree.column(c,width=w,anchor="center")
        tree.pack(fill="both",expand=True)
        for r in rows:
            try:
                created_dt = datetime.fromisoformat(r["created"])
                cy, cm, cd = self.jalali_date(created_dt)
                created_display = f"{cy:04d}/{cm:02d}/{cd:02d}"
            except Exception:
                created_display = r["created"]
            tree.insert("","end",values=(r["id"],r["account_no"],r["due_count"],f"{r['monthly']:,.0f}",f"{r['overdue']:,.0f}",created_display), tags=("number_red",))
        ttk.Button(self.content,text="به‌روزرسانی یادآوری",command=self.show_overdue_installments).pack(anchor="e",pady=8)

    def set_background(self):
        """پس‌زمینه تزئینی در لایه زیرین؛ کنترل‌ها در لایه بالایی باقی می‌مانند."""
        image_path = RESOURCE_DIR / "app_background.png"
        if not image_path.exists():
            return
        try:
            image = tk.PhotoImage(file=str(image_path))
            width = max(self.root.winfo_width(), 980)
            height = max(self.root.winfo_height(), 620)
            factor = max(1, (image.width() + width - 1) // width,
                         (image.height() + height - 1) // height)
            image = image.subsample(factor, factor)
            self._background_image = image
            self._background_label = tk.Label(
                self.root, image=image, bd=0, highlightthickness=0
            )
            self._background_label.place(x=0, y=0, relwidth=1, relheight=1)
            self._background_label.lower()
        except (tk.TclError, OSError):
            pass

    def style(self):
        self.root.configure(bg="#eef2f7")
        s = ttk.Style()
        try: s.theme_use("clam")
        except tk.TclError: pass
        s.configure("TButton", font=("IRANSans", 10), padding=7,
                    background="#e8edf3", foreground="#16324f")
        s.map("TButton",
              background=[("active", "#cfe3f8"), ("pressed", "#b7d5f2")],
              foreground=[("disabled", "#777777"), ("!disabled", "#16324f")])
        s.configure("TLabel", font=("IRANSans", 10), background="#eef2f7",
                    foreground="#16324f")
        s.configure("TFrame", background="#eef2f7")
        s.configure("TLabelframe", background="#eef2f7")
        s.configure("TLabelframe.Label", background="#eef2f7", foreground="#16324f")
        s.configure("Title.TLabel", font=("IRANSans", 20, "bold"), foreground="#16324f")
        s.configure("Treeview", font=("IRANSans", 10), rowheight=29)
        s.configure("Treeview.Heading", font=("Tahoma", 10, "bold"))
        s.configure("TLabelframe.Label", font=("Tahoma", 11, "bold"))

    def clear(self):
        for w in self.root.winfo_children(): w.destroy()

    def show_login(self):
        """صفحه ورود مرتب، واکنش‌گرا و راست‌چین."""
        self.clear()
        self.root.configure(bg="#edf3f8")

        # کارت ورود با عرض محدود؛ در پنجره‌های کوچک نیز اجزا روی هم نمی‌افتند.
        shell = tk.Frame(self.root, bg="#edf3f8")
        shell.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.92, relheight=0.90)

        card = tk.Frame(shell, bg="white", highlightbackground="#d7e2ec",
                        highlightthickness=1, bd=0)
        card.place(relx=0.5, rely=0.5, anchor="center", width=500, relheight=0.94)

        # سربرگ برند
        hero = tk.Frame(card, bg="#123b5d", padx=28, pady=20)
        hero.pack(fill="x")
        tk.Label(hero, text="✦", bg="#123b5d", fg="#62d6c7",
                 font=(self.login_font, 25, "bold")).pack(anchor="center")
        tk.Label(hero, text="رویال بانک", bg="#123b5d", fg="white",
                 font=(self.login_font, 22, "bold"), anchor="center",
                 justify="center").pack(fill="x", pady=(3, 2))
        tk.Label(hero, text="سامانه مدیریت بانکی رویال", bg="#123b5d",
                 fg="#c6e5f2", font=(self.login_font, 11),
                 anchor="center", justify="center").pack(fill="x")

        # فرم ورود
        form = tk.Frame(card, bg="white", padx=38, pady=22)
        form.pack(fill="both", expand=True)
        tk.Label(form, text="خوش آمدید", bg="white", fg="#173b58",
                 font=(self.login_font, 19, "bold"), anchor="e",
                 justify="right").pack(fill="x", pady=(0, 5))
        tk.Label(form, text="برای ادامه، وارد حساب کاربری خود شوید.",
                 bg="white", fg="#718397", font=(self.login_font, 10),
                 anchor="e", justify="right").pack(fill="x", pady=(0, 20))

        tk.Label(form, text="نام کاربری", bg="white", fg="#29445b",
                 font=(self.login_font, 10, "bold"), anchor="e",
                 justify="right").pack(fill="x", pady=(0, 6))
        self.login_user = tk.Entry(form, font=(self.login_font, 12),
                                   justify="right", relief="flat", bd=0,
                                   bg="#f2f6fa", fg="#19364f",
                                   insertbackground="#19364f")
        self.login_user.pack(fill="x", ipady=9, pady=(0, 14))
        self.login_user.configure(highlightthickness=1,
                                  highlightbackground="#dce6ef",
                                  highlightcolor="#27a99b")

        tk.Label(form, text="رمز عبور", bg="white", fg="#29445b",
                 font=(self.login_font, 10, "bold"), anchor="e",
                 justify="right").pack(fill="x", pady=(0, 6))
        self.login_pass = tk.Entry(form, font=(self.login_font, 12),
                                   show="●", justify="right", relief="flat",
                                   bd=0, bg="#f2f6fa", fg="#19364f",
                                   insertbackground="#19364f")
        self.login_pass.pack(fill="x", ipady=9, pady=(0, 18))
        self.login_pass.configure(highlightthickness=1,
                                  highlightbackground="#dce6ef",
                                  highlightcolor="#27a99b")

        login_btn = tk.Button(
            form, text="ورود به سامانه", command=self.login,
            bg="#0e9488", activebackground="#08796f", fg="white",
            activeforeground="white", relief="flat", bd=0,
            font=(self.login_font, 12, "bold"), cursor="hand2", pady=10
        )
        login_btn.pack(fill="x", pady=(0, 8))
        tk.Button(
            form, text="اتصال رمز مدیریت به رمز کارت مدیر",
            command=self.bind_admin_card, bg="#eaf2f8", fg="#29445b",
            activebackground="#dceaf3", relief="flat",
            font=(self.login_font, 10, "bold"), cursor="hand2", pady=7
        ).pack(fill="x", pady=(0, 10))
        login_btn.bind("<Enter>", lambda e: login_btn.configure(bg="#08796f"))
        login_btn.bind("<Leave>", lambda e: login_btn.configure(bg="#0e9488"))

        tk.Label(form, text="محیط امن مدیریت حساب‌ها و تسهیلات",
                 bg="white", fg="#93a2b1", font=(self.login_font, 8),
                 anchor="center", justify="center").pack(side="bottom",
                                                         fill="x", pady=(8, 0))
        self.login_pass.bind("<Return>", lambda e: self.login())
        self.login_user.bind("<Return>", lambda e: self.login_pass.focus_set())
        self.login_user.focus_set()

    def bind_admin_card(self):
        """Bind the manager login to one active ATM card PIN (one-time setup)."""
        existing = self.get_setting("admin_card_no", "")
        if existing:
            messagebox.showinfo("کارت مدیر ثبت شده",
                "کارت مدیر قبلاً تعیین شده است. برای جلوگیری از تغییر غیرمجاز، ثبت مجدد از داخل صفحه ورود غیرفعال است.")
            return
        card_no = simpledialog.askstring("تعیین کارت مدیر", "شماره کارت مدیر را وارد کنید:", parent=self.root)
        if not card_no:
            return
        pin = simpledialog.askstring("تأیید کارت مدیر", "رمز فعلی همین کارت را وارد کنید:", show="*", parent=self.root)
        if pin is None:
            return
        card = self.conn.execute(
            "SELECT card_no,pin_hash,pin_salt,status FROM cards WHERE card_no=?",
            (card_no.strip(),)
        ).fetchone()
        if not card or card["status"] != "فعال" or not card["pin_hash"] or not card["pin_salt"]:
            messagebox.showerror("کارت نامعتبر", "کارت فعال با رمز تعریف‌شده پیدا نشد.")
            return
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"),
                                     card["pin_salt"].encode("utf-8"), 200_000).hex()
        if not secrets.compare_digest(digest, card["pin_hash"]):
            messagebox.showerror("تأیید ناموفق", "رمز کارت صحیح نیست؛ اتصال انجام نشد.")
            return
        self.save_setting("admin_card_no", card["card_no"])
        messagebox.showinfo("اتصال انجام شد",
            "از این پس مدیر بانک برای ورود به مدیریت بانک باید از رمز همین کارت استفاده کند. تغییر رمز کارت در خودپرداز نیز به‌طور خودکار در ورود مدیریت اعمال می‌شود.")

    def login(self):
        username, password = self.login_user.get().strip(), self.login_pass.get()
        row = self.conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if not row:
            messagebox.showerror("خطا", "نام کاربری یا رمز عبور اشتباه است.")
            return
        if row["role"] == "مدیر" and self.get_setting("admin_card_no", ""):
            admin_card_no = self.get_setting("admin_card_no", "")
            card = self.conn.execute(
                "SELECT pin_hash,pin_salt,status FROM cards WHERE card_no=?",
                (admin_card_no,)
            ).fetchone()
            if not card or card["status"] != "فعال" or not card["pin_hash"] or not card["pin_salt"]:
                messagebox.showerror("خطا", "کارت مدیر فعال یا دارای رمز معتبر نیست.")
                return
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                         card["pin_salt"].encode("utf-8"), 200_000).hex()
            valid = secrets.compare_digest(digest, card["pin_hash"])
        else:
            salt, digest = hash_password(password, row["salt"])
            valid = secrets.compare_digest(digest, row["password_hash"])
        if not valid:
            messagebox.showerror("خطا", "نام کاربری یا رمز عبور اشتباه است.")
            return
        self.current_user = dict(row)
        self.show_main()

    @staticmethod
    def jalali_date(gdate):
        """Convert Gregorian date to Jalali without third-party packages."""
        gy, gm, gd = gdate.year, gdate.month, gdate.day
        gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
        gy2 = gy + 1 if gm > 2 else gy
        days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + gdm[gm - 1]
        jy = -1595 + 33 * (days // 12053)
        days %= 12053
        jy += 4 * (days // 1461)
        days %= 1461
        if days > 365:
            jy += (days - 1) // 365
            days = (days - 1) % 365
        if days < 186:
            jm = 1 + days // 31
            jd = 1 + days % 31
        else:
            jm = 7 + (days - 186) // 30
            jd = 1 + (days - 186) % 30
        return jy, jm, jd

    def update_clock(self):
        if not hasattr(self, "clock_label") or not self.clock_label.winfo_exists():
            return
        now = datetime.now()
        jy, jm, jd = self.jalali_date(now)
        weekdays = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
        weekday = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"][now.weekday()]
        self.clock_label.config(text=f"امروز: {weekday}  {jy:04d}/{jm:02d}/{jd:02d}     |     ساعت: {now.strftime('%H:%M:%S')}")
        self.root.after(1000, self.update_clock)

    def draw_analog_clock(self, canvas, size=150):
        """رسم و به‌روزرسانی ساعت آنالوگ با زمان محلی سیستم."""
        import math
        from datetime import datetime

        canvas.delete("all")
        cx = cy = size // 2
        radius = size // 2 - 8
        canvas.create_oval(cx-radius, cy-radius, cx+radius, cy+radius,
                           fill="#f8fbff", outline="#2877b9", width=3)
        for number in range(1, 13):
            angle = math.radians(number * 30 - 90)
            x = cx + radius * 0.78 * math.cos(angle)
            y = cy + radius * 0.78 * math.sin(angle)
            canvas.create_text(x, y, text=str(number), fill="#16324f",
                               font=("Tahoma", max(8, size//18), "bold"))
        now = datetime.now()
        # زاویه‌ها از جهت ساعت ۱۲ محاسبه می‌شوند.
        seconds = now.second + now.microsecond / 1_000_000
        minutes = now.minute + seconds / 60
        hours = (now.hour % 12) + minutes / 60

        def hand(value, units, length, width, color):
            angle = math.radians(value * 360 / units - 90)
            x = cx + length * math.cos(angle)
            y = cy + length * math.sin(angle)
            canvas.create_line(cx, cy, x, y, fill=color, width=width,
                               capstyle=tk.ROUND)

        hand(hours, 12, radius * 0.48, 5, "#16324f")
        hand(minutes, 60, radius * 0.68, 3, "#1878bd")
        hand(seconds, 60, radius * 0.76, 1, "#e24b4b")
        canvas.create_oval(cx-4, cy-4, cx+4, cy+4, fill="#e24b4b", outline="")
        self.root.after(250, lambda: self.draw_analog_clock(canvas, size))

    FEE_SERVICES = {
        "واریز وجه": "deposit", "برداشت وجه": "withdraw", "انتقال وجه": "transfer",
        "واریز سود سپرده": "interest", "پرداخت اقساط": "installment", "پرداخت تسهیلات": "loan"
    }

    def fee_config(self):
        try:
            return json.loads(self.get_setting("royal_fee_config", "{}"))
        except Exception:
            return {}

    def calculate_fee(self, service, amount, parent=None):
        cfg = self.fee_config().get(service, {})
        mode = cfg.get("mode", "fixed")
        value = float(cfg.get("value", 0) or 0)
        if mode == "percent":
            fee = float(amount) * value / 100.0
        elif mode == "manual":
            raw = simpledialog.askstring("کارمزد تراکنش", f"کارمزد {service} را به تومان وارد کنید:", parent=parent or self.root)
            if raw is None:
                raise ValueError("عملیات توسط کاربر لغو شد.")
            fee = float(raw.replace(",", "").strip())
        else:
            fee = value
        if fee < 0:
            raise ValueError("کارمزد نمی‌تواند منفی باشد.")
        return round(fee, 2)

    def credit_fee_fund(self, account_no, service, fee, now):
        fee = float(fee or 0)
        if fee <= 0:
            return
        row = self.conn.execute("SELECT id FROM funds WHERE fund_name='صندوق اصلی' ORDER BY id LIMIT 1").fetchone()
        if row:
            self.conn.execute("UPDATE funds SET balance=balance+?,description=? WHERE id=?", (fee, f"کارمزد {service}", row["id"]))
        else:
            self.conn.execute("INSERT INTO funds(fund_name,balance,description,created_at) VALUES(?,?,?,?)", ("صندوق اصلی", fee, f"کارمزد {service}", now))
        self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                          (account_no, "کارمزد کسرشده", -fee, f"کارمزد {service}؛ واریز به صندوق اصلی", now, self.current_user["username"]))

    def fee_settings(self):
        win = tk.Toplevel(self.root)
        win.title("تنظیم کارمزد خدمات")
        win.geometry("760x470")
        win.transient(self.root); win.grab_set()
        frame = ttk.Frame(win, padding=12); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="تنظیم مستقل کارمزد هر خدمت", font=(self.ui_font, 14, "bold")).pack(anchor="e", pady=(0, 8))
        ttk.Label(frame, text="برای هر خدمت یکی از روش‌های ثابت، درصدی یا دستی را انتخاب کنید. مبالغ به تومان هستند.").pack(anchor="e", pady=(0, 10))
        grid = ttk.Frame(frame); grid.pack(fill="both", expand=True)
        headers = ("خدمت", "روش محاسبه", "مقدار (تومان / درصد)")
        for col, title in enumerate(headers): ttk.Label(grid, text=title).grid(row=0, column=col, padx=8, pady=5, sticky="e")
        config = self.fee_config(); controls = {}
        for idx, service in enumerate(self.FEE_SERVICES, 1):
            cfg = config.get(service, {})
            mode = tk.StringVar(value=cfg.get("mode", "fixed"))
            value = tk.StringVar(value=str(cfg.get("value", 0)))
            ttk.Label(grid, text=service).grid(row=idx, column=0, padx=8, pady=5, sticky="e")
            combo = ttk.Combobox(grid, textvariable=mode, values=("fixed", "percent", "manual"), state="readonly", width=14)
            combo.grid(row=idx, column=1, padx=8, pady=5)
            # برچسب فارسی روش‌ها با حفظ مقادیر داخلی
            combo.configure(values=("ثابت", "درصدی", "دستی"))
            mode.set({"fixed":"ثابت", "percent":"درصدی", "manual":"دستی"}.get(mode.get(), "ثابت"))
            entry = ttk.Entry(grid, textvariable=value, width=20, justify="center")
            entry.grid(row=idx, column=2, padx=8, pady=5)
            controls[service] = (mode, value)
        ttk.Label(frame, text="در روش دستی، مبلغ کارمزد هنگام ثبت هر تراکنش پرسیده می‌شود.").pack(anchor="e", pady=8)
        def save():
            data = {}
            try:
                for service, (mode_var, value_var) in controls.items():
                    mode_text = mode_var.get()
                    mode = {"ثابت":"fixed", "درصدی":"percent", "دستی":"manual"}.get(mode_text)
                    if not mode: raise ValueError("روش کارمزد نامعتبر است.")
                    value = float(value_var.get().replace(",", "") or 0)
                    if value < 0 or (mode == "percent" and value > 100): raise ValueError(f"مقدار کارمزد {service} نامعتبر است.")
                    data[service] = {"mode": mode, "value": value}
                self.save_setting("royal_fee_config", json.dumps(data, ensure_ascii=False))
                messagebox.showinfo("ذخیره شد", "تنظیم کارمزد هر شش خدمت ذخیره شد.", parent=win)
                win.destroy()
            except ValueError as exc:
                messagebox.showerror("ورودی نامعتبر", str(exc), parent=win)
        ttk.Button(frame, text="ذخیره تنظیمات", command=save).pack(anchor="center", pady=10)

    def show_main(self):
        self.clear()
        self.set_background()
        top = tk.Frame(self.root, bg="#16324f", height=72)
        top.pack(fill="x")
        tk.Label(top, text="سامانه مدیریت بانکی رویال", bg="#16324f", fg="white",
                 font=("IRANSans", 18, "bold")).pack(side="right", padx=22, pady=18)
        tk.Label(top, text=f"کاربر: {self.current_user['username']} ({self.current_user['role']})",
                 bg="#16324f", fg="white", font=("IRANSans", 10)).pack(side="left", padx=20)
        self.clock_label = tk.Label(self.root, text="", bg="#e7f3ff", fg="#16324f",
                                    font=("Tahoma", 12, "bold"), padx=12, pady=9, anchor="e")
        self.clock_label.pack(fill="x")
        clock_holder = tk.Frame(self.root, bg="#eef2f7", padx=8, pady=4)
        clock_holder.pack(side="left", anchor="nw")
        tk.Label(clock_holder, text="ساعت آنالوگ", bg="#eef2f7", fg="#16324f",
                 font=("Tahoma", 9, "bold")).pack()
        analog_clock = tk.Canvas(clock_holder, width=150, height=150,
                                 bg="#eef2f7", highlightthickness=0)
        analog_clock.pack()
        self.draw_analog_clock(analog_clock, 150)
        self.update_clock()
        body = ttk.Frame(self.root, padding=10)
        body.pack(fill="both", expand=True)
        sidebar_width = 185 if self.get_setting("layout_density", "استاندارد") == "جمع‌وجور" else 220
        sidebar = tk.Frame(body, bg="#16324f", width=sidebar_width, bd=0)
        sidebar.pack(side="right", fill="y", padx=(10, 0))
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="پنل مدیریت", bg="#16324f", fg="white",
                 font=("Tahoma", 16, "bold")).pack(fill="x", padx=10, pady=(18, 4))
        tk.Label(sidebar, text="رویال بانک", bg="#16324f", fg="#b9d8f2",
                 font=("IRANSans", 10)).pack(fill="x", padx=10, pady=(0, 14))
        self.content = ttk.Frame(body, padding=8)
        self.content.pack(side="left", fill="both", expand=True)
        # تبدیل دکمه‌های ناوبری به نوار منو با دسته‌بندی‌های مشخص
        menubar = tk.Menu(self.root, font=("IRANSans", 10), tearoff=0)
        def add_menu(title, entries):
            menu = tk.Menu(menubar, tearoff=0, font=("IRANSans", 10))
            for label, command in entries:
                if label is None:
                    menu.add_separator()
                else:
                    menu.add_command(label=label, command=command)
            menubar.add_cascade(label=title, menu=menu)

        add_menu("صفحه اصلی", [
            ("داشبورد", self.dashboard),
        ])
        add_menu("حساب‌ها و صندوق", [
            ("مدیریت حساب‌ها و موجودی", self.manage_account),
            ("مدیریت صندوق", self.fund_management),
            ("مدیریت پرداخت", self.payments),
            ("واریز سود سپرده‌ها", self.deposit_interest_payout),
        ])
        add_menu("چک‌ها", [
            ("مدیریت چک", self.check_management),
        ])
        add_menu("تسهیلات", [
            ("مدیریت تسهیلات", self.loan_management),
            ("تنظیم کارمزد خدمات", self.fee_settings),
        ])
        add_menu("کارت‌ها", [
            ("مدیریت کارت نقدی", self.manage_cards),
            ("درخواست کارت", self.request_card),
            ("درخواست رمز کارت", self.request_card_pin),
            ("فعال‌سازی کارت انتخاب‌شده", self.activate_selected_card),
            ("مسدود کردن کارت انتخاب‌شده", self.block_selected_card),
            ("چاپ کارت انتخاب‌شده", self.print_selected_card),
        ])
        add_menu("خدمات ویژه", [
            ("قرعه‌کشی حساب‌ها", self.account_raffle),
        ])
        add_menu("گزارش و اطلاعات", [
            ("گزارش‌ها و نمودارهای مالی", self.financial_reports),
            ("پشتیبان‌گیری و بازیابی اطلاعات", self.data_backup_restore),
        ])
        add_menu("مدیریت", [
            ("مدیریت کاربران و دسترسی", self.users),
            ("به‌روزرسانی برنامه", self.update_program),
            ("تنظیمات برنامه", self.settings),
            (None, None),
            ("خروج", self.show_login),
        ])
        self.root.config(menu=menubar)
        tk.Label(sidebar, text="دسترسی سریع", bg="#16324f", fg="#b9d8f2",
                 font=("Tahoma", 11, "bold")).pack(fill="x", padx=12, pady=(8, 6))
        # دکمه‌های دسترسی سریع در پنل مدیریت؛ منوی بالای برنامه نیز حفظ می‌شود.
        quick_actions = [
            ("صفحه اصلی / داشبورد", self.dashboard),
            ("مدیریت حساب‌ها", self.manage_account),
            ("مدیریت چک", self.check_management),
            ("مدیریت صندوق", self.fund_management),
            ("واریز سود سپرده‌ها", self.deposit_interest_payout),
            ("مدیریت پرداخت‌ها", self.payments),
            ("مدیریت تسهیلات و اقساط", self.loan_management),
            ("تنظیم کارمزد خدمات", self.fee_settings),
            ("مدیریت کارت نقدی", self.manage_cards),
            ("🎁 قرعه‌کشی حساب‌ها", self.account_raffle),
            ("گزارش‌های مالی", self.financial_reports),
            ("پشتیبان‌گیری / بازیابی", self.data_backup_restore),
            ("مدیریت کاربران", self.users),
            ("تنظیمات برنامه", self.settings),
        ]
        for label, command in quick_actions:
            tk.Button(sidebar, text=label, command=command, anchor="e",
                      font=("Tahoma", 9), bg="#234866", fg="white",
                      activebackground="#32688c", activeforeground="white",
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2").pack(fill="x", padx=9, pady=2)
        tk.Label(sidebar, text="همه بخش‌ها از منوی بالای برنامه نیز در دسترس هستند.",
                 bg="#16324f", fg="#b9d8f2", font=("Tahoma", 8),
                 wraplength=180, justify="right").pack(fill="x", padx=12, pady=(8, 4))
        self.dashboard()

    def check_management(self):
        """مدیریت چک‌ها، یادآوری سررسید، رسید چاپی و گزارش سررسید."""
        self.panel("مدیریت چک‌ها")
        toolbar = ttk.LabelFrame(self.content, text="جست‌وجو و فیلتر", padding=(5, 3))
        toolbar.pack(fill="x", pady=(0, 7))
        ttk.Label(toolbar, text="شماره چک / حساب / ذی‌نفع:").pack(side="right", padx=4)
        search_var = tk.StringVar()
        search_entry = ttk.Entry(toolbar, textvariable=search_var, width=19, justify="right")
        search_entry.pack(side="right", padx=4)
        status_filter = ttk.Combobox(toolbar, values=["همه", "در انتظار", "وصول شده", "برگشتی", "باطل"],
                                     state="readonly", width=11, justify="right")
        status_filter.pack(side="right", padx=4)
        status_filter.set("همه")

        columns = ("id", "check_no", "account_no", "beneficiary", "amount", "issue_date", "due_date", "status")
        headings = ("شناسه", "شماره چک", "شماره حساب", "در وجه", "مبلغ (تومان)", "تاریخ صدور", "تاریخ سررسید", "وضعیت")
        widths = (38, 92, 88, 112, 98, 82, 88, 78)
        table_frame = ttk.Frame(self.content)
        table_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        for col, heading, width in zip(columns, headings, widths):
            tree.heading(col, text=heading)
            tree.column(col, width=width, anchor="e", stretch=False)
        tree.tag_configure("overdue", foreground="#b00020")
        tree.tag_configure("today", foreground="#a05a00")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        today = self.jalali_today_text().replace("-", "/")
        def refresh():
            for item in tree.get_children():
                tree.delete(item)
            term = search_var.get().strip()
            state = status_filter.get()
            sql = """SELECT id,check_no,account_no,beneficiary,amount,issue_date,due_date,status
                     FROM checks WHERE (check_no LIKE ? OR account_no LIKE ? OR beneficiary LIKE ?)"""
            args = [f"%{term}%"] * 3
            if state and state != "همه":
                sql += " AND status=?"
                args.append(state)
            sql += " ORDER BY due_date, id DESC"
            for row in self.conn.execute(sql, args):
                due = (row["due_date"] or "").replace("-", "/")
                tag = "overdue" if due and due < today and row["status"] == "در انتظار" else (
                    "today" if due == today and row["status"] == "در انتظار" else "")
                tree.insert("", "end", values=(
                    row["id"], row["check_no"], row["account_no"], row["beneficiary"],
                    f'{row["amount"]:,.0f}', row["issue_date"] or "—",
                    row["due_date"] or "—", row["status"]
                ), tags=(tag,) if tag else ())

        def selected_row():
            chosen = tree.selection()
            if not chosen:
                messagebox.showwarning("توجه", "ابتدا یک چک را از فهرست انتخاب کنید.", parent=self.root)
                return None
            vals = tree.item(chosen[0], "values")
            return self.conn.execute("SELECT * FROM checks WHERE id=?", (vals[0],)).fetchone()

        def add_check():
            win = tk.Toplevel(self.root)
            win.title("ثبت چک")
            win.geometry("450x445")
            win.transient(self.root)
            win.grab_set()
            form = ttk.Frame(win, padding=14)
            form.pack(fill="both", expand=True)
            form.columnconfigure(0, weight=1)
            fields = {}
            specs = [("شماره چک", "check_no"), ("شماره حساب", "account_no"),
                     ("در وجه", "beneficiary"), ("مبلغ (تومان)", "amount"),
                     ("تاریخ صدور", "issue_date"), ("تاریخ سررسید", "due_date")]
            for i, (label, key) in enumerate(specs):
                ttk.Label(form, text=label, anchor="e").grid(row=i, column=1, sticky="e", padx=8, pady=6)
                ent = ttk.Entry(form, width=28, justify="right")
                ent.grid(row=i, column=0, sticky="ew", padx=8, pady=6)
                fields[key] = ent
            fields["issue_date"].insert(0, self.jalali_today_text())
            fields["due_date"].insert(0, self.jalali_today_text())
            ttk.Label(form, text="توضیحات", anchor="e").grid(row=6, column=1, sticky="e", padx=8, pady=6)
            notes = ttk.Entry(form, width=28, justify="right")
            notes.grid(row=6, column=0, sticky="ew", padx=8, pady=6)

            def save():
                check_no, account_no = fields["check_no"].get().strip(), fields["account_no"].get().strip()
                beneficiary = fields["beneficiary"].get().strip()
                try:
                    amount = float(fields["amount"].get().replace(",", "").replace("٬", "").strip())
                except ValueError:
                    messagebox.showerror("خطا", "مبلغ چک باید عدد معتبر باشد.", parent=win); return
                if not all((check_no, account_no, beneficiary, fields["due_date"].get().strip())):
                    messagebox.showwarning("توجه", "شماره چک، شماره حساب، ذی‌نفع و تاریخ سررسید الزامی است.", parent=win); return
                if amount <= 0:
                    messagebox.showerror("خطا", "مبلغ چک باید بیشتر از صفر باشد.", parent=win); return
                account = self.conn.execute("SELECT status FROM accounts WHERE account_no=?", (account_no,)).fetchone()
                if not account:
                    messagebox.showerror("خطا", "شماره حساب در سامانه پیدا نشد.", parent=win); return
                if account["status"] != "فعال":
                    messagebox.showerror("خطا", "برای حساب غیرفعال یا بسته نمی‌توان چک ثبت کرد.", parent=win); return
                try:
                    self.conn.execute("""INSERT INTO checks(check_no,account_no,beneficiary,amount,issue_date,due_date,
                        status,notes,created_at,created_by) VALUES(?,?,?,?,?,?,'در انتظار',?,?,?)""",
                        (check_no, account_no, beneficiary, amount, fields["issue_date"].get().strip(),
                         fields["due_date"].get().strip(), notes.get().strip(),
                         datetime.now().isoformat(timespec="seconds"), self.current_user["username"]))
                    self.conn.commit()
                    win.destroy(); refresh()
                    messagebox.showinfo("موفق", "چک با موفقیت ثبت شد.", parent=self.root)
                except sqlite3.IntegrityError:
                    messagebox.showerror("خطا", "این شماره چک قبلاً ثبت شده است.", parent=win)
                except sqlite3.Error as exc:
                    self.conn.rollback()
                    messagebox.showerror("خطا", f"ثبت چک انجام نشد: {exc}", parent=win)
            ttk.Button(form, text="ثبت چک", command=save).grid(row=7, column=0, columnspan=2, pady=12)

        def change_status(new_status):
            row = selected_row()
            if row is None: return
            if not messagebox.askyesno("تأیید تغییر وضعیت",
                    f"وضعیت چک {row['check_no']} به «{new_status}» تغییر کند؟", parent=self.root): return
            try:
                self.conn.execute("UPDATE checks SET status=? WHERE id=?", (new_status, row["id"]))
                self.conn.commit(); refresh()
            except sqlite3.Error as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"تغییر وضعیت انجام نشد: {exc}", parent=self.root)

        def print_receipt():
            row = selected_row()
            if row is None: return
            values = [
                ("شماره چک", row["check_no"]), ("شماره حساب", row["account_no"]),
                ("در وجه", row["beneficiary"]), ("مبلغ (تومان)", f'{row["amount"]:,.0f}'),
                ("تاریخ صدور", row["issue_date"] or "—"), ("تاریخ سررسید", row["due_date"] or "—"),
                ("وضعیت", row["status"]), ("توضیحات", row["notes"] or "—")
            ]
            body = "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>" for k,v in values)
            page = f"""<!doctype html><html lang="fa"><meta charset="utf-8"><title>رسید چک</title>
            <style>body{{font-family:Tahoma,Arial;direction:rtl;margin:35px}}h2{{text-align:center}}
            table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #555;padding:12px;text-align:right}}
            .foot{{margin-top:45px;display:flex;justify-content:space-between}}</style>
            <h2>رسید ثبت چک - سامانه رویال</h2><table>{body}</table>
            <div class="foot"><span>امضای تحویل‌دهنده: ................</span><span>مهر و امضا: ................</span></div>
            <script>window.onload=function(){{window.print();}}</script></html>"""
            try:
                receipt_path = Path(APP_DIR) / f"check_receipt_{row['id']}.html"
                receipt_path.write_text(page, encoding="utf-8")
                webbrowser.open(receipt_path.resolve().as_uri())
            except Exception as exc:
                messagebox.showerror("خطا", f"آماده‌سازی رسید برای چاپ انجام نشد: {exc}", parent=self.root)

        def due_report():
            win = tk.Toplevel(self.root)
            win.title("گزارش چک‌های سررسیدشده")
            win.geometry("850x420")
            frame = ttk.Frame(win, padding=10); frame.pack(fill="both", expand=True)
            ttk.Label(frame, text=f"چک‌های در انتظار با تاریخ سررسید تا {today} (شامل سررسید امروز)",
                      anchor="e").pack(fill="x", pady=(0,8))
            cols = ("check_no","account_no","beneficiary","amount","due_date","status")
            tv = ttk.Treeview(frame, columns=cols, show="headings")
            for c,h,w in zip(cols,("شماره چک","شماره حساب","در وجه","مبلغ","سررسید","وضعیت"),(130,120,180,130,120,110)):
                tv.heading(c,text=h); tv.column(c,width=w,anchor="e")
            tv.pack(fill="both",expand=True)
            rows = self.conn.execute("""SELECT check_no,account_no,beneficiary,amount,due_date,status
                FROM checks WHERE status='در انتظار' ORDER BY due_date""").fetchall()
            due_rows = [r for r in rows if (r["due_date"] or "").replace("-", "/") <= today]
            for r in due_rows:
                tv.insert("", "end", values=(r["check_no"],r["account_no"],r["beneficiary"],
                            f'{r["amount"]:,.0f}',r["due_date"],r["status"]))
            ttk.Label(frame, text=f"تعداد چک‌های سررسیدشده: {len(due_rows)}").pack(anchor="e", pady=7)
            ttk.Button(frame, text="بستن", command=win.destroy).pack(anchor="e")

        def reminders():
            win = tk.Toplevel(self.root)
            win.title("یادآوری چک‌ها")
            win.geometry("820x400")
            frame = ttk.Frame(win, padding=10); frame.pack(fill="both",expand=True)
            ttk.Label(frame, text="چک‌های در انتظار سررسید؛ سررسیدهای گذشته با عنوان معوق مشخص شده‌اند.",
                      anchor="e").pack(fill="x",pady=(0,8))
            cols=("check_no","account_no","beneficiary","amount","due_date","reminder")
            tv=ttk.Treeview(frame,columns=cols,show="headings")
            for c,h,w in zip(cols,("شماره چک","شماره حساب","در وجه","مبلغ","سررسید","یادآوری"),(120,110,170,120,110,130)):
                tv.heading(c,text=h); tv.column(c,width=w,anchor="e")
            tv.pack(fill="both",expand=True)
            rows=self.conn.execute("SELECT check_no,account_no,beneficiary,amount,due_date FROM checks WHERE status='در انتظار' ORDER BY due_date").fetchall()
            for r in rows:
                due=(r["due_date"] or "").replace("-","/")
                if due:
                    label="معوق" if due < today else ("سررسید امروز" if due == today else "در پیش")
                    tv.insert("","end",values=(r["check_no"],r["account_no"],r["beneficiary"],
                        f'{r["amount"]:,.0f}',r["due_date"],label))
            ttk.Label(frame,text="این یادآوری هنگام ورود به بخش مدیریت چک قابل مشاهده است؛ اعلان زمان‌بندی‌شده سیستم‌عامل نیست.",
                      foreground="#666").pack(anchor="e",pady=6)
            ttk.Button(frame,text="بستن",command=win.destroy).pack(anchor="e")

        def delete_check():
            row=selected_row()
            if row is None: return
            if not messagebox.askyesno("حذف چک",f"چک شماره {row['check_no']} حذف شود؟",parent=self.root): return
            try:
                self.conn.execute("DELETE FROM checks WHERE id=?",(row["id"],))
                self.conn.commit(); refresh()
            except sqlite3.Error as exc:
                self.conn.rollback()
                messagebox.showerror("خطا",f"حذف چک انجام نشد: {exc}",parent=self.root)

        # چیدمان شبکه‌ای دکمه‌ها: در پنجره‌های کوچک هم دکمه‌ها از کادر بیرون نمی‌روند.
        actions = ttk.LabelFrame(self.content, text="عملیات چک", padding=(5, 4))
        actions.pack(fill="x", pady=(0, 5))
        primary_actions = [
            ("ثبت چک جدید", add_check), ("یادآوری چک", reminders),
            ("چاپ رسید چک", print_receipt), ("گزارش سررسیدها", due_report)
        ]
        for col, (label, command) in enumerate(primary_actions):
            actions.columnconfigure(col, weight=1, uniform="check_primary")
            ttk.Button(actions, text=label, command=command).grid(
                row=0, column=col, sticky="ew", padx=3, pady=2, ipady=2)

        status_actions = ttk.LabelFrame(self.content, text="تغییر وضعیت و مدیریت", padding=(5, 3))
        status_actions.pack(fill="x", pady=(0, 5))
        secondary_actions = [
            ("وصول شده", lambda: change_status("وصول شده")),
            ("برگشتی", lambda: change_status("برگشتی")),
            ("باطل کردن", lambda: change_status("باطل")),
            ("حذف چک", delete_check), ("به‌روزرسانی", refresh)
        ]
        for col, (label, command) in enumerate(secondary_actions):
            status_actions.columnconfigure(col, weight=1, uniform="check_secondary")
            ttk.Button(status_actions, text=label, command=command).grid(
                row=0, column=col, sticky="ew", padx=3, pady=2, ipady=1)
        ttk.Button(toolbar,text="جست‌وجو",command=refresh).pack(side="right",padx=4)
        status_filter.bind("<<ComboboxSelected>>",lambda _event: refresh())
        search_entry.bind("<Return>",lambda _event: refresh())
        refresh()
        # پنجره یادآوری را در هر بار ورود باز می‌کند تا سررسیدها از قلم نیفتند.
        pending = self.conn.execute("SELECT due_date FROM checks WHERE status='در انتظار'").fetchall()
        if any((r["due_date"] or "").replace("-","/") <= today for r in pending):
            self.root.after(350, reminders)

    def deposit_interest_payout(self):
        """محاسبه و واریز سود سپرده‌ها با نرخ و دوره واردشده توسط کاربر."""
        frame = self.panel("واریز سود به سپرده‌های سوددار")
        frame.pack(fill="both", expand=True)
        content = ttk.Frame(frame, padding=(12, 6))
        content.pack(fill="both", expand=True, padx=12, pady=6)
        ttk.Label(
            content,
            text="این بخش سود سپرده‌های فعال را بر اساس مانده فعلی، نرخ سالانه و تعداد ماه محاسبه می‌کند.",
            wraplength=760, justify="right"
        ).pack(anchor="e", pady=(0, 5))

        form = ttk.LabelFrame(content, text="تنظیمات سود", padding=6)
        form.pack(anchor="e", fill="x", pady=3)
        ttk.Label(form, text="نرخ سود سالانه (درصد):").grid(row=0, column=3, padx=4, pady=3, sticky="e")
        rate_var = tk.StringVar(value="20")
        ttk.Entry(form, textvariable=rate_var, width=14, justify="center").grid(row=0, column=2, padx=4, pady=3)
        ttk.Label(form, text="دوره سود (ماه):").grid(row=0, column=1, padx=4, pady=3, sticky="e")
        months_var = tk.StringVar(value="1")
        ttk.Spinbox(form, from_=1, to=12, textvariable=months_var, width=8, justify="center").grid(row=0, column=0, padx=4, pady=3)
        ttk.Label(form, text="فقط حساب‌های فعال با نوع سپرده در محاسبه لحاظ می‌شوند.").grid(
            row=1, column=0, columnspan=4, sticky="e", padx=4, pady=3
        )

        summary = ttk.Label(content, text="برای مشاهده مبلغ سود، دکمه «محاسبه سود» را بزنید.")
        summary.pack(anchor="e", pady=4)

        # نوار دکمه‌ها بالای جدول است تا در پنجره‌های کوتاه پنهان نشود.
        buttons = ttk.Frame(content)
        buttons.pack(fill="x", pady=(2, 5))

        columns = ("account", "name", "type", "balance", "rate", "interest")
        table = ttk.Treeview(content, columns=columns, show="headings", height=7)
        for col, label, width in (
            ("account", "شماره حساب", 125), ("name", "نام صاحب حساب", 175),
            ("type", "نوع سپرده", 135), ("balance", "مانده (تومان)", 125),
            ("rate", "نرخ", 75), ("interest", "سود (تومان)", 140)
        ):
            table.heading(col, text=label)
            table.column(col, width=width, anchor="center")
        table.pack(fill="both", expand=True, pady=3)

        preview_rows = []

        def calculate():
            preview_rows.clear()
            for item in table.get_children():
                table.delete(item)
            try:
                rate = float(rate_var.get().replace(",", "").strip())
                months = int(months_var.get().strip())
                if rate < 0 or rate > 100 or months < 1 or months > 12:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("ورودی نامعتبر", "نرخ باید بین صفر تا ۱۰۰ و دوره بین ۱ تا ۱۲ ماه باشد.", parent=self.root)
                return
            rows = self.conn.execute(
                "SELECT account_no, full_name, account_type, balance FROM accounts "
                "WHERE status='فعال' AND account_type LIKE '%سپرده%' ORDER BY id"
            ).fetchall()
            total = 0.0
            for account in rows:
                balance = float(account["balance"] or 0)
                interest = round(balance * (rate / 100.0) * (months / 12.0))
                if interest <= 0:
                    continue
                item = {
                    "account_no": account["account_no"],
                    "full_name": account["full_name"],
                    "account_type": account["account_type"],
                    "balance": balance,
                    "interest": interest,
                }
                preview_rows.append(item)
                total += interest
                table.insert("", "end", values=(
                    item["account_no"], item["full_name"], item["account_type"],
                    f'{balance:,.0f}', f"{rate:g}%", f'{interest:,.0f}'
                ))
            summary.config(text=f"تعداد سپرده‌های مشمول: {len(preview_rows)}    |    مجموع سود قابل واریز: {total:,.0f} تومان")

        def payout():
            if not preview_rows:
                messagebox.showinfo("واریز سود", "ابتدا محاسبه سود را انجام دهید و وجود سپرده مشمول را بررسی کنید.", parent=self.root)
                return
            rate = float(rate_var.get().replace(",", "").strip())
            months = int(months_var.get().strip())
            total = sum(x["interest"] for x in preview_rows)
            if not messagebox.askyesno(
                "تأیید واریز سود",
                f"سود {len(preview_rows)} سپرده به مبلغ مجموع {total:,.0f} تومان واریز شود؟\n"
                f"نرخ سالانه: {rate:g}% | دوره: {months} ماه\n"
                "این عملیات موجودی حساب‌ها را افزایش می‌دهد و در گردش حساب ثبت می‌شود.",
                parent=self.root
            ):
                return
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                cur = self.conn.cursor()
                for item in preview_rows:
                    gross = float(item["interest"])
                    fee = self.calculate_fee("واریز سود سپرده", gross, self.root)
                    if fee > gross:
                        raise ValueError("کارمزد واریز سود نمی‌تواند از مبلغ سود بیشتر باشد.")
                    amount = gross - fee
                    self.sync_fund_with_account_delta(amount, "واریز خالص سود سپرده")
                    cur.execute("UPDATE accounts SET balance=balance+? WHERE account_no=? AND status='فعال'",
                                (amount, item["account_no"]))
                    cur.execute(
                        "INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                        (item["account_no"], "واریز سود سپرده", amount,
                         f"سود ناخالص {gross:,.0f}؛ کارمزد {fee:,.0f}؛ نرخ سالانه {rate:g}%؛ دوره {months} ماه",
                         now, self.current_user["username"])
                    )
                    self.credit_fee_fund(item["account_no"], "واریز سود سپرده", fee, now)
                self.conn.commit()
            except Exception as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"واریز سود انجام نشد و تغییرات برگشت داده شد:\n{exc}", parent=self.root)
                return
            messagebox.showinfo("واریز موفق", f"سود {len(preview_rows)} سپرده به مبلغ {total:,.0f} تومان با موفقیت واریز شد.", parent=self.root)
            calculate()

        ttk.Button(buttons, text="محاسبه سود", command=calculate).pack(side="right", padx=4)
        ttk.Button(buttons, text="تأیید و واریز سود", command=payout).pack(side="right", padx=4)

    def account_raffle(self):
        """قرعه‌کشی رایگان و شفاف میان حساب‌های فعال؛ بدون شرط‌بندی یا دریافت وجه."""
        import secrets
        frame = self.panel("قرعه‌کشی حساب‌های رویال")
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="قرعه‌کشی رایگان بین حساب‌های فعال بانک؛ برای شرکت در قرعه‌کشی هیچ مبلغی دریافت نمی‌شود.",
                  wraplength=850, justify="right").pack(anchor="e", pady=(0, 12))
        form = ttk.LabelFrame(frame, text="تعریف قرعه‌کشی", padding=12)
        form.pack(fill="x", pady=6)
        ttk.Label(form, text="عنوان قرعه‌کشی:").grid(row=0, column=3, padx=6, pady=6, sticky="e")
        title_var = tk.StringVar(value="قرعه‌کشی دوره‌ای رویال")
        ttk.Entry(form, textvariable=title_var, width=34, justify="right").grid(row=0, column=2, padx=6, pady=6)
        ttk.Label(form, text="جایزه:").grid(row=1, column=3, padx=6, pady=6, sticky="e")
        prize_var = tk.StringVar(value="جایزه ویژه")
        ttk.Entry(form, textvariable=prize_var, width=34, justify="right").grid(row=1, column=2, padx=6, pady=6)
        ttk.Label(form, text="تعداد برندگان:").grid(row=2, column=3, padx=6, pady=6, sticky="e")
        count_var = tk.StringVar(value="1")
        ttk.Spinbox(form, from_=1, to=100, textvariable=count_var, width=8, justify="center").grid(row=2, column=2, padx=6, pady=6, sticky="e")
        eligible = self.conn.execute("SELECT COUNT(*) FROM accounts WHERE status='فعال'").fetchone()[0]
        count_label = ttk.Label(form, text=f"تعداد حساب‌های فعال و واجد شرایط: {eligible}")
        count_label.grid(row=3, column=0, columnspan=4, sticky="e", padx=6, pady=8)

        result_box = ttk.LabelFrame(frame, text="نتیجه قرعه‌کشی", padding=10)
        result_box.pack(fill="both", expand=True, pady=8)
        cols = ("row", "name", "account", "prize")
        tree = ttk.Treeview(result_box, columns=cols, show="headings", height=8)
        for col, label, width in (("row", "ردیف", 60), ("name", "نام و نام خانوادگی", 220),
                                  ("account", "شماره حساب", 180), ("prize", "جایزه", 180)):
            tree.heading(col, text=label)
            tree.column(col, width=width, anchor="center")
        tree.pack(fill="both", expand=True)

        def run_draw():
            title = title_var.get().strip()
            prize = prize_var.get().strip()
            try:
                winners_n = int(count_var.get())
            except ValueError:
                messagebox.showwarning("ورودی نامعتبر", "تعداد برندگان باید عدد صحیح باشد.", parent=self.root)
                return
            candidates = self.conn.execute("SELECT account_no, full_name FROM accounts WHERE status='فعال' ORDER BY id").fetchall()
            if not title or not prize or winners_n < 1:
                messagebox.showwarning("اطلاعات ناقص", "عنوان، جایزه و تعداد برندگان را کامل کنید.", parent=self.root)
                return
            if not candidates:
                messagebox.showinfo("قرعه‌کشی", "هیچ حساب فعالی برای قرعه‌کشی وجود ندارد.", parent=self.root)
                return
            if winners_n > len(candidates):
                messagebox.showwarning("تعداد نامعتبر", f"حداکثر تعداد برندگان {len(candidates)} نفر است.", parent=self.root)
                return
            if not messagebox.askyesno("تأیید قرعه‌کشی", f"قرعه‌کشی رایگان «{title}» بین {len(candidates)} حساب فعال انجام شود؟\nتعداد برندگان: {winners_n}\nجایزه: {prize}", parent=self.root):
                return
            selected = secrets.SystemRandom().sample(list(candidates), winners_n)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                cur = self.conn.cursor()
                cur.execute("INSERT INTO account_raffles(title, prize, winner_count, created_at, created_by) VALUES(?,?,?,?,?)",
                            (title, prize, winners_n, now, self.current_user["username"]))
                raffle_id = cur.lastrowid
                for winner in selected:
                    cur.execute("INSERT INTO account_raffle_winners(raffle_id, account_no, full_name, created_at) VALUES(?,?,?,?)",
                                (raffle_id, winner["account_no"], winner["full_name"], now))
                self.conn.commit()
            except Exception as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"ثبت نتیجه قرعه‌کشی انجام نشد:\n{exc}", parent=self.root)
                return
            for item in tree.get_children():
                tree.delete(item)
            for i, winner in enumerate(selected, 1):
                tree.insert("", "end", values=(i, winner["full_name"], winner["account_no"], prize))
            messagebox.showinfo("قرعه‌کشی با موفقیت انجام شد", f"{len(selected)} برنده انتخاب و نتیجه در سوابق ثبت شد.", parent=self.root)
            refresh_history()

        ttk.Button(form, text="اجرای قرعه‌کشی و ثبت نتیجه", command=run_draw).grid(row=4, column=0, columnspan=4, pady=10)

        history_box = ttk.LabelFrame(frame, text="سوابق قرعه‌کشی", padding=8)
        history_box.pack(fill="both", expand=True, pady=6)
        history = ttk.Treeview(history_box, columns=("id", "title", "prize", "count", "date"), show="headings", height=5)
        for col, label, width in (("id", "شناسه", 60), ("title", "عنوان", 210), ("prize", "جایزه", 170),
                                  ("count", "تعداد برندگان", 100), ("date", "تاریخ اجرا", 160)):
            history.heading(col, text=label)
            history.column(col, width=width, anchor="center")
        history.pack(fill="both", expand=True)

        def refresh_history():
            for item in history.get_children():
                history.delete(item)
            rows = self.conn.execute("SELECT id, title, prize, winner_count, created_at FROM account_raffles ORDER BY id DESC LIMIT 100").fetchall()
            for row in rows:
                history.insert("", "end", values=tuple(row))
        def show_winners(_event=None):
            selected_item = history.selection()
            if not selected_item:
                return
            raffle_id = history.item(selected_item[0], "values")[0]
            rows = self.conn.execute("SELECT full_name, account_no FROM account_raffle_winners WHERE raffle_id=? ORDER BY id", (raffle_id,)).fetchall()
            details = "\n".join(f"{i}. {r['full_name']} — {r['account_no']}" for i, r in enumerate(rows, 1))
            messagebox.showinfo("برندگان قرعه‌کشی", details or "برنده‌ای ثبت نشده است.", parent=self.root)
        history.bind("<Double-1>", show_winners)
        ttk.Label(history_box, text="برای مشاهده اسامی برندگان، روی سابقه موردنظر دوبار کلیک کنید.").pack(anchor="e", pady=4)
        refresh_history()

    def panel(self, title):
        for w in self.content.winfo_children(): w.destroy()
        ttk.Label(self.content, text=title, style="Title.TLabel").pack(anchor="e", pady=(4,14))
        return ttk.Frame(self.content)

    def financial_reports(self):
        frame = self.panel("گزارش‌ها و نمودارهای مالی")
        frame.pack(fill="both", expand=True)

        accounts = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(balance),0) FROM accounts"
        ).fetchone()
        tx_count = self.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        deposits = self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='واریز'"
        ).fetchone()[0]
        withdrawals = self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='برداشت'"
        ).fetchone()[0]
        transfers = self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='انتقال وجه'"
        ).fetchone()[0]

        # Current fund balance
        fund_balance = self.conn.execute(
            "SELECT COALESCE(SUM(balance),0) FROM funds"
        ).fetchone()[0]

        # Date boundaries use the app's ISO-like created_at timestamps.
        from datetime import datetime, date
        today = date.today().isoformat()
        month_start = date.today().replace(day=1).isoformat()
        year_start = date.today().replace(month=1, day=1).isoformat()

        def fund_period(start_date):
            row = self.conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM transactions "
                "WHERE substr(created_at,1,10) >= ? AND substr(created_at,1,10) <= ?",
                (start_date, today)
            ).fetchone()
            return float(row[0] or 0)

        daily_amount = fund_period(today)
        monthly_amount = fund_period(month_start)
        yearly_amount = fund_period(year_start)

        # Compact KPI tiles
        summary = ttk.Frame(frame)
        summary.pack(fill="x", pady=(2, 5))
        metrics = [
            ("حساب‌ها", f"{accounts[0]:,}"),
            ("مجموع موجودی حساب‌ها", f"{accounts[1]:,.0f}"),
            ("تراکنش‌ها", f"{tx_count:,}")
        ]
        for title, value in metrics:
            card = tk.Frame(summary, bg="white", bd=1, relief="solid", padx=8, pady=5)
            card.pack(side="right", fill="x", expand=True, padx=3)
            tk.Label(card, text=title, bg="white", fg="#516174",
                     font=("Tahoma", 8)).pack()
            tk.Label(card, text=value, bg="white", fg="#16324f",
                     font=("Tahoma", 10, "bold")).pack(pady=(2, 0))

        # Small, tidy fund statistics row
        fund_frame = tk.LabelFrame(frame, text="آمار صندوق", bg="#f7f9fc",
                                   fg="#16324f", font=("Tahoma", 9, "bold"),
                                   padx=5, pady=4)
        fund_frame.pack(fill="x", pady=4)
        fund_metrics = [
            ("موجودی فعلی صندوق", fund_balance),
            ("روزانه", daily_amount),
            ("ماهانه", monthly_amount),
            ("سالانه", yearly_amount),
        ]
        for title, value in fund_metrics:
            tile = tk.Frame(fund_frame, bg="white", bd=1, relief="solid", padx=6, pady=4)
            tile.pack(side="right", fill="x", expand=True, padx=2)
            tk.Label(tile, text=title, bg="white", fg="#516174",
                     font=("Tahoma", 8)).pack()
            tk.Label(tile, text=f"{value:,.0f} تومان", bg="white", fg="#16324f",
                     font=("Tahoma", 9, "bold")).pack(pady=(1, 0))

        # Compact transaction comparison chart
        chart = tk.Canvas(frame, height=150, bg="white", highlightthickness=1,
                          highlightbackground="#d5dee8")
        chart.pack(fill="x", expand=False, pady=4)
        chart.update_idletasks()
        width = max(chart.winfo_width(), 500)
        chart.create_text(width//2, 16, text="مقایسه مبالغ تراکنش‌ها",
                          fill="#16324f", font=("Tahoma", 10, "bold"))
        values = [("واریز", deposits, "#2c8c65"),
                  ("برداشت", withdrawals, "#d16a52"),
                  ("انتقال", transfers, "#3477a8")]
        max_value = max([v for _, v, _ in values] + [1])
        base_y, usable_h = 112, 72
        bar_w = min(65, (width-100)//(len(values)*2))
        for i, (label, value, color) in enumerate(values):
            x = width - 85 - i * (width-130)//len(values) - bar_w
            h = int(usable_h * value / max_value) if value else 2
            chart.create_rectangle(x, base_y-h, x+bar_w, base_y, fill=color, outline="")
            chart.create_text(x+bar_w//2, base_y+12, text=label,
                              fill="#16324f", font=("Tahoma", 8))
            chart.create_text(x+bar_w//2, base_y-h-8, text=f"{value:,.0f}",
                              fill="#16324f", font=("Tahoma", 7))
        ttk.Label(frame, text="آمار بر اساس تراکنش‌های ثبت‌شده در پایگاه داده است.",
                  font=("Tahoma", 8)).pack(anchor="e", pady=(2, 0))

    def dashboard(self):
        frame = self.panel("داشبورد")
        frame.pack(fill="both", expand=True)
        base_font = self.ui_font
        tk.Label(
            frame, text="نمای کلی وضعیت حساب‌ها، موجودی‌ها و تراکنش‌های سامانه",
            bg="#eef2f7", fg="#344256", font=(base_font, 9),
            anchor="e", justify="right"
        ).pack(fill="x", anchor="e", pady=(0, 3))

        count = self.conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        active = self.conn.execute("SELECT COUNT(*) FROM accounts WHERE status='فعال'").fetchone()[0]
        balance = self.conn.execute("SELECT COALESCE(SUM(balance),0) FROM accounts").fetchone()[0]
        fund_balance = self.conn.execute("SELECT COALESCE(SUM(balance),0) FROM funds").fetchone()[0]
        tx = self.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

        # ابزار نمایش موجودی در کادر کم‌ارتفاع و فشرده
        lookup = ttk.LabelFrame(frame, text="نمایش موجودی حساب", padding=4)
        lookup.pack(fill="x", pady=(0, 5))
        controls = tk.Frame(lookup, bg="#eef2f7")
        controls.pack(fill="x", anchor="e")
        ttk.Label(controls, text="شماره حساب:").pack(side="right", padx=(5, 3))
        account_entry = ttk.Entry(controls, width=20, justify="right")
        account_entry.pack(side="right", padx=3, ipady=1)

        result = tk.Label(
            lookup, text="شماره حساب را وارد کنید و «نمایش موجودی» را بزنید.",
            bg="#ffffff", fg="#344256", font=(base_font, 9),
            justify="right", anchor="e", wraplength=850,
            padx=7, pady=4, relief="solid", bd=1, highlightthickness=0
        )
        result.pack(fill="x", pady=(5, 0))

        def show_balance():
            number = account_entry.get().strip()
            if not number:
                result.config(text="لطفاً شماره حساب را وارد کنید.", bg="#59421b", fg="#ffe5ad")
                return
            row = self.conn.execute(
                "SELECT full_name, balance, status FROM accounts WHERE account_no=?", (number,)
            ).fetchone()
            if row:
                result.config(
                    text=f"نام صاحب حساب: {row['full_name']}  |  موجودی: {row['balance']:,.0f} تومان  |  وضعیت: {row['status']}",
                    bg="#174b43", fg="#b9f1d8"
                )
            else:
                result.config(text="حسابی با این شماره پیدا نشد؛ شماره حساب را بررسی کنید.", bg="#5b2732", fg="#ffd5dc")

        ttk.Button(controls, text="نمایش موجودی", command=show_balance).pack(side="right", padx=3)
        ttk.Button(controls, text="به‌روزرسانی", command=self.dashboard).pack(side="left", padx=3)

        summary = tk.Frame(frame, bg="#102b4e")
        summary.pack(fill="x", pady=(0, 3))
        for column in range(5):
            summary.grid_columnconfigure(column, weight=1, uniform="dashboard_stats")
        cards = [
            ("کل حساب‌ها", f"{count:,}", "#e8f2ff", "#1e5a8a"),
            ("حساب‌های فعال", f"{active:,}", "#e7f7ef", "#176b4d"),
            ("مجموع موجودی حساب‌ها", f"{balance:,.0f} تومان", "#ffffff", "#16324f"),
            ("موجودی صندوق‌ها", f"{fund_balance:,.0f} تومان", "#ffffff", "#16324f"),
            ("تعداد تراکنش‌ها", f"{tx:,}", "#f1edff", "#59449b"),
        ]
        stat_icons = ["▦", "✓", "↗", "▣", "⇄"]
        for index, (title, value, bg_color, value_color) in enumerate(cards):
            card = tk.Frame(summary, bg=bg_color, bd=0, highlightthickness=1,
                            highlightbackground="#d5dee8", padx=4, pady=3)
            card.grid(row=0, column=4-index, sticky="nsew", padx=2, pady=2)
            tk.Label(card, text=stat_icons[index], bg=bg_color, fg=value_color,
                     font=(base_font, 10, "bold")).pack(anchor="center", pady=(0, 1))
            tk.Label(card, text=title, bg=bg_color, fg="#46576a",
                     font=(base_font, 8, "bold"), anchor="center", justify="center",
                     wraplength=130).pack(fill="x", anchor="center")
            tk.Label(card, text=value, bg=bg_color, fg=value_color,
                     font=(base_font, 9, "bold"), anchor="center", justify="center",
                     wraplength=150).pack(fill="x", anchor="center", pady=(2, 0))

    def jalali_today_text(self):
        jy, jm, jd = self.jalali_date(datetime.now())
        return f"{jy:04d}/{jm:02d}/{jd:02d}"

    @staticmethod
    def jalali_to_gregorian_text(value):
        try:
            jy, jm, jd = map(int, value.strip().replace("-", "/").split("/"))
            jy += 1595
            days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33 + 3) // 4) + jd
            if jm <= 6:
                days += (jm - 1) * 31
            else:
                days += 186 + (jm - 7) * 30
            gy = 400 * (days // 146097)
            days %= 146097
            if days > 36524:
                gy += 100 * ((days - 1) // 36524)
                days = (days - 1) % 36524
                if days >= 365:
                    days += 1
            gy += 4 * (days // 1461)
            days %= 1461
            if days > 365:
                gy += (days - 1) // 365
                days = (days - 1) % 365
            gd = days + 1
            month_days = [31, 29 if (gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            gm = 1
            while gd > month_days[gm - 1]:
                gd -= month_days[gm - 1]
                gm += 1
            return f"{gy:04d}-{gm:02d}-{gd:02d}"
        except Exception:
            raise ValueError("تاریخ شمسی را به شکل YYYY/MM/DD وارد کنید.")

    def open_account(self):
        self.panel("افتتاح حساب")
        win = tk.Toplevel(self.root); win.title("افتتاح حساب"); win.geometry("480x440"); win.transient(self.root); win.grab_set()
        fields = {}
        # چیدمان راست‌چین و منظم فرم افتتاح حساب
        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=1)
        labels = [("نام و نام خانوادگی","name"),("کد ملی","nid"),("شماره همراه","phone"),("موجودی اولیه (تومان)","balance")]
        for i,(label,key) in enumerate(labels):
            ttk.Label(win,text=label,anchor="e").grid(row=i,column=1,sticky="e",padx=12,pady=9)
            ent=ttk.Entry(win,width=28,justify="right"); ent.grid(row=i,column=0,sticky="e",padx=12,pady=9); fields[key]=ent
            if key == "balance": self.format_money_entry(ent)
        ttk.Label(win,text="تاریخ ثبت عملیات (شمسی)").grid(row=4,column=1,sticky="e",padx=12,pady=9)
        date_entry=ttk.Entry(win,width=28,justify="right"); date_entry.grid(row=4,column=0,sticky="e",padx=12,pady=9)
        date_entry.insert(0,self.jalali_today_text())
        ttk.Label(win,text="نوع حساب").grid(row=5,column=1,sticky="e",padx=12,pady=9)
        typ=ttk.Combobox(win,values=["جاری","پس‌انداز","کوتاه‌مدت","سپرده سوددار"],state="readonly",justify="right",width=25); typ.grid(row=5,column=0,sticky="e",padx=12,pady=9); typ.set("جاری")
        def save():
            name=fields["name"].get().strip()
            if not name: messagebox.showwarning("توجه","نام صاحب حساب الزامی است.",parent=win); return
            try: bal=float(fields["balance"].get().replace(",", "") or 0)
            except ValueError: messagebox.showerror("خطا","موجودی باید عدد باشد.",parent=win); return
            if bal < 0: messagebox.showerror("خطا","موجودی اولیه نمی‌تواند منفی باشد.",parent=win); return
            national_id = normalize_national_id(fields["nid"].get())
            if national_id and self.conn.execute("SELECT 1 FROM accounts WHERE TRIM(national_id)=?", (national_id,)).fetchone():
                messagebox.showerror("خطا", "این کد ملی قبلاً ثبت شده است.", parent=win); return
            # شماره حساب شبیه‌سازی‌شده: دقیقاً ۸ رقم، شروع با ۲ و یکتا
            no = ""
            while not no or self.conn.execute("SELECT 1 FROM accounts WHERE account_no=?", (no,)).fetchone():
                no = "2" + "".join(secrets.choice(string.digits) for _ in range(7))
            try:
                self.conn.execute("INSERT INTO accounts(account_no,full_name,national_id,phone,account_type,balance,status,created_at) VALUES(?,?,?,?,?,?,'فعال',?)",
                    (no,name,national_id or None,fields["phone"].get().strip(),typ.get(),bal,datetime.now().isoformat(timespec="seconds")))
                self.conn.commit()
                if bal: self.log_tx(no,"واریز",bal,"موجودی اولیه")
                messagebox.showinfo("موفق","حساب افتتاح شد.\nشماره حساب: "+no,parent=win); win.destroy(); self.dashboard()
            except sqlite3.IntegrityError as exc:
                message = "این کد ملی قبلاً ثبت شده است." if "کد ملی تکراری" in str(exc) or "national_id" in str(exc) else "شماره حساب تکراری شد؛ دوباره تلاش کنید."
                messagebox.showerror("خطا", message, parent=win)
        ttk.Button(win,text="ثبت حساب",command=save).grid(row=6,column=0,columnspan=2,pady=18)

    def manage_account(self):
        self.panel("مدیریت حساب‌ها")
        search = ttk.Frame(self.content)
        search.pack(fill="x", pady=1)
        ttk.Label(search, text="شماره حساب").pack(side="right", padx=2)
        entry = ttk.Entry(search, width=18, justify="right")
        entry.pack(side="right", padx=2)
        # فهرست انتخاب مستقیم شماره حساب برای مدیریت/حذف حساب موردنظر
        account_numbers = [r[0] for r in self.conn.execute("SELECT account_no FROM accounts ORDER BY account_no DESC").fetchall()]
        selected_account = ttk.Combobox(search, values=account_numbers, width=22, state="readonly", justify="right")
        selected_account.pack(side="right", padx=2)
        def choose_account(_event=None):
            no = selected_account.get().strip()
            if no:
                entry.delete(0, "end")
                entry.insert(0, no)
                load()
        selected_account.bind("<<ComboboxSelected>>", choose_account)
        ttk.Button(search, text="نمایش شماره حساب‌ها", padding=(4, 2), command=lambda: self.show_account_list(lambda no: (entry.delete(0, "end"), entry.insert(0, no), selected_account.set(no), load()))).pack(side="right", padx=2)
        ttk.Button(search, text="افتتاح حساب جدید", padding=(4, 2), command=self.open_account).pack(side="right", padx=2)
        fields = {}
        form = ttk.LabelFrame(self.content, text="اطلاعات حساب", padding=(5, 4))
        form.pack(anchor="e", fill="x", pady=2)
        # فیلدها به ترتیب در ردیف‌های جداگانه و راست‌چین
        ttk.Label(form, text="شماره حساب").grid(row=0, column=1, padx=3, pady=1, sticky="e")
        account_display = ttk.Entry(form, width=24, justify="right", state="readonly")
        account_display.grid(row=0, column=0, padx=3, pady=1, sticky="e")
        account_display.configure(foreground="#c00000")
        for row_index, (label, key) in enumerate([("نام و نام خانوادگی", "name"), ("کد ملی", "nid"), ("شماره همراه", "phone")], start=1):
            ttk.Label(form, text=label).grid(row=row_index, column=1, padx=3, pady=1, sticky="e")
            e = ttk.Entry(form, width=24, justify="right")
            e.grid(row=row_index, column=0, padx=3, pady=1, sticky="e")
            fields[key] = e
        ttk.Label(form, text="تاریخ افتتاح حساب (شمسی)").grid(row=4, column=1, padx=3, pady=1, sticky="e")
        opening_date = ttk.Entry(form, width=24, justify="right", state="readonly")
        opening_date.grid(row=4, column=0, padx=3, pady=1, sticky="e")
        opening_date.configure(foreground="#c00000")
        status = ttk.Combobox(form, values=["فعال", "مسدود"], state="readonly", width=21, justify="right")
        status.grid(row=5, column=0, padx=3, pady=1, sticky="e")
        ttk.Label(form, text="وضعیت حساب").grid(row=5, column=1, padx=3, pady=1, sticky="e")
        account_type = ttk.Combobox(form, values=["جاری", "پس‌انداز", "کوتاه‌مدت", "سپرده سوددار"], state="readonly", width=21, justify="right")
        account_type.grid(row=6, column=0, padx=3, pady=1, sticky="e")
        ttk.Label(form, text="نوع حساب").grid(row=6, column=1, padx=3, pady=1, sticky="e")

        def load():
            no = entry.get().strip()
            row = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (no,)).fetchone()
            if not row:
                messagebox.showerror("خطا", "حساب پیدا نشد.")
                return
            account_display.configure(state="normal")
            account_display.delete(0, "end")
            account_display.insert(0, row["account_no"] or "")
            account_display.configure(state="readonly")
            for key, col in [("name", "full_name"), ("nid", "national_id"), ("phone", "phone")]:
                fields[key].delete(0, "end")
                fields[key].insert(0, row[col] or "")
            status.set(row["status"])
            account_type.set(row["account_type"] or "جاری")
            opening_date.configure(state="normal")
            opening_date.delete(0, "end")
            try:
                dt = datetime.fromisoformat(row["created_at"])
                jy, jm, jd = self.jalali_date(dt)
                opening_date.insert(0, f"{jy:04d}/{jm:02d}/{jd:02d}")
            except (ValueError, TypeError, KeyError):
                opening_date.insert(0, row["created_at"] or "")
            opening_date.configure(state="readonly")

        def save():
            try:
                national_id = normalize_national_id(fields["nid"].get())
                account_no = entry.get().strip()
                if national_id and self.conn.execute("SELECT 1 FROM accounts WHERE TRIM(national_id)=? AND account_no<>?", (national_id, account_no)).fetchone():
                    messagebox.showerror("خطا", "این کد ملی به حساب دیگری اختصاص دارد."); return
                cur = self.conn.execute(
                    "UPDATE accounts SET full_name=?,national_id=?,phone=?,status=?,account_type=? WHERE account_no=?",
                    (fields["name"].get().strip(), national_id, fields["phone"].get().strip(), status.get(), account_type.get(), account_no))
                self.conn.commit()
                if cur.rowcount:
                    messagebox.showinfo("موفق", "اطلاعات حساب به‌روزرسانی شد.")
                else:
                    messagebox.showerror("خطا", "ابتدا حساب را جست‌وجو کنید.")
            except sqlite3.Error as e:
                message = "این کد ملی قبلاً برای حساب دیگری ثبت شده است." if "کد ملی تکراری" in str(e) or "national_id" in str(e) else str(e)
                messagebox.showerror("خطا", message)

        def delete():
            no = entry.get().strip()
            row = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (no,)).fetchone()
            if not row:
                messagebox.showerror("خطا", "ابتدا شماره حساب معتبر را جست‌وجو کنید.")
                return
            try:
                active_loan = self.conn.execute(
                    "SELECT 1 FROM loans WHERE account_no=? AND status='فعال' AND "
                    + ("COALESCE(outstanding,0)>0 LIMIT 1" if "outstanding" in {r[1] for r in self.conn.execute('PRAGMA table_info(loans)')} else "COALESCE(remaining,0)>0 LIMIT 1"), (no,)).fetchone()
                if active_loan:
                    messagebox.showwarning("امکان حذف نیست", "برای این حساب وام فعال وجود دارد؛ ابتدا وام را تسویه کنید.")
                    return
            except sqlite3.Error:
                pass
            current_balance = float(row["balance"] or 0)
            balance_notice = (
                f"\\nموجودی فعلی: {current_balance:,.2f} تومان"
                "\\nموجودی قبل از حذف صفر و تعدیل آن در سوابق ثبت می‌شود."
                if abs(current_balance) > 0.000001 else
                "\\nموجودی حساب از قبل صفر است."
            )
            if not messagebox.askyesno(
                "تأیید حذف",
                f"حساب {no} متعلق به {row['full_name']} حذف شود؟{balance_notice}"
                "\\nتراکنش‌های تاریخی حفظ و کارت‌های مرتبط حذف می‌شوند."
            ):
                return
            try:
                # ثبت تعدیل موجودی در تاریخچه و صفر کردن موجودی، در همان تراکنش حذف
                if abs(current_balance) > 0.000001:
                    now = datetime.now().isoformat(timespec="seconds")
                    username = self.current_user["username"]
                    self.conn.execute("UPDATE accounts SET balance=0 WHERE account_no=?", (no,))
                    self.sync_fund_with_account_delta(-current_balance, f"تسویه موجودی حساب {no} هنگام حذف")
                    self.conn.execute(
                        "INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                        (no, "تعدیل موجودی هنگام حذف حساب", -current_balance,
                         f"صفر کردن موجودی حساب پیش از حذف؛ موجودی قبلی: {current_balance:.2f}",
                         now, username)
                    )
                self.conn.execute("DELETE FROM cards WHERE account_no=?", (no,))
                self.conn.execute("DELETE FROM accounts WHERE account_no=?", (no,))
                self.conn.commit()
                for widget in fields.values():
                    widget.delete(0, "end")
                status.set("")
                account_display.configure(state="normal")
                account_display.delete(0, "end")
                account_display.configure(state="readonly")
                entry.delete(0, "end")
                messagebox.showinfo("موفق", "موجودی حساب صفر شد، حساب و کارت‌های مرتبط حذف شدند و سوابق تراکنش‌ها حفظ شدند.")
                self.dashboard()
            except sqlite3.Error as e:
                self.conn.rollback()
                messagebox.showerror("خطا", f"حذف حساب انجام نشد: {e}")

        def close_account():
            no = entry.get().strip()
            row = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (no,)).fetchone()
            if not row:
                messagebox.showerror("خطا", "ابتدا شماره حساب معتبر را جست‌وجو کنید.")
                return
            if row["status"] == "بسته":
                messagebox.showinfo("حساب بسته است", "این حساب قبلاً بسته شده است.")
                return
            balance = float(row["balance"] or 0)
            if abs(balance) > 0.000001:
                messagebox.showwarning("امکان بستن حساب نیست",
                    f"موجودی حساب باید قبل از بستن صفر شود. موجودی فعلی: {balance:,.0f} تومان")
                return
            try:
                active_loan = self.conn.execute(
                    "SELECT 1 FROM loans WHERE account_no=? AND status='فعال' AND "
                    + ("COALESCE(outstanding,0)>0 LIMIT 1" if "outstanding" in {r[1] for r in self.conn.execute('PRAGMA table_info(loans)')} else "COALESCE(remaining,0)>0 LIMIT 1"), (no,)).fetchone()
                if active_loan:
                    messagebox.showwarning("امکان بستن حساب نیست", "برای این حساب وام فعال وجود دارد؛ ابتدا وام را تسویه کنید.")
                    return
            except sqlite3.Error:
                pass
            if not messagebox.askyesno("تأیید بستن حساب",
                    f"حساب {no} متعلق به {row['full_name']} بسته شود؟\\nاطلاعات و سوابق حفظ می‌شوند و کارت‌های مرتبط غیرفعال خواهند شد."):
                return
            try:
                self.conn.execute("UPDATE accounts SET status='بسته' WHERE account_no=?", (no,))
                self.conn.execute("UPDATE cards SET status='مسدود' WHERE account_no=?", (no,))
                self.conn.commit()
                status.set("بسته")
                messagebox.showinfo("موفق", "حساب با موفقیت بسته شد. اطلاعات و سوابق آن حفظ شده‌اند.")
                self.manage_account()
            except sqlite3.Error as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"بستن حساب انجام نشد: {exc}")

        ttk.Button(search, text="جست‌وجو", padding=(5, 2), command=load).pack(side="right", padx=2)

        # نوار عملیات مستقل و مرتب در پایین فرم مدیریت حساب
        actions = ttk.Frame(self.content)
        actions.pack(fill="x", pady=(8, 4), anchor="e")
        ttk.Button(
            actions, text="ذخیره تغییرات", padding=(10, 5), command=save
        ).pack(side="right", padx=(4, 2))
        ttk.Button(
            actions, text="حذف حساب", padding=(10, 5), command=delete
        ).pack(side="right", padx=4)
        ttk.Button(
            actions, text="بستن حساب", padding=(10, 5), command=close_account
        ).pack(side="right", padx=4)

    def show_account_list(self, on_select=None):
        """نمایش شماره حساب‌ها و امکان انتخاب حساب برای مدیریت."""
        win = tk.Toplevel(self.root)
        win.title("فهرست شماره حساب‌ها")
        win.geometry("850x480")
        win.transient(self.root)
        cols = ("account_no", "full_name", "account_type", "balance", "status", "phone", "created_at")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=14)
        headings = ("شماره حساب", "نام و نام خانوادگی", "نوع حساب", "موجودی (تومان)", "وضعیت حساب", "شماره همراه", "تاریخ افتتاح (شمسی)")
        widths = (150, 185, 100, 125, 95, 125, 140)
        for col, heading, width in zip(cols, headings, widths):
            tree.heading(col, text=heading)
            tree.column(col, width=width, anchor="e")
        tree.tag_configure("account_number_red", foreground="#d00000")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        for row in self.conn.execute("SELECT account_no,full_name,account_type,balance,status,phone,created_at FROM accounts ORDER BY id DESC"):
            try:
                dt = datetime.fromisoformat(row["created_at"])
                jy, jm, jd = self.jalali_date(dt)
                opening = f"{jy:04d}/{jm:02d}/{jd:02d}"
            except (ValueError, TypeError):
                opening = row["created_at"] or ""
            tree.insert("", "end", values=(row["account_no"], row["full_name"], row["account_type"], f"{row['balance']:,.0f}", row["status"], row["phone"] or "", opening), tags=("account_number_red",))

        def choose():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("توجه", "یک حساب را انتخاب کنید.", parent=win)
                return
            account_no = tree.item(selected[0], "values")[0]
            win.destroy()
            if on_select:
                on_select(account_no)

        ttk.Button(win, text="نمایش شماره حساب انتخاب‌شده", command=choose).pack(pady=(0, 10))

    def sync_fund_with_account_delta(self, delta, note="تغییر موجودی حساب"):
        """همگام‌سازی مجموع صندوق با تغییرات موجودی حساب‌ها."""
        delta = float(delta or 0)
        if abs(delta) < 0.000001:
            return
        row = self.conn.execute("SELECT id FROM funds ORDER BY id LIMIT 1").fetchone()
        now = datetime.now().isoformat(timespec="seconds")
        if row:
            self.conn.execute("UPDATE funds SET balance=balance+? WHERE id=?", (delta, row["id"]))
        else:
            self.conn.execute(
                "INSERT INTO funds(fund_name,balance,description,created_at) VALUES(?,?,?,?)",
                ("صندوق اصلی", delta, note, now)
            )

    def log_tx(self, account_no, kind, amount, description):
        self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
            (account_no,kind,amount,description,datetime.now().isoformat(timespec="seconds"),self.current_user["username"]))
        self.conn.commit()

    def payments(self):
        self.panel("مدیریت پرداخت / واریز / برداشت / انتقال وجه")
        # فرم فشرده‌تر و منظم‌تر برای نمایش بخش‌های بیشتر در صفحه
        form = ttk.LabelFrame(self.content, text="اطلاعات عملیات", padding=(8, 5))
        form.pack(fill="x", anchor="e", pady=4)
        fields = {}
        specs = [
            ("شماره حساب / کارت مبدا", "account"),
            ("شماره حساب / کارت مقصد (انتقال)", "destination"),
            ("مبلغ (تومان)", "amount"),
            ("شرح", "desc"),
            ("شماره سند (اختیاری)", "document_no")
        ]
        for i, (label, key) in enumerate(specs):
            ttk.Label(form, text=label).grid(row=i, column=1, padx=5, pady=3, sticky="e")
            e = ttk.Entry(form, width=26, justify="right")
            e.grid(row=i, column=0, padx=5, pady=3, sticky="ew")
            fields[key] = e
            if key == "amount": self.format_money_entry(e)
        form.columnconfigure(0, weight=1)

        kind = ttk.Combobox(form, values=["واریز", "برداشت", "انتقال وجه", "انتقال به کارت", "برداشت به کارت"],
                            state="readonly", width=24, justify="right")
        kind.grid(row=5, column=0, padx=5, pady=3, sticky="ew")
        kind.set("واریز")
        ttk.Label(form, text="نوع عملیات").grid(row=5, column=1, padx=5, pady=3, sticky="e")

        ttk.Label(form, text="تاریخ ثبت عملیات (شمسی)").grid(row=6, column=1, padx=5, pady=3, sticky="e")
        date_entry = ttk.Entry(form, width=26, justify="right")
        date_entry.grid(row=6, column=0, padx=5, pady=3, sticky="ew")
        date_entry.insert(0,self.jalali_today_text())

        def update_destination_state(_event=None):
            operation = kind.get()
            fields["destination"].configure(
                state="normal" if operation in ("انتقال وجه", "انتقال به کارت") else "disabled")
            fields["account"].configure(state="normal")
            if operation == "انتقال به کارت":
                labels = ("شماره حساب / کارت مبدا", "شماره کارت مقصد")
            elif operation == "برداشت به کارت":
                labels = ("شماره کارت / حساب مبدا", "شماره حساب مقصد (غیرفعال)")
            else:
                labels = ("شماره حساب / کارت مبدا", "شماره حساب / کارت مقصد (انتقال)")
            # برچسب‌ها را بر اساس نوع عملیات به‌روز می‌کنیم.
            for child in form.winfo_children():
                if isinstance(child, ttk.Label) and child.grid_info().get("row") == 0:
                    child.configure(text=labels[0])
                elif isinstance(child, ttk.Label) and child.grid_info().get("row") == 1:
                    child.configure(text=labels[1])
        kind.bind("<<ComboboxSelected>>", update_destination_state)
        update_destination_state()

        def process():
            try:
                self.jalali_to_gregorian_text(date_entry.get())
            except ValueError as exc:
                messagebox.showerror("خطا", str(exc)); return
            no=fields["account"].get().strip()
            destination=fields["destination"].get().strip()
            source_identifier_entered = no
            destination_identifier_entered = destination
            try:
                amount=float(fields["amount"].get().replace(",", "").strip())
            except ValueError:
                messagebox.showerror("خطا","مبلغ معتبر وارد کنید."); return
            if amount<=0:
                messagebox.showerror("خطا","مبلغ باید بیشتر از صفر باشد."); return

            operation=kind.get()

            # در تمام عملیات پرداخت، شماره کارت ورودی به حساب متصل به آن تبدیل می‌شود.
            # برای ورودی شماره حساب، مقدار بدون تغییر باقی می‌ماند.
            def resolve_payment_identifier(value, role):
                value = value.strip()
                card = self.conn.execute(
                    "SELECT account_no,status FROM cards WHERE card_no=?", (value,)
                ).fetchone()
                if card:
                    if card["status"] != "فعال":
                        messagebox.showerror("خطا", f"کارت {role} فعال نیست."); return None
                    return card["account_no"]
                return value

            if operation == "برداشت به کارت":
                resolved = resolve_payment_identifier(no, "مبدا")
                if resolved is None: return
                no = resolved
                operation = "برداشت"
            elif operation == "انتقال به کارت":
                resolved = resolve_payment_identifier(destination, "مقصد")
                if resolved is None: return
                destination = resolved
                operation = "انتقال وجه"
            else:
                # حتی در عملیات معمولی نیز اگر شماره کارت وارد شود، حساب مرتبط استفاده می‌شود.
                resolved = resolve_payment_identifier(no, "مبدا")
                if resolved is None: return
                no = resolved
                if operation == "انتقال وجه" and destination:
                    resolved = resolve_payment_identifier(destination, "مقصد")
                    if resolved is None: return
                    destination = resolved
            row=self.conn.execute(
                "SELECT * FROM accounts WHERE account_no=?",(no,)).fetchone()
            if not row:
                messagebox.showerror("خطا","حساب مبدا پیدا نشد."); return
            if row["status"]!="فعال":
                messagebox.showerror("خطا","حساب مبدا مسدود است."); return

            description=fields["desc"].get().strip()
            document_no=fields["document_no"].get().strip()
            now=datetime.now().isoformat(timespec="seconds")
            try:
                service = {"واریز":"واریز وجه", "برداشت":"برداشت وجه", "انتقال وجه":"انتقال وجه"}.get(operation)
                fee = self.calculate_fee(service, amount, self.root) if service else 0.0
                if operation == "واریز" and fee > amount:
                    raise ValueError("کارمزد واریز نمی‌تواند از مبلغ واریزی بیشتر باشد.")
                total_debit = amount + fee
                if operation == "انتقال وجه":
                    if not destination:
                        messagebox.showerror("خطا","شماره حساب مقصد را وارد کنید."); return
                    if destination == no:
                        messagebox.showerror("خطا","حساب مبدا و مقصد نمی‌توانند یکسان باشند."); return
                    target = self.conn.execute("SELECT * FROM accounts WHERE account_no=?",(destination,)).fetchone()
                    if not target or target["status"] != "فعال":
                        messagebox.showerror("خطا","حساب مقصد پیدا نشد یا مسدود است."); return
                    if row["balance"] < total_debit:
                        messagebox.showerror("خطا","موجودی حساب مبدأ برای انتقال و کارمزد کافی نیست."); return

                    def account_preview(account, role, entered_identifier):
                        details = [
                            f"{role}:",
                            f"نام صاحب حساب: {account['full_name']}",
                            f"شماره حساب: {account['account_no']}",
                            f"نوع حساب: {account['account_type']}",
                            f"وضعیت: {account['status']}",
                            f"موجودی فعلی: {account['balance']:,.0f} تومان",
                        ]
                        if account["phone"]:
                            details.append(f"تلفن: {account['phone']}")
                        if account["national_id"]:
                            details.append(f"کد ملی: {account['national_id']}")
                        if entered_identifier and entered_identifier != account["account_no"]:
                            details.append(f"شماره کارت واردشده: {entered_identifier}")
                        return "\n".join(details)

                    preview_text = (
                        account_preview(row, "حساب مبدأ", source_identifier_entered)
                        + "\n\n"
                        + account_preview(target, "حساب مقصد", destination_identifier_entered)
                        + f"\n\nمبلغ انتقال: {amount:,.0f} تومان"
                        + f"\nکارمزد: {fee:,.0f} تومان"
                        + f"\nمجموع کسر از حساب مبدأ: {total_debit:,.0f} تومان"
                        + "\n\nآیا اطلاعات صحیح است و انتقال انجام شود؟"
                    )
                    if not messagebox.askyesno("بررسی مشخصات و تأیید انتقال", preview_text): return
                    self.conn.execute("BEGIN IMMEDIATE")
                    self.conn.execute("UPDATE accounts SET balance=balance-? WHERE account_no=?", (total_debit,no))
                    self.conn.execute("UPDATE accounts SET balance=balance+? WHERE account_no=?", (amount,destination))
                    suffix=f" | {description}" if description else ""
                    cur = self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by,document_no) VALUES(?,?,?,?,?,?,?)", (no,"انتقال وجه",-amount,f"انتقال به حساب {destination}{suffix}",now,self.current_user["username"],document_no or None))
                    if not document_no:
                        document_no = str(cur.lastrowid)
                        self.conn.execute("UPDATE transactions SET document_no=? WHERE id=?", (document_no, cur.lastrowid))
                    self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by,document_no) VALUES(?,?,?,?,?,?,?)", (destination,"دریافت انتقال",amount,f"دریافت از حساب {no}{suffix}",now,self.current_user["username"],document_no))
                    self.credit_fee_fund(no, service, fee, now)
                    self.conn.commit()
                    messagebox.showinfo("موفق",f"انتقال ثبت شد. کارمزد: {fee:,.0f} تومان")
                else:
                    if operation == "برداشت" and row["balance"] < total_debit:
                        messagebox.showerror("خطا","موجودی حساب برای برداشت و کارمزد کافی نیست."); return
                    credit = amount - fee if operation == "واریز" else 0
                    debit = amount + fee if operation == "برداشت" else 0
                    if not messagebox.askyesno("تأیید عملیات", f"مبلغ: {amount:,.0f} تومان\nکارمزد: {fee:,.0f} تومان\nمبلغ خالص عملیات: {(credit if operation == 'واریز' else debit):,.0f} تومان؟"): return
                    self.conn.execute("BEGIN IMMEDIATE")
                    new_balance = row["balance"] + credit if operation == "واریز" else row["balance"] - debit
                    self.conn.execute("UPDATE accounts SET balance=? WHERE account_no=?", (new_balance,no))
                    self.sync_fund_with_account_delta(credit if operation == "واریز" else -debit, f"{operation} حساب {no}")
                    cur = self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by,document_no) VALUES(?,?,?,?,?,?,?)", (no,operation,credit if operation == "واریز" else -amount,f"{description}؛ کارمزد {fee:,.0f}".strip("؛ "),now,self.current_user["username"],document_no or None))
                    if not document_no:
                        document_no = str(cur.lastrowid)
                        self.conn.execute("UPDATE transactions SET document_no=? WHERE id=?", (document_no, cur.lastrowid))
                    self.credit_fee_fund(no, service, fee, now)
                    self.conn.commit()
                    messagebox.showinfo("موفق",f"عملیات انجام شد.\nکارمزد: {fee:,.0f} تومان\nموجودی جدید: {new_balance:,.0f} تومان")
            except Exception as exc:
                self.conn.rollback()
                messagebox.showerror("خطا",f"ثبت عملیات ناموفق بود: {exc}")
                return
            self.dashboard()

        actions = ttk.Frame(self.content)
        actions.pack(fill="x", pady=(4, 2))
        ttk.Button(actions, text="ثبت عملیات", command=process).pack(side="right", padx=4, pady=3)
        ttk.Button(actions, text="نمایش تاریخچه تراکنش‌ها",
                   command=self.transaction_history).pack(side="right", padx=4, pady=3)


    def fund_management(self):
        """مدیریت صندوق‌های داخلی و موجودی آن‌ها."""
        self.panel("مدیریت صندوق")
        form = ttk.Frame(self.content); form.pack(anchor="e", fill="x", pady=8)
        ttk.Label(form, text="نام صندوق").grid(row=0, column=1, padx=8, pady=6)
        name = ttk.Entry(form, width=28, justify="right"); name.grid(row=0, column=0, padx=8, pady=6)
        ttk.Label(form, text="موجودی اولیه (تومان)").grid(row=1, column=1, padx=8, pady=6)
        balance = ttk.Entry(form, width=28, justify="right"); balance.grid(row=1, column=0, padx=8, pady=6)
        self.format_money_entry(balance)
        ttk.Label(form, text="شرح").grid(row=2, column=1, padx=8, pady=6)
        desc = ttk.Entry(form, width=28, justify="right"); desc.grid(row=2, column=0, padx=8, pady=6)
        cols = ("id", "fund_name", "balance", "description", "created_at")
        tree = ttk.Treeview(self.content, columns=cols, show="headings", height=12)
        for col, heading, width in zip(cols, ("شناسه", "نام صندوق", "موجودی (تومان)", "شرح", "تاریخ ایجاد"), (60, 180, 150, 260, 170)):
            tree.heading(col, text=heading); tree.column(col, width=width, anchor="center")
        tree.pack(fill="both", expand=True)
        def refresh():
            tree.delete(*tree.get_children())
            for row in self.conn.execute("SELECT * FROM funds ORDER BY id DESC"):
                tree.insert("", "end", values=(row["id"], row["fund_name"], f'{row["balance"]:,.0f}', row["description"] or "", row["created_at"]))
        def add():
            fund_name = name.get().strip()
            if not fund_name:
                messagebox.showwarning("توجه", "نام صندوق الزامی است."); return
            try: amount = float(balance.get().replace(",", "").strip() or 0)
            except ValueError:
                messagebox.showerror("خطا", "موجودی باید عدد باشد."); return
            if amount < 0:
                messagebox.showerror("خطا", "موجودی نمی‌تواند منفی باشد."); return
            try:
                self.conn.execute("INSERT INTO funds(fund_name,balance,description,created_at) VALUES(?,?,?,?)",
                                  (fund_name, amount, desc.get().strip(), datetime.now().isoformat(timespec="seconds")))
                self.conn.commit(); refresh()
                name.delete(0, "end"); balance.delete(0, "end"); desc.delete(0, "end")
            except sqlite3.IntegrityError:
                messagebox.showerror("خطا", "صندوقی با این نام از قبل ثبت شده است.")
        ttk.Button(form, text="افزودن صندوق", command=add).grid(row=3, column=0, pady=8)
        refresh()

    def manage_cards(self):
        """نمایش و مدیریت کارت‌های نقدی ثبت‌شده در سامانه نمونه."""
        self.panel("مدیریت کارت نقدی")
        # چیدمان ثابت دو ردیفه تا دکمه‌ها در پنجره‌های معمولی روی هم نیفتند یا از کادر بیرون نروند.
        toolbar = ttk.Frame(self.content)
        toolbar.pack(fill="x", pady=(0, 8), anchor="e")
        card_actions = [
            ("درخواست کارت", self.request_card),
            ("درخواست رمز کارت", self.request_card_pin),
            ("فعال‌سازی کارت انتخاب‌شده", self.activate_selected_card),
            ("مسدود کردن کارت انتخاب‌شده", self.block_selected_card),
            ("چاپ کارت انتخاب‌شده", self.print_selected_card),
            ("حذف کارت انتخاب‌شده", self.delete_selected_card),
        ]
        for i, (label, command) in enumerate(card_actions):
            row, col = divmod(i, 3)
            btn = ttk.Button(toolbar, text=label, command=command, width=24)
            btn.grid(row=row, column=2-col, padx=4, pady=4, sticky="ew")
            toolbar.columnconfigure(col, weight=1, uniform="card_actions")
        cols = ("card_no", "account_no", "card_type", "status", "expiry_date", "requested_at", "created_by")
        tree = ttk.Treeview(self.content, columns=cols, show="headings", height=12)
        headers = ("شماره کارت", "شماره حساب", "نوع کارت", "وضعیت", "تاریخ انقضا", "تاریخ درخواست", "ثبت‌کننده")
        widths = (180, 140, 90, 80, 110, 170, 100)
        for col, heading, width in zip(cols, headers, widths):
            tree.heading(col, text=heading)
            tree.column(col, width=width, anchor="center")
        tree.tag_configure("card_number_red", foreground="#d00000")
        tree.pack(fill="both", expand=True)
        for row in self.conn.execute("SELECT card_no,account_no,card_type,status,expiry_date,requested_at,created_by FROM cards ORDER BY id DESC"):
            values = [row[c] for c in cols]
            try:
                expiry_dt = datetime.strptime(str(row["expiry_date"]), "%Y-%m-%d")
                ey, em, ed = self.jalali_date(expiry_dt)
                values[4] = f"{ey:04d}/{em:02d}/{ed:02d}"
            except Exception:
                pass
            tree.insert("", "end", values=tuple(values), tags=("card_number_red",))
        self.card_tree = tree

    def delete_selected_card(self):
        """حذف کارت انتخاب‌شده از فهرست کارت‌های آزمایشی."""
        tree = getattr(self, "card_tree", None)
        if tree is None or not tree.selection():
            messagebox.showwarning("توجه", "ابتدا یک کارت را از فهرست انتخاب کنید.")
            return
        values = tree.item(tree.selection()[0], "values")
        card_no, account_no = str(values[0]), str(values[1])
        if not messagebox.askyesno("تأیید حذف کارت", f"کارت شماره {card_no} حذف شود؟"):
            return
        try:
            self.conn.execute("DELETE FROM cards WHERE card_no=? AND account_no=?", (card_no, account_no))
            self.conn.commit()
            messagebox.showinfo("موفق", "کارت انتخاب‌شده حذف شد.")
            self.manage_cards()
        except sqlite3.Error as exc:
            self.conn.rollback()
            messagebox.showerror("خطا", f"حذف کارت انجام نشد: {exc}")

    def print_selected_card(self):
        """ساخت برگه چاپی برای کارت آزمایشی انتخاب‌شده؛ کارت بانکی واقعی صادر نمی‌کند."""
        if not hasattr(self, "card_tree"):
            messagebox.showwarning("توجه", "ابتدا بخش مدیریت کارت نقدی را باز کنید.")
            return
        selected = self.card_tree.selection()
        if not selected:
            messagebox.showwarning("توجه", "برای چاپ، ابتدا یک کارت را انتخاب کنید.")
            return
        values = self.card_tree.item(selected[0], "values")
        card_no, account_no, card_type, status, expiry_date = values[:5]
        if status != "فعال":
            if not messagebox.askyesno("تأیید", "این کارت مسدود است. آیا برگه مشخصات آن چاپ شود؟"):
                return
        account = self.conn.execute("SELECT full_name FROM accounts WHERE account_no=?", (account_no,)).fetchone()
        account_name = account["full_name"] if account else ""
        def esc(value):
            return html.escape(str(value or ""))
        def printer_setting(key, default):
            row = self.conn.execute("SELECT value FROM settings WHERE key=?", ("printer_" + key,)).fetchone()
            return row[0] if row else default
        paper_size = printer_setting("paper", "A4").strip()
        if paper_size not in ("A4", "A5", "Letter", " کارت بانکی (CR80)"):
            paper_size = "A4"
        if paper_size == " کارت بانکی (CR80)":
            page_size_rule = "86mm 54mm"
        else:
            page_orientation = "landscape" if printer_setting("orientation", "عمودی") == "افقی" else "portrait"
            page_size_rule = f"{paper_size} {page_orientation}"
        margin_mm = max(0, min(40, int(printer_setting("margin_mm", "18"))))
        color_mode = "grayscale(1)" if printer_setting("color", "رنگی") == "سیاه و سفید" else "none"
        # چاپ نمای کارت با سه مشخصه اصلی در خود کارت: شماره، نام دارنده و تاریخ انقضا
        expiry_display = str(expiry_date or "—").strip() or "—"
        name_display = str(account_name or "—").strip() or "—"
        document = f'''<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><title>چاپ کارت رویال بانک</title>
<style>
@page {{ size: {page_size_rule}; margin: {margin_mm}mm; }}
html {{ filter: {color_mode}; }}
* {{ box-sizing:border-box; }}
body {{ font-family: IRANSans, Tahoma, Arial, sans-serif; color:#17324f; margin:0; padding:8mm; }}
.card {{ width:86mm; height:54mm; border-radius:4mm; padding:5mm 6mm; overflow:hidden;
background:linear-gradient(125deg,#092b48 0%,#13577a 58%,#16836e 100%); color:#fff;
border:0.3mm solid #7cb8b0; position:relative; box-shadow:0 2mm 5mm #17324f33; }}
.brand {{font-size:15pt;font-weight:800;letter-spacing:.2px;}}
.subtitle {{font-size:8pt;opacity:.85;margin-top:1mm;}}
.chip {{position:absolute;left:8mm;top:17mm;width:11mm;height:8mm;border-radius:2mm;background:linear-gradient(135deg,#e8d9a6,#b7a36d);border:0.3mm solid #fff8;}}
.number-label {{font-size:7pt;opacity:.85;margin-top:8mm;}}
.number {{font-size:14pt;font-weight:700;letter-spacing:1px;direction:ltr;text-align:center;margin-top:1mm;white-space:nowrap;}}
.bottom {{display:flex;justify-content:space-between;align-items:end;gap:3mm;margin-top:5mm;}}
.holder {{min-width:0;flex:1;}}
.field-label {{font-size:6.5pt;opacity:.8;margin-bottom:1mm;}}
.holder-name {{font-size:9pt;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.expiry {{text-align:left;direction:ltr;white-space:nowrap;}}
.expiry-value {{font-size:9pt;font-weight:700;}}
.note {{font-size:8pt;color:#8b2525;margin-top:8mm;}}
@media print {{ body {{padding:0}} .card {{box-shadow:none;print-color-adjust:exact;-webkit-print-color-adjust:exact}} button {{display:none}} }}
</style></head><body>
<div class="card">
  <div class="brand">ROYAL BANK</div><div class="subtitle">قرض‌الحسنه رویال بانک · کارت نقدی</div>
  <div class="chip" aria-hidden="true"></div>
  <div class="number-label">شماره کارت</div><div class="number">{esc(card_no)}</div>
  <div class="bottom">
    <div class="holder"><div class="field-label">نام و نام خانوادگی</div><div class="holder-name">{esc(name_display)}</div></div>
    <div class="expiry"><div class="field-label">تاریخ انقضا</div><div class="expiry-value">{esc(expiry_display)}</div></div>
  </div>
</div>
<p class="note">این کارت نمونه چاپی نرم‌افزار است و کارت بانکی واقعی یا ابزار پرداخت محسوب نمی‌شود.</p>
<button onclick="window.print()">چاپ کارت</button><script>window.onload=()=>window.print()</script></body></html>'''
        output = APP_DIR / "card_print_preview.html"
        try:
            output.write_text(document, encoding="utf-8")
            webbrowser.open(output.resolve().as_uri())
        except OSError as exc:
            messagebox.showerror("خطا", f"ساخت برگه چاپی ناموفق بود: {exc}")

    def request_card(self):
        win = tk.Toplevel(self.root)
        win.title("درخواست کارت نقدی")
        win.geometry("500x390")
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text="شماره حساب فعال").grid(row=0, column=1, padx=12, pady=12, sticky="e")
        account_entry = ttk.Entry(win, width=28, justify="right")
        account_entry.grid(row=0, column=0, padx=12, pady=12)
        ttk.Label(win, text="نوع کارت").grid(row=1, column=1, padx=12, pady=12, sticky="e")
        card_type = ttk.Combobox(win, values=["نقدی"], state="readonly", width=25, justify="right")
        card_type.grid(row=1, column=0, padx=12, pady=12)
        card_type.set("نقدی")
        ttk.Label(win, text="تاریخ انقضا (شمسی YYYY/MM/DD)").grid(row=2, column=1, padx=12, pady=12, sticky="e")
        expiry_entry = ttk.Entry(win, width=28, justify="right")
        expiry_entry.grid(row=2, column=0, padx=12, pady=12)
        expiry_default = datetime.now().replace(year=datetime.now().year + 5)
        expiry_jy, expiry_jm, expiry_jd = self.jalali_date(expiry_default)
        expiry_entry.insert(0, f"{expiry_jy:04d}/{expiry_jm:02d}/{expiry_jd:02d}")
        ttk.Label(win, text="تاریخ ثبت درخواست (شمسی)").grid(row=3, column=1, padx=12, pady=12, sticky="e")
        request_date_entry = ttk.Entry(win, width=28, justify="right")
        request_date_entry.grid(row=3, column=0, padx=12, pady=12)
        request_date_entry.insert(0, self.jalali_today_text())
        keep_previous_card = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            win,
            text="حفظ شماره کارت قبلی (در صورت وجود کارت فعال)",
            variable=keep_previous_card
        ).grid(row=4, column=0, columnspan=2, padx=12, pady=8, sticky="e")

        def submit():
            account_no = account_entry.get().strip()
            expiry_jalali = expiry_entry.get().strip()
            try:
                expiry_date = self.jalali_to_gregorian_text(expiry_jalali)
                datetime.strptime(expiry_date, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("خطا", "تاریخ انقضا را به شکل شمسی YYYY/MM/DD وارد کنید.", parent=win)
                return
            if expiry_date <= datetime.now().strftime("%Y-%m-%d"):
                messagebox.showerror("خطا", "تاریخ انقضا باید در آینده باشد.", parent=win)
                return
            account = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (account_no,)).fetchone()
            if not account:
                messagebox.showerror("خطا", "حساب موردنظر پیدا نشد.", parent=win)
                return
            if account["status"] != "فعال":
                messagebox.showerror("خطا", "برای حساب مسدود امکان درخواست کارت وجود ندارد.", parent=win)
                return
            try:
                now_text = datetime.now().isoformat(timespec="seconds")
                previous_card = None
                if keep_previous_card.get():
                    previous_card = self.conn.execute(
                        "SELECT * FROM cards WHERE account_no=? AND status='فعال' ORDER BY id DESC LIMIT 1",
                        (account_no,)
                    ).fetchone()

                if previous_card:
                    # شماره کارت قبلی حفظ می‌شود و فقط تاریخ انقضا و مشخصات درخواست به‌روز می‌شود.
                    card_no = previous_card["card_no"]
                    self.conn.execute(
                        "UPDATE cards SET expiry_date=?, requested_at=?, created_by=? WHERE id=?",
                        (expiry_date, now_text, self.current_user["username"], previous_card["id"])
                    )
                    result_message = (
                        "درخواست تمدید کارت ثبت شد.\n"
                        f"شماره کارت قبلی حفظ شد: {card_no}\n"
                        f"تاریخ انقضای جدید: {expiry_date}"
                    )
                else:
                    # شماره کارت شبیه‌سازی‌شده: دقیقاً ۱۲ رقم، شروع با ۴ و یکتا
                    card_no = ""
                    while not card_no or self.conn.execute(
                        "SELECT 1 FROM cards WHERE card_no=?", (card_no,)
                    ).fetchone():
                        card_no = "4" + "".join(secrets.choice(string.digits) for _ in range(11))
                    self.conn.execute(
                        "INSERT INTO cards(card_no,account_no,card_type,status,requested_at,created_by,expiry_date) VALUES(?,?,?,'فعال',?,?,?)",
                        (card_no, account_no, card_type.get(), now_text, self.current_user["username"], expiry_date)
                    )
                    result_message = (
                        "درخواست کارت ثبت شد.\n"
                        f"شماره کارت: {card_no}\n"
                        f"تاریخ انقضا: {expiry_date}"
                    )

                self.conn.commit()
                messagebox.showinfo("ثبت شد", result_message, parent=win)
                win.destroy()
                if hasattr(self, "content"):
                    self.manage_cards()
            except sqlite3.Error as exc:
                messagebox.showerror("خطا", f"ثبت درخواست ناموفق بود: {exc}", parent=win)
        ttk.Button(win, text="ثبت درخواست", command=submit).grid(row=5, column=0, columnspan=2, pady=16)

    def request_card_pin(self):
        """Set or reset the selected customer's shared ATM PIN in the common database."""
        selected = getattr(self, "card_tree", None)
        if selected is None or not selected.selection():
            messagebox.showwarning("توجه", "ابتدا کارت مشتری را در فهرست انتخاب کنید."); return
        values = selected.item(selected.selection()[0], "values")
        card_no, account_no, status = values[0], values[1], values[3]
        if status != "فعال":
            messagebox.showerror("خطا", "برای کارت مسدود امکان تعریف رمز وجود ندارد."); return

        pin = simpledialog.askstring("تعریف رمز مشترک مشتری",
            "رمز ورود این مشتری به خودپرداز را وارد کنید (۴ تا ۸ رقم):",
            show="*", parent=self.root)
        if pin is None:
            return
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            messagebox.showwarning("رمز نامعتبر", "رمز باید ۴ تا ۸ رقم باشد."); return
        confirm = simpledialog.askstring("تأیید رمز مشتری",
            "همان رمز را دوباره وارد کنید:", show="*", parent=self.root)
        if confirm is None:
            return
        if not secrets.compare_digest(pin, confirm):
            messagebox.showwarning("عدم تطابق", "دو رمز یکسان نیستند؛ تغییری انجام نشد."); return

        # Match the ATM's PBKDF2-SHA256 format and store only the salted hash.
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"),
                                     salt.encode("utf-8"), 200_000).hex()
        try:
            cur = self.conn.execute(
                "UPDATE cards SET pin_hash=?, pin_salt=?, failed_attempts=0 WHERE card_no=? AND account_no=? AND status='فعال'",
                (digest, salt, card_no, account_no))
            if cur.rowcount != 1:
                self.conn.rollback()
                messagebox.showerror("خطا", "کارت فعال مشتری پیدا نشد؛ رمز تغییر نکرد."); return
            self.conn.execute(
                "INSERT INTO card_pin_requests(card_no,account_no,status,requested_at,requested_by) VALUES(?,?,?,?,?)",
                (card_no, account_no, "رمز مشترک مشتری در مدیریت تعریف شد", datetime.now().isoformat(timespec="seconds"), self.current_user["username"]))
            self.conn.commit()
            messagebox.showinfo("رمز مشترک ثبت شد",
                "رمز مشتری با موفقیت در پایگاه داده مشترک ثبت شد. مشتری می‌تواند در خودپرداز با همین شماره کارت و همین رمز وارد شود. تغییر بعدی رمز از این بخش یا خودپرداز در هر دو برنامه اعمال می‌شود.")
        except sqlite3.Error as exc:
            self.conn.rollback()
            messagebox.showerror("خطا", f"ثبت رمز مشتری انجام نشد: {exc}")

    def print_card_pin_request(self):
        # چاپ رسید درخواست؛ رمز واقعی کارت در برنامه نگهداری نمی‌شود.
        tree = getattr(self, "card_tree", None)
        if tree is None or not tree.selection():
            messagebox.showwarning("توجه", "ابتدا یک کارت را در فهرست مدیریت کارت انتخاب کنید.")
            return
        values = tree.item(tree.selection()[0], "values")
        card_no, account_no = values[0], values[1]
        request = self.conn.execute(
            "SELECT status, requested_at, requested_by FROM card_pin_requests WHERE card_no=? ORDER BY id DESC LIMIT 1",
            (card_no,)
        ).fetchone()
        if not request:
            if not messagebox.askyesno("درخواست رمز ثبت نشده", "برای این کارت هنوز درخواستی ثبت نشده است. اکنون درخواست رمز ثبت شود و رسید آن چاپ شود؟"):
                return
            try:
                self.conn.execute(
                    "INSERT INTO card_pin_requests(card_no,account_no,status,requested_at,requested_by) VALUES(?,?,?,?,?)",
                    (card_no, account_no, "در انتظار بررسی", datetime.now().isoformat(timespec="seconds"), self.current_user["username"])
                )
                self.conn.commit()
                request = self.conn.execute(
                    "SELECT status, requested_at, requested_by FROM card_pin_requests WHERE card_no=? ORDER BY id DESC LIMIT 1",
                    (card_no,)
                ).fetchone()
            except sqlite3.Error as exc:
                messagebox.showerror("خطا", f"ثبت درخواست ناموفق بود: {exc}")
                return
        account = self.conn.execute("SELECT full_name FROM accounts WHERE account_no=?", (account_no,)).fetchone()
        esc = html.escape
        document = f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>رسید درخواست رمز کارت</title>
<style>body{{font-family:IRANSans,Tahoma,Arial,sans-serif;color:#17324f;margin:32px}}.receipt{{max-width:720px;margin:auto;border:2px solid #087e8b;border-radius:14px;padding:26px}}h2{{text-align:center;color:#087e8b}}table{{width:100%;border-collapse:collapse;margin-top:20px}}td{{padding:12px;border:1px solid #ccd7e2}}td:first-child{{font-weight:bold;background:#edf7f8;width:35%}}.note{{margin-top:22px;color:#a12626;font-size:12px}}button{{padding:10px 24px;background:#087e8b;color:white;border:0;border-radius:6px;cursor:pointer}}@media print{{button{{display:none}}}}</style>
<div class="receipt"><h2>قرض‌الحسنه رویال بانک</h2><h3 style="text-align:center">رسید درخواست رمز کارت</h3>
<table><tr><td>نام صاحب حساب</td><td>{esc(account['full_name'] if account else '')}</td></tr>
<tr><td>شماره حساب</td><td>{esc(account_no)}</td></tr><tr><td>شماره کارت</td><td>{esc(card_no)}</td></tr>
<tr><td>نوع درخواست</td><td>درخواست رمز کارت</td></tr><tr><td>وضعیت فعلی درخواست</td><td>{esc(request['status'])}</td></tr><tr><td>زمان ثبت</td><td>{esc(request['requested_at'])}</td></tr>
<tr><td>ثبت‌کننده درخواست</td><td>{esc(request['requested_by'])}</td></tr></table>
<p class="note">این رسید فقط تأیید ثبت درخواست است و شامل رمز کارت نمی‌شود. رمز واقعی کارت در این نرم‌افزار ذخیره یا چاپ نمی‌شود؛ این نسخه نمونه/آموزشی است.</p>
<div style="text-align:center"><button onclick="window.print()">چاپ رسید</button></div></div><script>window.onload=()=>window.print()</script></html>'''
        output = APP_DIR / "card_pin_request_print.html"
        try:
            output.write_text(document, encoding="utf-8")
            webbrowser.open(output.resolve().as_uri())
        except OSError as exc:
            messagebox.showerror("خطا", f"ساخت برگه چاپی ناموفق بود: {exc}")

    def block_card(self):
        win = tk.Toplevel(self.root)
        win.title("مسدودی کارت")
        win.geometry("420x180")
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text="شماره کارت").grid(row=0, column=1, padx=10, pady=12, sticky="e")
        card_entry = ttk.Entry(win, width=28, justify="right")
        card_entry.grid(row=0, column=0, padx=7, pady=7)
        def block():
            card_no = card_entry.get().strip()
            cur = self.conn.execute("UPDATE cards SET status='مسدود' WHERE card_no=? AND status='فعال'", (card_no,))
            self.conn.commit()
            if cur.rowcount:
                messagebox.showinfo("موفق", "کارت مسدود شد.", parent=win)
                win.destroy()
                self.manage_cards()
            else:
                messagebox.showerror("خطا", "کارت فعال با این شماره پیدا نشد.", parent=win)
        ttk.Button(win, text="مسدود کردن کارت", command=block).grid(row=1, column=0, columnspan=2, pady=14)

    def activate_selected_card(self):
        """فعال‌سازی کارت آزمایشی انتخاب‌شده در فهرست مدیریت کارت."""
        if not hasattr(self, "card_tree"):
            messagebox.showwarning("توجه", "ابتدا بخش مدیریت کارت نقدی را باز کنید.")
            return
        selected = self.card_tree.selection()
        if not selected:
            messagebox.showwarning("توجه", "ابتدا یک کارت را در فهرست انتخاب کنید.")
            return
        values = self.card_tree.item(selected[0], "values")
        card_no = values[0]
        if values[3] == "فعال":
            messagebox.showinfo("اطلاع", "این کارت هم‌اکنون فعال است.")
            return
        if not messagebox.askyesno("تأیید فعال‌سازی", f"کارت {card_no} فعال شود؟"):
            return
        cur = self.conn.execute(
            "UPDATE cards SET status='فعال' WHERE card_no=? AND status='مسدود'", (card_no,)
        )
        self.conn.commit()
        if cur.rowcount:
            messagebox.showinfo("موفق", "کارت با موفقیت فعال شد.")
        else:
            messagebox.showwarning("توجه", "وضعیت کارت تغییر نکرد.")
        self.manage_cards()

    def block_selected_card(self):
        if not hasattr(self, "card_tree"):
            return
        selected = self.card_tree.selection()
        if not selected:
            messagebox.showwarning("توجه", "ابتدا یک کارت را انتخاب کنید.")
            return
        card_no = self.card_tree.item(selected[0], "values")[0]
        if not messagebox.askyesno("تأیید", f"کارت {card_no} مسدود شود؟"):
            return
        cur = self.conn.execute("UPDATE cards SET status='مسدود' WHERE card_no=? AND status='فعال'", (card_no,))
        self.conn.commit()
        if cur.rowcount:
            messagebox.showinfo("موفق", "کارت مسدود شد.")
        else:
            messagebox.showinfo("اطلاع", "این کارت قبلاً مسدود شده است.")
        self.manage_cards()

    def transfer_money(self):
        self.panel("انتقال وجه بین حساب‌ها")
        form = ttk.Frame(self.content)
        form.pack(anchor="e", pady=8)
        fields = {}
        for i, (label, key) in enumerate([
            ("شماره حساب مبدأ", "source"), ("شماره حساب مقصد", "destination"),
            ("مبلغ انتقال (تومان)", "amount"), ("شرح", "description")
        ]):
            ttk.Label(form, text=label).grid(row=i, column=1, padx=8, pady=8, sticky="e")
            entry = ttk.Entry(form, width=32, justify="right")
            entry.grid(row=i, column=0, padx=8, pady=8)
            fields[key] = entry
            if key == "amount": self.format_money_entry(entry)
        def transfer():
            source_no = fields["source"].get().strip()
            destination_no = fields["destination"].get().strip()
            if not source_no or not destination_no or source_no == destination_no:
                messagebox.showerror("خطا", "شماره حساب مبدأ و مقصد باید معتبر و متفاوت باشند.")
                return
            try:
                amount = float(fields["amount"].get().replace(",", ""))
            except ValueError:
                messagebox.showerror("خطا", "مبلغ معتبر وارد کنید.")
                return
            if amount <= 0:
                messagebox.showerror("خطا", "مبلغ انتقال باید بیشتر از صفر باشد.")
                return
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                source = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (source_no,)).fetchone()
                destination = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (destination_no,)).fetchone()
                if not source or not destination:
                    self.conn.rollback()
                    messagebox.showerror("خطا", "حساب مبدأ یا مقصد پیدا نشد.")
                    return
                if source["status"] != "فعال" or destination["status"] != "فعال":
                    self.conn.rollback()
                    messagebox.showerror("خطا", "حساب مبدأ و مقصد باید فعال باشند.")
                    return
                fee = self.calculate_fee("انتقال وجه", amount, self.root)
                if source["balance"] < amount + fee:
                    self.conn.rollback()
                    messagebox.showerror("خطا", "موجودی حساب مبدأ برای انتقال و کارمزد کافی نیست.")
                    return

                def account_preview(account, role):
                    details = [
                        f"{role}:",
                        f"نام صاحب حساب: {account['full_name']}",
                        f"شماره حساب: {account['account_no']}",
                        f"نوع حساب: {account['account_type']}",
                        f"وضعیت: {account['status']}",
                        f"موجودی فعلی: {account['balance']:,.0f} تومان",
                    ]
                    if account["phone"]:
                        details.append(f"تلفن: {account['phone']}")
                    if account["national_id"]:
                        details.append(f"کد ملی: {account['national_id']}")
                    return "\n".join(details)

                preview_text = (
                    account_preview(source, "حساب مبدأ")
                    + "\n\n"
                    + account_preview(destination, "حساب مقصد")
                    + f"\n\nمبلغ انتقال: {amount:,.0f} تومان"
                    + f"\nکارمزد: {fee:,.0f} تومان"
                    + f"\nمجموع کسر از حساب مبدأ: {amount + fee:,.0f} تومان"
                    + "\n\nآیا اطلاعات صحیح است و انتقال انجام شود؟"
                )
                if not messagebox.askyesno("بررسی مشخصات و تأیید انتقال", preview_text):
                    self.conn.rollback(); return
                self.conn.execute("UPDATE accounts SET balance=balance-? WHERE account_no=?", (amount + fee, source_no))
                self.conn.execute("UPDATE accounts SET balance=balance+? WHERE account_no=?", (amount, destination_no))
                description = fields["description"].get().strip()
                now = datetime.now().isoformat(timespec="seconds")
                username = self.current_user["username"]
                self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                                  (source_no, "انتقال وجه - برداشت", amount, f"به حساب {destination_no}. {description}", now, username))
                self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                                  (destination_no, "انتقال وجه - واریز", amount, f"از حساب {source_no}. {description}", now, username))
                self.credit_fee_fund(source_no, "انتقال وجه", fee, now)
                self.conn.commit()
                new_balance = self.conn.execute("SELECT balance FROM accounts WHERE account_no=?", (source_no,)).fetchone()[0]
                messagebox.showinfo("موفق", f"انتقال وجه با موفقیت ثبت شد.\nموجودی جدید مبدأ: {new_balance:,.0f} تومان")
                for entry in fields.values():
                    entry.delete(0, "end")
                self.dashboard()
            except sqlite3.Error as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"انتقال وجه انجام نشد: {exc}")
        ttk.Button(form, text="ثبت انتقال وجه", command=transfer).grid(row=4, column=0, pady=16)
        ttk.Label(self.content, text="توجه: این انتقال در پایگاه داده محلی برنامه نمونه ثبت می‌شود و به شبکه بانکی متصل نیست.").pack(anchor="e", pady=8)

    def account_report(self):
        """نمایش مشخصات، موجودی و ریز تراکنش‌های یک حساب."""
        self.panel("گزارش حساب")
        bar = ttk.Frame(self.content)
        bar.pack(fill="x", pady=6)
        ttk.Label(bar, text="شماره حساب").pack(side="right", padx=6)
        account_entry = ttk.Entry(bar, width=28, justify="right")
        account_entry.pack(side="right", padx=6)
        summary = ttk.Label(self.content, text="شماره حساب را وارد کنید و گزارش بگیرید.")
        summary.pack(anchor="e", pady=8)
        cols = ("id", "kind", "amount", "description", "created_at", "created_by")
        tree = ttk.Treeview(self.content, columns=cols, show="headings", height=15)
        for col, heading, width in zip(cols, ("شناسه", "نوع عملیات", "مبلغ", "شرح", "زمان", "کاربر"), (65, 145, 110, 300, 165, 110)):
            tree.heading(col, text=heading)
            tree.column(col, width=width, anchor="center")
        tree.pack(fill="both", expand=True, pady=8)

        def load_report():
            no = account_entry.get().strip()
            account = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (no,)).fetchone()
            if not account:
                messagebox.showerror("خطا", "حسابی با این شماره پیدا نشد.")
                return
            summary.config(text=f"صاحب حساب: {account['full_name']} | نوع: {account['account_type']} | وضعیت: {account['status']} | موجودی: {account['balance']:,.2f} | شماره حساب: {no}")
            for item in tree.get_children():
                tree.delete(item)
            rows = self.conn.execute("SELECT id,kind,amount,description,created_at,created_by FROM transactions WHERE account_no=? ORDER BY id DESC", (no,))
            for row in rows:
                tree.insert("", "end", values=(row["id"], row["kind"], f"{row['amount']:,.2f}", row["description"] or "", row["created_at"], row["created_by"]))
        ttk.Button(bar, text="نمایش گزارش", command=load_report).pack(side="right", padx=6)

    def loan_management(self):
        """ثبت وام آزمایشی و دریافت بازپرداخت از حساب مشتری."""
        self.panel("مدیریت پرداخت وام")
        form = ttk.LabelFrame(self.content, text="ثبت تسهیلات جدید", padding=10)
        form.pack(fill="x", pady=5)
        fields = {}
        for i, (label, key) in enumerate((("شماره حساب", "account"), ("مبلغ وام", "amount"), ("شرح / توضیحات", "description"))):
            ttk.Label(form, text=label).grid(row=i, column=1, padx=8, pady=6, sticky="e")
            entry = ttk.Entry(form, width=34, justify="right")
            entry.grid(row=i, column=0, padx=8, pady=6)
            fields[key] = entry
            if key == "amount": self.format_money_entry(entry)

        ttk.Label(form, text="تاریخ ثبت وام (شمسی)").grid(row=3, column=1, padx=8, pady=6, sticky="e")
        loan_date_entry = ttk.Entry(form, width=34, justify="right")
        loan_date_entry.grid(row=3, column=0, padx=8, pady=6)
        loan_date_entry.insert(0, self.jalali_today_text())

        def create_loan():
            try:
                self.jalali_to_gregorian_text(loan_date_entry.get())
            except ValueError as exc:
                messagebox.showerror("خطا", str(exc))
                return
            no = fields["account"].get().strip()
            try:
                amount = float(fields["amount"].get().replace(",", ""))
            except ValueError:
                messagebox.showerror("خطا", "مبلغ وام باید عدد معتبر باشد.")
                return
            if amount <= 0:
                messagebox.showerror("خطا", "مبلغ وام باید بیشتر از صفر باشد.")
                return
            account = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (no,)).fetchone()
            if not account:
                messagebox.showerror("خطا", "حساب پیدا نشد.")
                return
            if account["status"] != "فعال":
                messagebox.showerror("خطا", "برای حساب مسدود نمی‌توان وام ثبت کرد.")
                return
            try:
                now = datetime.now().isoformat(timespec="seconds")
                self.conn.execute("INSERT INTO loans(account_no,principal,outstanding,status,created_at,description) VALUES(?,?,?,'فعال',?,?)",
                                  (no, amount, amount, now, fields["description"].get().strip()))
                self.conn.execute("UPDATE accounts SET balance=balance+? WHERE account_no=?", (amount, no))
                self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                                  (no, "دریافت وام", amount, "واریز وام: " + fields["description"].get().strip(), now, self.current_user["username"]))
                self.conn.commit()
                messagebox.showinfo("موفق", f"تسهیلات به مبلغ {amount:,.2f} ثبت و به حساب واریز شد.")
                for entry in fields.values(): entry.delete(0, "end")
                refresh_loans()
                self.dashboard()
            except sqlite3.Error as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"ثبت وام انجام نشد: {exc}")

        ttk.Button(form, text="ثبت و واریز وام", command=create_loan).grid(row=3, column=0, pady=8)

        repay = ttk.LabelFrame(self.content, text="بازپرداخت تسهیلات", padding=10)
        repay.pack(fill="x", pady=5)
        ttk.Label(repay, text="شناسه تسهیلات").grid(row=0, column=3, padx=6, pady=6)
        loan_id_entry = ttk.Entry(repay, width=12, justify="right")
        loan_id_entry.grid(row=0, column=2, padx=6, pady=6)
        ttk.Label(repay, text="مبلغ قسط").grid(row=0, column=1, padx=6, pady=6)
        repay_amount_entry = ttk.Entry(repay, width=16, justify="right")
        repay_amount_entry.grid(row=0, column=0, padx=6, pady=6)
        self.format_money_entry(repay_amount_entry)

        cols = ("id", "account_no", "principal", "outstanding", "status", "created_at", "description")
        tree = ttk.Treeview(self.content, columns=cols, show="headings", height=9)
        for col, heading, width in zip(cols, ("شناسه تسهیلات", "شماره حساب", "مبلغ اولیه", "مانده بدهی", "وضعیت", "تاریخ", "شرح"), (75, 145, 110, 110, 80, 160, 220)):
            tree.heading(col, text=heading)
            tree.column(col, width=width, anchor="center")
        tree.pack(fill="both", expand=True, pady=6)

        def refresh_loans():
            for item in tree.get_children(): tree.delete(item)
            for row in self.conn.execute("SELECT * FROM loans ORDER BY id DESC"):
                tree.insert("", "end", values=(row["id"], row["account_no"], f"{row['principal']:,.2f}", f"{row['outstanding']:,.2f}", row["status"], row["created_at"], row["description"] or ""))

        def repay_loan():
            try:
                loan_id = int(loan_id_entry.get().strip())
                amount = float(repay_amount_entry.get().strip())
            except ValueError:
                messagebox.showerror("خطا", "شناسه تسهیلات و مبلغ قسط معتبر وارد کنید.")
                return
            if amount <= 0:
                messagebox.showerror("خطا", "مبلغ قسط باید بیشتر از صفر باشد.")
                return
            loan = self.conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
            if not loan or loan["status"] != "فعال":
                messagebox.showerror("خطا", "تسهیلات فعال با این شناسه پیدا نشد.")
                return
            if amount > loan["outstanding"]:
                messagebox.showerror("خطا", "مبلغ قسط از مانده بدهی بیشتر است.")
                return
            account = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (loan["account_no"],)).fetchone()
            if not account or account["status"] != "فعال":
                messagebox.showerror("خطا", "حساب تسهیلات فعال نیست.")
                return
            if account["balance"] < amount:
                messagebox.showerror("خطا", "موجودی حساب برای پرداخت قسط کافی نیست.")
                return
            try:
                now = datetime.now().isoformat(timespec="seconds")
                remaining = round(loan["outstanding"] - amount, 2)
                status = "تسویه‌شده" if remaining <= 0 else "فعال"
                self.conn.execute("UPDATE accounts SET balance=balance-? WHERE account_no=?", (amount, loan["account_no"]))
                self.conn.execute("UPDATE loans SET outstanding=?,status=? WHERE id=?", (remaining, status, loan_id))
                self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                                  (loan["account_no"], "بازپرداخت وام", amount, f"پرداخت قسط تسهیلات شماره {loan_id}", now, self.current_user["username"]))
                self.conn.commit()
                messagebox.showinfo("موفق", f"بازپرداخت ثبت شد. مانده بدهی: {remaining:,.2f}")
                loan_id_entry.delete(0, "end")
                repay_amount_entry.delete(0, "end")
                refresh_loans()
                self.dashboard()
            except sqlite3.Error as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"بازپرداخت انجام نشد: {exc}")

        ttk.Button(repay, text="ثبت بازپرداخت", command=repay_loan).grid(row=0, column=4, padx=8, pady=6)
        ttk.Button(repay, text="انتخاب وام از فهرست", command=lambda: select_loan()).grid(row=0, column=5, padx=8, pady=6)

        def select_loan():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("توجه", "ابتدا یک وام را از فهرست انتخاب کنید.")
                return
            values = tree.item(selected[0], "values")
            loan_id_entry.delete(0, "end")
            loan_id_entry.insert(0, values[0])

        refresh_loans()

    def account_report(self):
        """نمایش مشخصات حساب، مانده، کارت‌ها و تاریخچه تراکنش‌های یک حساب."""
        self.panel("گزارش حساب")
        search = ttk.Frame(self.content)
        search.pack(fill="x", pady=(0, 10))
        ttk.Label(search, text="شماره حساب").pack(side="right", padx=6)
        account_entry = ttk.Entry(search, width=28, justify="right")
        account_entry.pack(side="right", padx=6)
        result = ttk.Frame(self.content)
        result.pack(fill="both", expand=True)

        def show_report():
            account_no = account_entry.get().strip()
            account = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (account_no,)).fetchone()
            if not account:
                messagebox.showerror("خطا", "حسابی با این شماره پیدا نشد.")
                return
            for widget in result.winfo_children():
                widget.destroy()
            summary = ttk.LabelFrame(result, text="اطلاعات حساب", padding=10)
            summary.pack(fill="x", pady=(0, 8))
            details = [
                ("نام صاحب حساب", account["full_name"]), ("شماره حساب", account["account_no"]),
                ("نوع حساب", account["account_type"]), ("وضعیت", account["status"]),
                ("موجودی فعلی", f'{account["balance"]:,.2f}'), ("تلفن", account["phone"] or "—"),
                ("کد ملی", account["national_id"] or "—"), ("تاریخ افتتاح", account["created_at"])
            ]
            for i, (label, value) in enumerate(details):
                ttk.Label(summary, text=f"{label}: {value}").grid(row=i // 2, column=1 - (i % 2), sticky="e", padx=10, pady=4)
            tx_frame = ttk.LabelFrame(result, text="تاریخچه تراکنش‌ها", padding=6)
            tx_frame.pack(fill="both", expand=True, pady=5)
            tx_cols = ("kind", "amount", "description", "created_at", "created_by")
            tx_tree = ttk.Treeview(tx_frame, columns=tx_cols, show="headings", height=7)
            for col, heading, width in zip(tx_cols, ("نوع عملیات", "مبلغ", "شرح", "زمان", "کاربر"), (150, 110, 300, 170, 100)):
                tx_tree.heading(col, text=heading)
                tx_tree.column(col, width=width, anchor="center")
            tx_tree.pack(fill="both", expand=True)
            for row in self.conn.execute("SELECT kind,amount,description,created_at,created_by FROM transactions WHERE account_no=? ORDER BY id DESC", (account_no,)):
                tx_tree.insert("", "end", values=tuple(row[col] for col in tx_cols))
            card_rows = self.conn.execute("SELECT card_no,status,expiry_date FROM cards WHERE account_no=? ORDER BY id DESC", (account_no,)).fetchall()
            loan_rows = self.conn.execute("SELECT id,principal,remaining,status FROM loans WHERE account_no=? ORDER BY id DESC", (account_no,)).fetchall()
            footer = ttk.Frame(result)
            footer.pack(fill="x", pady=6)
            ttk.Label(footer, text=f"تعداد کارت‌ها: {len(card_rows)} | تعداد وام‌ها: {len(loan_rows)} | مانده بدهی وام: {sum(r['remaining'] for r in loan_rows):,.2f}").pack(anchor="e")

        ttk.Button(search, text="تهیه گزارش", command=show_report).pack(side="right", padx=6)
        account_entry.bind("<Return>", lambda event: show_report())

    def loan_management(self):
        """مدیریت تسهیلات، مبلغ‌ها به تومان و پرداخت اقساط."""
        self.panel("مدیریت تسهیلات")
        form = ttk.LabelFrame(self.content, text="ثبت تسهیلات جدید (مبالغ به تومان)", padding=5)
        form.pack(fill="x", pady=(0, 5))
        fields = {}
        field_specs = [
            ("شماره حساب فعال", "account"),
            ("مبلغ تسهیلات (تومان)", "principal"),
            ("نرخ سود کل دوره (%)", "interest_rate"),
            ("قسط ماهیانه (تومان)", "monthly"),
            ("مدت زمان (ماه)", "duration"),
            ("تعداد اقساط", "installments"),
            ("شرح / توضیحات", "notes"),
        ]
        for i, (label, key) in enumerate(field_specs):
            row, col = divmod(i, 4)
            cell = ttk.Frame(form)
            cell.grid(row=row, column=col, padx=4, pady=2, sticky="ew")
            ttk.Label(cell, text=label).pack(anchor="e")
            entry = ttk.Entry(cell, width=18, justify="right")
            entry.pack(fill="x", pady=(3, 0))
            fields[key] = entry
            if key in ("principal", "monthly"): self.format_money_entry(entry)
            form.columnconfigure(col, weight=1)

        # داشبورد خلاصه و ابزار جست‌وجو/فیلتر
        stats = ttk.LabelFrame(self.content, text="خلاصه سبد تسهیلات", padding=4)
        stats.pack(fill="x", pady=(0, 4))
        stats_label = ttk.Label(stats, text="", anchor="e", justify="right", font=(self.ui_font, 9, "bold"))
        stats_label.pack(fill="x")
        filter_bar = ttk.Frame(self.content)
        filter_bar.pack(fill="x", pady=(0, 3))
        ttk.Label(filter_bar, text="جست‌وجو (شناسه / حساب / شرح):").pack(side="right", padx=5)
        search_entry = ttk.Entry(filter_bar, width=20, justify="right")
        search_entry.pack(side="right", padx=5)
        status_filter = ttk.Combobox(filter_bar, values=("همه وضعیت‌ها", "فعال", "تسویه‌شده"), state="readonly", width=12, justify="right")
        status_filter.set("همه وضعیت‌ها")
        status_filter.pack(side="right", padx=5)

        cols = ("id", "account_no", "principal", "remaining", "monthly_payment", "duration_months", "installment_count", "status", "created_at", "interest_rate")
        tree = ttk.Treeview(self.content, columns=cols, show="headings", height=5)
        headings = ("شناسه تسهیلات", "شماره حساب", "مبلغ اولیه (تومان)", "مانده بدهی (تومان)", "قسط ماهیانه (تومان)", "مدت (ماه)", "تعداد اقساط", "وضعیت", "تاریخ ثبت", "سود (%)")
        widths = (70, 115, 130, 135, 145, 85, 90, 85, 150, 75)
        for col, heading, width in zip(cols, headings, widths):
            tree.heading(col, text=heading)
            tree.column(col, width=width, anchor="center")
        tree.pack(fill="both", expand=True)

        def refresh():
            for item in tree.get_children():
                tree.delete(item)
            all_rows = self.conn.execute("SELECT id,account_no,principal,remaining,monthly_payment,duration_months,installment_count,status,created_at,interest_rate,notes FROM loans ORDER BY id DESC").fetchall()
            total_principal = sum(float(r["principal"] or 0) for r in all_rows)
            total_remaining = sum(float(r["remaining"] or 0) for r in all_rows)
            active_count = sum(1 for r in all_rows if r["status"] == "فعال")
            stats_label.config(text=f"تعداد کل: {len(all_rows)}  |  فعال: {active_count}  |  تسویه‌شده: {len(all_rows)-active_count}  |  مجموع اصل: {total_principal:,.0f} تومان  |  مانده کل: {total_remaining:,.0f} تومان")
            query = search_entry.get().strip().lower()
            status = status_filter.get()
            for row in all_rows:
                haystack = f'{row["id"]} {row["account_no"]} {row["notes"] or ""}'.lower()
                if query and query not in haystack:
                    continue
                if status != "همه وضعیت‌ها" and row["status"] != status:
                    continue
                tree.insert("", "end", values=(row["id"], row["account_no"], f'{row["principal"]:,.0f}', f'{row["remaining"]:,.0f}', f'{row["monthly_payment"]:,.0f}', row["duration_months"], row["installment_count"], row["status"], row["created_at"], f'{row["interest_rate"]:.2f}%'))

        def export_loans_csv():
            import csv
            path = filedialog.asksaveasfilename(parent=self.root, title="ذخیره گزارش تسهیلات", defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="royal_bank_loans.csv")
            if not path:
                return
            try:
                rows = self.conn.execute("SELECT id,account_no,principal,remaining,monthly_payment,duration_months,installment_count,status,created_at,interest_rate,notes FROM loans ORDER BY id DESC").fetchall()
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["شناسه", "شماره حساب", "اصل تسهیلات", "مانده بدهی", "قسط ماهیانه", "مدت ماه", "تعداد اقساط", "وضعیت", "تاریخ ثبت", "نرخ سود کل دوره", "شرح"])
                    for row in rows:
                        writer.writerow([row[k] for k in ("id","account_no","principal","remaining","monthly_payment","duration_months","installment_count","status","created_at","interest_rate","notes")])
                messagebox.showinfo("گزارش آماده شد", f"گزارش تسهیلات ذخیره شد:\\n{path}")
            except OSError as exc:
                messagebox.showerror("خطا", f"ذخیره گزارش انجام نشد: {exc}")

        search_entry.bind("<KeyRelease>", lambda _event: refresh())
        status_filter.bind("<<ComboboxSelected>>", lambda _event: refresh())

        def grant_loan():
            account_no = fields["account"].get().strip()
            try:
                principal = float(fields["principal"].get().replace(",", ""))
                monthly = float(fields["monthly"].get().replace(",", "") or 0)
                interest_rate = float(fields["interest_rate"].get().replace(",", "") or 0)
                duration = int(fields["duration"].get() or 0)
                installments = int(fields["installments"].get() or 0)
            except ValueError:
                messagebox.showerror("خطا", "مبلغ‌ها باید عددی و مدت و تعداد اقساط باید عدد صحیح باشند.")
                return
            if principal <= 0 or monthly < 0 or interest_rate < 0 or duration <= 0 or installments <= 0:
                messagebox.showerror("خطا", "مبلغ وام باید مثبت باشد و مدت و تعداد اقساط نیز باید بیشتر از صفر باشند.")
                return
            total_due = round(principal * (1 + interest_rate / 100), 2)
            if monthly == 0:
                monthly = round(total_due / installments, 0)
                fields["monthly"].delete(0, "end")
                fields["monthly"].insert(0, str(int(monthly)))
            account = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (account_no,)).fetchone()
            if not account:
                messagebox.showerror("خطا", "حساب موردنظر پیدا نشد.")
                return
            if account["status"] != "فعال":
                messagebox.showerror("خطا", "برای حساب مسدود نمی‌توان وام ثبت کرد.")
                return
            now = datetime.now().isoformat(timespec="seconds")
            try:
                fee = self.calculate_fee("پرداخت تسهیلات", principal, self.root)
                if fee > principal: raise ValueError("کارمزد تسهیلات نمی‌تواند از اصل وام بیشتر باشد.")
                net_principal = principal - fee
                if not messagebox.askyesno("تأیید پرداخت تسهیلات", f"اصل تسهیلات: {principal:,.0f} تومان\nکارمزد: {fee:,.0f} تومان\nواریز خالص به حساب: {net_principal:,.0f} تومان؟"): return
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute("INSERT INTO loans(account_no,principal,remaining,monthly_payment,duration_months,installment_count,status,created_at,created_by,notes,interest_rate) VALUES(?,?,?,?,?,?,'فعال',?,?,?,?)",
                                  (account_no, principal, total_due, monthly, duration, installments, now, self.current_user["username"], fields["notes"].get().strip(), interest_rate))
                self.conn.execute("UPDATE accounts SET balance=balance+? WHERE account_no=?", (net_principal, account_no))
                self.sync_fund_with_account_delta(net_principal, "واریز خالص تسهیلات")
                self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                                  (account_no, "پرداخت وام", net_principal, f"اصل تسهیلات {principal:,.0f}؛ کارمزد {fee:,.0f}", now, self.current_user["username"]))
                self.credit_fee_fund(account_no, "پرداخت تسهیلات", fee, now)
                self.conn.commit()
                messagebox.showinfo("موفق", f"تسهیلات به مبلغ {principal:,.0f} تومان ثبت شد. کارمزد: {fee:,.0f} تومان | واریز خالص: {net_principal:,.0f} تومان | سود کل دوره: {interest_rate:.2f}% ({total_due-principal:,.0f} تومان) | کل بازپرداخت: {total_due:,.0f} تومان | قسط ماهیانه: {monthly:,.0f} تومان")
                for entry in fields.values():
                    entry.delete(0, "end")
                refresh()
            except sqlite3.Error as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"ثبت وام ناموفق بود: {exc}")

        def repay_loan():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("توجه", "ابتدا یک وام را از فهرست انتخاب کنید.")
                return
            loan_id = int(tree.item(selected[0], "values")[0])
            loan = self.conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
            if not loan or loan["remaining"] <= 0:
                messagebox.showinfo("اطلاع", "برای این وام بدهی باقی نمانده است.")
                return
            win = tk.Toplevel(self.root)
            win.title("پرداخت اقساط وام")
            win.geometry("390x230")
            win.transient(self.root)
            win.grab_set()
            ttk.Label(win, text=f"مانده بدهی با احتساب سود: {loan['remaining']:,.0f} تومان").pack(pady=(14, 5))
            ttk.Label(win, text=f"نرخ سود کل دوره: {float(loan['interest_rate'] or 0):.2f}%").pack(pady=3)
            ttk.Label(win, text=f"قسط ماهیانه: {loan['monthly_payment']:,.0f} تومان").pack(pady=3)
            ttk.Label(win, text="مبلغ پرداخت قسط (تومان)").pack(pady=(6, 0))
            amount_entry = ttk.Entry(win, width=25, justify="right")
            amount_entry.pack(pady=6)
            self.format_money_entry(amount_entry)
            amount_entry.insert(0, str(round(min(loan["monthly_payment"] or loan["remaining"], loan["remaining"]))))

            def submit_repayment():
                try:
                    amount = float(amount_entry.get().replace(",", ""))
                except ValueError:
                    messagebox.showerror("خطا", "مبلغ پرداخت را به تومان و به‌صورت عددی وارد کنید.", parent=win)
                    return
                if amount <= 0 or amount > loan["remaining"]:
                    messagebox.showerror("خطا", "مبلغ باید مثبت و حداکثر برابر مانده بدهی باشد.", parent=win)
                    return
                fee = self.calculate_fee("پرداخت اقساط", amount, win)
                account = self.conn.execute("SELECT * FROM accounts WHERE account_no=?", (loan["account_no"],)).fetchone()
                if not account or account["balance"] < amount + fee:
                    messagebox.showerror("خطا", "موجودی حساب برای پرداخت قسط و کارمزد کافی نیست.", parent=win)
                    return
                if not messagebox.askyesno("تأیید پرداخت قسط", f"مبلغ قسط: {amount:,.0f} تومان\nکارمزد: {fee:,.0f} تومان\nمجموع کسر: {amount+fee:,.0f} تومان؟", parent=win): return
                now = datetime.now().isoformat(timespec="seconds")
                remaining = round(loan["remaining"] - amount, 2)
                try:
                    self.conn.execute("BEGIN IMMEDIATE")
                    self.conn.execute("UPDATE accounts SET balance=balance-? WHERE account_no=?", (amount + fee, loan["account_no"]))
                    self.sync_fund_with_account_delta(-(amount + fee), "پرداخت قسط")
                    self.conn.execute("UPDATE loans SET remaining=?,status=? WHERE id=?", (remaining, "تسویه‌شده" if remaining <= 0 else "فعال", loan_id))
                    self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                                      (loan["account_no"], "پرداخت قسط وام", -amount, f"پرداخت قسط تسهیلات شماره {loan_id}", now, self.current_user["username"]))
                    self.credit_fee_fund(loan["account_no"], "پرداخت اقساط", fee, now)
                    self.conn.commit()
                    win.destroy()
                    refresh()
                    messagebox.showinfo("موفق", f"پرداخت قسط ثبت شد. مبلغ: {amount:,.0f} تومان | کارمزد: {fee:,.0f} تومان | مانده بدهی: {remaining:,.0f} تومان")
                except sqlite3.Error as exc:
                    self.conn.rollback()
                    messagebox.showerror("خطا", f"ثبت پرداخت قسط ناموفق بود: {exc}", parent=win)
            ttk.Button(win, text="ثبت پرداخت قسط", command=submit_repayment).pack(pady=8)

        def selected_loan():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("توجه", "ابتدا یک وام را از فهرست انتخاب کنید.")
                return None
            loan_id = int(tree.item(selected[0], "values")[0])
            return self.conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()

        def edit_loan():
            loan = selected_loan()
            if not loan:
                return
            win = tk.Toplevel(self.root)
            win.title("ویرایش وام")
            win.geometry("430x330")
            win.transient(self.root)
            win.grab_set()
            edit_fields = {}
            specs = [("مبلغ تسهیلات (تومان)", "principal", loan["principal"]),
                     ("نرخ سود کل دوره (%)", "interest_rate", loan["interest_rate"]),
                     ("قسط ماهیانه (تومان)", "monthly_payment", loan["monthly_payment"]),
                     ("مدت زمان (ماه)", "duration_months", loan["duration_months"]),
                     ("تعداد اقساط", "installment_count", loan["installment_count"]),
                     ("شرح / توضیحات", "notes", loan["notes"] or "")]
            for i, (label, key, value) in enumerate(specs):
                ttk.Label(win, text=label).grid(row=i, column=1, padx=10, pady=7, sticky="e")
                entry = ttk.Entry(win, width=28, justify="right")
                entry.grid(row=i, column=0, padx=10, pady=7)
                if key in ("principal", "monthly_payment"): self.format_money_entry(entry)
                entry.insert(0, str(value))
                edit_fields[key] = entry

            def save_edit():
                try:
                    principal = float(edit_fields["principal"].get().replace(",", ""))
                    monthly = float(edit_fields["monthly_payment"].get().replace(",", ""))
                    interest_rate = float(edit_fields["interest_rate"].get().replace(",", "") or 0)
                    duration = int(edit_fields["duration_months"].get())
                    installments = int(edit_fields["installment_count"].get())
                except ValueError:
                    messagebox.showerror("خطا", "مبالغ باید عددی و مدت و تعداد اقساط عدد صحیح باشند.", parent=win)
                    return
                if principal <= 0 or monthly < 0 or interest_rate < 0 or duration <= 0 or installments <= 0:
                    messagebox.showerror("خطا", "مبلغ وام، مدت و تعداد اقساط باید مثبت باشند.", parent=win)
                    return
                # مانده بدهی با حفظ مبلغ اقساط پرداخت‌شده متناسب با تغییر اصل وام اصلاح می‌شود.
                old_total_due = float(loan["principal"]) * (1 + float(loan["interest_rate"] or 0) / 100)
                paid = max(0, old_total_due - float(loan["remaining"]))
                new_total_due = round(principal * (1 + interest_rate / 100), 2)
                new_remaining = max(0, new_total_due - paid)
                delta = principal - float(loan["principal"])
                try:
                    self.conn.execute("BEGIN IMMEDIATE")
                    self.conn.execute("UPDATE loans SET principal=?,remaining=?,monthly_payment=?,duration_months=?,installment_count=?,notes=?,interest_rate=?,status=? WHERE id=?",
                                      (principal, new_remaining, monthly, duration, installments, edit_fields["notes"].get().strip(), interest_rate, "تسویه‌شده" if new_remaining <= 0 else "فعال", loan["id"]))
                    if abs(delta) > 0.0001:
                        self.conn.execute("UPDATE accounts SET balance=balance+? WHERE account_no=?", (delta, loan["account_no"]))
                        self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                                          (loan["account_no"], "اصلاح مبلغ وام", delta, f"ویرایش تسهیلات شماره {loan['id']}", datetime.now().isoformat(timespec="seconds"), self.current_user["username"]))
                    self.conn.commit()
                    win.destroy()
                    refresh()
                    messagebox.showinfo("موفق", "اطلاعات وام و مانده بدهی به‌روزرسانی شد.")
                except sqlite3.Error as exc:
                    self.conn.rollback()
                    messagebox.showerror("خطا", f"ویرایش وام ناموفق بود: {exc}", parent=win)
            ttk.Button(win, text="ذخیره تغییرات", command=save_edit).grid(row=len(specs), column=0, columnspan=2, pady=12)

        def delete_loan():
            loan = selected_loan()
            if not loan:
                return
            loan_id = loan["id"]
            repayments = self.conn.execute("SELECT COUNT(*) FROM transactions WHERE kind='پرداخت قسط وام' AND description LIKE ?", (f"%شماره {loan_id}%",)).fetchone()[0]
            if repayments:
                messagebox.showerror("امکان حذف نیست", "برای این وام سابقه پرداخت قسط وجود دارد. برای حفظ سوابق مالی، حذف آن مجاز نیست.")
                return
            account = self.conn.execute("SELECT balance FROM accounts WHERE account_no=?", (loan["account_no"],)).fetchone()
            if not account or account["balance"] < loan["principal"]:
                messagebox.showerror("امکان حذف نیست", "موجودی حساب برای برگشت مبلغ وام کافی نیست.")
                return
            if not messagebox.askyesno("تأیید حذف", f"تسهیلات شماره {loan_id} حذف شود؟ مبلغ وام از موجودی حساب کسر خواهد شد."):
                return
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute("UPDATE accounts SET balance=balance-? WHERE account_no=?", (loan["principal"], loan["account_no"]))
                self.conn.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",
                                  (loan["account_no"], "حذف وام", loan["principal"], f"حذف تسهیلات شماره {loan_id}", datetime.now().isoformat(timespec="seconds"), self.current_user["username"]))
                self.conn.execute("DELETE FROM loans WHERE id=?", (loan_id,))
                self.conn.commit()
                refresh()
                messagebox.showinfo("موفق", "تسهیلات حذف شد و عملیات در تاریخچه ثبت گردید.")
            except sqlite3.Error as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"حذف وام ناموفق بود: {exc}")

        # دکمه ثبت در ردیف مستقل قرار می‌گیرد تا با فیلدهای فرم تداخل نداشته باشد.
        loan_button_style = "LoanAction.TButton"
        ttk.Style(self.root).configure(loan_button_style, font=(self.ui_font, 8), padding=(3, 2))
        submit_row = ttk.Frame(form)
        submit_row.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 1))
        ttk.Button(submit_row, text="ثبت و پرداخت تسهیلات", command=grant_loan,
                   style=loan_button_style, width=20).pack(side="right", padx=3)

        # دکمه پرداخت قسط همیشه بالای جدول و کاملاً قابل مشاهده باشد.
        pay_bar = ttk.Frame(self.content)
        pay_bar.pack(fill="x", pady=(3, 2), before=tree)
        pay_style = "LoanPay.TButton"
        ttk.Style(self.root).configure(pay_style, font=(self.ui_font, 9, "bold"), padding=(4, 3))
        ttk.Button(pay_bar, text="💳 پرداخت قسط تسهیلات انتخاب‌شده", command=repay_loan,
                   style=pay_style).pack(fill="x", padx=2, pady=1)

        # سایر عملیات کوچک‌تر و مرتب در دو ستون، پایین جدول.
        buttons = ttk.Frame(self.content)
        buttons.pack(fill="x", pady=(3, 4))
        action_specs = [
            ("ویرایش تسهیلات انتخاب‌شده", edit_loan),
            ("حذف تسهیلات انتخاب‌شده", delete_loan),
            ("به‌روزرسانی فهرست", refresh),
            ("خروجی گزارش CSV", export_loans_csv),
        ]
        for index, (label, command) in enumerate(action_specs):
            row, col = divmod(index, 4)
            btn = ttk.Button(buttons, text=label, command=command, style=loan_button_style, width=18)
            btn.grid(row=row, column=col, padx=4, pady=3, sticky="ew")
            buttons.columnconfigure(col, weight=1, uniform="loan_actions")
        ttk.Label(self.content, text="تمام مبلغ‌های این بخش به تومان هستند.").pack(anchor="e", pady=1)
        refresh()

    def sim_recharge_management(self):
        """ثبت و گزارش خرید شارژ؛ خرید واقعی اپراتور بدون اتصال درون‌برنامه‌ای انجام نمی‌شود."""
        self.panel("مدیریت خرید شارژ سیم‌کارت")
        form = ttk.LabelFrame(self.content, text="ثبت خرید شارژ (تومان)", padding=10)
        form.pack(fill="x", pady=(0, 8))
        fields = {}
        specs = [("شماره سیم‌کارت", "phone"), ("اپراتور", "carrier"), ("مبلغ شارژ (تومان)", "amount"),
                 ("نوع شارژ", "kind"), ("کد شارژ", "code"), ("توضیحات", "notes")]
        for i, (label, key) in enumerate(specs):
            row, col = divmod(i, 3)
            cell = ttk.Frame(form)
            cell.grid(row=row, column=col, padx=8, pady=5, sticky="ew")
            ttk.Label(cell, text=label).pack(anchor="e")
            if key == "carrier":
                entry = ttk.Combobox(cell, values=("همراه اول", "ایرانسل", "رایتل", "شاتل موبایل", "سایر"), state="readonly", width=23, justify="right")
                entry.set("همراه اول")
            elif key == "kind":
                entry = ttk.Combobox(cell, values=("شارژ مستقیم", "کد شارژ"), state="readonly", width=23, justify="right")
                entry.set("شارژ مستقیم")
            else:
                entry = ttk.Entry(cell, width=25, justify="right")
            if key == "amount": self.format_money_entry(entry)
            entry.pack(fill="x", pady=(3, 0))
            fields[key] = entry
            form.columnconfigure(col, weight=1)

        cols = ("id", "phone_number", "carrier", "amount", "recharge_type", "recharge_code", "created_at", "created_by", "notes")
        tree = ttk.Treeview(self.content, columns=cols, show="headings", height=10)
        heads = ("شناسه", "شماره سیم‌کارت", "اپراتور", "مبلغ (تومان)", "نوع شارژ", "کد شارژ", "تاریخ ثبت", "ثبت‌کننده", "توضیحات")
        widths = (55, 120, 90, 110, 90, 130, 145, 90, 160)
        for col, heading, width in zip(cols, heads, widths):
            tree.heading(col, text=heading)
            tree.column(col, width=width, anchor="center")
        tree.pack(fill="both", expand=True, pady=5)

        def refresh_recharges():
            for item in tree.get_children():
                tree.delete(item)
            for row in self.conn.execute("SELECT id,phone_number,carrier,amount,recharge_type,recharge_code,created_at,created_by,notes FROM sim_recharges ORDER BY id DESC"):
                tree.insert("", "end", values=(row["id"], row["phone_number"], row["carrier"], f'{row["amount"]:,.0f}', row["recharge_type"], row["recharge_code"] or "", row["created_at"], row["created_by"], row["notes"] or ""))

        def save_recharge():
            phone = fields["phone"].get().strip()
            try:
                amount = float(fields["amount"].get().replace(",", ""))
            except ValueError:
                messagebox.showerror("خطا", "مبلغ شارژ را به تومان و به‌صورت عددی وارد کنید.")
                return
            kind = fields["kind"].get()
            code = fields["code"].get().strip()
            if not phone or not phone.isdigit() or len(phone) < 10 or amount <= 0:
                messagebox.showerror("خطا", "شماره سیم‌کارت معتبر و مبلغ شارژ مثبت وارد کنید.")
                return
            if kind == "کد شارژ" and not code:
                messagebox.showerror("خطا", "برای نوع «کد شارژ»، کد شارژ را وارد کنید.")
                return
            if kind == "شارژ مستقیم":
                code = ""
            now = datetime.now().isoformat(timespec="seconds")
            try:
                self.conn.execute("INSERT INTO sim_recharges(phone_number,carrier,amount,recharge_type,recharge_code,created_at,created_by,notes) VALUES(?,?,?,?,?,?,?,?)",
                                  (phone, fields["carrier"].get(), amount, kind, code, now, self.current_user["username"], fields["notes"].get().strip()))
                self.conn.commit()
                refresh_recharges()
                messagebox.showinfo("ثبت شد", "رکورد خرید شارژ با موفقیت ثبت شد. شارژ واقعی سیم‌کارت نیازمند اتصال به درگاه یا سرویس اپراتور است.")
                for key in ("phone", "amount", "code", "notes"):
                    fields[key].delete(0, "end")
            except sqlite3.Error as exc:
                self.conn.rollback()
                messagebox.showerror("خطا", f"ثبت رکورد شارژ ناموفق بود: {exc}")

        controls = ttk.Frame(self.content)
        controls.pack(fill="x", pady=7)
        ttk.Button(controls, text="ثبت خرید شارژ", command=save_recharge).pack(side="right", padx=4)
        ttk.Button(controls, text="به‌روزرسانی فهرست", command=refresh_recharges).pack(side="right", padx=4)
        ttk.Label(self.content, text="برای شارژ واقعی باید سرویس پرداخت/اپراتور متصل شود.").pack(anchor="e", pady=4)
        refresh_recharges()

    def transaction_history(self):
        """نمایش گردش حساب با چیدمان واکنش‌گرا و دکمه‌های همیشه در دسترس."""
        win = tk.Toplevel(self.root)
        win.title("گردش حساب")
        win.geometry("1180x680")
        win.minsize(820, 480)
        # پنجره در شروع بزرگ می‌شود تا جدول و دکمه‌ها در صفحه‌های معمولی بهتر دیده شوند.
        try:
            win.state("zoomed")
        except tk.TclError:
            pass

        top = ttk.Frame(win, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="گردش حساب — مرتب‌شده بر اساس جدیدترین تاریخ و ساعت",
                  font=("Tahoma", 11, "bold")).pack(side="right", padx=6)

        # دکمه‌ها در نوار بالایی قرار دارند تا با بزرگ شدن جدول از دید خارج نشوند.
        actions = ttk.Frame(win, padding=(8, 4))
        actions.pack(fill="x", side="top")

        summary = ttk.Label(win, text="", anchor="e", padding=(10, 5), justify="right")
        summary.pack(fill="x")

        table_frame = ttk.Frame(win, padding=(8, 4))
        table_frame.pack(fill="both", expand=True)
        cols = ("id", "account_no", "kind", "amount", "description", "created_at", "created_by")
        tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        heads = {"id":"شماره سند", "account_no":"شماره حساب", "kind":"نوع تراکنش",
                 "amount":"مبلغ (تومان)", "description":"شرح تراکنش",
                 "created_at":"تاریخ شمسی و ساعت", "created_by":"ثبت‌کننده"}
        widths = {"id":70, "account_no":105, "kind":115, "amount":105,
                  "description":250, "created_at":165, "created_by":90}
        for c in cols:
            tree.heading(c, text=heads[c])
            tree.column(c, width=widths[c], minwidth=60, anchor="center", stretch=(c == "description"))
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        tree.tag_configure("even", background="#f2f6fb")
        tree.tag_configure("odd", background="#ffffff")

        records = []
        for r in self.conn.execute(
                "SELECT id,document_no,account_no,kind,amount,description,created_at,created_by "
                "FROM transactions ORDER BY created_at DESC, id DESC"):
            raw_created_at = r["created_at"] or ""
            try:
                # پشتیبانی از هر دو قالب ISO با فاصله و ISO با حرف T.
                created_dt = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
                jy, jm, jd = self.jalali_date(created_dt)
                shown_created_at = f"{jy:04d}/{jm:02d}/{jd:02d}  {created_dt.strftime('%H:%M:%S')}"
            except (ValueError, TypeError):
                shown_created_at = raw_created_at
            values = (r["document_no"] or r["id"], r["account_no"], r["kind"],
                      f"{float(r['amount'] or 0):,.0f}", r["description"] or "",
                      shown_created_at, r["created_by"] or "")
            records.append(values)
            tree.insert("", "end", values=values,
                        tags=("even" if len(records) % 2 == 0 else "odd",))

        total_in = sum(float(r[3] or 0) for r in records if float(r[3] or 0) > 0)
        total_out = abs(sum(float(r[3] or 0) for r in records if float(r[3] or 0) < 0))
        summary_text = (f"تعداد تراکنش‌ها: {len(records):,}    |    "
                        f"جمع واریزها: {total_in:,.0f} تومان    |    "
                        f"جمع برداشت‌ها: {total_out:,.0f} تومان")
        summary.config(text=summary_text)

        def print_history():
            labels = [heads[c] for c in cols]
            table_rows = "".join(
                "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>"
                for row in records)
            header = "".join(f"<th>{html.escape(label)}</th>" for label in labels)
            doc = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
            <title>چاپ گردش حساب رویال</title><style>
            body{{font-family:Tahoma,Arial,sans-serif;margin:22px;color:#20364d}}
            h2{{text-align:center;margin-bottom:8px}}.summary{{text-align:center;margin:12px 0 18px}}
            table{{width:100%;border-collapse:collapse;font-size:10px}}
            th,td{{border:1px solid #9aa9b8;padding:7px;text-align:center;word-break:break-word}}
            th{{background:#e8eff6}}tr:nth-child(even){{background:#f5f8fb}}
            @media print{{body{{margin:8mm}}button{{display:none}}}}
            </style></head><body><h2>قرض‌الحسنه رویال بانک — گردش حساب</h2>
            <div class="summary">{html.escape(summary_text)}</div>
            <table><thead><tr>{header}</tr></thead><tbody>{table_rows}</tbody></table>
            <p>تاریخ تهیه گزارش (شمسی): {html.escape(self.jalali_today_text())} — ساعت: {html.escape(datetime.now().strftime('%H:%M:%S'))}</p>
            <button onclick="window.print()">چاپ گزارش</button>
            <script>window.onload=()=>window.print()</script></body></html>"""
            output = APP_DIR / "account_transaction_history.html"
            try:
                output.write_text(doc, encoding="utf-8")
                webbrowser.open(output.resolve().as_uri())
            except OSError as exc:
                messagebox.showerror("خطا", f"ساخت گزارش چاپی ناموفق بود: {exc}", parent=win)

        ttk.Button(actions, text="چاپ گردش حساب", command=print_history).pack(side="right", padx=5, pady=2)
        ttk.Button(actions, text="بستن", command=win.destroy).pack(side="left", padx=5, pady=2)

    def users(self):
        if self.current_user["role"]!="مدیر":
            messagebox.showwarning("دسترسی محدود","فقط مدیر می‌تواند کاربران را مدیریت کند."); return
        self.panel("مدیریت کاربران")
        form=ttk.Frame(self.content); form.pack(anchor="e",pady=8)
        fields={}
        for i,(label,key) in enumerate([("نام کاربری","username"),("رمز عبور","password")]):
            ttk.Label(form,text=label).grid(row=i,column=1,padx=8,pady=8)
            e=ttk.Entry(form,width=28,justify="right",show="*" if key=="password" else ""); e.grid(row=i,column=0,padx=8,pady=8); fields[key]=e
        role=ttk.Combobox(form,values=["کارمند","مدیر"],state="readonly",width=25,justify="right"); role.grid(row=2,column=0,padx=8,pady=8); role.set("کارمند")
        ttk.Label(form,text="نقش").grid(row=2,column=1,padx=8,pady=8)
        def add():
            username=fields["username"].get().strip(); password=fields["password"].get()
            if len(username)<3 or len(password)<8:
                messagebox.showerror("خطا","نام کاربری حداقل ۳ و رمز عبور حداقل ۸ نویسه باشد."); return
            salt,digest=hash_password(password)
            try:
                self.conn.execute("INSERT INTO users(username,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,1,?)",
                    (username,digest,salt,role.get(),datetime.now().isoformat(timespec="seconds")))
                self.conn.commit(); messagebox.showinfo("موفق","کاربر اضافه شد."); self.users()
            except sqlite3.IntegrityError: messagebox.showerror("خطا","این نام کاربری قبلاً ثبت شده است.")
        ttk.Button(form,text="افزودن کاربر",command=add).grid(row=3,column=0,pady=12)
        tree=ttk.Treeview(self.content,columns=("id","username","role","active","created"),show="headings",height=8)
        for c,h in zip(("id","username","role","active","created"),("شناسه","نام کاربری","نقش","فعال","زمان ایجاد")):
            tree.heading(c,text=h); tree.column(c,width=150,anchor="center")
        tree.pack(fill="both",expand=True,pady=10)
        for r in self.conn.execute("SELECT id,username,role,active,created_at FROM users"):
            tree.insert("","end",values=(r["id"],r["username"],r["role"],"بله" if r["active"] else "خیر",r["created_at"]))
        def toggle():
            sel=tree.selection()
            if not sel: return
            vals=tree.item(sel[0],"values"); uid=int(vals[0])
            if uid==self.current_user["id"]: messagebox.showwarning("توجه","نمی‌توانید حساب کاربری خودتان را غیرفعال کنید."); return
            self.conn.execute("UPDATE users SET active=1-active WHERE id=?",(uid,)); self.conn.commit(); self.users()
        ttk.Button(self.content,text="فعال/غیرفعال کردن کاربر انتخاب‌شده",command=toggle).pack(anchor="e")

    def data_backup_restore(self):
        """یکپارچه‌سازی پشتیبان‌گیری و بازیابی اطلاعات در یک بخش."""
        self.panel("پشتیبان‌گیری و بازیابی اطلاعات")
        box = ttk.LabelFrame(self.content, text="مدیریت نسخه‌های پشتیبان", padding=18)
        box.pack(fill="x", padx=12, pady=12)
        ttk.Label(
            box,
            text="برای حفظ اطلاعات، نسخه پشتیبان تهیه کنید یا اطلاعات را از یک فایل پشتیبان معتبر بازیابی کنید.",
            wraplength=650, justify="right"
        ).pack(anchor="e", pady=(0, 8))
        ttk.Label(
            box,
            text=f"تاریخ امروز / تاریخ تهیه پشتیبان (شمسی): {self.jalali_today_text()}",
            foreground="#526579", justify="right"
        ).pack(anchor="e", pady=(0, 12))
        controls = ttk.Frame(box)
        controls.pack(anchor="e", fill="x")
        ttk.Button(controls, text="تهیه نسخه پشتیبان", command=self.backup).pack(side="right", padx=6)
        ttk.Button(controls, text="بازیابی از نسخه پشتیبان", command=self.restore_data).pack(side="right", padx=6)
        ttk.Label(
            self.content,
            text="هنگام بازیابی، اطلاعات فعلی جایگزین می‌شود؛ قبل از ادامه، نسخه احتیاطی تهیه خواهد شد.",
            foreground="#a35b00", wraplength=700, justify="right"
        ).pack(anchor="e", padx=12, pady=8)

    def backup(self):
        path=filedialog.asksaveasfilename(title="ذخیره نسخه پشتیبان",defaultextension=".db",
             filetypes=[("SQLite database","*.db"),("All files","*.*")],
             initialfile=f"bank_backup_{self.jalali_today_text().replace('/', '-')}.db")
        if not path: return
        try:
            self.conn.commit()
            target=sqlite3.connect(path)
            self.conn.backup(target)
            target.close()
            messagebox.showinfo("موفق","نسخه پشتیبان ذخیره شد.")
        except Exception as e: messagebox.showerror("خطا",f"پشتیبان‌گیری ناموفق بود:\n{e}")

    def restore_data(self):
        """بازیابی پایگاه‌داده از یک فایل پشتیبان SQLite."""
        path = filedialog.askopenfilename(
            title="انتخاب فایل پشتیبان برای بازیابی",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")]
        )
        if not path:
            return
        if not messagebox.askyesno(
            "تأیید بازیابی",
            "بازیابی، اطلاعات فعلی برنامه را با اطلاعات فایل پشتیبان جایگزین می‌کند.\n"
            "پیش از ادامه، از اطلاعات فعلی نسخه پشتیبان بگیرید. ادامه می‌دهید؟"
        ):
            return
        source = None
        try:
            source = sqlite3.connect(path)
            tables = {row[0] for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            required = {"users", "accounts", "transactions", "cards"}
            if not required.issubset(tables):
                raise ValueError("این فایل، پشتیبان معتبر سامانه مدیریت بانک نیست.")
            # پایگاه داده فعلی پیش از جایگزینی به‌صورت خودکار پشتیبان گرفته می‌شود.
            safety_path = APP_DIR / ("bank_before_restore_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db")
            safety = sqlite3.connect(safety_path)
            self.conn.backup(safety)
            safety.close()
            source.backup(self.conn)
            self.conn.execute("""CREATE TABLE IF NOT EXISTS loans(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_no TEXT NOT NULL,
                principal REAL NOT NULL,
                remaining REAL NOT NULL,
                monthly_payment REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'فعال',
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                notes TEXT)""")
            self.conn.commit()
            messagebox.showinfo("موفق", f"بازیابی اطلاعات انجام شد.\nنسخه احتیاطی اطلاعات قبلی: {safety_path}")
            self.show_main()
        except (sqlite3.Error, OSError, ValueError) as exc:
            messagebox.showerror("خطا در بازیابی", str(exc))
        finally:
            if source is not None:
                source.close()

    def update_program(self):
        """به‌روزرسانی دستی فایل برنامه با تهیه نسخه پشتیبان از نسخه فعلی."""
        win = tk.Toplevel(self.root)
        win.title("به‌روزرسانی برنامه")
        win.geometry("540x250")
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text="به‌روزرسانی سامانه رویال بانک", style="Title.TLabel").pack(pady=(18, 8))
        ttk.Label(win, text="فایل نسخه جدید برنامه (bank_manager.py) را انتخاب کنید.\n"
                            "قبل از جایگزینی، از فایل فعلی نسخه پشتیبان گرفته می‌شود.",
                  justify="center").pack(padx=18, pady=8)

        def choose_update():
            selected = filedialog.askopenfilename(
                parent=win,
                title="انتخاب فایل نسخه جدید برنامه",
                filetypes=[("Python files", "*.py"), ("All files", "*.*")]
            )
            if not selected:
                return
            source = Path(selected).resolve()
            current = Path(__file__).resolve()
            if source == current:
                messagebox.showwarning("توجه", "این فایل همین نسخه در حال اجرا است؛ فایل نسخه جدید را انتخاب کنید.", parent=win)
                return
            if source.suffix.lower() != ".py":
                messagebox.showerror("فایل نامعتبر", "لطفاً فایل برنامه با پسوند .py را انتخاب کنید.", parent=win)
                return
            if not messagebox.askyesno("تأیید به‌روزرسانی",
                                       "فایل انتخاب‌شده جایگزین برنامه فعلی می‌شود. ادامه می‌دهید؟",
                                       parent=win):
                return
            backup = current.with_name(f"{current.stem}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
            try:
                shutil.copy2(current, backup)
                shutil.copy2(source, current)
            except OSError as exc:
                messagebox.showerror("خطای به‌روزرسانی",
                                     f"به‌روزرسانی انجام نشد: {exc}\nنسخه پشتیبان: {backup}", parent=win)
                return
            messagebox.showinfo("به‌روزرسانی آماده است",
                                f"فایل برنامه جایگزین شد. برای اجرای نسخه جدید، برنامه را ببندید و دوباره باز کنید.\n\n"
                                f"نسخه پشتیبان: {backup}", parent=win)
            win.destroy()

        ttk.Button(win, text="انتخاب فایل و به‌روزرسانی", command=choose_update).pack(pady=14)
        ttk.Button(win, text="بستن", command=win.destroy).pack()

    def printer_settings(self):
        """تنظیمات چاپ ذخیره‌شونده برای برگه‌های چاپی برنامه."""
        win = tk.Toplevel(self.root)
        win.title("تنظیمات پرینتر")
        win.geometry("480x430")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        box = ttk.Frame(win, padding=18)
        box.pack(fill="both", expand=True)

        def setting(key, default):
            row = self.conn.execute("SELECT value FROM settings WHERE key=?", ("printer_" + key,)).fetchone()
            return row[0] if row else default

        ttk.Label(box, text="تنظیمات چاپ", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="e", pady=(0, 14))
        ttk.Label(box, text="اندازه کاغذ").grid(row=1, column=1, sticky="e", padx=8, pady=8)
        paper = ttk.Combobox(box, values=["A4", "A5", "Letter", " کارت بانکی (CR80)"], state="readonly", width=22, justify="right")
        paper.grid(row=1, column=0, sticky="w", padx=8, pady=8)
        paper.set(setting("paper", "A4"))

        ttk.Label(box, text="جهت صفحه").grid(row=2, column=1, sticky="e", padx=8, pady=8)
        orientation = ttk.Combobox(box, values=["عمودی", "افقی"], state="readonly", width=22, justify="right")
        orientation.grid(row=2, column=0, sticky="w", padx=8, pady=8)
        orientation.set(setting("orientation", "عمودی"))

        ttk.Label(box, text="حاشیه صفحه (میلی‌متر)").grid(row=3, column=1, sticky="e", padx=8, pady=8)
        margin = ttk.Spinbox(box, from_=0, to=40, width=24, justify="right")
        margin.grid(row=3, column=0, sticky="w", padx=8, pady=8)
        margin.set(setting("margin_mm", "18"))

        ttk.Label(box, text="چاپ رنگی").grid(row=4, column=1, sticky="e", padx=8, pady=8)
        color = ttk.Combobox(box, values=["رنگی", "سیاه و سفید"], state="readonly", width=22, justify="right")
        color.grid(row=4, column=0, sticky="w", padx=8, pady=8)
        color.set(setting("color", "رنگی"))

        ttk.Label(box, text="پرینتر پیش‌فرض ویندوز برای انتخاب دستگاه استفاده می‌شود.", wraplength=410).grid(row=5, column=0, columnspan=2, sticky="e", pady=12)

        def save_settings():
            try:
                margin_value = int(margin.get())
                if not 0 <= margin_value <= 40:
                    raise ValueError
            except ValueError:
                messagebox.showerror("خطا", "حاشیه باید عددی بین صفر تا ۴۰ میلی‌متر باشد.", parent=win)
                return
            values = {"paper": paper.get().strip(), "orientation": orientation.get(),
                      "margin_mm": str(margin_value), "color": color.get()}
            self.conn.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                  [("printer_" + k, v) for k, v in values.items()])
            self.conn.commit()
            messagebox.showinfo("ذخیره شد", "تنظیمات چاپ ذخیره شد. در چاپ‌های بعدی برگه‌های برنامه اعمال می‌شود. برای انتخاب یا تغییر پرینتر پیش‌فرض، از دکمه تنظیمات ویندوز استفاده کنید.", parent=win)
            win.destroy()

        def open_windows_printers():
            import os
            import subprocess
            try:
                if os.name == "nt":
                    subprocess.Popen(["rundll32", "shell32.dll,SHHelpShortcuts_RunDLL", "PrintersFolder"])
                else:
                    messagebox.showinfo("راهنما", "انتخاب پرینتر از تنظیمات چاپ سیستم‌عامل انجام می‌شود.", parent=win)
            except OSError as exc:
                messagebox.showerror("خطا", f"باز کردن تنظیمات پرینتر ناموفق بود: {exc}", parent=win)

        buttons = ttk.Frame(box)
        buttons.grid(row=6, column=0, columnspan=2, pady=12)
        ttk.Button(buttons, text="ذخیره تنظیمات", command=save_settings).pack(side="right", padx=5)
        ttk.Button(buttons, text="پرینترهای ویندوز", command=open_windows_printers).pack(side="right", padx=5)
        ttk.Button(buttons, text="بستن", command=win.destroy).pack(side="right", padx=5)

    def settings(self):
        self.panel("تنظیمات برنامه")
        layout_box = ttk.LabelFrame(self.content, text="تنظیمات چیدمان کل برنامه", padding=10)
        layout_box.pack(fill="x", pady=(4, 10))
        ttk.Label(layout_box, text="اندازه پنجره برنامه:").grid(row=0, column=1, sticky="e", padx=6, pady=5)
        window_choice = ttk.Combobox(layout_box, values=["1000x650", "1180x740", "1360x820", "تمام‌صفحه"], state="readonly", width=16, justify="center")
        window_choice.grid(row=0, column=0, sticky="e", padx=6, pady=5)
        current_window = self.get_setting("window_size", "1180x740")
        window_choice.set(current_window if current_window in window_choice["values"] else "1180x740")
        ttk.Label(layout_box, text="فشردگی و فاصله اجزا:").grid(row=1, column=1, sticky="e", padx=6, pady=5)
        density_choice = ttk.Combobox(layout_box, values=["جمع‌وجور", "استاندارد", "درشت و خوانا"], state="readonly", width=16, justify="right")
        density_choice.grid(row=1, column=0, sticky="e", padx=6, pady=5)
        density_choice.set(self.get_setting("layout_density", "استاندارد"))
        def apply_layout():
            selected = window_choice.get()
            if selected == "تمام‌صفحه":
                self.root.state("zoomed")
                self.save_setting("window_size", "1180x740")
            else:
                self.root.state("normal")
                self.root.geometry(selected)
                self.save_setting("window_size", selected)
            self.save_setting("layout_density", density_choice.get())
            self.apply_font(self.ui_font)
            messagebox.showinfo("چیدمان", "تنظیمات چیدمان در کل برنامه اعمال و ذخیره شد.")
        ttk.Button(layout_box, text="اعمال چیدمان", command=apply_layout).grid(row=0, column=2, rowspan=2, padx=10, pady=5)
        ttk.Label(self.content, text="پوسته ظاهری نرم‌افزار").pack(anchor="e", pady=(8,4))
        theme_row = ttk.Frame(self.content); theme_row.pack(anchor="e", pady=4)
        themes = ["آبی سازمانی", "سبز امید", "بنفش مدرن", "فیروزه‌ای", "زرشکی", "نارنجی گرم", "ذغالی تیره", "صورتی ملایم", "اقیانوسی", "طلایی کلاسیک", "قرمز یاقوتی", "سبز زمردی", "آبی آسمانی", "نیلی شب", "نعنایی", "مرجانی", "قهوه‌ای شکلاتی", "لیمویی", "لاجوردی", "خاکستری نقره‌ای", "سبز زیتونی", "بنفش اسطوخودوسی", "آبی یخی", "رزگلد", "سبز جنگلی", "Office 2007", "Windows 7", "Longhorn", "Office Black", "مشکی مات", "مشکی و نقره‌ای", "سرمه‌ای کلاسیک", "سبز یشمی", "بنفش سلطنتی", "خاکستری مدرن", "آبی نفتی", "سبز پسته‌ای"]
        theme_choice = ttk.Combobox(theme_row, values=themes, state="readonly", width=25, justify="right")
        theme_choice.pack(side="right", padx=6); theme_choice.set(self.selected_theme)
        ttk.Button(theme_row, text="اعمال پوسته", command=lambda: self.set_theme(theme_choice.get(), True)).pack(side="right", padx=6)
        ttk.Label(self.content, text="فونت فارسی برنامه").pack(anchor="e", pady=(12,4))
        font_row=ttk.Frame(self.content); font_row.pack(anchor="e",pady=4)
        font_choice=ttk.Combobox(font_row, values=["Tahoma", "Vazirmatn", "Estedad", "Shabnam", "Sahel", "IRANSans", "Yekan Bakh", "Dana", "Noto Sans Arabic", "Noto Naskh Arabic", "Segoe UI", "Arial"], state="readonly", width=25, justify="right")
        font_choice.pack(side="right", padx=6); font_choice.set(self.ui_font)
        ttk.Button(font_row,text="اعمال فونت",command=lambda: (self.apply_font(font_choice.get()), messagebox.showinfo("فونت", "تنظیم فونت ذخیره شد. اگر فونت روی ویندوز نصب نباشد، سیستم از فونت جایگزین استفاده می‌کند."))).pack(side="right",padx=6)
        ttk.Label(self.content, text="اندازه فونت").pack(anchor="e", pady=(8,3))
        size_row=ttk.Frame(self.content); size_row.pack(anchor="e",pady=4)
        size_choice=ttk.Combobox(size_row, values=["9","10","11","12","13","14"], state="readonly", width=8, justify="center")
        size_choice.pack(side="right", padx=6); size_choice.set(self.get_setting("ui_font_size","10"))
        def apply_size():
            self.save_setting("ui_font_size", size_choice.get()); self.apply_font(self.ui_font); self.set_theme(self.selected_theme)
            messagebox.showinfo("اندازه فونت", "اندازه فونت ذخیره شد.")
        ttk.Button(size_row,text="اعمال اندازه",command=apply_size).pack(side="right",padx=6)
        ttk.Button(self.content, text="تنظیمات پرینتر", command=self.printer_settings).pack(anchor="e", pady=8)
        ttk.Label(self.content,text=f"مسیر پایگاه داده: {DB_PATH}").pack(anchor="e",pady=8)
        ttk.Label(self.content,text="این نسخه برای آموزش و نمونه‌سازی است و برای استفاده بانکی واقعی طراحی نشده است.").pack(anchor="e",pady=8)
        def change_password():
            win=tk.Toplevel(self.root); win.title("تغییر رمز مدیر"); win.geometry("360x190")
            ttk.Label(win,text="رمز جدید (حداقل ۸ نویسه)").pack(pady=10)
            e=ttk.Entry(win,show="*",width=28); e.pack()
            def save():
                p=e.get()
                if len(p)<8: messagebox.showerror("خطا","رمز باید حداقل ۸ نویسه باشد.",parent=win); return
                salt,digest=hash_password(p)
                self.conn.execute("UPDATE users SET password_hash=?,salt=? WHERE id=?",(digest,salt,self.current_user["id"]))
                self.conn.commit(); messagebox.showinfo("موفق","رمز تغییر کرد.",parent=win); win.destroy()
            ttk.Button(win,text="ذخیره رمز",command=save).pack(pady=14)
        ttk.Button(self.content,text="تغییر رمز عبور کاربر فعلی",command=change_password).pack(anchor="e",pady=10)

if __name__ == "__main__":
    root=tk.Tk()
    app=BankManager(root)
    root.mainloop()
