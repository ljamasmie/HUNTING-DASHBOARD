# Apprecio España — CRM Intelligence Dashboard

Dashboard de prospección comercial para Apprecio España, alimentado con datos reales de Apollo: **todas las listas de difusión de España del equipo** (Lorenzo Jamasmie, Joao Guerra, Maria Pelaye...), con filtro por dueño y por secuencia.

## Contenido

- `index.html` — el dashboard (HTML + CSS + JS). Carga los datos desde `data.json` con `fetch()` en cada visita, así que no hay que tocar el HTML para actualizar los datos. Solo depende de Chart.js vía CDN (`cdnjs.cloudflare.com`).
- `data.json` — los datos (contactos, empresas, listas). Se regenera automáticamente.
- `scripts/refresh_data.py` — script que consulta la API de Apollo y regenera `data.json`.
- `.github/workflows/refresh.yml` — GitHub Action programado que ejecuta el script y hace commit de los cambios.

## Ver el dashboard

### Opción A — Abrir directo
Descarga `index.html` y ábrelo con doble clic en cualquier navegador.

### Opción B — GitHub Pages (recomendado para compartir por link)
1. Crea el repo en GitHub y sube este `index.html` (y este `README.md`) a la raíz o a una carpeta `/docs`.
2. Ve a **Settings → Pages**.
3. En "Source" elige la rama (`main`) y la carpeta (`/root` o `/docs` según dónde subiste el archivo).
4. Guarda. GitHub te dará una URL tipo `https://<usuario>.github.io/<repo>/`.

```bash
git init
git add index.html README.md
git commit -m "Dashboard prospección Apprecio España"
git branch -M main
git remote add origin https://github.com/<tu-usuario>/<tu-repo>.git
git push -u origin main
```

Luego activa Pages desde la configuración del repo.

## Datos

- **Fuente:** Apollo. Entran todas las listas del equipo cuyo nombre lleve la palabra suelta `ES`, `Spain` o `España` (de contactos y de empresas), más las de `INCLUDE_LIST_IDS` en `scripts/refresh_data.py`. Para sacar una lista, añade su ID a `EXCLUDE_LIST_IDS`.
- **Dueño:** el usuario de Apollo que creó cada lista (nombres leídos de Apollo Users).
- **Secuencias:** por cada contacto se guardan las secuencias de Apollo en las que está; `sequences.json` trae nombre, dueño y métricas de cada una.
- **Filtro global** (barra bajo las pestañas): *Dueño* filtra por dueño de la lista (en la pestaña Secuencias, por dueño de la secuencia) y *Secuencia* deja solo los contactos/respuestas de esa secuencia. Se recuerda en el navegador.
- **Rubro:** derivado del nombre de cada lista (`RUBRO_RULES` en `scripts/refresh_data.py`). Las listas sin sector explícito se agrupan como "RRHH (general)", "Comercial (general)" o "Compras (general)".
- **Formato de `data.json` (v2):** compacto (columnas + diccionarios) para que ~80.000 contactos pesen ~13 MB (~2 MB comprimido). `scripts/dashboard_data.py` y el propio `index.html` lo convierten de vuelta a contactos normales. El dashboard sigue leyendo el formato antiguo si hace falta.
- **Respuestas:** salen del Gmail conectado en los secrets (`GMAIL_*`). Solo aparecen respuestas que llegaron a ese buzón.
- La fecha "datos al ..." de la cabecera viene del campo `generated_at` de `data.json`.

## Actualización automática de los datos

El repo incluye un **GitHub Action programado** (`.github/workflows/refresh.yml`) que corre `scripts/refresh_data.py` cada hora, consulta la API de Apollo lista por lista (~900 llamadas, 10–15 min) y hace commit de `data.json` si hubo cambios. Al estar `index.html` separado de los datos, el dashboard se actualiza solo con recargar la página — no hay que tocar el HTML ni redeployar nada.

### Configurar el secret de Apollo (una sola vez)

1. En Apollo: **Settings → Integrations → API** → genera/copia tu API key.
2. En el repo de GitHub: **Settings → Secrets and variables → Actions → New repository secret**.
   - Name: `APOLLO_API_KEY`
   - Value: la key de Apollo.
3. Listo. El workflow ya puede autenticarse.

### Probarlo manualmente

Puedes lanzarlo sin esperar al cron: en el repo, pestaña **Actions → Refrescar datos de Apollo → Run workflow**.

### Cambiar la frecuencia

Edita la línea `cron` en `.github/workflows/refresh.yml`. Ejemplos:
- Cada 6 horas: `0 */6 * * *`
- Cada hora: `0 * * * *`
- Dos veces al día (8am y 6pm UTC): `0 8,18 * * *`

### Correrlo en local (para probar antes de subirlo)

```bash
export APOLLO_API_KEY="tu_api_key"
pip install --upgrade pip  # el script solo usa la librería estándar de Python, no hace falta nada más
python3 scripts/refresh_data.py
```

Esto regenera `data.json` en la raíz del repo.

### Si alguien crea, borra o renombra una lista de España en Apollo

No hay que tocar nada: el script detecta solo las listas cuyo nombre lleva `ES`, `Spain` o `España`. Para forzar una lista que no sigue ese formato, añade su ID (de la URL `https://app.apollo.io/#/lists/<ID>`) a `INCLUDE_LIST_IDS`; para excluir una, a `EXCLUDE_LIST_IDS`.

### Alternativa sin GitHub Actions (manual)

Si prefieres no usar Actions, puedes correr `python3 scripts/refresh_data.py` en tu máquina cuando quieras y subir el `data.json` resultante con un commit normal.
