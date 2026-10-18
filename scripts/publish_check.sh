#!/usr/bin/env bash
# Run after `git add -A` and BEFORE you commit/push.
# Fails (exit 1) if anything personal is about to be published.
set -u
cd "$(dirname "$0")/.."
fail=0

echo "Checking staged files for personal data..."

# 1) files that must never be committed
bad_paths=$(git ls-files --cached | grep -E \
  '(^|/)(\.env|contacts\.json|priority_contacts\.txt|creds\.json)$|(^|/)auth/|^whatsapp/data/|\.(db|sqlite3?|jsonl|pem|key)$|ggml-.*\.bin$|(^|/)data/|^backups/|^reports/' || true)
if [ -n "$bad_paths" ]; then
    echo "✗ These files must not be committed:"; echo "$bad_paths" | sed 's/^/    /'; fail=1
fi

# 2) secrets / personal identifiers inside file contents (placeholders are allowed)
patterns=(
  'gsk_[A-Za-z0-9]{20,}'
  'csk-[a-z0-9]{20,}'
  'sk-[A-Za-z0-9]{20,}'
  'AIza[0-9A-Za-z_-]{30,}'
  'gh[pousr]_[A-Za-z0-9]{30,}'
  '[A-Za-z0-9._%+-]+@(gmail|googlemail|yahoo|outlook|hotmail)\.com'
  '\+?[0-9]{2}[ -]?[6-9][0-9]{9}\b'
  'APP_PASSWORD=[A-Za-z]{16}\b'
)
allowed='you@gmail\.com|me@gmail\.com|good@gmail\.com|gsk_xxx|gsk_yyy|abcdefghijklmnop|example'
for pattern in "${patterns[@]}"; do
    hits=$(git grep --cached -nIE "$pattern" -- . ':!*package-lock.json' | grep -Ev "$allowed" || true)
    if [ -n "$hits" ]; then
        echo "✗ Suspicious content matching /$pattern/:"
        echo "$hits" | sed -E 's/(.{110}).*/\1.../; s/^/    /'
        fail=1
    fi
done

# 3) large files
big=$(git ls-files --cached -z | xargs -0 -r du -k 2>/dev/null | awk '$1 > 5000 {print $2" ("$1" KB)"}')
if [ -n "$big" ]; then
    echo "! Large files staged (>5 MB):"; echo "$big" | sed 's/^/    /'
fi

if [ "$fail" -eq 0 ]; then
    echo "✓ Nothing personal found. Safe to commit and push."
else
    echo; echo "Fix the items above (add them to .gitignore, then: git rm --cached <file>) and re-run."
fi
exit "$fail"
