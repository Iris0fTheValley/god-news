from __future__ import annotations

import sys

from god_news.infrastructure.fetchers.drission import (
    DrissionWorkerRequest,
    DrissionWorkerResponse,
)
from god_news.infrastructure.fetchers.url_policy import UrlPolicy


def _run(request: DrissionWorkerRequest) -> DrissionWorkerResponse:
    try:
        from DrissionPage import Chromium, ChromiumOptions
    except ImportError:
        return DrissionWorkerResponse(
            ok=False,
            error="DrissionPage is unavailable; install the fetchers extra.",
        )

    policy = UrlPolicy(
        allow_private=request.allow_private,
        allowed_ports=request.allowed_ports,
    )
    try:
        policy.validate_sync(request.url)
    except Exception:
        return DrissionWorkerResponse(ok=False, error="Source URL was rejected.")
    browser = None
    try:
        options = (
            ChromiumOptions(read_file=False)
            .auto_port()
            .headless(True)
            .incognito(True)
            .no_imgs(True)
            .mute(True)
            .set_load_mode("eager")
            .set_timeouts(
                base=request.base_timeout_seconds,
                page_load=request.timeout_seconds,
                script=request.script_timeout_seconds,
            )
            .set_retry(times=0, interval=0)
        )
        browser = Chromium(addr_or_opts=options)
        tab = browser.latest_tab
        if not tab.get(request.url, retry=0, timeout=request.timeout_seconds):
            return DrissionWorkerResponse(ok=False, error="Browser page visit failed.")
        final_url = policy.validate_sync(str(tab.url))
        html = str(tab.html)
        if len(html.encode("utf-8")) > request.max_response_bytes:
            return DrissionWorkerResponse(
                ok=False,
                error="Rendered HTML exceeded the configured size limit.",
            )
        return DrissionWorkerResponse(
            ok=True,
            final_url=final_url,
            title=str(tab.title or "Untitled source"),
            html=html,
        )
    except Exception as exc:
        sys.stderr.write(f"Drission worker internal error: {type(exc).__name__}\n")
        return DrissionWorkerResponse(ok=False, error="Browser rendering failed.")
    finally:
        if browser is not None:
            browser.quit(timeout=request.quit_timeout_seconds, force=True, del_data=True)


def main() -> int:
    try:
        request = DrissionWorkerRequest.model_validate_json(sys.stdin.buffer.read())
        result = _run(request)
    except Exception as exc:
        sys.stderr.write(f"Drission worker input error: {type(exc).__name__}\n")
        result = DrissionWorkerResponse(ok=False, error="Browser worker failed.")
    sys.stdout.write(result.model_dump_json())
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
