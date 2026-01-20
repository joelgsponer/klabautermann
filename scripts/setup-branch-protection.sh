#!/bin/bash
# Setup branch protection rules for main and dev branches
# Requires: gh CLI authenticated with admin permissions
#
# Usage: ./scripts/setup-branch-protection.sh

set -euo pipefail

OWNER="joelgsponer"
REPO="klabautermann"

echo "Setting up branch protection rules for $OWNER/$REPO..."

# Function to set branch protection
setup_protection() {
    local branch=$1
    echo "Configuring protection for branch: $branch"

    gh api "repos/$OWNER/$REPO/branches/$branch/protection" \
        -X PUT \
        -H "Accept: application/vnd.github+json" \
        --input - <<EOF
{
    "required_status_checks": {
        "strict": true,
        "contexts": ["Lint", "Type Check", "Test"]
    },
    "enforce_admins": false,
    "required_pull_request_reviews": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews": true,
        "require_code_owner_reviews": false
    },
    "restrictions": null,
    "allow_force_pushes": false,
    "allow_deletions": false,
    "required_linear_history": false,
    "required_conversation_resolution": true
}
EOF

    echo "✓ Branch protection set for $branch"
}

# Setup for main branch
setup_protection "main"

# Setup for dev branch
setup_protection "dev"

echo ""
echo "Branch protection rules configured successfully!"
echo ""
echo "Summary:"
echo "  - Require PR reviews (1 approver)"
echo "  - Require status checks (Lint, Type Check, Test)"
echo "  - Require branches up to date"
echo "  - No force pushes"
echo "  - No branch deletions"
echo "  - Require conversation resolution"
