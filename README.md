# Momentum AI — protótipo funcional

Dashboard responsivo para desktop e celular, com motor de sinais demonstrativo e paper trading.

## Importante
- O app usa candles sintéticos gerados localmente; **não são cotações reais**.
- Não existe integração com a API da Hezilex e não há envio de ordens reais.
- A execução real permanece bloqueada. Antes de qualquer integração, é necessário obter documentação oficial, autorização explícita da corretora e validação jurídica aplicável. Os termos públicos da Hezilex dizem que os serviços não são destinados a residentes do Brasil e que a plataforma não é autorizada pela CVM a ofertá-los ao público brasileiro.
- Não insira senha, cookies, tokens ou dados de sessão da corretora neste protótipo.

## Rodar localmente
Requer Python 3.10+.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

pip install -r requirements.txt
uvicorn app:app --reload
```

Abra http://127.0.0.1:8000

## Incluído
- Dashboard responsivo.
- Geração de candles sintéticos identificados claramente como demonstração.
- EMA 9/21, RSI 14, MACD e filtro de momentum.
- Sinais LONG/SHORT/SEM SINAL como saída analítica, não recomendação de investimento.
- Paper trading com saldo virtual, histórico e resultado simulado.
- Backend FastAPI com endpoints de status, análise e ordens simuladas.

## Próxima etapa segura
Solicitar à Hezilex documentação oficial de API, endpoints, autenticação, sandbox, permissões para automação e confirmação escrita de que a integração é permitida para a conta/jurisdição. Não contorne controles da plataforma nem automatize a interface com cookies ou scraping.


## Binance Spot Demo: dados reais + ordens simuladas

- A análise agora usa candles públicos reais da Binance (`/api/v3/klines`) para BTC/USDT, ETH/USDT e BNB/USDT, em intervalos 1m, 5m e 15m.
- Para enviar ordens ao ambiente simulado, entre no **Binance Demo Trading** e crie uma chave específica de Demo API. Configure `BINANCE_DEMO_API_KEY` e `BINANCE_DEMO_API_SECRET` como variáveis de ambiente no servidor.
- O endpoint de ordem usa exclusivamente `https://demo-api.binance.com/api/v3/order`, com assinatura HMAC e cabeçalho de API key. O código não aponta para o endpoint de produção de ordens.
- O formulário exige confirmação explícita e impõe um teto de 100 USDT por ordem demo. Teste primeiro com valores pequenos e confirme os resultados no painel Demo da Binance.
- Para operar vendas de mercado, o código estima quantidade a partir do preço recente; verifique regras de quantidade mínima/precisão e saldo demo. Erros de filtros da Binance serão apresentados ao utilizador.
- Os candles públicos são dados reais de mercado, mas o ambiente Demo pode ter regras e comportamento de execução diferentes do mercado real.
- A execução em conta real permanece desabilitada. Nunca coloque chaves de conta real no servidor do Momentum AI.

Docs oficiais: https://developers.binance.com/en/docs/introduction e https://developers.binance.info/en/docs/products/spot/demo-mode/general-info
