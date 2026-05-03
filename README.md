# vtt-subtitles-comparison-lambda

AWS Lambda (Python 3.11) zum Vergleich von zwei Gruppen an Untertiteldateien.

## Features

- Upload per `multipart/form-data` an **einen Endpoint**.
- Zwei Gruppen:
  - `older_files` (aeltere Version)
  - `newer_files` (aktuellere Version)
- Pro Gruppe unterstuetzt:
  - einzelne `.vtt`/`.txt` Dateien
  - `.zip` Archive mit mehreren `.vtt`/`.txt` Dateien
- Jede hochgeladene Datei ist eine logische Vergleichseinheit:
  - normale `.vtt`/`.txt` Datei = 1 logische Datei
  - `.zip` Datei = 1 logische Datei (enthaelt mehrere VTT/TXT, intern zusammengefuehrt)
- Leere einzelne `.vtt`/`.txt` Dateien sind erlaubt und werden im Ergebnis explizit aufgefuehrt.
- Fehlender `WEBVTT`-Header wird toleriert, sofern gueltige Timing-Zeilen vorhanden sind.

## Vergleichsmetriken

Die API liefert:

- Anzahl Timestamps (gesamt und unique) pro Gruppe
- weggefallene Timestamps
- hinzugefuegte Timestamps
- Woerter-Statistik pro Gruppe (`sum`, `min`, `max`, `avg`) **pro logischer Datei**
- Delta zwischen neuer und alter Version fuer die Woerter-Statistik
- Informationen zu leeren Dateien (`empty_files`, `empty_logical_file_names`, `empty_files_count`)

## Lokales Testen

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Lambda Handler

- Entry Point: `function.main.handler`
- `GET`: liefert ein simples Upload-Frontend
- `POST`: verarbeitet Multipart-Uploads und gibt JSON mit den Vergleichsergebnissen zurueck
- `OPTIONS`: CORS Preflight

## Build/Deploy (Jenkins)

Eine Jenkins-Pipeline (`Jenkinsfile`) ist analog zum Referenzprojekt aufgebaut:

1. Checkout
2. ECR Login
3. Docker Build + Tag
4. Push nach ECR
5. Lambda Create/Update aus Container-Image
6. Lambda Function URL automatisch anlegen/aktualisieren (Auth `NONE`)
7. Oeffentliche Berechtigung (`lambda:InvokeFunctionUrl`) idempotent setzen

Die zentralen Variablen (`AWS_REGION`, `ECR_REGISTRY`, `ECR_REPOSITORY`, `LAMBDA_FUNCTION_NAME`, `LAMBDA_ROLE_ARN`, `FUNCTION_URL_AUTH_TYPE`, `FUNCTION_URL_PERMISSION_SID`) koennen in der Pipeline angepasst werden.
