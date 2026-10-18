"""Supabase budget guard: persistent counters and hard caps for every Supabase write path.

Every path that spends Supabase quota asks this guard first: PostgREST upserts (database size), Realtime broadcasts and
presence (messages), Storage uploads (storage and per-object size), signed URLs handed to browsers (egress), the Edge
Function inbox (invocations) and Storage image transformations (origin images, Pro only). A refusal never raises: the
caller falls back to local behaviour, and the guard records one event per cap per UTC day.

Counters persist in the SQLite `meta` table under `supa:budget:*`, so a restart never resets a day's spend. Caps come
from env with plan defaults selected by `SUPABASE_PLAN=free|pro` (default free). An env value above the plan ceiling (90 %
of what the plan includes) is clamped to the ceiling and reported as clamped.

Realtime messages are counted the way Supabase bills them (docs: guides/platform/manage-your-usage/realtime-messages):
"Each broadcast message counts as one message sent plus one message per subscribed client that receives it" and "Each
database change counts as one message per client that listens to the event"; Presence is billed in the same pool. So a
HUD broadcast to N viewers costs 1 + N, a presence join costs 1 + N and a leave costs N.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from .sites import DEMO_SITE

MB = 1024 * 1024
PLANS = ("free", "pro")


@dataclass(frozen=True)
class Cap:
    key: str
    env: str
    unit: str
    period: str            # day | month | gauge | object
    defaults: dict          # plan -> default cap (in `unit`)
    limits: dict            # plan -> (included amount in `unit`, period of that amount) or None when not available
    note: str = ""


# Plan limits: Free from supabase.com/pricing and the Realtime limits page (verified for this build); Pro from the same pages.
CAPS: tuple[Cap, ...] = (
    Cap("realtime_msgs_day", "SUPABASE_CAP_REALTIME_MSGS_DAY", "messages", "day", {"free": 40_000, "pro": 100_000},
        {"free": (2_000_000, "month"), "pro": (5_000_000, "month")}, "fan-out counted: a broadcast to N viewers costs 1 + N"),
    Cap("realtime_msgs_month", "SUPABASE_CAP_REALTIME_MSGS_MONTH", "messages", "month", {"free": 1_000_000, "pro": 3_000_000},
        {"free": (2_000_000, "month"), "pro": (5_000_000, "month")}),
    Cap("realtime_viewers", "SUPABASE_CAP_REALTIME_VIEWERS", "connections", "gauge", {"free": 20, "pro": 50},
        {"free": (200, "concurrent"), "pro": (500, "concurrent")}, "viewers beyond the cap are told to keep polling"),
    Cap("storage_mb", "SUPABASE_CAP_STORAGE_MB", "MB", "gauge", {"free": 600, "pro": 5_120},
        {"free": (1_024, "total"), "pro": (102_400, "total")}, "oldest eye frames are deleted from the bucket past 80 %"),
    Cap("upload_mb", "SUPABASE_CAP_UPLOAD_MB", "MB", "object", {"free": 5, "pro": 10},
        {"free": (50, "object"), "pro": (500 * 1024, "object")}),
    Cap("edge_calls_day", "SUPABASE_CAP_EDGE_CALLS_DAY", "invocations", "day", {"free": 5_000, "pro": 20_000},
        {"free": (500_000, "month"), "pro": (2_000_000, "month")}, "signed calls counted in the database by the inbox RPC"),
    Cap("db_mb", "SUPABASE_CAP_DB_MB", "MB", "gauge", {"free": 300, "pro": 2_048},
        {"free": (500, "total"), "pro": (8_192, "total")}, "pg_database_size through an RPC every 10 minutes; simulated rows shed past 80 %"),
    Cap("egress_mb_day", "SUPABASE_CAP_EGRESS_MB_DAY", "MB", "day", {"free": 500, "pro": 3_072},
        {"free": (5_120, "month"), "pro": (256_000, "month")}, "estimated from bytes served: signed URLs handed out and Realtime payloads"),
    Cap("egress_mb_month", "SUPABASE_CAP_EGRESS_MB_MONTH", "MB", "month", {"free": 4_000, "pro": 90_000},
        {"free": (5_120, "month"), "pro": (256_000, "month")}),
    Cap("transform_origins_month", "SUPABASE_CAP_TRANSFORM_ORIGINS_MONTH", "origin images", "month", {"free": 0, "pro": 80},
        {"free": None, "pro": (100, "month")}, "Pro only; Pillow thumbnails once the counter reaches the cap"),
)
CAP_BY_KEY = {cap.key: cap for cap in CAPS}
CEILING = 0.9  # an env override may not exceed 90 % of what the plan includes (per its own period)


def plan() -> str:
    value = re.split(r"\s+#", (os.getenv("SUPABASE_PLAN") or "").strip(), maxsplit=1)[0].strip().strip('"').strip("'").lower()
    return value if value in PLANS else "free"


def _env_int(name: str) -> int | None:
    raw = re.split(r"\s+#", (os.getenv(name) or "").strip(), maxsplit=1)[0].strip().strip('"').strip("'")
    if not raw or raw.startswith("#"):
        return None
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return None


def _ceiling(cap: Cap, plan_name: str) -> int | None:
    limit = cap.limits.get(plan_name)
    if limit is None:
        return 0  # not available on this plan
    amount, _period = limit
    if cap.period == "object":
        return amount
    return int(amount * CEILING)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Budget:
    """Caps and counters. Thread safe; persistent; never raises on the spend path."""

    def __init__(self, store, clock=utcnow):
        self.store = store
        self.clock = clock
        self.lock = threading.RLock()

    # ---- caps -------------------------------------------------------------------------------------------------

    @property
    def plan(self) -> str:
        return plan()

    def resolved(self) -> dict[str, dict]:
        plan_name = self.plan
        out = {}
        for cap in CAPS:
            default = cap.defaults[plan_name]
            value, source = default, "default"
            override = _env_int(cap.env)
            if override is not None:
                value, source = override, "env"
            ceiling = _ceiling(cap, plan_name)
            if ceiling is not None and value > ceiling:
                value, source = ceiling, "clamped"
            out[cap.key] = dict(value=value, source=source, default=default, ceiling=ceiling)
        return out

    def cap(self, key: str) -> int:
        return self.resolved()[key]["value"]

    # ---- counters ---------------------------------------------------------------------------------------------

    def _day(self) -> str:
        return self.clock().strftime("%Y-%m-%d")

    def _month(self) -> str:
        return self.clock().strftime("%Y-%m")

    def _key(self, name: str, period: str) -> str:
        if period == "day":
            return f"supa:budget:{name}:day:{self._day()}"
        if period == "month":
            return f"supa:budget:{name}:month:{self._month()}"
        return f"supa:budget:{name}"

    def _get(self, db, key: str) -> int:
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        try:
            return int(row["value"]) if row else 0
        except (TypeError, ValueError):
            return 0

    def _set(self, db, key: str, value: int) -> None:
        db.execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(int(value))))

    def counter(self, name: str, period: str) -> int:
        with self.store.connect() as db:
            return self._get(db, self._key(name, period))

    def _spend(self, name: str, amount: int, caps: list[tuple[str, int]], force: bool) -> bool:
        """Atomically add `amount` to the day and month counters of `name` when every (period, cap) allows it."""
        amount = max(0, int(amount))
        try:
            with self.lock, self.store.lock, self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = {period: self._get(db, self._key(name, period)) for period, _ in caps}
                if not force and any(current[period] + amount > limit for period, limit in caps):
                    return False
                for period, _ in caps:
                    self._set(db, self._key(name, period), current[period] + amount)
                return True
        except Exception:
            return False  # an unreadable counter refuses rather than overspends

    # ---- realtime ---------------------------------------------------------------------------------------------

    def spend_realtime(self, messages: int, force: bool = False) -> bool:
        """`messages` already includes fan-out (1 + subscribers for a broadcast). `force` records spend that already happened
        (a presence join the browser made), so the counter stays honest even past the cap."""
        caps = [("day", self.cap("realtime_msgs_day")), ("month", self.cap("realtime_msgs_month"))]
        return self._spend("realtime_msgs", messages, caps, force)

    def realtime_ok(self, messages: int = 1) -> bool:
        return (self.counter("realtime_msgs", "day") + messages <= self.cap("realtime_msgs_day")
                and self.counter("realtime_msgs", "month") + messages <= self.cap("realtime_msgs_month"))

    def realtime_fraction(self) -> float:
        """Share of the tighter realtime cap already spent (drives the HUD's adaptive coalescing)."""
        day_cap, month_cap = self.cap("realtime_msgs_day"), self.cap("realtime_msgs_month")
        fractions = [self.counter("realtime_msgs", "day") / day_cap if day_cap else 1.0,
                     self.counter("realtime_msgs", "month") / month_cap if month_cap else 1.0]
        return max(fractions)

    def viewers_ok(self, count: int) -> bool:
        return count <= self.cap("realtime_viewers")

    # ---- egress -----------------------------------------------------------------------------------------------

    def spend_egress(self, size_bytes: int, force: bool = False) -> bool:
        caps = [("day", self.cap("egress_mb_day") * MB), ("month", self.cap("egress_mb_month") * MB)]
        return self._spend("egress_bytes", size_bytes, caps, force)

    # ---- storage ----------------------------------------------------------------------------------------------

    def storage_bytes(self) -> int:
        return self.counter("storage_bytes", "gauge")

    def set_storage_bytes(self, value: int) -> None:
        with self.lock, self.store.lock, self.store.connect() as db:
            self._set(db, self._key("storage_bytes", "gauge"), max(0, int(value)))

    def add_storage(self, delta: int) -> None:
        with self.lock, self.store.lock, self.store.connect() as db:
            key = self._key("storage_bytes", "gauge")
            self._set(db, key, max(0, self._get(db, key) + int(delta)))

    def allow_upload(self, size_bytes: int) -> tuple[bool, str]:
        per_object = self.cap("upload_mb") * MB
        if size_bytes > per_object:
            return False, "upload_mb"
        if self.storage_bytes() + size_bytes > self.cap("storage_mb") * MB:
            return False, "storage_mb"
        return True, ""

    def storage_fraction(self) -> float:
        cap = self.cap("storage_mb") * MB
        return self.storage_bytes() / cap if cap else 1.0

    # ---- database ---------------------------------------------------------------------------------------------

    def set_db_bytes(self, value: int) -> None:
        with self.lock, self.store.lock, self.store.connect() as db:
            self._set(db, self._key("db_bytes", "gauge"), max(0, int(value)))
            db.execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       ("supa:budget:db_checked_at", self.clock().isoformat().replace("+00:00", "Z")))

    def db_bytes(self) -> int:
        return self.counter("db_bytes", "gauge")

    def db_state(self) -> str:
        """ok, shed (past 80 %: simulated sensor rows stay local) or full (at the cap: every row stays local)."""
        cap = self.cap("db_mb") * MB
        used = self.db_bytes()
        if cap <= 0 or used >= cap:
            return "full"
        return "shed" if used >= 0.8 * cap else "ok"

    # ---- edge function ----------------------------------------------------------------------------------------

    def set_edge_calls(self, day: str, calls: int) -> None:
        with self.lock, self.store.lock, self.store.connect() as db:
            self._set(db, f"supa:budget:edge_calls:day:{day}", max(0, int(calls)))

    def edge_ok(self) -> bool:
        return self.counter("edge_calls", "day") < self.cap("edge_calls_day")

    # ---- image transformations (Pro) ----------------------------------------------------------------------------

    def transforms_available(self) -> bool:
        return self.plan == "pro" and self.cap("transform_origins_month") > 0

    def allow_transform(self, object_key: str) -> bool:
        """Transformations bill per distinct origin image per month: an image already counted this month is free to reuse."""
        if not self.transforms_available():
            return False
        marker = f"supa:budget:transform_origin:{self._month()}:{object_key}"
        try:
            with self.lock, self.store.lock, self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM meta WHERE key=?", (marker,)).fetchone():
                    return True
                key = self._key("transform_origins", "month")
                used = self._get(db, key)
                if used + 1 > self.cap("transform_origins_month"):
                    return False
                self._set(db, key, used + 1)
                db.execute("INSERT INTO meta(key,value) VALUES (?,?)", (marker, "1"))
                return True
        except Exception:
            return False

    # ---- refusals -----------------------------------------------------------------------------------------------

    def refuse(self, cap_key: str, detail: str) -> None:
        """Record one event per cap per UTC day, plus the latest refusal for the usage report. Never raises."""
        try:
            at = self.clock().isoformat().replace("+00:00", "Z")
            self.store.meta(f"supa:budget:last_refusal:{cap_key}", json.dumps(dict(at=at, detail=detail[:300])))
            count_key = f"supa:budget:refusals:{cap_key}:day:{self._day()}"
            with self.lock, self.store.lock, self.store.connect() as db:
                self._set(db, count_key, self._get(db, count_key) + 1)
            if self.store.mark_once(f"supa:budget:refused:{cap_key}:{self._day()}", at):
                cap = CAP_BY_KEY.get(cap_key)
                title = f"Supabase {cap.key if cap else cap_key} cap reached; falling back to local"
                self.store.event(DEMO_SITE, "director", "supabase.budget", title, detail[:500])
        except Exception:
            pass

    def refusals_today(self, cap_key: str) -> int:
        with self.store.connect() as db:
            return self._get(db, f"supa:budget:refusals:{cap_key}:day:{self._day()}")

    # ---- report -------------------------------------------------------------------------------------------------

    def usage(self) -> dict:
        resolved = self.resolved()
        plan_name = self.plan
        used = {
            "realtime_msgs_day": self.counter("realtime_msgs", "day"),
            "realtime_msgs_month": self.counter("realtime_msgs", "month"),
            "realtime_viewers": int(self.store.meta("supa:budget:realtime_viewers") or 0),
            "storage_mb": round(self.storage_bytes() / MB, 3),
            "upload_mb": round(int(self.store.meta("supa:budget:largest_upload_bytes") or 0) / MB, 3),
            "edge_calls_day": self.counter("edge_calls", "day"),
            "db_mb": round(self.db_bytes() / MB, 3),
            "egress_mb_day": round(self.counter("egress_bytes", "day") / MB, 3),
            "egress_mb_month": round(self.counter("egress_bytes", "month") / MB, 3),
            "transform_origins_month": self.counter("transform_origins", "month"),
        }
        counters = []
        for cap in CAPS:
            entry = resolved[cap.key]
            limit = cap.limits.get(plan_name)
            free_limit = cap.limits.get("free")
            value = used[cap.key]
            last = self.store.meta(f"supa:budget:last_refusal:{cap.key}")
            counters.append(dict(
                key=cap.key, env=cap.env, unit=cap.unit, period=cap.period, used=value, cap=entry["value"], capSource=entry["source"],
                percentOfCap=round(100.0 * value / entry["value"], 2) if entry["value"] else None,
                planLimit=dict(amount=limit[0], period=limit[1]) if limit else None,
                freeLimit=dict(amount=free_limit[0], period=free_limit[1]) if free_limit else None,
                refusalsToday=self.refusals_today(cap.key), lastRefusal=json.loads(last) if last else None, note=cap.note or None))
        return dict(plan=plan_name, day=self._day(), month=self._month(), counters=counters,
                    dbCheckedAt=self.store.meta("supa:budget:db_checked_at"), dbState=self.db_state(),
                    realtimeFraction=round(self.realtime_fraction(), 4), transformsAvailable=self.transforms_available(),
                    counting="Realtime: 1 per broadcast sent + 1 per subscribed client (Supabase billing); presence joins 1 + N, leaves N.")

    def note_upload_size(self, size_bytes: int) -> None:
        try:
            if size_bytes > int(self.store.meta("supa:budget:largest_upload_bytes") or 0):
                self.store.meta("supa:budget:largest_upload_bytes", str(int(size_bytes)))
        except Exception:
            pass

    def note_viewers(self, count: int) -> None:
        try:
            self.store.meta("supa:budget:realtime_viewers", str(int(count)))
        except Exception:
            pass
