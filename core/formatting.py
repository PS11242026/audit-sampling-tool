"""Formatting helpers shared by the UI and report generators."""


def inr(value, decimals: int = 0) -> str:
    """Indian-grouped currency string: 12345678 -> 'Rs 1,23,45,678'."""
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    neg = v < 0
    s = f"{abs(v):.{decimals}f}"
    if "." in s:
        whole, frac = s.split(".")
        frac = "." + frac
    else:
        whole, frac = s, ""
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}Rs {whole}{frac}"


def short_hash(h: str, n: int = 12) -> str:
    return (h or "")[:n]


# Excel custom number format with Indian digit grouping.
INR_XLSX_FMT = (r"[>=100000]#\,##\,##\,##\,##0;"
                r"[<=-100000]-#\,##\,##\,##\,##0;#,##0")
