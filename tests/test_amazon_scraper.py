from orcatech.scrapers.amazon import _url_busca
from orcatech.scrapers import amazon
from orcatech.scrapers.errors import BloqueioLoja


def test_url_busca_codifica_termos_com_caracteres_especiais():
    assert _url_busca("câmera 4K & lente") == (
        "https://www.amazon.com.br/s?k=c%C3%A2mera+4K+%26+lente"
    )


def test_busca_amazon_tenta_fallback_se_selenium_for_bloqueado(monkeypatch):
    chamadas = []
    resultado = [{"site": "Amazon", "nome": "Produto", "preco": 100.0}]

    def selenium_bloqueado(_produto):
        raise BloqueioLoja("bloqueio temporário")

    def fallback(_produto):
        chamadas.append("fallback")
        return resultado

    monkeypatch.setattr(amazon, "_buscar_selenium", selenium_bloqueado)
    monkeypatch.setattr(amazon, "_buscar_uc", fallback)

    assert amazon.buscar_amazon("produto") == resultado
    assert chamadas == ["fallback"]
