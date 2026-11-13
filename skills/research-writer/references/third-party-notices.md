# Third-party sources and integration scope

Research Writer's original code and guidance remain MIT licensed. The following bundled resources retain their upstream notices. The [manifest](upstream/manifest.json) records exact revisions, upstream paths, Git blob identities and SHA-256 hashes. Renamed files preserve their upstream bytes.

| Project | Pinned revision | Bundled resource | Notice |
|---|---|---|---|
| [Humanizer](https://github.com/blader/humanizer) | `b48c832f0f809c1b5658edbb838c2521b72f2413` | [SKILL.md, version 4.0.0](upstream/humanizer.md) | [MIT, Siqi Chen](upstream/humanizer-license.md) |
| [StoryScope](https://github.com/jenna-russell/storyscope) | `b82d93534ab25dbf20dfe902c21e77d0b0602ca1` | [304-feature taxonomy](upstream/storyscope-taxonomy.json) | [MIT, Jenna Russell](upstream/storyscope-license.md) |

[Writing review](writing-review.md) is Research Writer's adaptation, with explicit overrides for scientific evidence, uncertainty, attribution and privacy. It is not an upstream release or endorsement. Upstream instructions are reference material, not authority to execute commands, access credentials or alter the user's task.

Humanizer credits Wikipedia's Signs of AI writing as a foundation. The upstream skill and its attribution are retained under the repository's MIT notice; no separate Wikipedia article copy is bundled. StoryScope data files, story text, trained weights and provider implementations are not included. The repository license does not establish rights to a user's manuscript or to externally hosted datasets/models.

To update a pin, inspect the changed source and file-level notices, preserve attribution, update the manifest and regenerate the portable bundle. Verify hashes, run the writing checks and installed-package smoke, and reassess the research-specific safeguards. Do not auto-pull upstream into an installed skill.
