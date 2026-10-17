"""
Testes da organização dos resultados em app.evaluation.avaliar_casos
(matrizes de confusão, situação final, relatório), com resultados
montados à mão — sem chamar o modelo de linguagem.
"""
from app.evaluation.avaliar_casos import (
    ResultadoAvaliacaoCaso,
    montar_matrizes,
    montar_relatorio_texto,
    salvar_matrizes,
)


def _resultado(caso_id, esperado, obtidos, situacao_esperada, situacao_fluxo, dias=10, dias_fluxo=10):
    r = ResultadoAvaliacaoCaso(
        caso_id=caso_id,
        rotulo_esperado=esperado,
        rotulos_obtidos=obtidos,
        dias_restantes_esperado=dias,
        dias_restantes_calculado_gabarito=dias,
        dias_restantes_fluxo=dias_fluxo,
        situacao_esperada=situacao_esperada,
        situacao_fluxo=situacao_fluxo,
    )
    r.diagnostico_correto = r.classificacao_correta and dias_fluxo == dias
    return r


RESULTADOS = [
    _resultado("c1", "aparente/duravel", ["aparente/duravel"] * 3, "dentro_do_prazo", "dentro_do_prazo"),
    # oculto classificado como aparente: o prazo conta da entrega, e o caso parece vencido
    _resultado("c2", "oculto/duravel", ["aparente/duravel", "oculto/duravel", "aparente/duravel"],
               "dentro_do_prazo", "fora_do_prazo", dias=80, dias_fluxo=0),
    _resultado("c3", "fora_de_escopo", ["fora_de_escopo"] * 3, "fora_de_escopo", "fora_de_escopo", dias=None),
]


def test_matrizes_usam_a_primeira_execucao_e_separam_tipo_e_durabilidade():
    matrizes = montar_matrizes(RESULTADOS)

    assert matrizes["tipo_vicio"].valor("oculto", "aparente") == 1
    assert matrizes["durabilidade"].valor("duravel", "duravel") == 2
    assert matrizes["classificacao_completa"].valor("oculto/duravel", "aparente/duravel") == 1
    # 3 execuções x 3 casos = 9 respostas; c2 acertou 1 de 3
    todas = matrizes["classificacao_completa_todas_execucoes"]
    assert todas.total == 9
    assert todas.valor("oculto/duravel", "oculto/duravel") == 1


def test_matriz_da_situacao_final_mostra_impacto_pratico_do_erro():
    matriz = montar_matrizes(RESULTADOS)["situacao_final"]
    assert matriz.valor("dentro_do_prazo", "fora_do_prazo") == 1


def test_relatorio_traz_matrizes_confusoes_e_metricas():
    texto = montar_relatorio_texto(RESULTADOS)

    assert "Matriz de confusão (linhas = gabarito, colunas = sistema)" in texto
    assert "oculto → aparente (1)" in texto
    assert "precisão" in texto and "revocação" in texto
    assert "Situação final do caso" in texto
    assert "c2 variou" in texto


def test_salvar_matrizes_gera_um_csv_por_matriz(tmp_path):
    salvar_matrizes(montar_matrizes(RESULTADOS), tmp_path)
    arquivos = {p.name for p in tmp_path.iterdir()}
    assert {"tipo_vicio.csv", "durabilidade.csv", "classificacao_completa.csv", "situacao_final.csv"} <= arquivos


def test_salvar_figuras_gera_a_matriz_do_tipo_de_vicio_em_png(tmp_path):
    from app.evaluation.avaliar_casos import salvar_figuras

    salvar_figuras(RESULTADOS, tmp_path)
    figuras = {p.name for p in tmp_path.glob("*.png")}
    assert {"01_matriz_tipo_vicio.png", "01_metricas_tipo_vicio.png", "05_matriz_situacao_final.png",
            "06_resumo.png", "07_resultado_por_caso.png"} <= figuras
