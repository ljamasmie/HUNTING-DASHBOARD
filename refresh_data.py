#!/usr/bin/env python3
"""
Refresca data.json con TODAS las listas de España del equipo en Apollo
(de cualquier dueño: Lorenzo Jamasmie, Joao Guerra, Maria Pelaye...) y
regenera el archivo que consume el dashboard.

Qué se considera "lista de España": cualquier lista cuyo nombre lleve la
palabra suelta "ES", o "Spain" / "España" (p. ej. "ES - RRHH - FIN DE AÑO -
2026", "RRHH Spain", "Outsourcing RRHH - ES"), más las que se añadan a mano
en INCLUDE_LIST_IDS. Para dejar fuera alguna, añádela a EXCLUDE_LIST_IDS.

Por cada lista se guarda su dueño (quien la creó en Apollo) y, por cada
contacto, las secuencias de Apollo en las que está. Con eso el dashboard
puede filtrar por dueño y por secuencia.

Requiere la variable de entorno APOLLO_API_KEY (master key).

Uso local:
    export APOLLO_API_KEY="tu_api_key"
    python3 scripts/refresh_data.py
"""
import os
import re
import sys
import json
import time
import datetime
from collections import Counter
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashboard_data import CONTACT_COLUMNS, LINKEDIN_PREFIX, repo_root  # noqa: E402

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY")
BASE = "https://api.apollo.io/api/v1"
PER_PAGE = 100
# Apollo devuelve como máximo 10.000 contactos por búsqueda; por eso se
# consulta lista por lista (ninguna lista de España pasa de 10.000).
MAX_PAGES_PER_LIST = 100
PAUSE_BETWEEN_CALLS = 0.25  # segundos, para no chocar con el rate limit

# Listas que entran aunque su nombre no diga "ES"/"Spain"/"España".
INCLUDE_LIST_IDS = {
    "6ac36ec7a87234000c300c37",  # HR Innovation Summit 2026 - Asistentes
}
# Listas que nunca entran aunque su nombre lo diga.
EXCLUDE_LIST_IDS = set()

# Nombres de respaldo por si /users/search falla (IDs verificados en Apollo).
FALLBACK_OWNER_NAMES = {
    "6a97347e1365fe0010e7b200": "Lorenzo Jamasmie",
    "62571d44f1bb9800d89bac6b": "Joao Guerra",
    "69f9f2421e3af1001dc8458a": "Maria Pelaye",
}

DEFAULT_RUBRO = "Sin clasificar"
# Se recorre en orden; gana la primera coincidencia sobre el nombre de la lista.
RUBRO_RULES = [
    (r"summit|evento|feria", "Eventos"),
    (r"belleza", "Retail Belleza"),
    (r"contact\s*center", "Contact Center"),
    (r"asegurador|seguros|insurance", "Aseguradoras"),
    (r"financier", "Financiero"),
    (r"salud|health", "Salud"),
    (r"retail", "Retail"),
    (r"constru|cosntru", "Construcción"),
    (r"automo", "Automotriz"),
    (r"outsourcing", "Outsourcing"),
    (r"market research", "Market Research"),
    (r"\bbpo\b", "BPO"),
    (r"restauraci", "Restauración"),
    (r"benefits|beneficios", "Beneficios"),
    (r"partners", "Partners"),
    (r"trade marketing", "Trade Marketing"),
    # sin sector explícito: se agrupa por área
    (r"rrhh|\bhr\b|c-level", "RRHH (general)"),
    (r"compras|procurement", "Compras (general)"),
    (r"comercial|sales|business development|owner2director|c\+vp", "Comercial (general)"),
]


def rubro_for(name):
    low = (name or "").lower()
    for pattern, rubro in RUBRO_RULES:
        if re.search(pattern, low):
            return rubro
    return DEFAULT_RUBRO


