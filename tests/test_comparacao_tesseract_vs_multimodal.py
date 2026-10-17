"""
Comparação REAL entre as duas abordagens de extração da Metodologia —
Tesseract e modelo multimodal (Claude) — sobre as fotos reais de
tests/casos/casos.json.

Diferente de test_comparar_extracao.py (que testa a lógica com
extratores falsos), este teste roda o Tesseract instalado e chama a API
do modelo de linguagem de verdade. Ele só confere que os extratores rodam sem erro em
todas as fotos: recusas e acertos são RESULTADOS do experimento (ficam
no relatório), e não falhas de teste.
- é pulado se o Tesseract não estiver instalado;
- a parte multimodal é pulada se a chave de API não estiver configurada.

Rodar só esta comparação, mostrando o relatório no terminal:

    python3 -m pytest tests/test_comparacao_tesseract_vs_multimodal.py -s

Para comparar mais de um modelo multimodal (ex.: Flash e Pro):

    MODELOS_COMPARACAO=claude-sonnet-5-5,claude-opus-5-5 \\
        python3 -m pytest tests/test_comparacao_tesseract_vs_multimodal.py -s

Os resultados são salvos em resultados/<data>_extracao/.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from app.config import MODELO_LLM, modelo_configurado
from app.evaluation.casos import carregar_casos
from app.evaluation.comparar_extracao import (
    comparar_extratores,
    montar_extratores,
    montar_relatorio_texto,
    salvar_relatorio,
)

ARQUIVO_CASOS = Path(__file__).parent / "casos" / "casos.json"
PASTA_RESULTADOS = Path(__file__).parent.parent / "resultados"

pytestmark = [
    pytest.mark.integracao,
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract não instalado"),
]


def _modelos_multimodais() -> list[str]:
    if not modelo_configurado():
        return []
    nomes = os.getenv("MODELOS_COMPARACAO", MODELO_LLM)
    return [m.strip() for m in nomes.split(",") if m.strip()]


@pytest.fixture(scope="module")
def relatorios():
    casos = carregar_casos(ARQUIVO_CASOS)
    extratores = montar_extratores(_modelos_multimodais())
    relatorios = comparar_extratores(casos, extratores)

    print(montar_relatorio_texto(relatorios))
    caminho_txt, _ = salvar_relatorio(
        relatorios,
        PASTA_RESULTADOS,
        metadados={"arquivo_de_casos": str(ARQUIVO_CASOS), "extratores": list(extratores)},
    )
    print(f"\nRelatório salvo em {caminho_txt}")
    return relatorios


def test_tesseract_roda_em_todas_as_imagens(relatorios):
    tesseract = relatorios["tesseract"]
    assert tesseract.casos_com_erro == [], [r.erro for r in tesseract.resultados_por_caso if r.erro]
    assert set(tesseract.acuracia_por_campo) == {"estabelecimento", "data_emissao", "produtos", "valor_total"}


@pytest.mark.skipif(not modelo_configurado(), reason="chave de API do modelo não configurada")
def test_multimodal_roda_em_todas_as_imagens(relatorios):
    multimodais = [r for nome, r in relatorios.items() if nome.startswith("multimodal:")]
    assert multimodais
    for relatorio in multimodais:
        assert relatorio.casos_com_erro == [], [r.erro for r in relatorio.resultados_por_caso if r.erro]
        assert relatorio.acuracia_media is not None
