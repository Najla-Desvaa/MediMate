"""SQLite persistence and atomic stock/intake bookkeeping for MediMate."""
from __future__ import annotations

import os
import sqlite3
import hashlib
import re
from contextvars import ContextVar
import tempfile
from datetime import date, timedelta
from contextlib import contextmanager
from pathlib import Path

from medimate_core import (
    ValidationError, clean_name, expiry_label, integer_quantity, local_timestamp,
    local_today, optional_text, parse_clock, parse_date, schedule_on_date, daily_intake_times,
)

APP_ID = 0x4D454449  # 'MEDI'; reject unrelated databases on restore
DATA_DIR = Path(os.environ.get("MEDIMATE_DATA_DIR", Path(__file__).resolve().parent / "data"))
DB_PATH = DATA_DIR / "medimate.sqlite"
# The full name selects its associated records. It is not a password-protected account.
_PROFILE = ContextVar("medimate_profile", default=None)


def display_name(raw: str) -> str:
    """Preserve a person's capitalization while standardizing extra spaces."""
    if not isinstance(raw, str):
        raise ValidationError("Masukkan nama lengkap / Enter your full name.")
    name = " ".join(raw.split())
    # Accept single-word legal names as well as multiple-word full names.
    if not (2 <= len(name) <= 80) or not re.fullmatch(r"[^\W_]+(?:[ .’'-][^\W_]+)*", name, flags=re.UNICODE):
        raise ValidationError("Nama harus 2–80 karakter dan hanya berisi huruf serta pemisah nama yang wajar.")
    return name


def profile_name(raw: str) -> str:
    """Canonical key: case- and whitespace-insensitive, so the same full name reopens its records."""
    return display_name(raw).casefold()


def _database_path() -> Path:
    profile = _PROFILE.get()
    if profile is None:
        return DB_PATH
    digest = hashlib.sha256(profile.encode("utf-8")).hexdigest()[:32]
    return DATA_DIR / "profiles" / (digest + ".sqlite")


@contextmanager
def use_profile(full_name: str):
    token = _PROFILE.set(profile_name(full_name))
    try:
        yield
    finally:
        _PROFILE.reset(token)


def configure_data_dir(folder: str | Path):
    """Set data directory before first use (primarily for testing)."""
    global DATA_DIR, DB_PATH
    DATA_DIR = Path(folder)
    DB_PATH = DATA_DIR / "medimate.sqlite"


@contextmanager
def connect():
    """Commit/rollback and ALWAYS close SQLite handles, including on errors."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS medicines (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL, form TEXT NOT NULL CHECK(form IN ('Tablet','Kapsul')),
          strength TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL CHECK(unit IN ('tablet','kapsul')),
          low_stock INTEGER NOT NULL CHECK(low_stock >= 0), notes TEXT NOT NULL DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS batches (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          medicine_id INTEGER NOT NULL REFERENCES medicines(id),
          qty INTEGER NOT NULL CHECK(qty >= 0), expiry TEXT NOT NULL,
          received_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schedules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          medicine_id INTEGER NOT NULL REFERENCES medicines(id),
          at_time TEXT NOT NULL, qty_per_intake INTEGER NOT NULL CHECK(qty_per_intake > 0),
          start_date TEXT NOT NULL, end_date TEXT, archived_on TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS intake_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          schedule_id INTEGER NOT NULL REFERENCES schedules(id),
          scheduled_date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('taken','skipped')),
          recorded_at TEXT NOT NULL, stock_deducted INTEGER NOT NULL DEFAULT 0,
          warning TEXT NOT NULL DEFAULT '',
          UNIQUE(schedule_id, scheduled_date)
        );
        CREATE TABLE IF NOT EXISTS stock_movements (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          medicine_id INTEGER NOT NULL REFERENCES medicines(id),
          batch_id INTEGER NOT NULL REFERENCES batches(id),
          qty_delta INTEGER NOT NULL, reason TEXT NOT NULL,
          intake_log_id INTEGER REFERENCES intake_logs(id),
          reverted INTEGER NOT NULL DEFAULT 0 CHECK(reverted IN (0,1)),
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_schedules_medicine ON schedules(medicine_id);
        CREATE INDEX IF NOT EXISTS idx_logs_schedule_day ON intake_logs(schedule_id,scheduled_date);
        CREATE INDEX IF NOT EXISTS idx_batches_medicine ON batches(medicine_id);
        """)
        db.execute(f"PRAGMA application_id={APP_ID}")
        db.execute("PRAGMA user_version=1")


