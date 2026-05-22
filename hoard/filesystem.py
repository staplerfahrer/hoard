import os
import subprocess
import traceback
import urllib.parse as urlparse

from config import config
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
	result = subprocess.run(
		['resources/dcraw.exe', '-e', '-c', server_path],
		capture_output=True
	)
	return result.stdout if result.returncode == 0 and result.stdout else None


def to_client_path(file_path: str) -> str:
	url = file_path.replace(config('root'), '').replace('\\', '/')
	return urlparse.quote(url, safe='/,') if url else '/'


def to_server_path(url: str) -> str:
	return config('root') + url.replace('/', '\\')


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
