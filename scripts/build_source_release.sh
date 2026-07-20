#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Usage: $0 <version-or-label>" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Refusing to archive: tracked files have uncommitted changes." >&2
  exit 1
fi

for required in LICENSE NOTICE THIRD_PARTY_NOTICES.md SECURITY.md CONTRIBUTING.md .gitattributes; do
  if ! git cat-file -e "HEAD:$required"; then
    echo "Refusing to archive: $required is not committed in HEAD." >&2
    exit 1
  fi
done

forbidden_pattern='(^|/)(\.env($|\.)|.*\.(pem|key|p12|pfx|dump|sqlite3?|db)$|backups?/|pg_backup/|release_mail/|security-audit/)'
if git archive --format=tar HEAD \
  | tar -tf - \
  | grep -E "$forbidden_pattern" \
  | grep -vE '^\.env(\.[^.]+)?\.example$'; then
  echo "Refusing to archive: a forbidden path would be included." >&2
  exit 1
fi

mkdir -p dist-source
output="dist-source/oral-source-$1.zip"
if [[ -e "$output" ]]; then
  echo "Refusing to overwrite existing archive: $output" >&2
  exit 1
fi

git archive --format=zip --prefix="oral-$1/" --output="$output" HEAD
sha256sum "$output"
echo "Created $output from $(git rev-parse --short=12 HEAD)"
