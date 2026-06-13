import os
import sys

# The hoard modules use top-level imports (`import filesystem`), so put hoard/
# on the path before importing anything from it. (cwd is handled per-test by the
# hoard_cwd fixture, not here, so pytest's own path resolution stays intact.)
HOARD = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, HOARD)

import pytest
import config


@pytest.fixture(autouse=True)
def hoard_cwd():
	"""Handlers resolve gallery.html / resources / log.txt relative to cwd."""
	prev = os.getcwd()
	os.chdir(HOARD)
	yield
	os.chdir(prev)


@pytest.fixture
def fake_root(tmp_path):
	"""A throwaway media root with one file and one subdirectory."""
	(tmp_path / 'sub').mkdir()
	(tmp_path / 'a.jpg').write_bytes(b'\xff\xd8\xff\xd9')
	return tmp_path


@pytest.fixture(autouse=True)
def inject_config(fake_root):
	"""Replace the cached config singleton with deterministic test values."""
	config.load({
		'roots'                   : [{'name': 'Photos', 'path': str(fake_root)}],
		'address'                 : '0.0.0.0',
		'port'                    : 8000,
		'thumbnailPorts'          : [8001],
		'thumbnailWidthHeight'    : [400, 400],
		'thumbBackgroundColor'    : '#242321',
		'thumbsBusyTimeout'       : 100,
		'thumbsPerSec'            : 30,
		'thumbsRetriesPerSec'     : 60000,
		'allowDelete'             : True,
		'autoPlayTimer'           : 9000,
		'cacheSeconds'            : 100,
		'scrollRateLimitMs'       : 100,
		'streamingChunkBytes'     : 1048576,
		'zoomSpeed'               : 180,
		'videoThumbnailTimeStamps': ['00:00:00.000'],
	})
	yield
	config.cached       = False
	config.config_cache = {}
