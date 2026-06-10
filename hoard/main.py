from collections import deque
from shutil import get_terminal_size
from socket import create_server, socket, getaddrinfo, gethostname, AF_INET, SOCK_DGRAM
from time import sleep, perf_counter
import os
import sys
import threading
import time
import traceback
import warnings
import webbrowser

from pillow_heif import register_heif_opener # type: ignore
register_heif_opener()

from config import config, WINDOWS
from log import log
import handle_request
import stats

# TODO: index all file names in the library on startup (walk the root dirs, store
#       relative paths in a list/trie) and expose a search endpoint; add a search
#       box to the gallery UI that queries it and navigates to matches.
# TODO: store other user-generated metadata (notes, ratings, etc.) alongside flags
#       in the per-directory notes.txt; create/update it only when present.
# TODO: manual zoom (scroll wheel / pinch) and drag-to-pan for the image viewer.
# TODO: allow renaming of images from the viewer UI; expose a rename endpoint.
# TODO: allow moving images to another directory from the viewer UI; expose a move endpoint.
# TODO: allow setting a password on specific directories; prompt for it on first access and store auth in a session cookie.
# TODO: create a set of mask images for common aspect ratios (1:1, 4:3, 16:9, 3:2, etc.) and apply them as CSS mask-image on thumbnails to soften edges.
# TODO: fix pixel dimensions reported for RAW files (currently reads dcraw output dimensions, which may reflect the thumbnail rather than the full sensor resolution).
# TODO: virtualize the thumbnail grid for large galleries (e.g. 50k files) — only keep DOM <img> nodes for the visible window plus a buffer, recycling nodes on scroll, so memory stays bounded regardless of directory size.
# TODO: let the user toggle displayUnrenderables from the gallery UI (a key/button that shows/hides unrenderable files live, instead of only via config.json + restart).
# TODO: MRU in cookie
# TODO: fix video player full-screen
# TODO: fix video player keyboard seek
# TODO: fix video hotkeys (keyboard controls are wildly inconsistent)
# TODO: when switching to full screen, maybe show thumbnail until the large image has loaded, or some busy indicator
# TODO: clicking video while full-screen should pause it

THREAD_COUNT = 30

queue            : deque[tuple[socket, str]] = deque()
thumbnail_queue  : deque[tuple[socket, str]] = deque()
busy_thread_count: int                       = 0
busy_thread_lock : threading.Lock            = threading.Lock()


def main():
	try:
		threading.excepthook = _log_thread_exception
		warnings.showwarning = _log_warning
		_validate_config()
		os.system('cls' if WINDOWS else 'clear')
		_check_dependencies()
		if config('autoStart'):
			webbrowser.open(_server_urls()[0])

		# UI thread
		threading.Thread(
			target=ui,
			name='UI',
			daemon=True).start()

		# thumbnail threads
		for port in config('thumbnailPorts'):
			threading.Thread(
				target=listen,
				args=(config('address'), port),
				name=f'Thumbnail Listener {config("address")}:{port}',
				daemon=True).start()

		workers = [threading.Thread(
			target=thread_worker,
			name=f'Worker Thread {i}')
			for i in range(THREAD_COUNT)]
		[t.start() for t in workers]
		listen(config('address'), config('port'))
		[t.join() for t in workers]
	except KeyboardInterrupt:
		log('KeyboardInterrupt')
		os._exit(0)
	except Exception:
		log(f'main() exception {traceback.format_exc()}')


def listen(address: str, port: int):
	# https://docs.python.org/3/library/socket.html
	with create_server((address, port)) as serv:
		# timeout because browsers may start blocking, empty request connections
		serv.settimeout(10)
		log(f'Listen...{serv} timeout {serv.timeout}')
		while True:
			try:
				conn, addr = serv.accept()
				log(f'Connected...{addr}')
				# https://stackoverflow.com/questions/20289981/python-sockets-stop-recv-from-hanging
				req = str(conn.recv(1_048_576), 'utf-8')
				if req == '':
					continue
				if '?tn HTTP/1.1' in req:
					thumbnail_queue.append((conn, req))
				else:
					queue.append((conn, req))
			except TimeoutError:
				# timeout is essential, see above
				pass
			except KeyboardInterrupt:
				log('KeyboardInterrupt')
				os._exit(0)
			except Exception:
				log(traceback.format_exc())


