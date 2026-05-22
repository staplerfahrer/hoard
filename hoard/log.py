import threading
import queue

_queue: queue.SimpleQueue[str] = queue.SimpleQueue()


def log(event: str) -> None:
	event = threading.current_thread().name + ' -> ' + event.strip()
	event = event.replace('\r\n', '\n') + '\n'
	event = event.replace('\n\n', '\n')
	_queue.put(event)


def _writer() -> None:
	while True:
		with open('log.txt', 'a') as f:
			f.write(_queue.get())


threading.Thread(target=_writer, name='Log Writer', daemon=True).start()
