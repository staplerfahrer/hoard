"""Render-plugin discovery.

Plugins are standalone .py files in the `plugins/` directory, each named after
the file type it handles (e.g. `text.py`, `excel.py`). Every plugin module must
expose three callables:

    match_extensions() -> Iterable[str]
        Lowercase extensions (including the dot) the plugin claims, e.g.
        ('.txt', '.log').

    render(server_path: str) -> tuple[bytes, str]
        Full-view render: (image_bytes, mime). Returned verbatim to the
        browser <img>, so the mime must be an image type.

    render_thumbnail(server_path: str, size: tuple[int, int]) -> bytes
        A PIL-openable preview image (e.g. PNG bytes). It is fed into
        handle_thumbnail's existing resize/letterbox/label pipeline, so it
        need not be pre-sized — `size` is the thumbnail canvas, advisory.

Plugins are consulted *before* the built-in handlers (see filesystem.classify,
handle_file.run, handle_thumbnail.run), so a plugin can override a built-in
type. v1 plugins are assumed to produce still images (KIND_IMAGE).

Discovery is lazy and cached: the directory is scanned and the modules imported
on first use. Use Ctrl+R to reload after adding or editing a plugin.
"""
import importlib.util
import os
import threading
import traceback

from log import log

PLUGIN_DIR = 'plugins'
_REQUIRED  = ('match_extensions', 'render', 'render_thumbnail')

# extension (lowercase, incl. dot) -> loaded plugin module
_registry: dict | None = None
_lock = threading.Lock()


def _load() -> dict:
	global _registry
	if _registry is not None:
		return _registry
	with _lock:
		if _registry is not None:  # another thread won the race
			return _registry
		registry: dict = {}
		if os.path.isdir(PLUGIN_DIR):
			for entry in sorted(os.scandir(PLUGIN_DIR), key=lambda e: e.name):
				if not entry.is_file() or entry.name.startswith('_') or not entry.name.endswith('.py'):
					continue
				mod = _import_file(entry.path)
				if mod is None:
					continue
				try:
					exts = tuple(mod.match_extensions())
				except Exception:
					log(f'plugin {entry.name}: match_extensions() failed {traceback.format_exc()}')
					continue
				for ext in exts:
					ext = ext.lower()
					if ext in registry:
						log(f'plugin {entry.name}: {ext} already handled by '
							f'{registry[ext].__name__}, overriding')
					registry[ext] = mod
				log(f'plugin loaded: {entry.name} -> {exts}')
		_registry = registry
		return _registry


def _import_file(path: str):
	name = os.path.basename(path)
	try:
		spec = importlib.util.spec_from_file_location(f'hoard_plugin_{name[:-3]}', path)
		if spec is None or spec.loader is None:
			return None
		mod = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(mod)
	except Exception:
		log(f'plugin {name}: import failed {traceback.format_exc()}')
		return None
	missing = [fn for fn in _REQUIRED if not callable(getattr(mod, fn, None))]
	if missing:
		log(f'plugin {name}: missing required function(s) {missing}, skipped')
		return None
	return mod


def plugin_for(server_path: str):
	"""Return the plugin module that handles this file, or None."""
	ext = os.path.splitext(server_path)[1].lower()
	return _load().get(ext)


def handles(ext: str) -> bool:
	"""True if some plugin claims this extension (incl. leading dot)."""
	return ext.lower() in _load()


def extensions() -> frozenset:
	"""All extensions claimed by plugins."""
	return frozenset(_load().keys())
