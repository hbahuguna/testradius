import docker
import uuid
import os
import tempfile
import shutil
from typing import Optional, List, Dict
from datetime import datetime
from testsquad_shared.api import ExecutionRequest, ExecutionStatusResponse, TaskStatus

class SandboxManager:
    def __init__(self, worker_image: str = "testsquad-worker:latest"):
        self.client = docker.from_env()
        self.worker_image = worker_image
        self._ensure_network()

    def _ensure_network(self, network_name: str = "testsquad-sandbox"):
        """Ensure a no-egress network exists for isolation."""
        try:
            self.client.networks.get(network_name)
        except docker.errors.NotFound:
            self.client.networks.create(
                network_name,
                driver="bridge",
                internal=True,
                labels={"testsquad": "sandbox", "v2": "true"}
            )

    async def create_run(self, request: ExecutionRequest) -> ExecutionStatusResponse:
        run_id = uuid.uuid4()
        container_name = f"testsquad-run-{run_id}"
        run_dir = tempfile.mkdtemp(prefix=f"testsquad-{run_id}-")
        
        try:
            volumes = {run_dir: {'bind': '/app', 'mode': 'rw'}}
            
            # Note: In a real implementation, we'd pull/build the image if missing
            # and handle volumes for code mounting.
            container = self.client.containers.run(
                self.worker_image,
                command=request.command,
                name=container_name,
                network="testsquad-sandbox",
                environment=request.env_vars,
                volumes=volumes,
                detach=True,
                remove=False,
                labels={
                    "testsquad_run_id": str(run_id), 
                    "v2": "true"
                }
            )
            
            return ExecutionStatusResponse(
                run_id=run_id,
                status=TaskStatus.RUNNING,
                started_at=datetime.utcnow()
            )
        except Exception as e:
            if os.path.exists(run_dir):
                shutil.rmtree(run_dir)
            return ExecutionStatusResponse(
                run_id=run_id,
                status=TaskStatus.FAILED,
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                error_message=str(e)
            )

    def get_run_status(self, run_id: uuid.UUID) -> ExecutionStatusResponse:
        container_name = f"testsquad-run-{run_id}"
        try:
            container = self.client.containers.get(container_name)
            
            # Map docker status to our TaskStatus
            state = container.attrs['State']
            docker_status = container.status
            
            status = TaskStatus.RUNNING
            exit_code = None
            finished_at = None
            
            if docker_status == "exited":
                exit_code = state['ExitCode']
                status = TaskStatus.COMPLETED if exit_code == 0 else TaskStatus.FAILED
                finished_at = datetime.fromisoformat(state['FinishedAt'].rstrip('Z'))

            return ExecutionStatusResponse(
                run_id=run_id,
                status=status,
                exit_code=exit_code,
                started_at=datetime.fromisoformat(state['StartedAt'].rstrip('Z')),
                finished_at=finished_at
            )
        except docker.errors.NotFound:
            raise ValueError(f"Run {run_id} not found")

    def stream_logs(self, run_id: uuid.UUID):
        """Generator for SSE log streaming."""
        container_name = f"testsquad-run-{run_id}"
        try:
            container = self.client.containers.get(container_name)
            for line in container.logs(stream=True, follow=True):
                yield f"data: {line.decode('utf-8')}\n\n"
        except docker.errors.NotFound:
            yield f"data: Error: Run {run_id} not found\n\n"

    def cleanup_run(self, run_id: uuid.UUID):
        container_name = f"testsquad-run-{run_id}"
        try:
            container = self.client.containers.get(container_name)
            container.remove(force=True)
        except docker.errors.NotFound:
            pass
            
        # Also clean up host volumes (searching for the temp dir path)
        # In a real system, we'd store the host_path in a DB.
        # For S1.3, we focus on the logic.
