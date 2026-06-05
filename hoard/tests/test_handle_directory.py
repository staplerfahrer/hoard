import pytest

import handle_directory as hd


@pytest.mark.parametrize('path', [
	'C:/lib/Thumbs.db',
	'C:/lib/photo.deleted',
	'C:/lib/sidecar.xmp',
	'C:/lib/desktop.ini',
	'C:/lib/shortcut.lnk',
	'C:/lib/.mylock_123',
	'C:/lib/notes.txt',          # hoard-managed flags/metadata file
])
def test_is_blocked_true(path):
	assert hd._is_blocked(path)


@pytest.mark.parametrize('path', [
	'C:/lib/a.jpg',
	'C:/lib/movie.mp4',
	'C:/lib/release-notes.txt',  # only an exact 'notes.txt' is blocked
	'C:/lib/raw.cr2',
])
def test_is_blocked_false(path):
	assert not hd._is_blocked(path)
