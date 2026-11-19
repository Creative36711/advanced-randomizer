#!/usr/bin/env python3
"""Разбор и обратная сборка SAGE .big — проверка обратимости формата.

Зачем: движок OpenBFME проверяет каждый архив по MD5 из эталона и не даёт
отказаться от проверки. Если распаковать .big и собрать заново даёт тот же
MD5 — пересборка законна, и потерянные архивы можно восстановить.

СВЕРХНАЙДЕННОЕ О ФОРМАТЕ (это не то, что описано в распространённых
разборах; всё проверено на настоящих архивах RotWK 2.01):

    [0..16)     заголовок: FourCC(4) Size(u32 LE) NumEntries(u32 BE) OffsetFirst(u32 BE)
    [16..)      список записей: offset(u32 BE) size(u32 BE) name(CString)
    [..start)   ПРОМЕЖУТОК: у libraries.big 8 нулей, у ambientstreams.big
                b'L219\\0\\0\\0\\0', у data1.big b'L253\\x00'. Это подпись
                сборщика, которая пишется в РАЗНЫХ местах. Сохраняется как есть.
    [start..)   данные записей подряд

    • OffsetFirst указывает на начало ДАННЫХ, а не списка записей.
    • OffsetFirst может ВРАТЬ: у data1.big в заголовке 750, данные с 751.
      Поэтому начало данных берётся из первой записи.
    • Бывают ДУБЛИКАТЫ имён (albertusmt.otf дважды, omnialtstd.ttf дважды) —
      движок требует «a name stored twice must be stored twice with the same bytes».
    • Бывает ХВОСТОВОЙ padding после последней записи.

Проверено байт-в-байт на всех 18 архивах RotWK 2.01: data1, data2, ini,
libraries, lotrsec, shaders, window, ambientstreams, terrain, audio,
music, bases, textures0/1/4, _patch201, _patch201ini, _patch201maps.

Запуск:
  python3 tools/big_roundtrip.py <файл.big>                    # проверить обратимость
  python3 tools/big_roundtrip.py <файл.big> --dump DIR         # распаковать
  python3 tools/big_roundtrip.py <файл.big> --rebuild OUT.big  # собрать заново
  python3 tools/big_roundtrip.py <файл.big> --list             # список записей

Код возврата 0 — байт-в-байт совпало, 1 — нет.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from dataclasses import dataclass, field


@dataclass
class Entry:
    offset: int
    size: int
    name: str


@dataclass
class BigFile:
    fourcc: bytes
    size: int            # размер из заголовка (может отличаться от файла)
    num_entries: int
    first_entry_offset: int   # OffsetFirst из заголовка (может «врать»)
    entries: list[Entry]
    raw: bytes
    gap: bytes = b""     # байты между списком записей и началом данных
    tail: bytes = b""    # байты после последней записи
    data_start: int = 0  # фактическое начало данных (из первой записи)

    def data(self, e: Entry) -> bytes:
        return self.raw[e.offset:e.offset + e.size]


def parse(raw: bytes) -> BigFile:
    if len(raw) < 16:
        raise ValueError(f"слишком короткий файл: {len(raw)} байт")
    fourcc = raw[0:4]
    if fourcc not in (b"BIGF", b"BIG4"):
        raise ValueError(f"не BIG: сигнатура {fourcc!r}")
    size = struct.unpack_from("<I", raw, 4)[0]
    num = struct.unpack_from(">I", raw, 8)[0]
    first = struct.unpack_from(">I", raw, 12)[0]

    entries: list[Entry] = []
    pos = 16
    for _ in range(num):
        off = struct.unpack_from(">I", raw, pos)[0]
        sz = struct.unpack_from(">I", raw, pos + 4)[0]
        end = raw.index(b"\x00", pos + 8)
        name = raw[pos + 8:end].decode("latin-1")
        entries.append(Entry(off, sz, name))
        pos = end + 1
    # OffsetFirst может быть МЕНЬШЕ конца списка (data1.big: в заголовке 750,
    # данные с 751). Поэтому начало данных берём из записей, а OffsetFirst
    # только сохраняем и пишем обратно как есть.

    actual_start = min((e.offset for e in entries), default=first)
    end_of_data = max((e.offset + e.size for e in entries), default=first)
    return BigFile(fourcc, size, num, first, entries, raw,
                   gap=raw[pos:actual_start], tail=raw[end_of_data:],
                   data_start=actual_start)


def build(f: BigFile, payloads: list[bytes]) -> bytes:
    """Собрать архив в порядке записей исходника."""
    entries_len = sum(8 + len(e.name.encode("latin-1")) + 1 for e in f.entries)
    minimum = 16 + entries_len
    data_start = max(f.data_start or f.first_entry_offset, minimum)

    offsets, cur = [], data_start
    for p in payloads:
        offsets.append(cur)
        cur += len(p)
    total = cur + len(f.tail)

    out = bytearray()
    out += f.fourcc
    out += struct.pack("<I", total)
    out += struct.pack(">I", len(f.entries))
    out += struct.pack(">I", f.first_entry_offset)   # как в исходнике
    for e, off, p in zip(f.entries, offsets, payloads):
        out += struct.pack(">I", off)
        out += struct.pack(">I", len(p))
        out += e.name.encode("latin-1") + b"\x00"
    out += f.gap
    out += b"\x00" * max(0, data_start - len(out))
    for p in payloads:
        out += p
    out += f.tail
    return bytes(out)


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="проверка обратимости SAGE .big")
    ap.add_argument("big", help="путь к .big")
    ap.add_argument("--dump", help="куда распаковать содержимое")
    ap.add_argument("--rebuild", help="куда записать пересобранный архив")
    ap.add_argument("--list", action="store_true", help="только список записей")
    args = ap.parse_args(argv)

    raw = open(args.big, "rb").read()
    f = parse(raw)

    if args.list:
        print(f"{f.fourcc.decode('latin-1')}  записей: {f.num_entries}  файл: {len(raw)} б")
        for e in f.entries:
            print(f"  {e.offset:>8} {e.size:>8}  {e.name}")
        return 0

    print(f"файл:      {args.big}")
    print(f"сигнатура: {f.fourcc.decode('latin-1')}")
    print(f"размер:    {f.size} (заголовок), {len(raw)} (диск)")
    print(f"записей:   {f.num_entries}   начало данных: {f.data_start}   "
          f"промежуток: {len(f.gap)} б   хвост: {len(f.tail)} б")
    print(f"MD5 исход: {md5(raw)}")

    payloads = [f.data(e) for e in f.entries]
    rebuilt = build(f, payloads)
    same = md5(rebuilt) == md5(raw)

    print(f"MD5 сборка: {md5(rebuilt)}")
    print("ИТОГ:", "БАЙТ-В-БАЙТ СОВПАЛО" if same else "НЕ СОВПАЛО")
    if not same:
        n = min(len(raw), len(rebuilt))
        pos = next((i for i in range(n) if raw[i] != rebuilt[i]), n)
        print(f"первое расхождение на байте {pos} из {n}")
        print(f"  исход:  {raw[max(0,pos-8):pos+8].hex(' ')}")
        print(f"  сборка: {rebuilt[max(0,pos-8):pos+8].hex(' ')}")

    if args.dump:
        import os
        for e, p in zip(f.entries, payloads):
            dst = os.path.join(args.dump, e.name.replace("\\", "/"))
            os.makedirs(os.path.dirname(dst) or args.dump, exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(p)
        print(f"распаковано в {args.dump}")

    if args.rebuild:
        with open(args.rebuild, "wb") as fh:
            fh.write(rebuilt)
        print(f"пересобрано в {args.rebuild}")

    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
