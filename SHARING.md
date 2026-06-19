# Sharing Guide

This repository is private by default because it contains research-specific app logic and generated card metadata.

## Best Option: Invite a GitHub Account

Ask the recipient for their GitHub username, then invite them as a collaborator.

```bash
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  /repos/hajimeTUT/open-campus-feature-game/collaborators/<github-username> \
  -f permission=pull
```

After the invitation is accepted, share this URL:

```text
https://github.com/hajimeTUT/open-campus-feature-game
```

## Alternative: Make the Repository Public

Only use this if it is acceptable to publish the app source and generated card metadata publicly.

```bash
gh repo edit hajimeTUT/open-campus-feature-game --visibility public --accept-visibility-change-consequences
```

## Fallback: Share a ZIP

If the recipient cannot use GitHub immediately, create a ZIP from the committed files.

```bash
git archive --format=zip --output ../open-campus-feature-game.zip HEAD
```

The ZIP excludes logs, registered devices, access-control runtime files, audio clips, and temporary tunnel files because those are ignored or untracked.
