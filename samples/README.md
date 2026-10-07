# Sample documents

Drop PDFs or images here. The harness picks up `.pdf`, `.png`, `.jpg`, `.jpeg`,
`.tiff`, `.tif`, `.bmp`, `.heif`, `.docx`, `.xlsx` recursively.

## Never commit customer documents

`samples/*.pdf` and the other document extensions are gitignored. Real POs and
invoices are confidential. For anything recorded, shared, or published, use
synthetic documents.

## Choosing a set that actually proves the point

The comparison is only interesting if the document set spans both ends of the
difficulty range. Aim for a folder layout like:

```
samples/
├── known/          # templates the prebuilt model handles well
│   ├── vendor-a-standard-template.pdf
│   └── top-vendor-recurring.pdf
└── unfamiliar/     # drifted and novel templates — where the two services diverge
    ├── vendor-a-revised-template.pdf   # same vendor, changed layout
    ├── vendor-b-different-structure.pdf
    └── multipage-line-items.pdf
```

Then target each set:

```bash
python src/run_demo.py compare --input samples/known
python src/run_demo.py compare --input samples/unfamiliar
```

### What makes a good "known" sample

- A template the prebuilt invoice model handles well — clear labeled fields,
  a conventional line-item table
- Establishes the baseline: **DI is faster, cheaper, and equally accurate here**

### What makes a good "unfamiliar" sample

These produce the differentiation. Best candidates, in order of impact:

1. **The same vendor's old and new template side by side.** If you can find a
   vendor who revised their invoice layout — renamed a header, moved the totals
   block, added a column — that pair is the single most valuable sample you can
   bring. It proves the problem is ordinary template churn, not exotic documents.
2. **A structurally different vendor template** — multi-column header, values
   without adjacent labels, or line items grouped under section sub-headers
   instead of one flat table.
3. **A layout where the PO number appears in body text** rather than a labeled
   header field.
4. **Multi-page line-item tables** with continuation rows.
5. **Scanned or photographed** rather than born-digital.

Language variation is worth including if you have it, but it is **not** the
primary driver — layout and template variation is. Don't let a translated
invoice distract from the template-drift story.

## Generating synthetic samples

If you can't use customer documents, build synthetic ones that reproduce the same
*structural* challenges — the goal is layout and language novelty, not realistic
vendor names. Word or Excel exported to PDF is sufficient; the point is that the
layout is outside the prebuilt model's training distribution.

## No documents yet?

You are not blocked. Run the built-in fixtures:

```bash
python src/run_demo.py simulate
```

That renders the full comparison — including the template-drift scenario where
the same vendor's revised layout silently corrupts DI's totals — with no Azure
calls and no documents. Every output is stamped `SIMULATED`.
