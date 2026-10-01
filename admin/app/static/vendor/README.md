# Vendored front-end libraries

Copied from npm, pinned, unmodified. Served by Flask from `static/` — the panel loads
nothing from a CDN, so it works offline and nothing third-party runs in an admin tool.

| Library | Version | Files | Licence |
|---|---|---|---|
| [Beer CSS](https://www.beercss.com) — Material Design 3 in plain CSS | 5.0.3 | `beercss/beer.min.css`, its shape SVGs, the Outlined and Subset icon fonts | MIT |
| [htmx](https://htmx.org) | 2.0.11 | `htmx/htmx.min.js` | 0BSD |
| [Roboto](https://github.com/googlefonts/roboto-classic), variable, via @fontsource-variable/roboto | 5.3.0 | `roboto/` — Latin, Latin-ext, Cyrillic subsets | OFL-1.1 |

`beer.min.css` lists each icon font twice: the local file first, a jsdelivr URL as a
fallback. Only the local one is ever used: the panel's Content-Security-Policy has
`font-src 'self'`, which blocks the CDN fallback outright. The Rounded and Sharp icon
fonts are not vendored; the panel uses Outlined only.

To upgrade: `npm pack beercss@<version> htmx.org@<version>`, copy the same files,
change the versions here and in `templates/base.html`'s comment, and look at every page.

Roboto is vendored because Beer CSS uses whatever font the viewer has installed. It
is loaded in `../app.css` as the family "Panel Roboto" - a name no installed font can
have, so a partly installed system Roboto (one weight only) can never take over.
