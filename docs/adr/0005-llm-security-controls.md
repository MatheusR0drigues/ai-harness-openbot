# ADR-0005: Controlos de segurança LLM e agêntica no harness

- Date: 2026-10-02
- Status: Accepted

## Contexto

`docs/Vulnerabilidades Web e Redes Pós-LLM.md` descreve classes de vulnerabilidade que o harness
não cobria: injeção de prompt indireta (LLM01), exfiltração zero-click do tipo EchoLeak
(CVE-2025-32711, LLM02/LLM08), tratamento inseguro de saídas (LLM10), excesso de agência e abuso
de ferramentas (ASI01/ASI02/ASI03/ASI05), superfície MCP (MCP03/MCP09), e vulnerabilidades
clássicas injetadas em código gerado por modelos.

Os controlos existentes (`check_secrets.py`, `check_structure.py`, `validate_spec.py`,
`sync_adapters.py`, e os guards `secret_in_write`, `sensitive_file`, `generated_file`,
`dangerous_shell`) cobrem segredos, estrutura e comandos destrutivos, mas nada no harness olhava
para conteúdo não confiável, para egress de dados, para a superfície de privilégio do agente, ou
para o enfraquecimento dos próprios controlos.

Restrições relevantes, verificadas no código antes desta decisão:

- `payload.py` normaliza chamadas de ferramenta (`write`, `read`, `shell`, `search`) mas não
  recebe o resultado da ferramenta, logo não existe hoje um ponto onde inspecionar o conteúdo que
  o agente acabou de ler.
- `config.py` tem schema fechado: qualquer secção nova em `harness.toml` exige alteração do
  validador e dos seus testes.
- O repositório é um template genérico: `product.md` e `tech.md` continuam TBD, e nenhum gate
  pode assumir uma stack.

## Decisão

1. **Egress é um tripwire, não uma fronteira.** O guard `data_egress` bloqueia comandos que
   enviam conteúdo local para fora (upload de ficheiro, pipe para cliente de rede, cmdlets
   PowerShell com corpo ou ficheiro de entrada, `scp`/`rsync` remoto, `nc`). O guard `exfil_url`
   bloqueia URLs e imagens remotas que transportam um bloco codificado longo, que é o vetor
   zero-click do EchoLeak. Ambos assumem a mesma limitação já documentada em `guards.py`: um
   comando ofuscado ou gerado em runtime passa.
2. **Injeção indireta é verificada como gate sobre os ficheiros do repositório.** O sensor
   `check_untrusted.py` corre em `verify` e aponta caracteres invisíveis, frases de override,
   diretivas escondidas e blobs codificados nos ficheiros versionados, com marcador
   `untrusted: allow` e caminhos exemptos declarados em `harness.toml`.
3. **O sensor de risco em código é config-driven e inerte por omissão.** `check_code_risks.py` só
   varre os globs declarados em `[code_risks] include`; sem configuração imprime um aviso e sai
   com 0, no mesmo registo do aviso de stack gates.

Decisão complementar, pela mesma lógica: o sensor `check_controls.py` passa a verificar a
baseline de gates e guards declarada em `[controls]`, transformando a regra "um gate desativado
sem ADR é um achado de segurança" num controlo executável.

## Alternativas rejeitadas

- **Allowlist de hosts para todo o egress** (`[network] allowed_hosts`). Fronteira mais forte, mas
  num template sem stack a lista nasce vazia e quebra `uv sync`, `pip install` e `git clone`. O
  agente aprenderia a pedir exceção para tudo e o controlo perderia significado. Pode ser
  adotada por um projeto derivado que conheça os seus destinos de rede.
- **`check_code_risks` ativo por omissão em todo o repositório.** Gera falsos positivos no próprio
  harness (por exemplo, `eval` aparece como string na lista de launchers de `guards.py`) e cria
  atrito num repositório que ainda não escolheu linguagem.
- **Guard de leitura que bloqueia ficheiros com marcadores de injeção.** O agente precisa de ler
  o ficheiro para o corrigir; bloquear a leitura impede a remediação.
- **`exfil_url` apenas a avisar.** O vetor é zero-click: o aviso não impede o render que exfiltra.

## Adiado

**Inspecionar o resultado da ferramenta (`tool_response`) no hook `post`**, para detetar injeção
no conteúdo efetivamente lido ou obtido da rede. Exige estender `payload.py` a um campo cujo
formato está documentado para Claude, Codex e Kiro, mas não foi medido no Antigravity. Requer
medição com `tools/` antes de ser implementado, e um ADR próprio.

## Consequências

- Mais fácil: um agente desviado por conteúdo envenenado encontra um bloqueio determinístico
  antes de exfiltrar dados ou alargar privilégios; a remoção de um controlo passa a falhar um
  gate em vez de passar em silêncio.
- Mais difícil: sete guards em vez de quatro aumentam a chance de um falso positivo numa tarefa
  legítima de rede; a saída de cada bloqueio indica a alternativa e, quando aplicável, remete a
  ação ao humano.
- `harness.toml` ganha três secções (`[untrusted]`, `[code_risks]`, `[controls]`) e
  `verify` ganha três gates `core`. Um projeto derivado especializa-os por dados, sem tocar em
  Python.
- O documento de pesquisa importado fica exempto do sensor de conteúdo não confiável, porque cita
  literalmente cargas de ataque. A exceção é declarada em `harness.toml`, visível no diff.
