from __future__ import annotations

import sys
from pathlib import Path

from god_news.domain.source_transcription import ASRSegment, ASRTranscript
from god_news.infrastructure.source_media_asr import (
    FasterWhisperWorkerRequest,
    FasterWhisperWorkerResponse,
)


def _run(request: FasterWhisperWorkerRequest) -> FasterWhisperWorkerResponse:
    try:
        media_path = Path(request.media_path).expanduser().resolve(strict=True)
    except OSError:
        return FasterWhisperWorkerResponse(ok=False, error_code="media_missing")
    if not media_path.is_file():
        return FasterWhisperWorkerResponse(ok=False, error_code="media_missing")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return FasterWhisperWorkerResponse(ok=False, error_code="asr_extra_missing")

    try:
        model = WhisperModel(
            request.model,
            device=request.device,
            compute_type=request.compute_type,
            download_root=request.download_root,
            local_files_only=request.local_files_only,
            cpu_threads=request.cpu_threads,
            num_workers=1,
        )
        generated, info = model.transcribe(
            str(media_path),
            task="transcribe",
            language=request.language_hint,
            beam_size=request.beam_size,
            vad_filter=request.vad_filter,
            word_timestamps=False,
            condition_on_previous_text=False,
        )
        segments: list[ASRSegment] = []
        previous_end = 0
        for raw in generated:
            text = str(raw.text).strip()
            if not text:
                continue
            start_ms = max(previous_end, round(float(raw.start) * 1_000))
            end_ms = max(start_ms + 1, round(float(raw.end) * 1_000))
            segments.append(
                ASRSegment(
                    sequence=len(segments),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                    average_log_probability=float(raw.avg_logprob),
                    no_speech_probability=float(raw.no_speech_prob),
                )
            )
            previous_end = end_ms
        if not segments:
            return FasterWhisperWorkerResponse(ok=False, error_code="no_speech_detected")
        return FasterWhisperWorkerResponse(
            ok=True,
            transcript=ASRTranscript(
                detected_language=str(info.language),
                language_probability=float(info.language_probability),
                segments=segments,
            ),
        )
    except Exception as exc:
        sys.stderr.write(f"ASR worker error: {type(exc).__name__}\n")
        return FasterWhisperWorkerResponse(ok=False, error_code="transcription_failed")


def main() -> int:
    try:
        request = FasterWhisperWorkerRequest.model_validate_json(sys.stdin.buffer.read())
        response = _run(request)
    except Exception as exc:
        sys.stderr.write(f"ASR worker input error: {type(exc).__name__}\n")
        response = FasterWhisperWorkerResponse(ok=False, error_code="invalid_request")
    sys.stdout.write(response.model_dump_json())
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
