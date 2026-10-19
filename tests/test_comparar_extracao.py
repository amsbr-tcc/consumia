"""
Testes de avaliacao.comparar_extracao.

Usam extratores falsos (funções Python simples, sem OCR nem chamada de
API) para testar a lógica de comparação em si: acurácia por campo,
recusa de fotos ruins, tratamento de exceções e o texto do
relatório. A comparação real (Tesseract x Claude) está em
test_comparacao_tesseract_vs_multimodal.py.
"""
from datetime import date
from pathlib import Path

from avaliacao.casos import CasoDeTeste
from avaliacao.comparar_extracao import (
    comparar_extratores,
    executar_extrator_sobre_casos,
    melhor_extrator,
    montar_relatorio_texto,
    salvar_relatorio,
)
from app.extracao.qualidade_imagem import ImagemIlegivelError, MotivoImagemRuim
from app.models import FonteExtracao, NotaFiscalExtraida


def _caso(id_, estabelecimento, data, produtos, valor):
    return CasoDeTeste(
        id=id_,
        imagem=Path(f"/imagens/{id_}.jpg"),  # caminho fictício, não é lido de fato
        gabarito={
            "estabelecimento": estabelecimento,
            "data_emissao": data,
            "produtos": produtos,
            "valor_total": valor,
        },
    )


CASOS = [
    _caso("caso_01", "FARMACIA BEM ESTAR LTDA", date(2026, 1, 20), ["DIPIRONA 500MG"], 45.90),
    _caso("caso_02", "SUPERMERCADO BOA COMPRA", date(2026, 2, 5), ["CAFE", "LEITE"], 120.00),
]
CASO_BORRADO = CasoDeTeste(id="caso_borrado", imagem=Path("/imagens/caso_borrado.jpg"), foto_ilegivel=True)


def extrator_perfeito(caminho_imagem: Path) -> NotaFiscalExtraida:
    """Simula um extrator que sempre acerta tudo e recusa a foto borrada."""
    if caminho_imagem.stem == "caso_borrado":
        raise ImagemIlegivelError(MotivoImagemRuim.BORRADA)
    gabarito = {c.id: c.gabarito for c in CASOS}[caminho_imagem.stem]
    return NotaFiscalExtraida(
        **gabarito, fonte=FonteExtracao.OCR_TESSERACT, texto_reconhecido="FARMACIA  BEM\nESTAR LTDA"
    )


def extrator_ruim(caminho_imagem: Path) -> NotaFiscalExtraida:
    """Simula um extrator que sempre erra tudo e aceita qualquer foto."""
    return NotaFiscalExtraida(
        estabelecimento="LOJA ERRADA",
        data_emissao=date(1900, 1, 1),
        produtos=["OUTRO"],
        valor_total=0.0,
        fonte=FonteExtracao.OCR_MULTIMODAL,
    )


def extrator_que_recusa_tudo(caminho_imagem: Path) -> NotaFiscalExtraida:
    raise ImagemIlegivelError(MotivoImagemRuim.ILEGIVEL)


def extrator_que_falha(caminho_imagem: Path) -> NotaFiscalExtraida:
    raise RuntimeError("falha simulada de extração")


def test_extrator_perfeito_tem_acuracia_100_por_cento_em_todos_os_campos():
    relatorio = executar_extrator_sobre_casos("perfeito", extrator_perfeito, CASOS)

    assert relatorio.acuracia_por_campo == {
        "estabelecimento": 1.0,
        "data_emissao": 1.0,
        "produtos": 1.0,
        "valor_total": 1.0,
    }
    assert relatorio.acuracia_media == 1.0
    assert relatorio.casos_com_erro == []


def test_extrator_ruim_tem_acuracia_0_por_cento():
    relatorio = executar_extrator_sobre_casos("ruim", extrator_ruim, CASOS)

    assert all(valor == 0.0 for valor in relatorio.acuracia_por_campo.values())




