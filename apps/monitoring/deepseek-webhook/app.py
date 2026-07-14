"""DeepSeek-backed alert RCA webhook.

Grafana/Alertmanager POSTs alert batches here; this asks an LLM for a root-cause
analysis + remediation and returns/logs it (Promtail ships the log line to Loki).
Prompt building lives in rca.py (pure, unit-tested); the network call is isolated
in request_analysis() so it is easy to reason about and stub.

Hardened vs. the original inline-in-YAML version: proper source in a signed image,
runs nonroot on a read-only rootfs, no secret baked into Git, and the base URL /
model come from plain env values (the previous config mounted a whole YAML file
into one env var by mistake).
"""

import datetime
import json
import logging
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rca import api_key_configured, build_falco_prompt, build_prompt

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
MAX_TOKENS = int(os.environ.get("DEEPSEEK_MAX_TOKENS", "1024"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="DeepSeek Alert RCA")


async def request_analysis(prompt: str) -> str:
    """Call the DeepSeek chat API and return the analysis text. Raises on error."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "You are an expert SRE and Kubernetes operator."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": MAX_TOKENS,
                "temperature": 0.3,
            },
        )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


@app.get("/healthz")
async def health():
    return {"status": "ok"}


async def analyze(prompt: str, *, source: str, title: str, count: int):
    """Run the prompt through the LLM, log one JSON line to Loki, and respond.

    Shared by both entry points: /webhook (Grafana/Alertmanager alerts) and
    /falco (Falco runtime detections via falcosidekick).
    """
    if not api_key_configured(DEEPSEEK_API_KEY):
        analysis = "DeepSeek API key not configured; set the deepseek-api-key secret."
    else:
        try:
            analysis = await request_analysis(prompt)
        except Exception as exc:  # noqa: BLE001 — surface any API/parse error as the analysis body
            logging.exception("DeepSeek call failed")
            analysis = f"Error calling DeepSeek API: {exc}"

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # One JSON line to stdout -> Promtail -> Loki.
    logging.info(json.dumps({
        "timestamp": timestamp,
        "source": source,
        "title": title,
        "event_count": count,
        "analysis": analysis[:2000],
    }))
    return JSONResponse({"status": "analyzed", "source": source,
                         "timestamp": timestamp, "analysis": analysis[:2000]})


@app.post("/webhook")
async def webhook(request: Request):
    """Grafana / Alertmanager alert batch -> RCA."""
    body = await request.json()
    alerts = body.get("alerts", [])
    if not alerts:
        return JSONResponse({"status": "no alerts"})
    return await analyze(
        build_prompt(alerts),
        source="alertmanager",
        title=body.get("title", "No title"),
        count=len(alerts),
    )


@app.post("/falco")
async def falco(request: Request):
    """Falco runtime detection (via falcosidekick) -> containment RCA.

    falcosidekick's webhook output posts a single Falco event; tolerate a list.
    """
    body = await request.json()
    event = body[0] if isinstance(body, list) and body else body
    if not isinstance(event, dict) or not event.get("rule"):
        return JSONResponse({"status": "no event"})
    return await analyze(
        build_falco_prompt(event),
        source="falco",
        title=event.get("rule", "Falco event"),
        count=1,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
