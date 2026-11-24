---
trigger: glob
globs: "**/*.py"
description: "Padrões Python do pack python: tipagem estrita, exceções explícitas, segurança e testes determinísticos."
---

# Diretrizes Python

Vale para todo arquivo `.py` do projeto. Os gates do pack `python` verificam boa parte destas
regras; o restante é responsabilidade de quem escreve e de quem revisa.

## Ambiente e dependências

- Gerencie o ambiente exclusivamente com `uv`; versione `pyproject.toml` e `uv.lock`.
- Toda dependência nova tem pin exato (`pacote==1.2.3`), é conhecida e mantida, e é citada para
  o humano antes de entrar. Nada de faixas (`>=`, `~=`) em dependências diretas.
- Ferramentas de qualidade (`ruff`, `pyright`, `pytest`, `pip-audit`) ficam no grupo de dev com
  pin exato. Scripts de infraestrutura e de harness preferem a biblioteca padrão.
- Use `pathlib.Path` para caminhos e `encoding="utf-8"` explícito ao ler ou gravar texto.

## Tipagem estrita

- O projeto roda `pyright` em modo `strict`; todo código novo passa sem erros nem avisos.
- Anote parâmetros e retornos de todas as funções e métodos, inclusive privados.
- Evite `Any`. Quando um valor vem de fora (JSON, TOML, payload), valide o formato e estreite o
  tipo com `isinstance` antes de usar; `cast` só depois da validação.
- `# type: ignore` e `# pyright: ignore` exigem o código da regra e o motivo na mesma linha.
- Prefira `dataclass(frozen=True, slots=True)`, `TypedDict`, `Protocol` e `Enum` a dicionários
  soltos e strings mágicas.
- Coleções abstratas nos parâmetros (`Sequence`, `Mapping`, `Iterable`) e tipos concretos nos
  retornos.

## Exceções explícitas

- Capture o tipo mais específico possível. Proibido `except:` vazio e `except Exception: pass`.
- Nunca engula um erro em silêncio: trate, registre com contexto ou propague.
- Ao traduzir uma exceção, preserve a causa com `raise NovoErro(...) from exc`.
- Defina exceções do domínio (subclasses de `ValueError`, `RuntimeError` etc.) em vez de
  levantar `Exception` genérica.
- Valide entradas na fronteira (CLI, HTTP, arquivos, variáveis de ambiente) e falhe cedo com
  mensagem acionável.

## Segurança

- Proibido `eval`, `exec` e `compile` sobre dados; interprete os dados explicitamente
  (`json`, `tomllib`, `ast.literal_eval` quando estritamente necessário).
- Proibido `pickle`, `marshal` e `shelve` para dados que cruzam uma fronteira de confiança. Para
  YAML, apenas `yaml.safe_load`.
- `subprocess` só com lista de argumentos (`argv`), `shell=False`, `check=False` com tratamento
  do código de saída, `capture_output=True`, `text=True` e `timeout` explícito.
- Toda chamada de rede tem `timeout` explícito. Proibido `verify=False` ou desligar a validação
  de certificados TLS.
- SQL sempre parametrizado; nunca monte consultas com f-string ou concatenação.
- Caminhos vindos de entrada externa: resolva com `Path.resolve()` e confirme com
  `relative_to()` que continuam dentro da pasta permitida.
- Segredos vêm do ambiente (`os.environ`) ou de um cofre; nunca no código, nos testes, nos logs
  ou em mensagens de erro. Cite um segredo pelo nome da variável, nunca pelo valor.
- Arquivos temporários com `tempfile`; nunca nomes previsíveis em pastas compartilhadas.
- **CSV Formula Injection:** neutralize células que comecem com `=`, `+`, `-`, `@`, `\t` ou `\r` ao exportar CSVs ou planilhas.
- Supressão do Bandit (`# nosec B603`) exige, na linha anterior, `# Bandit B603: <motivo>`.

## Testes

- Priorize o **Troféu de Testes (*Testing Trophy*)**: dê peso principal a testes de integração com fronteiras simuladas em vez de mocks excessivos de métodos privados; em PySpark, valide DataFrames com `assertDataFrameEqual(..., checkRowOrder=False)` e `StructType` explícito.
- Use `pytest`, com fixtures (`tmp_path`, `monkeypatch`, `capsys`) em vez de estado global.
- Testes unitários são determinísticos: sem relógio real (`datetime.now`, `time.time`), sem
  `time.sleep` e sem consultar processos reais (`psutil`). Injete relógio, agendador e sondador
  falsos. Exceção comprovada: `# determinism: allow` na própria linha.
- Testes não acessam a rede; injete o executor (`runner`) ou o cliente HTTP falso.
- Correção de bug começa por um teste de regressão que falha antes da correção.
- Nunca marque `skip`, afrouxe asserções ou apague testes para fazer um gate passar.

## Comentários e docstrings

- Comentário e docstring descrevem o código atual e o porquê dele, no presente.
- Sem datas, números de célula de notebook, molduras de caracteres repetidos, histórico de
  versões ou rótulos de patch (`FIX`, `NOVO`, `CORREÇÃO`). Histórico vai para o git, para o
  spec ou para um ADR em `docs/adr/`.
- Cite funções, constantes ou títulos de seção, nunca posições que mudam com a próxima edição.
- Falso positivo comprovado do analisador: `comments: allow` na própria linha.

## Gates do pack

| Gate | Comando | Verifica |
| :-- | :-- | :-- |
| `py-format` | `uv run ruff format --check .` | formatação |
| `py-lint` | `uv run ruff check .` | lint |
| `py-types` | `uv run pyright` | tipagem estrita |
| `py-tests` | `uv run pytest` | testes |
| `py-audit` | `python harness/packs/python/scripts/audit_deps.py` | vulnerabilidades em `uv.lock` |
| `py-determinism` | `python harness/packs/python/scripts/check_test_determinism.py` | determinismo dos testes |
| `py-comments` | `python harness/packs/python/scripts/verificar_comentarios.py` | comentários no presente |

Rode `python scripts/harness/verify.py --fast` entre tarefas e `python scripts/harness/verify.py`
antes de declarar a entrega concluída.
