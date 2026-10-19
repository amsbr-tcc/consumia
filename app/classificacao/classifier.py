"""
Segunda etapa do pipeline: classificação do relato do consumidor
quanto ao tipo de vício (aparente ou oculto) e à categoria do produto
(durável ou não durável), ou indicação de que o caso está fora do
escopo do protótipo, por meio de um modelo de linguagem usado com
aprendizado em contexto (Brown et al., 2020; ver prompts.py).

Conforme a Metodologia:
- a resposta é exigida em JSON (saída estruturada, com JSON Schema);
- a resposta é VALIDADA antes de seguir para o cálculo do prazo
  (`validar_resposta`): se vier incoerente, o modelo é consultado de
  novo, e, se continuar incoerente, levanta RespostaInvalidaError em vez
  de seguir com uma classificação inventada;
- usa esforço baixo (ver app/config.py); o modelo usado não permite
  ajustar a temperatura, e a variação entre execuções é medida na
  avaliação (cada relato é classificado três vezes).
"""
from __future__ import annotations

import json

from app.classificacao.prompts import INSTRUCAO_SISTEMA, montar_prompt_com_exemplos
from app.config import obter_modelo
from app.models import ClassificacaoVicio, Durabilidade, TipoVicio

_ESQUEMA_RESPOSTA = {
    "type": "object",
    "properties": {
        "tipo_vicio": {
            "type": "string",
            "enum": ["aparente", "oculto", "nenhum"],
        },
        "durabilidade": {
            "type": "string",
            "enum": ["duravel", "nao_duravel", "nenhum"],
        },
        "fora_de_escopo": {"type": "boolean"},
        "justificativa": {"type": "string"},
    },
    "required": ["tipo_vicio", "durabilidade", "fora_de_escopo", "justificativa"],
    "additionalProperties": False,
}

_TENTATIVAS = 2


class RespostaInvalidaError(ValueError):
    """A resposta do modelo não passou na validação (JSON ou valores incoerentes)."""


def validar_resposta(texto_resposta: str) -> ClassificacaoVicio:
    """
    Converte o JSON devolvido pelo modelo numa ClassificacaoVicio,
    conferindo que ele é coerente: um caso dentro do escopo precisa ter
    tipo de vício E durabilidade válidos, e toda resposta precisa de
    justificativa.
    """
    try:
        campos = json.loads(texto_resposta)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RespostaInvalidaError(f"Resposta não é um JSON válido: {texto_resposta!r}") from exc

    if not isinstance(campos, dict):
        raise RespostaInvalidaError(f"Resposta não é um objeto JSON: {texto_resposta!r}")

    fora_de_escopo = campos.get("fora_de_escopo")
    justificativa = (campos.get("justificativa") or "").strip()

    if not isinstance(fora_de_escopo, bool):
        raise RespostaInvalidaError("Campo fora_de_escopo ausente ou não booleano.")
    if not justificativa:
        raise RespostaInvalidaError("Resposta sem justificativa.")

    if fora_de_escopo:
        return ClassificacaoVicio(
            tipo_vicio=None,
            durabilidade=None,
            fora_de_escopo=True,
            motivo_fora_de_escopo=justificativa,
            justificativa=justificativa,
        )

    try:
        tipo_vicio = TipoVicio(campos.get("tipo_vicio"))
        durabilidade = Durabilidade(campos.get("durabilidade"))
    except ValueError as exc:
        raise RespostaInvalidaError(
            "Caso dentro do escopo, mas sem tipo de vício ou durabilidade válidos: "
            f"{campos.get('tipo_vicio')!r}, {campos.get('durabilidade')!r}"
        ) from exc

    return ClassificacaoVicio(
        tipo_vicio=tipo_vicio,
        durabilidade=durabilidade,
        fora_de_escopo=False,
        justificativa=justificativa,
    )


def classificar_relato(relato: str, modelo=None) -> ClassificacaoVicio:
    """
    Classifica o relato do consumidor quanto ao tipo de vício e à
    categoria do produto, ou indica que está fora do escopo.

    O parâmetro `modelo` existe para permitir injetar um modelo mockado
    nos testes, sem precisar de uma chamada de API real.
    """
    modelo = modelo or obter_modelo(instrucao_sistema=INSTRUCAO_SISTEMA)
    prompt = montar_prompt_com_exemplos(relato)

    erro: RespostaInvalidaError | None = None
    for _ in range(_TENTATIVAS):
        resposta = modelo.gerar(prompt, esquema=_ESQUEMA_RESPOSTA)
        try:
            return validar_resposta(resposta)
        except RespostaInvalidaError as exc:
            erro = exc

    raise erro
