import os
import subprocess
import traceback
import urllib.parse as urlparse

from config import config, WINDOWS
from log import log

MIME: dict[str, str] = {
	'.jpg' : 'image/jpeg',
	'.jpeg': 'image/jpeg',
	'.png' : 'image/png',
	'.gif' : 'image/gif',
	'.webp': 'image/webp',
	'.bmp' : 'image/bmp',
	'.svg' : 'image/svg+xml',
	'.crw' : 'image/jpeg',
	'.cr2' : 'image/jpeg',
	'.mp4' : 'video/mp4',
	'.m4v' : 'video/mp4',
	'.mov' : 'video/mp4',
	'.ts'  : 'video/mp2t',
	'.webm': 'video/webm',
	'.mp3' : 'audio/mpeg',
	'.m4a' : 'audio/mp4',
	'.ogg' : 'audio/ogg',
	'.wav' : 'audio/wav',
}

RAW_EXTS = frozenset({'.crw', '.cr2'})

NON_IMAGE_EXTS = frozenset({'.mp4', '.m4v', '.mov', '.ts', '.webm', '.mp3', '.m4a', '.ogg', '.wav'})

def dcraw_extract(server_path: str) -> bytes | None:
	exe = os.path.join('resources', 'dcraw.exe') if WINDOWS else 'dcraw'
	result = subprocess.run([exe, '-e', '-c', server_path], capture_output=True)
	return result.stdout if result.returncode == 0 and result.stdout else None


VIRTUAL_ROOT = '\x00'  # sentinel for the synthetic "/" directory (no real fs path)


def roots() -> list[tuple[str, str]]:
	"""Return [(name, abs_path), ...] from config 'roots'."""
	return [(r['name'], os.path.abspath(r['path'])) for r in config('roots')]


def to_client_path(file_path: str) -> str:
	abs_path = os.path.abspath(file_path)
	for name, root_path in roots():
		if abs_path == root_path:
			return '/' + urlparse.quote(name, safe='')
		if abs_path.startswith(root_path + os.sep):
			rel = abs_path[len(root_path):].replace(os.sep, '/')
			return urlparse.quote(f'/{name}{rel}', safe='/,')
	return '/'


def to_server_path(url: str) -> str:
	"""Translate a URL path to a filesystem path, or VIRTUAL_ROOT for '/'."""
	if url == '/':
		return VIRTUAL_ROOT
	parts = url.lstrip('/').split('/', 1)
	root_name = urlparse.unquote(parts[0])
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

		if range_u is None:
			range_u = range_l + config('streamingChunkBytes') - 1

		if range_u >= file_end: # type: ignore
			range_u = file_end - 1

		f.seek(range_l)
		return f.read(range_u - range_l + 1), range_l, range_u, file_end # type: ignore


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
