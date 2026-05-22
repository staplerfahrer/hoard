from typing import Any, Tuple
import os

from log import log


RESOURCE_MIMES: dict[str, str] = {
	'.svg': 'image/svg+xml',
	'.png': 'image/png',
	'.css': 'text/css',
}

resource_cache: dict[str, Tuple[bytes, str]] = {}


def resource(name: str) -> Any:
	global resource_cache

	if not resource_cache.keys():
		for info in os.scandir('resources'):
			if not info.is_file():
				continue
			res_path = f'/{info.name}'
			res_ext = os.path.splitext(res_path)[1]
			mime = RESOURCE_MIMES.get(res_ext, 'text/plain')
			with open(info.path, 'rb') as f:
				resource_cache[res_path] = (
					f.read(10 * 1_048_476),
					mime)

	return resource_cache.get(name, None)
