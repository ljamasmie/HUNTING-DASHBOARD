#!/usr/bin/env python3
"""
Trae las secuencias (sequences / emailer_campaigns) de Apollo con sus
métricas de outreach (programados, entregados, abiertos, clics, respuestas,
interesados) y genera sequences.json para el dashboard.

Requiere una API key MASTER de Apollo (el endpoint /emailer_campaigns/search
da 403 con una key que no sea master). Reusa el mismo secret APOLLO_API_KEY
que ya usa refresh_data.py.

Uso local:
    export APOLLO_API_KEY="tu_master_api_key"
    python3 scripts/refresh_sequences.py

El workflow de GitHub Actions (.github/workflows/refresh_sequences.yml)
llama a este script automáticamente.
"""
import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.error

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY")
if not APOLLO_API_KEY:
    print("ERROR: falta la variable de entorno APOLLO_API_KEY", file=sys.stderr)
    sys.exit(1)

SEARCH_URL = "https://api.apollo.io/api/v1/emailer_campaigns/search"
PER_PAGE = 50


def pick(d, *keys, default=0):
    """Devuelve el primer valor no-nulo entre varios nombres de campo
    posibles (la API de Apollo no siempre usa el mismo nombre)."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def fetch_page(page):
    payload = {"page": page, "per_page": PER_PAGE}
    req = urllib.request.Request(
        SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "x-api-key": APOLLO_API_KEY,
        },
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 403:
                print(
                    "ERROR 403: tu APOLLO_API_KEY no tiene permiso de 'master key'. "
                    "Este endpoint (/emailer_campaigns/search) solo funciona con una "
                    "master API key. Genera una en Apollo: Settings > Integrations > API.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"HTTPError {e.code} en page {page}: {body}", file=sys.stderr)
            if e.code == 429 and attempt < 2:
                time.sleep(5)
                continue
            raise
    raise RuntimeError("No se pudo obtener la página %s tras reintentos" % page)


def normalize(seq):
    delivered = pick(seq, "unique_delivered", "num_delivered", "delivered_count")
    opened = pick(seq, "unique_opened", "num_opened", "opened_count")
    clicked = pick(seq, "unique_clicked", "num_clicked", "clicked_count")
    replied = pick(seq, "unique_replied", "num_replied", "replied_count")
    interested = pick(seq, "unique_interested", "num_interested", "interested_count")
    bounced = pick(seq, "unique_bounced", "num_bounced", "bounced_count")
    unsubscribed = pick(
        seq, "unique_unsubscribed", "num_unsubscribed", "unsubscribed_count", "num_opted_out"
    )
    not_sent = pick(seq, "unique_not_sent", "num_not_sent")
    scheduled = pick(seq, "unique_scheduled", "num_scheduled", "scheduled_count")
    num_steps = seq.get("num_steps") or len(seq.get("emailer_steps") or []) or 0

    def pct(n):
        return round(n / delivered * 100) if delivered else 0

    return {
        "id": seq.get("id"),
        "name": seq.get("name") or "Sin nombre",
        "active": bool(seq.get("active")),
        "num_steps": num_steps,
        "created_at": seq.get("created_at"),
        "scheduled": scheduled,
        "delivered": delivered,
        "opened": opened,
        "clicked": clicked,
        "replied": replied,
        "interested": interested,
        "bounced": bounced,
        "unsubscribed": unsubscribed,
        "not_sent": not_sent,
        "open_pct": pct(opened),
        "click_pct": pct(clicked),
        "reply_pct": pct(replied),
        "interested_pct": pct(interested),
    }


def main():
    print("Consultando secuencias de Apollo...")
    first = fetch_page(1)
    raw = list(first.get("emailer_campaigns", []))
    total_pages = first.get("pagination", {}).get("total_pages", 1)
    print(f"  página 1/{total_pages} -> {len(raw)} secuencias")
    for page in range(2, total_pages + 1):
        data = fetch_page(page)
        batch = data.get("emailer_campaigns", [])
        raw.extend(batch)
        print(f"  página {page}/{total_pages} -> {len(batch)} secuencias")

    sequences = [normalize(s) for s in raw]
    sequences.sort(key=lambda s: -(s["delivered"] or 0))

    data_blob = {
        "sequences": sequences,
        "meta": {
            "total_sequences": len(sequences),
            "active_sequences": sum(1 for s in sequences if s["active"]),
            "total_delivered": sum(s["delivered"] for s in sequences),
            "total_replied": sum(s["replied"] for s in sequences),
        },
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = os.path.join(repo_root, "sequences.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data_blob, f, ensure_ascii=False)

    print(f"OK -> {out_path} ({len(sequences)} secuencias)")


if __name__ == "__main__":
    main()
