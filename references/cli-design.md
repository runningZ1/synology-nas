# CLI delivery contract

Version 0.2.0. Users: Agents and humans on the existing Windows/Python 3.12 host. Keep Python and the legacy `scripts/nas.py` interface; add the installable `synology-nas` executable, with no runtime third-party dependency. No subprocess/shell execution or daemon in the CLI.

Backend: Synology API discovery + official DSM Auth/File Station APIs. Endpoint paths/versions are negotiated against the device. Reference repositories are design evidence, not runtime dependencies. Optional DSM/Core and Download Station read operations are catalogued separately as device/community interfaces; missing packages return unsupported, never trigger installation.

Commands: version, schema, errors, doctor, discover, auth status, info, shares, list, stat, tree, search, mkdir, rename, copy, move, delete, upload, download, size, checksum, favorites, shares-links, tasks, system, api catalog/call. The catalog carries each API method's classification, required fields, version cap and source. Binary APIs use upload/download/thumbnail commands instead of JSON dispatch.

Machine contract: one versioned JSON envelope on stdout, including errors; JSONL emits one terminal envelope; text is escaped JSON for terminal safety. Exit codes 0 success; 1 unexpected/internal or backend operation failure; 2 invalid input; 3 auth/permission/missing; 4 transport/deadline; 5 conflict; 130 interruption. Error outcomes distinguish dispatched ambiguous writes. No automatic retries. Request timeout and command deadline bounded.

Reads: page size default 100/max 1000, explicit offsets; projection preserves path identity. Tree defaults depth 3, max 500 directories, 5000 entries, excludes recycle/snapshot/index internals, exports explicitly with completeness metadata. Search/long operations return task IDs and status/list commands when pending.

Writes: no remote mutation without --commit; default dry-run performs authenticated lookups, validates scope and builds a plan. --scope is a shared-folder-relative path, required for file mutations and enforced for all source/destination operands. Never mutate shared-folder roots. Deletion additionally requires --confirm equal to the normalized exact target. Generic high-risk sharing changes require --allow-sharing. Raw calls are allowlisted; no arbitrary DSM administration. All writes are non-retried; mkdir(existing directory), rename(same name) and delete(missing) return declared no-op. Remote concurrency is not transactional; never claim exactly-once.

Credentials: --password-file (file managed by user), --password-stdin, or SYNOLOGY_PASSWORD for CI compatibility. No password argv/config, no credential persistence or history extraction in product code. URL/user/CA may come from flags > environment > explicit/default nonsecret config. HTTPS verification default on; --insecure is per invocation only. Each invocation logs in and logs out; SID stays in memory. Auth status is a real login check, no persistent login command is needed.

Acceptance: faithful local fixture for failure matrix, pagination, mutation boundary, projection, binary integrity and hostile paths; installed Windows entrypoint; real read commands plus isolated CRUD/copy/move/archive/checksum checks only in a new test directory. No live share-link, settings, account, mount, backup, package or administrative changes.
