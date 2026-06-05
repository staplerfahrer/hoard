import io
import os
import subprocess
import traceback
import urllib.parse as urlparse

from PIL import Image

from config import config, WINDOWS
from log import log
import plugins

MIME: dict[str, str] = {
	'.jpg' : 'image/jpeg',
	'.jpeg': 'image/jpeg',
	'.png' : 'image/png',
	'.gif' : 'image/gif',
	'.webp': 'image/webp',
	'.bmp' : 'image/bmp',
	'.svg' : 'image/svg+xml',
	'.mp4' : 'video/mp4',
	'.m4v' : 'video/mp4',
	'.mov' : 'video/mp4',
	'.ts'  : 'video/mp2t',
	'.webm': 'video/webm',
	'.mp3' : 'audio/mpeg',
	'.m4a' : 'audio/mp4',
	'.ogg' : 'audio/ogg',
	'.wav' : 'audio/wav',
	'.pdf' : 'application/pdf',
	'.heic': 'image/heic',
	'.heif': 'image/heif',
}

# Camera RAW formats decodable by dcraw (Dave Coffin's dcraw.c, as built by
# ncruces/dcraw). Grouped by manufacturer. dcraw handles all of these; we route
# any of these extensions through dcraw_extract().
RAW_EXTS = frozenset({
	'.3fr',                          # Hasselblad
	'.arw', '.srf', '.sr2',          # Sony
	'.bay',                          # Casio
	'.cap', '.iiq', '.eip',          # Phase One
	'.crw', '.cr2',                  # Canon
	'.dcs', '.dcr', '.drf', '.k25', '.kdc',  # Kodak
	'.dng',                          # Adobe / generic
	'.erf',                          # Epson
	'.fff',                          # Imacon / Hasselblad
	'.mef',                          # Mamiya
	'.mdc',                          # Minolta / Agfa
	'.mos',                          # Leaf
	'.mrw',                          # Minolta
	'.nef', '.nrw',                  # Nikon
	'.orf',                          # Olympus
	'.pef', '.ptx',                  # Pentax
	'.pxn',                          # Logitech
	'.raf',                          # Fujifilm
	'.raw', '.rw2', '.rwl', '.rwz',  # Panasonic / Leica
	'.srw',                          # Samsung
	'.x3f',                          # Sigma / Foveon
})

# RAW files are always delivered as JPEG (embedded preview or re-encoded decode).
MIME.update({ext: 'image/jpeg' for ext in RAW_EXTS})

NON_IMAGE_EXTS = frozenset({'.mp4', '.m4v', '.mov', '.ts', '.webm', '.mp3', '.m4a', '.ogg', '.wav', '.pdf'})


# How the gallery viewer can present a file. These codes are mirrored in
# gallery.html (KIND_* constants) and packed one-char-per-file into {kinds}
# so the viewer can skip files it can't display during next/prev navigation.
KIND_UNVIEWABLE = 0  # txt, zip, audio, … — viewer skips these
KIND_IMAGE      = 1  # shown in <img> (native, RAW→JPEG, HEIC, PIL-convertible)
KIND_VIDEO      = 2  # shown in <video>
KIND_PDF        = 3  # shown in an <iframe>

# Still-image extensions the <img> endpoint (handle_file) can produce: browser-
# native, RAW (dcraw→JPEG), HEIC/HEIF (pillow-heif), and other formats re-encoded
# via PIL. Kept as an explicit allowlist so classification never opens the file.
IMAGE_EXTS = frozenset({
	'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg',
	'.heic', '.heif', '.tif', '.tiff', '.ico', '.jp2', '.tga',
}) | RAW_EXTS

VIDEO_EXTS = frozenset({'.mp4', '.m4v', '.mov', '.ts', '.webm'})


def classify(path: str) -> int:
	"""Return the viewer KIND_* code for a file, by extension only."""
	ext = os.path.splitext(path)[1].lower()
	if plugins.handles(ext):  # plugin-rendered files are shown as images
		return KIND_IMAGE
	if ext == '.pdf':
		return KIND_PDF
	if ext in IMAGE_EXTS:
		return KIND_IMAGE
	if ext in VIDEO_EXTS:
		return KIND_VIDEO
	return KIND_UNVIEWABLE


