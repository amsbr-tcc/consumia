"""
Testes das expressões regulares que localizam os quatro campos da nota
no texto reconhecido pelo Tesseract (app.extraction.regex_campos).
Usam texto pronto, então não exigem o Tesseract instalado.
"""
from datetime import date

import pytest

from app.extraction.regex_campos import (
    extrair_data_emissao,
    extrair_estabelecimento,
    extrair_produtos,
    extrair_valor_total,
)

TEXTO_OCR = """
FARMACIA BEM ESTAR LTDA

CNPJ: 12.345.678/0001-99

RUA DAS FLORES, 100 — CENTRO — SAO PAULO/SP
DOCUMENTO AUXILIAR DA NOTA FISCAL DE
CONSUMIDOR ELETRONICA

COD DESCRICAO QTD UN VL TOTAL
001 DIPIRONA 500MG 1 UN 12,90
002 PROTETOR SOLAR FPS50 1 UN 33,00
QTD. TOTAL DE ITENS 2
VALOR TOTAL R$ 45,90
FORMA DE PAGAMENTO CARTAO DE DEBITO
Protocolo de autorizacao: 135260000000001 19/01/2026
EMISSAO: 20/01/2026 14:32:10
CONSUMIDOR NAO IDENTIFICADO
"""


def test_estabelecimento_e_a_linha_acima_do_cnpj():
    assert extrair_estabelecimento(TEXTO_OCR) == "FARMACIA BEM ESTAR LTDA"


def test_estabelecimento_sem_cnpj_reconhecido_usa_primeira_linha_do_cabecalho():
    texto = "DOCUMENTO AUXILIAR DA NOTA FISCAL\nLOJA DO BAIRRO ME\nRUA A, 1"
    assert extrair_estabelecimento(texto) == "LOJA DO BAIRRO ME"


@pytest.mark.parametrize("texto, esperado", [
    # Endereço entre o nome e o CNPJ (Armarinhos Fernando): antes, o
    # sistema devolvia "CENTRO - SAO PAULO -".
    ("ARMARINHOS FERNANDO LTDA\nARMARINHOS FERNANDO\nRUA VINTE E CINCO DE MARCO, 864 872\n"
     "CENTRO - SAO PAULO -\nCNPJ 48.076.228/0001-91 IE 109.667.825.118", "ARMARINHOS FERNANDO LTDA"),
    ("Outback Steakhouse Restaurantes Brasil S A\nAV ANTONIO FREDERICO OZANAN 6000 LOJA LUC 060\n"
     "1 PISO\nVILA RIO BRANCO\nJUNDIAI 35 13215900\nCNPJ: 17261661020107 IE: 132494310116",
     "Outback Steakhouse Restaurantes Brasil S A"),
    # Nome na mesma linha do CNPJ.
    ("CNPJ: 05.406.034/0025-71 PUMA SPORTS LTDA\nJoaquim Bueno Neto, 9999 Itupeva - SP", "PUMA SPORTS LTDA"),
    ("DROGARIA SAO PAULO SA CNPJ-61.412.110/0613-75\nDos Imigrantes,299,Jardim Junco,Vinhedo-SP",
     "DROGARIA SAO PAULO SA"),
    # Nome continuando na linha de baixo do CNPJ.
    ("CNPJ: 12.011.363/0001-01 HR2 COMERCIO\nVAREJISTA DE ROUPAS EM GERAL LTDA\nVOLUNTARIOS DA PATRIA, 2182 Adamantina - SP",
     "HR2 COMERCIO VAREJISTA DE ROUPAS EM GERAL LTDA"),
    # Rótulo "Razao Social:" e nome fantasia antes da razão social.
    ("RIACHUELO\nRazao Social: Lojas Riachuelo SA\nCNPJ: 33200056061792", "Lojas Riachuelo SA"),
])
def test_estabelecimento_em_leiautes_reais(texto, esperado):
    assert extrair_estabelecimento(texto) == esperado


def test_produtos_sao_as_descricoes_das_linhas_de_item():
    assert extrair_produtos(TEXTO_OCR) == ["DIPIRONA 500MG", "PROTETOR SOLAR FPS50"]


def test_linhas_que_nao_sao_item_nao_viram_produto():
    assert extrair_produtos("QTD. TOTAL DE ITENS 2\nVALOR TOTAL R$ 45,90") == []


def test_produto_com_quantidade_decimal_e_unidade_kg():
    assert extrair_produtos("003 BANANA PRATA 1,250 KG 7,49") == ["BANANA PRATA"]


def test_data_de_emissao_prefere_a_data_marcada_como_emissao():
    # O texto tem outra data antes (a do protocolo); a de emissão é a certa.
    assert extrair_data_emissao(TEXTO_OCR) == date(2026, 1, 20)


def test_data_sem_rotulo_usa_a_primeira_data():
    assert extrair_data_emissao("compra em 05/02/2026") == date(2026, 2, 5)


def test_data_invalida_vira_none():
    assert extrair_data_emissao("EMISSAO: 31/02/2026") is None


def test_valor_total_formato_brasileiro():
    assert extrair_valor_total(TEXTO_OCR) == 45.90
    assert extrair_valor_total("VALOR A PAGAR R$ 1.234,56") == 1234.56
    assert extrair_valor_total("sem total aqui") is None


def test_valor_total_prefere_valor_a_pagar_depois_do_desconto():
    # Leiaute real (Outback): "VALOR TOTAL" é antes do desconto.
    texto = "VALOR TOTAL R$ 106,88\nDESCONTO R$ 16,90\nVALOR A PAGAR R$ 89,98"
    assert extrair_valor_total(texto) == 89.98
    assert extrair_valor_total("VALOR TOTAL PAGAR R$ 229,97") == 229.97


def test_valor_total_com_ponto_decimal_e_rotulo_curto():
    # Leiaute real (Armarinhos Fernando): "TOTAL R$____ 18.29".
    assert extrair_valor_total("Total dos itens:______ 18.29\nTOTAL R$__________ 18.29") == 18.29
    # "SUBTOTAL" não deve ser confundido com "TOTAL".
    assert extrair_valor_total("SUBTOTAL R$ 68,02") is None
