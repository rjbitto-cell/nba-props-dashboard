name: Update NBA Data

on:
  schedule:
    - cron: '0 15 * * *'
  workflow_dispatch:

jobs:
  update-data:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: pip install pandas nba_api

      - name: Run script
        run: python update_data.py

      - name: Commit updated data
        run: |
          git config --global user.name "bot"
          git config --global user.email "bot@github.com"
          git add data/player_stats.csv data/matchups.csv
          git commit -m "auto update data" || echo "No changes"
          git push
