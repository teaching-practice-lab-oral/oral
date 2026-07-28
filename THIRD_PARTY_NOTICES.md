# Third-party software notices

This project is licensed under Apache-2.0, but that license does not replace
the licenses of its dependencies, container base image, operating-system
packages, remotely loaded browser assets, or external services.

No third-party JavaScript or Python package source is vendored in this
repository. Python packages are installed from `requirements.txt`; their own
license files are retained in the installed distributions. The following table
records the direct dependency versions declared by this source release.

| Dependency | Version | Upstream license metadata |
|---|---:|---|
| Gunicorn | 26.0.0 | MIT |
| FastAPI | 0.139.0 | MIT |
| Starlette | 1.3.1 | BSD-3-Clause |
| Uvicorn | 0.29.0 | BSD-3-Clause |
| SQLAlchemy | 2.0.30 | MIT |
| Alembic | 1.13.1 | MIT |
| psycopg2-binary | 2.9.9 | LGPL with exceptions |
| PyJWT | 2.13.0 | MIT |
| cryptography | 48.0.1 | Apache-2.0 OR BSD-3-Clause |
| Passlib | 1.7.4 | BSD |
| bcrypt | 3.2.2 | Apache-2.0 |
| python-multipart | 0.0.31 | Apache-2.0 |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| boto3 | 1.34.101 | Apache-2.0 |
| OpenAI Python library | 2.45.0 | Apache-2.0 |
| aiosmtplib | 5.1.1 | MIT |
| openpyxl | 3.1.2 | MIT |
| python-docx | 1.2.0 | MIT |
| HTTPX | 0.27.0 | BSD-3-Clause |
| Tenacity | 8.3.0 | Apache-2.0 |
| pydantic-settings | 2.2.1 | MIT |
| email-validator | 2.3.0 | Unlicense |
| aiofiles | 23.2.1 | Apache-2.0 |
| Requests | 2.34.2 | Apache-2.0 |
| pytest (development/test only) | 9.1.1 | MIT |

The application dependency versions and license identifiers above were checked
against the metadata and license files inside the exact wheel files selected on
2026-07-20; OpenAI 2.45.0 was rechecked on 2026-07-22. The pytest entry was
checked from the installed 9.1.1 distribution.
Transitive packages are selected by pip at build time and may change because the
project does not currently ship a complete lockfile. Redistributors must inspect
the resolved environment and preserve all license and NOTICE files included by
those distributions.

## Browser assets

The application loads these assets from jsDelivr rather than redistributing
them in this repository:

- Bootstrap 5.3.2 — MIT.
- Bootstrap Icons 1.11.3 — MIT.

Cloudflare Turnstile JavaScript is loaded from Cloudflare as part of the
Turnstile service and remains subject to Cloudflare's applicable terms.

## Container and system components

The Docker image is built from `python:3.11-slim` and installs FFmpeg from the
base image's Debian repositories. Those components and all of their transitive
system libraries retain their own licenses. FFmpeg's effective license depends
on how the distributed binary was configured, so image redistributors must keep
the Debian copyright files and verify the final image rather than assuming the
project's Apache-2.0 license applies to FFmpeg.

PostgreSQL runs as a separate container image in the provided Compose examples.
It is not part of this project's Apache-2.0 licensed source and remains governed by its upstream terms.

This document is informational and is not legal advice. If a source or binary
distribution adds vendored code or bundled assets, update this inventory and
carry forward every required license, copyright, and attribution notice.
