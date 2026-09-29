"""
Teste isolado do Gshield (não mexe no resto do app).
Uso:   python -m scripts.testar_gshield "mouse gamer"
"""
import sys
from orcatech.scrapers.gshield import buscar_gshield

termo = " ".join(sys.argv[1:]) or "mouse gamer"
res = buscar_gshield(termo)

print(f"\n=== {len(res)} produtos para '{termo}' ===")
for p in res:
    print(f"{p['preco_texto']:>12} | foto={'sim' if p['imagem'] else 'NAO'} | {p['nome'][:70]}")
