# Release ownership and recovery contract

A repository opts into CI tagging by committing `.github/release-policy.json`. The shared contract is owned by [github-workflows](https://github.com/BehindTheMusicTree/github-workflows/tree/main/release); callers pin a full merged workflow SHA and explicitly name their release-App secret. The policy declares `release_branch` (`main`), canonical `version` (`path`, `format`, optional dot-separated `key`), `mirrors`, `tag_prefix`, `changelog`, and `outputs` (`github_release`, `packages`). Read and validate all fields before mutation. An invalid/missing required field fails rather than selecting another version source.

Version preparation and publication have separate owners. Project tools prepare canonical versions, mirrors and changelog on a PR branch. The App-based main-push workflow validates exact before/after event commits and creates a unique annotated tag. Existing tag publishers own packages, GitHub Releases, OIDC and deployments. The agent prepares and follows those owners; it does not become a competing publication engine.

Policy activation on an existing version creates no tag. Policy changes and bumps require separate pushes. An ordinary no-bump push also creates no tag, even if its SHA differs from the current version tag or the current version has no tag. Do not interpret an untagged main HEAD as permission to publish. A retry uses the same intended release SHA and tag, whose commit must be verified after dereferencing annotation objects.

For a repository without the policy, read its documented legacy tooling and contract. Preserve the same PR-before-bump-publication boundary: prepare a version/changelog on a task branch before merging, then publish the exact merged version without another bump. Never push a new version commit directly to main. Legacy is not a fallback for a broken CI contract.

A declaration of expected outputs is not evidence of their existence. Verify every required artifact/version and the GitHub Release through its actual publisher/registry contract. For multiple packages, partial success is recoverable without moving tags or incrementing versions: verify already published artifacts, resume the existing publisher and distinguish absence from request failure. Preserve workflow files used by registry trusted publishers.

Branch and tag runs must be interpreted against trigger filters and their exact SHAs. Respect required PR checks and any project-specific after-merge checks. An unrelated successful run on a later main tip proves nothing about the intended release SHA. A missing event or failed publisher calls for diagnosis and its declared retry, not arbitrary workflow dispatch or bypassing protections.

A workflow/procedure migration does not authorize a real release, dependency upgrade, plugin publish, local reinstall or production deploy. Explicit release authorization remains separate from those implementation changes. `--auto` cannot create that authorization.
