import type { CategoryId } from "../../src/brand/categories";
import type { PieceInput } from "../../src/schema/piece";

/**
 * Adaptador WordPress (REST API publica /wp-json/wp/v2). Flujo:
 * WordPress -> lectura -> normalizacion -> pieza en borrador -> revision en el
 * panel -> render. Nunca reescribe titulares ni inventa datos: el titular
 * audiovisual arranca igual al original y lo ajusta el editor.
 *
 * Configuracion (.env.local del panel):
 *   WORDPRESS_BASE_URL=https://medio.com     (sin credenciales: solo posts publicos)
 *   WORDPRESS_SOURCE_NAME=Nombre del medio
 * Sin WORDPRESS_BASE_URL devuelve notas de demostracion marcadas como tales.
 */

type WpPost = {
  id: number;
  date_gmt?: string;
  date?: string;
  link?: string;
  title?: { rendered?: string };
  excerpt?: { rendered?: string };
  _embedded?: {
    "wp:featuredmedia"?: Array<{ source_url?: string; media_details?: { width?: number; height?: number }; caption?: { rendered?: string } }>;
    "wp:term"?: Array<Array<{ name?: string; taxonomy?: string }>>;
  };
};

const decode = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#8220;|&#8221;|&quot;/g, '"')
    .replace(/&#8216;|&#8217;/g, "'")
    .replace(/&#8211;/g, "–")
    .replace(/&#8212;/g, "—")
    .replace(/&#8230;/g, "…")
    .replace(/&amp;/g, "&")
    .replace(/&nbsp;/g, " ")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/\s+/g, " ")
    .trim();

const CATEGORY_KEYWORDS: Array<[CategoryId, RegExp]> = [
  ["policiales", /polic|seguridad|crimen|delito/i],
  ["justicia", /justicia|judicial|tribunal/i],
  ["politica", /pol[ií]tica|gobierno|elecci/i],
  ["economia", /econom|finanz|negocio/i],
  ["deportes", /deport|f[uú]tbol/i],
  ["espectaculos", /espect[aá]culo|show|far[aá]ndula|famos/i],
  ["cultura", /cultura|arte|m[uú]sica/i],
  ["salud", /salud|hospital/i],
  ["educacion", /educaci|escuela|universidad/i],
  ["turismo", /turismo/i],
  ["clima", /clima|tiempo|meteorol/i],
  ["tecnologia", /tecnolog/i],
  ["sociedad", /sociedad|ciudad|comunidad/i],
];

const mapCategory = (names: string[]): CategoryId => {
  for (const [id, re] of CATEGORY_KEYWORDS) if (names.some((n) => re.test(n))) return id;
  return "actualidad";
};

export const normalizeWpPost = (post: WpPost, sourceName: string): PieceInput => {
  const title = decode(post.title?.rendered ?? "") || `Nota ${post.id}`;
  const media = post._embedded?.["wp:featuredmedia"]?.[0];
  const terms = (post._embedded?.["wp:term"] ?? []).flat().filter((t) => t.taxonomy === "category").map((t) => t.name ?? "");
  const date = post.date_gmt ? `${post.date_gmt}Z` : (post.date ?? new Date().toISOString());
  return {
    content: {
      id: `wp-${post.id}`,
      originalTitle: title,
      headline: title,
      deck: decode(post.excerpt?.rendered ?? "").slice(0, 220),
      category: mapCategory(terms),
      date,
      source: { name: sourceName, url: post.link },
      photos: media?.source_url
        ? [{ src: media.source_url, width: media.media_details?.width, height: media.media_details?.height, credit: decode(media.caption?.rendered ?? "") || undefined }]
        : [],
      editorialStatus: "draft",
    },
    presentation: { template: media?.source_url ? "editorial" : "static", format: "reel", durationSeconds: 15 },
  };
};

export const fetchWordPressPosts = async (limit = 10): Promise<{ demo: boolean; pieces: PieceInput[] }> => {
  const base = process.env.WORDPRESS_BASE_URL?.replace(/\/$/, "");
  const sourceName = process.env.WORDPRESS_SOURCE_NAME || "WordPress";
  if (!base) {
    return {
      demo: true,
      pieces: [
        {
          content: {
            id: "wp-demo-1",
            originalTitle: "Nota de demostración desde el adaptador WordPress",
            headline: "Nota de demostración desde el adaptador WordPress",
            deck: "Configurá WORDPRESS_BASE_URL para leer notas reales.",
            category: "actualidad",
            date: new Date().toISOString(),
            source: { name: "Demo" },
            photos: [{ src: "demo/ciudad.jpg", width: 2000, height: 1500 }],
            editorialStatus: "draft",
            isDemo: true,
          },
          presentation: { template: "editorial", format: "reel", durationSeconds: 15 },
        },
      ],
    };
  }
  const url = `${base}/wp-json/wp/v2/posts?_embed=1&per_page=${Math.min(50, Math.max(1, limit))}`;
  const res = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
  if (!res.ok) throw new Error(`WordPress respondio ${res.status}`);
  const posts = (await res.json()) as WpPost[];
  return { demo: false, pieces: posts.map((p) => normalizeWpPost(p, sourceName)) };
};
