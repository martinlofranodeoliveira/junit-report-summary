# JUnit Report Summary

Resuma relatórios JUnit XML locais em JSON ou Markdown. As contagens vêm dos casos de teste reais, evitando somar novamente os contadores de suítes aninhadas. Python 3.10 ou superior, somente biblioteca padrão, licença MIT. Não executa testes, acessa a rede ou modifica os arquivos de entrada.

```sh
python -m junit_report_summary examples/backend.xml
python -m junit_report_summary examples/backend.xml --format markdown
python -m junit_report_summary examples/backend.xml --fail-on-problems
```

O exemplo é sintético: três testes, um aprovado, uma falha, um ignorado e soma exata de `0.6` segundo. O último comando retorna `1` devido à falha proposital. Mensagens, rastros de erro e saídas dos testes não são incluídos.

Para combinar relatórios, passe os caminhos explicitamente na ordem desejada. Não há busca recursiva nem expansão de padrões pelo programa; o shell pode expandir padrões antes da execução. Aceita arquivos regulares e links para arquivos regulares; rejeita diretórios e arquivos especiais.

```python
from pathlib import Path
from junit_report_summary import parse_report, combine_reports

report = parse_report(Path("examples/backend.xml").read_bytes(), source="backend")
summary = combine_reports([report])
assert summary["summary"]["tests"] == 3
```

`parse_report(bytes, source="report.xml")` retorna `source`, `summary` e `cases`. `combine_reports(lista_ou_tupla)` recebe relatórios dessa função e retorna `sources`, `summary` e `cases`, com cópias dos registros. Casos repetidos e a ordem são preservados. Entradas inválidas geram `ReportError`, derivado de `ValueError`.

Cada caso contém `name`, `class_name`, `suite` (lista de nomes das suítes), `status`, `duration_seconds` e `source`. Nome do caso é obrigatório; classe e nomes de suítes ausentes ficam vazios. Havendo marcadores conflitantes, a precedência é erro, falha, ignorado e aprovado. Cada caso conta uma vez.

Os campos inteiros do resumo são `tests`, `passed`, `failures`, `errors` e `skipped`; `duration_seconds` é uma string decimal exata. Tempo ausente vale zero. Os atributos de contagem e tempo das suítes são ignorados. A soma de tempos dos casos **não representa o tempo de parede** de testes paralelos. Não há deduplicação nem interpretação automática de tentativas repetidas.

O CLI retorna `0` por padrão, inclusive quando o relatório contém falhas. Com `--fail-on-problems`, retorna `1` para falhas ou erros; somente ignorados não causam falha. Entrada inválida retorna `2`, mensagem genérica em stderr e nenhuma saída parcial em stdout. `--help` retorna `0`.

## Compare resultados observados entre execuções

Com `--history`, cada arquivo explícito representa uma execução, na ordem informada. O ID da execução é o argumento do caminho exatamente como foi escrito, incluindo caminhos relativos. Sem `--history`, o CLI continua combinando os relatórios como antes.

```sh
python -m junit_report_summary --history examples/history/run-1.xml examples/history/run-2.xml examples/history/run-3.xml
python -m junit_report_summary --history examples/history/run-1.xml examples/history/run-2.xml examples/history/run-3.xml --format markdown
python -m junit_report_summary --history examples/history/run-1.xml examples/history/run-2.xml examples/history/run-3.xml --fail-on-problems
# Retorna 1: há falhas ou erros observados nestas execuções sintéticas.
```

Os três arquivos contêm 13 observações de cinco identidades distintas. O resumo do histórico é `{"tests": 5, "mixed": 1, "problem_only": 1, "pass_only": 2, "skipped_only": 1}`. `test_optional` está ausente na execução 2; `test_new`, na execução 1. Ausência não conta como falha nem como resultado ignorado.

```python
from pathlib import Path
from junit_report_summary import (
    analyze_history, format_history_markdown, parse_report,
)

runs = [
    {
        "id": f"run-{number}",
        "report": parse_report(
            Path(f"examples/history/run-{number}.xml").read_bytes(),
            source=f"local-report-{number}.xml",
        ),
    }
    for number in (1, 2, 3)
]
history = analyze_history(runs)
assert history["summary"] == {
    "tests": 5, "mixed": 1, "problem_only": 1,
    "pass_only": 2, "skipped_only": 1,
}
assert history["tests"][0]["identity"] == {
    "suite": ["service", "auth"], "class_name": "Auth",
    "name": "test_login[user]",
}
assert history["tests"][0]["counts"] == {
    "passed": 2, "failure": 1, "error": 0, "skipped": 0,
}
assert history["tests"][3]["missing_runs"] == ["run-2"]
assert history["tests"][4]["missing_runs"] == ["run-1"]
print(format_history_markdown(history))
```

