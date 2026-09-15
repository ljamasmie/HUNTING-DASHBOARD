#!/usr/bin/env python3
"""
Refresca data.json consultando la API de Apollo para las listas de
Lorenzo Jamasmie y regenera el archivo que consume el dashboard.

Requiere la variable de entorno APOLLO_API_KEY (Settings > Integrations > API
dentro de Apollo -> genera una API key para tu usuario).

Uso local:
    export APOLLO_API_KEY="tu_api_key"
    python3 scripts/refresh_data.py

El workflow de GitHub Actions (.github/workflows/refresh.yml) llama a este
script automáticamente con el secret APOLLO_API_KEY.
"""
import os
import sys
import json
import time
import datetime
from collections import Counter, defaultdict
import urllib.request
import urllib.error

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY")
if not APOLLO_API_KEY:
    print("ERROR: falta la variable de entorno APOLLO_API_KEY", file=sys.stderr)
    sys.exit(1)

# IDs de las listas de Lorenzo Jamasmie (owner_id 6a97347e1365fe0010e7b200).
# El nombre visible se consulta en vivo a Apollo en cada corrida (ver fetch_label_names),
# así que si renombras una lista en Apollo, el dashboard se actualiza solo.
# El "rubro" queda fijo por ID (no por nombre) para que un renombre no lo desordene.
# Si Lorenzo crea una lista nueva, agrégala aquí con su ID y rubro.
# Si Lorenzo BORRA una lista, sácala de aquí (de los dos diccionarios) o va a
# seguir apareciendo fantasma en el dashboard con 0 contactos.
RUBRO_BY_ID = {
    "6a99928f1cd4ac001c899834": "Contact Centers",
    "6aa282ee44d9a9001880e704": "Seguros",
    "6aa7c0082e331500105b6388": "Outsourcing",
}
# Nombres de respaldo, solo se usan si la consulta a /labels falla (p.ej. la API
# key no es "master key" y Apollo bloquea ese endpoint con 403).
FALLBACK_NAMES = {
    "6a99928f1cd4ac001c899834": "CEOs, COOs y Cargos Comerciales - Contact Center España",
    "6aa282ee44d9a9001880e704": "Aseguradoras España - Comercial y RRHH",
    "6aa7c0082e331500105b6388": "Líderes RRHH - Outsourcing España",
}
OWNER_NAME = "Lorenzo Jamasmie"

LABELS_URL = "https://api.apollo.io/api/v1/labels"


