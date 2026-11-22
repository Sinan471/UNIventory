"""Spreadsheet-safe CSV cells (FR-49, NFR-11). Owner: Jesher (shared helper).

A cell that starts with = + - @ or a tab/carriage return can be executed as
a formula by spreadsheet software. Prefix it with an apostrophe so it is
shown as text. Every CSV export in the application uses this helper.
"""
import csv

DANGEROUS = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(DANGEROUS) or text.lstrip().startswith(("=", "+", "@")):
        return "'" + text
    return text


def safe_row(values) -> list[str]:
    return [safe_cell(v) for v in values]


def writer(stream):
    return csv.writer(stream, quoting=csv.QUOTE_MINIMAL)
