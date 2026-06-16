from typing import Any, Tuple
import os

from log import log


RESOURCE_MIMES: dict[str, str] = {
	'.svg': 'image/svg+xml',
	'.png': 'image/png',
	'.css': 'text/css',
	'.js' : 'text/javascript',
}

# resource_cache: dict[str, Tuple[bytes, str]] = {}

MAX_RESOURCE_BYTES = 50 * 1024 * 1024  # generous cap; resources are small static assets


def resource(name: str) -> Any:
	# global resource_cache

	# if not resource_cache.keys():
	# 	for info in os.scandir('resources'):
	# 		if not info.is_file():
	# 			continue
	# 		res_path = f'/{info.name}'
	# 		res_ext = os.path.splitext(res_path)[1]
	# 		mime = RESOURCE_MIMES.get(res_ext, 'text/plain')
	# 		with open(info.path, 'rb') as f:
	# 			resource_cache[res_path] = (
	# 				f.read(MAX_RESOURCE_BYTES),
	# 				mime)

	# return resource_cache.get(name, None)

	# todo: remove the loop
	for info in os.scandir('resources'):
		if not info.is_file():
			continue
		res_path = f'/{info.name}'
		if name != res_path:
			continue
		res_ext = os.path.splitext(res_path)[1]
		mime = RESOURCE_MIMES.get(res_ext, 'text/plain')
		with open(info.path, 'rb') as f:
			return (
				f.read(MAX_RESOURCE_BYTES),
				mime)
