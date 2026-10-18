# Logos de marca (Dúo Noticias)

El motor usa estos dos archivos, que se configuran en `src/brand/brand.config.ts`:

| Archivo | Uso | Estado actual |
| --- | --- | --- |
| `logo-horizontal.png` | Firma en reels, posts y cierre (isotipo + "DÚO NOTICIAS") | Extraído de `media/PlantillaPublicaciones.png` (672×144 px). Aprobado como oficial el 17/10/2026 |
| `logo-mark.png` | Slides de carrusel y espacios chicos (solo el loro) | Extraído del mismo archivo (139×144 px). Aprobado como oficial el 17/10/2026 |

## Cómo reemplazarlos por los oficiales

1. Exportá desde el archivo original (AI, SVG o PDF) estos PNG con fondo transparente:
   - `logo-horizontal.png`: versión **blanca**, al menos **2000 px de ancho** y sin márgenes vacíos alrededor.
   - `logo-mark.png`: versión **blanca**, al menos **800 px de alto** y recortada al isotipo.
2. Reemplazá los archivos con los **mismos nombres**.
3. Si cambió la proporción, actualizá `horizontalAspect` y `markAspect` en `src/brand/brand.config.ts` (ancho ÷ alto).
4. El próximo render reconstruye el bundle solo, porque detecta el cambio en `public/`.

## Opcionales que suman

- `logo-horizontal-color.png`: versión a color para fondos claros. Hoy los fondos claros (panel papel, slide de texto) usan el logo blanco sobre un bloque violeta.
- Guía de colores oficial. Hoy se usan el violeta `#361957` y el ámbar `#FFB700`, medidos de la plantilla.
