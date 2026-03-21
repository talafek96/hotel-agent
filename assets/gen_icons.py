# /// script
# requires-python = ">=3.10"
# dependencies = ["Pillow"]
# ///
"""Generate icon.ico and icon.icns from icon.png with all standard sizes.

Uses multi-step downscaling + unsharp mask to keep small sizes legible.
"""

import io
import struct
from pathlib import Path

from PIL import Image, ImageFilter

ASSETS = Path(__file__).parent
SRC = ASSETS / "icon.png"


def _downscale(src: Image.Image, target: int) -> Image.Image:
    """Downscale with multi-step resizing and sharpening for small targets.

    For sizes <= 64px we step down in halves first (avoiding harsh artefacts
    from a single large→tiny jump) and then sharpen so detail survives.
    """
    img = src.copy()

    # Step down in halves until we're within 2× of the target
    while img.width > target * 2:
        half = img.width // 2
        img = img.resize((half, half), Image.LANCZOS)

    # Final resize to exact target
    img = img.resize((target, target), Image.LANCZOS)

    # Sharpen small sizes so features remain visible
    if target <= 64:
        # radius/percent/threshold — more aggressive for smaller icons
        if target <= 32:
            img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=180, threshold=0))
        else:
            img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=1))

    return img


# ─── ICO (Windows) ───────────────────────────────────────────────────────────
ICO_SIZES = [256, 128, 64, 48, 32, 16]


def make_ico() -> None:
    src = Image.open(SRC).convert("RGBA")
    frames = [_downscale(src, s) for s in ICO_SIZES]
    dst = ASSETS / "icon.ico"
    frames[0].save(
        dst,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[1:],
    )
    print(f"  icon.ico  -> {dst.stat().st_size:,} bytes  (sizes: {ICO_SIZES})")


# ─── ICNS (macOS) ────────────────────────────────────────────────────────────
# ICNS icon types and their pixel sizes (PNG-capable types)
ICNS_TYPES = [
    (b"ic10", 1024),  # 512@2x
    (b"ic09",  512),  # 512
    (b"ic14",  512),  # 256@2x
    (b"ic08",  256),  # 256
    (b"ic13",  256),  # 128@2x
    (b"ic07",  128),  # 128
    (b"ic12",   64),  # 32@2x
    (b"ic11",   32),  # 16@2x
    (b"icp6",   64),  # 48 → 64 (closest standard)
    (b"icp5",   32),  # 32
    (b"icp4",   16),  # 16
]


def make_icns() -> None:
    """Build ICNS by hand-assembling the container format.

    Each entry: 4-byte type + 4-byte length (incl. header) + PNG payload.
    Outer wrapper: 'icns' + 4-byte total length + entries.
    """
    src = Image.open(SRC).convert("RGBA")
    entries = bytearray()
    seen_sizes: set[int] = set()

    for ostype, px in ICNS_TYPES:
        resized = _downscale(src, px) if px < src.width else src
        buf = io.BytesIO()
        resized.save(buf, format="PNG", optimize=True)
        png_data = buf.getvalue()
        entry_len = 8 + len(png_data)
        entries += ostype
        entries += struct.pack(">I", entry_len)
        entries += png_data
        seen_sizes.add(px)

    total_len = 8 + len(entries)
    icns_data = b"icns" + struct.pack(">I", total_len) + bytes(entries)

    dst = ASSETS / "icon.icns"
    dst.write_bytes(icns_data)
    print(f"  icon.icns -> {dst.stat().st_size:,} bytes  (sizes: {sorted(seen_sizes)})")


if __name__ == "__main__":
    print("Generating icons from", SRC)
    make_ico()
    make_icns()
    print("Done.")
