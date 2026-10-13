# Monitor de Logs ATI

Monitora uma caixa de email por IMAP, identifica erros recorrentes por conjunto
de dados e envia alertas por SMTP. A GUI e o serviço usam o mesmo fluxo.

## Roteamento para o controlador

Quando `CONTROLLER_DB_ENABLED = True`, a automação consulta o banco usando o
nome do conjunto extraído do log. Os emails retornados pela consulta são os
destinatários daquele alerta.

1. Lê o email de log e extrai conjunto e erro.
2. Registra a ocorrência sem contar novamente o mesmo Message-ID.
3. Ao atingir o mínimo de ocorrências, consulta os controladores desse conjunto.
4. Envia o alerta para os emails encontrados.
5. Confirma o alerta no histórico apenas após o sucesso do SMTP.

Sem controlador, com email inválido, falha no banco ou falha no SMTP, a mensagem
que disparou o alerta fica não lida para uma nova tentativa no próximo ciclo.
O estado persistido evita incrementar a contagem a cada tentativa, inclusive
após reiniciar. A janela de detecção continua valendo: ocorrências expiradas
saem da contagem.

Com o banco ativo, a lista fixa `EMAIL_RECIPIENTS` não é usada como alternativa
para um conjunto sem cadastro. Com o banco desativado, ela mantém o
comportamento anterior. Vários controladores podem receber o mesmo alerta;
emails repetidos são eliminados.

## Configuração

Instale as dependências:

```bash
pip install -r requirements.txt
```

Gere `config.py` pela GUI (`python main.py`) ou copie `config.py.example` para
`config.py` e ajuste IMAP, SMTP e os parâmetros de detecção.

| Configuração | Uso |
|---|---|
| `CONTROLLER_DB_ENABLED` | Ativa a consulta ao banco; padrão `False` |
| `CONTROLLER_DB_URL_ENV` | Nome da variável com a URL do banco; padrão `MONITOR_DATABASE_URL` |
| `CONTROLLER_DB_QUERY` | SELECT com parâmetro `:conjunto` e email na primeira coluna |
| `CONTROLLER_DB_CONNECT_ARGS` | Dicionário de opções específicas do driver, como timeout |
| `EMAIL_RECIPIENTS` | Destinatários fixos quando o banco está desativado |
| `POLLING_INTERVAL_MINUTES` | Intervalo entre verificações |
| `DEDUP_WINDOW_HOURS` | Janela para contar ocorrências |
| `MIN_OCCURRENCES_TO_ALERT` | Ocorrências novas necessárias para cada alerta |
| `REGEX_CONJUNTO` / `REGEX_ERRO` | Ajustes para o formato dos emails de log |

A GUI tem uma seção **Banco de Controladores** com consulta SQL, opções de
conexão e o botão **Consultar controlador (sem enviar)**. Salvar pela GUI
reescreve `config.py`; faça os ajustes de banco nos campos da interface se
pretender continuar usando esse modo.

### Conexão e driver

A URL fica no ambiente do processo que executa a automação. Não é copiada para
`config.py` nem `config_ui.json` pela configuração do banco.

| Banco | Driver adicional | Formato de URL |
|---|---|---|
| SQL Server | `pip install pyodbc` e ODBC Driver 18 no sistema | `mssql+pyodbc://USUARIO:SENHA@SERVIDOR/BASE?driver=ODBC+Driver+18+for+SQL+Server` |
| PostgreSQL | `pip install psycopg2-binary` | `postgresql+psycopg2://USUARIO:SENHA@SERVIDOR:5432/BASE` |
| MySQL | `pip install PyMySQL` | `mysql+pymysql://USUARIO:SENHA@SERVIDOR:3306/BASE` |
| SQLite | Incluído no Python | `sqlite:///controladores.db` |

