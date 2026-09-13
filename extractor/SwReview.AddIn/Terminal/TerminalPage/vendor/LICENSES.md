# Vendored terminal assets

The terminal page loads these files from disk with plain `<script src>` / `<link rel>`
tags. There is **no CDN reference anywhere** (plan.md: "Vendored, MIT: xterm.js and its fit
addon (pinned versions, no CDN)"), and the page's CSP is `script-src 'self'; style-src
'self'`, so a remote origin could not load even if one were added by mistake.

The three files are the published `lib/` (UMD) and `css/` artifacts, taken byte-for-byte from the npm
tarballs - `npm pack @xterm/xterm@6.0.0 @xterm/addon-fit@0.11.0` - with no build step and
no local edits. Source maps and TypeScript sources are deliberately not vendored: they are
not loaded at runtime and would ship megabytes next to the add-in DLL. The bundles keep
their trailing `//# sourceMappingURL=` comment so the files stay byte-identical to the
published artifacts; the missing `.map` costs a 404 in DevTools and nothing at runtime.

To refresh, bump the version below, re-run `npm pack`, copy the same three files, and
update the digests.

| File | Package | Version | License | SHA-256 |
|------|---------|---------|---------|---------|
| `xterm.js` | `@xterm/xterm` (`lib/xterm.js`) | 6.0.0 | MIT | `14903579ff54664cd72f8e8699e6961a6272c21863ec1c3b118cdc8af5d4a972` |
| `xterm.css` | `@xterm/xterm` (`css/xterm.css`) | 6.0.0 | MIT | `854a7c0fb70e8b1a083c16797ab827299fb18744f5ad34f227b48337e33293c6` |
| `addon-fit.js` | `@xterm/addon-fit` (`lib/addon-fit.js`) | 0.11.0 | MIT | `ba3ea256ce0620a0992a197d6c9baea64823fc93d8da07a9e366ca9943c18527` |

## @xterm/xterm 6.0.0 - MIT

```
Copyright (c) 2017-2019, The xterm.js authors (https://github.com/xtermjs/xterm.js)
Copyright (c) 2014-2016, SourceLair Private Company (https://www.sourcelair.com)
Copyright (c) 2012-2013, Christopher Jeffrey (https://github.com/chjj/)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## @xterm/addon-fit 0.11.0 - MIT

```
Copyright (c) 2019, The xterm.js authors (https://github.com/xtermjs/xterm.js)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```
