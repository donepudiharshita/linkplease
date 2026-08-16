import httpx

from .config import (
    PSEUDOGRAM_API_KEY,
    PSEUDOGRAM_BASE_URL,
    PSEUDOGRAM_TIMEOUT_SECONDS,
    validate_settings,
)


validate_settings()


class PseudoGramClient:
    """
    HTTP client for the PseudoGram API.

    A reusable httpx.Client keeps connections alive between
    requests and provides a cleaner boundary for testing.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float,
    ):
        self.base_url = base_url.rstrip("/")

        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers={
                "X-API-Key": api_key,
            },
        )

    def close(self) -> None:
        self.client.close()

    def send_dm(
        self,
        recipient_user_id: str,
        message: str,
        comment_id: str,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        """
        Send a DM through PseudoGram.

        The idempotency key prevents duplicate external DMs
        when the same application job is retried.
        """

        url = f"{self.base_url}/v1/dm/send"

        headers = {}

        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = {
            "recipient_user_id": recipient_user_id,
            "message": message,
            "comment_id": comment_id,
        }

        return self.client.post(
            url,
            json=payload,
            headers=headers,
        )

    def get_dm_status(
        self,
        dm_id: str,
    ) -> httpx.Response:
        """
        Check the current delivery state of a DM.

        Expected states:

        queued
        delivered
        failed
        """

        url = f"{self.base_url}/v1/dm/{dm_id}"

        return self.client.get(url)


pseudo_gram_client = PseudoGramClient(
    api_key=PSEUDOGRAM_API_KEY,
    base_url=PSEUDOGRAM_BASE_URL,
    timeout=PSEUDOGRAM_TIMEOUT_SECONDS,
)


def send_dm(
    recipient_user_id: str,
    message: str,
    comment_id: str,
    idempotency_key: str | None = None,
) -> httpx.Response:
    return pseudo_gram_client.send_dm(
        recipient_user_id=recipient_user_id,
        message=message,
        comment_id=comment_id,
        idempotency_key=idempotency_key,
    )


def get_dm_status(
    dm_id: str,
) -> httpx.Response:
    return pseudo_gram_client.get_dm_status(
        dm_id=dm_id,
    )