# Apprecio España — CRM Intelligence Dashboard

Dashboard de prospección comercial para Apprecio España, alimentado con datos reales de Apollo (listas de difusión propiedad de Lorenzo Jamasmie).

## Contenido

- `index.html` — dashboard completo, autocontenido (HTML + CSS + JS + datos embebidos). Solo depende de Chart.js vía CDN (`cdnjs.cloudflare.com`), el resto funciona sin conexión.

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

- **Fuente:** Apollo, vía las 4 listas propiedad de Lorenzo Jamasmie (verificado por `owner_id` en Apollo Users, sin mezclar contactos de otros usuarios del equipo).
- **Snapshot:** 14 de septiembre de 2026. Los datos están embebidos en el HTML — el dashboard **no se actualiza en vivo**. Para refrescarlo hay que volver a exportar/consultar Apollo y regenerar el archivo.
- **Rubro:** derivado del nombre de cada lista de Apollo (Contact Centers, Seguros, Outsourcing), ya que Apollo no tenía el campo de industria poblado en estos registros.
- **Actividad de secuencias** (contactados, respuestas, interesados): no disponible en el snapshot actual — Apollo no reporta esa actividad para estas listas, así que no se muestra información inventada.

## Actualizar los datos

El bloque de datos vive en un `<script type="application/json" id="apprecio-data">` dentro de `index.html`. Para refrescarlo:
1. Vuelve a consultar Apollo (API o exportación CSV) para las 4 listas.
2. Regenera el JSON con la misma estructura (`contacts`, `companies`, `lists`, `meta`).
3. Reemplaza el contenido de ese `<script>` y vuelve a subir el archivo.
