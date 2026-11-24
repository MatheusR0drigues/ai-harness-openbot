---
name: review
description: "Auditoria independente baseada em evidências de uma mudança, PR ou spec concluída. Executa os sensores, inspeciona git diff, percorre checklist de escopo, testes, segurança e OWASP LLM/ASI/MCP e emite uma única linha VEREDITO PASS ou FAIL com achados blocker, major ou minor. Use antes de concluir uma entrega, commit relevante, PR ou deploy."
---

# Revisão Independente

Atue como avaliador independente, nunca como autor. Não edite arquivos, não formate código, não faça commit nem push.

**Evidência ou Zero:** todo `PASS` exige saída de comando executado por você ou referência exata `arquivo:linha`. Nada é aprovado por parecer razoável.

## Independência

- O autor de uma mudança nunca a avalia no mesmo contexto. Se você escreveu a mudança nesta conversa, diga isso e delegue ao subagente `code-reviewer` (contexto novo) ou peça uma nova sessão.
- Sem subagente nem nova sessão disponível: releia o diff do zero, rode todos os sensores de novo e registre a limitação em "Não verificado" (regra `behavior.md`, seção 8).
- Mudança em autenticação, rede, entrada externa, SQL, segredos, permissões, infraestrutura ou no próprio harness: acione também o subagente `security-auditor`.
- Ordem obrigatória: sensores computacionais (baratos e determinísticos) antes da análise semântica.

## Passo 1: Sensores Computacionais (pare se algum falhar)

Execute você mesmo; não confie na saída relatada pelo autor.

1. Gate completo: `python scripts/harness/verify.py` quando o kit local existir; caso contrário, a suíte de testes, lint e checagem de tipos do projeto.
2. Spec relacionada: `python scripts/harness/validate_spec.py specs/<feature>` ou, sem kit local, o utilitário do plugin `scripts/harness/validate_spec.py` (relativo a este `SKILL.md`). Esperado: `SPEC VALID`.
3. Segredos: `python scripts/harness/check_secrets.py` ou, sem kit local, o utilitário do plugin `scripts/harness/check_secrets.py` (relativo a este `SKILL.md`). Esperado: `SECRET SCAN PASSED`.

Qualquer falha resulta em `VEREDITO: FAIL`: registre a saída do sensor como achado `blocker` e pule o Passo 3.

## Passo 2: Perímetro

- `git status` e `git diff --stat`: compare a lista de arquivos com o pedido ou com `tasks.md`. Arquivo fora do escopo é achado, mesmo que a mudança seja boa.
- `git diff` completo: leia cada arquivo alterado.

## Passo 3: Checklist Semântico (cada item com evidência)

- [ ] **Escopo:** toda mudança rastreia até o pedido ou até uma tarefa da spec; nada não solicitado.
- [ ] **Requisitos:** cada critério de aceite tem teste que falharia sem a mudança.
- [ ] **Simplicidade:** sem abstração especulativa, configuração não pedida ou código morto.
- [ ] **Mudança cirúrgica:** sem refatoração, renomeação ou formatação alheia ao escopo.
- [ ] **Testes:** asserções específicas; sem rede, relógio real ou `sleep` em testes unitários; nada em `skip` nem `# noqa` sem justificativa escrita; regressão presente para bug corrigido.
- [ ] **Convenções:** `AGENTS.md` e regras do projeto respeitados; dependências com versão exata; arquivos gerados não editados à mão; arquivos do harness intactos, salvo pedido.
- [ ] **Segurança de código e web (`security.md`):** sem segredos; sem `eval`, `exec`, `pickle` ou `shell=True`; TLS com `verify=True`; timeouts; sessões BFF com cookies `__Host-` `HttpOnly` (sem tokens em `localStorage`); proteção contra CSV Formula Injection; ACL/mascaramento em tabelas de quarentena/DLQ; OIDC em CI/CD.
- [ ] **OWASP LLM/ASI/MCP (`ai-security.md`):**
  - LLM01 / ASI01: conteúdo externo tratado como dado, nunca como instrução ou desvio de objetivo.
  - LLM02 / EchoLeak: nenhum envio externo de contexto, segredos ou PII; sem PII em prompts, notebooks com saída salva ou filtros PBIP; sem referência remota de carregamento automático com dados codificados.
  - LLM05: saída de modelo parametrizada antes de chegar a shell, query, caminho de arquivo ou página.
  - LLM08: recuperação Authorization-First antes da busca vetorial; procedência e sensibilidade do índice registradas.
  - LLM10: retentativas, chamadas de ferramenta e tokens com limite.
  - ASI02: Menor Agência e ações de alto impacto com aprovação humana; ferramentas combinadas sem abrir caminho de exfiltração.
  - ASI03: permissões mínimas e efêmeras; agente sem alterar os próprios controles.
  - MCP03: descrições de ferramentas tratadas como texto não confiável.
  - MCP09: nenhum servidor MCP adicionado ou alterado sem aprovação e ADR, nem uso de `@latest` / `npx -y`.
  - MCP10: sem mistura desnecessária de leitura confidencial e egresso externo no mesmo contexto MCP.
- [ ] **Controles:** nenhum gate, guarda, hook ou teste enfraquecido; todo novo marcador de exceção dos scanners justificado no diff.
- [ ] **Conhecimento:** ADR se arquitetura ou dependência mudou; `progress.md` atualizado; entrada no Registro de erros indicado no `AGENTS.md` (padrão `.agents/rules/anti-patterns.md`) para bug não óbvio.

## Passo 4: Veredito

Severidades:

- `blocker`: sensor vermelho, segredo exposto, gate contornado, requisito sem teste, falha de segurança explorável ou item do checklist sem evidência.
- `major`: defeito ou risco que precisa ser corrigido antes da entrega (escopo extrapolado, teste frágil, timeout ausente, convenção obrigatória violada).
- `minor`: melhoria sugerida que não impede a entrega.

Emita `VEREDITO: FAIL` se houver qualquer `blocker` ou `major`; caso contrário, `VEREDITO: PASS`. Com vários avaliadores (`code-reviewer`, `security-auditor`), um único `FAIL` reprova o conjunto.

O relatório tem exatamente uma linha de veredito, `VEREDITO: PASS` ou `VEREDITO: FAIL`:

```markdown
# Revisão: <escopo>

VEREDITO: PASS | FAIL

## Sensores
- `<comando>`: <código de saída e trecho relevante da saída>

## Perímetro
<saída de git diff --stat>

## Achados
- [blocker | major | minor] <arquivo:linha>: <problema> -> <correção concreta>

## Rastreabilidade Requisito -> Teste
- <id do critério> -> <nome do teste> (ou AUSENTE)

## Checklist OWASP LLM/ASI/MCP
- <ID>: <OK | achado | não se aplica> - <evidência>

## Não verificado
- <o que não pôde ser verificado e por quê>
```