def is_spain_list(label):
    lid = label.get("id") or label.get("_id")
    if lid in EXCLUDE_LIST_IDS:
        return False
    if lid in INCLUDE_LIST_IDS:
        return True
    tokens = re.split(r"[^0-9A-Za-zÀ-ÿ]+", label.get("name") or "")
    for t in tokens:
        if t == "ES" or t.lower() in ("spain", "españa", "espana"):
            return True
    return False


def api(method, path, payload=None):
    url = BASE + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "x-api-key": APOLLO_API_KEY,
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 429 and attempt < 4:
                wait = 15 * (attempt + 1)
                print(f"  429 rate limit en {path}, espero {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"HTTPError {e.code} en {path}: {body[:500]}", file=sys.stderr)
            raise
        except urllib.error.URLError as e:
            if attempt < 4:
                time.sleep(5)
                continue
            raise
    raise RuntimeError(f"No se pudo llamar a {path}")


def fetch_owner_names():
    names = dict(FALLBACK_OWNER_NAMES)
    try:
        data = api("GET", "/users/search?page=1&per_page=100")
        for u in data.get("users", []):
            if u.get("id") and u.get("name"):
                names[u["id"]] = u["name"]
    except Exception as e:
        print(f"Aviso: no se pudo leer /users/search ({e}); uso nombres de respaldo.", file=sys.stderr)
    return names


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
    if any(k in t for k in ["compras", "purchasing", "procurement", "buyer", "aprovisionamiento"]):
        return "Compras"
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


class Interner:
    """Asigna un índice a cada valor distinto (para el formato compacto)."""
    def __init__(self):
        self.values, self.index = [], {}

    def __call__(self, value):
        key = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
        if key not in self.index:
            self.index[key] = len(self.values)
            self.values.append(value)
        return self.index[key]


def fetch_list_contacts(label_id, label_name):
    contacts = []
    page = 1
    while True:
        data = api("POST", "/contacts/search", {
            "contact_label_ids": [label_id], "page": page, "per_page": PER_PAGE,
        })
        batch = data.get("contacts", [])
        contacts.extend(batch)
        total_pages = data.get("pagination", {}).get("total_pages", 1) or 1
        if page == 1 or page % 10 == 0 or page == total_pages:
            print(f"  {label_name}: página {page}/{total_pages} ({len(contacts)} contactos)")
        if page >= total_pages or page >= MAX_PAGES_PER_LIST or not batch:
            if total_pages > MAX_PAGES_PER_LIST:
                print(f"  Aviso: {label_name} supera 10.000 contactos; Apollo solo devuelve los primeros 10.000.",
                      file=sys.stderr)
            break
        page += 1
        time.sleep(PAUSE_BETWEEN_CALLS)
    return contacts


def main():
    if not APOLLO_API_KEY:
        print("ERROR: falta la variable de entorno APOLLO_API_KEY", file=sys.stderr)
        sys.exit(1)

    owner_names = fetch_owner_names()

    print("Leyendo listas de Apollo...")
    labels = api("GET", "/labels")
    spain = [l for l in labels
             if l.get("modality") in ("contacts", "accounts") and is_spain_list(l)]
    spain.sort(key=lambda l: l.get("created_at") or "", reverse=True)
    print(f"Listas de España: {len(spain)} "
          f"({sum(1 for l in spain if l.get('modality') == 'contacts')} de contactos, "
          f"{sum(1 for l in spain if l.get('modality') == 'accounts')} de empresas)")

    lists_out = []
    list_index = {}
    for l in spain:
        lid = l.get("id") or l.get("_id")
        owner_id = l.get("user_id") or l.get("owner_id")
        rec = {
            "id": lid,
            "name": l.get("name") or "Lista sin nombre",
            "rubro": rubro_for(l.get("name")),
            "owner_id": owner_id,
            "owner": owner_names.get(owner_id, "Desconocido"),
            "modality": l.get("modality"),
            "apollo_count": l.get("cached_count") or 0,
            "created_at": l.get("created_at"),
            "app_url": f"https://app.apollo.io/#/lists/{lid}",
            "contacts": 0, "companies": 0, "verified_email": 0, "with_phone": 0,
        }
        list_index[lid] = len(lists_out)
        lists_out.append(rec)

    # --- contactos, lista por lista ---
    by_id = {}
    for rec in lists_out:
        if rec["modality"] != "contacts":
            continue
        for c in fetch_list_contacts(rec["id"], rec["name"]):
            cur = by_id.get(c["id"])
            if cur is None:
                c["_lists"] = set()
                c["_seqs"] = set()
                by_id[c["id"]] = cur = c
            cur["_lists"].add(list_index[rec["id"]])
            for st in c.get("contact_campaign_statuses") or []:
                if st.get("emailer_campaign_id"):
                    cur["_seqs"].add(st["emailer_campaign_id"])
            for sid in c.get("emailer_campaign_ids") or []:
                cur["_seqs"].add(sid)
    print(f"Contactos únicos: {len(by_id)}")

    roles, cities, countries, statuses, orgs = (Interner() for _ in range(5))
    seq_ids = Interner()
    org_key_to_idx = {}
    rows = []
    list_companies = [set() for _ in lists_out]

    for c in by_id.values():
        org = c.get("organization") or {}
        org_name = c.get("organization_name") or org.get("name") or "N/A"
        org_id = c.get("organization_id") or org.get("id")
        okey = (org_name, org_id)
        if okey not in org_key_to_idx:
            org_key_to_idx[okey] = orgs([
                org_name,
                org.get("website_url") or org.get("primary_domain"),
                org.get("industry"),
                org.get("estimated_num_employees"),
                org_id,
            ])
        org_idx = org_key_to_idx[okey]

        phone = None
        if c.get("phone_numbers"):
            phone = c["phone_numbers"][0].get("sanitized_number")
        linkedin = c.get("linkedin_url")
        if linkedin and linkedin.startswith(LINKEDIN_PREFIX):
            linkedin = linkedin[len(LINKEDIN_PREFIX):]
        email_status = c.get("email_status") or "unavailable"

        my_lists = sorted(c["_lists"])
        for li in my_lists:
            L = lists_out[li]
            L["contacts"] += 1
            list_companies[li].add(org_name)
            if email_status == "verified":
                L["verified_email"] += 1
            if phone:
                L["with_phone"] += 1

        row = {
            "id": c["id"],
            "name": c.get("name"),
            "title": c.get("title"),
            "role_idx": roles(classify(c.get("title"))),
            "org_idx": org_idx,
            "city_idx": cities(c.get("city") or "N/A"),
            "country_idx": countries(c.get("country") or "N/A"),
            "email": c.get("email"),
            "email_status_idx": statuses(email_status),
            "phone": phone,
            "linkedin": linkedin,
            "list_idxs": my_lists,
            "seq_idxs": sorted(seq_ids(s) for s in c["_seqs"]),
        }
        rows.append([row[k] for k in CONTACT_COLUMNS])

    for li, L in enumerate(lists_out):
        if L["modality"] == "contacts":
            L["companies"] = len(list_companies[li])
        else:
            L["companies"] = L["apollo_count"]

    owners = sorted({(L["owner_id"], L["owner"]) for L in lists_out}, key=lambda o: o[1])

    data_blob = {
        "version": 2,
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "owner": "Equipo España",
        "owners": [{"id": oid, "name": name} for oid, name in owners],
        "lists": lists_out,
        "sequence_refs": [{"id": sid} for sid in seq_ids.values],
        "contact_columns": CONTACT_COLUMNS,
        "dict": {
            "roles": roles.values,
            "cities": cities.values,
            "countries": countries.values,
            "email_statuses": statuses.values,
            # cada org: [nombre, web, industria, nº empleados, apollo_organization_id]
            "orgs": orgs.values,
        },
        "contacts": rows,
    }

    out_path = os.path.join(repo_root(), "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data_blob, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"OK -> {out_path} ({len(rows)} contactos, {len(orgs.values)} empresas, "
          f"{len(lists_out)} listas, {len(seq_ids.values)} secuencias, {size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
