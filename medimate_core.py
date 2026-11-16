"""Pure, testable, non-clinical rules for MediMate.

MediMate never recommends medicines or determines dosage. All quantities and
schedules are entered by the user from existing instructions.
"""
from __future__ import annotations

from datetime import date, datetime, time
from collections.abc import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SUPPORTED_ZONES = ("Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura")
MAX_STOCK = 1_000_000
MAX_DAILY_INTAKES = 6


class ValidationError(ValueError):
    """Invalid user input suitable for display in the UI."""


def parse_date(value: str | date, label: str = "Tanggal") -> date:
    if isinstance(value, datetime):
        raise ValidationError(f"{label} harus berupa tanggal YYYY-MM-DD.")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{label} harus menggunakan format YYYY-MM-DD.") from None


def parse_clock(value: str) -> str:
    try:
        if not isinstance(value, str) or len(value.strip()) != 5:
            raise ValueError
        parsed = time.fromisoformat(value.strip())
        if parsed.second or parsed.microsecond:
            raise ValueError
        return parsed.strftime("%H:%M")
    except ValueError:
        raise ValidationError("Jam harus menggunakan format HH:MM (contoh: 08:30).") from None


def integer_quantity(value, label: str, minimum: int = 0) -> int:
    if value is None or isinstance(value, bool):
        raise ValidationError(f"{label} wajib diisi dengan bilangan bulat.")
    try:
        as_float = float(value)
        if not as_float.is_integer():
            raise ValueError
        q = int(as_float)
    except (ValueError, TypeError, OverflowError):
        raise ValidationError(f"{label} harus berupa bilangan bulat.") from None
    if q < minimum or q > MAX_STOCK:
        raise ValidationError(f"{label} harus berada pada rentang {minimum}–{MAX_STOCK:,}.")
    return q


def daily_intake_times(frequency, clock_values: Sequence[str]) -> list[str]:
    """Validate a daily frequency and independent clock times (one event per time)."""
    count = integer_quantity(frequency, "Frekuensi per hari", minimum=1)
    if count > MAX_DAILY_INTAKES:
        raise ValidationError(f"Frekuensi maksimal {MAX_DAILY_INTAKES} kali dalam sehari.")
    if len(clock_values) < count:
        raise ValidationError("Isi jam untuk setiap kali minum.")
    selected = [parse_clock(clock_values[i]) for i in range(count)]
    if len(set(selected)) != count:
        raise ValidationError("Jam setiap kali minum harus berbeda.")
    return sorted(selected)


def clean_name(value: str, label: str = "Nama obat", max_length: int = 120) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} tidak boleh kosong.")
    name = " ".join(value.split())
    if len(name) > max_length:
        raise ValidationError(f"{label} terlalu panjang (maksimal {max_length} karakter).")
    return name


def optional_text(value: str | None, label: str, max_length: int = 500) -> str:
    text = (value or "").strip()
    if len(text) > max_length:
        raise ValidationError(f"{label} terlalu panjang (maksimal {max_length} karakter).")
    return text


def local_today(zone: str) -> date:
    if zone not in SUPPORTED_ZONES:
        raise ValidationError("Zona waktu tidak dikenali.")
    try:
        return datetime.now(ZoneInfo(zone)).date()
    except ZoneInfoNotFoundError:
        raise ValidationError("Data zona waktu tidak tersedia pada sistem.") from None


def local_timestamp(zone: str) -> str:
    if zone not in SUPPORTED_ZONES:
        raise ValidationError("Zona waktu tidak dikenali.")
    return datetime.now(ZoneInfo(zone)).isoformat(timespec="seconds")


def expiry_label(expiry: str | date, today: date, warning_days: int = 30) -> str:
    gap = (parse_date(expiry, "Tanggal kedaluwarsa") - today).days
    if gap < 0:
        return "Kedaluwarsa"
    if gap <= warning_days:
        return "Mendekati kedaluwarsa"
    return "Baik"


def schedule_on_date(start: str, end: str | None, archived_on: str | None, target: date) -> bool:
    if target < parse_date(start):
        return False
    if end and target > parse_date(end):
        return False
    if archived_on and target >= parse_date(archived_on):
        return False
    return True


def is_past_event(scheduled_date: date, clock: str, zone: str) -> bool:
    now = datetime.now(ZoneInfo(zone))
    d = parse_date(scheduled_date)
    t = time.fromisoformat(parse_clock(clock))
    return datetime.combine(d, t, tzinfo=ZoneInfo(zone)) <= now


def recording_rate(taken: int, all_past: int) -> float:
    """Recorded-taken proportion, NOT clinically verified adherence."""
    return round(100.0 * taken / all_past, 1) if all_past else 0.0


def local_recorded_time(timestamp: str, zone: str) -> str:
    """Render a saved ISO timestamp as local date, HH:MM and selected WIB/WITA/WIT.

    Intake timestamps carry UTC offsets, so converting the display does not
    alter the instant stored in SQLite. Legacy offset-free timestamps are
    displayed without an unearned time zone label.
    """
    if zone not in SUPPORTED_ZONES:
        raise ValidationError("Zona waktu tidak dikenali.")
    if not timestamp:
        return "—"
    try:
        when = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return str(timestamp)
    if when.tzinfo is None:
        return when.strftime("%d/%m/%Y %H:%M")
    where = when.astimezone(ZoneInfo(zone))
    suffix = {"Asia/Jakarta": "WIB", "Asia/Makassar": "WITA", "Asia/Jayapura": "WIT"}[zone]
    return f"{where:%d/%m/%Y %H:%M} {suffix}"
