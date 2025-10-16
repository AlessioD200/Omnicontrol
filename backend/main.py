from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
import io
from pydantic import BaseModel, Field
import hashlib

from device_manager import DeviceManager
from user_store import create_or_update_user, find_user_by_token, link_hub_for_user
from dataclasses import asdict

import base64
import tempfile
import os
import subprocess
from typing import Tuple

UPLOAD_DIR = Path("state/updates")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Omnicontrol Hub API", version="1.0.0")
manager = DeviceManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    await manager.startup()
    # If an external agent service is managing the BlueZ agent (systemd
    # unit `omnicontrol-agent.service`) prefer that to avoid racing calls to
    # `bluetoothctl default-agent` during startup. Detect via systemctl and
    # skip the internal agent startup if the unit is active.
    try:
        import logging
        import subprocess

        agent_managed_by_systemd = False
        # Only attempt detection if systemctl is available in PATH
        from shutil import which

        if which("systemctl"):
            # Run systemctl is-active in a thread to avoid blocking the
            # event loop.
            res = await asyncio.to_thread(
                subprocess.run,
                ["systemctl", "is-active", "--quiet", "omnicontrol-agent.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if res.returncode == 0:
                agent_managed_by_systemd = True

        logger = logging.getLogger(__name__)
        if agent_managed_by_systemd:
            logger.info("omnicontrol-agent.service is active; skipping internal BlueZ agent startup")
        else:
            try:
                # manager.bluetooth._ensure_agent is async and will attempt
                # DBus agent registration when dbus-next is available.
                await manager.bluetooth._ensure_agent()
            except Exception as exc:  # pragma: no cover - environment dependent
                logger.warning(
                    "BlueZ DBus agent could not be started at startup: %s", exc
                )
    except Exception:
        # Non-fatal: best-effort check
        pass
    # Check for gdbus binary used by media_control and warn early if missing.
    try:
        import logging

        def _find_binary(name: str) -> Optional[str]:
            # Prefer shutil.which, but systemd may run with a restricted PATH.
            path = shutil.which(name)
            if path:
                return path
            # Common absolute locations
            candidates = [f"/usr/bin/{name}", f"/bin/{name}", f"/usr/local/bin/{name}"]
            for c in candidates:
                try:
                    if Path(c).exists():
                        return c
                except Exception:
                    continue
            return None

        logger = logging.getLogger(__name__)
        gdbus_path = _find_binary("gdbus")
        btctl_path = _find_binary("bluetoothctl")
        if not gdbus_path:
            logger.warning(
                "gdbus not found in PATH or common locations; media control endpoints will fail. Install libglib2.0-bin."
            )
        else:
            logger.info("gdbus found at %s", gdbus_path)
        if not btctl_path:
            logger.warning(
                "bluetoothctl not found in PATH or common locations; DBus agent fallback may not be available. Install bluez."
            )
        else:
            logger.info("bluetoothctl found at %s", btctl_path)
    except Exception:
        # Non-fatal: best-effort check
        pass


@app.get("/api/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/devices")
async def list_devices() -> Dict[str, List[Dict[str, object]]]:
    devices = await manager.get_devices()
    return {"devices": devices}


@app.post("/api/scan")
async def trigger_scan() -> Dict[str, object]:
    discovered = await manager.scan()
    stats = await manager.stats()
    return {"discovered": discovered, "stats": stats}


class CommandSpec(BaseModel):
    id: str
    characteristic: str
    label: Optional[str] = None
    payload_hex: Optional[str] = None
    payload_ascii: Optional[str] = None
    with_response: bool = False


class PairRequest(BaseModel):
    address: str
    name: Optional[str] = None
    room: Optional[str] = None
    type: Optional[str] = None
    device_id: Optional[str] = None
    commands: List[CommandSpec] = Field(default_factory=list)


class CommandRequest(BaseModel):
    command: str


@app.post("/api/pairings")
async def pair_device(request: PairRequest) -> Dict[str, object]:
    try:
        device = await manager.pair_bluetooth_device(request.dict(exclude_none=True))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return device.to_dict()


@app.post("/api/pairings/jobs")
async def create_pairing_job(request: PairRequest) -> Dict[str, str]:
    """Start a background pairing job and return a job id.

    The client can poll /api/pairings/jobs/{job_id} for status.
    """
    payload = request.dict(exclude_none=True)
    job_id = manager.start_pairing_job(payload)
    return {"job_id": job_id}


@app.get("/api/pairings/jobs/{job_id}")
async def get_pairing_job_status(job_id: str) -> Dict[str, object]:
    job = manager.get_pairing_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job


@app.post("/api/devices/{device_id}/toggle")
async def toggle_device(device_id: str) -> Dict[str, object]:
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Unknown device")
    try:
        updated = await manager.toggle_device(device_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return updated.to_dict()


@app.post("/api/devices/{device_id}/ping")
async def ping_device(device_id: str) -> Dict[str, str]:
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Unknown device")
    try:
        await manager.ping_device(device_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"status": "pinged", "device": device_id}


@app.post("/api/devices/{device_id}/command")
async def send_command(device_id: str, payload: CommandRequest) -> Dict[str, object]:
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Unknown device")
    try:
        updated = await manager.send_command(device_id, payload.command)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return updated.to_dict()


@app.post('/api/devices/{device_id}/connect')
async def connect_device(device_id: str) -> Dict[str, object]:
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail='Unknown device')
    if not device.address:
        raise HTTPException(status_code=400, detail='Device missing bluetooth address')
    try:
        ok = await manager.connect_device(device_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {'connected': bool(ok), 'device': device_id}


@app.get('/api/devices/{device_id}/stream_info')
async def device_stream_info(device_id: str) -> Dict[str, object]:
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail='Unknown device')
    # Expose helpful keys if present in metadata
    md = device.metadata or {}
    info = {}
    if md.get('rtsp_url'):
        info['rtsp_url'] = md.get('rtsp_url')
    if md.get('snapshot_url'):
        info['snapshot_url'] = md.get('snapshot_url')
    return info


@app.get('/api/devices/{device_id}/snapshot')
async def device_snapshot(device_id: str):
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail='Unknown device')
    md = device.metadata or {}
    snapshot = md.get('snapshot_url')
    if not snapshot:
        # If no HTTP snapshot URL is configured, try capturing a single frame from RTSP
        rtsp_fallback = md.get('rtsp_url')
        if not rtsp_fallback:
            raise HTTPException(status_code=404, detail='No snapshot URL configured for this device')
        # Use ffmpeg to grab a single frame and return as JPEG
        try:
            cmd = [
                'ffmpeg',
                '-rtsp_transport', 'tcp',
                '-i', str(rtsp_fallback),
                '-frames:v', '1',
                '-f', 'image2pipe',
                '-vcodec', 'mjpeg',
                'pipe:1',
            ]
            # run ffmpeg and capture stdout (the jpeg) with a short timeout
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
            if proc.returncode == 0 and proc.stdout:
                return StreamingResponse(io.BytesIO(proc.stdout), media_type='image/jpeg')
            # if ffmpeg failed, include stderr for debugging
            err = proc.stderr.decode('utf-8', errors='ignore')
            raise HTTPException(status_code=502, detail=f'FFmpeg snapshot failed: {err}')
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail='ffmpeg not found on system')
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail='Snapshot capture timed out')
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f'Failed to capture snapshot from RTSP: {e}') from e

    # Fetch snapshot and proxy bytes back to client. Support optional basic auth
    try:
        import urllib.request

        req_headers = {"User-Agent": "Omnicontrol/1.0"}
        # Support credentials in metadata under 'snapshot_auth': {'user':.., 'pass':..}
        auth = md.get('snapshot_auth') or {}
        if isinstance(auth, dict):
            user = auth.get('user')
            pwd = auth.get('pass') or auth.get('password')
            if user and pwd:
                token = base64.b64encode(f"{user}:{pwd}".encode('utf-8')).decode('ascii')
                req_headers['Authorization'] = f'Basic {token}'

        req = urllib.request.Request(str(snapshot), headers=req_headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            content_type = resp.headers.get_content_type() or 'image/jpeg'
            return StreamingResponse(io.BytesIO(data), media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'Failed to fetch snapshot: {e}') from e


# Simple FFmpeg-based RTSP -> HLS proxy manager
# For each device we create a temp dir with HLS segments and run a persistent ffmpeg process
_hls_processes: Dict[str, Dict[str, object]] = {}

def _ensure_hls(device_id: str, rtsp_url: str) -> Tuple[str, subprocess.Popen]:
    """Ensure an ffmpeg process is running to produce HLS for the given device.

    Returns the path to the m3u8 manifest and the process object.
    """
    entry = _hls_processes.get(device_id)
    if entry:
        proc = entry.get('proc')
        manifest = entry.get('manifest')
        # check process still alive
        if proc and proc.poll() is None and manifest and Path(manifest).exists():
            return manifest, proc

    # create temp dir for this device
    tmpdir = Path(tempfile.mkdtemp(prefix=f"omnicontrol-hls-{device_id}-"))
    manifest = str(tmpdir / 'stream.m3u8')

    # ffmpeg command to read RTSP and emit HLS segments
    cmd = [
        'ffmpeg',
        '-rtsp_transport', 'tcp',
        '-i', rtsp_url,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-f', 'hls',
        '-hls_time', '2',
        '-hls_list_size', '6',
        '-hls_flags', 'delete_segments',
        manifest,
    ]

    # spawn detached process and capture stderr to a logfile for debugging
    logpath = tmpdir / 'ffmpeg.log'
    # Open the logfile in append mode so multiple restarts accumulate output
    logf = open(str(logpath), 'ab')
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=logf)
    except Exception:
        # ensure file handle is closed on failure
        try:
            logf.close()
        except Exception:
            pass
        raise
    _hls_processes[device_id] = {'proc': proc, 'manifest': manifest, 'dir': str(tmpdir)}
    return manifest, proc


