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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashboard_data import load_raw  # noqa: E402

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY")
if not APOLLO_API_KEY:
    print("ERROR: falta la variable de entorno APOLLO_API_KEY", file=sys.stderr)
    sys.exit(1)

SEARCH_URL = "https://api.apollo.io/api/v1/emailer_campaigns/search"
PER_PAGE = 50


def pick(d, *keys, default=0):
    """Devuelve el primer valor no-nulo entre varios nombres de campo
    posibles (la API de Apollo no siempre usa el mismo nombre), convertido
    a número (Apollo a veces devuelve los conteos como texto, ej. "45")."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    continue
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


USERS_URL = "https://api.apollo.io/api/v1/users/search?page=1&per_page=100"
FALLBACK_OWNER_NAMES = {
    "6a97347e1365fe0010e7b200": "Lorenzo Jamasmie",
    "62571d44f1bb9800d89bac6b": "Joao Guerra",
    "69f9f2421e3af1001dc8458a": "Maria Pelaye",
}


def fetch_owner_names():
    names = dict(FALLBACK_OWNER_NAMES)
    req = urllib.request.Request(USERS_URL, method="GET", headers={
        "Accept": "application/json", "x-api-key": APOLLO_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            for u in json.loads(resp.read().decode("utf-8")).get("users", []):
                if u.get("id") and u.get("name"):
                    names[u["id"]] = u["name"]
    except Exception as e:
        print(f"Aviso: no se pudo leer /users/search ({e}); uso nombres de respaldo.", file=sys.stderr)
    return names


OWNER_NAMES = {}


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

    owner_id = seq.get("user_id") or seq.get("owner_id")
    return {
        "id": seq.get("id"),
        "name": seq.get("name") or "Sin nombre",
        "owner_id": owner_id,
        "owner": OWNER_NAMES.get(owner_id, "Desconocido"),
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


def is_mine(seq, list_names, seq_ids):
    """True si la secuencia tiene contactos de las listas de España del
    dashboard (su id aparece en data.json) o si se llama igual que una de
    esas listas."""
    if seq.get("id") in seq_ids:
        return True
    name = (seq.get("name") or "").strip().lower()
    return name in list_names


def load_refs():
    """Lee data.json (ya generado por refresh_data.py): nombres de las
    listas y los ids de las secuencias en las que hay contactos de España."""
    try:
        data = load_raw()
        names = {l["name"].strip().lower() for l in data.get("lists", []) if l.get("name")}
        seq_ids = {s["id"] for s in data.get("sequence_refs", []) if s.get("id")}
        return names, seq_ids
    except Exception as e:
        print(f"Aviso: no se pudo leer data.json para matchear listas ({e})", file=sys.stderr)
    return set(), set()


def main():
    OWNER_NAMES.update(fetch_owner_names())
    list_names, seq_ids = load_refs()
    print(f"Listas para matchear: {len(list_names)} · secuencias con contactos de España: {len(seq_ids)}")
    if not list_names and not seq_ids:
        print("Aviso: data.json vacío, no se filtrará.", file=sys.stderr)

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

    if list_names or seq_ids:
        sequences = [normalize(s) for s in raw if is_mine(s, list_names, seq_ids)]
    else:
        sequences = [normalize(s) for s in raw]
    print(f"Secuencias que coinciden con tus listas: {len(sequences)} de {len(raw)} totales")
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