def thread_worker():
	global busy_thread_count
	while True:
		try:
			sleep(0.01)
			if not len(queue) and not len(thumbnail_queue):
				continue

			with busy_thread_lock:
				busy_thread_count += 1

			start_time = perf_counter()

			try:
				conn, req = queue.popleft()
			except IndexError:
				conn, req = thumbnail_queue.popleft()

			first_line = req.split('\r\n', 1)[0]
			if first_line.startswith('GET ') and first_line.endswith(' HTTP/1.1'):
				log('Popping get ' + first_line[4:-9])
			else:
				log('Popping job ' + req.replace('\r\n', '\\n'))

			bytes_ = handle_request.build_response_bytes(req)
			log(f'{len(bytes_)} bytes')
			conn.sendall(bytes_)
			conn.close()

			elapsed = perf_counter() - start_time
			with stats.lock:
				stats.bytes_served      += len(bytes_)
				stats.processing_time   += elapsed
				stats.requests_served   += 1
				if '?tn HTTP/1.1' in req:
					stats.thumbnails_served += 1

			log(f'Finished in {elapsed:.3f} s')

			with busy_thread_lock:
				busy_thread_count -= 1
		except Exception:
			log(f'thread_worker() exception {traceback.format_exc()}')


# MARK: server UI
def ui():
	# hotkey daemon
	threading.Thread(
		target=_hotkey_listener,
		name='Hotkey Listener',
		daemon=True).start()

	sec_per_frame = 1 / 60
	last_rq = 0
	req_sec_avg = 0
	urls = _server_urls()
	# when bound to all interfaces, list every reachable URL; the title shows the primary one
	addresses_line = '' if len(urls) <= 1 else 'Reachable at  ' + '   '.join(urls) + '\n'
	while True:
		try:
			sleep(sec_per_frame)
			cols  = get_terminal_size().columns - 1
			title = f' hoard Media Gallery serving at {urls[0]} '
			pad   = (cols - len(title)) // 2
			title = f'{"=" * pad}{title}{"=" * pad}'
			request_queue = len(queue) + len(thumbnail_queue)
			with busy_thread_lock:
				busy_workers = busy_thread_count
			with stats.lock:
				tn  = stats.thumbnails_served
				b   = stats.bytes_served
				pt  = stats.processing_time
				rq  = stats.requests_served
			req_sec = (rq - last_rq) / sec_per_frame
			req_sec_avg = req_sec * 0.005 + req_sec_avg * 0.995
			last_rq = rq
			stats_line = f'{tn:,} tn  {b:,} B  {pt:.1f} s  {req_sec_avg:.0f} req/s'
			content = (
				f'{title}\n'
				f'Press <CTRL+C> to quit, <CTRL+R> to restart.\n'
				f'{addresses_line}'
				f'\r\033[K{request_queue:>4} queue   {"Q" * min(request_queue, cols - 20)}\n'
				f'\r\033[K{busy_workers :>4} workers {"W" * min(busy_workers, cols - 20)}\n'
				f'\r\033[K{stats_line}\n'
			)
			sys.stdout.write(f'\033[{content.count(chr(10))}A' + content)
			sys.stdout.flush()
		except Exception:
			# log to file (not stderr — this loop would overwrite it) and keep going
			log(f'ui() exception {traceback.format_exc()}')
			sleep(1)  # don't spin a tight error loop hammering the log


def _hotkey_listener():
	if WINDOWS:
		import msvcrt
		while True:
			try:
				sleep(0.05)
				if not msvcrt.kbhit():
					continue
				ch = msvcrt.getwch()
				if ch == '\x12':  # Ctrl+R
					log('Restarting...')
					os.execv(sys.executable, [sys.executable] + sys.argv)
			except Exception:
				log(f'_hotkey_listener() exception {traceback.format_exc()}')
	else:
		if not sys.stdin.isatty():
			return
		import tty, termios, select as _select
		fd           = sys.stdin.fileno()
		old_settings = termios.tcgetattr(fd)                                    # type: ignore
		try:
			tty.setraw(fd)                                                      # type: ignore
			while True:
				ready, _, _ = _select.select([sys.stdin], [], [], 0.05)
				if ready:
					ch = sys.stdin.read(1)
					if ch == '\x12':  # Ctrl+R
						termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore
						log('Restarting...')
						os.execv(sys.executable, [sys.executable] + sys.argv)
		except Exception:
			log(f'_hotkey_listener() exception {traceback.format_exc()}')
		finally:
			termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)              # type: ignore