@app.get('/api/devices/{device_id}/hls')
async def device_hls(device_id: str):
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail='Unknown device')
    md = device.metadata or {}
    rtsp = md.get('rtsp_url')
    if not rtsp:
        raise HTTPException(status_code=404, detail='No RTSP configured for this device')

    # start ffmpeg if needed
    try:
        manifest, proc = _ensure_hls(device_id, rtsp)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail='ffmpeg not found on system')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to start HLS proxy: {e}') from e

    # serve the m3u8 manifest
    if not Path(manifest).exists():
        # allow a short warm-up period
        await asyncio.sleep(1)
        if not Path(manifest).exists():
            raise HTTPException(status_code=503, detail='HLS stream not ready yet')
    return FileResponse(manifest, media_type='application/vnd.apple.mpegurl')


@app.post("/api/devices/{device_id}/media/play")
async def media_play(device_id: str) -> Dict[str, str]:
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Unknown device")
    # Validate client-provided device state before attempting media control
    if not device.address:
        raise HTTPException(status_code=400, detail="Device missing bluetooth address")
    try:
        # import lazily to avoid import-time circular dependencies and to
        # surface a clearer error if gdbus/media_control isn't available.
        import gdbus_media as _mc

        # gdbus_media uses subprocess/gdbus (blocking). Run in a thread.
        await asyncio.to_thread(_mc.play, device.address)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"status": "ok", "action": "play", "device": device_id}


