"""One date build identity for future SIFAS client packages (standard library only)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import re
from zoneinfo import ZoneInfo

GAME_VERSION = "3.12.0"
ANDROID_VERSION_PREFIX = GAME_VERSION + "-fovmod."
BUILD_KEY = "SIFASBuildVersion"
ANDROID_MAX_VERSION_CODE = 2_100_000_000
_CANONICAL = re.compile(r"([0-9]{4})\.([0-9]{2})\.([0-9]{2})\.([1-9][0-9]?)", re.ASCII)


@dataclass(frozen=True, order=True)
class BuildVersion:
    day: date
    sequence: int

    def __post_init__(self) -> None:
        if type(self.day) is not date or not 2000 <= self.day.year <= 2099:
            raise ValueError("Build date must be a calendar date in 2000..2099")
        if type(self.sequence) is not int or not 1 <= self.sequence <= 99:
            raise ValueError("Daily build sequence must be an integer in 1..99")
        if self.android_version_code > ANDROID_MAX_VERSION_CODE:
            raise ValueError("Build exceeds Android's versionCode limit")

    @classmethod
    def parse(cls, value: str) -> BuildVersion:
        match = _CANONICAL.fullmatch(value) if isinstance(value, str) else None
        if not match:
            raise ValueError("Build must be YYYY.MM.DD.N; N is 1..99 without leading zero")
        year, month, day, sequence = map(int, match.groups())
        return cls(date(year, month, day), sequence)

    @classmethod
    def for_seoul_date(cls, sequence: int, now: datetime | None = None) -> BuildVersion:
        instant = now if now is not None else datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("A timezone-aware instant is required")
        return cls(instant.astimezone(ZoneInfo("Asia/Seoul")).date(), sequence)

    @property
    def canonical(self) -> str:
        return f"{self.day:%Y.%m.%d}.{self.sequence}"

    @property
    def android_version_code(self) -> int:
        return (self.day.year * 10_000 + self.day.month * 100 + self.day.day) * 100 + self.sequence

    @property
    def android_version_name(self) -> str:
        # Preserve the upstream game identity; only the mod build suffix changes.
        return ANDROID_VERSION_PREFIX + self.canonical

    @property
    def apple_build_version(self) -> str:
        # Apple accepts 1..3 components; archived documented limits are 4/2/2 digits.
        year_month = (self.day.year % 100) * 100 + self.day.month
        return f"{year_month}.{self.day.day}.{self.sequence}"


def validate_android_source_name(value: str) -> None:
    if not isinstance(value, str) or not value.startswith(ANDROID_VERSION_PREFIX):
        raise ValueError(f"Unexpected game version; expected {ANDROID_VERSION_PREFIX}<build>")
    suffix = value[len(ANDROID_VERSION_PREFIX):]
    if re.fullmatch(r"b[1-9][0-9]*", suffix, re.ASCII):
        return
    BuildVersion.parse(suffix)


def android_build_label(version_name: str) -> str:
    """The FOV UI displays the canonical date read from actual package metadata."""
    validate_android_source_name(version_name)
    return BuildVersion.parse(version_name[len(ANDROID_VERSION_PREFIX):]).canonical


def output_filename(platform: str, region: str, build: BuildVersion) -> str:
    if platform == "android" and region in ("GL", "JP"):
        return f"LLAS_{region}_FOVMOD_{build.canonical}.apk"
    if platform == "ios" and region in ("GL", "JP", "GL_Local"):
        return f"SIFAS_{region}_{GAME_VERSION}_PlayCover_{build.canonical}_candidate.ipa"
    raise ValueError("Unsupported platform/region combination")


def metadata_plan(build: BuildVersion) -> dict:
    return {
        "build": build.canonical,
        "calendar_timezone": "Asia/Seoul",
        "daily_sequence": build.sequence,
        "android": {"versionName": build.android_version_name, "versionCode": build.android_version_code},
        "ios": {"CFBundleShortVersionString": GAME_VERSION,
                "CFBundleVersion": build.apple_build_version, BUILD_KEY: build.canonical},
        "filenames": {
            platform: {region: output_filename(platform, region, build) for region in regions}
            for platform, regions in (("android", ("GL", "JP")), ("ios", ("GL", "JP", "GL_Local")))
        },
    }
