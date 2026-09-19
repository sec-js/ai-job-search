#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the AI Job Search workspace.
# Installs the system + language dependencies the CI checks exercise:
#   - TeX Live (lualatex/xelatex) + poppler-utils for CV/cover-letter compiles
#   - pypdf + pyyaml for the Python tooling and PDF text-layer checks
#   - Bun for the portal-search CLIs
#   - Bun deps for every portal CLI under .agents/skills/*/cli
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export DEBIAN_FRONTEND=noninteractive

# --- System packages: LaTeX toolchain + PDF text extraction ----------------
# lualatex compiles the moderncv CV, xelatex compiles the cover letter, and
# pdftotext (poppler-utils) is the ATS text-layer fallback. apt is idempotent:
# already-installed packages are skipped on reruns.
NEEDED_APT=""
command -v lualatex  >/dev/null 2>&1 || NEEDED_APT="yes"
command -v xelatex   >/dev/null 2>&1 || NEEDED_APT="yes"
command -v pdftotext >/dev/null 2>&1 || NEEDED_APT="yes"
if [ -n "$NEEDED_APT" ]; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends \
    texlive-luatex texlive-latex-extra texlive-xetex \
    texlive-fonts-extra texlive-fonts-recommended \
    poppler-utils
fi

# --- Python dependencies ----------------------------------------------------
# pyyaml powers tools/lint_skills.py; pypdf is the default PDF text extractor
# for tools/verify_pdf.py. --break-system-packages is required on Debian's
# externally-managed Python 3.12.
python3 -m pip install --user --break-system-packages --upgrade pyyaml pypdf

# --- Bun (portal-search CLIs) ----------------------------------------------
if ! command -v bun >/dev/null 2>&1; then
  curl -fsSL https://bun.sh/install | bash
fi
# Make bun available on PATH for every process/terminal without editing shell
# profiles.
if [ -x "$HOME/.bun/bin/bun" ]; then
  sudo ln -sf "$HOME/.bun/bin/bun" /usr/local/bin/bun
  sudo ln -sf "$HOME/.bun/bin/bun" /usr/local/bin/bunx
fi

# --- Portal CLI dependencies -----------------------------------------------
# Discover CLIs the same way CI does (any package.json under skills/*/cli) so
# a fork's /add-portal CLI is bootstrapped without editing this script.
while IFS= read -r pkg; do
  cli_dir="$(dirname "$pkg")"
  echo "bun install: $cli_dir"
  (cd "$cli_dir" && bun install)
done < <(find .agents/skills -mindepth 3 -maxdepth 3 -path '*/cli/package.json' | sort)

echo "Cloud Agent bootstrap complete."