`analyze_history(runs)` recebe lista ou tupla com 1 a 100 dicionários, cada um contendo exatamente `{"id": str, "report": resultado_de_parse_report}`. IDs devem ser únicos, não vazios, ter até 128 caracteres e não conter controles ASCII C0 (`U+0000` a `U+001F`) nem DEL (`U+007F`). Relatórios vazios são válidos. O total entre todas as execuções é limitado a `MAX_CASES` (100 mil) observações, contando identidades repetidas em execuções diferentes. Os registros e tempos são validados pelas regras existentes; os contadores fornecidos no resumo são informativos e recalculados. Entradas mutáveis são copiadas e preservadas.

A identidade é a tripla exata **`(tuple(suite), class_name, name)`**. A sequência de suítes, a classe e o nome completo importam; nomes parametrizados permanecem distintos. O rótulo `source` não faz parte da identidade. Identidade duplicada dentro da mesma execução é ambígua e gera `ReportError`: tentativas repetidas não são agregadas nem deduplicadas silenciosamente. O `combine_reports` original continua preservando casos duplicados.

O resultado contém exatamente `runs`, `summary` e `tests`. `runs` lista os IDs fornecidos. `summary.tests` conta identidades distintas; os outros quatro contadores indicam quantas identidades pertencem a cada classificação:

| Classificação | Resultados observados |
| --- | --- |
| `mixed` | Pelo menos uma aprovação e uma falha ou erro; também pode haver ignorados. |
| `problem_only` | Pelo menos uma falha ou erro, sem aprovações; também pode haver ignorados. |
| `pass_only` | Pelo menos uma aprovação, sem falhas nem erros; também pode haver ignorados. |
| `skipped_only` | Todos os resultados observados são ignorados. |

Cada item de `tests` contém exatamente `identity` (`suite`, `class_name`, `name`), `classification`, `counts` (`passed`, `failure`, `error`, `skipped`), `observations` (itens com `run` e `status`) e `missing_runs`. As contagens de cada teste medem observações; o resumo conta identidades distintas. As identidades seguem a ordem da primeira aparição; observações e IDs ausentes seguem a ordem explícita das execuções. O histórico não contém tempos, rótulos de origem ou diagnósticos.

O histórico é construído na memória. A quantidade de entradas de execuções ausentes pode crescer como o número de identidades distintas multiplicado pelo número de execuções fornecidas (até 100 mil por 100). A saída pode ser grande mesmo dentro desses limites, principalmente com identificadores longos. Os resultados são completos, sem truncamento.

A ordem informada não estabelece cronologia nem comprova que as execuções usaram o mesmo código ou ambiente. `mixed` descreve somente resultados observados diferentes: não conclui que o teste seja instável, que haja uma tentativa repetida esperada, que tenha ocorrido regressão, qual seria sua causa ou que a ausência represente falha.

`format_history_markdown(history)` gera tabelas determinísticas com escape de identificadores, classificações, contagens e execuções ausentes. No CLI, `--format`, JSON com escapes ASCII e regras de saída também se aplicam ao histórico. Todos os arquivos são lidos e validados antes de qualquer saída. Falha ou erro em qualquer execução causa retorno `1` somente com `--fail-on-problems`; ignorados sozinhos não causam falha. Argumentos de caminho duplicados e identidades ambíguas retornam `2`, mensagem genérica em stderr e nenhuma saída parcial. Não há descoberta por padrões.

Limites: UTF-8 com BOM opcional; raízes `testsuite`/`testsuites`, grupos aninhados e namespaces por nome local. Somente filhos `testcase` diretos de uma suíte reconhecida contam. Extensões desconhecidas são opacas. Documentos malformados, outras codificações e marcadores `<!DOCTYPE`/`<!ENTITY` são rejeitados, inclusive dentro de comentários. Não resolve entidades, arquivos ou URLs.

Cada relatório pode ter até 16 MiB, profundidade XML 32, 300 mil elementos e 100 mil casos; a combinação também limita os casos a 100 mil. A árvore XML fica na memória. Tempos aceitam decimal sem sinal e expoente opcional, até 512 caracteres, escala de -128 a 128 e até 128 dígitos inteiros; valores negativos, não finitos ou maiores são rejeitados. O suporte atende dialetos comuns de JUnit, sem alegar uma especificação universal.

Markdown escapa identificadores, HTML, separadores e sintaxe de links. JSON usa escapes ASCII. Caminhos e nomes de testes/suítes ainda podem revelar informações: revise antes de publicar. Remover diagnósticos não transforma a ferramenta em um removedor geral de segredos.

Execute os testes com `python -m unittest discover -s tests -v`. O CI verifica Python 3.10, 3.12 e 3.14 com permissões de leitura. Veja o [README em inglês](README.md) para o contrato completo.
