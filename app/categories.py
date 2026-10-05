"""
DXCC credit categories and the operating profile.

Category codes follow LoTW's Account Status "DXCC Award" column
(Mixed, CW, Phone, Digital, one per band). Bands and modes are credited
separately; band-and-mode combinations are never DXCC slots.

The Award Credit Matrix has 16 credit columns in this fixed order:
    Mix  Ph  CW  RT  SAT  160 80 40 30 20 17 15 12 10 6 2
RT is LoTW's label for Digital. Satellite is read and stored because it is
in the matrix, but it is not a tracked category and is never counted or
shown (decision D11). There is no 70 cm column in the matrix.
"""

from dataclasses import dataclass

MIXED, PHONE, CW, DIGITAL, SAT = "MIXED", "PHONE", "CW", "DIGITAL", "SAT"
BANDS = ("160M", "80M", "40M", "30M", "20M", "17M", "15M", "12M", "10M", "6M", "2M")
MODES = (CW, PHONE, DIGITAL)

# Matrix header label -> category code, in matrix column order.
MATRIX_COLUMNS = (
    ("Mix", MIXED), ("Ph", PHONE), ("CW", CW), ("RT", DIGITAL), ("SAT", SAT),
    ("160", "160M"), ("80", "80M"), ("40", "40M"), ("30", "30M"), ("20", "20M"),
    ("17", "17M"), ("15", "15M"), ("12", "12M"), ("10", "10M"), ("6", "6M"),
    ("2", "2M"),
)
MATRIX_CATEGORIES = tuple(code for _, code in MATRIX_COLUMNS)

# Categories the app tracks and reconciles: everything in the matrix except SAT.
TRACKED = (MIXED, CW, PHONE, DIGITAL) + BANDS

LABELS = {MIXED: "Mixed", PHONE: "Phone", CW: "CW", DIGITAL: "Digital", SAT: "Satellite",
          **{b: b.replace("M", " m") for b in BANDS}}

DEFAULT_BANDS = ("160M", "80M", "40M", "30M", "20M", "17M", "15M", "12M", "10M", "6M")


@dataclass(frozen=True)
class Profile:
    """The operating profile: which bands and modes count as 'needed'.

    Mixed is always tracked (it is what "new entity" means), so it is not
    part of the profile. View filters never change the profile.
    """
    bands: tuple = DEFAULT_BANDS
    modes: tuple = MODES

    def __post_init__(self):
        bad = [b for b in self.bands if b not in BANDS] + [m for m in self.modes if m not in MODES]
        if bad:
            raise ValueError(f"Unknown profile categories: {bad}")
        # Normalise to the canonical order so equal profiles compare equal.
        object.__setattr__(self, "bands", tuple(b for b in BANDS if b in self.bands))
        object.__setattr__(self, "modes", tuple(m for m in MODES if m in self.modes))

    @property
    def slot_categories(self):
        """Categories that make up band/mode slots for a credited entity."""
        return self.modes + self.bands

    @property
    def markable_categories(self):
        """Categories a pending mark may be set on: Mixed plus the profile
        (Dan, 2026-10-05: progress is tracked on 160-6 m only, not 2 m)."""
        return (MIXED,) + self.slot_categories


DEFAULT_PROFILE = Profile()
