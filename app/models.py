"""
Modelos de dados usados em todo o pipeline do ConsumIA.

Mantidos como dataclasses simples (em vez de um ORM) porque o protótipo
não persiste dados em banco; cada execução do pipeline é independente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class TipoVicio(str, Enum):
    APARENTE = "aparente"
    OCULTO = "oculto"


class Durabilidade(str, Enum):
    DURAVEL = "duravel"
    NAO_DURAVEL = "nao_duravel"


class FonteExtracao(str, Enum):
    """
    Como os dados da nota fiscal foram obtidos: abordagem tradicional
    (Tesseract na foto, ou texto embutido no PDF, com expressões
    regulares) ou modelo de linguagem multimodal.
    """
    OCR_TESSERACT = "ocr_tesseract"
    TEXTO_PDF = "texto_pdf"            # texto embutido no PDF, sem OCR
    OCR_MULTIMODAL = "ocr_multimodal"


# Os quatro campos da nota fiscal extraídos e avaliados (Metodologia,
# primeira etapa). Usado também como lista de campos do gabarito.
CAMPOS_NOTA = ("estabelecimento", "data_emissao", "produtos", "valor_total")


@dataclass
class NotaFiscalExtraida:
    """Dados extraídos da imagem da nota fiscal, independente da abordagem."""
    estabelecimento: Optional[str] = None
    data_emissao: Optional[date] = None
    produtos: list[str] = field(default_factory=list)
    valor_total: Optional[float] = None
    fonte: Optional[FonteExtracao] = None
    confianca: Optional[float] = None   # 0-1, quando a fonte fornece uma estimativa
    observacoes: list[str] = field(default_factory=list)
    # Texto bruto reconhecido pelo OCR (só no Tesseract); usado para
    # conferir a leitura do OCR (depuração).
    texto_reconhecido: Optional[str] = None


@dataclass
class RelatoUsuario:
    """
    Entrada do consumidor: o relato em texto livre e as datas, que são
    informadas em campos próprios porque a data impressa na nota nem
    sempre coincide com a entrega ou com o aparecimento do defeito.
    """
    descricao_problema: str
    data_entrega: Optional[date] = None
    data_evidencia_defeito: Optional[date] = None
    # Situações que alteram o prazo do art. 26 (ver app/prazo/calculator.py):
    # reclamação já feita ao fornecedor (art. 26, §2º, I) e garantia
    # contratual (art. 50). Todas opcionais: sem elas, vale o prazo legal puro.
    data_reclamacao_fornecedor: Optional[date] = None
    data_resposta_negativa: Optional[date] = None
    data_fim_garantia_contratual: Optional[date] = None


@dataclass
class ClassificacaoVicio:
    """
    Saída da etapa de classificação (modelo de linguagem via prompting).

    tipo_vicio e durabilidade só são None quando fora_de_escopo é True
    (o relato não descreve um vício de produto coberto pelo art. 26).
    """
    tipo_vicio: Optional[TipoVicio]
    durabilidade: Optional[Durabilidade]
    fora_de_escopo: bool = False
    motivo_fora_de_escopo: Optional[str] = None
    justificativa: str = ""

    @property
    def rotulo(self) -> str:
        """Rótulo único do caso, usado nas métricas de classificação."""
        if self.fora_de_escopo:
            return "fora_de_escopo"
        return f"{self.tipo_vicio.value}/{self.durabilidade.value}"


class SituacaoPrazo(str, Enum):
    DENTRO_DO_PRAZO = "dentro_do_prazo"
    FORA_DO_PRAZO = "fora_do_prazo"
    # O resultado depende de como se lê o "obstam" do art. 26, §2º
    # (suspensão ou interrupção): o sistema não afirma que o prazo venceu.
    INDETERMINADO = "indeterminado"


@dataclass
class PrazoResultado:
    """Saída do cálculo determinístico do prazo (art. 26 do CDC)."""
    prazo_total_dias: int
    data_inicio_contagem: date
    data_vencimento: date
    data_referencia: date
    dias_decorridos: int
    dias_restantes: int
    situacao: SituacaoPrazo
    # Dias em que o prazo ficou parado pela reclamação ao fornecedor.
    dias_obstados: int = 0
    # True enquanto a reclamação ao fornecedor aguarda resposta.
    obstado_sem_resposta: bool = False
    garantia_contratual_considerada: bool = False
    reclamacao_considerada: bool = False
    # Vencimento se o "obstam" for lido como interrupção (só com reclamação).
    data_vencimento_se_interrupcao: Optional[date] = None
    observacoes: list[str] = field(default_factory=list)

    @property
    def dentro_do_prazo(self) -> bool:
        return self.situacao == SituacaoPrazo.DENTRO_DO_PRAZO


@dataclass
class CasoConsumidor:
    """Agrega tudo que o pipeline produz para um caso, do início ao fim."""
    nota: NotaFiscalExtraida
    relato: RelatoUsuario
    classificacao: Optional[ClassificacaoVicio] = None
    prazo: Optional[PrazoResultado] = None
    carta: Optional[str] = None
