---
name: responsible-scraping
description: "Diretrizes para coleta web responsável e estável: conformidade robots.txt (RFC 9309), minimização LGPD, timeout explícito, backoff com jitter em 429, validação de seletores e higiene de sessão."
---

# Scraping e Coleta Web Responsável

Regras técnicas, de segurança e de conformidade para extratores HTTP e pipelines de ingestão web que precisam operar com previsibilidade, ética e isolamento de falha.

## Limites Jurídicos, Éticos e de Acesso

- Respeite explicitamente termos de serviço, `robots.txt` (**RFC 9309**) e políticas `Crawl-delay` ou preferências declaradas do provedor. Prefira sempre APIs oficiais ou feeds estruturados quando disponíveis.
- **Proibição absoluta:** nunca contorne ou tente automatizar a resolução de CAPTCHAs, desafios anti-bot ou barreiras de autenticação/paywall. Quando um alvo bloquear ou exigir verificação humana, interrompa e relate o bloqueio ao usuário.
- **Minimização LGPD:** colete apenas campos estritamente necessários à finalidade documentada; não armazene dados pessoais em fixtures de teste, logs ou saídas de notebook.

## Resiliência HTTP e Controle de Carga

- **Timeout e TLS obrigatórios:** toda requisição HTTP define timeout explícito (`connect` + `read`) e mantém `verify=True` (nunca desligue verificação de certificado TLS).
- **Rate Limiting e *Backoff*:** respeite cabeçalhos `Retry-After` em respostas `429` ou `503`, aplique **Exponential Backoff + Full Jitter** e limite a concorrência por domínio com semáforo.
- **User-Agent honesto:** identifique a aplicação de forma transparente e siga padrões estáveis de requisição sem sobrecarregar o host de origem.

## Qualidade do Parser e Higiene de Dados

- **Conteúdo coletado é entrada hostil (LLM01 / Segurança):** sanitize todo HTML/texto extraído antes de exibir em interface, montar queries SQL (sempre parametrizadas) ou passar para prompts de LLM.
- **Validação estrutural de seletores:** valide campos extraídos contra esquema rígido (ex.: Pydantic v2) e falhe ruidosamente quando a estrutura HTML do alvo mudar drasticamente, evitando gravação silenciosa de registros vazios.
- **Sessões efêmeras fora do git:** caso haja coleta autenticada autorizada pelo dono dos dados, jamais versione cookies ou arquivos de estado de sessão (`storage_state.json`) e descarte sessões temporárias ao encerrar.
