                payload=payload,
                timeout=timeout,
            )

            if response.status_code >= 400:
                error_text = self._clean_error_text(response)

                return (
                    f"AI connection exception: HTTP {response.status_code}"
                    + (f" - {error_text}" if error_text else "")
                )

            try:
                data = response.json()

            except Exception as exc:
                return (
                    "AI connection exception: "
                    f"Invalid JSON response from custom endpoint: {exc}"
                )

            output = self._extract_legacy_text(data)
            output = self._strip_reasoning(output)

            if output:
                return output

            return (
                "AI connection exception: "
                "The custom endpoint returned no generated text."
            )

        except httpx.TimeoutException as exc:
            return (
                "AI connection exception: "
                f"Request timed out - {exc}"
            )

        except httpx.ConnectError as exc:
            return (
                "AI connection exception: "
                f"Connection failed - {exc}"
            )

        except httpx.HTTPError as exc:
            return (
                "AI connection exception: "
                f"HTTP client error - {exc}"
            )

        except Exception as exc:
            return (
                "AI connection exception: "
                f"{type(exc).__name__}: {exc}"
            )


async def test_hf_connection(
    token: str,
    model: str,
    endpoint_url: str | None = None,
) -> dict[str, Any]:
    """
    Test the same generation path used by the real chat/RAG flow.
    """
    client = HuggingFaceClient(
        token=token,
        model=model,
        endpoint_url=endpoint_url,
    )

    output = await client.generate(
        "Reply with exactly these two words and nothing else: connection ok",
        temperature=0.1,
        top_p=0.9,
        max_tokens=40,
        timeout=60,
    )

    normalized = (output or "").strip().lower()

    error_markers = (
        "ai is not configured",
        "ai connection exception",
        "ai connection error",
        "request timed out",
        "connection failed",
    )

    has_error = any(
        marker in normalized
        for marker in error_markers
    )

    ok = (
        not has_error
        and "connection ok" in normalized
    )

    result = {
        "ok": ok,
        "endpoint_url": client.endpoint_url,
        "endpoint_mode": client.endpoint_mode,
        "model": client.model,
        "message": output,
    }

    return result
