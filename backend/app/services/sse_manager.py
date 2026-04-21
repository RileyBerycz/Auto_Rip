from __future__ import annotations

import json
import queue
import threading
from typing import Dict, List


class SSEManager:
    def __init__(self):
        self.clients: Dict[str, queue.Queue] = {}
        self.lock = threading.Lock()

    def add_client(self, client_id: str) -> queue.Queue:
        with self.lock:
            q = queue.Queue()
            self.clients[client_id] = q
            return q

    def remove_client(self, client_id: str):
        with self.lock:
            self.clients.pop(client_id, None)

    def emit(self, event: str, payload: dict, room: str = None):
        message = f"event: {event}\ndata: {json.dumps(payload)}\n\n"
        with self.lock:
            clients_to_emit = [self.clients[cid] for cid in self.clients if not room or cid == room]
            for q in clients_to_emit:
                try:
                    q.put(message, block=False)
                except queue.Full:
                    pass  # Skip if queue full

    def generate_events(self, client_id: str):
        q = self.clients.get(client_id)
        if not q:
            return
        try:
            while True:
                yield q.get(timeout=30)  # Timeout to keep connection alive
        except queue.Empty:
            yield "data: keepalive\n\n"
        except GeneratorExit:
            self.remove_client(client_id)