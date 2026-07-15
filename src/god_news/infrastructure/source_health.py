from __future__ import annotations

import httpx

from god_news.config import Settings
from god_news.sources.health import SourceAdapterPolicy


class HttpSourceReachabilityProbe:
    """Low-impact reachability probe; it never downloads or parses source content."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def is_reachable(self, endpoint: str) -> bool:
        response = await self._client.request(
            "HEAD",
            endpoint,
            headers={"Accept": "*/*"},
        )
        # Authentication failures and method rejections still prove that the
        # configured host is reachable. Upstream 5xx responses do not.
        return response.status_code < 500


def build_source_policies(settings: Settings) -> tuple[SourceAdapterPolicy, ...]:
    reddit_credentials = bool(
        settings.source_reddit_client_id
        and settings.source_reddit_client_secret
        and settings.source_reddit_user_agent
    )
    guardian_credentials = settings.source_guardian_api_key is not None

    return (
        SourceAdapterPolicy(
            source="dazhong",
            enabled=settings.source_dazhong_enabled,
            configured=True,
            endpoint=settings.source_dazhong_endpoint,
            access_method="authorized_public_page",
            authorized=settings.source_dazhong_public_page_use_authorized,
            notes=[
                "typed_contract_ingress",
                "no_undocumented_private_api",
                "per_item_rights_review_still_required",
            ],
        ),
        SourceAdapterPolicy(
            source="reddit",
            enabled=settings.source_reddit_enabled,
            configured=reddit_credentials,
            endpoint=settings.source_reddit_endpoint,
            access_method="official_api",
            authorized=(reddit_credentials and settings.source_reddit_api_use_authorized),
            notes=[
                "official_oauth_data_api_only",
                "credentials_configured" if reddit_credentials else "credentials_missing",
                "per_item_rights_review_still_required",
            ],
        ),
        SourceAdapterPolicy(
            source="guardian",
            enabled=settings.source_guardian_enabled,
            configured=guardian_credentials,
            endpoint=settings.source_guardian_endpoint,
            access_method="official_api",
            authorized=(guardian_credentials and settings.source_guardian_ai_use_authorized),
            notes=[
                "official_content_api_only",
                "credentials_configured" if guardian_credentials else "credentials_missing",
                "per_item_rights_review_still_required",
            ],
        ),
        SourceAdapterPolicy(
            source="pikabu",
            enabled=settings.source_pikabu_enabled,
            configured=True,
            endpoint=settings.source_pikabu_endpoint,
            access_method="authorized_public_page",
            authorized=settings.source_pikabu_public_page_use_authorized,
            notes=[
                "typed_contract_ingress",
                "stop_on_captcha",
                "no_undocumented_private_api",
                "per_item_rights_review_still_required",
            ],
        ),
    )
