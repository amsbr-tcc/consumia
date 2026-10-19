"""
API HTTP mínima para o front-end (a interface web prototipada com
ferramenta de desenvolvimento assistido por IA) enviar a foto da nota
fiscal, o relato do usuário e as datas, e receber de volta o
diagnóstico e a carta.

Rodar localmente com:
    uvicorn app.api:app --reload

E abrir a documentação interativa em http://localhost:8000/docs

Foto ruim: quando a foto da nota está borrada, escura, pequena demais
ou ilegível, a API responde HTTP 422 com este corpo, para o front-end
mostrar a mensagem e pedir uma nova foto:

    {"detail": {"codigo": "foto_ilegivel",
                "motivo": "borrada",
                "mensagem": "A foto da nota fiscal está borrada. Tire outra foto ...",
                "acao": "tirar_nova_foto"}}
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.classificacao.classifier import RespostaInvalidaError
from app.extracao.detector import EXTENSOES_ACEITAS, FormatoNaoSuportadoError
from app.extracao.qualidade_imagem import ImagemIlegivelError
from app.pipeline import AVISO_LEGAL, CasoForaDeEscopoError, processar_caso
from app.models import PrazoResultado, RelatoUsuario, SituacaoPrazo
from app.prazo.calculator import DadosInsuficientesError

app = FastAPI(
    title="ConsumIA",
    description=(
        "Protótipo de sistema de apoio à decisão para orientação de "
        "consumidores sobre garantia e vícios de produtos, com base no "
        "Código de Defesa do Consumidor. " + AVISO_LEGAL
    ),
    version="0.2.0",
)

# Em produção, restrinja allow_origins ao domínio real do front-end,
# em vez de "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RespostaCaso(BaseModel):
    fora_de_escopo: bool
    motivo_fora_de_escopo: str | None = None
    estabelecimento: str | None = None
    data_emissao: str | None = None
    produtos: list[str] = []
    valor_total: float | None = None
    tipo_vicio: str | None = None
    durabilidade: str | None = None
    justificativa: str | None = None
    prazo_total_dias: int | None = None
    dias_decorridos: int | None = None
    dias_restantes: int | None = None
    dentro_do_prazo: bool | None = None
    situacao_prazo: str | None = None   # dentro_do_prazo, fora_do_prazo ou indeterminado
    data_vencimento: str | None = None
    observacoes_prazo: list[str] = []
    avisos: list[str] = []  # dados informados que parecem incoerentes, para o usuário conferir
    carta: str | None = None
    orientacao: str | None = None
    aviso_legal: str = AVISO_LEGAL


def avisos_de_datas(data_emissao, relato: RelatoUsuario) -> list[str]:
    """
    Datas informadas que parecem incoerentes. Não impedem a análise, mas
    o usuário deve conferir, porque elas definem o início do prazo.
    """
    def br(d):
        return d.strftime("%d/%m/%Y")

    avisos = []
    if data_emissao and relato.data_entrega and relato.data_entrega < data_emissao:
        avisos.append(
            f"A data de recebimento informada ({br(relato.data_entrega)}) é anterior à data "
            f"da nota fiscal ({br(data_emissao)}). Confira a data, porque ela é usada no "
            "cálculo do prazo."
        )
    if relato.data_entrega and relato.data_evidencia_defeito and relato.data_evidencia_defeito < relato.data_entrega:
        avisos.append(
            f"A data em que o defeito apareceu ({br(relato.data_evidencia_defeito)}) é anterior "
            f"à data de recebimento ({br(relato.data_entrega)}). Confira as duas datas."
        )
    return avisos


def orientacao_prazo(prazo: PrazoResultado, relato: RelatoUsuario) -> str | None:
    """
    Texto para o usuário quando não há carta por causa do prazo. Mesmo
    fora do prazo, o sistema não afirma que o consumidor perdeu o
    direito: aponta o que não foi informado e poderia mudar o resultado.
    """
    if prazo.situacao == SituacaoPrazo.INDETERMINADO:
        return (
            "Não é possível dizer com segurança se o prazo para reclamar "
            "terminou: o resultado depende de como se conta o período da sua "
            "reclamação ao fornecedor (art. 26, §2º, I, do CDC). Por isso a "
            "carta não foi gerada. Procure o PROCON da sua cidade ou um "
            "profissional do direito."
        )
    if prazo.situacao == SituacaoPrazo.FORA_DO_PRAZO:
        nao_informado = []
        if relato.data_reclamacao_fornecedor is None:
            nao_informado.append("uma reclamação já feita ao fornecedor")
        if relato.data_fim_garantia_contratual is None:
            nao_informado.append("uma garantia do fabricante ou da loja")
        complemento = (
            " Se houver " + " ou ".join(nao_informado) + ", informe a data, "
            "porque isso pode aumentar o prazo."
            if nao_informado else ""
        )
        return (
            "Pelo cálculo do art. 26 do CDC, o prazo para reclamar deste vício "
            f"terminou em {prazo.data_vencimento.strftime('%d/%m/%Y')}, por isso a "
            f"carta não foi gerada.{complemento} Em caso de dúvida, procure o "
            "PROCON da sua cidade ou um profissional do direito."
        )
    return None


@app.get("/saude")
def checar_saude():
    """Endpoint simples para confirmar que a API está no ar."""
    return {"status": "ok"}


@app.post(
    "/casos",
    response_model=RespostaCaso,
    responses={
        415: {"description": "O arquivo enviado não é uma imagem suportada."},
        422: {"description": "Foto da nota ilegível: o usuário deve tirar outra foto."},
    },
)
async def criar_caso(
    nota_fiscal: UploadFile = File(..., description="Foto (.jpg, .jpeg, .png ou .webp) ou PDF da nota fiscal"),
    descricao_problema: str = Form(..., min_length=10),
    data_entrega: date | None = Form(None),
    data_evidencia_defeito: date | None = Form(None),
    data_reclamacao_fornecedor: date | None = Form(
        None, description="Se já reclamou do problema ao fornecedor, a data da reclamação"),
    data_resposta_negativa: date | None = Form(
        None, description="Data da resposta negativa do fornecedor a essa reclamação, se houve"),
    data_fim_garantia_contratual: date | None = Form(
        None, description="Data em que termina a garantia do fabricante ou da loja, se houver"),
):
    """
    Recebe a foto da nota fiscal, o relato do problema e as datas,
    executa o pipeline completo e devolve o diagnóstico e a carta de
    reclamação.
    """
    sufixo = Path(nota_fiscal.filename or "").suffix.lower()
    if sufixo not in EXTENSOES_ACEITAS:
        raise HTTPException(
            status_code=415,
            detail=f"Envie uma foto ou o PDF da nota fiscal ({', '.join(sorted(EXTENSOES_ACEITAS))}).",
        )

    with tempfile.NamedTemporaryFile(suffix=sufixo, delete=False) as tmp:
        shutil.copyfileobj(nota_fiscal.file, tmp)
        caminho_temporario = Path(tmp.name)

    try:
        caso = processar_caso(
            caminho_imagem_nota=caminho_temporario,
            descricao_problema=descricao_problema,
            data_entrega=data_entrega,
            data_evidencia_defeito=data_evidencia_defeito,
            data_reclamacao_fornecedor=data_reclamacao_fornecedor,
            data_resposta_negativa=data_resposta_negativa,
            data_fim_garantia_contratual=data_fim_garantia_contratual,
        )
    except ImagemIlegivelError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "codigo": "foto_ilegivel",
                "motivo": exc.motivo.value,
                "mensagem": exc.mensagem_usuario,
                "acao": "tirar_nova_foto",
            },
        ) from exc
    except FormatoNaoSuportadoError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except CasoForaDeEscopoError as exc:
        return RespostaCaso(
            fora_de_escopo=True,
            motivo_fora_de_escopo=exc.motivo,
            orientacao=(
                "Este caso está fora do que o ConsumIA consegue orientar "
                "(por exemplo, serviços ou danos à saúde e à segurança). "
                "Procure o PROCON da sua cidade ou um profissional do direito."
            ),
        )
    except DadosInsuficientesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RespostaInvalidaError as exc:
        raise HTTPException(
            status_code=502,
            detail="Não foi possível classificar o relato agora. Tente novamente.",
        ) from exc
    finally:
        caminho_temporario.unlink(missing_ok=True)

    orientacao = orientacao_prazo(caso.prazo, caso.relato)

    return RespostaCaso(
        fora_de_escopo=False,
        estabelecimento=caso.nota.estabelecimento,
        data_emissao=caso.nota.data_emissao.isoformat() if caso.nota.data_emissao else None,
        produtos=caso.nota.produtos,
        valor_total=caso.nota.valor_total,
        tipo_vicio=caso.classificacao.tipo_vicio.value,
        durabilidade=caso.classificacao.durabilidade.value,
        justificativa=caso.classificacao.justificativa,
        prazo_total_dias=caso.prazo.prazo_total_dias,
        dias_decorridos=caso.prazo.dias_decorridos,
        dias_restantes=caso.prazo.dias_restantes,
        dentro_do_prazo=caso.prazo.dentro_do_prazo,
        situacao_prazo=caso.prazo.situacao.value,
        data_vencimento=caso.prazo.data_vencimento.isoformat(),
        observacoes_prazo=caso.prazo.observacoes,
        avisos=avisos_de_datas(caso.nota.data_emissao, caso.relato),
        carta=caso.carta,
        orientacao=orientacao,
    )
