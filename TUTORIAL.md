## Tutorial de Configuracao e Execucao

Este guia mostra exatamente o que voce precisa baixar e configurar para rodar o projeto localmente.

## 1. O que instalar

Instale os itens abaixo no Windows:

1. Python 3.11+ (recomendado 3.11 ou 3.12)
2. Google Chrome (navegador usado pelo Selenium)
3. Git (opcional, se voce ainda nao clonou o repositorio)

Observacao:
- O Selenium 4.29 consegue gerenciar o ChromeDriver automaticamente na maioria dos casos.
- Se houver bloqueio de rede/empresa, configure manualmente `CHROMEDRIVER_PATH` no `.env`.

## 2. Abrir o projeto

No PowerShell:

```powershell
cd C:\Users\felip\Documents\GitHub\Desafios-Entrevistas
```

## 3. Criar e ativar ambiente virtual

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Se o PowerShell bloquear scripts, rode uma vez:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## 4. Instalar dependencias

```powershell
pip install -r requirements.txt
```

## 5. Configurar variaveis de ambiente

Copie o arquivo de exemplo:

```powershell
Copy-Item .env.example .env
```

No arquivo `.env`, o unico campo obrigatorio para iniciar o bot e:

```env
PORTAL_TRANSPARENCIA_URL=https://portaldatransparencia.gov.br/pessoa-fisica/busca/lista?pagina=1&tamanhoPagina=10&beneficiarioProgramaSocial=true
```

Configuracoes recomendadas para primeira execucao:

```env
SELENIUM_HEADLESS=false
PORTAL_MAX_RESULTS=1
INTEGRATIONS_ENABLED=false
SKIP_DRIVE_UPLOAD=false
SKIP_EMAIL_NOTIFICATION=false
```

Explicacao rapida:
- `SELENIUM_HEADLESS=false`: abre o Chrome visivelmente para facilitar debug.
- `PORTAL_MAX_RESULTS=1`: processa apenas 1 resultado para testar mais rapido.
- `INTEGRATIONS_ENABLED=false`: desliga Google Drive/Sheets e e-mail para acelerar testes locais.
- `SKIP_DRIVE_UPLOAD=false`: quando false (padrao), faz upload para Drive. Use `true` para pular.
- `SKIP_EMAIL_NOTIFICATION=false`: quando false (padrao), envia e-mail. Use `true` para pular.

## 6. Rodar a API (forma mais pratica)

Com o ambiente virtual ativo:

```powershell
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

Abra no navegador:

```text
http://127.0.0.1:8000/docs
```

## 7. Testar uma execucao

Em outro terminal PowerShell (com o `venv` ativo):

```powershell
curl -X POST "http://127.0.0.1:8000/executions" ^
  -H "Content-Type: application/json" ^
  -d "{\"termo\":\"maria\",\"filtros\":[\"beneficiarioProgramaSocial\"],\"include_base64\":false}"
```

Os artefatos serao salvos em `artifacts/`.

## 8. Rodar via CLI (alternativa)

Tambem e possivel executar sem API:

```powershell
python app\main.py "maria" --param beneficiarioProgramaSocial --output artifacts --max-results 1
```

## 9. Configuracoes opcionais

### Google Drive e Google Sheets

Para habilitar upload no Drive e atualizacao de planilha, configure no `.env` pelo menos uma forma de credencial Google:

- OAuth:
  - `GOOGLE_OAUTH_CLIENT_SECRET_FILE` ou `GOOGLE_OAUTH_CLIENT_SECRET_JSON`
- Service Account:
  - `GOOGLE_SERVICE_ACCOUNT_FILE` ou `GOOGLE_SERVICE_ACCOUNT_JSON`

Campos de destino (opcionais):
- `GOOGLE_DRIVE_FOLDER_ID`
- `GOOGLE_SHEET_ID`
- `GOOGLE_SHEET_TITLE`
- `GOOGLE_SHEET_TAB_NAME`

Na primeira execucao com OAuth, uma autenticacao no navegador sera solicitada e o token sera salvo em `GOOGLE_OAUTH_TOKEN_FILE` (padrao: `.google-oauth-token.json`).

### Notificacao por e-mail

Para envio de e-mail ao final da automacao, preencha:

```env
NOTIFICATION_EMAIL_TO=
NOTIFICATION_EMAIL_FROM=
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
```

## 10. Problemas comuns

1. Erro `PORTAL_TRANSPARENCIA_URL is required`
	- Verifique se o arquivo `.env` existe na raiz e se a variavel foi preenchida.

2. Chrome/Driver nao inicia
	- Atualize o Google Chrome.
	- Se ambiente corporativo bloquear download automatico, baixe um ChromeDriver compativel e informe `CHROMEDRIVER_PATH`.

3. Timeout na busca
	- Defina `SELENIUM_HEADLESS=false` para observar o fluxo.
	- Aumente `SELENIUM_PAGE_LOAD_TIMEOUT`.

4. Integracoes Google nao funcionam
	- Confira credenciais no `.env`.
	- Verifique permissoes da API Google Drive/Sheets no projeto GCP.

## 11. Performance e Benchmarks

### Tempo de execucao tipico

Em testes reais com **22 resultados**:

```
Scraping paralelo:        35.0s  ← coleta de dados em paralelo (10 workers)
JSON save:                 0.0s
Google Drive upload:      73.7s  ← gargalo (upload sequencial de 22 pastas)
Google Sheets sync:        1.7s
Email SMTP:               33.6s  ← segunda demora (latencia de rede/SMTP)
TOTAL:                   143.9s  (~2.4 minutos)
```

### Como acelerar para testes locais

Se voce quer velocidade maxima durante desenvolvimento, desabilite as integrações lentas no `.env`:

```env
SKIP_DRIVE_UPLOAD=true
SKIP_EMAIL_NOTIFICATION=true
```

Com isso, a execução cai para **~40 segundos** (apenas scraping).

### Como testar modo rapido com INTEGRATIONS_ENABLED=false

Se nao quer nem carregar credenciais Google:

```env
INTEGRATIONS_ENABLED=false
SKIP_DRIVE_UPLOAD=true
SKIP_EMAIL_NOTIFICATION=true
```

Resultado: ~40s para coleta de dados, sem tentar conectar ao Google/SMTP.
