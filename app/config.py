"""
Configuração central do projeto: leitura de variáveis de ambiente e
criação do cliente do modelo de linguagem (Claude Sonnet 5.5, pela API
da Anthropic) usado na extração multimodal, na classificação e na
geração da carta.

Mantido num único lugar para que trocar de modelo seja uma alteração
de configuração (.env), sem mexer nos módulos de extração,
classificação e carta. Todos usam a mesma interface:

    modelo.gerar(conteudo, esquema=None) -> str

em que `conteudo` é um texto ou uma lista com textos e imagens (PIL), e
`esquema` (opcional) é um JSON Schema que a resposta deve seguir
(saída estruturada). Nos testes, os módulos recebem um modelo falso com
o mesmo método, sem chamar a API.
"""
from __future__ import annotations

import base64
import io
import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # lê o arquivo .env na raiz do projeto, se existir

# Endereço oficial da API. Fixado aqui para que nenhuma variável de
# ambiente externa (ex.: ANTHROPIC_BASE_URL de outra ferramenta) desvie
# as chamadas do protótipo.
_URL_API = "https://api.anthropic.com"

# Modelo fixo, para os resultados do TCC serem reproduzíveis.
MODELO_LLM = os.getenv("MODELO_CLAUDE", "claude-sonnet-5-5")

# Nível de esforço (profundidade do raciocínio): low, medium, high,
# xhigh ou max. O Claude Sonnet 5.5 não aceita ajustar a temperatura; o
# esforço é o parâmetro de geração disponível.
ESFORCO = os.getenv("ESFORCO_CLAUDE", "low")

# Lado maior da imagem enviada ao modelo (limite para leitura em alta
# resolução). Fotos maiores são reduzidas antes do envio.
_LADO_MAXIMO_IMAGEM = 2576

# Tentativas automáticas do SDK em erros temporários (429 e 5xx), com
# espera crescente entre elas.
_TENTATIVAS_SDK = 5


class RecusaDoModeloError(RuntimeError):
    """O modelo recusou responder (stop_reason "refusal")."""


def _imagem_para_bloco(imagem) -> dict:
    """Imagem PIL -> bloco de imagem em base64 (JPEG), reduzida se preciso."""
    imagem = imagem.convert("RGB")
    if max(imagem.size) > _LADO_MAXIMO_IMAGEM:
        imagem = imagem.copy()
        imagem.thumbnail((_LADO_MAXIMO_IMAGEM, _LADO_MAXIMO_IMAGEM))
    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=90)
    dados = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": dados}}


class ModeloClaude:
    """Envolve o cliente do SDK `anthropic` na interface `gerar` do projeto."""

    def __init__(self, client, nome_modelo: str, instrucao_sistema: str | None = None):
        self._client = client
        self.nome_modelo = nome_modelo
        self._instrucao_sistema = instrucao_sistema

    def gerar(self, conteudo: Any, esquema: dict | None = None) -> str:
        partes = conteudo if isinstance(conteudo, list) else [conteudo]
        blocos = [
            {"type": "text", "text": parte} if isinstance(parte, str) else _imagem_para_bloco(parte)
            for parte in partes
        ]
        # Imagem antes do texto, como recomendado para entradas visuais.
        blocos.sort(key=lambda bloco: bloco["type"] != "image")

        output_config: dict[str, Any] = {"effort": ESFORCO}
        if esquema:
            output_config["format"] = {"type": "json_schema", "schema": esquema}

        parametros: dict[str, Any] = {
            "model": self.nome_modelo,
            "max_tokens": 16000,
            "messages": [{"role": "user", "content": blocos}],
            "output_config": output_config,
        }
        if self._instrucao_sistema:
            parametros["system"] = self._instrucao_sistema

        resposta = self._client.messages.create(**parametros)
        if resposta.stop_reason == "refusal":
            raise RecusaDoModeloError(f"O modelo recusou responder: {resposta.stop_details}")
        return "".join(bloco.text for bloco in resposta.content if bloco.type == "text")


def modelo_configurado() -> bool:
    """True se há uma ANTHROPIC_API_KEY no ambiente/.env."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def obter_modelo(instrucao_sistema: str | None = None, nome_modelo: str | None = None) -> ModeloClaude:
    """
    Cria o cliente do modelo sob demanda (e não no import), para que os
    testes que não chamam a API não precisem de chave.

    `instrucao_sistema` fixa o comportamento do modelo (usada na
    classificação e na carta). `nome_modelo` permite usar outro modelo
    Claude (ex.: comparar modelos na extração).
    """
    import anthropic

    if not modelo_configurado():
        raise RuntimeError(
            "ANTHROPIC_API_KEY não configurada. Crie uma chave em "
            "https://console.anthropic.com e coloque no .env (ver .env.example)."
        )
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"], base_url=_URL_API, max_retries=_TENTATIVAS_SDK
    )
    return ModeloClaude(client, nome_modelo or MODELO_LLM, instrucao_sistema=instrucao_sistema)
