"""Bounded structural PNG validation; never trust a vendor MIME label."""

import struct
import zlib

MAX_IMAGE = 8 * 1024 * 1024
SIZES = {"1024x1024", "1536x1024", "1024x1536"}


def validate_png(data, size):
    if not isinstance(data, bytes) or not 57 <= len(data) <= MAX_IMAGE or size not in SIZES:
        raise ValueError("invalid_image")
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid_image")
    offset, seen_data, first = 8, False, True
    while offset + 12 <= len(data):
        length = struct.unpack("!I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            break
        payload = data[offset + 8 : end - 4]
        crc = struct.unpack("!I", data[end - 4 : end])[0]
        if zlib.crc32(kind + payload) != crc:
            break
        if first:
            if kind != b"IHDR" or length != 13:
                break
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                "!IIBBBBB", payload
            )
            if (
                f"{width}x{height}" != size
                or depth not in {8, 16}
                or color not in {0, 2, 4, 6}
                or compression
                or filtering
                or interlace not in {0, 1}
            ):
                break
            first = False
        elif kind == b"IHDR":
            break
        if kind == b"IDAT":
            seen_data = True
        if kind == b"IEND":
            if length == 0 and seen_data and end == len(data):
                return data
            break
        offset = end
    raise ValueError("invalid_image")