@app.post("/api/devices/{device_id}/media/pause")
async def media_pause(device_id: str) -> Dict[str, str]:
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Unknown device")
    if not device.address:
        raise HTTPException(status_code=400, detail="Device missing bluetooth address")
    try:
        import gdbus_media as _mc
        await asyncio.to_thread(_mc.pause, device.address)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"status": "ok", "action": "pause", "device": device_id}


@app.post("/api/devices/{device_id}/media/next")
async def media_next(device_id: str) -> Dict[str, str]:
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Unknown device")
    if not device.address:
        raise HTTPException(status_code=400, detail="Device missing bluetooth address")
    try:
        import gdbus_media as _mc
        await asyncio.to_thread(_mc.next_track, device.address)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"status": "ok", "action": "next", "device": device_id}


@app.post("/api/devices/{device_id}/media/previous")
async def media_previous(device_id: str) -> Dict[str, str]:
    device = await manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Unknown device")
    if not device.address:
        raise HTTPException(status_code=400, detail="Device missing bluetooth address")
    try:
        import gdbus_media as _mc
        await asyncio.to_thread(_mc.previous_track, device.address)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"status": "ok", "action": "previous", "device": device_id}


@app.get("/api/settings")
async def get_settings() -> Dict[str, object]:
    data = await manager.load_settings()
    return data


