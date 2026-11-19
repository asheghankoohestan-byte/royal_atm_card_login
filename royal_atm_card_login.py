# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import sqlite3, os, tempfile, subprocess, sys, html, calendar, hashlib, secrets, hmac, json
from datetime import datetime
from decimal import Decimal, InvalidOperation

TITLE="خودپرداز رویال"
DB_NAME="bank_manager.db"
CONFIG_NAME="royal_atm_db_path.txt"
BG="#081b2d"; PANEL="#102b43"; PANEL2="#163650"; ACCENT="#19b5a5"
TEXT="#f2f7fb"; MUTED="#9eb4c7"; GOLD="#f2bd58"; RED="#e36c76"

def db_path():
    # Match the database location used by bank_manager.py:
    # source mode: beside the manager script; frozen EXE: %LOCALAPPDATA%\\OmidAyandeh.
    if getattr(sys, "frozen", False):
        base=os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "OmidAyandeh")
        os.makedirs(base, exist_ok=True)
    else:
        base=os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, DB_NAME)

def validate_db(path):
    if not os.path.isfile(path): raise FileNotFoundError("فایل انتخاب‌شده وجود ندارد.")
    c=sqlite3.connect(path,timeout=10)
    try:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing={"accounts","cards","transactions"}-tables
        if missing: raise ValueError("بانک اطلاعاتی رویال نیست؛ جدول‌های لازم پیدا نشد.")
        cols={r[1] for r in c.execute("PRAGMA table_info(accounts)")}
        if not {"account_no","balance","status","full_name"}.issubset(cols):
            raise ValueError("ساختار جدول حساب‌ها سازگار نیست.")
    finally: c.close()

def connect():
    path=db_path()
    if not os.path.exists(path): raise FileNotFoundError("بانک اطلاعاتی یافت نشد. از صفحه شروع، فایل اصلی را انتخاب کنید.")
    validate_db(path)
    c=sqlite3.connect(path,timeout=20); c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    # Store card PINs as salted hashes, never as plain text.
    cols={r[1] for r in c.execute("PRAGMA table_info(cards)")}
    if "pin_hash" not in cols: c.execute("ALTER TABLE cards ADD COLUMN pin_hash TEXT")
    if "pin_salt" not in cols: c.execute("ALTER TABLE cards ADD COLUMN pin_salt TEXT")
    if "failed_attempts" not in cols: c.execute("ALTER TABLE cards ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0")
    c.commit()
    return c

def fmt(x): return f"{float(x):,.0f}"


