import pytest

import handle_request as hr


def _req(path: str, *headers: str) -> str:
	"""Build a raw HTTP/1.1 GET request string."""
	return '\r\n'.join([f'GET {path} HTTP/1.1', *headers, '', ''])


# ── request line / range parsing ─────────────────────────────────────────────

def test_decode_no_range():
	assert hr._decode_request(_req('/a.jpg')) == ('/a.jpg', None, None)


def test_decode_unquotes_path():
	path, _, _ = hr._decode_request(_req('/a%20b%2Fc.jpg'))
	assert path == '/a b/c.jpg'


@pytest.mark.parametrize('header, expected', [
	('Range: bytes=0-99',    (0, 99)),
	('Range: bytes=100-',    (100, None)),   # open-ended
	('Range: bytes=500-1000', (500, 1000)),
])
def test_decode_range(header, expected):
	_, range_l, range_u = hr._decode_request(_req('/clip.mp4', header))
	assert (range_l, range_u) == expected


def test_decode_range_is_case_insensitive():
	_, range_l, range_u = hr._decode_request(_req('/clip.mp4', 'range: bytes=10-20'))
	assert (range_l, range_u) == (10, 20)


def test_decode_rejects_non_get():
	with pytest.raises(Exception):
		hr._decode_request('POST /a.jpg HTTP/1.1\r\n\r\n')


def test_decode_rejects_wrong_http_version():
	with pytest.raises(Exception):
		hr._decode_request('GET /a.jpg HTTP/1.0\r\n\r\n')


# ── response encoding ────────────────────────────────────────────────────────

def test_encode_200_html_is_not_cached():
	out = hr._encode(b'<html>', 'text/html', None, None, None)
	assert out.startswith(b'HTTP/1.1 200 OK\r\n')
	assert b'Cache-Control: max-age=0\r\n' in out
	assert out.endswith(b'<html>')


def test_encode_200_image_uses_cache_seconds():
	out = hr._encode(b'\xff\xd8', 'image/jpeg', None, None, None)
	assert b'Cache-Control: public, max-age=100, immutable\r\n' in out
	assert b'Content-Type: image/jpeg\r\n' in out
	assert b'Content-Length: 2\r\n' in out


def test_encode_206_partial_content():
	out = hr._encode(b'abc', 'video/mp4', 0, 2, 10)
	assert out.startswith(b'HTTP/1.1 206 Partial Content\r\n')
	assert b'Content-Range: bytes 0-2/10\r\n' in out
	assert b'Content-Length: 3\r\n' in out
	assert out.endswith(b'abc')


@pytest.mark.parametrize('mime, expected', [
	('text/plain', b'max-age=0'),
	('text/html',  b'max-age=0'),
	('image/jpeg', b'max-age=100'),
	('video/mp4',  b'max-age=100'),
])
def test_set_cache(mime, expected):
	assert expected in hr._set_cache(mime).encode()
