from time import perf_counter
import functools
import json
import os
import re

from config import config, WINDOWS
from log import log
import filesystem as fs

if WINDOWS:
    import ctypes
    _StrCmpLogicalW          = ctypes.windll.shlwapi.StrCmpLogicalW
    _StrCmpLogicalW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    _StrCmpLogicalW.restype  = ctypes.c_int
    _sort_key                = functools.cmp_to_key(_StrCmpLogicalW)
else:
    def _natural_sort_key(path: str):
        parts = re.split(r'(\d+)', os.path.basename(path).lower())
        return [int(p) if p.isdigit() else p for p in parts]
    _sort_key = _natural_sort_key

BLOCK_LIST = [r'thumbs.db$', r'.deleted$', r'\.xmp$', r'desktop\.ini$', r'\.mylock_', r'\.lnk$']

def run(server_path: str, recursive: bool = False) -> tuple[bytes, str]:
	t = perf_counter()
	def tick(label: str):
		nonlocal t
		now = perf_counter()
		log(f'  {label:<20} {(now - t)*1000: >6.1f} ms')
		t = now

	all_roots      = fs.roots()                      # [(name, abs_path), ...]
	all_root_paths = [p for _, p in all_roots]

	# ── Case 1: virtual root "/" ─────────────────────────────────────────────
	if server_path == fs.VIRTUAL_ROOT:
		client_children = [fs.to_client_path(p) for _, p in all_roots]
		img_urls        = []
		kinds           = ''
		client_siblings = []
		tick('virtual root')

	else:
		# ── security: stay within configured roots ───────────────────────────
		req_obj = os.path.abspath(server_path)
		in_any_root = any(
			req_obj == rp or req_obj.startswith(rp + os.sep)
			for rp in all_root_paths
		)
		if not in_any_root:
			return run(fs.VIRTUAL_ROOT)
		tick('abspath/security')

		# scan current directory
		with os.scandir(req_obj) as itr:
			objs = [o for o in itr if not _is_blocked(o.path)]
		tick('scandir')

		children_list   = sorted([o.path for o in objs if o.is_dir()], key=_sort_key)
		if recursive:
			# all files under req_obj, grouped by folder, naturally sorted within each
			file_list   = _walk_files(req_obj)
		else:
			file_list   = sorted([o.path for o in objs if o.is_file()], key=_sort_key)
		tick('children/files')

		# children always have '..' (parent is real dir or virtual root)
		client_children = ['..'] + [fs.to_client_path(d) for d in children_list]
		img_urls        = [fs.to_client_path(f) for f in file_list]
		# one char per file (same order as img_urls): viewer KIND_* code
		kinds           = ''.join(str(fs.classify(f)) for f in file_list)
		tick('client_children/imgUrls')

		# ── Case 2: at a configured root dir — siblings = other roots ────────
		if req_obj in all_root_paths:
			client_siblings = ['..'] + [
				fs.to_client_path(p) for _, p in all_roots
			]

		# ── Case 3: normal subdir — scan real parent ─────────────────────────
		else:
			parent = os.path.abspath(os.path.join(req_obj, '..'))
			with os.scandir(parent) as parent_itr:
				client_siblings = ['..'] + [
					fs.to_client_path(e.path)
					for e in sorted(parent_itr, key=lambda e: _sort_key(e.path))
					if e.is_dir() and not _is_blocked(e.path)
				]

		tick('client_siblings')

	# produce HTML
	gallery_html = fs.read_file_bytes('gallery.html')[0]
	tick('read gallery_html')

	thumbnail_html = fs.read_file_bytes('thumbnail.html')[0]
	tick('read thumbnail_html')
	data = (gallery_html
		.replace(b'{thumbnailHtml}', thumbnail_html)
		.replace(b'{thumbnailPorts}', bytes(json.dumps(config('thumbnailPorts')), 'utf-8'))
		.replace(b'{thumbnailWidthHeight}', bytes(json.dumps(config('thumbnailWidthHeight')), 'utf-8'))
		)

	data = (data
		.replace(b'{allowDelete}', b'true' if config('allowDelete') else b'false')
		.replace(b'{displayUnrenderables}', b'true' if config('displayUnrenderables') else b'false')
		.replace(b'{preferAltNavigation}', b'true' if config('preferAltNavigation') else b'false')
		.replace(b'{recursive}', b'true' if recursive else b'false')
		.replace(b'{autoPlayTimer}', bytes(str(config('autoPlayTimer')), 'utf-8'))
		.replace(b'{dirUrls}', bytes(json.dumps(client_children), 'utf-8'))
		.replace(b'{imgUrls}', bytes(json.dumps(img_urls), 'utf-8'))
		.replace(b'{kinds}', bytes(json.dumps(kinds), 'utf-8'))
		.replace(b'{scrollRateLimitMs}', bytes(str(config('scrollRateLimitMs')), 'utf-8'))
		.replace(b'{siblingUrls}', bytes(json.dumps(client_siblings), 'utf-8'))
		.replace(b'{zoomSpeed}', bytes(config('zoomSpeed'), 'utf-8'))
		)
	tick('template')
	return data, 'text/html'


# def _natural_key(path: str):
# 	parts = re.split(r'(\d+)', os.path.basename(path).lower())
# 	return [int(p) if p.isdigit() else p for p in parts]


def _walk_files(root: str) -> list[str]:
	"""All non-blocked files under root, grouped by folder, naturally sorted.

	Subdirectories are pruned in place so blocked subtrees (.deleted, etc.) are
	not descended; symlinks are not followed (os.walk default), so no loops.
	"""
	files: list[str] = []
	for dirpath, dirnames, filenames in os.walk(root):
		dirnames[:] = sorted(
			(d for d in dirnames if not _is_blocked(os.path.join(dirpath, d))),
			key=_sort_key)
		for name in sorted(filenames, key=_sort_key):
			full = os.path.join(dirpath, name)
			if not _is_blocked(full):
				files.append(full)
	return files


def _is_blocked(path: str):
	for p in BLOCK_LIST:
		if re.search(p, path, re.IGNORECASE):
			return True
