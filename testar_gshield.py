"""
Teste isolado do Gshield (não mexe no resto do app).
Uso:   python testar_gshield.py "mouse gamer"
"""
import sys
from scraping_gshield import buscar_gshield

termo = " ".join(sys.argv[1:]) or "mouse gamer"
res = buscar_gshield(termo)

print(f"\n=== {len(res)} produtos para '{termo}' ===")
for p in res:
    print(f"{p['preco_texto']:>12} | foto={'sim' if p['imagem'] else 'NAO'} | {p['nome'][:70]}")
