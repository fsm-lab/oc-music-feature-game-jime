# Sharing Guide

This repository is public so that the app source can be shared by URL.

## Share the Public URL

Share this URL:

```text
https://github.com/hajimeTUT/open-campus-feature-game
```

## If Account-Level Access Management Is Needed

Public repositories do not provide account-level access control for readers. If access needs to be limited to named people, make the repository private again and invite GitHub accounts as collaborators.

```bash
gh repo edit hajimeTUT/open-campus-feature-game --visibility private
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  /repos/hajimeTUT/open-campus-feature-game/collaborators/<github-username> \
  -f permission=pull
```

GitHub repository Traffic can show aggregate clone/view counts to repository admins, but it does not provide a reliable per-reader notification for every public access.

## Fallback: Share a ZIP

If the recipient cannot use GitHub immediately, create a ZIP from the committed files.

```bash
git archive --format=zip --output ../open-campus-feature-game.zip HEAD
```

The ZIP excludes logs, registered devices, access-control runtime files, audio clips, and temporary tunnel files because those are ignored or untracked.
