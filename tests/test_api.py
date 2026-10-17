"""
Testes da API HTTP (app.api) sem chamar o modelo de linguagem: a foto ruim é
recusada pela checagem de qualidade antes de qualquer chamada externa,
e o pipeline é substituído por um falso nos demais casos.
"""
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app.models import (
    CasoConsumidor,
    ClassificacaoVicio,
    Durabilidade,
    NotaFiscalExtraida,
    RelatoUsuario,
    TipoVicio,
)
from app.prazo.calculator import calcular_prazo
from tests.conftest import foto_real

FOTO_BOA = foto_real("real_10")
cliente = TestClient(api.app)
RELATO = "O liquidificador parou de funcionar depois de dois meses."


def _enviar(nome_arquivo: str, conteudo: bytes, **campos):
    return cliente.post(
        "/casos",
        files={"nota_fiscal": (nome_arquivo, conteudo, "image/jpeg")},
        data={"descricao_problema": RELATO, **campos},
    )


@pytest.mark.parametrize("foto, motivo", [("foto_borrada", "borrada"), ("foto_escura", "escura")])
def test_foto_ruim_responde_422_pedindo_nova_foto(foto, motivo, request):
    resposta = _enviar("nota.jpg", request.getfixturevalue(foto).read_bytes())

    assert resposta.status_code == 422
    detalhe = resposta.json()["detail"]
    assert detalhe["codigo"] == "foto_ilegivel"
    assert detalhe["motivo"] == motivo
    assert detalhe["acao"] == "tirar_nova_foto"
    assert "Tire outra foto" in detalhe["mensagem"]


def test_arquivo_que_nao_e_imagem_responde_415():
    resposta = _enviar("nota.xml", b"<nfe/>")
    assert resposta.status_code == 415


def _caso_falso(data_referencia):
    classificacao = ClassificacaoVicio(TipoVicio.OCULTO, Durabilidade.DURAVEL, justificativa="ok")
    return CasoConsumidor(
        nota=NotaFiscalExtraida(estabelecimento="LOJA X", produtos=["LIQUIDIFICADOR"], valor_total=80.2),
        relato=RelatoUsuario(RELATO),
        classificacao=classificacao,
        prazo=calcular_prazo(TipoVicio.OCULTO, Durabilidade.DURAVEL,
                             data_evidencia_defeito=date(2026, 4, 10), data_referencia=data_referencia),
        carta="Prezados..." if data_referencia < date(2026, 7, 10) else None,
    )


def test_caso_dentro_do_prazo_devolve_diagnostico_carta_e_aviso_legal(monkeypatch):
    monkeypatch.setattr(api, "processar_caso", lambda **_: _caso_falso(date(2026, 4, 20)))
    resposta = _enviar("nota.jpg", FOTO_BOA.read_bytes())

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["dias_restantes"] == 80
    assert corpo["carta"] == "Prezados..."
    assert "não substitui" in corpo["aviso_legal"]


def test_caso_com_prazo_vencido_explica_por_que_nao_ha_carta(monkeypatch):
    monkeypatch.setattr(api, "processar_caso", lambda **_: _caso_falso(date(2026, 9, 1)))
    corpo = _enviar("nota.jpg", FOTO_BOA.read_bytes()).json()

    assert corpo["dentro_do_prazo"] is False
    assert corpo["carta"] is None
    assert "prazo" in corpo["orientacao"]


def test_situacao_indeterminada_nao_gera_carta_e_orienta_procurar_procon(monkeypatch):
    relato = RelatoUsuario(RELATO, data_entrega=date(2026, 1, 1),
                           data_reclamacao_fornecedor=date(2026, 1, 11),
                           data_resposta_negativa=date(2026, 1, 21))
    caso = CasoConsumidor(
        nota=NotaFiscalExtraida(estabelecimento="LOJA X"),
        relato=relato,
        classificacao=ClassificacaoVicio(TipoVicio.APARENTE, Durabilidade.NAO_DURAVEL, justificativa="ok"),
        prazo=calcular_prazo(TipoVicio.APARENTE, Durabilidade.NAO_DURAVEL, data_entrega=date(2026, 1, 1),
                             data_referencia=date(2026, 2, 15),
                             data_reclamacao_fornecedor=date(2026, 1, 11),
                             data_resposta_negativa=date(2026, 1, 21)),
    )
    monkeypatch.setattr(api, "processar_caso", lambda **_: caso)
    corpo = _enviar("nota.jpg", FOTO_BOA.read_bytes()).json()

    assert corpo["situacao_prazo"] == "indeterminado"
    assert corpo["carta"] is None
    assert "PROCON" in corpo["orientacao"]
    assert corpo["observacoes_prazo"]


def test_fora_do_prazo_pergunta_por_garantia_e_reclamacao_nao_informadas(monkeypatch):
    monkeypatch.setattr(api, "processar_caso", lambda **_: _caso_falso(date(2026, 9, 1)))
    corpo = _enviar("nota.jpg", FOTO_BOA.read_bytes()).json()

    assert corpo["situacao_prazo"] == "fora_do_prazo"
    assert "garantia" in corpo["orientacao"] and "reclamação" in corpo["orientacao"]


def test_api_repassa_as_datas_que_alteram_o_prazo(monkeypatch):
    recebido = {}

    def falso(**kwargs):
        recebido.update(kwargs)
        return _caso_falso(date(2026, 4, 20))

    monkeypatch.setattr(api, "processar_caso", falso)
    _enviar("nota.jpg", FOTO_BOA.read_bytes(),
            data_reclamacao_fornecedor="2026-04-12", data_fim_garantia_contratual="2027-01-01")

    assert recebido["data_reclamacao_fornecedor"] == date(2026, 4, 12)
    assert recebido["data_resposta_negativa"] is None
    assert recebido["data_fim_garantia_contratual"] == date(2027, 1, 1)
