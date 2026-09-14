# Apprecio España — CRM Intelligence Dashboard

Dashboard de prospección comercial para Apprecio España, alimentado con datos reales de Apollo (listas de difusión propiedad de Lorenzo Jamasmie).

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

- **Fuente:** Apollo, vía las 4 listas propiedad de Lorenzo Jamasmie (`owner_id` verificado en Apollo Users, sin mezclar contactos de otros usuarios del equipo).
- **Rubro:** derivado del nombre de cada lista de Apollo (Contact Centers, Seguros, Outsourcing), ya que Apollo no tenía el campo de industria poblado en estos registros.
- **Actividad de secuencias** (contactados, respuestas, interesados): no disponible en el snapshot — Apollo no reporta esa actividad para estas listas, así que no se muestra información inventada.
- La fecha "datos al ..." que aparece en la cabecera del dashboard viene del campo `generated_at` de `data.json`.

## Actualización automática de los datos

El repo incluye un **GitHub Action programado** (`.github/workflows/refresh.yml`) que corre `scripts/refresh_data.py` todos los días a las 06:00 UTC, consulta la API de Apollo para las 4 listas y hace commit de `data.json` si hubo cambios. Al estar `index.html` separado de los datos, el dashboard se actualiza solo con recargar la página — no hay que tocar el HTML ni redeployar nada.

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

### Si Lorenzo crea, borra o renombra una lista en Apollo

El script apunta a 4 IDs de lista fijos (línea `LABEL_MAP` en `scripts/refresh_data.py`). Si cambian las listas:
1. En Apollo, abre la lista y copia el ID de la URL: `https://app.apollo.io/#/lists/<ID>`.
2. Actualiza `LABEL_MAP` (y `RUBRO_MAP` si aplica) en `scripts/refresh_data.py`.
3. Haz commit — la próxima corrida del workflow ya usará las listas nuevas.

### Alternativa sin GitHub Actions (manual)

Si prefieres no usar Actions, puedes correr `python3 scripts/refresh_data.py` en tu máquina cuando quieras y subir el `data.json` resultante con un commit normal.
