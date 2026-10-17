"""
Testes do módulo app.prazo.calculator.

Cobrem os quatro casos base (vício aparente/oculto x durável/não durável),
os limites exatos do prazo (último dia dentro, primeiro dia fora), as
situações que alteram o prazo (garantia contratual e reclamação já feita
ao fornecedor) e os erros esperados quando faltam dados ou os dados são
inconsistentes.
"""
from datetime import date

import pytest

from app.models import Durabilidade, SituacaoPrazo, TipoVicio
from app.prazo.calculator import (
    DadosInsuficientesError,
    calcular_prazo,
    determinar_data_inicio_contagem,
)


# ---------------------------------------------------------------------------
# determinar_data_inicio_contagem
# ---------------------------------------------------------------------------

def test_data_inicio_vicio_aparente_usa_data_entrega():
    inicio = determinar_data_inicio_contagem(
        TipoVicio.APARENTE,
        data_entrega=date(2026, 1, 10),
        data_evidencia_defeito=None,
    )
    assert inicio == date(2026, 1, 10)


def test_data_inicio_vicio_oculto_usa_data_evidencia():
    inicio = determinar_data_inicio_contagem(
        TipoVicio.OCULTO,
        data_entrega=date(2026, 1, 10),
        data_evidencia_defeito=date(2026, 3, 1),
    )
    assert inicio == date(2026, 3, 1)


def test_data_inicio_vicio_aparente_sem_data_entrega_levanta_erro():
    with pytest.raises(DadosInsuficientesError):
        determinar_data_inicio_contagem(
            TipoVicio.APARENTE, data_entrega=None, data_evidencia_defeito=None
        )


def test_data_inicio_vicio_oculto_sem_data_evidencia_levanta_erro():
    with pytest.raises(DadosInsuficientesError):
        determinar_data_inicio_contagem(
            TipoVicio.OCULTO, data_entrega=date(2026, 1, 10), data_evidencia_defeito=None
        )


# ---------------------------------------------------------------------------
# calcular_prazo — os quatro casos base
# ---------------------------------------------------------------------------

def test_produto_nao_duravel_vicio_aparente_dentro_do_prazo():
    # Entrega em 01/01, hoje é 10/01 -> 9 dias decorridos, prazo de 30 dias.
    resultado = calcular_prazo(
        tipo_vicio=TipoVicio.APARENTE,
        durabilidade=Durabilidade.NAO_DURAVEL,
        data_entrega=date(2026, 1, 1),
        data_referencia=date(2026, 1, 10),
    )
    assert resultado.prazo_total_dias == 30
    assert resultado.data_inicio_contagem == date(2026, 1, 1)
    assert resultado.data_vencimento == date(2026, 1, 31)
    assert resultado.dias_decorridos == 9
    assert resultado.dias_restantes == 21
    assert resultado.dentro_do_prazo is True


def test_produto_duravel_vicio_aparente_dentro_do_prazo():
    resultado = calcular_prazo(
        tipo_vicio=TipoVicio.APARENTE,
        durabilidade=Durabilidade.DURAVEL,
        data_entrega=date(2026, 1, 1),
        data_referencia=date(2026, 2, 1),
    )
    assert resultado.prazo_total_dias == 90
    assert resultado.data_vencimento == date(2026, 4, 1)
    assert resultado.dentro_do_prazo is True


def test_produto_nao_duravel_vicio_oculto_usa_data_evidencia():
    # A compra foi há muito tempo, mas o defeito só apareceu recentemente:
    # a contagem começa na data em que o defeito ficou evidente, não na compra.
    resultado = calcular_prazo(
        tipo_vicio=TipoVicio.OCULTO,
        durabilidade=Durabilidade.NAO_DURAVEL,
        data_entrega=date(2025, 1, 1),
        data_evidencia_defeito=date(2026, 1, 1),
        data_referencia=date(2026, 1, 15),
    )
    assert resultado.data_inicio_contagem == date(2026, 1, 1)
    assert resultado.data_vencimento == date(2026, 1, 31)
    assert resultado.dentro_do_prazo is True


def test_produto_duravel_vicio_oculto_fora_do_prazo():
    resultado = calcular_prazo(
        tipo_vicio=TipoVicio.OCULTO,
        durabilidade=Durabilidade.DURAVEL,
        data_evidencia_defeito=date(2025, 1, 1),
        data_referencia=date(2026, 1, 1),  # 365 dias depois, prazo é de 90
    )
    assert resultado.dentro_do_prazo is False
    assert resultado.dias_restantes == 0


# ---------------------------------------------------------------------------
# Limites exatos do prazo (art. 132 do Código Civil: exclui o dia do
# começo, inclui o dia do vencimento)
# ---------------------------------------------------------------------------

