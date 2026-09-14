#!/usr/bin/env python3
"""
Cruza el Gmail de Lorenzo Jamasmie contra los contactos de Apollo (data.json)
y genera replies.json: qué contactos respondieron, con el texto del hilo completo.

NO hace ningún análisis con IA — solo detecta si hubo respuesta y guarda el
contenido del email para que el dashboard lo muestre tal cual.

Requiere 3 secrets/variables de entorno:
    GMAIL_CLIENT_ID
    GMAIL_CLIENT_SECRET
    GMAIL_REFRESH_TOKEN
(ver README.md para cómo generarlos con Google Cloud + OAuth Playground)

Uso local:
    export GMAIL_CLIENT_ID="..."
    export GMAIL_CLIENT_SECRET="..."
    export GMAIL_REFRESH_TOKEN="..."
    python3 scripts/refresh_replies.py

El workflow de GitHub Actions llama a este script automáticamente.
"""
import os
import sys
import json
import base64
import datetime
import urllib.request
import urllib.error
import urllib.parse
import re

GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN")

if not all([GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN]):
    print("ERROR: faltan GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN", file=sys.stderr)
    sys.exit(1)

DAYS_BACK = int(os.environ.get("REPLIES_DAYS", "30"))

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def get_access_token():
    data = urllib.parse.urlencode({
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": GMAIL_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


def gmail_get(access_token, path, params=None):
    url = f"{GMAIL_API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_inbox_message_ids(access_token, days_back):
    ids = []
    page_token = None
    query = f"in:inbox newer_than:{days_back}d"
    while True:
        params = {"q": query, "maxResults": 100}
        if page_token:
            params["pageToken"] = page_token
        data = gmail_get(access_token, "/messages", params)
        ids.extend(m["id"] for m in data.get("messages", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids


def get_message_metadata(access_token, msg_id):
    return gmail_get(access_token, f"/messages/{msg_id}", {
        "format": "metadata",
        "metadataHeaders": ["From", "To", "Subject", "Date"],
    })


def get_message_full(access_token, msg_id):
    return gmail_get(access_token, f"/messages/{msg_id}", {"format": "full"})


def header_value(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return None


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def extract_email(header_value_str):
    if not header_value_str:
        return None
    m = EMAIL_RE.search(header_value_str)
    return m.group(0).lower() if m else None


def decode_body_part(data_b64):
    if not data_b64:
        return ""
    padded = data_b64 + "=" * (-len(data_b64) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_plain_text(payload):
    """Busca recursivamente la parte text/plain del mensaje."""
    if payload.get("mimeType") == "text/plain":
        return decode_body_part(payload.get("body", {}).get("data"))
    for part in payload.get("parts", []) or []:
        text = extract_plain_text(part)
        if text:
            return text
    # último recurso: si es text/html, devolvemos igual (mejor que nada)
    if payload.get("mimeType") == "text/html":
        html = decode_body_part(payload.get("body", {}).get("data"))
        return re.sub("<[^<]+?>", " ", html)
    return ""


def main():
    # 1. Cargar contactos de Apollo desde data.json
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_json_path = os.path.join(repo_root, "data.json")
    with open(data_json_path, encoding="utf-8") as f:
        apollo_data = json.load(f)

    contacts_by_email = {}
    for c in apollo_data.get("contacts", []):
        if c.get("email"):
            contacts_by_email[c["email"].lower()] = c

    print(f"Contactos de Apollo con email: {len(contacts_by_email)}")

    # 2. Autenticar con Gmail
    access_token = get_access_token()

    # 3. Listar mensajes recientes del inbox
    print(f"Buscando mensajes del inbox de los últimos {DAYS_BACK} días...")
    msg_ids = list_inbox_message_ids(access_token, DAYS_BACK)
    print(f"  {len(msg_ids)} mensajes encontrados")

    # 4. Metadata de cada uno, filtrando por remitentes que matcheen Apollo
    matched_threads = {}  # threadId -> list of message dicts
    for i, mid in enumerate(msg_ids):
        try:
            meta = get_message_metadata(access_token, mid)
        except urllib.error.HTTPError as e:
            print(f"  Aviso: no se pudo leer mensaje {mid} ({e.code})", file=sys.stderr)
            continue
        from_email = extract_email(header_value(meta, "From"))
        if not from_email or from_email not in contacts_by_email:
            continue
        matched_threads.setdefault(meta["threadId"], []).append(meta)
        if (i + 1) % 50 == 0:
            print(f"  revisados {i + 1}/{len(msg_ids)}...")

    print(f"Hilos con al menos un mensaje de un contacto Apollo: {len(matched_threads)}")

    # 5. Para cada hilo con match, traer el cuerpo completo de los mensajes
    #    del contacto (no hace falta el cuerpo de los que envió Lorenzo)
    replies = []
    for thread_id, metas in matched_threads.items():
        # nos quedamos con el primer mensaje del contacto en el hilo como "la respuesta"
        contact_meta = metas[0]
        from_email = extract_email(header_value(contact_meta, "From"))
        contact = contacts_by_email[from_email]

        try:
            full = get_message_full(access_token, contact_meta["id"])
            body_text = extract_plain_text(full.get("payload", {})).strip()
        except Exception as e:
            print(f"  Aviso: no se pudo leer cuerpo de {contact_meta['id']} ({e})", file=sys.stderr)
            body_text = contact_meta.get("snippet", "")

        replies.append({
            "contact_email": from_email,
            "contact_name": contact.get("name"),
            "contact_title": contact.get("title"),
            "company": contact.get("company"),
            "lists": contact.get("lists", []),
            "rubros": contact.get("rubros", []),
            "thread_id": thread_id,
            "message_id": contact_meta["id"],
            "subject": header_value(contact_meta, "Subject"),
            "date": header_value(contact_meta, "Date"),
            "snippet": contact_meta.get("snippet", ""),
            "body_text": body_text[:5000],  # límite razonable
        })

    replies.sort(key=lambda r: r.get("date") or "", reverse=True)

    replied_emails = {r["contact_email"] for r in replies}

    data_blob = {
        "replies": replies,
        "meta": {
            "total_replies": len(replies),
            "unique_contacts_replied": len(replied_emails),
            "days_scanned": DAYS_BACK,
            "inbox_messages_scanned": len(msg_ids),
        },
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    out_path = os.path.join(repo_root, "replies.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data_blob, f, ensure_ascii=False)

    print(f"OK -> {out_path} ({len(replies)} respuestas de {len(replied_emails)} contactos)")


if __name__ == "__main__":
    main()
