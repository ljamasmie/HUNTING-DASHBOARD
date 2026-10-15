// ============================================================
// Añadir al Cloudflare Worker "hunting-dashboard" (nueva ruta POST /deal)
// Ajusta TOKEN al nombre del secreto que ya usa tu Worker para HubSpot
// (el mismo que usa /upsert). Reutiliza tu helper de CORS si ya tienes uno.
// ============================================================
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};
const json = (o, status = 200) =>
  new Response(JSON.stringify(o), { status, headers: { 'Content-Type': 'application/json', ...CORS } });

async function hs(env, path, init = {}) {
  const r = await fetch('https://api.hubapi.com' + path, {
    ...init,
    headers: { Authorization: 'Bearer ' + env.HUBSPOT_TOKEN, 'Content-Type': 'application/json', ...(init.headers || {}) },
  });
  const t = await r.text();
  let d; try { d = JSON.parse(t); } catch { d = { raw: t }; }
  if (!r.ok) throw new Error(d.message || ('HubSpot ' + r.status));
  return d;
}

// En tu fetch(request, env): añade antes del 404 final:
//   if (url.pathname === '/deal' && request.method === 'POST') return handleDeal(request, env);
//   (y asegura que OPTIONS responde con CORS)
export async function handleDeal(request, env) {
  try {
    const b = await request.json();
    if (!b.dealname) return json({ status: 'error', error: 'Falta dealname' }, 400);

    // 1) Evitar duplicados por nombre
    const found = await hs(env, '/crm/v3/objects/deals/search', {
      method: 'POST',
      body: JSON.stringify({ filterGroups: [{ filters: [{ propertyName: 'dealname', operator: 'EQ', value: b.dealname }] }], limit: 1 }),
    });
    if (found.results && found.results.length) {
      const id = found.results[0].id;
      return json({ status: 'already_exists', id, url: await dealUrl(env, id) });
    }

    // 2) Pipeline por defecto y primera etapa
    const pl = await hs(env, '/crm/v3/pipelines/deals');
    const pipe = pl.results.find(p => p.default) || pl.results[0];
    const stage = pipe.stages.sort((a, c) => a.displayOrder - c.displayOrder)[0];

    // 3) Crear negocio
    const deal = await hs(env, '/crm/v3/objects/deals', {
      method: 'POST',
      body: JSON.stringify({ properties: {
        dealname: b.dealname, amount: String(b.amount ?? 500),
        pipeline: pipe.id, dealstage: stage.id,
        description: (b.description || '').slice(0, 60000),
      } }),
    });

    // 4) Asociar a la empresa si existe (por dominio)
    if (b.domain) {
      try {
        const c = await hs(env, '/crm/v3/objects/companies/search', {
          method: 'POST',
          body: JSON.stringify({ filterGroups: [{ filters: [{ propertyName: 'domain', operator: 'EQ', value: b.domain }] }], limit: 1 }),
        });
        if (c.results && c.results.length)
          await hs(env, `/crm/v4/objects/deals/${deal.id}/associations/default/companies/${c.results[0].id}`, { method: 'PUT' });
      } catch (_) { /* la asociación es opcional */ }
    }
    return json({ status: 'created', id: deal.id, url: await dealUrl(env, deal.id) });
  } catch (e) {
    return json({ status: 'error', error: e.message }, 500);
  }
}

async function dealUrl(env, id) {
  try {
    const a = await hs(env, '/account-info/v3/details');
    return `https://app.hubspot.com/contacts/${a.portalId}/record/0-3/${id}`;
  } catch { return null; }
}