def test_ultimo_dia_do_prazo_ainda_esta_dentro():
    # Entrega em 01/01, produto não durável (30 dias) -> vencimento em 31/01.
    # No próprio dia do vencimento, o caso ainda está dentro do prazo.
    resultado = calcular_prazo(
        tipo_vicio=TipoVicio.APARENTE,
        durabilidade=Durabilidade.NAO_DURAVEL,
        data_entrega=date(2026, 1, 1),
        data_referencia=date(2026, 1, 31),
    )
    assert resultado.data_vencimento == date(2026, 1, 31)
    assert resultado.dentro_do_prazo is True
    assert resultado.dias_restantes == 0


def test_dia_seguinte_ao_vencimento_esta_fora():
    resultado = calcular_prazo(
        tipo_vicio=TipoVicio.APARENTE,
        durabilidade=Durabilidade.NAO_DURAVEL,
        data_entrega=date(2026, 1, 1),
        data_referencia=date(2026, 2, 1),  # um dia após 31/01
    )
    assert resultado.dentro_do_prazo is False


def test_no_dia_da_entrega_o_prazo_esta_intacto():
    # Dia 0: exclui-se o dia do começo, então no próprio dia da entrega
    # nenhum dia ainda foi consumido do prazo.
    resultado = calcular_prazo(
        tipo_vicio=TipoVicio.APARENTE,
        durabilidade=Durabilidade.DURAVEL,
        data_entrega=date(2026, 5, 10),
        data_referencia=date(2026, 5, 10),
    )
    assert resultado.dias_decorridos == 0
    assert resultado.dias_restantes == 90
    assert resultado.dentro_do_prazo is True


# ---------------------------------------------------------------------------
# Casos de erro
# ---------------------------------------------------------------------------

def test_durabilidade_invalida_levanta_erro():
    with pytest.raises(ValueError):
        calcular_prazo(
            tipo_vicio=TipoVicio.APARENTE,
            durabilidade="produto_qualquer",  # type: ignore[arg-type]
            data_entrega=date(2026, 1, 1),
        )


def test_data_inicio_no_futuro_levanta_erro():
    with pytest.raises(DadosInsuficientesError):
        calcular_prazo(
            tipo_vicio=TipoVicio.APARENTE,
            durabilidade=Durabilidade.NAO_DURAVEL,
            data_entrega=date(2026, 6, 1),
            data_referencia=date(2026, 1, 1),  # antes da entrega
        )


# ---------------------------------------------------------------------------
# Garantia contratual (art. 50): o prazo legal só corre depois dela
# ---------------------------------------------------------------------------

def _oculto_duravel(**kwargs):
    return calcular_prazo(
        tipo_vicio=TipoVicio.OCULTO,
        durabilidade=Durabilidade.DURAVEL,
        data_evidencia_defeito=date(2026, 3, 1),
        **kwargs,
    )


def test_garantia_contratual_adia_o_inicio_da_contagem():
    # Sem a garantia, o prazo venceria em 30/05; com garantia até 01/06,
    # os 90 dias contam a partir de 01/06 e vencem em 30/08.
    sem_garantia = _oculto_duravel(data_referencia=date(2026, 7, 1))
    assert sem_garantia.situacao == SituacaoPrazo.FORA_DO_PRAZO

    resultado = _oculto_duravel(
        data_referencia=date(2026, 7, 1), data_fim_garantia_contratual=date(2026, 6, 1)
    )
    assert resultado.data_inicio_contagem == date(2026, 6, 1)
    assert resultado.data_vencimento == date(2026, 8, 30)
    assert resultado.dias_decorridos == 30
    assert resultado.dias_restantes == 60
    assert resultado.situacao == SituacaoPrazo.DENTRO_DO_PRAZO
    assert resultado.garantia_contratual_considerada is True


def test_garantia_contratual_ainda_vigente_nao_consome_o_prazo_legal():
    resultado = _oculto_duravel(
        data_referencia=date(2026, 4, 1), data_fim_garantia_contratual=date(2026, 6, 1)
    )
    assert resultado.dias_decorridos == 0
    assert resultado.data_vencimento == date(2026, 8, 30)
    assert resultado.dentro_do_prazo is True


def test_garantia_contratual_que_terminou_antes_do_defeito_nao_muda_nada():
    resultado = _oculto_duravel(
        data_referencia=date(2026, 4, 1), data_fim_garantia_contratual=date(2026, 2, 1)
    )
    assert resultado.data_inicio_contagem == date(2026, 3, 1)
    assert resultado.garantia_contratual_considerada is False


# ---------------------------------------------------------------------------
# Reclamação ao fornecedor (art. 26, §2º, I): suspensão, com situação
# indeterminada quando a leitura como interrupção mudaria a conclusão
# ---------------------------------------------------------------------------

def _aparente_nao_duravel(**kwargs):
    # Entrega em 01/01, 30 dias: sem reclamação, vence em 31/01.
    return calcular_prazo(
        tipo_vicio=TipoVicio.APARENTE,
        durabilidade=Durabilidade.NAO_DURAVEL,
        data_entrega=date(2026, 1, 1),
        **kwargs,
    )


