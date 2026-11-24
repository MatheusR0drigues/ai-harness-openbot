---
name: auth-bff-oauth
description: "Padrão Backend-for-Frontend (BFF) com OAuth 2.1 + PKCE, cookies __Host- HttpOnly Secure SameSite=Lax, proteção CSRF, rotação de refresh token e proibição de JWT em localStorage."
---

# Autenticação Web Segura: BFF, OAuth 2.1 e Cookies `__Host-`

Padrão de arquitetura para aplicações Web/SPA modernas evitando exposição de tokens de acesso ou refresh ao JavaScript do navegador (proteção contra XSS e roubo de sessão).

## Arquitetura Recomendada: Backend-for-Frontend (BFF)

- **Nunca armazene tokens JWT, `access_token` ou `refresh_token` no `localStorage` ou `sessionStorage`:** qualquer script ou biblioteca vulnerável a XSS consegue ler e exfiltrar tokens guardados na camada de navegador.
- **Fluxo OAuth 2.1 + PKCE no BFF:**
  1. O navegador autentica exclusivamente por meio do servidor **BFF** (backend confidencial do mesmo domínio/site), que conduz **Authorization Code Flow com PKCE (`S256`)** e `state` + `nonce` validados contra o provedor OIDC.
  2. O BFF troca o código pelos tokens no backend e mantém tokens OAuth no servidor (ou em store cifrado de sessão no servidor), emitindo apenas um identificador opaco de sessão para o navegador.

## Contrato Estrito de Cookies de Sessão

Todo cookie de sessão emitido pelo BFF deve adotar:

- Prefixo **`__Host-`** (ex.: `__Host-session`), que impõe navegador-side:
  - `Secure` (exige HTTPS),
  - `Path=/`,
  - **ausência de atributo `Domain`** (impede compartilhamento indevido com subdomínios).
- **`HttpOnly`** obrigatório (inacessível a `document.cookie`).
- **`SameSite=Lax`** (ou `Strict` quando não houver redirecionamento de entrada OIDC na mesma requisição).

## Proteção CSRF, Rotação e Encerramento

- Rotas de mutação (`POST`, `PUT`, `PATCH`, `DELETE`) autenticadas por cookie exigem proteção contra CSRF: validação estrita de `Origin`/`Referer`, cabeçalhos customizados ou token anti-CSRF sincronizado por sessão, além de bloqueio CORS sem curinga (`*`) com `credentials: true`.
- Realize **rotação automática de `refresh_token`** no BFF com detecção de reuso (revogando a família de sessão em caso de replay).
- No logout, invalide a sessão no store do BFF, revogue o token no provedor quando suportado e expire o cookie com `Max-Age=0`.