def jalali_date(gy, gm, gd):
    g_days=[0,31,59,90,120,151,181,212,243,273,304,334]
    gy2=gy+1 if gm>2 else gy
    days=355666+365*gy+(gy2+3)//4-(gy2+99)//100+(gy2+399)//400+gd+g_days[gm-1]
    jy=-1595+33*(days//12053); days%=12053
    jy+=4*(days//1461); days%=1461
    if days>365:
        jy+=(days-1)//365; days=(days-1)%365
    if days<186: jm=1+days//31; jd=1+days%31
    else: jm=7+(days-186)//30; jd=1+(days-186)%30
    return jy,jm,jd

def _jalali_datetime_text(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        jy, jm, jd = jalali_date(dt.year, dt.month, dt.day)
        return f"{jy:04d}/{jm:02d}/{jd:02d}  {dt.strftime('%H:%M:%S')}"
    except (ValueError, TypeError):
        return str(value or "")

class ATM(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE); self.geometry("900x700"); self.minsize(780,640)
        self.configure(bg=BG); self.card=None
        self.option_add("*Font",("Tahoma",10))
        st=ttk.Style(self)
        try: st.theme_use("clam")
        except: pass
        st.configure("Treeview",background=PANEL,foreground=TEXT,fieldbackground=PANEL,rowheight=34,font=("Tahoma",10))
        st.configure("Treeview.Heading",background=PANEL2,foreground=TEXT,font=("Tahoma",10,"bold"))
        st.map("Treeview",background=[("selected",ACCENT)],foreground=[("selected","white")])
        self.root=tk.Frame(self,bg=BG); self.root.pack(fill="both",expand=True,padx=14,pady=12)
        self.header()
        self.clockbar=tk.Frame(self.root,bg=BG); self.clockbar.pack(fill="x",pady=(10,0))
        self.clock_canvas=tk.Canvas(self.clockbar,width=88,height=88,bg=BG,highlightthickness=0)
        self.clock_canvas.pack(side="right",padx=6)
        self.datetime_label=tk.Label(self.clockbar,text="",bg=BG,fg=TEXT,font=("Tahoma",12,"bold"),justify="right")
        self.datetime_label.pack(side="right",padx=12)
        self.body=tk.Frame(self.root,bg=BG); self.body.pack(fill="both",expand=True,pady=(6,0))
        self.footer()
        self.update_clock()
        self.login_screen()

    def header(self):
        h=tk.Frame(self.root,bg=PANEL,highlightbackground="#24455e",highlightthickness=1)
        h.pack(fill="x")
        mark=tk.Label(h,text="R",font=("Arial",24,"bold"),bg=ACCENT,fg="white",width=3,height=1)
        mark.pack(side="right",padx=16,pady=13)
        texts=tk.Frame(h,bg=PANEL); texts.pack(side="right",pady=10)
        tk.Label(texts,text="ROYAL",font=("Arial",17,"bold"),bg=PANEL,fg=TEXT).pack(anchor="e")
        tk.Label(texts,text="سامانه شبیه‌ساز خودپرداز رویال",font=("Tahoma",12,"bold"),bg=PANEL,fg=MUTED).pack(anchor="e")
        tk.Label(h,text="ATM  •  DEMO",font=("Arial",10,"bold"),bg=PANEL,fg=ACCENT).pack(side="left",padx=12)
        self.btn(h,"تنظیم کارمزدها",self.fee_settings,"secondary",width=14).pack(side="left",padx=4,pady=10)

    def footer(self):
        self.status=tk.Label(self.root,text="نسخه آزمایشی محلی • متصل به بانک اطلاعاتی انتخاب‌شده",bg=BG,fg=MUTED,font=("Tahoma",9))
        self.status.pack(anchor="center",pady=(12,0))

    def clear(self):
        for w in self.body.winfo_children(): w.destroy()

    def cardbox(self,parent):
        f=tk.Frame(parent,bg=PANEL,highlightbackground="#24455e",highlightthickness=1)
        return f

    def btn(self,parent,text,command,kind="primary",width=20):
        bg={"primary":ACCENT,"secondary":PANEL2,"danger":RED}.get(kind,ACCENT)
        fg="white"
        b=tk.Button(parent,text=text,command=command,bg=bg,fg=fg,activebackground="#128f84",
                    activeforeground="white",relief="flat",bd=0,cursor="hand2",
                    font=("Tahoma",9,"bold"),padx=10,pady=7,width=width)
        b.bind("<Enter>",lambda e:b.configure(bg="#168f84" if kind=="primary" else "#204762"))
        b.bind("<Leave>",lambda e:b.configure(bg=bg))
        return b

    def entry(self,parent,var,width=30):
        e=tk.Entry(parent,textvariable=var,width=width,justify="center",font=("Tahoma",13),
                   bg="#f3f7fa",fg="#123047",insertbackground="#123047",relief="flat",
                   highlightthickness=1,highlightbackground="#c4d3df",highlightcolor=ACCENT)
        return e

    def update_clock(self):
        now=datetime.now()
        jy,jm,jd=jalali_date(now.year,now.month,now.day)
        months=["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"]
        self.datetime_label.configure(text=f"ساعت {now.strftime('%H:%M:%S')}\n{jd:02d} {months[jm-1]} {jy}")
        c=self.clock_canvas;c.delete("all")
        cx=cy=59;r=48
        c.create_oval(cx-r,cy-r,cx+r,cy+r,fill=PANEL,outline=ACCENT,width=2)
        for i in range(12):
            import math
            a=math.radians(i*30-90)
            x1=cx+math.cos(a)*(r-8);y1=cy+math.sin(a)*(r-8)
            x2=cx+math.cos(a)*(r-14);y2=cy+math.sin(a)*(r-14)
            c.create_line(x1,y1,x2,y2,fill=TEXT,width=2)
        def hand(value,scale,color,width):
            a=math.radians(value-90)
            c.create_line(cx,cy,cx+math.cos(a)*scale,cy+math.sin(a)*scale,fill=color,width=width,capstyle="round")
        hand((now.hour%12)*30+now.minute*.5,25,TEXT,4)
        hand(now.minute*6+now.second*.1,35,ACCENT,3)
        hand(now.second*6,39,GOLD,1)
        c.create_oval(cx-4,cy-4,cx+4,cy+4,fill=GOLD,outline="")
        self.after(1000,self.update_clock)

    def login_screen(self):
        self.card=None
        self.clear()

        # Compact login composition: keep every action visible on common laptop screens.
        shell=tk.Frame(self.body,bg=BG)
        shell.pack(fill="both",expand=True,padx=18,pady=2)

        # Single compact card avoids pushing the action buttons below the window.
        box=self.cardbox(shell)
        box.pack(fill="both",expand=True,padx=55,pady=0)
        brand=tk.Frame(box,bg=PANEL)
        brand.pack(fill="x",padx=18,pady=(6,0))
        mark=tk.Label(brand,text="R",font=("Arial",17,"bold"),bg=ACCENT,fg="white",width=2,height=1)
        mark.pack(side="right",padx=(0,9))
        names=tk.Frame(brand,bg=PANEL)
        names.pack(side="right",anchor="e")
        tk.Label(names,text="ROYAL",font=("Arial",14,"bold"),bg=PANEL,fg=TEXT).pack(anchor="e")
        tk.Label(names,text="سامانه هوشمند خودپرداز",font=("Tahoma",8),bg=PANEL,fg=MUTED).pack(anchor="e")
        self.welcome_label=tk.Label(box,text="خوش آمدید",font=("Tahoma",22,"bold"),bg=PANEL,fg=TEXT)
        self.welcome_label.pack(pady=(3,1))
        self._welcome_anim_index=0
        self.animate_welcome()
        reminder=tk.Label(box,text="یادآوری پشتیبان‌گیری: از اطلاعات بانک اطلاعاتی رویال نسخه پشتیبان تهیه کنید.",
                          font=("Tahoma",8,"bold"),bg="#263b2e",fg="#b8efc5",
                          wraplength=600,justify="center")
        reminder.pack(fill="x",padx=22,pady=(1,3),ipady=2)
        tk.Label(box,text="برای ورود به حساب خود، اطلاعات کارت را وارد کنید",
                 font=("Tahoma",8),bg=PANEL,fg=MUTED).pack(pady=(0,4))

        fields=tk.Frame(box,bg=PANEL)
        fields.pack(fill="x",padx=42)
        self.card_var=tk.StringVar()
        self.pin_var=tk.StringVar()
        tk.Label(fields,text="شماره کارت",bg=PANEL,fg=TEXT,font=("Tahoma",10,"bold")).pack(anchor="e",pady=(1,3))
        card_entry=self.entry(fields,self.card_var,34)
        card_entry.pack(fill="x",ipady=4,pady=(0,5))
        card_entry.bind("<Return>",lambda e: self.login())
        tk.Label(fields,text="رمز کارت  •  ۴ تا ۸ رقم",bg=PANEL,fg=TEXT,font=("Tahoma",10,"bold")).pack(anchor="e",pady=(0,3))
        pin_entry=self.entry(fields,self.pin_var,34)
        pin_entry.configure(show="●")
        pin_entry.pack(fill="x",ipady=4,pady=(0,1))
        pin_entry.bind("<Return>",lambda e:self.login())

        links=tk.Frame(box,bg=PANEL)
        links.pack(fill="x",padx=42,pady=(0,2))
        forgot=tk.Label(links,text="رمز خود را فراموش کرده‌اید؟",bg=PANEL,fg=ACCENT,
                        font=("Tahoma",9,"bold"),cursor="hand2")
        forgot.pack(side="right")
        forgot.bind("<Button-1>",lambda e:self.forgot_pin())
        forgot.bind("<Enter>",lambda e:forgot.configure(fg=GOLD))
        forgot.bind("<Leave>",lambda e:forgot.configure(fg=ACCENT))

        self.btn(box,"ورود امن به خودپرداز",self.login,width=25).pack(pady=(2,3))
        self.btn(box,"انتخاب بانک اطلاعاتی اصلی",self.choose_database,"secondary",width=25).pack(pady=(0,3))

        data_actions=tk.Frame(box,bg=PANEL)
        data_actions.pack(fill="x",padx=25,pady=(1,3))
        self.btn(data_actions,"پشتیبان‌گیری",self.backup_database,"secondary",width=16).pack(side="right",padx=5)
        self.btn(data_actions,"بازیابی پشتیبان",self.restore_database,"secondary",width=16).pack(side="right",padx=5)

        self.db_label=tk.Label(box,text="بانک اطلاعاتی فعال:  "+db_path(),bg=PANEL,fg=MUTED,
                               font=("Tahoma",8),wraplength=620,justify="center")
        self.db_label.pack(padx=18,pady=(0,1))
        tk.Label(box,text="اطلاعات ورود شما به‌صورت امن بررسی می‌شود.",
                 bg=PANEL,fg=GOLD,font=("Tahoma",8)).pack(pady=(0,3))
        card_entry.focus_set()

    def animate_welcome(self):
        """انیمیشن ملایم رنگ متن خوش‌آمدگویی در صفحه ورود."""
        if not hasattr(self, "welcome_label") or not self.welcome_label.winfo_exists():
            return
        colors=[TEXT, GOLD, "#8ee7dc", TEXT]
        self.welcome_label.configure(fg=colors[self._welcome_anim_index % len(colors)])
        self._welcome_anim_index += 1
        self.after(650, self.animate_welcome)

    def forgot_pin(self):
        """Explain the verified recovery route without exposing or bypassing card security."""
        win=tk.Toplevel(self)
        win.title("بازیابی رمز کارت")
        win.geometry("440x270")
        win.resizable(False,False)
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()
        panel=self.cardbox(win)
        panel.pack(fill="both",expand=True,padx=18,pady=18)
        tk.Label(panel,text="بازیابی رمز کارت",bg=PANEL,fg=TEXT,
                 font=("Tahoma",17,"bold")).pack(pady=(18,10))
        tk.Label(panel,text="برای حفظ امنیت حساب، امکان بازیابی رمز فقط با شماره کارت وجود ندارد.",
                 bg=PANEL,fg=MUTED,font=("Tahoma",10),wraplength=360,
                 justify="center").pack(padx=18,pady=5)
        tk.Label(panel,text="لطفاً برای احراز هویت و تعریف رمز جدید با مدیر بانک یا مسئول سامانه تماس بگیرید.",
                 bg=PANEL,fg=TEXT,font=("Tahoma",10,"bold"),wraplength=360,
                 justify="center").pack(padx=18,pady=8)
        tk.Label(panel,text="پس از تأیید هویت، مدیر بانک می‌تواند رمز کارت را از پنل مدیریتی بازنشانی کند.",
                 bg=PANEL,fg=GOLD,font=("Tahoma",9),wraplength=360,
                 justify="center").pack(padx=18,pady=5)
        self.btn(panel,"متوجه شدم",win.destroy,"secondary",width=16).pack(pady=(10,15))

    def login(self):
        no=self.card_var.get().replace(" ","").strip()
        pin=self.pin_var.get().strip()
        if not no:
            messagebox.showwarning("اطلاعات ناقص","شماره کارت را وارد کنید.");return
        if not pin.isdigit() or not 4<=len(pin)<=8:
            messagebox.showwarning("رمز نامعتبر","رمز عبور باید ۴ تا ۸ رقم باشد.");return
        try:
            with connect() as c:
                row=c.execute("""SELECT cards.card_no,cards.account_no,cards.status card_status,
                    cards.pin_hash,cards.pin_salt,accounts.full_name,accounts.balance,accounts.status account_status
                    FROM cards JOIN accounts ON accounts.account_no=cards.account_no
                    WHERE cards.card_no=?""",(no,)).fetchone()
                if not row:
                    messagebox.showwarning("کارت پیدا نشد","این شماره کارت در بانک اطلاعاتی موجود نیست.");return
                if row["card_status"]!="فعال":
                    messagebox.showwarning("کارت مسدود یا غیرفعال","این کارت فعال نیست. برای رفع مسدودی به مدیر بانک مراجعه کنید.");return
                if row["account_status"]!="فعال":
                    messagebox.showwarning("حساب غیرفعال","حساب متصل به کارت فعال نیست.");return
                if not row["pin_hash"] or not row["pin_salt"]:
                    messagebox.showinfo("تعریف رمز کارت",
                        "برای این کارت هنوز رمزی ثبت نشده است. ابتدا رمز جدید را دوبار وارد کنید.")
                    first=simpledialog.askstring("تعریف رمز کارت","رمز جدید ۴ تا ۸ رقمی را وارد کنید:",
                                                 show="•",parent=self)
                    if first is None:return
                    if not first.isdigit() or not 4<=len(first)<=8:
                        messagebox.showwarning("رمز نامعتبر","رمز باید ۴ تا ۸ رقم باشد.");return
                    confirm=simpledialog.askstring("تأیید رمز کارت","همان رمز را دوباره وارد کنید:",
                                                   show="•",parent=self)
                    if confirm is None:return
                    if not hmac.compare_digest(first,confirm):
                        messagebox.showwarning("عدم تطابق","دو رمز یکسان نیستند. دوباره تلاش کنید.");return
                    salt=secrets.token_hex(16)
                    digest=hashlib.pbkdf2_hmac("sha256",first.encode("utf-8"),salt.encode("utf-8"),200000).hex()
                    c.execute("UPDATE cards SET pin_hash=?,pin_salt=? WHERE card_no=?",(digest,salt,no))
                    c.commit()
                    messagebox.showinfo("رمز ثبت شد","رمز کارت ثبت شد. اکنون با همان رمز وارد شوید.")
                    return
                digest=hashlib.pbkdf2_hmac("sha256",pin.encode("utf-8"),row["pin_salt"].encode("utf-8"),200000).hex()
                if not hmac.compare_digest(digest,row["pin_hash"]):
                    current=c.execute("SELECT failed_attempts FROM cards WHERE card_no=?",(no,)).fetchone()
                    attempts=(current["failed_attempts"] or 0)+1
                    if attempts>=3:
                        c.execute("UPDATE cards SET failed_attempts=?, status=? WHERE card_no=?",(attempts,"مسدود",no))
                        c.commit()
                        messagebox.showerror("کارت مسدود شد","رمز عبور ۳ بار اشتباه وارد شد. کارت برای امنیت مسدود شد؛ برای فعال‌سازی مجدد با مدیر بانک تماس بگیرید.")
                    else:
                        c.execute("UPDATE cards SET failed_attempts=? WHERE card_no=?",(attempts,no))
                        c.commit()
                        remaining=3-attempts
                        messagebox.showwarning("ورود ناموفق",f"رمز عبور اشتباه است. {remaining} فرصت دیگر باقی مانده است.")
                    return
                # A correct PIN clears the consecutive failure counter.
                c.execute("UPDATE cards SET failed_attempts=0 WHERE card_no=?",(no,))
                c.commit()
            self.card=row;self.menu_screen()
        except Exception as e:messagebox.showerror("خطای اتصال",str(e))

    def change_pin(self):
        """Allow the authenticated cardholder to change their own card PIN."""
        if not self.card:
            messagebox.showwarning("خطا", "ابتدا وارد خودپرداز شوید.", parent=self)
            return
        old_pin=simpledialog.askstring("تغییر رمز کارت", "رمز فعلی کارت را وارد کنید:",
                                       show="•", parent=self)
        if old_pin is None:
            return
        if not old_pin.isdigit() or not 4<=len(old_pin)<=8:
            messagebox.showwarning("رمز نامعتبر", "رمز باید ۴ تا ۸ رقم باشد.", parent=self)
            return
        new_pin=simpledialog.askstring("رمز جدید", "رمز جدید ۴ تا ۸ رقمی را وارد کنید:",
                                       show="•", parent=self)
        if new_pin is None:
            return
        if not new_pin.isdigit() or not 4<=len(new_pin)<=8:
            messagebox.showwarning("رمز نامعتبر", "رمز جدید باید ۴ تا ۸ رقم باشد.", parent=self)
            return
        if hmac.compare_digest(old_pin, new_pin):
            messagebox.showwarning("رمز تکراری", "رمز جدید باید با رمز فعلی متفاوت باشد.", parent=self)
            return
        confirm=simpledialog.askstring("تأیید رمز جدید", "رمز جدید را دوباره وارد کنید:",
                                       show="•", parent=self)
        if confirm is None:
            return
        if not hmac.compare_digest(new_pin, confirm):
            messagebox.showwarning("عدم تطابق", "دو بار واردشده یکسان نیستند. تغییر رمز انجام نشد.", parent=self)
            return
        try:
            with connect() as c:
                row=c.execute("SELECT pin_hash,pin_salt,status FROM cards WHERE card_no=?",
                              (self.card["card_no"],)).fetchone()
                if not row or row["status"]!="فعال":
                    messagebox.showerror("کارت غیرفعال", "کارت فعال نیست و امکان تغییر رمز وجود ندارد.", parent=self)
                    self.login_screen()
                    return
                old_digest=hashlib.pbkdf2_hmac("sha256",old_pin.encode("utf-8"),
                                               row["pin_salt"].encode("utf-8"),200000).hex() if row["pin_salt"] else ""
                if not row["pin_hash"] or not hmac.compare_digest(old_digest,row["pin_hash"]):
                    messagebox.showerror("رمز فعلی اشتباه است", "رمز فعلی صحیح نیست؛ رمز کارت تغییر نکرد.", parent=self)
                    return
                salt=secrets.token_hex(16)
                digest=hashlib.pbkdf2_hmac("sha256",new_pin.encode("utf-8"),salt.encode("utf-8"),200000).hex()
                c.execute("UPDATE cards SET pin_hash=?,pin_salt=?,failed_attempts=0 WHERE card_no=?",
                          (digest,salt,self.card["card_no"]))
                c.commit()
            messagebox.showinfo("تغییر رمز موفق", "رمز کارت با موفقیت تغییر کرد.", parent=self)
        except Exception as e:
            messagebox.showerror("خطای تغییر رمز", str(e), parent=self)

    def _write_database_backup(self, destination):
        """Create a consistent SQLite backup, including committed database pages."""
        source_path=db_path()
        if not os.path.isfile(source_path):
            raise FileNotFoundError("بانک اطلاعاتی فعالی برای پشتیبان‌گیری پیدا نشد.")
        src=sqlite3.connect(source_path, timeout=20)
        dst=sqlite3.connect(destination, timeout=20)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()
        validate_db(destination)

    def backup_database(self):
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        path=filedialog.asksaveasfilename(parent=self,title="ذخیره نسخه پشتیبان رویال",
            initialfile=f"royal_backup_{stamp}.db",
            defaultextension=".db",filetypes=[("SQLite database","*.db"),("All files","*.*")])
        if not path:return
        try:
            self._write_database_backup(path)
            messagebox.showinfo("پشتیبان‌گیری موفق",f"نسخه پشتیبان با موفقیت ذخیره شد:\n{path}",parent=self)
        except Exception as exc:
            try:
                if os.path.exists(path): os.remove(path)
            except OSError: pass
            messagebox.showerror("خطای پشتیبان‌گیری",str(exc),parent=self)

    def restore_database(self):
        source=filedialog.askopenfilename(parent=self,title="انتخاب فایل پشتیبان برای بازیابی",
            filetypes=[("SQLite database","*.db *.sqlite *.sqlite3"),("All files","*.*")])
        if not source:return
        try:
            validate_db(source)
            if os.path.abspath(source)==os.path.abspath(db_path()):
                messagebox.showinfo("بازیابی", "این فایل هم‌اکنون بانک اطلاعاتی فعال است.",parent=self)
                return
            if not messagebox.askyesno("تأیید بازیابی",
                "با بازیابی، اطلاعات فعلی بانک با محتوای فایل پشتیبان جایگزین می‌شود.\n"
                "پیش از جایگزینی، از اطلاعات فعلی یک نسخه اضطراری ساخته خواهد شد. ادامه می‌دهید؟",parent=self):
                return
            target=db_path()
            os.makedirs(os.path.dirname(target),exist_ok=True)
            stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
            safety=os.path.join(os.path.dirname(target),f"royal_before_restore_{stamp}.db")
            if os.path.exists(target): self._write_database_backup(safety)
            fd,temp_path=tempfile.mkstemp(prefix="royal_restore_",suffix=".db",dir=os.path.dirname(target))
            os.close(fd)
            try:
                src=sqlite3.connect(source,timeout=20)
                dst=sqlite3.connect(temp_path,timeout=20)
                try: src.backup(dst)
                finally: dst.close(); src.close()
                validate_db(temp_path)
                os.replace(temp_path,target)
            finally:
                if os.path.exists(temp_path): os.remove(temp_path)
            extra=f"\nنسخه اضطراری اطلاعات قبلی: {safety}" if os.path.exists(safety) else ""
            messagebox.showinfo("بازیابی موفق", "اطلاعات بانک با موفقیت بازیابی شد."+extra+"\nبرای اطمینان، برنامه را ببندید و دوباره اجرا کنید.",parent=self)
        except Exception as exc:
            messagebox.showerror("خطای بازیابی",str(exc),parent=self)

    def choose_database(self):
        path=filedialog.askopenfilename(title="بانک اطلاعاتی اصلی پروژه رویال را انتخاب کنید",
            filetypes=[("SQLite database","*.db *.sqlite *.sqlite3"),("All files","*.*")])
        if not path:return
        try:
            validate_db(path)
            messagebox.showinfo("بانک اطلاعاتی پروژه",
                "برای اتصال دائمی، فایل انتخاب‌شده را با نام bank_manager.db در کنار فایل برنامه قرار دهید و برنامه را دوباره اجرا کنید.",
                parent=self)
        except Exception as e:messagebox.showerror("فایل نامعتبر",str(e),parent=self)

    def menu_screen(self):
        self.clear()
        welcome=self.cardbox(self.body);welcome.pack(fill="x",pady=(0,8))
        tk.Label(welcome,text=f"سلام، {self.card['full_name']}",bg=PANEL,fg=TEXT,font=("Tahoma",13,"bold")).pack(anchor="e",padx=14,pady=(8,2))
        tk.Label(welcome,text=f"شماره کارت: {self.card['card_no']}     |     حساب: {self.card['account_no']}",bg=PANEL,fg=MUTED).pack(anchor="e",padx=14,pady=(0,8))
        tk.Label(self.body,text="خدمات خودپرداز",bg=BG,fg=TEXT,font=("Tahoma",14,"bold")).pack(pady=4)
        grid=tk.Frame(self.body,bg=BG);grid.pack(expand=True)
        services=[
            ("◉","مشاهده موجودی",self.balance,"primary"),
            ("⇄","انتقال وجه",self.transfer,"secondary"),
            ("▤","گردش حساب",self.history,"secondary"),
            ("₮","پرداخت اقساط",self.installment_payment,"secondary"),
            ("🔒","تغییر رمز کارت",self.change_pin,"secondary"),
        ]
        for i,(ico,label,fn,kind) in enumerate(services):
            tile=self.cardbox(grid);tile.grid(row=i//3,column=i%3,padx=5,pady=4,sticky="n")
            tk.Label(tile,text=ico,font=("Arial",16,"bold"),bg=PANEL,fg=ACCENT).pack(padx=12,pady=(6,2))
            self.btn(tile,label,fn,kind,width=14).pack(padx=6,pady=(0,6))
        self.btn(self.body,"پایان عملیات / کارت دیگر",self.login_screen,"danger",20).pack(pady=4)

    FEE_SERVICES = {"واریز وجه":"deposit", "برداشت وجه":"withdraw", "انتقال وجه":"transfer", "واریز سود سپرده":"interest", "پرداخت اقساط":"installment", "پرداخت تسهیلات":"loan"}

    def fee_config(self, c):
        row=c.execute("SELECT value FROM settings WHERE key='royal_fee_config'").fetchone()
        try: data=json.loads(row[0]) if row else {}
        except Exception: data={}
        return data

    def calculate_fee(self, c, service, amount, parent=None):
        cfg=self.fee_config(c).get(service, {})
        mode=cfg.get("mode", "fixed")
        if mode == "percent": fee=Decimal(str(amount))*Decimal(str(cfg.get("value",0)))/Decimal('100')
        elif mode == "manual":
            raw=simpledialog.askstring("کارمزد تراکنش",f"مبلغ کارمزد {service} را وارد کنید:",parent=parent or self)
            if raw is None: raise ValueError("عملیات توسط کاربر لغو شد.")
            fee=Decimal(raw.replace(',','').strip())
        else: fee=Decimal(str(cfg.get("value",0)))
        if fee < 0: raise ValueError("کارمزد نمی‌تواند منفی باشد.")
        return fee

    def credit_main_fund(self, c, fee, service, account_no, now):
        if fee <= 0: return
        row=c.execute("SELECT id FROM funds WHERE fund_name='صندوق اصلی' ORDER BY id LIMIT 1").fetchone()
        if row: c.execute("UPDATE funds SET balance=balance+? WHERE id=?",(float(fee),row['id']))
        else: c.execute("INSERT INTO funds(fund_name,balance,description,created_at) VALUES(?,?,?,?)",("صندوق اصلی",float(fee),"تجمیع کارمزد خدمات بانکی",now))
        c.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",(account_no,"کارمزد کسرشده",float(fee),f"کارمزد {service}؛ واریز به صندوق اصلی",now,"Royal ATM"))

    def fee_settings(self):
        win=tk.Toplevel(self);win.title("تنظیم کارمزد خدمات");win.geometry("700x590");win.configure(bg=BG);win.transient(self);win.grab_set()
        panel=self.cardbox(win);panel.pack(fill="both",expand=True,padx=14,pady=14)
        tk.Label(panel,text="مدیریت کارمزد خدمات رویال",bg=PANEL,fg=TEXT,font=("Tahoma",16,"bold")).pack(pady=(12,4))
        tk.Label(panel,text="برای هر خدمت روش و مبلغ کارمزد را جداگانه تغییر دهید. کارمزد دریافتی به صندوق اصلی واریز می‌شود.",bg=PANEL,fg=MUTED,wraplength=620).pack(pady=(0,10))
        with connect() as c: config=self.fee_config(c)
        fields={}
        area=tk.Frame(panel,bg=PANEL);area.pack(fill="both",expand=True,padx=12)
        for service in self.FEE_SERVICES:
            row=tk.Frame(area,bg=PANEL2);row.pack(fill="x",pady=3)
            tk.Label(row,text=service,bg=PANEL2,fg=TEXT,width=18,anchor="e").pack(side="right",padx=8,pady=6)
            old=config.get(service,{})
            mode=tk.StringVar(value=old.get("mode","fixed"));value=tk.StringVar(value=str(old.get("value",0)))
            ttk.Combobox(row,textvariable=mode,values=["fixed","percent","manual"],state="readonly",width=12).pack(side="right",padx=5)
            tk.Label(row,text="روش: ثابت / درصدی / دستی",bg=PANEL2,fg=MUTED).pack(side="right",padx=5)
            ent=self.entry(row,value,12);ent.pack(side="left",padx=8,pady=5)
            fields[service]=(mode,value)
        tk.Label(panel,text="در روش دستی، مبلغ کارمزد هنگام انجام همان تراکنش پرسیده می‌شود.",bg=PANEL,fg=GOLD).pack(pady=8)
        def save():
            try:
                data={}
                for service,(mode,value) in fields.items():
                    v=Decimal(value.get().replace(',','').strip() or '0')
                    if v<0: raise ValueError(f"مقدار کارمزد {service} نامعتبر است.")
                    if mode.get() not in ("fixed","percent","manual"): raise ValueError("روش کارمزد نامعتبر است.")
                    data[service]={"mode":mode.get(),"value":float(v)}
                with connect() as c:
                    c.execute("INSERT INTO settings(key,value) VALUES('royal_fee_config',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(data,ensure_ascii=False),));c.commit()
                messagebox.showinfo("ذخیره شد","تنظیم کارمزد همه خدمات ذخیره شد.",parent=win);win.destroy()
            except Exception as e: messagebox.showerror("خطا در ذخیره",str(e),parent=win)
        self.btn(panel,"ذخیره تنظیمات",save,width=18).pack(pady=(2,12))

    def print_html(self,title,content):
        try:
            path=os.path.join(tempfile.gettempdir(),"royal_atm_print.html")
            html_doc=f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>{html.escape(title)}</title>
            <style>body{{font-family:Tahoma,Arial;direction:rtl;margin:30px;color:#172b3a}}h2{{text-align:center}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #777;padding:8px}}.foot{{margin-top:25px}}</style>
            <h2>{html.escape(title)}</h2>{content}<p class="foot">سامانه شبیه‌ساز خودپرداز رویال • {jalali_date(datetime.now().year,datetime.now().month,datetime.now().day)[0]}/{jalali_date(datetime.now().year,datetime.now().month,datetime.now().day)[1]:02d}/{jalali_date(datetime.now().year,datetime.now().month,datetime.now().day)[2]:02d}</p>
            <script>window.onload=()=>window.print()</script></html>"""
            with open(path,"w",encoding="utf-8") as f:f.write(html_doc)
            import webbrowser;webbrowser.open("file:///"+path.replace("\\\\","/"))
        except Exception as e:messagebox.showerror("خطای چاپ",str(e))

    def print_balance(self,balance):
        c=self.card
        content=f"<table><tr><th>نام صاحب حساب</th><td>{html.escape(c['full_name'])}</td></tr><tr><th>شماره حساب</th><td>{html.escape(c['account_no'])}</td></tr><tr><th>شماره کارت</th><td>{html.escape(c['card_no'])}</td></tr><tr><th>موجودی</th><td>{fmt(balance)} ریال</td></tr></table>"
        self.print_html("گزارش موجودی حساب",content)

    def print_transfer_receipt(self,data):
        content=f"<table><tr><th>حساب مبدأ</th><td>{html.escape(data['source'])}</td></tr><tr><th>حساب مقصد</th><td>{html.escape(data['destination'])}</td></tr><tr><th>مبلغ انتقال</th><td>{fmt(data['amount'])} ریال</td></tr><tr><th>تاریخ و ساعت</th><td>{html.escape(data['date'])}</td></tr><tr><th>وضعیت</th><td>موفق</td></tr></table>"
        self.print_html("رسید انتقال وجه",content)

    def balance(self):
        try:
            with connect() as c:r=c.execute("SELECT balance FROM accounts WHERE account_no=?",(self.card["account_no"],)).fetchone()
            if r:
                self.clear()
                panel=self.cardbox(self.body);panel.pack(expand=True,padx=120,pady=50,fill="x")
                tk.Label(panel,text="موجودی قابل برداشت",bg=PANEL,fg=MUTED,font=("Tahoma",12)).pack(pady=(25,8))
                tk.Label(panel,text=fmt(r["balance"])+" ریال",bg=PANEL,fg=ACCENT,font=("Tahoma",25,"bold")).pack(pady=8)
                actions=tk.Frame(panel,bg=PANEL);actions.pack(pady=(10,18))
                self.btn(actions,"چاپ موجودی حساب",lambda:self.print_balance(r["balance"]),width=18).pack(side="right",padx=5)
                self.btn(actions,"بازگشت به خدمات",self.menu_screen,"secondary",width=18).pack(side="right",padx=5)
        except Exception as e:messagebox.showerror("خطا",str(e))

    def transfer(self):
        win=tk.Toplevel(self);win.title("انتقال وجه");win.geometry("470x360");win.configure(bg=BG);win.transient(self);win.grab_set()
        panel=self.cardbox(win);panel.pack(fill="both",expand=True,padx=18,pady=18)
        tk.Label(panel,text="انتقال وجه",bg=PANEL,fg=TEXT,font=("Tahoma",17,"bold")).pack(pady=(18,8))
        tk.Label(panel,text="شماره حساب مقصد",bg=PANEL,fg=MUTED).pack(pady=(8,4))
        dst=tk.StringVar();self.entry(panel,dst,30).pack(ipady=7)
        tk.Label(panel,text="مبلغ انتقال (ریال)",bg=PANEL,fg=MUTED).pack(pady=(12,4))
        amount=tk.StringVar();self.entry(panel,amount,30).pack(ipady=7)
        tk.Label(panel,text="انتقال فقط به حساب فعال انجام می‌شود.",bg=PANEL,fg=GOLD,font=("Tahoma",9)).pack(pady=8)
        def submit():
            try:
                dest=dst.get().strip();val=Decimal(amount.get().replace(",","").strip())
                if val<=0:raise ValueError("مبلغ باید بیشتر از صفر باشد.")
                if dest==self.card["account_no"]:raise ValueError("حساب مقصد نباید حساب مبدا باشد.")
                with connect() as c:
                    fee=self.calculate_fee(c,"انتقال وجه",val,win)
                total=val+fee
                if not messagebox.askyesno("تأیید انتقال",f"انتقال: {fmt(val)} ریال\nکارمزد: {fmt(fee)} ریال\nمجموع کسر از حساب: {fmt(total)} ریال؟",parent=win):return
                with connect() as c:
                    c.execute("BEGIN IMMEDIATE")
                    src=c.execute("SELECT balance,status FROM accounts WHERE account_no=?",(self.card["account_no"],)).fetchone()
                    target=c.execute("SELECT status FROM accounts WHERE account_no=?",(dest,)).fetchone()
                    if not target:raise ValueError("حساب مقصد پیدا نشد.")
                    if src["status"]!="فعال" or target["status"]!="فعال":raise ValueError("هر دو حساب باید فعال باشند.")
                    if Decimal(str(src["balance"]))<total:raise ValueError("موجودی برای مبلغ انتقال و کارمزد کافی نیست.")
                    now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    c.execute("UPDATE accounts SET balance=balance-? WHERE account_no=?",(float(total),self.card["account_no"]))
                    c.execute("UPDATE accounts SET balance=balance+? WHERE account_no=?",(float(val),dest))
                    c.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",(self.card["account_no"],"انتقال خروجی",float(val),f"انتقال به {dest}",now,"Royal ATM"))
                    c.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",(dest,"انتقال ورودی",float(val),f"انتقال از {self.card['account_no']}",now,"Royal ATM"))
                    self.credit_main_fund(c,fee,"انتقال وجه",self.card["account_no"],now)
                    c.commit()
                win.destroy()
                self.last_transfer={"source":self.card["account_no"],"destination":dest,"amount":val,"date":now}
                if messagebox.askyesno("انتقال موفق","انتقال وجه ثبت شد. رسید چاپ شود؟"):
                    self.print_transfer_receipt(self.last_transfer)
            except (InvalidOperation,ValueError) as e:messagebox.showwarning("اطلاعات نامعتبر",str(e),parent=win)
            except Exception as e:messagebox.showerror("خطا",str(e),parent=win)
        self.btn(panel,"تأیید و انتقال",submit).pack(pady=(8,18))

    def installment_payment(self):
        win=tk.Toplevel(self);win.title("پرداخت اقساط");win.geometry("560x470");win.configure(bg=BG);win.transient(self);win.grab_set()
        panel=self.cardbox(win);panel.pack(fill="both",expand=True,padx=18,pady=18)
        tk.Label(panel,text="پرداخت قسط تسهیلات",bg=PANEL,fg=TEXT,font=("Tahoma",16,"bold")).pack(pady=(14,6))
        tk.Label(panel,text="وام فعال خود را انتخاب کنید؛ مبلغ پرداخت از موجودی حساب کسر و مانده بدهی به‌روزرسانی می‌شود.",bg=PANEL,fg=MUTED,wraplength=460).pack(pady=(0,12))
        loans=[]
        try:
            with connect() as c:
                loans=c.execute("SELECT id,principal,remaining,monthly_payment FROM loans WHERE account_no=? AND remaining>0 AND status='فعال' ORDER BY id DESC",(self.card["account_no"],)).fetchall()
        except Exception as exc:
            messagebox.showerror("خطا",f"دریافت فهرست وام‌ها ناموفق بود: {exc}",parent=win);win.destroy();return
        if not loans:
            tk.Label(panel,text="برای این حساب وام فعال با مانده بدهی ثبت نشده است.",bg=PANEL,fg=GOLD,font=("Tahoma",11,"bold")).pack(pady=24)
            self.btn(panel,"بستن",win.destroy,"secondary",12).pack(pady=12);return
        loan_map={f"وام شماره {r['id']}  |  مانده: {fmt(r['remaining'])} تومان":r for r in loans}
        selected=tk.StringVar(value=next(iter(loan_map)))
        tk.Label(panel,text="انتخاب وام",bg=PANEL,fg=MUTED).pack(pady=(6,3))
        combo=ttk.Combobox(panel,textvariable=selected,values=list(loan_map),state="readonly",width=48,justify="right")
        combo.pack(pady=4)
        info=tk.Label(panel,text="",bg=PANEL,fg=MUTED,font=("Tahoma",10));info.pack(pady=6)
        tk.Label(panel,text="مبلغ پرداخت (تومان)",bg=PANEL,fg=MUTED).pack(pady=(8,3))
        amount=tk.StringVar();self.entry(panel,amount,30).pack(ipady=5)
        def update_loan(*_):
            loan=loan_map.get(selected.get())
            if loan:
                info.configure(text=f"مبلغ قسط ماهانه: {fmt(loan['monthly_payment'])} تومان  |  مانده بدهی: {fmt(loan['remaining'])} تومان")
                amount.set(str(round(min(loan['monthly_payment'] or loan['remaining'],loan['remaining']),2)))
        combo.bind("<<ComboboxSelected>>",update_loan);update_loan()
        def submit():
            loan=loan_map.get(selected.get())
            try:
                val=Decimal(amount.get().replace(",","").strip())
                if not loan:raise ValueError("یک وام معتبر انتخاب کنید.")
                if val<=0 or val>Decimal(str(loan['remaining'])):raise ValueError("مبلغ باید مثبت و حداکثر برابر مانده بدهی باشد.")
                with connect() as c:
                    fee=self.calculate_fee(c,"پرداخت اقساط",val,win)
                total=val+fee
                if not messagebox.askyesno("تأیید پرداخت قسط",f"مبلغ قسط: {fmt(val)} تومان\nکارمزد: {fmt(fee)} تومان\nمجموع کسر از حساب: {fmt(total)} تومان؟",parent=win):return
                now=datetime.now().isoformat(timespec="seconds")
                with connect() as c:
                    c.execute("BEGIN IMMEDIATE")
                    account=c.execute("SELECT balance,status FROM accounts WHERE account_no=?",(self.card['account_no'],)).fetchone()
                    current=c.execute("SELECT remaining FROM loans WHERE id=? AND account_no=?",(loan['id'],self.card['account_no'])).fetchone()
                    if not account or account['status']!="فعال":raise ValueError("حساب فعال نیست.")
                    if not current or Decimal(str(current['remaining']))<val:raise ValueError("مانده وام تغییر کرده است؛ فهرست را دوباره بررسی کنید.")
                    if Decimal(str(account['balance']))<total:raise ValueError("موجودی حساب برای پرداخت قسط و کارمزد کافی نیست.")
                    remaining=round(float(current['remaining'])-float(val),2)
                    c.execute("UPDATE accounts SET balance=balance-? WHERE account_no=?",(float(total),self.card['account_no']))
                    c.execute("UPDATE loans SET remaining=?,status=? WHERE id=?",(remaining,"تسویه‌شده" if remaining<=0 else "فعال",loan['id']))
                    c.execute("INSERT INTO transactions(account_no,kind,amount,description,created_at,created_by) VALUES(?,?,?,?,?,?)",(self.card['account_no'],"پرداخت قسط وام",float(val),f"پرداخت قسط تسهیلات شماره {loan['id']}",now,"Royal ATM"))
                    self.credit_main_fund(c,fee,"پرداخت اقساط",self.card['account_no'],now)
                    c.commit()
                win.destroy();messagebox.showinfo("پرداخت موفق",f"قسط وام شماره {loan['id']} ثبت شد.\nمبلغ: {fmt(val)} تومان\nمانده بدهی: {fmt(remaining)} تومان",parent=self)
            except (InvalidOperation,ValueError) as e:messagebox.showwarning("اطلاعات نامعتبر",str(e),parent=win)
            except Exception as e:messagebox.showerror("خطا",f"ثبت پرداخت قسط ناموفق بود: {e}",parent=win)
        self.btn(panel,"تأیید و پرداخت قسط",submit).pack(pady=(12,16))

    def history(self):
        win=tk.Toplevel(self);win.title("گردش حساب");win.geometry("820x460");win.configure(bg=BG)
        tk.Label(win,text="گردش حساب",bg=BG,fg=TEXT,font=("Tahoma",16,"bold")).pack(pady=12)
        cols=("date","kind","amount","description")
        tree=ttk.Treeview(win,columns=cols,show="headings")
        for c,t in zip(cols,("تاریخ","نوع تراکنش","مبلغ (ریال)","شرح")):tree.heading(c,text=t)
        tree.column("date",width=160,anchor="center");tree.column("kind",width=150,anchor="center")
        tree.column("amount",width=140,anchor="center");tree.column("description",width=350,anchor="e")
        tree.pack(fill="both",expand=True,padx=16,pady=12)
        try:
            with connect() as c:rows=c.execute("SELECT * FROM transactions WHERE account_no=? ORDER BY created_at DESC LIMIT 200",(self.card["account_no"],)).fetchall()
            for r in rows:
                raw_date = r["created_at"] or ""
                shown_date = _jalali_datetime_text(raw_date)
                tree.insert("", "end", values=(shown_date,r["kind"],fmt(r["amount"]),r["description"] or ""))
        except Exception as e:messagebox.showerror("خطا",str(e),parent=win)
        actions=tk.Frame(win,bg=BG);actions.pack(fill="x",padx=16,pady=(0,14))
        self.btn(actions,"چاپ گزارش حساب",lambda:self.print_history(rows),width=20).pack(side="right",padx=5)
        self.btn(actions,"بستن",win.destroy,"secondary",width=12).pack(side="left",padx=5)

    def print_history(self, rows):
        """Create a clean printable HTML report and open it in the default browser."""
        try:
            account=self.card["account_no"]
            fullname=self.card["full_name"]
            total_in=sum(float(r["amount"] or 0) for r in rows if "ورودی" in str(r["kind"]))
            total_out=sum(float(r["amount"] or 0) for r in rows if "خروجی" in str(r["kind"]))
            body=[]
            for r in rows:
                body.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                    html.escape(_jalali_datetime_text(r["created_at"] or "")),
                    html.escape(str(r["kind"] or "")),
                    html.escape(fmt(r["amount"] or 0)),
                    html.escape(str(r["description"] or ""))))
            report="""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
            <title>گزارش گردش حساب رویال</title><style>
            body{font-family:Tahoma,Arial,sans-serif;color:#183047;margin:30px}
            header{border-bottom:3px solid #19b5a5;padding-bottom:12px;margin-bottom:20px}
            h1{font-size:22px;margin:0 0 8px} .meta{color:#536b7d}
            .summary{display:flex;gap:12px;margin:18px 0}.summary div{border:1px solid #ccd8e0;padding:12px;border-radius:8px;flex:1}
            table{width:100%;border-collapse:collapse;margin-top:18px}th,td{border:1px solid #cbd5dd;padding:9px;text-align:right}
            th{background:#eaf3f5}tfoot{font-weight:bold}.foot{margin-top:25px;color:#718392;font-size:11px}
            @media print{button{display:none}body{margin:12mm}}
            </style></head><body>
            <header><h1>بانک رویال — گزارش گردش حساب</h1>
            <div class="meta">نام صاحب حساب: """+html.escape(fullname)+"""　 |　 شماره حساب: """+html.escape(account)+"""</div>
            <div class="meta">تاریخ تهیه گزارش (شمسی): """+_jalali_datetime_text(datetime.now().isoformat(timespec="seconds"))+"""</div></header>
            <div class="summary"><div>جمع ورودی: <b>"""+fmt(total_in)+""" ریال</b></div><div>جمع خروجی: <b>"""+fmt(total_out)+""" ریال</b></div><div>تعداد تراکنش: <b>"""+str(len(rows))+"""</b></div></div>
            <button onclick="window.print()">چاپ گزارش</button>
            <table><thead><tr><th>تاریخ</th><th>نوع تراکنش</th><th>مبلغ (ریال)</th><th>شرح</th></tr></thead>
            <tbody>"""+ "".join(body)+"""</tbody></table>
            <div class="foot">گزارش تهیه‌شده توسط شبیه‌ساز خودپرداز رویال — نسخه آزمایشی محلی</div>
            </body></html>"""
            fd,path=tempfile.mkstemp(prefix="royal_account_report_",suffix=".html")
            with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(report)
            import webbrowser
            webbrowser.open("file://"+os.path.abspath(path))
            messagebox.showinfo("گزارش آماده چاپ","گزارش در مرورگر باز شد. در پنجره چاپ، چاپگر یا «ذخیره به‌صورت PDF» را انتخاب کنید.",parent=self)
        except Exception as e:
            messagebox.showerror("خطای چاپ",str(e),parent=self)

if __name__=="__main__":ATM().mainloop()
