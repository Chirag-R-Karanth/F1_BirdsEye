from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class Driver:
    number: int
    code: str
    name: str
    team: str
    color: str

@dataclass(slots=True)
class CarState:
    number: int
    code: str = ""
    name: str = ""
    team: str = ""
    color: str = "white"
    pos: int | None = None
    gap: float | str | None = None
    interval: float | None = None
    tyre: str | None = None
    age: int | None = None
    x: float | None = None
    y: float | None = None
    speed: float | None = None
    gear: int | None = None
    throttle: float | None = None
    brake: float | None = None
    drs: int | None = None
    rpm: int | None = None
    lap: int | None = None
    last_lap: float | None = None

@dataclass(slots=True)
class Snapshot:
    lap: int | None
    total_laps: int | None
    elapsed: float
    status: str | None
    cars: list[CarState] = field(default_factory=list)

@dataclass(slots=True)
class SessionInfo:
    session_key: int
    meeting_key: int
    year: int
    circuit: str
    meeting_name: str
    session_name: str
    session_type: str
    start: float
    end: float
    total_laps: int | None = None


def parse_float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None
