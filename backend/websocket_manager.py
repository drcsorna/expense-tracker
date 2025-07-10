# backend/websocket_manager.py
# WebSocket connection manager for real-time progress updates

import json
import asyncio
from typing import Dict, List, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        # Active connections: session_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        
        # Connection metadata: session_id -> metadata
        self.connection_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Message history for reconnection recovery
        self.message_history: Dict[str, List[Dict[str, Any]]] = {}
        
        # Maximum messages to keep in history per session
        self.max_history_size = 50
    
    async def connect(self, websocket: WebSocket, session_id: str, user_id: Optional[int] = None):
        """Accept a new WebSocket connection."""
        try:
            await websocket.accept()
            
            # Store connection
            self.active_connections[session_id] = websocket
            
            # Store metadata
            self.connection_metadata[session_id] = {
                "user_id": user_id,
                "connected_at": datetime.utcnow(),
                "last_activity": datetime.utcnow(),
                "message_count": 0
            }
            
            # Initialize message history if not exists
            if session_id not in self.message_history:
                self.message_history[session_id] = []
            
            logger.info(f"WebSocket connection established for session {session_id}")
            
            # Send connection confirmation
            await self.send_personal_message(session_id, {
                "type": "connection_established",
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "WebSocket connection established successfully"
            })
            
            # Send any recent messages from history (for reconnection)
            await self._send_message_history(session_id)
            
        except Exception as e:
            logger.error(f"Failed to establish WebSocket connection for session {session_id}: {str(e)}")
            raise
    
    def disconnect(self, session_id: str):
        """Remove a WebSocket connection."""
        try:
            if session_id in self.active_connections:
                del self.active_connections[session_id]
            
            if session_id in self.connection_metadata:
                metadata = self.connection_metadata[session_id]
                logger.info(f"WebSocket disconnected for session {session_id}. "
                           f"Duration: {datetime.utcnow() - metadata['connected_at']}, "
                           f"Messages: {metadata['message_count']}")
                del self.connection_metadata[session_id]
            
            # Keep message history for potential reconnection
            # History will be cleaned up after timeout
            
        except Exception as e:
            logger.error(f"Error during disconnect for session {session_id}: {str(e)}")
    
    async def send_personal_message(self, session_id: str, message: Dict[str, Any]):
        """Send a message to a specific session."""
        if session_id not in self.active_connections:
            logger.warning(f"Attempted to send message to non-existent session {session_id}")
            return False
        
        try:
            websocket = self.active_connections[session_id]
            
            # Add timestamp if not present
            if "timestamp" not in message:
                message["timestamp"] = datetime.utcnow().isoformat()
            
            # Send message
            await websocket.send_text(json.dumps(message))
            
            # Update metadata
            if session_id in self.connection_metadata:
                self.connection_metadata[session_id]["last_activity"] = datetime.utcnow()
                self.connection_metadata[session_id]["message_count"] += 1
            
            # Store in history
            self._add_to_history(session_id, message)
            
            logger.debug(f"Message sent to session {session_id}: {message.get('type', 'unknown')}")
            return True
            
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected while sending message to session {session_id}")
            self.disconnect(session_id)
            return False
            
        except Exception as e:
            logger.error(f"Failed to send message to session {session_id}: {str(e)}")
            # Remove broken connection
            self.disconnect(session_id)
            return False
    
    async def send_progress(self, session_id: str, progress_data: Dict[str, Any]):
        """Send progress update to a specific session."""
        message = {
            "type": "progress_update",
            "data": progress_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return await self.send_personal_message(session_id, message)
    
    async def send_error(self, session_id: str, error_message: str, error_details: Optional[Dict[str, Any]] = None):
        """Send error message to a specific session."""
        message = {
            "type": "error",
            "error": error_message,
            "details": error_details or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return await self.send_personal_message(session_id, message)
    
    async def send_completion(self, session_id: str, result_data: Dict[str, Any]):
        """Send completion notification to a specific session."""
        message = {
            "type": "completion",
            "data": result_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return await self.send_personal_message(session_id, message)
    
    async def broadcast_to_user(self, user_id: int, message: Dict[str, Any]):
        """Broadcast a message to all sessions of a specific user."""
        sent_count = 0
        
        for session_id, metadata in self.connection_metadata.items():
            if metadata.get("user_id") == user_id:
                success = await self.send_personal_message(session_id, message)
                if success:
                    sent_count += 1
        
        logger.debug(f"Broadcast message to {sent_count} sessions for user {user_id}")
        return sent_count
    
    async def broadcast_to_all(self, message: Dict[str, Any]):
        """Broadcast a message to all active connections."""
        sent_count = 0
        
        for session_id in list(self.active_connections.keys()):
            success = await self.send_personal_message(session_id, message)
            if success:
                sent_count += 1
        
        logger.debug(f"Broadcast message to {sent_count} active sessions")
        return sent_count
    
    def get_active_sessions(self) -> List[str]:
        """Get list of active session IDs."""
        return list(self.active_connections.keys())
    
    def get_session_count(self) -> int:
        """Get number of active connections."""
        return len(self.active_connections)
    
    def get_user_sessions(self, user_id: int) -> List[str]:
        """Get active sessions for a specific user."""
        return [
            session_id for session_id, metadata in self.connection_metadata.items()
            if metadata.get("user_id") == user_id
        ]
    
    def is_session_active(self, session_id: str) -> bool:
        """Check if a session is active."""
        return session_id in self.active_connections
    
    def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific session."""
        return self.connection_metadata.get(session_id)
    
    async def ping_all_connections(self):
        """Send ping to all connections to check health."""
        ping_message = {
            "type": "ping",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Create a list of sessions to avoid modification during iteration
        sessions_to_ping = list(self.active_connections.keys())
        
        healthy_sessions = []
        for session_id in sessions_to_ping:
            try:
                websocket = self.active_connections.get(session_id)
                if websocket:
                    await websocket.send_text(json.dumps(ping_message))
                    healthy_sessions.append(session_id)
            except Exception as e:
                logger.warning(f"Ping failed for session {session_id}: {str(e)}")
                self.disconnect(session_id)
        
        logger.info(f"Pinged {len(healthy_sessions)} healthy connections")
        return healthy_sessions
    
    async def cleanup_stale_sessions(self, timeout_minutes: int = 30):
        """Clean up stale sessions and their history."""
        cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
        
        stale_sessions = []
        for session_id, metadata in list(self.connection_metadata.items()):
            if metadata["last_activity"] < cutoff_time:
                stale_sessions.append(session_id)
        
        # Clean up stale sessions
        for session_id in stale_sessions:
            self.disconnect(session_id)
            
            # Clean up message history for very old sessions
            if session_id in self.message_history:
                del self.message_history[session_id]
        
        if stale_sessions:
            logger.info(f"Cleaned up {len(stale_sessions)} stale sessions")
        
        return len(stale_sessions)
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        now = datetime.utcnow()
        
        total_connections = len(self.active_connections)
        total_history_entries = sum(len(history) for history in self.message_history.values())
        
        # Calculate average session duration
        durations = []
        for metadata in self.connection_metadata.values():
            duration = (now - metadata["connected_at"]).total_seconds()
            durations.append(duration)
        
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        # Group by user
        users = {}
        for session_id, metadata in self.connection_metadata.items():
            user_id = metadata.get("user_id", "anonymous")
            if user_id not in users:
                users[user_id] = []
            users[user_id].append(session_id)
        
        return {
            "total_active_connections": total_connections,
            "unique_users": len([user for user in users.keys() if user != "anonymous"]),
            "anonymous_connections": len(users.get("anonymous", [])),
            "total_message_history_entries": total_history_entries,
            "average_session_duration_seconds": avg_duration,
            "users_with_multiple_sessions": len([user for user, sessions in users.items() if len(sessions) > 1])
        }
    
    # Private methods
    
    def _add_to_history(self, session_id: str, message: Dict[str, Any]):
        """Add message to session history."""
        if session_id not in self.message_history:
            self.message_history[session_id] = []
        
        # Add message
        self.message_history[session_id].append(message)
        
        # Trim history if too large
        if len(self.message_history[session_id]) > self.max_history_size:
            self.message_history[session_id] = self.message_history[session_id][-self.max_history_size:]
    
    async def _send_message_history(self, session_id: str):
        """Send recent message history to a session (for reconnection)."""
        if session_id not in self.message_history:
            return
        
        history = self.message_history[session_id]
        if not history:
            return
        
        # Send last few important messages (progress, errors, completions)
        important_types = ["progress_update", "error", "completion"]
        recent_important = [
            msg for msg in history[-10:]  # Last 10 messages
            if msg.get("type") in important_types
        ]
        
        if recent_important:
            history_message = {
                "type": "message_history",
                "messages": recent_important,
                "count": len(recent_important),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            await self.send_personal_message(session_id, history_message)


# Background task to maintain connections
class WebSocketMaintenance:
    """Background maintenance for WebSocket connections."""
    
    def __init__(self, connection_manager: ConnectionManager):
        self.manager = connection_manager
        self.running = False
        self.task = None
    
    async def start_maintenance(self):
        """Start background maintenance task."""
        if self.running:
            return
        
        self.running = True
        self.task = asyncio.create_task(self._maintenance_loop())
        logger.info("WebSocket maintenance task started")
    
    async def stop_maintenance(self):
        """Stop background maintenance task."""
        if not self.running:
            return
        
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        logger.info("WebSocket maintenance task stopped")
    
    async def _maintenance_loop(self):
        """Main maintenance loop."""
        while self.running:
            try:
                # Ping connections every 60 seconds
                await asyncio.sleep(60)
                
                if not self.running:
                    break
                
                # Ping all connections
                await self.manager.ping_all_connections()
                
                # Clean up stale sessions every 5 minutes
                if datetime.utcnow().minute % 5 == 0:
                    await self.manager.cleanup_stale_sessions()
                
                # Log statistics every 10 minutes
                if datetime.utcnow().minute % 10 == 0:
                    stats = self.manager.get_connection_stats()
                    logger.info(f"WebSocket stats: {stats}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in WebSocket maintenance loop: {str(e)}")
                await asyncio.sleep(10)  # Wait before retrying