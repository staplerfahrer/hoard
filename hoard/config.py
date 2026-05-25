from log import log
from typing import Any
import json
import sys
import traceback

WINDOWS = sys.platform == 'win32'
MACOS   = sys.platform == 'darwin'
LINUX   = sys.platform.startswith('linux')


cached = False
config_cache: dict[str, Any] = {}


def config(name: str) -> Any:
	global cached, config_cache

	try:
		if not cached:
			with open('config.json', 'r') as f:
				config_cache = json.load(f)
			cached = True

		return config_cache[name]
	except:
		log(traceback.format_exc())
		raise
