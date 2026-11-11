"""WebSocket Connection Manager for streaming real-time alerts to connected users."""
import logging
from typing import Dict, List, Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class AlertConnectionManager:
    def __init__(self):
        # Maps user_id -> List[WebSocket]
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info("WebSocket connected for user_id=%d. Total active: %d", user_id, len(self.active_connections[user_id]))

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info("WebSocket disconnected for user_id=%d.", user_id)

    async def broadcast_alert(self, user_id: int, alert_data: Dict[str, Any]):
        """Pushes an alert to all active WebSocket clients of user_id."""
        if user_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(alert_data)
                except Exception as e:
                    logger.warning("Failed to send alert to websocket: %s", e)
                    disconnected.append(connection)
            for d in disconnected:
                self.disconnect(user_id, d)


alert_manager = AlertConnectionManager()