Instale o driver do banco escolhido na máquina de execução e, para gerar o
executável, também na máquina de build. O SQLAlchemy utiliza a URL para
selecionar o driver. Consulte a [documentação de URLs do SQLAlchemy](https://docs.sqlalchemy.org/en/20/core/engines.html#database-urls).

Exemplo local com SQLite no PowerShell:

```powershell
$env:MONITOR_DATABASE_URL = 'sqlite:///controladores.db'
python check_controller.py 'BASE_VENDAS'
```

No servidor, configure a variável no ambiente da conta/serviço que executa o
monitor. Uma variável definida apenas em um terminal não aparece
automaticamente em um serviço já iniciado. Use uma conta de banco com
permissão de SELECT nas tabelas necessárias. Para senhas com caracteres
especiais, codifique esses caracteres na URL conforme a documentação do driver.

### Relação entre conjunto e email

A consulta padrão é um **exemplo de esquema**, que deve ser ajustado ao banco
existente:

```sql
SELECT email_controlador
FROM conjunto_controlador
WHERE LOWER(TRIM(nome_conjunto)) = :conjunto
```

O parâmetro `:conjunto` recebe o nome extraído do log, sem espaços nas
extremidades e em minúsculas. Ele é enviado como parâmetro do banco, sem
interpolação de texto no SQL. A primeira coluna deve conter um email por linha,
sem nome de exibição nem vários emails separados por vírgula.

Se conjuntos e controladores estiverem em tabelas separadas, configure um JOIN,
por exemplo:

```sql
SELECT c.email
FROM conjuntos_de_dados d
JOIN controladores c ON c.id = d.controlador_id
WHERE LOWER(TRIM(d.nome)) = :conjunto
```

Ajuste nomes de tabelas, colunas, funções e collation para o seu banco. O
cruzamento utiliza igualdade; não há aproximação de nomes. O comportamento
de maiúsculas/minúsculas e acentos depende das funções e da collation do banco.
Em versões antigas do SQL Server, substitua `TRIM(d.nome)` por
`LTRIM(RTRIM(d.nome))`.

Caso ainda não exista cadastro, uma tabela de referência pode ter esta forma:

```sql
CREATE TABLE conjunto_controlador (
    nome_conjunto VARCHAR(255) NOT NULL,
    email_controlador VARCHAR(255) NOT NULL,
    PRIMARY KEY (nome_conjunto, email_controlador)
);

INSERT INTO conjunto_controlador (nome_conjunto, email_controlador)
VALUES ('base_vendas', 'controlador@example.invalid');
```

Esse SQL é ilustrativo: a automação não cria ou modifica tabelas.

### Validar antes de iniciar

Ative `CONTROLLER_DB_ENABLED`, defina a URL e execute:

```bash
python check_controller.py "BASE_VENDAS"
```

O comando consulta o banco e mostra os emails encontrados. Não envia email nem
altera o arquivo de ocorrências. Falhas retornam código de saída 1 com uma
mensagem de diagnóstico que omite os detalhes de conexão.

Após validar os conjuntos, inicie pela GUI ou execute `python service.py`.

## Executável e servidor

```bash
python build.py gui
python build.py service
```

Os executáveis são gerados em `dist/`. O build inclui os módulos de consulta,
os dialects do SQLAlchemy e os drivers pyodbc, psycopg2 e pymysql que estiverem
instalados. O executável Windows deve ser gerado no Windows; a dependência
nativa ODBC precisa estar instalada na VM quando esse driver for utilizado.

Copie o executável e `config.py` para a mesma pasta no servidor e configure a
variável de ambiente do banco para o processo. O modo serviço pode ser
gerenciado por NSSM, Tarefa Agendada ou systemd, conforme o sistema operacional.

A confirmação de envio significa que o SMTP aceitou os destinatários. Em
recusa parcial, o alerta fica pendente e a nova tentativa pode repetir o email
para um destinatário já aceito anteriormente.

## Arquivos

| Arquivo | Função |
|---|---|
| `main.py`, `gui.py` | Interface gráfica e configuração |
| `service.py` | Execução contínua sem interface |
| `monitor_cycle.py` | Processamento compartilhado e novas tentativas |
| `controller_directory.py` | Consulta de controladores e validação de emails |
| `check_controller.py` | Teste de consulta sem envio |
| `configuration.py`, `config.py.example` | Geração e exemplo de configuração |
| `imap_reader.py`, `parser.py` | Leitura e extração dos logs |
| `tracker.py` | Contagem e confirmação de alertas |
| `alert.py`, `tls_compat.py` | Envio SMTP |
| `build.py`, `requirements.txt` | Build e dependências |
| `tests/test_controller_routing.py` | Testes com SQLite e IMAP/SMTP simulados |

Em execução, o monitor usa `monitor.log` e `occurrences_state.json`. A GUI
também grava `config_ui.json`. Os arquivos de configuração com credenciais,
estado e logs ficam fora do Git.

## Testes

```bash
python -m unittest discover -s tests -v
```

Os testes verificam o cruzamento usando um banco SQLite real, isolamento entre
conjuntos, JOIN configurável, validação de emails, consultas parametrizadas,
configuração e novas tentativas após reiniciar. IMAP e SMTP são simulados.