def test_foto_ruim_nao_entra_na_acuracia_e_conta_como_recusada():
    relatorio = executar_extrator_sobre_casos("perfeito", extrator_perfeito, CASOS + [CASO_BORRADO])

    assert relatorio.acuracia_media == 1.0
    assert relatorio.fotos_ruins_recusadas == 1
    assert relatorio.fotos_ruins_total == 1


def test_extrator_que_aceita_foto_ruim_nao_conta_como_recusa():
    relatorio = executar_extrator_sobre_casos("ruim", extrator_ruim, [CASO_BORRADO])

    assert relatorio.fotos_ruins_recusadas == 0


def test_recusa_de_foto_boa_conta_como_erro_em_todos_os_campos():
    relatorio = executar_extrator_sobre_casos("recusa", extrator_que_recusa_tudo, CASOS)

    assert relatorio.recusas_indevidas == ["caso_01", "caso_02"]
    assert relatorio.acuracia_media == 0.0
    assert relatorio.casos_com_erro == []


def test_extrator_que_falha_conta_como_erro_em_todos_os_campos():
    relatorio = executar_extrator_sobre_casos("falho", extrator_que_falha, CASOS)

    assert relatorio.casos_com_erro == ["caso_01", "caso_02"]
    assert relatorio.acuracia_por_campo["valor_total"] == 0.0
    assert all("RuntimeError" in r.erro for r in relatorio.resultados_por_caso)


def test_comparar_extratores_e_melhor_extrator():
    relatorios = comparar_extratores(CASOS, {"perfeito": extrator_perfeito, "ruim": extrator_ruim})

    assert set(relatorios) == {"perfeito", "ruim"}
    assert melhor_extrator(relatorios) == "perfeito"


def test_montar_relatorio_texto_tem_tabela_lado_a_lado_e_erros_por_caso():
    relatorios = comparar_extratores(CASOS, {"perfeito": extrator_perfeito, "ruim": extrator_ruim})
    texto = montar_relatorio_texto(relatorios)

    assert "Comparação lado a lado" in texto
    assert "estabelecimento" in texto and "produtos" in texto
    assert "100%" in texto and "0%" in texto
    assert "caso_01 valor_total: 0.0 ≠ 45.9" in texto
    assert "Maior acurácia média: perfeito" in texto


def test_salvar_relatorio_grava_texto_e_json(tmp_path):
    relatorios = comparar_extratores(CASOS, {"perfeito": extrator_perfeito})
    caminho_txt, caminho_json = salvar_relatorio(relatorios, tmp_path, {"teste": True})

    assert "perfeito" in caminho_txt.read_text(encoding="utf-8")
    assert '"data_emissao"' in caminho_json.read_text(encoding="utf-8")


def test_matriz_da_checagem_da_foto():
    relatorio = executar_extrator_sobre_casos("ruim", extrator_ruim, CASOS + [CASO_BORRADO])
    matriz = relatorio.matriz_qualidade_foto

    assert matriz.valor("legivel", "aceitou") == 2
    assert matriz.valor("ilegivel", "aceitou") == 1   # foto ruim que passou: dado não confiável
    assert matriz.valor("ilegivel", "recusou") == 0
    assert "Checagem da foto" in montar_relatorio_texto({"ruim": relatorio})


def extrator_meio_a_meio(caminho_imagem: Path) -> NotaFiscalExtraida:
    """Acerta tudo no caso_01; no caso_02 erra o valor e não acha a data."""
    gabarito = dict({c.id: c.gabarito for c in CASOS}[caminho_imagem.stem])
    if caminho_imagem.stem == "caso_02":
        gabarito["valor_total"] = 99.0
        gabarito["data_emissao"] = None
    return NotaFiscalExtraida(**gabarito)


