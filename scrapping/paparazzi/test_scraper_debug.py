"""
Script de diagnostico para ver estructura HTML de Paparazzi (version ligera).
"""
from parsel import Selector

from utils.http_client import HttpClient

TEST_URL = "https://www.paparazzi.com.ar/looks/maxi-lopez-se-cambio-la-cara-con-un-retoque-estetico-y-dejo-a-todos-en-shock-el-impactante-antes-y-despues/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
    "Referer": "https://www.paparazzi.com.ar/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

print("=" * 80)
print("DIAGNOSTICO DE ESTRUCTURA HTML - PAPARAZZI")
print("=" * 80)
print(f"\nURL de prueba: {TEST_URL}\n")

try:
    client = HttpClient(headers=HEADERS, timeout=10, retries=2)
    try:
        resp = client.get(TEST_URL)
        resp.raise_for_status()
    finally:
        client.close()

    sel = Selector(text=resp.text)
    title = sel.xpath("//h1/text() | //title/text()").get()
    print("\nTITULO:", (title or "N/A").strip()[:120])

    print("\nPRIMEROS PARRAFOS:")
    for idx, text in enumerate(sel.xpath("//article//p//text() | //p//text()").getall()[:5], 1):
        cleaned = " ".join(text.split()).strip()
        if cleaned:
            print(f"  {idx}. {cleaned[:120]}")

    print("\nIMAGENES DETECTADAS:")
    imgs = sel.xpath("//img/@src | //img/@data-src").getall()
    for img in imgs[:5]:
        print(f"  - {img}")

except Exception as exc:
    print(f"\n[ERROR] {exc}")

print("\n" + "=" * 80)
print("DIAGNOSTICO COMPLETADO")
print("=" * 80)
