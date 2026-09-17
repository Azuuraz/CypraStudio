"""Optional Microsoft Edge online speech adapter (outbound HTTPS only)."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Callable


log = logging.getLogger("cypra.tts")


class EdgeUnavailable(RuntimeError):
    pass


class EdgeEngine:
    name = "edge"
    MAX_AUDIO_BYTES = 20 * 1024 * 1024

    @staticmethod
    def rate_for_speed(speed: float) -> str:
        percent = round((max(0.5, min(2.0, float(speed))) - 1.0) * 100)
        return f"{percent:+d}%"

    async def synthesize(
        self,
        text: str,
        *,
        voice: str,
        rate: str = "+0%",
        pitch: str = "+0Hz",
        volume: str = "+0%",
        cancelled: Callable[[], bool],
        timeout: float = 30.0,
    ) -> bytes:
        try:
            import edge_tts
        except ImportError as exc:
            raise EdgeUnavailable("edge-tts is not installed") from exc

        last_error = None
        for attempt in range(2):
            if cancelled():
                raise asyncio.CancelledError
            communicator = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
            output = io.BytesIO()
            try:
                async with asyncio.timeout(timeout):
                    async for chunk in communicator.stream():
                        if cancelled():
                            raise asyncio.CancelledError
                        if chunk.get("type") != "audio":
                            continue
                        data = chunk.get("data")
                        if not isinstance(data, bytes):
                            raise EdgeUnavailable("Edge returned malformed audio")
                        if output.tell() + len(data) > self.MAX_AUDIO_BYTES:
                            raise EdgeUnavailable("Edge audio exceeded the bounded buffer")
                        output.write(data)
                audio = output.getvalue()
                if len(audio) < 32:
                    raise EdgeUnavailable("Edge returned no usable audio")
                return audio
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as exc:
                last_error = EdgeUnavailable("Edge synthesis timed out")
            except EdgeUnavailable as exc:
                # These are deterministic response/validation failures (bad
                # chunks, oversized output, or unusable audio), not transport
                # failures. Retrying would send the same invalid request again.
                raise exc
            except Exception as exc:
                last_error = EdgeUnavailable("Edge connection failed")
            if attempt == 0:
                await asyncio.sleep(0.25)
        raise last_error or EdgeUnavailable("Edge synthesis failed")

    @staticmethod
    async def list_voices(timeout: float = 15.0) -> list[dict]:
        try:
            import edge_tts
        except ImportError as exc:
            raise EdgeUnavailable("edge-tts is not installed") from exc
        try:
            async with asyncio.timeout(timeout):
                voices = await edge_tts.list_voices()
        except asyncio.TimeoutError as exc:
            raise EdgeUnavailable("Edge voice discovery timed out") from exc
        return [voice for voice in voices if isinstance(voice, dict)]
