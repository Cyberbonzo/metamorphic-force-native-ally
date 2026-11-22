"""Extract the Metamorphic Force (ver AAA, Asia) chips from the user's arcade ZIPs.

Accepts any combination of: a merged/split metamrph.zip, metamrpha.zip, or an
outer ZIP that wraps one of them. Chips are matched by size and CRC.
"""
import argparse
import hashlib
import io
import json
import tempfile
from pathlib import Path
from zipfile import ZipFile

CHIPS = {
    "224aaa01.15h": (0x040000, 0x12515518), "224aaa02.15f": (0x040000, 0x04ED41DF),
    "224a03": (0x080000, 0xA5BEDB01), "224a04": (0x080000, 0xADA53BA4),
    "224a05": (0x040000, 0x4B4C985C),
    "224a09": (0x100000, 0x1931AFCE), "224a08": (0x100000, 0xDC94D53A),
    "224a10": (0x200000, 0x161287F0), "224a11": (0x200000, 0xDF5960E1),
    "224a12": (0x200000, 0xCA72A4B3), "224a13": (0x200000, 0x86B58FEB),
    "224a14": (0x040000, 0x3C79B404),
    "224a06": (0x200000, 0x972F6ABE), "224a07": (0x100000, 0x61B2F97A),
    "metamrpha.nv": (0x000080, 0x6D34A4F2),
}
WANTED = {chip_id: name for name, chip_id in CHIPS.items()}


def collect(archive, found, depth=0):
    for info in archive.infolist():
        chip_id = (info.file_size, info.CRC)
        if chip_id in WANTED and WANTED[chip_id] not in found:
            found[WANTED[chip_id]] = archive.read(info)
        elif info.filename.lower().endswith(".zip") and depth == 0 and info.file_size < 64 << 20:
            with ZipFile(io.BytesIO(archive.read(info))) as inner:
                collect(inner, found, depth + 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zips", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    found = {}
    for path in args.zips:
        with ZipFile(path) as archive:
            collect(archive, found)
    missing = sorted(set(CHIPS) - set(found))
    if missing:
        raise SystemExit("Missing Metamorphic Force (ver AAA) chips: " + ", ".join(missing))
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in found.items()}
    if out.exists():
        for name, digest in hashes.items():
            if hashlib.sha256((out / name).read_bytes()).hexdigest() != digest:
                raise SystemExit(f"Existing file differs: {out / name}")
    else:
        with tempfile.TemporaryDirectory(dir=out.parent) as scratch:
            stage = Path(scratch) / "chips"
            stage.mkdir()
            for name, data in found.items():
                (stage / name).write_bytes(data)
            stage.rename(out)
    print(json.dumps(dict(sorted(hashes.items())), indent=2))


if __name__ == "__main__":
    main()