def test_matriz_de_resultados_separa_incorreto_de_nao_extraido():
    matriz = executar_extrator_sobre_casos("meio", extrator_meio_a_meio, CASOS).matriz_resultados

    assert matriz["valor_total"].contagens == {"correto": 1, "incorreto": 1, "nao_extraido": 0, "foto_recusada": 0}
    assert matriz["data_emissao"].contagens["nao_extraido"] == 1
    # não extrair não derruba a precisão (só a revocação); devolver valor errado derruba as duas
    assert matriz["data_emissao"].precisao == 1.0 and matriz["data_emissao"].revocacao == 0.5
    assert matriz["valor_total"].precisao == 0.5
    assert matriz["TOTAL"].total == 8


def test_matriz_de_resultados_conta_foto_recusada():
    matriz = executar_extrator_sobre_casos("recusa", extrator_que_recusa_tudo, CASOS).matriz_resultados
    assert matriz["TOTAL"].contagens["foto_recusada"] == 8


def test_matriz_de_concordancia_mostra_onde_so_uma_abordagem_acerta():
    from avaliacao.comparar_extracao import matriz_concordancia

    relatorios = comparar_extratores(CASOS, {"tesseract": extrator_perfeito, "multimodal": extrator_meio_a_meio})
    valor = matriz_concordancia(relatorios["tesseract"], relatorios["multimodal"], "valor_total")
    assert valor.valor("acertou", "acertou") == 1
    assert valor.valor("acertou", "errou") == 1       # só o Tesseract acertou

    todos = matriz_concordancia(relatorios["tesseract"], relatorios["multimodal"])
    assert todos.total == 8 and todos.valor("acertou", "errou") == 2

    texto = montar_relatorio_texto(relatorios)
    assert "Concordância: tesseract x multimodal" in texto
    assert "Matriz de resultados" in texto


def test_salvar_relatorio_grava_matrizes_em_csv(tmp_path):
    relatorios = comparar_extratores(CASOS, {"tesseract": extrator_perfeito, "multimodal:x": extrator_meio_a_meio})
    salvar_relatorio(relatorios, tmp_path, {})
    pasta = next((tmp_path / "extracao").glob("*")) / "tabelas_csv"
    nomes = {p.name for p in pasta.iterdir()}
    assert {"resultados_tesseract.csv", "resultados_multimodal_x.csv",
            "concordancia_tesseract_x_multimodal_x.csv"} <= nomes


def test_salvar_relatorio_gera_figuras_png(tmp_path):
    relatorios = comparar_extratores(CASOS + [CASO_BORRADO], {"tesseract": extrator_perfeito, "multimodal:x": extrator_meio_a_meio})
    salvar_relatorio(relatorios, tmp_path, {})
    figuras = {p.name for p in (next((tmp_path / "extracao").glob("*")) / "figuras").glob("*.png")}
    assert {"01_comparacao_acuracia.png", "02_resultados_tesseract.png", "03_checagem_foto_tesseract.png",
            "04_concordancia_tesseract_x_multimodal_x.png"} <= figuras


def test_consistencia_entre_leituras_repetidas(tmp_path):
    from itertools import count

    contador = count()

    def extrator_instavel(caminho_imagem):
        # caso_01: sempre igual; caso_02: o valor muda a cada leitura.
        nota = extrator_perfeito(caminho_imagem)
        if caminho_imagem.stem == "caso_02":
            nota.valor_total = 100.0 + next(contador)
        return nota

    relatorio = executar_extrator_sobre_casos("x", extrator_instavel, CASOS, execucoes=3)

    assert relatorio.execucoes == 3
    assert relatorio.consistencia_por_campo["estabelecimento"] == 1.0
    assert relatorio.consistencia_por_campo["valor_total"] == 0.5
    assert relatorio.consistencia_por_campo["TODOS"] == 0.5
    assert relatorio.consistencia_recusa == 1.0
    # A acurácia continua sendo a da 1ª leitura.
    assert relatorio.acuracia_por_campo["estabelecimento"] == 1.0


def test_uma_execucao_nao_calcula_consistencia():
    relatorio = executar_extrator_sobre_casos("x", extrator_perfeito, CASOS)
    assert relatorio.consistencia_por_campo is None