def test_reclamacao_com_resposta_suspende_o_prazo():
    # Reclamação em 11/01 e resposta negativa em 21/01: 10 dias parados,
    # o vencimento passa de 31/01 para 10/02.
    resultado = _aparente_nao_duravel(
        data_referencia=date(2026, 2, 5),
        data_reclamacao_fornecedor=date(2026, 1, 11),
        data_resposta_negativa=date(2026, 1, 21),
    )
    assert resultado.dias_obstados == 10
    assert resultado.data_vencimento == date(2026, 2, 10)
    assert resultado.dias_decorridos == 25
    assert resultado.dias_restantes == 5
    assert resultado.situacao == SituacaoPrazo.DENTRO_DO_PRAZO
    assert resultado.reclamacao_considerada is True


def test_ultimo_dia_do_prazo_suspenso_ainda_esta_dentro():
    resultado = _aparente_nao_duravel(
        data_referencia=date(2026, 2, 10),
        data_reclamacao_fornecedor=date(2026, 1, 11),
        data_resposta_negativa=date(2026, 1, 21),
    )
    assert resultado.dias_restantes == 0
    assert resultado.dentro_do_prazo is True


def test_situacao_indeterminada_quando_suspensao_e_interrupcao_divergem():
    # Como suspensão, venceu em 10/02; como interrupção, o prazo recomeça
    # em 21/01 e vai até 20/02.
    resultado = _aparente_nao_duravel(
        data_referencia=date(2026, 2, 15),
        data_reclamacao_fornecedor=date(2026, 1, 11),
        data_resposta_negativa=date(2026, 1, 21),
    )
    assert resultado.data_vencimento_se_interrupcao == date(2026, 2, 20)
    assert resultado.situacao == SituacaoPrazo.INDETERMINADO
    assert resultado.dentro_do_prazo is False
    assert any("PROCON" in obs for obs in resultado.observacoes)


def test_fora_do_prazo_mesmo_lendo_como_interrupcao():
    resultado = _aparente_nao_duravel(
        data_referencia=date(2026, 2, 21),
        data_reclamacao_fornecedor=date(2026, 1, 11),
        data_resposta_negativa=date(2026, 1, 21),
    )
    assert resultado.situacao == SituacaoPrazo.FORA_DO_PRAZO


def test_reclamacao_sem_resposta_deixa_o_prazo_parado():
    # Reclamou em 11/01, quando restavam 20 dias; sem resposta, os 20
    # dias continuam disponíveis em 01/03.
    resultado = _aparente_nao_duravel(
        data_referencia=date(2026, 3, 1),
        data_reclamacao_fornecedor=date(2026, 1, 11),
    )
    assert resultado.obstado_sem_resposta is True
    assert resultado.dias_restantes == 20
    assert resultado.dias_decorridos == 10
    assert resultado.situacao == SituacaoPrazo.DENTRO_DO_PRAZO


def test_reclamacao_feita_depois_do_vencimento_nao_tem_efeito():
    resultado = _aparente_nao_duravel(
        data_referencia=date(2026, 2, 10),
        data_reclamacao_fornecedor=date(2026, 2, 5),
    )
    assert resultado.reclamacao_considerada is False
    assert resultado.data_vencimento == date(2026, 1, 31)
    assert resultado.situacao == SituacaoPrazo.FORA_DO_PRAZO


def test_garantia_e_reclamacao_juntas():
    # Garantia até 01/06 -> vence em 30/08; reclamação em 10/08 (restavam
    # 20 dias), resposta em 20/08 -> 10 dias parados, vence em 09/09.
    resultado = _oculto_duravel(
        data_referencia=date(2026, 9, 5),
        data_fim_garantia_contratual=date(2026, 6, 1),
        data_reclamacao_fornecedor=date(2026, 8, 10),
        data_resposta_negativa=date(2026, 8, 20),
    )
    assert resultado.data_vencimento == date(2026, 9, 9)
    assert resultado.dias_restantes == 4
    assert resultado.dentro_do_prazo is True


@pytest.mark.parametrize("reclamacao, resposta", [
    (None, date(2026, 1, 20)),                  # resposta sem reclamação
    (date(2026, 1, 20), date(2026, 1, 10)),     # resposta antes da reclamação
    (date(2026, 3, 1), None),                   # reclamação depois da data de referência
    (date(2026, 1, 10), date(2026, 3, 1)),      # resposta depois da data de referência
])
def test_datas_da_reclamacao_inconsistentes_levantam_erro(reclamacao, resposta):
    with pytest.raises(DadosInsuficientesError):
        _aparente_nao_duravel(
            data_referencia=date(2026, 2, 1),
            data_reclamacao_fornecedor=reclamacao,
            data_resposta_negativa=resposta,
        )
