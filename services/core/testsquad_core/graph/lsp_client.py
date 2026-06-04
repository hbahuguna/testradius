import asyncio
import json
import logging
from typing import List, Dict, Optional, Any
from lsprotocol import types

logger = logging.getLogger(__name__)

class LspClient:
    """
    A generic LSP Client to communicate with language servers via stdio.
    """
    def __init__(self, command: List[str], root_path: str):
        self.command = command
        self.root_path = root_path
        self.process = None
        self.id_counter = 1
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self._reader_task = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        logger.info(f"Starting LSP server: {' '.join(self.command)}")
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.root_path
        )
        
        self._reader_task = asyncio.create_task(self._read_loop())
        
        # Initialize the server
        # For TS, we often need to specify the tsserver path
        init_options = {}
        if "typescript-language-server" in self.command[0]:
            init_options = {
                "tsserver": {
                    "path": "/usr/local/bin/tsserver"
                }
            }

        await self.send_request("initialize", {
            "processId": None,
            "rootUri": f"file://{self.root_path}",
            "capabilities": {
                "textDocument": {
                    "definition": {"dynamicRegistration": True}
                }
            },
            "initializationOptions": init_options
        })
        await self.send_notification("initialized", {})
        logger.info("LSP server initialized.")

    async def stop(self):
        if self.process:
            try:
                # Try graceful shutdown
                await self.send_request("shutdown", {})
                await self.send_notification("exit", {})
            except:
                pass
            self.process.terminate()
            await self.process.wait()
            self.process = None
        
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None

    async def _read_loop(self):
        try:
            while self.process and not self.process.stdout.at_eof():
                line = await self.process.stdout.readline()
                if not line.startswith(b"Content-Length:"):
                    continue
                
                length = int(line.decode().split(":")[1].strip())
                await self.process.stdout.readline()  # Skip empty line
                
                body = await self.process.stdout.readexactly(length)
                message = json.loads(body.decode())
                
                if "id" in message:
                    msg_id = message["id"]
                    if msg_id in self.pending_requests:
                        future = self.pending_requests.pop(msg_id)
                        if "error" in message:
                            future.set_exception(Exception(message["error"]))
                        else:
                            future.set_result(message.get("result"))
                else:
                    # Notifications (don't have an ID)
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"LSP Read Loop Error: {e}")

    async def send_request(self, method: str, params: Any) -> Any:
        msg_id = self.id_counter
        self.id_counter += 1
        
        future = asyncio.get_running_loop().create_future()
        self.pending_requests[msg_id] = future
        
        await self._send_message({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params
        })
        
        try:
            # 10s timeout for LSP calls
            return await asyncio.wait_for(future, timeout=10.0)
        except asyncio.TimeoutError:
            if msg_id in self.pending_requests:
                del self.pending_requests[msg_id]
            raise Exception(f"LSP request '{method}' timed out after 10s")

    async def send_notification(self, method: str, params: Any):
        await self._send_message({
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        })

    async def _send_message(self, message: Dict):
        body = json.dumps(message).encode()
        header = f"Content-Length: {len(body)}\r\n\r\n".encode()
        self.process.stdin.write(header + body)
        await self.process.stdin.drain()

    async def get_definition(self, file_path: str, line: int, character: int) -> Optional[List[Dict]]:
        """
        Queries textDocument/definition for a given position.
        Returns a list of locations {uri, range}.
        """
        uri = f"file://{file_path}" if not file_path.startswith("file://") else file_path
        try:
            result = await self.send_request("textDocument/definition", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character}
            })
            if not result:
                return None
            
            # Result can be a single Location or a list of Locations
            if isinstance(result, dict):
                return [result]
            return result
        except Exception as e:
            logger.warning(f"Failed to get definition at {file_path}:{line}:{character}: {e}")
            return None
