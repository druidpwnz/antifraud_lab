# Vendored front-end libraries

Copied from npm, pinned, unmodified - except the one change to `beer.min.css` below. Served by Flask from `static/` — the panel loads
nothing from a CDN, so it works offline and nothing third-party runs in an admin tool.

| Library | Version | Files | Licence |
|---|---|---|---|
| [Beer CSS](https://www.beercss.com) — Material Design 3 in plain CSS | 5.0.3 | `beercss/beer.min.css`, its shape SVGs, the Outlined and Subset icon fonts | MIT |
| [htmx](https://htmx.org) | 2.0.11 | `htmx/htmx.min.js` | 0BSD |
| [Roboto](https://github.com/googlefonts/roboto-classic), variable, via @fontsource-variable/roboto | 5.3.0 | `roboto/` — Latin, Latin-ext, Cyrillic subsets | OFL-1.1 |

**One change to `beer.min.css`, and only one.** Upstream, each icon font's
`@font-face` lists the local file and then a jsdelivr URL as a fallback. The panel's
Content-Security-Policy (`font-src 'self'`) blocks that URL - but Chromium checks every
URL in an `@font-face` rule against the CSP when it reads the stylesheet, not only
when it uses the font, so every page logged four CSP errors in the console even
though the local font loaded fine. The fallback URLs are removed with:

    sed -E -i 's#,url\(https://cdn\.jsdelivr\.net/[^)]*\) format\("woff2"\)##g' beercss/beer.min.css

Re-run it after every upgrade, then check `grep -c https:// beercss/beer.min.css` is 0.

The Rounded and Sharp icon fonts are not vendored; the panel uses Outlined only, and
the browser never downloads a font face nothing on the page uses.

To upgrade: `npm pack beercss@<version> htmx.org@<version>`, copy the same files,
change the versions here and in `templates/base.html`'s comment, and look at every page.

Roboto is vendored because Beer CSS uses whatever font the viewer has installed. It
is loaded in `../app.css` as the family "Panel Roboto" - a name no installed font can
have, so a partly installed system Roboto (one weight only) can never take over.