def fetch_label_names():
    """Consulta los nombres actuales de las listas en Apollo. Si la API key
    no es master key, este endpoint da 403 y usamos los nombres de respaldo."""
    req = urllib.request.Request(
        LABELS_URL,
        headers={"Accept": "application/json", "x-api-key": APOLLO_API_KEY},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            all_labels = json.loads(resp.read().decode("utf-8"))
        names = {}
        for lid in RUBRO_BY_ID:
            match = next((l for l in all_labels if l.get("id") == lid or l.get("_id") == lid), None)
            names[lid] = match["name"] if match else FALLBACK_NAMES[lid]
        return names
    except urllib.error.HTTPError as e:
        print(f"Aviso: no se pudo leer /labels ({e.code}), uso nombres de respaldo.", file=sys.stderr)
        return dict(FALLBACK_NAMES)
    except Exception as e:
        print(f"Aviso: no se pudo leer /labels ({e}), uso nombres de respaldo.", file=sys.stderr)
        return dict(FALLBACK_NAMES)


LABEL_MAP = fetch_label_names()
RUBRO_MAP = {LABEL_MAP[lid]: rubro for lid, rubro in RUBRO_BY_ID.items()}

API_URL = "https://api.apollo.io/api/v1/contacts/search"
PER_PAGE = 100


def fetch_page(page):
    payload = {
        "contact_label_ids": list(LABEL_MAP.keys()),
        "page": page,
        "per_page": PER_PAGE,
    }
    req = urllib.request.Request(
        API_URL,
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
            print(f"HTTPError {e.code} en page {page}: {body}", file=sys.stderr)
            if e.code == 429 and attempt < 2:
                time.sleep(5)
                continue
            raise
    raise RuntimeError("No se pudo obtener la página %s tras reintentos" % page)


def classify(title):
    if not title:
        return "Otros"
    t = title.lower()
    if any(k in t for k in ["ceo", "director general", "chief executive", "fundador", "founder", "presidente"]):
        return "CEO / Founder"
    if any(k in t for k in ["coo", "chief operating"]):
        return "COO"
    if any(k in t for k in ["director de rrhh", "hr director", "director rrhh", "directora rrhh",
                             "directora de recursos humanos", "director de recursos humanos",
                             "people director", "head of hr", "head of people"]):
        return "HR/People Director"
    if any(k in t for k in ["talent acquisition", "selección", "reclutamiento", "recruiter", "recruiting"]):
        return "Talent Acquisition"
    if any(k in t for k in ["rrhh", "recursos humanos", "human resources", "hr manager",
                             "hr generalist", "hr business partner", "hr lead"]):
        return "HR/People Manager"
    if any(k in t for k in ["comercial", "sales director", "sales manager", "director comercial",
                             "ventas", "account executive", "business development"]):
        return "Comercial / Ventas"
    if any(k in t for k in ["compensat", "benefits", "beneficios"]):
        return "Compensation & Benefits"
    if any(k in t for k in ["l&d", "learning", "formación", "training"]):
        return "L&D"
    if any(k in t for k in ["comunicaci", "communications"]):
        return "Internal Communications"
    return "Otros"


def main():
    print("Consultando Apollo...")
    first = fetch_page(1)
    total_pages = first.get("pagination", {}).get("total_pages", 1)
    raw_contacts = list(first.get("contacts", []))
    print(f"  página 1/{total_pages} -> {len(raw_contacts)} registros")
    for page in range(2, total_pages + 1):
        data = fetch_page(page)
        batch = data.get("contacts", [])
        raw_contacts.extend(batch)
        print(f"  página {page}/{total_pages} -> {len(batch)} registros")

    # dedupe por id, conservando la unión de label_ids
    by_id = {}
    for c in raw_contacts:
        cid = c["id"]
        if cid not in by_id:
            c["label_ids"] = set(c.get("label_ids") or [])
            by_id[cid] = c
        else:
            by_id[cid]["label_ids"].update(c.get("label_ids") or [])
    unique = list(by_id.values())
    print(f"Contactos únicos: {len(unique)}")

    FOUR = set(LABEL_MAP.keys())
    out_contacts = []
    company_agg = defaultdict(lambda: {
        "contacts": 0, "rubros": set(), "city": None, "country": None,
        "titles": Counter(), "verified_email": 0, "with_phone": 0,
    })

    for c in unique:
        my_labels = [lid for lid in c["label_ids"] if lid in FOUR]
        if not my_labels:
            continue
        rubros = [RUBRO_MAP[LABEL_MAP[lid]] for lid in my_labels]
        role = classify(c.get("title"))
        phone = None
        if c.get("phone_numbers"):
            phone = c["phone_numbers"][0].get("sanitized_number")
        org = c.get("organization") or {}
        rec = {
            "id": c["id"], "name": c.get("name"), "title": c.get("title") or "N/A",
            "role": role, "company": c.get("organization_name") or "N/A",
            "city": c.get("city") or "N/A", "country": c.get("country") or "N/A",
            "email": c.get("email"), "email_status": c.get("email_status") or "unavailable",
            "phone": phone, "linkedin_url": c.get("linkedin_url"),
            "rubros": rubros, "lists": [LABEL_MAP[l] for l in my_labels],
            # --- campos añadidos para la integración con HubSpot (no se muestran
            # en el dashboard; solo se usan al mapear el contacto hacia HubSpot) ---
            "apollo_organization_id": c.get("organization_id") or org.get("id"),
            "company_website": org.get("website_url") or org.get("primary_domain"),
            "company_industry": org.get("industry"),
            "company_size": org.get("estimated_num_employees"),
        }
        rec["contact_source"] = "Apollo — " + (", ".join(rec["lists"]) if rec["lists"] else "N/A")
        out_contacts.append(rec)

        comp = rec["company"]
        ca = company_agg[comp]
        ca["contacts"] += 1
        for r in rubros:
            ca["rubros"].add(r)
        ca["city"] = ca["city"] or rec["city"]
        ca["country"] = ca["country"] or rec["country"]
        ca["titles"][rec["title"]] += 1
        ca["website"] = ca.get("website") or rec["company_website"]
        ca["industry"] = ca.get("industry") or rec["company_industry"]
        ca["size"] = ca.get("size") or rec["company_size"]
        ca["apollo_organization_id"] = ca.get("apollo_organization_id") or rec["apollo_organization_id"]
        if rec["email_status"] == "verified":
            ca["verified_email"] += 1
        if rec["phone"]:
            ca["with_phone"] += 1

    companies_out = []
    for name, d in company_agg.items():
        top_title = d["titles"].most_common(1)[0][0] if d["titles"] else "N/A"
        companies_out.append({
            "name": name, "contacts": d["contacts"], "rubros": sorted(d["rubros"]),
            "city": d["city"] or "N/A", "country": d["country"] or "N/A",
            "top_title": top_title, "verified_email": d["verified_email"], "with_phone": d["with_phone"],
            "website": d.get("website"), "industry": d.get("industry"), "size": d.get("size"),
            "apollo_organization_id": d.get("apollo_organization_id"),
        })
    companies_out.sort(key=lambda x: -x["contacts"])

    lists_summary = []
    for lid, name in LABEL_MAP.items():
        lcontacts = [c for c in out_contacts if name in c["lists"]]
        lcompanies = set(c["company"] for c in lcontacts)
        verified = sum(1 for c in lcontacts if c["email_status"] == "verified")
        with_phone = sum(1 for c in lcontacts if c["phone"])
        lists_summary.append({
            "name": name, "rubro": RUBRO_MAP[name], "contacts": len(lcontacts),
            "companies": len(lcompanies), "verified_email": verified, "with_phone": with_phone,
            "id": lid,
        })

    role_counts = Counter(c["role"] for c in out_contacts)
    rubro_counts = Counter()
    for c in out_contacts:
        for r in set(c["rubros"]):
            rubro_counts[r] += 1
    country_counts = Counter(c["country"] for c in out_contacts)

    data_blob = {
        "contacts": out_contacts,
        "companies": companies_out,
        "lists": lists_summary,
        "meta": {
            "role_counts": dict(role_counts),
            "rubro_counts": dict(rubro_counts),
            "country_counts": dict(country_counts.most_common(10)),
            "total_contacts": len(out_contacts),
            "total_companies": len(companies_out),
        },
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "owner": OWNER_NAME,
    }

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data_blob, f, ensure_ascii=False)

    print(f"OK -> {out_path} ({len(out_contacts)} contactos, {len(companies_out)} empresas)")


if __name__ == "__main__":
    main()
