# Desplegar la integración HubSpot

Esto crea un Worker gratuito en Cloudflare que hace de intermediario entre tu
dashboard (GitHub Pages, estático) y la API de HubSpot. El token de HubSpot
vive solo aquí — nunca en el navegador.

## 0. Requisitos
- Cuenta gratuita en https://dash.cloudflare.com (si no tienes una).
- Tu Private App Token de HubSpot (Settings → Integrations → Private Apps).
  Asegúrate de que el Private App tenga estos scopes habilitados:
  `crm.objects.contacts.read`, `crm.objects.contacts.write`,
  `crm.objects.companies.read`, `crm.objects.companies.write`,
  `crm.schemas.contacts.write`, `crm.schemas.companies.write`.
- Node.js instalado (para `npx wrangler`).

## 1. Instalar wrangler y autenticarte

```bash
cd hubspot-worker
npx wrangler login
```

## 2. Crear el namespace de KV (donde se guarda el estado de sincronización)

```bash
npx wrangler kv namespace create SYNC_KV
```

Copia el `id` que te devuelve y pégalo en `wrangler.toml`, en:
```toml
[[kv_namespaces]]
binding = "SYNC_KV"
id = "PEGA_AQUI_EL_ID"
```

## 3. Configurar el token de HubSpot como secret

```bash
npx wrangler secret put HUBSPOT_TOKEN
```
Pega tu Private App Token cuando te lo pida (no se guarda en ningún archivo del repo).

## 4. Revisar `ALLOWED_ORIGIN` en `wrangler.toml`

Debe ser exactamente el origen de tu GitHub Pages, sin barra final:
```toml
ALLOWED_ORIGIN = "https://ljamasmie.github.io"
```

## 5. Desplegar

```bash
npx wrangler deploy
```

Te dará una URL tipo `https://apprecio-hubspot-sync.<tu-cuenta>.workers.dev`.

## 6. Crear las propiedades personalizadas en HubSpot (una sola vez)

```bash
curl -X POST https://apprecio-hubspot-sync.<tu-cuenta>.workers.dev/setup-properties
```

Esto crea (si no existen ya) las propiedades personalizadas en Contactos y
Empresas: Apollo Contact ID, Apollo Company ID, Lead Source, Original List,
Industry Segment, Dashboard Source, LinkedIn URL.

## 7. Conectar el dashboard con el Worker

Abre `index.html` y busca la línea:
```js
const HUBSPOT_WORKER_URL = 'https://REEMPLAZA-CON-TU-WORKER.workers.dev';
```
Reemplázala con la URL real que te dio `wrangler deploy` (sin barra final).
Haz commit y push — GitHub Pages se actualiza solo.

## 8. Probar

1. Abre el dashboard → pestaña Contactos.
2. Deberías ver el indicador 🟢 HubSpot connected arriba de la tabla (o 🔴
   si algo falla — revisa que el token y los scopes sean correctos).
3. Haz clic en "Crear en HubSpot" en un contacto. Debe pasar por
   ⏳ Creando... → ✓ En HubSpot, con un link "Ver en HubSpot ↗".
4. Prueba la selección múltiple + "Crear seleccionados en HubSpot".

## Notas sobre límites y datos

- `data.json` sigue viniendo solo de Apollo — esta integración nunca lo
  modifica. El estado de HubSpot vive aparte, en KV.
- El script `scripts/refresh_data.py` ahora también trae `company_website`,
  `company_industry`, `company_size` y `apollo_organization_id` desde Apollo
  (campos que Apollo ya devuelve en el objeto `organization` de cada
  contacto) para poder mapearlos a HubSpot. No se muestran en el dashboard,
  solo se usan al crear el contacto/empresa en HubSpot.
- La detección de duplicados de empresa usa el dominio (de `company_website`
  o, si falta, el dominio del email corporativo — excluyendo proveedores
  como gmail/hotmail/outlook). Si Apollo no trae website para una empresa,
  no se podrá crear/asociar la empresa automáticamente para ese contacto
  (el contacto sí se crea igual).
- El Worker respeta el rate limit de HubSpot metiendo una pequeña pausa
  entre contactos en las cargas masivas.
