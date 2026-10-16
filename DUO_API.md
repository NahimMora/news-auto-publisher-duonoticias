# Duo Noticias API (Documentación completa)

## 1) Base URL
- Local: http://localhost:3000
- Todos los endpoints están bajo `/api`

## 2) Autenticación y llaves
### Admin
- Header requerido: `x-admin-key: <ADMIN_API_KEY>`
- Se valida contra `process.env.ADMIN_API_KEY`

### Pública
- Header requerido: `x-api-key: <PUBLIC_API_KEY>`
- Se valida en tabla `ApiKey` con `token` activo

## 3) Formato general de respuestas
### Éxito
```json
{ "data": ... }
```

### Éxito sin payload
```json
{ "ok": true }
```

### Error
```json
{ "error": "mensaje" }
```

### Error con validación (Zod)
```json
{ "error": { "formErrors": [], "fieldErrors": { "title": ["..."] } } }
```

## 4) Enum de categorías
- politics, sports, technology, entertainment, world, business, health

## 5) Reglas globales del modelo
- `slug` único por artículo.
- `isHero` solo puede estar activo en un artículo a la vez.
- `isFeatured` máximo 4 artículos activos al mismo tiempo.
- `breaking` se maneja con una lista fija de 5 IDs.
- `gallery` máximo 5 imágenes.

---

# ADMIN API

## 1) Artículos

### GET /api/admin/articles
Lista artículos para administración.

**Respuesta (data[]):**
```json
{
  "data": [
    {
      "id": "uuid",
      "title": "...",
      "slug": "...",
      "tag": "...",
      "description": "...",
      "category": "technology",
      "isActive": true,
      "isBreaking": false,
      "isHero": false,
      "isFeatured": true,
      "createdAt": "...",
      "publishedAt": "...",
      "author": { "name": "..." }
    }
  ]
}
```

### POST /api/admin/articles
Crea artículo.

**Reglas:**
- Si `slug` está vacío, se genera desde `title`.
- Si `isHero=true`, se limpia el hero anterior.
- Si `isFeatured=true` y ya hay 4 destacadas, **falla**.
  - **Excepción**: si `isHero=true` y `isFeatured=true`, se crea el hero y se baja `isFeatured` automáticamente.

**Body:**
```json
{
  "title": "Titulo",
  "slug": "mi-noticia",              // opcional
  "tag": "Ultimo momento",           // opcional
  "description": "Resumen...",
  "content": "Texto completo...",
  "category": "technology",
  "isActive": true,
  "isBreaking": false,
  "isHero": false,
  "isFeatured": true,
  "authorId": "u-admin-1",           // opcional
  "coverImageId": "media-id",        // opcional
  "publishedAt": "2026-01-29T12:00:00.000Z", // opcional
  "gallery": ["media-id-1", "media-id-2"],  // max 5
  "seo": { ... }
}
```

### GET /api/admin/articles/{id}
Obtiene artículo completo (incluye coverImage, seo, gallery).

### PATCH /api/admin/articles/{id}
Actualiza campos (todos opcionales).

### DELETE /api/admin/articles/{id}
Elimina un artículo.

### POST /api/admin/articles/bulk
Crea múltiples artículos.

**Body:** array o `{ items: [...] }`
**Reglas:**
- Solo 1 hero dentro del batch.
- Máximo 4 featured (sumando existentes + batch).
- Slug único autogenerado si no se envía.

---

## 2) Breaking News

### POST /api/admin/breaking
Setea breaking por lista fija de 5 IDs.

**Body:**
```json
{ "articleIds": ["id1","id2","id3","id4","id5"] }
```

---

## 3) Featured Layout

### POST /api/admin/featured
Resetea hero + featured y asigna nuevos.

**Body:**
```json
{ "heroId": "id", "featuredIds": ["id1","id2","id3","id4"] }
```

---

## 4) Media

### POST /api/admin/media
Crea media desde URL.

**Body:**
```json
{ "url": "https://...", "alt": "texto" }
```

### POST /api/admin/media/upload
Sube archivo local (multipart/form-data).

**Fields:**
- `file` (requerido)
- `alt` (opcional)

**Límite:** 8MB

---

## 5) Ads

### GET /api/admin/ads?placement=header|sidebar|inline|footer
### POST /api/admin/ads
### PATCH /api/admin/ads/{id}
### DELETE /api/admin/ads/{id}

**Body ejemplo:**
```json
{
  "name": "Banner principal",
  "placement": "header",
  "provider": "custom" | "google",
  "imageUrl": "https://...",
  "linkUrl": "https://...",
  "html": "<div>...",
  "googleSlot": "123",
  "googleFormat": "auto",
  "googleResponsive": true,
  "isActive": true,
  "order": 0
}
```

---

## 6) Metrics

### GET /api/admin/metrics?category=market|interest
### POST /api/admin/metrics
### PATCH /api/admin/metrics/{id}
### DELETE /api/admin/metrics/{id}

