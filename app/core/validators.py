"""Pure field normalizers and validators. Reused by Pydantic schemas."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from email_validator import EmailNotValidError, validate_email

from app.config import get_settings

NAME_RE = re.compile(r"^[^\W\d_]+([ '\-][^\W\d_]+)*$", re.UNICODE)
PHONE_RE = re.compile(r"^[2-9][0-9]{2}[2-9][0-9]{6}$")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
MEMBER_ID_RE = re.compile(r"^[A-Z0-9]{1,50}$")

SEX_ALIASES: dict[str, str] = {
    "male": "Male",
    "m": "Male",
    "female": "Female",
    "f": "Female",
    "other": "Other",
    "decline to answer": "Decline to Answer",
    "decline": "Decline to Answer",
    "prefer not to say": "Decline to Answer",
    "prefer not to answer": "Decline to Answer",
}

US_STATES: dict[str, str] = {
    "AL": "AL",
    "ALABAMA": "AL",
    "AK": "AK",
    "ALASKA": "AK",
    "AZ": "AZ",
    "ARIZONA": "AZ",
    "AR": "AR",
    "ARKANSAS": "AR",
    "CA": "CA",
    "CALIFORNIA": "CA",
    "CO": "CO",
    "COLORADO": "CO",
    "CT": "CT",
    "CONNECTICUT": "CT",
    "DE": "DE",
    "DELAWARE": "DE",
    "FL": "FL",
    "FLORIDA": "FL",
    "GA": "GA",
    "GEORGIA": "GA",
    "HI": "HI",
    "HAWAII": "HI",
    "ID": "ID",
    "IDAHO": "ID",
    "IL": "IL",
    "ILLINOIS": "IL",
    "IN": "IN",
    "INDIANA": "IN",
    "IA": "IA",
    "IOWA": "IA",
    "KS": "KS",
    "KANSAS": "KS",
    "KY": "KY",
    "KENTUCKY": "KY",
    "LA": "LA",
    "LOUISIANA": "LA",
    "ME": "ME",
    "MAINE": "ME",
    "MD": "MD",
    "MARYLAND": "MD",
    "MA": "MA",
    "MASSACHUSETTS": "MA",
    "MI": "MI",
    "MICHIGAN": "MI",
    "MN": "MN",
    "MINNESOTA": "MN",
    "MS": "MS",
    "MISSISSIPPI": "MS",
    "MO": "MO",
    "MISSOURI": "MO",
    "MT": "MT",
    "MONTANA": "MT",
    "NE": "NE",
    "NEBRASKA": "NE",
    "NV": "NV",
    "NEVADA": "NV",
    "NH": "NH",
    "NEW HAMPSHIRE": "NH",
    "NJ": "NJ",
    "NEW JERSEY": "NJ",
    "NM": "NM",
    "NEW MEXICO": "NM",
    "NY": "NY",
    "NEW YORK": "NY",
    "NC": "NC",
    "NORTH CAROLINA": "NC",
    "ND": "ND",
    "NORTH DAKOTA": "ND",
    "OH": "OH",
    "OHIO": "OH",
    "OK": "OK",
    "OKLAHOMA": "OK",
    "OR": "OR",
    "OREGON": "OR",
    "PA": "PA",
    "PENNSYLVANIA": "PA",
    "RI": "RI",
    "RHODE ISLAND": "RI",
    "SC": "SC",
    "SOUTH CAROLINA": "SC",
    "SD": "SD",
    "SOUTH DAKOTA": "SD",
    "TN": "TN",
    "TENNESSEE": "TN",
    "TX": "TX",
    "TEXAS": "TX",
    "UT": "UT",
    "UTAH": "UT",
    "VT": "VT",
    "VERMONT": "VT",
    "VA": "VA",
    "VIRGINIA": "VA",
    "WA": "WA",
    "WASHINGTON": "WA",
    "WV": "WV",
    "WEST VIRGINIA": "WV",
    "WI": "WI",
    "WISCONSIN": "WI",
    "WY": "WY",
    "WYOMING": "WY",
    "DC": "DC",
    "DISTRICT OF COLUMBIA": "DC",
    "WASHINGTON DC": "DC",
    "WASHINGTON D.C.": "DC",
    "PR": "PR",
    "PUERTO RICO": "PR",
    "GU": "GU",
    "GUAM": "GU",
    "VI": "VI",
    "VIRGIN ISLANDS": "VI",
    "U.S. VIRGIN ISLANDS": "VI",
    "US VIRGIN ISLANDS": "VI",
    "AS": "AS",
    "AMERICAN SAMOA": "AS",
    "MP": "MP",
    "NORTHERN MARIANA ISLANDS": "MP",
}

_MIN_DOB = date(1900, 1, 1)


def today_in_clinic_tz() -> date:
    """Calendar date in the clinic timezone (used for future-DOB checks)."""
    timezone_name = get_settings().clinic_timezone
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # Windows needs the tzdata package for IANA names like America/New_York.
        zone = timezone.utc
    return datetime.now(zone).date()


def collapse_spaces(value: str) -> str:
    """Trim and collapse internal whitespace. Rejects control characters."""
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError("Must not contain control characters")
    return " ".join(value.split())


def normalize_name(value: object, *, field: str = "name", max_length: int = 50) -> str:
    """Trim/collapse spaces; keep original letter case (McDonald, O'Neil)."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = collapse_spaces(value)
    if not cleaned or len(cleaned) > max_length:
        raise ValueError(f"{field} must be 1-{max_length} characters")
    if not NAME_RE.fullmatch(cleaned):
        raise ValueError(
            f"{field} may only contain letters with single spaces, hyphens, or apostrophes"
        )
    return cleaned


def normalize_dob(value: object, *, today: date | None = None) -> date:
    """Accept MM/DD/YYYY or YYYY-MM-DD. Reject future and pre-1900 dates."""
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        text = collapse_spaces(value)
        parsed = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("Date of birth must be MM/DD/YYYY or YYYY-MM-DD")
    else:
        raise ValueError("Date of birth must be MM/DD/YYYY or YYYY-MM-DD")

    cutoff = today or today_in_clinic_tz()
    if parsed < _MIN_DOB:
        raise ValueError("Date of birth cannot be before 01/01/1900")
    if parsed > cutoff:
        raise ValueError("Date of birth cannot be in the future")
    return parsed


def normalize_sex(value: object) -> str:
    """Map common spoken/abbreviated values to the sex_type enum labels."""
    if not isinstance(value, str):
        raise ValueError("Sex must be Male, Female, Other, or Decline to Answer")
    key = collapse_spaces(value).lower()
    mapped = SEX_ALIASES.get(key)
    if mapped is None:
        raise ValueError("Sex must be Male, Female, Other, or Decline to Answer")
    return mapped


def normalize_phone(value: object, *, field: str = "phone_number") -> str:
    """Strip non-digits, drop a leading country code 1, require NANP 10 digits."""
    if not isinstance(value, str) and not isinstance(value, int):
        raise ValueError(f"{field} must be a 10-digit U.S. phone number")
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if not PHONE_RE.fullmatch(digits):
        raise ValueError(f"{field} must be a valid 10-digit U.S. number with area code")
    return digits


def normalize_email(value: object) -> str | None:
    """Trim, lowercase, and validate. Empty becomes null."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("email must be a string")
    cleaned = collapse_spaces(value).lower()
    if not cleaned:
        return None
    try:
        result = validate_email(cleaned, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError("email must be a valid email address") from exc
    return result.normalized


def normalize_address_line_1(value: object) -> str:
    """Required street address, 1-200 characters."""
    if not isinstance(value, str):
        raise ValueError("address_line_1 must be a string")
    cleaned = collapse_spaces(value)
    if not cleaned or len(cleaned) > 200:
        raise ValueError("Street address must be 1-200 characters")
    return cleaned


def normalize_address_line_2(value: object) -> str | None:
    """Optional apt/suite. Empty becomes null."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("address_line_2 must be a string")
    cleaned = collapse_spaces(value)
    if not cleaned:
        return None
    if len(cleaned) > 100:
        raise ValueError("address_line_2 must be at most 100 characters")
    return cleaned


def normalize_city(value: object) -> str:
    """Required city, 1-100 characters."""
    if not isinstance(value, str):
        raise ValueError("city must be a string")
    cleaned = collapse_spaces(value)
    if not cleaned or len(cleaned) > 100:
        raise ValueError("City must be 1-100 characters")
    return cleaned


def normalize_state(value: object) -> str:
    """Uppercase 2-letter code, or a full U.S. state/territory name."""
    if not isinstance(value, str):
        raise ValueError("State must be a U.S. state or territory")
    key = collapse_spaces(value).upper().replace(".", "")
    # "WASHINGTON D C" after removing dots from "Washington D.C."
    key = " ".join(key.split())
    mapped = US_STATES.get(key)
    if mapped is None:
        raise ValueError("State must be a U.S. state, DC, or territory")
    return mapped


def normalize_zip(value: object) -> str:
    """5-digit ZIP or ZIP+4. Inserts a dash when given 9 digits."""
    if not isinstance(value, str) and not isinstance(value, int):
        raise ValueError("ZIP must be 5 digits or ZIP+4")
    cleaned = collapse_spaces(str(value))
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) == 9:
        cleaned = f"{digits[:5]}-{digits[5:]}"
    elif len(digits) == 5:
        cleaned = digits
    if not ZIP_RE.fullmatch(cleaned):
        raise ValueError("ZIP must be 5 digits or ZIP+4")
    return cleaned


