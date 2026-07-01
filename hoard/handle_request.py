from urllib.parse import unquote, quote
import subprocess
import os

import filesystem as fs
import handle_directory
import handle_file
import handle_flag
import handle_thumbnail
from log import log
from config import config, config_get, WINDOWS, MACOS
from resources import resource


_NOT_FOUND  = b'HTTP/1.1 404 Not Found\r\ncontent-type: text/plain\r\ncontent-length: 9\r\n\r\nNot Found'
# placeholder shipped in config.json.example — if left unchanged, lock everything out
_DEFAULT_AUTH_TOKEN = 'change-me-to-a-random-uuid'


def build_response_bytes(req: str, slow: bool = False) -> bytes:
	raw_req = req  # full request (with headers) — needed for cookies / Origin

	# magic link: ?auth=<token> sets the cookie (host-wide, so it covers every
	# port) and redirects to the clean URL. Checked before the gate so it works
	# from an unauthorized browser.
	magic = _auth_magic_link(raw_req)
	if magic is not None:
		return magic

	# gate every request on the auth cookie; unauthorized clients get a plain 404
	# (the server looks nonexistent rather than merely forbidden)
	if not _authorized(raw_req):
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
		extra_headers = _cors_headers()

	elif req_server_path == fs.VIRTUAL_ROOT or os.path.isdir(req_server_path):
		data, mime = handle_directory.run(req_server_path)
		extra_headers = _cors_headers()

	# everything below operates on a real file path — reject ../ traversal outside roots
	elif not fs.within_roots(req_server_path):
		log(f'404 (outside roots) {req_server_path}')
		return _NOT_FOUND

	elif req_server_path.endswith('?tn'): # remove ?tn
		result = handle_thumbnail.run(req_server_path, slow)
		if result is None:
			return b'HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain\r\nContent-Length: 4\r\nRetry-After: 10\r\n\r\nBusy'
		data, mime, dims = result
		extra_headers = _thumb_headers(dims, raw_req)

	elif req_server_path.endswith('?del'):
		data, mime = fs.delete_file(req_server_path)

	elif '?rename=' in req_server_path:
		data, mime = fs.rename_file(req_server_path)

	elif req_server_path.endswith('?explorer'):
		data, mime = _open_explorer(req_server_path)

	elif '?edit=' in req_server_path:
		data, mime = _open_editor(req_server_path)

	elif '?flag=' in req_server_path:
		data, mime = handle_flag.run(req_server_path)

	elif '?fav=' in req_server_path:
		data, mime = handle_flag.run_favorite(req_server_path)

	elif '?rotate=' in req_server_path:
		data, mime = handle_flag.run_rotation(req_server_path)

	else:
		result = handle_file.run(req_server_path, range_l, range_u, slow)
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


def _open_editor(serverPath: str) -> tuple[bytes, str]:
	# open the file in editors[<index>] from config; index is the ?edit= value.
	# each editor is a {name, path} entry (mirrors 'roots')
	target, _, idx = serverPath.rpartition('?edit=')
	editors = config_get('editors', []) or []
	try:
		editor = editors[int(idx)]['path']
	except (ValueError, IndexError, KeyError, TypeError):
		log(f'?edit: no editor at index {idx!r} (have {len(editors)})')
		return b'bad editor', 'text/plain'
	log(f'editing: {target} with {editor}')
	# pass args as a list (no shell): a crafted path can't inject a command
	subprocess.Popen([editor, target])
	return b'ok', 'text/plain'


def _request_header(req: str, name: str) -> str | None:
	"""Value of a request header (case-insensitive name), or None if absent."""
	prefix = name.lower() + ':'
	for line in req.split('\r\n')[1:]:          # skip the GET request line
		if line.lower().startswith(prefix):
			return line[len(prefix):].strip()
	return None


def _cors_headers() -> list[str]:
	"""CORS headers for a directory listing response, allowing credentialed cross-origin
	access from the same host's other ports (e.g. the thumbnail port). The gallery
	makes XHR requests to those ports and needs the auth cookie + custom header."""
	return [
		f'Access-Control-Allow-Origin: *',  # allow all origins, but they must send credentials to get the data
		'Access-Control-Allow-Credentials: true',
		'Access-Control-Expose-Headers: X-Thumb-Dims',
	]


def _thumb_headers(dims: str, req: str) -> list[str]:
	"""Headers for a thumbnail response: the dimension label, plus credentialed
	CORS when the request is cross-origin (the browser fetches thumbnails from the
	separate thumbnail-port origins and must send the auth cookie + read the
	custom header). A plain GET, so no preflight is triggered."""
	headers = [f'X-Thumb-Dims: {quote(dims)}']
	origin = _request_header(req, 'origin')
	if origin:
		# echo the caller's origin (can't use '*' alongside credentials); the
		# legitimate cross-origin callers are this same host's other ports
		headers += [
			f'Access-Control-Allow-Origin: {origin}',
			'Access-Control-Allow-Credentials: true',
			'Access-Control-Expose-Headers: X-Thumb-Dims',
		]
	return headers


def _auth_magic_link(req: str) -> bytes | None:
	"""If the request is `GET /...?auth=<token>` with the configured token, return
	a redirect that stores the auth cookie (host-wide, long-lived) and strips the
	token from the URL. Returns None if there's no auth query, the token doesn't
	match, or the gate is disabled (blank) / not configured (placeholder)."""
	token = config('authToken')
	if not token or token == _DEFAULT_AUTH_TOKEN:
		return None
	line = req.split('\r\n', 1)[0]
	if not line.startswith('GET ') or not line.endswith(' HTTP/1.1'):
		return None
	path = line[4:-9]                                   # still percent-encoded
	base, sep, query = path.partition('?')
	if not sep:
		return None
	params = [kv.partition('=') for kv in query.split('&')]
	if not any(k == 'auth' for k, _, _ in params):
		return None
	supplied = unquote(next(v for k, _, v in params if k == 'auth'), errors='replace')
	if supplied != token:
		return None                                    # let the gate 404 it
	# rebuild the query without auth, keeping each param's original '='-presence
	remaining = '&'.join(k + sep + v for k, sep, v in params if k != 'auth')
	location  = base + (f'?{remaining}' if remaining else '')
	cookie    = f'auth={token}; Path=/; Max-Age=315360000; HttpOnly; SameSite=Lax'
	return bytes(
		f'HTTP/1.1 302 Found\r\n'
		f'Location: {location}\r\n'
		f'Set-Cookie: {cookie}\r\n'
		f'Cache-Control: no-store\r\n'
		f'Content-Length: 0\r\n\r\n', 'utf-8')


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
		log('authToken is unchanged placeholder; denying all requests')
		return False
	for line in req.split('\r\n'):
		if line[:7].lower() != 'cookie:':
			continue
		for pair in line[7:].split(';'):
			name, _, value = pair.strip().partition('=')
			if name == 'auth' and value == token:
				return True
	log('request denied: missing or wrong auth cookie')
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