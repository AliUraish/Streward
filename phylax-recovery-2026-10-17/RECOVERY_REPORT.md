# Phylax recovery result

**Partial preservation only. No application source files were recovered. This is not a working repository or a recreation of the application.**

The exact loaded revision was `fac4f39d1458c334e1854576ea07981cf9613887` on `main` in `https://github.com/charlie-robison/phylax`. The surviving page displayed 43 commits.

## Material preserved

- `README.rendered.html` and `README.rendered.txt`: the README as rendered in the original open tab. The original raw Markdown bytes were not available.
- `repository-inventory.json` and `root-listing.txt`: all 19 root entries visible in the tab. A directory name does not include that directory's contents.
- `commit-messages.json`: 11 distinct commit identifiers and their descriptions visible in the directory listing. These are not Git commit objects or patches.
- `branches.json`: seven original branch names decoded from an existing cached GitHub response.
- `evidence/loaded-repository.mhtml`: a 3,092,682-byte Chrome archive of the surviving rendered page, saved without navigating away from or refreshing the original tab.
- `evidence/loaded-page-rendered.html`: the rendered HTML extracted from that MHTML archive. Chrome's MHTML export omits executable script elements.
- `evidence/cache/` and `evidence/cache-manifest.json`: eight matching HTTP cache files preserved before exploration, with original paths, sizes, modification times, SHA-256 hashes, and unchanged-during-copy checks.
- `evidence/user-screenshot.png`: the screenshot supplied in this chat.

## Checks and results

The normal repository URL, the exact commit in the signed-in browser, the standard ZIP archive pinned to that commit, and the raw README at that commit returned 404. A 404 does not establish whether the repository was deleted, made private, or otherwise became inaccessible.

The eight matching HTTP cache entries contained ancillary GitHub metadata and a cached 404 homepage response. None contained an application source-file response. The existing open tab still retained the older rendered repository homepage in memory.

The relevant Service Worker caches and Code Cache contained no matching repository entries. Matching open-tab inventory and the bounded matching browser-history query found only the repository homepage. Filename searches in Downloads, Desktop, Documents, the current workspace, and common code directories found no Phylax clone or archive.

Software Heritage reported that this origin was not found. Internet Archive returned a temporary-offline response (503), so its archive coverage could not be assessed. A focused public search for the exact repository name returned no results.

## Integrity and limits

The eight copied cache files match their recorded SHA-256 hashes and did not change during copying. The saved README's normalized text length and Unicode codepoint sum match the live original tab. The 19 root entries, 11 commit descriptions, and seven branch names were checked after extraction.

No source files were invented, reconstructed from the demo, or substituted from a different project. No repository code, setup scripts, credentials, cloud services, or database connections were executed. The original GitHub tab remains open with its original content.

Obtaining the exact application now requires an existing clone or ZIP, another machine with source-file pages cached, access restored by the repository owner, or a complete public archive. The material preserved here is insufficient to reproduce the original source bytes.

`phylax-recovered-materials.zip` includes only the readable recovered documents, inventory, and verification report. The browser archive and raw HTTP cache evidence remain local in `evidence/`.
