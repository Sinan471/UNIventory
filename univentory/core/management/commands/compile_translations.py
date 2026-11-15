"""Compile .po catalogues to .mo without GNU gettext (FR-57 framework).

Django's compilemessages needs the gettext tools, which are often missing
on Windows lab machines. This pure-Python compiler handles the subset used
here (msgctxt, msgid, msgid_plural, msgstr[n], multi-line strings) so every
member can compile their module's Arabic strings the same way.
"""
import ast
import struct
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


def parse_po(text: str) -> dict:
    messages: dict = {}
    entry: dict = {}
    key = None
    fuzzy = False

    def flush():
        nonlocal entry, fuzzy
        if "msgid" in entry and not fuzzy:
            msgid = entry["msgid"]
            if "msgctxt" in entry:
                msgid = entry["msgctxt"] + "\x04" + msgid
            if "msgid_plural" in entry:
                msgid = msgid + "\x00" + entry["msgid_plural"]
                strs = [entry.get(f"msgstr[{i}]", "") for i in range(10) if f"msgstr[{i}]" in entry]
                value = "\x00".join(strs)
                if any(strs):
                    messages[msgid] = value
            elif entry.get("msgstr") or msgid == "":
                messages[msgid] = entry.get("msgstr", "")
        entry = {}
        fuzzy = False

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#,") and "fuzzy" in line:
            fuzzy = True
            continue
        if not line or line.startswith("#"):
            if not line and entry:
                flush()
            continue
        if line.startswith('"'):
            entry[key] += ast.literal_eval(line)
            continue
        token, _, rest = line.partition(" ")
        if token == "msgctxt" or (token == "msgid" and any(k.startswith("msgstr") for k in entry)):
            flush()
        key = token
        entry[key] = ast.literal_eval(rest)
    flush()
    return messages


def write_mo(messages: dict, path: Path) -> None:
    keys = sorted(messages)
    ids = b""
    strs = b""
    offsets = []
    for k in keys:
        kb, vb = k.encode("utf-8"), messages[k].encode("utf-8")
        offsets.append((len(ids), len(kb), len(strs), len(vb)))
        ids += kb + b"\x00"
        strs += vb + b"\x00"
    n = len(keys)
    key_start = 7 * 4 + 16 * n
    value_start = key_start + len(ids)
    table = []
    for o_id, l_id, o_str, l_str in offsets:
        table.append((l_id, key_start + o_id))
    vtable = []
    for o_id, l_id, o_str, l_str in offsets:
        vtable.append((l_str, value_start + o_str))
    output = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    for length, offset in table:
        output += struct.pack("ii", length, offset)
    for length, offset in vtable:
        output += struct.pack("ii", length, offset)
    output += ids + strs
    path.write_bytes(output)


class Command(BaseCommand):
    help = "Compile every locale/*/LC_MESSAGES/*.po file (project and module locale folders) to .mo."

    def handle(self, *args, **options):
        roots = [Path(p) for p in settings.LOCALE_PATHS]
        roots += [Path(settings.BASE_DIR) / app / "locale" for app in settings.INSTALLED_APPS if "." not in app]
        count = 0
        for root in roots:
            for po in root.glob("*/LC_MESSAGES/*.po"):
                messages = parse_po(po.read_text(encoding="utf-8"))
                write_mo(messages, po.with_suffix(".mo"))
                count += 1
                self.stdout.write(f"compiled {po} ({len(messages) - 1} messages)")
        self.stdout.write(self.style.SUCCESS(f"{count} catalogue(s) compiled."))