def dcraw_extract(server_path: str) -> bytes | None:
	"""Return displayable JPEG bytes for a RAW file via dcraw.

	Tries the embedded preview first (-e: fast, no demosaicing, returned
	unchanged). RAW files without an embedded preview fall back to a full
	decode (-c -w) whose PPM output is re-encoded to JPEG.
	"""
	exe = os.path.join('resources', 'dcraw.exe') if WINDOWS else 'dcraw'

	# fast path: extract the embedded JPEG preview, passed through unchanged
	result = subprocess.run([exe, '-e', '-c', server_path], capture_output=True)
	if result.returncode == 0 and result.stdout:
		return result.stdout

	# fallback: full RAW decode (camera white balance) to PPM, re-encoded to JPEG
	result = subprocess.run([exe, '-c', '-w', server_path], capture_output=True)
	if result.returncode != 0 or not result.stdout:
		return None
	try:
		with Image.open(io.BytesIO(result.stdout)) as img:
			buf = io.BytesIO()
			img.convert('RGB').save(buf, format='JPEG', quality=95)
			return buf.getvalue()
	except Exception:
		log(f'dcraw_extract full-decode convert failed: {traceback.format_exc()}')
		return None


VIRTUAL_ROOT = '\x00'  # sentinel for the synthetic "/" directory (no real fs path)


def roots() -> list[tuple[str, str]]:
	"""Return [(name, abs_path), ...] from config 'roots'."""
	return [(r['name'], os.path.abspath(r['path'])) for r in config('roots')]


def to_client_path(file_path: str) -> str:
	# Percent-encode every reserved/unsafe char, keeping only '/' as the separator.
	# The exact escapes needn't match the browser's encoder byte-for-byte: the client
	# compares paths in DECODED form (decodeURIComponent), which is encoder-agnostic.
	safe = '/'
	abs_path = os.path.abspath(file_path)
	for name, root_path in roots():
		if abs_path == root_path:
			return '/' + urlparse.quote(name, safe=safe)
		if abs_path.startswith(root_path + os.sep):
			rel = abs_path[len(root_path):].replace(os.sep, '/')
			return urlparse.quote(f'/{name}{rel}', safe=safe)
	return '/'


def to_server_path(url: str) -> str:
	"""Translate a URL path to a filesystem path, or VIRTUAL_ROOT for '/'.

	The caller is expected to have percent-decoded the path already (handle_request
	unquotes the whole request path once), so this does NOT decode again — decoding
	twice would corrupt a name containing a literal '%'.
	"""
	if url == '/':
		return VIRTUAL_ROOT
	parts = url.lstrip('/').split('/', 1)
	root_name = parts[0]
	rest      = parts[1] if len(parts) > 1 else ''
	for name, root_path in roots():
		if name == root_name:
			return root_path + (os.sep + rest.replace('/', os.sep) if rest else '')
	return VIRTUAL_ROOT  # unknown root name → fall back to virtual root


def read_file_bytes(file_name: str, range_l: int | None = None, range_u: int | None = None) \
	 	-> tuple[bytes, int | None, int | None, int | None]:
	# range_u may be None
	# (https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Range)

	with open(file_name, 'rb') as f:
		if range_l is None:
			return f.read(), None, None, None

		f.seek(0, os.SEEK_END)
		file_end = f.tell()

		range_u_value = range_u or range_l + config('streamingChunkBytes') - 1

		if range_u_value >= file_end:
			range_u_value = file_end - 1

		f.seek(range_l)
		count = range_u_value - range_l + 1
		serve = f.read(count), range_l, range_u_value, file_end
		return serve


def delete_file(server_path: str) -> tuple[bytes, str]:
	if not config('allowDelete'):
		return b'disabled', 'text/plain'
	try:
		target = server_path[:-4]
		os.rename(target, target + '.deleted')
		return b'ok', 'text/plain'
	except:
		log(f'Exception at delete: {traceback.format_exc()}')
		return b'error', 'text/plain'


def is_picture(file_name: str) -> bool:
	parts = os.path.splitext(file_name)
	return parts[1].lower() in MIME


def serve_file(server_path: str, range_l: int | None, range_u: int | None) \
		-> tuple[bytes, str, int | None, int | None, int | None]:
	mime = MIME[os.path.splitext(server_path)[1].lower()]
	data, range_l, range_u, end = read_file_bytes(server_path, range_l, range_u)
	return data, mime, range_l, range_u, end