def rows(sql: str, args: tuple = ()) -> list[dict]:
    with connect() as db:
        return [dict(r) for r in db.execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    found = rows(sql, args)
    return found[0] if found else None


def _require_medicine(db: sqlite3.Connection, mid: int) -> sqlite3.Row:
    med = db.execute("SELECT * FROM medicines WHERE id=?", (mid,)).fetchone()
    if med is None:
        raise ValidationError("Obat tidak ditemukan.")
    return med


def medicine_list(active_only: bool = False) -> list[dict]:
    return rows("SELECT * FROM medicines " + ("WHERE active=1 " if active_only else "") + "ORDER BY active DESC, name COLLATE NOCASE")


def add_medicine(name, form, strength, initial_stock, low_stock, expiry, notes, zone) -> int:
    clean = clean_name(name)
    if form not in ("Tablet", "Kapsul"):
        raise ValidationError("Bentuk obat harus Tablet atau Kapsul.")
    stock = integer_quantity(initial_stock, "Stok awal")
    low = integer_quantity(low_stock, "Batas stok rendah")
    exp = parse_date(expiry, "Tanggal kedaluwarsa").isoformat()
    strength = optional_text(strength, "Kekuatan sesuai label", 120)
    notes = optional_text(notes, "Catatan")
    stamp = local_timestamp(zone)
    with connect() as db:
        cur = db.execute("INSERT INTO medicines(name,form,strength,unit,low_stock,notes,created_at) VALUES(?,?,?,?,?,?,?)",
                         (clean, form, strength, "tablet" if form == "Tablet" else "kapsul", low, notes, stamp))
        mid = cur.lastrowid
        batch = db.execute("INSERT INTO batches(medicine_id,qty,expiry,received_at) VALUES(?,?,?,?)", (mid, stock, exp, stamp))
        db.execute("INSERT INTO stock_movements(medicine_id,batch_id,qty_delta,reason,created_at) VALUES(?,?,?,'initial',?)",
                   (mid, batch.lastrowid, stock, stamp))
    return mid


def add_medicine_with_plan(name, form, strength, initial_stock, low_stock, expiry, notes,
                           qty_per_intake, frequency, clock_values, start, end, zone):
    """Create medicine, initial batch and one independent schedule per daily time atomically."""
    clean = clean_name(name)
    if form not in ("Tablet", "Kapsul"):
        raise ValidationError("Bentuk obat harus Tablet atau Kapsul.")
    stock = integer_quantity(initial_stock, "Stok awal")
    low = integer_quantity(low_stock, "Batas stok rendah")
    exp = parse_date(expiry, "Tanggal kedaluwarsa").isoformat()
    strength = optional_text(strength, "Kekuatan sesuai label", 120)
    notes = optional_text(notes, "Catatan")
    dose = integer_quantity(qty_per_intake, "Jumlah per konsumsi", minimum=1)
    times = daily_intake_times(frequency, clock_values)
    start = parse_date(start, "Tanggal mulai").isoformat()
    end = parse_date(end, "Tanggal akhir").isoformat() if end and str(end).strip() else None
    if end is not None and end < start:
        raise ValidationError("Tanggal akhir tidak boleh sebelum tanggal mulai.")
    stamp = local_timestamp(zone)
    with connect() as conn:
        cur = conn.execute("INSERT INTO medicines(name,form,strength,unit,low_stock,notes,created_at) VALUES(?,?,?,?,?,?,?)",
                           (clean, form, strength, "tablet" if form == "Tablet" else "kapsul", low, notes, stamp))
        mid = cur.lastrowid
        batch = conn.execute("INSERT INTO batches(medicine_id,qty,expiry,received_at) VALUES(?,?,?,?)", (mid, stock, exp, stamp))
        conn.execute("INSERT INTO stock_movements(medicine_id,batch_id,qty_delta,reason,created_at) VALUES(?,?,?,'initial',?)",
                     (mid, batch.lastrowid, stock, stamp))
        conn.executemany("INSERT INTO schedules(medicine_id,at_time,qty_per_intake,start_date,end_date,created_at) VALUES(?,?,?,?,?,?)",
                         [(mid, clock, dose, start, end, stamp) for clock in times])
    return mid


def update_medicine(mid, name, strength, low_stock, notes):
    if mid is None or mid == "":
        raise ValidationError("Pilih obat yang ingin diubah.")
    mid = int(mid)
    name = clean_name(name)
    strength = optional_text(strength, "Kekuatan sesuai label", 120)
    low = integer_quantity(low_stock, "Batas stok rendah")
    notes = optional_text(notes, "Catatan")
    with connect() as db:
        _require_medicine(db, mid)
        db.execute("UPDATE medicines SET name=?,strength=?,low_stock=?,notes=? WHERE id=?", (name, strength, low, notes, mid))


def set_medicine_active(mid, active: bool):
    if mid in (None, ""):
        raise ValidationError("Pilih obat terlebih dahulu.")
    with connect() as db:
        _require_medicine(db, int(mid))
        db.execute("UPDATE medicines SET active=? WHERE id=?", (int(active), int(mid)))


def add_batch(mid, quantity, expiry, zone):
    if mid in (None, ""):
        raise ValidationError("Pilih obat untuk penambahan stok.")
    quantity = integer_quantity(quantity, "Jumlah stok baru", minimum=1)
    exp = parse_date(expiry, "Tanggal kedaluwarsa").isoformat()
    stamp = local_timestamp(zone)
    with connect() as db:
        med = _require_medicine(db, int(mid))
        if not med["active"]:
            raise ValidationError("Obat nonaktif tidak bisa ditambah stok sebelum diaktifkan.")
        row = db.execute("INSERT INTO batches(medicine_id,qty,expiry,received_at) VALUES(?,?,?,?)", (int(mid), quantity, exp, stamp))
        db.execute("INSERT INTO stock_movements(medicine_id,batch_id,qty_delta,reason,created_at) VALUES(?,?,?,'refill',?)",
                   (int(mid), row.lastrowid, quantity, stamp))


def _validate_schedule(med_id, at_time, qty, start, end):
    if med_id in (None, ""):
        raise ValidationError("Pilih obat untuk jadwal.")
    t = parse_clock(at_time)
    q = integer_quantity(qty, "Jumlah per konsumsi", 1)
    start = parse_date(start, "Tanggal mulai").isoformat()
    end = parse_date(end, "Tanggal akhir").isoformat() if end and str(end).strip() else None
    if end is not None and end < start:
        raise ValidationError("Tanggal akhir tidak boleh sebelum tanggal mulai.")
    return int(med_id), t, q, start, end


def schedule_list() -> list[dict]:
    return rows("""SELECT s.*,m.name AS medicine,m.unit,m.active AS medicine_active
                   FROM schedules s JOIN medicines m ON m.id=s.medicine_id
                   ORDER BY s.start_date DESC,s.at_time,s.id""")


def add_schedule(med_id, at_time, qty, start, end, zone):
    mid, t, q, start, end = _validate_schedule(med_id, at_time, qty, start, end)
    with connect() as db:
        med = _require_medicine(db, mid)
        if not med["active"]:
            raise ValidationError("Aktifkan obat terlebih dahulu untuk menambah jadwal.")
        exists = db.execute("""SELECT id FROM schedules WHERE medicine_id=? AND at_time=?
          AND archived_on IS NULL AND (end_date IS NULL OR end_date>=?)
          AND (? IS NULL OR start_date<=?)""", (mid, t, start, end, end)).fetchone()
        if exists:
            raise ValidationError("Jadwal pada jam ini sudah ada dengan rentang tanggal yang bertumpuk.")
        db.execute("INSERT INTO schedules(medicine_id,at_time,qty_per_intake,start_date,end_date,created_at) VALUES(?,?,?,?,?,?)",
                   (mid, t, q, start, end, local_timestamp(zone)))


def add_daily_plan(med_id, qty_per_intake, frequency, clock_values, start, end, zone):
    """Save a whole daily set or save none; prevent collisions with existing schedules."""
    if med_id in (None, ""):
        raise ValidationError("Pilih obat untuk jadwal.")
    mid = int(med_id)
    times = daily_intake_times(frequency, clock_values)
    dose = integer_quantity(qty_per_intake, "Jumlah per konsumsi", minimum=1)
    start = parse_date(start, "Tanggal mulai").isoformat()
    end = parse_date(end, "Tanggal akhir").isoformat() if end and str(end).strip() else None
    if end is not None and end < start:
        raise ValidationError("Tanggal akhir tidak boleh sebelum tanggal mulai.")
    with connect() as conn:
        med = _require_medicine(conn, mid)
        if not med["active"]:
            raise ValidationError("Aktifkan obat terlebih dahulu untuk menambah jadwal.")
        for clock in times:
            clash = conn.execute("""SELECT 1 FROM schedules WHERE medicine_id=? AND at_time=?
                AND archived_on IS NULL AND (end_date IS NULL OR end_date>=?)
                AND (? IS NULL OR start_date<=?) LIMIT 1""",
                (mid, clock, start, end, end)).fetchone()
            if clash:
                raise ValidationError(f"Jam {clock} sudah memiliki jadwal dengan periode bertumpuk. Tidak ada perubahan disimpan.")
        stamp = local_timestamp(zone)
        conn.executemany("INSERT INTO schedules(medicine_id,at_time,qty_per_intake,start_date,end_date,created_at) VALUES(?,?,?,?,?,?)",
                         [(mid, clock, dose, start, end, stamp) for clock in times])
    return len(times)


def update_schedule(sid, med_id, at_time, qty, start, end):
    if sid in (None, ""):
        raise ValidationError("Pilih jadwal yang ingin diubah.")
    mid, t, q, start, end = _validate_schedule(med_id, at_time, qty, start, end)
    with connect() as db:
        existing = db.execute("SELECT * FROM schedules WHERE id=?", (int(sid),)).fetchone()
        if existing is None:
            raise ValidationError("Jadwal tidak ditemukan.")
        if existing["archived_on"]:
            raise ValidationError("Jadwal yang diarsipkan tidak dapat diubah.")
        if db.execute("SELECT 1 FROM intake_logs WHERE schedule_id=? LIMIT 1", (int(sid),)).fetchone():
            raise ValidationError("Jadwal sudah memiliki riwayat. Arsipkan dan buat jadwal baru untuk menjaga integritas riwayat.")
        _require_medicine(db, mid)
        clash = db.execute("""SELECT 1 FROM schedules WHERE id<>? AND medicine_id=? AND at_time=?
        AND archived_on IS NULL AND (end_date IS NULL OR end_date>=?)
        AND (? IS NULL OR start_date<=?) LIMIT 1""", (int(sid), mid, t, start, end, end)).fetchone()
        if clash:
            raise ValidationError("Rentang waktu bertumpuk dengan jadwal lain.")
        db.execute("UPDATE schedules SET medicine_id=?,at_time=?,qty_per_intake=?,start_date=?,end_date=? WHERE id=?",
                   (mid, t, q, start, end, int(sid)))


def archive_schedule(sid, zone):
    if sid in (None, ""):
        raise ValidationError("Pilih jadwal yang ingin diarsipkan.")
    day = local_today(zone).isoformat()
    with connect() as db:
        cur = db.execute("UPDATE schedules SET archived_on=? WHERE id=? AND archived_on IS NULL", (day, int(sid)))
        if cur.rowcount == 0:
            raise ValidationError("Jadwal tidak ditemukan atau sudah diarsipkan.")


def _day_events_conn(db: sqlite3.Connection, day: date) -> list[dict]:
    result = []
    records = db.execute("""SELECT s.*, m.name AS medicine, m.unit, m.active AS medicine_active
      FROM schedules s JOIN medicines m ON m.id=s.medicine_id
      ORDER BY s.at_time,m.name""").fetchall()
    for r in records:
        if not r["medicine_active"] or not schedule_on_date(r["start_date"], r["end_date"], r["archived_on"], day):
            continue
        log = db.execute("SELECT status,stock_deducted,warning,recorded_at FROM intake_logs WHERE schedule_id=? AND scheduled_date=?",
                         (r["id"], day.isoformat())).fetchone()
        result.append(dict(schedule_id=r["id"], scheduled_date=day.isoformat(), medicine=r["medicine"],
                           medicine_id=r["medicine_id"], at_time=r["at_time"], qty=r["qty_per_intake"],
                           unit=r["unit"], status=log["status"] if log else "unrecorded",
                           deducted=log["stock_deducted"] if log else 0,
                           warning=log["warning"] if log else "",
                           recorded_at=log["recorded_at"] if log else ""))
    return result


def day_events(day: str | date) -> list[dict]:
    d = parse_date(day)
    with connect() as db:
        return _day_events_conn(db, d)


def _restore_allocation(db, log_id: int, zone: str):
    """Reverse each active intake movement exactly once, on its original batch."""
    active = db.execute("SELECT id,medicine_id,batch_id,qty_delta FROM stock_movements WHERE intake_log_id=? AND reason='intake' AND reverted=0", (log_id,)).fetchall()
    for mov in active:
        restored = -int(mov["qty_delta"])
        db.execute("UPDATE batches SET qty=qty+? WHERE id=?", (restored, mov["batch_id"]))
        db.execute("UPDATE stock_movements SET reverted=1 WHERE id=?", (mov["id"],))
        db.execute("INSERT INTO stock_movements(medicine_id,batch_id,qty_delta,reason,intake_log_id,created_at) VALUES(?,?,?,'reversal',?,?)",
                   (mov["medicine_id"], mov["batch_id"], restored, log_id, local_timestamp(zone)))


def record_intake(sid, day, action, zone):
    """Idempotent update with atomic stock deduction/reversal.

    If insufficient eligible (unexpired) stock, preserve the user's reported
    taken event without deducting anything; show a reconciliation warning.
    """
    if sid in (None, ""):
        raise ValidationError("Pilih jadwal dari daftar untuk mencatat konsumsi.")
    day = parse_date(day)
    if day > local_today(zone):
        raise ValidationError("Tidak bisa mencatat konsumsi pada tanggal mendatang.")
    if action not in ("taken", "skipped", "clear"):
        raise ValidationError("Status pencatatan tidak dikenali.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        s = db.execute("SELECT s.*,m.active FROM schedules s JOIN medicines m ON m.id=s.medicine_id WHERE s.id=?", (int(sid),)).fetchone()
        if not s:
            raise ValidationError("Jadwal tidak ditemukan.")
        if not schedule_on_date(s["start_date"],s["end_date"],s["archived_on"],day):
            raise ValidationError("Tanggal di luar periode jadwal tersebut.")
        old = db.execute("SELECT * FROM intake_logs WHERE schedule_id=? AND scheduled_date=?", (int(sid),day.isoformat())).fetchone()
        if old and old["status"] == action:
            return "Status sudah tercatat; stok tidak diubah lagi."
        if old and old["status"] == "taken":
            _restore_allocation(db, old["id"], zone)
        if action == "clear":
            if old:
                db.execute("DELETE FROM stock_movements WHERE intake_log_id=?", (old["id"],))
                db.execute("DELETE FROM intake_logs WHERE id=?", (old["id"],))
            return "Pencatatan dibatalkan; alokasi stok sebelumnya telah dikembalikan."
        stamp = local_timestamp(zone)
        if old:
            lid = old["id"]
            db.execute("UPDATE intake_logs SET status=?,recorded_at=?,stock_deducted=0,warning='' WHERE id=?", (action,stamp,lid))
        else:
            cur = db.execute("INSERT INTO intake_logs(schedule_id,scheduled_date,status,recorded_at) VALUES(?,?,?,?)",
                             (int(sid),day.isoformat(),action,stamp))
            lid = cur.lastrowid
        if action == "skipped":
            return "Status Dilewati tersimpan; stok tidak berubah."
        needed = int(s["qty_per_intake"])
        batches = db.execute("SELECT * FROM batches WHERE medicine_id=? AND expiry>=? AND qty>0 ORDER BY expiry,id",
                             (s["medicine_id"], day.isoformat())).fetchall()
        available = sum(int(b["qty"]) for b in batches)
        if available < needed:
            message = (f"Stok layak pakai yang tercatat hanya {available}, sedangkan catatan konsumsi {needed}. "
                       "Status Diminum tersimpan tanpa pengurangan stok. Periksa kesesuaian catatan persediaan.")
            db.execute("UPDATE intake_logs SET warning=? WHERE id=?", (message,lid))
            return message
        rem = needed
        for batch in batches:
            take = min(rem, int(batch["qty"]))
            if take == 0:
                continue
            db.execute("UPDATE batches SET qty=qty-? WHERE id=?", (take,batch["id"]))
            db.execute("INSERT INTO stock_movements(medicine_id,batch_id,qty_delta,reason,intake_log_id,created_at) VALUES(?,?,?,'intake',?,?)",
                       (s["medicine_id"],batch["id"],-take,lid,stamp))
            rem -= take
            if rem == 0:
                break
        db.execute("UPDATE intake_logs SET stock_deducted=? WHERE id=?", (needed,lid))
        return f"Status Diminum tersimpan; stok berkurang {needed} unit tanpa penggandaan."


def stock_snapshot(day: date) -> list[dict]:
    data = medicine_list(active_only=True)
    with connect() as db:
        for m in data:
            batches = db.execute("SELECT qty,expiry FROM batches WHERE medicine_id=?", (m["id"],)).fetchall()
            m["stock_total"] = sum(int(b["qty"]) for b in batches)
            m["stock_usable"] = sum(int(b["qty"]) for b in batches if b["expiry"] >= day.isoformat())
            m["stock_expired"] = m["stock_total"] - m["stock_usable"]
            m["low"] = m["stock_usable"] <= m["low_stock"]
            expiring = [b["expiry"] for b in batches if b["qty"] > 0 and b["expiry"] >= day.isoformat()]
            m["nearest_expiry"] = min(expiring) if expiring else "—"
            m["expiry_status"] = expiry_label(m["nearest_expiry"],day) if expiring else "Tidak ada stok layak pakai"
    return data


def batch_list(day: date) -> list[dict]:
    result = rows("""SELECT b.id,b.medicine_id,m.name AS medicine,b.qty,b.expiry,m.unit
            FROM batches b JOIN medicines m ON m.id=b.medicine_id WHERE m.active=1
            ORDER BY b.expiry,b.id""")
    for r in result:
        r["status"] = expiry_label(r["expiry"],day) if r["qty"] else "Habis"
    return result


def log_history(limit: int = 200) -> list[dict]:
    return rows("""SELECT l.scheduled_date,s.at_time,m.name AS medicine,l.status,
        s.qty_per_intake AS quantity,l.stock_deducted,l.warning,l.recorded_at
        FROM intake_logs l JOIN schedules s ON s.id=l.schedule_id
        JOIN medicines m ON m.id=s.medicine_id
        ORDER BY julianday(l.recorded_at) DESC,l.id DESC LIMIT ?""",(limit,))


def analytics_events(start: date, end: date, zone: str) -> list[dict]:
    if end < start:
        raise ValidationError("Akhir periode lebih awal daripada awal periode.")
    if (end-start).days > 366:
        raise ValidationError("Periode analisis maksimal 366 hari.")
    from medimate_core import is_past_event
    observed = []
    with connect() as db:
        current = start
        while current <= end:
            for ev in _day_events_conn(db, current):
                if is_past_event(current, ev["at_time"],zone):
                    observed.append(ev)
            current += timedelta(days=1)
    return observed


def export_database() -> str:
    """Consistent SQLite backup, never a raw copy of a possibly open DB."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest_dir = Path(tempfile.mkdtemp(prefix="medimate_backup_"))
    output = dest_dir / "MediMate_Backup.sqlite"
    with connect() as source:
        backup = sqlite3.connect(output)
        try:
            source.backup(backup)
        finally:
            backup.close()
    return str(output)


def import_database(path: str, confirmation: str):
    """Accept only a valid MediMate SQLite backup, replace after validation."""
    if confirmation != "RESTORE":
        raise ValidationError("Ketik RESTORE untuk mengonfirmasi penggantian seluruh data.")
    if not path or not Path(path).is_file():
        raise ValidationError("Pilih file backup SQLite yang valid.")
    if Path(path).stat().st_size > 10_000_000:
        raise ValidationError("File backup melebihi batas 10 MB.")
    dest_path = _database_path()
    staging = dest_path.with_name(dest_path.stem + "_restore_staging.sqlite")
    dest_path.parent.mkdir(parents=True,exist_ok=True)
    if staging.exists():
        staging.unlink()
    try:
        source = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValidationError("File backup gagal pemeriksaan integritas.")
            if source.execute("PRAGMA application_id").fetchone()[0] != APP_ID or source.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValidationError("File backup MediMate tidak didukung atau tidak valid.")
            expected = ("medicines", "batches", "schedules", "intake_logs", "stock_movements")
            for table in expected:
                if not source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    raise ValidationError("Struktur backup MediMate tidak lengkap.")
            if source.execute("PRAGMA foreign_key_check").fetchone():
                raise ValidationError("Backup memiliki referensi database yang rusak.")
            if source.execute("SELECT COUNT(*) FROM intake_logs").fetchone()[0] > 50_000:
                raise ValidationError("Backup melebihi batas data prototipe.")
            target = sqlite3.connect(staging)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        os.replace(staging,dest_path)
    except (sqlite3.DatabaseError, OSError) as exc:
        raise ValidationError("Backup tidak dapat dibaca sebagai database MediMate yang valid.") from exc
    finally:
        if staging.exists():
            staging.unlink()