def normalize_insurance_provider(value: object) -> str | None:
    """Optional insurer name. Empty becomes null."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("insurance_provider must be a string")
    cleaned = collapse_spaces(value)
    if not cleaned:
        return None
    if len(cleaned) > 100:
        raise ValueError("insurance_provider must be at most 100 characters")
    return cleaned


def normalize_member_id(value: object) -> str | None:
    """Uppercase alphanumeric member ID. Empty becomes null."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("insurance_member_id must be a string")
    cleaned = collapse_spaces(value).upper().replace(" ", "").replace("-", "")
    if not cleaned:
        return None
    if not MEMBER_ID_RE.fullmatch(cleaned):
        raise ValueError("insurance_member_id must be 1-50 letters or numbers")
    return cleaned


def normalize_language(value: object) -> str:
    """Title-case language. Empty becomes English."""
    if value is None:
        return "English"
    if not isinstance(value, str):
        raise ValueError("preferred_language must be a string")
    cleaned = collapse_spaces(value).title()
    if not cleaned:
        return "English"
    if len(cleaned) > 50:
        raise ValueError("preferred_language must be at most 50 characters")
    return cleaned


def normalize_emergency_name(value: object) -> str | None:
    """Optional emergency-contact name. Same character rules as patient names."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("emergency_contact_name must be a string")
    cleaned = collapse_spaces(value)
    if not cleaned:
        return None
    return normalize_name(cleaned, field="emergency_contact_name", max_length=100)
