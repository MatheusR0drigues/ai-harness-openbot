---
trigger: always_on
description: "Baseline de segurança de código para toda mudança: segredos via ambiente ou cofre, pinning exato de dependências, TLS com verify=True, proibição de eval, exec, pickle e shell=True, proteção de sessão, cookies e storage state, entrada externa validada e integridade do harness."
---

# Baseline de Segurança de Código

Regras de segurança específicas do projeto ficam em `.agents/rules/` do repositório e somam a esta baseline, nunca a substituem. Riscos de LLM e agentes estão em `ai-security.md`.

## 1. Segredos

- Segredos vêm de variáveis de ambiente (opcionalmente de um `.env` ignorado pelo git) ou de um cofre (secret manager do provedor de nuvem, Kubernetes Secret, vault). Em CI/CD, prefira OIDC / Workload Identity de curta duração em vez de PATs ou chaves estáticas. Documente as variáveis com valor vazio em `.env.example`.
- Nunca escreva segredo, token, senha, chave privada ou string de conexão com credencial em arquivo versionado, incluindo testes, fixtures, comentários, notebooks com saída e mensagens de commit.
- Nunca registre em log, imprima ou ecoe segredos ou cabeçalhos `Authorization`. Refira-se a um segredo pelo nome da variável.
- O agente não lê `.env`; lê `.env.example`.
- Se um segredo vazar para um arquivo, remova-o e avise o humano de que ele precisa ser rotacionado.
- O scanner de segredos roda como gate e como hook de pré-escrita. O marcador de exceção do scanner serve só para falso positivo comprovado, na linha exata, com justificativa no diff.

## 2. Sessões, Cookies BFF e Storage State

- Em aplicações web com autenticação OAuth/OIDC, adote padrão **BFF (Backend-for-Frontend)** mantendo tokens no servidor e expondo apenas cookie `__Host-` com `HttpOnly; Secure; SameSite=Lax` e proteção CSRF; proibido guardar tokens JWT ou de sessão em `localStorage` ou `sessionStorage`.
- Estado de sessão de navegador (`storage_state.json`, dumps de cookies, perfis de navegador automatizado), tokens de sessão e cookies de autenticação são credenciais: ficam fora do git (`.gitignore`), nunca são versionados, colados no chat ou usados como fixture.
- Gere estado de sessão fora do repositório ou em diretório temporário, com permissão restrita ao usuário, e apague ao terminar.
- Fixtures de teste usam cookies e sessões sintéticos, montados em tempo de execução.

## 3. Dependências

- Versões exatas: `==` em Python e versão exata (sem `^` ou `~`) em Node, com lockfile versionado.
- Apenas pacotes conhecidos e mantidos. Sinalize possível typosquat (grafia incomum de pacote popular) antes de instalar.
- Prefira a biblioteca padrão quando ela resolver em poucas linhas.
- Toda nova dependência é mencionada ao humano; a auditoria de vulnerabilidades roda como gate quando o pack da stack estiver ativo.

## 4. Entrada Externa

- Todo valor externo (usuário, arquivo, rede, HTML coletado, saída de LLM) é validado na fronteira.
- SQL só com parâmetros vinculados; f-string ou concatenação com valor externo é bloqueante.
- Caminho de arquivo derivado de entrada externa é normalizado e restrito ao diretório esperado.
- **CSV / Excel Formula Injection:** ao exportar planilhas ou CSVs com dados externos, neutralize valores iniciados por `=`, `+`, `-`, `@`, `\t` ou `\r`.

## 5. Execução de Código e Desserialização

- Proibido `eval` e `exec`, inclusive formas equivalentes de execução dinâmica de texto (`compile` seguido de execução, `new Function` em JavaScript).
- Proibido desserializar com `pickle` (e `marshal` ou `shelve`); use JSON ou formato com esquema. YAML só com `yaml.safe_load`.
- Proibido `shell=True`; passe listas de argumentos (`argv`) a subprocessos, sempre com timeout.

## 6. Rede e TLS

- TLS sempre com verificação de certificado: `verify=True` (padrão de `requests` e `httpx`). Nunca `verify=False`, contexto SSL sem verificação ou variável de ambiente que desliga a checagem de certificado (como `NODE_TLS_REJECT_UNAUTHORIZED=0`).
- Certificado corporativo ou autoassinado: aponte o bundle de CA confiável em vez de desligar a verificação.
- Timeout em toda chamada de rede. Host novo é declarado no design da mudança.

## 7. Erros, Logs e Quarentena de Dados

- Erro mostrado ao usuário não vaza stack trace, SQL, host, credenciais ou nome de esquema.
- Dado pessoal não vai para log sem regra explícita do projeto.
- Tabelas de quarentena e *Dead Letter Queues* (DLQ) de pipelines herdam as ACLs, mascaramento e retenção curta da camada de origem, pois podem conter payloads com PII.

## 8. O Próprio Harness

- Gate desativado, hook removido, guarda afrouxada ou permissão ampliada sem ADR é achado de segurança, não de estilo.
- Com o kit local, o gate `check_controls.py` falha até a baseline ser restaurada ou a remoção ser justificada em ADR.
