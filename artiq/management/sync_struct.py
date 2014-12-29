import asyncio

from artiq.management import pyon
from artiq.management.tools import AsyncioServer


_init_string = b"ARTIQ sync_struct\n"


class Subscriber:
    def __init__(self, target_builder, notify_cb=None):
        self.target_builder = target_builder
        self.notify_cb = notify_cb

    @asyncio.coroutine
    def connect(self, host, port):
        self._reader, self._writer = \
            yield from asyncio.open_connection(host, port)
        try:
            self._writer.write(_init_string)
            self.receive_task = asyncio.Task(self._receive_cr())
        except:
            self._writer.close()
            del self._reader
            del self._writer
            raise

    @asyncio.coroutine
    def close(self):
        try:
            self.receive_task.cancel()
            try:
                yield from asyncio.wait_for(self.receive_task, None)
            except asyncio.CancelledError:
                pass
        finally:
            self._writer.close()
            del self._reader
            del self._writer

    @asyncio.coroutine
    def _receive_cr(self):
        target = None
        while True:
            line = yield from self._reader.readline()
            if not line:
                return
            obj = pyon.decode(line.decode())
            action = obj["action"]

            if action == "init":
                target = self.target_builder(obj["struct"])
            elif action == "append":
                target.append(obj["x"])
            elif action == "insert":
                target.insert(obj["i"], obj["x"])
            elif action == "pop":
                target.pop(obj["i"])
            elif action == "delitem":
                target.__delitem__(obj["key"])
            if self.notify_cb is not None:
                self.notify_cb()


class Notifier:
    def __init__(self, backing_struct):
        self.backing_struct = backing_struct
        self.publisher = None

    # Backing struct modification methods.
    # All modifications must go through them!

    def append(self, x):
        self.backing_struct.append(x)
        if self.publisher is not None:
            self.publisher.publish({"action": "append", "x": x})

    def insert(self, i, x):
        self.backing_struct.insert(i, x)
        if self.publisher is not None:
            self.publisher.publish({"action": "insert", "i": i, "x": x})

    def pop(self, i=-1):
        r = self.backing_struct.pop(i)
        if self.publisher is not None:
            self.publisher.publish({"action": "pop", "i": i})
        return r

    def __delitem__(self, key):
        self.backing_struct.__delitem__(key)
        if self.publisher is not None:
            self.publisher.publish({"action": "delitem", "key": key})


class Publisher(AsyncioServer):
    def __init__(self, notifier):
        AsyncioServer.__init__(self)
        self.notifier = notifier
        self._recipients = set()

        self.notifier.publisher = self

    @asyncio.coroutine
    def _handle_connection_cr(self, reader, writer):
        try:
            line = yield from reader.readline()
            if line != _init_string:
                return

            obj = {"action": "init", "struct": self.notifier.backing_struct}
            line = pyon.encode(obj) + "\n"
            writer.write(line.encode())

            queue = asyncio.Queue()
            self._recipients.add(queue)
            try:
                while True:
                    line = yield from queue.get()
                    writer.write(line)
                    # raise exception on connection error
                    yield from writer.drain()
            finally:
                self._recipients.remove(queue)
        except ConnectionResetError:
            # subscribers disconnecting are a normal occurence
            pass
        finally:
            writer.close()

    def publish(self, obj):
        line = pyon.encode(obj) + "\n"
        line = line.encode()
        for recipient in self._recipients:
            recipient.put_nowait(line)