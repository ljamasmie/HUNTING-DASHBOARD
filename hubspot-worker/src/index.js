/**
 * Worker de integración HubSpot para el dashboard "Apprecio España".
 *
 * Responsabilidad: ser el único sitio donde vive el token privado de HubSpot.
 * El frontend (GitHub Pages, estático) nunca ve ese token — solo llama a
 * estos endpoints.
 *
 * Endpoints:
 *   GET  /health            -> { connected, portalId, hubId }
 *   GET  /status            -> { "<apolloContactId>": {status, hubspot_contact_id, ...}, ... }
 *   POST /setup-properties  -> crea (idempotente) las propiedades personalizadas en HubSpot
 *   POST /upsert            -> body: { contacts: [ {...contactObjectFromDataJson} ] }
 *                               devuelve { results: { "<id>": {status, ...} } }
 *
 * Bindings esperados (ver wrangler.toml):
 *   - KV namespace: SYNC_KV
 *   - Secret:       HUBSPOT_TOKEN   (wrangler secret put HUBSPOT_TOKEN)
 *   - Var:          ALLOWED_ORIGIN  (p.ej. https://ljamasmie.github.io)
 */

const HUBSPOT_API = "https://api.hubapi.com";
const PROPERTY_GROUP = "apollo_dashboard";

const CONTACT_PROPS = [
  { name: "apollo_contact_id", label: "Apollo Contact ID", type: "string", fieldType: "text" },
  { name: "apollo_company_id", label: "Apollo Company ID", type: "string", fieldType: "text" },
  { name: "apollo_lead_source", label: "Lead Source", type: "string", fieldType: "text" },
  { name: "apollo_original_list", label: "Original List", type: "string", fieldType: "text" },
  { name: "apollo_industry_segment", label: "Industry Segment", type: "string", fieldType: "text" },
  { name: "apollo_dashboard_source", label: "Dashboard Source", type: "string", fieldType: "text" },
  { name: "apollo_linkedin_url", label: "Apollo LinkedIn URL", type: "string", fieldType: "text" },
];

const COMPANY_PROPS = [
  { name: "apollo_organization_id", label: "Apollo Company ID", type: "string", fieldType: "text" },
];

const PERSONAL_EMAIL_DOMAINS = new Set([
  "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com",
  "live.com", "aol.com", "protonmail.com", "hotmail.es", "yahoo.es",
]);

// ---------- helpers ----------

function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

function json(data, env, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(env) },
  });
}

async function hubspotFetch(path, env, opts = {}) {
  const res = await fetch(HUBSPOT_API + path, {
    ...opts,
    headers: {
      Authorization: `Bearer ${env.HUBSPOT_TOKEN}`,
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });
  const text = await res.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { raw: text };
  }
  if (!res.ok) {
    const err = new Error(body.message || `HubSpot API error ${res.status}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

function extractDomain(website, email) {
  if (website) {
    try {
      const withProto = website.startsWith("http") ? website : `https://${website}`;
      const host = new URL(withProto).hostname.replace(/^www\./, "");
      if (host) return host;
    } catch {
      /* ignore parse errors */
    }
  }
  if (email && email.includes("@")) {
    const domain = email.split("@")[1].toLowerCase();
    if (domain && !PERSONAL_EMAIL_DOMAINS.has(domain)) return domain;
  }
  return null;
}

async function getPortalId(env) {
  const cached = await env.SYNC_KV.get("meta:portal_id");
  if (cached) return cached;
  const info = await fetch(`${HUBSPOT_API}/oauth/v1/access-tokens/${env.HUBSPOT_TOKEN}`).then((r) => r.json());
  const portalId = info.hub_id || info.hubId;
  if (portalId) await env.SYNC_KV.put("meta:portal_id", String(portalId));
  return portalId;
}

// ---------- core logic ----------