@app.post("/api/settings")
async def save_settings(payload: Dict[str, object]) -> Dict[str, object]:
    stored = await manager.update_settings(payload)
    return stored


@app.get("/api/stats")
async def get_stats() -> Dict[str, int]:
    stats = await manager.stats()
    return stats


@app.get("/api/updates/history")
async def get_update_history() -> List[Dict[str, str]]:
    history = await manager.load_update_history()
    return history


@app.post("/api/updates")
async def stage_update(file: UploadFile = File(...), notes: str = "") -> Dict[str, object]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Firmware package missing")
    destination = UPLOAD_DIR / file.filename
    with destination.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    # compute sha256 checksum
    sha256 = hashlib.sha256()
    with destination.open("rb") as r:
        for chunk in iter(lambda: r.read(8192), b""):
            sha256.update(chunk)
    checksum = sha256.hexdigest()

    entry = {
        "version": derive_version(file.filename),
        "filename": file.filename,
        "checksum": checksum,
        "description": f"Staged {file.filename} – {notes or 'No additional notes provided.'}",
        "date": datetime.utcnow().date().isoformat(),
    }
    history = await manager.append_update_history(entry)
    return {"stored": str(destination), "entry": entry, "history": history}


@app.get('/api/updates/download/{filename}')
async def download_update(filename: str):
    path = UPLOAD_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail='Not found')
    return FileResponse(path, filename=filename, media_type='application/octet-stream')


@app.post('/api/devices/{device_id}/metadata')
async def update_device_metadata(device_id: str, payload: Dict[str, object]) -> Dict[str, object]:
    try:
        device = await manager.update_device_metadata(device_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return device.to_dict()


@app.post('/api/tapo/devices')
async def add_tapo_device(payload: Dict[str, object]) -> Dict[str, object]:
    """Register or update a Tapo device at runtime.

    POST body should be the device entry matching the Tapo store format, for example:
    {"id":"c200","name":"Tapo C200","ip":"192.168.0.236","type":"Camera","metadata":{...}}
    """
    try:
        # Use the controller's add_or_update_device which persists to the store
        manager.tapo.add_or_update_device(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "device": f"tapo-{payload.get('id')}"}


@app.get("/api/updates/latest")
async def get_latest_update() -> Dict[str, object]:
    history = await manager.load_update_history()
    if not history:
        raise HTTPException(status_code=404, detail="No updates available")
    latest = history[-1]
    return latest


@app.post('/api/account/link')
async def link_account(payload: Dict[str, str]) -> Dict[str, object]:
    """Link a hub URL with a user token. Expected payload: {user_id, token, hub, email?}

    This is a minimal local account store for development and testing.
    """
    user_id = payload.get('user_id') or payload.get('token')
    token = payload.get('token')
    hub = payload.get('hub')
    email = payload.get('email')

    if not token or not hub:
        raise HTTPException(status_code=400, detail='token and hub are required')

    # Create or update the user entry
    uid = user_id or token
    create_or_update_user(uid, token, email=email)
    user = link_hub_for_user(uid, hub)
    if not user:
        raise HTTPException(status_code=500, detail='Failed to link hub')
    return {'status': 'linked', 'user': asdict(user) if hasattr(user, '__dict__') else user}


@app.exception_handler(Exception)
async def generic_exception_handler(_, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


def derive_version(filename: str) -> str:
    parts = [part for part in filename.replace("_", "-").split("-") if part]
    for part in parts:
        if part and part[0].isdigit():
            return f"v{part}"
    return "Unversioned build"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
