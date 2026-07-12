import uvicorn

from god_news.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "god_news.main:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=1,
    )


if __name__ == "__main__":
    main()
