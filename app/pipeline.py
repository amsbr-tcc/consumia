"""
Orquestrador do pipeline completo do ConsumIA: liga as quatro etapas
descritas na Metodologia, na ordem correta, e devolve um CasoConsumidor
preenchido.

Entrada: a imagem da nota fiscal, o relato do problema em texto livre
e as datas de entrega e de evidência do defeito, informadas pelo
usuário em campos próprios (a data impressa na nota nem sempre
coincide com elas).

    1. extração da nota fiscal (app.extraction.detector) — com checagem
       de qualidade da foto; se estiver ilegível, o usuário é avisado
       para tirar outra
    2. classificação do vício (app.classification.classifier)
    3. cálculo do prazo (app.prazo.calculator) — determinístico, sem IA
    4. geração da carta (app.letter.generator)

Este módulo não decide regra de negócio nenhuma por conta própria; ele
só chama, nesta ordem, as funções já definidas nos módulos de cada
etapa, o que permite avaliar cada etapa separadamente (Metodologia).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from app.classification.classifier import classificar_relato
from app.extraction.detector import EXTRATOR_DE_IMAGEM_PADRAO, extrair_dados_nota_fiscal
from app.models import CasoConsumidor, RelatoUsuario
from app.prazo.calculator import calcular_prazo

AVISO_LEGAL = (
    "O ConsumIA oferece uma orientação inicial e não substitui a consulta "
    "a um profissional do direito, a um PROCON ou à Defensoria Pública."
)


class CasoForaDeEscopoError(Exception):
    """
    Levantado quando a classificação identifica que o relato não é um
    vício de produto coberto pelo art. 26 do CDC (ex.: é um serviço, ou
    envolve dano à segurança, o que é regido pelos arts. 12 a 17).
    """
    def __init__(self, motivo: str | None, caso: CasoConsumidor | None = None):
        self.motivo = motivo
        self.caso = caso
        super().__init__(motivo or "Caso fora do escopo do protótipo.")


def processar_caso(
    caminho_imagem_nota: str | Path,
    descricao_problema: str,
    data_entrega: date | None = None,
    data_evidencia_defeito: date | None = None,
    data_referencia: date | None = None,
    extrator: str = EXTRATOR_DE_IMAGEM_PADRAO,
    data_reclamacao_fornecedor: date | None = None,
    data_resposta_negativa: date | None = None,
    data_fim_garantia_contratual: date | None = None,
    gerar_carta_se_vencido: bool = False,
) -> CasoConsumidor:
    """
    Executa o pipeline completo para um caso e devolve o CasoConsumidor
    com a nota extraída, a classificação, o prazo e a carta gerada.

    Levanta:
    - ImagemIlegivelError, se a foto da nota não tiver qualidade (o
      usuário deve tirar outra foto) — antes de qualquer chamada ao
      modelo de classificação;
    - CasoForaDeEscopoError, se o caso não for coberto pelo art. 26 do
      CDC (nesse caso, a carta não é gerada);
    - DadosInsuficientesError, se faltar a data necessária ao cálculo.

    Quando o prazo já venceu, ou a situação é indeterminada (depende de
    como se lê o art. 26, §2º), a carta não é gerada (caso.carta fica
    None), a menos que `gerar_carta_se_vencido` seja True: uma carta
    citando o art. 26 fora do prazo poderia induzir o consumidor a erro.
    """
    relato = RelatoUsuario(
        descricao_problema=descricao_problema,
        data_entrega=data_entrega,
        data_evidencia_defeito=data_evidencia_defeito,
        data_reclamacao_fornecedor=data_reclamacao_fornecedor,
        data_resposta_negativa=data_resposta_negativa,
        data_fim_garantia_contratual=data_fim_garantia_contratual,
    )

    # Etapa 1: extração (com checagem de qualidade da foto)
    nota = extrair_dados_nota_fiscal(caminho_imagem_nota, extrator=extrator)
    caso = CasoConsumidor(nota=nota, relato=relato)

    # Etapa 2: classificação
    caso.classificacao = classificar_relato(descricao_problema)
    if caso.classificacao.fora_de_escopo:
        raise CasoForaDeEscopoError(caso.classificacao.motivo_fora_de_escopo, caso=caso)

    # Etapa 3: cálculo do prazo (determinístico, sem IA)
    caso.prazo = calcular_prazo(
        tipo_vicio=caso.classificacao.tipo_vicio,
        durabilidade=caso.classificacao.durabilidade,
        data_entrega=data_entrega,
        data_evidencia_defeito=data_evidencia_defeito,
        data_referencia=data_referencia,
        data_reclamacao_fornecedor=data_reclamacao_fornecedor,
        data_resposta_negativa=data_resposta_negativa,
        data_fim_garantia_contratual=data_fim_garantia_contratual,
    )

    # Etapa 4: geração da carta
    if caso.prazo.dentro_do_prazo or gerar_carta_se_vencido:
        from app.letter.generator import gerar_carta  # import tardio: só exige
        # a chave de API do modelo quando a carta é de fato gerada

        caso.carta = gerar_carta(caso)

    return caso
