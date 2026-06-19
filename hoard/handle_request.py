from urllib.parse import unquote, quote
import subprocess
import os

import filesystem as fs
import handle_directory
import handle_file
import handle_flag
import handle_thumbnail
from log import log
from config import config, WINDOWS, MACOS
from resources import resource


_NOT_FOUND  = b'HTTP/1.1 404 Not Found\r\ncontent-type: text/plain\r\ncontent-length: 9\r\n\r\nNot Found'
# placeholder shipped in config.json.example — if left unchanged, lock everything out
_DEFAULT_AUTH_TOKEN = 'change-me-to-a-random-uuid'


def build_response_bytes(req: str) -> bytes:
	# gate every request on the auth cookie; unauthorized clients get a plain 404
	# (the server looks nonexistent rather than merely forbidden)
	if not _authorized(req):
		return _NOT_FOUND

	req, range_l, range_u = _decode_request(req)
	# directory-level '?all' = recursive listing; strip it before path translation
	# (unlike file suffixes ?tn/?del, it must not ride through to_server_path or a
	# top-level root name like '/C Pictures?all' would fail to resolve)
	recursive             = req.endswith('?all')
	req_server_path       = fs.to_server_path(req[:-4] if recursive else req)
	end                   = None
	extra_headers         = None

	if resource(req):
		data, mime = resource(req)

	elif req.startswith('/.well-known'):
		data, mime = b'', 'text/plain'

	elif recursive and os.path.isdir(req_server_path):
		data, mime = handle_directory.run(req_server_path, recursive=True)

	elif req_server_path == fs.VIRTUAL_ROOT or os.path.isdir(req_server_path):
		data, mime = handle_directory.run(req_server_path)

	# everything below operates on a real file path — reject ../ traversal outside roots
	elif not fs.within_roots(req_server_path):
		log(f'404 (outside roots) {req_server_path}')
		return _NOT_FOUND

	elif req_server_path.endswith('?tn'): # remove ?tn
		result = handle_thumbnail.run(req_server_path)
		if result is None:
			return b'HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain\r\nContent-Length: 4\r\nRetry-After: 10\r\n\r\nBusy'
		data, mime, dims = result
		# the label text is no longer baked into the thumbnail; carry it on the
		# response so the client can render it as HTML. CORS headers let the page
		# fetch() thumbnails from the separate thumbnail-port origins and read the
		# custom header (a plain GET, so no preflight is triggered).
		extra_headers = [
			f'X-Thumb-Dims: {quote(dims)}',
			'Access-Control-Allow-Origin: *',
			'Access-Control-Expose-Headers: X-Thumb-Dims',
		]

	elif req_server_path.endswith('?del'):
		data, mime = fs.delete_file(req_server_path)

	elif '?rename=' in req_server_path:
		data, mime = fs.rename_file(req_server_path)

	elif req_server_path.endswith('?explorer'):
		data, mime = _open_explorer(req_server_path)

	elif '?flag=' in req_server_path:
		data, mime = handle_flag.run(req_server_path)

	elif '?fav=' in req_server_path:
		data, mime = handle_flag.run_favorite(req_server_path)

	elif '?rotate=' in req_server_path:
		data, mime = handle_flag.run_rotation(req_server_path)

	else:
		result = handle_file.run(req_server_path, range_l, range_u)
		if result is None:
			log(f'404 {req_server_path}')
			return _NOT_FOUND
		data, mime, range_l, range_u, end = result

	return _encode(data, mime, range_l, range_u, end, extra_headers)


def _open_explorer(serverPath: str) -> tuple[bytes, str]:
	# args are formed into a string so that .Popen() doesn't remove necessary quotes for explorer.exe
	target = serverPath[:-9]  # strip '?explorer'
	log('exploring: ' + target)
	if WINDOWS:
		# no shell=True: pass args directly so a crafted path can't inject a command
		args = f'explorer /select,"{target}"'
	elif MACOS:
		args = f'open -R "{target}'
	else:
		args = f'xdg-open "{os.path.dirname(target)}"'
	log(str(args))
	subprocess.Popen(args)
	return b'ok', 'text/plain'


def _authorized(req: str) -> bool:
	"""True if the request's Cookie header carries auth=<config 'authToken'>.

	A blank authToken disables the gate (all requests allowed); the unchanged
	example placeholder denies everything (forcing the operator to set a real
	token). Header names are case-insensitive; cookie names/values are not. Parses
	the raw request so it runs before any path handling.
	"""
	token = config('authToken')
	if not token:
		return True
	if token == _DEFAULT_AUTH_TOKEN:
		return False
	for line in req.split('\r\n'):
		if line[:7].lower() != 'cookie:':
			continue
		for pair in line[7:].split(';'):
			name, _, value = pair.strip().partition('=')
			if name == 'auth' and value == token:
				return True
	return False


def _decode_request(req: str) -> tuple[str, int | None, int | None]:
	# req is the WHOLE http request
	request_lines = req.split('\r\n')

	http_get = request_lines[0]
	if not http_get.startswith('GET '):
		raise Exception('request not GET')
	if not http_get.endswith(' HTTP/1.1'):
		raise Exception('request not HTTP/1.1')

	# errors='replace' so a stray non-UTF-8 %xx degrades to U+FFFD instead of raising
	# (which would drop the connection with no response); such a path just won't resolve
	requested_path = unquote(http_get[4:-9], encoding='utf-8', errors='replace')

	http_range = [l for l in request_lines if 'range:' in str.lower(l)]
	if not http_range:
		return requested_path, None, None

	http_range = str.replace(http_range[0].lower(), 'range: bytes=', '')
	split = http_range.split('-')
	range_l = int(split[0] or '0')
	range_u = int(split[1]) if split[1] != '' else None # 0-based, inclusive
	return requested_path, range_l, range_u


def _encode(data: bytes, mime: str, range_l: int | None, range_u: int | None, end: int | None,
		extra_headers: list[str] | None = None) -> bytes:
	if range_l is not None and range_u is not None and end is not None:
		return bytes(
			f'HTTP/1.1 206 Partial Content\r\n'
			f'Accept-Ranges: bytes\r\n'
			f'Content-Type: {mime}\r\n'
			f'Content-Length: {len(data)}\r\n'
			f'{_set_cache(mime)}\r\n'
			f'Content-Range: bytes {range_l}-{range_u}/{end}\r\n\r\n', 'utf-8') + data
	extra = ''.join(f'{h}\r\n' for h in extra_headers) if extra_headers else ''
	return bytes(
		f'HTTP/1.1 200 OK\r\n'
		f'Accept-Ranges: bytes\r\n'
		f'Content-Type: {mime}\r\n'
		f'Content-Length: {len(data)}\r\n'
		f'{extra}'
		f'{_set_cache(mime)}\r\n\r\n', 'utf-8') + data

def _set_cache(mime: str):
	if mime in ['text/plain', 'text/html', 'text/css', 'text/javascript']:
		return f'Cache-Control: max-age=0'
	else:
		return f'Cache-Control: public, max-age={config("cacheSeconds")}, immutable'