"""Small bounded raster inspection, never OCR or an image-to-model request."""

from io import BytesIO
import zlib

from PIL import Image
from pdfminer.psparser import literal_name
from pdfminer.utils import apply_png_predictor, apply_tiff_predictor

from backend.app.core.document_limits import DocumentError, FILE_BYTES

MAX_IMAGE_PIXELS = 4_000_000


def image_text_signal(image, budget):
    """True: repeated text-like bands; None: unsafe/unsupported; False: no signal.

    False is only a weak decoration signal when enough readable text is outside
    the image. It never makes an otherwise scanned/empty page readable.
    """
    budget.check()
    try:
        width, height = map(int, image["srcsize"])
        if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
            return None
        stream = image["stream"]
        # Masks/inverted decode arrays change what the image visibly contains;
        # raw RGB alone is not sufficient evidence that it is decorative.
        if any(stream.attrs.get(key) is not None for key in ("SMask", "Mask", "Decode")) or image.get("imagemask"):
            return None
        raw = stream.get_rawdata()
        if raw is None or len(raw) > FILE_BYTES:
            return None
        filters = stream.get_filters()
        if len(filters) > 1:
            return None
        filter_name = literal_name(filters[0][0]) if filters else ""
        if filter_name in {"DCTDecode", "DCT", "JPXDecode"}:
            bitmap = Image.open(BytesIO(raw))
            if bitmap.size != (width, height):
                bitmap.close()
                return None
        else:
            colors = [literal_name(value) for value in image.get("colorspace", [])]
            mode = {"DeviceRGB": "RGB", "RGB": "RGB", "DeviceGray": "L", "G": "L", "DeviceCMYK": "CMYK"}.get(colors[0] if colors else "")
            bits = image.get("bits", 8)
            if mode is None or bits not in {1, 8} or (bits == 1 and mode != "L"):
                return None
            channels = {"L": 1, "RGB": 3, "CMYK": 4}[mode]
            expected = ((width * channels * bits + 7) // 8) * height
            params = filters[0][1] if filters else {}
            predictor = params.get("Predictor", 1)
            if filter_name in {"FlateDecode", "Fl"}:
                decoder = zlib.decompressobj()
                # Include at most one PNG predictor byte per row, not an
                # unbounded get_data() decompression of untrusted PDF streams.
                raw = decoder.decompress(raw, expected + height + 1)
                if not decoder.eof or decoder.unconsumed_tail or len(raw) > expected + height:
                    return None
                if predictor >= 10:
                    if params.get("Colors", 1) != channels or params.get("Columns", 1) != width or params.get("BitsPerComponent", 8) != bits:
                        return None
                    raw = apply_png_predictor(predictor, channels, width, bits, raw)
                elif predictor == 2:
                    raw = apply_tiff_predictor(channels, width, bits, raw)
                elif predictor != 1:
                    return None
            elif filter_name:
                return None
            if len(raw) != expected:
                return None
            bitmap = Image.frombytes("1" if bits == 1 else mode, (width, height), raw)
        with bitmap:
            budget.check()
            bitmap.thumbnail((256, 256))
            with bitmap.convert("L") as gray:
                pixels, bands, active = gray.tobytes(), 0, False
                for y in range(gray.height):
                    ink = sum(value < 180 for value in pixels[y * gray.width:(y + 1) * gray.width]) / gray.width
                    row_active = .02 <= ink <= .75
                    if row_active and not active:
                        bands += 1
                    active = row_active
        budget.check()
        return bands >= 5
    except DocumentError:
        raise
    except Exception:
        return None
