"""
Carregamento dos casos de teste usados na avaliação do protótipo
(Metodologia: 15 casos simulados de reclamação, cada um com a foto de
uma nota fiscal real das autoras — com CPF e dados pessoais ocultados —
e um relato escrito pelas autoras, mais o gabarito).

O arquivo de casos é um JSON com uma lista de objetos neste formato
(ver dados/casos_foto.json):

    {
      "id": "caso_01",
      "imagem": "fotos/real_01.jpg",
      "foto_ilegivel": false,                   (true = o sistema deve pedir nova foto)
      "nota": {                                 (gabarito da extração; null se ilegível)
        "estabelecimento": "FARMACIA BEM ESTAR LTDA",  (ou lista de nomes aceitos)
        "data_emissao": "2026-01-20",
        "produtos": ["DIPIRONA 500MG", "PROTETOR SOLAR FPS50"],
        "valor_total": 45.90
      },
      "relato": "Abri o protetor solar e ...",
      "data_entrega": "2026-01-20",
      "data_evidencia_defeito": null,
      "data_referencia": "2026-02-01",          (data "de hoje" no caso, para o prazo ser reprodutível)
      "data_reclamacao_fornecedor": null,       (opcionais: situações que alteram o prazo,
      "data_resposta_negativa": null,            ver app/prazo/calculator.py)
      "data_fim_garantia_contratual": null,
      "esperado": {                             (gabarito da classificação e do prazo)
        "fora_de_escopo": false,
        "tipo_vicio": "aparente",
        "durabilidade": "nao_duravel",
        "dias_restantes": 18,
        "situacao": "dentro_do_prazo"           (opcional: dentro_do_prazo, fora_do_prazo
      }                                          ou indeterminado)
    }

Casos em PDF ficam em dados/casos_pdf.json, com "arquivo" no
lugar de "imagem" e "mesma_nota_que" apontando para o caso com a foto
da mesma nota (o gabarito é copiado dele):

    {"id": "pdf_02", "arquivo": "pdfs/pdf_02.pdf", "mesma_nota_que": "real_02"}

Os caminhos são resolvidos em relação à pasta do próprio arquivo de
casos, para que o conjunto possa ser movido sem editar caminhos.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from avaliacao.metricas import AlternativasAceitas
from app.models import CAMPOS_NOTA


@dataclass
class EsperadoCaso:
    fora_de_escopo: bool
    tipo_vicio: str | None = None
    durabilidade: str | None = None
    dias_restantes: int | None = None
    # dentro_do_prazo, fora_do_prazo ou indeterminado. Opcional: sem ela,
    # a situação esperada é calculada a partir da classificação do gabarito.
    situacao: str | None = None

    @property
    def rotulo(self) -> str:
        """Mesmo formato de ClassificacaoVicio.rotulo, para comparar."""
        if self.fora_de_escopo:
            return "fora_de_escopo"
        return f"{self.tipo_vicio}/{self.durabilidade}"


@dataclass
class CasoDeTeste:
    id: str
    imagem: Path
    # Gabarito dos campos da nota (vazio quando foto_ilegivel é True).
    gabarito: dict[str, Any] = field(default_factory=dict)
    foto_ilegivel: bool = False
    relato: str | None = None
    data_entrega: date | None = None
    data_evidencia_defeito: date | None = None
    data_referencia: date | None = None
    data_reclamacao_fornecedor: date | None = None
    data_resposta_negativa: date | None = None
    data_fim_garantia_contratual: date | None = None
    esperado: EsperadoCaso | None = None
    # Para casos em PDF: id do caso com a foto da mesma nota (de onde vem o gabarito).
    mesma_nota_que: str | None = None

    @property
    def tipo_entrada(self) -> str:
        """"pdf" ou "foto", pela extensão do arquivo."""
        return "pdf" if self.imagem.suffix.lower() == ".pdf" else "foto"


def _data(valor: str | None) -> date | None:
    return datetime.strptime(valor, "%Y-%m-%d").date() if valor else None


def _normalizar_gabarito_nota(nota: dict[str, Any] | None) -> dict[str, Any]:
    """
    Mantém só os quatro campos avaliados e converte a data (o JSON não
    tem tipo "data") para `date`, como os extratores devolvem.
    """
    if not nota:
        return {}
    gabarito = {}
    for campo in CAMPOS_NOTA:
        if campo not in nota:
            continue
        valor = nota[campo]
        if campo == "data_emissao":
            valor = _data(valor)
        elif campo == "estabelecimento" and isinstance(valor, list):
            valor = AlternativasAceitas(valor)  # mais de um nome aceito
        elif campo == "produtos":
            # Um item pode aceitar mais de uma forma (lista dentro da lista).
            valor = [AlternativasAceitas(v) if isinstance(v, list) else v for v in valor]
        gabarito[campo] = valor
    return gabarito


def _notas_das_fotos(pasta_base: Path, dados: list[dict]) -> dict[str, dict]:
    """
    Gabaritos das notas dos casos com foto (dados/casos_foto.json), para
    os casos em PDF que indicam "mesma_nota_que": assim, foto e PDF da
    mesma nota são avaliados contra o mesmo gabarito.
    """
    if not any(item.get("mesma_nota_que") for item in dados):
        return {}
    fotos = json.loads((pasta_base / "casos_foto.json").read_text(encoding="utf-8"))
    return {item["id"]: item["nota"] for item in fotos if item.get("nota")}


def carregar_casos(caminho_casos: str | Path) -> list[CasoDeTeste]:
    """
    Lê o arquivo JSON de casos e devolve a lista de casos de teste, com
    caminhos resolvidos e datas convertidas para `date`.
    """
    caminho_casos = Path(caminho_casos)
    pasta_base = caminho_casos.parent
    dados = json.loads(caminho_casos.read_text(encoding="utf-8"))
    notas_das_fotos = _notas_das_fotos(pasta_base, dados)

    casos = []
    for item in dados:
        esperado = item.get("esperado")
        nota = item.get("nota")
        if nota is None and item.get("mesma_nota_que"):
            nota = notas_das_fotos[item["mesma_nota_que"]]

        casos.append(
            CasoDeTeste(
                id=item["id"],
                imagem=pasta_base / item.get("arquivo", item.get("imagem")),
                gabarito=_normalizar_gabarito_nota(nota),
                foto_ilegivel=bool(item.get("foto_ilegivel", False)),
                relato=item.get("relato"),
                data_entrega=_data(item.get("data_entrega")),
                data_evidencia_defeito=_data(item.get("data_evidencia_defeito")),
                data_referencia=_data(item.get("data_referencia")),
                data_reclamacao_fornecedor=_data(item.get("data_reclamacao_fornecedor")),
                data_resposta_negativa=_data(item.get("data_resposta_negativa")),
                data_fim_garantia_contratual=_data(item.get("data_fim_garantia_contratual")),
                esperado=EsperadoCaso(**esperado) if esperado else None,
                mesma_nota_que=item.get("mesma_nota_que"),
            )
        )

    imagens_faltando = [str(c.imagem) for c in casos if not c.imagem.exists()]
    if imagens_faltando:
        raise FileNotFoundError(
            "Imagens listadas no arquivo de casos não foram encontradas: "
            + ", ".join(imagens_faltando)
        )

    return casos
