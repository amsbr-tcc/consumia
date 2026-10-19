"""
Anonimização dos PDFs das notas fiscais antes do uso no experimento
(Metodologia, LGPD): remove de fato o texto com dados pessoais (não só
cobre com tarja, porque num PDF digital o texto continua embutido e
seria lido pelos extratores e enviado ao modelo de linguagem).

- CPF: localizado por padrão (com ou sem pontuação);
- nome, endereço, telefone e outros dados do consumidor: lidos de um
  arquivo de termos, um por linha, guardado FORA da pasta do projeto
  (~/.consumia/termos_pessoais.txt, ou o caminho na variável de
  ambiente CONSUMIA_TERMOS), para nenhum dado pessoal ficar no projeto.

Depois de apagar, o PDF anonimizado é lido de novo e o script falha se
algum dos termos ou um CPF ainda aparecer no texto.

Uso:

    python3 -m avaliacao.anonimizar_pdf ENTRADA.pdf SAIDA.pdf
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

PADRAO_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
ARQUIVO_TERMOS = Path(os.getenv("CONSUMIA_TERMOS", Path.home() / ".consumia" / "termos_pessoais.txt"))


def ler_termos(caminho: Path = ARQUIVO_TERMOS) -> list[str]:
    if not caminho.exists():
        raise SystemExit(f"Crie {caminho} com os dados pessoais a apagar (um termo por linha).")
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    return [t.strip() for t in linhas if t.strip() and not t.startswith("#")]


def _so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e sem nada além de letras e dígitos."""
    import unicodedata

    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^0-9a-z]", "", sem_acento.lower())


def _tem_dado_pessoal(texto: str, termos: list[str]) -> bool:
    """
    Procura os termos também em texto "embaralhado" (camadas de texto
    sobrepostas no PDF), comparando sem espaços nem pontuação, e os
    números (CPF, telefone) só pelos dígitos.
    """
    if PADRAO_CPF.search(texto):
        return True
    normalizado, digitos = _normalizar(texto), _so_digitos(texto)
    for termo in termos:
        if len(_so_digitos(termo)) >= 8:
            if _so_digitos(termo) in digitos:
                return True
        elif len(_normalizar(termo)) >= 5 and _normalizar(termo) in normalizado:
            return True
    return False


def anonimizar(entrada: Path, saida: Path, termos: list[str]) -> int:
    """Apaga CPFs e termos pessoais; devolve o número de trechos apagados."""
    import pymupdf

    documento = pymupdf.open(entrada)
    apagados = 0
    for pagina in documento:
        texto = pagina.get_text()
        alvos = set(termos) | set(PADRAO_CPF.findall(texto))
        for alvo in alvos:
            for retangulo in pagina.search_for(alvo):
                pagina.add_redact_annot(retangulo, fill=(0, 0, 0))
                apagados += 1
        # Remove o texto e o desenho sob as tarjas (mantém as imagens).
        pagina.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
        # 2ª passada: blocos em que ainda sobrou dado pessoal (texto
        # intercalado com outras camadas) são apagados por inteiro.
        for x0, y0, x1, y1, texto_bloco, *_ in pagina.get_text("blocks"):
            if _tem_dado_pessoal(texto_bloco, termos):
                pagina.add_redact_annot(pymupdf.Rect(x0, y0, x1, y1), fill=(0, 0, 0))
                apagados += 1
        pagina.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    documento.save(saida, garbage=4, deflate=True)
    documento.close()
    return apagados


def verificar(caminho: Path, termos: list[str]) -> list[str]:
    """Termos ou CPFs que ainda aparecem no texto do PDF."""
    import pymupdf

    with pymupdf.open(caminho) as documento:
        texto = "\n".join(pagina.get_text() for pagina in documento)
    restantes = [t for t in termos if t.lower() in texto.lower()]
    restantes += PADRAO_CPF.findall(texto)
    digitos, normalizado = _so_digitos(texto), _normalizar(texto)
    restantes += [t for t in termos if len(_so_digitos(t)) >= 8 and _so_digitos(t) in digitos]
    restantes += [t for t in termos if len(_so_digitos(t)) < 8 and len(_normalizar(t)) >= 5
                  and _normalizar(t) in normalizado]
    return restantes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apaga dados pessoais de um PDF de nota fiscal.")
    parser.add_argument("entrada", type=Path)
    parser.add_argument("saida", type=Path)
    args = parser.parse_args(argv)

    termos = ler_termos()
    apagados = anonimizar(args.entrada, args.saida, termos)
    restantes = verificar(args.saida, termos)
    if restantes:
        args.saida.unlink()
        raise SystemExit(f"Ainda restaram {len(restantes)} dado(s) pessoal(is); o PDF não foi salvo.")
    print(f"{args.saida}: {apagados} trecho(s) apagado(s); nenhum dado pessoal restante.")


if __name__ == "__main__":
    main()
