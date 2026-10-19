"""
Testes do adaptador do Claude (app.config.ModeloClaude) com um cliente
falso: não chamam a API nem precisam de chave.
"""
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from app.config import ModeloClaude, RecusaDoModeloError
from app.extracao.ocr_multimodal import _ESQUEMA_RESPOSTA


class ClienteFalso:
    def __init__(self, texto='{"ok": true}', stop_reason="end_turn"):
        self.chamadas = []
        self._resposta = SimpleNamespace(
            stop_reason=stop_reason,
            stop_details=None,
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
        )
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **parametros):
        self.chamadas.append(parametros)
        return self._resposta


def test_imagem_vai_antes_do_texto_reduzida_e_com_esquema_json():
    cliente = ClienteFalso()
    modelo = ModeloClaude(cliente, "claude-sonnet-5-5", instrucao_sistema="instrução")
    imagem = Image.new("RGB", (4032, 3024), "white")

    texto = modelo.gerar(["Extraia os campos.", imagem], esquema=_ESQUEMA_RESPOSTA)

    assert json.loads(texto) == {"ok": True}
    parametros = cliente.chamadas[0]
    assert parametros["system"] == "instrução"
    assert parametros["output_config"]["format"] == {"type": "json_schema", "schema": _ESQUEMA_RESPOSTA}
    assert "temperature" not in parametros
    blocos = parametros["messages"][0]["content"]
    assert [b["type"] for b in blocos] == ["image", "text"]
    assert blocos[0]["source"]["media_type"] == "image/jpeg"


def test_texto_simples_sem_esquema():
    cliente = ClienteFalso(texto="Prezados,")
    assert ModeloClaude(cliente, "claude-sonnet-5-5").gerar("Redija a carta.") == "Prezados,"
    assert "format" not in cliente.chamadas[0]["output_config"]


def test_recusa_do_modelo_levanta_erro():
    modelo = ModeloClaude(ClienteFalso(stop_reason="refusal"), "claude-sonnet-5-5")
    with pytest.raises(RecusaDoModeloError):
        modelo.gerar("texto")
