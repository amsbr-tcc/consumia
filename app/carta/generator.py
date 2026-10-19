"""
Quarta etapa do pipeline: geração da carta de reclamação formal.

Recebe os dados já produzidos pelas etapas anteriores (extração,
classificação e cálculo do prazo), insere-os numa instrução e pede ao
modelo de linguagem que redija a carta, usando apenas essas informações
e marcando com colchetes os dados ausentes (ver prompts.py).
"""
from __future__ import annotations

from app.config import obter_modelo
from app.carta.prompts import INSTRUCAO_SISTEMA, artigos_aplicaveis, montar_prompt_usuario
from app.models import CasoConsumidor


def _iso(data) -> str | None:
    return data.isoformat() if data else None


def montar_dados_carta(caso: CasoConsumidor) -> dict:
    if caso.classificacao is None or caso.prazo is None:
        raise ValueError(
            "A carta só pode ser gerada depois da classificação e do "
            "cálculo do prazo (etapas 2 e 3 do pipeline)."
        )
    if caso.classificacao.fora_de_escopo:
        raise ValueError("Não há carta para casos fora do escopo do protótipo.")

    return {
        "estabelecimento": caso.nota.estabelecimento,
        "produtos": caso.nota.produtos,
        "valor_total": f"R$ {caso.nota.valor_total:.2f}".replace(".", ",") if caso.nota.valor_total is not None else None,
        "data_emissao": _iso(caso.nota.data_emissao),
        "data_entrega": _iso(caso.relato.data_entrega),
        "data_evidencia_defeito": _iso(caso.relato.data_evidencia_defeito),
        "descricao_problema": caso.relato.descricao_problema,
        "tipo_vicio": caso.classificacao.tipo_vicio.value,
        "durabilidade": caso.classificacao.durabilidade.value,
        "prazo_total_dias": caso.prazo.prazo_total_dias,
        "data_inicio_contagem": _iso(caso.prazo.data_inicio_contagem),
        "data_vencimento": _iso(caso.prazo.data_vencimento),
        "dias_restantes": caso.prazo.dias_restantes,
        "data_carta": _iso(caso.prazo.data_referencia),
        "data_reclamacao_fornecedor": _iso(caso.relato.data_reclamacao_fornecedor) if caso.prazo.reclamacao_considerada else None,
        "data_resposta_negativa": _iso(caso.relato.data_resposta_negativa) if caso.prazo.reclamacao_considerada else None,
        "data_fim_garantia_contratual": _iso(caso.relato.data_fim_garantia_contratual) if caso.prazo.garantia_contratual_considerada else None,
        "artigos": artigos_aplicaveis(
            caso.classificacao.tipo_vicio,
            caso.classificacao.durabilidade,
            garantia_contratual=caso.prazo.garantia_contratual_considerada,
            reclamacao_anterior=caso.prazo.reclamacao_considerada,
        ),
    }


def gerar_carta(caso: CasoConsumidor, modelo=None) -> str:
    """
    Gera o texto da carta de reclamação a partir dos dados já
    calculados nas etapas anteriores do pipeline.

    O parâmetro `modelo` existe para permitir injetar um modelo mockado
    nos testes, sem precisar de uma chamada de API real.
    """
    modelo = modelo or obter_modelo(instrucao_sistema=INSTRUCAO_SISTEMA)
    prompt_usuario = montar_prompt_usuario(montar_dados_carta(caso))

    return modelo.gerar(prompt_usuario).strip()
