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

Limites: UTF-8 com BOM opcional; raízes `testsuite`/`testsuites`, grupos aninhados e namespaces por nome local. Somente filhos `testcase` diretos de uma suíte reconhecida contam. Extensões desconhecidas são opacas. Documentos malformados, outras codificações e marcadores `<!DOCTYPE`/`<!ENTITY` são rejeitados, inclusive dentro de comentários. Não resolve entidades, arquivos ou URLs.

Cada relatório pode ter até 16 MiB, profundidade XML 32, 300 mil elementos e 100 mil casos; a combinação também limita os casos a 100 mil. A árvore XML fica na memória. Tempos aceitam decimal sem sinal e expoente opcional, até 512 caracteres, escala de -128 a 128 e até 128 dígitos inteiros; valores negativos, não finitos ou maiores são rejeitados. O suporte atende dialetos comuns de JUnit, sem alegar uma especificação universal.

Markdown escapa identificadores, HTML, separadores e sintaxe de links. JSON usa escapes ASCII. Caminhos e nomes de testes/suítes ainda podem revelar informações: revise antes de publicar. Remover diagnósticos não transforma a ferramenta em um removedor geral de segredos.

Execute os testes com `python -m unittest discover -s tests -v`. O CI verifica Python 3.10, 3.12 e 3.14 com permissões de leitura. Veja o [README em inglês](README.md) para o contrato completo.