async function upsertOneContact(rec, env) {
  if (!rec || !rec.id) throw new Error("Falta el id del contacto (Apollo Contact ID).");

  let hubspotContactId = null;
  let existed = false;

  if (rec.email) {
    const search = await hubspotFetch("/crm/v3/objects/contacts/search", env, {
      method: "POST",
      body: JSON.stringify({
        filterGroups: [{ filters: [{ propertyName: "email", operator: "EQ", value: rec.email }] }],
        properties: ["email"],
        limit: 1,
      }),
    });
    if (search.results && search.results.length) {
      hubspotContactId = search.results[0].id;
      existed = true;
    }
  }

  // --- empresa: buscar/crear y asociar ---
  let hubspotCompanyId = null;
  const domain = extractDomain(rec.company_website, rec.email);
  if (domain) {
    const compSearch = await hubspotFetch("/crm/v3/objects/companies/search", env, {
      method: "POST",
      body: JSON.stringify({
        filterGroups: [{ filters: [{ propertyName: "domain", operator: "EQ", value: domain }] }],
        properties: ["name", "domain"],
        limit: 1,
      }),
    });
    if (compSearch.results && compSearch.results.length) {
      hubspotCompanyId = compSearch.results[0].id;
    } else if (rec.company && rec.company !== "N/A") {
      const compProps = stripUndefined({
        name: rec.company,
        domain,
        industry: rec.company_industry || undefined,
        numberofemployees: rec.company_size ? String(rec.company_size) : undefined,
        apollo_organization_id: rec.apollo_organization_id ? String(rec.apollo_organization_id) : undefined,
      });
      const compCreate = await hubspotFetch("/crm/v3/objects/companies", env, {
        method: "POST",
        body: JSON.stringify({ properties: compProps }),
      });
      hubspotCompanyId = compCreate.id;
    }
  }

  // --- contacto: crear si no existía ---
  if (!hubspotContactId) {
    const parts = (rec.name || "").trim().split(/\s+/);
    const firstname = parts.shift() || rec.name || "";
    const lastname = parts.join(" ");

    const props = stripUndefined({
      firstname,
      lastname,
      email: rec.email || undefined,
      phone: rec.phone || undefined,
      jobtitle: rec.title && rec.title !== "N/A" ? rec.title : undefined,
      company: rec.company && rec.company !== "N/A" ? rec.company : undefined,
      website: rec.company_website || undefined,
      city: rec.city && rec.city !== "N/A" ? rec.city : undefined,
      country: rec.country && rec.country !== "N/A" ? rec.country : undefined,
      industry: rec.company_industry || undefined,
      apollo_contact_id: String(rec.id),
      apollo_company_id: rec.apollo_organization_id ? String(rec.apollo_organization_id) : undefined,
      apollo_lead_source: "Apollo → Apprecio Dashboard",
      apollo_original_list: (rec.lists || []).join(", ") || undefined,
      apollo_industry_segment: (rec.rubros || []).join(", ") || undefined,
      apollo_dashboard_source: "Apprecio Dashboard",
      apollo_linkedin_url: rec.linkedin_url || undefined,
    });

    if (!props.email && !props.firstname) {
      throw new Error("El contacto no tiene email ni nombre suficiente para crearlo en HubSpot.");
    }

    const created = await hubspotFetch("/crm/v3/objects/contacts", env, {
      method: "POST",
      body: JSON.stringify({ properties: props }),
    });
    hubspotContactId = created.id;
  }

  // --- asociar contacto <-> empresa ---
  if (hubspotCompanyId && hubspotContactId) {
    await hubspotFetch(
      `/crm/v4/objects/contacts/${hubspotContactId}/associations/default/companies/${hubspotCompanyId}`,
      env,
      { method: "PUT" }
    );
  }

  const portalId = await getPortalId(env);
  const url = portalId
    ? `https://app.hubspot.com/contacts/${portalId}/record/0-1/${hubspotContactId}`
    : null;

  const prevRaw = await env.SYNC_KV.get(`contact:${rec.id}`);
  const prev = prevRaw ? JSON.parse(prevRaw) : {};

  const state = {
    status: existed ? "already_exists" : "created",
    hubspot_contact_id: hubspotContactId,
    hubspot_company_id: hubspotCompanyId,
    hubspot_url: url,
    created_date: prev.created_date || new Date().toISOString(),
    last_synced: new Date().toISOString(),
    error: null,
  };
  await env.SYNC_KV.put(`contact:${rec.id}`, JSON.stringify(state));
  return state;
}

