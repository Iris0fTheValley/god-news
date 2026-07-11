from typing import cast

from fastapi import Request

from god_news.container import AppContainer


def get_container(request: Request) -> AppContainer:
    return cast(AppContainer, request.app.state.container)
