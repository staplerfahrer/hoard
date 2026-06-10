import os
import urllib.parse

import pytest

import filesystem as fs


# ── path translation ─────────────────────────────────────────────────────────

def test_root_url_is_virtual_root():
	assert fs.to_server_path('/') == fs.VIRTUAL_ROOT


def test_unknown_root_name_falls_back_to_virtual_root():
	assert fs.to_server_path('/NotARoot/x.jpg') == fs.VIRTUAL_ROOT


def test_named_root_maps_to_its_path(fake_root):
	assert fs.to_server_path('/Photos') == os.path.abspath(str(fake_root))


def test_server_path_joins_nested_url(fake_root):
	expected = os.path.join(os.path.abspath(str(fake_root)), 'sub', 'a.jpg')
	assert fs.to_server_path('/Photos/sub/a.jpg') == expected


def test_client_path_round_trips(fake_root):
	server = fs.to_server_path('/Photos/sub/a.jpg')
	assert fs.to_client_path(server) == '/Photos/sub/a.jpg'


def test_root_path_maps_back_to_named_url(fake_root):
	assert fs.to_client_path(str(fake_root)) == '/Photos'


def test_special_chars_are_encoded_and_round_trip(fake_root):
	# reserved/unsafe chars that are legal in filenames but not in raw URLs
	raw = os.path.join(str(fake_root), 'Tom & Jerry', 'a #1.jpg')
	url = fs.to_client_path(raw)
	# fully percent-encoded — none of these survive literally in the URL
	assert not any(c in url for c in ' &#')
	assert url.split('/')[1] == 'Photos'                 # '/' kept as separator
	# the real pipeline: handle_request unquotes once, then maps to a server path
	assert fs.to_server_path(urllib.parse.unquote(url)) == os.path.abspath(raw)


def test_percent_in_name_is_not_double_decoded(fake_root):
	raw = os.path.join(str(fake_root), '50%41 off')      # literal '%41', not 'A'
	url = fs.to_client_path(raw)
	assert fs.to_server_path(urllib.parse.unquote(url)) == os.path.abspath(raw)


def test_path_outside_any_root_maps_to_slash(tmp_path):
	# the configured root is tmp_path itself; a sibling path is under no root
	outside = tmp_path.parent / 'outside' / 'x.jpg'
	assert fs.to_client_path(str(outside)) == '/'


# ── root containment (path-traversal guard) ──────────────────────────────────

def test_within_roots_allows_files_inside(fake_root):
	assert fs.within_roots(os.path.join(str(fake_root), 'a.jpg'))
	assert fs.within_roots(os.path.join(str(fake_root), 'sub', 'deep.jpg'))


def test_within_roots_allows_virtual_root():
	assert fs.within_roots(fs.VIRTUAL_ROOT)


def test_within_roots_ignores_query_suffix(fake_root):
	# the real-path check must strip ?tn / ?del / ?flag=... before testing
	inside = os.path.join(str(fake_root), 'a.jpg')
	assert fs.within_roots(inside + '?tn')
	assert fs.within_roots(inside + '?flag=pick')


def test_within_roots_rejects_dotdot_escape(fake_root):
	escape = os.path.join(str(fake_root), '..', '..', 'secret.txt')
	assert not fs.within_roots(escape)
	assert not fs.within_roots(escape + '?del')


def test_within_roots_rejects_sibling_dir(tmp_path):
	# configured root is tmp_path; a sibling path is under no root
	assert not fs.within_roots(str(tmp_path.parent / 'outside' / 'x.jpg'))


# ── viewer KIND classification ───────────────────────────────────────────────

@pytest.mark.parametrize('name, kind', [
	('photo.jpg',  fs.KIND_IMAGE),
	('PHOTO.JPG',  fs.KIND_IMAGE),     # case-insensitive
	('shot.cr2',   fs.KIND_IMAGE),     # RAW
	('pic.heic',   fs.KIND_IMAGE),
	('clip.mp4',   fs.KIND_VIDEO),
	('clip.mov',   fs.KIND_VIDEO),
	('doc.pdf',    fs.KIND_PDF),
	#('notes.txt',  fs.KIND_UNVIEWABLE), # supported by the plugin
	('music.mp3',  fs.KIND_UNVIEWABLE),
	('noext',      fs.KIND_UNVIEWABLE),
])
def test_classify(name, kind):
	assert fs.classify(name) == kind


# ── MIME / picture detection ─────────────────────────────────────────────────

def test_is_picture():
	assert fs.is_picture('a.JPG')      # case-insensitive
	assert fs.is_picture('a.cr2')      # RAW extensions are in MIME
	assert not fs.is_picture('a.txt')


def test_raw_extensions_serve_as_jpeg():
	assert fs.MIME['.cr2'] == 'image/jpeg'
	assert fs.MIME['.nef'] == 'image/jpeg'
