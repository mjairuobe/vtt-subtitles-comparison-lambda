# vtt-subtitles-comparison-lambda

AWS Lambda (Python 3.11) zum Vergleich von zwei Gruppen an Untertiteldateien.

## Features

- Upload per `multipart/form-data` an **einen Endpoint**.
- Zwei Gruppen:
  - `older_files` (ältere Version)
  - `newer_files` (aktuellere Version)
- Pro Gruppe unterstützt:
  - einzelne `.vtt`/`.txt` Dateien
  - `.zip` Archive mit mehreren `.vtt`/`.txt` Dateien
- Jede hochgeladene Datei ist eine logische Vergleichseinheit:
  - normale `.vtt`/`.txt` Datei = 1 logische Datei
  - `.zip` Datei = 1 logische Datei (enthält mehrere VTT/TXT, intern zusammengeführt)
- Leere einzelne `.vtt`/`.txt` Dateien sind erlaubt und werden im Ergebnis explizit aufgeführt.
- Fehlender `WEBVTT`-Header wird toleriert, sofern gültige Timing-Zeilen vorhanden sind.

## Vergleichsmetriken

Die API liefert:

- Anzahl Timestamps (gesamt und eindeutig) pro Gruppe
- weggefallene Timestamps
- hinzugefügte Timestamps
- Wörter-Statistik pro Gruppe (`sum`, `min`, `max`, `avg`) **pro Timestamp**
  - `sum`: Summe aller Wörter über alle Timestamps
  - `min`: minimale Wörteranzahl in einem Timestamp
  - `max`: maximale Wörteranzahl in einem Timestamp
  - `avg`: durchschnittliche Wörteranzahl pro Timestamp
- Gruppenvergleich der Aggregatwerte über `word_aggregate_comparison` mit
  `sum/min/max/avg` jeweils als `older`, `newer`, `delta`
- Informationen zu leeren Dateien (`empty_files`, `empty_logical_file_names`, `empty_files_count`)

## Lokales Testen

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Lambda Handler

- Entry Point: `function.main.handler`
- `GET`: liefert ein Vergleichs-Frontend (HTML/CSS + JS) mit:
  - Upload der beiden Gruppen
  - visueller Gegenüberstellung der Ergebnisse
  - optionalem Download eines Beispiel-JSONs
  - optionalem Download des letzten Vergleichs-JSONs
- `POST`: verarbeitet Multipart-Uploads und gibt JSON mit den Vergleichsergebnissen zurück
- `OPTIONS`: CORS Preflight

## Build/Deploy (Jenkins)

Eine Jenkins-Pipeline (`Jenkinsfile`) ist analog zum Referenzprojekt aufgebaut:

1. Checkout
2. ECR Login
3. Docker Build + Tag
4. Push nach ECR
5. Lambda Create/Update aus Container-Image
6. Lambda Function URL automatisch anlegen/aktualisieren (Auth `NONE`)
7. Öffentliche Berechtigung (`lambda:InvokeFunctionUrl`) idempotent setzen

Die zentralen Variablen (`AWS_REGION`, `ECR_REGISTRY`, `ECR_REPOSITORY`, `LAMBDA_FUNCTION_NAME`, `LAMBDA_ROLE_ARN`, `FUNCTION_URL_AUTH_TYPE`, `FUNCTION_URL_PERMISSION_SID`) können in der Pipeline angepasst werden.
