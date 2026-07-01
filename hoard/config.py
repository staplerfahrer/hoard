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


def _ensure_loaded() -> None:
	global cached, config_cache
	if not cached:
		with open('config.json', 'r') as f:
			config_cache = json.load(f)
		cached = True


def config(name: str) -> Any:
	try:
		_ensure_loaded()
		return config_cache[name]
	except:
		log(traceback.format_exc())
		raise


def config_get(name: str, default: Any = None) -> Any:
	"""Like config() but returns `default` when the key is absent — no raise, no log.
	For optional keys that older config.json files may not have."""
	try:
		_ensure_loaded()
	except:
		log(traceback.format_exc())
		raise
	return config_cache.get(name, default)


def load(values: dict[str, Any]) -> None:
	"""Inject a config dict directly, bypassing config.json. Intended for tests."""
	global cached, config_cache
	config_cache = values
	cached       = True
