import pathlib
import os
import queue
import threading

LOG_FILE      = pathlib.Path(__file__).parent / 'log.txt'
MAX_LOG_BYTES = 5 * 1024 * 1024  # roll over to log.txt.1 once the file passes this

_queue: queue.SimpleQueue[str] = queue.SimpleQueue()


def log(event: str) -> None:
	event = threading.current_thread().name + ' -> ' + event.strip()
	event = event.replace('\r\n', '\n') + '\n'
	event = event.replace('\n\n', '\n')
	_queue.put(event)


def _writer() -> None:
	# keep one handle open (don't reopen per line) and rotate by size so log.txt
	# can't grow without bound
	f = open(LOG_FILE, 'a', encoding='utf-8')
	size = f.tell()
	try:
		while True:
			line = _queue.get()
			f.write(line)
			f.flush()
			size += len(line)
			if size > MAX_LOG_BYTES:
				f.close()
				try:
					os.replace(LOG_FILE, LOG_FILE + '.1')  # atomically overwrites old .1
				except OSError:
					pass
				f = open(LOG_FILE, 'a', encoding='utf-8')
				size = 0
	finally:
		f.close()


threading.Thread(target=_writer, name='Log Writer', daemon=True).start()
