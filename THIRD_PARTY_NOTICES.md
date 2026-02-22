# Third-Party Notices

This project includes and depends on third-party open-source software.

## Bundled Frontend Assets (Redistributed in-repo)

- **MathJax** (`static/vendor/mathjax`) — Apache-2.0  
  License file: `static/vendor/mathjax/LICENSE`
- **marked** (`static/vendor/marked.min.js`) — MIT  
  License header is embedded at the top of the vendored file.
- **DOMPurify** (`static/vendor/dompurify.min.js`) — MPL-2.0 OR Apache-2.0

## Frontend Build Dependencies

- **tailwindcss** (`package.json`) — MIT
- **@tailwindcss/typography** (`package.json`) — MIT

## Python Dependencies

Python package dependencies are managed via:

- `docker/pyproject.toml`
- `docker/uv.lock`

## Full Dependency Inventories

For complete dependency trees and resolved versions, see:

- `package-lock.json` (Node/npm)
- `docker/uv.lock` (Python/uv)

