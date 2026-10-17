"""
Cálculo do prazo decadencial para reclamação de vício de produto,
conforme o art. 26 da Lei nº 8.078/1990 (Código de Defesa do Consumidor).

Esta etapa é implementada como regra determinística, sem uso de modelo de
linguagem, exatamente como descrito na Metodologia do trabalho: as etapas
que aplicam uma regra explícita da lei são mais seguras quando não dependem
de um modelo de linguagem, que pode "alucinar" e informar um prazo errado.

Regras aplicadas (Brasil, 1990, art. 26):
    - 30 dias para produtos ou serviços não duráveis;
    - 90 dias para produtos ou serviços duráveis;
    - no vício aparente (ou de fácil constatação), a contagem começa na
      entrega efetiva do produto (art. 26, §1º);
    - no vício oculto, a contagem só começa no momento em que o defeito
      se evidencia (art. 26, §3º).

A contagem do prazo segue o art. 132 do Código Civil (Brasil, 2002):
exclui-se o dia do começo e inclui-se o dia do vencimento. Isso é obtido
naturalmente somando `prazo_total_dias` à data de início: o próprio dia
de início (dia 0) não é contado, e o último dia somado é incluído.

Situações que alteram o prazo, tratadas porque o sistema informa ao
consumidor se ele ainda pode reclamar (um "fora do prazo" errado pode
fazê-lo desistir de um direito que ainda tem):

    - garantia contratual (art. 50): é complementar à legal, então o
      prazo do art. 26 só começa a correr quando ela termina, se isso for
      depois do início normal da contagem;
    - reclamação comprovadamente feita ao fornecedor (art. 26, §2º, I):
      obsta a decadência até a resposta negativa inequívoca. O sistema
      lê "obstam" como SUSPENSÃO (o intervalo entre a reclamação e a
      resposta não é contado). Como parte da doutrina lê como
      INTERRUPÇÃO (o prazo recomeça inteiro após a resposta), quando as
      duas leituras levam a conclusões diferentes a situação é
      INDETERMINADO, e não "fora do prazo". Reclamação sem resposta deixa
      o prazo parado; reclamação feita depois do vencimento não tem efeito.

Este módulo NÃO trata:
    - a instauração de inquérito civil (art. 26, §2º, III), rara em
      reclamações individuais;
    - o prazo de 5 anos do fato do produto (arts. 12 a 17 e 27), que trata
      de dano à segurança do consumidor, não do vício de qualidade.
Essas exclusões são explicitadas como limitação na Metodologia do trabalho.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.models import Durabilidade, PrazoResultado, SituacaoPrazo, TipoVicio

PRAZO_DIAS = {
    Durabilidade.NAO_DURAVEL: 30,
    Durabilidade.DURAVEL: 90,
}


class DadosInsuficientesError(ValueError):
    """Levantado quando falta a data necessária para iniciar a contagem."""


def determinar_data_inicio_contagem(
    tipo_vicio: TipoVicio,
    data_entrega: date | None,
    data_evidencia_defeito: date | None,
) -> date:
    """
    Decide qual data marca o início da contagem do prazo, segundo o
    tipo de vício (art. 26, §§1º e 3º do CDC).

    Vício aparente: conta da entrega efetiva do produto.
    Vício oculto: conta do momento em que o defeito se tornou evidente.
    """
    if tipo_vicio == TipoVicio.APARENTE:
        if data_entrega is None:
            raise DadosInsuficientesError(
                "Vício aparente requer a data de entrega do produto."
            )
        return data_entrega

    if tipo_vicio == TipoVicio.OCULTO:
        if data_evidencia_defeito is None:
            raise DadosInsuficientesError(
                "Vício oculto requer a data em que o defeito se evidenciou."
            )
        return data_evidencia_defeito

    raise ValueError(f"tipo_vicio desconhecido: {tipo_vicio!r}")


def calcular_prazo(
    tipo_vicio: TipoVicio,
    durabilidade: Durabilidade,
    data_entrega: date | None = None,
    data_evidencia_defeito: date | None = None,
    data_referencia: date | None = None,
    data_reclamacao_fornecedor: date | None = None,
    data_resposta_negativa: date | None = None,
    data_fim_garantia_contratual: date | None = None,
) -> PrazoResultado:
    """
    Calcula o prazo decadencial restante para reclamação de vício de
    produto, conforme o art. 26 do CDC.

    Parâmetros
    ----------
    tipo_vicio: TipoVicio.APARENTE ou TipoVicio.OCULTO
    durabilidade: Durabilidade.DURAVEL ou Durabilidade.NAO_DURAVEL
    data_entrega: obrigatória se o vício for aparente
    data_evidencia_defeito: obrigatória se o vício for oculto
    data_referencia: data para a qual o prazo restante é calculado
        (por padrão, hoje). Existe como parâmetro explícito, e não
        `date.today()` direto no corpo da função, para permitir testes
        determinísticos com datas fixas.
    data_reclamacao_fornecedor: quando o consumidor já reclamou ao
        fornecedor (art. 26, §2º, I)
    data_resposta_negativa: resposta negativa do fornecedor a essa
        reclamação (None = ainda sem resposta)
    data_fim_garantia_contratual: fim da garantia dada pelo fabricante
        ou pela loja (art. 50), se houver

    Retorna um PrazoResultado com o prazo total, a data de início da
    contagem, a data de vencimento, os dias decorridos, os dias
    restantes e a situação (dentro do prazo, fora do prazo ou
    indeterminado).
    """
    if durabilidade not in PRAZO_DIAS:
        raise ValueError(f"durabilidade desconhecida: {durabilidade!r}")

    data_referencia = data_referencia or date.today()

    inicio_legal = determinar_data_inicio_contagem(
        tipo_vicio, data_entrega, data_evidencia_defeito
    )
    if inicio_legal > data_referencia:
        raise DadosInsuficientesError(
            "A data de início da contagem não pode ser posterior à data de referência."
        )
    _validar_reclamacao(data_reclamacao_fornecedor, data_resposta_negativa, data_referencia)

    observacoes: list[str] = []
    prazo_total = PRAZO_DIAS[durabilidade]

    # Garantia contratual (art. 50): o prazo legal só corre depois dela.
    data_inicio = inicio_legal
    garantia_considerada = False
    if data_fim_garantia_contratual and data_fim_garantia_contratual > inicio_legal:
        data_inicio = data_fim_garantia_contratual
        garantia_considerada = True
        observacoes.append(
            "A garantia contratual é complementar à legal (art. 50 do CDC): o prazo "
            f"do art. 26 só começa a contar no fim dela, em {data_inicio.isoformat()}."
        )

    vencimento_sem_obstaculo = data_inicio + timedelta(days=prazo_total)
    data_vencimento = vencimento_sem_obstaculo
    vencimento_se_interrupcao = None
    dias_obstados = 0
    obstado_sem_resposta = False
    reclamacao_considerada = False

    # Reclamação ao fornecedor (art. 26, §2º, I), lida como suspensão.
    if data_reclamacao_fornecedor is not None:
        if data_reclamacao_fornecedor > vencimento_sem_obstaculo:
            observacoes.append(
                "A reclamação ao fornecedor foi feita depois do vencimento do prazo, "
                "por isso não altera a contagem."
            )
        else:
            inicio_obstaculo = max(data_reclamacao_fornecedor, data_inicio)
            fim_obstaculo = data_resposta_negativa or data_referencia
            dias_obstados = max(0, (fim_obstaculo - inicio_obstaculo).days)
            obstado_sem_resposta = data_resposta_negativa is None
            reclamacao_considerada = obstado_sem_resposta or dias_obstados > 0
            data_vencimento = vencimento_sem_obstaculo + timedelta(days=dias_obstados)
            if obstado_sem_resposta:
                observacoes.append(
                    "Há reclamação ao fornecedor ainda sem resposta: o prazo fica parado "
                    "até a resposta negativa (art. 26, §2º, I). Guarde o comprovante "
                    "da reclamação (protocolo, e-mail ou mensagem)."
                )
            elif dias_obstados > 0:
                vencimento_se_interrupcao = data_resposta_negativa + timedelta(days=prazo_total)
                observacoes.append(
                    f"O prazo ficou parado por {dias_obstados} dia(s), entre a reclamação "
                    "ao fornecedor e a resposta negativa (art. 26, §2º, I)."
                )

    dias_decorridos = max(0, (data_referencia - data_inicio).days - dias_obstados)
    dias_restantes = max(0, (data_vencimento - data_referencia).days)

    if data_referencia <= data_vencimento:
        situacao = SituacaoPrazo.DENTRO_DO_PRAZO
    elif vencimento_se_interrupcao and data_referencia <= vencimento_se_interrupcao:
        situacao = SituacaoPrazo.INDETERMINADO
        observacoes.append(
            "Contando o intervalo da reclamação como suspensão, o prazo venceu em "
            f"{data_vencimento.isoformat()}; contando como interrupção, ele vai até "
            f"{vencimento_se_interrupcao.isoformat()}. Como há divergência sobre isso, "
            "procure um PROCON ou um profissional do direito."
        )
    else:
        situacao = SituacaoPrazo.FORA_DO_PRAZO

    return PrazoResultado(
        prazo_total_dias=prazo_total,
        data_inicio_contagem=data_inicio,
        data_vencimento=data_vencimento,
        data_referencia=data_referencia,
        dias_decorridos=dias_decorridos,
        dias_restantes=dias_restantes,
        situacao=situacao,
        dias_obstados=dias_obstados,
        obstado_sem_resposta=obstado_sem_resposta,
        garantia_contratual_considerada=garantia_considerada,
        reclamacao_considerada=reclamacao_considerada,
        data_vencimento_se_interrupcao=vencimento_se_interrupcao,
        observacoes=observacoes,
    )


def _validar_reclamacao(
    data_reclamacao: date | None, data_resposta: date | None, data_referencia: date
) -> None:
    if data_resposta is not None and data_reclamacao is None:
        raise DadosInsuficientesError(
            "Informe a data da reclamação ao fornecedor junto com a data da resposta."
        )
    if data_reclamacao is not None and data_reclamacao > data_referencia:
        raise DadosInsuficientesError(
            "A data da reclamação ao fornecedor não pode ser posterior à data de referência."
        )
    if data_resposta is not None:
        if data_resposta < data_reclamacao:
            raise DadosInsuficientesError(
                "A resposta do fornecedor não pode ser anterior à reclamação."
            )
        if data_resposta > data_referencia:
            raise DadosInsuficientesError(
                "A data da resposta do fornecedor não pode ser posterior à data de referência."
            )
