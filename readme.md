# Monitor de Logs ATI

Automação que monitora uma caixa de email via IMAP e dispara alertas quando
o mesmo erro de um mesmo conjunto aparece mais de uma vez dentro de uma janela
de tempo configurável.

---

## 📁 Estrutura dos Arquivos

```
email_monitor/
├── config.py           ← ⚙️  EDITE AQUI as credenciais e configurações
├── main.py             ← Ponto de entrada da automação
├── imap_reader.py      ← Leitura de emails via IMAP
├── parser.py           ← Extração de conjunto/erro dos emails
├── tracker.py          ← Rastreamento de ocorrências e duplicatas
├── alerter.py          ← Envio de alertas por SMTP
├── build.py            ← Script para gerar o .exe
├── requirements.txt    ← Dependências Python
└── README.md           ← Este arquivo
```

---

## ⚙️ Configuração (config.py)

Edite o arquivo `config.py` antes de gerar ou rodar o executável:

| Seção | O que configurar |
|---|---|
| `IMAP_*` | Credenciais e servidor de leitura de email |
| `SMTP_*` | Credenciais e servidor de envio de alertas |
| `EMAIL_RECIPIENTS` | Lista de emails que receberão os alertas |
| `POLLING_INTERVAL_MINUTES` | Frequência de verificação (em minutos) |
| `DEDUP_WINDOW_HOURS` | Janela de tempo para considerar logs iguais |
| `MIN_OCCURRENCES_TO_ALERT` | Quantas ocorrências disparam o alerta (padrão: 2) |
| `LOG_SUBJECT_KEYWORDS` | Palavras-chave para filtrar emails de log |
| `REGEX_CONJUNTO` | Regex para extrair o nome do conjunto |
| `REGEX_ERRO` | Regex para extrair o tipo de erro |

---

## 🚀 Como Gerar o Executável (.exe)

### Pré-requisitos
- Python 3.8 ou superior instalado na máquina de build
- Acesso à internet para instalar o PyInstaller

### Passos

```bash
# 1. Clone ou copie os arquivos para uma pasta
cd email_monitor

# 2. Instale dependências
pip install -r requirements.txt

# 3. Edite as configurações
notepad config.py    # Windows
nano config.py       # Linux

# 4. Gere o executável
python build.py
```

O executável será gerado em `dist/monitor_logs_ati.exe`.

---

## 🖥️ Deploy no Servidor

1. Copie os dois arquivos para o servidor:
   ```
   monitor_logs_ati.exe
   config.py
   ```
   > ⚠️ O `config.py` **deve ficar na mesma pasta** que o `.exe`

2. Execute o monitor:
   ```
   monitor_logs_ati.exe
   ```

3. Para rodar em segundo plano (Windows):
   ```
   start /B monitor_logs_ati.exe > nul 2>&1
   ```
   Ou configure como **Serviço do Windows** com NSSM:
   ```
   nssm install MonitorLogsATI "C:\caminho\monitor_logs_ati.exe"
   nssm start MonitorLogsATI
   ```

---

## 🔍 Como Funciona

```
[Caixa de Email IMAP]
        ↓ (a cada X minutos)
[Busca emails não lidos]
        ↓
[Extrai: Conjunto + Tipo de Erro]
        ↓
[Registra ocorrência no rastreador]
        ↓
[Mesmo Conjunto + Mesmo Erro apareceu >= 2x?]
        ↓ SIM
[Envia email de alerta para os destinatários]
        ↓
[Marca email como lido]
```

### Detecção de Duplicatas
- A automação mantém um arquivo `occurrences_state.json` com o histórico
- Se a mesma combinação `(conjunto, erro)` aparecer `MIN_OCCURRENCES_TO_ALERT`
  vezes dentro de `DEDUP_WINDOW_HOURS` horas, um alerta é disparado
- O alerta é enviado **uma vez** por janela — não fica re-enviando
- Quando a janela expira, o contador é resetado

### Extração de Dados dos Emails
A automação tenta extrair automaticamente o nome do conjunto e o tipo de erro
usando padrões comuns como:
- `Conjunto: NOME_DO_CONJUNTO`
- `Erro: mensagem de erro`
- `[NOME_EM_CAPS]`
- `ERROR: mensagem`

Para formatos específicos dos seus logs, configure `REGEX_CONJUNTO` e
`REGEX_ERRO` em `config.py`.

---

## 📋 Arquivos Gerados em Tempo de Execução

| Arquivo | Descrição |
|---|---|
| `monitor.log` | Log de execução da automação |
| `occurrences_state.json` | Estado persistido entre reinicializações |

---

## ❓ Dúvidas Comuns

**Q: A autenticação IMAP falha.**
A: Verifique se `IMAP_HOST`, `IMAP_USERNAME` e `IMAP_PASSWORD` estão corretos.
Confirme a porta (993 para SSL, 143 sem SSL).

**Q: O email de alerta não chega.**
A: Verifique as configurações SMTP. Tente a porta 587 com TLS ou 465 com SSL.
Cheque se o servidor permite autenticação SMTP.

**Q: O monitor não identifica o conjunto/erro corretamente.**
A: Configure `REGEX_CONJUNTO` e `REGEX_ERRO` em `config.py` com expressões
regulares que correspondam ao formato dos seus emails de log.

**Q: Quero resetar o histórico de alertas.**
A: Delete o arquivo `occurrences_state.json` e reinicie o monitor.