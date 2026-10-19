"""
Testes das etapas que usam modelo de linguagem — extração multimodal,
classificação e carta — com um modelo FALSO, que devolve uma resposta
pronta. Testam o que o NOSSO código faz com a resposta (validação,
recusa de foto ilegível, artigos e pedido da carta), sem chamar a API.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.classificacao.classifier import RespostaInvalidaError, classificar_relato, validar_resposta
from app.classificacao.prompts import montar_prompt_com_exemplos
from app.extracao.ocr_multimodal import extrair_via_modelo_multimodal
from app.extracao.qualidade_imagem import ImagemIlegivelError, MotivoImagemRuim
from app.carta.generator import gerar_carta, montar_dados_carta
from app.carta.prompts import artigos_aplicaveis, montar_prompt_usuario
from app.models import (
    CasoConsumidor,
    ClassificacaoVicio,
    Durabilidade,
    FonteExtracao,
    NotaFiscalExtraida,
    RelatoUsuario,
    TipoVicio,
)
from app.prazo.calculator import calcular_prazo

IMAGEM = Path(__file__).parent.parent / "dados" / "fotos" / "real_10.jpg"


class ModeloFalso:
    """Devolve, em ordem, as respostas fornecidas e guarda o que recebeu."""

    def __init__(self, *respostas):
        self._respostas = list(respostas)
        self.chamadas = []

    def gerar(self, conteudo, esquema=None):
        self.chamadas.append((conteudo, esquema))
        resposta = self._respostas.pop(0)
        return resposta if isinstance(resposta, str) else json.dumps(resposta)


# ---------------------------------------------------------------------------
# Extração multimodal
# ---------------------------------------------------------------------------

def _resposta_multimodal(**sobrescrever):
    resposta = {
        "legivel": True,
        "problema_imagem": None,
        "estabelecimento": "FARMACIA BEM ESTAR LTDA",
        "data_emissao": "2026-01-20",
        "produtos": ["DIPIRONA 500MG", "PROTETOR SOLAR FPS50"],
        "valor_total": 45.9,
    }
    resposta.update(sobrescrever)
    return resposta


def test_multimodal_devolve_os_quatro_campos():
    modelo = ModeloFalso(_resposta_multimodal())
    nota = extrair_via_modelo_multimodal(IMAGEM, modelo=modelo)

    assert nota.estabelecimento == "FARMACIA BEM ESTAR LTDA"
    assert nota.data_emissao == date(2026, 1, 20)
    assert nota.produtos == ["DIPIRONA 500MG", "PROTETOR SOLAR FPS50"]
    assert nota.valor_total == 45.9
    assert nota.fonte == FonteExtracao.OCR_MULTIMODAL

    _, esquema = modelo.chamadas[0]
    assert esquema["additionalProperties"] is False  # resposta exigida em JSON estruturado


def test_multimodal_foto_julgada_ilegivel_pede_nova_foto():
    modelo = ModeloFalso(_resposta_multimodal(legivel=False, problema_imagem="imagem tremida"))

    with pytest.raises(ImagemIlegivelError) as erro:
        extrair_via_modelo_multimodal(IMAGEM, modelo=modelo)

    assert erro.value.motivo == MotivoImagemRuim.ILEGIVEL
    assert "imagem tremida" in str(erro.value)


def test_multimodal_sem_nenhum_campo_lido_pede_nova_foto():
    modelo = ModeloFalso(_resposta_multimodal(data_emissao=None, valor_total=None, produtos=[]))

    with pytest.raises(ImagemIlegivelError):
        extrair_via_modelo_multimodal(IMAGEM, modelo=modelo)


def test_multimodal_data_em_formato_errado_vira_none():
    nota = extrair_via_modelo_multimodal(IMAGEM, modelo=ModeloFalso(_resposta_multimodal(data_emissao="20/01/2026")))
    assert nota.data_emissao is None


# ---------------------------------------------------------------------------
# Classificação
# ---------------------------------------------------------------------------

def test_classificacao_valida():
    resposta = {"tipo_vicio": "oculto", "durabilidade": "duravel", "fora_de_escopo": False,
                "justificativa": "Apareceu após meses de uso."}
    classificacao = classificar_relato("relato", modelo=ModeloFalso(resposta))

    assert classificacao.tipo_vicio == TipoVicio.OCULTO
    assert classificacao.durabilidade == Durabilidade.DURAVEL
    assert classificacao.rotulo == "oculto/duravel"


def test_classificacao_fora_de_escopo():
    resposta = {"tipo_vicio": "nenhum", "durabilidade": "nenhum", "fora_de_escopo": True,
                "justificativa": "É um serviço."}
    classificacao = classificar_relato("relato", modelo=ModeloFalso(resposta))

    assert classificacao.fora_de_escopo
    assert classificacao.motivo_fora_de_escopo == "É um serviço."
    assert classificacao.rotulo == "fora_de_escopo"


def test_classificacao_incoerente_e_repetida_e_depois_aceita():
    incoerente = {"tipo_vicio": "nenhum", "durabilidade": "duravel", "fora_de_escopo": False,
                  "justificativa": "?"}
    valida = {"tipo_vicio": "aparente", "durabilidade": "duravel", "fora_de_escopo": False,
              "justificativa": "Chegou quebrado."}
    modelo = ModeloFalso(incoerente, valida)

    assert classificar_relato("relato", modelo=modelo).tipo_vicio == TipoVicio.APARENTE
    assert len(modelo.chamadas) == 2


def test_classificacao_sempre_incoerente_levanta_erro_em_vez_de_seguir():
    incoerente = {"tipo_vicio": "nenhum", "durabilidade": "nenhum", "fora_de_escopo": False,
                  "justificativa": "?"}
    with pytest.raises(RespostaInvalidaError):
        classificar_relato("relato", modelo=ModeloFalso(incoerente, incoerente))


@pytest.mark.parametrize("texto", ["não é json", "[]", '{"fora_de_escopo": "sim", "justificativa": "x"}',
                                   '{"fora_de_escopo": false, "tipo_vicio": "aparente", "durabilidade": "duravel"}'])
def test_validar_resposta_rejeita_respostas_malformadas(texto):
    with pytest.raises(RespostaInvalidaError):
        validar_resposta(texto)


def test_prompt_de_classificacao_mostra_exemplos_em_json():
    prompt = montar_prompt_com_exemplos("Meu ventilador parou.")
    assert '"fora_de_escopo": false' in prompt
    assert "None" not in prompt and "False" not in prompt
    assert prompt.rstrip().endswith("Resposta:")


# ---------------------------------------------------------------------------
# Carta
# ---------------------------------------------------------------------------

def _caso(tipo=TipoVicio.APARENTE, durabilidade=Durabilidade.DURAVEL, estabelecimento="LOJA X"):
    classificacao = ClassificacaoVicio(tipo_vicio=tipo, durabilidade=durabilidade, justificativa="ok")
    return CasoConsumidor(
        nota=NotaFiscalExtraida(estabelecimento=estabelecimento, produtos=["TV 50"],
                                valor_total=2500.0, data_emissao=date(2026, 1, 5)),
        relato=RelatoUsuario("A TV chegou com a tela trincada.", data_entrega=date(2026, 1, 10)),
        classificacao=classificacao,
        prazo=calcular_prazo(tipo, durabilidade, data_entrega=date(2026, 1, 10),
                             data_evidencia_defeito=date(2026, 1, 20),
                             data_referencia=date(2026, 1, 25)),
    )


def test_artigos_sao_decididos_pelo_sistema_conforme_a_classificacao():
    duravel_aparente = " ".join(artigos_aplicaveis(TipoVicio.APARENTE, Durabilidade.DURAVEL))
    assert "art. 18" in duravel_aparente
    assert "inciso II" in duravel_aparente and "§1º" in duravel_aparente

    nao_duravel_oculto = " ".join(artigos_aplicaveis(TipoVicio.OCULTO, Durabilidade.NAO_DURAVEL))
    assert "inciso I " in nao_duravel_oculto and "§3º" in nao_duravel_oculto


def test_artigos_de_garantia_e_reclamacao_so_entram_quando_alteram_o_prazo():
    base = " ".join(artigos_aplicaveis(TipoVicio.OCULTO, Durabilidade.DURAVEL))
    assert "art. 50" not in base and "§2º" not in base

    com_ambos = " ".join(artigos_aplicaveis(
        TipoVicio.OCULTO, Durabilidade.DURAVEL, garantia_contratual=True, reclamacao_anterior=True
    ))
    assert "art. 50" in com_ambos and "§2º, inciso I" in com_ambos


def test_prompt_da_carta_menciona_reclamacao_anterior_sem_resposta():
    caso = _caso()
    caso.relato.data_reclamacao_fornecedor = date(2026, 1, 15)
    caso.prazo = calcular_prazo(TipoVicio.APARENTE, Durabilidade.DURAVEL, data_entrega=date(2026, 1, 10),
                                data_referencia=date(2026, 1, 25),
                                data_reclamacao_fornecedor=date(2026, 1, 15))
    prompt = montar_prompt_usuario(montar_dados_carta(caso))
    assert "Reclamação anterior" in prompt and "ainda sem resposta" in prompt
    assert "§2º, inciso I" in prompt


def test_prompt_da_carta_traz_pedido_do_art_18_e_prazo_para_resposta():
    prompt = montar_prompt_usuario(montar_dados_carta(_caso()))

    assert "30 (trinta) dias" in prompt
    assert "substituição do produto" in prompt
    assert "restituição imediata da quantia paga" in prompt
    assert "abatimento proporcional do preço" in prompt
    assert "Prazo para resposta" in prompt
    assert "LOJA X" in prompt and "TV 50" in prompt


def test_instrucao_da_carta_pede_texto_simples_primeira_pessoa_e_um_so_prazo():
    from app.carta.prompts import INSTRUCAO_SISTEMA, PEDIDO_ART_18

    assert "SEM formatação Markdown" in INSTRUCAO_SISTEMA
    assert "primeira pessoa" in INSTRUCAO_SISTEMA
    assert "único prazo" in INSTRUCAO_SISTEMA
    assert INSTRUCAO_SISTEMA.count("[nome do consumidor]") == 3  # regra, cabeçalho e assinatura
    assert PEDIDO_ART_18.startswith("Peço")


def test_dados_ausentes_viram_marcadores():
    prompt = montar_prompt_usuario(montar_dados_carta(_caso(estabelecimento=None)))
    assert "[nome do fornecedor]" in prompt
    # Os dados do consumidor não são coletados: a instrução fixa os marcadores.
    assert "use os marcadores" in prompt
    from app.carta.prompts import INSTRUCAO_SISTEMA
    assert "[CPF do consumidor]" in INSTRUCAO_SISTEMA


def test_gerar_carta_usa_o_texto_do_modelo():
    modelo = ModeloFalso("  Prezados,\n...  ")
    assert gerar_carta(_caso(), modelo=modelo) == "Prezados,\n..."


def test_carta_nao_e_gerada_para_caso_fora_de_escopo():
    caso = _caso()
    caso.classificacao = ClassificacaoVicio(None, None, fora_de_escopo=True, justificativa="serviço")
    with pytest.raises(ValueError):
        montar_dados_carta(caso)
