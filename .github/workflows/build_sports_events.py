name: Build and publish Sports Event EPG

on:
  workflow_dispatch:
  schedule:
    - cron: "7 */6 * * *"

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install tools
        run: |
          sudo apt-get update
          sudo apt-get install -y xz-utils

      - name: Build XMLTV feed
        run: |
          python builder/build_sports_events.py

      - name: Prepare GitHub Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: public

  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    needs: build
    runs-on: ubuntu-latest

    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
