# ConsumIA — backend

Protótipo de sistema de apoio à decisão para orientação de consumidores
sobre garantia e vícios de produtos, com base no Código de Defesa do
Consumidor (CDC).

> O ConsumIA oferece uma orientação inicial e **não substitui** a
> consulta a um profissional do direito. Esse aviso é devolvido pela
> API em toda resposta (`aviso_legal`), para a interface exibir.

## Entrada

- **Foto da nota fiscal** (.jpg, .jpeg, .png ou .webp);
- **relato do problema** em texto livre;
- **data de entrega** e **data em que o defeito apareceu**, em campos
  próprios (a data impressa na nota nem sempre coincide com elas);
- opcionais, porque alteram o prazo: **data da reclamação já feita ao
  fornecedor** e **data da resposta negativa** (art. 26, §2º, I), e
  **data de fim da garantia contratual** (art. 50).

## Pipeline (as quatro etapas da Metodologia)

1. **Extração da nota fiscal** (`app/extraction/`): estabelecimento,
   data de emissão, produtos e valor total, por uma de duas abordagens
   comparadas entre si:
   - **Tesseract** (`ocr_tesseract.py`): tons de cinza + binarização,
     e expressões regulares para achar os campos (`regex_campos.py`);
   - **modelo multimodal Claude Sonnet 5.5** (`ocr_multimodal.py`):
     recebe a imagem e uma instrução que pede os mesmos campos em JSON.

   Antes de extrair, a foto passa por uma **checagem de qualidade**
   (`qualidade_imagem.py`). Se estiver **borrada, escura, sem contraste
   ou pequena demais**, ou se a extração não conseguir ler nada, o
   usuário recebe uma mensagem pedindo para **tirar outra foto** (ver
   [Foto ruim](#foto-ruim-pedir-nova-foto)).
2. **Classificação do vício** (`app/classification/`): Claude Sonnet 5.5
   com aprendizado em contexto (instrução + exemplos), resposta exigida
   em JSON, **validada** antes de seguir, com esforço baixo (o modelo não
   permite ajustar a temperatura). Indica vício
   aparente/oculto e produto durável/não durável, ou que o caso está
   fora do escopo (serviços, danos à segurança).
3. **Cálculo do prazo** (`app/prazo/`): regra determinística do art. 26
   do CDC, sem IA; contagem pelo art. 132 do Código Civil. Considera a
   **garantia contratual** (o prazo legal só corre depois dela, art. 50)
   e a **reclamação ao fornecedor** (o prazo fica parado até a resposta
   negativa, art. 26, §2º, I, lido como suspensão). Quando a leitura
   como interrupção levaria a outra conclusão, a situação é
   `indeterminado` (o sistema não diz que o prazo venceu e orienta
   procurar o PROCON). Situações possíveis: `dentro_do_prazo`,
   `fora_do_prazo` e `indeterminado`.
4. **Geração da carta** (`app/letter/`): o Claude redige a carta só com
   os dados fornecidos (ausentes viram `[marcadores]`). Os artigos
   citados são **decididos pelo sistema** (`artigos_aplicaveis`), e o
   pedido segue o art. 18, §1º (30 dias para sanar; depois
   substituição, restituição ou abatimento); com garantia contratual ou
   reclamação anterior, entram também o art. 50 e o art. 26, §2º, I.
   Quando o prazo já venceu ou está indeterminado, a carta não é gerada
   e a API explica o motivo (`orientacao`), sem afirmar que o consumidor
   perdeu o direito.

`app/pipeline.py` liga as quatro etapas; `app/api.py` expõe tudo como
API HTTP (FastAPI) para a interface web.

## Linguagem e bibliotecas

Python (3.11 ou mais recente), com: `pytesseract` + Tesseract OCR
(idioma português), `Pillow` e `NumPy` (pré-processamento e checagem de
qualidade da imagem), `anthropic` (SDK oficial da Anthropic, para o Claude), `FastAPI`
e `Uvicorn` (API) e `pytest` (testes).

## Instalação

### 1. Python e dependências

```bash
cd consumia-backend
python3 -m venv venv
source venv/bin/activate       # no Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Tesseract (OCR)

**macOS** (com o [Homebrew](https://brew.sh)):
```bash
brew install tesseract tesseract-lang
```

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-por
```

**Windows:** instalador em https://github.com/UB-Mannheim/tesseract/wiki
(marque o idioma português na instalação).

### 3. Chave da API da Anthropic (Claude)

1. Acesse https://console.anthropic.com e crie uma conta (pessoa física,
   com cartão de crédito).
2. Em **Billing**, compre crédito pré-pago (a avaliação completa custa
   menos de US$ 1 com o Claude Sonnet 5.5).
3. Em **API Keys**, crie uma chave.
4. Copie `.env.example` para `.env` e cole a chave:

```bash
cp .env.example .env
# depois edite o .env e preencha ANTHROPIC_API_KEY=...
```

**Nunca** suba o arquivo `.env` para o GitHub (ele já está no `.gitignore`).

O modelo (`MODELO_CLAUDE=claude-sonnet-5-5`) e o nível de esforço
(`ESFORCO_CLAUDE=low`) ficam fixos no `.env`, para os resultados serem
reproduzíveis.

## Casos de teste

Os casos ficam em `tests/casos/casos.json`, com as imagens em
`tests/casos/imagens/`. Cada caso traz a foto, o relato, as datas e o
gabarito (campos da nota, classificação e dias restantes) — o formato
completo está documentado em `app/evaluation/casos.py`.

O arquivo tem **17 casos com fotos reais** (`tests/casos/reais/`), já
com CPF, nome e demais dados pessoais cobertos por tarjas pretas e sem os
metadados da foto (GPS incluído): 15 fotos legíveis e 2 ruins que o
sistema deve recusar (`real_16`, com o dedo na frente da nota, e
`real_17`, tremida). O campo `"observacao_gabarito"` explica cada caso e
indica o que ainda deve ser conferido na nota física. O projeto não usa
imagens sintéticas: nos testes de foto borrada ou escura, a versão ruim é
gerada na hora a partir de uma foto real (`tests/conftest.py`).

Critérios dos casos reais, conforme a Metodologia:

- fotos de notas de compras reais das autoras, **com CPF e demais
  dados pessoais ocultados antes** (só imagens já tratadas podem ir
  para o modelo de linguagem — LGPD);
- fotografadas em condições variadas de luz e enquadramento;
- cobrindo vício aparente/oculto × durável/não durável, prazo vencido,
  prazo perto do fim e casos fora do escopo;
- `"data_referencia"` fixa o "hoje" de cada caso, para os dias
  restantes do gabarito não mudarem conforme o dia em que se roda;
- incluam casos com garantia contratual e com reclamação já feita ao
  fornecedor (`"data_reclamacao_fornecedor"`, `"data_resposta_negativa"`,
  `"data_fim_garantia_contratual"`), e, no gabarito, a situação esperada
  (`"esperado": {"situacao": "dentro_do_prazo" | "fora_do_prazo" | "indeterminado"}`).

## Comparação Tesseract × modelo multimodal (etapa 1)

Compara as duas abordagens **sobre as mesmas imagens**:

- acurácia por campo, consistência entre as 3 leituras de cada foto e
  tempo médio;
- **matriz de resultados** de cada abordagem: para cada campo, em
  quantas notas o valor saiu **correto**, **incorreto** (valor errado,
  que seguiria para a carta como verdadeiro), **não extraído** (vazio,
  vira `[marcador]` na carta) ou com **foto recusada**; com precisão,
  revocação e F1 por campo;
- **matriz de concordância Tesseract × multimodal**: em quantas notas
  as duas acertam o campo, só uma acerta, ou as duas erram;
- **matriz da checagem da foto** (gabarito legível/ilegível × sistema
  aceitou/recusou).

Cada execução fica numa pasta própria, `resultados/<AAAA-MM-DD_HHMMSS>_extracao/`:

```
relatorio.txt   relatório completo
dados.json      todos os números, caso a caso
tabelas_csv/    as mesmas tabelas em CSV, para planilha
figuras/        matrizes e tabelas em PNG, prontas para o TCC
```

Pela pasta de testes (pytest):

```bash
python3 -m pytest tests/test_comparacao_tesseract_vs_multimodal.py -s
```

Ou direto pelo terminal, com mais opções:

```bash
# Tesseract × Claude (modelo do .env)
python3 -m app.evaluation.comparar_extracao tests/casos/casos.json

# comparando mais de um modelo multimodal
python3 -m app.evaluation.comparar_extracao tests/casos/casos.json --modelos claude-sonnet-5-5,claude-opus-5-5

# só Tesseract (sem chave de API)
python3 -m app.evaluation.comparar_extracao tests/casos/casos.json --sem-multimodal

# sem a checagem de qualidade (mede os extratores "puros")
python3 -m app.evaluation.comparar_extracao tests/casos/casos.json --sem-checagem-qualidade
```

Exemplo do formato da saída (valores ilustrativos, não são resultados reais):

```
=== Comparação lado a lado ===
campo                     tesseract  multimodal:claude-sonnet-5-5
estabelecimento                100%                         100%
data_emissao                   100%                         100%
produtos                        67%                         100%
valor_total                    100%                         100%
MÉDIA                           92%                         100%
```

Com o resultado, configure a abordagem vencedora no `.env`
(`EXTRATOR_IMAGEM=tesseract` ou `multimodal`).

Critério de acerto de cada campo (`app/evaluation/metricas.py`):
estabelecimento igual ignorando maiúsculas, acentos e pontuação;
produtos com exatamente os mesmos itens (em qualquer ordem); valor
total igual até o centavo; data igual.

## Avaliação da classificação, do prazo, do diagnóstico e das cartas

```bash
python3 -m app.evaluation.avaliar_casos tests/casos/casos.json --extrator multimodal
```

- **Classificação**: cada relato é classificado 3 vezes. Para a 1ª
  execução, **matrizes de confusão** de tipo de vício, durabilidade e
  classificação completa (linhas = gabarito, colunas = sistema), com
  acurácia, precisão, revocação e F1 por categoria derivadas delas;
  uma matriz com todas as 3 execuções e a consistência entre elas;
- **Prazo**: dias restantes calculados com a classificação e as datas
  do gabarito × dias restantes esperados;
- **Diagnóstico completo**: proporção de casos com classificação e
  prazo iguais aos do gabarito, e matriz de confusão da situação final
  (dentro do prazo / fora do prazo / fora do escopo), que mostra o
  impacto prático de cada erro — por exemplo, um vício oculto
  classificado como aparente faz um caso dentro do prazo parecer vencido;
- as matrizes também são salvas em CSV em
  `tabelas_csv/` e, como imagens PNG prontas para o TCC, em `figuras/`
  (entre elas a **matriz de confusão do tipo de vício**,
  `01_matriz_tipo_vicio.png`);
- tudo numa pasta própria, `resultados/<AAAA-MM-DD_HHMMSS>_avaliacao/`;
- **Cartas**: salvas em `cartas/`, dentro da pasta da execução, uma por
  caso, já com a **lista de verificação** da análise qualitativa
  (identificação das partes, fatos, fundamento legal, pedido, prazo
  para resposta, uso só dos dados informados, artigos corretos) para
  vocês preencherem.

## Foto ruim: pedir nova foto

Quando a foto não tem qualidade, a API responde **HTTP 422**:

```json
{
  "detail": {
    "codigo": "foto_ilegivel",
    "motivo": "borrada",
    "mensagem": "A foto da nota fiscal está borrada. Tire outra foto com o celular parado e a nota em foco.",
    "acao": "tirar_nova_foto"
  }
}
```

`motivo` pode ser `borrada`, `escura`, `sem_contraste`,
`resolucao_baixa` ou `ilegivel` (passou na checagem, mas nem o OCR nem
o modelo conseguiram ler a nota). A interface deve mostrar `mensagem`
e abrir a câmera de novo. A checagem acontece **antes** de qualquer
chamada ao modelo de linguagem, então foto ruim não gasta crédito da API.

Os limiares foram calibrados com as imagens sintéticas; depois de
testar com as fotos reais, ajustem se necessário no `.env`
(`QUALIDADE_LIMIAR_NITIDEZ` etc.).

## Rodando os testes

```bash
python3 -m pytest
```

Os testes de prazo, regex, métricas, checagem de qualidade, lógica de
comparação, API e das etapas com modelo de linguagem (com modelo falso)
**não** precisam de chave de API. `test_comparacao_tesseract_vs_multimodal.py`
roda o Tesseract instalado e, se houver `ANTHROPIC_API_KEY`, chama o
Claude de verdade (é pulado se faltar o Tesseract). Para rodar só os testes
rápidos:

```bash
python3 -m pytest -m "not integracao"
```

## Rodando a API localmente

```bash
uvicorn app.api:app --reload
```

Depois, abra http://localhost:8000/docs para testar pela interface
interativa do FastAPI (dá para enviar a foto e o relato pelo navegador).

## Limitações (documentar no TCC)

- Trata a garantia contratual e a reclamação ao fornecedor com base
  só nas datas informadas pelo usuário (não confere comprovantes). A
  reclamação é lida como suspensão; os casos em que a interrupção
  mudaria a conclusão ficam como `indeterminado`.
- Não trata a instauração de inquérito civil (art. 26, §2º, III).
- A extração por regex do Tesseract foi pensada para o leiaute do
  DANFE NFC-e (cupom fiscal); notas com leiaute muito diferente podem
  ter campos não encontrados.
- Casos fora do escopo (serviços, danos à segurança — arts. 12 a 17)
  são só identificados e encaminhados, sem carta.

## Estrutura do projeto

```
consumia-backend/
├── app/
│   ├── models.py              # estruturas de dados compartilhadas
│   ├── config.py              # configuração do modelo (Claude)
│   ├── pipeline.py            # orquestra as 4 etapas
│   ├── api.py                 # API HTTP (FastAPI)
│   ├── extraction/
│   │   ├── detector.py        # checagem da foto + escolha do extrator
│   │   ├── qualidade_imagem.py # foto borrada/escura/pequena -> pedir nova
│   │   ├── ocr_tesseract.py   # abordagem 1: Tesseract + regex
│   │   ├── regex_campos.py    # regex dos 4 campos
│   │   └── ocr_multimodal.py  # abordagem 2: Claude (imagem -> JSON)
│   ├── classification/
│   │   ├── classifier.py      # classificação + validação da resposta
│   │   └── prompts.py         # instrução e exemplos (few-shot)
│   ├── prazo/
│   │   └── calculator.py      # cálculo determinístico (art. 26 CDC)
│   ├── letter/
│   │   ├── generator.py       # geração da carta via Claude
│   │   └── prompts.py         # instrução, artigos e pedido (art. 18)
│   └── evaluation/
│       ├── metricas.py        # acurácia, P/R/F1, consistência
│       ├── casos.py           # carregamento dos casos de teste
│       ├── comparar_extracao.py  # etapa 1: Tesseract × multimodal
│       ├── avaliar_casos.py   # etapas 2-4 e diagnóstico completo
│       └── figuras.py         # matrizes e tabelas em PNG
├── tests/
│   ├── casos/
│   │   ├── casos.json         # os 17 casos reais + gabarito
│   │   └── reais/             # fotos das notas (dados pessoais ocultados)
│   ├── conftest.py            # fotos usadas pelos testes
│   └── test_*.py
├── resultados/                # uma pasta por execução da avaliação
│   ├── <data>_extracao/       # relatorio.txt, dados.json, tabelas_csv/, figuras/
│   ├── <data>_avaliacao/      # idem + cartas/
│   └── antigos/               # execuções anteriores (casos sintéticos)
├── requirements.txt
└── .env.example
```
