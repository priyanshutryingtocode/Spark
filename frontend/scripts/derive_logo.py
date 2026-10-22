"""Derive the logo and icon assets from `public/logo.png`, which is never written
to -- so the outputs cannot drift apart.

The PNG is effectively opaque (alpha 254-255) with 67% pure white, which is a
19.3:1 white block on the dark topbar, so the white is un-premultiplied away. Its
black S is invisible on #0c0e10, so it is recoloured to --text (#eef1e9); --ink
keeps the original black one flag away.

The fit is least-squares against each of the two flat foregrounds rather than a
white-key, because the candidates disagree sharply: a flat black pixel is alpha
1.0 as black and 2.96 as blue. Residuals are 0 for the right line, 133-209 for
the wrong one.

Icons keep only the largest connected component. The three detached streaks are
separate components, and a 1353x1497 mark at 16px turns hairline to grey mush.
"""

from __future__ import annotations

import argparse
import io
import pathlib
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = pathlib.Path(__file__).resolve().parent
PUBLIC = HERE.parent / "public"
SOURCE = PUBLIC / "logo.png"

# The two flat foregrounds in the artwork.
BLUE = (0x19, 0x6A, 0xD5)
BLACK = (0x00, 0x00, 0x00)
#: Recolouring applied to the black foreground. --text in src/styles/tokens.css.
INK = (0xEE, 0xF1, 0xE9)
DARK_INK = (0x0C, 0x0E, 0x10)

#: Deviation from white each foreground produces at alpha 1.0.
_DEV_BLUE = np.array([255.0 - c for c in BLUE])
_DEV_BLACK = np.array([255.0 - c for c in BLACK])


def load_source() -> np.ndarray:
    if not SOURCE.exists():
        raise SystemExit(f"missing source logo: {SOURCE}")
    return np.asarray(Image.open(SOURCE).convert("RGB")).astype(np.float64)


