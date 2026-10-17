from app.evaluation.metricas import (
    acuracia,
    acuracia_por_campo,
    precisao_revocacao_f1,
    proporcao_diagnostico_correto,
)


def test_acuracia_por_campo():
    resultados = [
        {"cnpj": ("12.345.678/0001-99", "12.345.678/0001-99"), "valor_total": (249.80, 249.80)},
        {"cnpj": ("00.000.000/0000-00", "11.111.111/0001-11"), "valor_total": (None, 59.90)},
    ]
    acc = acuracia_por_campo(resultados)
    assert acc["cnpj"] == 0.5
    assert acc["valor_total"] == 0.5


def test_campo_correto_ignora_maiusculas_e_espacos():
    resultados = [{"nome": ("  Loja Exemplo  ", "loja exemplo")}]
    acc = acuracia_por_campo(resultados)
    assert acc["nome"] == 1.0






def test_precisao_revocacao_f1_caso_perfeito():
    previstos = ["aparente", "oculto", "aparente"]
    esperados = ["aparente", "oculto", "aparente"]
    metricas = precisao_revocacao_f1(previstos, esperados)

    assert metricas["aparente"].precisao == 1.0
    assert metricas["aparente"].revocacao == 1.0
    assert metricas["aparente"].f1 == 1.0
    assert metricas["aparente"].suporte == 2

    assert metricas["oculto"].f1 == 1.0
    assert metricas["oculto"].suporte == 1


def test_precisao_revocacao_f1_com_erros():
    # gabarito:  aparente, aparente, oculto
    # previsto:  aparente, oculto,   oculto
    previstos = ["aparente", "oculto", "oculto"]
    esperados = ["aparente", "aparente", "oculto"]
    metricas = precisao_revocacao_f1(previstos, esperados)

    # "aparente": 1 verdadeiro positivo, 0 falso positivo, 1 falso negativo
    assert metricas["aparente"].precisao == 1.0
    assert metricas["aparente"].revocacao == 0.5

    # "oculto": 1 verdadeiro positivo, 1 falso positivo, 0 falso negativo
    assert metricas["oculto"].precisao == 0.5
    assert metricas["oculto"].revocacao == 1.0


def test_acuracia():
    assert acuracia(["a", "b", "c"], ["a", "b", "x"]) == 2 / 3
    assert acuracia([], []) == 0.0


def test_proporcao_diagnostico_correto():
    assert proporcao_diagnostico_correto([True, True, False, True]) == 0.75
    assert proporcao_diagnostico_correto([]) == 0.0


def test_campo_correto_ignora_acentos_e_pontuacao():
    from app.evaluation.metricas import campo_correto

    assert campo_correto("Farmácia Bem-Estar Ltda.", "FARMACIA BEM ESTAR LTDA")
    assert not campo_correto("FARMACIA BOM ESTAR", "FARMACIA BEM ESTAR LTDA")


def test_campo_correto_produtos_mesmos_itens_em_qualquer_ordem():
    from app.evaluation.metricas import campo_correto

    assert campo_correto(["protetor solar fps50", "Dipirona 500mg"], ["DIPIRONA 500MG", "PROTETOR SOLAR FPS50"])
    assert not campo_correto(["DIPIRONA 500MG"], ["DIPIRONA 500MG", "PROTETOR SOLAR FPS50"])
    assert not campo_correto(["DIPIRONA 5OOMG"], ["DIPIRONA 500MG"])


def test_campo_correto_valor_ate_o_centavo_e_none():
    from app.evaluation.metricas import campo_correto

    assert campo_correto(45.9, 45.90)
    assert not campo_correto(45.91, 45.90)
    assert not campo_correto(None, 45.90)


def test_consistencia_das_execucoes_repetidas():
    from app.evaluation.metricas import consistencia

    assert consistencia([["a", "a", "a"], ["a", "b", "a"]]) == 0.5
    assert consistencia([]) == 0.0


def test_matriz_de_confusao_conta_acertos_na_diagonal_e_confusoes_fora_dela():
    from app.evaluation.metricas import matriz_confusao

    esperados = ["aparente", "aparente", "oculto", "oculto", "oculto"]
    previstos = ["aparente", "oculto", "oculto", "aparente", "aparente"]
    matriz = matriz_confusao(previstos, esperados, ["aparente", "oculto", "fora_de_escopo"])

    assert matriz.valor("aparente", "aparente") == 1
    assert matriz.valor("oculto", "aparente") == 2      # oculto classificado como aparente
    assert matriz.valor("fora_de_escopo", "fora_de_escopo") == 0  # classe sem casos aparece zerada
    assert matriz.acertos == 2 and matriz.total == 5
    assert matriz.confusoes()[0] == ("oculto", "aparente", 2)


def test_matriz_de_confusao_acrescenta_classes_inesperadas_ao_final():
    from app.evaluation.metricas import matriz_confusao

    matriz = matriz_confusao(["resposta_invalida"], ["aparente"], ["aparente", "oculto"])
    assert matriz.classes == ["aparente", "oculto", "resposta_invalida"]
    assert matriz.valor("aparente", "resposta_invalida") == 1


def test_matriz_de_confusao_em_texto_e_csv():
    from app.evaluation.metricas import matriz_confusao

    matriz = matriz_confusao(["a", "b"], ["a", "a"], ["a", "b"])
    assert "total" in matriz.formatar_texto()
    assert matriz.para_csv().splitlines() == ["esperado \\ previsto;a;b", "a;1;1", "b;0;0"]


def test_resultado_do_campo():
    from app.evaluation.metricas import resultado_do_campo

    assert resultado_do_campo(45.9, 45.90) == "correto"
    assert resultado_do_campo(45.1, 45.90) == "incorreto"
    assert resultado_do_campo(None, 45.90) == "nao_extraido"
    assert resultado_do_campo([], ["CAFE"]) == "nao_extraido"
    assert resultado_do_campo(["LEITE"], ["CAFE"]) == "incorreto"


def test_alternativas_aceitas_no_gabarito_do_estabelecimento():
    from app.evaluation.metricas import AlternativasAceitas, campo_correto

    aceitos = AlternativasAceitas(["Lojas Riachuelo SA", "RIACHUELO"])
    assert campo_correto("RIACHUELO", aceitos)
    assert campo_correto("lojas riachuelo sa", aceitos)
    assert not campo_correto("C&A MODAS S.A.", aceitos)
