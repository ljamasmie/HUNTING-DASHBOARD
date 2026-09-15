name: Refrescar respuestas de Gmail

on:
  schedule:
    # Cada hora, en el minuto 15 (para no chocar con el refresh de Apollo que corre en el minuto 0).
    - cron: "15 * * * *"
  workflow_dispatch: {}  # permite lanzarlo manualmente desde la pestaña Actions

permissions:
  contents: write

jobs:
  refresh-replies:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Ejecutar refresh_replies.py
        env:
          GMAIL_CLIENT_ID: ${{ secrets.GMAIL_CLIENT_ID }}
          GMAIL_CLIENT_SECRET: ${{ secrets.GMAIL_CLIENT_SECRET }}
          GMAIL_REFRESH_TOKEN: ${{ secrets.GMAIL_REFRESH_TOKEN }}
        run: python3 scripts/refresh_replies.py

      - name: Commit replies.json si hubo cambios
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          if git diff --quiet -- replies.json; then
            echo "Sin cambios en replies.json"
          else
            git add replies.json
            git commit -m "chore: refresh Gmail replies ($(date -u +'%Y-%m-%d %H:%M UTC'))"
            git push
          fi