def unmultiply(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split a white-backed RGB image into (colour, alpha).

    Each foreground is a line through the origin in deviation space. For each
    pixel, project onto both lines and keep the closer fit. Least squares rather
    than "whichever explains the pixel as more opaque": that rule inverts on this
    artwork, because a flat black pixel scores alpha 1.0 as black but 2.96 as
    blue, so picking the larger turns the entire black S blue. Residuals are
    unambiguous -- 0 for the correct line against 133-209 for the wrong one.
    """
    dev = 255.0 - rgb

    def fit(foreground_dev: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        scale = (dev @ foreground_dev) / float(foreground_dev @ foreground_dev)
        return scale, np.linalg.norm(dev - scale[..., None] * foreground_dev, axis=2)

    scale_black, err_black = fit(_DEV_BLACK)
    scale_blue, err_blue = fit(_DEV_BLUE)

    is_black = err_black <= err_blue
    alpha = np.where(is_black, scale_black, scale_blue)

    colour = np.empty(rgb.shape, dtype=np.uint8)
    colour[is_black] = BLACK
    colour[~is_black] = BLUE
    return colour, np.clip(alpha, 0.0, 1.0)


def recolour(colour: np.ndarray, ink: tuple[int, int, int]) -> np.ndarray:
    out = colour.copy()
    # `.all(axis=2)`, not a bare comparison: `colour == BLACK` yields a per-channel
    # mask of shape (h, w, 3), and indexing the array with that assigns three
    # values per pixel into three pixel-slots -- which numpy rejects outright.
    black_pixels = (colour == np.array(BLACK, dtype=np.uint8)).all(axis=2)
    out[black_pixels] = np.array(ink, dtype=np.uint8)
    return out


def crop_to_ink(colour: np.ndarray, alpha: np.ndarray, threshold: float = 0.02):
    """Crop both arrays to the ink's bbox together; cropping only the mask leaves
    them different sizes and every later stack step fails on a shape mismatch.
    """
    ys, xs = np.nonzero(alpha > threshold)
    if len(ys) == 0:
        raise SystemExit("the source has no ink to crop to")
    return (
        colour[ys.min():ys.max() + 1, xs.min():xs.max() + 1],
        alpha[ys.min():ys.max() + 1, xs.min():xs.max() + 1],
    )


def square_pad(colour: np.ndarray, alpha: np.ndarray, margin: float = 0.04):
    """Pad to a square. The bbox is 1356x1498, so without this the mark stretches
    or sits visibly off-centre, and the favicon has no room for rounded corners.
    """
    height, width = alpha.shape
    side = int(round(max(height, width) * (1 + margin * 2)))
    colour_out = np.zeros((side, side, 3), dtype=colour.dtype)
    alpha_out = np.zeros((side, side), dtype=np.float32)
    top, left = (side - height) // 2, (side - width) // 2
    colour_out[top:top + height, left:left + width] = colour
    alpha_out[top:top + height, left:left + width] = alpha
    return colour_out, alpha_out


def keep_largest_blob(colour: np.ndarray, alpha: np.ndarray, threshold: float = 0.02):
    """Discard every component except the largest.

    That is the S. The streaks are separate components, so this removes them
    without any hand-drawn mask that could rot when the logo is next revised.
    """
    mask = alpha > threshold
    labels, count = ndimage.label(mask)
    if count > 1:
        sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
        biggest = int(np.argmax(sizes)) + 1
        kept = labels == biggest
        # Close the speckle that thresholding leaves along the antialiased edge,
        # otherwise a 16px render is peppered with holes.
        filled = ndimage.binary_fill_holes(kept)
        filled = ndimage.binary_closing(filled, structure=np.ones((5, 5)))
        alpha = np.where(filled, alpha, 0.0).astype(np.float32)
    return colour, alpha


def to_image(colour: np.ndarray, alpha: np.ndarray) -> Image.Image:
    rgba = np.dstack([
        colour,
        (np.clip(alpha, 0, 1) * 255).astype(np.uint8),
    ])
    return Image.fromarray(rgba, mode="RGBA")


def render(sizes: list[int], colour: np.ndarray, alpha: np.ndarray) -> list[Image.Image]:
    """Downscale one (colour, alpha) pair to several square sizes."""
    image = to_image(colour, alpha)
    return [image.resize((size, size), Image.LANCZOS) for size in sizes]


def encode(image: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def build_outputs(ink: tuple[int, int, int]) -> dict[str, bytes]:
    rgb = load_source()
    colour, alpha = unmultiply(rgb)
    colour = recolour(colour, ink)

    # Full mark, transparency preserved, streaks and all.
    full_colour, full_alpha = square_pad(*crop_to_ink(colour, alpha))
    # 512 is well past the largest consumer (the 180px touch icon) and costs a
    # few tens of KB, which is worth it for a topbar image shown at 2x on retina.
    full_image = render([512], full_colour, full_alpha)[0]

    # Simplified: the S alone, with extra clear space for the rounded corners.
    icon_colour, icon_alpha = square_pad(
        *keep_largest_blob(*crop_to_ink(colour, alpha)), margin=0.10,
    )
    icon_frames = render([16, 32, 48], icon_colour, icon_alpha)
    touch_frames = render([180], icon_colour, icon_alpha)

    return {
        "logo-mark.png": encode(full_image, "PNG"),
        "favicon-16.png": encode(icon_frames[0], "PNG"),
        "favicon-32.png": encode(icon_frames[1], "PNG"),
        "favicon-48.png": encode(icon_frames[2], "PNG"),
        "favicon.ico": encode(
            icon_frames[0], "ICO",
            sizes=[(f.width, f.height) for f in icon_frames],
            append_images=icon_frames[1:],
        ),
        "apple-touch-icon.png": encode(touch_frames[0], "PNG"),
    }


def _pixels(data: bytes) -> np.ndarray | None:
    """Decode an encoded image to RGBA, or None if it will not decode."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            return np.asarray(image.convert("RGBA")).astype(np.int16)
    except Exception:
        return None


def _differs(path: pathlib.Path, data: bytes) -> bool:
    """Whether the file differs from `data` *in pixels*, not bytes: `npm run`
    resolves a different Python than the venv, and its Pillow encodes the same
    pixels differently, so byte equality reported fresh files as stale.
    """
    if not path.exists():
        return True
    if path.read_bytes() == data:
        return False
    on_disk, fresh = _pixels(path.read_bytes()), _pixels(data)
    if on_disk is None or fresh is None:
        return True
    return on_disk.shape != fresh.shape or not np.array_equal(on_disk, fresh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ink", default=INK, type=lambda v: tuple(int(v[i:i + 2], 16) for i in (0, 2, 4)),
        help="replacement for the black foreground, as RRGGBB (default: --text)",
    )
    parser.add_argument(
        "--assert-consistent", action="store_true",
        help="exit non-zero if any output on disk differs from what would be written",
    )
    args = parser.parse_args(argv)

    outputs = build_outputs(args.ink)
    stale = []
    for name, data in outputs.items():
        path = PUBLIC / name
        if _differs(path, data):
            stale.append(name)
            if not args.assert_consistent:
                path.write_bytes(data)

    if args.assert_consistent and stale:
        print(f"  stale logo assets: {', '.join(stale)}", file=sys.stderr)
        return 1
    verb = "unchanged" if not stale else "regenerated " + ", ".join(stale)
    print(f"  logo assets: {verb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
