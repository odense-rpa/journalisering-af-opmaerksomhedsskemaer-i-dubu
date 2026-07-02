# Journalisering af opmærksomhedsskemaer i DUBU

Robotten modtager opmærksomhedsskemaer via e-mail og journaliserer dem automatisk som aktiviteter i DUBU med besked til den ansvarlige sagsbehandler.

## Hvad gør robotten?

1. Tjekker den delte postkasse `rpa.bfr@odense.dk` for nye e-mails fra `xflow@odense.dk`
2. Parser hver e-mail og udtrækker strukturerede data: CPR-nummer, navn og lokation
3. Tilføjer nye e-mails til arbejdskøen med e-mailens internet message ID som unik reference — allerede køsatte e-mails springes over
4. Søger i DUBU efter en sag, der matcher CPR-nummeret
5. Opretter en aktivitet af typen *Statusudtalelse* i DUBU med undertype sat til lokationen og en note om, at opmærksomhedsskemaet er journaliseret af Robot A
6. Henter e-mailens vedhæftede fil og uploader den som dokument på den nyoprettede aktivitet
7. Slår den primære sagsbehandler op i DUBU og sender en personlig advisering med link til aktiviteten
8. Flytter den behandlede e-mail til mappen *Journaliseret opmærksomhedsskema* i postkassen

## Forudsætninger

- Python ≥ 3.13
- [`uv`](https://docs.astral.sh/uv/) til pakkehåndtering
- Adgang til **Automation Server** (arbejdskø og credentials)
- Adgang til **DUBU** via RoboA-bruger
- Adgang til den delte postkasse `rpa.bfr@odense.dk` via Microsoft Graph (RoboC)
- Adgang til **Odense SQL Server** til opgavesporing

## Installation

```sh
uv sync
```

## Konfiguration

Credentials registreres i Automation Server:

- `RoboA` — DUBU-login (ekstra felter: `idp`, `ad_server_url`, `ad_server_port`, `ad_server_base_dn`)
- `RoboC` — Microsoft Graph-adgang til den delte postkasse
- `Odense SQL Server` — opgavesporing

Valgfri miljøvariabel:

| Variabel | Beskrivelse |
|---|---|
| `ATS_WORKQUEUE_OVERRIDE` | Tilsidesæt valg af arbejdskø (valgfrit) |

## Kørsel

```sh
uv run python main.py --queue   # Fyld arbejdskøen med nye e-mails
uv run python main.py           # Behandl arbejdskøen
```

## Afhængigheder

| Pakke | Formål |
|---|---|
| `automation-server-client` | Arbejdskøstyring og credential-opslag i Automation Server |
| `dubu-client` | Søg sager, opret aktiviteter, upload dokumenter og send adviseringer i DUBU |
| `odk-tools` | Opgavesporing via Tracker-klassen |
| `azure-identity` | Azure-autentificering til Microsoft Graph |
| `msgraph-sdk` | Læs og administrer e-mails via Microsoft Graph API |
| `aiofiles` | Asynkron fil-I/O |
| `python-dotenv` | Indlæs miljøvariabler fra `.env`-fil |
| `beautifulsoup4` | Parser HTML-e-mailbodies til ren tekst |
| `active-directory` | Active Directory-opslag |

## GDPR og sikkerhed

Robotten behandler CPR-numre og navne på borgere i forbindelse med sagssøgning i DUBU samt ved oprettelse af aktivitetsnoter og adviseringer. Oplysningerne stammer fra opmærksomhedsskemaerne og gemmes ikke uden for DUBU og postkassens arkivmappe. Adgang til Automation Server-logs og postkassen bør begrænses til medarbejdere med saglig grund.
