# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

Fixes are released from the latest version. There are no long-term support
branches.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Report it privately through GitHub: go to the
[Security tab](https://github.com/proteomics-ukj/ProteomicsCoPYlot/security/advisories/new)
and choose "Report a vulnerability". That opens a private advisory visible only
to the maintainers.

Please include:

- what an attacker can do, and what they need in order to do it;
- the steps to reproduce it, with the smallest example that works;
- the version or commit you tested, and how the application was deployed
  (local, Docker, viewer mode, viewer-portal mode).

You can expect an acknowledgement within a week and an assessment within two.
If a report is accepted, you will be credited in the advisory and the release
notes unless you ask otherwise.

## Scope

In scope: the FastAPI backend, the React frontend, the `proteomicscopylot`
package, the Docker images, and the read-only viewer and password-gated
viewer-portal modes, in particular anything that lets a viewer reach data,
files or endpoints outside the project they were given.

Out of scope:

- Anything that requires an attacker to already have write access to the machine
  running the application, or to the configuration and data files it is pointed
  at.
- The AI features when configured against a third-party provider. What you send
  to a cloud provider is governed by that provider's terms; the relevant issue
  here would be the application sending data you did not ask it to send.
- Vulnerabilities in dependencies with no exploitable path through this
  application. Dependencies are audited on a schedule (`pip-audit`, `npm audit`)
  and updated by Dependabot.

## A note on the deployment model

Proteomics CoPYlot is a research tool that is usually run locally against your
own data. The backend trusts the machine it runs on, and the local mode has no
authentication by design. Do not expose the analysis application to a network
you do not control. For sharing results with collaborators, use viewer mode or
the viewer portal, which are read-only and are the surfaces this policy treats
as security-relevant.