def _server_urls() -> list[str]:
	"""Client-reachable http URLs for the configured bind address."""
	address = config('address')
	port    = config('port')
	if address in ('0.0.0.0', '::', ''):
		hosts = _local_ip_addresses() or ['127.0.0.1']
	else:
		hosts = [address]
	return [f'http://{h}:{port}' for h in hosts]


def _local_ip_addresses() -> list[str]:
	"""Best-effort list of this machine's LAN IPv4 addresses (for 0.0.0.0 binds)."""
	ips: list[str] = []
	# primary outbound IP — the one LAN clients are most likely to reach us on.
	# Connecting a UDP socket sends no packets; it just selects the default route.
	try:
		with socket(AF_INET, SOCK_DGRAM) as s:
			s.connect(('8.8.8.8', 80))
			ips.append(s.getsockname()[0])
	except Exception:
		pass
	# any other IPv4 addresses bound to this host
	try:
		for info in getaddrinfo(gethostname(), None, AF_INET):
			ip = info[4][0]
			if ip not in ips:
				ips.append(ip) # type: ignore
	except Exception:
		pass
	return ips


def _validate_config():
	"""Fail fast with a clear message if config.json is missing or malformed,
	instead of surfacing cryptic errors mid-request later."""
	required = ['address', 'port', 'roots', 'thumbnailPorts', 'thumbnailWidthHeight',
				'thumbBackgroundColor', 'cacheSeconds', 'streamingChunkBytes']
	for key in required:
		try:
			config(key)
		except Exception:
			raise SystemExit(f'config.json: missing required key "{key}". '
							 'Copy config.json.example to config.json and edit it.')

	roots = config('roots')
	if not isinstance(roots, list) or not roots:
		raise SystemExit('config.json: "roots" must be a non-empty list of {name, path}.')
	for r in roots:
		if not isinstance(r, dict) or 'name' not in r or 'path' not in r:
			raise SystemExit('config.json: each entry in "roots" needs a "name" and a "path".')
		if not os.path.isdir(r['path']):
			print(f'Warning: root "{r.get("name")}" path does not exist: {r["path"]}')


def _check_dependencies():
	deps = {
		'dcraw.exe': 'https://github.com/ncruces/dcraw/releases or https://www.dechifro.org/dcraw/',
	}
	show_message = False
	for exe, url in deps.items():
		if not os.path.isfile(os.path.join('resources', exe)):
			print(f'Missing optional program {exe}\n'
				f'Download it from {url} and place it in the resources folder.\n'
				'Waiting 10 seconds...')
			show_message = True

	if show_message:
		time.sleep(10)
		os.system('cls' if WINDOWS else 'clear')


def _log_thread_exception(args: threading.ExceptHookArgs) -> None:
	"""Send uncaught exceptions from any thread to the log file.

	The default hook prints them to stderr, where the ui() repaint (cursor-up +
	rewrite at 60fps) overwrites them — so they flash on the terminal and are lost.
	Routing them to log.txt makes them readable after the fact.
	"""
	if issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
		return
	tb = ''.join(traceback.format_exception(
		args.exc_type, args.exc_value, args.exc_traceback))
	name = args.thread.name if args.thread else '<unknown>'
	log(f'Uncaught exception in thread {name}:\n{tb}')


def _log_warning(message, category, filename, lineno, file=None, line=None) -> None:
	"""Route Python warnings (e.g. from Pillow) to the log file, not stderr.

	Warnings aren't exceptions, so the per-request try/except never sees them and
	the default handler prints them straight to the terminal. This applies process-
	wide (all threads) once installed.
	"""
	log(f'{category.__name__}: {message} ({os.path.basename(filename)}:{lineno})')


if __name__ == '__main__':
	main()
