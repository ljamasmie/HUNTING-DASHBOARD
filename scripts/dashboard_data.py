"""
Utilidades compartidas para leer data.json.

Desde la versión 2, data.json se guarda en formato compacto (columnas +
diccionarios) para que pese poco aunque tenga decenas de miles de contactos.
Este módulo lo "hidrata" de vuelta a una lista de contactos con la misma
forma de siempre (name, email, lists, rubros, owners, sequences...), para que
los demás scripts (refresh_replies.py, refresh_sequences.py) no tengan que
conocer el formato interno.

El dashboard (index.html) hace exactamente la misma hidratación en JavaScript.
"""
import json
import os

LINKEDIN_PREFIX = "http://www.linkedin.com/in/"

# Orden de columnas de cada contacto en data.json v2 (DATA["contacts"] es una
# lista de filas; cada fila es una lista con estos campos en este orden).
CONTACT_COLUMNS = [
    "id", "name", "title", "role_idx", "org_idx", "city_idx", "country_idx",
    "email", "email_status_idx", "phone", "linkedin", "list_idxs", "seq_idxs",
]


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_raw(path=None):
    path = path or os.path.join(repo_root(), "data.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def hydrate(data):
    """Devuelve la lista de contactos como diccionarios, acepte el formato
    antiguo (v1, lista de objetos) o el nuevo (v2, compacto)."""
    if data.get("version") != 2:
        return data.get("contacts", [])

    d = data["dict"]
    lists = data["lists"]
    seqs = data.get("sequence_refs", [])
    out = []
    for row in data["contacts"]:
        r = dict(zip(CONTACT_COLUMNS, row))
        org = d["orgs"][r["org_idx"]] if r["org_idx"] is not None else [None] * 5
        my_lists = [lists[i] for i in (r["list_idxs"] or [])]
        linkedin = r["linkedin"]
        if linkedin and not linkedin.startswith("http"):
            linkedin = LINKEDIN_PREFIX + linkedin
        out.append({
            "id": r["id"],
            "name": r["name"],
            "title": r["title"] or "N/A",
            "role": d["roles"][r["role_idx"]],
            "company": org[0] or "N/A",
            "city": d["cities"][r["city_idx"]],
            "country": d["countries"][r["country_idx"]],
            "email": r["email"],
            "email_status": d["email_statuses"][r["email_status_idx"]],
            "phone": r["phone"],
            "linkedin_url": linkedin,
            "lists": [l["name"] for l in my_lists],
            "rubros": sorted({l["rubro"] for l in my_lists}),
            "owners": sorted({l["owner"] for l in my_lists}),
            "sequences": [seqs[i]["id"] for i in (r["seq_idxs"] or [])],
            "company_website": org[1],
            "company_industry": org[2],
            "company_size": org[3],
            "apollo_organization_id": org[4],
            "contact_source": "Apollo — " + (", ".join(l["name"] for l in my_lists) or "N/A"),
        })
    return out


def load_contacts(path=None):
    return hydrate(load_raw(path))
