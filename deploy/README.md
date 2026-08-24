# Deployment baseline

The API image is a starting point only. Production deployment must mount separate writable paths for SQLite/LanceDB and read-only PDF assets, configure backup and restore, and provide secrets outside the image.

Do not deploy before the readiness check, active release validation and rollback procedures in specification 05 are implemented.
