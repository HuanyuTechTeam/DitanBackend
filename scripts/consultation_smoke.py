"""Local-only smoke for a server configured with CONSULTATION_LLM_PROVIDER=fake.

Set CONSULTATION_SMOKE_TOKEN to a valid consultation ticket, then run:
  uv run python scripts/consultation_smoke.py --base-url http://127.0.0.1:8000
The token is used in headers only and never printed.
"""

import argparse
import asyncio
import json
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

ROOT = "/api/v1/consultations"


async def events(response):
    response.raise_for_status()
    name, data = "message", []
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield name, json.loads("\n".join(data))
            name, data = "message", []
        elif line.startswith("event:"):
            name = line[6:].lstrip(" ")
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))


async def get_data(client, path):
    response = await client.get(path)
    response.raise_for_status()
    return response.json()["data"]


async def finish_turn(client, path, body):
    async with client.stream("POST", path + "/turns", json=body) as response:
        async for name, data in events(response):
            if name == "error":
                raise RuntimeError(f"Turn failed: {data['code']}")
            if name == "completed":
                return data
    raise RuntimeError("Stream ended without a completed event")


async def smoke(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        ROOT,
        json={
            "encounter_uuid": str(uuid4()),
            "pre_diagnosis_uuid": str(uuid4()),
            "inputs": {
                "patient": {"sex": "男", "birthday": "1990-01-01"},
                "assessments": {},
            },
        },
    )
    response.raise_for_status()
    snapshot = response.json()["data"]
    path = ROOT + "/" + snapshot["consultation_id"]
    start = {"turn_id": str(uuid4()), "kind": "start", "base_version": 0}
    # Deliberately drop the first stream after a delta, then recover by the saved turn ID.
    disconnected = False
    async with client.stream("POST", path + "/turns", json=start) as response:
        async for name, data in events(response):
            if name == "delta":
                disconnected = True
                break
            if name == "error":
                raise RuntimeError(f"Start failed: {data['code']}")
    async with asyncio.timeout(65):
        while True:
            turn = await get_data(client, path + "/turns/" + start["turn_id"])
            if turn["status"] == "completed":
                break
            if turn["status"] == "failed":
                await finish_turn(client, path, start)
                break
            await asyncio.sleep(0.1)
    # Same ID can be submitted again; only the committed result is returned.
    await finish_turn(client, path, start)
    snapshot = await get_data(client, path)
    answers = 0
    while snapshot["status"] == "collecting":
        await finish_turn(
            client,
            path,
            {
                "turn_id": str(uuid4()),
                "kind": "answer",
                "base_version": snapshot["version"],
                "text": "本地假模型冒烟回答",
                "input_type": "text",
            },
        )
        answers += 1
        snapshot = await get_data(client, path)
    assert snapshot["status"] == "ready_for_report" and answers == 11
    await finish_turn(
        client,
        path,
        {
            "turn_id": str(uuid4()),
            "kind": "report",
            "base_version": snapshot["version"],
        },
    )
    snapshot = await get_data(client, path)
    archive = await get_data(client, path + "/archive")
    assert snapshot["status"] == "completed" and snapshot["version"] == 13
    assert archive["diagnosis_result"] == snapshot["report"]
    assert archive["diagnosis_result"].startswith("【假报告】"), (
        "Run this smoke with the fake provider"
    )
    assert "User: 本地假模型冒烟回答" in archive["conversation_log"]
    return {
        "consultation_id": snapshot["consultation_id"],
        "status": snapshot["status"],
        "version": snapshot["version"],
        "answers": answers,
        "disconnect_recovered": disconnected,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    } or parsed.scheme not in {"http", "https"}:
        parser.error("This smoke only accepts a loopback server")
    token = os.environ.get("CONSULTATION_SMOKE_TOKEN")
    if not token:
        parser.error("Set CONSULTATION_SMOKE_TOKEN to a valid consultation ticket")

    async def run():
        async with httpx.AsyncClient(
            base_url=args.base_url,
            timeout=httpx.Timeout(240, connect=5),
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=False,
            trust_env=False,
        ) as client:
            print(json.dumps(await smoke(client), ensure_ascii=False))

    asyncio.run(run())


if __name__ == "__main__":
    main()
