# test_occ_phase2.py
import cloudscraper
from bs4 import BeautifulSoup

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)

# Toma cualquier URL de OCC de tu DB
url = "https://www.occ.com.mx/empleo/oferta/21111655/"  # pon una URL real

resp = scraper.get(url, timeout=30)
soup = BeautifulSoup(resp.text, "html.parser")

# Prueba cada selector
print("1:", soup.select_one("#Descripcion"))
print("2:", soup.find("div", {"itemprop": "description"}))
print("3:", soup.select_one("div.break-words"))

# Guarda el HTML para inspeccionarlo
with open("debug_occ.html", "w") as f:
    f.write(resp.text)
print("HTML guardado en debug_occ.html")