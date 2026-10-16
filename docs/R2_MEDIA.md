# R2 media storage

El publicador usa `MEDIA_STORAGE_PROVIDER=r2` para subir archivos locales a Cloudflare R2 antes de publicarlos en Meta.

## Variables

```env
MEDIA_STORAGE_PROVIDER=r2
R2_ACCOUNT_ID=<account-id>
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_BUCKET=<bucket-r2>
R2_ACCESS_KEY_ID=<access-key-id-real>
R2_SECRET_ACCESS_KEY=<secret-access-key-real>
R2_PUBLIC_BASE_URL=https://pub-e56776066c7440c097c7fdd752ac42ec.r2.dev
R2_CUSTOM_DOMAIN=https://media.duonoticiasok.com
R2_SITE_FOLDER=img
R2_TEMP_FOLDER=img_temp
R2_DELETE_AFTER_PUBLISH=0
```

`R2_ACCESS_KEY_ID` no es la URL `pub-...r2.dev`; esa URL corresponde a `R2_PUBLIC_BASE_URL`.

## Carpetas

- `img`: imagenes definitivas del sitio.
- `img_temp`: imagenes y videos editados que necesitan una URL publica para publicar en Meta.

## Dominio media.duonoticiasok.com

1. En Cloudflare, entra a R2 Object Storage y selecciona el bucket.
2. En `Settings > Custom Domains`, agrega `media.duonoticiasok.com`.
3. Revisa el registro DNS que Cloudflare propone y confirma `Connect Domain`.
4. Espera a que el estado pase a `Active`.
5. Cambia `R2_PUBLIC_BASE_URL` a `https://media.duonoticiasok.com`.

La URL `r2.dev` sirve para pruebas, pero Cloudflare la recomienda para uso no productivo. Para produccion conviene usar el dominio personalizado.

## Credenciales

En R2, usa `Account Details > Manage API Tokens` y crea una credencial con permiso `Object Read & Write` limitada al bucket. Copia el `Access Key ID` y el `Secret Access Key`; el secret no se puede recuperar despues.

Referencias:

- https://developers.cloudflare.com/r2/buckets/public-buckets/
- https://developers.cloudflare.com/r2/api/tokens/
