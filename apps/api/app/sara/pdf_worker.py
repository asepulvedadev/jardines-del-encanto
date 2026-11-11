"""Fixed parser child: stdin bytes only, bounded resources and no host data access."""

import codecs
import importlib
import io
import json
import resource
import sys
import warnings

resource.setrlimit(resource.RLIMIT_AS, (192 * 1024 * 1024,) * 2)
resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))

# Warm the fixed parser's lazy imports before sealing filesystem access.
from pypdf import PdfReader

importlib.import_module("pypdf.filters")
importlib.import_module("pypdf.xmp")

for encoding in (
    "utf-8",
    "utf-16-be",
    "utf-16-le",
    "latin-1",
    "charmap",
    "unicode_escape",
    "raw_unicode_escape",
):
    codecs.lookup(encoding)


def deny_host_access(event, args):
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn")) or event in {
        "open",
        "os.system",
        "os.listdir",
        "os.scandir",
        "os.remove",
        "os.rename",
        "os.mkdir",
        "os.chdir",
        "os.symlink",
        "os.link",
    }:
        raise PermissionError("parser_access_denied")


warnings.simplefilter("ignore")
sys.addaudithook(deny_host_access)
try:
    raw = sys.stdin.buffer.read(524289)
    if not raw or len(raw) > 524288:
        sys.exit(2)
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
        sys.exit(2)
    chunks, length = [], 0
    for page in reader.pages:
        text = page.extract_text() or ""
        length += len(text) + 1
        if length > 16000:
            sys.exit(4)
        chunks.append(text)
    text = "\n".join(chunks).strip()
    if not text:
        sys.exit(3)
    print(json.dumps({"text": text}, ensure_ascii=True))
except Exception:  # noqa: BLE001 - no document/parser internals may cross the child boundary
    sys.exit(2)
