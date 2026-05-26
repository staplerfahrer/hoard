from collections import deque
from shutil import get_terminal_size
from socket import create_server, socket
from time import sleep, perf_counter
import os
import sys
import threading
import time
import traceback
import webbrowser

from config import config, WINDOWS
from log import log
import handle_request
import stats

THREAD_COUNT = 30
# TODO: MRU in cookie
# TODO: fix video player full-screen
# TODO: fix video player keyboard seek

# The thumbnails for every image are already loaded in the browser cache — addImg loaded them to build the gallery. In
#   updateViewed, instead of immediately hiding vi while the full-res fetches, we could set vi.src to the thumbnail URL
#   first (instant, from cache), then load the full-res in a background Image object and swap it in when ready.

#   The one complication: vi.onload = zoomStyle uses vi.naturalWidth/Height for the zoom animation, so we'd need to
#   suppress it for the thumbnail swap and only let it fire for the full-res. A simple boolean flag handles that.

#   A secondary win while we're there: cacheNext only pre-caches forward (+1 to +10) with a 2-second delay — ArrowLeft is
#   never pre-cached, and the delay means ArrowRight only benefits if you paused. Reducing that delay to ~100ms and adding
#    one step backward would help a lot too.

queue            : deque[tuple[socket, str]] = deque()
thumbnail_queue  : deque[tuple[socket, str]] = deque()
busy_thread_count: int                       = 0
busy_thread_lock : threading.Lock            = threading.Lock()


def check_dependencies():
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


def main():
	try:
		os.system('cls' if WINDOWS else 'clear')
		check_dependencies()
		if config('autoStart'):
			webbrowser.open(f'http://{config("address")}:{config("port")}')

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
		serv.settimeout(1)
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
		except:
			log(f'thread_worker() exception {traceback.format_exc()}')


# MARK: server UI
def ui():
	# hotkey daemon
	threading.Thread(
		target=hotkey_listener,
		name='Hotkey Listener',
		daemon=True).start()

	sec_per_frame = 1 / 60
	last_rq = 0
	req_sec_avg = 0
	while True:
		sleep(sec_per_frame)
		cols  = get_terminal_size().columns - 1
		title = f' hoard Media Gallery serving at http://{config("address")}:{config("port")} '
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
			f'\r\033[K{request_queue:>4} queue   {"Q" * min(request_queue, cols - 20)}\n'
			f'\r\033[K{busy_workers :>4} workers {"W" * min(busy_workers, cols - 20)}\n'
			f'\r\033[K{stats_line}\n'
		)
		sys.stdout.write(f'\033[{content.count(chr(10))}A' + content)
		sys.stdout.flush()


def hotkey_listener():
	if WINDOWS:
		import msvcrt
		while True:
			sleep(0.05)
			if not msvcrt.kbhit():
				continue
			ch = msvcrt.getwch()
			if ch == '\x12':  # Ctrl+R
				log('Restarting...')
				os.execv(sys.executable, [sys.executable] + sys.argv)
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
			pass
		finally:
			termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)              # type: ignore


if __name__ == '__main__':
	main()
