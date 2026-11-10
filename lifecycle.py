"""Stop scanning cooperatively and finish in-flight file operations before exit."""
import os
import threading


class Lifecycle:
    def __init__(self, inventory, parent_pid=0):
        self.inventory = inventory
        self.parent_pid = parent_pid
        self.closing = threading.Event()
        self.server = None

    def attach(self, server):
        self.server = server
        if self.parent_pid:
            threading.Thread(target=self._watch_parent, daemon=True).start()

    def request_exit(self):
        if self.closing.is_set():
            return
        self.closing.set()
        self.inventory.cancel()
        threading.Thread(target=self._finish, daemon=True).start()

    def _finish(self):
        # Closing a window must not interrupt a move, an undo, or a permanent delete.
        # A read-only scanner may be blocked inside a macOS permission request.
        # It is a daemon thread, so it must not hold the whole app open forever.
        worker = getattr(self.inventory, 'worker', None)
        if worker is not None and worker.is_alive():
            worker.join(timeout=2)
        stalled_read_only_scan = (worker is not None and worker.is_alive() and
                                  getattr(self.inventory, 'progress', {}).get('running', False))
        if not stalled_read_only_scan:
            with self.inventory.operation_lock:
                pass
        if self.server:
            self.server.shutdown()

    def _watch_parent(self):
        while not self.closing.wait(1):
            # A native parent disappearing re-parents us to launchd.
            if os.getppid() != self.parent_pid:
                self.request_exit()
                return
