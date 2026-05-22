from time import perf_counter
import ctypes
import functools
import json
import os
import re

_StrCmpLogicalW          = ctypes.windll.shlwapi.StrCmpLogicalW
_StrCmpLogicalW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_StrCmpLogicalW.restype  = ctypes.c_int
windows_sort_key         = functools.cmp_to_key(_StrCmpLogicalW)

from config import config
from log import log
import filesystem as fs

BLOCK_LIST = [r'thumbs.db$', r'.deleted$', r'\.xmp$', r'desktop\.ini$', r'\.mylock_', r'\.lnk$']

def run(server_path: str) -> tuple[bytes, str]:
	t = perf_counter()
	def tick(label: str):
		nonlocal t
		now = perf_counter()
		log(f'  {label:<20} {(now - t)*1000: >6.1f} ms')
		t = now

	# todo: for siblings and children, count the entries:
	# len(os.listdir(path))

	# discover directories & files
	root    = config('root')
	req_obj = os.path.abspath(server_path)
	if not (req_obj == root or req_obj.startswith(root + os.sep)):
		req_obj = root
	is_root = req_obj == root
	parent_path = [os.path.abspath(os.path.join(req_obj, '..'))] if not is_root else []
	tick('abspath/isRoot')

	with os.scandir(req_obj) as itr:
		objs = list(itr)
	tick('scandir')

	objs = [o for o in objs if not _is_blocked(o.path)]

	children_list = [os.path.join(req_obj, d.name) for d in objs if d.is_dir()]
	tick('children_list')

	file_list   = [os.path.join(req_obj, f.name) for f in objs if f.is_file()]
	tick('file_list')

	server_children = sorted(children_list, key=windows_sort_key)
	tick('server_children')
	client_children = [fs.to_client_path(d) for d in server_children]
	if not is_root:
		client_children = ['..'] + client_children
	tick('client_children')

	img_urls = [fs.to_client_path(f) for f in sorted(file_list, key=windows_sort_key)]
	tick('imgUrls')

	client_siblings: list[str] = []
	if not is_root:
		with os.scandir(parent_path[0]) as parent_itr:
			client_siblings = ['..'] + [fs.to_client_path(e.path) for e in sorted(parent_itr, key=lambda e: windows_sort_key(e.path)) if e.is_dir()]
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
		.replace(b'{autoPlayTimer}', bytes(str(config('autoPlayTimer')), 'utf-8'))
		.replace(b'{dirUrls}', bytes(json.dumps(client_children), 'utf-8'))
		.replace(b'{imgUrls}', bytes(json.dumps(img_urls), 'utf-8'))
		.replace(b'{siblingUrls}', bytes(json.dumps(client_siblings), 'utf-8'))
		.replace(b'{zoomSpeed}', bytes(config('zoomSpeed'), 'utf-8'))
		)
	tick('template')
	return data, 'text/html'


# def _natural_key(path: str):
# 	parts = re.split(r'(\d+)', os.path.basename(path).lower())
# 	return [int(p) if p.isdigit() else p for p in parts]


def _is_blocked(path: str):
	for p in BLOCK_LIST:
		if re.search(p, path, re.IGNORECASE):
			return True
