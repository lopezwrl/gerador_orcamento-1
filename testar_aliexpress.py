"""
Teste isolado da AliExpress (não mexe no resto do app).
Uso:   python testar_aliexpress.py "mouse gamer"
"""
import sys
from scraping_aliexpress import buscar_aliexpress

termo = " ".join(sys.argv[1:]) or "mouse gamer"
res = buscar_aliexpress(termo)

print(f"\n=== {len(res)} produtos para '{termo}' ===")
for p in res:
    print(f"{p['preco_texto']:>12} | foto={'sim' if p['imagem'] else 'NAO'} | {p['nome'][:70]}")
    print(f"             {p['link'][:100]}")
