# 
# Webapp to display game logs. 
# You DON'T NEED to run this, it will be automatically started by game_leader.py
# You can use it, though, to replay a game or test your player without running the game leader.
#
from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import logging
import threading
import time
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, request, jsonify, render_template, send_from_directory, Response
from flask_socketio import SocketIO
from pydantic import BaseModel, Field

# mute Flask and Werkzeug logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('flask.app').setLevel(logging.ERROR)

class GameLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: str
    actor_name: Optional[str] = "GameLeader"
    target_name: Optional[str] = None
    content: str
    public: bool = True
    context_data: Optional[Dict[str, Any]] = None

    def to_string(self, sequence_number: int = 0) -> str:
        parts = [f"[{sequence_number}] Event: {self.type}"]
        if self.actor_name:
            parts.append(f"Actor: {self.actor_name}")
        if self.target_name:
            parts.append(f"Target: {self.target_name}")
        parts.append(f"Content: {self.content}")
        if self.context_data:
            context_str = ", ".join([f"{k}: {v}" for k, v in self.context_data.items()])
            parts.append(f"Context: ({context_str})")
        return "\n".join(parts)


class Logger(ABC):
    @abstractmethod
    def log(self, entry: GameLogEntry) -> None:
        pass


class WebLogger(Logger):

    def __init__(self, port=4999):
        self.entries = []
        self.port = port
        self.app = Flask(__name__, static_folder='public', static_url_path='/static')
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        
        @self.app.route('/')
        def index():
            return send_from_directory('public', 'index.html')
        
        @self.app.route('/api/logs')
        def get_logs():
            # Convert all entries to dict and ensure timestamp is a string
            return jsonify([
                {
                    **entry.dict(),
                    "timestamp": entry.timestamp.isoformat() if isinstance(entry.timestamp, datetime) else entry.timestamp
                }
                for entry in self.entries
            ])
        
        # Start the server in a background thread
        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()
        # open browser after a short delay
        threading.Timer(0.5, lambda: webbrowser.open_new(f'http://localhost:{self.port}/')).start()

    def _run_server(self):
        # debug=False, use_reloader=False to avoid thread issue
        self.socketio.run(self.app, port=self.port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

    def log(self, entry: GameLogEntry) -> None:
        self.entries.append(entry)
        entry_dict = entry.dict()  # fails with model_dump_json() because of datetime
        entry_dict['timestamp'] = entry.timestamp.isoformat()
        self.socketio.emit('new_log_entry', entry_dict)

if __name__ == "__main__":
    #########################################################
    # NOT MEANT TO BE RUN, ONLY FOR TESTING
    #########################################################
    logger = WebLogger()
    # load the game logs from the file
    with open("game_logs_1749042737.9183989.json", "r", encoding="utf-8") as f:
        game_logs = json.load(f)

    for log in game_logs:
        time.sleep(0.2)
        print("Logging entry:", log)
        logger.log(GameLogEntry(**json.loads(log)))
    time.sleep(10)