# Bidded

**Spårbart beslutsstöd för offentlig upphandling.**

Bidded hjälper IT-konsultbolag att bedöma vilka offentliga upphandlingar de bör lämna anbud på. Projektet är en hackathonprototyp för svensk offentlig upphandling som jämför upphandlingskrav med företagets förmågor och låter specialiserade AI-agenter ta fram en gemensam, källbaserad rekommendation.

## Så fungerar det

1. **Samla underlaget.** Upphandlingsdokument i textbaserad PDF eller DOCX bearbetas och kopplas till en företagsprofil med kompetenser, certifieringar och referenser.
2. **Granska från flera perspektiv.** En Evidence Scout identifierar centrala fakta. Fyra specialistagenter analyserar formella krav, vinststrategi, leverans och ekonomi samt risker. De gör först oberoende bedömningar och granskar sedan varandras argument.
3. **Få en motiverad rekommendation.** En Judge sammanväger analysen till `bid`, `no_bid` eller `conditional_bid`, med risker, saknad information och konkreta nästa steg. Kritiska luckor eller motstridiga underlag kan leda till `needs_human_review`.

## Evidens i varje steg

Materiella påståenden ska stödjas av källhänvisningar till specifika utdrag ur upphandlingsdokument eller företagsunderlag. Dokumenthänvisningar behåller sidreferenser, och osäkerheter redovisas som antaganden eller saknad information.

Webbgränssnittet gör det möjligt att följa analysen, granska agenternas argument och öppna underlaget bakom rekommendationen. Vid `bid` eller `conditional_bid` kan Bidded även skapa ett anbudsutkast med citerade svar och föreslagna bilagor.

## Teknik

- **Backend:** Python, FastAPI, LangGraph, Claude via Anthropic API och Pydantic.
- **Frontend:** React, TypeScript, Vite och Tailwind CSS.
- **Data och dokument:** Supabase Postgres och Storage, PyMuPDF samt LibreOffice för DOCX-konvertering.
- **Kvalitet:** Deterministiska tester med pytest och Vitest samt lint med Ruff.

## Kom igång

Se [demo-runbook](docs/demo-runbook.md) för installation, konfiguration och körning, samt [frontend-guiden](frontend/README.md) för webbgränssnittet.