**Body ejemplo:**
```json
{
  "label": "Inflacion mensual",
  "value": "8,2%",
  "change": "+0,2%",
  "unit": "IPC",
  "category": "interest",
  "isActive": true,
  "order": 1,
  "sourceUrl": "https://..."
}
```

---

## 7) Stats / Analytics

### GET /api/admin/stats?from=YYYY-MM-DD&to=YYYY-MM-DD
Lista `StatsDaily` entre fechas.

### GET /api/admin/statistics
Devuelve agregados para dashboard:
- totalViews, avgCtr, publishedToday, totalArticles, totalUsers, activeUsers
- articlesByCategory
- topArticles
- dailyViews (últimos 7 días)

---

## 8) Users

### GET /api/admin/users
### POST /api/admin/users
### GET /api/admin/users/{id}
### PATCH /api/admin/users/{id}
### DELETE /api/admin/users/{id}

**Notas:**
- Roles: `admin` o `viewer`.
- No hay rol editor.

---

## 9) Newsletter

### GET /api/admin/newsletter
### POST /api/admin/newsletter
### GET /api/admin/newsletter/{id}
### PATCH /api/admin/newsletter/{id}
### DELETE /api/admin/newsletter/{id}

---

# PUBLIC API

## 1) Categorías
### GET /api/public/categories
Devuelve labels + slugs.

## 2) Noticias
### GET /api/public/news?category=business&limit=20&offset=0
- Devuelve artículos activos.
- Máximo limit: 50

### GET /api/public/news/{slug}
- Devuelve noticia completa + SEO + gallery.

## 3) Breaking
### GET /api/public/breaking
- Devuelve hasta 5 breaking.

## 4) Most Read
### GET /api/public/most-read?limit=3
- Devuelve top por `StatsDaily`.
- Si no hay stats, usa últimas noticias.

## 5) Metrics
### GET /api/public/metrics?category=market|interest&source=auto|manual
- `market + source=auto` usa live FX/crypto si hay respuesta.

## 6) Ads
### GET /api/public/ads?placement=header|sidebar|inline|footer

## 7) Newsletter
### POST /api/public/newsletter
**Body:**
```json
{ "email": "...", "name": "..." }
```

---

# SEO (detallado)

Campos disponibles (objeto `seo`):
- metaTitle, metaDescription
- canonicalUrl
- robots: index_follow | noindex_follow | index_nofollow | noindex_nofollow
- ogTitle, ogDescription, ogSiteName, ogLocale
- ogImageId, ogImageAlt, ogImageWidth, ogImageHeight, ogImageType
- twitterTitle, twitterDescription, twitterImageId, twitterSite, twitterCreator
- publishedTime, modifiedTime
- keywords

Notas:
- Para previews rápidos (WhatsApp/Telegram), usar `ogTitle`, `ogDescription`, `ogImageId`.
- `ogImageId` y `twitterImageId` referencian Media existente.
- Si no hay ogImageId, se usa la portada si existe.

Ejemplo SEO completo:
```json
{
  "seo": {
    "metaTitle": "Duo Noticias | Título optimizado",
    "metaDescription": "Resumen optimizado para buscadores.",
    "canonicalUrl": "https://duonoticias.com/news/mi-noticia",
    "robots": "index_follow",
    "ogTitle": "Título para redes",
    "ogDescription": "Descripción para redes",
    "ogSiteName": "Duo Noticias",
    "ogLocale": "es_AR",
    "ogImageId": "media-id",
    "ogImageAlt": "Texto alternativo",
    "ogImageWidth": 1200,
    "ogImageHeight": 630,
    "ogImageType": "image/jpeg",
    "twitterTitle": "Título para X",
    "twitterDescription": "Descripción para X",
    "twitterImageId": "media-id",
    "twitterSite": "@duonoticias",
    "twitterCreator": "@autor",
    "publishedTime": "2026-01-29T12:00:00.000Z",
    "modifiedTime": "2026-01-29T14:30:00.000Z",
    "keywords": "duo, noticias, salta"
  }
}
```

---

### Implementación en el sitio
- El SEO se resuelve por publicación en `app/news/[id]/page.tsx` usando `generateMetadata`.
- Se usan estos campos cuando existen: metaTitle, metaDescription, canonicalUrl, robots, ogTitle, ogDescription, ogType, ogSiteName, ogLocale, ogImage*, twitterCard, twitterTitle, twitterDescription, twitterImage*, twitterSite, twitterCreator, publishedTime, modifiedTime, keywords.
- Fallbacks: si no hay SEO, se usan title/description/coverImage del artículo.
# Auth (NextAuth)
- /api/auth/[...nextauth] gestionado por NextAuth
- /api/auth/register para signup por email

---

# Códigos de estado
- 200 ok
- 201 created
- 400 validation error
- 401 missing key
- 403 invalid key
- 404 not found