function stripUndefined(obj) {
  const out = {};
  for (const k in obj) if (obj[k] !== undefined && obj[k] !== null && obj[k] !== "") out[k] = obj[k];
  return out;
}

async function ensureGroup(objectType, env) {
  try {
    await hubspotFetch(`/crm/v3/properties/${objectType}/groups`, env, {
      method: "POST",
      body: JSON.stringify({ name: PROPERTY_GROUP, label: "Apollo / Apprecio Dashboard" }),
    });
  } catch (e) {
    if (e.status !== 409) throw e; // 409 = ya existe
  }
}

async function ensureProperty(objectType, prop, env) {
  try {
    await hubspotFetch(`/crm/v3/properties/${objectType}`, env, {
      method: "POST",
      body: JSON.stringify({ ...prop, groupName: PROPERTY_GROUP }),
    });
    return "created";
  } catch (e) {
    if (e.status === 409) return "already_existed";
    throw e;
  }
}

// ---------- route handlers ----------

async function handleHealth(env) {
  try {
    const portalId = await getPortalId(env);
    const account = await hubspotFetch("/account-info/v3/details", env).catch(() => null);
    return { connected: true, portalId, accountName: account?.companyName || null };
  } catch (e) {
    return { connected: false, error: e.message };
  }
}

async function handleStatus(env) {
  const list = await env.SYNC_KV.list({ prefix: "contact:" });
  const out = {};
  for (const key of list.keys) {
    const val = await env.SYNC_KV.get(key.name);
    if (val) out[key.name.replace("contact:", "")] = JSON.parse(val);
  }
  return out;
}

async function handleSetupProperties(env) {
  await ensureGroup("contacts", env);
  await ensureGroup("companies", env);
  const results = { contacts: {}, companies: {} };
  for (const p of CONTACT_PROPS) results.contacts[p.name] = await ensureProperty("contacts", p, env);
  for (const p of COMPANY_PROPS) results.companies[p.name] = await ensureProperty("companies", p, env);
  return results;
}

async function handleUpsert(request, env) {
  const body = await request.json();
  const contacts = Array.isArray(body.contacts) ? body.contacts : [];
  const results = {};
  for (const rec of contacts) {
    try {
      results[rec.id] = await upsertOneContact(rec, env);
    } catch (e) {
      const errState = {
        status: "error",
        error: e.message || "Error desconocido",
        last_synced: new Date().toISOString(),
      };
      await env.SYNC_KV.put(`contact:${rec.id}`, JSON.stringify(errState));
      results[rec.id] = errState;
    }
    // pequeño respiro entre contactos para no chocar con el rate limit de HubSpot
    if (contacts.length > 1) await new Promise((r) => setTimeout(r, 150));
  }
  return results;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(env) });
    }

    try {
      if (url.pathname === "/health" && request.method === "GET") {
        return json(await handleHealth(env), env);
      }
      if (url.pathname === "/status" && request.method === "GET") {
        return json(await handleStatus(env), env);
      }
      if (url.pathname === "/setup-properties" && request.method === "POST") {
        return json(await handleSetupProperties(env), env);
      }
      if (url.pathname === "/upsert" && request.method === "POST") {
        return json({ results: await handleUpsert(request, env) }, env);
      }
      return json({ error: "Not found" }, env, 404);
    } catch (e) {
      return json({ error: e.message || "Internal error" }, env, 500);
    }
  },
};
