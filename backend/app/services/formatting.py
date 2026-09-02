"""Indian currency formatting.

Money is stored in paise. Display uses the Indian grouping system, where digits
are grouped in a final triple and then in pairs: 48250000 paise becomes
"₹4,82,500" — not the Western "₹482,500".
"""

from __future__ import annotations

RUPEE = "₹"


def group_indian(number: int) -> str:
    """Group an integer using the Indian lakh/crore convention.

    >>> group_indian(482500)
    '4,82,500'
    >>> group_indian(2999)
    '2,999'
    """
    negative = number < 0
    digits = str(abs(number))

    if len(digits) <= 3:
        grouped = digits
    else:
        last_three = digits[-3:]
        rest = digits[:-3]
        # Everything before the final triple is grouped in pairs, right to left.
        pairs = []
        while len(rest) > 2:
            pairs.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            pairs.insert(0, rest)
        grouped = ",".join(pairs) + "," + last_three

    return f"-{grouped}" if negative else grouped


def format_inr(paise: int, *, show_paise: bool = False) -> str:
    """Format an amount in paise as an INR string.

    >>> format_inr(299900)
    '₹2,999'
    >>> format_inr(299950, show_paise=True)
    '₹2,999.50'
    """
    negative = paise < 0
    abs_paise = abs(paise)
    rupees, remainder = divmod(abs_paise, 100)

    if show_paise or remainder:
        body = f"{group_indian(rupees)}.{remainder:02d}"
    else:
        body = group_indian(rupees)

    return f"-{RUPEE}{body}" if negative else f"{RUPEE}{body}"


def to_paise(rupees: float | int) -> int:
    """Convert a rupee amount to integer paise, rounding to the nearest paisa."""
    return int(round(float(rupees) * 100))


def to_rupees(paise: int) -> float:
    """Convert paise to a float rupee amount. Display only — never for maths."""
    return paise / 100
