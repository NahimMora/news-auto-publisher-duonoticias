Actuá como un desarrollador senior Python especializado en scraping de medios,
automatización de publicaciones y pipelines de contenido para redes sociales.

Usa este proyecto como referencia que ya tiene el scrapping funcionando:
C:\Users\pc10\Desktop\AutoPublicadores\WebApp_HolaSalta

Base path del proyecto a modificar, actualmente esta funcionando muy bien, solo añade las funciones porpiamente dichas:
C:\Users\pc10\Desktop\AutoPublicadores\AutoPublicador_Duo

Este proyecto ya cuenta con:

- Scrapers funcionales
- Pipeline de procesamiento de noticias
- Procesamiento de imágenes (PIL / OpenCV)
- Procesamiento de videos tipo Paparazzi
- Publicación automática en Instagram y Facebook
- Agentes que transforman datos en textos para redes

Objetivo principal:
Extender el sistema para incorporar scraping de medios nacionales argentinos,
copiando la lógica de scraping usada para Noticias Argentinas (NA),
y conectarlo al pipeline completo de publicación.

---

### 1️⃣ Scraping (fase de obtención)

- Crear un nuevo scraper para medios nacionales argentinos
- Basarse en la estructura y estilo del scraper de Noticias Argentinas existente
- Priorizar scraping HTTP puro (requests / httpx / playwright si es necesario)
- Evitar Selenium salvo que sea estrictamente inevitable
- Extraer por noticia:
  - título
  - bajada/copete
  - cuerpo
  - fecha
  - autor (si existe)
  - imágenes
  - videos (si existen)
  - url original
  - medio de origen

- Normalizar la salida a un JSON estándar compatible con el pipeline actual
- Guardar los resultados en la carpeta data/ siguiendo el naming ya usado

---

### 2️⃣ Conexión al pipeline existente

- Integrar el nuevo scraper al flujo actual sin romper lógica previa
- Reutilizar:
  - validadores
  - deduplicación por hash o URL
  - control de errores
  - logs existentes

- El output del scraper debe ser consumido directamente por el módulo de agentes

---

### 3️⃣ Agente de transformación y decisión

Crear un agente que:

- Reciba el JSON crudo de la noticia
- Transforme los datos en:
  - Texto optimizado para Instagram
  - Lenguaje claro, directo y viral
  - Uso moderado de emojis
  - LEGACY: `ideologia_politica.md` no se usa en el runtime nuevo; la politica editorial vive en `config/editorial_policy.yaml`.
  - Pregunta o CTA final

- El agente debe evaluar si la noticia esta enfocada en algo sobre el gobierno de Javier Milei, Emilia Orozco, o relacionado a la politica nacional
- Si NO cumple el criterio:
  - Marcar la noticia como descartada
  - No continuar el pipeline
- Si SÍ cumple:
  - Marcar como aprobada
  - Pasar a edición de imagen/video

El agente debe ser fácilmente configurable mediante prompt o flags.

---

### 4️⃣ Edición de imágenes

- Reutilizar el tratamiento actual de imágenes
- Mantener:
  - Formato 4:5
  - Overlays
  - Logos
  - Gradientes
  - Watermarks
- No romper compatibilidad con plantillas actuales

---

### 5️⃣ Videos (si la noticia tiene video)

- Aplicar exactamente el mismo flujo que el proyecto Paparazzi
- Normalizar a formato Instagram
- Fondo difuminado si es necesario
- Mantener calidad y branding
- Integrar el video al post si existe

---

### 7️⃣ Estructura y calidad

- Código modular
- Funciones claras y reutilizables
- Nada hardcodeado
- Uso de config/env cuando corresponda
- Manejo robusto de errores (403, 404, timeouts, antibots)
- Comentarios técnicos breves y claros

---

Resultado esperado:
Un flujo end-to-end:
Scraping → Normalización → Agente (decisión + texto) → Edición media → Publicación Instagram

No explicar teoría.
Generar directamente el código necesario, respetando el estilo del proyecto existente.
